import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from electrical.topology import (
    ElectricalTopologyEditorSession,
    canonical_electrical_hash,
    new_electrical_design,
)
from engine.simulation.canonical import (
    CanonicalRevisionStore,
    _resolve_topology,
)
from geometry.pvfield import PVFieldPackingSession
from geometry.scene import SceneEditorSession


ROOT = Path(__file__).resolve().parents[2]


MODULE = {
    "schema_name": "ModuleDefinition",
    "schema_version": "0.1",
    "module_definition_id": "mod-topo",
    "revision_id": "mod-topo-r1",
    "manufacturer": "OpenSIMPV Test",
    "model": "TOPO-400",
    "verification_state": "auto_validated",
    "mechanical": {
        "width_m": 1.0,
        "height_m": 2.0,
        "thickness_m": 0.03,
        "mass_kg": 20.0,
    },
    "stc": {
        "pmp_w": 400.0,
        "voc_v": 40.0,
        "isc_a": 12.0,
        "vmp_v": 33.0,
        "imp_a": 11.5,
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
        "max_system_voltage_v": 1500.0,
        "max_series_fuse_a": 25.0,
        "operating_temperature_min_c": -40.0,
        "operating_temperature_max_c": 85.0,
    },
    "electrical_models": [
        {
            "model_type": "pvwatts",
            "model_version": "test-v1",
            "parameter_set": {},
            "verification_state": "auto_validated",
        }
    ],
    "capability_flags": {
        "layout_ready": True,
        "basic_yield_ready": True,
        "detailed_sdm_ready": False,
        "bifacial_ready": False,
        "detailed_shading_ready": False,
        "independent_iv_validated": False,
    },
}


