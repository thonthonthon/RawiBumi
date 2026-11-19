"""S11a: real scene commands and packer-consistent, plan-only keep-outs."""
from copy import deepcopy
import json
import math

import pytest

from geometry.scene import SceneEditorSession
from geometry.pvfield import ModuleFootprint, PVFieldPackingSession, rectangle_polygon, polygons_overlap_or_touch
from geometry.pvfield.packing import _resolved_exclusions
from geometry.pvfield.scene_layout import validate_scene_layout
from tests.unit.test_rb_fix_s2_honest_preflight import Project
from tests.unit.test_rb_fix_s1_geometry_integrity import Project as GeometryProject
from tests.unit.test_rb_fix_s3_scene_commands import _command, _send, _surface
from components.design_integration import module_nameplate_w  # D14: the DC nameplate basis


def project(tmp_path, **kwargs):
    p = Project(tmp_path, weather=False, strings=False, **kwargs)
    p.surface_id = p.bundle()["scene"]["surfaces"][0]["surface_id"]
    p.field_id = p.bundle()["scene"]["pv_fields"][0]["pv_field_id"]
    return p


def module_polygon(bundle, module):
    field = next(f for f in bundle["scene"]["pv_fields"] if f["pv_field_id"] == module["pv_field_id"])
    definition = bundle["pinned_components"]["modules"][module["module_definition_revision_id"]]
    footprint = ModuleFootprint.from_definition(definition, field["orientation"], field["tilt_deg"])
    t = module["transform"]
    return rectangle_polygon((t["position_x_m"], t["position_y_m"]),
        footprint.plan_projection_width_m, footprint.plan_projection_height_m, t["rotation_z_deg"])


def zone_points(p, *, kind="inside"):
    bundle = p.bundle()
    modules = sorted(bundle["scene"]["module_instances"], key=lambda m: m["transform"]["position_x_m"])
    first = module_polygon(bundle, modules[0]); third = module_polygon(bundle, modules[2])
    x = min(point[0] for point in first) - .05
    right = min(point[0] for point in third) + .1
    y = min(point[1] for point in first)
    low, high = {"inside": (y + .1, y + .3), "contact": (y - .2, y),
                 "clear": (y - .4, y - .2), "tiny": (y - .2, y + 5e-8)}[kind]
    return [[x, low], [right, low], [right, high], [x, high]]


def zone(p, points=None, *, route="polygon", surface_type="exclusion_area", **options):
    points = points or zone_points(p)
    parameters = {"name": "S11a keep-out", "surface_type": surface_type,
                  "base_elevation_m": 0, "usable_for_pv": False}
    if route == "polygon":
        return _send(p, "draw_polygon", [], {**parameters, "vertices": points}, **options)
    return p.client.post(p.url + "/surfaces/rectangle", json={**parameters,
        "origin_x_m": points[0][0], "origin_y_m": points[0][1],
        "width_m": points[1][0] - points[0][0], "height_m": points[2][1] - points[1][1], **options})


def scene_with_zone(p, points, surface_type="exclusion_area"):
    editor = SceneEditorSession(p.bundle()["scene"])
    editor.draw_polygon(surface_id="oracle-keepout", scene_object_id="obj-oracle-keepout",
        name="Independent oracle", vertices=points, surface_type=surface_type,
        base_elevation_m=0, usable_for_pv=False)
    return editor.scene


def oracle_ids(bundle, scene):
    """Independent packing primitive + resolved selection, never the detector."""
    fields = {f["pv_field_id"]: f for f in scene["pv_fields"]}
    supports = {s["surface_id"]: s for s in scene["surfaces"]}
    exclusions = {fid: _resolved_exclusions(scene, field, supports[field["support_surface_id"]])[0]
                  for fid, field in fields.items()}
    return {module["module_instance_id"] for module in bundle["scene"]["module_instances"]
            if any(polygons_overlap_or_touch(module_polygon(bundle, module), vertices)
                   for _, vertices in exclusions[module["pv_field_id"]])}


