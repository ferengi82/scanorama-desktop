"""Tests: Kamera-Mathematik, Farbmodi, Picking (alles ohne GL/Display)."""

import numpy as np
import pytest

from studio.core.cloud import PointCloud
from studio.ui.viewer.camera import OrbitCamera, look_at, perspective
from studio.ui.viewer.colors import COLOR_MODES, colorize
from studio.ui.viewer.picking import pick_point


def _cloud(xyz, intensity=None, station=None):
    n = len(xyz)
    return PointCloud(
        xyz=np.asarray(xyz, dtype=np.float32),
        intensity=(np.asarray(intensity, np.uint8) if intensity is not None
                   else np.full(n, 128, np.uint8)),
        scanner_dist=np.ones(n, np.float32),
        station=station,
    )


# --- Kamera ---------------------------------------------------------------

def test_eye_position_basics():
    cam = OrbitCamera(distance=10, yaw_deg=0, pitch_deg=0)
    # yaw=0, pitch=0 → Kamera auf der Y-Achse, Blick nach -Y
    np.testing.assert_allclose(cam.eye, [0, 10, 0], atol=1e-9)
    cam.pitch_deg = 90
    np.testing.assert_allclose(cam.eye, [0, 0, 10], atol=1e-6)


def test_view_matrix_transforms_target_to_front():
    cam = OrbitCamera(distance=5, yaw_deg=30, pitch_deg=20)
    V = cam.view_matrix()
    t = V @ np.append(cam.target, 1.0)
    # Zielpunkt liegt auf der Blickachse in Distanz-Entfernung
    np.testing.assert_allclose(t[:2], [0, 0], atol=1e-9)
    assert t[2] == pytest.approx(-5.0)


def test_perspective_maps_near_far():
    P = perspective(60, 1.0, 1.0, 100.0)
    near = P @ np.array([0, 0, -1.0, 1])
    far = P @ np.array([0, 0, -100.0, 1])
    assert near[2] / near[3] == pytest.approx(-1.0)
    assert far[2] / far[3] == pytest.approx(1.0)


def test_zoom_and_pitch_limits():
    cam = OrbitCamera(distance=1.0)
    for _ in range(100):
        cam.zoom(5)
    assert cam.distance == cam.MIN_DIST
    cam.rotate(0, 10000)
    assert cam.pitch_deg == cam.MAX_PITCH


def test_fit_contains_bbox():
    cam = OrbitCamera()
    cam.fit(np.array([-2, -2, 0]), np.array([2, 2, 3]))
    np.testing.assert_allclose(cam.target, [0, 0, 1.5], atol=1e-9)
    assert cam.distance > np.linalg.norm([2, 2, 1.5])  # außerhalb der Box


def test_screen_ray_center_hits_target():
    cam = OrbitCamera(distance=8, yaw_deg=123, pitch_deg=-15)
    origin, direction = cam.screen_ray(400, 300, 800, 600)
    np.testing.assert_allclose(origin, cam.eye, atol=1e-9)
    # Strahl durch die Bildmitte geht durchs Ziel
    to_target = cam.target - origin
    np.testing.assert_allclose(direction,
                               to_target / np.linalg.norm(to_target),
                               atol=1e-9)


# --- Farben ---------------------------------------------------------------

def test_colorize_intensity_monotonic():
    c = _cloud([[0, 0, 0]] * 3, intensity=[0, 128, 255])
    rgb = colorize(c, "intensity")
    assert rgb[0, 0] < rgb[1, 0] < rgb[2, 0]
    assert (rgb[:, 0] == rgb[:, 1]).all()  # Grauwerte


def test_colorize_height_uses_ramp():
    z = np.linspace(0, 3, 100)
    c = _cloud(np.column_stack((np.zeros(100), np.zeros(100), z)))
    rgb = colorize(c, "height").astype(int)
    # unten blau-lastig, oben rot-lastig
    assert rgb[0, 2] > rgb[0, 0]
    assert rgb[-1, 0] > rgb[-1, 2]


def test_colorize_station_categorical():
    c = _cloud([[0, 0, 0]] * 4, station=np.array([0, 1, 0, 2], np.uint16))
    rgb = colorize(c, "station")
    assert (rgb[0] == rgb[2]).all()
    assert not (rgb[0] == rgb[1]).all()


def test_all_modes_shape():
    c = _cloud(np.random.default_rng(0).uniform(-1, 1, (50, 3)))
    for mode in COLOR_MODES:
        rgb = colorize(c, mode)
        assert rgb.shape == (50, 3)
        assert rgb.dtype == np.uint8


# --- Picking ---------------------------------------------------------------

def test_pick_nearest_on_ray():
    xyz = np.array([[0, 5, 0], [0, 10, 0], [3, 5, 0]], dtype=np.float32)
    idx = pick_point(xyz, origin=np.zeros(3), direction=np.array([0, 1.0, 0]))
    assert idx == 0      # auf dem Strahl UND näher als Punkt 1


def test_pick_ignores_behind_camera():
    xyz = np.array([[0, -5, 0]], dtype=np.float32)
    assert pick_point(xyz, np.zeros(3), np.array([0, 1.0, 0])) is None


def test_pick_respects_cone():
    xyz = np.array([[1.0, 5, 0]], dtype=np.float32)   # ~11° neben dem Strahl
    assert pick_point(xyz, np.zeros(3), np.array([0, 1.0, 0]),
                      max_angle_deg=0.6) is None
    assert pick_point(xyz, np.zeros(3), np.array([0, 1.0, 0]),
                      max_angle_deg=15.0) == 0
