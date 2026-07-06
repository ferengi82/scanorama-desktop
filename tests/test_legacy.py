"""Tests: Reparatur veralteter Kamera-Mounts (refresh_stale_mounts)."""

from studio.core import legacy


def _meta():
    return {
        "config": {"motor": {"invert_dir": False}},
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


def test_refresh_stale_mounts():
    meta = _meta()          # veraltete Mounts (Roll=0)
    assert legacy.refresh_stale_mounts(meta) is True
    m = meta["cameras"]["mounts"]["usb0"]
    assert abs(m["roll_mount_deg"]) > 80    # Hochkant-Einbau
    assert m["device"] == "/dev/v4l/x"      # Gerätepfad bleibt erhalten
    # bereits kalibriert (Roll ±90) → unangetastet
    assert legacy.refresh_stale_mounts(meta) is False
