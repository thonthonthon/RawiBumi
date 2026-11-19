"""S3 scene edits through real HTTP and temporary persisted projects."""

from copy import deepcopy
import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from apps.api.server import create_app
from geometry.scene import SceneEditorSession
from tests.unit.test_rb_fix_s1_geometry_integrity import Project, ROOT, MODULE, INVERTER


def _command(kind, ids, parameters=None):
    return {"command": {"schema_name": "SceneEditorCommand", "schema_version": "0.1",
        "command_id": "s3-command", "command_type": kind, "target_entity_ids": ids,
        "parameters": parameters or {}}}


def _send(project, kind, ids, parameters=None, **policy):
    return project.client.post(project.url + "/scene/commands", json={**_command(kind, ids, parameters), **policy})


def _reject(project, kind, ids, parameters=None, **policy):
    before = project.path.read_bytes()
    response = _send(project, kind, ids, parameters, **policy)
    assert response.status_code == 422, response.text
    assert project.path.read_bytes() == before
    return response


def _surface(project):
    view = project.service.add_surface_rectangle(project.pid, name="Free surface", origin_x_m=20,
        origin_y_m=0, width_m=4, height_m=3, base_elevation_m=6.1, surface_type="flat_roof", usable_for_pv=True)
    return view["bundle"]["scene"]["surfaces"][-1]


def test_01_envelope_schema_is_enforced(tmp_path):
    project = Project(tmp_path)
    base = _command("move", ["missing"], {"dx_m": 1, "dy_m": 0})
    cases = []
    for key, value in (("schema_name", "Wrong"), ("schema_version", "2"),
                       ("extra", 1), ("command_type", "made_up"), ("issued_at", "yesterday")):
        body = deepcopy(base)
        body["command"][key] = value
        cases.append(body)
    missing = deepcopy(base)
    missing["command"].pop("parameters")
    cases.extend([missing, {**base, "extra": 1}])
    before = project.path.read_bytes()
    for body in cases:
        response = project.client.post(project.url + "/scene/commands", json=body)
        assert response.status_code == 422 and "detail" in response.json()
        assert project.path.read_bytes() == before


SUPPORTED = {"insert_vertex", "delete_vertex", "move_edge", "edit_height", "edit_plane", "add_hole", "remove_hole", "scale", "rotate", "delete", "move_vertex", "edit_exact_dimension", "edit_exact_angle",
             "edit_elevation", "draw_polygon", "move", "copy", "group", "ungroup", "set_reference_anchor"}  # BLD1
ENUM = json.loads((ROOT / "apps/web/schema/scene-editor-command.schema.json").read_text())["properties"]["command_type"]["enum"]


@pytest.mark.parametrize("kind", [kind for kind in ENUM if kind not in SUPPORTED])
def test_02_unsupported_commands_are_explicit(tmp_path, kind):
    project = Project(tmp_path)
    response = _reject(project, kind, [])
    assert f"command_type {kind} is not supported by /scene/commands yet" in response.json()["detail"]
    if kind in {"select", "multi_select"}:
        assert "session state" in response.json()["detail"]
    if kind in {"undo", "redo"}:
        assert "persisted history" in response.json()["detail"]


def test_03_parameters_target_counts_and_nonfinite_values_are_rejected(tmp_path):
    project = Project(tmp_path)
    surface = _surface(project)
    sid = surface["surface_id"]
    _reject(project, "rotate", [sid], {"angle_deg": 10, "unknown": 1})
    _reject(project, "move", [sid], {"dx_m": 1})
    _reject(project, "edit_elevation", [sid], {"base_elevation_m": 7, "height_m": 2})
    examples = {"rotate": {"angle_deg": 10}, "move": {"dx_m": 1, "dy_m": 0},
        "move_vertex": {"vertex_index": 0, "target_x_m": 20, "target_y_m": 1},
        "edit_exact_dimension": {"edge_index": 0, "length_m": 2},
        "edit_exact_angle": {"edge_index": 0, "azimuth_deg": 20},
        "edit_elevation": {"base_elevation_m": 7}, "delete": {}}
    for kind, params in examples.items():
        _reject(project, kind, [], params)
        if kind != "delete":
            _reject(project, kind, [sid, project.surface_id], params)
    polygon = {"surface_type": "flat_roof", "vertices": [[20, 0], [21, 0], [20, 1]]}
    _reject(project, "draw_polygon", [sid], polygon)
    before = project.path.read_bytes()
    for value in (float("nan"), float("inf"), -float("inf")):
        body = _command("rotate", [sid], {"angle_deg": value})
        response = project.client.post(project.url + "/scene/commands", content=json.dumps(body), headers={"content-type": "application/json"})
        assert response.status_code == 422, response.text
        assert project.path.read_bytes() == before
    _reject(project, "move_vertex", [sid], {"vertex_index": 0, "target_x_m": 20, "target_y_m": 1,
        "snap_tolerance_m": 0.1, "snap_kinds": ["unknown"]})


