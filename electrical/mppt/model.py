"""Explicit string assignment and analytical MPPT aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from electrical.string import StringElectricalResult
from engine.module.pvsyst import SDM_COLUMNS as MODULE_SDM_COLUMNS


MPPT_IDENTICAL_PARALLEL_MPP = "mppt.identical_parallel_mpp.v0.1"
SUPPORTED_MPPT_MODELS = {MPPT_IDENTICAL_PARALLEL_MPP}


@dataclass(frozen=True)
class MPPTAggregationResult:
    """Interval-start indexed DC state at one independent MPPT."""

    mppt_index: int
    string_ids: tuple[str, ...]
    frame: pd.DataFrame
    metadata: dict[str, Any]


def balanced_string_assignment(
    string_ids: Iterable[str],
    *,
    mppt_count: int,
    total_input_count: int | None = None,
) -> dict[int, tuple[str, ...]]:
    """Return a deterministic balanced assignment suggestion.

    This helper is optional. Runtime simulation does not call it implicitly; the
    electrical design remains the authority for MPPT assignment.
    """
    ids = list(string_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("string_ids must be unique")
    if not isinstance(mppt_count, int) or mppt_count < 1:
        raise ValueError("mppt_count must be an integer >= 1")
    if total_input_count is not None:
        if not isinstance(total_input_count, int) or total_input_count < 1:
            raise ValueError("total_input_count must be an integer >= 1")
        if len(ids) > total_input_count:
            raise ValueError(
                "string count exceeds verified total inverter DC input count"
            )

    base_count, remainder = divmod(len(ids), mppt_count)
    assignments: dict[int, tuple[str, ...]] = {}
    cursor = 0
    for index in range(1, mppt_count + 1):
        count = base_count + (1 if index <= remainder else 0)
        assignments[index] = tuple(ids[cursor : cursor + count])
        cursor += count
    return assignments


def validate_mppt_assignment(
    assignments: Mapping[int, Iterable[str]],
    *,
    string_ids: Iterable[str],
    mppt_count: int,
    total_input_count: int | None = None,
    input_count_per_mppt: int | None = None,
) -> dict[int, tuple[str, ...]]:
    """Validate an explicit manual string-to-MPPT assignment."""
    ids = list(string_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("string_ids must be unique")
    if not isinstance(mppt_count, int) or mppt_count < 1:
        raise ValueError("mppt_count must be an integer >= 1")

    expected_indices = set(range(1, mppt_count + 1))
    supplied_indices = set(assignments)
    invalid_indices = supplied_indices - expected_indices
    if invalid_indices:
        raise ValueError(
            f"assignment contains invalid MPPT indices: {sorted(invalid_indices)}"
        )

    normalized: dict[int, tuple[str, ...]] = {
        index: tuple(assignments.get(index, ()))
        for index in range(1, mppt_count + 1)
    }
    flattened = [
        string_id
        for index in range(1, mppt_count + 1)
        for string_id in normalized[index]
    ]

    duplicates = sorted(
        {string_id for string_id in flattened if flattened.count(string_id) > 1}
    )
    if duplicates:
        raise ValueError(
            f"strings assigned to more than one MPPT: {duplicates}"
        )

    unknown = sorted(set(flattened) - set(ids))
    if unknown:
        raise ValueError(f"assignment references unknown strings: {unknown}")

    unassigned = sorted(set(ids) - set(flattened))
    if unassigned:
        raise ValueError(f"strings are not assigned to an MPPT: {unassigned}")

    if total_input_count is not None:
        if not isinstance(total_input_count, int) or total_input_count < 1:
            raise ValueError("total_input_count must be an integer >= 1")
        if len(flattened) > total_input_count:
            raise ValueError(
                "assigned string count exceeds verified total inverter DC input count"
            )

    if input_count_per_mppt is not None:
        if not isinstance(input_count_per_mppt, int) or input_count_per_mppt < 1:
            raise ValueError("input_count_per_mppt must be an integer >= 1")
        overloaded = {
            index: len(values)
            for index, values in normalized.items()
            if len(values) > input_count_per_mppt
        }
        if overloaded:
            raise ValueError(
                "MPPT assignment exceeds verified per-MPPT input count: "
                f"{overloaded}"
            )

    return normalized


def _require_common_string_state(
    string_results: list[StringElectricalResult],
    *,
    column: str,
    active_mask: np.ndarray,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> np.ndarray:
    stacked = np.vstack(
        [item.frame[column].to_numpy(dtype=float) for item in string_results]
    )
    reference = stacked[0]
    tolerance = absolute_tolerance + relative_tolerance * np.abs(reference)
    mismatch = np.abs(stacked - reference) > tolerance
    mismatch[:, ~active_mask] = False
    if mismatch.any():
        raise ValueError(
            f"parallel MPPT analytical aggregation requires common {column}; "
            "full IV aggregation is required for mismatched strings"
        )
    return reference


def aggregate_parallel_strings(
    string_bank: Mapping[str, StringElectricalResult],
    *,
    mppt_index: int,
    string_ids: Iterable[str],
    min_operating_voltage_v: float | None = None,
    max_operating_voltage_v: float | None = None,
    max_operating_current_a: float | None = None,
    common_voltage_absolute_tolerance_v: float = 1e-6,
    common_voltage_relative_tolerance: float = 1e-9,
) -> MPPTAggregationResult:
    """Aggregate explicitly assigned strings at one common MPP voltage.

    The analytical result is exact for the current unshaded identical-string scope.
    If strings do not share the same active/Vmp/Voc state, the function refuses to
    approximate a multi-curve MPPT operating point.
    """
    ids = tuple(string_ids)
    if not isinstance(mppt_index, int) or mppt_index < 1:
        raise ValueError("mppt_index must be an integer >= 1")
    if not ids:
        raise ValueError("an aggregated MPPT must have at least one string")
    if len(ids) != len(set(ids)):
        raise ValueError("MPPT string_ids must be unique")

    missing_ids = sorted(set(ids) - set(string_bank))
    if missing_ids:
        raise ValueError(f"MPPT references missing string results: {missing_ids}")

    strings = [string_bank[string_id] for string_id in ids]
    index = strings[0].frame.index
    if any(not item.frame.index.equals(index) for item in strings[1:]):
        raise ValueError("all strings on an MPPT must share the same interval index")

    active_stack = np.vstack(
        [item.frame["active"].to_numpy(dtype=bool) for item in strings]
    )
    all_active = active_stack.all(axis=0)
    all_inactive = (~active_stack).all(axis=0)
    if not np.all(all_active | all_inactive):
        raise ValueError(
            "parallel MPPT analytical aggregation requires identical active state; "
            "full IV aggregation is required for mismatched strings"
        )

    vmp = _require_common_string_state(
        strings,
        column="string_vmp_v",
        active_mask=all_active,
        absolute_tolerance=common_voltage_absolute_tolerance_v,
        relative_tolerance=common_voltage_relative_tolerance,
    )
    voc = _require_common_string_state(
        strings,
        column="string_voc_v",
        active_mask=all_active,
        absolute_tolerance=common_voltage_absolute_tolerance_v,
        relative_tolerance=common_voltage_relative_tolerance,
    )

    isc = np.sum(
        np.vstack(
            [item.frame["string_isc_a"].to_numpy(dtype=float) for item in strings]
        ),
        axis=0,
    )
    imp = np.sum(
        np.vstack(
            [item.frame["string_imp_a"].to_numpy(dtype=float) for item in strings]
        ),
        axis=0,
    )
    pmp = np.sum(
        np.vstack(
            [item.frame["string_pmp_w"].to_numpy(dtype=float) for item in strings]
        ),
        axis=0,
    )

    product = vmp * imp
    denominator = np.maximum(np.maximum(np.abs(product), np.abs(pmp)), 1e-12)
    identity_error = np.abs(pmp - product) / denominator
    if (identity_error > 1e-8).any():
        raise RuntimeError("MPPT Pmp does not reconcile with Vmp*Imp")

    def _positive_optional(value: float | None, name: str) -> float | None:
        if value is None:
            return None
        numeric = float(value)
        if not isfinite(numeric) or numeric <= 0:
            raise ValueError(f"{name} must be finite and positive when supplied")
        return numeric

    min_voltage = _positive_optional(
        min_operating_voltage_v, "min_operating_voltage_v"
    )
    max_voltage = _positive_optional(
        max_operating_voltage_v, "max_operating_voltage_v"
    )
    max_current = _positive_optional(
        max_operating_current_a, "max_operating_current_a"
    )
    if (
        min_voltage is not None
        and max_voltage is not None
        and min_voltage > max_voltage
    ):
        raise ValueError("minimum MPPT voltage cannot exceed maximum MPPT voltage")

    below_min = (
        all_active & (vmp < min_voltage)
        if min_voltage is not None
        else np.zeros(len(index), dtype=bool)
    )
    above_max = (
        all_active & (vmp > max_voltage)
        if max_voltage is not None
        else np.zeros(len(index), dtype=bool)
    )
    voltage_limit_known = min_voltage is not None and max_voltage is not None
    within_voltage = (
        all_active & ~below_min & ~above_max
        if voltage_limit_known
        else np.zeros(len(index), dtype=bool)
    )

    current_violation_values = []
    if max_current is None:
        current_violation_values = [pd.NA] * len(index)
    else:
        current_violation_values = [
            bool(active and current > max_current)
            for active, current in zip(all_active, imp)
        ]

    frame = pd.DataFrame(index=index.copy())
    frame.index.name = "interval_start"
    if "evaluation_time" in strings[0].frame:
        frame["evaluation_time"] = strings[0].frame["evaluation_time"].to_numpy()
    frame["mppt_isc_a"] = isc
    frame["mppt_voc_v"] = voc
    frame["mppt_imp_a"] = imp
    frame["mppt_vmp_v"] = vmp
    frame["mppt_pmp_w"] = pmp
    frame["string_count"] = len(ids)
    frame["active"] = all_active
    frame["pmp_identity_relative_error"] = identity_error
    frame["voltage_below_min"] = below_min
    frame["voltage_above_max"] = above_max
    frame["voltage_within_window"] = within_voltage
    frame["operating_current_limit_known"] = max_current is not None
    frame["operating_current_above_limit"] = pd.array(
        current_violation_values,
        dtype="boolean",
    )
    # The raw MPP before any array loss, and the shared module IV model: the inverter recovers the loss chain's
    # current factor and wiring resistance from these and solves the constrained point (USE1, MPPT current limit).
    frame["source_mpp_vmp_v"] = vmp
    frame["source_mpp_imp_a"] = imp
    series = {item.metadata.get("modules_in_series") for item in strings}
    if len(series) == 1 and None not in series:
        frame["modules_in_series"] = int(next(iter(series)))
    if all(column in item.frame for item in strings for column in MODULE_SDM_COLUMNS):
        for column in MODULE_SDM_COLUMNS:
            frame[column] = _require_common_string_state(
                strings,
                column=column,
                active_mask=all_active,
                absolute_tolerance=0.0,
                relative_tolerance=1e-12,
            )

    metadata = {
        "schema_name": "MPPTAggregationResult",
        "schema_version": "0.1",
        "model_id": MPPT_IDENTICAL_PARALLEL_MPP,
        "mppt_index": mppt_index,
        "string_ids": list(ids),
        "string_count": len(ids),
        "aggregation_scope": "common_string_mpp_state_only",
        "min_operating_voltage_v": min_voltage,
        "max_operating_voltage_v": max_voltage,
        "max_operating_current_a": max_current,
        "voltage_limit_known": voltage_limit_known,
        "operating_current_limit_known": max_current is not None,
        "common_voltage_absolute_tolerance_v": float(
            common_voltage_absolute_tolerance_v
        ),
        "common_voltage_relative_tolerance": float(
            common_voltage_relative_tolerance
        ),
    }
    return MPPTAggregationResult(
        mppt_index=mppt_index,
        string_ids=ids,
        frame=frame,
        metadata=metadata,
    )


def aggregate_mppt_bank(
    string_bank: Mapping[str, StringElectricalResult],
    assignments: Mapping[int, Iterable[str]],
    *,
    mppt_count: int,
    total_input_count: int | None = None,
    input_count_per_mppt: int | None = None,
    min_operating_voltage_v: float | None = None,
    max_operating_voltage_v: float | None = None,
    max_operating_current_a: float | None = None,
) -> dict[int, MPPTAggregationResult]:
    """Validate explicit assignments and aggregate every populated MPPT."""
    normalized = validate_mppt_assignment(
        assignments,
        string_ids=string_bank.keys(),
        mppt_count=mppt_count,
        total_input_count=total_input_count,
        input_count_per_mppt=input_count_per_mppt,
    )

    return {
        index: aggregate_parallel_strings(
            string_bank,
            mppt_index=index,
            string_ids=string_ids,
            min_operating_voltage_v=min_operating_voltage_v,
            max_operating_voltage_v=max_operating_voltage_v,
            max_operating_current_a=max_operating_current_a,
        )
        for index, string_ids in normalized.items()
        if string_ids
    }


def total_mppt_power_w(
    mppt_bank: Mapping[int, MPPTAggregationResult],
) -> pd.Series:
    """Sum independent MPPT powers without inventing a common inverter DC voltage."""
    if not mppt_bank:
        raise ValueError("mppt_bank must not be empty")
    results = list(mppt_bank.values())
    index = results[0].frame.index
    if any(not item.frame.index.equals(index) for item in results[1:]):
        raise ValueError("all MPPT results must share the same interval index")
    total = np.sum(
        np.vstack(
            [item.frame["mppt_pmp_w"].to_numpy(dtype=float) for item in results]
        ),
        axis=0,
    )
    return pd.Series(total, index=index, name="total_mppt_pmp_w")
