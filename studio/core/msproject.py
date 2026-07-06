"""Metashape-Projektdatei (.psx) direkt erzeugen — ohne Metashape-API.

Struktur (aus einem echten Metashape-2.3-Projekt abgeleitet, siehe
docs/dev/STATUS.md 2026-07-05):

    <name>.psx                    Mini-XML → verweist auf .files-Ordner
    <name>.files/project.zip      doc.xml: Chunk-Liste + Meta
    <name>.files/0/chunk.zip      doc.xml: Sensoren (Kalibriergruppen),
                                  Kameras + Positions-Referenz, CRS, Settings
    <name>.files/0/0/frame.zip    doc.xml: Foto-Pfade (relativ)

Die Fotos kommen aus dem bestehenden Metashape-Export (output/metashape/,
aufrecht gedreht). Referenz: Positionen **und** Orientierung
(yaw/pitch/roll, rotation_enabled) — ein Einzelstandpunkt liefert sonst
keinen Orientierungs-Anker und Metashape verdreht die Wolke beim Align.
Alle Fotos eines Standpunkts kommen in eine ImageGroup ``type="station"``.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from .photos import (FOCAL_PX, PhotoPose, _rotated_calibration, _upright,
                     transform_pose)

log = logging.getLogger(__name__)

PSX = ('<?xml version="1.0" encoding="UTF-8"?>\n'
       '<document version="1.2.0" path="{projectname}.files/project.zip"/>\n')

PROJECT_DOC = """<?xml version="1.0" encoding="UTF-8"?>
<document version="1.2.0">
  <chunks next_id="1" active_id="0">
    <chunk id="0" path="0/chunk.zip"/>
  </chunks>
  <meta>
    <property name="Info/OriginalSoftwareName" value="Agisoft Metashape"/>
    <property name="Info/OriginalSoftwareVendor" value="Agisoft"/>
  </meta>
</document>
"""

LOCAL_CRS = ('LOCAL_CS["Local Coordinates (m)",LOCAL_DATUM["Local Datum",0],'
             'UNIT["metre",1,AUTHORITY["EPSG","9001"]]]')

SETTINGS = """  <settings>
    <property name="accuracy_tiepoints" value="1"/>
    <property name="accuracy_cameras" value="0.005"/>
    <property name="accuracy_cameras_ypr" value="10"/>
    <property name="accuracy_markers" value="0.0050000000000000001"/>
    <property name="accuracy_scalebars" value="0.001"/>
    <property name="accuracy_projections" value="0.5"/>
  </settings>
