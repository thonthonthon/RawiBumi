import json
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from components.candidates import build_inverter_candidate, build_module_candidate
from components.ond import parse_ond_text
from components.ond.mapper import map_ond
from components.pan import parse_pan_text
from components.pan.mapper import map_pan
from engine.inverter import INVERTER_VOLTAGE_DEPENDENT
from engine.irradiance import POA_ISOTROPIC
from engine.module import MODULE_PVSYST_SDM
from engine.optical import IAM_NONE
from engine.simulation import (
    CanonicalRevisionStore,
    run_canonical_simulation,
)
from engine.solar import SOLAR_POSITION_NREL_SPA
from engine.thermal import THERMAL_PVSYST
from weather.core import build_time_semantics, build_weather_dataset


ROOT = Path(__file__).resolve().parents[2]


def _module_definition():
    mapping = map_pan(
        parse_pan_text(
            (
                ROOT / "tests/fixtures/panond/synthetic_module.pan"
            ).read_text(encoding="utf-8")
        )
    )
    candidate = build_module_candidate(
        mapping,
        candidate_id="cand-phase38e-module",
        module_definition_id="mod-phase38e-module",
        revision_id="mod-phase38e-module-r1",
        source_id="src-phase38e-module",
    )
    assert candidate["definition_schema_ready"] is True, candidate[
        "validation_findings"
    ]
    return candidate["canonical_data"]


def _inverter_definition():
    mapping = map_ond(
        parse_ond_text(
            (
                ROOT
                / "tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND"
            ).read_text(encoding="utf-8")
        )
    )
    candidate = build_inverter_candidate(
        mapping,
        candidate_id="cand-phase38e-inverter",
        inverter_definition_id="inv-phase38e-huawei",
        revision_id="inv-phase38e-huawei-r1",
        source_id="src-phase38e-inverter",
    )
    assert candidate["definition_schema_ready"] is True, candidate[
        "validation_findings"
    ]
    return candidate["canonical_data"]


def _weather():
    index = pd.date_range(
        "2026-03-21T10:00:00+07:00",
        periods=3,
        freq="h",
    )
    # Diffuse-only and internally closed: GHI = DHI + DNI*cos(SZA).
    # This keeps the canonical orchestration test independent of decomposition.
    series = pd.DataFrame(
        {
            "ghi_w_m2": [400.0, 600.0, 800.0],
            "dni_w_m2": [0.0, 0.0, 0.0],
            "dhi_w_m2": [400.0, 600.0, 800.0],
            "ambient_temperature_c": [30.0, 30.0, 30.0],
            "wind_speed_m_s": [1.0, 1.0, 1.0],
            "pressure_pa": [100500.0, 100500.0, 100500.0],
        },
        index=index,
    )
    semantics = build_time_semantics(
        canonical_timezone="UTC+07:00",
        source_timestamp_convention="interval_start",
        native_interval_seconds=3600,
        current_interval_seconds=3600,
        source_timezone="UTC+07:00",
        source_utc_offset_hours=7.0,
    )
    return build_weather_dataset(
        series,
        weather_dataset_id="wx-phase38e",
        revision_id="wx-phase38e-r1",
        name="Phase 3.8E weather",
        site_id="site-phase38e",
        timezone="UTC+07:00",
        native_resolution_seconds=3600,
        source_format="synthetic_test",
        source_timestamp_convention="interval_start",
        location={
            "latitude_deg": -6.425,
            "longitude_deg": 106.831,
            "elevation_m": 93.0,
        },
        native_series_origin="measured",
        series_origin="measured",
        time_semantics=semantics,
    )


def _project_revision():
    return {
        "schema_name": "ProjectRevision",
        "schema_version": "0.1",
        "project_revision_id": "proj-phase38e-r1",
        "revision_number": 1,
        "scene_revision_id": "scene-phase38e-r1",
        "electrical_revision_id": "elec-phase38e-r1",
        "weather_dataset_revision_id": "wx-phase38e-r1",
        "simulation_defaults_revision_id": None,
        "change_summary": "Phase 3.8E synthetic canonical execution fixture.",
    }


