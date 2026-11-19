"""Pure, bounded synthetic process-RSS evidence validation; no live reader."""

import hashlib
import json
import re

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2a_observer as f2a

SCHEMA = "rawibumi.process-rss-capture.f2b4.v1"
RESULT_SCHEMA = SCHEMA + ".result"
INVALID_CAPTURE = "INVALID_CAPTURE"
INCOMPLETE_CAPTURE = "INCOMPLETE_CAPTURE"
PROCESS_RSS_SAMPLE_COMPLETE = "PROCESS_RSS_SAMPLE_COMPLETE"
PHASES = ("setup", "producer", "attribution", "persistence", "verification", "teardown")
POOLS = ("parent", "producer", "attribution")
MAX_DEPTH = 32
MAX_NODES = 1000000
MAX_TEXT_BYTES = 262144
MAX_TOTAL_TEXT_BYTES = 33554432
MAX_INTEGER_BITS = 63
MAX_EVENTS = 4096
MAX_FRAMES = 4096
MAX_IDENTITIES = 128
MAX_READS_PER_FRAME = 128
MAX_WHITESPACE_RUN = 64
REASON_CLASSES = {
    "INPUT_NOT_JSON": "INVALID", "INPUT_CAP_EXCEEDED": "INVALID",
    "SCHEMA_VERSION_MISMATCH": "INVALID", "SOURCE_TYPE_NOT_ACCEPTED": "INVALID",
    "SCHEMA_INVALID": "INVALID", "UNKNOWN_FIELD": "INVALID",
    "CONFIGURATION_INVALID": "INVALID", "TOPOLOGY_INVALID": "INVALID",
    "CLOCK_DOMAIN_INVALID": "INVALID", "CLOCK_DOMAIN_MISMATCH": "INVALID",
    "DUPLICATE_IDENTITY": "INVALID", "UNROSTERED_PROCESS": "INVALID",
    "SEQUENCE_ORDER_INVALID": "INVALID", "CHRONOLOGY_INVALID": "INVALID",
    "FRAME_CHRONOLOGY_INVALID": "INVALID", "FRAME_KIND_NOT_ACCEPTED": "INVALID",
    "READ_WINDOW_INVALID": "INVALID", "LIFECYCLE_CONTRADICTION": "INVALID",
    "PHASE_PLAN_CONTRADICTION": "INVALID", "PID_REUSE_OR_IDENTITY_RACE": "INVALID",
    "IDENTITY_CONTRADICTION": "INVALID", "ROSTER_CONTRADICTION": "INVALID",
    "RAW_TEXT_MALFORMED": "INVALID", "COUNTER_INCONSISTENT": "INVALID",
    "SMAPS_POLICY_VIOLATION": "INVALID", "INTERNAL_VALIDATION_FAILURE": "INVALID",
    "EVIDENCE_TRUNCATED": "INCOMPLETE", "SAMPLER_TERMINATED": "INCOMPLETE",
    "CAPTURE_DECLARED_INCOMPLETE": "INCOMPLETE", "DECLARED_COUNT_MISMATCH": "INCOMPLETE",
    "SEQUENCE_GAP": "INCOMPLETE", "REGISTRATION_NOT_ESTABLISHED": "INCOMPLETE",
    "PARENT_LIFECYCLE_GAP": "INCOMPLETE", "WORKER_LIFECYCLE_GAP": "INCOMPLETE",
    "ROSTER_CHANGED_IN_FRAME": "INCOMPLETE", "ROSTER_INCOMPLETE": "INCOMPLETE",
    "PROCESS_READ_MISSING": "INCOMPLETE", "PROCESS_READ_FAILED": "INCOMPLETE",
    "RAW_READ_TRUNCATED": "INCOMPLETE", "READ_SKEW_EXCEEDED": "INCOMPLETE",
    "SAMPLE_GAP": "INCOMPLETE", "NO_ELIGIBLE_FRAMES": "INCOMPLETE",
    "AMBIGUOUS_PHASE_FRAME": "INCOMPLETE", "PHASE_COVERAGE_GAP": "INCOMPLETE",
    "OOM_OR_SWAP_OBSERVED": "INCOMPLETE", "CGROUP_LIMIT_EVENT": "INCOMPLETE",
    "CGROUP_CORROBORATION_INCOMPLETE": "INCOMPLETE",
    "CGROUP_HIERARCHY_AMBIGUOUS": "INCOMPLETE", "CGROUP_NOT_ISOLATED": "INCOMPLETE",
}
WARNING_CODES = (
    "SHARED_PAGES_MAY_BE_COUNTED_REPEATEDLY", "OPTIONAL_SMAPS_UNAVAILABLE",
    "CGROUP_DIAGNOSTIC_UNAVAILABLE",
)
_CAVEATS = (
    "Injected synthetic data only; this is not a live collector.",
    "Sequential frames are not atomic and give no bound on the true instantaneous peak.",
    "Shared pages may be counted repeatedly; RSS sums are not unique physical memory.",
    "VmRSS and VmHWM can be inaccurate source counters.",
    "Cgroup values are diagnostics and are never combined with process RSS.",
    "Holder release is not established.",
    "The origin of the supplied data is unverified.",
)


class _Violation(Exception):
    def __init__(self, code):
        self.code = code


def _need(condition, code="SCHEMA_INVALID"):
    if not condition:
        raise _Violation(code)


