"""D2-B1 bounded byte-reader and provenance envelope; injected I/O only.

No native adapter exists in this gate. Callbacks are trusted to obey the read
limit and remain artificial/nonblocking. This module cannot preempt callbacks.
"""

import hashlib
import json
import re

SCHEMA = "rawibumi.real-procfs-reader.f2b4.d2b1.v1"
RESULT_SCHEMA = SCHEMA + ".result"
READER_VERSION = "f2b4.d2b1.v1"
SUCCESS = "INJECTED_READS_CONSISTENT_NONQUALIFYING"
MAX_PROCESSES = 64
MAX_FRAMES = 32
MAX_BYTES = 65536
MAX_TOTAL_BYTES = 4194304
MAX_READ_ATTEMPTS = 8288
MAX_DEPTH = 16
MAX_NODES = 20000
U64_MAX = 18446744073709551615
I64_MAX = 9223372036854775807
INVALID_CODES = (
    "INPUT_NOT_JSON", "INPUT_CAP_EXCEEDED", "SCHEMA_INVALID", "UNKNOWN_FIELD",
    "SCHEMA_VERSION_MISMATCH", "SOURCE_KIND_NOT_ACCEPTED", "REAL_SOURCE_NOT_AUTHORIZED",
    "CONFIGURATION_INVALID", "IDENTITY_INVALID", "DUPLICATE_IDENTITY", "BOOT_ID_MISMATCH",
    "PID_NAMESPACE_MISMATCH", "CGROUP_CONFIGURATION_INVALID", "READER_CONTRACT_VIOLATION",
    "RAW_TEXT_MALFORMED", "INVALID_UTF8", "DUPLICATE_FIELD", "MISSING_FIELD",
    "STATUS_STAT_CONTRADICTION", "CLOCK_FAILURE", "CLOCK_NON_MONOTONIC",
    "COUNTER_INCONSISTENT", "BASELINE_CHRONOLOGY_INVALID",
)


class _Violation(Exception):
    def __init__(self, code):
        self.code = code


def _need(condition, code="SCHEMA_INVALID"):
    if not condition:
        raise _Violation(code)


def canonical_json(value):
    """Pure canonical representation, including the final newline."""
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _copy(value):
    budget = [0, 0]
    ancestors = set()

    def visit(item, depth):
        _need(depth <= MAX_DEPTH, "INPUT_CAP_EXCEEDED")
        budget[0] += 1
        _need(budget[0] <= MAX_NODES, "INPUT_CAP_EXCEEDED")
        kind = type(item)
        if kind in (dict, list):
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
            _need(len(item) <= MAX_BYTES, "INPUT_CAP_EXCEEDED")
            try:
                size = len(item.encode("utf-8"))
            except UnicodeError:
                raise _Violation("INPUT_NOT_JSON") from None
            budget[1] += size
            _need(size <= MAX_BYTES and budget[1] <= MAX_TOTAL_BYTES, "INPUT_CAP_EXCEEDED")
        elif kind is int:
            _need(-I64_MAX - 1 <= item <= U64_MAX, "INPUT_CAP_EXCEEDED")
        elif kind not in (bool, type(None)):
            raise _Violation("INPUT_NOT_JSON")
        return item

    return visit(value, 0)


def _object(value, fields):
    _need(type(value) is dict)
    _need(not (value.keys() - set(fields)), "UNKNOWN_FIELD")
    _need(value.keys() == set(fields))


def _integer(value, minimum=0, maximum=I64_MAX, code="SCHEMA_INVALID"):
    _need(type(value) is int and minimum <= value <= maximum, code)


def _label(value, code="CONFIGURATION_INVALID"):
    _need(type(value) is str and len(value) <= 96 and ".." not in value and
          re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is not None, code)


