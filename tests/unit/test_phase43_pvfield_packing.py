import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from geometry.pvfield import (
    ModuleFootprint,
    PVFieldPackingSession,
    packing_snap_edges,
    polygons_overlap_or_touch,
    rectangle_polygon,
)
from geometry.scene import (
    SceneEditorSession,
    SnapEngine,
    canonical_scene_hash,
    canonical_scene_json,
)


ROOT = Path(__file__).resolve().parents[2]
MODULE = {
    "schema_name": "ModuleDefinition",
    "schema_version": "0.1",
    "module_definition_id": "mod-pack-ref",
    "revision_id": "mod-pack-ref-r1",
    "manufacturer": "OpenSIMPV Test",
    "model": "PACK-1x2",
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
    "capability_flags": {
        "layout_ready": True,
        "basic_yield_ready": True,
        "detailed_sdm_ready": False,
        "bifacial_ready": False,
        "detailed_shading_ready": False,
    },
}


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _base_scene():
    return _load("tests/fixtures/phase42/simple-survey-base.scene.json")


def _schema_registry():
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


def _roof_scene(width=10.0, height=8.0):
    editor = SceneEditorSession(_base_scene())
    editor.draw_rectangle(
        surface_id="roof",
        scene_object_id="obj-roof",
        name="Packing roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=width,
        height_m=height,
        base_elevation_m=8.0,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    return editor.scene


def _new_session(
    scene,
    *,
    setback=0.0,
    obstacle_setback=0.0,
    requested_rows=None,
    requested_per_row=None,
    table_configuration=None,
):
    session = PVFieldPackingSession(
        scene, {MODULE["revision_id"]: MODULE}
    )
    session.create_field(
        pv_field_id="field-1",
        name="Field 1",
        support_surface_id="roof",
        module_definition_revision_id=MODULE["revision_id"],
        orientation="portrait",
        azimuth_deg=0.0,
        tilt_deg=10.0,
        module_gap_x_m=0.0,
        module_gap_y_m=0.0,
        row_pitch_m=2.0,
        mounting_height_m=0.2,
        perimeter_setback_m=setback,
        obstacle_setback_m=obstacle_setback,
        table_configuration=table_configuration,
        requested_row_count=requested_rows,
        requested_modules_per_row=requested_per_row,
    )
    return session


def _field(scene):
    return next(item for item in scene["pv_fields"] if item["pv_field_id"] == "field-1")


def _modules(scene):
    return [
        item
        for item in scene["module_instances"]
        if item["pv_field_id"] == "field-1"
    ]


def test_module_footprint_uses_pinned_component_dimensions():
    portrait = ModuleFootprint.from_definition(MODULE, "portrait")
    landscape = ModuleFootprint.from_definition(MODULE, "landscape")
    assert (portrait.packed_width_m, portrait.packed_height_m) == (1.0, 2.0)
    assert (landscape.packed_width_m, landscape.packed_height_m) == (2.0, 1.0)
    assert portrait.module_definition_revision_id == "mod-pack-ref-r1"


def test_fill_area_rectangular_reference_is_exact_and_deterministic():
    first = _new_session(_roof_scene())
    result = first.fill_area("field-1")
    scene = first.scene

    assert result["module_count"] == 40
    assert _field(scene)["row_count"] == 4
    assert _field(scene)["modules_per_row"] == 10
    assert len(_field(scene)["generated_module_instance_ids"]) == 40
    assert _modules(scene)[0]["module_instance_id"].startswith("field-1-m-")
    assert _modules(scene)[0]["transform"]["position_x_m"] == pytest.approx(0.5)
    expected_first_row_y = math.cos(math.radians(10.0))
    assert _modules(scene)[0]["transform"]["position_y_m"] == pytest.approx(
        expected_first_row_y
    )
    assert _modules(scene)[-1]["transform"]["position_x_m"] == pytest.approx(9.5)
    assert _modules(scene)[-1]["transform"]["position_y_m"] == pytest.approx(
        expected_first_row_y + 3.0 * 2.0
    )

    second = _new_session(_roof_scene())
    second_result = second.fill_area("field-1")
    assert second_result["packing_input_hash"] == result["packing_input_hash"]
    assert _modules(second.scene) == _modules(scene)
    assert canonical_scene_json(second.scene) == canonical_scene_json(scene)


def test_perimeter_setback_changes_exact_usable_envelope():
    session = _new_session(_roof_scene(), setback=0.5)
    result = session.fill_area("field-1")

    assert result["module_count"] == 27
    assert _field(session.scene)["row_count"] == 3
    assert _field(session.scene)["modules_per_row"] == 9


def test_exclusion_and_obstacle_rules_are_hard_constraints():
    editor = SceneEditorSession(_roof_scene())
    editor.draw_rectangle(
        surface_id="exclude",
        scene_object_id="obj-exclude",
        name="Access hatch",
        surface_type="exclusion_area",
        origin_x_m=4.0,
        origin_y_m=2.0,
        width_m=2.0,
        height_m=2.0,
        base_elevation_m=8.0,
        usable_for_pv=False,
    )
    editor.draw_box_obstacle(
        obstacle_id="ahu",
        scene_object_id="obj-ahu",
        name="AHU",
        origin_x_m=7.2,
        origin_y_m=5.2,
        width_m=0.6,
        depth_m=0.6,
        base_elevation_m=8.0,
        height_m=1.2,
    )

    session = _new_session(editor.scene, obstacle_setback=0.2)
    result = session.fill_area("field-1")
    report = session.conflict_report("field-1")

    assert result["module_count"] < 40
    assert report["status"] == "valid"
    assert report["conflict_count"] == 0
    assert set(_field(session.scene)["resolved_exclusion_ids"]) == {
        "exclude",
        "ahu",
    }


def test_find_maximum_modules_is_advisory_and_does_not_mutate_scene():
    session = _new_session(_roof_scene())
    before = canonical_scene_hash(session.scene)
    suggestion = session.find_maximum_modules("field-1")
    after = canonical_scene_hash(session.scene)

    assert before == after
    assert suggestion["engineering_state_mutated"] is False
    assert suggestion["proposals"][0]["orientation"] == "portrait"
    assert suggestion["proposals"][0]["module_count"] == 40
    assert suggestion["proposals"][1]["orientation"] == "landscape"
    assert suggestion["proposals"][1]["module_count"] == 20


def test_change_orientation_is_explicit_and_undoable():
    session = _new_session(_roof_scene())
    session.fill_area("field-1")
    portrait_hash = canonical_scene_hash(session.scene)

    changed = session.change_orientation("field-1", "landscape")
    assert changed["module_count"] == 20
    assert _field(session.scene)["orientation"] == "landscape"

    assert session.undo() is True
    assert canonical_scene_hash(session.scene) == portrait_hash
    assert _field(session.scene)["orientation"] == "portrait"
    assert session.redo() is True
    assert _field(session.scene)["orientation"] == "landscape"


def test_table_arrangement_changes_spacing_and_assigns_tables():
    session = _new_session(
        _roof_scene(),
        requested_rows=1,
        requested_per_row=6,
        table_configuration={
            "modules_per_table_x": 2,
            "table_gap_x_m": 0.5,
        },
    )
    session.fill_area("field-1")
    modules = _modules(session.scene)
    xs = [item["transform"]["position_x_m"] for item in modules]

    assert len(modules) == 6
    assert xs == pytest.approx([0.5, 1.5, 3.0, 4.0, 5.5, 6.5])
    assert [item["table_index"] for item in modules] == [0, 0, 1, 1, 2, 2]


def test_equalize_spacing_is_an_explicit_rebuild_command():
    session = _new_session(
        _roof_scene(),
        requested_rows=1,
        requested_per_row=5,
    )
    session.fill_area("field-1")
    assert _field(session.scene)["module_gap_x_m"] == 0.0

    result = session.equalize_spacing("field-1", axis="horizontal")
    field = _field(session.scene)
    xs = [
        item["transform"]["position_x_m"]
        for item in _modules(session.scene)
    ]

    assert result["module_count"] == 5
    assert field["module_gap_x_m"] == pytest.approx(1.25)
    assert xs == pytest.approx([0.5, 2.75, 5.0, 7.25, 9.5])


def test_orient_to_edge_and_align_rows_are_explicit_commands():
    session = _new_session(_roof_scene(width=10.5))
    session.fill_area("field-1")

    session.orient_to_edge(
        "field-1", edge_index=1, alignment_axis="row"
    )
    assert _field(session.scene)["azimuth_deg"] == pytest.approx(270.0)

    session.align_rows("field-1", alignment="center")
    assert _field(session.scene)["packing_parameters"]["row_alignment"] == "center"


def test_moving_obstacle_reports_conflict_without_silent_repacking():
    editor = SceneEditorSession(_roof_scene())
    editor.draw_box_obstacle(
        obstacle_id="movable",
        scene_object_id="obj-movable",
        name="Movable obstacle",
        origin_x_m=11.0,
        origin_y_m=0.5,
        width_m=0.8,
        depth_m=1.0,
        base_elevation_m=8.0,
        height_m=1.0,
    )
    packed = _new_session(editor.scene)
    packed.fill_area("field-1")
    before_scene = packed.scene
    before_modules = _modules(before_scene)

    geometry_editor = SceneEditorSession(before_scene)
    geometry_editor.move(["movable"], dx_m=-10.5, dy_m=0.0)
    changed_scene = geometry_editor.scene

    # Unrelated geometry editing leaves every module coordinate untouched.
    assert _modules(changed_scene) == before_modules

    inspected = PVFieldPackingSession(
        changed_scene, {MODULE["revision_id"]: MODULE}
    )
    report = inspected.conflict_report("field-1")
    codes = {item["code"] for item in report["conflicts"]}

    assert report["status"] == "conflict"
    assert "packing_inputs_changed" in codes
    assert "module_obstacle_overlap" in codes

    inspected.rebuild_field("field-1")
    rebuilt_report = inspected.conflict_report("field-1")
    assert rebuilt_report["status"] == "valid"
    assert len(_modules(inspected.scene)) < len(before_modules)


def test_phase43_module_and_row_edges_feed_existing_snap_engine():
    session = _new_session(_roof_scene())
    session.fill_area("field-1")
    supplemental = session.snap_edges()
    snapper = SnapEngine(
        session.scene, supplemental_edges=supplemental
    )

    module_edge = snapper.resolve(
        (0.04, 1.0),
        tolerance_m=0.1,
        enabled_kinds={"module_edge"},
    )
    assert module_edge.applied is True
    assert module_edge.kind == "module_edge"
    assert module_edge.snapped_point[0] == pytest.approx(0.0)

    row_edge = snapper.resolve(
        (5.0, 1.04),
        tolerance_m=0.1,
        enabled_kinds={"row_edge"},
    )
    assert row_edge.applied is True
    assert row_edge.kind == "row_edge"
    assert row_edge.snapped_point[1] == pytest.approx(
        math.cos(math.radians(10.0))
    )


def test_packed_scene_and_conflict_report_validate_and_roundtrip():
    session = _new_session(_roof_scene(), setback=0.5)
    session.fill_area("field-1")
    scene = session.scene
    report = session.conflict_report("field-1")

    scene_schema = _load("geometry/scene/scene.schema.json")
    conflict_schema = _load(
        "schemas/pv-field-conflict-report.schema.json"
    )
    registry = _schema_registry()
    Draft202012Validator(
        scene_schema, registry=registry
    ).validate(scene)
    Draft202012Validator(
        conflict_schema, registry=registry
    ).validate(report)

    encoded = canonical_scene_json(scene)
    reloaded = json.loads(encoded)
    assert canonical_scene_hash(reloaded) == canonical_scene_hash(scene)
    assert [
        item["transform"] for item in _modules(reloaded)
    ] == [
        item["transform"] for item in _modules(scene)
    ]


def test_pv_field_command_schema_is_valid_and_renderer_neutral():
    schema = _load("apps/web/schema/pv-field-command.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(
        {
            "schema_name": "PVFieldCommand",
            "schema_version": "0.1",
            "command_id": "cmd-fill-001",
            "command_type": "fill_area",
            "pv_field_id": "field-1",
            "parameters": {},
            "issued_at": "2026-09-24T00:00:00Z",
        }
    )
    serialized = json.dumps(schema)
    assert "canvas" not in serialized.lower()
    assert "webgl" not in serialized.lower()
    assert "maplibre" not in serialized.lower()
