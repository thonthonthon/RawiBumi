"""Artificial evidence only. Orchestration owns execution of this suite."""

import ast
import builtins
import copy
from dataclasses import FrozenInstanceError
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

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_native_procfs_adapter as adapter
from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_native_provenance as provenance

BOOT = "11111111-2222-3333-4444-555555555555"
OTHER_BOOT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SECRET = "/private/host/secret command --credential=DO_NOT_ECHO"
MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_native_provenance.py"


class HarnessViolation(BaseException):
    pass


@pytest.fixture(autouse=True)
def forbid_native_io(monkeypatch):
    violations = []

    def blocked(*args, **kwargs):
        violations.append("unauthorized I/O or clock")
        raise HarnessViolation("unauthorized I/O or clock")

    def guard(original):
        def wrapped(*args, **kwargs):
            path = args[0] if args else kwargs.get("file", kwargs.get("path"))
            if isinstance(path, (str, bytes, os.PathLike)):
                name = os.fsdecode(path)
                if name in ("/proc", "/sys") or name.startswith(("/proc/", "/sys/")):
                    blocked()
            return original(*args, **kwargs)
        return wrapped

    for name in ("open", "read", "close", "listdir", "scandir", "readlink", "sysconf", "system",
                 "fork", "posix_spawn", "posix_spawnp", "setns", "unshare"):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, blocked)
    for obj, name in ((builtins, "open"), (io, "open")):
        monkeypatch.setattr(obj, name, guard(getattr(obj, name)))
    for obj, names in ((subprocess, ("Popen", "run", "call", "check_call", "check_output")),
                       (socket, ("socket", "create_connection")),
                       (time, ("monotonic_ns", "monotonic", "clock_gettime", "clock_gettime_ns"))):
        for name in names:
            if hasattr(obj, name):
                monkeypatch.setattr(obj, name, blocked)
    monkeypatch.setattr(adapter, "_NativeIO", blocked)
    yield violations
    assert violations == []


def identity(pid):
    return {"pid": pid, "ppid": 1 if pid == 100 else 100, "starttime_ticks": pid // 10,
            "boot_id": BOOT, "pid_namespace_id": "pidns:77", "role": "parent" if pid == 100 else "worker"}


def request(frames=2, smaps=False):
    return {"schema": adapter.SCHEMA, "source_kind": "TEST_INJECTED", "capture_mode": "INJECTED",
            "run_id": "synthetic", "config": {"clock_ticks_per_second": 100, "boot_id": BOOT,
            "pid_namespace_id": "pidns:77", "max_read_skew_ns": 10000, "max_bytes": 4096,
            "max_total_bytes": 1048576, "max_read_attempts": 1000, "max_read_iterations": 128,
            "smaps_rollup_policy": "OPTIONAL_DIAGNOSTIC" if smaps else "NOT_SAMPLED"},
            "roster": {"parent": identity(100), "workers": [identity(200)], "complete": True},
            "frame_rosters": [[100, 200] for _ in range(frames)], "cgroup": None}


