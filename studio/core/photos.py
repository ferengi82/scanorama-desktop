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


# Metashape-Kameraachsen relativ zu meinen (X rechts, Y Blick, Z oben):
# MS-X = −X, MS-Y = +Z, MS-Z = +Y (Blick). Datengetrieben bestimmt aus
# 108 Foto-Paaren (OPK + Matrix) eines Metashape-Alignments — Reststreuung
# 4° = Alignment-Rauschen. Metashape schreibt R_file = (Rx(ω)·Ry(φ)·Rz(κ))ᵀ
# und es gilt R_fileᵀ = M_kamera·Q (im selben Weltrahmen).
_MS_Q = np.array([[-1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]])


def matrix_to_opk(M: np.ndarray) -> tuple[float, float, float]:
    """Kamera-zu-Welt-Matrix (meine Achsen) → Metashape Omega/Phi/Kappa.

    A = M·Q = Rx(ω)·Ry(φ)·Rz(κ)  (XYZ-Zerlegung, Grad).
    """
    A = np.asarray(M, dtype=np.float64) @ _MS_Q
    sp = float(np.clip(A[0, 2], -1.0, 1.0))
    phi = math.asin(sp)
    if abs(math.cos(phi)) > 1e-7:
        omega = math.atan2(-A[1, 2], A[2, 2])
        kappa = math.atan2(-A[0, 1], A[0, 0])
    else:
        omega = math.atan2(A[1, 0], A[1, 1])
        kappa = 0.0
    return (math.degrees(omega), math.degrees(phi), math.degrees(kappa))


def opk_to_matrix(omega: float, phi: float, kappa: float) -> np.ndarray:
    """Inverse zu :func:`matrix_to_opk` (für Tests/Roundtrip)."""
    o, p, k = map(math.radians, (omega, phi, kappa))
    rx = np.array([[1, 0, 0],
                   [0, math.cos(o), -math.sin(o)],
                   [0, math.sin(o), math.cos(o)]])
    ry = np.array([[math.cos(p), 0, math.sin(p)],
                   [0, 1, 0],
                   [-math.sin(p), 0, math.cos(p)]])
    rz = np.array([[math.cos(k), -math.sin(k), 0],
                   [math.sin(k), math.cos(k), 0],
                   [0, 0, 1]])
    return (rx @ ry @ rz) @ _MS_Q.T


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
                        label_prefix: str = "",
                        mounts_override: dict | None = None) -> list[PhotoPose]:
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
    mounts = dict((meta.get("cameras") or {}).get("mounts") or {})
    if mounts_override:
        mounts.update(mounts_override)
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
    "# Rotationswinkel: Omega/Phi/Kappa (Reference-Settings → Rotation angles!)\n"
    "Label,X,Y,Z,Omega,Phi,Kappa\n"
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

Die Fotos sind bereits **aufrecht gedreht** (die Kameras sind hochkant
verbaut) — die Posen in cameras.csv passen zu den gedrehten Kopien.

1. **Fotos hinzufügen**: alle JPGs aus diesem Ordner in einen Chunk laden.
2. **Kalibriergruppen**: Tools → Camera Calibration → die Bilder nach
   Dateinamen-Endung in drei Gruppen teilen (`_usb0` / `_usb1` / `_usb2`)
   und je Gruppe die passende `calibration_usbN.xml` als Initial laden
   (Metashape optimiert beim Align weiter).
3. **Reference importieren**: Reference-Panel → Import →
   `cameras.csv` — Delimiter Komma, Spalten Label/X/Y/Z + Winkel,
   **Header-Zeilen: 4**, Koordinatensystem: Local Coordinates (m).
   WICHTIG: Reference-Settings → Rotation angles auf
   **„Omega, Phi, Kappa"** stellen (nicht Yaw/Pitch/Roll)!
4. **Punktwolke dazu**: die exportierte E57/PLY-Gesamtwolke desselben
   Projekts importieren — gleiches Koordinatensystem, passt direkt.