INVERTER = {
    "schema_name": "InverterDefinition",
    "schema_version": "0.1",
    "inverter_definition_id": "inv-topo",
    "revision_id": "inv-topo-r1",
    "manufacturer": "OpenSIMPV Test",
    "model": "TOPO-100K",
    "inverter_type": "string",
    "phase_configuration": "three_phase",
    "verification_state": "auto_validated",
    "dc_limits": {
        "max_dc_voltage_v": 1000.0,
        "nominal_dc_voltage_v": 600.0,
        "max_dc_power_w": 150000.0,
        "max_dc_current_a": 60.0,
        "max_dc_short_circuit_current_a": 80.0,
    },
    "ac_limits": {
        "nominal_ac_power_w": 100000.0,
        "max_ac_power_w": 110000.0,
        "nominal_ac_voltage_v": 400.0,
        "nominal_frequency_hz": 50.0,
    },
    "mppt_template": {
        "count": 2,
        "min_operating_voltage_v": 200.0,
        "max_operating_voltage_v": 850.0,
        "nominal_voltage_v": 600.0,
        "max_operating_current_a": 30.0,
        "max_short_circuit_current_a": 40.0,
        "input_count_per_mppt": 2,
        "total_input_count": 4,
        "independent_inputs": True,
    },
    "efficiency_model": {
        "model_type": "constant",
        "curves": [],
        "reference_metrics": {
            "max_efficiency_fraction": 0.985,
            "european_efficiency_fraction": 0.975,
            "cec_efficiency_fraction": None,
        },
    },
    "array_sizing_limits": {
        "max_pv_array_power_w": 150000.0,
        "max_pv_current_a": 60.0,
    },
    "capability_flags": {
        "basic_design_ready": True,
        "mppt_design_ready": True,
        "basic_yield_ready": True,
        "detailed_efficiency_ready": False,
        "derating_ready": False,
        "mppt_voltage_ready": True,
        "mppt_current_limit_ready": True,
        "array_sizing_ready": True,
    },
}


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _registry():
    registry = Registry()
    for directory in (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "geometry/scene3d",
        ROOT / "electrical/schema",
        ROOT / "apps/web/schema",
    ):
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def _scene():
    editor = SceneEditorSession(
        _load("tests/fixtures/phase42/simple-survey-base.scene.json")
    )
    editor.draw_rectangle(
        surface_id="roof",
        scene_object_id="obj-roof",
        name="Topology roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=4.0,
        height_m=4.0,
        base_elevation_m=8.0,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    packing = PVFieldPackingSession(
        editor.scene, {MODULE["revision_id"]: MODULE}
    )
    packing.create_field(
        pv_field_id="field-1",
        name="Field 1",
        support_surface_id="roof",
        module_definition_revision_id=MODULE["revision_id"],
        orientation="portrait",
        azimuth_deg=0.0,
        tilt_deg=0.0,
        module_gap_x_m=0.0,
        module_gap_y_m=0.0,
        row_pitch_m=2.0,
        mounting_height_m=0.2,
        requested_row_count=2,
        requested_modules_per_row=4,
    )
    packing.fill_area("field-1")
    assert len(packing.scene["module_instances"]) == 8
    return packing.scene


def _design():
    return new_electrical_design(
        project_id="proj-topo",
        electrical_revision_id="elec-topo-r1",
        pcc_id="pcc-1",
        revision_number=1,
        project_revision_id="proj-topo-r1",
    )


def _session():
    return ElectricalTopologyEditorSession(
        _scene(),
        _design(),
        project_revision_id="proj-topo-r1",
        module_definitions={MODULE["revision_id"]: MODULE},
        inverter_definitions={INVERTER["revision_id"]: INVERTER},
    )


def _module_ids(scene):
    return [
        item["module_instance_id"]
        for item in sorted(
            scene["module_instances"],
            key=lambda item: (
                item["row_index"],
                item["column_index"],
            ),
        )
    ]


def test_manual_workflow_create_string_then_assign_mppt_is_canonical():
    session = _session()
    inverter = session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=INVERTER["revision_id"],
        name="INV-1",
    )
    ids = _module_ids(session._scene)

    string = session.create_string(
        string_id="S01",
        module_instance_ids=ids[:4],
        name="String 1",
    )
    assert string["target_mppt_instance_id"] is None
    assert string["enabled"] is False

    report = session.consistency_report()
    assert report["blocking_count"] == 0
    assert report["draft_count"] == 1

    session.assign_strings_to_mppt(
        ["S01"],
        mppt_instance_id=inverter["mppt_instance_ids"][0],
    )
    design = session.electrical_design
    string = design["strings"][0]
    mppt = design["mppt_instances"][0]

    assert string["target_mppt_instance_id"] == mppt["mppt_instance_id"]
    assert string["enabled"] is True
    assert mppt["connected_string_ids"] == ["S01"]
    assert session.consistency_report()["blocking_count"] == 0


def test_manual_string_preserves_series_order_and_blocks_duplicate_membership():
    session = _session()
    ids = _module_ids(session._scene)
    selected = [ids[3], ids[2], ids[1], ids[0]]
    session.create_string(
        string_id="S01",
        module_instance_ids=selected,
    )
    assert session.electrical_design["strings"][0][
        "module_instance_ids"
    ] == selected

    with pytest.raises(ValueError, match="already belong"):
        session.create_string(
            string_id="S02",
            module_instance_ids=[ids[0], ids[4]],
        )


def test_reassignment_updates_both_mppts_atomically_and_undo_redo():
    session = _session()
    inverter = session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=INVERTER["revision_id"],
        name="INV-1",
    )
    ids = _module_ids(session._scene)
    session.create_string(string_id="S01", module_instance_ids=ids[:4])
    session.assign_strings_to_mppt(
        ["S01"], mppt_instance_id=inverter["mppt_instance_ids"][0]
    )
    before = session.canonical_hash()

    session.assign_strings_to_mppt(
        ["S01"], mppt_instance_id=inverter["mppt_instance_ids"][1]
    )
    design = session.electrical_design
    assert design["mppt_instances"][0]["connected_string_ids"] == []
    assert design["mppt_instances"][1]["connected_string_ids"] == ["S01"]

    assert session.undo() is True
    assert session.canonical_hash() == before
    assert session.redo() is True
    assert session.electrical_design["mppt_instances"][1][
        "connected_string_ids"
    ] == ["S01"]


