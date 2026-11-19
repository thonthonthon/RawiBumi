"""In-memory observer contracts only; no instruments or child processes."""

import ast
import builtins
import copy
import inspect
import json

import pytest

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2a_observer as o


P = [100, 10]
W = [200, 20]


def status(pid=100, ppid=1, rss=20, hwm=500, swap=0):
    return (f"Name:\tfake process\nPid: {pid}\nPPid: {ppid}\n"
            f"VmRSS: {rss} kB\nVmHWM: {hwm} kB\nVmSwap: {swap} kB\n")


def stat(pid=100, ppid=1, start=10, comm="fake (with ) spaces))"):
    tail = ["S"] + ["0"] * 19
    tail[1] = str(ppid)
    tail[5] = "-1"  # field 8 tpgid is legitimately negative
    for number in (16, 17, 18, 19):
        tail[number - 3] = "-2"
    tail[19] = str(start)
    return f"{pid} ({comm}) " + " ".join(tail)


def events(**changes):
    counters = dict(low=0, high=0, max=0, oom=0, oom_kill=0)
    counters.update(changes)
    return "".join(f"{key} {value}\n" for key, value in counters.items())


def config():
    return {"max_read_skew_ns": 5, "max_frame_gap_ns": 100,
            "required_phases": ["producer"],
            "topology": {"parents": [P.copy()], "workers": [{"identity": W.copy(), "parent": P.copy()}],
                         "max_concurrent_workers": 2, "start_method": "spawn"}}


def start(ident, role, time=0, ppid=1, name="producer"):
    return {"kind": "START", "time_ns": time, "identity": ident.copy(), "role": role,
            "ppid": ppid, "phase": name}


def reading(ident, ppid, rss=20, hwm=500, time=10, final=True, name="producer"):
    return {"identity": ident.copy(), "phase": name,
            "status": status(ident[0], ppid, rss, hwm),
            "stat": stat(ident[0], ppid, ident[1]),
            "smaps_rollup": f"00100000-00200000 ---p 00000000 00:00 0 [rollup]\nRss: {rss} kB\nSwap: 0 kB\n",
            "read_start_ns": time - 2, "read_end_ns": time - 1, "final": final}


def frame(time=10, rss=40, identities=None):
    supplied = identities if identities is not None else [(P, 1, 20), (W, 100, rss)]
    return {"kind": "FRAME", "time_ns": time,
            "expected_live": [ident.copy() for ident, _, _ in supplied],
            "readings": [reading(ident, ppid, amount, time=time) for ident, ppid, amount in supplied],
            "cgroup": {"source_id": "fake-cgroup", "time_ns": time, "memory_events": events()}}


def exit_record(ident, time=10):
    return {"kind": "EXIT", "time_ns": time, "identity": ident.copy()}


def holder(kind, ident=P, hid="h1", slots=3, time=2, name="producer"):
    return {"kind": kind, "time_ns": time, "identity": ident.copy(), "holder_id": hid,
            "slots": slots, "phase": name}


def data(records=None, cfg=None, run="baseline"):
    cfg = config() if cfg is None else cfg
    records = ([start(P, "parent"), start(W, "worker", 1, 100), frame(),
                exit_record(W), exit_record(P)] if records is None else records)
    records = copy.deepcopy(records)
    for seq, record in enumerate(records):
        record["sequence"] = seq
    identities = cfg["topology"]["parents"] + [item["identity"] for item in cfg["topology"]["workers"]]
    return {"input_id": "fake-" + run, "workload_id": "fake-workload", "independent_run_id": run,
            "conditions": {"modules": 2, "cache_state": "artificial", "intervals": 1},
            "records": records, "declared_record_count": len(records),
            "declared_frame_count": sum(record["kind"] == "FRAME" for record in records),
            "truncated": False,
            "holder_coverage": [{"identity": ident.copy(), "phase": name, "events_complete": True}
                                for ident in identities for name in cfg["required_phases"]]}


def result(evidence=None, cfg=None):
    return o.reconcile(config() if cfg is None else cfg, data() if evidence is None else evidence)


def codes(report):
    return {item["code"] for item in report["reasons"]}


def outcome(report, expected, code=None):
    assert report["outcome"] == expected
    if code is not None:
        assert code in codes(report)
        assert o.REASON_CLASSES[code] == expected or expected == o.INVALID
    assert report["production_memory_qualification"] == "INCONCLUSIVE"
    assert report["production_chronological_peak"] == "NOT_OBSERVED"
    assert o.verify_integrity(report)


def parser_error(parser, text, code):
    with pytest.raises(o.EvidenceError) as error:
        parser(text)
    assert error.value.code == code
    assert error.value.outcome == o.INVALID


def test_complete_fake_run_and_units():
    report = result()
    outcome(report, o.COMPLETE)
    assert report["reasons"] == []
    assert report["coverage_complete"] is True
    assert report["sampled_aggregate"]["max_rss_bytes"] == 60 * 1024
    assert report["sampled_aggregate"]["frames"][0]["sampled_smaps_rss_bytes"] == 60 * 1024
    assert report["per_process_hwm_bytes"] == {"100:10": 500 * 1024, "200:20": 500 * 1024}
    assert o.parse_status(status())["VmRSS"] == 20 * 1024
    assert o.parse_memory_events(events(high=7))["high"] == 7


@pytest.mark.parametrize("name", ["worker 12 kB", "proc_kB"])
def test_status_names_ending_in_kb_are_metadata(name):
    supplied = status().replace("fake process", name)
    assert o.parse_status(supplied)["VmRSS"] == 20 * 1024
    evidence = data()
    evidence["records"][2]["readings"][0]["status"] = supplied
    report = result(evidence)
    outcome(report, o.COMPLETE)
    assert report["sampled_aggregate"]["max_rss_bytes"] == 60 * 1024
    assert report["raw_supplied_observations"]["records"][2]["readings"][0]["status"] == supplied


@pytest.mark.parametrize("change,code", [
    (lambda text: text.replace("VmRSS: 20 kB\n", ""), "MISSING_FIELD"),
    (lambda text: text + "VmRSS: 20 kB\n", "DUPLICATE_FIELD"),
    (lambda text: text.replace("20 kB", "20 MB"), "INVALID_UNIT"),
    (lambda text: text.replace("20 kB", "20"), "INVALID_UNIT"),
    (lambda text: text.replace("20 kB", "1.5 kB"), "MALFORMED_INPUT"),
    (lambda text: text.replace("20 kB", "-1 kB"), "NEGATIVE_FIELD"),
    (lambda text: text.replace("VmRSS:", "VmRSS"), "MALFORMED_INPUT"),
    (lambda text: text.replace("500 kB", "1 kB"), "INCONSISTENT_COUNTER"),
    (lambda text: text.replace("Pid: 100", "Pid: -1"), "NEGATIVE_FIELD"),
])
def test_status_rejections(change, code):
    parser_error(o.parse_status, change(status()), code)


