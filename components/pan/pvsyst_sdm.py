"""PVsyst single-diode parameter completion and model validation.

OpenSIMPV keeps source PAN values separate from derived model parameters. This module:
1. derives I_L_ref and I_o_ref from source-backed STC points plus Rs/Rsh/Gamma/Ns;
2. applies the pvlib PVsyst-v6 auxiliary equations;
3. solves the single-diode equation with pvlib;
4. compares modeled STC points against source reference points;
5. evaluates an off-STC irradiance/temperature matrix for physical consistency,
   monotonic behavior, and source temperature-coefficient consistency.

The goal is auditable model validation, not bit-for-bit replication of PVsyst.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


BOLTZMANN_J_PER_K = 1.380649e-23
ELEMENTARY_CHARGE_C = 1.602176634e-19
CRYSTALLINE_SILICON_EG_REF_EV = 1.121

REQUIRED_PVSYST_PARAMETERS = {
    "r_series_ohm",
    "r_shunt_ref_ohm",
    "r_shunt_0_ohm",
    "r_shunt_exp",
    "gamma_ref",
    "mu_gamma",
    "photocurrent_ref_a",
    "saturation_current_ref_a",
    "alpha_sc_a_per_c",
    "energy_bandgap_ref_ev",
    "cells_in_series",
    "reference_irradiance_w_m2",
    "reference_cell_temperature_c",
}


@dataclass(frozen=True)
class PVSystSDMValidationConfig:
    point_relative_tolerance: float = 0.02
    solver: str = "lambertw"


@dataclass(frozen=True)
class PVSystOffSTCValidationConfig:
    irradiance_levels_w_m2: tuple[float, ...] = (200.0, 600.0, 1000.0)
    cell_temperatures_c: tuple[float, ...] = (0.0, 25.0, 50.0, 75.0)
    coefficient_delta_c: float = 5.0
    alpha_isc_relative_tolerance: float = 0.02
    beta_voc_relative_tolerance: float = 0.05
    gamma_pmp_relative_tolerance: float = 0.15
    power_identity_relative_tolerance: float = 1e-8
    monotonic_epsilon: float = 1e-9
    solver: str = "lambertw"


def derive_reference_currents(
    *,
    isc_a: float,
    voc_v: float,
    r_series_ohm: float,
    r_shunt_ref_ohm: float,
    gamma_ref: float,
    cells_in_series: int,
    reference_cell_temperature_c: float,
) -> dict[str, float]:
    """Derive PVsyst SDM I_L_ref and I_o_ref from Isc and Voc equations."""
    if min(isc_a, voc_v, r_series_ohm, r_shunt_ref_ohm, gamma_ref, cells_in_series) <= 0:
        raise ValueError("reference-current derivation requires positive electrical inputs")

    temp_k = reference_cell_temperature_c + 273.15
    if temp_k <= 0:
        raise ValueError("reference temperature must be above absolute zero")

    n_ns_vth = (
        gamma_ref
        * BOLTZMANN_J_PER_K
        / ELEMENTARY_CHARGE_C
        * cells_in_series
        * temp_k
    )
    exp_voc = math.exp(voc_v / n_ns_vth)
    exp_isc_rs = math.exp(isc_a * r_series_ohm / n_ns_vth)

    numerator = isc_a - (voc_v - isc_a * r_series_ohm) / r_shunt_ref_ohm
    denominator = exp_voc - exp_isc_rs
    if denominator <= 0:
        raise ValueError("invalid reference points: saturation-current denominator is nonpositive")

    saturation_current_ref_a = numerator / denominator
    photocurrent_ref_a = (
        saturation_current_ref_a * math.expm1(voc_v / n_ns_vth)
        + voc_v / r_shunt_ref_ohm
    )
    if saturation_current_ref_a <= 0 or photocurrent_ref_a <= 0:
        raise ValueError("derived PVsyst reference currents must be positive")

    return {
        "photocurrent_ref_a": photocurrent_ref_a,
        "saturation_current_ref_a": saturation_current_ref_a,
        "n_ns_vth_ref_v": n_ns_vth,
    }


def complete_parameter_set(
    module_data: dict[str, Any],
    source_parameters: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Complete the source-backed PVsyst parameter set without guessing unknown technology."""
    params = dict(source_parameters)
    derivations: list[dict[str, Any]] = []
    warnings: list[str] = []

    stc = module_data.get("stc") or {}
    cell = module_data.get("cell_architecture") or {}
    temp = module_data.get("temperature_coefficients") or {}

    if temp.get("alpha_isc_per_c") is not None:
        params["alpha_sc_a_per_c"] = temp["alpha_isc_per_c"]
    if cell.get("cells_in_series") is not None:
        params["cells_in_series"] = cell["cells_in_series"]
    if stc.get("reference_irradiance_w_m2") is not None:
        params["reference_irradiance_w_m2"] = stc["reference_irradiance_w_m2"]
    if stc.get("reference_cell_temperature_c") is not None:
        params["reference_cell_temperature_c"] = stc["reference_cell_temperature_c"]

    technology = module_data.get("technology")
    if technology in {"crystalline_silicon_mono", "crystalline_silicon_poly"}:
        params["energy_bandgap_ref_ev"] = CRYSTALLINE_SILICON_EG_REF_EV
        derivations.append({
            "target_path": "electrical_models[pvsyst_singlediode].parameter_set.energy_bandgap_ref_ev",
            "method": "pvsyst_crystalline_silicon_default_bandgap",
            "algorithm_version": "0.1",
            "inputs": {"technology": technology},
            "value": CRYSTALLINE_SILICON_EG_REF_EV,
            "unit": "eV",
            "estimated": False,
            "notes": "pvlib calcparams_pvsyst documents EgRef=1.121 eV for crystalline silicon.",
        })
    elif "energy_bandgap_ref_ev" not in params:
        warnings.append(
            "No verified PVsyst EgRef rule exists for this technology; model validation remains incomplete."
        )

    derivation_inputs = {
        "isc_a": stc.get("isc_a"),
        "voc_v": stc.get("voc_v"),
        "r_series_ohm": params.get("r_series_ohm"),
        "r_shunt_ref_ohm": params.get("r_shunt_ref_ohm"),
        "gamma_ref": params.get("gamma_ref"),
        "cells_in_series": params.get("cells_in_series"),
        "reference_cell_temperature_c": params.get("reference_cell_temperature_c"),
    }
    if all(value is not None for value in derivation_inputs.values()):
        try:
            derived = derive_reference_currents(**derivation_inputs)
        except ValueError as exc:
            warnings.append(f"Could not derive PVsyst reference currents: {exc}")
        else:
            params["photocurrent_ref_a"] = derived["photocurrent_ref_a"]
            params["saturation_current_ref_a"] = derived["saturation_current_ref_a"]
            for key, unit in (
                ("photocurrent_ref_a", "A"),
                ("saturation_current_ref_a", "A"),
            ):
                derivations.append({
                    "target_path": f"electrical_models[pvsyst_singlediode].parameter_set.{key}",
                    "method": "derive_from_isc_voc_single_diode_equations",
                    "algorithm_version": "0.1",
                    "inputs": derivation_inputs,
                    "value": derived[key],
                    "unit": unit,
                    "estimated": False,
                    "notes": "Derived analytically from the source-backed Isc/Voc points and source-backed PVsyst parameters.",
                })

    return params, derivations, warnings