def _number(raw, signed=False):
    digits = raw[1:] if signed and raw.startswith("-") else raw
    _need(0 < len(digits) <= 20 and re.fullmatch(r"[0-9]+", digits) is not None,
          "RAW_TEXT_MALFORMED")
    number = int(raw)
    _need(-I64_MAX - 1 <= number <= I64_MAX if signed else 0 <= number <= U64_MAX,
          "RAW_TEXT_MALFORMED")
    return number


def _memory(raw):
    parts = raw.split()
    _need(len(parts) == 2 and parts[1] == "kB", "RAW_TEXT_MALFORMED")
    value = _number(parts[0])
    _need(value <= U64_MAX // 1024, "RAW_TEXT_MALFORMED")
    return value * 1024


def _text(raw):
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise _Violation("INVALID_UTF8") from None
    _need(text.endswith("\n"), "TRUNCATED")
    _need(re.search(r"\s{65}", text) is None and re.search(r"[0-9]{21}", text) is None,
          "RAW_TEXT_MALFORMED")
    _need(not any((ord(c) < 32 and c not in ("\n", "\t")) or
                  127 <= ord(c) <= 159 or c in ("\u2028", "\u2029") for c in text),
          "RAW_TEXT_MALFORMED")
    return text


def _stat(text):
    _need(text.count("\n") == 1, "RAW_TEXT_MALFORMED")
    opening, closing = text.find("("), text.rfind(")")
    _need(opening > 0 and closing > opening and text[closing + 1:closing + 2] == " ",
          "RAW_TEXT_MALFORMED")
    pid = _number(text[:opening].strip())
    _need(1 <= pid <= 2147483647, "RAW_TEXT_MALFORMED")
    tail = text[closing + 1:].split()
    _need(len(tail) >= 20, "MISSING_FIELD")
    _need(len(tail) <= 50 and re.fullmatch(r"[RSDZTtXxKWIPN]", tail[0]) is not None,
          "RAW_TEXT_MALFORMED")
    signed = (4, 5, 6, 7, 8, 16, 17, 18, 19, 20, 21, 24, 38, 39, 44, 52)
    for field, raw in enumerate(tail[1:], 4):
        _number(raw, field in signed)
    ppid = _number(tail[1])
    _need(ppid <= 2147483647, "RAW_TEXT_MALFORMED")
    return {"pid": pid, "ppid": ppid, "starttime_ticks": _number(tail[19]), "state": tail[0]}


def _fields(text, rollup=False):
    fields = {}
    header = False
    for line in text.splitlines():
        _need(bool(line.strip()), "RAW_TEXT_MALFORMED")
        if rollup and re.fullmatch(r"[0-9a-fA-F]+-[0-9a-fA-F]+\s+\S+\s+[0-9a-fA-F]+\s+\S+\s+[0-9]+\s+\[rollup\]", line):
            _need(not header and not fields, "DUPLICATE_FIELD")
            header = True
            continue
        name, colon, raw = line.partition(":")
        _need(colon == ":" and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) is not None,
              "RAW_TEXT_MALFORMED")
        _need(name not in fields, "DUPLICATE_FIELD")
        fields[name] = raw.strip()
    return fields


def _status(text):
    fields = _fields(text)
    _need({"Pid", "PPid", "State"} <= fields.keys(), "MISSING_FIELD")
    _need(re.fullmatch(r"[RSDZTtXxKWIPN](?:\s+\([^()]*\))?", fields["State"]) is not None,
          "RAW_TEXT_MALFORMED")
    result = {"pid": _number(fields["Pid"]), "ppid": _number(fields["PPid"]),
              "state": fields["State"][0], "vmrss_bytes": None, "vmhwm_bytes": None}
    _need(1 <= result["pid"] <= 2147483647 and result["ppid"] <= 2147483647,
          "RAW_TEXT_MALFORMED")
    for name, raw in fields.items():
        if name.startswith("Vm") or name in ("RssAnon", "RssFile", "RssShmem", "HugetlbPages"):
            _memory(raw)
    if result["state"] in ("Z", "X", "x"):
        return result
    # exit_mm can precede zombie state; a live state without Vm* is uncertainty.
    _need({"VmRSS", "VmHWM"} <= fields.keys(), "PROCESS_MEMORY_UNAVAILABLE")
    result.update(vmrss_bytes=_memory(fields["VmRSS"]), vmhwm_bytes=_memory(fields["VmHWM"]))
    _need(result["vmhwm_bytes"] >= result["vmrss_bytes"], "COUNTER_INCONSISTENT")
    return result


