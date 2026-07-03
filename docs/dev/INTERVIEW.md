# Interview Desktop-Programm — abgeschlossen (2026-07-03)

Alle Fragen sind geklärt; die Ergebnisse stehen konsolidiert in
[DECISIONS.md](DECISIONS.md). Diese Datei bleibt als Protokoll.

| # | Frage | Antwort |
|---|---|---|
| 1 | Plattform | Windows primär; Metashape vorhanden, dessen Python-Libs nutzbar |
| 2 | Technologie | Python + Qt (PySide6) + eingebetteter 3D-Viewer |
| 3 | Umfang v1 | Rohdaten→Punktwolke+Export, 3D-Viewer, Registrierung/Fusion, Pi-Transfer |
| 4 | Datenweg Pi→PC | Beides: Netzwerk/SSH und USB-Stick (Import aus beliebigem Ordner) |
| 5 | Projekt-Konzept | Ja, Projektordner (Standpunkte + Einstellungen + Ergebnisse) |
| 6 | Exportformate | E57, PLY, LAS/LAZ |
| 7 | UI-Sprache | Deutsch + Englisch (umschaltbar) |
| 8 | Programmname | Scanorama Studio |
| 9 | Lizenz | MIT |
| 10 | Viewer | Distanz messen, Schnitte/Clipping, Punkt-Info; **später**: Standpunkt-Koordinaten → Landessystem |
| 11 | Filter-Defaults | v1-Defaults übernehmen (Stativ 165–195°, Nahbereich 0.30 m, SOR, Boden Z=0), einstellbar; neu el_offset |
| 12 | Verteilung | Beides: pip-Paket + Windows-EXE (PyInstaller/CI) |