"""


def _sensor_xml(sid: int, cam_id: str, img_rot: int) -> str:
    w, h, cx, cy = _rotated_calibration(img_rot)
    return (
        f'    <sensor id="{sid}" label="{escape(cam_id)}" type="frame">\n'
        f'      <resolution width="{w}" height="{h}"/>\n'
        f'      <property name="layer_index" value="0"/>\n'
        f'      <bands>\n'
        f'        <band label="Red"/>\n'
        f'        <band label="Green"/>\n'
        f'        <band label="Blue"/>\n'
        f'      </bands>\n'
        f'      <data_type>uint8</data_type>\n'
        f'      <calibration type="frame" class="initial">\n'
        f'        <resolution width="{w}" height="{h}"/>\n'
        f'        <f>{FOCAL_PX}</f>\n'
        f'        <cx>{cx:.4f}</cx>\n'
        f'        <cy>{cy:.4f}</cy>\n'
        f'      </calibration>\n'
        f'      <black_level>0 0 0</black_level>\n'
        f'      <sensitivity>1 1 1</sensitivity>\n'
        f'    </sensor>\n')


def write_psx(out_dir: str | Path, name: str,
              stations: list[tuple[str, list[PhotoPose], object]],
              photo_subdir: str = "metashape") -> Path:
    """Schreibt <out_dir>/<name>.psx + .files-Ordner.

    Args:
        stations: wie bei export_metashape — (name, posen, T_gesamt);
            die Foto-Kopien müssen bereits unter out_dir/photo_subdir
            liegen (export_metashape vorher aufrufen!)
    """
    out_dir = Path(out_dir)
    files = out_dir / f"{name}.files"
    (files / "0" / "0").mkdir(parents=True, exist_ok=True)

    # Posen wie im Export: transformieren + aufrecht drehen; pro Standpunkt
    # gruppiert, damit alle Fotos eines Standpunkts als eine Kamera-Station
    # (ImageGroup type="station") in den Chunk kommen.
    station_rows: list[tuple[str, list[tuple[PhotoPose, int]]]] = []
    for sname, poses, T in stations:
        prs: list[tuple[PhotoPose, int]] = []
        for pose in poses:
            p = pose if T is None else transform_pose(pose, T)
            p, img_rot = _upright(p)
            prs.append((p, img_rot))
        if prs:
            station_rows.append((sname, prs))
    all_rows = [pr for _s, prs in station_rows for pr in prs]
    if not all_rows:
        raise ValueError("Keine Fotos — erst den Metashape-Export erzeugen")

    cam_ids = sorted({p.cam_id for p, _ in all_rows})
    sensor_of = {cid: i for i, cid in enumerate(cam_ids)}
    rot_of = {p.cam_id: r for p, r in all_rows}

    sensors = "".join(_sensor_xml(sensor_of[c], c, rot_of[c])
                      for c in cam_ids)

    # Eine <group type="station"> je Standpunkt; die Kameras liegen darin.
    # Die Referenz trägt jetzt auch yaw/pitch/roll (rotation_enabled) —
    # ohne Orientierungs-Anker verdreht Metashape einen Einzelstandpunkt
    # beim Align (die Positionen liegen alle ~5 cm beieinander).
    groups, frames = [], []
    i = 0
    for gid, (sname, prs) in enumerate(station_rows):
        gcams = []
        for p, _r in prs:
            label = escape(Path(p.label).stem)
            gcams.append(
                f'      <camera id="{i}" sensor_id="{sensor_of[p.cam_id]}" '
                f'label="{label}">\n'
                f'        <reference x="{p.x:.6f}" y="{p.y:.6f}" '
                f'z="{p.z:.6f}" yaw="{p.yaw:.4f}" pitch="{p.pitch:.4f}" '
                f'roll="{p.roll:.4f}" enabled="true" '
                f'rotation_enabled="true"/>\n'
                f'      </camera>\n')
            frames.append(
                f'    <camera camera_id="{i}">\n'
                f'      <photo path="../../../{photo_subdir}/'
                f'{escape(p.label)}"/>\n'
                f'    </camera>\n')
            i += 1
        groups.append(
            f'    <group id="{gid}" label="{escape(sname)}" '
            f'type="station">\n' + "".join(gcams) + '    </group>\n')

    chunk_doc = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<chunk label="{escape(name)}" enabled="true" version="1.2.0">\n'
        f'  <sensors next_id="{len(cam_ids)}">\n{sensors}  </sensors>\n'
        '  <components next_id="0"/>\n'
        f'  <cameras next_id="{len(all_rows)}" '
        f'next_group_id="{len(station_rows)}">\n'
        + "".join(groups) + '  </cameras>\n'
        '  <frames next_id="1">\n'
        '    <frame id="0" path="0/frame.zip"/>\n'
        '  </frames>\n'
        f'  <reference>{LOCAL_CRS}</reference>\n'
        + SETTINGS + '</chunk>\n')

    frame_doc = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<frame version="1.2.0">\n  <cameras>\n'
                 + "".join(frames) + '  </cameras>\n</frame>\n')

    def zip_doc(path: Path, doc: str) -> None:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("doc.xml", doc)

    (out_dir / f"{name}.psx").write_text(PSX, encoding="utf-8")
    zip_doc(files / "project.zip", PROJECT_DOC)
    zip_doc(files / "0" / "chunk.zip", chunk_doc)
    zip_doc(files / "0" / "0" / "frame.zip", frame_doc)
    log.info(f"Metashape-Projekt geschrieben: {out_dir / (name + '.psx')} "
             f"({len(all_rows)} Kameras, {len(cam_ids)} Sensoren, "
             f"{len(station_rows)} Station-Gruppen)")
    return out_dir / f"{name}.psx"
