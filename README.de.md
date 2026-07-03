# Scanorama Studio

*Deutsche Version — English version: [README.md](README.md)*

Desktop-Programm (Windows-first, Python + Qt), das die Rohdaten des
[scanorama](https://github.com/ferengi82/scanorama)-3D-LiDAR-Scanners
auswertet: Scan-Ordner importieren (von Platte oder per SSH vom
Raspberry Pi), Punktwolken berechnen und filtern, mehrere Standpunkte
registrieren und fusionieren, im eingebauten 3D-Viewer prüfen und
messen, Export nach E57 / PLY / LAS.

**Status:** Planung abgeschlossen, Umsetzung startet — siehe
[docs/dev/PLAN.md](docs/dev/PLAN.md) (Meilensteine M1–M7) und
[docs/dev/STATUS.md](docs/dev/STATUS.md).

## Geplante v1-Funktionen

- Roh-Scan-Ordner → gefilterte, bodenausgerichtete Punktwolke
  (Stativ-Bereich, Nahbereich, statistische Ausreißer;
  Elevations-Offset-Kalibrierung)
- Projekt-Konzept: ein Projekt = ein Aufmaß mit mehreren Standpunkten
- Automatische Registrierung (FPFH + RANSAC → Multi-Scale-ICP →
  Pose-Graph) und distanzgewichtete Fusion
- OpenGL-Punktwolken-Viewer: Einfärbung, Distanzmessung, Clipping,
  Punkt-Info
- Scan-Transfer vom Pi über SSH
- Exporte: E57, PLY, LAS/LAZ
- Oberfläche Deutsch und Englisch; Auslieferung als pip-Paket und
  Windows-EXE

## Lizenz

MIT — siehe [LICENSE](LICENSE).
