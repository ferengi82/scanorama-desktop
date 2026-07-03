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

from . import filters, floor, rawscan, transform
from .cloud import PointCloud

log = logging.getLogger(__name__)


@dataclass
class ProcessingParams:
    """Alle Parameter der Einzelscan-Verarbeitung (v1-Defaults)."""
    el_offset_deg: float = 0.0
    filters: filters.FilterParams = field(default_factory=filters.FilterParams)
    align_floor: bool = True
    floor_threshold_m: float = 0.02

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ProcessingParams":
        f = d.get("filters", {})
        return ProcessingParams(
            el_offset_deg=d.get("el_offset_deg", 0.0),
            filters=filters.FilterParams(**f),
            align_floor=d.get("align_floor", True),
            floor_threshold_m=d.get("floor_threshold_m", 0.02),
        )


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
    Polar→Kartesisch (mit el_offset) → SOR-Ausreißer →
    optional Bodenausrichtung (Z=0).
    """
    params = params or ProcessingParams()
    t0 = time.monotonic()
    report: dict = {"scan_dir": str(scan_dir), "params": params.to_dict()}

    raw = rawscan.load_scan(scan_dir, force_decode=force_decode)
    report["scan_name"] = raw.name

    raw, raw_report = filters.filter_raw(raw, params.filters)
    report["raw_filter"] = raw_report

    cloud = transform.polar_to_cartesian(raw, params.el_offset_deg)

    cloud, sor_report = filters.remove_outliers(cloud, params.filters)
    report["outlier_filter"] = sor_report

    floor_T = None
    if params.align_floor:
        cloud, floor_T = floor.align_floor(cloud, params.floor_threshold_m)
        report["floor_aligned"] = floor_T is not None

    report["points"] = len(cloud)
    report["duration_s"] = round(time.monotonic() - t0, 2)
    log.info(f"Pipeline {raw.name}: {len(cloud):,} Punkte in "
             f"{report['duration_s']}s")
    return ProcessingResult(cloud=cloud, floor_transform=floor_T, report=report)
