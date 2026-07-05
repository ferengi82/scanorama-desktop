"""Punktwolken-Einfärbung aus der Fotorunde.

Jeder Punkt wird per Pinhole-Projektion in alle Fotos abgebildet und
bekommt eine gewichtete Mischfarbe aus allen Fotos, die ihn sehen:

  (a) Belichtungs-/Weißabgleich zwischen den Kameras — feste Gains je
      Kamera und Kanal, aus den Überlappungsbereichen benachbarter
      Kameras geschätzt (Brown-Lowe-Ausgleich, :func:`_estimate_gains`).
  (b) Weiche Mischung statt harter Umschaltung — jedes Foto trägt mit
      einem Feather-Gewicht bei (1 in Bildmitte, weich auf 0 zum Rand,
      :func:`_feather_weight`); gemischt wird in Linearlicht.
  (c) Verdeckung per Z-Buffer mit Splat (:func:`_occlusion_mask`):
      Punkte deutlich hinter dem nächstliegenden Punkt derselben
      Blickrichtung bekommen aus diesem Foto keine Farbe; das Splatten
      schließt Löcher dünner Vordergrundflächen.

Damit feste Gains je Kamera zulässig sind, müssen AE/AWB pro Kamera über
die ganze Fotorunde gelockt sein (siehe usb_camera_controller).

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
from .photos import (CX_PX, CY_PX, FOCAL_PX, SENSOR_H_PX, SENSOR_W_PX,
                     PhotoPose, yaw_pitch_roll_to_matrix)

log = logging.getLogger(__name__)

ZBUF_DOWNSCALE = 8         # Z-Buffer-Raster: Sensor / 8 ≈ 408×306 (feiner)
ZBUF_TOL_M = 0.10          # Punkte > 10 cm hinter dem Minimum: verdeckt
ZBUF_SPLAT = 1             # nahe Punkte in ±1 Zelle splatten (Löcher schließen)
MIN_DEPTH_M = 0.15         # näher als 15 cm vor der Linse: unglaubwürdig
IMG_SCALE = 4              # JPEGs aufs 1/4 verkleinert laden (Speed/RAM)

FEATHER_EXP = 2.0          # (b) Randabfall des Blend-Gewichts: (1-r)^EXP
FEATHER_FLOOR = 1e-3       # Mindestgewicht, damit Randpunkte Farbe behalten
GAIN_PRIOR = 1.0           # (a) Regularisierung: zieht Gains → 1
GAIN_CLAMP = (0.5, 2.0)    # (a) plausibler Gain-Bereich pro Kamera/Kanal
MIN_OVERLAP = 50           # (a) so viele gemeinsame Punkte nötig, um zu trauen


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    """sRGB [0..1] → Linearlicht [0..1] (Standard-Transferfunktion)."""
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c: np.ndarray) -> np.ndarray:
    """Linearlicht [0..1] → sRGB [0..1] (Umkehrung von _srgb_to_linear)."""
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def _feather_weight(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """(b) Blend-Gewicht: 1 in Bildmitte, weich auf 0 zum Rand (Feather).

    r = normierter Abstand zum Bildzentrum (Ellipse); (1-r)^EXP, auf 0
    geklemmt. So dominiert das Foto, in dem ein Punkt zentral liegt, und
    an den Bildrändern blenden überlappende Fotos weich ineinander.
    """
    du = (u - SENSOR_W_PX / 2.0) / (SENSOR_W_PX / 2.0)
    dv = (v - SENSOR_H_PX / 2.0) / (SENSOR_H_PX / 2.0)
    r = np.hypot(du, dv)
    return np.clip(1.0 - r, 0.0, 1.0) ** FEATHER_EXP


def _occlusion_mask(u: np.ndarray, v: np.ndarray,
                    depth: np.ndarray) -> np.ndarray:
    """(c) Verdeckung per Z-Buffer mit Splat.

    Pro Rasterzelle (Sensor/ZBUF_DOWNSCALE) wird das Tiefen-Minimum
    gehalten; jeder Punkt splattet seine Tiefe zusätzlich in die ±SPLAT-
    Nachbarzellen, damit Vordergrundflächen mit Lücken keine Hintergrund-
    punkte durchscheinen lassen. Sichtbar = höchstens ZBUF_TOL_M hinter
    dem Minimum der eigenen Zelle.
    """
    zw = SENSOR_W_PX // ZBUF_DOWNSCALE
    zh = SENSOR_H_PX // ZBUF_DOWNSCALE
    zu = np.clip((u / ZBUF_DOWNSCALE).astype(np.int64), 0, zw - 1)
    zv = np.clip((v / ZBUF_DOWNSCALE).astype(np.int64), 0, zh - 1)
    zbuf = np.full(zw * zh, np.inf, dtype=np.float64)
    for dv in range(-ZBUF_SPLAT, ZBUF_SPLAT + 1):
        for du in range(-ZBUF_SPLAT, ZBUF_SPLAT + 1):
            cu = np.clip(zu + du, 0, zw - 1)
            cv = np.clip(zv + dv, 0, zh - 1)
            np.minimum.at(zbuf, cv * zw + cu, depth)
    return depth <= zbuf[zv * zw + zu] + ZBUF_TOL_M


def _estimate_gains(cam_colors: list[np.ndarray],
                    cam_weights: list[np.ndarray],
                    prior: float = GAIN_PRIOR) -> np.ndarray:
    """(a) Gain-Ausgleich pro Kamera/Kanal aus Überlappungsbereichen.

    Brown-Lowe-Ansatz: minimiere die Farbdifferenz zwischen Kameras für
    Punkte, die zwei Kameras gemeinsam sehen, mit einem Prior, der die
    Gains gegen 1 zieht (Stabilität bei wenig Overlap). Da AE/AWB pro
    Kamera über die ganze Fotorunde gelockt sind, genügt ein fester Gain
    je Kamera und Kanal.

    Args:
        cam_colors: je Kamera (N,3)-Linearfarbe des besten Treffers
        cam_weights: je Kamera (N,) Blend-Gewicht (>0 = gesehen)

    Returns:
        gains (ncam,3), geklemmt auf GAIN_CLAMP.
    """
    ncam = len(cam_colors)
    seen = [w > 0 for w in cam_weights]
    gains = np.ones((ncam, 3), dtype=np.float64)
    for ch in range(3):
        A = np.zeros((ncam, ncam), dtype=np.float64)
        b = np.zeros(ncam, dtype=np.float64)
        for k in range(ncam):
            A[k, k] += prior
            b[k] += prior
        for i in range(ncam):
            for j in range(i + 1, ncam):
                ov = seen[i] & seen[j]
                nij = int(ov.sum())
                if nij < MIN_OVERLAP:
                    continue
                ii = float(cam_colors[i][ov, ch].mean())
                ij = float(cam_colors[j][ov, ch].mean())
                A[i, i] += nij * ii * ii
                A[j, j] += nij * ij * ij
                A[i, j] -= nij * ii * ij
                A[j, i] -= nij * ii * ij
        g = np.linalg.solve(A, b)
        gains[:, ch] = np.clip(g, *GAIN_CLAMP)
    return gains


def _blend(cam_colors: list[np.ndarray], cam_weights: list[np.ndarray],
           gains: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(b) Gewichtete Farbmischung über alle Kameras in Linearlicht.

    Returns:
        (rgb (N,3) uint8, colored (N,) bool) — colored=False, wo kein Foto
        beitrug (Gesamtgewicht 0).
    """
    n = cam_colors[0].shape[0]
    num = np.zeros((n, 3), dtype=np.float64)
    den = np.zeros(n, dtype=np.float64)
    for c in range(len(cam_colors)):
        w = cam_weights[c]
        num += (w[:, None] * gains[c][None, :]) * cam_colors[c]
        den += w
    colored = den > 0
    rgb = np.zeros((n, 3), dtype=np.uint8)
    lin = num[colored] / den[colored, None]
    rgb[colored] = np.clip(_linear_to_srgb(lin) * 255.0 + 0.5, 0, 255)
    return rgb, colored


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
        u = CX_PX + FOCAL_PX * x / y
        v = CY_PX - FOCAL_PX * z / y
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

    # Kameras indizieren (feste Gains pro Kamera, nicht pro Foto)
    cam_ids: list[str] = []
    for pose in poses:
        if pose.cam_id not in cam_ids:
            cam_ids.append(pose.cam_id)
    ncam = len(cam_ids)
    if ncam == 0:
        return rgb, 0
    cam_color = [np.zeros((n, 3), dtype=np.float32) for _ in range(ncam)]
    cam_weight = [np.zeros(n, dtype=np.float32) for _ in range(ncam)]

    # --- Phase 1: Sampeln (Verdeckung + Feather-Gewicht je Kamera) -------
    for pose in poses:
        img = _load_image(pose.source)
        if img is None:
            continue
        ci = cam_ids.index(pose.cam_id)
        u, v, depth, valid = _project(xyz, pose, floor_T)
        if not valid.any():
            continue
        idx = np.nonzero(valid)[0]
        ui, vi, di = u[idx], v[idx], depth[idx]

        visible = _occlusion_mask(ui, vi, di)          # (c)
        if not visible.any():
            continue
        idx, ui, vi = idx[visible], ui[visible], vi[visible]

        w = np.maximum(_feather_weight(ui, vi), FEATHER_FLOOR)  # (b)
        better = w > cam_weight[ci][idx]               # stärksten Treffer je Kamera
        if not better.any():
            continue
        idx, ui, vi, w = idx[better], ui[better], vi[better], w[better]

        h, wpx = img.shape[:2]
        px = np.clip((ui / IMG_SCALE).astype(np.int64), 0, wpx - 1)
        py = np.clip((vi / IMG_SCALE).astype(np.int64), 0, h - 1)
        cam_color[ci][idx] = _srgb_to_linear(img[py, px] / 255.0)
        cam_weight[ci][idx] = w

    # --- Phase 2: Gain-Ausgleich aus Überlappungen (a) -------------------
    gains = _estimate_gains(cam_color, cam_weight)

    # --- Phase 3: Gewichtete Mischung in Linearlicht (b) -----------------
    blended, colored = _blend(cam_color, cam_weight, gains)
    rgb[colored] = blended[colored]

    n_col = int(colored.sum())
    log.info(f"Einfärbung: {n_col:,} von {n:,} Punkten "
             f"({n_col / max(n, 1) * 100:.1f}%) aus {len(poses)} Fotos, "
             f"{ncam} Kameras, Gains {np.round(gains.mean(axis=1), 3).tolist()}")
    return rgb, n_col
