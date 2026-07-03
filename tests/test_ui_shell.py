"""UI-Shell-Test: Hauptfenster mit Projekt, Verarbeitung im Worker.

Läuft offscreen (kein GL nötig, solange das Fenster nicht angezeigt
wird — der Viewer initialisiert GL erst beim Anzeigen).
"""

import os

import pytest

if not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("pytestqt")

from studio.core.project import Project  # noqa: E402


@pytest.fixture
def window(qtbot, tmp_path):
    from studio.ui.mainwindow import MainWindow
    win = MainWindow()
    qtbot.addWidget(win)
    return win


def test_project_workflow(window, qtbot, tmp_path, mock_scan_dir):
    # Projekt anlegen + laden (ohne Dialoge, direkt über die API)
    window.project = Project.create(tmp_path / "prj", "UI-Test")
    window._project_loaded()
    assert "UI-Test" in window.windowTitle()

    # Scan importieren und im Panel anzeigen
    window.project.import_scan(mock_scan_dir)
    window.project_panel.set_project(window.project)
    assert window.project_panel.tree.topLevelItemCount() == 1

    # Standpunkt anzeigen → Worker verarbeitet im Hintergrund
    folder = mock_scan_dir.name
    window._show_station(folder)
    qtbot.waitUntil(lambda: folder in window._results, timeout=60000)
    result = window._results[folder]
    assert len(result.cloud) > 10000

    # Anzeige hat die Wolke übernommen
    assert window.viewer.cloud is result.cloud


def test_params_panel_roundtrip(window):
    from studio.core.filters import FilterParams
    from studio.core.pipeline import ProcessingParams

    p = ProcessingParams(el_offset_deg=-1.25,
                         filters=FilterParams(min_dist_m=0.5,
                                              sor_enabled=False),
                         align_floor=False)
    window.params_panel.set_params(p)
    q = window.params_panel.params()
    assert q.el_offset_deg == -1.25
    assert q.filters.min_dist_m == 0.5
    assert q.filters.sor_enabled is False
    assert q.align_floor is False


def test_apply_params_reprocesses(window, qtbot, tmp_path, mock_scan_dir):
    window.project = Project.create(tmp_path / "prj2", "Apply-Test")
    window._project_loaded()
    window.project.import_scan(mock_scan_dir)
    window.project_panel.set_project(window.project)

    window.params_panel.floor.setChecked(False)   # Mock-Szene: kein Boden
    window._apply_params()
    qtbot.waitUntil(lambda: mock_scan_dir.name in window._results,
                    timeout=60000)
    # Parameter wurden ins Projekt gespeichert
    reopened = Project.open(window.project.root)
    assert reopened.params.align_floor is False
