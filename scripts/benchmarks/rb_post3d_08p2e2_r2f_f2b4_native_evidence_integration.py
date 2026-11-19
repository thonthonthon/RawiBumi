"""Inert B3-B2 integration of supplied facts, never native acquisition.

The capture and verification schemas here are explicit supplied-data contracts,
not native adapter outputs. No callback executes except in the separately gated
artificial bridge preview. See the companion document for the exact protocol.
"""

from dataclasses import dataclass
from types import MethodType
import hashlib
import json
import re

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_native_provenance_bridge as bridge

SCHEMA = "rawibumi.native-evidence-integration.f2b4.d2b2b3b2.v1"
CAPTURE_SCHEMA = SCHEMA + ".capture"
VERIFICATION_SCHEMA = SCHEMA + ".verification"
ADAPTER_SCHEMA = "rawibumi.native-procfs-adapter.f2b4.d2b2a.v1.result"
PROBE_SCHEMA = "rawibumi.local-provenance-probe.f2b4.d2b2b3a.v1.report"
ASSESSMENT_SCHEMA = "rawibumi.native-provenance.f2b4.d2b2b2.v1"
MAX_BYTES = 8388608
MAX_STRING = 65536
MAX_NODES = 200000
MAX_DEPTH = 24
MAX_PROCESSES = 64
MAX_FRAMES = 32
U64 = (1 << 64) - 1

INVALID_CODES = (
    "NATIVE_MODE_DENIED", "SCHEMA_INVALID", "INPUT_NOT_JSON", "INPUT_CAP_EXCEEDED",
    "DUPLICATE_KEY", "INTEGER_INVALID", "LABEL_INVALID", "SOURCE_LABEL_CONFLICT",
    "IDENTITY_INVALID", "DUPLICATE_IDENTITY", "DUPLICATE_READ",
    "BOOT_ID_NONCANONICAL", "BOOT_ID_CONFLICT", "NAMESPACE_CONTRADICTION",
    "MOUNT_CONTRADICTION", "DESCRIPTOR_INVALID", "DESCRIPTOR_CHANGED", "DESCRIPTOR_ALIAS",
    "PATH_POLICY_VIOLATION", "CLOCK_REGRESSION", "READ_WINDOW_INVALID",
    "REASON_CODE_INVALID", "OUTCOME_CONFLICT", "DIGEST_INVALID", "INPUT_CHANGED",
    "CALLBACK_CONTRACT_INVALID", "UPSTREAM_INVALID", "PREVIEW_ROSTER_MISMATCH",
)
INCOMPLETE_CODES = (
    "SOURCE_ALIAS", "PID_REUSE", "PROCESS_REPARENTED", "MISSING_WORKER", "UNKNOWN_PROCESS",
    "ROSTER_DRIFT", "FRAME_MISSING", "PARTIAL_FRAME", "READ_FAILED", "PERMISSION_DENIED",
    "PROCESS_VANISHED", "FRAME_DURATION_EXCEEDED", "ROUTE_SKEW_EXCEEDED",
    "READ_GAP_EXCEEDED", "COVERAGE_GAP",
    "WORKER_LATE_OBSERVATION", "WORKER_EARLY_LAST_OBSERVATION", "SOURCE_DISAGREEMENT",
    "CLOCK_DOMAIN_UNCOMPARABLE", "NAMESPACE_UNCOMPARABLE", "UPSTREAM_INCOMPLETE",
    "UPSTREAM_CONVERSION_NOT_IMPLEMENTED",
)
READ_CODES = ("READ_FAILED", "PERMISSION_DENIED", "PROCESS_VANISHED")