def _missing_parameters(parameter_set: dict[str, Any]) -> list[str]:
    return sorted(REQUIRED_PVSYST_PARAMETERS - set(parameter_set))


def calculate_pvsyst_diode_parameters(
    *,
    effective_irradiance_w_m2: Any,
    cell_temperature_c: Any,
    parameter_set: dict[str, Any],
):
    """Return pvlib PVsyst-v6 single-diode parameters for scalar or array inputs.

    Runtime simulation and component validation share this mapping so the validated PAN
    parameter semantics cannot drift from the Phase-3 numerical engine.
    """
    missing = _missing_parameters(parameter_set)
    if missing:
        raise ValueError(
            "incomplete PVsyst single-diode parameter set: " + ", ".join(missing)
        )

    from pvlib.pvsystem import calcparams_pvsyst

    return calcparams_pvsyst(
        effective_irradiance=effective_irradiance_w_m2,
        temp_cell=cell_temperature_c,
        alpha_sc=parameter_set["alpha_sc_a_per_c"],
        gamma_ref=parameter_set["gamma_ref"],
        mu_gamma=parameter_set["mu_gamma"],
        I_L_ref=parameter_set["photocurrent_ref_a"],
        I_o_ref=parameter_set["saturation_current_ref_a"],
        R_sh_ref=parameter_set["r_shunt_ref_ohm"],
        R_sh_0=parameter_set["r_shunt_0_ohm"],
        R_s=parameter_set["r_series_ohm"],
        cells_in_series=parameter_set["cells_in_series"],
        R_sh_exp=parameter_set["r_shunt_exp"],
        EgRef=parameter_set["energy_bandgap_ref_ev"],
        irrad_ref=parameter_set["reference_irradiance_w_m2"],
        temp_ref=parameter_set["reference_cell_temperature_c"],
    )


