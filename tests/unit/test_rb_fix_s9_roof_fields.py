"""S9: support-surface changes, re-fill and whole-string deletion are atomic."""
from copy import deepcopy
import json
import math

import pytest
from shapely.geometry import Polygon

from geometry.scene import SceneEditorSession
from geometry.pvfield import PVFieldPackingSession
from tests.unit.test_rb_fix_s1_geometry_integrity import Project, MODULE
from tests.unit.test_rb_fix_s3_scene_commands import _command, _send, _surface
from components.design_integration import module_nameplate_w  # D14: the DC nameplate basis


def _post(project, kind, ids=None, parameters=None, **options):
    return _send(project, kind, ids or [project.surface_id], parameters, dependent_fields="apply", **options)


def _strings(project):
    project.service.create_strings(project.pid, string_length=5, allow_shorter_remainder=True)
    return deepcopy(project.bundle()["electrical_design"]["strings"])


def _free_editor(project):
    scene = deepcopy(project.bundle()["scene"])
    scene["pv_fields"] = []; scene["module_instances"] = []
    return SceneEditorSession(scene)


def test_01_engine_scale_centres_origin_holes_provenance_and_undo(tmp_path):
    p = Project(tmp_path, width=8, height=8)
    scene = _free_editor(p).scene
    roof = scene["surfaces"][0]
    roof["boundary_2d"]["holes"] = [[[2, 2], [3, 2], [3, 3], [2, 3]]]
    editor = SceneEditorSession(scene)
    original = editor.scene
    polygon = Polygon(roof["boundary_2d"]["vertices"])
    editor.scale([p.surface_id], factor=2)
    after = editor.scene["surfaces"][0]
    result = Polygon(after["boundary_2d"]["vertices"])
    assert result.area == pytest.approx(polygon.area * 4)
    assert result.centroid.distance(polygon.centroid) < 1e-12
    cx, cy = polygon.centroid.coords[0]
    assert after["boundary_2d"]["holes"][0] == [[cx + 2*(x-cx), cy + 2*(y-cy)] for x,y in roof["boundary_2d"]["holes"][0]]
    assert all(edge["source"] == "derived" for edge in after["edge_dimension_sources"])
    assert editor.undo_depth == 1
    editor.undo(); assert editor.scene == original
    editor.scale([p.surface_id], factor=.5, origin=(0, 0))
    assert editor.scene["surfaces"][0]["boundary_2d"]["vertices"] == [[x*.5,y*.5] for x,y in roof["boundary_2d"]["vertices"]]


@pytest.mark.parametrize("factor", [0, -1, math.nan, math.inf])
def test_01_bad_engine_factor_rolls_back(tmp_path, factor):
    p = Project(tmp_path); editor = _free_editor(p); before = editor.scene
    with pytest.raises(ValueError): editor.scale([p.surface_id], factor=factor)
    assert editor.scene == before and editor.undo_depth == 0


def test_01_locked_and_multi_target_scale_are_atomic_and_obstacle_parameters_invalidated(tmp_path):
    p = Project(tmp_path)
    p.service.add_box_obstacle(p.pid, name="Free box", origin_x_m=40, origin_y_m=0, width_m=2, depth_m=2, base_elevation_m=0, height_m=1)
    scene = _free_editor(p).scene; obstacle = scene["obstacles"][0]; obstacle["locked"] = True
    editor = SceneEditorSession(scene); before = editor.scene
    with pytest.raises(ValueError, match="locked"): editor.scale([p.surface_id, obstacle["obstacle_id"]], factor=2)
    assert editor.scene == before and editor.undo_depth == 0
    obstacle["locked"] = False; editor = SceneEditorSession(scene)
    editor.scale([obstacle["obstacle_id"]], factor=2)
    changed = editor.scene["obstacles"][0]
    assert changed["dimensions"]["parameterization_valid"] is False
    assert changed["geometry_source"] == "user_override"


