"""Phase-4.5 component-aware design integration.

Exact component revisions are bound to canonical design objects. Proposed revision
changes are analyzed without mutation; applying a change is always explicit.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping, Sequence

from geometry.pvfield import (
    ModuleFootprint,
    layout_impact_report,
    pack_field,
    packing_input_hash,
    replace_field_layout,
    validate_field_layout,
)


COMPONENT_INTEGRATION_VERSION = "opensimpv-component-integration-0.1"


def module_nameplate_w(definition: Mapping[str, Any]) -> float:
    """D14: one module's DC nameplate, the datasheet nominal power when the definition gives one, else its STC Pmp.
    The same rule as the engine's installed-DC capacity (engine/simulation/unshaded.py)."""
    stc = definition.get("stc") or {}
    nominal = stc.get("nominal_power_w")
    return float(stc["pmp_w"] if nominal is None else nominal)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _field(scene: Mapping[str, Any], pv_field_id: str) -> dict[str, Any]:
    for item in scene.get("pv_fields", []):
        if item.get("pv_field_id") == pv_field_id:
            return item
    raise KeyError(f"PV field not found: {pv_field_id}")


def _inverter_instance(
    electrical_design: Mapping[str, Any],
    inverter_instance_id: str,
) -> dict[str, Any]:
    for item in electrical_design.get("inverter_instances", []):
        if item.get("inverter_instance_id") == inverter_instance_id:
            return item
    raise KeyError(f"Inverter instance not found: {inverter_instance_id}")


def _revision_id(definition: Mapping[str, Any], expected_schema: str) -> str:
    if definition.get("schema_name") != expected_schema:
        raise ValueError(f"expected {expected_schema}")
    revision_id = str(definition.get("revision_id") or "")
    if not revision_id:
        raise ValueError("component definition requires revision_id")
    return revision_id


