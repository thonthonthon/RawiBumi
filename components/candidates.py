"""Canonical component candidate builders.

A candidate is not automatically a published/active component revision. It is a wrapper
around partial or complete canonical data plus:
- explicit derivations;
- engineering validation findings;
- capability flags;
- final-definition schema readiness.

No missing value is fabricated merely to make a schema pass.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from components.mapping import SemanticMappingResult
from components.ond.semantics import SINGLE_PROFILE_WARNING, assemble_inverter_semantics
from components.pan.pvsyst_sdm import (
    complete_parameter_set,
    validate_at_stc,
    validate_off_stc_matrix,
)
from components.pan.semantics import assemble_module_semantics
from components.validation import (
    ValidationConfig,
    inverter_capabilities,
    module_capabilities,
    pvsyst_sdm_readiness,
    validate_inverter,
    validate_module,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE_SCHEMA_PATH = ROOT / "components/schema/module-definition.schema.json"
INVERTER_SCHEMA_PATH = ROOT / "components/schema/inverter-definition.schema.json"


def _set_nested(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    current = data
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _extract_pvsyst_model_values(values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    ordinary: dict[str, Any] = {}
    parameters: dict[str, Any] = {}
    prefix = "electrical_models[pvsyst_singlediode].parameter_set."

    for path, value in values.items():
        if path.startswith(prefix):
            parameters[path[len(prefix) :]] = value
        else:
            ordinary[path] = value
    return ordinary, parameters


def _definition_schema_ready(data: dict[str, Any], schema_path: Path) -> tuple[bool, list[str]]:
    import json

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda err: list(err.absolute_path))
    return not errors, [error.message for error in errors]


def _candidate_status(
    schema_ready: bool,
    findings: list[dict[str, Any]],
) -> str:
    if any(item["severity"] == "blocking_error" for item in findings):
        return "needs_review"
    if schema_ready and not any(item["severity"] == "error" for item in findings):
        return "schema_ready"
    return "needs_review"


def build_module_candidate(
    mapping: SemanticMappingResult,
    *,
    candidate_id: str,
    module_definition_id: str,
    revision_id: str,
    source_id: str | None = None,
    validation_config: ValidationConfig | None = None,
) -> dict[str, Any]:
    values, sdm_parameters = _extract_pvsyst_model_values(mapping.values_by_canonical_path)
    gamma_pmp_relative = values.pop(
        "temperature_coefficients.gamma_pmp_relative_per_c", None
    )

    data: dict[str, Any] = {
        "schema_name": "ModuleDefinition",
        "schema_version": "0.1",
        "module_definition_id": module_definition_id,
        "revision_id": revision_id,
        "verification_state": "source_attached" if source_id else "unverified",
        "source_ids": [source_id] if source_id else [],
    }

    for path, value in values.items():
        _set_nested(data, path, deepcopy(value))

    data, pan_derivations, pan_semantic_warnings = assemble_module_semantics(
        data,
        source_id=source_id,
    )
    derivations: list[dict[str, Any]] = list(pan_derivations)
    stc = data.get("stc") or {}
    if stc.get("pmp_w") is None and stc.get("vmp_v") is not None and stc.get("imp_a") is not None:
        pmp = float(stc["vmp_v"]) * float(stc["imp_a"])
        stc["pmp_w"] = pmp
        data["stc"] = stc
        derivations.append(
            {
                "target_path": "stc.pmp_w",
                "method": "multiply_vmp_by_imp",
                "algorithm_version": "0.1",
                "inputs": {"stc.vmp_v": stc["vmp_v"], "stc.imp_a": stc["imp_a"]},
                "value": pmp,
                "unit": "W",
                "estimated": False,
                "notes": (
                    "Calculated reference MPP power from mapped Vmp and Imp. This is kept "
                    "separate from commercial/nameplate nominal_power_w."
                ),
            }
        )

    coefficients = data.get("temperature_coefficients") or {}
    if gamma_pmp_relative is not None and stc.get("pmp_w") is not None:
        gamma_absolute = float(gamma_pmp_relative) * float(stc["pmp_w"])
        coefficients["gamma_pmp_per_c"] = gamma_absolute
        derivations.append(
            {
                "target_path": "temperature_coefficients.gamma_pmp_per_c",
                "method": "relative_pmp_temperature_coefficient_to_absolute",
                "algorithm_version": "0.1",
                "inputs": {
                    "gamma_pmp_relative_per_c": gamma_pmp_relative,
                    "stc.pmp_w": stc["pmp_w"],
                },
                "value": gamma_absolute,
                "unit": "W/K",
                "estimated": False,
                "notes": "Converted source %/K coefficient to canonical absolute W/K.",
            }
        )
    if all(
        coefficients.get(key) is not None
        for key in ("alpha_isc_per_c", "beta_voc_per_c", "gamma_pmp_per_c")
    ):
        coefficients["coefficient_basis"] = "absolute"
    if coefficients:
        data["temperature_coefficients"] = coefficients

    stc_validation = None
    off_stc_validation = None
    model_validation_passed = False
    sdm_readiness = {"passed": False, "readiness_tolerances": [], "finding": None}
    model_warnings: list[str] = []
    if sdm_parameters:
        completed_parameters, model_derivations, model_warnings = complete_parameter_set(
            data, sdm_parameters
        )
        derivations.extend(model_derivations)
        stc_validation = validate_at_stc(data, completed_parameters)
        off_stc_validation = validate_off_stc_matrix(data, completed_parameters)
        sdm_readiness = pvsyst_sdm_readiness({"stc": stc_validation, "off_stc": off_stc_validation})
        model_validation_passed = sdm_readiness["passed"]
        combined_status = sdm_readiness["status"]
        data["electrical_models"] = [
            {
                "model_type": "pvsyst_singlediode",
                "model_version": "pvsyst_v6",
                "parameter_set": completed_parameters,
                "readiness_tolerances": sdm_readiness["readiness_tolerances"],
                "source_ids": [source_id] if source_id else [],
                "verification_state": (
                    "auto_validated"
                    if model_validation_passed
                    else ("source_attached" if source_id else "unverified")
                ),
                "validation": {
                    "status": combined_status,
                    "passed": model_validation_passed,
                    "stc": stc_validation,
                    "off_stc": off_stc_validation,
                },
            }
        ]

    findings = validate_module(data, config=validation_config)

    for warning in pan_semantic_warnings:
        findings.append(
            {
                "rule_id": "MODULE_PAN_SEMANTIC_ASSEMBLY_WARNING",
                "severity": "warning",
                "category": "semantic_mapping",
                "field_path": None,
                "message": warning,
                "measured_value": None,
                "limit_value": None,
                "unit": None,
                "context": {},
            }
        )

    for warning in model_warnings:
        findings.append(
            {
                "rule_id": "MODULE_SDM_PARAMETER_COMPLETION_WARNING",
                "severity": "warning",
                "category": "electrical_model",
                "field_path": "electrical_models.pvsyst_singlediode",
                "message": warning,
                "measured_value": None,
                "limit_value": None,
                "unit": None,
                "context": {},
            }
        )

    if stc_validation is not None:
        status = stc_validation.get("status")
        if status == "failed":
            findings.append(
                {
                    "rule_id": "MODULE_SDM_STC_VALIDATION_FAILED",
                    "severity": "error",
                    "category": "electrical_model",
                    "field_path": "electrical_models.pvsyst_singlediode.validation.stc",
                    "message": "PVsyst single-diode model did not reproduce all source STC points within tolerance.",
                    "measured_value": None,
                    "limit_value": stc_validation.get("point_relative_tolerance"),
                    "unit": "fraction",
                    "context": {"residuals": stc_validation.get("residuals", {})},
                }
            )
        elif status in {"incomplete", "unavailable"}:
            findings.append(
                {
                    "rule_id": "MODULE_SDM_STC_VALIDATION_INCOMPLETE",
                    "severity": "warning",
                    "category": "electrical_model",
                    "field_path": "electrical_models.pvsyst_singlediode.validation.stc",
                    "message": (
                        "PVsyst single-diode STC validation could not be completed; "
                        f"status={status}."
                    ),
                    "measured_value": None,
                    "limit_value": None,
                    "unit": None,
                    "context": {
                        "missing_parameters": stc_validation.get("missing_parameters", []),
                        "error": stc_validation.get("error"),
                    },
                }
            )

    if off_stc_validation is not None:
        status = off_stc_validation.get("status")
        if sdm_readiness["finding"] is not None:
            findings.append(sdm_readiness["finding"])
        elif status == "failed":
            findings.append(
                {
                    "rule_id": "MODULE_SDM_OFF_STC_VALIDATION_FAILED",
                    "severity": "error",
                    "category": "electrical_model",
                    "field_path": "electrical_models.pvsyst_singlediode.validation.off_stc",
                    "message": (
                        "PVsyst single-diode model failed the off-STC matrix, trend, "
                        "or temperature-coefficient consistency checks."
                    ),
                    "measured_value": None,
                    "limit_value": None,
                    "unit": None,
                    "context": {
                        "point_check_summary": off_stc_validation.get("point_check_summary", {}),
                        "trend_check_summary": off_stc_validation.get("trend_check_summary", {}),
                        "coefficient_check_summary": off_stc_validation.get("coefficient_check_summary", {}),
                    },
                }
            )
        elif status in {"incomplete", "unavailable"}:
            findings.append(
                {
                    "rule_id": "MODULE_SDM_OFF_STC_VALIDATION_INCOMPLETE",
                    "severity": "warning",
                    "category": "electrical_model",
                    "field_path": "electrical_models.pvsyst_singlediode.validation.off_stc",
                    "message": (
                        "PVsyst single-diode off-STC validation could not be completed; "
                        f"status={status}."
                    ),
                    "measured_value": None,
                    "limit_value": None,
                    "unit": None,
                    "context": {
                        "missing_parameters": off_stc_validation.get("missing_parameters", []),
                        "missing_source_coefficients": off_stc_validation.get(
                            "missing_source_coefficients", []
                        ),
                        "error": off_stc_validation.get("error"),
                    },
                }
            )
    capabilities = module_capabilities(
        data,
        findings,
        model_validation_passed=model_validation_passed,
    )
    data["capability_flags"] = capabilities

    schema_ready, schema_errors = _definition_schema_ready(data, MODULE_SCHEMA_PATH)
    for message in schema_errors:
        findings.append(
            {
                "rule_id": "MODULE_DEFINITION_SCHEMA_INCOMPLETE",
                "severity": "warning",
                "category": "schema",
                "field_path": None,
                "message": message,
                "measured_value": None,
                "limit_value": None,
                "unit": None,
                "context": {},
            }
        )

    return {
        "schema_name": "ComponentCandidate",
        "schema_version": "0.1",
        "candidate_id": candidate_id,
        "component_type": "module",
        "source_id": source_id,
        "canonical_data": data,
        "derivations": derivations,
        "validation_findings": findings,
        "capability_flags": capabilities,
        "definition_schema_ready": schema_ready,
        "status": _candidate_status(schema_ready, findings),
    }

def build_inverter_candidate(
    mapping: SemanticMappingResult,
    *,
    candidate_id: str,
    inverter_definition_id: str,
    revision_id: str,
    source_id: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_name": "InverterDefinition",
        "schema_version": "0.1",
        "inverter_definition_id": inverter_definition_id,
        "revision_id": revision_id,
        "verification_state": "source_attached" if source_id else "unverified",
        "source_ids": [source_id] if source_id else [],
    }

    for path, value in mapping.values_by_canonical_path.items():
        _set_nested(data, path, deepcopy(value))

    data, derivations, semantic_warnings = assemble_inverter_semantics(data)

    findings = validate_inverter(data)
    for warning in semantic_warnings:
        findings.append(
            {
                "rule_id": (
                    "INVERTER_SINGLE_EFFICIENCY_CURVE" if warning == SINGLE_PROFILE_WARNING
                    else "INVERTER_OND_SEMANTIC_ASSEMBLY_WARNING"
                ),
                "severity": "warning",
                "category": "semantic_mapping",
                "field_path": None,
                "message": warning,
                "measured_value": None,
                "limit_value": None,
                "unit": None,
                "context": {},
            }
        )

    capabilities = inverter_capabilities(data, findings)
    data["capability_flags"] = capabilities

    schema_ready, schema_errors = _definition_schema_ready(data, INVERTER_SCHEMA_PATH)
    for message in schema_errors:
        findings.append(
            {
                "rule_id": "INVERTER_DEFINITION_SCHEMA_INCOMPLETE",
                "severity": "warning",
                "category": "schema",
                "field_path": None,
                "message": message,
                "measured_value": None,
                "limit_value": None,
                "unit": None,
                "context": {},
            }
        )

    return {
        "schema_name": "ComponentCandidate",
        "schema_version": "0.1",
        "candidate_id": candidate_id,
        "component_type": "inverter",
        "source_id": source_id,
        "canonical_data": data,
        "derivations": derivations,
        "validation_findings": findings,
        "capability_flags": capabilities,
        "definition_schema_ready": schema_ready,
        "status": _candidate_status(schema_ready, findings),
    }

def finalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return an automatically validated canonical definition when safe to do so.

    Finalization is blocked if:
    - the canonical definition does not satisfy its JSON Schema; or
    - engineering validation contains an error/blocking_error.

    Capability flags remain separate: a finalized component can still be layout-ready only.
    """

    if not candidate.get("definition_schema_ready"):
        raise ValueError("candidate is not definition-schema ready")

    blockers = [
        item
        for item in candidate.get("validation_findings", [])
        if item.get("severity") in {"error", "blocking_error"}
    ]
    if blockers:
        raise ValueError("candidate has engineering validation errors")

    data = deepcopy(candidate["canonical_data"])
    data["verification_state"] = "auto_validated"
    return data
