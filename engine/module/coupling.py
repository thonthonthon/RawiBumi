"""Fixed-point coupling between PVsyst thermal and module electrical state."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

import numpy as np

from engine.irradiance import PlaneOfArrayResult
from engine.optical import OpticalResult
from engine.thermal import (
    SUPPORTED_THERMAL_MODELS,
    THERMAL_PVSYST,
    THERMAL_PVSYST81_TRANSIENT,
    ThermalResult,
    calculate_pvsyst81_transient_temperature,
    calculate_pvsyst_temperature,
)
from weather.core import CanonicalWeather

from .pvsyst import ModuleElectricalResult, calculate_pvsyst_module_electrical


@dataclass(frozen=True)
class CoupledModuleThermalResult:
    """Self-consistent module electrical and PVsyst thermal solution."""

    thermal: ThermalResult
    electrical: ModuleElectricalResult
    metadata: dict[str, Any]


def _calculate_thermal_state(
    poa: PlaneOfArrayResult,
    weather: CanonicalWeather,
    *,
    thermal_model_id: str,
    u_c_w_m2k: float,
    u_v_w_m2k_per_ms: float,
    alpha_absorption: float,
    module_efficiency: np.ndarray,
    module_unit_mass_kg_m2: float | None,
) -> ThermalResult:
    steady_state = calculate_pvsyst_temperature(
        poa,
        weather,
        u_c_w_m2k=u_c_w_m2k,
        u_v_w_m2k_per_ms=u_v_w_m2k_per_ms,
        alpha_absorption=alpha_absorption,
        module_efficiency=module_efficiency,
    )
    if thermal_model_id == THERMAL_PVSYST:
        return steady_state
    if thermal_model_id == THERMAL_PVSYST81_TRANSIENT:
        return calculate_pvsyst81_transient_temperature(
            steady_state,
            weather,
            module_unit_mass_kg_m2=module_unit_mass_kg_m2,
        )
    raise ValueError(
        "unsupported thermal_model_id; expected one of: "
        + ", ".join(sorted(SUPPORTED_THERMAL_MODELS))
    )


def solve_pvsyst_module_thermal_coupling(
    poa: PlaneOfArrayResult,
    optical: OpticalResult,
    weather: CanonicalWeather,
    *,
    parameter_set: dict[str, Any],
    module_area_m2: float,
    u_c_w_m2k: float,
    u_v_w_m2k_per_ms: float,
    alpha_absorption: float,
    thermal_model_id: str = THERMAL_PVSYST,
    module_unit_mass_kg_m2: float | None = None,
    initial_module_efficiency_fraction: float = 0.0,
    temperature_tolerance_c: float = 1e-4,
    efficiency_tolerance_fraction: float = 1e-8,
    max_iterations: int = 25,
    relaxation_factor: float = 1.0,
    solver: str = "lambertw",
    thermal_irradiance_basis: str = "incident_pre_iam",
) -> CoupledModuleThermalResult:
    """Iterate thermal and electrical states to a transparent fixed point.

    The initial efficiency is only a numerical starting state. It is iterated away
    until both temperature and external module efficiency satisfy the configured
    convergence tolerances.
    """
    if thermal_model_id not in SUPPORTED_THERMAL_MODELS:
        raise ValueError(
            "unsupported thermal_model_id; expected one of: "
            + ", ".join(sorted(SUPPORTED_THERMAL_MODELS))
        )
    if not poa.frame.index.equals(optical.frame.index):
        raise ValueError("POA and optical intervals must align exactly")
    if not poa.frame.index.equals(weather.series.index):
        raise ValueError("POA and weather intervals must align exactly")
    if (
        not isfinite(float(initial_module_efficiency_fraction))
        or not 0 <= initial_module_efficiency_fraction < 1
    ):
        raise ValueError(
            "initial_module_efficiency_fraction must lie within 0 <= eta < 1"
        )
    if not isfinite(float(temperature_tolerance_c)) or temperature_tolerance_c <= 0:
        raise ValueError("temperature_tolerance_c must be finite and positive")
    if (
        not isfinite(float(efficiency_tolerance_fraction))
        or efficiency_tolerance_fraction <= 0
    ):
        raise ValueError(
            "efficiency_tolerance_fraction must be finite and positive"
        )
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")
    if (
        not isfinite(float(relaxation_factor))
        or not 0 < relaxation_factor <= 1
    ):
        raise ValueError("relaxation_factor must lie within 0 < factor <= 1")

    if thermal_irradiance_basis not in {"incident_pre_iam", "effective"}:
        raise ValueError("unsupported thermal irradiance basis")
    efficiency_column = "module_efficiency_fraction"
    if thermal_irradiance_basis == "effective":
        thermal_frame = poa.frame.copy()
        thermal_frame["poa_global_w_m2"] = optical.frame["effective_irradiance_w_m2"]
        poa = PlaneOfArrayResult(thermal_frame, {**poa.metadata, "thermal_irradiance_basis": "effective"})
        efficiency_column = "module_efficiency_on_effective_irradiance_fraction"

    n = len(poa.frame)
    efficiency_state = np.full(
        n,
        float(initial_module_efficiency_fraction),
        dtype=float,
    )
    incident = optical.frame["effective_irradiance_w_m2" if thermal_irradiance_basis == "effective" else "incident_poa_global_w_m2"].to_numpy(dtype=float)
    efficiency_state[incident <= 0] = 0.0

    previous_temperature: np.ndarray | None = None
    converged = False
    iteration = 0
    max_temperature_delta = float("inf")
    max_efficiency_delta = float("inf")
    thermal: ThermalResult | None = None
    electrical: ModuleElectricalResult | None = None

    for iteration in range(1, max_iterations + 1):
        thermal = _calculate_thermal_state(
            poa,
            weather,
            thermal_model_id=thermal_model_id,
            u_c_w_m2k=u_c_w_m2k,
            u_v_w_m2k_per_ms=u_v_w_m2k_per_ms,
            alpha_absorption=alpha_absorption,
            module_efficiency=efficiency_state,
            module_unit_mass_kg_m2=module_unit_mass_kg_m2,
        )
        electrical = calculate_pvsyst_module_electrical(
            optical,
            thermal,
            parameter_set=parameter_set,
            module_area_m2=module_area_m2,
            solver=solver,
        )

        solved_efficiency = electrical.frame[
            efficiency_column
        ].to_numpy(dtype=float)
        max_efficiency_delta = float(
            np.max(np.abs(solved_efficiency - efficiency_state))
        ) if n else 0.0

        current_temperature = thermal.frame[
            "cell_temperature_c"
        ].to_numpy(dtype=float)
        if previous_temperature is None:
            max_temperature_delta = float("inf")
        else:
            max_temperature_delta = float(
                np.max(np.abs(current_temperature - previous_temperature))
            ) if n else 0.0

        if (
            previous_temperature is not None
            and max_temperature_delta <= temperature_tolerance_c
            and max_efficiency_delta <= efficiency_tolerance_fraction
        ):
            converged = True
            efficiency_state = solved_efficiency
            break

        efficiency_state = (
            float(relaxation_factor) * solved_efficiency
            + (1.0 - float(relaxation_factor)) * efficiency_state
        )
        previous_temperature = current_temperature

    if not converged or thermal is None or electrical is None:
        raise RuntimeError(
            "PVsyst thermal/electrical coupling did not converge within "
            f"{max_iterations} iterations "
            f"(temperature_delta_c={max_temperature_delta}, "
            f"efficiency_delta={max_efficiency_delta})"
        )

    # One final evaluation at the solved efficiency removes dependence on the
    # previous iteration from the returned state and quantifies the fixed-point residual.
    final_thermal = _calculate_thermal_state(
        poa,
        weather,
        thermal_model_id=thermal_model_id,
        u_c_w_m2k=u_c_w_m2k,
        u_v_w_m2k_per_ms=u_v_w_m2k_per_ms,
        alpha_absorption=alpha_absorption,
        module_efficiency=efficiency_state,
        module_unit_mass_kg_m2=module_unit_mass_kg_m2,
    )
    final_electrical = calculate_pvsyst_module_electrical(
        optical,
        final_thermal,
        parameter_set=parameter_set,
        module_area_m2=module_area_m2,
        solver=solver,
    )

    final_efficiency = final_electrical.frame[
        efficiency_column
    ].to_numpy(dtype=float)
    final_temperature = final_thermal.frame[
        "cell_temperature_c"
    ].to_numpy(dtype=float)
    returned_efficiency_residual = float(
        np.max(np.abs(final_efficiency - efficiency_state))
    ) if n else 0.0
    returned_temperature_residual = float(
        np.max(
            np.abs(
                final_temperature
                - thermal.frame["cell_temperature_c"].to_numpy(dtype=float)
            )
        )
    ) if n else 0.0

    if returned_efficiency_residual > efficiency_tolerance_fraction:
        raise RuntimeError(
            "returned coupled state exceeds efficiency fixed-point tolerance"
        )
    if returned_temperature_residual > temperature_tolerance_c:
        raise RuntimeError(
            "returned coupled state exceeds temperature fixed-point tolerance"
        )

    metadata = {
        "schema_name": "CoupledModuleThermalResult",
        "schema_version": "0.1",
        "coupling_method": "fixed_point_iteration",
        "initial_efficiency_policy": "explicit_numeric_start_only",
        "initial_module_efficiency_fraction": float(
            initial_module_efficiency_fraction
        ),
        "temperature_tolerance_c": float(temperature_tolerance_c),
        "efficiency_tolerance_fraction": float(
            efficiency_tolerance_fraction
        ),
        "max_iterations": int(max_iterations),
        "iterations": int(iteration),
        "relaxation_factor": float(relaxation_factor),
        "converged": True,
        "returned_temperature_residual_c": returned_temperature_residual,
        "returned_efficiency_residual_fraction": returned_efficiency_residual,
        "thermal_model_id": final_thermal.metadata["model_id"],
        "thermal_base_steady_state_model_id": final_thermal.metadata.get(
            "base_steady_state_model_id",
            final_thermal.metadata["model_id"],
        ),
        "thermal_temperature_state": final_thermal.metadata.get(
            "temperature_state"
        ),
        "module_unit_mass_kg_m2": final_thermal.metadata.get(
            "module_unit_mass_kg_m2"
        ),
        "module_unit_mass_source": final_thermal.metadata.get(
            "module_unit_mass_source"
        ),
        "module_model_id": final_electrical.metadata["model_id"],
    }
    if thermal_irradiance_basis == "effective":
        metadata["thermal_irradiance_basis"] = "effective"
        metadata["thermal_efficiency_basis"] = efficiency_column
    return CoupledModuleThermalResult(
        thermal=final_thermal,
        electrical=final_electrical,
        metadata=metadata,
    )
