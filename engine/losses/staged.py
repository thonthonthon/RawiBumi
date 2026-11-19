"""Opt-in loss chain: independent MPPT circuits and explicit AC boundaries.

The historical kernels remain unchanged. Each circuit calls the existing scalar
kernel independently, then receives its own fixed-reference I²R stage.
"""

from __future__ import annotations
from dataclasses import replace
from typing import Any, Mapping, Sequence
import numpy as np
import pandas as pd
from electrical.mppt import MPPTAggregationResult
from engine.inverter import (
    InverterElectricalResult,
    simulate_voltage_dependent_inverter,
)
from .array import ArrayLossResult, apply_pre_inverter_array_losses
from .energy import aggregate_interval_quantities
from .ledger import ElectricalLossLedgerResult, _LEDGER_CHANNELS, with_current_limit, with_orientation_mismatch

NEW_CHANNELS = (
    ("lid", "lid_loss_w", "raw_array_mpp_w", "after_lid_w"),
    (
        "module_quality",
        "module_quality_loss_w",
        "after_lid_w",
        "after_module_quality_w",
    ),
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
        "after_string_mismatch_w",
    ),
    (
        "degradation",
        "degradation_loss_w",
        "after_string_mismatch_w",
        "before_dc_wiring_w",
    ),
    *_LEDGER_CHANNELS[3:-1],
    (
        "inverter_self_consumption",
        "inverter_self_consumption_w",
        "ac_available_w",
        "ac_net_output_w",
    ),
    ("ac_wiring", "ac_wiring_loss_w", "ac_net_output_w", "after_ac_wiring_w"),
    (
        "transformer_iron",
        "transformer_iron_loss_w",
        "after_ac_wiring_w",
        "after_transformer_iron_w",
    ),
    (
        "transformer_copper",
        "transformer_copper_loss_w",
        "after_transformer_iron_w",
        "after_transformer_w",
    ),
    ("unavailability", "unavailability_loss_w", "after_transformer_w", "pcc_power_w"),
)
OPTICAL_CHANNELS = (
    (
        "soiling",
        "soiling_reference_loss_w",
        "optical_reference_w",
        "after_soiling_reference_w",
    ),
    (
        "module_operating_effects",
        "module_operating_delta_w",
        "after_soiling_reference_w",
        "raw_array_mpp_w",
    ),
)


def _scale_bank(
    bank: Mapping[int, MPPTAggregationResult], fraction: float
) -> dict[int, MPPTAggregationResult]:
    if fraction == 0:
        return dict(bank)
    output = {}
    for key, item in bank.items():
        frame = item.frame.copy()
        frame["mppt_pmp_w"] = frame["mppt_pmp_w"] - frame["mppt_pmp_w"] * fraction
        frame["mppt_imp_a"] = frame["mppt_imp_a"] - frame["mppt_imp_a"] * fraction
        output[key] = replace(item, frame=frame)
    return output


def apply_circuit_losses(
    bank: Mapping[int, MPPTAggregationResult],
    settings: Mapping[str, Any],
    references: Mapping[int, Mapping[str, Any]],
    *,
    quality: float,
) -> ArrayLossResult:
    values = settings["values"]
    adjusted, frames, circuits = {}, [], {}
    for key, item in sorted(bank.items()):
        reference = references[key]
        circuit_quality = reference.get("module_quality_fraction", quality)
        lid_fraction = reference.get("lid_fraction", values["lid_fraction"])
        if lid_fraction is None:
            raise ValueError(f"MPPT {key}: resolve automatic LID in the circuit reference before applying losses")
        start = item.frame["mppt_pmp_w"].to_numpy(dtype=float)
        after_lid = _scale_bank({key: item}, lid_fraction)
        scalar = apply_pre_inverter_array_losses(
            after_lid,
            module_quality_loss_fraction=circuit_quality,
            module_mismatch_loss_fraction=reference["module_mismatch_fraction"],
            string_mismatch_loss_fraction=reference["string_mismatch_fraction"],
        )
        degraded = _scale_bank(scalar.mppt_bank, values["degradation_fraction"])
        incoming = degraded[key].frame
        current = np.divide(
            incoming["mppt_pmp_w"].to_numpy(dtype=float),
            incoming["mppt_vmp_v"].to_numpy(dtype=float),
            out=np.zeros(len(incoming)),
            where=incoming["mppt_vmp_v"].to_numpy(dtype=float) > 0,
        )
        drop = current * reference["resistance_ohm"]
        if np.any(
            (current > 0) & (drop >= incoming["mppt_vmp_v"].to_numpy(dtype=float))
        ):
            raise ValueError(
                f"MPPT {key}: circuit DC voltage drop reaches/exceeds operating voltage"
            )
        if lid_fraction == 0 and values["degradation_fraction"] == 0:
            # No extra scalar round trip: still one independent circuit, never a pooled bank.
            wired = apply_pre_inverter_array_losses(
                {key: item},
                module_quality_loss_fraction=circuit_quality,
                module_mismatch_loss_fraction=reference["module_mismatch_fraction"],
                string_mismatch_loss_fraction=reference["string_mismatch_fraction"],
                dc_array_resistance_ohm=reference["resistance_ohm"],
            )
        else:
            wired = apply_pre_inverter_array_losses(
                degraded, dc_array_resistance_ohm=reference["resistance_ohm"]
            )
        f = scalar.frame.copy()
        f["raw_array_mpp_w"] = start
        f["lid_loss_w"] = start * lid_fraction
        f["after_lid_w"] = start - f["lid_loss_w"]
        f["after_string_mismatch_w"] = scalar.frame["before_dc_wiring_w"]
        f["degradation_loss_w"] = (
            f["after_string_mismatch_w"] * values["degradation_fraction"]
        )
        f["before_dc_wiring_w"] = f["after_string_mismatch_w"] - f["degradation_loss_w"]
        f["after_degradation_w"] = f["before_dc_wiring_w"]
        for column in (
            "dc_array_current_a",
            "dc_wiring_voltage_drop_v",
            "dc_wiring_loss_w",
            "array_virtual_mpp_w",
        ):
            f[column] = wired.frame[column]
        frames.append(f)
        adjusted.update(wired.mppt_bank)
        circuits[str(key)] = {**reference, "module_quality_fraction": circuit_quality}
    first = frames[0]
    frame = pd.DataFrame(
        {c: sum((f[c] for f in frames)) for c in first if c.endswith("_w")},
        index=first.index,
    )
    # Currents/voltage drops have no meaningful plant-equivalent voltage. Retain per-circuit evidence.
    if len(frames) == 1:
        for c in ("dc_array_current_a", "dc_wiring_voltage_drop_v"):
            frame[c] = first[c]
    return ArrayLossResult(
        adjusted,
        frame,
        {
            "model_id": "array_losses.per_circuit.v0.1",
            "dc_wiring_model": "independent_circuit_stc_i2r",
            "circuits": circuits,
            "quality_mismatch_voltage_policy": "preserve_vmp_map_power_factor_to_imp",
        },
    )


