"""Phase-5.6 receiver-set static sky visibility snapshots."""

from __future__ import annotations

from .beam import _fallback_evidence

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping

from .contract import (
    CONTRACT_VERSION,
    ELECTRICAL_SHADING_SCOPE,
    FACTOR_CONVENTION,
    ShadingContractError,
    assert_geometry_aware_shading_configuration,
)
from .ground import GROUND_VISIBILITY_SOLVER_ID
from .contract import normalize_product_namespace_identifier
from .prepared import (
    PREPARED_DIRECTIONAL_ENGINE_ID,
    PREPARED_DIRECTIONAL_ENGINE_VERSION,
    PreparedDirectionalReceiver,
)
from .sky import (
    SKY_VISIBILITY_SOLVER_ID,
    SKY_VISIBILITY_SOLVER_VERSION,
    SKY_WEIGHTING_METHOD,
    SkyDomeResolution,
    SkyVisibilityError,
    calculate_sky_visibility,
)
from .snapshot import receiver_ids_from_execution_group_plan


SKY_SNAPSHOT_ORCHESTRATOR_ID = "rawibumi.sky_shading_snapshot"
SKY_SNAPSHOT_ORCHESTRATOR_VERSION = "0.1"


class SkySnapshotError(ValueError):
    """Raised when a Phase-5.6 sky snapshot cannot be evaluated safely."""


@dataclass(frozen=True)
class SkyShadingSnapshotResult:
    shading_result: dict[str, Any]


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_configuration(configuration: Mapping[str, Any]) -> SkyDomeResolution:
    try:
        assert_geometry_aware_shading_configuration(configuration)
    except ShadingContractError as exc:
        raise SkySnapshotError(str(exc)) from exc

    diffuse_method = normalize_product_namespace_identifier(configuration.get("diffuse_method"))
    albedo_method = normalize_product_namespace_identifier(configuration.get("albedo_method"))
    if diffuse_method != SKY_VISIBILITY_SOLVER_ID:
        raise SkySnapshotError(
            f"diffuse_method must be {SKY_VISIBILITY_SOLVER_ID!r}"
        )
    if albedo_method not in {
        None,
        "none",
        GROUND_VISIBILITY_SOLVER_ID,
    }:
        raise SkySnapshotError(
            "snapshot accepts ground obstruction disabled or the explicit "
            "Phase-5.7 weighted ground solver; other ground methods are not executable"
        )

    if configuration.get("receiver_granularity") == "pv_field":
        raise SkySnapshotError(
            "pv_field receiver granularity is not produced by current compiled geometry"
        )
    if (configuration.get("cache_policy") or {}).get("mode") == "angular_bins":
        raise SkySnapshotError(
            "angular-bin cache policy is not used by static Phase-5.6 sky visibility"
        )

    resolution = configuration.get("geometric_resolution") or {}
    for field in ("receiver_subdivision_u", "receiver_subdivision_v"):
        if field in resolution:
            value = resolution[field]
            if isinstance(value, bool) or value != 1:
                raise SkySnapshotError(
                    f"{field} other than integer 1 is not implemented"
                )
    if "occluder_chord_tolerance_m" in resolution:
        raise SkySnapshotError(
            "occluder_chord_tolerance_m is not consumed by the polygon reference kernel"
        )
    if configuration.get("model_options"):
        raise SkySnapshotError(
            "model_options must be empty for the Phase-5.6 reference solver"
        )

    raw = configuration.get("sky_dome_resolution")
    if not isinstance(raw, Mapping):
        raise SkySnapshotError(
            "sky_dome_resolution must be explicit for Phase-5.6 sky visibility"
        )
    try:
        return SkyDomeResolution.from_mapping(raw)
    except SkyVisibilityError as exc:
        raise SkySnapshotError(str(exc)) from exc


