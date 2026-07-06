# Arbeitsstand Scanorama Studio

## 2026-07-06 — Alt-Scan-Entspiegelung zurückgenommen (war falschherum)

- User-Befund: Raum-Scans gespiegelt (Bett auf falscher Raumseite). Ursache
  war die am 2026-07-05 eingeführte Azimut-„Entspiegelung" (`unmirror_legacy`,
  Default an) — sie negierte bei **jedem** `invert_dir=false`-Scan den Azimut.
  Da sämtliche echten Daten `invert_dir=false` sind, spiegelte der Default
  faktisch jede Wolke. Die damalige Foto-/Metashape-Begründung trug nicht:
  Drehrichtung betrifft nur die Koordinaten, und Spiegel+Spiegel ist in sich
  konsistent (der Raum-Augenschein ist die härtere Grundwahrheit).
- **Entfernt:** `legacy.is_mirrored`/`unmirror_meta`, Pipeline-Param
  `unmirror_legacy`, `report["legacy_mirrored"]` sowie die Aufrufe in
  mainwindow.py/photo_overlay.py. `legacy.refresh_stale_mounts` (Mount-
  Reparatur für die Einfärbung) bleibt unverändert. `invert_dir=false`-Scans
  werden wieder in der ursprünglichen, korrekten Konvention (pre-v0.1.6)
  ausgewertet.
- Verifiziert: `2026-07-03_scan_01_001` — X-Achse der Pipeline jetzt
  vorzeichengleich mit der rohen `polar_to_cartesian`-Umrechnung (nicht mehr
  gespiegelt). 110 Tests grün. **Achtung:** unter der gespiegelten Version
  gerechnete Projekt-Posen einmal neu registrieren (Strg+R).

## 2026-07-05 (nachmittags) — Metashape-Winkelfix + Foto-Overlay-Prüfer

- User-Befund nach v0.1.6: Fotos 90° verdreht, Metashape-Wolke kippt.
  Drei Ursachen behoben:
  1. **Metashape-Export → Omega/Phi/Kappa** statt Yaw/Pitch/Roll (die
     YPR-Konvention war mit Roll±90 nie validiert). OPK-Konvention
     datengetrieben aus 108 (Winkel,Matrix)-Paaren der User-cameras.txt:
     R_file = (Rx(ω)Ry(φ)Rz(κ))ᵀ, MS-Kameraachsen via Q=[[-1,0,0],[0,0,1],
     [0,1,0]] (matrix_to_opk in photos.py, 108/108 exakt).
     WICHTIG in Metashape: Reference-Settings → Rotation „Omega Phi Kappa".
  2. **Fotos werden beim Export aufrecht gedreht** (Hochkant-Einbau),
     Drehung in Pose eingefaltet (Roll≈0), Portrait-Kalibrierung je
     Kamera (calibration_usbN.xml), Pixel-Konsistenz numerisch bewiesen.
  3. **Veraltete Mounts in meta.json** (Scans vor der cameras.json-
     Installation, alle roll=0) werden in der Pipeline automatisch durch
     die aktuellen Gerätewerte ersetzt (legacy.refresh_stale_mounts) —
     das war die „90°-Verdrehung" in der Studio-Einfärbung des Users.
- **Neues Werkzeug Foto-Overlay-Prüfer** (Menü Fotos): Foto ⇄ Wolken-
  Render überblendet, Live-Regler az/pitch/roll, Auto-Fit (1/alle Fotos),
  Übernehmen als project.camera_mounts-Override, cameras.json-Export
  für den Pi. Core: studio/core/overlay.py.
- 103 Tests grün; Export am Referenzscan regeneriert (108 OPK-Zeilen,
  Portrait-JPEGs). Release v0.1.7 nach User-Test.

## 2026-07-05 (mittags) — Alt-Scan-Entspiegelung

- `core/legacy.py` + Pipeline-Schalter `unmirror_legacy` (Default an):
  Scans mit invert_dir=false werden beim Verarbeiten automatisch
  entspiegelt — Azimut negiert, Strahlkalibrierungs-Vorzeichen aus der
  Alt-meta.json gespiegelt, Foto-Azimute negiert, veraltete Mounts
  durch die aktuellen Gerätewerte ersetzt (scanorama-Paket).
  Metashape-Export nutzt denselben Pfad. Report-Flag `legacy_mirrored`.
