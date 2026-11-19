"""Phase-6.0D execution-readiness gate for the existing Phase-5 worker.

This module does not add PV physics. It exposes whether a canonical browser-authored
design lies inside the already implemented homogeneous Phase-5 execution envelope.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping

from components.design_integration import module_nameplate_w
from engine.simulation.execution_groups import build_simulation_execution_plan, standard_execution_scope_findings, execution_units, circuit_units

from .orientation_policy import OVERRIDE_NOTE, overrides as orientation_overrides, with_effective_policy
from geometry.pvfield.scene_layout import validate_scene_layout
from geometry.pvfield.packing import packing_input_hash


READINESS_VERSION = "0.1"


def _finding(
    code: str,
    message: str,
    *,
    severity: str = "blocking_error",
    entity_id: str | None = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": code,
        "severity": severity,
        "category": "execution_readiness",
        "entity_id": entity_id,
        "message": message,
        "context": dict(context or {}),
    }


def design_validation_readiness_findings(report: Mapping[str, Any], orientation_overrides: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Keep actionable validator evidence, omitting per-call identities/times. An orientation warning on an MPPT
    with an override (S14b) is silenced; remaining scope refusals still name the override."""
    findings = []
    for item in report.get("findings", []):
        if item["severity"] not in {"blocking_error", "error", "warning"}:
            continue
        if item["rule_id"] == "MPPT_ORIENTATION_MISMATCH" and str(item["entity_id"]) in (orientation_overrides or {}):
            continue
        finding = _finding(
            item["rule_id"], item["message"], severity=item["severity"],
            entity_id=item["entity_id"], context={
                "validation_category": item.get("category"),
                **{key: deepcopy(item.get(key)) for key in (
                    "classification", "measured_value", "limit_value", "unit", "context"
                )},
            },
        )
        finding["category"] = "design_validation"
        findings.append(finding)
    return findings


def _ordered_findings(findings):
    # Preserve the existing identity, deduplication and lexical ordering. The
    # new exclusion warning is always last, including after S1 geometry.
    unique = {
        (str(item["rule_id"]), item.get("entity_id"), str(item["message"])): item
        for item in findings
    }
    return sorted(unique.values(), key=lambda item: (
        item["rule_id"] == "MODULES_NOT_SIMULATED",
        str(item["rule_id"]), str(item.get("entity_id") or ""), str(item["message"]),
    ))


