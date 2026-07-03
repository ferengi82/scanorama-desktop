"""Hauptfenster (M2-Stand: Viewer + Scan öffnen; wächst in M3).

Verarbeitung läuft in einem Worker-Thread, damit die Oberfläche
während Dekodierung/Filterung bedienbar bleibt.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QComboBox, QFileDialog, QLabel, QMainWindow,
                               QMessageBox, QSlider, QToolBar)

from .. import APP_NAME, __version__
from ..core.pipeline import ProcessingParams, ProcessingResult, process_scan
from .viewer import PointCloudGLWidget

log = logging.getLogger(__name__)


class ScanWorker(QThread):
    """Führt process_scan im Hintergrund aus."""
    finished_ok = Signal(object)     # ProcessingResult
    failed = Signal(str)

    def __init__(self, scan_dir: Path, params: ProcessingParams, parent=None):
        super().__init__(parent)
        self.scan_dir = scan_dir
        self.params = params

    def run(self) -> None:
        try:
            result = process_scan(self.scan_dir, self.params)
        except Exception as e:      # UI-Grenze: alles melden statt crashen
            log.exception("Verarbeitung fehlgeschlagen")
            self.failed.emit(str(e))
            return
        self.finished_ok.emit(result)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1280, 800)

        self.viewer = PointCloudGLWidget(self)
        self.setCentralWidget(self.viewer)
        self._worker: ScanWorker | None = None

        self._build_toolbar()
        self.statusBar().showMessage("Bereit — Scan-Ordner öffnen (Strg+O)")

    def _build_toolbar(self) -> None:
        tb = QToolBar("Haupt", self)
        tb.setMovable(False)
        self.addToolBar(tb)

        act_open = QAction("Scan öffnen…", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self._open_scan)
        tb.addAction(act_open)

        tb.addSeparator()
        tb.addWidget(QLabel(" Farbe: "))
        self.color_box = QComboBox()
        self.color_box.addItem("Intensität", "intensity")
        self.color_box.addItem("Höhe", "height")
        self.color_box.addItem("Standpunkt", "station")
        self.color_box.currentIndexChanged.connect(
            lambda: self.viewer.set_color_mode(self.color_box.currentData()))
        tb.addWidget(self.color_box)

        tb.addWidget(QLabel(" Punktgröße: "))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(1, 10)
        slider.setValue(2)
        slider.setFixedWidth(120)
        slider.valueChanged.connect(self.viewer.set_point_size)
        tb.addWidget(slider)

        act_fit = QAction("Einpassen", self)
        act_fit.setShortcut("F")
        act_fit.triggered.connect(self.viewer.fit_view)
        tb.addAction(act_fit)

    def _open_scan(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Scan-Ordner öffnen", str(Path.home()))
        if not path:
            return
        self.statusBar().showMessage(f"Verarbeite {Path(path).name} …")
        self._worker = ScanWorker(Path(path), ProcessingParams())
        self._worker.finished_ok.connect(self._scan_ready)
        self._worker.failed.connect(self._scan_failed)
        self._worker.start()

    def _scan_ready(self, result: ProcessingResult) -> None:
        self.viewer.set_cloud(result.cloud)
        floor = "Boden→Z=0" if result.floor_transform is not None else "kein Bodenfit"
        self.statusBar().showMessage(
            f"{result.report['scan_name']}: {len(result.cloud):,} Punkte "
            f"({result.report['duration_s']}s, {floor})")

    def _scan_failed(self, message: str) -> None:
        self.statusBar().showMessage("Fehler bei der Verarbeitung")
        QMessageBox.critical(self, APP_NAME, message)
