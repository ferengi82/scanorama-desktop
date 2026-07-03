"""CPU-Picking: nächstgelegener Punkt zu einem Bildschirm-Strahl.

Bewusst auf der CPU (numpy) statt über eine GPU-ID-Textur: bei wenigen
Millionen Punkten dauert die Suche nur Millisekunden, ist trivial
testbar und funktioniert unabhängig vom GL-Kontext.
"""

from __future__ import annotations

import numpy as np


def pick_point(xyz: np.ndarray, origin: np.ndarray, direction: np.ndarray,
               max_angle_deg: float = 0.6,
               clip_box: tuple[np.ndarray, np.ndarray] | None = None) -> int | None:
    """Findet den Punkt, der dem Strahl am nächsten liegt.

    Ein Punkt gilt als getroffen, wenn er innerhalb eines Kegels von
    ``max_angle_deg`` um den Strahl liegt (entspricht der "optischen
    Dicke" des Cursors); unter allen Treffern gewinnt der mit dem
    kleinsten Winkelabstand zur Strahlachse, bei ähnlichem Winkel der
    nähere.

    Args:
        xyz: (N,3) Punktkoordinaten
        origin: (3,) Strahl-Ursprung (Kameraposition)
        direction: (3,) normierte Strahlrichtung
        clip_box: optional (min3, max3) — nur sichtbare Punkte innerhalb
            der Clipping-Box sind wählbar

    Returns:
        Index des getroffenen Punkts (bezogen auf das volle Array) oder None
    """
    if len(xyz) == 0:
        return None

    if clip_box is not None:
        lo, hi = clip_box
        visible = np.all((xyz >= lo) & (xyz <= hi), axis=1)
        if not visible.any():
            return None
        idx_map = np.flatnonzero(visible)
        sub = pick_point(xyz[visible], origin, direction, max_angle_deg)
        return None if sub is None else int(idx_map[sub])

    rel = xyz.astype(np.float64) - origin
    t = rel @ direction                     # Projektion auf den Strahl
    ahead = t > 1e-6                        # nur Punkte vor der Kamera
    if not ahead.any():
        return None

    rel = rel[ahead]
    t = t[ahead]
    # Senkrechter Abstand zur Strahlachse, als Winkel normiert
    perp = np.linalg.norm(rel - t[:, None] * direction, axis=1)
    angle = perp / t                        # rad für kleine Winkel
    limit = np.radians(max_angle_deg)
    hit = angle < limit
    if not hit.any():
        return None

    # Score: Winkelabstand dominiert, Entfernung bricht Gleichstände
    # (nahe Punkte gewinnen bei ähnlichem Winkel)
    score = angle[hit] + t[hit] * (limit / 100.0)
    winner_local = np.flatnonzero(hit)[np.argmin(score)]
    return int(np.flatnonzero(ahead)[winner_local])
