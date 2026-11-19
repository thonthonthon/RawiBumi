"""Stable serialization for derived Phase-4.4 3-D verification artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def canonical_scene3d_json(scene3d: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(scene3d),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_scene3d_hash(scene3d: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        canonical_scene3d_json(scene3d).encode("utf-8")
    ).hexdigest()
