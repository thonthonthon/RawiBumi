"""TMY3 adapter using pvlib field parsing with OpenSIMPV-owned time semantics."""

from __future__ import annotations

import calendar
import datetime as dt
import io
from typing import Any

import pandas as pd
from pvlib.iotools import read_tmy3

from weather.core import (
    CanonicalWeather,
    build_time_semantics,
    build_weather_dataset,
    fingerprint_source_bytes,
    transformation,
    utc_offset_name,
)


_DATE_COLUMN = "Date (MM/DD/YYYY)"
_TIME_COLUMN = "Time (HH:MM)"
_TYPICAL_ANCHOR_NON_LEAP_YEAR = 2001
_TYPICAL_ANCHOR_LEAP_YEAR = 2000


def _read_source_time_columns(text: str) -> pd.DataFrame:
    """Read raw TMY3 date/time labels without pvlib calendar normalization."""
    try:
        raw = pd.read_csv(
            io.StringIO(text),
            skiprows=1,
            usecols=[_DATE_COLUMN, _TIME_COLUMN],
            dtype=str,
        )
    except ValueError as exc:
        raise ValueError(
            "TMY3 file must contain Date (MM/DD/YYYY) and Time (HH:MM) columns"
        ) from exc
    if raw.empty:
        raise ValueError("TMY3 file contains no weather rows")
    return raw


def _parse_source_interval_end_labels(
    raw: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.DatetimeIndex]:
    """Parse TMY3 right-labelled timestamps, including the 24:00 convention."""
    dates = pd.to_datetime(
        raw[_DATE_COLUMN].str.strip(),
        format="%m/%d/%Y",
        errors="raise",
    )
    parts = raw[_TIME_COLUMN].str.strip().str.extract(r"^(\d{1,2}):(\d{2})$")
    if parts.isna().any(axis=None):
        bad = raw.loc[parts.isna().any(axis=1), _TIME_COLUMN].head(5).tolist()
        raise ValueError(f"invalid TMY3 Time (HH:MM) values: {bad}")

    hours = parts[0].astype(int)
    minutes = parts[1].astype(int)
    invalid = (
        (hours < 0)
        | (hours > 24)
        | (minutes < 0)
        | (minutes > 59)
        | ((hours == 24) & (minutes != 0))
    )
    if invalid.any():
        bad = raw.loc[invalid, _TIME_COLUMN].head(5).tolist()
        raise ValueError(
            "TMY3 time must use 00:00..23:59, with 24:00 allowed only at midnight; "
            f"invalid values: {bad}"
        )

    interval_end = (
        dates
        + pd.to_timedelta(hours % 24, unit="h")
        + pd.to_timedelta(minutes, unit="m")
        + pd.to_timedelta((hours == 24).astype(int), unit="D")
    )
    return dates, hours, minutes, pd.DatetimeIndex(interval_end)


def _is_regular_hourly(index: pd.DatetimeIndex) -> bool:
    if len(index) < 2:
        return True
    diffs = index.to_series().diff().dropna().dt.total_seconds()
    return bool((diffs == 3600).all())


def _build_typical_year_interval_end(
    dates: pd.Series,
    hours: pd.Series,
    minutes: pd.Series,
) -> tuple[pd.DatetimeIndex, int]:
    """Map mixed source years onto one deterministic canonical typical year."""
    has_feb29 = bool(((dates.dt.month == 2) & (dates.dt.day == 29)).any())
    anchor_year = (
        _TYPICAL_ANCHOR_LEAP_YEAR
        if has_feb29
        else _TYPICAL_ANCHOR_NON_LEAP_YEAR
    )

    values: list[pd.Timestamp] = []
    for source_date, hour, minute in zip(dates, hours, minutes):
        timestamp = pd.Timestamp(
            year=anchor_year,
            month=int(source_date.month),
            day=int(source_date.day),
        )
        if int(hour) == 24:
            timestamp += pd.Timedelta(days=1)
        else:
            timestamp += pd.Timedelta(hours=int(hour), minutes=int(minute))
        values.append(timestamp)

    index = pd.DatetimeIndex(values)
    if (
        not index.is_monotonic_increasing
        or index.has_duplicates
        or not _is_regular_hourly(index)
    ):
        raise ValueError(
            "TMY3 mixed-year calendar could not be normalized to a regular "
            "typical-year hourly sequence"
        )
    return index, anchor_year


