"""B3-A artificial local provenance contract. No native facade or default I/O.

Callbacks model prebound descriptors and JSON bytes, not Linux filesystem calls.
Even consistent observations are caller-owned, injected, and nonqualifying.
"""

from dataclasses import dataclass
import errno
import hashlib
import json
import re

from scripts.benchmarks.rb_post3d_08p2e2_r2f_f2b4_native_procfs_adapter import canonical_json
from scripts.benchmarks.rb_post3d_08p2e2_r2f_f2b4_native_provenance import assess_provenance

SCHEMA = "rawibumi.local-provenance-probe.f2b4.d2b2b3a.v1"
CLOCK_DOMAIN = "INJECTED_MONOTONIC_NS"
MAX_DEPTH = 24
MAX_NODES = 200000
MAX_BYTES = 8388608
MAX_STRING = 65536
MAX_READ_BYTES = 4096
MAX_CAPTURES = 8
MAX_FRAMES = 32
MAX_PROCESSES = 64  # Includes the explicit local probe context.
MAX_READS = 260  # Two sweeps of boot, mount, and two leaves per identity.
U64 = 18446744073709551615

INVALID_CODES = (
    "INPUT_NOT_JSON", "INPUT_CAP_EXCEEDED", "SCHEMA_INVALID", "INTEGER_INVALID",
    "SOURCE_KIND_INVALID", "CLOCK_DOMAIN_INVALID", "DUPLICATE_IDENTITY", "IDENTITY_CONTRADICTION",
    "PATH_POLICY_VIOLATION", "SYMLINK_REJECTED", "DESCRIPTOR_INVALID",
    "DESCRIPTOR_CHANGED", "DESCRIPTOR_ALIAS", "MOUNT_MISMATCH", "NAMESPACE_METHOD_INVALID",
    "NAMESPACE_DESCRIPTOR_MISMATCH", "READER_CONTRACT_VIOLATION", "INVALID_UTF8",
    "DUPLICATE_FIELD", "CLOCK_FAILURE", "CLOCK_REGRESSION", "READ_WINDOW_MISMATCH",
    "REFERENCE_DIGEST_MISMATCH", "REFERENCE_INVALID", "INPUT_CHANGED", "REASON_CODE_INVALID",
)
INCOMPLETE_CODES = (
    "PERMISSION_DENIED", "PROCESS_VANISHED", "READ_FAILED", "CALLBACK_EXCEPTION",
    "BOOT_ID_CHANGED", "NAMESPACE_MISMATCH", "PID_REUSE", "PROCESS_REPARENTED",
    "UNKNOWN_PROCESS", "ROSTER_INCOMPLETE", "READ_SKEW_EXCEEDED", "STALE_READING",
    "FRAME_TIMESTAMP_MISSING", "FRAME_GAP_EXCEEDED", "COVERAGE_UNBOUNDED",
    "REFERENCE_INCOMPLETE", "REFERENCE_ROSTER_MISMATCH", "REFERENCE_ENVIRONMENT_MISMATCH", "REQUEST_INTEGRITY_UNAVAILABLE",
    "CAPTURE_REQUEST_REJECTED", "CLOCK_DOMAIN_UNCOMPARABLE",
)


@dataclass(frozen=True)
class ProbeReport:
    """Frozen serialized result; each to_dict call returns a detached tree."""

    serialized: str

    def to_dict(self):
        return json.loads(self.serialized)


class _Rejected(Exception):
    def __init__(self, code):
        self.code = code


def _need(condition, code="SCHEMA_INVALID"):
    if not condition:
        raise _Rejected(code)


def _sealed_codes(codes):
    """Discard unclassified labels without losing the fact of their rejection."""
    return {code if code in INVALID_CODES or code in INCOMPLETE_CODES else "REASON_CODE_INVALID"
            for code in codes}


