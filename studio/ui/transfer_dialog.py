"""Dialog: Scans vom Pi holen und ins Projekt importieren."""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLineEdit, QProgressBar,
                               QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..core.transfer import PiTransfer, RemoteConfig, RemoteScan
from .workers import WorkerManager

log = logging.getLogger(__name__)


class TransferDialog(QDialog):
    """Verbindungsdaten, Scan-Liste, Download in den Projektordner."""

    def __init__(self, workers: WorkerManager, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Scans vom Gerät holen"))
        self.resize(640, 480)
        self.workers = workers
        self.settings = QSettings("scanorama", "studio")
        self.downloaded: list = []       # lokale Pfade nach Download

        form = QFormLayout()
        self.host = QLineEdit(self.settings.value("pi/host", ""))
        self.user = QLineEdit(self.settings.value("pi/user", "pi"))
        self.port = QSpinBox(minimum=1, maximum=65535)
        self.port.setValue(int(self.settings.value("pi/port", 22)))
        self.key = QLineEdit(self.settings.value("pi/key", ""))
        self.key.setPlaceholderText(self.tr("leer = Standard-SSH-Schlüssel"))
        self.scans_dir = QLineEdit(self.settings.value("pi/scans_dir", "scans"))
        form.addRow(self.tr("Host/IP"), self.host)
        form.addRow(self.tr("Benutzer"), self.user)
        form.addRow(self.tr("Port"), self.port)
        form.addRow(self.tr("Schlüsseldatei"), self.key)
        form.addRow(self.tr("Scan-Ordner"), self.scans_dir)

        self.btn_connect = QPushButton(self.tr("Verbinden && auflisten"))
        self.btn_connect.clicked.connect(self._list_scans)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [self.tr("Scan"), self.tr("Größe"), self.tr("Datum"),
             self.tr("Vollständig")])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.progress = QProgressBar()
        self.progress.setVisible(False)

        self.btn_download = QPushButton(self.tr("Ausgewählte holen"))
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self._download_selected)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        top = QHBoxLayout()
        top.addLayout(form, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.btn_connect)
        layout.addWidget(self.table)
        layout.addWidget(self.progress)
        layout.addWidget(self.btn_download)
        layout.addWidget(buttons)

        self.target_dir = None           # wird vom Aufrufer gesetzt
        self._scans: list[RemoteScan] = []

    # ------------------------------------------------------------------
    def _config(self) -> RemoteConfig:
        self.settings.setValue("pi/host", self.host.text())
        self.settings.setValue("pi/user", self.user.text())
        self.settings.setValue("pi/port", self.port.value())
        self.settings.setValue("pi/key", self.key.text())
        self.settings.setValue("pi/scans_dir", self.scans_dir.text())
        return RemoteConfig(
            host=self.host.text().strip(),
            user=self.user.text().strip(),
            port=self.port.value(),
            key_path=self.key.text().strip(),
            scans_dir=self.scans_dir.text().strip() or "scans",
        )

    def _list_scans(self) -> None:
        config = self._config()
        self.btn_connect.setEnabled(False)

        def job():
            with PiTransfer(config) as t:
                return t.list_scans()

        def on_result(scans):
            self._scans = scans
            self.table.setRowCount(len(scans))
            for row, s in enumerate(scans):
                when = datetime.fromtimestamp(s.mtime).strftime("%d.%m.%Y %H:%M")
                for col, text in enumerate([
                        s.name, f"{s.size_mb:.1f} MB", when,
                        self.tr("ja") if s.complete else self.tr("NEIN")]):
                    item = QTableWidgetItem(text)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, col, item)
            self.btn_connect.setEnabled(True)
            self.btn_download.setEnabled(bool(scans))

        def on_error(message):
            self.btn_connect.setEnabled(True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, self.windowTitle(), message)

        self.workers.start(job, on_result=on_result, on_error=on_error)

    def _download_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows or self.target_dir is None:
            return
        names = [self._scans[r].name for r in rows]
        config = self._config()
        target = self.target_dir
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_download.setEnabled(False)

        def job():
            paths = []
            with PiTransfer(config) as t:
                for name in names:
                    paths.append(t.download(name, target))
            return paths

        def on_result(paths):
            self.downloaded.extend(paths)
            self.progress.setVisible(False)
            self.btn_download.setEnabled(True)
            self.accept()

        def on_error(message):
            self.progress.setVisible(False)
            self.btn_download.setEnabled(True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, self.windowTitle(), message)

        self.workers.start(job, on_result=on_result, on_error=on_error)