def test_04_rotate_uses_clockwise_geometry_and_one_persisted_revision(tmp_path):
    project = Project(tmp_path)
    surface = _surface(project)
    before = project.bundle()
    ids = [surface["scene_object_id"]]
    origin = [3.0, 2.0]
    angle = math.radians(30)
    expected = []
    for x, y in surface["boundary_2d"]["vertices"]:
        dx, dy = x - origin[0], y - origin[1]
        expected.append([origin[0] + dx * math.cos(angle) + dy * math.sin(angle),
                         origin[1] - dx * math.sin(angle) + dy * math.cos(angle)])
    prior_bytes = project.path.read_bytes()
    assert _send(project, "rotate", ids, {"angle_deg": 30, "origin": origin}, dry_run=True).json() == {"dry_run": True, "conflicts": []}
    assert project.path.read_bytes() == prior_bytes
    response = _send(project, "rotate", ids, {"angle_deg": 30, "origin": origin})
    assert response.status_code == 200, response.text
    after = project.bundle()
    for actual, target in zip(after["scene"]["surfaces"][-1]["boundary_2d"]["vertices"], expected):
        assert actual == pytest.approx(target, abs=1e-9)
    assert after["scene"]["revision_number"] == before["scene"]["revision_number"] + 1
    assert after["project"]["project_revision"]["revision_number"] == before["project"]["project_revision"]["revision_number"] + 1
    assert after["electrical_design"] == before["electrical_design"]
    assert after["scene"]["change_summary"] == f"Scene command rotate on {[surface['surface_id']]} (s3-command)."
    reopened = create_app(store_root=project.service.store.root).state.project_service.get_bundle(project.pid)
    assert reopened == after


def test_05_vertex_move_validity_and_out_of_range_422(tmp_path):
    project = Project(tmp_path)
    sid = _surface(project)["surface_id"]
    response = _send(project, "move_vertex", [sid], {"vertex_index": 0, "target_x_m": 21, "target_y_m": 0.2})
    assert response.status_code == 200, response.text
    vertices = project.bundle()["scene"]["surfaces"][-1]["boundary_2d"]["vertices"]
    assert len(vertices) == 4 and vertices[0] == [21, 0.2] and Polygon(vertices).is_valid
    _reject(project, "move_vertex", [sid], {"vertex_index": 0, "target_x_m": 25, "target_y_m": 2})
    response = _reject(project, "move_vertex", [sid], {"vertex_index": 4, "target_x_m": 21, "target_y_m": 0})
    assert "vertex_index is outside geometry" in response.json()["detail"]


def test_06_exact_dimension_and_provenance(tmp_path):
    project = Project(tmp_path)
    sid = _surface(project)["surface_id"]
    response = _send(project, "edit_exact_dimension", [sid], {"edge_index": 0, "length_m": 6, "source": "field_measurement"})
    assert response.status_code == 200, response.text
    surface = project.bundle()["scene"]["surfaces"][-1]
    vertices = surface["boundary_2d"]["vertices"]
    assert math.dist(vertices[0], vertices[1]) == pytest.approx(6, abs=1e-9)
    record = next(r for r in surface["edge_dimension_sources"] if r["edge_index"] == 0)
    assert record["source"] == "field_measurement" and record["value_m"] == 6
    _reject(project, "edit_exact_dimension", [sid], {"edge_index": 4, "length_m": 6})
    _reject(project, "edit_exact_dimension", [sid], {"edge_index": 0, "length_m": 0})
    _reject(project, "edit_exact_dimension", [sid], {"edge_index": 0, "length_m": 6, "preserve": "unknown"})
    _reject(project, "edit_exact_dimension", [sid], {"edge_index": 0, "length_m": 6, "source": "unknown-source"})


