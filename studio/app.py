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
    from PySide6.QtWidgets import QApplication

    from . import APP_NAME
    from .ui.mainwindow import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
