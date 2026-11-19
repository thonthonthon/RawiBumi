"""Artificial strings and clocks only. The orchestrator executes this suite."""

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

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_procfs_provider as provider
from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_sampler as d1

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_procfs_provider.py"
BOOT = "11111111-2222-3333-4444-555555555555"


def request(workers=False, frames=1, smaps=False, cgroup=False):
    data = {"schema": provider.SCHEMA, "source_kind": "FAKE_FIXTURE", "frame_count": frames,
            "config": {"clock_ticks_per_second": 100, "boot_id": BOOT, "pid_namespace_id": "pidns:77",
                       "host_id": "fixture-host", "max_read_skew_ns": 1000,
                       "smaps_rollup_policy": "OPTIONAL_DIAGNOSTIC" if smaps else "NOT_SAMPLED"},
            "roster": {"parent": {"pid": 100, "ppid": 1, "starttime_ticks": 10, "boot_id": BOOT},
                       "workers": [{"pid": 200, "parent_pid": 100, "starttime_ticks": 20,
                                    "boot_id": BOOT, "role": "producer"}] if workers else []}, "cgroup": None}
    if cgroup:
        data["cgroup"] = {"token": "fixtures/owned", "controller_id": "cgv2:fixture",
                          "membership": [100, 200] if workers else [100], "membership_provenance": "fixture-registry",
                          "baseline": {"memory_current_bytes": 10000, "memory_peak_bytes": 20000,
                                       "events": {"low": 0, "high": 0, "max": 0, "oom": 0, "oom_kill": 0},
                                       "provenance": "fixture-baseline", "boot_id": BOOT,
                                       "pid_namespace_id": "pidns:77", "observed_ns": 0}}
    return data


def stat(pid=100, ppid=1, ticks=10, state="R", comm="fixture (with) ) (spaces)"):
    return "%d (%s) %s\n" % (pid, comm, " ".join([state, str(ppid)] + ["0"] * 17 + [str(ticks)]))


def full_stat(overrides=None):
    # Artificial 52-field Linux layout, including the unsigned RLIM_INFINITY.
    fields = {number: "0" for number in range(4, 53)}
    fields.update({4: "1", 5: "100", 6: "100", 8: "-1", 9: "4194304", 10: "25",
                   12: "1", 14: "10", 15: "5", 18: "-5", 19: "-10", 20: "1",
                   22: "10", 23: "1048576", 24: "5", 25: "18446744073709551615",
                   26: "4194304", 27: "4198400", 28: "140737488347136", 38: "17",
                   45: "6291456", 46: "6295552", 47: "6300000", 48: "140737488348000",
                   49: "140737488348010", 50: "140737488348010", 51: "140737488348020"})
    fields.update(overrides or {})
    return "100 (fixture (with) ) (spaces)) R " + " ".join(fields[n] for n in range(4, 53)) + "\n"


def status(pid=100, ppid=1, state="S", rss=5, hwm=20):
    # VmSwap is deliberately absent: it is not mandatory in the D2-A contract.
    return "Name: fixture\nPid: %d\nPPid: %d\nState: %s (fixture)\nVmRSS: %d kB\nVmHWM: %d kB\n" % (
        pid, ppid, state, rss, hwm)


def dead_status(pid=100, ppid=1, state="Z"):
    # A process with no mm has no VmRSS, VmHWM or other Vm* lines.
    return "Name: fixture\nState: %s (zombie)\nPid: %d\nPPid: %d\nThreads: 1\n" % (state, pid, ppid)


class Fixture:
    def __init__(self, overrides=None, clock=None):
        self.overrides = overrides or {}
        self.clock_values = iter(clock) if clock is not None else None
        self.calls = []
        self.tick_value = 0
        self.counts = {}

    def clock(self):
        self.calls.append(("clock",))
        if self.clock_values is not None:
            value = next(self.clock_values)
            if isinstance(value, Exception):
                raise value
            return value
        value = self.tick_value
        self.tick_value += 1
        return value

    def read(self, kind, target, max_bytes):
        self.calls.append(("read", kind, target, max_bytes))
        key = (kind, target)
        index = self.counts.get(key, 0)
        self.counts[key] = index + 1
        if key in self.overrides:
            value = self.overrides[key]
            if type(value) is list:
                value = value[min(index, len(value) - 1)]
            if isinstance(value, BaseException):
                raise value
            return value
        if kind == "stat":
            return stat(target, 1 if target == 100 else 100, 10 if target == 100 else 20)
        if kind == "status":
            return status(target, 1 if target == 100 else 100)
        return {"smaps_rollup": "Rss: 9 kB\nSwap: 0 kB\n", "memory.current": "30000\n",
                "memory.peak": "40000\n", "memory.events": "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\nfuture 7\n"}[kind]


