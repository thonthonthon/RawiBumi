"""Stable generated ModuleInstance identity semantics for Phase 4.7H-A.

A generated-field rebuild is allowed to preserve an existing module ID only when
that generated physical placement is unchanged. Newly created or changed
placements receive deterministic placement-derived IDs.

Phase 4.7H-B freezes the complementary manual-edit rule: an explicit
engineer-authored move preserves the existing object identity, while a later
generated rebuild still uses replacement semantics and collision guards.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


MODULE_IDENTITY_VERSION = "opensimpv-module-placement-identity-0.1"
MODULE_REPLACEMENT_IDENTITY_VERSION = "opensimpv-module-replacement-identity-0.1"
_ID_DECIMALS = 9


def _number(value: Any) -> str:
    resolved = round(float(value), _ID_DECIMALS)
    if resolved == 0.0:
        resolved = 0.0
    return f"{resolved:.{_ID_DECIMALS}f}"


def _orientation(field: Mapping[str, Any]) -> str:
    footprint = field.get("module_footprint") or {}
    return str(footprint.get("orientation") or field.get("orientation") or "")


def placement_identity_payload(
    field: Mapping[str, Any],
    module: Mapping[str, Any],
) -> dict[str, str]:
    """Return the canonical generated-placement identity payload.

    The payload intentionally excludes component revision and physical module
    dimensions. Rebinding a same-size/same-placement component does not by
    itself create a different physical placement identity. Position Z is intentionally excluded. Phase 4.7H-C freezes it as a canonical
    derived coordinate from support-plane elevation at the module XY plus the
    vertical mounting-height offset; changing the support plane does not by
    itself replace the ModuleInstance object.
    """
    transform = module["transform"]
    azimuth = float(transform.get("rotation_z_deg", field.get("azimuth_deg", 0.0)))
    return {
        "identity_version": MODULE_IDENTITY_VERSION,
        "pv_field_id": str(field["pv_field_id"]),
        "support_surface_id": str(field["support_surface_id"]),
        "position_x_m": _number(transform["position_x_m"]),
        "position_y_m": _number(transform["position_y_m"]),
        "rotation_z_deg": _number(azimuth % 360.0),
        "orientation": _orientation(field),
        "tilt_deg": _number(field.get("tilt_deg", 0.0)),
        "mounting_height_m": _number(field.get("mounting_height_m", 0.0)),
    }


def placement_fingerprint(
    field: Mapping[str, Any],
    module: Mapping[str, Any],
) -> str:
    encoded = json.dumps(
        placement_identity_payload(field, module),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def generated_module_id(
    field: Mapping[str, Any],
    module: Mapping[str, Any],
) -> str:
    digest = placement_fingerprint(field, module)
    return f"{field['pv_field_id']}-m-{digest[:20]}"


def replacement_generated_module_id(
    field: Mapping[str, Any],
    module: Mapping[str, Any],
    *,
    conflicting_old_id: str,
    conflicting_old_fingerprint: str,
    disambiguator: int = 0,
) -> str:
    """Return a deterministic replacement ID when a placement ID would resurrect
    a different pre-rebuild object identity.

    This guard is needed after explicit manual movement: the object keeps its
    ModuleInstance ID while moved, but a later generated rebuild may return to
    the coordinates from which that ID was originally derived.
    """
    payload = {
        "replacement_identity_version": MODULE_REPLACEMENT_IDENTITY_VERSION,
        "placement": placement_identity_payload(field, module),
        "conflicting_old_id": str(conflicting_old_id),
        "conflicting_old_fingerprint": str(conflicting_old_fingerprint),
        "disambiguator": int(disambiguator),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"{field['pv_field_id']}-m-{digest[:20]}"


def packing_slot_key(module: Mapping[str, Any]) -> str | None:
    """Return deterministic generated-grid lineage for rebuild delta pairing."""
    metadata = module.get("metadata") or {}
    row = metadata.get("grid_row_index")
    column = metadata.get("grid_column_index")
    if row is None or column is None:
        return None
    return f"r{int(row):06d}:c{int(column):06d}"


def placement_equivalent(
    before_field: Mapping[str, Any],
    before_module: Mapping[str, Any],
    after_field: Mapping[str, Any],
    after_module: Mapping[str, Any],
) -> bool:
    return placement_fingerprint(before_field, before_module) == placement_fingerprint(
        after_field, after_module
    )
