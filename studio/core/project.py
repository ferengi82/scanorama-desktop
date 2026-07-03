"""Projekt-Konzept: Ein Projekt = ein Aufmaß mit mehreren Standpunkten.

Ordnerstruktur (Entscheidung D5):

    MeinAufmass/
    ├── project.json      Einstellungen, Standpunkte, Posen — die Wahrheit
    ├── scans/            Original-Scan-Ordner (unverändert, nie angefasst!)
    │   ├── 2026-07-02_scan_01_001/
    │   └── 2026-07-02_scan_01_002/
    └── output/           Exporte und Registrierungs-Ergebnisse

Alles Berechnete ist aus project.json + Rohdaten reproduzierbar.
Posen (4×4, scan-lokal → Projekt-Rahmen) kommen in M4 aus der
Registrierung; bis dahin sind sie ``None``.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .pipeline import ProcessingParams
from .rawscan import is_scan_folder

log = logging.getLogger(__name__)

PROJECT_FILE = "project.json"
SCHEMA_VERSION = 1


class ProjectError(Exception):
    """Projektordner fehlt/ist beschädigt oder Operation unzulässig."""


@dataclass
class Station:
    """Ein Standpunkt im Projekt."""
    folder: str                       # Ordnername unter scans/
    enabled: bool = True              # nimmt an Registrierung/Fusion teil
    pose: list | None = None          # 4×4 als geschachtelte Liste oder None

    def pose_matrix(self) -> np.ndarray | None:
        return np.asarray(self.pose, dtype=np.float64) if self.pose else None

    def set_pose(self, T: np.ndarray | None) -> None:
        self.pose = None if T is None else np.asarray(T, dtype=np.float64).tolist()


@dataclass
class Project:
    root: Path
    name: str
    params: ProcessingParams = field(default_factory=ProcessingParams)
    stations: list[Station] = field(default_factory=list)
    created: str = ""

    # ------------------------------------------------------------------
    # Anlegen / Öffnen / Speichern
    # ------------------------------------------------------------------
    @staticmethod
    def create(root: str | Path, name: str) -> "Project":
        """Legt einen neuen Projektordner an (muss leer/neu sein)."""
        root = Path(root)
        if (root / PROJECT_FILE).exists():
            raise ProjectError(f"{root} enthält bereits ein Projekt")
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise ProjectError(f"{root} ist nicht leer")
        (root / "scans").mkdir()
        (root / "output").mkdir()
        project = Project(root=root, name=name,
                          created=datetime.now().astimezone().isoformat())
        project.save()
        log.info(f"Projekt angelegt: {root} ({name})")
        return project

    @staticmethod
    def open(root: str | Path) -> "Project":
        root = Path(root)
        path = root / PROJECT_FILE
        if not path.exists():
            raise ProjectError(f"Kein Projekt: {path} fehlt")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ProjectError(f"{path} unlesbar: {e}") from e
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ProjectError(
                f"Unbekannte Projektversion {data.get('schema_version')!r}")
        project = Project(
            root=root,
            name=data.get("name", root.name),
            params=ProcessingParams.from_dict(data.get("params", {})),
            stations=[Station(**s) for s in data.get("stations", [])],
            created=data.get("created", ""),
        )
        # Verwaiste Einträge melden (Scan-Ordner von Hand gelöscht?)
        for s in project.stations:
            if not (project.scans_dir / s.folder).exists():
                log.warning(f"Standpunkt fehlt auf der Platte: {s.folder}")
        log.info(f"Projekt geöffnet: {root} "
                 f"({len(project.stations)} Standpunkte)")
        return project

    def save(self) -> None:
        data = {
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "created": self.created,
            "params": self.params.to_dict(),
            "stations": [
                {"folder": s.folder, "enabled": s.enabled, "pose": s.pose}
                for s in self.stations
            ],
        }
        path = self.root / PROJECT_FILE
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(path)   # atomar — halbe project.json gibt es nie

    # ------------------------------------------------------------------
    # Pfade
    # ------------------------------------------------------------------
    @property
    def scans_dir(self) -> Path:
        return self.root / "scans"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    def station_path(self, station: Station) -> Path:
        return self.scans_dir / station.folder

    def get_station(self, folder: str) -> Station:
        for s in self.stations:
            if s.folder == folder:
                return s
        raise ProjectError(f"Unbekannter Standpunkt: {folder}")

    # ------------------------------------------------------------------
    # Standpunkte verwalten
    # ------------------------------------------------------------------
    def import_scan(self, source: str | Path) -> Station:
        """Kopiert einen Scan-Ordner ins Projekt und registriert ihn.

        Der Quellordner bleibt unangetastet (USB-Stick, Netzlaufwerk, …).
        """
        source = Path(source)
        if not is_scan_folder(source):
            raise ProjectError(f"Kein Scanorama-Scan: {source}")
        target = self.scans_dir / source.name
        if target.exists():
            raise ProjectError(f"Standpunkt existiert bereits: {source.name}")
        log.info(f"Importiere {source} → {target} …")
        shutil.copytree(source, target)
        station = Station(folder=source.name)
        self.stations.append(station)
        self.save()
        return station

    def remove_station(self, folder: str, delete_files: bool = False) -> None:
        station = self.get_station(folder)
        self.stations.remove(station)
        if delete_files:
            shutil.rmtree(self.station_path(station), ignore_errors=True)
        self.save()
        log.info(f"Standpunkt entfernt: {folder}"
                 f"{' (Dateien gelöscht)' if delete_files else ''}")
