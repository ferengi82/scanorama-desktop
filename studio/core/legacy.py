"""Entspiegelung von Alt-Scans (invert_dir=false).

Scans, die vor der Drehrichtungs-Umstellung (2026-07-05) aufgenommen
wurden, sind **spiegelverkehrt zur Realität**: Der Plattform-Azimut
lief physisch andersherum, als das Koordinatensystem annimmt. Die
Metashape-Kamerakalibrierung hat das bewiesen — realitätstreue Fotos
lassen sich nur auf eine realitätstreue Wolke konsistent projizieren.

Die Entspiegelung passiert beim Verarbeiten (nicht in den Rohdaten!):

    Azimut            az → −az            (spiegelt die Wolke zurück)
    Strahlkalibrierung skew/wobble/split → Vorzeichen gespiegelt
                       (die Werte in der Alt-meta.json wurden in der
                       gespiegelten Konvention gefittet)
    Foto-Azimute       az → −az           (gleiche Plattform)
    Kamera-Mounts      Alt-meta.json trägt die veralteten v1-Werte —
                       sie werden durch die aktuellen Kalibrierwerte
                       des Geräts ersetzt (gleicher physischer Aufbau)

Erkennung: ``config.motor.invert_dir == false`` in der meta.json.
Neue Scans (invert_dir=true) bleiben unangetastet.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MIRROR_SIGN_KEYS = ("beam_skew_deg", "beam_wobble_deg", "halfplane_split_deg")


def is_mirrored(meta: dict) -> bool:
    """True für Alt-Scans mit gespiegelter Drehrichtungs-Konvention."""
    return (meta.get("config", {}).get("motor", {})
            .get("invert_dir") is False)


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


def unmirror_meta(meta: dict) -> dict:
    """Angepasste Kopie der meta.json für die entspiegelte Auswertung.

    - Kalibrier-Vorzeichen gespiegelt (skew/wobble/split)
    - Foto-Azimute negiert
    - Kamera-Mounts durch die aktuellen Gerätewerte ersetzt
    """
    import copy

    meta = copy.deepcopy(meta)

    calib = meta.get("calibration") or {}
    for k in MIRROR_SIGN_KEYS:
        if k in calib:
            calib[k] = -calib[k]

    for entry in meta.get("photos") or []:
        entry["azimuth_deg"] = -float(entry.get("azimuth_deg", 0.0))

    cameras = meta.get("cameras")
    if cameras and cameras.get("mounts"):
        try:
            from scanorama.camera.mounts import load_mounts
            current = {cid: m.to_dict() for cid, m in load_mounts().items()}
            for cid, old in cameras["mounts"].items():
                if cid in current:
                    device = old.get("device")
                    cameras["mounts"][cid] = dict(current[cid])
                    if device is not None:
                        cameras["mounts"][cid]["device"] = device
        except ImportError:
            log.warning("scanorama-Paket nicht verfügbar — Alt-Mounts "
                        "bleiben unverändert (Einfärbung ggf. falsch)")
    return meta
