"""Phase-5.9 annual geometry-aware ShadingResult assembly.

The annual artifact is intentionally small. Receiver factors remain in the
columnar dataset produced by the simulation artifact layer; this object binds
that dataset to the scene, execution plan, model contract, approximations, and
a path-independent physical-result identity.

The existing canonical SimulationConfiguration hash remains execution/config
identity. cache_policy.mode='none' and 'exact' therefore remain distinguishable
inputs even though they are exact-physics execution choices. This module adds a
separate scientific identity for comparing their physical shading results.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Mapping

from geometry.shading import (
    BEAM_SOLVER_ID,
    BEAM_SOLVER_VERSION,
    CONTRACT_VERSION,
    ELECTRICAL_SHADING_SCOPE,
    FACTOR_CONVENTION,
    GROUND_VISIBILITY_SOLVER_ID,
    GROUND_VISIBILITY_SOLVER_VERSION,
    GROUND_WEIGHTING_METHOD,
    SKY_VISIBILITY_SOLVER_ID,
    SKY_VISIBILITY_SOLVER_VERSION,
    SKY_WEIGHTING_METHOD,
    assert_shading_result_storage_consistency,
    normalize_product_namespace_identifier,
)


ANNUAL_SHADING_ORCHESTRATOR_ID = "rawibumi.annual_geometry_aware_shading"
ANNUAL_SHADING_ORCHESTRATOR_VERSION = "0.1"


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _scientific_shading_configuration(
    shading_configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the physics-significant shading configuration.

    cache_policy.mode='none' and 'exact' use the same exact equations and are
    normalized to a common scientific marker. Approximate cache policies are
    not normalized and therefore remain part of physical identity.
    """
    value = deepcopy(dict(shading_configuration))
    for field in ("beam_method", "diffuse_method", "albedo_method"):
        if field in value:
            value[field] = normalize_product_namespace_identifier(value[field])
    cache_policy = dict(value.get("cache_policy") or {})
    cache_mode = cache_policy.get("mode")
    if cache_mode in {"none", "exact"}:
        value["cache_policy"] = {"physics_semantics": "exact"}
    return value


def _solver_manifest(
    shading_configuration: Mapping[str, Any],
) -> dict[str, Any]:
    sky_enabled = (
        normalize_product_namespace_identifier(shading_configuration.get("diffuse_method")) == SKY_VISIBILITY_SOLVER_ID
    )
    ground_enabled = (
        normalize_product_namespace_identifier(shading_configuration.get("albedo_method")) == GROUND_VISIBILITY_SOLVER_ID
    )
    return {
        "beam": {
            "model_id": BEAM_SOLVER_ID,
            "model_version": BEAM_SOLVER_VERSION,
            "resolution": {
                "geometric_resolution": dict(
                    shading_configuration.get("geometric_resolution") or {}
                ),
                "sun_position_resolution_seconds": shading_configuration.get(
                    "sun_position_resolution_seconds"
                ),
                "sun_sampling_policy": (
                    "canonical_simulation_solar_evaluation_timestamps"
                ),
            },
            "notes": (
                "Exact Phase-5 polygon-projection beam visibility. Execution "
                "acceleration/cache telemetry is intentionally excluded from "
                "physical-result identity."
            ),
        },
        "sky_diffuse": (
            {
                "model_id": SKY_VISIBILITY_SOLVER_ID,
                "model_version": SKY_VISIBILITY_SOLVER_VERSION,
                "resolution": {
                    **dict(shading_configuration.get("sky_dome_resolution") or {}),
                    "weighting_method": SKY_WEIGHTING_METHOD,
                },
                "notes": (
                    "Static weighted upper-hemisphere visibility with a separate "
                    "horizon band; circumsolar visibility follows the current "
                    "sun-direction beam visibility."
                ),
            }
            if sky_enabled
            else {
                "model_id": "none",
                "model_version": "0.1",
                "resolution": {},
                "notes": "Sky obstruction is disabled.",
            }
        ),
        "ground": (
            {
                "model_id": GROUND_VISIBILITY_SOLVER_ID,
                "model_version": GROUND_VISIBILITY_SOLVER_VERSION,
                "resolution": {
                    **dict(
                        shading_configuration.get("ground_dome_resolution") or {}
                    ),
                    "weighting_method": GROUND_WEIGHTING_METHOD,
                },
                "notes": (
                    "Receiver-side lower-hemisphere visibility applied to the "
                    "existing uniform Lambertian scalar-albedo source."
                ),
            }
            if ground_enabled
            else {
                "model_id": "none",
                "model_version": "0.1",
                "resolution": {},
                "notes": "Ground obstruction is disabled.",
            }
        ),
    }


def _channels(shading_configuration: Mapping[str, Any]) -> list[str]:
    result = ["beam_visibility"]
    if normalize_product_namespace_identifier(shading_configuration.get("diffuse_method")) == SKY_VISIBILITY_SOLVER_ID:
        result.extend(["sky_visibility", "directional_diffuse_visibility"])
    if normalize_product_namespace_identifier(shading_configuration.get("albedo_method")) == GROUND_VISIBILITY_SOLVER_ID:
        result.append("ground_visibility")
    return result