def _copy(value, *, max_nodes=MAX_NODES, max_bytes=MAX_BYTES, max_depth=MAX_DEPTH):
    """Closed JSON types, bounded depth/nodes/UTF-8 bytes, no user methods."""
    budget = [0, 0]
    ancestors = set()

    def visit(item, depth):
        _need(depth <= max_depth, "INPUT_CAP_EXCEEDED")
        budget[0] += 1
        _need(budget[0] <= max_nodes, "INPUT_CAP_EXCEEDED")
        kind = type(item)
        if kind in (dict, list):
            _need(id(item) not in ancestors, "INPUT_NOT_JSON")
            _need(len(item) <= max_nodes - budget[0], "INPUT_CAP_EXCEEDED")
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
                raise _Rejected("INPUT_NOT_JSON") from None
            _need("\x00" not in item, "INPUT_NOT_JSON")
            budget[1] += size
            _need(size <= MAX_STRING and budget[1] <= max_bytes, "INPUT_CAP_EXCEEDED")
        elif kind is int:
            _need(0 <= item <= U64, "INTEGER_INVALID")
        elif kind not in (bool, type(None)):
            raise _Rejected("INPUT_NOT_JSON")
        return item

    return visit(value, 0)


def _object(value, keys):
    _need(type(value) is dict and value.keys() == set(keys))


def _int(value, low=0, high=U64):
    _need(type(value) is int and low <= value <= high, "INTEGER_INVALID")


def _list(value, maximum, minimum=0):
    _need(type(value) is list)
    _need(minimum <= len(value) <= maximum, "INPUT_CAP_EXCEEDED")


def _digest(value):
    # Match canonical_json exactly, without building an oversized serialization.
    encoder = json.JSONEncoder(sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
    digest, size = hashlib.sha256(), 0
    for chunk in encoder.iterencode(value):
        encoded = chunk.encode("utf-8")
        size += len(encoded)
        _need(size <= MAX_BYTES, "INPUT_CAP_EXCEEDED")
        digest.update(encoded)
    _need(size + 1 <= MAX_BYTES, "INPUT_CAP_EXCEEDED")
    digest.update(b"\n")
    return digest.hexdigest()


def _identity(value):
    _object(value, ("pid", "ppid", "starttime_ticks"))
    _int(value["pid"], 1, 2147483647)
    _int(value["ppid"], 0, 2147483647)
    _int(value["starttime_ticks"])
    _need(value["pid"] != value["ppid"])


def _request(value):
    _object(value, ("schema", "source_kind", "clock_domain", "context", "targets",
                    "roster_complete", "limits", "frame_windows"))
    _need(value["schema"] == SCHEMA)
    _need(value["source_kind"] == "INJECTED", "SOURCE_KIND_INVALID")
    _need(value["clock_domain"] == CLOCK_DOMAIN, "CLOCK_DOMAIN_INVALID")
    _list(value["targets"], MAX_PROCESSES - 1, 1)
    identities = [value["context"]] + value["targets"]
    for identity in identities:
        _identity(identity)
    _need(len({p["pid"] for p in identities}) == len(identities), "DUPLICATE_IDENTITY")
    _need(type(value["roster_complete"]) is bool)
    _object(value["limits"], ("max_age_ns", "max_read_skew_ns", "max_frame_gap_ns"))
    for limit in value["limits"].values():
        _int(limit)
    _list(value["frame_windows"], MAX_FRAMES, 1)
    return identities


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, "DUPLICATE_FIELD")
        result[key] = value
    return result


def _decode(raw):
    _need(type(raw) is bytes, "READER_CONTRACT_VIOLATION")
    _need(len(raw) <= MAX_READ_BYTES, "INPUT_CAP_EXCEEDED")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise _Rejected("INVALID_UTF8") from None
    try:
        value = json.loads(text, object_pairs_hook=_pairs)
    except (ValueError, RecursionError):
        raise _Rejected("INPUT_NOT_JSON") from None
    return _copy(value)


