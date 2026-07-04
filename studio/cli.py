"""Headless-Batchverarbeitung ohne GUI.

Beispiele:
    scanorama-studio-cli process ~/scans/2026-07-02_scan_01_003 \\
        --out ./ausgabe --formats e57 ply

    scanorama-studio-cli process scans/* --no-floor --min-dist 0
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .core import export
from .core.filters import FilterParams
from .core.pipeline import ProcessingParams, process_scan

log = logging.getLogger("studio")


def cmd_process(args: argparse.Namespace) -> int:
    params = ProcessingParams(
        el_offset_deg=args.el_offset,
        beam_skew_deg=args.beam_skew,
        beam_wobble_deg=args.beam_wobble,
        halfplane_split_deg=args.halfplane_split,
        calib_from_meta=not args.no_meta_calib,
        filters=FilterParams(
            block_start_deg=args.block_start,
            block_end_deg=args.block_end,
            min_dist_m=args.min_dist,
            sor_enabled=not args.no_sor,
        ),
        align_floor=not args.no_floor,
    )
    out_dir = Path(args.out)
    rc = 0
    for scan_dir in args.scan_dirs:
        p = Path(scan_dir)
        try:
            result = process_scan(p, params, force_decode=args.force_decode)
        except Exception as e:
            log.error(f"{p}: Verarbeitung fehlgeschlagen: {e}")
            rc = 1
            continue
        written = export.export_cloud(result.cloud, out_dir / p.name,
                                      args.formats)
        for w in written:
            print(w)
    return rc


def cmd_calibrate(args: argparse.Namespace) -> int:
    import json
    from datetime import date

    from .core.calibrate import CalibrationError, fit_calibration

    try:
        result = fit_calibration(args.scan_dir, subsample=args.subsample)
    except CalibrationError as e:
        log.error(str(e))
        return 1
    c = result.calibration
    print(f"Naht (median |Δr|): {result.seam_before_mm:.1f} mm → "
          f"{result.seam_after_mm:.1f} mm  "
          f"({result.bins} Bins, {result.evaluations} Auswertungen)")
    payload = {**c.to_dict(),
               "fitted": date.today().isoformat(),
               "source": Path(args.scan_dir).name,
               "seam_before_mm": round(result.seam_before_mm, 1),
               "seam_after_mm": round(result.seam_after_mm, 1)}
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    print(text)
    if args.write:
        out = Path(args.write)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"→ {out}")
        print("Auf dem Pi ablegen als ~/.config/scanorama/calibration.json — "
              "dann trägt der Scanner die Werte in jede meta.json ein.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scanorama-studio-cli",
        description="Scanorama Studio — Headless-Verarbeitung von Scan-Ordnern "
                    "(Rohdaten → gefilterte Punktwolke → PLY/LAS/E57)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version",
                        version=f"scanorama-studio {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("process", help="Scan-Ordner verarbeiten und exportieren",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("scan_dirs", nargs="+", metavar="SCAN_ORDNER",
                   help="Ein oder mehrere Scan-Ordner des Scanners")
    p.add_argument("--out", default="./output",
                   help="Ausgabeverzeichnis")
    p.add_argument("--formats", nargs="+", default=["e57", "ply"],
                   choices=list(export.FORMATS),
                   help="Exportformate")
    g = p.add_argument_group("Verarbeitung")
    g.add_argument("--el-offset", type=float, default=0.0,
                   help="Elevations-Offset in Grad (wenn keine "
                        "Kalibrierung in der meta.json)")
    g.add_argument("--beam-skew", type=float, default=0.0,
                   help="Strahl-Skew in Grad (siehe calibrate)")
    g.add_argument("--beam-wobble", type=float, default=0.0,
                   help="Strahl-Wobble in Grad (siehe calibrate)")
    g.add_argument("--halfplane-split", type=float, default=0.0,
                   help="Halbebenen-Versatz in Grad (siehe calibrate)")
    g.add_argument("--no-meta-calib", action="store_true",
                   help="Kalibrierung aus der meta.json ignorieren")
    g.add_argument("--block-start", type=float, default=165.0,
                   help="Stativ-Bereich Anfang (Elevation, 0°=oben)")
    g.add_argument("--block-end", type=float, default=195.0,
                   help="Stativ-Bereich Ende (0/0 = deaktiviert)")
    g.add_argument("--min-dist", type=float, default=0.30,
                   help="Nahbereichsfilter in Metern (0 = aus)")
    g.add_argument("--no-sor", action="store_true",
                   help="Statistischen Ausreißerfilter deaktivieren")
    g.add_argument("--no-floor", action="store_true",
                   help="Bodenausrichtung (Z=0) deaktivieren")
    p.add_argument("--force-decode", action="store_true",
                   help="points.npz aus den Rohdaten neu berechnen")
    p.set_defaults(func=cmd_process)

    p = sub.add_parser(
        "calibrate",
        help="Strahlkalibrierung aus einem 360°-Scan bestimmen "
             "(Zwei-Lagen-Analyse)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("scan_dir", metavar="SCAN_ORDNER",
                   help="Ein voller 360°-Scan (scanorama scan --az-end 360)")
    p.add_argument("--write", metavar="DATEI",
                   help="Ergebnis als calibration.json schreiben "
                        "(für ~/.config/scanorama/ auf dem Pi)")
    p.add_argument("--subsample", type=int, default=3,
                   help="Nur jeden n-ten Punkt verwenden (Tempo)")
    p.set_defaults(func=cmd_calibrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
