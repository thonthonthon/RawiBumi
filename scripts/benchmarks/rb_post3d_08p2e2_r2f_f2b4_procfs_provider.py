"""D2-A: bounded, fake-only procfs provider. No operating-system backend."""

import hashlib
import json
import re

SCHEMA = "rawibumi.real-procfs-provider.f2b4.d2a.v1"
RESULT_SCHEMA = SCHEMA + ".result"
SUCCESS = "FAKE_PROVIDER_SAMPLE_CONSISTENT"
MAX_PROCESSES = 64
MAX_FRAMES = 32
MAX_TEXT_BYTES = 65536
MAX_TOTAL_TEXT_BYTES = 4194304
MAX_DEPTH = 16
MAX_NODES = 20000
MAX_WHITESPACE_RUN = 64
INTEGER_LIMIT = 9223372036854775808
INVALID_CODES = (
    "INPUT_NOT_JSON", "INPUT_CAP_EXCEEDED", "SCHEMA_INVALID", "UNKNOWN_FIELD",
    "SCHEMA_VERSION_MISMATCH", "SOURCE_KIND_NOT_ACCEPTED", "REAL_SOURCE_NOT_AUTHORIZED",
    "CONFIGURATION_INVALID", "IDENTITY_INVALID", "DUPLICATE_IDENTITY", "BOOT_ID_MISMATCH",
    "CGROUP_CONFIGURATION_INVALID", "READER_CONTRACT_VIOLATION", "RAW_TEXT_MALFORMED",
    "DUPLICATE_FIELD", "MISSING_FIELD", "IDENTITY_CONTRADICTION", "PID_REUSE_OR_IDENTITY_RACE",
    "CLOCK_FAILURE", "CLOCK_NON_MONOTONIC", "COUNTER_INCONSISTENT", "BASELINE_CHRONOLOGY_INVALID",
)


class _Violation(Exception):
    def __init__(self, code):
        self.code = code


def _need(condition, code="SCHEMA_INVALID"):
    if not condition:
        raise _Violation(code)


def canonical_json(value):
    """Canonical serialization used by the integrity seal; no I/O."""
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
                copied = {}
                for key, child in item.items():
                    _need(type(key) is str, "INPUT_NOT_JSON")
                    copied[visit(key, depth + 1)] = visit(child, depth + 1)
            else:
                copied = [visit(child, depth + 1) for child in item]
            ancestors.remove(id(item))
            return copied
        if kind is str:
            _need(len(item) <= MAX_TEXT_BYTES, "INPUT_CAP_EXCEEDED")
            try:
                size = len(item.encode("utf-8"))
            except UnicodeError:
                raise _Violation("INPUT_NOT_JSON") from None
            budget[1] += size
            _need(size <= MAX_TEXT_BYTES and budget[1] <= MAX_TOTAL_TEXT_BYTES, "INPUT_CAP_EXCEEDED")
        elif kind is int:
            _need(-INTEGER_LIMIT < item < INTEGER_LIMIT, "INPUT_CAP_EXCEEDED")
        elif kind not in (bool, type(None)):
            # Floats, including NaN/Inf, have no place in this integer-only contract.
            raise _Violation("INPUT_NOT_JSON")
        return item

    return visit(value, 0)


def _object(value, fields):
    _need(type(value) is dict)
    _need(not (value.keys() - set(fields)), "UNKNOWN_FIELD")
    _need(set(fields) == value.keys())


def _integer(value, minimum=0, maximum=INTEGER_LIMIT - 1, code="SCHEMA_INVALID"):
    _need(type(value) is int and minimum <= value <= maximum, code)


def _label(value, code="CONFIGURATION_INVALID"):
    _need(type(value) is str and len(value) <= 96 and ".." not in value
          and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is not None, code)


def _uint(raw):
    _need(0 < len(raw) <= 19 and re.fullmatch(r"[0-9]+", raw) is not None, "RAW_TEXT_MALFORMED")
    number = int(raw)
    _need(number < INTEGER_LIMIT, "RAW_TEXT_MALFORMED")
    return number