def _descriptor(value, path):
    _object(value, ("path", "st_dev", "st_ino", "mount_id", "filesystem", "mount_path",
                    "symlink", "binding", "read_method"))
    _need(value["path"] == path, "PATH_POLICY_VIOLATION")
    _need(type(value["symlink"]) is bool, "DESCRIPTOR_INVALID")
    _need(not value["symlink"], "SYMLINK_REJECTED")
    for key in ("st_dev", "st_ino", "mount_id"):
        _int(value[key], 1)
    namespace = path.endswith("/namespace")
    filesystem, mount_path = ("nsfs", "namespace_target") if namespace else ("proc", "proc")
    _need(value["filesystem"] == filesystem and value["mount_path"] == mount_path, "MOUNT_MISMATCH")
    _need(value["binding"] == "INJECTED_PREBOUND_NO_FOLLOW", "DESCRIPTOR_INVALID")
    method = "INJECTED_NAMESPACE_TARGET_DESCRIPTOR" if namespace else "INJECTED_BOUND_DESCRIPTOR"
    _need(value["read_method"] == method, "NAMESPACE_METHOD_INVALID")


def _value(value, path, desc):
    if path == "boot_id":
        _object(value, ("boot_id",))
        _need(type(value["boot_id"]) is str and re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value["boot_id"]) is not None)
    elif path == "mount":
        _object(value, ("mount_id", "filesystem", "mount_path", "descriptor_dev"))
        _int(value["mount_id"], 1)
        _int(value["descriptor_dev"], 1)
        _need(value["mount_id"] == desc["mount_id"] and value["filesystem"] == "proc" and
              value["mount_path"] == "proc" and value["descriptor_dev"] == desc["st_dev"], "MOUNT_MISMATCH")
    elif path.endswith("/identity"):
        _identity(value)
    else:
        _object(value, ("st_dev", "st_ino", "read_method"))
        _int(value["st_dev"], 1)
        _int(value["st_ino"], 1)
        _need(value["read_method"] == "INJECTED_NAMESPACE_TARGET_DESCRIPTOR", "NAMESPACE_METHOD_INVALID")
        _need((value["st_dev"], value["st_ino"]) == (desc["st_dev"], desc["st_ino"]),
              "NAMESPACE_DESCRIPTOR_MISMATCH")


def _exception(exc):
    if isinstance(exc, OSError) and exc.errno == errno.ELOOP:
        return "SYMLINK_REJECTED"
    if isinstance(exc, OSError) and exc.errno == errno.ENOTDIR:
        return "PATH_POLICY_VIOLATION"
    if isinstance(exc, PermissionError):
        return "PERMISSION_DENIED"
    if isinstance(exc, (FileNotFoundError, ProcessLookupError)):
        return "PROCESS_VANISHED"
    if isinstance(exc, OSError):
        return "READ_FAILED"
    return "CALLBACK_EXCEPTION"


class _Probe:
    def __init__(self, reader, descriptor, clock):
        self.reader, self.descriptor, self.clock = reader, descriptor, clock
        self.codes = set()
        self.reads = []
        self.last_tick = None

    def tick(self, codes):
        try:
            value = self.clock()
            _int(value)
            _need(self.last_tick is None or value >= self.last_tick, "CLOCK_REGRESSION")
            self.last_tick = value
            return value
        except _Rejected as exc:
            codes.add("CLOCK_REGRESSION" if exc.code == "CLOCK_REGRESSION" else "CLOCK_FAILURE")
        except Exception:
            codes.add("CLOCK_FAILURE")
        return None

    def read(self, path, allowlist, max_skew):
        _need(path in allowlist and len(self.reads) < MAX_READS, "PATH_POLICY_VIOLATION")
        codes = set()
        start = self.tick(codes)
        value, before, after, raw_digest = None, None, None, None
        if start is not None:
            try:
                before = _copy(self.descriptor(path), max_nodes=128, max_bytes=4096, max_depth=4)
                _descriptor(before, path)
                raw = self.reader(path, MAX_READ_BYTES + 1)
                value = _decode(raw)
                raw_digest = hashlib.sha256(raw).hexdigest()
                _value(value, path, before)
            except _Rejected as exc:
                codes.add(exc.code)
            except Exception as exc:
                codes.add(_exception(exc))
            # Recheck even after a failed read. Never retry any callback.
            if before is not None:
                try:
                    after = _copy(self.descriptor(path), max_nodes=128, max_bytes=4096, max_depth=4)
                    _descriptor(after, path)
                    _need(before == after, "DESCRIPTOR_CHANGED")
                except _Rejected as exc:
                    codes.add(exc.code)
                except Exception as exc:
                    codes.add(_exception(exc))
        end = self.tick(codes)
        if start is None or end is None:
            codes.add("COVERAGE_UNBOUNDED")
        elif end - start > max_skew:
            codes.add("READ_SKEW_EXCEEDED")
        codes = _sealed_codes(codes)
        self.codes.update(codes)
        self.reads.append({"source": path, "start_ns": start, "end_ns": end,
                           "failure_codes": sorted(codes), "provenance": "INJECTED_LOCAL_PROBE",
                           "sha256": raw_digest, "descriptor_stable": before is not None and before == after and not codes})
        return None if codes else (value, before)


