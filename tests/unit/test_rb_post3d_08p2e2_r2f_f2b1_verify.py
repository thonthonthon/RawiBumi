"""Artificial in-memory F2-B1 contracts; no production modules or instruments."""

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


def memory_events(**changes):
    values = dict(low=0, high=0, max=0, oom=0, oom_kill=0)
    values.update(changes)
    return "".join(f"{name} {value}\n" for name, value in values.items())


def fake_reading(ident, ppid, rss, phase, now, final):
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


def fake_inputs(run="baseline", offset=0, rss=40, distribution=(1,),
                phases=("producer",)):
    """Consistent arbitrary rosters, phases, lifetimes and explicit fake coverage."""
    parents = [[offset + 100 + index, offset + 10 + index]
               for index in range(len(distribution))]
    workers = []
    for parent, count in zip(parents, distribution):
        for _ in range(count):
            index = len(workers)
            workers.append({"identity": [offset + 200 + index, offset + 20 + index],
                            "parent": parent.copy()})
    cfg = {
        "max_read_skew_ns": 5, "max_frame_gap_ns": 100,
        "required_phases": list(phases),
        "topology": {"parents": parents, "workers": workers,
                     "max_concurrent_workers": max(2, len(workers)),
                     "start_method": "spawn"},
    }
    processes = [(parent, 1, "parent", 20) for parent in parents]
    processes += [(worker["identity"], worker["parent"][0], "worker", rss)
                  for worker in workers]
    records = [
        {"kind": "START", "identity": ident.copy(), "ppid": ppid,
         "role": role, "phase": phases[0], "time_ns": 0 if role == "parent" else 1}
        for ident, ppid, role, _ in processes
    ]
    # Nonempty holder metrics allow testing all maxima, not just empty objects.
    for kind, now in (("CREATE", 2), ("RELEASE", 3)):
        records.append({"kind": kind, "time_ns": now, "identity": parents[0].copy(),
                        "holder_id": "artificial-holder", "slots": 3, "phase": phases[0]})
    for index, phase in enumerate(phases):
        now = 10 * (index + 1)
        if index:
            records += [{"kind": "PHASE", "time_ns": now - 9,
                         "identity": ident.copy(), "phase": phase}
                        for ident, _, _, _ in processes]
        records.append({
            "kind": "FRAME", "time_ns": now,
            "expected_live": [ident.copy() for ident, _, _, _ in processes],
            "readings": [fake_reading(ident, ppid, amount, phase, now,
                                      index == len(phases) - 1)
                         for ident, ppid, _, amount in processes],
            "cgroup": {"source_id": "fake-cgroup", "time_ns": now,
                       "memory_events": memory_events()},
        })
    records += [{"kind": "EXIT", "time_ns": 10 * len(phases),
                 "identity": worker["identity"].copy()} for worker in workers]
    records += [{"kind": "EXIT", "time_ns": 10 * len(phases), "identity": parent.copy()}
                for parent in parents]
    for sequence, record in enumerate(records):
        record["sequence"] = sequence
    raw = {
        "input_id": "fake-" + run, "independent_run_id": run,
        "workload_id": "fake-workload",
        "conditions": {"modules": 2, "cache_state": "artificial", "intervals": 1},
        "records": records, "declared_record_count": len(records),
        "declared_frame_count": len(phases), "truncated": False,
        "holder_coverage": [{"identity": ident.copy(), "phase": phase,
                             "events_complete": True}
                            for ident, _, _, _ in processes for phase in phases],
    }
    return cfg, raw


def complete(**kwargs):
    report = o.reconcile(*fake_inputs(**kwargs))
    assert report["outcome"] == o.COMPLETE, report["reasons"]
    assert report["coverage_complete"] is True
    assert report["reasons"] == []
    assert o.verify_integrity(report)
    return report


def pair(**candidate_kwargs):
    return complete(), complete(run="candidate", offset=1000, **candidate_kwargs)


def check_envelope(report):
    assert o.verify_integrity(report)
    for key, value in v.ENVELOPE.items():
        assert report[key] == value

    def visit(value):
        if type(value) is dict:
            assert not (set(value) & {"budget_pass", "speedup", "numerical_parity",
                                     "projection_717", "summed_hwm_peak_bytes"})
            for item in value.values():
                visit(item)
        elif type(value) is list:
            for item in value:
                visit(item)
        elif type(value) is str:
            assert value not in {"PASS", "ACCEPTED", "717", "MEMORY_SCREEN_MET"}

    visit(report)


