"""OpenGL-Punktwolken-Widget.

Rendering-Strategie:
  - Positionen (float32) und Farben (uint8, normalisiert) in zwei VBOs
  - Permutations-LOD: Die Punkte liegen zufällig permutiert im Buffer.
    Während der Interaktion werden nur die ersten ``lod_budget`` Punkte
    gezeichnet (= gleichmäßige Stichprobe), im Ruhezustand alle.
  - Shader mit gl_PointSize, runde Punkte per discard im Fragment-Shader.

Maus: links = Orbit, rechts/Mitte = Verschieben, Rad = Zoom,
Doppelklick = Ansicht auf Wolke einpassen.
"""

from __future__ import annotations

import logging

import numpy as np
from shiboken6 import VoidPtr
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QMatrix4x4, QSurfaceFormat
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader,
                              QOpenGLShaderProgram, QOpenGLVertexArrayObject)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ...core.cloud import PointCloud
from . import colors as colormod
from .camera import OrbitCamera
from .picking import pick_point

log = logging.getLogger(__name__)

GL_POINTS = 0x0000
GL_LINES = 0x0001
GL_DEPTH_TEST = 0x0B71
GL_PROGRAM_POINT_SIZE = 0x8642
GL_COLOR_BUFFER_BIT = 0x4000
GL_DEPTH_BUFFER_BIT = 0x0100
GL_FLOAT = 0x1406
GL_UNSIGNED_BYTE = 0x1401

