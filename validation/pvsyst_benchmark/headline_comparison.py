"""Evidence-qualified benchmark comparisons; never alter engine inputs."""

from math import isfinite
import re

from .compare import stage_metrics, grid_verdict
from .reference import Basis


def column_register(columns, evidence):
    """Require a unique independently supported basis, not a closest-fit score.

    Evidence is case-specific: a source's exported component names alone do not
    establish its orientation. Missing or ambiguous proofs fail closed.
    """
    records = {}
    for column in columns:
        item = evidence.get(column, {})
        supported = set(Basis(b) for b in item.get("supported", []))
        proof = item.get("proof", [])
        supported.discard(Basis.UNAVAILABLE)
        basis = next(iter(supported)) if len(supported) == 1 and proof else Basis.UNAVAILABLE
        if column == "FIAMAlb":
            basis = Basis.UNAVAILABLE
        records[column] = {
            "basis": basis.value,
            "status": "proved" if basis != Basis.UNAVAILABLE else "unavailable",
            "proof": proof,
            "reason": item.get("reason", "no_unique_independent_basis") if basis == Basis.UNAVAILABLE else None,
        }
    return records


def qualified_metrics(reference, actual, *, column, register, actual_basis):
    basis = Basis(register.get(column, {}).get("basis", Basis.UNAVAILABLE))
    return stage_metrics(reference, actual, reference_basis=basis, actual_basis=actual_basis)


def perez_diffuse_attribution(joint, isotropic, *, threshold=0.0005):
    """A6 policy. The historical A5 sum remains visible, not used as a gate."""
    if not all(isfinite(v) for v in (joint, isotropic, threshold)) or threshold <= 0:
        raise ValueError("finite diagnostic fractions and positive threshold required")
    isolated = joint - isotropic
    passed = abs(isolated) < threshold and abs(joint) < threshold
    return {
        "label": "Perez diffuse convention bound",
        "diagnostic_only": True,
        "delta_E_J": joint,
        "delta_E_I": isotropic,
        "delta_E_H_linear_superposition_estimate": isolated,
        "threshold": threshold,
        "accepted": passed,
        "attribution": "partly attributed (Perez extraterrestrial/brightness convention), immaterial" if passed else "blocking",
        "superseded_A5": {
            "absolute_sum": abs(joint) + abs(isotropic),
            "status": "over-conservative, failed" if abs(joint) + abs(isotropic) >= threshold else "over-conservative, passed",
        },
    }


def public_summary(*, label, annual, monthly, runtime_seconds):
    """Allow only P-labels, relative deviations and runtime into public output."""
    if not re.fullmatch(r"P[23]", label) or len(monthly) != 12:
        raise ValueError("P2/P3 and twelve monthly deviations required")
    if not all(isfinite(v) for v in [annual, runtime_seconds, *monthly]) or runtime_seconds < 0:
        raise ValueError("finite comparison values required")
    return {
        "label": label,
        "energy_verdict": grid_verdict(annual, monthly),
        "annual_relative_deviation": annual,
        "worst_month_relative_deviation": max(monthly, key=abs),
        "runtime_seconds": runtime_seconds,
    }
