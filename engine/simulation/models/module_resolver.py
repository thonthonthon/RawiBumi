"""Progressive module-model resolver."""

from __future__ import annotations

from typing import Any

from components.validation import module_capabilities, validate_module

from .assumptions import assumption, enabled_refinement, unavailable_refinement
from .registry import MODULE_MODELS, MODULE_PVSYST_SDM, MODULE_STC_TEMPCO


TRUSTED_MODEL_STATES = {"auto_validated", "reviewed", "manufacturer_verified"}


def _component_id(module: dict[str, Any]) -> str | None:
    return module.get("module_definition_id")


def _pvsyst_model(module: dict[str, Any]) -> dict[str, Any] | None:
    for model in module.get("electrical_models") or []:
        if model.get("model_type") != "pvsyst_singlediode":
            continue
        validation = model.get("validation") or {}
        if validation.get("passed") is True:
            return model
    return None


def _basic_missing_fields(module: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    stc = module.get("stc") or {}
    for key in (
        "pmp_w",
        "voc_v",
        "isc_a",
        "vmp_v",
        "imp_a",
        "reference_irradiance_w_m2",
        "reference_cell_temperature_c",
    ):
        if stc.get(key) is None:
            missing.append(f"stc.{key}")

    coefficients = module.get("temperature_coefficients") or {}
    for key in ("alpha_isc_per_c", "beta_voc_per_c", "gamma_pmp_per_c"):
        if coefficients.get(key) is None:
            missing.append(f"temperature_coefficients.{key}")

    basis = coefficients.get("coefficient_basis")
    if basis not in {"absolute", "relative"}:
        missing.append("temperature_coefficients.coefficient_basis[absolute|relative]")

    if not module.get("source_ids"):
        missing.append("source_ids")
    return missing


def _basic_available(module: dict[str, Any], findings: list[dict[str, Any]]) -> bool:
    return not _basic_missing_fields(module) and not any(
        item["severity"] in {"error", "blocking_error"}
        and item["category"] in {"identity", "electrical", "limits"}
        for item in findings
    )


def _eligible_models(
    module: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    eligible: dict[str, dict[str, Any]] = {}

    detailed = _pvsyst_model(module)
    if detailed is not None:
        eligible[MODULE_PVSYST_SDM.model_id] = {
            "descriptor": MODULE_PVSYST_SDM,
            "parameter_source_path": "electrical_models[pvsyst_singlediode].parameter_set",
            "component_model_version": detailed.get("model_version"),
            "validation_status": (detailed.get("validation") or {}).get("status"),
        }

    if _basic_available(module, findings):
        eligible[MODULE_STC_TEMPCO.model_id] = {
            "descriptor": MODULE_STC_TEMPCO,
            "parameter_source_path": "stc + temperature_coefficients",
            "component_model_version": None,
            "validation_status": "engineering_validated_inputs",
        }

    return eligible


def resolve_module_model(
    module: dict[str, Any],
    *,
    resolution_id: str,
    requested_model_id: str | None = None,
) -> dict[str, Any]:
    """Select the highest justified module model, or block an unavailable explicit request."""
    findings = validate_module(module)
    model_validation_passed = _pvsyst_model(module) is not None
    capabilities = module_capabilities(
        module,
        findings,
        model_validation_passed=model_validation_passed,
    )
    eligible = _eligible_models(module, findings)
    assumptions: list[dict[str, Any]] = []
    warnings: list[str] = []

    unsupported_entries = sorted(
        {
            model.get("model_type")
            for model in module.get("electrical_models") or []
            if model.get("model_type")
            not in {"pvsyst_singlediode"}
        }
        - {None}
    )
    if unsupported_entries:
        warnings.append(
            "Component contains electrical model types that have no Phase-1 executable "
            f"resolution contract yet: {', '.join(unsupported_entries)}."
        )
        assumptions.append(
            assumption(
                f"{resolution_id}:unsupported-module-model",
                kind="unsupported_model",
                scope="module",
                statement=warnings[-1],
                basis="OpenSIMPV Phase-1 model registry",
                severity="warning",
                source_paths=["electrical_models"],
                affects=["module_model_selection"],
            )
        )

    selected: dict[str, Any] | None = None
    status = "resolved"

    if requested_model_id is not None:
        if requested_model_id not in MODULE_MODELS:
            status = "blocked"
            assumptions.append(
                assumption(
                    f"{resolution_id}:unknown-requested-module-model",
                    kind="explicit_requirement",
                    scope="module",
                    statement=(
                        f"Requested module model {requested_model_id!r} is not registered."
                    ),
                    basis="explicit user/simulation configuration request",
                    severity="blocking",
                    affects=["module_model_selection"],
                )
            )
        elif requested_model_id not in eligible:
            status = "blocked"
            assumptions.append(
                assumption(
                    f"{resolution_id}:unavailable-requested-module-model",
                    kind="explicit_requirement",
                    scope="module",
                    statement=(
                        f"Requested module model {requested_model_id!r} is registered but "
                        "the component does not satisfy its evidence/input requirements."
                    ),
                    basis="explicit user/simulation configuration request",
                    severity="blocking",
                    affects=["module_model_selection"],
                )
            )
        else:
            selected = eligible[requested_model_id]
    elif eligible:
        selected = max(
            eligible.values(),
            key=lambda item: item["descriptor"].fidelity_rank,
        )
    else:
        status = "blocked"

    if selected is not None:
        descriptor = selected["descriptor"]
        selected_model = {
            **descriptor.as_dict(),
            "component_model_version": selected["component_model_version"],
            "parameter_source_path": selected["parameter_source_path"],
            "validation_status": selected["validation_status"],
        }
        assumptions.append(
            assumption(
                f"{resolution_id}:module-model-selection",
                kind="model_selection",
                scope="module",
                statement=f"Selected {descriptor.model_id}.",
                basis=(
                    "explicit requested model"
                    if requested_model_id is not None
                    else "highest-fidelity eligible registered model"
                ),
                source_paths=[selected["parameter_source_path"]],
                affects=["module_dc_model"],
            )
        )
        if descriptor.model_id == MODULE_STC_TEMPCO.model_id:
            assumptions.append(
                assumption(
                    f"{resolution_id}:module-basic-fallback",
                    kind="fallback",
                    scope="module",
                    statement=(
                        "Detailed validated single-diode behavior is unavailable; use the "
                        "explicit STC/temperature-coefficient module model."
                    ),
                    basis="progressive-fidelity policy",
                    severity="warning",
                    source_paths=["stc", "temperature_coefficients"],
                    affects=["module_dc_model", "iv_curve_fidelity"],
                )
            )
    else:
        selected_model = None
        missing = _basic_missing_fields(module)
        assumptions.append(
            assumption(
                f"{resolution_id}:module-resolution-blocked",
                kind="limitation",
                scope="module",
                statement=(
                    "No registered module simulation model can be justified from the "
                    "available canonical data."
                ),
                basis="OpenSIMPV Phase-1 model registry and component validation",
                severity="blocking",
                source_paths=missing,
                affects=["module_dc_model", "energy_simulation"],
            )
        )

    enabled: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []

    bifacial = module.get("bifacial") or {}
    if (
        bifacial.get("enabled") is True
        and isinstance(bifacial.get("bifaciality_factor"), (int, float))
        and bifacial.get("bifaciality_factor") > 0
    ):
        enabled.append(
            enabled_refinement(
                "module_bifacial_response",
                model_id="module.bifaciality_factor.v0.1",
                source_paths=["bifacial.bifaciality_factor"],
                notes=(
                    "Component-side bifacial response is available; rear irradiance still "
                    "depends on the irradiance/scene model selected later."
                ),
            )
        )
    else:
        unavailable.append(
            unavailable_refinement(
                "module_bifacial_response",
                reason_code="BIFACIAL_PARAMETERS_UNAVAILABLE",
                consequence="Rear-side bifacial response cannot be applied.",
                missing_fields=["bifacial.enabled", "bifacial.bifaciality_factor"],
            )
        )

    if capabilities.get("detailed_shading_ready"):
        enabled.append(
            enabled_refinement(
                "module_electrical_shading",
                model_id="module.topology_aware_shading.v0.1",
                source_paths=["module_topology", "electrical_models"],
                notes="Component data are sufficient for a future topology-aware shading model.",
            )
        )
    else:
        unavailable.append(
            unavailable_refinement(
                "module_electrical_shading",
                reason_code="MODULE_TOPOLOGY_OR_VALIDATED_SDM_UNAVAILABLE",
                consequence=(
                    "Electrical near-shading refinement cannot use detailed module topology."
                ),
                missing_fields=["module_topology", "validated detailed electrical model"],
            )
        )

    return {
        "schema_name": "ResolvedComponentModel",
        "schema_version": "0.1",
        "resolution_id": resolution_id,
        "component_type": "module",
        "component_definition_id": _component_id(module),
        "component_revision_id": module.get("revision_id"),
        "status": status,
        "requested_model_id": requested_model_id,
        "selected_model": selected_model,
        "enabled_refinements": enabled,
        "unavailable_refinements": unavailable,
        "assumptions": assumptions,
        "warnings": warnings,
        "source_ids": list(module.get("source_ids") or []),
        "capability_snapshot": capabilities,
    }
