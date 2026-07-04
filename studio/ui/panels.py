"""Dock-Panels des Hauptfensters: Projekt, Parameter, Log."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..core.filters import FilterParams
from ..core.pipeline import ProcessingParams
from ..core.project import Project


class ProjectPanel(QWidget):
    """Standpunkt-Liste mit Aktiv-Häkchen und Import-Knopf."""

    stationSelected = Signal(str)       # Ordnername
    stationToggled = Signal(str, bool)  # Ordnername, enabled
    importRequested = Signal()
    removeRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([self.tr("Standpunkt"), self.tr("Status")])
        self.tree.setRootIsDecorated(False)
        self.tree.currentItemChanged.connect(self._on_select)
        self.tree.itemChanged.connect(self._on_check)

        btn_import = QPushButton(self.tr("Scans importieren…"))
        btn_import.clicked.connect(self.importRequested.emit)
        btn_remove = QPushButton(self.tr("Entfernen"))
        btn_remove.clicked.connect(self._on_remove)

        buttons = QHBoxLayout()
        buttons.addWidget(btn_import)
        buttons.addWidget(btn_remove)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.tree)
        layout.addLayout(buttons)

    def set_project(self, project: Project | None) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        if project is not None:
            for s in project.stations:
                item = QTreeWidgetItem([s.folder, ""])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if s.enabled
                                   else Qt.CheckState.Unchecked)
                self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)

    def set_status(self, folder: str, text: str) -> None:
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.text(0) == folder:
                item.setText(1, text)
                return

    def current_folder(self) -> str | None:
        item = self.tree.currentItem()
        return item.text(0) if item else None

    def _on_select(self, current, _previous) -> None:
        if current is not None:
            self.stationSelected.emit(current.text(0))

    def _on_check(self, item, column) -> None:
        if column == 0:
            self.stationToggled.emit(
                item.text(0), item.checkState(0) == Qt.CheckState.Checked)

    def _on_remove(self) -> None:
        folder = self.current_folder()
        if folder:
            self.removeRequested.emit(folder)


class ParamsPanel(QWidget):
    """Verarbeitungs-Parameter (v1-Defaults) mit Anwenden-Knopf."""

    applyRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        form = QFormLayout()

        self.calib_from_meta = QCheckBox(
            self.tr("Kalibrierung aus Scan-Metadaten"))
        self.calib_from_meta.setToolTip(self.tr(
            "Strahlkalibrierung aus der meta.json des Scans übernehmen "
            "(trägt der Scanner ein). Die vier Felder unten greifen nur, "
            "wenn der Scan keine Kalibrierung mitbringt oder der Haken "
            "aus ist."))
        form.addRow(self.calib_from_meta)

        def _angle_box(decimals=3, rng=30.0):
            box = QDoubleSpinBox(minimum=-rng, maximum=rng,
                                 singleStep=0.05, decimals=decimals)
            box.setSuffix(" °")
            return box

        self.el_offset = _angle_box()
        form.addRow(self.tr("Elevations-Offset"), self.el_offset)
        self.beam_skew = _angle_box(rng=5.0)
        form.addRow(self.tr("Strahl-Skew"), self.beam_skew)
        self.beam_wobble = _angle_box(rng=5.0)
        form.addRow(self.tr("Strahl-Wobble"), self.beam_wobble)
        self.halfplane_split = _angle_box(rng=5.0)
        form.addRow(self.tr("Halbebenen-Versatz"), self.halfplane_split)

        self.block_start = QDoubleSpinBox(minimum=0, maximum=360, decimals=1)
        self.block_start.setSuffix(" °")
        self.block_end = QDoubleSpinBox(minimum=0, maximum=360, decimals=1)
        self.block_end.setSuffix(" °")
        form.addRow(self.tr("Stativ-Bereich von"), self.block_start)
        form.addRow(self.tr("Stativ-Bereich bis"), self.block_end)

        self.min_dist = QDoubleSpinBox(minimum=0, maximum=5,
                                       singleStep=0.05, decimals=2)
        self.min_dist.setSuffix(" m")
        form.addRow(self.tr("Nahbereich"), self.min_dist)

        self.sor = QCheckBox(self.tr("Ausreißer entfernen (SOR)"))
        form.addRow(self.sor)
        self.floor = QCheckBox(self.tr("Boden ausrichten (Z=0)"))
        form.addRow(self.floor)

        self.fusion_voxel = QDoubleSpinBox(minimum=0.1, maximum=20.0,
                                           singleStep=0.1, decimals=1)
        self.fusion_voxel.setSuffix(" cm")
        self.fusion_voxel.setToolTip(self.tr(
            "Voxelgröße der Fusion: pro Voxel bleibt genau ein "
            "(gewichteter) Punkt. Kleiner = dichtere Gesamtwolke."))
        form.addRow(self.tr("Fusions-Voxel"), self.fusion_voxel)

        self.btn_apply = QPushButton(self.tr("Neu verarbeiten"))
        self.btn_apply.clicked.connect(self.applyRequested.emit)

        hint = QLabel(self.tr("Änderungen wirken nach „Neu verarbeiten“ "
                              "auf alle Standpunkte."))
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(form)
        layout.addWidget(self.btn_apply)
        layout.addWidget(hint)
        layout.addStretch()

        self.set_params(ProcessingParams())

    def set_fusion_voxel_m(self, meters: float) -> None:
        self.fusion_voxel.setValue(meters * 100.0)

    def fusion_voxel_m(self) -> float:
        return self.fusion_voxel.value() / 100.0

    def set_params(self, p: ProcessingParams) -> None:
        self.calib_from_meta.setChecked(p.calib_from_meta)
        self.el_offset.setValue(p.el_offset_deg)
        self.beam_skew.setValue(p.beam_skew_deg)
        self.beam_wobble.setValue(p.beam_wobble_deg)
        self.halfplane_split.setValue(p.halfplane_split_deg)
        self.block_start.setValue(p.filters.block_start_deg)
        self.block_end.setValue(p.filters.block_end_deg)
        self.min_dist.setValue(p.filters.min_dist_m)
        self.sor.setChecked(p.filters.sor_enabled)
        self.floor.setChecked(p.align_floor)

    def params(self) -> ProcessingParams:
        return ProcessingParams(
            el_offset_deg=self.el_offset.value(),
            beam_skew_deg=self.beam_skew.value(),
            beam_wobble_deg=self.beam_wobble.value(),
            halfplane_split_deg=self.halfplane_split.value(),
            calib_from_meta=self.calib_from_meta.isChecked(),
            filters=FilterParams(
                block_start_deg=self.block_start.value(),
                block_end_deg=self.block_end.value(),
                min_dist_m=self.min_dist.value(),
                sor_enabled=self.sor.isChecked(),
            ),
            align_floor=self.floor.isChecked(),
        )


class LogPanel(QPlainTextEdit):
    """Zeigt das Python-Logging live im Fenster (thread-sicher)."""

    _appendLine = Signal(str)

    class _Handler(logging.Handler):
        def __init__(self, sig):
            super().__init__(level=logging.INFO)
            self.sig = sig
            self.setFormatter(logging.Formatter("%(asctime)s  %(message)s",
                                                datefmt="%H:%M:%S"))

        def emit(self, record):
            # Signal-Emission ist threadsicher → landet im GUI-Thread
            self.sig.emit(self.format(record))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)
        self._appendLine.connect(self.appendPlainText)
        self.handler = self._Handler(self._appendLine)
        logging.getLogger().addHandler(self.handler)

    def detach(self) -> None:
        logging.getLogger().removeHandler(self.handler)
