"""Tests: Foto-Overlay-Renderer + Auto-Fit + Projekt-Mount-Override."""

import numpy as np
import pytest

from studio.core.cloud import PointCloud
from studio.core.overlay import (autofit, overlay_score, pose_from_mount,
                                 render_from_pose)
from studio.core.photos import SENSOR_H_PX, SENSOR_W_PX

MOUNT = {"r_cam_m": 0.05, "z_cam_m": -0.05, "az_offset_deg": 30.0,
         "yaw_mount_deg": 0.0, "pitch_mount_deg": 10.0,
         "roll_mount_deg": 90.0}


def _szene():
    """Sternförmige Wand rund um den Ursprung (Struktur für Gradienten)."""
    rng = np.random.default_rng(3)
    psi = rng.uniform(0, 2 * np.pi, 250_000)
    z = rng.uniform(-1.0, 1.2, len(psi))
    r = 3.0 + 0.4 * np.sin(3 * psi) + 0.2 * np.cos(5 * psi)
    xyz = np.column_stack([r * np.sin(psi), r * np.cos(psi), z])
    inten = (128 + 90 * np.sin(8 * psi) * np.cos(4 * z)).astype(np.uint8)
    return PointCloud(xyz=xyz.astype(np.float32), intensity=inten,
                      scanner_dist=np.linalg.norm(xyz, axis=1).astype(np.float32))


def test_render_from_pose():
    cloud = _szene()
    pose = pose_from_mount(MOUNT, 0.0)
    img = render_from_pose(cloud, pose, None, scale=16)
    assert img.shape == (SENSOR_H_PX // 16, SENSOR_W_PX // 16)
    assert (img > 0).mean() > 0.2      # Szene füllt das Bild


def test_autofit_findet_offset():
    """Foto = Render mit der Wahrheit; Start um 6°/3° daneben."""
    cloud = _szene()
    fotos = []
    for az in (0.0, 90.0, 180.0):
        pose = pose_from_mount(MOUNT, az)
        fotos.append((az, render_from_pose(cloud, pose, None,
                                           scale=16).astype(np.float64)))

    start = dict(MOUNT)
    start["az_offset_deg"] = MOUNT["az_offset_deg"] + 6.0
    start["pitch_mount_deg"] = MOUNT["pitch_mount_deg"] - 3.0
    fitted, before, after = autofit(cloud, start, fotos, None)
    assert after > before
    assert fitted["az_offset_deg"] == pytest.approx(30.0, abs=1.5)
    assert fitted["pitch_mount_deg"] == pytest.approx(10.0, abs=1.5)


def test_overlay_score_bevorzugt_wahrheit():
    cloud = _szene()
    pose = pose_from_mount(MOUNT, 45.0)
    foto = render_from_pose(cloud, pose, None, scale=16).astype(np.float64)
    gut = overlay_score(cloud, MOUNT, 45.0, foto, None)
    falsch = overlay_score(cloud, dict(MOUNT, az_offset_deg=75.0),
                           45.0, foto, None)
    assert gut > falsch


@pytest.mark.parametrize("scale", [8, 16])
def test_overlay_score_beliebige_fotoaufloesung(scale):
    """Foto in Sensor/scale-Auflösung darf keinen Broadcast-Fehler werfen.

    Regression: Der Prüfer reicht das Anzeige-Foto (Sensor/8) an
    overlay_score, das aber fest mit Sensor/16 renderte →
    „operands could not be broadcast together (152,203) (305,407)".
    """
    cloud = _szene()
    w, h = SENSOR_W_PX // scale, SENSOR_H_PX // scale
    foto = np.zeros((h, w), np.float64)      # wie _render (scale 8) / _autofit (16)
    s = overlay_score(cloud, MOUNT, 0.0, foto, None)
    assert np.isfinite(s)


def test_project_camera_mounts_roundtrip(tmp_path):
    from studio.core.project import Project

    p = Project.create(tmp_path / "proj", "Test")
    p.camera_mounts = {"usb0": dict(MOUNT)}
    p.save()
    q = Project.open(tmp_path / "proj")
    assert q.camera_mounts["usb0"]["az_offset_deg"] == 30.0