def _normalize_source_calendar(
    raw: pd.DataFrame,
) -> tuple[pd.DatetimeIndex, dict[str, Any]]:
    """Classify source calendar and return normalized interval-end labels."""
    dates, hours, minutes, source_interval_end = _parse_source_interval_end_labels(
        raw
    )
    source_years = sorted({int(value) for value in dates.dt.year})
    regular_source = (
        source_interval_end.is_monotonic_increasing
        and not source_interval_end.has_duplicates
        and _is_regular_hourly(source_interval_end)
    )

    if len(source_years) == 1:
        year = source_years[0]
        expected_records = 8784 if calendar.isleap(year) else 8760
        expected_first = pd.Timestamp(year=year, month=1, day=1, hour=1)
        expected_last = pd.Timestamp(year=year + 1, month=1, day=1, hour=0)
        full_actual_year = (
            len(source_interval_end) == expected_records
            and regular_source
            and source_interval_end[0] == expected_first
            and source_interval_end[-1] == expected_last
        )
        classification = (
            "actual_year" if full_actual_year else "partial_time_series"
        )
        normalized = source_interval_end
        calendar_type = "gregorian"
        anchor_year = None
    elif regular_source:
        classification = "multi_year_time_series"
        normalized = source_interval_end
        calendar_type = "gregorian"
        anchor_year = None
    else:
        classification = "typical_year"
        normalized, anchor_year = _build_typical_year_interval_end(
            dates, hours, minutes
        )
        calendar_type = "typical_year"

    metadata = {
        "calendar_classification": classification,
        "source_years": source_years,
        "calendar_anchor_year": anchor_year,
        "calendar_type": calendar_type,
    }
    return normalized, metadata


