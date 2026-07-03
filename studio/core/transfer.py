"""Scan-Transfer vom Raspberry Pi über SSH/SFTP (paramiko).

Läuft ohne externe Tools auch unter Windows. Der Pi braucht nur einen
laufenden SSH-Dienst und den öffentlichen Schlüssel des Auswerte-PCs
in ``~/.ssh/authorized_keys`` (siehe docs/SETUP).

Sicherheit: Host-Keys werden beim ersten Kontakt akzeptiert und in der
known_hosts-Datei des Systems gespeichert (Heimnetz-Szenario).
"""

from __future__ import annotations

import logging
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# Dateien, die einen vollständigen Roh-Scan ausmachen
RAW_FILES = ("lidar_raw.bin", "lidar_index.npz", "motor_timeline.csv",
             "meta.json")


class TransferError(Exception):
    """Verbindungs- oder Übertragungsfehler."""


@dataclass
class RemoteConfig:
    host: str = ""
    user: str = "pi"
    port: int = 22
    key_path: str = ""            # leer = Standard-Keys/Agent
    password: str = ""            # Alternative zu Schlüsseln (nicht persistiert!)
    scans_dir: str = "scans"      # relativ zum Home des Users


@dataclass
class RemoteScan:
    name: str
    size_bytes: int
    mtime: float
    complete: bool                # alle Rohdaten-Dateien vorhanden
    files: list[str] = field(default_factory=list)

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1e6


class PiTransfer:
    """SFTP-Verbindung zum Scanner-Pi: Scans auflisten und holen."""

    def __init__(self, config: RemoteConfig):
        self.config = config
        self._client = None
        self._sftp = None

    # ------------------------------------------------------------------
    def connect(self) -> None:
        import paramiko

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=self.config.host,
                port=self.config.port,
                username=self.config.user,
                key_filename=self.config.key_path or None,
                password=self.config.password or None,
                timeout=10,
                allow_agent=True,
                look_for_keys=True,
            )
        except Exception as e:
            hint = ""
            if "No authentication methods" in str(e):
                hint = (" — kein SSH-Schlüssel gefunden: bitte Passwort "
                        "eingeben oder Schlüsseldatei angeben.")
            raise TransferError(f"Verbindung zu {self.config.user}@"
                                f"{self.config.host} fehlgeschlagen: {e}{hint}") from e
        self._client = client
        self._sftp = client.open_sftp()
        log.info(f"Verbunden: {self.config.user}@{self.config.host}")

    def close(self) -> None:
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "PiTransfer":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    def _remote_scans_path(self) -> str:
        d = self.config.scans_dir
        if d.startswith(("/", "~")):
            return d.replace("~", ".", 1) if d.startswith("~/") else d
        return d   # relativ zum Home (SFTP-Startverzeichnis)

    def list_scans(self) -> list[RemoteScan]:
        """Listet Scan-Ordner auf dem Pi (neueste zuerst)."""
        if self._sftp is None:
            raise TransferError("Nicht verbunden")
        base = self._remote_scans_path()
        try:
            entries = self._sftp.listdir_attr(base)
        except FileNotFoundError:
            raise TransferError(f"Ordner fehlt auf dem Gerät: {base}")

        scans = []
        for e in entries:
            if not stat.S_ISDIR(e.st_mode):
                continue
            folder = f"{base}/{e.filename}"
            try:
                files = self._sftp.listdir_attr(folder)
            except OSError:
                continue
            names = [f.filename for f in files]
            size = sum(f.st_size or 0 for f in files)
            complete = all(r in names for r in RAW_FILES)
            scans.append(RemoteScan(
                name=e.filename, size_bytes=size,
                mtime=float(e.st_mtime or 0),
                complete=complete, files=names,
            ))
        scans.sort(key=lambda s: s.mtime, reverse=True)
        log.info(f"{len(scans)} Scan(s) auf dem Gerät gefunden")
        return scans

    def download(self, scan_name: str, target_dir: str | Path,
                 progress: Callable[[int, int], None] | None = None) -> Path:
        """Lädt einen Scan-Ordner herunter.

        Args:
            scan_name: Ordnername auf dem Pi
            target_dir: lokales Zielverzeichnis (Scan wird Unterordner)
            progress: Callback (übertragene Bytes, Gesamtbytes)

        Returns:
            Pfad des lokalen Scan-Ordners
        """
        if self._sftp is None:
            raise TransferError("Nicht verbunden")
        remote = f"{self._remote_scans_path()}/{scan_name}"
        target = Path(target_dir) / scan_name
        if target.exists():
            raise TransferError(f"Ziel existiert bereits: {target}")
        target.mkdir(parents=True)

        # Rekursiv alle Dateien einsammeln (Scan-Ordner enthalten
        # Unterordner, z.B. photos/ mit der Fotorunde).
        files: list[tuple[str, str, int]] = []   # (remote, relativ, größe)

        def walk(remote_dir: str, rel: str) -> None:
            for e in self._sftp.listdir_attr(remote_dir):
                r = f"{remote_dir}/{e.filename}"
                p = f"{rel}/{e.filename}" if rel else e.filename
                if stat.S_ISDIR(e.st_mode):
                    walk(r, p)
                elif stat.S_ISREG(e.st_mode):
                    files.append((r, p, e.st_size or 0))

        walk(remote, "")
        total = sum(size for _, _, size in files)
        done = 0
        log.info(f"Lade {scan_name} ({total / 1e6:.1f} MB, "
                 f"{len(files)} Dateien) …")
        try:
            for remote_file, rel, size in files:
                local = target / rel
                local.parent.mkdir(parents=True, exist_ok=True)

                def cb(transferred, _total, base=done):
                    if progress:
                        progress(base + transferred, total)
                self._sftp.get(remote_file, str(local), callback=cb)
                done += size
        except Exception as e:
            raise TransferError(f"Übertragung abgebrochen: {e}") from e
        log.info(f"Fertig: {target}")
        return target
