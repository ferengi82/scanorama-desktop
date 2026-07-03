"""Tests: Registrierung/Fusion mit synthetischer Raumszene.

Zwei/drei "Standpunkte" sehen dieselbe L-förmige Raumszene aus
unterschiedlichen Posen. Die Registrierung muss die bekannten Posen
wiederfinden (Translation < 2 cm, Rotation < 1°).
"""

import numpy as np
import pytest

from studio.core.cloud import PointCloud
from studio.core.fusion import distance_weight, fuse
from studio.core.registration import (RegistrationParams, RegistrationResult,
                                      register_stations)


def _scene(rng) -> np.ndarray:
    """L-förmiger Raum mit Kisten — genug Struktur für FPFH."""
    pts = []
    # Boden 6×4
    pts.append(np.column_stack([rng.uniform(0, 6, 30000),
                                rng.uniform(0, 4, 30000),
                                rng.normal(0, 0.004, 30000)]))
    # Wand y=0 und Wand x=0
    pts.append(np.column_stack([rng.uniform(0, 6, 15000),
                                rng.normal(0, 0.004, 15000),
                                rng.uniform(0, 2.5, 15000)]))
    pts.append(np.column_stack([rng.normal(0, 0.004, 15000),
                                rng.uniform(0, 4, 15000),
                                rng.uniform(0, 2.5, 15000)]))
    # zwei Kisten (brechen die Symmetrie)
    for cx, cy, s in [(2.0, 1.5, 0.6), (4.5, 2.8, 0.4)]:
        n = 6000
        face = rng.integers(0, 3, n)
        u, v = rng.uniform(0, s, n), rng.uniform(0, s, n)
        box = np.empty((n, 3))
        box[face == 0] = np.column_stack([u, v, np.full(n, s)])[face == 0]
        box[face == 1] = np.column_stack([u, np.zeros(n), v])[face == 1]
        box[face == 2] = np.column_stack([np.zeros(n), u, v])[face == 2]
        box += [cx, cy, 0]
        pts.append(box)
    return np.vstack(pts)


def _station(scene: np.ndarray, pose: np.ndarray, rng) -> PointCloud:
    """Szene aus Sicht eines Standpunkts: global → lokal (inv(pose))."""
    inv = np.linalg.inv(pose)
    local = scene @ inv[:3, :3].T + inv[:3, 3]
    # Standpunkt-typisches Rauschen + eigene Stichprobe
    idx = rng.choice(len(local), size=int(len(local) * 0.8), replace=False)
    local = local[idx] + rng.normal(0, 0.003, (len(idx), 3))
    dist = np.linalg.norm(local, axis=1)
    return PointCloud(
        xyz=local.astype(np.float32),
        intensity=np.full(len(local), 100, np.uint8),
        scanner_dist=dist.astype(np.float32),
    )


def _pose(x, y, yaw_deg) -> np.ndarray:
    T = np.eye(4)
    a = np.radians(yaw_deg)
    T[:2, :2] = [[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]
    T[:3, 3] = [x, y, 0.0]
    return T


def _pose_error(T_est, T_true) -> tuple[float, float]:
    d = np.linalg.inv(T_true) @ T_est
    trans_err = float(np.linalg.norm(d[:3, 3]))
    angle = np.degrees(np.arccos(np.clip((np.trace(d[:3, :3]) - 1) / 2, -1, 1)))
    return trans_err, float(angle)


@pytest.fixture(scope="module")
def scene():
    return _scene(np.random.default_rng(11))


def test_two_station_registration(scene):
    rng = np.random.default_rng(4)
    pose_a = _pose(1.5, 1.0, 0)
    pose_b = _pose(4.0, 2.0, 40)
    a = _station(scene, pose_a, rng)
    b = _station(scene, pose_b, rng)

    result = register_stations([a, b], RegistrationParams())
    assert isinstance(result, RegistrationResult)
    np.testing.assert_allclose(result.poses[0], np.eye(4))

    # Erwartete Relativpose: bringt B-lokal in den Rahmen von A-lokal
    T_true = np.linalg.inv(pose_a) @ pose_b
    trans_err, rot_err = _pose_error(result.poses[1], T_true)
    assert trans_err < 0.02, f"Translationsfehler {trans_err * 100:.1f} cm"
    assert rot_err < 1.0, f"Rotationsfehler {rot_err:.2f}°"
    assert result.pairs[0].rating in ("gut", "mäßig")


def test_fusion_weights_and_voxels(scene):
    rng = np.random.default_rng(5)
    pose_a = _pose(1.5, 1.0, 0)
    pose_b = _pose(4.0, 2.0, 40)
    a = _station(scene, pose_a, rng)
    b = _station(scene, pose_b, rng)

    fused = fuse([a, b], [pose_a, pose_b], voxel_size_m=0.05)
    # Fusion reduziert deutlich (beide sehen dieselbe Szene)
    assert len(fused) < (len(a) + len(b)) * 0.7
    # beide Standpunkte tragen bei
    assert set(np.unique(fused.station)) == {0, 1}
    # fusionierte Wolke liegt im Szenen-Bereich (globaler Rahmen)
    assert fused.xyz[:, 0].min() > -0.5 and fused.xyz[:, 0].max() < 6.5
    assert fused.xyz[:, 2].min() > -0.3 and fused.xyz[:, 2].max() < 3.0


def test_distance_weight_model():
    w = distance_weight(np.array([1.0, 2.0, 8.0, 25.0]))
    assert w[0] == pytest.approx(1 / 25)          # σ=5mm
    assert w[1] == pytest.approx(1 / 25)
    assert w[2] == pytest.approx(1 / 225)         # σ=15mm
    assert w[3] == pytest.approx(1 / 625)         # σ=25mm
    assert w[0] / w[3] == pytest.approx(25.0)


def test_single_station():
    c = PointCloud(xyz=np.zeros((10, 3), np.float32),
                   intensity=np.zeros(10, np.uint8),
                   scanner_dist=np.ones(10, np.float32))
    result = register_stations([c])
    assert len(result.poses) == 1
    np.testing.assert_allclose(result.poses[0], np.eye(4))
