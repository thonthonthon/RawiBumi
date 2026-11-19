"""Injected artificial adapter contracts; never invoke a production pipeline."""

import ast
import builtins
import copy
import inspect
import io
import os
import socket
import subprocess
import time

import pytest

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2a_observer as o
from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b1_verify as v
from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b2_adapter as a


def memory_events(**changes):
    values = dict(low=0, high=0, max=0, oom=0, oom_kill=0)
    values.update(changes)
    return "".join(f"{key} {value}\n" for key, value in values.items())


def reading(ident, ppid, phase, now, rss=40, final=False):
    tail = ["S"] + ["0"] * 19
    tail[1], tail[19] = str(ppid), str(ident[1])
    return {
        "identity": ident.copy(), "phase": phase, "final": final,
        "read_start_ns": now - 2, "read_end_ns": now - 1,
        "status": (f"Name: fake\nPid: {ident[0]}\nPPid: {ppid}\n"
                   f"VmRSS: {rss} kB\nVmHWM: 500 kB\nVmSwap: 0 kB\n"),
        "stat": f"{ident[0]} (fake process) " + " ".join(tail),
        "smaps_rollup": f"Rss: {rss} kB\nSwap: 0 kB\n",
    }


def frame(processes, phase, now, rss=40, final=False):
    return {
        "kind": "FRAME", "time_ns": now,
        "read_start_ns": now - 2, "read_end_ns": now,
        "expected_live": [ident.copy() for ident, _, _ in processes],
        "readings": [reading(ident, ppid, phase, now, 20 if role == "parent" else rss,
                             final) for ident, ppid, role in processes],
        "cgroup": {"time_ns": now, "memory_events": memory_events(),
                   "read_start_ns": now - 1, "read_end_ns": now},
    }


def decorate(provider):
    """Fixture construction only: supply explicit provenance and sequences."""
    domain = provider["clock"]["domain_id"]
    sources = {item["kind"]: item["source_id"] for item in provider["sources"]}
    capture_sequence = 0
    for sequence, event in enumerate(provider["events"]):
        event.update(sequence=sequence, source_id=sources["fake_events"],
                     clock_id=domain, metadata={"event_id": f"event-{sequence}"})
        if event["kind"] == "FRAME":
            for item in event["readings"]:
                item.update(source_id=sources["fake_proc"], clock_id=domain,
                            capture_sequence=capture_sequence, metadata={"injected": True})
                item["file_read_bounds"] = {
                    name: {"read_start_ns": item["read_start_ns"],
                           "read_end_ns": item["read_end_ns"]}
                    for name in ("status", "stat", "smaps_rollup") if item.get(name) is not None
                }
                capture_sequence += 1
            if event.get("cgroup") is not None:
                event["cgroup"].update(source_id=sources["fake_cgroup"], clock_id=domain,
                                       capture_sequence=capture_sequence, metadata={"injected": True})
                capture_sequence += 1
    provider["declared_record_count"] = len(provider["events"])
    provider["declared_frame_count"] = sum(e["kind"] == "FRAME" for e in provider["events"])
    return provider


def provider(run="baseline", offset=0, workers=1, phases=o.PHASES,
             rss=40, mode=None):
    parent = [100 + offset, 10 + offset]
    roster = [{"identity": [200 + offset + index, 20 + offset + index],
               "parent": parent.copy(), "pool": "shared_fake_pool"}
              for index in range(workers)]
    processes = [(parent, 1, "parent")]
    processes += [(item["identity"], parent[0], "worker") for item in roster]
    events = [{"kind": "START", "identity": ident.copy(), "ppid": ppid,
               "role": role, "phase": phases[0], "time_ns": 0 if role == "parent" else 1}
              for ident, ppid, role in processes]
    events += [
        {"kind": "CREATE", "time_ns": 2, "identity": parent.copy(),
         "phase": phases[0], "holder_id": "holder", "slots": 3,
         "initialization_succeeded": True},
        {"kind": "RELEASE", "time_ns": 3, "identity": parent.copy(),
         "phase": phases[0], "holder_id": "holder", "slots": 3,
         "ownership_termination": {"explicit": True, "basis": "explicit_owner_disposal",
                                   "evidence_id": "injected-disposal"}},
    ]
    for index, phase in enumerate(phases):
        now = 10 * (index + 1)
        if index:
            events += [{"kind": "PHASE", "identity": ident.copy(), "phase": phase,
                        "time_ns": now - 9} for ident, _, _ in processes]
        events.append(frame(processes, phase, now, rss, final=index == len(phases) - 1))
    events += [{"kind": "EXIT", "time_ns": 10 * len(phases), "identity": ident.copy()}
               for ident, _, _ in reversed(processes)]
    value = {
        "schema": a.SCHEMA, "input_kind": "FAKE_INPUT_ONLY",
        "clock": {"kind": "monotonic", "unit": "ns", "domain_id": "fake-clock-" + run},
        "sources": [{"source_id": kind + "-" + run, "kind": kind,
                     "clock_id": "fake-clock-" + run, "metadata": {"provider": "injected"}}
                    for kind in ("fake_events", "fake_proc", "fake_cgroup")],
        "configuration": {
            "max_read_skew_ns": 5, "max_frame_gap_ns": 100,
            "required_phases": list(phases),
            "topology": {"start_method": "spawn", "parents": [parent], "workers": roster,
                         "max_concurrent_workers": 4,
                         "execution_mode": mode or ("spawned" if workers else "inline")}},
        "input_id": "fake-" + run, "independent_run_id": run, "workload_id": "fake-workload",
        "conditions": {"modules": 2, "intervals": 1, "state": "artificial"},
        "events": events, "truncated": False,
        "holder_coverage": [{"identity": ident.copy(), "phase": phase, "events_complete": True}
                            for ident, _, _ in processes for phase in phases],
    }
    return decorate(value)


def frames(value):
    return [event for event in value["events"] if event["kind"] == "FRAME"]


def event(value, kind):
    return next(item for item in value["events"] if item["kind"] == kind)


def codes(report):
    return {item["code"] for item in report["reasons"]}


def envelope(report):
    assert o.verify_integrity(report)
    for key, value in a.ENVELOPE.items():
        assert report[key] == value

    def visit(item):
        if type(item) is dict:
            assert not set(item) & {"budget_pass", "speedup", "numerical_parity",
                                    "projection_717", "summed_hwm_peak_bytes"}
            for child in item.values():
                visit(child)
        elif type(item) is list:
            for child in item:
                visit(child)
        elif type(item) is str:
            assert item not in {"PASS", "ACCEPTED", "MEMORY_SCREEN_MET"}

    visit(report)


