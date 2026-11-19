"""Artificial/injected I/O only. Do not execute the native backend in this gate."""

import ast
import builtins
import copy
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import pytest

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_native_procfs_adapter as adapter
from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_real_procfs_reader as b1
from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_procfs_provider as d2a
from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_sampler as d1

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_native_procfs_adapter.py"
BOOT = "11111111-2222-3333-4444-555555555555"
SECRET = "private-command-and-host-secret"
REAL_NATIVE_IO = adapter._NativeIO  # Only used with rejected paths, before os.open.


class HarnessViolation(BaseException):
    """A test guard failure must escape the adapter's Exception handlers."""


def identity(pid=100):
    return {"pid": pid, "ppid": 1 if pid == 100 else 100, "starttime_ticks": pid // 10,
            "boot_id": BOOT, "pid_namespace_id": "pidns:77", "role": "parent" if pid == 100 else "worker"}


def request(frames=1, smaps=False, native=False):
    return {"schema": adapter.SCHEMA, "source_kind": "NATIVE_REQUEST" if native else "TEST_INJECTED",
            "capture_mode": "NATIVE" if native else "INJECTED", "run_id": "fixture-run",
            "config": {"clock_ticks_per_second": 100, "boot_id": BOOT, "pid_namespace_id": "pidns:77",
                       "max_read_skew_ns": 10000, "max_bytes": 4096, "max_total_bytes": 1048576,
                       "max_read_attempts": 1000, "max_read_iterations": 128,
                       "smaps_rollup_policy": "OPTIONAL_DIAGNOSTIC" if smaps else "NOT_SAMPLED"},
            "roster": {"parent": identity(), "workers": [identity(200)], "complete": True},
            "frame_rosters": [[100, 200] for _ in range(frames)], "cgroup": None}


