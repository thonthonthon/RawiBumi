"""Integrated Phase-3.7 electrical loss chain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from electrical.mppt import MPPTAggregationResult
from engine.inverter import (
    InverterElectricalResult,
    INVERTER_VOLTAGE_DEPENDENT,
    simulate_voltage_dependent_inverter,
)

from .array import ArrayLossResult, apply_pre_inverter_array_losses
from .ledger import ElectricalLossLedgerResult, build_electrical_loss_ledger


@dataclass(frozen=True)
class ElectricalLossChainResult:
    array_losses: ArrayLossResult
    inverter: InverterElectricalResult
    ledger: ElectricalLossLedgerResult
    metadata: dict[str, Any]


def simulate_electrical_loss_chain(
    mppt_bank: Mapping[int, MPPTAggregationResult],
    inverter_definition: dict[str, Any],
    *,
    interval_seconds: float | pd.Series | np.ndarray | list[float],
    module_quality_loss_fraction: float = 0.0,
    module_mismatch_loss_fraction: float = 0.0,
    string_mismatch_loss_fraction: float = 0.0,
    dc_array_resistance_ohm: float = 0.0,
    loss_settings: Mapping[str, Any] | None = None,
    circuit_references: Mapping[int, Mapping[str, Any]] | None = None,
    circuit_loss_context: Mapping[str, Any] | None = None,
    inverter_temperature_c: float | pd.Series | np.ndarray | list[float] | None = None,
    inverter_temperature_basis: str | None = None,
    inverter_model_id: str = INVERTER_VOLTAGE_DEPENDENT,
) -> ElectricalLossChainResult:
    """Apply pre-inverter array losses, inverter physics, then reconcile the chain."""
    if loss_settings is not None:
        from .staged import apply_circuit_losses, build_staged_ledger

        from .settings import assert_compatible_wiring_modes

        assert_compatible_wiring_modes(
            per_circuit=True, global_resistance_ohm=dc_array_resistance_ohm
        )
        if circuit_references is None:
            raise ValueError("per-circuit wiring requires pinned STC references")
        array_losses = apply_circuit_losses(
            mppt_bank,
            loss_settings,
            circuit_references,
            quality=module_quality_loss_fraction,
        )
        inverter = simulate_voltage_dependent_inverter(
            array_losses.mppt_bank,
            inverter_definition,
            inverter_temperature_c=inverter_temperature_c,
            temperature_basis=inverter_temperature_basis,
            model_id=inverter_model_id,
        )
        ledger = build_staged_ledger(
            array_losses,
            inverter,
            settings=loss_settings,
            nominal_w=float(inverter_definition["ac_limits"]["nominal_ac_power_w"]),
            interval_seconds=interval_seconds,
            circuit_loss_context=circuit_loss_context,
        )
        return ElectricalLossChainResult(
            array_losses,
            inverter,
            ledger,
            {
                "schema_name": "ElectricalLossChainResult",
                "schema_version": "0.1",
                "resolved_loss_settings": dict(loss_settings),
                "stage_order": ledger.metadata["channel_order"],
            },
        )
    array_losses = apply_pre_inverter_array_losses(
        mppt_bank,
        module_quality_loss_fraction=module_quality_loss_fraction,
        module_mismatch_loss_fraction=module_mismatch_loss_fraction,
        string_mismatch_loss_fraction=string_mismatch_loss_fraction,
        dc_array_resistance_ohm=dc_array_resistance_ohm,
    )
    inverter = simulate_voltage_dependent_inverter(
        array_losses.mppt_bank,
        inverter_definition,
        inverter_temperature_c=inverter_temperature_c,
        temperature_basis=inverter_temperature_basis,
        model_id=inverter_model_id,
    )
    ledger = build_electrical_loss_ledger(
        array_losses,
        inverter,
        interval_seconds=interval_seconds,
    )
    return ElectricalLossChainResult(
        array_losses=array_losses,
        inverter=inverter,
        ledger=ledger,
        metadata={
            "schema_name": "ElectricalLossChainResult",
            "schema_version": "0.1",
            "stage_order": ledger.metadata["channel_order"],
        },
    )
