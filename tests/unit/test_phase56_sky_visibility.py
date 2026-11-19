import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from geometry.shading import (
    SKY_VISIBILITY_SOLVER_ID,
    SkyDomeResolution,
    calculate_sky_visibility,
    evaluate_sky_shading_snapshot,
    generate_horizon_patches,
    generate_sky_patches,
)


ROOT = Path(__file__).resolve().parents[2]
HASH = "b" * 64


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


def _receiver(receiver_id="receiver:module:m1", module_id="m1"):
    vertices = [
        [-1.0, -1.0, 0.0],
        [1.0, -1.0, 0.0],
        [1.0, 1.0, 0.0],
        [-1.0, 1.0, 0.0],
    ]
    return {
        "receiver_id": receiver_id,
        "source_entity_type": "module_instance",
        "source_entity_id": module_id,
        "receiver_type": "module_plane",
        "vertices_3d": vertices,
        "center_xyz": [0.0, 0.0, 0.0],
        "normal_xyz": [0.0, 0.0, 1.0],
        "area_m2": 4.0,
        "enabled": True,
        "pv_field_id": "field-1",
        "support_surface_id": "surface-1",
        "module_instance_id": module_id,
        "metadata": {},
    }


def _plane_occluder(
    occluder_id="occ",
    *,
    z=10.0,
    extent=1000.0,
    source_entity_type="obstacle",
    source_entity_id=None,
    shading_enabled=True,
):
    vertices = [
        [-extent, -extent, z],
        [extent, -extent, z],
        [extent, extent, z],
        [-extent, extent, z],
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
                "normal_xyz": [0.0, 0.0, 1.0],
            }
        ],
        "bounds_3d": {
            "min_xyz": [-extent, -extent, z],
            "max_xyz": [extent, extent, z],
        },
        "shading_enabled": shading_enabled,
        "metadata": {},
    }


def _compiled(occluders=()):
    return {
        "source_scene_revision_id": "scene-r1",
        "geometry_payload_sha256": HASH,
        "receivers": [_receiver()],
        "occluders": list(occluders),
    }


def _resolution():
    return SkyDomeResolution(
        azimuth_sectors=8,
        elevation_bands=4,
        horizon_azimuth_sectors=8,
        horizon_elevation_bands=2,
        horizon_band_elevation_deg=15.0,
    )


def _configuration(*, self_shading_enabled=False):
    return {
        "beam_method": "opensimpv.beam_shadow.polygon_projection",
        "diffuse_method": SKY_VISIBILITY_SOLVER_ID,
        "albedo_method": "none",
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
        "model_options": {},
    }


def test_phase56_equal_solid_angle_dome_has_exact_total_solid_angle():
    resolution = _resolution()
    sky = generate_sky_patches(resolution)
    horizon = generate_horizon_patches(resolution)

    assert sum(item.solid_angle_sr for item in sky) == pytest.approx(
        2.0 * math.pi,
        rel=0.0,
        abs=1e-14,
    )
    assert sum(item.solid_angle_sr for item in horizon) == pytest.approx(
        2.0 * math.pi * math.sin(math.radians(15.0)),
        rel=0.0,
        abs=1e-14,
    )


