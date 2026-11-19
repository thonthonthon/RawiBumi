"""Manual module edits: real HTTP, isolated persisted projects and canonical engines."""
from copy import deepcopy
import json

import pytest

from geometry.pvfield import PVFieldPackingSession
from geometry.scene.surface_plane import SurfacePlane
from tests.unit.test_rb_fix_s1_geometry_integrity import Project
from components.design_integration import module_nameplate_w  # D14: the DC nameplate basis


def command(p, kind="move_modules", ids=None, **options):
    data = {"command": kind, "module_instance_ids": ids if ids is not None else [p.modules()[0]["module_instance_id"]], **options}
    return p.client.post(p.url + "/pv-fields/modules/commands", content=json.dumps(data), headers={"Content-Type": "application/json"})


def session(p):
    b = p.bundle()
    return PVFieldPackingSession(b["scene"], p.service._component_definitions(b, "modules"), electrical_design=b["electrical_design"])


def sparse(p):
    modules = p.modules()
    editor = session(p)
    editor.remove_modules([m["module_instance_id"] for m in modules[1:-1]])
    p.service._commit_layout_edit(p.bundle(), editor.scene, [], change_summary="Sparse test layout")
    return modules[0]


def test_delete_preview_oracle_strings_flags_revisions_and_manual(tmp_path):
    p = Project(tmp_path); p.executable()
    before = p.bundle(); ids = [m["module_instance_id"] for m in p.modules()[:3]]
    strings = [s["string_id"] for s in before["electrical_design"]["strings"] if set(ids).intersection(s["module_instance_ids"])]
    definitions = before["pinned_components"]["modules"]
    remaining = [m for m in before["scene"]["module_instances"] if m["module_instance_id"] not in ids]
    power = lambda modules: sum(module_nameplate_w(definitions[m["module_definition_revision_id"]]) for m in modules)
    raw = p.path.read_bytes()
    r = command(p, "delete_modules", ids, dry_run=True); assert r.status_code == 200, r.text
    preview = r.json(); assert preview["string_ids"] == strings
    assert preview["fields"] == [{"pv_field_id": p.field_id, "name": before["scene"]["pv_fields"][0]["name"],
        "module_count_before": len(p.modules()), "module_count_after": len(remaining),
        "stc_power_w_before": power(before["scene"]["module_instances"]), "stc_power_w_after": power(remaining),
        "string_ids": strings, "field_becomes_empty": False}]
    assert p.path.read_bytes() == raw
    refused = command(p, "delete_modules", ids); assert refused.status_code == 422
    assert all(sid in refused.text for sid in strings); assert p.path.read_bytes() == raw
    r = command(p, "delete_modules", ids, discard_dependent_strings=True); assert r.status_code == 200, r.text
    after = p.bundle()
    assert after["scene"]["module_instances"] == remaining
    assert after["electrical_design"]["strings"] == [s for s in before["electrical_design"]["strings"] if s["string_id"] not in strings]
    assert after["scene"]["pv_fields"][0]["layout_status"] == "manual"
    assert after["scene"]["pv_fields"][0]["packing_input_hash"] is None
    assert after["scene"]["revision_number"] == before["scene"]["revision_number"] + 1
    assert after["electrical_design"]["revision_number"] == before["electrical_design"]["revision_number"] + 1


def test_empty_field_is_retained_with_warning_and_other_field_can_execute(tmp_path):
    p = Project(tmp_path)
    view = p.service.add_surface_rectangle(p.pid, name="Second", origin_x_m=20, origin_y_m=0, width_m=8, height_m=8.5, base_elevation_m=6.1)
    surface = view["bundle"]["scene"]["surfaces"][-1]["surface_id"]
    p.service.create_pv_field(p.pid, **{**p.fill, "support_surface_id": surface, "name": "Second field"})
    p.executable()
    ids = [m["module_instance_id"] for m in p.modules() if m["pv_field_id"] == p.field_id]
    preview = command(p, "delete_modules", ids, dry_run=True); assert preview.status_code == 200
    assert preview.json()["fields"][0]["field_becomes_empty"]
    r = command(p, "delete_modules", ids, discard_dependent_strings=True); assert r.status_code == 200, r.text
    assert any(f["pv_field_id"] == p.field_id for f in p.bundle()["scene"]["pv_fields"])
    ready = p.client.get(p.url + "/execution-readiness").json()
    assert ready["ready"], ready
    assert any(f["rule_id"] == "PV_FIELD_EMPTY" and f["severity"] == "warning" and f["entity_id"] == p.field_id for f in ready["findings"])
    assert not any(f["severity"] == "blocking_error" for f in ready["findings"])