def mapped(value):
    result = a.adapt(value)
    envelope(result)
    assert result["adapter_status"] == "MAPPED_FAKE_INPUT", result["reasons"]
    report = result["observer_report"]
    envelope(report)
    assert o.canonical_bytes(report) == o.canonical_bytes(o.reconcile(
        result["configuration"], result["evidence"]))
    verification = v.verify_report(report)
    envelope(verification)
    assert verification["verification"]["reconstruction_verified"] is True
    return result


def complete(value=None):
    result = mapped(provider() if value is None else value)
    assert result["outcome"] == o.COMPLETE, result["reasons"]
    assert result["reasons"] == []
    assert v.verify_report(result["observer_report"])["outcome"] == "VERIFIED_FAKE_OBSERVATION"
    return result


def diagnostic(value, code=None, outcome=o.INVALID):
    result = a.adapt(value)
    envelope(result)
    assert result["adapter_status"] == "ADAPTER_DIAGNOSTIC"
    assert result["observer_report"] is None
    assert result["outcome"] == outcome
    if code:
        assert codes(result) == {code}
    return result


def not_comparable(result):
    assert result["outcome"] in (o.INVALID, o.INCONCLUSIVE)
    baseline = complete(provider(run="comparison-baseline", offset=10000))
    comparison = v.compare_verified_reports(baseline["observer_report"], result["observer_report"])
    envelope(comparison)
    assert comparison["outcome"] == v.NOT_COMPARABLE
    assert comparison[v.DELTA] is None
    assert comparison["baseline"]["eligible"] is True
    assert comparison["candidate"]["eligible"] is False
    assert not any(item["code"] == "INPUTS_NOT_INDEPENDENT" for item in comparison["reasons"])


@pytest.mark.parametrize("workers", [0, 1, 3])
def test_complete_inline_and_actual_spawn_rosters(workers):
    value = provider(workers=workers)
    result = complete(value)
    topology = result["configuration"]["topology"]
    assert len(topology["workers"]) == workers
    assert topology["max_concurrent_workers"] == 4
    assert sum(e["kind"] == "START" for e in result["evidence"]["records"]) == workers + 1
    assert len(result["observer_report"]["processes"]) == workers + 1
    assert result["evidence"]["provider_input"] == value
    for process in result["observer_report"]["role_phase_coverage"].values():
        assert set(process["aligned_complete_phases"]) == set(o.PHASES)


@pytest.mark.parametrize("rss,delta", [(30, -10240), (40, 0), (60, 20480)])
def test_independent_pid_rosters_compare_only_through_f2b1(rss, delta):
    left = complete()["observer_report"]
    right = complete(provider(run="candidate", offset=1000, rss=rss))["observer_report"]
    result = v.compare_verified_reports(left, right)
    envelope(result)
    assert result["outcome"] == v.COMPARABLE, result["reasons"]
    assert result[v.DELTA] == delta
    assert result["baseline"]["eligible"] and result["candidate"]["eligible"]


@pytest.mark.parametrize("change,code", [
    ("workers", "TOPOLOGY_MISMATCH"),
    ("pool", "TOPOLOGY_MISMATCH"), ("workload", "WORKLOAD_MISMATCH"),
    ("conditions", "CONDITIONS_MISMATCH"),
])
def test_semantic_changes_cannot_compare(change, code):
    left = provider()
    right = provider(run="candidate", offset=1000,
                     workers=2 if change == "workers" else 1)
    if change == "pool":
        right["configuration"]["topology"]["workers"][0]["pool"] = "other_pool"
    elif change == "workload":
        right["workload_id"] = "different"
    elif change == "conditions":
        right["conditions"]["modules"] = 3
    result = v.compare_verified_reports(complete(left)["observer_report"],
                                        complete(right)["observer_report"])
    envelope(result)
    assert result["outcome"] == v.NOT_COMPARABLE
    assert result[v.DELTA] is None
    assert {"side": "pair", "code": code} in result["reasons"]


def test_spawned_empty_roster_and_mode_change_cannot_supply_comparable_coverage():
    left = complete(provider(run="inline", workers=0))
    value = provider(run="spawned-unobserved", offset=1000, workers=0, mode="spawned")
    result = diagnostic(value, "ADAPTER_SPAWNED_WORKERS_UNOBSERVED", o.INCONCLUSIVE)
    assert result["provider_input"] == value
    comparison = v.compare_verified_reports(left["observer_report"], result["observer_report"])
    envelope(comparison)
    assert comparison["outcome"] == v.NOT_COMPARABLE
    assert comparison[v.DELTA] is None
    assert comparison["baseline"]["eligible"] is True
    assert comparison["candidate"]["eligible"] is False


def test_changed_per_parent_distribution_does_not_compare():
    def two_parents(run, offset, redistribute):
        value = provider(run=run, offset=offset, workers=2)
        top = value["configuration"]["topology"]
        extra = [101 + offset, 11 + offset]
        top["parents"].append(extra)
        value["events"].insert(1, {"kind": "START", "identity": extra.copy(),
                                    "role": "parent", "ppid": 1,
                                    "phase": o.PHASES[0], "time_ns": 0})
        if redistribute:
            worker = top["workers"][0]
            worker["parent"] = extra.copy()
            for e in value["events"]:
                if e["kind"] == "START" and e["identity"] == worker["identity"]:
                    e["ppid"] = extra[0]
            for f in frames(value):
                f["readings"][1] = reading(worker["identity"], extra[0],
                                           f["readings"][1]["phase"], f["time_ns"],
                                           final=f["readings"][1]["final"])
        events = []
        for e in value["events"]:
            if e["kind"] == "FRAME":
                phase = e["readings"][0]["phase"]
                if phase != o.PHASES[0]:
                    events.append({"kind": "PHASE", "identity": extra.copy(),
                                   "phase": phase, "time_ns": e["time_ns"] - 9})
                e["expected_live"].append(extra.copy())
                e["readings"].append(reading(extra, 1, phase, e["time_ns"], rss=20,
                                              final=e["readings"][0]["final"]))
            events.append(e)
        events.append({"kind": "EXIT", "identity": extra.copy(),
                       "time_ns": 10 * len(o.PHASES)})
        value["events"] = events
        value["holder_coverage"] += [{"identity": extra.copy(), "phase": phase,
                                       "events_complete": True} for phase in o.PHASES]
        return decorate(value)

    left = complete(two_parents("baseline", 0, False))["observer_report"]
    right = complete(two_parents("candidate", 1000, True))["observer_report"]
    result = v.compare_verified_reports(left, right)
    envelope(result)
    assert result["reasons"] == [{"side": "pair", "code": "TOPOLOGY_MISMATCH"}]
    assert result[v.DELTA] is None