def assert_comparable(baseline, candidate, delta=None):
    report = v.compare_verified_reports(baseline, candidate)
    check_envelope(report)
    assert report["schema"] == v.SCHEMA
    assert report["outcome"] == v.COMPARABLE, report["reasons"]
    assert report["reasons"] == []
    assert type(report[v.DELTA]) is int
    if delta is not None:
        assert report[v.DELTA] == delta
    for side in ("baseline", "candidate"):
        assert report[side]["reconstruction_verified"] is True
        assert report[side]["eligible"] is True
        assert report[side]["observed_outcome"] == o.COMPLETE
        assert report[side]["observed_reasons"] == []
    return report


def assert_rejected(baseline, candidate, code, side="candidate"):
    report = v.compare_verified_reports(baseline, candidate)
    check_envelope(report)
    assert report["outcome"] == v.NOT_COMPARABLE
    assert report[v.DELTA] is None
    assert {"side": side, "code": code} in report["reasons"]
    assert report["reasons"] == sorted(report["reasons"],
                                       key=lambda item: (item["side"], item["code"]))
    return report


def regenerate(report, mutate):
    cfg = copy.deepcopy(report["configuration"])
    raw = copy.deepcopy(report["raw_supplied_observations"])
    mutate(cfg, raw)
    return o.reconcile(cfg, raw)


def test_equivalent_topology_with_different_identities_and_provenance():
    baseline, candidate = pair(rss=50)
    before = copy.deepcopy((baseline, candidate))
    report = assert_comparable(baseline, candidate, 10 * 1024)
    assert o.compare_reports(baseline, candidate)["outcome"] != v.COMPARABLE
    for side, source in (("baseline", baseline), ("candidate", candidate)):
        summary = report[side]
        assert summary["source_report_sha256"] == o.digest(source)
        assert summary["source_input_sha256"] == o.digest(source["raw_supplied_observations"])
        assert summary["configuration_sha256"] == o.digest(source["configuration"])
        assert summary["input_id"] == source["input_id"]
        assert summary["independent_run_id"] == source["independent_run_id"]
    assert o.canonical_bytes([baseline, candidate]) == o.canonical_bytes(list(before))
    assert v.verify_report(candidate)["verification"]["eligible"] is True
    check_envelope(v.verify_report(candidate))


def test_negative_delta_and_side_swap_keep_sign():
    baseline, candidate = pair(rss=10)
    assert_comparable(baseline, candidate, -30 * 1024)
    assert_comparable(candidate, baseline, 30 * 1024)
    # Independent fake observations may have equal maxima; no HWM sum is used.
    baseline, candidate = pair()
    assert_comparable(baseline, candidate, 0)


@pytest.mark.parametrize("left_distribution,right_distribution", [
    ((2, 0), (1, 1)), ((1,), (1, 0)), ((1,), (2,)),
])
def test_unequal_parent_worker_topology(left_distribution, right_distribution):
    baseline = complete(distribution=left_distribution)
    candidate = complete(run="candidate", offset=1000, distribution=left_distribution)
    assert_comparable(baseline, candidate, 0)
    candidate = complete(run="candidate", offset=1000, distribution=right_distribution)
    assert_rejected(baseline, candidate, "TOPOLOGY_MISMATCH", "pair")


@pytest.mark.parametrize("mutate", [
    lambda cfg, raw: cfg["topology"].update(max_concurrent_workers=3),
    lambda cfg, raw: cfg["topology"].update(declared_operating_mode="different"),
    lambda cfg, raw: cfg["topology"]["workers"][0].update(declared_role="different"),
    lambda cfg, raw: cfg["topology"]["workers"][0].update(extra_identity=[17, 18]),
])
def test_nonidentity_topology_settings_are_preserved(mutate):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    candidate = regenerate(candidate, mutate)
    assert candidate["outcome"] == o.COMPLETE
    assert_rejected(baseline, candidate, "TOPOLOGY_MISMATCH", "pair")