def test_02_http_free_scale_persists_one_revision_and_rejects_bad_parameters(tmp_path):
    p = Project(tmp_path); free = _surface(p); sid = free["surface_id"]
    before = p.bundle(); response = _send(p, "scale", [sid], {"factor": 2})
    assert response.status_code == 200, response.text
    after = p.bundle()
    assert Polygon(after["scene"]["surfaces"][-1]["boundary_2d"]["vertices"]).area == pytest.approx(48)
    assert after["scene"]["revision_number"] == before["scene"]["revision_number"] + 1
    assert after["project"]["project_revision"]["revision_number"] == before["project"]["project_revision"]["revision_number"] + 1
    snapshot = p.path.read_bytes()
    for parameters in ({"factor": 0}, {"factor": -1}, {"factor": 101}, {"factor": 2,"unknown": 1}, {"factor": 2,"origin": [0]}, {"factor": 2,"origin": [math.nan, 0]}, {"factor": math.inf}):
        r = p.client.post(p.url+"/scene/commands", content=json.dumps(_command("scale",[sid],parameters)), headers={"Content-Type":"application/json"})
        assert r.status_code == 422, r.text
    for ids in ([], [sid,p.surface_id]): assert _send(p,"scale",ids,{"factor":2}).status_code == 422
    assert p.path.read_bytes() == snapshot
    assert _send(p,"scale",[sid],{"factor":100}).status_code == 200
    snapshot = p.path.read_bytes()
    assert _send(p,"scale",[sid],{"factor":100}).status_code == 422
    assert p.path.read_bytes() == snapshot


@pytest.mark.parametrize("alias", [False, True])
def test_03_default_reject_preserves_exact_support_messages(tmp_path, alias):
    p = Project(tmp_path); roof = p.bundle()["scene"]["surfaces"][0]; sid = roof["scene_object_id"] if alias else p.surface_id
    edits = {"move":{"dx_m":1,"dy_m":0},"rotate":{"angle_deg":10},"scale":{"factor":.8},"move_vertex":{"vertex_index":0,"target_x_m":1,"target_y_m":1},"edit_exact_dimension":{"edge_index":0,"length_m":5},"edit_exact_angle":{"edge_index":0,"azimuth_deg":10},"delete":{}}
    raw = p.path.read_bytes()
    for kind, parameters in edits.items():
        expected = f"support surface is already used by PV fields ['{p.field_id}']; " + ("delete the fields first (DELETE /pv-fields/{id})" if kind=="delete" else "rebuild/impact handling is required before moving it")
        for options in ({}, {"dependent_fields":"reject"}):
            r = _send(p,kind,[sid],parameters,**options); assert r.status_code == 422 and r.json()["detail"] == expected
    r = p.client.post(p.url+"/scene/move",json={"entity_id":sid,"dx_m":1,"dy_m":0})
    assert r.status_code == 422 and "rebuild/impact handling" in r.json()["detail"]
    assert p.path.read_bytes() == raw


def test_04_strung_scale_preview_flags_independent_rebuild_and_single_save(tmp_path, monkeypatch):
    p = Project(tmp_path); strings = _strings(p); before = p.bundle(); raw = p.path.read_bytes()
    r = _post(p,"scale",parameters={"factor":.8},dry_run=True)
    assert r.status_code == 200, r.text
    preview = r.json(); field = preview["dependent_fields"][0]
    assert preview["dry_run"] and preview["conflicts"] == [] and field["action"] == "refill"
    assert field["module_count_after"] != field["module_count_before"]
    assert field["stc_power_w_before"] == field["module_count_before"] * module_nameplate_w(before["pinned_components"]["modules"][MODULE])
    assert field["requires_discard_dependent_strings"] and field["string_ids"]
    assert p.path.read_bytes() == raw
    refused = _post(p,"scale",parameters={"factor":.8}); assert refused.status_code == 422
    assert refused.json()["detail"]["dependent_fields"] == preview["dependent_fields"]
    assert p.path.read_bytes() == raw
    editor = SceneEditorSession(before["scene"]); editor.scale([p.surface_id],factor=.8)
    independent = PVFieldPackingSession(editor.scene,before["pinned_components"]["modules"],electrical_design=before["electrical_design"])
    independent.rebuild_field(p.field_id)
    calls=[]; original=p.service._save
    monkeypatch.setattr(p.service,"_save",lambda bundle: (calls.append(bundle),original(bundle))[-1])
    committed = _post(p,"scale",parameters={"factor":.8},discard_dependent_strings=True)
    assert committed.status_code == 200, committed.text
    after = p.bundle(); assert len(calls) == 1
    assert len(after["scene"]["pv_fields"]) == 1
    assert after["scene"]["module_instances"] == independent.scene["module_instances"]
    assert after["scene"]["pv_fields"][0] == independent.scene["pv_fields"][0]
    assert [s for s in strings if s["string_id"] not in field["string_ids"]] == after["electrical_design"]["strings"]
    assert after["scene"]["revision_number"] == before["scene"]["revision_number"]+1
    assert after["electrical_design"]["revision_number"] == before["electrical_design"]["revision_number"]+1


