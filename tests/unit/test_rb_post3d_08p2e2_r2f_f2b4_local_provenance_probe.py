"""Artificial-only B3-A contract and B2 rejection regression cases.

Execution belongs to the orchestrator, after independent review.
"""

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

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_local_provenance_probe as probe
from tests.unit import test_rb_post3d_08p2e2_r2f_f2b4_native_provenance as b2

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_local_provenance_probe.py"
SECRET = "SECRET-must-never-be-echoed"


class HarnessViolation(BaseException):
    pass


@pytest.fixture(autouse=True)
def forbid_native_io(monkeypatch):
    violations = []

    def blocked(*args, **kwargs):
        violations.append("forbidden native operation")
        raise HarnessViolation("forbidden native operation")

    def path_guard(original):
        def wrapped(*args, **kwargs):
            path = args[0] if args else kwargs.get("file", kwargs.get("path"))
            if isinstance(path, (str, bytes, os.PathLike)):
                name = os.fsdecode(path)
                if name in ("/proc", "/sys") or name.startswith(("/proc/", "/sys/")):
                    blocked()
            return original(*args, **kwargs)
        return wrapped

    # These patches last only for this test. stat/lstat guards are path-aware
    # so pytest's repository-source handling is unaffected.
    with monkeypatch.context() as guard:
        for name in ("open", "read", "readlink", "listdir", "scandir", "sysconf", "system",
                     "fork", "posix_spawn", "posix_spawnp", "setns", "unshare"):
            if hasattr(os, name):
                guard.setattr(os, name, blocked)
        for obj, name in ((builtins, "open"), (io, "open"), (os, "stat"), (os, "lstat")):
            guard.setattr(obj, name, path_guard(getattr(obj, name)))
        for obj, names in ((time, ("monotonic_ns", "monotonic", "time_ns", "perf_counter_ns",
                                  "clock_gettime", "clock_gettime_ns")),
                           (subprocess, ("Popen", "run", "call", "check_call", "check_output")),
                           (socket, ("socket", "create_connection"))):
            for name in names:
                if hasattr(obj, name):
                    guard.setattr(obj, name, blocked)
        guard.setattr(b2.adapter, "_NativeIO", blocked)
        yield violations
    assert violations == []