def pool_lifetimes(reused_pid=False):
    value = provider(workers=2, phases=("producer", "attribution"))
    top = value["configuration"]["topology"]
    parent = top["parents"][0]
    first, second = top["workers"]
    first["pool"], second["pool"] = "producer", "attribution"
    top["max_concurrent_workers"] = 1
    if reused_pid:
        second["identity"][0] = first["identity"][0]
    p, w1, w2 = (parent, 1, "parent"), (first["identity"], parent[0], "worker"), (second["identity"], parent[0], "worker")
    phase2 = "producer" if reused_pid else "attribution"
    value["events"] = [
        {"kind": "START", "identity": parent.copy(), "role": "parent", "ppid": 1,
         "phase": "producer", "time_ns": 0},
        {"kind": "START", "identity": w1[0].copy(), "role": "worker", "ppid": parent[0],
         "phase": "producer", "time_ns": 1},
        frame([p, w1], "producer", 10, final=True),
        {"kind": "EXIT", "identity": w1[0].copy(), "time_ns": 10},
        {"kind": "START", "identity": w2[0].copy(), "role": "worker", "ppid": parent[0],
         "phase": phase2, "time_ns": 11},
    ]
    if not reused_pid:
        value["events"].append({"kind": "PHASE", "identity": parent.copy(),
                                "phase": phase2, "time_ns": 11})
    value["events"] += [frame([p, w2], phase2, 20, final=True),
                        {"kind": "EXIT", "identity": w2[0].copy(), "time_ns": 20},
                        {"kind": "EXIT", "identity": parent.copy(), "time_ns": 20}]
    if reused_pid:
        value["configuration"]["required_phases"] = ["producer"]
    value["holder_coverage"] = [
        {"identity": ident.copy(), "phase": phase, "events_complete": True}
        for ident in (parent, w1[0], w2[0])
        for phase in value["configuration"]["required_phases"]]
    # Explicit holder lifetimes within each pool, attributed to CREATE phase.
    for identity, phase, create_ns, release_ns in ((w1[0], "producer", 2, 3),
                                                  (w2[0], phase2, 12, 13)):
        additions = [
            {"kind": "CREATE", "identity": identity.copy(), "phase": phase,
             "time_ns": create_ns, "slots": 2, "holder_id": "pool-holder",
             "initialization_succeeded": True},
            {"kind": "RELEASE", "identity": identity.copy(), "phase": phase,
             "time_ns": release_ns, "slots": 2, "holder_id": "pool-holder",
             "ownership_termination": {"explicit": True, "basis": "explicit_ownership_transfer",
                                       "evidence_id": "injected-transfer"}},
        ]
        index = next(i for i, e in enumerate(value["events"]) if e["time_ns"] > create_ns)
        value["events"][index:index] = additions
    return decorate(value)


def test_distinct_producer_attribution_lifecycles_keep_uncovered_phases():
    value = pool_lifetimes()
    result = mapped(value)
    assert codes(result) == {"MISSING_PHASE_COVERAGE"}
    assert result["outcome"] == o.INCONCLUSIVE
    assert result["configuration"]["topology"]["max_concurrent_workers"] == 1
    holders = result["observer_report"]["holder_metrics"]
    for phase in ("producer", "attribution"):
        assert holders["cumulative_lifetimes_by_phase"][phase] == {"holders": 1, "slots": 2}
    assert [e["kind"] for e in result["evidence"]["records"]] == [e["kind"] for e in value["events"]]
    not_comparable(result)


def test_pid_reuse_with_increasing_starttime_preserves_both_lifetimes():
    result = complete(pool_lifetimes(reused_pid=True))
    workers = result["configuration"]["topology"]["workers"]
    assert workers[0]["identity"][0] == workers[1]["identity"][0]
    assert workers[0]["identity"][1] < workers[1]["identity"][1]
    assert len(result["observer_report"]["processes"]) == 3


@pytest.mark.parametrize("variant", ["smaller_start", "still_live", "stat_mismatch"])
def test_pid_reuse_anomalies(variant):
    value = pool_lifetimes(reused_pid=True)
    if variant == "smaller_start":
        old = value["configuration"]["topology"]["workers"][1]["identity"].copy()
        new = [old[0], 19]
        value["configuration"]["topology"]["workers"][1]["identity"] = new
        for item in value["events"] + value["holder_coverage"]:
            if item.get("identity") == old:
                item["identity"] = new.copy()
        for f in frames(value):
            f["expected_live"] = [new.copy() if x == old else x for x in f["expected_live"]]
            for r in f["readings"]:
                if r["identity"] == old:
                    r["identity"] = new.copy()
    elif variant == "still_live":
        first = value["configuration"]["topology"]["workers"][0]["identity"]
        value["events"] = [e for e in value["events"] if not (e["kind"] == "EXIT" and e["identity"] == first)]
        decorate(value)
    else:
        r = frames(value)[0]["readings"][1]
        r["stat"] = r["stat"].rsplit(" ", 1)[0] + " 999"
    result = mapped(value)
    assert "PID_REUSE_ANOMALY" in codes(result)
    assert result["outcome"] == o.INVALID
    not_comparable(result)


def test_equal_starttime_duplicate_identity_is_rejected_by_f2a():
    value = pool_lifetimes(reused_pid=True)
    top = value["configuration"]["topology"]
    top["workers"][1]["identity"] = top["workers"][0]["identity"].copy()
    assert "UNKNOWN_WORKER_TOPOLOGY" in codes(mapped(value))


