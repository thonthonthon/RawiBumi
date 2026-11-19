"""Phase-5 geometry-aware fixed-tilt execution.

Phase 5.5 integrated direct-beam receiver visibility into the homogeneous
fixed-tilt numerical chain. Phase 5.6 extends the same path with component-aware
sky diffuse obstruction:

- isotropic diffuse uses weighted full-sky visibility;
- circumsolar diffuse uses the current sun-direction visibility;
- horizon diffuse uses a separately weighted low-elevation horizon band;
- ground-reflected POA remains unobstructed.

Receiver-level geometric factors are retained even though the current
homogeneous electrical worker consumes receiver-area-weighted group factors.
Electrical mismatch remains explicitly not modeled.
"""

from __future__ import annotations

from geometry.shading.beam import _fallback_totals

import hashlib
import json
from typing import Any, Callable, Mapping

import pandas as pd

from engine.irradiance import (
    BEAM_POA_MODIFIER_ID,
    SKY_DIFFUSE_POA_MODIFIER_ID,
    GROUND_POA_MODIFIER_ID,
    SIGNED_HORIZON_POLICY,
    PlaneOfArrayResult,
    apply_beam_visibility_to_poa,
    apply_sky_diffuse_visibility_to_poa,
    apply_ground_visibility_to_poa,
)
from engine.solar import SolarPositionResult
from geometry.shading import (
    BEAM_SOLVER_ID,
    SKY_VISIBILITY_SOLVER_ID,
    GROUND_VISIBILITY_SOLVER_ID,
    normalize_product_namespace_identifier,
    evaluate_beam_shading_snapshot,
    evaluate_sky_shading_snapshot,
    evaluate_ground_shading_snapshot,
    sun_vector_from_azimuth_elevation,
    ShadingAccelerationError,
    build_shading_acceleration_context,
)
from weather.core import CanonicalWeather

from .temporal import TemporalExecutionContext
from .unshaded import (
    FixedTiltPOAPostprocessResult,
    UnshadedFixedTiltConfiguration,
    UnshadedFixedTiltSimulationResult,
    _run_fixed_tilt,
)


BEAM_VISIBILITY_AGGREGATION_METHOD_ID = (
    "beam_visibility.execution_group_area_weighted_mean.v0.1"
)
DIFFUSE_VISIBILITY_AGGREGATION_METHOD_ID = (
    "diffuse_visibility.execution_group_area_weighted_mean.v0.1"
)
GROUND_VISIBILITY_AGGREGATION_METHOD_ID = (
    "ground_visibility.execution_group_area_weighted_mean.v0.1"
)

GEOMETRY_AWARE_FIXED_TILT_SCOPE = (
    "fixed_tilt_beam_shaded_homogeneous_single_inverter.v0.1"
)
GEOMETRY_AWARE_BEAM_SKY_FIXED_TILT_SCOPE = (
    "fixed_tilt_beam_sky_shaded_homogeneous_single_inverter.v0.1"
)
GEOMETRY_AWARE_BEAM_SKY_MODEL_ID = (
    "rawibumi.geometry_near_shading.beam_plus_component_diffuse.v0.1"
)
GEOMETRY_AWARE_BEAM_SKY_GROUND_FIXED_TILT_SCOPE = (
    "fixed_tilt_beam_sky_ground_shaded_homogeneous_single_inverter.v0.1"
)
GEOMETRY_AWARE_BEAM_SKY_GROUND_MODEL_ID = (
    "rawibumi.geometry_near_shading.beam_sky_ground.v0.1"
)


