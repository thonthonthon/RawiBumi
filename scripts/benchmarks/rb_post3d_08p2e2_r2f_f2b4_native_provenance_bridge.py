"""B0 artificial acquisition bridge. Imports/construction never acquire evidence.

Only explicitly injected symbolic callbacks execute. This module has no native
adapter, filesystem, process, discovery, real-clock or production capability.
See the companion validation document for the closed callback protocol.
"""

from dataclasses import dataclass
from types import MethodType
import errno
import hashlib
import json
import re

SCHEMA = "rawibumi.native-provenance-bridge.d2b2b3b0.v1"
INJECTED_TEST_ONLY = "INJECTED_TEST_ONLY"
NATIVE_LOCAL_UNVERIFIED = "NATIVE_LOCAL_UNVERIFIED"  # Reserved, never a result.
CLOCK_DOMAIN = "INJECTED_MONOTONIC_NS"
U64 = (1 << 64) - 1
MAX_PROCESSES = 16
MAX_DEPTH = 12
MAX_NODES = 2048
MAX_BYTES = 16384
MAX_RAW_BYTES = 4096
MAX_READS = 4 * (2 + 3 * MAX_PROCESSES)
MAX_ELAPSED_NS = 1000000000

INVALID_CODES = (
    "NATIVE_MODE_DENIED", "SCHEMA_INVALID", "INPUT_CAP_EXCEEDED", "INPUT_NOT_JSON",
    "INTEGER_INVALID", "ORIGIN_INVALID", "CALLBACK_CONTRACT_INVALID", "PATH_POLICY_VIOLATION",
    "SYMLINK_SUBSTITUTION", "DESCRIPTOR_INVALID", "DESCRIPTOR_CHANGED", "DESCRIPTOR_ALIAS",
    "MOUNT_CONTRADICTION", "NAMESPACE_CONTRADICTION", "IDENTITY_SUBSTITUTION",
    "SOURCE_DIGEST_MISMATCH", "INPUT_CHANGED", "REASON_CODE_INVALID", "COUNTER_ROLLBACK",
    "CLOCK_FAILURE", "CLOCK_REGRESSION",
)
INCOMPLETE_CODES = (
    "SOURCE_ALIAS", "MISSING_WORKER", "FRAME_MISSING", "STALE_HANDLE", "PERMISSION_DENIED",
    "READ_FAILED", "CALLBACK_EXCEPTION", "CLOSE_FAILED", "PID_REUSE", "PROCESS_REPARENTED",
    "BOOT_ID_CHANGED", "SOURCE_DISAGREEMENT", "STALE_READING", "READ_SKEW_EXCEEDED",
    "READ_GAP_EXCEEDED", "ELAPSED_CAP_EXCEEDED",
)
PROVIDER_ERRORS = ("STALE_HANDLE", "PERMISSION_DENIED", "READ_FAILED")


class _Rejected(Exception):
    def __init__(self, code):
        self.code = code


def _need(condition, code="SCHEMA_INVALID"):
    if not condition:
        raise _Rejected(code)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _copy(value, *, raw=False):
    """Copy exact built-in bounded types; never invoke caller serialization."""
    nodes, size, ancestors = 0, 0, set()

    def visit(item, depth):
        nonlocal nodes, size
        nodes += 1
        _need(nodes <= MAX_NODES and depth <= MAX_DEPTH, "INPUT_CAP_EXCEEDED")
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
            _need(len(item) <= MAX_BYTES, "INPUT_CAP_EXCEEDED")
            try:
                size += len(item.encode("utf-8"))
            except UnicodeError:
                raise _Rejected("INPUT_NOT_JSON") from None
            _need("\x00" not in item, "INPUT_NOT_JSON")
        elif kind is bytes and raw:
            _need(len(item) <= MAX_RAW_BYTES, "INPUT_CAP_EXCEEDED")
            size += len(item)
        elif kind is int:
            _integer(item)
        elif kind not in (bool, type(None)):
            raise _Rejected("INPUT_NOT_JSON")
        size += 8  # Bound structural/primitive overhead as well as strings.
        _need(size <= MAX_BYTES, "INPUT_CAP_EXCEEDED")
        return item

    return visit(value, 0)


