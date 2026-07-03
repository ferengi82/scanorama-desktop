"""Filter für Roh- und Punktdaten.

Defaults stammen aus Scanner-v1 (Interview-Entscheidung):
    - Stativ-Bereich: Elevation 165°–195° verwerfen (Stativ verdeckt
      die Unterseite; 0° = oben, 180° = unten)
    - Nahbereich: Punkte näher als 0.30 m am Scanner verwerfen
      (Reflexe von Stativ/Gehäuse)
    - Statistischer Ausreißerfilter (SOR): Punkte, deren mittlerer
      Nachbarabstand weit über dem Durchschnitt liegt, entfernen

Stativ- und Nahbereichsfilter arbeiten auf den polaren Rohdaten
(billig, vor der Transformation); SOR braucht die kartesische Wolke.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from .cloud import PointCloud
from .rawscan import RawScan

log = logging.getLogger(__name__)


@dataclass
class FilterParams:
    """Filter-Parameter mit den v1-Defaults."""
    block_start_deg: float = 165.0   # Stativ-Bereich Anfang (0 = deaktiviert
    block_end_deg: float = 195.0     # wenn start >= end)
    min_dist_m: float = 0.30         # Nahbereich; 0 = deaktiviert
    sor_enabled: bool = True
    sor_neighbors: int = 20
    sor_std_ratio: float = 2.0


def filter_raw(raw: RawScan, params: FilterParams) -> tuple[RawScan, dict]:
    """Wendet Stativ- und Nahbereichsfilter auf polare Rohdaten an.

    Returns:
        (gefilterter RawScan, Report mit Entfernt-Zählern)
    """
    n0 = len(raw)
    keep = np.ones(n0, dtype=bool)
    report = {"input": n0}

    if params.block_start_deg < params.block_end_deg:
        blocked = ((raw.elevation_deg >= params.block_start_deg)
                   & (raw.elevation_deg <= params.block_end_deg))
        keep &= ~blocked
        report["removed_tripod"] = int(blocked.sum())
    else:
        report["removed_tripod"] = 0

    if params.min_dist_m > 0:
        near = raw.distance_mm < params.min_dist_m * 1000.0
        removed_near = int((near & keep).sum())
        keep &= ~near
        report["removed_near"] = removed_near
    else:
        report["removed_near"] = 0

    out = RawScan(
        path=raw.path,
        name=raw.name,
        elevation_deg=raw.elevation_deg[keep],
        azimuth_deg=raw.azimuth_deg[keep],
        distance_mm=raw.distance_mm[keep],
        intensity=raw.intensity[keep],
        t_ns=raw.t_ns[keep],
        meta=raw.meta,
    )
    report["output"] = len(out)
    log.info(f"Rohfilter {raw.name}: {n0:,} → {len(out):,} Punkte "
             f"(Stativ {report['removed_tripod']:,}, "
             f"Nahbereich {report['removed_near']:,})")
    return out, report


def remove_outliers(cloud: PointCloud, params: FilterParams) -> tuple[PointCloud, dict]:
    """Statistischer Ausreißerfilter (SOR) über Open3D.

    Für jeden Punkt wird der mittlere Abstand zu ``sor_neighbors``
    Nachbarn berechnet; Punkte jenseits von
    ``mean + sor_std_ratio · std`` fliegen raus.
    """
    n0 = len(cloud)
    if not params.sor_enabled or n0 == 0:
        return cloud, {"removed_outliers": 0, "output": n0}

    pc = cloud.to_open3d()
    _, inlier_idx = pc.remove_statistical_outlier(
        nb_neighbors=params.sor_neighbors,
        std_ratio=params.sor_std_ratio,
    )
    mask = np.zeros(n0, dtype=bool)
    mask[np.asarray(inlier_idx, dtype=np.int64)] = True
    out = cloud.subset(mask)
    removed = n0 - len(out)
    log.info(f"Ausreißerfilter: {removed:,} von {n0:,} Punkten entfernt "
             f"({removed / n0 * 100:.2f}%)")
    return out, {"removed_outliers": removed, "output": len(out)}
