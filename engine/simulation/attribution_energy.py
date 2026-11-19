"""Auditable energy reporting from persisted compact DC attribution, without physics."""
from dataclasses import dataclass
import json
from math import fsum, isclose
from pathlib import Path

import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker

from .artifacts import canonical_object_sha256
from .attribution_json_stream import open_persisted_attribution
from .detailed_attribution import BASES, CHANNEL_PAIRS, POLICY, DetailedDCAttributionResult, explain

MODEL_ID = "rawibumi.phase69b.dc_attribution_energy.v0.1"
IDENTITY_KEYS = ("scientific_input_sha256", "attribution_model_id", "attribution_model_version",
    "source_numerical_result_sha256", "source_electrical_design_sha256", "source_module_input_hashes",
    "region_solvers", "sample_count", "numerical_policy")
AGGREGATION_POLICY = {"integration": "power_w_times_explicit_duration_seconds_divided_by_3600",
    "period_assignment": "local_interval_start_entire_interval_no_boundary_proration",
    "partial_energy": "observed_available_intervals_only_no_extrapolation",
    "dark_coverage": "not_applicable_excluded_from_applicable_denominator",
    "scientific_values": "unrounded_signed_values_no_significance_suppression",
    "completeness_scope": "observed_simulated_intervals_only_not_full_calendar_period",
    "aggregation_scope": "validated_interval_ledger_across_applicable_mppt_scopes",
    "scope": "controlled_run_daily_monthly_no_annual_scale_claim"}
COMPONENTS = tuple(k for k in CHANNEL_PAIRS if k != "total_detailed_dc_delta")


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def load_compact_attribution(path):
    """Compatibility API: materialize an isolated source with caller-owned lifetime."""
    record = json.loads(Path(path).read_text())
    source = DetailedDCAttributionResult.freeze(record["payload"], _decoded=True)
    if source.attribution_result_sha256 != record["attribution_result_sha256"]:
        raise ValueError("attribution energy source hash mismatch")
    return source


def _coverage(state):
    durations, terms, reasons = state
    available, missing, dark = (durations[k] for k in ("available", "unavailable", "not_applicable"))
    available_seconds, missing_seconds = fsum(available), fsum(missing)
    applicable_seconds = fsum([available_seconds, missing_seconds])
    status = ("not_applicable" if not available and not missing else "unavailable" if not available
              else "partial" if missing else "complete")
    energy = fsum(terms) if available else None
    return {"availability": "not_applicable" if status == "not_applicable" else "unavailable" if status == "unavailable" else "available",
        "completeness": status, "applicable_interval_count": len(available)+len(missing),
        "applicable_duration_seconds": applicable_seconds,
        "available_interval_count": len(available), "available_duration_seconds": available_seconds,
        "unavailable_interval_count": len(missing), "unavailable_duration_seconds": missing_seconds,
        "not_applicable_interval_count": len(dark), "not_applicable_duration_seconds": fsum(dark),
        "availability_fraction": available_seconds/applicable_seconds if applicable_seconds else None,
        "observed_signed_energy_wh": energy, "complete_signed_energy_wh": energy if status == "complete" else None,
        "unavailable_reason_codes": sorted(reasons),
        "unavailable_reasons": [{"reason_code": reason, "interval_count": len(reasons[reason]),
            "duration_seconds": fsum(reasons[reason])} for reason in sorted(reasons)]}