def _stat_number(raw, signed):
    # Unselected kernel fields include u64 rsslim and signed scheduling values.
    # Identity fields are checked again using the narrower _uint contract.
    digits = raw[1:] if signed and raw.startswith("-") else raw
    _need(0 < len(digits) <= 20 and re.fullmatch(r"[0-9]+", digits) is not None,
          "RAW_TEXT_MALFORMED")
    number = int(raw)
    _need(-INTEGER_LIMIT <= number < INTEGER_LIMIT if signed
          else 0 <= number < 2 * INTEGER_LIMIT, "RAW_TEXT_MALFORMED")


def _memory(raw):
    parts = raw.split()
    _need(len(parts) == 2 and parts[1] == "kB", "RAW_TEXT_MALFORMED")
    number = _uint(parts[0])
    _need(number <= (INTEGER_LIMIT - 1) // 1024, "RAW_TEXT_MALFORMED")
    return number * 1024


def _text_guard(text):
    _need(re.search(r"\s{%d}" % (MAX_WHITESPACE_RUN + 1), text) is None, "RAW_TEXT_MALFORMED")
    _need(re.search(r"[0-9]{21}", text) is None, "RAW_TEXT_MALFORMED")
    _need(not any((ord(c) < 32 and c not in ("\n", "\t")) or
                  c in ("\x7f", "\x85", "\u2028", "\u2029") for c in text),
          "RAW_TEXT_MALFORMED")


def _stat(text):
    opening, closing = text.find("("), text.rfind(")")
    _need(opening > 0 and closing > opening, "RAW_TEXT_MALFORMED")
    pid = _uint(text[:opening].strip())
    _need(pid > 0 and text[closing + 1:closing + 2].isspace(), "RAW_TEXT_MALFORMED")
    tail = text[closing + 1:].split()
    _need(len(tail) >= 20, "MISSING_FIELD")
    _need(len(tail) <= 256 and re.fullmatch(r"[RSDZTtXxKWIPN]", tail[0]) is not None,
          "RAW_TEXT_MALFORMED")
    signed = (4, 5, 6, 7, 8, 16, 17, 18, 19, 20, 21, 24, 38, 39, 44, 52)
    for number, raw in enumerate(tail[1:], 4):
        _stat_number(raw, number in signed)
    return {"pid": pid, "ppid": _uint(tail[1]), "starttime_ticks": _uint(tail[19]), "state": tail[0]}


def _fields(text, rollup=False):
    fields = {}
    header = False
    for line in text.split("\n"):
        if not line.strip():
            continue
        if rollup and re.fullmatch(r"[0-9a-fA-F]+-[0-9a-fA-F]+\s+\S+\s+[0-9a-fA-F]+\s+\S+\s+[0-9]+\s+\[rollup\]", line):
            _need(not header, "DUPLICATE_FIELD")
            header = True
            continue
        # Split once rather than using a whitespace-backtracking expression.
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
    result = {"pid": _uint(fields["Pid"]), "ppid": _uint(fields["PPid"]),
              "state": fields["State"][0], "vmrss_bytes": None, "vmhwm_bytes": None}
    for name, raw in fields.items():
        if name.startswith("Vm") or name in ("RssAnon", "RssFile", "RssShmem", "HugetlbPages"):
            _memory(raw)
    # Dead processes can have no mm and hence no Vm* fields. Preserve identity
    # checking and let process() classify this as lifecycle uncertainty.
    if result["state"] in ("Z", "X", "x"):
        return result
    _need({"VmRSS", "VmHWM"} <= fields.keys(), "MISSING_FIELD")
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
        _need(len(parts) == 2 and re.fullmatch(r"[a-z_]+", parts[0]) is not None, "RAW_TEXT_MALFORMED")
        name, raw = parts
        _need(name not in result, "DUPLICATE_FIELD")
        result[name] = _uint(raw)
    _need({"low", "high", "max", "oom", "oom_kill"} <= result.keys(), "MISSING_FIELD")
    return result


def _identity(identity, config, worker=False):
    _object(identity, ("pid", "starttime_ticks", "boot_id", "parent_pid", "role") if worker
            else ("pid", "starttime_ticks", "boot_id", "ppid"))
    _integer(identity["pid"], 1, 2147483647, "IDENTITY_INVALID")
    _integer(identity["starttime_ticks"], code="IDENTITY_INVALID")
    _integer(identity["parent_pid" if worker else "ppid"], 1 if worker else 0, 2147483647,
             "IDENTITY_INVALID")
    _need(identity["boot_id"] == config["boot_id"], "BOOT_ID_MISMATCH")
    if worker:
        _label(identity["role"], "IDENTITY_INVALID")


def _validate(data):
    _object(data, ("schema", "source_kind", "config", "roster", "frame_count", "cgroup"))
    _need(data["schema"] == SCHEMA, "SCHEMA_VERSION_MISMATCH")
    _need(data["source_kind"] != "REAL_PROCFS", "REAL_SOURCE_NOT_AUTHORIZED")
    _need(data["source_kind"] == "FAKE_FIXTURE", "SOURCE_KIND_NOT_ACCEPTED")
    c = data["config"]
    _object(c, ("clock_ticks_per_second", "boot_id", "pid_namespace_id", "host_id",
                "max_read_skew_ns", "smaps_rollup_policy"))
    _integer(c["clock_ticks_per_second"], 1, 1000000, "CONFIGURATION_INVALID")
    _integer(c["max_read_skew_ns"], code="CONFIGURATION_INVALID")
    _need(type(c["boot_id"]) is str and len(c["boot_id"]) == 36 and
          re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", c["boot_id"]) is not None,
          "CONFIGURATION_INVALID")
    _label(c["pid_namespace_id"])
    _label(c["host_id"])
    _need(c["smaps_rollup_policy"] in ("NOT_SAMPLED", "OPTIONAL_DIAGNOSTIC"), "CONFIGURATION_INVALID")
    _integer(data["frame_count"], 1, MAX_FRAMES, "INPUT_CAP_EXCEEDED")
    roster = data["roster"]
    _object(roster, ("parent", "workers"))
    _identity(roster["parent"], c)
    _need(type(roster["workers"]) is list)
    _need(len(roster["workers"]) < MAX_PROCESSES, "INPUT_CAP_EXCEEDED")
    parent = roster["parent"]
    seen = {parent["pid"]}
    for worker in roster["workers"]:
        _identity(worker, c, worker=True)
        _need(worker["parent_pid"] == parent["pid"], "IDENTITY_CONTRADICTION")
        _need(worker["pid"] not in seen, "DUPLICATE_IDENTITY")
        seen.add(worker["pid"])
    _need(parent["ppid"] not in seen, "IDENTITY_CONTRADICTION")
    cg = data["cgroup"]
    if cg is not None:
        _object(cg, ("token", "controller_id", "membership", "membership_provenance", "baseline"))
        token = cg["token"]
        _need(type(token) is str and 0 < len(token) <= 192 and ".." not in token and
              all(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}", part) is not None
                  for part in token.split("/")), "CGROUP_CONFIGURATION_INVALID")
        _label(cg["controller_id"], "CGROUP_CONFIGURATION_INVALID")
        _label(cg["membership_provenance"], "CGROUP_CONFIGURATION_INVALID")
        _need(type(cg["membership"]) is list and len(cg["membership"]) <= MAX_PROCESSES,
              "CGROUP_CONFIGURATION_INVALID")
        for pid in cg["membership"]:
            _integer(pid, 1, 2147483647, "CGROUP_CONFIGURATION_INVALID")
        _need(len(set(cg["membership"])) == len(cg["membership"]) and set(cg["membership"]) == seen,
              "CGROUP_CONFIGURATION_INVALID")
        baseline = cg["baseline"]
        _object(baseline, ("memory_current_bytes", "memory_peak_bytes", "events", "provenance",
                           "boot_id", "pid_namespace_id", "observed_ns"))
        for field in ("memory_current_bytes", "memory_peak_bytes", "observed_ns"):
            _integer(baseline[field], code="CGROUP_CONFIGURATION_INVALID")
        _need(baseline["memory_peak_bytes"] >= baseline["memory_current_bytes"], "CGROUP_CONFIGURATION_INVALID")
        _need(type(baseline["events"]) is dict and
              {"low", "high", "max", "oom", "oom_kill"} <= baseline["events"].keys(),
              "CGROUP_CONFIGURATION_INVALID")
        for name, value in baseline["events"].items():
            _need(len(name) <= 64 and re.fullmatch(r"[a-z_]+", name) is not None, "CGROUP_CONFIGURATION_INVALID")
            _integer(value, code="CGROUP_CONFIGURATION_INVALID")
        _label(baseline["provenance"], "CGROUP_CONFIGURATION_INVALID")
        _need(baseline["boot_id"] == c["boot_id"] and baseline["pid_namespace_id"] == c["pid_namespace_id"],
              "CGROUP_CONFIGURATION_INVALID")


