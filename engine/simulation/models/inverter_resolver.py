"""Progressive inverter-model resolver."""

from __future__ import annotations

from typing import Any

from components.validation import inverter_capabilities, validate_inverter

from .assumptions import assumption, enabled_refinement, unavailable_refinement
from .registry import (
    INVERTER_CONSTANT,
    INVERTER_MODELS,
    INVERTER_ONE_DIMENSIONAL_CURVE,
    INVERTER_VOLTAGE_CURVES,
    INVERTER_VOLTAGE_CURVES_BOUNDED,
)


def _component_id(inverter: dict[str, Any]) -> str | None:
    return inverter.get("inverter_definition_id")


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _mppt_voltage_ready(inverter: dict[str, Any]) -> bool:
    max_dc = (inverter.get("dc_limits") or {}).get("max_dc_voltage_v")
    template = inverter.get("mppt_template")
    if isinstance(template, dict):
        return (
            _positive(max_dc)
            and isinstance(template.get("count"), int)
            and template.get("count") > 0
            and isinstance(template.get("min_operating_voltage_v"), (int, float))
            and template.get("min_operating_voltage_v") >= 0
            and _positive(template.get("max_operating_voltage_v"))
        )

    mppts = inverter.get("mppts") or []
    return bool(mppts) and _positive(max_dc) and all(
        isinstance(item.get("min_operating_voltage_v"), (int, float))
        and item.get("min_operating_voltage_v") >= 0
        and _positive(item.get("max_operating_voltage_v"))
        for item in mppts
    )


def _current_limit_paths(inverter: dict[str, Any]) -> list[str]:
    template = inverter.get("mppt_template")
    if isinstance(template, dict) and _positive(template.get("max_operating_current_a")):
        return ["mppt_template.max_operating_current_a"]

    mppts = inverter.get("mppts") or []
    if mppts and all(_positive(item.get("max_operating_current_a")) for item in mppts):
        return [f"mppts[{index}].max_operating_current_a" for index, _ in enumerate(mppts)]
    return []


def _efficiency_eligibility(inverter: dict[str, Any]) -> dict[str, dict[str, Any]]:
    efficiency = inverter.get("efficiency_model") or {}
    model_type = efficiency.get("model_type")
    eligible: dict[str, dict[str, Any]] = {}

    if model_type == "voltage_dependent_curves" and efficiency.get("curves"):
        eligible[INVERTER_VOLTAGE_CURVES.model_id] = {
            "descriptor": INVERTER_VOLTAGE_CURVES,
            "parameter_source_path": "efficiency_model.curves",
        }
        # Equal rank and legacy-first insertion preserve the existing auto-selection.
        eligible[INVERTER_VOLTAGE_CURVES_BOUNDED.model_id] = {
            "descriptor": INVERTER_VOLTAGE_CURVES_BOUNDED,
            "parameter_source_path": "efficiency_model.curves",
        }
    elif model_type == "one_dimensional_curve" and efficiency.get("curves"):
        eligible[INVERTER_ONE_DIMENSIONAL_CURVE.model_id] = {
            "descriptor": INVERTER_ONE_DIMENSIONAL_CURVE,
            "parameter_source_path": "efficiency_model.curves",
        }
    elif (
        model_type == "constant"
        and isinstance(efficiency.get("efficiency_fraction"), (int, float))
        and 0 < efficiency.get("efficiency_fraction") <= 1
    ):
        eligible[INVERTER_CONSTANT.model_id] = {
            "descriptor": INVERTER_CONSTANT,
            "parameter_source_path": "efficiency_model.efficiency_fraction",
        }
    return eligible


