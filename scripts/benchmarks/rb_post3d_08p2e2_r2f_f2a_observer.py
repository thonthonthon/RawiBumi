"""Pure fake-input passive observer. No instruments, production imports or I/O.

See the companion validation document for the caller-supplied record contract.
All times are integer monotonic nanoseconds; Linux kB denotes 1024 bytes.
"""

import hashlib
import json
import re


SCHEMA = "rawibumi.passive-memory-observer.f2a.v1"
PHASES = ("setup", "producer", "attribution", "persistence", "verification",
          "dispatch", "b2_numerical_acceptance", "compatibility_controls")
INVALID = "INVALID_EVIDENCE"
INCONCLUSIVE = "INCONCLUSIVE"
COMPLETE = "OBSERVATION_COMPLETE"
REASON_CLASSES = {
    **dict.fromkeys((
        "MALFORMED_INPUT", "MISSING_FIELD", "DUPLICATE_FIELD", "NEGATIVE_FIELD",
        "INVALID_UNIT", "INCONSISTENT_COUNTER", "INVALID_IDENTITY",
        "PID_REUSE_ANOMALY", "DUPLICATE_RECORD", "OUT_OF_ORDER",
        "UNKNOWN_WORKER_TOPOLOGY", "IDENTITY_CONTRADICTION", "INVALID_PHASE",
        "INVALID_LIFECYCLE", "UNEXPECTED_PROCESS", "INVALID_READ_WINDOW",
        "DUPLICATE_HOLDER", "INVALID_RELEASE", "CROSS_PROCESS_RELEASE",
        "SLOT_COUNT_MISMATCH",
    ), INVALID),
    **dict.fromkeys((
        "SAMPLE_GAP", "MISSING_PROCESS", "INCOMPLETE_FRAME_SET",
        "EVIDENCE_TRUNCATED", "SEQUENCE_GAP", "DECLARED_COUNT_MISMATCH",
        "MISSING_PHASE_COVERAGE", "MISSING_ROLE_COVERAGE", "OPEN_PROCESS_LIFETIME",
        "EXIT_WITHOUT_FINAL_OBSERVATION", "OPEN_HOLDER_LIFETIME",
        "ALIGNMENT_NOT_ESTABLISHED", "EXCESSIVE_READ_SKEW", "SWAP_OBSERVED",
        "OOM_OBSERVED", "CGROUP_LIMIT_EVENT", "MISSING_CGROUP_DATA",
        "INCOMPLETE_HOLDER_COVERAGE",
    ), INCONCLUSIVE),
}