def _smaps(text):
    fields = _fields(text, rollup=True)
    _need({"Rss", "Swap"} <= fields.keys(), "MISSING_FIELD")
    return {name: _memory(raw) for name, raw in fields.items()}


def _events(text):
    result = {}
    for line in text.splitlines():
        parts = line.split()
        _need(len(parts) == 2 and re.fullmatch(r"[a-z_]{1,64}", parts[0]) is not None,
              "RAW_TEXT_MALFORMED")
        name, raw = parts
        _need(name not in result, "DUPLICATE_FIELD")
        result[name] = _number(raw)
    _need({"low", "high", "max", "oom", "oom_kill"} <= result.keys(), "MISSING_FIELD")
    return result


def _exception_class(exc):
    # Fixed built-in names preserve useful classes without accepting arbitrary
    # user-defined class names as a channel for unrelated host information.
    for cls in (PermissionError, FileNotFoundError, ProcessLookupError, OSError,
                ValueError, TypeError, RuntimeError, TimeoutError, BlockingIOError,
                InterruptedError):
        if type(exc) is cls:
            return cls.__name__
    return ("PermissionError" if isinstance(exc, PermissionError) else
            "FileNotFoundError" if isinstance(exc, FileNotFoundError) else
            "ProcessLookupError" if isinstance(exc, ProcessLookupError) else
            "OSError" if isinstance(exc, OSError) else "Exception")


def _identity(identity, config):
    _object(identity, ("pid", "ppid", "starttime_ticks", "boot_id", "pid_namespace_id", "role"))
    _integer(identity["pid"], 1, 2147483647, "IDENTITY_INVALID")
    _integer(identity["ppid"], 0, 2147483647, "IDENTITY_INVALID")
    _integer(identity["starttime_ticks"], 0, U64_MAX, "IDENTITY_INVALID")
    _need(identity["boot_id"] == config["boot_id"], "BOOT_ID_MISMATCH")
    _need(identity["pid_namespace_id"] == config["pid_namespace_id"], "PID_NAMESPACE_MISMATCH")
    _label(identity["role"], "IDENTITY_INVALID")


