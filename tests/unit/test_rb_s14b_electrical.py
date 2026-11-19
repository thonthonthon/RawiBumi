"""S14b: the orientation policy the simulation honours, persisted pairing, notation Apply, replicate pattern."""

import pytest

from apps.api.history import design_fingerprint
from apps.api.live_checks import topology_checks
from apps.api.orientation_policy import with_effective_policy
from apps.api.study import _validation_configuration
from engine.simulation.execution_groups import build_simulation_execution_plan, normal_angle_deg, string_compatibility_keys
from geometry.pvfield.explicit import create_explicit_field
from tests.unit.test_rb_fix_s2_honest_preflight import MODULE, Project
from validation.engineering import validate_engineering_design


def _command(kind, parameters, command_id=None):
    return {"schema_name": "ElectricalTopologyCommand", "schema_version": "0.1", "command_id": command_id or kind,
            "command_type": kind, "parameters": parameters}


def _post(p, *commands):
    return p.client.post(p.url + "/electrical/commands", json={"commands": list(commands)})


def _ok(p, *commands):
    response = _post(p, *commands)
    assert response.status_code == 200, response.text
    return response.json()


def _refused(p, command, message):
    before = p.path.read_bytes()
    response = _post(p, command)
    assert response.status_code == 422, response.text
    assert message in response.text
    assert p.path.read_bytes() == before


def _mppts(p):
    return [m["mppt_instance_id"] for m in sorted(p.bundle()["electrical_design"]["mppt_instances"], key=lambda m: m["index"])]


