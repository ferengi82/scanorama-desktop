"""Fotoposen der Fotorunde + Metashape-Reference-Export.

Der Scanner macht nach jedem LiDAR-Scan eine Fotorunde (3× IMX179 auf
dem Drehteller) und schreibt in die meta.json:

    cameras.mounts   Einbaulage jeder Kamera relativ zur Drehachse
    photos[]         pro Foto: file, cam_id, index, azimuth_deg, t_ns

Daraus entsteht hier die Pose jedes Fotos — erst im Plattform-Frame
(POSE_RECIPE des Scanners), dann über die Verarbeitungskette des
Standpunkts ins Projekt-Koordinatensystem:

    T_gesamt = station.pose (Registrierung) · floor_transform (Bodenfit)

Euler-Konvention (Metashape-Reference, durch die validierten v1-CSVs
festgelegt): Yaw ist **Kompass-Yaw** — 0° = Blick +Y, positiv Richtung
+X (im Uhrzeigersinn von oben). Als Kamera-zu-Welt-Matrix heißt das

    R = R_z(−yaw) · R_x(pitch) · R_y(roll)      (Standard-Matrizen)

(v1 baute hier R_z(+yaw) — beim Kombinieren registrierter Standpunkte
drehte das Yaw in die falsche Richtung; Metashape hat es beim Align
stillschweigend wegoptimiert. Hier korrekt.)

Der Metashape-Export schreibt Foto-Kopien mit eindeutigen Labels
(Scanner-Dateinamen wiederholen sich pro Standpunkt!), die Reference-CSV
und eine Start-Kalibrierung — CSV-Format wie im bewährten v1-Workflow
(Metashape liest nur den CSV-Reference-Import, keine XMP-Sidecars).
"""

from __future__ import annotations

import logging
import math
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Sonix GXI-IMX179 USB-Modul (Sony IMX179, 8 MP).
# f/cx/cy aus Metashape-Selbstkalibrierung des Aufbaus (2026-07-04,
# 108 Fotos aligned) — ersetzt die alte 3,5-mm-Datenblatt-Annahme.
SENSOR_W_PX = 3264
SENSOR_H_PX = 2448
PIXEL_UM = 1.4
FOCAL_PX = 2548.876
CX_PX = SENSOR_W_PX / 2 - 19.096                 # Hauptpunkt
CY_PX = SENSOR_H_PX / 2 + 100.349


@dataclass
class PhotoPose:
    """Ein Foto mit Pose (Position in Metern, Winkel in Grad)."""
    label: str            # eindeutiger Name im Export
    source: Path          # Quelldatei (JPEG im Scan-Ordner)
    cam_id: str
    azimuth_deg: float
    x: float
    y: float
    z: float
    yaw: float
    pitch: float
    roll: float


def compute_pose(az_deg: float, mount: dict) -> tuple[float, float, float,
                                                      float, float, float]:
    """Plattform-Pose eines Fotos aus Azimut + Mount (POSE_RECIPE).

    Returns:
        (x, y, z, yaw, pitch, roll)
    """
    a = math.radians(az_deg + mount.get("az_offset_deg", 0.0))
    x = mount.get("r_cam_m", 0.0) * math.sin(a)
    y = mount.get("r_cam_m", 0.0) * math.cos(a)
    z = mount.get("z_cam_m", 0.0)
    yaw = (az_deg + mount.get("az_offset_deg", 0.0)
           + mount.get("yaw_mount_deg", 0.0)) % 360.0
    pitch = mount.get("pitch_mount_deg", 0.0)
    roll = mount.get("roll_mount_deg", 0.0)
    return x, y, z, yaw, pitch, roll


