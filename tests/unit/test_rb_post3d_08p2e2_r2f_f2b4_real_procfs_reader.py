"""Artificial byte streams only; execution belongs to the orchestrator."""

import ast
import builtins
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import pytest

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_real_procfs_reader as reader
from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_procfs_provider as d2a
from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_sampler as d1

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_real_procfs_reader.py"
BOOT = "11111111-2222-3333-4444-555555555555"
EVENTS = b"low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n"


def identity(pid=100):
    return {"pid": pid, "ppid": 1 if pid == 100 else 100, "starttime_ticks": pid // 10,
            "boot_id": BOOT, "pid_namespace_id": "pidns:77", "role": "parent" if pid == 100 else "worker"}


def request(workers=True, frames=1, smaps=False, cgroup=False):
    pids = [100, 200] if workers else [100]
    data = {"schema": reader.SCHEMA, "source_kind": "TEST_INJECTED", "run_id": "fixture-run",
            "reader_source_sha256": None,
            "config": {"clock_ticks_per_second": 100, "boot_id": BOOT, "pid_namespace_id": "pidns:77",
                       "max_read_skew_ns": 1000, "max_bytes": 4096, "max_total_bytes": 1048576,
                       "max_read_attempts": 1000,
                       "smaps_rollup_policy": "OPTIONAL_DIAGNOSTIC" if smaps else "NOT_SAMPLED"},
            "roster": {"parent": identity(), "workers": [identity(200)] if workers else [], "complete": True},
            "frame_rosters": [pids[:] for _ in range(frames)], "cgroup": None}
    if cgroup:
        data["cgroup"] = {"enabled": True, "token": "owned-fixture", "controller_id": "cgv2:fixture",
                          "membership": pids[:], "membership_provenance": "fixture-registry",
                          "boot_id": BOOT, "pid_namespace_id": "pidns:77",
                          "baseline": {"memory_current_bytes": 100, "memory_peak_bytes": 200,
                                       "events": {"low": 0, "high": 0, "max": 0, "oom": 0, "oom_kill": 0},
                                       "observed_ns": 0, "provenance": "fixture-baseline"}}
    return data


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
    return ("%d (%s) %s " % (pid, comm, state) + " ".join(fields[n] for n in range(4, 53)) + "\n").encode()


def status(pid=100, ppid=None, state="S", rss=5, hwm=20, memory=True):
    text = ("Name:\tfixture-name\nUmask:\t0022\nState:\t%s (fixture)\nTgid:\t%d\nNgid:\t0\n"
            "Pid:\t%d\nPPid:\t%d\nTracerPid:\t0\nUid:\t1000\t1000\t1000\t1000\n"
            "Gid:\t1000\t1000\t1000\t1000\nGroups:\t1000 27\nThreads:\t1\nSigQ:\t0/30000\n"
            "Speculation_Store_Bypass:\tthread vulnerable\nx86_Thread_features:\t\n" %
            (state, pid, pid, (1 if pid == 100 else 100) if ppid is None else ppid))
    if memory:
        text += "VmRSS:\t%d kB\nVmHWM:\t%d kB\nRssAnon:\t3 kB\n" % (rss, hwm)
    return text.encode()


def rollup():
    return (b"00400000-7ffffffff000 ---p 00000000 00:00 0                          [rollup]\n"
            b"Rss: 9 kB\nPss: 6 kB\nPss_Anon: 3 kB\nPss_File: 3 kB\nPss_Shmem: 0 kB\n"
            b"Shared_Clean: 1 kB\nShared_Dirty: 0 kB\nPrivate_Clean: 2 kB\nPrivate_Dirty: 6 kB\n"
            b"Referenced: 9 kB\nAnonymous: 6 kB\nLazyFree: 0 kB\nAnonHugePages: 0 kB\n"
            b"ShmemPmdMapped: 0 kB\nFilePmdMapped: 0 kB\nShared_Hugetlb: 0 kB\n"
            b"Private_Hugetlb: 0 kB\nSwap: 0 kB\nSwapPss: 0 kB\nLocked: 0 kB\n")


class Fixture:
    def __init__(self, overrides=None, ticks=None):
        self.overrides = overrides or {}
        self.ticks = iter(ticks) if ticks is not None else None
        self.tick_value = 0
        self.calls = []
        self.counts = {}

    def clock(self):
        self.calls.append(("clock",))
        value = next(self.ticks) if self.ticks is not None else self.tick_value
        self.tick_value += 1
        if isinstance(value, BaseException):
            raise value
        return value

    def value(self, key, default):
        index = self.counts.get(key, 0)
        self.counts[key] = index + 1
        value = self.overrides.get(key, default)
        if type(value) is list:
            value = value[min(index, len(value) - 1)]
        if isinstance(value, BaseException):
            raise value
        return value

    def read(self, path, limit):
        self.calls.append(("read", path, limit))
        root, proc, raw_pid, kind = path.split("/")
        assert root == "" and proc == "proc" and kind in ("stat", "status", "smaps_rollup")
        pid = int(raw_pid)
        assert pid in (100, 200)
        # All path resolution is a pure lookup; this never opens a file.
        default = stat(pid) if kind == "stat" else status(pid) if kind == "status" else rollup()
        return self.value(path, default)

    def cgroup(self, token, kind, limit):
        self.calls.append(("cgroup", token, kind, limit))
        assert token == "owned-fixture"
        return self.value(kind, {"memory.current": b"300\n", "memory.peak": b"400\n", "memory.events": EVENTS}[kind])