@pytest.mark.parametrize("variant,code,outcome", [
    ("absent", "MISSING_PROCESS", o.INCONCLUSIVE),
    ("late", "UNEXPECTED_PROCESS", o.INVALID),
    ("late_not_expected", "INVALID_LIFECYCLE", o.INVALID),
    ("late_consistent", "MISSING_PHASE_COVERAGE", o.INCONCLUSIVE),
    ("unrostered", "UNKNOWN_WORKER_TOPOLOGY", o.INVALID),
])
def test_unobserved_and_late_workers(variant, code, outcome):
    value = provider()
    worker = value["configuration"]["topology"]["workers"][0]["identity"]
    if variant == "unrostered":
        value["configuration"]["topology"]["workers"] = []
        value["holder_coverage"] = [x for x in value["holder_coverage"] if x["identity"] != worker]
    elif variant == "absent":
        # Keep the declared roster and holder declarations, but consistently
        # supply no worker lifecycle events, expected-live entries or readings.
        value["events"] = [e for e in value["events"] if e.get("identity") != worker]
        for f in frames(value):
            f["expected_live"].remove(worker)
            f["readings"] = [r for r in f["readings"] if r["identity"] != worker]
    else:
        start = next(e for e in value["events"] if e["kind"] == "START" and e["role"] == "worker")
        value["events"].remove(start)
        start["time_ns"] = 10
        first = frames(value)[0]
        value["events"].insert(value["events"].index(first) + 1, start)
        if variant in ("late_not_expected", "late_consistent"):
            first["expected_live"].remove(worker)
        if variant == "late_consistent":
            first["readings"] = [r for r in first["readings"] if r["identity"] != worker]
    result = mapped(decorate(value))
    assert result["outcome"] == outcome
    assert code in codes(result)
    if variant == "absent":
        assert "MISSING_ROLE_COVERAGE" in codes(result)
        assert o.identity_key(worker) not in result["observer_report"]["processes"]
    elif variant == "late_consistent":
        assert codes(result) == {"MISSING_PHASE_COVERAGE"}
    not_comparable(result)


@pytest.mark.parametrize("variant", ["roster", "start"])
def test_inline_cannot_hide_observed_workers(variant):
    value = provider()
    value["configuration"]["topology"]["execution_mode"] = "inline"
    if variant == "start":
        value["configuration"]["topology"]["workers"] = []
    diagnostic(value, "ADAPTER_INLINE_WORKER")


@pytest.mark.parametrize("start,expected", [(5, "BOUNDED_SEQUENTIAL_READS"), (4, "EXCESSIVE_SKEW")])
def test_inclusive_skew_boundary(start, expected):
    value = provider()
    f = frames(value)[0]
    f["read_start_ns"] = start
    for r in f["readings"]:
        r["read_start_ns"] = start
        for bounds in r["file_read_bounds"].values():
            bounds["read_start_ns"] = start
    result = mapped(value)
    assert result["observer_report"]["sampled_aggregate"]["frames"][0]["alignment"] == expected
    if start == 5:
        assert result["outcome"] == o.COMPLETE
    else:
        assert "EXCESSIVE_READ_SKEW" in codes(result)
        not_comparable(result)


@pytest.mark.parametrize("variant", ["reversed", "outside_frame", "file_outside", "cgroup_future"])
def test_structurally_impossible_windows(variant):
    value = provider()
    f = frames(value)[0]
    if variant == "reversed":
        f["read_start_ns"], f["read_end_ns"] = 10, 9
    elif variant == "outside_frame":
        f["readings"][0]["read_start_ns"] = 7
    elif variant == "file_outside":
        f["readings"][0]["file_read_bounds"]["stat"]["read_start_ns"] = 7
    else:
        f["cgroup"]["time_ns"] = 11
    diagnostic(value, "INVALID_READ_WINDOW")


@pytest.mark.parametrize("variant", ["before_start", "before_phase", "after_capture"])
def test_f2a_read_window_semantics(variant):
    value = provider()
    f = frames(value)[0 if variant != "before_phase" else 1]
    r = f["readings"][1]
    if variant == "before_start":
        start, end = 0, 9
    elif variant == "before_phase":
        start, end = 10, 19
    else:
        # Valid proc and cgroup captures inside a frame envelope whose end
        # falsely follows the event timestamp: F2-A owns this classification.
        start, end = 8, 9
        f["read_end_ns"] = 11
    if variant != "after_capture":
        f["read_start_ns"] = start
        for bounds in r["file_read_bounds"].values():
            bounds["read_start_ns"] = start
    r["read_start_ns"], r["read_end_ns"] = start, end
    result = mapped(value)
    assert "INVALID_READ_WINDOW" in codes(result)
    assert result["outcome"] == o.INVALID


def test_absent_bounds_remain_unaligned_without_invented_windows():
    value = provider()
    f = frames(value)[0]
    f.pop("read_start_ns")
    f.pop("read_end_ns")
    for r in f["readings"]:
        r.pop("read_start_ns")
        r.pop("read_end_ns")
    result = diagnostic(value, "ALIGNMENT_NOT_ESTABLISHED", o.INCONCLUSIVE)
    assert result["provider_input"] == value
    not_comparable(result)


@pytest.mark.parametrize("where", ["frame", "proc", "cgroup"])
def test_each_capture_needs_its_own_envelope(where):
    value = provider()
    f = frames(value)[0]
    target = f if where == "frame" else f["readings"][0] if where == "proc" else f["cgroup"]
    target.pop("read_start_ns")
    target.pop("read_end_ns")
    result = diagnostic(value, "ALIGNMENT_NOT_ESTABLISHED", o.INCONCLUSIVE)
    assert result["provider_input"] == value
    not_comparable(result)


@pytest.mark.parametrize("variant", ["wall", "unit", "source", "event", "proc", "cgroup"])
def test_no_cross_origin_or_wall_clock_assumptions(variant):
    value = provider()
    if variant == "wall":
        value["clock"]["kind"] = "realtime"
    elif variant == "unit":
        value["clock"]["unit"] = "seconds"
    elif variant == "source":
        value["sources"][0]["clock_id"] = "other-boot"
    elif variant == "event":
        value["events"][0]["clock_id"] = "other-boot"
    else:
        item = frames(value)[0]["readings"][0] if variant == "proc" else frames(value)[0]["cgroup"]
        item["clock_id"] = "other-boot"
    diagnostic(value, "ADAPTER_CLOCK_INVALID")


@pytest.mark.parametrize("name", ["status", "stat"])
@pytest.mark.parametrize("failure", [False, True])
def test_missing_required_proc_text_differs_from_explicit_failed_read(name, failure):
    value = provider()
    r = frames(value)[0]["readings"][1]
    r.pop(name)
    if failure:
        r["read_failure"] = "ENOENT:" + name
    result = mapped(value)
    assert result["outcome"] == (o.INCONCLUSIVE if failure else o.INVALID)
    assert {"MISSING_PROCESS", "INCOMPLETE_FRAME_SET"} <= codes(result)
    if not failure:
        assert "MISSING_FIELD" in codes(result)
    assert result["evidence"]["provider_input"]["events"] == value["events"]
    not_comparable(result)


