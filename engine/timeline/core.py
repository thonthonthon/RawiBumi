"""Simulation timeline construction from canonical weather time semantics."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

import pandas as pd

from weather.core import CanonicalWeather


@dataclass(frozen=True)
class SimulationTimeline:
    """Interval-start indexed simulation timeline.

    The DataFrame index is the canonical interval start. Each row contains the interval end,
    midpoint, representative evaluation time, and interval duration in seconds.
    """

    frame: pd.DataFrame
    metadata: dict[str, Any]


def build_simulation_timeline(
    weather: CanonicalWeather,
    *,
    simulation_timestep_seconds: int | None = None,
) -> SimulationTimeline:
    """Build a strict quasi-steady timeline from a canonical weather series.

    This function does not resample weather. If the requested simulation timestep differs
    from the current canonical weather cadence, the caller must explicitly resample first.
    """
    index = weather.series.index
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("weather series index must be a pandas DatetimeIndex")
    if index.tz is None:
        raise ValueError("weather series timestamps must be timezone-aware")
    if len(index) == 0:
        raise ValueError("weather series must contain at least one interval")
    if not index.is_monotonic_increasing or index.has_duplicates:
        raise ValueError("weather series timestamps must be strictly increasing and unique")

    series_resolution = int(weather.dataset["series_resolution_seconds"])
    requested_resolution = (
        int(simulation_timestep_seconds)
        if simulation_timestep_seconds is not None
        else series_resolution
    )
    if requested_resolution < 1:
        raise ValueError("simulation_timestep_seconds must be positive")
    if requested_resolution != series_resolution:
        raise ValueError(
            "simulation timestep must match the current weather series resolution; "
            "explicitly resample weather before timeline construction"
        )

    if len(index) > 1:
        diffs = index.to_series().diff().dropna().dt.total_seconds().astype(int)
        if not (diffs == series_resolution).all():
            raise ValueError(
                "weather series cadence does not match series_resolution_seconds"
            )

    semantics = weather.dataset.get("time_semantics")
    if not isinstance(semantics, dict):
        raise ValueError("weather dataset is missing canonical time_semantics")

    canonical = semantics.get("canonical")
    representative = semantics.get("representative_time")
    if not isinstance(canonical, dict) or not isinstance(representative, dict):
        raise ValueError("weather time_semantics is incomplete")

    if canonical.get("timestamp_convention") != "interval_start":
        raise ValueError("Phase 3 requires canonical interval-start weather timestamps")
    if int(canonical.get("interval_seconds", 0)) != series_resolution:
        raise ValueError(
            "time_semantics canonical interval_seconds does not match weather series"
        )

    policy = representative.get("policy")
    if policy != "interval_midpoint":
        raise ValueError(
            "unsupported representative-time policy; Phase 3.1 requires interval_midpoint"
        )

    offset_minutes = float(
        representative.get("solar_evaluation_offset_minutes", 0.0)
    )
    if not isfinite(offset_minutes):
        raise ValueError("solar_evaluation_offset_minutes must be finite")

    duration = pd.to_timedelta(series_resolution, unit="s")
    midpoint_delta = pd.to_timedelta(series_resolution / 2.0, unit="s")
    solar_offset = pd.to_timedelta(offset_minutes, unit="m")

    frame = pd.DataFrame(index=index.copy())
    frame.index.name = "interval_start"
    frame["interval_end"] = frame.index + duration
    frame["interval_midpoint"] = frame.index + midpoint_delta
    frame["evaluation_time"] = frame["interval_midpoint"] + solar_offset
    frame["duration_seconds"] = series_resolution

    metadata = {
        "schema_name": "SimulationTimeline",
        "schema_version": "0.1",
        "weather_dataset_id": weather.dataset.get("weather_dataset_id"),
        "weather_revision_id": weather.dataset.get("revision_id"),
        "timezone": str(index.tz),
        "simulation_timestep_seconds": series_resolution,
        "representative_time_policy": policy,
        "solar_evaluation_offset_minutes": offset_minutes,
        "solar_evaluation_offset_source": representative.get(
            "solar_evaluation_offset_source", "none"
        ),
    }
    return SimulationTimeline(frame=frame, metadata=metadata)