def codes(result):
    return set(result["invalid_reason_codes"]) | set(result["incomplete_reason_codes"])


def seal(result):
    payload = {k: v for k, v in result.items() if k != "integrity"}
    raw = (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n").encode()
    assert result["integrity"] == {"algorithm": "sha256", "scope": "canonical result excluding integrity",
                                   "sha256": hashlib.sha256(raw).hexdigest()}


def sample(data=None, fixture=None, expected=None):
    fixture = fixture or Fixture()
    result = provider.ProcfsProvider(fixture.read, fixture.clock, fixture.read).sample(data if data is not None else request())
    seal(result)
    assert result["production_memory_qualification"] == "INCONCLUSIVE"
    assert result["production_chronological_peak"] == "NOT_OBSERVED"
    assert result["production_workload_measured"] is False
    assert result["holder_release"] == "NOT_ESTABLISHED"
    assert result["origin_attestation"] == "UNVERIFIED"
    assert result["source_kind"] == "FAKE_FIXTURE"
    assert result["worker_absence_proven"] is False
    assert result["atomic_snapshot"] is False
    assert result["bound_claim"] == "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK"
    assert result["starttime_alignment"] == "NOT_CALIBRATED"
    if expected:
        assert expected in codes(result)
        assert result["outcome"] != provider.SUCCESS
        for frame in result["frames"]:
            if frame["reason_codes"]:
                assert all(p["status"] != provider.SUCCESS and p["vmrss_bytes"] is None
                           for p in frame["processes"])
    return result


@pytest.mark.parametrize("workers,smaps,cgroup", [(False, False, False), (True, False, False),
                                                   (False, True, False), (True, True, True)])
def test_valid_samples_and_exact_callback_order(workers, smaps, cgroup):
    fixture = Fixture()
    result = sample(request(workers=workers, smaps=smaps, cgroup=cgroup), fixture)
    assert result["outcome"] == provider.SUCCESS
    assert result["reasons"] == []
    frame = result["frames"][0]
    expected_reads = []
    for pid in ([100, 200] if workers else [100]):
        for kind in (["stat", "status", "smaps_rollup", "stat"] if smaps else ["stat", "status", "stat"]):
            expected_reads.append(("read", kind, pid, provider.MAX_TEXT_BYTES))
    if cgroup:
        expected_reads += [("read", k, "fixtures/owned", provider.MAX_TEXT_BYTES)
                           for k in ("memory.current", "memory.peak", "memory.events")]
    expected_calls = [call for read in expected_reads for call in (("clock",), read, ("clock",))]
    assert fixture.calls == expected_calls
    assert frame["first_read_start_ns"] == 0
    assert frame["last_read_end_ns"] == 2 * len(expected_reads) - 1
    assert frame["read_skew_ns"] == frame["last_read_end_ns"]
    assert result["first_read_start_ns"] == frame["first_read_start_ns"]
    assert result["last_read_end_ns"] == frame["last_read_end_ns"]
    assert frame["read_window_complete"] is True
    assert result["worker_coverage"] == ("REGISTERED_ROSTER_OBSERVED" if workers else "NOT_ESTABLISHED")
    for process in frame["processes"]:
        assert process["vmrss_bytes"] == 5120
        assert process["vmhwm_bytes"] == 20480
        assert process["smaps_rollup"] == ({"Rss": 9216, "Swap": 0} if smaps else None)
        for read in process["reads"]:
            assert read["status"] == "OK"
            assert len(read["sha256"]) == 64 and read["byte_length"] > 0
    raw = stat().encode()
    assert frame["processes"][0]["reads"][0]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert frame["processes"][0]["reads"][0]["byte_length"] == len(raw)
    assert "Name: fixture" not in provider.canonical_json(result)
    assert "comm" not in frame["processes"][0]
    assert "sampled_max_rss_bytes" not in provider.canonical_json(result)


@pytest.mark.parametrize("comm", ["a b", "(a)", ") (", "nested ((x)) ) ( worker", "plain"])
def test_stat_final_parenthesis(comm):
    assert sample(fixture=Fixture({("stat", 100): stat(comm=comm)}))["outcome"] == provider.SUCCESS


def test_full_linux_stat_with_unsigned_rsslim_and_signed_scheduling_fields():
    text = full_stat()
    assert len(text.rsplit(")", 1)[1].split()) == 50  # Fields 3 through 52.
    result = sample(fixture=Fixture({("stat", 100): text}))
    assert result["outcome"] == provider.SUCCESS
    process = result["frames"][0]["processes"][0]
    assert process["vmrss_bytes"] == 5120
    assert process["identity"]["starttime_ticks"] == 10
    assert all(read["status"] == "OK" for read in process["reads"])


@pytest.mark.parametrize("field,value", [
    (25, "18446744073709551615"), (26, "18446744073709551615"),
    (8, "-9223372036854775808"), (18, "-9223372036854775808"),
    (19, "9223372036854775807"), (52, "-9223372036854775808"),
])
def test_stat_u64_and_i64_endpoints_are_accepted(field, value):
    assert sample(fixture=Fixture({("stat", 100): full_stat({field: value})}))["outcome"] == provider.SUCCESS


@pytest.mark.parametrize("field,value", [
    (25, "18446744073709551616"), (25, "100000000000000000000"), (25, "9" * 5000),
    (25, "-1"), (18, "9223372036854775808"), (18, "-9223372036854775809"),
    (19, "18446744073709551615"), (20, "9223372036854775808"),
    (52, "-9223372036854775809"), (22, "9223372036854775808"),
    (4, "9223372036854775808"),
])
def test_stat_overflow_and_consumed_identity_bounds_fail_closed(field, value):
    sample(fixture=Fixture({("stat", 100): full_stat({field: value})}), expected="RAW_TEXT_MALFORMED")


@pytest.mark.parametrize("texts,reason", [
    ([stat(ticks=11), stat()], "PID_REUSE_OR_IDENTITY_RACE"),
    ([stat(), stat(ticks=11)], "PID_REUSE_OR_IDENTITY_RACE"),
    ([stat(pid=101), stat()], "IDENTITY_CONTRADICTION"),
    ([stat(), stat(ppid=2)], "IDENTITY_CONTRADICTION"),
    (["100 broken R 1\n"], "RAW_TEXT_MALFORMED"),
    (["100 (broken) R 1 0\n"], "MISSING_FIELD"),
])
def test_stat_identity_races_and_malformed(texts, reason):
    sample(fixture=Fixture({("stat", 100): texts}), expected=reason)


@pytest.mark.parametrize("state", ["Z", "X", "x"])
@pytest.mark.parametrize("kind", ["stat", "status"])
def test_dead_process(kind, state):
    text = stat(state=state) if kind == "stat" else status(state=state)
    sample(fixture=Fixture({(kind, 100): text}), expected="PROCESS_NOT_LIVE")


@pytest.mark.parametrize("state", ["Z", "X", "x"])
def test_dead_status_without_vm_fields_is_lifecycle_uncertainty(state):
    result = sample(fixture=Fixture({("status", 100): dead_status(state=state)}), expected="PROCESS_NOT_LIVE")
    assert result["outcome"] == "INCOMPLETE"
    assert "MISSING_FIELD" not in codes(result)
    process = result["frames"][0]["processes"][0]
    assert process["vmrss_bytes"] is None and process["vmhwm_bytes"] is None


def test_dead_status_still_checks_registered_identity():
    result = sample(fixture=Fixture({("status", 100): dead_status(pid=101)}), expected="IDENTITY_CONTRADICTION")
    assert "PROCESS_NOT_LIVE" in codes(result)


@pytest.mark.parametrize("kind", ["stat", "status"])
def test_registered_worker_reparenting_is_not_hidden(kind):
    text = stat(200, 1, 20) if kind == "stat" else status(200, 1)
    sample(request(workers=True), Fixture({(kind, 200): text}), expected="IDENTITY_CONTRADICTION")


@pytest.mark.parametrize("text,reason", [
    (status(pid=101), "IDENTITY_CONTRADICTION"), (status(ppid=2), "IDENTITY_CONTRADICTION"),
    ("bad status\n", "RAW_TEXT_MALFORMED"), (status() + "VmRSS: 5 kB\n", "DUPLICATE_FIELD"),
    (status() + "Name: duplicate\n", "DUPLICATE_FIELD"),
    (status().replace("VmRSS: 5 kB\n", ""), "MISSING_FIELD"),
    (status().replace("VmHWM: 20 kB\n", ""), "MISSING_FIELD"),
    (status().replace("State: S (fixture)\n", ""), "MISSING_FIELD"),
    (status().replace("5 kB", "5 MB"), "RAW_TEXT_MALFORMED"),
    (status().replace("5 kB", "5"), "RAW_TEXT_MALFORMED"),
    (status().replace("5 kB", "-5 kB"), "RAW_TEXT_MALFORMED"),
    (status().replace("5 kB", "５ kB"), "RAW_TEXT_MALFORMED"),
    (status().replace("5 kB", "9" * 5000 + " kB"), "RAW_TEXT_MALFORMED"),
    (status().replace("5 kB", " " * 65 + "5 kB"), "RAW_TEXT_MALFORMED"),
    (status(rss=30), "COUNTER_INCONSISTENT"), (status(state="?"), "RAW_TEXT_MALFORMED"),
    (status().replace("\n", "\r\n"), "RAW_TEXT_MALFORMED"),
    (status().replace("5 kB", "9007199254740992 kB"), "RAW_TEXT_MALFORMED"),
])
def test_status_rejections(text, reason):
    sample(fixture=Fixture({("status", 100): text}), expected=reason)


@pytest.mark.parametrize("kind", ["stat", "status", "smaps_rollup", "memory.current", "memory.peak", "memory.events"])
@pytest.mark.parametrize("text,reason", [("x" * (provider.MAX_TEXT_BYTES + 1), "OVERSIZED"),
                                         ("x", "TRUNCATED"), ("é" * 40000 + "\n", "OVERSIZED")])
def test_read_text_caps_and_truncation(kind, text, reason):
    target = 100 if kind in ("stat", "status", "smaps_rollup") else "fixtures/owned"
    sample(request(smaps=True, cgroup=True), Fixture({(kind, target): text}), expected=reason)


@pytest.mark.parametrize("error,reason", [(PermissionError("secret"), "PERMISSION_DENIED"),
    (FileNotFoundError("secret"), "PROCESS_VANISHED"), (ProcessLookupError("secret"), "PROCESS_VANISHED"),
    (OSError("secret"), "READ_FAILED"), (RuntimeError("secret"), "READER_EXCEPTION")])
@pytest.mark.parametrize("kind", ["stat", "status", "smaps_rollup", "memory.events"])
def test_reader_errors_never_leak_text(kind, error, reason):
    target = "fixtures/owned" if kind == "memory.events" else 100
    result = sample(request(smaps=True, cgroup=True), Fixture({(kind, target): error}), expected=reason)
    assert "secret" not in provider.canonical_json(result)


class TextSubclass(str):
    pass


@pytest.mark.parametrize("value", [b"text", None, 1, True, TextSubclass("text\n"), {}])
def test_exact_reader_return_type(value):
    sample(fixture=Fixture({("status", 100): value}), expected="READER_CONTRACT_VIOLATION")


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_base_exceptions_propagate(error):
    fixture = Fixture({("status", 100): error})
    with pytest.raises(type(error)):
        provider.ProcfsProvider(fixture.read, fixture.clock).sample(request())


def test_clock_ties_and_skew_bound():
    result = sample(fixture=Fixture(clock=[7] * 6))
    assert result["outcome"] == provider.SUCCESS
    assert result["frames"][0]["read_skew_ns"] == 0
    data = request()
    data["config"]["max_read_skew_ns"] = 5
    assert sample(data)["outcome"] == provider.SUCCESS
    data["config"]["max_read_skew_ns"] = 4
    result = sample(data, expected="READ_SKEW_EXCEEDED")
    assert result["outcome"] == "INCOMPLETE"
    assert result["frames"][0]["read_skew_ns"] == 5


@pytest.mark.parametrize("bad,reason", [(True, "CLOCK_FAILURE"), (1.0, "CLOCK_FAILURE"), (-1, "CLOCK_FAILURE"),
    (2**63, "CLOCK_FAILURE"), (RuntimeError("secret-clock"), "CLOCK_FAILURE"), (0, "CLOCK_NON_MONOTONIC")])
@pytest.mark.parametrize("position", [1, 3, 5])
def test_clock_failures_invalidate_entire_frame(bad, reason, position):
    values = [1, 2, 3, 4, 5, 6]
    values[position] = bad
    result = sample(request(workers=True, frames=2), Fixture(clock=values), expected=reason)
    assert result["outcome"] == "INVALID"
    assert "secret-clock" not in provider.canonical_json(result)
    assert len(result["frames"]) == 1
    assert all(p["vmrss_bytes"] is None for p in result["frames"][0]["processes"])


@pytest.mark.parametrize("position", [0, 2, 4])
@pytest.mark.parametrize("bad", [False, None, -1, 1.0, 2**63, RuntimeError("secret")])
def test_clock_failure_before_read_never_calls_that_reader(position, bad):
    values = list(range(6))
    values[position] = bad
    fixture = Fixture(clock=values)
    result = sample(fixture=fixture, expected="CLOCK_FAILURE")
    assert len([call for call in fixture.calls if call[0] == "read"]) == position // 2
    assert result["frames"][0]["read_window_complete"] is False


def test_monotonicity_is_checked_across_frames():
    result = sample(request(frames=2), Fixture(clock=list(range(6)) + [0]), expected="CLOCK_NON_MONOTONIC")
    assert result["frames"][0]["status"] == provider.SUCCESS
    assert result["frames"][1]["status"] == "INVALID"


def test_reader_and_clock_errors_are_both_retained():
    sample(fixture=Fixture({("stat", 100): PermissionError("secret")}, clock=[1, 0]), expected="PERMISSION_DENIED")
    result = sample(fixture=Fixture({("stat", 100): PermissionError("secret")}, clock=[1, 0]))
    assert {"PERMISSION_DENIED", "CLOCK_NON_MONOTONIC"} <= codes(result)


@pytest.mark.parametrize("error", [FileNotFoundError(), ProcessLookupError()])
def test_worker_not_observed_is_coverage_uncertainty(error):
    result = sample(request(workers=True, frames=2), Fixture({("stat", 200): error}), expected="PROCESS_VANISHED")
    assert result["worker_coverage"] == "UNCERTAIN"
    assert result["unregistered_worker_coverage"] == "NOT_ESTABLISHED"


def test_empty_worker_roster_does_not_establish_worker_absence():
    result = sample(request(frames=2))
    assert result["worker_coverage"] == "NOT_ESTABLISHED"
    assert result["unregistered_worker_coverage"] == "NOT_ESTABLISHED"
    assert "NO_WORKERS" not in provider.canonical_json(result)


@pytest.mark.parametrize("initially_present", [True, False])
@pytest.mark.parametrize("failure", ["vanished", "zombie"])
def test_registered_worker_departure_and_late_arrival_preserve_uncertainty(initially_present, failure):
    live_stat, live_status = stat(200, 100, 20), status(200, 100)
    if failure == "vanished":
        failed_stat = failed_status = FileNotFoundError()
        reason = "PROCESS_VANISHED"
    else:
        failed_stat, failed_status = stat(200, 100, 20, state="Z"), dead_status(200, 100)
        reason = "PROCESS_NOT_LIVE"
    stats = [live_stat, live_stat, failed_stat, failed_stat]
    statuses = [live_status, failed_status]
    if not initially_present:
        stats.reverse()
        statuses.reverse()
    fixture = Fixture({("stat", 200): stats, ("status", 200): statuses})
    result = sample(request(workers=True, frames=2), fixture, expected=reason)
    assert result["outcome"] == "INCOMPLETE"
    assert result["worker_coverage"] == "UNCERTAIN"
    assert result["worker_absence_proven"] is False
    assert result["unregistered_worker_coverage"] == "NOT_ESTABLISHED"
    observed = result["frames"][0 if initially_present else 1]
    missing = result["frames"][1 if initially_present else 0]
    assert observed["status"] == provider.SUCCESS
    assert [p["vmrss_bytes"] for p in observed["processes"]] == [5120, 5120]
    assert missing["status"] == "INCOMPLETE"
    assert all(p["vmrss_bytes"] is None for p in missing["processes"])
    assert reason in missing["processes"][1]["reason_codes"]


def test_cgroup_and_smaps_are_separate_from_rss_and_baselines():
    plain = sample(request(workers=True))
    enriched = sample(request(workers=True, cgroup=True, smaps=True))
    assert [p["vmrss_bytes"] for p in plain["frames"][0]["processes"]] == [5120, 5120]
    assert [p["vmrss_bytes"] for p in enriched["frames"][0]["processes"]] == [5120, 5120]
    cg = enriched["frames"][0]["cgroup"]
    assert cg["memory_current_bytes"] == 30000
    assert cg["memory_peak_bytes"] == 40000
    assert cg["events"]["future"] == 7
    assert cg["baseline"] == request(cgroup=True)["cgroup"]["baseline"]
    assert cg["membership_verification"] == "CALLER_ASSERTED_ONLY"


@pytest.mark.parametrize("kind,text,reason", [
    ("memory.current", "-1\n", "RAW_TEXT_MALFORMED"), ("memory.peak", "1 kB\n", "RAW_TEXT_MALFORMED"),
    ("memory.current", "9" * 5000 + "\n", "RAW_TEXT_MALFORMED"),
    ("memory.events", "low 0\n", "MISSING_FIELD"),
    ("memory.events", "low 0\nlow 0\n", "DUPLICATE_FIELD"),
    ("memory.peak", "100\n", "COUNTER_INCONSISTENT"),
    ("memory.events", FileNotFoundError(), "PROCESS_VANISHED"),
])
def test_bad_optional_cgroup_retains_failed_process_records(kind, text, reason):
    result = sample(request(cgroup=True), Fixture({(kind, "fixtures/owned"): text}), expected=reason)
    assert len(result["frames"][0]["processes"]) == 1
    assert result["frames"][0]["cgroup"]["status"] != provider.SUCCESS


def test_cgroup_event_monotonicity_uses_fixed_identity_and_baseline():
    data = request(cgroup=True)
    data["cgroup"]["baseline"]["events"]["high"] = 1
    sample(data, expected="COUNTER_INCONSISTENT")
    fixture = Fixture({("memory.events", "fixtures/owned"): [
        "low 0\nhigh 1\nmax 0\noom 0\noom_kill 0\n", "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n"]})
    result = sample(request(cgroup=True, frames=2), fixture, expected="COUNTER_INCONSISTENT")
    assert result["frames"][0]["status"] == provider.SUCCESS
    assert result["frames"][1]["status"] == "INVALID"


@pytest.mark.parametrize("field,value", [("boot_id", "other"), ("pid_namespace_id", "other"),
    ("memory_current_bytes", True), ("memory_peak_bytes", -1), ("observed_ns", False),
    ("events", {"low": 0}), ("provenance", "../forged")])
def test_cgroup_baseline_validation_precedes_reading(field, value):
    data = request(cgroup=True)
    data["cgroup"]["baseline"][field] = value
    fixture = Fixture()
    sample(data, fixture, expected="CGROUP_CONFIGURATION_INVALID")
    assert fixture.calls == []


def test_baseline_cannot_be_from_after_the_cgroup_observation():
    data = request(cgroup=True)
    data["cgroup"]["baseline"]["observed_ns"] = 999
    sample(data, expected="BASELINE_CHRONOLOGY_INVALID")


@pytest.mark.parametrize("text,reason", [("Rss: 5 MB\nSwap: 0 kB\n", "RAW_TEXT_MALFORMED"),
    ("Rss: 5 kB\n", "MISSING_FIELD"), ("Rss: 5 kB\nRss: 5 kB\nSwap: 0 kB\n", "DUPLICATE_FIELD")])
def test_optional_smaps_malformed_is_never_promoted(text, reason):
    sample(request(smaps=True), Fixture({("smaps_rollup", 100): text}), expected=reason)


def test_smaps_header_is_parsed_without_exposing_addresses():
    text = "00000000-00001000 ---p 00000000 00:00 0 [rollup]\nRss: 9 kB\nSwap: 0 kB\n"
    result = sample(request(smaps=True), Fixture({("smaps_rollup", 100): text}))
    assert result["outcome"] == provider.SUCCESS
    assert result["frames"][0]["processes"][0]["smaps_rollup"] == {"Rss": 9216, "Swap": 0}
    assert "00001000" not in provider.canonical_json(result)


def test_sequential_cgroup_current_can_exceed_later_peak_without_atomic_claim():
    result = sample(request(cgroup=True), Fixture({("memory.current", "fixtures/owned"): "90000\n"}))
    assert result["outcome"] == provider.SUCCESS
    assert result["atomic_snapshot"] is False


def set_path(data, path, value):
    current = data
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value


@pytest.mark.parametrize("path", [("roster", "parent", "pid"), ("roster", "parent", "ppid"),
    ("roster", "parent", "starttime_ticks"), ("config", "clock_ticks_per_second"),
    ("config", "max_read_skew_ns"), ("frame_count",)])
@pytest.mark.parametrize("value", [True, False, -1, 2**63, 1.5, float("nan"), float("inf"), "1/../self", "/proc/1", None, {}, []])
def test_numeric_input_validation_before_any_callback(path, value):
    data = request()
    set_path(data, path, value)
    fixture = Fixture()
    result = sample(data, fixture)
    assert result["outcome"] == "INVALID"
    assert fixture.calls == []


@pytest.mark.parametrize("path,value,reason", [
    (("source_kind",), "REAL_PROCFS", "REAL_SOURCE_NOT_AUTHORIZED"),
    (("source_kind",), "anything", "SOURCE_KIND_NOT_ACCEPTED"),
    (("schema",), d1.SCHEMA, "SCHEMA_VERSION_MISMATCH"),
    (("origin_attestation",), "VERIFIED", "UNKNOWN_FIELD"),
    (("production_workload_measured",), True, "UNKNOWN_FIELD"),
    (("config", "boot_id"), "boot", "CONFIGURATION_INVALID"),
    (("config", "pid_namespace_id"), "../self", "CONFIGURATION_INVALID"),
    (("config", "host_id"), "host/1", "CONFIGURATION_INVALID"),
    (("config", "host_id"), "x" * 97, "CONFIGURATION_INVALID"),
    (("config", "clock_ticks_per_second"), 0, "CONFIGURATION_INVALID"),
    (("config", "clock_ticks_per_second"), 1000001, "CONFIGURATION_INVALID"),
    (("config", "smaps_rollup_policy"), "REQUIRED", "CONFIGURATION_INVALID"),
    (("roster", "parent", "boot_id"), "00000000-2222-3333-4444-555555555555", "BOOT_ID_MISMATCH"),
    (("roster", "workers", 0, "parent_pid"), 1, "IDENTITY_CONTRADICTION"),
    (("roster", "workers", 0, "pid"), 100, "DUPLICATE_IDENTITY"),
    (("roster", "workers", 0, "boot_id"), "other", "BOOT_ID_MISMATCH"),
    (("roster", "parent", "ppid"), 200, "IDENTITY_CONTRADICTION"),
    (("frame_count",), provider.MAX_FRAMES + 1, "INPUT_CAP_EXCEEDED"),
])
def test_closed_schema_and_identity_input(path, value, reason):
    data = request(workers=True)
    set_path(data, path, value)
    fixture = Fixture()
    sample(data, fixture, expected=reason)
    assert fixture.calls == []


@pytest.mark.parametrize("token", ["../x", ".", "..", "/absolute", "a//b", "a/../b", "a/./b", "a/", "a\\b", "a\x00b", "x" * 193])
def test_cgroup_token_cannot_traverse(token):
    data = request(cgroup=True)
    data["cgroup"]["token"] = token
    fixture = Fixture()
    sample(data, fixture, expected="CGROUP_CONFIGURATION_INVALID")
    assert fixture.calls == []


@pytest.mark.parametrize("field,value", [("membership", [True]), ("membership", [100, 100]),
    ("membership", []), ("controller_id", "/host"), ("baseline", {}), ("baseline", None)])
def test_cgroup_nested_validation(field, value):
    data = request(cgroup=True)
    data["cgroup"][field] = value
    fixture = Fixture()
    assert sample(data, fixture)["outcome"] == "INVALID"
    assert fixture.calls == []


@pytest.mark.parametrize("root", [None, True, [], "request", 1])
def test_non_object_input(root):
    fixture = Fixture()
    result = provider.ProcfsProvider(fixture.read, fixture.clock).sample(root)
    assert result["outcome"] == "INVALID"
    assert "SCHEMA_INVALID" in codes(result)
    assert fixture.calls == []


def test_input_caps_cycles_and_nested_objects():
    fixture = Fixture()
    data = request()
    data["extra"] = "x" * (provider.MAX_TEXT_BYTES + 1)
    sample(data, fixture, expected="INPUT_CAP_EXCEEDED")
    data["extra"] = [None] * provider.MAX_NODES
    sample(data, fixture, expected="INPUT_CAP_EXCEEDED")
    data["extra"] = []
    child = data["extra"]
    for _ in range(provider.MAX_DEPTH + 1):
        child.append([])
        child = child[0]
    sample(data, fixture, expected="INPUT_CAP_EXCEEDED")
    data["extra"] = data
    sample(data, fixture, expected="INPUT_NOT_JSON")
    data = request()
    data["roster"]["workers"] = [dict(pid=i + 200, parent_pid=100, starttime_ticks=20, boot_id=BOOT, role="worker")
                                  for i in range(provider.MAX_PROCESSES)]
    sample(data, fixture, expected="INPUT_CAP_EXCEEDED")
    assert fixture.calls == []


def test_total_read_budget_stops_without_partial_success(monkeypatch):
    # Lower the budget so this exercises exactly the production guard cheaply.
    monkeypatch.setattr(provider, "MAX_TOTAL_TEXT_BYTES", 4000)
    text = status() + "NameExtra: " + "x" * 3000 + "\n"
    result = sample(request(frames=3), Fixture({("status", 100): text}), expected="TOTAL_TEXT_CAP_EXCEEDED")
    assert len(result["frames"]) == 2
    assert result["frames"][1]["processes"][0]["vmrss_bytes"] is None


def test_determinism_input_snapshot_and_detached_results():
    data = request(workers=True, cgroup=True, frames=2)
    original = copy.deepcopy(data)
    first = sample(data)
    assert data == original
    assert first == sample(data)
    fixture = Fixture()

    def mutating_reader(kind, target, max_bytes):
        data["roster"]["parent"]["pid"] = 999
        data["cgroup"]["baseline"]["events"]["high"] = 999
        return fixture.read(kind, target, max_bytes)

    changed_during_read = provider.ProcfsProvider(mutating_reader, fixture.clock, mutating_reader).sample(data)
    assert changed_during_read == first
    first["frames"][0]["processes"][0]["identity"]["pid"] = 777
    assert sample(original)["frames"][0]["processes"][0]["identity"]["pid"] == 100
    first["frames"][0]["cgroup"]["baseline"]["events"]["high"] = 99
    assert first["frames"][1]["cgroup"]["baseline"]["events"]["high"] == 0


def test_unconfigured_provider_never_falls_back():
    result = provider.ProcfsProvider().sample(request())
    assert result["outcome"] == "INCOMPLETE"
    assert "READER_NOT_CONFIGURED" in codes(result)
    fixture = Fixture()
    result = provider.ProcfsProvider(read_proc=fixture.read).sample(request())
    assert "CLOCK_NOT_CONFIGURED" in codes(result)
    assert fixture.calls == []
    fixture = Fixture()
    result = provider.ProcfsProvider(fixture.read, fixture.clock).sample(request(cgroup=True))
    assert "CGROUP_READER_NOT_CONFIGURED" in codes(result)
    assert result["frames"][0]["processes"][0]["status"] != provider.SUCCESS


def test_import_construction_and_sampling_have_no_live_api(monkeypatch):
    source = MODULE_PATH.read_text()
    tree = ast.parse(source)
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all(isinstance(node, ast.Import) for node in imports)
    assert {alias.name for node in imports for alias in node.names} == {"hashlib", "json", "re"}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            expressions = list(node.decorator_list)
            if isinstance(node, ast.FunctionDef):
                expressions += node.args.defaults + [d for d in node.args.kw_defaults if d is not None]
            else:
                assert all(isinstance(n, ast.FunctionDef) or
                           (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and
                            isinstance(n.value.value, str)) for n in node.body)
        else:
            expressions = [node]
        assert not any(isinstance(child, ast.Call) for expr in expressions for child in ast.walk(expr))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            assert not any(isinstance(d, (ast.Call, ast.Attribute, ast.Name)) for d in node.args.defaults)
    assert "assess_injected_capture" not in source
    assert "INJECTED_SYNTHETIC" not in source
    assert "PROCESS_RSS_SAMPLE_COMPLETE" not in source
    compiled = compile(source, str(MODULE_PATH), "exec")
    expected = sample()
    original_import = builtins.__import__
    forbidden_calls = []

    def forbidden(*args, **kwargs):
        forbidden_calls.append(True)
        raise AssertionError("live API called")

    def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        assert name in ("hashlib", "json", "re")
        return original_import(name, globals, locals, fromlist, level)

    with monkeypatch.context() as guard:
        for obj, names in (
            (builtins, ("open",)), (io, ("open",)),
            (os, ("open", "stat", "listdir", "scandir", "walk", "getpid", "getppid", "sysconf", "readlink", "fork", "system")),
            (Path, ("open", "read_text", "read_bytes", "iterdir")), (subprocess, ("Popen", "run", "check_output")),
            (socket, ("socket",)), (time, ("monotonic", "monotonic_ns", "perf_counter", "time", "time_ns")),
        ):
            for name in names:
                if hasattr(obj, name):
                    guard.setattr(obj, name, forbidden)
        # Install last: pytest's patch setup itself imports inspect.
        guard.setattr(builtins, "__import__", restricted_import)
        namespace = {}
        exec(compiled, namespace)
        empty = namespace["ProcfsProvider"]()
        assert empty.sample(request())["outcome"] == "INCOMPLETE"
        fixture = Fixture()
        instance = namespace["ProcfsProvider"](fixture.read, fixture.clock, fixture.read)
        assert fixture.calls == []
        actual = instance.sample(request())
    assert forbidden_calls == []
    assert actual == expected


def test_d1_contract_stays_separate_and_rejects_real_label_and_new_envelope():
    assert d1.SCHEMA == "rawibumi.process-rss-capture.f2b4.v1"
    assert provider.SCHEMA != d1.SCHEMA
    result = d1.assess_injected_capture({"schema": d1.SCHEMA, "source_type": "REAL_PROCFS"})
    assert result["outcome"] == "INVALID_CAPTURE"
    assert "SOURCE_TYPE_NOT_ACCEPTED" in result["invalid_reason_codes"]
    result = d1.assess_injected_capture(sample())
    assert result["outcome"] == "INVALID_CAPTURE"
    assert "SCHEMA_VERSION_MISMATCH" in result["invalid_reason_codes"]


def test_suite_has_no_skip_or_production_imports():
    tree = ast.parse(Path(__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "pytest":
            assert node.attr not in ("skip", "xfail")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [node.module] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names]
            assert all(not name.startswith(("engine", "shading")) for name in names)
