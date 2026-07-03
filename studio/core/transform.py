"""Polar → Kartesisch mit Elevations-Offset-Kalibrierung.

Geometrie-Konvention (identisch zur meta.json des Scanners):
    Elevation 0° = direkt nach oben (Z+), 90° = horizontal vorwärts
    Azimut     = Drehung um die Stehachse (Z)
    rechtshändig: X = rechts, Y = vorne (bei az=0), Z = oben
    Ursprung   = Schnittpunkt Drehachse / LiDAR-Scanebene

    r = distance / 1000                  [m]
    z = r · cos(el + el_offset)
    h = r · sin(el + el_offset)          Horizontalabstand
    x = h · sin(az)
    y = h · cos(az)

``el_offset`` korrigiert eine Verdrehung der LiDAR-Montage: Zeigt der
native 0°-Winkel des Sensors nicht exakt nach oben, kippt die gesamte
Wolke — der Offset dreht das zurück (Kalibrierwert des Aufbaus).
"""

from __future__ import annotations

import numpy as np

from .cloud import PointCloud
from .rawscan import RawScan


def polar_to_cartesian(raw: RawScan, el_offset_deg: float = 0.0) -> PointCloud:
    """Rechnet einen RawScan in eine kartesische Punktwolke um."""
    r = raw.distance_mm.astype(np.float64) / 1000.0
    el = np.radians(raw.elevation_deg.astype(np.float64) + el_offset_deg)
    az = np.radians(raw.azimuth_deg.astype(np.float64))

    z = r * np.cos(el)
    h = r * np.sin(el)
    x = h * np.sin(az)
    y = h * np.cos(az)

    return PointCloud(
        xyz=np.column_stack((x, y, z)).astype(np.float32),
        intensity=raw.intensity,
        scanner_dist=r.astype(np.float32),
        meta={
            "scan_name": raw.name,
            "el_offset_deg": el_offset_deg,
            "source": str(raw.path),
        },
    )