- Validiert am echten Alt-Scan 2026-07-04_scan_05_001: entspiegelt +
  78,5 % eingefärbt, Panorama sauber. Achtung: bestehende Projekt-Posen
  von Alt-Scans wurden auf gespiegelten Wolken gerechnet → nach dem
  Update einmal neu registrieren (Strg+R).

## 2026-07-05 — Kamera-Mounts GELÖST + gemessene Intrinsics

- Rätsel der „falschen" Mounts aufgeklärt: Module hochkant (roll ±90°),
  andere Pitches als v1 — bestimmt aus Metashape-Rotationen (108 Fotos)
  + Azimut-Fit gegen die Wolke. Werte leben im Scanner-Repo
  (CALIBRATED_MOUNTS + cameras.json auf dem Pi); Studio-Code unverändert
  korrekt (yaw=az+az_offset — Achtung: eigene Test-Harnesse mit
  Spiegel-Konventionen führten hier zweimal in die Irre; der Produktpfad
  colorize_cloud war der verlässliche Test).
- `photos.py`: FOCAL_PX=2548.876, CX/CY-Hauptpunkt aus Metashape-
  Selbstkalibrierung (ersetzt 3,5-mm-Annahme); calibration.xml-Export
  trägt die gemessenen Werte.
- Nebenbei entdeckt (Scanner-Repo `8a2f79f`): Scans vor invert_dir=true
  waren spiegelverkehrt zur Realität. Alt-Scans ggf. im Studio spiegeln
  (offener Punkt).
- Verifiziert: colorize auf 2026-07-05_scan_01_001 → 77,7 % Punkte,
  Panorama sauber. Naht mit gespiegelter Strahlkalibrierung 3,7 mm.

## 2026-07-04 (nachts) — Fotoverarbeitung: Metashape-Export + Einfärbung

- `core/photos.py`: Fotoposen aus meta.json (POSE_RECIPE), Kompass-Yaw-
  Euler (R = R_z(−yaw)·R_x(pitch)·R_y(roll) — v1 hatte beim Kombinieren
  registrierter Standpunkte das Yaw-Vorzeichen falsch), Metashape-Export
  (Foto-Kopien mit eindeutigen Labels + cameras.csv + calibration.xml +
  ANLEITUNG.md) → Menü „Fotos", output/metashape/
- `core/colorize.py`: RGB pro Punkt aus bestem Foto (Pinhole f=2500 px,
  Z-Buffer-Occlusion /16-Raster); Pipeline-Schalter `colorize_photos`
  (Default an), `PointCloud.rgb` durch Fusion/PLY/LAS(pf2)/E57/Viewer
  („Foto-Farben", neuer Default mit Grau-Fallback). Neue Dependency
  pillow. 93 Tests grün, End-to-End an 2 echten Standpunkten validiert
  (Registrierung Fitness 0.87/9 mm, 216 Fotos exportiert, 72 % Punkte
  eingefärbt in ~40 s).
- **OFFEN: Kamera-Mount-Werte stimmen nicht mehr** — die v1-Werte
  (az_offset 270/35/145, pitch +50/+15/−20) passen nachweislich nicht
  zum aktuellen Aufbau (Reprojektion zeigt andere Szene als Foto,
  Einfärbung ghostet). Automatische Bestimmung per Wolke↔Foto-
  Gradientenkorrelation versucht (Scratchpad mount_calib.py): beste
  Kandidaten usb0 172°/+53°, usb1 278°/−17°, usb2 86°/+28° — aber bei
  den dunklen Fotos nicht verlässlich (Einzelfoto-Scores ≈ Rauschen;
  evtl. stand zudem eine Person im Raum). Nächster Schritt: User nach
  physischer Anordnung fragen bzw. helle Referenz-Fotorunde machen,
  dann cameras.json auf dem Pi aktualisieren. Der Feature-Code selbst
  ist davon unabhängig korrekt.

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
