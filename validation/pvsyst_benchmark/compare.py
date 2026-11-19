"""Stage metrics with basis/coverage gates; no calibration."""

import numpy as np
import pandas as pd
from .reference import Basis


TOLERANCES = {
    "transposition": {
        "annual_relative": 0.005,
        "monthly_relative": 0.01,
        "nrmse": 0.02,
    },
    "beam_shading": {"weighted_mae": 0.005, "rmse": 0.02},
    "sky_ground_shading": {"weighted_mae": 0.01},
    "iam": {"factor_mae": 0.0015, "annual_upstream_relative": 0.003},
    "soiling": {"factor_mae": 0.0001},
    "effective_irradiance": {
        "annual_relative": 0.01,
        "monthly_relative": 0.02,
        "nrmse": 0.03,
    },
    "temperature": {"bias_c": 0.2, "rmse_c": 0.5},
    "array": {"annual_relative": 0.015, "monthly_relative": 0.03, "nrmse": 0.05},
    "inverter": {"annual_upstream_relative": 0.005},
    "night": {"annual_upstream_relative": 0.0001},
    "ac": {"annual_upstream_relative": 0.002},
    "grid": {"annual_relative": 0.03, "monthly_relative": 0.05},
}


def _aligned(reference, actual):
    if (
        not isinstance(reference, pd.Series)
        or not isinstance(actual, pd.Series)
        or not reference.index.equals(actual.index)
        or not reference.index.is_unique
        or len(reference) == 0
    ):
        raise ValueError("series must have identical unique complete indices")
    r, a = np.asarray(reference, dtype=float), np.asarray(actual, dtype=float)
    if not np.isfinite(r).all() or not np.isfinite(a).all():
        raise ValueError("comparison contains non-finite values")
    return r, a


def stage_metrics(
    reference,
    actual,
    *,
    reference_basis: Basis,
    actual_basis: Basis,
    duration_hours=1.0
):
    if reference_basis == Basis.UNAVAILABLE or reference_basis != actual_basis:
        return {
            "status": "unavailable",
            "reason": "unproved_or_mismatched_reference_basis",
        }
    r, a = _aligned(reference, actual)
    if not np.isfinite(duration_hours) or duration_hours <= 0:
        raise ValueError("invalid duration")
    d = a - r
    scale = float(np.mean(abs(r)))
    monthly = []
    for month in sorted(set(reference.index.strftime("%Y-%m"))):
        mask = reference.index.strftime("%Y-%m") == month
        rs = float(r[mask].sum() * duration_hours)
        ac = float(a[mask].sum() * duration_hours)
        monthly.append(
            {
                "month": month,
                "reference_integral": rs,
                "actual_integral": ac,
                "relative_deviation": (ac - rs) / abs(rs) if rs != 0 else None,
            }
        )
    return {
        "status": "compared",
        "basis": reference_basis.value,
        "rows": len(r),
        "hourly_bias": float(d.mean()),
        "hourly_rmse": float(np.sqrt(np.mean(d * d))),
        "hourly_nrmse": float(np.sqrt(np.mean(d * d)) / scale) if scale else None,
        "annual_reference_integral": float(r.sum() * duration_hours),
        "annual_actual_integral": float(a.sum() * duration_hours),
        "signed_integral_relative_deviation": (
            float(d.sum() / abs(r.sum())) if r.sum() != 0 else None
        ),
        "absolute_source_normalized_bias": (
            float(d.sum() / abs(r).sum()) if abs(r).sum() != 0 else None
        ),
        "monthly": monthly,
    }


def factor_metrics(reference, actual, source_flux):
    r, a = _aligned(reference, actual)
    _, flux = _aligned(reference, source_flux)
    if (flux < 0).any():
        raise ValueError("factor weighting flux must be non-negative")
    active = flux > 0
    if not active.any():
        return {
            "status": "unavailable",
            "reason": "zero_source_flux",
            "zero_source_rows": len(r),
        }
    w = flux[active] / flux[active].sum()
    d = (a - r)[active]
    return {
        "status": "compared",
        "weighted_mae": float(np.dot(w, abs(d))),
        "weighted_rmse": float(np.sqrt(np.dot(w, d * d))),
        "weighted_bias": float(np.dot(w, d)),
        "zero_source_rows": int((~active).sum()),
    }


def grid_verdict(annual_relative, monthly_relative):
    """Pure boundary logic for future runs/synthetic tests, never used by VAL1a."""
    if len(monthly_relative) != 12 or any(
        x is None or not np.isfinite(x) for x in [annual_relative, *monthly_relative]
    ):
        return "unavailable"
    return (
        "pass"
        if abs(annual_relative) <= 0.03
        and all(abs(x) <= 0.05 for x in monthly_relative)
        else "fail"
    )
