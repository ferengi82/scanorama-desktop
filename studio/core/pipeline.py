"""Verarbeitungs-Pipeline: Scan-Ordner → gefilterte, ausgerichtete Wolke.

Die Pipeline ist die eine Stelle, an der die Einzelschritte
(Laden → Rohfilter → Transformation → Ausreißer → Bodenausrichtung)
in fester Reihenfolge zusammengesetzt werden. UI und CLI rufen nur
:func:`process_scan` auf; die Parameter sind vollständig in
:class:`ProcessingParams` beschrieben und damit in project.json
speicherbar (Reproduzierbarkeit).
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import filters, floor, legacy, rawscan, transform
from .cloud import PointCloud

log = logging.getLogger(__name__)


@dataclass
class ProcessingParams:
    """Alle Parameter der Einzelscan-Verarbeitung (v1-Defaults).

    Strahlkalibrierung: ``calib_from_meta=True`` (Default) nimmt die
    Werte aus dem ``calibration``-Block der meta.json des Scans (dort
    trägt sie der Scanner ein). Die vier Felder hier greifen, wenn die
    meta.json keinen (nicht-null) Block hat oder der Schalter aus ist —
    so lassen sich auch Alt-Scans ohne meta-Block kalibrieren.
    """
    el_offset_deg: float = 0.0
    beam_skew_deg: float = 0.0
    beam_wobble_deg: float = 0.0
    halfplane_split_deg: float = 0.0
    calib_from_meta: bool = True
    filters: filters.FilterParams = field(default_factory=filters.FilterParams)
    align_floor: bool = True
    floor_threshold_m: float = 0.02
    colorize_photos: bool = True     # Punkte aus der Fotorunde einfärben
    unmirror_legacy: bool = True     # Alt-Scans (invert_dir=false) entspiegeln

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ProcessingParams":
        f = d.get("filters", {})
        return ProcessingParams(
            el_offset_deg=d.get("el_offset_deg", 0.0),
            beam_skew_deg=d.get("beam_skew_deg", 0.0),
            beam_wobble_deg=d.get("beam_wobble_deg", 0.0),
            halfplane_split_deg=d.get("halfplane_split_deg", 0.0),
            calib_from_meta=d.get("calib_from_meta", True),
            filters=filters.FilterParams(**f),
            align_floor=d.get("align_floor", True),
            floor_threshold_m=d.get("floor_threshold_m", 0.02),
            colorize_photos=d.get("colorize_photos", True),
            unmirror_legacy=d.get("unmirror_legacy", True),
        )

    def calibration(self) -> transform.LidarCalibration:
        """Kalibrierung aus den Parameter-Feldern (ohne meta.json)."""
        return transform.LidarCalibration(
            el_offset_deg=self.el_offset_deg,
            beam_skew_deg=self.beam_skew_deg,
            beam_wobble_deg=self.beam_wobble_deg,
            halfplane_split_deg=self.halfplane_split_deg,
        )


def resolve_calibration(params: ProcessingParams,
                        meta: dict) -> tuple[transform.LidarCalibration, str]:
    """Effektive Kalibrierung: meta.json des Scans oder Parameter.

    Returns:
        (Kalibrierung, Quelle) — Quelle "meta" | "params"
    """
    if params.calib_from_meta:
        block = meta.get("calibration") or {}
        calib = transform.LidarCalibration.from_dict(block)
        if not calib.is_zero():
            return calib, "meta"
    return params.calibration(), "params"


@dataclass
class ProcessingResult:
    cloud: PointCloud
    floor_transform: np.ndarray | None
    report: dict


def process_scan(scan_dir: str | Path,
                 params: ProcessingParams | None = None,
                 force_decode: bool = False) -> ProcessingResult:
    """Verarbeitet einen Scan-Ordner vollständig.

    Schritte: Laden → Stativ-/Nahbereichsfilter (polar) →
    Polar→Kartesisch (mit Strahlkalibrierung) → SOR-Ausreißer →
    optional Bodenausrichtung (Z=0).
    """
    params = params or ProcessingParams()
    t0 = time.monotonic()
    report: dict = {"scan_dir": str(scan_dir), "params": params.to_dict()}

    raw = rawscan.load_scan(scan_dir, force_decode=force_decode)
    report["scan_name"] = raw.name

    # Alt-Scans (invert_dir=false) sind spiegelverkehrt zur Realität →
    # Azimut negieren und die meta-Blöcke mitspiegeln (siehe legacy.py)
    report["legacy_mirrored"] = False
    if params.unmirror_legacy and legacy.is_mirrored(raw.meta):
        raw.azimuth_deg = -raw.azimuth_deg
        raw.meta = legacy.unmirror_meta(raw.meta)
        report["legacy_mirrored"] = True
        log.info("Alt-Scan (invert_dir=false) — entspiegelt "
                 "(Azimut negiert, Kalibrierung/Fotos angepasst)")

    raw, raw_report = filters.filter_raw(raw, params.filters)
    report["raw_filter"] = raw_report

    calib, calib_source = resolve_calibration(params, raw.meta)
    report["calibration"] = {"source": calib_source, **calib.to_dict()}
    if calib_source == "meta":
        log.info(f"Strahlkalibrierung aus meta.json: "
                 f"skew {calib.beam_skew_deg:+.3f}° "
                 f"wobble {calib.beam_wobble_deg:+.3f}° "
                 f"split {calib.halfplane_split_deg:+.3f}° "
                 f"el_off {calib.el_offset_deg:+.3f}°")
    cloud = transform.polar_to_cartesian(raw, calib)

    cloud, sor_report = filters.remove_outliers(cloud, params.filters)
    report["outlier_filter"] = sor_report

    floor_T = None
    if params.align_floor:
        cloud, floor_T = floor.align_floor(cloud, params.floor_threshold_m)
        report["floor_aligned"] = floor_T is not None

    if params.colorize_photos:
        from . import colorize, photos
        poses = photos.load_station_photos(raw.path, raw.meta)
        if poses:
            cloud.rgb, n_colored = colorize.colorize_cloud(cloud, poses,
                                                           floor_T)
            report["colorized_points"] = n_colored
        else:
            report["colorized_points"] = 0

    report["points"] = len(cloud)
    report["duration_s"] = round(time.monotonic() - t0, 2)
    log.info(f"Pipeline {raw.name}: {len(cloud):,} Punkte in "
             f"{report['duration_s']}s")
    return ProcessingResult(cloud=cloud, floor_transform=floor_T, report=report)