class BeamVerticalSliceError(ValueError):
    """Raised when geometry-aware runtime inputs violate the supported boundary."""


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_execution_plan(
    execution_group_plan: Mapping[str, Any],
    execution_group_id: str | None = None,
) -> Mapping[str, Any]:
    if execution_group_id is not None:
        if execution_group_plan.get("execution_class") not in {
            "homogeneous_single_group", "separable_multi_group", "mixed_orientation_coupled",
        }:
            raise BeamVerticalSliceError("geometry execution requires separable groups")
        from .execution_groups import execution_units
        matches = [g for g in execution_units(execution_group_plan)
                   if g["execution_group_id"] == execution_group_id]
        if len(matches) != 1:
            raise BeamVerticalSliceError("execution group is unresolved")
        group = matches[0]
        if group.get("missing_receiver_module_ids") or not group.get("receiver_ids"):
            raise BeamVerticalSliceError("geometry execution requires resolved group receivers")
        return group
    if execution_group_plan.get("execution_class") != "homogeneous_single_group":
        raise BeamVerticalSliceError(
            "geometry-aware fixed-tilt execution requires "
            "execution_class='homogeneous_single_group'"
        )
    groups = execution_group_plan.get("groups") or []
    if len(groups) != 1:
        raise BeamVerticalSliceError(
            "geometry-aware fixed-tilt execution requires exactly one group"
        )
    group = groups[0]
    receiver_ids = group.get("receiver_ids") or []
    missing = group.get("missing_receiver_module_ids") or []
    if missing:
        raise BeamVerticalSliceError(
            "geometry-aware execution requires resolved module receivers for "
            "every active module: "
            + ", ".join(sorted(str(item) for item in missing))
        )
    if not receiver_ids:
        raise BeamVerticalSliceError(
            "geometry-aware execution group contains no resolved receiver IDs"
        )
    return group


def _receiver_area_map(
    compiled_geometry: Mapping[str, Any],
    receiver_ids: list[str],
) -> dict[str, float]:
    receivers = {
        str(item.get("receiver_id")): item
        for item in compiled_geometry.get("receivers", [])
    }
    result: dict[str, float] = {}
    for receiver_id in receiver_ids:
        receiver = receivers.get(receiver_id)
        if receiver is None:
            raise BeamVerticalSliceError(
                "execution-group receiver is missing from compiled geometry: "
                f"{receiver_id}"
            )
        if receiver.get("source_entity_type") != "module_instance":
            raise BeamVerticalSliceError(
                "homogeneous electrical aggregation requires module_instance receivers"
            )
        area = float(receiver.get("area_m2") or 0.0)
        if area <= 0.0:
            raise BeamVerticalSliceError(
                f"receiver area must be positive: {receiver_id}"
            )
        result[receiver_id] = area
    return result


def _bounded_area_weighted(
    values: Mapping[str, float],
    areas: Mapping[str, float],
    *,
    name: str,
) -> float:
    if set(values) != set(areas):
        raise BeamVerticalSliceError(
            f"{name} receiver set does not reconcile with execution group"
        )
    denominator = sum(float(areas[key]) for key in sorted(areas))
    if denominator <= 0.0:
        raise BeamVerticalSliceError(f"{name} area denominator must be positive")
    numerator = sum(
        float(areas[key]) * float(values[key])
        for key in sorted(values)
    )
    factor = numerator / denominator
    tolerance = 1e-12
    if factor < -tolerance or factor > 1.0 + tolerance:
        raise BeamVerticalSliceError(
            f"area-weighted {name} visibility escaped [0, 1] beyond tolerance"
        )
    return min(1.0, max(0.0, factor))


