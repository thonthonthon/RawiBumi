import json
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from components.candidates import build_inverter_candidate, build_module_candidate
from components.ond import parse_ond_text
from components.ond.mapper import map_ond
from components.pan import parse_pan_text
from components.pan.mapper import map_pan
from components.validation import inverter_capabilities, validate_inverter
from electrical.topology import (
    ElectricalTopologyEditorSession,
    new_electrical_design,
)
from engine.inverter import INVERTER_VOLTAGE_DEPENDENT
from engine.irradiance import POA_ISOTROPIC
from engine.module import MODULE_PVSYST_SDM
from engine.optical import IAM_NONE
from engine.simulation import (
    build_design_revision_store,
    build_project_revision_from_design,
    build_simulation_configuration_from_design,
    run_canonical_simulation,
    run_validated_design_simulation,
)
from engine.simulation.artifacts import canonical_object_sha256
from engine.solar import SOLAR_POSITION_NREL_SPA
from engine.thermal import THERMAL_PVSYST
from geometry.pvfield import PVFieldPackingSession
from geometry.scene import SceneEditorSession
from validation.engineering import (
    ENGINEERING_RULE_SET_ID,
    validate_engineering_design,
)
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
        candidate_id="cand-phase48-module",
        module_definition_id="mod-phase48-module",
        revision_id="mod-phase48-module-r1",
        source_id="src-phase48-module",
    )
    assert candidate["definition_schema_ready"] is True
    return candidate["canonical_data"]


def _inverter_definition():
    """Build a fully design-valid synthetic inverter for the Phase-4.8 gate.

    The existing Huawei OND fixture is intentionally missing a verified MPPT
    current limit and nominal frequency, so it is suitable for yield/runtime
    tests but not for a Phase-4 engineering-valid reference project.  This
    fixture reuses its executable voltage-dependent efficiency curves only,
    while all design-limit values below are explicitly synthetic test data.
    """
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
        candidate_id="cand-phase48-efficiency-source",
        inverter_definition_id="inv-phase48-efficiency-source",
        revision_id="inv-phase48-efficiency-source-r1",
        source_id="src-phase48-efficiency-source",
    )
    source = candidate["canonical_data"]

    inverter = deepcopy(source)
    inverter["inverter_definition_id"] = "inv-phase48-reference"
    inverter["revision_id"] = "inv-phase48-reference-r1"
    inverter["manufacturer"] = "OpenSIMPV Synthetic"
    inverter["model"] = "PHASE48-REF-100K"
    inverter["verification_state"] = "auto_validated"
    inverter["source_ids"] = ["src-phase48-synthetic-reference"]

    inverter["ac_limits"]["nominal_frequency_hz"] = 50.0
    inverter["dc_limits"]["max_dc_current_a"] = 320.0
    inverter["dc_limits"]["max_dc_short_circuit_current_a"] = 400.0
    inverter["mppt_template"]["max_operating_current_a"] = 32.0
    inverter["mppt_template"]["max_short_circuit_current_a"] = 40.0

    # Keep the voltage-domain and efficiency curves from the executable source
    # fixture, but do not represent the synthetic current/frequency limits as
    # Huawei/manufacturer-backed data.
    inverter.setdefault("metadata", {})["phase48_reference_fixture"] = {
        "identity": "synthetic",
        "efficiency_curve_basis": "existing executable test fixture",
        "design_current_limits_basis": "synthetic Phase-4.8 regression values",
        "nominal_frequency_basis": "synthetic Phase-4.8 regression value",
    }

    findings = validate_inverter(inverter)
    blocking = [
        item
        for item in findings
        if item["severity"] in {"error", "blocking_error"}
    ]
    assert not blocking, blocking
    inverter["capability_flags"] = inverter_capabilities(
        inverter, findings
    )
    assert inverter["capability_flags"]["mppt_design_ready"] is True
    assert inverter["capability_flags"]["basic_design_ready"] is True
    assert inverter["capability_flags"]["basic_yield_ready"] is True
    assert inverter["capability_flags"]["detailed_efficiency_ready"] is True
    return inverter