def _modules_not_simulated_finding(scene, electrical, definitions, plan):
    """Classify every enabled placement outside the authoritative plan union.

    Include S1-unresolved placements: topology and the plan still let us classify
    them, using execution_plan_excluded when no more specific reason applies.
    """
    simulated = {str(mid) for group in execution_units(plan)
                 for mid in group.get("module_instance_ids", [])}
    excluded = sorted(
        (module for module in scene.get("module_instances", [])
         if module.get("enabled", True) and str(module["module_instance_id"]) not in simulated),
        key=lambda module: str(module["module_instance_id"]),
    )
    if not excluded:
        return None
    strings_by_module = {}
    for string in sorted(electrical.get("strings", []), key=lambda item: str(item["string_id"])):
        for mid in string.get("module_instance_ids", []):
            strings_by_module.setdefault(str(mid), []).append(string)
    mppts = {str(item["mppt_instance_id"]): item for item in electrical.get("mppt_instances", [])}
    inverters = {str(item["inverter_instance_id"]): item for item in electrical.get("inverter_instances", [])}
    plan_errors = [item for item in plan.get("findings", []) if item["severity"] == "error"]
    reasons = {}
    plan_codes = set()
    power = 0.0
    incomplete = False
    for module in excluded:
        mid = str(module["module_instance_id"])
        strings = strings_by_module.get(mid, [])
        reason = "unstrung"
        for string in strings:
            target = string.get("target_mppt_instance_id")
            mppt = mppts.get(str(target))
            inverter = inverters.get(str((mppt or {}).get("inverter_instance_id")))
            if target is None:
                reason = "string_unassigned"
            elif string.get("enabled") is not True:
                reason = "string_disabled"
            elif mppt is None or mppt.get("enabled") is not True:
                reason = "mppt_missing_or_disabled"
            elif inverter is None or inverter.get("enabled") is not True:
                reason = "inverter_missing_or_disabled"
            else:
                reason = "execution_plan_excluded"
                ids = {mid, str(string["string_id"]), str(target), str(mppt["inverter_instance_id"])}
                related = [item for item in plan_errors
                           if str(item.get("entity_id")) in ids
                           or any(str((item.get("context") or {}).get(key)) in ids for key in (
                               "module_instance_id", "string_id", "mppt_instance_id", "inverter_instance_id"
                           ))
                           or any(ids.intersection(map(str, (item.get("context") or {}).get(key) or []))
                                  for key in ("module_instance_ids", "string_ids", "mppt_instance_ids", "inverter_instance_ids"))]
                plan_codes.update(item["code"] for item in (related or plan_errors))
            break  # Candidate strings are considered in deterministic id order.
        reasons[reason] = reasons.get(reason, 0) + 1
        definition = definitions.get(str(module.get("module_definition_revision_id")))
        stc = definition.get("stc") if isinstance(definition, Mapping) else None
        try:
            # D14: the datasheet nominal power when given, else the STC Pmp.
            pmp = module_nameplate_w(definition) if isinstance(stc, Mapping) else None
        except (KeyError, ValueError, TypeError, OverflowError):
            pmp = None
        if pmp is None or not math.isfinite(pmp) or pmp < 0:
            incomplete = True
        else:
            power += pmp
    context = {
        "module_count": len(excluded), "stc_power_w": power,
        "stc_power_incomplete": incomplete, "by_reason": dict(sorted(reasons.items())),
        "module_instance_ids": [str(module["module_instance_id"]) for module in excluded[:200]],
        "omitted_module_count": max(0, len(excluded) - 200),
    }
    if "execution_plan_excluded" in reasons:
        context["plan_finding_codes"] = sorted(plan_codes)
    return _finding(
        "MODULES_NOT_SIMULATED",
        f"{len(excluded)} placed modules ({power / 1000:.2f} kWp STC) will not be simulated: "
        + ", ".join(f"{reason}: {count}" for reason, count in sorted(reasons.items())) + ".",
        severity="warning", context=context,
    )


def phase5_module_definition_readiness(
    module: Mapping[str, Any], *, revision_id: str | None = None,
) -> dict[str, Any]:
    """Apply the existing Phase-5 module rule without a bound project."""
    revision_id = str(module.get("revision_id") or "") if revision_id is None else str(revision_id)
    findings: list[dict[str, Any]] = []
    if (module.get("capability_flags") or {}).get("detailed_sdm_ready") is not True:
        findings.append(
            _finding(
                "EXECUTION_MODULE_SDM_NOT_READY",
                (
                    f"Module revision {revision_id} is not detailed_sdm_ready "
                    "for the selected Phase-5 module model."
                ),
                entity_id=revision_id,
            )
        )
    return {"revision_id": revision_id, "ready": not findings, "findings": findings}


