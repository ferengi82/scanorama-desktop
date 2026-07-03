# Arbeitsstand Scanorama Studio

> Wird laufend gepflegt. Neuester Eintrag oben.

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