@pytest.fixture(autouse=True)
def forbid_live_io(monkeypatch):
    # Guards even a mistakenly introduced native fallback. Test-source reads are
    # allowed; procfs, cgroups, subprocesses and sockets are always forbidden.
    def blocked(*args, **kwargs):
        raise AssertionError("live I/O is forbidden in D2-B1")

    def guard(original):
        def wrapped(path, *args, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)):
                name = os.fsdecode(path)
                assert not (name == "/proc" or name.startswith("/proc/") or
                            name == "/sys/fs/cgroup" or name.startswith("/sys/fs/cgroup/"))
            return original(path, *args, **kwargs)
        return wrapped

    for obj, name in ((builtins, "open"), (io, "open"), (os, "open"), (os, "listdir"), (os, "scandir"), (os, "readlink")):
        monkeypatch.setattr(obj, name, guard(getattr(obj, name)))
    for obj, names in ((subprocess, ("Popen", "run", "call", "check_call", "check_output")),
                       (socket, ("socket", "create_connection")), (os, ("system", "fork", "posix_spawn"))):
        for name in names:
            if hasattr(obj, name):
                monkeypatch.setattr(obj, name, blocked)


def codes(result):
    return set(result["invalid_reason_codes"] + result["incomplete_reason_codes"])


def sample(data=None, fixture=None, expected=None, cgroup_reader=True):
    fixture = fixture if fixture is not None else Fixture()
    result = reader.RealProcfsReader(fixture.read, fixture.clock, fixture.cgroup if cgroup_reader else None).sample(
        request() if data is None else data)
    payload = {k: v for k, v in result.items() if k != "integrity"}
    assert result["integrity"] == {"algorithm": "sha256", "scope": "canonical result excluding integrity",
                                    "sha256": hashlib.sha256(reader.canonical_json(payload).encode()).hexdigest()}
    assert result["source_kind"] == "TEST_INJECTED"
    assert result["origin_attestation"] == "UNVERIFIED"
    assert result["production_memory_qualification"] == "INCONCLUSIVE"
    assert result["production_chronological_peak"] == "NOT_OBSERVED"
    assert result["production_workload_measured"] is False
    assert result["atomic_snapshot"] is False
    assert result["worker_absence_proven"] is False
    assert result["holder_release"] == "NOT_ESTABLISHED"
    assert result["simultaneous_holder_occupancy"] == "NOT_ESTABLISHED"
    assert result["starttime_alignment"] == "NOT_CALIBRATED"
    assert result["bound_claim"] == "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK"
    if expected:
        assert expected in codes(result)
        assert result["outcome"] != reader.SUCCESS
    for frame in result["frames"]:
        if frame["reason_codes"]:
            for process in frame["processes"]:
                assert process["status"] != reader.SUCCESS
                assert process["vmrss_bytes"] is process["vmhwm_bytes"] is process["smaps_rollup"] is None
            if frame["cgroup"]:
                cg = frame["cgroup"]
                assert cg["status"] != reader.SUCCESS
                assert cg["memory_current_bytes"] is cg["memory_peak_bytes"] is cg["events"] is None
    return result


@pytest.mark.parametrize("workers", [False, True])
@pytest.mark.parametrize("smaps", [False, True])
@pytest.mark.parametrize("cgroup", [False, True])
def test_normal_bounded_order_and_provenance(workers, smaps, cgroup):
    f = Fixture()
    data = request(workers=workers, smaps=smaps, cgroup=cgroup)
    result = sample(data, f)
    assert result["outcome"] == reader.SUCCESS
    assert result["worker_coverage"] == "REGISTERED_ROSTER_OBSERVED"
    assert result["unregistered_worker_coverage"] == "NOT_ESTABLISHED"
    assert result["run_id"] == "fixture-run"
    assert result["reader_version"] == reader.READER_VERSION
    assert result["reader_source_hash_provenance"] == "NOT_RECORDED"
    assert result["input_sha256"] == hashlib.sha256(reader.canonical_json(data).encode()).hexdigest()
    expected = []
    raws = []
    for pid in ([100, 200] if workers else [100]):
        for kind in (["stat", "status", "smaps_rollup", "stat"] if smaps else ["stat", "status", "stat"]):
            expected += [("clock",), ("read", "/proc/%d/%s" % (pid, kind), 4097), ("clock",)]
            raws.append(stat(pid) if kind == "stat" else status(pid) if kind == "status" else rollup())
    if cgroup:
        for kind, raw in (("memory.current", b"300\n"), ("memory.peak", b"400\n"), ("memory.events", EVENTS)):
            expected += [("clock",), ("cgroup", "owned-fixture", kind, 4097), ("clock",)]
            raws.append(raw)
    assert f.calls == expected
    frame = result["frames"][0]
    records = [r for p in frame["processes"] for r in p["reads"]] + (frame["cgroup"]["reads"] if cgroup else [])
    assert result["read_attempts"] == len(records)
    assert result["total_bytes"] == sum(map(len, raws))
    assert result["first_read_start_ns"] == 0
    assert result["last_read_end_ns"] == len(records) * 2 - 1
    assert result["read_skew_ns"] == frame["read_skew_ns"] == len(records) * 2 - 1
    assert frame["read_window_complete"] is True
    for index, (record, raw) in enumerate(zip(records, raws), 1):
        assert record["attempt"] == index and record["status"] == "OK"
        assert record["byte_length"] == len(raw)
        assert record["sha256"] == hashlib.sha256(raw).hexdigest()
    assert all(p["vmrss_bytes"] == 5120 and p["vmhwm_bytes"] == 20480 for p in frame["processes"])
    assert not any("aggregate" in key or "rss_sum" in key for key in result)