@pytest.mark.parametrize("name", ["VmRSS", "VmHWM", "VmSwap", "Pid", "PPid"])
def test_every_required_status_field_must_be_present(name):
    supplied = "\n".join(line for line in status().splitlines() if not line.startswith(name + ":"))
    parser_error(o.parse_status, supplied, "MISSING_FIELD")


@pytest.mark.parametrize("comm", ["plain", "contains spaces", "nested (comm)", "a)b)c))", ") ("])
def test_stat_uses_final_closing_parenthesis_and_field_22(comm):
    parsed = o.parse_stat(stat(comm=comm, start=123456))
    assert parsed == {"pid": 100, "comm": comm, "state": "S", "ppid": 1, "starttime_ticks": 123456}


@pytest.mark.parametrize("supplied,code", [
    (stat().rsplit(" ", 1)[0], "MISSING_FIELD"),
    (stat(start="nope"), "MALFORMED_INPUT"),
    (stat(start=-1), "NEGATIVE_FIELD"),
    (stat(pid=-1), "NEGATIVE_FIELD"),
    (stat(ppid=-1), "NEGATIVE_FIELD"),
    ("100 missing parentheses", "MALFORMED_INPUT"),
    (stat().replace(") S ", ")S "), "MALFORMED_INPUT"),
])
def test_stat_rejections(supplied, code):
    parser_error(o.parse_stat, supplied, code)


def test_smaps_header_conversion_and_unknown_kib_fields():
    parsed = o.parse_smaps_rollup("001000-002000 ---p 00000000 00:00 0 [rollup]\nRss: 42 kB\nSwap: 0 kB\nPss: 19 kB\n")
    assert parsed == {"Rss": 42 * 1024, "Swap": 0, "Pss": 19 * 1024}


@pytest.mark.parametrize("supplied,code", [
    ("Rss: 1 kB\n", "MISSING_FIELD"),
    ("Rss: 1 kB\nSwap: 0 kB\nRss: 2 kB", "DUPLICATE_FIELD"),
    ("Rss: -1 kB\nSwap: 0 kB", "NEGATIVE_FIELD"),
    ("Rss: nope kB\nSwap: 0 kB", "MALFORMED_INPUT"),
    ("Rss: 1 KB\nSwap: 0 kB", "INVALID_UNIT"),
])
def test_smaps_rejections(supplied, code):
    parser_error(o.parse_smaps_rollup, supplied, code)


@pytest.mark.parametrize("supplied,code", [
    (events().replace("low 0\n", ""), "MISSING_FIELD"),
    (events() + "oom 0\n", "DUPLICATE_FIELD"),
    (events(oom=-1), "NEGATIVE_FIELD"),
    (events(oom="x"), "MALFORMED_INPUT"),
    (events() + "invalid three fields\n", "MALFORMED_INPUT"),
])
def test_memory_events_rejections(supplied, code):
    parser_error(o.parse_memory_events, supplied, code)


def test_optional_data_stays_absent():
    assert o.parse_memory_events(None) is None
    assert "oom_group_kill" not in o.parse_memory_events(events())
    assert o.parse_memory_events(events(future_counter=9))["future_counter"] == 9
    evidence = data()
    evidence["records"][2]["cgroup"] = {"source_id": "fake", "time_ns": 10, "memory_events": None}
    evidence["records"][2]["readings"][0].pop("smaps_rollup")
    report = result(evidence)
    outcome(report, o.INCONCLUSIVE, "MISSING_CGROUP_DATA")
    assert report["cgroup_observations"][0]["memory_events"] is None
    assert report["sampled_aggregate"]["max_rss_bytes"] == 60 * 1024
    assert report["sampled_aggregate"]["frames"][0]["sampled_smaps_rss_bytes"] is None
    assert report["processes"]["100:10"]["observations"][0]["smaps_rollup"] is None
    evidence["records"][2].pop("cgroup")
    outcome(result(evidence), o.INCONCLUSIVE, "MISSING_CGROUP_DATA")


@pytest.mark.parametrize("path,value,code", [
    ((2, "readings", 0, "stat"), stat(start=11), "PID_REUSE_ANOMALY"),
    ((2, "readings", 0, "stat"), stat(pid=101), "IDENTITY_CONTRADICTION"),
    ((2, "readings", 0, "status"), status(pid=101), "IDENTITY_CONTRADICTION"),
    ((2, "readings", 0, "stat"), stat(ppid=2), "IDENTITY_CONTRADICTION"),
    ((2, "readings", 0, "status"), status(ppid=2), "IDENTITY_CONTRADICTION"),
    ((1, "role"), "parent", "IDENTITY_CONTRADICTION"),
    ((1, "ppid"), 999, "IDENTITY_CONTRADICTION"),
    ((1, "time_ns"), -1, "NEGATIVE_FIELD"),
    ((1, "time_ns"), True, "MALFORMED_INPUT"),
    ((2, "readings", 0, "phase"), "unknown", "INVALID_PHASE"),
])
def test_identity_and_input_contradictions(path, value, code):
    evidence = data()
    target = evidence["records"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    outcome(result(evidence), o.INVALID, code)


@pytest.mark.parametrize("record,code", [
    (start(P, "parent", 2), "DUPLICATE_RECORD"),
    ({"kind": "PHASE", "identity": P, "time_ns": 2, "phase": "producer"}, "DUPLICATE_RECORD"),
    ({"kind": "PHASE", "identity": P, "time_ns": 2, "phase": "attribution", "role": "worker"}, "IDENTITY_CONTRADICTION"),
    ({"kind": "PHASE", "identity": P, "time_ns": 2, "phase": "attribution", "ppid": 2}, "IDENTITY_CONTRADICTION"),
    (exit_record([999, 999], 2), "INVALID_LIFECYCLE"),
])
def test_lifecycle_misuse(record, code):
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), record])
    outcome(result(evidence), o.INVALID, code)