def stat(pid=100, ppid=None, ticks=None, state="R", overrides=None, comm="fake (internal) ) (spaces)"):
    # Complete hand-written 52-field layout; no data is obtained from the host.
    fields = {n: "0" for n in range(4, 53)}
    fields.update({4: str((1 if pid == 100 else 100) if ppid is None else ppid),
                   5: str(pid), 6: str(pid), 8: "-1", 9: "4194304", 10: "25", 12: "1",
                   14: "10", 15: "5", 18: "-5", 19: "-10", 20: "1",
                   22: str(pid // 10 if ticks is None else ticks), 23: "1048576", 24: "5",
                   25: "18446744073709551615", 26: "4194304", 27: "4198400", 28: "140737488347136",
                   38: "17", 45: "6291456", 46: "6295552", 47: "6300000", 48: "140737488348000"})
    fields.update(overrides or {})
    comm = comm.encode() if isinstance(comm, str) else comm
    return (str(pid).encode() + b" (" + comm + b") " + state.encode() + b" " +
            " ".join(fields[n] for n in range(4, 53)).encode() + b"\n")


def status(pid=100, ppid=None, state="S", rss=5, hwm=20, memory=True, name=b"fixture-name"):
    text = ("Name:\tfixture-name\nUmask:\t0022\nState:\t%s (fixture)\nTgid:\t%d\nNgid:\t0\n"
            "Pid:\t%d\nPPid:\t%d\nTracerPid:\t0\nUid:\t1000\t1000\t1000\t1000\n"
            "Gid:\t1000\t1000\t1000\t1000\nGroups:\t1000 27\nThreads:\t1\nSigQ:\t0/30000\n"
            "Speculation_Store_Bypass:\tthread vulnerable\nx86_Thread_features:\t\n" %
            (state, pid, pid, (1 if pid == 100 else 100) if ppid is None else ppid))
    if memory:
        text += "VmRSS:\t%d kB\nVmHWM:\t%d kB\nRssAnon:\t3 kB\n" % (rss, hwm)
    name = name.encode() if isinstance(name, str) else name
    return text.encode().replace(b"fixture-name", name)


def rollup():
    return (b"00400000-7ffffffff000 ---p 00000000 00:00 0                          [rollup]\n"
            b"Rss: 9 kB\nPss: 6 kB\nPss_Anon: 3 kB\nPss_File: 3 kB\nPss_Shmem: 0 kB\n"
            b"Shared_Clean: 1 kB\nShared_Dirty: 0 kB\nPrivate_Clean: 2 kB\nPrivate_Dirty: 6 kB\n"
            b"Referenced: 9 kB\nAnonymous: 6 kB\nLazyFree: 0 kB\nAnonHugePages: 0 kB\n"
            b"ShmemPmdMapped: 0 kB\nFilePmdMapped: 0 kB\nShared_Hugetlb: 0 kB\n"
            b"Private_Hugetlb: 0 kB\nSwap: 0 kB\nSwapPss: 0 kB\nLocked: 0 kB\n")


class FakeIO:
    """Pure fd/stream model; no host filesystem calls or native glue."""

    instances = []

    def __init__(self, overrides=None, open_errors=None, ticks=None, chunk_size=None,
                 read_fault=None, close_fault=False, allowed_pids=("100", "200")):
        self.instances.append(self)
        self.violations = []
        self.allowed_pids = allowed_pids
        self.overrides = overrides or {}
        self.open_errors = open_errors or {}
        self.ticks = iter(ticks) if ticks is not None else None
        self.chunk_size, self.read_fault, self.close_fault = chunk_size, read_fault, close_fault
        self.next_fd = 10
        self.handles = {}
        self.opened, self.closed, self.calls, self.leaves = [], [], [], []
        self.counts = {}
        self.tick_count = 0

    def require(self, condition, violation):
        if not condition:
            self.violations.append(violation)
            raise RuntimeError("fake I/O contract violated")

    def assert_clean(self):
        assert not self.violations, self.violations

    def handle(self, fd):
        self.require(type(fd) is int and fd in self.handles and fd not in self.closed,
                     "unknown or closed fd")
        return self.handles[fd]

    def clock(self):
        self.calls.append(("clock",))
        value = next(self.ticks) if self.ticks is not None else self.tick_count
        self.tick_count += 1
        if isinstance(value, Exception):
            raise value
        return value

    def open(self, name, *, directory, dir_fd=None):
        self.calls.append(("open", name, directory, dir_fd))
        self.require(type(name) is str and type(directory) is bool, "invalid open arguments")
        if dir_fd is None:
            self.require(name == "/proc" and directory, "unauthorized root")
            value, key = ("root",), "/proc"
        else:
            parent = self.handle(dir_fd)
            if directory:
                self.require(parent == ("root",) and name in self.allowed_pids, "unauthorized PID")
                value, key = ("pid", int(name)), name
            else:
                self.require(parent[0] == "pid" and name in ("stat", "status", "smaps_rollup"),
                             "unauthorized leaf")
                pid = parent[1]
                key = (pid, name)
                occurrence = self.counts.get(key, 0)
                self.counts[key] = occurrence + 1
                default = stat(pid) if name == "stat" else status(pid) if name == "status" else rollup()
                data = self.overrides.get((pid, name, occurrence), self.overrides.get(key, default))
                value = ["file", data, 0]
                self.leaves.append((pid, name, occurrence))
        if key in self.open_errors:
            raise self.open_errors[key]
        fd = self.next_fd
        self.next_fd += 1
        self.handles[fd] = value
        self.opened.append(fd)
        return fd

    def read(self, fd, limit):
        self.calls.append(("read", fd, limit))
        value = self.handle(fd)
        self.require(value[0] == "file" and type(limit) is int and limit > 0, "invalid read or limit")
        if self.read_fault is not None:
            return self.read_fault(limit)
        raw, offset = value[1:]
        if isinstance(raw, Exception):
            raise raw
        count = min(limit, self.chunk_size) if self.chunk_size else limit
        chunk = raw[offset:offset + count]
        value[2] += len(chunk)
        return chunk

    def close(self, fd):
        self.calls.append(("close", fd))
        self.handle(fd)
        self.closed.append(fd)
        del self.handles[fd]
        if self.close_fault:
            raise OSError(errno.EIO, SECRET)


@pytest.fixture(autouse=True)
def forbid_native_io(monkeypatch):
    violations = []
    monkeypatch.setattr(FakeIO, "instances", [])

    def blocked(*args, **kwargs):
        violations.append("native/process/network I/O attempted")
        raise AssertionError("native/process/network I/O forbidden in D2-B2-A")

    def guard(original):
        def wrapped(*args, **kwargs):
            path = args[0] if args else kwargs.get("file", kwargs.get("path"))
            if isinstance(path, (str, bytes, os.PathLike)):
                name = os.fsdecode(path)
                if (name == "/proc" or name.startswith("/proc/") or
                        name == "/sys/fs/cgroup" or name.startswith("/sys/fs/cgroup/")):
                    blocked()
            return original(*args, **kwargs)
        return wrapped

    # Block ALL fd operations: this also catches relative openat paths.
    for name in ("open", "read", "close", "listdir", "scandir", "readlink"):
        monkeypatch.setattr(os, name, blocked)
    for obj, name in ((builtins, "open"), (io, "open")):
        monkeypatch.setattr(obj, name, guard(getattr(obj, name)))
    for obj, names in ((subprocess, ("Popen", "run", "call", "check_call", "check_output")),
                       (socket, ("socket", "create_connection")),
                       (os, ("system", "fork", "posix_spawn", "posix_spawnp"))):
        for name in names:
            if hasattr(obj, name):
                monkeypatch.setattr(obj, name, blocked)
    # Reject native binding before any backend object can be made, even if the
    # module accidentally weakens a gate. No mocked native output is generated.
    monkeypatch.setattr(adapter, "_NativeIO", blocked)
    yield violations
    assert not violations, violations
    for fake in FakeIO.instances:
        fake.assert_clean()


def codes(result):
    return set(result["invalid_reason_codes"] + result["incomplete_reason_codes"])


def assert_envelope(result):
    payload = {k: v for k, v in result.items() if k != "integrity"}
    assert result["integrity"]["sha256"] == hashlib.sha256(adapter.canonical_json(payload).encode()).hexdigest()
    assert result["source_kind"] == "TEST_INJECTED"
    assert result["origin_attestation"] == "UNVERIFIED"
    assert result["qualification"] == "NONQUALIFYING"
    assert result["production_memory_qualification"] == "INCONCLUSIVE"
    assert result["production_chronological_peak"] == "NOT_OBSERVED"
    assert result["production_workload_measured"] is False
    assert result["worker_absence_proven"] is False
    assert result["unregistered_worker_coverage"] == "NOT_ESTABLISHED"
    assert result["atomic_snapshot"] is False
    assert result["bound_claim"] == "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK"
    assert result["holder_release"] == result["owner_termination"] == "NOT_ESTABLISHED"
    assert result["simultaneous_holder_occupancy"] == "NOT_ESTABLISHED"
    assert result["independent_verification"] == "REQUIRED_NOT_PERFORMED"
    serialized = adapter.canonical_json(result)
    for forbidden in ("REAL_PROCFS", "LOCAL_COLLECTOR_RECORDED", "PROCESS_RSS_SAMPLE_COMPLETE",
                      "OBSERVATION_COMPLETE", "FAKE_FIXTURE", SECRET):
        assert forbidden not in serialized
    for frame in result["frames"]:
        if frame["status"] != adapter.SUCCESS:
            for process in frame["processes"]:
                assert process["status"] != adapter.SUCCESS
                assert process["vmrss_bytes"] is process["vmhwm_bytes"] is process["smaps_rollup"] is None


def sample(data=None, fake=None, expected=None, outcome=None):
    fake = fake if fake is not None else FakeIO()
    result = adapter.NativeProcfsAdapter(fake, fake.clock).sample(request() if data is None else data)
    fake.assert_clean()
    assert_envelope(result)
    assert fake.opened == sorted(fake.closed)
    assert not fake.handles
    if expected:
        assert expected in codes(result)
    if outcome:
        assert result["outcome"] == outcome
    return result


def test_static_import_and_native_safety():
    source = MODULE_PATH.read_text()
    tree = ast.parse(source)
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imports <= {"hashlib", "json", "re", "os", "time", "errno", "sys"}
    assert not any(isinstance(node, ast.ImportFrom) for node in ast.walk(tree))
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            assert not any(isinstance(child, ast.Call) for child in ast.walk(node))
    forbidden = {"listdir", "scandir", "walk", "glob", "readlink", "symlink", "write", "unlink",
                 "chmod", "sleep", "sysconf", "fork", "Popen", "system", "socket"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden
    native = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_NativeIO")
    methods = {n.name: n for n in native.body if isinstance(n, ast.FunctionDef)}
    os_calls = [(method.name, n) for method in methods.values() for n in ast.walk(method)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and
                isinstance(n.func.value, ast.Name) and n.func.value.id == "os"]
    assert [(name, n.func.attr) for name, n in os_calls] == [
        ("open", "open"), ("read", "read"), ("close", "close")]
    open_call = os_calls[0][1]
    expected_open = ast.parse("os.open(name, flags, dir_fd=dir_fd)").body[0].value
    assert ast.dump(open_call) == ast.dump(expected_open)
    flags = [n for n in methods["open"].body if isinstance(n, ast.Assign)]
    assert len(flags) == 1
    expected_flags = ast.parse("flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC").body[0]
    assert ast.dump(flags[0]) == ast.dump(expected_flags)
    directory_flag = ast.parse("if directory:\n    flags |= os.O_DIRECTORY").body[0]
    assert sum(ast.dump(n) == ast.dump(directory_flag) for n in methods["open"].body) == 1
    flag_uses = [n for n in ast.walk(native) if isinstance(n, ast.Attribute) and
                 n.attr.startswith("O_")]
    assert sorted(n.attr for n in flag_uses) == ["O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_RDONLY"]
    # All native os calls belong to those three methods; the native clock is
    # bound once inside sample and never invoked directly elsewhere.
    assert [n for n in ast.walk(tree) if isinstance(n, ast.Call) and
            isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and
            n.func.value.id == "os"] == [n for _, n in os_calls]
    sample_method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "sample")
    clocks = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and
              isinstance(n.value, ast.Name) and n.value.id == "time"]
    assert len(clocks) == 1 and clocks[0].attr == "monotonic_ns"
    assert clocks[0] in list(ast.walk(sample_method))
    needs = [n for n in ast.walk(methods["open"]) if isinstance(n, ast.Call) and
             isinstance(n.func, ast.Name) and n.func.id == "_need"]
    assert needs and all(n.lineno < open_call.lineno for n in needs)
    for forbidden_text in ("/sys/fs/cgroup", "memory.peak", "cmdline", "asyncio", "threading", "subprocess"):
        assert forbidden_text not in source