def _envelope():
    return {"schema": RESULT_SCHEMA, "source_kind": "FAKE_FIXTURE", "origin_attestation": "UNVERIFIED",
            "production_memory_qualification": "INCONCLUSIVE", "production_chronological_peak": "NOT_OBSERVED",
            "production_workload_measured": False, "holder_release": "NOT_ESTABLISHED",
            "atomic_snapshot": False, "bound_claim": "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK",
            "clock_kind": "INJECTED_MONOTONIC_NS",
            "starttime_alignment": "NOT_CALIBRATED", "worker_absence_proven": False,
            "worker_coverage": "NOT_ESTABLISHED", "unregistered_worker_coverage": "NOT_ESTABLISHED",
            "input_sha256": None, "config": None, "frames": [], "reasons": [],
            "first_read_start_ns": None, "last_read_end_ns": None, "read_skew_ns": None,
            "outcome": "INVALID", "invalid_reason_codes": [], "incomplete_reason_codes": []}


def _finish(report, reasons):
    ordered = sorted(set(reasons))
    report["reasons"] = [{"code": code, "location": location} for code, location in ordered]
    report["invalid_reason_codes"] = sorted({c for c, _ in ordered if c in INVALID_CODES})
    report["incomplete_reason_codes"] = sorted({c for c, _ in ordered if c not in INVALID_CODES})
    report["outcome"] = ("INVALID" if report["invalid_reason_codes"] else
                         "INCOMPLETE" if ordered else SUCCESS)
    report["integrity"] = {"algorithm": "sha256", "scope": "canonical result excluding integrity",
                           "sha256": _digest(report)}
    # JSON round-trip detaches even shared metadata between frames in this result.
    return json.loads(canonical_json(report))


