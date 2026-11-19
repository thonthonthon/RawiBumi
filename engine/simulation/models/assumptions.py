"""Resolution-assumption helpers.

Phase 1 must never hide why a model was selected, why a lower-fidelity fallback was used, or
which refinement could not be applied. These records are serialized into the resolution
result and later become part of simulation-run provenance/reporting.
"""

from __future__ import annotations

from typing import Iterable


VALID_KINDS = {
    "model_selection",
    "fallback",
    "missing_refinement",
    "unsupported_model",
    "explicit_requirement",
    "limitation",
}

VALID_SEVERITIES = {"info", "warning", "blocking"}


def assumption(
    assumption_id: str,
    *,
    kind: str,
    scope: str,
    statement: str,
    basis: str,
    severity: str = "info",
    source_paths: Iterable[str] = (),
    affects: Iterable[str] = (),
) -> dict[str, object]:
    if kind not in VALID_KINDS:
        raise ValueError(f"unsupported assumption kind: {kind}")
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"unsupported assumption severity: {severity}")
    return {
        "schema_name": "SimulationAssumption",
        "schema_version": "0.1",
        "assumption_id": assumption_id,
        "kind": kind,
        "scope": scope,
        "statement": statement,
        "basis": basis,
        "severity": severity,
        "source_paths": list(source_paths),
        "affects": list(affects),
    }


def unavailable_refinement(
    refinement_id: str,
    *,
    reason_code: str,
    consequence: str,
    missing_fields: Iterable[str] = (),
) -> dict[str, object]:
    return {
        "refinement_id": refinement_id,
        "status": "unavailable",
        "reason_code": reason_code,
        "missing_fields": list(missing_fields),
        "consequence": consequence,
    }


def enabled_refinement(
    refinement_id: str,
    *,
    model_id: str,
    source_paths: Iterable[str],
    notes: str | None = None,
) -> dict[str, object]:
    return {
        "refinement_id": refinement_id,
        "status": "enabled",
        "model_id": model_id,
        "source_paths": list(source_paths),
        "notes": notes,
    }