def _electrical_model_summary(module_definition: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for model in module_definition.get("electrical_models") or []:
        result.append(
            {
                "model_type": model.get("model_type"),
                "model_version": model.get("model_version"),
                "verification_state": model.get("verification_state"),
            }
        )
    result.sort(
        key=lambda item: (
            str(item.get("model_type") or ""),
            str(item.get("model_version") or ""),
        )
    )
    return result


def module_design_snapshot(module_definition: Mapping[str, Any]) -> dict[str, Any]:
    """Design-facing properties controlled by one exact module revision."""
    revision_id = _revision_id(module_definition, "ModuleDefinition")
    mechanical = module_definition.get("mechanical") or {}
    stc = module_definition.get("stc") or {}
    coefficients = module_definition.get("temperature_coefficients") or {}
    limits = module_definition.get("limits") or {}
    capabilities = module_definition.get("capability_flags") or {}

    return {
        "component_type": "module",
        "definition_id": module_definition.get("module_definition_id"),
        "revision_id": revision_id,
        "manufacturer": module_definition.get("manufacturer"),
        "model": module_definition.get("model"),
        "verification_state": module_definition.get("verification_state"),
        "mechanical": {
            "width_m": mechanical.get("width_m"),
            "height_m": mechanical.get("height_m"),
            "thickness_m": mechanical.get("thickness_m"),
            "mass_kg": mechanical.get("mass_kg"),
        },
        "stc": {
            "pmp_w": stc.get("pmp_w"),
            "voc_v": stc.get("voc_v"),
            "isc_a": stc.get("isc_a"),
            "vmp_v": stc.get("vmp_v"),
            "imp_a": stc.get("imp_a"),
        },
        "temperature_coefficients": {
            "alpha_isc_per_c": coefficients.get("alpha_isc_per_c"),
            "beta_voc_per_c": coefficients.get("beta_voc_per_c"),
            "gamma_pmp_per_c": coefficients.get("gamma_pmp_per_c"),
            "coefficient_basis": coefficients.get("coefficient_basis"),
        },
        "string_design_limits": {
            "max_system_voltage_v": limits.get("max_system_voltage_v"),
            "max_system_voltage_iec_v": limits.get("max_system_voltage_iec_v"),
            "max_system_voltage_ul_v": limits.get("max_system_voltage_ul_v"),
            "max_series_fuse_a": limits.get("max_series_fuse_a"),
            "operating_temperature_min_c": limits.get(
                "operating_temperature_min_c"
            ),
            "operating_temperature_max_c": limits.get(
                "operating_temperature_max_c"
            ),
        },
        "available_simulation_models": _electrical_model_summary(
            module_definition
        ),
        "capability_flags": deepcopy(capabilities),
    }


def _normalized_mppts(
    inverter_definition: Mapping[str, Any],
) -> list[dict[str, Any]]:
    explicit = inverter_definition.get("mppts")
    if explicit:
        result = []
        for item in explicit:
            result.append(
                {
                    "index": int(item["mppt_index"]),
                    "min_operating_voltage_v": item.get(
                        "min_operating_voltage_v"
                    ),
                    "max_operating_voltage_v": item.get(
                        "max_operating_voltage_v"
                    ),
                    "nominal_voltage_v": item.get("nominal_voltage_v"),
                    "max_operating_current_a": item.get(
                        "max_operating_current_a"
                    ),
                    "max_short_circuit_current_a": item.get(
                        "max_short_circuit_current_a"
                    ),
                    "input_count": item.get("input_count"),
                    "independent_inputs": item.get("independent_inputs"),
                }
            )
        return sorted(result, key=lambda item: item["index"])

    template = inverter_definition.get("mppt_template")
    if not template:
        return []
    count = int(template["count"])
    return [
        {
            "index": index,
            "min_operating_voltage_v": template.get(
                "min_operating_voltage_v"
            ),
            "max_operating_voltage_v": template.get(
                "max_operating_voltage_v"
            ),
            "nominal_voltage_v": template.get("nominal_voltage_v"),
            "max_operating_current_a": template.get(
                "max_operating_current_a"
            ),
            "max_short_circuit_current_a": template.get(
                "max_short_circuit_current_a"
            ),
            "input_count": template.get("input_count_per_mppt"),
            "independent_inputs": template.get("independent_inputs"),
        }
        for index in range(1, count + 1)
    ]


def inverter_inputs_per_mppt(
    inverter_definition: Mapping[str, Any], index: int = 1
) -> tuple[int | None, str | None]:
    """DC inputs on one MPPT: as stated, or the total ÷ the MPPT count when that divides evenly (USE-D4)."""
    for item in _normalized_mppts(inverter_definition):
        if int(item["index"]) == int(index) and item.get("input_count"):
            return int(item["input_count"]), "definition"
    template = inverter_definition.get("mppt_template") or {}
    total, count = template.get("total_input_count"), template.get("count")
    if total and count and int(total) % int(count) == 0:
        return int(total) // int(count), f"derived: {int(total)} inputs on {int(count)} MPPTs"
    return None, None


def inverter_design_snapshot(
    inverter_definition: Mapping[str, Any],
) -> dict[str, Any]:
    """Design-facing properties controlled by one exact inverter revision."""
    revision_id = _revision_id(inverter_definition, "InverterDefinition")
    dc = inverter_definition.get("dc_limits") or {}
    ac = inverter_definition.get("ac_limits") or {}
    efficiency = inverter_definition.get("efficiency_model") or {}
    capabilities = inverter_definition.get("capability_flags") or {}
    sizing = inverter_definition.get("array_sizing_limits") or {}
    mppts = _normalized_mppts(inverter_definition)

    return {
        "component_type": "inverter",
        "definition_id": inverter_definition.get("inverter_definition_id"),
        "revision_id": revision_id,
        "manufacturer": inverter_definition.get("manufacturer"),
        "model": inverter_definition.get("model"),
        "verification_state": inverter_definition.get(
            "verification_state"
        ),
        "dc_limits": {
            "max_dc_voltage_v": dc.get("max_dc_voltage_v"),
            "nominal_dc_voltage_v": dc.get("nominal_dc_voltage_v"),
            "max_dc_power_w": dc.get("max_dc_power_w"),
            "max_dc_current_a": dc.get("max_dc_current_a"),
            "max_dc_short_circuit_current_a": dc.get(
                "max_dc_short_circuit_current_a"
            ),
            "startup_voltage_v": dc.get("startup_voltage_v"),
            "shutdown_voltage_v": dc.get("shutdown_voltage_v"),
        },
        "mppts": mppts,
        "mppt_count": len(mppts),
        "ac_limits": {
            "nominal_ac_power_w": ac.get("nominal_ac_power_w"),
            "max_ac_power_w": ac.get("max_ac_power_w"),
            "nominal_ac_voltage_v": ac.get("nominal_ac_voltage_v"),
            "nominal_frequency_hz": ac.get("nominal_frequency_hz"),
            "max_ac_current_a": ac.get("max_ac_current_a"),
        },
        "array_sizing_limits": {
            "nominal_pv_array_power_w": sizing.get(
                "nominal_pv_array_power_w"
            ),
            "max_pv_array_power_w": sizing.get("max_pv_array_power_w"),
            "max_pv_current_a": sizing.get("max_pv_current_a"),
        },
        "efficiency_model": {
            "model_type": efficiency.get("model_type"),
            "reference_metrics": deepcopy(
                efficiency.get("reference_metrics")
            ),
            "curve_count": len(efficiency.get("curves") or []),
        },
        "capability_flags": deepcopy(capabilities),
    }


def _flatten(
    value: Any,
    *,
    prefix: str = "",
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(value[key], prefix=path))
        return result
    if isinstance(value, list):
        return {prefix: deepcopy(value)}
    return {prefix: value}


def _changed_properties(
    current: Mapping[str, Any] | None,
    proposed: Mapping[str, Any],
) -> list[dict[str, Any]]:
    current_flat = _flatten(current or {})
    proposed_flat = _flatten(proposed)
    paths = sorted(set(current_flat) | set(proposed_flat))
    return [
        {
            "path": path,
            "current_value": deepcopy(current_flat.get(path)),
            "proposed_value": deepcopy(proposed_flat.get(path)),
        }
        for path in paths
        if current_flat.get(path) != proposed_flat.get(path)
    ]


def _impact_report(
    *,
    component_type: str,
    target_id: str,
    current_revision_id: str | None,
    proposed_revision_id: str,
    current_properties: Mapping[str, Any] | None,
    proposed_properties: Mapping[str, Any],
    consequences: Sequence[Mapping[str, Any]],
    available_actions: Sequence[str],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    severity_rank = {"info": 0, "warning": 1, "conflict": 2}
    maximum = max(
        (
            severity_rank[str(item["severity"])]
            for item in consequences
        ),
        default=0,
    )
    status = (
        "conflict"
        if maximum >= 2
        else "warning"
        if maximum == 1
        else "compatible"
    )
    if current_revision_id == proposed_revision_id and not consequences:
        status = "no_change"

    report: dict[str, Any] = {
        "schema_name": "ComponentRevisionImpactReport",
        "schema_version": "0.1",
        "integration_version": COMPONENT_INTEGRATION_VERSION,
        "component_type": component_type,
        "target_id": target_id,
        "current_revision_id": current_revision_id,
        "proposed_revision_id": proposed_revision_id,
        "status": status,
        "mutation_performed": False,
        "current_properties": deepcopy(current_properties),
        "proposed_properties": deepcopy(proposed_properties),
        "changed_properties": _changed_properties(
            current_properties, proposed_properties
        ),
        "consequences": [deepcopy(dict(item)) for item in consequences],
        "available_actions": list(available_actions),
    }
    if extra:
        report.update(deepcopy(dict(extra)))

    report["impact_hash"] = _hash(
        {
            key: value
            for key, value in report.items()
            if key != "impact_hash"
        }
    )
    return report


def _module_rows(
    scene: Mapping[str, Any],
    pv_field_id: str,
) -> dict[str, int]:
    return {
        str(item["module_instance_id"]): int(item["row_index"])
        for item in scene.get("module_instances", [])
        if item.get("pv_field_id") == pv_field_id
    }


def _geometry_consequences(
    scene: Mapping[str, Any],
    pv_field_id: str,
    new_module_definition: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    field = _field(scene, pv_field_id)
    orientation = str(field["orientation"])
    new_footprint = ModuleFootprint.from_definition(
        new_module_definition,
        orientation,
        float(field.get("tilt_deg", 0.0)),
    )

    hypothetical = deepcopy(dict(scene))
    hypothetical_field = _field(hypothetical, pv_field_id)
    hypothetical_field["module_definition_revision_id"] = (
        new_footprint.module_definition_revision_id
    )
    hypothetical_field["module_footprint"] = new_footprint.to_mapping()
    for module in hypothetical.get("module_instances", []):
        if module.get("pv_field_id") == pv_field_id:
            module["module_definition_revision_id"] = (
                new_footprint.module_definition_revision_id
            )

    layout_report = validate_field_layout(
        hypothetical, pv_field_id
    )
    rows = _module_rows(hypothetical, pv_field_id)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for conflict in layout_report["conflicts"]:
        code = str(conflict["code"])
        if code == "packing_inputs_changed":
            continue
        grouped.setdefault(code, []).append(conflict)

    consequences: list[dict[str, Any]] = []
    descriptions = {
        "module_outside_support_or_setback": (
            "Modules violate the support boundary or perimeter setback "
            "with the proposed component dimensions."
        ),
        "module_exclusion_overlap": (
            "Modules overlap an exclusion/walkway with the proposed "
            "component dimensions."
        ),
        "module_obstacle_overlap": (
            "Modules overlap an obstacle with the proposed component dimensions."
        ),
        "module_obstacle_setback": (
            "Modules violate obstacle setback with the proposed component dimensions."
        ),
        "module_module_overlap": (
            "Existing module centers produce module-module overlap with "
            "the proposed component dimensions."
        ),
    }
    for code in sorted(grouped):
        conflicts = grouped[code]
        module_ids = sorted(
            {
                str(item["module_instance_id"])
                for item in conflicts
                if item.get("module_instance_id")
            }
        )
        related_ids = sorted(
            {
                str(item["related_entity_id"])
                for item in conflicts
                if item.get("related_entity_id")
            }
        )
        row_indices = sorted(
            {
                rows[module_id]
                for module_id in module_ids
                if module_id in rows
            }
        )
        consequences.append(
            {
                "code": code,
                "severity": "conflict",
                "count": len(module_ids) or len(conflicts),
                "entity_ids": module_ids,
                "related_entity_ids": related_ids,
                "row_indices": row_indices,
                "message": descriptions.get(code, code),
            }
        )

    rebuild_preview: dict[str, Any]
    try:
        result = pack_field(
            hypothetical,
            hypothetical_field,
            new_module_definition,
        )
    except Exception as exc:
        rebuild_preview = {
            "available": False,
            "reason": str(exc),
            "module_count": None,
            "module_count_delta": None,
            "packing_input_hash": None,
        }
        consequences.append(
            {
                "code": "rebuild_not_available_with_current_field_parameters",
                "severity": "warning",
                "count": 1,
                "entity_ids": [pv_field_id],
                "related_entity_ids": [],
                "row_indices": [],
                "message": str(exc),
            }
        )
    else:
        current_count = sum(
            1
            for item in scene.get("module_instances", [])
            if item.get("pv_field_id") == pv_field_id
        )
        rebuild_preview = {
            "available": True,
            "reason": None,
            "module_count": result.module_count,
            "module_count_delta": result.module_count - current_count,
            "packing_input_hash": result.packing_input_hash,
        }
        if result.module_count != current_count:
            consequences.append(
                {
                    "code": "rebuild_module_count_changes",
                    "severity": "warning",
                    "count": abs(result.module_count - current_count),
                    "entity_ids": [pv_field_id],
                    "related_entity_ids": [],
                    "row_indices": [],
                    "message": (
                        f"Explicit rebuild would change module count from "
                        f"{current_count} to {result.module_count}."
                    ),
                }
            )

    return consequences, rebuild_preview


def _connected_topology(
    electrical_design: Mapping[str, Any],
    inverter_instance_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mppts = [
        item
        for item in electrical_design.get("mppt_instances", [])
        if item.get("inverter_instance_id") == inverter_instance_id
    ]
    mppt_ids = {str(item["mppt_instance_id"]) for item in mppts}
    strings = [
        item
        for item in electrical_design.get("strings", [])
        if item.get("target_mppt_instance_id") in mppt_ids
    ]
    return mppts, strings


class ComponentDesignSession:
    """Atomic component-revision integration over Scene + ElectricalDesign."""

    def __init__(
        self,
        scene: Mapping[str, Any],
        *,
        electrical_design: Mapping[str, Any] | None = None,
        module_definitions: Mapping[str, Mapping[str, Any]] | None = None,
        inverter_definitions: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self._scene = deepcopy(dict(scene))
        self._electrical = (
            deepcopy(dict(electrical_design))
            if electrical_design is not None
            else None
        )
        self._modules = {
            str(key): deepcopy(dict(value))
            for key, value in (module_definitions or {}).items()
        }
        self._inverters = {
            str(key): deepcopy(dict(value))
            for key, value in (inverter_definitions or {}).items()
        }
        self._undo: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        self._redo: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

    @property
    def scene(self) -> dict[str, Any]:
        return deepcopy(self._scene)

    @property
    def electrical_design(self) -> dict[str, Any] | None:
        return deepcopy(self._electrical)

    def _module(self, revision_id: str) -> Mapping[str, Any]:
        try:
            return self._modules[revision_id]
        except KeyError as exc:
            raise KeyError(
                f"module revision not available: {revision_id}"
            ) from exc

    def _inverter(self, revision_id: str) -> Mapping[str, Any]:
        try:
            return self._inverters[revision_id]
        except KeyError as exc:
            raise KeyError(
                f"inverter revision not available: {revision_id}"
            ) from exc

    def _mutate(self, operation):
        before = (deepcopy(self._scene), deepcopy(self._electrical))
        try:
            result = operation()
        except Exception:
            self._scene, self._electrical = before
            raise
        self._undo.append(before)
        self._redo.clear()
        return result

    def undo(self) -> bool:
        if not self._undo:
            return False
        previous = self._undo.pop()
        self._redo.append((deepcopy(self._scene), deepcopy(self._electrical)))
        self._scene, self._electrical = previous
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        following = self._redo.pop()
        self._undo.append((deepcopy(self._scene), deepcopy(self._electrical)))
        self._scene, self._electrical = following
        return True

    def binding_manifest(self) -> dict[str, Any]:
        module_bindings = []
        for field in sorted(
            self._scene.get("pv_fields", []),
            key=lambda item: str(item["pv_field_id"]),
        ):
            revision_id = str(field["module_definition_revision_id"])
            definition = self._modules.get(revision_id)
            module_bindings.append(
                {
                    "target_type": "pv_field",
                    "target_id": str(field["pv_field_id"]),
                    "revision_id": revision_id,
                    "resolved": definition is not None,
                    "design_properties": (
                        module_design_snapshot(definition)
                        if definition is not None
                        else None
                    ),
                }
            )

        inverter_bindings = []
        if self._electrical is not None:
            for inverter in sorted(
                self._electrical.get("inverter_instances", []),
                key=lambda item: str(item["inverter_instance_id"]),
            ):
                revision_id = str(
                    inverter["inverter_definition_revision_id"]
                )
                definition = self._inverters.get(revision_id)
                inverter_bindings.append(
                    {
                        "target_type": "inverter_instance",
                        "target_id": str(inverter["inverter_instance_id"]),
                        "revision_id": revision_id,
                        "resolved": definition is not None,
                        "design_properties": (
                            inverter_design_snapshot(definition)
                            if definition is not None
                            else None
                        ),
                    }
                )

        manifest = {
            "schema_name": "ComponentBindingManifest",
            "schema_version": "0.1",
            "integration_version": COMPONENT_INTEGRATION_VERSION,
            "scene_id": str(self._scene["scene_id"]),
            "scene_revision_id": str(self._scene["revision_id"]),
            "electrical_revision_id": (
                str(self._electrical["electrical_revision_id"])
                if self._electrical is not None
                else None
            ),
            "module_bindings": module_bindings,
            "inverter_bindings": inverter_bindings,
        }
        manifest["manifest_hash"] = _hash(manifest)
        return manifest

    def analyze_module_revision_change(
        self,
        pv_field_id: str,
        proposed_revision_id: str,
    ) -> dict[str, Any]:
        field = _field(self._scene, pv_field_id)
        current_revision_id = str(
            field["module_definition_revision_id"]
        )
        proposed = self._module(proposed_revision_id)
        current = self._modules.get(current_revision_id)
        proposed_snapshot = module_design_snapshot(proposed)
        current_snapshot = (
            module_design_snapshot(current) if current is not None else None
        )

        if current_revision_id == proposed_revision_id:
            consequences: list[dict[str, Any]] = []
            rebuild_preview = {
                "available": True,
                "reason": None,
                "module_count": sum(
                    1
                    for item in self._scene.get("module_instances", [])
                    if item.get("pv_field_id") == pv_field_id
                ),
                "module_count_delta": 0,
                "packing_input_hash": field.get("packing_input_hash"),
            }
        else:
            consequences, rebuild_preview = _geometry_consequences(
                self._scene, pv_field_id, proposed
            )

        changed = _changed_properties(
            current_snapshot, proposed_snapshot
        )
        changed_paths = {item["path"] for item in changed}

        field_module_ids = {
            str(item["module_instance_id"])
            for item in self._scene.get("module_instances", [])
            if item.get("pv_field_id") == pv_field_id
        }
        connected_strings = []
        if self._electrical is not None:
            connected_strings = [
                item
                for item in self._electrical.get("strings", [])
                if field_module_ids.intersection(
                    str(module_id)
                    for module_id in item.get("module_instance_ids", [])
                )
            ]
        if any(
            path.startswith("stc.")
            or path.startswith("temperature_coefficients.")
            or path.startswith("string_design_limits.")
            for path in changed_paths
        ):
            consequences.append(
                {
                    "code": "string_design_revalidation_required",
                    "severity": "warning",
                    "count": len(connected_strings) or 1,
                    "entity_ids": (
                        sorted(str(item["string_id"]) for item in connected_strings)
                        if connected_strings
                        else [pv_field_id]
                    ),
                    "related_entity_ids": [pv_field_id],
                    "row_indices": [],
                    "message": (
                        "Module electrical/string-design properties changed; "
                        "existing/future string checks must be revalidated."
                    ),
                }
            )
        if (
            connected_strings
            and rebuild_preview.get("available")
            and rebuild_preview.get("module_count_delta") not in {None, 0}
        ):
            consequences.append(
                {
                    "code": "field_rebuild_may_invalidate_string_membership",
                    "severity": "warning",
                    "count": len(connected_strings),
                    "entity_ids": sorted(
                        str(item["string_id"]) for item in connected_strings
                    ),
                    "related_entity_ids": [pv_field_id],
                    "row_indices": [],
                    "message": (
                        "The explicit field rebuild preview changes module count; "
                        "existing string membership must be reviewed after rebuild."
                    ),
                }
            )

        if any(
            path.startswith("available_simulation_models")
            or path.startswith("capability_flags.")
            for path in changed_paths
        ):
            consequences.append(
                {
                    "code": "simulation_capability_changed",
                    "severity": "warning",
                    "count": 1,
                    "entity_ids": [pv_field_id],
                    "related_entity_ids": [],
                    "row_indices": [],
                    "message": (
                        "Available simulation model/capability changed with "
                        "the proposed module revision."
                    ),
                }
            )

        return _impact_report(
            component_type="module",
            target_id=pv_field_id,
            current_revision_id=current_revision_id,
            proposed_revision_id=proposed_revision_id,
            current_properties=current_snapshot,
            proposed_properties=proposed_snapshot,
            consequences=consequences,
            available_actions=[
                "keep_current_revision",
                "apply_revision_keep_current_layout",
                "apply_revision_and_rebuild_field",
            ],
            extra={"rebuild_preview": rebuild_preview},
        )

    def apply_module_revision_keep_current_layout(
        self,
        pv_field_id: str,
        proposed_revision_id: str,
    ) -> dict[str, Any]:
        report = self.analyze_module_revision_change(
            pv_field_id, proposed_revision_id
        )
        proposed = self._module(proposed_revision_id)

        def operation() -> dict[str, Any]:
            field = _field(self._scene, pv_field_id)
            footprint = ModuleFootprint.from_definition(
                proposed,
                str(field["orientation"]),
                float(field.get("tilt_deg", 0.0)),
            )
            old_footprint = deepcopy(field.get("module_footprint"))
            old_footprint_model = (
                ModuleFootprint.from_mapping(
                    old_footprint,
                    fallback_tilt_deg=float(field.get("tilt_deg", 0.0)),
                )
                if old_footprint
                else None
            )
            same_geometry = bool(
                old_footprint_model
                and abs(
                    old_footprint_model.plan_projection_width_m
                    - footprint.plan_projection_width_m
                )
                <= 1e-12
                and abs(
                    old_footprint_model.plan_projection_height_m
                    - footprint.plan_projection_height_m
                )
                <= 1e-12
            )
            previous_hash = field.get("packing_input_hash")
            field["module_definition_revision_id"] = proposed_revision_id
            field["module_footprint"] = footprint.to_mapping()
            field["layout_source"] = "generated_then_edited"
            field.setdefault("metadata", {})[
                "component_revision_change"
            ] = {
                "integration_version": COMPONENT_INTEGRATION_VERSION,
                "action": "apply_revision_keep_current_layout",
                "previous_revision_id": report["current_revision_id"],
                "new_revision_id": proposed_revision_id,
                "impact_hash": report["impact_hash"],
                "previous_packing_input_hash": previous_hash,
            }
            for module in self._scene.get("module_instances", []):
                if module.get("pv_field_id") == pv_field_id:
                    module["module_definition_revision_id"] = (
                        proposed_revision_id
                    )

            has_geometry_conflict = any(
                item["severity"] == "conflict"
                for item in report["consequences"]
            )
            if same_geometry and not has_geometry_conflict:
                field["packing_input_hash"] = packing_input_hash(
                    self._scene, field, footprint
                )
                field["layout_status"] = "packed"
            else:
                field["packing_input_hash"] = None
                field["layout_status"] = (
                    "conflict" if has_geometry_conflict else "stale"
                )
            return deepcopy(report)

        return self._mutate(operation)

    def apply_module_revision_and_rebuild_field(
        self,
        pv_field_id: str,
        proposed_revision_id: str,
    ) -> dict[str, Any]:
        report = self.analyze_module_revision_change(
            pv_field_id, proposed_revision_id
        )
        if not report["rebuild_preview"]["available"]:
            raise ValueError(report["rebuild_preview"]["reason"])
        proposed = self._module(proposed_revision_id)

        def operation() -> dict[str, Any]:
            before_scene = deepcopy(self._scene)
            field = _field(self._scene, pv_field_id)
            footprint = ModuleFootprint.from_definition(
                proposed, str(field["orientation"])
            )
            field["module_definition_revision_id"] = proposed_revision_id
            field["module_footprint"] = footprint.to_mapping()
            result = pack_field(self._scene, field, proposed)
            self._scene = replace_field_layout(self._scene, result)
            layout_impact = layout_impact_report(
                before_scene,
                self._scene,
                pv_field_id,
                electrical_design=self._electrical,
            )
            rebuilt = _field(self._scene, pv_field_id)
            rebuilt.setdefault("metadata", {})[
                "component_revision_change"
            ] = {
                "integration_version": COMPONENT_INTEGRATION_VERSION,
                "action": "apply_revision_and_rebuild_field",
                "previous_revision_id": report["current_revision_id"],
                "new_revision_id": proposed_revision_id,
                "impact_hash": report["impact_hash"],
                "layout_impact_hash": layout_impact["impact_hash"],
            }
            return {
                "impact_report": deepcopy(report),
                "layout_impact": layout_impact,
                "module_count": result.module_count,
                "packing_input_hash": result.packing_input_hash,
            }

        return self._mutate(operation)

    def analyze_inverter_revision_change(
        self,
        inverter_instance_id: str,
        proposed_revision_id: str,
    ) -> dict[str, Any]:
        if self._electrical is None:
            raise ValueError("electrical_design is required")
        inverter = _inverter_instance(
            self._electrical, inverter_instance_id
        )
        current_revision_id = str(
            inverter["inverter_definition_revision_id"]
        )
        proposed = self._inverter(proposed_revision_id)
        current = self._inverters.get(current_revision_id)
        proposed_snapshot = inverter_design_snapshot(proposed)
        current_snapshot = (
            inverter_design_snapshot(current) if current is not None else None
        )
        changes = _changed_properties(
            current_snapshot, proposed_snapshot
        )
        changed_paths = {item["path"] for item in changes}
        mppts, strings = _connected_topology(
            self._electrical, inverter_instance_id
        )

        consequences: list[dict[str, Any]] = []
        supported_indices = {
            int(item["index"])
            for item in proposed_snapshot["mppts"]
        }
        unsupported = sorted(
            item["mppt_instance_id"]
            for item in mppts
            if int(item["index"]) not in supported_indices
        )
        if unsupported:
            consequences.append(
                {
                    "code": "inverter_mppt_topology_conflict",
                    "severity": "conflict",
                    "count": len(unsupported),
                    "entity_ids": unsupported,
                    "related_entity_ids": [inverter_instance_id],
                    "row_indices": [],
                    "message": (
                        "Current MPPT instance indices are not available "
                        "on the proposed inverter revision."
                    ),
                }
            )

        if strings and any(
            path.startswith("dc_limits.")
            or path.startswith("mppts")
            or path.startswith("array_sizing_limits.")
            for path in changed_paths
        ):
            consequences.append(
                {
                    "code": "connected_strings_require_revalidation",
                    "severity": "warning",
                    "count": len(strings),
                    "entity_ids": sorted(
                        str(item["string_id"]) for item in strings
                    ),
                    "related_entity_ids": [inverter_instance_id],
                    "row_indices": [],
                    "message": (
                        "Inverter DC/MPPT limits changed; connected strings "
                        "must be revalidated against the proposed revision."
                    ),
                }
            )

        if any(
            path.startswith("ac_limits.")
            for path in changed_paths
        ):
            consequences.append(
                {
                    "code": "ac_rating_changed",
                    "severity": "warning",
                    "count": 1,
                    "entity_ids": [inverter_instance_id],
                    "related_entity_ids": [],
                    "row_indices": [],
                    "message": (
                        "Inverter AC rating/voltage properties changed."
                    ),
                }
            )

        if any(
            path.startswith("efficiency_model.")
            or path.startswith("capability_flags.")
            for path in changed_paths
        ):
            consequences.append(
                {
                    "code": "inverter_simulation_capability_changed",
                    "severity": "warning",
                    "count": 1,
                    "entity_ids": [inverter_instance_id],
                    "related_entity_ids": [],
                    "row_indices": [],
                    "message": (
                        "Inverter efficiency model or simulation capability "
                        "changed with the proposed revision."
                    ),
                }
            )

        return _impact_report(
            component_type="inverter",
            target_id=inverter_instance_id,
            current_revision_id=current_revision_id,
            proposed_revision_id=proposed_revision_id,
            current_properties=current_snapshot,
            proposed_properties=proposed_snapshot,
            consequences=consequences,
            available_actions=[
                "keep_current_revision",
                "apply_revision_keep_current_topology",
            ],
            extra={
                "topology_summary": {
                    "current_mppt_instance_count": len(mppts),
                    "connected_string_count": len(strings),
                    "proposed_mppt_count": proposed_snapshot["mppt_count"],
                    "automatic_topology_rebuild_available": False,
                }
            },
        )

    def apply_inverter_revision_keep_current_topology(
        self,
        inverter_instance_id: str,
        proposed_revision_id: str,
    ) -> dict[str, Any]:
        report = self.analyze_inverter_revision_change(
            inverter_instance_id, proposed_revision_id
        )

        def operation() -> dict[str, Any]:
            assert self._electrical is not None
            inverter = _inverter_instance(
                self._electrical, inverter_instance_id
            )
            inverter["inverter_definition_revision_id"] = (
                proposed_revision_id
            )
            inverter["component_binding"] = {
                "integration_version": COMPONENT_INTEGRATION_VERSION,
                "action": "apply_revision_keep_current_topology",
                "previous_revision_id": report["current_revision_id"],
                "new_revision_id": proposed_revision_id,
                "impact_hash": report["impact_hash"],
                "status": (
                    "conflict"
                    if report["status"] == "conflict"
                    else "requires_revalidation"
                    if report["status"] == "warning"
                    else "bound"
                ),
            }
            return deepcopy(report)

        return self._mutate(operation)