@pytest.mark.parametrize("comm", ["simple", "space space", "a (b) c", ") ) ( ((", "λ (x)"])
def test_final_command_parenthesis(comm):
    result = sample(fixture=Fixture({"/proc/100/stat": stat(comm=comm)}))
    assert result["outcome"] == reader.SUCCESS
    assert comm not in reader.canonical_json(result)


@pytest.mark.parametrize("ticks", [0, 9223372036854775807, 9223372036854775808, 18446744073709551615])
def test_full_u64_starttime(ticks):
    data = request(workers=False)
    data["roster"]["parent"]["starttime_ticks"] = ticks
    assert sample(data, Fixture({"/proc/100/stat": stat(ticks=ticks)}))["outcome"] == reader.SUCCESS


@pytest.mark.parametrize("field,value", [(8, "-9223372036854775808"), (18, "9223372036854775807"),
                                         (25, "18446744073709551615"), (52, "-9223372036854775808")])
def test_stat_i64_u64_edges(field, value):
    assert sample(fixture=Fixture({"/proc/100/stat": stat(overrides={field: value})}))["outcome"] == reader.SUCCESS


@pytest.mark.parametrize("field,value", [(8, "-9223372036854775809"), (18, "9223372036854775808"),
    (25, "18446744073709551616"), (22, "-1"), (25, "9" * 21), (25, "+1"), (25, "1.5")])
def test_stat_numeric_rejection(field, value):
    sample(fixture=Fixture({"/proc/100/stat": stat(overrides={field: value})}), expected="RAW_TEXT_MALFORMED")


@pytest.mark.parametrize("before", [False, True])
def test_pid_reuse_before_or_after(before):
    values = [stat(ticks=11), stat()] if before else [stat(), stat(ticks=11)]
    f = Fixture({"/proc/100/stat": values})
    r = sample(fixture=f, expected="PID_REUSE_OR_IDENTITY_RACE")
    assert r["outcome"] == "INCOMPLETE"
    if before:
        assert not any(c[:2] == ("read", "/proc/100/status") for c in f.calls)
        assert "PRIOR_IDENTITY_UNVERIFIED" in codes(r)


@pytest.mark.parametrize("kind", ["stat", "status"])
@pytest.mark.parametrize("field", ["pid", "ppid"])
def test_identity_contradictions(kind, field):
    kwargs = {field: 999}
    raw = stat(**kwargs) if kind == "stat" else status(**kwargs)
    expected = "STATUS_STAT_CONTRADICTION" if kind == "status" else (
        "PROCESS_REPARENTED" if field == "ppid" else "PID_REUSE_OR_IDENTITY_RACE")
    sample(fixture=Fixture({"/proc/100/" + kind: raw}), expected=expected)


@pytest.mark.parametrize("kind", ["stat", "status"])
@pytest.mark.parametrize("state", ["Z", "X", "x"])
def test_dead_or_zombie_without_memory(kind, state):
    raw = stat(state=state) if kind == "stat" else status(state=state, memory=False)
    assert sample(fixture=Fixture({"/proc/100/" + kind: raw}), expected="PROCESS_NOT_LIVE")["outcome"] == "INCOMPLETE"


def test_exit_mm_before_zombie():
    assert sample(fixture=Fixture({"/proc/100/status": status(memory=False)}),
                  expected="PROCESS_MEMORY_UNAVAILABLE")["outcome"] == "INCOMPLETE"


@pytest.mark.parametrize("place", ["parent", "worker", "cgroup"])
@pytest.mark.parametrize("domain,expected", [("boot_id", "BOOT_ID_MISMATCH"), ("pid_namespace_id", "PID_NAMESPACE_MISMATCH")])
def test_provenance_domains_rejected_before_io(place, domain, expected):
    data = request(cgroup=True)
    target = data["roster"]["parent"] if place == "parent" else data["roster"]["workers"][0] if place == "worker" else data["cgroup"]
    target[domain] = "different-domain"
    f = Fixture()
    sample(data, f, expected)
    assert f.calls == []


