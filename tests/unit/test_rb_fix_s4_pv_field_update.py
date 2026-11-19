"""S4 update/delete/refill acceptance against real persisted service bundles."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from apps.api.server import create_app
from geometry.pvfield import PVFieldPackingSession
from geometry.pvfield.identity import generated_module_id
from geometry.pvfield.impact import layout_impact_report
from geometry.pvfield.packing import pack_field, replace_field_layout
from geometry.scene import SceneEditorSession
from tests.unit.test_rb_fix_s1_geometry_integrity import Project, MODULE
from components.design_integration import module_nameplate_w  # D14: the DC nameplate basis


def _url(project):
    return project.url + "/pv-fields/" + project.field_id


def _ids(scene, field_id):
    return {m["module_instance_id"] for m in scene["module_instances"] if m["pv_field_id"] == field_id}


def _second_field(project, x=20):
    view = project.service.add_surface_rectangle(project.pid, name="Other roof", origin_x_m=x,
        origin_y_m=0, width_m=8, height_m=8.5, base_elevation_m=6.1, surface_type="flat_roof", usable_for_pv=True)
    sid = view["bundle"]["scene"]["surfaces"][-1]["surface_id"]
    view = project.service.create_pv_field(project.pid, name="Other field", **{**project.fill, "support_surface_id": sid})
    return view["bundle"]["scene"]["pv_fields"][-1]["pv_field_id"]


def _session(project):
    bundle = project.bundle()
    return PVFieldPackingSession(bundle["scene"], bundle["pinned_components"]["modules"],
                                 electrical_design=bundle["electrical_design"])


def _ready(project):
    response = project.client.get(project.url + "/execution-readiness")
    assert response.status_code == 200, response.text
    ready = response.json()
    assert not any(f["rule_id"] in {"SCENE_MODULE_OVERLAP", "SCENE_MODULE_OBSTACLE_OVERLAP", "PV_FIELD_EMPTY"}
                   for f in ready["findings"])
    placed = {m["module_instance_id"] for m in project.modules() if m.get("enabled", True)}
    simulated = {mid for group in ready["execution_plan"]["groups"] for mid in group["module_instance_ids"]}
    warning = [f for f in ready["findings"] if f["rule_id"] == "MODULES_NOT_SIMULATED"]
    assert (warning[0]["context"]["module_count"] if warning else 0) == len(placed - simulated)
    return ready


def _packed_obstacle(project):
    response = project.client.post(project.url + "/obstacles/box", json=project.obstacle(on_module_conflict="remove_modules"))
    assert response.status_code == 200, response.text
    response = project.client.patch(_url(project), json={"azimuth_deg": 0, "discard_manual_layout": True})
    assert response.status_code == 200, response.text


def test_01_tilt_update_is_in_place_and_persists(tmp_path):
    project = Project(tmp_path)
    before = project.bundle()
    expected = _session(project)
    expected.update_field(project.field_id, tilt_deg=15)
    response = project.client.patch(_url(project), json={"tilt_deg": 15})
    assert response.status_code == 200, response.text
    after = project.bundle()
    assert len(after["scene"]["pv_fields"]) == 1
    assert after["scene"]["pv_fields"][0]["tilt_deg"] == 15
    assert _ids(before["scene"], project.field_id).isdisjoint(_ids(after["scene"], project.field_id))
    assert _ids(after["scene"], project.field_id) == _ids(expected.scene, project.field_id)
    assert after["project"]["project_revision"]["revision_number"] == before["project"]["project_revision"]["revision_number"] + 1
    assert after["electrical_design"] == before["electrical_design"]
    assert create_app(store_root=project.service.store.root).state.project_service.get_bundle(project.pid) == after
    _ready(project)


def test_02_strung_update_requires_discard_and_saves_once_atomically(tmp_path, monkeypatch):
    project = Project(tmp_path)
    _second_field(project)
    project.executable()
    before = project.bundle()
    before_bytes = project.path.read_bytes()
    field_ids = _ids(before["scene"], project.field_id)
    affected = {s["string_id"] for s in before["electrical_design"]["strings"] if field_ids.intersection(s["module_instance_ids"])}
    response = project.client.patch(_url(project), json={"tilt_deg": 15})
    assert response.status_code == 422
    assert all(s in str(response.json()["detail"]) for s in affected)
    assert project.path.read_bytes() == before_bytes
    with monkeypatch.context() as context:
        def fail_save(bundle):
            raise OSError("injected save failure")
        context.setattr(project.service.store, "save", fail_save)
        with pytest.raises(OSError, match="injected save failure"):
            project.service.update_pv_field(project.pid, project.field_id, tilt_deg=15, discard_dependent_strings=True)
        assert project.path.read_bytes() == before_bytes
    saved = []
    save = project.service.store.save
    def capture(bundle):
        saved.append(deepcopy(bundle))
        return save(bundle)
    monkeypatch.setattr(project.service.store, "save", capture)
    response = project.client.patch(_url(project), json={"tilt_deg": 15, "discard_dependent_strings": True})
    assert response.status_code == 200, response.text
    after = project.bundle()
    assert len(saved) == 1
    assert after["electrical_design"]["strings"] == [s for s in before["electrical_design"]["strings"] if s["string_id"] not in affected]
    for key in ("scene", "electrical_design"):
        assert after[key]["revision_number"] == before[key]["revision_number"] + 1
    assert after["project"]["project_revision"]["revision_number"] == before["project"]["project_revision"]["revision_number"] + 1
    revision = after["project"]["project_revision"]
    assert revision["scene_revision_id"] == after["scene"]["revision_id"]
    assert revision["electrical_revision_id"] == after["electrical_design"]["electrical_revision_id"]
    _ready(project)


def test_03_setback_preserves_unmoved_ids_and_only_deletes_affected_strings(tmp_path):
    project = Project(tmp_path)
    _packed_obstacle(project)
    project.service.create_strings(project.pid, string_length=3)
    before = project.bundle()
    response = project.client.patch(_url(project), json={"obstacle_setback_m": 0.5, "dry_run": True})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["retained_module_count"] > 0 and preview["removed_module_count"] > 0
    assert len(preview["string_ids"]) < len(before["electrical_design"]["strings"])
    response = project.client.patch(_url(project), json={"obstacle_setback_m": 0.5, "discard_dependent_strings": True})
    assert response.status_code == 200, response.text
    after = project.bundle()
    assert _ids(after["scene"], project.field_id) <= _ids(before["scene"], project.field_id)
    assert after["electrical_design"]["strings"] == [s for s in before["electrical_design"]["strings"] if s["string_id"] not in preview["string_ids"]]
    _ready(project)


def test_04_dry_run_counts_power_and_dependency_preview_are_exact(tmp_path):
    project = Project(tmp_path)
    project.executable()
    before = project.path.read_bytes()
    session = _session(project)
    result = session.update_field(project.field_id, tilt_deg=15)
    preview = project.client.patch(_url(project), json={"tilt_deg": 15, "dry_run": True}).json()
    old_ids = _ids(project.bundle()["scene"], project.field_id)
    new_ids = _ids(session.scene, project.field_id)
    assert preview["dry_run"] and preview["pv_field_id"] == project.field_id
    assert preview["module_count_before"] == len(old_ids)
    assert preview["module_count_after"] == len(new_ids)
    assert preview["retained_module_count"] == 0
    assert preview["added_module_count"] == len(new_ids - old_ids)
    assert preview["removed_module_count"] == len(old_ids - new_ids)
    pmp = module_nameplate_w(project.bundle()["pinned_components"]["modules"][MODULE])
    assert preview["stc_power_w_before"] == pytest.approx(len(old_ids) * pmp)
    assert preview["stc_power_w_after"] == pytest.approx(len(new_ids) * pmp)
    assert preview["layout_impact"] == result["layout_impact"]
    assert preview["string_ids"] == sorted(s["string_id"] for s in project.bundle()["electrical_design"]["strings"])
    assert preview["requires_discard_dependent_strings"] and not preview["requires_discard_manual_layout"]
    assert preview["conflicts"] == []
    assert project.path.read_bytes() == before


def test_05_name_only_update_keeps_manual_placements_and_needs_no_flags(tmp_path):
    project = Project(tmp_path)
    session = _session(project)
    session.remove_modules([project.modules()[0]["module_instance_id"]])
    bundle = project.bundle()
    bundle["scene"] = session.scene
    project.service.store.save(bundle)
    before = project.bundle()
    response = project.client.patch(_url(project), json={"name": "Renamed"})
    assert response.status_code == 200
    after = project.bundle()
    assert after["scene"]["module_instances"] == before["scene"]["module_instances"]
    assert after["scene"]["pv_fields"][0]["name"] == "Renamed"
    assert after["scene"]["pv_fields"][0]["layout_status"] == "manual"
    assert after["electrical_design"] == before["electrical_design"]
    _ready(project)


def test_06_update_refuses_cross_field_overlap_with_no_save(tmp_path):
    project = Project(tmp_path)
    bundle = project.bundle()
    second = deepcopy(bundle["scene"]["pv_fields"][0])
    second["pv_field_id"] = "other-half"
    bundle["scene"]["pv_fields"].append(second)
    for module in bundle["scene"]["module_instances"]:
        if module["column_index"] >= 3:
            module["pv_field_id"] = second["pv_field_id"]
    project.service.store.save(bundle)
    assert project.layout()["status"] == "ok"
    before = project.path.read_bytes()
    preview = project.client.patch(_url(project), json={"row_pitch_m": 2.7, "dry_run": True})
    assert preview.status_code == 200 and preview.json()["conflicts"]
    response = project.client.patch(_url(project), json={"row_pitch_m": 2.7})
    assert response.status_code == 422
    assert any(c["code"] == "module_module_overlap" for c in response.json()["detail"]["conflicts"])
    assert project.path.read_bytes() == before


def test_07_update_refuses_empty_layout_without_changing_field(tmp_path):
    project = Project(tmp_path)
    before = project.path.read_bytes()
    response = project.client.patch(_url(project), json={"perimeter_setback_m": 100})
    assert response.status_code == 422
    assert response.json()["detail"] == "PV field packing produced zero modules; adjust surface, setback, orientation, row pitch, or module selection"
    assert project.path.read_bytes() == before
    _ready(project)


def test_08_manual_layout_requires_its_own_discard_flag(tmp_path):
    project = Project(tmp_path)
    assert project.client.post(project.url + "/obstacles/box", json=project.obstacle(on_module_conflict="remove_modules")).status_code == 200
    before = project.path.read_bytes()
    preview = project.client.patch(_url(project), json={"tilt_deg": 15, "dry_run": True}).json()
    assert preview["requires_discard_manual_layout"]
    response = project.client.patch(_url(project), json={"tilt_deg": 15})
    assert response.status_code == 422 and "discard_manual_layout" in response.json()["detail"]
    assert project.path.read_bytes() == before
    assert project.client.patch(_url(project), json={"tilt_deg": 15, "discard_manual_layout": True}).status_code == 200
    assert project.bundle()["scene"]["pv_fields"][0]["layout_status"] == "packed"
    _ready(project)


def test_09_update_validation_matches_create_and_rejects_unknown_inputs(tmp_path):
    project = Project(tmp_path)
    before = project.path.read_bytes()
    for invalid in ({"tilt_deg": 95}, {"row_pitch_m": 0.1}, {"perimeter_setback_m": -1}):
        created = project.client.post(project.url + "/pv-fields", json={**project.fill, **invalid})
        updated = project.client.patch(_url(project), json=invalid)
        assert created.status_code == updated.status_code == 422
        assert created.json()["detail"] == updated.json()["detail"]
    assert project.client.patch(_url(project), json={}).status_code == 422
    assert project.client.patch(_url(project), json={"unknown": 1}).status_code == 422
    assert project.client.patch(project.url + "/pv-fields/missing", json={"tilt_deg": 15}).status_code == 422
    assert project.client.patch("/api/projects/missing/pv-fields/missing", json={"tilt_deg": 15}).status_code == 404
    assert project.path.read_bytes() == before


def test_10_delete_unstrung_field_preserves_other_fields_and_pins(tmp_path):
    project = Project(tmp_path)
    other = _second_field(project)
    before = project.bundle()
    response = project.client.delete(_url(project))
    assert response.status_code == 200, response.text
    after = project.bundle()
    assert [f["pv_field_id"] for f in after["scene"]["pv_fields"]] == [other]
    assert after["scene"]["module_instances"] == [m for m in before["scene"]["module_instances"] if m["pv_field_id"] == other]
    assert after["pinned_components"] == before["pinned_components"]
    assert after["electrical_design"] == before["electrical_design"]
    _ready(project)
    cors = project.client.options(_url(project), headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "DELETE"})
    assert cors.status_code == 200 and "DELETE" in cors.headers["access-control-allow-methods"]
    assert project.client.delete(_url(project)).status_code == 422


def test_11_delete_preview_and_flag_cover_mixed_field_strings(tmp_path):
    project = Project(tmp_path)
    _second_field(project)
    project.executable()
    bundle = project.bundle()
    field_ids = _ids(bundle["scene"], project.field_id)
    mixed = next(s for s in bundle["electrical_design"]["strings"] if not field_ids.intersection(s["module_instance_ids"]))
    mixed["module_instance_ids"].append(next(iter(sorted(field_ids))))
    project.service.store.save(bundle)
    before = project.path.read_bytes()
    ids = _ids(bundle["scene"], project.field_id)
    strings = sorted(s["string_id"] for s in bundle["electrical_design"]["strings"] if ids.intersection(s["module_instance_ids"]))
    response = project.client.delete(_url(project), params={"dry_run": True})
    assert response.status_code == 200
    preview = response.json()
    assert preview["module_count"] == 18 and preview["string_ids"] == strings
    assert preview["stc_power_w"] == pytest.approx(18 * module_nameplate_w(bundle["pinned_components"]["modules"][MODULE]))
    assert preview["requires_discard_dependent_strings"]
    assert project.client.delete(_url(project)).status_code == 422
    assert project.path.read_bytes() == before
    assert project.client.delete(_url(project), params={"discard_dependent_strings": True}).status_code == 200
    assert project.bundle()["electrical_design"]["strings"] == [s for s in bundle["electrical_design"]["strings"] if s["string_id"] not in strings]
    _ready(project)


def test_12_obstacle_refill_preview_commit_move_and_manual_guards(tmp_path):
    project = Project(tmp_path / "strings")
    project.executable()
    before = project.bundle()
    before_bytes = project.path.read_bytes()
    request = project.obstacle(on_module_conflict="refill_field")
    preview = project.client.post(project.url + "/obstacles/box", json={**request, "dry_run": True}).json()["options"]["refill_field"]
    assert preview["available"] and len(preview["fields"]) == 1
    field = preview["fields"][0]
    assert field["module_count_before"] == 18 and field["module_count_after"] == 15
    assert field["removed_module_count"] == 3 and field["added_module_count"] == 0
    assert preview["requires_discard_dependent_strings"] and not preview["requires_discard_manual_layout"]
    assert project.client.post(project.url + "/obstacles/box", json=request).status_code == 422
    assert project.path.read_bytes() == before_bytes
    response = project.client.post(project.url + "/obstacles/box", json={**request, "discard_dependent_strings": True})
    assert response.status_code == 200, response.text
    assert project.bundle()["electrical_design"]["strings"] == [s for s in before["electrical_design"]["strings"] if s["string_id"] not in preview["string_ids"]]
    assert project.layout()["status"] == "ok"
    _ready(project)
    manual = Project(tmp_path / "manual")
    assert manual.client.post(manual.url + "/obstacles/box", json=manual.obstacle(on_module_conflict="remove_modules")).status_code == 200
    oid = manual.bundle()["scene"]["obstacles"][0]["obstacle_id"]
    move = {"entity_id": oid, "dx_m": 1.154, "dy_m": 0, "on_module_conflict": "refill_field"}
    before_bytes = manual.path.read_bytes()
    preview = manual.client.post(manual.url + "/scene/move", json={**move, "dry_run": True}).json()
    assert preview["options"]["refill_field"]["requires_discard_manual_layout"]
    assert manual.client.post(manual.url + "/scene/move", json=move).status_code == 422
    assert manual.path.read_bytes() == before_bytes
    assert manual.client.post(manual.url + "/scene/move", json={**move, "discard_manual_layout": True}).status_code == 200
    _ready(manual)


def test_12b_opted_out_refill_is_unavailable_and_atomic_across_fields(tmp_path):
    for multi in (False, True):
        project = Project(tmp_path / str(multi))
        if multi:
            _second_field(project)
        bundle = project.bundle()
        rules = {"use_scene_obstacles": False, "obstacle_ids": []}
        bundle["scene"]["pv_fields"][0]["exclusion_rules"] = rules
        project.service.store.save(bundle)
        before = project.path.read_bytes()
        request = project.obstacle(on_module_conflict="refill_field", **({"width_m": 22.508} if multi else {}))
        response = project.client.post(project.url + "/obstacles/box", json={**request, "dry_run": True})
        assert response.status_code == 200, response.text
        preview = response.json()["options"]["refill_field"]
        assert not preview["available"] and preview["reason"] == "field_exclusion_rules_ignore_obstacle"
        assert len(preview["remaining_conflicts"]) == (6 if multi else 3)
        assert len(preview["fields"]) == (2 if multi else 1)
        response = project.client.post(project.url + "/obstacles/box", json={**request,
            "discard_dependent_strings": True, "discard_manual_layout": True})
        assert response.status_code == 422
        def pairs(conflicts):
            return {(c["code"], c["module_instance_id"], c["pv_field_id"]) for c in conflicts}
        assert pairs(response.json()["detail"]["conflicts"]) == pairs(preview["remaining_conflicts"])
        assert project.path.read_bytes() == before
        assert project.bundle()["scene"]["pv_fields"][0]["exclusion_rules"] == rules
        response = project.client.post(project.url + "/obstacles/box", json={**request, "on_module_conflict": "remove_modules"})
        assert response.status_code == 200, response.text
        assert project.bundle()["scene"]["pv_fields"][0]["exclusion_rules"] == rules
        _ready(project)


def test_12c_patch_refuses_remaining_obstacle_overlap_but_name_only_is_allowed(tmp_path):
    project = Project(tmp_path)
    bundle = project.bundle()
    editor = SceneEditorSession(bundle["scene"])
    editor.draw_box_obstacle(obstacle_id="old-obstacle", scene_object_id="obj-old-obstacle", **project.obstacle())
    bundle["scene"] = editor.scene
    bundle["scene"]["pv_fields"][0]["exclusion_rules"] = {"use_scene_obstacles": False, "obstacle_ids": []}
    project.service.store.save(bundle)
    before = project.path.read_bytes()
    preview = project.client.patch(_url(project), json={"mounting_height_m": 0.3, "dry_run": True}).json()
    assert len(preview["conflicts"]) == 3
    response = project.client.patch(_url(project), json={"mounting_height_m": 0.3,
        "discard_manual_layout": True, "discard_dependent_strings": True})
    assert response.status_code == 422 and response.json()["detail"]["conflicts"] == preview["conflicts"]
    assert project.path.read_bytes() == before
    assert project.client.patch(_url(project), json={"name": "Name only"}).status_code == 200
    assert project.bundle()["scene"]["pv_fields"][0]["exclusion_rules"] == bundle["scene"]["pv_fields"][0]["exclusion_rules"]


def test_13_no_conflict_obstacles_accept_both_explicit_options(tmp_path):
    project = Project(tmp_path)
    for index, option in enumerate(("refill_field", "remove_modules")):
        assert project.client.post(project.url + "/obstacles/box", json=project.obstacle(
            origin_x_m=50 + index * 10, on_module_conflict=option,
        )).status_code == 200
    assert len(project.bundle()["scene"]["obstacles"]) == 2
    assert len(project.modules()) == 18
    _ready(project)


def test_14_readiness_after_update_and_restring_then_actual_simulate(tmp_path):
    project = Project(tmp_path)
    project.executable()
    assert project.client.patch(_url(project), json={"tilt_deg": 15, "discard_dependent_strings": True}).status_code == 200
    ready = _ready(project)
    assert next(f for f in ready["findings"] if f["rule_id"] == "MODULES_NOT_SIMULATED")["context"]["module_count"] == len(project.modules())
    project.service.create_strings(project.pid, string_length=6)
    iid = project.bundle()["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    project.service.assign_strings(project.pid, inverter_instance_id=iid)
    assert _ready(project)["ready"]
    response = project.client.post(project.url + "/simulate", json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] in {"completed", "completed_with_warnings"}
    assert project.client.delete(_url(project), params={"discard_dependent_strings": True}).status_code == 200
    _ready(project)


def test_15_engine_commands_are_one_undo_step_and_electrical_is_immutable(tmp_path):
    project = Project(tmp_path)
    project.executable()
    session = _session(project)
    original = session.scene
    electrical = session.electrical_design
    for method, args, kwargs in ((session.update_field, ("missing",), {"tilt_deg": 15}),
                                 (session.delete_field, ("missing",), {}),
                                 (session.update_field, (project.field_id,), {})):
        with pytest.raises(ValueError):
            method(*args, **kwargs)
        assert session.scene == original and session.undo_depth == 0
    session.update_field(project.field_id, tilt_deg=15, azimuth_deg=360)
    updated = session.scene
    assert updated["pv_fields"][0]["azimuth_deg"] == 0
    assert session.undo_depth == 1 and session.electrical_design == electrical
    assert session.undo() and session.scene == original
    assert session.redo() and session.scene == updated
    session.delete_field(project.field_id)
    assert session.undo_depth == 2 and not session.scene["module_instances"]
    assert session.undo() and session.scene == updated
    assert session.electrical_design == electrical


def test_16_mounting_height_replaces_ids_against_original_identity_basis(tmp_path):
    project = Project(tmp_path)
    project.executable()
    bundle = project.bundle()
    original = bundle["scene"]
    candidate = deepcopy(original["pv_fields"][0])
    candidate["mounting_height_m"] = 0.3
    packed = pack_field(original, candidate, bundle["pinned_components"]["modules"][MODULE])
    expected = replace_field_layout(original, packed)
    session = _session(project)
    result = session.update_field(project.field_id, mounting_height_m=0.3)
    assert session.scene == expected
    ids = _ids(expected, project.field_id)
    assert ids.isdisjoint(_ids(original, project.field_id))
    field = session.scene["pv_fields"][0]
    assert all(m["module_instance_id"] == generated_module_id(field, m) for m in session.scene["module_instances"])
    impact = result["layout_impact"]
    assert set(impact["invalidated_module_ids"]) == _ids(original, project.field_id)
    assert {s["string_id"] for s in impact["affected_strings"]} == {s["string_id"] for s in bundle["electrical_design"]["strings"]}
    assert impact == layout_impact_report(original, expected, project.field_id, electrical_design=bundle["electrical_design"])


def test_17_setback_and_pitch_preserve_only_equivalent_original_placements(tmp_path):
    project = Project(tmp_path)
    _packed_obstacle(project)
    before = project.bundle()["scene"]
    for parameters in ({"obstacle_setback_m": 0.5}, {"row_pitch_m": 2.7}):
        session = _session(project)
        impact = session.update_field(project.field_id, **parameters)["layout_impact"]
        after = session.scene
        old_by_position = {(m["transform"]["position_x_m"], m["transform"]["position_y_m"]): m["module_instance_id"] for m in before["module_instances"]}
        unchanged = []
        for module in after["module_instances"]:
            position = (module["transform"]["position_x_m"], module["transform"]["position_y_m"])
            if position in old_by_position:
                assert module["module_instance_id"] == old_by_position[position]
                unchanged.append(module["module_instance_id"])
        assert unchanged and impact["retained_module_ids"] == sorted(unchanged)
        assert impact == layout_impact_report(before, after, project.field_id, electrical_design=project.bundle()["electrical_design"])


def test_18_failed_optional_refill_keeps_reject_and_removal_available(tmp_path, monkeypatch):
    original_rebuild = PVFieldPackingSession.rebuild_field
    for error_type in (ValueError, KeyError):
        for multi in (False, True):
            project = Project(tmp_path / error_type.__name__ / str(multi))
            if multi:
                _second_field(project)
            request = project.obstacle(**({"width_m": 22.508} if multi else {}))
            baseline = project.client.post(project.url + "/obstacles/box", json={**request, "dry_run": True}).json()
            removal = baseline["options"]["remove_modules"]
            before = project.path.read_bytes()
            modules = {m["module_instance_id"]: m for m in project.modules()}
            # On two fields, fail after one real successful draft rebuild to
            # prove the partially rebuilt scene never leaks into another option.
            failing_field = sorted(f["pv_field_id"] for f in project.bundle()["scene"]["pv_fields"])[-1]
            error = error_type("simulated rebuild failure")
            def fail_rebuild(session, field_id):
                if field_id == failing_field:
                    raise error
                return original_rebuild(session, field_id)
            with monkeypatch.context() as context:
                context.setattr(PVFieldPackingSession, "rebuild_field", fail_rebuild)
                for option in ("reject", "remove_modules", "refill_field"):
                    response = project.client.post(project.url + "/obstacles/box", json={
                        **request, "on_module_conflict": option, "dry_run": True,
                    })
                    assert response.status_code == 200, response.text
                    preview = response.json()
                    assert preview["options"]["refill_field"] == {
                        "available": False, "reason": "refill_unavailable", "message": str(error),
                    }
                    assert preview["options"]["remove_modules"] == removal
                    assert project.path.read_bytes() == before
                response = project.client.post(project.url + "/obstacles/box", json={**request, "on_module_conflict": "reject"})
                assert response.status_code == 422
                assert "Obstacle conflicts with modules" in response.json()["detail"]["message"]
                assert response.json()["detail"]["options"]["remove_modules"] == removal
                assert project.path.read_bytes() == before
                response = project.client.post(project.url + "/obstacles/box", json={
                    **request, "on_module_conflict": "refill_field", "discard_dependent_strings": True,
                    "discard_manual_layout": True,
                })
                assert response.status_code == 422
                assert response.json()["detail"]["message"] == str(error)
                assert response.json()["detail"]["options"]["refill_field"]["reason"] == "refill_unavailable"
                assert project.path.read_bytes() == before
                response = project.client.post(project.url + "/obstacles/box", json={**request, "on_module_conflict": "remove_modules"})
                assert response.status_code == 200, response.text
            survivors = {m["module_instance_id"]: m for m in project.modules()}
            assert survivors == {mid: m for mid, m in modules.items() if mid not in removal["module_instance_ids"]}
            assert len(project.bundle()["scene"]["obstacles"]) == 1
            _ready(project)
