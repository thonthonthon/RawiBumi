"""Synthetic-only regression contract. Execution belongs to the orchestrator."""

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

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_sampler as sampler


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_sampler.py"
PARENT = {"pid": 100, "starttime_ticks": 10, "boot_id": "boot"}


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False, ensure_ascii=True) + "\n").encode()


def identity(pid=100, ticks=10):
    return {"pid": pid, "starttime_ticks": ticks, "boot_id": "boot"}


def fileread(text, start, result="OK"):
    return {"result": result, "start_ns": start, "end_ns": start + 1,
            "error" if result == "FAILED" else "text": text}


def stat(ident, ppid=1, state="R"):
    return "%d (synthetic (worker)) %s\n" % (
        ident["pid"], " ".join([state, str(ppid)] + ["0"] * 17 + [str(ident["starttime_ticks"])]))


def status(ident, rss=5, hwm=20, swap=0, ppid=1):
    return "Pid: %d\nPPid: %d\nVmRSS: %d kB\nVmHWM: %d kB\nVmSwap: %d kB\n" % (ident["pid"], ppid, rss, hwm, swap)


def process_read(ident, start, rss=5, hwm=20, ppid=1, smaps=False):
    return {"identity": dict(ident), "stat_before": fileread(stat(ident, ppid), start),
            "status": fileread(status(ident, rss, hwm, ppid=ppid), start + 2),
            "smaps_rollup": fileread("Rss: 9 kB\nSwap: 0 kB\n", start + 4) if smaps else None,
            "stat_after": fileread(stat(ident, ppid), start + 6)}


def cgroup(identities, start):
    return {"clock_domain_id": "domain", "cgroup_version": 2, "cgroup_path": "/synthetic",
            "memory_events": fileread("low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n", start),
            "cgroup_procs": fileread("".join(str(i["pid"]) + "\n" for i in identities), start + 2),
            "memory_current": fileread("1000000\n", start + 4), "memory_peak": fileread("9000000\n", start + 6)}


def frame(index, start, identities, rss=5, smaps=False):
    return {"frame_sequence": index, "clock_domain_id": "domain", "frame_kind": "BOUNDED_SEQUENTIAL_RSS_FRAME",
            "frame_start_ns": start, "frame_evaluation_ns": start + 40, "frame_end_ns": start + 80,
            "expected_live": copy.deepcopy(identities),
            "process_reads": [process_read(i, start + j * 10, rss=rss, ppid=1 if i == PARENT else 100, smaps=smaps)
                              for j, i in enumerate(identities)],
            "cgroup": cgroup(identities, start + len(identities) * 10)}


def event(time_ns, kind, ident=PARENT, phase="setup"):
    value = {"sequence": 0, "time_ns": time_ns, "clock_domain_id": "domain", "kind": kind, "identity": dict(ident)}
    if kind != "EXIT":
        value["phase"] = phase
    return value


def finish_fixture(data):
    for i, e in enumerate(data["events"]):
        e["sequence"] = i
    data["capture"]["declared_event_count"] = len(data["events"])
    data["capture"]["declared_frame_count"] = len(data["frames"])
    return data


def inline():
    phases = list(sampler.PHASES)
    return finish_fixture({
        "schema": sampler.SCHEMA, "source_type": "INJECTED_SYNTHETIC", "run_id": "synthetic-run",
        "clock": {"kind": "CLOCK_MONOTONIC", "unit": "ns", "domain_id": "domain", "host_id": "host",
                  "boot_id": "boot", "pid_namespace_id": "namespace"},
        "source_provenance": {"origin_attestation": "UNVERIFIED", "kernel_release": "synthetic",
                              "os_description": "synthetic", "workload_id": "workload", "input_id": "input",
                              "configuration_id": "config", "source_tree_fingerprint": "source",
                              "sampler_code_version": "v1", "registration_protocol": "synthetic-registry",
                              "requested_worker_counts": {"producer": 999, "attribution": 999}},
        "capture": {"declared_event_count": 0, "declared_frame_count": 0, "truncated": False,
                    "sampler_termination": "NORMAL", "capture_completeness_declared": True},
        "configuration": {"max_read_skew_ns": 100, "max_frame_gap_ns": 100,
                          "phase_plan": {"parent": phases, "producer": [], "attribution": []},
                          "cgroup_requirement": "CORROBORATION_REQUIRED", "smaps_rollup_policy": "NOT_SAMPLED"},
        "topology": {"execution_mode": "inline", "parent_identities": [{**PARENT, "ppid": 1}],
                     "actual_workers": [], "registration_coverage": "DECLARED_COMPLETE"},
        "events": [event(0, "START")] + [event(i * 100, "PHASE", phase=p) for i, p in enumerate(phases[1:], 1)]
                  + [event(600, "EXIT")],
        "frames": [frame(i, i * 100 + 10, [PARENT], rss=5 + i) for i in range(6)],
    })


def spawned(reuse=False, overlap=False):
    data = inline()
    first, second = identity(200, 20), identity(201, 21)
    later = identity(200 if reuse else 300, 30)
    workers = [(first, "producer"), (second, "producer"), (later, "attribution")]
    data["topology"].update(execution_mode="spawned", actual_workers=[{**i, "parent_pid": 100, "pool": p} for i, p in workers])
    data["configuration"]["phase_plan"].update(producer=["producer"], attribution=["attribution"])
    data["events"] += [event(101, "START", first, "producer"), event(102, "START", second, "producer"),
                       event(195, "EXIT", first), event(196, "EXIT", second),
                       event(201 if not overlap else 103, "START", later, "attribution"), event(295, "EXIT", later)]
    data["events"].sort(key=lambda e: e["time_ns"])
    data["frames"][1] = frame(1, 110, [PARENT, first, second] + ([later] if overlap else []), rss=6)
    data["frames"][2] = frame(2, 210, [PARENT, later], rss=7)
    return finish_fixture(data)


def codes(result):
    return set(result["invalid_reason_codes"]) | set(result["incomplete_reason_codes"])


def check_seal(result):
    payload = {k: v for k, v in result.items() if k != "integrity"}
    assert result["integrity"] == {"algorithm": "sha256", "scope": "canonical result excluding integrity",
                                   "sha256": hashlib.sha256(canonical(payload)).hexdigest()}


def check_envelope(result):
    assert result["production_memory_qualification"] == "INCONCLUSIVE"
    assert result["production_chronological_peak"] == "NOT_OBSERVED"
    assert result["holder_release"] == "NOT_ESTABLISHED"
    assert result["actual_measurement_performed"] is False
    check_seal(result)


