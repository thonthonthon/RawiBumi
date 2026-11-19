"""PVsyst documented standard weather CSV adapter.

This adapter intentionally targets PVsyst's documented interchange CSV format rather than
guessing the internal .MET object serialization. Modern internal .MET files are an internal
PVsyst format; OpenSIMPV will add a direct reader only when a redistributable fixture and
stable field contract are available.
"""

from __future__ import annotations

import io
import math
import re
from typing import Any

import pandas as pd

from weather.core import (
    CanonicalWeather,
    build_time_semantics,
    build_weather_dataset,
    fingerprint_source_bytes,
    transformation,
    utc_offset_name,
)


_FORMAT_TAGS = {"#weather data hourly data", "#tmy hourly data"}


def _delimiter(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return ";" if stripped.count(";") >= stripped.count(",") else ","
    raise ValueError("PVsyst standard weather file has no data table")


def _header_metadata(lines: list[str], delimiter: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        if delimiter in stripped:
            parts = [part.strip() for part in stripped.split(delimiter)]
            tag = parts[0].lstrip("#").strip().lower()
            if len(parts) > 1:
                metadata[tag] = parts[1]
    return metadata


def _parse_time_step(value: str) -> int:
    normalized = value.strip().lower().replace("minutes", "min").replace("minute", "min")
    normalized = normalized.replace("hours", "hour").replace("hrs", "hour").replace("hr", "hour")
    if normalized in {"hour", "hourly", "1 hour", "1hour"}:
        return 3600
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(min|hour)\s*", normalized)
    if not match:
        raise ValueError(f"unsupported PVsyst #Time step value {value!r}")
    number = float(match.group(1))
    seconds = number * (60 if match.group(2) == "min" else 3600)
    if seconds < 1 or not seconds.is_integer():
        raise ValueError("PVsyst time step must resolve to a whole number of seconds")
    return int(seconds)


def _parse_ut_reference(value: str | None, fallback_hours: float) -> float:
    if value is None or not value.strip():
        return fallback_hours
    normalized = value.strip().upper().replace("UTC", "UT")
    if normalized == "UT":
        return 0.0
    match = re.fullmatch(r"UT\s*([+-])\s*(\d+(?:\.\d+)?)", normalized)
    if not match:
        raise ValueError(f"unsupported PVsyst #Time reference value {value!r}")
    magnitude = float(match.group(2))
    return magnitude if match.group(1) == "+" else -magnitude


def _nearest_steps(total_minutes: float, step_minutes: float) -> int:
    """Nearest whole interval, with exact half-step ties resolved toward zero.

    PVsyst's documented +25 min / 10 min example becomes +20 min timestamp shift
    plus a +5 min within-interval solar-time remainder.
    """
    quotient = total_minutes / step_minutes
    magnitude = abs(quotient)
    lower = math.floor(magnitude)
    fraction = magnitude - lower
    rounded = lower + (1 if fraction > 0.5 else 0)
    return rounded if quotient >= 0 else -rounded


def _normalize_unit(unit: str) -> str:
    return (
        unit.strip()
        .lower()
        .replace("²", "2")
        .replace(" ", "")
        .replace("deg.c", "degc")
        .replace("m/sec", "m/s")
    )


def _irradiance_to_w_m2(values: pd.Series, unit: str, duration_seconds: int) -> pd.Series:
    normalized = _normalize_unit(unit)
    numeric = pd.to_numeric(values, errors="coerce")
    if normalized in {"w/m2", "wm-2"}:
        return numeric
    if normalized in {"mj/m2/h", "mj/m2/hour"}:
        return numeric * (1_000_000.0 / 3600.0)
    if normalized in {"mj/m2"}:
        return numeric * (1_000_000.0 / duration_seconds)
    raise ValueError(f"unsupported PVsyst irradiance unit {unit!r}")


def _find_header_and_units(lines: list[str]) -> tuple[int, list[str], list[str], str]:
    delimiter = _delimiter("\n".join(lines))
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        headers = [item.strip() for item in stripped.split(delimiter)]
        if index + 1 >= len(lines):
            raise ValueError("PVsyst standard weather file is missing unit row")
        units = [item.strip() for item in lines[index + 1].strip().split(delimiter)]
        if len(units) != len(headers):
            raise ValueError("PVsyst weather header/unit column counts differ")
        return index, headers, units, delimiter
    raise ValueError("PVsyst standard weather data header not found")


def read_pvsyst_standard_weather_bytes(
    data: bytes,
    *,
    weather_dataset_id: str,
    revision_id: str,
    name: str,
    site_id: str,
    filename: str,
    source_id: str | None = None,
    source_url: str | None = None,
    encoding: str = "utf-8-sig",
) -> CanonicalWeather:
    text = data.decode(encoding)
    lines = text.splitlines()
    first_nonempty = next((line.strip() for line in lines if line.strip()), "")
    if first_nonempty.lower() not in _FORMAT_TAGS:
        raise ValueError(
            "file is not a documented PVsyst Standard weather CSV "
            "(expected #Weather data hourly data or #TMY hourly data)"
        )

    header_index, headers, units, delimiter = _find_header_and_units(lines)
    metadata = _header_metadata(lines[:header_index], delimiter)

    required_header_tags = (
        "site",
        "country",
        "data source",
        "time step",
        "latitude",
        "longitude",
        "altitude",
        "time zone",
    )
    missing_tags = [tag for tag in required_header_tags if not metadata.get(tag)]
    if missing_tags:
        raise ValueError(
            "PVsyst Standard weather header is missing: " + ", ".join(missing_tags)
        )

    duration_seconds = _parse_time_step(metadata["time step"])
    site_offset_hours = float(metadata["time zone"])
    source_offset_hours = _parse_ut_reference(
        metadata.get("time reference"), site_offset_hours
    )

    data_text = "\n".join([lines[header_index], *lines[header_index + 2 :]]) + "\n"
    frame = pd.read_csv(io.StringIO(data_text), sep=delimiter)
    frame.columns = [str(column).strip() for column in frame.columns]
    unit_by_column = dict(zip(headers, units))

    required_date_columns = {"Month", "Day", "Hour"}
    missing_date = sorted(required_date_columns - set(frame.columns))
    if missing_date:
        raise ValueError(
            "PVsyst Standard weather data is missing date columns: "
            + ", ".join(missing_date)
        )

    if "Year" in frame.columns:
        years = pd.to_numeric(frame["Year"], errors="raise").astype(int)
    elif metadata.get("year"):
        years = pd.Series(int(metadata["year"]), index=frame.index)
    else:
        raise ValueError("PVsyst Standard weather requires Year column or #Year")

    months = pd.to_numeric(frame["Month"], errors="raise").astype(int)
    days = pd.to_numeric(frame["Day"], errors="raise").astype(int)
    hours = pd.to_numeric(frame["Hour"], errors="raise").astype(int)
    minutes = (
        pd.to_numeric(frame["Minute"], errors="raise").astype(int)
        if "Minute" in frame.columns
        else pd.Series(0, index=frame.index)
    )

    if ((hours < 0) | (hours > 23)).any():
        raise ValueError("PVsyst Standard Hour must use interval-start 0..23 convention")
    if ((minutes < 0) | (minutes > 59)).any():
        raise ValueError("PVsyst Standard Minute must be in 0..59")

    naive = pd.to_datetime(
        {
            "year": years,
            "month": months,
            "day": days,
            "hour": hours,
            "minute": minutes,
        },
        errors="raise",
    )
    source_tz = utc_offset_name(source_offset_hours)
    site_tz = utc_offset_name(site_offset_hours)
    index = pd.DatetimeIndex(naive).tz_localize(source_tz).tz_convert(site_tz)

    total_shift_minutes = float(metadata.get("hour shift") or 0) * 60.0 + float(
        metadata.get("time shift") or 0
    )
    whole_shift_seconds = 0
    solar_time_shift_minutes = 0.0
    transforms: list[dict[str, Any]] = []

    if source_offset_hours != site_offset_hours:
        transforms.append(
            transformation(
                "timezone_normalization",
                algorithm="pvsyst_time_reference_to_site_legal_time",
                algorithm_version="0.1",
                parameters={
                    "source_utc_offset_hours": source_offset_hours,
                    "site_utc_offset_hours": site_offset_hours,
                },
            )
        )

    if total_shift_minutes:
        step_minutes = duration_seconds / 60.0
        whole_steps = _nearest_steps(total_shift_minutes, step_minutes)
        whole_shift_minutes = whole_steps * step_minutes
        solar_time_shift_minutes = total_shift_minutes - whole_shift_minutes
        whole_shift_seconds = int(round(whole_shift_minutes * 60))
        index = index + pd.Timedelta(seconds=whole_shift_seconds)
        transforms.append(
            transformation(
                "timezone_normalization",
                algorithm="pvsyst_declared_time_shift_v8_1",
                algorithm_version="0.1",
                parameters={
                    "declared_total_shift_minutes": total_shift_minutes,
                    "timestamp_shift_seconds": whole_shift_seconds,
                    "remaining_solar_time_shift_minutes": solar_time_shift_minutes,
                },
            )
        )

    canonical = pd.DataFrame(index=index)
    mapped: dict[str, str] = {
        "GHI": "ghi_w_m2",
        "DHI": "dhi_w_m2",
        "DNI": "dni_w_m2",
        "GPI": "poa_irradiance_w_m2",
        "Tamb": "ambient_temperature_c",
        "WindVel": "wind_speed_m_s",
        "RH": "relative_humidity_fraction",
        "Pw": "precipitable_water_mm",
        "Aod": "aerosol_optical_depth",
        "Linke": "linke_turbidity",
        "Albedo": "albedo",
    }

    for source_column, target_column in mapped.items():
        if source_column not in frame.columns:
            continue
        unit = unit_by_column.get(source_column, "")
        values = frame[source_column]
        if source_column in {"GHI", "DHI", "DNI", "GPI"}:
            canonical[target_column] = _irradiance_to_w_m2(
                values, unit, duration_seconds
            ).to_numpy()
        elif source_column == "WindVel":
            normalized = _normalize_unit(unit)
            numeric = pd.to_numeric(values, errors="coerce")
            if normalized in {"m/s", "ms-1"}:
                canonical[target_column] = numeric.to_numpy()
            elif normalized in {"km/h", "kmh"}:
                canonical[target_column] = (numeric / 3.6).to_numpy()
            else:
                raise ValueError(f"unsupported WindVel unit {unit!r}")
        elif source_column == "RH":
            normalized = _normalize_unit(unit)
            numeric = pd.to_numeric(values, errors="coerce")
            if normalized in {"%", "percent"}:
                canonical[target_column] = (numeric / 100.0).to_numpy()
            elif normalized in {"ratio", "1", ""}:
                canonical[target_column] = numeric.to_numpy()
            else:
                raise ValueError(f"unsupported RH unit {unit!r}")
        elif source_column == "Pw":
            normalized = _normalize_unit(unit)
            numeric = pd.to_numeric(values, errors="coerce")
            if normalized == "cm":
                canonical[target_column] = (numeric * 10.0).to_numpy()
            elif normalized == "mm":
                canonical[target_column] = numeric.to_numpy()
            else:
                raise ValueError(f"unsupported Pw unit {unit!r}")
        else:
            canonical[target_column] = pd.to_numeric(
                values, errors="coerce"
            ).to_numpy()

    if "ambient_temperature_c" not in canonical:
        raise ValueError("PVsyst Standard weather requires Tamb")
    if "ghi_w_m2" not in canonical and "poa_irradiance_w_m2" not in canonical:
        raise ValueError("PVsyst Standard weather requires GHI or GPI")

    source_file = fingerprint_source_bytes(
        data,
        file_id=f"{weather_dataset_id}:source:0",
        filename=filename,
        media_type="text/csv",
        source_url=source_url,
        attribution="PVsyst Standard weather CSV supplied by user/provider",
    )

    variable_metadata: dict[str, dict[str, Any]] = {}
    for variable in canonical.columns:
        variable_metadata[variable] = {
            "temporal_basis": (
                "interval_average"
                if variable.endswith("_w_m2")
                else "source_interval_value"
            )
        }

    time_semantics = build_time_semantics(
        canonical_timezone=site_tz,
        source_timestamp_convention="interval_start",
        native_interval_seconds=duration_seconds,
        current_interval_seconds=duration_seconds,
        source_timezone=source_tz,
        source_utc_offset_hours=source_offset_hours,
        solar_evaluation_offset_minutes=solar_time_shift_minutes,
        solar_evaluation_offset_source=(
            "pvsyst_declared_time_shift_remainder"
            if solar_time_shift_minutes
            else "none"
        ),
    )

    return build_weather_dataset(
        canonical,
        weather_dataset_id=weather_dataset_id,
        revision_id=revision_id,
        name=name,
        site_id=site_id,
        timezone=site_tz,
        native_resolution_seconds=duration_seconds,
        source_id=source_id,
        source_format="pvsyst_standard_weather_csv",
        source_timestamp_convention="interval_start",
        source_files=[source_file],
        location={
            "latitude_deg": float(metadata["latitude"]),
            "longitude_deg": float(metadata["longitude"]),
            "elevation_m": float(metadata["altitude"]),
        },
        variable_metadata=variable_metadata,
        transformations=transforms,
        leap_year_handling=(
            "pvsyst_typical_year"
            if first_nonempty.lower() == "#tmy hourly data"
            else "source_preserved"
        ),
        time_semantics=time_semantics,
        extra_metadata={
            "source_metadata": {
                "site": metadata.get("site"),
                "country": metadata.get("country"),
                "data_source": metadata.get("data source"),
                "source_utc_offset_hours": source_offset_hours,
                "site_utc_offset_hours": site_offset_hours,
                "declared_total_time_shift_minutes": total_shift_minutes,
                "solar_time_shift_minutes": solar_time_shift_minutes,
            }
        },
    )