def _canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False,
                       ensure_ascii=True) + "\n").encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _copy_json(value):
    budget = [0, 0]
    ancestors = set()

    def visit(item, depth):
        _need(depth <= MAX_DEPTH, "INPUT_CAP_EXCEEDED")
        budget[0] += 1
        _need(budget[0] <= MAX_NODES, "INPUT_CAP_EXCEEDED")
        kind = type(item)
        if kind in (list, dict):
            _need(id(item) not in ancestors, "INPUT_NOT_JSON")
            # Reject oversize containers before allocating their copies.
            _need(len(item) <= MAX_NODES - budget[0], "INPUT_CAP_EXCEEDED")
            ancestors.add(id(item))
            if kind is list:
                copied = [visit(child, depth + 1) for child in item]
            else:
                copied = {}
                for key, child in item.items():
                    _need(type(key) is str, "INPUT_NOT_JSON")
                    copied[visit(key, depth + 1)] = visit(child, depth + 1)
            ancestors.remove(id(item))
            return copied
        if kind is str:
            _need(len(item) <= MAX_TEXT_BYTES, "INPUT_CAP_EXCEEDED")
            try:
                size = len(item.encode("utf-8"))
            except UnicodeError:
                raise _Violation("INPUT_NOT_JSON") from None
            _need(size <= MAX_TEXT_BYTES, "INPUT_CAP_EXCEEDED")
            budget[1] += size
            _need(budget[1] <= MAX_TOTAL_TEXT_BYTES, "INPUT_CAP_EXCEEDED")
        elif kind is int:
            _need(item.bit_length() <= MAX_INTEGER_BITS, "INPUT_CAP_EXCEEDED")
        elif kind is float:
            _need(item == item and -float("inf") < item < float("inf"), "INPUT_NOT_JSON")
        else:
            _need(item is None or kind is bool, "INPUT_NOT_JSON")
        return item

    return visit(value, 0)


def _object(value, fields):
    _need(type(value) is dict)
    _need(not (value.keys() - set(fields)), "UNKNOWN_FIELD")
    _need(set(fields) <= value.keys())


def _label(value):
    _need(type(value) is str and bool(value.strip()))


def _integer(value, minimum=0):
    _need(type(value) is int and value >= minimum)


def _identity(value, extra=()):
    _object(value, ("pid", "starttime_ticks", "boot_id") + extra)
    _integer(value["pid"], 1)
    _integer(value["starttime_ticks"])
    _label(value["boot_id"])
    return "%d:%d" % (value["pid"], value["starttime_ticks"])


def _file(value):
    _need(type(value) is dict)
    result = value.get("result")
    _need(result in ("OK", "TRUNCATED", "FAILED"))
    _object(value, ("result", "start_ns", "end_ns", "error" if result == "FAILED" else "text"))
    _integer(value["start_ns"])
    _integer(value["end_ns"])
    if result == "FAILED":
        _need(value["error"] in ("ENOENT", "ESRCH", "EACCES", "EPERM", "EIO"))
    else:
        _need(type(value["text"]) is str)


def _bounded_list(value, cap):
    _need(type(value) is list)
    _need(len(value) <= cap, "INPUT_CAP_EXCEEDED")


def _empty_result(copied, copied_ok=True):
    root = copied if type(copied) is dict else {}
    source = root.get("source_type")
    return {
        "schema": RESULT_SCHEMA, "input_schema": root.get("schema") if type(root.get("schema")) is str else None,
        "source_type": source if source in ("INJECTED_SYNTHETIC", "REAL_PROCFS") else None,
        "origin_attestation": "UNVERIFIED", "outcome": INVALID_CAPTURE,
        "production_memory_qualification": "INCONCLUSIVE",
        "production_chronological_peak": "NOT_OBSERVED", "holder_release": "NOT_ESTABLISHED",
        "actual_measurement_performed": False,
        "run_id": root.get("run_id") if type(root.get("run_id")) is str else None,
        "input_sha256": _digest(copied) if copied_ok else None,
        "provider_input": copied, "reasons": [], "invalid_reason_codes": [],
        "incomplete_reason_codes": [], "warnings": [], "frames": [], "processes": {},
        "phase_coverage": {}, "cgroup_observations": [], "caveats": list(_CAVEATS),
        "sampled_rss": {
            "statistic": "MAX_OF_BOUNDED_SEQUENTIAL_VMRSS_SUMS",
            "frame_semantics": "BOUNDED_SEQUENTIAL_RSS_FRAME", "metric_status": "DIAGNOSTIC_ONLY",
            "comparability": "NOT_COMPARABLE", "bound_claim": "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK",
            "sampled_max_rss_bytes": None, "sampled_max_frame_index": None,
            "eligible_frame_count": 0, "attempted_frame_count": 0,
            "max_eligible_read_skew_ns": None, "configured_max_read_skew_ns": None, "clock_kind": None,
        },
    }