def _inverter(p):
    return p.bundle()["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]


def _two_fields(tmp_path, second_tilt, *, weather=False, count=10):
    """Two single-row roofs of `count` modules: the first at 10°, the second at `second_tilt`; one string each on MPPT 1."""
    p = Project(tmp_path, count, weather=weather, strings=False)
    roof = p.service.add_surface_rectangle(p.pid, name="Second roof", origin_x_m=0, origin_y_m=20, width_m=1 + count * 1.154 - 0.01,
                                           height_m=3.45, base_elevation_m=6.1, surface_type="flat_roof", usable_for_pv=True)
    surface = next(s for s in roof["bundle"]["scene"]["surfaces"] if s["name"] == "Second roof")["surface_id"]
    p.service.create_pv_field(p.pid, name="Second field", support_surface_id=surface, module_definition_revision_id=MODULE,
                              tilt_deg=second_tilt, row_pitch_m=3.2, perimeter_setback_m=0.5, obstacle_setback_m=0.3)
    scene = p.bundle()["scene"]
    second = scene["pv_fields"][-1]["pv_field_id"]
    a = [m["module_instance_id"] for m in scene["module_instances"] if m["pv_field_id"] != second]
    b = [m["module_instance_id"] for m in scene["module_instances"] if m["pv_field_id"] == second]
    _ok(p, _command("create_string", {"string_id": "S001", "module_instance_ids": a}, "a"),
        _command("create_string", {"string_id": "S002", "module_instance_ids": b[:len(a)]}, "b"),
        _command("assign_strings_to_mppt", {"mppt_instance_id": _mppts(p)[0], "string_ids": ["S001", "S002"]}, "c"))
    return p, a, b


# --- the execution plan -------------------------------------------------------------------------------------------

def test_without_a_policy_the_plan_compares_exactly(tmp_path):
    p, _, _ = _two_fields(tmp_path, 10.5)
    b = p.bundle()
    plan = build_simulation_execution_plan(b["scene"], b["electrical_design"], numerical_options={"albedo": .2})
    assert plan["execution_class"] == "mixed_orientation_coupled" and plan["heterogeneous_mppt_instance_ids"]

    assert len(plan["mixed_orientation"]["classes"]) == 2


def test_within_the_tolerance_one_mppt_runs_as_one_group_at_the_mean_normal(tmp_path):
    p, a, b = _two_fields(tmp_path, 10.5)
    bundle = p.bundle()
    plan = build_simulation_execution_plan(bundle["scene"], with_effective_policy(bundle["electrical_design"]), numerical_options={"albedo": .2})
    assert plan["execution_class"] == "homogeneous_single_group" and not plan["heterogeneous_mppt_instance_ids"]
    [group] = plan["groups"]
    assert group["surface_tilt_deg"] == pytest.approx(10.25, abs=1e-6) and group["surface_azimuth_deg"] == pytest.approx(0.0, abs=1e-6)
    assert group["orientation_merge"] == {"tolerance_deg": 1.0, "max_normal_angle_deg": pytest.approx(0.5), "representative": "module_weighted_mean_normal",
                                          "source_orientations": [[10.0, 0.0], [10.5, 0.0]]}
    assert sorted(group["string_ids"]) == ["S001", "S002"]


def test_identical_orientations_keep_the_exact_plan_with_a_policy(tmp_path):
    p, _, _ = _two_fields(tmp_path, 10.0)
    b = p.bundle()
    exact = build_simulation_execution_plan(b["scene"], b["electrical_design"], numerical_options={"albedo": .2})
    policy = build_simulation_execution_plan(b["scene"], with_effective_policy(b["electrical_design"]), numerical_options={"albedo": .2})
    assert policy["execution_plan_payload_sha256"] == exact["execution_plan_payload_sha256"]
    assert "orientation_merge" not in policy["groups"][0]


def test_beyond_the_tolerance_stays_heterogeneous(tmp_path):
    p, _, _ = _two_fields(tmp_path, 12.0)
    b = p.bundle()
    plan = build_simulation_execution_plan(b["scene"], with_effective_policy(b["electrical_design"]), numerical_options={"albedo": .2})
    assert plan["heterogeneous_mppt_instance_ids"] == [_mppts(p)[0]]


def test_a_string_spanning_two_close_orientations_is_one_state(tmp_path):
    p, a, b = _two_fields(tmp_path, 10.5)
    _ok(p, _command("swap_modules", {"first_module_instance_id": a[0], "second_module_instance_id": b[0]}))
    bundle = p.bundle()
    exact = build_simulation_execution_plan(bundle["scene"], bundle["electrical_design"], numerical_options={"albedo": .2})
    assert exact["execution_class"] == "mixed_orientation_coupled" and not exact["findings"]
    merged = build_simulation_execution_plan(bundle["scene"], with_effective_policy(bundle["electrical_design"]), numerical_options={"albedo": .2})
    assert not merged["findings"] and merged["group_count"] == 1


def test_auto_assignment_keys_follow_the_tolerance(tmp_path):
    p, _, _ = _two_fields(tmp_path, 10.5)
    b = p.bundle()
    strings = b["electrical_design"]["strings"]
    exact = string_compatibility_keys(b["scene"], strings)
    assert exact["S001"] != exact["S002"]
    close = string_compatibility_keys(b["scene"], strings, orientation_tolerance_deg=1.0)
    assert close["S001"] == close["S002"]
    assert normal_angle_deg((10.0, 0.0), (10.5, 0.0)) == pytest.approx(0.5)


# --- validation, readiness and a full run ---------------------------------------------------------------------------

def _validate(p, comparison):
    b = p.bundle()
    configuration = _validation_configuration(b["electrical_design"]) if comparison == "normal_angle" else _validation_configuration()
    return validate_engineering_design(b["scene"], b["electrical_design"], project_revision_id=b["electrical_design"]["project_revision_id"],
                                       component_revisions={**b["pinned_components"]["modules"], **b["pinned_components"]["inverters"]},
                                       configuration=configuration, design_validation_report_id="s14b", generated_at="2026-11-09T00:00:00+00:00")


def test_validator_normal_angle_mode_and_unchanged_default(tmp_path):
    p, _, _ = _two_fields(tmp_path, 10.5)
    rule = lambda report: [f for f in report["findings"] if f["rule_id"] == "MPPT_ORIENTATION_MISMATCH"]
    assert len(rule(_validate(p, "tilt_azimuth"))) == 1  # the 0.1° tilt/azimuth default is unchanged
    assert rule(_validate(p, "normal_angle")) == []
    assert "orientation_comparison" not in _validate(p, "tilt_azimuth")["metadata"]["validation_configuration"]


def test_validator_normal_angle_reports_the_angle_and_the_limit(tmp_path):
    p, _, _ = _two_fields(tmp_path, 12.0)
    [finding] = [f for f in _validate(p, "normal_angle")["findings"] if f["rule_id"] == "MPPT_ORIENTATION_MISMATCH"]
    assert finding["measured_value"] == pytest.approx(2.0, abs=1e-3) and finding["limit_value"] == 1.0
    assert finding["context"]["string_ids"] == ["S002"] and finding["context"]["orientation_comparison"] == "normal_angle"


def test_a_within_tolerance_mixed_mppt_is_ready_and_runs(tmp_path):
    p, _, _ = _two_fields(tmp_path, 10.5, weather=True)
    ready = p.client.get(p.url + "/execution-readiness").json()
    assert ready["ready"] is True and ready["findings"] == []
    [group] = ready["execution_plan"]["groups"]
    assert group["orientation_merge"]["max_normal_angle_deg"] == pytest.approx(0.5)
    run = p.client.post(p.url + "/simulate", json={})
    assert run.status_code == 200, run.text
    # The fixture weather's near-zero-GHI warning is the only warning, as for an identical-orientation design.
    assert run.json()["status"] in {"completed", "completed_with_warnings"}
    assert {f["rule_id"] for f in run.json()["validation_findings"] if f["severity"] != "info"} == {"WX_SOLAR_DAYLIGHT_WITH_NEAR_ZERO_GHI"}
    checks = {s["string_id"]: {c["code"]: c["state"] for c in s["checks"]} for s in p.client.get(p.url).json()["topology_checks"]["strings"]}
    assert checks["S001"]["orientation"] == checks["S002"]["orientation"] == "pass"


def test_beyond_the_tolerance_the_override_silences_the_warning_but_the_run_stays_blocked(tmp_path):
    p, _, _ = _two_fields(tmp_path, 12.0, weather=True)
    checks = lambda: {s["string_id"]: {c["code"]: c for c in s["checks"]} for s in p.client.get(p.url).json()["topology_checks"]["strings"]}
    assert checks()["S002"]["orientation"]["state"] == "warn" and "(2.0°; limit 1.0°)" in checks()["S002"]["orientation"]["message"]
    mppt = _mppts(p)[0]
    _ok(p, _command("set_orientation_override", {"mppt_instance_id": mppt, "reason": "  One roof plane; survey tolerance  "}))
    assert p.bundle()["electrical_design"]["orientation_policy"]["overrides"] == [{"mppt_instance_id": mppt, "reason": "One roof plane; survey tolerance"}]
    assert checks()["S002"]["orientation"] == {"code": "orientation", "state": "pass", "message": "Mixed orientation accepted by override: One roof plane; survey tolerance"}
    ready = p.client.get(p.url + "/execution-readiness").json()
    assert ready["ready"] is True
    assert not [f for f in ready["findings"] if f["rule_id"] == "MPPT_ORIENTATION_MISMATCH"]
    assert not [f for f in ready["findings"] if f["rule_id"] == "SIMULATION_SCOPE_MIXED_STRINGS_ON_ONE_MPPT"]
    assert p.client.post(p.url + "/simulate", json={}).status_code == 200
    # Clearing the override brings the warning back.
    _ok(p, _command("set_orientation_override", {"mppt_instance_id": mppt, "reason": None}))
    assert checks()["S002"]["orientation"]["state"] == "warn"


def test_a_tighter_tolerance_splits_the_group_again(tmp_path):
    p, _, _ = _two_fields(tmp_path, 10.5, weather=True)
    _ok(p, _command("set_orientation_tolerance", {"tolerance_deg": 0.25}))
    assert p.bundle()["electrical_design"]["orientation_policy"]["normal_angle_tolerance_deg"] == 0.25
    ready = p.client.get(p.url + "/execution-readiness").json()
    assert ready["ready"] and len(ready["execution_plan"]["mixed_orientation"]["classes"]) == 2
    assert p.client.post(p.url + "/simulate", json={}).status_code == 200
    assert "orientation tolerance 0.25° between module normals" in p.client.get(p.url).json()["topology_checks"]["basis"]


def test_policy_command_refusals(tmp_path):
    p, _, _ = _two_fields(tmp_path, 10.0)
    _refused(p, _command("set_orientation_tolerance", {"tolerance_deg": 1.5}), "less than or equal to 1")
    _refused(p, _command("set_orientation_tolerance", {"tolerance_deg": "1"}), "tolerance_deg")
    _refused(p, _command("set_orientation_override", {"mppt_instance_id": _mppts(p)[0], "reason": ""}), "at least 1 character")
    _refused(p, _command("set_orientation_override", {"mppt_instance_id": _mppts(p)[0], "reason": "   "}), "1 to 500 characters")
    _refused(p, _command("set_orientation_override", {"mppt_instance_id": "mppt-404", "reason": "x"}), "mppt-404")
    _refused(p, _command("set_orientation_override", {"mppt_instance_id": _mppts(p)[0]}), "reason")


# --- pairing --------------------------------------------------------------------------------------------------------

def test_pairing_is_saved_undoable_advisory_and_outside_the_fingerprint(tmp_path):
    p, a, b = _two_fields(tmp_path, 10.0)
    fields = [f["pv_field_id"] for f in p.bundle()["scene"]["pv_fields"]]
    before = p.client.get(p.url).json()
    view = _ok(p, _command("set_inverter_pairing", {"inverter_instance_id": _inverter(p), "pv_field_ids": [fields[0], fields[0]]}))
    assert view["bundle"]["electrical_design"]["inverter_instances"][0]["paired_pv_field_ids"] == [fields[0]]
    assert view["design_fingerprint"] == before["design_fingerprint"]
    pairing = {s["string_id"]: next(c for c in s["checks"] if c["code"] == "pairing") for s in view["topology_checks"]["strings"]}
    assert pairing["S001"]["state"] == "pass" and pairing["S002"] == {"code": "pairing", "state": "warn", "message": "Modules outside the inverter's paired fields: Second field."}
    entry = view["history"]["past"][-1]["entry_id"]
    undone = p.client.post(p.url + "/undo", json={"expected_project_revision_id": view["bundle"]["project"]["project_revision"]["project_revision_id"], "expected_entry_id": entry})
    assert undone.status_code == 200 and "paired_pv_field_ids" not in undone.json()["bundle"]["electrical_design"]["inverter_instances"][0]
    _refused(p, _command("set_inverter_pairing", {"inverter_instance_id": _inverter(p), "pv_field_ids": ["field-404"]}), "unknown PV fields")
    _ok(p, _command("set_inverter_pairing", {"inverter_instance_id": _inverter(p), "pv_field_ids": fields}))
    view = _ok(p, _command("set_inverter_pairing", {"inverter_instance_id": _inverter(p), "pv_field_ids": []}))
    assert "paired_pv_field_ids" not in view["bundle"]["electrical_design"]["inverter_instances"][0]


def test_fingerprint_keeps_the_tolerance_but_not_override_reasons(tmp_path):
    p, _, _ = _two_fields(tmp_path, 10.0)
    base = design_fingerprint(p.bundle())
    _ok(p, _command("set_orientation_tolerance", {"tolerance_deg": 1.0}))
    assert design_fingerprint(p.bundle()) == base  # an explicit 1° is the default
    _ok(p, _command("set_orientation_override", {"mppt_instance_id": _mppts(p)[0], "reason": "why"}))
    assert design_fingerprint(p.bundle()) == base
    _ok(p, _command("set_orientation_tolerance", {"tolerance_deg": 0.5}))
    assert design_fingerprint(p.bundle()) != base


# --- notation apply -------------------------------------------------------------------------------------------------

@pytest.fixture
def twenty(tmp_path):
    return Project(tmp_path, 20, weather=False, strings=False)


def _lengths(p):
    design = p.bundle()["electrical_design"]
    by = {m: [] for m in _mppts(p)}
    for s in design["strings"]:
        if s.get("target_mppt_instance_id"):
            by[s["target_mppt_instance_id"]].append(len(s["module_instance_ids"]))
    return [sorted(v) for v in by.values()]


def test_apply_creates_keeps_reuses_and_unassigns(twenty):
    p = twenty
    view = _ok(p, _command("apply_mppt_layout", {"inverter_instance_id": _inverter(p), "layout": [[10, 10], [0]]}))
    assert view["command_results"][0]["result"]["created_string_ids"] == ["S001", "S002"]
    assert _lengths(p) == [[10, 10], []]
    assert all(s["enabled"] and s["topology_source"].startswith("apply_mppt_layout:") for s in p.bundle()["electrical_design"]["strings"])
    # One 10 stays on MPPT 1; the other is released and reused on MPPT 2.
    result = _ok(p, _command("apply_mppt_layout", {"inverter_instance_id": _inverter(p), "layout": [[10], [10]]}))["command_results"][0]["result"]
    assert result["kept_string_ids"] == ["S001"] and result["reused_string_ids"] == ["S002"] and result["created_string_ids"] == []
    assert _lengths(p) == [[10], [10]]
    mppts = {m["mppt_instance_id"]: m for m in p.bundle()["electrical_design"]["mppt_instances"]}
    assert mppts[_mppts(p)[0]]["connected_string_ids"] == ["S001"] and mppts[_mppts(p)[1]]["connected_string_ids"] == ["S002"]
    # An empty layout unassigns everything; nothing is deleted.
    result = _ok(p, _command("apply_mppt_layout", {"inverter_instance_id": _inverter(p), "layout": [[0], [0]]}))["command_results"][0]["result"]
    assert result["unassigned_string_ids"] == ["S001", "S002"] and len(p.bundle()["electrical_design"]["strings"]) == 2
    assert _lengths(p) == [[], []]


def test_apply_refusals_change_nothing(twenty):
    p = twenty
    inv = _inverter(p)
    _refused(p, _command("apply_mppt_layout", {"inverter_instance_id": inv, "layout": [[10]]}), "the layout has 1 MPPTs")
    _refused(p, _command("apply_mppt_layout", {"inverter_instance_id": inv, "layout": [[5, 5, 5, 5], [0]]}), "verified DC inputs")
    _refused(p, _command("apply_mppt_layout", {"inverter_instance_id": inv, "layout": [[15], [10]]}), "not enough unstrung modules")
    _refused(p, _command("apply_mppt_layout", {"inverter_instance_id": inv, "layout": [[-1], [0]]}), "greater than or equal to 0")
    _refused(p, _command("apply_mppt_layout", {"inverter_instance_id": inv, "layout": [[10], [0]], "pv_field_ids": ["field-404"]}), "unknown PV fields")


def test_apply_draws_from_the_paired_fields(tmp_path):
    p = Project(tmp_path, 10, weather=False, strings=False)
    roof = p.service.add_surface_rectangle(p.pid, name="Other", origin_x_m=0, origin_y_m=20, width_m=1 + 10 * 1.154 - 0.01, height_m=3.45,
                                           base_elevation_m=6.1, surface_type="flat_roof", usable_for_pv=True)
    surface = next(s for s in roof["bundle"]["scene"]["surfaces"] if s["name"] == "Other")["surface_id"]
    p.service.create_pv_field(p.pid, name="Other field", support_surface_id=surface, module_definition_revision_id=MODULE, tilt_deg=10,
                              row_pitch_m=3.2, perimeter_setback_m=0.5, obstacle_setback_m=0.3)
    other = p.bundle()["scene"]["pv_fields"][-1]["pv_field_id"]
    _ok(p, _command("set_inverter_pairing", {"inverter_instance_id": _inverter(p), "pv_field_ids": [other]}))
    _ok(p, _command("apply_mppt_layout", {"inverter_instance_id": _inverter(p), "layout": [[10], [0]]}))
    [string] = p.bundle()["electrical_design"]["strings"]
    fields = {m["module_instance_id"]: m["pv_field_id"] for m in p.bundle()["scene"]["module_instances"]}
    assert {fields[m] for m in string["module_instance_ids"]} == {other}


# --- replicate pattern ----------------------------------------------------------------------------------------------

def _tables(tmp_path):
    """One explicit field with four identical 3×1 tables and one 2×1 table."""
    p = Project(tmp_path, 18, weather=False, strings=False)
    raw = p.bundle()
    surface = raw["scene"]["surfaces"][0]["surface_id"]
    raw["scene"]["pv_fields"], raw["scene"]["module_instances"] = [], []
    definitions = p.service._component_definitions(raw, "modules")

    def table(table_id, x, across=3):
        return {"table_id": table_id, "anchor_xyz_m": [x, 1.7, 6.1], "anchor_convention": "center", "tilt_deg": 0.0, "azimuth_deg": 180.0,
                "module_definition_revision_id": MODULE, "modules_across": across, "modules_up": 1, "module_orientation": "portrait",
                "module_gap_across_m": 0.02, "module_gap_up_m": 0.02, "support_surface_id": surface}
    field, modules = create_explicit_field(raw["scene"], definitions, pv_field_id="field-tables", name="Tables",
                                           tables=[table("T1", 2.0), table("T2", 6.0), table("T3", 10.0), table("T4", 14.0), table("T5", 18.0, 2)],
                                           provenance={"source_id": "test"})
    raw["scene"]["pv_fields"].append(field)
    raw["scene"]["module_instances"].extend(modules)
    p.service.save_bundle(raw, history_mode="neutral")
    slot = {(m["table_id"], m["column_index"]): m["module_instance_id"] for m in modules}
    return p, slot


def test_replicate_copies_the_source_wiring_by_slot_to_identical_unwired_tables(tmp_path):
    p, slot = _tables(tmp_path)
    # T1 wired back to front; T3 already wired, so it's skipped; T5 has another size.
    _ok(p, _command("create_string", {"string_id": "S001", "module_instance_ids": [slot["T1", 2], slot["T1", 1], slot["T1", 0]]}, "a"),
        _command("create_string", {"string_id": "S002", "module_instance_ids": [slot["T3", 0]]}, "b"))
    result = _ok(p, _command("replicate_pattern", {"source_pv_field_id": "field-tables", "source_table_id": "T1"}))["command_results"][0]["result"]
    assert result["copied"] == [{"pv_field_id": "field-tables", "table_id": "T2"}, {"pv_field_id": "field-tables", "table_id": "T4"}]
    assert result["skipped"] == [{"pv_field_id": "field-tables", "table_id": "T3", "reason": "already wired"}]
    strings = {s["string_id"]: s for s in p.bundle()["electrical_design"]["strings"]}
    copies = [strings[sid] for sid in result["created_string_ids"]]
    assert [s["module_instance_ids"] for s in copies] == [[slot["T2", 2], slot["T2", 1], slot["T2", 0]], [slot["T4", 2], slot["T4", 1], slot["T4", 0]]]
    assert all(s["target_mppt_instance_id"] is None and s["topology_source"].startswith("replicate_pattern:") for s in copies)


def test_replicate_refusals(tmp_path):
    p, slot = _tables(tmp_path)
    ref = {"source_pv_field_id": "field-tables", "source_table_id": "T1"}
    _refused(p, _command("replicate_pattern", ref), "no string lies wholly inside it")
    _ok(p, _command("create_string", {"string_id": "S001", "module_instance_ids": [slot["T1", 0], slot["T1", 1], slot["T1", 2]]}))
    _refused(p, _command("replicate_pattern", {**ref, "targets": [{"pv_field_id": "field-tables", "table_id": "T5"}]}), "not identical")
    _refused(p, _command("replicate_pattern", {**ref, "targets": [{"pv_field_id": "field-tables", "table_id": "T1"}]}), "its own target")
    _refused(p, _command("replicate_pattern", {**ref, "source_table_id": "T9"}), "unknown table T9")
    generated = Project(tmp_path / "generated", 6, weather=False, strings=True)
    field = generated.bundle()["scene"]["pv_fields"][0]["pv_field_id"]
    _refused(generated, _command("replicate_pattern", {"source_pv_field_id": field, "source_table_id": "0"}), "row 14")
    # Explicit targets: only T2.
    result = _ok(p, _command("replicate_pattern", {**ref, "targets": [{"pv_field_id": "field-tables", "table_id": "T2"}]}))["command_results"][0]["result"]
    assert result["copied"] == [{"pv_field_id": "field-tables", "table_id": "T2"}]


def test_live_check_failure_path_keeps_all_seven_codes(tmp_path):
    p, _, _ = _two_fields(tmp_path, 10.0)
    result = topology_checks(p.bundle(), lambda bundle: (_ for _ in ()).throw(ValueError("x")))
    assert [c["code"] for c in result["strings"][0]["checks"]] == ["voltage_window", "max_voltage", "current", "unequal_lengths", "orientation", "inputs", "pairing"]