def test_all_emitted_reason_literals_are_in_sealed_vocabulary():
    tree = ast.parse(MODULE_PATH.read_text())
    emitted = set()

    def literals(node):
        # Only values returned as codes count; conditional predicates may
        # contain unrelated strings such as config["max_bytes"].
        if isinstance(node, ast.Constant) and type(node.value) is str:
            return {node.value}
        if isinstance(node, ast.IfExp):
            return literals(node.body) | literals(node.orelse)
        return set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else None)
            position = 1 if name == "_need" else 0 if name in ("_Violation", "reason") else None
            if position is not None and len(node.args) > position:
                emitted.update(literals(node.args[position]))
            for keyword in node.keywords:
                if keyword.arg == "code":
                    emitted.update(literals(keyword.value))
        if isinstance(node, ast.FunctionDef):
            if node.name in ("_io_error", "_exception_code"):
                for statement in ast.walk(node):
                    if isinstance(statement, ast.Return):
                        emitted.update(literals(statement.value))
            for argument, default in zip(node.args.args[-len(node.args.defaults):], node.args.defaults):
                if argument.arg == "code":
                    emitted.update(literals(default))
    assert {"OVERSIZED", "TOTAL_BYTES_CAP_EXCEEDED", "PATH_POLICY_VIOLATION",
            "READ_SKEW_EXCEEDED", "READER_EXCEPTION", "READER_CONTRACT_VIOLATION"} <= emitted
    assert "max_bytes" not in emitted
    assert emitted <= set(adapter.KNOWN_CODES)
    assert set(adapter.INVALID_CODES) <= set(adapter.KNOWN_CODES)
    assert len(adapter.KNOWN_CODES) == len(set(adapter.KNOWN_CODES))


@pytest.mark.parametrize("name,directory,dir_fd", [
    ("cmdline", False, 10), ("../1", True, 10), ("self", True, 10),
    ("/proc", True, 10), ("/proc", False, None), ("/elsewhere", True, None),
    ("stat", True, 10), ("status", True, 10), ("smaps_rollup", True, 10),
    ("0", True, 10), ("01", True, 10), ("2147483648", True, 10),
    ("9" * 100, True, 10), ("100", False, 10), ("stat", False, -1),
    ("stat", False, True), (None, False, 10), ("stat", "yes", 10),
])
def test_native_leaf_defense_rejects_before_os_open(name, directory, dir_fd, forbid_native_io):
    with pytest.raises(adapter._Violation) as caught:
        REAL_NATIVE_IO().open(name, directory=directory, dir_fd=dir_fd)
    assert caught.value.code == "PATH_POLICY_VIOLATION"
    assert forbid_native_io == []


@pytest.mark.parametrize("code", [SECRET, None, 123, []])
@pytest.mark.parametrize("stage", ["root", "pid", "leaf", "read", "close"])
def test_injected_violation_codes_are_sealed(code, stage):
    violation = adapter._Violation(code)
    fake = FakeIO(overrides={(100, "stat"): violation} if stage == "read" else None,
                  open_errors={"/proc" if stage == "root" else "100" if stage == "pid"
                               else (100, "stat"): violation} if stage in ("root", "pid", "leaf") else None)
    if stage == "close":
        original = fake.close

        def close(fd):
            original(fd)
            raise violation

        fake.close = close
    result = sample(fake=fake, expected="READER_CONTRACT_VIOLATION", outcome="INVALID")
    assert codes(result) <= set(adapter.KNOWN_CODES)
    assert SECRET not in adapter.canonical_json(result)


def test_import_and_constructor_inert(monkeypatch):
    compiled = compile(MODULE_PATH.read_text(), str(MODULE_PATH), "exec")

    def blocked(*args, **kwargs):
        raise HarnessViolation("import/constructor performed I/O or clock call")

    namespace = {"__name__": "inert_adapter"}
    with monkeypatch.context() as patch:
        for obj, name in ((builtins, "open"), (io, "open"), (time, "monotonic_ns"),
                          (time, "time"), (time, "sleep")):
            patch.setattr(obj, name, blocked)
        exec(compiled, namespace)
        namespace["NativeProcfsAdapter"]()
        namespace["NativeProcfsAdapter"](blocked, blocked)


@pytest.mark.parametrize("opt_in", [None, False, True, 1, "", "ALLOW_BOUNDED_NATIVE_PROCFS_D2B2 "])
def test_native_default_deny(opt_in, monkeypatch):
    def blocked():
        raise HarnessViolation("native clock called")
    with monkeypatch.context() as patch:
        patch.setattr(time, "monotonic_ns", blocked)
        result = adapter.NativeProcfsAdapter().sample(request(native=True), native_opt_in=opt_in)
    assert result["outcome"] == "INVALID"
    assert "NATIVE_OPT_IN_REQUIRED" in codes(result)
    assert result["open_attempts"] == 0
    assert_envelope(result)


def test_opt_in_str_subclass_rejected():
    class String(str):
        pass
    result = adapter.NativeProcfsAdapter().sample(request(native=True), native_opt_in=String(adapter.NATIVE_OPT_IN))
    assert "NATIVE_OPT_IN_REQUIRED" in codes(result)
    assert_envelope(result)


def test_no_default_readers_or_clock():
    result = adapter.NativeProcfsAdapter().sample(request())
    assert "READER_NOT_CONFIGURED" in codes(result)
    assert_envelope(result)
    assert adapter.NativeProcfsAdapter().sample()["outcome"] == "INVALID"
    fake = FakeIO()
    result = adapter.NativeProcfsAdapter(fake).sample(request())
    assert "CLOCK_NOT_CONFIGURED" in codes(result) and not fake.calls


@pytest.mark.parametrize("injection", ["filesystem", "clock", "both"])
def test_native_opt_in_with_injection_rejected(injection):
    fake = FakeIO()
    obj = adapter.NativeProcfsAdapter(fake if injection != "clock" else None,
                                     fake.clock if injection != "filesystem" else None)
    result = obj.sample(request(native=True), native_opt_in=adapter.NATIVE_OPT_IN)
    assert "NATIVE_INJECTION_CONFLICT" in codes(result)
    assert not fake.calls
    assert_envelope(result)


