"""Pure, nonqualifying provenance assessment of supplied adapter results.

No reader, clock, collector, callback, or authentication mechanism lives here.
See the companion contract for the deliberately bounded evidence vocabulary.
"""

from dataclasses import dataclass
import hashlib
import json
import re

from scripts.benchmarks.rb_post3d_08p2e2_r2f_f2b4_native_procfs_adapter import (
    SCHEMA, RESULT_SCHEMA, canonical_json,
)

ASSESSMENT_SCHEMA = "rawibumi.native-provenance.f2b4.d2b2b2.v1"
SUCCESS = "CAPTURE_CONSISTENT_NONQUALIFYING"
MAX_DEPTH = 24
MAX_NODES = 200000
MAX_BYTES = 8388608
MAX_STRING = 65536
MAX_CAPTURES = 8
MAX_FRAMES = 32
MAX_PROCESSES = 64
U64 = 18446744073709551615
I64 = 9223372036854775807
PHASES = ("setup", "producer", "attribution", "persistence", "verification", "teardown")
TRUST = ("CALLER_ASSERTED_ONLY", "INJECTED_STRUCTURALLY_CONSISTENT", "NATIVE_SOURCE_UNVERIFIED")
FUTURE_TRUST = ("NATIVE_SOURCE_VERIFIED", "PRODUCTION_CHRONOLOGY_ASSESSED")
STATUSES = ("VERIFIED_BY_INDEPENDENT_PROBE", "CALLER_ASSERTED", "UNAVAILABLE", "INCONSISTENT")
SOURCES = ("CALLER", "INJECTED", "EXTERNAL_PROBE")
ENV_FIELDS = ("boot_id", "namespace_inode", "namespace_device", "namespace_label", "mount_id",
              "mount_type", "clk_tck", "monotonic_start_ns", "monotonic_end_ns")
ADAPTER_INVALID = (
    "INPUT_NOT_JSON", "INPUT_CAP_EXCEEDED", "SCHEMA_INVALID", "UNKNOWN_FIELD",
    "SCHEMA_VERSION_MISMATCH", "SOURCE_KIND_NOT_ACCEPTED", "SOURCE_ORIGIN_CONFLICT",
    "CONFIGURATION_INVALID", "IDENTITY_INVALID", "DUPLICATE_IDENTITY", "BOOT_ID_MISMATCH",
    "PID_NAMESPACE_MISMATCH", "CGROUP_NOT_AUTHORIZED", "READER_CONTRACT_VIOLATION",
    "RAW_TEXT_MALFORMED", "INVALID_UTF8", "DUPLICATE_FIELD", "MISSING_FIELD",
    "IDENTITY_CONTRADICTION", "CLOCK_FAILURE", "CLOCK_NON_MONOTONIC",
    "COUNTER_INCONSISTENT", "PATH_POLICY_VIOLATION", "NATIVE_OPT_IN_REQUIRED",
    "NATIVE_INJECTION_CONFLICT", "NATIVE_UNAVAILABLE", "READER_NOT_CONFIGURED",
    "CLOCK_NOT_CONFIGURED",
)
ADAPTER_INCOMPLETE = (
    "TRUNCATED", "PROCESS_MEMORY_UNAVAILABLE", "PERMISSION_DENIED", "PROCESS_VANISHED",
    "READ_FAILED", "READER_EXCEPTION", "CAPTURE_STOPPED", "OPEN_ATTEMPT_CAP_EXCEEDED",
    "PRIOR_IDENTITY_UNVERIFIED", "TOTAL_BYTES_CAP_EXCEEDED", "READ_ATTEMPT_CAP_EXCEEDED",
    "OVERSIZED", "READ_ITERATION_CAP_EXCEEDED", "PROCESS_REPARENTED", "PID_REUSE",
    "PROCESS_NOT_LIVE", "ROSTER_INCOMPLETE", "UNKNOWN_PROCESS", "REGISTERED_PROCESS_MISSING",
    "READ_SKEW_EXCEEDED", "ROOT_UNAVAILABLE",
)
FIXED = {
    "qualification": "NONQUALIFYING", "independent_verification": "REQUIRED_NOT_PERFORMED",
    "production_memory_qualification": "INCONCLUSIVE", "production_chronological_peak": "NOT_OBSERVED",
    "production_workload_measured": False, "atomic_snapshot": False,
    "bound_claim": "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK", "holder_release": "NOT_ESTABLISHED",
    "owner_termination": "NOT_ESTABLISHED", "simultaneous_holder_occupancy": "NOT_ESTABLISHED",
    "worker_absence_proven": False, "unregistered_worker_coverage": "NOT_ESTABLISHED",
    "roster_provenance": "CALLER_ASSERTED_ONLY", "environment_provenance": "CALLER_ASSERTED_ONLY",
    "procfs_mount_verified": False, "starttime_alignment": "NOT_CALIBRATED", "cgroup": "DISABLED",
}
RESULT_FIELDS = (
    "schema", "source_kind", "origin_attestation", "clock_kind", "run_id", "input_sha256",
    "config", "roster", "frames_requested", "frames", "reasons", "outcome", "read_attempts",
    "open_attempts", "total_bytes", "first_read_start_ns", "last_read_end_ns", "read_skew_ns",
    "invalid_reason_codes", "incomplete_reason_codes", "integrity", "worker_coverage",
)


