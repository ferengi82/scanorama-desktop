# Umsetzungsplan Scanorama Studio

> Grundlage: Interview-Entscheidungen in [DECISIONS.md](DECISIONS.md).
> Stand: 2026-07-03. Fortschritt wird in [STATUS.md](STATUS.md) gepflegt.

## Zielbild

Windows-Desktop-Programm (Python + PySide6, DE/EN), das die Rohdaten des
Scanorama-Scanners vollständig auswertet: Scan-Ordner importieren (Ordner
oder SSH vom Pi), Punktwolke berechnen und filtern, mehrere Standpunkte
registrieren/fusionieren, im 3D-Viewer prüfen und messen, als
E57/PLY/LAS exportieren. Projektbasiert und reproduzierbar.

## Paketstruktur

```
scanorama-desktop/
├── pyproject.toml            Paket "scanorama-studio", GUI-Entry "scanorama-studio"
├── studio/
│   ├── core/                 UI-frei, pytest-bar (D2)
│   │   ├── rawscan.py        Scan-Ordner lesen/validieren (nutzt scanorama-Paket, D1)
│   │   ├── cloud.py          Punktwolken-Modell (numpy structured array + Meta)
│   │   ├── transform.py      el_offset-Kalibrierung, Polar→Kartesisch (DATAFORMAT-Formel)
│   │   ├── filters.py        Stativ-Bereich, Nahbereich, SOR-Ausreißer
│   │   ├── floor.py          RANSAC-Bodenerkennung → Z=0
│   │   ├── registration.py   FPFH+RANSAC → Multi-Scale-ICP → Pose-Graph (Open3D, D4)
│   │   ├── fusion.py         distanzgewichtete Voxel-Fusion
│   │   ├── export.py         PLY (eigen), E57 (pye57), LAS/LAZ (laspy)
│   │   ├── project.py        Projektordner + project.json (D5)
│   │   ├── transfer.py       SSH-Scanliste + Download vom Pi (paramiko, D6)
│   │   └── pipeline.py       Verarbeitungsschritte orchestrieren (auch headless)
│   ├── ui/
│   │   ├── mainwindow.py     Hauptfenster: Projektbaum, Viewer, Pipeline-Panel, Log
│   │   ├── viewer/           QOpenGLWidget-Renderer (D3): VBO, Shader, Octree-LOD,
│   │   │                     Einfärbung (Intensität/Höhe/Standpunkt), Picking
│   │   ├── panels/           Import, Filter-Parameter, Registrierung, Export, Pi-Transfer
│   │   ├── tools/            Distanzmessung, Clipping-Box/-Ebene, Punkt-Info
│   │   ├── workers.py        QThread-Wrapper um core.pipeline (UI bleibt flüssig)
│   │   └── i18n/             de.ts / en.ts (Qt Linguist)
│   └── cli.py                Headless-Batch: decode/filter/register/export ohne GUI
├── tests/                    pytest für core (mit echten Fixtures vom Referenzscan)
├── docs/                     README-Themen vertieft, DE+EN
├── .github/workflows/        CI: pytest (Linux+Windows) + PyInstaller-EXE-Release
└── docs/dev/                 DECISIONS / PLAN / ROADMAP / STATUS / INTERVIEW
```

Abhängigkeiten: `numpy`, `scanorama` (git), `open3d`, `laspy[lazrs]`,
`pye57`, `paramiko`, `PySide6`; dev: `pytest`, `pytest-qt`, `pyinstaller`.

## Meilensteine

### M1 — Core-Pipeline ohne UI (das Fundament)
1. Repo-Gerüst: pyproject, LICENSE (MIT), README-Stubs DE/EN, CI-Skelett
2. `rawscan.py`: Scan-Ordner laden (points.npz bevorzugt, sonst decode aus
   Rohdaten via scanorama-Paket), meta.json auswerten, Validierung
3. `transform.py` + `filters.py` + `floor.py`: Kartesische Wolke mit
   v1-Default-Filtern; el_offset als Parameter
4. `export.py`: PLY zuerst, dann LAS, dann E57
5. `cli.py`: `scanorama-studio-cli process <scanordner> --out xy.e57`
6. Tests mit echtem Referenzscan (verkleinerte Fixture im Repo,
   Vollscan lokal); Golden-Werte gegen v1-Ergebnisse aus dem alten
   Projekt vergleichen (Plausibilität, nicht Bit-Gleichheit)

**Meilenstein-Kriterium:** Referenzscan → gefilterte, bodenausgerichtete
E57/PLY/LAS per CLI, Ergebnis in CloudCompare geprüft.