def test_01_exact_engine_geometry_provenance_and_undo(tmp_path):
    p = project(tmp_path); free = _surface(p); sid = free["surface_id"]
    editor = SceneEditorSession(p.bundle()["scene"]); before = editor.scene
    editor.insert_vertex(sid, edge_index=0, x_m=22, y_m=-1)
    changed = editor.scene["surfaces"][-1]
    assert changed["boundary_2d"]["vertices"] == [[20, 0], [22, -1], [24, 0], [24, 3], [20, 3]]
    assert [r["edge_index"] for r in changed["edge_dimension_sources"]] == list(range(5))
    assert all(r["source"] == "derived" for r in changed["edge_dimension_sources"][:2])
    assert editor.undo_depth == 1
    editor.undo(); assert editor.scene == before
    editor.redo(); editor.delete_vertex(sid, vertex_index=1)
    assert editor.scene["surfaces"][-1]["boundary_2d"]["vertices"] == free["boundary_2d"]["vertices"]
    assert [r["edge_index"] for r in editor.scene["surfaces"][-1]["edge_dimension_sources"]] == list(range(4))
    editor.move_edge(sid, edge_index=2, dx_m=0, dy_m=1)
    assert editor.scene["surfaces"][-1]["boundary_2d"]["vertices"] == [[20, 0], [24, 0], [24, 4], [20, 4]]
    assert editor.undo_depth == 3
    editor.undo(); assert editor.scene["surfaces"][-1]["boundary_2d"]["vertices"] == free["boundary_2d"]["vertices"]


@pytest.mark.parametrize("kind,parameters", [
    ("insert_vertex", {"edge_index": 0, "x_m": 20, "y_m": 0}),
    ("insert_vertex", {"edge_index": 99, "x_m": 22, "y_m": 0}),
    ("insert_vertex", {"edge_index": 0, "x_m": math.nan, "y_m": 0}),
    ("move_edge", {"edge_index": 0, "dx_m": 0, "dy_m": 3}),
    ("move_edge", {"edge_index": 4, "dx_m": 0, "dy_m": 1}),
    ("move_edge", {"edge_index": 0, "dx_m": math.inf, "dy_m": 0}),
    ("delete_vertex", {"vertex_index": 99}),
])
def test_01_invalid_geometry_is_atomic(tmp_path, kind, parameters):
    p = project(tmp_path); sid = _surface(p)["surface_id"]
    editor = SceneEditorSession(p.bundle()["scene"]); before = editor.scene
    with pytest.raises((ValueError, IndexError)): getattr(editor, kind)(sid, **parameters)
    assert editor.scene == before and editor.undo_depth == 0


def test_01_minimum_vertices_open_lines_and_locks(tmp_path):
    p = project(tmp_path); sid = _surface(p)["surface_id"]
    scene = p.bundle()["scene"]; scene["surfaces"][-1]["locked"] = True
    for kind, parameters in [("insert_vertex", {"edge_index": 0, "x_m": 22, "y_m": -1}),
                             ("delete_vertex", {"vertex_index": 1}),
                             ("move_edge", {"edge_index": 0, "dx_m": 0, "dy_m": -1})]:
        editor = SceneEditorSession(scene)
        with pytest.raises(ValueError, match="locked"): getattr(editor, kind)(sid, **parameters)
        assert editor.scene == scene and editor.undo_depth == 0
    scene["surfaces"][-1]["locked"] = False
    editor = SceneEditorSession(scene); editor.delete_vertex(sid, vertex_index=1)
    before = editor.scene
    with pytest.raises(ValueError, match="at least 3"): editor.delete_vertex(sid, vertex_index=1)
    assert editor.scene == before
    scene = p.bundle()["scene"]
    scene["reference_lines"] = [{"reference_line_id": "line", "scene_object_id": "obj-line",
        "vertices": [[0, 0], [2, 0]], "locked": False}]
    editor = SceneEditorSession(scene)
    with pytest.raises(ValueError, match="at least 2"): editor.delete_vertex("line", vertex_index=0)
    editor.insert_vertex("line", edge_index=0, x_m=1, y_m=0)
    editor.move_edge("line", edge_index=1, dx_m=0, dy_m=1)
    assert editor.scene["reference_lines"][0]["vertices"] == [[0, 0], [1, 1], [2, 1]]
    editor.delete_vertex("line", vertex_index=0)
    assert editor.scene["reference_lines"][0]["vertices"] == [[1, 1], [2, 1]]


