import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from geometry.scene import SceneEditorSession


ROOT = Path(__file__).resolve().parents[2]


def _load(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _base_scene():
    return _load("tests/fixtures/phase42/simple-survey-base.scene.json")


def _registry():
    registry = Registry()
    directories = (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
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


def _validate_scene(scene):
    schema = _load("geometry/scene/scene.schema.json")
    Draft202012Validator(schema, registry=_registry()).validate(scene)


def _surface(scene, surface_id):
    return next(
        item for item in scene["surfaces"]
        if item["surface_id"] == surface_id
    )


def _obstacle(scene, obstacle_id):
    return next(
        item for item in scene["obstacles"]
        if item["obstacle_id"] == obstacle_id
    )


def _line(scene, line_id):
    return next(
        item for item in scene["reference_lines"]
        if item["reference_line_id"] == line_id
    )


def test_phase42_schemas_and_command_fixture_are_valid():
    for path in (
        "geometry/scene/scene.schema.json",
        "apps/web/schema/design-workspace-state.schema.json",
        "apps/web/schema/scene-editor-command.schema.json",
    ):
        Draft202012Validator.check_schema(_load(path))

    command_schema = _load(
        "apps/web/schema/scene-editor-command.schema.json"
    )
    command = _load(
        "tests/fixtures/schema/scene-editor-command.example.json"
    )
    Draft202012Validator(command_schema).validate(command)
    _validate_scene(_base_scene())


def test_phase42_site_and_obstacle_primitives_form_a_canonical_scene():
    editor = SceneEditorSession(_base_scene())

    editor.draw_rectangle(
        surface_id="ground-001",
        scene_object_id="obj-ground-001",
        name="Ground boundary",
        surface_type="ground",
        origin_x_m=-5.0,
        origin_y_m=-5.0,
        width_m=40.0,
        height_m=30.0,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    editor.draw_rectangle(
        surface_id="building-001",
        scene_object_id="obj-building-001",
        name="Building footprint",
        surface_type="building_footprint",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=20.0,
        height_m=10.0,
        usable_for_pv=False,
        geometry_source="field_measurement",
    )
    editor.draw_polygon(
        surface_id="roof-001",
        scene_object_id="obj-roof-001",
        name="Main roof",
        surface_type="flat_roof",
        vertices=[(0, 0), (20, 0), (20, 10), (0, 10)],
        base_elevation_m=8.0,
        geometry_source="field_measurement",
    )
    editor.draw_rectangle(
        surface_id="excl-001",
        scene_object_id="obj-excl-001",
        name="Skylight exclusion",
        surface_type="exclusion_area",
        origin_x_m=5.0,
        origin_y_m=4.0,
        width_m=2.0,
        height_m=1.5,
        base_elevation_m=8.0,
        usable_for_pv=False,
    )

    editor.draw_box_obstacle(
        obstacle_id="box-001",
        scene_object_id="obj-box-001",
        name="AHU",
        origin_x_m=8.0,
        origin_y_m=4.0,
        width_m=1.5,
        depth_m=1.0,
        base_elevation_m=8.0,
        height_m=1.2,
    )
    editor.draw_polygon_extrusion(
        obstacle_id="poly-001",
        scene_object_id="obj-poly-001",
        name="Irregular curb",
        vertices=[(12, 2), (14, 2), (14.5, 3), (12, 3)],
        base_elevation_m=8.0,
        height_m=0.5,
    )
    editor.draw_cylinder_obstacle(
        obstacle_id="cyl-001",
        scene_object_id="obj-cyl-001",
        name="Tank vent",
        center_x_m=16.0,
        center_y_m=6.0,
        radius_m=0.35,
        base_elevation_m=8.0,
        height_m=1.0,
        segments=16,
    )
    editor.draw_wall_obstacle(
        obstacle_id="wall-001",
        scene_object_id="obj-wall-001",
        name="Wall",
        start=(2, 8),
        end=(8, 8),
        width_m=0.2,
        base_elevation_m=8.0,
        height_m=1.0,
    )
    editor.draw_wall_obstacle(
        obstacle_id="parapet-001",
        scene_object_id="obj-parapet-001",
        name="Parapet",
        start=(0, 0),
        end=(20, 0),
        width_m=0.15,
        base_elevation_m=8.0,
        height_m=0.8,
        parapet=True,
    )
    editor.draw_pole_obstacle(
        obstacle_id="pole-001",
        scene_object_id="obj-pole-001",
        name="Pole",
        center_x_m=3.0,
        center_y_m=3.0,
        radius_m=0.1,
        base_elevation_m=8.0,
        height_m=2.0,
        segments=12,
    )
    editor.draw_simplified_tree(
        obstacle_id="tree-001",
        scene_object_id="obj-tree-001",
        name="Tree canopy",
        center_x_m=25.0,
        center_y_m=10.0,
        radius_m=2.0,
        base_elevation_m=0.0,
        height_m=6.0,
        segments=16,
    )
    editor.draw_line(
        reference_line_id="ref-001",
        scene_object_id="obj-ref-001",
        name="Survey baseline",
        vertices=[(0, -2), (20, -2)],
        line_type="dimension",
        geometry_source="field_measurement",
    )

    scene = editor.scene
    _validate_scene(scene)

    assert len(scene["surfaces"]) == 4
    assert len(scene["obstacles"]) == 7
    assert len(scene["reference_lines"]) == 1
    assert scene["pv_fields"] == []
    assert scene["module_instances"] == []
    assert _surface(scene, "building-001")["surface_type"] == "building_footprint"
    assert _obstacle(scene, "parapet-001")["obstacle_type"] == "parapet"
    assert _obstacle(scene, "pole-001")["obstacle_type"] == "pole"
    assert _obstacle(scene, "tree-001")["obstacle_type"] == "simplified_tree"


def test_exact_dimension_angle_elevation_and_provenance_are_explicit():
    editor = SceneEditorSession(_base_scene())
    editor.draw_rectangle(
        surface_id="roof-map",
        scene_object_id="obj-roof-map",
        name="Map-derived roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=20.37,
        height_m=10.0,
        base_elevation_m=8.0,
        geometry_source="map_measurement",
    )

    initial = editor.measure_edge("roof-map", edge_index=0)
    assert initial["length_m"] == pytest.approx(20.37)
    assert initial["dimension_source"] == "map_measurement"

    editor.edit_exact_dimension(
        "roof-map",
        edge_index=0,
        length_m=20.0,
        preserve="start",
        source="user_override",
    )
    edited = editor.measure_edge("roof-map", edge_index=0)
    assert edited["length_m"] == pytest.approx(20.0)
    assert edited["dimension_source"] == "user_override"

    sources = _surface(editor.scene, "roof-map")[
        "edge_dimension_sources"
    ]
    provenance = sources[0]
    assert provenance["original_value_m"] == pytest.approx(20.37)
    assert provenance["value_m"] == pytest.approx(20.0)
    assert provenance["source"] == "user_override"
    # Moving endpoint 1 changes adjacent edge 1; its stored value must not stay stale.
    assert sources[1]["source"] == "derived"
    assert sources[1]["value_m"] == pytest.approx(
        editor.measure_edge("roof-map", edge_index=1)["length_m"]
    )

    assert editor.undo() is True
    assert editor.measure_edge("roof-map", edge_index=0)[
        "length_m"
    ] == pytest.approx(20.37)
    assert editor.redo() is True
    assert editor.measure_edge("roof-map", edge_index=0)[
        "length_m"
    ] == pytest.approx(20.0)

    editor.draw_line(
        reference_line_id="bearing",
        scene_object_id="obj-bearing",
        name="Bearing line",
        vertices=[(0.0, 0.0), (0.0, 10.0)],
    )
    assert editor.measure_edge("bearing", edge_index=0)[
        "azimuth_deg"
    ] == pytest.approx(0.0)
    editor.edit_exact_angle(
        "bearing",
        edge_index=0,
        azimuth_deg=90.0,
        preserve="start",
    )
    bearing = editor.measure_edge("bearing", edge_index=0)
    assert bearing["length_m"] == pytest.approx(10.0)
    assert bearing["azimuth_deg"] == pytest.approx(90.0)

    editor.edit_elevation("roof-map", base_elevation_m=8.35)
    assert _surface(editor.scene, "roof-map")[
        "base_elevation_m"
    ] == pytest.approx(8.35)


def test_move_rotate_copy_array_mirror_and_history_are_deterministic():
    editor = SceneEditorSession(_base_scene())
    editor.draw_rectangle(
        surface_id="s1",
        scene_object_id="obj-s1",
        name="Rectangle",
        surface_type="ground",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=2.0,
        height_m=1.0,
    )
    initial_hash = editor.canonical_hash()

    editor.move(["s1"], dx_m=3.0, dy_m=4.0)
    moved_hash = editor.canonical_hash()
    assert moved_hash != initial_hash
    assert editor.undo() is True
    assert editor.canonical_hash() == initial_hash
    assert editor.redo() is True
    assert editor.canonical_hash() == moved_hash

    editor.rotate(["s1"], angle_deg=90.0, origin=(0.0, 0.0))
    rotated = _surface(editor.scene, "s1")["boundary_2d"]["vertices"]
    assert rotated[0] == pytest.approx([4.0, -3.0])

    editor.copy(
        "s1",
        new_entity_id="s-copy",
        new_scene_object_id="obj-s-copy",
        dx_m=10.0,
        dy_m=0.0,
    )
    before_array_depth = editor.undo_depth
    created = editor.array(
        "s1",
        copies=2,
        step_dx_m=4.0,
        step_dy_m=0.0,
        entity_id_prefix="s-array",
        scene_object_id_prefix="obj-s-array",
    )
    assert created == ("s-array-1", "s-array-2")
    assert editor.undo_depth == before_array_depth + 1
    assert editor.undo() is True
    assert all(
        item["surface_id"] not in created
        for item in editor.scene["surfaces"]
    )
    assert editor.redo() is True

    before_mirror = _surface(editor.scene, "s1")[
        "edge_dimension_sources"
    ]
    editor.mirror(
        ["s1"],
        line_start=(0.0, -100.0),
        line_end=(0.0, 100.0),
    )
    after = _surface(editor.scene, "s1")
    assert len(after["edge_dimension_sources"]) == len(before_mirror)
    assert sorted(
        item["edge_index"] for item in after["edge_dimension_sources"]
    ) == [0, 1, 2, 3]


def test_align_distribute_group_lock_hide_selection_and_delete():
    editor = SceneEditorSession(_base_scene())
    positions = [(0.0, 0.0), (4.0, 3.0), (10.0, 6.0)]
    for index, (x, y) in enumerate(positions, start=1):
        editor.draw_rectangle(
            surface_id=f"s{index}",
            scene_object_id=f"obj-s{index}",
            name=f"S{index}",
            surface_type="ground",
            origin_x_m=x,
            origin_y_m=y,
            width_m=1.0,
            height_m=1.0,
        )

    assert editor.select(["s1"]) == ("s1",)
    assert editor.select(["s2"], additive=True) == ("s1", "s2")

    editor.align(["s1", "s2", "s3"], mode="min_y")
    for surface_id in ("s1", "s2", "s3"):
        assert _surface(editor.scene, surface_id)[
            "boundary_2d"
        ]["vertices"][0][1] == pytest.approx(0.0)

    editor.distribute(["s1", "s2", "s3"], axis="x")
    centers = []
    for surface_id in ("s1", "s2", "s3"):
        xs = [
            point[0]
            for point in _surface(editor.scene, surface_id)[
                "boundary_2d"
            ]["vertices"]
        ]
        centers.append((min(xs) + max(xs)) / 2.0)
    assert centers == pytest.approx([0.5, 5.5, 10.5])

    editor.group(["s1", "s2"], group_id="grp-1")
    assert _surface(editor.scene, "s1")["group_id"] == "grp-1"
    assert _surface(editor.scene, "s2")["group_id"] == "grp-1"

    editor.set_locked(["s2"], locked=True)
    before = editor.canonical_hash()
    with pytest.raises(ValueError, match="locked"):
        editor.move(["s1", "s2"], dx_m=1.0, dy_m=0.0)
    assert editor.canonical_hash() == before

    # Lock protects engineering edits, not viewport visibility.
    editor.set_visible(["s2"], visible=False)
    assert _surface(editor.scene, "s2")["visible"] is False
    editor.set_visible(["s2"], visible=True)
    editor.set_locked(["s2"], locked=False)
    editor.set_visible(["s2"], visible=False)
    assert editor.select(["s2"]) == ()
    editor.set_visible(["s2"], visible=True)
    assert editor.select(["s2"]) == ("s2",)

    editor.ungroup(["s1", "s2"])
    assert _surface(editor.scene, "s1")["group_id"] is None

    editor.delete(["s3"])
    assert {item["surface_id"] for item in editor.scene["surfaces"]} == {
        "s1",
        "s2",
    }


def test_snap_engine_is_visible_predictable_and_overridable():
    editor = SceneEditorSession(_base_scene())
    editor.draw_rectangle(
        surface_id="roof",
        scene_object_id="obj-roof",
        name="Roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=10.0,
        height_m=10.0,
    )
    editor.draw_line(
        reference_line_id="diag-a",
        scene_object_id="obj-diag-a",
        name="Diagonal A",
        vertices=[(0.0, 0.0), (10.0, 10.0)],
    )
    editor.draw_line(
        reference_line_id="diag-b",
        scene_object_id="obj-diag-b",
        name="Diagonal B",
        vertices=[(0.0, 10.0), (10.0, 0.0)],
    )
    snaps = editor.snap_engine(
        supplemental_edges={
            "module_edge": [
                ("module-future-1", (0.0, 2.0), (4.0, 2.0))
            ],
            "row_edge": [
                ("row-future-1", (0.0, 3.0), (4.0, 3.0))
            ],
        }
    )

    vertex = snaps.resolve(
        (0.04, 0.03),
        tolerance_m=0.1,
        enabled_kinds={"vertex"},
    )
    assert vertex.applied is True
    assert vertex.kind == "vertex"
    assert vertex.snapped_point == pytest.approx((0.0, 0.0))
    assert vertex.visible_marker == "vertex"

    midpoint = snaps.resolve(
        (5.02, 0.03),
        tolerance_m=0.1,
        enabled_kinds={"midpoint"},
    )
    assert midpoint.snapped_point == pytest.approx((5.0, 0.0))

    edge = snaps.resolve(
        (3.0, 0.04),
        tolerance_m=0.1,
        enabled_kinds={"edge"},
    )
    assert edge.snapped_point == pytest.approx((3.0, 0.0))

    intersection = snaps.resolve(
        (5.03, 4.98),
        tolerance_m=0.1,
        enabled_kinds={"intersection"},
    )
    assert intersection.kind == "intersection"
    assert intersection.snapped_point == pytest.approx((5.0, 5.0))

    grid = snaps.resolve(
        (2.24, 2.26),
        tolerance_m=0.4,
        enabled_kinds={"user_grid"},
        grid_spacing_m=0.5,
    )
    assert grid.snapped_point == pytest.approx((2.0, 2.5))

    parallel = snaps.resolve(
        (3.0, 0.04),
        tolerance_m=0.1,
        enabled_kinds={"parallel"},
        anchor=(0.0, 0.0),
        reference_direction=(1.0, 0.0),
    )
    assert parallel.kind == "parallel"
    assert parallel.snapped_point == pytest.approx((3.0, 0.0))

    perpendicular = snaps.resolve(
        (0.04, 3.0),
        tolerance_m=0.1,
        enabled_kinds={"perpendicular"},
        anchor=(0.0, 0.0),
        reference_direction=(1.0, 0.0),
    )
    assert perpendicular.kind == "perpendicular"
    assert perpendicular.snapped_point == pytest.approx((0.0, 3.0))

    module_edge = snaps.resolve(
        (1.0, 2.04),
        tolerance_m=0.1,
        enabled_kinds={"module_edge"},
    )
    assert module_edge.kind == "module_edge"
    assert module_edge.source_entity_id == "module-future-1"
    assert module_edge.snapped_point == pytest.approx((1.0, 2.0))

    row_edge = snaps.resolve(
        (1.0, 3.04),
        tolerance_m=0.1,
        enabled_kinds={"row_edge"},
    )
    assert row_edge.kind == "row_edge"
    assert row_edge.source_entity_id == "row-future-1"
    assert row_edge.snapped_point == pytest.approx((1.0, 3.0))

    overridden = snaps.resolve(
        (0.04, 0.03),
        tolerance_m=0.1,
        enabled_kinds={"vertex"},
        override=True,
    )
    assert overridden.applied is False
    assert overridden.snapped_point == pytest.approx((0.04, 0.03))


def test_exact_dimension_rejects_unrecognized_provenance_source():
    editor = SceneEditorSession(_base_scene())
    editor.draw_rectangle(
        surface_id="roof-source",
        scene_object_id="obj-roof-source",
        name="Roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=10.0,
        height_m=5.0,
    )
    before = editor.canonical_hash()
    with pytest.raises(ValueError, match="unsupported geometry source"):
        editor.edit_exact_dimension(
            "roof-source",
            edge_index=0,
            length_m=9.5,
            source="screen_pixels",
        )
    assert editor.canonical_hash() == before


def test_invalid_polygon_fails_closed_without_creating_history():
    editor = SceneEditorSession(_base_scene())
    with pytest.raises(ValueError, match="self-intersect"):
        editor.draw_polygon(
            surface_id="bad",
            scene_object_id="obj-bad",
            name="Bow tie",
            surface_type="ground",
            vertices=[(0, 0), (2, 2), (0, 2), (2, 0)],
        )
    assert editor.scene["surfaces"] == []
    assert editor.undo_depth == 0


def test_phase42_exit_gate_survey_scene_roundtrips_without_pv_modules():
    editor = SceneEditorSession(_base_scene())

    editor.draw_rectangle(
        surface_id="roof-survey",
        scene_object_id="obj-roof-survey",
        name="Survey roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=20.0,
        height_m=10.0,
        base_elevation_m=7.8,
        geometry_source="field_measurement",
    )
    editor.draw_rectangle(
        surface_id="exclusion-survey",
        scene_object_id="obj-exclusion-survey",
        name="Access hatch exclusion",
        surface_type="exclusion_area",
        origin_x_m=8.5,
        origin_y_m=4.0,
        width_m=2.0,
        height_m=1.2,
        base_elevation_m=7.8,
        usable_for_pv=False,
        geometry_source="field_measurement",
    )
    editor.draw_box_obstacle(
        obstacle_id="ahu-survey",
        scene_object_id="obj-ahu-survey",
        name="AHU",
        origin_x_m=12.0,
        origin_y_m=3.0,
        width_m=1.5,
        depth_m=1.0,
        base_elevation_m=7.8,
        height_m=1.25,
        geometry_source="field_measurement",
    )
    editor.draw_wall_obstacle(
        obstacle_id="parapet-survey",
        scene_object_id="obj-parapet-survey",
        name="South parapet",
        start=(0.0, 0.0),
        end=(20.0, 0.0),
        width_m=0.15,
        base_elevation_m=7.8,
        height_m=0.8,
        parapet=True,
        geometry_source="field_measurement",
    )

    committed = editor.commit_revision(
        revision_id="scene-phase42-survey-r2",
        revision_number=2,
        created_at="2026-09-24T01:00:00Z",
        created_by="phase42-test",
        change_summary="Recreated rooftop from survey dimensions.",
    )
    _validate_scene(committed)

    assert committed["supersedes_revision_id"] == "scene-phase42-survey-r1"
    assert committed["pv_fields"] == []
    assert committed["module_instances"] == []
    assert editor.undo_depth == 0
    assert editor.redo_depth == 0

    encoded = editor.canonical_json()
    reloaded = json.loads(encoded)
    _validate_scene(reloaded)

    reloaded_editor = SceneEditorSession(reloaded)
    assert reloaded_editor.canonical_hash() == editor.canonical_hash()
    assert reloaded_editor.measure_edge(
        "roof-survey", edge_index=0
    )["length_m"] == pytest.approx(20.0)
    assert reloaded_editor.measure_edge(
        "roof-survey", edge_index=1
    )["length_m"] == pytest.approx(10.0)