# Sealed, namespaced vocabularies. These are not imports of native collectors.
# Predecessor READ_SKEW_EXCEEDED codes retain their own meanings here only;
# integration frame duration and cross-route skew have distinct codes above.
ADAPTER_INVALID = (
    "INPUT_NOT_JSON", "INPUT_CAP_EXCEEDED", "SCHEMA_INVALID", "UNKNOWN_FIELD",
    "SCHEMA_VERSION_MISMATCH", "SOURCE_KIND_NOT_ACCEPTED", "SOURCE_ORIGIN_CONFLICT",
    "CONFIGURATION_INVALID", "IDENTITY_INVALID", "DUPLICATE_IDENTITY", "BOOT_ID_MISMATCH",
    "PID_NAMESPACE_MISMATCH", "CGROUP_NOT_AUTHORIZED", "READER_CONTRACT_VIOLATION",
    "RAW_TEXT_MALFORMED", "INVALID_UTF8", "DUPLICATE_FIELD", "MISSING_FIELD",
    "IDENTITY_CONTRADICTION", "CLOCK_FAILURE", "CLOCK_NON_MONOTONIC",
    "COUNTER_INCONSISTENT", "PATH_POLICY_VIOLATION", "NATIVE_OPT_IN_REQUIRED",
    "NATIVE_INJECTION_CONFLICT", "NATIVE_UNAVAILABLE", "READER_NOT_CONFIGURED", "CLOCK_NOT_CONFIGURED",
)
ADAPTER_INCOMPLETE = (
    "TRUNCATED", "PROCESS_MEMORY_UNAVAILABLE", "PERMISSION_DENIED", "PROCESS_VANISHED",
    "READ_FAILED", "READER_EXCEPTION", "CAPTURE_STOPPED", "OPEN_ATTEMPT_CAP_EXCEEDED",
    "PRIOR_IDENTITY_UNVERIFIED", "TOTAL_BYTES_CAP_EXCEEDED", "READ_ATTEMPT_CAP_EXCEEDED",
    "OVERSIZED", "READ_ITERATION_CAP_EXCEEDED", "PROCESS_REPARENTED", "PID_REUSE",
    "PROCESS_NOT_LIVE", "ROSTER_INCOMPLETE", "UNKNOWN_PROCESS", "REGISTERED_PROCESS_MISSING",
    "READ_SKEW_EXCEEDED", "ROOT_UNAVAILABLE",
)
PROBE_INVALID = (
    "INPUT_NOT_JSON", "INPUT_CAP_EXCEEDED", "SCHEMA_INVALID", "INTEGER_INVALID",
    "SOURCE_KIND_INVALID", "CLOCK_DOMAIN_INVALID", "DUPLICATE_IDENTITY", "IDENTITY_CONTRADICTION",
    "PATH_POLICY_VIOLATION", "SYMLINK_REJECTED", "DESCRIPTOR_INVALID",
    "DESCRIPTOR_CHANGED", "DESCRIPTOR_ALIAS", "MOUNT_MISMATCH", "NAMESPACE_METHOD_INVALID",
    "NAMESPACE_DESCRIPTOR_MISMATCH", "READER_CONTRACT_VIOLATION", "INVALID_UTF8",
    "DUPLICATE_FIELD", "CLOCK_FAILURE", "CLOCK_REGRESSION", "READ_WINDOW_MISMATCH",
    "REFERENCE_DIGEST_MISMATCH", "REFERENCE_INVALID", "INPUT_CHANGED", "REASON_CODE_INVALID",
)
PROBE_INCOMPLETE = (
    "PERMISSION_DENIED", "PROCESS_VANISHED", "READ_FAILED", "CALLBACK_EXCEPTION",
    "BOOT_ID_CHANGED", "NAMESPACE_MISMATCH", "PID_REUSE", "PROCESS_REPARENTED",
    "UNKNOWN_PROCESS", "ROSTER_INCOMPLETE", "READ_SKEW_EXCEEDED", "STALE_READING",
    "FRAME_TIMESTAMP_MISSING", "FRAME_GAP_EXCEEDED", "COVERAGE_UNBOUNDED",
    "REFERENCE_INCOMPLETE", "REFERENCE_ROSTER_MISMATCH", "REFERENCE_ENVIRONMENT_MISMATCH",
    "REQUEST_INTEGRITY_UNAVAILABLE", "CAPTURE_REQUEST_REJECTED", "CLOCK_DOMAIN_UNCOMPARABLE",
)
VERIFIERS = {
    "ADAPTER_D2B2": (ADAPTER_SCHEMA, ADAPTER_INVALID, ADAPTER_INCOMPLETE,
                     "CAPTURE_CONSISTENT_NONQUALIFYING"),
    "PROBE_B3A": (PROBE_SCHEMA, PROBE_INVALID, PROBE_INCOMPLETE, "CONSISTENT"),
    "BRIDGE_H0": (bridge.SCHEMA + ".report", bridge.INVALID_CODES, bridge.INCOMPLETE_CODES, "CONSISTENT"),
}
ORIGINS = {
    "INJECTED_TEST_ONLY": ("TEST_INJECTED", "UNVERIFIED", "INJECTED_MONOTONIC_NS"),
    "NATIVE_PROCFS_UNVERIFIED": ("NATIVE_PROCFS_UNVERIFIED", "UNVERIFIED_NATIVE_CAPTURE", "LOCAL_MONOTONIC_NS"),
}
RESERVED_LABELS = (
    "NATIVE", "AUTHENTIC", "ATTEST", "QUALIF", "VERIFIED", "CORROBORAT",
    "INJECTEDTESTONLY", "INJECTEDMONOTONICNS", "NOTESTABLISHED", "NOTIMPLEMENTED",
    "INCONCLUSIVE", "NOTOBSERVED", "CALLERCONFIGUREDONLY", "ALIASDETECTED",
    "NOTACQUIRED", "SEQUENTIALNONATOMIC", "CONSISTENT", "INCOMPLETE", "INVALID", "AGREES",
)