def _geometry_poa_postprocessor(
    *,
    compiled_geometry: Mapping[str, Any],
    execution_group_plan: Mapping[str, Any],
    shading_configuration: Mapping[str, Any],
    receiver_factor_chunk_consumer: Callable[[pd.DataFrame], None] | None = None,
    retain_receiver_factors: bool = True,
    receiver_factor_chunk_rows: int = 8192,
    execution_group_id: str | None = None,
    shared_acceleration_context=None,
):
    group = _validate_execution_plan(execution_group_plan, execution_group_id)
    selected_group_ids = [execution_group_id] if execution_group_id is not None else None
    receiver_ids = sorted(str(item) for item in group["receiver_ids"])

    if isinstance(receiver_factor_chunk_rows, bool) or int(receiver_factor_chunk_rows) < 1:
        raise BeamVerticalSliceError(
            "receiver_factor_chunk_rows must be a positive integer"
        )
    receiver_factor_chunk_rows = int(receiver_factor_chunk_rows)

    if not retain_receiver_factors and receiver_factor_chunk_consumer is None:
        raise BeamVerticalSliceError(
            "receiver factors cannot be discarded: retain_receiver_factors=false "
            "requires an explicit receiver_factor_chunk_consumer"
        )

    geometry_hash = str(compiled_geometry.get("geometry_payload_sha256") or "")
    if execution_group_plan.get("compiled_geometry_hash") != geometry_hash:
        raise BeamVerticalSliceError(
            "execution group plan and CompiledShadingGeometry hash do not match"
        )

    diffuse_method = normalize_product_namespace_identifier(shading_configuration.get("diffuse_method"))
    if diffuse_method not in {"none", SKY_VISIBILITY_SOLVER_ID}:
        raise BeamVerticalSliceError(
            "geometry-aware fixed-tilt runtime supports diffuse_method='none' "
            f"or {SKY_VISIBILITY_SOLVER_ID!r}"
        )
    sky_enabled = diffuse_method == SKY_VISIBILITY_SOLVER_ID

    albedo_method = normalize_product_namespace_identifier(shading_configuration.get("albedo_method"))
    if albedo_method not in {None, "none", GROUND_VISIBILITY_SOLVER_ID}:
        raise BeamVerticalSliceError(
            "geometry-aware fixed-tilt runtime supports albedo_method null, "
            "'none', or the Phase-5.7 weighted ground solver"
        )
    ground_enabled = albedo_method == GROUND_VISIBILITY_SOLVER_ID

    areas = _receiver_area_map(compiled_geometry, receiver_ids)
    total_area = sum(areas.values())
    receiver_set_sha256 = _sha256_json(receiver_ids)

    try:
        acceleration_context = shared_acceleration_context or build_shading_acceleration_context(
            compiled_geometry,
            shading_configuration=shading_configuration,
            receiver_ids=receiver_ids,
            source_execution_plan_id=str(
                execution_group_plan["execution_plan_id"]
            ),
            source_execution_plan_payload_sha256=str(
                execution_group_plan["execution_plan_payload_sha256"]
            ),
        )
        prepared_queries = acceleration_context.prepared_query_map()
    except ShadingAccelerationError as exc:
        raise BeamVerticalSliceError(
            f"shading acceleration initialization failed: {exc}"
        ) from exc

    static_sky_snapshot: dict[str, Any] | None = None
    static_sky_records: dict[str, dict[str, Any]] = {}
    group_sky_visibility: float | None = None
    group_horizon_visibility: float | None = None

    static_ground_snapshot: dict[str, Any] | None = None
    static_ground_records: dict[str, dict[str, Any]] = {}
    group_ground_visibility: float | None = None

    if sky_enabled:
        static_sky_snapshot = acceleration_context.get_static_result(
            "sky_visibility"
        )
        if static_sky_snapshot is None:
            static_sky_snapshot = evaluate_sky_shading_snapshot(
                compiled_geometry,
                shading_configuration=shading_configuration,
                execution_group_plan=execution_group_plan,
                prepared_queries=prepared_queries,
            ).shading_result
            acceleration_context.put_static_result(
                "sky_visibility",
                static_sky_snapshot,
            )
        static_sky_records = {
            str(item["receiver_id"]): item
            for item in static_sky_snapshot["inline_records"]
        }
        sky_values = {
            receiver_id: float(
                static_sky_records[receiver_id]["sky_visibility_factor"]
            )
            for receiver_id in receiver_ids
        }
        horizon_values = {
            receiver_id: float(
                static_sky_records[receiver_id][
                    "directional_diffuse_visibility"
                ]["horizon"]
            )
            for receiver_id in receiver_ids
        }
        group_sky_visibility = _bounded_area_weighted(
            sky_values,
            areas,
            name="sky",
        )
        group_horizon_visibility = _bounded_area_weighted(
            horizon_values,
            areas,
            name="horizon",
        )

    if ground_enabled:
        static_ground_snapshot = acceleration_context.get_static_result(
            "ground_visibility"
        )
        if static_ground_snapshot is None:
            static_ground_snapshot = evaluate_ground_shading_snapshot(
                compiled_geometry,
                shading_configuration=shading_configuration,
                execution_group_plan=execution_group_plan,
                prepared_queries=prepared_queries,
            ).shading_result
            acceleration_context.put_static_result(
                "ground_visibility",
                static_ground_snapshot,
            )
        static_ground_records = {
            str(item["receiver_id"]): item
            for item in static_ground_snapshot["inline_records"]
        }
        ground_values = {
            receiver_id: float(
                static_ground_records[receiver_id]["ground_visibility_factor"]
            )
            for receiver_id in receiver_ids
        }
        group_ground_visibility = _bounded_area_weighted(
            ground_values,
            areas,
            name="ground",
        )

    def process(
        poa: PlaneOfArrayResult,
        solar: SolarPositionResult,
        temporal: TemporalExecutionContext,
    ) -> FixedTiltPOAPostprocessResult:
        if not poa.frame.index.equals(solar.frame.index):
            raise BeamVerticalSliceError("POA and solar intervals do not align")
        if not poa.frame.index.equals(temporal.weather.series.index):
            raise BeamVerticalSliceError(
                "POA and working weather intervals do not align"
            )

        group_beam_factors: list[float] = []
        receiver_rows: list[dict[str, Any]] = []
        retained_receiver_factor_chunks: list[pd.DataFrame] = []
        receiver_factor_row_count = 0
        max_buffered_receiver_factor_rows = 0
        receiver_factor_chunk_count = 0
        beam_snapshot_manifest: list[dict[str, Any]] = []
        fallback_events = [
            event for static in (static_sky_snapshot, static_ground_snapshot)
            if static is not None for record in static["inline_records"]
            if record["receiver_id"] in receiver_ids
            for event in record.get("shadow_union_precision_fallback_events", [])
        ]

        def flush_receiver_rows(*, force: bool = False) -> None:
            nonlocal receiver_factor_row_count
            nonlocal max_buffered_receiver_factor_rows
            nonlocal receiver_factor_chunk_count
            if not receiver_rows:
                return
            max_buffered_receiver_factor_rows = max(
                max_buffered_receiver_factor_rows,
                len(receiver_rows),
            )
            if not force and len(receiver_rows) < receiver_factor_chunk_rows:
                return
            chunk = pd.DataFrame(receiver_rows)
            chunk = chunk.sort_values(
                ["interval_start", "receiver_id"],
                kind="stable",
            ).reset_index(drop=True)
            if receiver_factor_chunk_consumer is not None:
                receiver_factor_chunk_consumer(chunk)
            if retain_receiver_factors:
                retained_receiver_factor_chunks.append(chunk)
            receiver_factor_row_count += len(chunk)
            receiver_factor_chunk_count += 1
            receiver_rows.clear()

        for interval_start in poa.frame.index:
            solar_row = solar.frame.loc[interval_start]
            sun_vector = sun_vector_from_azimuth_elevation(
                float(solar_row["solar_azimuth_deg"]),
                float(solar_row["solar_apparent_elevation_deg"]),
            )
            evaluation_time = pd.Timestamp(solar_row["evaluation_time"])
            snapshot = evaluate_beam_shading_snapshot(
                compiled_geometry,
                shading_configuration=shading_configuration,
                sun_vector_xyz=sun_vector,
                execution_group_plan=execution_group_plan,
                execution_group_ids=selected_group_ids,
                timestamp=evaluation_time.isoformat(),
                include_diagnostics=False,
                prepared_queries=prepared_queries,
            ).shading_result

            beam_values: dict[str, float] = {}
            seen: set[str] = set()
            for record in snapshot["inline_records"]:
                receiver_id = str(record["receiver_id"])
                if receiver_id not in areas:
                    raise BeamVerticalSliceError(
                        "beam snapshot returned a receiver outside the execution group"
                    )
                factor = float(record["beam_visibility_factor"])
                beam_values[receiver_id] = factor
                seen.add(receiver_id)

                row = {
                    "interval_start": interval_start,
                    "evaluation_time": evaluation_time,
                    "receiver_id": receiver_id,
                    "receiver_area_m2": areas[receiver_id],
                    "beam_visibility_factor": factor,
                    "quality_flags_json": json.dumps(
                        list(record["quality_flags"]),
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                    "shading_result_id": snapshot["shading_result_id"],
                }

                if sky_enabled:
                    sky_record = static_sky_records[receiver_id]
                    combined_flags = sorted(
                        set(record["quality_flags"])
                        | set(sky_record["quality_flags"])
                    )
                    row.update(
                        {
                            "sky_visibility_factor": float(
                                sky_record["sky_visibility_factor"]
                            ),
                            "circumsolar_visibility_factor": factor,
                            "horizon_visibility_factor": float(
                                sky_record["directional_diffuse_visibility"][
                                    "horizon"
                                ]
                            ),
                            "quality_flags_json": json.dumps(
                                combined_flags,
                                separators=(",", ":"),
                                ensure_ascii=False,
                            ),
                            "sky_shading_result_id": static_sky_snapshot[
                                "shading_result_id"
                            ],
                        }
                    )
                if ground_enabled:
                    ground_record = static_ground_records[receiver_id]
                    combined_flags = sorted(
                        set(json.loads(row["quality_flags_json"]))
                        | set(ground_record["quality_flags"])
                    )
                    row.update(
                        {
                            "ground_visibility_factor": float(
                                ground_record["ground_visibility_factor"]
                            ),
                            "quality_flags_json": json.dumps(
                                combined_flags,
                                separators=(",", ":"),
                                ensure_ascii=False,
                            ),
                            "ground_shading_result_id": static_ground_snapshot[
                                "shading_result_id"
                            ],
                        }
                    )
                receiver_rows.append(row)

            if seen != set(receiver_ids):
                raise BeamVerticalSliceError(
                    "beam snapshot receiver set does not reconcile with execution group"
                )

            group_factor = _bounded_area_weighted(
                beam_values,
                areas,
                name="beam",
            )
            group_beam_factors.append(group_factor)
            fallback_events.extend(
                event for record in snapshot["inline_records"]
                for event in record.get("shadow_union_precision_fallback_events", [])
            )
            beam_snapshot_manifest.append(
                {
                    "interval_start": interval_start.isoformat(),
                    "evaluation_time": evaluation_time.isoformat(),
                    "shading_result_id": snapshot["shading_result_id"],
                    "result_payload_sha256": snapshot["result_payload_sha256"],
                    "sun_state_sha256": snapshot["sun_state_sha256"],
                }
            )
            flush_receiver_rows()

        flush_receiver_rows(force=True)

        beam_series = pd.Series(
            group_beam_factors,
            index=poa.frame.index,
            dtype=float,
            name="beam_visibility_factor_group",
        )
        shaded_poa = apply_beam_visibility_to_poa(
            poa,
            beam_series,
            aggregation_method_id=BEAM_VISIBILITY_AGGREGATION_METHOD_ID,
            aggregation_metadata={
                "execution_group_id": group["execution_group_id"],
                "receiver_count": len(receiver_ids),
                "receiver_set_sha256": receiver_set_sha256,
                "receiver_area_total_m2": total_area,
                "weight_basis": "compiled_receiver_area_m2",
            },
        )

        if sky_enabled:
            assert group_sky_visibility is not None
            assert group_horizon_visibility is not None
            shaded_poa = apply_sky_diffuse_visibility_to_poa(
                shaded_poa,
                sky_visibility_factor=group_sky_visibility,
                circumsolar_visibility_factor=beam_series,
                horizon_visibility_factor=group_horizon_visibility,
                aggregation_method_id=DIFFUSE_VISIBILITY_AGGREGATION_METHOD_ID,
                aggregation_metadata={
                    "execution_group_id": group["execution_group_id"],
                    "receiver_count": len(receiver_ids),
                    "receiver_set_sha256": receiver_set_sha256,
                    "receiver_area_total_m2": total_area,
                    "weight_basis": "compiled_receiver_area_m2",
                    "sky_shading_result_id": static_sky_snapshot[
                        "shading_result_id"
                    ],
                    "sky_shading_result_payload_sha256": static_sky_snapshot[
                        "result_payload_sha256"
                    ],
                    "circumsolar_visibility_source": (
                        "same current-sun receiver visibility as direct beam"
                    ),
                    "horizon_policy": SIGNED_HORIZON_POLICY,
                },
            )

        if ground_enabled:
            assert group_ground_visibility is not None
            shaded_poa = apply_ground_visibility_to_poa(
                shaded_poa,
                group_ground_visibility,
                aggregation_method_id=GROUND_VISIBILITY_AGGREGATION_METHOD_ID,
                aggregation_metadata={
                    "execution_group_id": group["execution_group_id"],
                    "receiver_count": len(receiver_ids),
                    "receiver_set_sha256": receiver_set_sha256,
                    "receiver_area_total_m2": total_area,
                    "weight_basis": "compiled_receiver_area_m2",
                    "ground_shading_result_id": static_ground_snapshot[
                        "shading_result_id"
                    ],
                    "ground_shading_result_payload_sha256": static_ground_snapshot[
                        "result_payload_sha256"
                    ],
                    "source_model": (
                        "existing_uniform_lambertian_scalar_albedo_poa_component"
                    ),
                },
            )

        if retain_receiver_factors:
            if not retained_receiver_factor_chunks:
                raise BeamVerticalSliceError(
                    "receiver-factor retention produced no chunks"
                )
            receiver_factors = pd.concat(
                retained_receiver_factor_chunks,
                ignore_index=True,
            )
        else:
            receiver_factors = None

        metadata: dict[str, Any] = {
            "model_id": (
                GEOMETRY_AWARE_BEAM_SKY_GROUND_MODEL_ID
                if ground_enabled
                else (
                    GEOMETRY_AWARE_BEAM_SKY_MODEL_ID
                    if sky_enabled
                    else BEAM_POA_MODIFIER_ID
                )
            ),
            "beam_poa_modifier_id": BEAM_POA_MODIFIER_ID,
            "beam_solver_id": BEAM_SOLVER_ID,
            "compiled_geometry_hash": geometry_hash,
            "execution_plan_id": execution_group_plan["execution_plan_id"],
            "execution_plan_payload_sha256": execution_group_plan[
                "execution_plan_payload_sha256"
            ],
            "execution_group_id": group["execution_group_id"],
            "receiver_set_sha256": receiver_set_sha256,
            "receiver_count": len(receiver_ids),
            "receiver_area_total_m2": total_area,
            "aggregation_method_id": BEAM_VISIBILITY_AGGREGATION_METHOD_ID,
            "aggregation_formula": (
                "sum(receiver_area_m2 * beam_visibility_factor) / "
                "sum(receiver_area_m2)"
            ),
            "electrical_shading_scope": "not_modeled",
            "electrical_approximation": (
                "receiver-level geometric visibility is area-weighted to "
                "homogeneous execution-group component modifiers before the "
                "existing electrical model"
            ),
            "solar_direction_source": (
                "canonical NREL SPA solar_azimuth_deg + "
                "solar_apparent_elevation_deg"
            ),
            **_fallback_totals(fallback_events),
            "snapshot_count": len(beam_snapshot_manifest),
            "snapshot_manifest_sha256": _sha256_json(beam_snapshot_manifest),
            "receiver_factor_rows": receiver_factor_row_count,
            "diffuse_method": diffuse_method,
            "albedo_method": albedo_method,
            "sun_sampling_policy": (
                "canonical_simulation_solar_evaluation_timestamps"
            ),
            "sun_position_resolution_seconds": shading_configuration.get(
                "sun_position_resolution_seconds"
            ),
            "shading_acceleration": acceleration_context.manifest(),
            "shading_cache_manifest": acceleration_context.cache_manifest(),
        }

        if sky_enabled:
            metadata.update(
                {
                    "sky_diffuse_poa_modifier_id": SKY_DIFFUSE_POA_MODIFIER_ID,
                    "sky_visibility_solver_id": SKY_VISIBILITY_SOLVER_ID,
                    "diffuse_aggregation_method_id": (
                        DIFFUSE_VISIBILITY_AGGREGATION_METHOD_ID
                    ),
                    "diffuse_aggregation_formula": (
                        "sum(receiver_area_m2 * component_visibility_factor) / "
                        "sum(receiver_area_m2)"
                    ),
                    "group_sky_visibility_factor": group_sky_visibility,
                    "group_horizon_visibility_factor": group_horizon_visibility,
                    "circumsolar_visibility_policy": (
                        "reuse current sun-direction beam visibility"
                    ),
                    "horizon_signed_component_policy": SIGNED_HORIZON_POLICY,
                    "sky_shading_result_id": static_sky_snapshot[
                        "shading_result_id"
                    ],
                    "sky_shading_result_payload_sha256": static_sky_snapshot[
                        "result_payload_sha256"
                    ],
                    "sky_solver_manifest": static_sky_snapshot[
                        "solver_manifest"
                    ]["sky_diffuse"],
                }
            )

        if ground_enabled:
            metadata.update(
                {
                    "ground_poa_modifier_id": GROUND_POA_MODIFIER_ID,
                    "ground_visibility_solver_id": GROUND_VISIBILITY_SOLVER_ID,
                    "ground_aggregation_method_id": (
                        GROUND_VISIBILITY_AGGREGATION_METHOD_ID
                    ),
                    "ground_aggregation_formula": (
                        "sum(receiver_area_m2 * ground_visibility_factor) / "
                        "sum(receiver_area_m2)"
                    ),
                    "group_ground_visibility_factor": group_ground_visibility,
                    "ground_source_model": (
                        "existing_uniform_lambertian_scalar_albedo_poa_component"
                    ),
                    "ground_shading_result_id": static_ground_snapshot[
                        "shading_result_id"
                    ],
                    "ground_shading_result_payload_sha256": static_ground_snapshot[
                        "result_payload_sha256"
                    ],
                    "ground_solver_manifest": static_ground_snapshot[
                        "solver_manifest"
                    ]["ground"],
                }
            )

        metadata["execution_telemetry"] = {
            "shading_acceleration": acceleration_context.metrics(),
            "receiver_factor_pipeline": {
                "retained_in_memory": bool(retain_receiver_factors),
                "stream_consumer_enabled": receiver_factor_chunk_consumer is not None,
                "configured_chunk_rows": receiver_factor_chunk_rows,
                "chunk_count": receiver_factor_chunk_count,
                "max_buffered_rows": max_buffered_receiver_factor_rows,
                "row_count": receiver_factor_row_count,
            },
        }
        return FixedTiltPOAPostprocessResult(
            poa=shaded_poa,
            metadata=metadata,
            receiver_factors=receiver_factors,
        )

    return process


def _run_geometry_fixed_tilt(
    weather: CanonicalWeather,
    *,
    config: UnshadedFixedTiltConfiguration,
    compiled_geometry: Mapping[str, Any],
    execution_group_plan: Mapping[str, Any],
    shading_configuration: Mapping[str, Any],
    execution_scope: str,
    receiver_factor_chunk_consumer: Callable[[pd.DataFrame], None] | None = None,
    retain_receiver_factors: bool = True,
    receiver_factor_chunk_rows: int = 8192,
) -> UnshadedFixedTiltSimulationResult:
    beam_method = normalize_product_namespace_identifier(shading_configuration.get("beam_method"))
    albedo_method = normalize_product_namespace_identifier(shading_configuration.get("albedo_method"))
    if beam_method != BEAM_SOLVER_ID:
        raise BeamVerticalSliceError(
            f"beam_method must be {BEAM_SOLVER_ID!r}"
        )
    if albedo_method not in {
        None,
        "none",
        GROUND_VISIBILITY_SOLVER_ID,
    normalize_product_namespace_identifier,
    }:
        raise BeamVerticalSliceError(
            "unsupported geometry-aware albedo/ground obstruction method"
        )

    group = _validate_execution_plan(execution_group_plan)
    with build_shading_acceleration_context(
        compiled_geometry,
        shading_configuration=shading_configuration,
        receiver_ids=group["receiver_ids"],
        source_execution_plan_id=str(execution_group_plan["execution_plan_id"]),
        source_execution_plan_payload_sha256=str(execution_group_plan["execution_plan_payload_sha256"]),
    ) as acceleration:
        postprocessor = _geometry_poa_postprocessor(
            compiled_geometry=compiled_geometry,
            execution_group_plan=execution_group_plan,
            shading_configuration=shading_configuration,
            shared_acceleration_context=acceleration,
            receiver_factor_chunk_consumer=receiver_factor_chunk_consumer,
            retain_receiver_factors=retain_receiver_factors,
            receiver_factor_chunk_rows=receiver_factor_chunk_rows,
        )
        return _run_fixed_tilt(
            weather,
            config=config,
            poa_postprocessor=postprocessor,
            execution_scope=execution_scope,
        )


def run_beam_shaded_fixed_tilt(
    weather: CanonicalWeather,
    *,
    config: UnshadedFixedTiltConfiguration,
    compiled_geometry: Mapping[str, Any],
    execution_group_plan: Mapping[str, Any],
    shading_configuration: Mapping[str, Any],
    receiver_factor_chunk_consumer: Callable[[pd.DataFrame], None] | None = None,
    retain_receiver_factors: bool = True,
    receiver_factor_chunk_rows: int = 8192,
) -> UnshadedFixedTiltSimulationResult:
    """Run the Phase-5.5 beam-only geometry-aware vertical slice."""
    diffuse_method = normalize_product_namespace_identifier(shading_configuration.get("diffuse_method"))
    albedo_method = normalize_product_namespace_identifier(shading_configuration.get("albedo_method"))
    if diffuse_method != "none":
        raise BeamVerticalSliceError(
            "run_beam_shaded_fixed_tilt requires diffuse_method='none'"
        )
    if albedo_method not in {None, "none"}:
        raise BeamVerticalSliceError(
            "run_beam_shaded_fixed_tilt requires ground obstruction disabled"
        )
    return _run_geometry_fixed_tilt(
        weather,
        config=config,
        compiled_geometry=compiled_geometry,
        execution_group_plan=execution_group_plan,
        shading_configuration=shading_configuration,
        receiver_factor_chunk_consumer=receiver_factor_chunk_consumer,
        retain_receiver_factors=retain_receiver_factors,
        receiver_factor_chunk_rows=receiver_factor_chunk_rows,
        execution_scope=GEOMETRY_AWARE_FIXED_TILT_SCOPE,
    )


def run_beam_sky_shaded_fixed_tilt(
    weather: CanonicalWeather,
    *,
    config: UnshadedFixedTiltConfiguration,
    compiled_geometry: Mapping[str, Any],
    execution_group_plan: Mapping[str, Any],
    shading_configuration: Mapping[str, Any],
    receiver_factor_chunk_consumer: Callable[[pd.DataFrame], None] | None = None,
    retain_receiver_factors: bool = True,
    receiver_factor_chunk_rows: int = 8192,
) -> UnshadedFixedTiltSimulationResult:
    """Run Phase-5.6 beam + component-aware sky diffuse obstruction."""
    diffuse_method = normalize_product_namespace_identifier(shading_configuration.get("diffuse_method"))
    albedo_method = normalize_product_namespace_identifier(shading_configuration.get("albedo_method"))
    if diffuse_method != SKY_VISIBILITY_SOLVER_ID:
        raise BeamVerticalSliceError(
            f"diffuse_method must be {SKY_VISIBILITY_SOLVER_ID!r}"
        )
    if albedo_method not in {None, "none"}:
        raise BeamVerticalSliceError(
            "run_beam_sky_shaded_fixed_tilt requires ground obstruction disabled"
        )
    return _run_geometry_fixed_tilt(
        weather,
        config=config,
        compiled_geometry=compiled_geometry,
        execution_group_plan=execution_group_plan,
        shading_configuration=shading_configuration,
        receiver_factor_chunk_consumer=receiver_factor_chunk_consumer,
        retain_receiver_factors=retain_receiver_factors,
        receiver_factor_chunk_rows=receiver_factor_chunk_rows,
        execution_scope=GEOMETRY_AWARE_BEAM_SKY_FIXED_TILT_SCOPE,
    )


def run_beam_sky_ground_shaded_fixed_tilt(
    weather: CanonicalWeather,
    *,
    config: UnshadedFixedTiltConfiguration,
    compiled_geometry: Mapping[str, Any],
    execution_group_plan: Mapping[str, Any],
    shading_configuration: Mapping[str, Any],
    receiver_factor_chunk_consumer: Callable[[pd.DataFrame], None] | None = None,
    retain_receiver_factors: bool = True,
    receiver_factor_chunk_rows: int = 8192,
) -> UnshadedFixedTiltSimulationResult:
    """Run Phase-5.7 beam + sky diffuse + ground/albedo obstruction."""
    diffuse_method = normalize_product_namespace_identifier(shading_configuration.get("diffuse_method"))
    albedo_method = normalize_product_namespace_identifier(shading_configuration.get("albedo_method"))
    if diffuse_method != SKY_VISIBILITY_SOLVER_ID:
        raise BeamVerticalSliceError(
            f"diffuse_method must be {SKY_VISIBILITY_SOLVER_ID!r}"
        )
    if albedo_method != GROUND_VISIBILITY_SOLVER_ID:
        raise BeamVerticalSliceError(
            f"albedo_method must be {GROUND_VISIBILITY_SOLVER_ID!r}"
        )
    return _run_geometry_fixed_tilt(
        weather,
        config=config,
        compiled_geometry=compiled_geometry,
        execution_group_plan=execution_group_plan,
        shading_configuration=shading_configuration,
        receiver_factor_chunk_consumer=receiver_factor_chunk_consumer,
        retain_receiver_factors=retain_receiver_factors,
        receiver_factor_chunk_rows=receiver_factor_chunk_rows,
        execution_scope=GEOMETRY_AWARE_BEAM_SKY_GROUND_FIXED_TILT_SCOPE,
    )