def _scene(module_revision_id: str):
    module_ids = [f"module-{index:02d}" for index in range(1, 19)]
    transform = {
        "position_x_m": 0.0,
        "position_y_m": 0.0,
        "position_z_m": 8.2,
        "rotation_x_deg": 0.0,
        "rotation_y_deg": 0.0,
        "rotation_z_deg": 0.0,
        "scale_x": 1.0,
        "scale_y": 1.0,
        "scale_z": 1.0,
    }
    return {
        "schema_name": "Scene",
        "schema_version": "0.1",
        "scene_id": "scene-phase38e",
        "project_id": "proj-phase38e",
        "revision_id": "scene-phase38e-r1",
        "coordinate_system_id": "enu-phase38e",
        "map_layer_configuration": None,
        "created_at": "2026-09-23T00:00:00Z",
        "notes": "Synthetic homogeneous unshaded field.",
        "surfaces": [
            {
                "surface_id": "roof-001",
                "scene_object_id": "obj-roof-001",
                "surface_type": "flat_roof",
                "boundary_2d": {
                    "vertices": [
                        [0.0, 0.0],
                        [30.0, 0.0],
                        [30.0, 10.0],
                        [0.0, 10.0],
                    ],
                    "holes": [],
                    "winding": "counterclockwise",
                    "closed": True,
                },
                "base_elevation_m": 8.0,
                "slope_deg": 0.0,
                "azimuth_deg": 0.0,
                "parent_surface_id": None,
                "material": None,
                "albedo": 0.20,
                "usable_for_pv": True,
                "shading_receiver": False,
                "notes": None,
            }
        ],
        "obstacles": [],
        "pv_fields": [
            {
                "pv_field_id": "field-001",
                "scene_id": "scene-phase38e",
                "name": "Reference field",
                "support_surface_id": "roof-001",
                "module_definition_revision_id": module_revision_id,
                "orientation": "portrait",
                "azimuth_deg": 0.0,
                "tilt_deg": 0.0,
                "mounting_height_m": 0.2,
                "layout_mode": "fixed_tilt",
                "row_count": 1,
                "modules_per_row": 18,
                "module_gap_x_m": 0.02,
                "module_gap_y_m": 0.02,
                "row_pitch_m": 2.5,
                "table_configuration": None,
                "boundary_constraint_id": None,
                "setback_configuration": {
                    "perimeter_setback_m": 0.0,
                    "edge_specific_setbacks": None,
                    "obstacle_setback_m": 0.0,
                    "walkway_rules": None,
                },
                "generated_module_instance_ids": module_ids,
                "layout_source": "manual",
                "notes": None,
            }
        ],
        "module_instances": [
            {
                "module_instance_id": module_id,
                "pv_field_id": "field-001",
                "module_definition_revision_id": module_revision_id,
                "transform": {
                    **transform,
                    "position_x_m": float(index),
                },
                "row_index": 0,
                "column_index": index,
                "table_index": None,
                "enabled": True,
                "electrical_connection_id": None,
                "metadata": {},
            }
            for index, module_id in enumerate(module_ids)
        ],
    }


