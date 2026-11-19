"""Artificial B0 regression fixtures; execution belongs to the orchestrator."""

import ast
import builtins
import copy
from dataclasses import FrozenInstanceError
import errno
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import pytest

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_native_provenance_bridge as bridge

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_native_provenance_bridge.py"
BOOT = "12345678-1234-5678-90ab-123456789abc"
SECRET = "private-callback-message-must-not-escape"


class HarnessViolation(BaseException):
    pass


@pytest.fixture(autouse=True)
def forbid_native_io(monkeypatch):
    violations = []

    def blocked(*args, **kwargs):
        violations.append("forbidden native operation")
        raise HarnessViolation("forbidden native operation")

    def path_guard(original, opening=False):
        def wrapped(*args, **kwargs):
            path = args[0] if args else kwargs.get("file", kwargs.get("path"))
            if isinstance(path, (str, bytes, os.PathLike)):
                name = os.fsdecode(path)
                if name in ("/proc", "/sys") or name.startswith(("/proc/", "/sys/")):
                    blocked()
            if opening:
                mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
                if any(flag in mode for flag in "wax+"):
                    blocked()
                # The sole intentional file read is code inspection in the
                # import/AST control. Evidence never comes from local files.
                if not isinstance(path, (str, bytes, os.PathLike)) or os.fsdecode(path) != str(MODULE_PATH):
                    blocked()
            return original(*args, **kwargs)
        return wrapped

    with monkeypatch.context() as guard:
        for name in ("open", "read", "readlink", "listdir", "scandir", "sysconf", "system", "fork",
                     "forkpty", "posix_spawn", "posix_spawnp", "setns", "unshare", "kill", "killpg",
                     "pidfd_open", "mkdir", "makedirs", "remove", "unlink", "rename", "replace", "rmdir"):
            if hasattr(os, name):
                guard.setattr(os, name, blocked)
        for obj, name in ((builtins, "open"), (io, "open")):
            guard.setattr(obj, name, path_guard(getattr(obj, name), opening=True))
        for name in ("stat", "lstat"):
            guard.setattr(os, name, path_guard(getattr(os, name)))
        for obj, names in ((time, ("monotonic_ns", "monotonic", "time_ns",
                                  "perf_counter_ns", "clock_gettime", "clock_gettime_ns")),
                           (subprocess, ("Popen", "run", "call", "check_call", "check_output")),
                           (socket, ("socket", "create_connection"))):
            for name in names:
                if hasattr(obj, name):
                    guard.setattr(obj, name, blocked)
        yield violations
    assert violations == []


def roster():
    return [{"pid": 100, "ppid": 1, "starttime_ticks": 10},
            {"pid": 200, "ppid": 100, "starttime_ticks": 20}]


def request():
    return {"schema": bridge.SCHEMA, "mode": bridge.INJECTED_TEST_ONLY, "native_opt_in": False,
            "clock_domain": bridge.CLOCK_DOMAIN, "sweeps": 2,
            "limits": {"max_elapsed_ns": 100000, "max_read_ns": 100, "max_gap_ns": 100,
                       "max_age_ns": 100000, "max_source_skew_ns": 1000}}


def digest(value):
    return hashlib.sha256(bridge.canonical_json(value).encode()).hexdigest()


class FakeClock:
    def __init__(self):
        self.calls = 0
        self.hook = None

    def __call__(self):
        self.calls += 1
        return self.hook(self.calls) if self.hook else 1000 + self.calls


class FakeProvider:
    """Closed artificial operation allowlist; no strings are OS paths or fds."""

    def __init__(self, name, identities=None, raw=False):
        identities = roster() if identities is None else identities
        self.name, self.raw = name, raw
        self.identities = {p["pid"]: copy.deepcopy(p) for p in identities}
        self.paths = {"boot_id", "proc_mount"}
        self.paths.update(f"pids/{pid}/{leaf}" for pid in self.identities for leaf in ("identity", "ns_link", "ns_target"))
        self.active, self.calls, self.counts, self.emitted = {}, [], {}, []
        self.sequence, self.next_handle, self.hook = 0, 0, None

    def configured(self, **changes):
        values = {"provider_id": self.name, "source_id": self.name + "_source",
                  "fixture_id": self.name + "_fixture", "callback": self}
        values.update(changes)
        return bridge.Provider(**values)

    def descriptor(self, path):
        parts = path.split("/")
        identity = self.identities[int(parts[1])] if path.startswith("pids/") else None
        target, link = path.endswith("/ns_target"), path.endswith("/ns_link")
        return {"path_id": path, "role": "NSFS_TARGET" if target else "PROCFS_LINK_LOCATION" if link else "PROCFS_OBJECT",
                "st_dev": 4 if target else 5, "st_ino": 77 if target else sorted(self.paths).index(path) + 100,
                "mount_id": 10 if target else 9, "filesystem": "nsfs" if target else "proc",
                "symlink": link, "binding": "INJECTED_DESCRIPTOR_RELATIVE_NO_FOLLOW", "identity": copy.deepcopy(identity)}

    def envelope(self, path):
        if path == "boot_id":
            payload = {"boot_id": BOOT}
        elif path == "proc_mount":
            payload = {"mount_id": 9, "st_dev": 5, "filesystem": "proc"}
        elif path.endswith("/identity"):
            payload = {"identity": copy.deepcopy(self.identities[int(path.split("/")[1])]),
                       "cpu_ticks": 50, "vmhwm_kib": 100, "rss_kib": 80}
        elif path.endswith("/ns_link"):
            payload = {"namespace_inode": 77}
        else:
            payload = {"st_dev": 4, "st_ino": 77}
        self.sequence += 1
        raw = json.dumps(payload, sort_keys=True).encode() if self.raw else None
        return {"payload": payload, "raw": raw, "sha256": digest(payload) if raw is None else hashlib.sha256(raw).hexdigest(),
                "method": "INJECTED_JSON_BYTES" if self.raw else "INJECTED_STRUCTURED",
                "declared_origin": bridge.INJECTED_TEST_ONLY, "sequence": self.sequence, "status": "OK", "reason": None}

    def __call__(self, operation):
        if type(operation) is not bridge.Operation or operation.path_id not in self.paths:
            raise HarnessViolation("unallowlisted artificial operation")
        op = operation
        if op.action not in ("OPEN", "DESCRIBE", "READ", "CLOSE") or op.sweep not in (0, 1):
            raise HarnessViolation("unallowlisted artificial operation")
        if op.max_bytes != (bridge.MAX_RAW_BYTES + 1 if op.action == "READ" else 0):
            raise HarnessViolation("unbounded artificial read")
        self.calls.append(op)
        key = op.action, op.path_id
        count = self.counts.get(key, 0)
        self.counts[key] = count + 1
        if op.action == "OPEN":
            if op.handle is not None:
                raise HarnessViolation("open with an existing handle")
            self.next_handle += 1
            value = bridge.Handle(f"{self.name}_{self.next_handle}")
            value = self.hook(op, count, value) if self.hook else value
            if type(value) is bridge.Handle:
                self.active[value.token] = op.path_id
            return value
        if type(op.handle) is not bridge.Handle or self.active.get(op.handle.token) != op.path_id:
            raise HarnessViolation("stale or foreign artificial handle")
        if op.action == "CLOSE":
            del self.active[op.handle.token]
            return self.hook(op, count, None) if self.hook else None
        value = self.descriptor(op.path_id) if op.action == "DESCRIBE" else self.envelope(op.path_id)
        value = self.hook(op, count, value) if self.hook else value
        self.emitted.append(value)
        return value


