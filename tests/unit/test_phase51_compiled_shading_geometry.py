import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from geometry.pvfield import PVFieldPackingSession
from geometry.scene import SceneEditorSession, canonical_scene_hash
from geometry.scene3d import generate_scene3d
from geometry.shading import (
    COMPILER_ID,
    COMPILER_VERSION,
    canonical_compiled_shading_geometry_hash,
    compile_shading_geometry,
)


ROOT = Path(__file__).resolve().parents[2]

MODULE = {
    "schema_name": "ModuleDefinition",
    "schema_version": "0.1",
    "module_definition_id": "mod-phase51",
    "revision_id": "mod-phase51-r1",
    "manufacturer": "RawiBumi Test",
    "model": "P51-1x2",
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
        ROOT / "geometry/shading",
        ROOT / "electrical/schema",
        ROOT / "apps/web/schema",
    ):
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def _scene():
    editor = SceneEditorSession(
        _load("tests/fixtures/phase42/simple-survey-base.scene.json")
    )
    editor.draw_rectangle(
        surface_id="roof",
        scene_object_id="obj-roof",
        name="Roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=12.0,
        height_m=8.0,
        base_elevation_m=8.0,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    editor.draw_box_obstacle(
        obstacle_id="ahu-b",
        scene_object_id="obj-ahu-b",
        name="AHU B",
        origin_x_m=9.0,
        origin_y_m=5.0,
        width_m=1.0,
        depth_m=1.0,
        base_elevation_m=8.0,
        height_m=1.5,
    )
    editor.draw_box_obstacle(
        obstacle_id="ahu-a",
        scene_object_id="obj-ahu-a",
        name="AHU A",
        origin_x_m=10.5,
        origin_y_m=5.0,
        width_m=1.0,
        depth_m=1.0,
        base_elevation_m=8.0,
        height_m=1.0,
    )
    scene = editor.scene
    scene["surfaces"][0]["shading_receiver"] = True

    packing = PVFieldPackingSession(scene, {MODULE["revision_id"]: MODULE})
    packing.create_field(
        pv_field_id="field-1",
        name="Field 1",
        support_surface_id="roof",
        module_definition_revision_id=MODULE["revision_id"],
        orientation="portrait",
        azimuth_deg=180.0,
        tilt_deg=10.0,
        module_gap_x_m=0.02,
        module_gap_y_m=0.02,
        row_pitch_m=2.5,
        mounting_height_m=0.2,
        perimeter_setback_m=0.5,
        obstacle_setback_m=0.5,
        requested_row_count=2,
        requested_modules_per_row=3,
    )
    packing.fill_area("field-1")
    return packing.scene


def _validate(compiled):
    schema = _load("geometry/shading/compiled-shading-geometry.schema.json")
    Draft202012Validator(schema, registry=_registry()).validate(compiled)


def test_phase51_compiler_is_derived_schema_valid_and_does_not_mutate_scene():
    scene = _scene()
    before = canonical_scene_hash(scene)
    compiled = compile_shading_geometry(scene)

    assert canonical_scene_hash(scene) == before
    assert compiled["authority"] == "derived_numerical_only"
    assert compiled["editable"] is False
    assert compiled["compiler_id"] == COMPILER_ID
    assert compiled["compiler_version"] == COMPILER_VERSION
    assert compiled["source_scene_hash"] == before
    assert compiled["source_scene_revision_id"] == scene["revision_id"]
    assert compiled["coordinate_system_id"] == scene["coordinate_system_id"]
    assert compiled["finding_count"] == len(compiled["findings"])
    _validate(compiled)


def test_phase51_module_receivers_reuse_phase44_geometry_exactly():
    scene = _scene()
    scene3d = generate_scene3d(scene)
    compiled = compile_shading_geometry(scene)

    generated = {
        item["module_instance_id"]: item
        for item in scene3d["modules"]
        if item["status"] == "resolved"
    }
    receivers = {
        item["module_instance_id"]: item
        for item in compiled["receivers"]
        if item["source_entity_type"] == "module_instance"
    }
    assert set(receivers) == set(generated)

    for module_id, receiver in receivers.items():
        reference = generated[module_id]
        assert receiver["vertices_3d"] == reference["corners_3d"]
        assert receiver["center_xyz"] == reference["center_xyz"]
        assert receiver["normal_xyz"] == reference["normal_xyz"]
        assert receiver["area_m2"] == pytest.approx(
            reference["plane_width_m"] * reference["plane_height_m"]
        )
        assert receiver["pv_field_id"] == reference["pv_field_id"]
        assert receiver["support_surface_id"] == reference["support_surface_id"]


def test_phase51_compiles_module_self_shading_and_native_obstacle_occluders():
    compiled = compile_shading_geometry(_scene())
    module_occluders = [
        item for item in compiled["occluders"]
        if item["source_entity_type"] == "module_instance"
    ]
    obstacle_occluders = [
        item for item in compiled["occluders"]
        if item["source_entity_type"] == "obstacle"
    ]

    module_receiver_count = sum(
        item["source_entity_type"] == "module_instance"
        for item in compiled["receivers"]
    )
    assert len(module_occluders) == module_receiver_count
    assert {item["source_entity_id"] for item in obstacle_occluders} == {
        "ahu-a", "ahu-b"
    }

    for item in module_occluders:
        assert len(item["faces"]) == 1
        assert item["metadata"]["self_shading_controlled_by_configuration"] is True

    for item in obstacle_occluders:
        assert len(item["faces"]) == 6
        for face in item["faces"]:
            norm = math.sqrt(sum(value * value for value in face["normal_xyz"]))
            assert norm == pytest.approx(1.0)


def test_phase51_explicit_surface_receiver_compiles_without_becoming_occluder():
    compiled = compile_shading_geometry(_scene())
    surface_receivers = [
        item for item in compiled["receivers"]
        if item["source_entity_type"] == "surface"
    ]
    assert len(surface_receivers) == 1
    assert surface_receivers[0]["source_entity_id"] == "roof"
    assert surface_receivers[0]["receiver_type"] == "aggregate_plane"
    assert surface_receivers[0]["area_m2"] == pytest.approx(96.0)
    assert not any(
        item["source_entity_type"] == "surface"
        for item in compiled["occluders"]
    )


def test_phase51_same_scene_and_json_roundtrip_are_byte_deterministic():
    scene = _scene()
    first = compile_shading_geometry(scene)
    second = compile_shading_geometry(scene)
    reopened = json.loads(
        json.dumps(scene, sort_keys=True, separators=(",", ":"), allow_nan=False)
    )
    third = compile_shading_geometry(reopened)

    assert first == second == third
    assert (
        canonical_compiled_shading_geometry_hash(first)
        == canonical_compiled_shading_geometry_hash(second)
        == canonical_compiled_shading_geometry_hash(third)
    )


def test_phase51_geometry_payload_order_is_stable_even_if_source_collections_reorder():
    scene = _scene()
    first = compile_shading_geometry(scene)

    reordered = json.loads(json.dumps(scene))
    reordered["obstacles"] = list(reversed(reordered["obstacles"]))
    reordered["module_instances"] = list(reversed(reordered["module_instances"]))
    second = compile_shading_geometry(reordered)

    assert first["source_scene_hash"] != second["source_scene_hash"]
    assert first["compilation_input_hash"] != second["compilation_input_hash"]
    assert first["geometry_payload_sha256"] == second["geometry_payload_sha256"]
    assert first["receivers"] == second["receivers"]
    assert first["occluders"] == second["occluders"]


def test_phase51_disabled_obstacle_stays_in_artifact_but_cannot_silently_shade():
    scene = _scene()
    target = next(item for item in scene["obstacles"] if item["obstacle_id"] == "ahu-a")
    target["shading_enabled"] = False
    compiled = compile_shading_geometry(scene)

    obstacle = next(
        item for item in compiled["occluders"]
        if item["source_entity_id"] == "ahu-a"
    )
    assert obstacle["shading_enabled"] is False


def test_phase51_imported_mesh_is_not_replaced_by_footprint_extrusion():
    scene = _scene()
    scene["obstacles"][0]["obstacle_type"] = "imported_mesh"
    compiled = compile_shading_geometry(scene)

    obstacle_id = scene["obstacles"][0]["obstacle_id"]
    assert not any(
        item["source_entity_type"] == "obstacle"
        and item["source_entity_id"] == obstacle_id
        for item in compiled["occluders"]
    )
    finding = next(
        item for item in compiled["findings"]
        if item["code"] == "obstacle_compile_failed"
        and item["entity_id"] == obstacle_id
    )
    assert finding["severity"] == "error"
    assert "requires mesh vertices and faces" in finding["message"]


def test_phase51_polygon_holes_fail_explicitly_instead_of_becoming_solid_geometry():
    scene = _scene()
    scene["obstacles"][0]["footprint"]["holes"] = [
        [[9.2, 5.2], [9.4, 5.2], [9.4, 5.4], [9.2, 5.4]]
    ]
    compiled = compile_shading_geometry(scene)

    obstacle_id = scene["obstacles"][0]["obstacle_id"]
    assert not any(
        item["source_entity_type"] == "obstacle"
        and item["source_entity_id"] == obstacle_id
        for item in compiled["occluders"]
    )
    assert any(
        item["code"] == "obstacle_compile_failed"
        and item["entity_id"] == obstacle_id
        and "holes" in item["message"]
        for item in compiled["findings"]
    )


def test_phase51_unresolved_module_is_reported_and_not_in_receiver_set():
    scene = _load("tests/fixtures/schema/scene.example.json")
    compiled = compile_shading_geometry(scene)

    assert not any(
        item["source_entity_type"] == "module_instance"
        and item["source_entity_id"] == "module-001"
        for item in compiled["receivers"]
    )
    assert any(
        item["code"] == "module_receiver_unresolved"
        and item["entity_id"] == "module-001"
        for item in compiled["findings"]
    )
    _validate(compiled)
