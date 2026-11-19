from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.catalog import catalog_summaries, load_reference_catalog
from apps.api.project_store import FileProjectStore
from apps.api.server import create_app
from apps.api.service import ProjectShellService
from apps.api.study import BrowserStudyService
from components.validation import validate_inverter


ROOT = Path(__file__).resolve().parents[2]
UAT_MODULE_REV = "mod-rawibumi-uat-550-r1"
UAT_INVERTER_REV = "inv-rawibumi-uat-150k-r1"


def _services(tmp_path):
    project_service = ProjectShellService(FileProjectStore(tmp_path / "projects"))
    study = BrowserStudyService(
        project_service,
        weather_root=tmp_path / "weather",
        run_root=tmp_path / "runs",
        snapshot_root=tmp_path / "weather-snapshots",
    )
    return project_service, study


def _author_native_uat_project(project_service):
    bundle = project_service.create_project(
        name="RawiBumi native UAT",
        latitude_deg=-6.2,
        longitude_deg=106.8,
        elevation_m=25.0,
        timezone_name="Asia/Jakarta",
        workspace_mode="map_overlay",
    )
    project_id = bundle["project"]["project_id"]

    view = project_service.add_surface_rectangle(
        project_id,
        name="UAT roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=24.0,
        height_m=8.0,
        base_elevation_m=8.0,
        surface_type="flat_roof",
        usable_for_pv=True,
    )
    surface_id = view["bundle"]["scene"]["surfaces"][0]["surface_id"]

    project_service.add_box_obstacle(
        project_id,
        name="UAT obstacle",
        origin_x_m=11.5,
        origin_y_m=6.6,
        width_m=1.0,
        depth_m=1.0,
        base_elevation_m=8.0,
        height_m=1.8,
    )

    view = project_service.create_pv_field(
        project_id,
        name="UAT array",
        support_surface_id=surface_id,
        module_definition_revision_id=UAT_MODULE_REV,
        orientation="portrait",
        azimuth_deg=0.0,
        tilt_deg=10.0,
        row_pitch_m=2.6,
        perimeter_setback_m=0.3,
        obstacle_setback_m=0.3,
    )
    assert len(view["bundle"]["scene"]["module_instances"]) >= 10

    view = project_service.add_inverter(
        project_id,
        inverter_definition_revision_id=UAT_INVERTER_REV,
        name="INV-01",
    )
    inverter_id = view["bundle"]["electrical_design"]["inverter_instances"][0][
        "inverter_instance_id"
    ]

    view = project_service.create_strings(
        project_id,
        string_length=10,
        allow_shorter_remainder=False,
    )
    strings = view["bundle"]["electrical_design"]["strings"]
    assert strings
    assert {len(item["module_instance_ids"]) for item in strings} == {10}

    view = project_service.assign_strings(
        project_id,
        inverter_instance_id=inverter_id,
    )
    assert view["topology_consistency"]["blocking_count"] == 0
    assert not view["topology_view"]["unassigned_strings"]
    return project_id


def test_phase60d_native_browser_project_runs_existing_phase5_engine(tmp_path):
    projects, study = _services(tmp_path)
    project_id = _author_native_uat_project(projects)

    fixture = (
        ROOT / "tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json"
    ).read_bytes()
    acquired = study.acquire_weather(
        project_id,
        source_id="open_meteo_archive_era5",
        start_date="2025-01-01",
        end_date="2025-01-01",
        raw_response=fixture,
    )

    assert acquired["selection"]["source_id"] == "open_meteo_archive_era5"
    assert acquired["manifest"]["source_method"]["projection_authority"] == (
        "source_product"
    )
    assert (
        acquired["manifest"]["source_method"][
            "rawibumi_resource_projection_applied"
        ]
        is False
    )
    assert acquired["manifest"]["source_method"][
        "opensimpv_resource_projection_applied"
    ] is False

    readiness = study.execution_readiness(project_id)
    assert readiness["ready"] is True, readiness["findings"]
    assert readiness["execution_class"] == "homogeneous_single_group"
    assert readiness["legacy_homogeneous_backend_compatible"] is True

    record = study.run_study(project_id)
    diagnostic = [
        (item.get("rule_id"), item.get("severity"), item.get("message"))
        for item in record["validation_findings"]
        if item.get("severity") in {"blocking_error", "error"}
    ]
    assert record["status"] in {"completed", "completed_with_warnings"}, diagnostic
    assert record["summary_result"] is not None
    assert record["summary_result"]["total_energy_wh"] >= 0.0
    assert record["summary_result"]["monthly_energy"]
    assert record["summary_result"]["loss_summary"]
    assert record["weather_source"]["source_id"] == "open_meteo_archive_era5"

    reopened = ProjectShellService(
        FileProjectStore(tmp_path / "projects")
    ).project_view(project_id)
    assert reopened["bundle"]["weather_selection"]["revision_id"] == (
        acquired["selection"]["revision_id"]
    )
    assert reopened["bundle"]["simulation_runs"][-1]["simulation_run_id"] == (
        record["simulation_run_id"]
    )

    run_dir = (
        tmp_path
        / "runs"
        / project_id
        / record["simulation_run_id"]
    )
    assert (run_dir / "simulation-run.json").exists()
    assert (run_dir / "summary-result.json").exists()
    assert (run_dir / "timeseries.parquet").exists()


def test_phase60d_weather_source_catalog_is_explicit_and_unblended(tmp_path):
    _, study = _services(tmp_path)
    sources = study.weather_sources()
    assert [item["source_id"] for item in sources] == [
        "open_meteo_archive_era5"
    ]
    assert all(
        item["rawibumi_resource_projection_applied"] is False
        for item in sources
    )