def _object(value, keys):
    _need(type(value) is dict and value.keys() == set(keys))


def _exact(left, right):
    """Type-sensitive equality for already bounded, copied trees (1 != true)."""
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_exact(left[k], right[k]) for k in left)
    if type(left) is list:
        return len(left) == len(right) and all(_exact(a, b) for a, b in zip(left, right))
    return left == right


def _integer(value, low=0, high=U64):
    _need(type(value) is int and low <= value <= high, "INTEGER_INVALID")


def _label(value):
    _need(type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) is not None)


def _caller_label(value):
    _label(value)
    # Labels are untrusted display text, never origin or qualification claims.
    # Ignore permitted separators and case, including inside authority words.
    normalized = value.upper().replace("_", "").replace("-", "")
    reserved = (
        "NATIVE", "AUTHENTIC", "ATTEST", "QUALIF", "VERIFIED", "CORROBORAT",
        "INJECTEDTESTONLY", "INJECTEDMONOTONICNS", "NOTESTABLISHED", "NOTIMPLEMENTED",
        "INCONCLUSIVE", "NOTOBSERVED", "CALLERCONFIGUREDONLY", "ALIASDETECTED",
        "NOTACQUIRED", "SEQUENTIALNONATOMIC", "CONSISTENT", "INCOMPLETE", "INVALID", "AGREES",
    )
    _need(not any(token in normalized for token in reserved), "ORIGIN_INVALID")


@dataclass(frozen=True)
class Handle:
    """Opaque artificial lease. Token has no path or operating-system meaning."""

    token: str

    def __post_init__(self):
        _label(self.token)


@dataclass(frozen=True)
class Operation:
    action: str
    path_id: str
    sweep: int
    handle: object = None
    max_bytes: int = 0


@dataclass(frozen=True)
class Provider:
    provider_id: str
    source_id: str
    fixture_id: str
    callback: object
    declared_origin: str = INJECTED_TEST_ONLY


@dataclass(frozen=True)
class BridgeReport:
    serialized: str

    def to_dict(self):
        return json.loads(self.serialized)


def _identity(value):
    _object(value, ("pid", "ppid", "starttime_ticks"))
    _integer(value["pid"], 1, 2147483647)
    _integer(value["ppid"], 0, 2147483647)
    _integer(value["starttime_ticks"])
    _need(value["pid"] != value["ppid"])


def _same_identity(observed, expected):
    _identity(observed)
    _need(observed["pid"] == expected["pid"], "IDENTITY_SUBSTITUTION")
    _need(observed["starttime_ticks"] == expected["starttime_ticks"], "PID_REUSE")
    _need(observed["ppid"] == expected["ppid"], "PROCESS_REPARENTED")


def _request(request, roster):
    _object(request, ("schema", "mode", "native_opt_in", "clock_domain", "sweeps", "limits"))
    _need(request["mode"] == INJECTED_TEST_ONLY and request["native_opt_in"] is False,
          "NATIVE_MODE_DENIED")
    _need(request["schema"] == SCHEMA and request["clock_domain"] == CLOCK_DOMAIN)
    _need(type(request["sweeps"]) is int and request["sweeps"] == 2)
    _object(request["limits"], ("max_elapsed_ns", "max_read_ns", "max_gap_ns", "max_age_ns", "max_source_skew_ns"))
    for value in request["limits"].values():
        _integer(value, 1, MAX_ELAPSED_NS)
    _need(type(roster) is list)
    _need(1 <= len(roster) <= MAX_PROCESSES, "INPUT_CAP_EXCEEDED")
    for value in roster:
        _identity(value)
    _need(len({value["pid"] for value in roster}) == len(roster))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, "SCHEMA_INVALID")
        result[key] = value
    return result


def _payload(raw):
    try:
        return _copy(json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs))
    except (ValueError, UnicodeError, RecursionError):
        raise _Rejected("INPUT_NOT_JSON") from None


