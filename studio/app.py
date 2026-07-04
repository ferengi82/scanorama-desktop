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
    from PySide6.QtCore import (QCoreApplication, QSettings, Qt,
                                qInstallMessageHandler)
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME
    from .ui import i18n
    from .ui.mainwindow import MainWindow
    from .ui.viewer.widget import set_default_gl_format

    # Qt-eigene Warnungen (z.B. "Failed to create context") laufen am
    # Python-Logging vorbei — hier einfangen, damit sie im Protokoll stehen.
    qt_log = logging.getLogger("qt")
    qInstallMessageHandler(
        lambda _mode, _ctx, message: qt_log.warning(message))

    # VOR der QApplication: Rendering-Backend wählen. Default ist
    # Desktop-OpenGL (Windows könnte sonst ANGLE/Direct3D wählen);
    # bei Treibern ohne GL 3.3 (oder Remote Desktop) kann auf
    # Software-Rendering umgeschaltet werden (Mesa/opengl32sw.dll).
    if QSettings("scanorama", "studio").value("opengl", "desktop") == "software":
        QCoreApplication.setAttribute(
            Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
        logging.info("Software-OpenGL aktiv (Einstellung)")
    else:
        QCoreApplication.setAttribute(
            Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    set_default_gl_format()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    i18n.install_translator(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