def test_07_exact_angle_matches_engineering_azimuth(tmp_path):
    project = Project(tmp_path)
    sid = _surface(project)["surface_id"]
    response = _send(project, "edit_exact_angle", [sid], {"edge_index": 0, "azimuth_deg": 60})
    assert response.status_code == 200, response.text
    a, b = project.bundle()["scene"]["surfaces"][-1]["boundary_2d"]["vertices"][:2]
    assert math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360 == pytest.approx(60, abs=1e-9)
    _reject(project, "edit_exact_angle", [sid], {"edge_index": 9, "azimuth_deg": 60})


def test_08_polygon_surface_creation_and_fill(tmp_path):
    project = Project(tmp_path)
    vertices = [[20, 0], [28, 0], [28, 4], [24, 4], [24, 8], [20, 8]]
    response = _send(project, "draw_polygon", [], {"name": "L roof", "surface_type": "flat_roof", "vertices": vertices})
    assert response.status_code == 200, response.text
    surface = project.bundle()["scene"]["surfaces"][-1]
    assert surface["surface_id"].startswith("surface-") and surface["scene_object_id"] == "obj-" + surface["surface_id"]
    assert surface["boundary_2d"]["vertices"] == vertices and surface["boundary_2d"]["holes"] == []
    response = project.client.post(project.url + "/pv-fields", json={**project.fill, "support_surface_id": surface["surface_id"]})
    assert response.status_code == 200, response.text
    _reject(project, "draw_polygon", [], {"surface_type": "invalid", "vertices": vertices})
    _reject(project, "draw_polygon", [], {"surface_type": "flat_roof", "vertices": [[20, 0], [24, 4], [20, 4], [24, 0]]})


def test_09_delete_is_atomic_and_has_no_automatic_refill(tmp_path):
    project = Project(tmp_path)
    free = _surface(project)
    assert project.client.post(project.url + "/obstacles/box", json=project.obstacle(origin_x_m=50)).status_code == 200
    obstacle = project.bundle()["scene"]["obstacles"][0]
    _reject(project, "delete", [obstacle["scene_object_id"], project.surface_id])
    _reject(project, "delete", [obstacle["obstacle_id"], "missing"])
    before = deepcopy(project.modules())
    response = _send(project, "delete", [obstacle["scene_object_id"], free["surface_id"]])
    assert response.status_code == 200, response.text
    assert not project.bundle()["scene"]["obstacles"]
    assert all(s["surface_id"] != free["surface_id"] for s in project.bundle()["scene"]["surfaces"])
    assert project.modules() == before


def test_10_support_surface_guards_use_both_id_forms(tmp_path):
    project = Project(tmp_path)
    surface = project.bundle()["scene"]["surfaces"][0]
    before = project.path.read_bytes()
    commands = {
        "rotate": {"angle_deg": 30}, "move": {"dx_m": 1, "dy_m": 0},
        "move_vertex": {"vertex_index": 0, "target_x_m": 1, "target_y_m": 1},
        "edit_exact_dimension": {"edge_index": 0, "length_m": 10},
        "edit_exact_angle": {"edge_index": 0, "azimuth_deg": 45}, "delete": {},
    }
    for target in (surface["surface_id"], surface["scene_object_id"]):
        for kind, params in commands.items():
            response = project.client.post(project.url + "/scene/commands", json=_command(kind, [target], params))
            assert response.status_code == 422, response.text
            assert project.field_id in str(response.json()["detail"])
            assert project.path.read_bytes() == before