_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec3 pos;
layout(location = 1) in vec3 col;
uniform mat4 mvp;
uniform float point_size;
out vec3 v_col;
out vec3 v_world;
void main() {
    gl_Position = mvp * vec4(pos, 1.0);
    gl_PointSize = point_size;
    v_col = col;
    v_world = pos;
}
"""

_FRAGMENT_SHADER = """
#version 330 core
in vec3 v_col;
in vec3 v_world;
uniform int clip_enabled;
uniform vec3 clip_min;
uniform vec3 clip_max;
uniform int round_points;
uniform int use_uniform_color;   // 1 = Overlay (Marker/Messlinie)
uniform vec3 uniform_color;
out vec4 frag;
void main() {
    if (clip_enabled == 1 &&
        (any(lessThan(v_world, clip_min)) ||
         any(greaterThan(v_world, clip_max)))) discard;
    if (round_points == 1) {
        // runde Punkte: Ecken des Point-Sprites verwerfen
        vec2 d = gl_PointCoord - vec2(0.5);
        if (dot(d, d) > 0.25) discard;
    }
    frag = vec4(use_uniform_color == 1 ? uniform_color : v_col, 1.0);
}
"""

TOOLS = ("orbit", "measure", "info")


class PointCloudGLWidget(QOpenGLWidget):
    """Zeigt eine PointCloud; Kamera und Farben sind von außen steuerbar."""

    #: Punktindex + Weltkoordinaten, wenn im Pick-Modus geklickt wurde
    pointPicked = Signal(int, object)

    def __init__(self, parent=None, lod_budget: int = 1_500_000):
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setSamples(0)
        QSurfaceFormat.setDefaultFormat(fmt)
        super().__init__(parent)

        self.camera = OrbitCamera()
        self.lod_budget = lod_budget
        self.point_size = 2.0
        self.color_mode = "intensity"
        self.tool = "orbit"                          # orbit | measure | info
        self.clip_box: tuple[np.ndarray, np.ndarray] | None = None
        self._overlay: np.ndarray | None = None      # (M,3) Marker-Punkte
        self._overlay_lines = False
        self._vbo_overlay: QOpenGLBuffer | None = None
        self._vao_overlay: QOpenGLVertexArrayObject | None = None
        self._dirty_overlay = False

        self._cloud: PointCloud | None = None
        self._perm: np.ndarray | None = None        # Permutation für LOD
        self._positions: np.ndarray | None = None   # permutiert, float32
        self._colors: np.ndarray | None = None      # permutiert, uint8
        self._dirty_positions = False
        self._dirty_colors = False

        self._program: QOpenGLShaderProgram | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._vbo_pos: QOpenGLBuffer | None = None
        self._vbo_col: QOpenGLBuffer | None = None
        self._gl_ready = False

        self._interacting = False
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(300)
        self._idle_timer.timeout.connect(self._end_interaction)
        self._last_mouse = None

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------
    def set_cloud(self, cloud: PointCloud | None, fit_view: bool = True) -> None:
        """Neue Wolke anzeigen (None = leeren)."""
        self._cloud = cloud
        if cloud is None or len(cloud) == 0:
            self._perm = self._positions = self._colors = None
        else:
            rng = np.random.default_rng(0)
            self._perm = rng.permutation(len(cloud))
            self._positions = np.ascontiguousarray(cloud.xyz[self._perm])
            self._colors = np.ascontiguousarray(
                colormod.colorize(cloud, self.color_mode)[self._perm])
            if fit_view:
                self.camera.fit(cloud.xyz.min(axis=0), cloud.xyz.max(axis=0))
        self._dirty_positions = True
        self._dirty_colors = True
        self.update()

    def set_color_mode(self, mode: str) -> None:
        if mode not in colormod.COLOR_MODES:
            raise ValueError(f"Unbekannter Farbmodus: {mode}")
        self.color_mode = mode
        if self._cloud is not None and self._perm is not None:
            self._colors = np.ascontiguousarray(
                colormod.colorize(self._cloud, mode)[self._perm])
            self._dirty_colors = True
        self.update()

    def set_point_size(self, px: float) -> None:
        self.point_size = float(np.clip(px, 1.0, 10.0))
        self.update()

    def fit_view(self) -> None:
        if self._cloud is not None and len(self._cloud):
            self.camera.fit(self._cloud.xyz.min(axis=0),
                            self._cloud.xyz.max(axis=0))
            self.update()

    def pick_at(self, x: float, y: float) -> int | None:
        """Punktindex unter der Bildschirmposition (Widget-Koordinaten)."""
        if self._cloud is None or len(self._cloud) == 0:
            return None
        origin, direction = self.camera.screen_ray(
            x, y, self.width(), self.height())
        return pick_point(self._cloud.xyz, origin, direction,
                          clip_box=self.clip_box)

    def set_tool(self, tool: str) -> None:
        if tool not in TOOLS:
            raise ValueError(f"Unbekanntes Werkzeug: {tool}")
        self.tool = tool

    def set_clip_box(self, lo, hi) -> None:
        """Axis-aligned Clipping-Box setzen (None/None = deaktivieren)."""
        if lo is None or hi is None:
            self.clip_box = None
        else:
            self.clip_box = (np.asarray(lo, dtype=np.float64),
                             np.asarray(hi, dtype=np.float64))
        self.update()

    def set_overlay(self, points: list[np.ndarray] | None,
                    lines: bool = True) -> None:
        """Marker-Punkte (z.B. Messpunkte) über der Wolke anzeigen.

        Bei ``lines=True`` werden aufeinanderfolgende Paare verbunden.
        """
        if not points:
            self._overlay = None
        else:
            self._overlay = np.asarray(points, dtype=np.float32).reshape(-1, 3)
        self._overlay_lines = lines
        self._dirty_overlay = True
        self.update()

    @property
    def cloud(self) -> PointCloud | None:
        return self._cloud

    # ------------------------------------------------------------------
    # OpenGL
    # ------------------------------------------------------------------
    def initializeGL(self) -> None:
        f = self.context().functions()
        f.glClearColor(0.13, 0.14, 0.15, 1.0)
        f.glEnable(GL_DEPTH_TEST)
        f.glEnable(GL_PROGRAM_POINT_SIZE)

        self._program = QOpenGLShaderProgram(self)
        ok = (self._program.addShaderFromSourceCode(
                  QOpenGLShader.ShaderTypeBit.Vertex, _VERTEX_SHADER)
              and self._program.addShaderFromSourceCode(
                  QOpenGLShader.ShaderTypeBit.Fragment, _FRAGMENT_SHADER)
              and self._program.link())
        if not ok:
            log.error(f"Shader-Fehler: {self._program.log()}")
            return

        self._vao = QOpenGLVertexArrayObject(self)
        self._vao.create()
        self._vbo_pos = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._vbo_pos.create()
        self._vbo_col = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._vbo_col.create()
        self._vao_overlay = QOpenGLVertexArrayObject(self)
        self._vao_overlay.create()
        self._vbo_overlay = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self._vbo_overlay.create()
        self._gl_ready = True
        self._dirty_positions = True
        self._dirty_colors = True
        self._dirty_overlay = True

    def _upload(self) -> None:
        f = self.context().functions()
        self._vao.bind()
        if self._dirty_positions and self._positions is not None:
            self._vbo_pos.bind()
            data = self._positions.tobytes()
            self._vbo_pos.allocate(data, len(data))
            f.glEnableVertexAttribArray(0)
            f.glVertexAttribPointer(0, 3, GL_FLOAT, 0, 0, VoidPtr(0))
            self._vbo_pos.release()
        if self._dirty_colors and self._colors is not None:
            self._vbo_col.bind()
            data = self._colors.tobytes()
            self._vbo_col.allocate(data, len(data))
            f.glEnableVertexAttribArray(1)
            f.glVertexAttribPointer(1, 3, GL_UNSIGNED_BYTE, 1, 0, VoidPtr(0))
            self._vbo_col.release()
        self._vao.release()
        self._dirty_positions = False
        self._dirty_colors = False

    def _upload_overlay(self) -> None:
        f = self.context().functions()
        if self._overlay is not None:
            self._vao_overlay.bind()
            self._vbo_overlay.bind()
            data = np.ascontiguousarray(self._overlay).tobytes()
            self._vbo_overlay.allocate(data, len(data))
            f.glEnableVertexAttribArray(0)
            f.glVertexAttribPointer(0, 3, GL_FLOAT, 0, 0, VoidPtr(0))
            f.glDisableVertexAttribArray(1)   # Farbe kommt als Konstante
            self._vbo_overlay.release()
            self._vao_overlay.release()
        self._dirty_overlay = False

    def paintGL(self) -> None:
        f = self.context().functions()
        f.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if not self._gl_ready or self._positions is None:
            return
        if self._dirty_positions or self._dirty_colors:
            self._upload()

        if self._dirty_overlay:
            self._upload_overlay()

        n = len(self._positions)
        count = min(n, self.lod_budget) if self._interacting else n

        aspect = self.width() / max(self.height(), 1)
        mvp = self.camera.mvp(aspect).astype(np.float32)

        p = self._program
        p.bind()
        p.setUniformValue(p.uniformLocation("mvp"),
                          QMatrix4x4(*mvp.flatten().tolist()))
        p.setUniformValue(p.uniformLocation("point_size"),
                          float(self.point_size))
        p.setUniformValue1i(p.uniformLocation("round_points"), 1)
        p.setUniformValue1i(p.uniformLocation("use_uniform_color"), 0)

        if self.clip_box is not None:
            lo, hi = self.clip_box
            p.setUniformValue1i(p.uniformLocation("clip_enabled"), 1)
            p.setUniformValue(p.uniformLocation("clip_min"),
                              float(lo[0]), float(lo[1]), float(lo[2]))
            p.setUniformValue(p.uniformLocation("clip_max"),
                              float(hi[0]), float(hi[1]), float(hi[2]))
        else:
            p.setUniformValue1i(p.uniformLocation("clip_enabled"), 0)

        self._vao.bind()
        f.glDrawArrays(GL_POINTS, 0, count)
        self._vao.release()

        # --- Overlay (Messpunkte/-linien) — immer sichtbar, ungeclippt ---
        if self._overlay is not None and len(self._overlay):
            f.glDisable(GL_DEPTH_TEST)
            p.setUniformValue1i(p.uniformLocation("clip_enabled"), 0)
            p.setUniformValue1i(p.uniformLocation("use_uniform_color"), 1)
            p.setUniformValue(p.uniformLocation("uniform_color"),
                              1.0, 0.62, 0.05)   # orange
            p.setUniformValue(p.uniformLocation("point_size"),
                              float(self.point_size) + 8.0)
            self._vao_overlay.bind()
            m = len(self._overlay)
            f.glDrawArrays(GL_POINTS, 0, m)
            if self._overlay_lines and m >= 2:
                p.setUniformValue1i(p.uniformLocation("round_points"), 0)
                f.glDrawArrays(GL_LINES, 0, m - (m % 2))
            self._vao_overlay.release()
            f.glEnable(GL_DEPTH_TEST)

        p.release()

    # ------------------------------------------------------------------
    # Interaktion
    # ------------------------------------------------------------------
    def _begin_interaction(self) -> None:
        self._interacting = True
        self._idle_timer.start()

    def _end_interaction(self) -> None:
        self._interacting = False
        self.update()   # volle Punktdichte nachzeichnen

    def mousePressEvent(self, ev) -> None:
        self._last_mouse = ev.position()
        if self.tool != "orbit" and ev.button() == Qt.MouseButton.LeftButton:
            idx = self.pick_at(ev.position().x(), ev.position().y())
            if idx is not None:
                self.pointPicked.emit(idx, self._cloud.xyz[idx].copy())

    def mouseMoveEvent(self, ev) -> None:
        if self._last_mouse is None:
            self._last_mouse = ev.position()
            return
        delta = ev.position() - self._last_mouse
        self._last_mouse = ev.position()
        buttons = ev.buttons()
        if buttons & Qt.MouseButton.LeftButton and self.tool == "orbit":
            self.camera.rotate(delta.x(), delta.y())
        elif buttons & (Qt.MouseButton.RightButton | Qt.MouseButton.MiddleButton):
            self.camera.pan(delta.x(), delta.y(), self.height())
        else:
            return
        self._begin_interaction()
        self.update()

    def wheelEvent(self, ev) -> None:
        steps = ev.angleDelta().y() / 120.0
        self.camera.zoom(steps)
        self._begin_interaction()
        self.update()

    def mouseDoubleClickEvent(self, ev) -> None:
        self.fit_view()
