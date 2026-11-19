"""Plane-of-array irradiance transposition for the Phase-3 unshaded engine."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd
import pvlib

from engine.irradiance.completion import IrradianceCompletionResult
from engine.solar import SolarPositionResult


POA_ISOTROPIC = "poa.transposition.isotropic.pvlib.v0.1"
POA_HAYDAVIES = "poa.transposition.haydavies.pvlib.v0.1"
POA_PEREZ = "poa.transposition.perez.pvlib.v0.1"
POA_PEREZ_DRIESSE = "poa.transposition.perez_driesse.pvlib.v0.1"
POA_PVSYST81_PEREZ = "poa.transposition.pvsyst81_perez.v0.1"

PVSYST_LOW_SUN_CUTOFF_DEG = 2.0

SUPPORTED_TRANSPOSITION_MODELS = {
    POA_ISOTROPIC,
    POA_HAYDAVIES,
    POA_PEREZ,
    POA_PEREZ_DRIESSE,
    POA_PVSYST81_PEREZ,
}

_PVLIB_MODEL = {
    POA_ISOTROPIC: "isotropic",
    POA_HAYDAVIES: "haydavies",
    POA_PEREZ: "perez",
    POA_PEREZ_DRIESSE: "perez-driesse",
}


@dataclass(frozen=True)
class PerezCoefficientSet:
    """Explicit Perez coefficient table with timestep and provenance.

    Rows are the eight Perez clearness bins. Columns are ordered:
    F11, F12, F13, F21, F22, F23.

    PVsyst 8.1 production sub-hourly coefficient tables are timestep-specific.
    OpenSIMPV never substitutes the public 2023 proof-of-concept minute table and
    never relabels ordinary Perez-1990 coefficients as PVsyst-8.1 coefficients.
    """

    coefficient_set_id: str
    timestep_seconds: int
    coefficients: tuple[tuple[float, float, float, float, float, float], ...]
    source_reference: str
    pvsyst81_production_verified: bool = False

    def __post_init__(self) -> None:
        if not self.coefficient_set_id:
            raise ValueError("coefficient_set_id must not be empty")
        if int(self.timestep_seconds) != self.timestep_seconds:
            raise ValueError("Perez coefficient timestep_seconds must be an integer")
        if int(self.timestep_seconds) <= 0:
            raise ValueError("Perez coefficient timestep_seconds must be positive")
        array = np.asarray(self.coefficients, dtype=float)
        if array.shape != (8, 6):
            raise ValueError("Perez coefficient table must have shape (8, 6)")
        if not np.isfinite(array).all():
            raise ValueError("Perez coefficient table must contain only finite values")
        if not self.source_reference:
            raise ValueError("Perez coefficient source_reference must not be empty")


@dataclass(frozen=True)
class PlaneOfArrayResult:
    """Interval-start indexed unshaded POA irradiance components."""

    frame: pd.DataFrame
    metadata: dict[str, Any]


def _coerce_albedo(
    albedo: float | pd.Series | np.ndarray | list[float],
    index: pd.DatetimeIndex,
) -> np.ndarray:
    if np.isscalar(albedo):
        value = float(albedo)
        if not isfinite(value) or not 0 <= value <= 1:
            raise ValueError("albedo must be finite and within 0..1")
        return np.full(len(index), value, dtype=float)

    if isinstance(albedo, pd.Series):
        values = albedo.reindex(index).to_numpy(dtype=float)
    else:
        values = np.asarray(albedo, dtype=float)

    if values.ndim != 1 or len(values) != len(index):
        raise ValueError("albedo must be scalar or one value per interval")
    if not np.isfinite(values).all() or not ((values >= 0) & (values <= 1)).all():
        raise ValueError("albedo values must be finite and within 0..1")
    return values


def _validate_pvsyst81_timestep(timestep_seconds: int | None) -> int:
    if timestep_seconds is None:
        raise ValueError(
            "PVsyst 8.1 Perez compatibility requires simulation_timestep_seconds"
        )
    timestep = int(timestep_seconds)
    if timestep != timestep_seconds or timestep <= 0:
        raise ValueError("simulation_timestep_seconds must be a positive integer")
    if timestep > 3600:
        raise ValueError("PVsyst 8.1 Perez compatibility does not support >60 minutes")
    if 3600 % timestep != 0:
        raise ValueError(
            "PVsyst 8.1 sub-hourly Perez timestep must be an integer divisor "
            "of 60 minutes"
        )
    return timestep


def _diffuse_subcomponents(
    *,
    model_id: str,
    surface_tilt_deg: float,
    surface_azimuth_deg: float,
    dhi: np.ndarray,
    dni: np.ndarray,
    dni_extra: np.ndarray,
    apparent_zenith: np.ndarray,
    solar_azimuth: np.ndarray,
    relative_airmass: np.ndarray,
    model_perez: str,
) -> dict[str, np.ndarray]:
    if model_id == POA_ISOTROPIC:
        sky = np.asarray(
            pvlib.irradiance.isotropic(surface_tilt_deg, dhi),
            dtype=float,
        )
        return {
            "poa_sky_diffuse": sky,
            "poa_isotropic": sky,
            "poa_circumsolar": np.zeros_like(sky),
            "poa_horizon": np.zeros_like(sky),
        }

    if model_id == POA_HAYDAVIES:
        components = pvlib.irradiance.haydavies(
            surface_tilt_deg,
            surface_azimuth_deg,
            dhi,
            dni,
            dni_extra,
            solar_zenith=apparent_zenith,
            solar_azimuth=solar_azimuth,
            return_components=True,
        )
    elif model_id == POA_PEREZ:
        components = pvlib.irradiance.perez(
            surface_tilt_deg,
            surface_azimuth_deg,
            dhi,
            dni,
            dni_extra,
            apparent_zenith,
            solar_azimuth,
            relative_airmass,
            model=model_perez,
            return_components=True,
        )
    else:
        components = pvlib.irradiance.perez_driesse(
            surface_tilt_deg,
            surface_azimuth_deg,
            dhi,
            dni,
            dni_extra,
            apparent_zenith,
            solar_azimuth,
            airmass=relative_airmass,
            return_components=True,
        )

    result: dict[str, np.ndarray] = {}
    for key in (
        "poa_sky_diffuse",
        "poa_isotropic",
        "poa_circumsolar",
        "poa_horizon",
    ):
        if key in components:
            result[key] = np.asarray(components[key], dtype=float)
        else:
            result[key] = np.zeros(len(dhi), dtype=float)
    return result


def _custom_perez_diffuse_subcomponents(
    *,
    coefficients: np.ndarray,
    surface_tilt_deg: float,
    surface_azimuth_deg: float,
    dhi: np.ndarray,
    dni: np.ndarray,
    dni_extra: np.ndarray,
    apparent_zenith: np.ndarray,
    solar_azimuth: np.ndarray,
    relative_airmass: np.ndarray,
) -> dict[str, np.ndarray]:
    """Evaluate the discrete Perez-1990 form with an explicit 8x6 table."""
    z = np.radians(apparent_zenith)
    kappa = 1.041

    with np.errstate(invalid="ignore", divide="ignore"):
        delta = dhi * relative_airmass / dni_extra
        eps = (
            np.divide(dhi + dni, dhi) + kappa * z**3
        ) / (1.0 + kappa * z**3)

    ebin = np.digitize(
        eps,
        (0.0, 1.065, 1.23, 1.5, 1.95, 2.8, 4.5, 6.2),
    )
    ebin = np.asarray(ebin, dtype=int)
    ebin[np.isnan(eps)] = 0
    ebin -= 1

    extended = np.vstack(
        [
            coefficients,
            np.array([[np.nan] * 6], dtype=float),
        ]
    )
    rows = extended[ebin]
    f1 = rows[:, 0] + rows[:, 1] * delta + rows[:, 2] * z
    f1 = np.maximum(f1, 0.0)
    f2 = rows[:, 3] + rows[:, 4] * delta + rows[:, 5] * z

    a = np.asarray(
        pvlib.irradiance.aoi_projection(
            surface_tilt_deg,
            surface_azimuth_deg,
            apparent_zenith,
            solar_azimuth,
        ),
        dtype=float,
    )
    a = np.maximum(a, 0.0)
    b = np.maximum(
        np.cos(np.radians(apparent_zenith)),
        np.cos(np.radians(85.0)),
    )

    term1 = 0.5 * (1.0 - f1) * (
        1.0 + np.cos(np.radians(surface_tilt_deg))
    )
    term2 = f1 * a / b
    term3 = f2 * np.sin(np.radians(surface_tilt_deg))

    isotropic = dhi * term1
    circumsolar = dhi * term2
    horizon = dhi * term3
    sky = np.maximum(isotropic + circumsolar + horizon, 0.0)

    invalid_airmass = np.isnan(relative_airmass)
    sky = np.where(invalid_airmass, 0.0, sky)
    zero_sky = sky == 0.0
    isotropic = np.where(zero_sky | invalid_airmass, 0.0, isotropic)
    circumsolar = np.where(zero_sky | invalid_airmass, 0.0, circumsolar)
    horizon = np.where(zero_sky | invalid_airmass, 0.0, horizon)

    return {
        "poa_sky_diffuse": sky,
        "poa_isotropic": isotropic,
        "poa_circumsolar": circumsolar,
        "poa_horizon": horizon,
    }


def _custom_perez_total(
    *,
    surface_tilt_deg: float,
    surface_azimuth_deg: float,
    ghi: np.ndarray,
    dni: np.ndarray,
    dhi: np.ndarray,
    albedo: np.ndarray,
    apparent_zenith: np.ndarray,
    solar_azimuth: np.ndarray,
    diffuse: dict[str, np.ndarray],
) -> dict[str, np.ndarray]:
    projection = np.asarray(
        pvlib.irradiance.aoi_projection(
            surface_tilt_deg,
            surface_azimuth_deg,
            apparent_zenith,
            solar_azimuth,
        ),
        dtype=float,
    )
    direct = np.maximum(dni * projection, 0.0)
    ground = (
        ghi
        * albedo
        * (1.0 - np.cos(np.radians(surface_tilt_deg)))
        / 2.0
    )
    sky = diffuse["poa_sky_diffuse"]
    poa_diffuse = sky + ground
    return {
        "poa_direct": direct,
        "poa_sky_diffuse": sky,
        "poa_ground_diffuse": ground,
        "poa_diffuse": poa_diffuse,
        "poa_global": direct + poa_diffuse,
    }


def _apply_pvsyst_low_sun_cutoff(
    *,
    total: dict[str, np.ndarray],
    diffuse: dict[str, np.ndarray],
    true_solar_elevation_deg: np.ndarray,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], np.ndarray]:
    """Apply PVsyst's HSol < 2° beam and circumsolar cutoff."""
    low_sun = true_solar_elevation_deg < PVSYST_LOW_SUN_CUTOFF_DEG
    if not low_sun.any():
        return total, diffuse, low_sun

    adjusted_total = {
        key: np.asarray(value, dtype=float).copy()
        for key, value in total.items()
    }
    adjusted_diffuse = {
        key: np.asarray(value, dtype=float).copy()
        for key, value in diffuse.items()
    }

    adjusted_total["poa_direct"][low_sun] = 0.0
    adjusted_diffuse["poa_circumsolar"][low_sun] = 0.0

    remaining_sky = (
        adjusted_diffuse["poa_isotropic"]
        + adjusted_diffuse["poa_horizon"]
    )
    negative_remaining = low_sun & (remaining_sky < 0.0)
    if negative_remaining.any():
        adjusted_diffuse["poa_isotropic"][negative_remaining] = 0.0
        adjusted_diffuse["poa_horizon"][negative_remaining] = 0.0
        remaining_sky = (
            adjusted_diffuse["poa_isotropic"]
            + adjusted_diffuse["poa_horizon"]
        )

    adjusted_diffuse["poa_sky_diffuse"][low_sun] = remaining_sky[low_sun]
    adjusted_total["poa_sky_diffuse"][low_sun] = remaining_sky[low_sun]
    adjusted_total["poa_diffuse"] = (
        adjusted_total["poa_sky_diffuse"]
        + adjusted_total["poa_ground_diffuse"]
    )
    adjusted_total["poa_global"] = (
        adjusted_total["poa_direct"]
        + adjusted_total["poa_diffuse"]
    )
    return adjusted_total, adjusted_diffuse, low_sun


