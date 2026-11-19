"""Detailed PVsyst-v6 single-diode runtime for the Phase-3 module engine."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd
import pvlib

from components.pan.pvsyst_sdm import (
    REQUIRED_PVSYST_PARAMETERS,
    calculate_pvsyst_diode_parameters,
)
from engine.optical import OpticalResult
from engine.thermal import ThermalResult


MODULE_PVSYST_SDM = "module.pvsyst_singlediode.v6"
SUPPORTED_MODULE_MODELS = {MODULE_PVSYST_SDM}
# Per-module single-diode parameters, in pvlib's calcparams order (I_L, I_0, R_s, R_sh, nNsVth).
SDM_COLUMNS = (
    "sdm_photocurrent_a",
    "sdm_saturation_current_a",
    "sdm_series_resistance_ohm",
    "sdm_shunt_resistance_ohm",
    "sdm_nnsvth_v",
)


@dataclass(frozen=True)
class ModuleElectricalResult:
    """Per-module IV summary at the operating MPP for every interval."""

    frame: pd.DataFrame
    metadata: dict[str, Any]


def extract_validated_pvsyst_parameter_set(
    module_definition: dict[str, Any],
) -> dict[str, Any]:
    """Return the validated detailed PVsyst parameter set from a canonical module."""
    for model in module_definition.get("electrical_models") or []:
        if model.get("model_type") != "pvsyst_singlediode":
            continue
        validation = model.get("validation") or {}
        if validation.get("passed") is not True:
            raise ValueError(
                "PVsyst single-diode model exists but has not passed detailed validation"
            )
        params = model.get("parameter_set") or {}
        missing = sorted(REQUIRED_PVSYST_PARAMETERS - set(params))
        if missing:
            raise ValueError(
                "validated PVsyst model is missing runtime parameters: "
                + ", ".join(missing)
            )
        return dict(params)
    raise ValueError("module definition has no validated PVsyst single-diode model")


def calculate_pvsyst_module_electrical(
    optical: OpticalResult,
    thermal: ThermalResult,
    *,
    parameter_set: dict[str, Any],
    module_area_m2: float,
    solver: str = "lambertw",
    active_irradiance_threshold_w_m2: float = 1e-6,
    power_identity_relative_tolerance: float = 1e-8,
) -> ModuleElectricalResult:
    """Calculate per-module Isc/Voc/Imp/Vmp/Pmp with the validated PVsyst SDM.

    Effective irradiance drives the electrical model. External module efficiency is
    reported on the incident-POA basis because that is the efficiency required by
    the PVsyst thermal heat-balance equation.
    """
    if not optical.frame.index.equals(thermal.frame.index):
        raise ValueError("optical and thermal intervals must align exactly")
    if not isfinite(float(module_area_m2)) or module_area_m2 <= 0:
        raise ValueError("module_area_m2 must be finite and positive")
    if (
        not isfinite(float(active_irradiance_threshold_w_m2))
        or active_irradiance_threshold_w_m2 < 0
    ):
        raise ValueError(
            "active_irradiance_threshold_w_m2 must be finite and non-negative"
        )
    if (
        not isfinite(float(power_identity_relative_tolerance))
        or power_identity_relative_tolerance < 0
    ):
        raise ValueError(
            "power_identity_relative_tolerance must be finite and non-negative"
        )

    missing = sorted(REQUIRED_PVSYST_PARAMETERS - set(parameter_set))
    if missing:
        raise ValueError(
            "incomplete PVsyst single-diode parameter set: " + ", ".join(missing)
        )

    index = optical.frame.index
    effective = pd.to_numeric(
        optical.frame["effective_irradiance_w_m2"], errors="coerce"
    ).reindex(index)
    incident = pd.to_numeric(
        optical.frame["incident_poa_global_w_m2"], errors="coerce"
    ).reindex(index)
    temperature = pd.to_numeric(
        thermal.frame["cell_temperature_c"], errors="coerce"
    ).reindex(index)

    if effective.isna().any() or incident.isna().any() or temperature.isna().any():
        raise ValueError(
            "module electrical model requires complete effective irradiance, "
            "incident POA, and cell temperature"
        )
    if (effective < 0).any() or (incident < 0).any():
        raise ValueError("module electrical irradiance inputs must be non-negative")

    active = effective.to_numpy(dtype=float) > float(
        active_irradiance_threshold_w_m2
    )
    n = len(index)
    outputs = {
        "isc_a": np.zeros(n, dtype=float),
        "voc_v": np.zeros(n, dtype=float),
        "imp_a": np.zeros(n, dtype=float),
        "vmp_v": np.zeros(n, dtype=float),
        "pmp_w": np.zeros(n, dtype=float),
    }
    # Single-diode parameters per interval, kept so later stages can solve the IV curve away from the MPP
    # (the MPPT current limit, USE1). NaN where inactive.
    sdm = {name: np.full(n, np.nan) for name in SDM_COLUMNS}

    if active.any():
        diode_params = calculate_pvsyst_diode_parameters(
            effective_irradiance_w_m2=effective.to_numpy(dtype=float)[active],
            cell_temperature_c=temperature.to_numpy(dtype=float)[active],
            parameter_set=parameter_set,
        )
        for name, values in zip(SDM_COLUMNS, diode_params):
            sdm[name][active] = np.broadcast_to(np.asarray(values, dtype=float), (int(active.sum()),))
        solved = pvlib.pvsystem.singlediode(*diode_params, method=solver)
        mapping = {
            "isc_a": "i_sc",
            "voc_v": "v_oc",
            "imp_a": "i_mp",
            "vmp_v": "v_mp",
            "pmp_w": "p_mp",
        }
        for target, source in mapping.items():
            outputs[target][active] = np.asarray(solved[source], dtype=float)

    for name, values in outputs.items():
        if not np.isfinite(values).all():
            raise RuntimeError(f"PVsyst module model produced non-finite {name}")
        if (values < -1e-10).any():
            raise RuntimeError(f"PVsyst module model produced negative {name}")
        outputs[name] = np.maximum(values, 0.0)

    if (outputs["voc_v"] + 1e-9 < outputs["vmp_v"]).any():
        raise RuntimeError("PVsyst module model produced Vmp above Voc")
    if (outputs["isc_a"] + 1e-9 < outputs["imp_a"]).any():
        raise RuntimeError("PVsyst module model produced Imp above Isc")

    product = outputs["vmp_v"] * outputs["imp_a"]
    denominator = np.maximum(
        np.maximum(np.abs(outputs["pmp_w"]), np.abs(product)),
        1e-12,
    )
    identity_error = np.abs(outputs["pmp_w"] - product) / denominator
    if (identity_error > power_identity_relative_tolerance).any():
        raise RuntimeError("Pmp does not reconcile with Vmp*Imp within tolerance")

    incident_array = incident.to_numpy(dtype=float)
    effective_array = effective.to_numpy(dtype=float)
    external_efficiency = np.zeros(n, dtype=float)
    effective_basis_efficiency = np.zeros(n, dtype=float)

    incident_mask = incident_array > 0
    effective_mask = effective_array > 0
    external_efficiency[incident_mask] = (
        outputs["pmp_w"][incident_mask]
        / (incident_array[incident_mask] * float(module_area_m2))
    )
    effective_basis_efficiency[effective_mask] = (
        outputs["pmp_w"][effective_mask]
        / (effective_array[effective_mask] * float(module_area_m2))
    )

    if (external_efficiency < -1e-12).any() or (
        external_efficiency > 1.0 + 1e-9
    ).any():
        raise RuntimeError("external module efficiency escaped physical 0..1 bounds")
    if (effective_basis_efficiency < -1e-12).any() or (
        effective_basis_efficiency > 1.0 + 1e-9
    ).any():
        raise RuntimeError(
            "effective-irradiance module efficiency escaped physical 0..1 bounds"
        )

    frame = pd.DataFrame(index=index.copy())
    frame.index.name = "interval_start"
    if "evaluation_time" in optical.frame:
        frame["evaluation_time"] = optical.frame["evaluation_time"].to_numpy()
    frame["effective_irradiance_w_m2"] = effective_array
    frame["incident_poa_global_w_m2"] = incident_array
    frame["cell_temperature_c"] = temperature.to_numpy(dtype=float)
    frame["isc_a"] = outputs["isc_a"]
    frame["voc_v"] = outputs["voc_v"]
    frame["imp_a"] = outputs["imp_a"]
    frame["vmp_v"] = outputs["vmp_v"]
    frame["pmp_w"] = outputs["pmp_w"]
    frame["module_efficiency_fraction"] = external_efficiency
    frame["module_efficiency_on_effective_irradiance_fraction"] = (
        effective_basis_efficiency
    )
    frame["pmp_identity_relative_error"] = identity_error
    frame["active"] = active
    for name, values in sdm.items():
        frame[name] = values

    metadata = {
        "schema_name": "ModuleElectricalResult",
        "schema_version": "0.1",
        "model_id": MODULE_PVSYST_SDM,
        "implementation": (
            "components.pan.pvsyst_sdm.calculate_pvsyst_diode_parameters + "
            "pvlib.pvsystem.singlediode"
        ),
        "pvlib_version": pvlib.__version__,
        "solver": solver,
        "module_area_m2": float(module_area_m2),
        "effective_irradiance_basis": "optical.effective_irradiance_w_m2",
        "external_efficiency_basis": "incident_poa_global_w_m2_times_module_area",
        "active_irradiance_threshold_w_m2": float(
            active_irradiance_threshold_w_m2
        ),
        "power_identity_relative_tolerance": float(
            power_identity_relative_tolerance
        ),
        "active_interval_count": int(active.sum()),
    }
    return ModuleElectricalResult(frame=frame, metadata=metadata)
