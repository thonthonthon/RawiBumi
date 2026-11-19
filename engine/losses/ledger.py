"""Ordered electrical loss ledger and reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from engine.inverter import InverterElectricalResult

from .array import ArrayLossResult
from .energy import EnergyAggregationResult, aggregate_interval_quantities


LOSS_LEDGER_MODEL = "loss_ledger.electrical_chain.v0.1"


@dataclass(frozen=True)
class ElectricalLossLedgerResult:
    frame: pd.DataFrame
    energy: EnergyAggregationResult
    summary: pd.DataFrame
    metadata: dict[str, Any]


_LEDGER_CHANNELS = (
    ("module_quality", "module_quality_loss_w", "raw_array_mpp_w", "after_module_quality_w"),
    (
        "module_mismatch",
        "module_mismatch_loss_w",
        "after_module_quality_w",
        "after_module_mismatch_w",
    ),
    (
        "string_mismatch",
        "string_mismatch_loss_w",
        "after_module_mismatch_w",
        "before_dc_wiring_w",
    ),
    (
        "dc_wiring",
        "dc_wiring_loss_w",
        "before_dc_wiring_w",
        "array_virtual_mpp_w",
    ),
    (
        "mppt_voltage_threshold",
        "dc_voltage_threshold_loss_w",
        "array_virtual_mpp_w",
        "dc_voltage_window_accepted_w",
    ),
    (
        "inverter_power_threshold",
        "dc_power_threshold_loss_w",
        "dc_voltage_window_accepted_w",
        "dc_to_converter_w",
    ),
    (
        "inverter_conversion",
        "inverter_conversion_loss_w",
        "dc_to_converter_w",
        "ac_unclipped_w",
    ),
    (
        "inverter_clipping",
        "inverter_clipping_loss_w",
        "ac_unclipped_w",
        "ac_available_w",
    ),
    (
        "inverter_self_consumption",
        "inverter_self_consumption_w",
        "ac_available_w",
        "pcc_power_w",
    ),
)


def with_current_limit(channels: tuple, frame: pd.DataFrame) -> tuple:
    """Insert the MPPT current-limit channel after DC wiring when the inverter emitted it."""
    if "mppt_current_limit_loss_w" not in frame:
        return channels
    out = []
    for row in channels:
        if row[0] == "mppt_voltage_threshold":
            out.append(("mppt_current_limit", "mppt_current_limit_loss_w", row[2], "after_mppt_current_limit_w"))
            row = (row[0], row[1], "after_mppt_current_limit_w", row[3])
        out.append(row)
    return tuple(out)


def with_orientation_mismatch(channels: tuple, frame: pd.DataFrame) -> tuple:
    """Insert orientation coupling once, before the first module-MPP scalar loss."""
    if "orientation_mismatch_loss_w" not in frame:
        return channels
    out, inserted = [], False
    for name, loss, upstream, downstream in channels:
        if upstream == "raw_array_mpp_w":
            if not inserted:
                out.append(("orientation_mismatch", "orientation_mismatch_loss_w", "raw_array_mpp_w", "after_orientation_mismatch_w"))
                inserted = True
            upstream = "after_orientation_mismatch_w"
        out.append((name,loss,upstream,downstream))
    return tuple(out)


def build_electrical_loss_ledger(
    array_losses: ArrayLossResult,
    inverter: InverterElectricalResult,
    *,
    interval_seconds: float | pd.Series | np.ndarray | list[float],
) -> ElectricalLossLedgerResult:
    """Build an ordered, non-overlapping module-MPP-to-PCC loss ledger.

    Phase 3.7's PCC is an identity boundary at net inverter AC output. AC wiring,
    transformer, availability, curtailment, and auxiliary plant loads are not silently
    added here.
    """
    if not array_losses.frame.index.equals(inverter.frame.index):
        raise ValueError("array-loss and inverter intervals must align exactly")

    frame = array_losses.frame.copy()
    for column in inverter.frame.columns:
        if column == "evaluation_time":
            continue
        frame[column] = inverter.frame[column].to_numpy()

    frame["pcc_power_w"] = inverter.frame["ac_net_output_w"].to_numpy(dtype=float)
    channels = with_current_limit(with_orientation_mismatch(_LEDGER_CHANNELS, frame), frame)

    required = set()
    for _, loss_col, upstream_col, downstream_col in channels:
        required.update((loss_col, upstream_col, downstream_col))
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"loss ledger inputs are missing: {missing}")

    max_residual = 0.0
    for channel, loss_col, upstream_col, downstream_col in channels:
        residual = (
            frame[downstream_col].to_numpy(dtype=float)
            - (
                frame[upstream_col].to_numpy(dtype=float)
                - frame[loss_col].to_numpy(dtype=float)
            )
        )
        frame[f"{channel}_reconciliation_residual_w"] = residual
        if len(residual):
            max_residual = max(max_residual, float(np.max(np.abs(residual))))

    if max_residual > 1e-6:
        raise RuntimeError(
            f"electrical loss ledger does not reconcile; max residual={max_residual} W"
        )

    power_columns = [
        "raw_array_mpp_w",
        "module_quality_loss_w",
        "after_module_quality_w",
        "module_mismatch_loss_w",
        "after_module_mismatch_w",
        "string_mismatch_loss_w",
        "before_dc_wiring_w",
        "dc_wiring_loss_w",
        "array_virtual_mpp_w",
        *(("mppt_current_limit_loss_w", "after_mppt_current_limit_w") if "mppt_current_limit_loss_w" in frame else ()),
        "dc_voltage_threshold_loss_w",
        "dc_voltage_window_accepted_w",
        "dc_power_threshold_loss_w",
        "dc_to_converter_w",
        "inverter_conversion_loss_w",
        "ac_unclipped_w",
        "inverter_clipping_loss_w",
        "ac_available_w",
        "night_consumption_w",
        "standby_consumption_w",
        "inverter_self_consumption_w",
        "pcc_power_w",
    ]
    if "orientation_mismatch_loss_w" in frame:
        power_columns.extend(("orientation_mismatch_loss_w", "after_orientation_mismatch_w"))
    energy = aggregate_interval_quantities(
        frame,
        interval_seconds=interval_seconds,
        power_columns_w=power_columns,
    )

    rows: list[dict[str, Any]] = []
    for order, (channel, loss_col, upstream_col, downstream_col) in enumerate(
        channels,
        start=1,
    ):
        loss_key = loss_col.replace("_w", "_kwh")
        upstream_key = upstream_col.replace("_w", "_kwh")
        downstream_key = downstream_col.replace("_w", "_kwh")
        loss_energy = energy.annual[loss_key]
        rows.append(
            {
                "order": order,
                "channel": channel,
                "loss_power_column": loss_col,
                "upstream_power_column": upstream_col,
                "downstream_power_column": downstream_col,
                "loss_energy_kwh": loss_energy,
                "classification": (
                    "gain" if loss_energy < 0 else ("loss" if loss_energy > 0 else "zero")
                ),
                "upstream_energy_kwh": energy.annual[upstream_key],
                "downstream_energy_kwh": energy.annual[downstream_key],
            }
        )

    summary = pd.DataFrame(rows).set_index("order")
    total_signed_loss = float(summary["loss_energy_kwh"].sum())
    upstream_energy = energy.annual["raw_array_mpp_kwh"]
    downstream_energy = energy.annual["pcc_power_kwh"]
    annual_residual = downstream_energy - (upstream_energy - total_signed_loss)
    if abs(annual_residual) > 1e-9:
        raise RuntimeError(
            f"annual electrical loss ledger residual is {annual_residual} kWh"
        )

    metadata = {
        "schema_name": "ElectricalLossLedgerResult",
        "schema_version": "0.1",
        "model_id": LOSS_LEDGER_MODEL,
        "scope": "raw_array_mpp_to_pcc_identity_boundary",
        "pcc_boundary": "net_inverter_ac_output_no_downstream_ac_stage",
        "channel_order": [item[0] for item in channels],
        "signed_loss_convention": "positive_loss_negative_gain",
        "max_interval_reconciliation_residual_w": max_residual,
        "annual_reconciliation_residual_kwh": annual_residual,
        "downstream_ac_stages_modelled": False,
    }
    return ElectricalLossLedgerResult(
        frame=frame,
        energy=energy,
        summary=summary,
        metadata=metadata,
    )
