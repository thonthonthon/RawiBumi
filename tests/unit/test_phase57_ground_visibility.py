import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from geometry.shading import (
    GROUND_VISIBILITY_SOLVER_ID,
    GroundDomeResolution,
    calculate_directional_receiver_visibility,
    calculate_direct_beam_shadow,
    calculate_ground_visibility,
    evaluate_ground_shading_snapshot,
    generate_ground_patches,
)


ROOT = Path(__file__).resolve().parents[2]
HASH = "c" * 64


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


def _validate(path, value):
    schema = json.loads((ROOT / path).read_text(encoding="utf-8"))
    Draft202012Validator(schema, registry=_registry()).validate(value)


def _vertical_receiver(
    receiver_id="receiver:module:m1",
    module_id="m1",
):
    vertices = [
        [0.0, -1.0, -1.0],
        [0.0, 1.0, -1.0],
        [0.0, 1.0, 1.0],
        [0.0, -1.0, 1.0],
    ]
    return {
        "receiver_id": receiver_id,
        "source_entity_type": "module_instance",
        "source_entity_id": module_id,
        "receiver_type": "module_plane",
        "vertices_3d": vertices,
        "center_xyz": [0.0, 0.0, 0.0],
        "normal_xyz": [1.0, 0.0, 0.0],
        "area_m2": 4.0,
        "enabled": True,
        "pv_field_id": "field-1",
        "support_surface_id": "surface-1",
        "module_instance_id": module_id,
        "metadata": {},
    }


def _horizontal_receiver():
    receiver = _vertical_receiver()
    receiver["vertices_3d"] = [
        [-1.0, -1.0, 0.0],
        [1.0, -1.0, 0.0],
        [1.0, 1.0, 0.0],
        [-1.0, 1.0, 0.0],
    ]
    receiver["normal_xyz"] = [0.0, 0.0, 1.0]
    return receiver


def _plane_occluder(
    occluder_id="occ",
    *,
    x=1.0,
    extent=1000.0,
    source_entity_type="obstacle",
    source_entity_id=None,
    shading_enabled=True,
):
    vertices = [
        [x, -extent, -extent],
        [x, extent, -extent],
        [x, extent, extent],
        [x, -extent, extent],
    ]
    return {
        "occluder_id": occluder_id,
        "source_entity_type": source_entity_type,
        "source_entity_id": source_entity_id or occluder_id,
        "geometry_type": "polygon_faces",
        "faces": [
            {
                "face_id": f"{occluder_id}:face",
                "vertices_3d": vertices,
                "normal_xyz": [1.0, 0.0, 0.0],
            }
        ],
        "bounds_3d": {
            "min_xyz": [x, -extent, -extent],
            "max_xyz": [x, extent, extent],
        },
        "shading_enabled": shading_enabled,
        "metadata": {},
    }


def _compiled(*, receiver=None, occluders=()):
    return {
        "source_scene_revision_id": "scene-r1",
        "geometry_payload_sha256": HASH,
        "receivers": [receiver or _vertical_receiver()],
        "occluders": list(occluders),
    }


def _resolution(azimuth=16, depression=8):
    return GroundDomeResolution(
        azimuth_sectors=azimuth,
        depression_bands=depression,
    )


def _configuration(*, self_shading_enabled=False):
    return {
        "beam_method": "opensimpv.beam_shadow.polygon_projection",
        "diffuse_method": "opensimpv.sky_visibility.weighted_dome",
        "albedo_method": GROUND_VISIBILITY_SOLVER_ID,
        "fidelity_level": "engineering",
        "sun_position_resolution_seconds": None,
        "electrical_shading_method": None,
        "geometry_contract_version": "0.1",
        "coordinate_basis": "scene_local_east_north_up_m",
        "sun_vector_convention": "receiver_to_sun",
        "factor_convention": "visibility_one_clear_zero_blocked",
        "receiver_granularity": "module",
        "self_shading_enabled": self_shading_enabled,
        "cache_policy": {"mode": "exact"},
        "geometric_resolution": {
            "receiver_subdivision_u": 1,
            "receiver_subdivision_v": 1,
        },
        "sky_dome_resolution": {
            "azimuth_sectors": 8,
            "elevation_bands": 4,
            "horizon_azimuth_sectors": 8,
            "horizon_elevation_bands": 2,
            "horizon_band_elevation_deg": 15.0,
        },
        "ground_dome_resolution": {
            "azimuth_sectors": 16,
            "depression_bands": 8,
        },
        "model_options": {},
    }


def test_phase57_ground_dome_has_exact_lower_hemisphere_solid_angle():
    patches = generate_ground_patches(_resolution())
    assert sum(item.solid_angle_sr for item in patches) == pytest.approx(
        2.0 * math.pi,
        rel=0.0,
        abs=1e-14,
    )
    assert all(item.direction_xyz[2] < 0.0 for item in patches)


