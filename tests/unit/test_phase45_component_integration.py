import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from components import (
    ComponentDesignSession,
    inverter_design_snapshot,
    module_design_snapshot,
)
from geometry.pvfield import PVFieldPackingSession
from geometry.scene import SceneEditorSession, canonical_scene_hash
from geometry.scene3d import generate_scene3d


ROOT = Path(__file__).resolve().parents[2]


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _registry():
    registry = Registry()
    directories = (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "geometry/scene3d",
        ROOT / "electrical/schema",
        ROOT / "apps/web/schema",
    )
    for directory in directories:
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def _module(
    revision_id: str,
    *,
    width: float,
    height: float,
    pmp: float = 400.0,
    voc: float = 40.0,
    isc: float = 12.0,
    vmp: float = 33.0,
    imp: float = 11.5,
    model_type: str = "pvwatts",
    max_system_voltage: float = 1500.0,
):
    return {
        "schema_name": "ModuleDefinition",
        "schema_version": "0.1",
        "module_definition_id": "mod-family-a",
        "revision_id": revision_id,
        "manufacturer": "OpenSIMPV Test",
        "model": "Family A",
        "verification_state": "auto_validated",
        "mechanical": {
            "width_m": width,
            "height_m": height,
            "thickness_m": 0.03,
            "mass_kg": 22.0,
        },
        "stc": {
            "pmp_w": pmp,
            "voc_v": voc,
            "isc_a": isc,
            "vmp_v": vmp,
            "imp_a": imp,
            "reference_irradiance_w_m2": 1000.0,
            "reference_cell_temperature_c": 25.0,
        },
        "temperature_coefficients": {
            "alpha_isc_per_c": 0.005,
            "beta_voc_per_c": -0.12,
            "gamma_pmp_per_c": -1.5,
            "coefficient_basis": "absolute",
        },
        "limits": {
            "max_system_voltage_v": max_system_voltage,
            "max_series_fuse_a": 25.0,
            "operating_temperature_min_c": -40.0,
            "operating_temperature_max_c": 85.0,
        },
        "electrical_models": [
            {
                "model_type": model_type,
                "model_version": "test-v1",
                "parameter_set": {},
                "verification_state": "auto_validated",
            }
        ],
        "capability_flags": {
            "layout_ready": True,
            "basic_yield_ready": True,
            "detailed_sdm_ready": model_type == "pvsyst_singlediode",
            "bifacial_ready": False,
            "detailed_shading_ready": False,
            "independent_iv_validated": False,
        },
    }


MODULE_R1 = _module("mod-family-a-r1", width=1.0, height=2.0)
MODULE_R2_LARGE = _module(
    "mod-family-a-r2",
    width=1.5,
    height=2.2,
    pmp=500.0,
    voc=45.0,
    isc=13.5,
    vmp=37.0,
    imp=13.0,
    model_type="pvsyst_singlediode",
)
MODULE_R2_SAME_SIZE = _module(
    "mod-family-a-r2-electrical",
    width=1.0,
    height=2.0,
    pmp=430.0,
    voc=42.0,
    isc=12.5,
    vmp=34.5,
    imp=12.0,
    model_type="pvsyst_singlediode",
)


