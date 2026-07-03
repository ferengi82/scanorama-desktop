"""Sprachumschaltung Deutsch/Englisch.

Die Quelltexte der Oberfläche sind Deutsch (``self.tr("…")``); für
Englisch wird eine Qt-Übersetzung (``translations/en.qm``) geladen.
Die Sprache steht in den QSettings und wirkt nach einem Neustart.

Übersetzungs-Workflow (M7):
    pyside6-lupdate studio -ts studio/ui/translations/en.ts
    # en.ts übersetzen, dann:
    pyside6-lrelease studio/ui/translations/en.ts
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSettings, QTranslator

log = logging.getLogger(__name__)

LANGUAGES = {"de": "Deutsch", "en": "English"}
_translator: QTranslator | None = None   # muss am Leben bleiben


def current_language() -> str:
    return str(QSettings("scanorama", "studio").value("language", "de"))


def set_language(lang: str) -> None:
    if lang not in LANGUAGES:
        raise ValueError(f"Unbekannte Sprache: {lang}")
    QSettings("scanorama", "studio").setValue("language", lang)


def install_translator(app) -> None:
    """Lädt die Übersetzung für die eingestellte Sprache (falls nötig)."""
    global _translator
    lang = current_language()
    if lang == "de":
        return   # Quellsprache
    qm = Path(__file__).parent / "translations" / f"{lang}.qm"
    if not qm.exists():
        log.warning(f"Übersetzung fehlt: {qm} — Oberfläche bleibt Deutsch")
        return
    _translator = QTranslator()
    if _translator.load(str(qm)):
        app.installTranslator(_translator)
        log.info(f"Sprache: {LANGUAGES[lang]}")