def _resolve_receiver_ids(
    compiled_geometry: Mapping[str, Any],
    *,
    receiver_ids: Iterable[str] | None,
    execution_group_plan: Mapping[str, Any] | None,
    execution_group_ids: Iterable[str] | None,
    receiver_granularity: str,
) -> tuple[list[str], str | None]:
    if receiver_ids is not None and execution_group_plan is not None:
        raise SkySnapshotError(
            "provide receiver_ids or execution_group_plan selection, not both"
        )
    if receiver_ids is None and execution_group_plan is None:
        raise SkySnapshotError(
            "receiver selection must be explicit"
        )

    source_plan_id: str | None = None
    if execution_group_plan is not None:
        if (
            execution_group_plan.get("compiled_geometry_hash")
            != compiled_geometry.get("geometry_payload_sha256")
        ):
            raise SkySnapshotError(
                "execution group plan and compiled geometry hashes do not match"
            )
        selected = receiver_ids_from_execution_group_plan(
            execution_group_plan,
            execution_group_ids=execution_group_ids,
        )
        source_plan_id = str(execution_group_plan.get("execution_plan_id") or "")
        if not source_plan_id:
            raise SkySnapshotError("execution_group_plan lacks execution_plan_id")
    else:
        if execution_group_ids is not None:
            raise SkySnapshotError(
                "execution_group_ids requires execution_group_plan"
            )
        selected = sorted(set(str(item) for item in receiver_ids or []))
        if not selected:
            raise SkySnapshotError("receiver_ids must not be empty")

    receiver_map = {
        str(item.get("receiver_id")): item
        for item in compiled_geometry.get("receivers", [])
    }
    unknown = [item for item in selected if item not in receiver_map]
    if unknown:
        raise SkySnapshotError("unknown receiver_id(s): " + ", ".join(unknown))
    disabled = [
        item for item in selected
        if receiver_map[item].get("enabled") is not True
    ]
    if disabled:
        raise SkySnapshotError(
            "disabled receiver_id(s) cannot be evaluated: " + ", ".join(disabled)
        )

    source_types = {
        str(receiver_map[item].get("source_entity_type") or "")
        for item in selected
    }
    if receiver_granularity == "module" and source_types != {"module_instance"}:
        raise SkySnapshotError(
            "receiver_granularity='module' requires module_instance receivers"
        )
    if receiver_granularity == "surface" and source_types != {"surface"}:
        raise SkySnapshotError(
            "receiver_granularity='surface' requires surface receivers"
        )
    if receiver_granularity == "mixed" and not source_types.issubset(
        {"module_instance", "surface"}
    ):
        raise SkySnapshotError("mixed receiver selection contains unsupported type")
    return selected, source_plan_id


def _quality_flags(
    sky_factor: float,
    horizon_factor: float,
    *,
    self_shading_enabled: bool,
) -> list[str]:
    flags: list[str] = []
    if sky_factor == 1.0:
        flags.append("sky_clear")
    elif sky_factor == 0.0:
        flags.append("sky_fully_obstructed")
    else:
        flags.append("sky_partially_obstructed")

    if horizon_factor == 1.0:
        flags.append("horizon_clear")
    elif horizon_factor == 0.0:
        flags.append("horizon_fully_obstructed")
    else:
        flags.append("horizon_partially_obstructed")

    if not self_shading_enabled:
        flags.append("self_shading_disabled")
    return flags