def _inverter(
    revision_id: str,
    *,
    mppt_count: int,
    max_dc_voltage: float,
    mppt_max_voltage: float,
    mppt_current: float,
    mppt_isc: float,
    ac_power: float,
    efficiency_model: str,
):
    return {
        "schema_name": "InverterDefinition",
        "schema_version": "0.1",
        "inverter_definition_id": "inv-family-a",
        "revision_id": revision_id,
        "manufacturer": "OpenSIMPV Test",
        "model": "INV Family A",
        "inverter_type": "string",
        "phase_configuration": "three_phase",
        "verification_state": "auto_validated",
        "dc_limits": {
            "max_dc_voltage_v": max_dc_voltage,
            "nominal_dc_voltage_v": 600.0,
            "max_dc_power_w": ac_power * 1.5,
            "max_dc_current_a": mppt_current * mppt_count,
            "max_dc_short_circuit_current_a": mppt_isc * mppt_count,
        },
        "ac_limits": {
            "nominal_ac_power_w": ac_power,
            "max_ac_power_w": ac_power * 1.1,
            "nominal_ac_voltage_v": 400.0,
            "nominal_frequency_hz": 50.0,
        },
        "mppt_template": {
            "count": mppt_count,
            "min_operating_voltage_v": 180.0,
            "max_operating_voltage_v": mppt_max_voltage,
            "nominal_voltage_v": 600.0,
            "max_operating_current_a": mppt_current,
            "max_short_circuit_current_a": mppt_isc,
            "input_count_per_mppt": 2,
            "independent_inputs": True,
        },
        "efficiency_model": {
            "model_type": efficiency_model,
            "curves": [],
            "reference_metrics": {
                "max_efficiency_fraction": 0.985,
                "european_efficiency_fraction": 0.975,
                "cec_efficiency_fraction": None,
            },
        },
        "array_sizing_limits": {
            "max_pv_array_power_w": ac_power * 1.5,
            "max_pv_current_a": mppt_current * mppt_count,
        },
        "capability_flags": {
            "basic_design_ready": True,
            "mppt_design_ready": True,
            "basic_yield_ready": True,
            "detailed_efficiency_ready": efficiency_model
            != "constant",
            "derating_ready": False,
            "mppt_voltage_ready": True,
            "mppt_current_limit_ready": True,
            "array_sizing_ready": True,
        },
    }


INV_R1 = _inverter(
    "inv-family-a-r1",
    mppt_count=2,
    max_dc_voltage=1000.0,
    mppt_max_voltage=850.0,
    mppt_current=30.0,
    mppt_isc=40.0,
    ac_power=100000.0,
    efficiency_model="constant",
)
INV_R2_SMALL = _inverter(
    "inv-family-a-r2",
    mppt_count=1,
    max_dc_voltage=900.0,
    mppt_max_voltage=750.0,
    mppt_current=20.0,
    mppt_isc=30.0,
    ac_power=80000.0,
    efficiency_model="voltage_dependent_curves",
)
INV_R2_LIMITS = _inverter(
    "inv-family-a-r2-limits",
    mppt_count=2,
    max_dc_voltage=950.0,
    mppt_max_voltage=800.0,
    mppt_current=25.0,
    mppt_isc=35.0,
    ac_power=90000.0,
    efficiency_model="voltage_dependent_curves",
)


def _base_scene():
    return _load("tests/fixtures/phase42/simple-survey-base.scene.json")


