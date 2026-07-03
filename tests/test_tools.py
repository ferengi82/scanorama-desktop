"""Tests: Werkzeug-Panel (Messen, Punkt-Info, Clipping) + Picking mit Box."""

import os

import numpy as np
import pytest

if not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("pytestqt")

from studio.core.cloud import PointCloud  # noqa: E402
from studio.ui.viewer.picking import pick_point  # noqa: E402


def _cloud():
    xyz = np.array([[0, 2, 0], [0, 4, 0], [1, 2, 1]], dtype=np.float32)
    return PointCloud(xyz=xyz,
                      intensity=np.array([10, 20, 30], np.uint8),
                      scanner_dist=np.array([2, 4, 2.5], np.float32),
                      station=np.array([0, 0, 1], np.uint16))


@pytest.fixture
def panel(qtbot):
    from studio.ui.tools import ToolsPanel
    from studio.ui.viewer import PointCloudGLWidget
    viewer = PointCloudGLWidget()
    qtbot.addWidget(viewer)
    viewer.set_cloud(_cloud(), fit_view=False)
    p = ToolsPanel(viewer)
    qtbot.addWidget(p)
    return p


def test_measure_two_points(panel):
    panel.rb_measure.setChecked(True)
    assert panel.viewer.tool == "measure"
    panel.viewer.pointPicked.emit(0, np.array([0.0, 2.0, 0.0]))
    assert "Zweiten Punkt" in panel.result_label.text()
    panel.viewer.pointPicked.emit(1, np.array([0.0, 4.0, 0.0]))
    assert "2.000 m" in panel.result_label.text()
    # Overlay enthält beide Messpunkte
    assert panel.viewer._overlay.shape == (2, 3)


def test_measure_third_point_starts_over(panel):
    panel.rb_measure.setChecked(True)
    for idx, pt in [(0, [0, 2, 0]), (1, [0, 4, 0]), (2, [1, 2, 1])]:
        panel.viewer.pointPicked.emit(idx, np.array(pt, dtype=float))
    assert len(panel._measure_points) == 1  # neue Messung begonnen


def test_info_tool(panel):
    panel.rb_info.setChecked(True)
    panel.viewer.pointPicked.emit(2, np.array([1.0, 2.0, 1.0]))
    text = panel.result_label.text()
    assert "Intensität: 30" in text
    assert "Standpunkt: 1" in text
    assert "2.50 m" in text


def test_tool_switch_clears_measurement(panel):
    panel.rb_measure.setChecked(True)
    panel.viewer.pointPicked.emit(0, np.array([0.0, 2.0, 0.0]))
    panel.rb_orbit.setChecked(True)
    assert panel._measure_points == []
    assert panel.viewer._overlay is None


def test_clip_box_applied(panel):
    panel.reset_clip_to_cloud()
    panel.box_clip.setChecked(True)
    panel._clip_spins["zmax"].setValue(0.5)   # oberen Punkt wegschneiden
    lo, hi = panel.viewer.clip_box
    assert hi[2] == pytest.approx(0.5)

    # Picking respektiert die Box: Strahl auf den Punkt bei z=1
    idx = pick_point(panel.viewer.cloud.xyz,
                     origin=np.array([1.0, 0.0, 1.0]),
                     direction=np.array([0.0, 1.0, 0.0]),
                     clip_box=panel.viewer.clip_box)
    assert idx is None
    panel.box_clip.setChecked(False)
    assert panel.viewer.clip_box is None
