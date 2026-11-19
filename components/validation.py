"""Engineering validation and capability evaluation for component candidates.

The checks in this module implement the v0.1 Open Component Library engineering anchor.
They intentionally separate:
- schema completeness;
- engineering consistency;
- simulation capability.

A component may be structurally representable yet still lack enough evidence or parameters
for a particular simulation capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable


ERROR_SEVERITIES = {"error", "blocking_error"}

PVSYST_SDM_REQUIRED_PARAMETERS = {
    "r_series_ohm",
    "r_shunt_ref_ohm",
    "r_shunt_0_ohm",
    "r_shunt_exp",
    "gamma_ref",
    "mu_gamma",
}


@dataclass(frozen=True)
class ValidationConfig:
    stc_power_relative_tolerance: float = 0.02


def finding(
    rule_id: str,
    severity: str,
    category: str,
    message: str,
    *,
    field_path: str | None = None,
    measured_value: Any = None,
    limit_value: Any = None,
    unit: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "category": category,
        "field_path": field_path,
        "message": message,
        "measured_value": measured_value,
        "limit_value": limit_value,
        "unit": unit,
        "context": context or {},
    }


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _get(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _required_positive_findings(
    data: dict[str, Any],
    paths: Iterable[tuple[str, ...]],
    *,
    category: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in paths:
        value = _get(data, *path)
        field_path = ".".join(path)
        if value is None:
            results.append(
                finding(
                    f"MISSING_{field_path.upper().replace('.', '_')}",
                    "error",
                    category,
                    f"Required value {field_path} is missing.",
                    field_path=field_path,
                )
            )
        elif not _positive(value):
            results.append(
                finding(
                    f"NONPOSITIVE_{field_path.upper().replace('.', '_')}",
                    "error",
                    category,
                    f"{field_path} must be greater than zero.",
                    field_path=field_path,
                    measured_value=value,
                )
            )
    return results


def validate_module(
    data: dict[str, Any],
    *,
    config: ValidationConfig | None = None,
) -> list[dict[str, Any]]:
    config = config or ValidationConfig()
    findings: list[dict[str, Any]] = []

    for field_name in ("manufacturer", "model"):
        value = data.get(field_name)
        if not isinstance(value, str) or not value.strip():
            findings.append(
                finding(
                    f"MODULE_{field_name.upper()}_MISSING",
                    "blocking_error",
                    "identity",
                    f"Module {field_name} is required.",
                    field_path=field_name,
                )
            )

    findings.extend(
        _required_positive_findings(
            data,
            [("mechanical", "width_m"), ("mechanical", "height_m")],
            category="geometry",
        )
    )

    for optional_path in (("mechanical", "thickness_m"), ("mechanical", "mass_kg")):
        value = _get(data, *optional_path)
        if value is not None and not _positive(value):
            findings.append(
                finding(
                    f"MODULE_{'_'.join(optional_path).upper()}_NONPOSITIVE",
                    "error",
                    "geometry",
                    f"{'.'.join(optional_path)} must be greater than zero when present.",
                    field_path=".".join(optional_path),
                    measured_value=value,
                )
            )

    stc_paths = [
        ("stc", "pmp_w"),
        ("stc", "voc_v"),
        ("stc", "isc_a"),
        ("stc", "vmp_v"),
        ("stc", "imp_a"),
        ("stc", "reference_irradiance_w_m2"),
    ]
    findings.extend(_required_positive_findings(data, stc_paths, category="electrical"))

    tref = _get(data, "stc", "reference_cell_temperature_c")
    if tref is None:
        findings.append(
            finding(
                "MODULE_STC_REFERENCE_TEMPERATURE_MISSING",
                "error",
                "electrical",
                "stc.reference_cell_temperature_c is missing.",
                field_path="stc.reference_cell_temperature_c",
            )
        )

    voc = _get(data, "stc", "voc_v")
    vmp = _get(data, "stc", "vmp_v")
    isc = _get(data, "stc", "isc_a")
    imp = _get(data, "stc", "imp_a")
    pmp = _get(data, "stc", "pmp_w")

    if _positive(voc) and _positive(vmp) and voc <= vmp:
        findings.append(
            finding(
                "MODULE_VOC_NOT_ABOVE_VMP",
                "error",
                "electrical",
                "Voc must be greater than Vmp.",
                field_path="stc.voc_v",
                measured_value=voc,
                limit_value=vmp,
                unit="V",
            )
        )

    if _positive(isc) and _positive(imp) and isc < imp:
        findings.append(
            finding(
                "MODULE_ISC_BELOW_IMP",
                "error",
                "electrical",
                "Isc must be greater than or equal to Imp.",
                field_path="stc.isc_a",
                measured_value=isc,
                limit_value=imp,
                unit="A",
            )
        )

    if _positive(pmp) and _positive(vmp) and _positive(imp):
        point_power = float(vmp) * float(imp)
        denom = max(abs(float(pmp)), abs(point_power))
        relative_error = abs(float(pmp) - point_power) / denom if denom else 0.0
        if relative_error > config.stc_power_relative_tolerance:
            findings.append(
                finding(
                    "MODULE_PMP_VMP_IMP_MISMATCH",
                    "warning",
                    "electrical",
                    "Pmp differs from Vmp × Imp beyond the configured tolerance.",
                    field_path="stc.pmp_w",
                    measured_value=relative_error,
                    limit_value=config.stc_power_relative_tolerance,
                    unit="fraction",
                    context={"pmp_w": pmp, "vmp_imp_w": point_power},
                )
            )

    max_voltages = [
        ("limits.max_system_voltage_v", _get(data, "limits", "max_system_voltage_v")),
        ("limits.max_system_voltage_iec_v", _get(data, "limits", "max_system_voltage_iec_v")),
        ("limits.max_system_voltage_ul_v", _get(data, "limits", "max_system_voltage_ul_v")),
    ]
    if _positive(voc):
        for path, limit in max_voltages:
            if limit is not None and (not _positive(limit) or limit < voc):
                findings.append(
                    finding(
                        "MODULE_SYSTEM_VOLTAGE_BELOW_VOC",
                        "error",
                        "limits",
                        f"{path} must be at least Voc.",
                        field_path=path,
                        measured_value=limit,
                        limit_value=voc,
                        unit="V",
                    )
                )

    optical = data.get("optical") or {}
    absorptance = optical.get("absorptance_fraction")
    if absorptance is not None:
        if (
            not isinstance(absorptance, (int, float))
            or isinstance(absorptance, bool)
            or not isfinite(float(absorptance))
            or not 0.0 < float(absorptance) <= 1.0
        ):
            findings.append(
                finding(
                    "MODULE_ABSORPTANCE_OUT_OF_RANGE",
                    "error",
                    "optical_thermal",
                    "optical.absorptance_fraction must be finite and within (0, 1].",
                    field_path="optical.absorptance_fraction",
                    measured_value=absorptance,
                    limit_value={"minimum_exclusive": 0.0, "maximum": 1.0},
                    unit="fraction",
                )
            )

    iam = optical.get("iam")
    if isinstance(iam, dict):
        points = iam.get("points")
        if not isinstance(points, list) or len(points) < 2:
            findings.append(
                finding(
                    "MODULE_IAM_PROFILE_TOO_SHORT",
                    "error",
                    "optical",
                    "Tabulated IAM requires at least two points.",
                    field_path="optical.iam.points",
                    measured_value=(len(points) if isinstance(points, list) else None),
                    limit_value=2,
                    unit="count",
                )
            )
        else:
            previous_angle = None
            for index, point in enumerate(points):
                angle = point.get("angle_deg") if isinstance(point, dict) else None
                modifier = point.get("modifier") if isinstance(point, dict) else None
                point_path = f"optical.iam.points[{index}]"
                if (
                    not isinstance(angle, (int, float))
                    or isinstance(angle, bool)
                    or not isfinite(float(angle))
                    or not 0.0 <= float(angle) <= 90.0
                ):
                    findings.append(
                        finding(
                            "MODULE_IAM_ANGLE_INVALID",
                            "error",
                            "optical",
                            "IAM angle must be finite and within 0..90 degrees.",
                            field_path=f"{point_path}.angle_deg",
                            measured_value=angle,
                            unit="deg",
                        )
                    )
                    continue
                if (
                    not isinstance(modifier, (int, float))
                    or isinstance(modifier, bool)
                    or not isfinite(float(modifier))
                    or float(modifier) < 0.0
                ):
                    findings.append(
                        finding(
                            "MODULE_IAM_MODIFIER_INVALID",
                            "error",
                            "optical",
                            "IAM modifier must be finite and non-negative.",
                            field_path=f"{point_path}.modifier",
                            measured_value=modifier,
                            unit="fraction",
                        )
                    )
                if previous_angle is not None and float(angle) <= previous_angle:
                    findings.append(
                        finding(
                            "MODULE_IAM_ANGLES_NOT_STRICTLY_INCREASING",
                            "error",
                            "optical",
                            "IAM angles must be strictly increasing.",
                            field_path="optical.iam.points",
                            measured_value=float(angle),
                            limit_value=previous_angle,
                            unit="deg",
                        )
                    )
                previous_angle = float(angle)
            first_angle = points[0].get("angle_deg") if isinstance(points[0], dict) else None
            if first_angle != 0 and first_angle != 0.0:
                findings.append(
                    finding(
                        "MODULE_IAM_ZERO_DEGREE_REFERENCE_MISSING",
                        "error",
                        "optical",
                        "IAM profile must start with an explicit 0-degree reference.",
                        field_path="optical.iam.points[0].angle_deg",
                        measured_value=first_angle,
                        limit_value=0.0,
                        unit="deg",
                    )
                )

    quality = data.get("quality") or {}
    tolerance = quality.get("nameplate_power_tolerance")
    if isinstance(tolerance, dict):
        lower = tolerance.get("lower_fraction")
        upper = tolerance.get("upper_fraction")
        if lower is not None and upper is not None:
            valid_lower = (
                isinstance(lower, (int, float))
                and not isinstance(lower, bool)
                and isfinite(float(lower))
            )
            valid_upper = (
                isinstance(upper, (int, float))
                and not isinstance(upper, bool)
                and isfinite(float(upper))
            )
            if not valid_lower or not valid_upper:
                findings.append(
                    finding(
                        "MODULE_NAMEPLATE_TOLERANCE_NONFINITE",
                        "error",
                        "module_quality",
                        "Module nameplate power-tolerance bounds must be finite.",
                        field_path="quality.nameplate_power_tolerance",
                        measured_value={"lower_fraction": lower, "upper_fraction": upper},
                        unit="fraction",
                    )
                )
            elif float(lower) > float(upper):
                findings.append(
                    finding(
                        "MODULE_NAMEPLATE_TOLERANCE_REVERSED",
                        "error",
                        "module_quality",
                        "Lower nameplate power tolerance cannot exceed upper tolerance.",
                        field_path="quality.nameplate_power_tolerance",
                        measured_value={"lower_fraction": lower, "upper_fraction": upper},
                        unit="fraction",
                    )
                )

    module_quality = quality.get("default_module_quality_loss_fraction")
    if module_quality is not None and (
        not isinstance(module_quality, (int, float))
        or isinstance(module_quality, bool)
        or not isfinite(float(module_quality))
    ):
        findings.append(
            finding(
                "MODULE_QUALITY_DEFAULT_NONFINITE",
                "error",
                "module_quality",
                "Default module-quality loss fraction must be finite when present.",
                field_path="quality.default_module_quality_loss_fraction",
                measured_value=module_quality,
                unit="fraction",
            )
        )

    for model in data.get("electrical_models", []) or []:
        if model.get("model_type") != "pvsyst_singlediode":
            continue
        params = model.get("parameter_set") or {}
        for key in ("r_series_ohm", "r_shunt_ref_ohm", "r_shunt_0_ohm"):
            value = params.get(key)
            if value is not None and not _positive(value):
                findings.append(
                    finding(
                        f"MODULE_SDM_{key.upper()}_NONPOSITIVE",
                        "error",
                        "electrical_model",
                        f"PVsyst single-diode parameter {key} must be greater than zero.",
                        field_path=f"electrical_models.pvsyst_singlediode.parameter_set.{key}",
                        measured_value=value,
                        unit="ohm",
                    )
                )

    return findings


def pvsyst_sdm_readiness(validation: dict[str, Any]) -> dict[str, Any]:
    """Accept only a beta-only mismatch beyond the ordinary strict SDM policy.

    Raw records are evidence, never modified here. Legacy model records without
    the raw subrecords retain their existing aggregate acceptance contract.
    """
    stc = validation.get("stc")
    off = validation.get("off_stc")
    accepted = validation.get("passed") is True
    if isinstance(stc, dict) and isinstance(off, dict):
        accepted = stc.get("passed") is True and off.get("passed") is True
        checks = off.get("coefficient_checks") or {}
        beta = checks.get("beta_voc_per_c") or {}
        points = off.get("points") or []
        trends = off.get("trend_checks") or []
        beta_only = (
            stc.get("passed") is True
            and off.get("status") == "failed"
            and off.get("passed") is False
            and not off.get("missing_parameters")
            and not off.get("missing_source_coefficients")
            and (off.get("point_check_summary") or {}).get("passed") is True
            and (off.get("trend_check_summary") or {}).get("passed") is True
            and bool(points) and all(point.get("passed") is True for point in points)
            and bool(trends) and all(check.get("passed") is True for check in trends)
            and {"alpha_isc_per_c", "beta_voc_per_c", "gamma_pmp_per_c"}.issubset(checks)
            and beta.get("passed") is False
            and all(check.get("passed") is True for key, check in checks.items() if key != "beta_voc_per_c")
            and all(isinstance(beta.get(key), (int, float)) and isfinite(beta[key])
                    for key in ("modeled_value", "source_value", "relative_error"))
        )
        if beta_only:
            modeled, source = beta["modeled_value"], beta["source_value"]
            return {"passed": True, "status": "passed", "readiness_tolerances": ["beta_voc_per_c"],
                    "finding": finding(
                        "MODULE_SDM_VOC_TEMPCO_MISMATCH", "warning", "electrical",
                        "The module's single-diode model changes Voc with temperature differently "
                        f"from the datasheet (model {modeled} V/°C, datasheet {source} V/°C). "
                        "Energy simulation uses the model; string voltage limits use the more "
                        "conservative of the two.",
                        field_path="electrical_models.pvsyst_singlediode.validation.off_stc.coefficient_checks.beta_voc_per_c",
                        measured_value=modeled, limit_value=source, unit="V/°C",
                        context={"relative_error": beta["relative_error"]},
                    )}
    status = validation.get("status")
    if isinstance(stc, dict) and isinstance(off, dict):
        status = "passed" if accepted else (
            "incomplete" if stc.get("status") in {"incomplete", "unavailable"}
            or off.get("status") in {"incomplete", "unavailable"} else "failed"
        )
    return {"passed": accepted, "status": status, "readiness_tolerances": [], "finding": None}


def module_capabilities(
    data: dict[str, Any],
    findings: Iterable[dict[str, Any]],
    *,
    model_validation_passed: bool = False,
) -> dict[str, bool]:
    findings = list(findings)
    error_rules = {f["rule_id"] for f in findings if f["severity"] in ERROR_SEVERITIES}

    identity_ok = bool(data.get("manufacturer")) and bool(data.get("model"))
    geometry_ok = _positive(_get(data, "mechanical", "width_m")) and _positive(
        _get(data, "mechanical", "height_m")
    )
    layout_ready = identity_ok and geometry_ok and not any(
        rule.startswith("MODULE_MANUFACTURER")
        or rule.startswith("MODULE_MODEL")
        or "MECHANICAL" in rule
        for rule in error_rules
    )

    stc_required = all(
        _get(data, "stc", key) is not None
        for key in (
            "pmp_w",
            "voc_v",
            "isc_a",
            "vmp_v",
            "imp_a",
            "reference_irradiance_w_m2",
            "reference_cell_temperature_c",
        )
    )
    has_source = bool(data.get("source_ids"))

    coeffs = data.get("temperature_coefficients") or {}
    has_temperature_coefficients = all(
        coeffs.get(key) is not None
        for key in ("alpha_isc_per_c", "beta_voc_per_c", "gamma_pmp_per_c")
    )

    relevant_electrical_errors = any(
        f["severity"] in ERROR_SEVERITIES and f["category"] in {"electrical", "limits"}
        for f in findings
    )
    basic_yield_ready = (
        layout_ready
        and stc_required
        and has_temperature_coefficients
        and has_source
        and not relevant_electrical_errors
    )

    pvsyst_models = [
        model
        for model in (data.get("electrical_models") or [])
        if model.get("model_type") == "pvsyst_singlediode"
    ]
    has_complete_sdm = False
    for model in pvsyst_models:
        params = model.get("parameter_set") or {}
        if PVSYST_SDM_REQUIRED_PARAMETERS.issubset(params):
            has_complete_sdm = True
            break

    detailed_sdm_ready = (
        stc_required
        and has_complete_sdm
        and model_validation_passed
        and all(
            pvsyst_sdm_readiness(model.get("validation") or {})["passed"]
            for model in pvsyst_models if model.get("readiness_tolerances")
        )
        and not relevant_electrical_errors
    )

    bifacial = data.get("bifacial") or {}
    bifacial_ready = (
        basic_yield_ready
        and bifacial.get("enabled") is True
        and _positive(bifacial.get("bifaciality_factor"))
    )

    # Phase 6.1 moved detailed electrical topology out of ModuleDefinition into
    # a separately revisioned ModuleTopologyDefinition. Detailed-shading
    # readiness therefore cannot be decided from the module object alone:
    # topology trust, exact revision binding, bypass coverage, and region/cell
    # parameterization are resolved by shading.electrical capability logic.
    # Keep the legacy capability key for schema/backward compatibility, but
    # never authorize detailed physics from an embedded module_topology shortcut.
    detailed_shading_ready = False

    return {
        "layout_ready": layout_ready,
        "basic_yield_ready": basic_yield_ready,
        "detailed_sdm_ready": detailed_sdm_ready,
        "bifacial_ready": bifacial_ready,
        "detailed_shading_ready": detailed_shading_ready,
        "independent_iv_validated": bool(
            (data.get("capability_flags") or {}).get("independent_iv_validated", False)
        ),
    }


def validate_inverter(data: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    if _get(data, "ac_limits", "nominal_frequency_hz") is None:
        findings.append(finding(
            "INVERTER_AC_FREQUENCY_NOT_SPECIFIED", "warning", "ac",
            "The inverter file does not state its nominal AC frequency. It is not needed "
            "for the energy simulation; check grid compatibility (50 Hz in Indonesia) "
            "against the datasheet.",
            field_path="ac_limits.nominal_frequency_hz",
        ))

    for field_name in ("manufacturer", "model"):
        value = data.get(field_name)
        if not isinstance(value, str) or not value.strip():
            findings.append(
                finding(
                    f"INVERTER_{field_name.upper()}_MISSING",
                    "blocking_error",
                    "identity",
                    f"Inverter {field_name} is required.",
                    field_path=field_name,
                )
            )

    phase = data.get("phase_configuration")
    if phase not in {"single_phase", "three_phase", "other"}:
        findings.append(
            finding(
                "INVERTER_PHASE_MISSING",
                "error",
                "ac",
                "A valid phase configuration is required.",
                field_path="phase_configuration",
            )
        )

    max_dc = _get(data, "dc_limits", "max_dc_voltage_v")
    if max_dc is not None and not _positive(max_dc):
        findings.append(
            finding(
                "INVERTER_MAX_DC_VOLTAGE_NONPOSITIVE",
                "error",
                "dc",
                "Maximum DC voltage must be greater than zero.",
                field_path="dc_limits.max_dc_voltage_v",
                measured_value=max_dc,
                unit="V",
            )
        )

    template = data.get("mppt_template") or {}
    mppt_min = template.get("min_operating_voltage_v")
    mppt_max = template.get("max_operating_voltage_v")
    count = template.get("count")
    op_current = template.get("max_operating_current_a")
    isc_current = template.get("max_short_circuit_current_a")

    if mppt_min is not None and mppt_max is not None:
        if not _positive(mppt_max) or mppt_min < 0 or mppt_min >= mppt_max:
            findings.append(
                finding(
                    "INVERTER_MPPT_RANGE_INVALID",
                    "error",
                    "mppt",
                    "MPPT minimum voltage must be lower than MPPT maximum voltage.",
                    field_path="mppt_template",
                    context={"min_v": mppt_min, "max_v": mppt_max},
                )
            )
        if _positive(max_dc) and _positive(mppt_max) and mppt_max > max_dc:
            findings.append(
                finding(
                    "INVERTER_MPPT_MAX_ABOVE_ABSOLUTE_DC_MAX",
                    "error",
                    "mppt",
                    "Maximum MPPT operating voltage must not exceed absolute maximum DC voltage.",
                    field_path="mppt_template.max_operating_voltage_v",
                    measured_value=mppt_max,
                    limit_value=max_dc,
                    unit="V",
                )
            )

    if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 1):
        findings.append(
            finding(
                "INVERTER_MPPT_COUNT_INVALID",
                "error",
                "mppt",
                "MPPT count must be a positive integer.",
                field_path="mppt_template.count",
                measured_value=count,
            )
        )

    if op_current is not None and not _positive(op_current):
        findings.append(
            finding(
                "INVERTER_MPPT_OPERATING_CURRENT_NONPOSITIVE",
                "error",
                "mppt",
                "Maximum MPPT operating current must be greater than zero.",
                field_path="mppt_template.max_operating_current_a",
                measured_value=op_current,
                unit="A",
            )
        )

    if isc_current is not None:
        if not _positive(isc_current):
            findings.append(
                finding(
                    "INVERTER_MPPT_ISC_NONPOSITIVE",
                    "error",
                    "mppt",
                    "Maximum MPPT short-circuit current must be greater than zero.",
                    field_path="mppt_template.max_short_circuit_current_a",
                    measured_value=isc_current,
                    unit="A",
                )
            )
        elif _positive(op_current) and isc_current < op_current:
            findings.append(
                finding(
                    "INVERTER_MPPT_ISC_BELOW_OPERATING_CURRENT",
                    "error",
                    "mppt",
                    "MPPT short-circuit current limit should not be below its operating current limit.",
                    field_path="mppt_template.max_short_circuit_current_a",
                    measured_value=isc_current,
                    limit_value=op_current,
                    unit="A",
                )
            )

    nominal_ac = _get(data, "ac_limits", "nominal_ac_power_w")
    if nominal_ac is not None and not _positive(nominal_ac):
        findings.append(
            finding(
                "INVERTER_NOMINAL_AC_POWER_NONPOSITIVE",
                "error",
                "ac",
                "Nominal AC power must be greater than zero.",
                field_path="ac_limits.nominal_ac_power_w",
                measured_value=nominal_ac,
                unit="W",
            )
        )

    max_ac = _get(data, "ac_limits", "max_ac_power_w")
    if max_ac is not None:
        if not _positive(max_ac):
            findings.append(
                finding(
                    "INVERTER_MAX_AC_POWER_NONPOSITIVE",
                    "error",
                    "ac",
                    "Maximum AC power must be greater than zero.",
                    field_path="ac_limits.max_ac_power_w",
                    measured_value=max_ac,
                    unit="W",
                )
            )
        elif _positive(nominal_ac) and max_ac < nominal_ac:
            findings.append(
                finding(
                    "INVERTER_MAX_AC_POWER_BELOW_NOMINAL",
                    "error",
                    "ac",
                    "Maximum AC power must not be below nominal AC power.",
                    field_path="ac_limits.max_ac_power_w",
                    measured_value=max_ac,
                    limit_value=nominal_ac,
                    unit="W",
                )
            )

    nominal_ac_current = _get(data, "ac_limits", "nominal_ac_current_a")
    max_ac_current = _get(data, "ac_limits", "max_ac_current_a")
    for key, value in (
        ("nominal_ac_current_a", nominal_ac_current),
        ("max_ac_current_a", max_ac_current),
    ):
        if value is not None and not _positive(value):
            findings.append(
                finding(
                    f"INVERTER_{key.upper()}_NONPOSITIVE",
                    "error",
                    "ac",
                    f"{key} must be greater than zero when present.",
                    field_path=f"ac_limits.{key}",
                    measured_value=value,
                    unit="A",
                )
            )
    if _positive(nominal_ac_current) and _positive(max_ac_current) and max_ac_current < nominal_ac_current:
        findings.append(
            finding(
                "INVERTER_MAX_AC_CURRENT_BELOW_NOMINAL",
                "error",
                "ac",
                "Maximum AC current must not be below nominal AC current.",
                field_path="ac_limits.max_ac_current_a",
                measured_value=max_ac_current,
                limit_value=nominal_ac_current,
                unit="A",
            )
        )

    nominal_mppt_voltage = template.get("nominal_voltage_v")
    if nominal_mppt_voltage is not None:
        if not _positive(nominal_mppt_voltage):
            findings.append(
                finding(
                    "INVERTER_NOMINAL_MPPT_VOLTAGE_NONPOSITIVE",
                    "error",
                    "mppt",
                    "Nominal MPPT voltage must be greater than zero when present.",
                    field_path="mppt_template.nominal_voltage_v",
                    measured_value=nominal_mppt_voltage,
                    unit="V",
                )
            )
        elif _positive(mppt_min) and _positive(mppt_max) and not (
            mppt_min <= nominal_mppt_voltage <= mppt_max
        ):
            findings.append(
                finding(
                    "INVERTER_NOMINAL_MPPT_VOLTAGE_OUTSIDE_RANGE",
                    "warning",
                    "mppt",
                    "Nominal MPPT voltage lies outside the MPPT operating range.",
                    field_path="mppt_template.nominal_voltage_v",
                    measured_value=nominal_mppt_voltage,
                    context={"min_v": mppt_min, "max_v": mppt_max},
                    unit="V",
                )
            )

    sizing = data.get("array_sizing_limits") or {}
    nominal_pv = sizing.get("nominal_pv_array_power_w")
    max_pv = sizing.get("max_pv_array_power_w")
    max_pv_current = sizing.get("max_pv_current_a")
    for key, value, unit in (
        ("nominal_pv_array_power_w", nominal_pv, "W"),
        ("max_pv_array_power_w", max_pv, "W"),
        ("max_pv_current_a", max_pv_current, "A"),
    ):
        if value is not None and not _positive(value):
            findings.append(
                finding(
                    f"INVERTER_ARRAY_SIZING_{key.upper()}_NONPOSITIVE",
                    "error",
                    "array_sizing",
                    f"{key} must be greater than zero when present.",
                    field_path=f"array_sizing_limits.{key}",
                    measured_value=value,
                    unit=unit,
                )
            )
    if _positive(nominal_pv) and _positive(max_pv) and max_pv < nominal_pv:
        findings.append(
            finding(
                "INVERTER_MAX_PV_ARRAY_POWER_BELOW_NOMINAL",
                "error",
                "array_sizing",
                "Maximum PV-array sizing power must not be below nominal PV-array sizing power.",
                field_path="array_sizing_limits.max_pv_array_power_w",
                measured_value=max_pv,
                limit_value=nominal_pv,
                unit="W",
            )
        )

    thresholds = data.get("operating_thresholds") or {}
    for key in (
        "minimum_input_power_w",
        "startup_power_w",
        "shutdown_power_w",
        "standby_loss_w",
        "night_loss_w",
    ):
        value = thresholds.get(key)
        if value is not None and (
            not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0
        ):
            findings.append(
                finding(
                    f"INVERTER_{key.upper()}_INVALID",
                    "error",
                    "loss",
                    f"{key} must be nonnegative when present.",
                    field_path=f"operating_thresholds.{key}",
                    measured_value=value,
                    unit="W",
                )
            )

    derating = data.get("temperature_derating_model") or {}
    t_max = derating.get("max_power_temperature_c")
    t_nom = derating.get("nominal_power_temperature_c")
    t_lim1 = derating.get("limit1_temperature_c")
    t_abs = derating.get("absolute_limit_temperature_c")
    p_lim1 = derating.get("limit1_power_w")
    ordered = [
        ("max_power_temperature_c", t_max),
        ("nominal_power_temperature_c", t_nom),
        ("limit1_temperature_c", t_lim1),
        ("absolute_limit_temperature_c", t_abs),
    ]
    present = [(name, value) for name, value in ordered if value is not None]
    for (left_name, left), (right_name, right) in zip(present, present[1:]):
        if right < left:
            findings.append(
                finding(
                    "INVERTER_TEMPERATURE_DERATING_ORDER_INVALID",
                    "error",
                    "derating",
                    "Temperature-derating breakpoints must be nondecreasing.",
                    field_path="temperature_derating_model",
                    context={
                        "left": {"field": left_name, "value_c": left},
                        "right": {"field": right_name, "value_c": right},
                    },
                )
            )
    if p_lim1 is not None:
        if not isinstance(p_lim1, (int, float)) or isinstance(p_lim1, bool) or p_lim1 < 0:
            findings.append(
                finding(
                    "INVERTER_TEMPERATURE_LIMIT_POWER_INVALID",
                    "error",
                    "derating",
                    "Temperature-derating limit power must be nonnegative.",
                    field_path="temperature_derating_model.limit1_power_w",
                    measured_value=p_lim1,
                    unit="W",
                )
            )
        elif _positive(max_ac) and p_lim1 > max_ac:
            findings.append(
                finding(
                    "INVERTER_TEMPERATURE_LIMIT_POWER_ABOVE_MAX_AC",
                    "error",
                    "derating",
                    "Temperature-derating limit power must not exceed maximum AC power.",
                    field_path="temperature_derating_model.limit1_power_w",
                    measured_value=p_lim1,
                    limit_value=max_ac,
                    unit="W",
                )
            )

    efficiency = data.get("efficiency_model") or {}
    model_type = efficiency.get("model_type")
    if model_type == "constant":
        value = efficiency.get("efficiency_fraction")
        if value is not None and not (0 < value <= 1):
            findings.append(
                finding(
                    "INVERTER_EFFICIENCY_OUT_OF_RANGE",
                    "error",
                    "efficiency",
                    "Inverter efficiency must satisfy 0 < efficiency <= 1.",
                    field_path="efficiency_model.efficiency_fraction",
                    measured_value=value,
                    limit_value=1.0,
                    unit="fraction",
                )
            )

    metrics = efficiency.get("reference_metrics") or {}
    for key in (
        "max_efficiency_fraction",
        "european_efficiency_fraction",
        "cec_efficiency_fraction",
    ):
        value = metrics.get(key)
        if value is not None and not (0 <= value <= 1):
            findings.append(
                finding(
                    "INVERTER_EFFICIENCY_REFERENCE_METRIC_OUT_OF_RANGE",
                    "error",
                    "efficiency",
                    "Efficiency reference metrics must satisfy 0 <= efficiency <= 1.",
                    field_path=f"efficiency_model.reference_metrics.{key}",
                    measured_value=value,
                    limit_value=1.0,
                    unit="fraction",
                )
            )

    curves = efficiency.get("curves") or []
    previous_voltage = None
    for curve_index, curve in enumerate(curves):
        curve_voltage = curve.get("dc_voltage_v") if isinstance(curve, dict) else None
        if curve_voltage is not None:
            if not _positive(curve_voltage):
                findings.append(
                    finding(
                        "INVERTER_EFFICIENCY_CURVE_VOLTAGE_NONPOSITIVE",
                        "error",
                        "efficiency",
                        "Efficiency-curve DC voltage must be greater than zero.",
                        field_path=f"efficiency_model.curves[{curve_index}].dc_voltage_v",
                        measured_value=curve_voltage,
                        unit="V",
                    )
                )
            if previous_voltage is not None and curve_voltage <= previous_voltage:
                findings.append(
                    finding(
                        "INVERTER_EFFICIENCY_CURVE_VOLTAGES_NOT_INCREASING",
                        "error",
                        "efficiency",
                        "Efficiency-curve voltage anchors must be strictly increasing.",
                        field_path="efficiency_model.curves",
                    )
                )
            previous_voltage = curve_voltage
        points = curve.get("points") if isinstance(curve, dict) else None
        if not points:
            continue
        previous_input = None
        for point_index, point in enumerate(points):
            pdc = point.get("dc_power_w")
            pac = point.get("ac_power_w")
            eta = point.get("efficiency_fraction")
            if pdc is not None:
                if pdc < 0:
                    findings.append(
                        finding(
                            "INVERTER_EFFICIENCY_NEGATIVE_INPUT_POWER",
                            "error",
                            "efficiency",
                            "Efficiency-curve DC input power cannot be negative.",
                            field_path=f"efficiency_model.curves[{curve_index}].points[{point_index}]",
                            measured_value=pdc,
                            unit="W",
                        )
                    )
                if previous_input is not None and pdc <= previous_input:
                    findings.append(
                        finding(
                            "INVERTER_EFFICIENCY_INPUT_AXIS_NOT_STRICTLY_INCREASING",
                            "error",
                            "efficiency",
                            "Efficiency-curve input power must be strictly increasing within a curve.",
                            field_path=f"efficiency_model.curves[{curve_index}]",
                        )
                    )
                previous_input = pdc
            if pac is not None:
                if pac < 0:
                    findings.append(
                        finding(
                            "INVERTER_EFFICIENCY_NEGATIVE_OUTPUT_POWER",
                            "error",
                            "efficiency",
                            "Efficiency-curve AC output power cannot be negative.",
                            field_path=f"efficiency_model.curves[{curve_index}].points[{point_index}]",
                            measured_value=pac,
                            unit="W",
                        )
                    )
                if pdc is not None and pac > pdc:
                    findings.append(
                        finding(
                            "INVERTER_EFFICIENCY_OUTPUT_ABOVE_INPUT",
                            "error",
                            "efficiency",
                            "Efficiency-curve AC output power cannot exceed DC input power.",
                            field_path=f"efficiency_model.curves[{curve_index}].points[{point_index}]",
                            context={"dc_power_w": pdc, "ac_power_w": pac},
                        )
                    )
            if eta is not None and not (0 <= eta <= 1):
                findings.append(
                    finding(
                        "INVERTER_EFFICIENCY_OUT_OF_RANGE",
                        "error",
                        "efficiency",
                        "Efficiency-curve values must satisfy 0 <= efficiency <= 1.",
                        field_path=f"efficiency_model.curves[{curve_index}].points[{point_index}].efficiency_fraction",
                        measured_value=eta,
                        limit_value=1.0,
                        unit="fraction",
                    )
                )

    return findings


def inverter_capabilities(
    data: dict[str, Any],
    findings: Iterable[dict[str, Any]],
) -> dict[str, bool]:
    """Evaluate inverter capabilities without making refinement data mandatory.

    Design validation and energy simulation are intentionally separate. A missing physical
    MPPT current limit blocks current-limit design checks, but it does not block a lower-
    fidelity energy simulation when voltage range, AC rating, and an efficiency model exist.
    """
    findings = list(findings)
    identity_ok = bool(data.get("manufacturer")) and bool(data.get("model"))
    has_source = bool(data.get("source_ids"))

    dc_max = _get(data, "dc_limits", "max_dc_voltage_v")
    ac_power = _get(data, "ac_limits", "nominal_ac_power_w")
    ac_voltage = _get(data, "ac_limits", "nominal_ac_voltage_v")
    phase = data.get("phase_configuration")

    template = data.get("mppt_template") or {}
    min_v = template.get("min_operating_voltage_v")
    max_v = template.get("max_operating_voltage_v")
    count = template.get("count")
    op_current = template.get("max_operating_current_a")

    mppt_core = (
        (_positive(min_v) or min_v == 0)
        and _positive(max_v)
        and isinstance(count, int)
        and count > 0
    )
    mppt_voltage_ready = (
        identity_ok
        and _positive(dc_max)
        and mppt_core
        and not any(
            f["severity"] in ERROR_SEVERITIES and f["category"] in {"mppt", "dc"}
            for f in findings
        )
    )
    mppt_current_limit_ready = mppt_voltage_ready and _positive(op_current)
    mppt_design_ready = mppt_current_limit_ready

    ac_design_core = (
        _positive(ac_power)
        and _positive(ac_voltage)
        and phase in {"single_phase", "three_phase", "other"}
    )
    basic_design_ready = (
        mppt_design_ready
        and ac_design_core
        and has_source
        and not any(
            f["severity"] in ERROR_SEVERITIES and f["category"] in {"identity", "ac"}
            for f in findings
        )
    )

    efficiency = data.get("efficiency_model") or {}
    supported_efficiency_model = efficiency.get("model_type") in {
        "constant",
        "one_dimensional_curve",
        "voltage_dependent_curves",
        "sandia",
        "pvwatts",
        "custom",
    }
    efficiency_errors = any(
        f["severity"] in ERROR_SEVERITIES and f["category"] == "efficiency"
        for f in findings
    )

    # Yield readiness deliberately does not require a physical MPPT current limit.
    # If that limit is absent, current clipping is an unsupported refinement and must
    # be disclosed in the simulation configuration/report rather than fabricated.
    basic_yield_ready = (
        identity_ok
        and has_source
        and mppt_voltage_ready
        and _positive(ac_power)
        and supported_efficiency_model
        and not efficiency_errors
        and not any(
            f["severity"] in ERROR_SEVERITIES and f["category"] in {"identity", "ac"}
            for f in findings
        )
    )

    detailed_efficiency_ready = (
        basic_yield_ready
        and efficiency.get("model_type") in {
            "one_dimensional_curve",
            "voltage_dependent_curves",
        }
        and bool(efficiency.get("curves"))
    )

    sizing = data.get("array_sizing_limits") or {}
    array_sizing_ready = any(
        _positive(sizing.get(key))
        for key in (
            "nominal_pv_array_power_w",
            "max_pv_array_power_w",
            "max_pv_current_a",
        )
    )

    derating_model = data.get("temperature_derating_model") or {}
    derating_ready = bool(
        derating_model
        and derating_model.get("max_power_temperature_c") is not None
        and derating_model.get("nominal_power_temperature_c") is not None
        and derating_model.get("limit1_temperature_c") is not None
        and derating_model.get("limit1_power_w") is not None
    ) or bool(data.get("temperature_derating_curve") or data.get("altitude_derating_curve"))

    return {
        "mppt_voltage_ready": mppt_voltage_ready,
        "mppt_current_limit_ready": mppt_current_limit_ready,
        "mppt_design_ready": mppt_design_ready,
        "basic_design_ready": basic_design_ready,
        "basic_yield_ready": basic_yield_ready,
        "detailed_efficiency_ready": detailed_efficiency_ready,
        "array_sizing_ready": array_sizing_ready,
        "derating_ready": derating_ready,
    }