def test_11_legacy_move_alias_bypasses_are_closed(tmp_path):
    roof = Project(tmp_path / "roof")
    surface = roof.bundle()["scene"]["surfaces"][0]
    before_roof = roof.path.read_bytes()
    moved_roof = roof.client.post(roof.url + "/scene/move", json={
        "entity_id": surface["scene_object_id"], "dx_m": 10, "dy_m": 0,
    })
    project = Project(tmp_path / "obstacle")
    request = project.obstacle(origin_x_m=50)
    assert project.client.post(project.url + "/obstacles/box", json=request).status_code == 200
    obstacle = project.bundle()["scene"]["obstacles"][0]
    before_obstacle = project.path.read_bytes()
    move = {"dx_m": project.obstacle()["origin_x_m"] - 50, "dy_m": 0}
    moved_obstacle = project.client.post(project.url + "/scene/move", json={
        "entity_id": obstacle["scene_object_id"], **move,
    })
    assert (moved_roof.status_code, moved_obstacle.status_code) == (422, 422)
    assert roof.path.read_bytes() == before_roof
    assert project.path.read_bytes() == before_obstacle
    assert roof.field_id in moved_roof.json()["detail"]
    canonical_roof = roof.client.post(roof.url + "/scene/move", json={
        "entity_id": surface["surface_id"], "dx_m": 10, "dy_m": 0,
    })
    assert canonical_roof.json() == moved_roof.json()
    assert moved_obstacle.json()["detail"]["conflicts"]
    canonical = project.client.post(project.url + "/scene/move", json={
        "entity_id": obstacle["obstacle_id"], **move, "dry_run": True,
    })
    alias = project.client.post(project.url + "/scene/move", json={
        "entity_id": obstacle["scene_object_id"], **move, "dry_run": True,
    })
    assert canonical.status_code == alias.status_code == 200
    assert canonical.json() == alias.json()


def test_12_obstacle_edits_use_existing_conflict_policies_for_both_ids(tmp_path):
    for alias in (False, True):
        for option in ("remove_modules", "refill_field"):
            project = Project(tmp_path / f"vertex-{alias}-{option}")
            assert project.client.post(project.url + "/obstacles/box", json=project.obstacle(
                origin_x_m=0.3, origin_y_m=-1, width_m=3.442, depth_m=0.2,
            )).status_code == 200
            obstacle = project.bundle()["scene"]["obstacles"][0]
            target = obstacle["scene_object_id" if alias else "obstacle_id"]
            params = {"vertex_index": 3, "target_x_m": 0.3, "target_y_m": 2.85}
            rejected = _reject(project, "move_vertex", [target], params)
            assert sum(c["code"] == "module_obstacle_overlap" for c in rejected.json()["detail"]["conflicts"]) == 3
            before = {m["module_instance_id"]: m for m in project.modules()}
            preview = _send(project, "move_vertex", [target], params, dry_run=True)
            assert preview.status_code == 200
            removal = preview.json()["options"]["remove_modules"]["module_instance_ids"]
            response = _send(project, "move_vertex", [target], params, on_module_conflict=option)
            assert response.status_code == 200, response.text
            if option == "remove_modules":
                assert {m["module_instance_id"]: m for m in project.modules()} == {mid: m for mid, m in before.items() if mid not in removal}
            assert not any(c["code"] == "module_obstacle_overlap" for c in project.layout()["conflicts"])
        for kind, params in (("rotate", {"angle_deg": 90, "origin": [0, 0]}),
                             ("edit_exact_dimension", {"edge_index": 0, "length_m": 4}),
                             ("edit_exact_angle", {"edge_index": 1, "azimuth_deg": 80})):
            project = Project(tmp_path / f"{kind}-{alias}")
            assert project.client.post(project.url + "/obstacles/box", json=project.obstacle(
                origin_x_m=-1.2, origin_y_m=0.3, width_m=0.2, depth_m=3,
            )).status_code == 200
            obstacle = project.bundle()["scene"]["obstacles"][0]
            target = obstacle["scene_object_id" if alias else "obstacle_id"]
            response = _reject(project, kind, [target], params)
            assert response.json()["detail"]["conflicts"]
        project = Project(tmp_path / f"elevation-{alias}")
        assert project.client.post(project.url + "/obstacles/box", json=project.obstacle(base_elevation_m=10)).status_code == 200
        obstacle = project.bundle()["scene"]["obstacles"][0]
        target = obstacle["scene_object_id" if alias else "obstacle_id"]
        response = _reject(project, "edit_elevation", [target], {"base_elevation_m": 6.1})
        assert response.json()["detail"]["conflicts"]
        assert _send(project, "edit_elevation", [target], {"base_elevation_m": 12}).status_code == 200


