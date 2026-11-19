"""Deterministic serialization for canonical ElectricalDesignRevision drafts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def canonical_electrical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_electrical_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        canonical_electrical_json(value).encode("utf-8")
    ).hexdigest()