@dataclass(frozen=True)
class Assessment:
    """Immutable serialized envelope; to_dict returns a new detached JSON tree."""

    serialized: str

    def to_dict(self):
        return json.loads(self.serialized)


class _Invalid(Exception):
    def __init__(self, code):
        self.code = code


def _need(condition, code="SCHEMA_INVALID"):
    if not condition:
        raise _Invalid(code)


def _bounded_copy(value):
    budget = [0, 0]
    ancestors = set()

    def visit(item, depth):
        _need(depth <= MAX_DEPTH, "INPUT_CAP_EXCEEDED")
        budget[0] += 1
        _need(budget[0] <= MAX_NODES, "INPUT_CAP_EXCEEDED")
        kind = type(item)
        if kind is dict or kind is list:
            _need(id(item) not in ancestors, "INPUT_NOT_JSON")
            _need(len(item) <= MAX_NODES - budget[0], "INPUT_CAP_EXCEEDED")
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
                size = len(item.encode("utf-8"))
            except UnicodeError:
                raise _Invalid("INPUT_NOT_JSON") from None
            budget[1] += size
            _need(budget[1] <= MAX_BYTES and size <= MAX_STRING, "INPUT_CAP_EXCEEDED")
        elif kind is int:
            _need(-I64 - 1 <= item <= U64, "INPUT_CAP_EXCEEDED")
        elif kind not in (bool, type(None)):
            raise _Invalid("INPUT_NOT_JSON")
        return item

    return visit(value, 0)


def _object(value, keys):
    _need(type(value) is dict and value.keys() == set(keys))


def _integer(value, low=0, high=I64):
    _need(type(value) is int and low <= value <= high, "INTEGER_INVALID")
    return value


def _list(value, maximum, minimum=0):
    _need(type(value) is list)
    _need(minimum <= len(value) <= maximum, "INPUT_CAP_EXCEEDED")
    return value


def _label(value):
    _need(type(value) is str and len(value) <= 96 and ".." not in value and
          re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is not None, "LABEL_INVALID")


def _uuid(value):
    _need(type(value) is str and re.fullmatch(
        r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value) is not None, "BOOT_ID_NONCANONICAL")


def _hash(value):
    _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "DIGEST_INVALID")


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _codes(value, ordered=True):
    _list(value, 128)
    _need(all(type(c) is str and c in ADAPTER_INVALID + ADAPTER_INCOMPLETE for c in value),
          "REASON_CODE_INVALID")
    _need(not ordered or value == sorted(set(value)), "REASON_CODE_INVALID")
    return set(value)


def _classification(codes):
    return "INVALID" if codes & set(ADAPTER_INVALID) else "INCOMPLETE" if codes else SUCCESS


def _identity(value, config):
    _object(value, ("pid", "ppid", "starttime_ticks", "boot_id", "pid_namespace_id", "role"))
    _integer(value["pid"], 1, 2147483647)
    _integer(value["ppid"], 0, 2147483647)
    _integer(value["starttime_ticks"], 0, U64)
    _uuid(value["boot_id"])
    _need(value["boot_id"] == config["boot_id"], "BOOT_ID_MISMATCH")
    _need(value["pid_namespace_id"] == config["pid_namespace_id"], "PID_NAMESPACE_MISMATCH")
    _label(value["role"])


def _request(data):
    _object(data, ("schema", "source_kind", "capture_mode", "run_id", "config", "roster", "frame_rosters", "cgroup"))
    _need(data["schema"] == SCHEMA, "SCHEMA_VERSION_MISMATCH")
    _need(data["capture_mode"] in ("INJECTED", "NATIVE"), "SOURCE_LABEL_CONFLICT")
    _need(data["source_kind"] == ("TEST_INJECTED" if data["capture_mode"] == "INJECTED" else "NATIVE_REQUEST"),
          "SOURCE_LABEL_CONFLICT")
    _label(data["run_id"])
    c = data["config"]
    _object(c, ("clock_ticks_per_second", "boot_id", "pid_namespace_id", "max_read_skew_ns", "max_bytes",
                "max_total_bytes", "max_read_attempts", "max_read_iterations", "smaps_rollup_policy"))
    for key, high in (("clock_ticks_per_second", 1000000), ("max_bytes", 65536),
                      ("max_total_bytes", 4194304), ("max_read_attempts", 16384), ("max_read_iterations", 128)):
        _integer(c[key], 1, high)
    _integer(c["max_read_skew_ns"])
    _uuid(c["boot_id"])
    _label(c["pid_namespace_id"])
    _need(c["smaps_rollup_policy"] in ("NOT_SAMPLED", "OPTIONAL_DIAGNOSTIC"))
    roster = data["roster"]
    _object(roster, ("parent", "workers", "complete"))
    _need(type(roster["complete"]) is bool)
    identities = [roster["parent"]] + _list(roster["workers"], MAX_PROCESSES - 1)
    for p in identities:
        _identity(p, c)
    pids = [p["pid"] for p in identities]
    _need(len(set(pids)) == len(pids), "DUPLICATE_IDENTITY")
    _need(roster["parent"]["role"] == "parent" and roster["parent"]["ppid"] not in pids,
          "PARENT_RELATION_CONTRADICTION")
    _need(all(p["ppid"] == pids[0] and p["role"] != "parent" for p in identities[1:]),
          "PARENT_RELATION_CONTRADICTION")
    for observed in _list(data["frame_rosters"], MAX_FRAMES, 1):
        _list(observed, MAX_PROCESSES)
        for pid in observed:
            _integer(pid, 1, 2147483647)
        _need(len(observed) == len(set(observed)), "DUPLICATE_IDENTITY")
    _need(data["cgroup"] is None or data["cgroup"] == {"enabled": False}, "SCHEMA_INVALID")
    if data["cgroup"] is not None:
        _need(data["cgroup"]["enabled"] is False)
    return identities