def test_13_surface_elevation_resynchronizes_only_z_and_guards_new_pairs(tmp_path):
    project = Project(tmp_path / "raise")
    project.executable()
    before = project.bundle()
    response = _send(project, "edit_elevation", [before["scene"]["surfaces"][0]["scene_object_id"]], {"base_elevation_m": 7.6})
    assert response.status_code == 200, response.text
    after = project.bundle()
    assert after["electrical_design"] == before["electrical_design"]
    for old, new in zip(before["scene"]["module_instances"], after["scene"]["module_instances"]):
        expected = deepcopy(old)
        expected["transform"]["position_z_m"] += 1.5
        assert new["transform"]["position_z_m"] == pytest.approx(expected["transform"]["position_z_m"], abs=1e-9)
        new["transform"]["position_z_m"] = old["transform"]["position_z_m"]
        assert new == old
    project = Project(tmp_path / "lower")
    assert project.client.post(project.url + "/obstacles/box", json=project.obstacle(base_elevation_m=0, height_m=2)).status_code == 200
    response = _reject(project, "edit_elevation", [project.surface_id], {"base_elevation_m": 1})
    detail = response.json()["detail"]
    assert detail["message"] == "Elevation change creates module–obstacle overlaps." and "options" not in detail
    assert len(detail["conflicts"]) == 3
    preview = _send(project, "edit_elevation", [project.surface_id], {"base_elevation_m": 1}, dry_run=True)
    assert preview.status_code == 200 and preview.json() == {"dry_run": True, "conflicts": detail["conflicts"]}
    # Existing pairs are not introduced by this edit and do not block it.
    bundle = project.bundle()
    bundle["scene"]["obstacles"][0].update(base_elevation_m=6.1, height_m=2)
    project.service.store.save(bundle)
    assert _send(project, "edit_elevation", [project.surface_id], {"base_elevation_m": 6.2}).status_code == 200


def test_14_polygon_obstacle_has_box_policies_and_finite_strict_body(tmp_path):
    for option in ("reject", "remove_modules", "refill_field"):
        project = Project(tmp_path / option)
        box_request = project.obstacle()
        x, y = box_request["origin_x_m"], box_request["origin_y_m"]
        width, depth = box_request["width_m"], box_request["depth_m"]
        request = {"vertices": [[x, y], [x + width, y], [x + width, y + depth], [x, y + depth]],
                   "base_elevation_m": 6.1, "height_m": 1, "on_module_conflict": option}
        before = project.path.read_bytes()
        preview = project.client.post(project.url + "/obstacles/extrusion", json={**request, "dry_run": True})
        assert preview.status_code == 200 and preview.json()["options"]["remove_modules"]["module_count"] == 3
        assert project.path.read_bytes() == before
        response = project.client.post(project.url + "/obstacles/extrusion", json=request)
        assert response.status_code == (422 if option == "reject" else 200), response.text
        if option == "reject":
            assert response.json()["detail"]["conflicts"] and project.path.read_bytes() == before
        else:
            assert project.bundle()["scene"]["obstacles"][0]["obstacle_type"] == "extruded_polygon"
            assert not any(c["code"] == "module_obstacle_overlap" for c in project.layout()["conflicts"])
    project = Project(tmp_path / "clear")
    request = {"vertices": [[50, 0], [51, 0], [50, 1]], "height_m": 1}
    assert project.client.post(project.url + "/obstacles/extrusion", json=request).status_code == 200
    before = project.path.read_bytes()
    for bad in ({**request, "extra": 1}, {**request, "vertices": [[0, 0], [1, 1]]}):
        assert project.client.post(project.url + "/obstacles/extrusion", json=bad).status_code == 422
        assert project.path.read_bytes() == before
    for value in (float("nan"), float("inf"), -float("inf")):
        response = project.client.post(project.url + "/obstacles/extrusion", content=json.dumps({**request, "base_elevation_m": value}), headers={"content-type": "application/json"})
        assert response.status_code == 422, response.text
        assert project.path.read_bytes() == before


