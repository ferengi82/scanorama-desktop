"""Punktwolken-Export: PLY (eigen), LAS/LAZ (laspy), E57 (pye57).

- PLY: binary_little_endian mit x/y/z (float32), intensity (uchar),
  distance (float32, Original-Scannerdistanz), station (ushort).
  Kompatibel mit CloudCompare/MeshLab/Open3D.
- LAS 1.4: Vermessungsstandard, Intensität auf uint16 skaliert,
  point_source_id = Standpunkt.
- E57: Standard für terrestrische Scans, importiert Metashape als
  Scan-Station (Portierung des bewährten v1-Exports). Pose optional —
  Punkte bleiben scan-lokal, die Pose bringt sie in den globalen Rahmen.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .cloud import PointCloud

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PLY
# ---------------------------------------------------------------------------

def save_ply(cloud: PointCloud, filename: str | Path) -> None:
    """Binary-PLY mit intensity/distance/station-Zusatzfeldern."""
    n = len(cloud)
    dtype = np.dtype([
        ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
        ("intensity", "u1"),
        ("distance", "<f4"),
        ("station", "<u2"),
    ])
    out = np.empty(n, dtype=dtype)
    out["x"], out["y"], out["z"] = cloud.xyz[:, 0], cloud.xyz[:, 1], cloud.xyz[:, 2]
    out["intensity"] = cloud.intensity
    out["distance"] = cloud.scanner_dist
    out["station"] = cloud.station

    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        "comment Scanorama Studio\n"
        f"element vertex {n}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property uchar intensity\n"
        "property float distance\n"
        "property ushort station\n"
        "end_header\n"
    )
    with open(filename, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(out.tobytes())
    log.info(f"PLY geschrieben: {filename} ({n:,} Punkte)")


def load_ply(filename: str | Path) -> PointCloud:
    """Liest ein von :func:`save_ply` geschriebenes PLY zurück (für Tests)."""
    with open(filename, "rb") as f:
        header = b""
        while not header.endswith(b"end_header\n"):
            line = f.readline()
            if not line:
                raise ValueError(f"{filename}: PLY-Header unvollständig")
            header += line
        n = int([ln for ln in header.decode().splitlines()
                 if ln.startswith("element vertex")][0].split()[-1])
        dtype = np.dtype([
            ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
            ("intensity", "u1"), ("distance", "<f4"), ("station", "<u2"),
        ])
        data = np.frombuffer(f.read(n * dtype.itemsize), dtype=dtype)
    return PointCloud(
        xyz=np.column_stack((data["x"], data["y"], data["z"])),
        intensity=data["intensity"].copy(),
        scanner_dist=data["distance"].copy(),
        station=data["station"].copy(),
    )


# ---------------------------------------------------------------------------
# LAS / LAZ
# ---------------------------------------------------------------------------

def save_las(cloud: PointCloud, filename: str | Path) -> None:
    """LAS 1.4 (bzw. LAZ bei .laz-Endung) mit 0.1-mm-Auflösung."""
    import laspy

    las = laspy.LasData(laspy.LasHeader(point_format=0, version="1.4"))
    xyz = cloud.xyz.astype(np.float64)
    las.header.offsets = xyz.min(axis=0)
    las.header.scales = [0.0001, 0.0001, 0.0001]
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    # Scanner liefert 0–255 → LAS-üblich auf uint16 spreizen
    las.intensity = (cloud.intensity.astype(np.uint16) * 257)
    las.point_source_id = cloud.station.astype(np.uint16)
    las.write(str(filename))
    log.info(f"LAS geschrieben: {filename} ({len(cloud):,} Punkte)")


# ---------------------------------------------------------------------------
# E57 (Portierung aus Scanner-v1: lidar_e57.py)
# ---------------------------------------------------------------------------

def rotation_matrix_to_quaternion(R: np.ndarray) -> np.ndarray:
    """3×3-Rotationsmatrix → Einheits-Quaternion (w, x, y, z).

    Shepperd-Methode mit Vorzeichen-Korrektur — numerisch stabil auch
    bei fast-Identität oder 180°-Drehungen.
    """
    R = np.asarray(R, dtype=np.float64)
    if R.shape != (3, 3):
        raise ValueError(f"Erwarte 3x3-Matrix, bekam {R.shape}")

    trace = R[0, 0] + R[1, 1] + R[2, 2]
    if trace > 0.0:
        s = 2.0 * np.sqrt(trace + 1.0)
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2])
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = 2.0 * np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2])
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1])
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z], dtype=np.float64)
    return q / np.linalg.norm(q)


def pose_from_transform(T: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """4×4-Transformation → (Translation xyz, Quaternion wxyz)."""
    T = np.asarray(T, dtype=np.float64)
    if T.shape != (4, 4):
        raise ValueError(f"Erwarte 4x4-Matrix, bekam {T.shape}")
    return T[:3, 3].copy(), rotation_matrix_to_quaternion(T[:3, :3])


def save_e57(clouds: list[PointCloud], filename: str | Path,
             poses: list[np.ndarray] | None = None,
             names: list[str] | None = None) -> None:
    """Schreibt eine oder mehrere Wolken als E57-Scan-Stationen.

    Args:
        clouds: Wolken in **scan-lokalen** Koordinaten
        poses: optionale 4×4-Transformationen (scan-lokal → global);
            None = Identität für alle
        names: Stations-Namen (Default: scan_name aus der Meta bzw. Index)
    """
    import pye57

    if not clouds:
        raise ValueError("Keine Wolken zum Schreiben")
    if poses is not None and len(poses) != len(clouds):
        raise ValueError("poses-Länge muss zu clouds passen")

    e57 = pye57.E57(str(filename), mode="w")
    try:
        for i, cloud in enumerate(clouds):
            xyz = cloud.xyz.astype(np.float64)
            data = {
                "cartesianX": np.ascontiguousarray(xyz[:, 0]),
                "cartesianY": np.ascontiguousarray(xyz[:, 1]),
                "cartesianZ": np.ascontiguousarray(xyz[:, 2]),
                "intensity": cloud.intensity.astype(np.float64),
            }
            if poses is None:
                translation = np.zeros(3)
                rotation = np.array([1.0, 0.0, 0.0, 0.0])
            else:
                translation, rotation = pose_from_transform(poses[i])
            name = (names[i] if names
                    else cloud.meta.get("scan_name", f"scan_{i:03d}"))
            e57.write_scan_raw(data, name=name,
                               rotation=rotation, translation=translation)
    finally:
        e57.close()
    log.info(f"E57 geschrieben: {filename} ({len(clouds)} Station(en))")


# ---------------------------------------------------------------------------
# Sammel-Export
# ---------------------------------------------------------------------------

FORMATS = ("ply", "las", "laz", "e57")


def export_cloud(cloud: PointCloud, base: str | Path,
                 formats: list[str]) -> list[Path]:
    """Exportiert eine Wolke in mehrere Formate. Rückgabe: Dateipfade."""
    base = Path(base)
    base.parent.mkdir(parents=True, exist_ok=True)
    written = []
    for fmt in formats:
        fmt = fmt.lower().lstrip(".")
        if fmt not in FORMATS:
            raise ValueError(f"Unbekanntes Format: {fmt} (kenne {FORMATS})")
        target = base.with_suffix(f".{fmt}")
        if fmt == "ply":
            save_ply(cloud, target)
        elif fmt in ("las", "laz"):
            save_las(cloud, target)
        elif fmt == "e57":
            save_e57([cloud], target)
        written.append(target)
    return written
