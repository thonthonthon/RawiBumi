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
from electrical.topology import ElectricalTopologyEditorSession, new_electrical_design
from engine.inverter import INVERTER_VOLTAGE_DEPENDENT
from engine.irradiance import POA_ISOTROPIC
from engine.module import MODULE_PVSYST_SDM
from engine.optical import IAM_NONE
from engine.simulation import (
    build_design_revision_store,
    build_project_revision_from_design,
    build_simulation_configuration_from_design,
    load_design_state_package,
    persist_design_state_package,
    run_validated_design_simulation,
)
from engine.simulation.artifacts import canonical_object_sha256
from engine.solar import SOLAR_POSITION_NREL_SPA
from engine.thermal import THERMAL_PVSYST
from geometry.pvfield import PVFieldPackingSession
from geometry.scene import SceneEditorSession
from validation.engineering import validate_engineering_design
from weather.core import build_time_semantics, build_weather_dataset


ROOT = Path(__file__).resolve().parents[2]
CREATED_AT = "2026-09-24T06:00:00Z"


def _module_definition():
    mapping = map_pan(
        parse_pan_text(
            (
                ROOT
                / "tests/fixtures/panond/manufacturer/"
                "JKM550M-72HL4-V_SGS_6079M3.PAN"
            ).read_text(encoding="utf-8")
        )
    )
    candidate = build_module_candidate(
        mapping,
        candidate_id="cand-phase49c-module",
        module_definition_id="mod-phase49c-jkm550",
        revision_id="mod-phase49c-jkm550-r1",
        source_id="src-phase49c-jkm550-pan",
    )
    assert candidate["definition_schema_ready"] is True
    return candidate["canonical_data"]


def _inverter_definition():
    mapping = map_ond(
        parse_ond_text(
            (
                ROOT
                / "tests/fixtures/panond/manufacturer/"
                "Huawei_Sun2000_100KTL_M1.OND"
            ).read_text(encoding="utf-8")
        )
    )
    candidate = build_inverter_candidate(
        mapping,
        candidate_id="cand-phase49c-inverter-source",
        inverter_definition_id="inv-phase49c-source",
        revision_id="inv-phase49c-source-r1",
        source_id="src-phase49c-huawei-ond",
    )
    inverter = deepcopy(candidate["canonical_data"])
    inverter["inverter_definition_id"] = "inv-phase49c-reference"
    inverter["revision_id"] = "inv-phase49c-reference-r1"
    inverter["manufacturer"] = "RawiBumi Reference Overlay"
    inverter["model"] = "SUN2000-100KTL-M1 / Phase49C design overlay"
    inverter["verification_state"] = "auto_validated"
    inverter["source_ids"] = [
        "src-phase49c-huawei-ond",
        "src-phase49c-design-overlay",
    ]
    inverter["ac_limits"]["nominal_frequency_hz"] = 50.0
    inverter["dc_limits"]["max_dc_current_a"] = 320.0
    inverter["dc_limits"]["max_dc_short_circuit_current_a"] = 400.0
    inverter["mppt_template"]["max_operating_current_a"] = 32.0
    inverter["mppt_template"]["max_short_circuit_current_a"] = 40.0
    inverter.setdefault("metadata", {})["phase49c_reference_overlay"] = {
        "identity_and_efficiency_basis": "manufacturer OND fixture",
        "design_current_limits_basis": "synthetic regression-only overlay",
        "nominal_frequency_basis": "synthetic regression-only overlay",
        "not_claimed_as_pvsyst_source_topology": True,
    }
    findings = validate_inverter(inverter)
    blocking = [
        item
        for item in findings
        if item["severity"] in {"error", "blocking_error"}
    ]
    assert not blocking, blocking
    inverter["capability_flags"] = inverter_capabilities(inverter, findings)
    assert inverter["capability_flags"]["mppt_design_ready"] is True
    assert inverter["capability_flags"]["basic_yield_ready"] is True
    return inverter


def _weather(project_id):
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
        weather_dataset_id=f"wx-{project_id}",
        revision_id=f"wx-{project_id}-r1",
        name=f"{project_id} Phase 4.9C reference weather",
        site_id=f"site-{project_id}",
        timezone="UTC+07:00",
        native_resolution_seconds=3600,
        source_format="synthetic_reference",
        source_timestamp_convention="interval_start",
        location={
            "latitude_deg": -6.4245,
            "longitude_deg": 106.8307,
            "elevation_m": 82.0,
        },
        native_series_origin="provider_generated",
        series_origin="provider_generated",
        time_semantics=semantics,
    )


