"""Canonical weather data container and provenance helpers for RawiBumi Phase 2."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

import pandas as pd


CANONICAL_VARIABLES: dict[str, dict[str, str]] = {
    "ghi_w_m2": {"canonical_unit": "W/m2", "quantity": "irradiance"},
    "dni_w_m2": {"canonical_unit": "W/m2", "quantity": "irradiance"},
    "dhi_w_m2": {"canonical_unit": "W/m2", "quantity": "irradiance"},
    "poa_irradiance_w_m2": {"canonical_unit": "W/m2", "quantity": "irradiance"},
    "ambient_temperature_c": {"canonical_unit": "degC", "quantity": "state"},
    "wind_speed_m_s": {"canonical_unit": "m/s", "quantity": "state"},
    "pressure_pa": {"canonical_unit": "Pa", "quantity": "state"},
    "albedo": {"canonical_unit": "fraction", "quantity": "state"},
    "relative_humidity_fraction": {"canonical_unit": "fraction", "quantity": "state"},
    "dew_point_temperature_c": {"canonical_unit": "degC", "quantity": "state"},
    "precipitable_water_mm": {"canonical_unit": "mm", "quantity": "state"},
    "aerosol_optical_depth": {"canonical_unit": "1", "quantity": "state"},
    "linke_turbidity": {"canonical_unit": "1", "quantity": "state"},
}

IRRADIANCE_VARIABLES = {
    key for key, meta in CANONICAL_VARIABLES.items() if meta["quantity"] == "irradiance"
}

SERIES_ORIGINS = {
    "measured",
    "provider_generated",
    "opensimpv_derived",  # frozen v0.1 canonical provenance token
    "unknown",
}

SOURCE_REFERENCE_KINDS = {
    "none",
    "provider_declared_time_reference",
    "unknown",
}


def build_time_semantics(
    *,
    canonical_timezone: str,
    source_timestamp_convention: str,
    native_interval_seconds: int,
    current_interval_seconds: int,
    source_timezone: str | None = None,
    source_utc_offset_hours: float | None = None,
    source_reference_kind: str = "none",
    source_reference_offset_minutes: float | None = None,
    source_reference_applied_to_canonical_timestamp: bool = False,
    source_reference_applied_to_solar_evaluation: bool = False,
    solar_evaluation_offset_minutes: float = 0.0,
    solar_evaluation_offset_source: str = "none",
) -> dict[str, Any]:
    """Build the canonical weather time-semantics contract used by Phase 3."""
    if native_interval_seconds < 1 or current_interval_seconds < 1:
        raise ValueError("time-semantics interval durations must be positive")
    if source_reference_kind not in SOURCE_REFERENCE_KINDS:
        raise ValueError(
            "source_reference_kind must be one of: "
            + ", ".join(sorted(SOURCE_REFERENCE_KINDS))
        )

    return {
        "origin_source": {
            "timezone": source_timezone or canonical_timezone,
            "utc_offset_hours": source_utc_offset_hours,
            "timestamp_convention": source_timestamp_convention,
            "interval_seconds": int(native_interval_seconds),
            "reference": {
                "kind": source_reference_kind,
                "offset_minutes": (
                    float(source_reference_offset_minutes)
                    if source_reference_offset_minutes is not None
                    else None
                ),
                "applied_to_canonical_timestamp": bool(
                    source_reference_applied_to_canonical_timestamp
                ),
                "applied_to_solar_evaluation": bool(
                    source_reference_applied_to_solar_evaluation
                ),
            },
        },
        "canonical": {
            "timezone": canonical_timezone,
            "timestamp_convention": "interval_start",
            "interval_seconds": int(current_interval_seconds),
        },
        "representative_time": {
            "policy": "interval_midpoint",
            "solar_evaluation_offset_minutes": float(
                solar_evaluation_offset_minutes
            ),
            "solar_evaluation_offset_source": solar_evaluation_offset_source,
        },
    }


@dataclass
class CanonicalWeather:
    """Canonical metadata plus interval-start indexed time series.

    The DataFrame index is always the start of each canonical interval and must be
    timezone-aware. dataset['series_resolution_seconds'] gives the interval duration
    represented by each row. native_resolution_seconds retains the original source
    resolution even after later resampling.
    """

    dataset: dict[str, Any]
    series: pd.DataFrame

    def copy(self) -> "CanonicalWeather":
        return CanonicalWeather(deepcopy(self.dataset), self.series.copy(deep=True))


def fingerprint_source_bytes(
    data: bytes,
    *,
    file_id: str,
    filename: str,
    media_type: str | None = None,
    source_url: str | None = None,
    attribution: str | None = None,
    license_spdx: str | None = None,
    license_url: str | None = None,
) -> dict[str, Any]:
    return {
        "file_id": file_id,
        "filename": filename,
        "media_type": media_type,
        "byte_size": len(data),
        "sha256": sha256(data).hexdigest(),
        "source_url": source_url,
        "attribution": attribution,
        "license_spdx": license_spdx,
        "license_url": license_url,
    }


def utc_offset_name(offset_hours: float) -> str:
    total_minutes = int(round(offset_hours * 60))
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _iso(timestamp: pd.Timestamp) -> str:
    return timestamp.isoformat()


def build_weather_dataset(
    series: pd.DataFrame,
    *,
    weather_dataset_id: str,
    revision_id: str,
    name: str,
    site_id: str,
    timezone: str,
    native_resolution_seconds: int,
    series_resolution_seconds: int | None = None,
    source_id: str | None = None,
    source_format: str,
    source_timestamp_convention: str,
    source_files: list[dict[str, Any]] | None = None,
    location: dict[str, Any] | None = None,
    variable_metadata: dict[str, dict[str, Any]] | None = None,
    transformations: list[dict[str, Any]] | None = None,
    calendar_type: str = "gregorian",
    leap_year_handling: str = "source_preserved",
    data_quality_status: str = "not_run",
    weather_series_reference: str | None = None,
    native_series_origin: str = "unknown",
    series_origin: str | None = None,
    upstream_generation: dict[str, Any] | None = None,
    time_semantics: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
    start_time: str | pd.Timestamp | None = None,
    end_time: str | pd.Timestamp | None = None,
) -> CanonicalWeather:
    if not isinstance(series.index, pd.DatetimeIndex):
        raise TypeError("canonical weather series index must be a pandas DatetimeIndex")
    if series.index.tz is None:
        raise ValueError("canonical weather timestamps must be timezone-aware")
    explicit_period = start_time is not None and end_time is not None
    if (start_time is None) != (end_time is None):
        raise ValueError("explicit weather period requires both start_time and end_time")
    if len(series) == 0 and not explicit_period:
        raise ValueError("canonical weather series must contain at least one row")
    if native_resolution_seconds < 1:
        raise ValueError("native_resolution_seconds must be positive")
    effective_resolution = series_resolution_seconds or native_resolution_seconds
    if effective_resolution < 1:
        raise ValueError("series_resolution_seconds must be positive")

    if native_series_origin not in SERIES_ORIGINS:
        raise ValueError(
            "native_series_origin must be one of: "
            + ", ".join(sorted(SERIES_ORIGINS))
        )
    effective_series_origin = series_origin or native_series_origin
    if effective_series_origin not in SERIES_ORIGINS:
        raise ValueError(
            "series_origin must be one of: "
            + ", ".join(sorted(SERIES_ORIGINS))
        )

    variables: dict[str, dict[str, Any]] = {}
    provided_metadata = variable_metadata or {}
    for column in series.columns:
        base = dict(
            CANONICAL_VARIABLES.get(
                column, {"canonical_unit": None, "quantity": "other"}
            )
        )
        base.update(provided_metadata.get(column, {}))
        variables[column] = base

    if explicit_period:
        coverage_start = pd.Timestamp(start_time)
        coverage_end = pd.Timestamp(end_time)
        if (
            pd.isna(coverage_start) or pd.isna(coverage_end)
            or coverage_start.tzinfo is None or coverage_end.tzinfo is None
            or coverage_end <= coverage_start
        ):
            raise ValueError("explicit weather period must have ordered timezone-aware bounds")
        coverage_start = coverage_start.tz_convert(timezone)
        coverage_end = coverage_end.tz_convert(timezone)
    else:
        coverage_start = pd.Timestamp(series.index[0])
        coverage_end = pd.Timestamp(series.index[-1]) + pd.Timedelta(
            seconds=effective_resolution
        )

    effective_time_semantics = deepcopy(time_semantics)
    if effective_time_semantics is None:
        effective_time_semantics = build_time_semantics(
            canonical_timezone=timezone,
            source_timestamp_convention=source_timestamp_convention,
            native_interval_seconds=native_resolution_seconds,
            current_interval_seconds=effective_resolution,
            source_timezone=timezone,
        )
    else:
        canonical_time = effective_time_semantics.get("canonical") or {}
        canonical_time["timezone"] = timezone
        canonical_time["timestamp_convention"] = "interval_start"
        canonical_time["interval_seconds"] = int(effective_resolution)
        effective_time_semantics["canonical"] = canonical_time

    dataset: dict[str, Any] = {
        "schema_name": "WeatherDataset",
        "schema_version": "0.1",
        "weather_dataset_id": weather_dataset_id,
        "revision_id": revision_id,
        "name": name,
        "source_id": source_id,
        "site_id": site_id,
        "source_format": source_format,
        "source_files": source_files or [],
        "native_resolution_seconds": int(native_resolution_seconds),
        "series_resolution_seconds": int(effective_resolution),
        "native_series_origin": native_series_origin,
        "series_origin": effective_series_origin,
        "upstream_generation": deepcopy(upstream_generation),
        "timezone": timezone,
        "timestamp_convention": "interval_start",
        "source_timestamp_convention": source_timestamp_convention,
        "time_semantics": effective_time_semantics,
        "start_time": _iso(coverage_start),
        "end_time": _iso(coverage_end),
        "calendar_type": calendar_type,
        "leap_year_handling": leap_year_handling,
        "data_quality_status": data_quality_status,
        "weather_series_reference": weather_series_reference
        or f"memory://{weather_dataset_id}/{revision_id}",
        "location": location,
        "variables": variables,
        "transformations": transformations or [],
    }
    if extra_metadata:
        dataset.update(deepcopy(extra_metadata))

    canonical = series.copy()
    canonical.index.name = "interval_start"
    return CanonicalWeather(dataset, canonical)


def transformation(
    transformation_type: str,
    *,
    algorithm: str,
    algorithm_version: str,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "transformation_type": transformation_type,
        "algorithm": algorithm,
        "algorithm_version": algorithm_version,
        "parameters": parameters or {},
    }


def interval_energy_wh_m2(
    weather: CanonicalWeather,
    variable: str = "ghi_w_m2",
) -> float:
    """Integrate an interval-average irradiance series to Wh/m2."""
    if variable not in weather.series:
        raise KeyError(variable)
    duration_h = weather.dataset["series_resolution_seconds"] / 3600.0
    return float(weather.series[variable].fillna(0.0).sum() * duration_h)
