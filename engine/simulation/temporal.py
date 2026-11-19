"""Explicit temporal execution context for arbitrary supported working cadence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from engine.timeline import SimulationTimeline, build_simulation_timeline
from weather.core import CanonicalWeather
from weather.disaggregation import resample_weather


V1_TARGET_TIMESTEPS_SECONDS = (60, 300, 900, 3600)


@dataclass(frozen=True)
class TemporalExecutionContext:
    """Working weather, timeline, and interval-level temporal provenance."""

    weather: CanonicalWeather
    timeline: SimulationTimeline
    provenance: pd.DataFrame
    metadata: dict[str, Any]


def _cadence_relation(working_seconds: int, native_seconds: int) -> str:
    if working_seconds < native_seconds:
        return "finer_than_native"
    if working_seconds > native_seconds:
        return "coarser_than_native"
    return "equal_to_native"


def _input_transformation(
    target_seconds: int,
    input_seconds: int,
) -> str:
    if target_seconds < input_seconds:
        return "disaggregation"
    if target_seconds > input_seconds:
        return "aggregation"
    return "unchanged"


def _lineage_from_input(
    input_weather: CanonicalWeather,
    working_weather: CanonicalWeather,
    *,
    target_seconds: int,
) -> pd.DataFrame:
    """Map each working interval to the canonical input interval span it came from."""
    input_seconds = int(input_weather.dataset["series_resolution_seconds"])
    working_index = working_weather.series.index
    input_index = input_weather.series.index
    relation = _input_transformation(target_seconds, input_seconds)

    if relation == "unchanged":
        source_start = input_index
        source_end = input_index + pd.to_timedelta(input_seconds, unit="s")
        source_count = np.ones(len(working_index), dtype=int)
    elif relation == "disaggregation":
        if input_seconds % target_seconds != 0:
            raise ValueError(
                "working cadence must divide input cadence for deterministic "
                "interval lineage"
            )
        factor = input_seconds // target_seconds
        source_start = pd.DatetimeIndex(
            np.repeat(input_index.to_numpy(), factor)
        )
        source_end = source_start + pd.to_timedelta(input_seconds, unit="s")
        source_count = np.ones(len(working_index), dtype=int)
    else:
        if target_seconds % input_seconds != 0:
            raise ValueError(
                "working cadence must be an integer multiple of input cadence "
                "for deterministic interval lineage"
            )
        factor = target_seconds // input_seconds
        if len(input_index) % factor != 0:
            raise ValueError(
                "input cadence does not contain complete working-interval groups"
            )
        source_start = input_index[::factor]
        source_end = source_start + pd.to_timedelta(target_seconds, unit="s")
        source_count = np.full(len(working_index), factor, dtype=int)

    if len(source_start) != len(working_index):
        raise RuntimeError("temporal lineage row count does not match working weather")

    native_seconds = int(input_weather.dataset["native_resolution_seconds"])
    origin = str(working_weather.dataset.get("series_origin", "unknown"))
    frame = pd.DataFrame(index=working_index.copy())
    frame.index.name = "interval_start"
    frame["input_interval_start"] = source_start
    frame["input_interval_end"] = source_end
    frame["input_interval_count"] = source_count
    frame["input_series_resolution_seconds"] = input_seconds
    frame["native_resolution_seconds"] = native_seconds
    frame["simulation_resolution_seconds"] = target_seconds
    frame["cadence_relation_to_native"] = _cadence_relation(
        target_seconds,
        native_seconds,
    )
    frame["input_to_working_transformation"] = relation
    frame["working_series_origin"] = origin
    frame["is_rawibumi_disaggregated"] = relation == "disaggregation"
    frame["is_rawibumi_aggregated"] = relation == "aggregation"
    # Compatibility aliases for pre-rename consumers.
    frame["is_opensimpv_disaggregated"] = frame["is_rawibumi_disaggregated"]
    frame["is_opensimpv_aggregated"] = frame["is_rawibumi_aggregated"]
    frame["is_working_resolution_native"] = target_seconds == native_seconds
    is_opensimpv_derived = origin in {"opensimpv_derived", "opensimpv_derived"}
    frame["is_working_series_opensimpv_derived"] = is_opensimpv_derived
    frame["is_working_series_opensimpv_derived"] = is_opensimpv_derived
    return frame


def _provider_subhourly_metadata(weather: CanonicalWeather) -> dict[str, Any]:
    upstream = weather.dataset.get("upstream_generation")
    native_seconds = int(weather.dataset["native_resolution_seconds"])
    if not isinstance(upstream, dict):
        return {
            "provider_generated_subhourly": False,
            "provider_base_resolution_seconds": None,
            "provider_generation_method": None,
        }

    base = upstream.get("base_resolution_seconds")
    base_value = int(base) if isinstance(base, int) and base > 0 else None
    provider_generated = (
        weather.dataset.get("native_series_origin") == "provider_generated"
        and base_value is not None
        and native_seconds < base_value
    )
    return {
        "provider_generated_subhourly": provider_generated,
        "provider_base_resolution_seconds": base_value,
        "provider_generation_method": upstream.get("method"),
    }


def prepare_temporal_execution(
    weather: CanonicalWeather,
    *,
    simulation_timestep_seconds: int,
) -> TemporalExecutionContext:
    """Create one explicit working weather/timeline contract.

    No implicit interpolation happens inside the physics engine. Resolution conversion
    occurs here, before timeline/solar evaluation, using the versioned weather
    transformation layer.

    The function accepts any positive integer cadence that can be reached from the
    supplied canonical series by the current integer-ratio resampler. The V1 target
    cadences (60/300/900/3600 s) are identified in metadata but are not hard-coded as
    the only legal values.
    """
    if (
        not isinstance(simulation_timestep_seconds, int)
        or isinstance(simulation_timestep_seconds, bool)
        or simulation_timestep_seconds < 1
    ):
        raise ValueError("simulation_timestep_seconds must be an integer >= 1")

    input_seconds = int(weather.dataset["series_resolution_seconds"])
    native_seconds = int(weather.dataset["native_resolution_seconds"])

    working = resample_weather(
        weather,
        target_resolution_seconds=simulation_timestep_seconds,
    )
    timeline = build_simulation_timeline(
        working,
        simulation_timestep_seconds=simulation_timestep_seconds,
    )
    provenance = _lineage_from_input(
        weather,
        working,
        target_seconds=simulation_timestep_seconds,
    )

    relation = _input_transformation(simulation_timestep_seconds, input_seconds)
    native_relation = _cadence_relation(
        simulation_timestep_seconds,
        native_seconds,
    )
    provider_meta = _provider_subhourly_metadata(weather)

    latest_transform = (
        working.dataset.get("transformations", [])[-1]
        if relation != "unchanged" and working.dataset.get("transformations")
        else None
    )
    transform_algorithm = (
        latest_transform.get("algorithm")
        if isinstance(latest_transform, dict)
        else None
    )
    transform_algorithm_version = (
        latest_transform.get("algorithm_version")
        if isinstance(latest_transform, dict)
        else None
    )
    energy_check = None
    if isinstance(latest_transform, dict):
        params = latest_transform.get("parameters")
        if isinstance(params, dict):
            energy_check = params.get("energy_preservation_check")

    if relation == "disaggregation":
        temporal_fidelity = "rawibumi_disaggregated"
    elif relation == "aggregation":
        temporal_fidelity = "rawibumi_aggregated"
    elif (
        provider_meta["provider_generated_subhourly"]
        and simulation_timestep_seconds == native_seconds
    ):
        temporal_fidelity = "provider_generated_native_subhourly"
    elif simulation_timestep_seconds == native_seconds:
        temporal_fidelity = "native_source_cadence"
    elif working.dataset.get("series_origin") in {"opensimpv_derived", "opensimpv_derived"}:
        temporal_fidelity = "prederived_working_series"
    else:
        temporal_fidelity = "input_series_cadence"

    false_precision_warning = bool(
        native_relation == "finer_than_native"
        or provider_meta["provider_generated_subhourly"]
    )

    metadata = {
        "schema_name": "TemporalExecutionContext",
        "schema_version": "0.1",
        "weather_dataset_id": working.dataset.get("weather_dataset_id"),
        "weather_revision_id": working.dataset.get("revision_id"),
        "native_resolution_seconds": native_seconds,
        "input_series_resolution_seconds": input_seconds,
        "simulation_timestep_seconds": simulation_timestep_seconds,
        "input_to_working_transformation": relation,
        "cadence_relation_to_native": native_relation,
        "native_series_origin": weather.dataset.get("native_series_origin", "unknown"),
        "input_series_origin": weather.dataset.get("series_origin", "unknown"),
        "working_series_origin": working.dataset.get("series_origin", "unknown"),
        "temporal_fidelity": temporal_fidelity,
        "derived_subhourly": bool(working.dataset.get("derived_subhourly", False)),
        "provider_generated_subhourly": provider_meta[
            "provider_generated_subhourly"
        ],
        "provider_base_resolution_seconds": provider_meta[
            "provider_base_resolution_seconds"
        ],
        "provider_generation_method": provider_meta[
            "provider_generation_method"
        ],
        "false_precision_warning": false_precision_warning,
        "working_interval_count": len(working.series),
        "v1_target_timestep": simulation_timestep_seconds
        in V1_TARGET_TIMESTEPS_SECONDS,
        "resolution_transform_algorithm": transform_algorithm,
        "resolution_transform_algorithm_version": transform_algorithm_version,
        "irradiance_energy_preservation_check": energy_check,
        "source_origin_time_semantics": (
            working.dataset.get("time_semantics") or {}
        ).get("origin_source"),
        "working_canonical_time_semantics": (
            working.dataset.get("time_semantics") or {}
        ).get("canonical"),
        "representative_time_semantics": (
            working.dataset.get("time_semantics") or {}
        ).get("representative_time"),
    }

    return TemporalExecutionContext(
        weather=working,
        timeline=timeline,
        provenance=provenance,
        metadata=metadata,
    )