@pytest.mark.parametrize("error,code,cls", [(FileNotFoundError("secret"), "PROCESS_VANISHED", "FileNotFoundError"),
    (ProcessLookupError("secret"), "PROCESS_VANISHED", "ProcessLookupError"),
    (PermissionError("secret"), "PERMISSION_DENIED", "PermissionError"),
    (OSError("secret"), "READ_FAILED", "OSError"), (ValueError("secret"), "READER_EXCEPTION", "ValueError")])
def test_read_failures_preserve_window_not_message(error, code, cls):
    result = sample(fixture=Fixture({"/proc/200/status": error}), expected=code)
    record = result["frames"][0]["processes"][1]["reads"][1]
    assert record["exception_class"] == cls
    assert record["start_ns"] == 8 and record["end_ns"] == 9
    assert record["sha256"] is None and record["byte_length"] is None
    assert "secret" not in reader.canonical_json(result)
    assert result["worker_coverage"] == "UNCERTAIN"


def test_base_exception_is_not_hidden():
    with pytest.raises(KeyboardInterrupt):
        sample(fixture=Fixture({"/proc/100/status": KeyboardInterrupt()}))


@pytest.mark.parametrize("late", [False, True])
def test_registered_worker_departure_and_late_arrival(late):
    good = [stat(200), stat(200)]
    missing = [FileNotFoundError(), FileNotFoundError()]
    values = missing + good if late else good + missing
    r = sample(request(frames=2), Fixture({"/proc/200/stat": values}), "PROCESS_VANISHED")
    assert r["worker_coverage"] == "UNCERTAIN"
    good_index = 1 if late else 0
    assert r["frames"][good_index]["status"] == reader.SUCCESS
    assert r["frames"][good_index]["processes"][1]["vmrss_bytes"] == 5120
    assert all(len(f["processes"]) == 2 for f in r["frames"])


@pytest.mark.parametrize("observed,complete,expected", [([100], True, "REGISTERED_PROCESS_MISSING"),
    ([100, 200, 999], True, "UNKNOWN_PROCESS"), ([100, 200], False, "ROSTER_INCOMPLETE"),
    ([], True, "REGISTERED_PROCESS_MISSING")])
def test_roster_coverage_is_explicit(observed, complete, expected):
    data = request()
    data["frame_rosters"][0] = observed
    data["roster"]["complete"] = complete
    f = Fixture()
    r = sample(data, f, expected)
    assert len(r["frames"][0]["processes"]) == 2
    assert not any("/999/" in str(c) for c in f.calls)


@pytest.mark.parametrize("late", [False, True])
def test_caller_reported_worker_missing_in_one_frame(late):
    data = request(frames=2)
    data["frame_rosters"][0 if late else 1] = [100]
    r = sample(data, expected="REGISTERED_PROCESS_MISSING")
    assert r["frames"][1 if late else 0]["status"] == reader.SUCCESS


class BytesSubclass(bytes):
    pass


@pytest.mark.parametrize("raw", ["text\n", bytearray(b"x\n"), memoryview(b"x\n"), BytesSubclass(b"x\n"), None, 5])
def test_exact_bytes_callback_contract(raw):
    sample(fixture=Fixture({"/proc/100/status": raw}), expected="READER_CONTRACT_VIOLATION")


@pytest.mark.parametrize("raw,expected", [(b"\xff\n", "INVALID_UTF8"), (b"x\x00\n", "RAW_TEXT_MALFORMED"),
    (b"x\x01\n", "RAW_TEXT_MALFORMED"), (b"x\x7f\n", "RAW_TEXT_MALFORMED"),
    (b"x\xc2\x80\n", "RAW_TEXT_MALFORMED"), (b"x\xe2\x80\xa8\n", "RAW_TEXT_MALFORMED"),
    (b"", "TRUNCATED"), (b"Pid: 100", "TRUNCATED"), (b" " * 65 + b"\n", "RAW_TEXT_MALFORMED"),
    (b"9" * 21 + b"\n", "RAW_TEXT_MALFORMED")])
def test_binary_decode_and_text_failures(raw, expected):
    r = sample(fixture=Fixture({"/proc/100/status": raw}), expected=expected)
    record = r["frames"][0]["processes"][0]["reads"][1]
    assert record["sha256"] == hashlib.sha256(raw).hexdigest()
    assert record["byte_length"] == len(raw)


@pytest.mark.parametrize("extra,expected", [(1, "OVERSIZED"), (2, "READER_CONTRACT_VIOLATION")])
def test_read_limit_plus_one(extra, expected):
    raw = b"x" * (4096 + extra)
    r = sample(fixture=Fixture({"/proc/100/status": raw}), expected=expected)
    record = r["frames"][0]["processes"][0]["reads"][1]
    assert record["byte_length"] == len(raw)
    assert record["sha256"] == (hashlib.sha256(raw).hexdigest() if extra == 1 else None)
    assert record["status"] == "FAILED"