def test_rigid_sloped_move_preserves_ids_strings_z_and_one_revision(tmp_path):
    p = Project(tmp_path); p.executable()
    plane = {"slope_deg": 12, "azimuth_deg": 135, "base_elevation_m": 6.1,
             "elevation_reference": {"mode": "explicit_xy", "x_m": 0, "y_m": 0}}
    r = p.client.post(p.url + "/scene/commands", json={"command": {"schema_name": "SceneEditorCommand", "schema_version": "0.1",
        "command_id": "s13b-plane", "command_type": "edit_plane", "target_entity_ids": [p.surface_id], "parameters": plane}})
    assert r.status_code == 200, r.text
    before = p.bundle(); ids = [m["module_instance_id"] for m in p.modules()[:6]]
    raw = p.path.read_bytes()
    preview = command(p, ids=ids, dx_m=.005, dy_m=.1, dry_run=True)
    assert preview.status_code == 200 and preview.json()["moved_count"] == len(ids) and preview.json()["conflicts"] == []
    assert p.path.read_bytes() == raw
    r = command(p, ids=ids, dx_m=.005, dy_m=.1); assert r.status_code == 200, r.text
    after = p.bundle(); surface = SurfacePlane.from_surface(after["scene"]["surfaces"][0])
    for old, new in zip(before["scene"]["module_instances"], after["scene"]["module_instances"]):
        if old["module_instance_id"] not in ids:
            assert new == old; continue
        assert {k: v for k, v in old.items() if k not in {"transform", "metadata"}} == {k: v for k, v in new.items() if k not in {"transform", "metadata"}}
        x, y = old["transform"]["position_x_m"] + .005, old["transform"]["position_y_m"] + .1
        assert new["transform"] == {**old["transform"], "position_x_m": x, "position_y_m": y,
            "position_z_m": surface.elevation_at(x, y) + after["scene"]["pv_fields"][0]["mounting_height_m"]}
    assert after["electrical_design"] == before["electrical_design"]
    assert after["scene"]["revision_number"] == before["scene"]["revision_number"] + 1
    assert after["scene"]["pv_fields"][0]["layout_status"] == "manual"


@pytest.mark.parametrize("case", ["module", "module_touch", "obstacle", "obstacle_setback", "hole", "hole_setback", "keepout", "edge", "perimeter", "other_roof"])
def test_move_refusals_are_structured_and_leave_storage_identical(tmp_path, case):
    p = Project(tmp_path); first = sparse(p)
    x, y = 4., 4.
    if case in {"module", "module_touch"}:
        last = p.modules()[-1]; x, y = last["transform"]["position_x_m"], last["transform"]["position_y_m"]
        if case == "module_touch": x -= p.bundle()["pinned_components"]["modules"][first["module_definition_revision_id"]]["mechanical"]["width_m"]
    elif case.startswith("obstacle"):
        p.service.add_box_obstacle(p.pid, name="Target", origin_x_m=3.5, origin_y_m=3.5, width_m=1, depth_m=1, base_elevation_m=6.1, height_m=2)
        if case == "obstacle_setback": x = 3.5 - .1 - .567
    elif case.startswith("hole"):
        bundle = p.bundle(); bundle["scene"]["surfaces"][0]["boundary_2d"]["holes"] = [[[3.5, 3.5], [4.5, 3.5], [4.5, 4.5], [3.5, 4.5]]]
        p.service.store.save(bundle)
        if case == "hole_setback": x = 3.5 - .1 - .567
    elif case == "keepout":
        p.service.add_surface_rectangle(p.pid, name="Keep-out", origin_x_m=3.5, origin_y_m=3.5, width_m=1, height_m=1, base_elevation_m=6.1, surface_type="exclusion_area", usable_for_pv=False)
    elif case == "edge": x = -2.
    elif case == "perimeter": x = .567 + .1
    elif case == "other_roof":
        p.service.add_surface_rectangle(p.pid, name="Other roof", origin_x_m=20, origin_y_m=0, width_m=8, height_m=8.5, base_elevation_m=6.1)
        x = 24.
    raw = p.path.read_bytes()
    r = command(p, dx_m=x-first["transform"]["position_x_m"], dy_m=y-first["transform"]["position_y_m"])
    if case == "module_touch":
        assert r.status_code == 200, r.text
        assert p.path.read_bytes() != raw
        return
    assert r.status_code == 422, r.text
    conflicts = r.json()["detail"]["conflicts"]; assert conflicts
    expected = {"module": "module_module_overlap", "module_touch": "module_module_overlap", "obstacle": "module_obstacle_overlap",
                "obstacle_setback": "module_obstacle_setback", "hole": "module_over_hole", "hole_setback": "module_outside_support_or_setback",
                "keepout": "module_exclusion_overlap", "edge": "module_outside_support_or_setback", "perimeter": "module_outside_support_or_setback",
                "other_roof": "module_outside_support_or_setback"}[case]
    assert expected in {c["code"] for c in conflicts}
    assert all({"code", "module_instance_id", "other_id", "pv_field_id"} <= c.keys() for c in conflicts)
    assert all(first["module_instance_id"] in {c["module_instance_id"], c["other_id"]} for c in conflicts)
    assert p.path.read_bytes() == raw


