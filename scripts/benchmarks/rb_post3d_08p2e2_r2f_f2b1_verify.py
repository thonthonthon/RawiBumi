"""Independent deterministic verification of caller-supplied fake F2-A reports.

Pure standard-library computation through the immutable F2-A reconciler. No
instruments, production imports, execution entry point, or I/O. Reconstruction
checks derived data, not authenticity of the supplied raw observations.
"""

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2a_observer as observer


SCHEMA = "rawibumi.passive-memory-verifier.f2b1.v1"
INPUT_SCHEMA = "rawibumi.passive-memory-observer.f2a.v1"
COMPARABLE = "COMPARABLE_FAKE_OBSERVATIONS"
NOT_COMPARABLE = "NOT_COMPARABLE"
ENVELOPE = {
    "production_memory_qualification": "INCONCLUSIVE",
    "production_chronological_peak": "NOT_OBSERVED",
    "input_kind": "FAKE_INPUT_ONLY",
}
DELTA = "candidate_minus_baseline_sampled_max_rss_bytes"


def _json_copy(value):
    """Strict JSON types and UTF-8 strings; reject coercion and recursive values."""
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("Non-string key")
        for key in value:
            key.encode("utf-8")
        return {key: _json_copy(item) for key, item in value.items()}
    if type(value) is list:
        return [_json_copy(item) for item in value]
    if type(value) is str:
        # Canonical JSON escapes surrogates, so serialization alone accepts them.
        value.encode("utf-8")
        return value
    if value is None or type(value) in (bool, int, float):
        return value
    raise ValueError("Non-JSON value")


def _same(left, right):
    # Python equality aliases True with 1, and integers with floats.
    return observer.canonical_bytes(left) == observer.canonical_bytes(right)


def _topology_shape(config):
    """Drop only roster identities/references; preserve every other setting.

    Each parent is represented by its sorted multiset of worker descriptors.
    Parent order has no meaning in F2-A. Unknown/duplicate references fail closed.
    """
    topology = config["topology"]
    if type(topology) is not dict:
        raise ValueError("Missing topology object")
    parents, workers = topology["parents"], topology["workers"]
    if type(parents) is not list or not parents or type(workers) is not list:
        raise ValueError("Missing explicit rosters")
    if (topology["start_method"] != "spawn"
            or type(topology["max_concurrent_workers"]) is not int
            or topology["max_concurrent_workers"] < 0):
        raise ValueError("Invalid operating topology")
    groups = {}
    seen = set()
    for parent in parents:
        key = observer.identity_key(parent)
        if key in seen:
            raise ValueError("Duplicate parent")
        seen.add(key)
        groups[key] = []
    for worker in workers:
        if type(worker) is not dict:
            raise ValueError("Missing worker descriptor")
        key = observer.identity_key(worker["identity"])
        parent = observer.identity_key(worker["parent"])
        if key in seen or parent not in groups:
            raise ValueError("Duplicate worker or unknown parent")
        seen.add(key)
        groups[parent].append({name: value for name, value in worker.items()
                               if name not in ("identity", "parent")})
    if workers and topology["max_concurrent_workers"] == 0:
        raise ValueError("Zero worker limit")
    parent_shapes = [
        {"worker_count": len(descriptors),
         "workers": sorted(descriptors, key=observer.canonical_bytes)}
        for descriptors in groups.values()
    ]
    return {
        "settings": {key: value for key, value in topology.items()
                     if key not in ("parents", "workers")},
        "parent_count": len(parents),
        "total_workers": len(workers),
        "parents": sorted(parent_shapes, key=observer.canonical_bytes),
    }


def _summary():
    return {
        "reconstruction_verified": False,
        "eligible": False,
        "source_report_sha256": None,
        "source_input_sha256": None,
        "configuration_sha256": None,
        "input_id": None,
        "independent_run_id": None,
        "workload_id": None,
        "observed_outcome": None,
        "observed_reasons": None,
        "observed_reason_codes": None,
        "sampled_max_rss_bytes": None,
        "verification_reason_codes": [],
    }


