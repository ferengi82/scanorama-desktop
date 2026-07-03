"""Hintergrund-Ausführung von Core-Funktionen (UI bleibt bedienbar).

Ein Worker pro Aufgabe; Ergebnisse kommen als Qt-Signale zurück in den
GUI-Thread. Core-Code weiß nichts von Qt (Entscheidung D2) — hier ist
die einzige Brücke.
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QThread, Signal

log = logging.getLogger(__name__)


class CallableWorker(QThread):
    """Führt eine beliebige Funktion im Hintergrund aus.

    Signale:
        finished_ok(object) — Rückgabewert der Funktion
        failed(str)         — Fehlermeldung (Exception-Text)
    """
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable, *args, parent=None, **kwargs):
        super().__init__(parent)
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as e:   # UI-Grenze: melden statt abstürzen
            log.exception(f"Hintergrund-Aufgabe fehlgeschlagen: {self._fn}")
            self.failed.emit(str(e))
            return
        self.finished_ok.emit(result)


class WorkerManager:
    """Hält laufende Worker am Leben (Qt räumt sonst zu früh auf)."""

    def __init__(self):
        self._active: list[CallableWorker] = []

    def start(self, fn: Callable, *args,
              on_result: Callable | None = None,
              on_error: Callable | None = None, **kwargs) -> CallableWorker:
        worker = CallableWorker(fn, *args, **kwargs)
        if on_result:
            worker.finished_ok.connect(on_result)
        if on_error:
            worker.failed.connect(on_error)
        worker.finished.connect(lambda: self._active.remove(worker))
        self._active.append(worker)
        worker.start()
        return worker

    @property
    def busy(self) -> bool:
        return bool(self._active)