def _electrical(inverter_revision_id: str):
    module_ids = [f"module-{index:02d}" for index in range(1, 19)]
    return {
        "schema_name": "ElectricalDesignRevision",
        "schema_version": "0.1",
        "electrical_revision_id": "elec-phase38e-r1",
        "project_id": "proj-phase38e",
        "created_at": "2026-09-23T00:00:00Z",
        "change_summary": "Single-string canonical fixture.",
        "inverter_instances": [
            {
                "inverter_instance_id": "inv-inst-001",
                "project_revision_id": "proj-phase38e-r1",
                "inverter_definition_revision_id": inverter_revision_id,
                "name": "INV-01",
                "location": None,
                "enabled": True,
                "mppt_instance_ids": ["mppt-inst-001"],
                "ac_connection_id": "conn-ac-001",
            }
        ],
        "mppt_instances": [
            {
                "mppt_instance_id": "mppt-inst-001",
                "inverter_instance_id": "inv-inst-001",
                "mppt_definition_id": "mppt-def-001",
                "index": 1,
                "connected_string_ids": ["string-001"],
                "enabled": True,
            }
        ],
        "strings": [
            {
                "string_id": "string-001",
                "project_revision_id": "proj-phase38e-r1",
                "name": "S01",
                "module_instance_ids": module_ids,
                "target_mppt_instance_id": "mppt-inst-001",
                "enabled": True,
                "polarity": "normal",
                "cable_definition_id": None,
                "notes": None,
            }
        ],
        "connections": [
            {
                "connection_id": "conn-ac-001",
                "project_revision_id": "proj-phase38e-r1",
                "from_node_id": "inv-inst-001",
                "to_node_id": "pcc-001",
                "connection_type": "pcc",
                "phase": "three_phase",
                "conductor_reference": None,
                "length_m": None,
                "resistance_ohm": None,
                "loss_model_id": None,
                "enabled": True,
            }
        ],
        "pcc_definition": {"pcc_id": "pcc-001"},
    }


def _configuration():
    return {
        "schema_name": "SimulationConfiguration",
        "schema_version": "0.1",
        "simulation_configuration_id": "simcfg-phase38e-001",
        "project_revision_id": "proj-phase38e-r1",
        "name": "Phase 3.8E canonical execution",
        "simulation_timestep_seconds": 3600,
        "start_time": None,
        "end_time": None,
        "weather_dataset_revision_id": "wx-phase38e-r1",
        "model_selections": {
            "solar_position": SOLAR_POSITION_NREL_SPA,
            "transposition": POA_ISOTROPIC,
            "temperature": THERMAL_PVSYST,
            "module_electrical": MODULE_PVSYST_SDM,
            "inverter": INVERTER_VOLTAGE_DEPENDENT,
            "iam": IAM_NONE,
        },
        "loss_model_ids": ["loss_ledger.electrical_chain.v0.1"],
        "shading_configuration": {
            "beam_method": "none",
            "diffuse_method": "none",
            "albedo_method": "support_surface",
            "fidelity_level": "engineering",
            "sun_position_resolution_seconds": None,
            "electrical_shading_method": None,
        },
        "numerical_options": {
            "thermal": {
                "u_c_w_m2k": 20.0,
                "u_v_w_m2k_per_ms": 0.0,
            },
            "losses": {
                "module_mismatch_loss_fraction": 0.0,
                "string_mismatch_loss_fraction": 0.0,
                "dc_array_resistance_ohm": 0.0,
            },
            "coupling": {
                "initial_module_efficiency_fraction": 0.0,
                "temperature_tolerance_c": 1e-4,
                "efficiency_tolerance_fraction": 1e-8,
                "max_iterations": 25,
                "relaxation_factor": 1.0,
            },
            "module_solver": "lambertw",
        },
        "output_configuration": {
            "standard_timeseries": True,
            "format": "parquet",
        },
    }


def _inputs():
    module = _module_definition()
    inverter = _inverter_definition()
    weather = _weather()
    scene = _scene(module["revision_id"])
    electrical = _electrical(inverter["revision_id"])
    store = CanonicalRevisionStore(
        scene_revisions={scene["revision_id"]: scene},
        electrical_revisions={
            electrical["electrical_revision_id"]: electrical
        },
        weather_revisions={weather.dataset["revision_id"]: weather},
        component_revisions={
            module["revision_id"]: module,
            inverter["revision_id"]: inverter,
        },
    )
    return _project_revision(), _configuration(), store


