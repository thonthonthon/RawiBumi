"""Inert supplied-data correlation; no acquisition, authentication or conversion.

The B3-B2 report remains authoritative. Only successful identity-leaf byte facts
may differ in the subordinate comparison. Original upstream reports are retained
by exact digest with explicit custody limits, never converted into captures.
"""

from dataclasses import dataclass
import hashlib
import json
import re

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_native_evidence_integration as integration

SCHEMA = "rawibumi.native-semantic-correlation.f2b4.d2b2b3b3.v1"
INVALID_CODES = integration.INVALID_CODES + ("INPUT_ALIAS", "READ_SIZE_CONTRADICTION")
INCOMPLETE_CODES = integration.INCOMPLETE_CODES + (
    "STABLE_IDENTITY_MISMATCH", "STABLE_READ_DISAGREEMENT", "TEMPORAL_NONOVERLAP",
    "UNSUPPORTED_LOSSLESS_CONVERSION",
)
canonical_json = integration.canonical_json
digest = integration.digest


@dataclass(frozen=True)
class SemanticReport:
    serialized: str

    def to_dict(self):
        return json.loads(self.serialized)

    @property
    def sha256(self):
        return hashlib.sha256(self.serialized.encode("utf-8")).hexdigest()


def _trust():
    return {
        "qualification": "NONQUALIFYING", "independence": "INDEPENDENCE_NOT_ESTABLISHED",
        "source_origin_authenticated": False, "worker_roster_complete": False,
        "production_memory_qualified": False, "peak_observed": False,
        "native_origin_authentication": "NOT_IMPLEMENTED", "live_native_integration": "NOT_IMPLEMENTED",
        "independent_kernel_attestation": "NOT_ESTABLISHED", "worker_absence_proven": False,
        "holder_release": "NOT_ESTABLISHED", "production_memory_qualification": "INCONCLUSIVE",
        "production_chronological_peak": "NOT_OBSERVED", "production_workload_measured": False,
        "bound_claim": "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK", "atomic_snapshot": False,
        "verification_provenance": "CALLER_ASSERTED", "memo_cap": 256,
        "continuous_time_coverage": False, "merged_rss_peak": False,
    }


def _partitions(codes):
    codes = set(codes)
    if codes - set(INVALID_CODES) - set(INCOMPLETE_CODES):
        codes.add("REASON_CODE_INVALID")
    invalid = sorted(codes & set(INVALID_CODES))
    incomplete = sorted(codes & set(INCOMPLETE_CODES))
    return {"outcome": "INVALID" if invalid else "INCOMPLETE" if incomplete else "CONSISTENT",
            "reason_codes": sorted(invalid + incomplete), "invalid_reason_codes": invalid,
            "incomplete_reason_codes": incomplete}


def _decode(value):
    # B3-B2 supplies bounded exact-type JSON decoding. Reject shared containers
    # additionally, including sharing within a route and outside the routes.
    copied = integration._decode(value)
    if type(value) is not bytes:
        seen = set()

        def visit(item):
            if type(item) in (dict, list):
                integration._need(id(item) not in seen, "INPUT_ALIAS")
                seen.add(id(item))
                for child in (item.values() if type(item) is dict else item):
                    visit(child)

        visit(value)
    return copied


def _paired_time(a, b, tolerance, codes):
    if any(abs(a[k] - b[k]) > tolerance for k in ("start_ns", "end_ns")):
        codes.add("ROUTE_SKEW_EXCEEDED")
    # Closed intervals, widened by at most the supplied skew tolerance. This
    # does not assert simultaneous acquisition, even when the rule succeeds.
    if a["start_ns"] > b["end_ns"] + tolerance or b["start_ns"] > a["end_ns"] + tolerance:
        codes.add("TEMPORAL_NONOVERLAP")