def _approximation_manifest(
    shading_configuration: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result = [
        {
            "approximation_id": (
                "phase59_execution_group_area_weighted_geometric_irradiance"
            ),
            "scope": "electrical_input_aggregation",
            "description": (
                "Module receiver geometric visibility is area-weighted to one "
                "homogeneous execution-group irradiance state before the existing "
                "electrical model. Detailed electrical mismatch is not modeled."
            ),
        }
    ]
    if normalize_product_namespace_identifier(shading_configuration.get("diffuse_method")) == SKY_VISIBILITY_SOLVER_ID:
        result.append(
            {
                "approximation_id": "phase56_discrete_weighted_sky_dome",
                "scope": "sky_diffuse_geometry",
                "description": (
                    "Continuous sky visibility is integrated using the explicitly "
                    "configured discrete weighted sky and horizon domes."
                ),
            }
        )
    if normalize_product_namespace_identifier(shading_configuration.get("albedo_method")) == GROUND_VISIBILITY_SOLVER_ID:
        result.append(
            {
                "approximation_id": "phase57_uniform_lambertian_ground_view",
                "scope": "ground_reflected_geometry",
                "description": (
                    "Ground-reflected POA uses receiver-side lower-hemisphere "
                    "visibility of the existing uniform Lambertian scalar-albedo "
                    "source; spatial ground irradiance and bifacial rear irradiance "
                    "are not modeled."
                ),
            }
        )
    return result


def build_annual_shading_result(
    *,
    compiled_geometry: Mapping[str, Any],
    execution_group_plan: Mapping[str, Any],
    shading_configuration: Mapping[str, Any],
    shading_runtime: Mapping[str, Any],
    dataset_reference: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one annual/long-run dataset-reference ShadingResult.

    The returned dataset_reference is copied directly from the canonical
    receiver-factor persistence result. SimulationRun must expose the same
    logical object rather than constructing a competing dataset identity.
    """
    geometry_hash = str(compiled_geometry.get("geometry_payload_sha256") or "")
    scene_revision_id = str(
        compiled_geometry.get("source_scene_revision_id") or ""
    )
    execution_plan_id = str(execution_group_plan.get("execution_plan_id") or "")
    execution_plan_sha256 = str(
        execution_group_plan.get("execution_plan_payload_sha256") or ""
    )
    receiver_set_sha256 = str(shading_runtime.get("receiver_set_sha256") or "")
    if not (
        len(geometry_hash) == 64
        and len(execution_plan_sha256) == 64
        and len(receiver_set_sha256) == 64
        and scene_revision_id
        and execution_plan_id
    ):
        raise ValueError(
            "annual ShadingResult requires complete scene/geometry/execution/"
            "receiver provenance"
        )

    dataset = deepcopy(dict(dataset_reference))
    if not dataset.get("physical_content_sha256"):
        raise ValueError(
            "annual ShadingResult requires receiver-factor physical_content_sha256"
        )
    record_count = dataset.get("row_count")
    if isinstance(record_count, bool) or not isinstance(record_count, int):
        raise ValueError("receiver-factor dataset row_count must be an integer")

    scientific_configuration = _scientific_shading_configuration(
        shading_configuration
    )
    scientific_configuration_sha256 = _sha256_json(scientific_configuration)
    solver_manifest = _solver_manifest(shading_configuration)
    channels = _channels(shading_configuration)
    approximations = _approximation_manifest(shading_configuration)

    physical_payload = {
        "physical_identity_version": "phase59.v0.1",
        "source_scene_revision_id": scene_revision_id,
        "compiled_geometry_hash": geometry_hash,
        "scientific_shading_configuration_sha256": (
            scientific_configuration_sha256
        ),
        "source_execution_plan_payload_sha256": execution_plan_sha256,
        "receiver_set_sha256": receiver_set_sha256,
        "solver_manifest": solver_manifest,
        "channels": channels,
        "factor_convention": FACTOR_CONVENTION,
        "electrical_shading_scope": ELECTRICAL_SHADING_SCOPE,
        "receiver_factor_physical_content_sha256": dataset[
            "physical_content_sha256"
        ],
        "record_count": record_count,
        "approximation_manifest": approximations,
    }
    physical_result_sha256 = _sha256_json(physical_payload)

    payload = {
        "schema_name": "ShadingResult",
        "schema_version": "0.1",
        "contract_version": CONTRACT_VERSION,
        "orchestrator_manifest": {
            "orchestrator_id": ANNUAL_SHADING_ORCHESTRATOR_ID,
            "orchestrator_version": ANNUAL_SHADING_ORCHESTRATOR_VERSION,
        },
        "source_scene_revision_id": scene_revision_id,
        "compiled_geometry_hash": geometry_hash,
        "shading_configuration_hash": _sha256_json(
            dict(shading_configuration)
        ),
        "scientific_shading_configuration_sha256": (
            scientific_configuration_sha256
        ),
        "source_execution_plan_id": execution_plan_id,
        "source_execution_plan_payload_sha256": execution_plan_sha256,
        "receiver_set_sha256": receiver_set_sha256,
        "solver_manifest": solver_manifest,
        "fidelity_level": shading_configuration["fidelity_level"],
        "receiver_granularity": shading_configuration[
            "receiver_granularity"
        ],
        "factor_convention": FACTOR_CONVENTION,
        "electrical_shading_scope": ELECTRICAL_SHADING_SCOPE,
        "channels": channels,
        "storage_mode": "dataset_reference",
        "record_count": record_count,
        "dataset_reference": dataset,
        "physical_result_sha256": physical_result_sha256,
        "approximation_manifest": approximations,
        "findings": [],
    }
    result_payload_sha256 = _sha256_json(payload)
    result = {
        **payload,
        "shading_result_id": (
            f"shading-result:{physical_result_sha256[:16]}"
        ),
        "result_payload_sha256": result_payload_sha256,
    }
    assert_shading_result_storage_consistency(result)
    return result