def test_exact_max_bytes_is_not_truncated():
    raw = status()
    # Fill a harmless unselected field to exactly the cap.
    raw += b"Comment: " + b"a" * (4096 - len(raw) - 10) + b"\n"
    assert len(raw) == 4096
    assert sample(fixture=Fixture({"/proc/100/status": raw}))["outcome"] == reader.SUCCESS


@pytest.mark.parametrize("raw,expected", [(status() + b"Pid: 100\n", "DUPLICATE_FIELD"),
    (status().replace(b"Pid:\t100\n", b"Pid: bad\n"), "RAW_TEXT_MALFORMED"),
    (status().replace(b"PPid:\t1\n", b""), "MISSING_FIELD"),
    (status().replace(b"State:\tS (fixture)\n", b"State: BAD\n"), "RAW_TEXT_MALFORMED"),
    (status() + b"broken field\n", "RAW_TEXT_MALFORMED"), (status() + b"\n", "RAW_TEXT_MALFORMED"),
    (status().replace(b"5 kB", b"5 MB"), "RAW_TEXT_MALFORMED"),
    (status(rss=21, hwm=20), "COUNTER_INCONSISTENT")])
def test_status_malformed_or_contradictory(raw, expected):
    sample(fixture=Fixture({"/proc/100/status": raw}), expected=expected)


@pytest.mark.parametrize("raw,expected", [(b"100 broken\n", "RAW_TEXT_MALFORMED"),
    (b"100 (x) R 1\n", "MISSING_FIELD"), (stat().replace(b") R ", b") BAD "), "RAW_TEXT_MALFORMED"),
    (stat() + b"\n", "RAW_TEXT_MALFORMED"), (stat(comm="line\nbreak"), "RAW_TEXT_MALFORMED")])
def test_stat_malformed(raw, expected):
    sample(fixture=Fixture({"/proc/100/stat": raw}), expected=expected)


@pytest.mark.parametrize("ticks,expected,attempts", [([10, 9], "CLOCK_NON_MONOTONIC", 1),
    ([10, RuntimeError("secret")], "CLOCK_FAILURE", 1), ([True], "CLOCK_FAILURE", 0),
    ([1.5], "CLOCK_FAILURE", 0), ([-1], "CLOCK_FAILURE", 0),
    ([9223372036854775808], "CLOCK_FAILURE", 0)])
def test_clock_failure_stops_capture(ticks, expected, attempts):
    f = Fixture(ticks=ticks)
    r = sample(request(frames=2, cgroup=True), f, expected)
    assert r["read_attempts"] == attempts
    assert len(r["frames"]) == 1
    assert r["frames_requested"] == 2
    assert r["frames"][0]["read_window_complete"] is False
    assert len(r["frames"][0]["processes"]) == 2
    assert "secret" not in reader.canonical_json(r)


def test_clock_ties_are_legal():
    assert sample(fixture=Fixture(ticks=[3] * 12))["read_skew_ns"] == 0


def test_large_skew_demotes_entire_frame():
    data = request(cgroup=True)
    data["config"]["max_read_skew_ns"] = 1
    sample(data, expected="READ_SKEW_EXCEEDED")


def test_read_and_clock_failures_are_both_retained():
    r = sample(request(workers=False), Fixture({"/proc/100/stat": PermissionError()}, ticks=[0, -1]),
               "CLOCK_FAILURE")
    assert "PERMISSION_DENIED" in codes(r)


def test_bytes_retained_on_end_clock_failure():
    raw = stat()
    r = sample(request(workers=False), Fixture(ticks=[5, 4]), "CLOCK_NON_MONOTONIC")
    record = r["frames"][0]["processes"][0]["reads"][0]
    assert record["sha256"] == hashlib.sha256(raw).hexdigest()
    assert record["end_ns"] is None
    assert r["last_read_end_ns"] is None


@pytest.mark.parametrize("raw,expected", [("wrong type", "READER_CONTRACT_VIOLATION"),
    (b"x" * 4097, "OVERSIZED"), (b"x" * 4098, "READER_CONTRACT_VIOLATION")])
def test_byte_failure_and_clock_failure_are_both_retained(raw, expected):
    r = sample(request(workers=False), Fixture({"/proc/100/stat": raw}, ticks=[0, -1]), "CLOCK_FAILURE")
    assert expected in codes(r)
    assert expected in r["frames"][0]["processes"][0]["reads"][0]["reason_codes"]


@pytest.mark.parametrize("cap,expected", [(1, "TOTAL_BYTES_CAP_EXCEEDED"), (len(stat()), "TOTAL_BYTES_CAP_EXCEEDED")])
def test_total_byte_cap(cap, expected):
    data = request(frames=2)
    data["config"]["max_total_bytes"] = cap
    f = Fixture()
    # Obey the smaller passed limit, including the overlimit detection byte.
    def bounded(path, limit):
        return f.read(path, limit)[:limit]
    r = reader.RealProcfsReader(bounded, f.clock).sample(data)
    assert expected in codes(r) and r["outcome"] != reader.SUCCESS
    assert r["total_bytes"] <= cap + 1
    assert len(r["frames"][0]["processes"]) == 2


