"""Tests: PLY/LAS/E57-Export mit Rücklese-Prüfung."""

import numpy as np
import pytest

from studio.core.cloud import PointCloud
from studio.core import export


@pytest.fixture
def cloud() -> PointCloud:
    rng = np.random.default_rng(7)
    n = 5000
    return PointCloud(
        xyz=rng.uniform(-5, 5, (n, 3)).astype(np.float32),
        intensity=rng.integers(0, 256, n, dtype=np.uint8),
        scanner_dist=rng.uniform(0.3, 10, n).astype(np.float32),
        station=rng.integers(0, 3, n, dtype=np.uint16),
        meta={"scan_name": "test"},
    )


def test_ply_roundtrip(cloud, tmp_path):
    path = tmp_path / "test.ply"
    export.save_ply(cloud, path)
    back = export.load_ply(path)
    assert len(back) == len(cloud)
    np.testing.assert_allclose(back.xyz, cloud.xyz, atol=1e-6)
    np.testing.assert_array_equal(back.intensity, cloud.intensity)
    np.testing.assert_array_equal(back.station, cloud.station)


def test_las_roundtrip(cloud, tmp_path):
    import laspy
    path = tmp_path / "test.las"
    export.save_las(cloud, path)
    las = laspy.read(str(path))
    assert len(las.points) == len(cloud)
    np.testing.assert_allclose(np.asarray(las.x), cloud.xyz[:, 0].astype(np.float64), atol=0.0002)
    np.testing.assert_array_equal(np.asarray(las.point_source_id), cloud.station)


def test_e57_roundtrip(cloud, tmp_path):
    import pye57
    path = tmp_path / "test.e57"
    export.save_e57([cloud], path, names=["station_1"])
    e57 = pye57.E57(str(path))
    try:
        assert e57.scan_count == 1
        data = e57.read_scan_raw(0)
        np.testing.assert_allclose(data["cartesianX"],
                                   cloud.xyz[:, 0].astype(np.float64), atol=1e-5)
        np.testing.assert_allclose(data["intensity"],
                                   cloud.intensity.astype(np.float64), atol=0.5)
    finally:
        e57.close()


def test_e57_multistation_with_poses(cloud, tmp_path):
    import pye57
    T = np.eye(4)
    T[:3, 3] = [1.0, 2.0, 0.5]
    path = tmp_path / "multi.e57"
    export.save_e57([cloud, cloud], path, poses=[np.eye(4), T],
                    names=["s1", "s2"])
    e57 = pye57.E57(str(path))
    try:
        assert e57.scan_count == 2
        # Station 2 mit angewandter Pose lesen → verschoben um T
        d_local = e57.read_scan_raw(1)
        d_global = e57.read_scan(1, ignore_missing_fields=True)
        assert d_global["cartesianX"].mean() == pytest.approx(
            d_local["cartesianX"].mean() + 1.0, abs=1e-4)
    finally:
        e57.close()


def test_quaternion_identity():
    q = export.rotation_matrix_to_quaternion(np.eye(3))
    np.testing.assert_allclose(q, [1, 0, 0, 0], atol=1e-12)


def test_quaternion_180deg():
    R = np.diag([1.0, -1.0, -1.0])  # 180° um X
    q = export.rotation_matrix_to_quaternion(R)
    np.testing.assert_allclose(np.abs(q), [0, 1, 0, 0], atol=1e-12)


def test_export_cloud_multi(cloud, tmp_path):
    written = export.export_cloud(cloud, tmp_path / "out" / "scan1",
                                  ["ply", "las", "e57"])
    assert all(p.exists() for p in written)
    assert {p.suffix for p in written} == {".ply", ".las", ".e57"}
