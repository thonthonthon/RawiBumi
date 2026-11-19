"""PVsyst steady-state and 8.1 transient module temperature models."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd
import pvlib

from engine.irradiance import PlaneOfArrayResult
from weather.core import CanonicalWeather


THERMAL_PVSYST = "thermal.pvsyst.pvlib.v0.1"
THERMAL_PVSYST_STEADY_STATE = THERMAL_PVSYST
THERMAL_PVSYST81_TRANSIENT = "thermal.pvsyst81.prilliman_adapted.v0.1"
DEFAULT_PVSYST81_UNIT_MASS_KG_M2 = 11.0
PVSYST81_INVALID_UNIT_MASS_THRESHOLD_KG_M2 = 20.0
SUPPORTED_THERMAL_MODELS = {
    THERMAL_PVSYST,
    THERMAL_PVSYST81_TRANSIENT,
}


@dataclass(frozen=True)
class ThermalResult:
    """Interval-start indexed PV module temperature state."""

    frame: pd.DataFrame
    metadata: dict[str, Any]


def _coerce_series_or_scalar(
    value: float | pd.Series | np.ndarray | list[float],
    *,
    index: pd.DatetimeIndex,
    name: str,
) -> np.ndarray:
    if np.isscalar(value):
        numeric = float(value)
        if not isfinite(numeric):
            raise ValueError(f"{name} must be finite")
        return np.full(len(index), numeric, dtype=float)

    if isinstance(value, pd.Series):
        array = value.reindex(index).to_numpy(dtype=float)
    else:
        array = np.asarray(value, dtype=float)

    if array.ndim != 1 or len(array) != len(index):
        raise ValueError(f"{name} must be scalar or one value per interval")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values")
    return array


def calculate_pvsyst_temperature(
    poa: PlaneOfArrayResult,
    weather: CanonicalWeather,
    *,
    u_c_w_m2k: float,
    u_v_w_m2k_per_ms: float,
    alpha_absorption: float,
    module_efficiency: float | pd.Series | np.ndarray | list[float],
    wind_speed_m_s: float | pd.Series | np.ndarray | list[float] | None = None,
) -> ThermalResult:
    """Calculate the PVsyst steady-state cell/module temperature.

    The incident POA before IAM is used for the heat balance. Optical reflection is
    represented by the explicit absorption coefficient rather than by substituting
    effective irradiance into the thermal equation.
    """
    if not poa.frame.index.equals(weather.series.index):
        raise ValueError("POA and weather intervals must align exactly")

    index = poa.frame.index
    if not isfinite(float(u_c_w_m2k)) or u_c_w_m2k < 0:
        raise ValueError("u_c_w_m2k must be finite and non-negative")
    if not isfinite(float(u_v_w_m2k_per_ms)) or u_v_w_m2k_per_ms < 0:
        raise ValueError("u_v_w_m2k_per_ms must be finite and non-negative")
    if not isfinite(float(alpha_absorption)) or not 0 <= alpha_absorption <= 1:
        raise ValueError("alpha_absorption must be finite and within 0..1")

    if "ambient_temperature_c" not in weather.series:
        raise ValueError("PVsyst thermal model requires ambient_temperature_c")
    temp_air = pd.to_numeric(
        weather.series["ambient_temperature_c"], errors="coerce"
    ).reindex(index)
    if temp_air.isna().any():
        raise ValueError("ambient_temperature_c must be complete for thermal modeling")

    poa_global = pd.to_numeric(
        poa.frame["poa_global_w_m2"], errors="coerce"
    ).reindex(index)
    if poa_global.isna().any() or (poa_global < 0).any():
        raise ValueError("PVsyst thermal model requires complete non-negative POA")

    efficiency = _coerce_series_or_scalar(
        module_efficiency,
        index=index,
        name="module_efficiency",
    )
    if ((efficiency < 0) | (efficiency >= 1)).any():
        raise ValueError("module_efficiency must lie within 0 <= eta < 1")

    if wind_speed_m_s is not None:
        wind = _coerce_series_or_scalar(
            wind_speed_m_s,
            index=index,
            name="wind_speed_m_s",
        )
        wind_source = "explicit_argument"
    elif "wind_speed_m_s" in weather.series:
        candidate = pd.to_numeric(
            weather.series["wind_speed_m_s"], errors="coerce"
        ).reindex(index)
        if candidate.notna().all():
            wind = candidate.to_numpy(dtype=float)
            wind_source = "canonical_weather.wind_speed_m_s"
        elif u_v_w_m2k_per_ms == 0:
            wind = np.zeros(len(index), dtype=float)
            wind_source = "not_required_uv_zero"
        else:
            raise ValueError(
                "wind_speed_m_s must be complete when u_v_w_m2k_per_ms is non-zero"
            )
    elif u_v_w_m2k_per_ms == 0:
        wind = np.zeros(len(index), dtype=float)
        wind_source = "not_required_uv_zero"
    else:
        raise ValueError(
            "wind_speed_m_s is required when u_v_w_m2k_per_ms is non-zero"
        )

    if (wind < 0).any():
        raise ValueError("wind_speed_m_s must be non-negative")

    loss_coefficient = float(u_c_w_m2k) + float(u_v_w_m2k_per_ms) * wind
    if (loss_coefficient <= 0).any():
        raise ValueError("PVsyst thermal heat-loss coefficient must be positive")

    incident = poa_global.to_numpy(dtype=float)
    ambient = temp_air.to_numpy(dtype=float)
    cell_temperature = np.asarray(
        pvlib.temperature.pvsyst_cell(
            incident,
            ambient,
            wind_speed=wind,
            u_c=float(u_c_w_m2k),
            u_v=float(u_v_w_m2k_per_ms),
            module_efficiency=efficiency,
            alpha_absorption=float(alpha_absorption),
        ),
        dtype=float,
    )
    absorbed_heat = incident * float(alpha_absorption) * (1.0 - efficiency)
    delta_temperature = cell_temperature - ambient

    output = pd.DataFrame(index=index.copy())
    output.index.name = "interval_start"
    if "evaluation_time" in poa.frame:
        output["evaluation_time"] = poa.frame["evaluation_time"].to_numpy()
    output["incident_poa_global_w_m2"] = incident
    output["ambient_temperature_c"] = ambient
    output["wind_speed_m_s"] = wind
    output["module_efficiency_fraction"] = efficiency
    output["alpha_absorption"] = float(alpha_absorption)
    output["heat_input_w_m2"] = absorbed_heat
    output["heat_loss_coefficient_w_m2k"] = loss_coefficient
    output["temperature_rise_c"] = delta_temperature
    output["cell_temperature_c"] = cell_temperature
    output["module_temperature_c"] = cell_temperature

    metadata = {
        "schema_name": "ThermalResult",
        "schema_version": "0.1",
        "model_id": THERMAL_PVSYST,
        "implementation": "pvlib.temperature.pvsyst_cell",
        "pvlib_version": pvlib.__version__,
        "u_c_w_m2k": float(u_c_w_m2k),
        "u_v_w_m2k_per_ms": float(u_v_w_m2k_per_ms),
        "alpha_absorption": float(alpha_absorption),
        "irradiance_basis": "incident_poa_global_before_iam",
        "module_efficiency_policy": (
            "scalar"
            if np.isscalar(module_efficiency)
            else "interval_series"
        ),
        "wind_speed_source": wind_source,
        "cell_module_temperature_equivalence": True,
        "temperature_state": "steady_state",
    }
    return ThermalResult(frame=output, metadata=metadata)


def _resolve_pvsyst81_unit_mass(
    module_unit_mass_kg_m2: float | None,
) -> tuple[float, str]:
    if module_unit_mass_kg_m2 is None:
        return DEFAULT_PVSYST81_UNIT_MASS_KG_M2, "pvsyst81_default_missing_mass"

    requested = float(module_unit_mass_kg_m2)
    if not isfinite(requested) or requested <= 0:
        raise ValueError("module_unit_mass_kg_m2 must be finite and positive")
    if requested >= PVSYST81_INVALID_UNIT_MASS_THRESHOLD_KG_M2:
        return (
            DEFAULT_PVSYST81_UNIT_MASS_KG_M2,
            "pvsyst81_default_invalid_mass_ge_20",
        )
    return requested, "component_mass_divided_by_one_sided_area"


def _validate_regular_thermal_timeline(
    weather: CanonicalWeather,
    index: pd.DatetimeIndex,
) -> float:
    raw = weather.dataset.get("series_resolution_seconds")
    if raw is None:
        raise ValueError(
            "PVsyst 8.1 transient thermal model requires series_resolution_seconds"
        )
    interval_seconds = float(raw)
    if not isfinite(interval_seconds) or interval_seconds <= 0:
        raise ValueError("series_resolution_seconds must be finite and positive")

    if len(index) > 1:
        deltas = (index[1:] - index[:-1]).total_seconds().to_numpy(dtype=float)
        if not np.allclose(deltas, interval_seconds, atol=1e-9, rtol=0.0):
            raise ValueError(
                "PVsyst 8.1 transient thermal model requires a regular interval-start "
                "timeline matching series_resolution_seconds"
            )
    return interval_seconds


def _pvsyst81_prilliman_boundaries(
    steady_temperature_c: np.ndarray,
    relaxation_rate_s_inv: np.ndarray,
    *,
    interval_seconds: float,
    cutoff_seconds: float,
) -> tuple[np.ndarray, int]:
    """Return Prilliman temperatures at interval boundaries.

    PVsyst documents a cutoff of 3*tau_max. For hourly simulations this cutoff can
    be shorter than one time step, while PVsyst 8.1 still applies the transient
    model. The immediate previous steady-state sample is therefore always retained;
    additional older samples are retained while they remain within the cutoff.
    """
    n = len(steady_temperature_c)
    if n == 0:
        return np.empty(0, dtype=float), 0

    lag_count = max(1, int(np.floor(cutoff_seconds / interval_seconds + 1e-12)))
    lag_count = min(lag_count, n)

    numerator = np.zeros(n + 1, dtype=float)
    denominator = np.zeros(n + 1, dtype=float)

    for lag in range(1, lag_count + 1):
        count = n - lag + 1
        if count <= 0:
            break
        source = slice(0, count)
        target = slice(lag, lag + count)
        weight = np.exp(
            -relaxation_rate_s_inv[source] * (float(lag) * interval_seconds)
        )
        numerator[target] += steady_temperature_c[source] * weight
        denominator[target] += weight

    boundaries = np.empty(n + 1, dtype=float)
    boundaries[0] = steady_temperature_c[0]
    if (denominator[1:] <= 0).any():
        raise RuntimeError("PVsyst 8.1 transient thermal history window is empty")
    boundaries[1:] = numerator[1:] / denominator[1:]
    return boundaries, lag_count


def calculate_pvsyst81_transient_temperature(
    steady_state: ThermalResult,
    weather: CanonicalWeather,
    *,
    module_unit_mass_kg_m2: float | None = None,
) -> ThermalResult:
    """Apply the PVsyst 8.1 adaptation of Prilliman thermal inertia.

    The input is the PVsyst steady-state thermal result. The returned
    cell_temperature_c/module_temperature_c are the interval-average transient
    temperatures used by the electrical model, while steady-state values remain
    explicitly available for audit.

    The relaxation and Prilliman-history equations follow the current PVsyst 8.1
    documentation. The interval average is evaluated as the exact analytical
    integral of the documentation's exponential transition equation (Eq. 3).
    The currently rendered PVsyst Eq. 4 is algebraically inconsistent with Eq. 3,
    so literal Eq. 4 rendering is not treated as an executable formula.
    """
    frame = steady_state.frame
    index = frame.index
    if not index.equals(weather.series.index):
        raise ValueError("steady-state thermal and weather intervals must align exactly")
    required = {
        "cell_temperature_c",
        "ambient_temperature_c",
        "module_efficiency_fraction",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            "steady-state thermal result is missing required columns: "
            + ", ".join(missing)
        )

    interval_seconds = _validate_regular_thermal_timeline(weather, index)

    if "wind_speed_m_s" not in weather.series:
        raise ValueError(
            "PVsyst 8.1 transient thermal model requires weather wind_speed_m_s "
            "even when the steady-state Uv coefficient is zero"
        )
    wind_series = pd.to_numeric(
        weather.series["wind_speed_m_s"], errors="coerce"
    ).reindex(index)
    if wind_series.isna().any():
        raise ValueError(
            "PVsyst 8.1 transient thermal model requires complete wind_speed_m_s"
        )
    wind = wind_series.to_numpy(dtype=float)
    if (wind < 0).any():
        raise ValueError("wind_speed_m_s must be non-negative")

    unit_mass, unit_mass_source = _resolve_pvsyst81_unit_mass(
        module_unit_mass_kg_m2
    )
    relaxation_rate = (
        0.0046
        + 0.00046 * wind
        - 0.00023 * unit_mass
        - 0.000016 * wind * unit_mass
    )
    if (relaxation_rate <= 0).any() or not np.isfinite(relaxation_rate).all():
        raise ValueError(
            "PVsyst 8.1 transient thermal relaxation rate must remain positive"
        )

    zero_wind_rate = 0.0046 - 0.00023 * unit_mass
    if zero_wind_rate <= 0:
        raise ValueError("resolved PVsyst 8.1 unit mass produces invalid tau_max")
    tau_max_seconds = 1.0 / zero_wind_rate
    cutoff_seconds = 3.0 * tau_max_seconds

    steady_temperature = pd.to_numeric(
        frame["cell_temperature_c"], errors="coerce"
    ).to_numpy(dtype=float)
    if not np.isfinite(steady_temperature).all():
        raise ValueError("steady-state cell temperature must be complete and finite")

    boundaries, lag_count = _pvsyst81_prilliman_boundaries(
        steady_temperature,
        relaxation_rate,
        interval_seconds=interval_seconds,
        cutoff_seconds=cutoff_seconds,
    )

    x = relaxation_rate * interval_seconds
    average_response_fraction = np.empty_like(x)
    small = np.abs(x) < 1e-6
    average_response_fraction[small] = (
        x[small] / 2.0
        - x[small] * x[small] / 6.0
        + x[small] * x[small] * x[small] / 24.0
    )
    average_response_fraction[~small] = (
        1.0 + np.expm1(-x[~small]) / x[~small]
    )

    transient_temperature = (
        boundaries[:-1]
        + (boundaries[1:] - boundaries[:-1]) * average_response_fraction
    )

    output = frame.copy(deep=True)
    ambient = pd.to_numeric(
        output["ambient_temperature_c"], errors="coerce"
    ).to_numpy(dtype=float)
    output["wind_speed_m_s"] = wind
    output["steady_state_temperature_rise_c"] = (
        steady_temperature - ambient
    )
    output["steady_state_cell_temperature_c"] = steady_temperature
    output["steady_state_module_temperature_c"] = steady_temperature
    output["prilliman_interval_start_temperature_c"] = boundaries[:-1]
    output["prilliman_interval_end_temperature_c"] = boundaries[1:]
    output["thermal_relaxation_rate_s_inv"] = relaxation_rate
    output["thermal_relaxation_time_s"] = 1.0 / relaxation_rate
    output["thermal_cutoff_seconds"] = cutoff_seconds
    output["transient_average_response_fraction"] = average_response_fraction
    output["temperature_rise_c"] = transient_temperature - ambient
    output["cell_temperature_c"] = transient_temperature
    output["module_temperature_c"] = transient_temperature

    metadata = dict(steady_state.metadata)
    metadata.update(
        {
            "model_id": THERMAL_PVSYST81_TRANSIENT,
            "implementation": "opensimpv_pvsyst81_prilliman_adapted",
            "base_steady_state_model_id": steady_state.metadata.get("model_id"),
            "temperature_state": "interval_average_transient",
            "pvsyst_compatibility_target": "8.1.x",
            "module_unit_mass_kg_m2": float(unit_mass),
            "module_unit_mass_source": unit_mass_source,
            "default_unit_mass_kg_m2": DEFAULT_PVSYST81_UNIT_MASS_KG_M2,
            "invalid_unit_mass_threshold_kg_m2": (
                PVSYST81_INVALID_UNIT_MASS_THRESHOLD_KG_M2
            ),
            "tau_max_seconds": float(tau_max_seconds),
            "cutoff_seconds": float(cutoff_seconds),
            "history_lag_count": int(lag_count),
            "simulation_interval_seconds": float(interval_seconds),
            "wind_speed_source": "canonical_weather.wind_speed_m_s",
            "wind_required_for_thermal_inertia": True,
            "cutoff_under_timestep_policy": (
                "always_include_immediate_previous_steady_state_sample"
            ),
            "initialization_policy": "first_steady_state_boundary",
            "interval_average_equation": (
                "T0 + (T1-T0) * (1 - (1-exp(-P*dt))/(P*dt))"
            ),
            "interval_average_formula_basis": (
                "exact_analytical_integral_of_documented_exponential_transition_eq3"
            ),
            "published_eq4_consistency_status": (
                "rendered_eq4_is_algebraically_inconsistent_with_eq3"
            ),
            "compatibility_note": (
                "Implements the documented PVsyst 8.1 relaxation and Prilliman "
                "history equations and the exact analytical integral of the "
                "documented exponential transition. The currently rendered PVsyst "
                "Eq. 4 is not used literally because it is algebraically inconsistent "
                "with Eq. 3. When 3*tau_max is shorter than the simulation step, the "
                "immediate previous steady-state sample is retained so the hourly "
                "model remains defined; both details must remain visible in the "
                "PVsyst 8.1.6 attribution campaign."
            ),
        }
    )
    return ThermalResult(frame=output, metadata=metadata)
