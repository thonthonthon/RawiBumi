import json
import math
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from geometry.shading import (
    BEAM_SOLVER_ID,
    ExactStaticShadingCache,
    GROUND_VISIBILITY_SOLVER_ID,
    GroundDomeResolution,
    SKY_VISIBILITY_SOLVER_ID,
    ShadingAccelerationError,
    SkyDomeResolution,
    build_shading_acceleration_context,
    calculate_directional_receiver_visibility,
    calculate_direct_beam_shadow,
    calculate_ground_visibility,
    calculate_prepared_directional_receiver_visibility,
    calculate_prepared_direct_beam_shadow,
    calculate_sky_visibility,
    prepare_directional_receiver,
)


ROOT = Path(__file__).resolve().parents[2]
HASH = "a" * 64
PLAN_HASH_1 = "e" * 64
PLAN_HASH_2 = "f" * 64


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
        if not directory.exists():
            continue
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def _validate_schema(path, value):
    schema = json.loads((ROOT / path).read_text(encoding="utf-8"))
    Draft202012Validator(schema, registry=_registry()).validate(value)


def _receiver(receiver_id="receiver:module:m1", module_id="m1"):
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


def _box_occluder(
    occluder_id="occ",
    *,
    x0=1.0,
    x1=2.0,
    y0=-0.5,
    y1=0.5,
    z0=-2.0,
    z1=2.0,
    source_entity_type="obstacle",
    source_entity_id=None,
    shading_enabled=True,
):
    source_id = source_entity_id or occluder_id
    faces = [
        (
            "west",
            [[x0, y0, z0], [x0, y1, z0], [x0, y1, z1], [x0, y0, z1]],
            [-1.0, 0.0, 0.0],
        ),
        (
            "east",
            [[x1, y0, z0], [x1, y0, z1], [x1, y1, z1], [x1, y1, z0]],
            [1.0, 0.0, 0.0],
        ),
        (
            "south",
            [[x0, y0, z0], [x0, y0, z1], [x1, y0, z1], [x1, y0, z0]],
            [0.0, -1.0, 0.0],
        ),
        (
            "north",
            [[x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]],
            [0.0, 1.0, 0.0],
        ),
        (
            "bottom",
            [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0]],
            [0.0, 0.0, -1.0],
        ),
        (
            "top",
            [[x0, y0, z1], [x0, y1, z1], [x1, y1, z1], [x1, y0, z1]],
            [0.0, 0.0, 1.0],
        ),
    ]
    return {
        "occluder_id": occluder_id,
        "source_entity_type": source_entity_type,
        "source_entity_id": source_id,
        "geometry_type": "polygon_faces",
        "faces": [
            {
                "face_id": f"{occluder_id}:{name}",
                "vertices_3d": vertices,
                "normal_xyz": normal,
            }
            for name, vertices, normal in faces
        ],
        "bounds_3d": {
            "min_xyz": [x0, y0, z0],
            "max_xyz": [x1, y1, z1],
        },
        "shading_enabled": shading_enabled,
        "metadata": {},
    }


def _compiled(*, receiver=None, occluders=(), geometry_hash=HASH):
    return {
        "source_scene_revision_id": "scene-phase58-r1",
        "geometry_payload_sha256": geometry_hash,
        "receivers": [receiver or _receiver()],
        "occluders": list(occluders),
    }


def _config(
    *,
    mode="exact",
    self_shading_enabled=False,
    sky_azimuth=12,
    ground_azimuth=12,
):
    return {
        "beam_method": BEAM_SOLVER_ID,
        "diffuse_method": SKY_VISIBILITY_SOLVER_ID,
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
        "cache_policy": {"mode": mode},
        "geometric_resolution": {
            "receiver_subdivision_u": 1,
            "receiver_subdivision_v": 1,
        },
        "model_options": {},
        "sky_dome_resolution": {
            "azimuth_sectors": sky_azimuth,
            "elevation_bands": 6,
            "horizon_azimuth_sectors": sky_azimuth,
            "horizon_elevation_bands": 2,
            "horizon_band_elevation_deg": 15.0,
        },
        "ground_dome_resolution": {
            "azimuth_sectors": ground_azimuth,
            "depression_bands": 6,
        },
    }


@pytest.mark.parametrize(
    "direction",
    [
        (1.0, 0.0, 1.0),
        (1.0, 0.2, 0.8),
        (1.0, -0.3, 0.25),
        (1.0, 0.0, -0.5),
        (-1.0, 0.0, 1.0),
    ],
)
def test_phase58_prepared_beam_matches_reference_result_exactly(direction):
    compiled = _compiled(occluders=[_box_occluder()])
    prepared = prepare_directional_receiver(
        compiled,
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
    )
    reference = calculate_direct_beam_shadow(
        compiled,
        receiver_id="receiver:module:m1",
        sun_vector_xyz=direction,
        self_shading_enabled=False,
    )
    accelerated = calculate_prepared_direct_beam_shadow(
        prepared,
        sun_vector_xyz=direction,
    )
    assert accelerated == reference