class _Verifier:
    def __init__(self):
        self.invalid = set()
        self.incomplete = set()
        self.notes = {"PROBE_EVIDENCE_UNVERIFIED", "DISCOVERY_UNVERIFIED", "NONATOMIC_SEQUENTIAL_RSS"}
        self.summaries = []
        self.trust = []
        self.prior_environment = None
        self.prior_registration_environment = None
        self.prior_identities = None
        self.previous_end = None

    def check(self, condition, code, incomplete=False):
        if not condition:
            (self.incomplete if incomplete else self.invalid).add(code)

    def field(self, field, validator):
        _object(field, ("value", "source", "status"))
        _need(field["source"] in SOURCES and field["status"] in STATUSES, "PROBE_SCHEMA_INVALID")
        if field["status"] == "VERIFIED_BY_INDEPENDENT_PROBE":
            # EXTERNAL_PROBE is also only a declaration; no authenticator exists.
            self.invalid.add("PROBE_VERIFICATION_OVERCLAIM")
        if field["status"] == "INCONSISTENT":
            self.invalid.add("PROBE_INCONSISTENT")
        if field["status"] == "UNAVAILABLE":
            _need(field["value"] is None, "PROBE_SCHEMA_INVALID")
            self.notes.add("PROBE_FIELD_UNAVAILABLE")
            return None
        validator(field["value"])
        return field["value"]

    def probes(self, evidence, request, summary):
        _object(evidence, ("environments", "processes", "alignment", "coverage", "claimed_trust",
                           "discovery", "cgroup_diagnostic"))
        _need(evidence["claimed_trust"] in TRUST + FUTURE_TRUST, "TRUST_CLAIM_INVALID")
        environments = _list(evidence["environments"], 8, 1)
        values = []
        for env in environments:
            _object(env, ENV_FIELDS)
            v = {}
            for key in ENV_FIELDS:
                validator = (_uuid if key == "boot_id" else _label if key == "namespace_label" else
                             self.mount_type if key == "mount_type" else
                             (lambda n: _integer(n, 1, 1000000)) if key == "clk_tck" else
                             (lambda n: _integer(n, 1, U64)) if key in ("namespace_inode", "mount_id") else _integer)
                v[key] = self.field(env[key], validator)
            if v["monotonic_start_ns"] is not None and v["monotonic_end_ns"] is not None:
                self.check(v["monotonic_start_ns"] <= v["monotonic_end_ns"], "PROBE_CLOCK_REGRESSION")
                if summary["first_read_start_ns"] is not None:
                    self.check(v["monotonic_start_ns"] <= summary["first_read_start_ns"], "PROBE_WINDOW_CONFLICT")
                if summary["last_read_end_ns"] is not None:
                    self.check(summary["last_read_end_ns"] <= v["monotonic_end_ns"], "PROBE_WINDOW_CONFLICT")
            if v["mount_id"] is None:
                self.notes.add("MOUNT_ID_UNAVAILABLE")
            self.notes.add("MOUNT_TYPE_UNVERIFIED")
            c = request["config"]
            for key, expected, code in (("boot_id", c["boot_id"], "BOOT_ID_MISMATCH"),
                                        ("namespace_label", c["pid_namespace_id"], "PID_NAMESPACE_MISMATCH"),
                                        ("clk_tck", c["clock_ticks_per_second"], "CLK_TCK_MISMATCH")):
                if v[key] is not None:
                    self.check(v[key] == expected, code)
            values.append(v)
        # Compare every available reading, including partial records.
        merged = {}
        for v in values:
            for key, value in v.items():
                if value is not None and key not in ("monotonic_start_ns", "monotonic_end_ns"):
                    self.check(key not in merged or merged[key] == value, "ENVIRONMENT_PROBE_CONFLICT")
                    merged[key] = value
        if self.prior_environment is not None:
            for key in set(merged) & set(self.prior_environment):
                self.check(merged[key] == self.prior_environment[key], "CROSS_CAPTURE_ENVIRONMENT_CONFLICT")
        self.prior_environment = {**(self.prior_environment or {}), **merged}
        _need(type(evidence["discovery"]) is dict, "PROBE_SCHEMA_INVALID")
        self.field(evidence["discovery"], self.discovery)
        if evidence["cgroup_diagnostic"] is not None:
            self.field(evidence["cgroup_diagnostic"], lambda n: _integer(n, 0, U64))
            self.notes.add("CGROUP_DIAGNOSTIC_ONLY")
        identities = [request["roster"]["parent"]] + request["roster"]["workers"]
        expected = {p["pid"]: p for p in identities}
        seen = set()
        for p in _list(evidence["processes"], MAX_PROCESSES):
            _object(p, ("pid", "starttime_ticks", "ppid"))
            pid = self.field(p["pid"], lambda n: _integer(n, 1, 2147483647))
            ticks = self.field(p["starttime_ticks"], lambda n: _integer(n, 0, U64))
            ppid = self.field(p["ppid"], lambda n: _integer(n, 0, 2147483647))
            if pid is None:
                self.incomplete.add("PROBE_IDENTITY_MISSING")
                continue
            self.check(pid not in seen, "DUPLICATE_PROBE_IDENTITY")
            seen.add(pid)
            if pid not in expected:
                self.incomplete.add("UNKNOWN_WORKER")
                continue
            if ticks is None or ppid is None:
                self.incomplete.add("PROBE_IDENTITY_MISSING")
            else:
                self.check(ticks == expected[pid]["starttime_ticks"], "PID_REUSE", True)
                self.check(ppid == expected[pid]["ppid"], "PROCESS_REPARENTED", True)
                self.check(ppid != pid, "PARENT_RELATION_CONTRADICTION")
        self.check(set(expected) <= seen, "PROBE_IDENTITY_MISSING", True)
        alignment = evidence["alignment"]
        if alignment is not None:
            _object(alignment, ("monotonic_ns", "boottime_ns"))
            mono = self.field(alignment["monotonic_ns"], _integer)
            boot = self.field(alignment["boottime_ns"], _integer)
            if mono is not None and boot is not None:
                self.check(boot >= mono, "BOOT_ALIGNMENT_CONFLICT")
                if merged.get("clk_tck") is not None and summary["first_read_start_ns"] is not None:
                    frequency = merged["clk_tck"]
                    tolerance = (1000000000 + frequency - 1) // frequency
                    aligned = summary["first_read_start_ns"] + boot - mono
                    for p in identities:
                        self.check(p["starttime_ticks"] * 1000000000 // frequency <= aligned + tolerance,
                                   "STARTTIME_ALIGNMENT_CONFLICT")
            self.notes.add("BOOT_ALIGNMENT_UNVERIFIED")
        else:
            self.notes.add("BOOT_ALIGNMENT_UNAVAILABLE")
        self.coverage(evidence["coverage"], request, summary)

    @staticmethod
    def mount_type(value):
        _need(value == "proc", "PROCFS_TYPE_MISMATCH")

    @staticmethod
    def discovery(value):
        _need(value in ("UNKNOWN", "ROSTER_ONLY", "INDEPENDENT_INJECTED"), "PROBE_SCHEMA_INVALID")

    def coverage(self, coverage, request, summary):
        _object(coverage, ("frame_phases", "required_phases", "max_frame_gap_ns"))
        _integer(coverage["max_frame_gap_ns"], 1)
        phases = _list(coverage["frame_phases"], MAX_FRAMES)
        _need(len(phases) == len(request["frame_rosters"]), "PHASE_PLAN_MISMATCH")
        _need(all(p is None or p in PHASES for p in phases), "PHASE_INVALID")
        required = _list(coverage["required_phases"], len(PHASES))
        _need(all(p in PHASES for p in required) and len(set(required)) == len(required), "PHASE_INVALID")
        covered = {phases[f["index"]] for f in summary["frames"] if f["usable"]}
        summary["uncovered_phases"] = sorted(set(required) - covered)
        self.check(not summary["uncovered_phases"], "PHASE_COVERAGE_GAP", True)
        for gap in summary["frame_gaps_ns"]:
            self.check(gap <= coverage["max_frame_gap_ns"], "FRAME_GAP_EXCEEDED", True)
        if summary["preceding_capture_gap_ns"] is not None:
            self.check(summary["preceding_capture_gap_ns"] <= coverage["max_frame_gap_ns"],
                       "FRAME_GAP_EXCEEDED", True)

    def window(self, container, reads):
        starts = [r["start_ns"] for r in reads if r["start_ns"] is not None]
        ends = [r["end_ns"] for r in reads if r["end_ns"] is not None]
        first, last = min(starts) if starts else None, max(ends) if ends else None
        skew = last - first if first is not None and last is not None else None
        for key, actual in (("first_read_start_ns", first), ("last_read_end_ns", last), ("read_skew_ns", skew)):
            if container[key] is not None:
                _integer(container[key])
            self.check(container[key] == actual, "READ_WINDOW_MISMATCH")
        return first, last, skew

    def _read_record(self, r, identity, label, config):
        _object(r, ("label", "kind", "pid", "status", "start_ns", "end_ns", "byte_length", "sha256",
                    "byte_provenance_complete", "read_calls", "requested_limits", "reason_codes", "exception_class"))
        _integer(r["pid"], 1, 2147483647)
        self.check(r["pid"] == identity["pid"], "IDENTITY_CONTRADICTION")
        self.check(r["label"] == label and r["kind"] == ("stat" if label.startswith("stat_") else label),
                   "READ_SEQUENCE_INVALID")
        _need(r["status"] in ("OK", "FAILED", "NOT_READ"))
        codes = _codes(r["reason_codes"], ordered=False)
        self.check((r["status"] == "OK") == (not codes), "READ_STATUS_MISMATCH")
        for key in ("start_ns", "end_ns"):
            if r[key] is not None:
                _integer(r[key])
        self.check((r["status"] == "NOT_READ") == (r["start_ns"] is None), "READ_STATUS_MISMATCH")
        self.check(r["start_ns"] is not None or r["end_ns"] is None, "READ_WINDOW_MISMATCH")
        if r["start_ns"] is not None and r["end_ns"] is not None:
            self.check(r["end_ns"] >= r["start_ns"], "CLOCK_REGRESSION")
        if r["start_ns"] is not None and r["end_ns"] is None:
            self.check(bool(codes & {"CLOCK_FAILURE", "CLOCK_NON_MONOTONIC"}), "READ_WINDOW_MISMATCH")
        if r["status"] == "OK":
            self.check(r["end_ns"] is not None, "READ_WINDOW_MISMATCH")
        _integer(r["byte_length"], 0, 4194305)
        _integer(r["read_calls"], 0, config["max_read_iterations"])
        if r["start_ns"] is None:
            self.check(r["byte_length"] == r["read_calls"] == 0, "READ_ACCOUNTING_MISMATCH")
        limits = _list(r["requested_limits"], config["max_read_iterations"])
        for n in limits:
            _integer(n, 1, config["max_bytes"] + 1)
        self.check(len(limits) == r["read_calls"] and all(b <= a for a, b in zip(limits, limits[1:])),
                   "READ_ACCOUNTING_MISMATCH")
        _need(type(r["byte_provenance_complete"]) is bool)
        if r["byte_provenance_complete"]:
            _hash(r["sha256"])
            self.check(r["start_ns"] is not None, "BYTE_PROVENANCE_CONFLICT")
        else:
            self.check(r["sha256"] is None, "BYTE_PROVENANCE_CONFLICT")
        if r["status"] == "OK":
            self.check(r["byte_provenance_complete"] and 0 < r["read_calls"] and
                       r["byte_length"] <= config["max_bytes"], "BYTE_PROVENANCE_CONFLICT")
        self.exception_class(r["exception_class"])
        return codes

    @staticmethod
    def exception_class(value):
        _need(value is None or value in ("PermissionError", "FileNotFoundError", "ProcessLookupError", "OSError",
              "ValueError", "TypeError", "RuntimeError", "TimeoutError", "BlockingIOError", "InterruptedError", "Exception"))

    def capture(self, capture, request, evidence):
        _object(capture, tuple(FIXED) + RESULT_FIELDS)
        _need(capture["schema"] == RESULT_SCHEMA, "SCHEMA_VERSION_MISMATCH")
        for key, value in FIXED.items():
            _need(type(capture[key]) is type(value) and capture[key] == value, "FIXED_NONCLAIM_CONFLICT")
        integrity = capture["integrity"]
        _object(integrity, ("algorithm", "scope", "sha256"))
        _need(integrity["algorithm"] == "sha256" and integrity["scope"] == "canonical result excluding integrity",
              "DIGEST_CONTRACT_UNSUPPORTED")
        _hash(integrity["sha256"])
        matched = integrity["sha256"] == _digest({k: v for k, v in capture.items() if k != "integrity"})
        (self.notes if matched else self.invalid).add("CAPTURE_HASH_VERIFIED" if matched else "CAPTURE_HASH_MISMATCH")
        if capture["input_sha256"] is None:
            self.notes.add("REQUEST_INTEGRITY_UNAVAILABLE")
            self.invalid.add("CAPTURE_REQUEST_REJECTED")
            _need(capture["frames"] == [] and capture["config"] is None and capture["roster"] is None,
                  "REQUEST_RESULT_MISMATCH")
            return
        _hash(capture["input_sha256"])
        request_match = capture["input_sha256"] == _digest(request)
        (self.notes if request_match else self.invalid).add("REQUEST_HASH_VERIFIED" if request_match else "REQUEST_HASH_MISMATCH")
        identities = _request(request)
        registration_environment = tuple(request["config"][k] for k in
                                         ("boot_id", "pid_namespace_id", "clock_ticks_per_second"))
        if self.prior_registration_environment is not None:
            self.check(registration_environment == self.prior_registration_environment,
                       "CROSS_CAPTURE_ENVIRONMENT_CONFLICT")
        self.prior_registration_environment = registration_environment
        native = request["capture_mode"] == "NATIVE"
        expected_labels = (("NATIVE_PROCFS_UNVERIFIED", "UNVERIFIED_NATIVE_CAPTURE", "LOCAL_MONOTONIC_NS") if native else
                           ("TEST_INJECTED", "UNVERIFIED", "INJECTED_MONOTONIC_NS"))
        self.check(tuple(capture[k] for k in ("source_kind", "origin_attestation", "clock_kind")) == expected_labels,
                   "SOURCE_LABEL_CONFLICT")
        tier = TRUST[2] if native else TRUST[1]
        self.trust.append(tier)
        for key in ("config", "roster", "run_id"):
            self.check(_digest(capture[key]) == _digest(request[key]), "REQUEST_RESULT_MISMATCH")
        _integer(capture["frames_requested"], 1, MAX_FRAMES)
        self.check(capture["frames_requested"] == len(request["frame_rosters"]), "REQUEST_RESULT_MISMATCH")
        frames = _list(capture["frames"], MAX_FRAMES, 1)
        # Coverage indexes the requested phase plan using recorded frame order.
        # Reject excess frames before any summary can reach that lookup.
        _need(len(frames) <= len(request["frame_rosters"]), "REQUEST_RESULT_MISMATCH")
        self.check(len(frames) == len(request["frame_rosters"]), "CAPTURE_STOPPED", True)
        observed_ids = {p["pid"]: (p["starttime_ticks"], p["ppid"]) for p in identities}
        if self.prior_identities is not None:
            self.check(set(observed_ids) == set(self.prior_identities), "CROSS_CAPTURE_ROSTER_CHANGED", True)
            for pid in set(observed_ids) & set(self.prior_identities):
                self.check(observed_ids[pid][0] == self.prior_identities[pid][0], "PID_REUSE", True)
                self.check(observed_ids[pid][1] == self.prior_identities[pid][1], "PROCESS_REPARENTED", True)
        self.prior_identities = {**(self.prior_identities or {}), **observed_ids}
        config = request["config"]
        labels = ["stat_before", "status"] + (["smaps_rollup"] if config["smaps_rollup_policy"] == "OPTIONAL_DIAGNOSTIC" else []) + ["stat_after"]
        summary = {"capture_hash": integrity["sha256"], "capture_hash_verified": matched,
                   "request_hash_verified": request_match, "first_read_start_ns": None, "last_read_end_ns": None,
                   "read_skew_ns": None, "max_frame_skew_ns": None, "frame_gaps_ns": [],
                   "frames": [], "missing_identity_count": 0, "unknown_identity_count": 0, "uncovered_phases": []}
        prior_capture_end = self.previous_end
        summary["preceding_capture_gap_ns"] = None
        all_reads, all_codes, previous_frame_end = [], set(), None
        for index, frame in enumerate(frames):
            _object(frame, ("index", "status", "reason_codes", "processes", "observed_pids", "roster_complete",
                            "first_read_start_ns", "last_read_end_ns", "read_skew_ns", "read_window_complete"))
            _integer(frame["index"], 0, MAX_FRAMES - 1)
            self.check(frame["index"] == index, "FRAME_INDEX_MISMATCH")
            _need(type(frame["roster_complete"]) is bool and type(frame["read_window_complete"]) is bool)
            codes = _codes(frame["reason_codes"])
            _list(frame["observed_pids"], MAX_PROCESSES)
            for pid in frame["observed_pids"]:
                _integer(pid, 1, 2147483647)
            _need(len(set(frame["observed_pids"])) == len(frame["observed_pids"]), "DUPLICATE_IDENTITY")
            self.check(index < len(request["frame_rosters"]) and frame["observed_pids"] == request["frame_rosters"][index],
                       "REQUEST_RESULT_MISMATCH")
            self.check(frame["roster_complete"] == request["roster"]["complete"], "REQUEST_RESULT_MISMATCH")
            missing = set(observed_ids) - set(frame["observed_pids"])
            unknown = set(frame["observed_pids"]) - set(observed_ids)
            summary["missing_identity_count"] += len(missing)
            summary["unknown_identity_count"] += len(unknown)
            derived = set()
            if missing:
                derived.add("REGISTERED_PROCESS_MISSING")
            if unknown:
                derived.add("UNKNOWN_PROCESS")
            if not request["roster"]["complete"]:
                derived.add("ROSTER_INCOMPLETE")
            processes = _list(frame["processes"], MAX_PROCESSES)
            _need(len(processes) == len(identities), "PROCESS_ROSTER_MISMATCH")
            frame_reads = []
            for p, identity in zip(processes, identities):
                _object(p, ("identity", "status", "reason_codes", "reads", "stat_before_identity", "stat_after_identity",
                            "open_exception_class", "vmrss_bytes", "vmhwm_bytes", "smaps_rollup"))
                _identity(p["identity"], config)
                self.check(p["identity"] == identity, "PROCESS_ROSTER_MISMATCH")
                pcodes = _codes(p["reason_codes"])
                derived.update(pcodes)
                self.exception_class(p["open_exception_class"])
                reads = _list(p["reads"], len(labels))
                _need(len(reads) == len(labels), "READ_SEQUENCE_INVALID")
                for r, label in zip(reads, labels):
                    rcodes = self._read_record(r, identity, label, config)
                    derived.update(rcodes)
                    self.check(rcodes <= pcodes, "REASON_PROPAGATION_MISMATCH")
                    if label in ("stat_before", "stat_after"):
                        observed = p[label + "_identity"]
                        if observed is not None:
                            _object(observed, ("pid", "ppid", "starttime_ticks", "state"))
                            _integer(observed["pid"], 1, 2147483647)
                            _integer(observed["ppid"], 0, 2147483647)
                            _integer(observed["starttime_ticks"], 0, U64)
                            _need(observed["state"] in ("R", "S", "D", "Z", "T", "t", "X", "x", "K", "W", "P", "I", "N"))
                            if observed["pid"] != identity["pid"]:
                                derived.add("IDENTITY_CONTRADICTION")
                            if observed["ppid"] != identity["ppid"]:
                                derived.add("PROCESS_REPARENTED")
                            if observed["ppid"] == observed["pid"]:
                                self.invalid.add("PARENT_RELATION_CONTRADICTION")
                            if observed["starttime_ticks"] != identity["starttime_ticks"]:
                                derived.add("PID_REUSE")
                            if observed["state"] in ("Z", "X", "x"):
                                derived.add("PROCESS_NOT_LIVE")
                            self.check(r["status"] == "OK", "IDENTITY_READ_MISMATCH")
                        else:
                            self.check(r["status"] != "OK", "IDENTITY_READ_MISMATCH")
                frame_reads.extend(reads)
                self.check(p["status"] == frame["status"], "PROCESS_STATUS_MISMATCH")
                if frame["status"] != SUCCESS:
                    self.check(p["vmrss_bytes"] is p["vmhwm_bytes"] is p["smaps_rollup"] is None,
                               "FAILED_FRAME_MEMORY_PRESENT")
                else:
                    _integer(p["vmrss_bytes"], 0, U64)
                    _integer(p["vmhwm_bytes"], 0, U64)
                    self.check(p["vmhwm_bytes"] >= p["vmrss_bytes"], "COUNTER_INCONSISTENT")
                    if p["smaps_rollup"] is not None:
                        self.smaps(p["smaps_rollup"])
                    self.check((p["smaps_rollup"] is not None) == ("smaps_rollup" in labels), "SMAPS_POLICY_MISMATCH")
            # The adapter uses barriers: frame -> label -> registered process.
            for offset in range(len(labels)):
                for p in processes:
                    r = p["reads"][offset]
                    for key in ("start_ns", "end_ns"):
                        if r[key] is not None:
                            self.check(self.previous_end is None or r[key] >= self.previous_end, "CLOCK_REGRESSION")
                            self.previous_end = r[key]
            first, last, skew = self.window(frame, frame_reads)
            if skew is not None and skew > config["max_read_skew_ns"]:
                derived.add("READ_SKEW_EXCEEDED")
            self.check(derived <= codes, "FRAME_REASON_MISMATCH")
            self.check(frame["status"] == _classification(codes), "FRAME_STATUS_MISMATCH")
            self.check(frame["read_window_complete"] == all(r["start_ns"] is not None and r["end_ns"] is not None for r in frame_reads),
                       "READ_WINDOW_MISMATCH")
            if previous_frame_end is not None and first is not None:
                summary["frame_gaps_ns"].append(first - previous_frame_end)
            previous_frame_end = last
            if skew is not None:
                summary["max_frame_skew_ns"] = max(summary["max_frame_skew_ns"] or 0, skew)
            summary["frames"].append({"index": index, "first_read_start_ns": first, "last_read_end_ns": last,
                                      "read_skew_ns": skew, "usable": not codes and frame["read_window_complete"],
                                      "missing_identity_count": len(missing), "unknown_identity_count": len(unknown),
                                      "read_window_complete": frame["read_window_complete"]})
            all_reads.extend(frame_reads)
            all_codes.update(codes)
        first, last, skew = self.window(capture, all_reads)
        summary.update(first_read_start_ns=first, last_read_end_ns=last, read_skew_ns=skew)
        if prior_capture_end is not None and first is not None:
            summary["preceding_capture_gap_ns"] = first - prior_capture_end
        for key in ("total_bytes", "read_attempts", "open_attempts"):
            _integer(capture[key])
        self.check(capture["total_bytes"] == sum(r["byte_length"] for r in all_reads) and
                   capture["read_attempts"] == sum(r["read_calls"] for r in all_reads), "READ_ACCOUNTING_MISMATCH")
        self.check(capture["read_attempts"] <= config["max_read_attempts"] and
                   capture["total_bytes"] <= config["max_total_bytes"] + 1 and
                   1 <= capture["open_attempts"] <= 1 + len(request["frame_rosters"]) * MAX_PROCESSES * 5,
                   "READ_ACCOUNTING_MISMATCH")
        reasons = _list(capture["reasons"], 20000)
        reason_codes = set()
        for reason in reasons:
            _object(reason, ("code", "location"))
            _need(reason["code"] in ADAPTER_INVALID + ADAPTER_INCOMPLETE, "REASON_CODE_INVALID")
            _need(type(reason["location"]) is str and len(reason["location"]) <= 128)
            reason_codes.add(reason["code"])
        self.check(all_codes <= reason_codes, "REASON_PROPAGATION_MISMATCH")
        self.check(len(frames) == len(request["frame_rosters"]) or "CAPTURE_STOPPED" in reason_codes,
                   "REASON_PROPAGATION_MISMATCH")
        self.check(capture["outcome"] == _classification(reason_codes), "CAPTURE_STATUS_MISMATCH")
        self.check(_codes(capture["invalid_reason_codes"]) == reason_codes & set(ADAPTER_INVALID) and
                   _codes(capture["incomplete_reason_codes"]) == reason_codes & set(ADAPTER_INCOMPLETE), "REASON_PROPAGATION_MISMATCH")
        self.check(capture["worker_coverage"] == ("UNCERTAIN" if reason_codes else "REGISTERED_ROSTER_OBSERVED"),
                   "COVERAGE_CLAIM_CONFLICT")
        self.invalid.update(reason_codes & set(ADAPTER_INVALID))
        self.incomplete.update(reason_codes & set(ADAPTER_INCOMPLETE))
        self.probes(evidence, request, summary)
        claim = evidence["claimed_trust"]
        self.check(claim not in FUTURE_TRUST and TRUST.index(claim) <= TRUST.index(tier) if claim in TRUST else False,
                   "TRUST_OVERCLAIM")
        self.summaries.append(summary)

    @staticmethod
    def smaps(value):
        allowed = ("Rss", "Pss", "Pss_Dirty", "Pss_Anon", "Pss_File", "Pss_Shmem", "Shared_Clean", "Shared_Dirty",
                   "Private_Clean", "Private_Dirty", "Referenced", "Anonymous", "KSM", "LazyFree", "AnonHugePages",
                   "ShmemPmdMapped", "FilePmdMapped", "Shared_Hugetlb", "Private_Hugetlb", "Swap", "SwapPss", "Locked")
        _need(type(value) is dict and {"Rss", "Swap"} <= value.keys() and not value.keys() - set(allowed))
        for n in value.values():
            _integer(n, 0, U64)

    def finish(self):
        # No input strings, raw evidence, identifiers or paths are echoed.
        outcome = "INVALID" if self.invalid else "INCOMPLETE" if self.incomplete else "UNVERIFIED"
        tier = min(self.trust, key=TRUST.index) if self.trust and not self.invalid else TRUST[0]
        starts = [s["first_read_start_ns"] for s in self.summaries if s["first_read_start_ns"] is not None]
        ends = [s["last_read_end_ns"] for s in self.summaries if s["last_read_end_ns"] is not None]
        skews = [s["max_frame_skew_ns"] for s in self.summaries if s["max_frame_skew_ns"] is not None]
        result = {"schema": ASSESSMENT_SCHEMA, **FIXED, "outcome": outcome, "trust_level": tier,
                  "reason_codes": sorted(self.invalid | self.incomplete | self.notes),
                  "invalid_reason_codes": sorted(self.invalid), "incomplete_reason_codes": sorted(self.incomplete),
                  "captures": self.summaries, "worker_coverage": "NOT_ESTABLISHED",
                  "observed_windows": {"first_read_start_ns": min(starts) if starts else None,
                                       "last_read_end_ns": max(ends) if ends else None,
                                       "max_frame_skew_ns": max(skews) if skews else None}}
        return Assessment(canonical_json(result))


def assess_provenance(captures, requests, evidence):
    """Assess bounded ordered lists; never execute supplied objects or callbacks.

    Input errors return an immutable INVALID assessment. Cross-capture identity
    continuity is assessed only for the explicitly supplied ordered sequence.
    """
    verifier = _Verifier()
    try:
        captures, requests, evidence = _bounded_copy([captures, requests, evidence])
        _list(captures, MAX_CAPTURES, 1)
        _list(requests, MAX_CAPTURES, 1)
        _list(evidence, MAX_CAPTURES, 1)
        _need(len(captures) == len(requests) == len(evidence), "INPUT_CARDINALITY_MISMATCH")
        for capture, request, probes in zip(captures, requests, evidence):
            verifier.capture(capture, request, probes)
    except _Invalid as exc:
        verifier.invalid.add(exc.code)
    return verifier.finish()