@pytest.mark.parametrize("stop", ["sentinel", "permission_error"])
def test_all_native_gates_reach_blocking_stub_without_native_io(monkeypatch, forbid_native_io, stop):
    attempts, clock_calls = [], []

    class NativeBranchReached(BaseException):
        pass

    class BlockingNative:
        def __init__(self):
            attempts.append("constructed")

        def open(self, name, *, directory, dir_fd=None):
            attempts.append((name, directory, dir_fd))
            if stop == "permission_error":
                raise PermissionError(errno.EACCES, SECRET)
            raise NativeBranchReached

    def blocked_clock():
        clock_calls.append("clock")
        raise HarnessViolation("native clock must not run")

    with monkeypatch.context() as patch:
        patch.setattr(adapter, "_NativeIO", BlockingNative)
        patch.setattr(adapter.sys, "platform", "linux")
        for index, name in enumerate(("O_RDONLY", "O_NOFOLLOW", "O_CLOEXEC", "O_DIRECTORY")):
            if not hasattr(os, name):
                patch.setattr(os, name, 1 << index, raising=False)
        patch.setattr(time, "monotonic_ns", blocked_clock)
        if stop == "sentinel":
            with pytest.raises(NativeBranchReached):
                adapter.NativeProcfsAdapter().sample(request(native=True), native_opt_in=adapter.NATIVE_OPT_IN)
        else:
            result = adapter.NativeProcfsAdapter().sample(request(native=True), native_opt_in=adapter.NATIVE_OPT_IN)
            assert result["source_kind"] == "NATIVE_PROCFS_UNVERIFIED"
            assert result["origin_attestation"] == "UNVERIFIED_NATIVE_CAPTURE"
            assert result["clock_kind"] == "LOCAL_MONOTONIC_NS"
            assert result["qualification"] == "NONQUALIFYING"
            assert result["outcome"] == "INCOMPLETE" and "PERMISSION_DENIED" in codes(result)
            assert result["read_attempts"] == result["total_bytes"] == 0
            serialized = adapter.canonical_json(result)
            assert "REAL_PROCFS" not in serialized and SECRET not in serialized
    assert attempts == ["constructed", ("/proc", True, None)]
    assert clock_calls == forbid_native_io == []


def test_fake_allowlist_violation_is_visible_after_incomplete_capture():
    fake = FakeIO(allowed_pids=("100",))
    result = adapter.NativeProcfsAdapter(fake, fake.clock).sample(request())
    assert result["outcome"] == "INCOMPLETE" and "READER_EXCEPTION" in codes(result)
    assert_envelope(result)
    assert fake.violations == ["unauthorized PID"]
    with pytest.raises(AssertionError, match="unauthorized PID"):
        fake.assert_clean()
    fake.violations.clear()  # Consume the deliberate negative control only.
    assert not fake.handles and fake.opened == sorted(fake.closed)


def test_sample_helper_rejects_swallowed_fake_allowlist_violation():
    fake = FakeIO(allowed_pids=("100",))
    with pytest.raises(AssertionError, match="unauthorized PID"):
        sample(fake=fake, outcome="INCOMPLETE")
    assert fake.violations == ["unauthorized PID"]
    fake.violations.clear()  # Consume the deliberate negative control only.
    assert not fake.handles and fake.opened == sorted(fake.closed)


@pytest.mark.parametrize("operation", ["root", "pid", "leaf", "parent_fd", "read_fd",
                                       "read_directory", "limit", "closed_fd", "double_close"])
def test_fake_contract_violations_are_recorded(operation):
    fake = FakeIO()
    root = fake.open("/proc", directory=True)
    pid = fake.open("100", directory=True, dir_fd=root)
    leaf = fake.open("stat", directory=False, dir_fd=pid)
    if operation in ("closed_fd", "double_close"):
        fake.close(leaf)
    actions = {
        "root": lambda: fake.open("/elsewhere", directory=True),
        "pid": lambda: fake.open("300", directory=True, dir_fd=root),
        "leaf": lambda: fake.open("cmdline", directory=False, dir_fd=pid),
        "parent_fd": lambda: fake.open("stat", directory=False, dir_fd=999),
        "read_fd": lambda: fake.read(999, 1),
        "read_directory": lambda: fake.read(pid, 1),
        "limit": lambda: fake.read(leaf, 0),
        "closed_fd": lambda: fake.read(leaf, 1),
        "double_close": lambda: fake.close(leaf),
    }
    with pytest.raises(RuntimeError, match="fake I/O contract violated"):
        actions[operation]()
    assert len(fake.violations) == 1
    with pytest.raises(AssertionError):
        fake.assert_clean()
    fake.violations.clear()
    for fd in list(fake.handles):
        fake.close(fd)


@pytest.mark.parametrize("field,value,code", [
    ("schema", "bad", "SCHEMA_VERSION_MISMATCH"),
    ("native_opt_in", adapter.NATIVE_OPT_IN, "UNKNOWN_FIELD"),
    ("path", "/tmp/../proc", "UNKNOWN_FIELD"), ("filename", "cmdline", "UNKNOWN_FIELD"),
    ("origin_attestation", "LOCAL_COLLECTOR_RECORDED", "UNKNOWN_FIELD"),
    ("qualification", "COMPLETE", "UNKNOWN_FIELD"), ("outcome", "OBSERVATION_COMPLETE", "UNKNOWN_FIELD"),
    ("source_kind", "REAL_PROCFS", "SOURCE_KIND_NOT_ACCEPTED"),
    ("source_kind", "LOCAL_COLLECTOR_RECORDED", "SOURCE_KIND_NOT_ACCEPTED"),
    ("source_kind", "FAKE_FIXTURE", "SOURCE_KIND_NOT_ACCEPTED"),
    ("cgroup", {"enabled": True}, "CGROUP_NOT_AUTHORIZED"),
    ("cgroup", {"enabled": 0}, "CGROUP_NOT_AUTHORIZED"),
    ("cgroup", {"enabled": False, "read": "fake"}, "CGROUP_NOT_AUTHORIZED"),
])
def test_validation_failures_before_native_binding(field, value, code):
    data = request(native=True)
    data[field] = value
    result = adapter.NativeProcfsAdapter().sample(data, native_opt_in=adapter.NATIVE_OPT_IN)
    assert result["outcome"] == "INVALID" and code in codes(result)
    assert result["open_attempts"] == 0
    assert_envelope(result)


@pytest.mark.parametrize("pid", [0, -1, True, "1/..", "self", "../200", 2147483648])
def test_invalid_pid_before_native_binding(pid):
    data = request(native=True)
    data["roster"]["parent"]["pid"] = pid
    result = adapter.NativeProcfsAdapter().sample(data, native_opt_in=adapter.NATIVE_OPT_IN)
    assert result["outcome"] == "INVALID" and "IDENTITY_INVALID" in codes(result)
    assert_envelope(result)


