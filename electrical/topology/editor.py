"""Phase-4.6 canonical electrical-topology editor.

This module edits ElectricalDesignRevision drafts. It deliberately does not perform
Phase-4.7 electrical validity checks (temperature-corrected Voc/Vmpp, current,
DC/AC ratio, orientation mismatch, etc.).
"""

from __future__ import annotations

import math

from copy import deepcopy
from datetime import datetime, timezone
from math import ceil, floor
from typing import Any, Iterable, Mapping, Sequence

from components.design_integration import (
    inverter_design_snapshot,
    module_design_snapshot,
)
from electrical.mppt import (
    balanced_string_assignment,
    validate_mppt_assignment,
)

from .serialization import (
    canonical_electrical_hash,
    canonical_electrical_json,
)


TOPOLOGY_EDITOR_VERSION = "opensimpv-electrical-topology-editor-0.1"


def new_electrical_design(
    *,
    project_id: str,
    electrical_revision_id: str,
    pcc_id: str,
    revision_number: int = 1,
    project_revision_id: str | None = None,
) -> dict[str, Any]:
    if not project_id or not electrical_revision_id or not pcc_id:
        raise ValueError("project_id, electrical_revision_id, and pcc_id are required")
    if revision_number < 1:
        raise ValueError("revision_number must be at least 1")
    design = {
        "schema_name": "ElectricalDesignRevision",
        "schema_version": "0.1",
        "electrical_revision_id": electrical_revision_id,
        "project_id": project_id,
        "created_at": None,
        "change_summary": None,
        "inverter_instances": [],
        "mppt_instances": [],
        "strings": [],
        "connections": [],
        "pcc_definition": {
            "pcc_id": pcc_id,
            "name": "PCC",
        },
        "revision_number": revision_number,
        "created_by": None,
        "supersedes_revision_id": None,
        "status": "draft",
    }
    if project_revision_id is not None:
        design["project_revision_id"] = project_revision_id
    return design


def _unique(values: Iterable[str], name: str) -> list[str]:
    result = [str(value) for value in values]
    if not result:
        raise ValueError(f"{name} must not be empty")
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must be unique")
    return result


def _module_sort_key(module: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(module.get("pv_field_id") or ""),
        int(module.get("row_index") or 0),
        int(module.get("column_index") or 0),
        str(module.get("module_instance_id") or ""),
    )


