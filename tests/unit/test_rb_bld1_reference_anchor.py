"""RB-BLD1 saved own-axis anchors and anchored rectangle dimensions."""
import math

import pytest
from pydantic import ValidationError

from apps.api.server import _validated_scene_command, create_app
from geometry.scene import SceneEditorSession
from geometry.scene.editor import _reference_point
from geometry.scene.geometry2d import rotate_points_clockwise
from test_phase42_scene_editor import _base_scene, _validate_scene


ANCHORS = [(u, v) for u in ("start", "center", "end") for v in ("start", "center", "end")]


def editor_for(kind="flat_roof", clockwise=False):
    editor = SceneEditorSession(_base_scene())
    ring = rotate_points_clockwise([(0, 0), (10, 0), (10, 6), (0, 6)], (0, 0), 30)
    if clockwise:
        ring.reverse()
    if kind == "obstacle":
        editor.draw_polygon_extrusion(obstacle_id="bld1", scene_object_id="obj-bld1", name="Box", vertices=ring, base_elevation_m=0, height_m=2)
    else:
        editor.draw_polygon(surface_id="bld1", scene_object_id="obj-bld1", name="Roof", surface_type=kind, vertices=ring)
    return editor


def item(editor, kind):
    return next(e for e in editor.scene["obstacles" if kind == "obstacle" else "surfaces"] if e.get("surface_id", e.get("obstacle_id")) == "bld1")


@pytest.mark.parametrize("kind", ["flat_roof", "exclusion_area", "obstacle"])
def test_store_undo_redo_lock_and_old_new_schema(kind):
    editor = editor_for(kind)
    _validate_scene(editor.scene)
    before = editor.scene
    editor.set_reference_anchor("bld1", u="center", v="end")
    assert item(editor, kind)["reference_anchor"] == {"u": "center", "v": "end"}
    _validate_scene(editor.scene)
    assert editor.undo()
    assert editor.scene == before
    assert editor.redo()
    editor.move(["bld1"], dx_m=3, dy_m=4)
    editor.rotate(["bld1"], angle_deg=20)
    editor.edit_exact_dimension("bld1", edge_index=0, length_m=12, preserve="rectangle")
    assert item(editor, kind)["reference_anchor"] == {"u": "center", "v": "end"}
    editor.set_locked(["bld1"], locked=True)
    before = editor.scene
    with pytest.raises(ValueError, match="locked"):
        editor.set_reference_anchor("bld1", u="start", v="start")
    assert editor.scene == before


@pytest.mark.parametrize("u,v", ANCHORS)
@pytest.mark.parametrize("clockwise", [False, True])
@pytest.mark.parametrize("edge", [0, 1])
def test_resize_keeps_all_nine_anchors_fixed(u, v, clockwise, edge):
    editor = editor_for(clockwise=clockwise)
    editor.set_reference_anchor("bld1", u=u, v=v)
    anchor = {"u": u, "v": v}
    ring = item(editor, "flat_roof")["boundary_2d"]["vertices"]
    point = _reference_point(ring, anchor)
    editor.edit_exact_dimension("bld1", edge_index=edge, length_m=14, preserve="rectangle")
    updated = item(editor, "flat_roof")["boundary_2d"]["vertices"]
    assert _reference_point(updated, anchor) == pytest.approx(point, abs=1e-9)
    assert math.dist(updated[edge], updated[(edge + 1) % 4]) == pytest.approx(14)


def command(ids, parameters):
    return {"schema_name": "SceneEditorCommand", "schema_version": "0.1", "command_id": "bld1-anchor", "command_type": "set_reference_anchor", "target_entity_ids": ids, "parameters": parameters}


@pytest.mark.parametrize("ids,parameters", [([], {"u": "start", "v": "start"}), (["a", "b"], {"u": "start", "v": "start"}), (["a"], {"u": "bad", "v": "start"}), (["a"], {"u": "start"}), (["a"], {"u": "start", "v": "start", "extra": 1})])
def test_api_rejects_invalid_anchor_commands(ids, parameters):
    with pytest.raises((ValueError, ValidationError)):
        _validated_scene_command(command(ids, parameters))


def test_service_validated_command_persists_without_geometry_change(tmp_path):
    service = create_app(store_root=tmp_path / "projects").state.project_service
    bundle = service.create_project(name="BLD1", latitude_deg=-6.2, longitude_deg=106.8, timezone_name="Asia/Jakarta", workspace_mode="blank_engineering_plane")
    pid = bundle["project"]["project_id"]
    view = service.scene_command(pid, {"command_id": "draw", "command_type": "draw_polygon", "target_entity_ids": [], "parameters": {"name": "Roof", "surface_type": "flat_roof", "vertices": [(0, 0), (10, 0), (10, 6), (0, 6)]}})
    entity = view["bundle"]["scene"]["surfaces"][-1]
    result = service.scene_command(pid, _validated_scene_command(command([entity["surface_id"]], {"u": "end", "v": "center"})))
    saved = service.get_bundle(pid)["scene"]["surfaces"][-1]
    assert saved["reference_anchor"] == {"u": "end", "v": "center"}
    assert saved["boundary_2d"] == entity["boundary_2d"]
    assert result["bundle"]["scene"] == service.get_bundle(pid)["scene"]


@pytest.mark.parametrize("anchor", [{"u": "bad", "v": "start"}, {"u": "start"}, {"u": "start", "v": "end", "extra": 1}])
def test_schema_rejects_malformed_saved_anchors(anchor):
    from jsonschema import ValidationError as SchemaValidationError
    scene = editor_for().scene
    scene["surfaces"][-1]["reference_anchor"] = anchor
    with pytest.raises(SchemaValidationError):
        _validate_scene(scene)
