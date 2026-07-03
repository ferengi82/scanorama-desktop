# Entscheidungen (Kickoff-Interview 2026-07-03)

Referenz für alle weiteren Arbeiten an Scanorama Studio.

## Interview-Ergebnisse (User-Entscheidungen)

| Thema | Entscheidung |
|---|---|
| Plattform | **Windows primär** (dort läuft auch Metashape — dessen Python-Libs dürfen bei Bedarf genutzt werden), Linux nice-to-have |
| Technologie | **Python + PySide6 (Qt)** mit eingebettetem OpenGL-3D-Viewer |
| Umfang v1 | **Vollausbau**: Rohdaten→Punktwolke+Export · 3D-Viewer · Registrierung/Fusion · Scan-Transfer vom Pi |
| Datenweg | **Beides**: Import aus beliebigem Ordner (USB-Stick) UND eingebauter SSH-Transfer vom Pi |
| Projekt-Konzept | **Ja**: Ein Projekt = Ordner mit Standpunkt-Scans + Einstellungen + Ergebnissen (`project.json`) |
| Exportformate | **E57, PLY, LAS/LAZ** (kein CSV in v1) |
| UI-Sprache | **Deutsch + Englisch** (Qt-Übersetzungssystem, umschaltbar) |
| Programmname | **Scanorama Studio** (Repo: scanorama-desktop) |
| Lizenz | MIT |
| Viewer-Funktionen | Navigation/Einfärbung + **Distanz messen, Schnitte/Clipping, Punkt-Info** |
| Georeferenzierung | **Später (v2)**: Standpunkt-Koordinaten eingeben → Transformation der Wolke ins Landessystem |
| Filter-Defaults | Aus Scanner-v1 übernehmen, einstellbar: Stativ el 165–195°, Nahbereich <0.30 m, SOR-Ausreißer, Boden→Z=0 (RANSAC); neu: el_offset-Kalibrierung |
| Verteilung | **Beides**: pip-Paket (Entwicklung) + fertige Windows-EXE (PyInstaller, GitHub Actions) |

## Architekturentscheidungen

### D1: Rohdaten-Lesen kommt aus dem Scanner-Paket

Das Scanner-Repo [ferengi82/scanorama](https://github.com/ferengi82/scanorama)
enthält bereits die hardwarefreie Dekodier-Logik (`scanorama.lidar.protocol`,
`scanorama.scan.decode`). Studio nutzt es als Dependency
(`scanorama @ git+https://github.com/ferengi82/scanorama`) statt Code zu
duplizieren — das Datenformat hat genau eine Implementierung.

### D2: Strikte Trennung core/ (UI-frei) und ui/ (PySide6)

Alle Verarbeitung (Dekodieren, Transformieren, Filtern, Registrieren,
Exportieren, Projekt, Transfer) lebt in `studio/core/` — ohne Qt-Import,
vollständig pytest-bar, auch headless/CLI nutzbar. Die UI ist eine
Schicht darüber und ruft nur core-Funktionen (in Worker-Threads) auf.

### D3: Eigener OpenGL-Punktwolken-Viewer (QOpenGLWidget)

Ein schlanker Renderer (VBOs, Shader, Octree-Dezimierung beim Navigieren)
statt schwerer Viewer-Frameworks. Ziel: ein 180°-Scan (~4 Mio. Punkte)
flüssig, fusionierte Projekte (~20 Mio.) mit LOD. Open3D wird NUR für
Algorithmen (FPFH/ICP/Pose-Graph/SOR) verwendet, nicht fürs Rendering.

### D4: Registrierung = portierte merge_scans-Pipeline

Die bewährte v1-Pipeline (FPFH+RANSAC → Multi-Scale-ICP → Pose-Graph →
distanzgewichtete Voxel-Fusion, inkl. der 2026-04-Fixes) wird nach
`core/registration.py`/`core/fusion.py` portiert und um die neuen
Rohdaten-Eingänge angepasst.

### D5: Projektordner als einzige Wahrheit

```
MeinAufmass/                  ← Projektordner
├── project.json              ← Einstellungen, Standpunktliste, Posen
├── scans/                    ← Original-Scan-Ordner vom Pi (unverändert!)
│   ├── 2026-07-02_scan_01_001/
│   └── 2026-07-02_scan_01_002/
└── output/                   ← Exporte, Registrierungs-Ergebnisse
```

Scan-Rohdaten werden nie verändert; alle Verarbeitung ist reproduzierbar
aus `project.json` + Rohdaten.

### D6: Pi-Transfer per SSH (paramiko)

Läuft auf Windows ohne externe Tools. Das Programm listet Scans auf dem
Pi (`~/scans`), zeigt Größe/Datum/Meta und kopiert gewählte Ordner ins
Projekt. Zugangsdaten (Host/User/Key) in den Programm-Einstellungen.

## Hardware/Umgebung

- Auswerte-PC: Windows, Metashape vorhanden (dessen Python-API bei
  Bedarf nutzbar — aber Kern-Pipeline bleibt unabhängig davon)
- Referenz-Testdaten: `pi:~/scans-v2/2026-07-02_scan_01_003/`
  (180°-Scan, 3.9 Mio. Punkte) + kleinere Kurz-Scans
