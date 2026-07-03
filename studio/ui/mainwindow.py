"""Hauptfenster: Projektbaum links, 3D-Viewer mittig, Parameter rechts,
Log unten. Alle Core-Aufrufe laufen über Worker-Threads.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QComboBox, QDockWidget, QFileDialog,
                               QInputDialog, QLabel, QMainWindow, QMessageBox,
                               QSlider, QToolBar)

from .. import APP_NAME, __version__
from ..core import export
from ..core.pipeline import ProcessingResult, process_scan
from ..core.project import Project, ProjectError
from ..core.rawscan import find_scan_folders
from . import i18n
from .panels import LogPanel, ParamsPanel, ProjectPanel
from .viewer import PointCloudGLWidget
from .workers import WorkerManager

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1440, 900)
        self.settings = QSettings("scanorama", "studio")

        self.project: Project | None = None
        self._results: dict[str, ProcessingResult] = {}   # Cache pro Standpunkt
        self.workers = WorkerManager()

        self.viewer = PointCloudGLWidget(self)
        self.setCentralWidget(self.viewer)

        self._build_docks()
        self._build_toolbar()
        self._build_menu()
        self._update_enabled()
        self.statusBar().showMessage(
            self.tr("Bereit — Projekt anlegen oder öffnen (Strg+N / Strg+O)"))

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------
    def _build_docks(self) -> None:
        self.project_panel = ProjectPanel(self)
        dock = QDockWidget(self.tr("Projekt"), self)
        dock.setObjectName("dock_project")
        dock.setWidget(self.project_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        self.params_panel = ParamsPanel(self)
        dock = QDockWidget(self.tr("Verarbeitung"), self)
        dock.setObjectName("dock_params")
        dock.setWidget(self.params_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self.log_panel = LogPanel(self)
        dock = QDockWidget(self.tr("Protokoll"), self)
        dock.setObjectName("dock_log")
        dock.setWidget(self.log_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

        self.project_panel.stationSelected.connect(self._show_station)
        self.project_panel.stationToggled.connect(self._toggle_station)
        self.project_panel.importRequested.connect(self._import_scans)
        self.project_panel.removeRequested.connect(self._remove_station)
        self.params_panel.applyRequested.connect(self._apply_params)

    def _build_toolbar(self) -> None:
        tb = QToolBar(self.tr("Ansicht"), self)
        tb.setObjectName("toolbar_view")
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addWidget(QLabel(self.tr(" Farbe: ")))
        self.color_box = QComboBox()
        self.color_box.addItem(self.tr("Intensität"), "intensity")
        self.color_box.addItem(self.tr("Höhe"), "height")
        self.color_box.addItem(self.tr("Standpunkt"), "station")
        self.color_box.currentIndexChanged.connect(
            lambda: self.viewer.set_color_mode(self.color_box.currentData()))
        tb.addWidget(self.color_box)

        tb.addWidget(QLabel(self.tr(" Punktgröße: ")))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(1, 10)
        slider.setValue(2)
        slider.setFixedWidth(120)
        slider.valueChanged.connect(self.viewer.set_point_size)
        tb.addWidget(slider)

        act_fit = QAction(self.tr("Einpassen"), self)
        act_fit.setShortcut("F")
        act_fit.triggered.connect(self.viewer.fit_view)
        tb.addAction(act_fit)

    def _build_menu(self) -> None:
        m_project = self.menuBar().addMenu(self.tr("&Projekt"))

        act = QAction(self.tr("&Neues Projekt…"), self)
        act.setShortcut(QKeySequence.StandardKey.New)
        act.triggered.connect(self._new_project)
        m_project.addAction(act)

        act = QAction(self.tr("Projekt ö&ffnen…"), self)
        act.setShortcut(QKeySequence.StandardKey.Open)
        act.triggered.connect(self._open_project)
        m_project.addAction(act)

        m_project.addSeparator()
        self.act_import = QAction(self.tr("Scans &importieren…"), self)
        self.act_import.setShortcut("Ctrl+I")
        self.act_import.triggered.connect(self._import_scans)
        m_project.addAction(self.act_import)

        self.act_export = QAction(self.tr("Standpunkt &exportieren…"), self)
        self.act_export.setShortcut("Ctrl+E")
        self.act_export.triggered.connect(self._export_current)
        m_project.addAction(self.act_export)

        m_project.addSeparator()
        act = QAction(self.tr("&Beenden"), self)
        act.setShortcut(QKeySequence.StandardKey.Quit)
        act.triggered.connect(self.close)
        m_project.addAction(act)

        m_settings = self.menuBar().addMenu(self.tr("&Einstellungen"))
        m_lang = m_settings.addMenu(self.tr("&Sprache / Language"))
        for code, label in i18n.LANGUAGES.items():
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(code == i18n.current_language())
            act.triggered.connect(
                lambda _=False, c=code: self._set_language(c))
            m_lang.addAction(act)

    def _set_language(self, code: str) -> None:
        i18n.set_language(code)
        QMessageBox.information(
            self, APP_NAME,
            self.tr("Die Sprache wird beim nächsten Start übernommen."))

    def _update_enabled(self) -> None:
        has_project = self.project is not None
        self.act_import.setEnabled(has_project)
        self.act_export.setEnabled(has_project and bool(self._results))
        self.params_panel.setEnabled(has_project)
        self.project_panel.setEnabled(has_project)

    # ------------------------------------------------------------------
    # Projekt-Verwaltung
    # ------------------------------------------------------------------
    def _new_project(self) -> None:
        root = QFileDialog.getExistingDirectory(
            self, self.tr("Ordner für das neue Projekt wählen"),
            self.settings.value("last_dir", str(Path.home())))
        if not root:
            return
        name, ok = QInputDialog.getText(self, self.tr("Neues Projekt"),
                                        self.tr("Projektname:"),
                                        text=Path(root).name)
        if not ok or not name:
            return
        try:
            # In einen Unterordner mit Projektnamen anlegen, falls der
            # gewählte Ordner nicht leer ist.
            target = Path(root)
            if any(target.iterdir()):
                target = target / name
            self.project = Project.create(target, name)
        except ProjectError as e:
            QMessageBox.critical(self, APP_NAME, str(e))
            return
        self.settings.setValue("last_dir", str(Path(root)))
        self._project_loaded()

    def _open_project(self) -> None:
        root = QFileDialog.getExistingDirectory(
            self, self.tr("Projektordner öffnen"),
            self.settings.value("last_dir", str(Path.home())))
        if not root:
            return
        try:
            self.project = Project.open(root)
        except ProjectError as e:
            QMessageBox.critical(self, APP_NAME, str(e))
            return
        self.settings.setValue("last_dir", str(Path(root).parent))
        self._project_loaded()

    def _project_loaded(self) -> None:
        self._results.clear()
        self.viewer.set_cloud(None)
        self.params_panel.set_params(self.project.params)
        self.project_panel.set_project(self.project)
        self.setWindowTitle(f"{APP_NAME} — {self.project.name}")
        self.statusBar().showMessage(
            self.tr("Projekt geladen: %s (%d Standpunkte)")
            % (self.project.name, len(self.project.stations)))
        self._update_enabled()

    def _import_scans(self) -> None:
        if self.project is None:
            return
        root = QFileDialog.getExistingDirectory(
            self, self.tr("Ordner mit Scan-Ordnern wählen (Stick/Netzwerk)"),
            self.settings.value("last_import_dir", str(Path.home())))
        if not root:
            return
        self.settings.setValue("last_import_dir", root)
        found = find_scan_folders(root)
        if not found:
            QMessageBox.information(
                self, APP_NAME,
                self.tr("Keine Scan-Ordner gefunden in:\n%s") % root)
            return
        imported = 0
        for scan_dir in found:
            try:
                self.project.import_scan(scan_dir)
                imported += 1
            except ProjectError as e:
                log.warning(str(e))
        self.project_panel.set_project(self.project)
        self.statusBar().showMessage(
            self.tr("%d Scan(s) importiert") % imported)
        self._update_enabled()

    def _remove_station(self, folder: str) -> None:
        if self.project is None:
            return
        answer = QMessageBox.question(
            self, APP_NAME,
            self.tr("Standpunkt „%s“ aus dem Projekt entfernen?\n"
                    "(Dateien im Projektordner werden gelöscht)") % folder)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.project.remove_station(folder, delete_files=True)
        self._results.pop(folder, None)
        self.project_panel.set_project(self.project)
        self._update_enabled()

    def _toggle_station(self, folder: str, enabled: bool) -> None:
        if self.project is None:
            return
        self.project.get_station(folder).enabled = enabled
        self.project.save()

    # ------------------------------------------------------------------
    # Verarbeitung & Anzeige
    # ------------------------------------------------------------------
    def _show_station(self, folder: str) -> None:
        if self.project is None:
            return
        if folder in self._results:
            self._display_result(folder)
            return
        self._process_station(folder, show_after=True)

    def _process_station(self, folder: str, show_after: bool = False) -> None:
        station = self.project.get_station(folder)
        scan_dir = self.project.station_path(station)
        params = self.project.params
        self.project_panel.set_status(folder, self.tr("verarbeite…"))
        self.statusBar().showMessage(self.tr("Verarbeite %s …") % folder)

        def on_result(result, folder=folder, show=show_after):
            self._results[folder] = result
            self.project_panel.set_status(
                folder, self.tr("%d Punkte") % len(result.cloud))
            if show:
                self._display_result(folder)
            self._update_enabled()

        def on_error(message, folder=folder):
            self.project_panel.set_status(folder, self.tr("Fehler"))
            QMessageBox.critical(self, APP_NAME, message)

        self.workers.start(process_scan, scan_dir, params,
                           on_result=on_result, on_error=on_error)

    def _display_result(self, folder: str) -> None:
        result = self._results[folder]
        self.viewer.set_cloud(result.cloud)
        floor = (self.tr("Boden→Z=0") if result.floor_transform is not None
                 else self.tr("kein Bodenfit"))
        self.statusBar().showMessage(
            f"{folder}: {len(result.cloud):,} "
            + self.tr("Punkte") + f" ({floor})")

    def _apply_params(self) -> None:
        if self.project is None:
            return
        self.project.params = self.params_panel.params()
        self.project.save()
        self._results.clear()
        current = self.project_panel.current_folder()
        for s in self.project.stations:
            self._process_station(s.folder,
                                  show_after=(s.folder == current))

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _export_current(self) -> None:
        if self.project is None:
            return
        folder = self.project_panel.current_folder()
        if not folder or folder not in self._results:
            QMessageBox.information(
                self, APP_NAME,
                self.tr("Bitte zuerst einen verarbeiteten Standpunkt wählen."))
            return
        formats, ok = QInputDialog.getItem(
            self, self.tr("Exportieren"),
            self.tr("Format:"), ["e57", "ply", "las", "laz"], 0, False)
        if not ok:
            return
        cloud = self._results[folder].cloud

        def do_export():
            return export.export_cloud(
                cloud, self.project.output_dir / folder, [formats])

        def on_result(written):
            self.statusBar().showMessage(
                self.tr("Exportiert: %s") % ", ".join(str(w) for w in written))

        self.workers.start(do_export, on_result=on_result,
                           on_error=lambda m: QMessageBox.critical(
                               self, APP_NAME, m))

    # ------------------------------------------------------------------
    def closeEvent(self, ev) -> None:
        self.log_panel.detach()
        super().closeEvent(ev)
