"""S6 acceptance: project/site edits, concurrency, deletion and API bounds."""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from threading import Event
import json

from fastapi.testclient import TestClient

import apps.api.study as study_module
from tests.unit.test_rb_fix_s2_honest_preflight import Project
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
import shutil

import pytest
import weather.providers.open_meteo as provider_module
from tests.unit.test_rb_fix_s2_honest_preflight import ROOT, MODULE
from tests.unit.test_rb_fix_s1_geometry_integrity import Project as GeometryProject
from apps.api.project_store import ProjectNotFoundError


def test_07_surface_added_during_run_is_not_lost(tmp_path, monkeypatch):
    project = Project(tmp_path)
    entered, release = Event(), Event()
    original = study_module.run_validated_design_simulation
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(30), "test did not release simulation"
        return original(*args, **kwargs)
    monkeypatch.setattr(study_module, "run_validated_design_simulation", paused)
    old_scene_revision = project.bundle()["scene"]["revision_id"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(project.client.post, project.url + "/simulate", json={})
        try:
            assert entered.wait(30), "simulation did not enter engine"
            response = project.client.post(project.url + "/surfaces/rectangle", json={
                "origin_x_m": 100, "width_m": 5, "height_m": 5, "name": "Concurrent edit",
            })
            assert response.status_code == 200, response.text
            assert len(project.bundle()["scene"]["surfaces"]) == 2
        finally:
            release.set()
        result = future.result(timeout=30)
    assert result.status_code == 200, result.text
    bundle = project.bundle()
    assert len(bundle["scene"]["surfaces"]) == 2
    assert bundle["simulation_runs"][-1]["scene_revision_id"] == old_scene_revision
    assert bundle["simulation_runs"][-1]["simulation_run_id"] == result.json()["simulation_run_id"]


def test_10_nonfinite_validation_is_422_with_existing_list_shape(tmp_path):
    project = Project(tmp_path, weather=False, strings=False)
    client = TestClient(project.app, raise_server_exceptions=False)
    before = project.path.read_bytes()
    response = client.post(project.url + "/obstacles/box", content=json.dumps({
        "origin_x_m": 100, "origin_y_m": 100, "width_m": float("nan"), "depth_m": 1, "height_m": 1,
    }), headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
    assert isinstance(response.json()["detail"], list)
    assert any(e.get("input") == "nan" for e in response.json()["detail"])
    assert project.path.read_bytes() == before




RAW = (ROOT / "tests/fixtures/weather/open_meteo_era5_phase60d_uat.json").read_bytes()
WEATHER = {"source_id": "open_meteo_archive_era5", "start_date": "2025-01-01", "end_date": "2025-01-01"}


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path, weather=False, strings=False)


def _reject(project, path, body, *, method="patch", contains=()):
    before = project.path.read_bytes()
    revision = deepcopy(project.bundle()["project"]["project_revision"])
    response = getattr(project.client, method)(project.url + path, json=body)
    assert response.status_code == 422, response.text
    for text in contains:
        assert text in str(response.json()["detail"]), response.text
    assert project.path.read_bytes() == before
    assert project.bundle()["project"]["project_revision"] == revision
    return response


def _rectangle(project, **params):
    return project.client.post(project.url + "/surfaces/rectangle", json={
        "origin_x_m": 100, "origin_y_m": 100, "width_m": 5, "height_m": 5, **params})


def _scene_command(kind, ids, parameters):
    return {"command": {"schema_name": "SceneEditorCommand", "schema_version": "0.1",
        "command_id": "s6-command", "command_type": kind, "target_entity_ids": ids, "parameters": parameters}}


def _delete(project, **kwargs):
    return project.client.delete(project.url, params={"confirm": project.pid}, **kwargs)


def test_01_project_metadata_without_revision(project):
    before = project.bundle()
    response = project.client.patch(project.url, json={"name": "  Renamed  ", "description": "Description"})
    assert response.status_code == 200, response.text
    updated = response.json()["bundle"]
    assert updated["project"]["name"] == "Renamed" and updated["project"]["description"] == "Description"
    assert updated["updated_at"] != before["updated_at"]
    assert updated["project"]["project_revision"] == before["project"]["project_revision"]
    assert project.client.get("/api/projects").json()[0]["name"] == "Renamed"
    assert project.client.patch(project.url, json={"description": None}).json()["bundle"]["project"]["description"] is None
    for body in ({"name": " \t "}, {"name": None}, {"extra": 1}, {}, {"name": "x" * 161}, {"description": "x" * 2001}):
        _reject(project, "", body)
    assert project.client.patch("/api/projects/missing", json={"name": "Valid"}).status_code == 404


def test_02_site_copies_local_geometry_map_and_noop(project):
    before = project.bundle()
    old_map = project.client.get(project.url).json()["scene_view"]["geojson"]
    values = {"latitude_deg": -7.1, "longitude_deg": 107.3, "elevation_m": 80, "timezone": "Asia/Makassar"}
    response = project.client.patch(project.url + "/site", json=values)
    assert response.status_code == 200, response.text
    after = response.json()["bundle"]
    site = after["project"]["site"]
    for key, value in values.items():
        assert site[key] == value and after["site_workspace_bootstrap"]["site"][key] == value
        if key != "timezone":
            assert site["local_coordinate_system"]["origin_" + key] == value
    old_lcs = before["project"]["site"]["local_coordinate_system"]
    assert site["local_coordinate_system"]["coordinate_system_id"] == old_lcs["coordinate_system_id"]
    assert site["local_coordinate_system"]["site_id"] == old_lcs["site_id"]
    assert site["local_coordinate_system"]["rotation_from_true_north_deg"] == 0
    assert json.dumps(after["scene"], sort_keys=True) == json.dumps(before["scene"], sort_keys=True)
    assert response.json()["scene_view"]["geojson"] != old_map
    revision = after["project"]["project_revision"]
    assert revision["revision_number"] == before["project"]["project_revision"]["revision_number"] + 1
    assert all(k in revision["change_summary"] for k in (*values, "local metres", "map-overlay"))
    stored = project.path.read_bytes()
    assert project.client.patch(project.url + "/site", json={**values, "clear_weather_selection": True}).status_code == 200
    assert project.path.read_bytes() == stored


def test_03_weather_bound_edits_clear_selection_keep_runs_and_files(tmp_path):
    project = Project(tmp_path)
    run = project.client.post(project.url + "/simulate", json={})
    assert run.status_code == 200, run.text
    before = project.bundle()
    selection = before["weather_selection"]
    directory = project.study.weather.root / project.pid
    files = {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    for change in ({"latitude_deg": -7}, {"longitude_deg": 108}, {"timezone": "Asia/Makassar"}, {"elevation_m": 26}):
        _reject(project, "/site", change, contains=(selection["revision_id"], "clear_weather_selection"))
    response = project.client.patch(project.url + "/site", json={"name": " Renamed site "})
    assert response.status_code == 200 and response.json()["bundle"]["weather_selection"] == selection
    response = project.client.patch(project.url + "/site", json={"elevation_m": 26, "clear_weather_selection": True})
    assert response.status_code == 200, response.text
    after = project.bundle()
    assert after["weather_selection"] is None and after["project"]["project_revision"]["weather_dataset_revision_id"] is None
    assert after["simulation_runs"] == before["simulation_runs"]
    assert {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()} == files
    assert not project.readiness()["ready"]
    assert any("weather" in f["message"].lower() for f in project.readiness()["findings"])


def test_04_site_and_create_elevation_validation(project):
    for values in ({"latitude_deg": 91}, {"latitude_deg": 90}, {"longitude_deg": 181}, {"timezone": "Mars/Base"},
                   {"elevation_m": 9001}, {"elevation_m": -501}, {}, {"clear_weather_selection": True}, {"extra": 1}, {"name": " "}):
        _reject(project, "/site", values)
    for value in (float("nan"), float("inf"), float("-inf")):
        before = project.path.read_bytes()
        response = project.client.patch(project.url + "/site", content=json.dumps({"latitude_deg": value}),
                                         headers={"Content-Type": "application/json"})
        assert response.status_code == 422 and isinstance(response.json()["detail"], str)
        assert project.path.read_bytes() == before
    assert project.client.patch("/api/projects/missing/site", json={"name": "Valid"}).status_code == 404
    create = {"name": "Site", "latitude_deg": -6.2, "longitude_deg": 106.8, "timezone": "Asia/Jakarta"}
    for value in (9001, -501, float("nan")):
        response = project.client.post("/api/projects", content=json.dumps({**create, "elevation_m": value}),
                                       headers={"Content-Type": "application/json"})
        assert response.status_code == 422 and isinstance(response.json()["detail"], list)


def test_05_delete_exact_paths_and_shared_snapshots(tmp_path):
    first = Project(tmp_path / "shared")
    second = Project(tmp_path / "shared")
    pid2 = second.pid
    snapshots = {p: p.read_bytes() for p in first.study.snapshots.root.rglob("*.json")}
    assert len(snapshots) == 1
    runs = first.study.run_root / first.pid
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "owned.txt").write_text("run")
    sibling = first.study.run_root / (first.pid + "-other")
    sibling.mkdir()
    (sibling / "keep").write_text("sibling")
    before = first.path.read_bytes()
    for params in ({}, {"confirm": "wrong"}):
        assert first.client.delete(first.url, params=params).status_code == 422
        assert first.path.read_bytes() == before and (runs / "owned.txt").exists()
    response = _delete(first)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted_project_id": first.pid, "removed": {"bundle": True, "runs": True, "weather": True, "imagery": False}}
    assert not first.path.exists() and not runs.exists() and not (first.study.weather.root / first.pid).exists()
    assert (sibling / "keep").read_text() == "sibling"
    assert first.client.get(first.url).status_code == 404 and _delete(first).status_code == 404
    assert all(r["project_id"] != first.pid for r in first.client.get("/api/projects").json())
    assert all(p.read_bytes() == data for p, data in snapshots.items())
    other_run = first.client.post(f"/api/projects/{pid2}/simulate", json={})
    assert other_run.status_code == 200, other_run.text
    assert other_run.json()["status"] in {"completed", "completed_with_warnings"}
    sentinel = tmp_path / "outside"
    sentinel.write_text("safe")
    for project_id in ("%2e%2e%2fx", "a/b", "a%2fb"):
        response = first.client.delete(f"/api/projects/{project_id}", params={"confirm": project_id})
        assert response.status_code in {422, 404}
        assert sentinel.read_text() == "safe"


@pytest.mark.parametrize("target", ["runs", "weather", "bundle", "loop"])
def test_05b_symlink_preflight_is_all_or_nothing(project, tmp_path, target):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("safe")
    runs = project.study.run_root / project.pid
    runs.mkdir(parents=True)
    (runs / "owned").write_text("owned")
    weather = project.study.weather.root / project.pid
    weather.mkdir(parents=True)
    (weather / "owned").write_text("weather")
    before = project.path.read_bytes()
    if target == "bundle":
        actual = outside / "bundle.json"
        actual.write_bytes(before)
        project.path.unlink()
        project.path.symlink_to(actual)
    else:
        path = runs if target in {"runs", "loop"} else weather
        shutil.rmtree(path)
        path.symlink_to(path.name if target == "loop" else outside, target_is_directory=True)
    response = _delete(project)
    assert response.status_code == 422, response.text
    assert project.path.read_bytes() == before and (outside / "keep").read_text() == "safe"
    if target not in {"runs", "loop"}:
        assert (runs / "owned").read_text() == "owned"
    if target != "weather":
        assert (weather / "owned").read_text() == "weather"


def test_05c_delete_does_not_follow_inner_symlink_and_retries_after_failure(project, tmp_path, monkeypatch):
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "keep").write_text("safe")
    runs = project.study.run_root / project.pid
    runs.mkdir(parents=True)
    (runs / "external-link").symlink_to(outside, target_is_directory=True)
    weather = project.study.weather.root / project.pid
    weather.mkdir(parents=True)
    original = study_module.shutil.rmtree
    def fail_weather(path, *args, **kwargs):
        if path == weather:
            raise OSError("injected removal failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(study_module.shutil, "rmtree", fail_weather)
    client = TestClient(project.app, raise_server_exceptions=False)
    assert client.delete(project.url, params={"confirm": project.pid}).status_code == 500
    assert project.path.exists() and not runs.exists() and weather.exists()
    assert (outside / "keep").read_text() == "safe"
    assert any(r["project_id"] == project.pid for r in project.client.get("/api/projects").json())
    monkeypatch.setattr(study_module.shutil, "rmtree", original)
    result = _delete(project)
    assert result.status_code == 200 and result.json()["removed"] == {"bundle": True, "runs": False, "weather": True, "imagery": False}
    assert (outside / "keep").read_text() == "safe"


@pytest.mark.parametrize("kind", ["run", "weather"])
def test_06_busy_blocks_site_and_delete_but_allows_metadata_and_scene(tmp_path, monkeypatch, kind):
    project = Project(tmp_path)
    entered, release = Event(), Event()
    if kind == "run":
        original = study_module.run_validated_design_simulation
        def paused(*args, **kwargs):
            entered.set()
            assert release.wait(30)
            return original(*args, **kwargs)
        monkeypatch.setattr(study_module, "run_validated_design_simulation", paused)
        path, body = "/simulate", {}
    else:
        def paused(*args, **kwargs):
            entered.set()
            assert release.wait(30)
            return RAW
        monkeypatch.setattr(project.study.open_meteo, "_get_bytes", paused)
        path, body = "/weather/acquire", WEATHER
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(project.client.post, project.url + path, json=body)
        try:
            assert entered.wait(30)
            before = project.path.read_bytes()
            assert _delete(project).status_code == 409
            assert project.client.patch(project.url + "/site", json={"name": "Busy"}).status_code == 409
            assert project.path.read_bytes() == before
            assert project.client.patch(project.url, json={"name": "Allowed metadata"}).status_code == 200
            assert _rectangle(project).status_code == 200
            electrical = project.client.post(project.url + "/electrical/commands", json={"commands": [{
                "schema_name": "ElectricalTopologyCommand", "schema_version": "0.1", "command_id": "during-operation",
                "command_type": "delete_string", "parameters": {"string_id": "S001"},
            }]})
            assert electrical.status_code == 200, electrical.text
        finally:
            release.set()
        result = future.result(timeout=30)
    assert result.status_code == 200, result.text
    assert project.bundle()["project"]["name"] == "Allowed metadata"
    assert len(project.bundle()["scene"]["surfaces"]) == 2
    assert project.bundle()["electrical_design"]["strings"] == []
    assert project.study._in_progress == {}
    assert project.client.patch(project.url + "/site", json={"name": "Now idle"}).status_code == 200
    assert _delete(project).status_code == 200


def test_07b_surface_added_during_weather_is_not_lost(project, monkeypatch):
    entered, release = Event(), Event()
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(30)
        return RAW
    monkeypatch.setattr(project.study.open_meteo, "_get_bytes", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(project.client.post, project.url + "/weather/acquire", json=WEATHER)
        try:
            assert entered.wait(30)
            assert _rectangle(project).status_code == 200
            revision = deepcopy(project.bundle()["project"]["project_revision"])
        finally:
            release.set()
        result = future.result(timeout=30)
    assert result.status_code == 200, result.text
    after = project.bundle()
    assert len(after["scene"]["surfaces"]) == 2
    assert after["weather_selection"] == result.json()["selection"]
    assert after["project"]["project_revision"] == {**revision, "weather_dataset_revision_id": result.json()["selection"]["revision_id"]}


@pytest.mark.parametrize("kind", ["run", "weather"])
def test_07c_registry_bypassed_deleted_project_is_not_resurrected(tmp_path, monkeypatch, kind):
    project = Project(tmp_path)
    entered, release = Event(), Event()
    monkeypatch.setattr(project.study, "_project_operation", lambda pid: nullcontext())
    if kind == "run":
        original = study_module.run_validated_design_simulation
        def paused(*args, **kwargs):
            entered.set()
            assert release.wait(30)
            return original(*args, **kwargs)
        monkeypatch.setattr(study_module, "run_validated_design_simulation", paused)
        operation = lambda: project.study.run_study(project.pid)
    else:
        original = project.study.open_meteo.parse_response
        def paused(*args, **kwargs):
            entered.set()
            assert release.wait(30)
            return original(*args, **kwargs)
        monkeypatch.setattr(project.study.open_meteo, "parse_response", paused)
        operation = lambda: project.study.acquire_weather(project.pid, **WEATHER, raw_response=RAW)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(operation)
        try:
            assert entered.wait(30)
            assert _delete(project).status_code == 200
        finally:
            release.set()
        with pytest.raises(ProjectNotFoundError):
            future.result(timeout=30)
    assert not project.path.exists() and project.client.get(project.url).status_code == 404


def test_08_azimuth_surface_type_and_polygon_slope_are_not_wrapped(tmp_path):
    project = GeometryProject(tmp_path, width=20, height=20)
    _reject(project, "/surfaces/rectangle", {"width_m": 5, "height_m": 5, "surface_type": "made_up"}, method="post")
    surface = project.bundle()["scene"]["surfaces"][0]["surface_id"]
    field = project.bundle()["scene"]["pv_fields"][0]["pv_field_id"]
    for value in (360, -1):
        _reject(project, "/pv-fields", {"support_surface_id": surface, "module_definition_revision_id": MODULE, "azimuth_deg": value}, method="post")
        _reject(project, "/pv-fields/" + field, {"azimuth_deg": value})
    response = project.client.patch(project.url + "/pv-fields/" + field, json={"azimuth_deg": 359.9})
    assert response.status_code == 200, response.text
    assert response.json()["bundle"]["scene"]["pv_fields"][0]["azimuth_deg"] == 359.9
    surface_response = _rectangle(project, origin_x_m=40, origin_y_m=0, width_m=20, height_m=20)
    new_surface = surface_response.json()["bundle"]["scene"]["surfaces"][-1]["surface_id"]
    response = project.client.post(project.url + "/pv-fields", json={"support_surface_id": new_surface,
        "module_definition_revision_id": MODULE, "azimuth_deg": 359.9})
    assert response.status_code == 200, response.text
    assert response.json()["bundle"]["scene"]["pv_fields"][-1]["azimuth_deg"] == 359.9
    params = {"surface_type": "flat_roof", "vertices": [[200, 0], [205, 0], [205, 5], [200, 5]]}
    for change in ({"azimuth_deg": 360}, {"azimuth_deg": -1}, {"slope_deg": 90}, {"slope_deg": -1}):
        _reject(project, "/scene/commands", _scene_command("draw_polygon", [], {**params, **change}), method="post")


def test_09_geometry_bounds_and_legacy_outlier(project):
    for params in ({"width_m": 10001}, {"origin_x_m": 50001}, {"width_m": 1e12}):
        _reject(project, "/surfaces/rectangle", {"width_m": 5, "height_m": 5, **params}, method="post", contains=("scene entity",))
    for change in ({"height_m": 1001}, {"base_elevation_m": 10001}, {"base_elevation_m": -1001}):
        _reject(project, "/obstacles/box", {"origin_x_m": 100, "origin_y_m": 100, "width_m": 5, "depth_m": 5, "height_m": 1, **change}, method="post", contains=("scene entity",))
    response = _rectangle(project)
    sid = response.json()["bundle"]["scene"]["surfaces"][-1]["surface_id"]
    _reject(project, "/scene/move", {"entity_id": sid, "dx_m": 50000, "dy_m": 0}, method="post", contains=(sid, "50000"))
    box = project.client.post(project.url + "/obstacles/box", json={"origin_x_m": 100, "origin_y_m": 100, "width_m": 1, "depth_m": 1, "height_m": 1})
    assert box.status_code == 200, box.text
    bundle = project.bundle()
    obstacle = bundle["scene"]["obstacles"][-1]
    obstacle["height_m"] = 1001
    for v in obstacle["footprint"]["vertices"]:
        v[0] += 60000
    project.service.store.save(bundle)
    before = deepcopy(obstacle)
    assert _rectangle(project, origin_x_m=200).status_code == 200
    assert project.bundle()["scene"]["obstacles"][-1] == before


def test_10b_nan_handler_recursive_inputs_and_string_contracts(project):
    response = project.client.post("/api/projects", content=json.dumps({"name": "Bad", "latitude_deg": float("nan"),
        "longitude_deg": 0, "timezone": "UTC"}), headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and isinstance(response.json()["detail"], list)
    # A nested invalid input must also serialize without NaN/inf JSON literals.
    response = project.client.post(project.url + "/obstacles/box", content=json.dumps({"width_m": {"nested": [float("inf"), float("-inf")]}}),
        headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert any(e.get("input") == {"nested": ["inf", "-inf"]} for e in response.json()["detail"])
    for path, body in (("/scene/commands", {}), ("/obstacles/extrusion", {"height_m": float("nan"), "vertices": []}),
                       ("/electrical/commands", {"commands": [], "dry_run": float("inf")})):
        before = project.path.read_bytes()
        response = project.client.post(project.url + path, content=json.dumps(body), headers={"Content-Type": "application/json"})
        assert response.status_code == 422 and isinstance(response.json()["detail"], str)
        assert project.path.read_bytes() == before


def test_11_future_dates_precede_transport_and_weather_http_mapping(project, monkeypatch):
    def never(*args, **kwargs):
        pytest.fail("future period reached provider transport")
    monkeypatch.setattr(provider_module, "urlopen", never)
    future = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    _reject(project, "/weather/acquire", {**WEATHER, "end_date": future}, method="post", contains=(f"end_date {future} is in the future; the archive has no data for it",))
    for code in (400, 404, 503):
        def fail(*args, **kwargs):
            raise HTTPError("https://provider.invalid", code, "Test period", {}, None)
        monkeypatch.setattr(provider_module, "urlopen", fail)
        before = project.path.read_bytes()
        response = project.client.post(project.url + "/weather/acquire", json=WEATHER)
        assert response.status_code == (422 if code < 500 else 503), response.text
        if code < 500:
            assert response.json()["detail"] == f"requested period is not available from the provider (HTTP {code}: Test period)"
        assert project.path.read_bytes() == before and project.study._in_progress == {}
    def offline(*args, **kwargs):
        raise URLError("Offline")
    monkeypatch.setattr(provider_module, "urlopen", offline)
    assert project.client.post(project.url + "/weather/acquire", json=WEATHER).status_code == 503
    assert project.study._in_progress == {}


def test_12_blank_polygon_and_extrusion_names(project):
    response = project.client.post(project.url + "/scene/commands", json=_scene_command("draw_polygon", [], {
        "name": " \t ", "surface_type": "flat_roof", "vertices": [[200, 0], [205, 0], [205, 5], [200, 5]],
    }))
    assert response.status_code == 200, response.text
    assert response.json()["bundle"]["scene"]["surfaces"][-1]["name"] == "Surface"
    response = project.client.post(project.url + "/obstacles/extrusion", json={
        "name": " \t ", "height_m": 1, "vertices": [[300, 0], [305, 0], [305, 5], [300, 5]],
    })
    assert response.status_code == 200, response.text
    assert response.json()["bundle"]["scene"]["obstacles"][-1]["name"] == "Obstacle"


def test_06b_counter_covers_overlapping_weather_requests_until_both_finish(project, monkeypatch):
    entered = [Event(), Event()]
    release = [Event(), Event()]
    indices = iter(range(2))
    def paused(*args, **kwargs):
        index = next(indices)
        entered[index].set()
        assert release[index].wait(30)
        return RAW
    monkeypatch.setattr(project.study.open_meteo, "_get_bytes", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(project.client.post, project.url + "/weather/acquire", json=WEATHER) for _ in range(2)]
        try:
            assert all(event.wait(30) for event in entered)
            assert project.study._in_progress[project.pid] == 2
            release[0].set()
            done, pending = wait(futures, timeout=30, return_when=FIRST_COMPLETED)
            assert len(done) == 1 and len(pending) == 1
            assert next(iter(done)).result().status_code == 200
            assert project.study._in_progress[project.pid] == 1
            assert _delete(project).status_code == 409
            assert project.client.patch(project.url + "/site", json={"name": "Still busy"}).status_code == 409
        finally:
            for event in release:
                event.set()
        assert all(f.result(timeout=30).status_code == 200 for f in futures)
    assert project.study._in_progress == {}
    assert project.client.patch(project.url + "/site", json={"name": "Both finished"}).status_code == 200


@pytest.mark.parametrize("intervention", ["run", "delete"])
def test_13_inflight_edit_cannot_overwrite_run_or_resurrect_project(tmp_path, monkeypatch, intervention):
    from geometry.scene import SceneEditorSession

    project = Project(tmp_path)
    entered, release = Event(), Event()
    original = SceneEditorSession.commit_revision
    def paused(self, *args, **kwargs):
        entered.set()
        assert release.wait(30), "test did not release ordinary edit"
        return original(self, *args, **kwargs)
    monkeypatch.setattr(SceneEditorSession, "commit_revision", paused)
    before = project.bundle()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_rectangle, project)
        try:
            assert entered.wait(30), "ordinary edit did not reach commit"
            if intervention == "run":
                response = project.client.post(project.url + "/simulate", json={})
                assert response.status_code == 200, response.text
                assert response.json()["status"] in {"completed", "completed_with_warnings"}
                merged = project.path.read_bytes()
            else:
                response = _delete(project)
                assert response.status_code == 200, response.text
                assert not project.path.exists()
        finally:
            release.set()
        edit = future.result(timeout=30)
    if intervention == "run":
        assert edit.status_code == 409, edit.text[:250]
        assert edit.json()["detail"] == "project changed concurrently; reload and retry"
        assert project.path.read_bytes() == merged
        assert len(project.bundle()["simulation_runs"]) == 1
        assert project.bundle()["simulation_runs"][0]["simulation_run_id"] == response.json()["simulation_run_id"]
        assert project.bundle()["scene"] == before["scene"]
    else:
        assert edit.status_code == 404, edit.text[:250]
        assert not project.path.exists()
        assert project.client.get(project.url).status_code == 404
        assert not any(row["project_id"] == project.pid for row in project.client.get("/api/projects").json())


def test_14_sequential_edits_and_same_bundle_saved_twice_succeed(project):
    before = project.bundle()
    for x in (100, 200):
        response = _rectangle(project, origin_x_m=x)
        assert response.status_code == 200, response.text
    after = project.bundle()
    assert len(after["scene"]["surfaces"]) == len(before["scene"]["surfaces"]) + 2
    assert after["project"]["project_revision"]["revision_number"] == before["project"]["project_revision"]["revision_number"] + 2
    bundle = project.bundle()
    bundle["project"]["description"] = "first save"
    project.service.save_bundle(bundle)
    first_timestamp = bundle["updated_at"]
    assert project.bundle()["updated_at"] == first_timestamp
    bundle["project"]["description"] = "second save"
    project.service.save_bundle(bundle)
    assert project.bundle()["updated_at"] == bundle["updated_at"]
    assert project.bundle()["project"]["description"] == "second save"
