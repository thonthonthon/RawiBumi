"""Meteonorm text DAT adapter with explicit interval semantics."""

from __future__ import annotations

import datetime as dt
import io
import logging
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


_REQUIRED_TIME_COLUMNS = {"m", "dm", "dy", "h", "mi"}
_CORE_COLUMN_MAP = {
    "G_Gh": "ghi_w_m2",
    "G_Dh": "dhi_w_m2",
    "G_Bn": "dni_w_m2",
    "Ta": "ambient_temperature_c",
    "FF": "wind_speed_m_s",
    "Td": "dew_point_temperature_c",
}
_IRRADIANCE_SOURCE_COLUMNS = {"G_Gh", "G_Dh", "G_Bn"}

_LOCATION_RE = re.compile(
    r"""^\s*
    (?P<lat>[+-]?\d+(?:\.\d+)?)\s*\[deg\s*(?P<lat_hemi>[NS])\]\s*,\s*
    (?P<lon>[+-]?\d+(?:\.\d+)?)\s*\[deg\s*(?P<lon_hemi>[EW])\]\s*,\s*
    (?P<elev>[+-]?\d+(?:\.\d+)?)\s*\[m\]\s*,\s*
    (?P<tz>[+-]?\d+(?:\.\d+)?)\s*\[timezone\s*h\]\s*,\s*
    (?P<time_ref>[+-]?\d+(?:\.\d+)?)\s*\[time\s*ref\.\s*min\]\s*
    $""",
    re.IGNORECASE | re.VERBOSE,
)


def _signed_hemisphere(value: str, hemisphere: str) -> float:
    """Interpret Meteonorm coordinates that may carry both sign and hemisphere.

    Some Meteonorm exports emit signed numeric coordinates together with an N/E token,
    for example -6.425 [deg N]. An explicit negative numeric sign is therefore
    authoritative. Positive/unsigned values still use S/W to determine sign.
    """
    numeric = float(value)
    if numeric < 0:
        return numeric
    return -numeric if hemisphere.upper() in {"S", "W"} else numeric


def _parse_location_line(line: str) -> dict[str, float]:
    match = _LOCATION_RE.fullmatch(line.strip())
    if not match:
        raise ValueError(
            "Meteonorm DAT location line must contain latitude, longitude, "
            "elevation, timezone, and time reference"
        )
    return {
        "latitude_deg": _signed_hemisphere(
            match.group("lat"), match.group("lat_hemi")
        ),
        "longitude_deg": _signed_hemisphere(
            match.group("lon"), match.group("lon_hemi")
        ),
        "elevation_m": float(match.group("elev")),
        "utc_offset_hours": float(match.group("tz")),
        "source_time_reference_minutes": float(match.group("time_ref")),
    }


