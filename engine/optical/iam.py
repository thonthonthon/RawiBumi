"""Component-aware incidence-angle modifier handling for Phase 3."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pvlib

from engine.irradiance import PlaneOfArrayResult


IAM_NONE = "iam.none.v0.1"
IAM_TABULATED = "iam.tabulated.pvlib_interp.v0.1"
IAM_PHYSICAL_GLASS = "iam.physical_glass.v0.1"
SUPPORTED_IAM_MODELS = {IAM_NONE, IAM_TABULATED, IAM_PHYSICAL_GLASS}


@dataclass(frozen=True)
class TabulatedIAMProfile:
    """Immutable reference-angle IAM profile."""

    theta_ref_deg: tuple[float, ...]
    iam_ref: tuple[float, ...]
    interpolation_method: str = "linear"
    normalize: bool = True

    @classmethod
    def from_points(
        cls,
        points: Iterable[tuple[float, float] | list[float]],
        *,
        interpolation_method: str = "linear",
        normalize: bool = True,
    ) -> "TabulatedIAMProfile":
        pairs = tuple((float(theta), float(value)) for theta, value in points)
        if len(pairs) < 2:
            raise ValueError("IAM profile requires at least two points")
        theta = tuple(item[0] for item in pairs)
        values = tuple(item[1] for item in pairs)
        profile = cls(
            theta_ref_deg=theta,
            iam_ref=values,
            interpolation_method=interpolation_method,
            normalize=normalize,
        )
        profile.validate()
        return profile

    def validate(self) -> None:
        if len(self.theta_ref_deg) != len(self.iam_ref):
            raise ValueError("IAM angle and modifier arrays must have equal length")
        if len(self.theta_ref_deg) < 2:
            raise ValueError("IAM profile requires at least two reference points")
        if not all(isfinite(value) for value in self.theta_ref_deg):
            raise ValueError("IAM reference angles must be finite")
        if not all(isfinite(value) for value in self.iam_ref):
            raise ValueError("IAM reference values must be finite")
        if not all(0.0 <= value <= 90.0 for value in self.theta_ref_deg):
            raise ValueError("IAM reference angles must lie within 0..90 degrees")
        if any(b <= a for a, b in zip(self.theta_ref_deg, self.theta_ref_deg[1:])):
            raise ValueError("IAM reference angles must be strictly increasing")
        if any(value < 0.0 for value in self.iam_ref):
            raise ValueError("IAM reference values must be non-negative")
        if self.theta_ref_deg[0] != 0.0:
            raise ValueError("IAM profile must include an explicit 0-degree reference")
        if self.interpolation_method not in {"linear", "quadratic", "cubic"}:
            raise ValueError(
                "IAM interpolation_method must be linear, quadratic, or cubic"
            )
        minimum_points = {"linear": 2, "quadratic": 3, "cubic": 4}
        if len(self.theta_ref_deg) < minimum_points[self.interpolation_method]:
            raise ValueError(
                f"IAM {self.interpolation_method} interpolation requires at least "
                f"{minimum_points[self.interpolation_method]} points"
            )


@dataclass(frozen=True)
class OpticalResult:
    """POA components after incidence-angle optical modification."""

    frame: pd.DataFrame
    metadata: dict[str, Any]


def evaluate_tabulated_iam(
    aoi_deg: float | np.ndarray | pd.Series,
    profile: TabulatedIAMProfile,
) -> float | np.ndarray | pd.Series:
    """Evaluate a tabulated IAM profile and set back-side incidence to zero."""
    profile.validate()
    input_is_series = isinstance(aoi_deg, pd.Series)
    index = aoi_deg.index if input_is_series else None
    values = np.asarray(aoi_deg, dtype=float)
    evaluated = np.asarray(
        pvlib.iam.interp(
            values,
            profile.theta_ref_deg,
            profile.iam_ref,
            method=profile.interpolation_method,
            normalize=profile.normalize,
        ),
        dtype=float,
    )
    evaluated = np.where(np.isfinite(values) & (np.abs(values) < 90.0), evaluated, 0.0)
    evaluated = np.maximum(evaluated, 0.0)

    if np.isscalar(aoi_deg):
        return float(evaluated)
    if input_is_series:
        return pd.Series(evaluated, index=index)
    return evaluated


@lru_cache(maxsize=128)
def _diffuse_iam_cached(
    profile: TabulatedIAMProfile,
    surface_tilt_deg: float,
) -> tuple[float, float, float]:
    profile.validate()

    def iam_function(aoi):
        return np.asarray(evaluate_tabulated_iam(aoi, profile), dtype=float)

    sky = float(
        pvlib.iam.marion_integrate(iam_function, surface_tilt_deg, "sky")
    )
    horizon = float(
        pvlib.iam.marion_integrate(iam_function, surface_tilt_deg, "horizon")
    )
    ground = float(
        pvlib.iam.marion_integrate(iam_function, surface_tilt_deg, "ground")
    )
    return sky, horizon, ground


def diffuse_iam_factors(
    profile: TabulatedIAMProfile,
    *,
    surface_tilt_deg: float,
) -> dict[str, float]:
    """Integrate a tabulated IAM profile over sky/horizon/ground solid angle."""
    if not isfinite(float(surface_tilt_deg)) or not 0 <= surface_tilt_deg <= 180:
        raise ValueError("surface_tilt_deg must be finite and within 0..180")
    sky, horizon, ground = _diffuse_iam_cached(profile, float(surface_tilt_deg))
    return {"sky": sky, "horizon": horizon, "ground": ground}


def evaluate_physical_glass_iam(aoi_deg):
    """Normalized Fresnel-cover transmission; no assumed AR coating."""
    values = np.asarray(aoi_deg, dtype=float)
    evaluated = pvlib.iam.physical(values, n=1.526, K=4.0, L=0.002, n_ar=None)
    result = np.where(np.isfinite(values) & (np.abs(values) < 90), evaluated, 0.0)
    if np.isscalar(aoi_deg): return float(result)
    if isinstance(aoi_deg, pd.Series): return pd.Series(result, index=aoi_deg.index)
    return result


@lru_cache(maxsize=128)
def physical_glass_diffuse_factors(surface_tilt_deg: float) -> dict[str, float]:
    if not isfinite(surface_tilt_deg) or not 0 <= surface_tilt_deg <= 180:
        raise ValueError("surface_tilt_deg must be finite and within 0..180")
    return {part: float(pvlib.iam.marion_integrate(evaluate_physical_glass_iam, surface_tilt_deg, part))
            for part in ("sky", "horizon", "ground")}


def apply_iam(
    poa: PlaneOfArrayResult,
    *,
    model_id: str,
    surface_tilt_deg: float,
    profile: TabulatedIAMProfile | None = None,
) -> OpticalResult:
    """Apply component-aware IAM to an unshaded POA result.

    Circumsolar irradiance is treated like direct beam because it is concentrated
    around the solar disk. Isotropic sky, horizon, and ground components use
    solid-angle-integrated diffuse IAM factors.
    """
    if model_id not in SUPPORTED_IAM_MODELS:
        raise ValueError(f"unsupported IAM model: {model_id}")
    if not isfinite(float(surface_tilt_deg)) or not 0 <= surface_tilt_deg <= 180:
        raise ValueError("surface_tilt_deg must be finite and within 0..180")

    required = {
        "aoi_deg",
        "poa_beam_w_m2",
        "poa_sky_diffuse_w_m2",
        "poa_ground_diffuse_w_m2",
        "poa_global_w_m2",
        "poa_isotropic_w_m2",
        "poa_circumsolar_w_m2",
        "poa_horizon_w_m2",
    }
    missing = required - set(poa.frame.columns)
    if missing:
        raise ValueError(f"POA result is missing IAM component columns: {sorted(missing)}")

    frame = poa.frame
    index = frame.index
    aoi = pd.to_numeric(frame["aoi_deg"], errors="coerce")

    if model_id == IAM_NONE:
        beam_iam = np.ones(len(frame), dtype=float)
        diffuse = {"sky": 1.0, "horizon": 1.0, "ground": 1.0}
        profile_metadata = None
    elif model_id == IAM_PHYSICAL_GLASS:
        beam_iam = np.asarray(evaluate_physical_glass_iam(aoi), dtype=float)
        diffuse = physical_glass_diffuse_factors(float(surface_tilt_deg))
        profile_metadata = {"n": 1.526, "K": 4.0, "L": 0.002, "n_ar": None}
    else:
        if profile is None:
            raise ValueError("tabulated IAM model requires an explicit profile")
        profile.validate()
        beam_iam = np.asarray(evaluate_tabulated_iam(aoi, profile), dtype=float)
        diffuse = diffuse_iam_factors(
            profile,
            surface_tilt_deg=float(surface_tilt_deg),
        )
        profile_metadata = {
            "theta_ref_deg": list(profile.theta_ref_deg),
            "iam_ref": list(profile.iam_ref),
            "interpolation_method": profile.interpolation_method,
            "normalize": profile.normalize,
        }

    beam = frame["poa_beam_w_m2"].to_numpy(dtype=float)
    isotropic = frame["poa_isotropic_w_m2"].to_numpy(dtype=float)
    circumsolar = frame["poa_circumsolar_w_m2"].to_numpy(dtype=float)
    horizon = frame["poa_horizon_w_m2"].to_numpy(dtype=float)
    ground = frame["poa_ground_diffuse_w_m2"].to_numpy(dtype=float)
    incident = frame["poa_global_w_m2"].to_numpy(dtype=float)

    effective_beam = beam * beam_iam
    effective_circumsolar = circumsolar * beam_iam
    effective_isotropic = isotropic * diffuse["sky"]
    effective_horizon = horizon * diffuse["horizon"]
    effective_ground = ground * diffuse["ground"]
    effective_sky = effective_isotropic + effective_circumsolar + effective_horizon
    effective_diffuse = effective_sky + effective_ground
    effective_global = effective_beam + effective_diffuse

    output = pd.DataFrame(index=index.copy())
    output.index.name = "interval_start"
    if "evaluation_time" in frame:
        output["evaluation_time"] = frame["evaluation_time"].to_numpy()
    output["aoi_deg"] = aoi.to_numpy(dtype=float)
    output["iam_beam"] = beam_iam
    output["iam_sky"] = float(diffuse["sky"])
    output["iam_horizon"] = float(diffuse["horizon"])
    output["iam_ground"] = float(diffuse["ground"])
    output["effective_poa_beam_w_m2"] = effective_beam
    output["effective_poa_isotropic_w_m2"] = effective_isotropic
    output["effective_poa_circumsolar_w_m2"] = effective_circumsolar
    output["effective_poa_horizon_w_m2"] = effective_horizon
    output["effective_poa_sky_diffuse_w_m2"] = effective_sky
    output["effective_poa_ground_diffuse_w_m2"] = effective_ground
    output["effective_poa_diffuse_w_m2"] = effective_diffuse
    output["effective_irradiance_w_m2"] = effective_global
    output["incident_poa_global_w_m2"] = incident
    output["iam_delta_w_m2"] = incident - effective_global

    effective_component_sum = (
        output["effective_poa_beam_w_m2"]
        + output["effective_poa_sky_diffuse_w_m2"]
        + output["effective_poa_ground_diffuse_w_m2"]
    )
    if not np.allclose(
        effective_component_sum.to_numpy(dtype=float),
        output["effective_irradiance_w_m2"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-9,
        equal_nan=True,
    ):
        raise RuntimeError("effective irradiance components do not reconcile")

    sky_component_sum = (
        output["effective_poa_isotropic_w_m2"]
        + output["effective_poa_circumsolar_w_m2"]
        + output["effective_poa_horizon_w_m2"]
    )
    if not np.allclose(
        sky_component_sum.to_numpy(dtype=float),
        output["effective_poa_sky_diffuse_w_m2"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-9,
        equal_nan=True,
    ):
        raise RuntimeError("effective sky diffuse subcomponents do not reconcile")

    metadata = {
        "schema_name": "OpticalResult",
        "schema_version": "0.1",
        "model_id": model_id,
        "implementation": (
            "identity"
            if model_id == IAM_NONE
            else "pvlib.iam.physical + pvlib.iam.marion_integrate" if model_id == IAM_PHYSICAL_GLASS
            else "pvlib.iam.interp + pvlib.iam.marion_integrate"
        ),
        "pvlib_version": pvlib.__version__,
        "surface_tilt_deg": float(surface_tilt_deg),
        "circumsolar_policy": "beam_iam_at_solar_aoi",
        "diffuse_integration_method": (
            None if model_id == IAM_NONE else "Marion_2017_solid_angle"
        ),
        "profile": profile_metadata,
        "component_reconciliation_tolerance_w_m2": 1e-9,
    }
    return OpticalResult(frame=output, metadata=metadata)