def calculate_poa(
    irradiance: IrradianceCompletionResult,
    solar: SolarPositionResult,
    *,
    surface_tilt_deg: float,
    surface_azimuth_deg: float,
    albedo: float | pd.Series | np.ndarray | list[float] = 0.20,
    model_id: str,
    model_perez: str = "allsitescomposite1990",
    simulation_timestep_seconds: int | None = None,
    pvsyst81_perez_coefficient_set: PerezCoefficientSet | None = None,
    allow_unverified_pvsyst81_coefficients: bool = False,
) -> PlaneOfArrayResult:
    """Transpose completed horizontal irradiance to an unshaded fixed plane.

    No transposition model is silently selected: model_id is mandatory.

    The PVsyst 8.1 compatibility model is fail-closed for sub-hourly simulation.
    PVsyst documents timestep-specific 48-coefficient production tables but does
    not publish those tables in its current help. Therefore OpenSIMPV requires an
    explicit coefficient set with provenance instead of silently using Perez-1990
    or the older public one-minute proof-of-concept coefficients.
    """
    if model_id not in SUPPORTED_TRANSPOSITION_MODELS:
        raise ValueError(f"unsupported POA transposition model: {model_id}")
    if not isfinite(float(surface_tilt_deg)) or not 0 <= surface_tilt_deg <= 180:
        raise ValueError("surface_tilt_deg must be finite and within 0..180")
    if (
        not isfinite(float(surface_azimuth_deg))
        or not 0 <= surface_azimuth_deg < 360
    ):
        raise ValueError("surface_azimuth_deg must be finite and within 0<=azimuth<360")

    index = irradiance.frame.index
    if not solar.frame.index.equals(index):
        raise ValueError("solar-position intervals must align exactly with irradiance")

    ghi = irradiance.frame["ghi_w_m2"].to_numpy(dtype=float)
    dni = irradiance.frame["dni_w_m2"].to_numpy(dtype=float)
    dhi = irradiance.frame["dhi_w_m2"].to_numpy(dtype=float)
    if (
        not np.isfinite(ghi).all()
        or not np.isfinite(dni).all()
        or not np.isfinite(dhi).all()
    ):
        raise ValueError("POA transposition requires complete finite GHI/DNI/DHI")
    if (ghi < 0).any() or (dni < 0).any() or (dhi < 0).any():
        raise ValueError("POA transposition requires non-negative irradiance")

    apparent_zenith = solar.frame["solar_apparent_zenith_deg"].to_numpy(dtype=float)
    true_zenith = solar.frame["solar_zenith_deg"].to_numpy(dtype=float)
    true_elevation = 90.0 - true_zenith
    solar_azimuth = solar.frame["solar_azimuth_deg"].to_numpy(dtype=float)
    evaluation_times = pd.DatetimeIndex(solar.frame["evaluation_time"])

    albedo_values = _coerce_albedo(albedo, index)
    dni_extra = np.asarray(
        pvlib.irradiance.get_extra_radiation(evaluation_times),
        dtype=float,
    )
    relative_airmass = np.asarray(
        pvlib.atmosphere.get_relative_airmass(apparent_zenith),
        dtype=float,
    )

    coefficient_metadata: dict[str, Any] | None = None
    low_sun_mask = np.zeros(len(index), dtype=bool)

    if model_id == POA_PVSYST81_PEREZ:
        timestep = _validate_pvsyst81_timestep(simulation_timestep_seconds)
        if model_perez not in {"1990", "allsitescomposite1990"}:
            raise ValueError(
                "PVsyst 8.1 Perez hourly compatibility requires Perez-1990; "
                "other pvlib Perez coefficient families are not compatible"
            )

        if timestep == 3600:
            base_total = pvlib.irradiance.get_total_irradiance(
                surface_tilt=float(surface_tilt_deg),
                surface_azimuth=float(surface_azimuth_deg),
                solar_zenith=apparent_zenith,
                solar_azimuth=solar_azimuth,
                dni=dni,
                ghi=ghi,
                dhi=dhi,
                dni_extra=dni_extra,
                airmass=relative_airmass,
                albedo=albedo_values,
                model="perez",
                model_perez="allsitescomposite1990",
            )
            total = {
                key: np.asarray(base_total[key], dtype=float)
                for key in (
                    "poa_direct",
                    "poa_sky_diffuse",
                    "poa_ground_diffuse",
                    "poa_diffuse",
                    "poa_global",
                )
            }
            diffuse = _diffuse_subcomponents(
                model_id=POA_PEREZ,
                surface_tilt_deg=float(surface_tilt_deg),
                surface_azimuth_deg=float(surface_azimuth_deg),
                dhi=dhi,
                dni=dni,
                dni_extra=dni_extra,
                apparent_zenith=apparent_zenith,
                solar_azimuth=solar_azimuth,
                relative_airmass=relative_airmass,
                model_perez="allsitescomposite1990",
            )
            coefficient_metadata = {
                "policy": "perez_1990_hourly_reference",
                "coefficient_set_id": "pvlib.allsitescomposite1990",
                "source_reference": "Perez et al. 1990 / pvlib",
                "pvsyst81_production_verified": True,
                "subhourly": False,
            }
        else:
            if pvsyst81_perez_coefficient_set is None:
                raise ValueError(
                    "PVsyst 8.1 sub-hourly Perez production coefficients are "
                    "timestep-specific and are not published in the current PVsyst "
                    "documentation; provide an explicit PerezCoefficientSet with "
                    "provenance instead of silently using Perez-1990"
                )
            coefficient_set = pvsyst81_perez_coefficient_set
            if coefficient_set.timestep_seconds != timestep:
                raise ValueError(
                    "PVsyst 8.1 Perez coefficient-set timestep does not match "
                    "simulation_timestep_seconds"
                )
            if (
                not coefficient_set.pvsyst81_production_verified
                and not allow_unverified_pvsyst81_coefficients
            ):
                raise ValueError(
                    "sub-hourly Perez coefficient set is not verified as the "
                    "PVsyst 8.1 production table; set "
                    "allow_unverified_pvsyst81_coefficients=True only for "
                    "diagnostic/non-parity experiments"
                )
            coefficient_array = np.asarray(
                coefficient_set.coefficients,
                dtype=float,
            )
            diffuse = _custom_perez_diffuse_subcomponents(
                coefficients=coefficient_array,
                surface_tilt_deg=float(surface_tilt_deg),
                surface_azimuth_deg=float(surface_azimuth_deg),
                dhi=dhi,
                dni=dni,
                dni_extra=dni_extra,
                apparent_zenith=apparent_zenith,
                solar_azimuth=solar_azimuth,
                relative_airmass=relative_airmass,
            )
            total = _custom_perez_total(
                surface_tilt_deg=float(surface_tilt_deg),
                surface_azimuth_deg=float(surface_azimuth_deg),
                ghi=ghi,
                dni=dni,
                dhi=dhi,
                albedo=albedo_values,
                apparent_zenith=apparent_zenith,
                solar_azimuth=solar_azimuth,
                diffuse=diffuse,
            )
            coefficient_metadata = {
                "policy": "explicit_timestep_specific_table",
                "coefficient_set_id": coefficient_set.coefficient_set_id,
                "source_reference": coefficient_set.source_reference,
                "pvsyst81_production_verified": (
                    coefficient_set.pvsyst81_production_verified
                ),
                "subhourly": True,
                "unverified_execution_override": bool(
                    allow_unverified_pvsyst81_coefficients
                    and not coefficient_set.pvsyst81_production_verified
                ),
            }

        total, diffuse, low_sun_mask = _apply_pvsyst_low_sun_cutoff(
            total=total,
            diffuse=diffuse,
            true_solar_elevation_deg=true_elevation,
        )
        implementation = "opensimpv_pvsyst81_perez_compatibility"
    else:
        pvlib_model = _PVLIB_MODEL[model_id]
        base_total = pvlib.irradiance.get_total_irradiance(
            surface_tilt=float(surface_tilt_deg),
            surface_azimuth=float(surface_azimuth_deg),
            solar_zenith=apparent_zenith,
            solar_azimuth=solar_azimuth,
            dni=dni,
            ghi=ghi,
            dhi=dhi,
            dni_extra=dni_extra,
            airmass=relative_airmass,
            albedo=albedo_values,
            model=pvlib_model,
            model_perez=model_perez,
        )
        total = {
            key: np.asarray(base_total[key], dtype=float)
            for key in (
                "poa_direct",
                "poa_sky_diffuse",
                "poa_ground_diffuse",
                "poa_diffuse",
                "poa_global",
            )
        }
        diffuse = _diffuse_subcomponents(
            model_id=model_id,
            surface_tilt_deg=float(surface_tilt_deg),
            surface_azimuth_deg=float(surface_azimuth_deg),
            dhi=dhi,
            dni=dni,
            dni_extra=dni_extra,
            apparent_zenith=apparent_zenith,
            solar_azimuth=solar_azimuth,
            relative_airmass=relative_airmass,
            model_perez=model_perez,
        )
        implementation = "pvlib.irradiance"

    aoi = np.asarray(
        pvlib.irradiance.aoi(
            float(surface_tilt_deg),
            float(surface_azimuth_deg),
            apparent_zenith,
            solar_azimuth,
        ),
        dtype=float,
    )

    frame = pd.DataFrame(index=index.copy())
    frame.index.name = "interval_start"
    frame["evaluation_time"] = solar.frame["evaluation_time"].to_numpy()
    frame["aoi_deg"] = aoi
    frame["solar_elevation_deg"] = true_elevation
    frame["dni_extra_w_m2"] = dni_extra
    frame["relative_airmass"] = relative_airmass
    frame["poa_beam_w_m2"] = total["poa_direct"]
    frame["poa_sky_diffuse_w_m2"] = total["poa_sky_diffuse"]
    frame["poa_ground_diffuse_w_m2"] = total["poa_ground_diffuse"]
    frame["poa_diffuse_w_m2"] = total["poa_diffuse"]
    frame["poa_global_w_m2"] = total["poa_global"]
    frame["poa_isotropic_w_m2"] = diffuse["poa_isotropic"]
    frame["poa_circumsolar_w_m2"] = diffuse["poa_circumsolar"]
    frame["poa_horizon_w_m2"] = diffuse["poa_horizon"]
    frame["pvsyst_low_sun_cutoff_applied"] = low_sun_mask

    component_sum = (
        frame["poa_beam_w_m2"]
        + frame["poa_sky_diffuse_w_m2"]
        + frame["poa_ground_diffuse_w_m2"]
    )
    if not np.allclose(
        component_sum.to_numpy(dtype=float),
        frame["poa_global_w_m2"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-8,
        equal_nan=True,
    ):
        raise RuntimeError("POA global does not reconcile with beam+sky+ground")

    sky_subcomponent_sum = (
        frame["poa_isotropic_w_m2"]
        + frame["poa_circumsolar_w_m2"]
        + frame["poa_horizon_w_m2"]
    )
    if not np.allclose(
        sky_subcomponent_sum.to_numpy(dtype=float),
        frame["poa_sky_diffuse_w_m2"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-7,
        equal_nan=True,
    ):
        raise RuntimeError("POA sky diffuse does not reconcile with subcomponents")

    metadata = {
        "schema_name": "PlaneOfArrayResult",
        "schema_version": "0.1",
        "model_id": model_id,
        "implementation": implementation,
        "pvlib_version": pvlib.__version__,
        "surface_tilt_deg": float(surface_tilt_deg),
        "surface_azimuth_deg": float(surface_azimuth_deg),
        "azimuth_convention": "0_north_90_east_180_south_270_west",
        "model_perez": (
            "allsitescomposite1990"
            if model_id == POA_PVSYST81_PEREZ
            else model_perez if model_id == POA_PEREZ else None
        ),
        "simulation_timestep_seconds": (
            int(simulation_timestep_seconds)
            if simulation_timestep_seconds is not None
            else None
        ),
        "pvsyst81_perez_coefficients": coefficient_metadata,
        "pvsyst_low_sun_cutoff_deg": (
            PVSYST_LOW_SUN_CUTOFF_DEG
            if model_id == POA_PVSYST81_PEREZ
            else None
        ),
        "pvsyst_low_sun_cutoff_basis": (
            "true_solar_elevation_deg"
            if model_id == POA_PVSYST81_PEREZ
            else None
        ),
        "pvsyst_low_sun_cutoff_interval_count": int(low_sun_mask.sum()),
        "pvsyst_low_sun_components_zeroed": (
            ["beam", "circumsolar"]
            if model_id == POA_PVSYST81_PEREZ
            else []
        ),
        "subhourly_coefficient_parity_status": (
            (
                "verified_production_table"
                if coefficient_metadata
                and coefficient_metadata.get("subhourly")
                and coefficient_metadata.get("pvsyst81_production_verified")
                else "unverified_explicit_table"
                if coefficient_metadata
                and coefficient_metadata.get("subhourly")
                else "not_applicable_hourly"
            )
            if model_id == POA_PVSYST81_PEREZ
            else None
        ),
        "albedo_source": "explicit_argument",
        "unshaded": True,
        "beam_shading_factor": 1.0,
        "diffuse_shading_factor": 1.0,
        "ground_shading_factor": 1.0,
        "component_reconciliation_tolerance_w_m2": 1e-8,
        "sky_subcomponents_exposed": True,
    }
    return PlaneOfArrayResult(frame=frame, metadata=metadata)