class _Capture:
    def __init__(self, data, read_proc, clock, read_cgroup):
        self.data = data
        self.read_proc = read_proc
        self.clock = clock
        self.read_cgroup = read_cgroup
        self.reasons = []
        self.last_tick = None
        self.total_bytes = 0
        self.stopped = False
        self.previous_events = dict(data["cgroup"]["baseline"]["events"]) if data["cgroup"] else None
        self.previous_peak = data["cgroup"]["baseline"]["memory_peak_bytes"] if data["cgroup"] else None

    def tick(self):
        try:
            value = self.clock()
        except Exception:
            raise _Violation("CLOCK_FAILURE") from None
        _integer(value, code="CLOCK_FAILURE")
        _need(self.last_tick is None or value >= self.last_tick, "CLOCK_NON_MONOTONIC")
        self.last_tick = value
        return value

    def read(self, kind, target, location, parser, cgroup=False):
        record = {"kind": kind, "status": "NOT_READ", "reason_codes": [], "start_ns": None,
                  "end_ns": None, "sha256": None, "byte_length": None}
        value = None
        try:
            _need(not self.stopped, "CAPTURE_STOPPED")
            callback = self.read_cgroup if cgroup else self.read_proc
            _need(callable(callback), "CGROUP_READER_NOT_CONFIGURED" if cgroup else "READER_NOT_CONFIGURED")
            record["start_ns"] = self.tick()
            error = None
            try:
                text = callback(kind, target, MAX_TEXT_BYTES)
            except PermissionError:
                error = "PERMISSION_DENIED"
            except (FileNotFoundError, ProcessLookupError):
                error = "PROCESS_VANISHED"
            except OSError:
                error = "READ_FAILED"
            except Exception:
                error = "READER_EXCEPTION"
            # End the window even if the read failed; never retain exception messages.
            try:
                record["end_ns"] = self.tick()
            except _Violation as exc:
                if error:
                    record["reason_codes"].append(error)
                raise exc
            if error:
                raise _Violation(error)
            _need(type(text) is str, "READER_CONTRACT_VIOLATION")
            _need(len(text) <= MAX_TEXT_BYTES, "OVERSIZED")
            try:
                raw = text.encode("utf-8")
            except UnicodeError:
                raise _Violation("RAW_TEXT_MALFORMED") from None
            _need(len(raw) <= MAX_TEXT_BYTES, "OVERSIZED")
            record["byte_length"] = len(raw)
            record["sha256"] = hashlib.sha256(raw).hexdigest()
            self.total_bytes += len(raw)
            if self.total_bytes > MAX_TOTAL_TEXT_BYTES:
                self.stopped = True
                raise _Violation("TOTAL_TEXT_CAP_EXCEEDED")
            _need(text.endswith("\n"), "TRUNCATED")
            _text_guard(text)
            value = parser(text)
            record["status"] = "OK"
        except _Violation as exc:
            record["status"] = "FAILED"
            record["reason_codes"].append(exc.code)
            if exc.code in ("CLOCK_FAILURE", "CLOCK_NON_MONOTONIC"):
                self.stopped = True
        record["reason_codes"] = sorted(set(record["reason_codes"]))
        self.reasons.extend((code, location) for code in record["reason_codes"])
        return record, value

    def process(self, identity, worker, location):
        expected_ppid = identity["parent_pid" if worker else "ppid"]
        record = {"identity": dict(identity), "status": "INCOMPLETE", "reads": [],
                  "vmrss_bytes": None, "vmhwm_bytes": None, "smaps_rollup": None,
                  "reason_codes": []}
        values = {}
        sequence = [("stat_before", "stat", _stat), ("status", "status", _status)]
        if self.data["config"]["smaps_rollup_policy"] == "OPTIONAL_DIAGNOSTIC":
            sequence.append(("smaps_rollup", "smaps_rollup", _smaps))
        sequence.append(("stat_after", "stat", _stat))
        for label, kind, parser in sequence:
            read, value = self.read(kind, identity["pid"], location + "." + label, parser)
            read["label"] = label
            record["reads"].append(read)
            values[label] = value
            record["reason_codes"].extend(read["reason_codes"])
            if value is not None and label in ("stat_before", "stat_after", "status"):
                if value["pid"] != identity["pid"] or value["ppid"] != expected_ppid:
                    record["reason_codes"].append("IDENTITY_CONTRADICTION")
                if label != "status" and value["starttime_ticks"] != identity["starttime_ticks"]:
                    record["reason_codes"].append("PID_REUSE_OR_IDENTITY_RACE")
                if value["state"] in ("Z", "X", "x"):
                    record["reason_codes"].append("PROCESS_NOT_LIVE")
        record["reason_codes"] = sorted(set(record["reason_codes"]))
        self.reasons.extend((code, location) for code in record["reason_codes"])
        if not record["reason_codes"]:
            record["status"] = SUCCESS
            record["vmrss_bytes"] = values["status"]["vmrss_bytes"]
            record["vmhwm_bytes"] = values["status"]["vmhwm_bytes"]
            record["smaps_rollup"] = values.get("smaps_rollup")
        return record

    def cgroup(self, location):
        cg = self.data["cgroup"]
        if cg is None:
            return None
        section = {"identity": {k: cg[k] for k in ("token", "controller_id", "membership", "membership_provenance")},
                   "membership_verification": "CALLER_ASSERTED_ONLY", "baseline": cg["baseline"],
                   "status": "INCOMPLETE", "reads": [], "reason_codes": [],
                   "memory_current_bytes": None, "memory_peak_bytes": None, "events": None}
        values = []
        for kind, parser in (("memory.current", lambda t: _uint(t.strip())),
                             ("memory.peak", lambda t: _uint(t.strip())), ("memory.events", _events)):
            read, value = self.read(kind, cg["token"], location + "." + kind, parser, cgroup=True)
            section["reads"].append(read)
            section["reason_codes"].extend(read["reason_codes"])
            values.append(value)
        current, peak, events = values
        starts = [r["start_ns"] for r in section["reads"] if r["start_ns"] is not None]
        if starts and cg["baseline"]["observed_ns"] > starts[0]:
            section["reason_codes"].append("BASELINE_CHRONOLOGY_INVALID")
        if peak is not None and peak < self.previous_peak:
            section["reason_codes"].append("COUNTER_INCONSISTENT")
        if events is not None and any(name not in events or events[name] < count
                                      for name, count in self.previous_events.items()):
            section["reason_codes"].append("COUNTER_INCONSISTENT")
        # Do not compare current with peak: these are separate, non-atomic reads.
        if not section["reason_codes"]:
            section.update(status=SUCCESS, memory_current_bytes=current, memory_peak_bytes=peak, events=events)
            self.previous_peak, self.previous_events = peak, events
        section["reason_codes"] = sorted(set(section["reason_codes"]))
        self.reasons.extend((code, location) for code in section["reason_codes"])
        return section

    def frames(self):
        frames = []
        identities = [(self.data["roster"]["parent"], False)] + [(w, True) for w in self.data["roster"]["workers"]]
        for index in range(self.data["frame_count"]):
            start_reasons = len(self.reasons)
            location = "frames.%d" % index
            processes = [self.process(identity, worker, location + ".processes.%d" % number)
                         for number, (identity, worker) in enumerate(identities)]
            cg = self.cgroup(location + ".cgroup")
            reads = [r for p in processes for r in p["reads"]] + (cg["reads"] if cg else [])
            starts = [r["start_ns"] for r in reads if r["start_ns"] is not None]
            ends = [r["end_ns"] for r in reads if r["end_ns"] is not None]
            first, last = (starts[0] if starts else None), (ends[-1] if ends else None)
            skew = last - first if first is not None and last is not None else None
            if skew is not None and skew > self.data["config"]["max_read_skew_ns"]:
                self.reasons.append(("READ_SKEW_EXCEEDED", location))
            codes = sorted({code for code, _ in self.reasons[start_reasons:]})
            status = "INVALID" if any(c in INVALID_CODES for c in codes) else "INCOMPLETE" if codes else SUCCESS
            if codes:
                for process in processes:
                    # A frame-wide failure must never leave successful member records.
                    process.update(status=status, vmrss_bytes=None, vmhwm_bytes=None, smaps_rollup=None)
                if cg:
                    cg["status"] = status
            frames.append({"index": index, "status": status, "reason_codes": codes, "processes": processes,
                           "cgroup": cg, "first_read_start_ns": first, "last_read_end_ns": last,
                           "read_skew_ns": skew, "read_window_complete": all(r["start_ns"] is not None and
                               r["end_ns"] is not None for r in reads)})
            if self.stopped:
                break
        if len(frames) != self.data["frame_count"]:
            self.reasons.append(("CAPTURE_STOPPED", "frames"))
        return frames