class EvidenceError(ValueError):
    """An input contract violation with a stable, reportable reason code."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.outcome = REASON_CLASSES[code]


def require(condition, code, detail):
    if not condition:
        raise EvidenceError(code, detail)


def integer(value, name, minimum=0):
    require(type(value) is int, "MALFORMED_INPUT", name + " must be an integer")
    require(value >= minimum, "NEGATIVE_FIELD" if value < 0 else "MALFORMED_INPUT",
            name + " below minimum")
    return value


def field(mapping, name):
    require(type(mapping) is dict, "MALFORMED_INPUT", "Expected an object")
    require(name in mapping, "MISSING_FIELD", name)
    return mapping[name]


def label(value, name):
    require(type(value) is str and bool(value.strip()), "MALFORMED_INPUT", name)
    return value


def identity(value):
    require(type(value) in (list, tuple) and len(value) == 2,
            "INVALID_IDENTITY", "Expected [pid, starttime_ticks]")
    return (integer(value[0], "pid", 1), integer(value[1], "starttime_ticks"))


def identity_key(value):
    return "%d:%d" % identity(value)


def phase(value):
    require(type(value) is str and value in PHASES, "INVALID_PHASE", str(value))
    return value


def canonical_bytes(value):
    """Canonical JSON, no NaN/Infinity; no filesystem writes."""
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _json_copy(value):
    # Reject non-JSON keys/types rather than letting JSON silently coerce keys.
    if type(value) is dict:
        require(all(type(key) is str for key in value), "MALFORMED_INPUT", "Non-string key")
        return {key: _json_copy(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [_json_copy(item) for item in value]
    require(value is None or type(value) in (str, bool, int, float),
            "MALFORMED_INPUT", "Non-JSON value")
    try:
        canonical_bytes(value)
    except (ValueError, TypeError) as exc:
        raise EvidenceError("MALFORMED_INPUT", "Non-finite JSON value") from exc
    return value


def seal(report):
    payload = {key: value for key, value in report.items() if key != "integrity"}
    return {**payload, "integrity": {"algorithm": "sha256", "scope": "canonical report excluding integrity",
                                    "sha256": digest(payload)}}


def verify_integrity(report):
    if type(report) is not dict:
        return False
    try:
        return seal(report)["integrity"] == report["integrity"]
    except (ValueError, TypeError, KeyError, RecursionError):
        return False


def _unsigned(raw, name):
    require(re.fullmatch(r"-[0-9]+", raw) is None, "NEGATIVE_FIELD", name)
    require(re.fullmatch(r"[0-9]+", raw) is not None, "MALFORMED_INPUT", name)
    return int(raw)


def _proc_fields(text, memory_fields, integer_fields=(), header=False, all_memory=False):
    require(type(text) is str, "MALFORMED_INPUT", "Expected supplied proc text")
    parsed = {}
    seen = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        if header and re.fullmatch(r"[0-9a-fA-F]+-[0-9a-fA-F]+\s+\S+\s+[0-9a-fA-F]+\s+\S+\s+[0-9]+\s+\[rollup\]", line):
            require("__header" not in seen, "DUPLICATE_FIELD", "rollup header")
            seen.add("__header")
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*):\s*(.*?)\s*", line)
        require(match is not None, "MALFORMED_INPUT", "Malformed proc line: " + line)
        name, raw = match.groups()
        require(name not in seen, "DUPLICATE_FIELD", name)
        seen.add(name)
        if name in integer_fields:
            parsed[name] = _unsigned(raw, name)
        elif (all_memory or name in memory_fields or name.startswith("Vm")
              or name in ("RssAnon", "RssFile", "RssShmem", "HugetlbPages")):
            parts = raw.split()
            require(len(parts) == 2 and parts[1] == "kB", "INVALID_UNIT", name)
            parsed[name] = _unsigned(parts[0], name) * 1024
        # Unselected proc metadata is retained verbatim in raw observations.
    required = set(memory_fields) | set(integer_fields)
    require(required <= parsed.keys(), "MISSING_FIELD", ",".join(sorted(required - parsed.keys())))
    return parsed


def parse_status(text):
    result = _proc_fields(text, ("VmRSS", "VmHWM", "VmSwap"), ("Pid", "PPid"))
    require(result["Pid"] > 0, "INVALID_IDENTITY", "status Pid must be positive")
    require(result["VmHWM"] >= result["VmRSS"], "INCONSISTENT_COUNTER", "VmHWM below VmRSS")
    return result


def parse_smaps_rollup(text):
    return _proc_fields(text, ("Rss", "Swap"), header=True, all_memory=True)


def parse_stat(text):
    require(type(text) is str, "MALFORMED_INPUT", "Expected supplied stat text")
    # comm can contain spaces, '(' and ')'. Only the final ')' is the delimiter.
    opening = text.find("(")
    closing = text.rfind(")")
    require(opening > 0 and closing > opening, "MALFORMED_INPUT", "stat comm delimiters")
    pid = _unsigned(text[:opening].strip(), "pid")
    require(pid > 0, "INVALID_IDENTITY", "stat pid must be positive")
    require(text[closing + 1:closing + 2].isspace(), "MALFORMED_INPUT", "stat state delimiter")
    tail = text[closing + 1:].split()
    require(len(tail) >= 20, "MISSING_FIELD", "stat needs field 22")
    require(re.fullmatch(r"[RSDZTtXxKWIPN]", tail[0]) is not None,
            "MALFORMED_INPUT", "stat state")
    # Fields 16-19 are signed; later Linux fields can also be signed.
    signed_fields = {7, 8, 16, 17, 18, 19, 21, 24, 38, 39, 44, 52}
    for number, raw in enumerate(tail[1:], 4):
        if number in signed_fields:
            require(re.fullmatch(r"-?[0-9]+", raw) is not None,
                    "MALFORMED_INPUT", "stat field %d" % number)
        else:
            _unsigned(raw, "stat field %d" % number)
    return {"pid": pid, "comm": text[opening + 1:closing], "state": tail[0],
            "ppid": int(tail[1]), "starttime_ticks": int(tail[19])}


def parse_memory_events(text):
    if text is None:
        return None
    require(type(text) is str, "MALFORMED_INPUT", "Expected memory.events text")
    result = {}
    for line in text.splitlines():
        parts = line.split()
        require(len(parts) == 2 and re.fullmatch(r"[a-z_]+", parts[0]) is not None,
                "MALFORMED_INPUT", "memory.events line")
        name, raw = parts
        require(name not in result, "DUPLICATE_FIELD", name)
        result[name] = _unsigned(raw, name)
    require({"low", "high", "max", "oom", "oom_kill"} <= result.keys(),
            "MISSING_FIELD", "memory.events required counters")
    return result  # Unknown future counters are preserved as counts, not bytes.


def _configuration(config):
    integer(field(config, "max_read_skew_ns"), "max_read_skew_ns")
    integer(field(config, "max_frame_gap_ns"), "max_frame_gap_ns", 1)
    phases = field(config, "required_phases")
    require(type(phases) is list and bool(phases), "INVALID_PHASE", "required_phases")
    for item in phases:
        phase(item)
    require(len(set(phases)) == len(phases), "DUPLICATE_FIELD", "required_phases")
    require(type(config.get("topology")) is dict, "UNKNOWN_WORKER_TOPOLOGY", "Missing topology")
    topology = config["topology"]
    require({"start_method", "parents", "workers", "max_concurrent_workers"} <= topology.keys(),
            "UNKNOWN_WORKER_TOPOLOGY", "Incomplete topology declaration")
    require(field(topology, "start_method") == "spawn", "UNKNOWN_WORKER_TOPOLOGY", "spawn required")
    parents = field(topology, "parents")
    workers = field(topology, "workers")
    require(type(parents) is list and bool(parents) and type(workers) is list,
            "UNKNOWN_WORKER_TOPOLOGY", "Explicit parent and worker roster required")
    limit = integer(field(topology, "max_concurrent_workers"), "max_concurrent_workers")
    roster = {}
    for value in parents:
        key = identity_key(value)
        require(key not in roster, "UNKNOWN_WORKER_TOPOLOGY", "Duplicate parent")
        roster[key] = {"identity": list(identity(value)), "role": "parent", "parent": None}
    parent_keys = set(roster)
    for worker in workers:
        value = field(worker, "identity")
        key = identity_key(value)
        parent = identity_key(field(worker, "parent"))
        require(key not in roster and parent in parent_keys,
                "UNKNOWN_WORKER_TOPOLOGY", "Duplicate worker or unknown parent")
        roster[key] = {"identity": list(identity(value)), "role": "worker", "parent": parent}
    require(not workers or limit > 0, "UNKNOWN_WORKER_TOPOLOGY", "Worker limit is zero")
    return roster, limit


class _Reconciler:
    def __init__(self, config):
        self.config = config
        self.roster, self.worker_limit = _configuration(config)
        self.processes = {}
        self.frames = []
        self.cgroups = []
        self.holders = {}
        self.holder_maxima = {}
        self.global_holder_maxima = {}
        self.reasons = []
        self.last_time = None
        self.last_frame = None
        self.last_sequence = None
        self.cgroup_counters = {}

    def reason(self, code, detail, sequence=None):
        self.reasons.append({"code": code, "outcome": REASON_CLASSES[code],
                             "detail": detail, "sequence": sequence})

    def live(self):
        return {key for key, value in self.processes.items() if value["exit_ns"] is None}

    def process(self, value):
        key = identity_key(value)
        require(key in self.live(), "INVALID_LIFECYCLE", "Identity is not live: " + key)
        return key, self.processes[key]

    def consume(self, record):
        seq = integer(field(record, "sequence"), "sequence")
        if self.last_sequence is not None:
            require(seq > self.last_sequence, "DUPLICATE_RECORD" if seq == self.last_sequence
                    else "OUT_OF_ORDER", "record sequence")
            if seq != self.last_sequence + 1:
                self.reason("SEQUENCE_GAP", "Missing record sequence", seq)
        elif seq != 0:
            self.reason("SEQUENCE_GAP", "First sequence must be zero", seq)
        self.last_sequence = seq
        now = integer(field(record, "time_ns"), "time_ns")
        require(self.last_time is None or now >= self.last_time, "OUT_OF_ORDER", "record timestamp")
        self.last_time = now
        kind = field(record, "kind")
        require(kind in ("START", "PHASE", "EXIT", "CREATE", "RELEASE", "FRAME"),
                "MALFORMED_INPUT", "Unknown record kind")
        if kind == "FRAME":
            self.frame(record, now)
            return
        key = identity_key(field(record, "identity"))
        if kind == "START":
            require(key in self.roster, "UNKNOWN_WORKER_TOPOLOGY", key)
            require(key not in self.processes, "DUPLICATE_RECORD", "Duplicate START")
            declared = self.roster[key]
            require(field(record, "role") == declared["role"], "IDENTITY_CONTRADICTION", "role")
            ppid = integer(field(record, "ppid"), "ppid")
            expected_ppid = ppid if declared["parent"] is None else self.roster[declared["parent"]]["identity"][0]
            require(ppid == expected_ppid, "IDENTITY_CONTRADICTION", "ppid")
            require(not any(self.processes[k]["identity"][0] == declared["identity"][0]
                            for k in self.live()), "PID_REUSE_ANOMALY", "PID already live")
            require(all(value["identity"][1] < declared["identity"][1]
                        for value in self.processes.values() if value["identity"][0] == declared["identity"][0]),
                    "PID_REUSE_ANOMALY", "Reused PID starttime did not increase")
            if declared["parent"] is not None:
                require(declared["parent"] in self.live(), "INVALID_LIFECYCLE", "Parent not live")
                require(sum(self.processes[k]["role"] == "worker" for k in self.live()) < self.worker_limit,
                        "UNKNOWN_WORKER_TOPOLOGY", "Worker concurrency exceeds declaration")
            current_phase = phase(field(record, "phase"))
            self.processes[key] = {**declared, "ppid": ppid, "start_ns": now, "exit_ns": None,
                                   "phase": current_phase, "phases": [current_phase],
                                   "phase_since_ns": now, "observations": [], "observed_hwm_bytes": None}
            return
        key, process = self.process(field(record, "identity"))
        if "role" in record:
            require(record["role"] == process["role"], "IDENTITY_CONTRADICTION", "role change")
        if "ppid" in record:
            require(integer(record["ppid"], "ppid") == process["ppid"],
                    "IDENTITY_CONTRADICTION", "ppid change")
        if kind == "PHASE":
            current_phase = phase(field(record, "phase"))
            require(current_phase != process["phase"], "DUPLICATE_RECORD", "Repeated PHASE")
            process["phase"] = current_phase
            process["phase_since_ns"] = now
            process["phases"].append(current_phase)
        elif kind == "EXIT":
            require(not any(self.processes[child]["parent"] == key for child in self.live()),
                    "INVALID_LIFECYCLE", "Parent EXIT while declared worker is live")
            # Final observation means an explicitly final, valid per-process reading
            # at this timestamp in a complete and aligned frame, immediately before EXIT.
            final = [item for item in process["observations"]
                     if item["time_ns"] == now and item["final"] and item["aggregate_eligible"]]
            if not final:
                self.reason("EXIT_WITHOUT_FINAL_OBSERVATION", key, record["sequence"])
            process["exit_ns"] = now
        else:
            self.holder(record, key, process, now)

    def holder(self, record, key, process, now):
        current_phase = phase(field(record, "phase"))
        require(current_phase == process["phase"], "INVALID_PHASE", "Holder phase differs from process")
        count = integer(field(record, "slots"), "slots")
        holder_id = label(field(record, "holder_id"), "holder_id")
        pair = (key, holder_id)
        if record["kind"] == "CREATE":
            require(pair not in self.holders, "DUPLICATE_HOLDER", "Holder ID reuse")
            self.holders[pair] = {"process": key, "holder_id": holder_id, "phase": current_phase,
                                  "slots": count, "create_ns": now, "release_ns": None}
        else:
            if pair not in self.holders:
                require(not any(hid == holder_id and owner != key for owner, hid in self.holders),
                        "CROSS_PROCESS_RELEASE", holder_id)
                raise EvidenceError("INVALID_RELEASE", "Unmatched holder " + holder_id)
            item = self.holders[pair]
            require(item["release_ns"] is None, "INVALID_RELEASE", "Double RELEASE")
            require(item["slots"] == count, "SLOT_COUNT_MISMATCH", holder_id)
            item["release_ns"] = now
        # Concurrency is per identity, by CREATE phase even across phase transitions.
        active = [item for item in self.holders.values()
                  if item["process"] == key and item["release_ns"] is None]
        for bucket in ("ALL",) + PHASES:
            selected = [item for item in active if bucket == "ALL" or item["phase"] == bucket]
            maxima = self.holder_maxima.setdefault(key, {}).setdefault(bucket, {"holders": 0, "slots": 0})
            maxima["holders"] = max(maxima["holders"], len(selected))
            maxima["slots"] = max(maxima["slots"], sum(item["slots"] for item in selected))
        all_active = [item for item in self.holders.values()
                      if item["release_ns"] is None and self.processes[item["process"]]["exit_ns"] is None]
        for bucket in ("ALL",) + PHASES:
            selected = [item for item in all_active if bucket == "ALL" or item["phase"] == bucket]
            maxima = self.global_holder_maxima.setdefault(bucket, {"holders": 0, "slots": 0})
            maxima["holders"] = max(maxima["holders"], len(selected))
            maxima["slots"] = max(maxima["slots"], sum(item["slots"] for item in selected))

    def reading(self, reading, now, expected):
        key, process = self.process(field(reading, "identity"))
        require(key in expected, "UNEXPECTED_PROCESS", key)
        if "role" in reading:
            require(reading["role"] == process["role"], "IDENTITY_CONTRADICTION", "Reading role")
        status = parse_status(field(reading, "status"))
        stat = parse_stat(field(reading, "stat"))
        require(status["Pid"] == stat["pid"] == process["identity"][0],
                "IDENTITY_CONTRADICTION", "Reading pid mismatch")
        require(stat["starttime_ticks"] == process["identity"][1],
                "PID_REUSE_ANOMALY", "Reading starttime mismatch")
        require(status["PPid"] == stat["ppid"] == process["ppid"],
                "IDENTITY_CONTRADICTION", "Reading ppid mismatch")
        require(phase(field(reading, "phase")) == process["phase"], "INVALID_PHASE", "Reading phase")
        hwm = process["observed_hwm_bytes"]
        require(hwm is None or status["VmHWM"] >= hwm,
                "INCONSISTENT_COUNTER", "Decreasing VmHWM: " + key)
        smaps = reading.get("smaps_rollup")
        smaps = None if smaps is None else parse_smaps_rollup(smaps)
        final = reading.get("final", False)
        require(type(final) is bool, "MALFORMED_INPUT", "final must be boolean")
        result = {"identity": key, "time_ns": now, "phase": process["phase"], "status": status,
                  "smaps_rollup": smaps, "final": final, "aggregate_eligible": False}
        return key, result

    def window(self, mapping, now, floor):
        start, end = mapping.get("read_start_ns"), mapping.get("read_end_ns")
        if start is None and end is None:
            return None
        integer(start, "read_start_ns")
        integer(end, "read_end_ns")
        require(floor <= start <= end <= now, "INVALID_READ_WINDOW", "Read bounds outside live phase/capture")
        return start, end

    def cgroup(self, supplied, now):
        if supplied is None:
            self.reason("MISSING_CGROUP_DATA", "No supplied memory.events")
            return None
        source = label(field(supplied, "source_id"), "cgroup source_id")
        timestamp = integer(field(supplied, "time_ns"), "cgroup time_ns")
        require(timestamp <= now, "INVALID_READ_WINDOW", "Future cgroup reading")
        events = parse_memory_events(field(supplied, "memory_events"))
        if events is None:
            self.reason("MISSING_CGROUP_DATA", source)
        prior = self.cgroup_counters.get(source)
        if prior is not None:
            require(timestamp > prior[0], "OUT_OF_ORDER", "cgroup timestamp")
            if events is not None:
                require(all(name in events and events[name] >= value for name, value in prior[1].items()),
                        "INCONSISTENT_COUNTER", "Decreasing/disappearing cgroup counters")
        self.cgroup_counters[source] = (timestamp, events if events is not None else prior[1] if prior else {})
        if events is not None:
            if any(events.get(name, 0) > 0 for name in ("oom", "oom_kill", "oom_group_kill")):
                self.reason("OOM_OBSERVED", source)
            if events["max"] > 0:
                self.reason("CGROUP_LIMIT_EVENT", source)
        result = {"source_id": source, "time_ns": timestamp, "memory_events": events,
                  "semantics": "cgroup v2 hierarchical cumulative event counters; not process RSS"}
        self.cgroups.append(result)
        return result

    def frame(self, record, now):
        require(self.last_frame is None or now > self.last_frame,
                "OUT_OF_ORDER", "Frame capture times must strictly increase")
        if self.last_frame is not None and now - self.last_frame > self.config["max_frame_gap_ns"]:
            self.reason("SAMPLE_GAP", "Frame capture gap", record["sequence"])
        self.last_frame = now
        supplied_expected = field(record, "expected_live")
        require(type(supplied_expected) is list, "MALFORMED_INPUT", "expected_live")
        expected = [identity_key(item) for item in supplied_expected]
        require(len(expected) == len(set(expected)), "DUPLICATE_RECORD", "expected_live")
        expected = set(expected)
        live = self.live()
        require(expected <= live, "UNEXPECTED_PROCESS", "Expected identity not live")
        topology_complete = expected == live
        if not topology_complete:
            self.reason("MISSING_PROCESS", "Live identities omitted from expected_live: " + ",".join(sorted(live - expected)))
        readings = field(record, "readings")
        require(type(readings) is list, "MALFORMED_INPUT", "readings")
        frame = {"time_ns": now, "expected_live": sorted(expected), "valid_readings": [],
                 "complete": False, "alignment": "NOT_ESTABLISHED", "read_skew_ns": None,
                 "sampled_rss_bytes": None, "sampled_smaps_rss_bytes": None}
        self.frames.append(frame)
        seen = set()
        valid = {}
        windows = []
        window_invalid = False
        try:
            frame_window = self.window(record, now, 0)
        except EvidenceError as exc:
            self.reason(exc.code, exc.detail, record["sequence"])
            frame_window = None
            window_invalid = True
        for reading in readings:
            try:
                key = identity_key(field(reading, "identity"))
                require(key not in seen, "DUPLICATE_RECORD", "Duplicate process reading")
                seen.add(key)
                key, parsed = self.reading(reading, now, expected)
                valid[key] = parsed
                process = self.processes[key]
                process["observed_hwm_bytes"] = parsed["status"]["VmHWM"]
                process["observations"].append(parsed)
                frame["valid_readings"].append(parsed)
                if parsed["status"]["VmSwap"] or (parsed["smaps_rollup"] or {}).get("Swap", 0):
                    self.reason("SWAP_OBSERVED", key, record["sequence"])
                # A malformed timing envelope must not discard valid process data.
                floor = max(process["start_ns"], process["phase_since_ns"])
                bounds = self.window(reading, now, floor)
                if bounds is None and frame_window is not None:
                    require(frame_window[0] >= floor, "INVALID_READ_WINDOW", "Frame predates live phase")
                    bounds = frame_window
                if bounds is not None and frame_window is not None:
                    require(frame_window[0] <= bounds[0] <= bounds[1] <= frame_window[1],
                            "INVALID_READ_WINDOW", "Reading outside frame bounds")
                if bounds is not None:
                    previous_end = process.get("last_read_end_ns")
                    require(previous_end is None or bounds[0] >= previous_end,
                            "OUT_OF_ORDER", "Per-process read windows overlap or reverse")
                    process["last_read_end_ns"] = bounds[1]
                windows.append(bounds)
            except EvidenceError as exc:
                self.reason(exc.code, exc.detail, record["sequence"])
                window_invalid = True
        frame["valid_readings"].sort(key=lambda item: item["identity"])
        frame["complete"] = topology_complete and set(valid) == expected and bool(expected) and len(readings) == len(valid)
        if set(valid) != expected:
            self.reason("MISSING_PROCESS", "Missing valid readings: " + ",".join(sorted(expected - set(valid))), record["sequence"])
        if not frame["complete"]:
            self.reason("INCOMPLETE_FRAME_SET", "Incomplete frame", record["sequence"])
        if window_invalid:
            frame["alignment"] = "INVALID"
        elif windows and all(item is not None for item in windows):
            earliest = min(item[0] for item in windows)
            latest = max(item[1] for item in windows)
            frame["read_skew_ns"] = latest - earliest
            frame["capture_age_ns"] = now - earliest
            if now - earliest <= self.config["max_read_skew_ns"]:
                frame["alignment"] = "BOUNDED_SEQUENTIAL_READS"
            else:
                frame["alignment"] = "EXCESSIVE_SKEW"
                self.reason("EXCESSIVE_READ_SKEW", "Read span or age exceeds configuration", record["sequence"])
        else:
            self.reason("ALIGNMENT_NOT_ESTABLISHED", "No complete read bounds", record["sequence"])
        if frame["complete"] and frame["alignment"] == "BOUNDED_SEQUENTIAL_READS":
            frame["sampled_rss_bytes"] = sum(item["status"]["VmRSS"] for item in valid.values())
            if all(item["smaps_rollup"] is not None for item in valid.values()):
                frame["sampled_smaps_rss_bytes"] = sum(item["smaps_rollup"]["Rss"] for item in valid.values())
            for item in valid.values():
                item["aggregate_eligible"] = True
        try:
            self.cgroup(record.get("cgroup"), now)
        except EvidenceError as exc:
            self.reason(exc.code, exc.detail, record["sequence"])

    def finish(self, evidence):
        coverage = evidence.get("holder_coverage", [])
        require(type(coverage) is list, "MALFORMED_INPUT", "holder_coverage")
        covered = set()
        for declaration in coverage:
            key = identity_key(field(declaration, "identity"))
            require(key in self.roster, "UNKNOWN_WORKER_TOPOLOGY", "Holder coverage identity")
            name = phase(field(declaration, "phase"))
            require((key, name) not in covered, "DUPLICATE_RECORD", "Holder coverage")
            require(type(field(declaration, "events_complete")) is bool,
                    "MALFORMED_INPUT", "events_complete")
            covered.add((key, name))
            if not declaration["events_complete"]:
                self.reason("INCOMPLETE_HOLDER_COVERAGE", key + ":" + name)
        for key in self.roster:
            phases = set(self.config["required_phases"]) | set(self.processes.get(key, {}).get("phases", []))
            for name in sorted(phases):
                if (key, name) not in covered:
                    self.reason("INCOMPLETE_HOLDER_COVERAGE", key + ":" + name)
        if evidence["truncated"]:
            self.reason("EVIDENCE_TRUNCATED", "Caller marked truncation")
        if evidence["declared_record_count"] != len(evidence["records"]):
            self.reason("DECLARED_COUNT_MISMATCH", "Record count differs from declaration")
        if evidence["declared_frame_count"] != len(self.frames):
            self.reason("DECLARED_COUNT_MISMATCH", "Frame count differs from declaration")
        if not self.frames:
            self.reason("INCOMPLETE_FRAME_SET", "No frames")
        for key in sorted(self.roster):
            if key not in self.processes:
                self.reason("MISSING_PROCESS", "Declared process never started: " + key)
        for key, process in self.processes.items():
            if process["exit_ns"] is None:
                self.reason("OPEN_PROCESS_LIFETIME", key)
            observed = {item["phase"] for item in process["observations"] if item["aggregate_eligible"]}
            missing = set(self.config["required_phases"]) - observed
            if missing:
                self.reason("MISSING_PHASE_COVERAGE", key + ":" + ",".join(sorted(missing)))
        observed_roles = {item["role"] for item in self.processes.values() if item["observations"]}
        expected_roles = {item["role"] for item in self.roster.values()}
        if expected_roles - observed_roles:
            self.reason("MISSING_ROLE_COVERAGE", ",".join(sorted(expected_roles - observed_roles)))
        for item in self.holders.values():
            if item["release_ns"] is None:
                self.reason("OPEN_HOLDER_LIFETIME", item["process"] + ":" + item["holder_id"])
        # Check both boundary and trailing gaps: a single early frame is not full coverage.
        if self.last_frame is not None and self.last_time - self.last_frame > self.config["max_frame_gap_ns"]:
            self.reason("SAMPLE_GAP", "Trailing lifecycle records beyond last frame")
        starts = [item["start_ns"] for item in self.processes.values()]
        if starts and self.frames and self.frames[0]["time_ns"] - min(starts) > self.config["max_frame_gap_ns"]:
            self.reason("SAMPLE_GAP", "Initial lifecycle records precede first frame")

    def metrics(self):
        lifetimes = {name: {"holders": 0, "slots": 0} for name in PHASES}
        by_process = {}
        for item in self.holders.values():
            counter = lifetimes[item["phase"]]
            counter["holders"] += 1
            counter["slots"] += item["slots"]
            counter = by_process.setdefault(item["process"], {}).setdefault(item["phase"], {"holders": 0, "slots": 0})
            counter["holders"] += 1
            counter["slots"] += item["slots"]
        samples = [frame["sampled_rss_bytes"] for frame in self.frames if frame["sampled_rss_bytes"] is not None]
        return {
            "sampled_aggregate": {"semantics": "SAMPLED sum of process VmRSS; bounded sequential reads; shared pages may be counted repeatedly",
                                  "max_rss_bytes": max(samples) if samples else None,
                                  "eligible_frame_count": len(samples), "frames": self.frames},
            "per_process_hwm_bytes": {key: value["observed_hwm_bytes"] for key, value in sorted(self.processes.items())},
            "cgroup_observations": self.cgroups,
            "holder_metrics": {"semantics": "Artificial event counts, not measured RSS; phase means CREATE phase",
                               "cumulative_lifetimes_by_phase": lifetimes,
                               "cumulative_lifetimes_by_process_phase": by_process,
                               "concurrent_maxima_by_process_phase": self.holder_maxima,
                               "concurrent_maxima_by_phase": self.global_holder_maxima,
                               "lifetimes": [self.holders[key] for key in sorted(self.holders)],
                               "lifetime_coverage_complete": not any(item["release_ns"] is None for item in self.holders.values()),
                               "event_coverage_complete": not any(item["outcome"] == INVALID or item["code"] in ("INCOMPLETE_HOLDER_COVERAGE", "EVIDENCE_TRUNCATED", "SEQUENCE_GAP", "DECLARED_COUNT_MISMATCH", "MISSING_PHASE_COVERAGE", "MISSING_PROCESS") for item in self.reasons)},
            "processes": {key: value for key, value in sorted(self.processes.items())},
            "role_phase_coverage": {key: {"role": value["role"], "declared_phases": value["phases"],
                                         "observed_phases": sorted({item["phase"] for item in value["observations"]}),
                                         "aligned_complete_phases": sorted({item["phase"] for item in value["observations"] if item["aggregate_eligible"]})}
                                    for key, value in sorted(self.processes.items())},
        }


def reconcile(config, evidence):
    """Reconcile one declared independent fake run; contract errors become reasons.

    Non-JSON input raises EvidenceError because it cannot be preserved in a JSON
    report. JSON-safe malformed records/config produce INVALID_EVIDENCE reports.
    No missing observations are synthesized or extrapolated.
    """
    config, evidence = _json_copy(config), _json_copy(evidence)
    report = {"schema": SCHEMA, "production_memory_qualification": INCONCLUSIVE,
              "production_chronological_peak": "NOT_OBSERVED", "input_kind": "FAKE_INPUT_ONLY",
              "configuration": config, "raw_supplied_observations": evidence,
              "input_sha256": digest(evidence),
              "caveats": ["No production measurement or memory-budget acceptance decision.",
                          "No runtime speedup or numerical parity claim.",
                          "Process VmHWM is observed per lifetime, never summed.",
                          "Sampled RSS sums are not system memory or chronological peaks.",
                          "Absent optional readings remain null; read bounds do not establish atomicity.",
                          "Holder coverage is limited to supplied artificial events."]}
    state = None
    reasons = []
    try:
        state = _Reconciler(config)
        for name in ("input_id", "workload_id", "independent_run_id"):
            label(field(evidence, name), name)
            report[name] = evidence[name]
        require(type(field(evidence, "conditions")) is dict, "MALFORMED_INPUT", "conditions")
        records = field(evidence, "records")
        require(type(records) is list, "MALFORMED_INPUT", "records")
        integer(field(evidence, "declared_record_count"), "declared_record_count")
        integer(field(evidence, "declared_frame_count"), "declared_frame_count")
        require(type(field(evidence, "truncated")) is bool, "MALFORMED_INPUT", "truncated")
        for record in records:
            try:
                state.consume(record)
            except EvidenceError as exc:
                state.reason(exc.code, exc.detail, record.get("sequence") if type(record) is dict else None)
        state.finish(evidence)
    except EvidenceError as exc:
        if state is not None:
            state.reason(exc.code, exc.detail)
        else:
            reasons.append({"code": exc.code, "outcome": exc.outcome, "detail": exc.detail, "sequence": None})
    if state is not None:
        report.update(state.metrics())
        reasons.extend(state.reasons)
    report["reasons"] = sorted(reasons, key=lambda item: (item["code"], -1 if type(item["sequence"]) is not int else item["sequence"], item["detail"]))
    report["outcome"] = INVALID if any(item["outcome"] == INVALID for item in reasons) else INCONCLUSIVE if reasons else COMPLETE
    report["coverage_complete"] = report["outcome"] == COMPLETE
    return seal(report)


def signed_difference(baseline, candidate):
    """Candidate minus baseline; retain numeric type and negative sign."""
    require(type(baseline) in (int, float) and type(candidate) in (int, float),
            "MALFORMED_INPUT", "Numeric differences only")
    canonical_bytes([baseline, candidate])
    result = candidate - baseline
    canonical_bytes(result)
    return result


def _comparison_input(report):
    """Extract JSON-safe provenance even when the supplied report is malformed."""
    outcome, codes, checksum = None, None, None
    if type(report) is not dict:
        return {}, outcome, codes, checksum
    if type(report.get("outcome")) is str:
        outcome = report["outcome"]
    supplied_reasons = report.get("reasons")
    if type(supplied_reasons) is list and all(
            type(item) is dict and type(item.get("code")) is str for item in supplied_reasons):
        codes = sorted({item["code"] for item in supplied_reasons})
    try:
        safe_report = _json_copy(report)
        checksum = digest(safe_report)
    except (ValueError, TypeError, RecursionError):
        return {}, outcome, codes, checksum
    return safe_report, outcome, codes, checksum


def compare_reports(baseline, candidate):
    """Compare only complete independent fake observations; never accept a budget."""
    reasons = []
    if not verify_integrity(baseline) or not verify_integrity(candidate):
        reasons.append("INTEGRITY_MISMATCH")
    baseline, baseline_outcome, baseline_codes, baseline_hash = _comparison_input(baseline)
    candidate, candidate_outcome, candidate_codes, candidate_hash = _comparison_input(candidate)
    raw_inputs, metrics = [], []
    for report, observed_outcome, observed_codes in (
            (baseline, baseline_outcome, baseline_codes),
            (candidate, candidate_outcome, candidate_codes)):
        if observed_outcome is None or observed_codes is None or not report:
            reasons.append("MALFORMED_REPORT")
        if observed_outcome != COMPLETE or observed_codes != [] or report.get("coverage_complete") is not True:
            reasons.append("INPUT_NOT_OBSERVATION_COMPLETE")
        for name in ("configuration", "raw_supplied_observations", "sampled_aggregate"):
            if type(report.get(name)) is not dict:
                reasons.append("MALFORMED_REPORT")
        raw = report.get("raw_supplied_observations")
        raw = raw if type(raw) is dict else {}
        if type(raw.get("conditions")) is not dict or type(raw.get("records")) is not list:
            reasons.append("MALFORMED_REPORT")
        raw_inputs.append(raw)
        for name in ("input_id", "workload_id", "independent_run_id", "input_sha256"):
            if type(report.get(name)) is not str or not report[name].strip():
                reasons.append("MALFORMED_REPORT")
        sampled = report.get("sampled_aggregate")
        metric = sampled.get("max_rss_bytes") if type(sampled) is dict else None
        if metric is None:
            reasons.append("MISSING_SAMPLED_METRIC")
        elif type(metric) is not int or metric < 0:
            reasons.append("MALFORMED_REPORT")
        metrics.append(metric)
    if baseline.get("schema") != SCHEMA or candidate.get("schema") != SCHEMA:
        reasons.append("SCHEMA_MISMATCH")
    if any(report.get("outcome") not in (COMPLETE, INCONCLUSIVE) for report in (baseline, candidate)):
        reasons.append("INVALID_EVIDENCE")
    if any(report.get("production_memory_qualification") != INCONCLUSIVE or
           report.get("production_chronological_peak") != "NOT_OBSERVED" or
           report.get("input_kind") != "FAKE_INPUT_ONLY" for report in (baseline, candidate)):
        reasons.append("INVALID_ENVELOPE")
    if (baseline.get("configuration") != candidate.get("configuration") or
            baseline.get("workload_id") != candidate.get("workload_id") or
            raw_inputs[0].get("conditions") != raw_inputs[1].get("conditions")):
        reasons.append("CONDITIONS_MISMATCH")
    if (not baseline.get("independent_run_id") or not candidate.get("independent_run_id") or
            baseline.get("independent_run_id") == candidate.get("independent_run_id") or
            baseline.get("input_id") == candidate.get("input_id") or
            baseline.get("input_sha256") == candidate.get("input_sha256")):
        reasons.append("INPUTS_NOT_INDEPENDENT")
    if raw_inputs[0].get("records") == raw_inputs[1].get("records"):
        reasons.append("INPUTS_NOT_INDEPENDENT")
    result = {"schema": SCHEMA + ".comparison", "production_memory_qualification": INCONCLUSIVE,
              "production_chronological_peak": "NOT_OBSERVED", "baseline_sha256": baseline_hash,
              "candidate_sha256": candidate_hash,
              "baseline_outcome": baseline_outcome, "candidate_outcome": candidate_outcome,
              "baseline_reason_codes": baseline_codes, "candidate_reason_codes": candidate_codes,
              "reasons": sorted(set(reasons)),
              "outcome": "NOT_COMPARABLE" if reasons else "COMPARABLE_FAKE_OBSERVATIONS",
              "candidate_minus_baseline_sampled_max_rss_bytes": None if reasons else signed_difference(*metrics),
              "caveat": "Descriptive sampled fake-input difference only; no acceptance or production peak."}
    return seal(result)