def test_readings_before_start_after_exit_and_unexpected_helpers():
    evidence = data([start(P, "parent"), frame(10)])
    outcome(result(evidence), o.INVALID, "UNEXPECTED_PROCESS")
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), frame(), exit_record(W), frame(20)])
    outcome(result(evidence), o.INVALID, "UNEXPECTED_PROCESS")
    evidence = data()
    evidence["records"][2]["readings"].append(reading([999, 90], 100))
    outcome(result(evidence), o.INVALID, "INVALID_LIFECYCLE")


def test_live_worker_reading_omitted_from_expected_live_withholds_aggregate():
    evidence = data()
    evidence["records"][2]["expected_live"] = [P.copy()]
    report = result(evidence)
    outcome(report, o.INVALID, "UNEXPECTED_PROCESS")
    assert "MISSING_PROCESS" in codes(report)
    sampled = report["sampled_aggregate"]
    assert sampled["max_rss_bytes"] is None
    assert sampled["frames"][0]["sampled_rss_bytes"] is None
    assert sampled["frames"][0]["complete"] is False
    assert [item["identity"] for item in sampled["frames"][0]["valid_readings"]] == ["100:10"]
    assert report["processes"]["100:10"]["observations"][0]["status"]["VmRSS"] == 20 * 1024


def test_nonoverlapping_pid_reuse_is_distinct_and_hwm_is_never_summed():
    replacement = [200, 21]
    cfg = config()
    cfg["topology"]["workers"].append({"identity": replacement, "parent": P})
    second = frame(20, identities=[(P, 1, 20), (replacement, 100, 50)])
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), frame(), exit_record(W),
                     start(replacement, "worker", 11, 100), second, exit_record(replacement, 20), exit_record(P, 20)], cfg)
    report = result(evidence, cfg)
    outcome(report, o.COMPLETE)
    assert report["sampled_aggregate"]["max_rss_bytes"] == 70 * 1024
    assert set(report["per_process_hwm_bytes"]) == {"100:10", "200:20", "200:21"}
    assert report["per_process_hwm_bytes"]["200:20"] == 500 * 1024
    assert report["per_process_hwm_bytes"]["200:21"] == 500 * 1024
    # Only per-lifetime HWM is present. No aggregate or peak field contains HWM.
    assert not any("hwm" in name.lower() for name in report["sampled_aggregate"])
    assert "sum_hwm" not in json.dumps(report).lower()
    assert "chronological_peak_bytes" not in json.dumps(report)
    assert report["processes"]["200:20"]["exit_ns"] == 10
    assert report["processes"]["200:21"]["start_ns"] == 11


def test_overlapping_pid_reuse_is_invalid():
    cfg = config()
    cfg["topology"]["workers"].append({"identity": [200, 21], "parent": P})
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), start([200, 21], "worker", 2, 100)], cfg)
    outcome(result(evidence, cfg), o.INVALID, "PID_REUSE_ANOMALY")


def test_multiple_parents_and_overlapping_workers():
    p2, w2 = [101, 11], [201, 21]
    cfg = config()
    cfg["topology"]["parents"].append(p2)
    cfg["topology"]["workers"].append({"identity": w2, "parent": p2})
    evidence = data([start(P, "parent"), start(p2, "parent"), start(W, "worker", 1, 100),
                     start(w2, "worker", 1, 101),
                     frame(10, identities=[(P, 1, 20), (p2, 1, 30), (W, 100, 40), (w2, 101, 50)]),
                     exit_record(W), exit_record(w2), exit_record(P), exit_record(p2)], cfg)
    report = result(evidence, cfg)
    outcome(report, o.COMPLETE)
    assert report["sampled_aggregate"]["max_rss_bytes"] == 140 * 1024
    assert [value["role"] for value in report["processes"].values()].count("parent") == 2


@pytest.mark.parametrize("change,code", [
    (lambda cfg: cfg["topology"].update(start_method="fork"), "UNKNOWN_WORKER_TOPOLOGY"),
    (lambda cfg: cfg["topology"].update(max_concurrent_workers=0), "UNKNOWN_WORKER_TOPOLOGY"),
    (lambda cfg: cfg["topology"]["parents"].append(P), "UNKNOWN_WORKER_TOPOLOGY"),
    (lambda cfg: cfg["topology"]["workers"][0].update(parent=[999, 0]), "UNKNOWN_WORKER_TOPOLOGY"),
    (lambda cfg: cfg.pop("max_read_skew_ns"), "MISSING_FIELD"),
    (lambda cfg: cfg.update(max_frame_gap_ns=True), "MALFORMED_INPUT"),
    (lambda cfg: cfg.update(required_phases=["unknown"]), "INVALID_PHASE"),
])
def test_invalid_configuration(change, code):
    cfg = config()
    change(cfg)
    outcome(result(data(), cfg), o.INVALID, code)


def test_worker_concurrency_declaration_and_parent_exit_order():
    cfg = config()
    cfg["topology"]["max_concurrent_workers"] = 1
    cfg["topology"]["workers"].append({"identity": [201, 21], "parent": P})
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), start([201, 21], "worker", 2, 100)], cfg)
    outcome(result(evidence, cfg), o.INVALID, "UNKNOWN_WORKER_TOPOLOGY")
    outcome(result(data([start(W, "worker", 0, 100)])), o.INVALID, "INVALID_LIFECYCLE")
    outcome(result(data([start(P, "parent"), start(W, "worker", 1, 100), exit_record(P, 2)])), o.INVALID, "INVALID_LIFECYCLE")


@pytest.mark.parametrize("omit_expected", [False, True])
def test_missing_worker_withholds_aggregate_and_preserves_parent(omit_expected):
    evidence = data()
    evidence["records"][2]["readings"].pop()
    if omit_expected:
        evidence["records"][2]["expected_live"].pop()
    report = result(evidence)
    outcome(report, o.INCONCLUSIVE, "MISSING_PROCESS")
    assert report["sampled_aggregate"]["max_rss_bytes"] is None
    assert report["processes"]["100:10"]["observations"][0]["status"]["VmRSS"] == 20 * 1024
    assert report["per_process_hwm_bytes"]["100:10"] == 500 * 1024
    assert "INCOMPLETE_FRAME_SET" in codes(report)
    assert "EXIT_WITHOUT_FINAL_OBSERVATION" in codes(report)