def test_01_obstacle_height_and_shape_parameterization(tmp_path):
    p = project(tmp_path)
    p.service.add_box_obstacle(p.pid, name="Free", origin_x_m=40, origin_y_m=0,
        width_m=2, depth_m=2, base_elevation_m=0, height_m=1)
    obstacle = p.bundle()["scene"]["obstacles"][0]; oid = obstacle["obstacle_id"]
    for kind, parameters in [("insert_vertex", {"edge_index": 0, "x_m": 41, "y_m": -1}),
                             ("delete_vertex", {"vertex_index": 1}),
                             ("move_edge", {"edge_index": 0, "dx_m": 0, "dy_m": -1}),
                             ("edit_height", {"height_m": 0})]:
        editor = SceneEditorSession(p.bundle()["scene"]); before = editor.scene
        getattr(editor, kind)(oid, **parameters)
        changed = editor.scene["obstacles"][0]
        assert changed["dimensions"]["parameterization_valid"] is False
        assert changed["geometry_source"] == "user_override" and editor.undo_depth == 1
        editor.undo(); assert editor.scene == before
        locked = deepcopy(before); locked["obstacles"][0]["locked"] = True
        with pytest.raises(ValueError, match="locked"): getattr(SceneEditorSession(locked), kind)(oid, **parameters)
    for height in (-1, math.nan, math.inf):
        editor = SceneEditorSession(p.bundle()["scene"]); before = editor.scene
        with pytest.raises(ValueError): editor.edit_height(oid, height_m=height)
        assert editor.scene == before and editor.undo_depth == 0
    with pytest.raises(ValueError, match="obstacle"):
        SceneEditorSession(p.bundle()["scene"]).edit_height(p.surface_id, height_m=1)


@pytest.mark.parametrize("kind,parameters", [
    ("insert_vertex", {"edge_index": 0, "x_m": 22, "y_m": -1}),
    ("delete_vertex", {"vertex_index": 1}),
    ("move_edge", {"edge_index": 2, "dx_m": 0, "dy_m": 1}),
    ("edit_height", {"height_m": 2}),
])
def test_02_http_validation_single_target_bounds_and_one_revision(tmp_path, kind, parameters):
    p = project(tmp_path); sid = _surface(p)["surface_id"]
    if kind == "edit_height":
        p.service.add_box_obstacle(p.pid, name="Free", origin_x_m=40, origin_y_m=0,
            width_m=2, depth_m=2, base_elevation_m=0, height_m=1)
        sid = p.bundle()["scene"]["obstacles"][0]["obstacle_id"]
    before = p.bundle()
    response = _send(p, kind, [sid], parameters)
    assert response.status_code == 200, response.text
    after = p.bundle()
    assert after["scene"]["revision_number"] == before["scene"]["revision_number"] + 1
    assert after["project"]["project_revision"]["revision_number"] == before["project"]["project_revision"]["revision_number"] + 1
    snapshot = p.path.read_bytes()
    for ids in ([], [sid, p.surface_id]):
        assert _send(p, kind, ids, parameters).status_code == 422
    invalid = [{**parameters, "unknown": 1}]
    for key, value in parameters.items():
        invalid.append({**parameters, key: True if key.endswith("index") else math.nan})
    if kind == "edit_height": invalid.extend([{"height_m": -1}, {"height_m": 1001}])
    if kind == "insert_vertex": invalid.append({**parameters, "x_m": 50_001})
    if kind == "move_edge": invalid.append({**parameters, "dx_m": 50_001})
    for params in invalid:
        response = p.client.post(p.url + "/scene/commands", content=json.dumps(_command(kind, [sid], params)),
                                 headers={"Content-Type": "application/json"})
        assert response.status_code == 422, response.text
        assert p.path.read_bytes() == snapshot


