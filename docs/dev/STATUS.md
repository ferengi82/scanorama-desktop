# Arbeitsstand Scanorama Studio

## 2026-07-04 (abends) — v0.1.5: Strahlkalibrierung (Naht-Fehler gelöst)

- Ursache der Naht (erste/letzte Messung eines 180°-Scans weichen cm ab):
  der STL27L-Strahl liegt nicht exakt in der Rotorebene. Vier Winkel
  (el_offset, beam_skew, beam_wobble, halfplane_split) beschreiben es;
  Motor/Mechanik nachweislich exakt (Kamera-Null-Test 0,02°).
- `core/transform.py`: volles Strahlmodell (`LidarCalibration`,
  `beam_directions`); Pipeline nimmt Kalibrierung automatisch aus der
  meta.json des Scans (`resolve_calibration`, Schalter+Felder im Panel)
- Neu `core/calibrate.py` + CLI `calibrate <360°-Scan> [--write]`:
  Zwei-Lagen-Fit per Pattern-Search, Naht 38,8 → 2,9 mm (echte Scans,
  3× kreuzvalidiert)
- v0.1.4: Fusions-Voxel einstellbar (Panel, Default 1 cm), Versionsnummer
  im Release-ZIP-Namen

## 2026-07-04 — Windows-Debugging (v0.1.1–v0.1.3)

- v0.1.1: EXE-Startfix (editable Install für PyInstaller unsichtbar →
  pip install . + collect_submodules), Passwort-Feld im Pi-Dialog ✓
  (Transfer vom Windows-PC funktioniert), Desktop-GL erzwungen
- v0.1.2: Viewer-Diagnose (Hilfe-Menü), Qt-Meldungen im Protokoll,
  Software-GL-Schalter. Diagnose vom User-PC (RTX 4080, 150% Skalierung):
  GL 3.3 Desktop ok, 0x0502 anhängig, Testwürfel fehlerfrei gezeichnet
  aber 0 Pixel im Framebuffer
- v0.1.3: Fixes dafür — GL_SCISSOR_TEST vor jedem Frame aus, Viewport
  explizit in physischen Pixeln (HiDPI!), gl_PointSize >= 1 geklemmt,
  setUniformValue1f. Release-ZIPs heißen jetzt
  ScanoramaStudio-<tag>-windows.zip. **GELÖST: User bestätigt, Viewer läuft mit v0.1.3.**
- Falls weiter leer: nächste Verdächtige wären QMatrix4x4-Uniform-Upload
  (mvp per Hand via glUniformMatrix4fv prüfen) und Diagnose um
  Uniform-Readback/Program-Validate erweitern


> Wird laufend gepflegt. Neuester Eintrag oben.

## 2026-07-03 (spät) — v1 KOMPLETT: CI grün, EXE gebaut, Pi-Tests bestanden

- **CI grün auf Ubuntu + Windows**, Windows-EXE gebaut (Artefakt
  `ScanoramaStudio-windows`, ~134 MB). Für ein Release: Tag `v0.1.0`
  pushen → EXE hängt automatisch am GitHub-Release.
  (CI-Fixes: Mesa-DRI + volle Qt6-xcb-Bibliotheken auf dem Runner.)
- **Pi wieder online**: Scanner als `~/scanorama` deployt (21 Tests
  grün, Selftest ok), altes `~/pilidar` gelöscht.
- **Transfer gegen echtes Gerät**: Liste + Download 37.2 MB in 3.9 s
  (9.6 MB/s) mit Fortschritts-Callbacks.
- **Voller 180°-Scan durch die Studio-Pipeline**: 3.93 Mio → 2.72 Mio
  Punkte in 15 s, **Bodenfit erfolgreich** (Tischplatte korrekt
  verworfen). Befund: Bodenebene um **7.4° geneigt** → deutet auf
  el_offset der LiDAR-Montage hin! Mit `--el-offset` kompensierbar;
  Kalibrier-Assistent steht auf der v2-Roadmap.

**Noch offen:** EXE auf dem Windows-PC des Users starten/testen,
Viewer-Performance auf echter GPU, el_offset bestimmen.

## 2026-07-03 (abends) — v1 implementiert (M1–M7)

Alle Meilensteine an einem Tag umgesetzt, ~70 Tests grün. Highlights:
- Core-Pipeline auf echtem 30°-Scan validiert (223k Punkte → E57/PLY/LAS)
- Registrierung auf echten Mai-Standpunkten: Fitness 0.93, RMSE 10 mm
- Viewer offscreen (Xvfb+Mesa) gerendert und per Screenshot geprüft
- SSH-Transfer integrationsgetestet (localhost-sshd als Pi-Ersatz)
- 94 UI-Strings DE→EN übersetzt (en.qm), Sprachumschaltung getestet

**Offen / beim nächsten Mal:**
1. **Windows**: EXE per GitHub Actions bauen (workflow_dispatch) und auf
   dem Auswerte-PC testen (Open3D/pye57-DLLs!), Viewer-Performance mit
   4 Mio. Punkten auf echter GPU abnehmen
2. **Pi wieder online**: Transfer-Dialog gegen das echte Gerät testen;
   180°-Referenzscan durch Studio ziehen (Bodenfit prüfen!)
3. Der 30°-Testscan findet keinen Boden (Schreibtisch-Szene, alle
   Ebenen ~90° — korrekt so); Bodenfit am 180°-Scan validieren
4. v2-Themen: Georeferenzierung (Landessystem), el_offset-Assistent

## 2026-07-03 — Projektstart

- Repo `ferengi82/scanorama-desktop` angelegt (Scanner-Repo wurde am
  selben Tag zu `ferengi82/scanorama` umbenannt)
- Kickoff-Interview vollständig geführt → [DECISIONS.md](DECISIONS.md)
- Umsetzungsplan erstellt → [PLAN.md](PLAN.md), Meilensteine M1–M7
- Noch **kein Code** — nächster Schritt ist M1 (Repo-Gerüst +
  Core-Pipeline), nach Freigabe des Plans durch den User

**Kontext für die Fortsetzung:**
- Rohdatenformat: Scanner-Repo `docs/DATAFORMAT.de.md`
- Referenzdaten: `pi:~/scans-v2/2026-07-02_scan_01_003/` (180°, 3.9 Mio.
  Punkte) — Pi ist zeitweise offline, Kopie ggf. lokal ziehen sobald online
- Algorithmen-Vorlage: altes Projekt `/storage/projekte/LiDar/merge_scans.py`
  (Registrierung/Fusion) und `lidar_e57.py` (E57-Export)
