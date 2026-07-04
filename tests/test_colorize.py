"""Tests: Punktwolken-Einfärbung aus Fotos (synthetische Szene)."""

import numpy as np
import pytest
from PIL import Image

from studio.core.cloud import PointCloud
from studio.core.colorize import colorize_cloud
from studio.core.export import load_ply, save_ply
from studio.core.photos import PhotoPose


def _photo(tmp_path, name: str, color: tuple, **pose_kw) -> PhotoPose:
    """Einfarbiges Test-JPEG + Pose."""
    path = tmp_path / name
    Image.new("RGB", (3264 // 8, 2448 // 8), color).save(path, "JPEG",
                                                         quality=95)
    d = dict(label=name, source=path, cam_id="usb0", azimuth_deg=0.0,
             x=0.0, y=0.0, z=0.0, yaw=0.0, pitch=0.0, roll=0.0)
    d.update(pose_kw)
    return PhotoPose(**d)


def _cloud(xyz) -> PointCloud:
    xyz = np.asarray(xyz, dtype=np.float32)
    n = len(xyz)
    return PointCloud(xyz=xyz,
                      intensity=np.full(n, 128, np.uint8),
                      scanner_dist=np.linalg.norm(xyz, axis=1).astype(np.float32))


def test_punkt_vor_kamera_bekommt_farbe(tmp_path):
    rot = _photo(tmp_path, "rot.jpg", (255, 0, 0))            # Blick +Y
    gruen = _photo(tmp_path, "gruen.jpg", (0, 255, 0), yaw=180.0)
    cloud = _cloud([[0, 2, 0],     # vor der roten Kamera
                    [0, -2, 0],    # hinter ihr → grüne Kamera (yaw 180)
                    [0, 2, 0.3]])  # leicht oberhalb, immer noch rot
    rgb, n_col = colorize_cloud(cloud, [rot, gruen])
    assert n_col == 3
    assert rgb[0][0] > 200 and rgb[0][1] < 60       # rot
    assert rgb[1][1] > 200 and rgb[1][0] < 60       # grün
    assert rgb[2][0] > 200


def test_punkt_ausserhalb_bildfeld_bleibt_grau(tmp_path):
    rot = _photo(tmp_path, "rot.jpg", (255, 0, 0))
    cloud = _cloud([[0, -2, 0]])   # hinter der einzigen Kamera
    rgb, n_col = colorize_cloud(cloud, [rot])
    assert n_col == 0
    assert rgb[0][0] == rgb[0][1] == rgb[0][2]      # Grauwert-Fallback


def test_zbuffer_verdeckt_hintere_punkte(tmp_path):
    rot = _photo(tmp_path, "rot.jpg", (255, 0, 0))
    # Dichte "Wand" bei y=1 m + einzelner Punkt dahinter (y=3, gleiche
    # Blickrichtung) → der hintere darf keine Farbe aus diesem Foto bekommen.
    # Wandraster muss dichter sein als das Z-Buffer-Raster (16 px ≙ 6,4 mm
    # in 1 m Abstand), sonst fällt der hintere Punkt in eine leere Zelle.
    xs, zs = np.meshgrid(np.linspace(-0.5, 0.5, 200),
                         np.linspace(-0.4, 0.4, 160))
    wand = np.column_stack([xs.ravel(), np.ones(xs.size), zs.ravel()])
    dahinter = np.array([[0.0, 3.0, 0.0]])
    cloud = _cloud(np.vstack([wand, dahinter]))
    rgb, n_col = colorize_cloud(cloud, [rot])
    assert n_col == len(wand)                       # Wand ja, Punkt nein
    hinten = rgb[-1]
    assert hinten[0] == hinten[1] == hinten[2]      # grau geblieben


def test_floor_transform_verschiebt_kamera(tmp_path):
    """floor_T hebt die Wolke an — die Kamera muss mitwandern."""
    rot = _photo(tmp_path, "rot.jpg", (255, 0, 0))
    floor_T = np.eye(4)
    floor_T[2, 3] = 0.7                              # Boden→Z=0-Shift
    cloud = _cloud([[0, 2, 0.7]])                    # Punkt im floor-Frame
    rgb, n_col = colorize_cloud(cloud, [rot], floor_T)
    assert n_col == 1 and rgb[0][0] > 200


def test_ply_roundtrip_mit_rgb(tmp_path):
    cloud = _cloud([[0, 1, 0], [1, 0, 0]])
    cloud.rgb = np.array([[10, 20, 30], [200, 100, 50]], dtype=np.uint8)
    path = tmp_path / "farbig.ply"
    save_ply(cloud, path)
    back = load_ply(path)
    np.testing.assert_array_equal(back.rgb, cloud.rgb)
    # Bestandsformat ohne RGB bleibt lesbar
    cloud.rgb = None
    save_ply(cloud, path)
    assert load_ply(path).rgb is None


def test_las_mit_rgb(tmp_path):
    import laspy
    cloud = _cloud([[0, 1, 0], [1, 0, 0]])
    cloud.rgb = np.array([[255, 0, 0], [0, 0, 255]], dtype=np.uint8)
    from studio.core.export import save_las
    path = tmp_path / "farbig.las"
    save_las(cloud, path)
    las = laspy.read(str(path))
    assert las.header.point_format.id == 2
    assert int(las.red[0]) == 255 * 257


def test_fusion_mittelt_rgb():
    from studio.core.fusion import fuse
    a = _cloud([[0, 0, 0]]); a.rgb = np.array([[100, 0, 0]], np.uint8)
    b = _cloud([[0.001, 0, 0]]); b.rgb = np.array([[200, 0, 0]], np.uint8)
    fused = fuse([a, b], [np.eye(4), np.eye(4)], voxel_size_m=0.05)
    assert len(fused) == 1
    assert 100 <= fused.rgb[0][0] <= 200
    # ohne rgb in einer Teilwolke → Ergebnis ohne rgb
    b.rgb = None
    fused = fuse([a, b], [np.eye(4), np.eye(4)], voxel_size_m=0.05)
    assert fused.rgb is None