def _descriptor(value, path, identity):
    _object(value, ("path_id", "role", "st_dev", "st_ino", "mount_id", "filesystem",
                    "symlink", "binding", "identity"))
    _need(value["path_id"] == path, "PATH_POLICY_VIOLATION")
    target, link = path.endswith("/ns_target"), path.endswith("/ns_link")
    role = "NSFS_TARGET" if target else "PROCFS_LINK_LOCATION" if link else "PROCFS_OBJECT"
    _need(value["role"] == role, "DESCRIPTOR_INVALID")
    _need(type(value["symlink"]) is bool and value["symlink"] is link, "SYMLINK_SUBSTITUTION")
    _need(value["filesystem"] == ("nsfs" if target else "proc"), "MOUNT_CONTRADICTION")
    _need(value["binding"] == "INJECTED_DESCRIPTOR_RELATIVE_NO_FOLLOW", "DESCRIPTOR_INVALID")
    for key in ("st_dev", "st_ino", "mount_id"):
        _integer(value[key], 1)
    if identity is None:
        _need(value["identity"] is None, "IDENTITY_SUBSTITUTION")
    else:
        _same_identity(value["identity"], identity)


def _value(value, path, desc, identity):
    if path == "boot_id":
        _object(value, ("boot_id",))
        _need(type(value["boot_id"]) is str and re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value["boot_id"]) is not None)
    elif path == "proc_mount":
        _object(value, ("mount_id", "st_dev", "filesystem"))
        _integer(value["mount_id"], 1)
        _integer(value["st_dev"], 1)
        _need(all(value[k] == desc[k] for k in value), "MOUNT_CONTRADICTION")
    elif path.endswith("/identity"):
        _object(value, ("identity", "cpu_ticks", "vmhwm_kib", "rss_kib"))
        _same_identity(value["identity"], identity)
        for key in ("cpu_ticks", "vmhwm_kib", "rss_kib"):
            _integer(value[key])
    elif path.endswith("/ns_link"):
        _object(value, ("namespace_inode",))
        _integer(value["namespace_inode"], 1)
    else:
        _object(value, ("st_dev", "st_ino"))
        for key in value:
            _integer(value[key], 1)
            _need(value[key] == desc[key], "NAMESPACE_CONTRADICTION")


def _exception(exc, action, identity):
    if isinstance(exc, OSError):
        if exc.errno == errno.ELOOP:
            return "SYMLINK_SUBSTITUTION"
        if exc.errno == errno.ENOTDIR:
            return "PATH_POLICY_VIOLATION"
        if exc.errno == errno.EACCES:
            return "PERMISSION_DENIED"
        if exc.errno in (errno.ENOENT, errno.ESRCH):
            if action == "OPEN":
                return "MISSING_WORKER" if identity is not None else "FRAME_MISSING"
            return "STALE_HANDLE"
        return "READ_FAILED"
    return "CALLBACK_EXCEPTION"


def _sealed(codes):
    return {code if code in INVALID_CODES + INCOMPLETE_CODES else "REASON_CODE_INVALID" for code in codes}


def _error_entry(action, code, exc):
    number = exc.errno if isinstance(exc, OSError) else None
    return {"action": action, "reason_code": next(iter(_sealed({code}))),
            "errno": number if type(number) is int and 0 <= number <= 2147483647 else None}


