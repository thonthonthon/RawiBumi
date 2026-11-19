import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from geometry.pvfield import PVFieldPackingSession
from geometry.scene import SceneEditorSession, canonical_scene_hash
from geometry.scene3d import (
    SurfacePlane,
    canonical_scene3d_hash,
    canonical_scene3d_json,
    distance3d,
    generate_scene3d,
)


ROOT = Path(__file__).resolve().parents[2]

MODULE = {
    "schema_name": "ModuleDefinition",
    "schema_version": "0.1",
    "module_definition_id": "mod-height-ref",
    "revision_id": "mod-height-ref-r1",
    "manufacturer": "OpenSIMPV Test",
    "model": "HEIGHT-1x2",
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


def _registry():
    registry = Registry()
    directories = (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "geometry/scene3d",
        ROOT / "electrical/schema",
        ROOT / "apps/web/schema",
    )
    for directory in directories:
        for path in directory.glob("*.schema.json"):
            schema = _load(str(path.relative_to(ROOT)))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def _flat_roof_scene(*, elevation=8.0):
    editor = SceneEditorSession(_base_scene())
    editor.draw_rectangle(
        surface_id="roof",
        scene_object_id="obj-roof",
        name="Flat roof",
        surface_type="flat_roof",
        origin_x_m=0.0,
        origin_y_m=0.0,
        width_m=10.0,
        height_m=8.0,
        base_elevation_m=elevation,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    return editor.scene


def _pitched_roof_scene(
    *,
    base_elevation=10.0,
    slope_deg=10.0,
    azimuth_deg=180.0,
):
    editor = SceneEditorSession(_base_scene())
    editor.draw_polygon(
        surface_id="roof",
        scene_object_id="obj-roof",
        name="Pitched roof",
        surface_type="pitched_roof",
        vertices=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        base_elevation_m=base_elevation,
        slope_deg=slope_deg,
        azimuth_deg=azimuth_deg,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    return editor.scene


def _packed_one_module(
    scene,
    *,
    field_azimuth=180.0,
    field_tilt=10.0,
    mounting_height=0.2,
):
    packing = PVFieldPackingSession(
        scene, {MODULE["revision_id"]: MODULE}
    )
    packing.create_field(
        pv_field_id="field-1",
        name="Field 1",
        support_surface_id="roof",
        module_definition_revision_id=MODULE["revision_id"],
        orientation="portrait",
        azimuth_deg=field_azimuth,
        tilt_deg=field_tilt,
        module_gap_x_m=0.0,
        module_gap_y_m=0.0,
        row_pitch_m=2.0,
        mounting_height_m=mounting_height,
        perimeter_setback_m=0.0,
        requested_row_count=1,
        requested_modules_per_row=1,
    )
    packing.fill_area("field-1")
    return packing.scene


def _surface(scene3d, surface_id):
    return next(
        item for item in scene3d["surfaces"]
        if item["surface_id"] == surface_id
    )


def _module(scene3d, module_id=None):
    modules = scene3d["modules"]
    if module_id is None:
        return modules[0]
    return next(
        item for item in modules
        if item["module_instance_id"] == module_id
    )


def test_flat_surface_lifts_to_constant_elevation_and_up_normal():
    scene3d = generate_scene3d(_flat_roof_scene(elevation=8.0))
    roof = _surface(scene3d, "roof")

    assert roof["status"] == "resolved"
    assert all(
        point[2] == pytest.approx(8.0)
        for point in roof["boundary_vertices_3d"]
    )
    assert roof["plane"]["reference_point_xy_m"] == pytest.approx([5.0, 4.0])
    assert roof["plane"]["reference_elevation_m"] == pytest.approx(8.0)
    assert roof["plane"]["normal_xyz"] == pytest.approx([0.0, 0.0, 1.0])


def test_pitched_surface_uses_centroid_datum_and_downhill_azimuth():
    scene = _pitched_roof_scene(
        base_elevation=10.0,
        slope_deg=10.0,
        azimuth_deg=180.0,
    )
    plane = SurfacePlane.from_surface(scene["surfaces"][0])

    delta = math.tan(math.radians(10.0)) * 5.0
    assert plane.elevation_at(5.0, 5.0) == pytest.approx(10.0)
    assert plane.elevation_at(5.0, 0.0) == pytest.approx(10.0 - delta)
    assert plane.elevation_at(5.0, 10.0) == pytest.approx(10.0 + delta)
    assert plane.normal_xyz == pytest.approx(
        (0.0, -math.sin(math.radians(10.0)), math.cos(math.radians(10.0))),
        abs=1e-12,
    )

    generated = generate_scene3d(scene)
    roof = _surface(generated, "roof")
    assert min(p[2] for p in roof["boundary_vertices_3d"]) == pytest.approx(
        10.0 - delta
    )
    assert max(p[2] for p in roof["boundary_vertices_3d"]) == pytest.approx(
        10.0 + delta
    )


def test_explicit_elevation_reference_overrides_default_centroid_datum():
    scene = _pitched_roof_scene(
        base_elevation=10.0,
        slope_deg=10.0,
        azimuth_deg=180.0,
    )
    scene["surfaces"][0]["elevation_reference"] = {
        "mode": "explicit_xy",
        "x_m": 0.0,
        "y_m": 0.0,
    }

    plane = SurfacePlane.from_surface(scene["surfaces"][0])
    assert plane.elevation_reference_mode == "explicit_xy"
    assert plane.elevation_at(0.0, 0.0) == pytest.approx(10.0)

    generated = generate_scene3d(scene)
    roof = _surface(generated, "roof")
    assert roof["plane"]["elevation_reference_mode"] == "explicit_xy"
    assert roof["plane"]["reference_point_xy_m"] == pytest.approx([0.0, 0.0])


def test_obstacle_and_parapet_are_vertical_extrusions_from_canonical_height():
    editor = SceneEditorSession(_flat_roof_scene())
    editor.draw_box_obstacle(
        obstacle_id="ahu",
        scene_object_id="obj-ahu",
        name="AHU",
        origin_x_m=2.0,
        origin_y_m=2.0,
        width_m=1.0,
        depth_m=2.0,
        base_elevation_m=8.0,
        height_m=1.5,
    )
    editor.draw_wall_obstacle(
        obstacle_id="parapet",
        scene_object_id="obj-parapet",
        name="Parapet",
        start=(0.0, 0.0),
        end=(10.0, 0.0),
        width_m=0.2,
        base_elevation_m=8.0,
        height_m=0.8,
        parapet=True,
    )

    generated = generate_scene3d(editor.scene)
    by_id = {
        item["obstacle_id"]: item
        for item in generated["obstacles"]
    }
    assert all(
        point[2] == pytest.approx(8.0)
        for point in by_id["ahu"]["base_vertices_3d"]
    )
    assert all(
        point[2] == pytest.approx(9.5)
        for point in by_id["ahu"]["top_vertices_3d"]
    )
    assert all(
        point[2] == pytest.approx(8.8)
        for point in by_id["parapet"]["top_vertices_3d"]
    )


def test_flush_module_on_matching_pitched_roof_preserves_physical_dimensions():
    scene = _packed_one_module(
        _pitched_roof_scene(
            base_elevation=10.0,
            slope_deg=10.0,
            azimuth_deg=180.0,
        ),
        field_azimuth=180.0,
        field_tilt=10.0,
        mounting_height=0.2,
    )
    generated = generate_scene3d(scene)
    module = _module(generated)

    assert module["status"] == "resolved"
    assert module["physical_width_m"] == pytest.approx(1.0)
    assert module["physical_height_m"] == pytest.approx(2.0)
    assert distance3d(
        tuple(module["corners_3d"][0]),
        tuple(module["corners_3d"][1]),
    ) == pytest.approx(1.0)
    assert distance3d(
        tuple(module["corners_3d"][1]),
        tuple(module["corners_3d"][2]),
    ) == pytest.approx(2.0)
    assert module["minimum_support_clearance_m"] == pytest.approx(0.2)
    assert module["maximum_support_clearance_m"] == pytest.approx(0.2)

    roof_normal = _surface(generated, "roof")["plane"]["normal_xyz"]
    assert module["normal_xyz"] == pytest.approx(roof_normal)


def test_tilted_module_with_insufficient_mounting_height_reports_penetration():
    scene = _packed_one_module(
        _flat_roof_scene(elevation=8.0),
        field_azimuth=180.0,
        field_tilt=20.0,
        mounting_height=0.1,
    )
    generated = generate_scene3d(scene)
    module = _module(generated)

    assert module["minimum_support_clearance_m"] < 0.0
    codes = {item["code"] for item in generated["findings"]}
    assert "module_intersects_support_plane" in codes


def test_generated_3d_is_non_editable_derived_and_deterministic():
    scene = _packed_one_module(_flat_roof_scene())
    source_hash_before = canonical_scene_hash(scene)

    first = generate_scene3d(scene)
    second = generate_scene3d(scene)

    assert canonical_scene_hash(scene) == source_hash_before
    assert first["authority"] == "derived_verification_only"
    assert first["editable"] is False
    assert first["mesh_editing_supported"] is False
    assert first["source_scene_hash"] == source_hash_before
    assert first["generation_input_hash"] == second["generation_input_hash"]
    assert canonical_scene3d_json(first) == canonical_scene3d_json(second)
    assert canonical_scene3d_hash(first) == canonical_scene3d_hash(second)


def test_existing_manual_scene_without_stored_footprint_remains_deterministic():
    scene = _load("tests/fixtures/schema/scene.example.json")
    generated = generate_scene3d(scene)

    module = _module(generated, "module-001")
    assert module["status"] == "unresolved"
    assert module["corners_3d"] == []
    assert any(
        item["code"] == "module_geometry_unresolved"
        and item["entity_id"] == "module-001"
        for item in generated["findings"]
    )

    schema = _load("geometry/scene3d/generated-scene3d.schema.json")
    Draft202012Validator(schema, registry=_registry()).validate(generated)


def test_generated_scene3d_schema_and_bounds_are_stable():
    scene = _packed_one_module(_flat_roof_scene())
    generated = generate_scene3d(scene)

    schema = _load("geometry/scene3d/generated-scene3d.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, registry=_registry()).validate(generated)

    assert generated["bounds_3d"] is not None
    assert generated["bounds_3d"]["min_xyz"][0] <= 0.0
    assert generated["bounds_3d"]["max_xyz"][0] >= 10.0
    assert generated["finding_count"] == len(generated["findings"])


def test_scene_schema_rejects_vertical_surface_but_accepts_explicit_height_reference():
    schema = _load("geometry/scene/scene.schema.json")
    validator = Draft202012Validator(schema, registry=_registry())

    scene = _pitched_roof_scene(slope_deg=10.0)
    scene["surfaces"][0]["elevation_reference"] = {
        "mode": "explicit_xy",
        "x_m": 0.0,
        "y_m": 0.0,
    }
    validator.validate(scene)

    invalid = json.loads(json.dumps(scene))
    invalid["surfaces"][0]["slope_deg"] = 90.0
    with pytest.raises(Exception):
        validator.validate(invalid)


def test_generation_is_order_stable_for_entity_collections():
    editor = SceneEditorSession(_flat_roof_scene())
    editor.draw_box_obstacle(
        obstacle_id="b",
        scene_object_id="obj-b",
        name="B",
        origin_x_m=3.0,
        origin_y_m=3.0,
        width_m=1.0,
        depth_m=1.0,
        base_elevation_m=8.0,
        height_m=1.0,
    )
    editor.draw_box_obstacle(
        obstacle_id="a",
        scene_object_id="obj-a",
        name="A",
        origin_x_m=1.0,
        origin_y_m=1.0,
        width_m=1.0,
        depth_m=1.0,
        base_elevation_m=8.0,
        height_m=1.0,
    )
    scene = editor.scene
    first = generate_scene3d(scene)

    reordered = json.loads(json.dumps(scene))
    reordered["obstacles"] = list(reversed(reordered["obstacles"]))
    second = generate_scene3d(reordered)

    assert [item["obstacle_id"] for item in first["obstacles"]] == ["a", "b"]
    assert [item["obstacle_id"] for item in second["obstacles"]] == ["a", "b"]