def test_manual_assignment_enforces_verified_physical_input_count():
    session = _session()
    inverter = session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=INVERTER["revision_id"],
        name="INV-1",
    )
    ids = _module_ids(session._scene)
    for index in range(3):
        session.create_string(
            string_id=f"S0{index+1}",
            module_instance_ids=[ids[index]],
        )

    with pytest.raises(ValueError, match="verified DC inputs"):
        session.assign_strings_to_mppt(
            ["S01", "S02", "S03"],
            mppt_instance_id=inverter["mppt_instance_ids"][0],
        )


def test_create_strings_is_explicit_deterministic_and_one_undo_step():
    session = _session()
    ids = list(reversed(_module_ids(session._scene)))
    depth = session.undo_depth

    created = session.create_strings(
        ids,
        string_length=2,
        id_prefix="S",
        ordering="row_major",
    )
    assert created == ("S001", "S002", "S003", "S004")
    assert session.undo_depth == depth + 1

    strings = session.electrical_design["strings"]
    assert [
        value
        for string in strings
        for value in string["module_instance_ids"]
    ] == _module_ids(session._scene)
    assert all(string["enabled"] is False for string in strings)

    assert session.undo() is True
    assert session.electrical_design["strings"] == []


def test_create_strings_remainder_policy_fails_closed_without_history():
    session = _session()
    ids = _module_ids(session._scene)[:5]
    before = session.canonical_hash()
    depth = session.undo_depth

    with pytest.raises(ValueError, match="not divisible"):
        session.create_strings(
            ids,
            string_length=2,
            remainder_policy="error",
        )

    assert session.canonical_hash() == before
    assert session.undo_depth == depth


def test_assign_strings_uses_existing_deterministic_balanced_helper():
    session = _session()
    session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=INVERTER["revision_id"],
        name="INV-1",
    )
    ids = _module_ids(session._scene)
    session.create_strings(ids, string_length=2)

    assignment = session.assign_strings(
        ["S001", "S002", "S003", "S004"],
        inverter_instance_id="inv-1",
    )
    assert assignment == {
        1: ("S001", "S002"),
        2: ("S003", "S004"),
    }

    view = session.inspect_inverter("inv-1")
    assert [len(item["strings"]) for item in view["mppts"]] == [2, 2]
    assert session.consistency_report()["blocking_count"] == 0


def test_assign_strings_does_not_move_unselected_existing_strings():
    session = _session()
    inverter = session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=INVERTER["revision_id"],
        name="INV-1",
    )
    ids = _module_ids(session._scene)
    session.create_strings(ids, string_length=2)
    session.assign_strings_to_mppt(
        ["S001"], mppt_instance_id=inverter["mppt_instance_ids"][0]
    )

    with pytest.raises(ValueError, match="Balance MPPT"):
        session.assign_strings(
            ["S002", "S003", "S004"],
            inverter_instance_id="inv-1",
        )


def test_balance_mppt_is_explicit_and_rebalances_current_inverter_strings():
    session = _session()
    inverter = session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=INVERTER["revision_id"],
        name="INV-1",
    )
    ids = _module_ids(session._scene)[:6]
    session.create_strings(ids, string_length=2)

    # Start with 1+2 strings while staying within the verified 2-input limit.
    session.assign_strings_to_mppt(
        ["S001"],
        mppt_instance_id=inverter["mppt_instance_ids"][0],
    )
    session.assign_strings_to_mppt(
        ["S002", "S003"],
        mppt_instance_id=inverter["mppt_instance_ids"][1],
    )

    result = session.balance_mppt("inv-1")
    assert result[1] == ("S001", "S002")
    assert result[2] == ("S003",)