@pytest.mark.parametrize("smaps", [False, True])
def test_consistent_frame_and_path_allowlist(smaps):
    fake = FakeIO()
    result = sample(request(smaps=smaps), fake, outcome=adapter.SUCCESS)
    expected = [(100, "stat", 0), (200, "stat", 0), (100, "status", 0), (200, "status", 0)]
    if smaps:
        expected += [(100, "smaps_rollup", 0), (200, "smaps_rollup", 0)]
    assert fake.leaves == expected + [(100, "stat", 1), (200, "stat", 1)]
    frame = result["frames"][0]
    assert frame["read_window_complete"] is True
    assert frame["status"] == adapter.SUCCESS
    for window in (frame, result):
        assert window["first_read_start_ns"] == 0
        assert window["last_read_end_ns"] == window["read_skew_ns"] == (15 if smaps else 11)
    assert result["worker_coverage"] == "REGISTERED_ROSTER_OBSERVED"
    for p in frame["processes"]:
        assert p["stat_before_identity"] == p["stat_after_identity"]
        assert p["stat_before_identity"]["pid"] == p["identity"]["pid"]
        assert p["vmrss_bytes"] == 5120 and p["vmhwm_bytes"] == 20480
        assert (p["smaps_rollup"] is not None) is smaps
        for read in p["reads"]:
            assert read["status"] == "OK" and read["byte_provenance_complete"] is True
            assert read["requested_limits"] == [4097, 4097 - read["byte_length"]]


@pytest.mark.parametrize("which", ["status", "stat_after", "stat_before"])
@pytest.mark.parametrize("change,code", [("ppid", "PROCESS_REPARENTED"), ("ticks", "PID_REUSE")])
def test_lifecycle_identity_changes_incomplete(which, change, code):
    if which == "status" and change == "ticks":
        # Status has no starttime: a reuse is detected by the closing stat.
        which = "stat_after"
    leaf = "status" if which == "status" else "stat"
    occurrence = 1 if which == "stat_after" else 0
    raw = status(200, ppid=1) if leaf == "status" else stat(200, **{change: 1 if change == "ppid" else 21})
    result = sample(fake=FakeIO({(200, leaf, occurrence): raw}), expected=code, outcome="INCOMPLETE")
    assert result["frames"][0]["status"] == "INCOMPLETE"


@pytest.mark.parametrize("leaf", ["stat", "status"])
def test_contradictory_pid_invalid(leaf):
    raw = stat(300, ppid=100, ticks=20) if leaf == "stat" else status(300, ppid=100)
    sample(fake=FakeIO({(200, leaf): raw}), expected="IDENTITY_CONTRADICTION", outcome="INVALID")


def test_thread_id_rejected():
    sample(fake=FakeIO({(200, "status"): status(200).replace(b"Tgid:\t200", b"Tgid:\t201")}),
           expected="IDENTITY_CONTRADICTION", outcome="INVALID")


@pytest.mark.parametrize("state", ["Z", "X", "x"])
def test_exited_process_nonqualifying(state):
    sample(fake=FakeIO({(200, "status"): status(200, state=state, memory=False)}),
           expected="PROCESS_NOT_LIVE", outcome="INCOMPLETE")


def test_exit_mm_without_zombie_state_incomplete():
    sample(fake=FakeIO({(200, "status"): status(200, memory=False)}),
           expected="PROCESS_MEMORY_UNAVAILABLE", outcome="INCOMPLETE")


@pytest.mark.parametrize("exc,code,outcome", [
    (PermissionError(SECRET), "PERMISSION_DENIED", "INCOMPLETE"),
    (FileNotFoundError(SECRET), "PROCESS_VANISHED", "INCOMPLETE"),
    (ProcessLookupError(SECRET), "PROCESS_VANISHED", "INCOMPLETE"),
    (OSError(errno.ENOENT, SECRET), "PROCESS_VANISHED", "INCOMPLETE"),
    (OSError(errno.EIO, SECRET), "READ_FAILED", "INCOMPLETE"),
    (RuntimeError(SECRET), "READER_EXCEPTION", "INCOMPLETE"),
    (OSError(errno.ELOOP, SECRET), "PATH_POLICY_VIOLATION", "INVALID"),
    (OSError(errno.ENOTDIR, SECRET), "PATH_POLICY_VIOLATION", "INVALID"),
])
@pytest.mark.parametrize("stage", ["root", "pid", "leaf", "read"])
def test_io_errors_and_cleanup(exc, code, outcome, stage):
    fake = FakeIO(overrides={(200, "status"): exc} if stage == "read" else None,
                  open_errors={"/proc" if stage == "root" else "200" if stage == "pid"
                               else (200, "status"): exc} if stage != "read" else None)
    sample(fake=fake, expected=code, outcome=outcome)


def test_exit_between_status_and_post_identity():
    result = sample(fake=FakeIO({(200, "stat", 1): ProcessLookupError(SECRET)}),
                    expected="PROCESS_VANISHED", outcome="INCOMPLETE")
    assert result["frames"][0]["processes"][1]["stat_after_identity"] is None


@pytest.mark.parametrize("observed,complete,code", [
    ([100], True, "REGISTERED_PROCESS_MISSING"),
    ([100, 200, 300], True, "UNKNOWN_PROCESS"),
    ([100, 200], False, "ROSTER_INCOMPLETE"),
])
def test_roster_coverage_does_not_discover_or_suppress_reads(observed, complete, code):
    data, fake = request(), FakeIO()
    data["frame_rosters"][0] = observed
    data["roster"]["complete"] = complete
    sample(data, fake, expected=code, outcome="INCOMPLETE")
    assert {pid for pid, _, _ in fake.leaves} == {100, 200}


def test_worker_departure_and_unregistered_arrival_multiple_frames():
    data, fake = request(frames=2), FakeIO({(200, "stat", 2): FileNotFoundError(SECRET),
                                          (200, "stat", 3): FileNotFoundError(SECRET)})
    data["frame_rosters"][1] = [100, 300]
    result = sample(data, fake, expected="UNKNOWN_PROCESS", outcome="INCOMPLETE")
    assert result["frames"][0]["status"] == adapter.SUCCESS
    assert result["frames"][1]["status"] == "INCOMPLETE"
    assert all(pid != 300 for pid, _, _ in fake.leaves)


def test_exact_max_bytes_and_partial_chunks():
    raw = stat()
    data, fake = request(), FakeIO(chunk_size=17)
    data["config"]["max_bytes"] = max(len(raw), len(stat(200)), len(status()), len(status(200)))
    result = sample(data, fake, outcome=adapter.SUCCESS)
    read = result["frames"][0]["processes"][0]["reads"][0]
    assert read["byte_length"] == len(raw)
    assert read["sha256"] == hashlib.sha256(raw).hexdigest()
    assert read["requested_limits"][0] == data["config"]["max_bytes"] + 1
    assert read["requested_limits"][-1] == data["config"]["max_bytes"] + 1 - len(raw)
    assert read["read_calls"] > 2


