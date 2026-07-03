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
from ..core import export, fusion
from ..core.pipeline import ProcessingResult, process_scan
from ..core.project import Project, ProjectError
from ..core.rawscan import find_scan_folders
from ..core.registration import RegistrationParams, register_stations
from . import i18n
from .panels import LogPanel, ParamsPanel, ProjectPanel
from .tools import ToolsPanel
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
        self._fused = None                                # fusionierte Gesamtwolke
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

        self.tools_panel = ToolsPanel(self.viewer, self)
        dock = QDockWidget(self.tr("Werkzeuge"), self)
        dock.setObjectName("dock_tools")
        dock.setWidget(self.tools_panel)
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

        m_reg = self.menuBar().addMenu(self.tr("&Registrierung"))
        self.act_register = QAction(
            self.tr("Standpunkte &registrieren && fusionieren"), self)
        self.act_register.setShortcut("Ctrl+R")
        self.act_register.triggered.connect(self._register_and_fuse)
        m_reg.addAction(self.act_register)

        self.act_show_fused = QAction(self.tr("&Gesamtwolke anzeigen"), self)
        self.act_show_fused.triggered.connect(self._show_fused)
        m_reg.addAction(self.act_show_fused)

        m_reg.addSeparator()
        self.act_export_fused = QAction(
            self.tr("Gesamtwolke e&xportieren…"), self)
        self.act_export_fused.triggered.connect(self._export_fused)
        m_reg.addAction(self.act_export_fused)

        self.act_export_e57 = QAction(
            self.tr("Alle Standpunkte als &E57 mit Posen (Metashape)…"), self)
        self.act_export_e57.triggered.connect(self._export_e57_stations)
        m_reg.addAction(self.act_export_e57)

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
        n_enabled = (sum(s.enabled for s in self.project.stations)
                     if has_project else 0)
        self.act_register.setEnabled(n_enabled >= 2)
        has_fused = self._fused is not None
        self.act_show_fused.setEnabled(has_fused)
        self.act_export_fused.setEnabled(has_fused)
        self.act_export_e57.setEnabled(
            has_project and any(s.pose is not None for s in self.project.stations))

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
        self._fused = None
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
    # Registrierung & Fusion
    # ------------------------------------------------------------------
    def _register_and_fuse(self) -> None:
        if self.project is None:
            return
        enabled = [s for s in self.project.stations if s.enabled]
        if len(enabled) < 2:
            QMessageBox.information(
                self, APP_NAME,
                self.tr("Mindestens zwei aktive Standpunkte nötig."))
            return

        project = self.project
        params = project.params
        cached = dict(self._results)
        folders = [s.folder for s in enabled]
        voxel = project.fusion_voxel_m
        self.statusBar().showMessage(
            self.tr("Registriere %d Standpunkte …") % len(enabled))

        def job():
            results = {}
            for s in enabled:
                if s.folder in cached:
                    results[s.folder] = cached[s.folder]
                else:
                    results[s.folder] = process_scan(
                        project.station_path(s), params)
            clouds = [results[f].cloud for f in folders]
            reg = register_stations(clouds, RegistrationParams())
            fused = fusion.fuse(clouds, reg.poses, voxel_size_m=voxel)
            return results, reg, fused

        def on_result(payload):
            results, reg, fused = payload
            self._results.update(results)
            for s, T in zip(enabled, reg.poses):
                s.set_pose(T)
            self.project.save()
            self._fused = fused
            for folder in folders:
                self.project_panel.set_status(
                    folder, self.tr("%d Punkte") % len(results[folder].cloud))
            self._show_fused()
            weakest = min(reg.pairs, key=lambda p: p.fitness) if reg.pairs else None
            note = ""
            if weakest is not None:
                note = self.tr("\nSchwächstes Paar: %d→%d (%s, Fitness %.2f)") % (
                    weakest.source, weakest.target, weakest.rating,
                    weakest.fitness)
            QMessageBox.information(
                self, APP_NAME,
                self.tr("Registrierung abgeschlossen — Gesamtwolke: "
                        "%d Punkte.") % len(fused) + note)
            self._update_enabled()

        self.workers.start(job, on_result=on_result,
                           on_error=lambda m: QMessageBox.critical(
                               self, APP_NAME, m))

    def _show_fused(self) -> None:
        if self._fused is None:
            return
        self.viewer.set_cloud(self._fused)
        self.color_box.setCurrentIndex(2)   # Standpunkt-Farben
        self.viewer.set_color_mode("station")
        self.statusBar().showMessage(
            self.tr("Gesamtwolke: %d Punkte aus %d Standpunkten") % (
                len(self._fused), self._fused.meta.get("stations", 0)))

    def _export_fused(self) -> None:
        if self._fused is None or self.project is None:
            return
        formats, ok = QInputDialog.getItem(
            self, self.tr("Gesamtwolke exportieren"),
            self.tr("Format:"), ["e57", "ply", "las", "laz"], 0, False)
        if not ok:
            return
        cloud = self._fused
        out = self.project.output_dir / "gesamtwolke"

        self.workers.start(
            export.export_cloud, cloud, out, [formats],
            on_result=lambda written: self.statusBar().showMessage(
                self.tr("Exportiert: %s") % ", ".join(str(w) for w in written)),
            on_error=lambda m: QMessageBox.critical(self, APP_NAME, m))

    def _export_e57_stations(self) -> None:
        """Alle registrierten Standpunkte als E57-Stationen mit Posen —
        Metashape importiert sie fertig ausgerichtet."""
        if self.project is None:
            return
        stations = [s for s in self.project.stations
                    if s.pose is not None and s.folder in self._results]
        if len(stations) < 1:
            QMessageBox.information(
                self, APP_NAME,
                self.tr("Erst registrieren — es gibt noch keine Posen."))
            return
        clouds = [self._results[s.folder].cloud for s in stations]
        poses = [s.pose_matrix() for s in stations]
        names = [s.folder for s in stations]
        target = self.project.output_dir / "standpunkte_posen.e57"

        self.workers.start(
            export.save_e57, clouds, target, poses, names,
            on_result=lambda _: self.statusBar().showMessage(
                self.tr("E57 mit Posen exportiert: %s") % target),
            on_error=lambda m: QMessageBox.critical(self, APP_NAME, m))

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