class _Acquisition:
    def __init__(self, providers, clock, limits):
        self.providers, self.clock, self.limits = providers, clock, limits
        self.codes, self.reads = set(), []
        self.last_tick = self.first_tick = self.last_end = None
        self.sequence, self.handles = {}, {}
        self.objects, self.retained = {}, []

    def tick(self):
        try:
            tick = self.clock()
            _integer(tick)
            _need(self.last_tick is None or tick >= self.last_tick, "CLOCK_REGRESSION")
            if self.first_tick is None:
                self.first_tick = tick
            self.last_tick = tick
            _need(tick - self.first_tick <= self.limits["max_elapsed_ns"], "ELAPSED_CAP_EXCEEDED")
            return tick
        except _Rejected as exc:
            self.codes.add(exc.code if exc.code in ("CLOCK_REGRESSION", "ELAPSED_CAP_EXCEEDED") else "CLOCK_FAILURE")
        except Exception:
            self.codes.add("CLOCK_FAILURE")
        return None

    def retain(self, original, provider_index):
        snapshot = _copy(original, raw=True)

        def remember(value):
            if type(value) in (dict, list):
                previous = self.objects.get(id(value))
                if previous is not None and previous != provider_index:
                    self.codes.add("SOURCE_ALIAS")
                self.objects[id(value)] = provider_index
                for child in value.values() if type(value) is dict else value:
                    remember(child)

        remember(original)
        # Strong references prevent id reuse and allow final mutation checks.
        self.retained.append((original, snapshot))
        return snapshot

    def read(self, provider_index, sweep, path, identity):
        _need(len(self.reads) < MAX_READS, "INPUT_CAP_EXCEEDED")
        callback = self.providers[provider_index].callback
        record = {"provider_index": provider_index, "sweep": sweep, "path_id": path,
                  "clock_domain": CLOCK_DOMAIN, "start_ns": None, "end_ns": None,
                  "descriptor_before": None, "descriptor_after": None, "payload": None,
                  "sha256": None, "payload_sha256": None, "method": None,
                  "declared_sha256": None, "raw_byte_count": None,
                  "declared_origin": None, "sequence": None, "provider_status": None,
                  "provider_reason": None, "status": "FAILED", "reason_codes": []}
        record["operation_errors"] = []
        self.reads.append(record)
        codes, handle, pending = set(), None, None
        start = self.tick()
        record["start_ns"] = start
        if start is None:
            record["reason_codes"] = sorted(self.codes & {"CLOCK_FAILURE", "CLOCK_REGRESSION", "ELAPSED_CAP_EXCEEDED"})
            return record
        if self.last_end is not None and start - self.last_end > self.limits["max_gap_ns"]:
            codes.add("READ_GAP_EXCEEDED")
        action = "OPEN"
        try:
            obtained = callback(Operation("OPEN", path, sweep))
            _need(type(obtained) is Handle, "CALLBACK_CONTRACT_INVALID")
            handle = obtained  # Register before metadata/read validation.
            _label(handle.token)
            owner = self.handles.get(handle.token)
            if owner is not None and owner != provider_index:
                codes.add("SOURCE_ALIAS")
            self.handles[handle.token] = provider_index
            action = "DESCRIBE"
            desc = self.retain(callback(Operation(action, path, sweep, handle)), provider_index)
            _descriptor(desc, path, identity)
            record["descriptor_before"] = desc
            action = "READ"
            original = callback(Operation(action, path, sweep, handle, MAX_RAW_BYTES + 1))
            _need(original is not None, "FRAME_MISSING")
            envelope = self.retain(original, provider_index)
            _object(envelope, ("payload", "raw", "sha256", "method", "declared_origin", "sequence", "status", "reason"))
            _need(envelope["declared_origin"] == INJECTED_TEST_ONLY, "ORIGIN_INVALID")
            record["declared_origin"] = INJECTED_TEST_ONLY
            _need(envelope["method"] in ("INJECTED_STRUCTURED", "INJECTED_JSON_BYTES"))
            record["method"] = envelope["method"]
            _integer(envelope["sequence"])
            sequence = envelope["sequence"]
            record["sequence"] = sequence
            previous = self.sequence.get(provider_index)
            if previous is not None:
                _need(sequence >= previous, "COUNTER_ROLLBACK")
                _need(sequence != previous, "STALE_READING")
            self.sequence[provider_index] = sequence
            _need(envelope["status"] in ("OK", "ERROR"), "REASON_CODE_INVALID")
            record["provider_status"] = envelope["status"]
            if envelope["status"] == "ERROR":
                _need(envelope["reason"] in PROVIDER_ERRORS, "REASON_CODE_INVALID")
                _need(envelope["payload"] is envelope["raw"] is envelope["sha256"] is None)
                record["provider_reason"] = envelope["reason"]
                raise _Rejected(envelope["reason"])
            _need(envelope["reason"] is None, "REASON_CODE_INVALID")
            payload, raw = envelope["payload"], envelope["raw"]
            _value(payload, path, desc, identity)
            if envelope["method"] == "INJECTED_JSON_BYTES":
                _need(type(raw) is bytes, "CALLBACK_CONTRACT_INVALID")
                digest = hashlib.sha256(raw).hexdigest()
            else:
                _need(raw is None, "CALLBACK_CONTRACT_INVALID")
                digest = _digest(payload)
            claimed = envelope["sha256"]
            if type(claimed) is str and re.fullmatch(r"[0-9a-f]{64}", claimed) is not None:
                record["declared_sha256"] = claimed
            record.update(payload=payload, sha256=digest, payload_sha256=_digest(payload),
                          raw_byte_count=None if raw is None else len(raw))
            if raw is not None:
                _need(_exact(_payload(raw), payload), "SOURCE_DIGEST_MISMATCH")
            _need(claimed == digest, "SOURCE_DIGEST_MISMATCH")
        except _Rejected as exc:
            codes.add(exc.code)
            record["operation_errors"].append(_error_entry(action, exc.code, exc))
        except Exception as exc:
            code = _exception(exc, action, identity)
            codes.add(code)
            record["operation_errors"].append(_error_entry(action, code, exc))
        except BaseException as exc:
            pending = exc
        finally:
            if handle is not None:
                # Always recheck and close once, including during BaseException
                # unwinding. A cleanup failure cannot replace the original.
                for cleanup in ("DESCRIBE", "CLOSE"):
                    try:
                        result = callback(Operation(cleanup, path, sweep, handle))
                        if cleanup == "DESCRIBE":
                            after = self.retain(result, provider_index)
                            _descriptor(after, path, identity)
                            record["descriptor_after"] = after
                            if record["descriptor_before"] is not None:
                                _need(record["descriptor_before"] == after, "DESCRIPTOR_CHANGED")
                        else:
                            _need(result is None, "CALLBACK_CONTRACT_INVALID")
                    except _Rejected as exc:
                        codes.add(exc.code)
                        record["operation_errors"].append(_error_entry(cleanup, exc.code, exc))
                    except Exception as exc:
                        code = "CLOSE_FAILED" if cleanup == "CLOSE" else _exception(exc, cleanup, identity)
                        codes.add(code)
                        record["operation_errors"].append(_error_entry(cleanup, code, exc))
                    except BaseException as exc:
                        if pending is None:
                            pending = exc
        if pending is not None:
            raise pending
        end = self.tick()
        record["end_ns"] = end
        if end is not None:
            self.last_end = end
            if end - start > self.limits["max_read_ns"]:
                codes.add("READ_SKEW_EXCEEDED")
        else:
            codes.update(self.codes & {"CLOCK_FAILURE", "CLOCK_REGRESSION", "ELAPSED_CAP_EXCEEDED"})
        codes = _sealed(codes)
        record["reason_codes"] = sorted(codes)
        record["status"] = "OK" if not codes and end is not None else "FAILED"
        self.codes.update(codes)
        return record


