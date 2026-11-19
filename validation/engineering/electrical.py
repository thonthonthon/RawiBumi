"""Phase-4.7 deterministic PV engineering validation.

The validator is read-only. It evaluates canonical Scene + ElectricalDesign +
exact component revisions under explicit design conditions and produces the
Phase-4 DesignValidationReport contract.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import ceil, isfinite
from typing import Any, Mapping, Sequence

import numpy as np
import pvlib

from components.design_integration import inverter_design_snapshot, module_nameplate_w
from components.pan.pvsyst_sdm import calculate_pvsyst_diode_parameters
from engine.module import extract_validated_pvsyst_parameter_set


ENGINEERING_RULE_SET_ID = "rawibumi.engineering_validation.v0.2"
LEGACY_ENGINEERING_RULE_SET_IDS = {"opensimpv.engineering_validation.v0.2"}

_CLASSIFICATION_TO_SEVERITY = {
    "INFO": "info",
    "RECOMMENDATION": "recommendation",
    "WARNING": "warning",
    "INVALID": "blocking_error",
}
_CLASSIFICATION_ORDER = {
    "INVALID": 0,
    "WARNING": 1,
    "RECOMMENDATION": 2,
    "INFO": 3,
}


@dataclass(frozen=True)
class ModuleDesignState:
    revision_id: str
    model_basis: str
    downgraded: bool
    voc_min_temp_v: float
    voc_max_temp_v: float
    vmp_min_temp_v: float
    vmp_max_temp_v: float
    imp_min_temp_a: float
    imp_max_temp_a: float
    isc_min_temp_a: float
    isc_max_temp_a: float
    stc_power_w: float
    max_system_voltage_v: float | None
    evidence_grade: str
    voltage_uncertainty_fraction: float
    current_uncertainty_fraction: float


def _config(value: Mapping[str, Any]) -> dict[str, Any]:
    cfg = deepcopy(dict(value))
    if cfg.get("schema_name") != "EngineeringValidationConfiguration":
        raise ValueError(
            "validation configuration must use EngineeringValidationConfiguration"
        )
    if cfg.get("schema_version") != "0.1":
        raise ValueError("unsupported validation configuration version")

    t_min = float(cfg["minimum_cell_temperature_c"])
    t_max = float(cfg["maximum_cell_temperature_c"])
    irradiance = float(cfg["design_irradiance_w_m2"])
    if not all(isfinite(x) for x in (t_min, t_max, irradiance)):
        raise ValueError("validation design conditions must be finite")
    if t_min >= t_max:
        raise ValueError(
            "minimum_cell_temperature_c must be below maximum_cell_temperature_c"
        )
    if irradiance <= 0.0:
        raise ValueError("design_irradiance_w_m2 must be positive")

    cfg.setdefault("orientation_tolerance_deg", 0.1)
    cfg.setdefault(
        "temperature_model_policy", "detailed_then_linear_fallback"
    )
    cfg.setdefault("fallback_voltage_uncertainty_fraction", 0.05)
    cfg.setdefault("fallback_current_uncertainty_fraction", 0.05)
    for key in (
        "fallback_voltage_uncertainty_fraction",
        "fallback_current_uncertainty_fraction",
    ):
        value = float(cfg[key])
        if not isfinite(value) or value < 0.0 or value >= 1.0:
            raise ValueError(
                f"{key} must be finite and satisfy 0 <= value < 1"
            )
        cfg[key] = value
    tol = float(cfg["orientation_tolerance_deg"])
    if not isfinite(tol) or tol < 0.0:
        raise ValueError("orientation_tolerance_deg must be finite and non-negative")
    # Read, not defaulted into the config: reports keep echoing exactly what the caller passed.
    if cfg.get("orientation_comparison", "tilt_azimuth") not in {"tilt_azimuth", "normal_angle"}:
        raise ValueError("orientation_comparison must be tilt_azimuth or normal_angle")

    ratio_min = cfg.get("dc_ac_ratio_warning_min")
    ratio_max = cfg.get("dc_ac_ratio_warning_max")
    if ratio_min is not None:
        ratio_min = float(ratio_min)
        if not isfinite(ratio_min) or ratio_min <= 0:
            raise ValueError("dc_ac_ratio_warning_min must be positive")
        cfg["dc_ac_ratio_warning_min"] = ratio_min
    if ratio_max is not None:
        ratio_max = float(ratio_max)
        if not isfinite(ratio_max) or ratio_max <= 0:
            raise ValueError("dc_ac_ratio_warning_max must be positive")
        cfg["dc_ac_ratio_warning_max"] = ratio_max
    if (
        ratio_min is not None
        and ratio_max is not None
        and ratio_min > ratio_max
    ):
        raise ValueError(
            "dc_ac_ratio_warning_min cannot exceed dc_ac_ratio_warning_max"
        )
    return cfg


def _linear_value(
    reference: float,
    coefficient: float,
    basis: str,
    delta_c: float,
) -> float:
    if basis == "absolute":
        return reference + coefficient * delta_c
    if basis == "relative":
        return reference * (1.0 + coefficient * delta_c)
    raise ValueError(
        "temperature coefficient basis must be absolute or relative"
    )


def _relative_coefficient(
    coefficient: float,
    *,
    reference: float,
    basis: str,
) -> float:
    if basis == "relative":
        return coefficient
    if basis == "absolute":
        if reference <= 0.0:
            raise ValueError("reference must be positive")
        return coefficient / reference
    raise ValueError(
        "temperature coefficient basis must be absolute or relative"
    )


def _detailed_module_state(
    module: Mapping[str, Any],
    *,
    minimum_cell_temperature_c: float,
    maximum_cell_temperature_c: float,
    design_irradiance_w_m2: float,
) -> ModuleDesignState:
    capabilities = module.get("capability_flags") or {}
    if capabilities.get("detailed_sdm_ready") is not True:
        raise ValueError(
            "validated detailed PVsyst model requires "
            "capability_flags.detailed_sdm_ready=true"
        )
    params = extract_validated_pvsyst_parameter_set(dict(module))
    temperatures = np.asarray(
        [minimum_cell_temperature_c, maximum_cell_temperature_c],
        dtype=float,
    )
    irradiance = np.asarray(
        [design_irradiance_w_m2, design_irradiance_w_m2],
        dtype=float,
    )
    diode = calculate_pvsyst_diode_parameters(
        effective_irradiance_w_m2=irradiance,
        cell_temperature_c=temperatures,
        parameter_set=params,
    )
    solved = pvlib.pvsystem.singlediode(*diode, method="lambertw")

    def pair(name: str) -> tuple[float, float]:
        values = np.asarray(solved[name], dtype=float)
        if values.shape != (2,) or not np.isfinite(values).all():
            raise ValueError(
                f"detailed module model produced invalid {name}"
            )
        if (values < 0).any():
            raise ValueError(
                f"detailed module model produced negative {name}"
            )
        return float(values[0]), float(values[1])

    voc_min, voc_max = pair("v_oc")
    vmp_min, vmp_max = pair("v_mp")
    imp_min, imp_max = pair("i_mp")
    isc_min, isc_max = pair("i_sc")
    stc = module.get("stc") or {}
    limits = module.get("limits") or {}
    model_basis = "validated_pvsyst_singlediode"
    model = next(
        entry for entry in module.get("electrical_models") or []
        if entry.get("model_type") == "pvsyst_singlediode"
    )
    if "beta_voc_per_c" in (model.get("readiness_tolerances") or []):
        coeff = module.get("temperature_coefficients") or {}
        basis = coeff.get("coefficient_basis")
        gref = stc.get("reference_irradiance_w_m2")
        if basis not in {"absolute", "relative"} or gref is None or not isfinite(float(gref)) or float(gref) <= 0:
            raise ValueError("datasheet Voc envelope requires coefficient basis and positive reference irradiance")
        tref = float(stc["reference_cell_temperature_c"])
        cold_linear = _linear_value(
            float(stc["voc_v"]), float(coeff["beta_voc_per_c"]),
            str(basis), minimum_cell_temperature_c - tref,
        )
        alpha_rel = _relative_coefficient(float(coeff["alpha_isc_per_c"]), reference=float(stc["isc_a"]), basis=str(basis))
        gamma_rel = _relative_coefficient(float(coeff["gamma_pmp_per_c"]), reference=float(stc["pmp_w"]), basis=str(basis))
        hot_linear = _linear_value(
            float(stc["vmp_v"]), gamma_rel - alpha_rel, "relative",
            maximum_cell_temperature_c - tref,
        )
        if not all(isfinite(value) and value > 0 for value in (cold_linear, hot_linear)):
            raise ValueError("datasheet Voc envelope produced non-positive or non-finite voltage")
        voc_min = max(voc_min, cold_linear)
        vmp_max = min(vmp_max, hot_linear)
        model_basis += "+datasheet_voc_envelope"
    return ModuleDesignState(
        revision_id=str(module["revision_id"]),
        model_basis=model_basis,
        downgraded=False,
        voc_min_temp_v=voc_min,
        voc_max_temp_v=voc_max,
        vmp_min_temp_v=vmp_min,
        vmp_max_temp_v=vmp_max,
        imp_min_temp_a=imp_min,
        imp_max_temp_a=imp_max,
        isc_min_temp_a=isc_min,
        isc_max_temp_a=isc_max,
        # D14: the DC nameplate (datasheet nominal, else STC Pmp), as the engine's installed capacity.
        stc_power_w=module_nameplate_w(module),
        max_system_voltage_v=min(
            (
                float(limits[key])
                for key in (
                    "max_system_voltage_v",
                    "max_system_voltage_iec_v",
                    "max_system_voltage_ul_v",
                )
                if limits.get(key) is not None
            ),
            default=None,
        ),
        evidence_grade="validated_detailed_model",
        voltage_uncertainty_fraction=0.0,
        current_uncertainty_fraction=0.0,
    )


def _fallback_module_state(
    module: Mapping[str, Any],
    *,
    minimum_cell_temperature_c: float,
    maximum_cell_temperature_c: float,
    design_irradiance_w_m2: float,
    voltage_uncertainty_fraction: float = 0.05,
    current_uncertainty_fraction: float = 0.05,
) -> ModuleDesignState:
    stc = module.get("stc") or {}
    coeff = module.get("temperature_coefficients") or {}
    limits = module.get("limits") or {}
    basis = coeff.get("coefficient_basis")
    if basis not in {"absolute", "relative"}:
        raise ValueError(
            "linear fallback requires coefficient_basis=absolute or relative"
        )
    for key in ("alpha_isc_per_c", "beta_voc_per_c", "gamma_pmp_per_c"):
        if coeff.get(key) is None:
            raise ValueError(
                f"linear fallback requires temperature coefficient {key}"
            )

    pmp = float(stc["pmp_w"])
    voc = float(stc["voc_v"])
    isc = float(stc["isc_a"])
    vmp = float(stc["vmp_v"])
    imp = float(stc["imp_a"])
    tref = float(stc["reference_cell_temperature_c"])
    gref = float(stc["reference_irradiance_w_m2"])
    scale = design_irradiance_w_m2 / gref
    if abs(scale - 1.0) > 1e-9:
        raise ValueError(
            "linear temperature-coefficient fallback is evidence-bounded to "
            "the module reference irradiance; irradiance-dependent Voc/Vmpp "
            "requires a validated detailed model"
        )

    alpha = float(coeff["alpha_isc_per_c"])
    beta = float(coeff["beta_voc_per_c"])
    gamma = float(coeff["gamma_pmp_per_c"])
    alpha_rel = _relative_coefficient(
        alpha, reference=isc, basis=str(basis)
    )
    gamma_rel = _relative_coefficient(
        gamma, reference=pmp, basis=str(basis)
    )
    # Explicit approximation: d(Vmp)/Vmp ≈ d(Pmp)/Pmp - d(Isc)/Isc.
    beta_vmp_rel = gamma_rel - alpha_rel

    def state(temp_c: float) -> tuple[float, float, float, float]:
        delta = temp_c - tref
        voc_t = _linear_value(voc, beta, str(basis), delta)
        isc_t = isc * (1.0 + alpha_rel * delta) * scale
        imp_t = imp * (1.0 + alpha_rel * delta) * scale
        vmp_t = vmp * (1.0 + beta_vmp_rel * delta)
        values = (voc_t, vmp_t, imp_t, isc_t)
        if not all(isfinite(value) and value > 0.0 for value in values):
            raise ValueError(
                "linear coefficient fallback produced non-positive design state"
            )
        return values

    cold = state(minimum_cell_temperature_c)
    hot = state(maximum_cell_temperature_c)
    return ModuleDesignState(
        revision_id=str(module["revision_id"]),
        model_basis=(
            "linear_temperature_coefficients:"
            "beta_vmp_relative_approx_gamma_pmp_minus_alpha_isc"
        ),
        downgraded=True,
        voc_min_temp_v=cold[0],
        voc_max_temp_v=hot[0],
        vmp_min_temp_v=cold[1],
        vmp_max_temp_v=hot[1],
        imp_min_temp_a=cold[2],
        imp_max_temp_a=hot[2],
        isc_min_temp_a=cold[3],
        isc_max_temp_a=hot[3],
        stc_power_w=module_nameplate_w(module),
        max_system_voltage_v=min(
            (
                float(limits[key])
                for key in (
                    "max_system_voltage_v",
                    "max_system_voltage_iec_v",
                    "max_system_voltage_ul_v",
                )
                if limits.get(key) is not None
            ),
            default=None,
        ),
        evidence_grade="linear_fallback_guarded",
        voltage_uncertainty_fraction=float(voltage_uncertainty_fraction),
        current_uncertainty_fraction=float(current_uncertainty_fraction),
    )


def _module_state(
    module: Mapping[str, Any],
    cfg: Mapping[str, Any],
) -> ModuleDesignState:
    detailed_error: Exception | None = None
    try:
        return _detailed_module_state(
            module,
            minimum_cell_temperature_c=float(
                cfg["minimum_cell_temperature_c"]
            ),
            maximum_cell_temperature_c=float(
                cfg["maximum_cell_temperature_c"]
            ),
            design_irradiance_w_m2=float(
                cfg["design_irradiance_w_m2"]
            ),
        )
    except Exception as exc:
        detailed_error = exc

    if cfg["temperature_model_policy"] == "detailed_required":
        raise ValueError(
            f"validated detailed module model required: {detailed_error}"
        ) from detailed_error

    try:
        return _fallback_module_state(
            module,
            minimum_cell_temperature_c=float(
                cfg["minimum_cell_temperature_c"]
            ),
            maximum_cell_temperature_c=float(
                cfg["maximum_cell_temperature_c"]
            ),
            design_irradiance_w_m2=float(
                cfg["design_irradiance_w_m2"]
            ),
            voltage_uncertainty_fraction=float(
                cfg["fallback_voltage_uncertainty_fraction"]
            ),
            current_uncertainty_fraction=float(
                cfg["fallback_current_uncertainty_fraction"]
            ),
        )
    except Exception as fallback_error:
        raise ValueError(
            "no executable temperature-dependent module model; "
            f"detailed={detailed_error}; fallback={fallback_error}"
        ) from fallback_error


def module_design_state(module: Mapping[str, Any], configuration: Mapping[str, Any]) -> ModuleDesignState:
    """The temperature-dependent module state the validation uses, for callers that size strings (USE1 suggestion)."""
    return _module_state(module, _config(configuration))


def _symmetric_envelope(
    value: float,
    uncertainty_fraction: float,
) -> tuple[float, float]:
    nominal = float(value)
    uncertainty = float(uncertainty_fraction)
    return nominal * (1.0 - uncertainty), nominal * (1.0 + uncertainty)


def _string_voltage_envelope(
    string_modules: Sequence[tuple[Mapping[str, Any], ModuleDesignState]],
    attribute: str,
) -> tuple[float, float, float]:
    nominal = sum(float(getattr(state, attribute)) for _, state in string_modules)
    lower = sum(
        _symmetric_envelope(
            float(getattr(state, attribute)),
            state.voltage_uncertainty_fraction,
        )[0]
        for _, state in string_modules
    )
    upper = sum(
        _symmetric_envelope(
            float(getattr(state, attribute)),
            state.voltage_uncertainty_fraction,
        )[1]
        for _, state in string_modules
    )
    return nominal, lower, upper


def _string_current_envelope(
    string_modules: Sequence[tuple[Mapping[str, Any], ModuleDesignState]],
    attribute: str,
) -> tuple[float, float, float]:
    nominal = min(float(getattr(state, attribute)) for _, state in string_modules)
    lower = min(
        _symmetric_envelope(
            float(getattr(state, attribute)),
            state.current_uncertainty_fraction,
        )[0]
        for _, state in string_modules
    )
    upper = min(
        _symmetric_envelope(
            float(getattr(state, attribute)),
            state.current_uncertainty_fraction,
        )[1]
        for _, state in string_modules
    )
    return nominal, lower, upper


def compare_temperature_model_paths(
    module: Mapping[str, Any],
    *,
    minimum_cell_temperature_c: float,
    maximum_cell_temperature_c: float,
    design_irradiance_w_m2: float,
) -> dict[str, Any]:
    """Compare validated detailed PVsyst output with the documented linear path.

    This function is evidence tooling. It does not select the runtime validation
    model and does not mutate the component.
    """
    detailed = _detailed_module_state(
        module,
        minimum_cell_temperature_c=minimum_cell_temperature_c,
        maximum_cell_temperature_c=maximum_cell_temperature_c,
        design_irradiance_w_m2=design_irradiance_w_m2,
    )
    fallback = _fallback_module_state(
        module,
        minimum_cell_temperature_c=minimum_cell_temperature_c,
        maximum_cell_temperature_c=maximum_cell_temperature_c,
        design_irradiance_w_m2=design_irradiance_w_m2,
        voltage_uncertainty_fraction=0.0,
        current_uncertainty_fraction=0.0,
    )
    attributes = (
        "voc_min_temp_v",
        "voc_max_temp_v",
        "vmp_min_temp_v",
        "vmp_max_temp_v",
        "imp_min_temp_a",
        "imp_max_temp_a",
        "isc_min_temp_a",
        "isc_max_temp_a",
    )
    errors: dict[str, float] = {}
    for attribute in attributes:
        reference = float(getattr(detailed, attribute))
        approximate = float(getattr(fallback, attribute))
        errors[attribute] = abs(approximate - reference) / max(
            abs(reference), 1e-12
        )
    voltage_errors = [
        errors[key] for key in errors if key.startswith(("voc_", "vmp_"))
    ]
    current_errors = [
        errors[key] for key in errors if key.startswith(("imp_", "isc_"))
    ]
    return {
        "schema_name": "TemperatureModelEvidence",
        "schema_version": "0.1",
        "module_revision_id": str(module["revision_id"]),
        "minimum_cell_temperature_c": float(minimum_cell_temperature_c),
        "maximum_cell_temperature_c": float(maximum_cell_temperature_c),
        "design_irradiance_w_m2": float(design_irradiance_w_m2),
        "relative_errors": errors,
        "maximum_voltage_relative_error": max(voltage_errors),
        "maximum_current_relative_error": max(current_errors),
        "detailed_model_basis": detailed.model_basis,
        "fallback_model_basis": fallback.model_basis,
    }


def _azimuth_difference_deg(a: float, b: float) -> float:
    raw = abs((float(a) - float(b)) % 360.0)
    return min(raw, 360.0 - raw)


def _finding(
    *,
    project_revision_id: str,
    entity_id: str,
    rule_id: str,
    classification: str,
    category: str,
    message: str,
    generated_at: str,
    measured_value: Any = None,
    limit_value: Any = None,
    unit: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_name": "ValidationFinding",
        "schema_version": "0.1",
        "finding_id": "",
        "project_revision_id": project_revision_id,
        "entity_id": str(entity_id),
        "rule_id": rule_id,
        "severity": _CLASSIFICATION_TO_SEVERITY[classification],
        "classification": classification,
        "category": category,
        "message": message,
        "measured_value": deepcopy(measured_value),
        "limit_value": deepcopy(limit_value),
        "unit": unit,
        "context": deepcopy(dict(context or {})),
        "generated_at": generated_at,
        "resolved_at": None,
        "resolution_note": None,
    }


def _finalize_findings(
    findings: Sequence[Mapping[str, Any]],
    *,
    report_id: str,
) -> list[dict[str, Any]]:
    ordered = sorted(
        (deepcopy(dict(item)) for item in findings),
        key=lambda item: (
            _CLASSIFICATION_ORDER[str(item["classification"])],
            str(item["rule_id"]),
            str(item["entity_id"]),
            str(item["message"]),
        ),
    )
    for index, item in enumerate(ordered, start=1):
        item["finding_id"] = f"{report_id}:finding:{index:04d}"
    return ordered


def inverter_design_capability_issues(
    snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project-independent issues from the existing inverter capability rules."""
    issues: list[dict[str, Any]] = []
    caps = snapshot.get("capability_flags") or {}
    for flag in ("basic_design_ready", "mppt_design_ready"):
        if caps.get(flag) is False:
            issues.append({
                "rule_id": f"INVERTER_{flag.upper()}_FALSE",
                "classification": "INVALID",
                "category": "component_capability",
                "message": f"Inverter revision explicitly reports {flag}=false.",
            })
    if caps.get("basic_yield_ready") is False:
        issues.append({
            "rule_id": "INVERTER_BASIC_SIMULATION_CAPABILITY_UNAVAILABLE",
            "classification": "WARNING",
            "category": "component_capability",
            "message": "Inverter revision explicitly reports basic_yield_ready=false.",
        })
    for issue in issues:
        issue["severity"] = _CLASSIFICATION_TO_SEVERITY[issue["classification"]]
    return issues


