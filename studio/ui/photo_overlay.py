"""Foto-Overlay-Prüfer: Foto ⇄ Wolken-Render überblenden, Mounts justieren.

Dialog (Menü Fotos → Foto-Overlay prüfen…): zeigt für ein gewähltes Foto
die aus der Kamerapose gerenderte Punktwolke halbtransparent über dem
Foto. Regler für az_offset/pitch/roll wirken live; Auto-Fit optimiert
die Winkel gegen ein oder alle Fotos der Kamera. „Übernehmen" schreibt
die Werte als Projekt-Override (project.camera_mounts), „cameras.json…"
exportiert sie für den Pi (~/.config/scanorama/).
"""

from __future__ import annotations

import json
import logging

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QSlider, QVBoxLayout)

from .. import APP_NAME
from ..core import legacy, overlay, photos as photos_mod

log = logging.getLogger(__name__)

RENDER_SCALE = 8      # Sensor/8 ≈ 408×306
VIEW_W = 816


class PhotoOverlayDialog(QDialog):
    """Interaktiver Abgleich Foto ↔ Punktwolke für eine Station."""

    def __init__(self, project, station_folder: str, result, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Foto-Overlay prüfen — %s") % station_folder)
        self.project = project
        self.result = result                      # ProcessingResult
        self.cloud = result.cloud
        if len(self.cloud) > 1_200_000:
            step = len(self.cloud) // 1_200_000 + 1
            self.cloud = self.cloud.subset(
                np.arange(0, len(self.cloud), step))
        self.floor_T = result.floor_transform

        scan_dir = project.station_path(project.get_station(station_folder))
        meta = json.loads((scan_dir / "meta.json").read_text(encoding="utf-8"))
        legacy.refresh_stale_mounts(meta)
        self.mounts = dict((meta.get("cameras") or {}).get("mounts") or {})
        if project.camera_mounts:
            self.mounts.update(project.camera_mounts)
        self.photos = photos_mod.load_station_photos(scan_dir, meta)
        self.scan_dir = scan_dir

        cams = sorted({p.cam_id for p in self.photos})
        if not cams:
            raise ValueError("Standpunkt hat keine Fotos")

        self.cam_box = QComboBox()
        self.cam_box.addItems(cams)
        self.photo_slider = QSlider(Qt.Orientation.Horizontal)
        self.blend = QSlider(Qt.Orientation.Horizontal)
        self.blend.setRange(0, 100)
        self.blend.setValue(50)
        self.image = QLabel()
        self.image.setMinimumSize(VIEW_W, VIEW_W * 3 // 4)
        self.info = QLabel()

        form = QFormLayout()
        self.spin = {}
        for key, lo, hi in (("az_offset_deg", 0.0, 360.0),
                            ("pitch_mount_deg", -90.0, 90.0),
                            ("roll_mount_deg", -180.0, 180.0)):
            box = QDoubleSpinBox(minimum=lo, maximum=hi, decimals=2,
                                 singleStep=0.25)
            box.setSuffix(" °")
            box.valueChanged.connect(self._schedule_render)
            self.spin[key] = box
        form.addRow(self.tr("Blickrichtung (az_offset)"),
                    self.spin["az_offset_deg"])
        form.addRow(self.tr("Neigung (pitch)"), self.spin["pitch_mount_deg"])
        form.addRow(self.tr("Verdrehung (roll)"), self.spin["roll_mount_deg"])

        btn_fit1 = QPushButton(self.tr("Auto-Fit (dieses Foto)"))
        btn_fitall = QPushButton(self.tr("Auto-Fit (alle Fotos der Kamera)"))
        btn_apply = QPushButton(self.tr("Übernehmen (Projekt)"))
        btn_export = QPushButton(self.tr("cameras.json exportieren…"))
        btn_fit1.clicked.connect(lambda: self._autofit(False))
        btn_fitall.clicked.connect(lambda: self._autofit(True))
        btn_apply.clicked.connect(self._apply)
        btn_export.clicked.connect(self._export_json)

        top = QHBoxLayout()
        top.addWidget(QLabel(self.tr("Kamera:")))
        top.addWidget(self.cam_box)
        top.addWidget(QLabel(self.tr("Foto:")))
        top.addWidget(self.photo_slider, 1)
        top.addWidget(QLabel(self.tr("Überblendung:")))
        top.addWidget(self.blend)

        buttons = QHBoxLayout()
        for b in (btn_fit1, btn_fitall, btn_apply, btn_export):
            buttons.addWidget(b)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.image, 1)
        lay.addLayout(form)
        lay.addLayout(buttons)
        lay.addWidget(self.info)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._render)

        self.cam_box.currentTextChanged.connect(self._cam_changed)
        self.photo_slider.valueChanged.connect(self._schedule_render)
        self.blend.valueChanged.connect(self._schedule_render)
        self._loading = False
        self._cam_changed(self.cam_box.currentText())

    # -- Datenzugriff ---------------------------------------------------
    def _cam_photos(self):
        cam = self.cam_box.currentText()
        return [p for p in self.photos if p.cam_id == cam]

    def _cam_changed(self, cam: str) -> None:
        lst = self._cam_photos()
        self.photo_slider.setRange(0, max(len(lst) - 1, 0))
        m = self.mounts.get(cam, {})
        self._loading = True
        for key, box in self.spin.items():
            box.setValue(float(m.get(key, 0.0)))
        self._loading = False
        self._render()

    def _current_mount(self) -> dict:
        cam = self.cam_box.currentText()
        m = dict(self.mounts.get(cam, {}))
        for key, box in self.spin.items():
            m[key] = box.value()
        m.setdefault("r_cam_m", 0.05)
        m.setdefault("z_cam_m", -0.05)
        m.setdefault("yaw_mount_deg", 0.0)
        return m

    def _schedule_render(self) -> None:
        if not self._loading:
            self._timer.start()

    # -- Anzeige ----------------------------------------------------------
    def _render(self) -> None:
        lst = self._cam_photos()
        if not lst:
            return
        p = lst[self.photo_slider.value()]
        mount = self._current_mount()
        pose = overlay.pose_from_mount(mount, p.azimuth_deg)
        rend = overlay.render_from_pose(self.cloud, pose, self.floor_T,
                                        RENDER_SCALE)
        h, w = rend.shape
        with Image.open(p.source) as im:
            foto = np.asarray(im.convert("L").resize((w, h)), np.float64)
        foto = np.clip((foto / 255.0) ** 0.5 * 255, 0, 255)

        a = self.blend.value() / 100.0
        mix = np.clip((1 - a) * foto + a * rend.astype(np.float64),
                      0, 255).astype(np.uint8)
        rgb = np.stack([mix, mix, mix], axis=-1)
        # Render grünlich einfärben, Foto neutral — Kanten besser sichtbar
        rgb[..., 1] = np.clip(rgb[..., 1] + (a * rend * 0.3), 0, 255)
        img = QImage(np.ascontiguousarray(rgb).data, w, h, 3 * w,
                     QImage.Format.Format_RGB888)
        self.image.setPixmap(QPixmap.fromImage(img).scaledToWidth(
            VIEW_W, Qt.TransformationMode.SmoothTransformation))
        score = overlay.overlay_score(self.cloud, mount, p.azimuth_deg,
                                      foto, self.floor_T)
        self.info.setText(self.tr(
            "Foto %s | Azimut %.1f° | Deckungs-Score %.3f") % (
            p.source.name, p.azimuth_deg, score))

    # -- Aktionen ---------------------------------------------------------
    def _autofit(self, all_photos: bool) -> None:
        lst = self._cam_photos()
        if not lst:
            return
        if all_photos:
            sel = lst[:: max(len(lst) // 8, 1)][:8]
        else:
            sel = [lst[self.photo_slider.value()]]
        pairs = []
        w = photos_mod.SENSOR_W_PX // 16
        h = photos_mod.SENSOR_H_PX // 16
        for p in sel:
            with Image.open(p.source) as im:
                pairs.append((p.azimuth_deg, np.asarray(
                    im.convert("L").resize((w, h)), np.float64)))
        mount, before, after = overlay.autofit(
            self.cloud, self._current_mount(), pairs, self.floor_T)
        self._loading = True
        for key, box in self.spin.items():
            box.setValue(float(mount[key]))
        self._loading = False
        self._render()
        self.info.setText(self.info.text() + self.tr(
            "  — Auto-Fit: %.3f → %.3f") % (before, after))

    def _apply(self) -> None:
        cam = self.cam_box.currentText()
        if self.project.camera_mounts is None:
            self.project.camera_mounts = {}
        base = dict(self.mounts.get(cam, {}))
        base.update(self._current_mount())
        base.pop("device", None)
        self.project.camera_mounts[cam] = base
        self.mounts[cam] = base
        self.project.save()
        QMessageBox.information(
            self, APP_NAME,
            self.tr("Mount für %s im Projekt gespeichert — wirkt beim "
                    "nächsten „Neu verarbeiten“ und im Metashape-Export.")
            % cam)

    def _export_json(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self, self.tr("cameras.json exportieren"),
            str(self.project.output_dir / "cameras.json"), "JSON (*.json)")
        if not target:
            return
        data = {}
        for cam in sorted(self.mounts):
            m = dict(self.mounts.get(cam, {}))
            if self.project.camera_mounts and cam in self.project.camera_mounts:
                m.update(self.project.camera_mounts[cam])
            m.pop("device", None)
            data[cam] = m
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        QMessageBox.information(
            self, APP_NAME,
            self.tr("Gespeichert: %s\nAuf dem Pi ablegen als "
                    "~/.config/scanorama/cameras.json.") % target)