def _base_scene(project_id):
    scene = json.loads(
        (
            ROOT / "tests/fixtures/phase42/simple-survey-base.scene.json"
        ).read_text(encoding="utf-8")
    )
    scene["project_id"] = project_id
    scene["scene_id"] = f"scene-{project_id}"
    scene["revision_id"] = f"scene-{project_id}-base"
    scene["coordinate_system_id"] = f"enu-{project_id}"
    scene["map_layer_configuration"] = {
        "schema_name": "MapLayerConfiguration",
        "schema_version": "0.1",
        "map_configuration_id": f"map-{project_id}",
        "engineering_geometry_authority": "local_metric",
        "map_measurement_role": "context_only",
        "providers": [],
        "layers": [
            {
                "layer_id": "engineering-reference-grid",
                "layer_type": "engineering_grid",
                "provider_id": None,
            }
        ],
    }
    return scene


def _add_field(
    packing,
    *,
    field_id,
    surface_id,
    module_revision_id,
    tilt_deg=0.0,
    azimuth_deg=0.0,
    exclusion_rules=None,
):
    packing.create_field(
        pv_field_id=field_id,
        name=field_id,
        support_surface_id=surface_id,
        module_definition_revision_id=module_revision_id,
        orientation="portrait",
        azimuth_deg=azimuth_deg,
        tilt_deg=tilt_deg,
        module_gap_x_m=0.02,
        module_gap_y_m=0.02,
        row_pitch_m=2.5,
        mounting_height_m=0.2,
        perimeter_setback_m=0.0,
        obstacle_setback_m=0.0,
        exclusion_rules=exclusion_rules,
        requested_row_count=1,
        requested_modules_per_row=18,
    )
    result = packing.fill_area(field_id)
    assert result["module_count"] == 18


