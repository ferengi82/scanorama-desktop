"""Punktwolken-Einfärbung aus der Fotorunde.

Für jeden Punkt wird das am besten geeignete Foto gewählt (Punkt liegt
möglichst nahe der Bildmitte) und die Farbe per Pinhole-Projektion aus
dem JPEG geholt. Verdeckungen werden über einen groben Z-Buffer pro
Foto behandelt: Punkte, die deutlich hinter dem nächstliegenden Punkt
derselben Blickrichtung liegen, bekommen aus diesem Foto keine Farbe.

Kameramodell (Näherung, siehe :mod:`studio.core.photos`):
    f = 2500 px (3,5-mm-Objektiv, 1,4-µm-Pixel), Hauptpunkt = Bildmitte,
    keine Verzeichnung. Kameraachsen bei Identität: Blick +Y, rechts +X,
    oben +Z → Pixel u = cx + f·x/y, v = cy − f·z/y (Bild-v nach unten).

Die Kameraposen kommen aus der meta.json (photos[] + cameras.mounts,
:func:`studio.core.photos.load_station_photos`) und werden mit dem
floor_transform des Standpunkts in den Frame der verarbeiteten Wolke
gebracht — Punkte und Kameras leben dann im selben Koordinatensystem.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .cloud import PointCloud
from .photos import (FOCAL_PX, SENSOR_H_PX, SENSOR_W_PX, PhotoPose,
                     yaw_pitch_roll_to_matrix)

log = logging.getLogger(__name__)

ZBUF_DOWNSCALE = 16        # Z-Buffer-Raster: Sensor / 16 ≈ 204×153
ZBUF_TOL_M = 0.10          # Punkte > 10 cm hinter dem Minimum: verdeckt
MIN_DEPTH_M = 0.15         # näher als 15 cm vor der Linse: unglaubwürdig
IMG_SCALE = 4              # JPEGs aufs 1/4 verkleinert laden (Speed/RAM)


def _load_image(path: Path) -> np.ndarray | None:
    """JPEG als (H, W, 3)-uint8, auf 1/IMG_SCALE verkleinert."""
    from PIL import Image
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img = img.resize((img.width // IMG_SCALE, img.height // IMG_SCALE))
            return np.asarray(img, dtype=np.uint8)
    except Exception as e:
        log.warning(f"Foto unlesbar: {path.name} ({e})")
        return None


def _project(xyz: np.ndarray, pose: PhotoPose,
             floor_T: np.ndarray | None) -> tuple[np.ndarray, ...]:
    """Projiziert Punkte in ein Foto.

    Returns:
        (u, v, depth, valid) — Pixel (Vollauflösung), Tiefe entlang der
        Blickrichtung, valid = vor der Kamera & im Bildfeld
    """
    c = np.array([pose.x, pose.y, pose.z], dtype=np.float64)
    R = yaw_pitch_roll_to_matrix(pose.yaw, pose.pitch, pose.roll)
    if floor_T is not None:
        T = np.asarray(floor_T, dtype=np.float64)
        c = T[:3, :3] @ c + T[:3, 3]
        R = T[:3, :3] @ R

    # Welt → Kamera (R ist Kamera→Welt)
    p = (xyz.astype(np.float64) - c) @ R          # == R.T @ (p-c) pro Punkt
    x, y, z = p[:, 0], p[:, 1], p[:, 2]           # y = Blickrichtung

    with np.errstate(divide="ignore", invalid="ignore"):
        u = SENSOR_W_PX / 2 + FOCAL_PX * x / y
        v = SENSOR_H_PX / 2 - FOCAL_PX * z / y
    valid = ((y > MIN_DEPTH_M)
             & (u >= 0) & (u < SENSOR_W_PX)
             & (v >= 0) & (v < SENSOR_H_PX))
    return u, v, y, valid


def colorize_cloud(cloud: PointCloud, poses: list[PhotoPose],
                   floor_T: np.ndarray | None = None) -> tuple[np.ndarray, int]:
    """Berechnet RGB pro Punkt aus den Fotos.

    Args:
        cloud: verarbeitete Wolke des Standpunkts (nach Bodenfit!)
        poses: Fotoposen im Plattform-Frame (load_station_photos)
        floor_T: floor_transform des Standpunkts (bringt die Kameras in
            den Frame der Wolke); None = Wolke ist unausgerichtet

    Returns:
        (rgb (N,3) uint8, anzahl_eingefärbt) — nicht eingefärbte Punkte
        behalten ihren Intensitäts-Grauwert (kein schwarzes Loch).
    """
    n = len(cloud)
    xyz = cloud.xyz
    # Fallback: Grauwert aus Intensität (gleiche Gamma wie der Viewer)
    g = ((cloud.intensity.astype(np.float64) / 255.0) ** 0.6 * 255).astype(np.uint8)
    rgb = np.column_stack((g, g, g))
    best_score = np.full(n, np.inf, dtype=np.float64)
    colored = np.zeros(n, dtype=bool)

    zw = SENSOR_W_PX // ZBUF_DOWNSCALE
    zh = SENSOR_H_PX // ZBUF_DOWNSCALE

    for pose in poses:
        img = _load_image(pose.source)
        if img is None:
            continue
        u, v, depth, valid = _project(xyz, pose, floor_T)
        if not valid.any():
            continue
        idx = np.nonzero(valid)[0]
        ui, vi, di = u[idx], v[idx], depth[idx]

        # --- Z-Buffer: Tiefen-Minimum pro Rasterzelle -------------------
        zu = np.clip((ui / ZBUF_DOWNSCALE).astype(np.int64), 0, zw - 1)
        zv = np.clip((vi / ZBUF_DOWNSCALE).astype(np.int64), 0, zh - 1)
        cell = zv * zw + zu
        zbuf = np.full(zw * zh, np.inf, dtype=np.float64)
        np.minimum.at(zbuf, cell, di)
        visible = di <= zbuf[cell] + ZBUF_TOL_M
        if not visible.any():
            continue
        idx, ui, vi, di = idx[visible], ui[visible], vi[visible], di[visible]

        # --- Score: Abstand von der Bildmitte (normiert) ----------------
        score = np.hypot((ui - SENSOR_W_PX / 2) / (SENSOR_W_PX / 2),
                         (vi - SENSOR_H_PX / 2) / (SENSOR_H_PX / 2))
        better = score < best_score[idx]
        if not better.any():
            continue
        idx, ui, vi, score = idx[better], ui[better], vi[better], score[better]

        h, w = img.shape[:2]
        px = np.clip((ui / IMG_SCALE).astype(np.int64), 0, w - 1)
        py = np.clip((vi / IMG_SCALE).astype(np.int64), 0, h - 1)
        rgb[idx] = img[py, px]
        best_score[idx] = score
        colored[idx] = True

    n_col = int(colored.sum())
    log.info(f"Einfärbung: {n_col:,} von {n:,} Punkten "
             f"({n_col / max(n, 1) * 100:.1f}%) aus {len(poses)} Fotos")
    return rgb, n_col
