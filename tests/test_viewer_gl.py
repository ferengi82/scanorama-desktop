"""GL-Smoke-Test: Widget offscreen rendern (übersprungen ohne GL-Kontext).

Prüft, dass Shader kompilieren, VBO-Upload funktioniert und ein Frame
mit Inhalt entsteht (nicht nur Hintergrundfarbe).
"""

import os

import numpy as np
import pytest

# Ohne Display auf "offscreen" ausweichen; unter Xvfb/X11 normal (xcb+GLX)
if not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtOpenGLWidgets")

from studio.core.cloud import PointCloud  # noqa: E402


@pytest.fixture
def cloud():
    rng = np.random.default_rng(3)
    n = 50000
    return PointCloud(
        xyz=rng.uniform(-1, 1, (n, 3)).astype(np.float32),
        intensity=rng.integers(0, 256, n, dtype=np.uint8),
        scanner_dist=np.ones(n, np.float32),
    )


def test_widget_renders_offscreen(qtbot, cloud):
    from studio.ui.viewer import PointCloudGLWidget

    w = PointCloudGLWidget()
    qtbot.addWidget(w)
    w.resize(320, 240)
    w.show()
    qtbot.waitExposed(w)

    if w.context() is None or not w.context().isValid():
        pytest.skip("Kein OpenGL-Kontext (offscreen ohne GL-Treiber)")

    w.set_cloud(cloud)
    img = w.grabFramebuffer()
    assert img.width() > 0

    # Mindestens ein Pixel muss von der Hintergrundfarbe abweichen
    arr = np.frombuffer(bytes(img.constBits()), dtype=np.uint8)
    unique = len(np.unique(arr.reshape(-1, 4)[:, :3], axis=0))
    assert unique > 1, "Frame enthält nur Hintergrund — nichts gerendert"

    # Farbmodus-Wechsel darf nicht crashen
    w.set_color_mode("height")
    w.grabFramebuffer()