def _windows(windows, maximum_gap, codes):
    """Missing endpoints never reset the last known endpoint or prove coverage."""
    previous = None
    for window in windows:
        _object(window, ("start_ns", "end_ns"))
        start, end = window["start_ns"], window["end_ns"]
        for tick in (start, end):
            if tick is not None:
                _int(tick)
        if start is None or end is None:
            codes.update(("FRAME_TIMESTAMP_MISSING", "COVERAGE_UNBOUNDED"))
        if start is not None and end is not None:
            _need(end >= start, "READ_WINDOW_MISMATCH")
        if previous is not None:
            for tick in (start, end):
                if tick is not None:
                    _need(tick >= previous, "CLOCK_REGRESSION")
            if start is not None and start - previous > maximum_gap:
                codes.add("FRAME_GAP_EXCEEDED")
        if end is not None:
            previous = end


def _reference(reference, targets, windows, codes):
    """Check copies with the unchanged B2 verifier; this never authenticates I/O."""
    if reference is None:
        return None, [], []
    _object(reference, ("payload", "sha256"))
    payload = reference["payload"]
    _need(type(reference["sha256"]) is str and reference["sha256"] == _digest(payload), "REFERENCE_DIGEST_MISMATCH")
    _object(payload, ("captures", "requests", "evidence"))
    for values in payload.values():
        _list(values, MAX_CAPTURES, 1)
    _need(len(payload["captures"]) == len(payload["requests"]) == len(payload["evidence"]), "REFERENCE_INVALID")
    assessment = assess_provenance(payload["captures"], payload["requests"], payload["evidence"]).to_dict()
    if assessment["invalid_reason_codes"]:
        codes.add("REFERENCE_INVALID")
    if assessment["incomplete_reason_codes"]:
        codes.add("REFERENCE_INCOMPLETE")
    comparisons, environments = [], []
    for capture in payload["captures"]:
        _need(type(capture) is dict, "REFERENCE_INVALID")
        if capture.get("input_sha256") is None:
            codes.update(("REQUEST_INTEGRITY_UNAVAILABLE", "CAPTURE_REQUEST_REJECTED"))
        # B2's rejected-request early return deliberately has no semantic summary.
        if assessment["invalid_reason_codes"]:
            continue
        roster = capture["roster"]
        identities = [roster["parent"]] + roster["workers"]
        actual = [{k: p[k] for k in ("pid", "ppid", "starttime_ticks")} for p in identities]
        if sorted(actual, key=lambda p: p["pid"]) != sorted(targets, key=lambda p: p["pid"]):
            codes.add("REFERENCE_ROSTER_MISMATCH")
        frame_windows = [{"start_ns": f["first_read_start_ns"], "end_ns": f["last_read_end_ns"]}
                         for f in capture["frames"]]
        comparisons.append((capture["clock_kind"], frame_windows))
        if capture["clock_kind"] != CLOCK_DOMAIN:
            codes.add("CLOCK_DOMAIN_UNCOMPARABLE")
    if comparisons and all(domain == CLOCK_DOMAIN for domain, _ in comparisons):
        combined = [window for _, frames in comparisons for window in frames]
        _list(combined, MAX_FRAMES, 1)
        if combined != windows:
            codes.add("READ_WINDOW_MISMATCH")
    if not assessment["invalid_reason_codes"]:
        for evidence in payload["evidence"]:
            for environment in evidence["environments"]:
                expected = {}
                for key in ("boot_id", "namespace_device", "namespace_inode", "mount_id", "mount_type"):
                    field = environment[key]
                    if field["value"] is None or field["status"] in ("UNAVAILABLE", "INCONSISTENT"):
                        codes.add("REFERENCE_INCOMPLETE")
                    else:
                        expected[key] = field["value"]
                environments.append(expected)
    return _digest(payload), comparisons, environments


