import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from geometry.pvfield import (
    ModuleFootprint,
    PACKING_GEOMETRY_BASIS,
    PVFieldPackingSession,
)
from geometry.pvfield.geometry import rectangle_polygon
from geometry.scene import SceneEditorSession, canonical_scene_hash
from geometry.scene.surface_plane import SurfacePlane, module_center_z
from geometry.scene3d import generate_scene3d


ROOT = Path(__file__).resolve().parents[2]

MODULE = {
    "schema_name": "ModuleDefinition",
    "schema_version": "0.1",
    "module_definition_id": "mod-47hc",
    "revision_id": "mod-47hc-r1",
    "manufacturer": "OpenSIMPV Test",
    "model": "GEOMETRY-1x2",
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


def _roof_scene(*, slope_deg=0.0, azimuth_deg=180.0):
    editor = SceneEditorSession(_base_scene())
    editor.draw_polygon(
        surface_id="roof",
        scene_object_id="obj-roof",
        name="Geometry roof",
        surface_type="pitched_roof" if slope_deg else "flat_roof",
        vertices=[
            (0.0, 0.0),
            (10.0, 0.0),
            (10.0, 10.0),
            (0.0, 10.0),
        ],
        base_elevation_m=10.0,
        slope_deg=slope_deg,
        azimuth_deg=azimuth_deg,
        usable_for_pv=True,
        geometry_source="field_measurement",
    )
    return editor.scene


def _packed_scene(*, roof_slope=0.0, field_tilt=60.0, mounting_height=0.3):
    session = PVFieldPackingSession(
        _roof_scene(slope_deg=roof_slope),
        {MODULE["revision_id"]: MODULE},
    )
    session.create_field(
        pv_field_id="field-1",
        name="Field 1",
        support_surface_id="roof",
        module_definition_revision_id=MODULE["revision_id"],
        orientation="portrait",
        azimuth_deg=180.0,
        tilt_deg=field_tilt,
        module_gap_x_m=0.0,
        module_gap_y_m=0.0,
        row_pitch_m=max(0.25, 2.0 * math.cos(math.radians(field_tilt))),
        mounting_height_m=mounting_height,
        requested_row_count=1,
        requested_modules_per_row=1,
    )
    session.fill_area("field-1")
    return session.scene


def _field(scene):
    return next(item for item in scene["pv_fields"] if item["pv_field_id"] == "field-1")


def _module(scene):
    return next(item for item in scene["module_instances"] if item["pv_field_id"] == "field-1")


def _rounded_xy(points):
    return sorted((round(float(x), 9), round(float(y), 9)) for x, y in points)


def test_module_footprint_separates_physical_plane_from_horizontal_projection():
    footprint = ModuleFootprint.from_definition(
        MODULE, "portrait", 60.0
    )

    assert footprint.packed_width_m == pytest.approx(1.0)
    assert footprint.packed_height_m == pytest.approx(2.0)
    assert footprint.plan_projection_width_m == pytest.approx(1.0)
    assert footprint.plan_projection_height_m == pytest.approx(1.0)

    stored = footprint.to_mapping()
    assert stored["packing_basis"] == PACKING_GEOMETRY_BASIS
    assert stored["packed_height_m"] == pytest.approx(2.0)
    assert stored["plan_projection_height_m"] == pytest.approx(1.0)


def test_legacy_phase43_footprint_migrates_to_horizontal_projection():
    legacy = {
        "source_revision_id": MODULE["revision_id"],
        "physical_width_m": 1.0,
        "physical_height_m": 2.0,
        "orientation": "portrait",
        "packed_width_m": 1.0,
        "packed_height_m": 2.0,
        "packing_basis": "support_surface_2d",
    }
    footprint = ModuleFootprint.from_mapping(
        legacy, fallback_tilt_deg=60.0
    )
    assert footprint.plan_projection_width_m == pytest.approx(1.0)
    assert footprint.plan_projection_height_m == pytest.approx(1.0)


def test_2d_packing_polygon_equals_horizontal_projection_of_physical_3d_module():
    scene = _packed_scene(field_tilt=60.0)
    field = _field(scene)
    module = _module(scene)
    footprint = field["module_footprint"]

    center = (
        module["transform"]["position_x_m"],
        module["transform"]["position_y_m"],
    )
    packed_polygon = rectangle_polygon(
        center,
        footprint["plan_projection_width_m"],
        footprint["plan_projection_height_m"],
        module["transform"]["rotation_z_deg"],
    )

    generated = generate_scene3d(scene)
    geometry = generated["modules"][0]
    projected_3d = [
        (point[0], point[1])
        for point in geometry["corners_3d"]
    ]

    assert geometry["plane_width_m"] == pytest.approx(1.0)
    assert geometry["plane_height_m"] == pytest.approx(2.0)
    assert geometry["plan_projection_width_m"] == pytest.approx(1.0)
    assert geometry["plan_projection_height_m"] == pytest.approx(1.0)
    assert _rounded_xy(projected_3d) == _rounded_xy(packed_polygon)


def test_pitched_roof_packing_writes_canonical_module_center_z():
    scene = _packed_scene(
        roof_slope=10.0,
        field_tilt=10.0,
        mounting_height=0.25,
    )
    field = _field(scene)
    module = _module(scene)
    support = next(
        item for item in scene["surfaces"] if item["surface_id"] == "roof"
    )
    x = module["transform"]["position_x_m"]
    y = module["transform"]["position_y_m"]
    expected = module_center_z(
        support, x, y, field["mounting_height_m"]
    )

    assert module["transform"]["position_z_m"] == pytest.approx(expected)
    assert module["metadata"]["position_z_basis"] == (
        "support_plane_plus_vertical_mounting_height"
    )
    # The packed module is intentionally away from the support reference
    # centroid, so the old base_elevation+mounting shortcut would be wrong.
    assert module["transform"]["position_z_m"] != pytest.approx(
        support["base_elevation_m"] + field["mounting_height_m"]
    )

    generated = generate_scene3d(scene)
    geometry = generated["modules"][0]
    assert geometry["center_xyz"][2] == pytest.approx(expected)
    assert geometry["expected_center_z_m"] == pytest.approx(expected)
    assert geometry["center_z_residual_m"] == pytest.approx(0.0)
    assert "module_center_z_inconsistent" not in {
        item["code"] for item in generated["findings"]
    }


def test_manual_module_move_on_pitched_roof_updates_canonical_z():
    scene = _packed_scene(
        roof_slope=12.0,
        field_tilt=12.0,
        mounting_height=0.2,
    )
    module_id = _module(scene)["module_instance_id"]
    session = PVFieldPackingSession(
        scene, {MODULE["revision_id"]: MODULE}
    )

    session.move_module(
        module_id,
        target_x_m=5.0,
        target_y_m=7.0,
    )
    moved = _module(session.scene)
    field = _field(session.scene)
    support = next(
        item
        for item in session.scene["surfaces"]
        if item["surface_id"] == "roof"
    )

    assert moved["module_instance_id"] == module_id
    assert moved["transform"]["position_z_m"] == pytest.approx(
        module_center_z(
            support,
            5.0,
            7.0,
            field["mounting_height_m"],
        )
    )


def test_support_vertex_edit_resynchronizes_module_z_without_replacing_identity():
    scene = _packed_scene(
        roof_slope=10.0,
        field_tilt=10.0,
        mounting_height=0.2,
    )
    module_before = deepcopy(_module(scene))
    old_z = module_before["transform"]["position_z_m"]

    editor = SceneEditorSession(scene)
    editor.move_vertex(
        "roof",
        vertex_index=2,
        target_x_m=12.0,
        target_y_m=10.0,
    )

    updated = editor.scene
    module_after = _module(updated)
    field = _field(updated)
    support = next(
        item for item in updated["surfaces"] if item["surface_id"] == "roof"
    )

    assert module_after["module_instance_id"] == module_before["module_instance_id"]
    assert module_after["transform"]["position_z_m"] != pytest.approx(old_z)
    assert module_after["transform"]["position_z_m"] == pytest.approx(
        module_center_z(
            support,
            module_after["transform"]["position_x_m"],
            module_after["transform"]["position_y_m"],
            field["mounting_height_m"],
        )
    )

    report = PVFieldPackingSession(
        updated, {MODULE["revision_id"]: MODULE}
    ).conflict_report("field-1")
    assert "packing_inputs_changed" in {
        item["code"] for item in report["conflicts"]
    }


def test_stale_canonical_z_is_reported_not_silently_reinterpreted():
    scene = _packed_scene(
        roof_slope=10.0,
        field_tilt=10.0,
        mounting_height=0.2,
    )
    module = _module(scene)
    module["transform"]["position_z_m"] += 1.0

    generated = generate_scene3d(scene)
    geometry = generated["modules"][0]
    codes = {item["code"] for item in generated["findings"]}

    assert "module_center_z_inconsistent" in codes
    assert geometry["center_z_residual_m"] == pytest.approx(1.0)
    # Derived 3-D respects canonical Scene Z and reports the inconsistency.
    assert geometry["center_xyz"][2] == pytest.approx(
        module["transform"]["position_z_m"]
    )


def test_geometry_coherence_roundtrip_preserves_canonical_hash():
    scene = _packed_scene(
        roof_slope=8.0,
        field_tilt=20.0,
        mounting_height=0.25,
    )
    encoded = json.dumps(scene, sort_keys=True, separators=(",", ":"))
    reloaded = json.loads(encoded)
    assert canonical_scene_hash(reloaded) == canonical_scene_hash(scene)

    generated = generate_scene3d(reloaded)
    assert all(
        item["code"] != "module_center_z_inconsistent"
        for item in generated["findings"]
    )
