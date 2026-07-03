"""Scanorama Studio — Desktop-Auswertung für den scanorama-Scanner.

Architektur (siehe docs/dev/DECISIONS.md):
  - ``studio.core``  : UI-freie Verarbeitung (pytest-bar, headless nutzbar)
  - ``studio.ui``    : PySide6-Oberfläche über dem Core
  - ``studio.cli``   : Headless-Batchverarbeitung
"""

__version__ = "0.1.1"
APP_NAME = "Scanorama Studio"