@pytest.mark.parametrize("kind,code,expected", [
    ("no_bounds", "ALIGNMENT_NOT_ESTABLISHED", o.INCONCLUSIVE),
    ("skew", "EXCESSIVE_READ_SKEW", o.INCONCLUSIVE),
    ("backwards", "INVALID_READ_WINDOW", o.INVALID),
    ("future", "INVALID_READ_WINDOW", o.INVALID),
    ("predates_start", "INVALID_READ_WINDOW", o.INVALID),
    ("one_bound", "MALFORMED_INPUT", o.INVALID),
])
def test_alignment_failures_preserve_per_process_data(kind, code, expected):
    evidence = data()
    readings = evidence["records"][2]["readings"]
    if kind == "no_bounds":
        for item in readings:
            item.pop("read_start_ns")
            item.pop("read_end_ns")
    elif kind == "skew":
        readings[0]["read_start_ns"] = 0
    elif kind == "backwards":
        readings[0]["read_end_ns"] = 7
    elif kind == "future":
        readings[0]["read_end_ns"] = 11
    elif kind == "predates_start":
        readings[1]["read_start_ns"] = 0
    else:
        readings[0].pop("read_end_ns")
    report = result(evidence)
    outcome(report, expected, code)
    assert report["sampled_aggregate"]["max_rss_bytes"] is None
    assert len(report["sampled_aggregate"]["frames"][0]["valid_readings"]) == 2


def test_frame_envelope_can_bound_sequential_reads():
    evidence = data()
    supplied = evidence["records"][2]
    supplied.update(read_start_ns=8, read_end_ns=10)
    for item in supplied["readings"]:
        item.pop("read_start_ns")
        item.pop("read_end_ns")
    report = result(evidence)
    outcome(report, o.COMPLETE)
    observed = report["sampled_aggregate"]["frames"][0]
    assert observed["alignment"] == "BOUNDED_SEQUENTIAL_READS"
    assert observed["read_skew_ns"] == 2
    assert observed["capture_age_ns"] == 2
    supplied["readings"][0].update(read_start_ns=7, read_end_ns=9)
    outcome(result(evidence), o.INVALID, "INVALID_READ_WINDOW")


def test_invalid_frame_envelope_preserves_process_data():
    evidence = data()
    evidence["records"][2].update(read_start_ns=10, read_end_ns=8)
    report = result(evidence)
    outcome(report, o.INVALID, "INVALID_READ_WINDOW")
    assert len(report["sampled_aggregate"]["frames"][0]["valid_readings"]) == 2
    assert report["sampled_aggregate"]["max_rss_bytes"] is None


@pytest.mark.parametrize("which", ["expected_live", "readings"])
def test_duplicate_processes_fail_closed(which):
    evidence = data()
    supplied = evidence["records"][2][which]
    supplied.append(copy.deepcopy(supplied[0]))
    report = result(evidence)
    outcome(report, o.INVALID, "DUPLICATE_RECORD")
    assert report["sampled_aggregate"]["max_rss_bytes"] is None


def test_frame_order_record_order_and_gaps():
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), frame(), frame(), exit_record(W), exit_record(P)])
    outcome(result(evidence), o.INVALID, "OUT_OF_ORDER")
    evidence = data()
    evidence["records"][2]["time_ns"] = 0
    outcome(result(evidence), o.INVALID, "OUT_OF_ORDER")
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), frame(), frame(200), exit_record(W, 200), exit_record(P, 200)])
    outcome(result(evidence), o.INCONCLUSIVE, "SAMPLE_GAP")
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), frame(200), exit_record(W, 200), exit_record(P, 200)])
    outcome(result(evidence), o.INCONCLUSIVE, "SAMPLE_GAP")
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), frame(), exit_record(W, 200), exit_record(P, 200)])
    outcome(result(evidence), o.INCONCLUSIVE, "SAMPLE_GAP")


def test_final_observation_requires_explicit_final_aligned_complete_frame():
    evidence = data()
    evidence["records"][2]["readings"][1]["final"] = False
    outcome(result(evidence), o.INCONCLUSIVE, "EXIT_WITHOUT_FINAL_OBSERVATION")
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), frame(), exit_record(W, 11), exit_record(P, 11)])
    outcome(result(evidence), o.INCONCLUSIVE, "EXIT_WITHOUT_FINAL_OBSERVATION")


@pytest.mark.parametrize("indication", ["status_swap", "smaps_swap", "oom", "oom_kill", "oom_group_kill", "max"])
def test_swap_and_oom_fail_closed(indication):
    evidence = data()
    supplied = evidence["records"][2]
    if indication == "status_swap":
        supplied["readings"][0]["status"] = status(swap=1)
    elif indication == "smaps_swap":
        supplied["readings"][0]["smaps_rollup"] = "Rss: 20 kB\nSwap: 1 kB\n"
    else:
        supplied["cgroup"]["memory_events"] = events(**{indication: 1})
    code = "SWAP_OBSERVED" if indication.endswith("swap") else "CGROUP_LIMIT_EVENT" if indication == "max" else "OOM_OBSERVED"
    report = result(evidence)
    outcome(report, o.INCONCLUSIVE, code)
    # Contamination disqualifies the evidence, but does not erase the valid sample.
    assert report["sampled_aggregate"]["max_rss_bytes"] == 60 * 1024


def test_pressure_counters_are_separate_from_rss_and_keep_source_time():
    evidence = data()
    supplied = evidence["records"][2]["cgroup"]
    supplied.update(time_ns=7, memory_events=events(high=4, low=5))
    report = result(evidence)
    outcome(report, o.COMPLETE)
    assert report["cgroup_observations"][0]["time_ns"] == 7
    assert report["cgroup_observations"][0]["memory_events"]["high"] == 4
    assert report["sampled_aggregate"]["max_rss_bytes"] == 60 * 1024


@pytest.mark.parametrize("counter", ["hwm", "cgroup", "optional_counter"])
def test_decreasing_counters_are_invalid(counter):
    first, second = frame(), frame(20)
    if counter == "hwm":
        second["readings"][0]["status"] = status(hwm=400)
    elif counter == "cgroup":
        first["cgroup"]["memory_events"] = events(high=1)
    else:
        first["cgroup"]["memory_events"] = events(oom_group_kill=0)
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), first, second, exit_record(W, 20), exit_record(P, 20)])
    outcome(result(evidence), o.INVALID, "INCONSISTENT_COUNTER")


def test_cgroup_timestamps_are_ordered_per_source_and_never_future():
    first, second = frame(), frame(20)
    second["cgroup"]["time_ns"] = 10
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), first, second])
    outcome(result(evidence), o.INVALID, "OUT_OF_ORDER")
    evidence = data()
    evidence["records"][2]["cgroup"]["time_ns"] = 11
    outcome(result(evidence), o.INVALID, "INVALID_READ_WINDOW")


