"""Scan-Ordner des Scanners lesen (Format: DATAFORMAT.md im Scanner-Repo).

Bevorzugt wird die dekodierte Punkttabelle ``points.npz`` gelesen.
Fehlt sie (oder ist ``force_decode`` gesetzt), wird sie aus den
Master-Rohdaten (``lidar_raw.bin`` + Index + Motor-Zeitleiste) über das
scanorama-Paket neu erzeugt — dieselbe Implementierung wie auf dem Pi,
das Format existiert genau einmal (Entscheidung D1).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

REQUIRED_RAW_FILES = ("lidar_raw.bin", "lidar_index.npz", "motor_timeline.csv")


class ScanFolderError(Exception):
    """Ordner ist kein (vollständiger) Scanorama-Scan."""


@dataclass
class RawScan:
    """Polare Rohpunkte eines Standpunkts + Metadaten."""
    path: Path
    name: str
    elevation_deg: np.ndarray   # (N,) float32, 0° = oben
    azimuth_deg: np.ndarray     # (N,) float32, Plattform-Drehung
    distance_mm: np.ndarray     # (N,) uint16
    intensity: np.ndarray       # (N,) uint8
    t_ns: np.ndarray            # (N,) int64, Host-Zeit (monotonic)
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.distance_mm)


def is_scan_folder(path: str | Path) -> bool:
    """True, wenn der Ordner wie ein Scanorama-Scan aussieht."""
    p = Path(path)
    return p.is_dir() and (
        (p / "points.npz").exists()
        or all((p / f).exists() for f in REQUIRED_RAW_FILES)
    )


def find_scan_folders(root: str | Path) -> list[Path]:
    """Sucht Scan-Ordner direkt unter ``root`` (und ``root`` selbst)."""
    root = Path(root)
    result = []
    if is_scan_folder(root):
        result.append(root)
    if root.is_dir():
        result.extend(sorted(p for p in root.iterdir() if is_scan_folder(p)))
    return result


def load_scan(path: str | Path, force_decode: bool = False) -> RawScan:
    """Lädt einen Scan-Ordner als :class:`RawScan`.

    Args:
        path: Scan-Ordner (``yyyy-mm-dd_scan_XX_NNN/``)
        force_decode: points.npz ignorieren und aus den Rohdaten neu
            dekodieren (schreibt points.npz in den Ordner!)

    Raises:
        ScanFolderError: wenn der Ordner unvollständig/unlesbar ist
    """
    p = Path(path)
    if not p.is_dir():
        raise ScanFolderError(f"Kein Ordner: {p}")

    meta: dict = {}
    meta_path = p / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning(f"meta.json unlesbar ({e}) — fahre ohne Metadaten fort")

    points_path = p / "points.npz"
    if force_decode or not points_path.exists():
        if not all((p / f).exists() for f in REQUIRED_RAW_FILES):
            missing = [f for f in REQUIRED_RAW_FILES if not (p / f).exists()]
            raise ScanFolderError(
                f"{p}: weder points.npz noch vollständige Rohdaten "
                f"(fehlt: {', '.join(missing)})"
            )
        log.info(f"Dekodiere Rohdaten: {p.name} …")
        from scanorama.scan.decode import decode_scan
        decode_scan(p)  # schreibt points.npz

    try:
        pts = np.load(points_path)
        raw = RawScan(
            path=p,
            name=p.name,
            elevation_deg=pts["elevation_deg"],
            azimuth_deg=pts["azimuth_deg"],
            distance_mm=pts["distance_mm"],
            intensity=pts["intensity"],
            t_ns=pts["t_ns"],
            meta=meta,
        )
    except (OSError, KeyError, ValueError) as e:
        raise ScanFolderError(f"{points_path} unlesbar: {e}") from e

    log.info(f"Scan geladen: {raw.name} ({len(raw):,} Punkte, "
             f"Azimut {raw.azimuth_deg.min():.1f}–{raw.azimuth_deg.max():.1f}°)")
    return raw
