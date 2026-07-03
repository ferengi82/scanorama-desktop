"""Integrationstest des SSH-Transfers gegen den lokalen sshd.

Simuliert den Pi mit einem temporären "Scans"-Ordner auf localhost.
Wird übersprungen, wenn kein SSH-Zugang auf 127.0.0.1 möglich ist
(z.B. in CI-Umgebungen ohne sshd).
"""

import getpass
import shutil
import socket
from pathlib import Path

import numpy as np
import pytest

from studio.core.transfer import PiTransfer, RemoteConfig, TransferError

paramiko = pytest.importorskip("paramiko")


def _localhost_config(scans_dir: str) -> RemoteConfig:
    return RemoteConfig(host="127.0.0.1", user=getpass.getuser(),
                        scans_dir=scans_dir)


@pytest.fixture(scope="module")
def local_ssh_available():
    try:
        with socket.create_connection(("127.0.0.1", 22), timeout=2):
            pass
    except OSError:
        pytest.skip("Kein sshd auf 127.0.0.1")
    t = PiTransfer(_localhost_config("."))
    try:
        t.connect()
    except TransferError:
        pytest.skip("SSH-Login auf 127.0.0.1 nicht möglich (kein Key)")
    finally:
        t.close()
    return True


@pytest.fixture
def fake_device_scans(tmp_path, mock_scan_dir):
    """Baut einen 'Geräte'-Scanordner mit einem echten Mock-Scan."""
    device = tmp_path / "device_scans"
    device.mkdir()
    shutil.copytree(mock_scan_dir, device / mock_scan_dir.name)
    # Unterordner mit Fotos (wie die Fotorunde des Scanners)
    photos = device / mock_scan_dir.name / "photos"
    photos.mkdir(exist_ok=True)
    (photos / "photo_00_az000_usb0.jpg").write_bytes(b"\xff\xd8fake\xff\xd9")
    # ein unvollständiger Scan (abgebrochen) + eine lose Datei
    broken = device / "2026-01-01_scan_99_001"
    broken.mkdir()
    (broken / "lidar_raw.bin").write_bytes(b"x" * 100)
    (device / "notiz.txt").write_text("keine Ordner")
    return device


def test_list_and_download(local_ssh_available, fake_device_scans,
                           tmp_path, mock_scan_dir):
    config = _localhost_config(str(fake_device_scans))
    with PiTransfer(config) as t:
        scans = t.list_scans()
        names = {s.name for s in scans}
        assert mock_scan_dir.name in names
        assert "2026-01-01_scan_99_001" in names
        assert "notiz.txt" not in names

        by_name = {s.name: s for s in scans}
        assert by_name[mock_scan_dir.name].complete
        assert not by_name["2026-01-01_scan_99_001"].complete
        assert by_name[mock_scan_dir.name].size_mb > 0.1

        # Download mit Fortschritts-Callback
        seen = []
        target = t.download(mock_scan_dir.name, tmp_path / "geholt",
                            progress=lambda done, total: seen.append((done, total)))
        assert target.is_dir()
        assert seen and seen[-1][0] == seen[-1][1]   # 100 % erreicht

        # Bytes identisch mit der Quelle
        src = (mock_scan_dir / "lidar_raw.bin").read_bytes()
        dst = (target / "lidar_raw.bin").read_bytes()
        assert src == dst

        # Unterordner (photos/) wurde rekursiv mitgeholt
        assert (target / "photos" / "photo_00_az000_usb0.jpg").is_file()

        # doppelter Download → Fehler statt Überschreiben
        with pytest.raises(TransferError, match="existiert bereits"):
            t.download(mock_scan_dir.name, tmp_path / "geholt")


def test_missing_dir_raises(local_ssh_available, tmp_path):
    config = _localhost_config(str(tmp_path / "gibtsnicht"))
    with PiTransfer(config) as t:
        with pytest.raises(TransferError, match="fehlt"):
            t.list_scans()


def test_connect_failure():
    config = RemoteConfig(host="127.0.0.1", user="definitiv_kein_user_xyz")
    with pytest.raises(TransferError, match="fehlgeschlagen"):
        PiTransfer(config).connect()
