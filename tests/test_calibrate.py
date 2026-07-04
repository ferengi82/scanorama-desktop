"""Tests für Strahlkalibrierung: transform-Modell + calibrate-Fit.

Synthetik: Zylinderraum (Radius D, Boden/Decke) wird mit einem
bekannten „wahren" Kalibrierfehler abgetastet. Der Fit muss die Naht
schließen und die Wahrheit näherungsweise wiederfinden.
"""

import numpy as np
import pytest

from studio.core.calibrate import (CalibrationError, _seam_cost,
                                   fit_calibration)
from studio.core.pipeline import ProcessingParams, resolve_calibration
from studio.core.transform import LidarCalibration, beam_directions

RNG = np.random.default_rng(7)

D_WALL = 3.0     # m Zylinderradius
H_CEIL = 1.4     # m Decke über Scanebene
H_FLOOR = 1.1    # m Boden unter Scanebene
TRUE = LidarCalibration(el_offset_deg=0.2, beam_skew_deg=0.5,
                        beam_wobble_deg=0.7, halfplane_split_deg=-1.2)


def synth_scan(calib: LidarCalibration, noise_mm: float = 5.0):
    """Erzeugt (el, az, dist_mm) eines 360°-Scans.

    Sternförmiger Raum: Wandradius über den Azimut moduliert („Möbel"),
    sonst wären die Azimut-Gradienten null und die Naht unsichtbar.
    """
    el = np.tile(np.arange(0.0, 360.0, 0.72), 720)
    az = np.repeat(np.arange(0.0, 360.0, 0.5), 500)

    d = beam_directions(el, az, calib)
    h = np.hypot(d[:, 0], d[:, 1])
    psi = np.arctan2(d[:, 0], d[:, 1])
    wall = D_WALL + 0.4 * np.sin(3 * psi) + 0.2 * np.cos(5 * psi)
    with np.errstate(divide="ignore"):
        r_wall = np.where(h > 1e-9, wall / h, np.inf)
        r_ceil = np.where(d[:, 2] > 1e-9, H_CEIL / d[:, 2], np.inf)
        r_floor = np.where(d[:, 2] < -1e-9, H_FLOOR / (-d[:, 2]), np.inf)
    r = np.minimum(np.minimum(r_wall, r_ceil), r_floor)
    r = r + RNG.normal(0.0, noise_mm / 1000.0, len(r))
    return el, az, r


def write_scan_dir(tmp_path, el, az, r):
    scan = tmp_path / "2026-07-04_scan_09_001"
    scan.mkdir()
    np.savez_compressed(
        scan / "points.npz",
        elevation_deg=el.astype(np.float32),
        azimuth_deg=az.astype(np.float32),
        distance_mm=np.clip(r * 1000, 0, 65535).astype(np.uint16),
        intensity=np.full(len(r), 100, np.uint8),
        t_ns=np.zeros(len(r), np.int64),
    )
    return scan


def test_transform_rekonstruiert_geometrie():
    """Mit der wahren Kalibrierung liegen die Wandpunkte auf der Wand."""
    el, az, r = synth_scan(TRUE, noise_mm=0.0)
    d = beam_directions(el, az, TRUE)
    xyz = r[:, None] * d
    wall = (np.abs(xyz[:, 2]) < 1.0) & (r < D_WALL * 1.5)
    psi = np.arctan2(xyz[wall, 0], xyz[wall, 1])
    soll = D_WALL + 0.4 * np.sin(3 * psi) + 0.2 * np.cos(5 * psi)
    radius = np.hypot(xyz[wall, 0], xyz[wall, 1])
    assert np.abs(radius - soll).max() < 0.002


def test_naht_offen_ohne_kalibrierung():
    el, az, r = synth_scan(TRUE)
    seam_raw, _ = _seam_cost(el, az, r, LidarCalibration())
    seam_true, _ = _seam_cost(el, az, r, TRUE)
    assert seam_raw > 5 * seam_true      # Fehler dominiert das Rauschen
    assert seam_true < 10                # mit Wahrheit ~Rauschniveau


def test_fit_findet_kalibrierung(tmp_path):
    el, az, r = synth_scan(TRUE)
    scan = write_scan_dir(tmp_path, el, az, r)
    result = fit_calibration(scan, subsample=1)
    c = result.calibration
    assert result.seam_after_mm < result.seam_before_mm / 3
    assert result.seam_after_mm < 10
    assert abs(c.el_offset_deg - TRUE.el_offset_deg) < 0.25
    # skew/wobble/split sind untereinander teilentartet (gleiche Naht-
    # Wirkung) — nur die Größenordnung prüfen, nicht den exakten Wert
    assert abs(c.halfplane_split_deg - TRUE.halfplane_split_deg) < 1.0


def test_fit_lehnt_teilscan_ab(tmp_path):
    el, az, r = synth_scan(TRUE)
    keep = az <= 180
    scan = write_scan_dir(tmp_path, el[keep], az[keep], r[keep])
    with pytest.raises(CalibrationError):
        fit_calibration(scan)


def test_resolve_calibration_meta_vor_params():
    params = ProcessingParams(el_offset_deg=9.9)
    meta = {"calibration": {"el_offset_deg": 0.2, "beam_skew_deg": 0.5,
                            "beam_wobble_deg": 0.7,
                            "halfplane_split_deg": -1.2, "model": "…"}}
    calib, source = resolve_calibration(params, meta)
    assert source == "meta"
    assert calib.beam_skew_deg == 0.5

    # meta ohne/mit Null-Block → Parameter-Felder greifen
    calib, source = resolve_calibration(params, {})
    assert source == "params" and calib.el_offset_deg == 9.9
    calib, source = resolve_calibration(
        params, {"calibration": {"el_offset_deg": 0.0}})
    assert source == "params"

    # Schalter aus → immer Parameter
    params.calib_from_meta = False
    calib, source = resolve_calibration(params, meta)
    assert source == "params" and calib.el_offset_deg == 9.9
