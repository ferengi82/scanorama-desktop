"""Tests: Bodenerkennung und -ausrichtung."""

import numpy as np
import pytest

from studio.core.cloud import PointCloud
from studio.core.floor import align_floor


def _room_cloud(tilt_deg=5.0, floor_z=-1.4, seed=1) -> PointCloud:
    """Synthetischer Raum: Boden (verkippt) + eine Wand + Streuung."""
    rng = np.random.default_rng(seed)
    # Boden: 4×4 m dicht
    fx = rng.uniform(-2, 2, 20000)
    fy = rng.uniform(-2, 2, 20000)
    fz = np.full_like(fx, floor_z) + rng.normal(0, 0.003, fx.size)
    floor_pts = np.column_stack((fx, fy, fz))
    # Wand bei y=2
    wx = rng.uniform(-2, 2, 5000)
    wz = rng.uniform(floor_z, floor_z + 2.5, 5000)
    wall = np.column_stack((wx, np.full_like(wx, 2.0), wz))
    pts = np.vstack([floor_pts, wall])

    # Alles um X kippen (simulierter el_offset-Resteffekt)
    a = np.radians(tilt_deg)
    R = np.array([[1, 0, 0],
                  [0, np.cos(a), -np.sin(a)],
                  [0, np.sin(a), np.cos(a)]])
    pts = pts @ R.T
    n = len(pts)
    return PointCloud(
        xyz=pts.astype(np.float32),
        intensity=np.full(n, 80, np.uint8),
        scanner_dist=np.linalg.norm(pts, axis=1).astype(np.float32),
    )


def test_align_tilted_floor():
    cloud = _room_cloud(tilt_deg=5.0, floor_z=-1.4)
    aligned, T = align_floor(cloud)
    assert T is not None
    # Bodenpunkte (die unteren 60 %) müssen jetzt bei z≈0 liegen
    z = aligned.xyz[:, 2]
    floor_z = np.median(z[z < np.percentile(z, 60)])
    assert floor_z == pytest.approx(0.0, abs=0.01)
    # und der Boden muss eben sein (kleine Streuung im unteren Bereich)
    floor_mask = np.abs(z) < 0.05
    assert floor_mask.sum() > 15000


def test_no_floor_returns_none():
    """Nur eine senkrechte Wand — es darf kein Boden erkannt werden."""
    rng = np.random.default_rng(2)
    wx = rng.uniform(-2, 2, 5000)
    wz = rng.uniform(-1, 2, 5000)
    pts = np.column_stack((wx, np.full_like(wx, 2.0), wz))
    cloud = PointCloud(
        xyz=pts.astype(np.float32),
        intensity=np.zeros(len(pts), np.uint8),
        scanner_dist=np.ones(len(pts), np.float32),
    )
    aligned, T = align_floor(cloud)
    assert T is None
    np.testing.assert_array_equal(aligned.xyz, cloud.xyz)