def _validate(data):
    _object(data, ("schema", "source_kind", "run_id", "reader_source_sha256", "config",
                   "roster", "frame_rosters", "cgroup"))
    _need(data["schema"] == SCHEMA, "SCHEMA_VERSION_MISMATCH")
    _need(data["source_kind"] not in ("REAL_PROCFS", "NATIVE"), "REAL_SOURCE_NOT_AUTHORIZED")
    _need(data["source_kind"] == "TEST_INJECTED", "SOURCE_KIND_NOT_ACCEPTED")
    _label(data["run_id"])
    source_hash = data["reader_source_sha256"]
    _need(source_hash is None or (type(source_hash) is str and
          re.fullmatch(r"[0-9a-f]{64}", source_hash) is not None), "CONFIGURATION_INVALID")
    c = data["config"]
    _object(c, ("clock_ticks_per_second", "boot_id", "pid_namespace_id", "max_read_skew_ns",
                "max_bytes", "max_total_bytes", "max_read_attempts", "smaps_rollup_policy"))
    _integer(c["clock_ticks_per_second"], 1, 1000000, "CONFIGURATION_INVALID")
    _integer(c["max_read_skew_ns"], code="CONFIGURATION_INVALID")
    _integer(c["max_bytes"], 1, MAX_BYTES, "CONFIGURATION_INVALID")
    _integer(c["max_total_bytes"], 1, MAX_TOTAL_BYTES, "CONFIGURATION_INVALID")
    _integer(c["max_read_attempts"], 1, MAX_READ_ATTEMPTS, "CONFIGURATION_INVALID")
    _need(type(c["boot_id"]) is str and re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", c["boot_id"]) is not None,
        "CONFIGURATION_INVALID")
    _label(c["pid_namespace_id"])
    _need(c["smaps_rollup_policy"] in ("NOT_SAMPLED", "OPTIONAL_DIAGNOSTIC"), "CONFIGURATION_INVALID")
    roster = data["roster"]
    _object(roster, ("parent", "workers", "complete"))
    _need(type(roster["complete"]) is bool)
    _need(type(roster["workers"]) is list and len(roster["workers"]) < MAX_PROCESSES,
          "INPUT_CAP_EXCEEDED")
    identities = [roster["parent"]] + roster["workers"]
    seen = set()
    for identity in identities:
        _identity(identity, c)
        _need(identity["pid"] not in seen, "DUPLICATE_IDENTITY")
        seen.add(identity["pid"])
    _need(roster["parent"]["role"] == "parent", "IDENTITY_INVALID")
    _need(roster["parent"]["ppid"] not in seen, "IDENTITY_INVALID")
    for worker in roster["workers"]:
        _need(worker["ppid"] == roster["parent"]["pid"] and worker["role"] != "parent", "IDENTITY_INVALID")
    _need(type(data["frame_rosters"]) is list and 1 <= len(data["frame_rosters"]) <= MAX_FRAMES,
          "INPUT_CAP_EXCEEDED")
    for pids in data["frame_rosters"]:
        _need(type(pids) is list and len(pids) <= MAX_PROCESSES, "INPUT_CAP_EXCEEDED")
        for pid in pids:
            _integer(pid, 1, 2147483647, "IDENTITY_INVALID")
        _need(len(set(pids)) == len(pids), "DUPLICATE_IDENTITY")
    _validate_cgroup(data, seen)


def _validate_cgroup(data, seen):
    cg, c = data["cgroup"], data["config"]
    if cg is None:
        return
    _object(cg, ("enabled", "token", "controller_id", "membership", "membership_provenance",
                 "boot_id", "pid_namespace_id", "baseline"))
    _need(cg["enabled"] is True, "CGROUP_CONFIGURATION_INVALID")
    _label(cg["token"], "CGROUP_CONFIGURATION_INVALID")
    _label(cg["controller_id"], "CGROUP_CONFIGURATION_INVALID")
    _label(cg["membership_provenance"], "CGROUP_CONFIGURATION_INVALID")
    _need(cg["boot_id"] == c["boot_id"], "BOOT_ID_MISMATCH")
    _need(cg["pid_namespace_id"] == c["pid_namespace_id"], "PID_NAMESPACE_MISMATCH")
    _need(type(cg["membership"]) is list and len(cg["membership"]) <= MAX_PROCESSES,
          "CGROUP_CONFIGURATION_INVALID")
    for pid in cg["membership"]:
        _integer(pid, 1, 2147483647, "CGROUP_CONFIGURATION_INVALID")
    _need(len(set(cg["membership"])) == len(cg["membership"]) and set(cg["membership"]) == seen,
          "CGROUP_CONFIGURATION_INVALID")
    baseline = cg["baseline"]
    _object(baseline, ("memory_current_bytes", "memory_peak_bytes", "events", "observed_ns", "provenance"))
    for name in ("memory_current_bytes", "memory_peak_bytes"):
        _integer(baseline[name], 0, U64_MAX, "CGROUP_CONFIGURATION_INVALID")
    _integer(baseline["observed_ns"], code="CGROUP_CONFIGURATION_INVALID")
    _label(baseline["provenance"], "CGROUP_CONFIGURATION_INVALID")
    _need(type(baseline["events"]) is dict and
          {"low", "high", "max", "oom", "oom_kill"} <= baseline["events"].keys(), "CGROUP_CONFIGURATION_INVALID")
    for name, value in baseline["events"].items():
        _need(re.fullmatch(r"[a-z_]{1,64}", name) is not None, "CGROUP_CONFIGURATION_INVALID")
        _integer(value, 0, U64_MAX, "CGROUP_CONFIGURATION_INVALID")
    # Neither baseline nor reads assert atomic current/peak correspondence.