def test_attempt_cap_keeps_partial_frame_identities():
    data = request(frames=2, cgroup=True)
    data["config"]["max_read_attempts"] = 2
    r = sample(data, expected="READ_ATTEMPT_CAP_EXCEEDED")
    assert r["read_attempts"] == 2 and len(r["frames"]) == 1
    assert len(r["frames"][0]["processes"]) == 2


def test_failed_frame_clears_cgroup_and_process_values():
    r = sample(request(cgroup=True), Fixture({"/proc/100/status": PermissionError()}), "PERMISSION_DENIED")
    assert all(record["status"] == "OK" for record in r["frames"][0]["cgroup"]["reads"])
    assert r["frames"][0]["cgroup"]["memory_current_bytes"] is None


@pytest.mark.parametrize("kind,raw,expected", [("memory.current", b"x\n", "RAW_TEXT_MALFORMED"),
    ("memory.peak", b"199\n", "COUNTER_INCONSISTENT"),
    ("memory.events", b"low 0\n", "MISSING_FIELD"),
    ("memory.events", EVENTS + b"low 0\n", "DUPLICATE_FIELD"),
    ("memory.current", PermissionError(), "PERMISSION_DENIED"),
    ("memory.peak", FileNotFoundError(), "CGROUP_UNAVAILABLE"),
    ("memory.events", EVENTS.replace(b"low 0", b"low -1"), "RAW_TEXT_MALFORMED")])
def test_cgroup_failures(kind, raw, expected):
    sample(request(cgroup=True), Fixture({kind: raw}), expected)


def test_cgroup_separate_and_disabled_by_default():
    f = Fixture()
    assert sample(fixture=f)["frames"][0]["cgroup"] is None
    assert not any(c[0] == "cgroup" for c in f.calls)
    sample(request(cgroup=True), expected="CGROUP_READER_NOT_CONFIGURED", cgroup_reader=False)


def test_baseline_chronology():
    data = request(cgroup=True)
    data["cgroup"]["baseline"]["observed_ns"] = 1000
    sample(data, expected="BASELINE_CHRONOLOGY_INVALID")


@pytest.mark.parametrize("which", ["baseline", "earlier_frame", "failed_frame"])
def test_events_decrease_against_each_reference(which):
    data = request(cgroup=True, frames=1 if which == "baseline" else 2)
    nonzero = EVENTS.replace(b"low 0", b"low 1")
    overrides = {"memory.events": EVENTS}
    if which == "baseline":
        data["cgroup"]["baseline"]["events"]["low"] = 1
    else:
        overrides["memory.events"] = [nonzero, EVENTS]
        if which == "failed_frame":
            overrides["/proc/100/status"] = [PermissionError(), status()]
    r = sample(data, Fixture(overrides), "COUNTER_INCONSISTENT")
    if which != "baseline":
        assert "COUNTER_INCONSISTENT" in r["frames"][1]["reason_codes"]


def test_peak_decrease_against_earlier_frame():
    sample(request(cgroup=True, frames=2), Fixture({"memory.peak": [b"500\n", b"400\n"]}), "COUNTER_INCONSISTENT")


def test_sequential_current_and_peak_have_no_atomic_assumption():
    data = request(cgroup=True)
    data["cgroup"]["baseline"]["memory_current_bytes"] = 10000
    r = sample(data, Fixture({"memory.current": b"20000\n"}))
    assert r["outcome"] == reader.SUCCESS
    assert r["frames"][0]["cgroup"]["memory_current_bytes"] == 20000
    assert r["frames"][0]["processes"][0]["vmrss_bytes"] == 5120


@pytest.mark.parametrize("token", ["../other", "/absolute", "x/y", "x\\y", "a..b", "", "user@1000.service"])
def test_opaque_cgroup_token_has_no_path_semantics(token):
    data = request(cgroup=True)
    data["cgroup"]["token"] = token
    f = Fixture()
    sample(data, f, "CGROUP_CONFIGURATION_INVALID")
    assert f.calls == []


@pytest.mark.parametrize("change", ["enabled", "membership", "events"])
def test_cgroup_closed_configuration(change):
    data = request(cgroup=True)
    if change == "enabled":
        data["cgroup"]["enabled"] = False
    elif change == "membership":
        data["cgroup"]["membership"] = [100]
    else:
        del data["cgroup"]["baseline"]["events"]["oom"]
    f = Fixture()
    sample(data, f, "CGROUP_CONFIGURATION_INVALID")
    assert f.calls == []


@pytest.mark.parametrize("raw,expected", [(b"Rss: 1 kB\n", "MISSING_FIELD"),
    (rollup() + b"Rss: 1 kB\n", "DUPLICATE_FIELD"),
    (rollup().replace(b"Swap: 0 kB", b"Swap: bad"), "RAW_TEXT_MALFORMED"),
    (PermissionError(), "PERMISSION_DENIED")])