def run(*, data=None, identities=None, left=None, right=None, clock=None, configured=None):
    data, identities = request() if data is None else data, roster() if identities is None else identities
    left, right = FakeProvider("left", identities) if left is None else left, FakeProvider("right", identities) if right is None else right
    clock = FakeClock() if clock is None else clock
    before = copy.deepcopy([data, identities])
    report = bridge.acquire_provenance_bridge(identities, data,
        providers=configured if configured is not None else (left.configured(), right.configured()), clock=clock)
    output = report.to_dict()
    assert [data, identities] == before
    assert output["source_state"] == "INJECTED_TEST_ONLY"
    assert output["qualification"] == "NONQUALIFYING"
    assert output["native_origin_authentication"] == output["independent_host_attestation"] == "NOT_IMPLEMENTED"
    assert output["independent_corroboration"] == output["worker_roster_completeness"] == "NOT_ESTABLISHED"
    assert output["whole_process_tree_coverage"] == output["rss_chronological_qualification"] == "NOT_ESTABLISHED"
    assert output["holder_release"] == output["rss_reclamation"] == "NOT_ESTABLISHED"
    assert output["production_memory_qualification"] == "INCONCLUSIVE"
    assert output["production_chronological_peak"] == "NOT_OBSERVED"
    assert output["atomic_snapshot"] is output["production_workload_measured"] is False
    assert output["rss_sampling"] == "SEQUENTIAL_NONATOMIC"
    assert SECRET not in report.serialized
    assert "NATIVE_LOCAL_UNVERIFIED" not in report.serialized
    invalid, incomplete = set(output["invalid_reason_codes"]), set(output["incomplete_reason_codes"])
    assert not invalid & incomplete
    assert invalid <= set(bridge.INVALID_CODES) and incomplete <= set(bridge.INCOMPLETE_CODES)
    assert output["reason_codes"] == sorted(invalid | incomplete)
    assert output["outcome"] == ("INVALID" if invalid else "INCOMPLETE" if incomplete else "CONSISTENT")
    assert len(output["observations"]) <= bridge.MAX_READS
    assert clock.calls <= 2 * bridge.MAX_READS + 1
    assert not left.active and not right.active
    for fake in (left, right):
        opens = [op for op in fake.calls if op.action == "OPEN"]
        closes = [op for op in fake.calls if op.action == "CLOSE"]
        assert len(closes) <= len(opens)
        # Aliasing controls intentionally route both provider slots to one fake.
        assert all(n <= (8 if action == "DESCRIBE" else 4) for (action, _), n in fake.counts.items())
    return output


def reason(output, code):
    assert code in output["reason_codes"]
    assert output["outcome"] != "CONSISTENT"
    assert output["cross_source_structural_agreement"] == "NOT_ESTABLISHED"


def exact_reasons(output, *, invalid=(), incomplete=()):
    assert output["invalid_reason_codes"] == sorted(invalid)
    assert output["incomplete_reason_codes"] == sorted(incomplete)
    assert output["reason_codes"] == sorted(set(invalid) | set(incomplete))
    assert output["outcome"] == ("INVALID" if invalid else "INCOMPLETE" if incomplete else "CONSISTENT")
    assert output["cross_source_structural_agreement"] == ("NOT_ESTABLISHED" if invalid or incomplete else "AGREES")


def rewrite(envelope, key, value):
    envelope["payload"][key] = value
    if envelope["raw"] is not None:
        envelope["raw"] = json.dumps(envelope["payload"], sort_keys=True).encode()
        envelope["sha256"] = hashlib.sha256(envelope["raw"]).hexdigest()
    else:
        envelope["sha256"] = digest(envelope["payload"])
    return envelope


@pytest.mark.parametrize("raw", [False, True])
def test_agreement_is_only_artificial_structural_agreement(raw):
    left, right = FakeProvider("left", raw=raw), FakeProvider("right", raw=raw)
    output = run(left=left, right=right)
    assert output["reason_codes"] == [] and output["outcome"] == "CONSISTENT"
    assert output["cross_source_structural_agreement"] == "AGREES"
    assert output["source_acquisition"] == "CALLER_CONFIGURED_ONLY"
    assert output["request_sha256"] == digest([request(), roster()])
    assert len(output["observations"]) == 32
    for record in output["observations"]:
        assert record["start_ns"] < record["end_ns"] and record["status"] == "OK"
        assert record["descriptor_before"] == record["descriptor_after"]
        assert record["sha256"] == record["declared_sha256"]
        assert record["payload_sha256"] == digest(record["payload"])
        assert "raw" not in record
        if record["path_id"].endswith("/ns_target"):
            assert record["descriptor_before"]["mount_id"] == 10
            assert record["descriptor_before"]["filesystem"] == "nsfs"
        elif record["path_id"].endswith("/ns_link"):
            assert record["descriptor_before"]["mount_id"] == 9
            assert record["descriptor_before"]["symlink"] is True
    boots = [r for r in output["observations"] if r["path_id"] == "boot_id"]
    assert len(boots) == 4 and all(b["descriptor_before"]["path_id"] == "boot_id" for b in boots)
    assert len([op for op in left.calls if op.action == "CLOSE"]) == 16


def test_raw_digest_retains_exact_bytes_at_the_limit_without_serializing_them():
    left = FakeProvider("left", raw=True)
    original = []
    def hook(op, n, value):
        if op.action == "READ" and op.path_id == "boot_id":
            value["raw"] += b" " * (bridge.MAX_RAW_BYTES - len(value["raw"]))
            value["sha256"] = hashlib.sha256(value["raw"]).hexdigest()
            original.append(value["raw"])
        return value
    left.hook = hook
    output = run(left=left)
    assert output["reason_codes"] == []
    record = output["observations"][0]
    assert record["raw_byte_count"] == bridge.MAX_RAW_BYTES
    assert record["sha256"] == hashlib.sha256(original[0]).hexdigest()
    assert record["sha256"] != record["payload_sha256"]
    assert "raw" not in record