def test_parent_and_worker_declaration_order_does_not_matter():
    baseline = complete(distribution=(2, 0))
    candidate = complete(run="candidate", offset=1000, distribution=(0, 2))
    candidate = regenerate(candidate, lambda cfg, raw: (
        cfg["topology"]["parents"].reverse(), cfg["topology"]["workers"].reverse()))
    assert candidate["outcome"] == o.COMPLETE
    assert_comparable(baseline, candidate, 0)


def test_worker_descriptors_remain_grouped_by_parent():
    baseline = complete(distribution=(2, 2))
    candidate = complete(run="candidate", offset=1000, distribution=(2, 2))

    def descriptors(report, labels):
        def mutate(cfg, raw):
            for worker, label in zip(cfg["topology"]["workers"], labels):
                worker["declared_kind"] = label
        rebuilt = regenerate(report, mutate)
        assert rebuilt["outcome"] == o.COMPLETE
        return rebuilt

    baseline = descriptors(baseline, ("red", "red", "blue", "blue"))
    candidate = descriptors(candidate, ("blue", "blue", "red", "red"))
    assert_comparable(baseline, candidate, 0)
    candidate = descriptors(candidate, ("red", "blue", "red", "blue"))
    assert_rejected(baseline, candidate, "TOPOLOGY_MISMATCH", "pair")


@pytest.mark.parametrize("location,code", [
    ("configuration", "CONFIGURATION_MISMATCH"),
    ("topology", "TOPOLOGY_MISMATCH"),
    ("worker", "TOPOLOGY_MISMATCH"),
])
def test_nonidentity_settings_use_canonical_type_equality(location, code):
    baseline, candidate = pair()

    def setting(report, value):
        def mutate(cfg, raw):
            target = (cfg if location == "configuration" else cfg["topology"]
                      if location == "topology" else cfg["topology"]["workers"][0])
            target["declared_flag"] = value
        rebuilt = regenerate(report, mutate)
        assert rebuilt["outcome"] == o.COMPLETE
        return rebuilt

    baseline, candidate = setting(baseline, True), setting(candidate, True)
    assert_comparable(baseline, candidate)
    candidate = setting(candidate, 1)
    assert_rejected(baseline, candidate, code, "pair")


@pytest.mark.parametrize("mutate,code", [
    (lambda cfg, raw: raw.update(workload_id="different"), "WORKLOAD_MISMATCH"),
    (lambda cfg, raw: raw["conditions"].update(modules=3), "CONDITIONS_MISMATCH"),
    (lambda cfg, raw: raw["conditions"].update(modules=2.0), "CONDITIONS_MISMATCH"),
    (lambda cfg, raw: raw["conditions"].update(intervals=True), "CONDITIONS_MISMATCH"),
    (lambda cfg, raw: cfg.update(max_read_skew_ns=6), "CONFIGURATION_MISMATCH"),
    (lambda cfg, raw: cfg.update(max_frame_gap_ns=101), "CONFIGURATION_MISMATCH"),
    (lambda cfg, raw: cfg.update(extra_threshold=1), "CONFIGURATION_MISMATCH"),
])
def test_workload_conditions_and_threshold_mismatches(mutate, code):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    candidate = regenerate(candidate, mutate)
    assert candidate["outcome"] == o.COMPLETE
    assert_rejected(baseline, candidate, code, "pair")


def test_required_phases_compared_in_declared_order():
    baseline = complete(phases=("producer", "verification"))
    candidate = complete(run="candidate", offset=1000,
                         phases=("producer", "verification"))
    assert_comparable(baseline, candidate)
    candidate = regenerate(candidate, lambda cfg, raw: cfg["required_phases"].reverse())
    assert candidate["outcome"] == o.COMPLETE
    assert_rejected(baseline, candidate, "CONFIGURATION_MISMATCH", "pair")
    candidate = complete(run="candidate", offset=1000, phases=("producer",))
    assert_rejected(baseline, candidate, "CONFIGURATION_MISMATCH", "pair")