@pytest.mark.parametrize("records,code", [
    ([holder("CREATE"), holder("CREATE")], "DUPLICATE_HOLDER"),
    ([holder("CREATE"), holder("RELEASE"), holder("RELEASE")], "INVALID_RELEASE"),
    ([holder("RELEASE")], "INVALID_RELEASE"),
    ([holder("CREATE"), holder("RELEASE", W)], "CROSS_PROCESS_RELEASE"),
    ([holder("CREATE", slots=-1)], "NEGATIVE_FIELD"),
    ([holder("CREATE", slots=True)], "MALFORMED_INPUT"),
    ([holder("CREATE", name="unknown")], "INVALID_PHASE"),
    ([holder("CREATE"), holder("RELEASE", slots=4)], "SLOT_COUNT_MISMATCH"),
    ([holder("CREATE"), holder("RELEASE"), holder("CREATE")], "DUPLICATE_HOLDER"),
])
def test_holder_misuse(records, code):
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100)] + records)
    outcome(result(evidence), o.INVALID, code)


@pytest.mark.parametrize("missing", ["slots", "phase", "holder_id"])
def test_holder_required_fields(missing):
    record = holder("CREATE")
    record.pop(missing)
    outcome(result(data([start(P, "parent"), record])), o.INVALID, "MISSING_FIELD")


def test_holder_lifetimes_concurrency_and_phase_attribution():
    cfg = config()
    cfg["required_phases"].append("attribution")
    first = frame(10)
    second = frame(20)
    for item in second["readings"]:
        item["phase"] = "attribution"
    records = [start(P, "parent"), start(W, "worker", 1, 100),
               holder("CREATE", P, "same-id", 3, 2), holder("CREATE", W, "same-id", 5, 3),
               holder("CREATE", P, "other", 7, 4), first,
               {"kind": "PHASE", "identity": P, "phase": "attribution", "time_ns": 11},
               {"kind": "PHASE", "identity": W, "phase": "attribution", "time_ns": 11},
               holder("RELEASE", P, "same-id", 3, 12, "attribution"),
               holder("RELEASE", P, "other", 7, 13, "attribution"),
               holder("RELEASE", W, "same-id", 5, 14, "attribution"),
               holder("CREATE", P, "new", 2, 15, "attribution"),
               holder("RELEASE", P, "new", 2, 16, "attribution"),
               second, exit_record(W, 20), exit_record(P, 20)]
    report = result(data(records, cfg), cfg)
    outcome(report, o.COMPLETE)
    metrics = report["holder_metrics"]
    assert metrics["cumulative_lifetimes_by_phase"]["producer"] == {"holders": 3, "slots": 15}
    assert metrics["cumulative_lifetimes_by_phase"]["attribution"] == {"holders": 1, "slots": 2}
    assert metrics["concurrent_maxima_by_process_phase"]["100:10"]["ALL"] == {"holders": 2, "slots": 10}
    assert metrics["concurrent_maxima_by_phase"]["ALL"] == {"holders": 3, "slots": 15}
    assert metrics["concurrent_maxima_by_phase"]["attribution"] == {"holders": 1, "slots": 2}
    assert metrics["lifetime_coverage_complete"] is True
    assert metrics["event_coverage_complete"] is True


def test_open_holder_and_lifecycle_flags():
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), holder("CREATE"), frame()])
    report = result(evidence)
    outcome(report, o.INCONCLUSIVE, "OPEN_HOLDER_LIFETIME")
    assert "OPEN_PROCESS_LIFETIME" in codes(report)
    assert report["holder_metrics"]["lifetime_coverage_complete"] is False
    assert report["holder_metrics"]["cumulative_lifetimes_by_phase"]["producer"]["holders"] == 1


@pytest.mark.parametrize("change,code", [
    (lambda evidence: evidence.update(truncated=True), "EVIDENCE_TRUNCATED"),
    (lambda evidence: evidence.update(declared_record_count=99), "DECLARED_COUNT_MISMATCH"),
    (lambda evidence: evidence.update(declared_frame_count=99), "DECLARED_COUNT_MISMATCH"),
    (lambda evidence: evidence.pop("holder_coverage"), "INCOMPLETE_HOLDER_COVERAGE"),
    (lambda evidence: evidence["holder_coverage"][0].update(events_complete=False), "INCOMPLETE_HOLDER_COVERAGE"),
])
def test_truncation_count_and_event_coverage(change, code):
    evidence = data()
    change(evidence)
    report = result(evidence)
    outcome(report, o.INCONCLUSIVE, code)
    assert report["holder_metrics"]["event_coverage_complete"] is False


def test_sequence_gap_and_duplicates():
    evidence = data()
    for record in evidence["records"][2:]:
        record["sequence"] += 1
    report = result(evidence)
    outcome(report, o.INCONCLUSIVE, "SEQUENCE_GAP")
    assert report["holder_metrics"]["event_coverage_complete"] is False
    evidence = data()
    evidence["records"][1]["sequence"] = 0
    outcome(result(evidence), o.INVALID, "DUPLICATE_RECORD")
    evidence = data()
    evidence["records"][2]["sequence"] = 0
    outcome(result(evidence), o.INVALID, "OUT_OF_ORDER")


def test_missing_phases_roles_and_all_frames():
    cfg = config()
    cfg["required_phases"].append("verification")
    outcome(result(data(cfg=cfg), cfg), o.INCONCLUSIVE, "MISSING_PHASE_COVERAGE")
    report = result(data([start(P, "parent"), start(W, "worker", 1, 100)]))
    outcome(report, o.INCONCLUSIVE, "INCOMPLETE_FRAME_SET")
    assert "MISSING_ROLE_COVERAGE" in codes(report)
    assert report["sampled_aggregate"]["max_rss_bytes"] is None
    report = result(data([start(P, "parent"), frame(10, identities=[(P, 1, 20)]), exit_record(P)]))
    outcome(report, o.INCONCLUSIVE, "MISSING_PROCESS")


def test_invalid_evidence_dominates_incomplete_evidence():
    evidence = data()
    evidence.update(truncated=True)
    evidence["records"][2]["readings"][0]["status"] = status(swap=-1)
    report = result(evidence)
    outcome(report, o.INVALID, "NEGATIVE_FIELD")
    assert "EVIDENCE_TRUNCATED" in codes(report)
    assert report["coverage_complete"] is False


