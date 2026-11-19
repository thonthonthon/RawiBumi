import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from engine.simulation import build_simulation_execution_plan
from geometry.shading import (
    BEAM_SOLVER_ID,
    BeamSnapshotError,
    calculate_direct_beam_shadow,
    compile_shading_geometry,
    evaluate_beam_shading_snapshot,
    receiver_ids_from_execution_group_plan,
    sun_vector_from_azimuth_elevation,
)


ROOT = Path(__file__).resolve().parents[2]
HASH = "a" * 64


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


def _receiver(receiver_id, module_id, x0):
    vertices = [
        [x0, 0.0, 0.0],
        [x0 + 2.0, 0.0, 0.0],
        [x0 + 2.0, 2.0, 0.0],
        [x0, 2.0, 0.0],
    ]
    return {
        "receiver_id": receiver_id,
        "source_entity_type": "module_instance",
        "source_entity_id": module_id,
        "receiver_type": "module_plane",
        "vertices_3d": vertices,
        "center_xyz": [x0 + 1.0, 1.0, 0.0],
        "normal_xyz": [0.0, 0.0, 1.0],
        "area_m2": 4.0,
        "enabled": True,
        "pv_field_id": "field-1",
        "support_surface_id": "surface-1",
        "module_instance_id": module_id,
        "metadata": {},
    }


def _compiled():
    obstacle = {
        "occluder_id": "occluder:obstacle:block",
        "source_entity_type": "obstacle",
        "source_entity_id": "block",
        "geometry_type": "polygon_faces",
        "faces": [
            {
                "face_id": "block:top",
                "vertices_3d": [
                    [0.0, 0.0, 1.0],
                    [2.0, 0.0, 1.0],
                    [2.0, 2.0, 1.0],
                    [0.0, 2.0, 1.0],
                ],
                "normal_xyz": [0.0, 0.0, 1.0],
            }
        ],
        "bounds_3d": {
            "min_xyz": [0.0, 0.0, 1.0],
            "max_xyz": [2.0, 2.0, 1.0],
        },
        "shading_enabled": True,
        "metadata": {},
    }
    return {
        "source_scene_revision_id": "scene-r1",
        "geometry_payload_sha256": HASH,
        "receivers": [
            _receiver("receiver:module:m1", "m1", 0.0),
            _receiver("receiver:module:m2", "m2", 3.0),
        ],
        "occluders": [obstacle],
    }


def _configuration(*, self_shading_enabled=False):
    return {
        "beam_method": BEAM_SOLVER_ID,
        "diffuse_method": "none",
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
        "model_options": {},
    }


def _execution_plan():
    return {
        "authority": "derived_execution_only",
        "execution_plan_id": "execution-plan:test",
        "compiled_geometry_hash": HASH,
        "groups": [
            {
                "execution_group_id": "execgrp:one",
                "receiver_ids": [
                    "receiver:module:m2",
                    "receiver:module:m1",
                ],
                "missing_receiver_module_ids": [],
            }
        ],
    }


def test_phase54_snapshot_populates_shading_result_in_stable_receiver_order():
    snapshot = evaluate_beam_shading_snapshot(
        _compiled(),
        shading_configuration=_configuration(),
        sun_vector_xyz=(0.0, 0.0, 1.0),
        receiver_ids=[
            "receiver:module:m2",
            "receiver:module:m1",
            "receiver:module:m2",
        ],
        timestamp="2026-09-24T14:00:00+07:00",
    )
    result = snapshot.shading_result

    assert snapshot.diagnostic_artifact is None
    assert result["channels"] == ["beam_visibility"]
    assert result["record_count"] == 2
    assert [item["receiver_id"] for item in result["inline_records"]] == [
        "receiver:module:m1",
        "receiver:module:m2",
    ]
    assert result["inline_records"][0]["beam_visibility_factor"] == 0.0
    assert result["inline_records"][1]["beam_visibility_factor"] == 1.0
    assert result["inline_records"][0]["timestamp"] == "2026-09-24T07:00:00Z"
    assert result["inline_records"][0]["sky_visibility_factor"] is None
    assert result["inline_records"][0]["ground_visibility_factor"] is None
    assert result["inline_records"][0]["quality_flags"] == [
        "receiver_fully_shaded",
        "self_shading_disabled",
    ]
    assert result["inline_records"][1]["quality_flags"] == [
        "receiver_clear",
        "self_shading_disabled",
    ]
    assert result["electrical_shading_scope"] == "not_modeled"
    assert result["orchestrator_manifest"]["orchestrator_id"] == (
        "rawibumi.beam_shading_snapshot"
    )
    _validate("geometry/shading/shading-result.schema.json", result)