def _envelope():
    return {"schema": RESULT_SCHEMA, "reader_version": READER_VERSION,
            "source_kind": "TEST_INJECTED", "origin_attestation": "UNVERIFIED",
            "production_memory_qualification": "INCONCLUSIVE", "production_chronological_peak": "NOT_OBSERVED",
            "production_workload_measured": False, "holder_release": "NOT_ESTABLISHED",
            "simultaneous_holder_occupancy": "NOT_ESTABLISHED", "atomic_snapshot": False,
            "bound_claim": "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK", "clock_kind": "INJECTED_MONOTONIC_NS",
            "starttime_alignment": "NOT_CALIBRATED", "worker_absence_proven": False,
            "worker_coverage": "NOT_ESTABLISHED", "unregistered_worker_coverage": "NOT_ESTABLISHED",
            "provenance_verification": "CALLER_ASSERTED_ONLY", "run_id": None, "input_sha256": None,
            "reader_source_sha256": None, "reader_source_hash_provenance": "NOT_RECORDED",
            "config": None, "roster": None, "frames_requested": None, "frames": [], "reasons": [],
            "first_read_start_ns": None, "last_read_end_ns": None, "read_skew_ns": None,
            "read_attempts": 0, "total_bytes": 0, "outcome": "INVALID",
            "invalid_reason_codes": [], "incomplete_reason_codes": []}


def _finish(report, reasons):
    ordered = sorted(set(reasons))
    report["reasons"] = [{"code": c, "location": loc} for c, loc in ordered]
    report["invalid_reason_codes"] = sorted({c for c, _ in ordered if c in INVALID_CODES})
    report["incomplete_reason_codes"] = sorted({c for c, _ in ordered if c not in INVALID_CODES})
    report["outcome"] = "INVALID" if report["invalid_reason_codes"] else "INCOMPLETE" if ordered else SUCCESS
    report["integrity"] = {"algorithm": "sha256", "scope": "canonical result excluding integrity",
                           "sha256": _digest(report)}
    return json.loads(canonical_json(report))