def _verify(report):
    summary = _summary()
    failures = summary["verification_reason_codes"]

    def reject(code):
        failures.append(code)
        return summary, None, None

    if type(report) is not dict:
        return reject("MALFORMED_REPORT")
    try:
        submitted = _json_copy(report)
        # Copying rejects bad Unicode; the digest rejects nonfinite floats and
        # oversized integers before any submitted-report digest is retained.
        summary["source_report_sha256"] = observer.digest(submitted)
    except Exception:
        # Includes recursion/cycles; never copy unvalidated payloads to outputs.
        return reject("MALFORMED_REPORT")
    try:
        if not observer.verify_integrity(submitted):
            return reject("INTEGRITY_MISMATCH")
        if submitted.get("schema") != INPUT_SCHEMA:
            return reject("SCHEMA_MISMATCH")
        if (type(submitted.get("configuration")) is not dict
                or type(submitted.get("raw_supplied_observations")) is not dict):
            return reject("MALFORMED_REPORT")
    except Exception:
        return reject("MALFORMED_REPORT")
    try:
        rebuilt = observer.reconcile(submitted["configuration"],
                                     submitted["raw_supplied_observations"])
        if not _same(rebuilt, submitted):
            return reject("RECONSTRUCTION_MISMATCH")
    except Exception:
        # F2-A can raise for impossible nested structures; report a fixed code.
        return reject("RECONSTRUCTION_FAILED")

    # Only independently reconstructed, matching content supplies metadata.
    summary.update(
        reconstruction_verified=True,
        source_input_sha256=rebuilt["input_sha256"],
        configuration_sha256=observer.digest(rebuilt["configuration"]),
        observed_outcome=rebuilt["outcome"],
        observed_reasons=rebuilt["reasons"],
        observed_reason_codes=sorted({item["code"] for item in rebuilt["reasons"]}),
    )
    for name in ("input_id", "independent_run_id", "workload_id"):
        value = rebuilt.get(name)
        if type(value) is str and value.strip():
            summary[name] = value
        else:
            failures.append("MISSING_INPUT_DECLARATION")
    # Defense in depth: the pinned F2-A reconciler already supplies this envelope.
    if any(rebuilt.get(key) != value for key, value in ENVELOPE.items()):
        failures.append("INVALID_ENVELOPE")
    if (rebuilt["outcome"] != observer.COMPLETE or rebuilt["reasons"] != []
            or rebuilt.get("coverage_complete") is not True):
        failures.append("INPUT_NOT_OBSERVATION_COMPLETE")
    aggregate = rebuilt.get("sampled_aggregate")
    metric = aggregate.get("max_rss_bytes") if type(aggregate) is dict else None
    if type(metric) is not int or metric < 0:
        failures.append("MISSING_OR_INVALID_SAMPLED_METRIC")
    else:
        summary["sampled_max_rss_bytes"] = metric
    raw = rebuilt["raw_supplied_observations"]
    if type(raw.get("conditions")) is not dict or type(raw.get("records")) is not list:
        failures.append("MALFORMED_EVIDENCE")
    try:
        shape = _topology_shape(rebuilt["configuration"])
    except Exception:
        shape = None
        failures.append("TOPOLOGY_NOT_NORMALIZABLE")
    summary["verification_reason_codes"] = sorted(set(failures))
    summary["eligible"] = not failures
    return summary, rebuilt, shape


def _safe_verify(report):
    # Last boundary: even an unexpected reconciliation failure is fail-closed.
    try:
        return _verify(report)
    except Exception:
        summary = _summary()
        summary["verification_reason_codes"] = ["RECONSTRUCTION_FAILED"]
        return summary, None, None


def verify_report(report):
    """Return a sealed verification summary; this alone establishes no comparison.

    Outcomes/reasons in the summary are null until complete reconstruction matches.
    An authentic F2-A INVALID/INCONCLUSIVE report can reconstruct successfully but
    remains ineligible. No submitted payload or exception text is echoed.
    """
    summary, _, _ = _safe_verify(report)
    return observer.seal({
        "schema": SCHEMA + ".verification", **ENVELOPE,
        "outcome": "VERIFIED_FAKE_OBSERVATION" if summary["eligible"] else NOT_COMPARABLE,
        "verification": summary, DELTA: None,
    })


def compare_verified_reports(baseline, candidate):
    """Reconstruct two reports, compare declared conditions and topology shape.

    Independence declarations concern artificial data only. SHA-256 is integrity,
    not authentication. Only comparable observations receive a signed RSS delta.
    """
    left, baseline_report, left_shape = _safe_verify(baseline)
    right, candidate_report, right_shape = _safe_verify(candidate)
    reasons = [
        {"side": side, "code": code}
        for side, summary in (("baseline", left), ("candidate", right))
        for code in summary["verification_reason_codes"]
    ]
    delta = None
    if left["eligible"] and right["eligible"]:
        try:
            a, b = baseline_report, candidate_report
            raw_a, raw_b = a["raw_supplied_observations"], b["raw_supplied_observations"]
            checks = (
                ("WORKLOAD_MISMATCH", a["workload_id"], b["workload_id"]),
                ("CONDITIONS_MISMATCH", raw_a["conditions"], raw_b["conditions"]),
                ("CONFIGURATION_MISMATCH",
                 {key: value for key, value in a["configuration"].items() if key != "topology"},
                 {key: value for key, value in b["configuration"].items() if key != "topology"}),
                ("TOPOLOGY_MISMATCH", left_shape, right_shape),
            )
            for code, first, second in checks:
                if not _same(first, second):
                    reasons.append({"side": "pair", "code": code})
            if (any(_same(a[name], b[name]) for name in
                    ("input_id", "independent_run_id", "input_sha256"))
                    or _same(raw_a["records"], raw_b["records"])):
                reasons.append({"side": "pair", "code": "INPUTS_NOT_INDEPENDENT"})
            if not reasons:
                delta = right["sampled_max_rss_bytes"] - left["sampled_max_rss_bytes"]
        except Exception:
            reasons.append({"side": "pair", "code": "COMPARISON_FAILED"})
    reasons.sort(key=lambda item: (item["side"], item["code"]))
    return observer.seal({
        "schema": SCHEMA, **ENVELOPE,
        "input_report_schema": INPUT_SCHEMA,
        "outcome": NOT_COMPARABLE if reasons else COMPARABLE,
        "baseline": left, "candidate": right,
        "reasons": reasons, DELTA: None if reasons else delta,
        "caveats": [
            "Descriptive sampled fake-input difference only; no production acceptance.",
            "Reconstruction detects falsified derived fields, not regenerated raw evidence.",
            "Unauthenticated reports are not admissible production measurements.",
            "Distinct declarations and records do not prove experimental independence.",
            "Per-process HWM is never summed into a simultaneous peak.",
        ],
    })