@pytest.mark.parametrize("variant,code", [
    ("malformed", "ADAPTER_CAPTURE_IDENTITY_INVALID"),
    ("missing", "ADAPTER_CAPTURE_IDENTITY_INVALID"),
    ("off_roster", "ADAPTER_FAILED_CAPTURE_NOT_ROSTERED"),
    ("not_expected", "ADAPTER_FAILED_CAPTURE_NOT_EXPECTED"),
    ("duplicate_success", "ADAPTER_DUPLICATE_CAPTURE_IDENTITY"),
    ("duplicate_failed", "ADAPTER_DUPLICATE_CAPTURE_IDENTITY"),
    ("duplicate_success_after_failed", "ADAPTER_DUPLICATE_CAPTURE_IDENTITY"),
])
def test_failed_capture_identity_cannot_disappear_or_supply_a_delta(variant, code):
    value = provider(run="failed-capture", offset=1000, rss=1)
    f = frames(value)[0]
    failed = f["readings"][1]
    failed["read_failure"] = "ESRCH"
    if variant == "malformed":
        failed["identity"] = [True, 20]
    elif variant == "missing":
        failed.pop("identity")
    elif variant == "off_roster":
        failed["identity"] = [9999, 9999]
        f["expected_live"].append(failed["identity"].copy())
    elif variant == "not_expected":
        f["expected_live"].remove(failed["identity"])
    elif variant == "duplicate_success":
        failed["identity"] = f["readings"][0]["identity"].copy()
    else:
        duplicate = copy.deepcopy(failed)
        if variant == "duplicate_success_after_failed":
            duplicate.pop("read_failure")
        f["readings"].append(duplicate)
        decorate(value)
    before = o.canonical_bytes(value)
    result = diagnostic(value, code)
    assert result["outcome"] != o.COMPLETE
    assert result["provider_input"] == value
    assert o.canonical_bytes(value) == before
    assert o.canonical_bytes(a.adapt(value)) == o.canonical_bytes(result)
    verification = v.verify_report(result["observer_report"])
    envelope(verification)
    assert verification["outcome"] == v.NOT_COMPARABLE
    assert verification[v.DELTA] is None
    not_comparable(result)


@pytest.mark.parametrize("variant", ["malformed", "missing", "duplicate"])
def test_successful_captures_get_the_same_identity_and_duplicate_checks(variant):
    value = provider()
    readings = frames(value)[0]["readings"]
    if variant == "malformed":
        readings[1]["identity"] = [True, 20]
    elif variant == "missing":
        readings[1].pop("identity")
    else:
        readings[1]["identity"] = readings[0]["identity"].copy()
    result = diagnostic(value, "ADAPTER_DUPLICATE_CAPTURE_IDENTITY" if variant == "duplicate"
                        else "ADAPTER_CAPTURE_IDENTITY_INVALID")
    assert result["provider_input"] == value
    not_comparable(result)


@pytest.mark.parametrize("gap", ["frame_bounds", "proc_bounds", "capture_sequence"])
@pytest.mark.parametrize("invalid_frame", [0, 1])
def test_failed_identity_invalidity_precedes_inconclusive_capture_gaps(gap, invalid_frame):
    value = provider()
    failed = frames(value)[invalid_frame]["readings"][1]
    failed["identity"] = [0, 20]
    failed["read_failure"] = "ESRCH"
    first = frames(value)[0]
    if gap == "capture_sequence":
        first["readings"][0]["capture_sequence"] = 1
    else:
        target = first if gap == "frame_bounds" else first["readings"][0]
        target.pop("read_start_ns")
        target.pop("read_end_ns")
    result = diagnostic(value, "ADAPTER_CAPTURE_IDENTITY_INVALID", o.INVALID)
    assert result["provider_input"] == value
    not_comparable(result)


@pytest.mark.parametrize("variant", ["missing", "malformed", "duplicate"])
def test_failed_capture_needs_checkable_expected_live(variant):
    value = provider()
    f = frames(value)[0]
    f["readings"][1]["read_failure"] = "ESRCH"
    if variant == "missing":
        f.pop("expected_live")
    elif variant == "malformed":
        f["expected_live"][0] = [False, 10]
    else:
        f["expected_live"].append(f["expected_live"][0].copy())
    result = diagnostic(value, "ADAPTER_EXPECTED_LIVE_INVALID")
    assert result["provider_input"] == value
    not_comparable(result)


def test_valid_failed_capture_retains_raw_provenance_and_missing_process():
    value = provider(run="valid-failed-read", offset=1000, rss=1)
    failed = frames(value)[0]["readings"][1]
    failed["read_failure"] = "ESRCH"
    result = mapped(value)
    assert result["outcome"] == o.INCONCLUSIVE
    assert {"MISSING_PROCESS", "INCOMPLETE_FRAME_SET"} <= codes(result)
    assert result["evidence"]["provider_input"] == value
    assert result["evidence"]["provider_input"]["events"] == value["events"]
    mapped_frame = next(e for e in result["evidence"]["records"] if e["kind"] == "FRAME")
    assert mapped_frame["expected_live"] == frames(value)[0]["expected_live"]
    assert all(r["identity"] != failed["identity"] for r in mapped_frame["readings"])
    not_comparable(result)


@pytest.mark.parametrize("null", [False, True])
def test_optional_smaps_absence_is_not_invalid(null):
    value = provider()
    for f in frames(value):
        for r in f["readings"]:
            if null:
                r["smaps_rollup"] = None
            else:
                r.pop("smaps_rollup")
            r["file_read_bounds"].pop("smaps_rollup")
    result = complete(value)
    assert all(f["sampled_smaps_rss_bytes"] is None
               for f in result["observer_report"]["sampled_aggregate"]["frames"])


def test_optional_smaps_bundle_failure_withholds_even_valid_required_text():
    value = provider()
    r = frames(value)[0]["readings"][1]
    assert type(r["status"]) is str and type(r["stat"]) is str
    r.pop("smaps_rollup")
    r["file_read_bounds"].pop("smaps_rollup")
    r["read_failure"] = "EACCES:smaps_rollup"
    result = mapped(value)
    assert result["outcome"] == o.INCONCLUSIVE
    assert {"MISSING_PROCESS", "INCOMPLETE_FRAME_SET"} <= codes(result)
    assert result["evidence"]["provider_input"] == value
    not_comparable(result)


