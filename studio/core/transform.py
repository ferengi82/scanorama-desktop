"""Polar → Kartesisch mit LiDAR-Strahlkalibrierung.

Geometrie-Konvention (identisch zur meta.json des Scanners):
    Elevation 0° = direkt nach oben (Z+), 90° = horizontal vorwärts
    Azimut     = Drehung um die Stehachse (Z)
    rechtshändig: X = rechts, Y = vorne (bei az=0), Z = oben
    Ursprung   = Schnittpunkt Drehachse / LiDAR-Scanebene

Ideales Modell:  r = dist/1000; z = r·cos(el); h = r·sin(el);
                 x = h·sin(az); y = h·cos(az)

Der reale Strahl weicht davon ab — vier Kalibrierwinkel (bestimmt per
Zwei-Lagen-Analyse eines 360°-Scans, ``scanorama-studio-cli calibrate``):

    el_offset_deg        Rotor-Nullpunkt: wahre Elevation = el + Offset
    beam_skew_deg        Strahl zeigt konstant seitlich aus der
                         Rotorebene (ω0)
    beam_wobble_deg      elevationsabhängiger Seitwärtsanteil
                         ω(el) = ω0 + ω1·cos(el)
    halfplane_split_deg  Azimut-Versatz der Halbebenen: el>180° um
                         +split/2, el≤180° um −split/2 um Z gedreht

Strahlmodell (Plattform-Frame ŷ=vorn, x̂=rechts, ẑ=oben):

    el' = el + el_offset
    ω   = beam_skew + beam_wobble·cos(el)
    d_p = cos ω·(cos el'·ẑ + sin el'·ŷ) + sin ω·x̂
    d_p um ±split/2 um ẑ gedreht → Welt: d = R_z(az)·d_p → P = r·d

Ohne den Versatz zwischen den Halbebenen (Naht!) stimmen bei einem
180°-Scan Anfang und Ende nicht überein — die Kalibrierung schließt
die Naht auf Sensorrauschen (~3 mm statt einiger cm).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .cloud import PointCloud
from .rawscan import RawScan

CALIB_KEYS = ("el_offset_deg", "beam_skew_deg", "beam_wobble_deg",
              "halfplane_split_deg")


@dataclass
class LidarCalibration:
    """Strahlkalibrierung des Geräts (alle Winkel in Grad)."""
    el_offset_deg: float = 0.0
    beam_skew_deg: float = 0.0
    beam_wobble_deg: float = 0.0
    halfplane_split_deg: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "LidarCalibration":
        return LidarCalibration(**{k: float(d.get(k, 0.0)) for k in CALIB_KEYS})

    def is_zero(self) -> bool:
        return all(getattr(self, k) == 0.0 for k in CALIB_KEYS)


def beam_directions(elevation_deg: np.ndarray, azimuth_deg: np.ndarray,
                    calib: LidarCalibration) -> np.ndarray:
    """Welt-Einheitsvektoren der Strahlen, (N, 3) in X/Y/Z-Konvention."""
    el_raw = np.mod(elevation_deg.astype(np.float64), 360.0)
    el = np.radians(el_raw)
    elc = np.radians(el_raw + calib.el_offset_deg)
    om = np.radians(calib.beam_skew_deg
                    + calib.beam_wobble_deg * np.cos(el))

    co, so = np.cos(om), np.sin(om)
    dz = co * np.cos(elc)
    dy = co * np.sin(elc)
    dx = so

    # Halbebenen-Split: ±split/2 um ẑ (addiert zum Azimut des Vektors)
    if calib.halfplane_split_deg != 0.0:
        half = np.radians(np.where(el_raw > 180.0,
                                   +calib.halfplane_split_deg / 2,
                                   -calib.halfplane_split_deg / 2))
        ch, sh = np.cos(half), np.sin(half)
        dx, dy = ch * dx + sh * dy, -sh * dx + ch * dy

    # Plattform-Drehung um ẑ (x = h·sin az, y = h·cos az)
    a = np.radians(azimuth_deg.astype(np.float64))
    ca, sa = np.cos(a), np.sin(a)
    wx = ca * dx + sa * dy
    wy = -sa * dx + ca * dy
    return np.column_stack((wx, wy, dz))


def polar_to_cartesian(raw: RawScan,
                       calib: LidarCalibration | None = None) -> PointCloud:
    """Rechnet einen RawScan in eine kartesische Punktwolke um."""
    calib = calib or LidarCalibration()
    r = raw.distance_mm.astype(np.float64) / 1000.0
    d = beam_directions(raw.elevation_deg, raw.azimuth_deg, calib)

    return PointCloud(
        xyz=(r[:, None] * d).astype(np.float32),
        intensity=raw.intensity,
        scanner_dist=r.astype(np.float32),
        meta={
            "scan_name": raw.name,
            "calibration": calib.to_dict(),
            "source": str(raw.path),
        },
    )