def _alias(left, right):
    if left.callback is right.callback:
        return True
    # Do not execute arbitrary callable-object __getattribute__ methods during
    # preflight. Only actual Python bound methods have this identity route.
    lself = left.callback.__self__ if type(left.callback) is MethodType else None
    rself = right.callback.__self__ if type(right.callback) is MethodType else None
    return ((lself is not None and (lself is rself or lself is right.callback))
            or (rself is not None and rself is left.callback) or left.provider_id == right.provider_id
            or left.source_id == right.source_id or left.fixture_id == right.fixture_id)


def _correlate(reads, roster, limits, codes):
    mounts, devices, stable, descriptors, counters = {}, {}, {}, {}, {}
    good = {}
    for record in reads:
        if record["status"] != "OK":
            continue
        p, s, path = record["provider_index"], record["sweep"], record["path_id"]
        desc, payload = record["descriptor_before"], record["payload"]
        good[p, s, path] = record
        mid, dev, fs = desc["mount_id"], desc["st_dev"], desc["filesystem"]
        if (mid in mounts and mounts[mid] != (dev, fs)) or (dev in devices and devices[dev] != fs):
            codes.add("MOUNT_CONTRADICTION")
        mounts[mid], devices[dev] = (dev, fs), fs
        identity_key = (dev, desc["st_ino"])
        previous_descriptor = descriptors.get(identity_key)
        if previous_descriptor is not None and previous_descriptor[0] != path:
            if (previous_descriptor[1], desc["role"]) != ("NSFS_TARGET", "NSFS_TARGET"):
                codes.add("DESCRIPTOR_ALIAS")
        descriptors[identity_key] = (path, desc["role"])
        if path in stable:
            old_desc, old_payload = stable[path]
            if old_desc != desc:
                codes.add("DESCRIPTOR_CHANGED")
            if path == "boot_id" and old_payload != payload:
                codes.add("BOOT_ID_CHANGED")
            elif "/ns_" in path and old_payload != payload:
                codes.add("NAMESPACE_CONTRADICTION")
        stable[path] = (desc, payload)
        if path.endswith("/identity"):
            previous = counters.get((p, path))
            if previous is not None and any(payload[k] < previous[k] for k in ("cpu_ticks", "vmhwm_kib")):
                codes.add("COUNTER_ROLLBACK")
            counters[p, path] = payload
        if p == 1:
            other = good.get((0, s, path))
            if other is not None and (other["payload"] != payload or other["descriptor_before"] != desc):
                codes.add("SOURCE_DISAGREEMENT")
            if other is not None and record["end_ns"] - other["start_ns"] > limits["max_source_skew_ns"]:
                codes.add("READ_SKEW_EXCEEDED")
    # A cross-provider timeline requires complete, agreeing boot/namespace
    # evidence. Missing or incomparable scopes never establish comparability.
    boots = [good.get((p, s, "boot_id")) for s in range(2) for p in range(2)]
    same_boot = all(boots) and all(r["payload"] == boots[0]["payload"] for r in boots)
    for identity in roster:
        prefix = f"pids/{identity['pid']}/"
        targets = [good.get((p, s, prefix + "ns_target")) for s in range(2) for p in range(2)]
        if not same_boot or not all(targets) or any(r["payload"] != targets[0]["payload"] for r in targets):
            continue
        previous = None
        # reads are appended in sequential acquisition/bridge-clock order;
        # provider sequence counters cannot order observations across sources.
        for record in reads:
            if record["status"] != "OK" or record["path_id"] != prefix + "identity":
                continue
            payload = record["payload"]
            # Successful identity validation pins PID and starttime to roster.
            if previous is not None and any(payload[k] < previous[k] for k in ("cpu_ticks", "vmhwm_kib")):
                codes.add("COUNTER_ROLLBACK")
            previous = payload
    for p in range(2):
        for s in range(2):
            root = good.get((p, s, "proc_mount"))
            for (provider, sweep, path), record in good.items():
                if (provider, sweep) != (p, s):
                    continue
                desc = record["descriptor_before"]
                if root is not None and desc["filesystem"] == "proc":
                    rd = root["descriptor_before"]
                    if (desc["mount_id"], desc["st_dev"]) != (rd["mount_id"], rd["st_dev"]):
                        codes.add("MOUNT_CONTRADICTION")
            for identity in roster:
                prefix = f"pids/{identity['pid']}/"
                link, target = good.get((p, s, prefix + "ns_link")), good.get((p, s, prefix + "ns_target"))
                if link and target and link["payload"]["namespace_inode"] != target["payload"]["st_ino"]:
                    codes.add("NAMESPACE_CONTRADICTION")