def test_deterministic_json_integrity_and_caller_mutation_isolation():
    cfg, evidence = config(), data()
    report = result(evidence, cfg)
    reversed_config = dict(reversed(list(cfg.items())))
    reversed_evidence = dict(reversed(list(evidence.items())))
    assert o.canonical_bytes(report) == o.canonical_bytes(result(reversed_evidence, reversed_config))
    assert json.loads(o.canonical_bytes(report)) == report
    cfg["max_read_skew_ns"] = 999
    evidence["records"].clear()
    assert o.verify_integrity(report)
    changed = copy.deepcopy(report)
    changed["sampled_aggregate"]["max_rss_bytes"] = 1
    assert not o.verify_integrity(changed)
    assert report["integrity"]["sha256"] == o.digest({key: value for key, value in report.items() if key != "integrity"})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object(), {1: "key"}])
def test_non_json_values_are_rejected_without_coercion(value):
    evidence = data()
    evidence["conditions"]["invalid"] = value
    with pytest.raises(o.EvidenceError) as error:
        result(evidence)
    assert error.value.code == "MALFORMED_INPUT"


def independent_reports():
    baseline = result()
    evidence = data(run="candidate")
    evidence["records"][2]["readings"][1] = reading(W, 100, rss=10)
    return baseline, result(evidence)


def test_signed_comparison_integrity_and_numeric_types():
    baseline, candidate = independent_reports()
    compared = o.compare_reports(baseline, candidate)
    assert compared["outcome"] == "COMPARABLE_FAKE_OBSERVATIONS"
    assert compared["candidate_minus_baseline_sampled_max_rss_bytes"] == -30 * 1024
    assert type(compared["candidate_minus_baseline_sampled_max_rss_bytes"]) is int
    assert compared["baseline_outcome"] == compared["candidate_outcome"] == o.COMPLETE
    assert compared["baseline_reason_codes"] == compared["candidate_reason_codes"] == []
    assert o.verify_integrity(compared)
    assert o.compare_reports(baseline, candidate) == compared
    assert o.canonical_bytes(o.compare_reports(baseline, candidate)) == o.canonical_bytes(compared)
    assert o.signed_difference(5, 2) == -3
    assert type(o.signed_difference(5, 2)) is int
    assert o.signed_difference(5.5, 2.0) == -3.5
    assert type(o.signed_difference(5.5, 2.0)) is float
    assert compared["production_memory_qualification"] == o.INCONCLUSIVE
    assert compared["production_chronological_peak"] == "NOT_OBSERVED"
    compared["candidate_minus_baseline_sampled_max_rss_bytes"] = 1
    assert not o.verify_integrity(compared)


@pytest.mark.parametrize("change,code", [
    (lambda report: report.update(schema="other"), "SCHEMA_MISMATCH"),
    (lambda report: report.update(outcome=o.INVALID), "INVALID_EVIDENCE"),
    (lambda report: report.update(independent_run_id="baseline"), "INPUTS_NOT_INDEPENDENT"),
    (lambda report: report.update(workload_id="other"), "CONDITIONS_MISMATCH"),
    (lambda report: report["configuration"].update(max_read_skew_ns=7), "CONDITIONS_MISMATCH"),
    (lambda report: report["raw_supplied_observations"]["conditions"].update(modules=3), "CONDITIONS_MISMATCH"),
    (lambda report: report["sampled_aggregate"].update(max_rss_bytes=None), "MISSING_SAMPLED_METRIC"),
    (lambda report: report.update(production_memory_qualification="PASS"), "INVALID_ENVELOPE"),
    (lambda report: report.update(input_kind="LIVE_INPUT"), "INVALID_ENVELOPE"),
    (lambda report: report.update(coverage_complete=False), "INPUT_NOT_OBSERVATION_COMPLETE"),
])
def test_noncomparable_reports(change, code):
    baseline, candidate = independent_reports()
    change(candidate)
    candidate = o.seal(candidate)
    compared = o.compare_reports(baseline, candidate)
    assert compared["outcome"] == "NOT_COMPARABLE"
    assert code in compared["reasons"]
    assert compared["candidate_minus_baseline_sampled_max_rss_bytes"] is None
    assert o.verify_integrity(compared)


def test_identical_inputs_relabelled_inputs_and_tampering_are_not_comparable():
    baseline, candidate = independent_reports()
    assert "INPUTS_NOT_INDEPENDENT" in o.compare_reports(baseline, baseline)["reasons"]
    relabelled = data(run="relabelled")
    assert "INPUTS_NOT_INDEPENDENT" in o.compare_reports(baseline, result(relabelled))["reasons"]
    candidate["sampled_aggregate"]["max_rss_bytes"] = 1
    assert "INTEGRITY_MISMATCH" in o.compare_reports(baseline, candidate)["reasons"]


@pytest.mark.parametrize("incomplete_side", ["baseline", "candidate"])
@pytest.mark.parametrize("case,code", [
    ("truncated", "EVIDENCE_TRUNCATED"),
    ("oom", "OOM_OBSERVED"),
    ("oom_kill", "OOM_OBSERVED"),
    ("status_swap", "SWAP_OBSERVED"),
    ("smaps_swap", "SWAP_OBSERVED"),
    ("missing_worker", "MISSING_PROCESS"),
])
def test_inconclusive_comparison_is_refused_and_retains_input_reasons(incomplete_side, case, code):
    baseline, candidate = independent_reports()
    inputs = {"baseline": baseline, "candidate": candidate}
    evidence = copy.deepcopy(inputs[incomplete_side]["raw_supplied_observations"])
    supplied_frame = evidence["records"][2]
    if case == "truncated":
        evidence["truncated"] = True
    elif case in ("oom", "oom_kill"):
        supplied_frame["cgroup"]["memory_events"] = events(**{case: 1})
    elif case == "status_swap":
        supplied_frame["readings"][1]["status"] = supplied_frame["readings"][1]["status"].replace(
            "VmSwap: 0 kB", "VmSwap: 1 kB")
    elif case == "smaps_swap":
        supplied_frame["readings"][1]["smaps_rollup"] = supplied_frame["readings"][1]["smaps_rollup"].replace(
            "Swap: 0 kB", "Swap: 1 kB")
    else:
        supplied_frame["readings"].pop()
    inputs[incomplete_side] = result(evidence)
    outcome(inputs[incomplete_side], o.INCONCLUSIVE, code)
    compared = o.compare_reports(inputs["baseline"], inputs["candidate"])
    assert compared["outcome"] == "NOT_COMPARABLE"
    assert compared["candidate_minus_baseline_sampled_max_rss_bytes"] is None
    assert "INPUT_NOT_OBSERVATION_COMPLETE" in compared["reasons"]
    for side in ("baseline", "candidate"):
        assert compared[side + "_outcome"] == inputs[side]["outcome"]
        assert compared[side + "_reason_codes"] == sorted(codes(inputs[side]))
        assert compared[side + "_sha256"] == o.digest(inputs[side])
    assert code in compared[incomplete_side + "_reason_codes"]
    assert compared["production_memory_qualification"] == o.INCONCLUSIVE
    assert compared["production_chronological_peak"] == "NOT_OBSERVED"
    assert o.verify_integrity(compared)