def _correlate(data, codes):
    left, right = data["routes"]
    a, b = left["capture"], right["capture"]
    environment = ("boot_id", "namespace", "procfs", "nsfs", "clock_kind",
                   "source_state", "source_kind", "origin_attestation")
    if (any(a[k] != b[k] for k in environment) or a["namespace"]["kind"] != "INODE" or
            left["provenance"]["data_origin"] != right["provenance"]["data_origin"]):
        codes.add("STABLE_IDENTITY_MISMATCH")
    roster = {p["pid"]: p for p in data["reference"]["roster"]}
    tolerance = data["limits"]["max_route_skew_ns"]
    divergences = []
    sizes, stable_reads = {}, {}
    for capture in (a, b):
        for frame in capture["frames"]:
            for process in frame["processes"]:
                for read in process["reads"]:
                    sha, count, path = read["sha256"], read["byte_count"], read["path_id"]
                    if sha in sizes and sizes[sha] != count:
                        codes.add("READ_SIZE_CONTRADICTION")
                    sizes[sha] = count
                    if not path.endswith("/identity"):
                        facts = (sha, count, read["status"], tuple(read["reason_codes"]))
                        if path in stable_reads and stable_reads[path] != facts:
                            codes.add("STABLE_READ_DISAGREEMENT")
                        stable_reads[path] = facts
    for fa, fb in zip(a["frames"], b["frames"]):
        _paired_time(fa, fb, tolerance, codes)
        pa = {p["identity"]["pid"]: p for p in fa["processes"]}
        pb = {p["identity"]["pid"]: p for p in fb["processes"]}
        if pa.keys() != roster.keys() or pb.keys() != roster.keys():
            codes.add("MISSING_WORKER")
            continue
        for pid in sorted(roster):
            x, y = pa[pid], pb[pid]
            if x["identity"] != roster[pid] or y["identity"] != roster[pid]:
                codes.add("STABLE_IDENTITY_MISMATCH")
            if ({d["path_id"]: d for d in x["descriptors"]} !=
                    {d["path_id"]: d for d in y["descriptors"]}):
                codes.add("STABLE_IDENTITY_MISMATCH")
            ar = {r["path_id"]: r for r in x["reads"]}
            br = {r["path_id"]: r for r in y["reads"]}
            if ar.keys() != br.keys():
                codes.add("PARTIAL_FRAME")
            for path in sorted(ar.keys() & br.keys()):
                ra, rb = ar[path], br[path]
                _paired_time(ra, rb, tolerance, codes)
                if ra["status"] != rb["status"] or ra["reason_codes"] != rb["reason_codes"]:
                    codes.add("STABLE_READ_DISAGREEMENT")
                if ra["sha256"] == rb["sha256"] and ra["byte_count"] != rb["byte_count"]:
                    codes.add("READ_SIZE_CONTRADICTION")
                if any(ra[k] != rb[k] for k in ("sha256", "byte_count")):
                    if path == f"pids/{pid}/identity" and ra["status"] == rb["status"] == "OK":
                        divergences.append({"frame_index": fa["index"], "path_id": path,
                            "reason": "VOLATILE_IDENTITY_READ_BYTES_DIFFER",
                            "left_sha256": ra["sha256"], "right_sha256": rb["sha256"],
                            "left_byte_count": ra["byte_count"], "right_byte_count": rb["byte_count"]})
                    else:
                        codes.add("STABLE_READ_DISAGREEMENT")
    return divergences


def correlate_native_semantics(request, *, callbacks=()):
    """Accept B3-B2 supplied requests, preserving its original object and verdict.

    Callbacks are identity-only inputs to B3-B2. Neither callbacks nor preview
    providers/clocks are invoked. Only a fully validated predecessor with no
    reasons other than SOURCE_DISAGREEMENT can reach semantic comparison.
    """
    predecessor = integration.integrate_native_evidence(request, callbacks=callbacks)
    original = predecessor.to_dict()
    codes, divergences = set(), []
    classification = "NOT_EVALUATED"
    try:
        data = _decode(request)
        if original["request_sha256"] is not None:
            integration._need(digest(data) == original["request_sha256"], "INPUT_CHANGED")
        if type(request) is bytes:
            integration._need(hashlib.sha256(request).hexdigest() == original["raw_input_sha256"], "INPUT_CHANGED")
        if original["outcome"] == "INVALID":
            codes.update(original["reason_codes"])
        elif set(original["reason_codes"]) - {"SOURCE_DISAGREEMENT"}:
            codes.update(original["reason_codes"])
        else:
            divergences = _correlate(data, codes)
            classification = "NOT_CORRELATED" if codes else "STABLE_IDENTITY_CORRELATED"
        integration._need(digest(_decode(request)) == digest(data), "INPUT_CHANGED")
    except integration._Rejected as exc:
        codes.add(exc.code)
        classification = "NOT_EVALUATED"
        divergences = []
    semantic = _partitions(codes)
    semantic["classification"] = classification
    semantic["volatile_divergences"] = divergences
    result = {"schema": SCHEMA + ".report", **_trust(),
              **_partitions(codes | set(original["reason_codes"])), "semantic": semantic,
              "predecessor_report_embedded": original, "predecessor_report_sha256": predecessor.sha256,
              "predecessor_outcome": original["outcome"],
              "predecessor_reason_codes": original["reason_codes"],
              "request_sha256": original["request_sha256"], "raw_input_sha256": original["raw_input_sha256"]}
    return SemanticReport(canonical_json(result))