### M2 — 3D-Viewer
1. QOpenGLWidget-Renderer: VBO-Upload, Punkt-Shader, Orbit-Navigation
2. Einfärbung: Intensität / Höhe / Standpunkt; Punktgröße einstellbar
3. Octree-Dezimierung: beim Bewegen reduzierte Dichte, ruhend voll
4. Picking (Punkt unterm Cursor) als Basis für Messen/Punkt-Info

**Kriterium:** 4-Mio.-Punkte-Scan flüssig auf dem Windows-PC (>30 fps
beim Navigieren).

### M3 — Projekt + UI-Shell
1. `project.py`: Projekt anlegen/öffnen, Scans importieren (Ordner-Kopie
   nach `scans/`), project.json (Einstellungen, Posen, Pipeline-Stand)
2. Hauptfenster: Projektbaum (Standpunkte), Viewer mittig,
   Pipeline-Panel (Filter-Parameter mit v1-Defaults), Log unten
3. Worker-Threads: Verarbeitung blockiert die UI nicht, Fortschrittsbalken
4. i18n-Gerüst DE/EN ab dem ersten Dialog (nachrüsten ist teuer)

**Kriterium:** Projekt anlegen → Scan importieren → verarbeiten →
im Viewer ansehen → exportieren, alles ohne Konsole.

### M4 — Registrierung & Fusion
1. `registration.py`: Port der merge_scans-Pipeline auf Open3D-Basis
   (FPFH+RANSAC grob, Multi-Scale-ICP fein, Pose-Graph bei >2 Scans)
2. `fusion.py`: distanzgewichtete Voxel-Fusion (STL27L-Fehlermodell aus v1)
3. UI: Registrieren-Knopf, Ergebnisanzeige (RMSE/Fitness je Paar,
   Ampel-Bewertung), Posen in project.json, fusionierte Wolke im Viewer
4. Einzelposen manuell verwerfen/wiederholen können

**Kriterium:** Zwei überlappende Referenz-Standpunkte automatisch
registriert, Fusion exportiert, Ergebnis in CloudCompare kontrolliert.

### M5 — Viewer-Werkzeuge
1. Distanzmessung (2 Punkte → Strecke, Anzeige im Viewer)
2. Clipping-Box/-Ebene (z.B. Horizontalschnitt für Grundriss)
3. Punkt-Info (Koordinaten, Intensität, Scanner-Distanz, Standpunkt)

### M6 — Pi-Transfer
1. `transfer.py`: SSH-Verbindung (Host/User/Key aus Einstellungen),
   Scan-Liste von `~/scans` mit Meta-Vorschau, Download mit Fortschritt
2. UI-Panel: Scans auswählen → direkt ins offene Projekt importieren

### M7 — Release-Fähigkeit
1. GitHub Actions: pytest auf Linux+Windows, PyInstaller-EXE als Release
2. EXE auf dem Auswerte-PC getestet (Open3D/pye57-DLLs!)
3. Doku DE/EN vollständig (Bedienung, Projektformat, Screenshots)

## Nicht in v1 (ROADMAP)

- **Georeferenzierung**: Standpunkt-Koordinaten (Landessystem) eingeben →
  Helmert-Transformation der Gesamtwolke; Export in Landeskoordinaten.
  (Vom User explizit für einen späteren Schritt gewünscht.)
- Kamera-/Foto-Integration + Metashape-Anbindung (kommt, sobald der
  Scanner die Fotorunde wieder hat; Metashape-Python-API darf genutzt werden)
- Mesh-Erzeugung (Poisson) aus der fusionierten Wolke

## Risiken / offene technische Punkte

| Risiko | Umgang |
|---|---|
| Open3D + PyInstaller auf Windows (DLL-Größe/Pfade) | früh in M1/CI testen, notfalls Registrierung als optionales Plugin-Paket |
| pye57 Windows-Wheels | in M1 verifizieren; Fallback: E57 zuletzt, PLY/LAS zuerst |
| Viewer-Performance bei 20 Mio.+ Punkten | Octree-LOD von Anfang an; Zielwert in M2 messen |
| el_offset unbekannt | Kalibrier-Workflow: ebene Referenzfläche scannen, Offset aus Bodenebene schätzen — Detaildesign in M1 |
| Pi aktuell offline | M1–M5 brauchen nur vorhandene Referenzdaten; M6 testet, wenn der Pi wieder da ist |

## Arbeitsweise

- Reihenfolge M1→M7, jeder Meilenstein endet mit nachgewiesenem Kriterium
- Tests ohne Hardware/GUI wo möglich (core), pytest-qt offscreen für UI-Logik
- docs/dev/STATUS.md nach jedem Arbeitstag fortschreiben
- Commits klein und thematisch, Push auf main