def test_optional_rollup_is_conservatively_frame_wide(raw, expected):
    sample(request(smaps=True, cgroup=True), Fixture({"/proc/200/smaps_rollup": raw}), expected)


@pytest.mark.parametrize("source,expected", [("REAL_PROCFS", "REAL_SOURCE_NOT_AUTHORIZED"),
    ("NATIVE", "REAL_SOURCE_NOT_AUTHORIZED"), ("FAKE_FIXTURE", "SOURCE_KIND_NOT_ACCEPTED"),
    ("INJECTED_SYNTHETIC", "SOURCE_KIND_NOT_ACCEPTED"), ("unknown", "SOURCE_KIND_NOT_ACCEPTED")])
def test_selected_real_or_laundered_source_never_calls_reader(source, expected):
    data = request()
    data["source_kind"] = source
    def forbidden(*args):
        raise AssertionError("a rejected source must never invoke any callback")
    r = reader.RealProcfsReader(forbidden, forbidden, forbidden).sample(data)
    assert expected in codes(r) and r["frames"] == []
    assert r["source_kind"] == "TEST_INJECTED" and r["origin_attestation"] == "UNVERIFIED"


@pytest.mark.parametrize("field", ["origin_attestation", "production_memory_qualification", "outcome", "path", "native"])
def test_caller_cannot_supply_attestation_or_extra_fields(field):
    data = request()
    data[field] = "LOCAL_COLLECTOR_RECORDED"
    f = Fixture()
    sample(data, f, "UNKNOWN_FIELD")
    assert f.calls == []


@pytest.mark.parametrize("path,value,expected", [
    (("schema",), "old", "SCHEMA_VERSION_MISMATCH"),
    (("run_id",), "../escape", "CONFIGURATION_INVALID"),
    (("reader_source_sha256",), "not-a-hash", "CONFIGURATION_INVALID"),
    (("config", "max_bytes"), 65537, "CONFIGURATION_INVALID"),
    (("config", "max_total_bytes"), 4194305, "CONFIGURATION_INVALID"),
    (("config", "max_read_attempts"), 8289, "CONFIGURATION_INVALID"),
    (("config", "clock_ticks_per_second"), 0, "CONFIGURATION_INVALID"),
    (("config", "max_read_skew_ns"), -1, "CONFIGURATION_INVALID"),
    (("config", "boot_id"), "bad", "CONFIGURATION_INVALID"),
    (("config", "pid_namespace_id"), "pid:[77]", "CONFIGURATION_INVALID"),
    (("config", "smaps_rollup_policy"), "REQUIRED", "CONFIGURATION_INVALID"),
    (("roster", "parent", "pid"), True, "IDENTITY_INVALID"),
    (("roster", "parent", "pid"), 0, "IDENTITY_INVALID"),
    (("roster", "parent", "pid"), 2147483648, "IDENTITY_INVALID"),
    (("roster", "parent", "starttime_ticks"), -1, "IDENTITY_INVALID"),
    (("roster", "parent", "starttime_ticks"), 18446744073709551616, "INPUT_CAP_EXCEEDED"),
    (("roster", "complete"), 1, "SCHEMA_INVALID"),
    (("frame_rosters",), [], "INPUT_CAP_EXCEEDED"),
    (("frame_rosters",), [[100]] * 33, "INPUT_CAP_EXCEEDED"),
    (("frame_rosters",), [[100, 100]], "DUPLICATE_IDENTITY"),
])
def test_closed_schema_values(path, value, expected):
    data = request()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    f = Fixture()
    sample(data, f, expected)
    assert f.calls == []


@pytest.mark.parametrize("section", ["root", "config", "parent", "roster", "cgroup", "baseline"])
def test_missing_or_unknown_schema_fields(section):
    for missing in (False, True):
        data = request(cgroup=True)
        target = {"root": data, "config": data["config"], "parent": data["roster"]["parent"],
                  "roster": data["roster"], "cgroup": data["cgroup"], "baseline": data["cgroup"]["baseline"]}[section]
        if missing:
            del target[next(iter(target))]
        else:
            target["unexpected"] = 1
        f = Fixture()
        sample(data, f, "SCHEMA_INVALID" if missing else "UNKNOWN_FIELD")
        assert not f.calls


class DictSubclass(dict):
    pass


@pytest.mark.parametrize("value,expected", [(float("nan"), "INPUT_NOT_JSON"), (1.5, "INPUT_NOT_JSON"),
    ({1: "x"}, "INPUT_NOT_JSON"), (DictSubclass(), "INPUT_NOT_JSON"),
    (b"bytes", "INPUT_NOT_JSON"), ("x" * 65537, "INPUT_CAP_EXCEEDED"),
    ("\ud800", "INPUT_NOT_JSON"), ([0] * 20001, "INPUT_CAP_EXCEEDED")])
def test_non_json_or_excessive_input(value, expected):
    f = Fixture()
    sample(value, f, expected)
    assert not f.calls