# These are exact original envelope contracts, not imports of acquisition code.
# Dynamic fields are checked below; neither a digest nor a caller's original
# outcome is an authentication mechanism or a re-execution of its verifier.
ADAPTER_FIXED = {
    "qualification": "NONQUALIFYING", "independent_verification": "REQUIRED_NOT_PERFORMED",
    "production_memory_qualification": "INCONCLUSIVE", "production_chronological_peak": "NOT_OBSERVED",
    "production_workload_measured": False, "atomic_snapshot": False,
    "bound_claim": "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK", "holder_release": "NOT_ESTABLISHED",
    "owner_termination": "NOT_ESTABLISHED", "simultaneous_holder_occupancy": "NOT_ESTABLISHED",
    "worker_absence_proven": False, "unregistered_worker_coverage": "NOT_ESTABLISHED",
    "roster_provenance": "CALLER_ASSERTED_ONLY", "environment_provenance": "CALLER_ASSERTED_ONLY",
    "procfs_mount_verified": False, "starttime_alignment": "NOT_CALIBRATED", "cgroup": "DISABLED",
}
PROBE_FIXED = {
    "source_kind": "INJECTED_LOCAL_PROBE", "qualification": "NONQUALIFYING",
    "clock_domain": "INJECTED_MONOTONIC_NS", "native_adapter": "NOT_IMPLEMENTED",
    "independent_trust_root_gate": "NOT_IMPLEMENTED", "independent_verification": "REQUIRED_NOT_PERFORMED",
    "procfs_mount_authenticated": False, "namespace_authenticated": False,
    "mount_namespace_binding": "UNVERIFIED", "production_memory_qualification": "INCONCLUSIVE",
    "production_chronological_peak": "NOT_OBSERVED", "production_workload_measured": False,
    "holder_release": "NOT_ESTABLISHED", "rss_reclamation": "NOT_ESTABLISHED",
    "worker_discovery": "NOT_ESTABLISHED", "worker_absence_proven": False, "atomic_snapshot": False,
}
BRIDGE_FIXED = {
    "source_state": "INJECTED_TEST_ONLY", "qualification": "NONQUALIFYING",
    "clock_domain": "INJECTED_MONOTONIC_NS", "independent_corroboration": "NOT_ESTABLISHED",
    "native_origin_authentication": "NOT_IMPLEMENTED", "independent_host_attestation": "NOT_IMPLEMENTED",
    "worker_roster_completeness": "NOT_ESTABLISHED", "whole_process_tree_coverage": "NOT_ESTABLISHED",
    "rss_chronological_qualification": "NOT_ESTABLISHED", "rss_sampling": "SEQUENTIAL_NONATOMIC",
    "production_memory_qualification": "INCONCLUSIVE", "production_chronological_peak": "NOT_OBSERVED",
    "production_workload_measured": False, "holder_release": "NOT_ESTABLISHED",
    "rss_reclamation": "NOT_ESTABLISHED", "atomic_snapshot": False,
}
COMMON_KEYS = ("schema", "outcome", "invalid_reason_codes", "incomplete_reason_codes")
ADAPTER_DYNAMIC = (
    "source_kind", "origin_attestation", "clock_kind", "worker_coverage", "run_id", "input_sha256",
    "config", "roster", "frames_requested", "frames", "reasons", "read_attempts", "open_attempts",
    "total_bytes", "first_read_start_ns", "last_read_end_ns", "read_skew_ns", "integrity",
)
PROBE_DYNAMIC = (
    "trust_level", "context_pid", "target_pids", "context_identity", "target_identities",
    "input_sha256", "reference_sha256", "reason_codes", "reads", "frame_coverage",
)
BRIDGE_DYNAMIC = (
    "reason_codes", "request_sha256", "registered_roster", "providers", "observations",
    "source_acquisition", "cross_source_structural_agreement",
)
MISSING_FIELDS = {
    "ADAPTER_D2B2": ("second_route", "descriptor_identities", "procfs_nsfs_mount_identity",
                     "reference_window", "route_provenance"),
    "PROBE_B3A": ("second_route", "reference_window", "route_provenance", "bound_original_inputs"),
    "BRIDGE_H0": ("reference_window", "frame_count", "per_frame_windows", "limits", "route_provenance"),
}