def _simulate_point(
    *,
    effective_irradiance_w_m2: float,
    cell_temperature_c: float,
    parameter_set: dict[str, Any],
    solver: str,
) -> tuple[dict[str, float], str]:
    import pvlib
    from pvlib.pvsystem import singlediode

    diode_params = calculate_pvsyst_diode_parameters(
        effective_irradiance_w_m2=effective_irradiance_w_m2,
        cell_temperature_c=cell_temperature_c,
        parameter_set=parameter_set,
    )
    solved = singlediode(*diode_params, method=solver)
    modeled = {
        "isc_a": float(solved["i_sc"]),
        "voc_v": float(solved["v_oc"]),
        "imp_a": float(solved["i_mp"]),
        "vmp_v": float(solved["v_mp"]),
        "pmp_w": float(solved["p_mp"]),
    }
    return modeled, getattr(pvlib, "__version__", "unknown")


def validate_at_stc(
    module_data: dict[str, Any],
    parameter_set: dict[str, Any],
    *,
    config: PVSystSDMValidationConfig | None = None,
) -> dict[str, Any]:
    """Validate a completed PVsyst SDM parameter set against source STC points using pvlib."""
    config = config or PVSystSDMValidationConfig()
    missing = _missing_parameters(parameter_set)
    if missing:
        return {
            "status": "incomplete",
            "passed": False,
            "missing_parameters": missing,
            "implementation": "pvlib-python",
            "implementation_version": None,
            "solver": config.solver,
            "point_relative_tolerance": config.point_relative_tolerance,
            "reference": {},
            "modeled": {},
            "residuals": {},
        }

    stc = module_data["stc"]
    try:
        modeled, version = _simulate_point(
            effective_irradiance_w_m2=stc["reference_irradiance_w_m2"],
            cell_temperature_c=stc["reference_cell_temperature_c"],
            parameter_set=parameter_set,
            solver=config.solver,
        )
    except ImportError as exc:
        return {
            "status": "unavailable",
            "passed": False,
            "missing_parameters": [],
            "implementation": "pvlib-python",
            "implementation_version": None,
            "solver": config.solver,
            "point_relative_tolerance": config.point_relative_tolerance,
            "reference": {},
            "modeled": {},
            "residuals": {},
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "passed": False,
            "missing_parameters": [],
            "implementation": "pvlib-python",
            "implementation_version": None,
            "solver": config.solver,
            "point_relative_tolerance": config.point_relative_tolerance,
            "reference": {},
            "modeled": {},
            "residuals": {},
            "error": f"{type(exc).__name__}: {exc}",
        }

    reference = {
        "isc_a": float(stc["isc_a"]),
        "voc_v": float(stc["voc_v"]),
        "imp_a": float(stc["imp_a"]),
        "vmp_v": float(stc["vmp_v"]),
        "pmp_w": float(stc["pmp_w"]),
    }

    residuals: dict[str, dict[str, float | bool]] = {}
    passed = True
    for key, expected in reference.items():
        actual = modeled[key]
        absolute = actual - expected
        relative = absolute / expected
        within = abs(relative) <= config.point_relative_tolerance
        residuals[key] = {
            "absolute": absolute,
            "relative": relative,
            "absolute_relative": abs(relative),
            "within_tolerance": within,
        }
        passed = passed and within

    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "missing_parameters": [],
        "implementation": "pvlib-python",
        "implementation_version": version,
        "solver": config.solver,
        "point_relative_tolerance": config.point_relative_tolerance,
        "reference": reference,
        "modeled": modeled,
        "residuals": residuals,
    }


