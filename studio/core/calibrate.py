"""Strahlkalibrierung aus einem 360°-Scan bestimmen (Zwei-Lagen-Analyse).

Bei einem 360°-Plattform-Scan wird jede Weltrichtung zweimal gemessen:
von der vorderen Halbebene (el ≤ 180°) und — 180° Plattformdrehung
später — von der hinteren (el > 180°). Ohne Kalibrierfehler messen
beide Lagen dieselbe Distanz. Die vier Winkel der
:class:`~studio.core.transform.LidarCalibration` werden so optimiert,
dass die mediane Distanz-Differenz über alle gemeinsamen
Richtungs-Bins minimal wird (nur Bins mit Azimut-Gradient — dort ist
der Fehler sichtbar).

Aufruf: ``scanorama-studio-cli calibrate <360°-Scan-Ordner>``
Die gefundenen Werte gehören auf den Pi nach
``~/.config/scanorama/calibration.json`` — dann trägt der Scanner sie
in jede meta.json ein und Studio wendet sie automatisch an.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import rawscan
from .transform import LidarCalibration, beam_directions

log = logging.getLogger(__name__)

MIN_DIST_M = 0.30      # Nahbereich raus (Eigenbau/Stativ)
POLAR_MIN = 10.0       # Zenit: Azimut-Zuordnung instabil
POLAR_MAX = 150.0      # Stativ-Bereich raus
MAX_BIN_STD = 0.03     # m — Kanten-Bins verwerfen
MIN_GRAD = 0.3         # m/rad — nur Bins, in denen ψ-Fehler sichtbar ist
MAX_GRAD = 5.0


class CalibrationError(Exception):
    """Scan für die Kalibrierung ungeeignet (kein 360°-Scan?)."""


@dataclass
class CalibrationResult:
    calibration: LidarCalibration
    seam_before_mm: float     # Median |Δr| unkalibriert
    seam_after_mm: float      # Median |Δr| mit Ergebnis
    bins: int                 # bewertete Richtungs-Bins
    evaluations: int          # Kostenfunktions-Auswertungen


def _seam_cost(el, az, r, calib: LidarCalibration) -> tuple[float, int]:
    """Median |Δr| [mm] über gradiententragende Zwei-Lagen-Bins."""
    d = beam_directions(el, az, calib)
    theta = np.degrees(np.arccos(np.clip(d[:, 2], -1.0, 1.0)))
    psi = np.mod(np.degrees(np.arctan2(d[:, 0], d[:, 1])), 360.0)
    face2 = np.mod(el, 360.0) > 180.0

    ok = (r >= MIN_DIST_M) & (theta >= POLAR_MIN) & (theta <= POLAR_MAX)
    th, ps, rr, f2 = theta[ok], psi[ok], r[ok], face2[ok]

    n_th, n_ps = 180, 360
    flat = (np.clip(th.astype(np.int64), 0, n_th - 1) * n_ps
            + np.clip(ps.astype(np.int64), 0, n_ps - 1))
    size = n_th * n_ps
    fields = []
    for sel in (~f2, f2):
        cnt = np.bincount(flat[sel], minlength=size).astype(np.float64)
        s = np.bincount(flat[sel], weights=rr[sel], minlength=size)
        s2 = np.bincount(flat[sel], weights=rr[sel] ** 2, minlength=size)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = s / cnt
            var = np.maximum(s2 / cnt - mean ** 2, 0.0)
        mean[cnt < 2] = np.nan
        fields.append((mean.reshape(n_th, n_ps),
                       np.sqrt(var).reshape(n_th, n_ps)))
    (m1, sd1), (m2, sd2) = fields

    rmean = 0.5 * (m1 + m2)
    bin_rad = np.radians(1.0)
    dps = (np.roll(rmean, -1, 1) - np.roll(rmean, 1, 1)) / (2 * bin_rad)
    good = (np.isfinite(m1) & np.isfinite(m2) & np.isfinite(dps)
            & (sd1 < MAX_BIN_STD) & (sd2 < MAX_BIN_STD)
            & (np.abs(dps) > MIN_GRAD) & (np.abs(dps) < MAX_GRAD))
    n = int(good.sum())
    if n < 300:
        raise CalibrationError(
            f"Nur {n} auswertbare Zwei-Lagen-Bins — die Kalibrierung "
            f"braucht einen vollen 360°-Scan mit Struktur im Raum")
    return float(np.median(np.abs((m1 - m2)[good])) * 1000), n


def fit_calibration(scan_dir: str | Path,
                    subsample: int = 3) -> CalibrationResult:
    """Bestimmt die Strahlkalibrierung aus einem 360°-Scan.

    Optimierung: Pattern-Search (Koordinaten-Suche mit Schritt-
    halbierung) auf dem Naht-Kriterium — robust, ohne Gradienten,
    ohne zusätzliche Abhängigkeiten.
    """
    raw = rawscan.load_scan(scan_dir)
    az_span = float(raw.azimuth_deg.max() - raw.azimuth_deg.min())
    if az_span < 350:
        raise CalibrationError(
            f"Azimut-Bereich nur {az_span:.0f}° — für die Zwei-Lagen-"
            f"Kalibrierung ist ein voller 360°-Scan nötig "
            f"(scanorama scan --az-end 360)")

    el = raw.elevation_deg.astype(np.float64)[::subsample]
    az = raw.azimuth_deg.astype(np.float64)[::subsample]
    r = (raw.distance_mm.astype(np.float64) / 1000.0)[::subsample]

    evals = 0

    def cost(p: np.ndarray) -> float:
        nonlocal evals, bins
        evals += 1
        c, bins = _seam_cost(el, az, r, LidarCalibration(*p))
        return c

    bins = 0
    p = np.zeros(4)   # (el_offset, skew, wobble, split)
    before = cost(p)

    # Grobsuche über den Halbebenen-Split (stärkster, mehrdeutigster Term)
    best_split, best_c = 0.0, before
    for split in np.arange(-2.5, 2.6, 0.5):
        c = cost(np.array([0.0, 0.0, 0.0, split]))
        if c < best_c:
            best_c, best_split = c, split
    p[3] = best_split
    current = best_c

    # Pattern-Search über alle vier Winkel
    step = 0.4
    while step >= 0.01:
        improved = False
        for i in range(4):
            for sign in (+1.0, -1.0):
                trial = p.copy()
                trial[i] += sign * step
                c = cost(trial)
                if c < current - 1e-4:
                    p, current, improved = trial, c, True
                    break
        if not improved:
            step /= 2

    calib = LidarCalibration(*np.round(p, 3))
    after, bins = _seam_cost(el, az, r, calib)
    log.info(f"Kalibrierung: el_off {calib.el_offset_deg:+.3f}° "
             f"skew {calib.beam_skew_deg:+.3f}° "
             f"wobble {calib.beam_wobble_deg:+.3f}° "
             f"split {calib.halfplane_split_deg:+.3f}° — "
             f"Naht {before:.1f} → {after:.1f} mm ({evals} Auswertungen)")
    return CalibrationResult(calibration=calib, seam_before_mm=before,
                             seam_after_mm=after, bins=bins,
                             evaluations=evals)
