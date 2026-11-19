"""Bounded synthetic persisted artifacts only: these tests never simulate."""
from copy import deepcopy
import csv
from hashlib import sha256
from io import BytesIO, StringIO
import json
from types import SimpleNamespace
from zipfile import ZipFile

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.server import create_app
from engine.simulation.artifacts import (
    _build_run_package_manifest,
    persist_parquet_result,
    persist_run_package,
)


REQUEST = {"format": "csv", "resolution": "hourly", "level": "project", "columns": ["pcc_power_w"]}


def reseal(case):
    """Test-only adversarial outer-manifest repair; never used by export code."""
    manifest = _build_run_package_manifest(case.directory, simulation_run_id=case.run_id)
    (case.directory / "run-package-manifest.json").write_text(json.dumps(manifest))


def rewrite_run(case, change):
    path = case.directory / "simulation-run.json"
    run = json.loads(path.read_text())
    change(run)
    path.write_text(json.dumps(run))
    reseal(case)


@pytest.fixture
def persisted(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CSV export must never run a simulation")
    monkeypatch.setattr("engine.simulation.canonical.run_canonical_simulation", forbidden)
    monkeypatch.setattr("apps.api.study.run_validated_design_simulation", forbidden)

    def make(*, frame=None, status="completed"):
        index = pd.date_range("2026-10-01T10:00:00+07:00", periods=3, freq="h")
        if frame is None:
            frame = pd.DataFrame({
                "timestamp": index,
                "interval_seconds": [3600., 3600., 3600.],
                "ghi_w_m2": [0., 510.125, 720.25],
                "ambient_temperature_c": [25., 26.5, 27.],
                "pcc_power_w": [-1.25, 1234.5678901234567, 2400.125],
                "interval_energy_wh": [-1.25, 1234.5678901234567, 2400.125],
                # Extra persisted fields must never become selectable implicitly.
                "mppt_1_mppt_pmp_w": [0., 1400., 2500.],
            })
        app = create_app(store_root=tmp_path / f"case-{make.count}" / "projects")
        make.count += 1
        service = app.state.project_service
        bundle = service.create_project(name="Synthetic CSV", latitude_deg=-6.2,
            longitude_deg=106.8, elevation_m=25., timezone_name="Asia/Jakarta",
            workspace_mode="map_overlay")
        project_id = bundle["project"]["project_id"]
        run_id = "synthetic-run"
        root = app.state.study_service.run_root / project_id
        reference = persist_parquet_result(frame, output_directory=root, simulation_run_id=run_id)
        identities = {
            "project_revision_id": bundle["project"]["project_revision"]["project_revision_id"],
            "scene_revision_id": "scene-synthetic-r1", "electrical_revision_id": "electrical-synthetic-r1",
            "weather_revision_id": "weather-synthetic-r1", "component_revision_manifest": {},
            "engine_version": "synthetic-test", "model_manifest": {},
        }
        reproduction = {
            "schema_name": "ReproducibilityManifest", "schema_version": "0.1", **identities,
            "simulation_timestep_seconds": 3600, "timezone": "UTC+07:00",
            "weather_transformations": [], "loss_models": [], "shading_configuration": {},
            "numerical_options": {},
            "input_hashes": {key: "a" * 64 for key in (
                "project_revision_sha256", "simulation_configuration_sha256", "scene_revision_sha256",
                "electrical_revision_sha256", "weather_dataset_sha256", "weather_series_logical_sha256",
                "component_manifest_sha256", "combined_input_sha256", "engine_version_sha256")},
            "native_weather_resolution_seconds": 3600, "working_weather_resolution_seconds": 3600,
            "source_timestamp_convention": "interval_start", "representative_time_policy": "interval_midpoint",
            "solar_evaluation_offset_minutes": 0., "output_configuration": {"standard_timeseries": True},
            "result_logical_content_sha256": reference["logical_content_sha256"],
            "result_file_sha256": reference["sha256"],
        }
        run = {
            "schema_name": "SimulationRun", "schema_version": "0.1", **identities,
            "simulation_run_id": run_id, "simulation_configuration_id": "configuration-synthetic",
            "started_at": "2026-10-01T00:00:00Z", "completed_at": "2026-10-01T00:00:00Z",
            "status": status, "input_hash": "a" * 64, "result_reference": reference,
            "summary_result": None, "validation_findings": [], "assumptions": [],
            "reproducibility_manifest": reproduction, "job_stage_history": ["completed"],
            "warning_summary": {"warning_count": 0, "error_count": 0, "blocking_error_count": 0},
        }
        directory = persist_run_package(output_directory=root, simulation_run_id=run_id,
            simulation_run=run, summary_result=None, reproducibility_manifest=reproduction,
            validation_findings=[], model_resolution=None)
        bundle["simulation_runs"] = [deepcopy(run)]
        service.save_bundle(bundle)
        return SimpleNamespace(app=app, client=TestClient(app), directory=directory,
            project_id=project_id, run_id=run_id, frame=frame,
            path=f"/api/projects/{project_id}/runs/{run_id}/exports")
    make.count = 0
    return make


def unpack(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == ["timeseries.csv", "export-manifest.json"]
        for info in archive.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
        raw = archive.read("timeseries.csv")
        return list(csv.DictReader(StringIO(raw.decode()))), json.loads(archive.read("export-manifest.json")), raw


def test_values_parity_schema_timestamps_determinism_and_immutable_source(persisted):
    case = persisted(status="completed_with_warnings")
    before = {p.relative_to(case.directory): (p.read_bytes(), p.stat().st_mtime_ns)
              for p in case.directory.rglob("*") if p.is_file()}
    schema = case.client.get(case.path + "/schema")
    assert schema.status_code == 200, schema.text
    fields = schema.json()["columns"]
    expected = list(case.frame.columns[:-1])
    assert [c["id"] for c in fields] == expected
    assert [c["id"] for c in fields if c["required"]] == ["timestamp", "interval_seconds"]
    assert {c["id"]: c["unit"] for c in fields}["pcc_power_w"] == "W"
    assert schema.json()["row_count"] == 3
    request = {**REQUEST, "columns": list(reversed(expected))}
    response = case.client.post(case.path, json=request)
    rows, manifest, raw = unpack(response)
    assert list(rows[0]) == expected
    assert len(rows) == len(case.frame)
    for ordinal, row in enumerate(rows):
        assert row["timestamp"] == case.frame.iloc[ordinal]["timestamp"].isoformat()
        assert row["timestamp"].endswith("+07:00")
        for column in expected[1:]:
            assert float(row[column]) == case.frame.iloc[ordinal][column]
        assert row["interval_seconds"] == "3600"
    assert b"\r\n" not in raw
    assert manifest["timestamp_convention"] == "interval_start"
    assert manifest["source_timezone"] == "UTC+07:00"
    assert manifest["source_interval"]["interval_seconds"] == 3600
    assert manifest["source_dataset"]["row_count"] == 3
    assert "uri" not in manifest["source_dataset"]
    assert manifest["csv_sha256"] == sha256(raw).hexdigest()
    assert manifest["csv_byte_size"] == len(raw)
    assert len(manifest["source_dataset"]["sha256"]) == 64
    assert len(manifest["source_dataset"]["logical_content_sha256"]) == 64
    assert manifest["source_identities"]["project_revision_id"]
    assert "generated_at" not in manifest
    assert [c["id"] for c in manifest["columns"]] == expected
    assert response.content == case.client.post(case.path, json=request).content
    assert response.content == case.client.post(case.path, json={**request, "columns": expected}).content
    after = {p.relative_to(case.directory): (p.read_bytes(), p.stat().st_mtime_ns)
             for p in case.directory.rglob("*") if p.is_file()}
    assert after == before


def test_required_columns_automatically_included(persisted):
    case = persisted()
    rows, manifest, _ = unpack(case.client.post(case.path, json=REQUEST))
    assert list(rows[0]) == ["timestamp", "interval_seconds", "pcc_power_w"]
    assert [c["id"] for c in manifest["columns"]] == list(rows[0])


def test_missing_numeric_values_are_empty_never_zero(persisted):
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-10-01T10:00:00+07:00", periods=3, freq="h"),
        "interval_seconds": [3600., 3600., 3600.], "pcc_power_w": [0., float("nan"), -1.5]})
    case = persisted(frame=frame)
    rows, manifest, _ = unpack(case.client.post(case.path, json=REQUEST))
    assert [r["pcc_power_w"] for r in rows] == ["0", "", "-1.5"]
    assert manifest["missing_value_serialization"] == "empty CSV field (never zero)"


