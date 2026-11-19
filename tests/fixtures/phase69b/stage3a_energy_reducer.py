"""Frozen Stage 3A reducer oracle for exact Stage 3B compatibility."""
from math import fsum, isclose
import pandas as pd
from engine.simulation.attribution_energy import BASES, CHANNEL_PAIRS, POLICY, COMPONENTS, MODEL_ID, AGGREGATION_POLICY, explain

def _coverage(rows, section, key, value_key):
    selected = [(i, row, row["ledger"][section][key]) for i, row in rows]
    available = [(i, r, v) for i, r, v in selected if v["status"] == "available"]
    missing = [(i, r, v) for i, r, v in selected if v["status"] == "unavailable"]
    dark = [(i, r, v) for i, r, v in selected if v["status"] == "not_applicable"]
    count, seconds = lambda seq: len(seq), lambda seq: fsum(r["duration_seconds"] for _, r, _ in seq)
    applicable_seconds = fsum([seconds(available), seconds(missing)])
    status = ("not_applicable" if not available and not missing else "unavailable" if not available
              else "partial" if missing else "complete")
    energy = fsum(v[value_key] * r["duration_seconds"] / 3600 for _, r, v in available) if available else None
    reasons = sorted({reason for _, _, v in missing for reason in v["reason_codes"]})
    return {"availability": "not_applicable" if status == "not_applicable" else "unavailable" if status == "unavailable" else "available",
        "completeness": status, "applicable_interval_count": count(available)+count(missing),
        "applicable_duration_seconds": applicable_seconds,
        "available_interval_count": count(available), "available_duration_seconds": seconds(available),
        "unavailable_interval_count": count(missing), "unavailable_duration_seconds": seconds(missing),
        "not_applicable_interval_count": count(dark), "not_applicable_duration_seconds": seconds(dark),
        "availability_fraction": seconds(available)/applicable_seconds if applicable_seconds else None,
        "observed_signed_energy_wh": energy, "complete_signed_energy_wh": energy if status == "complete" else None,
        "unavailable_reason_codes": reasons,
        "unavailable_reasons": [{"reason_code": reason,
            "interval_count": sum(reason in v["reason_codes"] for _, _, v in missing),
            "duration_seconds": fsum(r["duration_seconds"] for _, r, v in missing if reason in v["reason_codes"])} for reason in reasons]}


def _telescope(rows, bases, channels, policy):
    applicable = {i for i, r in rows if any(v["status"] != "not_applicable" for v in r["ledger"]["bases"].values())}
    common = [(i, r) for i, r in rows if i in applicable and
              all(v["status"] == "available" for v in r["ledger"]["bases"].values()) and
              all(v["status"] == "available" for v in r["ledger"]["channels"].values())]
    blockers = [k for k in BASES if applicable and (bases[k]["completeness"] != "complete" or
        {i for i, r in rows if r["ledger"]["bases"][k]["status"] != "not_applicable"} != applicable)]
    blocked_channels = [k for k in CHANNEL_PAIRS if applicable and (channels[k]["completeness"] != "complete" or
        {i for i, r in rows if r["ledger"]["channels"][k]["status"] != "not_applicable"} != applicable)]
    status = "not_applicable" if not applicable else "complete" if not blockers and not blocked_channels else (
        "partial" if any(v["available_interval_count"] for v in bases.values()) else "unavailable")
    seconds = fsum(r["duration_seconds"] for _, r in common)
    components = fsum(fsum(r["ledger"]["channels"][k]["value_w"] * r["duration_seconds"]/3600 for _, r in common) for k in COMPONENTS) if common else None
    total = fsum(r["ledger"]["channels"]["total_detailed_dc_delta"]["value_w"] * r["duration_seconds"]/3600 for _, r in common) if common else None
    residual = components-total if common else None
    atol = policy["energy_absolute_tolerance_wh_per_second"] * seconds
    rtol = policy["energy_relative_tolerance"]
    if common and not isclose(components, total, abs_tol=atol, rel_tol=rtol):
        raise ValueError("attribution energy telescope does not reconcile")
    power_residuals = [r["ledger"]["telescope"]["residual_w"] for _, r in common]
    if any(not isclose(v, 0., abs_tol=policy["power_absolute_tolerance_w"], rel_tol=policy["power_relative_tolerance"]) for v in power_residuals):
        raise ValueError("attribution interval power telescope does not reconcile")
    return {"status": status, "blocking_bases": blockers, "blocking_channels": blocked_channels,
        "common_available_interval_indices": [i for i, _ in common],
        "common_available_interval_count": len(common), "common_available_duration_seconds": seconds,
        "max_abs_interval_power_residual_w": max(map(abs, power_residuals)) if common else None,
        "energy_residual_wh": residual if status == "complete" else None,
        "common_available_energy_residual_wh": residual,
        "energy_absolute_tolerance_wh": atol, "energy_relative_tolerance": rtol,
        "energy_allowed_residual_wh": max(atol, rtol*max(abs(components), abs(total))) if common else None}


