# Roadmap Scanorama Studio

## v1 — Vollständige Auswertung (AKTUELL, Details in PLAN.md)

- [x] M1 Core-Pipeline: Rohdaten → gefilterte Punktwolke → PLY/E57/LAS (CLI)
- [x] M2 3D-Viewer (OpenGL; Performance-Abnahme auf Windows-GPU steht aus)
- [x] M3 Projekt-Konzept + UI-Shell (PySide6, DE/EN)
- [x] M4 Registrierung/Fusion mehrerer Standpunkte
- [x] M5 Viewer-Werkzeuge: Messen, Clipping, Punkt-Info
- [x] M6 Scan-Transfer vom Pi (SSH; Test gegen echten Pi steht aus — offline)
- [x] M7 CI + PyInstaller-Spec + Doku DE/EN (erster EXE-Build/Test auf Windows steht aus)

## v2 — Vermessung

- [ ] **Georeferenzierung**: Standpunkt-Koordinaten im Landessystem
      eingeben → Transformation/Export der Gesamtwolke in
      Landeskoordinaten (User-Wunsch aus dem Interview)
- [ ] el_offset-Kalibrier-Assistent (geführter Workflow)

## v3 — Kameras & Mesh

- [ ] Foto-Integration (sobald der Scanner die Fotorunde hat)
- [ ] Metashape-Anbindung (Python-API vorhanden auf dem Auswerte-PC)
- [ ] Mesh-Erzeugung (Poisson) + Textur
