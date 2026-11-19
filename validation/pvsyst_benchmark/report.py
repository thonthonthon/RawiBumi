"""Private evidence and a strictly allowlisted anonymous public summary."""

import json
from pathlib import Path
import re


PUBLIC_CODES = frozenset(
    {
        "mesh_pending",
        "circuit_settings_pending",
        "ac_inputs_pending",
        "module_not_ready",
        "source_unknown",
        "origin_unresolved",
        "scene_mismatch",
        "counts_mismatch",
        "weather_failed",
        "stage_basis_unavailable",
    }
)


def blocked_report(label, *, reasons, evidence):
    if label not in {"P2", "P3"} or not reasons:
        raise ValueError("active label and blocking reasons are required")
    return {
        "case": label,
        "status": "blocked",
        "phase": "tooling_only",
        "headline_run_performed": False,
        "reasons": list(reasons),
        "evidence": evidence,
    }


def public_summary(reports):
    result = []
    for r in reports:
        if r.get("case") not in {"P2", "P3"} or r.get("status") != "blocked":
            raise ValueError("VAL1a cannot emit an energy verdict")
        codes = sorted({x.get("public_code", "source_unknown") for x in r["reasons"]})
        if not set(codes) <= PUBLIC_CODES:
            raise ValueError("unknown public reason")
        result.append({"case": r["case"], "status": "blocked", "reason_codes": codes})
    return {"phase": "tooling_only", "cases": result}


def write_reports(output, reports):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "private-report.json").write_text(
        json.dumps(reports, indent=2, allow_nan=False) + "\n"
    )
    summary = public_summary(reports)
    (output / "public-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = ["# Benchmark tooling status", ""]
    for case in summary["cases"]:
        lines.append(case["case"] + ": blocked — " + ", ".join(case["reason_codes"]))
    (output / "public-summary.md").write_text("\n".join(lines) + "\n")
    return summary


def privacy_violations(paths, *, forbidden_tokens=()):
    """Inspect only explicitly selected files, never traverse private inputs."""
    issues = []
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token and token.casefold() in text.casefold():
                issues.append(str(path))
        # Absolute workstation/source locations must be supplied externally.
        if re.search(r"/" + r'(?:home|Users)/[^\s"\']+|[A-Za-z]:\\', text):
            issues.append(str(path))
        if re.search(r"\b\d+(?:\.\d+)?\s*(?:kWh|MWh|GWh)\b", text):
            issues.append(str(path))
    return sorted(set(issues))