class _Rejected(Exception):
    def __init__(self, code):
        self.code = code


def _need(condition, code="SCHEMA_INVALID"):
    if not condition:
        raise _Rejected(code)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def digest(value):
    """Digest an already validated JSON tree; no origin authentication implied."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IntegrationReport:
    serialized: str

    def to_dict(self):
        return json.loads(self.serialized)

    @property
    def sha256(self):
        return hashlib.sha256(self.serialized.encode("utf-8")).hexdigest()


def _copy(value):
    nodes, size, ancestors = 0, 0, set()

    def visit(item, depth):
        nonlocal nodes, size
        nodes += 1
        size += 8
        _need(nodes <= MAX_NODES and depth <= MAX_DEPTH and size <= MAX_BYTES, "INPUT_CAP_EXCEEDED")
        kind = type(item)
        if kind in (dict, list):
            _need(id(item) not in ancestors, "INPUT_NOT_JSON")
            _need(len(item) <= MAX_NODES - nodes, "INPUT_CAP_EXCEEDED")
            ancestors.add(id(item))
            if kind is dict:
                result = {}
                for key, child in item.items():
                    _need(type(key) is str, "INPUT_NOT_JSON")
                    result[visit(key, depth + 1)] = visit(child, depth + 1)
            else:
                result = [visit(child, depth + 1) for child in item]
            ancestors.remove(id(item))
            return result
        if kind is str:
            _need(len(item) <= MAX_STRING, "INPUT_CAP_EXCEEDED")
            try:
                size += len(item.encode("utf-8"))
            except UnicodeError:
                raise _Rejected("INPUT_NOT_JSON") from None
            _need("\x00" not in item, "INPUT_NOT_JSON")
            _need(size <= MAX_BYTES, "INPUT_CAP_EXCEEDED")
        elif kind is int:
            _need(-U64 <= item <= U64, "INTEGER_INVALID")
        elif kind not in (bool, type(None)):
            raise _Rejected("INPUT_NOT_JSON")
        return item

    return visit(value, 0)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, "DUPLICATE_KEY")
        result[key] = value
    return result


def _decode(value):
    if type(value) is bytes:
        _need(len(value) <= MAX_BYTES, "INPUT_CAP_EXCEEDED")
        try:
            value = json.loads(value.decode("utf-8"), object_pairs_hook=_pairs)
        except (ValueError, UnicodeError, RecursionError):
            raise _Rejected("INPUT_NOT_JSON") from None
    return _copy(value)


def _unchanged(value, expected, *, encoded=False):
    try:
        current = _decode(value) if encoded else _copy(value)
        _need(digest(current) == expected, "INPUT_CHANGED")
    except _Rejected:
        raise _Rejected("INPUT_CHANGED") from None


def _object(value, keys):
    _need(type(value) is dict and value.keys() == set(keys))


def _integer(value, low=0, high=U64):
    _need(type(value) is int and low <= value <= high, "INTEGER_INVALID")


def _list(value, maximum, minimum=0):
    _need(type(value) is list)
    _need(minimum <= len(value) <= maximum, "INPUT_CAP_EXCEEDED")


def _hash(value):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "DIGEST_INVALID")


def _label(value):
    _need(type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) is not None, "LABEL_INVALID")
    normalized = value.upper().replace("_", "").replace("-", "")
    _need(not any(token in normalized for token in RESERVED_LABELS), "LABEL_INVALID")


def _codes(value, vocabulary):
    _list(value, len(vocabulary))
    _need(all(type(c) is str and c in vocabulary for c in value), "REASON_CODE_INVALID")
    _need(value == sorted(set(value)), "REASON_CODE_INVALID")
    return set(value)


def _identity(value):
    _object(value, ("pid", "ppid", "starttime_ticks"))
    _integer(value["pid"], 1, 2147483647)
    _integer(value["ppid"], 0, 2147483647)
    _integer(value["starttime_ticks"])
    _need(value["pid"] != value["ppid"], "IDENTITY_INVALID")


def _roster(value):
    _list(value, MAX_PROCESSES, 1)
    for identity in value:
        _identity(identity)
    _need(len({p["pid"] for p in value}) == len(value), "DUPLICATE_IDENTITY")
    return {p["pid"]: p for p in value}


def _match_identity(observed, expected, codes):
    _identity(observed)
    # Callers join by validated PID; paths are separately bound to that PID.
    if observed["starttime_ticks"] != expected["starttime_ticks"]:
        codes.add("PID_REUSE")
    if observed["ppid"] != expected["ppid"]:
        codes.add("PROCESS_REPARENTED")


def _window(value):
    _object(value, ("start_ns", "end_ns"))
    _integer(value["start_ns"])
    _integer(value["end_ns"])
    _need(value["start_ns"] <= value["end_ns"], "CLOCK_REGRESSION")


def _environment(value):
    _need(type(value["boot_id"]) is str and re.fullmatch(
        r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value["boot_id"]) is not None,
        "BOOT_ID_NONCANONICAL")
    ns = value["namespace"]
    _object(ns, ("kind", "value"))
    _need(ns["kind"] in ("INODE", "LABEL"))
    if ns["kind"] == "INODE":
        _integer(ns["value"], 1)
    else:
        _label(ns["value"])
    for name, fs in (("procfs", "proc"), ("nsfs", "nsfs")):
        mount = value[name]
        _object(mount, ("filesystem", "mount_id", "st_dev"))
        _need(mount["filesystem"] == fs, "MOUNT_CONTRADICTION")
        _integer(mount["mount_id"], 1)
        _integer(mount["st_dev"], 1)
    _need(value["procfs"]["mount_id"] != value["nsfs"]["mount_id"] and
          value["procfs"]["st_dev"] != value["nsfs"]["st_dev"], "MOUNT_CONTRADICTION")
    _need(value["clock_kind"] in ("INJECTED_MONOTONIC_NS", "LOCAL_MONOTONIC_NS"))


def _join_environment(value, reference, codes):
    _need(value["boot_id"] == reference["boot_id"], "BOOT_ID_CONFLICT")
    ns, rns = value["namespace"], reference["namespace"]
    if ns["kind"] != "INODE" or rns["kind"] != "INODE":
        codes.add("NAMESPACE_UNCOMPARABLE")
    else:
        _need(ns == rns, "NAMESPACE_CONTRADICTION")
    _need(value["procfs"] == reference["procfs"] and value["nsfs"] == reference["nsfs"],
          "MOUNT_CONTRADICTION")
    if value["clock_kind"] != reference["clock_kind"]:
        codes.add("CLOCK_DOMAIN_UNCOMPARABLE")


def _alias(left, right):
    if left is right:
        return True
    lself = left.__self__ if type(left) is MethodType else None
    rself = right.__self__ if type(right) is MethodType else None
    return ((lself is not None and (lself is rself or lself is right)) or
            (rself is not None and rself is left))


def _containers(value):
    # Called only after _copy has bounded and rejected cycles/subclasses.
    found = set()

    def visit(item):
        if type(item) in (dict, list) and id(item) not in found:
            found.add(id(item))
            for child in (item.values() if type(item) is dict else item):
                visit(child)

    visit(value)
    return found


def _verification(value, capture, codes):
    _object(value, ("schema", "validator", "upstream_schema", "outcome", "reason_codes",
                    "invalid_reason_codes", "incomplete_reason_codes", "report_sha256", "capture_sha256"))
    _need(value["schema"] == VERIFICATION_SCHEMA)
    _need(type(value["validator"]) is str and value["validator"] in VERIFIERS)
    schema, invalid, incomplete, success = VERIFIERS[value["validator"]]
    _need(value["upstream_schema"] == schema)
    _hash(value["report_sha256"])
    _hash(value["capture_sha256"])
    _need(value["capture_sha256"] == digest(capture), "DIGEST_INVALID")
    all_codes = _codes(value["reason_codes"], invalid + incomplete)
    bad = _codes(value["invalid_reason_codes"], invalid)
    gaps = _codes(value["incomplete_reason_codes"], incomplete)
    _need(bad == all_codes & set(invalid) and gaps == all_codes & set(incomplete), "OUTCOME_CONFLICT")
    _need(value["outcome"] == ("INVALID" if bad else "INCOMPLETE" if gaps else success), "OUTCOME_CONFLICT")
    # Injected validators cannot serve as native evidence, even by assertion.
    if value["validator"] in ("BRIDGE_H0", "PROBE_B3A"):
        _need(capture["source_state"] == "INJECTED_TEST_ONLY", "SOURCE_LABEL_CONFLICT")
    if bad:
        codes.add("UPSTREAM_INVALID")
    if gaps:
        codes.add("UPSTREAM_INCOMPLETE")
    return {"validator": value["validator"], "outcome": value["outcome"],
            "reason_codes": sorted(all_codes), "report_sha256": value["report_sha256"],
            "capture_sha256": value["capture_sha256"], "provenance": "CALLER_ASSERTED"}


def _frames(capture, reference, limits, codes):
    roster = _roster(capture["roster"])
    expected = _roster(reference["roster"])
    if capture["roster"] != reference["roster"]:
        codes.add("ROSTER_DRIFT")
    for pid in set(roster) & set(expected):
        _match_identity(roster[pid], expected[pid], codes)
    if set(expected) - set(roster):
        codes.add("MISSING_WORKER")
    if set(roster) - set(expected):
        codes.add("UNKNOWN_PROCESS")
    frames = capture["frames"]
    _list(frames, MAX_FRAMES)
    if len(frames) != reference["frame_count"]:
        codes.add("FRAME_MISSING")
    prior_end, stable, descriptors, appearances, summaries = None, {}, {}, [], []
    for index, frame in enumerate(frames):
        _object(frame, ("index", "start_ns", "end_ns", "observed_pids", "processes", "read_complete", "reason_codes"))
        _integer(frame["index"], 0, MAX_FRAMES - 1)
        _need(frame["index"] == index)
        _window({k: frame[k] for k in ("start_ns", "end_ns")})
        start, end = frame["start_ns"], frame["end_ns"]
        if prior_end is not None:
            _need(start >= prior_end, "CLOCK_REGRESSION")
            if start - prior_end > limits["max_gap_ns"]:
                codes.add("READ_GAP_EXCEEDED")
        prior_end = end
        if end - start > limits["max_read_ns"]:
            codes.add("FRAME_DURATION_EXCEEDED")
        if capture["clock_kind"] == reference["clock_kind"]:
            _need(reference["window"]["start_ns"] <= start <= end <= reference["window"]["end_ns"],
                  "READ_WINDOW_INVALID")
        _need(type(frame["read_complete"]) is bool)
        if not frame["read_complete"]:
            codes.add("PARTIAL_FRAME")
        codes.update(_codes(frame["reason_codes"], READ_CODES))
        _list(frame["observed_pids"], MAX_PROCESSES)
        for pid in frame["observed_pids"]:
            _integer(pid, 1, 2147483647)
        seen = set(frame["observed_pids"])
        _need(len(seen) == len(frame["observed_pids"]), "DUPLICATE_IDENTITY")
        appearances.append(seen)
        if set(expected) - seen:
            codes.add("MISSING_WORKER")
        if seen - set(expected):
            codes.add("UNKNOWN_PROCESS")
        _list(frame["processes"], MAX_PROCESSES)
        process_pids, previous_read = set(), start
        for process in frame["processes"]:
            _object(process, ("identity", "descriptors", "reads"))
            identity = process["identity"]
            _identity(identity)
            pid = identity["pid"]
            _need(pid not in process_pids, "DUPLICATE_IDENTITY")
            process_pids.add(pid)
            if pid not in expected:
                codes.add("UNKNOWN_PROCESS")
            else:
                _match_identity(identity, expected[pid], codes)
            paths = {f"pids/{pid}/{leaf}" for leaf in ("identity", "ns_link", "ns_target")}
            _list(process["descriptors"], 3)
            by_path = {}
            for desc in process["descriptors"]:
                _object(desc, ("path_id", "role", "filesystem", "mount_id", "st_dev", "st_ino"))
                path = desc["path_id"]
                _need(type(path) is str and path in paths, "PATH_POLICY_VIOLATION")
                _need(path not in by_path, "DESCRIPTOR_ALIAS")
                by_path[path] = desc
                target = path.endswith("/ns_target")
                role = "NSFS_TARGET" if target else "PROCFS_LINK_LOCATION" if path.endswith("/ns_link") else "PROCFS_OBJECT"
                _need(desc["role"] == role, "DESCRIPTOR_INVALID")
                for key in ("mount_id", "st_dev", "st_ino"):
                    _integer(desc[key], 1)
                mount = capture["nsfs" if target else "procfs"]
                _need(all(desc[k] == mount[k] for k in mount), "MOUNT_CONTRADICTION")
                ns = capture["namespace"]
                if target and ns["kind"] == "INODE":
                    _need(desc["st_ino"] == ns["value"], "NAMESPACE_CONTRADICTION")
                key = (desc["st_dev"], desc["st_ino"])
                if key in descriptors and descriptors[key][0] != path:
                    _need(target and descriptors[key][1] == "NSFS_TARGET", "DESCRIPTOR_ALIAS")
                descriptors[key] = (path, role)
                _need(path not in stable or stable[path] == desc, "DESCRIPTOR_CHANGED")
                stable[path] = desc
            if set(by_path) != paths:
                codes.add("PARTIAL_FRAME")
            _list(process["reads"], 3)
            read_paths = set()
            for read in process["reads"]:
                _object(read, ("path_id", "start_ns", "end_ns", "status", "sha256", "byte_count", "reason_codes"))
                path = read["path_id"]
                _need(type(path) is str and path in paths, "PATH_POLICY_VIOLATION")
                _need(path not in read_paths, "DUPLICATE_READ")
                read_paths.add(path)
                _window({k: read[k] for k in ("start_ns", "end_ns")})
                _need(start <= read["start_ns"] <= read["end_ns"] <= end, "READ_WINDOW_INVALID")
                _need(read["start_ns"] >= previous_read, "CLOCK_REGRESSION")
                if read["start_ns"] - previous_read > limits["max_gap_ns"]:
                    codes.add("READ_GAP_EXCEEDED")
                previous_read = read["end_ns"]
                _integer(read["byte_count"], 0, MAX_STRING)
                rcodes = _codes(read["reason_codes"], READ_CODES)
                _need(read["status"] == ("FAILED" if rcodes else "OK"), "OUTCOME_CONFLICT")
                codes.update(rcodes)
                if read["sha256"] is None:
                    _need(bool(rcodes), "DIGEST_INVALID")
                else:
                    _hash(read["sha256"])
            if read_paths != paths:
                codes.add("PARTIAL_FRAME")
        if set(expected) - process_pids:
            codes.add("MISSING_WORKER")
        if process_pids != seen:
            codes.add("PARTIAL_FRAME")
        summaries.append({"index": index, "start_ns": start, "end_ns": end,
                          "missing_count": len(set(expected) - seen), "unknown_count": len(seen - set(expected))})
    if frames and capture["clock_kind"] == reference["clock_kind"]:
        if frames[0]["start_ns"] != reference["window"]["start_ns"] or frames[-1]["end_ns"] != reference["window"]["end_ns"]:
            codes.add("COVERAGE_GAP")
    if not frames:
        codes.add("COVERAGE_GAP")
    if appearances:
        union = set().union(*appearances) & set(expected)
        if union - appearances[0]:
            codes.add("WORKER_LATE_OBSERVATION")
        if union - appearances[-1]:
            codes.add("WORKER_EARLY_LAST_OBSERVATION")
    return summaries


def _compare_frames(left, right, max_skew, codes):
    """Compare validated supplied structure/byte facts separately from time."""
    if len(left) != len(right):
        codes.add("SOURCE_DISAGREEMENT")
    for a, b in zip(left, right):
        if any(abs(a[k] - b[k]) > max_skew for k in ("start_ns", "end_ns")):
            codes.add("ROUTE_SKEW_EXCEEDED")
        if (a["index"] != b["index"] or set(a["observed_pids"]) != set(b["observed_pids"]) or
                any(a[k] != b[k] for k in ("read_complete", "reason_codes"))):
            codes.add("SOURCE_DISAGREEMENT")
        ap = {p["identity"]["pid"]: p for p in a["processes"]}
        bp = {p["identity"]["pid"]: p for p in b["processes"]}
        if ap.keys() != bp.keys():
            codes.add("SOURCE_DISAGREEMENT")
        for pid in sorted(ap.keys() & bp.keys()):
            pa, pb = ap[pid], bp[pid]
            if (pa["identity"] != pb["identity"] or
                    {d["path_id"]: d for d in pa["descriptors"]} !=
                    {d["path_id"]: d for d in pb["descriptors"]}):
                codes.add("SOURCE_DISAGREEMENT")
            ar = {r["path_id"]: r for r in pa["reads"]}
            br = {r["path_id"]: r for r in pb["reads"]}
            if ar.keys() != br.keys():
                codes.add("SOURCE_DISAGREEMENT")
            for path in sorted(ar.keys() & br.keys()):
                ra, rb = ar[path], br[path]
                if any(abs(ra[k] - rb[k]) > max_skew for k in ("start_ns", "end_ns")):
                    codes.add("ROUTE_SKEW_EXCEEDED")
                if any(ra[k] != rb[k] for k in ("status", "reason_codes", "sha256", "byte_count")):
                    codes.add("SOURCE_DISAGREEMENT")


def _finish(codes, request_digest=None, raw_digest=None, routes=(), preview=None):
    sealed = set(codes)
    if sealed - set(INVALID_CODES) - set(INCOMPLETE_CODES):
        sealed.add("REASON_CODE_INVALID")
    invalid = sorted(sealed & set(INVALID_CODES))
    incomplete = sorted(sealed & set(INCOMPLETE_CODES))
    outcome = "INVALID" if invalid else "INCOMPLETE" if incomplete else "CONSISTENT"
    result = {
        "schema": SCHEMA + ".report", "outcome": outcome,
        "reason_codes": sorted(set(invalid + incomplete)), "invalid_reason_codes": invalid,
        "incomplete_reason_codes": incomplete, "structure_consistent": outcome == "CONSISTENT",
        "request_sha256": request_digest, "raw_input_sha256": raw_digest, "routes": list(routes),
        "bridge_preview": preview, "qualification": "NONQUALIFYING",
        "independence": "INDEPENDENCE_NOT_ESTABLISHED", "source_origin_authenticated": False,
        "worker_roster_complete": False, "production_memory_qualified": False, "peak_observed": False,
        "native_origin_authentication": "NOT_IMPLEMENTED", "live_native_integration": "NOT_IMPLEMENTED",
        "independent_kernel_attestation": "NOT_ESTABLISHED", "worker_absence_proven": False,
        "holder_release": "NOT_ESTABLISHED", "production_memory_qualification": "INCONCLUSIVE",
        "production_chronological_peak": "NOT_OBSERVED", "production_workload_measured": False,
        "bound_claim": "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK", "atomic_snapshot": False,
        "verification_provenance": "CALLER_ASSERTED", "memo_cap": 256,
    }
    return IntegrationReport(canonical_json(result))


def integrate_native_evidence(request, *, callbacks=()):
    """Validate two bounded supplied routes. callbacks are identity-only, never run.

    Accept exact JSON dict/list trees or strict UTF-8 JSON bytes. All acquisition
    opt-ins are rejected. See CAPTURE_SCHEMA; raw predecessor reports are not
    silently converted. Errors return frozen nonqualifying reports.
    """
    codes, routes, request_digest, raw_digest = set(), [], None, None
    try:
        if type(request) is dict:
            _need(len(request) <= MAX_NODES, "INPUT_CAP_EXCEEDED")
            _need(all(type(key) is str for key in request), "INPUT_NOT_JSON")
            mode = request.get("mode")
            _need(type(mode) is str and mode == "SUPPLIED_ONLY" and request.get("native_opt_in") is False,
                  "NATIVE_MODE_DENIED")
        if type(request) is bytes and len(request) <= MAX_BYTES:
            raw_digest = hashlib.sha256(request).hexdigest()
        data = _decode(request)
        if type(data) is dict:
            _need(data.get("mode") == "SUPPLIED_ONLY" and data.get("native_opt_in") is False,
                  "NATIVE_MODE_DENIED")
        _object(data, ("schema", "mode", "native_opt_in", "reference", "routes", "limits"))
        _need(data["schema"] == SCHEMA)
        request_digest = digest(data)
        reference, limits = data["reference"], data["limits"]
        _object(reference, ("boot_id", "namespace", "procfs", "nsfs", "clock_kind", "roster", "window", "frame_count"))
        _environment(reference)
        _roster(reference["roster"])
        _window(reference["window"])
        _integer(reference["frame_count"], 2, MAX_FRAMES)
        _object(limits, ("max_read_ns", "max_gap_ns", "max_route_skew_ns"))
        for value in limits.values():
            _integer(value, 1, 1000000000)
        _list(data["routes"], 2, 2)
        _need(type(callbacks) is tuple and len(callbacks) in (0, 2), "CALLBACK_CONTRACT_INVALID")
        if callbacks:
            _need(all(callable(c) for c in callbacks), "CALLBACK_CONTRACT_INVALID")
            if _alias(*callbacks):
                codes.add("SOURCE_ALIAS")
        if type(request) is dict:
            original_routes = request["routes"]
            if _containers(original_routes[0]) & _containers(original_routes[1]):
                codes.add("SOURCE_ALIAS")
        prior = None
        for route in data["routes"]:
            _object(route, ("provenance", "capture", "verification"))
            provenance, capture = route["provenance"], route["capture"]
            _object(provenance, ("route_id", "provider_id", "callback_id", "method_id", "collection_domain", "data_origin"))
            for key in ("route_id", "provider_id", "callback_id", "method_id", "collection_domain"):
                _label(provenance[key])
                if prior is not None and provenance[key] == prior["provenance"][key]:
                    codes.add("SOURCE_ALIAS")
            _need(type(capture) is dict)
            if capture.get("schema") in (ADAPTER_SCHEMA, PROBE_SCHEMA, ASSESSMENT_SCHEMA, bridge.SCHEMA + ".report"):
                raise _Rejected("UPSTREAM_CONVERSION_NOT_IMPLEMENTED")
            _object(capture, ("schema", "source_state", "source_kind", "origin_attestation", "clock_kind",
                              "boot_id", "namespace", "procfs", "nsfs", "roster", "frames"))
            _need(capture["schema"] == CAPTURE_SCHEMA)
            state = capture["source_state"]
            _need(type(state) is str and state in ORIGINS, "SOURCE_LABEL_CONFLICT")
            _need(tuple(capture[k] for k in ("source_kind", "origin_attestation", "clock_kind")) == ORIGINS[state],
                  "SOURCE_LABEL_CONFLICT")
            _need(provenance["data_origin"] == state, "SOURCE_LABEL_CONFLICT")
            _environment(capture)
            _join_environment(capture, reference, codes)
            if prior is not None:
                _need(state == prior["capture"]["source_state"], "SOURCE_LABEL_CONFLICT")
            frames = _frames(capture, reference, limits, codes)
            verified = _verification(route["verification"], capture, codes)
            if prior is not None:
                other = prior["capture"]
                # Equal source states already pin both captures to the same clock kind.
                _compare_frames(capture["frames"], other["frames"], limits["max_route_skew_ns"], codes)
            routes.append({"source_state": state, "source_kind": capture["source_kind"],
                           "origin_attestation": capture["origin_attestation"], "clock_kind": capture["clock_kind"],
                           "provenance_sha256": digest(provenance), "capture_sha256": digest(capture),
                           "verification": verified, "frames": frames})
            prior = route
        _unchanged(request, request_digest, encoded=True)
    except _Rejected as exc:
        codes.add(exc.code)
    return _finish(codes, request_digest, raw_digest, routes)


def preview_injected_bridge(request, bridge_request, *, providers, clock):
    """Optional, artificial-only preview. Bridge output is retained by digest.

    Callbacks/clock must be deterministic artificial fixtures. This cannot
    sandbox arbitrary Python code. Native-shaped facts never enter the bridge.
    """
    base = integrate_native_evidence(request)
    result = base.to_dict()
    codes = set(result["reason_codes"])
    if result["outcome"] != "CONSISTENT":
        return base
    preview = None
    try:
        _need(all(r["source_state"] == "INJECTED_TEST_ONLY" for r in result["routes"]), "NATIVE_MODE_DENIED")
        data = _decode(request)
        configured_request = _copy(bridge_request)
        _need(type(configured_request) is dict and configured_request.get("mode") == "INJECTED_TEST_ONLY" and
              configured_request.get("native_opt_in") is False, "NATIVE_MODE_DENIED")
        _need(type(providers) in (list, tuple) and len(providers) == 2, "CALLBACK_CONTRACT_INVALID")
        configured = tuple(providers)
        _need(all(type(p) is bridge.Provider for p in configured), "CALLBACK_CONTRACT_INVALID")
        # The protected bridge performs all remaining callback/clock preflight.
        acquired = bridge.acquire_provenance_bridge(data["reference"]["roster"], configured_request,
                                                    providers=configured, clock=clock)
        original = acquired.to_dict()
        if original["registered_roster"] != data["reference"]["roster"]:
            codes.add("PREVIEW_ROSTER_MISMATCH")
        if original["outcome"] == "INVALID":
            codes.add("UPSTREAM_INVALID")
        elif original["outcome"] == "INCOMPLETE":
            codes.add("UPSTREAM_INCOMPLETE")
        preview = {"schema": bridge.SCHEMA + ".report", "outcome": original["outcome"],
                   "sha256": hashlib.sha256(acquired.serialized.encode("utf-8")).hexdigest(),
                   "reason_codes": original["reason_codes"], "source_state": original["source_state"],
                   "qualification": original["qualification"], "request_sha256": original["request_sha256"]}
        _unchanged(request, result["request_sha256"], encoded=True)
        _unchanged(bridge_request, digest(configured_request))
        _need(type(providers) in (list, tuple) and len(providers) == 2 and
              all(p is q for p, q in zip(providers, configured)), "INPUT_CHANGED")
    except _Rejected as exc:
        codes.add(exc.code)
    return _finish(codes, result["request_sha256"], result["raw_input_sha256"], result["routes"], preview)