@pytest.mark.parametrize("route", ["polygon", "rectangle"])
@pytest.mark.parametrize("surface_type", ["exclusion_area", "walkway"])
def test_03_keepout_preview_removal_oracle_fresh_fill_and_strings(tmp_path, route, surface_type):
    p = project(tmp_path); before = p.bundle(); snapshot = p.path.read_bytes()
    points = zone_points(p); draft = scene_with_zone(p, points, surface_type)
    expected = oracle_ids(before, draft)
    assert len(expected) == 3
    packing = PVFieldPackingSession(draft, before["pinned_components"]["modules"], electrical_design=before["electrical_design"])
    packing.rebuild_field(p.field_id)
    fresh_exclusion = {m["module_instance_id"] for m in before["scene"]["module_instances"]} - {
        m["module_instance_id"] for m in packing.scene["module_instances"]}
    assert fresh_exclusion == expected
    refusal = zone(p, points, route=route, surface_type=surface_type)
    assert refusal.status_code == 422, refusal.text
    detail = refusal.json()["detail"]
    assert set(detail["options"]["remove_modules"]["module_instance_ids"]) == expected
    assert all(c["code"] == "module_exclusion_overlap" for c in detail["conflicts"])
    preview = zone(p, points, route=route, surface_type=surface_type, dry_run=True)
    assert preview.status_code == 200, preview.text
    options = preview.json()["options"]
    assert options["remove_modules"]["module_count"] == 3
    power = sum(module_nameplate_w(before["pinned_components"]["modules"][m["module_definition_revision_id"]])
                for m in before["scene"]["module_instances"] if m["module_instance_id"] in expected)
    assert options["remove_modules"]["stc_power_w"] == pytest.approx(power)
    assert options["refill_field"]["available"] is True
    assert options["refill_field"]["fields"][0]["module_count_before"] == 20
    assert options["refill_field"]["fields"][0]["module_count_after"] == 17
    assert p.path.read_bytes() == snapshot
    response = zone(p, points, route=route, surface_type=surface_type, on_module_conflict="remove_modules")
    assert response.status_code == 200, response.text
    assert {m["module_instance_id"] for m in p.bundle()["scene"]["module_instances"]} == {
        m["module_instance_id"] for m in before["scene"]["module_instances"]} - expected
    assert p.bundle()["scene"]["pv_fields"][0]["layout_status"] == "manual"


def test_03_refill_and_independent_discard_flags_are_atomic(tmp_path):
    p = Project(tmp_path, weather=False, strings=True)
    p.surface_id = p.bundle()["scene"]["surfaces"][0]["surface_id"]
    p.field_id = p.bundle()["scene"]["pv_fields"][0]["pv_field_id"]
    bundle = p.bundle(); bundle["scene"]["pv_fields"][0]["layout_status"] = "manual"; p.service.store.save(bundle)
    snapshot = p.path.read_bytes()
    preview = zone(p, dry_run=True).json()["options"]
    assert preview["remove_modules"]["string_ids"]
    assert preview["refill_field"]["requires_discard_manual_layout"] is True
    for opts in ({"on_module_conflict": "remove_modules"},
                 {"on_module_conflict": "refill_field", "discard_dependent_strings": True},
                 {"on_module_conflict": "refill_field", "discard_manual_layout": True}):
        response = zone(p, **opts)
        assert response.status_code == 422, response.text
        assert p.path.read_bytes() == snapshot
    response = zone(p, on_module_conflict="refill_field", discard_manual_layout=True, discard_dependent_strings=True)
    assert response.status_code == 200, response.text
    after = p.bundle()
    assert len(after["scene"]["module_instances"]) == 17
    assert not after["electrical_design"]["strings"]
    assert not [c for c in validate_scene_layout(after["scene"], after["pinned_components"]["modules"])["conflicts"]
                if c["code"] == "module_exclusion_overlap"]