def test_unrelated_legacy_overlap_does_not_block_move(tmp_path):
    p = Project(tmp_path); b = p.bundle(); duplicate = deepcopy(p.modules()[1])
    duplicate["module_instance_id"] = "legacy-overlap"
    b["scene"]["module_instances"].append(duplicate); p.service.store.save(b)
    r = command(p, dx_m=.005, dy_m=0); assert r.status_code == 200, r.text


def test_small_overlap_refusal_when_moved_module_is_other_side_of_packer_pair(tmp_path):
    p = Project(tmp_path); first = sparse(p); last = p.modules()[-1]
    width = p.bundle()["pinned_components"]["modules"][first["module_definition_revision_id"]]["mechanical"]["width_m"]
    raw = p.path.read_bytes()
    r = command(p, ids=[last["module_instance_id"]], dx_m=first["transform"]["position_x_m"]+width-1e-7-last["transform"]["position_x_m"],
                dy_m=first["transform"]["position_y_m"]+.01-last["transform"]["position_y_m"])
    assert r.status_code == 422, r.text
    assert any(c["code"] == "module_module_overlap" and c["other_id"] == last["module_instance_id"] for c in r.json()["detail"]["conflicts"])
    assert p.path.read_bytes() == raw


@pytest.mark.parametrize("body", [
    {"module_instance_ids": []}, {"module_instance_ids": ["unknown"]}, {"module_instance_ids": ["same", "same"]},
    {"command": "delete_modules", "dx_m": 0}, {"command": "delete_modules", "dy_m": None},
    {"dx_m": 0}, {"dx_m": float("nan"), "dy_m": 0}, {"dx_m": float("inf"), "dy_m": 0},
    {"dx_m": 10001, "dy_m": 0}, {"dx_m": 0, "dy_m": 0, "extra": True},
])
def test_request_validation_is_422_and_atomic(tmp_path, body):
    p = Project(tmp_path); raw = p.path.read_bytes()
    r = command(p, **{**{"kind": "move_modules"}, **{"ids": body.get("module_instance_ids", [p.modules()[0]["module_instance_id"]])},
        **{k: v for k, v in body.items() if k not in {"module_instance_ids", "command"}}, **({"kind": body["command"]} if "command" in body else {})})
    assert r.status_code == 422, r.text; assert p.path.read_bytes() == raw


def test_engine_group_move_is_one_undo_step_and_rejects_bad_ids(tmp_path):
    p = Project(tmp_path); editor = session(p); before = editor.scene; ids = [m["module_instance_id"] for m in p.modules()[:6]]
    editor.move_modules(ids, .005, .1); assert editor.undo_depth == 1
    assert editor.undo(); assert editor.scene == before
    for invalid in ([], [ids[0], ids[0]], ["unknown"]):
        with pytest.raises(ValueError): editor.move_modules(invalid, 0, 0)
        assert editor.scene == before


def test_concurrent_edit_409_keeps_newer_bundle_and_registry_clears(tmp_path, monkeypatch):
    p = Project(tmp_path); before = deepcopy(p.modules()); original = p.service._commit_layout_edit
    def concurrent(bundle, *args, **kwargs):
        assert p.study._in_progress[p.pid] == 1
        p.service.update_project(p.pid, name="Concurrent name")
        return original(bundle, *args, **kwargs)
    monkeypatch.setattr(p.service, "_commit_layout_edit", concurrent)
    r = command(p, dx_m=.005, dy_m=0); assert r.status_code == 409, r.text
    assert p.modules() == before; assert p.bundle()["project"]["name"] == "Concurrent name"
    assert p.pid not in p.study._in_progress


def test_manual_edits_simulate_and_later_refills_require_discard(tmp_path):
    p = Project(tmp_path); p.executable()
    r = command(p, dx_m=.005, dy_m=0); assert r.status_code == 200, r.text
    for phase in ("move", "delete"):
        if phase == "delete":
            r = command(p, "delete_modules", [m["module_instance_id"] for m in p.modules()[:3]], discard_dependent_strings=True)
            assert r.status_code == 200, r.text
        ready = p.client.get(p.url + "/execution-readiness").json(); assert ready["ready"], ready
        r = p.client.post(p.url + "/simulate", json={}); assert r.status_code == 200, r.text
        assert r.json()["status"] in {"completed", "completed_with_warnings"}
    r = p.client.patch(p.url + "/pv-fields/" + p.field_id, json={"row_pitch_m": 2.7, "discard_dependent_strings": True})
    assert r.status_code == 422 and "discard_manual_layout" in r.text
    r = p.client.post(p.url + "/scene/commands", json={"command": {"schema_name": "SceneEditorCommand", "schema_version": "0.1", "command_id": "s13b-roof",
        "command_type": "move", "target_entity_ids": [p.surface_id], "parameters": {"dx_m": .1, "dy_m": 0}}, "dependent_fields": "apply", "dry_run": True})
    assert r.status_code == 200, r.text
    assert r.json()["dependent_fields"][0]["requires_discard_manual_layout"]
