"""Deterministic weather resolution conversion for Phase 2.

Phase 2 deliberately uses interval-preserving methods instead of inventing sub-hourly cloud
structure. Irradiance interval means are held constant when disaggregated, which preserves
source-interval energy exactly. More physical clear-sky-normalized shaping belongs to a later
model with solar geometry and must have its own model/version identifier.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd

from weather.core import (
    IRRADIANCE_VARIABLES,
    CanonicalWeather,
    interval_energy_wh_m2,
    transformation,
)


def _assert_regular(weather: CanonicalWeather) -> None:
    index = weather.series.index
    expected = int(weather.dataset["series_resolution_seconds"])
    if not index.is_monotonic_increasing or index.has_duplicates:
        raise ValueError("weather must have monotonic unique timestamps before resampling")
    if len(index) > 1:
        diffs = index.to_series().diff().dropna().dt.total_seconds()
        if not (diffs == expected).all():
            raise ValueError(
                "weather cadence is irregular; resolve gaps/overlaps before resampling"
            )


def _energy_map(weather: CanonicalWeather) -> dict[str, float]:
    return {
        column: interval_energy_wh_m2(weather, column)
        for column in weather.series.columns
        if column in IRRADIANCE_VARIABLES
    }


def _updated_weather(
    source: CanonicalWeather,
    series: pd.DataFrame,
    *,
    target_resolution_seconds: int,
    transform: dict[str, Any],
) -> CanonicalWeather:
    result = CanonicalWeather(deepcopy(source.dataset), series)
    result.series.index.name = "interval_start"
    result.dataset["series_resolution_seconds"] = target_resolution_seconds
    time_semantics = result.dataset.get("time_semantics")
    if isinstance(time_semantics, dict):
        canonical_time = time_semantics.get("canonical")
        if isinstance(canonical_time, dict):
            canonical_time["interval_seconds"] = target_resolution_seconds
    result.dataset.setdefault("native_series_origin", "unknown")
    input_series_origin = source.dataset.get("series_origin", "unknown")
    result.dataset["series_origin"] = "opensimpv_derived"
    transform.setdefault("parameters", {})
    transform["parameters"].setdefault("input_series_origin", input_series_origin)
    transform["parameters"].setdefault(
        "output_series_origin", "opensimpv_derived"
    )
    result.dataset["start_time"] = pd.Timestamp(series.index[0]).isoformat()
    result.dataset["end_time"] = (
        pd.Timestamp(series.index[-1])
        + pd.Timedelta(seconds=target_resolution_seconds)
    ).isoformat()
    result.dataset["transformations"] = [
        *(result.dataset.get("transformations") or []),
        transform,
    ]
    result.dataset["derived_subhourly"] = (
        target_resolution_seconds < result.dataset["native_resolution_seconds"]
    )
    result.dataset["data_quality_status"] = "not_run_after_transformation"
    result.dataset.pop("qc_summary", None)
    return result


def resample_weather(
    weather: CanonicalWeather,
    *,
    target_resolution_seconds: int,
) -> CanonicalWeather:
    """Convert a regular canonical weather series to an integer-ratio resolution.

    Upsampling:
      zero-order interval hold for all variables. This creates synthetic subinterval values
      but preserves each source interval's irradiance energy exactly.

    Downsampling:
      equal-duration arithmetic mean across complete groups. For interval-average irradiance
      this also preserves integrated energy exactly.

    Non-integer ratios and partial terminal groups are rejected rather than silently
    interpolated/truncated.
    """
    if target_resolution_seconds < 1:
        raise ValueError("target_resolution_seconds must be positive")
    _assert_regular(weather)

    current = int(weather.dataset["series_resolution_seconds"])
    if target_resolution_seconds == current:
        return weather.copy()

    before_energy = _energy_map(weather)

    if target_resolution_seconds < current:
        if current % target_resolution_seconds != 0:
            raise ValueError(
                "Phase-2 disaggregation requires target resolution to divide source resolution"
            )
        factor = current // target_resolution_seconds
        repeated_values = np.repeat(weather.series.to_numpy(), factor, axis=0)
        starts: list[pd.Timestamp] = []
        step = pd.Timedelta(seconds=target_resolution_seconds)
        for timestamp in weather.series.index:
            base = pd.Timestamp(timestamp)
            starts.extend(base + step * offset for offset in range(factor))
        new_series = pd.DataFrame(
            repeated_values,
            index=pd.DatetimeIndex(starts),
            columns=weather.series.columns,
        )
        transform_type = (
            "hourly_to_subhourly_disaggregation"
            if current == 3600
            else "resampling"
        )
        transform = transformation(
            transform_type,
            algorithm="interval_mean_hold",
            algorithm_version="0.1",
            parameters={
                "source_resolution_seconds": current,
                "target_resolution_seconds": target_resolution_seconds,
                "factor": factor,
                "synthetic_subinterval": True,
                "irradiance_energy_preserving": True,
                "state_variable_method": "interval_hold",
            },
        )
    else:
        if target_resolution_seconds % current != 0:
            raise ValueError(
                "Phase-2 aggregation requires target resolution to be an integer "
                "multiple of source resolution"
            )
        factor = target_resolution_seconds // current
        if len(weather.series) % factor != 0:
            raise ValueError(
                "weather length does not contain complete target-resolution groups"
            )

        values = weather.series.to_numpy(dtype=float)
        grouped = values.reshape(-1, factor, values.shape[1]).mean(axis=1)
        new_index = weather.series.index[::factor]
        new_series = pd.DataFrame(
            grouped,
            index=new_index,
            columns=weather.series.columns,
        )
        transform = transformation(
            "resampling",
            algorithm="equal_duration_interval_mean",
            algorithm_version="0.1",
            parameters={
                "source_resolution_seconds": current,
                "target_resolution_seconds": target_resolution_seconds,
                "factor": factor,
                "irradiance_energy_preserving": True,
                "state_variable_method": "interval_mean",
            },
        )

    result = _updated_weather(
        weather,
        new_series,
        target_resolution_seconds=target_resolution_seconds,
        transform=transform,
    )

    after_energy = _energy_map(result)
    energy_check: dict[str, dict[str, float]] = {}
    for variable, before in before_energy.items():
        after = after_energy[variable]
        relative_error = 0.0 if before == 0 and after == 0 else (
            abs(after - before) / max(abs(before), 1e-12)
        )
        energy_check[variable] = {
            "before_wh_m2": before,
            "after_wh_m2": after,
            "relative_error": relative_error,
        }
        if relative_error > 1e-12:
            raise RuntimeError(
                f"energy preservation failure for {variable}: {relative_error}"
            )

    result.dataset["transformations"][-1]["parameters"][
        "energy_preservation_check"
    ] = energy_check
    return result