def test_raw_json_boolean_cannot_impersonate_an_integer_in_the_structured_payload():
    identities = [{"pid": 1, "ppid": 0, "starttime_ticks": 10}]
    left = FakeProvider("left", identities, raw=True)
    def hook(op, n, value):
        if op.action == "READ" and op.path_id == "pids/1/identity":
            raw_payload = copy.deepcopy(value["payload"])
            raw_payload["identity"]["pid"] = True
            value["raw"] = json.dumps(raw_payload).encode()
            value["sha256"] = hashlib.sha256(value["raw"]).hexdigest()
        return value
    left.hook = hook
    reason(run(left=left, identities=identities), "SOURCE_DIGEST_MISMATCH")


def test_import_replay_and_construction_are_inert():
    importlib.reload(bridge)
    fake, clock = FakeProvider("unused"), FakeClock()
    fake.configured()
    bridge.Handle("unused")
    assert fake.calls == [] and clock.calls == 0
    tree = ast.parse(MODULE_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            assert not {"os", "time", "sys", "ctypes", "socket", "subprocess", "pathlib"} & set(names)
            assert all(not (name or "").startswith("scripts.") for name in names)
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            assert name not in ("open", "openat", "fork", "spawn", "stat", "lstat", "readlink", "sysconf", "eval", "exec")


@pytest.mark.parametrize("operation", [
    lambda: builtins.open("/proc/self/stat"), lambda: io.open("/sys/kernel"),
    lambda: builtins.open("/etc/hostname"),
    lambda: Path("/proc/self/status").read_bytes(), lambda: os.open("leaf", 0, dir_fd=123),
    lambda: os.read(123, 1), lambda: os.readlink("/proc/self/ns/pid"),
    lambda: os.stat("/proc/self"), lambda: os.lstat("/sys"),
    lambda: time.monotonic_ns(), lambda: time.monotonic(), lambda: time.time_ns(),
    lambda: subprocess.Popen(["forbidden"]), lambda: subprocess.run(["forbidden"]),
    lambda: socket.socket(), lambda: os.listdir("."), lambda: os.scandir("."),
    lambda: builtins.open("forbidden-artificial-file", "w"),
    lambda: io.open("forbidden-artificial-file", "a"), lambda: os.mkdir("forbidden-artificial-directory"),
    lambda: os.unlink("forbidden-artificial-file"), lambda: os.kill(999999, 0),
])
def test_guard_negative_controls(operation, forbid_native_io):
    with pytest.raises(HarnessViolation):
        operation()
    assert forbid_native_io == ["forbidden native operation"]
    forbid_native_io.clear()


@pytest.mark.parametrize("mode", ["NATIVE", "NATIVE_LOCAL_UNVERIFIED", "native", "INJECTED_TEST_ONLY"])
@pytest.mark.parametrize("opt_in", [True, 1, "yes"])
def test_native_requests_denied_before_callbacks_or_clock(mode, opt_in):
    data, left, right, clock = request(), FakeProvider("left"), FakeProvider("right"), FakeClock()
    data.update(mode=mode, native_opt_in=opt_in)
    output = run(data=data, left=left, right=right, clock=clock)
    assert output["reason_codes"] == ["NATIVE_MODE_DENIED"]
    assert left.calls == right.calls == [] and clock.calls == 0


@pytest.mark.parametrize("mode", ["NATIVE", "NATIVE_LOCAL_UNVERIFIED", "native"])
def test_native_label_is_denied_with_opt_in_false(mode):
    data = request()
    data["mode"] = mode
    output = run(data=data)
    assert output["reason_codes"] == ["NATIVE_MODE_DENIED"]
    assert output["source_acquisition"] == "NOT_ACQUIRED"


@pytest.mark.parametrize("origin", ["NATIVE", "NATIVE_LOCAL_UNVERIFIED", "AUTHENTICATED", None])
def test_forged_provider_origin_denied_before_callbacks(origin):
    left, right, clock = FakeProvider("left"), FakeProvider("right"), FakeClock()
    output = run(left=left, right=right, clock=clock,
                 configured=(left.configured(declared_origin=origin), right.configured()))
    assert output["reason_codes"] == ["ORIGIN_INVALID"]
    assert left.calls == right.calls == [] and clock.calls == 0


@pytest.mark.parametrize("key", ["provider_id", "source_id", "fixture_id"])
def test_reserved_native_state_cannot_be_echoed_as_provider_identifier(key):
    left, right = FakeProvider("left"), FakeProvider("right")
    output = run(left=left, right=right,
                 configured=(left.configured(**{key: bridge.NATIVE_LOCAL_UNVERIFIED}), right.configured()))
    assert output["reason_codes"] == ["ORIGIN_INVALID"] and not left.calls


@pytest.mark.parametrize("slot", [0, 1])
@pytest.mark.parametrize("key", ["provider_id", "source_id", "fixture_id"])
@pytest.mark.parametrize("label", [
    "NATIVE_LOCAL_UNVERIFIED_x", "native-local-unverified", "Native_host", "x_nAtIvE_y",
    "n_a-t_i-v_e_host", "AUTHENTICATED", "authenticated_src", "authentic-ated_src",
    "qualified_fixture", "unQUALIFIED_fixture", "q_u-a_l_i-f_i_e_d", "host_attested",
    "verified_source", "corroborated_source", "injected-test-only_x", "not_established_x",
    "not-implemented_x", "inconclusive_x", "not_observed_x", "caller-configured-only_x",
    "alias_detected_x", "not_acquired_x", "sequential_nonatomic_x", "injected_monotonic_ns_x",
    "consistent_x", "incomplete_x", "invalid_x", "agrees_x",
])
def test_untrusted_authority_labels_rejected_before_any_io(slot, key, label):
    left, right, clock = FakeProvider("left"), FakeProvider("right"), FakeClock()
    configured = [left.configured(), right.configured()]
    configured[slot] = (left if slot == 0 else right).configured(**{key: label})
    output = run(left=left, right=right, clock=clock, configured=configured)
    exact_reasons(output, invalid=("ORIGIN_INVALID",))
    assert left.calls == right.calls == [] and clock.calls == 0
    assert label not in bridge.canonical_json(output)


def test_benign_labels_serialize_only_as_caller_provider_metadata():
    left, right = FakeProvider("left"), FakeProvider("right")
    configured = [fake.configured(provider_id=f"route_{fake.name}_x", source_id=f"source_{fake.name}_x",
                                  fixture_id=f"fixture_{fake.name}_x") for fake in (left, right)]
    output = run(left=left, right=right, configured=configured)
    exact_reasons(output)
    providers = output.pop("providers")
    remainder = bridge.canonical_json(output)
    for provider, declared in zip(providers, configured):
        for key in ("provider_id", "source_id", "fixture_id"):
            assert provider[key] == getattr(declared, key)
            assert provider[key] not in remainder
        assert provider["declared_origin"] == "INJECTED_TEST_ONLY"
    assert output["source_state"] == "INJECTED_TEST_ONLY"
    assert output["qualification"] == "NONQUALIFYING"
    assert output["independent_corroboration"] == "NOT_ESTABLISHED"
    assert output["native_origin_authentication"] == output["independent_host_attestation"] == "NOT_IMPLEMENTED"


@pytest.mark.parametrize("alias", ["callback", "bound_owner", "provider_id", "source_id", "fixture_id", "handle", "payload"])
def test_alias_detection_never_attests_independence(alias):
    left, right = FakeProvider("left"), FakeProvider("right")
    configured = [left.configured(), right.configured()]
    if alias == "callback":
        configured[1] = right.configured(callback=left)
    elif alias == "bound_owner":
        configured = [left.configured(callback=left.__call__), right.configured(callback=left.__call__)]
    elif alias in ("provider_id", "source_id", "fixture_id"):
        configured[1] = right.configured(**{alias: getattr(configured[0], alias)})
    elif alias == "handle":
        def hook(op, n, value):
            return bridge.Handle(f"shared_{op.sweep}_{sorted(left.paths).index(op.path_id)}") if op.action == "OPEN" else value
        left.hook = right.hook = hook
    else:
        shared = {"boot_id": BOOT}
        def hook(op, n, value):
            if op.action == "READ" and op.path_id == "boot_id":
                value["payload"] = shared
            return value
        left.hook = right.hook = hook
    output = run(left=left, right=right, configured=configured)
    exact_reasons(output, incomplete=("FRAME_MISSING", "SOURCE_ALIAS") if alias == "handle" else ("SOURCE_ALIAS",))
    assert output["source_acquisition"] == "ALIAS_DETECTED"


@pytest.mark.parametrize("reverse", [False, True])
def test_provider_object_and_its_own_bound_call_are_aliases_in_either_order(reverse):
    left, right = FakeProvider("left"), FakeProvider("right")
    callbacks = [left, left.__call__]
    if reverse:
        callbacks.reverse()
    output = run(left=left, right=right, configured=(
        left.configured(callback=callbacks[0]), right.configured(callback=callbacks[1])))
    exact_reasons(output, incomplete=("SOURCE_ALIAS",))
    assert output["source_acquisition"] == "ALIAS_DETECTED"
    assert output["independent_corroboration"] == "NOT_ESTABLISHED"
    assert not right.calls


@pytest.mark.parametrize("reverse", [False, True])
def test_distinct_provider_object_and_bound_call_do_not_alias(reverse):
    left, right = FakeProvider("left"), FakeProvider("right")
    configured = [left.configured(), right.configured(callback=right.__call__)]
    if reverse:
        configured.reverse()
    output = run(left=left, right=right, configured=configured)
    exact_reasons(output)
    assert output["source_acquisition"] == "CALLER_CONFIGURED_ONLY"
    assert output["independent_corroboration"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize("path", ["/proc/100/stat", "../boot_id", "pids/999/identity", "pids/100/../identity", "custom", "boot_id/extra"])
def test_symbolic_allowlist_rejects_path_injection(path):
    left = FakeProvider("left")
    def hook(op, n, value):
        if op.action == "DESCRIBE":
            value["path_id"] = path
        return value
    left.hook = hook
    reason(run(left=left), "PATH_POLICY_VIOLATION")
    with pytest.raises(HarnessViolation):
        left(bridge.Operation("OPEN", path, 0))


@pytest.mark.parametrize("leaf", ["boot_id", "proc_mount", "pids/100/identity", "pids/100/ns_target", "pids/100/ns_link"])
def test_symlink_substitution_including_missing_link_location(leaf):
    left = FakeProvider("left")
    def hook(op, n, value):
        if op.action == "DESCRIBE" and op.path_id == leaf:
            value["symlink"] = not value["symlink"]
        return value
    left.hook = hook
    reason(run(left=left), "SYMLINK_SUBSTITUTION")


@pytest.mark.parametrize("action", ["OPEN", "READ", "DESCRIBE"])
@pytest.mark.parametrize("number,expected", [
    (errno.ELOOP, "SYMLINK_SUBSTITUTION"), (errno.ENOTDIR, "PATH_POLICY_VIOLATION"),
    (errno.ENOENT, "vanished"), (errno.ESRCH, "vanished"), (errno.EACCES, "PERMISSION_DENIED"),
    (errno.EIO, "READ_FAILED"),
])
def test_errno_matrix_preserves_missing_worker_vs_stale_handle(action, number, expected):
    left = FakeProvider("left")
    def hook(op, n, value):
        if op.action == action and op.path_id == "pids/100/identity":
            raise OSError(number, SECRET)
        return value
    left.hook = hook
    output = run(left=left)
    expected = ("MISSING_WORKER" if action == "OPEN" else "STALE_HANDLE") if expected == "vanished" else expected
    if number in (errno.ELOOP, errno.ENOTDIR):
        exact_reasons(output, invalid=(expected,), incomplete=("FRAME_MISSING",))
    else:
        exact_reasons(output, incomplete=(expected, "FRAME_MISSING"))
    assert left.counts[action, "pids/100/identity"] == (4 if action == "DESCRIBE" else 2)
    record = next(r for r in output["observations"] if r["path_id"] == "pids/100/identity")
    assert record["operation_errors"][0]["action"] == action
    assert record["operation_errors"][0]["errno"] == number


def test_missing_global_evidence_is_not_reported_as_a_stale_handle():
    left = FakeProvider("left")
    def hook(op, n, value):
        if op.action == "OPEN" and op.path_id == "boot_id":
            raise FileNotFoundError(errno.ENOENT, SECRET)
        return value
    left.hook = hook
    output = run(left=left)
    exact_reasons(output, incomplete=("FRAME_MISSING",))


@pytest.mark.parametrize("location", ["payload", "descriptor"])
@pytest.mark.parametrize("field,new_value,expected", [
    ("pid", 300, "IDENTITY_SUBSTITUTION"), ("pid", 100, "SCHEMA_INVALID"),
    ("ppid", 2, "PROCESS_REPARENTED"), ("starttime_ticks", 999, "PID_REUSE"),
])
def test_registered_identity_and_separate_schema_invalid_pid_equals_ppid(location, field, new_value, expected):
    left = FakeProvider("left")
    # pid 200 has ppid 100: pid=100 is the distinct invalid-schema control;
    # pid=300 remains a valid identity, but is outside the registered roster.
    def hook(op, n, value):
        if op.path_id == "pids/200/identity" and op.sweep == 1:
            if location == "payload" and op.action == "READ":
                value["payload"]["identity"][field] = new_value
                value["sha256"] = digest(value["payload"])
            elif location == "descriptor" and op.action == "DESCRIBE":
                value["identity"][field] = new_value
        return value
    left.hook = hook
    output = run(left=left)
    if expected in ("IDENTITY_SUBSTITUTION", "SCHEMA_INVALID"):
        exact_reasons(output, invalid=(expected,), incomplete=("FRAME_MISSING",))
    else:
        exact_reasons(output, incomplete=(expected, "FRAME_MISSING"))


@pytest.mark.parametrize("kind", ["mount_map", "cross_sweep_mount_device", "device_map", "ns_proc_collision", "swapped_descriptor", "changed_descriptor", "namespace", "boot_change", "boot_malformed"])
def test_cross_sweep_and_cross_source_contradictions(kind):
    left = FakeProvider("left")
    def hook(op, n, value):
        path = op.path_id
        if op.action == "DESCRIBE":
            if kind == "mount_map" and path.endswith("ns_target"):
                value["mount_id"] = 9
            elif kind == "cross_sweep_mount_device" and path.endswith("ns_target") and op.sweep == 1:
                value["st_dev"] = 6
            elif kind in ("device_map", "ns_proc_collision") and path.endswith("ns_target"):
                value["st_dev"] = 5
            elif kind == "swapped_descriptor" and path == "pids/100/identity":
                value["st_ino"] = left.descriptor("pids/200/identity")["st_ino"]
            elif kind == "changed_descriptor" and path == "boot_id" and op.sweep == 1:
                value["st_ino"] = 9999
        elif op.action == "READ":
            if kind in ("device_map", "ns_proc_collision") and path.endswith("ns_target"):
                rewrite(value, "st_dev", 5)
            elif kind == "cross_sweep_mount_device" and path.endswith("ns_target") and op.sweep == 1:
                rewrite(value, "st_dev", 6)
            elif kind == "namespace" and path.endswith("ns_link") and op.sweep == 1:
                rewrite(value, "namespace_inode", 78)
            elif kind in ("boot_change", "boot_malformed") and path == "boot_id" and op.sweep == 1:
                rewrite(value, "boot_id", "00000000-0000-0000-0000-000000000000" if kind == "boot_change" else "forged")
        return value
    left.hook = hook
    expected = {"mount_map": "MOUNT_CONTRADICTION", "cross_sweep_mount_device": "MOUNT_CONTRADICTION", "device_map": "MOUNT_CONTRADICTION",
                "ns_proc_collision": "MOUNT_CONTRADICTION", "swapped_descriptor": "DESCRIPTOR_ALIAS",
                "changed_descriptor": "DESCRIPTOR_CHANGED", "namespace": "NAMESPACE_CONTRADICTION",
                "boot_change": "BOOT_ID_CHANGED", "boot_malformed": "SCHEMA_INVALID"}[kind]
    reason(run(left=left), expected)


def test_descriptor_recheck_detects_change_inside_one_read_window():
    left = FakeProvider("left")
    def hook(op, n, value):
        if op.action == "DESCRIBE" and op.path_id == "boot_id" and n % 2:
            value["st_ino"] = 9999
        return value
    left.hook = hook
    output = run(left=left)
    exact_reasons(output, invalid=("DESCRIPTOR_CHANGED",), incomplete=("FRAME_MISSING",))
    record = output["observations"][0]
    assert record["descriptor_before"]["st_ino"] != record["descriptor_after"]["st_ino"]
    assert record["payload"] == {"boot_id": BOOT}


@pytest.mark.parametrize("path", ["boot_id", "pids/100/identity"])
@pytest.mark.parametrize("number,expected", [
    (errno.EACCES, "PERMISSION_DENIED"), (errno.ENOENT, "STALE_HANDLE"), (errno.ESRCH, "STALE_HANDLE"),
])
def test_first_describe_errno_does_not_invent_descriptor_change(path, number, expected):
    left = FakeProvider("left")
    def hook(op, n, value):
        if op.action == "DESCRIBE" and op.path_id == path and n == 0:
            raise OSError(number, SECRET)
        return value
    left.hook = hook
    output = run(left=left)
    exact_reasons(output, incomplete=(expected, "FRAME_MISSING"))
    record = next(r for r in output["observations"] if r["path_id"] == path)
    assert record["descriptor_before"] is None
    assert record["descriptor_after"] == left.descriptor(path)
    assert record["payload"] is None and record["status"] == "FAILED"
    assert record["operation_errors"] == [{"action": "DESCRIBE", "reason_code": expected, "errno": number}]
    first_open = next(op for op in left.calls if op.action == "DESCRIBE" and op.path_id == path)
    lease_ops = [op.action for op in left.calls if op.handle == first_open.handle]
    assert lease_ops == ["DESCRIBE", "DESCRIBE", "CLOSE"]


@pytest.mark.parametrize("path", ["boot_id", "pids/100/identity"])
def test_invalid_first_descriptor_retains_only_original_failure_after_valid_recheck(path):
    left = FakeProvider("left")
    def hook(op, n, value):
        if op.action == "DESCRIBE" and op.path_id == path and n == 0:
            value["symlink"] = True
        return value
    left.hook = hook
    output = run(left=left)
    exact_reasons(output, invalid=("SYMLINK_SUBSTITUTION",), incomplete=("FRAME_MISSING",))
    record = next(r for r in output["observations"] if r["path_id"] == path)
    assert record["descriptor_before"] is None and record["descriptor_after"] == left.descriptor(path)
    lease = next(op.handle for op in left.calls if op.action == "DESCRIBE" and op.path_id == path)
    assert [op.action for op in left.calls if op.handle == lease] == ["DESCRIBE", "DESCRIBE", "CLOSE"]


@pytest.mark.parametrize("counter", ["sequence", "cpu_ticks", "vmhwm_kib", "rss_kib"])
def test_counter_policy_allows_rss_decreases(counter):
    left = FakeProvider("left")
    def hook(op, n, value):
        if op.action == "READ" and op.sweep == 1:
            if counter == "sequence" and op.path_id == "boot_id":
                value["sequence"] = 0
            elif counter != "sequence" and op.path_id == "pids/100/identity":
                rewrite(value, counter, 1)
        return value
    left.hook = hook
    output = run(left=left)
    if counter == "rss_kib":
        assert "COUNTER_ROLLBACK" not in output["reason_codes"]
        reason(output, "SOURCE_DISAGREEMENT")
    else:
        reason(output, "COUNTER_ROLLBACK")


def test_both_providers_can_observe_a_lower_rss_without_failure():
    left, right = FakeProvider("left"), FakeProvider("right")
    def hook(op, n, value):
        if op.action == "READ" and op.sweep == 1 and op.path_id.endswith("/identity"):
            rewrite(value, "rss_kib", 1)
        return value
    left.hook = right.hook = hook
    assert run(left=left, right=right)["reason_codes"] == []


def timed_counter_run(counter, values, scope=None):
    left, right, clock = FakeProvider("left"), FakeProvider("right"), FakeClock()
    clock.hook = lambda n: 1000 + 10 * n
    def provider_hook(provider_index):
        def hook(op, n, value):
            if op.action == "READ" and op.path_id == "pids/100/identity":
                rewrite(value, counter, values[2 * op.sweep + provider_index])
            if provider_index == 1:
                if scope == "boot" and op.action == "READ" and op.path_id == "boot_id":
                    rewrite(value, "boot_id", "00000000-0000-0000-0000-000000000000")
                elif scope == "namespace":
                    if op.path_id == "pids/100/ns_target":
                        if op.action == "DESCRIBE":
                            value["st_ino"] = 78
                        elif op.action == "READ":
                            rewrite(value, "st_ino", 78)
                    elif op.path_id == "pids/100/ns_link" and op.action == "READ":
                        rewrite(value, "namespace_inode", 78)
                elif scope in ("missing_boot", "missing_namespace") and op.action == "READ":
                    missing_path = "boot_id" if scope == "missing_boot" else "pids/100/ns_target"
                    if op.path_id == missing_path:
                        return None
            return value
        return hook
    left.hook, right.hook = provider_hook(0), provider_hook(1)
    output = run(left=left, right=right, clock=clock)
    records = [r for r in output["observations"] if r["path_id"] == "pids/100/identity"]
    # Acquisition order differs from provider-major order and local sequences.
    assert [(r["provider_index"], r["sweep"], r["start_ns"], r["end_ns"]) for r in records] == [
        (0, 0, 1050, 1060), (1, 0, 1210, 1220), (0, 1, 1370, 1380), (1, 1, 1530, 1540)]
    assert [r["payload"][counter] for r in records] == list(values)
    return output


@pytest.mark.parametrize("counter", ["cpu_ticks", "vmhwm_kib"])
@pytest.mark.parametrize("values", [(50, 60, 55, 65), (60, 50, 70, 65)])
def test_cumulative_rollback_across_providers_uses_global_fake_clock_order(counter, values):
    output = timed_counter_run(counter, values)
    exact_reasons(output, invalid=("COUNTER_ROLLBACK",), incomplete=("SOURCE_DISAGREEMENT",))


@pytest.mark.parametrize("counter", ["cpu_ticks", "vmhwm_kib"])
@pytest.mark.parametrize("values,disagreement", [((50, 60, 70, 80), True), ((50, 50, 70, 70), False)])
def test_cumulative_growth_does_not_use_provider_major_order(counter, values, disagreement):
    output = timed_counter_run(counter, values)
    exact_reasons(output, incomplete=("SOURCE_DISAGREEMENT",) if disagreement else ())


def test_cross_provider_rss_decrease_is_snapshot_disagreement_without_rollback():
    output = timed_counter_run("rss_kib", (80, 70, 60, 50))
    exact_reasons(output, incomplete=("SOURCE_DISAGREEMENT",))


@pytest.mark.parametrize("counter", ["cpu_ticks", "vmhwm_kib"])
@pytest.mark.parametrize("scope", ["boot", "namespace", "missing_boot", "missing_namespace"])
def test_cross_provider_rollback_requires_complete_comparable_scope(counter, scope):
    # Each provider grows; only the cross-provider readings decrease.
    output = timed_counter_run(counter, (50, 60, 55, 65), scope)
    if scope == "boot":
        exact_reasons(output, incomplete=("BOOT_ID_CHANGED", "SOURCE_DISAGREEMENT"))
    elif scope == "namespace":
        exact_reasons(output, invalid=("DESCRIPTOR_CHANGED", "NAMESPACE_CONTRADICTION"),
                      incomplete=("SOURCE_DISAGREEMENT",))
    else:
        exact_reasons(output, incomplete=("FRAME_MISSING", "SOURCE_DISAGREEMENT"))


@pytest.mark.parametrize("counter", ["cpu_ticks", "vmhwm_kib"])
def test_cumulative_counters_of_unrelated_pids_are_not_compared(counter):
    left, right, clock = FakeProvider("left"), FakeProvider("right"), FakeClock()
    clock.hook = lambda n: 1000 + 10 * n
    def hook(op, n, value):
        if op.action == "READ" and op.path_id.endswith("/identity"):
            rewrite(value, counter, 100 if op.path_id == "pids/100/identity" else 1)
        return value
    left.hook = right.hook = hook
    output = run(left=left, right=right, clock=clock)
    exact_reasons(output)
    records = [r for r in output["observations"] if r["path_id"].endswith("/identity")]
    assert [r["start_ns"] for r in records] == [1050, 1110, 1210, 1270, 1370, 1430, 1530, 1590]
    assert [r["payload"][counter] for r in records] == [100, 1] * 4


@pytest.mark.parametrize("counter", ["cpu_ticks", "vmhwm_kib"])
@pytest.mark.parametrize("location", ["payload", "descriptor"])
def test_reused_pid_with_lower_counters_is_only_pid_reuse(counter, location):
    left, right, clock = FakeProvider("left"), FakeProvider("right"), FakeClock()
    clock.hook = lambda n: 1000 + 10 * n
    def hook(op, n, value):
        if op.path_id == "pids/100/identity" and op.sweep == 1:
            if op.action == "READ":
                rewrite(value, counter, 1)
                if location == "payload":
                    changed = copy.deepcopy(value["payload"]["identity"])
                    changed["starttime_ticks"] = 999
                    rewrite(value, "identity", changed)
            elif op.action == "DESCRIBE" and location == "descriptor":
                value["identity"]["starttime_ticks"] = 999
        return value
    left.hook = right.hook = hook
    output = run(left=left, right=right, clock=clock)
    exact_reasons(output, incomplete=("PID_REUSE", "FRAME_MISSING"))
    records = [r for r in output["observations"] if r["path_id"] == "pids/100/identity"]
    assert [r["start_ns"] for r in records] == [1050, 1210, 1370, 1530]
    assert [r["status"] for r in records] == ["OK", "OK", "FAILED", "FAILED"]


@pytest.mark.parametrize("case", ["missing", "origin", "status", "reason", "error_reason", "digest", "raw_mismatch", "bytearray", "raw_type", "stale_sequence"])
def test_malformed_or_forged_read_envelopes(case):
    left = FakeProvider("left", raw=case in ("raw_mismatch", "bytearray", "raw_type"))
    def hook(op, n, value):
        if op.action != "READ" or op.path_id != "boot_id":
            return value
        if case == "missing":
            return None
        if case == "origin":
            value["declared_origin"] = "NATIVE_LOCAL_UNVERIFIED"
        elif case == "status":
            value["status"] = SECRET
        elif case == "reason":
            value["reason"] = SECRET
        elif case == "error_reason":
            value.update(status="ERROR", reason=SECRET)
        elif case == "digest":
            value["sha256"] = "0" * 64
        elif case == "raw_mismatch":
            value["raw"] = b'{}'
            value["sha256"] = hashlib.sha256(value["raw"]).hexdigest()
        elif case == "bytearray":
            value["raw"] = bytearray(value["raw"])
        elif case == "raw_type":
            value["raw"] = "artificial-string"
        elif case == "stale_sequence" and op.sweep == 1:
            value["sequence"] = 8
        return value
    left.hook = hook
    expected = {"missing": "FRAME_MISSING", "origin": "ORIGIN_INVALID", "status": "REASON_CODE_INVALID",
                "reason": "REASON_CODE_INVALID", "error_reason": "REASON_CODE_INVALID", "digest": "SOURCE_DIGEST_MISMATCH",
                "raw_mismatch": "SOURCE_DIGEST_MISMATCH", "bytearray": "INPUT_NOT_JSON",
                "raw_type": "CALLBACK_CONTRACT_INVALID", "stale_sequence": "STALE_READING"}[case]
    reason(run(left=left), expected)


@pytest.mark.parametrize("raw,expected", [
    (b"\xff", "INPUT_NOT_JSON"), (b"{", "INPUT_NOT_JSON"),
    (b'{"boot_id":"x","boot_id":"y"}', "SCHEMA_INVALID"),
    ((b"[" * (bridge.MAX_DEPTH + 2)) + b"0" + (b"]" * (bridge.MAX_DEPTH + 2)), "INPUT_CAP_EXCEEDED"),
])
def test_malformed_raw_json_is_failed_evidence(raw, expected):
    left = FakeProvider("left", raw=True)
    def hook(op, n, value):
        if op.action == "READ" and op.path_id == "boot_id":
            value["raw"] = raw
            value["sha256"] = hashlib.sha256(raw).hexdigest()
        return value
    left.hook = hook
    reason(run(left=left), expected)


@pytest.mark.parametrize("code", bridge.PROVIDER_ERRORS)
def test_closed_error_envelopes_are_retained(code):
    left = FakeProvider("left")
    def hook(op, n, value):
        if op.action == "READ" and op.path_id == "boot_id":
            value.update(status="ERROR", reason=code, payload=None, raw=None, sha256=None)
        return value
    left.hook = hook
    output = run(left=left)
    reason(output, code)
    record = output["observations"][0]
    assert record["provider_status"] == "ERROR" and record["provider_reason"] == code


@pytest.mark.parametrize("kind", ["raw", "items", "depth", "string", "cycle"])
def test_payload_quotas_reject_without_truncating(kind):
    left = FakeProvider("left")
    def hook(op, n, value):
        if op.action != "READ":
            return value
        if kind == "raw":
            value["raw"] = b"x" * (bridge.MAX_RAW_BYTES + 1)
        elif kind == "items":
            value["payload"] = [0] * (bridge.MAX_NODES + 1)
        elif kind == "depth":
            nested = None
            for _ in range(bridge.MAX_DEPTH + 1):
                nested = [nested]
            value["payload"] = nested
        elif kind == "string":
            value["payload"] = "x" * (bridge.MAX_BYTES + 1)
        else:
            value["payload"] = [value]
        return value
    left.hook = hook
    output = run(left=left)
    reason(output, "INPUT_NOT_JSON" if kind == "cycle" else "INPUT_CAP_EXCEEDED")
    assert all(r["payload"] is None for r in output["observations"] if r["provider_index"] == 0)


@pytest.mark.parametrize("action", ["OPEN", "DESCRIBE", "READ", "CLOSE"])
@pytest.mark.parametrize("error", [ValueError, RuntimeError, OSError])
def test_callback_exceptions_fail_evidence_and_close_without_retry(action, error):
    left = FakeProvider("left")
    def hook(op, n, value):
        if op.action == action:
            raise error(SECRET)
        return value
    left.hook = hook
    output = run(left=left)
    reason(output, "CLOSE_FAILED" if action == "CLOSE" else "READ_FAILED" if error is OSError else "CALLBACK_EXCEPTION")
    if action != "OPEN":
        assert len([op for op in left.calls if op.action == "CLOSE"]) == 16


@pytest.mark.parametrize("action", ["DESCRIBE", "READ", "CLOSE"])
@pytest.mark.parametrize("close_failure", [False, True])
def test_baseexception_escapes_after_cleanup_even_if_close_raises(action, close_failure):
    left, right, clock = FakeProvider("left"), FakeProvider("right"), FakeClock()
    original = HarnessViolation("original fake-I/O assertion")
    def hook(op, n, value):
        if op.action == action:
            raise original
        if op.action == "CLOSE" and close_failure:
            raise RuntimeError(SECRET)
        return value
    left.hook = hook
    with pytest.raises(HarnessViolation) as caught:
        bridge.acquire_provenance_bridge(roster(), request(), providers=(left.configured(), right.configured()), clock=clock)
    assert caught.value is original
    assert not left.active and not right.active
    assert len([op for op in left.calls if op.action == "CLOSE"]) == 1


def test_original_baseexception_survives_a_second_baseexception_during_close():
    left, right = FakeProvider("left"), FakeProvider("right")
    original = HarnessViolation("read assertion")
    def hook(op, n, value):
        if op.action == "READ":
            raise original
        if op.action == "CLOSE":
            raise HarnessViolation("cleanup assertion")
        return value
    left.hook = hook
    with pytest.raises(HarnessViolation) as caught:
        bridge.acquire_provenance_bridge(roster(), request(), providers=(left.configured(), right.configured()), clock=FakeClock())
    assert caught.value is original and not left.active


@pytest.mark.parametrize("at_tick", [1, 2])
def test_clock_baseexception_propagates_with_no_open_handles(at_tick):
    left, right, clock = FakeProvider("left"), FakeProvider("right"), FakeClock()
    def hook(n):
        if n == at_tick:
            raise HarnessViolation("clock assertion")
        return 1000 + n
    clock.hook = hook
    with pytest.raises(HarnessViolation):
        bridge.acquire_provenance_bridge(roster(), request(), providers=(left.configured(), right.configured()), clock=clock)
    assert not left.active and not right.active


@pytest.mark.parametrize("value", [None, True, -1, 1.5, "1000", bridge.U64 + 1])
def test_invalid_clock_never_opens_handles(value):
    clock, left = FakeClock(), FakeProvider("left")
    clock.hook = lambda n: value
    output = run(clock=clock, left=left)
    reason(output, "CLOCK_FAILURE")
    assert not left.calls and clock.calls == 1


@pytest.mark.parametrize("case", ["regression", "exception", "read_skew", "source_skew", "gap", "age", "elapsed"])
def test_clock_windows_and_elapsed_budget(case):
    data, clock = request(), FakeClock()
    if case == "regression":
        clock.hook = lambda n: 1000 if n == 1 else 999
    elif case == "exception":
        def fail(n):
            raise RuntimeError(SECRET)
        clock.hook = fail
    elif case == "read_skew":
        clock.hook = lambda n: 1000 + n * 101
        data["limits"]["max_gap_ns"] = 1000
    elif case == "source_skew":
        data["limits"]["max_source_skew_ns"] = 1
    elif case == "gap":
        clock.hook = lambda n: 1000 + n + (1000 if n >= 3 else 0)
    elif case == "age":
        data["limits"]["max_age_ns"] = 1
    else:
        data["limits"]["max_elapsed_ns"] = 1
    expected = {"regression": "CLOCK_REGRESSION", "exception": "CLOCK_FAILURE", "read_skew": "READ_SKEW_EXCEEDED",
                "source_skew": "READ_SKEW_EXCEEDED", "gap": "READ_GAP_EXCEEDED", "age": "STALE_READING",
                "elapsed": "ELAPSED_CAP_EXCEEDED"}[case]
    reason(run(data=data, clock=clock), expected)


@pytest.mark.parametrize("field", ["payload", "sha256", "descriptor"])
def test_retained_source_mutation_after_acquisition_is_rejected(field):
    left, right = FakeProvider("left"), FakeProvider("right")
    def hook(op, n, value):
        if op.action == "CLOSE" and op.sweep == 1 and op.path_id == "boot_id":
            target = next(v for v in left.emitted if type(v) is dict and ("path_id" in v if field == "descriptor" else "payload" in v))
            if field == "descriptor":
                target["st_ino"] = 999
            elif field == "payload":
                target["payload"]["boot_id"] = "00000000-0000-0000-0000-000000000000"
            else:
                target["sha256"] = "0" * 64
        return value
    right.hook = hook
    output = run(left=left, right=right)
    reason(output, "INPUT_CHANGED")
    assert output["observations"][0]["payload"] == {"boot_id": BOOT}


def test_retained_integer_to_boolean_mutation_is_not_hidden_by_python_equality():
    left, right = FakeProvider("left"), FakeProvider("right")
    def hook(op, n, value):
        if op.action == "CLOSE" and op.sweep == 1 and op.path_id == "boot_id":
            target = next(v for v in left.emitted if type(v) is dict and "sequence" in v)
            assert target["sequence"] == 1
            target["sequence"] = True
        return value
    right.hook = hook
    reason(run(left=left, right=right), "INPUT_CHANGED")


def test_request_mutation_by_callback_is_rejected_and_output_detached():
    data, left, right = request(), FakeProvider("left"), FakeProvider("right")
    def hook(op, n, value):
        if op.action == "CLOSE":
            data["limits"]["max_age_ns"] = 99999
        return value
    left.hook = hook
    output = bridge.acquire_provenance_bridge(roster(), data,
        providers=(left.configured(), right.configured()), clock=FakeClock()).to_dict()
    reason(output, "INPUT_CHANGED")


def test_unknown_internal_reason_is_sealed(monkeypatch):
    left = FakeProvider("left")
    def fail(op, n, value):
        if op.action == "READ":
            raise RuntimeError(SECRET)
        return value
    left.hook = fail
    monkeypatch.setattr(bridge, "_exception", lambda *args: SECRET)
    reason(run(left=left), "REASON_CODE_INVALID")


@pytest.mark.parametrize("key", ["paths", "root", "roster_complete", "frame_windows"])
def test_custom_request_fields_never_trigger_io(key):
    data, left, clock = request(), FakeProvider("left"), FakeClock()
    data[key] = "/proc"
    output = run(data=data, left=left, clock=clock)
    assert output["reason_codes"] == ["SCHEMA_INVALID"]
    assert left.calls == [] and clock.calls == 0


@pytest.mark.parametrize("slot", ["clock", "left", "right", "missing_provider"])
def test_missing_callback_configuration_denied_before_acquisition(slot):
    left, right, clock = FakeProvider("left"), FakeProvider("right"), FakeClock()
    configured = [left.configured(), right.configured()]
    selected_clock = clock
    if slot == "clock":
        selected_clock = None
    elif slot == "missing_provider":
        configured.pop()
    else:
        configured[0 if slot == "left" else 1] = (left if slot == "left" else right).configured(callback=None)
    output = bridge.acquire_provenance_bridge(roster(), request(), providers=configured, clock=selected_clock).to_dict()
    assert output["reason_codes"] == ["CALLBACK_CONTRACT_INVALID"]
    assert not left.calls and not right.calls and clock.calls == 0


@pytest.mark.parametrize("kind", ["empty", "duplicate", "too_many", "schema_invalid"])
def test_closed_registered_roster_validation_before_io(kind):
    identities = roster()
    if kind == "empty":
        identities = []
    elif kind == "duplicate":
        identities.append(copy.deepcopy(identities[0]))
    elif kind == "too_many":
        identities = [{"pid": 100 + n, "ppid": 1, "starttime_ticks": n} for n in range(bridge.MAX_PROCESSES + 1)]
    else:
        identities[0]["ppid"] = identities[0]["pid"]
    left, clock = FakeProvider("left", identities), FakeClock()
    output = run(identities=identities, left=left, clock=clock)
    assert output["outcome"] == "INVALID" and not left.calls and clock.calls == 0


def test_maximum_registered_roster_is_bounded_and_structurally_consistent():
    identities = [{"pid": 100 + n, "ppid": 1, "starttime_ticks": n} for n in range(bridge.MAX_PROCESSES)]
    output = run(identities=identities)
    assert output["reason_codes"] == []
    assert len(output["observations"]) == bridge.MAX_READS


def test_deterministic_serialization_frozen_report_and_detached_copies():
    def acquire():
        left, right = FakeProvider("left", raw=True), FakeProvider("right", raw=True)
        return bridge.acquire_provenance_bridge(roster(), request(), providers=(left.configured(), right.configured()), clock=FakeClock())
    first, second = acquire(), acquire()
    assert first.serialized == second.serialized
    assert first.serialized == bridge.canonical_json(first.to_dict())
    detached = first.to_dict()
    detached["observations"][0]["payload"]["boot_id"] = "changed"
    detached["registered_roster"].clear()
    assert first.to_dict() == second.to_dict()
    with pytest.raises(FrozenInstanceError):
        first.serialized = "changed"


def test_canonical_serialization_matches_predecessor_convention():
    value = {"z": [1, None, False], "a": "é"}
    assert bridge.canonical_json(value) == json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