def damage_evidence(cfg, raw, kind):
    frame = next(record for record in raw["records"] if record["kind"] == "FRAME")
    if kind == "truncated":
        raw["truncated"] = True
    elif kind in ("oom", "oom_kill"):
        frame["cgroup"]["memory_events"] = memory_events(**{kind: 1})
    elif kind == "status_swap":
        frame["readings"][0]["status"] = frame["readings"][0]["status"].replace(
            "VmSwap: 0", "VmSwap: 1")
    elif kind == "smaps_swap":
        frame["readings"][0]["smaps_rollup"] = "Rss: 20 kB\nSwap: 1 kB\n"
    elif kind == "absent_worker":
        frame["readings"].pop()
    elif kind == "absent_holder_coverage":
        raw["holder_coverage"].pop()
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize("side", ["baseline", "candidate"])
@pytest.mark.parametrize("kind,code", [
    ("truncated", "EVIDENCE_TRUNCATED"), ("oom", "OOM_OBSERVED"),
    ("oom_kill", "OOM_OBSERVED"), ("status_swap", "SWAP_OBSERVED"),
    ("smaps_swap", "SWAP_OBSERVED"), ("absent_worker", "MISSING_PROCESS"),
    ("absent_holder_coverage", "INCOMPLETE_HOLDER_COVERAGE"),
])
def test_incomplete_inputs_keep_reconstructed_side_reasons(side, kind, code):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    damaged = regenerate(baseline if side == "baseline" else candidate,
                         lambda cfg, raw: damage_evidence(cfg, raw, kind))
    assert damaged["outcome"] == o.INCONCLUSIVE
    assert code in {item["code"] for item in damaged["reasons"]}
    if side == "baseline":
        baseline = damaged
    else:
        candidate = damaged
    report = assert_rejected(baseline, candidate, "INPUT_NOT_OBSERVATION_COMPLETE", side)
    summary = report[side]
    assert summary["reconstruction_verified"] is True
    assert summary["observed_outcome"] == damaged["outcome"]
    assert summary["observed_reasons"] == damaged["reasons"]
    assert summary["observed_reason_codes"] == sorted({item["code"] for item in damaged["reasons"]})
    assert summary["source_input_sha256"] == damaged["input_sha256"]


def set_path(value, path, replacement):
    for component in path[:-1]:
        value = value[component]
    value[path[-1]] = replacement


@pytest.mark.parametrize("path,replacement", [
    (("outcome",), o.INCONCLUSIVE),
    (("reasons",), [{"code": "made-up", "outcome": o.INCONCLUSIVE,
                     "sequence": None, "detail": "forged"}]),
    (("coverage_complete",), False), (("coverage_complete",), 1),
    (("sampled_aggregate", "max_rss_bytes"), 1),
    (("sampled_aggregate", "max_rss_bytes"), None),
    (("sampled_aggregate", "max_rss_bytes"), -1),
    (("sampled_aggregate", "max_rss_bytes"), True),
    (("sampled_aggregate", "max_rss_bytes"), "61440"),
    (("sampled_aggregate", "max_rss_bytes"), 61440.0),
    (("sampled_aggregate", "eligible_frame_count"), 2),
    (("sampled_aggregate", "frames", 0, "sampled_rss_bytes"), 1),
    (("sampled_aggregate", "frames", 0, "sampled_smaps_rss_bytes"), 1),
    (("per_process_hwm_bytes",), {"1200:1020": 1}),
    (("cgroup_observations", 0, "memory_events", "oom"), 1),
    (("role_phase_coverage",), {}),
    (("holder_metrics", "concurrent_maxima_by_process_phase"), {}),
    (("holder_metrics", "concurrent_maxima_by_phase", "ALL", "slots"), 999),
    (("holder_metrics", "cumulative_lifetimes_by_phase", "producer", "holders"), 999),
    (("holder_metrics", "lifetimes", 0, "release_ns"), None),
    (("processes",), {}), (("input_sha256",), "0" * 64),
    (("caveats",), []), (("production_memory_qualification",), "forged"),
    (("production_chronological_peak",), "forged"), (("input_kind",), "forged"),
    (("input_id",), "forged"), (("unexpected",), "extra derived field"),
])
def test_resealed_derived_field_forgery_rejected(path, replacement):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    set_path(candidate, path, replacement)
    forged = o.seal(candidate)
    assert o.verify_integrity(forged)
    report = assert_rejected(baseline, forged, "RECONSTRUCTION_MISMATCH")
    assert report["candidate"]["reconstruction_verified"] is False
    assert report["candidate"]["observed_outcome"] is None
    assert report["candidate"]["observed_reasons"] is None
    assert report["candidate"]["source_input_sha256"] is None
    assert report["candidate"]["source_report_sha256"] == o.digest(forged)


