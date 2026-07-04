"""Einfärbung der Punktwolke (reines numpy, ohne GL/Qt).

Modi:
    intensity — Grauwerte mit leichter Gamma-Anhebung (dunkle Rückstrahlung
                bleibt erkennbar)
    height    — Z-Höhe über eine Turbo-ähnliche Farbrampe, robust skaliert
                (2.–98. Perzentil, Ausreißer sprengen die Skala nicht)
    station   — kategorische Palette pro Standpunkt (für fusionierte Wolken)
"""

from __future__ import annotations

import numpy as np

from ...core.cloud import PointCloud

COLOR_MODES = ("intensity", "height", "station", "rgb")

# Stützstellen einer kompakten Turbo-ähnlichen Rampe (blau→cyan→gelb→rot)
_RAMP = np.array([
    [48, 18, 227],
    [50, 136, 189],
    [26, 188, 156],
    [102, 194, 60],
    [230, 216, 32],
    [244, 109, 67],
    [213, 62, 79],
], dtype=np.float64)

# Kategorische Palette für Standpunkte (10 gut unterscheidbare Farben)
_STATIONS = np.array([
    [86, 180, 233], [230, 159, 0], [0, 158, 115], [240, 66, 129],
    [213, 94, 0], [0, 114, 178], [204, 121, 167], [153, 153, 51],
    [136, 84, 208], [64, 176, 166],
], dtype=np.uint8)


def _ramp_lookup(t: np.ndarray) -> np.ndarray:
    """t ∈ [0,1] → Farbe aus der Rampe (linear interpoliert)."""
    t = np.clip(t, 0.0, 1.0) * (len(_RAMP) - 1)
    i0 = np.floor(t).astype(np.int64)
    i1 = np.minimum(i0 + 1, len(_RAMP) - 1)
    frac = (t - i0)[:, None]
    return (_RAMP[i0] * (1 - frac) + _RAMP[i1] * frac).astype(np.uint8)


def colorize(cloud: PointCloud, mode: str) -> np.ndarray:
    """Farben (N,3) uint8 für den gewählten Modus."""
    n = len(cloud)
    if n == 0:
        return np.empty((0, 3), dtype=np.uint8)

    if mode == "intensity":
        # Gamma 0.6: dunkle Intensitäten anheben, sonst ist fast alles schwarz
        v = (cloud.intensity.astype(np.float64) / 255.0) ** 0.6
        g = (v * 255).astype(np.uint8)
        return np.column_stack((g, g, g))

    if mode == "height":
        z = cloud.xyz[:, 2].astype(np.float64)
        lo, hi = np.percentile(z, [2.0, 98.0])
        if hi - lo < 1e-9:
            lo, hi = z.min(), z.max() + 1e-9
        return _ramp_lookup((z - lo) / (hi - lo))

    if mode == "station":
        return _STATIONS[cloud.station.astype(np.int64) % len(_STATIONS)]

    if mode == "rgb":
        if cloud.rgb is not None:
            return cloud.rgb
        # Wolke ohne Fotos → Intensitäts-Grau als Fallback
        return colorize(cloud, "intensity")

    raise ValueError(f"Unbekannter Farbmodus: {mode!r} (kenne {COLOR_MODES})")
