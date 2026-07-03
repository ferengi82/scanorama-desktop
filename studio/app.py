"""GUI-Einstiegspunkt (wird in M3 zum vollen Hauptfenster ausgebaut).

Aktuell: minimales Fenster mit 3D-Viewer, Scan-Ordner öffnen,
Farbmodus- und Punktgrößen-Umschaltung — zum Testen des Viewers.
"""

from __future__ import annotations

import logging
import sys


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME
    from .ui import i18n
    from .ui.mainwindow import MainWindow
    from .ui.viewer.widget import set_default_gl_format

    # VOR der QApplication: Desktop-OpenGL erzwingen (Windows könnte
    # sonst ANGLE/Direct3D wählen) und das 3.3-Core-Format setzen.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    set_default_gl_format()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    i18n.install_translator(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