def identity(pid):
    return {"pid": pid, "ppid": 1 if pid in (100, 1000) else 100, "starttime_ticks": pid // 10}


def request():
    return {"schema": probe.SCHEMA, "source_kind": "INJECTED", "clock_domain": probe.CLOCK_DOMAIN,
            "context": identity(1000), "targets": [identity(100), identity(200)], "roster_complete": True,
            "limits": {"max_age_ns": 2000000000, "max_read_skew_ns": 1000, "max_frame_gap_ns": 10000},
            "frame_windows": [{"start_ns": 0, "end_ns": 1}]}


class FakeProbe:
    """Exact symbolic allowlist. No strings are interpreted as OS paths/fds."""

    def __init__(self, data=None):
        data = request() if data is None else data
        self.identities = {p["pid"]: copy.deepcopy(p) for p in [data["context"]] + data["targets"]}
        self.paths = {"boot_id", "mount"}
        self.paths.update(f"pids/{pid}/{leaf}" for pid in self.identities for leaf in ("identity", "namespace"))
        self.calls, self.counts = [], {}
        self.tick = 1000000100
        self.reader_hook = None
        self.descriptor_hook = None
        self.clock_hook = None

    def require(self, path):
        if type(path) is not str or path not in self.paths:
            raise HarnessViolation("unallowlisted artificial path")

    def descriptor(self, path):
        self.require(path)
        self.calls.append(("descriptor", path))
        key = ("descriptor", path)
        n = self.counts.get(key, 0)
        self.counts[key] = n + 1
        namespace = path.endswith("/namespace")
        value = {"path": path, "st_dev": 4 if namespace else 5,
                 "st_ino": 77 if namespace else sorted(self.paths).index(path) + 100,
                 "mount_id": 10 if namespace else 9, "filesystem": "nsfs" if namespace else "proc",
                 "mount_path": "namespace_target" if namespace else "proc", "symlink": False,
                 "binding": "INJECTED_PREBOUND_NO_FOLLOW",
                 "read_method": "INJECTED_NAMESPACE_TARGET_DESCRIPTOR" if namespace else "INJECTED_BOUND_DESCRIPTOR"}
        return self.descriptor_hook(path, n, value) if self.descriptor_hook else value

    def read(self, path, limit):
        self.require(path)
        if type(limit) is not int or limit != probe.MAX_READ_BYTES + 1:
            raise HarnessViolation("unbounded artificial read")
        self.calls.append(("read", path))
        key = ("read", path)
        n = self.counts.get(key, 0)
        self.counts[key] = n + 1
        if path == "boot_id":
            value = {"boot_id": b2.BOOT}
        elif path == "mount":
            value = {"mount_id": 9, "filesystem": "proc", "mount_path": "proc", "descriptor_dev": 5}
        elif path.endswith("/namespace"):
            value = {"st_dev": 4, "st_ino": 77, "read_method": "INJECTED_NAMESPACE_TARGET_DESCRIPTOR"}
        else:
            value = self.identities[int(path.split("/")[1])].copy()
        if self.reader_hook:
            value = self.reader_hook(path, n, value)
        return value if type(value) is bytes else json.dumps(value, sort_keys=True).encode()

    def clock(self):
        self.calls.append(("clock",))
        self.tick += 1
        return self.clock_hook(self.tick) if self.clock_hook else self.tick


def run(data=None, fake=None, reference=None):
    data = request() if data is None else data
    fake = FakeProbe(data) if fake is None else fake
    before = copy.deepcopy([data, reference])
    result = probe.probe_local_provenance(data, reader=fake.read, descriptor=fake.descriptor,
                                          clock=fake.clock, reference=reference)
    assert [data, reference] == before
    output = result.to_dict()
    assert output["qualification"] == "NONQUALIFYING"
    assert output["source_kind"] == "INJECTED_LOCAL_PROBE"
    assert output["reason_codes"] == sorted(set(output["reason_codes"]))
    assert_reason_partition(output)
    for forbidden in (SECRET, "NATIVE_SOURCE_VERIFIED", "PRODUCTION_CHRONOLOGY_ASSESSED",
                      "VERIFIED_BY_INDEPENDENT_PROBE"):
        assert forbidden not in result.serialized
    assert len(output["reads"]) <= probe.MAX_READS
    assert len([c for c in fake.calls if c[0] == "read"]) <= probe.MAX_READS
    assert len([c for c in fake.calls if c[0] == "descriptor"]) <= 2 * probe.MAX_READS
    assert len([c for c in fake.calls if c[0] == "clock"]) <= 2 * probe.MAX_READS + 1
    return output


def assert_reason_partition(output):
    invalid, incomplete = set(output["invalid_reason_codes"]), set(output["incomplete_reason_codes"])
    assert not invalid & incomplete
    assert set(output["reason_codes"]) == invalid | incomplete
    assert output["invalid_reason_codes"] == sorted(invalid)
    assert output["incomplete_reason_codes"] == sorted(incomplete)
    assert output["reason_codes"] == sorted(output["invalid_reason_codes"] + output["incomplete_reason_codes"])
    assert invalid <= set(probe.INVALID_CODES)
    assert incomplete <= set(probe.INCOMPLETE_CODES)
    assert not set(probe.INVALID_CODES) & set(probe.INCOMPLETE_CODES)


def assert_reason(output, code, outcome=None):
    assert_reason_partition(output)
    assert code in output["reason_codes"]
    if outcome is not None:
        assert output["outcome"] == outcome
    assert code in output["invalid_reason_codes"] + output["incomplete_reason_codes"]


def test_consistent_synthetic_probe_is_only_nonqualifying():
    fake = FakeProbe()
    output = run(fake=fake)
    assert output["outcome"] == "CONSISTENT"
    assert output["reason_codes"] == []
    assert output["trust_level"] == "INJECTED_LOCAL_PROBE"
    assert output["context_pid"] == 1000 and output["target_pids"] == [100, 200]
    assert output["context_identity"] == identity(1000)
    assert output["target_identities"] == [identity(100), identity(200)]
    assert output["input_sha256"] == digest(request())
    assert len(output["reads"]) == 16
    assert all(r["descriptor_stable"] and r["failure_codes"] == [] for r in output["reads"])
    assert all(r["start_ns"] <= r["end_ns"] and r["provenance"] == "INJECTED_LOCAL_PROBE" for r in output["reads"])
    assert output["native_adapter"] == output["independent_trust_root_gate"] == "NOT_IMPLEMENTED"
    assert output["procfs_mount_authenticated"] is output["namespace_authenticated"] is False
    assert output["mount_namespace_binding"] == "UNVERIFIED"
    assert output["production_memory_qualification"] == "INCONCLUSIVE"
    assert output["production_chronological_peak"] == "NOT_OBSERVED"
    assert output["holder_release"] == output["rss_reclamation"] == output["worker_discovery"] == "NOT_ESTABLISHED"
    assert output["atomic_snapshot"] is output["worker_absence_proven"] is False


def test_import_is_inert_and_module_has_no_native_capability():
    importlib.reload(probe)
    tree = ast.parse(MODULE_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            assert not {"os", "time", "sys", "ctypes", "socket", "subprocess", "pathlib"} & set(names)
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            assert name not in ("open", "openat", "fork", "spawn", "stat", "lstat", "readlink", "sysconf", "eval", "exec")
    assert all(not isinstance(n, ast.Expr) or not isinstance(n.value, ast.Call) for n in tree.body)
    assert all(not isinstance(n, ast.Assign) or not isinstance(n.value, ast.Call) for n in tree.body)


@pytest.mark.parametrize("operation", [
    lambda: builtins.open("/proc/self/stat"), lambda: io.open("/sys/fs/cgroup/memory.current"),
    lambda: Path("/proc/self/status").read_bytes(), lambda: os.open("stat", 0, dir_fd=123),
    lambda: os.read(123, 1), lambda: os.readlink("/proc/self/ns/pid"), lambda: os.stat("/proc/self"),
    lambda: os.lstat("/sys"), lambda: time.monotonic_ns(), lambda: time.time_ns(),
    lambda: subprocess.Popen(["forbidden"]), lambda: socket.socket(),
])
def test_guard_negative_controls(operation, forbid_native_io):
    with pytest.raises(HarnessViolation):
        operation()
    assert forbid_native_io == ["forbidden native operation"]
    forbid_native_io.clear()


@pytest.mark.parametrize("path", ["/proc", "../boot_id", "pids/999/identity", "pids/100/status", "self", "mount/extra"])
def test_fixture_cannot_perform_unallowlisted_io(path):
    fake = FakeProbe()
    with pytest.raises(HarnessViolation):
        fake.read(path, 4097)
    with pytest.raises(HarnessViolation):
        fake.descriptor(path)
    with pytest.raises(HarnessViolation):
        fake.read("boot_id", 0)


@pytest.mark.parametrize("where", ["reader", "descriptor"])
@pytest.mark.parametrize("error,code", [(PermissionError, "PERMISSION_DENIED"), (FileNotFoundError, "PROCESS_VANISHED"),
    (ProcessLookupError, "PROCESS_VANISHED"), (OSError, "READ_FAILED"), (ValueError, "CALLBACK_EXCEPTION"),
    (RuntimeError, "CALLBACK_EXCEPTION")])
def test_callback_exceptions_are_sealed_and_never_retried(where, error, code):
    fake = FakeProbe()

    def fail(*args):
        raise error(SECRET)

    setattr(fake, where + "_hook", fail)
    output = run(fake=fake)
    assert output["invalid_reason_codes"] == []
    assert_reason(output, code, "INCOMPLETE")
    assert all(r["failure_codes"] == [code] for r in output["reads"])
    # Two sweeps, one invocation per read or descriptor-before; no retries.
    assert all(n == 2 for (kind, _), n in fake.counts.items() if kind == ("read" if where == "reader" else "descriptor"))


@pytest.mark.parametrize("where", ["reader", "descriptor", "clock"])
@pytest.mark.parametrize("callback", [None, 0, "not-callable", {}])
def test_missing_or_noncallable_callbacks_fail_before_any_io(where, callback):
    fake = FakeProbe()
    callbacks = {"reader": fake.read, "descriptor": fake.descriptor, "clock": fake.clock}
    callbacks[where] = callback
    output = probe.probe_local_provenance(request(), **callbacks).to_dict()
    assert_reason(output, "READER_CONTRACT_VIOLATION", "INVALID")
    assert output["reason_codes"] == ["READER_CONTRACT_VIOLATION"]
    assert output["reads"] == [] and fake.calls == []


@pytest.mark.parametrize("where", ["reader", "descriptor_before", "descriptor_after"])
@pytest.mark.parametrize("error,code", [
    (OSError(errno.ELOOP, SECRET), "SYMLINK_REJECTED"),
    (NotADirectoryError(errno.ENOTDIR, SECRET), "PATH_POLICY_VIOLATION"),
])
def test_path_resolution_errors_are_invalid(where, error, code):
    fake = FakeProbe()

    def fail(path, n, value):
        if where != "descriptor_after" or n % 2 == 1:
            raise error
        return value

    setattr(fake, "reader_hook" if where == "reader" else "descriptor_hook", fail)
    output = run(fake=fake)
    assert output["reason_codes"] == [code]
    assert_reason(output, code, "INVALID")
    assert "READ_FAILED" not in output["reason_codes"]
    assert all(r["failure_codes"] == [code] for r in output["reads"])


@pytest.mark.parametrize("where", ["read", "aggregate"])
def test_unknown_reason_is_sealed_and_cannot_produce_consistent(monkeypatch, where):
    fake = FakeProbe()
    unknown = "UNKNOWN_" + SECRET + "_NATIVE_SOURCE_VERIFIED"
    if where == "read":
        def fail(*args):
            raise RuntimeError(SECRET)

        fake.reader_hook = fail
        monkeypatch.setattr(probe, "_exception", lambda exc: unknown)
    else:
        original = probe._windows

        def add_unknown(windows, gap, codes):
            original(windows, gap, codes)
            codes.update((unknown, "ROSTER_INCOMPLETE"))

        monkeypatch.setattr(probe, "_windows", add_unknown)
    output = run(fake=fake)
    assert_reason(output, "REASON_CODE_INVALID", "INVALID")
    assert output["invalid_reason_codes"] == ["REASON_CODE_INVALID"]
    assert output["incomplete_reason_codes"] == ([] if where == "read" else ["ROSTER_INCOMPLETE"])
    if where == "read":
        assert all(r["failure_codes"] == ["REASON_CODE_INVALID"] for r in output["reads"])


@pytest.mark.parametrize("where", ["reader", "descriptor", "clock"])
def test_baseexception_guards_escape(where):
    fake = FakeProbe()

    def fail(*args):
        raise HarnessViolation("guard")

    setattr(fake, where + "_hook", fail)
    with pytest.raises(HarnessViolation):
        run(fake=fake)


@pytest.mark.parametrize("raw,code", [(b"\xff", "INVALID_UTF8"), (b"{}\x00", "INPUT_NOT_JSON"),
    (b'{"boot_id":"\\ud800"}', "INPUT_NOT_JSON"), (b'{"a":1,"a":2}', "DUPLICATE_FIELD"),
    (b"x" * 4097, "INPUT_CAP_EXCEEDED"), (b"NaN", "INPUT_NOT_JSON"), (b"[]", "SCHEMA_INVALID")])
def test_binary_and_json_read_failures(raw, code):
    fake = FakeProbe()
    fake.reader_hook = lambda path, n, value: raw
    assert_reason(run(fake=fake), code, "INVALID")


@pytest.mark.parametrize("value", ["bytes-required", None, True, bytearray(b"{}"), memoryview(b"{}")])
def test_reader_must_return_exact_bytes(value):
    fake = FakeProbe()
    fake.read = lambda path, limit: value
    assert_reason(run(fake=fake), "READER_CONTRACT_VIOLATION", "INVALID")


@pytest.mark.parametrize("field,value,code", [
    ("path", "../" + SECRET, "PATH_POLICY_VIOLATION"), ("path", "/proc/self", "PATH_POLICY_VIOLATION"),
    ("symlink", True, "SYMLINK_REJECTED"), ("symlink", 1, "DESCRIPTOR_INVALID"),
    ("filesystem", "sysfs", "MOUNT_MISMATCH"), ("mount_path", "elsewhere", "MOUNT_MISMATCH"),
    ("st_ino", True, "INTEGER_INVALID"), ("binding", "FOLLOW_SYMLINKS", "DESCRIPTOR_INVALID"),
    ("read_method", "pid:[77]", "NAMESPACE_METHOD_INVALID"),
])
def test_descriptor_contract(field, value, code):
    fake = FakeProbe()
    fake.descriptor_hook = lambda path, n, desc: {**desc, field: value}
    assert_reason(run(fake=fake), code, "INVALID")


@pytest.mark.parametrize("field", ["st_dev", "st_ino", "mount_id"])
@pytest.mark.parametrize("boundary", ["during_read", "between_sweeps"])
def test_descriptor_races(field, boundary):
    fake = FakeProbe()

    def change(path, n, desc):
        changed = n % 2 == 1 if boundary == "during_read" else n >= 2
        if changed:
            desc[field] += 1
        return desc

    fake.descriptor_hook = change
    assert_reason(run(fake=fake), "DESCRIPTOR_CHANGED", "INVALID")


def test_swapped_mount_with_internally_matching_id_is_still_rejected():
    fake = FakeProbe()
    fake.descriptor_hook = lambda path, n, desc: {**desc, "mount_id": 88} if path.startswith("pids/200/") else desc
    assert_reason(run(fake=fake), "MOUNT_MISMATCH", "INVALID")


def test_duplicate_non_namespace_descriptors_are_rejected():
    fake = FakeProbe()
    fake.descriptor_hook = lambda path, n, desc: {**desc, "st_ino": 999} if not path.endswith("/namespace") else desc
    assert_reason(run(fake=fake), "DESCRIPTOR_ALIAS", "INVALID")


def test_linux_faithful_nsfs_target_is_separate_from_procfs_mount():
    fake = FakeProbe()
    target = fake.descriptor("pids/100/namespace")
    leaf = fake.descriptor("pids/100/identity")
    assert (target["filesystem"], target["mount_path"]) == ("nsfs", "namespace_target")
    assert (leaf["filesystem"], leaf["mount_path"]) == ("proc", "proc")
    assert (leaf["mount_id"], leaf["st_dev"]) == (9, 5)
    assert (target["mount_id"], target["st_dev"]) == (10, 4)
    assert target["symlink"] is False  # Metadata is for the resolved target, not the link.
    output = run(fake=fake)
    assert output["outcome"] == "CONSISTENT"
    assert output["reason_codes"] == output["invalid_reason_codes"] == output["incomplete_reason_codes"] == []
    assert output["mount_namespace_binding"] == "UNVERIFIED"
    assert output["procfs_mount_authenticated"] is output["namespace_authenticated"] is False


@pytest.mark.parametrize("leaf", ["boot_id", "pids/200/identity"])
def test_namespace_target_cannot_alias_any_procfs_leaf_in_sweep(leaf):
    fake = FakeProbe()
    inode = sorted(fake.paths).index(leaf) + 100
    fake.descriptor_hook = lambda path, n, desc: {**desc, "st_dev": 5, "st_ino": inode} if path.endswith("/namespace") else desc
    fake.reader_hook = lambda path, n, value: {**value, "st_dev": 5, "st_ino": inode} if path.endswith("/namespace") else value
    assert_reason(run(fake=fake), "DESCRIPTOR_ALIAS", "INVALID")


@pytest.mark.parametrize("namespace", [False, True])
def test_same_mount_id_with_different_device_is_impossible(namespace):
    fake = FakeProbe()

    def impossible(path, n, desc):
        if namespace and path.endswith("/namespace"):
            return {**desc, "mount_id": 9}  # nsfs device 4 cannot be procfs mount 9/device 5.
        if not namespace and path == "pids/200/identity":
            return {**desc, "st_dev": 6}  # Nor can another procfs leaf change device on mount 9.
        return desc

    fake.descriptor_hook = impossible
    assert_reason(run(fake=fake), "MOUNT_MISMATCH", "INVALID")


@pytest.mark.parametrize("namespace", [False, True])
def test_same_device_cannot_be_procfs_and_nsfs_on_different_mounts(namespace):
    fake = FakeProbe()

    def collide(path, n, desc):
        if path.endswith("/namespace") == namespace:
            return {**desc, "st_dev": 5 if namespace else 4}
        return desc

    def matching_payload(path, n, value):
        if namespace and path.endswith("/namespace"):
            return {**value, "st_dev": 5}
        if not namespace and path == "mount":
            return {**value, "descriptor_dev": 4}
        return value

    # Keep mount IDs 9/10 and distinct inodes: only device/filesystem coherence fails.
    fake.descriptor_hook = collide
    fake.reader_hook = matching_payload
    output = run(fake=fake)
    assert_reason(output, "MOUNT_MISMATCH", "INVALID")
    assert output["reason_codes"] == output["invalid_reason_codes"] == ["MOUNT_MISMATCH"]
    assert output["incomplete_reason_codes"] == []
    assert output["trust_level"] == "CALLER_ASSERTED_ONLY"


@pytest.mark.parametrize("proc_first", [False, True])
@pytest.mark.parametrize("alias", [False, True])
def test_device_filesystem_collision_and_alias_checks_span_usable_sweeps(proc_first, alias):
    fake = FakeProbe()
    inode = sorted(fake.paths).index("boot_id") + 100 if alias else 77

    def namespace_target(path, n, desc):
        return {**desc, "st_dev": 5, "st_ino": inode} if path.endswith("/namespace") else desc

    def disjoint_usable_sweeps(path, n, value):
        namespace_sweep = n == (1 if proc_first else 0)
        if path.endswith("/namespace") != namespace_sweep:
            raise PermissionError("artificial unavailable sweep")
        return {**value, "st_dev": 5, "st_ino": inode} if path.endswith("/namespace") else value

    # Neither sweep alone has usable descriptors from both filesystems. No path
    # is usable twice, so DESCRIPTOR_CHANGED cannot mask the cross-sweep checks.
    fake.descriptor_hook = namespace_target
    fake.reader_hook = disjoint_usable_sweeps
    output = run(fake=fake)
    invalid = sorted(["MOUNT_MISMATCH"] + (["DESCRIPTOR_ALIAS"] if alias else []))
    assert output["outcome"] == "INVALID"
    assert output["invalid_reason_codes"] == invalid
    assert output["incomplete_reason_codes"] == ["PERMISSION_DENIED"]
    assert output["reason_codes"] == sorted(invalid + ["PERMISSION_DENIED"])
    assert output["trust_level"] == "CALLER_ASSERTED_ONLY"


@pytest.mark.parametrize("value", [None, True, "metadata", [], {"unexpected": "x"}])
def test_malformed_descriptor_return_is_safe(value):
    fake = FakeProbe()
    fake.descriptor_hook = lambda path, n, desc: value
    assert_reason(run(fake=fake), "SCHEMA_INVALID", "INVALID")


def test_descriptor_buffer_cap_is_enforced_before_schema():
    fake = FakeProbe()
    fake.descriptor_hook = lambda path, n, desc: {**desc, "extra": "x" * 4097}
    assert_reason(run(fake=fake), "INPUT_CAP_EXCEEDED", "INVALID")


@pytest.mark.parametrize("key,value,code", [("mount_id", 88, "MOUNT_MISMATCH"),
    ("descriptor_dev", 88, "MOUNT_MISMATCH"), ("filesystem", "tmpfs", "MOUNT_MISMATCH"),
    ("mount_path", "../proc", "MOUNT_MISMATCH")])
def test_mount_payload_must_match_descriptor(key, value, code):
    fake = FakeProbe()
    fake.reader_hook = lambda path, n, raw: {**raw, key: value} if path == "mount" else raw
    assert_reason(run(fake=fake), code, "INVALID")


@pytest.mark.parametrize("key,value,code,outcome", [
    ("pid", 300, "IDENTITY_CONTRADICTION", "INVALID"),
    ("pid", 1000, "IDENTITY_CONTRADICTION", "INVALID"),
    ("ppid", 101, "PROCESS_REPARENTED", "INCOMPLETE"),
    ("starttime_ticks", 999, "PID_REUSE", "INCOMPLETE"),
])
def test_identity_changes_never_pass(key, value, code, outcome):
    fake = FakeProbe()
    fake.reader_hook = lambda path, n, raw: {**raw, key: value} if path == "pids/200/identity" and n == 1 else raw
    output = run(fake=fake)
    assert_reason(output, code, outcome)
    assert output["reason_codes"] == [code]
    assert output["invalid_reason_codes"] == ([code] if outcome == "INVALID" else [])
    assert output["incomplete_reason_codes"] == ([code] if outcome == "INCOMPLETE" else [])
    assert output["trust_level"] == ("CALLER_ASSERTED_ONLY" if outcome == "INVALID" else "INJECTED_LOCAL_PROBE")
    assert "UNKNOWN_PROCESS" in probe.INCOMPLETE_CODES and "UNKNOWN_PROCESS" not in probe.INVALID_CODES


def test_boot_identity_changes_between_sweeps():
    fake = FakeProbe()
    fake.reader_hook = lambda path, n, raw: {"boot_id": b2.OTHER_BOOT} if path == "boot_id" and n == 1 else raw
    assert_reason(run(fake=fake), "BOOT_ID_CHANGED", "INCOMPLETE")


def test_namespace_target_and_context_mismatch():
    fake = FakeProbe()
    fake.reader_hook = lambda path, n, raw: {**raw, "st_ino": 88} if path == "pids/200/namespace" else raw
    fake.descriptor_hook = lambda path, n, desc: {**desc, "st_ino": 88} if path == "pids/200/namespace" else desc
    assert_reason(run(fake=fake), "NAMESPACE_MISMATCH", "INCOMPLETE")


def test_namespace_payload_cannot_substitute_target_descriptor_identity():
    fake = FakeProbe()
    fake.reader_hook = lambda path, n, raw: {**raw, "st_ino": 88} if path.endswith("/namespace") else raw
    assert_reason(run(fake=fake), "NAMESPACE_DESCRIPTOR_MISMATCH", "INVALID")


def test_textual_namespace_is_not_a_certificate():
    fake = FakeProbe()
    fake.reader_hook = lambda path, n, raw: "pid:[77]" if path.endswith("/namespace") else raw
    assert_reason(run(fake=fake), "SCHEMA_INVALID", "INVALID")


@pytest.mark.parametrize("value", [None, True, "1", -1, probe.U64 + 1])
def test_clock_contract(value):
    fake = FakeProbe()
    fake.clock_hook = lambda tick: value
    output = run(fake=fake)
    assert_reason(output, "CLOCK_FAILURE", "INVALID")
    assert_reason(output, "COVERAGE_UNBOUNDED")
    assert all(r["start_ns"] is r["end_ns"] is None for r in output["reads"])
    assert not any(c[0] == "read" for c in fake.calls)


def test_clock_callback_exception_has_no_message_leak():
    fake = FakeProbe()

    def fail(tick):
        raise RuntimeError(SECRET)

    fake.clock_hook = fail
    assert_reason(run(fake=fake), "CLOCK_FAILURE", "INVALID")


def test_clock_regression_keeps_missing_end_without_invention():
    fake = FakeProbe()
    fake.clock_hook = lambda tick: 0 if tick == 1000000102 else tick
    output = run(fake=fake)
    assert_reason(output, "CLOCK_REGRESSION", "INVALID")
    assert output["reads"][0]["start_ns"] == 1000000101
    assert output["reads"][0]["end_ns"] is None


@pytest.mark.parametrize("key,code", [("max_age_ns", "STALE_READING"), ("max_read_skew_ns", "READ_SKEW_EXCEEDED")])
def test_stale_or_skewed_reads_are_incomplete(key, code):
    data = request()
    data["limits"][key] = 0
    assert_reason(run(data), code, "INCOMPLETE")


@pytest.mark.parametrize("missing", ["start_ns", "end_ns", "both"])
def test_missing_timestamp_across_gap_never_proves_bounded_coverage(missing):
    data = request()
    middle = {"start_ns": 3, "end_ns": 4}
    for key in middle:
        if missing in (key, "both"):
            middle[key] = None
    data["frame_windows"] = [{"start_ns": 0, "end_ns": 1}, middle, {"start_ns": 100, "end_ns": 101}]
    data["limits"]["max_frame_gap_ns"] = 10
    output = run(data)
    assert_reason(output, "FRAME_TIMESTAMP_MISSING", "INCOMPLETE")
    assert_reason(output, "COVERAGE_UNBOUNDED")
    assert_reason(output, "FRAME_GAP_EXCEEDED")
    assert output["frame_coverage"] == "UNBOUNDED"


@pytest.mark.parametrize("windows,code", [
    ([{"start_ns": 2, "end_ns": 1}], "READ_WINDOW_MISMATCH"),
    ([{"start_ns": 10, "end_ns": 11}, {"start_ns": 1, "end_ns": 2}], "CLOCK_REGRESSION"),
    ([{"start_ns": 2000000000, "end_ns": 2000000001}], "CLOCK_REGRESSION"),
])
def test_frame_clock_contradictions(windows, code):
    data = request()
    data["frame_windows"] = windows
    assert_reason(run(data), code, "INVALID")


def test_roster_insufficiency_is_explicit():
    data = request()
    data["roster_complete"] = False
    assert_reason(run(data), "ROSTER_INCOMPLETE", "INCOMPLETE")


@pytest.mark.parametrize("value", [float("nan"), 1.5, b"bytes", "\ud800", "nul\x00byte", {1: 2}])
def test_non_json_request_types_fail_without_callbacks(value):
    data, fake = request(), FakeProbe()
    data["source_kind"] = value
    # NaN is intentionally not equal to itself; don't use the equality helper.
    result = probe.probe_local_provenance(data, reader=fake.read, descriptor=fake.descriptor, clock=fake.clock).to_dict()
    assert result["invalid_reason_codes"] == ["INPUT_NOT_JSON"]
    assert fake.calls == []


@pytest.mark.parametrize("base", [str, int, dict, list])
def test_input_subclasses_never_run_user_methods(base):
    class Hostile(base):
        def __iter__(self):
            raise HarnessViolation("iteration")

        def __eq__(self, other):
            raise HarnessViolation("comparison")

    fake = FakeProbe()
    result = probe.probe_local_provenance(Hostile(), reader=fake.read, descriptor=fake.descriptor, clock=fake.clock).to_dict()
    assert result["invalid_reason_codes"] == ["INPUT_NOT_JSON"]
    assert fake.calls == []


@pytest.mark.parametrize("case,code", [("extra", "SCHEMA_INVALID"), ("missing", "SCHEMA_INVALID"),
    ("duplicate", "DUPLICATE_IDENTITY"), ("pid_bool", "INTEGER_INVALID"),
    ("frames", "INPUT_CAP_EXCEEDED"), ("processes", "INPUT_CAP_EXCEEDED"),
    ("nodes", "INPUT_CAP_EXCEEDED"), ("depth", "INPUT_CAP_EXCEEDED"),
    ("string", "INPUT_CAP_EXCEEDED"), ("bytes", "INPUT_CAP_EXCEEDED"),
    ("serialization", "INPUT_CAP_EXCEEDED"), ("cycle", "INPUT_NOT_JSON")])
def test_probe_closed_schema_and_caps(case, code):
    data, fake = request(), FakeProbe()
    if case == "extra":
        data[SECRET] = SECRET
    elif case == "missing":
        del data["context"]
    elif case == "duplicate":
        data["targets"].append(copy.deepcopy(data["context"]))
    elif case == "pid_bool":
        data["context"]["pid"] = True
    elif case == "frames":
        data["frame_windows"] *= 33
    elif case == "processes":
        data["targets"] *= 32
    elif case == "nodes":
        data["extra"] = [None] * probe.MAX_NODES
    elif case == "depth":
        nested = None
        for _ in range(probe.MAX_DEPTH + 1):
            nested = [nested]
        data["extra"] = nested
    elif case == "string":
        data["extra"] = "x" * (probe.MAX_STRING + 1)
    elif case == "bytes":
        data["extra"] = ["x" * probe.MAX_STRING] * 129
    elif case == "serialization":
        # UTF-8 copy is below 8 MiB; ASCII-escaped canonical JSON exceeds it.
        data["extra"] = ["é" * 32768] * 43
    else:
        data["extra"] = data
    output = probe.probe_local_provenance(data, reader=fake.read, descriptor=fake.descriptor, clock=fake.clock).to_dict()
    assert output["invalid_reason_codes"] == [code]
    assert output["reads"] == [] and fake.calls == []


def test_maximum_probe_callback_counts_are_bounded():
    data = request()
    data["targets"] = [identity(pid) for pid in range(100, 163)]
    data["frame_windows"] = [{"start_ns": 2 * i, "end_ns": 2 * i + 1} for i in range(32)]
    fake = FakeProbe(data)
    output = run(data, fake)
    assert output["outcome"] == "CONSISTENT"
    assert len(output["reads"]) == probe.MAX_READS
    assert len(fake.calls) == 5 * probe.MAX_READS + 1


@pytest.mark.parametrize("where", ["source_kind", "clock_domain", "extra", "descriptor", "reading"])
@pytest.mark.parametrize("claim", ["NATIVE_SOURCE_VERIFIED", "PRODUCTION_CHRONOLOGY_ASSESSED", "VERIFIED_BY_INDEPENDENT_PROBE", SECRET])
def test_caller_claims_never_authorize_or_echo(where, claim):
    data, fake = request(), FakeProbe()
    if where in ("source_kind", "clock_domain"):
        data[where] = claim
    elif where == "extra":
        data["provenance"] = claim
    elif where == "descriptor":
        fake.descriptor_hook = lambda path, n, desc: {**desc, "provenance": claim}
    else:
        fake.reader_hook = lambda path, n, raw: {**raw, "provenance": claim}
    output = run(data, fake)
    assert output["outcome"] == "INVALID"
    assert output["trust_level"] == "CALLER_ASSERTED_ONLY"


def reverse(value):
    if type(value) is dict:
        return {key: reverse(value[key]) for key in reversed(value)}
    if type(value) is list:
        return [reverse(item) for item in value]
    return value


def test_deterministic_replay_key_order_and_detached_report():
    data = request()
    fake = FakeProbe(data)
    result = probe.probe_local_provenance(data, reader=fake.read, descriptor=fake.descriptor, clock=fake.clock)
    again = run(reverse(data))
    assert result.serialized == b2.adapter.canonical_json(again)
    detached = result.to_dict()
    detached["reads"].clear()
    detached["target_pids"].append(999)
    assert result.to_dict()["reads"] and result.to_dict()["target_pids"] == [100, 200]
    with pytest.raises(FrozenInstanceError):
        result.serialized = "changed"


def reference_fixture(frames=2):
    capture, data, evidence = b2.fixture(frames=frames)
    payload = {"captures": [capture], "requests": [data], "evidence": [evidence]}
    reference = {"payload": payload, "sha256": digest(payload)}
    local = request()
    local["frame_windows"] = [{"start_ns": f["first_read_start_ns"], "end_ns": f["last_read_end_ns"]}
                              for f in capture["frames"]]
    return local, reference


def digest(value):
    return hashlib.sha256(b2.adapter.canonical_json(value).encode()).hexdigest()


def test_reference_copy_digest_and_replay_are_nonqualifying():
    data, ref = reference_fixture()
    before = copy.deepcopy(ref)
    output = run(data, reference=ref)
    assert output["outcome"] == "CONSISTENT"
    assert output["reference_sha256"] == ref["sha256"]
    assert ref == before
    assert output == run(reverse(data), reference=reverse(ref))


@pytest.mark.parametrize("case,code", [
    ("missing_payload", "SCHEMA_INVALID"), ("missing_sha256", "SCHEMA_INVALID"),
    ("extra", "SCHEMA_INVALID"), ("sha_tamper", "REFERENCE_DIGEST_MISMATCH"),
    ("nine_captures", "INPUT_CAP_EXCEEDED"),
])
def test_malformed_reference_envelope_rejected_before_callbacks(case, code):
    data, ref = reference_fixture()
    if case.startswith("missing_"):
        del ref[case.removeprefix("missing_")]
    elif case == "extra":
        ref[SECRET] = SECRET
    elif case == "sha_tamper":
        ref["sha256"] = "0" * 64
    else:
        for key in ("captures", "requests", "evidence"):
            ref["payload"][key] = [copy.deepcopy(ref["payload"][key][0]) for _ in range(9)]
        ref["sha256"] = digest(ref["payload"])
    fake = FakeProbe(data)
    output = run(data, fake, ref)
    assert_reason(output, code, "INVALID")
    assert output["reason_codes"] == [code]
    assert output["reads"] == [] and fake.calls == []


def test_reference_over_32_combined_windows_is_rejected_without_truncation():
    data, ref = reference_fixture(frames=17)
    first = ref["payload"]["captures"][0]
    old_request = ref["payload"]["requests"][0]
    fake_io = b2.FakeIO()
    fake_io.tick = first["last_read_end_ns"] + 1
    second = b2.adapter.NativeProcfsAdapter(fake_io, fake_io.clock).sample(old_request)
    assert second["outcome"] == b2.adapter.SUCCESS
    ref["payload"]["captures"].append(second)
    ref["payload"]["requests"].append(copy.deepcopy(old_request))
    ref["payload"]["evidence"].append(b2.probes(old_request))
    ref["sha256"] = digest(ref["payload"])
    assert sum(len(c["frames"]) for c in ref["payload"]["captures"]) == 34
    fake = FakeProbe(data)
    output = run(data, fake, ref)
    assert_reason(output, "INPUT_CAP_EXCEEDED", "INVALID")
    assert output["reads"] == [] and fake.calls == []


@pytest.mark.parametrize("claim", ["NATIVE_SOURCE_VERIFIED", "PRODUCTION_CHRONOLOGY_ASSESSED",
                                   "VERIFIED_BY_INDEPENDENT_PROBE"])
@pytest.mark.parametrize("where", ["claimed_trust", "field_status"])
def test_rehashed_reference_trust_inflation_is_rejected_and_never_echoed(claim, where):
    data, ref = reference_fixture()
    evidence = ref["payload"]["evidence"][0]
    if where == "claimed_trust":
        evidence["claimed_trust"] = claim
    else:
        evidence["environments"][0]["namespace_inode"]["status"] = claim
    ref["sha256"] = digest(ref["payload"])
    output = run(data, reference=ref)
    assert_reason(output, "REFERENCE_INVALID", "INVALID")
    assert output["trust_level"] == "CALLER_ASSERTED_ONLY"
    assert claim not in b2.adapter.canonical_json(output)


@pytest.mark.parametrize("rehash", [False, True])
def test_reference_tamper_cannot_be_laundered_by_outer_digest(rehash):
    data, ref = reference_fixture()
    ref["payload"]["captures"][0]["frames"][0]["processes"][1]["stat_after_identity"]["starttime_ticks"] = 999
    if rehash:
        ref["sha256"] = digest(ref["payload"])
    output = run(data, reference=ref)
    assert_reason(output, "REFERENCE_INVALID" if rehash else "REFERENCE_DIGEST_MISMATCH", "INVALID")


def test_reference_rehashed_structural_tamper_still_fails():
    data, ref = reference_fixture()
    capture = ref["payload"]["captures"][0]
    capture["frames"][0]["processes"][1]["stat_after_identity"]["starttime_ticks"] = 999
    b2.rehash(capture)
    ref["sha256"] = digest(ref["payload"])
    assert_reason(run(data, reference=ref), "REFERENCE_INVALID", "INVALID")


def test_reference_roster_and_frame_window_mismatches():
    data, ref = reference_fixture()
    data["targets"][1]["starttime_ticks"] += 1
    assert_reason(run(data, reference=ref), "REFERENCE_ROSTER_MISMATCH", "INCOMPLETE")
    data, ref = reference_fixture()
    data["frame_windows"][0]["start_ns"] -= 1
    assert_reason(run(data, reference=ref), "READ_WINDOW_MISMATCH", "INVALID")


def test_reference_rejected_request_none_hash_is_explicit():
    data = b2.request()
    data["config"]["max_bytes"] = 0
    fake = b2.FakeIO()
    capture = b2.adapter.NativeProcfsAdapter(fake, fake.clock).sample(data)
    assert capture["input_sha256"] is None
    payload = {"captures": [capture], "requests": [data], "evidence": [b2.probes(data)]}
    ref = {"payload": payload, "sha256": digest(payload)}
    output = run(reference=ref)
    assert_reason(output, "REQUEST_INTEGRITY_UNAVAILABLE", "INVALID")
    assert_reason(output, "CAPTURE_REQUEST_REJECTED")


@pytest.mark.parametrize("key,value", [("boot_id", b2.OTHER_BOOT), ("namespace_inode", 88),
    ("namespace_device", 88), ("mount_id", 88)])
def test_matching_reference_digest_does_not_hide_environment_mismatch(key, value):
    data, ref = reference_fixture()
    env = ref["payload"]["evidence"][0]["environments"][0]
    env[key]["value"] = value
    if key == "boot_id":
        # Keep the entire B2 registration internally consistent with this boot.
        old_request = ref["payload"]["requests"][0]
        old_capture = ref["payload"]["captures"][0]
        old_request["config"]["boot_id"] = value
        for p in [old_request["roster"]["parent"]] + old_request["roster"]["workers"]:
            p["boot_id"] = value
        old_capture["config"]["boot_id"] = value
        old_capture["roster"] = copy.deepcopy(old_request["roster"])
        for frame in old_capture["frames"]:
            for process in frame["processes"]:
                process["identity"]["boot_id"] = value
        b2.bind_request(old_capture, old_request)
    ref["sha256"] = digest(ref["payload"])
    assert_reason(run(data, reference=ref), "REFERENCE_ENVIRONMENT_MISMATCH", "INCOMPLETE")


def test_missing_reference_environment_read_is_explicitly_incomplete():
    data, ref = reference_fixture()
    ref["payload"]["evidence"][0]["environments"][0]["mount_id"] = b2.field(None, status="UNAVAILABLE")
    ref["sha256"] = digest(ref["payload"])
    assert_reason(run(data, reference=ref), "REFERENCE_INCOMPLETE", "INCOMPLETE")


def test_different_declared_clock_domains_are_never_compared():
    data, ref = reference_fixture()
    capture, old_request, evidence = (ref["payload"][key][0] for key in ("captures", "requests", "evidence"))
    old_request.update(capture_mode="NATIVE", source_kind="NATIVE_REQUEST")
    capture.update(source_kind="NATIVE_PROCFS_UNVERIFIED", origin_attestation="UNVERIFIED_NATIVE_CAPTURE",
                   clock_kind="LOCAL_MONOTONIC_NS")
    evidence["claimed_trust"] = "NATIVE_SOURCE_UNVERIFIED"
    b2.bind_request(capture, old_request)
    ref["sha256"] = digest(ref["payload"])
    data["frame_windows"] = [{"start_ns": 0, "end_ns": 1}]
    output = run(data, reference=ref)
    assert_reason(output, "CLOCK_DOMAIN_UNCOMPARABLE", "INCOMPLETE")
    assert "READ_WINDOW_MISMATCH" not in output["reason_codes"]
    assert output["trust_level"] == "INJECTED_LOCAL_PROBE"


def test_ordered_reference_captures_compare_aggregate_windows():
    data, ref = reference_fixture(frames=1)
    first = ref["payload"]["captures"][0]
    old_request = ref["payload"]["requests"][0]
    fake = b2.FakeIO()
    fake.tick = first["last_read_end_ns"] + 1
    second = b2.adapter.NativeProcfsAdapter(fake, fake.clock).sample(old_request)
    assert second["outcome"] == b2.adapter.SUCCESS
    ref["payload"]["captures"].append(second)
    ref["payload"]["requests"].append(copy.deepcopy(old_request))
    ref["payload"]["evidence"].append(b2.probes(old_request))
    ref["sha256"] = digest(ref["payload"])
    data["frame_windows"].append({"start_ns": second["first_read_start_ns"], "end_ns": second["last_read_end_ns"]})
    assert run(data, reference=ref)["outcome"] == "CONSISTENT"


def test_callback_mutation_of_original_input_is_detected():
    data, fake = request(), FakeProbe()

    def mutate(path, n, raw):
        data["limits"]["max_age_ns"] += 1
        return raw

    fake.reader_hook = mutate
    output = probe.probe_local_provenance(data, reader=fake.read, descriptor=fake.descriptor, clock=fake.clock).to_dict()
    assert_reason(output, "INPUT_CHANGED", "INVALID")


# The eight mandatory B2 carryovers use the unchanged public assessment API.
# Rehashing removes accidental digest rejection as an explanation for rejection.
@pytest.mark.parametrize("case,code", [("frame_reason", "FRAME_REASON_MISMATCH"),
    ("propagation", "REASON_PROPAGATION_MISMATCH"), ("capture_status", "CAPTURE_STATUS_MISMATCH"),
    ("reason_code", "REASON_CODE_INVALID"), ("phase_plan", "PHASE_PLAN_MISMATCH"),
    ("cardinality", "INPUT_CARDINALITY_MISMATCH"), ("trust", "TRUST_CLAIM_INVALID")])
def test_b2_mandatory_rehashed_rejections(case, code):
    capture, data, evidence = b2.fixture(fault=PermissionError(SECRET) if case == "propagation" else None)
    if case == "frame_reason":
        capture["frames"][0]["processes"][1]["stat_after_identity"]["starttime_ticks"] = 999
    elif case == "propagation":
        # Preserve nonempty process codes to avoid changing process status.
        p = capture["frames"][0]["processes"][0]
        p["reason_codes"].remove("PERMISSION_DENIED")
    elif case == "capture_status":
        capture["outcome"] = "INCOMPLETE"
    elif case == "reason_code":
        capture["frames"][0]["reason_codes"] = ["UNKNOWN_REASON"]
    elif case == "phase_plan":
        evidence["coverage"]["frame_phases"] = ["setup"]
    elif case == "trust":
        evidence["claimed_trust"] = "UNKNOWN_TIER"
    b2.rehash(capture)
    captures = [capture, copy.deepcopy(capture)] if case == "cardinality" else [capture]
    output = b2.provenance.assess_provenance(captures, [data], [evidence]).to_dict()
    assert output["qualification"] == "NONQUALIFYING"
    assert output["outcome"] == "INVALID"
    assert output["invalid_reason_codes"] == [code]
    expected_incomplete = sorted(set(capture["incomplete_reason_codes"]) | {"PHASE_COVERAGE_GAP"}) if case == "propagation" else []
    assert output["incomplete_reason_codes"] == expected_incomplete


def test_b2_cross_capture_changed_roster_is_incomplete_not_invalid():
    capture, data, evidence = b2.fixture(frames=1)
    second_data = b2.request(frames=1)
    second_data["roster"]["workers"] = [b2.identity(300)]
    second_data["frame_rosters"] = [[100, 300]]
    fake = b2.FakeIO(allowed_pids=("100", "300"))
    fake.tick = capture["last_read_end_ns"] + 1
    second = b2.adapter.NativeProcfsAdapter(fake, fake.clock).sample(second_data)
    assert second["outcome"] == b2.adapter.SUCCESS and fake.handles == {}
    b2.rehash(second)
    output = b2.provenance.assess_provenance([capture, second], [data, second_data], [evidence, b2.probes(second_data)]).to_dict()
    assert output["qualification"] == "NONQUALIFYING"
    assert output["outcome"] == "INCOMPLETE"
    assert output["invalid_reason_codes"] == []
    assert output["incomplete_reason_codes"] == ["CROSS_CAPTURE_ROSTER_CHANGED"]


@pytest.mark.parametrize("case", ["nodes", "bytes", "captures", "frames", "processes"])
def test_b2_cap_stress_is_explicit_rejection_without_truncation(case):
    capture, data, evidence = b2.fixture(frames=1)
    captures, requests, evidences = [capture], [data], [evidence]
    if case == "nodes":
        data = b2.request(frames=32)
        data["roster"]["workers"] = [b2.identity(pid) for pid in range(200, 263)]
        pids = [100] + [p["pid"] for p in data["roster"]["workers"]]
        data["frame_rosters"] = [pids[:] for _ in range(32)]
        data["config"].update(max_read_attempts=16384, max_total_bytes=4194304)
        fake = b2.FakeIO(allowed_pids=tuple(str(pid) for pid in pids))
        capture = b2.adapter.NativeProcfsAdapter(fake, fake.clock).sample(data)
        assert capture["outcome"] == b2.adapter.SUCCESS and fake.handles == {}
        assert len(capture["frames"]) == 32 and all(len(f["processes"]) == 64 for f in capture["frames"])
        captures, requests, evidences = [capture], [data], [b2.probes(data)]
    elif case == "bytes":
        evidence["alignment"] = ["x" * 65536] * 129
    elif case == "captures":
        captures, requests, evidences = [capture] * 9, [data] * 9, [evidence] * 9
    elif case == "frames":
        # Tamper AFTER adapter capture to bypass its request rejection path.
        data["frame_rosters"] *= 33
        b2.bind_request(capture, data)
    else:
        data["roster"]["workers"] = [b2.identity(pid) for pid in range(200, 264)]
        b2.bind_request(capture, data)
    original = copy.deepcopy([captures, requests, evidences])
    output = b2.provenance.assess_provenance(captures, requests, evidences).to_dict()
    assert output["outcome"] == "INVALID" and output["qualification"] == "NONQUALIFYING"
    assert output["invalid_reason_codes"] == ["INPUT_CAP_EXCEEDED"]
    assert output["incomplete_reason_codes"] == output["captures"] == []
    assert [captures, requests, evidences] == original


def test_b2_rejected_request_limitation_is_pinned_without_invented_hash():
    data = b2.request()
    data["config"]["max_bytes"] = 0
    fake = b2.FakeIO()
    capture = b2.adapter.NativeProcfsAdapter(fake, fake.clock).sample(data)
    assert capture["input_sha256"] is None and fake.handles == {}
    output = b2.provenance.assess_provenance([capture], [data], [b2.probes(data)]).to_dict()
    assert output["outcome"] == "INVALID" and output["qualification"] == "NONQUALIFYING"
    assert output["invalid_reason_codes"] == ["CAPTURE_REQUEST_REJECTED"]
    assert output["incomplete_reason_codes"] == []
    assert "REQUEST_INTEGRITY_UNAVAILABLE" in output["reason_codes"]
    assert "REQUEST_HASH_VERIFIED" not in output["reason_codes"]
    assert "CONFIGURATION_INVALID" not in output["reason_codes"]


def test_b2_rehashed_mismatched_timestamp_has_meaningful_reason():
    capture, data, evidence = b2.fixture()
    capture["frames"][0]["last_read_end_ns"] += 1
    b2.rehash(capture)
    output = b2.provenance.assess_provenance([capture], [data], [evidence]).to_dict()
    assert output["qualification"] == "NONQUALIFYING" and output["outcome"] == "INVALID"
    assert output["invalid_reason_codes"] == ["READ_WINDOW_MISMATCH"]
    assert output["incomplete_reason_codes"] == []


def test_b2_missing_end_tick_keeps_frame_unusable_and_has_no_invented_end():
    data, fake = b2.request(frames=3), b2.FakeIO()
    ticks = iter((1000000001, 1000000000))
    capture = b2.adapter.NativeProcfsAdapter(fake, lambda: next(ticks)).sample(data)
    output = b2.provenance.assess_provenance([capture], [data], [b2.probes(data)]).to_dict()
    assert output["qualification"] == "NONQUALIFYING"
    assert output["invalid_reason_codes"] == ["CLOCK_NON_MONOTONIC"]
    assert output["incomplete_reason_codes"] == sorted(set(capture["incomplete_reason_codes"]) | {"PHASE_COVERAGE_GAP"})
    assert output["captures"][0]["last_read_end_ns"] is None
    assert all(not f["usable"] for f in output["captures"][0]["frames"])
    # Current B2 resets its preceding end after a missing-end frame. B3-A
    # explicitly adds COVERAGE_UNBOUNDED; B2 itself is left byte-identical.
    assert output["captures"][0]["frame_gaps_ns"] == []


def test_b2_gap_reset_limitation_and_b3_unbounded_coverage_across_missing_frame():
    class MissingMiddle(b2.FakeIO):
        def __init__(self):
            super().__init__()
            self.directories = {}

        def open(self, name, *, directory, dir_fd=None):
            if directory and dir_fd is not None:
                n = self.directories.get(name, 0)
                self.directories[name] = n + 1
                if n == 1:
                    if name == "100":
                        self.tick += 1000
                    raise FileNotFoundError(SECRET)
            return super().open(name, directory=directory, dir_fd=dir_fd)

    old_request, fake = b2.request(frames=3), MissingMiddle()
    capture = b2.adapter.NativeProcfsAdapter(fake, fake.clock).sample(old_request)
    evidence = b2.probes(old_request)
    evidence["coverage"]["max_frame_gap_ns"] = 10
    output = b2.provenance.assess_provenance([capture], [old_request], [evidence]).to_dict()
    assert fake.handles == {}
    assert capture["frames"][1]["first_read_start_ns"] is capture["frames"][1]["last_read_end_ns"] is None
    assert capture["frames"][2]["first_read_start_ns"] - capture["frames"][0]["last_read_end_ns"] == 1001
    assert output["outcome"] == "INCOMPLETE" and output["qualification"] == "NONQUALIFYING"
    assert output["invalid_reason_codes"] == []
    assert output["incomplete_reason_codes"] == ["PRIOR_IDENTITY_UNVERIFIED", "PROCESS_VANISHED"]
    assert output["captures"][0]["frame_gaps_ns"] == []
    assert "FRAME_GAP_EXCEEDED" not in output["reason_codes"]
    payload = {"captures": [capture], "requests": [old_request], "evidence": [evidence]}
    ref = {"payload": payload, "sha256": digest(payload)}
    data = request()
    data["limits"]["max_frame_gap_ns"] = 10
    data["frame_windows"] = [{"start_ns": f["first_read_start_ns"], "end_ns": f["last_read_end_ns"]}
                             for f in capture["frames"]]
    local_fake = FakeProbe(data)
    local_fake.tick = capture["last_read_end_ns"] + 100
    local = run(data, local_fake, ref)
    assert_reason(local, "FRAME_TIMESTAMP_MISSING", "INCOMPLETE")
    assert_reason(local, "COVERAGE_UNBOUNDED")
    assert_reason(local, "FRAME_GAP_EXCEEDED")
    assert_reason(local, "REFERENCE_INCOMPLETE")