def validate_engineering_design(
    scene: Mapping[str, Any],
    electrical_design: Mapping[str, Any],
    *,
    project_revision_id: str,
    component_revisions: Mapping[str, Mapping[str, Any]],
    configuration: Mapping[str, Any],
    design_validation_report_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """Validate one exact canonical design without mutating it."""
    if not project_revision_id or not design_validation_report_id:
        raise ValueError("project_revision_id and report ID are required")
    cfg = _config(configuration)
    scene_copy = deepcopy(dict(scene))
    electrical = deepcopy(dict(electrical_design))
    components = {
        str(key): deepcopy(dict(value))
        for key, value in component_revisions.items()
    }

    findings: list[dict[str, Any]] = []
    modules = {
        str(item["module_instance_id"]): item
        for item in scene_copy.get("module_instances", [])
    }
    fields = {
        str(item["pv_field_id"]): item
        for item in scene_copy.get("pv_fields", [])
    }
    strings = {
        str(item["string_id"]): item
        for item in electrical.get("strings", [])
    }
    mppts = {
        str(item["mppt_instance_id"]): item
        for item in electrical.get("mppt_instances", [])
    }
    inverters = {
        str(item["inverter_instance_id"]): item
        for item in electrical.get("inverter_instances", [])
    }

    module_states: dict[str, ModuleDesignState | None] = {}
    used_module_revisions = sorted(
        {
            str(module["module_definition_revision_id"])
            for module in modules.values()
            if module.get("enabled") is True
        }
    )
    for revision_id in used_module_revisions:
        definition = components.get(revision_id)
        if definition is None:
            module_states[revision_id] = None
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=revision_id,
                    rule_id="MODULE_COMPONENT_REVISION_NOT_FOUND",
                    classification="INVALID",
                    category="component_capability",
                    message=(
                        "Module component revision required by the Scene "
                        "is not available."
                    ),
                    generated_at=generated_at,
                )
            )
            continue
        try:
            state = _module_state(definition, cfg)
        except Exception as exc:
            module_states[revision_id] = None
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=revision_id,
                    rule_id="MODULE_TEMPERATURE_MODEL_UNAVAILABLE",
                    classification="INVALID",
                    category="component_capability",
                    message=(
                        "Temperature-dependent Voc/Vmpp/current validation "
                        "cannot be executed for this module revision."
                    ),
                    generated_at=generated_at,
                    context={"reason": str(exc)},
                )
            )
        else:
            module_states[revision_id] = state
            if state.downgraded:
                findings.append(
                    _finding(
                        project_revision_id=project_revision_id,
                        entity_id=revision_id,
                        rule_id="MODULE_TEMPERATURE_MODEL_DOWNGRADED",
                        classification="WARNING",
                        category="component_capability",
                        message=(
                            "Detailed PVsyst single-diode validation model "
                            "is unavailable; a documented linear coefficient "
                            "fallback is used for design-temperature checks."
                        ),
                        generated_at=generated_at,
                        context={
                            "model_basis": state.model_basis,
                            "evidence_grade": state.evidence_grade,
                            "voltage_uncertainty_fraction": (
                                state.voltage_uncertainty_fraction
                            ),
                            "current_uncertainty_fraction": (
                                state.current_uncertainty_fraction
                            ),
                            "fallback_reference_irradiance_only": True,
                        },
                    )
                )

        caps = definition.get("capability_flags") or {}
        if caps.get("basic_yield_ready") is False:
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=revision_id,
                    rule_id="MODULE_BASIC_SIMULATION_CAPABILITY_UNAVAILABLE",
                    classification="WARNING",
                    category="component_capability",
                    message=(
                        "Module revision explicitly reports basic_yield_ready=false."
                    ),
                    generated_at=generated_at,
                )
            )

    inverter_snapshots: dict[str, dict[str, Any] | None] = {}
    for inverter_id, inverter in sorted(inverters.items()):
        revision_id = str(inverter["inverter_definition_revision_id"])
        definition = components.get(revision_id)
        if definition is None:
            inverter_snapshots[inverter_id] = None
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=inverter_id,
                    rule_id="INVERTER_COMPONENT_REVISION_NOT_FOUND",
                    classification="INVALID",
                    category="component_capability",
                    message="Bound inverter component revision is not available.",
                    generated_at=generated_at,
                    context={"revision_id": revision_id},
                )
            )
            continue
        snapshot = inverter_design_snapshot(definition)
        inverter_snapshots[inverter_id] = snapshot
        for issue in inverter_design_capability_issues(snapshot):
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=inverter_id,
                    generated_at=generated_at,
                    **{key: value for key, value in issue.items() if key != "severity"},
                )
            )

    # Structural reciprocity required before electrical arithmetic is meaningful.
    for string_id, string in sorted(strings.items()):
        if string.get("enabled") is not True:
            continue
        target_id = string.get("target_mppt_instance_id")
        if target_id is None or str(target_id) not in mppts:
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=string_id,
                    rule_id="ENABLED_STRING_MPPT_NOT_RESOLVED",
                    classification="INVALID",
                    category="electrical_topology",
                    message="Enabled string has no resolvable target MPPT.",
                    generated_at=generated_at,
                )
            )
            continue
        if string_id not in mppts[str(target_id)].get(
            "connected_string_ids", []
        ):
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=string_id,
                    rule_id="STRING_MPPT_ASSIGNMENT_NOT_RECIPROCAL",
                    classification="INVALID",
                    category="electrical_topology",
                    message=(
                        "String target MPPT and MPPT connected-string list "
                        "do not reconcile."
                    ),
                    generated_at=generated_at,
                )
            )

    for mppt_id, mppt in sorted(mppts.items()):
        for string_id in mppt.get("connected_string_ids", []):
            string = strings.get(str(string_id))
            if string is None or string.get(
                "target_mppt_instance_id"
            ) != mppt_id:
                findings.append(
                    _finding(
                        project_revision_id=project_revision_id,
                        entity_id=mppt_id,
                        rule_id="MPPT_STRING_ASSIGNMENT_NOT_RECIPROCAL",
                        classification="INVALID",
                        category="electrical_topology",
                        message=(
                            f"MPPT assignment does not reconcile for string "
                            f"{string_id}."
                        ),
                        generated_at=generated_at,
                    )
                )

    string_states: dict[str, dict[str, Any]] = {}
    module_membership: dict[str, list[str]] = {}
    for string_id, string in sorted(strings.items()):
        if string.get("enabled") is not True:
            continue
        ids = [str(value) for value in string.get("module_instance_ids", [])]
        if not ids:
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=string_id,
                    rule_id="ENABLED_STRING_EMPTY",
                    classification="INVALID",
                    category="electrical_topology",
                    message="Enabled string contains no modules.",
                    generated_at=generated_at,
                )
            )
            continue

        string_modules = []
        unavailable = False
        orientations: list[tuple[float, float]] = []
        for module_id in ids:
            module_membership.setdefault(module_id, []).append(string_id)
            module = modules.get(module_id)
            if module is None or module.get("enabled") is not True:
                unavailable = True
                findings.append(
                    _finding(
                        project_revision_id=project_revision_id,
                        entity_id=string_id,
                        rule_id="STRING_MODULE_NOT_RESOLVED",
                        classification="INVALID",
                        category="electrical_topology",
                        message=(
                            f"String references missing or disabled module "
                            f"{module_id}."
                        ),
                        generated_at=generated_at,
                        context={"module_instance_id": module_id},
                    )
                )
                continue
            revision_id = str(module["module_definition_revision_id"])
            state = module_states.get(revision_id)
            if state is None:
                unavailable = True
                continue
            field = fields.get(str(module["pv_field_id"]))
            if field is None:
                unavailable = True
                findings.append(
                    _finding(
                        project_revision_id=project_revision_id,
                        entity_id=module_id,
                        rule_id="MODULE_PV_FIELD_NOT_RESOLVED",
                        classification="INVALID",
                        category="electrical_topology",
                        message="Module references a missing PV field.",
                        generated_at=generated_at,
                    )
                )
                continue
            if field.get("field_kind") == "explicit_layout":
                from geometry.pvfield.explicit import table_for_module
                try:
                    field = table_for_module(module, field)
                except (ValueError, KeyError, TypeError) as exc:
                    findings.append(_finding(project_revision_id=project_revision_id,
                        entity_id=module_id, rule_id="MODULE_PV_FIELD_NOT_RESOLVED",
                        classification="INVALID", category="component_binding",
                        message=str(exc), generated_at=generated_at))
                    continue
            if str(field["module_definition_revision_id"]) != revision_id:
                findings.append(
                    _finding(
                        project_revision_id=project_revision_id,
                        entity_id=module_id,
                        rule_id="MODULE_FIELD_REVISION_MISMATCH",
                        classification="INVALID",
                        category="component_binding",
                        message=(
                            "Module revision does not match its parent PVField "
                            "component revision."
                        ),
                        generated_at=generated_at,
                    )
                )
            orientations.append(
                (
                    float(field["tilt_deg"]),
                    float(
                        module["transform"].get(
                            "rotation_z_deg", field["azimuth_deg"]
                        )
                    ),
                )
            )
            string_modules.append((module, state))

        if unavailable or not string_modules:
            continue

        voc_min = _string_voltage_envelope(
            string_modules, "voc_min_temp_v"
        )
        vmp_min = _string_voltage_envelope(
            string_modules, "vmp_min_temp_v"
        )
        vmp_max = _string_voltage_envelope(
            string_modules, "vmp_max_temp_v"
        )
        imp_min = _string_current_envelope(
            string_modules, "imp_min_temp_a"
        )
        imp_max = _string_current_envelope(
            string_modules, "imp_max_temp_a"
        )
        isc_min = _string_current_envelope(
            string_modules, "isc_min_temp_a"
        )
        isc_max = _string_current_envelope(
            string_modules, "isc_max_temp_a"
        )
        evidence_grades = sorted(
            {state.evidence_grade for _, state in string_modules}
        )
        string_state = {
            "string_id": string_id,
            "module_count": len(string_modules),
            "voc_min_temp_v": voc_min[0],
            "voc_min_temp_lower_v": voc_min[1],
            "voc_min_temp_upper_v": voc_min[2],
            "vmp_min_temp_v": vmp_min[0],
            "vmp_min_temp_lower_v": vmp_min[1],
            "vmp_min_temp_upper_v": vmp_min[2],
            "vmp_max_temp_v": vmp_max[0],
            "vmp_max_temp_lower_v": vmp_max[1],
            "vmp_max_temp_upper_v": vmp_max[2],
            "imp_min_temp_a": imp_min[0],
            "imp_min_temp_lower_a": imp_min[1],
            "imp_min_temp_upper_a": imp_min[2],
            "imp_max_temp_a": imp_max[0],
            "imp_max_temp_lower_a": imp_max[1],
            "imp_max_temp_upper_a": imp_max[2],
            "isc_min_temp_a": isc_min[0],
            "isc_min_temp_lower_a": isc_min[1],
            "isc_min_temp_upper_a": isc_min[2],
            "isc_max_temp_a": isc_max[0],
            "isc_max_temp_lower_a": isc_max[1],
            "isc_max_temp_upper_a": isc_max[2],
            "stc_power_w": sum(
                state.stc_power_w for _, state in string_modules
            ),
            "module_system_voltage_limit_v": min(
                (
                    state.max_system_voltage_v
                    for _, state in string_modules
                    if state.max_system_voltage_v is not None
                ),
                default=None,
            ),
            "orientations": orientations,
            "module_instance_ids": ids,
            "evidence_grades": evidence_grades,
            "uses_linear_fallback": any(
                state.downgraded for _, state in string_modules
            ),
        }
        string_states[string_id] = string_state
        string_state["imp_design_max_a"] = max(
            string_state["imp_min_temp_a"],
            string_state["imp_max_temp_a"],
        )
        string_state["imp_design_upper_a"] = max(
            string_state["imp_min_temp_upper_a"],
            string_state["imp_max_temp_upper_a"],
        )
        string_state["isc_design_max_a"] = max(
            string_state["isc_min_temp_a"],
            string_state["isc_max_temp_a"],
        )
        string_state["isc_design_upper_a"] = max(
            string_state["isc_min_temp_upper_a"],
            string_state["isc_max_temp_upper_a"],
        )
        findings.append(
            _finding(
                project_revision_id=project_revision_id,
                entity_id=string_id,
                rule_id="STRING_DESIGN_CURRENT_COMPUTED",
                classification="INFO",
                category="electrical_current",
                message=(
                    "Worst-endpoint string operating current was computed "
                    "for the configured design irradiance and cell-temperature range."
                ),
                generated_at=generated_at,
                measured_value=string_state["imp_design_max_a"],
                unit="A",
                context={
                    "isc_a": string_state["isc_design_max_a"],
                    "minimum_cell_temperature_c": cfg[
                        "minimum_cell_temperature_c"
                    ],
                    "maximum_cell_temperature_c": cfg[
                        "maximum_cell_temperature_c"
                    ],
                    "design_irradiance_w_m2": cfg[
                        "design_irradiance_w_m2"
                    ],
                    "evidence_grades": string_state["evidence_grades"],
                    "conservative_operating_current_upper_a": (
                        string_state["imp_design_upper_a"]
                    ),
                    "conservative_isc_upper_a": (
                        string_state["isc_design_upper_a"]
                    ),
                },
            )
        )

    for module_id, owners in sorted(module_membership.items()):
        if len(owners) > 1:
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=module_id,
                    rule_id="MODULE_IN_MULTIPLE_STRINGS",
                    classification="INVALID",
                    category="electrical_topology",
                    message=(
                        "One module instance belongs to more than one enabled string."
                    ),
                    generated_at=generated_at,
                    context={"string_ids": sorted(owners)},
                )
            )

    # Per-inverter / per-MPPT engineering checks.
    for inverter_id, inverter in sorted(inverters.items()):
        if inverter.get("enabled") is not True:
            continue
        snapshot = inverter_snapshots.get(inverter_id)
        if snapshot is None:
            continue
        mppt_specs = {
            int(item["index"]): item for item in snapshot["mppts"]
        }
        inverter_mppts = sorted(
            [
                item
                for item in mppts.values()
                if item.get("inverter_instance_id") == inverter_id
                and item.get("enabled") is True
            ],
            key=lambda item: int(item["index"]),
        )
        connected_string_ids: list[str] = []

        for mppt in inverter_mppts:
            mppt_id = str(mppt["mppt_instance_id"])
            index = int(mppt["index"])
            spec = mppt_specs.get(index)
            if spec is None:
                findings.append(
                    _finding(
                        project_revision_id=project_revision_id,
                        entity_id=mppt_id,
                        rule_id="MPPT_INDEX_UNSUPPORTED_BY_INVERTER_REVISION",
                        classification="INVALID",
                        category="component_binding",
                        message=(
                            "Canonical MPPT index is not available on the "
                            "bound inverter revision."
                        ),
                        generated_at=generated_at,
                    )
                )
                continue

            ids = [
                str(value)
                for value in mppt.get("connected_string_ids", [])
                if str(value) in string_states
                and strings[str(value)].get("enabled") is True
            ]
            connected_string_ids.extend(ids)
            states = [string_states[string_id] for string_id in ids]

            if states:
                lengths = sorted(
                    {int(item["module_count"]) for item in states}
                )
                if len(lengths) > 1:
                    findings.append(
                        _finding(
                            project_revision_id=project_revision_id,
                            entity_id=mppt_id,
                            rule_id="MPPT_UNEQUAL_STRING_LENGTH",
                            classification="WARNING",
                            category="electrical_topology",
                            message=(
                                "Parallel strings on the same MPPT have unequal "
                                "module counts."
                            ),
                            generated_at=generated_at,
                            context={"module_counts": lengths},
                        )
                    )

                reference_orientation = states[0]["orientations"][0]
                tolerance = float(cfg["orientation_tolerance_deg"])
                mismatched = []
                largest_normal_angle = None
                if cfg.get("orientation_comparison", "tilt_azimuth") == "normal_angle":
                    # S14b: the largest pairwise angle between module normals on the MPPT, the same rule the
                    # execution plan uses to group strings; the strings off the first orientation are listed.
                    from engine.simulation.execution_groups import normal_angle_deg
                    distinct = sorted({tuple(o) for state in states for o in state["orientations"]})
                    largest_normal_angle = max((normal_angle_deg(a, b) for i, a in enumerate(distinct) for b in distinct[i + 1:]), default=0.0)
                    if largest_normal_angle > tolerance:
                        mismatched = [state["string_id"] for state in states
                                      if any(tuple(o) != tuple(reference_orientation) for o in state["orientations"])]
                for state in states if largest_normal_angle is None else ():
                    for tilt, azimuth in state["orientations"]:
                        if (
                            abs(tilt - reference_orientation[0]) > tolerance
                            or _azimuth_difference_deg(
                                azimuth, reference_orientation[1]
                            )
                            > tolerance
                        ):
                            mismatched.append(state["string_id"])
                            break
                if mismatched:
                    findings.append(
                        _finding(
                            project_revision_id=project_revision_id,
                            entity_id=mppt_id,
                            rule_id="MPPT_ORIENTATION_MISMATCH",
                            classification="WARNING",
                            category="electrical_topology",
                            message=(
                                "Strings/modules on the same MPPT have different "
                                "tilt or azimuth."
                            ),
                            generated_at=generated_at,
                            **({"measured_value": round(largest_normal_angle, 3), "limit_value": tolerance, "unit": "°"}
                               if largest_normal_angle is not None else {}),
                            context={
                                "string_ids": sorted(set(mismatched)),
                                "orientation_tolerance_deg": tolerance,
                                **({"orientation_comparison": "normal_angle"} if largest_normal_angle is not None else {}),
                            },
                        )
                    )

            min_v = spec.get("min_operating_voltage_v")
            max_v = spec.get("max_operating_voltage_v")
            for state in states:
                string_id = str(state["string_id"])
                for (
                    label,
                    measured,
                    lower,
                    upper,
                    rule_id,
                    uncertainty_rule_id,
                ) in (
                    (
                        "minimum_cell_temperature",
                        state["vmp_min_temp_v"],
                        state["vmp_min_temp_lower_v"],
                        state["vmp_min_temp_upper_v"],
                        "STRING_VMPP_MIN_TEMP_OUTSIDE_MPPT_WINDOW",
                        "STRING_VMPP_MIN_TEMP_FALLBACK_UNCERTAINTY_NEAR_MPPT_WINDOW",
                    ),
                    (
                        "maximum_cell_temperature",
                        state["vmp_max_temp_v"],
                        state["vmp_max_temp_lower_v"],
                        state["vmp_max_temp_upper_v"],
                        "STRING_VMPP_MAX_TEMP_OUTSIDE_MPPT_WINDOW",
                        "STRING_VMPP_MAX_TEMP_FALLBACK_UNCERTAINTY_NEAR_MPPT_WINDOW",
                    ),
                ):
                    definitely_outside = (
                        min_v is not None and upper < float(min_v)
                    ) or (
                        max_v is not None and lower > float(max_v)
                    )
                    crosses_boundary = (
                        min_v is not None
                        and lower < float(min_v) <= upper
                    ) or (
                        max_v is not None
                        and lower <= float(max_v) < upper
                    )
                    if definitely_outside:
                        findings.append(
                            _finding(
                                project_revision_id=project_revision_id,
                                entity_id=string_id,
                                rule_id=rule_id,
                                classification="INVALID",
                                category="electrical_voltage",
                                message=(
                                    "The complete string Vmpp evidence envelope "
                                    "is outside the bound inverter MPPT operating "
                                    "window at a configured design temperature."
                                ),
                                generated_at=generated_at,
                                measured_value=measured,
                                limit_value={
                                    "minimum_v": min_v,
                                    "maximum_v": max_v,
                                },
                                unit="V",
                                context={
                                    "mppt_instance_id": mppt_id,
                                    "temperature_condition": label,
                                    "evidence_lower_v": lower,
                                    "evidence_upper_v": upper,
                                    "evidence_grades": state[
                                        "evidence_grades"
                                    ],
                                },
                            )
                        )
                    elif state["uses_linear_fallback"] and crosses_boundary:
                        findings.append(
                            _finding(
                                project_revision_id=project_revision_id,
                                entity_id=string_id,
                                rule_id=uncertainty_rule_id,
                                classification="WARNING",
                                category="evidence_quality",
                                message=(
                                    "The linear-fallback Vmpp uncertainty "
                                    "envelope crosses an MPPT operating-window "
                                    "boundary; the approximate result is not "
                                    "authoritative enough for a hard INVALID."
                                ),
                                generated_at=generated_at,
                                measured_value=measured,
                                limit_value={
                                    "minimum_v": min_v,
                                    "maximum_v": max_v,
                                },
                                unit="V",
                                context={
                                    "mppt_instance_id": mppt_id,
                                    "temperature_condition": label,
                                    "evidence_lower_v": lower,
                                    "evidence_upper_v": upper,
                                    "evidence_grades": state[
                                        "evidence_grades"
                                    ],
                                },
                            )
                        )

                absolute_limit = snapshot["dc_limits"].get(
                    "max_dc_voltage_v"
                )
                conservative_voc = state["voc_min_temp_upper_v"]
                if (
                    absolute_limit is not None
                    and conservative_voc > float(absolute_limit)
                ):
                    findings.append(
                        _finding(
                            project_revision_id=project_revision_id,
                            entity_id=string_id,
                            rule_id="STRING_VOC_EXCEEDS_INVERTER_MAX_DC",
                            classification="INVALID",
                            category="electrical_voltage",
                            message=(
                                "Conservative string Voc evidence at minimum "
                                "design cell temperature exceeds inverter "
                                "absolute maximum DC voltage."
                            ),
                            generated_at=generated_at,
                            measured_value=conservative_voc,
                            limit_value=float(absolute_limit),
                            unit="V",
                            context={
                                "nominal_estimate_v": state[
                                    "voc_min_temp_v"
                                ],
                                "evidence_lower_v": state[
                                    "voc_min_temp_lower_v"
                                ],
                                "minimum_cell_temperature_c": cfg[
                                    "minimum_cell_temperature_c"
                                ],
                                "inverter_instance_id": inverter_id,
                                "evidence_grades": state[
                                    "evidence_grades"
                                ],
                            },
                        )
                    )
                module_limit = state[
                    "module_system_voltage_limit_v"
                ]
                if (
                    module_limit is not None
                    and conservative_voc > float(module_limit)
                ):
                    findings.append(
                        _finding(
                            project_revision_id=project_revision_id,
                            entity_id=string_id,
                            rule_id="STRING_VOC_EXCEEDS_MODULE_SYSTEM_VOLTAGE",
                            classification="INVALID",
                            category="electrical_voltage",
                            message=(
                                "Conservative string Voc evidence at minimum "
                                "design cell temperature exceeds the lowest "
                                "module maximum-system-voltage rating."
                            ),
                            generated_at=generated_at,
                            measured_value=conservative_voc,
                            limit_value=float(module_limit),
                            unit="V",
                            context={
                                "nominal_estimate_v": state[
                                    "voc_min_temp_v"
                                ],
                                "evidence_lower_v": state[
                                    "voc_min_temp_lower_v"
                                ],
                                "evidence_grades": state[
                                    "evidence_grades"
                                ],
                            },
                        )
                    )

            total_imp = sum(
                float(item["imp_design_max_a"]) for item in states
            )
            total_imp_upper = sum(
                float(item["imp_design_upper_a"]) for item in states
            )
            total_isc = sum(
                float(item["isc_design_max_a"]) for item in states
            )
            total_isc_upper = sum(
                float(item["isc_design_upper_a"]) for item in states
            )
            max_i = spec.get("max_operating_current_a")
            max_isc = spec.get("max_short_circuit_current_a")
            if max_i is None and states:
                findings.append(
                    _finding(
                        project_revision_id=project_revision_id,
                        entity_id=mppt_id,
                        rule_id="MPPT_OPERATING_CURRENT_LIMIT_UNAVAILABLE",
                        classification="WARNING",
                        category="component_capability",
                        message=(
                            "MPPT operating-current limit is not available; "
                            "the aggregate current check is incomplete."
                        ),
                        generated_at=generated_at,
                        measured_value=total_imp,
                        unit="A",
                        context={
                            "conservative_upper_a": total_imp_upper,
                            "evidence_grades": sorted(
                                {
                                    grade
                                    for item in states
                                    for grade in item["evidence_grades"]
                                }
                            ),
                        },
                    )
                )
            elif max_i is not None and total_imp_upper > float(max_i):
                findings.append(
                    _finding(
                        project_revision_id=project_revision_id,
                        entity_id=mppt_id,
                        rule_id="MPPT_OPERATING_CURRENT_EXCEEDED",
                        classification="WARNING",
                        category="electrical_current",
                        message=(
                            "Conservative aggregate operating current exceeds the "
                            "MPPT operating-current limit; the inverter will limit "
                            "the current (energy loss reported in the loss waterfall)."
                        ),
                        generated_at=generated_at,
                        measured_value=total_imp_upper,
                        limit_value=float(max_i),
                        unit="A",
                        context={
                            "nominal_estimate_a": total_imp,
                            "evidence_grades": sorted(
                                {
                                    grade
                                    for item in states
                                    for grade in item["evidence_grades"]
                                }
                            ),
                        },
                    )
                )
            if max_isc is None and states:
                findings.append(
                    _finding(
                        project_revision_id=project_revision_id,
                        entity_id=mppt_id,
                        rule_id="MPPT_SHORT_CIRCUIT_CURRENT_LIMIT_UNAVAILABLE",
                        classification="WARNING",
                        category="component_capability",
                        message=(
                            "MPPT short-circuit-current limit is not available; "
                            "the aggregate Isc check is incomplete."
                        ),
                        generated_at=generated_at,
                        measured_value=total_isc,
                        unit="A",
                        context={
                            "conservative_upper_a": total_isc_upper,
                            "evidence_grades": sorted(
                                {
                                    grade
                                    for item in states
                                    for grade in item["evidence_grades"]
                                }
                            ),
                        },
                    )
                )
            elif max_isc is not None and total_isc_upper > float(max_isc):
                findings.append(
                    _finding(
                        project_revision_id=project_revision_id,
                        entity_id=mppt_id,
                        rule_id="MPPT_SHORT_CIRCUIT_CURRENT_EXCEEDED",
                        classification="INVALID",
                        category="electrical_current",
                        message=(
                            "Conservative aggregate Isc evidence exceeds the "
                            "MPPT short-circuit-current limit."
                        ),
                        generated_at=generated_at,
                        measured_value=total_isc_upper,
                        limit_value=float(max_isc),
                        unit="A",
                        context={
                            "nominal_estimate_a": total_isc,
                            "evidence_grades": sorted(
                                {
                                    grade
                                    for item in states
                                    for grade in item["evidence_grades"]
                                }
                            ),
                        },
                    )
                )

        unique_connected = sorted(set(connected_string_ids))
        inverter_states = [
            string_states[string_id]
            for string_id in unique_connected
            if string_id in string_states
        ]
        total_imp = sum(
            float(item["imp_design_max_a"]) for item in inverter_states
        )
        total_imp_upper = sum(
            float(item["imp_design_upper_a"]) for item in inverter_states
        )
        total_isc = sum(
            float(item["isc_design_max_a"]) for item in inverter_states
        )
        total_isc_upper = sum(
            float(item["isc_design_upper_a"]) for item in inverter_states
        )
        dc_limits = snapshot["dc_limits"]
        total_evidence_grades = sorted(
            {
                grade
                for item in inverter_states
                for grade in item["evidence_grades"]
            }
        )
        if dc_limits.get("max_dc_current_a") is None and inverter_states:
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=inverter_id,
                    rule_id="INVERTER_TOTAL_DC_CURRENT_LIMIT_UNAVAILABLE",
                    classification="WARNING",
                    category="component_capability",
                    message=(
                        "Total inverter DC operating-current limit is not "
                        "available; inverter-level aggregate current validation "
                        "is incomplete."
                    ),
                    generated_at=generated_at,
                    measured_value=total_imp,
                    unit="A",
                    context={
                        "conservative_upper_a": total_imp_upper,
                        "evidence_grades": total_evidence_grades,
                    },
                )
            )
        elif (
            dc_limits.get("max_dc_current_a") is not None
            and total_imp_upper > float(dc_limits["max_dc_current_a"])
        ):
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=inverter_id,
                    rule_id="INVERTER_TOTAL_DC_CURRENT_EXCEEDED",
                    classification="INVALID",
                    category="electrical_current",
                    message=(
                        "Conservative total inverter operating-current evidence "
                        "exceeds the inverter DC current limit."
                    ),
                    generated_at=generated_at,
                    measured_value=total_imp_upper,
                    limit_value=float(dc_limits["max_dc_current_a"]),
                    unit="A",
                    context={
                        "nominal_estimate_a": total_imp,
                        "evidence_grades": total_evidence_grades,
                    },
                )
            )
        if (
            dc_limits.get("max_dc_short_circuit_current_a") is None
            and inverter_states
        ):
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=inverter_id,
                    rule_id="INVERTER_TOTAL_DC_ISC_LIMIT_UNAVAILABLE",
                    classification="WARNING",
                    category="component_capability",
                    message=(
                        "Total inverter DC short-circuit-current limit is not "
                        "available; inverter-level aggregate Isc validation is "
                        "incomplete."
                    ),
                    generated_at=generated_at,
                    measured_value=total_isc,
                    unit="A",
                    context={
                        "conservative_upper_a": total_isc_upper,
                        "evidence_grades": total_evidence_grades,
                    },
                )
            )
        elif (
            dc_limits.get("max_dc_short_circuit_current_a") is not None
            and total_isc_upper
            > float(dc_limits["max_dc_short_circuit_current_a"])
        ):
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=inverter_id,
                    rule_id="INVERTER_TOTAL_DC_ISC_EXCEEDED",
                    classification="INVALID",
                    category="electrical_current",
                    message=(
                        "Conservative total inverter short-circuit-current "
                        "evidence exceeds the inverter DC short-circuit-current "
                        "limit."
                    ),
                    generated_at=generated_at,
                    measured_value=total_isc_upper,
                    limit_value=float(
                        dc_limits["max_dc_short_circuit_current_a"]
                    ),
                    unit="A",
                    context={
                        "nominal_estimate_a": total_isc,
                        "evidence_grades": total_evidence_grades,
                    },
                )
            )

        dc_power = sum(
            float(item["stc_power_w"]) for item in inverter_states
        )
        ac_power = snapshot["ac_limits"].get("nominal_ac_power_w")
        if ac_power is not None and float(ac_power) > 0.0:
            ratio = dc_power / float(ac_power)
            findings.append(
                _finding(
                    project_revision_id=project_revision_id,
                    entity_id=inverter_id,
                    rule_id="INVERTER_DC_AC_RATIO",
                    classification="INFO",
                    category="sizing",
                    message="Inverter connected STC DC/AC ratio was computed.",
                    generated_at=generated_at,
                    measured_value=ratio,
                    unit=None,
                    context={
                        "connected_dc_stc_power_w": dc_power,
                        "nominal_ac_power_w": float(ac_power),
                    },
                )
            )
            ratio_min = cfg.get("dc_ac_ratio_warning_min")
            ratio_max = cfg.get("dc_ac_ratio_warning_max")
            outside = (
                ratio_min is not None and ratio < float(ratio_min)
            ) or (
                ratio_max is not None and ratio > float(ratio_max)
            )
            if outside:
                findings.append(
                    _finding(
                        project_revision_id=project_revision_id,
                        entity_id=inverter_id,
                        rule_id="INVERTER_DC_AC_RATIO_OUTSIDE_POLICY",
                        classification="WARNING",
                        category="sizing",
                        message=(
                            "DC/AC ratio is outside the configured advisory range."
                        ),
                        generated_at=generated_at,
                        measured_value=ratio,
                        limit_value={
                            "minimum": ratio_min,
                            "maximum": ratio_max,
                        },
                    )
                )

    finalized = _finalize_findings(
        findings, report_id=design_validation_report_id
    )
    counts = {
        "info": sum(
            1 for item in finalized if item["severity"] == "info"
        ),
        "recommendation": sum(
            1
            for item in finalized
            if item["severity"] == "recommendation"
        ),
        "warning": sum(
            1 for item in finalized if item["severity"] == "warning"
        ),
        "error": sum(
            1 for item in finalized if item["severity"] == "error"
        ),
        "blocking_error": sum(
            1
            for item in finalized
            if item["severity"] == "blocking_error"
        ),
    }
    blocking = counts["blocking_error"] > 0
    status = (
        "invalid"
        if blocking
        else "valid_with_findings"
        if finalized
        else "valid"
    )
    classification_counts = {
        classification: sum(
            1
            for item in finalized
            if item["classification"] == classification
        )
        for classification in (
            "INFO",
            "RECOMMENDATION",
            "WARNING",
            "INVALID",
        )
    }
    return {
        "schema_name": "DesignValidationReport",
        "schema_version": "0.1",
        "design_validation_report_id": design_validation_report_id,
        "project_revision_id": project_revision_id,
        "scene_revision_id": str(scene_copy["revision_id"]),
        "electrical_revision_id": str(
            electrical["electrical_revision_id"]
        ),
        "rule_set_id": ENGINEERING_RULE_SET_ID,
        "generated_at": generated_at,
        "status": status,
        "finding_counts": counts,
        "blocking_simulation": blocking,
        "findings": finalized,
        "metadata": {
            "classification_counts": classification_counts,
            "validation_configuration": cfg,
            "design_mutated": False,
            "temperature_model_precedence": [
                "validated_pvsyst_singlediode",
                "linear_temperature_coefficients_fallback",
            ],
            "linear_fallback_vmp_assumption": (
                "relative_beta_vmp ≈ relative_gamma_pmp "
                "- relative_alpha_isc"
            ),
            "validation_evidence_policy": {
                "detailed_model": (
                    "validated_pvsyst_singlediode with "
                    "detailed_sdm_ready=true"
                ),
                "fallback_model": (
                    "temperature coefficients at module reference irradiance"
                ),
                "fallback_voltage_uncertainty_fraction": cfg[
                    "fallback_voltage_uncertainty_fraction"
                ],
                "fallback_current_uncertainty_fraction": cfg[
                    "fallback_current_uncertainty_fraction"
                ],
                "absolute_limit_policy": (
                    "INVALID if conservative upper evidence exceeds limit"
                ),
                "mppt_window_policy": (
                    "INVALID only if full evidence envelope is outside; "
                    "WARNING if fallback envelope crosses boundary"
                ),
                "fallback_reference_irradiance_only": True,
            },
        },
    }