class _Capture:
    def __init__(self, data, read_proc, clock, read_cgroup):
        self.data, self.read_proc, self.clock, self.read_cgroup = data, read_proc, clock, read_cgroup
        self.reasons = []
        self.last_tick = None
        self.total_bytes = 0
        self.attempts = 0
        self.stopped = False
        self.previous = data["cgroup"]["baseline"] if data["cgroup"] else None

    def tick(self):
        try:
            value = self.clock()
        except Exception:
            raise _Violation("CLOCK_FAILURE") from None
        _integer(value, code="CLOCK_FAILURE")
        _need(self.last_tick is None or value >= self.last_tick, "CLOCK_NON_MONOTONIC")
        self.last_tick = value
        return value

    def read(self, kind, target, location, parser, cgroup=False, skip=None):
        record = {"kind": kind, "target": target, "status": "NOT_READ", "reason_codes": [],
                  "start_ns": None, "end_ns": None, "sha256": None, "byte_length": None,
                  "exception_class": None, "attempt": None}
        value = None
        try:
            _need(skip is None, skip)
            _need(not self.stopped, "CAPTURE_STOPPED")
            _need(self.attempts < self.data["config"]["max_read_attempts"], "READ_ATTEMPT_CAP_EXCEEDED")
            remaining = self.data["config"]["max_total_bytes"] - self.total_bytes
            _need(remaining > 0, "TOTAL_BYTES_CAP_EXCEEDED")
            callback = self.read_cgroup if cgroup else self.read_proc
            _need(callable(callback), "CGROUP_READER_NOT_CONFIGURED" if cgroup else "READER_NOT_CONFIGURED")
            record["start_ns"] = self.tick()
            self.attempts += 1
            record["attempt"] = self.attempts
            # Reducing the cap near the total budget bounds bytes even on failure.
            cap = min(self.data["config"]["max_bytes"], remaining)
            error, raw = None, None
            try:
                raw = callback(target, kind, cap + 1) if cgroup else callback("/proc/%d/%s" % (target, kind), cap + 1)
            except Exception as exc:
                record["exception_class"] = _exception_class(exc)
                error = ("PERMISSION_DENIED" if isinstance(exc, PermissionError) else
                         "CGROUP_UNAVAILABLE" if cgroup and isinstance(exc, (FileNotFoundError, ProcessLookupError)) else
                         "PROCESS_VANISHED" if isinstance(exc, (FileNotFoundError, ProcessLookupError)) else
                         "READ_FAILED" if isinstance(exc, OSError) else "READER_EXCEPTION")
            # Preserve bounded returned-byte provenance even if the end clock fails.
            byte_error = None
            if type(raw) is bytes:
                record["byte_length"] = len(raw)
                self.total_bytes += len(raw)
                if len(raw) <= cap + 1:
                    record["sha256"] = hashlib.sha256(raw).hexdigest()
                else:
                    byte_error = "READER_CONTRACT_VIOLATION"
                if byte_error is None and len(raw) > cap:
                    byte_error = ("OVERSIZED" if cap == self.data["config"]["max_bytes"]
                                  else "TOTAL_BYTES_CAP_EXCEEDED")
            elif error is None:
                byte_error = "READER_CONTRACT_VIOLATION"
            if byte_error:
                record["reason_codes"].append(byte_error)
            try:
                record["end_ns"] = self.tick()
            except _Violation:
                if error:
                    record["reason_codes"].append(error)
                raise
            if error:
                raise _Violation(error)
            _need(byte_error is None, byte_error)
            value = parser(_text(raw))
            record["status"] = "OK"
        except _Violation as exc:
            record["status"] = "NOT_READ" if record["start_ns"] is None else "FAILED"
            record["reason_codes"].append(exc.code)
            if exc.code in ("CLOCK_FAILURE", "CLOCK_NON_MONOTONIC", "READ_ATTEMPT_CAP_EXCEEDED",
                            "TOTAL_BYTES_CAP_EXCEEDED", "READER_CONTRACT_VIOLATION"):
                self.stopped = True
        record["reason_codes"] = sorted(set(record["reason_codes"]))
        self.reasons.extend((c, location) for c in record["reason_codes"])
        return record, value

    def process(self, identity, location, present):
        record = {"identity": identity, "status": "INCOMPLETE", "reads": [], "reason_codes": [],
                  "vmrss_bytes": None, "vmhwm_bytes": None, "smaps_rollup": None}
        values = {}
        sequence = [("stat_before", "stat", _stat), ("status", "status", _status)]
        if self.data["config"]["smaps_rollup_policy"] == "OPTIONAL_DIAGNOSTIC":
            sequence.append(("smaps_rollup", "smaps_rollup", _smaps))
        sequence.append(("stat_after", "stat", _stat))
        before_valid = False
        for label, kind, parser in sequence:
            skip = "REGISTERED_PROCESS_MISSING" if not present else (
                "PRIOR_IDENTITY_UNVERIFIED" if label in ("status", "smaps_rollup") and not before_valid else None)
            read, value = self.read(kind, identity["pid"], location + "." + label, parser, skip=skip)
            read["label"] = label
            record["reads"].append(read)
            values[label] = value
            record["reason_codes"].extend(read["reason_codes"])
            if value is not None and kind in ("stat", "status"):
                if value["pid"] != identity["pid"]:
                    record["reason_codes"].append("STATUS_STAT_CONTRADICTION" if kind == "status" else "PID_REUSE_OR_IDENTITY_RACE")
                if value["ppid"] != identity["ppid"]:
                    record["reason_codes"].append("STATUS_STAT_CONTRADICTION" if kind == "status" and
                        values.get("stat_before", {}).get("ppid") != value["ppid"] else "PROCESS_REPARENTED")
                if kind == "stat" and value["starttime_ticks"] != identity["starttime_ticks"]:
                    record["reason_codes"].append("PID_REUSE_OR_IDENTITY_RACE")
                if value["state"] in ("Z", "X", "x"):
                    record["reason_codes"].append("PROCESS_NOT_LIVE")
            if label == "stat_before":
                before_valid = not record["reason_codes"]
        record["reason_codes"] = sorted(set(record["reason_codes"]))
        self.reasons.extend((c, location) for c in record["reason_codes"])
        if not record["reason_codes"]:
            record.update(status=SUCCESS, vmrss_bytes=values["status"]["vmrss_bytes"],
                          vmhwm_bytes=values["status"]["vmhwm_bytes"], smaps_rollup=values.get("smaps_rollup"))
        return record

    def cgroup(self, location):
        cg = self.data["cgroup"]
        if cg is None:
            return None
        section = {"identity": {k: v for k, v in cg.items() if k not in ("baseline", "enabled")},
                   "membership_verification": "CALLER_ASSERTED_ONLY", "baseline": cg["baseline"],
                   "status": "INCOMPLETE", "reads": [], "reason_codes": [],
                   "memory_current_bytes": None, "memory_peak_bytes": None, "events": None}
        values = []
        for kind, parser in (("memory.current", lambda t: _number(t.strip())),
                             ("memory.peak", lambda t: _number(t.strip())), ("memory.events", _events)):
            read, value = self.read(kind, cg["token"], location + "." + kind, parser, cgroup=True)
            section["reads"].append(read)
            section["reason_codes"].extend(read["reason_codes"])
            values.append(value)
        current, peak, events = values
        starts = [r["start_ns"] for r in section["reads"] if r["start_ns"] is not None]
        if starts and cg["baseline"]["observed_ns"] > starts[0]:
            section["reason_codes"].append("BASELINE_CHRONOLOGY_INVALID")
        if peak is not None and peak < self.previous["memory_peak_bytes"]:
            section["reason_codes"].append("COUNTER_INCONSISTENT")
        if events is not None and any(name not in events or events[name] < count
                                      for name, count in self.previous["events"].items()):
            section["reason_codes"].append("COUNTER_INCONSISTENT")
        if not section["reason_codes"]:
            section.update(status=SUCCESS, memory_current_bytes=current, memory_peak_bytes=peak, events=events)
            self.previous = {"memory_peak_bytes": peak, "events": events}
        section["reason_codes"] = sorted(set(section["reason_codes"]))
        self.reasons.extend((c, location) for c in section["reason_codes"])
        return section

    def frames(self):
        frames = []
        roster = self.data["roster"]
        identities = [roster["parent"]] + roster["workers"]
        expected = {p["pid"] for p in identities}
        for index, observed in enumerate(self.data["frame_rosters"]):
            start_reasons = len(self.reasons)
            location = "frames.%d" % index
            present = set(observed)
            if not roster["complete"]:
                self.reasons.append(("ROSTER_INCOMPLETE", location))
            if present - expected:
                self.reasons.append(("UNKNOWN_PROCESS", location))
            if expected - present:
                self.reasons.append(("REGISTERED_PROCESS_MISSING", location))
            processes = [self.process(p, location + ".processes.%d" % n, p["pid"] in present)
                         for n, p in enumerate(identities)]
            cg = self.cgroup(location + ".cgroup")
            reads = [r for p in processes for r in p["reads"]] + (cg["reads"] if cg else [])
            starts = [r["start_ns"] for r in reads if r["start_ns"] is not None]
            ends = [r["end_ns"] for r in reads if r["end_ns"] is not None]
            first, last = (starts[0] if starts else None), (ends[-1] if ends else None)
            skew = last - first if first is not None and last is not None else None
            if skew is not None and skew > self.data["config"]["max_read_skew_ns"]:
                self.reasons.append(("READ_SKEW_EXCEEDED", location))
            codes = sorted({c for c, _ in self.reasons[start_reasons:]})
            status = "INVALID" if any(c in INVALID_CODES for c in codes) else "INCOMPLETE" if codes else SUCCESS
            if codes:
                for p in processes:
                    p.update(status=status, vmrss_bytes=None, vmhwm_bytes=None, smaps_rollup=None)
                if cg:
                    cg.update(status=status, memory_current_bytes=None, memory_peak_bytes=None, events=None)
            frames.append({"index": index, "status": status, "reason_codes": codes, "processes": processes,
                           "cgroup": cg, "roster_provenance": "CALLER_ASSERTED_ONLY", "observed_pids": observed,
                           "first_read_start_ns": first, "last_read_end_ns": last, "read_skew_ns": skew,
                           "read_window_complete": all(r["start_ns"] is not None and r["end_ns"] is not None for r in reads)})
            if self.stopped:
                break
        if len(frames) != len(self.data["frame_rosters"]):
            self.reasons.append(("CAPTURE_STOPPED", "frames"))
        return frames


