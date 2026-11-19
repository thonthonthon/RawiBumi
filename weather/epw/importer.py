"""EnergyPlus Weather (EPW) adapter using pvlib's documented parser."""

from __future__ import annotations

import io
import logging
from typing import Any

import pandas as pd
from pvlib.iotools import read_epw

from weather.core import (
    CanonicalWeather,
    build_time_semantics,
    build_weather_dataset,
    fingerprint_source_bytes,
    transformation,
    utc_offset_name,
)


def read_epw_weather_bytes(
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
    fields = text.partition("\n")[0].split(",")
    if len(fields) < 10:
        logging.getLogger(__name__).warning("Incomplete EPW location header: %d fields", len(fields))
        raise ValueError("EPW location header is incomplete; provide all location fields.")
    frame, meta = read_epw(io.StringIO(text))

    duration_seconds = 3600
    # pvlib normalizes EPW's 1..24 hour representation to a 0..23 local-standard-
    # time DatetimeIndex. That normalized index is used as OpenSIMPV interval start.
    canonical = pd.DataFrame(index=frame.index)

    column_map = {
        "ghi": "ghi_w_m2",
        "dni": "dni_w_m2",
        "dhi": "dhi_w_m2",
        "temp_air": "ambient_temperature_c",
        "wind_speed": "wind_speed_m_s",
        "albedo": "albedo",
        "temp_dew": "dew_point_temperature_c",
        "aerosol_optical_depth": "aerosol_optical_depth",
    }
    for source_column, target_column in column_map.items():
        if source_column in frame.columns:
            canonical[target_column] = pd.to_numeric(
                frame[source_column], errors="coerce"
            ).to_numpy()

    if "atmospheric_pressure" in frame.columns:
        canonical["pressure_pa"] = pd.to_numeric(
            frame["atmospheric_pressure"], errors="coerce"
        ).to_numpy()
    if "relative_humidity" in frame.columns:
        canonical["relative_humidity_fraction"] = (
            pd.to_numeric(frame["relative_humidity"], errors="coerce").to_numpy()
            / 100.0
        )
    if "precipitable_water" in frame.columns:
        # EPW stores precipitable water in cm.
        canonical["precipitable_water_mm"] = (
            pd.to_numeric(frame["precipitable_water"], errors="coerce").to_numpy()
            * 10.0
        )

    offset_hours = float(meta["TZ"])
    timezone = utc_offset_name(offset_hours)
    source_file = fingerprint_source_bytes(
        data,
        file_id=f"{weather_dataset_id}:source:0",
        filename=filename,
        media_type="text/plain",
        source_url=source_url,
        attribution="EPW source file supplied by user/provider",
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
            algorithm="epw_hour_1_24_to_interval_start",
            algorithm_version="0.1",
            parameters={
                "note": (
                    "pvlib normalizes EPW hour 1..24 records to 0..23 local "
                    "standard-time interval starts."
                )
            },
        ),
        transformation(
            "unit_conversion",
            algorithm="interval_energy_wh_m2_to_average_w_m2",
            algorithm_version="0.1",
            parameters={
                "duration_seconds": 3600,
                "note": (
                    "For one-hour EPW intervals the numeric Wh/m2 value equals "
                    "the interval-average W/m2 value."
                ),
            },
        ),
    ]
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

    time_semantics = build_time_semantics(
        canonical_timezone=timezone,
        source_timestamp_convention="epw_hour_1_24_interval",
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
        source_format="epw",
        source_timestamp_convention="epw_hour_1_24_interval",
        source_files=[source_file],
        location={
            "latitude_deg": float(meta["latitude"]),
            "longitude_deg": float(meta["longitude"]),
            "elevation_m": float(meta["altitude"]),
        },
        variable_metadata=variable_metadata,
        transformations=transforms,
        leap_year_handling="epw_8760_typical_year",
        time_semantics=time_semantics,
        extra_metadata={
            "source_metadata": {
                "city": meta.get("city"),
                "state_or_province": meta.get("state-prov"),
                "country": meta.get("country"),
                "wmo_code": meta.get("WMO_code"),
                "utc_offset_hours": offset_hours,
            }
        },
    )