def yaw_pitch_roll_to_matrix(yaw: float, pitch: float, roll: float) -> np.ndarray:
    """Kamera-zu-Welt-Matrix aus Kompass-Yaw/Pitch/Roll (Grad).

    R = R_z(−yaw)·R_x(pitch)·R_y(roll); Kameraachsen bei Identität:
    Blick +Y, rechts +X, oben +Z. Prüfstein: yaw=90° → Blick +X.
    """
    y, p, r = map(math.radians, (yaw, pitch, roll))
    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)
    rz = np.array([[cy, sy, 0], [-sy, cy, 0], [0, 0, 1]])   # R_z(−yaw)
    rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    ry = np.array([[cr, 0, sr], [0, 1, 0], [-sr, 0, cr]])
    return rz @ rx @ ry


def matrix_to_yaw_pitch_roll(m: np.ndarray) -> tuple[float, float, float]:
    """Inverse zu :func:`yaw_pitch_roll_to_matrix` (Grad, Yaw ∈ [0,360))."""
    sp = float(np.clip(m[2][1], -1.0, 1.0))
    pitch = math.asin(sp)
    if abs(math.cos(pitch)) > 1e-7:
        yaw = math.atan2(m[0][1], m[1][1])
        roll = math.atan2(-m[2][0], m[2][2])
    else:
        # Gimbal-Lock (Kamera senkrecht): Roll auf 0 festlegen
        yaw = math.atan2(-m[1][0], m[0][0])
        roll = 0.0
    return (math.degrees(yaw) % 360.0, math.degrees(pitch),
            math.degrees(roll))


def transform_pose(pose: PhotoPose, T: np.ndarray) -> PhotoPose:
    """Wendet eine 4×4-Transformation auf eine Fotopose an."""
    T = np.asarray(T, dtype=np.float64)
    p = T @ np.array([pose.x, pose.y, pose.z, 1.0])
    R = T[:3, :3] @ yaw_pitch_roll_to_matrix(pose.yaw, pose.pitch, pose.roll)
    yaw, pitch, roll = matrix_to_yaw_pitch_roll(R)
    return PhotoPose(label=pose.label, source=pose.source, cam_id=pose.cam_id,
                     azimuth_deg=pose.azimuth_deg,
                     x=float(p[0]), y=float(p[1]), z=float(p[2]),
                     yaw=yaw, pitch=pitch, roll=roll)


def load_station_photos(scan_dir: str | Path, meta: dict,
                        label_prefix: str = "") -> list[PhotoPose]:
    """Fotoposen eines Scans im Plattform-Frame (aus der meta.json).

    Args:
        scan_dir: Scan-Ordner (Fotos liegen unter ``photos/``)
        meta: geladene meta.json des Scans
        label_prefix: z.B. Standpunkt-Name — macht Labels projektweit
            eindeutig (Scanner-Dateinamen wiederholen sich pro Scan!)

    Fotos ohne Mount-Profil oder mit fehlender Datei werden mit Warnung
    übersprungen. Scans ohne Fotorunde → leere Liste.
    """
    scan_dir = Path(scan_dir)
    photos = meta.get("photos") or []
    mounts = (meta.get("cameras") or {}).get("mounts") or {}
    result: list[PhotoPose] = []
    for entry in photos:
        cam_id = entry.get("cam_id", "?")
        mount = mounts.get(cam_id)
        if mount is None:
            log.warning(f"{scan_dir.name}: kein Mount-Profil für '{cam_id}' "
                        f"— Foto übersprungen")
            continue
        source = scan_dir / entry["file"]
        if not source.is_file():
            log.warning(f"{scan_dir.name}: Foto fehlt: {entry['file']}")
            continue
        x, y, z, yaw, pitch, roll = compute_pose(
            float(entry.get("azimuth_deg", 0.0)), mount)
        label = (f"{label_prefix}_{source.name}" if label_prefix
                 else source.name)
        result.append(PhotoPose(label=label, source=source, cam_id=cam_id,
                                azimuth_deg=float(entry.get("azimuth_deg", 0.0)),
                                x=x, y=y, z=z,
                                yaw=yaw, pitch=pitch, roll=roll))
    return result


# ---------------------------------------------------------------------------
# Metashape-Export
# ---------------------------------------------------------------------------