def apply_ac_wiring(
    power: pd.Series, fraction: float, nominal_w: float
) -> pd.DataFrame:
    if not np.isfinite(nominal_w) or nominal_w <= 0:
        raise ValueError("AC wiring requires the inverter's positive nominal AC power")
    loss = fraction * power**2 / nominal_w
    return pd.DataFrame({"ac_wiring_loss_w": loss, "after_ac_wiring_w": power - loss})


def apply_plant_losses(
    power: pd.Series,
    settings: Mapping[str, Any],
    *,
    nominal_w: float,
    plant_ac_segment: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    cable = None
    if plant_ac_segment is not None and plant_ac_segment.get("active"):
        cable = apply_ac_segment(power, plant_ac_segment)
        power = cable["downstream_w"]
    transformer = settings["values"]["transformer"]
    reference = transformer["reference_power_w"] or nominal_w
    if not np.isfinite(reference) or reference <= 0:
        raise ValueError("plant transformer requires a positive reference power")
    iron = transformer["iron_fraction"] * reference if transformer["enabled"] else 0.0
    copper = (
        transformer["copper_fraction"] * power**2 / reference
        if transformer["enabled"]
        else power * 0
    )
    before_availability = power - iron - copper
    unavailable = settings["values"][
        "unavailability_fraction"
    ] * before_availability.clip(lower=0)
    result = pd.DataFrame(
        {
            "transformer_iron_loss_w": np.full(len(power), iron),
            "after_transformer_iron_w": power - iron,
            "transformer_copper_loss_w": copper,
            "after_transformer_w": before_availability,
            "unavailability_loss_w": unavailable,
            "pcc_power_w": before_availability - unavailable,
        },
        index=power.index,
    )
    if cable is not None:
        result["plant_ac_wiring_loss_w"] = cable["loss_w"]
        result["after_plant_ac_wiring_w"] = cable["downstream_w"]
    return result


def reconcile_loss_frame(
    frame: pd.DataFrame,
    *,
    interval_seconds: Any,
    optical: bool = False,
    settings: Mapping[str, Any],
) -> ElectricalLossLedgerResult:
    channels = with_current_limit(with_orientation_mismatch((*OPTICAL_CHANNELS, *NEW_CHANNELS) if optical else NEW_CHANNELS, frame), frame)
    if "plant_ac_wiring_loss_w" in frame:
        channels = tuple(
            (
                name,
                loss,
                "after_plant_ac_wiring_w" if name == "transformer_iron" else up,
                down,
            )
            for name, loss, up, down in channels
        )
        index = next(i for i, row in enumerate(channels) if row[0] == "ac_wiring") + 1
        channels = (
            *channels[:index],
            (
                "plant_ac_wiring",
                "plant_ac_wiring_loss_w",
                "after_ac_wiring_w",
                "after_plant_ac_wiring_w",
            ),
            *channels[index:],
        )
    maximum = 0.0
    for name, loss, upstream, downstream in channels:
        residual = frame[downstream] - (frame[upstream] - frame[loss])
        frame[f"{name}_reconciliation_residual_w"] = residual
        maximum = max(maximum, float(residual.abs().max()))
    if maximum > 1e-6:
        raise RuntimeError(f"new loss ledger does not reconcile: {maximum} W")
    columns = sorted({c for _, loss, up, down in channels for c in (loss, up, down)})
    energy = aggregate_interval_quantities(
        frame, interval_seconds=interval_seconds, power_columns_w=columns
    )
    rows = []
    for order, (name, loss, up, down) in enumerate(channels, 1):
        e = lambda c: energy.annual[c.replace("_w", "_kwh")]
        value = e(loss)
        rows.append(
            {
                "order": order,
                "channel": name,
                "loss_power_column": loss,
                "upstream_power_column": up,
                "downstream_power_column": down,
                "loss_energy_kwh": value,
                "upstream_energy_kwh": e(up),
                "downstream_energy_kwh": e(down),
                "classification": (
                    "gain" if value < 0 else ("loss" if value > 0 else "zero")
                ),
            }
        )
    summary = pd.DataFrame(rows).set_index("order")
    reference = "optical_reference_kwh" if optical else "raw_array_mpp_kwh"
    residual = (
        energy.annual[reference]
        - float(summary.loss_energy_kwh.sum())
        - energy.annual["pcc_power_kwh"]
    )
    if abs(residual) > 1e-9:
        raise RuntimeError(f"new annual loss ledger does not reconcile: {residual} kWh")
    return ElectricalLossLedgerResult(
        frame,
        energy,
        summary,
        {
            "schema_name": "ElectricalLossLedgerResult",
            "schema_version": "0.1",
            "model_id": "loss_ledger.staged.v0.1",
            "scope": "post_iam_reference_to_pcc" if optical else "raw_array_mpp_to_pcc",
            "pcc_boundary": "after_ac_wiring_transformer_and_unavailability",
            "channel_order": [c[0] for c in channels],
            "signed_loss_convention": "positive_loss_negative_gain",
            "downstream_ac_stages_modelled": True,
            "max_interval_reconciliation_residual_w": maximum,
            "annual_reconciliation_residual_kwh": residual,
            "resolved_loss_settings": dict(settings),
        },
    )


def build_staged_ledger(
    arrays: ArrayLossResult,
    inverter: InverterElectricalResult,
    *,
    settings: Mapping[str, Any],
    nominal_w: float,
    interval_seconds: Any,
    apply_plant: bool = True,
    circuit_loss_context: Mapping[str, Any] | None = None,
) -> ElectricalLossLedgerResult:
    frame = arrays.frame.copy()
    for c in inverter.frame:
        if c != "evaluation_time":
            frame[c] = inverter.frame[c]
    for c, data in apply_ac_wiring(
        frame["ac_net_output_w"],
        settings["values"]["ac_wiring_nominal_fraction"],
        nominal_w,
    ).items():
        frame[c] = data
    if circuit_loss_context is not None and circuit_loss_context["ac_wiring"]["active"]:
        stage = apply_ac_segment(
            frame["ac_net_output_w"], circuit_loss_context["ac_wiring"]
        )
        frame["ac_wiring_loss_w"] = stage["loss_w"]
        frame["after_ac_wiring_w"] = stage["downstream_w"]
    effective = settings
    if not apply_plant:
        from copy import deepcopy

        effective = deepcopy(settings)
        effective["values"]["transformer"]["enabled"] = False
        effective["values"]["unavailability_fraction"] = 0.0
    for c, data in apply_plant_losses(
        frame["after_ac_wiring_w"],
        effective,
        nominal_w=nominal_w,
        plant_ac_segment=(
            circuit_loss_context.get("plant_ac_wiring")
            if circuit_loss_context is not None and apply_plant
            else None
        ),
    ).items():
        frame[c] = data
    return reconcile_loss_frame(
        frame,
        interval_seconds=interval_seconds,
        settings={
            **settings,
            "circuits": arrays.metadata.get("circuits", {}),
            "inverter_reference_power_w": nominal_w,
            "transformer_reference_power_w": settings["values"]["transformer"][
                "reference_power_w"
            ]
            or nominal_w,
            "measurement_boundary": "after_ac_wiring_transformer_and_unavailability",
            "method": "manufacturing_dispersion_scalar",
        },
    )


def apply_ac_segment(power: pd.Series, resolved: Mapping[str, Any]) -> pd.DataFrame:
    """A declared segment on signed net real power, never a voltage-flow solver."""
    if not np.isfinite(power.to_numpy(dtype=float)).all():
        raise ValueError("AC segment power must be finite")
    if resolved["mode"] == "percent":
        loss = resolved["loss_fraction"] * power**2 / resolved["reference_power_w"]
    else:
        loss = (
            resolved["resistance_per_phase_ohm"]
            * power**2
            / resolved["line_voltage_v"] ** 2
        )
    if (
        not np.isfinite(loss.to_numpy(dtype=float)).all()
        or ((power != 0) & (loss >= power.abs())).any()
    ):
        raise ValueError(
            "AC cable or percentage would reach/exceed the modeled bus voltage; check the segment inputs"
        )
    return pd.DataFrame(
        {"loss_w": loss, "downstream_w": power - loss}, index=power.index
    )