def _weather():
    index = pd.date_range(
        "2026-03-21T10:00:00+07:00",
        periods=3,
        freq="h",
    )
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
        weather_dataset_id="wx-phase48",
        revision_id="wx-phase48-r1",
        name="Phase 4.8 design integration weather",
        site_id="site-phase48",
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


def _phase4_design(module, inverter):
    base = json.loads(
        (
            ROOT
            / "tests/fixtures/phase42/simple-survey-base.scene.json"
        ).read_text(encoding="utf-8")
    )
    base["project_id"] = "proj-phase48"
    base["scene_id"] = "scene-phase48"
    base["revision_id"] = "scene-phase48-base"

    editor = SceneEditorSession(base)
    editor.draw_rectangle(
        surface_id="roof-001",
        scene_object_id="obj-roof-001",
        name="Phase 4.8 flat roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=30.0,
        height_m=10.0,
        base_elevation_m=8.0,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    scene = editor.scene

    packing = PVFieldPackingSession(
        scene,
        {module["revision_id"]: module},
    )
    packing.create_field(
        pv_field_id="field-001",
        name="Phase 4.8 reference field",
        support_surface_id="roof-001",
        module_definition_revision_id=module["revision_id"],
        orientation="portrait",
        azimuth_deg=0.0,
        tilt_deg=0.0,
        module_gap_x_m=0.02,
        module_gap_y_m=0.02,
        row_pitch_m=2.5,
        mounting_height_m=0.2,
        perimeter_setback_m=0.0,
        obstacle_setback_m=0.0,
        requested_row_count=1,
        requested_modules_per_row=18,
    )
    packing.fill_area("field-001")
    assert len(packing.scene["module_instances"]) == 18

    scene_commit = SceneEditorSession(packing.scene).commit_revision(
        revision_id="scene-phase48-r1",
        revision_number=1,
        change_summary="Phase 4.8 design-generated scene.",
        created_by="phase48-test",
        created_at="2026-09-24T02:00:00Z",
    )

    electrical = new_electrical_design(
        project_id="proj-phase48",
        electrical_revision_id="elec-phase48-draft",
        pcc_id="pcc-001",
        revision_number=1,
        project_revision_id="proj-phase48-r1",
    )
    topology = ElectricalTopologyEditorSession(
        scene_commit,
        electrical,
        project_revision_id="proj-phase48-r1",
        module_definitions={module["revision_id"]: module},
        inverter_definitions={inverter["revision_id"]: inverter},
    )
    inv = topology.add_inverter(
        inverter_instance_id="inv-inst-001",
        inverter_definition_revision_id=inverter["revision_id"],
        name="INV-01",
    )
    module_ids = [
        item["module_instance_id"]
        for item in sorted(
            scene_commit["module_instances"],
            key=lambda item: (
                int(item["row_index"]),
                int(item["column_index"]),
            ),
        )
    ]
    topology.create_string(
        string_id="string-001",
        module_instance_ids=module_ids,
        name="S01",
    )
    topology.assign_strings_to_mppt(
        ["string-001"],
        mppt_instance_id=inv["mppt_instance_ids"][0],
    )
    electrical_commit = topology.commit_revision(
        electrical_revision_id="elec-phase48-r1",
        revision_number=1,
        change_summary="Phase 4.8 design-generated topology.",
        created_by="phase48-test",
        created_at="2026-09-24T02:00:00Z",
    )
    return scene_commit, electrical_commit


def _validation_configuration():
    return {
        "schema_name": "EngineeringValidationConfiguration",
        "schema_version": "0.1",
        "minimum_cell_temperature_c": -10.0,
        "maximum_cell_temperature_c": 70.0,
        "design_irradiance_w_m2": 1000.0,
        "orientation_tolerance_deg": 0.1,
        "dc_ac_ratio_warning_min": None,
        "dc_ac_ratio_warning_max": None,
        "temperature_model_policy": "detailed_then_linear_fallback",
        "fallback_voltage_uncertainty_fraction": 0.05,
        "fallback_current_uncertainty_fraction": 0.05,
    }


def _simulation_configuration(project_revision):
    return build_simulation_configuration_from_design(
        project_revision,
        simulation_configuration_id="simcfg-phase48-001",
        simulation_timestep_seconds=3600,
        name="Phase 4.8 design-to-simulation reference",
        model_selections={
            "solar_position": SOLAR_POSITION_NREL_SPA,
            "transposition": POA_ISOTROPIC,
            "temperature": THERMAL_PVSYST,
            "module_electrical": MODULE_PVSYST_SDM,
            "inverter": INVERTER_VOLTAGE_DEPENDENT,
            "iam": IAM_NONE,
        },
        loss_model_ids=["loss_ledger.electrical_chain.v0.1"],
        shading_configuration={
            "beam_method": "none",
            "diffuse_method": "none",
            "albedo_method": "support_surface",
            "fidelity_level": "engineering",
            "sun_position_resolution_seconds": None,
            "electrical_shading_method": None,
        },
        numerical_options={
            "albedo": 0.20,
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
        output_configuration={
            "standard_timeseries": True,
            "format": "parquet",
        },
    )


def _inputs():
    module = _module_definition()
    inverter = _inverter_definition()
    scene, electrical = _phase4_design(module, inverter)
    weather = _weather()

    project_revision = build_project_revision_from_design(
        scene,
        electrical,
        project_revision_id="proj-phase48-r1",
        revision_number=1,
        weather_dataset_revision_id=weather.dataset["revision_id"],
        change_summary="Phase 4.8 fully design-authored project revision.",
    )
    configuration = _simulation_configuration(project_revision)
    components = {
        module["revision_id"]: module,
        inverter["revision_id"]: inverter,
    }
    store = build_design_revision_store(
        scene,
        electrical,
        weather,
        components,
    )
    validation = validate_engineering_design(
        scene,
        electrical,
        project_revision_id=project_revision["project_revision_id"],
        component_revisions=components,
        configuration=_validation_configuration(),
        design_validation_report_id="validation-phase48-r1",
        generated_at="2026-09-24T02:00:00Z",
    )
    return (
        module,
        inverter,
        scene,
        electrical,
        weather,
        project_revision,
        configuration,
        store,
        validation,
    )


def test_phase4_design_matches_equivalent_direct_canonical_simulation(tmp_path):
    (
        _module,
        _inverter,
        _scene,
        _electrical,
        _weather,
        project_revision,
        configuration,
        store,
        validation,
    ) = _inputs()

    assert validation["rule_set_id"] == ENGINEERING_RULE_SET_ID
    assert validation["blocking_simulation"] is False

    integrated = run_validated_design_simulation(
        project_revision,
        configuration,
        revision_store=store,
        design_validation_report=validation,
        output_directory=tmp_path,
        simulation_run_id="run-phase48-integrated",
        engine_version="opensimpv-test@phase48",
        executed_at="2026-09-24T02:05:00Z",
    )
    direct = run_canonical_simulation(
        project_revision,
        configuration,
        revision_store=store,
        output_directory=tmp_path,
        simulation_run_id="run-phase48-direct",
        engine_version="opensimpv-test@phase48",
        executed_at="2026-09-24T02:05:00Z",
    )

    assert integrated.simulation_run["status"] in {
        "completed",
        "completed_with_warnings",
    }
    assert direct.simulation_run["status"] in {
        "completed",
        "completed_with_warnings",
    }

    assert (
        integrated.simulation_run["input_hash"]
        == direct.simulation_run["input_hash"]
    )
    assert (
        integrated.simulation_run["result_reference"][
            "logical_content_sha256"
        ]
        == direct.simulation_run["result_reference"][
            "logical_content_sha256"
        ]
    )
    pd.testing.assert_frame_equal(
        integrated.standard_timeseries,
        direct.standard_timeseries,
    )
    assert integrated.summary_result["total_energy_wh"] == pytest.approx(
        direct.summary_result["total_energy_wh"]
    )

    run = integrated.simulation_run
    assert run["design_validation_report_id"] == "validation-phase48-r1"
    assert run["design_validation_rule_set_id"] == ENGINEERING_RULE_SET_ID
    assert len(run["design_validation_report_sha256"]) == 64
    manifest = run["reproducibility_manifest"]
    assert (
        manifest["design_validation_report_sha256"]
        == run["design_validation_report_sha256"]
    )
    assert (
        tmp_path
        / "run-phase48-integrated"
        / "design-validation-report.json"
    ).exists()


def test_blocking_design_validation_stops_before_physics(tmp_path):
    (
        _module,
        _inverter,
        _scene,
        _electrical,
        _weather,
        project_revision,
        configuration,
        store,
        validation,
    ) = _inputs()

    blocked = deepcopy(validation)
    blocked["status"] = "invalid"
    blocked["blocking_simulation"] = True
    blocked["finding_counts"]["blocking_error"] += 1
    blocked["metadata"]["classification_counts"]["INVALID"] += 1
    blocked["findings"].append(
        {
            "schema_name": "ValidationFinding",
            "schema_version": "0.1",
            "finding_id": "validation-phase48-r1:manual-blocker",
            "project_revision_id": "proj-phase48-r1",
            "entity_id": "string-001",
            "rule_id": "PHASE48_TEST_BLOCKER",
            "severity": "blocking_error",
            "classification": "INVALID",
            "category": "electrical_voltage",
            "message": "Synthetic blocking design finding.",
            "measured_value": 1001.0,
            "limit_value": 1000.0,
            "unit": "V",
            "context": {},
            "generated_at": "2026-09-24T02:00:00Z",
            "resolved_at": None,
            "resolution_note": None,
        }
    )

    result = run_validated_design_simulation(
        project_revision,
        configuration,
        revision_store=store,
        design_validation_report=blocked,
        output_directory=tmp_path,
        simulation_run_id="run-phase48-blocked",
        engine_version="opensimpv-test@phase48",
        executed_at="2026-09-24T02:05:00Z",
    )

    assert result.simulation_run["status"] == "failed"
    assert result.backend_result is None
    assert result.standard_timeseries is None
    assert result.simulation_run["result_reference"] is None
    assert {
        item["rule_id"]
        for item in result.simulation_run["validation_findings"]
    } >= {
        "PHASE48_TEST_BLOCKER",
        "DESIGN_VALIDATION_BLOCKS_SIMULATION",
    }


def test_stale_validation_report_cannot_gate_new_scene_revision(tmp_path):
    (
        _module,
        _inverter,
        scene,
        _electrical,
        _weather,
        project_revision,
        configuration,
        store,
        validation,
    ) = _inputs()

    stale = deepcopy(validation)
    stale["scene_revision_id"] = "scene-phase48-older"

    result = run_validated_design_simulation(
        project_revision,
        configuration,
        revision_store=store,
        design_validation_report=stale,
        output_directory=tmp_path,
        simulation_run_id="run-phase48-stale-validation",
        engine_version="opensimpv-test@phase48",
        executed_at="2026-09-24T02:05:00Z",
    )

    assert result.simulation_run["status"] == "failed"
    assert result.backend_result is None
    assert "DESIGN_VALIDATION_REPORT_REVISION_MISMATCH" in {
        item["rule_id"]
        for item in result.simulation_run["validation_findings"]
    }
    assert result.simulation_run["scene_revision_id"] == scene["revision_id"]


def test_ui_workspace_state_is_not_part_of_simulation_identity():
    (
        _module,
        _inverter,
        _scene,
        _electrical,
        _weather,
        project_revision,
        configuration,
        _store,
        _validation,
    ) = _inputs()

    workspace_a = {
        "selection": ["module-a"],
        "zoom": 12.0,
        "active_tool": "select",
    }
    workspace_b = {
        "selection": ["module-z"],
        "zoom": 500.0,
        "active_tool": "measure",
    }
    assert workspace_a != workspace_b

    first = _simulation_configuration(project_revision)
    second = _simulation_configuration(project_revision)

    assert first == second == configuration
    assert canonical_object_sha256(first) == canonical_object_sha256(second)
    assert "workspace" not in json.dumps(first).lower()