@pytest.mark.parametrize(
    "direction",
    [
        (1.0, 0.0, 1.0),
        (1.0, 0.2, 0.4),
        (1.0, -0.3, -0.7),
        (-1.0, 0.0, -0.5),
    ],
)
def test_phase58_prepared_generic_directional_matches_reference_exactly(direction):
    compiled = _compiled(occluders=[_box_occluder()])
    prepared = prepare_directional_receiver(
        compiled,
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
    )
    reference = calculate_directional_receiver_visibility(
        compiled,
        receiver_id="receiver:module:m1",
        source_direction_xyz=direction,
        self_shading_enabled=False,
    )
    accelerated = calculate_prepared_directional_receiver_visibility(
        prepared,
        source_direction_xyz=direction,
    )
    assert accelerated == reference


def test_phase58_prepared_sky_matches_reference_query_exactly():
    compiled = _compiled(occluders=[_box_occluder()])
    resolution = SkyDomeResolution(
        azimuth_sectors=12,
        elevation_bands=6,
        horizon_azimuth_sectors=12,
        horizon_elevation_bands=2,
        horizon_band_elevation_deg=15.0,
    )
    prepared = prepare_directional_receiver(
        compiled,
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
    )
    reference = calculate_sky_visibility(
        compiled,
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=resolution,
    )
    accelerated = calculate_sky_visibility(
        compiled,
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=resolution,
        prepared_query=prepared,
    )
    assert accelerated == reference


def test_phase58_prepared_ground_matches_reference_query_exactly():
    compiled = _compiled(occluders=[_box_occluder()])
    resolution = GroundDomeResolution(
        azimuth_sectors=12,
        depression_bands=6,
    )
    prepared = prepare_directional_receiver(
        compiled,
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
    )
    reference = calculate_ground_visibility(
        compiled,
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=resolution,
    )
    accelerated = calculate_ground_visibility(
        compiled,
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
        resolution=resolution,
        prepared_query=prepared,
    )
    assert accelerated == reference


def test_phase58_prepared_query_preserves_occluder_order_independence():
    a = _box_occluder("a", x0=1.0, x1=1.5, y0=-0.8, y1=-0.1)
    b = _box_occluder("b", x0=2.0, x1=2.5, y0=0.1, y1=0.8)
    first = _compiled(occluders=[a, b])
    second = _compiled(occluders=[b, a])
    p1 = prepare_directional_receiver(
        first,
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
    )
    p2 = prepare_directional_receiver(
        second,
        receiver_id="receiver:module:m1",
        self_shading_enabled=False,
    )
    one = calculate_prepared_direct_beam_shadow(
        p1, sun_vector_xyz=(1.0, 0.1, 0.5)
    )
    two = calculate_prepared_direct_beam_shadow(
        p2, sun_vector_xyz=(1.0, 0.1, 0.5)
    )
    assert one == two


def _make_static_result(context, channel, result_hash="b" * 64):
    return {
        "source_scene_revision_id": context.source_scene_revision_id,
        "compiled_geometry_hash": context.compiled_geometry_hash,
        "shading_configuration_hash": context.shading_configuration_hash,
        "receiver_set_sha256": context.receiver_set_sha256,
        "result_payload_sha256": result_hash,
        "source_execution_plan_id": context.source_execution_plan_id,
        "channels": (
            ["sky_visibility", "directional_diffuse_visibility"]
            if channel == "sky_visibility"
            else [channel]
        ),
        "storage_mode": "inline",
        "record_count": 1,
        "inline_records": [{"receiver_id": "receiver:module:m1"}],
    }


def test_phase58_static_cache_cold_then_warm_and_manifest_schema():
    store = ExactStaticShadingCache(max_entries=8)
    context = build_shading_acceleration_context(
        _compiled(),
        shading_configuration=_config(),
        receiver_ids=["receiver:module:m1"],
        source_execution_plan_id="plan-1",
        source_execution_plan_payload_sha256=PLAN_HASH_1,
        static_store=store,
    )

    assert context.get_static_result("sky_visibility") is None
    assert context.static_cache_miss_count == 1
    value = _make_static_result(context, "sky_visibility")
    context.put_static_result("sky_visibility", value)

    warm = build_shading_acceleration_context(
        _compiled(),
        shading_configuration=_config(),
        receiver_ids=["receiver:module:m1"],
        source_execution_plan_id="plan-1",
        source_execution_plan_payload_sha256=PLAN_HASH_1,
        static_store=store,
    )
    assert warm.get_static_result("sky_visibility") == value
    assert warm.static_cache_hit_count == 1

    manifest = warm.cache_manifest()
    _validate_schema(
        "geometry/shading/shading-cache-manifest.schema.json",
        manifest,
    )
    assert manifest["cache_policy"] == {"mode": "exact"}
    assert manifest["source_execution_plan_payload_sha256"] == PLAN_HASH_1
    assert manifest["entry_count"] == 1
    assert manifest["entries"][0]["channel"] == "sky_visibility"