def test_phase60d_simulation_requires_pinned_weather(tmp_path):
    projects, study = _services(tmp_path)
    project_id = _author_native_uat_project(projects)

    import pytest

    with pytest.raises(ValueError, match="weather source"):
        study.run_study(project_id)


def test_phase60d_fastapi_vertical_slice_uses_pinned_fixture_without_live_network(tmp_path):
    app = create_app(store_root=tmp_path / "api-projects")
    client = TestClient(app)

    project_id = _author_native_uat_project(app.state.project_service)
    fixture = (
        ROOT / "tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json"
    ).read_bytes()
    acquired = app.state.study_service.acquire_weather(
        project_id,
        source_id="open_meteo_archive_era5",
        start_date="2025-01-01",
        end_date="2025-01-01",
        raw_response=fixture,
    )

    sources = client.get("/api/weather-sources")
    assert sources.status_code == 200
    assert [item["source_id"] for item in sources.json()] == [
        "open_meteo_archive_era5"
    ]

    readiness = client.get(f"/api/projects/{project_id}/execution-readiness")
    assert readiness.status_code == 200
    assert readiness.json()["ready"] is True, readiness.json()["findings"]

    run = client.post(f"/api/projects/{project_id}/simulate")
    assert run.status_code == 200
    body = run.json()
    assert body["status"] in {"completed", "completed_with_warnings"}, [
        (item.get("rule_id"), item.get("severity"), item.get("message"))
        for item in body.get("validation_findings", [])
    ]
    assert body["weather_dataset_revision_id"] == acquired["selection"]["revision_id"]
    assert body["summary_result"]["monthly_energy"]
    assert body["summary_result"]["loss_summary"]

    runs = client.get(f"/api/projects/{project_id}/runs")
    assert runs.status_code == 200
    assert runs.json()[-1]["simulation_run_id"] == body["simulation_run_id"]

    reopened = client.get(f"/api/projects/{project_id}")
    assert reopened.status_code == 200
    assert reopened.json()["bundle"]["simulation_runs"][-1]["input_hash"] == (
        body["input_hash"]
    )


def test_phase60d_explicit_mppt_reference_is_design_valid_but_execution_blocked(tmp_path):
    projects, study = _services(tmp_path)
    bundle = projects.create_project(
        name="Explicit MPPT readiness boundary",
        latitude_deg=-6.2,
        longitude_deg=106.8,
        elevation_m=25.0,
        timezone_name="Asia/Jakarta",
        workspace_mode="blank_engineering_plane",
    )
    project_id = bundle["project"]["project_id"]
    view = projects.add_surface_rectangle(
        project_id,
        name="Roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=24.0,
        height_m=8.0,
        base_elevation_m=8.0,
        surface_type="flat_roof",
        usable_for_pv=True,
    )
    surface_id = view["bundle"]["scene"]["surfaces"][0]["surface_id"]
    projects.create_pv_field(
        project_id,
        name="Array",
        support_surface_id=surface_id,
        module_definition_revision_id=UAT_MODULE_REV,
        orientation="portrait",
        azimuth_deg=0.0,
        tilt_deg=10.0,
        row_pitch_m=2.6,
        perimeter_setback_m=0.3,
        obstacle_setback_m=0.3,
    )
    view = projects.add_inverter(
        project_id,
        inverter_definition_revision_id="inv-rawibumi-ref-150k-r1",
        name="INV-EXPLICIT",
    )
    inverter_id = view["bundle"]["electrical_design"]["inverter_instances"][0][
        "inverter_instance_id"
    ]
    projects.create_strings(
        project_id,
        string_length=10,
        allow_shorter_remainder=False,
    )
    projects.assign_strings(
        project_id,
        inverter_instance_id=inverter_id,
    )

    fixture = (
        ROOT / "tests/fixtures/weather/open_meteo_era5_phase60d_uat.json"
    ).read_bytes()
    study.acquire_weather(
        project_id,
        source_id="open_meteo_archive_era5",
        start_date="2025-01-01",
        end_date="2025-01-01",
        raw_response=fixture,
    )

    readiness = study.execution_readiness(project_id)
    assert readiness["ready"] is False
    assert any(
        item["rule_id"] == "EXECUTION_INVERTER_EXPLICIT_MPPTS_UNSUPPORTED"
        for item in readiness["findings"]
    )

    import pytest

    with pytest.raises(ValueError, match="execution preflight failed"):
        study.run_study(project_id)


def test_phase60d_catalog_distinguishes_design_only_and_phase5_executable_inverters():
    catalog = load_reference_catalog()
    uat = catalog["inverters"][UAT_INVERTER_REV]
    explicit = catalog["inverters"]["inv-rawibumi-ref-150k-r1"]

    assert "mppts" not in uat
    assert uat["mppt_template"]["count"] == 2
    assert uat["mppt_template"]["input_count_per_mppt"] == 3
    assert not [
        item
        for item in validate_inverter(uat)
        if item["severity"] in {"blocking_error", "error"}
    ]

    summaries = {
        item["revision_id"]: item
        for item in catalog_summaries()["inverters"]
    }
    assert summaries[UAT_INVERTER_REV]["simulation_ready"] is True
    assert summaries["inv-rawibumi-ref-150k-r1"]["simulation_ready"] is False
    assert any(
        item["rule_id"] == "EXECUTION_INVERTER_EXPLICIT_MPPTS_UNSUPPORTED"
        for item in summaries["inv-rawibumi-ref-150k-r1"][
            "execution_readiness_findings"
        ]
    )