@pytest.mark.parametrize("evidence", [[], "malformed raw evidence", None])
def test_comparison_refuses_invalid_reports_from_malformed_raw_evidence(evidence):
    baseline = result()
    candidate = o.reconcile(config(), evidence)
    outcome(candidate, o.INVALID, "MALFORMED_INPUT")
    compared = o.compare_reports(baseline, candidate)
    assert compared["outcome"] == "NOT_COMPARABLE"
    assert compared["candidate_outcome"] == o.INVALID
    assert compared["candidate_reason_codes"] == ["MALFORMED_INPUT"]
    assert "INVALID_EVIDENCE" in compared["reasons"]
    assert "INPUT_NOT_OBSERVATION_COMPLETE" in compared["reasons"]
    assert compared["candidate_minus_baseline_sampled_max_rss_bytes"] is None
    assert o.verify_integrity(compared)


@pytest.mark.parametrize("malformed", [None, [], "not a report"])
@pytest.mark.parametrize("side", ["baseline", "candidate"])
def test_comparison_refuses_non_object_reports(malformed, side):
    baseline, candidate = independent_reports()
    inputs = {"baseline": baseline, "candidate": candidate}
    inputs[side] = malformed
    assert not o.verify_integrity(malformed)
    compared = o.compare_reports(inputs["baseline"], inputs["candidate"])
    assert compared["outcome"] == "NOT_COMPARABLE"
    assert "MALFORMED_REPORT" in compared["reasons"]
    assert "INTEGRITY_MISMATCH" in compared["reasons"]
    assert compared[side + "_outcome"] is None
    assert compared[side + "_reason_codes"] is None
    assert compared[side + "_sha256"] is None
    assert compared["candidate_minus_baseline_sampled_max_rss_bytes"] is None
    assert o.verify_integrity(compared)


@pytest.mark.parametrize("name,value", [
    ("raw_supplied_observations", "bad"), ("raw_supplied_observations", []),
    ("raw_supplied_observations", None),
    ("raw_supplied_observations", {"conditions": [], "records": []}),
    ("raw_supplied_observations", {"conditions": {}, "records": None}),
    ("sampled_aggregate", []), ("sampled_aggregate", None),
    ("configuration", []), ("configuration", None),
    ("reasons", {}), ("reasons", None), ("reasons", "bad"),
    ("reasons", [None]), ("reasons", [{}]), ("reasons", [{"code": 7}]),
    ("outcome", None), ("outcome", []), ("outcome", {"invalid": True}),
])
@pytest.mark.parametrize("side", ["baseline", "candidate"])
def test_comparison_refuses_sealed_malformed_structures(name, value, side):
    baseline, candidate = independent_reports()
    inputs = {"baseline": baseline, "candidate": candidate}
    inputs[side][name] = value
    inputs[side] = o.seal(inputs[side])
    assert o.verify_integrity(inputs[side])
    compared = o.compare_reports(inputs["baseline"], inputs["candidate"])
    assert compared["outcome"] == "NOT_COMPARABLE"
    assert "MALFORMED_REPORT" in compared["reasons"]
    assert compared["candidate_minus_baseline_sampled_max_rss_bytes"] is None
    if name == "reasons":
        assert compared[side + "_reason_codes"] is None
    if name == "outcome":
        assert compared[side + "_outcome"] is None
    assert o.verify_integrity(compared)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object(), {1: "bad key"}])
def test_comparison_refuses_non_json_reports_without_raising(value):
    baseline, candidate = independent_reports()
    candidate["raw_supplied_observations"]["conditions"]["invalid"] = value
    compared = o.compare_reports(baseline, candidate)
    assert compared["outcome"] == "NOT_COMPARABLE"
    assert "MALFORMED_REPORT" in compared["reasons"]
    assert compared["candidate_outcome"] == o.COMPLETE
    assert compared["candidate_reason_codes"] == []
    assert compared["candidate_sha256"] is None
    assert compared["candidate_minus_baseline_sampled_max_rss_bytes"] is None
    assert o.verify_integrity(compared)


@pytest.mark.parametrize("value", ["10", [], True, -1, 1.5])
def test_comparison_refuses_malformed_sampled_metrics(value):
    baseline, candidate = independent_reports()
    candidate["sampled_aggregate"]["max_rss_bytes"] = value
    compared = o.compare_reports(baseline, o.seal(candidate))
    assert compared["outcome"] == "NOT_COMPARABLE"
    assert "MALFORMED_REPORT" in compared["reasons"]
    assert compared["candidate_minus_baseline_sampled_max_rss_bytes"] is None
    assert o.verify_integrity(compared)


def test_comparison_refuses_complete_label_with_reasons_and_deduplicates_codes():
    baseline, candidate = independent_reports()
    evidence = copy.deepcopy(candidate["raw_supplied_observations"])
    evidence["truncated"] = True
    evidence["records"][2]["cgroup"]["memory_events"] = events(oom=1, oom_kill=1)
    candidate = result(evidence)
    assert codes(candidate) == {"EVIDENCE_TRUNCATED", "OOM_OBSERVED"}
    candidate["outcome"] = o.COMPLETE
    candidate["coverage_complete"] = True
    candidate["reasons"].append(copy.deepcopy(candidate["reasons"][0]))
    compared = o.compare_reports(baseline, o.seal(candidate))
    assert compared["outcome"] == "NOT_COMPARABLE"
    assert "INPUT_NOT_OBSERVATION_COMPLETE" in compared["reasons"]
    assert compared["candidate_outcome"] == o.COMPLETE
    assert compared["candidate_reason_codes"] == ["EVIDENCE_TRUNCATED", "OOM_OBSERVED"]
    assert compared["candidate_minus_baseline_sampled_max_rss_bytes"] is None
    assert compared["production_memory_qualification"] == o.INCONCLUSIVE
    assert compared["production_chronological_peak"] == "NOT_OBSERVED"
    assert o.verify_integrity(compared)