@pytest.mark.parametrize("changes", [
    {"format": "parquet"}, {"resolution": "native"}, {"level": "inverter"}, {"level": "mppt"},
    {"columns": ["load"]}, {"columns": ["mppt_1_mppt_pmp_w"]}, {"columns": ["not_a_column"]},
    {"columns": ["dni_w_m2"]},
    {"columns": ["pcc_power_w", "pcc_power_w"]}, {"columns": []}, {"columns": [3]},
    {"columns": "pcc_power_w"}, {"columns": None}, {"extra": True},
])
def test_reject_unsupported_and_malformed_requests(persisted, changes):
    case = persisted()
    response = case.client.post(case.path, json={**REQUEST, **changes})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]


def test_malformed_json(persisted):
    case = persisted()
    response = case.client.post(case.path, content="{", headers={"Content-Type": "application/json"})
    assert response.status_code == 422


def test_unknown_project_run_and_project_binding(persisted):
    case, other = persisted(), persisted()
    assert case.client.get("/api/projects/unknown/runs/run/exports/schema").status_code == 404
    assert case.client.post(case.path.replace(case.run_id, "unknown"), json=REQUEST).status_code == 422
    # An actual directory is insufficient without a project run-list record.
    bundle = case.app.state.project_service.get_bundle(case.project_id)
    bundle["simulation_runs"] = []
    case.app.state.project_service.save_bundle(bundle)
    assert case.client.get(case.path + "/schema").status_code == 422
    assert other.client.get(other.path + "/schema").status_code == 200


