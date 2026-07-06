"""Reparatur veralteter Kamera-Mounts in Alt-meta.json.

Scans zwischen v1 und der Mount-Kalibrierung vom 2026-07-05 tragen die
alten Kamera-Mount-Werte (alle ``roll_mount_deg == 0`` — physisch
unmöglich, die Module sind hochkant verbaut). ``refresh_stale_mounts``
ersetzt sie beim Verarbeiten durch die aktuellen Gerätewerte, damit die
Foto-Einfärbung stimmt. Betrifft nur die Kamera-Mounts, nicht die
Punktwolken-Geometrie.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def refresh_stale_mounts(meta: dict) -> bool:
    """Ersetzt veraltete Kamera-Mounts (in place) durch aktuelle Gerätewerte.

    Scans zwischen v1 und der Mount-Kalibrierung vom 2026-07-05 tragen
    die alten Werte (alle roll_mount_deg == 0 — physisch unmöglich, die
    Module sind hochkant verbaut). Returns True, wenn ersetzt wurde.
    """
    mounts = (meta.get("cameras") or {}).get("mounts") or {}
    if not mounts:
        return False
    if any(abs(m.get("roll_mount_deg", 0.0)) > 10 for m in mounts.values()):
        return False                      # bereits kalibrierte Werte
    try:
        from scanorama.camera.mounts import load_mounts
    except ImportError:
        log.warning("scanorama-Paket fehlt — veraltete Mounts bleiben")
        return False
    current = {cid: m.to_dict() for cid, m in load_mounts().items()}
    for cid, old in mounts.items():
        if cid in current:
            device = old.get("device")
            mounts[cid] = dict(current[cid])
            if device is not None:
                mounts[cid]["device"] = device
    log.info("Veraltete Kamera-Mounts (roll=0) durch aktuelle "
             "Kalibrierwerte ersetzt")
    return True
