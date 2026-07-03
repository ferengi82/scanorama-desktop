"""UI-Test des Registrier-Workflows (Kernalgorithmen gemockt —
die echte Registrierung ist in test_registration.py abgedeckt)."""

import os
from unittest.mock import patch

import numpy as np
import pytest

if not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("pytestqt")

from studio.core.cloud import PointCloud  # noqa: E402
from studio.core.project import Project  # noqa: E402
from studio.core.registration import (PairQuality,  # noqa: E402
                                      RegistrationResult)


def _tiny_cloud(n=100):
    rng = np.random.default_rng(0)
    return PointCloud(xyz=rng.uniform(-1, 1, (n, 3)).astype(np.float32),
                      intensity=np.full(n, 50, np.uint8),
                      scanner_dist=np.ones(n, np.float32))


def test_register_and_fuse_flow(qtbot, tmp_path, mock_scan_dir, monkeypatch):
    import shutil

    from studio.ui.mainwindow import MainWindow

    # Auto-OK für die Abschluss-Meldung
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))

    win = MainWindow()
    qtbot.addWidget(win)
    win.project = Project.create(tmp_path / "prj", "Reg-Test")
    win._project_loaded()

    # Zwei Standpunkte: derselbe Mock-Scan, zweite Kopie umbenannt
    win.project.import_scan(mock_scan_dir)
    copy = tmp_path / (mock_scan_dir.name[:-1] + "9")
    shutil.copytree(mock_scan_dir, copy)
    win.project.import_scan(copy)
    win.project_panel.set_project(win.project)
    win._update_enabled()
    assert win.act_register.isEnabled()

    T = np.eye(4)
    T[:3, 3] = [1.0, 0.0, 0.0]
    fake_reg = RegistrationResult(poses=[np.eye(4), T],
                                  pairs=[PairQuality(1, 0, 0.8, 0.005)])
    fused = _tiny_cloud()
    fused.meta["stations"] = 2

    with patch("studio.ui.mainwindow.register_stations",
               return_value=fake_reg) as mock_reg, \
         patch("studio.ui.mainwindow.fusion") as mock_fusion:
        mock_fusion.fuse.return_value = fused
        win._register_and_fuse()
        qtbot.waitUntil(lambda: win._fused is not None, timeout=120000)

    assert mock_reg.called
    # Posen wurden gespeichert
    reopened = Project.open(win.project.root)
    poses = [s.pose_matrix() for s in reopened.stations]
    assert poses[0] is not None and poses[1] is not None
    np.testing.assert_allclose(poses[1], T)
    # Gesamtwolke wird angezeigt, Export-Aktionen aktiv
    assert win.viewer.cloud is fused
    assert win.act_export_fused.isEnabled()
    assert win.act_export_e57.isEnabled()
