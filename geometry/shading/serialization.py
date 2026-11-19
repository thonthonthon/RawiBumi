"""Stable serialization/hashing for Phase-5 shading geometry artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_geometry_payload_json(payload: Mapping[str, Any]) -> str:
    """Serialize only the numerical geometry payload.

    The payload identity intentionally excludes provenance/findings so identical
    compiled receiver/occluder geometry has the same geometry hash even when a
    semantically equivalent Scene serialization has different collection order.
    """
    return _canonical_json(payload)


def canonical_geometry_payload_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        canonical_geometry_payload_json(payload).encode("utf-8")
    ).hexdigest()


def canonical_compiled_shading_geometry_json(
    compiled: Mapping[str, Any],
) -> str:
    return _canonical_json(compiled)


def canonical_compiled_shading_geometry_hash(
    compiled: Mapping[str, Any],
) -> str:
    return hashlib.sha256(
        canonical_compiled_shading_geometry_json(compiled).encode("utf-8")
    ).hexdigest()