def test_one_extra_byte_not_truncated():
    data, fake = request(), FakeIO()
    data["config"]["max_bytes"] = len(stat()) - 1
    result = sample(data, fake, expected="OVERSIZED", outcome="INCOMPLETE")
    read = result["frames"][0]["processes"][0]["reads"][0]
    assert read["byte_length"] == len(stat())
    assert read["sha256"] == hashlib.sha256(stat()).hexdigest()


@pytest.mark.parametrize("fault", [lambda n: b"x" * (n + 1), lambda n: "text",
                                   lambda n: bytearray(b"x"), lambda n: None])
def test_callback_contract_violation_stops_without_more_io(fault):
    fake = FakeIO(read_fault=fault)
    result = sample(request(frames=3), fake, expected="READER_CONTRACT_VIOLATION", outcome="INVALID")
    assert result["read_attempts"] == 1
    assert len(result["frames"]) == 1 and "CAPTURE_STOPPED" in codes(result)
    assert result["frames"][0]["processes"][0]["reads"][0]["sha256"] is None


def test_bytes_subclass_rejected():
    class Bytes(bytes):
        pass
    sample(fake=FakeIO(read_fault=lambda n: Bytes(b"x")),
           expected="READER_CONTRACT_VIOLATION", outcome="INVALID")


def test_remaining_total_budget_reduces_request_and_allows_only_one_sentinel():
    data, fake = request(), FakeIO()
    data["config"]["max_total_bytes"] = len(stat()) + 10
    result = sample(data, fake, expected="TOTAL_BYTES_CAP_EXCEEDED", outcome="INCOMPLETE")
    reads = [call for call in fake.calls if call[0] == "read"]
    assert [call[2] for call in reads] == [len(stat()) + 11, 11, 11]
    assert result["total_bytes"] == data["config"]["max_total_bytes"] + 1


@pytest.mark.parametrize("frames", [1, 2])
@pytest.mark.parametrize("remaining", [0, 7])
def test_stopped_post_identity_preserves_actual_frame_and_capture_windows(frames, remaining):
    data = request(frames=frames)
    data["config"]["max_total_bytes"] = sum(map(len, (stat(), stat(200), status(), status(200)))) + remaining
    data["config"]["max_read_skew_ns"] = 8
    result = sample(data, expected="TOTAL_BYTES_CAP_EXCEEDED", outcome="INCOMPLETE")
    assert "CAPTURE_STOPPED" in codes(result) and "READ_SKEW_EXCEEDED" in codes(result)
    assert len(result["frames"]) == 1
    frame = result["frames"][0]
    last_read = frame["processes"][0]["reads"][-1]
    assert last_read["label"] == "stat_after" and last_read["status"] == "FAILED"
    assert frame["processes"][1]["reads"][-1]["status"] == "NOT_READ"
    reads = [r for p in frame["processes"] for r in p["reads"]]
    assert max(r["end_ns"] for r in reads if r["end_ns"] is not None) == last_read["end_ns"] == 9
    for window in (frame, result):
        assert window["first_read_start_ns"] == min(r["start_ns"] for r in reads if r["start_ns"] is not None) == 0
        assert window["last_read_end_ns"] == 9 and window["read_skew_ns"] == 9
    assert frame["read_window_complete"] is False


@pytest.mark.parametrize("field,limit,code", [("max_read_attempts", 1, "READ_ATTEMPT_CAP_EXCEEDED"),
                                             ("max_read_iterations", 1, "READ_ITERATION_CAP_EXCEEDED")])
def test_finite_read_caps(field, limit, code):
    data = request(frames=3)
    data["config"][field] = limit
    result = sample(data, expected=code, outcome="INCOMPLETE")
    assert result["read_attempts"] == 1 and len(result["frames"]) == 1


@pytest.mark.parametrize("ticks,code,outcome", [
    ([5, 4], "CLOCK_NON_MONOTONIC", "INVALID"),
    ([1, True], "CLOCK_FAILURE", "INVALID"), ([1, -1], "CLOCK_FAILURE", "INVALID"),
    ([1, RuntimeError(SECRET)], "CLOCK_FAILURE", "INVALID"),
    (["1"], "CLOCK_FAILURE", "INVALID"),
])
def test_clock_failures_stop_and_cleanup(ticks, code, outcome):
    sample(request(frames=3), FakeIO(ticks=ticks), expected=code, outcome=outcome)


def test_clock_ties_allowed():
    result = sample(fake=FakeIO(ticks=[5] * 12), outcome=adapter.SUCCESS)
    assert result["read_skew_ns"] == 0


def test_high_skew_clears_whole_frame():
    data = request()
    data["config"]["max_read_skew_ns"] = 1
    sample(data, expected="READ_SKEW_EXCEEDED", outcome="INCOMPLETE")


def test_contract_violation_preserved_if_end_clock_also_fails():
    result = sample(fake=FakeIO(ticks=[1, 0], read_fault=lambda n: b"x" * (n + 1)),
                    expected="READER_CONTRACT_VIOLATION", outcome="INVALID")
    assert "CLOCK_NON_MONOTONIC" in codes(result)
    assert result["read_attempts"] == 1


@pytest.mark.parametrize("raw,code", [
    (stat().replace(b" R ", b" \xff "), "INVALID_UTF8"),
    (stat().replace(b" R ", b" \xc2\x85 "), "INVALID_UTF8"),
    (b"100 (cut) R 1\n", "MISSING_FIELD"),
    (stat()[:-1], "TRUNCATED"), (stat().replace(b"4194304", b"9" * 21), "RAW_TEXT_MALFORMED"),
    (stat().replace(b" R ", b" R " + b" " * 65), "RAW_TEXT_MALFORMED"),
    (stat().replace(b" R ", b" R\x00 "), "RAW_TEXT_MALFORMED"),
    (stat().replace(b" R ", b" R\x1b "), "RAW_TEXT_MALFORMED"),
    (stat().replace(b" R ", b" R\x7f "), "RAW_TEXT_MALFORMED"),
    (stat().replace(b" R ", b" R\xe2\x80\xa8 "), "INVALID_UTF8"),
    (stat().replace(b" R ", b" ? "), "RAW_TEXT_MALFORMED"),
    (stat().replace(b" R ", b" R\n "), "RAW_TEXT_MALFORMED"),
    (stat().replace(b") R ", b")R "), "RAW_TEXT_MALFORMED"),
    (stat().replace(b"100 (", b"one (", 1), "RAW_TEXT_MALFORMED"),
    (stat().replace(b"100 (", b"0100 (", 1), "RAW_TEXT_MALFORMED"),
    (stat().replace(b"100 (", b" 100 (", 1), "RAW_TEXT_MALFORMED"),
    (stat().replace(b"100 (", b"100  (", 1), "RAW_TEXT_MALFORMED"),
    (stat().replace(b"100 (", b"\xff (", 1), "RAW_TEXT_MALFORMED"),
    (stat(overrides={52: ")"}), "RAW_TEXT_MALFORMED"),
    (stat(overrides={22: "1.5"}), "RAW_TEXT_MALFORMED"),
    (stat()[:-1] + b" 0\n", "RAW_TEXT_MALFORMED"),
])
def test_stat_malformed(raw, code):
    sample(fake=FakeIO({(100, "stat", 0): raw}), expected=code,
           outcome="INCOMPLETE" if code == "TRUNCATED" else "INVALID")


