# Scanorama Studio

*Deutsche Version — English version: [README.md](README.md)*

Desktop-Programm (Windows-first, Python + Qt), das die Rohdaten des
[scanorama](https://github.com/ferengi82/scanorama)-3D-LiDAR-Scanners
auswertet: Scan-Ordner importieren (von Platte oder per SSH vom
Raspberry Pi), Punktwolken berechnen und filtern, mehrere Standpunkte
registrieren und fusionieren, im eingebauten 3D-Viewer prüfen und
messen, Export nach E57 / PLY / LAS.

![Scanorama Studio](docs/img/studio.png)

## Funktionen (v1)

- **Projekte**: ein Projekt = ein Aufmaß; Standpunkte, Einstellungen,
  Posen und Ergebnisse liegen im Projektordner (`project.json`),
  vollständig reproduzierbar
- **Verarbeitungs-Pipeline**: Roh-Scan → Stativ-/Nahbereichsfilter →
  Polar→Kartesisch (mit Elevations-Offset-Kalibrierung) → statistischer
  Ausreißerfilter → automatische Bodenausrichtung (Z=0)
- **3D-Viewer** (OpenGL): Millionen Punkte, LOD beim Navigieren,
  Einfärbung nach Intensität / Höhe / Standpunkt
- **Werkzeuge**: Distanzmessung (3D/horizontal/Höhendifferenz),
  Clipping-Box (Grundriss-Schnitte), Punkt-Info
- **Registrierung & Fusion**: FPFH+RANSAC → Multi-Scale-ICP →
  Pose-Graph, distanzgewichtete Voxel-Fusion (STL27L-Fehlermodell),
  Qualitäts-Ampel pro Paar
- **Exporte**: E57 (einzeln oder mehrere Stationen mit Posen —
  Metashape importiert sie fertig registriert), PLY, LAS/LAZ
- **Geräte-Transfer**: Scans per SSH vom Pi auflisten und holen
- Oberfläche Deutsch und Englisch (Einstellungen → Sprache)

## Installation

**Windows (empfohlen):** `ScanoramaStudio-windows.zip` aus den
[Releases](https://github.com/ferengi82/scanorama-desktop/releases)
laden, entpacken, `ScanoramaStudio.exe` starten.

**Aus dem Quellcode (Windows/Linux):**

```bash
git clone https://github.com/ferengi82/scanorama-desktop.git
cd scanorama-desktop
python -m venv venv
./venv/bin/pip install -e .          # Windows: venv\Scripts\pip install -e .
./venv/bin/scanorama-studio          # GUI
```

## Typischer Ablauf

1. **Projekt → Neues Projekt…** — Ordner für das Aufmaß wählen
2. **Projekt → Scans importieren…** (USB-Stick/Ordner) oder
   **Scans vom Gerät holen…** (SSH vom Pi)
3. Standpunkt anklicken → wird verarbeitet und angezeigt; Parameter im
   *Verarbeitung*-Panel anpassen und *Neu verarbeiten*
4. **Registrierung → Standpunkte registrieren & fusionieren** (Strg+R) —
   Posen werden berechnet und gespeichert, die Gesamtwolke erscheint
   nach Standpunkten eingefärbt
5. Export: Gesamtwolke (E57/PLY/LAS) oder *Alle Standpunkte als E57
   mit Posen* für Metashape

## Batchverarbeitung ohne GUI

```bash
scanorama-studio-cli process ~/scans/2026-07-02_scan_01_003 \
    --out ./output --formats e57 ply las
```

## Repository-Struktur

```
studio/core/        Verarbeitung (ohne Qt): rawscan, transform, filters,
                    floor, registration, fusion, export, project, transfer
studio/ui/          PySide6: Hauptfenster, Panels, Werkzeuge, GL-Viewer, i18n
studio/cli.py       Headless-Batch-Pipeline
tests/              pytest (~70 Tests, ohne Hardware lauffähig)
scanorama-studio.spec  PyInstaller-Build (Windows-EXE via GitHub Actions)
docs/dev/           Entscheidungen, Plan, Roadmap, Status (Arbeitsstand)
```

Das Rohdatenformat ist genau einmal definiert — im
[Scanner-Repository](https://github.com/ferengi82/scanorama/blob/main/docs/DATAFORMAT.de.md);
Studio nutzt das Scanner-Paket als Dependency zum Dekodieren.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