@pytest.mark.parametrize(
    "variant",
    [
        "geometry",
        "self_shading",
        "sky_resolution",
        "execution_plan",
    ],
)
def test_phase58_static_cache_invalidates_on_identity_change(variant):
    store = ExactStaticShadingCache(max_entries=16)
    base_geometry = _compiled()
    base_config = _config()
    base = build_shading_acceleration_context(
        base_geometry,
        shading_configuration=base_config,
        receiver_ids=["receiver:module:m1"],
        source_execution_plan_id="plan-1",
        source_execution_plan_payload_sha256=PLAN_HASH_1,
        static_store=store,
    )
    base.put_static_result(
        "sky_visibility",
        _make_static_result(base, "sky_visibility"),
    )

    geometry = base_geometry
    config = deepcopy(base_config)
    plan = "plan-1"
    plan_hash = PLAN_HASH_1

    if variant == "geometry":
        geometry = _compiled(geometry_hash="c" * 64)
    elif variant == "self_shading":
        config["self_shading_enabled"] = True
    elif variant == "sky_resolution":
        config["sky_dome_resolution"]["azimuth_sectors"] = 16
        config["sky_dome_resolution"]["horizon_azimuth_sectors"] = 16
    elif variant == "execution_plan":
        plan = "plan-2"
        plan_hash = PLAN_HASH_2

    changed = build_shading_acceleration_context(
        geometry,
        shading_configuration=config,
        receiver_ids=["receiver:module:m1"],
        source_execution_plan_id=plan,
        source_execution_plan_payload_sha256=plan_hash,
        static_store=store,
    )
    assert changed.get_static_result("sky_visibility") is None
    assert changed.static_cache_miss_count == 1


def test_phase58_solver_version_is_part_of_static_cache_identity(monkeypatch):
    import geometry.shading.cache as cache_module

    store = ExactStaticShadingCache(max_entries=8)
    first = build_shading_acceleration_context(
        _compiled(),
        shading_configuration=_config(),
        receiver_ids=["receiver:module:m1"],
        source_execution_plan_id="plan-1",
        source_execution_plan_payload_sha256=PLAN_HASH_1,
        static_store=store,
    )
    first.put_static_result(
        "sky_visibility",
        _make_static_result(first, "sky_visibility"),
    )

    monkeypatch.setattr(cache_module, "BEAM_SOLVER_VERSION", "future-test")
    second = build_shading_acceleration_context(
        _compiled(),
        shading_configuration=_config(),
        receiver_ids=["receiver:module:m1"],
        source_execution_plan_id="plan-1",
        source_execution_plan_payload_sha256=PLAN_HASH_1,
        static_store=store,
    )
    assert second.get_static_result("sky_visibility") is None


def test_phase58_cache_none_keeps_reference_path_and_empty_cache_manifest():
    context = build_shading_acceleration_context(
        _compiled(),
        shading_configuration=_config(mode="none"),
        receiver_ids=["receiver:module:m1"],
        source_execution_plan_id="plan-1",
        source_execution_plan_payload_sha256=PLAN_HASH_1,
        static_store=ExactStaticShadingCache(max_entries=4),
    )
    assert context.prepared_query_map() is None
    assert context.get_static_result("sky_visibility") is None
    assert context.metrics()["prepared_receiver_count"] == 0
    manifest = context.cache_manifest()
    _validate_schema(
        "geometry/shading/shading-cache-manifest.schema.json",
        manifest,
    )
    assert manifest["entry_count"] == 0
    assert manifest["cache_policy"] == {"mode": "none"}


def test_phase58_angular_bins_remain_explicitly_separate_from_exact_path():
    config = _config()
    config["cache_policy"] = {
        "mode": "angular_bins",
        "sun_azimuth_bin_deg": 5.0,
        "sun_altitude_bin_deg": 2.0,
    }
    with pytest.raises(ShadingAccelerationError, match="angular_bins"):
        build_shading_acceleration_context(
            _compiled(),
            shading_configuration=config,
            receiver_ids=["receiver:module:m1"],
        )