@pytest.mark.parametrize("comm", [
    b"", b"inside ) ( ) R 1 2", b"line\nbreak", b"\x00\x01\x1b\x7f", b"\x85",
    "name\u2028\u2029".encode(), b"invalid\xff", b"a" * 14 + b"\xe2",
    b"9" * 25, b" " * 65, b"k" * 64,
])
def test_stat_comm_is_opaque_bytes(comm):
    result = sample(fake=FakeIO({(100, "stat"): stat(comm=comm)}), outcome=adapter.SUCCESS)
    process = result["frames"][0]["processes"][0]
    assert process["stat_before_identity"] == process["stat_after_identity"] == {
        "pid": 100, "ppid": 1, "starttime_ticks": 10, "state": "R"}


@pytest.mark.parametrize("name", [b"", b"bad\xff\x01\x1b\x7f\x85 (name)\\n", "line\u2028".encode(),
                                  b"9" * 25, b" " * 65])
def test_status_name_is_opaque_bytes(name):
    sample(fake=FakeIO({(100, "status"): status(name=name)}), outcome=adapter.SUCCESS)


@pytest.mark.parametrize("raw,code,outcome", [
    (status()[:-1], "TRUNCATED", "INCOMPLETE"),
    (b"Pid: 100\n", "MISSING_FIELD", "INVALID"),
    (status() + b"Pid: 100\n", "DUPLICATE_FIELD", "INVALID"),
    (status(rss=21, hwm=20), "COUNTER_INCONSISTENT", "INVALID"),
    (status().replace(b"5 kB", b"5 MB"), "RAW_TEXT_MALFORMED", "INVALID"),
    (status().replace(b"5 kB", b"18446744073709551615 kB"), "RAW_TEXT_MALFORMED", "INVALID"),
    (status(name=b"\xff") + b"Name: another\xff\n", "DUPLICATE_FIELD", "INVALID"),
    (status().replace(b"thread vulnerable", b"\xff"), "INVALID_UTF8", "INVALID"),
    (status().replace(b"thread vulnerable", b"\x01"), "RAW_TEXT_MALFORMED", "INVALID"),
    (status().replace(b"thread vulnerable", b"\xc2\x85"), "RAW_TEXT_MALFORMED", "INVALID"),
    (status().replace(b"thread vulnerable", b"\xe2\x80\xa8"), "RAW_TEXT_MALFORMED", "INVALID"),
    (status().replace(b"thread vulnerable", b"9" * 21), "RAW_TEXT_MALFORMED", "INVALID"),
    (status().replace(b"thread vulnerable", b" " * 65), "RAW_TEXT_MALFORMED", "INVALID"),
])
def test_status_malformed(raw, code, outcome):
    sample(fake=FakeIO({(100, "status"): raw}), expected=code, outcome=outcome)


@pytest.mark.parametrize("field,value,valid", [
    (22, adapter.U64_MAX, True), (25, adapter.U64_MAX, True),
    (18, -adapter.I64_MAX - 1, True), (19, adapter.I64_MAX, True),
    (22, adapter.U64_MAX + 1, False), (25, adapter.U64_MAX + 1, False),
    (18, -adapter.I64_MAX - 2, False), (19, adapter.I64_MAX + 1, False), (25, -1, False),
])
def test_kernel_integer_ranges(field, value, valid):
    data = request()
    if field == 22 and valid:
        data["roster"]["parent"]["starttime_ticks"] = value
    result = sample(data, FakeIO({(100, "stat"): stat(overrides={field: str(value)})}),
                    outcome=adapter.SUCCESS if valid else "INVALID")
    if not valid:
        assert "RAW_TEXT_MALFORMED" in codes(result)


@pytest.mark.parametrize("raw,code", [(b"Rss: 1 kB\n", "MISSING_FIELD"),
                                      (rollup() + b"Rss: 1 kB\n", "DUPLICATE_FIELD")])
def test_rollup_parser_failures_clear_rss(raw, code):
    sample(request(smaps=True), FakeIO({(200, "smaps_rollup"): raw}), expected=code, outcome="INVALID")


def test_optional_rollup_permission_denial_demotes_entire_frame():
    result = sample(request(smaps=True), FakeIO(open_errors={
        (200, "smaps_rollup"): PermissionError(errno.EACCES, SECRET)}),
        expected="PERMISSION_DENIED", outcome="INCOMPLETE")
    frame = result["frames"][0]
    assert frame["status"] == "INCOMPLETE"
    assert all(p["vmrss_bytes"] is p["vmhwm_bytes"] is p["smaps_rollup"] is None
               for p in frame["processes"])


def test_cgroup_disabled_and_no_reader_surface():
    data = request()
    data["cgroup"] = {"enabled": False}
    result = sample(data, outcome=adapter.SUCCESS)
    assert result["cgroup"] == "DISABLED"
    assert "read_cgroup" not in MODULE_PATH.read_text()


def test_raw_names_and_command_not_serialized():
    fake = FakeIO({(100, "stat"): stat(comm=SECRET.encode() + b"\xff\n\x01 (space) )"),
                   (100, "status"): status(name=SECRET.encode() + b"\xff\x01\\n")})
    result = sample(fake=fake, outcome=adapter.SUCCESS)
    assert SECRET not in adapter.canonical_json(result)
    assert "Name" not in adapter.canonical_json(result)


@pytest.mark.parametrize("fail", [False, True])
def test_deterministic_failure_and_success_provenance(fail):
    overrides = {(200, "status"): PermissionError(SECRET)} if fail else {}
    first = sample(fake=FakeIO(overrides))
    second = sample(fake=FakeIO(overrides))
    assert first == second
    if fail:
        read = first["frames"][0]["processes"][1]["reads"][1]
        assert read["exception_class"] == "PermissionError"
        assert read["sha256"] == hashlib.sha256(b"").hexdigest()
        assert read["start_ns"] is not None and read["end_ns"] is not None


def test_predecessors_reject_new_envelope():
    result = sample(outcome=adapter.SUCCESS)
    assert b1.RealProcfsReader().sample(result)["outcome"] == "INVALID"
    assert d2a.ProcfsProvider().sample(result)["outcome"] == "INVALID"
    assert d1.assess_injected_capture(result)["outcome"] == "INVALID_CAPTURE"


