"""Resolution-explicit power/irradiance integration and PV KPIs."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EnergyAggregationResult:
    interval: pd.DataFrame
    monthly: pd.DataFrame
    annual: dict[str, float]
    metadata: dict[str, Any]


def _durations_seconds(
    interval_seconds: float | pd.Series | np.ndarray | list[float],
    *,
    index: pd.DatetimeIndex,
) -> np.ndarray:
    if np.isscalar(interval_seconds):
        value = float(interval_seconds)
        if not isfinite(value) or value <= 0:
            raise ValueError("interval_seconds must be finite and positive")
        return np.full(len(index), value, dtype=float)
    if isinstance(interval_seconds, pd.Series):
        values = interval_seconds.reindex(index).to_numpy(dtype=float)
    else:
        values = np.asarray(interval_seconds, dtype=float)
    if values.ndim != 1 or len(values) != len(index):
        raise ValueError(
            "interval_seconds must be scalar or contain one value per interval"
        )
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("interval durations must be finite and positive")
    return values


def aggregate_interval_quantities(
    frame: pd.DataFrame,
    *,
    interval_seconds: float | pd.Series | np.ndarray | list[float],
    power_columns_w: Iterable[str] = (),
    irradiance_columns_w_m2: Iterable[str] = (),
) -> EnergyAggregationResult:
    """Integrate interval-average powers/irradiances using explicit durations.

    Timestamp spacing is not used to guess the final interval duration. The caller must
    pass the canonical working interval duration(s).
    """
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("aggregation frame must use a DatetimeIndex")
    if not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        raise ValueError("aggregation index must be unique and monotonic")

    power_columns = list(power_columns_w)
    irradiance_columns = list(irradiance_columns_w_m2)
    requested = power_columns + irradiance_columns
    missing = [column for column in requested if column not in frame.columns]
    if missing:
        raise ValueError(f"aggregation columns are missing: {missing}")

    durations = _durations_seconds(interval_seconds, index=frame.index)
    hours = durations / 3600.0

    interval = pd.DataFrame(index=frame.index.copy())
    interval.index.name = frame.index.name or "interval_start"
    interval["interval_seconds"] = durations

    for column in power_columns:
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"power column {column!r} contains non-finite values")
        interval[column.replace("_w", "_wh")] = values * hours

    for column in irradiance_columns:
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(
                f"irradiance column {column!r} contains non-finite values"
            )
        interval[column.replace("_w_m2", "_wh_m2")] = values * hours

    energy_columns = [column for column in interval.columns if column != "interval_seconds"]
    month_keys = frame.index.strftime("%Y-%m")
    monthly_wh = interval[energy_columns].groupby(month_keys).sum()
    monthly = monthly_wh / 1000.0
    monthly.columns = [
        column.replace("_wh_m2", "_kwh_m2").replace("_wh", "_kwh")
        for column in monthly.columns
    ]
    monthly.index.name = "month"

    annual: dict[str, float] = {}
    for column in energy_columns:
        value_k = float(interval[column].sum() / 1000.0)
        key = column.replace("_wh_m2", "_kwh_m2").replace("_wh", "_kwh")
        annual[key] = value_k

    metadata = {
        "schema_name": "EnergyAggregationResult",
        "schema_version": "0.1",
        "integration_method": "interval_average_times_explicit_duration",
        "duration_source_policy": "caller_supplied_canonical_interval_seconds",
        "power_columns_w": power_columns,
        "irradiance_columns_w_m2": irradiance_columns,
    }
    return EnergyAggregationResult(
        interval=interval,
        monthly=monthly,
        annual=annual,
        metadata=metadata,
    )


def calculate_pv_kpis(
    *,
    grid_energy_kwh: float,
    installed_dc_kwp: float,
    incident_poa_kwh_m2: float,
    reference_irradiance_kw_m2: float = 1.0,
) -> dict[str, float]:
    """Return specific yield, reference yield, and IEC-style performance ratio."""
    for value, name in (
        (grid_energy_kwh, "grid_energy_kwh"),
        (installed_dc_kwp, "installed_dc_kwp"),
        (incident_poa_kwh_m2, "incident_poa_kwh_m2"),
        (reference_irradiance_kw_m2, "reference_irradiance_kw_m2"),
    ):
        if not isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    if installed_dc_kwp <= 0:
        raise ValueError("installed_dc_kwp must be positive")
    if incident_poa_kwh_m2 < 0:
        raise ValueError("incident_poa_kwh_m2 must be non-negative")
    if reference_irradiance_kw_m2 <= 0:
        raise ValueError("reference_irradiance_kw_m2 must be positive")

    specific_yield = float(grid_energy_kwh) / float(installed_dc_kwp)
    reference_yield_h = (
        float(incident_poa_kwh_m2) / float(reference_irradiance_kw_m2)
    )
    pr = (
        specific_yield / reference_yield_h
        if reference_yield_h > 0
        else 0.0
    )
    return {
        "specific_yield_kwh_per_kwp": specific_yield,
        "reference_yield_h": reference_yield_h,
        "performance_ratio": pr,
    }