def _fixed(report, fixed, dynamic):
    integration._object(report, tuple(fixed) + COMMON_KEYS + dynamic)
    integration._need(all(type(report[k]) is type(v) and report[k] == v for k, v in fixed.items()),
                      "SOURCE_LABEL_CONFLICT")


def _hashes(value):
    """Check every declared original hash, including nested read records."""
    if type(value) is dict:
        for key, child in value.items():
            if (key == "sha256" or key.endswith("_sha256")) and child is not None:
                integration._hash(child)
            _hashes(child)
    elif type(value) is list:
        for child in value:
            _hashes(child)


def _adapter_window(summary, reads):
    """Bind an adapter's timing summary to its supplied read endpoints."""
    for key in ("first_read_start_ns", "last_read_end_ns", "read_skew_ns"):
        if summary[key] is not None:
            integration._integer(summary[key])
    starts, ends = [], []
    for read in reads:
        integration._need(type(read) is dict and {"start_ns", "end_ns"} <= read.keys())
        for key, values in (("start_ns", starts), ("end_ns", ends)):
            if read[key] is not None:
                integration._integer(read[key])
                values.append(read[key])
    first, last = min(starts) if starts else None, max(ends) if ends else None
    skew = last - first if first is not None and last is not None else None
    integration._need((summary["first_read_start_ns"], summary["last_read_end_ns"], summary["read_skew_ns"]) ==
                      (first, last, skew), "OUTCOME_CONFLICT")


