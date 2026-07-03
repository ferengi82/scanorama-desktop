"""Punktwolken-Modell des Studios.

Bewusst schlank: parallele numpy-Arrays statt Objekt-pro-Punkt.
``xyz`` ist float32 (Speicher: 4 Mio. Punkte ≈ 48 MB) — für
Open3D-Algorithmen wird bei Bedarf nach float64 konvertiert.

Felder pro Punkt:
    xyz          (N,3) float32   Meter, Koordinatensystem siehe DATAFORMAT
    intensity    (N,)  uint8     Rückstrahlstärke des Scanners
    scanner_dist (N,)  float32   Original-Distanz zum Scanner (für
                                 distanzgewichtete Fusion, STL27L-Fehlermodell)
    station      (N,)  uint16    Standpunkt-Index (0 bei Einzelscan;
                                 nach Fusion: Herkunft jedes Punkts)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class PointCloud:
    xyz: np.ndarray                       # (N,3) float32
    intensity: np.ndarray                 # (N,)  uint8
    scanner_dist: np.ndarray              # (N,)  float32
    station: np.ndarray | None = None     # (N,)  uint16, lazy erzeugt
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        self.xyz = np.ascontiguousarray(self.xyz, dtype=np.float32)
        self.intensity = np.asarray(self.intensity, dtype=np.uint8)
        self.scanner_dist = np.asarray(self.scanner_dist, dtype=np.float32)
        n = len(self.xyz)
        if len(self.intensity) != n or len(self.scanner_dist) != n:
            raise ValueError("Alle Punkt-Arrays müssen gleich lang sein")
        if self.station is None:
            self.station = np.zeros(n, dtype=np.uint16)
        else:
            self.station = np.asarray(self.station, dtype=np.uint16)
            if len(self.station) != n:
                raise ValueError("station-Array hat falsche Länge")

    def __len__(self) -> int:
        return len(self.xyz)

    def subset(self, mask: np.ndarray) -> "PointCloud":
        """Neue Wolke mit den Punkten, für die ``mask`` True ist."""
        return PointCloud(
            xyz=self.xyz[mask],
            intensity=self.intensity[mask],
            scanner_dist=self.scanner_dist[mask],
            station=self.station[mask],
            meta=dict(self.meta),
        )

    def transformed(self, T: np.ndarray) -> "PointCloud":
        """Neue Wolke, mit 4×4-Matrix ``T`` transformiert (Punkte → global)."""
        T = np.asarray(T, dtype=np.float64)
        if T.shape != (4, 4):
            raise ValueError(f"Erwarte 4x4-Transformation, bekam {T.shape}")
        xyz = self.xyz.astype(np.float64) @ T[:3, :3].T + T[:3, 3]
        return PointCloud(
            xyz=xyz.astype(np.float32),
            intensity=self.intensity.copy(),
            scanner_dist=self.scanner_dist.copy(),
            station=self.station.copy(),
            meta=dict(self.meta),
        )

    def to_open3d(self):
        """Konvertiert nach open3d.geometry.PointCloud (float64, nur XYZ)."""
        import open3d as o3d
        pc = o3d.geometry.PointCloud()
        pc.points = o3d.utility.Vector3dVector(self.xyz.astype(np.float64))
        return pc

    @staticmethod
    def concat(clouds: list["PointCloud"]) -> "PointCloud":
        """Hängt mehrere Wolken aneinander (station bleibt erhalten)."""
        if not clouds:
            raise ValueError("Keine Wolken zum Zusammenfügen")
        return PointCloud(
            xyz=np.vstack([c.xyz for c in clouds]),
            intensity=np.concatenate([c.intensity for c in clouds]),
            scanner_dist=np.concatenate([c.scanner_dist for c in clouds]),
            station=np.concatenate([c.station for c in clouds]),
            meta={"concat_of": [c.meta.get("scan_name", "?") for c in clouds]},
        )