@pytest.mark.parametrize("kind,parameters", [("move",{"dx_m":20,"dy_m":3}),("rotate",{"angle_deg":90}),("move_vertex",{"vertex_index":0,"target_x_m":-.5,"target_y_m":0}),("edit_exact_dimension",{"edge_index":0,"length_m":9}),("edit_exact_angle",{"edge_index":0,"azimuth_deg":80})])
def test_05_all_support_edits_rebuild_stored_parameters_and_stay_inside(tmp_path, kind, parameters):
    p=Project(tmp_path); before=p.bundle(); editor=SceneEditorSession(before["scene"])
    getattr(editor,kind)([p.surface_id] if kind in {"move","rotate"} else p.surface_id,**parameters)
    independent=PVFieldPackingSession(editor.scene,before["pinned_components"]["modules"],electrical_design=before["electrical_design"]); independent.rebuild_field(p.field_id)
    r=_post(p,kind,parameters=parameters); assert r.status_code==200,r.text
    after=p.bundle(); assert after["scene"]["module_instances"]==independent.scene["module_instances"]
    roof=Polygon(after["scene"]["surfaces"][0]["boundary_2d"]["vertices"])
    for feature in r.json()["scene_view"]["local_features"]:
        if feature["category"]=="module": assert roof.buffer(1e-9).covers(Polygon(feature["polygon"]))


def test_06_zero_manual_and_geometry_conflicts_never_save(tmp_path):
    p=Project(tmp_path); before=p.path.read_bytes()
    preview=_post(p,"scale",parameters={"factor":.01},dry_run=True)
    assert preview.status_code==200 and preview.json()["dependent_fields"][0]["module_count_after"]==0
    r=_post(p,"scale",parameters={"factor":.01}); assert r.status_code==422 and "zero modules" in r.json()["detail"]["message"]
    assert p.path.read_bytes()==before
    b=p.bundle(); b["scene"]["pv_fields"][0]["layout_status"]="manual"; p.service.store.save(b); before=p.path.read_bytes()
    r=_post(p,"scale",parameters={"factor":.8}); assert r.status_code==422 and "discard_manual_layout" in r.json()["detail"]["message"]
    assert p.path.read_bytes()==before
    r=_post(p,"scale",parameters={"factor":.8},discard_manual_layout=True); assert r.status_code==200,r.text
    # The field's own exclusion policy remains authoritative; opted-out obstacle
    # packing must be refused when S1 still finds an actual overlap afterward.
    b=p.bundle(); b["scene"]["pv_fields"][0]["exclusion_rules"]["use_scene_obstacles"]=False; p.service.store.save(b)
    p.service.add_box_obstacle(p.pid,name="Destination obstacle",origin_x_m=20,origin_y_m=0,width_m=8,depth_m=9,base_elevation_m=6.1,height_m=2)
    before=p.path.read_bytes(); r=_post(p,"move",parameters={"dx_m":20,"dy_m":0})
    assert r.status_code==422 and r.json()["detail"]["dependent_fields"][0]["conflicts"]
    assert p.path.read_bytes()==before


def test_06_cross_field_conflict_and_rebuild_failure_are_atomic(tmp_path, monkeypatch):
    p=Project(tmp_path); second=p.service.add_surface_rectangle(p.pid,name="Other roof",origin_x_m=20,origin_y_m=0,width_m=8,height_m=8.5,base_elevation_m=6.1,surface_type="flat_roof",usable_for_pv=True)["bundle"]["scene"]["surfaces"][-1]
    p.service.create_pv_field(p.pid,**{**p.fill,"support_surface_id":second["surface_id"],"name":"Other field"})
    before=p.path.read_bytes(); r=_post(p,"move",parameters={"dx_m":20,"dy_m":0})
    assert r.status_code==422 and any(c["code"]=="module_module_overlap" for c in r.json()["detail"]["dependent_fields"][0]["conflicts"])
    assert p.path.read_bytes()==before
    monkeypatch.setattr(PVFieldPackingSession,"rebuild_field",lambda *args: (_ for _ in ()).throw(ValueError("Cannot rebuild")))
    r=_post(p,"scale",parameters={"factor":.8}); assert r.status_code==422 and "Cannot rebuild" in r.json()["detail"]["message"]
    assert p.path.read_bytes()==before