def _base_missing_fields(inverter: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not inverter.get("source_ids"):
        missing.append("source_ids")
    if not _positive((inverter.get("ac_limits") or {}).get("nominal_ac_power_w")):
        missing.append("ac_limits.nominal_ac_power_w")
    if not _mppt_voltage_ready(inverter):
        missing.extend(
            [
                "dc_limits.max_dc_voltage_v",
                "mppt_template/mppts voltage domain",
            ]
        )
    if not _efficiency_eligibility(inverter):
        missing.append("supported executable efficiency_model")
    return list(dict.fromkeys(missing))


def resolve_inverter_model(
    inverter: dict[str, Any],
    *,
    resolution_id: str,
    requested_model_id: str | None = None,
    required_refinements: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve inverter conversion and independent optional refinements."""
    findings = validate_inverter(inverter)
    capabilities = inverter_capabilities(inverter, findings)
    eligible = _efficiency_eligibility(inverter)

    assumptions: list[dict[str, Any]] = []
    warnings: list[str] = []
    status = "resolved"
    selected: dict[str, Any] | None = None

    efficiency = inverter.get("efficiency_model") or {}
    declared_type = efficiency.get("model_type")
    if declared_type in {"sandia", "pvwatts", "custom"}:
        message = (
            f"Inverter declares {declared_type!r}, but Phase 1 has no frozen executable "
            "parameter contract for that model type."
        )
        warnings.append(message)
        assumptions.append(
            assumption(
                f"{resolution_id}:unsupported-inverter-model",
                kind="unsupported_model",
                scope="inverter",
                statement=message,
                basis="OpenSIMPV Phase-1 model registry",
                severity="warning",
                source_paths=["efficiency_model"],
                affects=["inverter_model_selection"],
            )
        )

    if _base_missing_fields(inverter):
        eligible = {}

    if requested_model_id is not None:
        if requested_model_id not in INVERTER_MODELS:
            status = "blocked"
            assumptions.append(
                assumption(
                    f"{resolution_id}:unknown-requested-inverter-model",
                    kind="explicit_requirement",
                    scope="inverter",
                    statement=(
                        f"Requested inverter model {requested_model_id!r} is not registered."
                    ),
                    basis="explicit user/simulation configuration request",
                    severity="blocking",
                    affects=["inverter_model_selection"],
                )
            )
        elif requested_model_id not in eligible:
            status = "blocked"
            assumptions.append(
                assumption(
                    f"{resolution_id}:unavailable-requested-inverter-model",
                    kind="explicit_requirement",
                    scope="inverter",
                    statement=(
                        f"Requested inverter model {requested_model_id!r} cannot be justified "
                        "from the available canonical data."
                    ),
                    basis="explicit user/simulation configuration request",
                    severity="blocking",
                    affects=["inverter_model_selection"],
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
            "component_model_version": None,
            "parameter_source_path": selected["parameter_source_path"],
            "validation_status": "engineering_validated_inputs",
        }
        assumptions.append(
            assumption(
                f"{resolution_id}:inverter-model-selection",
                kind="model_selection",
                scope="inverter",
                statement=f"Selected {descriptor.model_id}.",
                basis=(
                    "explicit requested model"
                    if requested_model_id is not None
                    else "highest-fidelity eligible registered model"
                ),
                source_paths=[selected["parameter_source_path"]],
                affects=["inverter_conversion_model"],
            )
        )
        if descriptor.model_id == INVERTER_CONSTANT.model_id:
            assumptions.append(
                assumption(
                    f"{resolution_id}:inverter-basic-fallback",
                    kind="fallback",
                    scope="inverter",
                    statement=(
                        "Only an explicit constant-efficiency conversion model is available; "
                        "load/voltage-dependent efficiency refinement is unavailable."
                    ),
                    basis="progressive-fidelity policy",
                    severity="warning",
                    source_paths=["efficiency_model.efficiency_fraction"],
                    affects=["inverter_conversion_model", "conversion_loss_fidelity"],
                )
            )
    else:
        selected_model = None
        missing = _base_missing_fields(inverter)
        assumptions.append(
            assumption(
                f"{resolution_id}:inverter-resolution-blocked",
                kind="limitation",
                scope="inverter",
                statement=(
                    "No registered inverter energy-conversion model can be justified from "
                    "the available canonical data."
                ),
                basis="OpenSIMPV Phase-1 model registry and component validation",
                severity="blocking",
                source_paths=missing,
                affects=["inverter_conversion_model", "energy_simulation"],
            )
        )

    enabled: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []

    current_paths = _current_limit_paths(inverter)
    if current_paths:
        enabled.append(
            enabled_refinement(
                "mppt_current_limit",
                model_id="inverter.mppt_current_limit.v0.1",
                source_paths=current_paths,
                notes="Physical operating-current limit is available for current clipping.",
            )
        )
    else:
        unavailable.append(
            unavailable_refinement(
                "mppt_current_limit",
                reason_code="PHYSICAL_MPPT_CURRENT_LIMIT_UNAVAILABLE",
                consequence=(
                    "MPPT current clipping cannot be evaluated; voltage/efficiency-based "
                    "energy conversion may still proceed."
                ),
                missing_fields=[
                    "mppt_template.max_operating_current_a or per-MPPT equivalent"
                ],
            )
        )
        assumptions.append(
            assumption(
                f"{resolution_id}:missing-current-limit",
                kind="missing_refinement",
                scope="inverter",
                statement=(
                    "Physical MPPT operating-current limit is unavailable. Do not infer it "
                    "from contractual PV-array current fields."
                ),
                basis="progressive-fidelity policy",
                severity="warning",
                source_paths=["mppt_template", "mppts", "array_sizing_limits"],
                affects=["mppt_current_clipping", "current_limit_design_check"],
            )
        )

    derating = inverter.get("temperature_derating_model") or {}
    if (
        derating.get("max_power_temperature_c") is not None
        and derating.get("nominal_power_temperature_c") is not None
        and derating.get("limit1_temperature_c") is not None
        and derating.get("limit1_power_w") is not None
    ):
        enabled.append(
            enabled_refinement(
                "temperature_derating",
                model_id="inverter.temperature_power_limit.v0.1",
                source_paths=["temperature_derating_model"],
                notes=(
                    "Component derating breakpoints are available; runtime temperature basis "
                    "must still be selected explicitly if stored as unknown."
                ),
            )
        )
        if derating.get("temperature_basis") in {None, "unknown"}:
            assumptions.append(
                assumption(
                    f"{resolution_id}:derating-temperature-basis",
                    kind="limitation",
                    scope="inverter",
                    statement=(
                        "Temperature derating data are available, but the component does not "
                        "fix the runtime temperature basis. Simulation configuration must "
                        "resolve that basis before applying derating."
                    ),
                    basis="component temperature_derating_model",
                    severity="warning",
                    source_paths=["temperature_derating_model.temperature_basis"],
                    affects=["temperature_derating"],
                )
            )
    else:
        unavailable.append(
            unavailable_refinement(
                "temperature_derating",
                reason_code="TEMPERATURE_DERATING_DATA_UNAVAILABLE",
                consequence=(
                    "Temperature-dependent AC power derating cannot be applied unless another "
                    "source or simulation override supplies the model."
                ),
                missing_fields=["temperature_derating_model"],
            )
        )

    thresholds = inverter.get("operating_thresholds") or {}
    night_loss = thresholds.get("night_loss_w")
    if isinstance(night_loss, (int, float)) and night_loss >= 0:
        enabled.append(
            enabled_refinement(
                "night_loss",
                model_id="inverter.night_loss_constant_w.v0.1",
                source_paths=["operating_thresholds.night_loss_w"],
            )
        )
    else:
        unavailable.append(
            unavailable_refinement(
                "night_loss",
                reason_code="NIGHT_LOSS_UNAVAILABLE",
                consequence=(
                    "No night self-consumption term is justified from component data. A later "
                    "simulation configuration may supply an explicit override."
                ),
                missing_fields=["operating_thresholds.night_loss_w"],
            )
        )

    startup_paths = [
        path
        for path, value in (
            ("operating_thresholds.minimum_input_power_w", thresholds.get("minimum_input_power_w")),
            ("operating_thresholds.startup_power_w", thresholds.get("startup_power_w")),
        )
        if isinstance(value, (int, float)) and value >= 0
    ]
    if startup_paths:
        enabled.append(
            enabled_refinement(
                "startup_threshold",
                model_id="inverter.startup_threshold.v0.1",
                source_paths=startup_paths,
            )
        )
    else:
        unavailable.append(
            unavailable_refinement(
                "startup_threshold",
                reason_code="STARTUP_THRESHOLD_UNAVAILABLE",
                consequence="Low-power startup behavior cannot be refined from component data.",
                missing_fields=[
                    "operating_thresholds.minimum_input_power_w or startup_power_w"
                ],
            )
        )

    required_refinements = required_refinements or set()
    available_ids = {item["refinement_id"] for item in enabled}
    missing_required = sorted(required_refinements - available_ids)
    if missing_required:
        status = "blocked"
        assumptions.append(
            assumption(
                f"{resolution_id}:required-refinement-unavailable",
                kind="explicit_requirement",
                scope="inverter",
                statement=(
                    "Explicitly required inverter refinements are unavailable: "
                    + ", ".join(missing_required)
                ),
                basis="explicit user/simulation configuration request",
                severity="blocking",
                affects=missing_required,
            )
        )

    return {
        "schema_name": "ResolvedComponentModel",
        "schema_version": "0.1",
        "resolution_id": resolution_id,
        "component_type": "inverter",
        "component_definition_id": _component_id(inverter),
        "component_revision_id": inverter.get("revision_id"),
        "status": status,
        "requested_model_id": requested_model_id,
        "selected_model": selected_model,
        "enabled_refinements": enabled,
        "unavailable_refinements": unavailable,
        "assumptions": assumptions,
        "warnings": warnings,
        "source_ids": list(inverter.get("source_ids") or []),
        "capability_snapshot": capabilities,
    }