def test_consistently_forged_sample_maximum_and_frame_are_still_rejected():
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    candidate["sampled_aggregate"]["max_rss_bytes"] = 1
    candidate["sampled_aggregate"]["frames"][0]["sampled_rss_bytes"] = 1
    assert_rejected(baseline, o.seal(candidate), "RECONSTRUCTION_MISMATCH")


@pytest.mark.parametrize("key", ["caveats", "holder_metrics", "reasons", "outcome",
                                     "per_process_hwm_bytes", "input_sha256"])
def test_removed_derived_key_is_rejected(key):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    candidate.pop(key)
    assert_rejected(baseline, o.seal(candidate), "RECONSTRUCTION_MISMATCH")


def test_inconclusive_evidence_cannot_be_relabelled_complete():
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    candidate = regenerate(candidate, lambda cfg, raw: raw.update(truncated=True))
    assert candidate["outcome"] == o.INCONCLUSIVE
    candidate.update(outcome=o.COMPLETE, reasons=[], coverage_complete=True)
    assert_rejected(baseline, o.seal(candidate), "RECONSTRUCTION_MISMATCH")


@pytest.mark.parametrize("mutation,code", [
    (lambda report: report.update(schema="unknown.v1"), "SCHEMA_MISMATCH"),
    (lambda report: report.pop("configuration"), "MALFORMED_REPORT"),
    (lambda report: report.pop("raw_supplied_observations"), "MALFORMED_REPORT"),
    (lambda report: report.update(configuration=[]), "MALFORMED_REPORT"),
    (lambda report: report.update(raw_supplied_observations=[]), "MALFORMED_REPORT"),
])
def test_schema_and_required_containers(mutation, code):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    mutation(candidate)
    assert_rejected(baseline, o.seal(candidate), code)


def test_unsealed_tampering_is_rejected_before_reconstruction():
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    candidate["sampled_aggregate"]["max_rss_bytes"] = 0
    assert_rejected(baseline, candidate, "INTEGRITY_MISMATCH")


@pytest.mark.parametrize("mutate", [
    lambda cfg, raw: cfg["topology"].update(parents={}),
    lambda cfg, raw: cfg["topology"].update(workers=[None]),
    lambda cfg, raw: cfg["topology"]["parents"].append(cfg["topology"]["parents"][0].copy()),
    lambda cfg, raw: cfg["topology"]["workers"].append(copy.deepcopy(cfg["topology"]["workers"][0])),
    lambda cfg, raw: cfg["topology"]["workers"][0].update(parent=[9999, 0]),
    lambda cfg, raw: cfg["topology"].update(start_method="fork"),
    lambda cfg, raw: cfg["topology"].update(max_concurrent_workers=True),
])
def test_unresolvable_topology_fails_closed(mutate):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    candidate = regenerate(candidate, mutate)
    assert candidate["outcome"] == o.INVALID
    report = assert_rejected(baseline, candidate, "TOPOLOGY_NOT_NORMALIZABLE")
    assert report["candidate"]["observed_outcome"] == o.INVALID
    assert report["candidate"]["reconstruction_verified"] is True


@pytest.mark.parametrize("mutate", [
    lambda cfg, raw: raw.update(records=[None]),
    lambda cfg, raw: raw.update(records={}),
    lambda cfg, raw: raw.update(holder_coverage=[None]),
    lambda cfg, raw: raw.update(conditions=[]),
    lambda cfg, raw: raw.update(input_id=""),
    lambda cfg, raw: raw["records"][4].update(readings=[None]),
])
def test_reconstructed_malformed_evidence_retains_invalid_outcome(mutate):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    candidate = regenerate(candidate, mutate)
    assert candidate["outcome"] == o.INVALID
    report = assert_rejected(baseline, candidate, "INPUT_NOT_OBSERVATION_COMPLETE")
    assert report["candidate"]["observed_reasons"] == candidate["reasons"]
    assert report["candidate"]["observed_outcome"] == o.INVALID