def _scene_r1(module):
    project_id = "p49c-r1"
    editor = SceneEditorSession(_base_scene(project_id))
    editor.draw_rectangle(
        surface_id="roof-r1",
        scene_object_id="obj-roof-r1",
        name="R1 simple flat rooftop",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=25.0,
        height_m=5.0,
        base_elevation_m=8.0,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    packing = PVFieldPackingSession(
        editor.scene, {module["revision_id"]: module}
    )
    _add_field(
        packing,
        field_id="field-r1",
        surface_id="roof-r1",
        module_revision_id=module["revision_id"],
    )
    return project_id, packing.scene


def _scene_r2(module):
    project_id = "p49c-r2"
    editor = SceneEditorSession(_base_scene(project_id))
    for index, y in enumerate((0.0, 10.0), start=1):
        editor.draw_rectangle(
            surface_id=f"roof-r2-{index}",
            scene_object_id=f"obj-roof-r2-{index}",
            name=f"R2 roof {index}",
            surface_type="flat_roof",
            origin_x_m=0.0,
            origin_y_m=y,
            width_m=25.0,
            height_m=5.0,
            base_elevation_m=8.0 + index,
            usable_for_pv=True,
            geometry_source="field_measurement",
        )
    packing = PVFieldPackingSession(
        editor.scene, {module["revision_id"]: module}
    )
    for index in (1, 2):
        _add_field(
            packing,
            field_id=f"field-r2-{index}",
            surface_id=f"roof-r2-{index}",
            module_revision_id=module["revision_id"],
        )
    return project_id, packing.scene


def _scene_r3(module):
    project_id = "p49c-r3"
    editor = SceneEditorSession(_base_scene(project_id))
    editor.draw_rectangle(
        surface_id="ground-r3",
        scene_object_id="obj-ground-r3",
        name="R3 rectangular ground-mounted site",
        surface_type="ground",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=25.0,
        height_m=5.0,
        base_elevation_m=0.0,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    packing = PVFieldPackingSession(
        editor.scene, {module["revision_id"]: module}
    )
    _add_field(
        packing,
        field_id="field-r3",
        surface_id="ground-r3",
        module_revision_id=module["revision_id"],
        tilt_deg=20.0,
    )
    return project_id, packing.scene


def _scene_r4(module):
    """Reconstruct the Phase-4.9B VC5 table/obstacle geometry exactly."""
    project_id = "p49c-r4"
    editor = SceneEditorSession(_base_scene(project_id))
    table_x = (0.0, 23.0)
    table_y = (8.0, 11.0, 14.0, 17.0, 20.0, 23.0)
    table_width = 20.752
    table_depth = 2.278
    index = 0
    for y in table_y:
        for x in table_x:
            index += 1
            editor.draw_rectangle(
                surface_id=f"vc5-table-{index:02d}",
                scene_object_id=f"obj-vc5-table-{index:02d}",
                name=f"VC5 source table {index:02d}",
                surface_type="custom_plane",
                origin_x_m=x,
                origin_y_m=y,
                width_m=table_width,
                height_m=table_depth,
                base_elevation_m=0.0,
                usable_for_pv=True,
                geometry_source="imported_geometry",
            )
    editor.draw_box_obstacle(
        obstacle_id="vc5-obstacle-north",
        scene_object_id="obj-vc5-obstacle-north",
        name="VC5 north obstacle",
        origin_x_m=-8.256538,
        origin_y_m=-5.0,
        width_m=40.0,
        depth_m=10.0,
        base_elevation_m=0.0,
        height_m=5.0,
        geometry_source="imported_geometry",
    )
    editor.draw_box_obstacle(
        obstacle_id="vc5-obstacle-south",
        scene_object_id="obj-vc5-obstacle-south",
        name="VC5 south obstacle",
        origin_x_m=-8.24263,
        origin_y_m=24.358715,
        width_m=40.0,
        depth_m=10.0,
        base_elevation_m=0.0,
        height_m=5.0,
        geometry_source="imported_geometry",
    )
    packing = PVFieldPackingSession(
        editor.scene, {module["revision_id"]: module}
    )
    no_obstacle_clearance = {
        "use_scene_exclusion_surfaces": True,
        "surface_types": ["exclusion_area", "walkway"],
        "use_scene_obstacles": False,
        "surface_ids": [],
        "obstacle_ids": [],
    }
    for index in range(1, 13):
        _add_field(
            packing,
            field_id=f"field-r4-{index:02d}",
            surface_id=f"vc5-table-{index:02d}",
            module_revision_id=module["revision_id"],
            tilt_deg=20.0,
            exclusion_rules=no_obstacle_clearance,
        )
    assert len(packing.scene["module_instances"]) == 216
    return project_id, packing.scene


def _scene_r5(module):
    project_id = "p49c-r5"
    editor = SceneEditorSession(_base_scene(project_id))
    surfaces = (
        (1, 0.0, 0.0, 25.0, 5.0, 0.0),
        (2, 0.0, 10.0, 5.0, 25.0, 90.0),
    )
    for index, x, y, width, height, azimuth in surfaces:
        editor.draw_rectangle(
            surface_id=f"roof-r5-{index}",
            scene_object_id=f"obj-roof-r5-{index}",
            name=f"R5 orientation {azimuth:.0f}",
            surface_type="flat_roof",
            origin_x_m=x,
            origin_y_m=y,
            width_m=width,
            height_m=height,
            base_elevation_m=8.0,
            usable_for_pv=True,
            geometry_source="field_measurement",
        )
    packing = PVFieldPackingSession(
        editor.scene, {module["revision_id"]: module}
    )
    _add_field(
        packing,
        field_id="field-r5-north",
        surface_id="roof-r5-1",
        module_revision_id=module["revision_id"],
        tilt_deg=20.0,
        azimuth_deg=0.0,
    )
    _add_field(
        packing,
        field_id="field-r5-east",
        surface_id="roof-r5-2",
        module_revision_id=module["revision_id"],
        tilt_deg=20.0,
        azimuth_deg=90.0,
    )
    return project_id, packing.scene


SCENE_BUILDERS = {
    "R1": _scene_r1,
    "R2": _scene_r2,
    "R3": _scene_r3,
    "R4": _scene_r4,
    "R5": _scene_r5,
}


def _committed_design(case_id, module, inverter):
    project_id, draft_scene = SCENE_BUILDERS[case_id](module)
    scene = SceneEditorSession(draft_scene).commit_revision(
        revision_id=f"scene-{project_id}-r1",
        revision_number=1,
        change_summary=f"Phase 4.9C {case_id} reference scene.",
        created_by="phase49c-test",
        created_at=CREATED_AT,
    )

    project_revision_id = f"{project_id}-revision-1"
    electrical = new_electrical_design(
        project_id=project_id,
        electrical_revision_id=f"elec-{project_id}-draft",
        pcc_id=f"pcc-{project_id}",
        revision_number=1,
        project_revision_id=project_revision_id,
    )
    topology = ElectricalTopologyEditorSession(
        scene,
        electrical,
        project_revision_id=project_revision_id,
        module_definitions={module["revision_id"]: module},
        inverter_definitions={inverter["revision_id"]: inverter},
    )
    inv = topology.add_inverter(
        inverter_instance_id=f"inv-{project_id}-1",
        inverter_definition_revision_id=inverter["revision_id"],
        name="INV-01",
    )
    modules_by_field = {}
    for item in scene["module_instances"]:
        modules_by_field.setdefault(item["pv_field_id"], []).append(item)
    for number, field_id in enumerate(sorted(modules_by_field), start=1):
        modules = sorted(
            modules_by_field[field_id],
            key=lambda item: (
                int(item["row_index"]),
                int(item["column_index"]),
            ),
        )
        ids = [item["module_instance_id"] for item in modules]
        assert len(ids) == 18
        topology.create_string(
            string_id=f"S{number:03d}",
            module_instance_ids=ids,
            name=f"String {number:03d}",
        )

    topology.assign_strings(
        [item["string_id"] for item in topology.electrical_design["strings"]],
        inverter_instance_id=inv["inverter_instance_id"],
    )
    electrical_commit = topology.commit_revision(
        electrical_revision_id=f"elec-{project_id}-r1",
        revision_number=1,
        change_summary=f"Phase 4.9C {case_id} reference topology.",
        created_by="phase49c-test",
        created_at=CREATED_AT,
    )
    return project_id, project_revision_id, scene, electrical_commit


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


def _simulation_configuration(project_revision, case_id):
    shaded_reference = case_id == "R4"
    return build_simulation_configuration_from_design(
        project_revision,
        simulation_configuration_id=f"simcfg-{case_id.lower()}",
        simulation_timestep_seconds=3600,
        name=f"Phase 4.9C {case_id}",
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
            "beam_method": (
                "pvsyst_shd_reference" if shaded_reference else "none"
            ),
            "diffuse_method": (
                "pvsyst_shd_reference" if shaded_reference else "none"
            ),
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
        output_configuration={"standard_timeseries": True, "format": "parquet"},
    )


def _reference(case_id):
    module = _module_definition()
    inverter = _inverter_definition()
    project_id, project_revision_id, scene, electrical = _committed_design(
        case_id, module, inverter
    )
    weather = _weather(project_id)
    project_revision = build_project_revision_from_design(
        scene,
        electrical,
        project_revision_id=project_revision_id,
        revision_number=1,
        weather_dataset_revision_id=weather.dataset["revision_id"],
        change_summary=f"Phase 4.9C {case_id} canonical reference project.",
    )
    configuration = _simulation_configuration(project_revision, case_id)
    components = {
        module["revision_id"]: module,
        inverter["revision_id"]: inverter,
    }
    validation = validate_engineering_design(
        scene,
        electrical,
        project_revision_id=project_revision_id,
        component_revisions=components,
        configuration=_validation_configuration(),
        design_validation_report_id=f"validation-{case_id.lower()}-r1",
        generated_at=CREATED_AT,
    )
    assert validation["blocking_simulation"] is False
    return {
        "project_id": project_id,
        "module": module,
        "inverter": inverter,
        "scene": scene,
        "electrical": electrical,
        "weather": weather,
        "components": components,
        "project_revision": project_revision,
        "configuration": configuration,
        "validation": validation,
    }


@pytest.mark.parametrize("case_id", ["R1", "R2", "R3", "R4", "R5"])
def test_phase49c_save_reload_revalidate_preserves_canonical_design(case_id, tmp_path):
    ref = _reference(case_id)

    directory = persist_design_state_package(
        tmp_path / case_id,
        scene=ref["scene"],
        electrical_design=ref["electrical"],
        project_revision=ref["project_revision"],
        simulation_configuration=ref["configuration"],
        design_validation_report=ref["validation"],
    )
    loaded = load_design_state_package(directory)

    pairs = (
        (ref["scene"], loaded.scene),
        (ref["electrical"], loaded.electrical_design),
        (ref["project_revision"], loaded.project_revision),
        (ref["configuration"], loaded.simulation_configuration),
        (ref["validation"], loaded.design_validation_report),
    )
    for original, reopened in pairs:
        assert reopened == original
        assert canonical_object_sha256(reopened) == canonical_object_sha256(original)

    revalidated = validate_engineering_design(
        loaded.scene,
        loaded.electrical_design,
        project_revision_id=loaded.project_revision["project_revision_id"],
        component_revisions=ref["components"],
        configuration=_validation_configuration(),
        design_validation_report_id=loaded.design_validation_report[
            "design_validation_report_id"
        ],
        generated_at=CREATED_AT,
    )
    assert revalidated == ref["validation"]
    assert canonical_object_sha256(revalidated) == canonical_object_sha256(
        ref["validation"]
    )

    assert loaded.manifest["ui_workspace_state_included"] is False
    assert loaded.manifest["scene_revision_id"] == ref["scene"]["revision_id"]
    assert loaded.manifest["electrical_revision_id"] == ref["electrical"][
        "electrical_revision_id"
    ]


@pytest.mark.parametrize("case_id", ["R1", "R2", "R3"])
def test_phase49c_supported_reference_projects_rerun_identically(case_id, tmp_path):
    ref = _reference(case_id)
    store = build_design_revision_store(
        ref["scene"], ref["electrical"], ref["weather"], ref["components"]
    )
    before = run_validated_design_simulation(
        ref["project_revision"],
        ref["configuration"],
        revision_store=store,
        design_validation_report=ref["validation"],
        output_directory=tmp_path / "before",
        simulation_run_id=f"run-{case_id.lower()}-before",
        engine_version="rawibumi-test@phase49c",
        executed_at="2026-09-24T06:05:00Z",
    )
    assert before.simulation_run["status"] in {
        "completed",
        "completed_with_warnings",
    }

    directory = persist_design_state_package(
        tmp_path / "saved" / case_id,
        scene=ref["scene"],
        electrical_design=ref["electrical"],
        project_revision=ref["project_revision"],
        simulation_configuration=ref["configuration"],
        design_validation_report=ref["validation"],
    )
    loaded = load_design_state_package(directory)
    store2 = build_design_revision_store(
        loaded.scene,
        loaded.electrical_design,
        ref["weather"],
        ref["components"],
    )
    after = run_validated_design_simulation(
        loaded.project_revision,
        loaded.simulation_configuration,
        revision_store=store2,
        design_validation_report=loaded.design_validation_report,
        output_directory=tmp_path / "after",
        simulation_run_id=f"run-{case_id.lower()}-after",
        engine_version="rawibumi-test@phase49c",
        executed_at="2026-09-24T06:05:00Z",
    )
    assert after.simulation_run["status"] in {
        "completed",
        "completed_with_warnings",
    }
    assert before.simulation_run["input_hash"] == after.simulation_run["input_hash"]
    assert (
        before.simulation_run["result_reference"]["logical_content_sha256"]
        == after.simulation_run["result_reference"]["logical_content_sha256"]
    )
    pd.testing.assert_frame_equal(before.standard_timeseries, after.standard_timeseries)
    before_summary = deepcopy(before.summary_result)
    after_summary = deepcopy(after.summary_result)
    assert before_summary.pop("simulation_run_id") != after_summary.pop(
        "simulation_run_id"
    )
    assert before_summary == after_summary


@pytest.mark.parametrize(
    ("case_id", "expected_rule"),
    [
        ("R4", "SIMULATION_SCOPE_UNSHADED_ONLY"),
    ],
)
def test_phase49c_out_of_scope_reference_projects_fail_explicitly_and_stably(
    case_id, expected_rule, tmp_path
):
    ref = _reference(case_id)

    def run(scene, electrical, project, configuration, validation, directory, suffix):
        store = build_design_revision_store(
            scene, electrical, ref["weather"], ref["components"]
        )
        return run_validated_design_simulation(
            project,
            configuration,
            revision_store=store,
            design_validation_report=validation,
            output_directory=directory,
            simulation_run_id=f"run-{case_id.lower()}-{suffix}",
            engine_version="rawibumi-test@phase49c",
            executed_at="2026-09-24T06:05:00Z",
        )

    before = run(
        ref["scene"],
        ref["electrical"],
        ref["project_revision"],
        ref["configuration"],
        ref["validation"],
        tmp_path / "before",
        "before",
    )
    assert before.simulation_run["status"] == "failed"
    assert before.backend_result is None
    before_rules = {
        item["rule_id"] for item in before.simulation_run["validation_findings"]
    }
    assert expected_rule in before_rules

    saved = persist_design_state_package(
        tmp_path / "saved" / case_id,
        scene=ref["scene"],
        electrical_design=ref["electrical"],
        project_revision=ref["project_revision"],
        simulation_configuration=ref["configuration"],
        design_validation_report=ref["validation"],
    )
    loaded = load_design_state_package(saved)
    after = run(
        loaded.scene,
        loaded.electrical_design,
        loaded.project_revision,
        loaded.simulation_configuration,
        loaded.design_validation_report,
        tmp_path / "after",
        "after",
    )
    assert after.simulation_run["status"] == "failed"
    assert after.backend_result is None
    after_rules = {
        item["rule_id"] for item in after.simulation_run["validation_findings"]
    }
    assert expected_rule in after_rules
    assert before_rules == after_rules


def test_phase49c_r4_preserves_exact_phase49b_vc5_geometry():
    ref = _reference("R4")
    scene = ref["scene"]

    surfaces = sorted(
        (
            round(min(point[0] for point in item["boundary_2d"]["vertices"]), 6),
            round(min(point[1] for point in item["boundary_2d"]["vertices"]), 6),
        )
        for item in scene["surfaces"]
    )
    expected_surfaces = sorted(
        (x, y)
        for y in (8.0, 11.0, 14.0, 17.0, 20.0, 23.0)
        for x in (0.0, 23.0)
    )
    assert surfaces == expected_surfaces

    obstacles = {
        item["obstacle_id"]: (
            round(min(point[0] for point in item["footprint"]["vertices"]), 6),
            round(min(point[1] for point in item["footprint"]["vertices"]), 6),
            item["dimensions"]["width_m"],
            item["dimensions"]["depth_m"],
            item["height_m"],
        )
        for item in scene["obstacles"]
    }
    assert obstacles == {
        "vc5-obstacle-north": (-8.256538, -5.0, 40.0, 10.0, 5.0),
        "vc5-obstacle-south": (-8.24263, 24.358715, 40.0, 10.0, 5.0),
    }
    assert len(scene["module_instances"]) == 216
    assert len(ref["electrical"]["strings"]) == 12


def test_phase49c_package_detects_saved_object_mutation(tmp_path):
    ref = _reference("R1")
    directory = persist_design_state_package(
        tmp_path / "tamper",
        scene=ref["scene"],
        electrical_design=ref["electrical"],
        project_revision=ref["project_revision"],
        simulation_configuration=ref["configuration"],
        design_validation_report=ref["validation"],
    )
    path = directory / "scene.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["notes"] = "mutated after save"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="object hash mismatch"):
        load_design_state_package(directory)


def test_phase49c_frozen_reference_matrix_records_closure_boundary():
    manifest = __import__("yaml").safe_load(
        (
            ROOT
            / "tests/benchmarks/phase49c_reference_projects_20260924.yaml"
        ).read_text(encoding="utf-8")
    )

    assert manifest["reference_matrix_id"] == (
        "P49C-CANONICAL-REFERENCE-PROJECTS-20260924"
    )
    assert set(manifest["cases"]) == {"R1", "R2", "R3", "R4", "R5"}
    assert {
        case_id
        for case_id, case in manifest["cases"].items()
        if case["execution_expectation"] == "supported"
    } == {"R1", "R2", "R3"}
    assert manifest["cases"]["R4"]["expected_rule_id"] == (
        "SIMULATION_SCOPE_UNSHADED_ONLY"
    )
    assert manifest["cases"]["R5"]["expected_rule_id"] == (
        "SIMULATION_SCOPE_REQUIRES_ONE_ORIENTATION"
    )
    assert manifest["phase4_closure"]["phase4_status_after_49c"] == (
        "CLOSED_FOR_CURRENT_SCOPE"
    )
    assert manifest["phase4_closure"]["unsupported_physics_remains_explicit"] is True
    assert manifest["design_state_package"]["integrity"]["fail_closed_on_mutation"] is True