def acquire_provenance_bridge(roster, request, *, providers, clock):
    """Acquire two sweeps from exactly two artificial providers, never native.

    All callbacks and the clock are mandatory. Ordinary callback exceptions are
    failed evidence; BaseException escapes after closing an obtained handle.
    """
    codes, reads, provider_labels, identities = set(), [], [], []
    request_digest, acquisition = None, None
    try:
        # Denial precedes even clock/provider validation and execution.
        if type(request) is dict:
            mode = request.get("mode")
            _need(type(mode) is str and mode == INJECTED_TEST_ONLY and request.get("native_opt_in") is False,
                  "NATIVE_MODE_DENIED")
        data, copied_roster = _copy([request, roster])
        _request(data, copied_roster)
        identities = copied_roster
        request_digest = _digest([data, identities])
        _need(type(providers) in (tuple, list) and len(providers) == 2, "CALLBACK_CONTRACT_INVALID")
        _need(callable(clock), "CALLBACK_CONTRACT_INVALID")
        for provider in providers:
            _need(type(provider) is Provider and callable(provider.callback), "CALLBACK_CONTRACT_INVALID")
            _need(type(provider.declared_origin) is str and provider.declared_origin == INJECTED_TEST_ONLY,
                  "ORIGIN_INVALID")
            for label in (provider.provider_id, provider.source_id, provider.fixture_id):
                _caller_label(label)
            provider_labels.append({"provider_id": provider.provider_id, "source_id": provider.source_id,
                                    "fixture_id": provider.fixture_id, "declared_origin": INJECTED_TEST_ONLY})
        # Freeze the caller's provider list before callbacks can modify it.
        configured = tuple(providers)
        if _alias(*configured):
            codes.add("SOURCE_ALIAS")
        acquisition = _Acquisition(configured, clock, data["limits"])
        paths = [("boot_id", None), ("proc_mount", None)]
        paths.extend((f"pids/{p['pid']}/{leaf}", p) for p in identities
                     for leaf in ("identity", "ns_link", "ns_target"))
        stopped = False
        for sweep in range(2):
            for provider_index in range(2):
                for path, identity in paths:
                    acquisition.read(provider_index, sweep, path, identity)
                    if acquisition.codes & {"CLOCK_FAILURE", "CLOCK_REGRESSION", "ELAPSED_CAP_EXCEEDED"}:
                        stopped = True
                        break
                if stopped:
                    break
            if stopped:
                break
        reads = acquisition.reads
        now = acquisition.tick() if not stopped else None
        if now is not None:
            if any(r["start_ns"] is not None and now - r["start_ns"] > data["limits"]["max_age_ns"] for r in reads):
                codes.add("STALE_READING")
        codes.update(acquisition.codes)
        if len(reads) != 4 * len(paths) or any(r["status"] != "OK" for r in reads):
            codes.add("FRAME_MISSING")
        _correlate(reads, identities, data["limits"], codes)
        # All retained raw bytes remain internal, never serialized in the report.
        for original, snapshot in acquisition.retained:
            _need(_exact(_copy(original, raw=True), snapshot), "INPUT_CHANGED")
        _need(_digest(_copy([request, roster])) == request_digest, "INPUT_CHANGED")
        _need(type(providers) in (tuple, list) and len(providers) == 2 and
              all(a is b for a, b in zip(providers, configured)), "INPUT_CHANGED")
    except _Rejected as exc:
        codes.add(exc.code)
        if acquisition is not None:
            reads = acquisition.reads
            codes.update(acquisition.codes)
    codes = _sealed(codes)
    invalid = sorted(codes & set(INVALID_CODES))
    incomplete = sorted(codes & set(INCOMPLETE_CODES))
    result = {
        "schema": SCHEMA + ".report", "source_state": INJECTED_TEST_ONLY,
        "qualification": "NONQUALIFYING", "outcome": "INVALID" if invalid else "INCOMPLETE" if incomplete else "CONSISTENT",
        "reason_codes": sorted(codes), "invalid_reason_codes": invalid, "incomplete_reason_codes": incomplete,
        "clock_domain": CLOCK_DOMAIN, "request_sha256": request_digest,
        "registered_roster": identities, "providers": provider_labels, "observations": reads,
        "source_acquisition": "ALIAS_DETECTED" if "SOURCE_ALIAS" in codes else "CALLER_CONFIGURED_ONLY" if
                              any(r["start_ns"] is not None for r in reads) else "NOT_ACQUIRED",
        "independent_corroboration": "NOT_ESTABLISHED",
        "cross_source_structural_agreement": "AGREES" if not codes else "NOT_ESTABLISHED",
        "native_origin_authentication": "NOT_IMPLEMENTED", "independent_host_attestation": "NOT_IMPLEMENTED",
        "worker_roster_completeness": "NOT_ESTABLISHED", "whole_process_tree_coverage": "NOT_ESTABLISHED",
        "rss_chronological_qualification": "NOT_ESTABLISHED", "rss_sampling": "SEQUENTIAL_NONATOMIC",
        "production_memory_qualification": "INCONCLUSIVE", "production_chronological_peak": "NOT_OBSERVED",
        "production_workload_measured": False, "holder_release": "NOT_ESTABLISHED",
        "rss_reclamation": "NOT_ESTABLISHED", "atomic_snapshot": False,
    }
    return BridgeReport(canonical_json(result))