Erstellt von Scanorama Studio am {date}.
"""


def _upright(pose: PhotoPose) -> tuple[PhotoPose, int]:
    """Dreht die Pose so um die Blickachse, dass Roll ≈ 0 wird.

    Returns:
        (neue Pose, Bilddrehung in Grad für PIL.rotate — CCW positiv)

    Kamera-Drehung um die Blickachse (meine Y-Achse) um ψ entspricht
    einer Bildinhalts-Drehung um −ψ; wir wählen das Vielfache von 90°,
    das den Roll minimiert.
    """
    M = yaw_pitch_roll_to_matrix(pose.yaw, pose.pitch, pose.roll)
    best = None
    for psi in (0.0, 90.0, -90.0, 180.0):
        p = math.radians(psi)
        ry = np.array([[math.cos(p), 0, math.sin(p)], [0, 1, 0],
                       [-math.sin(p), 0, math.cos(p)]])
        yaw, pitch, roll = matrix_to_yaw_pitch_roll(M @ ry)
        if best is None or abs(roll) < abs(best[0]):
            best = (roll, psi, yaw, pitch)
    roll, psi, yaw, pitch = best
    new = PhotoPose(label=pose.label, source=pose.source, cam_id=pose.cam_id,
                    azimuth_deg=pose.azimuth_deg, x=pose.x, y=pose.y,
                    z=pose.z, yaw=yaw, pitch=pitch, roll=roll)
    return new, int(round(psi)) % 360


def _rotated_calibration(img_rot: int) -> tuple[int, int, float, float]:
    """Sensorgröße + Hauptpunktversatz nach Bilddrehung (PIL, CCW positiv)."""
    dx = CX_PX - SENSOR_W_PX / 2
    dy = CY_PX - SENSOR_H_PX / 2
    r = img_rot % 360
    if r == 90:                              # CCW: (dx,dy) → (dy,−dx)
        return SENSOR_H_PX, SENSOR_W_PX, dy, -dx
    if r == 270:                             # CW:  (dx,dy) → (−dy,dx)
        return SENSOR_H_PX, SENSOR_W_PX, -dy, dx
    if r == 180:
        return SENSOR_W_PX, SENSOR_H_PX, -dx, -dy
    return SENSOR_W_PX, SENSOR_H_PX, dx, dy


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

    rows: list[tuple[PhotoPose, int]] = []
    cam_rot: dict[str, int] = {}
    for name, poses, T in stations:
        for pose in poses:
            p = pose if T is None else transform_pose(pose, T)
            p, img_rot = _upright(p)
            rows.append((p, img_rot))
            cam_rot.setdefault(p.cam_id, img_rot)
    if not rows:
        raise ValueError("Keine Fotos zu exportieren — hat mindestens ein "
                         "Standpunkt eine Fotorunde (photos/ + meta.json)?")

    labels = [p.label for p, _ in rows]
    dups = {l for l in labels if labels.count(l) > 1}
    if dups:
        raise ValueError(f"Doppelte Foto-Labels: {sorted(dups)[:5]} — "
                         f"label_prefix pro Standpunkt setzen!")

    from PIL import Image

    lines = [CSV_HEADER]
    for p, img_rot in rows:
        target = out_dir / p.label
        if img_rot == 0:
            shutil.copy2(p.source, target)
        else:
            with Image.open(p.source) as im:
                im.rotate(img_rot, expand=True).save(target, "JPEG",
                                                     quality=92)
        M = yaw_pitch_roll_to_matrix(p.yaw, p.pitch, p.roll)
        omega, phi, kappa = matrix_to_opk(M)
        lines.append(f"{p.label},{p.x:.6f},{p.y:.6f},{p.z:.6f},"
                     f"{omega:.4f},{phi:.4f},{kappa:.4f}\n")

    csv_path = out_dir / "cameras.csv"
    csv_path.write_text("".join(lines), encoding="utf-8")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for cam_id, img_rot in sorted(cam_rot.items()):
        w, h, cx_off, cy_off = _rotated_calibration(img_rot)
        (out_dir / f"calibration_{cam_id}.xml").write_text(
            CALIB_TEMPLATE.format(width=w, height=h, f_px=FOCAL_PX,
                                  cx=cx_off, cy=cy_off, date=now),
            encoding="utf-8")
    (out_dir / "ANLEITUNG.md").write_text(
        ANLEITUNG_MD.format(n_photos=len(rows), n_stations=len(stations),
                            date=now), encoding="utf-8")
    log.info(f"Metashape-Export: {out_dir} ({len(rows)} Fotos, "
             f"{len(stations)} Standpunkte)")
    return csv_path