@pytest.mark.parametrize("run_id", ["..", "../outside", "/tmp/outside", "a/b", "a\\b", "\x00bad"])
def test_path_traversal_rejected_before_read(persisted, run_id):
    case = persisted()
    with pytest.raises(ValueError):
        case.app.state.study_service.csv_export_source(case.project_id, run_id)


def test_project_traversal_and_symlink_rejected(persisted, tmp_path):
    case = persisted()
    with pytest.raises(ValueError):
        case.app.state.study_service.csv_export_source("../outside", case.run_id)
    link = case.directory.parent / "linked-run"
    link.symlink_to(case.directory, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        case.app.state.study_service.csv_export_source(case.project_id, "linked-run")
    nested = case.directory / "outside-link"
    nested.symlink_to(tmp_path / "outside")
    assert case.client.get(case.path + "/schema").status_code == 422


@pytest.mark.parametrize("kind", ["duration", "cadence", "naive", "missing_stamp", "missing_duration", "nullable_duration", "empty", "infinite", "duplicate"])
def test_invalid_interval_or_numeric_semantics(persisted, kind):
    stamps = pd.date_range("2026-10-01T10:00:00+07:00", periods=3, freq="h")
    frame = pd.DataFrame({"timestamp": stamps, "interval_seconds": [3600.] * 3, "pcc_power_w": [0., 1., 2.]})
    if kind == "duration":
        frame["interval_seconds"] = [1800.] * 3
    elif kind == "cadence":
        frame["timestamp"] = pd.date_range(stamps[0], periods=3, freq="2h")
    elif kind == "naive":
        frame["timestamp"] = stamps.tz_localize(None)
    elif kind == "missing_stamp":
        frame.loc[1, "timestamp"] = pd.NaT
    elif kind == "missing_duration":
        frame.loc[1, "interval_seconds"] = float("nan")
    elif kind == "nullable_duration":
        frame["interval_seconds"] = pd.Series([3600., pd.NA, 3600.], dtype="Float64")
    elif kind == "empty":
        frame = frame.iloc[:0]
    elif kind == "infinite":
        frame.loc[1, "pcc_power_w"] = float("inf")
    elif kind == "duplicate":
        frame.loc[1, "timestamp"] = frame.loc[0, "timestamp"]
    case = persisted(frame=frame)
    for response in (case.client.get(case.path + "/schema"), case.client.post(case.path, json=REQUEST)):
        assert response.status_code == 422, response.text
        assert response.json()["detail"]


@pytest.mark.parametrize("artifact", ["timeseries.parquet", "simulation-run.json", "reproducibility-manifest.json", "run-package-manifest.json"])
@pytest.mark.parametrize("operation", ["tamper", "delete"])
def test_missing_and_tampered_package(persisted, artifact, operation):
    case = persisted()
    path = case.directory / artifact
    if operation == "delete":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"tampered")
    assert case.client.get(case.path + "/schema").status_code == 422
    assert case.client.post(case.path, json=REQUEST).status_code == 422