def evaluate_sky_shading_snapshot(
    compiled_geometry: Mapping[str, Any],
    *,
    shading_configuration: Mapping[str, Any],
    receiver_ids: Iterable[str] | None = None,
    execution_group_plan: Mapping[str, Any] | None = None,
    execution_group_ids: Iterable[str] | None = None,
    prepared_queries: Mapping[str, PreparedDirectionalReceiver] | None = None,
) -> SkyShadingSnapshotResult:
    """Evaluate static isotropic-sky and horizon visibility across receivers."""
    resolution = _validate_configuration(shading_configuration)

    geometry_hash = str(compiled_geometry.get("geometry_payload_sha256") or "")
    if (
        len(geometry_hash) != 64
        or any(character not in "0123456789abcdef" for character in geometry_hash)
    ):
        raise SkySnapshotError(
            "compiled geometry must provide lowercase geometry_payload_sha256"
        )
    scene_revision_id = str(
        compiled_geometry.get("source_scene_revision_id") or ""
    )
    if not scene_revision_id:
        raise SkySnapshotError(
            "compiled geometry must retain source_scene_revision_id"
        )

    selected, source_plan_id = _resolve_receiver_ids(
        compiled_geometry,
        receiver_ids=receiver_ids,
        execution_group_plan=execution_group_plan,
        execution_group_ids=execution_group_ids,
        receiver_granularity=str(shading_configuration["receiver_granularity"]),
    )
    receiver_set_sha256 = _sha256_json(selected)
    configuration_hash = _sha256_json(dict(shading_configuration))
    self_shading_enabled = bool(
        shading_configuration["self_shading_enabled"]
    )

    records: list[dict[str, Any]] = []
    first_query: dict[str, Any] | None = None
    evaluation_count = 0

    parallel_results = (
        prepared_queries.evaluate("sky", selected, resolution=resolution)
        if hasattr(prepared_queries, "evaluate") else None
    )

    for receiver_id in selected:
        try:
            if parallel_results is not None:
                query = parallel_results[receiver_id]
            else:
                query = calculate_sky_visibility(
                    compiled_geometry,
                    receiver_id=receiver_id,
                    self_shading_enabled=self_shading_enabled,
                    resolution=resolution,
                    prepared_query=(
                        prepared_queries.get(receiver_id)
                        if prepared_queries is not None
                        else None
                    ),
                )
        except SkyVisibilityError as exc:
            raise SkySnapshotError(
                f"sky evaluation failed for {receiver_id}: {exc}"
            ) from exc
        if first_query is None:
            first_query = query
        evaluation_count += int(query["evaluation_count"])

        sky_factor = float(query["sky_visibility_factor"])
        horizon_factor = float(query["horizon_visibility_factor"])
        records.append(
            {
                "receiver_id": receiver_id,
                **{key: value for key, value in _fallback_evidence(query).items()
                   if key != "quality_flags"},
                "timestamp": None,
                "sun_vector_xyz": None,
                "beam_visibility_factor": None,
                "sky_visibility_factor": sky_factor,
                "ground_visibility_factor": None,
                "directional_diffuse_visibility": {
                    "horizon": horizon_factor,
                },
                "quality_flags": _quality_flags(
                    sky_factor,
                    horizon_factor,
                    self_shading_enabled=self_shading_enabled,
                ) + query.get("quality_flags", []),
            }
        )

    if first_query is None:
        raise SkySnapshotError("receiver selection produced no evaluations")

    solver_manifest = {
        "beam": {
            "model_id": "none",
            "model_version": "0.1",
            "resolution": {},
            "notes": "This static snapshot does not evaluate the time-varying beam channel.",
        },
        "sky_diffuse": {
            "model_id": SKY_VISIBILITY_SOLVER_ID,
            "model_version": SKY_VISIBILITY_SOLVER_VERSION,
            "resolution": {
                **resolution.as_dict(),
                "weighting_method": SKY_WEIGHTING_METHOD,
                "receiver_evaluation": (
                    "full_polygon_directional_visibility_prepared_exact"
                    if prepared_queries is not None
                    else "full_polygon_directional_visibility_reference"
                ),
                "receiver_count": len(records),
                "directional_evaluation_count": evaluation_count,
                "directional_visibility_kernel": {
                    "model_id": first_query["beam_solver_id"],
                    "model_version": first_query["beam_solver_version"],
                },
                "acceleration_engine": (
                    {
                        "engine_id": PREPARED_DIRECTIONAL_ENGINE_ID,
                        "engine_version": PREPARED_DIRECTIONAL_ENGINE_VERSION,
                    }
                    if prepared_queries is not None
                    else None
                ),
            },
            "notes": (
                "Isotropic sky uses the full weighted upper-hemisphere dome. "
                "Horizon visibility uses a separately discretized low-elevation band."
            ),
        },
        "ground": {
            "model_id": "none",
            "model_version": "0.1",
            "resolution": {},
            "notes": "Ground obstruction is deferred to Phase 5.7.",
        },
    }

    approximation = {
        "approximation_id": "phase56_discrete_weighted_sky_dome",
        "scope": "sky_diffuse_geometry",
        "description": (
            "Continuous sky radiance visibility is numerically integrated using "
            "the explicitly configured discrete equal-solid-angle sky and horizon domes."
        ),
        "affected_entity_ids": selected,
    }

    payload = {
        "schema_name": "ShadingResult",
        "schema_version": "0.1",
        "contract_version": CONTRACT_VERSION,
        "orchestrator_manifest": {
            "orchestrator_id": SKY_SNAPSHOT_ORCHESTRATOR_ID,
            "orchestrator_version": SKY_SNAPSHOT_ORCHESTRATOR_VERSION,
        },
        "source_scene_revision_id": scene_revision_id,
        "compiled_geometry_hash": geometry_hash,
        "shading_configuration_hash": configuration_hash,
        "receiver_set_sha256": receiver_set_sha256,
        "source_execution_plan_id": source_plan_id,
        "solver_manifest": solver_manifest,
        "fidelity_level": shading_configuration["fidelity_level"],
        "receiver_granularity": shading_configuration["receiver_granularity"],
        "factor_convention": FACTOR_CONVENTION,
        "electrical_shading_scope": ELECTRICAL_SHADING_SCOPE,
        "channels": ["sky_visibility", "directional_diffuse_visibility"],
        "storage_mode": "inline",
        "record_count": len(records),
        "inline_records": records,
        "approximation_manifest": [approximation],
        "findings": [],
    }
    payload_hash = _sha256_json(payload)
    result = {
        **payload,
        "shading_result_id": f"shading-result:{payload_hash[:16]}",
        "result_payload_sha256": payload_hash,
    }
    return SkyShadingSnapshotResult(shading_result=result)
