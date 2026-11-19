"""Analytical series-string aggregation for the Phase-3 unshaded engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from engine.module import ModuleElectricalResult
from engine.module.pvsyst import SDM_COLUMNS as MODULE_SDM_COLUMNS


STRING_IDENTICAL_SERIES_MPP = "string.identical_series_mpp.v0.1"
SUPPORTED_STRING_MODELS = {STRING_IDENTICAL_SERIES_MPP}


@dataclass(frozen=True)
class StringElectricalResult:
    """Interval-start indexed electrical state for one PV string."""

    string_id: str
    frame: pd.DataFrame
    metadata: dict[str, Any]


def calculate_identical_series_string(
    module: ModuleElectricalResult,
    *,
    string_id: str,
    modules_in_series: int,
) -> StringElectricalResult:
    """Aggregate identical module MPP states into one series string.

    This analytical model is exact for the Phase-3 unshaded/electrically identical
    benchmark. It is intentionally not a substitute for future full IV aggregation of
    non-identical or shaded modules.
    """
    if not isinstance(string_id, str) or not string_id:
        raise ValueError("string_id must be a non-empty string")
    if not isinstance(modules_in_series, int) or modules_in_series < 1:
        raise ValueError("modules_in_series must be an integer >= 1")

    required = {"isc_a", "voc_v", "imp_a", "vmp_v", "pmp_w", "active"}
    missing = required - set(module.frame.columns)
    if missing:
        raise ValueError(
            f"module electrical result is missing string inputs: {sorted(missing)}"
        )

    source = module.frame
    n = float(modules_in_series)

    frame = pd.DataFrame(index=source.index.copy())
    frame.index.name = "interval_start"
    if "evaluation_time" in source:
        frame["evaluation_time"] = source["evaluation_time"].to_numpy()

    frame["string_isc_a"] = source["isc_a"].to_numpy(dtype=float)
    frame["string_voc_v"] = source["voc_v"].to_numpy(dtype=float) * n
    frame["string_imp_a"] = source["imp_a"].to_numpy(dtype=float)
    frame["string_vmp_v"] = source["vmp_v"].to_numpy(dtype=float) * n
    frame["string_pmp_w"] = source["pmp_w"].to_numpy(dtype=float) * n
    frame["active"] = source["active"].to_numpy(dtype=bool)
    # The module's single-diode parameters ride along (identical modules), so the inverter can solve the string's
    # IV curve away from the MPP when an MPPT current limit binds.
    for column in MODULE_SDM_COLUMNS:
        if column in source:
            frame[column] = source[column].to_numpy(dtype=float)
    frame["modules_in_series"] = modules_in_series

    product = (
        frame["string_vmp_v"].to_numpy(dtype=float)
        * frame["string_imp_a"].to_numpy(dtype=float)
    )
    expected = frame["string_pmp_w"].to_numpy(dtype=float)
    denominator = np.maximum(np.maximum(np.abs(product), np.abs(expected)), 1e-12)
    frame["pmp_identity_relative_error"] = np.abs(expected - product) / denominator

    if (frame["string_voc_v"] + 1e-9 < frame["string_vmp_v"]).any():
        raise RuntimeError("series-string aggregation produced Vmp above Voc")
    if (frame["string_isc_a"] + 1e-9 < frame["string_imp_a"]).any():
        raise RuntimeError("series-string aggregation produced Imp above Isc")

    metadata = {
        "schema_name": "StringElectricalResult",
        "schema_version": "0.1",
        "model_id": STRING_IDENTICAL_SERIES_MPP,
        "string_id": string_id,
        "modules_in_series": modules_in_series,
        "module_model_id": module.metadata.get("model_id"),
        "aggregation_scope": "identical_module_states_only",
        "series_rules": {
            "voltage": "sum",
            "current": "common",
            "power": "sum",
        },
    }
    return StringElectricalResult(
        string_id=string_id,
        frame=frame,
        metadata=metadata,
    )


def build_identical_string_bank(
    module: ModuleElectricalResult,
    *,
    string_ids: Iterable[str],
    modules_in_series: int,
) -> dict[str, StringElectricalResult]:
    """Build multiple electrically identical strings from one module state."""
    ids = list(string_ids)
    if not ids:
        raise ValueError("string_ids must not be empty")
    if len(ids) != len(set(ids)):
        raise ValueError("string_ids must be unique")

    return {
        string_id: calculate_identical_series_string(
            module,
            string_id=string_id,
            modules_in_series=modules_in_series,
        )
        for string_id in ids
    }