@pytest.mark.parametrize("variant", ["absent", "failure", "null_text"])
def test_missing_cgroup_defers_to_f2a(variant):
    value = provider()
    f = frames(value)[0]
    if variant == "absent":
        f["cgroup"] = None
        decorate(value)
    elif variant == "failure":
        f["cgroup"]["read_failure"] = "EACCES"
    else:
        f["cgroup"]["memory_events"] = None
    result = mapped(value)
    assert result["outcome"] == o.INCONCLUSIVE
    assert "MISSING_CGROUP_DATA" in codes(result)
    not_comparable(result)


def test_disappearance_never_fabricates_worker_exit():
    value = provider()
    worker = value["configuration"]["topology"]["workers"][0]["identity"]
    value["events"] = [e for e in value["events"] if not (e["kind"] == "EXIT" and e["identity"] == worker)]
    for f in frames(value)[1:]:
        f["readings"][1]["read_failure"] = "ESRCH"
    decorate(value)
    result = mapped(value)
    assert {"INVALID_LIFECYCLE", "OPEN_PROCESS_LIFETIME", "MISSING_PROCESS"} <= codes(result)
    assert not any(e["kind"] == "EXIT" and e["identity"] == worker for e in result["evidence"]["records"])
    not_comparable(result)


@pytest.mark.parametrize("variant,code", [
    ("duplicate", "DUPLICATE_HOLDER"), ("unmatched", "INVALID_RELEASE"),
    ("cross_owner", "CROSS_PROCESS_RELEASE"), ("slots", "SLOT_COUNT_MISMATCH"),
])
def test_explicit_holder_contradictions_reuse_f2a(variant, code):
    value = provider()
    if variant == "duplicate":
        value["events"].insert(value["events"].index(event(value, "CREATE")), copy.deepcopy(event(value, "CREATE")))
        decorate(value)
    else:
        r = event(value, "RELEASE")
        if variant == "unmatched":
            r["holder_id"] = "unknown"
        elif variant == "cross_owner":
            r["identity"] = value["configuration"]["topology"]["workers"][0]["identity"].copy()
        else:
            r["slots"] = 4
    result = mapped(value)
    assert code in codes(result)
    assert result["outcome"] == o.INVALID
    not_comparable(result)


@pytest.mark.parametrize("success", [None, False, 1, "yes"])
def test_holder_create_requires_explicit_success(success):
    value = provider()
    event(value, "CREATE")["initialization_succeeded"] = success
    diagnostic(value, "ADAPTER_CREATE_UNCONFIRMED")


@pytest.mark.parametrize("slots", [None, True, -1, 1.5, "3"])
def test_adapter_create_slots_diagnostic_is_distinct_from_f2a_mismatch(slots):
    value = provider()
    event(value, "CREATE")["slots"] = slots
    result = diagnostic(value, "ADAPTER_CREATE_SLOTS_INVALID")
    assert result["provider_input"] == value
    not_comparable(result)


def test_unjustified_release_requires_a_known_owner_before_withholding():
    value = provider()
    release = event(value, "RELEASE")
    release.pop("ownership_termination")
    release["identity"] = [9999, 9999]
    result = diagnostic(value, "ADAPTER_RELEASE_OWNER_UNKNOWN")
    assert result["provider_input"] == value
    not_comparable(result)


def test_unjustified_unknown_holder_release_retains_inconclusive_limitation():
    value = provider()
    release = event(value, "RELEASE")
    release["holder_id"] = "never-created"
    release.pop("ownership_termination")
    result = mapped(value)
    assert result["outcome"] == o.INCONCLUSIVE
    assert {"OPEN_HOLDER_LIFETIME", "INCOMPLETE_HOLDER_COVERAGE"} <= codes(result)
    assert "INVALID_RELEASE" not in codes(result)
    assert result["evidence"]["provider_input"] == value
    assert result["evidence"]["withheld_events"] == [
        {"sequence": release["sequence"], "code": "ADAPTER_RELEASE_UNJUSTIFIED"}]
    not_comparable(result)


def test_holder_release_in_later_phase_keeps_create_phase_attribution():
    value = provider()
    release = event(value, "RELEASE")
    value["events"].remove(release)
    release["phase"] = o.PHASES[1]
    release["time_ns"] = 12
    index = value["events"].index(frames(value)[1])
    value["events"].insert(index, release)
    result = complete(decorate(value))
    holder = result["observer_report"]["holder_metrics"]["lifetimes"][0]
    assert holder["phase"] == o.PHASES[0]
    assert holder["release_ns"] == 12


@pytest.mark.parametrize("variant", ["not_explicit", "no_evidence_id"])
def test_release_basis_alone_does_not_establish_termination(variant):
    value = provider()
    termination = event(value, "RELEASE")["ownership_termination"]
    if variant == "not_explicit":
        termination["explicit"] = False
    else:
        termination["evidence_id"] = ""
    result = mapped(value)
    assert {"OPEN_HOLDER_LIFETIME", "INCOMPLETE_HOLDER_COVERAGE"} <= codes(result)
    not_comparable(result)


@pytest.mark.parametrize("basis", ["interval_end", "function_return", "frame", "process_exit", "gc", "weakref", "unknown", None])
def test_release_inference_never_closes_a_holder(basis):
    value = provider()
    r = event(value, "RELEASE")
    if basis is None:
        r.pop("ownership_termination")
    else:
        r["ownership_termination"]["basis"] = basis
    result = mapped(value)
    assert {"OPEN_HOLDER_LIFETIME", "INCOMPLETE_HOLDER_COVERAGE", "SEQUENCE_GAP",
            "DECLARED_COUNT_MISMATCH"} <= codes(result)
    assert result["outcome"] == o.INCONCLUSIVE
    assert not any(e["kind"] == "RELEASE" for e in result["evidence"]["records"])
    assert result["observer_report"]["holder_metrics"]["lifetimes"][0]["release_ns"] is None
    assert all(not item["events_complete"] for item in result["evidence"]["holder_coverage"]
               if item["identity"] == r["identity"])
    assert result["evidence"]["provider_input"] == value
    not_comparable(result)


def test_unobserved_release_and_partial_events_cannot_supply_negative_delta():
    value = provider(run="partial", offset=1000, rss=1)
    value["events"] = [e for e in value["events"] if e["kind"] != "RELEASE"]
    for declaration in value["holder_coverage"]:
        declaration["events_complete"] = False
    decorate(value)
    result = mapped(value)
    assert {"OPEN_HOLDER_LIFETIME", "INCOMPLETE_HOLDER_COVERAGE"} <= codes(result)
    not_comparable(result)


