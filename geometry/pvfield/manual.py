"""Manual PV module editing semantics for Phase 4.7H-B."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .packing import validate_field_layout


MANUAL_LAYOUT_EDIT_VERSION = "opensimpv-manual-layout-edit-0.1"


def affected_string_memberships(
    electrical_design: Mapping[str, Any] | None,
    module_instance_id: str,
) -> list[dict[str, Any]]:
    """Return identity-preserving electrical memberships for one moved module."""
    if electrical_design is None:
        return []
    result: list[dict[str, Any]] = []
    for string in sorted(
        electrical_design.get("strings", []),
        key=lambda item: str(item.get("string_id", "")),
    ):
        ids = [str(value) for value in string.get("module_instance_ids", [])]
        if module_instance_id not in ids:
            continue
        result.append(
            {
                "string_id": str(string["string_id"]),
                "membership_status": "identity_preserved_geometry_changed",
                "module_instance_id": module_instance_id,
            }
        )
    return result


def manual_module_edit_report(
    scene: Mapping[str, Any],
    *,
    pv_field_id: str,
    module_instance_id: str,
    edit_kind: str,
    before_transform: Mapping[str, Any],
    electrical_design: Mapping[str, Any] | None = None,
    snap: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, read-only result for one explicit manual edit."""
    module = next(
        (
            item
            for item in scene.get("module_instances", [])
            if str(item.get("module_instance_id")) == module_instance_id
        ),
        None,
    )
    if module is None:
        raise KeyError(f"module instance not found: {module_instance_id}")
    field = next(
        (
            item
            for item in scene.get("pv_fields", [])
            if str(item.get("pv_field_id")) == pv_field_id
        ),
        None,
    )
    if field is None:
        raise KeyError(f"PV field not found: {pv_field_id}")

    from .explicit import assert_generated_layout
    assert_generated_layout(field)
    if any(o.get('obstacle_type')=='imported_mesh' for o in scene.get('obstacles',[])):
        native={**scene,'obstacles':[o for o in scene['obstacles'] if o.get('obstacle_type')!='imported_mesh']}
        conflicts=validate_field_layout(native,pv_field_id)
        # Stored mechanical dimensions let the scene validator resolve legacy
        # modules only when a definition is supplied by its owning service.
        # Physical mesh gating is performed there on the full scene.
    else:
        conflicts = validate_field_layout(scene, pv_field_id)
    return {
        "schema_name": "ManualModuleEditReport",
        "schema_version": "0.1",
        "manual_edit_version": MANUAL_LAYOUT_EDIT_VERSION,
        "pv_field_id": pv_field_id,
        "module_instance_id": module_instance_id,
        "edit_kind": edit_kind,
        "identity_preserved": True,
        "before_transform": deepcopy(dict(before_transform)),
        "after_transform": deepcopy(dict(module["transform"])),
        "field_layout_status": str(field.get("layout_status")),
        "manual_position_override": bool(
            (module.get("metadata") or {}).get(
                "manual_position_override", False
            )
        ),
        "conflict_report": conflicts,
        "affected_strings": affected_string_memberships(
            electrical_design, module_instance_id
        ),
        "electrical_design_mutated": False,
        "snap": deepcopy(dict(snap)) if snap is not None else None,
    }