def _period(kind, key, rows, policy):
    bases = {k: _coverage(rows, "bases", k, "power_w") for k in BASES}
    channels = {k: _coverage(rows, "channels", k, "value_w") for k in CHANNEL_PAIRS}
    return {"period_kind": kind, "period_key": key, "interval_indices": [i for i, _ in rows],
        "observed_start": rows[0][1]["interval_start"], "observed_end": rows[-1][1]["interval_end"],
        "interval_count": len(rows), "duration_seconds": fsum(r["duration_seconds"] for _, r in rows),
        "bases": bases, "channels": channels, "telescope": _telescope(rows, bases, channels, policy)}


def _assemble(identity, source_hash, scopes, audit):
    groups = {"daily": {}, "monthly": {}}
    rows = list(enumerate(audit))
    previous = None
    for _, r in rows:
        start, end = pd.Timestamp(r["interval_start"]), pd.Timestamp(r["interval_end"])
        if start.tzinfo is None or end.tzinfo is None or end <= start or (end-start).total_seconds() != r["duration_seconds"] or (previous is not None and start != previous):
            raise ValueError("attribution energy interval identity/duration mismatch")
        previous = end
        if r["ledger"] != explain(r["ledger"]["bases"]):
            raise ValueError("attribution energy source ledger semantics mismatch")
        for kind, fmt in (("daily", "%Y-%m-%d"), ("monthly", "%Y-%m")):
            groups[kind].setdefault(start.strftime(fmt), []).append((_, r))
        expected = {k: {"status": v["status"], "reason_codes": v["reason_codes"],
            "signed_energy_wh": v["value_w"] * r["duration_seconds"] / 3600 if v["status"] == "available" else None}
            for k, v in r["ledger"]["channels"].items()}
        if r["channel_energy"] != expected:
            raise ValueError("attribution interval energy semantics mismatch")
    policy = identity["numerical_policy"]
    if policy != POLICY:
        raise ValueError("unsupported source attribution numerical policy")
    periods = [_period("run_total", "observed_run", rows, policy)]
    for kind in ("daily", "monthly"):
        periods.extend(_period(kind, k, v, policy) for k, v in sorted(groups[kind].items()))
    return {"schema_name": "DetailedDCAttributionEnergySummary", "schema_version": "0.1",
        "energy_summary_model_id": MODEL_ID, "energy_summary_model_version": "0.1",
        "accounting_basis": "detailed_selected_mppt_dc_before_residual_losses",
        "application": "explanatory_only_never_applied_to_actual_ledger",
        "sign_convention": "positive_reduction_negative_recovery",
        "source_attribution_result_sha256": source_hash, "source_identity": identity,
        "scope_identity": scopes, "aggregation_policy": AGGREGATION_POLICY,
        "observed_start": audit[0]["interval_start"], "observed_end": audit[-1]["interval_end"],
        "observed_duration_seconds": fsum(r["duration_seconds"] for r in audit),
        "interval_audit": audit, "periods": periods}