def _telescope(rows, bases, channels, policy):
    applicable = False
    base_mismatch, channel_mismatch = set(), set()
    common_indices, durations, power_residuals = [], [], []
    terms = {k: [] for k in CHANNEL_PAIRS}
    for i, r in rows:
        ledger = r["ledger"]
        active = any(v["status"] != "not_applicable" for v in ledger["bases"].values())
        applicable = applicable or active
        for k in BASES:
            if (ledger["bases"][k]["status"] != "not_applicable") != active:
                base_mismatch.add(k)
        for k in CHANNEL_PAIRS:
            if (ledger["channels"][k]["status"] != "not_applicable") != active:
                channel_mismatch.add(k)
        if active and all(v["status"] == "available" for v in ledger["bases"].values()) and all(v["status"] == "available" for v in ledger["channels"].values()):
            common_indices.append(i)
            durations.append(r["duration_seconds"])
            power_residuals.append(ledger["telescope"]["residual_w"])
            for k in CHANNEL_PAIRS:
                terms[k].append(ledger["channels"][k]["value_w"] * r["duration_seconds"]/3600)
    blockers = [k for k in BASES if applicable and (bases[k]["completeness"] != "complete" or k in base_mismatch)]
    blocked_channels = [k for k in CHANNEL_PAIRS if applicable and (channels[k]["completeness"] != "complete" or k in channel_mismatch)]
    common = bool(common_indices)
    status = "not_applicable" if not applicable else "complete" if not blockers and not blocked_channels else (
        "partial" if any(v["available_interval_count"] for v in bases.values()) else "unavailable")
    seconds = fsum(durations)
    components = fsum(fsum(terms[k]) for k in COMPONENTS) if common else None
    total = fsum(terms["total_detailed_dc_delta"]) if common else None
    residual = components-total if common else None
    atol = policy["energy_absolute_tolerance_wh_per_second"] * seconds
    rtol = policy["energy_relative_tolerance"]
    if common and not isclose(components, total, abs_tol=atol, rel_tol=rtol):
        raise ValueError("attribution energy telescope does not reconcile")
    if any(not isclose(v, 0., abs_tol=policy["power_absolute_tolerance_w"], rel_tol=policy["power_relative_tolerance"]) for v in power_residuals):
        raise ValueError("attribution interval power telescope does not reconcile")
    return {"status": status, "blocking_bases": blockers, "blocking_channels": blocked_channels,
        "common_available_interval_indices": common_indices,
        "common_available_interval_count": len(common_indices), "common_available_duration_seconds": seconds,
        "max_abs_interval_power_residual_w": max(map(abs, power_residuals)) if common else None,
        "energy_residual_wh": residual if status == "complete" else None,
        "common_available_energy_residual_wh": residual,
        "energy_absolute_tolerance_wh": atol, "energy_relative_tolerance": rtol,
        "energy_allowed_residual_wh": max(atol, rtol*max(abs(components), abs(total))) if common else None}


class _Rows:
    def __init__(self, audit, indices):
        self.audit, self.indices = audit, indices

    def __iter__(self):
        return ((i, self.audit[i]) for i in self.indices)

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, index):
        i = self.indices[index]
        return i, self.audit[i]


def _period(kind, key, rows, policy):
    states = {(section, k): ({status: [] for status in ("available", "unavailable", "not_applicable")}, [], {})
              for section, keys in (("bases", BASES), ("channels", CHANNEL_PAIRS)) for k in keys}
    for _, row in rows:
        seconds = row["duration_seconds"]
        for (section, k), (durations, terms, reasons) in states.items():
            value = row["ledger"][section][k]
            durations[value["status"]].append(seconds)
            if value["status"] == "available":
                terms.append(value["power_w" if section == "bases" else "value_w"] * seconds / 3600)
            elif value["status"] == "unavailable":
                for reason in set(value["reason_codes"]):
                    reasons.setdefault(reason, []).append(seconds)
    bases = {k: _coverage(states[("bases", k)]) for k in BASES}
    channels = {k: _coverage(states[("channels", k)]) for k in CHANNEL_PAIRS}
    del states
    return {"period_kind": kind, "period_key": key, "interval_indices": [i for i, _ in rows],
        "observed_start": rows[0][1]["interval_start"], "observed_end": rows[-1][1]["interval_end"],
        "interval_count": len(rows), "duration_seconds": fsum(r["duration_seconds"] for _, r in rows),
        "bases": bases, "channels": channels, "telescope": _telescope(rows, bases, channels, policy)}