class ElectricalTopologyEditorSession:
    """Atomic editor for one draft ElectricalDesignRevision."""

    def __init__(
        self,
        scene: Mapping[str, Any],
        electrical_design: Mapping[str, Any],
        *,
        project_revision_id: str | None = None,
        module_definitions: Mapping[str, Mapping[str, Any]] | None = None,
        inverter_definitions: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self._scene = deepcopy(dict(scene))
        self._design = deepcopy(dict(electrical_design))
        self._design.setdefault("inverter_instances", [])
        self._design.setdefault("mppt_instances", [])
        self._design.setdefault("strings", [])
        self._design.setdefault("connections", [])
        self._design.setdefault("pcc_definition", {})

        self._modules = {
            str(key): deepcopy(dict(value))
            for key, value in (module_definitions or {}).items()
        }
        self._inverters = {
            str(key): deepcopy(dict(value))
            for key, value in (inverter_definitions or {}).items()
        }
        self._project_revision_id = (
            project_revision_id
            or self._design.get("project_revision_id")
            or self._infer_project_revision_id()
        )
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []

    @property
    def electrical_design(self) -> dict[str, Any]:
        return deepcopy(self._design)

    @property
    def undo_depth(self) -> int:
        return len(self._undo)

    @property
    def redo_depth(self) -> int:
        return len(self._redo)

    def canonical_json(self) -> str:
        return canonical_electrical_json(self._design)

    def canonical_hash(self) -> str:
        return canonical_electrical_hash(self._design)

    def _infer_project_revision_id(self) -> str | None:
        values = {
            str(item["project_revision_id"])
            for collection in ("inverter_instances", "strings", "connections")
            for item in self._design.get(collection, [])
            if item.get("project_revision_id")
        }
        if len(values) > 1:
            raise ValueError(
                "electrical draft contains multiple project_revision_id values"
            )
        return next(iter(values)) if values else None

    def _require_project_revision_id(self) -> str:
        if not self._project_revision_id:
            raise ValueError(
                "project_revision_id is required to create canonical topology entities"
            )
        return str(self._project_revision_id)

    def _mutate(self, operation):
        before = deepcopy(self._design)
        try:
            result = operation()
        except Exception:
            self._design = before
            raise
        self._undo.append(before)
        self._redo.clear()
        return result

    def undo(self) -> bool:
        if not self._undo:
            return False
        previous = self._undo.pop()
        self._redo.append(deepcopy(self._design))
        self._design = previous
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        following = self._redo.pop()
        self._undo.append(deepcopy(self._design))
        self._design = following
        return True

    def _scene_module(self, module_instance_id: str) -> dict[str, Any]:
        for item in self._scene.get("module_instances", []):
            if item.get("module_instance_id") == module_instance_id:
                return item
        raise KeyError(f"Scene module not found: {module_instance_id}")

    def _string(self, string_id: str) -> dict[str, Any]:
        for item in self._design.get("strings", []):
            if item.get("string_id") == string_id:
                return item
        raise KeyError(f"StringCircuit not found: {string_id}")

    def _mppt(self, mppt_instance_id: str) -> dict[str, Any]:
        for item in self._design.get("mppt_instances", []):
            if item.get("mppt_instance_id") == mppt_instance_id:
                return item
        raise KeyError(f"MPPTInstance not found: {mppt_instance_id}")

    def _inverter(self, inverter_instance_id: str) -> dict[str, Any]:
        for item in self._design.get("inverter_instances", []):
            if item.get("inverter_instance_id") == inverter_instance_id:
                return item
        raise KeyError(f"InverterInstance not found: {inverter_instance_id}")

    def _inverter_definition(
        self, inverter_instance: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        revision_id = str(inverter_instance["inverter_definition_revision_id"])
        try:
            return self._inverters[revision_id]
        except KeyError as exc:
            raise KeyError(
                f"inverter component revision not available: {revision_id}"
            ) from exc

    def _module_definition(
        self, revision_id: str
    ) -> Mapping[str, Any]:
        try:
            return self._modules[revision_id]
        except KeyError as exc:
            raise KeyError(
                f"module component revision not available: {revision_id}"
            ) from exc

    def _assert_unique_id(self, entity_id: str) -> None:
        existing = {
            str(item.get(key))
            for collection, key in (
                ("inverter_instances", "inverter_instance_id"),
                ("mppt_instances", "mppt_instance_id"),
                ("strings", "string_id"),
                ("connections", "connection_id"),
            )
            for item in self._design.get(collection, [])
            if item.get(key) is not None
        }
        if entity_id in existing:
            raise ValueError(f"duplicate electrical entity ID: {entity_id}")

    def _pcc_id(self) -> str:
        pcc_id = str(self._design.get("pcc_definition", {}).get("pcc_id") or "")
        if not pcc_id:
            raise ValueError("pcc_definition.pcc_id is required")
        return pcc_id

    def add_inverter(
        self,
        *,
        inverter_instance_id: str,
        inverter_definition_revision_id: str,
        name: str,
        location: Mapping[str, Any] | None = None,
        enabled: bool = True,
        connect_to_pcc: bool = True,
    ) -> dict[str, Any]:
        self._assert_unique_id(inverter_instance_id)
        try:
            definition = self._inverters[inverter_definition_revision_id]
        except KeyError as exc:
            raise KeyError(
                f"inverter component revision not available: "
                f"{inverter_definition_revision_id}"
            ) from exc
        snapshot = inverter_design_snapshot(definition)
        if snapshot["mppt_count"] < 1:
            raise ValueError("inverter revision has no usable MPPT definition")
        project_revision_id = self._require_project_revision_id()

        mppt_ids = [
            f"{inverter_instance_id}-mppt-{index:02d}"
            for index in range(1, snapshot["mppt_count"] + 1)
        ]
        for entity_id in mppt_ids:
            self._assert_unique_id(entity_id)

        connection_id = (
            f"{inverter_instance_id}-to-{self._pcc_id()}"
            if connect_to_pcc
            else None
        )
        if connection_id:
            self._assert_unique_id(connection_id)

        def operation() -> dict[str, Any]:
            inverter = {
                "inverter_instance_id": inverter_instance_id,
                "project_revision_id": project_revision_id,
                "inverter_definition_revision_id": (
                    inverter_definition_revision_id
                ),
                "name": name,
                "location": deepcopy(dict(location)) if location else None,
                "enabled": bool(enabled),
                "mppt_instance_ids": mppt_ids,
                "ac_connection_id": connection_id,
            }
            self._design["inverter_instances"].append(inverter)

            for mppt in snapshot["mppts"]:
                index = int(mppt["index"])
                self._design["mppt_instances"].append(
                    {
                        "mppt_instance_id": (
                            f"{inverter_instance_id}-mppt-{index:02d}"
                        ),
                        "inverter_instance_id": inverter_instance_id,
                        "mppt_definition_id": (
                            f"{inverter_definition_revision_id}:mppt:{index}"
                        ),
                        "index": index,
                        "connected_string_ids": [],
                        "enabled": bool(enabled),
                    }
                )

            if connection_id:
                self._design["connections"].append(
                    {
                        "connection_id": connection_id,
                        "project_revision_id": project_revision_id,
                        "from_node_id": inverter_instance_id,
                        "to_node_id": self._pcc_id(),
                        "connection_type": "pcc",
                        "phase": definition.get("phase_configuration"),
                        "conductor_reference": None,
                        "length_m": None,
                        "resistance_ohm": None,
                        "loss_model_id": None,
                        "enabled": bool(enabled),
                    }
                )
            return deepcopy(inverter)

        return self._mutate(operation)

    def create_string(
        self,
        *,
        string_id: str,
        module_instance_ids: Sequence[str],
        name: str | None = None,
        polarity: str = "normal",
        notes: str | None = None,
        take_from_unassigned: bool = False,
    ) -> dict[str, Any]:
        self._assert_unique_id(string_id)
        module_ids = _unique(module_instance_ids, "module_instance_ids")
        if polarity not in {"normal", "reversed", "unknown"}:
            raise ValueError("invalid string polarity")
        project_revision_id = self._require_project_revision_id()

        for module_id in module_ids:
            module = self._scene_module(module_id)
            if module.get("enabled") is not True:
                raise ValueError(f"module is disabled: {module_id}")

        already_used = {
            str(module_id): str(string["string_id"])
            for string in self._design.get("strings", [])
            for module_id in string.get("module_instance_ids", [])
        }
        conflicts = {
            module_id: already_used[module_id]
            for module_id in module_ids
            if module_id in already_used
        }
        assigned = {
            string["string_id"]: string
            for string in self._design["strings"]
            if string.get("target_mppt_instance_id")
            or any(string["string_id"] in mppt.get("connected_string_ids", [])
                   for mppt in self._design["mppt_instances"])
        }
        blocked = set(conflicts.values()) & assigned.keys()
        if blocked:
            descriptions = []
            for sid in sorted(blocked):
                target = assigned[sid].get("target_mppt_instance_id")
                mppt = next((m for m in self._design["mppt_instances"]
                             if m["mppt_instance_id"] == target or sid in m.get("connected_string_ids", [])), None)
                descriptions.append(f"{sid} on MPPT {mppt['index'] if mppt else target}")
            raise ValueError(
                f"These modules are already in {', '.join(descriptions)}. "
                f"Remove them from {', '.join(sorted(blocked))} first, or use Move module."
            )
        if conflicts and not take_from_unassigned:
            raise ValueError(f"modules already belong to strings: {conflicts}")
        taken_from = {}
        selected = set(module_ids)
        for string in self._design["strings"]:
            taken = [mid for mid in string["module_instance_ids"] if mid in selected]
            if taken:
                taken_from[string["string_id"]] = taken

        def operation() -> dict[str, Any]:
            deleted_string_ids = []
            for string in list(self._design["strings"]):
                if string["string_id"] in taken_from:
                    string["module_instance_ids"] = [mid for mid in string["module_instance_ids"] if mid not in selected]
                    if not string["module_instance_ids"]:
                        self._design["strings"].remove(string)
                        deleted_string_ids.append(string["string_id"])
            item = {
                "string_id": string_id,
                "project_revision_id": project_revision_id,
                "name": name or string_id,
                "module_instance_ids": module_ids,
                "target_mppt_instance_id": None,
                "enabled": False,
                "polarity": polarity,
                "cable_definition_id": None,
                "notes": notes,
                "topology_source": "manual",
            }
            self._design["strings"].append(item)
            return {**deepcopy(item), "taken_from": taken_from, "deleted_string_ids": deleted_string_ids}

        return self._mutate(operation)

    def _mppt_capacity(self, mppt: Mapping[str, Any]) -> int | None:
        inverter = self._inverter(str(mppt["inverter_instance_id"]))
        snapshot = inverter_design_snapshot(
            self._inverter_definition(inverter)
        )
        match = next(
            (
                item
                for item in snapshot["mppts"]
                if int(item["index"]) == int(mppt["index"])
            ),
            None,
        )
        if match is None or match.get("input_count") is None:
            return None
        return int(match["input_count"])

    def assign_strings_to_mppt(
        self,
        string_ids: Sequence[str],
        *,
        mppt_instance_id: str,
        enable: bool = True,
    ) -> dict[str, Any]:
        ids = _unique(string_ids, "string_ids")
        target = self._mppt(mppt_instance_id)
        strings = [self._string(string_id) for string_id in ids]

        existing = [
            str(value)
            for value in target.get("connected_string_ids", [])
            if str(value) not in ids
        ]
        capacity = self._mppt_capacity(target)
        if capacity is not None and len(existing) + len(ids) > capacity:
            raise ValueError(
                f"MPPT {mppt_instance_id} has {capacity} verified DC inputs; "
                f"assignment would use {len(existing) + len(ids)}"
            )

        def operation() -> dict[str, Any]:
            for string in strings:
                old_target = string.get("target_mppt_instance_id")
                if old_target:
                    old_mppt = self._mppt(str(old_target))
                    old_mppt["connected_string_ids"] = sorted(
                        value
                        for value in old_mppt.get(
                            "connected_string_ids", []
                        )
                        if value != string["string_id"]
                    )
                string["target_mppt_instance_id"] = mppt_instance_id
                string["enabled"] = bool(enable)

            target["connected_string_ids"] = sorted(
                set(existing + ids)
            )
            return {
                "mppt_instance_id": mppt_instance_id,
                "assigned_string_ids": sorted(ids),
                "enabled": bool(enable),
            }

        return self._mutate(operation)

    def unassign_strings(
        self, string_ids: Sequence[str]
    ) -> tuple[str, ...]:
        ids = _unique(string_ids, "string_ids")
        strings = [self._string(string_id) for string_id in ids]

        def operation() -> tuple[str, ...]:
            for string in strings:
                target_id = string.get("target_mppt_instance_id")
                if target_id:
                    mppt = self._mppt(str(target_id))
                    mppt["connected_string_ids"] = sorted(
                        value
                        for value in mppt.get("connected_string_ids", [])
                        if value != string["string_id"]
                    )
                string["target_mppt_instance_id"] = None
                string["enabled"] = False
            return tuple(sorted(ids))

        return self._mutate(operation)

    def delete_string(self, string_id: str) -> None:
        self._string(string_id)

        def operation() -> None:
            for mppt in self._design.get("mppt_instances", []):
                mppt["connected_string_ids"] = [
                    value
                    for value in mppt.get("connected_string_ids", [])
                    if value != string_id
                ]
            self._design["strings"] = [
                item
                for item in self._design["strings"]
                if item["string_id"] != string_id
            ]

        self._mutate(operation)

    # ---- S14a string edits; each keeps strings and MPPT links consistent -------
    def _owner(self, module_instance_id: str) -> dict[str, Any]:
        self._scene_module(module_instance_id)
        for string in self._design.get("strings", []):
            if module_instance_id in string.get("module_instance_ids", []):
                return string
        raise ValueError(f"module {module_instance_id} is not in a string")

    def split_string(self, string_id: str, after_module_instance_id: str, new_string_id: str) -> dict[str, Any]:
        """The modules after `after_module_instance_id` become `new_string_id`; both keep the MPPT."""
        string = self._string(string_id)
        modules = list(string.get("module_instance_ids", []))
        if after_module_instance_id not in modules:
            raise ValueError(f"module {after_module_instance_id} is not in {string_id}")
        at = modules.index(after_module_instance_id)
        if at == len(modules) - 1:
            raise ValueError("splitting after the last module leaves nothing to split off")
        self._assert_unique_id(new_string_id)
        target = string.get("target_mppt_instance_id")
        if target:
            mppt = self._mppt(str(target))
            capacity = self._mppt_capacity(mppt)
            if capacity is not None and len(mppt.get("connected_string_ids", [])) + 1 > capacity:
                raise ValueError(f"MPPT {target} has {capacity} verified DC inputs; the split string needs one more")

        def operation() -> dict[str, Any]:
            string["module_instance_ids"] = modules[: at + 1]
            tail = {**deepcopy(string), "string_id": new_string_id, "name": new_string_id,
                    "module_instance_ids": modules[at + 1 :], "topology_source": f"split_string:{TOPOLOGY_EDITOR_VERSION}"}
            self._design["strings"].append(tail)
            if target:
                mppt = self._mppt(str(target))
                mppt["connected_string_ids"] = sorted(set(mppt.get("connected_string_ids", [])) | {new_string_id})
            return {"string_id": string_id, "new_string_id": new_string_id}

        return self._mutate(operation)

    def join_strings(self, first_string_id: str, second_string_id: str) -> dict[str, Any]:
        """`second` is appended to the end of `first` and removed; `first` keeps its MPPT."""
        if first_string_id == second_string_id:
            raise ValueError("join needs two different strings")
        first, second = self._string(first_string_id), self._string(second_string_id)

        def operation() -> dict[str, Any]:
            first["module_instance_ids"] = list(first["module_instance_ids"]) + list(second["module_instance_ids"])
            for mppt in self._design.get("mppt_instances", []):
                mppt["connected_string_ids"] = [v for v in mppt.get("connected_string_ids", []) if v != second_string_id]
            self._design["strings"] = [s for s in self._design["strings"] if s["string_id"] != second_string_id]
            return {"string_id": first_string_id, "removed_string_id": second_string_id}

        return self._mutate(operation)

    def reverse_string(self, string_id: str) -> dict[str, Any]:
        """Reverse the wiring order, so the string's two ends swap."""
        string = self._string(string_id)

        def operation() -> dict[str, Any]:
            string["module_instance_ids"] = list(reversed(string["module_instance_ids"]))
            return {"string_id": string_id}

        return self._mutate(operation)

    def move_module(self, module_instance_id: str, to_string_id: str | None = None, index: int | None = None) -> dict[str, Any]:
        """Take a module out of its string, optionally into `to_string_id` at `index` (None appends). A string left
        empty is deleted."""
        source = self._owner(module_instance_id)
        target = self._string(to_string_id) if to_string_id is not None else None
        if index is not None and (not isinstance(index, int) or index < 0):
            raise ValueError("index must be a non-negative integer")

        def operation() -> dict[str, Any]:
            source["module_instance_ids"] = [m for m in source["module_instance_ids"] if m != module_instance_id]
            if target is not None:
                ids = list(target["module_instance_ids"])
                ids.insert(len(ids) if index is None else min(index, len(ids)), module_instance_id)
                target["module_instance_ids"] = ids
            removed = None
            if not source["module_instance_ids"]:
                removed = source["string_id"]
                for mppt in self._design.get("mppt_instances", []):
                    mppt["connected_string_ids"] = [v for v in mppt.get("connected_string_ids", []) if v != removed]
                self._design["strings"] = [s for s in self._design["strings"] if s["string_id"] != removed]
            return {"module_instance_id": module_instance_id, "to_string_id": to_string_id, "removed_string_id": removed}

        return self._mutate(operation)

    def swap_modules(self, first_module_instance_id: str, second_module_instance_id: str) -> dict[str, Any]:
        """Exchange two strung modules' places (in one string or across two)."""
        if first_module_instance_id == second_module_instance_id:
            raise ValueError("swap needs two different modules")
        a, b = self._owner(first_module_instance_id), self._owner(second_module_instance_id)

        def operation() -> dict[str, Any]:
            ia = a["module_instance_ids"].index(first_module_instance_id)
            ib = b["module_instance_ids"].index(second_module_instance_id)
            a["module_instance_ids"][ia] = second_module_instance_id
            b["module_instance_ids"][ib] = first_module_instance_id
            return {"first_string_id": a["string_id"], "second_string_id": b["string_id"]}

        return self._mutate(operation)

    # S14b ---------------------------------------------------------------------------------------------------------

    def _policy(self) -> dict[str, Any]:
        policy = self._design.get("orientation_policy")
        return deepcopy(policy) if isinstance(policy, Mapping) else {"normal_angle_tolerance_deg": None, "overrides": []}

    def set_orientation_tolerance(self, tolerance_deg: float) -> dict[str, Any]:
        """The design's orientation tolerance: the largest angle between module normals that still counts as one
        orientation on an MPPT (for the checks and the execution plan)."""
        value = float(tolerance_deg)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError("tolerance_deg must be finite and non-negative")

        def operation() -> dict[str, Any]:
            policy = self._policy()
            policy["normal_angle_tolerance_deg"] = value
            policy.setdefault("overrides", [])
            self._design["orientation_policy"] = policy
            return {"normal_angle_tolerance_deg": value}

        return self._mutate(operation)

    def set_orientation_override(self, mppt_instance_id: str, reason: str | None = None) -> dict[str, Any]:
        """Accept a mixed orientation on one MPPT with a reason, or clear the override (None)."""
        self._mppt(mppt_instance_id)
        text = None if reason is None else str(reason).strip()
        if text is not None and not 1 <= len(text) <= 500:
            raise ValueError("an orientation override needs a reason of 1 to 500 characters")

        def operation() -> dict[str, Any]:
            policy = self._policy()
            overrides = [o for o in policy.get("overrides") or [] if o.get("mppt_instance_id") != mppt_instance_id]
            if text is not None:
                overrides.append({"mppt_instance_id": mppt_instance_id, "reason": text})
            policy["overrides"] = sorted(overrides, key=lambda o: o["mppt_instance_id"])
            self._design["orientation_policy"] = policy
            return {"mppt_instance_id": mppt_instance_id, "reason": text}

        return self._mutate(operation)

    def set_inverter_pairing(self, inverter_instance_id: str, pv_field_ids: Sequence[str]) -> dict[str, Any]:
        """The PV fields an inverter is paired with (advisory): the pool of notation Apply, and the kWp shown."""
        inverter = self._inverter(inverter_instance_id)
        known = {str(f["pv_field_id"]) for f in self._scene.get("pv_fields", [])}
        ids = list(dict.fromkeys(str(f) for f in pv_field_ids))
        unknown = [f for f in ids if f not in known]
        if unknown:
            raise ValueError(f"unknown PV fields: {unknown}")

        def operation() -> dict[str, Any]:
            if ids:
                inverter["paired_pv_field_ids"] = ids
            else:
                inverter.pop("paired_pv_field_ids", None)
            return {"inverter_instance_id": inverter_instance_id, "pv_field_ids": ids}

        return self._mutate(operation)

    # ---- USE1 inverter lifecycle --------------------------------------------------
    def _detach_mppts(self, mppt_ids: set[str]) -> list[str]:
        """Unassign the strings on these MPPTs, drop their orientation overrides; returns the unassigned string IDs."""
        released = []
        for string in self._design.get("strings", []):
            if string.get("target_mppt_instance_id") in mppt_ids:
                string["target_mppt_instance_id"] = None
                string["enabled"] = False
                released.append(str(string["string_id"]))
        policy = self._design.get("orientation_policy")
        if policy and policy.get("overrides"):
            policy["overrides"] = [o for o in policy["overrides"] if o.get("mppt_instance_id") not in mppt_ids]
        return sorted(released)

    def remove_inverter(self, inverter_instance_id: str) -> dict[str, Any]:
        """Remove an inverter, its MPPTs and its PCC connection; its strings stay, unassigned."""
        inverter = self._inverter(inverter_instance_id)

        def operation() -> dict[str, Any]:
            mppt_ids = {str(m["mppt_instance_id"]) for m in self._design["mppt_instances"]
                        if m["inverter_instance_id"] == inverter_instance_id}
            released = self._detach_mppts(mppt_ids)
            self._design["mppt_instances"] = [m for m in self._design["mppt_instances"]
                                              if m["inverter_instance_id"] != inverter_instance_id]
            self._design["connections"] = [c for c in self._design.get("connections", [])
                                           if c.get("connection_id") != inverter.get("ac_connection_id")]
            self._design["inverter_instances"] = [i for i in self._design["inverter_instances"]
                                                  if i["inverter_instance_id"] != inverter_instance_id]
            return {"inverter_instance_id": inverter_instance_id, "unassigned_string_ids": released}

        return self._mutate(operation)

    def change_inverter_definition(self, inverter_instance_id: str, inverter_definition_revision_id: str) -> dict[str, Any]:
        """Swap an inverter's component revision in place. Strings on MPPT k stay when the new revision has an MPPT k;
        the others become unassigned. The instance ID, name, pairing and PCC connection are kept."""
        inverter = self._inverter(inverter_instance_id)
        try:
            definition = self._inverters[inverter_definition_revision_id]
        except KeyError as exc:
            raise KeyError(f"inverter component revision not available: {inverter_definition_revision_id}") from exc
        snapshot = inverter_design_snapshot(definition)
        if snapshot["mppt_count"] < 1:
            raise ValueError("inverter revision has no usable MPPT definition")
        indices = [int(m["index"]) for m in snapshot["mppts"]]

        def operation() -> dict[str, Any]:
            mine = [m for m in self._design["mppt_instances"] if m["inverter_instance_id"] == inverter_instance_id]
            dropped = {str(m["mppt_instance_id"]) for m in mine if int(m["index"]) not in indices}
            released = self._detach_mppts(dropped)
            kept = {int(m["index"]): m for m in mine if int(m["index"]) in indices}
            others = [m for m in self._design["mppt_instances"] if m["inverter_instance_id"] != inverter_instance_id]
            rebuilt = []
            for index in indices:
                mppt = kept.get(index) or {
                    "mppt_instance_id": f"{inverter_instance_id}-mppt-{index:02d}",
                    "inverter_instance_id": inverter_instance_id, "index": index,
                    "connected_string_ids": [], "enabled": bool(inverter.get("enabled", True)),
                }
                mppt["mppt_definition_id"] = f"{inverter_definition_revision_id}:mppt:{index}"
                rebuilt.append(mppt)
            self._design["mppt_instances"] = others + rebuilt
            inverter["inverter_definition_revision_id"] = inverter_definition_revision_id
            inverter["mppt_instance_ids"] = [m["mppt_instance_id"] for m in rebuilt]
            for connection in self._design.get("connections", []):
                if connection.get("connection_id") == inverter.get("ac_connection_id"):
                    connection["phase"] = definition.get("phase_configuration")
            kept_strings = sorted(str(s) for m in rebuilt for s in m.get("connected_string_ids", []))
            return {"inverter_instance_id": inverter_instance_id,
                    "inverter_definition_revision_id": inverter_definition_revision_id,
                    "kept_string_ids": kept_strings, "unassigned_string_ids": released}

        return self._mutate(operation)

    def _new_string_ids(self, count: int) -> list[str]:
        used = {
            str(item.get(key))
            for collection, key in (("inverter_instances", "inverter_instance_id"), ("mppt_instances", "mppt_instance_id"),
                                    ("strings", "string_id"), ("connections", "connection_id"))
            for item in self._design.get(collection, []) if item.get(key) is not None
        }
        out, counter = [], 1
        while len(out) < count:
            if f"S{counter:03d}" not in used:
                out.append(f"S{counter:03d}")
            counter += 1
        return out

    def _new_string(self, string_id: str, module_ids: Sequence[str], source: str) -> dict[str, Any]:
        return {"string_id": string_id, "project_revision_id": self._require_project_revision_id(), "name": string_id,
                "module_instance_ids": list(module_ids), "target_mppt_instance_id": None, "enabled": False,
                "polarity": "normal", "cable_definition_id": None, "notes": None,
                "topology_source": f"{source}:{TOPOLOGY_EDITOR_VERSION}"}

    def apply_mppt_layout(self, inverter_instance_id: str, layout: Sequence[Sequence[int]],
                          pv_field_ids: Sequence[str] | None = None,
                          sources: Sequence[Sequence[str] | None] | None = None,
                          release_modules: bool = False) -> dict[str, Any]:
        """Make the inverter's MPPTs carry strings of these lengths (one list per MPPT, one length per input, 0 =
        empty). Matching strings stay; the inverter's other strings are unassigned; the rest come from unassigned
        strings of the right length in the pool, then from unstrung pool modules in row-major order.
        With `release_modules` (UXF3, U2-25: re-stringing an existing layout), the inverter's strings that are neither
        kept nor reused are deleted instead, and their modules join the unstrung pool for the new strings."""
        inverter = self._inverter(inverter_instance_id)
        mppts = sorted((m for m in self._design.get("mppt_instances", []) if m.get("inverter_instance_id") == inverter_instance_id),
                       key=lambda m: int(m["index"]))
        rows = [list(row) for row in layout]
        if len(rows) != len(mppts):
            raise ValueError(f"the layout has {len(rows)} MPPTs; inverter {inverter_instance_id} has {len(mppts)}")
        for i, row in enumerate(rows):
            if any(type(n) is not int or n < 0 for n in row):
                raise ValueError("string lengths must be whole numbers of 0 or more")
            used = sum(1 for n in row if n > 0)
            capacity = self._mppt_capacity(mppts[i])
            if capacity is not None and used > capacity:
                raise ValueError(f"MPPT {i + 1} would use {used} inputs; it has {capacity} verified DC inputs")
        pool = list(pv_field_ids or inverter.get("paired_pv_field_ids") or [])
        known = {str(f["pv_field_id"]) for f in self._scene.get("pv_fields", [])}
        if [f for f in pool if f not in known]:
            raise ValueError(f"unknown PV fields: {[f for f in pool if f not in known]}")
        in_pool = (lambda mid: True) if not pool else (lambda mid: str(self._scene_module(mid).get("pv_field_id")) in pool)

        if sources is not None:
            if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
                raise ValueError("sources must be a list of per-MPPT sources")
            if len(sources) != len(mppts):
                raise ValueError("sources length must equal the MPPT count")
            for source in sources:
                if source is not None and (not isinstance(source, Sequence) or isinstance(source, (str, bytes)) or not source
                        or any(not isinstance(f, str) or f not in known or (pool and f not in pool) for f in source)):
                    raise ValueError("each source must be non-empty, known PV fields inside the inverter pool")
        restricted = sources is not None and any(source is not None for source in sources)
        source_by_mppt = {str(m["mppt_instance_id"]): source for m, source in zip(mppts, sources or [None] * len(mppts))}
        def in_source(mid, mppt_id):
            source = source_by_mppt[mppt_id]
            return in_pool(mid) if source is None else str(self._scene_module(mid).get("pv_field_id")) in source

        strings = self._design.get("strings", [])
        mppt_ids = [str(m["mppt_instance_id"]) for m in mppts]
        mine = [s for s in strings if s.get("target_mppt_instance_id") in mppt_ids]
        kept: list[dict[str, Any]] = []
        wanted: list[tuple[str, int]] = []
        for mppt_id, row in zip(mppt_ids, rows):
            for n in (n for n in row if n > 0):
                match = next((s for s in mine if s not in kept and s["target_mppt_instance_id"] == mppt_id
                              and len(s["module_instance_ids"]) == n
                              and (not restricted or all(in_source(mid, mppt_id) for mid in s["module_instance_ids"]))), None)
                if match is not None:
                    kept.append(match)
                else:
                    wanted.append((mppt_id, n))
        released = [s for s in mine if s not in kept]
        free = [s for s in strings if (s.get("target_mppt_instance_id") is None or s in released)
                and s.get("module_instance_ids") and all(in_pool(m) for m in s["module_instance_ids"])]
        plan: list[tuple[str, dict[str, Any] | None, list[str] | None]] = []
        for mppt_id, n in wanted:
            reuse = next((s for s in free if len(s["module_instance_ids"]) == n
                          and (not restricted or all(in_source(mid, mppt_id) for mid in s["module_instance_ids"]))), None)
            if reuse is not None:
                free.remove(reuse)
                plan.append((mppt_id, reuse, None))
                continue
            plan.append((mppt_id, None, None))
        reused_strings = [string for _, string, _ in plan if string is not None]
        # Only strings wholly inside the pool are deleted; one reaching outside stays, unassigned, as before.
        dropped = [string for string in released if not any(string is r for r in reused_strings)
                   and all(in_pool(str(m)) for m in string.get("module_instance_ids", []))] if release_modules else []
        strung = {str(m) for s in strings if not any(s is d for d in dropped) for m in s.get("module_instance_ids", [])}
        candidates = [str(m["module_instance_id"]) for m in self._scene.get("module_instances", [])
                      if m.get("enabled") is True and str(m["module_instance_id"]) not in strung and in_pool(str(m["module_instance_id"]))]
        unstrung = self._ordered_modules(candidates, ordering="row_major") if candidates else []
        fresh = [(i, n) for i, (_, n) in enumerate(wanted) if plan[i][1] is None]
        if restricted:
            # Reserve constrained pools before an "any" row can consume them; keep emission in layout order.
            fresh.sort(key=lambda item: source_by_mppt[plan[item[0]][0]] is None)
        for index, n in fresh:
            mppt_id = plan[index][0]
            available = [mid for mid in unstrung if in_source(mid, mppt_id)] if restricted else unstrung
            if len(available) < n:
                held = {str(mid) for s in released if s not in reused_strings
                        and all(in_pool(str(m)) for m in s["module_instance_ids"])
                        for mid in s["module_instance_ids"]}
                total_available = set(candidates) | held | {
                    str(mid) for s in kept + reused_strings for mid in s["module_instance_ids"]}
                message = (f"not enough unstrung modules: this layout needs {sum(sum(row) for row in rows)} modules; "
                           f"{len(total_available)} are available for {inverter.get('name') or inverter_instance_id}.")
                if restricted:
                    source = ", ".join(source_by_mppt[mppt_id] or pool) or "any"
                    message += (f" MPPT {mppt_ids.index(mppt_id) + 1} source fields {source} "
                                f"need {sum(rows[mppt_ids.index(mppt_id)])} modules; "
                                f"{sum(in_source(mid, mppt_id) for mid in total_available)} are available.")
                message += " Use fewer or shorter strings."
                if not release_modules and held:
                    message += (f" Its current strings hold {len(held)} of them; apply from the Systems table "
                                "or the Electrical step to re-use them.")
                raise ValueError(message)
            chosen = available[:n]
            plan[index] = (mppt_id, None, chosen)
            used = set(chosen)
            unstrung = [mid for mid in unstrung if mid not in used]
        new_ids = iter(self._new_string_ids(sum(1 for _, _, ids in plan if ids is not None)))

        def operation() -> dict[str, Any]:
            if dropped:
                gone = {str(d["string_id"]) for d in dropped}
                self._design["strings"] = [item for item in self._design["strings"] if str(item["string_id"]) not in gone]
                for mppt in self._design.get("mppt_instances", []):
                    mppt["connected_string_ids"] = [v for v in mppt.get("connected_string_ids", []) if v not in gone]
            for string in released:
                if any(string is d for d in dropped):
                    continue
                string["target_mppt_instance_id"], string["enabled"] = None, False
            reused, created = [], []
            targets: dict[str, list[str]] = {m: [str(s["string_id"]) for s in kept if s["target_mppt_instance_id"] == m] for m in mppt_ids}
            for mppt_id, string, ids in plan:
                if string is None:
                    string = self._new_string(next(new_ids), ids, "apply_mppt_layout")
                    self._design["strings"].append(string)
                    created.append(string["string_id"])
                else:
                    reused.append(string["string_id"])
                string["target_mppt_instance_id"], string["enabled"] = mppt_id, True
                targets[mppt_id].append(str(string["string_id"]))
            for mppt in mppts:
                mppt["connected_string_ids"] = sorted(targets[str(mppt["mppt_instance_id"])])
            return {"inverter_instance_id": inverter_instance_id, "kept_string_ids": sorted(s["string_id"] for s in kept),
                    "unassigned_string_ids": sorted(s["string_id"] for s in released if s.get("target_mppt_instance_id") is None
                                                    and not any(s is d for d in dropped)),
                    **({"deleted_string_ids": sorted(str(d["string_id"]) for d in dropped)} if release_modules else {}),
                    "reused_string_ids": sorted(reused), "created_string_ids": created}

        return self._mutate(operation)

    def _explicit_table(self, pv_field_id: str, table_id: str) -> dict[str, Any]:
        field = next((f for f in self._scene.get("pv_fields", []) if f.get("pv_field_id") == pv_field_id), None)
        if field is None:
            raise ValueError(f"unknown PV field: {pv_field_id}")
        if field.get("field_kind") != "explicit_layout":
            raise ValueError(f"PV field {pv_field_id} has no tables yet: replicate works on explicit tables (the table "
                             "model for generated fields is row 14)")
        table = next((t for t in field.get("tables", []) if t.get("table_id") == table_id), None)
        if table is None:
            raise ValueError(f"unknown table {table_id} in PV field {pv_field_id}")
        return table

    def replicate_pattern(self, source_pv_field_id: str, source_table_id: str,
                          targets: Sequence[Mapping[str, str]] | None = None) -> dict[str, Any]:
        """Copy the wiring of the strings lying wholly inside an explicit table, slot by slot, onto identical,
        unwired tables (by default every identical table in every field). Partly wired targets are skipped."""
        source = self._explicit_table(source_pv_field_id, source_table_id)
        slots: dict[tuple[str, str], dict[tuple[int, int], str]] = {}
        for m in self._scene.get("module_instances", []):
            if m.get("enabled") is True and m.get("table_id") is not None:
                slots.setdefault((str(m["pv_field_id"]), str(m["table_id"])), {})[(int(m["row_index"]), int(m["column_index"]))] = str(m["module_instance_id"])
        key = (source_pv_field_id, source_table_id)
        slot_of = {mid: slot for slot, mid in slots.get(key, {}).items()}
        strings = self._design.get("strings", [])
        pattern = [[slot_of[m] for m in s["module_instance_ids"]] for s in strings
                   if s.get("module_instance_ids") and all(m in slot_of for m in s["module_instance_ids"])]
        if not pattern:
            raise ValueError(f"wire table {source_table_id} first: no string lies wholly inside it")

        def signature(table, table_key):
            return (table["modules_across"], table["modules_up"], table["module_orientation"],
                    table["module_definition_revision_id"], frozenset(slots.get(table_key, {})))

        wanted = signature(source, key)
        if targets is None:
            chosen = [(str(f["pv_field_id"]), str(t["table_id"])) for f in self._scene.get("pv_fields", [])
                      if f.get("field_kind") == "explicit_layout" for t in f.get("tables", [])
                      if (str(f["pv_field_id"]), str(t["table_id"])) != key and signature(t, (str(f["pv_field_id"]), str(t["table_id"]))) == wanted]
        else:
            chosen = []
            for target in targets:
                tkey = (str(target["pv_field_id"]), str(target["table_id"]))
                if tkey == key:
                    raise ValueError("the source table can't be its own target")
                if signature(self._explicit_table(*tkey), tkey) != wanted:
                    raise ValueError(f"table {tkey[1]} in PV field {tkey[0]} is not identical to the source table")
                chosen.append(tkey)
        strung = {str(m) for s in strings for m in s.get("module_instance_ids", [])}
        copies, skipped = [], []
        for tkey in chosen:
            mapped = [[slots[tkey][slot] for slot in string] for string in pattern]
            if any(m in strung for ids in mapped for m in ids):
                skipped.append({"pv_field_id": tkey[0], "table_id": tkey[1], "reason": "already wired"})
            else:
                copies.append((tkey, mapped))
        if not copies:
            raise ValueError("no identical, unwired table to copy the pattern to")
        new_ids = iter(self._new_string_ids(sum(len(mapped) for _, mapped in copies)))

        def operation() -> dict[str, Any]:
            created = []
            for _, mapped in copies:
                for ids in mapped:
                    string = self._new_string(next(new_ids), ids, "replicate_pattern")
                    self._design["strings"].append(string)
                    created.append(string["string_id"])
            return {"copied": [{"pv_field_id": k[0], "table_id": k[1]} for k, _ in copies], "skipped": skipped,
                    "created_string_ids": created}

        return self._mutate(operation)

    def _ordered_modules(
        self,
        module_instance_ids: Sequence[str],
        *,
        ordering: str,
    ) -> list[str]:
        ids = _unique(module_instance_ids, "module_instance_ids")
        modules = [self._scene_module(module_id) for module_id in ids]
        if any(module.get("enabled") is not True for module in modules):
            raise ValueError("automatic stringing requires enabled modules")
        if ordering == "selection":
            return ids
        if ordering == "row_major":
            return [
                str(item["module_instance_id"])
                for item in sorted(modules, key=_module_sort_key)
            ]
        if ordering == "serpentine":
            # Row-major per field, with every other row of a field reversed (S14a), so a string runs back and
            # forth along the rows instead of returning to the start of each row.
            ordered = sorted(modules, key=_module_sort_key)
            result: list[str] = []
            rows: dict[tuple[str, int], list[str]] = {}
            for item in ordered:
                rows.setdefault((str(item.get("pv_field_id") or ""), int(item.get("row_index") or 0)), []).append(
                    str(item["module_instance_id"]))
            parity: dict[str, int] = {}
            for (field_id, _), row in rows.items():
                count = parity.get(field_id, 0)
                result.extend(reversed(row) if count % 2 else row)
                parity[field_id] = count + 1
            return result
        raise ValueError("ordering must be selection, row_major or serpentine")

    def create_strings(
        self,
        module_instance_ids: Sequence[str],
        *,
        string_length: int,
        id_prefix: str = "S",
        ordering: str = "row_major",
        remainder_policy: str = "error",
    ) -> tuple[str, ...]:
        """Explicit deterministic Create Strings automation command."""
        if not isinstance(string_length, int) or string_length < 1:
            raise ValueError("string_length must be an integer >= 1")
        if not id_prefix:
            raise ValueError("id_prefix must not be empty")
        ordered = self._ordered_modules(
            module_instance_ids, ordering=ordering
        )
        remainder = len(ordered) % string_length
        if remainder and remainder_policy == "error":
            raise ValueError(
                "selected module count is not divisible by string_length"
            )
        if remainder_policy not in {"error", "allow_shorter"}:
            raise ValueError(
                "remainder_policy must be error or allow_shorter"
            )

        used_modules = {
            str(module_id)
            for string in self._design.get("strings", [])
            for module_id in string.get("module_instance_ids", [])
        }
        duplicate = sorted(set(ordered) & used_modules)
        if duplicate:
            raise ValueError(
                f"modules already belong to strings: {duplicate}"
            )

        chunks = [
            ordered[index : index + string_length]
            for index in range(0, len(ordered), string_length)
        ]
        existing_ids = {
            str(item.get(key))
            for collection, key in (
                ("inverter_instances", "inverter_instance_id"),
                ("mppt_instances", "mppt_instance_id"),
                ("strings", "string_id"),
                ("connections", "connection_id"),
            )
            for item in self._design.get(collection, [])
            if item.get(key) is not None
        }
        generated: list[str] = []
        counter = 1
        for _ in chunks:
            while f"{id_prefix}{counter:03d}" in existing_ids:
                counter += 1
            generated.append(f"{id_prefix}{counter:03d}")
            existing_ids.add(generated[-1])
            counter += 1

        project_revision_id = self._require_project_revision_id()

        def operation() -> tuple[str, ...]:
            for string_id, module_ids in zip(generated, chunks):
                self._design["strings"].append(
                    {
                        "string_id": string_id,
                        "project_revision_id": project_revision_id,
                        "name": string_id,
                        "module_instance_ids": list(module_ids),
                        "target_mppt_instance_id": None,
                        "enabled": False,
                        "polarity": "normal",
                        "cable_definition_id": None,
                        "notes": None,
                        "topology_source": (
                            f"create_strings:{ordering}:"
                            f"{TOPOLOGY_EDITOR_VERSION}"
                        ),
                    }
                )
            return tuple(generated)

        return self._mutate(operation)

    def _assignment_context(
        self, inverter_instance_id: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        inverter = self._inverter(inverter_instance_id)
        snapshot = inverter_design_snapshot(
            self._inverter_definition(inverter)
        )
        mppts = sorted(
            [
                item
                for item in self._design.get("mppt_instances", [])
                if item.get("inverter_instance_id")
                == inverter_instance_id
            ],
            key=lambda item: int(item["index"]),
        )
        if len(mppts) != snapshot["mppt_count"]:
            raise ValueError(
                "canonical MPPT instances do not match bound inverter revision"
            )
        return inverter, mppts, snapshot

    def _balanced_assignment(
        self,
        string_ids: Sequence[str],
        inverter_instance_id: str,
        compatibility_keys=None,
    ) -> dict[int, tuple[str, ...]]:
        ids = _unique(string_ids, "string_ids")
        for string_id in ids:
            self._string(string_id)
        _, mppts, snapshot = self._assignment_context(
            inverter_instance_id
        )

        capacities = [
            item.get("input_count") for item in snapshot["mppts"]
        ]
        if compatibility_keys is not None:
            keys = {sid: compatibility_keys[sid] for sid in ids}
            if len(set(keys.values())) > 1:
                return self._grouped_assignment(ids, keys, mppts, capacities)
        known_capacities = [
            int(value) for value in capacities if value is not None
        ]
        total_input_count = (
            sum(known_capacities)
            if len(known_capacities) == len(capacities)
            else None
        )
        assignment = balanced_string_assignment(
            sorted(ids),
            mppt_count=len(mppts),
            total_input_count=total_input_count,
        )

        uniform_capacity = None
        if capacities and all(
            value is not None and value == capacities[0]
            for value in capacities
        ):
            uniform_capacity = int(capacities[0])

        normalized = validate_mppt_assignment(
            assignment,
            string_ids=sorted(ids),
            mppt_count=len(mppts),
            total_input_count=total_input_count,
            input_count_per_mppt=uniform_capacity,
        )
        for mppt, spec in zip(mppts, snapshot["mppts"]):
            capacity = spec.get("input_count")
            if capacity is not None and len(
                normalized[int(mppt["index"])]
            ) > int(capacity):
                raise ValueError(
                    f"balanced assignment exceeds verified input count "
                    f"for MPPT index {mppt['index']}"
                )
        return normalized

    @staticmethod
    def _grouped_assignment(ids, keys, mppts, capacities):
        """Reserve each usable tracker for a single opaque compatibility key."""
        groups = {}
        for sid in sorted(ids):
            groups.setdefault(keys[sid], []).append(sid)
        available = [(m, cap) for m, cap in zip(mppts, capacities) if m.get("enabled")]
        assignment = {int(m["index"]): () for m in mppts}
        # Largest groups/capacities first; no partial edit occurs if capacity is lacking.
        ordered = sorted(groups.values(), key=lambda values: (-len(values), values[0]))
        reserved = []
        for values in ordered:
            chosen, remaining = [], len(values)
            available.sort(key=lambda item: (-(int(item[1]) if item[1] is not None else len(ids)), int(item[0]["index"])))
            while remaining > 0:
                if not available:
                    raise ValueError("Not enough compatible MPPT inputs; put each kind of string on its own MPPT or add an inverter.")
                mppt, cap = available.pop(0)
                size = min(remaining, int(cap) if cap is not None else remaining)
                chosen.append((mppt, int(cap) if cap is not None else len(ids)))
                remaining -= size
            reserved.append((values, chosen))
        # Use spare trackers to balance within groups, without mixing their states.
        for mppt, cap in sorted(available, key=lambda item: int(item[0]["index"])):
            eligible = [(values, chosen) for values, chosen in reserved if len(chosen) < len(values)]
            if not eligible:
                break
            values, chosen = min(eligible, key=lambda item: (-len(item[0])/len(item[1]), item[0][0]))
            chosen.append((mppt, int(cap) if cap is not None else len(ids)))
        for values, chosen in reserved:
            buckets = {int(m["index"]): [] for m, _ in chosen}
            limits = {int(m["index"]): cap for m, cap in chosen}
            for sid in values:
                candidates = [i for i in buckets if len(buckets[i]) < limits[i]]
                index = min(candidates, key=lambda i: (len(buckets[i]), i))
                buckets[index].append(sid)
            assignment.update({i: tuple(values) for i, values in buckets.items()})
        return assignment

    def assign_strings(
        self,
        string_ids: Sequence[str],
        *,
        inverter_instance_id: str,
        compatibility_keys=None,
    ) -> dict[int, tuple[str, ...]]:
        """Explicit Assign Strings automation for an otherwise empty inverter bank."""
        ids = _unique(string_ids, "string_ids")
        _, mppts, _ = self._assignment_context(inverter_instance_id)
        selected = set(ids)
        occupied_by_others = sorted(
            {
                str(string_id)
                for mppt in mppts
                for string_id in mppt.get("connected_string_ids", [])
                if str(string_id) not in selected
            }
        )
        if occupied_by_others:
            raise ValueError(
                "Assign Strings will not move existing unselected strings; "
                "use Balance MPPT explicitly"
            )
        assignment = self._balanced_assignment(
            ids, inverter_instance_id, compatibility_keys
        )

        def operation() -> dict[int, tuple[str, ...]]:
            for mppt in mppts:
                mppt["connected_string_ids"] = []
            for string_id in ids:
                string = self._string(string_id)
                old_target = string.get("target_mppt_instance_id")
                if old_target:
                    old = self._mppt(str(old_target))
                    old["connected_string_ids"] = [
                        value
                        for value in old.get("connected_string_ids", [])
                        if value != string_id
                    ]

            by_index = {
                int(item["index"]): item for item in mppts
            }
            for index, assigned in assignment.items():
                mppt = by_index[index]
                mppt["connected_string_ids"] = list(assigned)
                for string_id in assigned:
                    string = self._string(string_id)
                    string["target_mppt_instance_id"] = (
                        mppt["mppt_instance_id"]
                    )
                    string["enabled"] = True
            return deepcopy(assignment)

        return self._mutate(operation)

    def balance_mppt(
        self, inverter_instance_id: str, *, compatibility_keys=None
    ) -> dict[int, tuple[str, ...]]:
        """Explicitly rebalance all strings currently assigned to one inverter."""
        _, mppts, _ = self._assignment_context(inverter_instance_id)
        ids = sorted(
            {
                str(string_id)
                for mppt in mppts
                for string_id in mppt.get("connected_string_ids", [])
            }
        )
        if not ids:
            raise ValueError("inverter has no assigned strings to balance")
        assignment = self._balanced_assignment(
            ids, inverter_instance_id, compatibility_keys
        )

        def operation() -> dict[int, tuple[str, ...]]:
            by_index = {
                int(item["index"]): item for item in mppts
            }
            for mppt in mppts:
                mppt["connected_string_ids"] = []
            for index, assigned in assignment.items():
                mppt = by_index[index]
                mppt["connected_string_ids"] = list(assigned)
                for string_id in assigned:
                    string = self._string(string_id)
                    string["target_mppt_instance_id"] = (
                        mppt["mppt_instance_id"]
                    )
                    string["enabled"] = True
            return deepcopy(assignment)

        return self._mutate(operation)

    def suggest_string_length(
        self,
        *,
        module_definition_revision_id: str,
        inverter_instance_id: str,
        mppt_index: int | None = None,
    ) -> dict[str, Any]:
        """Reference-condition-only advisory. Phase 4.7 owns design validation."""
        module = module_design_snapshot(
            self._module_definition(module_definition_revision_id)
        )
        inverter, _, inv = self._assignment_context(
            inverter_instance_id
        )
        stc = module["stc"]
        voc = float(stc["voc_v"])
        vmp = float(stc["vmp_v"])
        if voc <= 0.0 or vmp <= 0.0:
            raise ValueError("module STC Voc and Vmp must be positive")

        mppt_specs = inv["mppts"]
        if mppt_index is not None:
            mppt_specs = [
                item
                for item in mppt_specs
                if int(item["index"]) == int(mppt_index)
            ]
            if not mppt_specs:
                raise ValueError("requested MPPT index does not exist")

        min_mppt_voltage = max(
            float(item["min_operating_voltage_v"])
            for item in mppt_specs
            if item.get("min_operating_voltage_v") is not None
        )
        max_mppt_voltage = min(
            float(item["max_operating_voltage_v"])
            for item in mppt_specs
            if item.get("max_operating_voltage_v") is not None
        )
        absolute_voltage = float(
            inv["dc_limits"]["max_dc_voltage_v"]
        )
        module_system_voltage = module["string_design_limits"].get(
            "max_system_voltage_v"
        )
        if module_system_voltage is not None:
            absolute_voltage = min(
                absolute_voltage, float(module_system_voltage)
            )

        minimum_length = max(
            1, ceil(min_mppt_voltage / vmp)
        )
        maximum_length = min(
            floor(max_mppt_voltage / vmp),
            floor(absolute_voltage / voc),
        )
        if maximum_length < minimum_length:
            recommended = None
            status = "no_reference_condition_solution"
        else:
            nominal = inv["dc_limits"].get("nominal_dc_voltage_v")
            if nominal is not None:
                recommended = round(float(nominal) / vmp)
                recommended = max(
                    minimum_length,
                    min(maximum_length, recommended),
                )
            else:
                recommended = maximum_length
            status = "suggestion_available"

        return {
            "schema_name": "StringLengthSuggestion",
            "schema_version": "0.1",
            "editor_version": TOPOLOGY_EDITOR_VERSION,
            "engineering_state_mutated": False,
            "status": status,
            "module_definition_revision_id": (
                module_definition_revision_id
            ),
            "inverter_instance_id": inverter_instance_id,
            "inverter_definition_revision_id": inverter[
                "inverter_definition_revision_id"
            ],
            "mppt_index": mppt_index,
            "basis": "stc_reference_conditions_only",
            "minimum_modules_per_string": minimum_length,
            "maximum_modules_per_string": maximum_length,
            "recommended_modules_per_string": recommended,
            "reference_inputs": {
                "module_voc_v": voc,
                "module_vmp_v": vmp,
                "inverter_max_dc_voltage_v": inv["dc_limits"][
                    "max_dc_voltage_v"
                ],
                "effective_absolute_voltage_v": absolute_voltage,
                "mppt_min_operating_voltage_v": min_mppt_voltage,
                "mppt_max_operating_voltage_v": max_mppt_voltage,
                "inverter_nominal_dc_voltage_v": inv["dc_limits"].get(
                    "nominal_dc_voltage_v"
                ),
            },
            "validation_deferred": [
                "Voc @ minimum design temperature",
                "Vmpp @ low temperature",
                "Vmpp @ high temperature",
                "MPPT current",
                "Isc",
                "DC/AC ratio",
            ],
        }

    def inspect_inverter(
        self, inverter_instance_id: str
    ) -> dict[str, Any]:
        inverter, mppts, snapshot = self._assignment_context(
            inverter_instance_id
        )
        tree = []
        for mppt in mppts:
            strings = []
            for string_id in sorted(
                str(value)
                for value in mppt.get("connected_string_ids", [])
            ):
                string = self._string(string_id)
                strings.append(
                    {
                        "string_id": string_id,
                        "name": string["name"],
                        "module_count": len(
                            string["module_instance_ids"]
                        ),
                        "enabled": bool(string["enabled"]),
                    }
                )
            tree.append(
                {
                    "mppt_instance_id": mppt["mppt_instance_id"],
                    "index": int(mppt["index"]),
                    "enabled": bool(mppt["enabled"]),
                    "input_count": next(
                        (
                            item.get("input_count")
                            for item in snapshot["mppts"]
                            if int(item["index"])
                            == int(mppt["index"])
                        ),
                        None,
                    ),
                    "strings": strings,
                }
            )
        return {
            "inverter_instance_id": inverter_instance_id,
            "name": inverter["name"],
            "inverter_definition_revision_id": inverter[
                "inverter_definition_revision_id"
            ],
            "enabled": bool(inverter["enabled"]),
            "mppts": tree,
        }

    def topology_view(self) -> dict[str, Any]:
        assigned = {
            str(value)
            for mppt in self._design.get("mppt_instances", [])
            for value in mppt.get("connected_string_ids", [])
        }
        unassigned = [
            {
                "string_id": item["string_id"],
                "name": item["name"],
                "module_count": len(item["module_instance_ids"]),
                "enabled": bool(item["enabled"]),
            }
            for item in sorted(
                self._design.get("strings", []),
                key=lambda value: str(value["string_id"]),
            )
            if item["string_id"] not in assigned
        ]
        return {
            "schema_name": "ElectricalTopologyView",
            "schema_version": "0.1",
            "electrical_revision_id": self._design[
                "electrical_revision_id"
            ],
            "pcc_definition": deepcopy(
                self._design.get("pcc_definition", {})
            ),
            "inverters": [
                self.inspect_inverter(item["inverter_instance_id"])
                for item in sorted(
                    self._design.get("inverter_instances", []),
                    key=lambda value: str(
                        value["inverter_instance_id"]
                    ),
                )
            ],
            "unassigned_strings": unassigned,
        }

    def consistency_report(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []

        modules = {
            str(item["module_instance_id"])
            for item in self._scene.get("module_instances", [])
        }
        membership: dict[str, list[str]] = {}
        strings = {
            str(item["string_id"]): item
            for item in self._design.get("strings", [])
        }
        mppts = {
            str(item["mppt_instance_id"]): item
            for item in self._design.get("mppt_instances", [])
        }
        inverters = {
            str(item["inverter_instance_id"]): item
            for item in self._design.get("inverter_instances", [])
        }

        def add(severity: str, code: str, entity_id: str, message: str):
            findings.append(
                {
                    "severity": severity,
                    "code": code,
                    "entity_id": entity_id,
                    "message": message,
                }
            )

        for string_id, string in sorted(strings.items()):
            for module_id in string.get("module_instance_ids", []):
                module_id = str(module_id)
                membership.setdefault(module_id, []).append(string_id)
                if module_id not in modules:
                    add(
                        "error",
                        "string_unknown_module",
                        string_id,
                        f"String references unknown module {module_id}.",
                    )
            target_id = string.get("target_mppt_instance_id")
            if target_id is None:
                if string.get("enabled") is True:
                    add(
                        "error",
                        "enabled_string_unassigned",
                        string_id,
                        "Enabled string has no target MPPT.",
                    )
                else:
                    add(
                        "draft",
                        "string_unassigned",
                        string_id,
                        "String is not yet assigned to an MPPT.",
                    )
            else:
                mppt = mppts.get(str(target_id))
                if mppt is None:
                    add(
                        "error",
                        "string_unknown_mppt",
                        string_id,
                        f"String target MPPT does not exist: {target_id}.",
                    )
                elif string_id not in mppt.get(
                    "connected_string_ids", []
                ):
                    add(
                        "error",
                        "string_mppt_not_reciprocal",
                        string_id,
                        "String target and MPPT connected_string_ids do not reconcile.",
                    )

        for module_id, owners in sorted(membership.items()):
            if len(owners) > 1:
                add(
                    "error",
                    "module_in_multiple_strings",
                    module_id,
                    f"Module belongs to multiple strings: {sorted(owners)}.",
                )

        for mppt_id, mppt in sorted(mppts.items()):
            inverter_id = str(mppt["inverter_instance_id"])
            inverter = inverters.get(inverter_id)
            if inverter is None:
                add(
                    "error",
                    "mppt_unknown_inverter",
                    mppt_id,
                    f"MPPT references unknown inverter {inverter_id}.",
                )
            elif mppt_id not in inverter.get("mppt_instance_ids", []):
                add(
                    "error",
                    "mppt_inverter_not_reciprocal",
                    mppt_id,
                    "MPPT is not listed by its inverter instance.",
                )
            for string_id in mppt.get("connected_string_ids", []):
                string = strings.get(str(string_id))
                if string is None:
                    add(
                        "error",
                        "mppt_unknown_string",
                        mppt_id,
                        f"MPPT references unknown string {string_id}.",
                    )
                elif string.get(
                    "target_mppt_instance_id"
                ) != mppt_id:
                    add(
                        "error",
                        "mppt_string_not_reciprocal",
                        mppt_id,
                        f"MPPT/string assignment does not reconcile for {string_id}.",
                    )

        for inverter_id, inverter in sorted(inverters.items()):
            actual = sorted(
                mppt_id
                for mppt_id, mppt in mppts.items()
                if mppt["inverter_instance_id"] == inverter_id
            )
            declared = sorted(
                str(value)
                for value in inverter.get("mppt_instance_ids", [])
            )
            if actual != declared:
                add(
                    "error",
                    "inverter_mppt_list_inconsistent",
                    inverter_id,
                    "Inverter mppt_instance_ids do not match canonical MPPT instances.",
                )

        findings.sort(
            key=lambda item: (
                {"error": 0, "warning": 1, "draft": 2, "info": 3}[
                    item["severity"]
                ],
                item["code"],
                item["entity_id"],
            )
        )
        return {
            "schema_name": "ElectricalTopologyConsistencyReport",
            "schema_version": "0.1",
            "electrical_revision_id": self._design[
                "electrical_revision_id"
            ],
            "blocking_count": sum(
                1 for item in findings if item["severity"] == "error"
            ),
            "draft_count": sum(
                1 for item in findings if item["severity"] == "draft"
            ),
            "findings": findings,
        }

    def commit_revision(
        self,
        *,
        electrical_revision_id: str,
        revision_number: int,
        change_summary: str,
        created_by: str | None = None,
        created_at: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        if not electrical_revision_id:
            raise ValueError("electrical_revision_id must not be empty")
        if revision_number < 1:
            raise ValueError("revision_number must be at least 1")
        report = self.consistency_report()
        if report["blocking_count"]:
            raise ValueError(
                "electrical topology has blocking structural inconsistencies"
            )

        previous_revision_id = self._design[
            "electrical_revision_id"
        ]
        committed = deepcopy(self._design)
        committed["electrical_revision_id"] = electrical_revision_id
        committed["revision_number"] = revision_number
        committed["supersedes_revision_id"] = previous_revision_id
        committed["change_summary"] = change_summary
        committed["created_by"] = created_by
        committed["created_at"] = created_at or datetime.now(
            timezone.utc
        ).isoformat().replace("+00:00", "Z")
        committed["status"] = status
        committed["topology_editor_version"] = TOPOLOGY_EDITOR_VERSION
        self._design = committed
        self._undo.clear()
        self._redo.clear()
        return deepcopy(committed)