def phase5_inverter_definition_readiness(
    inverter: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe whether one inverter definition is executable by the current worker."""
    findings: list[dict[str, Any]] = []
    revision_id = str(inverter.get("revision_id") or "")

    if inverter.get("mppts"):
        findings.append(
            _finding(
                "EXECUTION_INVERTER_EXPLICIT_MPPTS_UNSUPPORTED",
                (
                    "The current Phase-5 worker executes the homogeneous "
                    "mppt_template contract only. Explicit mppts[] definitions are "
                    "valid canonical design data but require a topology-specific "
                    "electrical runtime."
                ),
                entity_id=revision_id or None,
            )
        )

    template = inverter.get("mppt_template")
    if not isinstance(template, Mapping):
        findings.append(
            _finding(
                "EXECUTION_INVERTER_MPPT_TEMPLATE_REQUIRED",
                "The current Phase-5 worker requires inverter mppt_template.",
                entity_id=revision_id or None,
            )
        )
    else:
        count = template.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            findings.append(
                _finding(
                    "EXECUTION_INVERTER_MPPT_TEMPLATE_INVALID",
                    "The current Phase-5 worker requires mppt_template.count >= 1.",
                    entity_id=revision_id or None,
                )
            )

    capabilities = inverter.get("capability_flags") or {}
    if capabilities.get("basic_yield_ready") is not True:
        findings.append(
            _finding(
                "EXECUTION_INVERTER_BASIC_YIELD_NOT_READY",
                "The selected inverter is not marked basic_yield_ready.",
                entity_id=revision_id or None,
            )
        )
    if capabilities.get("detailed_efficiency_ready") is not True:
        findings.append(
            _finding(
                "EXECUTION_INVERTER_EFFICIENCY_NOT_READY",
                (
                    "The selected Phase-6.0D inverter must provide the detailed "
                    "efficiency data required by the selected voltage-dependent "
                    "inverter model."
                ),
                entity_id=revision_id or None,
            )
        )

    return {
        "revision_id": revision_id,
        "ready": not findings,
        "findings": findings,
    }


def scene_layout_readiness_findings(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    """S1 geometry findings, bounded independently of execution fidelity."""
    scene = bundle.get("scene") or {}
    definitions = (bundle.get("pinned_components") or {}).get("modules") or {}
    report = validate_scene_layout(scene, definitions)
    findings = []
    rules = {
        "module_module_overlap": ("SCENE_MODULE_OVERLAP", "blocking_error"),
        "module_obstacle_overlap": ("SCENE_MODULE_OBSTACLE_OVERLAP", "blocking_error"),
        "module_obstacle_setback": ("SCENE_MODULE_OBSTACLE_SETBACK", "warning"),
        "module_obstacle_clearance": ("SCENE_MODULE_OBSTACLE_CLEARANCE", "blocking_error"),
        "module_over_hole": ("SCENE_MODULE_OVER_HOLE", "blocking_error"),
        "module_exclusion_overlap": ("SCENE_MODULE_KEEPOUT_OVERLAP", "warning"),
    }
    for code, (rule, severity) in rules.items():
        pairs = [item for item in report["conflicts"] if item["code"] == code]
        for item in pairs[:50]:
            findings.append(_finding(
                rule, f"{code}: {item['module_instance_id']} and {item['other_id']}.",
                severity=severity, entity_id=item["module_instance_id"], context=item,
            ))
        if len(pairs) > 50:
            findings.append(_finding(
                rule, f"{len(pairs) - 50} additional {code} pairs (first 50 reported).",
                severity=severity,
                context={"total_pair_count": len(pairs), "omitted_pair_count": len(pairs) - 50},
            ))
    unresolved = [item for item in report["conflicts"]
                  if item["code"] in {"module_unresolved", "obstacle_unresolved", "field_unresolved"}]
    for item in unresolved[:50]:
        entity_id = item["module_instance_id"] or item["other_id"]
        findings.append(_finding(
            "SCENE_LAYOUT_UNRESOLVED",
            f"Cannot resolve layout for {entity_id}: {item['reason']}.",
            entity_id=entity_id, context=item,
        ))
    if len(unresolved) > 50:
        findings.append(_finding(
            "SCENE_LAYOUT_UNRESOLVED",
            f"{len(unresolved) - 50} additional unresolved layout entities (first 50 reported).",
            context={"total_entity_count": len(unresolved), "omitted_entity_count": len(unresolved) - 50},
        ))
    populated = {
        str(item["pv_field_id"]) for item in scene.get("module_instances", [])
        if item.get("enabled", True)
    }
    for field in sorted(scene.get("pv_fields", []), key=lambda item: str(item["pv_field_id"])):
        field_id = str(field["pv_field_id"])
        if field_id not in populated:
            findings.append(_finding(
                "PV_FIELD_EMPTY", f"PV field {field_id} has zero enabled modules.",
                severity="warning", entity_id=field_id,
            ))
        if field.get("field_kind") != "explicit_layout" and field.get("packing_input_hash") is not None:
            try:
                stale = packing_input_hash(scene, field) != field["packing_input_hash"]
            except (KeyError, ValueError, TypeError, AttributeError, OverflowError, IndexError) as exc:
                findings.append(_finding(
                    "SCENE_PV_FIELD_LAYOUT_UNCHECKED",
                    f"PV field {field_id}: its layout could not be compared with its packing inputs ({exc}). Re-fill it if the roof or obstacles changed.",
                    severity="warning", entity_id=field_id,
                ))
                continue
            if stale:
                findings.append(_finding(
                    "SCENE_PV_FIELD_LAYOUT_STALE",
                    f"PV field {field_id} was packed from inputs that have since changed (support surface, obstacles or exclusion areas). Its modules are unchanged; re-fill it to regenerate the layout.",
                    severity="warning", entity_id=field_id,
                ))
    return findings


def phase5_execution_readiness(bundle: Mapping[str, Any], *, numerical_options=None, detailed=False) -> dict[str, Any]:
    """Evaluate the product design against the exact Phase-5 execution envelope."""
    findings: list[dict[str, Any]] = []

    weather = bundle.get("weather_selection")
    if not isinstance(weather, Mapping) or not weather.get("revision_id"):
        findings.append(
            _finding(
                "EXECUTION_WEATHER_REVISION_REQUIRED",
                "Acquire or select a pinned WeatherDataset revision before simulation.",
            )
        )

    scene = bundle.get("scene") or {}
    # S14b: the plan groups strings within the design's orientation tolerance, as the run will.
    electrical = with_effective_policy(bundle.get("electrical_design") or {})
    pinned = bundle.get("pinned_components") or {}
    modules = pinned.get("modules") or {}
    inverters = pinned.get("inverters") or {}

    plan = build_simulation_execution_plan(
        scene,
        electrical,
        numerical_options={"albedo": 0.20},
        detailed=detailed,
    )
    for item in plan.get("findings", []):
        if item.get("severity") == "error" and item.get("code") != "execution_group_mppt_heterogeneous":
            findings.append(
                _finding(
                    f"EXECUTION_PLAN_{str(item.get('code') or 'INVALID').upper()}",
                    str(item.get("message") or "Execution-plan error."),
                    entity_id=(
                        str(item.get("entity_id"))
                        if item.get("entity_id") is not None
                        else None
                    ),
                    context=item.get("context") or {},
                )
            )

    accepted = orientation_overrides(electrical)
    for item in standard_execution_scope_findings(scene, electrical, plan, numerical_options=numerical_options):
        message = item["message"]
        if item["rule_id"] == "SIMULATION_SCOPE_MIXED_STRINGS_ON_ONE_MPPT" and str(item["entity_id"]) in accepted:
            # Detailed readiness retains its pre-USE5 finding bytes.
            note = "The orientation override records your reason; the simulation can't model mixed orientations on one MPPT yet." if detailed else OVERRIDE_NOTE
            message = f"{message} {note}"
        findings.append(_finding(item["rule_id"], message,
                                 entity_id=item["entity_id"], context=item["context"]))

    used_module_ids = {
        str(group.get("module_revision_id") or "")
        for group in execution_units(plan)
        if group.get("module_revision_id")
    }
    for revision_id in sorted(used_module_ids):
        definition = modules.get(revision_id)
        if not isinstance(definition, Mapping):
            findings.append(
                _finding(
                    "EXECUTION_MODULE_REVISION_NOT_PINNED",
                    f"Module revision {revision_id} is not pinned in the project.",
                    entity_id=revision_id,
                )
            )
            continue
        findings.extend(
            phase5_module_definition_readiness(definition, revision_id=revision_id)["findings"]
        )

    used_inverter_ids = {
        str(group.get("inverter_definition_revision_id") or "")
        for group in execution_units(plan)
        if group.get("inverter_definition_revision_id")
    }
    for revision_id in sorted(used_inverter_ids):
        definition = inverters.get(revision_id)
        if not isinstance(definition, Mapping):
            findings.append(
                _finding(
                    "EXECUTION_INVERTER_REVISION_NOT_PINNED",
                    f"Inverter revision {revision_id} is not pinned in the project.",
                    entity_id=revision_id,
                )
            )
            continue
        findings.extend(
            phase5_inverter_definition_readiness(definition)["findings"]
        )

    if numerical_options is not None and "loss_settings" in numerical_options:
        from engine.losses.settings import resolve_loss_settings, circuit_reference
        try:
            settings = resolve_loss_settings(numerical_options["loss_settings"])
            from engine.losses.settings import resolve_circuit_loss_settings, legacy_loss_settings
            circuit_resolution = resolve_circuit_loss_settings(numerical_options["loss_settings"], scene, electrical,
                {**modules, **inverters}, module_quality_override=numerical_options.get("module_overrides", {}).get("module_quality_loss_fraction"), detailed=detailed)
            settings = resolve_loss_settings(legacy_loss_settings(numerical_options["loss_settings"]))
            for group in circuit_units(plan):
                definition = modules.get(group["module_revision_id"])
                if definition is not None:
                    for mppt_id in group["mppt_instance_ids"]:
                        mppt = next(m for m in electrical["mppt_instances"] if m["mppt_instance_id"] == mppt_id)
                        local_settings = settings
                        if circuit_resolution is not None and mppt_id in circuit_resolution["circuits"]:
                            local_settings = deepcopy(settings)
                            local_settings["values"]["dc_wiring_stc_fraction"] = circuit_resolution["circuits"][mppt_id]["dc_wiring_stc_fraction"]
                        circuit_reference(local_settings, definition, modules_in_series=group["modules_in_series"],
                            parallel_strings=len(mppt["connected_string_ids"]), mppt_index=mppt["index"])
        except (ValueError, TypeError, KeyError) as exc:
            findings.append(_finding("LOSS_SETTINGS_INVALID", f"Loss settings cannot run: {exc}"))

    if numerical_options is not None and "optics_thermal_settings" in numerical_options:
        from engine.simulation.optics_thermal import resolve_optics_thermal_settings, resolve_iam
        try:
            optics = resolve_optics_thermal_settings(numerical_options["optics_thermal_settings"])
            for group in execution_units(plan):
                definition = modules.get(group["module_revision_id"])
                if definition is not None:
                    resolve_iam(optics, definition)
        except (ValueError, TypeError, KeyError) as exc:
            findings.append(_finding("OPTICS_THERMAL_INVALID", f"Optics/thermal settings cannot run: {exc}"))

    findings.extend(scene_layout_readiness_findings(bundle))
    exclusion = _modules_not_simulated_finding(scene, electrical, modules, plan)
    if exclusion is not None:
        findings.append(exclusion)

    ordered = _ordered_findings(findings)

    return {
        "schema_name": "Phase5ExecutionReadiness",
        "schema_version": "0.1",
        "readiness_version": READINESS_VERSION,
        "ready": not any(item["severity"] == "blocking_error" for item in ordered),
        "execution_class": plan.get("execution_class"),
        "legacy_homogeneous_backend_compatible": plan.get(
            "legacy_homogeneous_backend_compatible"
        ),
        "execution_plan": deepcopy(plan),
        "findings": deepcopy(ordered),
    }
