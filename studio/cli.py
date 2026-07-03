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
                   help="Elevations-Offset-Kalibrierung in Grad")
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

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