def test_suggest_string_length_is_non_mutating_and_stc_only():
    session = _session()
    session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=INVERTER["revision_id"],
        name="INV-1",
    )
    before = session.canonical_hash()

    suggestion = session.suggest_string_length(
        module_definition_revision_id=MODULE["revision_id"],
        inverter_instance_id="inv-1",
    )

    assert session.canonical_hash() == before
    assert suggestion["engineering_state_mutated"] is False
    assert suggestion["basis"] == "stc_reference_conditions_only"
    assert suggestion["minimum_modules_per_string"] == 7
    assert suggestion["maximum_modules_per_string"] == 25
    assert suggestion["recommended_modules_per_string"] == 18
    assert "Voc @ minimum design temperature" in suggestion[
        "validation_deferred"
    ]


def test_topology_view_matches_required_inverter_mppt_string_hierarchy():
    session = _session()
    session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=INVERTER["revision_id"],
        name="Inverter 1",
    )
    ids = _module_ids(session._scene)
    session.create_strings(ids, string_length=2)
    session.assign_strings(
        ["S001", "S002", "S003", "S004"],
        inverter_instance_id="inv-1",
    )

    view = session.topology_view()
    assert view["inverters"][0]["name"] == "Inverter 1"
    assert [
        item["index"] for item in view["inverters"][0]["mppts"]
    ] == [1, 2]
    assert [
        item["string_id"]
        for item in view["inverters"][0]["mppts"][0]["strings"]
    ] == ["S001", "S002"]
    assert view["unassigned_strings"] == []


def test_unassign_and_delete_string_keep_reciprocal_topology_clean():
    session = _session()
    inverter = session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=INVERTER["revision_id"],
        name="INV-1",
    )
    ids = _module_ids(session._scene)
    session.create_string(string_id="S01", module_instance_ids=ids[:4])
    session.assign_strings_to_mppt(
        ["S01"], mppt_instance_id=inverter["mppt_instance_ids"][0]
    )

    session.unassign_strings(["S01"])
    string = session.electrical_design["strings"][0]
    assert string["target_mppt_instance_id"] is None
    assert string["enabled"] is False
    assert session.electrical_design["mppt_instances"][0][
        "connected_string_ids"
    ] == []

    session.delete_string("S01")
    assert session.electrical_design["strings"] == []
    assert session.consistency_report()["blocking_count"] == 0


def test_consistency_report_detects_nonreciprocal_external_fixture():
    scene = _scene()
    design = _design()
    design["strings"] = [
        {
            "string_id": "S01",
            "project_revision_id": "proj-topo-r1",
            "name": "S01",
            "module_instance_ids": [_module_ids(scene)[0]],
            "target_mppt_instance_id": "missing-mppt",
            "enabled": True,
            "polarity": "normal",
        }
    ]
    session = ElectricalTopologyEditorSession(
        scene,
        design,
        project_revision_id="proj-topo-r1",
    )
    report = session.consistency_report()
    assert report["blocking_count"] == 1
    assert report["findings"][0]["code"] == "string_unknown_mppt"


def test_commit_revision_creates_immutable_revision_identity_and_clears_history():
    session = _session()
    session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=INVERTER["revision_id"],
        name="INV-1",
    )
    before = session.electrical_design["electrical_revision_id"]

    committed = session.commit_revision(
        electrical_revision_id="elec-topo-r2",
        revision_number=2,
        change_summary="Created topology in design environment.",
        created_by="test",
        created_at="2026-09-24T00:00:00Z",
    )

    assert committed["electrical_revision_id"] == "elec-topo-r2"
    assert committed["supersedes_revision_id"] == before
    assert committed["revision_number"] == 2
    assert session.undo_depth == 0
    assert session.redo_depth == 0
    assert session.canonical_hash() == canonical_electrical_hash(committed)


