"""Voltage-dependent inverter conversion, thresholds, and clipping for Phase 3."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

import numpy as np
import pandas as pd

from electrical.mppt import MPPTAggregationResult


INVERTER_VOLTAGE_DEPENDENT = "inverter.voltage_dependent_efficiency.v0.1"
INVERTER_VOLTAGE_DEPENDENT_BOUNDED = "inverter.voltage_dependent_efficiency.v0.2"
ADJACENT_ENVELOPE_POLICY = "adjacent_envelope_clamped_quadratic_v0.2"


def inverter_voltage_interpolation_policy(model_id: str) -> str:
    """Resolve a versioned model's sole voltage-policy selector."""
    if model_id == INVERTER_VOLTAGE_DEPENDENT:
        return "bounded_quadratic_v0.1"
    if model_id == INVERTER_VOLTAGE_DEPENDENT_BOUNDED:
        return ADJACENT_ENVELOPE_POLICY
    raise ValueError(f"unsupported inverter model {model_id!r}")


@dataclass(frozen=True)
class InverterElectricalResult:
    """Interval-start indexed inverter conversion and loss state."""

    frame: pd.DataFrame
    metadata: dict[str, Any]


def _positive(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
        and float(value) > 0
    )


def _nonnegative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
        and float(value) >= 0
    )


def _runtime_ready(inverter: dict[str, Any]) -> None:
    efficiency = inverter.get("efficiency_model") or {}
    if efficiency.get("model_type") != "voltage_dependent_curves":
        raise ValueError(
            "Phase 3.6 detailed runtime requires voltage_dependent_curves efficiency data"
        )
    curves = efficiency.get("curves") or []
    if len(curves) < 2:
        raise ValueError("voltage-dependent inverter model requires at least two curves")

    ac = inverter.get("ac_limits") or {}
    if not _positive(ac.get("nominal_ac_power_w")):
        raise ValueError("inverter requires nominal AC power")
    if not _positive(ac.get("max_ac_power_w") or ac.get("nominal_ac_power_w")):
        raise ValueError("inverter requires a positive AC output power limit")

    template = inverter.get("mppt_template") or {}
    if not _nonnegative(template.get("min_operating_voltage_v")):
        raise ValueError("inverter requires MPPT minimum operating voltage")
    if not _positive(template.get("max_operating_voltage_v")):
        raise ValueError("inverter requires MPPT maximum operating voltage")


def _curve_ac_output_w(curve: dict[str, Any], dc_power_w: float) -> float:
    """Bounded linear Pin/Pout interpolation for one OND voltage anchor.

    Above the highest source point, the endpoint efficiency is held constant instead
    of clamping AC power. This keeps conversion efficiency bounded while allowing the
    separate AC power-limit stage to represent clipping.
    """
    points = sorted(
        curve.get("points") or [],
        key=lambda item: float(item["dc_power_w"]),
    )
    if len(points) < 2:
        raise ValueError("inverter efficiency curve requires at least two points")

    pin = np.asarray([float(item["dc_power_w"]) for item in points], dtype=float)
    pout = np.asarray([float(item["ac_power_w"]) for item in points], dtype=float)
    if not np.isfinite(pin).all() or not np.isfinite(pout).all():
        raise ValueError("inverter efficiency curve contains non-finite values")
    if (np.diff(pin) <= 0).any():
        raise ValueError("inverter efficiency curve DC powers must be strictly increasing")
    if (pin < 0).any() or (pout < 0).any():
        raise ValueError("inverter efficiency curve powers must be non-negative")

    power = float(dc_power_w)
    if power <= 0:
        return 0.0
    if power <= pin[0]:
        value = float(pout[0])
    elif power >= pin[-1]:
        endpoint_efficiency = float(pout[-1] / pin[-1]) if pin[-1] > 0 else 0.0
        value = power * endpoint_efficiency
    else:
        value = float(np.interp(power, pin, pout))

    return float(np.clip(value, 0.0, power))