@pytest.mark.parametrize("field,value", [
    ("logical_content_sha256", "b" * 64), ("sha256", "b" * 64), ("row_count", 99),
    ("column_count", 99), ("columns", ["timestamp", "interval_seconds", "pcc_power_w"]),
    ("timestamp_convention", "interval_end"), ("uri", "file:///tmp/outside.parquet"),
])
def test_reference_binding_after_outer_manifest_repaired(persisted, field, value):
    case = persisted()
    rewrite_run(case, lambda run: run["result_reference"].__setitem__(field, value))
    assert case.client.get(case.path + "/schema").status_code == 422


@pytest.mark.parametrize("status", ["running", "failed", "queued", "cancelled"])
def test_noncompleted_run_rejected(persisted, status):
    case = persisted(status=status)
    response = case.client.get(case.path + "/schema")
    assert response.status_code == 422
    assert "completed" in response.json()["detail"]


def test_run_identity_and_saved_input_binding(persisted):
    case = persisted()
    rewrite_run(case, lambda run: run.__setitem__("simulation_run_id", "different-run"))
    assert case.client.get(case.path + "/schema").status_code == 422
    case = persisted()
    rewrite_run(case, lambda run: run.__setitem__("input_hash", "b" * 64))
    assert case.client.get(case.path + "/schema").status_code == 422


@pytest.mark.parametrize("key,value", [("simulation_timestep_seconds", 1800), ("working_weather_resolution_seconds", 1800), ("timezone", "UTC")])
def test_source_resolution_and_timezone_metadata_binding(persisted, key, value):
    case = persisted()
    def change(run):
        run["reproducibility_manifest"][key] = value
        (case.directory / "reproducibility-manifest.json").write_text(json.dumps(run["reproducibility_manifest"]))
    rewrite_run(case, change)
    assert case.client.get(case.path + "/schema").status_code == 422


def test_daylight_saving_offsets_preserved_without_conversion(persisted):
    stamps = pd.date_range("2026-11-01T00:00:00", periods=4, freq="h", tz="America/New_York")
    case = persisted(frame=pd.DataFrame({"timestamp": stamps, "interval_seconds": [3600.] * 4, "pcc_power_w": [0., 1., 2., 3.]}))
    def change(run):
        run["reproducibility_manifest"]["timezone"] = "America/New_York"
        (case.directory / "reproducibility-manifest.json").write_text(json.dumps(run["reproducibility_manifest"]))
    rewrite_run(case, change)
    rows, manifest, _ = unpack(case.client.post(case.path, json=REQUEST))
    assert [r["timestamp"] for r in rows] == [s.isoformat() for s in stamps]
    assert rows[1]["timestamp"].endswith("-04:00")
    assert rows[2]["timestamp"].endswith("-05:00")
    assert manifest["source_timezone"] == "America/New_York"


@pytest.mark.parametrize("column", ["timestamp", "interval_seconds"])
def test_missing_interpretive_column_rejected(persisted, column):
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-10-01T10:00:00+07:00", periods=1, freq="h"),
        "interval_seconds": [3600.], "pcc_power_w": [5.]}).drop(columns=[column])
    case = persisted(frame=frame)
    assert case.client.get(case.path + "/schema").status_code == 422


def test_single_hour_is_exported_without_synthesizing_rows(persisted):
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-10-01T10:00:00+07:00", periods=1, freq="h"),
        "interval_seconds": [3600.], "pcc_power_w": [5.]})
    case = persisted(frame=frame)
    rows, manifest, _ = unpack(case.client.post(case.path, json=REQUEST))
    assert len(rows) == manifest["row_count"] == 1
    assert float(rows[0]["pcc_power_w"]) == 5.


def test_noncomplete_manifest_rejected(persisted):
    case = persisted()
    path = case.directory / "run-package-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["package_state"] = "incomplete"
    path.write_text(json.dumps(manifest))
    assert case.client.get(case.path + "/schema").status_code == 422


@pytest.mark.parametrize("payload", [[], {"artifacts": [None]}])
def test_malformed_completion_manifest_is_clear_error(persisted, payload):
    case = persisted()
    (case.directory / "run-package-manifest.json").write_text(json.dumps(payload))
    assert case.client.get(case.path + "/schema").status_code == 422


def test_numeric_serialization_preserves_persisted_integers(persisted):
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-10-01T10:00:00+07:00", periods=1, freq="h"),
        "interval_seconds": [3600], "pcc_power_w": [9007199254740993]})
    case = persisted(frame=frame)
    rows, _, _ = unpack(case.client.post(case.path, json=REQUEST))
    assert rows[0]["pcc_power_w"] == "9007199254740993"