def stat(pid, ppid=None, ticks=None):
    fields = {i: "0" for i in range(4, 53)}
    fields.update({4: str((1 if pid == 100 else 100) if ppid is None else ppid),
                   22: str(pid // 10 if ticks is None else ticks)})
    return ("%d (opaque artificial name) R " % pid + " ".join(fields[i] for i in range(4, 53)) + "\n").encode()


def status(pid):
    return ("Name:\tartificial\nPid:\t%d\nTgid:\t%d\nPPid:\t%d\nState:\tR (running)\nVmRSS:\t5 kB\nVmHWM:\t20 kB\n" %
            (pid, pid, 1 if pid == 100 else 100)).encode()


class FakeIO:
    """In-memory fd facade, with a fail-loud allowlist independent of adapter."""

    def __init__(self, fault=None, overrides=None, allowed_pids=("100", "200")):
        self.handles = {}
        self.next_fd = 10
        self.tick = 1000000000
        self.fault = fault
        self.overrides = overrides or {}
        self.allowed_pids = allowed_pids
        self.occurrences = {}

    def open(self, name, *, directory, dir_fd=None):
        if dir_fd is None:
            if name != "/proc" or not directory:
                raise HarnessViolation("unauthorized artificial root")
            value = ("root",)
        elif directory:
            if self.handles[dir_fd] != ("root",) or name not in self.allowed_pids:
                raise HarnessViolation("unauthorized artificial PID")
            value = ("pid", int(name))
        else:
            parent = self.handles[dir_fd]
            if parent[0] != "pid" or name not in ("stat", "status", "smaps_rollup"):
                raise HarnessViolation("unauthorized artificial leaf")
            pid = parent[1]
            occurrence = self.occurrences.get((pid, name), 0)
            self.occurrences[(pid, name)] = occurrence + 1
            raw = stat(pid) if name == "stat" else status(pid) if name == "status" else b"Rss: 5 kB\nSwap: 0 kB\n"
            raw = self.overrides.get((pid, name, occurrence), raw)
            value = ["leaf", raw, 0]
        self.next_fd += 1
        self.handles[self.next_fd] = value
        return self.next_fd

    def read(self, fd, limit):
        if type(limit) is not int or limit <= 0 or self.handles[fd][0] != "leaf":
            raise HarnessViolation("unauthorized artificial read")
        if self.fault is not None:
            raise self.fault
        value = self.handles[fd]
        result = value[1][value[2]:value[2] + limit]
        value[2] += len(result)
        return result

    def close(self, fd):
        if fd not in self.handles:
            raise HarnessViolation("unauthorized artificial close")
        del self.handles[fd]

    def clock(self):
        self.tick += 1
        return self.tick


def field(value, source="INJECTED", status="CALLER_ASSERTED"):
    return {"value": value, "source": source, "status": status}


def probes(data):
    env = {"boot_id": field(data["config"]["boot_id"]), "namespace_inode": field(77),
           "namespace_device": field(4), "namespace_label": field("pidns:77"), "mount_id": field(9),
           "mount_type": field("proc"), "clk_tck": field(100), "monotonic_start_ns": field(0),
           "monotonic_end_ns": field(2000000000)}
    return {"environments": [env], "processes": [{k: field(p[k]) for k in ("pid", "ppid", "starttime_ticks")}
            for p in [data["roster"]["parent"]] + data["roster"]["workers"]], "alignment": None,
            "coverage": {"frame_phases": ["setup"] * len(data["frame_rosters"]), "required_phases": ["setup"],
                         "max_frame_gap_ns": 10000}, "claimed_trust": "INJECTED_STRUCTURALLY_CONSISTENT",
            "discovery": field("ROSTER_ONLY"), "cgroup_diagnostic": None}


def fixture(frames=2, smaps=False, fault=None, overrides=None):
    data = request(frames, smaps)
    fake = FakeIO(fault, overrides)
    capture = adapter.NativeProcfsAdapter(fake, fake.clock).sample(data)
    assert fake.handles == {}
    assert capture["input_sha256"] is not None
    return capture, data, probes(data)


def rehash(capture):
    capture["integrity"]["sha256"] = hashlib.sha256(adapter.canonical_json(
        {k: v for k, v in capture.items() if k != "integrity"}).encode()).hexdigest()


def bind_request(capture, data):
    capture["input_sha256"] = hashlib.sha256(adapter.canonical_json(data).encode()).hexdigest()
    rehash(capture)


def assess(capture, data, evidence):
    original = copy.deepcopy([capture, data, evidence])
    result = provenance.assess_provenance([capture], [data], [evidence])
    assert [capture, data, evidence] == original
    output = result.to_dict()
    assert adapter.canonical_json(output) == result.serialized
    assert output["reason_codes"] == sorted(set(output["reason_codes"]))
    assert output["qualification"] == "NONQUALIFYING"
    assert output["production_memory_qualification"] == "INCONCLUSIVE"
    assert output["production_chronological_peak"] == "NOT_OBSERVED"
    assert output["holder_release"] == "NOT_ESTABLISHED"
    assert output["worker_absence_proven"] is False
    assert output["unregistered_worker_coverage"] == "NOT_ESTABLISHED"
    assert output["atomic_snapshot"] is False
    for forbidden in ("NATIVE_SOURCE_VERIFIED", "PRODUCTION_CHRONOLOGY_ASSESSED", "REAL_PROCFS", SECRET):
        assert forbidden not in result.serialized
    return output


def expect(items, code, outcome="INVALID", rehashed=False):
    capture, data, evidence = items
    if rehashed:
        rehash(capture)
    output = assess(capture, data, evidence)
    assert code in output["reason_codes"]
    assert output["outcome"] == outcome
    return output


@pytest.mark.parametrize("smaps", [False, True])
def test_positive_parent_child_is_only_structural(smaps):
    items = fixture(smaps=smaps)
    assert items[0]["outcome"] == adapter.SUCCESS
    output = assess(*items)
    assert output["outcome"] == "UNVERIFIED"
    assert output["invalid_reason_codes"] == output["incomplete_reason_codes"] == []
    assert output["trust_level"] == "INJECTED_STRUCTURALLY_CONSISTENT"
    assert {"CAPTURE_HASH_VERIFIED", "REQUEST_HASH_VERIFIED", "PROBE_EVIDENCE_UNVERIFIED"} <= set(output["reason_codes"])
    window = output["captures"][0]
    assert window["first_read_start_ns"] == items[0]["first_read_start_ns"]
    assert window["last_read_end_ns"] == items[0]["last_read_end_ns"]
    assert window["frame_gaps_ns"] == [1]
    assert window["uncovered_phases"] == []


def test_import_inert_under_native_guards():
    importlib.reload(provenance)


def test_static_no_native_capability():
    tree = ast.parse(MODULE_PATH.read_text())
    allowed = {"dataclasses", "hashlib", "json", "re",
               "scripts.benchmarks.rb_post3d_08p2e2_r2f_f2b4_native_procfs_adapter"}
    forbidden = {"open", "read", "sample", "_NativeIO", "NativeProcfsAdapter", "monotonic_ns", "sysconf",
                 "readlink", "Popen", "system", "fork", "socket", "ctypes", "os", "time"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name in allowed for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module in allowed
            if node.module.endswith("native_procfs_adapter"):
                assert {a.name for a in node.names} <= {"SCHEMA", "RESULT_SCHEMA", "canonical_json"}
        if isinstance(node, ast.Name):
            assert node.id not in forbidden
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            assert not any(isinstance(child, ast.Call) for child in ast.walk(node))


@pytest.mark.parametrize("attempt", [
    lambda: builtins.open("/proc/self/stat"), lambda: io.open("/proc/100/status"),
    lambda: os.open("stat", 0), lambda: os.read(0, 1), lambda: os.readlink("/proc/self/ns/pid"),
    lambda: os.sysconf("SC_CLK_TCK"), lambda: subprocess.Popen(["unused"]),
    lambda: socket.socket(), lambda: adapter._NativeIO(), lambda: time.monotonic_ns(),
])
def test_negative_controls_native_guard(attempt, forbid_native_io):
    with pytest.raises(HarnessViolation):
        attempt()
    assert len(forbid_native_io) == 1
    forbid_native_io.clear()


@pytest.mark.parametrize("attempt", [
    lambda fake: fake.open("/proc/self", directory=True),
    lambda fake: fake.open("999", directory=True, dir_fd=11),
    lambda fake: fake.open("cmdline", directory=False, dir_fd=12),
    lambda fake: fake.read(12, 0), lambda fake: fake.close(999),
])
def test_negative_controls_fake_allowlist(attempt):
    fake = FakeIO()
    assert fake.open("/proc", directory=True) == 11
    assert fake.open("100", directory=True, dir_fd=11) == 12
    with pytest.raises(HarnessViolation):
        attempt(fake)


def test_fake_violation_escapes_adapter_exception_handler():
    fake = FakeIO(allowed_pids=("100",))
    with pytest.raises(HarnessViolation, match="artificial PID"):
        adapter.NativeProcfsAdapter(fake, fake.clock).sample(request())


@pytest.mark.parametrize("partial", [False, True])
def test_native_label_is_never_authentication(partial):
    capture, data, evidence = fixture()
    capture["source_kind"] = "NATIVE_PROCFS_UNVERIFIED"
    if partial:
        expect((capture, data, evidence), "SOURCE_LABEL_CONFLICT", rehashed=True)
        return
    capture.update(origin_attestation="UNVERIFIED_NATIVE_CAPTURE", clock_kind="LOCAL_MONOTONIC_NS")
    data.update(capture_mode="NATIVE", source_kind="NATIVE_REQUEST")
    evidence["claimed_trust"] = "NATIVE_SOURCE_UNVERIFIED"
    bind_request(capture, data)
    output = assess(capture, data, evidence)
    assert output["outcome"] == "UNVERIFIED"
    assert output["trust_level"] == "NATIVE_SOURCE_UNVERIFIED"


@pytest.mark.parametrize("tier", ["NATIVE_SOURCE_UNVERIFIED", "NATIVE_SOURCE_VERIFIED", "PRODUCTION_CHRONOLOGY_ASSESSED"])
def test_trust_overclaim_rejected(tier):
    items = fixture()
    items[2]["claimed_trust"] = tier
    expect(items, "TRUST_OVERCLAIM")


@pytest.mark.parametrize("key,value,code", [
    ("boot_id", OTHER_BOOT, "BOOT_ID_MISMATCH"), ("namespace_label", "pidns:88", "PID_NAMESPACE_MISMATCH"),
    ("clk_tck", 250, "CLK_TCK_MISMATCH"), ("clk_tck", True, "INTEGER_INVALID"),
    ("mount_type", "ext4", "PROCFS_TYPE_MISMATCH"), ("mount_id", 0, "INTEGER_INVALID"),
    ("namespace_inode", 0, "INTEGER_INVALID"), ("namespace_device", -1, "INTEGER_INVALID"),
    ("monotonic_start_ns", 3000000000, "PROBE_CLOCK_REGRESSION"),
    ("monotonic_end_ns", 5, "PROBE_WINDOW_CONFLICT"),
])
def test_environment_contradictions(key, value, code):
    items = fixture()
    items[2]["environments"][0][key]["value"] = value
    expect(items, code)


@pytest.mark.parametrize("uuid", [OTHER_BOOT.upper(), "{" + BOOT + "}", "1111", "../boot", SECRET])
@pytest.mark.parametrize("where", ["probe", "request", "capture"])
def test_noncanonical_boot_ids_never_normalized(uuid, where):
    items = fixture()
    capture, data, evidence = items
    if where == "probe":
        evidence["environments"][0]["boot_id"]["value"] = uuid
        code = "BOOT_ID_NONCANONICAL"
    elif where == "request":
        data["config"]["boot_id"] = uuid
        code = "BOOT_ID_NONCANONICAL"
    else:
        capture["roster"]["parent"]["boot_id"] = uuid
        code = "REQUEST_RESULT_MISMATCH"
    expect(items, code)


@pytest.mark.parametrize("key", ["boot_id", "namespace_inode", "namespace_device", "namespace_label", "mount_id", "clk_tck"])
def test_conflicting_duplicate_environment_probes(key):
    items = fixture()
    other = copy.deepcopy(items[2]["environments"][0])
    other[key]["value"] = OTHER_BOOT if key == "boot_id" else "pidns:88" if key == "namespace_label" else 999
    items[2]["environments"].append(other)
    expect(items, "ENVIRONMENT_PROBE_CONFLICT")


@pytest.mark.parametrize("source", ["CALLER", "INJECTED", "EXTERNAL_PROBE"])
@pytest.mark.parametrize("key", ["boot_id", "mount_type", "clk_tck"])
def test_fake_verified_probe_status_is_rejected(source, key):
    items = fixture()
    items[2]["environments"][0][key].update(source=source, status="VERIFIED_BY_INDEPENDENT_PROBE")
    expect(items, "PROBE_VERIFICATION_OVERCLAIM")


@pytest.mark.parametrize("key,code", [("mount_id", "MOUNT_ID_UNAVAILABLE"), ("mount_type", "MOUNT_TYPE_UNVERIFIED"),
                                     ("boot_id", "PROBE_FIELD_UNAVAILABLE")])
def test_unavailable_probe_is_unverified(key, code):
    baseline = assess(*fixture())
    items = fixture()
    items[2]["environments"][0][key] = field(None, status="UNAVAILABLE")
    output = expect(items, code, "UNVERIFIED")
    added = {"PROBE_FIELD_UNAVAILABLE"}
    if key == "mount_id":
        added.add("MOUNT_ID_UNAVAILABLE")
    assert set(output["reason_codes"]) == set(baseline["reason_codes"]) | added
    assert output["invalid_reason_codes"] == output["incomplete_reason_codes"] == []


def test_inconsistent_probe_is_invalid():
    items = fixture()
    items[2]["environments"][0]["clk_tck"]["status"] = "INCONSISTENT"
    expect(items, "PROBE_INCONSISTENT")


@pytest.mark.parametrize("mono,boot,code", [(100, 99, "BOOT_ALIGNMENT_CONFLICT"),
                                         (0, 0, "STARTTIME_ALIGNMENT_CONFLICT")])
def test_boot_alignment_conflicts(mono, boot, code):
    data = request(frames=1)
    overrides = {}
    if code == "STARTTIME_ALIGNMENT_CONFLICT":
        data["roster"]["workers"][0]["starttime_ticks"] = 10000
        overrides = {(200, "stat", n): stat(200, ticks=10000) for n in (0, 1)}
    fake = FakeIO(overrides=overrides)
    capture = adapter.NativeProcfsAdapter(fake, fake.clock).sample(data)
    assert capture["outcome"] == adapter.SUCCESS
    evidence = probes(data)
    evidence["alignment"] = {"monotonic_ns": field(mono), "boottime_ns": field(boot)}
    output = expect((capture, data, evidence), code)
    assert output["invalid_reason_codes"] == [code]
    assert output["incomplete_reason_codes"] == []
    assert {"CAPTURE_HASH_VERIFIED", "REQUEST_HASH_VERIFIED"} <= set(output["reason_codes"])


def test_synthetic_alignment_is_never_calibration():
    items = fixture()
    items[2]["alignment"] = {"monotonic_ns": field(1000000000), "boottime_ns": field(2000000000)}
    output = expect(items, "BOOT_ALIGNMENT_UNVERIFIED", "UNVERIFIED")
    assert output["starttime_alignment"] == "NOT_CALIBRATED"


@pytest.mark.parametrize("key", ["first_read_start_ns", "last_read_end_ns", "read_skew_ns"])
@pytest.mark.parametrize("level", ["capture", "frame"])
def test_rehashed_window_tamper(key, level):
    items = fixture()
    target = items[0] if level == "capture" else items[0]["frames"][0]
    target[key] += 10
    expect(items, "READ_WINDOW_MISMATCH", rehashed=True)


@pytest.mark.parametrize("which", ["end_before_start", "barrier_order", "second_frame"])
def test_read_clock_regressions(which):
    items = fixture()
    f = items[0]["frames"][1 if which == "second_frame" else 0]
    r = f["processes"][0]["reads"][1 if which == "barrier_order" else 0]
    r["end_ns" if which == "end_before_start" else "start_ns"] = 0
    expect(items, "CLOCK_REGRESSION", rehashed=True)


def test_read_skew_violation_stays_incomplete():
    data = request()
    data["config"]["max_read_skew_ns"] = 1
    fake = FakeIO()
    capture = adapter.NativeProcfsAdapter(fake, fake.clock).sample(data)
    expect((capture, data, probes(data)), "READ_SKEW_EXCEEDED", "INCOMPLETE")


def test_uncovered_phases():
    items = fixture()
    items[2]["coverage"].update(frame_phases=["setup", "producer"], required_phases=list(provenance.PHASES))
    output = expect(items, "PHASE_COVERAGE_GAP", "INCOMPLETE")
    assert output["captures"][0]["uncovered_phases"] == ["attribution", "persistence", "teardown", "verification"]
    assert output["invalid_reason_codes"] == []
    assert output["incomplete_reason_codes"] == ["PHASE_COVERAGE_GAP"]


def test_measured_frame_gap_limit():
    data = request()
    fake = FakeIO()
    base = fake.clock
    count = 0

    def clock():
        nonlocal count
        count += 1
        if count == 13:
            fake.tick += 1000
        return base()

    capture = adapter.NativeProcfsAdapter(fake, clock).sample(data)
    evidence = probes(data)
    evidence["coverage"]["max_frame_gap_ns"] = 10
    output = expect((capture, data, evidence), "FRAME_GAP_EXCEEDED", "INCOMPLETE")
    # Gap is actual observed ns between end and next start, not a sample count.
    assert output["captures"][0]["frame_gaps_ns"] == [1001]
    assert output["invalid_reason_codes"] == []
    assert output["incomplete_reason_codes"] == ["FRAME_GAP_EXCEEDED"]


@pytest.mark.parametrize("change,code", [("ticks", "PID_REUSE"), ("parent", "PROCESS_REPARENTED")])
def test_observed_identity_races(change, code):
    raw = stat(200, ticks=999) if change == "ticks" else stat(200, ppid=1)
    items = fixture(overrides={(200, "stat", 1): raw})
    output = expect(items, code, "INCOMPLETE")
    assert output["invalid_reason_codes"] == []
    assert output["incomplete_reason_codes"] == [code]


def test_self_parent_is_contradiction():
    items = fixture(overrides={(200, "stat", 1): stat(200, ppid=200)})
    expect(items, "PARENT_RELATION_CONTRADICTION")


@pytest.mark.parametrize("observed,code", [([100], "REGISTERED_PROCESS_MISSING"),
                                         ([100, 200, 300], "UNKNOWN_PROCESS")])
def test_missing_extra_worker(observed, code):
    data = request()
    data["frame_rosters"][0] = observed
    fake = FakeIO()
    capture = adapter.NativeProcfsAdapter(fake, fake.clock).sample(data)
    expect((capture, data, probes(data)), code, "INCOMPLETE")


@pytest.mark.parametrize("case,code", [("missing", "PROBE_IDENTITY_MISSING"), ("extra", "UNKNOWN_WORKER"),
                                     ("ticks", "PID_REUSE"), ("parent", "PROCESS_REPARENTED")])
def test_independent_process_claims(case, code):
    items = fixture()
    p = items[2]["processes"]
    if case == "missing":
        p.pop()
    elif case == "extra":
        p.append({"pid": field(300), "ppid": field(100), "starttime_ticks": field(30)})
    else:
        p[1]["starttime_ticks" if case == "ticks" else "ppid"]["value"] = 999
    output = expect(items, code, "INCOMPLETE")
    assert output["invalid_reason_codes"] == []
    assert output["incomplete_reason_codes"] == [code]
    if case == "extra":
        assert "PROBE_IDENTITY_MISSING" not in output["reason_codes"]


@pytest.mark.parametrize("fault,code", [(PermissionError(SECRET), "PERMISSION_DENIED"),
                                      (FileNotFoundError(SECRET), "PROCESS_VANISHED"),
                                      (OSError(SECRET), "READ_FAILED")])
@pytest.mark.parametrize("cgroup", [False, True])
def test_failed_frames_optional_diagnostic_never_upgrades(fault, code, cgroup):
    items = fixture(fault=fault)
    if cgroup:
        items[2]["cgroup_diagnostic"] = field(123456)
    output = expect(items, code, "INCOMPLETE")
    assert not any(f["usable"] for f in output["captures"][0]["frames"])


@pytest.mark.parametrize("case,code", [
    ("oversized", "OVERSIZED"), ("root_open", "ROOT_UNAVAILABLE"),
    ("leaf_close", "READ_FAILED"), ("pid_close", "READ_FAILED"), ("root_close", "READ_FAILED"),
    ("smaps", "PERMISSION_DENIED"), ("total_bytes", "TOTAL_BYTES_CAP_EXCEEDED"),
])
@pytest.mark.parametrize("cgroup", [False, True])
def test_adapter_incomplete_paths_have_no_structural_invalids(case, code, cgroup):
    data = request(frames=3, smaps=case == "smaps")
    fake = FakeIO()
    if case == "oversized":
        data["config"]["max_bytes"] = len(stat(100)) - 1
    elif case == "total_bytes":
        data["config"]["max_total_bytes"] = len(stat(100)) + 10
    elif case in ("root_open", "smaps"):
        original_open = fake.open

        def failing_open(name, *, directory, dir_fd=None):
            if (case == "root_open" and dir_fd is None) or (case == "smaps" and name == "smaps_rollup"):
                raise PermissionError(SECRET)
            return original_open(name, directory=directory, dir_fd=dir_fd)

        fake.open = failing_open
    else:
        original_close = fake.close

        def failing_close(fd):
            kind = fake.handles[fd][0]
            original_close(fd)
            if kind == case.removesuffix("_close"):
                raise OSError(SECRET)

        fake.close = failing_close
    capture = adapter.NativeProcfsAdapter(fake, fake.clock).sample(data)
    assert fake.handles == {}
    assert capture["outcome"] == "INCOMPLETE"
    assert capture["invalid_reason_codes"] == []
    assert code in capture["incomplete_reason_codes"]
    if case == "oversized":
        record = capture["frames"][0]["processes"][0]["reads"][0]
        assert record["byte_length"] == data["config"]["max_bytes"] + 1
    elif case == "total_bytes":
        assert capture["total_bytes"] == data["config"]["max_total_bytes"] + 1
    elif case == "root_open":
        assert capture["first_read_start_ns"] is capture["last_read_end_ns"] is None
    elif case == "root_close":
        assert all(p["reason_codes"] == [] for p in capture["frames"][-1]["processes"])
    evidence = probes(data)
    evidence["cgroup_diagnostic"] = field(123456) if cgroup else None
    output = expect((capture, data, evidence), code, "INCOMPLETE")
    expected_codes = set(capture["incomplete_reason_codes"])
    if not any(f["status"] == adapter.SUCCESS for f in capture["frames"]):
        expected_codes.add("PHASE_COVERAGE_GAP")
    assert output["invalid_reason_codes"] == []
    assert output["incomplete_reason_codes"] == sorted(expected_codes)
    for source, summary in zip(capture["frames"], output["captures"][0]["frames"]):
        assert summary["usable"] == (source["status"] == adapter.SUCCESS)
        if source["status"] != adapter.SUCCESS:
            assert all(p["vmrss_bytes"] is p["vmhwm_bytes"] is p["smaps_rollup"] is None
                       for p in source["processes"])


def test_adapter_rejected_end_tick_keeps_only_original_invalid_code():
    data, fake = request(frames=3), FakeIO()
    ticks = iter((1000000001, 1000000000))
    capture = adapter.NativeProcfsAdapter(fake, lambda: next(ticks)).sample(data)
    assert fake.handles == {}
    assert capture["invalid_reason_codes"] == ["CLOCK_NON_MONOTONIC"]
    record = capture["frames"][0]["processes"][0]["reads"][0]
    assert record["start_ns"] == 1000000001 and record["end_ns"] is None
    output = expect((capture, data, probes(data)), "CLOCK_NON_MONOTONIC")
    assert output["invalid_reason_codes"] == capture["invalid_reason_codes"]
    assert output["incomplete_reason_codes"] == sorted(set(capture["incomplete_reason_codes"]) | {"PHASE_COVERAGE_GAP"})
    assert output["captures"][0]["last_read_end_ns"] is None


def test_interrupted_frame_clears_rss_and_leaves_phase_uncovered():
    data = request(frames=3)
    data["config"]["max_read_attempts"] = 1
    fake = FakeIO()
    capture = adapter.NativeProcfsAdapter(fake, fake.clock).sample(data)
    evidence = probes(data)
    evidence["cgroup_diagnostic"] = field(100)
    output = expect((capture, data, evidence), "CAPTURE_STOPPED", "INCOMPLETE")
    assert len(output["captures"][0]["frames"]) == 1
    assert output["captures"][0]["uncovered_phases"] == ["setup"]


@pytest.mark.parametrize("diagnostic", [None, 1, 1000000])
@pytest.mark.parametrize("discovery", ["UNKNOWN", "ROSTER_ONLY", "INDEPENDENT_INJECTED"])
def test_caller_roster_or_discovery_never_proves_absence(discovery, diagnostic):
    items = fixture()
    items[2]["discovery"] = field(discovery)
    items[2]["cgroup_diagnostic"] = None if diagnostic is None else field(diagnostic)
    output = assess(*items)
    assert output["outcome"] == "UNVERIFIED"
    assert "DISCOVERY_UNVERIFIED" in output["reason_codes"]


def test_unhashed_capture_mutation_and_request_mutation():
    items = fixture()
    items[0]["frames"][0]["processes"][0]["vmrss_bytes"] += 1
    expect(items, "CAPTURE_HASH_MISMATCH")
    items = fixture()
    items[1]["run_id"] = "different"
    expect(items, "REQUEST_HASH_MISMATCH")


@pytest.mark.parametrize("extra", ["appended", "duplicated"])
@pytest.mark.parametrize("rehashed", [False, True])
def test_extra_usable_recorded_frame_returns_stable_invalid(extra, rehashed):
    capture, data, evidence = fixture(frames=1)
    frame = fixture(frames=2)[0]["frames"][1] if extra == "appended" else copy.deepcopy(capture["frames"][0])
    assert frame["status"] == adapter.SUCCESS and frame["read_window_complete"]
    capture["frames"].append(frame)
    if rehashed:
        rehash(capture)
    output = assess(capture, data, evidence)
    expected = {"REQUEST_RESULT_MISMATCH"}
    if not rehashed:
        expected.add("CAPTURE_HASH_MISMATCH")
    assert output["outcome"] == "INVALID"
    assert output["invalid_reason_codes"] == sorted(expected)
    assert output["incomplete_reason_codes"] == []
    assert output["captures"] == []
    assert ("CAPTURE_HASH_VERIFIED" in output["reason_codes"]) is rehashed
    assert output == assess(capture, data, evidence)


@pytest.mark.parametrize("kind,code", [("frame_status", "FRAME_STATUS_MISMATCH"),
    ("process_status", "PROCESS_STATUS_MISMATCH"), ("observed", "REQUEST_RESULT_MISMATCH"),
    ("config", "REQUEST_RESULT_MISMATCH"), ("roster", "REQUEST_RESULT_MISMATCH"),
    ("frames_requested", "REQUEST_RESULT_MISMATCH"), ("total_bytes", "READ_ACCOUNTING_MISMATCH"),
    ("read_calls", "READ_ACCOUNTING_MISMATCH"), ("read_window_complete", "READ_WINDOW_MISMATCH"),
    ("read_pid", "IDENTITY_CONTRADICTION"), ("read_label", "READ_SEQUENCE_INVALID"),
    ("identity_omitted", "IDENTITY_READ_MISMATCH"), ("identity_duplicate", "PROCESS_ROSTER_MISMATCH"),
    ("coverage", "COVERAGE_CLAIM_CONFLICT"), ("fixed_claim", "FIXED_NONCLAIM_CONFLICT")])
def test_rehashed_structural_tampering(kind, code):
    items = fixture()
    capture = items[0]
    frame = capture["frames"][0]
    p = frame["processes"][0]
    if kind == "frame_status":
        frame["status"] = "INCOMPLETE"
    elif kind == "process_status":
        p["status"] = "INVALID"
    elif kind == "observed":
        frame["observed_pids"].pop()
    elif kind == "config":
        capture["config"]["clock_ticks_per_second"] = True
    elif kind == "roster":
        capture["roster"]["parent"]["pid"] = 101
    elif kind == "frames_requested":
        capture["frames_requested"] = 1
    elif kind == "total_bytes":
        capture["total_bytes"] += 1
    elif kind == "read_calls":
        p["reads"][0]["read_calls"] += 1
    elif kind == "read_window_complete":
        frame["read_window_complete"] = False
    elif kind == "read_pid":
        p["reads"][0]["pid"] = 200
    elif kind == "read_label":
        p["reads"][0]["label"] = "status"
    elif kind == "identity_omitted":
        p["stat_before_identity"] = None
    elif kind == "identity_duplicate":
        frame["processes"][1] = copy.deepcopy(p)
    elif kind == "coverage":
        capture["worker_coverage"] = "CERTAIN"
    else:
        capture["worker_absence_proven"] = True
    expect(items, code, rehashed=True)


def test_rehashed_failed_frame_cannot_retain_rss():
    items = fixture(fault=PermissionError(SECRET))
    items[0]["frames"][0]["processes"][0]["vmrss_bytes"] = 1024
    expect(items, "FAILED_FRAME_MEMORY_PRESENT", rehashed=True)


@pytest.mark.parametrize("path", ["request", "capture", "frame", "process", "read", "evidence", "environment", "field"])
@pytest.mark.parametrize("extra", [False, True])
def test_exact_schema_keys(path, extra):
    items = fixture()
    c, d, e = items
    obj = {"request": d, "capture": c, "frame": c["frames"][0], "process": c["frames"][0]["processes"][0],
           "read": c["frames"][0]["processes"][0]["reads"][0], "evidence": e,
           "environment": e["environments"][0], "field": e["environments"][0]["clk_tck"]}[path]
    if extra:
        obj[SECRET] = SECRET
    else:
        del obj[next(iter(obj))]
    expect(items, "SCHEMA_INVALID")


@pytest.mark.parametrize("bad", [True, False, 0, -1, 2147483648, "100", None])
def test_malformed_pid(bad):
    items = fixture()
    items[1]["roster"]["parent"]["pid"] = bad
    expect(items, "INTEGER_INVALID")


@pytest.mark.parametrize("bad", [True, -1, provenance.U64 + 1, "10", None])
def test_malformed_starttime(bad):
    items = fixture()
    items[1]["roster"]["parent"]["starttime_ticks"] = bad
    expect(items, "INPUT_CAP_EXCEEDED" if type(bad) is int and bad > provenance.U64 else "INTEGER_INVALID")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 1.5, b"raw", object(), {1: "bad"}])
def test_non_json_evidence_returns_safe_envelope(value):
    c, d, e = fixture()
    e["alignment"] = value
    result = provenance.assess_provenance([c], [d], [e]).to_dict()
    assert result["outcome"] == "INVALID"
    assert "INPUT_NOT_JSON" in result["reason_codes"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("base", [dict, list, str, int])
def test_subclasses_never_execute_user_code(base):
    class Hostile(base):
        def __iter__(self):
            raise HarnessViolation("iter called")

        def __eq__(self, other):
            raise HarnessViolation("eq called")

        def __str__(self):
            raise HarnessViolation("str called")

    value = Hostile()
    result = provenance.assess_provenance(value, [], [])
    assert result.to_dict()["invalid_reason_codes"] == ["INPUT_NOT_JSON"]


@pytest.mark.parametrize("case", ["cycle", "deep", "nodes", "bytes", "string", "frames", "roster", "captures"])
def test_bounds_fail_closed(case):
    c, d, e = fixture()
    captures, requests, evidence = [c], [d], [e]
    if case == "cycle":
        e["alignment"] = e
    elif case == "deep":
        value = None
        for _ in range(provenance.MAX_DEPTH + 1):
            value = [value]
        e["alignment"] = value
    elif case == "nodes":
        e["alignment"] = [None] * provenance.MAX_NODES
    elif case == "bytes":
        e["alignment"] = ["x" * provenance.MAX_STRING] * 129
    elif case == "string":
        e["alignment"] = "x" * (provenance.MAX_STRING + 1)
    elif case == "frames":
        d["frame_rosters"] *= 17
    elif case == "roster":
        d["roster"]["workers"] *= 64
    else:
        captures, requests, evidence = [c] * 9, [d] * 9, [e] * 9
    result = provenance.assess_provenance(captures, requests, evidence).to_dict()
    assert result["outcome"] == "INVALID"
    assert ("INPUT_NOT_JSON" if case == "cycle" else "INPUT_CAP_EXCEEDED") in result["reason_codes"]


def test_full_size_ordinary_adapter_capture_exceeds_global_copy_budget():
    data = request(frames=32)
    data["roster"]["workers"] = [identity(pid) for pid in range(200, 263)]
    pids = [100] + [p["pid"] for p in data["roster"]["workers"]]
    data["frame_rosters"] = [pids[:] for _ in range(32)]
    data["config"].update(max_read_attempts=16384, max_total_bytes=4194304)
    fake = FakeIO(allowed_pids=tuple(str(pid) for pid in pids))
    capture = adapter.NativeProcfsAdapter(fake, fake.clock).sample(data)
    assert fake.handles == {}
    assert capture["outcome"] == adapter.SUCCESS
    assert len(capture["frames"]) == 32
    assert all(len(f["processes"]) == 64 for f in capture["frames"])
    output = provenance.assess_provenance([capture], [data], [probes(data)]).to_dict()
    assert output["outcome"] == "INVALID"
    assert output["invalid_reason_codes"] == ["INPUT_CAP_EXCEEDED"]
    assert output["incomplete_reason_codes"] == output["captures"] == []


@pytest.mark.parametrize("case", ["observed", "registered", "probe"])
def test_duplicate_identities(case):
    items = fixture()
    if case == "observed":
        items[0]["frames"][0]["observed_pids"].append(200)
    elif case == "registered":
        items[1]["roster"]["workers"].append(identity(200))
    else:
        items[2]["processes"].append(copy.deepcopy(items[2]["processes"][0]))
    expect(items, "DUPLICATE_PROBE_IDENTITY" if case == "probe" else "DUPLICATE_IDENTITY")


@pytest.mark.parametrize("key", ["algorithm", "scope", "sha256"])
def test_malformed_integrity_contract(key):
    items = fixture()
    items[0]["integrity"][key] = SECRET
    expect(items, "DIGEST_INVALID" if key == "sha256" else "DIGEST_CONTRACT_UNSUPPORTED")


def test_rejected_request_has_no_invented_request_hash():
    data = request()
    data["config"]["max_bytes"] = 0
    fake = FakeIO()
    capture = adapter.NativeProcfsAdapter(fake, fake.clock).sample(data)
    assert capture["input_sha256"] is None
    output = expect((capture, data, probes(data)), "REQUEST_INTEGRITY_UNAVAILABLE")
    assert "REQUEST_HASH_VERIFIED" not in output["reason_codes"]


@pytest.mark.parametrize("key", ["namespace_inode", "namespace_device", "mount_id", "boot_id"])
def test_cross_capture_environment_mismatch(key):
    c, d, e = fixture(frames=1)
    second_data = copy.deepcopy(d)
    if key == "boot_id":
        second_data["config"]["boot_id"] = OTHER_BOOT
        for p in [second_data["roster"]["parent"]] + second_data["roster"]["workers"]:
            p["boot_id"] = OTHER_BOOT
    fake = FakeIO()
    fake.tick = c["last_read_end_ns"] + 1
    second = adapter.NativeProcfsAdapter(fake, fake.clock).sample(second_data)
    assert second["outcome"] == adapter.SUCCESS
    second_evidence = probes(second_data)
    second_evidence["environments"][0][key]["value"] = OTHER_BOOT if key == "boot_id" else 999
    output = provenance.assess_provenance([c, second], [d, second_data], [e, second_evidence]).to_dict()
    assert output["invalid_reason_codes"] == ["CROSS_CAPTURE_ENVIRONMENT_CONFLICT"]
    assert output["incomplete_reason_codes"] == []
    assert output["outcome"] == "INVALID"


def test_cross_capture_reused_pid_and_replay_order():
    c, d, e = fixture(frames=1)
    second_data = request(frames=1)
    second_data["roster"]["workers"][0]["starttime_ticks"] = 999
    fake = FakeIO(overrides={(200, "stat", 0): stat(200, ticks=999), (200, "stat", 1): stat(200, ticks=999)})
    fake.tick = c["last_read_end_ns"] + 1
    second = adapter.NativeProcfsAdapter(fake, fake.clock).sample(second_data)
    output = provenance.assess_provenance([c, second], [d, second_data], [e, probes(second_data)]).to_dict()
    assert output["outcome"] == "INCOMPLETE"
    assert "PID_REUSE" in output["incomplete_reason_codes"]
    # Reversing otherwise consistent captures is a chronological contradiction.
    output = provenance.assess_provenance([second, c], [second_data, d], [probes(second_data), e]).to_dict()
    assert "CLOCK_REGRESSION" in output["invalid_reason_codes"]


@pytest.mark.parametrize("key,new", [("boot_id", OTHER_BOOT), ("pid_namespace_id", "pidns:88"),
                                    ("clock_ticks_per_second", 250)])
def test_registration_environment_continuity_even_without_probe_readings(key, new):
    c, d, e = fixture(frames=1)
    second_data = copy.deepcopy(d)
    second_data["config"][key] = new
    if key != "clock_ticks_per_second":
        for p in [second_data["roster"]["parent"]] + second_data["roster"]["workers"]:
            p[key] = new
    fake = FakeIO()
    fake.tick = c["last_read_end_ns"] + 1
    second = adapter.NativeProcfsAdapter(fake, fake.clock).sample(second_data)
    second_evidence = probes(second_data)
    for evidence in (e, second_evidence):
        for name in ("boot_id", "namespace_label", "clk_tck"):
            evidence["environments"][0][name] = field(None, status="UNAVAILABLE")
    output = provenance.assess_provenance([c, second], [d, second_data], [e, second_evidence]).to_dict()
    assert output["outcome"] == "INVALID"
    assert "CROSS_CAPTURE_ENVIRONMENT_CONFLICT" in output["invalid_reason_codes"]


@pytest.mark.parametrize("mode,source", [("NATIVE", "TEST_INJECTED"), ("INJECTED", "NATIVE_REQUEST"),
                                        ("INJECTED", "REAL_PROCFS")])
def test_request_source_label_laundering(mode, source):
    items = fixture()
    items[1].update(capture_mode=mode, source_kind=source)
    bind_request(items[0], items[1])
    expect(items, "SOURCE_LABEL_CONFLICT")


@pytest.mark.parametrize("value", [None, True, [], {}, 1, "bad"])
@pytest.mark.parametrize("location", ["capture", "request", "evidence", "field", "processes", "frame"])
def test_malformed_nested_shapes_are_serializable(value, location):
    c, d, e = fixture()
    if location == "capture":
        c = value
    elif location == "request":
        d = value
    elif location == "evidence":
        e = value
    elif location == "field":
        e["environments"][0]["clk_tck"] = value
    elif location == "processes":
        c["frames"][0]["processes"] = value
    else:
        c["frames"][0] = value
    output = provenance.assess_provenance([c], [d], [e]).to_dict()
    assert output["outcome"] == "INVALID"
    json.dumps(output, allow_nan=False)


def test_end_without_start_is_invalid_even_on_failed_frame():
    data = request(frames=3)
    data["config"]["max_read_attempts"] = 1
    fake = FakeIO()
    capture = adapter.NativeProcfsAdapter(fake, fake.clock).sample(data)
    record = capture["frames"][0]["processes"][1]["reads"][0]
    assert record["start_ns"] is None
    record["end_ns"] = capture["last_read_end_ns"]
    expect((capture, data, probes(data)), "READ_WINDOW_MISMATCH", rehashed=True)


def test_rehashed_capture_cannot_exceed_configured_global_read_cap():
    items = fixture()
    items[1]["config"]["max_read_attempts"] = 1
    items[0]["config"]["max_read_attempts"] = 1
    bind_request(items[0], items[1])
    expect(items, "READ_ACCOUNTING_MISMATCH")


def test_consistent_ordered_capture_sequence_is_still_nonqualifying():
    c, d, e = fixture(frames=1)
    fake = FakeIO()
    fake.tick = c["last_read_end_ns"] + 1
    second = adapter.NativeProcfsAdapter(fake, fake.clock).sample(d)
    result = provenance.assess_provenance([c, second], [d, d], [e, e]).to_dict()
    assert result["outcome"] == "UNVERIFIED"
    assert result["invalid_reason_codes"] == result["incomplete_reason_codes"] == []
    assert len(result["captures"]) == 2
    assert result["captures"][1]["preceding_capture_gap_ns"] == 2
    assert result["observed_windows"]["first_read_start_ns"] == c["first_read_start_ns"]
    assert result["observed_windows"]["last_read_end_ns"] == second["last_read_end_ns"]


def test_replay_key_order_and_envelope_immutability():
    items = fixture()

    def reverse(value):
        if type(value) is dict:
            return {key: reverse(value[key]) for key in reversed(value)}
        if type(value) is list:
            return [reverse(v) for v in value]
        return value

    first = provenance.assess_provenance([items[0]], [items[1]], [items[2]])
    again = provenance.assess_provenance(*[[reverse(i)] for i in items])
    assert first.serialized == again.serialized
    assert first == provenance.assess_provenance([items[0]], [items[1]], [items[2]])
    detached = first.to_dict()
    detached["captures"].clear()
    assert first.to_dict()["captures"]
    with pytest.raises(FrozenInstanceError):
        first.serialized = "changed"


@pytest.mark.parametrize("where", ["reason_location", "run_id", "namespace_label", "unknown_key", "probe_source"])
def test_no_input_strings_leak(where):
    items = fixture(fault=PermissionError(SECRET))
    c, d, e = items
    if where == "reason_location":
        c["reasons"][0]["location"] = SECRET
        rehash(c)
    elif where == "run_id":
        d["run_id"] = SECRET
    elif where == "namespace_label":
        e["environments"][0]["namespace_label"]["value"] = SECRET
    elif where == "unknown_key":
        e[SECRET] = SECRET
    else:
        e["environments"][0]["boot_id"]["source"] = SECRET
    output = assess(*items)
    assert SECRET not in adapter.canonical_json(output)
