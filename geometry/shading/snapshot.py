"""Phase-5.4 deterministic receiver-set beam shading snapshots.

This module orchestrates the Phase-5.3 single-receiver reference kernel across
an explicit receiver set or receiver IDs derived from a Phase-5.2 execution
group plan. It populates the existing Phase-5 ShadingResult contract.

Detailed projected geometry remains an optional, separate derived diagnostic
artifact and is never required for the scalar factor path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Sequence

from .beam import (
    _fallback_evidence,
    BEAM_SOLVER_ID,
    BEAM_SOLVER_VERSION,
    DEFAULT_BEAM_TOLERANCES,
    BeamShadowError,
    calculate_direct_beam_shadow,
    calculate_direct_beam_shadow_with_diagnostics,
)
from .contract import (
    CONTRACT_VERSION,
    ELECTRICAL_SHADING_SCOPE,
    FACTOR_CONVENTION,
    ShadingContractError,
    assert_geometry_aware_shading_configuration,
    normalize_product_namespace_identifier,
)
from .sky import SKY_VISIBILITY_SOLVER_ID
from .ground import GROUND_VISIBILITY_SOLVER_ID
from .prepared import (
    PREPARED_DIRECTIONAL_ENGINE_ID,
    PREPARED_DIRECTIONAL_ENGINE_VERSION,
    PreparedDirectionalError,
    PreparedDirectionalReceiver,
    calculate_prepared_direct_beam_shadow,
)


SNAPSHOT_ORCHESTRATOR_ID = "rawibumi.beam_shading_snapshot"
SNAPSHOT_ORCHESTRATOR_VERSION = "0.1"


class BeamSnapshotError(ValueError):
    """Raised when a Phase-5.4 beam snapshot cannot be evaluated safely."""


@dataclass(frozen=True)
class BeamShadingSnapshotResult:
    shading_result: dict[str, Any]
    diagnostic_artifact: dict[str, Any] | None


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalized_sun_vector(value: Sequence[float]) -> list[float]:
    if len(value) != 3:
        raise BeamSnapshotError("sun_vector_xyz must have exactly three coordinates")
    vector = [float(item) for item in value]
    if not all(math.isfinite(item) for item in vector):
        raise BeamSnapshotError("sun_vector_xyz must be finite")
    norm = math.sqrt(sum(item * item for item in vector))
    if norm <= 0.0 or not math.isfinite(norm):
        raise BeamSnapshotError("sun_vector_xyz must have non-zero finite magnitude")
    return [item / norm for item in vector]


def _normalized_timestamp(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BeamSnapshotError("timestamp must be null or a non-empty ISO-8601 string")
    text = value.strip()
    parse_value = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(parse_value)
    except ValueError as exc:
        raise BeamSnapshotError("timestamp must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BeamSnapshotError("timestamp must include an explicit timezone")
    utc = parsed.astimezone(timezone.utc)
    return utc.isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_snapshot_configuration(configuration: Mapping[str, Any]) -> None:
    try:
        assert_geometry_aware_shading_configuration(configuration)
    except ShadingContractError as exc:
        raise BeamSnapshotError(str(exc)) from exc

    beam_method = normalize_product_namespace_identifier(configuration.get("beam_method"))
    diffuse_method = normalize_product_namespace_identifier(configuration.get("diffuse_method"))
    albedo_method = normalize_product_namespace_identifier(configuration.get("albedo_method"))
    if beam_method != BEAM_SOLVER_ID:
        raise BeamSnapshotError(
            f"beam_method must be {BEAM_SOLVER_ID!r} for Phase-5.4 snapshots"
        )
    if diffuse_method not in {
        "none",
        SKY_VISIBILITY_SOLVER_ID,
    }:
        raise BeamSnapshotError(
            "beam snapshots accept diffuse_method='none' or the Phase-5.6 "
            "weighted sky solver; other diffuse methods are not executable"
        )
    if albedo_method not in {
        None,
        "none",
        GROUND_VISIBILITY_SOLVER_ID,
    }:
        raise BeamSnapshotError(
            "albedo_method must disable ground obstruction or select the explicit "
            "Phase-5.7 weighted ground solver; other ground methods are not executable"
        )

    if configuration.get("receiver_granularity") == "pv_field":
        raise BeamSnapshotError(
            "pv_field receiver granularity is not produced by the current "
            "CompiledShadingGeometry contract"
        )

    if (configuration.get("cache_policy") or {}).get("mode") == "angular_bins":
        raise BeamSnapshotError(
            "cache_policy='angular_bins' is not implemented in Phase 5.4; "
            "snapshot evaluation is exact for the supplied sun vector"
        )

    resolution = configuration.get("geometric_resolution") or {}
    for field in ("receiver_subdivision_u", "receiver_subdivision_v"):
        if field in resolution:
            value = resolution[field]
            if isinstance(value, bool) or value != 1:
                raise BeamSnapshotError(
                    f"{field} other than integer 1 is not implemented by the "
                    "Phase-5.3 polygon receiver kernel"
                )
    if "occluder_chord_tolerance_m" in resolution:
        raise BeamSnapshotError(
            "occluder_chord_tolerance_m is not consumed by the current compiled "
            "polygon-face reference kernel"
        )
    if configuration.get("model_options"):
        raise BeamSnapshotError(
            "model_options must be empty for Phase-5.4 reference snapshots; "
            "no hidden beam options are supported"
        )


def receiver_ids_from_execution_group_plan(
    execution_group_plan: Mapping[str, Any],
    *,
    execution_group_ids: Iterable[str] | None = None,
) -> list[str]:
    """Return deterministic resolved receiver IDs from selected execution groups."""
    if execution_group_plan.get("authority") != "derived_execution_only":
        raise BeamSnapshotError(
            "execution_group_plan must be a derived_execution_only artifact"
        )

    from engine.simulation.execution_groups import execution_units
    groups = {str(item.get("execution_group_id")): item for item in execution_units(execution_group_plan)}
    if execution_group_ids is None:
        selected_ids = sorted(groups)
    else:
        selected_ids = sorted(set(str(item) for item in execution_group_ids))
        unknown = [item for item in selected_ids if item not in groups]
        if unknown:
            raise BeamSnapshotError(
                "unknown execution_group_id(s): " + ", ".join(unknown)
            )

    receivers: set[str] = set()
    missing_modules: set[str] = set()
    for group_id in selected_ids:
        group = groups[group_id]
        receivers.update(str(item) for item in group.get("receiver_ids", []))
        missing_modules.update(
            str(item) for item in group.get("missing_receiver_module_ids", [])
        )

    if missing_modules:
        raise BeamSnapshotError(
            "selected execution group(s) have unresolved module receiver IDs: "
            + ", ".join(sorted(missing_modules))
        )
    if not receivers:
        raise BeamSnapshotError(
            "selected execution group(s) contain no resolved shading receivers"
        )
    return sorted(receivers)


def _resolve_receiver_ids(
    compiled_geometry: Mapping[str, Any],
    *,
    receiver_ids: Iterable[str] | None,
    execution_group_plan: Mapping[str, Any] | None,
    execution_group_ids: Iterable[str] | None,
    receiver_granularity: str,
) -> tuple[list[str], str | None]:
    if receiver_ids is not None and execution_group_plan is not None:
        raise BeamSnapshotError(
            "provide receiver_ids or execution_group_plan selection, not both"
        )
    if receiver_ids is None and execution_group_plan is None:
        raise BeamSnapshotError(
            "receiver selection must be explicit through receiver_ids or an "
            "execution_group_plan"
        )
    if execution_group_ids is not None and execution_group_plan is None:
        raise BeamSnapshotError(
            "execution_group_ids requires execution_group_plan"
        )

    source_plan_id: str | None = None
    if execution_group_plan is not None:
        plan_geometry_hash = execution_group_plan.get("compiled_geometry_hash")
        compiled_hash = compiled_geometry.get("geometry_payload_sha256")
        if plan_geometry_hash != compiled_hash:
            raise BeamSnapshotError(
                "execution group plan compiled_geometry_hash does not match "
                "the supplied CompiledShadingGeometry"
            )
        selected = receiver_ids_from_execution_group_plan(
            execution_group_plan,
            execution_group_ids=execution_group_ids,
        )
        source_plan_id = str(execution_group_plan.get("execution_plan_id") or "")
        if not source_plan_id:
            raise BeamSnapshotError("execution_group_plan lacks execution_plan_id")
    else:
        selected = sorted(set(str(item) for item in receiver_ids or []))
        if not selected:
            raise BeamSnapshotError("receiver_ids must not be empty")

    receiver_map = {
        str(item.get("receiver_id")): item
        for item in compiled_geometry.get("receivers", [])
    }
    unknown = [item for item in selected if item not in receiver_map]
    if unknown:
        raise BeamSnapshotError("unknown receiver_id(s): " + ", ".join(unknown))

    disabled = [
        item
        for item in selected
        if receiver_map[item].get("enabled") is not True
    ]
    if disabled:
        raise BeamSnapshotError(
            "disabled receiver_id(s) cannot be evaluated: " + ", ".join(disabled)
        )

    source_types = {
        str(receiver_map[item].get("source_entity_type") or "")
        for item in selected
    }
    if receiver_granularity == "module" and source_types != {"module_instance"}:
        raise BeamSnapshotError(
            "receiver_granularity='module' requires only module_instance receivers"
        )
    if receiver_granularity == "surface" and source_types != {"surface"}:
        raise BeamSnapshotError(
            "receiver_granularity='surface' requires only surface receivers"
        )
    if receiver_granularity == "mixed" and not source_types.issubset(
        {"module_instance", "surface"}
    ):
        raise BeamSnapshotError("mixed receiver selection contains unsupported type")

    return selected, source_plan_id


def _quality_flags(
    beam_result: Mapping[str, Any],
    *,
    self_shading_enabled: bool,
) -> list[str]:
    flags: list[str] = []
    status = beam_result["status"]
    if status == "no_direct_beam_sun_below_horizon":
        flags.append("sun_below_horizon")
    elif status == "no_direct_beam_receiver_backside":
        flags.append("receiver_backside")
    else:
        factor = float(beam_result["beam_visibility_factor"])
        if factor == 1.0:
            flags.append("receiver_clear")
        elif factor == 0.0:
            flags.append("receiver_fully_shaded")
        else:
            flags.append("receiver_partially_shaded")
    if not self_shading_enabled:
        flags.append("self_shading_disabled")
    flags.extend(beam_result.get("quality_flags", []))
    return flags


def evaluate_beam_shading_snapshot(
    compiled_geometry: Mapping[str, Any],
    *,
    shading_configuration: Mapping[str, Any],
    sun_vector_xyz: Sequence[float],
    receiver_ids: Iterable[str] | None = None,
    execution_group_plan: Mapping[str, Any] | None = None,
    execution_group_ids: Iterable[str] | None = None,
    timestamp: str | None = None,
    include_diagnostics: bool = False,
    prepared_queries: Mapping[str, PreparedDirectionalReceiver] | None = None,
) -> BeamShadingSnapshotResult:
    """Evaluate one direct-beam sun state across an explicit receiver set."""
    _validate_snapshot_configuration(shading_configuration)

    geometry_hash = str(compiled_geometry.get("geometry_payload_sha256") or "")
    if (
        len(geometry_hash) != 64
        or any(character not in "0123456789abcdef" for character in geometry_hash)
    ):
        raise BeamSnapshotError(
            "compiled geometry must provide a lowercase SHA-256 geometry_payload_sha256"
        )
    scene_revision_id = str(
        compiled_geometry.get("source_scene_revision_id") or ""
    )
    if not scene_revision_id:
        raise BeamSnapshotError(
            "compiled geometry must retain source_scene_revision_id"
        )

    normalized_timestamp = _normalized_timestamp(timestamp)
    normalized_sun = _normalized_sun_vector(sun_vector_xyz)
    selected_receivers, source_execution_plan_id = _resolve_receiver_ids(
        compiled_geometry,
        receiver_ids=receiver_ids,
        execution_group_plan=execution_group_plan,
        execution_group_ids=execution_group_ids,
        receiver_granularity=str(shading_configuration["receiver_granularity"]),
    )
    receiver_set_sha256 = _sha256_json(selected_receivers)
    shading_configuration_hash = _sha256_json(dict(shading_configuration))
    sun_state_sha256 = _sha256_json(
        {
            "sun_vector_xyz": normalized_sun,
            "timestamp": normalized_timestamp,
        }
    )

    records: list[dict[str, Any]] = []
    diagnostic_entries: list[dict[str, Any]] = []
    first_beam_result: dict[str, Any] | None = None
    self_shading_enabled = bool(
        shading_configuration["self_shading_enabled"]
    )

    below_global_horizon_short_circuit = (
        not include_diagnostics
        and normalized_sun[2] <= DEFAULT_BEAM_TOLERANCES.horizon_z
    )
    geometry_query_count = 0

    parallel_results = None
    if (not include_diagnostics and not below_global_horizon_short_circuit
            and hasattr(prepared_queries, "evaluate")):
        try:
            parallel_results = prepared_queries.evaluate(
                "beam", selected_receivers, source=normalized_sun,
            )
        except RuntimeError as exc:
            raise BeamSnapshotError(
                f"beam worker evaluation failed; timestamp={normalized_timestamp}: {exc}"
            ) from exc

    for receiver_id in selected_receivers:
        try:
            reused_global_shortcut = (
                below_global_horizon_short_circuit
                and first_beam_result is not None
            )
            if reused_global_shortcut:
                beam_result = first_beam_result
            elif parallel_results is not None:
                beam_result = parallel_results[receiver_id]
            elif include_diagnostics:
                beam_result, diagnostic = (
                    calculate_direct_beam_shadow_with_diagnostics(
                        compiled_geometry,
                        receiver_id=receiver_id,
                        sun_vector_xyz=normalized_sun,
                        self_shading_enabled=self_shading_enabled,
                    )
                )
                diagnostic_entries.append(
                    {
                        "receiver_id": receiver_id,
                        "status": beam_result["status"],
                        "beam_visibility_factor": beam_result[
                            "beam_visibility_factor"
                        ],
                        "beam_shaded_fraction": beam_result[
                            "beam_shaded_fraction"
                        ],
                        "shaded_area_m2": beam_result["shaded_area_m2"],
                        "contributing_occluder_ids": beam_result[
                            "contributing_occluder_ids"
                        ],
                        **diagnostic,
                    }
                )
            else:
                prepared = (
                    prepared_queries.get(receiver_id)
                    if prepared_queries is not None
                    else None
                )
                if prepared is not None:
                    beam_result = calculate_prepared_direct_beam_shadow(
                        prepared,
                        sun_vector_xyz=normalized_sun,
                    )
                else:
                    beam_result = calculate_direct_beam_shadow(
                        compiled_geometry,
                        receiver_id=receiver_id,
                        sun_vector_xyz=normalized_sun,
                        self_shading_enabled=self_shading_enabled,
                    )
            if not reused_global_shortcut:
                geometry_query_count += 1
        except (BeamShadowError, PreparedDirectionalError) as exc:
            raise BeamSnapshotError(
                f"beam evaluation failed for {receiver_id}; timestamp={normalized_timestamp}: {exc}"
            ) from exc

        if first_beam_result is None:
            first_beam_result = beam_result

        records.append(
            {
                "receiver_id": receiver_id,
                **{key: value for key, value in _fallback_evidence(
                    beam_result, timestamp=normalized_timestamp, channel="beam",
                ).items() if key != "quality_flags"},
                "timestamp": normalized_timestamp,
                "sun_vector_xyz": beam_result["sun_vector_xyz"],
                "beam_visibility_factor": beam_result[
                    "beam_visibility_factor"
                ],
                "sky_visibility_factor": None,
                "ground_visibility_factor": None,
                "quality_flags": _quality_flags(
                    beam_result,
                    self_shading_enabled=self_shading_enabled,
                ),
            }
        )

    if first_beam_result is None:
        raise BeamSnapshotError("receiver selection produced no evaluations")

    solver_manifest = {
        "beam": {
            "model_id": BEAM_SOLVER_ID,
            "model_version": BEAM_SOLVER_VERSION,
            "resolution": {
                "tolerances": first_beam_result["tolerances"],
                "geometry_engine": first_beam_result["geometry_engine"],
                "receiver_evaluation": (
                    "full_polygon_prepared_exact"
                    if prepared_queries is not None and not include_diagnostics
                    else "full_polygon_reference"
                ),
                "receiver_count": len(records),
                "receiver_geometry_query_count": geometry_query_count,
                "global_below_horizon_short_circuit": (
                    below_global_horizon_short_circuit
                ),
                "acceleration_engine": (
                    {
                        "engine_id": PREPARED_DIRECTIONAL_ENGINE_ID,
                        "engine_version": PREPARED_DIRECTIONAL_ENGINE_VERSION,
                    }
                    if prepared_queries is not None and not include_diagnostics
                    else None
                ),
            },
            "notes": (
                "Phase-5.3 polygon-projection physics. cache_policy='exact' may "
                "reuse direction-independent prepared receiver/occluder geometry; "
                "diagnostic execution remains on the reference path."
            ),
        },
        "sky_diffuse": {
            "model_id": "none",
            "model_version": "0.1",
            "resolution": {},
            "notes": "Diffuse sky obstruction is not modeled in Phase 5.4.",
        },
        "ground": {
            "model_id": "none",
            "model_version": "0.1",
            "resolution": {},
            "notes": "Ground obstruction is not modeled in Phase 5.4.",
        },
    }

    result_payload = {
        "schema_name": "ShadingResult",
        "orchestrator_manifest": {
            "orchestrator_id": SNAPSHOT_ORCHESTRATOR_ID,
            "orchestrator_version": SNAPSHOT_ORCHESTRATOR_VERSION,
        },
        "schema_version": "0.1",
        "contract_version": CONTRACT_VERSION,
        "source_scene_revision_id": scene_revision_id,
        "compiled_geometry_hash": geometry_hash,
        "shading_configuration_hash": shading_configuration_hash,
        "receiver_set_sha256": receiver_set_sha256,
        "sun_state_sha256": sun_state_sha256,
        "source_execution_plan_id": source_execution_plan_id,
        "solver_manifest": solver_manifest,
        "fidelity_level": shading_configuration["fidelity_level"],
        "receiver_granularity": shading_configuration["receiver_granularity"],
        "factor_convention": FACTOR_CONVENTION,
        "electrical_shading_scope": ELECTRICAL_SHADING_SCOPE,
        "channels": ["beam_visibility"],
        "storage_mode": "inline",
        "record_count": len(records),
        "inline_records": records,
        "approximation_manifest": [],
        "findings": [],
    }
    result_payload_sha256 = _sha256_json(result_payload)
    shading_result = {
        **result_payload,
        "shading_result_id": f"shading-result:{result_payload_sha256[:16]}",
        "result_payload_sha256": result_payload_sha256,
    }

    diagnostic_artifact: dict[str, Any] | None = None
    if include_diagnostics:
        diagnostic_payload = {
            "schema_name": "BeamShadowDiagnosticArtifact",
            "orchestrator_id": SNAPSHOT_ORCHESTRATOR_ID,
            "orchestrator_version": SNAPSHOT_ORCHESTRATOR_VERSION,
            "schema_version": "0.1",
            "authority": "derived_diagnostic_only",
            "editable": False,
            "shading_result_id": shading_result["shading_result_id"],
            "compiled_geometry_hash": geometry_hash,
            "shading_configuration_hash": shading_configuration_hash,
            "receiver_set_sha256": receiver_set_sha256,
            "sun_state_sha256": sun_state_sha256,
            "source_execution_plan_id": source_execution_plan_id,
            "solver_id": BEAM_SOLVER_ID,
            "solver_version": BEAM_SOLVER_VERSION,
            "sun_vector_xyz": first_beam_result["sun_vector_xyz"],
            "timestamp": normalized_timestamp,
            "self_shading_enabled": self_shading_enabled,
            "receiver_count": len(diagnostic_entries),
            "entries": diagnostic_entries,
        }
        diagnostic_payload_sha256 = _sha256_json(diagnostic_payload)
        diagnostic_artifact = {
            **diagnostic_payload,
            "diagnostic_artifact_id": (
                f"beam-diagnostic:{diagnostic_payload_sha256[:16]}"
            ),
            "diagnostic_payload_sha256": diagnostic_payload_sha256,
        }

    return BeamShadingSnapshotResult(
        shading_result=shading_result,
        diagnostic_artifact=diagnostic_artifact,
    )
