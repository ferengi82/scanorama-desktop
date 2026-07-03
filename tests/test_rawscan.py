"""Tests: Scan-Ordner laden und validieren."""

import numpy as np
import pytest

from studio.core import rawscan


def test_load_mock_scan(mock_scan_dir):
    raw = rawscan.load_scan(mock_scan_dir)
    assert len(raw) > 10000
    assert raw.name == mock_scan_dir.name
    assert raw.meta["schema_version"] == 1
    assert raw.azimuth_deg.min() >= -0.5
    assert raw.azimuth_deg.max() == pytest.approx(30.0, abs=1.0)
    assert raw.elevation_deg.min() >= 0.0
    assert raw.elevation_deg.max() < 360.0
    assert raw.distance_mm.dtype == np.uint16


def test_is_scan_folder(mock_scan_dir, tmp_path):
    assert rawscan.is_scan_folder(mock_scan_dir)
    assert not rawscan.is_scan_folder(tmp_path)
    assert not rawscan.is_scan_folder(tmp_path / "gibtsnicht")


def test_find_scan_folders(mock_scan_dir):
    found = rawscan.find_scan_folders(mock_scan_dir.parent)
    assert mock_scan_dir in found


def test_load_invalid_folder_raises(tmp_path):
    with pytest.raises(rawscan.ScanFolderError):
        rawscan.load_scan(tmp_path)


def test_force_decode_matches_existing(mock_scan_dir):
    """Neu-Dekodieren aus Rohdaten liefert dieselben Punkte wie points.npz."""
    a = rawscan.load_scan(mock_scan_dir)
    b = rawscan.load_scan(mock_scan_dir, force_decode=True)
    assert len(a) == len(b)
    np.testing.assert_array_equal(a.distance_mm, b.distance_mm)
    np.testing.assert_allclose(a.azimuth_deg, b.azimuth_deg, atol=1e-6)
