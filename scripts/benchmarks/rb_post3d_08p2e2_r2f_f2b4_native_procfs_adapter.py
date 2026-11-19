"""Opt-in bounded native capture capability; B0 hardening is artificial I/O only.

No predecessor integration or qualifying observation is provided. Constructors
and imports are inert. A native call requires separate operational authorization.
"""

import errno
import hashlib
import json
import os
import re
import sys
import time

SCHEMA = "rawibumi.native-procfs-adapter.f2b4.d2b2a.v1"
RESULT_SCHEMA = SCHEMA + ".result"
NATIVE_OPT_IN = "ALLOW_BOUNDED_NATIVE_PROCFS_D2B2"
SUCCESS = "CAPTURE_CONSISTENT_NONQUALIFYING"
MAX_PROCESSES = 64
MAX_FRAMES = 32
MAX_BYTES = 65536
MAX_TOTAL_BYTES = 4194304
MAX_READ_ATTEMPTS = 16384
MAX_READ_ITERATIONS = 128
MAX_DEPTH = 16
MAX_NODES = 20000
U64_MAX = 18446744073709551615
I64_MAX = 9223372036854775807
INVALID_CODES = (
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
KNOWN_CODES = INVALID_CODES + (
    "TRUNCATED", "PROCESS_MEMORY_UNAVAILABLE", "PERMISSION_DENIED", "PROCESS_VANISHED",
    "READ_FAILED", "READER_EXCEPTION", "CAPTURE_STOPPED", "OPEN_ATTEMPT_CAP_EXCEEDED",
    "PRIOR_IDENTITY_UNVERIFIED", "TOTAL_BYTES_CAP_EXCEEDED", "READ_ATTEMPT_CAP_EXCEEDED",
    "OVERSIZED", "READ_ITERATION_CAP_EXCEEDED", "PROCESS_REPARENTED", "PID_REUSE",
    "PROCESS_NOT_LIVE", "ROSTER_INCOMPLETE", "UNKNOWN_PROCESS", "REGISTERED_PROCESS_MISSING",
    "READ_SKEW_EXCEEDED", "ROOT_UNAVAILABLE",
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


def _text(raw, encoding="utf-8"):
    try:
        text = raw.decode(encoding, errors="strict")
    except UnicodeError:
        raise _Violation("INVALID_UTF8") from None
    _need(text.endswith("\n"), "TRUNCATED")
    _need(re.search(r"\s{65}", text) is None and re.search(r"[0-9]{21}", text) is None,
          "RAW_TEXT_MALFORMED")
    _need(not any((ord(c) < 32 and c not in ("\n", "\t")) or
                  127 <= ord(c) <= 159 or c in ("\u2028", "\u2029") for c in text),
          "RAW_TEXT_MALFORMED")
    return text


def _stat(raw):
    _need(raw.endswith(b"\n"), "TRUNCATED")
    opening, closing = raw.find(b"("), raw.rfind(b")")
    _need(opening > 0 and closing > opening and raw[closing + 1:closing + 2] == b" " and
          re.fullmatch(rb"[1-9][0-9]{0,9} ", raw[:opening]) is not None,
          "RAW_TEXT_MALFORMED")
    pid = _number(raw[:opening - 1].decode("ascii"))
    _need(1 <= pid <= 2147483647, "RAW_TEXT_MALFORMED")
    # comm is opaque kernel bytes, including embedded parens/newlines and split
    # UTF-8 sequences. Only the final ') ' delimits the strict numeric tail.
    text = _text(raw[closing + 2:], encoding="ascii")
    _need(text.count("\n") == 1, "RAW_TEXT_MALFORMED")
    tail = text.split()
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


def _status(raw):
    _need(raw.endswith(b"\n"), "TRUNCATED")
    # Name is partially escaped by Linux and need not be UTF-8 or control-free.
    # Keep its key for duplicate detection, discarding only its opaque value.
    sanitized = b"\n".join(b"Name:" if line.startswith(b"Name:") else line
                           for line in raw.split(b"\n"))
    fields = _fields(_text(sanitized))
    _need({"Pid", "PPid", "State", "Tgid"} <= fields.keys(), "MISSING_FIELD")
    _need(re.fullmatch(r"[RSDZTtXxKWIPN](?:\s+\([^()]*\))?", fields["State"]) is not None,
          "RAW_TEXT_MALFORMED")
    _need(_number(fields["Tgid"]) == _number(fields["Pid"]), "IDENTITY_CONTRADICTION")
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
    _object(data, ("schema", "source_kind", "capture_mode", "run_id", "config",
                   "roster", "frame_rosters", "cgroup"))
    _need(data["schema"] == SCHEMA, "SCHEMA_VERSION_MISMATCH")
    _need(data["capture_mode"] in ("INJECTED", "NATIVE"), "CONFIGURATION_INVALID")
    _need(data["source_kind"] == ("TEST_INJECTED" if data["capture_mode"] == "INJECTED"
                                   else "NATIVE_REQUEST"), "SOURCE_KIND_NOT_ACCEPTED")
    _label(data["run_id"])
    c = data["config"]
    _object(c, ("clock_ticks_per_second", "boot_id", "pid_namespace_id", "max_read_skew_ns",
                "max_bytes", "max_total_bytes", "max_read_attempts", "max_read_iterations", "smaps_rollup_policy"))
    _integer(c["clock_ticks_per_second"], 1, 1000000, "CONFIGURATION_INVALID")
    _integer(c["max_read_skew_ns"], code="CONFIGURATION_INVALID")
    _integer(c["max_bytes"], 1, MAX_BYTES, "CONFIGURATION_INVALID")
    _integer(c["max_total_bytes"], 1, MAX_TOTAL_BYTES, "CONFIGURATION_INVALID")
    _integer(c["max_read_attempts"], 1, MAX_READ_ATTEMPTS, "CONFIGURATION_INVALID")
    _integer(c["max_read_iterations"], 1, MAX_READ_ITERATIONS, "CONFIGURATION_INVALID")
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
    _need(data["cgroup"] is None or (type(data["cgroup"]) is dict and
          data["cgroup"].keys() == {"enabled"} and data["cgroup"]["enabled"] is False),
          "CGROUP_NOT_AUTHORIZED")


def _envelope():
    return {"schema": RESULT_SCHEMA, "source_kind": "TEST_INJECTED",
            "origin_attestation": "UNVERIFIED", "qualification": "NONQUALIFYING",
            "independent_verification": "REQUIRED_NOT_PERFORMED",
            "production_memory_qualification": "INCONCLUSIVE",
            "production_chronological_peak": "NOT_OBSERVED",
            "production_workload_measured": False, "atomic_snapshot": False,
            "bound_claim": "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK",
            "holder_release": "NOT_ESTABLISHED", "owner_termination": "NOT_ESTABLISHED",
            "simultaneous_holder_occupancy": "NOT_ESTABLISHED",
            "worker_absence_proven": False, "unregistered_worker_coverage": "NOT_ESTABLISHED",
            "roster_provenance": "CALLER_ASSERTED_ONLY", "worker_coverage": "NOT_ESTABLISHED",
            "environment_provenance": "CALLER_ASSERTED_ONLY",
            "procfs_mount_verified": False, "starttime_alignment": "NOT_CALIBRATED",
            "clock_kind": "INJECTED_MONOTONIC_NS", "cgroup": "DISABLED",
            "run_id": None, "input_sha256": None, "config": None, "roster": None,
            "frames_requested": None, "frames": [], "reasons": [], "outcome": "INVALID",
            "read_attempts": 0, "open_attempts": 0, "total_bytes": 0,
            "first_read_start_ns": None, "last_read_end_ns": None, "read_skew_ns": None,
            "invalid_reason_codes": [], "incomplete_reason_codes": []}


def _classification(codes):
    return "INVALID" if any(c in INVALID_CODES for c in codes) else "INCOMPLETE" if codes else SUCCESS


def _finish(report, reasons):
    ordered = sorted(set(reasons))
    report["reasons"] = [{"code": c, "location": loc} for c, loc in ordered]
    report["invalid_reason_codes"] = sorted({c for c, _ in ordered if c in INVALID_CODES})
    report["incomplete_reason_codes"] = sorted({c for c, _ in ordered if c not in INVALID_CODES})
    report["outcome"] = _classification([c for c, _ in ordered])
    report["integrity"] = {"algorithm": "sha256", "scope": "canonical result excluding integrity",
                           "sha256": _digest(report)}
    return json.loads(canonical_json(report))


def _io_error(exc):
    if isinstance(exc, OSError):
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            return "PATH_POLICY_VIOLATION"
        if isinstance(exc, PermissionError) or exc.errno in (errno.EACCES, errno.EPERM):
            return "PERMISSION_DENIED"
        if isinstance(exc, (FileNotFoundError, ProcessLookupError)) or exc.errno in (errno.ENOENT, errno.ESRCH):
            return "PROCESS_VANISHED"
        return "READ_FAILED"
    return "READER_EXCEPTION"


def _exception_code(exc):
    if isinstance(exc, _Violation):
        return (exc.code if type(exc.code) is str and exc.code in KNOWN_CODES
                else "READER_CONTRACT_VIOLATION")
    return _io_error(exc)


class _NativeIO:
    """Minimal native glue. Never constructed on injected or rejected calls."""

    def open(self, name, *, directory, dir_fd=None):
        _need(type(name) is str and type(directory) is bool, "PATH_POLICY_VIOLATION")
        if dir_fd is None:
            _need(name == "/proc" and directory, "PATH_POLICY_VIOLATION")
        else:
            _need(type(dir_fd) is int and dir_fd >= 0, "PATH_POLICY_VIOLATION")
            if directory:
                _need(re.fullmatch(r"[1-9][0-9]{0,9}", name) is not None and
                      int(name) <= 2147483647, "PATH_POLICY_VIOLATION")
            else:
                _need(name in ("stat", "status", "smaps_rollup"), "PATH_POLICY_VIOLATION")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        if directory:
            flags |= os.O_DIRECTORY
        return os.open(name, flags, dir_fd=dir_fd)

    def read(self, fd, limit):
        return os.read(fd, limit)

    def close(self, fd):
        os.close(fd)


class _Capture:
    def __init__(self, data, filesystem, clock):
        self.data, self.fs, self.clock = data, filesystem, clock
        self.config = data["config"]
        self.reasons = []
        self.last_tick = None
        self.total_bytes = 0
        self.attempts = 0
        self.open_attempts = 0
        self.stopped = False

    def reason(self, code, location, process=None):
        self.reasons.append((code, location))
        if process is not None:
            process["reason_codes"].append(code)

    def tick(self):
        try:
            value = self.clock()
        except Exception:
            raise _Violation("CLOCK_FAILURE") from None
        _integer(value, code="CLOCK_FAILURE")
        _need(self.last_tick is None or value >= self.last_tick, "CLOCK_NON_MONOTONIC")
        self.last_tick = value
        return value

    def close(self, fd, location, process=None):
        code = None
        if fd is not None:
            try:
                self.fs.close(fd)
            except Exception as exc:
                code = _exception_code(exc)
                self.reason(code, location, process)
                # Never retry a close: the descriptor could already be released.
                self.stopped = True
        return code

    def open(self, name, directory, parent=None):
        _need(not self.stopped, "CAPTURE_STOPPED")
        # Root once, then at most one directory and four leaf opens per PID/frame.
        cap = 1 + len(self.data["frame_rosters"]) * MAX_PROCESSES * 5
        _need(self.open_attempts < cap, "OPEN_ATTEMPT_CAP_EXCEEDED")
        self.open_attempts += 1
        fd = self.fs.open(name, directory=directory, dir_fd=parent)
        _need(type(fd) is int and fd >= 0, "READER_CONTRACT_VIOLATION")
        return fd

    def read(self, pidfd, pid, label, leaf, parser, location):
        record = {"label": label, "kind": leaf, "pid": pid, "status": "FAILED",
                  "start_ns": None, "end_ns": None, "byte_length": 0, "sha256": None,
                  "byte_provenance_complete": False, "read_calls": 0, "requested_limits": [],
                  "reason_codes": [], "exception_class": None}
        fd, value, raw = None, None, b""
        byte_provenance_complete = True
        try:
            _need(leaf in ("stat", "status", "smaps_rollup"), "PATH_POLICY_VIOLATION")
            _need(not self.stopped, "CAPTURE_STOPPED")
            _need(pidfd is not None, "PRIOR_IDENTITY_UNVERIFIED")
            record["start_ns"] = self.tick()
            errors = []
            try:
                remaining = self.config["max_total_bytes"] - self.total_bytes
                _need(remaining > 0, "TOTAL_BYTES_CAP_EXCEEDED")
                cap = min(self.config["max_bytes"], remaining)
                fd = self.open(leaf, False, pidfd)
                eof = False
                for _ in range(self.config["max_read_iterations"]):
                    _need(self.attempts < self.config["max_read_attempts"], "READ_ATTEMPT_CAP_EXCEEDED")
                    # Across short reads, returned bytes cannot exceed cap+1.
                    limit = cap + 1 - len(raw)
                    record["requested_limits"].append(limit)
                    self.attempts += 1
                    record["read_calls"] += 1
                    chunk = self.fs.read(fd, limit)
                    if type(chunk) is not bytes:
                        byte_provenance_complete = False
                        raise _Violation("READER_CONTRACT_VIOLATION")
                    record["byte_length"] += len(chunk)
                    self.total_bytes += len(chunk)
                    if len(chunk) > limit:
                        # Do not hash, decode or copy an unbounded callback result.
                        byte_provenance_complete = False
                        raise _Violation("READER_CONTRACT_VIOLATION")
                    raw += chunk
                    _need(len(raw) <= cap, "OVERSIZED" if cap == self.config["max_bytes"]
                          else "TOTAL_BYTES_CAP_EXCEEDED")
                    if not chunk:
                        eof = True
                        break
                _need(eof, "READ_ITERATION_CAP_EXCEEDED")
            except Exception as exc:
                code = _exception_code(exc)
                errors.append(code)
                if not isinstance(exc, _Violation):
                    record["exception_class"] = _exception_class(exc)
            finally:
                close_error = self.close(fd, location + ".close")
                if close_error:
                    errors.append(close_error)
                try:
                    record["end_ns"] = self.tick()
                except _Violation as exc:
                    errors.append(_exception_code(exc))
            if errors:
                record["reason_codes"].extend(errors[1:])
                raise _Violation(errors[0])
            value = parser(_text(raw) if leaf == "smaps_rollup" else raw)
            record["status"] = "OK"
        except Exception as exc:
            code = _exception_code(exc)
            if not isinstance(exc, _Violation):
                record["exception_class"] = _exception_class(exc)
            record["reason_codes"].append(code)
            if any(c in ("CLOCK_FAILURE", "CLOCK_NON_MONOTONIC", "READER_CONTRACT_VIOLATION",
                        "TOTAL_BYTES_CAP_EXCEEDED", "READ_ATTEMPT_CAP_EXCEEDED",
                        "READ_ITERATION_CAP_EXCEEDED", "OPEN_ATTEMPT_CAP_EXCEEDED")
                   for c in record["reason_codes"]):
                self.stopped = True
        # Hash only the exact, bounded bytes actually returned, including partial
        # reads on failures. No raw source text is ever serialized.
        if byte_provenance_complete and record["start_ns"] is not None:
            record["sha256"] = hashlib.sha256(raw).hexdigest()
            record["byte_provenance_complete"] = True
        if record["start_ns"] is None:
            record["status"] = "NOT_READ"
        for code in record["reason_codes"]:
            self.reason(code, location)
        return record, value

    def identity(self, process, value, label, location):
        if value is None:
            return
        expected = process["identity"]
        if label in ("stat_before", "stat_after"):
            process[label + "_identity"] = value
        if value["pid"] != expected["pid"]:
            self.reason("IDENTITY_CONTRADICTION", location, process)
        if value["ppid"] != expected["ppid"]:
            self.reason("PROCESS_REPARENTED", location, process)
        if "starttime_ticks" in value and value["starttime_ticks"] != expected["starttime_ticks"]:
            self.reason("PID_REUSE", location, process)
        if value["state"] in ("Z", "X", "x"):
            self.reason("PROCESS_NOT_LIVE", location, process)

    def frame(self, index, observed, root):
        start_reasons = 0 if root is None else len(self.reasons)
        location = "frames.%d" % index
        roster = self.data["roster"]
        identities = [roster["parent"]] + roster["workers"]
        expected = {p["pid"] for p in identities}
        if not roster["complete"]:
            self.reason("ROSTER_INCOMPLETE", location)
        if set(observed) - expected:
            self.reason("UNKNOWN_PROCESS", location)
        if expected - set(observed):
            self.reason("REGISTERED_PROCESS_MISSING", location)
        processes, handles = [], []
        try:
            for n, identity in enumerate(identities):
                p = {"identity": identity, "status": "INCOMPLETE", "reason_codes": [], "reads": [],
                     "stat_before_identity": None, "stat_after_identity": None,
                     "open_exception_class": None,
                     "vmrss_bytes": None, "vmhwm_bytes": None, "smaps_rollup": None}
                processes.append(p)
                fd = None
                try:
                    # Observed PIDs can flag gaps but cannot suppress registered reads.
                    _need(root is not None, "ROOT_UNAVAILABLE")
                    fd = self.open(str(identity["pid"]), True, root)
                except Exception as exc:
                    code = _exception_code(exc)
                    if not isinstance(exc, _Violation):
                        p["open_exception_class"] = _exception_class(exc)
                    self.reason(code, location + ".processes.%d.open" % n, p)
                    if code == "READER_CONTRACT_VIOLATION":
                        self.stopped = True
                handles.append(fd)
            # Frame barriers: all pre-identities, then data, then all post-identities.
            # Hold each PID directory for the entire frame; never reopen or retry.
            sequence = [("stat_before", "stat", _stat), ("status", "status", _status)]
            if self.config["smaps_rollup_policy"] == "OPTIONAL_DIAGNOSTIC":
                sequence.append(("smaps_rollup", "smaps_rollup", _smaps))
            sequence.append(("stat_after", "stat", _stat))
            for label, leaf, parser in sequence:
                for n, (p, fd) in enumerate(zip(processes, handles)):
                    loc = location + ".processes.%d.%s" % (n, label)
                    if label in ("status", "smaps_rollup") and p["reason_codes"]:
                        readfd = None
                    else:
                        readfd = fd
                    read, value = self.read(readfd, p["identity"]["pid"], label, leaf, parser, loc)
                    p["reads"].append(read)
                    p["reason_codes"].extend(read["reason_codes"])
                    if leaf in ("stat", "status"):
                        self.identity(p, value, label, loc)
                    if value is not None and label == "status":
                        p.update(vmrss_bytes=value["vmrss_bytes"], vmhwm_bytes=value["vmhwm_bytes"])
                    if value is not None and label == "smaps_rollup":
                        p["smaps_rollup"] = value
        finally:
            for n, fd in enumerate(handles):
                self.close(fd, location + ".processes.%d.close" % n, processes[n])
        reads = [r for p in processes for r in p["reads"]]
        starts = [r["start_ns"] for r in reads if r["start_ns"] is not None]
        ends = [r["end_ns"] for r in reads if r["end_ns"] is not None]
        first, last = (min(starts) if starts else None), (max(ends) if ends else None)
        skew = last - first if first is not None and last is not None else None
        if skew is not None and skew > self.config["max_read_skew_ns"]:
            self.reason("READ_SKEW_EXCEEDED", location)
        codes = sorted({c for c, _ in self.reasons[start_reasons:]})
        status = _classification(codes)
        for p in processes:
            p["status"] = status
            p["reason_codes"] = sorted(set(p["reason_codes"]))
            if codes:
                p.update(vmrss_bytes=None, vmhwm_bytes=None, smaps_rollup=None)
        return {"index": index, "status": status, "reason_codes": codes,
                "processes": processes, "observed_pids": observed,
                "roster_complete": roster["complete"], "first_read_start_ns": first,
                "last_read_end_ns": last, "read_skew_ns": skew,
                "read_window_complete": all(r["start_ns"] is not None and r["end_ns"] is not None for r in reads)}

    def frames(self):
        root, frames = None, []
        try:
            try:
                root = self.open("/proc", True)
            except Exception as exc:
                code = _exception_code(exc)
                self.reason(code, "root.open")
                self.stopped = True
            for index, observed in enumerate(self.data["frame_rosters"]):
                frames.append(self.frame(index, observed, root))
                if self.stopped:
                    break
        finally:
            close_error = self.close(root, "root.close")
            if close_error and frames:
                frame = frames[-1]
                frame["reason_codes"] = sorted(set(frame["reason_codes"] + [close_error]))
                frame["status"] = _classification(frame["reason_codes"])
                for p in frame["processes"]:
                    p.update(status=frame["status"], vmrss_bytes=None, vmhwm_bytes=None, smaps_rollup=None)
        if len(frames) != len(self.data["frame_rosters"]):
            self.reason("CAPTURE_STOPPED", "frames")
        return frames


class NativeProcfsAdapter:
    """Inert. Inject both filesystem and clock for artificial I/O.

    filesystem.open(name, *, directory, dir_fd) -> fd (exact nonnegative int)
    filesystem.read(fd, limit) -> exact bytes; b'' indicates EOF
    filesystem.close(fd) -> None
    The injected facade must be artificial and nonblocking. Python cannot
    preempt a hostile callback or stop it from performing its own unrelated I/O.
    """

    def __init__(self, filesystem=None, monotonic_ns=None):
        self._filesystem = filesystem
        self._clock = monotonic_ns

    def sample(self, request=None, *, native_opt_in=None):
        report = _envelope()
        try:
            data = _copy(request)
            _validate(data)
            injected = self._filesystem is not None or self._clock is not None
            if native_opt_in is not None:
                _need(not injected, "NATIVE_INJECTION_CONFLICT")
                _need(type(native_opt_in) is str and native_opt_in == NATIVE_OPT_IN,
                      "NATIVE_OPT_IN_REQUIRED")
                _need(data["capture_mode"] == "NATIVE", "SOURCE_ORIGIN_CONFLICT")
            if data["capture_mode"] == "NATIVE":
                _need(not injected, "NATIVE_INJECTION_CONFLICT")
                _need(type(native_opt_in) is str and native_opt_in == NATIVE_OPT_IN,
                      "NATIVE_OPT_IN_REQUIRED")
                _need(sys.platform == "linux" and all(hasattr(os, flag) for flag in
                      ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_RDONLY")), "NATIVE_UNAVAILABLE")
                filesystem, clock = _NativeIO(), time.monotonic_ns
                # This is a local, unverified native capture envelope, never an
                # attested real-source input for any predecessor verifier.
                report.update(source_kind="NATIVE_PROCFS_UNVERIFIED",
                              origin_attestation="UNVERIFIED_NATIVE_CAPTURE", clock_kind="LOCAL_MONOTONIC_NS")
            else:
                filesystem, clock = self._filesystem, self._clock
                _need(filesystem is not None and all(callable(getattr(filesystem, name, None))
                      for name in ("open", "read", "close")), "READER_NOT_CONFIGURED")
                _need(callable(clock), "CLOCK_NOT_CONFIGURED")
            report.update(run_id=data["run_id"], input_sha256=_digest(data), config=data["config"],
                          roster=data["roster"], frames_requested=len(data["frame_rosters"]))
        except _Violation as exc:
            return _finish(report, [(_exception_code(exc), "request")])
        capture = _Capture(data, filesystem, clock)
        report["frames"] = capture.frames()
        reads = [r for f in report["frames"] for p in f["processes"] for r in p["reads"]]
        starts = [r["start_ns"] for r in reads if r["start_ns"] is not None]
        ends = [r["end_ns"] for r in reads if r["end_ns"] is not None]
        report.update(read_attempts=capture.attempts, open_attempts=capture.open_attempts,
                      total_bytes=capture.total_bytes,
                      first_read_start_ns=min(starts) if starts else None,
                      last_read_end_ns=max(ends) if ends else None,
                      read_skew_ns=max(ends) - min(starts) if starts and ends else None,
                      worker_coverage="REGISTERED_ROSTER_OBSERVED" if not capture.reasons else "UNCERTAIN")
        return _finish(report, capture.reasons)