@pytest.mark.parametrize("variant,code", [("missing", "MISSING_PHASE_COVERAGE"), ("repeated", "DUPLICATE_RECORD")])
def test_phases_are_observed_and_never_completed_implicitly(variant, code):
    value = provider()
    change = event(value, "PHASE")
    if variant == "missing":
        value["events"].remove(change)
    else:
        value["events"].insert(value["events"].index(change), copy.deepcopy(change))
    decorate(value)
    result = mapped(value)
    assert code in codes(result)
    assert sum(e["kind"] == "PHASE" for e in result["evidence"]["records"]) == sum(e["kind"] == "PHASE" for e in value["events"])
    not_comparable(result)


@pytest.mark.parametrize("variant,code", [
    ("vm_swap", "SWAP_OBSERVED"), ("smaps_swap", "SWAP_OBSERVED"),
    ("oom", "OOM_OBSERVED"), ("oom_kill", "OOM_OBSERVED"),
    ("max", "CGROUP_LIMIT_EVENT"), ("decreasing", "INCONSISTENT_COUNTER"),
])
def test_contamination_and_counter_contradictions(variant, code):
    value = provider()
    if variant == "vm_swap":
        r = frames(value)[0]["readings"][0]
        r["status"] = r["status"].replace("VmSwap: 0", "VmSwap: 1")
    elif variant == "smaps_swap":
        frames(value)[0]["readings"][0]["smaps_rollup"] = "Rss: 20 kB\nSwap: 1 kB\n"
    else:
        for f in frames(value)[1:]:
            f["cgroup"]["memory_events"] = memory_events(**{variant if variant != "decreasing" else "high": 1})
        if variant == "decreasing":
            frames(value)[0]["cgroup"]["memory_events"] = memory_events(high=2)
    result = mapped(value)
    assert code in codes(result)
    assert result["outcome"] == (o.INVALID if variant == "decreasing" else o.INCONCLUSIVE)
    not_comparable(result)


@pytest.mark.parametrize("variant,code", [
    ("truncated", "EVIDENCE_TRUNCATED"), ("sequence", "SEQUENCE_GAP"),
    ("records", "DECLARED_COUNT_MISMATCH"), ("frames", "DECLARED_COUNT_MISMATCH"),
    ("final", "EXIT_WITHOUT_FINAL_OBSERVATION"), ("open", "OPEN_PROCESS_LIFETIME"),
    ("holder_coverage", "INCOMPLETE_HOLDER_COVERAGE"),
])
def test_incomplete_evidence_cannot_compare(variant, code):
    value = provider()
    if variant == "truncated":
        value["truncated"] = True
    elif variant == "sequence":
        for e in value["events"][2:]:
            e["sequence"] += 1
    elif variant in ("records", "frames"):
        value["declared_record_count" if variant == "records" else "declared_frame_count"] += 1
    elif variant == "final":
        frames(value)[-1]["readings"][0]["final"] = False
    elif variant == "open":
        value["events"].pop()
        value["declared_record_count"] -= 1
    else:
        value["holder_coverage"] = []
    result = mapped(value)
    assert code in codes(result)
    assert result["outcome"] == o.INCONCLUSIVE
    if variant == "sequence":
        assert [e["sequence"] for e in result["evidence"]["records"]] == [e["sequence"] for e in value["events"]]
    not_comparable(result)


@pytest.mark.parametrize("variant,code,outcome", [
    ("event_time", "OUT_OF_ORDER", o.INVALID), ("event_seq", "OUT_OF_ORDER", o.INVALID),
    ("capture_seq", "SEQUENCE_GAP", o.INCONCLUSIVE), ("capture_reverse", "OUT_OF_ORDER", o.INVALID),
    ("capture_time", "OUT_OF_ORDER", o.INVALID),
    ("bool_time", "ADAPTER_TIME_INVALID", o.INVALID), ("negative_time", "ADAPTER_TIME_INVALID", o.INVALID),
])
def test_invalid_sequences_and_timestamps(variant, code, outcome):
    value = provider()
    if variant == "event_time":
        event(value, "RELEASE")["time_ns"] = 1
    elif variant == "event_seq":
        value["events"][1]["sequence"] = 0
    elif variant == "capture_seq":
        frames(value)[0]["readings"][1]["capture_sequence"] += 1
    elif variant == "capture_reverse":
        frames(value)[0]["readings"][1]["capture_sequence"] = 0
    elif variant == "capture_time":
        r = frames(value)[0]["readings"][1]
        r["read_end_ns"] = 8
        for bounds in r["file_read_bounds"].values():
            bounds["read_end_ns"] = 8
    else:
        value["events"][0]["time_ns"] = True if variant == "bool_time" else -1
    diagnostic(value, code, outcome)


@pytest.mark.parametrize("field,text,code", [
    ("status", "garbage", "MALFORMED_INPUT"),
    ("status", "Pid: 100\nPPid: 1\nVmRSS: 2 MB\nVmHWM: 5 kB\nVmSwap: 0 kB", "INVALID_UNIT"),
    ("stat", "100 no delimiters", "MALFORMED_INPUT"),
    ("smaps_rollup", "Rss: no kB\nSwap: 0 kB", "MALFORMED_INPUT"),
])
def test_malformed_claimed_successful_proc_strings(field, text, code):
    value = provider()
    frames(value)[0]["readings"][0][field] = text
    result = mapped(value)
    assert result["outcome"] == o.INVALID
    assert code in codes(result)
    assert frames(result["evidence"]["provider_input"])[0]["readings"][0][field] == text


def test_malformed_cgroup_text_is_invalid_without_repair():
    value = provider()
    frames(value)[0]["cgroup"]["memory_events"] = "oom NaN\n"
    result = mapped(value)
    assert result["outcome"] == o.INVALID
    assert "MALFORMED_INPUT" in codes(result)


def test_valid_unicode_raw_text_round_trips_and_hwm_stays_separate():
    value = provider()
    for f in frames(value):
        for r in f["readings"]:
            r["status"] = r["status"].replace("Name: fake", "Name: bumi 🌏")
            r["stat"] = r["stat"].replace("fake process", "bumi (🌏) )")
    result = complete(value)
    assert result["evidence"]["provider_input"] == value
    report = result["observer_report"]
    assert set(report["per_process_hwm_bytes"].values()) == {500 * 1024}
    assert report["sampled_aggregate"]["max_rss_bytes"] == 60 * 1024
    assert all(p["observations"] for p in report["processes"].values())