def test_cyclic_and_deep_input():
    cyclic = []
    cyclic.append(cyclic)
    sample(cyclic, expected="INPUT_NOT_JSON")
    deep = 0
    for _ in range(18):
        deep = [deep]
    sample(deep, expected="INPUT_CAP_EXCEEDED")


def test_roster_bounds_and_duplicates():
    data = request()
    data["roster"]["workers"] = [identity(200)] * 64
    sample(data, expected="INPUT_CAP_EXCEEDED")
    data["roster"]["workers"] = [identity(200)] * 2
    sample(data, expected="DUPLICATE_IDENTITY")


def test_total_input_string_budget():
    sample(["x" * 65536] * 65, expected="INPUT_CAP_EXCEEDED")


def test_snapshot_before_callbacks_and_detached_results():
    data = request(cgroup=True)
    before = copy.deepcopy(data)
    f = Fixture()
    def mutating(path, limit):
        data["config"]["max_bytes"] = 1
        data["roster"]["workers"].clear()
        data["frame_rosters"][0].clear()
        data["cgroup"]["baseline"]["events"]["low"] = 999
        return f.read(path, limit)
    result = reader.RealProcfsReader(mutating, f.clock, f.cgroup).sample(data)
    expected = sample(before)
    assert result == expected
    result["frames"][0]["processes"][0]["identity"]["pid"] = 999
    assert result["roster"]["parent"]["pid"] == 100
    assert before["roster"]["parent"]["pid"] == 100
    assert sample(before) == expected


def test_source_hash_is_explicit_caller_assertion():
    data = request()
    data["reader_source_sha256"] = "a" * 64
    r = sample(data)
    assert r["reader_source_sha256"] == "a" * 64
    assert r["reader_source_hash_provenance"] == "CALLER_ASSERTED_ONLY"


def test_no_reader_or_clock_fallback():
    r = reader.RealProcfsReader().sample(request())
    assert "READER_NOT_CONFIGURED" in codes(r) and not r["frames"]
    r = reader.RealProcfsReader(Fixture().read).sample(request())
    assert "CLOCK_NOT_CONFIGURED" in codes(r) and not r["frames"]


def test_import_and_constructor_inertness(monkeypatch):
    source = MODULE_PATH.read_text()
    tree = ast.parse(source)
    assert {alias.name for n in tree.body if isinstance(n, ast.Import) for alias in n.names} == {"hashlib", "json", "re"}
    assert not any(isinstance(n, ast.ImportFrom) for n in ast.walk(tree))
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            assert not any(isinstance(n, ast.Call) for n in ast.walk(node))
    compiled = compile(source, str(MODULE_PATH), "exec")
    original_import = builtins.__import__
    def blocked(*args, **kwargs):
        raise AssertionError("import/constructor must be inert")
    def restricted(name, *args, **kwargs):
        assert name in ("hashlib", "json", "re")
        return original_import(name, *args, **kwargs)
    with monkeypatch.context() as patch:
        for obj, names in ((builtins, ("open",)), (io, ("open",)),
                           (os, ("open", "read", "stat", "listdir", "scandir", "readlink", "getpid", "fork")),
                           (Path, ("open", "read_bytes", "read_text", "iterdir", "resolve")),
                           (time, ("time", "time_ns", "monotonic", "monotonic_ns", "sleep")),
                           (subprocess, ("Popen", "run")), (socket, ("socket", "create_connection"))):
            for name in names:
                if hasattr(obj, name):
                    patch.setattr(obj, name, blocked)
        patch.setattr(builtins, "__import__", restricted)
        namespace = {}
        exec(compiled, namespace)
        namespace["RealProcfsReader"](blocked, blocked, blocked)
        namespace["RealProcfsReader"]()


def test_old_contracts_reject_new_envelope():
    r = d2a.ProcfsProvider().sample(sample())
    assert r["outcome"] != d2a.SUCCESS
    r = d2a.ProcfsProvider().sample({"schema": d2a.SCHEMA, "source_kind": "REAL_PROCFS", "config": {},
                                  "roster": {}, "frame_count": 1, "cgroup": None})
    assert "REAL_SOURCE_NOT_AUTHORIZED" in (r["invalid_reason_codes"] + r["incomplete_reason_codes"])
    r = d1.assess_injected_capture(sample())
    assert r["outcome"] == d1.INVALID_CAPTURE
    assert "SCHEMA_VERSION_MISMATCH" in r["invalid_reason_codes"]


def test_source_has_no_qualification_routes_or_live_dependencies():
    source = MODULE_PATH.read_text()
    for token in ("PROCESS_RSS_SAMPLE_COMPLETE", "OBSERVATION_COMPLETE", "FAKE_PROVIDER_SAMPLE_CONSISTENT",
                  "FAKE_FIXTURE", "LOCAL_COLLECTOR_RECORDED", "import os", "import time", "open(",
                  "assess_injected_capture", "engine.", "shading."):
        assert token not in source
    for node in ast.walk(ast.parse(Path(__file__).read_text())):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "pytest":
            assert node.attr not in ("skip", "xfail")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [node.module] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
            assert not any(name and name.split(".")[0] in ("engine", "shading") for name in names)
