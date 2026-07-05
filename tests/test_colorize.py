"""Tests: Punktwolken-Einfärbung aus Fotos (synthetische Szene)."""

import numpy as np
import pytest
from PIL import Image

from studio.core.cloud import PointCloud
from studio.core.colorize import (ZBUF_DOWNSCALE, _blend, _estimate_gains,
                                  _feather_weight, _linear_to_srgb,
                                  _occlusion_mask, _srgb_to_linear,
                                  colorize_cloud)
from studio.core.export import load_ply, save_ply
from studio.core.photos import PhotoPose, SENSOR_H_PX, SENSOR_W_PX


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


# --- (a/b/c) Helfer für Angleich, Blend, Verdeckung ----------------------

def test_srgb_linear_roundtrip():
    c = np.array([0.0, 0.04, 0.2, 0.5, 0.8, 1.0])
    back = _linear_to_srgb(_srgb_to_linear(c))
    np.testing.assert_allclose(back, c, atol=1e-6)
    # Mittelgrau sRGB 0.5 wird in Linearlicht deutlich dunkler
    assert _srgb_to_linear(np.array([0.5]))[0] == pytest.approx(0.214, abs=0.01)
    assert _srgb_to_linear(np.array([0.0]))[0] == 0.0


def test_feather_weight_mitte_max_rand_null():
    cx, cy = SENSOR_W_PX / 2, SENSOR_H_PX / 2
    u = np.array([cx, cx, 0.0, cx])
    v = np.array([cy, cy - cy / 2, cy, 0.0])   # Mitte, halbhoch, li-Rand, o-Rand
    w = _feather_weight(u, v)
    assert w[0] == pytest.approx(1.0)           # Bildmitte → 1
    assert w[2] == pytest.approx(0.0)           # linker Rand → 0
    assert w[3] == pytest.approx(0.0)           # oberer Rand → 0
    assert 0.0 < w[1] < 1.0                      # dazwischen, monoton fallend
    assert w[1] > _feather_weight(np.array([cx]), np.array([cy / 4]))[0]


def test_occlusion_mask_gleiche_zelle_hinten_verdeckt():
    cx, cy = SENSOR_W_PX / 2, SENSOR_H_PX / 2
    u = np.array([cx, cx, cx])
    v = np.array([cy, cy, cy])
    depth = np.array([1.0, 1.05, 3.0])          # 2 nah (in Toleranz), 1 fern
    m = _occlusion_mask(u, v, depth)
    assert m[0] and m[1]                         # innerhalb 10 cm sichtbar
    assert not m[2]                              # 2 m dahinter → verdeckt


def test_occlusion_mask_splat_schliesst_nachbarloch():
    """Vordergrundpunkt verdeckt Hintergrund in NACHBARzelle (Splat 3×3)."""
    cx, cy = SENSOR_W_PX / 2, SENSOR_H_PX / 2
    u = np.array([cx, cx + ZBUF_DOWNSCALE])      # eine Zelle daneben
    v = np.array([cy, cy])
    depth = np.array([1.0, 3.0])                 # vorne, hinten
    m = _occlusion_mask(u, v, depth)
    assert m[0]
    assert not m[1]                              # per Splat verdeckt


def test_estimate_gains_gleicht_helligkeit_an():
    n = 300
    cam0 = np.zeros((n, 3)); cam0[:] = 0.4       # dunklere Kamera
    cam1 = np.zeros((n, 3)); cam1[:] = 0.6       # 1,5× hellere Kamera
    w = np.ones(n)                                # voller Overlap
    gains = _estimate_gains([cam0, cam1], [w, w])
    # angeglichene Helligkeit: g0·0.4 ≈ g1·0.6
    np.testing.assert_allclose(gains[0] * 0.4, gains[1] * 0.6, atol=0.01)
    assert gains[0, 0] / gains[1, 0] == pytest.approx(1.5, abs=0.05)


def test_estimate_gains_ohne_overlap_bleibt_eins():
    n = 100
    cam0 = np.full((n, 3), 0.4); cam1 = np.full((n, 3), 0.6)
    w0 = np.zeros(n); w0[:50] = 1.0              # Kamera 0 sieht nur vordere
    w1 = np.zeros(n); w1[50:] = 1.0              # Kamera 1 nur hintere → kein Overlap
    gains = _estimate_gains([cam0, cam1], [w0, w1])
    np.testing.assert_allclose(gains, 1.0, atol=1e-9)


def test_blend_gewichtet_und_fallback():
    cam0 = np.array([[0.2, 0.2, 0.2]]); cam1 = np.array([[0.8, 0.8, 0.8]])
    gains = np.ones((2, 3))
    # gleiche Gewichte → linearer Mittelwert 0.5
    rgb, colored = _blend([cam0, cam1], [np.array([1.0]), np.array([1.0])], gains)
    assert colored[0]
    assert rgb[0, 0] == pytest.approx(round(_linear_to_srgb(np.array([0.5]))[0] * 255),
                                      abs=1)
    # kein Treffer (Gewicht 0) → nicht eingefärbt
    _, colored2 = _blend([cam0], [np.array([0.0])], np.ones((1, 3)))
    assert not colored2[0]


def test_kameranaht_wird_durch_gain_geschlossen(tmp_path):
    """Zwei Kameras mit Helligkeits-Offset, teils überlappend.

    Ohne Angleich klafft an der Grenze eine Naht (140 ↔ 190). Der
    Overlap-Gain-Ausgleich muss die nur-links (Cam0) und nur-rechts (Cam1)
    eingefärbten Bereiche einander angleichen.
    """
    def cam(name, color, yaw, cam_id):
        path = tmp_path / name
        Image.new("RGB", (SENSOR_W_PX // 8, SENSOR_H_PX // 8), color).save(
            path, "JPEG", quality=95)
        return PhotoPose(label=name, source=path, cam_id=cam_id,
                         azimuth_deg=0.0, x=0.0, y=0.0, z=0.0,
                         yaw=yaw, pitch=0.0, roll=0.0)

    cam0 = cam("c0.jpg", (140, 140, 140), -25.0, "usb0")
    cam1 = cam("c1.jpg", (190, 190, 190), +25.0, "usb1")
    xs = np.linspace(-1.0, 1.0, 400)
    cloud = _cloud(np.column_stack([xs, np.full(xs.size, 3.0),
                                    np.zeros(xs.size)]))
    rgb, n_col = colorize_cloud(cloud, [cam0, cam1])
    assert n_col > 200

    # Randbereiche, die nur je eine Kamera sieht
    links = rgb[xs < -0.6][:, 0].astype(float)
    rechts = rgb[xs > 0.6][:, 0].astype(float)
    assert len(links) > 20 and len(rechts) > 20
    # Naht geschlossen: mittlere Helligkeit beider Seiten ähnlich
    assert abs(links.mean() - rechts.mean()) < 20        # roh wären es ~50
    # ... und die Angleichung liegt zwischen den Rohwerten (nicht unverändert)
    assert 140 < links.mean() < 190 or 140 < rechts.mean() < 190


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
