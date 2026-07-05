"""Tests: Entspiegelung von Alt-Scans (invert_dir=false)."""

import numpy as np

from studio.core import legacy


def _meta(invert_dir):
    return {
        "config": {"motor": {"invert_dir": invert_dir}},
        "calibration": {"el_offset_deg": 0.263, "beam_skew_deg": -0.413,
                        "beam_wobble_deg": -0.863,
                        "halfplane_split_deg": 1.425, "model": "…"},
        "photos": [{"file": "photos/p.jpg", "cam_id": "usb0",
                    "azimuth_deg": 190.0, "t_ns": 0}],
        "cameras": {"mounts": {"usb0": {
            "r_cam_m": 0.032, "z_cam_m": -0.012, "az_offset_deg": 270.0,
            "yaw_mount_deg": 0.0, "pitch_mount_deg": 50.0,
            "roll_mount_deg": 0.0, "device": "/dev/v4l/x"}}},
    }


def test_erkennung():
    assert legacy.is_mirrored(_meta(False))
    assert not legacy.is_mirrored(_meta(True))
    assert not legacy.is_mirrored({})            # kein config-Block


def test_unmirror_meta():
    meta = _meta(False)
    out = legacy.unmirror_meta(meta)
    # Kalibrier-Vorzeichen gespiegelt, el_offset unverändert
    assert out["calibration"]["beam_skew_deg"] == 0.413
    assert out["calibration"]["halfplane_split_deg"] == -1.425
    assert out["calibration"]["el_offset_deg"] == 0.263
    # Foto-Azimut negiert
    assert out["photos"][0]["azimuth_deg"] == -190.0
    # Mounts durch aktuelle Gerätewerte ersetzt (scanorama-Paket),
    # Gerätepfad bleibt erhalten
    m = out["cameras"]["mounts"]["usb0"]
    assert m["az_offset_deg"] != 270.0
    assert abs(m["roll_mount_deg"]) > 80         # Hochkant-Einbau
    assert m["device"] == "/dev/v4l/x"
    # Original unangetastet
    assert meta["calibration"]["beam_skew_deg"] == -0.413


def test_pipeline_entspiegelt(tmp_path, monkeypatch):
    import json

    from studio.core.pipeline import ProcessingParams, process_scan

    scan = tmp_path / "alt_scan"
    scan.mkdir()
    n = 2000
    az = np.linspace(0, 180, n).astype(np.float32)
    np.savez_compressed(
        scan / "points.npz",
        elevation_deg=np.full(n, 90.0, np.float32),
        azimuth_deg=az,
        distance_mm=np.full(n, 2000, np.uint16),
        intensity=np.full(n, 100, np.uint8),
        t_ns=np.zeros(n, np.int64))
    (scan / "meta.json").write_text(json.dumps(_meta(False)),
                                    encoding="utf-8")

    params = ProcessingParams(align_floor=False, colorize_photos=False)
    params.filters.sor_enabled = False
    params.filters.min_dist_m = 0.0
    params.filters.block_start_deg = 0.0
    params.filters.block_end_deg = 0.0
    result = process_scan(scan)
    # Default-Params entspiegeln: report-Flag + X-Verlauf gespiegelt
    assert result.report["legacy_mirrored"] is True

    params.unmirror_legacy = False
    result2 = process_scan(scan, params)
    assert result2.report["legacy_mirrored"] is False
    # x = h·sin(az): entspiegelt (−az) hat negierte x-Werte
    x1 = result.cloud.xyz[:, 0]
    x2 = result2.cloud.xyz[:, 0]
    assert np.mean(x1) < 0 < np.mean(x2)


def test_refresh_stale_mounts():
    meta = _meta(True)      # neue Richtung, aber Roll=0 (veraltet)
    assert legacy.refresh_stale_mounts(meta) is True
    m = meta["cameras"]["mounts"]["usb0"]
    assert abs(m["roll_mount_deg"]) > 80
    assert m["device"] == "/dev/v4l/x"
    # bereits kalibriert (Roll ±90) → unangetastet
    assert legacy.refresh_stale_mounts(meta) is False