def test_15_stale_warning_survives_detailed_readiness_and_refill_clears_it(tmp_path):
    from tests.unit.test_rb_fix_s4_pv_field_update import _packed_obstacle
    project = Project(tmp_path / "packed")
    _packed_obstacle(project)
    count = len(project.modules())
    project.service.add_inverter(project.pid, inverter_definition_revision_id=INVERTER, name="INV")
    project.service.create_strings(project.pid, string_length=count)
    iid = project.bundle()["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    project.service.assign_strings(project.pid, inverter_instance_id=iid)
    project.study.acquire_weather(project.pid, source_id="open_meteo_archive_era5", start_date="2025-01-01", end_date="2025-01-01",
        raw_response=(ROOT / "tests/fixtures/weather/open_meteo_era5_phase60d_uat.json").read_bytes())
    def stale(ready):
        return [f for f in ready["findings"] if f["rule_id"] == "SCENE_PV_FIELD_LAYOUT_STALE"]
    fresh = project.study.execution_readiness(project.pid)
    assert fresh["ready"] and stale(fresh) == []
    obstacle = project.bundle()["scene"]["obstacles"][0]
    modules = deepcopy(project.modules())
    assert _send(project, "delete", [obstacle["scene_object_id"]]).status_code == 200
    ready = project.study.execution_readiness(project.pid)
    assert ready["ready"] and len(stale(ready)) == 1
    assert stale(ready)[0]["entity_id"] == project.field_id and stale(ready)[0]["severity"] == "warning"
    assert project.modules() == modules
    detailed = project.study.execution_readiness(project.pid, {"requested_fidelity": "level_2_bypass_substring", "fallback_policy": "explicit_lower_fidelity"})
    assert stale(detailed) == stale(ready)
    assert project.client.patch(project.url + "/pv-fields/" + project.field_id, json={"tilt_deg": 10}).status_code == 200
    assert stale(project.study.execution_readiness(project.pid)) == []
    manual = Project(tmp_path / "manual")
    assert manual.client.post(manual.url + "/obstacles/box", json=manual.obstacle(on_module_conflict="remove_modules")).status_code == 200
    assert stale(manual.study.execution_readiness(manual.pid)) == []
    bundle = project.bundle()
    healthy = deepcopy(bundle)
    bundle["scene"]["surfaces"] = []
    project.service.store.save(bundle)
    assert stale(project.study.execution_readiness(project.pid)) == []
    for damage in ("footprint", "empty_obstacle"):
        damaged = deepcopy(healthy)
        if damage == "footprint":
            damaged["scene"]["pv_fields"][0].pop("module_footprint")
        else:
            damaged["scene"]["obstacles"] = [{"obstacle_id": "damaged", "footprint": {"vertices": []},
                                               "base_elevation_m": 0, "height_m": 1}]
        project.service.store.save(damaged)
        response = project.client.get(project.url + "/execution-readiness")
        assert response.status_code == 200 and stale(response.json()) == []


def test_16_locked_unknown_targets_and_project_errors(tmp_path):
    project = Project(tmp_path)
    surface = _surface(project)
    bundle = project.bundle()
    bundle["scene"]["surfaces"][-1]["locked"] = True
    project.service.store.save(bundle)
    response = _reject(project, "move", [surface["scene_object_id"]], {"dx_m": 1, "dy_m": 0})
    assert "locked" in response.json()["detail"]
    _reject(project, "delete", [surface["surface_id"]])
    response = _reject(project, "move", ["missing"], {"dx_m": 1, "dy_m": 0})
    assert response.json()["detail"] == "scene entity not found: missing"
    response = project.client.post("/api/projects/missing/scene/commands", json=_command("move", [surface["surface_id"]], {"dx_m": 1, "dy_m": 0}))
    assert response.status_code == 404