class DictSubclass(dict):
    pass


@pytest.mark.parametrize("bad", [None, [], "not-an-object", 3, True,
                                object(), set(), (), DictSubclass()],
                         ids=["null", "list", "str", "int", "bool", "object", "set", "tuple", "subclass"])
def test_bad_provider_roots_never_raise(bad):
    diagnostic(bad)


@pytest.mark.parametrize("bad", [object(), (), float("nan"), float("inf"), -float("inf"),
                                {1: "key"}, "\ud800", {"\udfff": 1}],
                         ids=["object", "tuple", "nan", "inf", "neg_inf", "key", "surrogate_value", "surrogate_key"])
def test_unsafe_nested_values_never_echo_payload(bad):
    value = provider()
    value["conditions"]["bad"] = bad
    result = diagnostic(value)
    assert result["provider_input"] is None
    assert "bad" not in o.canonical_bytes(result).decode()


@pytest.mark.parametrize("variant", ["cycle", "depth", "integer", "text", "events", "readings", "sources"])
def test_bounded_input_caps_and_cycles(variant):
    value = provider()
    if variant == "cycle":
        value["conditions"]["recursive"] = value
    elif variant == "depth":
        child = value["conditions"]
        for _ in range(a.MAX_DEPTH + 1):
            child["deeper"] = {}
            child = child["deeper"]
    elif variant == "integer":
        value["conditions"]["large"] = 1 << a.MAX_INTEGER_BITS
    elif variant == "text":
        value["conditions"]["large"] = "x" * (a.MAX_TEXT_BYTES + 1)
    elif variant == "events":
        value["events"] = [value["events"][0]] * (a.MAX_EVENTS + 1)
    elif variant == "readings":
        frames(value)[0]["readings"] *= a.MAX_READINGS_PER_FRAME
    else:
        value["sources"] = [value["sources"][0]] * (a.MAX_SOURCES + 1)
    diagnostic(value, "ADAPTER_NON_JSON" if variant == "cycle" else "ADAPTER_CAP_EXCEEDED")


@pytest.mark.parametrize("variant", ["kind", "schema", "source", "source_kind", "metadata", "slot_bool", "count_bool", "start_method"])
def test_schema_and_provenance_fail_closed(variant):
    value = provider()
    if variant == "kind":
        value["input_kind"] = "LIVE"
    elif variant == "schema":
        value["schema"] = "unknown"
    elif variant == "source":
        value["events"][0]["source_id"] = "missing"
    elif variant == "source_kind":
        value["sources"][0]["kind"] = "fake_proc"
    elif variant == "metadata":
        value["events"][0]["metadata"] = []
    elif variant == "slot_bool":
        event(value, "CREATE")["slots"] = True
    elif variant == "count_bool":
        value["declared_record_count"] = True
        assert mapped(value)["outcome"] == o.INVALID
        return
    else:
        value["configuration"]["topology"]["start_method"] = "fork"
        assert "UNKNOWN_WORKER_TOPOLOGY" in codes(mapped(value))
        return
    diagnostic(value)


def test_determinism_mutation_immunity_and_independent_reconstruction():
    value = provider()
    before = o.canonical_bytes(value)
    first, second = complete(value), complete(value)
    assert o.canonical_bytes(first) == o.canonical_bytes(second)
    assert o.canonical_bytes(value) == before
    sealed_before = o.canonical_bytes(first)
    value["conditions"]["modules"] = 900
    frames(value)[0]["readings"][0]["status"] = "changed"
    value["sources"][0]["metadata"]["provider"] = "changed"
    assert o.canonical_bytes(first) == sealed_before


def test_mapped_records_do_not_alias_retained_provider_objects():
    result = complete()
    raw = result["evidence"]["provider_input"]
    before = o.canonical_bytes(raw)
    for record in result["evidence"]["records"]:
        record["metadata"]["event_id"] = "edited-mapping"
        if "identity" in record:
            record["identity"][0] = 9999
        if record["kind"] == "RELEASE":
            record["ownership_termination"]["evidence_id"] = "edited-mapping"
        if record["kind"] == "FRAME":
            record["expected_live"][0][0] = 9999
            record["cgroup"]["metadata"]["injected"] = False
            record["readings"][0]["status"] = "edited-mapping"
            record["readings"][0]["identity"][0] = 9999
            record["readings"][0]["file_read_bounds"]["stat"]["read_start_ns"] = 0
    assert o.canonical_bytes(raw) == before


def test_unexpected_reconcile_failure_is_sealed(monkeypatch):
    def fail(*args):
        raise RuntimeError("must never echo arbitrary exception text")

    monkeypatch.setattr(o, "reconcile", fail)
    result = diagnostic(provider(), "ADAPTER_RECONCILIATION_FAILED")
    assert "must never echo" not in o.canonical_bytes(result).decode()


def test_import_safety_and_no_live_io(monkeypatch):
    source = inspect.getsource(a)
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module)
        assert not (isinstance(node, ast.Name) and node.id == "__name__")
    assert imports == {"scripts.benchmarks"}
    assert not any(isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                   for node in tree.body)
    assert "engine.simulation" not in source
    assert "shading" not in source
    value = provider()
    expected = complete(value)
    real_import = builtins.__import__
    seen = []

    def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        assert name == "scripts.benchmarks"
        assert fromlist == ("rb_post3d_08p2e2_r2f_f2a_observer",)
        seen.append(name)
        return real_import(name, globals, locals, fromlist, level)

    def forbidden(*args, **kwargs):
        raise AssertionError("Live I/O, process or clock observation attempted")

    with monkeypatch.context() as patch:
        for target, name in ((builtins, "open"), (io, "open"), (os, "open"),
                             (os, "stat"), (os, "listdir"), (os, "scandir"),
                             (os, "getpid"), (os, "fork"), (os, "system"),
                             (subprocess, "Popen"), (subprocess, "run"),
                             (socket, "socket"), (time, "monotonic_ns"),
                             (time, "perf_counter"), (time, "time")):
            patch.setattr(target, name, forbidden)
        patch.setattr(builtins, "__import__", restricted_import)
        namespace = {}
        exec(compile(tree, "<fake-adapter>", "exec"), namespace)
        actual = namespace["adapt"](value)
        error = namespace["adapt"](None)
    assert seen == ["scripts.benchmarks"]
    assert o.canonical_bytes(actual) == o.canonical_bytes(expected)
    envelope(error)
    assert error["observer_report"] is None