def _schema_registry():
    registry = Registry()
    for path in (ROOT / "schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        if "$id" in schema:
            registry = registry.with_resource(
                schema["$id"],
                Resource.from_contents(schema),
            )
    return registry


def _validate_run(run):
    schema = json.loads(
        (ROOT / "schemas/simulation-run.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(
        schema,
        registry=_schema_registry(),
    ).validate(run)


def test_canonical_revisioned_execution_produces_immutable_run_package(tmp_path):
    project_revision, configuration, store = _inputs()

    result = run_canonical_simulation(
        project_revision,
        configuration,
        revision_store=store,
        output_directory=tmp_path,
        simulation_run_id="run-phase38e-001",
        engine_version="opensimpv-test@phase38e",
        executed_at="2026-09-23T12:00:00Z",
    )

    run = result.simulation_run
    _validate_run(run)

    assert run["status"] in {"completed", "completed_with_warnings"}, [
        (
            item["rule_id"],
            item["entity_id"],
            item["message"],
            item["context"],
        )
        for item in run["validation_findings"]
    ]
    assert run["project_revision_id"] == "proj-phase38e-r1"
    assert run["scene_revision_id"] == "scene-phase38e-r1"
    assert run["electrical_revision_id"] == "elec-phase38e-r1"
    assert run["weather_revision_id"] == "wx-phase38e-r1"
    assert run["component_revision_manifest"] == {
        "module_revision_id": "mod-phase38e-module-r1",
        "inverter_revision_id": "inv-phase38e-huawei-r1",
    }
    assert run["model_manifest"]["module"] == MODULE_PVSYST_SDM
    assert run["model_manifest"]["inverter"] == INVERTER_VOLTAGE_DEPENDENT
    assert run["job_stage_history"] == [
        "queued",
        "validating",
        "preprocessing",
        "simulating",
        "aggregating",
        "reconciling",
        "completed",
    ]

    run_dir = tmp_path / "run-phase38e-001"
    assert (run_dir / "timeseries.parquet").exists()
    assert (run_dir / "simulation-run.json").exists()
    assert (run_dir / "summary-result.json").exists()
    assert (run_dir / "reproducibility-manifest.json").exists()
    assert (run_dir / "validation-findings.json").exists()
    assert (run_dir / "model-resolution.json").exists()

    persisted = pd.read_parquet(run_dir / "timeseries.parquet")
    pd.testing.assert_frame_equal(
        persisted,
        result.standard_timeseries.reset_index(drop=True),
        check_dtype=False,
    )

    reference = run["result_reference"]
    assert reference["format"] == "parquet"
    assert reference["row_count"] == 3
    assert reference["logical_content_sha256"]
    assert len(reference["sha256"]) == 64

    summary = result.summary_result
    assert summary is not None
    assert summary["simulation_run_id"] == "run-phase38e-001"
    expected_total_energy_wh = (
        result.backend_result.energy.annual["pcc_power_kwh"] * 1000.0
    )
    assert summary["total_energy_wh"] == pytest.approx(
        expected_total_energy_wh
    )
    assert summary["annual_energy_wh"] is None
    assert summary["period_start_time"] == "2026-03-21T10:00:00+07:00"
    assert summary["period_end_time"] == "2026-03-21T13:00:00+07:00"
    assert summary["period_duration_hours"] == pytest.approx(3.0)
    assert summary["capacity_factor_basis"] == (
        "installed_dc_nameplate_over_executed_period"
    )
    assert summary["peak_dc_power_w"] >= 0.0
    assert summary["peak_ac_power_w"] >= 0.0
    assert summary["shading_energy_loss_wh"] == 0.0

    manifest = run["reproducibility_manifest"]
    assert manifest["native_weather_resolution_seconds"] == 3600
    assert manifest["working_weather_resolution_seconds"] == 3600
    assert manifest["representative_time_policy"] == "interval_midpoint"
    assert manifest["output_configuration"] == {
        "standard_timeseries": True,
        "format": "parquet",
    }
    assert manifest["numerical_options"]["thermal"] == {
        "u_c_w_m2k": 20.0,
        "u_v_w_m2k_per_ms": 0.0,
    }
    assert manifest["result_logical_content_sha256"] == reference[
        "logical_content_sha256"
    ]
    assert len(manifest["input_hashes"]["engine_version_sha256"]) == 64

    with pytest.raises(FileExistsError, match="immutable"):
        run_canonical_simulation(
            project_revision,
            configuration,
            revision_store=store,
            output_directory=tmp_path,
            simulation_run_id="run-phase38e-001",
            engine_version="opensimpv-test@phase38e",
            executed_at="2026-09-23T12:00:00Z",
        )


def test_identical_pinned_inputs_reproduce_input_and_logical_result_hash(tmp_path):
    project_revision, configuration, store = _inputs()

    first = run_canonical_simulation(
        project_revision,
        configuration,
        revision_store=store,
        output_directory=tmp_path,
        simulation_run_id="run-phase38e-a",
        engine_version="opensimpv-test@phase38e",
        executed_at="2026-09-23T12:00:00Z",
    )
    second = run_canonical_simulation(
        project_revision,
        configuration,
        revision_store=store,
        output_directory=tmp_path,
        simulation_run_id="run-phase38e-b",
        engine_version="opensimpv-test@phase38e",
        executed_at="2026-09-23T12:00:00Z",
    )

    assert first.simulation_run["input_hash"] == second.simulation_run["input_hash"]
    assert (
        first.simulation_run["result_reference"]["logical_content_sha256"]
        == second.simulation_run["result_reference"]["logical_content_sha256"]
    )
    pd.testing.assert_frame_equal(
        first.standard_timeseries,
        second.standard_timeseries,
    )


def test_engine_version_changes_execution_identity_but_not_logical_result(tmp_path):
    project_revision, configuration, store = _inputs()

    first = run_canonical_simulation(
        project_revision,
        configuration,
        revision_store=store,
        output_directory=tmp_path,
        simulation_run_id="run-phase38e-engine-a",
        engine_version="opensimpv-test@engine-a",
        executed_at="2026-09-23T12:00:00Z",
    )
    second = run_canonical_simulation(
        project_revision,
        configuration,
        revision_store=store,
        output_directory=tmp_path,
        simulation_run_id="run-phase38e-engine-b",
        engine_version="opensimpv-test@engine-b",
        executed_at="2026-09-23T12:00:00Z",
    )

    assert first.simulation_run["input_hash"] != second.simulation_run["input_hash"]
    assert (
        first.simulation_run["reproducibility_manifest"]["input_hashes"][
            "engine_version_sha256"
        ]
        != second.simulation_run["reproducibility_manifest"]["input_hashes"][
            "engine_version_sha256"
        ]
    )
    assert (
        first.simulation_run["result_reference"]["logical_content_sha256"]
        == second.simulation_run["result_reference"]["logical_content_sha256"]
    )


def test_missing_required_scene_revision_returns_failed_run_without_physics(tmp_path):
    project_revision, configuration, store = _inputs()
    broken = CanonicalRevisionStore(
        scene_revisions={},
        electrical_revisions=store.electrical_revisions,
        weather_revisions=store.weather_revisions,
        component_revisions=store.component_revisions,
    )

    result = run_canonical_simulation(
        project_revision,
        configuration,
        revision_store=broken,
        output_directory=tmp_path,
        simulation_run_id="run-phase38e-missing-scene",
        engine_version="opensimpv-test@phase38e",
        executed_at="2026-09-23T12:00:00Z",
    )

    assert result.simulation_run["status"] == "failed"
    assert result.backend_result is None
    assert result.standard_timeseries is None
    assert result.simulation_run["result_reference"] is None
    assert any(
        item["rule_id"] == "SIMULATION_REQUIRED_REVISION_NOT_FOUND"
        and item["severity"] == "blocking_error"
        for item in result.simulation_run["validation_findings"]
    )
    assert (
        tmp_path
        / "run-phase38e-missing-scene"
        / "simulation-run.json"
    ).exists()
    assert not (
        tmp_path
        / "run-phase38e-missing-scene"
        / "timeseries.parquet"
    ).exists()
    _validate_run(result.simulation_run)


def test_solar_aware_weather_error_creates_blocking_gate_and_preserves_source(tmp_path):
    project_revision, configuration, store = _inputs()
    weather = next(iter(store.weather_revisions.values())).copy()
    original = weather.series.copy(deep=True)
    weather.series.loc[weather.series.index[1], "dni_w_m2"] = 2000.0

    broken = CanonicalRevisionStore(
        scene_revisions=store.scene_revisions,
        electrical_revisions=store.electrical_revisions,
        weather_revisions={weather.dataset["revision_id"]: weather},
        component_revisions=store.component_revisions,
    )

    result = run_canonical_simulation(
        project_revision,
        configuration,
        revision_store=broken,
        output_directory=tmp_path,
        simulation_run_id="run-phase38e-weather-block",
        engine_version="opensimpv-test@phase38e",
        executed_at="2026-09-23T12:00:00Z",
    )

    rules = {
        item["rule_id"]
        for item in result.simulation_run["validation_findings"]
    }
    assert result.simulation_run["status"] == "failed"
    assert "WX_SOLAR_DNI_ABOVE_PHYSICAL_LIMIT" in rules, [
        (
            item["rule_id"],
            item["entity_id"],
            item["message"],
            item["context"],
        )
        for item in result.simulation_run["validation_findings"]
    ]
    assert "SIMULATION_WEATHER_QC_FAILED" in rules
    assert result.backend_result is None

    # QC is non-destructive. The store's weather retains exactly the caller's values.
    expected = original.copy(deep=True)
    expected.loc[expected.index[1], "dni_w_m2"] = 2000.0
    pd.testing.assert_frame_equal(weather.series, expected)


def test_unsupported_shaded_configuration_blocks_instead_of_flattening(tmp_path):
    project_revision, configuration, store = _inputs()
    configuration = json.loads(json.dumps(configuration))
    configuration["shading_configuration"]["beam_method"] = "near_shading"

    result = run_canonical_simulation(
        project_revision,
        configuration,
        revision_store=store,
        output_directory=tmp_path,
        simulation_run_id="run-phase38e-shading-block",
        engine_version="opensimpv-test@phase38e",
        executed_at="2026-09-23T12:00:00Z",
    )

    assert result.simulation_run["status"] == "failed"
    assert any(
        item["rule_id"] == "SIMULATION_SCOPE_UNSHADED_ONLY"
        for item in result.simulation_run["validation_findings"]
    )


def test_output_configuration_is_explicit_and_fail_closed(tmp_path):
    project_revision, configuration, store = _inputs()
    configuration = json.loads(json.dumps(configuration))
    configuration["output_configuration"] = {"format": "csv"}

    result = run_canonical_simulation(
        project_revision,
        configuration,
        revision_store=store,
        output_directory=tmp_path,
        simulation_run_id="run-phase38e-output-block",
        engine_version="opensimpv-test@phase38e",
        executed_at="2026-09-23T12:00:00Z",
    )

    assert result.simulation_run["status"] == "failed"
    assert any(
        item["rule_id"] == "SIMULATION_OUTPUT_CONFIGURATION_UNSUPPORTED"
        for item in result.simulation_run["validation_findings"]
    )


def test_configuration_weather_revision_must_match_project_revision(tmp_path):
    project_revision, configuration, store = _inputs()
    configuration = json.loads(json.dumps(configuration))
    configuration["weather_dataset_revision_id"] = "wx-other-r1"

    result = run_canonical_simulation(
        project_revision,
        configuration,
        revision_store=store,
        output_directory=tmp_path,
        simulation_run_id="run-phase38e-weather-mismatch",
        engine_version="opensimpv-test@phase38e",
        executed_at="2026-09-23T12:00:00Z",
    )

    assert result.simulation_run["status"] == "failed"
    assert any(
        item["rule_id"] == "SIMULATION_WEATHER_REVISION_MISMATCH"
        for item in result.simulation_run["validation_findings"]
    )
