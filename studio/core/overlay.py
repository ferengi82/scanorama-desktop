"""Foto-Overlay: Wolken-Reprojektion aus einer Kamerapose + Auto-Fit.

Grundlage des Foto-Overlay-Prüfers: Die Punktwolke wird aus der
Kamerapose eines Fotos gerendert (Intensitäts-Graubild) und mit dem
echten Foto überblendet — Abweichungen der Einbauwerte (az_offset/
pitch/roll) sind sofort sichtbar. Der Auto-Fit optimiert die drei
Winkel per Pattern-Search auf der Gradienten-Korrelation
(bewährtes Verfahren der Mount-Kalibrierung vom 2026-07-05).
"""

from __future__ import annotations

import logging

import numpy as np

from .cloud import PointCloud
from .colorize import _project
from .photos import PhotoPose, compute_pose

log = logging.getLogger(__name__)


def pose_from_mount(mount: dict, azimuth_deg: float) -> PhotoPose:
    """PhotoPose aus Mount-Werten + Plattform-Azimut (Plattform-Frame)."""
    x, y, z, yaw, pitch, roll = compute_pose(azimuth_deg, mount)
    return PhotoPose(label="", source=None, cam_id="",
                     azimuth_deg=azimuth_deg,
                     x=x, y=y, z=z, yaw=yaw, pitch=pitch, roll=roll)


def render_from_pose(cloud: PointCloud, pose: PhotoPose,
                     floor_T: np.ndarray | None,
                     scale: int = 8) -> np.ndarray:
    """Intensitäts-Render der Wolke aus Kamerasicht, (H/scale, W/scale)."""
    from .photos import SENSOR_H_PX, SENSOR_W_PX

    w, h = SENSOR_W_PX // scale, SENSOR_H_PX // scale
    u, v, depth, valid = _project(cloud.xyz, pose, floor_T)
    img = np.zeros((h, w), np.uint8)
    idx = np.nonzero(valid)[0]
    if len(idx) == 0:
        return img
    idx = idx[np.argsort(depth[idx])[::-1]]     # nahe Punkte gewinnen
    px = np.clip((u[idx] / scale).astype(np.int64), 0, w - 1)
    py = np.clip((v[idx] / scale).astype(np.int64), 0, h - 1)
    g = ((cloud.intensity[idx].astype(np.float64) / 255.0) ** 0.5 * 255)
    img[py, px] = g.astype(np.uint8)
    return img


def _norm_grad(img: np.ndarray) -> np.ndarray:
    g = img.astype(np.float64)
    m = np.abs(np.diff(g, axis=1))[:-1, :] + np.abs(np.diff(g, axis=0))[:, :-1]
    m -= m.mean()
    s = m.std()
    return m / s if s > 1e-9 else m * 0


def overlay_score(cloud: PointCloud, mount: dict, azimuth_deg: float,
                  photo_gray: np.ndarray, floor_T: np.ndarray | None,
                  scale: int = 16) -> float:
    """Gradienten-Korrelation Render↔Foto (höher = besser ausgerichtet)."""
    pose = pose_from_mount(mount, azimuth_deg)
    r = _norm_grad(render_from_pose(cloud, pose, floor_T, scale))
    return float(np.mean(r * _norm_grad(photo_gray)))


def autofit(cloud: PointCloud, mount: dict,
            photos: list[tuple[float, np.ndarray]],
            floor_T: np.ndarray | None,
            max_delta_deg: float = 15.0) -> tuple[dict, float, float]:
    """Verfeinert az_offset/pitch/roll per Pattern-Search.

    Args:
        photos: Liste (azimuth_deg, foto_graubild) — 1..n Fotos der Kamera
        max_delta_deg: Suchradius um die Startwerte

    Returns:
        (mount', score_vorher, score_nachher)
    """
    def total(m: dict) -> float:
        return sum(overlay_score(cloud, m, az, g, floor_T)
                   for az, g in photos)

    keys = ("az_offset_deg", "pitch_mount_deg", "roll_mount_deg")
    m = dict(mount)
    before = current = total(m)
    step = min(4.0, max_delta_deg)
    start = {k: m[k] for k in keys}
    while step >= 0.25:
        improved = False
        for k in keys:
            for sign in (+1.0, -1.0):
                trial = dict(m)
                trial[k] = m[k] + sign * step
                if abs(trial[k] - start[k]) > max_delta_deg:
                    continue
                s = total(trial)
                if s > current + 1e-6:
                    m, current, improved = trial, s, True
                    break
        if not improved:
            step /= 2
    m["az_offset_deg"] = round(m["az_offset_deg"] % 360.0, 2)
    m["pitch_mount_deg"] = round(m["pitch_mount_deg"], 2)
    m["roll_mount_deg"] = round(m["roll_mount_deg"], 2)
    log.info(f"Auto-Fit: Score {before:.3f} → {current:.3f} "
             f"(az {m['az_offset_deg']}° pitch {m['pitch_mount_deg']}° "
             f"roll {m['roll_mount_deg']}°)")
    return m, before, current
