"""S14b: the app's orientation policy (user decision 2026-11-08).

Strings on one MPPT whose module normals agree within the tolerance (1° unless the design says less) are one
orientation group, for the design checks and for the simulation alike. Beyond it the design check warns; a per-MPPT
override with a reason silences that warning. Standard runs simulate mixed orientations; mixed module types and
string lengths remain outside their scope. The engine library compares exactly when a design carries no policy, so this module gives
every app path the same effective policy.
"""
from __future__ import annotations

from typing import Any, Mapping

DEFAULT_TOLERANCE_DEG = 1.0
MAX_TOLERANCE_DEG = 1.0
OVERRIDE_NOTE = "The orientation override records your reason."


def effective_policy(design: Mapping[str, Any]) -> dict[str, Any]:
    policy = design.get("orientation_policy") or {}
    tolerance = policy.get("normal_angle_tolerance_deg")
    return {"normal_angle_tolerance_deg": DEFAULT_TOLERANCE_DEG if tolerance is None else float(tolerance),
            "overrides": [dict(o) for o in policy.get("overrides") or []]}


def with_effective_policy(design: Mapping[str, Any]) -> dict[str, Any]:
    """A shallow copy of the design that carries its effective policy, for the execution plan."""
    return {**design, "orientation_policy": effective_policy(design)}


def tolerance_deg(design: Mapping[str, Any]) -> float:
    return effective_policy(design)["normal_angle_tolerance_deg"]


def overrides(design: Mapping[str, Any]) -> dict[str, str]:
    """MPPT id → the reason of its override."""
    return {str(o["mppt_instance_id"]): str(o["reason"]) for o in effective_policy(design)["overrides"]}
