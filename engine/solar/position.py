"""NREL SPA solar-position adapter for the OpenSIMPV Phase-3 engine."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd
import pvlib

from engine.timeline import SimulationTimeline, build_simulation_timeline
from weather.core import CanonicalWeather


SOLAR_POSITION_NREL_SPA = "solar_position.nrel_spa.pvlib.v0.1"
SUPPORTED_SOLAR_POSITION_MODELS = {SOLAR_POSITION_NREL_SPA}


@dataclass(frozen=True)
class SolarPositionResult:
    """Interval-start indexed solar-position output and model manifest."""

    frame: pd.DataFrame
    metadata: dict[str, Any]


def _coerce_parameter(
    value: float | pd.Series | np.ndarray | list[float] | tuple[float, ...],
    *,
    index: pd.DatetimeIndex,
    name: str,
    positive: bool = False,
) -> float | np.ndarray:
    if np.isscalar(value):
        numeric = float(value)
        if not isfinite(numeric):
            raise ValueError(f"{name} must be finite")
        if positive and numeric <= 0:
            raise ValueError(f"{name} must be positive")
        return numeric

    if isinstance(value, pd.Series):
        aligned = value.reindex(index)
        if aligned.isna().any():
            raise ValueError(f"{name} series must cover every simulation interval")
        array = aligned.to_numpy(dtype=float)
    else:
        array = np.asarray(value, dtype=float)

    if array.ndim != 1 or len(array) != len(index):
        raise ValueError(f"{name} must be scalar or one value per simulation interval")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values")
    if positive and not (array > 0).all():
        raise ValueError(f"{name} must contain only positive values")
    return array


def calculate_solar_position(
    timeline: SimulationTimeline,
    *,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float = 0.0,
    pressure_pa: float | pd.Series | np.ndarray | list[float] | None = None,
    temperature_c: float | pd.Series | np.ndarray | list[float] | None = None,
    model_id: str = SOLAR_POSITION_NREL_SPA,
    delta_t_seconds: float | None = None,
    atmos_refract_deg: float = 0.5667,
    pressure_source: str | None = None,
    temperature_source: str | None = None,
) -> SolarPositionResult:
    """Calculate solar position at each timeline representative evaluation time.

    Azimuth follows the canonical OpenSIMPV convention: 0° North, 90° East,
    180° South, 270° West.
    """
    if model_id not in SUPPORTED_SOLAR_POSITION_MODELS:
        raise ValueError(f"unsupported solar-position model: {model_id}")
    if not isfinite(float(latitude_deg)) or not -90 <= float(latitude_deg) <= 90:
        raise ValueError("latitude_deg must be within -90..90")
    if not isfinite(float(longitude_deg)) or not -180 <= float(longitude_deg) <= 180:
        raise ValueError("longitude_deg must be within -180..180")
    if not isfinite(float(elevation_m)):
        raise ValueError("elevation_m must be finite")
    if delta_t_seconds is not None and not isfinite(float(delta_t_seconds)):
        raise ValueError("delta_t_seconds must be finite when supplied")
    if not isfinite(float(atmos_refract_deg)):
        raise ValueError("atmos_refract_deg must be finite")

    interval_index = timeline.frame.index
    evaluation_times = pd.DatetimeIndex(timeline.frame["evaluation_time"])
    if evaluation_times.tz is None:
        raise ValueError("solar evaluation times must be timezone-aware")

    if pressure_pa is None:
        pressure_value: float | np.ndarray = float(
            pvlib.atmosphere.alt2pres(float(elevation_m))
        )
        resolved_pressure_source = pressure_source or "standard_atmosphere_from_elevation"
    else:
        pressure_value = _coerce_parameter(
            pressure_pa,
            index=interval_index,
            name="pressure_pa",
            positive=True,
        )
        resolved_pressure_source = pressure_source or "explicit"

    if temperature_c is None:
        temperature_value: float | np.ndarray = 12.0
        resolved_temperature_source = temperature_source or "spa_default_12c"
    else:
        temperature_value = _coerce_parameter(
            temperature_c,
            index=interval_index,
            name="temperature_c",
        )
        resolved_temperature_source = temperature_source or "explicit"

    result = pvlib.solarposition.spa_python(
        evaluation_times,
        latitude=float(latitude_deg),
        longitude=float(longitude_deg),
        altitude=float(elevation_m),
        pressure=pressure_value,
        temperature=temperature_value,
        delta_t=delta_t_seconds,
        atmos_refract=float(atmos_refract_deg),
        how="numpy",
        numthreads=1,
    )

    output = pd.DataFrame(index=interval_index.copy())
    output.index.name = "interval_start"
    output["evaluation_time"] = timeline.frame["evaluation_time"].to_numpy()
    output["solar_apparent_zenith_deg"] = result["apparent_zenith"].to_numpy()
    output["solar_zenith_deg"] = result["zenith"].to_numpy()
    output["solar_apparent_elevation_deg"] = result[
        "apparent_elevation"
    ].to_numpy()
    output["solar_elevation_deg"] = result["elevation"].to_numpy()
    output["solar_azimuth_deg"] = result["azimuth"].to_numpy()
    output["equation_of_time_minutes"] = result["equation_of_time"].to_numpy()

    if not output["solar_azimuth_deg"].between(0.0, 360.0, inclusive="left").all():
        raise RuntimeError("solar azimuth escaped canonical 0<=azimuth<360 convention")

    metadata = {
        "schema_name": "SolarPositionResult",
        "schema_version": "0.1",
        "model_id": model_id,
        "implementation": "pvlib.solarposition.spa_python",
        "pvlib_version": pvlib.__version__,
        "algorithm_family": "NREL_SPA",
        "latitude_deg": float(latitude_deg),
        "longitude_deg": float(longitude_deg),
        "elevation_m": float(elevation_m),
        "azimuth_convention": "0_north_90_east_180_south_270_west",
        "representative_time_policy": timeline.metadata[
            "representative_time_policy"
        ],
        "solar_evaluation_offset_minutes": timeline.metadata[
            "solar_evaluation_offset_minutes"
        ],
        "delta_t_seconds": (
            float(delta_t_seconds) if delta_t_seconds is not None else None
        ),
        "delta_t_policy": (
            "explicit" if delta_t_seconds is not None else "pvlib_calculated"
        ),
        "atmos_refract_deg": float(atmos_refract_deg),
        "pressure_source": resolved_pressure_source,
        "temperature_source": resolved_temperature_source,
        "execution_backend": "numpy",
        "numthreads": 1,
    }
    return SolarPositionResult(frame=output, metadata=metadata)


def solar_position_from_weather(
    weather: CanonicalWeather,
    *,
    timeline: SimulationTimeline | None = None,
    model_id: str = SOLAR_POSITION_NREL_SPA,
    delta_t_seconds: float | None = None,
) -> SolarPositionResult:
    """Calculate solar position using canonical weather location and met inputs."""
    timeline = timeline or build_simulation_timeline(weather)

    location = weather.dataset.get("location")
    if not isinstance(location, dict):
        raise ValueError("weather dataset requires location metadata for solar position")
    if location.get("latitude_deg") is None or location.get("longitude_deg") is None:
        raise ValueError("weather location requires latitude_deg and longitude_deg")

    elevation_m = float(location.get("elevation_m") or 0.0)

    pressure = None
    pressure_source = "standard_atmosphere_from_elevation"
    if "pressure_pa" in weather.series and weather.series["pressure_pa"].notna().all():
        pressure = weather.series["pressure_pa"]
        pressure_source = "canonical_weather.pressure_pa"

    temperature = None
    temperature_source = "spa_default_12c"
    if (
        "ambient_temperature_c" in weather.series
        and weather.series["ambient_temperature_c"].notna().all()
    ):
        temperature = weather.series["ambient_temperature_c"]
        temperature_source = "canonical_weather.ambient_temperature_c"

    return calculate_solar_position(
        timeline,
        latitude_deg=float(location["latitude_deg"]),
        longitude_deg=float(location["longitude_deg"]),
        elevation_m=elevation_m,
        pressure_pa=pressure,
        temperature_c=temperature,
        model_id=model_id,
        delta_t_seconds=delta_t_seconds,
        pressure_source=pressure_source,
        temperature_source=temperature_source,
    )