@pytest.mark.parametrize("mutation, code", [
    ({"input_id": ""}, "MISSING_INPUT_DECLARATION"),
    ({"conditions": []}, "MALFORMED_EVIDENCE"),
])
def test_reconstructed_declaration_and_evidence_failure_codes(mutation, code):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    candidate = regenerate(candidate, lambda cfg, raw: raw.update(mutation))
    assert candidate["outcome"] == o.INVALID
    report = assert_rejected(baseline, candidate, code)
    assert report["candidate"]["reconstruction_verified"] is True


@pytest.mark.parametrize("bad", [None, [], "report", 3, True, object()])
def test_non_object_reports_on_both_sides(bad):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    assert_rejected(baseline, bad, "MALFORMED_REPORT")
    assert_rejected(bad, candidate, "MALFORMED_REPORT", "baseline")
    check_envelope(v.verify_report(bad))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), object(),
                                     {1: "bad-key"}, (1, 2), "\ud800",
                                     pytest.param(10 ** 5000, id="oversized-integer")])
def test_non_json_nested_values_never_escape(bad):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    candidate["raw_supplied_observations"]["conditions"]["nested"] = bad
    report = assert_rejected(baseline, candidate, "MALFORMED_REPORT")
    assert report["candidate"]["source_report_sha256"] is None
    check_envelope(v.verify_report(candidate))


@pytest.mark.parametrize("surrogate", ["\ud800", "\udfff"])
@pytest.mark.parametrize("location", ["key", "value"])
@pytest.mark.parametrize("resealed", [False, True])
def test_surrogate_strings_are_rejected_before_digest(surrogate, location, resealed):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    conditions = candidate["raw_supplied_observations"]["conditions"]
    conditions["nested"] = {surrogate: "value"} if location == "key" else surrogate
    if resealed:
        candidate = o.seal(candidate)
        assert o.verify_integrity(candidate)
    report = assert_rejected(baseline, candidate, "MALFORMED_REPORT")
    assert report["candidate"]["source_report_sha256"] is None
    report = assert_rejected(candidate, baseline, "MALFORMED_REPORT", "baseline")
    assert report["baseline"]["source_report_sha256"] is None
    verified = v.verify_report(candidate)
    check_envelope(verified)
    assert verified["verification"]["verification_reason_codes"] == ["MALFORMED_REPORT"]
    assert verified["verification"]["source_report_sha256"] is None


def test_utf8_unicode_keys_and_values_remain_comparable():
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    mutation = lambda cfg, raw: raw["conditions"].update({"caf\u00e9": "\U0001f331"})
    baseline = regenerate(baseline, mutation)
    candidate = regenerate(candidate, mutation)
    assert baseline["outcome"] == candidate["outcome"] == o.COMPLETE
    assert_comparable(baseline, candidate)


@pytest.mark.parametrize("cycle", [False, True])
def test_deep_and_recursive_inputs_are_sealed_errors(cycle):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    nested = {}
    if cycle:
        nested["next"] = nested
    else:
        cursor = nested
        for _ in range(5000):
            cursor["next"] = {}
            cursor = cursor["next"]
    candidate["raw_supplied_observations"]["nested"] = nested
    assert_rejected(baseline, candidate, "MALFORMED_REPORT")
    assert_rejected(candidate, baseline, "MALFORMED_REPORT", "baseline")
    check_envelope(v.verify_report(candidate))


@pytest.mark.parametrize("exception", [RecursionError, ValueError, TypeError, KeyError,
                                           AttributeError, RuntimeError])
def test_failed_reconciliation_never_raises(monkeypatch, exception):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)

    def failed(*args, **kwargs):
        raise exception("must not echo this payload")

    monkeypatch.setattr(o, "reconcile", failed)
    report = assert_rejected(baseline, candidate, "RECONSTRUCTION_FAILED")
    assert "must not echo" not in o.canonical_bytes(report).decode()
    check_envelope(v.verify_report(candidate))


@pytest.mark.parametrize("name", ["input_id", "independent_run_id"])
def test_reused_independence_declarations(name):
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    candidate = regenerate(candidate, lambda cfg, raw: raw.update({name: baseline[name]}))
    assert candidate["outcome"] == o.COMPLETE
    assert_rejected(baseline, candidate, "INPUTS_NOT_INDEPENDENT", "pair")


