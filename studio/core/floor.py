"""Boden erkennen und Wolke ausrichten (Boden → Z=0).

Algorithmus (wie in Scanner-v1 bewährt):
  1. RANSAC sucht die größte Ebene in der Wolke (Open3D segment_plane).
  2. Ist die Ebene annähernd horizontal (<15° Neigung der Normale zu Z)
     und liegt sie im unteren Höhenbereich der Wolke, gilt sie als Boden.
  3. Sonst: Ebenen-Punkte entfernen und nächste Ebene suchen (max. 5).
  4. Rotation (Rodrigues), sodass die Bodennormale exakt Z+ zeigt,
     dann Z-Verschiebung, sodass der Boden bei Z=0 liegt.

Rückgabe ist die 4×4-Transformation — sie wird auch im Projekt
gespeichert, damit der Schritt reproduzierbar bleibt.
"""

from __future__ import annotations

import logging

import numpy as np

from .cloud import PointCloud

log = logging.getLogger(__name__)

MAX_TILT_DEG = 15.0     # maximale Neigung der Bodenebene
MAX_ATTEMPTS = 5        # wie viele Ebenen probiert werden
LOWER_FRACTION = 0.5    # Boden muss in der unteren Hälfte der Wolke liegen


def _rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rotationsmatrix, die Vektor a auf Vektor b dreht (Rodrigues)."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-12:
        return np.eye(3) if c > 0 else -np.eye(3)
    vx = np.array([[0, -v[2], v[1]],
                   [v[2], 0, -v[0]],
                   [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1.0 / (1.0 + c))


def detect_floor(cloud: PointCloud,
                 distance_threshold: float = 0.02) -> np.ndarray | None:
    """Findet die Bodenebene. Rückgabe: 4×4-Ausricht-Transformation oder None.

    Args:
        cloud: kartesische Punktwolke
        distance_threshold: RANSAC-Ebenendicke in Metern
    """
    if len(cloud) < 1000:
        log.warning("Zu wenige Punkte für Bodenerkennung")
        return None

    import open3d as o3d
    pc = cloud.to_open3d()
    z_min = float(cloud.xyz[:, 2].min())
    z_max = float(cloud.xyz[:, 2].max())
    z_limit = z_min + (z_max - z_min) * LOWER_FRACTION

    for attempt in range(MAX_ATTEMPTS):
        if len(pc.points) < 1000:
            break
        plane, inliers = pc.segment_plane(
            distance_threshold=distance_threshold,
            ransac_n=3, num_iterations=1000,
        )
        a, b, c, d = plane
        normal = np.array([a, b, c])
        normal /= np.linalg.norm(normal)
        if normal[2] < 0:            # Normale nach oben orientieren
            normal, d = -normal, -d

        tilt = np.degrees(np.arccos(np.clip(normal[2], -1, 1)))
        pts = np.asarray(pc.points)[inliers]
        plane_z = float(np.median(pts[:, 2]))

        if tilt <= MAX_TILT_DEG and plane_z <= z_limit:
            R = _rotation_between(normal, np.array([0.0, 0.0, 1.0]))
            # Nach der Rotation liegt der Boden bei z = Median der
            # rotierten Inlier-Punkte → dorthin verschieben.
            z_floor = float(np.median((pts @ R.T)[:, 2]))
            T = np.eye(4)
            T[:3, :3] = R
            T[2, 3] = -z_floor
            log.info(f"Boden erkannt (Versuch {attempt + 1}): "
                     f"Neigung {tilt:.2f}°, {len(inliers):,} Punkte, "
                     f"z → 0 (war {z_floor:+.3f} m)")
            return T

        log.info(f"Ebene {attempt + 1} ist kein Boden "
                 f"(Neigung {tilt:.1f}°, z={plane_z:+.2f}) — weiter …")
        pc = pc.select_by_index(inliers, invert=True)

    log.warning("Keine Bodenebene gefunden — Wolke bleibt unausgerichtet")
    return None


def align_floor(cloud: PointCloud,
                distance_threshold: float = 0.02) -> tuple[PointCloud, np.ndarray | None]:
    """Erkennt den Boden und richtet die Wolke aus (Boden → Z=0).

    Returns:
        (ausgerichtete Wolke, Transformation oder None wenn kein Boden)
    """
    T = detect_floor(cloud, distance_threshold)
    if T is None:
        return cloud, None
    return cloud.transformed(T), T
