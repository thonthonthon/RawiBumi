"""USE3C: table stacking, canonical heights and one-row compatibility."""
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
import math
import random
from time import perf_counter

import pytest

from geometry.pvfield import PVFieldPackingSession, packing
from geometry.pvfield.pitch import shading_free_row_pitch
from geometry.scene.surface_plane import SurfacePlane, module_center_z, synchronize_scene_module_center_z
from geometry.scene3d.generator import _module_geometry
from geometry.scene3d.height import module_axes
from tests.unit.test_phase43_pvfield_packing import MODULE, _roof_scene
from tests.unit.test_rb_fix_s2_honest_preflight import Project, MODULE as API_MODULE


def case(rows=2, leftover="smaller_table", *, depth=11., slope=0., roof_azimuth=0.):
    scene = _roof_scene(width=3., height=depth)
    roof = packing._surface(scene, "roof")
    roof.update(slope_deg=slope, azimuth_deg=roof_azimuth)
    field = {"pv_field_id": "field-1", "support_surface_id": "roof", "module_definition_revision_id": MODULE["revision_id"],
             "orientation": "portrait", "azimuth_deg": 0., "tilt_deg": 0., "row_pitch_m": 2. * rows + 1.,
             "module_gap_x_m": 0., "module_gap_y_m": 0., "mounting_height_m": 1.}
    if rows > 1:
        field["table_configuration"] = {"rows_per_table": rows, "leftover_depth": leftover, "modules_per_table_x": 3}
    return scene, field


def install(scene, result):
    scene = deepcopy(scene)
    scene["pv_fields"] = [result.pv_field]
    scene["module_instances"] = list(deepcopy(result.module_instances))
    return scene


