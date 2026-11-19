"""C1: identifiers from project files and routes stay inside their store folders, at every entry point."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from apps.api.safe_paths import InvalidStorePath
from apps.api.weather_store import FileWeatherRevisionStore
from tests.unit.test_rb_data1_project_files import remanifest, rewrite
from tests.unit.test_rb_fix_s2_honest_preflight import Project, ROOT

WEATHER_FIXTURE = ROOT / "tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json"
_OPENED: list[str] | None = None


def _record_opens(event, args):
    if _OPENED is not None and event == "open" and args and isinstance(args[0], (str, bytes, Path)):
        _OPENED.append(str(args[0]))


sys.addaudithook(_record_opens)


@contextmanager
def file_opens():
    """Collect every file opened in the block (Python's audit hook)."""
    global _OPENED
    _OPENED = []
    try:
        yield _OPENED
    finally:
        _OPENED = None


@pytest.fixture
def two_projects(tmp_path):
    """A project with weather (the 'existing' one) and a second project whose archive is edited."""
    existing = Project(tmp_path, 18)
    study = existing.study
    selection = existing.bundle()["weather_selection"]
    sentinel = study.weather.root / existing.pid / selection["revision_id"] / "weather-dataset.json"
    second = existing.service.create_project(name="C1 second", latitude_deg=-6.2, longitude_deg=106.8,
                                             timezone_name="Asia/Jakarta", elevation_m=25)
    second_id = second["project"]["project_id"]
    study.acquire_weather(second_id, source_id="open_meteo_archive_era5", start_date="2025-01-01",
                          end_date="2025-01-01", raw_response=WEATHER_FIXTURE.read_bytes())
    return existing, selection, sentinel, second_id


def _no_leak(response, *values):
    body = response.text
    assert "Traceback" not in body
    for value in values:
        assert value not in body


@pytest.mark.parametrize("bad", ["../{other}/{rev}", "..", "a/b", "/abs", "C:\\x", "x\n", "．．／x"])
def test_import_rejects_a_malformed_weather_revision_and_reads_nothing_outside(two_projects, bad):
    existing, selection, sentinel, second_id = two_projects
    bad = bad.format(other=existing.pid, rev=selection["revision_id"])
    before = sentinel.read_bytes()
    archive = existing.client.get(f"/api/projects/{second_id}/export", params={"include_results": False})
    assert archive.status_code == 200

    def change(members):
        bundle = json.loads(members["project.json"])
        bundle["weather_selection"] = deepcopy(selection)
        bundle["weather_selection"]["revision_id"] = bad
        bundle["project"]["project_revision"]["weather_dataset_revision_id"] = bad
        members["project.json"] = json.dumps(bundle).encode()
        remanifest(members)

    with file_opens() as opened:
        response = existing.client.post("/api/projects/import", params={"replace": True},
                                        content=rewrite(archive.content, change))
    # Refused either as an invalid archive (422) or as an unreadable project file (409 project_unreadable).
    assert response.status_code in {409, 422}, response.text
    _no_leak(response, bad, str(sentinel.parent))
    assert sentinel.read_bytes() == before
    assert str(sentinel) not in opened


@pytest.mark.parametrize("bad", ["../x", "a/b", "..", "x\n"])
def test_weather_store_rejects_malformed_ids_before_touching_the_disk(tmp_path, bad):
    store = FileWeatherRevisionStore(tmp_path / "weather")
    (tmp_path / "x").mkdir()
    with file_opens() as opened:
        for call in (lambda: store.load("project-0123456789", bad), lambda: store.manifest("project-0123456789", bad),
                     lambda: store.load(bad, "wx-ref-001-r1")):
            with pytest.raises((InvalidStorePath, ValueError)):
                call()
    assert not any(str(tmp_path / "x") in path for path in opened)


def test_hand_placed_project_file_with_a_malformed_weather_revision_is_reported_unreadable(two_projects):
    existing, selection, sentinel, _ = two_projects
    path = existing.service.store.path_for(existing.pid)
    bundle = json.loads(path.read_text(encoding="utf-8"))
    bundle["weather_selection"]["revision_id"] = f"../{existing.pid}/{selection['revision_id']}"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    with file_opens() as opened:
        response = existing.client.get(existing.url)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "project_unreadable"
    _no_leak(response, "../")
    assert str(sentinel) not in opened


@pytest.mark.parametrize("backup_id", ["not-a-backup", "..", "a.b", "20261117T1234Z-r1"])
def test_restore_of_a_malformed_backup_id_is_not_found(two_projects, backup_id):
    existing = two_projects[0]
    response = existing.client.post(f"{existing.url}/backups/{backup_id}/restore")
    # 405: the HTTP client normalises "/backups/../restore" to another URL, so it never reaches restore at all.
    assert response.status_code in {404, 405}, response.text
    _no_leak(response, str(existing.service.store.root))


@pytest.mark.parametrize("route", ["result", "annual-pxx", "timeseries", "report-snapshot",
                                   "exports/free-csv", "exports/schema"])
@pytest.mark.parametrize("run_id", ["..", "a.b..c%00", "run with space", "%2e%2e"])
def test_run_routes_refuse_malformed_run_ids_without_a_server_error(two_projects, route, run_id):
    existing = two_projects[0]
    with file_opens() as opened:
        response = existing.client.get(f"{existing.url}/runs/{run_id}/{route}")
    assert response.status_code in {404, 422}, (route, run_id, response.status_code, response.text)
    _no_leak(response, str(existing.study.run_root))
    run_root = str(existing.study.run_root.resolve())
    assert not any(path.startswith(run_root) and existing.pid not in path for path in opened)


def test_existing_projects_keep_their_identifiers_and_round_trip(two_projects):
    """Compatibility: a normally created project exports and imports back unchanged under the new rules."""
    existing = two_projects[0]
    before = existing.bundle()
    archive = existing.client.get(f"{existing.url}/export", params={"include_results": True})
    assert archive.status_code == 200
    response = existing.client.post("/api/projects/import", params={"replace": True}, content=archive.content)
    assert response.status_code == 200, response.text
    after = existing.bundle()
    assert after["weather_selection"]["revision_id"] == before["weather_selection"]["revision_id"]
    assert after["project"]["project_id"] == before["project"]["project_id"]