@pytest.mark.parametrize("kind,expected_conflicts", [("contact", 3), ("tiny", 3), ("clear", 0)])
def test_03_contact_tiny_overlap_and_clearance_follow_packer(tmp_path, kind, expected_conflicts):
    p = project(tmp_path); points = zone_points(p, kind=kind)
    before = p.bundle(); expected = oracle_ids(before, scene_with_zone(p, points))
    assert len(expected) == expected_conflicts
    response = zone(p, points, dry_run=True)
    assert response.status_code == 200, response.text
    assert set(response.json()["options"]["remove_modules"]["module_instance_ids"]) == expected
    if kind == "clear":
        assert zone(p, points).status_code == 200
        assert len(p.bundle()["scene"]["module_instances"]) == 20
        assert p.bundle()["scene"]["pv_fields"][0]["setback_configuration"]["obstacle_setback_m"] == .3


@pytest.mark.parametrize("policy", ["reject", "remove_modules", "refill_field"])
def test_03_ignored_keepout_is_information_only_and_never_changes_field(tmp_path, policy):
    p = project(tmp_path); bundle = p.bundle()
    bundle["scene"]["pv_fields"][0]["exclusion_rules"] = {"use_scene_exclusion_surfaces": False}
    p.service.store.save(bundle); before = p.bundle(); snapshot = p.path.read_bytes()
    response = zone(p, on_module_conflict=policy, dry_run=True)
    assert response.status_code == 200, response.text
    assert response.json()["conflicts"] == []
    assert response.json()["ignored_by_fields"] == [{"pv_field_id": p.field_id, "reason": "field_exclusion_rules_ignore_keepout"}]
    assert p.path.read_bytes() == snapshot
    committed = zone(p, on_module_conflict=policy)
    assert committed.status_code == 200, committed.text
    assert p.bundle()["scene"]["module_instances"] == before["scene"]["module_instances"]
    assert p.bundle()["scene"]["pv_fields"] == before["scene"]["pv_fields"]
    assert not [f for f in p.readiness()["findings"] if f["rule_id"] == "SCENE_MODULE_KEEPOUT_OVERLAP"]


def test_03_explicit_surface_id_overrides_disabled_automatic_selection(tmp_path):
    p = project(tmp_path)
    assert zone(p, zone_points(p, kind="clear")).status_code == 200
    bundle = p.bundle(); sid = bundle["scene"]["surfaces"][-1]["surface_id"]
    rules = {"use_scene_exclusion_surfaces": False, "surface_types": ["walkway"], "surface_ids": [sid]}
    bundle["scene"]["pv_fields"][0]["exclusion_rules"] = rules; p.service.store.save(bundle)
    before = p.path.read_bytes()
    preview = _send(p, "move", [sid], {"dx_m": 0, "dy_m": .5}, dry_run=True)
    assert preview.status_code == 200, preview.text
    assert preview.json()["options"]["refill_field"]["available"] is True
    assert preview.json()["ignored_by_fields"] == []
    assert len(preview.json()["conflicts"]) == 3 and p.path.read_bytes() == before
    committed = _send(p, "move", [sid], {"dx_m": 0, "dy_m": .5}, on_module_conflict="refill_field")
    assert committed.status_code == 200, committed.text
    assert p.bundle()["scene"]["pv_fields"][0]["exclusion_rules"] == rules
    assert len(p.bundle()["scene"]["module_instances"]) == 17


@pytest.mark.parametrize("surface_type", ["exclusion_area", "walkway"])
def test_04_keepout_clear_of_modules_commits_without_an_option(tmp_path, surface_type):
    p = project(tmp_path); before = p.bundle()
    response = zone(p, [[40, 0], [41, 0], [41, 1], [40, 1]], surface_type=surface_type)
    assert response.status_code == 200, response.text
    assert p.bundle()["scene"]["module_instances"] == before["scene"]["module_instances"]