def _relative_check(
    *,
    source_value: float | None,
    modeled_value: float,
    tolerance: float,
    quantity: str,
    unit: str,
) -> dict[str, Any]:
    if source_value is None:
        return {
            "quantity": quantity,
            "unit": unit,
            "evaluated": False,
            "passed": False,
            "reason": "source coefficient missing",
            "source_value": None,
            "modeled_value": modeled_value,
            "relative_error": None,
            "tolerance": tolerance,
        }
    source = float(source_value)
    if abs(source) < 1e-12:
        return {
            "quantity": quantity,
            "unit": unit,
            "evaluated": False,
            "passed": True,
            "reason": "source coefficient is effectively zero; relative comparison omitted",
            "source_value": source,
            "modeled_value": modeled_value,
            "relative_error": None,
            "tolerance": tolerance,
        }
    relative_error = abs((modeled_value - source) / source)
    return {
        "quantity": quantity,
        "unit": unit,
        "evaluated": True,
        "passed": relative_error <= tolerance,
        "reason": None,
        "source_value": source,
        "modeled_value": modeled_value,
        "relative_error": relative_error,
        "tolerance": tolerance,
    }


def _monotonic(values: list[float], direction: str, epsilon: float) -> bool:
    pairs = zip(values, values[1:])
    if direction == "increasing":
        return all(right > left + epsilon for left, right in pairs)
    if direction == "decreasing":
        return all(right < left - epsilon for left, right in pairs)
    raise ValueError(f"unsupported monotonic direction: {direction}")


