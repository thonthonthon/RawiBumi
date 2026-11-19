"""Stable serialization and hashing for canonical scene revisions."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_scene_json(scene: dict[str, Any]) -> str:
    return json.dumps(
        scene,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_scene_hash(scene: dict[str, Any]) -> str:
    payload = canonical_scene_json(scene).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