def _quadratic_voltage_output_w(
    *,
    voltage_v: float,
    dc_power_w: float,
    curves: list[dict[str, Any]],
) -> float:
    anchors = np.asarray(
        [float(curve["dc_voltage_v"]) for curve in curves],
        dtype=float,
    )
    order = np.argsort(anchors)
    anchors = anchors[order]
    ordered_curves = [curves[index] for index in order]

    if not np.isfinite(anchors).all() or (np.diff(anchors) <= 0).any():
        raise ValueError("inverter curve voltage anchors must be finite and increasing")

    voltage = float(np.clip(float(voltage_v), anchors[0], anchors[-1]))
    outputs = np.asarray(
        [_curve_ac_output_w(curve, dc_power_w) for curve in ordered_curves],
        dtype=float,
    )

    if len(anchors) >= 3:
        # Use the nearest three anchors for a bounded quadratic interpolation.
        nearest = np.argsort(np.abs(anchors - voltage))[:3]
        nearest = np.sort(nearest)
        x = anchors[nearest]
        y = outputs[nearest]
        result = 0.0
        for i in range(3):
            basis = 1.0
            for j in range(3):
                if i != j:
                    basis *= (voltage - x[j]) / (x[i] - x[j])
            result += y[i] * basis
        value = float(result)
    else:
        value = float(np.interp(voltage, anchors, outputs))

    return float(np.clip(value, 0.0, float(dc_power_w)))


def _adjacent_envelope_quadratic(
    voltage_v: float, anchors: np.ndarray, outputs: np.ndarray
) -> tuple[float, float, float]:
    """Unchanged nearest-three polynomial, bounded by its adjacent anchors."""
    voltage = float(np.clip(voltage_v, anchors[0], anchors[-1]))
    nearest = np.sort(np.argsort(np.abs(anchors - voltage))[:3])
    x, y = anchors[nearest], outputs[nearest]
    result = 0.0
    for i in range(3):
        basis = 1.0
        for j in range(3):
            if i != j:
                basis *= (voltage - x[j]) / (x[i] - x[j])
        result += y[i] * basis
    bracket = min(max(int(np.searchsorted(anchors, voltage, side="right")) - 1, 0), len(anchors) - 2)
    lower = float(min(outputs[bracket], outputs[bracket + 1]))
    upper = float(max(outputs[bracket], outputs[bracket + 1]))
    return float(np.clip(result, lower, upper)), lower, upper