def test_reused_report_and_identical_raw_records_are_not_independent():
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    report = assert_rejected(baseline, baseline, "INPUTS_NOT_INDEPENDENT", "pair")
    assert report["baseline"]["source_input_sha256"] == report["candidate"]["source_input_sha256"]
    # Different independently declared IDs and source digests cannot excuse a
    # byte-identical record payload, even when the caller asserts independence.
    candidate = regenerate(baseline, lambda cfg, raw: raw.update(
        input_id="fake-candidate", independent_run_id="candidate"))
    assert candidate["outcome"] == o.COMPLETE
    assert candidate["input_sha256"] != baseline["input_sha256"]
    assert_rejected(baseline, candidate, "INPUTS_NOT_INDEPENDENT", "pair")


def test_full_raw_regeneration_is_not_authenticity_verification():
    baseline, candidate = pair()
    assert_comparable(baseline, candidate)
    # A consistent new artificial record set may reconstruct. This demonstrates
    # the explicitly documented limit rather than promising authentication.
    cfg, raw = fake_inputs(run="candidate", offset=1000, rss=80)
    candidate = o.reconcile(cfg, raw)
    assert candidate["outcome"] == o.COMPLETE
    assert_comparable(baseline, candidate, 40 * 1024)


def reverse_keys(value):
    if type(value) is dict:
        return {key: reverse_keys(value[key]) for key in reversed(value)}
    if type(value) is list:
        return [reverse_keys(item) for item in value]
    return value


def test_determinism_key_order_and_nonmutation():
    baseline, candidate = pair()
    before = o.canonical_bytes([baseline, candidate])
    expected = assert_comparable(baseline, candidate)
    for _ in range(3):
        assert o.canonical_bytes(v.compare_verified_reports(baseline, candidate)) == o.canonical_bytes(expected)
    assert o.canonical_bytes(v.compare_verified_reports(reverse_keys(baseline), reverse_keys(candidate))) == o.canonical_bytes(expected)
    assert o.canonical_bytes(v.verify_report(candidate)) == o.canonical_bytes(v.verify_report(reverse_keys(candidate)))
    assert o.canonical_bytes([baseline, candidate]) == before
    malformed = copy.deepcopy(candidate)
    malformed["raw_supplied_observations"]["truncated"] = True
    before = o.canonical_bytes(malformed)
    assert_rejected(baseline, o.seal(malformed), "RECONSTRUCTION_MISMATCH")
    assert o.canonical_bytes(malformed) == before


def test_import_safety_and_no_live_io(monkeypatch):
    source = inspect.getsource(v)
    observer_source = inspect.getsource(o)
    trees = [ast.parse(source), ast.parse(observer_source)]
    for tree, allowed in zip(trees, ({"scripts.benchmarks"}, {"hashlib", "json", "re"})):
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
            assert not (isinstance(node, ast.Name) and node.id == "__name__")
        assert imports == allowed
        assert not any(isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                       for node in tree.body)
    assert "engine.simulation" not in source + observer_source
    assert "shading" not in source + observer_source
    real_import = builtins.__import__
    seen = []

    def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        assert name == "scripts.benchmarks"
        assert fromlist == ("rb_post3d_08p2e2_r2f_f2a_observer",)
        seen.append(name)
        return real_import(name, globals, locals, fromlist, level)

    def forbidden(*args, **kwargs):
        raise AssertionError("Live I/O, process or clock observation attempted")

    baseline, candidate = pair()
    expected = assert_comparable(baseline, candidate)
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
        exec(compile(trees[0], "<fake-verifier>", "exec"), namespace)
        actual = namespace["compare_verified_reports"](baseline, candidate)
        verified = namespace["verify_report"](candidate)
        error = namespace["compare_verified_reports"](None, {})
    assert seen == ["scripts.benchmarks"]
    assert o.canonical_bytes(actual) == o.canonical_bytes(expected)
    check_envelope(verified)
    check_envelope(error)
    assert error["outcome"] == v.NOT_COMPARABLE
    assert error[v.DELTA] is None
