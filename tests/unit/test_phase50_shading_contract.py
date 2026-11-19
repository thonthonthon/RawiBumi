import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from geometry.shading import (
    COORDINATE_BASIS,
    FACTOR_CONVENTION,
    SUN_VECTOR_CONVENTION,
    ShadingContractError,
    assert_geometry_aware_shading_configuration,
    shaded_fraction_from_visibility,
    sun_vector_from_azimuth_elevation,
)


ROOT = Path(__file__).resolve().parents[2]


def _load(relative_path: str):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _registry() -> Registry:
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


def _phase5_configuration():
    return {
        "beam_method": "polygon_projection.v0.1",
        "diffuse_method": "sky_dome_isotropic.v0.1",
        "albedo_method": "ground_view.v0.1",
        "fidelity_level": "engineering",
        "sun_position_resolution_seconds": None,
        "electrical_shading_method": None,
        "geometry_contract_version": "0.1",
        "coordinate_basis": COORDINATE_BASIS,
        "sun_vector_convention": SUN_VECTOR_CONVENTION,
        "factor_convention": FACTOR_CONVENTION,
        "receiver_granularity": "module",
        "self_shading_enabled": True,
        "cache_policy": {"mode": "exact"},
        "geometric_resolution": {
            "receiver_subdivision_u": 1,
            "receiver_subdivision_v": 1,
        },
        "model_options": {},
    }


def test_sun_vector_uses_east_north_up_and_receiver_to_sun_convention():
    north = sun_vector_from_azimuth_elevation(0.0, 0.0)
    east = sun_vector_from_azimuth_elevation(90.0, 0.0)
    up = sun_vector_from_azimuth_elevation(123.0, 90.0)

    assert north == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)
    assert east == pytest.approx((1.0, 0.0, 0.0), abs=1e-12)
    assert up == pytest.approx((0.0, 0.0, 1.0), abs=1e-12)
    assert math.sqrt(sum(value * value for value in north)) == pytest.approx(1.0)


def test_visibility_factor_convention_is_one_clear_zero_blocked():
    assert shaded_fraction_from_visibility(1.0) == pytest.approx(0.0)
    assert shaded_fraction_from_visibility(0.0) == pytest.approx(1.0)
    assert shaded_fraction_from_visibility(0.25) == pytest.approx(0.75)

    with pytest.raises(ShadingContractError):
        shaded_fraction_from_visibility(-0.01)
    with pytest.raises(ShadingContractError):
        shaded_fraction_from_visibility(1.01)


def test_geometry_aware_configuration_requires_explicit_phase5_contract():
    configuration = _phase5_configuration()
    assert_geometry_aware_shading_configuration(configuration)

    missing = dict(configuration)
    del missing["factor_convention"]
    with pytest.raises(ShadingContractError):
        assert_geometry_aware_shading_configuration(missing)

    electrical = dict(configuration)
    electrical["electrical_shading_method"] = "bypass_substring"
    with pytest.raises(ShadingContractError):
        assert_geometry_aware_shading_configuration(electrical)


def test_phase4_shading_configuration_remains_schema_compatible():
    schema = _load("geometry/shading/shading-configuration.schema.json")
    legacy = {
        "beam_method": "none",
        "diffuse_method": "none",
        "albedo_method": "support_surface",
        "fidelity_level": "engineering",
        "sun_position_resolution_seconds": None,
        "electrical_shading_method": None,
    }
    Draft202012Validator(schema, registry=_registry()).validate(legacy)

    external_reference = dict(legacy)
    external_reference["beam_method"] = "pvsyst_shd_reference"
    external_reference["diffuse_method"] = "pvsyst_shd_reference"
    Draft202012Validator(schema, registry=_registry()).validate(external_reference)


def test_explicit_phase5_shading_configuration_validates_inside_simulation_configuration():
    simulation_schema = _load("schemas/simulation-configuration.schema.json")
    configuration = {
        "schema_name": "SimulationConfiguration",
        "schema_version": "0.1",
        "simulation_configuration_id": "simcfg-phase50",
        "project_revision_id": "project-revision-phase50",
        "simulation_timestep_seconds": 3600,
        "weather_dataset_revision_id": "weather-phase50",
        "model_selections": {
            "solar_position": "solar.test",
            "transposition": "poa.test",
            "temperature": "temperature.test",
            "module_electrical": "module.test",
            "inverter": "inverter.test",
        },
        "loss_model_ids": [],
        "shading_configuration": _phase5_configuration(),
        "numerical_options": {},
        "output_configuration": {},
    }
    Draft202012Validator(
        simulation_schema, registry=_registry()
    ).validate(configuration)