def test_request_detached_from_callbacks_and_result():
    data = request()
    original = copy.deepcopy(data)
    fake = FakeIO()
    base_read = fake.read

    def mutating_read(fd, limit):
        data["roster"]["parent"]["pid"] = 999
        return base_read(fd, limit)

    fake.read = mutating_read
    result = sample(data, fake, outcome=adapter.SUCCESS)
    assert result["roster"] == original["roster"]
    result["roster"]["parent"]["pid"] = 111
    assert data["roster"]["parent"]["pid"] == 999


@pytest.mark.parametrize("mode,source", [("NATIVE", "NATIVE_REQUEST"), ("NATIVE", "REAL_PROCFS"),
                                        ("INJECTED", "NATIVE_REQUEST"), ("INJECTED", "LOCAL_COLLECTOR_RECORDED")])
def test_injected_source_laundering_rejected_without_callbacks(mode, source):
    data, fake = request(), FakeIO()
    data.update(capture_mode=mode, source_kind=source)
    result = sample(data, fake, outcome="INVALID")
    assert not fake.calls and result["frames"] == []


def test_injected_request_with_native_opt_in_is_rejected():
    fake = FakeIO()
    result = adapter.NativeProcfsAdapter(fake, fake.clock).sample(request(), native_opt_in=adapter.NATIVE_OPT_IN)
    assert "NATIVE_INJECTION_CONFLICT" in codes(result) and not fake.calls
    assert_envelope(result)
    result = adapter.NativeProcfsAdapter().sample(request(), native_opt_in=adapter.NATIVE_OPT_IN)
    assert "SOURCE_ORIGIN_CONFLICT" in codes(result)
    assert_envelope(result)


@pytest.mark.parametrize("field,value", [("max_bytes", 0), ("max_bytes", adapter.MAX_BYTES + 1),
    ("max_total_bytes", True), ("max_total_bytes", adapter.MAX_TOTAL_BYTES + 1),
    ("max_read_attempts", adapter.MAX_READ_ATTEMPTS + 1),
    ("max_read_iterations", adapter.MAX_READ_ITERATIONS + 1), ("clock_ticks_per_second", 0),
    ("max_read_skew_ns", -1), ("boot_id", "../boot"), ("pid_namespace_id", "../../pid")])
def test_bad_bounds_and_provenance_before_native_binding(field, value):
    data = request(native=True)
    data["config"][field] = value
    result = adapter.NativeProcfsAdapter().sample(data, native_opt_in=adapter.NATIVE_OPT_IN)
    assert result["outcome"] == "INVALID" and "CONFIGURATION_INVALID" in codes(result)
    assert_envelope(result)


@pytest.mark.parametrize("case,code", [("oversized_roster", "INPUT_CAP_EXCEEDED"),
    ("empty_frames", "INPUT_CAP_EXCEEDED"), ("too_many_frames", "INPUT_CAP_EXCEEDED"),
    ("duplicate_worker", "DUPLICATE_IDENTITY"), ("duplicate_observed", "DUPLICATE_IDENTITY"),
    ("boot_mismatch", "BOOT_ID_MISMATCH"), ("namespace_mismatch", "PID_NAMESPACE_MISMATCH"),
    ("cycle", "INPUT_NOT_JSON"), ("deep", "INPUT_CAP_EXCEEDED"),
    ("giant_integer", "INPUT_CAP_EXCEEDED"), ("invalid_utf8_string", "INPUT_NOT_JSON")])
def test_registration_and_input_caps_before_io(case, code):
    data, fake = request(), FakeIO()
    if case == "oversized_roster":
        data["roster"]["workers"] *= adapter.MAX_PROCESSES
    elif case == "empty_frames":
        data["frame_rosters"] = []
    elif case == "too_many_frames":
        data["frame_rosters"] *= adapter.MAX_FRAMES + 1
    elif case == "duplicate_worker":
        data["roster"]["workers"] *= 2
    elif case == "duplicate_observed":
        data["frame_rosters"][0].append(200)
    elif case == "boot_mismatch":
        data["roster"]["workers"][0]["boot_id"] = "another-boot"
    elif case == "namespace_mismatch":
        data["roster"]["workers"][0]["pid_namespace_id"] = "another-ns"
    elif case == "cycle":
        data["cycle"] = data
    elif case == "deep":
        value = None
        for _ in range(20):
            value = [value]
        data["deep"] = value
    elif case == "giant_integer":
        data["roster"]["parent"]["starttime_ticks"] = 10 ** 100
    else:
        data["run_id"] = "\ud800"
    sample(data, fake, expected=code, outcome="INVALID")
    assert not fake.calls


def test_partial_bytes_then_error_retains_exact_digest():
    fake = FakeIO(chunk_size=11)
    base_read = fake.read
    count = 0

    def partial_then_error(fd, limit):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError(errno.EIO, SECRET)
        return base_read(fd, limit)

    fake.read = partial_then_error
    result = sample(fake=fake, expected="READ_FAILED", outcome="INCOMPLETE")
    record = result["frames"][0]["processes"][0]["reads"][0]
    assert record["byte_length"] == 11
    assert record["sha256"] == hashlib.sha256(stat()[:11]).hexdigest()
    assert record["byte_provenance_complete"] is True


@pytest.mark.parametrize("stage", ["root", "pid", "leaf"])
def test_close_failures_are_nonqualifying_and_not_retried(stage):
    fake = FakeIO()
    original = fake.close

    def close(fd):
        kind = fake.handle(fd)[0]
        original(fd)
        if kind == {"root": "root", "pid": "pid", "leaf": "file"}[stage]:
            raise OSError(errno.EIO, SECRET)

    fake.close = close
    result = sample(fake=fake, expected="READ_FAILED", outcome="INCOMPLETE")
    assert result["frames"][0]["status"] == "INCOMPLETE"
    assert len(fake.closed) == len(set(fake.closed))


def test_no_worker_roster_and_disabled_cgroup_callback_never_used():
    data, fake = request(), FakeIO()
    data["roster"]["workers"] = []
    data["frame_rosters"] = [[100]]
    data["cgroup"] = {"enabled": False}

    def forbidden_cgroup(*args, **kwargs):
        raise HarnessViolation("cgroup callback used")

    fake.read_cgroup = forbidden_cgroup
    result = sample(data, fake, outcome=adapter.SUCCESS)
    assert result["worker_absence_proven"] is False
    assert fake.leaves == [(100, "stat", 0), (100, "status", 0), (100, "stat", 1)]


def test_native_platform_gate_is_checked_without_binding(monkeypatch):
    data = request(native=True)
    # sys.platform is data, not a mocked native reader or clock. The request
    # must be rejected before native construction or native labels are selected.
    with monkeypatch.context() as patch:
        patch.setattr(adapter.sys, "platform", "unsupported")
        result = adapter.NativeProcfsAdapter().sample(data, native_opt_in=adapter.NATIVE_OPT_IN)
    assert "NATIVE_UNAVAILABLE" in codes(result)
    assert_envelope(result)