def evaluate_voltage_dependent_conversion(
    efficiency_model: dict[str, Any],
    *,
    dc_power_w: float,
    tracker_voltages_v: np.ndarray,
    tracker_powers_w: np.ndarray,
    model_id: str = INVERTER_VOLTAGE_DEPENDENT,
) -> tuple[float, float]:
    """Return unclipped AC power and effective conversion efficiency.

    The OND efficiency curves describe the whole inverter. For multiple independent
    trackers, each tracker voltage is therefore used to evaluate the inverter-wide
    transfer curve at total DC power, and those efficiencies are weighted by tracker
    DC-power share. This avoids applying inverter fixed losses once per MPPT.
    """
    inverter_voltage_interpolation_policy(model_id)
    power = float(dc_power_w)
    if power <= 0:
        return 0.0, 0.0

    curves = list(efficiency_model.get("curves") or [])
    if len(curves) < 2:
        raise ValueError("voltage-dependent inverter model requires at least two curves")

    voltages = np.asarray(tracker_voltages_v, dtype=float)
    tracker_power = np.asarray(tracker_powers_w, dtype=float)
    if (
        voltages.ndim != 1
        or tracker_power.ndim != 1
        or len(voltages) != len(tracker_power)
    ):
        raise ValueError("tracker voltage and power vectors must have equal one-dimensional shape")
    if not np.isfinite(voltages).all() or not np.isfinite(tracker_power).all():
        raise ValueError("tracker voltage/power vectors must be finite")
    if (tracker_power < 0).any():
        raise ValueError("tracker power must be non-negative")

    active = tracker_power > 0
    if not active.any():
        return 0.0, 0.0

    bounded = model_id == INVERTER_VOLTAGE_DEPENDENT_BOUNDED and len(curves) >= 3
    if bounded:
        anchors = np.asarray([float(c["dc_voltage_v"]) for c in curves], dtype=float)
        order = np.argsort(anchors)
        anchors = anchors[order]
        if not np.isfinite(anchors).all() or (np.diff(anchors) <= 0).any():
            raise ValueError("inverter curve voltage anchors must be finite and increasing")
        outputs = np.asarray([_curve_ac_output_w(curves[i], power) for i in order], dtype=float)
        weighted_lower = weighted_upper = 0.0
    weighted_efficiency = 0.0
    for voltage, tracker_pdc in zip(voltages[active], tracker_power[active]):
        if bounded:
            ac_at_voltage, lower, upper = _adjacent_envelope_quadratic(float(voltage), anchors, outputs)
            weighted_lower += (float(tracker_pdc) / power) * lower
            weighted_upper += (float(tracker_pdc) / power) * upper
        else:
            ac_at_voltage = _quadratic_voltage_output_w(
                voltage_v=float(voltage),
                dc_power_w=power,
                curves=curves,
            )
        eta_at_voltage = ac_at_voltage / power
        weighted_efficiency += (float(tracker_pdc) / power) * eta_at_voltage

    weighted_efficiency = float(np.clip(weighted_efficiency, 0.0, 1.0))
    if bounded:
        # Mathematical convex bounds also guard the final floating-point round trip.
        global_lower, global_upper = float(outputs.min()), float(outputs.max())
        lower = max(0.0, global_lower, min(weighted_lower, global_upper, power))
        upper = min(power, global_upper, max(weighted_upper, lower))
        ac = float(np.clip(power * weighted_efficiency, lower, upper))
        return ac, ac / power
    return power * weighted_efficiency, weighted_efficiency


def _coerce_temperature(
    value: float | pd.Series | np.ndarray | list[float],
    *,
    index: pd.DatetimeIndex,
) -> np.ndarray:
    if np.isscalar(value):
        numeric = float(value)
        if not isfinite(numeric):
            raise ValueError("inverter temperature must be finite")
        return np.full(len(index), numeric, dtype=float)
    if isinstance(value, pd.Series):
        array = value.reindex(index).to_numpy(dtype=float)
    else:
        array = np.asarray(value, dtype=float)
    if array.ndim != 1 or len(array) != len(index):
        raise ValueError("inverter temperature must be scalar or one value per interval")
    if not np.isfinite(array).all():
        raise ValueError("inverter temperature must contain only finite values")
    return array


def _ac_power_limit(
    inverter: dict[str, Any],
    *,
    index: pd.DatetimeIndex,
    inverter_temperature_c: float | pd.Series | np.ndarray | list[float] | None,
    temperature_basis: str | None,
) -> tuple[np.ndarray, dict[str, Any]]:
    ac = inverter.get("ac_limits") or {}
    nominal = float(ac["nominal_ac_power_w"])
    maximum = float(ac.get("max_ac_power_w") or nominal)

    if inverter_temperature_c is None:
        return np.full(len(index), maximum, dtype=float), {
            "temperature_derating_applied": False,
            "temperature_basis": None,
            "temperature_derating_reason": "runtime_temperature_not_supplied",
        }

    derating = inverter.get("temperature_derating_model") or {}
    required = (
        "max_power_temperature_c",
        "nominal_power_temperature_c",
        "limit1_temperature_c",
        "limit1_power_w",
    )
    if any(derating.get(key) is None for key in required):
        raise ValueError(
            "inverter temperature supplied but component derating breakpoints are incomplete"
        )
    if temperature_basis in {None, "unknown"}:
        raise ValueError(
            "temperature_basis must be explicitly resolved before applying inverter derating"
        )

    component_basis = derating.get("temperature_basis")
    if component_basis not in {None, "unknown", temperature_basis}:
        raise ValueError(
            "runtime inverter temperature basis conflicts with component derating basis"
        )

    temperature = _coerce_temperature(inverter_temperature_c, index=index)
    t_max = float(derating["max_power_temperature_c"])
    t_nom = float(derating["nominal_power_temperature_c"])
    t_lim1 = float(derating["limit1_temperature_c"])
    p_lim1 = float(derating["limit1_power_w"])
    if not (t_max < t_nom < t_lim1):
        raise ValueError("inverter derating temperatures must be strictly increasing")
    if not (0 <= p_lim1 <= nominal <= maximum):
        raise ValueError("inverter derating power breakpoints are inconsistent")

    absolute = derating.get("absolute_limit_temperature_c")
    if absolute is not None:
        absolute = float(absolute)
        if (temperature >= absolute).any():
            raise ValueError(
                "inverter temperature reaches the absolute limit, but no verified "
                "post-limit power behavior is defined"
            )

    limit = np.empty(len(index), dtype=float)
    for i, temp in enumerate(temperature):
        if temp <= t_max:
            limit[i] = maximum
        elif temp <= t_nom:
            limit[i] = maximum + (nominal - maximum) * (
                (temp - t_max) / (t_nom - t_max)
            )
        elif temp <= t_lim1:
            limit[i] = nominal + (p_lim1 - nominal) * (
                (temp - t_nom) / (t_lim1 - t_nom)
            )
        else:
            # Bounded at the last verified power point. TPLimAbs is not silently
            # converted into a zero-power endpoint.
            limit[i] = p_lim1

    return limit, {
        "temperature_derating_applied": True,
        "temperature_basis": temperature_basis,
        "temperature_derating_reason": "explicit_runtime_temperature",
    }


