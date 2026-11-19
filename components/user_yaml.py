"""Advanced YAML component overlays.

CSV is the normal human/spreadsheet entry path. YAML exists for nested or future canonical
fields that do not fit cleanly in a flat table.
"""

from __future__ import annotations

from typing import Any

import yaml

from components.source_overlay import ComponentSourceFragment


def _prune(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {
            key: pruned
            for key, child in value.items()
            if (pruned := _prune(child)) is not None
        }
        return cleaned or None
    if isinstance(value, list):
        cleaned = [
            pruned
            for child in value
            if (pruned := _prune(child)) is not None
        ]
        return cleaned or None
    if value is None:
        return None
    return value


def parse_component_overlay_yaml(text: str) -> tuple[str, ComponentSourceFragment]:
    payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError("component overlay YAML must contain an object")

    component_type = payload.get("component_type")
    if component_type not in {"module", "inverter"}:
        raise ValueError("component_type must be 'module' or 'inverter'")

    source = payload.get("source") or {}
    if not isinstance(source, dict):
        raise ValueError("source must be an object")
    source_id = source.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source.source_id is required")

    raw_data = payload.get("data")
    if not isinstance(raw_data, dict):
        raise ValueError("data must be an object")
    data = _prune(raw_data)
    if not isinstance(data, dict) or not data:
        raise ValueError("data does not contain any supplied values")

    priority = int(source.get("priority", 100))
    return component_type, ComponentSourceFragment(
        source_id=source_id.strip(),
        source_kind=source.get("source_kind") or "user_supplied",
        source_url=source.get("source_url") or None,
        priority=priority,
        notes=source.get("notes") or None,
        license_spdx=source.get("license_spdx") or None,
        license_url=source.get("license_url") or None,
        attribution=source.get("attribution") or None,
        data=data,
    )