def test_editor_generated_topology_is_accepted_by_existing_simulation_resolver():
    scene = _scene()
    session = ElectricalTopologyEditorSession(
        scene,
        _design(),
        project_revision_id="proj-topo-r1",
        module_definitions={MODULE["revision_id"]: MODULE},
        inverter_definitions={INVERTER["revision_id"]: INVERTER},
    )
    session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=INVERTER["revision_id"],
        name="INV-1",
    )
    ids = _module_ids(scene)
    session.create_strings(ids, string_length=4)
    session.assign_strings(
        ["S001", "S002"],
        inverter_instance_id="inv-1",
    )
    electrical = session.electrical_design

    store = CanonicalRevisionStore(
        scene_revisions={scene["revision_id"]: scene},
        electrical_revisions={
            electrical["electrical_revision_id"]: electrical
        },
        weather_revisions={},
        component_revisions={
            MODULE["revision_id"]: MODULE,
            INVERTER["revision_id"]: INVERTER,
        },
    )
    findings = []
    resolved = _resolve_topology(
        scene,
        electrical,
        store,
        {
            "simulation_configuration_id": "cfg-test",
            "shading_configuration": {
                "beam_method": "none",
                "diffuse_method": "none",
            },
            "numerical_options": {"albedo": 0.2},
        },
        run_id="run-test",
        project_revision_id="proj-topo-r1",
        generated_at="2026-09-24T00:00:00Z",
        findings=findings,
    )

    blockers = [
        item for item in findings
        if item["severity"] == "blocking_error"
    ]
    assert blockers == []
    assert resolved is not None
    assert resolved["modules_in_series"] == 4
    assert resolved["string_ids"] == ("S001", "S002")
    assert resolved["mppt_assignments"] == {
        1: ("S001",),
        2: ("S002",),
    }


def test_phase46_schemas_validate_draft_view_report_suggestion_and_command():
    session = _session()
    session.add_inverter(
        inverter_instance_id="inv-1",
        inverter_definition_revision_id=INVERTER["revision_id"],
        name="INV-1",
    )
    ids = _module_ids(session._scene)
    session.create_string(string_id="S01", module_instance_ids=ids[:4])

    registry = _registry()
    electrical_schema = _load(
        "electrical/schema/electrical-design.schema.json"
    )
    view_schema = _load(
        "apps/web/schema/electrical-topology-view.schema.json"
    )
    report_schema = _load(
        "electrical/schema/electrical-topology-consistency-report.schema.json"
    )
    suggestion_schema = _load(
        "electrical/schema/string-length-suggestion.schema.json"
    )
    command_schema = _load(
        "apps/web/schema/electrical-topology-command.schema.json"
    )

    Draft202012Validator(
        electrical_schema, registry=registry
    ).validate(session.electrical_design)
    Draft202012Validator(
        view_schema, registry=registry
    ).validate(session.topology_view())
    Draft202012Validator(
        report_schema, registry=registry
    ).validate(session.consistency_report())
    Draft202012Validator(
        suggestion_schema, registry=registry
    ).validate(
        session.suggest_string_length(
            module_definition_revision_id=MODULE["revision_id"],
            inverter_instance_id="inv-1",
        )
    )
    Draft202012Validator(command_schema).validate(
        {
            "schema_name": "ElectricalTopologyCommand",
            "schema_version": "0.1",
            "command_id": "cmd-topo-001",
            "command_type": "create_string",
            "parameters": {
                "string_id": "S02",
                "module_instance_ids": ids[4:],
            },
        }
    )


def test_repeated_identical_manual_workflow_serializes_identically():
    def build():
        session = _session()
        session.add_inverter(
            inverter_instance_id="inv-1",
            inverter_definition_revision_id=INVERTER["revision_id"],
            name="INV-1",
        )
        ids = _module_ids(session._scene)
        session.create_strings(ids, string_length=4)
        session.assign_strings(
            ["S001", "S002"],
            inverter_instance_id="inv-1",
        )
        return session.electrical_design

    first = build()
    second = build()
    assert first == second
    assert canonical_electrical_hash(first) == canonical_electrical_hash(
        second
    )