def test_05_readiness_warning_is_nonblocking_and_bounded(tmp_path):
    p = Project(tmp_path, count=60, string_length=20)
    assert p.readiness()["ready"] is True
    bundle = p.bundle(); editor = SceneEditorSession(bundle["scene"])
    roof = bundle["scene"]["surfaces"][0]
    editor.draw_polygon(surface_id="legacy-keepout", scene_object_id="obj-legacy-keepout", name="Legacy keep-out",
        vertices=roof["boundary_2d"]["vertices"], surface_type="exclusion_area", base_elevation_m=-500, usable_for_pv=False)
    bundle["scene"] = editor.scene; p.service.store.save(bundle)
    ready = p.readiness()
    assert ready["ready"] is True
    findings = [f for f in ready["findings"] if f["rule_id"] == "SCENE_MODULE_KEEPOUT_OVERLAP"]
    assert len(findings) == 51 and all(f["severity"] == "warning" for f in findings)
    summaries = [f for f in findings if "total_pair_count" in f["context"]]
    assert len(summaries) == 1
    assert summaries[0]["context"] == {"total_pair_count": 60, "omitted_pair_count": 10}


@pytest.mark.parametrize("kind,parameters", [
    ("insert_vertex", {"edge_index": 0, "x_m": 4, "y_m": 0}),
    ("delete_vertex", {"vertex_index": 1}),
    ("move_edge", {"edge_index": 0, "dx_m": 0, "dy_m": .1}),
])
def test_06_hosted_edits_preview_refill_and_default_reject(tmp_path, kind, parameters):
    p = GeometryProject(tmp_path)
    p.service.create_strings(p.pid, string_length=5, allow_shorter_remainder=True)
    sid = p.bundle()["scene"]["surfaces"][0]["surface_id"]
    field_id = p.bundle()["scene"]["pv_fields"][0]["pv_field_id"]
    before = p.bundle(); snapshot = p.path.read_bytes()
    refused = _send(p, kind, [sid], parameters)
    assert refused.status_code == 422 and "rebuild/impact handling is required" in refused.json()["detail"]
    preview = _send(p, kind, [sid], parameters, dependent_fields="apply", dry_run=True)
    assert preview.status_code == 200, preview.text
    assert p.path.read_bytes() == snapshot
    field, = preview.json()["dependent_fields"]
    assert field["pv_field_id"] == field_id and field["module_count_before"] == len(before["scene"]["module_instances"])
    editor = SceneEditorSession(before["scene"]); getattr(editor, kind)(sid, **parameters)
    packing = PVFieldPackingSession(editor.scene, before["pinned_components"]["modules"], electrical_design=before["electrical_design"])
    packing.rebuild_field(field_id)
    if field["string_ids"]:
        assert _send(p, kind, [sid], parameters, dependent_fields="apply").status_code == 422
        assert p.path.read_bytes() == snapshot
    committed = _send(p, kind, [sid], parameters, dependent_fields="apply", discard_dependent_strings=bool(field["string_ids"]))
    assert committed.status_code == 200, committed.text
    after = p.bundle()
    assert after["scene"]["surfaces"] == packing.scene["surfaces"]
    assert after["scene"]["module_instances"] == packing.scene["module_instances"]
    assert len(after["scene"]["pv_fields"]) == 1
    assert after["scene"]["revision_number"] == before["scene"]["revision_number"] + 1
    assert after["project"]["project_revision"]["revision_number"] == before["project"]["project_revision"]["revision_number"] + 1


