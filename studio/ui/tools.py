"""Werkzeug-Panel: Navigations-/Mess-/Info-Modus und Clipping-Box.

Die Werkzeug-Logik (Messpunkte sammeln, Punkt-Attribute anzeigen) lebt
hier; der Viewer liefert nur pointPicked-Signale und zeichnet Overlays.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox,
                               QGridLayout, QGroupBox, QLabel, QPushButton,
                               QRadioButton, QVBoxLayout, QWidget)

from .viewer import PointCloudGLWidget


class ToolsPanel(QWidget):
    """Steuert Werkzeug-Modus und Clipping des Viewers."""

    def __init__(self, viewer: PointCloudGLWidget, parent=None):
        super().__init__(parent)
        self.viewer = viewer
        self._measure_points: list[np.ndarray] = []

        # --- Werkzeugwahl -------------------------------------------------
        box_tool = QGroupBox(self.tr("Werkzeug"))
        self.rb_orbit = QRadioButton(self.tr("Navigieren"))
        self.rb_measure = QRadioButton(self.tr("Distanz messen"))
        self.rb_info = QRadioButton(self.tr("Punkt-Info"))
        self.rb_orbit.setChecked(True)
        group = QButtonGroup(self)
        for rb, tool in ((self.rb_orbit, "orbit"),
                         (self.rb_measure, "measure"),
                         (self.rb_info, "info")):
            group.addButton(rb)
            rb.toggled.connect(
                lambda on, t=tool: on and self._set_tool(t))
        lay = QVBoxLayout(box_tool)
        for rb in (self.rb_orbit, self.rb_measure, self.rb_info):
            lay.addWidget(rb)

        self.result_label = QLabel(self.tr("—"))
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.result_label)

        # --- Clipping -----------------------------------------------------
        self.box_clip = QGroupBox(self.tr("Schnitt (Clipping)"))
        self.box_clip.setCheckable(True)
        self.box_clip.setChecked(False)
        grid = QGridLayout(self.box_clip)
        self._clip_spins: dict[str, QDoubleSpinBox] = {}
        for row, axis in enumerate("XYZ"):
            grid.addWidget(QLabel(axis), row, 0)
            for col, side in enumerate(("min", "max")):
                spin = QDoubleSpinBox(minimum=-500, maximum=500,
                                      decimals=2, singleStep=0.1)
                spin.setSuffix(" m")
                spin.valueChanged.connect(self._apply_clip)
                grid.addWidget(spin, row, col + 1)
                self._clip_spins[f"{axis.lower()}{side}"] = spin
        btn_reset = QPushButton(self.tr("Auf Wolke setzen"))
        btn_reset.clicked.connect(self.reset_clip_to_cloud)
        grid.addWidget(btn_reset, 3, 0, 1, 3)
        self.box_clip.toggled.connect(self._apply_clip)

        hint = QLabel(self.tr("Tipp: Für einen Grundriss Z auf z.B. "
                              "0.9–1.1 m begrenzen."))
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(box_tool)
        layout.addWidget(self.box_clip)
        layout.addWidget(hint)
        layout.addStretch()

        viewer.pointPicked.connect(self._on_pick)

    # ------------------------------------------------------------------
    def _set_tool(self, tool: str) -> None:
        self.viewer.set_tool(tool)
        self._measure_points.clear()
        self.viewer.set_overlay(None)
        self.result_label.setText(self.tr("—"))

    def _on_pick(self, index: int, xyz) -> None:
        if self.viewer.tool == "measure":
            self._measure_points.append(np.asarray(xyz))
            if len(self._measure_points) > 2:
                self._measure_points = self._measure_points[-1:]
            self.viewer.set_overlay(self._measure_points, lines=True)
            if len(self._measure_points) == 2:
                a, b = self._measure_points
                d = float(np.linalg.norm(b - a))
                dz = float(abs(b[2] - a[2]))
                dxy = float(np.linalg.norm((b - a)[:2]))
                self.result_label.setText(
                    self.tr("Strecke: %.3f m\nhorizontal: %.3f m\n"
                            "Höhendifferenz: %.3f m") % (d, dxy, dz))
            else:
                self.result_label.setText(self.tr("Zweiten Punkt anklicken …"))
        elif self.viewer.tool == "info":
            cloud = self.viewer.cloud
            self.viewer.set_overlay([np.asarray(xyz)], lines=False)
            self.result_label.setText(self.tr(
                "X %.3f  Y %.3f  Z %.3f m\nIntensität: %d\n"
                "Scanner-Distanz: %.2f m\nStandpunkt: %d") % (
                xyz[0], xyz[1], xyz[2],
                int(cloud.intensity[index]),
                float(cloud.scanner_dist[index]),
                int(cloud.station[index])))

    # ------------------------------------------------------------------
    def reset_clip_to_cloud(self) -> None:
        cloud = self.viewer.cloud
        if cloud is None or len(cloud) == 0:
            return
        lo = cloud.xyz.min(axis=0)
        hi = cloud.xyz.max(axis=0)
        for i, axis in enumerate("xyz"):
            self._clip_spins[f"{axis}min"].setValue(float(lo[i]))
            self._clip_spins[f"{axis}max"].setValue(float(hi[i]))
        self._apply_clip()

    def _apply_clip(self) -> None:
        if not self.box_clip.isChecked():
            self.viewer.set_clip_box(None, None)
            return
        lo = [self._clip_spins[f"{a}min"].value() for a in "xyz"]
        hi = [self._clip_spins[f"{a}max"].value() for a in "xyz"]
        self.viewer.set_clip_box(lo, hi)
