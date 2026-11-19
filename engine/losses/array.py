"""Explicit pre-inverter array losses for the Phase-3 electrical chain."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

import numpy as np
import pandas as pd

from electrical.mppt import MPPTAggregationResult


ARRAY_LOSS_MODEL = "array_losses.explicit_mpp_i2r.v0.1"


@dataclass(frozen=True)
class ArrayLossResult:
    """Adjusted MPPT bank plus interval array-loss channels."""

    mppt_bank: dict[int, MPPTAggregationResult]
    frame: pd.DataFrame
    metadata: dict[str, Any]


def _signed_loss_fraction(value: float, name: str) -> float:
    numeric = float(value)
    if not isfinite(numeric) or not -1.0 < numeric < 1.0:
        raise ValueError(f"{name} must be finite and lie within -1 < fraction < 1")
    return numeric


def _nonnegative_fraction(value: float, name: str) -> float:
    numeric = float(value)
    if not isfinite(numeric) or not 0.0 <= numeric < 1.0:
        raise ValueError(f"{name} must be finite and lie within 0 <= fraction < 1")
    return numeric


def _nonnegative_resistance(value: float) -> float:
    numeric = float(value)
    if not isfinite(numeric) or numeric < 0:
        raise ValueError("dc_array_resistance_ohm must be finite and non-negative")
    return numeric


def apply_pre_inverter_array_losses(
    mppt_bank: Mapping[int, MPPTAggregationResult],
    *,
    module_quality_loss_fraction: float = 0.0,
    module_mismatch_loss_fraction: float = 0.0,
    string_mismatch_loss_fraction: float = 0.0,
    dc_array_resistance_ohm: float = 0.0,
    common_voltage_absolute_tolerance_v: float = 1e-6,
    common_voltage_relative_tolerance: float = 1e-9,
) -> ArrayLossResult:
    """Apply explicit MPP quality/mismatch factors and global I²R wiring loss.

    Positive loss fractions reduce MPP power. A negative module-quality loss
    fraction is an explicit gain, matching source conventions such as PVsyst's
    -0.75% module-quality loss entry.

    The global equivalent array resistance model is only valid when active MPPTs
    share a common pre-wire MPP voltage. This is true for the current unshaded
    identical-string benchmark. Heterogeneous tracker voltages require per-circuit
    resistance data rather than a fabricated global voltage drop.
    """
    if not mppt_bank:
        raise ValueError("mppt_bank must not be empty")

    quality = _signed_loss_fraction(
        module_quality_loss_fraction,
        "module_quality_loss_fraction",
    )
    module_mismatch = _nonnegative_fraction(
        module_mismatch_loss_fraction,
        "module_mismatch_loss_fraction",
    )
    string_mismatch = _nonnegative_fraction(
        string_mismatch_loss_fraction,
        "string_mismatch_loss_fraction",
    )
    resistance = _nonnegative_resistance(dc_array_resistance_ohm)

    if (
        not isfinite(float(common_voltage_absolute_tolerance_v))
        or common_voltage_absolute_tolerance_v < 0
    ):
        raise ValueError(
            "common_voltage_absolute_tolerance_v must be finite and non-negative"
        )
    if (
        not isfinite(float(common_voltage_relative_tolerance))
        or common_voltage_relative_tolerance < 0
    ):
        raise ValueError(
            "common_voltage_relative_tolerance must be finite and non-negative"
        )

    mppts = [mppt_bank[index] for index in sorted(mppt_bank)]
    index = mppts[0].frame.index
    if any(not item.frame.index.equals(index) for item in mppts[1:]):
        raise ValueError("all MPPT results must share the same interval index")

    required = {
        "mppt_isc_a",
        "mppt_voc_v",
        "mppt_imp_a",
        "mppt_vmp_v",
        "mppt_pmp_w",
        "active",
    }
    for item in mppts:
        missing = required - set(item.frame.columns)
        if missing:
            raise ValueError(
                f"MPPT {item.mppt_index} is missing array-loss inputs: {sorted(missing)}"
            )

    n = len(index)
    raw_total = np.zeros(n, dtype=float)
    quality_loss = np.zeros(n, dtype=float)
    module_mismatch_loss = np.zeros(n, dtype=float)
    string_mismatch_loss = np.zeros(n, dtype=float)

    intermediate: dict[int, dict[str, np.ndarray]] = {}
    for item in mppts:
        frame = item.frame
        p0 = frame["mppt_pmp_w"].to_numpy(dtype=float)
        vmp = frame["mppt_vmp_v"].to_numpy(dtype=float)
        imp = frame["mppt_imp_a"].to_numpy(dtype=float)
        active = frame["active"].to_numpy(dtype=bool)

        if (p0 < -1e-9).any() or (vmp < -1e-9).any() or (imp < -1e-9).any():
            raise ValueError("array-loss inputs must be non-negative")

        l_quality = p0 * quality
        p1 = p0 - l_quality

        l_module_mismatch = p1 * module_mismatch
        p2 = p1 - l_module_mismatch

        l_string_mismatch = p2 * string_mismatch
        p3 = p2 - l_string_mismatch

        # The configured quality/mismatch abstractions are MPP power factors. To
        # preserve tracker voltage for the following wiring calculation, map their
        # MPP effect onto Imp. Voc and Isc remain source electrical state.
        imp3 = np.divide(
            p3,
            vmp,
            out=np.zeros_like(p3),
            where=vmp > 0,
        )
        # Zero is the inactive branch contribution to the array-current sum.
        # An explicit dark tracker still has unavailable V/I in the output.
        imp3[~active] = 0.0

        raw_total += p0
        quality_loss += l_quality
        module_mismatch_loss += l_module_mismatch
        string_mismatch_loss += l_string_mismatch
        intermediate[item.mppt_index] = {
            "pmp_before_wiring": p3,
            "vmp_before_wiring": vmp,
            "imp_before_wiring": imp3,
            "active": active,
        }

    after_quality = raw_total - quality_loss
    after_module_mismatch = after_quality - module_mismatch_loss
    before_wiring = after_module_mismatch - string_mismatch_loss

    total_current = np.sum(
        np.vstack(
            [
                intermediate[item.mppt_index]["imp_before_wiring"]
                for item in mppts
            ]
        ),
        axis=0,
    )
    voltage_drop = total_current * resistance
    wiring_loss = total_current * voltage_drop

    if resistance > 0:
        active_voltage_stack = np.vstack(
            [
                intermediate[item.mppt_index]["vmp_before_wiring"]
                for item in mppts
            ]
        )
        active_stack = np.vstack(
            [intermediate[item.mppt_index]["active"] for item in mppts]
        )
        for col in range(n):
            active_values = active_voltage_stack[:, col][active_stack[:, col]]
            if len(active_values) <= 1:
                continue
            ref = float(active_values[0])
            tolerance = (
                float(common_voltage_absolute_tolerance_v)
                + float(common_voltage_relative_tolerance) * abs(ref)
            )
            if np.max(np.abs(active_values - ref)) > tolerance:
                raise ValueError(
                    "global equivalent DC-array resistance requires common active "
                    "MPPT voltage; use per-circuit resistance for heterogeneous trackers"
                )
            if voltage_drop[col] >= ref and total_current[col] > 0:
                raise ValueError(
                    "global DC wiring voltage drop reaches/exceeds active MPP voltage"
                )

    adjusted: dict[int, MPPTAggregationResult] = {}
    after_wiring_total = np.zeros(n, dtype=float)
    for item in mppts:
        source = item.frame
        state = intermediate[item.mppt_index]
        active = state["active"]
        v_before = state["vmp_before_wiring"]
        imp_after = state["imp_before_wiring"]
        v_after = np.where(active, np.maximum(v_before - voltage_drop, 0.0), 0.0)
        p_after = v_after * imp_after
        after_wiring_total += p_after

        out = source.copy()
        dark = source.get("availability", pd.Series("", index=index)).eq("inactive_dark").to_numpy()
        if dark.any() and (active[dark].any() or source.loc[dark, "mppt_pmp_w"].ne(0).any()
                          or not source.loc[dark, ["mppt_vmp_v", "mppt_imp_a", "mppt_voc_v", "mppt_isc_a"]].isna().all().all()):
            raise ValueError("invalid inactive_dark array input")
        out["mppt_imp_a"] = np.where(dark, np.nan, imp_after)
        out["mppt_vmp_v"] = np.where(dark, np.nan, v_after)
        out["mppt_pmp_w"] = p_after

        denominator = np.maximum(
            np.maximum(np.abs(p_after), np.abs(v_after * imp_after)),
            1e-12,
        )
        out["pmp_identity_relative_error"] = (
            np.abs(p_after - v_after * imp_after) / denominator
        )

        out.loc[dark, "pmp_identity_relative_error"] = np.nan

        min_v = item.metadata.get("min_operating_voltage_v")
        max_v = item.metadata.get("max_operating_voltage_v")
        if min_v is not None:
            out["voltage_below_min"] = active & (v_after < float(min_v))
        if max_v is not None:
            out["voltage_above_max"] = active & (v_after > float(max_v))
        if min_v is not None and max_v is not None:
            out["voltage_within_window"] = (
                active
                & (v_after >= float(min_v))
                & (v_after <= float(max_v))
            )

        adjusted[item.mppt_index] = MPPTAggregationResult(
            mppt_index=item.mppt_index,
            string_ids=item.string_ids,
            frame=out,
            metadata={
                **item.metadata,
                "pre_inverter_array_loss_model_id": ARRAY_LOSS_MODEL,
                "module_quality_loss_fraction": quality,
                "module_mismatch_loss_fraction": module_mismatch,
                "string_mismatch_loss_fraction": string_mismatch,
                "dc_array_resistance_ohm": resistance,
            },
        )

    if not np.allclose(
        after_wiring_total,
        before_wiring - wiring_loss,
        atol=1e-7,
        rtol=1e-12,
    ):
        raise RuntimeError("DC wiring I2R loss does not reconcile")

    frame = pd.DataFrame(index=index.copy())
    frame.index.name = "interval_start"
    if "evaluation_time" in mppts[0].frame:
        frame["evaluation_time"] = mppts[0].frame["evaluation_time"].to_numpy()
    frame["raw_array_mpp_w"] = raw_total
    frame["module_quality_loss_w"] = quality_loss
    frame["after_module_quality_w"] = after_quality
    frame["module_mismatch_loss_w"] = module_mismatch_loss
    frame["after_module_mismatch_w"] = after_module_mismatch
    frame["string_mismatch_loss_w"] = string_mismatch_loss
    frame["before_dc_wiring_w"] = before_wiring
    frame["dc_array_current_a"] = total_current
    frame["dc_wiring_voltage_drop_v"] = voltage_drop
    frame["dc_wiring_loss_w"] = wiring_loss
    frame["array_virtual_mpp_w"] = after_wiring_total

    metadata = {
        "schema_name": "ArrayLossResult",
        "schema_version": "0.1",
        "model_id": ARRAY_LOSS_MODEL,
        "module_quality_loss_fraction": quality,
        "module_quality_sign_convention": "positive_loss_negative_gain",
        "module_mismatch_loss_fraction": module_mismatch,
        "string_mismatch_loss_fraction": string_mismatch,
        "dc_wiring_model": "global_equivalent_resistance_i2r",
        "dc_array_resistance_ohm": resistance,
        "dc_wiring_reference_fraction_policy": (
            "source_stc_fraction_is_reference_only_not_runtime_multiplier"
        ),
        "quality_mismatch_voltage_policy": (
            "preserve_vmp_map_power_factor_to_imp"
        ),
        "wiring_voltage_policy": (
            "common_tracker_voltage_drop_equals_total_array_current_times_global_resistance"
        ),
    }
    return ArrayLossResult(
        mppt_bank=adjusted,
        frame=frame,
        metadata=metadata,
    )