def test_phase54_snapshot_matches_phase53_single_receiver_queries_exactly():
    compiled = _compiled()
    snapshot = evaluate_beam_shading_snapshot(
        compiled,
        shading_configuration=_configuration(),
        sun_vector_xyz=(0.0, 0.0, 1.0),
        receiver_ids=[
            "receiver:module:m1",
            "receiver:module:m2",
        ],
    ).shading_result

    for record in snapshot["inline_records"]:
        single = calculate_direct_beam_shadow(
            compiled,
            receiver_id=record["receiver_id"],
            sun_vector_xyz=(0.0, 0.0, 1.0),
            self_shading_enabled=False,
        )
        assert record["beam_visibility_factor"] == single[
            "beam_visibility_factor"
        ]
        assert record["sun_vector_xyz"] == single["sun_vector_xyz"]


def test_phase54_diagnostics_are_separate_and_do_not_change_scalar_result():
    compiled = _compiled()
    normal = evaluate_beam_shading_snapshot(
        compiled,
        shading_configuration=_configuration(),
        sun_vector_xyz=(0.0, 0.0, 1.0),
        receiver_ids=["receiver:module:m1", "receiver:module:m2"],
        timestamp="2026-09-24T07:00:00Z",
        include_diagnostics=False,
    )
    diagnostic = evaluate_beam_shading_snapshot(
        compiled,
        shading_configuration=_configuration(),
        sun_vector_xyz=(0.0, 0.0, 1.0),
        receiver_ids=["receiver:module:m2", "receiver:module:m1"],
        timestamp="2026-09-24T07:00:00Z",
        include_diagnostics=True,
    )

    assert normal.shading_result == diagnostic.shading_result
    artifact = diagnostic.diagnostic_artifact
    assert artifact is not None
    assert artifact["authority"] == "derived_diagnostic_only"
    assert artifact["editable"] is False
    assert artifact["shading_result_id"] == normal.shading_result[
        "shading_result_id"
    ]
    assert artifact["receiver_count"] == 2
    assert artifact["entries"][0]["receiver_id"] == "receiver:module:m1"
    assert artifact["entries"][0]["shadow_union_polygons_uv"]
    assert artifact["entries"][1]["shadow_union_polygons_uv"] == []
    _validate(
        "geometry/shading/beam-shadow-diagnostic-artifact.schema.json",
        artifact,
    )


def test_phase54_execution_group_receiver_selection_is_explicit_and_hash_bound():
    compiled = _compiled()
    plan = _execution_plan()

    assert receiver_ids_from_execution_group_plan(plan) == [
        "receiver:module:m1",
        "receiver:module:m2",
    ]

    snapshot = evaluate_beam_shading_snapshot(
        compiled,
        shading_configuration=_configuration(),
        sun_vector_xyz=(0.0, 0.0, 1.0),
        execution_group_plan=plan,
    ).shading_result
    assert snapshot["source_execution_plan_id"] == "execution-plan:test"
    assert snapshot["record_count"] == 2

    bad_plan = dict(plan)
    bad_plan["compiled_geometry_hash"] = "b" * 64
    with pytest.raises(BeamSnapshotError, match="compiled_geometry_hash"):
        evaluate_beam_shading_snapshot(
            compiled,
            shading_configuration=_configuration(),
            sun_vector_xyz=(0.0, 0.0, 1.0),
            execution_group_plan=bad_plan,
        )