def test_07_cascade_delete_preview_whole_strings_and_multi_target_atomicity(tmp_path):
    p=Project(tmp_path); _strings(p)
    other=p.service.add_surface_rectangle(p.pid,name="Other roof",origin_x_m=25,origin_y_m=0,width_m=8,height_m=8.5,base_elevation_m=6.1,surface_type="flat_roof",usable_for_pv=True)["bundle"]["scene"]["surfaces"][-1]
    p.service.create_pv_field(p.pid,**{**p.fill,"support_surface_id":other["surface_id"],"name":"Other field"})
    other_id=p.bundle()["scene"]["pv_fields"][-1]["pv_field_id"]
    p.service.create_strings(p.pid,pv_field_id=other_id,string_length=5,allow_shorter_remainder=True)
    before=p.bundle(); raw=p.path.read_bytes()
    preview=_post(p,"delete",dry_run=True).json()["dependent_fields"][0]
    assert preview["action"]=="delete" and preview["module_count_after"]==preview["stc_power_w_after"]==0
    assert preview["string_ids"] and p.path.read_bytes()==raw
    for ids in ([p.surface_id],[p.surface_id,"missing"]):
        r=_post(p,"delete",ids,discard_dependent_strings=len(ids)>1)
        assert r.status_code==422 and p.path.read_bytes()==raw
    r=_post(p,"delete",discard_dependent_strings=True); assert r.status_code==200,r.text
    b=p.bundle(); assert [f["pv_field_id"] for f in b["scene"]["pv_fields"]]==[other_id]
    assert all(m["pv_field_id"]==other_id for m in b["scene"]["module_instances"])
    assert b["electrical_design"]["strings"]==[s for s in before["electrical_design"]["strings"] if s["string_id"] not in preview["string_ids"]]
    assert [s["surface_id"] for s in b["scene"]["surfaces"]]==[other["surface_id"]]


def test_08_move_route_alias_matches_command_apply_and_preserves_elevation_policy(tmp_path):
    p=Project(tmp_path); before=p.bundle(); alias=before["scene"]["surfaces"][0]["scene_object_id"]
    r=p.client.post(p.url+"/scene/move",json={"entity_id":alias,"dx_m":10,"dy_m":2,"dependent_fields":"apply","dry_run":True})
    assert r.status_code==200 and r.json()["dependent_fields"]
    r=p.client.post(p.url+"/scene/move",json={"entity_id":alias,"dx_m":10,"dy_m":2,"dependent_fields":"apply"}); assert r.status_code==200,r.text
    moved=p.bundle(); editor=SceneEditorSession(before["scene"]); editor.move([alias],dx_m=10,dy_m=2)
    session=PVFieldPackingSession(editor.scene,before["pinned_components"]["modules"]); session.rebuild_field(p.field_id)
    assert moved["scene"]["module_instances"]==session.scene["module_instances"]
    r=_post(p,"edit_elevation",parameters={"base_elevation_m":7}); assert r.status_code==200,r.text
    assert [m["module_instance_id"] for m in p.modules()]==[m["module_instance_id"] for m in sorted(moved["scene"]["module_instances"],key=lambda m:(m["row_index"],m["column_index"]))]


def test_09_stale_save_during_apply_returns_409_and_keeps_newer_edit(tmp_path,monkeypatch):
    p=Project(tmp_path); original=p.service._commit_layout_edit
    def concurrent(bundle,*args,**kwargs):
        p.service.update_project(p.pid,name="Concurrent rename")
        return original(bundle,*args,**kwargs)
    monkeypatch.setattr(p.service,"_commit_layout_edit",concurrent)
    before=p.bundle()["scene"]
    r=_post(p,"scale",parameters={"factor":.8})
    assert r.status_code==409 and r.json()["detail"]=="project changed concurrently; reload and retry"
    assert p.bundle()["project"]["name"]=="Concurrent rename" and p.bundle()["scene"]==before


def test_07_ambiguous_legacy_delete_alias_cannot_remove_a_locked_match(tmp_path):
    p = Project(tmp_path)
    _surface(p)
    bundle = p.bundle()
    alias = bundle["scene"]["surfaces"][0]["scene_object_id"]
    bundle["scene"]["surfaces"][1]["scene_object_id"] = alias
    bundle["scene"]["surfaces"][1]["locked"] = True
    p.service.store.save(bundle)
    before = p.path.read_bytes()
    r = _post(p, "delete", [alias])
    assert r.status_code == 422 and "locked" in r.json()["detail"]
    assert p.path.read_bytes() == before
    bundle = p.bundle(); bundle["scene"]["surfaces"][1]["locked"] = False; p.service.store.save(bundle)
    r = _post(p, "delete", [alias])
    assert r.status_code == 200, r.text
    assert p.bundle()["scene"]["surfaces"] == []
    assert p.bundle()["scene"]["pv_fields"] == []