def _mppt_limits(
    inverter: dict[str, Any],
    mppt_index: int,
) -> dict[str, float | None]:
    explicit = inverter.get("mppts") or []
    if explicit:
        found = next(
            (item for item in explicit if int(item.get("mppt_index", -1)) == mppt_index),
            None,
        )
        if found is None:
            raise ValueError(f"inverter has no definition for MPPT {mppt_index}")
        return {
            "min_voltage": float(found["min_operating_voltage_v"]),
            "max_voltage": float(found["max_operating_voltage_v"]),
            "max_current": (
                float(found["max_operating_current_a"])
                if _positive(found.get("max_operating_current_a"))
                else None
            ),
        }

    template = inverter.get("mppt_template") or {}
    count = int(template.get("count") or 0)
    if mppt_index < 1 or mppt_index > count:
        raise ValueError(f"MPPT {mppt_index} exceeds inverter MPPT count {count}")
    return {
        "min_voltage": float(template["min_operating_voltage_v"]),
        "max_voltage": float(template["max_operating_voltage_v"]),
        "max_current": (
            float(template["max_operating_current_a"])
            if _positive(template.get("max_operating_current_a"))
            else None
        ),
    }


MPPT_CURRENT_LIMIT_POLICY = "sdm_constrained_operating_point.v1"
_SDM_COLUMNS = (
    "sdm_photocurrent_a",
    "sdm_saturation_current_a",
    "sdm_series_resistance_ohm",
    "sdm_shunt_resistance_ohm",
    "sdm_nnsvth_v",
)


def _branch_point(voltage_v, current_a, k: float, resistance: float, limit: float) -> tuple[float, float]:
    """Best admissible point on a sampled branch (ascending voltage) after the loss mapping.

    Admissible means a post-loss current at or below the limit; a shaded curve may peak again further right, so the
    highest-power sample competes with the interpolated point where the current equals the limit.
    """
    raw_v, raw_i = np.asarray(voltage_v, dtype=float), np.asarray(current_a, dtype=float)
    post_i = k * raw_i
    post_v = raw_v - post_i * resistance
    inside = np.flatnonzero(post_i <= limit)
    if not len(inside) or inside[0] == 0:
        raise ValueError("current-limit branch does not cross the MPPT current limit")
    j = int(inside[0])
    t = (post_i[j - 1] - limit) / (post_i[j - 1] - post_i[j])
    boundary_v = raw_v[j - 1] + t * (raw_v[j] - raw_v[j - 1]) - limit * resistance
    candidates_v = np.concatenate(([boundary_v], post_v[j:]))
    candidates_i = np.concatenate(([limit], post_i[j:]))
    best = int(np.argmax(candidates_v * candidates_i))
    return float(candidates_v[best]), float(candidates_i[best])