def test_compiled_geometry_result_and_cache_contract_examples_validate():
    registry = _registry()
    digest_a = "a" * 64
    digest_b = "b" * 64
    digest_c = "c" * 64
    digest_d = "d" * 64

    compiled = {
        "schema_name": "CompiledShadingGeometry",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "authority": "derived_numerical_only",
        "editable": False,
        "source_scene_id": "scene-1",
        "source_scene_revision_id": "scene-revision-1",
        "coordinate_system_id": "coords-1",
        "coordinate_basis": COORDINATE_BASIS,
        "source_scene_hash": digest_a,
        "compiler_id": "shading_geometry_compiler.reference",
        "compiler_version": "0.1",
        "compilation_input_hash": digest_b,
        "compiled_geometry_id": "compiled-1",
        "geometry_payload_sha256": digest_c,
        "receivers": [
            {
                "receiver_id": "receiver-module-1",
                "source_entity_type": "module_instance",
                "source_entity_id": "module-1",
                "receiver_type": "module_plane",
                "vertices_3d": [
                    [0.0, 0.0, 1.0],
                    [1.0, 0.0, 1.0],
                    [1.0, 2.0, 1.0],
                    [0.0, 2.0, 1.0],
                ],
                "center_xyz": [0.5, 1.0, 1.0],
                "normal_xyz": [0.0, 0.0, 1.0],
                "area_m2": 2.0,
                "enabled": True,
                "pv_field_id": "field-1",
                "support_surface_id": "surface-1",
                "module_instance_id": "module-1",
                "metadata": {},
            }
        ],
        "occluders": [
            {
                "occluder_id": "occluder-obstacle-1",
                "source_entity_type": "obstacle",
                "source_entity_id": "obstacle-1",
                "geometry_type": "polygon_faces",
                "faces": [
                    {
                        "face_id": "face-1",
                        "vertices_3d": [
                            [2.0, 0.0, 0.0],
                            [3.0, 0.0, 0.0],
                            [3.0, 0.0, 1.0],
                            [2.0, 0.0, 1.0],
                        ],
                        "normal_xyz": [0.0, -1.0, 0.0],
                    }
                ],
                "bounds_3d": {
                    "min_xyz": [2.0, 0.0, 0.0],
                    "max_xyz": [3.0, 0.0, 1.0],
                },
                "shading_enabled": True,
                "metadata": {},
            }
        ],
        "bounds_3d": {
            "min_xyz": [0.0, 0.0, 0.0],
            "max_xyz": [3.0, 2.0, 1.0],
        },
        "finding_count": 0,
        "findings": [],
    }
    Draft202012Validator(
        _load("geometry/shading/compiled-shading-geometry.schema.json"),
        registry=registry,
    ).validate(compiled)

    result = {
        "schema_name": "ShadingResult",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "shading_result_id": "shading-result-1",
        "orchestrator_manifest": {
            "orchestrator_id": "phase50-contract-fixture",
            "orchestrator_version": "0.1",
        },
        "source_scene_revision_id": "scene-revision-1",
        "compiled_geometry_hash": digest_c,
        "shading_configuration_hash": digest_d,
        "solver_manifest": {
            "beam": {
                "model_id": "none",
                "model_version": "0.1",
                "resolution": {},
                "notes": None,
            },
            "sky_diffuse": {
                "model_id": "none",
                "model_version": "0.1",
                "resolution": {},
                "notes": None,
            },
            "ground": {
                "model_id": "none",
                "model_version": "0.1",
                "resolution": {},
                "notes": None,
            },
        },
        "fidelity_level": "engineering",
        "receiver_granularity": "module",
        "factor_convention": FACTOR_CONVENTION,
        "electrical_shading_scope": "not_modeled",
        "channels": [
            "beam_visibility",
            "sky_visibility",
            "ground_visibility",
        ],
        "storage_mode": "inline",
        "record_count": 1,
        "receiver_set_sha256": digest_b,
        "source_execution_plan_id": None,
        "result_payload_sha256": digest_a,
        "inline_records": [
            {
                "receiver_id": "receiver-module-1",
                "timestamp": "2026-09-24T05:00:00Z",
                "sun_vector_xyz": [1.0, 0.0, 0.0],
                "beam_visibility_factor": 1.0,
                "sky_visibility_factor": 1.0,
                "ground_visibility_factor": 1.0,
                "quality_flags": [],
            }
        ],
        "approximation_manifest": [],
        "findings": [],
    }
    Draft202012Validator(
        _load("geometry/shading/shading-result.schema.json"),
        registry=registry,
    ).validate(result)

    cache = {
        "schema_name": "ShadingCacheManifest",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "cache_manifest_id": "cache-1",
        "source_scene_revision_id": "scene-revision-1",
        "compiled_geometry_hash": digest_c,
        "shading_configuration_hash": digest_d,
        "solver_manifest_hash": digest_a,
        "source_execution_plan_payload_sha256": digest_b,
        "fidelity_level": "engineering",
        "cache_policy": {"mode": "exact"},
        "deterministic": True,
        "entry_count": 1,
        "entries": [
            {
                "cache_key_sha256": digest_a,
                "channel": "beam_visibility",
                "receiver_set_sha256": digest_b,
                "sun_state_sha256": digest_c,
                "result_sha256": digest_d,
                "entry_uri": None,
            }
        ],
        "invalidation_basis": [
            "source_scene_revision",
            "compiled_geometry_hash",
            "shading_configuration_hash",
            "solver_manifest_hash",
            "fidelity_level",
            "receiver_set",
            "sun_state",
            "execution_plan",
        ],
    }
    Draft202012Validator(
        _load("geometry/shading/shading-cache-manifest.schema.json"),
        registry=registry,
    ).validate(cache)
