"""3D-Punktwolken-Viewer (QOpenGLWidget).

Aufteilung:
    camera.py  — Orbit-Kamera-Mathematik (reines numpy, testbar ohne GL)
    colors.py  — Einfärbung Intensität/Höhe/Standpunkt (reines numpy)
    widget.py  — QOpenGLWidget mit VBO-Rendering und Permutations-LOD
"""

from .widget import PointCloudGLWidget

__all__ = ["PointCloudGLWidget"]