def test_07_obstacle_height_conflict_options_and_lowering(tmp_path):
    p = project(tmp_path); points = zone_points(p)
    p.service.add_box_obstacle(p.pid, name="Low", origin_x_m=points[0][0], origin_y_m=points[0][1],
        width_m=points[1][0]-points[0][0], depth_m=.2, base_elevation_m=0, height_m=1)
    oid = p.bundle()["scene"]["obstacles"][0]["obstacle_id"]; snapshot = p.path.read_bytes()
    refused = _send(p, "edit_height", [oid], {"height_m": 7})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["options"]["remove_modules"]["module_count"] == 3
    assert p.path.read_bytes() == snapshot
    preview = _send(p, "edit_height", [oid], {"height_m": 7}, dry_run=True)
    assert preview.status_code == 200 and preview.json()["options"]["remove_modules"]["module_count"] == 3
    bundle = p.bundle(); bundle["scene"]["obstacles"][0]["height_m"] = 7; p.service.store.save(bundle)
    lowered = _send(p, "edit_height", [oid], {"height_m": 1})
    assert lowered.status_code == 200, lowered.text
    assert len(p.bundle()["scene"]["module_instances"]) == 20


@pytest.mark.parametrize("kind", ["move", "rotate", "scale", "move_vertex", "insert_vertex", "delete_vertex",
                                  "move_edge", "edit_exact_dimension", "edit_exact_angle", "edit_elevation"])
def test_08_every_keepout_geometry_command_uses_conflict_flow(tmp_path, kind):
    p = project(tmp_path); bundle = p.bundle(); points = zone_points(p)
    bundle["scene"] = scene_with_zone(p, points); p.service.store.save(bundle)
    x, y = points[0]; cx, cy = (points[0][0]+points[2][0])/2, (points[0][1]+points[2][1])/2
    parameters = {
        "move": {"dx_m": .01, "dy_m": 0}, "rotate": {"angle_deg": .5, "origin": [cx, cy]},
        "scale": {"factor": 1.01, "origin": [cx, cy]},
        "move_vertex": {"vertex_index": 0, "target_x_m": x+.01, "target_y_m": y},
        "insert_vertex": {"edge_index": 0, "x_m": cx, "y_m": y-.01},
        "delete_vertex": {"vertex_index": 1}, "move_edge": {"edge_index": 0, "dx_m": 0, "dy_m": -.01},
        "edit_exact_dimension": {"edge_index": 0, "length_m": 2},
        "edit_exact_angle": {"edge_index": 0, "azimuth_deg": 89.9},
        "edit_elevation": {"base_elevation_m": 1000},
    }[kind]
    before = p.path.read_bytes()
    response = _send(p, kind, ["obj-oracle-keepout"], parameters)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["options"]["remove_modules"]["module_count"] > 0
    assert all(c["code"] == "module_exclusion_overlap" for c in detail["conflicts"])
    assert p.path.read_bytes() == before
    committed = _send(p, kind, ["obj-oracle-keepout"], parameters, on_module_conflict="remove_modules")
    assert committed.status_code == 200, committed.text
    after = p.bundle()
    assert not [c for c in validate_scene_layout(after["scene"], after["pinned_components"]["modules"])["conflicts"]
                if c["code"] == "module_exclusion_overlap"]


def test_09_optional_keepout_rebuild_failure_does_not_disable_removal(tmp_path, monkeypatch):
    p = project(tmp_path); snapshot = p.path.read_bytes()
    def unavailable(*args, **kwargs):
        raise ValueError("S11a forced rebuild failure")
    monkeypatch.setattr(PVFieldPackingSession, "rebuild_field", unavailable)
    preview = zone(p, dry_run=True)
    assert preview.status_code == 200
    assert preview.json()["options"]["refill_field"]["available"] is False
    assert preview.json()["options"]["refill_field"]["reason"] == "refill_unavailable"
    refused = zone(p, on_module_conflict="refill_field")
    assert refused.status_code == 422 and "S11a forced rebuild failure" in refused.json()["detail"]["message"]
    assert p.path.read_bytes() == snapshot
    assert zone(p, on_module_conflict="remove_modules").status_code == 200
    assert len(p.bundle()["scene"]["module_instances"]) == 17