class _Assessment:
    def __init__(self, data, report):
        self.data = data
        self.report = report
        self.reasons = set()
        self.warnings = set()
        self.states = {}
        self.applied_events = []
        self.hwm = {}
        self.cgroup_path = None
        self.cgroup_counts = None

    def reason(self, code, location):
        self.reasons.add((code, location))

    def warning(self, code, location):
        self.warnings.add((code, location))

    def check(self, function, location):
        try:
            function()
            return True
        except _Violation as exc:
            self.reason(exc.code, location)
            return False

    def root(self):
        d = self.data
        self.check(lambda: _object(d, ("schema", "source_type", "run_id", "clock", "source_provenance",
                                       "capture", "configuration", "topology", "events", "frames")), "root")
        if type(d) is not dict:
            return False
        self.check(lambda: _need(d.get("schema") == SCHEMA, "SCHEMA_VERSION_MISMATCH"), "root.schema")
        self.check(lambda: _need(d.get("source_type") == "INJECTED_SYNTHETIC", "SOURCE_TYPE_NOT_ACCEPTED"),
                   "root.source_type")
        self.check(lambda: _label(d.get("run_id")), "root.run_id")
        self.check(self.clock, "root.clock")
        self.check(self.provenance, "root.source_provenance")
        self.check(self.capture, "root.capture")
        self.check(self.configuration, "root.configuration")
        self.check(self.topology, "root.topology")
        self.check(lambda: _bounded_list(d.get("events"), MAX_EVENTS), "root.events")
        self.check(lambda: _bounded_list(d.get("frames"), MAX_FRAMES), "root.frames")
        return not any(REASON_CLASSES[c] == "INVALID" for c, _ in self.reasons)

    def clock(self):
        c = self.data.get("clock")
        _object(c, ("kind", "unit", "domain_id", "host_id", "boot_id", "pid_namespace_id"))
        _label(c["kind"])
        _label(c["unit"])
        _need(c["kind"] == "CLOCK_MONOTONIC" and c["unit"] == "ns", "CLOCK_DOMAIN_INVALID")
        for key in ("domain_id", "host_id", "boot_id", "pid_namespace_id"):
            _label(c[key])

    def provenance(self):
        p = self.data.get("source_provenance")
        labels = ("kernel_release", "os_description", "workload_id", "input_id", "configuration_id",
                  "source_tree_fingerprint", "sampler_code_version", "registration_protocol")
        _object(p, labels + ("origin_attestation", "requested_worker_counts"))
        _need(p["origin_attestation"] == "UNVERIFIED", "SOURCE_TYPE_NOT_ACCEPTED")
        for name in labels:
            _label(p[name])
        _object(p["requested_worker_counts"], ("producer", "attribution"))
        for value in p["requested_worker_counts"].values():
            _integer(value)

    def capture(self):
        c = self.data.get("capture")
        _object(c, ("declared_event_count", "declared_frame_count", "truncated", "sampler_termination",
                    "capture_completeness_declared"))
        _integer(c["declared_event_count"])
        _integer(c["declared_frame_count"])
        _need(type(c["truncated"]) is bool and type(c["capture_completeness_declared"]) is bool)
        _need(c["sampler_termination"] in ("NORMAL", "ABNORMAL"))
        for flag, code in ((c["truncated"], "EVIDENCE_TRUNCATED"),
                           (c["sampler_termination"] == "ABNORMAL", "SAMPLER_TERMINATED"),
                           (not c["capture_completeness_declared"], "CAPTURE_DECLARED_INCOMPLETE")):
            if flag:
                self.reason(code, "root.capture")
        for singular, plural in (("event", "events"), ("frame", "frames")):
            if type(self.data.get(plural)) is list and c["declared_" + singular + "_count"] != len(self.data[plural]):
                self.reason("DECLARED_COUNT_MISMATCH", "root.capture")

    def configuration(self):
        c = self.data.get("configuration")
        _object(c, ("max_read_skew_ns", "max_frame_gap_ns", "phase_plan", "cgroup_requirement", "smaps_rollup_policy"))
        _need(type(c["max_read_skew_ns"]) is int and type(c["max_frame_gap_ns"]) is int)
        _object(c["phase_plan"], POOLS)
        for pool in POOLS:
            _need(type(c["phase_plan"][pool]) is list)
            for phase in c["phase_plan"][pool]:
                _label(phase)
        _label(c["cgroup_requirement"])
        _label(c["smaps_rollup_policy"])
        _need(c["max_read_skew_ns"] >= 0 and c["max_frame_gap_ns"] >= 1, "CONFIGURATION_INVALID")
        for pool in POOLS:
            plan = c["phase_plan"][pool]
            _need(all(p in PHASES for p in plan) and len(plan) == len(set(plan)), "CONFIGURATION_INVALID")
        _need(bool(c["phase_plan"]["parent"]), "CONFIGURATION_INVALID")
        _need(c["cgroup_requirement"] == "CORROBORATION_REQUIRED", "CONFIGURATION_INVALID")
        _need(c["smaps_rollup_policy"] in ("NOT_SAMPLED", "OPTIONAL_DIAGNOSTIC"), "CONFIGURATION_INVALID")

    def topology(self):
        t = self.data.get("topology")
        _object(t, ("execution_mode", "parent_identities", "actual_workers", "registration_coverage"))
        _label(t["execution_mode"])
        _need(t["execution_mode"] in ("inline", "spawned"), "TOPOLOGY_INVALID")
        _need(type(t["parent_identities"]) is list and type(t["actual_workers"]) is list)
        _need(len(t["parent_identities"]) + len(t["actual_workers"]) <= MAX_IDENTITIES, "INPUT_CAP_EXCEEDED")
        _need(len(t["parent_identities"]) == 1, "TOPOLOGY_INVALID")
        _label(t["registration_coverage"])
        _need(t["registration_coverage"] in ("DECLARED_COMPLETE", "NOT_ESTABLISHED"))
        if t["registration_coverage"] == "NOT_ESTABLISHED":
            self.reason("REGISTRATION_NOT_ESTABLISHED", "root.topology")
        parent = t["parent_identities"][0]
        _identity(parent, ("ppid",))
        _integer(parent["ppid"])
        all_ids = [(parent, "parent")]
        for worker in t["actual_workers"]:
            _identity(worker, ("parent_pid", "pool"))
            _integer(worker["parent_pid"], 1)
            _label(worker["pool"])
            _need(worker["pool"] in ("producer", "attribution"), "TOPOLOGY_INVALID")
            all_ids.append((worker, worker["pool"]))
        for ident, pool in all_ids:
            key = _identity(ident, ("ppid",) if pool == "parent" else ("parent_pid", "pool"))
            if pool == "parent":
                _integer(ident["ppid"])
            else:
                _need(ident["parent_pid"] == parent["pid"], "TOPOLOGY_INVALID")
            _need(key not in self.states, "DUPLICATE_IDENTITY")
            clock = self.data.get("clock")
            if type(clock) is dict and type(clock.get("boot_id")) is str:
                _need(ident["boot_id"] == clock["boot_id"], "CLOCK_DOMAIN_MISMATCH")
            self.states[key] = {
                "pool": pool, "pid": ident["pid"], "starttime_ticks": ident["starttime_ticks"],
                "start_ns": None, "exit_ns": None, "entered_phases": [], "observed_phases": [],
                "eligible_observation_count": 0, "max_observed_vmrss_bytes": None,
                "max_observed_vmhwm_bytes": None,
            }
        config = self.data.get("configuration")
        plan = config.get("phase_plan") if type(config) is dict else None
        if t["execution_mode"] == "inline":
            _need(not t["actual_workers"], "TOPOLOGY_INVALID")
            if type(plan) is dict:
                _need(not plan.get("producer") and not plan.get("attribution"), "TOPOLOGY_INVALID")
        else:
            _need(bool(t["actual_workers"]), "TOPOLOGY_INVALID")
            if type(plan) is dict:
                for pool in ("producer", "attribution"):
                    _need(bool(plan.get(pool)) == any(p == pool for _, p in all_ids), "TOPOLOGY_INVALID")

    def reference(self, ident):
        key = _identity(ident)
        _need(ident["boot_id"] == self.data["clock"]["boot_id"], "CLOCK_DOMAIN_MISMATCH")
        _need(key in self.states, "UNROSTERED_PROCESS")
        return key

    def events(self):
        previous_sequence = None
        previous_time = None
        live = set()
        started_pids = {}
        parent_key = next(k for k, s in self.states.items() if s["pool"] == "parent")
        for index, event in enumerate(self.data["events"]):
            loc = "event:%d" % index
            try:
                _need(type(event) is dict)
                kind = event.get("kind")
                _need(kind in ("START", "PHASE", "EXIT"))
                fields = ("sequence", "time_ns", "clock_domain_id", "kind", "identity")
                _object(event, fields + (() if kind == "EXIT" else ("phase",)))
                _integer(event["sequence"])
                _integer(event["time_ns"])
                _label(event["clock_domain_id"])
                key = _identity(event["identity"])
                if kind != "EXIT":
                    _label(event["phase"])
                _need(event["clock_domain_id"] == self.data["clock"]["domain_id"], "CLOCK_DOMAIN_MISMATCH")
                _need(event["identity"]["boot_id"] == self.data["clock"]["boot_id"], "CLOCK_DOMAIN_MISMATCH")
                seq, time = event["sequence"], event["time_ns"]
                old_sequence, old_time = previous_sequence, previous_time
                previous_sequence = seq if old_sequence is None else max(seq, old_sequence)
                previous_time = time if old_time is None else max(time, old_time)
                _need(old_sequence is None or seq > old_sequence, "SEQUENCE_ORDER_INVALID")
                if seq != (0 if old_sequence is None else old_sequence + 1):
                    self.reason("SEQUENCE_GAP", loc)
                _need(old_time is None or time >= old_time, "CHRONOLOGY_INVALID")
                self.reference(event["identity"])
                state = self.states[key]
                parent = self.states[parent_key]
                _need(parent["exit_ns"] is None, "LIFECYCLE_CONTRADICTION")
                if kind == "START":
                    _need(state["start_ns"] is None, "LIFECYCLE_CONTRADICTION")
                    _need(state["pool"] == "parent" or parent_key in live, "LIFECYCLE_CONTRADICTION")
                    _need(not any(self.states[k]["pid"] == state["pid"] for k in live), "PID_REUSE_OR_IDENTITY_RACE")
                    _need(state["starttime_ticks"] > started_pids.get(state["pid"], -1), "PID_REUSE_OR_IDENTITY_RACE")
                else:
                    _need(key in live, "LIFECYCLE_CONTRADICTION")
                    if kind == "PHASE":
                        _need(state["entered_phases"][-1] != event["phase"], "LIFECYCLE_CONTRADICTION")
                if kind != "EXIT":
                    _need(event["phase"] in self.data["configuration"]["phase_plan"][state["pool"]],
                          "PHASE_PLAN_CONTRADICTION")
                    state["entered_phases"].append(event["phase"])
                if kind == "START":
                    state["start_ns"] = time
                    started_pids[state["pid"]] = state["starttime_ticks"]
                    live.add(key)
                elif kind == "EXIT":
                    state["exit_ns"] = time
                    live.remove(key)
                self.applied_events.append(event)
            except _Violation as exc:
                self.reason(exc.code, loc)

    def windows(self, files, a, b, location):
        previous_end = a
        good = True
        for name, item in files:
            if item is None:
                continue
            if not (a <= item["start_ns"] <= item["end_ns"] <= b and previous_end <= item["start_ns"]):
                self.reason("READ_WINDOW_INVALID", location + "/" + name)
                good = False
            previous_end = item["end_ns"]
        return good

    def parse(self, parser, text, loc, guarded=False):
        if guarded and re.search(r"\s{%d,}" % (MAX_WHITESPACE_RUN + 1), text):
            self.reason("RAW_TEXT_MALFORMED", loc)
            return None
        try:
            parsed = parser(text)
            if any(type(v) is int and (v < 0 or v >= 2 ** 63) for v in parsed.values()):
                self.reason("RAW_TEXT_MALFORMED", loc)
                return None
            return parsed
        except f2a.EvidenceError as exc:
            self.reason("COUNTER_INCONSISTENT" if exc.code == "INCONSISTENT_COUNTER" else "RAW_TEXT_MALFORMED", loc)
        except (ValueError, TypeError, OverflowError):
            self.reason("RAW_TEXT_MALFORMED", loc)
        return None

    def read(self, read, loc, a, b, possibly_live, phase, seen, previous_end):
        _object(read, ("identity", "stat_before", "status", "smaps_rollup", "stat_after"))
        key = self.reference(read["identity"])
        _need(key not in seen, "DUPLICATE_IDENTITY")
        seen.add(key)
        _need(key in possibly_live, "ROSTER_CONTRADICTION")
        names = ("stat_before", "status", "smaps_rollup", "stat_after")
        for name in names:
            if name == "smaps_rollup" and read[name] is None:
                continue
            try:
                _file(read[name])
            except _Violation as exc:
                self.reason(exc.code, loc + "/" + name)
                return None, previous_end, None
        files = [(n, read[n]) for n in names]
        before_reasons = set(self.reasons)
        self.windows(files, a, b, loc)
        if previous_end is not None and read["stat_before"]["start_ns"] < previous_end:
            self.reason("READ_WINDOW_INVALID", loc)
        previous_end = read["stat_after"]["end_ns"]
        if self.data["configuration"]["smaps_rollup_policy"] == "NOT_SAMPLED" and read["smaps_rollup"] is not None:
            self.reason("SMAPS_POLICY_VIOLATION", loc + "/smaps_rollup")
        mandatory_ok = True
        for name in ("stat_before", "status", "stat_after"):
            result = read[name]["result"]
            if result != "OK":
                mandatory_ok = False
                self.reason("PROCESS_READ_FAILED" if result == "FAILED" else "RAW_READ_TRUNCATED", loc + "/" + name)
        parsed_stats = []
        exiting = False
        expected_ppid = (self.data["topology"]["parent_identities"][0]["ppid"]
                         if self.states[key]["pool"] == "parent" else self.data["topology"]["parent_identities"][0]["pid"])
        for name in ("stat_before", "stat_after"):
            item = read[name]
            stat = self.parse(f2a.parse_stat, item["text"], loc + "/" + name) if item["result"] == "OK" else None
            parsed_stats.append(stat)
            if stat is not None:
                if stat["pid"] != read["identity"]["pid"] or stat["ppid"] != expected_ppid:
                    self.reason("IDENTITY_CONTRADICTION", loc + "/" + name)
                if stat["starttime_ticks"] != read["identity"]["starttime_ticks"]:
                    self.reason("PID_REUSE_OR_IDENTITY_RACE", loc + "/" + name)
                if stat["state"] in ("Z", "X", "x"):
                    exiting = True
                    self.reason("PROCESS_READ_FAILED", loc + "/" + name)
        if all(s is not None for s in parsed_stats):
            left, right = parsed_stats
            if (left["pid"], left["starttime_ticks"]) != (right["pid"], right["starttime_ticks"]):
                self.reason("PID_REUSE_OR_IDENTITY_RACE", loc)
            if left["ppid"] != right["ppid"]:
                self.reason("IDENTITY_CONTRADICTION", loc)
        status = None
        if not exiting and read["status"]["result"] == "OK":
            status = self.parse(f2a.parse_status, read["status"]["text"], loc + "/status", True)
            if status is not None:
                if status["Pid"] != read["identity"]["pid"] or status["PPid"] != expected_ppid:
                    self.reason("IDENTITY_CONTRADICTION", loc + "/status")
                if status["VmHWM"] < self.hwm.get(key, 0):
                    self.reason("COUNTER_INCONSISTENT", loc + "/status")
                if status["VmSwap"] > 0:
                    self.reason("OOM_OR_SWAP_OBSERVED", loc + "/status")
        smaps = None
        rollup = read["smaps_rollup"]
        if rollup is not None and self.data["configuration"]["smaps_rollup_policy"] == "OPTIONAL_DIAGNOSTIC":
            if rollup["result"] != "OK":
                self.warning("OPTIONAL_SMAPS_UNAVAILABLE", loc + "/smaps_rollup")
            else:
                smaps = self.parse(f2a.parse_smaps_rollup, rollup["text"], loc + "/smaps_rollup", True)
                if smaps is not None and smaps["Swap"] > 0:
                    self.reason("OOM_OR_SWAP_OBSERVED", loc + "/smaps_rollup")
        invalid = any(REASON_CLASSES[c] == "INVALID" for c, _ in self.reasons - before_reasons)
        verified = mandatory_ok and not exiting and not invalid and status is not None and all(s is not None for s in parsed_stats)
        if verified:
            self.hwm[key] = max(self.hwm.get(key, 0), status["VmHWM"])
        hashes = {name: (hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
                         if item is not None and item["result"] != "FAILED" else None) for name, item in files}
        member = {
            "identity": dict(read["identity"]), "pool": self.states[key]["pool"], "phase": phase.get(key),
            "read_status": "VERIFIED" if verified else "NOT_VERIFIED",
            "vmrss_bytes": status["VmRSS"] if verified else None,
            "vmhwm_bytes": status["VmHWM"] if verified else None,
            "vmswap_bytes": status["VmSwap"] if verified else None,
            "smaps_rss_bytes": smaps["Rss"] if verified and smaps is not None else None,
            "smaps_swap_bytes": smaps["Swap"] if verified and smaps is not None else None,
            "raw_sha256": hashes,
        }
        return member, previous_end, (read["stat_before"]["start_ns"], read["stat_after"]["end_ns"])

    def cgroup(self, obs, frame_index, a, b, live):
        loc = "frame:%d/cgroup" % frame_index
        result = {"frame_index": frame_index, "cgroup_version": None, "cgroup_path": None,
                  "memory_events": None, "cgroup_procs_pids": None, "memory_current_bytes": None,
                  "memory_peak_bytes": None, "isolation": "NOT_EVALUATED",
                  "semantics": "CGROUP_DIAGNOSTICS_NEVER_ADDED_TO_PROCESS_RSS"}
        self.report["cgroup_observations"].append(result)
        if obs is None:
            self.reason("CGROUP_CORROBORATION_INCOMPLETE", loc)
            return
        _object(obs, ("clock_domain_id", "cgroup_version", "cgroup_path", "memory_events", "cgroup_procs",
                      "memory_current", "memory_peak"))
        _label(obs["clock_domain_id"])
        _need(type(obs["cgroup_version"]) is int and obs["cgroup_version"] in (1, 2))
        _label(obs["cgroup_path"])
        _need(obs["cgroup_path"].startswith("/"))
        result.update(cgroup_version=obs["cgroup_version"], cgroup_path=obs["cgroup_path"])
        if obs["clock_domain_id"] != self.data["clock"]["domain_id"]:
            self.reason("CLOCK_DOMAIN_MISMATCH", loc)
        if obs["cgroup_version"] != 2:
            self.reason("CGROUP_CORROBORATION_INCOMPLETE", loc)
        path_changed = self.cgroup_path is not None and self.cgroup_path != obs["cgroup_path"]
        if path_changed:
            self.reason("CGROUP_HIERARCHY_AMBIGUOUS", loc)
            result["isolation"] = "HIERARCHY_AMBIGUOUS"
        if self.cgroup_path is None:
            self.cgroup_path = obs["cgroup_path"]
        files = []
        for name in ("memory_events", "cgroup_procs", "memory_current", "memory_peak"):
            item = obs[name]
            if item is None and name in ("memory_current", "memory_peak"):
                continue
            try:
                _file(item)
            except _Violation as exc:
                self.reason(exc.code, loc + "/" + name)
                continue
            files.append((name, item))
        self.windows(files, a, b, loc)
        for name, item in files:
            fileloc = loc + "/" + name
            if item["result"] != "OK":
                if name in ("memory_events", "cgroup_procs"):
                    self.reason("CGROUP_CORROBORATION_INCOMPLETE", loc)
                else:
                    self.warning("CGROUP_DIAGNOSTIC_UNAVAILABLE", fileloc)
                continue
            text = item["text"]
            if name == "memory_events":
                counts = self.parse(f2a.parse_memory_events, text, fileloc)
                # Future counter names remain raw evidence, not trusted output keys.
                # All parsed counters still participate in monotonicity validation.
                result["memory_events"] = (None if counts is None else {
                    k: counts[k] for k in ("low", "high", "max", "oom", "oom_kill", "oom_group_kill") if k in counts
                })
                if counts is not None:
                    if any(counts.get(k, 0) > 0 for k in ("oom", "oom_kill", "oom_group_kill")):
                        self.reason("OOM_OR_SWAP_OBSERVED", loc)
                    if counts["max"] > 0:
                        self.reason("CGROUP_LIMIT_EVENT", loc)
                    if self.cgroup_counts is not None and any(k not in counts or counts[k] < v for k, v in self.cgroup_counts.items()):
                        self.reason("COUNTER_INCONSISTENT", loc)
                    self.cgroup_counts = counts
            else:
                try:
                    if name == "cgroup_procs":
                        pids = []
                        pid_set = set()
                        for line in text.splitlines():
                            _need(re.fullmatch(r"[0-9]+", line) is not None, "RAW_TEXT_MALFORMED")
                            pid = int(line)
                            _need(0 < pid < 2 ** 63 and pid not in pid_set, "RAW_TEXT_MALFORMED")
                            pids.append(pid)
                            pid_set.add(pid)
                        result["cgroup_procs_pids"] = sorted(pids)
                        if live is not None:
                            roster = {self.states[k]["pid"] for k in live}
                            extra, missing = set(pids) - roster, roster - set(pids)
                            if extra:
                                self.reason("CGROUP_NOT_ISOLATED", loc)
                            if missing:
                                self.reason("CGROUP_HIERARCHY_AMBIGUOUS", loc)
                            result["isolation"] = ("HIERARCHY_AMBIGUOUS" if missing or path_changed else
                                                   "NOT_ISOLATED" if extra else "PROCS_MATCH_ROSTER")
                    else:
                        _need(re.fullmatch(r"[0-9]+\n?", text) is not None, "RAW_TEXT_MALFORMED")
                        value = int(text)
                        _need(value < 2 ** 63, "RAW_TEXT_MALFORMED")
                        result[name + "_bytes"] = value
                except (_Violation, ValueError, OverflowError):
                    self.reason("RAW_TEXT_MALFORMED", fileloc)

    def frames(self):
        previous_sequence = None
        previous_end = None
        event_cursor = 0
        phase = {}
        for index, frame in enumerate(self.data["frames"]):
            loc = "frame:%d" % index
            output = {"index": index, "frame_sequence": None, "frame_kind": None,
                      "frame_start_ns": None, "frame_evaluation_ns": None, "frame_end_ns": None,
                      "live_roster": None, "read_skew_ns": None, "eligible": False,
                      "ineligibility_codes": [], "members": [], "sampled_aggregate_rss_bytes": None,
                      "aggregation_status": "NOT_AGGREGATED", "smaps_rss_diagnostic_bytes": None}
            self.report["frames"].append(output)
            start_reasons = set(self.reasons)
            try:
                _object(frame, ("frame_sequence", "clock_domain_id", "frame_kind", "frame_start_ns",
                                "frame_evaluation_ns", "frame_end_ns", "expected_live", "process_reads", "cgroup"))
                for name in ("frame_sequence", "frame_start_ns", "frame_evaluation_ns", "frame_end_ns"):
                    _integer(frame[name])
                _label(frame["clock_domain_id"])
                _label(frame["frame_kind"])
                _bounded_list(frame["expected_live"], MAX_IDENTITIES)
                _bounded_list(frame["process_reads"], MAX_READS_PER_FRAME)
                for name in ("frame_sequence", "frame_kind", "frame_start_ns", "frame_evaluation_ns", "frame_end_ns"):
                    output[name] = frame[name]
                _need(frame["clock_domain_id"] == self.data["clock"]["domain_id"], "CLOCK_DOMAIN_MISMATCH")
                sequence = frame["frame_sequence"]
                old_sequence = previous_sequence
                previous_sequence = sequence if old_sequence is None else max(sequence, old_sequence)
                _need(old_sequence is None or sequence > old_sequence, "SEQUENCE_ORDER_INVALID")
                if sequence != (0 if old_sequence is None else old_sequence + 1):
                    self.reason("SEQUENCE_GAP", loc)
                a, b = frame["frame_start_ns"], frame["frame_end_ns"]
                _need(a <= frame["frame_evaluation_ns"] <= b, "READ_WINDOW_INVALID")
                _need(previous_end is None or a > previous_end, "FRAME_CHRONOLOGY_INVALID")
                previous_end = b
                if frame["frame_kind"] != "BOUNDED_SEQUENTIAL_RSS_FRAME":
                    self.reason("FRAME_KIND_NOT_ACCEPTED", loc)
                while event_cursor < len(self.applied_events) and self.applied_events[event_cursor]["time_ns"] < a:
                    event = self.applied_events[event_cursor]
                    key = "%d:%d" % (event["identity"]["pid"], event["identity"]["starttime_ticks"])
                    if event["kind"] == "EXIT":
                        phase.pop(key, None)
                    else:
                        phase[key] = event["phase"]
                    event_cursor += 1
                window_cursor = event_cursor
                changed = False
                ambiguous = False
                while window_cursor < len(self.applied_events) and self.applied_events[window_cursor]["time_ns"] <= b:
                    kind = self.applied_events[window_cursor]["kind"]
                    changed |= kind in ("START", "EXIT")
                    ambiguous |= kind == "PHASE"
                    window_cursor += 1
                if changed:
                    self.reason("ROSTER_CHANGED_IN_FRAME", loc)
                if ambiguous:
                    self.reason("AMBIGUOUS_PHASE_FRAME", loc)
                possible = {k for k, s in self.states.items() if s["start_ns"] is not None and s["start_ns"] <= b
                            and (s["exit_ns"] is None or s["exit_ns"] >= a)}
                live = None if changed else {k for k, s in self.states.items() if s["start_ns"] is not None and s["start_ns"] < a
                                             and (s["exit_ns"] is None or s["exit_ns"] > b)}
                output["live_roster"] = sorted(live) if live is not None else None
                expected = set()
                for ident in frame["expected_live"]:
                    try:
                        key = self.reference(ident)
                        _need(key not in expected, "DUPLICATE_IDENTITY")
                        expected.add(key)
                        _need(key in possible, "ROSTER_CONTRADICTION")
                    except _Violation as exc:
                        self.reason(exc.code, loc)
                if live is not None and live - expected:
                    self.reason("ROSTER_INCOMPLETE", loc)
                seen = set()
                read_end = None
                windows = []
                for j, read in enumerate(frame["process_reads"]):
                    readloc = loc + "/read:%d" % j
                    try:
                        member, read_end, window = self.read(read, readloc, a, b, possible, phase, seen, read_end)
                        if member is not None:
                            output["members"].append(member)
                        if window is not None:
                            windows.append(window)
                    except _Violation as exc:
                        self.reason(exc.code, readloc)
                if live is not None and live - seen:
                    self.reason("PROCESS_READ_MISSING", loc)
                skew = max(w[1] for w in windows) - min(w[0] for w in windows) if windows else None
                output["read_skew_ns"] = skew
                if skew is not None and skew > self.data["configuration"]["max_read_skew_ns"]:
                    self.reason("READ_SKEW_EXCEEDED", loc)
                local = self.reasons - start_reasons
                invalid = any(REASON_CLASSES[c] == "INVALID" for c, _ in local)
                members = output["members"]
                eligible = (not changed and not ambiguous and bool(live) and live == expected == seen
                            and len(members) == len(live) and all(m["read_status"] == "VERIFIED" for m in members)
                            and not invalid and skew is not None and skew <= self.data["configuration"]["max_read_skew_ns"])
                if eligible:
                    output["eligible"] = True
                    output["sampled_aggregate_rss_bytes"] = sum(m["vmrss_bytes"] for m in members)
                    output["aggregation_status"] = "BOUNDED_SEQUENTIAL_RSS_SUM"
                    if all(m["smaps_rss_bytes"] is not None for m in members):
                        output["smaps_rss_diagnostic_bytes"] = sum(m["smaps_rss_bytes"] for m in members)
                    for member in members:
                        key = "%d:%d" % (member["identity"]["pid"], member["identity"]["starttime_ticks"])
                        state = self.states[key]
                        state["eligible_observation_count"] += 1
                        if member["phase"] not in state["observed_phases"]:
                            state["observed_phases"].append(member["phase"])
                        for target, source in (("max_observed_vmrss_bytes", "vmrss_bytes"), ("max_observed_vmhwm_bytes", "vmhwm_bytes")):
                            state[target] = max(state[target] or 0, member[source])
                else:
                    output["ineligibility_codes"] = sorted({c for c, _ in local})
                    if live == set():
                        output["ineligibility_codes"].append("EMPTY_ROSTER")
                        output["ineligibility_codes"].sort()
                # Cgroup failures affect the verdict, but never erase an eligible RSS diagnostic.
                try:
                    self.cgroup(frame["cgroup"], index, a, b, live)
                except _Violation as exc:
                    self.reason(exc.code, loc + "/cgroup")
            except _Violation as exc:
                self.reason(exc.code, loc)
                output["ineligibility_codes"] = sorted({c for c, _ in self.reasons - start_reasons})

    def run_coverage(self):
        frames = [f for f in self.report["frames"] if f["eligible"]]
        parent = next(s for s in self.states.values() if s["pool"] == "parent")
        if parent["start_ns"] is None or parent["exit_ns"] is None:
            self.reason("PARENT_LIFECYCLE_GAP", "run")
        for key, state in self.states.items():
            if state["pool"] != "parent" and (state["start_ns"] is None or state["exit_ns"] is None or not state["eligible_observation_count"]):
                self.reason("WORKER_LIFECYCLE_GAP", "process:" + key)
            for phase in set(state["entered_phases"]) - set(state["observed_phases"]):
                self.reason("PHASE_COVERAGE_GAP", "process:%s/phase:%s" % (key, phase))
        plan = self.data["configuration"]["phase_plan"]
        pools = {}
        for pool in POOLS:
            pools[pool] = {}
            for phase in PHASES:
                observed = any(s["pool"] == pool and phase in s["observed_phases"] for s in self.states.values())
                pools[pool][phase] = ("NOT_APPLICABLE_BY_DECLARED_WORKLOAD" if phase not in plan[pool] else
                                      "OBSERVED" if observed else "UNOBSERVED")
                if phase in plan[pool] and not observed:
                    self.reason("PHASE_COVERAGE_GAP", "pool:%s/phase:%s" % (pool, phase))
        self.report["phase_coverage"] = {"pools": pools}
        self.report["processes"] = self.states
        metric = self.report["sampled_rss"]
        metric.update(attempted_frame_count=len(self.data["frames"]), eligible_frame_count=len(frames),
                      configured_max_read_skew_ns=self.data["configuration"]["max_read_skew_ns"],
                      clock_kind=self.data["clock"]["kind"])
        if not frames:
            self.reason("NO_ELIGIBLE_FRAMES", "run")
            return
        winner = max(frames, key=lambda f: f["sampled_aggregate_rss_bytes"])
        metric.update(sampled_max_rss_bytes=winner["sampled_aggregate_rss_bytes"], sampled_max_frame_index=winner["index"],
                      max_eligible_read_skew_ns=max(f["read_skew_ns"] for f in frames))
        bound = self.data["configuration"]["max_frame_gap_ns"]
        if parent["start_ns"] is not None and frames[0]["frame_start_ns"] - parent["start_ns"] > bound:
            self.reason("SAMPLE_GAP", "run:initial")
        for previous, current in zip(frames, frames[1:]):
            if current["frame_start_ns"] - previous["frame_end_ns"] > bound:
                self.reason("SAMPLE_GAP", "frame:%d" % current["index"])
        if parent["exit_ns"] is not None and parent["exit_ns"] - frames[-1]["frame_end_ns"] > bound:
            self.reason("SAMPLE_GAP", "run:terminal")
        if any(len(f["members"]) >= 2 for f in frames):
            self.warning("SHARED_PAGES_MAY_BE_COUNTED_REPEATEDLY", "run")

    def finish(self):
        report = self.report
        report["reasons"] = [{"code": c, "class": REASON_CLASSES[c], "location": loc} for c, loc in sorted(self.reasons)]
        report["invalid_reason_codes"] = sorted({c for c, _ in self.reasons if REASON_CLASSES[c] == "INVALID"})
        report["incomplete_reason_codes"] = sorted({c for c, _ in self.reasons if REASON_CLASSES[c] == "INCOMPLETE"})
        report["warnings"] = [{"code": c, "location": loc} for c, loc in sorted(self.warnings)]
        report["outcome"] = (INVALID_CAPTURE if report["invalid_reason_codes"] else
                             INCOMPLETE_CAPTURE if report["incomplete_reason_codes"] else PROCESS_RSS_SAMPLE_COMPLETE)
        if report["outcome"] == PROCESS_RSS_SAMPLE_COMPLETE:
            report["sampled_rss"]["metric_status"] = "COMPLETE_SAMPLED_SERIES"
        report["integrity"] = {"algorithm": "sha256", "scope": "canonical result excluding integrity", "sha256": _digest(report)}
        return report


def assess_injected_capture(provider_input):
    """Validate only supplied JSON data, returning a detached, canonically sealed dict.

    INVALID takes precedence over INCOMPLETE; independent reasons are retained.
    No returned value qualifies production memory or establishes holder release.
    """
    try:
        copied = _copy_json(provider_input)
    except _Violation as exc:
        assessment = _Assessment(None, _empty_result(None, copied_ok=False))
        assessment.reason(exc.code, "root")
        return assessment.finish()
    except Exception:
        assessment = _Assessment(None, _empty_result(None, copied_ok=False))
        assessment.reason("INPUT_NOT_JSON", "root")
        return assessment.finish()
    try:
        assessment = _Assessment(copied, _empty_result(copied))
        if assessment.root():
            assessment.events()
            assessment.frames()
            assessment.run_coverage()
        return assessment.finish()
    except Exception:
        assessment = _Assessment(copied, _empty_result(copied))
        assessment.reason("INTERNAL_VALIDATION_FAILURE", "root")
        return assessment.finish()