def test_phase57_horizontal_upward_receiver_has_zero_front_ground_view():
    result = calculate_ground_visibility(
        _compiled(receiver=_horizontal_receiver()),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    _validate("geometry/shading/ground-visibility-query-result.schema.json", result)
    assert result["has_front_ground_view"] is False
    assert result["ground_front_weight_sum_sr"] == 0.0
    assert result["ground_visible_weight_sum_sr"] == 0.0
    assert result["ground_visibility_factor"] == 1.0


def test_phase57_vertical_receiver_projected_ground_weight_converges_to_pi_over_two():
    result = calculate_ground_visibility(
        _compiled(),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(72, 40),
    )
    assert result["has_front_ground_view"] is True
    assert result["ground_front_weight_sum_sr"] == pytest.approx(
        math.pi / 2.0,
        rel=0.001,
    )
    assert result["ground_visibility_factor"] == 1.0
    assert result["evaluation_count"] == 0


def test_phase57_generic_directional_kernel_accepts_below_horizon_source_without_weakening_beam_api():
    compiled = _compiled(occluders=[_plane_occluder()])
    direction = (1.0, 0.0, -1.0)

    generic = calculate_directional_receiver_visibility(
        compiled,
        receiver_id="receiver:module:m1",
        source_direction_xyz=direction,
        self_shading_enabled=False,
    )
    beam = calculate_direct_beam_shadow(
        compiled,
        receiver_id="receiver:module:m1",
        sun_vector_xyz=direction,
        self_shading_enabled=False,
    )

    _validate(
        "geometry/shading/directional-visibility-query-result.schema.json",
        generic,
    )
    assert generic["status"] == "evaluated"
    assert generic["visibility_factor"] == pytest.approx(0.0, abs=1e-12)

    # Phase-5.3 solar semantics remain unchanged.
    assert beam["status"] == "no_direct_beam_sun_below_horizon"
    assert beam["beam_visibility_factor"] == 1.0


def test_phase57_large_front_plane_blocks_all_discrete_front_ground_view():
    result = calculate_ground_visibility(
        _compiled(occluders=[_plane_occluder()]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    assert result["ground_visibility_factor"] == pytest.approx(0.0, abs=1e-12)
    assert result["evaluation_count"] > 0


def test_phase57_disabled_occluder_is_ignored():
    result = calculate_ground_visibility(
        _compiled(occluders=[_plane_occluder(shading_enabled=False)]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    assert result["ground_visibility_factor"] == 1.0
    assert result["participating_occluder_count"] == 0
    assert result["evaluation_count"] == 0


def test_phase57_receiver_never_self_occludes():
    own = _plane_occluder(
        "occluder:module:m1",
        source_entity_type="module_instance",
        source_entity_id="m1",
    )
    result = calculate_ground_visibility(
        _compiled(occluders=[own]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=True,
        resolution=_resolution(),
    )
    assert result["ground_visibility_factor"] == 1.0
    assert result["participating_occluder_count"] == 0


def test_phase57_other_module_ground_occlusion_obeys_self_shading_switch():
    other = _plane_occluder(
        "occluder:module:m2",
        source_entity_type="module_instance",
        source_entity_id="m2",
    )
    disabled = calculate_ground_visibility(
        _compiled(occluders=[other]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    enabled = calculate_ground_visibility(
        _compiled(occluders=[other]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=True,
        resolution=_resolution(),
    )
    assert disabled["ground_visibility_factor"] == 1.0
    assert enabled["ground_visibility_factor"] == pytest.approx(0.0, abs=1e-12)


def test_phase57_symmetric_half_ground_mask_is_half_visible(monkeypatch):
    compiled = _compiled(occluders=[_plane_occluder("dummy", extent=1.0)])

    def fake_directional(
        compiled_geometry,
        *,
        receiver_id,
        source_direction_xyz,
        self_shading_enabled,
        **kwargs,
    ):
        # Split by north/south. Weighting is symmetric in y for the x-facing
        # receiver, so exactly one half of the front lower hemisphere is clear.
        visibility = 0.0 if float(source_direction_xyz[1]) > 0.0 else 1.0
        return {"visibility_factor": visibility}

    monkeypatch.setattr(
        "geometry.shading.ground.calculate_directional_receiver_visibility",
        fake_directional,
    )
    result = calculate_ground_visibility(
        compiled,
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    assert result["ground_visibility_factor"] == pytest.approx(0.5, abs=1e-14)


def test_phase57_ground_result_is_deterministic_under_occluder_reorder():
    first = _plane_occluder("a", x=1.0, extent=2.0)
    second = _plane_occluder("b", x=2.0, extent=3.0)
    one = calculate_ground_visibility(
        _compiled(occluders=[first, second]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    two = calculate_ground_visibility(
        _compiled(occluders=[second, first]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    assert one == two


def test_phase57_ground_snapshot_populates_existing_shading_result_contract():
    snapshot = evaluate_ground_shading_snapshot(
        _compiled(),
        shading_configuration=_configuration(),
        receiver_ids=["receiver:module:m1"],
    ).shading_result
    _validate("geometry/shading/shading-result.schema.json", snapshot)
    assert snapshot["channels"] == ["ground_visibility"]
    assert snapshot["record_count"] == 1
    record = snapshot["inline_records"][0]
    assert record["beam_visibility_factor"] is None
    assert record["sky_visibility_factor"] is None
    assert record["ground_visibility_factor"] == 1.0
    assert snapshot["solver_manifest"]["ground"]["model_id"] == (
        GROUND_VISIBILITY_SOLVER_ID
    )
