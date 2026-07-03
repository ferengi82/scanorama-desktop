"""Orbit-Kamera: Mathematik ohne jede GL-Abhängigkeit.

Konvention wie im Datenformat: Z = oben. Die Kamera umkreist einen
Zielpunkt (``target``) auf Kugelkoordinaten (Azimut ``yaw``, Höhenwinkel
``pitch``, Abstand ``distance``).

Alle Matrizen sind row-major numpy float32 und werden für OpenGL beim
Upload transponiert (GLSL erwartet column-major).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    """View-Matrix (4×4, row-major)."""
    f = _normalize(target - eye)
    s = _normalize(np.cross(f, up))
    u = np.cross(s, f)
    M = np.eye(4, dtype=np.float64)
    M[0, :3], M[1, :3], M[2, :3] = s, u, -f
    M[0, 3] = -np.dot(s, eye)
    M[1, 3] = -np.dot(u, eye)
    M[2, 3] = np.dot(f, eye)
    return M


def perspective(fov_y_deg: float, aspect: float,
                near: float, far: float) -> np.ndarray:
    """Perspektivische Projektionsmatrix (4×4, row-major)."""
    f = 1.0 / np.tan(np.radians(fov_y_deg) / 2.0)
    M = np.zeros((4, 4), dtype=np.float64)
    M[0, 0] = f / aspect
    M[1, 1] = f
    M[2, 2] = (far + near) / (near - far)
    M[2, 3] = 2 * far * near / (near - far)
    M[3, 2] = -1.0
    return M


@dataclass
class OrbitCamera:
    target: np.ndarray = field(default_factory=lambda: np.zeros(3))
    distance: float = 10.0
    yaw_deg: float = -45.0      # Drehung um Z
    pitch_deg: float = 30.0     # Höhenwinkel (0 = horizontal, 90 = von oben)
    fov_y_deg: float = 50.0

    MIN_PITCH = -89.0
    MAX_PITCH = 89.0
    MIN_DIST = 0.05
    MAX_DIST = 500.0

    @property
    def eye(self) -> np.ndarray:
        """Kameraposition in Weltkoordinaten."""
        yaw = np.radians(self.yaw_deg)
        pitch = np.radians(self.pitch_deg)
        d = self.distance
        return self.target + d * np.array([
            np.cos(pitch) * np.sin(yaw),
            np.cos(pitch) * np.cos(yaw),
            np.sin(pitch),
        ])

    def view_matrix(self) -> np.ndarray:
        return look_at(self.eye, self.target, np.array([0.0, 0.0, 1.0]))

    def proj_matrix(self, aspect: float) -> np.ndarray:
        # Clipping dynamisch an den Abstand koppeln → nutzbar von 5 cm
        # (Nahbereich) bis Gebäudegröße ohne Z-Fighting.
        near = max(self.distance * 0.001, 0.005)
        far = max(self.distance * 20.0, 100.0)
        return perspective(self.fov_y_deg, aspect, near, far)

    def mvp(self, aspect: float) -> np.ndarray:
        return self.proj_matrix(aspect) @ self.view_matrix()

    # --- Interaktion ------------------------------------------------------
    def rotate(self, dx_px: float, dy_px: float) -> None:
        """Orbit: Mausbewegung in Pixel → Winkeländerung."""
        self.yaw_deg = (self.yaw_deg + dx_px * 0.3) % 360.0
        self.pitch_deg = float(np.clip(self.pitch_deg + dy_px * 0.3,
                                       self.MIN_PITCH, self.MAX_PITCH))

    def pan(self, dx_px: float, dy_px: float, viewport_h: int) -> None:
        """Verschiebt den Zielpunkt in der Bildebene."""
        # Weltgröße eines Pixels in Zielpunkt-Entfernung
        scale = 2.0 * self.distance * np.tan(np.radians(self.fov_y_deg) / 2) / max(viewport_h, 1)
        V = self.view_matrix()
        right, up = V[0, :3], V[1, :3]
        self.target = self.target - right * dx_px * scale + up * dy_px * scale

    def zoom(self, steps: float) -> None:
        """Mausrad: ein Schritt ≈ 15 % näher/weiter."""
        self.distance = float(np.clip(self.distance * (0.85 ** steps),
                                      self.MIN_DIST, self.MAX_DIST))

    def fit(self, bbox_min: np.ndarray, bbox_max: np.ndarray) -> None:
        """Kamera so setzen, dass die Bounding-Box komplett sichtbar ist."""
        bbox_min = np.asarray(bbox_min, dtype=np.float64)
        bbox_max = np.asarray(bbox_max, dtype=np.float64)
        self.target = (bbox_min + bbox_max) / 2.0
        radius = float(np.linalg.norm(bbox_max - bbox_min)) / 2.0
        radius = max(radius, 0.1)
        self.distance = float(np.clip(
            radius / np.tan(np.radians(self.fov_y_deg) / 2.0) * 1.1,
            self.MIN_DIST, self.MAX_DIST))

    def screen_ray(self, x_px: float, y_px: float,
                   width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
        """Bildpunkt → Strahl (Ursprung, Richtung) in Weltkoordinaten.

        Grundlage für CPU-Picking (Punkt anklicken).
        """
        ndc_x = 2.0 * x_px / max(width, 1) - 1.0
        ndc_y = 1.0 - 2.0 * y_px / max(height, 1)
        aspect = width / max(height, 1)
        tan_f = np.tan(np.radians(self.fov_y_deg) / 2.0)

        V = self.view_matrix()
        right, up, back = V[0, :3], V[1, :3], V[2, :3]
        forward = -back
        direction = _normalize(forward
                               + right * ndc_x * tan_f * aspect
                               + up * ndc_y * tan_f)
        return self.eye, direction