def test_import_safety_and_no_execution_entry_point(monkeypatch):
    source = inspect.getsource(o)
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            imports.add(node.module)
        assert not (isinstance(node, ast.Name) and node.id == "__name__")
    assert imports == {"hashlib", "json", "re"}
    assert not any(isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                   for node in tree.body)
    real_import = builtins.__import__
    seen = []

    def restricted_import(name, *args, **kwargs):
        assert name in imports
        seen.append(name)
        return real_import(name, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Import must not read files or measure processes")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(builtins, "__import__", restricted_import)
    namespace = {}
    exec(compile(tree, "<in-memory-observer>", "exec"), namespace)
    assert set(seen) == imports
    assert namespace["SCHEMA"] == o.SCHEMA


def test_no_acceptance_projection_estimate_or_runtime_claim_fields():
    report = result()
    forbidden = {"PASS", "ACCEPTED", "estimate", "speedup", "numerical_parity", "717", "budget_pass"}

    def visit(value):
        if isinstance(value, dict):
            assert not (set(value) & forbidden)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str):
            assert value not in forbidden

    visit(report)
    assert report["input_kind"] == "FAKE_INPUT_ONLY"
    assert set(o.REASON_CLASSES.values()) == {o.INVALID, o.INCONCLUSIVE}
    assert all(reason["outcome"] == o.REASON_CLASSES[reason["code"]] for reason in report["reasons"])


@pytest.mark.parametrize("ident,code", [
    ([100], "INVALID_IDENTITY"),
    ([True, 10], "MALFORMED_INPUT"),
    ([100, False], "MALFORMED_INPUT"),
    ([-1, 10], "NEGATIVE_FIELD"),
    ([100, -1], "NEGATIVE_FIELD"),
])
def test_identity_shapes_and_boolean_rejection(ident, code):
    evidence = data()
    evidence["records"][0]["identity"] = ident
    outcome(result(evidence), o.INVALID, code)


def test_reused_pid_starttime_must_increase():
    cfg = config()
    reused = [200, 19]
    cfg["topology"]["workers"].append({"identity": reused, "parent": P})
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), frame(), exit_record(W),
                     start(reused, "worker", 11, 100)], cfg)
    outcome(result(evidence, cfg), o.INVALID, "PID_REUSE_ANOMALY")


def test_per_process_read_windows_must_not_reverse():
    second = frame(11)
    second["readings"][0].update(read_start_ns=7, read_end_ns=8)
    evidence = data([start(P, "parent"), start(W, "worker", 1, 100), frame(), second])
    report = result(evidence)
    outcome(report, o.INVALID, "OUT_OF_ORDER")
    assert report["sampled_aggregate"]["frames"][1]["sampled_rss_bytes"] is None
    assert len(report["sampled_aggregate"]["frames"][1]["valid_readings"]) == 2


def test_exited_process_open_holders_do_not_inflate_later_concurrency():
    replacement = [201, 21]
    cfg = config()
    cfg["topology"]["workers"].append({"identity": replacement, "parent": P})
    records = [start(P, "parent"), start(W, "worker", 1, 100),
               holder("CREATE", W, "old", 10, 2), frame(), exit_record(W),
               start(replacement, "worker", 11, 100), holder("CREATE", replacement, "new", 20, 12),
               holder("RELEASE", replacement, "new", 20, 13),
               frame(20, identities=[(P, 1, 20), (replacement, 100, 40)]),
               exit_record(replacement, 20), exit_record(P, 20)]
    report = result(data(records, cfg), cfg)
    outcome(report, o.INCONCLUSIVE, "OPEN_HOLDER_LIFETIME")
    metrics = report["holder_metrics"]
    assert metrics["concurrent_maxima_by_phase"]["ALL"] == {"holders": 1, "slots": 20}
    assert metrics["cumulative_lifetimes_by_phase"]["producer"] == {"holders": 2, "slots": 30}
    assert next(item for item in metrics["lifetimes"] if item["holder_id"] == "old")["release_ns"] is None


def test_reading_role_and_optional_lifecycle_ppid_validation():
    evidence = data()
    evidence["records"][2]["readings"][0]["role"] = "worker"
    outcome(result(evidence), o.INVALID, "IDENTITY_CONTRADICTION")
    evidence = data()
    evidence["records"][-1]["ppid"] = True
    outcome(result(evidence), o.INVALID, "MALFORMED_INPUT")


@pytest.mark.parametrize("change", [
    lambda cfg: cfg.pop("topology"),
    lambda cfg: cfg["topology"].pop("workers"),
])
def test_undeclared_topology_has_explicit_reason(change):
    cfg = config()
    change(cfg)
    outcome(result(data(), cfg), o.INVALID, "UNKNOWN_WORKER_TOPOLOGY")


def test_reason_code_classes_are_pinned():
    invalid = """MALFORMED_INPUT MISSING_FIELD DUPLICATE_FIELD NEGATIVE_FIELD INVALID_UNIT
        INCONSISTENT_COUNTER INVALID_IDENTITY PID_REUSE_ANOMALY DUPLICATE_RECORD OUT_OF_ORDER
        UNKNOWN_WORKER_TOPOLOGY IDENTITY_CONTRADICTION INVALID_PHASE INVALID_LIFECYCLE
        UNEXPECTED_PROCESS INVALID_READ_WINDOW DUPLICATE_HOLDER INVALID_RELEASE
        CROSS_PROCESS_RELEASE SLOT_COUNT_MISMATCH""".split()
    incomplete = """SAMPLE_GAP MISSING_PROCESS INCOMPLETE_FRAME_SET EVIDENCE_TRUNCATED SEQUENCE_GAP
        DECLARED_COUNT_MISMATCH MISSING_PHASE_COVERAGE MISSING_ROLE_COVERAGE OPEN_PROCESS_LIFETIME
        EXIT_WITHOUT_FINAL_OBSERVATION OPEN_HOLDER_LIFETIME ALIGNMENT_NOT_ESTABLISHED
        EXCESSIVE_READ_SKEW SWAP_OBSERVED OOM_OBSERVED CGROUP_LIMIT_EVENT MISSING_CGROUP_DATA
        INCOMPLETE_HOLDER_COVERAGE""".split()
    assert o.REASON_CLASSES == {**dict.fromkeys(invalid, o.INVALID), **dict.fromkeys(incomplete, o.INCONCLUSIVE)}