def _adapter_summary(report, codes):
    """Check capture-envelope consistency, without rerunning its verifier."""
    unestablished = report["worker_coverage"] == "NOT_ESTABLISHED"
    if unestablished:
        integration._need(report["outcome"] == "INVALID" and all(report[k] is None for k in
            ("run_id", "input_sha256", "config", "roster", "frames_requested")), "OUTCOME_CONFLICT")
        integration._need(not report["frames"] and all(report[k] == 0 for k in
            ("read_attempts", "open_attempts", "total_bytes")), "OUTCOME_CONFLICT")
    else:
        # Adapter run labels have their own public grammar, broader than the
        # B3-B2 provenance-label grammar (including dots/colons and 96 chars).
        run_id = report["run_id"]
        integration._need(type(run_id) is str and len(run_id) <= 96 and ".." not in run_id and
                          re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", run_id) is not None, "LABEL_INVALID")
        integration._hash(report["input_sha256"])
        integration._need(type(report["config"]) is dict and type(report["roster"]) is dict)
        integration._integer(report["frames_requested"], 1, integration.MAX_FRAMES)
        integration._need(len(report["frames"]) == report["frames_requested"] or
                          "CAPTURE_STOPPED" in codes, "OUTCOME_CONFLICT")
        integration._need(report["worker_coverage"] ==
                          ("UNCERTAIN" if codes else "REGISTERED_ROSTER_OBSERVED"), "OUTCOME_CONFLICT")
    reads = []
    for index, frame in enumerate(report["frames"]):
        integration._object(frame, ("index", "status", "reason_codes", "processes", "observed_pids",
            "roster_complete", "first_read_start_ns", "last_read_end_ns", "read_skew_ns", "read_window_complete"))
        integration._integer(frame["index"])
        integration._need(frame["index"] == index, "OUTCOME_CONFLICT")
        frame_codes = integration._codes(frame["reason_codes"], integration.ADAPTER_INVALID + integration.ADAPTER_INCOMPLETE)
        integration._need(frame_codes <= codes and frame["status"] ==
            ("INVALID" if frame_codes & set(integration.ADAPTER_INVALID) else "INCOMPLETE" if frame_codes else
             "CAPTURE_CONSISTENT_NONQUALIFYING"), "OUTCOME_CONFLICT")
        integration._list(frame["processes"], integration.MAX_PROCESSES)
        frame_reads = []
        for process in frame["processes"]:
            integration._need(type(process) is dict and "reads" in process)
            integration._list(process["reads"], 4)
            frame_reads.extend(process["reads"])
        _adapter_window(frame, frame_reads)
        complete = all(r["start_ns"] is not None and r["end_ns"] is not None for r in frame_reads)
        integration._need(type(frame["read_window_complete"]) is bool and
                          frame["read_window_complete"] == complete, "OUTCOME_CONFLICT")
        if not codes:
            integration._need(bool(frame_reads) and complete, "OUTCOME_CONFLICT")
        reads.extend(frame_reads)
    _adapter_window(report, reads)


def _upstream_envelope(kind, report):
    schema, invalid, incomplete, success = integration.VERIFIERS[kind]
    integration._need(type(report) is dict and report.get("schema") == schema)
    if kind == "ADAPTER_D2B2":
        _fixed(report, ADAPTER_FIXED, ADAPTER_DYNAMIC)
        integration._list(report["reasons"], integration.MAX_NODES)
        pairs = []
        for reason in report["reasons"]:
            integration._object(reason, ("code", "location"))
            integration._need(type(reason["location"]) is str)
            integration._need(type(reason["code"]) is str and reason["code"] in invalid + incomplete,
                              "REASON_CODE_INVALID")
            pairs.append((reason["code"], reason["location"]))
        integration._need(pairs == sorted(set(pairs)), "REASON_CODE_INVALID")
        reasons = sorted({code for code, _ in pairs})
        integration._object(report["integrity"], ("algorithm", "scope", "sha256"))
        integrity = report["integrity"]
        integration._need(integrity["algorithm"] == "sha256" and
                          integrity["scope"] == "canonical result excluding integrity", "DIGEST_INVALID")
        integration._need(integrity["sha256"] == digest({k: v for k, v in report.items() if k != "integrity"}),
                          "DIGEST_INVALID")
        origin = report["source_kind"]
        integration._need(type(origin) is str and origin in ("TEST_INJECTED", "NATIVE_PROCFS_UNVERIFIED"),
                          "SOURCE_LABEL_CONFLICT")
        expected = (("UNVERIFIED", "INJECTED_MONOTONIC_NS") if origin == "TEST_INJECTED" else
                    ("UNVERIFIED_NATIVE_CAPTURE", "LOCAL_MONOTONIC_NS"))
        integration._need((report["origin_attestation"], report["clock_kind"]) == expected,
                          "SOURCE_LABEL_CONFLICT")
        integration._need(report["worker_coverage"] in ("NOT_ESTABLISHED", "REGISTERED_ROSTER_OBSERVED", "UNCERTAIN"))
        for key in ("read_attempts", "open_attempts", "total_bytes"):
            integration._integer(report[key])
        for key in ("first_read_start_ns", "last_read_end_ns", "read_skew_ns", "frames_requested"):
            if report[key] is not None:
                integration._integer(report[key])
        integration._list(report["frames"], integration.MAX_FRAMES)
    else:
        fixed, dynamic = (PROBE_FIXED, PROBE_DYNAMIC) if kind == "PROBE_B3A" else (BRIDGE_FIXED, BRIDGE_DYNAMIC)
        _fixed(report, fixed, dynamic)
        reasons = report["reason_codes"]
        origin = report["source_kind"] if kind == "PROBE_B3A" else report["source_state"]
    all_codes = integration._codes(reasons, invalid + incomplete)
    bad = integration._codes(report["invalid_reason_codes"], invalid)
    gaps = integration._codes(report["incomplete_reason_codes"], incomplete)
    integration._need(bad == all_codes & set(invalid) and gaps == all_codes & set(incomplete), "OUTCOME_CONFLICT")
    integration._need(report["outcome"] == ("INVALID" if bad else "INCOMPLETE" if gaps else success),
                      "OUTCOME_CONFLICT")
    if kind == "ADAPTER_D2B2":
        _adapter_summary(report, all_codes)
    if kind == "PROBE_B3A":
        integration._need(report["trust_level"] == ("CALLER_ASSERTED_ONLY" if bad else "INJECTED_LOCAL_PROBE"),
                          "SOURCE_LABEL_CONFLICT")
        integration._need(report["frame_coverage"] == ("UNBOUNDED" if all_codes else "CALLER_ASSERTED_WINDOWS_ONLY"),
                          "OUTCOME_CONFLICT")
        integration._list(report["reads"], integration.MAX_NODES)
        integration._list(report["target_pids"], integration.MAX_PROCESSES)
        integration._list(report["target_identities"], integration.MAX_PROCESSES)
        for pid in report["target_pids"]:
            integration._integer(pid, 1, 2147483647)
        for identity in report["target_identities"]:
            integration._identity(identity)
        if report["context_pid"] is not None:
            integration._integer(report["context_pid"], 1, 2147483647)
        if report["context_identity"] is not None:
            integration._identity(report["context_identity"])
            integration._need(report["context_identity"]["pid"] == report["context_pid"], "IDENTITY_INVALID")
        if not bad:
            integration._need(report["context_identity"] is not None, "IDENTITY_INVALID")
            integration._need(report["target_pids"] == [p["pid"] for p in report["target_identities"]],
                              "IDENTITY_INVALID")
            integration._hash(report["input_sha256"])
        paths = {"boot_id", "mount"}
        identities = report["target_identities"] + ([report["context_identity"]] if report["context_identity"] else [])
        for identity in identities:
            paths.update((f"pids/{identity['pid']}/identity", f"pids/{identity['pid']}/namespace"))
        observed = []
        for read in report["reads"]:
            integration._object(read, ("source", "start_ns", "end_ns", "failure_codes", "provenance", "sha256",
                                       "descriptor_stable"))
            integration._need(type(read["source"]) is str and read["source"] in paths, "PATH_POLICY_VIOLATION")
            integration._need(read["provenance"] == "INJECTED_LOCAL_PROBE", "SOURCE_LABEL_CONFLICT")
            failures = integration._codes(read["failure_codes"], invalid + incomplete)
            integration._need(failures <= all_codes, "OUTCOME_CONFLICT")
            integration._need(type(read["descriptor_stable"]) is bool)
            for endpoint in ("start_ns", "end_ns"):
                if read[endpoint] is not None:
                    integration._integer(read[endpoint])
            if read["start_ns"] is not None and read["end_ns"] is not None:
                integration._need(read["start_ns"] <= read["end_ns"] or "CLOCK_REGRESSION" in failures,
                                  "OUTCOME_CONFLICT")
            if not failures:
                integration._hash(read["sha256"])
                integration._need(read["descriptor_stable"] is True and
                                  read["start_ns"] is not None and read["end_ns"] is not None, "OUTCOME_CONFLICT")
            observed.append(read["source"])
        if not all_codes:
            integration._need(len(observed) == 2 * len(paths) and all(observed.count(p) == 2 for p in paths),
                              "OUTCOME_CONFLICT")
    if kind == "BRIDGE_H0":
        integration._list(report["observations"], integration.MAX_NODES)
        integration._list(report["providers"], 2)
        integration._list(report["registered_roster"], integration.MAX_PROCESSES)
        for identity in report["registered_roster"]:
            integration._identity(identity)
        for provider in report["providers"]:
            integration._object(provider, ("provider_id", "source_id", "fixture_id", "declared_origin"))
            integration._need(provider["declared_origin"] == "INJECTED_TEST_ONLY", "SOURCE_LABEL_CONFLICT")
            for key in ("provider_id", "source_id", "fixture_id"):
                integration._label(provider[key])
        for read in report["observations"]:
            integration._object(read, ("provider_index", "sweep", "path_id", "clock_domain", "start_ns", "end_ns",
                "descriptor_before", "descriptor_after", "payload", "sha256", "payload_sha256", "method",
                "declared_sha256", "raw_byte_count", "declared_origin", "sequence", "provider_status",
                "provider_reason", "status", "reason_codes", "operation_errors"))
            integration._integer(read["provider_index"], 0, 1)
            integration._integer(read["sweep"], 0, 1)
            integration._need(read["clock_domain"] == "INJECTED_MONOTONIC_NS", "SOURCE_LABEL_CONFLICT")
            failures = integration._codes(read["reason_codes"], invalid + incomplete)
            integration._need(failures <= all_codes, "OUTCOME_CONFLICT")
            integration._need(read["status"] == ("FAILED" if failures else "OK"), "OUTCOME_CONFLICT")
            if read["payload"] is not None:
                integration._need(read["payload_sha256"] == digest(read["payload"]), "DIGEST_INVALID")
            if not failures:
                integration._need(read["descriptor_before"] is not None and
                                  read["descriptor_before"] == read["descriptor_after"], "DESCRIPTOR_INVALID")
                integration._need(read["declared_origin"] == "INJECTED_TEST_ONLY", "SOURCE_LABEL_CONFLICT")
                integration._need(read["sha256"] == read["declared_sha256"], "DIGEST_INVALID")
                integration._hash(read["sha256"])
                if read["method"] == "INJECTED_STRUCTURED":
                    integration._need(read["sha256"] == read["payload_sha256"], "DIGEST_INVALID")
        if not all_codes:
            integration._need(len(report["providers"]) == 2 and bool(report["registered_roster"]), "OUTCOME_CONFLICT")
            integration._hash(report["request_sha256"])
            paths = {"boot_id", "proc_mount"}
            for identity in report["registered_roster"]:
                paths.update(f"pids/{identity['pid']}/{leaf}" for leaf in ("identity", "ns_link", "ns_target"))
            actual = [(r["provider_index"], r["sweep"], r["path_id"]) for r in report["observations"]]
            expected = {(p, s, path) for p in (0, 1) for s in (0, 1) for path in paths}
            integration._need(len(actual) == len(expected) and all(type(path) is str for _, _, path in actual) and
                              set(actual) == expected, "OUTCOME_CONFLICT")
        integration._need(report["cross_source_structural_agreement"] == ("NOT_ESTABLISHED" if all_codes else "AGREES"),
                          "OUTCOME_CONFLICT")
        acquisition = ("ALIAS_DETECTED" if "SOURCE_ALIAS" in all_codes else
                       "CALLER_CONFIGURED_ONLY" if any(type(r) is dict and r.get("start_ns") is not None
                                                       for r in report["observations"]) else "NOT_ACQUIRED")
        integration._need(report["source_acquisition"] == acquisition, "OUTCOME_CONFLICT")
    _hashes(report)
    return {"original_schema": schema, "data_origin": origin, "original_outcome": report["outcome"],
            "original_reason_codes": sorted(all_codes), "original_invalid_reason_codes": sorted(bad),
            "original_incomplete_reason_codes": sorted(gaps)}


def import_upstream_report(kind, raw_bytes):
    """Inspect an original envelope; NEVER produce a converted capture.

    Only bounded strict UTF-8 JSON bytes are accepted (whitespace need not be
    canonical). Envelope validation is not original verification. Exact bytes
    remain in caller custody; the result stores raw and canonical digests.
    """
    codes, metadata, raw_hash, canonical_hash = set(), None, None, None
    try:
        integration._need(type(kind) is str and kind in integration.VERIFIERS)
        integration._need(type(raw_bytes) is bytes, "INPUT_NOT_JSON")
        integration._need(len(raw_bytes) <= integration.MAX_BYTES, "INPUT_CAP_EXCEEDED")
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        report = _decode(raw_bytes)
        metadata = _upstream_envelope(kind, report)
        canonical_hash = digest(report)
        codes.add("UNSUPPORTED_LOSSLESS_CONVERSION")
        if metadata["original_invalid_reason_codes"]:
            codes.add("UPSTREAM_INVALID")
        if metadata["original_incomplete_reason_codes"]:
            codes.add("UPSTREAM_INCOMPLETE")
    except integration._Rejected as exc:
        codes.add(exc.code)
    result = {"schema": SCHEMA + ".upstream-import", **_trust(), **_partitions(codes),
              "conversion": "UNSUPPORTED_LOSSLESS_CONVERSION" if metadata is not None else "REJECTED",
              "converted_capture": None, "original": metadata, "raw_input_sha256": raw_hash,
              "canonical_report_sha256": canonical_hash,
              "original_verification": "CALLER_SUPPLIED_NOT_REVERIFIED",
              "validation_scope": "ORIGINAL_ENVELOPE_ONLY",
              "custody_limitation": "DIGEST_ONLY_EXACT_BYTES_REMAIN_WITH_CALLER_NOT_RETAINED_OR_AUTHENTICATED",
              "missing_semantic_fields": list(MISSING_FIELDS[kind]) if metadata is not None else []}
    return SemanticReport(canonical_json(result))