class RealProcfsReader:
    """Inert constructor. sample() is the only callback entry point.

    read_proc(path, limit) -> exact bytes; paths are built internally from the
    registered PID and the whitelist. read_cgroup(token, kind, limit) -> bytes
    is separate and gated by request.cgroup.enabled. No fallback I/O exists.
    """

    def __init__(self, read_proc=None, monotonic_ns=None, read_cgroup=None):
        self._read_proc = read_proc
        self._clock = monotonic_ns
        self._read_cgroup = read_cgroup

    def sample(self, request):
        report = _envelope()
        try:
            data = _copy(request)
            _validate(data)
            report.update(input_sha256=_digest(data), run_id=data["run_id"], config=data["config"],
                          roster=data["roster"], frames_requested=len(data["frame_rosters"]),
                          reader_source_sha256=data["reader_source_sha256"],
                          reader_source_hash_provenance="CALLER_ASSERTED_ONLY" if data["reader_source_sha256"] else "NOT_RECORDED")
            _need(callable(self._read_proc), "READER_NOT_CONFIGURED")
            _need(callable(self._clock), "CLOCK_NOT_CONFIGURED")
        except _Violation as exc:
            return _finish(report, [(exc.code, "request")])
        capture = _Capture(data, self._read_proc, self._clock, self._read_cgroup)
        report["frames"] = capture.frames()
        reads = [r for f in report["frames"] for p in f["processes"] for r in p["reads"]]
        reads += [r for f in report["frames"] if f["cgroup"] for r in f["cgroup"]["reads"]]
        starts = [r["start_ns"] for r in reads if r["start_ns"] is not None]
        ends = [r["end_ns"] for r in reads if r["end_ns"] is not None]
        report["first_read_start_ns"] = min(starts) if starts else None
        report["last_read_end_ns"] = max(ends) if ends else None
        if starts and ends:
            report["read_skew_ns"] = max(ends) - min(starts)
        report.update(read_attempts=capture.attempts, total_bytes=capture.total_bytes,
                      worker_coverage="REGISTERED_ROSTER_OBSERVED" if not capture.reasons else "UNCERTAIN")
        return _finish(report, capture.reasons)