def _assemble(identity, source_hash, scopes, audit):
    groups = {"daily": {}, "monthly": {}}
    rows = _Rows(audit, range(len(audit)))
    previous = None
    for i, r in rows:
        start, end = pd.Timestamp(r["interval_start"]), pd.Timestamp(r["interval_end"])
        if start.tzinfo is None or end.tzinfo is None or end <= start or (end-start).total_seconds() != r["duration_seconds"] or (previous is not None and start != previous):
            raise ValueError("attribution energy interval identity/duration mismatch")
        previous = end
        if r["ledger"] != explain(r["ledger"]["bases"]):
            raise ValueError("attribution energy source ledger semantics mismatch")
        for kind, fmt in (("daily", "%Y-%m-%d"), ("monthly", "%Y-%m")):
            groups[kind].setdefault(start.strftime(fmt), []).append(i)
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
        periods.extend(_period(kind, k, _Rows(audit, v), policy) for k, v in sorted(groups[kind].items()))
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


def _from_source(source, payload=None):
    payload = source.replay_stream() if payload is None else payload
    audit = [{**{k: r[k] for k in ("interval_start", "interval_end", "evaluation_time", "duration_seconds")},
        "ledger": r["ledger"],
        "channel_energy": {k: {"status": v["status"], "reason_codes": v["reason_codes"],
            "signed_energy_wh": v["value_w"] * r["duration_seconds"] / 3600 if v["status"] == "available" else None}
            for k, v in r["ledger"]["channels"].items()}} for r in payload["intervals"]]
    scopes = [{k: m[k] for k in ("mppt_instance_id", "mppt_index", "module_ids", "string_ids", "tracker_model_id")}
              for m in payload["intervals"][0]["mppts"]]
    return _assemble({k: payload[k] for k in IDENTITY_KEYS}, source.attribution_result_sha256, scopes, audit)


@dataclass(frozen=True)
class DetailedDCAttributionEnergySummary:
    canonical_payload: bytes
    energy_summary_sha256: str

    @classmethod
    def freeze(cls, payload, *, _decoded=False):
        result = cls(_bytes(payload), canonical_object_sha256(payload))
        if _decoded:
            result._validate_payload(payload)
        else:
            result.replay()
        return result

    def replay(self):
        payload = json.loads(self.canonical_payload)
        return self._validate_payload(payload)

    def _validate_payload(self, payload):
        if _bytes(payload) != self.canonical_payload or canonical_object_sha256(payload) != self.energy_summary_sha256:
            raise ValueError("attribution energy summary hash mismatch")
        schema = json.loads((Path(__file__).resolve().parents[2]/"schemas/detailed-dc-attribution-energy-summary.schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
        expected = _assemble(payload["source_identity"], payload["source_attribution_result_sha256"], payload["scope_identity"], payload["interval_audit"])
        if payload != expected:
            raise ValueError("attribution energy summary semantics mismatch")
        return payload

    def record(self):
        return {"payload": self.replay(), "energy_summary_sha256": self.energy_summary_sha256}


def aggregate_persisted_attribution(path):
    """Only validated compact JSON is consumed; no electrical solver is called."""
    with open_persisted_attribution(path) as (source, payload):
        return DetailedDCAttributionEnergySummary.freeze(_from_source(source, payload), _decoded=True)


def verify_energy_summary(summary, attribution_path, *, _source=None, _payload=None, _summary_payload=None):
    # Private reuse arguments must come from the same package attribution already
    # validated and bound by the caller; attribution_path is used only otherwise.
    if _source is None:
        with open_persisted_attribution(attribution_path) as (source, payload):
            expected = _from_source(source, payload)
    else:
        _payload = _source.replay_stream() if _payload is None else _source._validate_payload(_payload)
        expected = _from_source(_source, _payload)
    actual = summary.replay() if _summary_payload is None else summary._validate_payload(_summary_payload)
    if actual != expected:
        raise ValueError("attribution energy summary/source binding mismatch")
