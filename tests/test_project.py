"""Tests: Projekt anlegen/öffnen/speichern, Scans importieren."""

import numpy as np
import pytest

from studio.core.pipeline import ProcessingParams
from studio.core.project import Project, ProjectError


def test_create_and_reopen(tmp_path):
    p = Project.create(tmp_path / "aufmass", "Testaufmaß")
    assert (p.root / "project.json").exists()
    assert p.scans_dir.is_dir() and p.output_dir.is_dir()

    q = Project.open(p.root)
    assert q.name == "Testaufmaß"
    assert q.created == p.created
    assert q.stations == []


def test_create_refuses_nonempty(tmp_path):
    d = tmp_path / "voll"
    d.mkdir()
    (d / "datei.txt").write_text("x")
    with pytest.raises(ProjectError, match="nicht leer"):
        Project.create(d, "x")


def test_open_missing_raises(tmp_path):
    with pytest.raises(ProjectError, match="Kein Projekt"):
        Project.open(tmp_path)


def test_import_scan(tmp_path, mock_scan_dir):
    p = Project.create(tmp_path / "prj", "Import-Test")
    station = p.import_scan(mock_scan_dir)
    assert station.folder == mock_scan_dir.name
    assert (p.scans_dir / mock_scan_dir.name / "points.npz").exists()
    # Quelle unangetastet
    assert (mock_scan_dir / "points.npz").exists()

    # doppelt importieren → Fehler
    with pytest.raises(ProjectError, match="existiert bereits"):
        p.import_scan(mock_scan_dir)

    # Wiedereröffnen kennt den Standpunkt
    q = Project.open(p.root)
    assert [s.folder for s in q.stations] == [mock_scan_dir.name]


def test_import_rejects_non_scan(tmp_path):
    p = Project.create(tmp_path / "prj", "x")
    bogus = tmp_path / "keinscan"
    bogus.mkdir()
    with pytest.raises(ProjectError, match="Kein Scanorama-Scan"):
        p.import_scan(bogus)


def test_params_and_pose_persist(tmp_path, mock_scan_dir):
    p = Project.create(tmp_path / "prj", "Persist")
    p.params = ProcessingParams(el_offset_deg=2.5, align_floor=False)
    s = p.import_scan(mock_scan_dir)
    T = np.eye(4)
    T[:3, 3] = [1, 2, 3]
    s.set_pose(T)
    p.save()

    q = Project.open(p.root)
    assert q.params.el_offset_deg == 2.5
    assert q.params.align_floor is False
    np.testing.assert_allclose(q.stations[0].pose_matrix(), T)


def test_remove_station(tmp_path, mock_scan_dir):
    p = Project.create(tmp_path / "prj", "Remove")
    s = p.import_scan(mock_scan_dir)
    p.remove_station(s.folder, delete_files=True)
    assert p.stations == []
    assert not (p.scans_dir / s.folder).exists()
