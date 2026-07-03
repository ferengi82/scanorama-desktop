"""Gemeinsame Fixtures.

``mock_scan_dir`` erzeugt einmal pro Testlauf einen kompletten
Scan-Ordner über den Mock-Modus des Scanner-Pakets (kein Gerät nötig).
``real_scan_dir`` nutzt den echten 30°-Scan in testdata/ (nicht im Repo;
Tests werden übersprungen, wenn er fehlt).
"""

from pathlib import Path

import pytest

TESTDATA = Path(__file__).parent.parent / "testdata"


@pytest.fixture(scope="session")
def mock_scan_dir(tmp_path_factory) -> Path:
    """Kompletter Scan-Ordner aus dem Scanner-Mock (30° Stream)."""
    from scanorama.config import Config
    from scanorama.scan.recorder import run_scan

    cfg = Config()
    cfg.motor.driver = "mock"
    cfg.lidar.startup_wait_s = 0.0
    cfg.scan.mode = "stream"
    cfg.scan.az_start_deg = 0.0
    cfg.scan.az_end_deg = 30.0
    cfg.scan.stream_speed_deg_s = 5.0
    cfg.output_dir = str(tmp_path_factory.mktemp("mockscans"))
    return run_scan(cfg, use_mock_lidar=True)


@pytest.fixture(scope="session")
def real_scan_dir() -> Path:
    """Echter 30°-Scan vom Gerät (liegt lokal in testdata/, nicht im Git)."""
    candidates = sorted(TESTDATA.glob("*_scan_*")) if TESTDATA.exists() else []
    if not candidates:
        pytest.skip("Kein echter Scan in testdata/ vorhanden")
    return candidates[0]
