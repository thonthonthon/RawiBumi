import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from geometry.pvfield import PVFieldPackingSession
from geometry.scene import SceneEditorSession, canonical_scene_hash
from geometry.scene3d import generate_scene3d


ROOT = Path(__file__).resolve().parents[2]

MODULE = {
    "schema_name": "ModuleDefinition",
    "schema_version": "0.1",
    "module_definition_id": "mod-47hb",
    "revision_id": "mod-47hb-r1",
    "manufacturer": "OpenSIMPV Test",
    "model": "MANUAL-1x2",
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


def _registry():
    registry = Registry()
    for directory in (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "geometry/scene3d",
        ROOT / "electrical/schema",
        ROOT / "apps/web/schema",
    ):
        for path in directory.glob("*.schema.json"):
            schema = _load(str(path.relative_to(ROOT)))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def _roof_scene():
    editor = SceneEditorSession(
        _load("tests/fixtures/phase42/simple-survey-base.scene.json")
    )
    editor.draw_rectangle(
        surface_id="roof",
        scene_object_id="obj-roof",
        name="Manual edit roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=10.0,
        height_m=8.0,
        base_elevation_m=8.0,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    editor.draw_rectangle(
        surface_id="snap-target",
        scene_object_id="obj-snap-target",
        name="Snap target",
        surface_type="reference",
        origin_x_m=6.0,
        origin_y_m=4.0,
        width_m=1.0,
        height_m=1.0,
        base_elevation_m=8.0,
        usable_for_pv=False,
    )
    return editor.scene


def _packed_scene():
    session = PVFieldPackingSession(
        _roof_scene(), {MODULE["revision_id"]: MODULE}
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
        requested_row_count=1,
        requested_modules_per_row=3,
    )
    session.fill_area("field-1")
    return session.scene


def _modules(scene):
    return sorted(
        [
            item
            for item in scene["module_instances"]
            if item["pv_field_id"] == "field-1"
        ],
        key=lambda item: (item["row_index"], item["column_index"]),
    )


def _field(scene):
    return next(
        item
        for item in scene["pv_fields"]
        if item["pv_field_id"] == "field-1"
    )


def _electrical(module_ids):
    return {
        "schema_name": "ElectricalDesignRevision",
        "schema_version": "0.1",
        "electrical_revision_id": "elec-47hb-r1",
        "project_id": "proj-47hb",
        "project_revision_id": "proj-47hb-r1",
        "revision_number": 1,
        "supersedes_revision_id": None,
        "status": "draft",
        "inverter_instances": [],
        "mppt_instances": [],
        "strings": [
            {
                "string_id": "S01",
                "project_revision_id": "proj-47hb-r1",
                "name": "String 1",
                "module_instance_ids": list(module_ids),
                "target_mppt_instance_id": None,
                "enabled": False,
                "polarity": "normal",
            }
        ],
        "connections": [],
        "pcc_definition": {"pcc_id": "pcc-1"},
    }


def test_manual_module_move_preserves_identity_and_string_membership():
    scene = _packed_scene()
    ids = [item["module_instance_id"] for item in _modules(scene)]
    electrical = _electrical(ids)
    electrical_before = deepcopy(electrical)
    session = PVFieldPackingSession(
        scene,
        {MODULE["revision_id"]: MODULE},
        electrical_design=electrical,
    )
    module_id = ids[1]
    before = next(
        item
        for item in session.scene["module_instances"]
        if item["module_instance_id"] == module_id
    )

    report = session.move_module(
        module_id,
        target_x_m=5.0,
        target_y_m=1.0,
    )
    after = next(
        item
        for item in session.scene["module_instances"]
        if item["module_instance_id"] == module_id
    )

    assert after["module_instance_id"] == before["module_instance_id"]
    assert after["transform"]["position_x_m"] == pytest.approx(5.0)
    assert after["metadata"]["manual_position_override"] is True
    assert after["metadata"]["identity_origin"] == "manual_edit_preserved"
    assert _field(session.scene)["layout_status"] == "manual"
    assert _field(session.scene)["layout_source"] == "generated_then_edited"
    assert _field(session.scene)["packing_input_hash"] is None
    assert _field(session.scene)["metadata"]["row_layouts_status"] == "generated_lineage_only"

    assert report["identity_preserved"] is True
    assert report["manual_position_override"] is True
    assert report["affected_strings"] == [
        {
            "string_id": "S01",
            "membership_status": "identity_preserved_geometry_changed",
            "module_instance_id": module_id,
        }
    ]
    assert report["electrical_design_mutated"] is False
    assert session.electrical_design == electrical_before


def test_manual_move_is_atomic_undoable_and_redoable():
    scene = _packed_scene()
    module_id = _modules(scene)[1]["module_instance_id"]
    session = PVFieldPackingSession(
        scene, {MODULE["revision_id"]: MODULE}
    )
    before_hash = canonical_scene_hash(session.scene)

    session.move_module(
        module_id,
        target_x_m=5.0,
        target_y_m=1.0,
    )
    moved_hash = canonical_scene_hash(session.scene)
    assert moved_hash != before_hash

    assert session.undo() is True
    assert canonical_scene_hash(session.scene) == before_hash
    assert session.redo() is True
    assert canonical_scene_hash(session.scene) == moved_hash


def test_manual_move_snapping_is_visible_and_overridable():
    scene = _packed_scene()
    module_id = _modules(scene)[1]["module_instance_id"]

    snapped = PVFieldPackingSession(
        scene, {MODULE["revision_id"]: MODULE}
    )
    report = snapped.move_module(
        module_id,
        target_x_m=5.24,
        target_y_m=3.26,
        snap_tolerance_m=0.4,
        snap_kinds={"user_grid"},
        grid_spacing_m=0.5,
    )
    module = next(
        item
        for item in snapped.scene["module_instances"]
        if item["module_instance_id"] == module_id
    )
    assert module["transform"]["position_x_m"] == pytest.approx(5.0)
    assert module["transform"]["position_y_m"] == pytest.approx(3.5)
    assert report["snap"]["applied"] is True
    assert report["snap"]["kind"] == "user_grid"
    assert report["snap"]["visible_marker"] == "user_grid"

    overridden = PVFieldPackingSession(
        scene, {MODULE["revision_id"]: MODULE}
    )
    report = overridden.move_module(
        module_id,
        target_x_m=5.24,
        target_y_m=3.26,
        snap_tolerance_m=0.4,
        snap_kinds={"user_grid"},
        grid_spacing_m=0.5,
        snap_override=True,
    )
    module = next(
        item
        for item in overridden.scene["module_instances"]
        if item["module_instance_id"] == module_id
    )
    assert module["transform"]["position_x_m"] == pytest.approx(5.24)
    assert module["transform"]["position_y_m"] == pytest.approx(3.26)
    assert report["snap"]["applied"] is False


def test_manual_rotation_preserves_identity_and_propagates_to_derived_3d():
    scene = _packed_scene()
    module_id = _modules(scene)[1]["module_instance_id"]
    session = PVFieldPackingSession(
        scene, {MODULE["revision_id"]: MODULE}
    )

    report = session.rotate_module(module_id, azimuth_deg=90.0)
    module = next(
        item
        for item in session.scene["module_instances"]
        if item["module_instance_id"] == module_id
    )
    assert module["module_instance_id"] == module_id
    assert module["transform"]["rotation_z_deg"] == pytest.approx(90.0)
    assert report["identity_preserved"] is True

    generated = generate_scene3d(session.scene)
    generated_module = next(
        item
        for item in generated["modules"]
        if item["module_instance_id"] == module_id
    )
    assert generated_module["azimuth_deg"] == pytest.approx(90.0)


def test_manual_conflict_is_reported_without_reverting_the_engineer_edit():
    scene = _packed_scene()
    modules = _modules(scene)
    first_id = modules[0]["module_instance_id"]
    second = modules[1]
    session = PVFieldPackingSession(
        scene, {MODULE["revision_id"]: MODULE}
    )

    report = session.move_module(
        first_id,
        target_x_m=second["transform"]["position_x_m"],
        target_y_m=second["transform"]["position_y_m"],
    )
    codes = {
        item["code"] for item in report["conflict_report"]["conflicts"]
    }

    assert report["conflict_report"]["status"] == "conflict"
    assert "module_module_overlap" in codes
    assert _field(session.scene)["layout_status"] == "manual"
    moved = next(
        item
        for item in session.scene["module_instances"]
        if item["module_instance_id"] == first_id
    )
    assert moved["transform"]["position_x_m"] == pytest.approx(
        second["transform"]["position_x_m"]
    )


def test_generated_rebuild_after_manual_move_does_not_resurrect_old_identity():
    scene = _packed_scene()
    old_module = _modules(scene)[1]
    old_id = old_module["module_instance_id"]
    electrical = _electrical([old_id])
    session = PVFieldPackingSession(
        scene,
        {MODULE["revision_id"]: MODULE},
        electrical_design=electrical,
    )

    session.move_module(
        old_id,
        target_x_m=5.0,
        target_y_m=1.0,
    )
    assert any(
        item["module_instance_id"] == old_id
        for item in session.scene["module_instances"]
    )

    rebuilt = session.rebuild_field("field-1")
    impact = rebuilt["layout_impact"]
    slot_move = next(
        item
        for item in impact["moved_modules"]
        if item["old_module_instance_id"] == old_id
    )

    assert slot_move["identity_preserved"] is False
    assert slot_move["new_module_instance_id"] != old_id
    assert old_id in impact["invalidated_module_ids"]
    assert impact["topology_status"] == "review_required"
    assert impact["affected_strings"][0]["string_id"] == "S01"


def test_move_vertex_is_explicit_snapped_and_invalid_polygon_fails_closed():
    editor = SceneEditorSession(_roof_scene())
    before_depth = editor.undo_depth

    result = editor.move_vertex(
        "roof",
        vertex_index=1,
        target_x_m=9.76,
        target_y_m=0.24,
        snap_tolerance_m=0.4,
        snap_kinds={"user_grid"},
        grid_spacing_m=0.5,
    )
    roof = next(
        item for item in editor.scene["surfaces"]
        if item["surface_id"] == "roof"
    )
    assert roof["boundary_2d"]["vertices"][1] == pytest.approx([10.0, 0.0])
    assert result["snap"]["applied"] is True
    assert result["snap"]["kind"] == "user_grid"
    assert roof["geometry_source"] == "user_override"
    assert editor.undo_depth == before_depth + 1

    before_hash = editor.canonical_hash()
    depth = editor.undo_depth
    with pytest.raises(ValueError):
        editor.move_vertex(
            "roof",
            vertex_index=1,
            target_x_m=0.0,
            target_y_m=8.0,
        )
    assert editor.canonical_hash() == before_hash
    assert editor.undo_depth == depth


def test_manual_edit_save_reload_preserves_identity_geometry_and_hash():
    scene = _packed_scene()
    module_id = _modules(scene)[1]["module_instance_id"]
    packing = PVFieldPackingSession(
        scene, {MODULE["revision_id"]: MODULE}
    )
    packing.move_module(
        module_id,
        target_x_m=5.0,
        target_y_m=1.0,
    )

    editor = SceneEditorSession(packing.scene)
    editor.move_vertex(
        "roof",
        vertex_index=2,
        target_x_m=10.5,
        target_y_m=8.0,
    )
    committed = editor.commit_revision(
        revision_id="scene-47hb-r2",
        revision_number=2,
        created_at="2026-09-24T02:00:00Z",
        created_by="phase47hb-test",
        change_summary="Manual module and vertex edits.",
    )
    expected_hash = editor.canonical_hash()
    encoded = editor.canonical_json()
    reloaded = json.loads(encoded)

    assert canonical_scene_hash(reloaded) == expected_hash
    module = next(
        item
        for item in reloaded["module_instances"]
        if item["module_instance_id"] == module_id
    )
    assert module["transform"]["position_x_m"] == pytest.approx(5.0)
    assert module["metadata"]["manual_position_override"] is True
    assert committed["supersedes_revision_id"] != committed["revision_id"]


def test_manual_edit_report_validates_against_schema():
    scene = _packed_scene()
    module_id = _modules(scene)[1]["module_instance_id"]
    session = PVFieldPackingSession(
        scene, {MODULE["revision_id"]: MODULE}
    )
    report = session.move_module(
        module_id,
        target_x_m=5.0,
        target_y_m=1.0,
    )

    schema = _load("schemas/manual-module-edit-report.schema.json")
    Draft202012Validator(
        schema, registry=_registry()
    ).validate(report)
