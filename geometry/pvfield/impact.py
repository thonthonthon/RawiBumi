"""Read-only PV field layout delta and electrical topology impact analysis."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping

from .identity import (
    MODULE_IDENTITY_VERSION,
    packing_slot_key,
    placement_fingerprint,
)


LAYOUT_IMPACT_VERSION = "opensimpv-layout-impact-0.1"


def _field(scene: Mapping[str, Any], pv_field_id: str) -> Mapping[str, Any]:
    for item in scene.get("pv_fields", []):
        if item.get("pv_field_id") == pv_field_id:
            return item
    raise KeyError(f"PV field not found: {pv_field_id}")


def _modules(
    scene: Mapping[str, Any], pv_field_id: str
) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["module_instance_id"]): item
        for item in scene.get("module_instances", [])
        if item.get("pv_field_id") == pv_field_id
    }


def _position(module: Mapping[str, Any]) -> list[float]:
    transform = module["transform"]
    return [
        float(transform["position_x_m"]),
        float(transform["position_y_m"]),
    ]


def _impact_hash(report: Mapping[str, Any]) -> str:
    payload = {key: deepcopy(value) for key, value in report.items() if key != "impact_hash"}
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def layout_impact_report(
    before_scene: Mapping[str, Any],
    after_scene: Mapping[str, Any],
    pv_field_id: str,
    *,
    electrical_design: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare one generated field before/after an explicit layout operation.

    Electrical topology is never mutated. String references to module IDs that
    no longer exist are reported as stale references requiring engineer review.
    """
    before_field = _field(before_scene, pv_field_id)
    after_field = _field(after_scene, pv_field_id)
    before = _modules(before_scene, pv_field_id)
    after = _modules(after_scene, pv_field_id)

    retained: list[str] = []
    moved: list[dict[str, Any]] = []
    removed_ids = set(before) - set(after)
    added_ids = set(after) - set(before)

    for module_id in sorted(set(before).intersection(after)):
        if placement_fingerprint(before_field, before[module_id]) == placement_fingerprint(
            after_field, after[module_id]
        ):
            retained.append(module_id)
        else:
            moved.append(
                {
                    "slot_key": packing_slot_key(after[module_id])
                    or packing_slot_key(before[module_id]),
                    "old_module_instance_id": module_id,
                    "new_module_instance_id": module_id,
                    "old_position_xy_m": _position(before[module_id]),
                    "new_position_xy_m": _position(after[module_id]),
                    "identity_preserved": True,
                }
            )

    old_by_slot: dict[str, str] = {}
    for module_id in sorted(removed_ids):
        slot = packing_slot_key(before[module_id])
        if slot is not None and slot not in old_by_slot:
            old_by_slot[slot] = module_id

    new_by_slot: dict[str, str] = {}
    for module_id in sorted(added_ids):
        slot = packing_slot_key(after[module_id])
        if slot is not None and slot not in new_by_slot:
            new_by_slot[slot] = module_id

    for slot in sorted(set(old_by_slot).intersection(new_by_slot)):
        old_id = old_by_slot[slot]
        new_id = new_by_slot[slot]
        moved.append(
            {
                "slot_key": slot,
                "old_module_instance_id": old_id,
                "new_module_instance_id": new_id,
                "old_position_xy_m": _position(before[old_id]),
                "new_position_xy_m": _position(after[new_id]),
                "identity_preserved": False,
            }
        )
        removed_ids.discard(old_id)
        added_ids.discard(new_id)

    moved.sort(
        key=lambda item: (
            str(item.get("slot_key") or ""),
            str(item["old_module_instance_id"]),
            str(item["new_module_instance_id"]),
        )
    )
    invalidated_ids = sorted(
        set(removed_ids)
        | {
            str(item["old_module_instance_id"])
            for item in moved
            if not item["identity_preserved"]
        }
    )

    affected_strings: list[dict[str, Any]] = []
    if electrical_design is not None:
        invalidated = set(invalidated_ids)
        before_ids = set(before)
        after_ids = set(after)
        for string in sorted(
            electrical_design.get("strings", []),
            key=lambda item: str(item.get("string_id", "")),
        ):
            referenced = {
                str(value) for value in string.get("module_instance_ids", [])
            }
            referenced_field_ids = referenced.intersection(before_ids)
            if not referenced_field_ids:
                continue
            stale = sorted(invalidated.intersection(referenced_field_ids))
            unresolved = sorted(referenced_field_ids - after_ids)
            if stale or unresolved:
                affected_strings.append(
                    {
                        "string_id": str(string["string_id"]),
                        "referenced_invalidated_module_ids": stale,
                        "unresolved_module_instance_ids": unresolved,
                        "membership_status": "stale_reference",
                    }
                )

    report: dict[str, Any] = {
        "schema_name": "PVFieldLayoutImpactReport",
        "schema_version": "0.1",
        "impact_version": LAYOUT_IMPACT_VERSION,
        "module_identity_version": MODULE_IDENTITY_VERSION,
        "pv_field_id": pv_field_id,
        "before_scene_revision_id": str(before_scene.get("revision_id") or ""),
        "after_scene_revision_id": str(after_scene.get("revision_id") or ""),
        "retained_module_ids": sorted(retained),
        "moved_modules": moved,
        "removed_module_ids": sorted(removed_ids),
        "added_module_ids": sorted(added_ids),
        "invalidated_module_ids": invalidated_ids,
        "affected_strings": affected_strings,
        "topology_status": "review_required" if affected_strings else "unchanged",
        "electrical_design_mutated": False,
    }
    report["impact_hash"] = _impact_hash(report)
    return report
