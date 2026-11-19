"""Deterministic multi-source component overlays with field-level provenance.

External formats are evidence sources, not canonical authorities. A component may therefore be
assembled from PAN/OND, manufacturer datasheets, user CSV rows, laboratory measurements, or
future open databases. Later sources may refine a component without making optional data a
prerequisite for lower-fidelity simulation.

Conflict resolution is explicit:
- identical values accumulate provenance;
- a higher-priority source may replace a lower-priority value;
- conflicting values at equal priority are unresolved and raise by default.

No value is inferred merely because another source omitted it.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

from components.candidates import INVERTER_SCHEMA_PATH, MODULE_SCHEMA_PATH, _definition_schema_ready
from components.validation import (
    inverter_capabilities,
    module_capabilities,
    pvsyst_sdm_readiness,
    validate_inverter,
    validate_module,
)


@dataclass(frozen=True)
class ComponentSourceFragment:
    source_id: str
    data: dict[str, Any]
    priority: int = 0
    source_kind: str = "user_supplied"
    source_url: str | None = None
    notes: str | None = None
    license_spdx: str | None = None
    license_url: str | None = None
    attribution: str | None = None


def _leaf_items(value: Any, prefix: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _leaf_items(child, prefix + (str(key),))
    else:
        yield prefix, value


def _set_path(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = target
    for key in path[:-1]:
        node = current.get(key)
        if not isinstance(node, dict):
            node = {}
            current[key] = node
        current = node
    current[path[-1]] = deepcopy(value)


def _get_path(target: dict[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    current: Any = target
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return False, None
        current = current[key]
    return True, current


def merge_component_fragments(
    fragments: Iterable[ComponentSourceFragment],
    *,
    conflict_policy: str = "raise_equal_priority",
) -> dict[str, Any]:
    """Merge canonical component fragments in ascending source priority.

    Lists are treated as atomic values. This is intentional: detailed structures such as
    efficiency curves or electrical-model arrays should come from one explicit source/adapter
    unless a specialized merger exists for that structure.
    """
    fragments = list(fragments)
    if not fragments:
        raise ValueError("at least one component source fragment is required")
    if conflict_policy not in {"raise_equal_priority", "keep_first"}:
        raise ValueError("unsupported conflict_policy")

    # Component identity is not an ordinary overridable engineering field. Refuse to
    # accidentally merge two different products merely because one source has higher priority.
    for identity_key in ("manufacturer", "model"):
        supplied = [
            str(fragment.data[identity_key]).strip()
            for fragment in fragments
            if fragment.data.get(identity_key) not in {None, ""}
        ]
        normalized = {value.casefold() for value in supplied}
        if len(normalized) > 1:
            raise ValueError(
                f"component identity conflict for {identity_key}: {supplied!r}"
            )

    ordered = sorted(enumerate(fragments), key=lambda item: (item[1].priority, item[0]))
    merged: dict[str, Any] = {}
    provenance: dict[str, list[dict[str, Any]]] = {}
    winning_priority: dict[str, int] = {}
    conflicts: list[dict[str, Any]] = []

    for _, fragment in ordered:
        if not fragment.source_id:
            raise ValueError("source_id must be non-empty")
        for path, incoming in _leaf_items(fragment.data):
            if not path:
                continue
            dotted = ".".join(path)
            exists, existing = _get_path(merged, path)
            evidence = {
                "source_id": fragment.source_id,
                "source_kind": fragment.source_kind,
                "source_url": fragment.source_url,
                "priority": fragment.priority,
                "notes": fragment.notes,
                "license_spdx": fragment.license_spdx,
                "license_url": fragment.license_url,
                "attribution": fragment.attribution,
                "value": deepcopy(incoming),
            }

            if not exists:
                _set_path(merged, path, incoming)
                winning_priority[dotted] = fragment.priority
                provenance[dotted] = [evidence]
                continue

            if existing == incoming:
                provenance.setdefault(dotted, []).append(evidence)
                continue

            previous_priority = winning_priority[dotted]
            conflict = {
                "field_path": dotted,
                "existing_value": deepcopy(existing),
                "incoming_value": deepcopy(incoming),
                "existing_priority": previous_priority,
                "incoming_priority": fragment.priority,
                "incoming_source_id": fragment.source_id,
                "resolution": None,
            }

            if fragment.priority > previous_priority:
                _set_path(merged, path, incoming)
                winning_priority[dotted] = fragment.priority
                provenance.setdefault(dotted, []).append(evidence)
                conflict["resolution"] = "incoming_higher_priority"
            elif fragment.priority < previous_priority:
                provenance.setdefault(dotted, []).append(evidence)
                conflict["resolution"] = "existing_higher_priority"
            elif conflict_policy == "keep_first":
                provenance.setdefault(dotted, []).append(evidence)
                conflict["resolution"] = "kept_first_equal_priority"
            else:
                conflict["resolution"] = "unresolved_equal_priority"
                conflicts.append(conflict)
                raise ValueError(
                    f"equal-priority source conflict at {dotted}: "
                    f"{existing!r} vs {incoming!r}"
                )
            conflicts.append(conflict)

    source_ids = [fragment.source_id for _, fragment in ordered]
    existing_ids = merged.get("source_ids")
    if isinstance(existing_ids, list):
        source_ids = list(dict.fromkeys([*existing_ids, *source_ids]))
    merged["source_ids"] = source_ids

    return {
        "data": merged,
        "field_provenance": provenance,
        "conflicts": conflicts,
        "sources": [
            {
                "source_id": fragment.source_id,
                "source_kind": fragment.source_kind,
                "source_url": fragment.source_url,
                "priority": fragment.priority,
                "notes": fragment.notes,
                "license_spdx": fragment.license_spdx,
                "license_url": fragment.license_url,
                "attribution": fragment.attribution,
            }
            for _, fragment in ordered
        ],
    }


def _module_model_validation_passed(data: dict[str, Any]) -> bool:
    for model in data.get("electrical_models") or []:
        if (
            model.get("model_type") == "pvsyst_singlediode"
            and pvsyst_sdm_readiness(model.get("validation") or {})["passed"]
        ):
            return True
    return False


def build_candidate_from_fragments(
    component_type: str,
    fragments: Iterable[ComponentSourceFragment],
    *,
    candidate_id: str,
    definition_id: str,
    revision_id: str,
) -> dict[str, Any]:
    """Merge source fragments, validate, and compute progressive capability flags."""
    merged = merge_component_fragments(fragments)
    data = merged["data"]

    data["schema_version"] = "0.1"
    data.setdefault("verification_state", "source_attached")
    if component_type == "module":
        data["schema_name"] = "ModuleDefinition"
        data["module_definition_id"] = definition_id
        data["revision_id"] = revision_id
        findings = validate_module(data)
        for model in data.get("electrical_models") or []:
            if model.get("model_type") != "pvsyst_singlediode":
                continue
            readiness = pvsyst_sdm_readiness(model.get("validation") or {})
            model["readiness_tolerances"] = readiness["readiness_tolerances"]
            validation = model.get("validation") or {}
            if isinstance(validation.get("stc"), dict) and isinstance(validation.get("off_stc"), dict):
                validation["passed"] = readiness["passed"]
                validation["status"] = readiness["status"]
                model["verification_state"] = (
                    "auto_validated" if readiness["passed"] else
                    "source_attached" if data.get("source_ids") else "unverified"
                )
            if readiness["finding"] is not None:
                findings.append(readiness["finding"])
        capabilities = module_capabilities(
            data,
            findings,
            model_validation_passed=_module_model_validation_passed(data),
        )
        schema_ready, schema_errors = _definition_schema_ready(data, MODULE_SCHEMA_PATH)
    elif component_type == "inverter":
        data["schema_name"] = "InverterDefinition"
        data["inverter_definition_id"] = definition_id
        data["revision_id"] = revision_id
        findings = validate_inverter(data)
        capabilities = inverter_capabilities(data, findings)
        schema_ready, schema_errors = _definition_schema_ready(data, INVERTER_SCHEMA_PATH)
    else:
        raise ValueError("component_type must be 'module' or 'inverter'")

    data["capability_flags"] = capabilities

    for message in schema_errors:
        findings.append(
            {
                "rule_id": f"{component_type.upper()}_DEFINITION_SCHEMA_INCOMPLETE",
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

    status = "schema_ready" if schema_ready and not any(
        item["severity"] in {"error", "blocking_error"} for item in findings
    ) else "needs_review"

    return {
        "schema_name": "ComponentCandidate",
        "schema_version": "0.1",
        "candidate_id": candidate_id,
        "component_type": component_type,
        "source_id": None,
        "canonical_data": data,
        "derivations": [],
        "validation_findings": findings,
        "capability_flags": capabilities,
        "definition_schema_ready": schema_ready,
        "status": status,
        "field_provenance": merged["field_provenance"],
        "source_conflicts": merged["conflicts"],
        "sources": merged["sources"],
    }
