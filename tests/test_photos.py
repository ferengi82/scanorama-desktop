"""Tests: Fotoposen (POSE_RECIPE, Euler, Transformation) + Metashape-Export."""

import json

import numpy as np
import pytest

from studio.core.photos import (PhotoPose, compute_pose, export_metashape,
                                load_station_photos,
                                matrix_to_yaw_pitch_roll, transform_pose,
                                yaw_pitch_roll_to_matrix)

MOUNT = {"r_cam_m": 0.05, "z_cam_m": -0.04, "az_offset_deg": 0.0,
         "yaw_mount_deg": 0.0, "pitch_mount_deg": 15.0, "roll_mount_deg": 0.0}


def test_compute_pose_richtungen():
    # az=0: Kamera radial nach +Y, Blick +Y (yaw 0)
    x, y, z, yaw, pitch, roll = compute_pose(0.0, MOUNT)
    assert (x, y) == pytest.approx((0.0, 0.05), abs=1e-12)
    assert z == -0.04 and yaw == 0.0 and pitch == 15.0

    # az=90: radial nach +X, yaw 90
    x, y, z, yaw, _, _ = compute_pose(90.0, MOUNT)
    assert (x, y) == pytest.approx((0.05, 0.0), abs=1e-12)
    assert yaw == 90.0

    # az_offset addiert sich zu Position UND Yaw
    m = dict(MOUNT, az_offset_deg=90.0)
    x, y, _, yaw, _, _ = compute_pose(0.0, m)
    assert (x, y) == pytest.approx((0.05, 0.0), abs=1e-12)
    assert yaw == 90.0


@pytest.mark.parametrize("ypr", [(0, 0, 0), (37, 5, -8), (270, -20, 3),
                                 (359.9, 50, 0)])
def test_euler_roundtrip(ypr):
    R = yaw_pitch_roll_to_matrix(*ypr)
    back = matrix_to_yaw_pitch_roll(R)
    assert back == pytest.approx((ypr[0] % 360, ypr[1], ypr[2]), abs=1e-9)


def _pose(**kw):
    d = dict(label="p.jpg", source=None, cam_id="usb0", azimuth_deg=0.0,
             x=0.1, y=0.2, z=0.3, yaw=37.0, pitch=5.0, roll=-8.0)
    d.update(kw)
    return PhotoPose(**d)


def test_transform_pose_identitaet_translation_rotation():
    p = _pose()
    out = transform_pose(p, np.eye(4))
    assert (out.x, out.y, out.z) == pytest.approx((0.1, 0.2, 0.3))
    assert (out.yaw, out.pitch, out.roll) == pytest.approx((37, 5, -8), abs=1e-9)

    T = np.eye(4)
    T[:3, 3] = [1, 2, 3]
    out = transform_pose(p, T)
    assert (out.x, out.y, out.z) == pytest.approx((1.1, 2.2, 3.3))
    assert out.yaw == pytest.approx(37.0)

    # Physische 90°-CCW-Drehung um Z (mathematische Matrix, wie sie die
    # Registrierung liefert): Position +Y → −X, Kompass-Yaw 0 → 270.
    c, s = 0.0, 1.0
    T = np.eye(4)
    T[:3, :3] = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    p2 = _pose(x=0.0, y=1.0, z=0.0, yaw=0.0, pitch=0.0, roll=0.0)
    out = transform_pose(p2, T)
    assert (out.x, out.y) == pytest.approx((-1.0, 0.0), abs=1e-9)
    assert out.yaw == pytest.approx(270.0, abs=1e-9)


def test_kompass_yaw_blickrichtung():
    """yaw=90° muss Blick +X ergeben (Kompass, wie die Fotorunde)."""
    R = yaw_pitch_roll_to_matrix(90, 0, 0)
    np.testing.assert_allclose(R @ [0, 1, 0], [1, 0, 0], atol=1e-12)
    # pitch +50° hebt den Blick Richtung +Z
    R = yaw_pitch_roll_to_matrix(0, 50, 0)
    view = R @ [0, 1, 0]
    assert view[2] == pytest.approx(np.sin(np.radians(50)))


def _fake_scan(tmp_path, name="2026-07-04_scan_03_001", n=4):
    scan = tmp_path / name
    (scan / "photos").mkdir(parents=True)
    photos = []
    for i in range(n):
        az = i * 90.0
        fn = f"photos/photo_{i:02d}_az{int(az):03d}_usb0.jpg"
        (scan / fn).write_bytes(b"\xff\xd8\xff\xd9")  # Mini-"JPEG"
        photos.append({"file": fn, "cam_id": "usb0", "index": i,
                       "azimuth_deg": az, "t_ns": 0})
    meta = {"photos": photos, "cameras": {"mounts": {"usb0": MOUNT}}}
    (scan / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return scan, meta


def test_load_station_photos(tmp_path):
    scan, meta = _fake_scan(tmp_path)
    poses = load_station_photos(scan, meta, label_prefix=scan.name)
    assert len(poses) == 4
    assert poses[0].label.startswith(scan.name + "_photo_00")
    assert poses[1].yaw == pytest.approx(90.0)
    # fehlende Datei → übersprungen
    (scan / meta["photos"][2]["file"]).unlink()
    assert len(load_station_photos(scan, meta)) == 3


def test_export_metashape(tmp_path):
    scan, meta = _fake_scan(tmp_path)
    poses = load_station_photos(scan, meta, label_prefix="s1")
    T = np.eye(4)
    T[:3, 3] = [10, 0, 0]
    out = tmp_path / "metashape"
    csv_path = export_metashape([("s1", poses, T)], out)

    lines = csv_path.read_text(encoding="utf-8").splitlines()
    data = [l for l in lines if not l.startswith("#") and not l.startswith("Label")]
    assert len(data) == 4
    first = data[0].split(",")
    assert first[0] == "s1_photo_00_az000_usb0.jpg"
    assert float(first[1]) == pytest.approx(10.0, abs=1e-6)   # verschoben
    assert (out / "s1_photo_00_az000_usb0.jpg").is_file()      # Kopie da
    assert (out / "calibration.xml").is_file()
    assert (out / "ANLEITUNG.md").is_file()


def test_export_metashape_doppelte_labels(tmp_path):
    scan, meta = _fake_scan(tmp_path)
    poses = load_station_photos(scan, meta)   # ohne Prefix
    with pytest.raises(ValueError, match="Doppelte"):
        export_metashape([("a", poses, None), ("b", poses, None)],
                         tmp_path / "out")


def test_export_metashape_ohne_fotos(tmp_path):
    with pytest.raises(ValueError, match="Keine Fotos"):
        export_metashape([("leer", [], None)], tmp_path / "out")