class ProcfsProvider:
    """Explicitly injected fake-only provider; construction never calls callbacks.

    ``sample(request)`` returns a sealed detached dictionary. Callbacks must be
    bounded, nonblocking fixture functions; this library cannot preempt a caller.
    No callbacks or operating-system APIs are selected by default.
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
            report["input_sha256"] = _digest(data)
            report["config"] = dict(data["config"])
            _need(callable(self._read_proc), "READER_NOT_CONFIGURED")
            _need(callable(self._clock), "CLOCK_NOT_CONFIGURED")
        except _Violation as exc:
            return _finish(report, [(exc.code, "request")])
        capture = _Capture(data, self._read_proc, self._clock, self._read_cgroup)
        report["frames"] = capture.frames()
        starts = [f["first_read_start_ns"] for f in report["frames"] if f["first_read_start_ns"] is not None]
        ends = [f["last_read_end_ns"] for f in report["frames"] if f["last_read_end_ns"] is not None]
        report["first_read_start_ns"] = starts[0] if starts else None
        report["last_read_end_ns"] = ends[-1] if ends else None
        if starts and ends:
            report["read_skew_ns"] = ends[-1] - starts[0]
        if data["roster"]["workers"]:
            report["worker_coverage"] = ("REGISTERED_ROSTER_OBSERVED" if not capture.reasons else "UNCERTAIN")
        return _finish(report, capture.reasons)