CSV_HEADER = (
    "# Metashape Reference Import — Scanorama Studio\n"
    "# Koordinaten: lokal metrisch (Meter), rechtshändig, X=rechts Y=vorne Z=oben\n"
    "# Yaw=Drehung um Z (0°=+Y, CW positiv), Pitch=um X, Roll=um Y (Grad)\n"
    "Label,X,Y,Z,Yaw,Pitch,Roll\n"
)

CALIB_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<calibration>
  <projection>frame</projection>
  <width>{width}</width>
  <height>{height}</height>
  <f>{f_px:.4f}</f>
  <cx>{cx:.4f}</cx>
  <cy>{cy:.4f}</cy>
  <k1>0</k1>
  <k2>0</k2>
  <k3>0</k3>
  <k4>0</k4>
  <p1>0</p1>
  <p2>0</p2>
  <date>{date}</date>
</calibration>
"""

ANLEITUNG_MD = """# Metashape-Import ({n_photos} Fotos, {n_stations} Standpunkte)

1. **Fotos hinzufügen**: alle JPGs aus diesem Ordner in einen Chunk laden.
2. **Reference importieren**: Reference-Panel → Import →
   `cameras.csv` — Delimiter Komma, Spalten Label/X/Y/Z/Yaw/Pitch/Roll,
   **Header-Zeilen: 4**. Koordinatensystem: Local Coordinates (m).
3. **Kalibrierung** (optional, Startwerte): Tools → Camera Calibration →
   `calibration.xml` laden (Metashape optimiert beim Align weiter).
4. **Punktwolke dazu**: die exportierte E57/PLY-Gesamtwolke desselben
   Projekts importieren — gleiches Koordinatensystem, passt direkt.

Erstellt von Scanorama Studio am {date}.
"""


def export_metashape(stations: list[tuple[str, list[PhotoPose], np.ndarray | None]],
                     out_dir: str | Path) -> Path:
    """Schreibt Foto-Kopien + Reference-CSV + Kalibrierung nach ``out_dir``.

    Args:
        stations: Liste (standpunkt_name, posen_im_plattform_frame, T_gesamt);
            T_gesamt = station_pose @ floor_transform oder None (Identität)
        out_dir: Zielordner (z.B. ``<projekt>/output/metashape``)

    Returns:
        Pfad der geschriebenen CSV.

    Raises:
        ValueError: keine Fotos oder doppelte Labels.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[PhotoPose] = []
    for name, poses, T in stations:
        for pose in poses:
            rows.append(pose if T is None else transform_pose(pose, T))
    if not rows:
        raise ValueError("Keine Fotos zu exportieren — hat mindestens ein "
                         "Standpunkt eine Fotorunde (photos/ + meta.json)?")

    labels = [p.label for p in rows]
    dups = {l for l in labels if labels.count(l) > 1}
    if dups:
        raise ValueError(f"Doppelte Foto-Labels: {sorted(dups)[:5]} — "
                         f"label_prefix pro Standpunkt setzen!")

    lines = [CSV_HEADER]
    for p in rows:
        shutil.copy2(p.source, out_dir / p.label)
        lines.append(f"{p.label},{p.x:.6f},{p.y:.6f},{p.z:.6f},"
                     f"{p.yaw:.4f},{p.pitch:.4f},{p.roll:.4f}\n")

    csv_path = out_dir / "cameras.csv"
    csv_path.write_text("".join(lines), encoding="utf-8")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (out_dir / "calibration.xml").write_text(
        CALIB_TEMPLATE.format(width=SENSOR_W_PX, height=SENSOR_H_PX,
                              f_px=FOCAL_PX,
                              cx=CX_PX - SENSOR_W_PX / 2,
                              cy=CY_PX - SENSOR_H_PX / 2,
                              date=now), encoding="utf-8")
    (out_dir / "ANLEITUNG.md").write_text(
        ANLEITUNG_MD.format(n_photos=len(rows), n_stations=len(stations),
                            date=now), encoding="utf-8")
    log.info(f"Metashape-Export: {out_dir} ({len(rows)} Fotos, "
             f"{len(stations)} Standpunkte)")
    return csv_path