def assess(data, expected=None):
    result = sampler.assess_injected_capture(data)
    check_envelope(result)
    assert "INTERNAL_VALIDATION_FAILURE" not in codes(result)
    if expected:
        assert expected in codes(result)
        assert result["outcome"] != sampler.PROCESS_RSS_SAMPLE_COMPLETE
    return result


def test_inline_exact_success_and_distinct_memory_metrics():
    result = assess(inline())
    assert result["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE
    assert result["reasons"] == result["warnings"] == []
    assert result["sampled_rss"]["sampled_max_rss_bytes"] == 10 * 1024
    assert result["sampled_rss"]["sampled_max_frame_index"] == 5
    assert result["sampled_rss"]["metric_status"] == "COMPLETE_SAMPLED_SERIES"
    assert result["sampled_rss"]["eligible_frame_count"] == 6
    assert result["processes"]["100:10"]["max_observed_vmhwm_bytes"] == 20 * 1024
    assert result["frames"][0]["members"][0]["vmrss_bytes"] == 5 * 1024
    for pool in ("producer", "attribution"):
        assert set(result["phase_coverage"]["pools"][pool].values()) == {"NOT_APPLICABLE_BY_DECLARED_WORKLOAD"}


@pytest.mark.parametrize("reuse,overlap", [(False, False), (True, False), (False, True)])
def test_separate_actual_pools_sequential_overlapping_and_reused_pid(reuse, overlap):
    result = assess(spawned(reuse, overlap))
    assert result["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE
    assert result["sampled_rss"]["sampled_max_rss_bytes"] == (24 if overlap else 18) * 1024
    assert result["sampled_rss"]["sampled_max_frame_index"] == 1
    assert result["phase_coverage"]["pools"]["producer"]["producer"] == "OBSERVED"
    assert result["phase_coverage"]["pools"]["attribution"]["attribution"] == "OBSERVED"
    assert result["warnings"] == [{"code": "SHARED_PAGES_MAY_BE_COUNTED_REPEATEDLY", "location": "run"}]
    assert len(result["processes"]) == 4


@pytest.mark.parametrize("field,new,reason", [
    ("pid", 999, "IDENTITY_CONTRADICTION"), ("starttime_ticks", 11, "PID_REUSE_OR_IDENTITY_RACE"),
])
def test_stat_identity_mismatch(field, new, reason):
    data = inline()
    ident = dict(PARENT, **{field: new})
    data["frames"][0]["process_reads"][0]["stat_after"]["text"] = stat(ident)
    result = assess(data, reason)
    assert result["outcome"] == sampler.INVALID_CAPTURE
    assert result["frames"][0]["members"][0]["vmrss_bytes"] is None
    assert result["frames"][0]["sampled_aggregate_rss_bytes"] is None


@pytest.mark.parametrize("name", ["stat_before", "stat_after", "status"])
def test_ppid_mismatch(name):
    data = inline()
    data["frames"][0]["process_reads"][0][name]["text"] = status(PARENT, ppid=2) if name == "status" else stat(PARENT, ppid=2)
    assess(data, "IDENTITY_CONTRADICTION")


def test_status_pid_mismatch():
    data = inline()
    data["frames"][0]["process_reads"][0]["status"]["text"] = status(identity(999))
    assess(data, "IDENTITY_CONTRADICTION")


@pytest.mark.parametrize("name", ["stat_before", "status", "stat_after"])
@pytest.mark.parametrize("error", ["ENOENT", "ESRCH", "EACCES", "EPERM", "EIO"])
def test_failed_mandatory_read_is_not_zero(name, error):
    data = inline()
    item = data["frames"][0]["process_reads"][0][name]
    item.update(result="FAILED", error=error)
    del item["text"]
    result = assess(data, "PROCESS_READ_FAILED")
    assert result["outcome"] == sampler.INCOMPLETE_CAPTURE
    assert result["frames"][0]["sampled_aggregate_rss_bytes"] is None
    assert result["frames"][0]["members"][0]["vmrss_bytes"] is None
    assert result["sampled_rss"]["eligible_frame_count"] == 5


@pytest.mark.parametrize("state", ["Z", "X", "x"])
def test_exiting_process_skips_status_parse(state):
    data = inline()
    read = data["frames"][0]["process_reads"][0]
    read["stat_before"]["text"] = stat(PARENT, state=state)
    read["status"]["text"] = "this must not be parsed"
    result = assess(data, "PROCESS_READ_FAILED")
    assert "RAW_TEXT_MALFORMED" not in codes(result)


def test_mandatory_truncated_retains_raw_without_zero():
    data = inline()
    data["frames"][0]["process_reads"][0]["status"]["result"] = "TRUNCATED"
    result = assess(data, "RAW_READ_TRUNCATED")
    assert result["frames"][0]["members"][0]["vmhwm_bytes"] is None


@pytest.mark.parametrize("case,reason", [
    ("transient", "WORKER_LIFECYCLE_GAP"), ("unrostered_event", "UNROSTERED_PROCESS"),
    ("unrostered_read", "UNROSTERED_PROCESS"), ("silent", "WORKER_LIFECYCLE_GAP"),
    ("omitted", "ROSTER_INCOMPLETE"), ("exited", "ROSTER_CONTRADICTION"),
    ("missing_read", "PROCESS_READ_MISSING"), ("holder", "SCHEMA_INVALID"),
    ("parent_start", "PARENT_LIFECYCLE_GAP"), ("parent_exit", "PARENT_LIFECYCLE_GAP"),
    ("after_exit", "LIFECYCLE_CONTRADICTION"),
])
def test_lifecycle_and_roster_defects(case, reason):
    data = spawned()
    worker = identity(200, 20)
    if case == "transient":
        data["events"] = [dict(e, time_ns=192 if e["kind"] == "START" else 193)
                          if e["identity"] == worker else e for e in data["events"]]
        data["events"].sort(key=lambda e: e["time_ns"])
        data["frames"][1] = frame(1, 110, [PARENT, identity(201, 21)], rss=6)
    elif case == "unrostered_event":
        data["events"].insert(1, event(1, "START", identity(999, 99), "producer"))
    elif case == "unrostered_read":
        data["frames"][1]["process_reads"][1]["identity"] = identity(999, 99)
    elif case == "silent":
        data["events"] = [e for e in data["events"] if not (e["identity"] == worker and e["kind"] == "EXIT")]
        data["frames"][2]["process_reads"].append(process_read(worker, 240, ppid=100))
        read = data["frames"][2]["process_reads"][-1]["status"]
        read.update(result="FAILED", error="ENOENT")
        del read["text"]
    elif case == "omitted":
        data["frames"][1]["expected_live"].pop()
    elif case == "exited":
        data["frames"][2]["expected_live"].append(worker)
    elif case == "missing_read":
        data["frames"][1]["process_reads"].pop()
    elif case == "holder":
        data["events"][0]["kind"] = "CREATE"
    elif case in ("parent_start", "parent_exit"):
        target = "START" if case == "parent_start" else "EXIT"
        data["events"] = [e for e in data["events"] if not (e["identity"] == PARENT and e["kind"] == target)]
    else:
        data["events"].append(event(601, "START", worker, "producer"))
    finish_fixture(data)
    result = assess(data, reason)
    if case == "silent":
        assert "PROCESS_READ_FAILED" in codes(result)


@pytest.mark.parametrize("ticks,start", [(20, 201), (19, 201), (30, 103)])
def test_invalid_pid_reuse(ticks, start):
    data = spawned(reuse=True)
    for e in data["events"]:
        if e["identity"] == identity(200, 30):
            e["identity"]["starttime_ticks"] = ticks
            if e["kind"] == "START":
                e["time_ns"] = start
    data["topology"]["actual_workers"][-1]["starttime_ticks"] = ticks
    for f in data["frames"]:
        for ident in f["expected_live"]:
            if ident == identity(200, 30):
                ident["starttime_ticks"] = ticks
        for r in f["process_reads"]:
            if r["identity"] == identity(200, 30):
                r["identity"]["starttime_ticks"] = ticks
    data["events"].sort(key=lambda e: e["time_ns"])
    finish_fixture(data)
    result = assess(data)
    # Equal start ticks collide in topology before lifecycle analysis.
    assert ("DUPLICATE_IDENTITY" if ticks == 20 else "PID_REUSE_OR_IDENTITY_RACE") in codes(result)


@pytest.mark.parametrize("section", ["event", "frame", "identity", "cgroup", "kind", "unit"])
def test_clock_domain(section):
    data = inline()
    if section == "event":
        data["events"][0]["clock_domain_id"] = "other"
    elif section == "frame":
        data["frames"][0]["clock_domain_id"] = "other"
    elif section == "identity":
        data["topology"]["parent_identities"][0]["boot_id"] = "other"
    elif section == "cgroup":
        data["frames"][0]["cgroup"]["clock_domain_id"] = "other"
    else:
        data["clock"][section] = "CLOCK_REALTIME" if section == "kind" else "ms"
    assess(data, "CLOCK_DOMAIN_INVALID" if section in ("kind", "unit") else "CLOCK_DOMAIN_MISMATCH")


@pytest.mark.parametrize("section", ["events", "frames"])
@pytest.mark.parametrize("case", ["first", "gap", "duplicate", "decreasing"])
def test_sequences(section, case):
    data = inline()
    field = "sequence" if section == "events" else "frame_sequence"
    if case == "first":
        for record in data[section]:
            record[field] += 1
    elif case == "gap":
        for record in data[section][2:]:
            record[field] += 1
    else:
        data[section][2][field] = 1 if case == "duplicate" else 0
    assess(data, "SEQUENCE_GAP" if case in ("first", "gap") else "SEQUENCE_ORDER_INVALID")


def test_equal_event_times_are_accepted_and_backwards_times_rejected():
    data = spawned()
    data["events"][3]["time_ns"] = data["events"][2]["time_ns"]
    assert assess(data)["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE
    data["events"][3]["time_ns"] -= 1
    assess(data, "CHRONOLOGY_INVALID")


@pytest.mark.parametrize("bound,reason", [(7, None), (6, "READ_SKEW_EXCEEDED")])
def test_read_skew_boundary(bound, reason):
    data = inline()
    data["configuration"]["max_read_skew_ns"] = bound
    result = assess(data, reason)
    if reason is None:
        assert result["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE
        assert result["sampled_rss"]["max_eligible_read_skew_ns"] == 7
    else:
        assert result["sampled_rss"]["sampled_max_rss_bytes"] is None
        assert "NO_ELIGIBLE_FRAMES" in codes(result)


@pytest.mark.parametrize("bound", [20, 19])
def test_gap_boundary(bound):
    data = inline()
    data["configuration"]["max_frame_gap_ns"] = bound
    result = assess(data)
    if bound == 20:
        assert result["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE
    else:
        assert {r["location"] for r in result["reasons"] if r["code"] == "SAMPLE_GAP"} == {"frame:%d" % i for i in range(1, 6)}


@pytest.mark.parametrize("which,location", [(0, "run:initial"), (-1, "run:terminal")])
def test_initial_and_terminal_coverage(which, location):
    data = inline()
    del data["frames"][which]
    for i, f in enumerate(data["frames"]):
        f["frame_sequence"] = i
    finish_fixture(data)
    result = assess(data, "SAMPLE_GAP")
    assert {"code": "SAMPLE_GAP", "class": "INCOMPLETE", "location": location} in result["reasons"]


@pytest.mark.parametrize("offset,ambiguous", [(-1, False), (0, True), (40, True), (80, True), (81, False)])
def test_phase_closed_window_ties(offset, ambiguous):
    data = inline()
    data["events"][1]["time_ns"] = 10 + offset
    result = assess(data)
    assert ("AMBIGUOUS_PHASE_FRAME" in codes(result)) is ambiguous
    assert result["frames"][0]["eligible"] is (not ambiguous)


@pytest.mark.parametrize("kind", ["START", "EXIT"])
def test_membership_transition_inside_window(kind):
    data = spawned()
    for e in data["events"]:
        if e["identity"] == identity(200, 20) and e["kind"] == kind:
            e["time_ns"] = 150
    data["events"].sort(key=lambda e: e["time_ns"])
    finish_fixture(data)
    result = assess(data, "ROSTER_CHANGED_IN_FRAME")
    assert result["frames"][1]["sampled_aggregate_rss_bytes"] is None


@pytest.mark.parametrize("case,reason", [
    ("touch_frames", "FRAME_CHRONOLOGY_INVALID"), ("overlap_frames", "FRAME_CHRONOLOGY_INVALID"),
    ("reversed", "READ_WINDOW_INVALID"), ("outside", "READ_WINDOW_INVALID"),
    ("overlap_files", "READ_WINDOW_INVALID"), ("overlap_processes", "READ_WINDOW_INVALID"),
    ("evaluation", "READ_WINDOW_INVALID"), ("frame_kind", "FRAME_KIND_NOT_ACCEPTED"),
])
def test_frame_and_read_windows(case, reason):
    data = spawned()
    f = data["frames"][1]
    r = f["process_reads"][0]
    if case in ("touch_frames", "overlap_frames"):
        f["frame_start_ns"] = 90 if case == "touch_frames" else 89
    elif case == "reversed":
        r["status"]["end_ns"] = r["status"]["start_ns"] - 1
    elif case == "outside":
        r["stat_before"]["start_ns"] = 109
    elif case == "overlap_files":
        r["status"]["start_ns"] = 110
    elif case == "overlap_processes":
        f["process_reads"][1]["stat_before"]["start_ns"] = 115
    elif case == "evaluation":
        f["frame_evaluation_ns"] = 191
    else:
        f["frame_kind"] = "ATOMIC_SNAPSHOT"
    assess(data, reason)


def test_touching_file_windows_are_valid():
    data = inline()
    r = data["frames"][0]["process_reads"][0]
    r["status"]["start_ns"] = r["stat_before"]["end_ns"]
    r["stat_after"]["start_ns"] = r["status"]["end_ns"]
    assert assess(data)["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE


@pytest.mark.parametrize("where", ["topology", "expected_live", "process_reads"])
def test_duplicate_identities(where):
    data = spawned()
    if where == "topology":
        data[where]["actual_workers"].append(copy.deepcopy(data[where]["actual_workers"][0]))
    else:
        data["frames"][1][where].append(copy.deepcopy(data["frames"][1][where][-1]))
    assess(data, "DUPLICATE_IDENTITY")


@pytest.mark.parametrize("text,reason", [
    ("Pid: 100\nPPid: 1\nVmRSS: 5 MB\nVmHWM: 20 kB\nVmSwap: 0 kB\n", "RAW_TEXT_MALFORMED"),
    ("Pid: 100\nPPid: 1\nVmRSS: 5 kB\nVmRSS: 5 kB\nVmHWM: 20 kB\nVmSwap: 0 kB\n", "RAW_TEXT_MALFORMED"),
    ("Pid: 100\nPPid: 1\nVmHWM: 20 kB\nVmSwap: 0 kB\n", "RAW_TEXT_MALFORMED"),
    ("PPid: 1\nVmRSS: 5 kB\nVmHWM: 20 kB\nVmSwap: 0 kB\n", "RAW_TEXT_MALFORMED"),
    ("Pid: 100\nPPid: 1\nVmRSS: 5 kB\nVmHWM: 4 kB\nVmSwap: 0 kB\n", "COUNTER_INCONSISTENT"),
    ("Pid: １００\nPPid: 1\nVmRSS: 5 kB\nVmHWM: 20 kB\nVmSwap: 0 kB\n", "RAW_TEXT_MALFORMED"),
])
def test_raw_status_malformed_and_counter_semantics(text, reason):
    data = inline()
    data["frames"][0]["process_reads"][0]["status"]["text"] = text
    assess(data, reason)


def test_hwm_decrease_is_invalid():
    data = inline()
    data["frames"][1]["process_reads"][0]["status"]["text"] = status(PARENT, rss=6, hwm=19)
    assess(data, "COUNTER_INCONSISTENT")


@pytest.mark.parametrize("where", ["status", "smaps_rollup"])
def test_swap_is_incomplete_but_retains_eligible_rss(where):
    data = inline()
    r = data["frames"][0]["process_reads"][0]
    if where == "status":
        r[where]["text"] = status(PARENT, swap=1)
    else:
        data["configuration"]["smaps_rollup_policy"] = "OPTIONAL_DIAGNOSTIC"
        r[where] = fileread("Rss: 9 kB\nSwap: 1 kB\n", 14)
    result = assess(data, "OOM_OR_SWAP_OBSERVED")
    assert result["outcome"] == sampler.INCOMPLETE_CAPTURE
    assert result["frames"][0]["eligible"] is True
    assert result["frames"][0]["sampled_aggregate_rss_bytes"] == 5 * 1024


@pytest.mark.parametrize("case,reason", [
    ("oom", "OOM_OR_SWAP_OBSERVED"), ("max", "CGROUP_LIMIT_EVENT"), ("decrease", "COUNTER_INCONSISTENT"),
    ("disappear", "COUNTER_INCONSISTENT"), ("path", "CGROUP_HIERARCHY_AMBIGUOUS"),
    ("missing_pid", "CGROUP_HIERARCHY_AMBIGUOUS"), ("extra_pid", "CGROUP_NOT_ISOLATED"),
    ("v1", "CGROUP_CORROBORATION_INCOMPLETE"), ("null", "CGROUP_CORROBORATION_INCOMPLETE"),
    ("events_failed", "CGROUP_CORROBORATION_INCOMPLETE"), ("procs_failed", "CGROUP_CORROBORATION_INCOMPLETE"),
    ("procs_truncated", "CGROUP_CORROBORATION_INCOMPLETE"), ("missing_key", "SCHEMA_INVALID"),
    ("bad_pid", "RAW_TEXT_MALFORMED"), ("duplicate_pid", "RAW_TEXT_MALFORMED"),
    ("unicode", "RAW_TEXT_MALFORMED"), ("bad_current", "RAW_TEXT_MALFORMED"),
    ("window", "READ_WINDOW_INVALID"),
])
def test_cgroup_fail_closed_without_erasing_rss(case, reason):
    data = inline()
    cg = data["frames"][1]["cgroup"]
    if case in ("oom", "max"):
        cg["memory_events"]["text"] = cg["memory_events"]["text"].replace(case + " 0", case + " 1")
    elif case == "decrease":
        data["frames"][0]["cgroup"]["memory_events"]["text"] += "future 2\n"
        cg["memory_events"]["text"] += "future 1\n"
    elif case == "disappear":
        data["frames"][0]["cgroup"]["memory_events"]["text"] += "future 2\n"
    elif case == "path":
        cg["cgroup_path"] = "/different"
    elif case == "missing_pid":
        cg["cgroup_procs"]["text"] = ""
    elif case == "extra_pid":
        cg["cgroup_procs"]["text"] += "999\n"
    elif case == "v1":
        cg["cgroup_version"] = 1
    elif case == "null":
        data["frames"][1]["cgroup"] = None
    elif case in ("events_failed", "procs_failed"):
        item = cg["memory_events" if case == "events_failed" else "cgroup_procs"]
        item.update(result="FAILED", error="EACCES")
        del item["text"]
    elif case == "procs_truncated":
        cg["cgroup_procs"]["result"] = "TRUNCATED"
    elif case == "missing_key":
        del data["frames"][1]["cgroup"]
    elif case in ("bad_pid", "duplicate_pid", "unicode"):
        cg["cgroup_procs"]["text"] = {"bad_pid": "0\n", "duplicate_pid": "100\n100\n", "unicode": "１００\n"}[case]
    elif case == "bad_current":
        cg["memory_current"]["text"] = "1 kB\n"
    else:
        cg["cgroup_procs"]["start_ns"] = cg["memory_events"]["start_ns"]
    result = assess(data, reason)
    if case != "missing_key":
        assert result["frames"][1]["eligible"] is True
        assert result["frames"][1]["sampled_aggregate_rss_bytes"] == 6 * 1024


def test_cgroup_diagnostics_never_change_rss_or_expose_other_peak_keys():
    data = inline()
    for f in data["frames"]:
        f["cgroup"]["memory_current"]["text"] = str(2 ** 62)
        f["cgroup"]["memory_peak"]["text"] = str(2 ** 62 + 1)
    result = assess(data)
    assert result["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE
    assert result["sampled_rss"]["sampled_max_rss_bytes"] == 10240
    assert result["cgroup_observations"][0]["memory_peak_bytes"] == 2 ** 62 + 1

    def walk(value):
        if type(value) is dict:
            for k, v in value.items():
                if k == "provider_input":
                    continue
                assert "peak" not in k or k in ("production_chronological_peak", "memory_peak_bytes")
                walk(v)
        elif type(value) is list:
            for item in value:
                walk(item)
    walk(result)


@pytest.mark.parametrize("case", ["absent", "failed", "truncated", "all", "forbidden"])
def test_optional_smaps_policy(case):
    data = inline()
    if case != "forbidden":
        data["configuration"]["smaps_rollup_policy"] = "OPTIONAL_DIAGNOSTIC"
    if case == "all":
        data["frames"] = [frame(i, i * 100 + 10, [PARENT], rss=5 + i, smaps=True) for i in range(6)]
    elif case != "absent":
        r = data["frames"][0]["process_reads"][0]
        r["smaps_rollup"] = fileread("EACCES" if case == "failed" else "Rss: 9 kB\nSwap: 0 kB\n", 14,
                                         result={"failed": "FAILED", "truncated": "TRUNCATED"}.get(case, "OK"))
    result = assess(data)
    if case == "forbidden":
        assert "SMAPS_POLICY_VIOLATION" in codes(result)
    else:
        assert result["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE
        assert result["frames"][0]["smaps_rss_diagnostic_bytes"] == (9216 if case == "all" else None)
        assert result["sampled_rss"]["sampled_max_rss_bytes"] == 10240
        assert bool(result["warnings"]) is (case in ("failed", "truncated"))


def test_combined_reasons_invalid_precedence_diagnostics_and_deduplication():
    data = inline()
    data["frames"][0]["process_reads"][0]["stat_after"]["text"] = stat(identity(100, 11))
    data["frames"][1]["cgroup"] = None
    data["capture"]["truncated"] = True
    data["configuration"]["max_frame_gap_ns"] = 19
    result = assess(data, "PID_REUSE_OR_IDENTITY_RACE")
    assert result["outcome"] == sampler.INVALID_CAPTURE
    assert {"EVIDENCE_TRUNCATED", "SAMPLE_GAP", "CGROUP_CORROBORATION_INCOMPLETE"} <= codes(result)
    assert result["sampled_rss"]["sampled_max_rss_bytes"] == 10240
    pairs = [(r["code"], r["location"]) for r in result["reasons"]]
    assert pairs == sorted(set(pairs))
    assert result["sampled_rss"]["metric_status"] == "DIAGNOSTIC_ONLY"


@pytest.mark.parametrize("section,field,value,reason", [
    (None, "source_type", "REAL_PROCFS", "SOURCE_TYPE_NOT_ACCEPTED"),
    (None, "schema", "wrong", "SCHEMA_VERSION_MISMATCH"),
    ("source_provenance", "origin_attestation", "AUTHENTICATED", "SOURCE_TYPE_NOT_ACCEPTED"),
    ("capture", "truncated", True, "EVIDENCE_TRUNCATED"),
    ("capture", "sampler_termination", "ABNORMAL", "SAMPLER_TERMINATED"),
    ("capture", "capture_completeness_declared", False, "CAPTURE_DECLARED_INCOMPLETE"),
    ("capture", "declared_event_count", 999, "DECLARED_COUNT_MISMATCH"),
    ("capture", "declared_frame_count", 999, "DECLARED_COUNT_MISMATCH"),
    ("topology", "registration_coverage", "NOT_ESTABLISHED", "REGISTRATION_NOT_ESTABLISHED"),
    ("configuration", "max_frame_gap_ns", 0, "CONFIGURATION_INVALID"),
    ("configuration", "cgroup_requirement", "OPTIONAL", "CONFIGURATION_INVALID"),
    ("topology", "execution_mode", "guessed", "TOPOLOGY_INVALID"),
])
def test_root_contract(section, field, value, reason):
    data = inline()
    (data if section is None else data[section])[field] = value
    result = assess(data, reason)
    if value == "REAL_PROCFS":
        assert result["source_type"] == "REAL_PROCFS"
    if result["invalid_reason_codes"]:
        assert result["frames"] == []
        assert result["processes"] == result["phase_coverage"] == {}
        assert result["cgroup_observations"] == []


@pytest.mark.parametrize("where", ["root", "event", "frame", "read", "file", "identity", "cgroup", "plan"])
def test_closed_objects(where):
    data = inline()
    target = {"root": data, "event": data["events"][0], "frame": data["frames"][0],
              "read": data["frames"][0]["process_reads"][0],
              "file": data["frames"][0]["process_reads"][0]["status"],
              "identity": data["events"][0]["identity"], "cgroup": data["frames"][0]["cgroup"],
              "plan": data["configuration"]["phase_plan"]}[where]
    target["unexpected"] = 1
    assess(data, "UNKNOWN_FIELD")


@pytest.mark.parametrize("field", ["outcome", "production_memory_qualification"])
def test_no_trusted_field_promotion(field):
    data = inline()
    data[field] = "FORGED"
    assess(data, "UNKNOWN_FIELD")


@pytest.mark.parametrize("value", [True, 1.0, -1, "1", None])
@pytest.mark.parametrize("where", ["pid", "time_ns", "read_time"])
def test_integer_types(value, where):
    data = inline()
    if where == "pid":
        data["topology"]["parent_identities"][0]["pid"] = value
    elif where == "time_ns":
        data["events"][0]["time_ns"] = value
    else:
        data["frames"][0]["process_reads"][0]["status"]["start_ns"] = value
    assess(data, "SCHEMA_INVALID")


@pytest.mark.parametrize("value", [None, [], "text", 1, True])
def test_nonobject_root_always_sealed(value):
    assess(value, "SCHEMA_INVALID")


class DictSubclass(dict):
    pass


@pytest.mark.parametrize("value", [(1,), DictSubclass(a=1), {1: "bad"}, float("nan"), float("inf"),
                                       -float("inf"), "\ud800", {"\ud800": 1}, object()])
def test_non_json_values(value):
    result = assess(value, "INPUT_NOT_JSON")
    assert result["provider_input"] is result["input_sha256"] is result["source_type"] is result["run_id"] is None


def test_cycles_are_rejected_and_aliasing_is_allowed():
    value = []
    value.append(value)
    assess(value, "INPUT_NOT_JSON")
    data = inline()
    data["frames"][0]["expected_live"][0] = data["events"][0]["identity"]
    assert assess(data)["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE


@pytest.mark.parametrize("case", ["nodes", "text", "unicode_text", "depth", "integer", "events", "frames", "identities", "reads"])
def test_input_caps(case):
    data = inline()
    if case == "nodes":
        data = [None] * (sampler.MAX_NODES + 1)
    elif case in ("text", "unicode_text"):
        data = "a" * (sampler.MAX_TEXT_BYTES + 1) if case == "text" else "é" * (sampler.MAX_TEXT_BYTES // 2 + 1)
    elif case == "depth":
        data = 0
        for _ in range(sampler.MAX_DEPTH + 1):
            data = [data]
    elif case == "integer":
        data = 2 ** 63
    elif case in ("events", "frames"):
        data[case] = [data[case][0]] * (getattr(sampler, "MAX_" + case.upper()) + 1)
    elif case == "identities":
        data["topology"]["actual_workers"] = [{**identity(i + 200, i), "parent_pid": 100, "pool": "producer"}
                                                 for i in range(sampler.MAX_IDENTITIES)]
    else:
        data["frames"][0]["process_reads"] *= sampler.MAX_READS_PER_FRAME + 1
    result = assess(data, "INPUT_CAP_EXCEEDED")
    assert result["outcome"] == sampler.INVALID_CAPTURE


def test_total_text_cap(monkeypatch):
    monkeypatch.setattr(sampler, "MAX_TOTAL_TEXT_BYTES", 10)
    result = assess({"a": "1234567890"}, "INPUT_CAP_EXCEEDED")
    assert result["provider_input"] is None


@pytest.mark.parametrize("where", ["status", "smaps_rollup"])
def test_whitespace_guard_precedes_dependency_parser(monkeypatch, where):
    data = inline()
    read = data["frames"][0]["process_reads"][0]
    text = (status(PARENT) if where == "status" else "Rss: 9 kB\nSwap: 0 kB\n").replace(": ", ":" + " " * 65, 1)
    if where == "status":
        read[where]["text"] = text
    else:
        data["configuration"]["smaps_rollup_policy"] = "OPTIONAL_DIAGNOSTIC"
        read[where] = fileread(text, 14)
    original = getattr(sampler.f2a, "parse_" + where)

    def guarded(raw):
        assert raw != text, "oversized whitespace reached dependency parser"
        return original(raw)
    monkeypatch.setattr(sampler.f2a, "parse_" + where, guarded)
    assess(data, "RAW_TEXT_MALFORMED")


@pytest.mark.parametrize("where", ["stat_before", "status", "smaps_rollup", "memory_events", "cgroup_procs", "memory_current"])
def test_huge_raw_integers_do_not_escape(where):
    data = inline()
    read = data["frames"][0]["process_reads"][0]
    digits = "9" * 5000
    if where == "stat_before":
        read[where]["text"] = read[where]["text"].replace("100 (", digits + " (", 1)
    elif where == "status":
        read[where]["text"] = read[where]["text"].replace("5 kB", digits + " kB")
    elif where == "smaps_rollup":
        data["configuration"]["smaps_rollup_policy"] = "OPTIONAL_DIAGNOSTIC"
        read[where] = fileread("Rss: " + digits + " kB\nSwap: 0 kB\n", 14)
    else:
        cg = data["frames"][0]["cgroup"]
        cg[where]["text"] = "low " + digits + "\nhigh 0\nmax 0\noom 0\noom_kill 0\n" if where == "memory_events" else digits
    assess(data, "RAW_TEXT_MALFORMED")


def test_determinism_reconstruction_seal_and_no_input_mutation():
    data = spawned(reuse=True)
    before = canonical(data)
    first = assess(data)
    assert canonical(data) == before
    assert first["input_sha256"] == hashlib.sha256(before).hexdigest()
    assert canonical(assess(data)) == canonical(first)
    assert canonical(assess(first["provider_input"])) == canonical(first)

    def permute(value):
        if type(value) is dict:
            return {k: permute(v) for k, v in reversed(list(value.items()))}
        if type(value) is list:
            return [permute(v) for v in value]
        return value
    assert canonical(assess(permute(data))) == canonical(first)
    first["provider_input"]["events"][0]["identity"]["pid"] = 999
    first["frames"][1]["members"][0]["identity"]["pid"] = 888
    assert canonical(data) == before
    assert assess(data)["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE


def test_internal_failure_is_sealed_without_exception_text(monkeypatch):
    def fail(self):
        raise RuntimeError("SECRET EXCEPTION DETAIL")
    monkeypatch.setattr(sampler._Assessment, "frames", fail)
    result = sampler.assess_injected_capture(inline())
    check_envelope(result)
    assert result["reasons"] == [{"code": "INTERNAL_VALIDATION_FAILURE", "class": "INVALID", "location": "root"}]
    assert "SECRET" not in canonical(result).decode()
    assert result["provider_input"] == inline()
    assert result["frames"] == []


def test_import_and_calls_cannot_touch_live_apis(monkeypatch):
    source = MODULE_PATH.read_text()
    tree = ast.parse(source)
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert len(imports) == 4
    assert {n.names[0].name for n in imports if isinstance(n, ast.Import)} == {"hashlib", "json", "re"}
    from_import = next(n for n in imports if isinstance(n, ast.ImportFrom))
    assert from_import.module == "scripts.benchmarks"
    assert [(n.name, n.asname) for n in from_import.names] == [("rb_post3d_08p2e2_r2f_f2a_observer", "f2a")]
    assert {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "f2a"} <= {"parse_stat", "parse_status", "parse_smaps_rollup", "parse_memory_events", "EvidenceError"}
    for forbidden in ("__name__", "engine", "shading", "f2b1", "f2b2", "f2b3", "OBSERVATION_COMPLETE",
                      "COMPARABLE_FAKE_OBSERVATIONS", "FAKE_INPUT_ONLY", "ATOMIC_SNAPSHOT"):
        assert forbidden not in source
    # Walk expressions actually executed at import, including defaults/decorators.
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            expressions = list(node.decorator_list)
            if isinstance(node, ast.FunctionDef):
                expressions += node.args.defaults + [d for d in node.args.kw_defaults if d is not None]
        else:
            expressions = [node]
        assert not any(isinstance(child, ast.Call) for expr in expressions for child in ast.walk(expr))
    good, bad = inline(), inline()
    bad["frames"][0]["cgroup"] = None
    expected = [canonical(sampler.assess_injected_capture(d)) for d in (good, bad)]
    original_import = builtins.__import__

    def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        assert name in ("hashlib", "json", "re", "scripts.benchmarks")
        return original_import(name, globals, locals, fromlist, level)

    def forbidden_api(*args, **kwargs):
        raise AssertionError("live API called")

    # Compile before patching; import execution and both function calls are guarded.
    compiled = compile(source, str(MODULE_PATH), "exec")
    with monkeypatch.context() as guard:
        for obj, names in (
            (builtins, ("open",)), (io, ("open",)),
            (os, ("open", "stat", "listdir", "scandir", "walk", "getpid", "fork", "system")),
            (Path, ("open", "read_text", "read_bytes", "iterdir")), (subprocess, ("Popen", "run")),
            (socket, ("socket",)), (time, ("monotonic", "monotonic_ns", "perf_counter", "time", "time_ns")),
        ):
            for name in names:
                if hasattr(obj, name):
                    guard.setattr(obj, name, forbidden_api)
        # pytest's setattr imports inspect. Install the import guard last so
        # setup can finish and undo restores imports first; module execution
        # and both validator calls still run under every restriction.
        guard.setattr(builtins, "__import__", restricted_import)
        namespace = {}
        exec(compiled, namespace)
        actual = [canonical(namespace["assess_injected_capture"](d)) for d in (good, bad)]
    assert actual == expected


def test_test_module_scope_has_no_skip_or_production_dependencies():
    tree = ast.parse(Path(__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert not (isinstance(node.value, ast.Name) and node.value.id == "pytest" and node.attr in ("skip", "xfail"))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [node.module] if isinstance(node, ast.ImportFrom) else [x.name for x in node.names]
            assert all(not name.startswith(("engine", "shading")) for name in names)


@pytest.mark.parametrize("where", ["status", "smaps_rollup", "memory_events", "cgroup_procs", "memory_current", "memory_peak"])
def test_non_ascii_raw_numbers(where):
    data = inline()
    read = data["frames"][0]["process_reads"][0]
    if where == "status":
        read[where]["text"] = status(PARENT).replace("5 kB", "５ kB")
    elif where == "smaps_rollup":
        data["configuration"]["smaps_rollup_policy"] = "OPTIONAL_DIAGNOSTIC"
        read[where] = fileread("Rss: ９ kB\nSwap: 0 kB\n", 14)
    else:
        cg = data["frames"][0]["cgroup"]
        cg[where]["text"] = "low ０\nhigh 0\nmax 0\noom 0\noom_kill 0\n" if where == "memory_events" else "１００\n"
    assess(data, "RAW_TEXT_MALFORMED")


@pytest.mark.parametrize("where", ["memory_current", "memory_peak"])
@pytest.mark.parametrize("result", ["FAILED", "TRUNCATED"])
def test_optional_cgroup_diagnostic_failure_is_warning_only(where, result):
    data = inline()
    old = data["frames"][0]["cgroup"][where]
    data["frames"][0]["cgroup"][where] = fileread("EACCES" if result == "FAILED" else "100",
                                                               old["start_ns"], result)
    report = assess(data)
    assert report["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE
    assert report["cgroup_observations"][0][where + "_bytes"] is None
    assert report["warnings"] == [{"code": "CGROUP_DIAGNOSTIC_UNAVAILABLE", "location": "frame:0/cgroup/" + where}]


@pytest.mark.parametrize("case,reason", [
    ("no_parent", "TOPOLOGY_INVALID"), ("many_parents", "TOPOLOGY_INVALID"),
    ("parent_pid", "TOPOLOGY_INVALID"), ("inline_workers", "TOPOLOGY_INVALID"),
    ("inline_plan", "TOPOLOGY_INVALID"), ("spawned_empty", "TOPOLOGY_INVALID"),
    ("pool_no_plan", "TOPOLOGY_INVALID"), ("plan_no_pool", "TOPOLOGY_INVALID"),
    ("empty_parent_plan", "CONFIGURATION_INVALID"), ("duplicate_phase", "CONFIGURATION_INVALID"),
    ("unknown_phase", "CONFIGURATION_INVALID"), ("malformed_parent", "SCHEMA_INVALID"),
])
def test_topology_and_configuration_constraints(case, reason):
    data = spawned()
    if case == "no_parent":
        data["topology"]["parent_identities"] = []
    elif case == "many_parents":
        data["topology"]["parent_identities"] *= 2
    elif case == "parent_pid":
        data["topology"]["actual_workers"][0]["parent_pid"] = 999
    elif case == "inline_workers":
        data["topology"]["execution_mode"] = "inline"
    elif case == "inline_plan":
        data = inline()
        data["configuration"]["phase_plan"]["producer"] = ["producer"]
    elif case == "spawned_empty":
        data["topology"]["actual_workers"] = []
    elif case == "pool_no_plan":
        data["configuration"]["phase_plan"]["producer"] = []
    elif case == "plan_no_pool":
        data["topology"]["actual_workers"] = [w for w in data["topology"]["actual_workers"] if w["pool"] != "producer"]
    elif case == "empty_parent_plan":
        data["configuration"]["phase_plan"]["parent"] = []
    elif case == "duplicate_phase":
        data["configuration"]["phase_plan"]["parent"].append("setup")
    elif case == "unknown_phase":
        data["configuration"]["phase_plan"]["parent"].append("invented")
    else:
        del data["topology"]["parent_identities"][0]["pid"]
    assess(data, reason)


@pytest.mark.parametrize("case,reason", [
    ("duplicate_start", "LIFECYCLE_CONTRADICTION"), ("duplicate_phase", "LIFECYCLE_CONTRADICTION"),
    ("phase_not_live", "LIFECYCLE_CONTRADICTION"), ("worker_before_parent", "LIFECYCLE_CONTRADICTION"),
    ("outside_plan", "PHASE_PLAN_CONTRADICTION"),
])
def test_event_application_is_fail_closed(case, reason):
    data = spawned()
    if case == "duplicate_start":
        data["events"].insert(1, event(1, "START"))
    elif case == "duplicate_phase":
        data["events"].insert(1, event(1, "PHASE"))
    elif case == "phase_not_live":
        data["events"].insert(1, event(1, "PHASE", identity(200, 20), "producer"))
    elif case == "worker_before_parent":
        data["events"].insert(0, event(0, "START", identity(200, 20), "producer"))
    else:
        data["events"][0]["phase"] = "invented"
    finish_fixture(data)
    assess(data, reason)


def test_incomplete_only_combination_preserves_all_codes():
    data = inline()
    data["capture"].update(truncated=True, sampler_termination="ABNORMAL", capture_completeness_declared=False)
    data["topology"]["registration_coverage"] = "NOT_ESTABLISHED"
    data["frames"][0]["cgroup"] = None
    report = assess(data)
    assert report["outcome"] == sampler.INCOMPLETE_CAPTURE
    assert report["invalid_reason_codes"] == []
    assert set(report["incomplete_reason_codes"]) == {
        "EVIDENCE_TRUNCATED", "SAMPLER_TERMINATED", "CAPTURE_DECLARED_INCOMPLETE",
        "REGISTRATION_NOT_ESTABLISHED", "CGROUP_CORROBORATION_INCOMPLETE",
    }
    assert report["sampled_rss"]["eligible_frame_count"] == 6


def test_s1_sections_are_independent_and_capture_flags_survive():
    data = inline()
    data["schema"] = "wrong"
    data["clock"]["kind"] = "wrong"
    data["configuration"]["max_frame_gap_ns"] = 0
    data["capture"]["truncated"] = True
    report = assess(data)
    assert set(report["invalid_reason_codes"]) == {"SCHEMA_VERSION_MISMATCH", "CLOCK_DOMAIN_INVALID", "CONFIGURATION_INVALID"}
    assert report["incomplete_reason_codes"] == ["EVIDENCE_TRUNCATED"]
    assert report["frames"] == []


def test_no_frames_gives_null_metric_and_all_missing_coverage():
    data = inline()
    data["frames"] = []
    finish_fixture(data)
    report = assess(data, "NO_ELIGIBLE_FRAMES")
    assert report["outcome"] == sampler.INCOMPLETE_CAPTURE
    assert report["sampled_rss"]["sampled_max_rss_bytes"] is None
    assert report["sampled_rss"]["sampled_max_frame_index"] is None
    assert report["sampled_rss"]["eligible_frame_count"] == 0
    assert "PHASE_COVERAGE_GAP" in codes(report)


def test_equal_sampled_maximum_uses_lowest_frame_index():
    data = inline()
    for f in data["frames"]:
        f["process_reads"][0]["status"]["text"] = status(PARENT, rss=10)
    report = assess(data)
    assert report["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE
    assert report["sampled_rss"]["sampled_max_rss_bytes"] == 10240
    assert report["sampled_rss"]["sampled_max_frame_index"] == 0


@pytest.mark.parametrize("field", ["max_read_skew_ns", "max_frame_gap_ns"])
@pytest.mark.parametrize("value", [True, 1.0, None, "100"])
def test_configuration_integer_types_are_schema_errors(field, value):
    data = inline()
    data["configuration"][field] = value
    report = assess(data, "SCHEMA_INVALID")
    assert report["invalid_reason_codes"] == ["SCHEMA_INVALID"]


def test_empty_roster_has_no_numeric_zero():
    data = inline()
    # A frame strictly after the complete declared parent lifetime has no live members.
    data["frames"].append(frame(6, 610, []))
    finish_fixture(data)
    report = assess(data)
    empty = report["frames"][-1]
    assert empty["live_roster"] == []
    assert empty["ineligibility_codes"] == ["EMPTY_ROSTER"]
    assert empty["sampled_aggregate_rss_bytes"] is None
    assert empty["read_skew_ns"] is None
    assert report["sampled_rss"]["eligible_frame_count"] == 6


def test_raw_hashes_are_of_exact_supplied_text_and_reconstruction_detects_tamper():
    data = inline()
    report = assess(data)
    read = data["frames"][0]["process_reads"][0]
    hashes = report["frames"][0]["members"][0]["raw_sha256"]
    assert hashes["status"] == hashlib.sha256(read["status"]["text"].encode()).hexdigest()
    assert hashes["smaps_rollup"] is None
    original = canonical(report)
    report["frames"][0]["sampled_aggregate_rss_bytes"] += 1024
    assert canonical(sampler.assess_injected_capture(report["provider_input"])) == original
    assert report["integrity"]["sha256"] != hashlib.sha256(canonical({k: v for k, v in report.items() if k != "integrity"})).hexdigest()


def test_future_raw_counter_names_are_not_promoted_to_output_keys():
    data = inline()
    for f in data["frames"]:
        f["cgroup"]["memory_events"]["text"] += "future_peak_counter 0\n"
    report = assess(data)
    assert report["outcome"] == sampler.PROCESS_RSS_SAMPLE_COMPLETE
    assert "future_peak_counter" not in report["cgroup_observations"][0]["memory_events"]
    assert "future_peak_counter" in report["provider_input"]["frames"][0]["cgroup"]["memory_events"]["text"]
    # Even unknown counters remain accountable for disappearance and decreases.
    data["frames"][1]["cgroup"]["memory_events"]["text"] = data["frames"][1]["cgroup"]["memory_events"]["text"].replace("future_peak_counter 0\n", "")
    assess(data, "COUNTER_INCONSISTENT")