def constrain_mppt_current(
    frame: pd.DataFrame, max_current_a: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Move a binding MPPT to the best operating point whose current is within the limit.

    The post-loss curve is the raw curve with the loss chain's current factor
    ``k = I_post / I_raw`` and wiring resistance ``R = (V_raw - V_post) / I_post``, both
    recovered at the MPP from the carried ``source_mpp_*`` columns. The raw curve is the
    module single-diode model (standard path: ``V = N_s * v_from_i(I_max / (k * N_p))``,
    where the boundary point is the optimum) or the sampled branch carried by the
    detailed path (``current_limit_branch``).

    The solved voltage is authoritative, even when its power exceeds the engine's
    post-loss MPP convention and the signed current-limit loss becomes a gain.
    Returns (pmp, vmp, imp, binding).
    """
    pmp = frame["mppt_pmp_w"].to_numpy(dtype=float).copy()
    vmp = frame["mppt_vmp_v"].to_numpy(dtype=float).copy()
    imp = frame["mppt_imp_a"].to_numpy(dtype=float).copy()
    active = frame["active"].to_numpy(dtype=bool)
    limit = float(max_current_a)
    binding = active & (imp > limit)
    if not binding.any():
        return pmp, vmp, imp, binding
    sdm = all(column in frame for column in ("modules_in_series", "string_count", *_SDM_COLUMNS))
    branches = frame["current_limit_branch"].to_numpy(dtype=object)[binding] if "current_limit_branch" in frame else None
    missing = [c for c in ("source_mpp_vmp_v", "source_mpp_imp_a") if c not in frame]
    if missing or (not sdm and (branches is None or any(b is None for b in branches))):
        raise ValueError(
            "MPPT operating-current limit binds but the MPPT carries no IV model; full IV "
            "operating-point solving is required"
        )

    def column(name: str) -> np.ndarray:
        return frame[name].to_numpy(dtype=float)[binding]

    k = imp[binding] / column("source_mpp_imp_a")
    resistance = (column("source_mpp_vmp_v") - vmp[binding]) / imp[binding]
    if not (np.isfinite(k).all() and (k > 0).all() and np.isfinite(resistance).all() and (resistance > -1e-9).all()):
        raise ValueError("MPPT loss chain is not a current scaling plus series resistance; cannot constrain current")
    resistance = np.maximum(resistance, 0.0)
    if sdm:
        import pvlib

        module_current = limit / (k * column("string_count"))
        module_voltage = pvlib.pvsystem.v_from_i(
            module_current, *(column(name) for name in _SDM_COLUMNS), method="lambertw"
        )
        voltage = column("modules_in_series") * np.asarray(module_voltage, dtype=float) - limit * resistance
        current = np.full(len(voltage), limit)
    else:
        points = [_branch_point(v, i, kk, r, limit) for (v, i), kk, r in zip(branches, k, resistance)]
        voltage = np.array([v for v, _ in points])
        current = np.array([i for _, i in points])
    power = voltage * current
    if not np.isfinite(power).all() or (voltage <= 0).any():
        raise ValueError("MPPT current-limited operating point has no positive voltage")
    pmp[binding] = power
    imp[binding] = current
    vmp[binding] = voltage
    return pmp, vmp, imp, binding


def simulate_voltage_dependent_inverter(
    mppt_bank: Mapping[int, MPPTAggregationResult],
    inverter: dict[str, Any],
    *,
    inverter_temperature_c: float | pd.Series | np.ndarray | list[float] | None = None,
    temperature_basis: str | None = None,
    model_id: str = INVERTER_VOLTAGE_DEPENDENT,
) -> InverterElectricalResult:
    """Convert MPPT MPP power to AC with explicit thresholds and clipping.

    A binding MPPT operating-current limit moves that MPPT to the constrained point on
    its IV curve (``constrain_mppt_current``); the difference is the
    ``mppt_current_limit_loss_w`` channel, emitted whenever any limit is known. The
    voltage window is then judged at the operating voltage.
    """
    policy = inverter_voltage_interpolation_policy(model_id)
    _runtime_ready(inverter)
    if not mppt_bank:
        raise ValueError("mppt_bank must not be empty")

    mppts = [mppt_bank[index] for index in sorted(mppt_bank)]
    index = mppts[0].frame.index
    if any(not item.frame.index.equals(index) for item in mppts[1:]):
        raise ValueError("all MPPT results must share the same interval index")

    n = len(index)
    raw_power = np.zeros(n, dtype=float)
    voltage_accepted_power = np.zeros(n, dtype=float)
    voltage_loss = np.zeros(n, dtype=float)
    tracker_voltages = np.zeros((len(mppts), n), dtype=float)
    tracker_dark = np.zeros((len(mppts), n), dtype=bool)
    tracker_accepted_power = np.zeros((len(mppts), n), dtype=float)
    any_current_limit_known = False
    current_limit_loss = np.zeros(n, dtype=float)
    current_limit_intervals: dict[str, dict[str, int]] = {}

    absolute_dc_voltage = (inverter.get("dc_limits") or {}).get("max_dc_voltage_v")
    absolute_dc_voltage = (
        float(absolute_dc_voltage) if _positive(absolute_dc_voltage) else None
    )

    for row, mppt in enumerate(mppts):
        frame = mppt.frame
        pmp = frame["mppt_pmp_w"].to_numpy(dtype=float)
        vmp = frame["mppt_vmp_v"].to_numpy(dtype=float)
        voc = frame["mppt_voc_v"].to_numpy(dtype=float)
        imp = frame["mppt_imp_a"].to_numpy(dtype=float)
        active = frame["active"].to_numpy(dtype=bool)

        dark = frame.get("availability", pd.Series("", index=index)).eq("inactive_dark").to_numpy()
        if dark.any() and (active[dark].any() or (pmp[dark] != 0).any()
                          or not np.isnan(vmp[dark]).all() or not np.isnan(imp[dark]).all()
                          or not np.isnan(voc[dark]).all()):
            raise ValueError("invalid inactive_dark inverter input")
        tracker_dark[row, :] = dark
        product = vmp * imp
        denominator = np.maximum(
            np.maximum(np.abs(product), np.abs(pmp)),
            1e-12,
        )
        if (np.abs(pmp - product) / denominator > 1e-8).any():
            raise ValueError(
                "MPPT input Pmp does not reconcile with Vmp*Imp"
            )

        limits = _mppt_limits(inverter, mppt.mppt_index)
        min_v = float(limits["min_voltage"])
        max_v = float(limits["max_voltage"])
        max_current = limits["max_current"]
        any_current_limit_known = any_current_limit_known or max_current is not None

        if absolute_dc_voltage is not None:
            unsafe = active & (voc > absolute_dc_voltage)
            if unsafe.any():
                examples = [ts.isoformat() for ts in index[unsafe][:3]]
                raise ValueError(
                    "string/MPPT open-circuit voltage exceeds inverter absolute DC "
                    f"voltage limit (examples={examples})"
                )

        if "mixed_terminal_envelopes" in mppt.metadata:
            envelopes = mppt.metadata["mixed_terminal_envelopes"]
            if not envelopes.index.equals(index) or mppt.metadata["terminal_limits"] != limits:
                raise ValueError("mixed terminal envelopes have stale interval/limit bindings")
            w0, wi, wiv = (envelopes[c].to_numpy(dtype=float) for c in ("w0","wi","wiv"))
            final_v, final_i = (envelopes[c].to_numpy(dtype=float) for c in ("voltage_v","current_a"))
            if not all(np.isfinite(a).all() for a in (w0,wi,wiv,final_v,final_i)) or np.any(wiv < -1e-8):
                raise ValueError("mixed terminal envelope contains invalid values")
            if not np.allclose(w0,pmp,atol=1e-6,rtol=0) or np.any(wi>w0+1e-6) or np.any(wiv>wi+1e-6):
                raise ValueError("mixed terminal envelopes are not nested")
            operating = wiv > 0
            if (np.any(operating & ((final_v<min_v-1e-8) | (final_v>max_v+1e-8))) or
                (max_current is not None and np.any(final_i>max_current+1e-8)) or
                not np.allclose(wiv,final_v*final_i,atol=1e-6,rtol=1e-10)):
                raise ValueError("mixed operating point violates terminal constraints")
            raw_power += w0
            current_limit_loss += w0-wi
            voltage_loss += wi-wiv
            voltage_accepted_power += wiv
            tracker_voltages[row,:] = final_v
            tracker_accepted_power[row,:] = wiv
            if max_current is not None:
                current_limit_intervals[str(mppt.mppt_index)] = {"binding_intervals":int(np.sum(w0-wi>1e-8))}
            continue

        raw_power += pmp
        if max_current is not None:
            limited, vmp, imp, binding = constrain_mppt_current(frame, float(max_current))
            current_limit_loss += pmp - limited
            pmp = limited
            current_limit_intervals[str(mppt.mppt_index)] = {
                "binding_intervals": int(binding.sum()),
            }

        within = active & (vmp >= min_v) & (vmp <= max_v)
        accepted = np.where(within, pmp, 0.0)

        voltage_accepted_power += accepted
        voltage_loss += pmp - accepted
        tracker_voltages[row, :] = vmp
        tracker_accepted_power[row, :] = accepted

    thresholds = inverter.get("operating_thresholds") or {}
    startup_threshold = thresholds.get("startup_power_w")
    if not _nonnegative(startup_threshold):
        startup_threshold = thresholds.get("minimum_input_power_w")
    startup_threshold_w = float(startup_threshold) if _nonnegative(startup_threshold) else 0.0

    converter_active = voltage_accepted_power > startup_threshold_w
    threshold_loss = np.where(converter_active, 0.0, voltage_accepted_power)
    dc_to_converter = np.where(converter_active, voltage_accepted_power, 0.0)

    efficiency_model = inverter["efficiency_model"]
    ac_unclipped = np.zeros(n, dtype=float)
    efficiency = np.zeros(n, dtype=float)
    for i in range(n):
        if dc_to_converter[i] <= 0:
            continue
        # Dark trackers have no voltage; omit their zero-power contributions
        # instead of inventing a voltage for conversion interpolation.
        ac_value, eta = evaluate_voltage_dependent_conversion(
            efficiency_model,
            dc_power_w=float(dc_to_converter[i]),
            tracker_voltages_v=tracker_voltages[~tracker_dark[:, i], i],
            tracker_powers_w=tracker_accepted_power[~tracker_dark[:, i], i],
            model_id=model_id,
        )
        ac_unclipped[i] = ac_value
        efficiency[i] = eta

    conversion_loss = dc_to_converter - ac_unclipped
    if (conversion_loss < -1e-8).any():
        raise RuntimeError("inverter conversion model produced negative conversion loss")
    conversion_loss = np.maximum(conversion_loss, 0.0)

    ac_limit, derating_meta = _ac_power_limit(
        inverter,
        index=index,
        inverter_temperature_c=inverter_temperature_c,
        temperature_basis=temperature_basis,
    )
    ac_available = np.minimum(ac_unclipped, ac_limit)
    clipping_loss = np.maximum(ac_unclipped - ac_available, 0.0)
    clipped = clipping_loss > 0

    standby_loss_w = thresholds.get("standby_loss_w")
    if not _nonnegative(standby_loss_w):
        standby_loss_w = (efficiency_model or {}).get("standby_loss_w")
    standby_loss_w = float(standby_loss_w) if _nonnegative(standby_loss_w) else 0.0

    night_loss_w = thresholds.get("night_loss_w")
    if not _nonnegative(night_loss_w):
        night_loss_w = (efficiency_model or {}).get("night_loss_w")
    night_loss_w = float(night_loss_w) if _nonnegative(night_loss_w) else 0.0

    night = raw_power <= 0
    standby = (raw_power > 0) & ~converter_active
    night_consumption = np.where(night, night_loss_w, 0.0)
    standby_consumption = np.where(standby, standby_loss_w, 0.0)
    self_consumption = night_consumption + standby_consumption
    ac_net = ac_available - self_consumption

    frame = pd.DataFrame(index=index.copy())
    frame.index.name = "interval_start"
    if "evaluation_time" in mppts[0].frame:
        frame["evaluation_time"] = mppts[0].frame["evaluation_time"].to_numpy()
    frame["dc_mpp_available_w"] = raw_power
    if any_current_limit_known:
        frame["mppt_current_limit_loss_w"] = current_limit_loss
        frame["after_mppt_current_limit_w"] = raw_power - current_limit_loss
    frame["dc_voltage_window_accepted_w"] = voltage_accepted_power
    frame["dc_voltage_threshold_loss_w"] = voltage_loss
    frame["dc_power_threshold_loss_w"] = threshold_loss
    frame["dc_to_converter_w"] = dc_to_converter
    frame["inverter_efficiency_fraction"] = efficiency
    frame["inverter_conversion_loss_w"] = conversion_loss
    frame["ac_unclipped_w"] = ac_unclipped
    frame["ac_power_limit_w"] = ac_limit
    frame["inverter_clipping_loss_w"] = clipping_loss
    frame["ac_available_w"] = ac_available
    frame["night_consumption_w"] = night_consumption
    frame["standby_consumption_w"] = standby_consumption
    frame["inverter_self_consumption_w"] = self_consumption
    frame["ac_net_output_w"] = ac_net
    frame["converter_active"] = converter_active
    frame["clipped"] = clipped

    dc_reconciled = (
        frame["dc_to_converter_w"].to_numpy(dtype=float)
        + frame["dc_voltage_threshold_loss_w"].to_numpy(dtype=float)
        + frame["dc_power_threshold_loss_w"].to_numpy(dtype=float)
        + current_limit_loss
    )
    if not np.allclose(
        dc_reconciled,
        frame["dc_mpp_available_w"].to_numpy(dtype=float),
        atol=1e-8,
        rtol=0.0,
    ):
        raise RuntimeError("inverter DC threshold channels do not reconcile")

    ac_reconciled = (
        frame["ac_available_w"].to_numpy(dtype=float)
        + frame["inverter_clipping_loss_w"].to_numpy(dtype=float)
    )
    if not np.allclose(
        ac_reconciled,
        frame["ac_unclipped_w"].to_numpy(dtype=float),
        atol=1e-8,
        rtol=0.0,
    ):
        raise RuntimeError("inverter clipping channel does not reconcile")

    metadata = {
        "schema_name": "InverterElectricalResult",
        "schema_version": "0.1",
        "model_id": model_id,
        "component_definition_id": inverter.get("inverter_definition_id"),
        "component_revision_id": inverter.get("revision_id"),
        "efficiency_power_interpolation": "bounded_linear_pin_pout_v0.1",
        "efficiency_power_above_curve_policy": "hold_endpoint_efficiency",
        "efficiency_voltage_interpolation": policy,
        "multi_mppt_efficiency_policy": (
            "power_weighted_voltage_efficiency_at_total_inverter_dc_power"
        ),
        "startup_threshold_w": startup_threshold_w,
        "nominal_ac_power_w": float(inverter["ac_limits"]["nominal_ac_power_w"]),
        "base_max_ac_power_w": float(
            inverter["ac_limits"].get("max_ac_power_w")
            or inverter["ac_limits"]["nominal_ac_power_w"]
        ),
        "night_loss_w": night_loss_w,
        "standby_loss_w": standby_loss_w,
        "mppt_current_limit_known": any_current_limit_known,
        "binding_current_limit_policy": MPPT_CURRENT_LIMIT_POLICY,
        **({"mppt_current_limit": current_limit_intervals} if current_limit_intervals else {}),
        **derating_meta,
    }
    return InverterElectricalResult(frame=frame, metadata=metadata)