def probe_local_provenance(request, *, reader, descriptor, clock, reference=None):
    """Execute at most 260 injected reads, 520 descriptor calls and 521 ticks.

    reader(relative_name, 4097) -> bytes (at most 4096 accepted).
    descriptor(relative_name) -> closed prebound metadata; clock() -> u64 ns.
    No callback defaults, native facade, traversal, retries, or discovery exist.
    Exception messages and caller labels are never emitted. BaseException escapes.
    """
    probe = _Probe(reader, descriptor, clock)
    request_digest, reference_digest = None, None
    context_pid, target_pids = None, []
    context_identity, target_identities = None, []
    try:
        data, ref = _copy([request, reference])
        request_digest = _digest(data)
        identities = _request(data)
        _need(callable(reader) and callable(descriptor) and callable(clock), "READER_CONTRACT_VIOLATION")
        context_pid = data["context"]["pid"]
        target_pids = [p["pid"] for p in data["targets"]]
        context_identity, target_identities = data["context"], data["targets"]
        limits = data["limits"]
        if not data["roster_complete"]:
            probe.codes.add("ROSTER_INCOMPLETE")
        _windows(data["frame_windows"], limits["max_frame_gap_ns"], probe.codes)
        reference_digest, reference_windows, environments = _reference(ref, data["targets"], data["frame_windows"], probe.codes)
        if reference_windows and all(domain == CLOCK_DOMAIN for domain, _ in reference_windows):
            combined = [window for _, frames in reference_windows for window in frames]
            _windows(combined, limits["max_frame_gap_ns"], probe.codes)
        else:
            for _, windows in reference_windows:
                _windows(windows, limits["max_frame_gap_ns"], probe.codes)
        paths = ["boot_id", "mount"]
        for identity in identities:
            paths.extend((f"pids/{identity['pid']}/identity", f"pids/{identity['pid']}/namespace"))
        allowlist = frozenset(paths)
        sweeps = []
        for _ in range(2):
            sweeps.append({path: probe.read(path, allowlist, limits["max_read_skew_ns"]) for path in paths})
        boot, namespace, mount, device = None, None, None, None
        mount_identities = {}
        device_filesystems = {}
        descriptors_seen = {}
        namespace_descriptors = set()
        for sweep in sweeps:
            for path, observation in sweep.items():
                if observation is None:
                    continue
                value, desc = observation
                # A mount cannot denote both procfs and nsfs, or two devices.
                # Namespace metadata describes the prebound nsfs target only;
                # it does not supply a procfs link-location identity or binding.
                mount_identity = (desc["st_dev"], desc["filesystem"])
                prior_mount_identity = mount_identities.setdefault(desc["mount_id"], mount_identity)
                if prior_mount_identity != mount_identity:
                    probe.codes.add("MOUNT_MISMATCH")
                # Different mount IDs cannot make one device both procfs and nsfs.
                prior_filesystem = device_filesystems.setdefault(desc["st_dev"], desc["filesystem"])
                if prior_filesystem != desc["filesystem"]:
                    probe.codes.add("MOUNT_MISMATCH")
                descriptor_identity = (desc["st_dev"], desc["st_ino"])
                if not path.endswith("/namespace"):
                    if mount is None:
                        mount = desc["mount_id"]
                    if desc["mount_id"] != mount:
                        probe.codes.add("MOUNT_MISMATCH")
                    prior_path = descriptors_seen.setdefault(descriptor_identity, path)
                    if prior_path != path:
                        probe.codes.add("DESCRIPTOR_ALIAS")
                    if device is None:
                        device = desc["st_dev"]
                    if desc["st_dev"] != device:
                        probe.codes.add("MOUNT_MISMATCH")
                else:
                    namespace_descriptors.add(descriptor_identity)
                if path == "boot_id":
                    if boot is not None and boot != value:
                        probe.codes.add("BOOT_ID_CHANGED")
                    boot = value
                elif path.endswith("/namespace"):
                    if namespace is not None and namespace != value:
                        probe.codes.add("NAMESPACE_MISMATCH")
                    namespace = value
                elif path.endswith("/identity"):
                    expected = next(p for p in identities if path == f"pids/{p['pid']}/identity")
                    for key, code in (("pid", "IDENTITY_CONTRADICTION"), ("ppid", "PROCESS_REPARENTED"),
                                      ("starttime_ticks", "PID_REUSE")):
                        if value[key] != expected[key]:
                            probe.codes.add(code)
        if namespace_descriptors & descriptors_seen.keys():
            probe.codes.add("DESCRIPTOR_ALIAS")
        observed_environment = {"boot_id": boot["boot_id"] if boot else None,
                                "namespace_device": namespace["st_dev"] if namespace else None,
                                "namespace_inode": namespace["st_ino"] if namespace else None,
                                "mount_id": mount, "mount_type": "proc"}
        for expected in environments:
            if any(observed_environment[key] != value for key, value in expected.items()):
                probe.codes.add("REFERENCE_ENVIRONMENT_MISMATCH")
        # Compare descriptor identity across sweeps as well as across each read.
        for path in paths:
            first, last = sweeps[0][path], sweeps[1][path]
            if first is not None and last is not None and first[1] != last[1]:
                probe.codes.add("DESCRIPTOR_CHANGED")
        now = probe.tick(probe.codes)
        if now is None:
            probe.codes.add("COVERAGE_UNBOUNDED")
        else:
            ticks = [r["start_ns"] for r in probe.reads if r["start_ns"] is not None]
            ticks.extend(w[k] for w in data["frame_windows"] for k in ("start_ns", "end_ns") if w[k] is not None)
            for tick in ticks:
                if tick > now:
                    probe.codes.add("CLOCK_REGRESSION")
                elif now - tick > limits["max_age_ns"]:
                    probe.codes.add("STALE_READING")
        # Callbacks may mutate caller-owned envelopes. Recopy within the same caps.
        current_data, current_ref = _copy([request, reference])
        _need(_digest(current_data) == request_digest and _digest(current_ref) == _digest(ref), "INPUT_CHANGED")
    except _Rejected as exc:
        probe.codes.add(exc.code)
    probe.codes = _sealed_codes(probe.codes)
    invalid = sorted(probe.codes & set(INVALID_CODES))
    incomplete = sorted(probe.codes & set(INCOMPLETE_CODES))
    result = {
        "schema": SCHEMA + ".report", "source_kind": "INJECTED_LOCAL_PROBE",
        "qualification": "NONQUALIFYING", "outcome": "INVALID" if invalid else "INCOMPLETE" if incomplete else "CONSISTENT",
        "trust_level": "CALLER_ASSERTED_ONLY" if invalid else "INJECTED_LOCAL_PROBE",
        "clock_domain": CLOCK_DOMAIN, "context_pid": context_pid, "target_pids": target_pids,
        "context_identity": context_identity, "target_identities": target_identities,
        "input_sha256": request_digest, "reference_sha256": reference_digest,
        "reason_codes": sorted(probe.codes), "invalid_reason_codes": invalid,
        "incomplete_reason_codes": incomplete, "reads": probe.reads,
        "native_adapter": "NOT_IMPLEMENTED", "independent_trust_root_gate": "NOT_IMPLEMENTED",
        "independent_verification": "REQUIRED_NOT_PERFORMED", "procfs_mount_authenticated": False,
        "namespace_authenticated": False, "mount_namespace_binding": "UNVERIFIED",
        "frame_coverage": "UNBOUNDED" if probe.codes else "CALLER_ASSERTED_WINDOWS_ONLY",
        "production_memory_qualification": "INCONCLUSIVE", "production_chronological_peak": "NOT_OBSERVED",
        "production_workload_measured": False, "holder_release": "NOT_ESTABLISHED",
        "rss_reclamation": "NOT_ESTABLISHED", "worker_discovery": "NOT_ESTABLISHED",
        "worker_absence_proven": False, "atomic_snapshot": False,
    }
    return ProbeReport(canonical_json(result))