def read_tmy3_weather_bytes(
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
    raw_time = _read_source_time_columns(text)
    interval_end_naive, calendar_metadata = _normalize_source_calendar(raw_time)

    # pvlib remains the field/metadata parser, but OpenSIMPV owns timestamp/calendar
    # semantics so actual leap-year files are not altered by pvlib's TMY normalization.
    frame, meta = read_tmy3(
        io.StringIO(text),
        map_variables=True,
        encoding=None,
    )
    if len(frame) != len(interval_end_naive):
        raise ValueError(
            "TMY3 field parser row count differs from raw timestamp row count"
        )

    duration_seconds = 3600
    offset_hours = float(meta["TZ"])
    timezone = utc_offset_name(offset_hours)
    tzinfo = dt.timezone(dt.timedelta(hours=offset_hours))
    interval_end = interval_end_naive.tz_localize(tzinfo)
    interval_start = interval_end - pd.Timedelta(seconds=duration_seconds)

    canonical = pd.DataFrame(index=interval_start)
    column_map = {
        "ghi": "ghi_w_m2",
        "dni": "dni_w_m2",
        "dhi": "dhi_w_m2",
        "temp_air": "ambient_temperature_c",
        "wind_speed": "wind_speed_m_s",
        "albedo": "albedo",
        "temp_dew": "dew_point_temperature_c",
    }
    for source_column, target_column in column_map.items():
        if source_column in frame.columns:
            canonical[target_column] = pd.to_numeric(
                frame[source_column], errors="coerce"
            ).to_numpy()

    if "pressure" in frame.columns:
        canonical["pressure_pa"] = (
            pd.to_numeric(frame["pressure"], errors="coerce").to_numpy() * 100.0
        )
    if "relative_humidity" in frame.columns:
        canonical["relative_humidity_fraction"] = (
            pd.to_numeric(frame["relative_humidity"], errors="coerce").to_numpy()
            / 100.0
        )
    if "precipitable_water" in frame.columns:
        canonical["precipitable_water_mm"] = (
            pd.to_numeric(frame["precipitable_water"], errors="coerce").to_numpy()
            * 10.0
        )

    source_file = fingerprint_source_bytes(
        data,
        file_id=f"{weather_dataset_id}:source:0",
        filename=filename,
        media_type="text/csv",
        source_url=source_url,
        attribution="TMY3 source file supplied by user/provider",
    )

    variable_metadata: dict[str, dict[str, Any]] = {}
    for variable in ("ghi_w_m2", "dni_w_m2", "dhi_w_m2"):
        if variable in canonical:
            variable_metadata[variable] = {
                "temporal_basis": "interval_average",
                "source_quantity": "interval_energy_wh_m2",
                "source_interval_seconds": 3600,
            }
    for variable in canonical.columns:
        if variable not in variable_metadata:
            variable_metadata[variable] = {
                "temporal_basis": "source_timestamp_sample"
            }

    transforms = [
        transformation(
            "timezone_normalization",
            algorithm="tmy3_interval_end_to_interval_start",
            algorithm_version="0.2",
            parameters={
                "shift_seconds": -3600,
                "calendar_classification": calendar_metadata[
                    "calendar_classification"
                ],
                "source_years": calendar_metadata["source_years"],
                "calendar_anchor_year": calendar_metadata[
                    "calendar_anchor_year"
                ],
            },
        ),
        transformation(
            "unit_conversion",
            algorithm="interval_energy_wh_m2_to_average_w_m2",
            algorithm_version="0.1",
            parameters={
                "duration_seconds": 3600,
                "note": (
                    "For one-hour TMY3 intervals the numeric Wh/m2 value equals "
                    "the interval-average W/m2 value."
                ),
            },
        ),
    ]
    if "pressure_pa" in canonical:
        transforms.append(
            transformation(
                "unit_conversion",
                algorithm="mbar_to_pa",
                algorithm_version="0.1",
                parameters={"factor": 100.0},
            )
        )
    if "relative_humidity_fraction" in canonical:
        transforms.append(
            transformation(
                "unit_conversion",
                algorithm="percent_to_fraction",
                algorithm_version="0.1",
                parameters={"factor": 0.01},
            )
        )
    if "precipitable_water_mm" in canonical:
        transforms.append(
            transformation(
                "unit_conversion",
                algorithm="cm_to_mm",
                algorithm_version="0.1",
                parameters={"factor": 10.0},
            )
        )

    classification = calendar_metadata["calendar_classification"]
    leap_year_handling = (
        "tmy3_typical_year_normalized"
        if classification == "typical_year"
        else "source_preserved"
    )

    time_semantics = build_time_semantics(
        canonical_timezone=timezone,
        source_timestamp_convention="interval_end",
        native_interval_seconds=duration_seconds,
        current_interval_seconds=duration_seconds,
        source_timezone=timezone,
        source_utc_offset_hours=offset_hours,
    )

    return build_weather_dataset(
        canonical,
        weather_dataset_id=weather_dataset_id,
        revision_id=revision_id,
        name=name,
        site_id=site_id,
        timezone=timezone,
        native_resolution_seconds=duration_seconds,
        source_id=source_id,
        source_format="tmy3",
        source_timestamp_convention="interval_end",
        source_files=[source_file],
        location={
            "latitude_deg": float(meta["latitude"]),
            "longitude_deg": float(meta["longitude"]),
            "elevation_m": float(meta["altitude"]),
        },
        variable_metadata=variable_metadata,
        transformations=transforms,
        calendar_type=calendar_metadata["calendar_type"],
        leap_year_handling=leap_year_handling,
        time_semantics=time_semantics,
        extra_metadata={
            "source_metadata": {
                "station_name": meta.get("Name"),
                "state": meta.get("State"),
                "usaf": meta.get("USAF"),
                "utc_offset_hours": offset_hours,
                "calendar_classification": classification,
                "source_years": calendar_metadata["source_years"],
                "calendar_anchor_year": calendar_metadata[
                    "calendar_anchor_year"
                ],
            }
        },
    )