def test_phase54_snapshot_identity_is_independent_of_receiver_input_order():
    compiled = _compiled()
    first = evaluate_beam_shading_snapshot(
        compiled,
        shading_configuration=_configuration(),
        sun_vector_xyz=(0.0, 0.0, 5.0),
        receiver_ids=["receiver:module:m1", "receiver:module:m2"],
    ).shading_result
    second = evaluate_beam_shading_snapshot(
        compiled,
        shading_configuration=_configuration(),
        sun_vector_xyz=(0.0, 0.0, 1.0),
        receiver_ids=["receiver:module:m2", "receiver:module:m1"],
    ).shading_result

    assert first == second
    assert first["receiver_set_sha256"] == second["receiver_set_sha256"]
    assert first["sun_state_sha256"] == second["sun_state_sha256"]
    assert first["result_payload_sha256"] == second["result_payload_sha256"]


@pytest.mark.parametrize(
    "mutation,match",
    [
        ({"diffuse_method": "sky_dome"}, "diffuse_method"),
        ({"albedo_method": "ground_view"}, "albedo_method"),
        ({"cache_policy": {"mode": "angular_bins", "sun_azimuth_bin_deg": 1.0, "sun_altitude_bin_deg": 1.0}}, "angular_bins"),
        ({"model_options": {"hidden": True}}, "model_options"),
        ({"geometric_resolution": {"receiver_subdivision_u": 2, "receiver_subdivision_v": 1}}, "receiver_subdivision_u"),
    ],
)
def test_phase54_unsupported_snapshot_options_fail_closed(mutation, match):
    config = _configuration()
    config.update(mutation)
    with pytest.raises(BeamSnapshotError, match=match):
        evaluate_beam_shading_snapshot(
            _compiled(),
            shading_configuration=config,
            sun_vector_xyz=(0.0, 0.0, 1.0),
            receiver_ids=["receiver:module:m1"],
        )


def _load_phase49c_reference_module():
    path = ROOT / "tests/unit/test_phase49c_reference_projects.py"
    spec = importlib.util.spec_from_file_location(
        "_rawibumi_phase49c_reference_for_phase54",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase54_r4_receiver_chain_is_reproducible_and_directional():
    phase49c = _load_phase49c_reference_module()
    ref = phase49c._reference("R4")

    compiled = compile_shading_geometry(ref["scene"])
    plan = build_simulation_execution_plan(
        ref["scene"],
        ref["electrical"],
        numerical_options={"albedo": 0.20},
        compiled_shading_geometry=compiled,
    )
    assert plan["execution_class"] == "homogeneous_single_group"
    assert plan["group_count"] == 1
    assert len(plan["groups"][0]["receiver_ids"]) == 216

    config = _configuration(self_shading_enabled=False)
    north_sun = sun_vector_from_azimuth_elevation(0.0, 15.0)
    south_sun = sun_vector_from_azimuth_elevation(180.0, 30.0)

    north = evaluate_beam_shading_snapshot(
        compiled,
        shading_configuration=config,
        sun_vector_xyz=north_sun,
        execution_group_plan=plan,
        timestamp="2026-03-21T08:00:00+07:00",
    ).shading_result
    north_repeat = evaluate_beam_shading_snapshot(
        compiled,
        shading_configuration=config,
        sun_vector_xyz=north_sun,
        execution_group_plan=plan,
        timestamp="2026-03-21T08:00:00+07:00",
    ).shading_result
    south = evaluate_beam_shading_snapshot(
        compiled,
        shading_configuration=config,
        sun_vector_xyz=south_sun,
        execution_group_plan=plan,
        timestamp="2026-03-21T16:00:00+07:00",
    ).shading_result

    assert north == north_repeat
    assert north["record_count"] == 216
    assert south["record_count"] == 216
    assert north["source_execution_plan_id"] == plan["execution_plan_id"]

    north_factors = {
        item["receiver_id"]: item["beam_visibility_factor"]
        for item in north["inline_records"]
    }
    south_factors = {
        item["receiver_id"]: item["beam_visibility_factor"]
        for item in south["inline_records"]
    }
    assert min(north_factors.values()) < 1.0
    assert max(north_factors.values()) == 1.0
    assert min(south_factors.values()) < 1.0
    assert max(south_factors.values()) == 1.0

    north_shaded = {
        receiver_id
        for receiver_id, factor in north_factors.items()
        if factor < 1.0
    }
    south_shaded = {
        receiver_id
        for receiver_id, factor in south_factors.items()
        if factor < 1.0
    }
    assert north_shaded
    assert south_shaded
    assert north_shaded != south_shaded
