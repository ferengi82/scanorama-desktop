"""Tests: Stativ-/Nahbereichs- und Ausreißerfilter."""

from pathlib import Path

import numpy as np

from studio.core.cloud import PointCloud
from studio.core.filters import FilterParams, filter_raw, remove_outliers
from studio.core.rawscan import RawScan


def _raw(elevations, distances_mm):
    n = len(elevations)
    return RawScan(
        path=Path("."), name="synthetisch",
        elevation_deg=np.array(elevations, dtype=np.float32),
        azimuth_deg=np.zeros(n, dtype=np.float32),
        distance_mm=np.array(distances_mm, dtype=np.uint16),
        intensity=np.full(n, 50, dtype=np.uint8),
        t_ns=np.zeros(n, dtype=np.int64),
    )


def test_tripod_filter():
    raw = _raw([100, 165, 180, 195, 200], [1000] * 5)
    out, report = filter_raw(raw, FilterParams(min_dist_m=0))
    assert report["removed_tripod"] == 3          # 165, 180, 195
    assert list(out.elevation_deg) == [100, 200]


def test_tripod_filter_disabled():
    raw = _raw([170, 180], [1000, 1000])
    params = FilterParams(block_start_deg=0, block_end_deg=0, min_dist_m=0)
    out, report = filter_raw(raw, params)
    assert len(out) == 2
    assert report["removed_tripod"] == 0


def test_near_filter():
    raw = _raw([10, 20, 30], [100, 299, 301])
    out, report = filter_raw(raw, FilterParams(block_start_deg=0,
                                               block_end_deg=0,
                                               min_dist_m=0.30))
    assert report["removed_near"] == 2            # 100 mm und 299 mm
    assert list(out.distance_mm) == [301]


def test_outlier_filter_removes_lonely_point():
    rng = np.random.default_rng(42)
    # dichte Ebene + ein einsamer Ausreißer weit außerhalb
    plane = rng.uniform(-1, 1, size=(2000, 2))
    xyz = np.column_stack((plane, rng.normal(0, 0.005, 2000))).astype(np.float32)
    xyz = np.vstack([xyz, [[0.0, 0.0, 5.0]]]).astype(np.float32)
    n = len(xyz)
    cloud = PointCloud(
        xyz=xyz,
        intensity=np.full(n, 10, np.uint8),
        scanner_dist=np.ones(n, np.float32),
    )
    out, report = remove_outliers(cloud, FilterParams())
    assert report["removed_outliers"] >= 1
    # der Ausreißer bei z=5 muss weg sein
    assert out.xyz[:, 2].max() < 1.0


def test_outlier_filter_disabled():
    cloud = PointCloud(
        xyz=np.zeros((10, 3), np.float32),
        intensity=np.zeros(10, np.uint8),
        scanner_dist=np.ones(10, np.float32),
    )
    out, report = remove_outliers(cloud, FilterParams(sor_enabled=False))
    assert len(out) == 10
    assert report["removed_outliers"] == 0