def _packed_scene(
    module_definition=MODULE_R1,
    *,
    orientation="portrait",
):
    editor = SceneEditorSession(_base_scene())
    editor.draw_rectangle(
        surface_id="roof",
        scene_object_id="obj-roof",
        name="Tight roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=4.1,
        height_m=4.6,
        base_elevation_m=8.0,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    packing = PVFieldPackingSession(
        editor.scene,
        {module_definition["revision_id"]: module_definition},
    )
    packing.create_field(
        pv_field_id="field-1",
        name="Field 1",
        support_surface_id="roof",
        module_definition_revision_id=module_definition["revision_id"],
        orientation=orientation,
        azimuth_deg=0.0,
        tilt_deg=10.0,
        module_gap_x_m=0.05,
        module_gap_y_m=0.05,
        row_pitch_m=2.3,
        mounting_height_m=0.3,
        perimeter_setback_m=0.05,
    )
    packing.fill_area("field-1")
    return packing.scene


def _electrical(scene):
    module_ids = [
        item["module_instance_id"]
        for item in scene["module_instances"]
    ]
    first = module_ids[: max(1, len(module_ids) // 2)]
    second = module_ids[max(1, len(module_ids) // 2) :]
    if not second:
        second = first[-1:]

    return {
        "schema_name": "ElectricalDesignRevision",
        "schema_version": "0.1",
        "electrical_revision_id": "elec-r1",
        "project_id": "proj-ref-001",
        "inverter_instances": [
            {
                "inverter_instance_id": "inv-1",
                "project_revision_id": "proj-r1",
                "inverter_definition_revision_id": INV_R1["revision_id"],
                "name": "INV-1",
                "location": None,
                "enabled": True,
                "mppt_instance_ids": ["mppt-1", "mppt-2"],
                "ac_connection_id": None,
            }
        ],
        "mppt_instances": [
            {
                "mppt_instance_id": "mppt-1",
                "inverter_instance_id": "inv-1",
                "mppt_definition_id": "mppt-def-1",
                "index": 1,
                "connected_string_ids": ["string-1"],
                "enabled": True,
            },
            {
                "mppt_instance_id": "mppt-2",
                "inverter_instance_id": "inv-1",
                "mppt_definition_id": "mppt-def-2",
                "index": 2,
                "connected_string_ids": ["string-2"],
                "enabled": True,
            },
        ],
        "strings": [
            {
                "string_id": "string-1",
                "project_revision_id": "proj-r1",
                "name": "S1",
                "module_instance_ids": first,
                "target_mppt_instance_id": "mppt-1",
                "enabled": True,
                "polarity": "normal",
            },
            {
                "string_id": "string-2",
                "project_revision_id": "proj-r1",
                "name": "S2",
                "module_instance_ids": second,
                "target_mppt_instance_id": "mppt-2",
                "enabled": True,
                "polarity": "normal",
            },
        ],
        "connections": [],
        "pcc_definition": {"pcc_id": "pcc-1"},
    }


def _session(scene=None):
    scene = scene or _packed_scene()
    electrical = _electrical(scene)
    return ComponentDesignSession(
        scene,
        electrical_design=electrical,
        module_definitions={
            MODULE_R1["revision_id"]: MODULE_R1,
            MODULE_R2_LARGE["revision_id"]: MODULE_R2_LARGE,
            MODULE_R2_SAME_SIZE["revision_id"]: MODULE_R2_SAME_SIZE,
        },
        inverter_definitions={
            INV_R1["revision_id"]: INV_R1,
            INV_R2_SMALL["revision_id"]: INV_R2_SMALL,
            INV_R2_LIMITS["revision_id"]: INV_R2_LIMITS,
        },
    )


def _field(scene):
    return next(
        item for item in scene["pv_fields"]
        if item["pv_field_id"] == "field-1"
    )


def test_module_design_snapshot_exposes_all_design_facing_domains():
    snapshot = module_design_snapshot(MODULE_R2_LARGE)
    assert snapshot["revision_id"] == MODULE_R2_LARGE["revision_id"]
    assert snapshot["mechanical"]["width_m"] == pytest.approx(1.5)
    assert snapshot["stc"]["voc_v"] == pytest.approx(45.0)
    assert snapshot["string_design_limits"]["max_system_voltage_v"] == pytest.approx(1500.0)
    assert snapshot["available_simulation_models"][0]["model_type"] == "pvsyst_singlediode"
    assert snapshot["capability_flags"]["layout_ready"] is True


def test_inverter_snapshot_normalizes_mppt_template_and_limits():
    snapshot = inverter_design_snapshot(INV_R1)
    assert snapshot["revision_id"] == INV_R1["revision_id"]
    assert snapshot["dc_limits"]["max_dc_voltage_v"] == pytest.approx(1000.0)
    assert snapshot["mppt_count"] == 2
    assert [item["index"] for item in snapshot["mppts"]] == [1, 2]
    assert snapshot["mppts"][0]["max_operating_current_a"] == pytest.approx(30.0)
    assert snapshot["ac_limits"]["nominal_ac_power_w"] == pytest.approx(100000.0)
    assert snapshot["efficiency_model"]["model_type"] == "constant"


def test_binding_manifest_pins_exact_scene_and_inverter_revisions():
    session = _session()
    first = session.binding_manifest()
    second = session.binding_manifest()

    assert first == second
    assert first["module_bindings"][0]["revision_id"] == MODULE_R1["revision_id"]
    assert first["inverter_bindings"][0]["revision_id"] == INV_R1["revision_id"]
    assert first["module_bindings"][0]["resolved"] is True
    assert first["inverter_bindings"][0]["resolved"] is True
    assert len(first["manifest_hash"]) == 64


def test_module_revision_analysis_is_non_mutating_and_detects_geometry_consequences():
    session = _session()
    before = canonical_scene_hash(session.scene)
    before_electrical = deepcopy(session.electrical_design)

    report = session.analyze_module_revision_change(
        "field-1", MODULE_R2_LARGE["revision_id"]
    )

    assert canonical_scene_hash(session.scene) == before
    assert session.electrical_design == before_electrical
    assert report["mutation_performed"] is False
    assert report["status"] == "conflict"
    codes = {item["code"] for item in report["consequences"]}
    assert "module_module_overlap" in codes or "module_outside_support_or_setback" in codes
    assert "string_design_revalidation_required" in codes
    assert "field_rebuild_may_invalidate_string_membership" in codes
    assert report["rebuild_preview"]["available"] is True
    assert report["rebuild_preview"]["module_count_delta"] < 0


def test_same_size_module_revision_keeps_geometry_but_changes_electrical_capability():
    session = _session()
    report = session.analyze_module_revision_change(
        "field-1", MODULE_R2_SAME_SIZE["revision_id"]
    )

    codes = {item["code"] for item in report["consequences"]}
    assert report["status"] == "warning"
    assert "module_module_overlap" not in codes
    assert "module_outside_support_or_setback" not in codes
    assert "string_design_revalidation_required" in codes
    assert "simulation_capability_changed" in codes
    assert report["rebuild_preview"]["module_count_delta"] == 0


def test_keep_current_layout_is_explicit_atomic_and_does_not_move_modules():
    session = _session()
    before_scene = session.scene
    before_positions = [
        deepcopy(item["transform"])
        for item in before_scene["module_instances"]
    ]

    report = session.apply_module_revision_keep_current_layout(
        "field-1", MODULE_R2_LARGE["revision_id"]
    )
    after = session.scene
    field = _field(after)

    assert report["status"] == "conflict"
    assert [
        item["transform"] for item in after["module_instances"]
    ] == before_positions
    assert field["module_definition_revision_id"] == MODULE_R2_LARGE["revision_id"]
    assert all(
        item["module_definition_revision_id"] == MODULE_R2_LARGE["revision_id"]
        for item in after["module_instances"]
    )
    assert field["layout_status"] == "conflict"
    assert field["packing_input_hash"] is None
    assert field["metadata"]["component_revision_change"]["action"] == "apply_revision_keep_current_layout"

    assert session.undo() is True
    assert session.scene == before_scene
    assert session.redo() is True
    assert _field(session.scene)["module_definition_revision_id"] == MODULE_R2_LARGE["revision_id"]


def test_same_size_keep_layout_can_rebind_without_geometric_staleness():
    session = _session()
    before_positions = [
        deepcopy(item["transform"])
        for item in session.scene["module_instances"]
    ]
    session.apply_module_revision_keep_current_layout(
        "field-1", MODULE_R2_SAME_SIZE["revision_id"]
    )
    field = _field(session.scene)

    assert [
        item["transform"] for item in session.scene["module_instances"]
    ] == before_positions
    assert field["layout_status"] == "packed"
    assert field["packing_input_hash"] is not None


def test_apply_revision_and_rebuild_field_is_explicit_and_leaves_electrical_topology_untouched():
    session = _session()
    before_electrical = deepcopy(session.electrical_design)
    before_count = len(session.scene["module_instances"])

    result = session.apply_module_revision_and_rebuild_field(
        "field-1", MODULE_R2_LARGE["revision_id"]
    )
    after = session.scene

    assert len(after["module_instances"]) < before_count
    assert len(after["module_instances"]) == result["module_count"]
    assert _field(after)["module_definition_revision_id"] == MODULE_R2_LARGE["revision_id"]
    assert _field(after)["packing_input_hash"] == result["packing_input_hash"]
    assert session.electrical_design == before_electrical


def test_inverter_revision_analysis_detects_topology_and_limit_consequences_without_mutation():
    session = _session()
    before = deepcopy(session.electrical_design)

    report = session.analyze_inverter_revision_change(
        "inv-1", INV_R2_SMALL["revision_id"]
    )

    assert session.electrical_design == before
    assert report["status"] == "conflict"
    codes = {item["code"] for item in report["consequences"]}
    assert "inverter_mppt_topology_conflict" in codes
    assert "connected_strings_require_revalidation" in codes
    assert "ac_rating_changed" in codes
    assert "inverter_simulation_capability_changed" in codes
    assert report["topology_summary"]["proposed_mppt_count"] == 1
    assert report["topology_summary"]["automatic_topology_rebuild_available"] is False


def test_inverter_revision_same_mppt_count_still_exposes_changed_limits():
    session = _session()
    report = session.analyze_inverter_revision_change(
        "inv-1", INV_R2_LIMITS["revision_id"]
    )

    assert report["status"] == "warning"
    codes = {item["code"] for item in report["consequences"]}
    assert "inverter_mppt_topology_conflict" not in codes
    assert "connected_strings_require_revalidation" in codes
    assert "ac_rating_changed" in codes


def test_apply_inverter_revision_keeps_current_topology_and_marks_binding_state():
    session = _session()
    before = deepcopy(session.electrical_design)

    report = session.apply_inverter_revision_keep_current_topology(
        "inv-1", INV_R2_SMALL["revision_id"]
    )
    after = session.electrical_design
    inverter = after["inverter_instances"][0]

    assert report["status"] == "conflict"
    assert inverter["inverter_definition_revision_id"] == INV_R2_SMALL["revision_id"]
    assert inverter["mppt_instance_ids"] == before["inverter_instances"][0]["mppt_instance_ids"]
    assert after["mppt_instances"] == before["mppt_instances"]
    assert after["strings"] == before["strings"]
    assert inverter["component_binding"]["status"] == "conflict"

    assert session.undo() is True
    assert session.electrical_design == before


def test_component_reports_and_manifest_validate_against_schemas():
    session = _session()
    module_report = session.analyze_module_revision_change(
        "field-1", MODULE_R2_LARGE["revision_id"]
    )
    inverter_report = session.analyze_inverter_revision_change(
        "inv-1", INV_R2_SMALL["revision_id"]
    )
    manifest = session.binding_manifest()
    registry = _registry()

    impact_schema = _load(
        "components/schema/component-revision-impact.schema.json"
    )
    manifest_schema = _load(
        "components/schema/component-binding-manifest.schema.json"
    )

    Draft202012Validator(
        impact_schema, registry=registry
    ).validate(module_report)
    Draft202012Validator(
        impact_schema, registry=registry
    ).validate(inverter_report)
    Draft202012Validator(
        manifest_schema, registry=registry
    ).validate(manifest)


def test_component_revision_command_schema_is_explicit_and_renderer_neutral():
    schema = _load(
        "apps/web/schema/component-revision-command.schema.json"
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(
        {
            "schema_name": "ComponentRevisionCommand",
            "schema_version": "0.1",
            "command_id": "cmd-component-001",
            "command_type": "analyze_revision_change",
            "component_type": "module",
            "target_id": "field-1",
            "proposed_revision_id": MODULE_R2_LARGE["revision_id"],
        }
    )
    serialized = json.dumps(schema).lower()
    assert "three.js" not in serialized
    assert "canvas" not in serialized


def test_landscape_module_orientation_propagates_to_3d_plane_dimensions():
    scene = _packed_scene(MODULE_R1, orientation="landscape")
    generated = generate_scene3d(scene)
    module = generated["modules"][0]

    assert module["physical_width_m"] == pytest.approx(1.0)
    assert module["physical_height_m"] == pytest.approx(2.0)
    assert module["orientation"] == "landscape"
    assert module["plane_width_m"] == pytest.approx(2.0)
    assert module["plane_height_m"] == pytest.approx(1.0)