def _read_table(lines: list[str]) -> pd.DataFrame:
    if len(lines) < 4:
        raise ValueError("Meteonorm DAT file is missing header or data rows")
    header = lines[2].strip()
    delimiter = "\t" if "\t" in header else r"\s+"
    data_text = "\n".join(lines[2:]) + "\n"
    frame = pd.read_csv(
        io.StringIO(data_text),
        sep=delimiter,
        engine="python" if delimiter == r"\s+" else "c",
    )
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = sorted(_REQUIRED_TIME_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(
            "Meteonorm DAT file is missing time columns: " + ", ".join(missing)
        )
    if frame.empty:
        raise ValueError("Meteonorm DAT file contains no weather rows")
    return frame


def _source_interval_end_labels(
    frame: pd.DataFrame,
) -> tuple[pd.DatetimeIndex, int, dict[str, Any]]:
    month = pd.to_numeric(frame["m"], errors="raise").astype(int)
    day = pd.to_numeric(frame["dm"], errors="raise").astype(int)
    day_of_year = pd.to_numeric(frame["dy"], errors="raise").astype(int)
    hour = pd.to_numeric(frame["h"], errors="coerce")
    minute = pd.to_numeric(frame["mi"], errors="raise").astype(int)

    if hour.isna().any() or ((hour < 0) | (hour > 24)).any():
        logging.getLogger(__name__).warning("Meteonorm DAT contains an out-of-range hour")
        raise ValueError("Meteonorm DAT hour must be within 0..24")
    hour = hour.astype(int)
    if ((minute < 0) | (minute > 59)).any():
        raise ValueError("Meteonorm DAT minute must be within 0..59")
    if ((hour == 24) & (minute != 0)).any():
        raise ValueError("Meteonorm DAT 24 hour label is valid only as 24:00")

    has_feb29 = bool(((month == 2) & (day == 29)).any())
    anchor_year = 2000 if has_feb29 else 2001

    source_date = pd.to_datetime(
        {
            "year": pd.Series(anchor_year, index=frame.index),
            "month": month,
            "day": day,
        },
        errors="raise",
    )
    expected_day_of_year = source_date.dt.dayofyear.astype(int)
    mismatch = expected_day_of_year != day_of_year
    if mismatch.any():
        examples = frame.loc[mismatch, ["m", "dm", "dy"]].head(5).to_dict("records")
        raise ValueError(
            "Meteonorm DAT day-of-year does not match month/day; "
            f"examples: {examples}"
        )

    interval_end = (
        source_date
        + pd.to_timedelta(hour % 24, unit="h")
        + pd.to_timedelta(minute, unit="m")
        + pd.to_timedelta((hour == 24).astype(int), unit="D")
    )
    interval_end = pd.DatetimeIndex(interval_end)
    if not interval_end.is_monotonic_increasing or interval_end.has_duplicates:
        raise ValueError(
            "Meteonorm DAT timestamps must be strictly increasing before normalization"
        )
    if len(interval_end) < 2:
        raise ValueError(
            "Meteonorm DAT requires at least two rows to infer source resolution"
        )

    diffs = interval_end.to_series().diff().dropna().dt.total_seconds()
    unique_diffs = sorted({int(value) for value in diffs})
    if len(unique_diffs) != 1:
        raise ValueError(
            "Meteonorm DAT cadence is irregular; observed interval seconds: "
            + ", ".join(str(value) for value in unique_diffs[:10])
        )
    resolution_seconds = unique_diffs[0]
    if resolution_seconds < 1:
        raise ValueError("Meteonorm DAT inferred resolution must be positive")
    if 86400 % resolution_seconds != 0:
        raise ValueError(
            "Meteonorm DAT source resolution must divide a 24-hour day exactly"
        )

    start_of_year = pd.Timestamp(anchor_year, 1, 1)
    end_of_year = pd.Timestamp(anchor_year + 1, 1, 1)
    expected_records = int(
        (end_of_year - start_of_year).total_seconds() / resolution_seconds
    )
    full_year = (
        len(interval_end) == expected_records
        and interval_end[0]
        == start_of_year + pd.Timedelta(seconds=resolution_seconds)
        and interval_end[-1] == end_of_year
    )

    calendar_metadata = {
        "calendar_classification": (
            "yearless_typical_year" if full_year else "yearless_partial_series"
        ),
        "calendar_anchor_year": anchor_year,
        "source_day_count": int(day_of_year.max()),
        "day_of_year_validated": True,
    }
    return interval_end, resolution_seconds, calendar_metadata


def read_meteonorm_dat_bytes(
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
    lines = [line.rstrip("\r") for line in text.splitlines()]
    if len(lines) < 3:
        raise ValueError("Meteonorm DAT file is too short")

    site_name = lines[0].strip()
    if not site_name:
        raise ValueError("Meteonorm DAT site name is missing")

    location = _parse_location_line(lines[1])
    if location["source_time_reference_minutes"] != -30:
        raise ValueError("Meteonorm DAT time reference is not supported yet. Export with the standard -30-minute reference.")
    frame = _read_table(lines)
    interval_end_naive, resolution_seconds, calendar_metadata = (
        _source_interval_end_labels(frame)
    )

    tzinfo = dt.timezone(
        dt.timedelta(hours=float(location["utc_offset_hours"]))
    )
    interval_end = interval_end_naive.tz_localize(tzinfo)
    interval_start = interval_end - pd.Timedelta(seconds=resolution_seconds)

    canonical = pd.DataFrame(index=interval_start)
    mapped_source_columns: list[str] = []
    for source_column, target_column in _CORE_COLUMN_MAP.items():
        if source_column not in frame.columns:
            continue
        canonical[target_column] = pd.to_numeric(
            frame[source_column], errors="coerce"
        ).to_numpy()
        mapped_source_columns.append(source_column)

    if "ghi_w_m2" not in canonical:
        raise ValueError("Meteonorm DAT requires G_Gh for canonical GHI")
    if "ambient_temperature_c" not in canonical:
        raise ValueError("Meteonorm DAT requires Ta for ambient temperature")

    source_file = fingerprint_source_bytes(
        data,
        file_id=f"{weather_dataset_id}:source:0",
        filename=filename,
        media_type="text/plain",
        source_url=source_url,
        attribution="Meteonorm DAT weather file supplied by user/provider",
    )

    variable_metadata: dict[str, dict[str, Any]] = {}
    reverse_map = {target: source for source, target in _CORE_COLUMN_MAP.items()}
    for variable in canonical.columns:
        source_column = reverse_map[variable]
        variable_metadata[variable] = {
            "temporal_basis": (
                "interval_average"
                if source_column in _IRRADIANCE_SOURCE_COLUMNS
                else "source_interval_value"
            ),
            "source_column": source_column,
        }

    transforms = [
        transformation(
            "timezone_normalization",
            algorithm="meteonorm_interval_end_to_interval_start",
            algorithm_version="0.1",
            parameters={
                "shift_seconds": -resolution_seconds,
                "source_resolution_seconds": resolution_seconds,
                "source_time_reference_minutes": location[
                    "source_time_reference_minutes"
                ],
                "source_time_reference_applied_to_timestamp": False,
                "calendar_anchor_year": calendar_metadata[
                    "calendar_anchor_year"
                ],
            },
        )
    ]

    source_columns = [str(column) for column in frame.columns]
    provider_generated_subhourly = (
        resolution_seconds < 3600 and "G_Gh_hr" in frame.columns
    )
    native_series_origin = (
        "provider_generated" if provider_generated_subhourly else "unknown"
    )
    upstream_generation = (
        {
            "provider": "Meteonorm",
            "synthetic": True,
            "base_resolution_seconds": 3600,
            "method": "meteonorm_provider_subhourly_generation",
            "evidence": "source_structure",
            "evidence_detail": (
                "Subhourly G_Gh series is accompanied by G_Gh_hr hourly-reference "
                "values in the source DAT structure."
            ),
        }
        if provider_generated_subhourly
        else None
    )

    unmapped_source_columns = [
        column
        for column in source_columns
        if column not in _REQUIRED_TIME_COLUMNS
        and column not in mapped_source_columns
    ]

    canonical_timezone = utc_offset_name(location["utc_offset_hours"])
    time_semantics = build_time_semantics(
        canonical_timezone=canonical_timezone,
        source_timestamp_convention="interval_end",
        native_interval_seconds=resolution_seconds,
        current_interval_seconds=resolution_seconds,
        source_timezone=canonical_timezone,
        source_utc_offset_hours=location["utc_offset_hours"],
        source_reference_kind="provider_declared_time_reference",
        source_reference_offset_minutes=location[
            "source_time_reference_minutes"
        ],
        source_reference_applied_to_canonical_timestamp=False,
        source_reference_applied_to_solar_evaluation=False,
    )

    return build_weather_dataset(
        canonical,
        weather_dataset_id=weather_dataset_id,
        revision_id=revision_id,
        name=name,
        site_id=site_id,
        timezone=canonical_timezone,
        native_resolution_seconds=resolution_seconds,
        source_id=source_id,
        source_format="meteonorm_dat",
        source_timestamp_convention="interval_end",
        source_files=[source_file],
        location={
            "latitude_deg": location["latitude_deg"],
            "longitude_deg": location["longitude_deg"],
            "elevation_m": location["elevation_m"],
        },
        variable_metadata=variable_metadata,
        transformations=transforms,
        calendar_type="typical_year",
        native_series_origin=native_series_origin,
        upstream_generation=upstream_generation,
        leap_year_handling="meteonorm_yearless_typical_year_anchor",
        time_semantics=time_semantics,
        extra_metadata={
            "source_metadata": {
                "provider": "Meteonorm",
                "site_name": site_name,
                "utc_offset_hours": location["utc_offset_hours"],
                "source_time_reference_minutes": location[
                    "source_time_reference_minutes"
                ],
                "calendar_classification": calendar_metadata[
                    "calendar_classification"
                ],
                "calendar_anchor_year": calendar_metadata[
                    "calendar_anchor_year"
                ],
                "source_day_count": calendar_metadata["source_day_count"],
                "day_of_year_validated": calendar_metadata[
                    "day_of_year_validated"
                ],
                "available_source_columns": source_columns,
                "mapped_source_columns": mapped_source_columns,
                "unmapped_source_columns": unmapped_source_columns,
                "provider_generated_subhourly": provider_generated_subhourly,
            }
        },
    )
