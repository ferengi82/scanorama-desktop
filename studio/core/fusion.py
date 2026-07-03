"""Distanzgewichtete Voxel-Fusion registrierter Standpunkte.

Gewichtung nach dem STL27L-Fehlermodell (Inverse-Varianz, Gauß-Markov):

    0.03–2 m : σ ≈ 5 mm   → Gewicht 1/25
    2–8 m    : σ linear 5→15 mm
    >8 m     : σ 15→25 mm

Ein Punkt aus 1.5 m bekommt ~25× mehr Gewicht als einer aus 10 m.
Pro Voxel entsteht der gewichtete Mittelwert; die Standpunkt-Zuordnung
übernimmt der Beitrag mit dem höchsten Gewicht.

Gegenüber v1 vollständig vektorisiert (np.bincount statt Python-Schleife
über Voxel) — wichtig bei fusionierten Wolken mit >10 Mio. Punkten.
"""

from __future__ import annotations

import logging

import numpy as np

from .cloud import PointCloud

log = logging.getLogger(__name__)

DEFAULT_VOXEL_M = 0.03


def distance_weight(dist_m: np.ndarray) -> np.ndarray:
    """Inverse-Varianz-Gewicht pro Punkt (STL27L-Fehlermodell aus v1)."""
    sigma_mm = np.where(
        dist_m <= 2.0,
        5.0,
        np.where(
            dist_m <= 8.0,
            5.0 + (dist_m - 2.0) * (15.0 - 5.0) / 6.0,
            15.0 + (dist_m - 8.0) * (25.0 - 15.0) / 17.0,
        ),
    )
    sigma_mm = np.maximum(sigma_mm, 1.0)
    return 1.0 / (sigma_mm ** 2)


def fuse(clouds: list[PointCloud], poses: list[np.ndarray],
         voxel_size_m: float = DEFAULT_VOXEL_M) -> PointCloud:
    """Transformiert die Wolken mit ihren Posen und fusioniert per Voxel.

    Args:
        clouds: Wolken in scan-lokalen Koordinaten (Reihenfolge = Station)
        poses: 4×4-Transformationen (lokal → Projekt-Rahmen)
        voxel_size_m: Kantenlänge der Fusions-Voxel

    Returns:
        Fusionierte PointCloud (station = dominanter Beitrag pro Voxel)
    """
    if len(clouds) != len(poses):
        raise ValueError("clouds und poses müssen gleich lang sein")
    if not clouds:
        raise ValueError("Keine Wolken zum Fusionieren")

    parts = []
    for idx, (cloud, T) in enumerate(zip(clouds, poses)):
        moved = cloud.transformed(T)
        moved.station = np.full(len(moved), idx, dtype=np.uint16)
        parts.append(moved)
    merged = PointCloud.concat(parts)

    xyz = merged.xyz.astype(np.float64)
    w = distance_weight(merged.scanner_dist.astype(np.float64))
    log.info(f"Fusion: {len(merged):,} Punkte aus {len(clouds)} Standpunkten, "
             f"Voxel {voxel_size_m * 1000:.0f} mm")

    # Voxel-Index pro Punkt → kompakte Gruppen-IDs
    vidx = np.floor(xyz / voxel_size_m).astype(np.int64)
    vidx -= vidx.min(axis=0)
    dims = vidx.max(axis=0) + 1
    flat = (vidx[:, 0] * dims[1] + vidx[:, 1]) * dims[2] + vidx[:, 2]
    unique, groups = np.unique(flat, return_inverse=True)
    n_voxels = len(unique)

    # Gewichtete Mittelwerte vektorisiert (bincount mit weights)
    w_sum = np.bincount(groups, weights=w, minlength=n_voxels)
    w_sum = np.maximum(w_sum, 1e-12)
    out_xyz = np.column_stack([
        np.bincount(groups, weights=xyz[:, k] * w, minlength=n_voxels) / w_sum
        for k in range(3)
    ])
    out_intensity = (np.bincount(
        groups, weights=merged.intensity.astype(np.float64) * w,
        minlength=n_voxels) / w_sum)
    out_dist = (np.bincount(
        groups, weights=merged.scanner_dist.astype(np.float64) * w,
        minlength=n_voxels) / w_sum)

    # Station: Beitrag mit dem höchsten Gewicht gewinnt.
    # Sortierung nach (Voxel, -Gewicht) → erster Eintrag pro Gruppe.
    order = np.lexsort((-w, groups))
    first = np.searchsorted(groups[order], np.arange(n_voxels), side="left")
    out_station = merged.station[order[first]]

    log.info(f"  → {n_voxels:,} fusionierte Punkte")
    return PointCloud(
        xyz=out_xyz.astype(np.float32),
        intensity=np.clip(np.round(out_intensity), 0, 255).astype(np.uint8),
        scanner_dist=out_dist.astype(np.float32),
        station=out_station,
        meta={"scan_name": "fusion",
              "voxel_size_m": voxel_size_m,
              "stations": len(clouds)},
    )