@pytest.mark.parametrize("rows,depth,full_rows", [(2, 12., 5), (3, 10., 4)])
@pytest.mark.parametrize("leftover", ["smaller_table", "smaller_table_front", "leave_empty"])
def test_hand_counts_leftover_side_and_constant_aisle(rows, depth, full_rows, leftover):
    scene, field = case(rows, leftover, depth=depth)
    result = packing.pack_field(scene, field, MODULE)
    expected_rows = full_rows if leftover != "leave_empty" else full_rows - 1
    assert len(result.module_instances) == 3 * expected_rows
    tables = defaultdict(list)
    for m in result.module_instances:
        tables[m["table_index"]].append(m)
    bounds = sorted((min(m["transform"]["position_y_m"] for m in ms) - 1.,
                     max(m["transform"]["position_y_m"] for m in ms) + 1., len(ms) // 3) for ms in tables.values())
    assert all(b[0] - a[1] == pytest.approx(1.) for a, b in zip(bounds, bounds[1:]))
    if leftover != "leave_empty":
        assert bounds[0 if leftover == "smaller_table" else -1][2] == 1
    assert [m["row_index"] for m in result.module_instances] == sorted(m["row_index"] for m in result.module_instances)


@pytest.mark.parametrize("slope,azimuth", [(0., 0.), (5., 90.), (10., 0.)])
def test_column_coplanarity_gap_and_synchronized_height(slope, azimuth):
    scene, field = case(slope=slope, roof_azimuth=azimuth, depth=14.)
    field.update(tilt_deg=10., module_gap_y_m=.2, row_pitch_m=5.)
    result = packing.pack_field(scene, field, MODULE)
    scene = install(scene, result)
    assert synchronize_scene_module_center_z(scene) == []
    plane = SurfacePlane.from_surface(packing._surface(scene, "roof"))
    groups = defaultdict(list)
    normal = module_axes(0., 10.)[2]
    for m in result.module_instances:
        geometry, _, findings = _module_geometry(m, result.pv_field, plane)
        assert not any(f["code"] == "module_center_z_inconsistent" for f in findings)
        groups[m["table_index"], m["column_index"]].append((m, geometry))
        if slope == 10. and azimuth == 0.:
            t = m["transform"]
            assert t["position_z_m"] == pytest.approx(module_center_z(packing._surface(scene, "roof"), t["position_x_m"], t["position_y_m"], 1.), abs=1e-9)
    for column in groups.values():
        column.sort(key=lambda item: item[0]["metadata"]["table_row_offset"])
        for (_, front), (_, back) in zip(column, column[1:]):
            origin = front["corners_3d"][0]
            assert all(abs(sum(n * (p - p0) for n, p, p0 in zip(normal, corner, origin))) < 1e-9 for corner in back["corners_3d"])
            assert math.dist(front["corners_3d"][0], back["corners_3d"][3]) == pytest.approx(.2, abs=1e-9)
    front = [m for m in scene["module_instances"] if m["metadata"]["table_row_offset"] == 0]
    left, right = next((a, b) for a in front for b in front if a["table_index"] == b["table_index"] and b["column_index"] == a["column_index"] + 1)
    delta = [right["transform"][k] - left["transform"][k] for k in ("position_x_m", "position_y_m", "position_z_m")]
    residual = abs(sum(a * b for a, b in zip(normal, delta)))
    assert residual == pytest.approx(math.tan(math.radians(slope)) * math.cos(math.radians(10.)) if azimuth == 90. else 0., abs=1e-9)
    before = {m["module_instance_id"]: m["transform"]["position_z_m"] for m in scene["module_instances"]}
    packing._surface(scene, "roof")["base_elevation_m"] += 2.
    synchronize_scene_module_center_z(scene)
    assert all(m["transform"]["position_z_m"] == pytest.approx(before[m["module_instance_id"]] + 2.) for m in scene["module_instances"])


def test_moves_and_drop_fill_keep_or_take_row_offset():
    scene, field = case(depth=14., slope=5., roof_azimuth=90.)
    field.update(tilt_deg=10., module_gap_y_m=.2, row_pitch_m=5.)
    result = packing.pack_field(scene, field, MODULE)
    scene = install(scene, result)
    session = PVFieldPackingSession(scene, {MODULE["revision_id"]: MODULE})
    back = next(m for m in scene["module_instances"] if m["metadata"]["table_row_offset"] == 1)
    mid = back["module_instance_id"]
    session.move_modules([mid], dx_m=.05, dy_m=.05)
    moved = next(m for m in session.scene["module_instances"] if m["module_instance_id"] == mid)
    assert moved["metadata"]["table_row_offset"] == 1
    session.move_module(mid, target_x_m=moved["transform"]["position_x_m"] + .05, target_y_m=moved["transform"]["position_y_m"] + .05)
    moved = next(m for m in session.scene["module_instances"] if m["module_instance_id"] == mid)
    t = moved["transform"]
    assert t["position_z_m"] == pytest.approx(module_center_z(packing._surface(scene, "roof"), t["position_x_m"], t["position_y_m"], 1., field=result.pv_field, table_row_offset=1))
    # Free a front-row slot; move the selected back-row module onto that slot through drop-fill.
    front = next(m for m in scene["module_instances"] if m["metadata"]["table_row_offset"] == 0 and m["column_index"] == back["column_index"] and m["table_index"] == back["table_index"])
    session.remove_modules([front["module_instance_id"]])
    session.fill_move_modules([mid], front["transform"]["position_x_m"] - t["position_x_m"], front["transform"]["position_y_m"] - t["position_y_m"])
    placed = next(m for m in session.scene["module_instances"] if m["module_instance_id"] == mid)
    assert placed["metadata"]["table_row_offset"] == 0
    assert placed["metadata"]["position_z_basis"] == "support_plane_plus_vertical_mounting_height"
    assert placed["transform"] == front["transform"]


def test_errors():
    scene, field = case()
    field["row_pitch_m"] = 3.9
    with pytest.raises(ValueError, match="tables would overlap"):
        packing.pack_field(scene, field, MODULE)
    field["row_pitch_m"] = 5.
    field["packing_parameters"] = {"requested_row_count": 2}
    with pytest.raises(ValueError, match="requested_row_count"):
        packing.pack_field(scene, field, MODULE)


def test_random_phase_search_matches_exhaustive(monkeypatch):
    rng = random.Random(20261113)
    estimator = packing._phase_estimator
    for _ in range(20):
        scene, field = case(leftover=rng.choice(["smaller_table", "smaller_table_front", "leave_empty"]), depth=rng.uniform(6., 15.))
        width, skew = rng.uniform(1., 5.), rng.uniform(-.3, .3)
        roof = packing._surface(scene, "roof")
        roof["boundary_2d"]["vertices"] = [[0, 0], [width, skew], [width, 14. + skew], [0, 14.]]
        counts = []
        for phase in range(16):
            # Force every phase to the top of the ranking and disable bound pruning after it.
            calls = []
            def forced(*args):
                bound = estimator(*args)
                def score(rows):
                    calls.append(bound(rows))
                    return 10**9 if len(calls) - 1 == phase else 0
                return score
            with monkeypatch.context() as patch:
                patch.setattr(packing, "_phase_estimator", forced)
                counts.append(len(packing.pack_field(scene, field, MODULE).module_instances))
        actual = packing.pack_field(scene, field, MODULE)
        assert len(actual.module_instances) == max(counts)


def test_pitch_single_row_identity_and_two_row_formula():
    args = dict(orientation="portrait", tilt_deg=10., design_sun_elevation_deg=30.)
    one = shading_free_row_pitch(MODULE, **args)
    assert shading_free_row_pitch(MODULE, **args, rows_per_table=1, module_gap_y_m=.7) == one
    two = shading_free_row_pitch(MODULE, **args, rows_per_table=2, module_gap_y_m=.2)
    assert two["row_pitch_m"] == pytest.approx(4.2 * (math.cos(math.radians(10)) + math.sin(math.radians(10)) / math.tan(math.radians(30))))
    assert two["inputs"]["rows_per_table"] == 2
    assert "rows_per_table" not in one["inputs"]


def test_storage_update_two_to_one_and_existing_table_keys():
    scene, _ = case()
    session = PVFieldPackingSession(scene, {MODULE["revision_id"]: MODULE})
    args = dict(pv_field_id="field-1", name="Tables", support_surface_id="roof", module_definition_revision_id=MODULE["revision_id"], orientation="portrait", azimuth_deg=0., tilt_deg=0., module_gap_x_m=0., module_gap_y_m=0., row_pitch_m=5., mounting_height_m=1., table_configuration={"modules_per_table_x": 3})
    session.create_field(**args, rows_per_table=2)
    session.fill_area("field-1")
    session.update_field("field-1", rows_per_table=1)
    restored = session.scene["pv_fields"][0]
    assert restored["table_configuration"] == {"modules_per_table_x": 3}
    fresh = PVFieldPackingSession(scene, {MODULE["revision_id"]: MODULE})
    fresh.create_field(**args)
    fresh.fill_area("field-1")
    # Compare pure packer outputs; rebuild history deliberately records preserved identities.
    assert asdict(packing.pack_field(session.scene, restored, MODULE)) == asdict(packing.pack_field(fresh.scene, fresh.scene["pv_fields"][0], MODULE))


@pytest.mark.parametrize("leftover,rows", [("smaller_table", 5), ("smaller_table_front", 5), ("leave_empty", 4)])
def test_api_creation_refill_and_pitch(tmp_path, leftover, rows):
    p = Project(tmp_path, 20, weather=False, strings=False)
    bundle = p.bundle()
    old = bundle["scene"]["pv_fields"][0]
    assert not (old.get("table_configuration") or {}).get("rows_per_table")
    sid = old["support_surface_id"]
    p.client.delete(p.url + "/pv-fields/" + old["pv_field_id"])
    # A new rectangle, away from the existing roof; UAT module length is 2.278 m.
    response = p.client.post(p.url + "/surfaces/rectangle", json={"name": "Tables roof", "origin_x_m": 100., "width_m": 4., "height_m": 13.5, "base_elevation_m": 6.})
    sid = response.json()["bundle"]["scene"]["surfaces"][-1]["surface_id"]
    body = dict(name="Tables", support_surface_id=sid, module_definition_revision_id=API_MODULE, rows_per_table=2,
                leftover_depth=leftover, tilt_deg=0., row_pitch_m=5.5, module_gap_x_m=0., module_gap_y_m=0., perimeter_setback_m=0., obstacle_setback_m=0.)
    response = p.client.post(p.url + "/pv-fields", json=body)
    assert response.status_code == 200, response.text
    field = response.json()["bundle"]["scene"]["pv_fields"][0]
    assert field["table_configuration"]["rows_per_table"] == 2
    assert field["table_configuration"]["leftover_depth"] == leftover
    assert len(response.json()["bundle"]["scene"]["module_instances"]) == 3 * rows
    response = p.client.patch(p.url + "/pv-fields/" + field["pv_field_id"], json={"rows_per_table": 1})
    assert response.status_code == 200, response.text
    assert not (response.json()["bundle"]["scene"]["pv_fields"][0]["table_configuration"] or {})
    response = p.client.post(p.url + "/pv-fields/shading-free-pitch", json={"module_definition_revision_id": API_MODULE, "orientation": "portrait", "tilt_deg": 10., "design_sun_elevation_deg": 30., "rows_per_table": 2, "module_gap_y_m": .2})
    assert response.status_code == 200, response.text
    assert response.json()["inputs"]["rows_per_table"] == 2


def test_timing_10000_r2_modules():
    scene, field = case(depth=249.)
    packing._surface(scene, "roof")["boundary_2d"]["vertices"] = [[0, 0], [100, 0], [100, 249], [0, 249]]
    start = perf_counter()
    result = packing.pack_field(scene, field, MODULE)
    seconds = perf_counter() - start
    assert len(result.module_instances) == 10000
    print({"rows_per_table": 2, "modules": 10000, "seconds": seconds})


@pytest.mark.parametrize("tilt,expected", [
    (0., "a9dcdf074a943bf0761e108682532b6d5a7ea344d5273dec9a5412144e431880"),
    (10., "8ba27c72138ffc096f631babf3a95dcb44544e656151735333ddb739d800dc60"),
    (30., "69c25b0049603ad869330a61d2bb91587522caf6ac14823634e4b07fc8de6ea2"),
])
def test_r1_byte_identity_against_321c1d0(tilt, expected):
    scene, field = case(rows=1, depth=12.)
    field.update(tilt_deg=tilt, row_pitch_m=3.)
    result = asdict(packing.pack_field(scene, field, MODULE))
    assert sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == expected


def test_table_indices_split_contiguous_column_runs():
    scene, field = case(depth=9.)
    packing._surface(scene, "roof")["boundary_2d"]["vertices"] = [[0, 0], [5, 0], [5, 9], [0, 9]]
    field["table_configuration"]["modules_per_table_x"] = 5
    scene["obstacles"] = [{"obstacle_id": "gap", "footprint": {"vertices": [[2.1, -1], [2.9, -1], [2.9, 10], [2.1, 10]]}}]
    result = packing.pack_field(scene, field, MODULE)
    # The missing central column separates each table into two contiguous runs; both rows share each run's index.
    groups = defaultdict(list)
    for module in result.module_instances:
        groups[module["table_index"]].append(module)
    assert len(groups) == 4
    assert all({m["metadata"]["table_row_offset"] for m in modules} == {0, 1} for modules in groups.values())


@pytest.mark.parametrize("table", [None, {}, {"modules_per_table_x": 3}])
def test_r1_create_preserves_existing_table_configuration(table):
    scene, _ = case()
    session = PVFieldPackingSession(scene, {MODULE["revision_id"]: MODULE})
    field = session.create_field(pv_field_id="field-1", name="Legacy", support_surface_id="roof",
        module_definition_revision_id=MODULE["revision_id"], orientation="portrait", azimuth_deg=0., tilt_deg=10.,
        module_gap_x_m=0., module_gap_y_m=0., row_pitch_m=3., mounting_height_m=1.,
        table_configuration=table, rows_per_table=1)
    assert field["table_configuration"] == table