def test_phase56_open_horizontal_receiver_is_exactly_clear_and_has_pi_weight():
    result = calculate_sky_visibility(
        _compiled(),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    _validate("geometry/shading/sky-visibility-query-result.schema.json", result)

    assert result["solver_id"] == SKY_VISIBILITY_SOLVER_ID
    assert result["sky_visibility_factor"] == 1.0
    assert result["horizon_visibility_factor"] == 1.0
    assert result["participating_occluder_count"] == 0
    assert result["evaluation_count"] == 0
    assert result["sky_front_weight_sum_sr"] == pytest.approx(
        math.pi,
        rel=0.0,
        abs=1e-14,
    )
    mu = math.sin(math.radians(15.0))
    assert result["horizon_front_weight_sum_sr"] == pytest.approx(
        math.pi * mu * mu,
        rel=0.0,
        abs=1e-14,
    )


def test_phase56_large_overhead_plane_blocks_every_discrete_sky_patch():
    result = calculate_sky_visibility(
        _compiled([_plane_occluder()]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    assert result["sky_visibility_factor"] == pytest.approx(0.0, abs=1e-12)
    assert result["horizon_visibility_factor"] == pytest.approx(0.0, abs=1e-12)
    assert result["evaluation_count"] > 0


def test_phase56_disabled_occluder_is_ignored():
    result = calculate_sky_visibility(
        _compiled([_plane_occluder(shading_enabled=False)]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    assert result["sky_visibility_factor"] == 1.0
    assert result["horizon_visibility_factor"] == 1.0
    assert result["participating_occluder_count"] == 0


def test_phase56_module_occluder_obeys_self_shading_switch():
    module = _plane_occluder(
        "occluder:module:m2",
        source_entity_type="module_instance",
        source_entity_id="m2",
    )
    disabled = calculate_sky_visibility(
        _compiled([module]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    enabled = calculate_sky_visibility(
        _compiled([module]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=True,
        resolution=_resolution(),
    )
    assert disabled["sky_visibility_factor"] == 1.0
    assert enabled["sky_visibility_factor"] == pytest.approx(0.0, abs=1e-12)


def test_phase56_receiver_never_self_occludes():
    own = _plane_occluder(
        "occluder:module:m1",
        source_entity_type="module_instance",
        source_entity_id="m1",
    )
    result = calculate_sky_visibility(
        _compiled([own]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=True,
        resolution=_resolution(),
    )
    assert result["sky_visibility_factor"] == 1.0
    assert result["participating_occluder_count"] == 0


def test_phase56_weighted_half_azimuth_mask_is_exactly_half(monkeypatch):
    dummy = _plane_occluder("dummy", z=100.0, extent=1.0)
    compiled = _compiled([dummy])

    def fake_beam(
        compiled_geometry,
        *,
        receiver_id,
        sun_vector_xyz,
        self_shading_enabled,
        **kwargs,
    ):
        # East half of the sky is blocked, west half is clear.
        visibility = 0.0 if float(sun_vector_xyz[0]) > 0.0 else 1.0
        return {"beam_visibility_factor": visibility}

    monkeypatch.setattr(
        "geometry.shading.sky.calculate_direct_beam_shadow",
        fake_beam,
    )
    result = calculate_sky_visibility(
        compiled,
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    assert result["sky_visibility_factor"] == pytest.approx(0.5, abs=1e-14)
    assert result["horizon_visibility_factor"] == pytest.approx(0.5, abs=1e-14)


def test_phase56_sky_snapshot_populates_existing_shading_result_contract():
    snapshot = evaluate_sky_shading_snapshot(
        _compiled(),
        shading_configuration=_configuration(),
        receiver_ids=["receiver:module:m1"],
    ).shading_result

    _validate("geometry/shading/shading-result.schema.json", snapshot)
    assert snapshot["channels"] == [
        "sky_visibility",
        "directional_diffuse_visibility",
    ]
    assert snapshot["record_count"] == 1
    record = snapshot["inline_records"][0]
    assert record["beam_visibility_factor"] is None
    assert record["sky_visibility_factor"] == 1.0
    assert record["ground_visibility_factor"] is None
    assert record["directional_diffuse_visibility"]["horizon"] == 1.0
    assert "sky_clear" in record["quality_flags"]
    assert snapshot["solver_manifest"]["sky_diffuse"]["model_id"] == (
        SKY_VISIBILITY_SOLVER_ID
    )


def test_phase56_sky_result_is_deterministic_under_occluder_reorder():
    first = _plane_occluder("a", z=5.0, extent=2.0)
    second = _plane_occluder("b", z=10.0, extent=3.0)
    one = calculate_sky_visibility(
        _compiled([first, second]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    two = calculate_sky_visibility(
        _compiled([second, first]),
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=_resolution(),
    )
    assert one == two
