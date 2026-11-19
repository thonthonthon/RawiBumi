"""Explicit electrical losses, energy integration, and reconciliation."""

from .array import (
    ARRAY_LOSS_MODEL,
    ArrayLossResult,
    apply_pre_inverter_array_losses,
)
from .chain import ElectricalLossChainResult, simulate_electrical_loss_chain
from .energy import (
    EnergyAggregationResult,
    aggregate_interval_quantities,
    calculate_pv_kpis,
)
from .ledger import (
    LOSS_LEDGER_MODEL,
    ElectricalLossLedgerResult,
    build_electrical_loss_ledger,
)

__all__ = [
    "ARRAY_LOSS_MODEL",
    "ArrayLossResult",
    "apply_pre_inverter_array_losses",
    "ElectricalLossChainResult",
    "simulate_electrical_loss_chain",
    "EnergyAggregationResult",
    "aggregate_interval_quantities",
    "calculate_pv_kpis",
    "LOSS_LEDGER_MODEL",
    "ElectricalLossLedgerResult",
    "build_electrical_loss_ledger",
]
