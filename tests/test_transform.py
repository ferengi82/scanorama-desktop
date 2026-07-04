"""Tests: Polar → Kartesisch (bekannte Winkel → bekannte Koordinaten)."""

from pathlib import Path

import numpy as np
import pytest

from studio.core.rawscan import RawScan
from studio.core.transform import LidarCalibration, polar_to_cartesian


def _raw(elevations, azimuths, dist_mm=1000):
    n = len(elevations)
    return RawScan(
        path=Path("."), name="synthetisch",
        elevation_deg=np.array(elevations, dtype=np.float32),
        azimuth_deg=np.array(azimuths, dtype=np.float32),
        distance_mm=np.full(n, dist_mm, dtype=np.uint16),
        intensity=np.full(n, 100, dtype=np.uint8),
        t_ns=np.zeros(n, dtype=np.int64),
    )


@pytest.mark.parametrize("el,az,expected", [
    (0,   0,  (0, 0, 1)),     # direkt nach oben
    (90,  0,  (0, 1, 0)),     # horizontal vorwärts (Y+)
    (180, 0,  (0, 0, -1)),    # direkt nach unten
    (270, 0,  (0, -1, 0)),    # horizontal rückwärts
    (90,  90, (1, 0, 0)),     # vorwärts + 90° Azimut → X+
    (90, 180, (0, -1, 0)),    # vorwärts + 180° Azimut → Y-
])
def test_known_directions(el, az, expected):
    cloud = polar_to_cartesian(_raw([el], [az], dist_mm=1000))
    np.testing.assert_allclose(cloud.xyz[0], expected, atol=1e-6)


def test_el_offset_shifts_elevation():
    """el=80 mit Offset +10 muss el=90 ohne Offset entsprechen."""
    a = polar_to_cartesian(_raw([80.0], [0.0]),
                           LidarCalibration(el_offset_deg=10.0))
    b = polar_to_cartesian(_raw([90.0], [0.0]))
    np.testing.assert_allclose(a.xyz, b.xyz, atol=1e-6)


def test_scanner_dist_in_meters():
    cloud = polar_to_cartesian(_raw([45.0], [10.0], dist_mm=2500))
    assert cloud.scanner_dist[0] == pytest.approx(2.5)
    assert np.linalg.norm(cloud.xyz[0]) == pytest.approx(2.5, abs=1e-5)


def test_metadata_carried():
    cloud = polar_to_cartesian(_raw([10], [20]),
                               LidarCalibration(el_offset_deg=1.5))
    assert cloud.meta["calibration"]["el_offset_deg"] == 1.5
    assert cloud.meta["scan_name"] == "synthetisch"


def test_halfplane_split_verschiebt_nur_azimut():
    """Split ±c/2: hintere Halbebene +, vordere −, Distanz unverändert."""
    calib = LidarCalibration(halfplane_split_deg=2.0)
    front = polar_to_cartesian(_raw([90.0], [0.0]), calib)
    back = polar_to_cartesian(_raw([270.0], [0.0]), calib)
    # Azimut des Punkts: atan2(x, y); vorn −1°, hinten 180°+1°
    az_front = np.degrees(np.arctan2(front.xyz[0, 0], front.xyz[0, 1]))
    az_back = np.degrees(np.arctan2(back.xyz[0, 0], back.xyz[0, 1])) % 360
    assert az_front == pytest.approx(-1.0, abs=1e-4)
    assert az_back == pytest.approx(181.0, abs=1e-4)
    assert np.linalg.norm(front.xyz[0]) == pytest.approx(1.0, abs=1e-6)
