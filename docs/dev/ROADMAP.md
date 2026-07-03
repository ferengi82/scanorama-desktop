# Roadmap Scanorama Studio

## v1 — Vollständige Auswertung (AKTUELL, Details in PLAN.md)

- [ ] M1 Core-Pipeline: Rohdaten → gefilterte Punktwolke → PLY/E57/LAS (CLI)
- [ ] M2 3D-Viewer (OpenGL, 4 Mio. Punkte flüssig)
- [ ] M3 Projekt-Konzept + UI-Shell (PySide6, DE/EN)
- [ ] M4 Registrierung/Fusion mehrerer Standpunkte
- [ ] M5 Viewer-Werkzeuge: Messen, Clipping, Punkt-Info
- [ ] M6 Scan-Transfer vom Pi (SSH)
- [ ] M7 Windows-EXE-Release (CI) + Doku DE/EN

## v2 — Vermessung

- [ ] **Georeferenzierung**: Standpunkt-Koordinaten im Landessystem
      eingeben → Transformation/Export der Gesamtwolke in
      Landeskoordinaten (User-Wunsch aus dem Interview)
- [ ] el_offset-Kalibrier-Assistent (geführter Workflow)

## v3 — Kameras & Mesh

- [ ] Foto-Integration (sobald der Scanner die Fotorunde hat)
- [ ] Metashape-Anbindung (Python-API vorhanden auf dem Auswerte-PC)
- [ ] Mesh-Erzeugung (Poisson) + Textur
