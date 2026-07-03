"""Tests: komplette Pipeline (Mock-Scan + echter Scan) und CLI."""

import numpy as np
import pytest

from studio.cli import main as cli_main
from studio.core.filters import FilterParams
from studio.core.pipeline import ProcessingParams, process_scan


def test_pipeline_mock_scan(mock_scan_dir):
    # Mock-Szene ist rotationssymmetrisch (kein planarer Boden) →
    # Bodenausrichtung aus, Rest mit Defaults.
    params = ProcessingParams(align_floor=False)
    result = process_scan(mock_scan_dir, params)
    assert len(result.cloud) > 10000
    assert result.report["raw_filter"]["removed_tripod"] > 0
    assert result.report["points"] == len(result.cloud)
    # Mock-Distanzen: 1.5–2.5 m → alle Punkte in dieser Kugel
    r = np.linalg.norm(result.cloud.xyz.astype(np.float64), axis=1)
    assert r.min() > 1.4 and r.max() < 2.6


def test_pipeline_params_roundtrip():
    p = ProcessingParams(el_offset_deg=1.5,
                         filters=FilterParams(min_dist_m=0.5),
                         align_floor=False)
    q = ProcessingParams.from_dict(p.to_dict())
    assert q.el_offset_deg == 1.5
    assert q.filters.min_dist_m == 0.5
    assert q.align_floor is False


def test_pipeline_real_scan(real_scan_dir):
    """Integration: echter 30°-Scan vom Gerät mit v1-Default-Filtern."""
    result = process_scan(real_scan_dir, ProcessingParams())
    assert len(result.cloud) > 100000
    # Nahbereichsfilter: kein Punkt näher als 30 cm
    assert result.cloud.scanner_dist.min() >= 0.30
    # Stativ-Bereich entfernt
    assert result.report["raw_filter"]["removed_tripod"] > 0
    if result.floor_transform is not None:
        z = result.cloud.xyz[:, 2]
        # Boden liegt bei z≈0 → praktisch nichts deutlich darunter
        assert np.percentile(z, 1) > -0.15


def test_cli_process(mock_scan_dir, tmp_path, capsys):
    rc = cli_main([
        "process", str(mock_scan_dir),
        "--out", str(tmp_path),
        "--formats", "ply", "e57",
        "--no-floor",
    ])
    assert rc == 0
    out_files = list(tmp_path.rglob("*"))
    suffixes = {p.suffix for p in out_files if p.is_file()}
    assert {".ply", ".e57"} <= suffixes