def validate_off_stc_matrix(
    module_data: dict[str, Any],
    parameter_set: dict[str, Any],
    *,
    config: PVSystOffSTCValidationConfig | None = None,
) -> dict[str, Any]:
    """Validate PVsyst SDM behavior over an irradiance/temperature matrix.

    This is not a comparison to hidden PVsyst desktop outputs. The matrix combines:
    - numerical/physical point checks;
    - monotonic behavior checks;
    - source-anchored temperature-slope checks at reference irradiance.
    """
    config = config or PVSystOffSTCValidationConfig()
    missing = _missing_parameters(parameter_set)
    coefficients = module_data.get("temperature_coefficients") or {}
    missing_coefficients = [
        key
        for key in ("alpha_isc_per_c", "beta_voc_per_c", "gamma_pmp_per_c")
        if coefficients.get(key) is None
    ]

    if missing or missing_coefficients:
        return {
            "status": "incomplete",
            "passed": False,
            "missing_parameters": missing,
            "missing_source_coefficients": missing_coefficients,
            "implementation": "pvlib-python",
            "implementation_version": None,
            "solver": config.solver,
            "grid": {
                "irradiance_levels_w_m2": list(config.irradiance_levels_w_m2),
                "cell_temperatures_c": list(config.cell_temperatures_c),
            },
            "points": [],
            "trend_checks": [],
            "coefficient_checks": {},
        }

    if not config.irradiance_levels_w_m2 or not config.cell_temperatures_c:
        raise ValueError("off-STC validation grid must not be empty")
    if any(g <= 0 for g in config.irradiance_levels_w_m2):
        raise ValueError("off-STC validation irradiances must be greater than zero")
    if config.coefficient_delta_c <= 0:
        raise ValueError("coefficient_delta_c must be greater than zero")

    points: list[dict[str, Any]] = []
    by_point: dict[tuple[float, float], dict[str, float]] = {}
    version: str | None = None

    try:
        for irradiance in config.irradiance_levels_w_m2:
            for temperature in config.cell_temperatures_c:
                modeled, version = _simulate_point(
                    effective_irradiance_w_m2=float(irradiance),
                    cell_temperature_c=float(temperature),
                    parameter_set=parameter_set,
                    solver=config.solver,
                )
                by_point[(float(irradiance), float(temperature))] = modeled

                finite = all(math.isfinite(value) for value in modeled.values())
                positive = all(value > 0 for value in modeled.values())
                voc_gt_vmp = modeled["voc_v"] > modeled["vmp_v"]
                isc_gte_imp = modeled["isc_a"] >= modeled["imp_a"]
                product = modeled["vmp_v"] * modeled["imp_a"]
                power_relative_error = abs(modeled["pmp_w"] - product) / max(
                    abs(modeled["pmp_w"]), abs(product), 1e-12
                )
                power_identity = (
                    power_relative_error <= config.power_identity_relative_tolerance
                )
                point_passed = (
                    finite
                    and positive
                    and voc_gt_vmp
                    and isc_gte_imp
                    and power_identity
                )
                points.append({
                    "effective_irradiance_w_m2": float(irradiance),
                    "cell_temperature_c": float(temperature),
                    "modeled": modeled,
                    "checks": {
                        "finite": finite,
                        "positive": positive,
                        "voc_gt_vmp": voc_gt_vmp,
                        "isc_gte_imp": isc_gte_imp,
                        "pmp_equals_vmp_times_imp": power_identity,
                        "power_identity_relative_error": power_relative_error,
                    },
                    "passed": point_passed,
                })

        gref = float(parameter_set["reference_irradiance_w_m2"])
        tref = float(parameter_set["reference_cell_temperature_c"])
        delta = float(config.coefficient_delta_c)
        low, version = _simulate_point(
            effective_irradiance_w_m2=gref,
            cell_temperature_c=tref - delta,
            parameter_set=parameter_set,
            solver=config.solver,
        )
        high, version = _simulate_point(
            effective_irradiance_w_m2=gref,
            cell_temperature_c=tref + delta,
            parameter_set=parameter_set,
            solver=config.solver,
        )
    except ImportError as exc:
        return {
            "status": "unavailable",
            "passed": False,
            "missing_parameters": [],
            "missing_source_coefficients": [],
            "implementation": "pvlib-python",
            "implementation_version": None,
            "solver": config.solver,
            "grid": {
                "irradiance_levels_w_m2": list(config.irradiance_levels_w_m2),
                "cell_temperatures_c": list(config.cell_temperatures_c),
            },
            "points": [],
            "trend_checks": [],
            "coefficient_checks": {},
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "passed": False,
            "missing_parameters": [],
            "missing_source_coefficients": [],
            "implementation": "pvlib-python",
            "implementation_version": version,
            "solver": config.solver,
            "grid": {
                "irradiance_levels_w_m2": list(config.irradiance_levels_w_m2),
                "cell_temperatures_c": list(config.cell_temperatures_c),
            },
            "points": points,
            "trend_checks": [],
            "coefficient_checks": {},
            "error": f"{type(exc).__name__}: {exc}",
        }

    trend_checks: list[dict[str, Any]] = []
    irradiances = sorted(float(value) for value in config.irradiance_levels_w_m2)
    temperatures = sorted(float(value) for value in config.cell_temperatures_c)

    for temperature in temperatures:
        for quantity in ("isc_a", "voc_v", "pmp_w"):
            values = [by_point[(irradiance, temperature)][quantity] for irradiance in irradiances]
            passed = _monotonic(values, "increasing", config.monotonic_epsilon)
            trend_checks.append({
                "axis": "irradiance",
                "fixed_cell_temperature_c": temperature,
                "quantity": quantity,
                "direction": "increasing",
                "coordinates": irradiances,
                "values": values,
                "passed": passed,
            })

    temperature_coefficients_by_quantity = {
        "isc_a": float(coefficients["alpha_isc_per_c"]),
        "voc_v": float(coefficients["beta_voc_per_c"]),
        "pmp_w": float(coefficients["gamma_pmp_per_c"]),
    }
    for irradiance in irradiances:
        for quantity, coefficient in temperature_coefficients_by_quantity.items():
            if abs(coefficient) < 1e-12:
                continue
            direction = "increasing" if coefficient > 0 else "decreasing"
            values = [by_point[(irradiance, temperature)][quantity] for temperature in temperatures]
            passed = _monotonic(values, direction, config.monotonic_epsilon)
            trend_checks.append({
                "axis": "temperature",
                "fixed_effective_irradiance_w_m2": irradiance,
                "quantity": quantity,
                "direction": direction,
                "coordinates": temperatures,
                "values": values,
                "passed": passed,
            })

    modeled_slopes = {
        "alpha_isc_per_c": (high["isc_a"] - low["isc_a"]) / (2.0 * delta),
        "beta_voc_per_c": (high["voc_v"] - low["voc_v"]) / (2.0 * delta),
        "gamma_pmp_per_c": (high["pmp_w"] - low["pmp_w"]) / (2.0 * delta),
    }
    coefficient_checks = {
        "alpha_isc_per_c": _relative_check(
            source_value=coefficients["alpha_isc_per_c"],
            modeled_value=modeled_slopes["alpha_isc_per_c"],
            tolerance=config.alpha_isc_relative_tolerance,
            quantity="alpha_isc_per_c",
            unit="A/K",
        ),
        "beta_voc_per_c": _relative_check(
            source_value=coefficients["beta_voc_per_c"],
            modeled_value=modeled_slopes["beta_voc_per_c"],
            tolerance=config.beta_voc_relative_tolerance,
            quantity="beta_voc_per_c",
            unit="V/K",
        ),
        "gamma_pmp_per_c": _relative_check(
            source_value=coefficients["gamma_pmp_per_c"],
            modeled_value=modeled_slopes["gamma_pmp_per_c"],
            tolerance=config.gamma_pmp_relative_tolerance,
            quantity="gamma_pmp_per_c",
            unit="W/K",
        ),
    }

    point_passed = all(point["passed"] for point in points)
    trends_passed = all(check["passed"] for check in trend_checks)
    coefficients_passed = all(check["passed"] for check in coefficient_checks.values())
    passed = point_passed and trends_passed and coefficients_passed

    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "missing_parameters": [],
        "missing_source_coefficients": [],
        "implementation": "pvlib-python",
        "implementation_version": version,
        "solver": config.solver,
        "grid": {
            "irradiance_levels_w_m2": irradiances,
            "cell_temperatures_c": temperatures,
            "point_count": len(points),
        },
        "point_check_summary": {
            "passed": point_passed,
            "passed_count": sum(1 for point in points if point["passed"]),
            "total_count": len(points),
        },
        "trend_check_summary": {
            "passed": trends_passed,
            "passed_count": sum(1 for check in trend_checks if check["passed"]),
            "total_count": len(trend_checks),
        },
        "coefficient_check_summary": {
            "passed": coefficients_passed,
            "passed_count": sum(1 for check in coefficient_checks.values() if check["passed"]),
            "total_count": len(coefficient_checks),
            "finite_difference_delta_c": delta,
        },
        "points": points,
        "trend_checks": trend_checks,
        "coefficient_checks": coefficient_checks,
    }
