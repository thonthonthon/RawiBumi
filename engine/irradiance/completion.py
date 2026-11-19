"""Irradiance component completion for the Phase-3 unshaded engine."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd
import pvlib

from engine.solar import SolarPositionResult
from weather.core import CanonicalWeather


DECOMPOSITION_ERBS = "irradiance.decomposition.erbs.pvlib.v0.1"
DECOMPOSITION_DISC = "irradiance.decomposition.disc.pvlib.v0.1"
DECOMPOSITION_DIRINT = "irradiance.decomposition.dirint.pvlib.v0.1"

SUPPORTED_DECOMPOSITION_MODELS = {
    DECOMPOSITION_ERBS,
    DECOMPOSITION_DISC,
    DECOMPOSITION_DIRINT,
}


@dataclass(frozen=True)
class IrradianceCompletionResult:
    """Completed GHI/DNI/DHI plus per-component provenance."""

    frame: pd.DataFrame
    metadata: dict[str, Any]


def _aligned_numeric(
    frame: pd.DataFrame,
    column: str,
    index: pd.DatetimeIndex,
) -> pd.Series:
    if column not in frame:
        return pd.Series(np.nan, index=index, dtype=float)
    values = pd.to_numeric(frame[column], errors="coerce").reindex(index)
    return values.astype(float)


def _nonnegative_with_tolerance(
    values: pd.Series,
    *,
    label: str,
    tolerance_w_m2: float,
) -> pd.Series:
    bad = values < -tolerance_w_m2
    if bad.any():
        examples = [ts.isoformat() for ts in values.index[bad][:3]]
        minimum = float(values[bad].min())
        raise ValueError(
            f"{label} produced materially negative irradiance "
            f"(minimum {minimum:.3f} W/m2; examples={examples})"
        )
    return values.clip(lower=0.0)


def _decomposition_pressure(
    weather: CanonicalWeather,
    index: pd.DatetimeIndex,
) -> tuple[float | np.ndarray, str]:
    if "pressure_pa" in weather.series:
        pressure = pd.to_numeric(
            weather.series["pressure_pa"], errors="coerce"
        ).reindex(index)
        if pressure.notna().all() and (pressure > 0).all():
            return pressure.to_numpy(dtype=float), "canonical_weather.pressure_pa"

    location = weather.dataset.get("location") or {}
    elevation_m = float(location.get("elevation_m") or 0.0)
    return (
        float(pvlib.atmosphere.alt2pres(elevation_m)),
        "standard_atmosphere_from_elevation",
    )


def _run_decomposition(
    weather: CanonicalWeather,
    solar: SolarPositionResult,
    *,
    model_id: str,
    min_cos_zenith: float,
    max_zenith_deg: float,
    negative_tolerance_w_m2: float,
) -> tuple[pd.Series, pd.Series, dict[str, Any]]:
    if model_id not in SUPPORTED_DECOMPOSITION_MODELS:
        raise ValueError(f"unsupported irradiance decomposition model: {model_id}")

    index = weather.series.index
    ghi = _aligned_numeric(weather.series, "ghi_w_m2", index)
    zenith = pd.to_numeric(
        solar.frame["solar_zenith_deg"], errors="coerce"
    ).reindex(index)
    times = pd.DatetimeIndex(solar.frame["evaluation_time"])
    if len(times) != len(index):
        raise ValueError("solar evaluation times do not align with weather intervals")

    if model_id == DECOMPOSITION_ERBS:
        modeled = pvlib.irradiance.erbs(
            ghi.to_numpy(dtype=float),
            zenith.to_numpy(dtype=float),
            times,
            min_cos_zenith=min_cos_zenith,
            max_zenith=max_zenith_deg,
        )
        dni = pd.Series(np.asarray(modeled["dni"], dtype=float), index=index)
        dhi = pd.Series(np.asarray(modeled["dhi"], dtype=float), index=index)
        details = {
            "implementation": "pvlib.irradiance.erbs",
            "pressure_source": None,
            "dew_point_source": None,
        }
    elif model_id == DECOMPOSITION_DISC:
        pressure, pressure_source = _decomposition_pressure(weather, index)
        modeled = pvlib.irradiance.disc(
            ghi.to_numpy(dtype=float),
            zenith.to_numpy(dtype=float),
            times,
            pressure=pressure,
            min_cos_zenith=min_cos_zenith,
            max_zenith=max_zenith_deg,
        )
        dni = pd.Series(np.asarray(modeled["dni"], dtype=float), index=index)
        cosz = np.maximum(
            np.cos(np.radians(zenith.to_numpy(dtype=float))),
            0.0,
        )
        dhi = pd.Series(
            ghi.to_numpy(dtype=float) - dni.to_numpy(dtype=float) * cosz,
            index=index,
        )
        details = {
            "implementation": "pvlib.irradiance.disc",
            "pressure_source": pressure_source,
            "dew_point_source": None,
        }
    else:
        if len(index) < 3:
            raise ValueError("DIRINT requires at least three time-series intervals")
        pressure, pressure_source = _decomposition_pressure(weather, index)
        dew_point = None
        dew_point_source = None
        if "dew_point_temperature_c" in weather.series:
            candidate = pd.to_numeric(
                weather.series["dew_point_temperature_c"], errors="coerce"
            ).reindex(index)
            if candidate.notna().all():
                dew_point = candidate.to_numpy(dtype=float)
                dew_point_source = "canonical_weather.dew_point_temperature_c"

        dni_values = pvlib.irradiance.dirint(
            ghi.to_numpy(dtype=float),
            zenith.to_numpy(dtype=float),
            times,
            pressure=pressure,
            use_delta_kt_prime=True,
            temp_dew=dew_point,
            min_cos_zenith=min_cos_zenith,
            max_zenith=max_zenith_deg,
        )
        dni = pd.Series(np.asarray(dni_values, dtype=float), index=index)
        cosz = np.maximum(
            np.cos(np.radians(zenith.to_numpy(dtype=float))),
            0.0,
        )
        dhi = pd.Series(
            ghi.to_numpy(dtype=float) - dni.to_numpy(dtype=float) * cosz,
            index=index,
        )
        details = {
            "implementation": "pvlib.irradiance.dirint",
            "pressure_source": pressure_source,
            "dew_point_source": dew_point_source,
            "use_delta_kt_prime": True,
        }

    dni = _nonnegative_with_tolerance(
        dni,
        label=f"{model_id} DNI",
        tolerance_w_m2=negative_tolerance_w_m2,
    )
    dhi = _nonnegative_with_tolerance(
        dhi,
        label=f"{model_id} DHI",
        tolerance_w_m2=negative_tolerance_w_m2,
    )
    return dni, dhi, details


def complete_irradiance(
    weather: CanonicalWeather,
    solar: SolarPositionResult,
    *,
    decomposition_model_id: str | None = None,
    min_cos_zenith: float = 0.065,
    max_zenith_deg: float = 87.0,
    negative_tolerance_w_m2: float = 1.0,
) -> IrradianceCompletionResult:
    """Complete missing DNI/DHI without overwriting valid source components.

    Rules:
    - source GHI is mandatory and is never synthesized;
    - one missing component is derived analytically when geometry is stable;
    - at low sun, missing DNI is set to zero and both-missing intervals become
      diffuse-only (DHI=GHI);
    - daytime intervals with both DNI and DHI missing require an explicit
      decomposition model;
    - valid source DNI/DHI values are preserved exactly.
    """
    if not 0 < min_cos_zenith <= 1:
        raise ValueError("min_cos_zenith must be within (0, 1]")
    if not 0 < max_zenith_deg <= 90:
        raise ValueError("max_zenith_deg must be within (0, 90]")
    if not isfinite(float(negative_tolerance_w_m2)) or negative_tolerance_w_m2 < 0:
        raise ValueError("negative_tolerance_w_m2 must be finite and non-negative")

    index = weather.series.index
    if not solar.frame.index.equals(index):
        raise ValueError("solar-position intervals must align exactly with weather")

    ghi = _aligned_numeric(weather.series, "ghi_w_m2", index)
    if ghi.isna().any():
        raise ValueError("Phase 3 irradiance completion requires complete GHI")
    if (ghi < -negative_tolerance_w_m2).any():
        raise ValueError("Phase 3 irradiance completion received materially negative GHI")
    ghi = ghi.clip(lower=0.0)

    dni = _aligned_numeric(weather.series, "dni_w_m2", index)
    dhi = _aligned_numeric(weather.series, "dhi_w_m2", index)

    dni_method = pd.Series(
        np.where(dni.notna(), "source", "missing"),
        index=index,
        dtype="object",
    )
    dhi_method = pd.Series(
        np.where(dhi.notna(), "source", "missing"),
        index=index,
        dtype="object",
    )

    zenith = pd.to_numeric(
        solar.frame["solar_zenith_deg"], errors="coerce"
    ).reindex(index)
    if zenith.isna().any():
        raise ValueError("solar-position result contains missing true zenith values")

    cosz = pd.Series(
        np.maximum(np.cos(np.radians(zenith.to_numpy(dtype=float))), 0.0),
        index=index,
    )
    stable_direct_geometry = (
        (zenith < max_zenith_deg) & (cosz >= min_cos_zenith)
    )
    low_sun = ~stable_direct_geometry

    # DHI can be derived without division whenever DNI is known.
    derive_dhi = dhi.isna() & dni.notna()
    if derive_dhi.any():
        raw_dhi = ghi.loc[derive_dhi] - (
            dni.loc[derive_dhi] * cosz.loc[derive_dhi]
        )
        dhi.loc[derive_dhi] = _nonnegative_with_tolerance(
            raw_dhi,
            label="analytical DHI",
            tolerance_w_m2=negative_tolerance_w_m2,
        )
        dhi_method.loc[derive_dhi] = "horizontal_identity"

    # DNI derivation divides by cos(zenith), so use it only where stable.
    derive_dni = dni.isna() & dhi.notna() & stable_direct_geometry
    if derive_dni.any():
        raw_dni = (
            ghi.loc[derive_dni] - dhi.loc[derive_dni]
        ) / cosz.loc[derive_dni]
        dni.loc[derive_dni] = _nonnegative_with_tolerance(
            raw_dni,
            label="analytical DNI",
            tolerance_w_m2=negative_tolerance_w_m2,
        )
        dni_method.loc[derive_dni] = "horizontal_identity"

    # Explicit low-sun protection: do not divide by a vanishing cosine.
    low_sun_missing_dni = dni.isna() & low_sun
    if low_sun_missing_dni.any():
        dni.loc[low_sun_missing_dni] = 0.0
        dni_method.loc[low_sun_missing_dni] = "low_sun_zero_direct"

    low_sun_missing_dhi = dhi.isna() & low_sun & dni.eq(0.0)
    if low_sun_missing_dhi.any():
        dhi.loc[low_sun_missing_dhi] = ghi.loc[low_sun_missing_dhi]
        dhi_method.loc[low_sun_missing_dhi] = "low_sun_diffuse_only"

    model_needed = dni.isna() | dhi.isna()
    model_details: dict[str, Any] | None = None
    if model_needed.any():
        if decomposition_model_id is None:
            examples = [ts.isoformat() for ts in index[model_needed][:3]]
            raise ValueError(
                "daytime intervals still require DNI/DHI decomposition; "
                "select an explicit decomposition_model_id "
                f"(examples={examples})"
            )
        modeled_dni, modeled_dhi, model_details = _run_decomposition(
            weather,
            solar,
            model_id=decomposition_model_id,
            min_cos_zenith=min_cos_zenith,
            max_zenith_deg=max_zenith_deg,
            negative_tolerance_w_m2=negative_tolerance_w_m2,
        )
        fill_dni = dni.isna()
        fill_dhi = dhi.isna()
        dni.loc[fill_dni] = modeled_dni.loc[fill_dni]
        dhi.loc[fill_dhi] = modeled_dhi.loc[fill_dhi]
        dni_method.loc[fill_dni] = decomposition_model_id
        dhi_method.loc[fill_dhi] = decomposition_model_id

    if dni.isna().any() or dhi.isna().any():
        raise RuntimeError("irradiance completion left unresolved DNI/DHI intervals")

    output = pd.DataFrame(
        {
            "ghi_w_m2": ghi,
            "dni_w_m2": dni,
            "dhi_w_m2": dhi,
            "dni_completion_method": dni_method,
            "dhi_completion_method": dhi_method,
        },
        index=index,
    )
    output.index.name = "interval_start"

    metadata = {
        "schema_name": "IrradianceCompletionResult",
        "schema_version": "0.1",
        "decomposition_model_id": decomposition_model_id,
        "decomposition_model_used": bool(model_details),
        "decomposition_model": model_details,
        "min_cos_zenith": float(min_cos_zenith),
        "max_zenith_deg": float(max_zenith_deg),
        "negative_tolerance_w_m2": float(negative_tolerance_w_m2),
        "low_sun_policy": "zero_missing_dni_and_diffuse_only_when_both_missing",
        "source_preserved_dni_intervals": int((dni_method == "source").sum()),
        "source_preserved_dhi_intervals": int((dhi_method == "source").sum()),
        "analytical_dni_intervals": int(
            (dni_method == "horizontal_identity").sum()
        ),
        "analytical_dhi_intervals": int(
            (dhi_method == "horizontal_identity").sum()
        ),
        "modeled_dni_intervals": int(
            dni_method.isin(SUPPORTED_DECOMPOSITION_MODELS).sum()
        ),
        "modeled_dhi_intervals": int(
            dhi_method.isin(SUPPORTED_DECOMPOSITION_MODELS).sum()
        ),
        "low_sun_dni_intervals": int(
            (dni_method == "low_sun_zero_direct").sum()
        ),
        "low_sun_dhi_intervals": int(
            (dhi_method == "low_sun_diffuse_only").sum()
        ),
    }
    return IrradianceCompletionResult(frame=output, metadata=metadata)
