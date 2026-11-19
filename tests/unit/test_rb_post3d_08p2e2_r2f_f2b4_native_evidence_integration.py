"""Artificial B3-B2 contracts. Execution is reserved for the orchestrator."""

import ast
import builtins
import copy
from dataclasses import FrozenInstanceError
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import pytest

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_native_evidence_integration as integration
from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_native_procfs_adapter as adapter
from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_local_provenance_probe as probe

bridge = integration.bridge
MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_native_evidence_integration.py"
BOOT = "12345678-1234-5678-90ab-123456789abc"


class HarnessViolation(BaseException):
    pass


@pytest.fixture(autouse=True)
def forbid_native_io(monkeypatch):
    violations = []

    def blocked(*args, **kwargs):
        violations.append("forbidden operation")
        raise HarnessViolation("forbidden operation")

    def source_only(original):
        def guarded(*args, **kwargs):
            path = args[0] if args else kwargs.get("file")
            mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
            if (not isinstance(path, (str, bytes, os.PathLike)) or
                    os.fsdecode(path) != str(MODULE_PATH) or any(c in mode for c in "wax+")):
                blocked()
            return original(*args, **kwargs)
        return guarded

    with monkeypatch.context() as guard:
        for name in ("open", "read", "stat", "lstat", "readlink", "listdir", "scandir", "sysconf", "system",
                     "fork", "forkpty", "posix_spawn", "posix_spawnp", "setns", "unshare", "kill", "killpg",
                     "pidfd_open", "mkdir", "makedirs", "remove", "unlink", "rename", "replace", "rmdir"):
            if hasattr(os, name):
                guard.setattr(os, name, blocked)
        for obj in (builtins, io):
            guard.setattr(obj, "open", source_only(obj.open))
        for obj, names in ((time, ("monotonic_ns", "monotonic", "time", "time_ns", "perf_counter",
                                  "perf_counter_ns", "clock_gettime", "clock_gettime_ns")),
                           (subprocess, ("Popen", "run", "call", "check_call", "check_output")),
                           (socket, ("socket", "create_connection"))):
            for name in names:
                if hasattr(obj, name):
                    guard.setattr(obj, name, blocked)
        yield violations
    assert violations == []


def identities():
    return [{"pid": 100, "ppid": 1, "starttime_ticks": 10},
            {"pid": 200, "ppid": 100, "starttime_ticks": 20}]


def environment(native=False):
    return {"boot_id": BOOT, "namespace": {"kind": "INODE", "value": 77},
            "procfs": {"filesystem": "proc", "mount_id": 9, "st_dev": 5},
            "nsfs": {"filesystem": "nsfs", "mount_id": 10, "st_dev": 4},
            "clock_kind": "LOCAL_MONOTONIC_NS" if native else "INJECTED_MONOTONIC_NS"}


def capture(native=False):
    state = "NATIVE_PROCFS_UNVERIFIED" if native else "INJECTED_TEST_ONLY"
    value = {"schema": integration.CAPTURE_SCHEMA, "source_state": state,
             "source_kind": integration.ORIGINS[state][0], "origin_attestation": integration.ORIGINS[state][1],
             **environment(native), "roster": identities(), "frames": []}
    for index in range(2):
        start = 100 + 100 * index
        frame = {"index": index, "start_ns": start, "end_ns": start + 50,
                 "observed_pids": [100, 200], "processes": [], "read_complete": True, "reason_codes": []}
        tick = start
        for n, identity in enumerate(identities()):
            process = {"identity": identity, "descriptors": [], "reads": []}
            for k, leaf in enumerate(("identity", "ns_link", "ns_target")):
                path = f"pids/{identity['pid']}/{leaf}"
                target = leaf == "ns_target"
                process["descriptors"].append({"path_id": path,
                    "role": "NSFS_TARGET" if target else "PROCFS_LINK_LOCATION" if leaf == "ns_link" else "PROCFS_OBJECT",
                    **value["nsfs" if target else "procfs"], "st_ino": 77 if target else 1000 + 10 * n + k})
                process["reads"].append({"path_id": path, "start_ns": tick, "end_ns": tick + 1,
                    "status": "OK", "sha256": hashlib.sha256(b"artificial bytes").hexdigest(),
                    "byte_count": 16, "reason_codes": []})
                tick += 2
            frame["processes"].append(process)
        value["frames"].append(frame)
    return value


def verification(value, validator="ADAPTER_D2B2", invalid=(), incomplete=()):
    schema, _, _, success = integration.VERIFIERS[validator]
    return {"schema": integration.VERIFICATION_SCHEMA, "validator": validator, "upstream_schema": schema,
            "outcome": "INVALID" if invalid else "INCOMPLETE" if incomplete else success,
            "reason_codes": sorted(set(invalid) | set(incomplete)), "invalid_reason_codes": sorted(invalid),
            "incomplete_reason_codes": sorted(incomplete), "report_sha256": "a" * 64,
            "capture_sha256": integration.digest(value)}


def request(native=False):
    state = "NATIVE_PROCFS_UNVERIFIED" if native else "INJECTED_TEST_ONLY"
    routes = []
    for label in ("left", "right"):
        value = capture(native)
        routes.append({"provenance": {key: label + "_" + key for key in
            ("route_id", "provider_id", "callback_id", "method_id", "collection_domain")},
            "capture": value, "verification": verification(value)})
        routes[-1]["provenance"]["data_origin"] = state
    return {"schema": integration.SCHEMA, "mode": "SUPPLIED_ONLY", "native_opt_in": False,
            "reference": {**environment(native), "roster": identities(),
                          "window": {"start_ns": 100, "end_ns": 250}, "frame_count": 2},
            "routes": routes, "limits": {"max_read_ns": 60, "max_gap_ns": 60, "max_route_skew_ns": 5}}


def rebind(data):
    """Explicitly update only the asserted binding after a deliberate mutation."""
    for route in data["routes"]:
        route["verification"]["capture_sha256"] = integration.digest(route["capture"])
    return data


def check(data=None, **kwargs):
    data = request() if data is None else data
    before = copy.deepcopy(data)
    report = integration.integrate_native_evidence(data, **kwargs)
    assert data == before
    result = report.to_dict()
    assert result["qualification"] == "NONQUALIFYING"
    assert result["independence"] == "INDEPENDENCE_NOT_ESTABLISHED"
    for key in ("source_origin_authenticated", "worker_roster_complete", "production_memory_qualified", "peak_observed",
                "worker_absence_proven", "production_workload_measured", "atomic_snapshot"):
        assert result[key] is False
    assert result["holder_release"] == "NOT_ESTABLISHED"
    assert result["production_memory_qualification"] == "INCONCLUSIVE"
    assert result["production_chronological_peak"] == "NOT_OBSERVED"
    assert result["live_native_integration"] == result["native_origin_authentication"] == "NOT_IMPLEMENTED"
    assert result["memo_cap"] == 256
    bad, gaps = set(result["invalid_reason_codes"]), set(result["incomplete_reason_codes"])
    assert bad <= set(integration.INVALID_CODES)
    assert gaps <= set(integration.INCOMPLETE_CODES)
    assert result["reason_codes"] == sorted(bad | gaps)
    assert result["outcome"] == ("INVALID" if bad else "INCOMPLETE" if gaps else "CONSISTENT")
    assert result["structure_consistent"] is (result["outcome"] == "CONSISTENT")
    assert len(report.serialized) < 65536
    return result


def expect(result, outcome, *codes):
    assert result["outcome"] == outcome
    assert result["reason_codes"] == sorted(codes)


def test_complete_agreement_is_only_structural():
    result = check()
    assert result["outcome"] == "CONSISTENT"
    assert result["reason_codes"] == []
    assert {r["source_state"] for r in result["routes"]} == {"INJECTED_TEST_ONLY"}
    assert all(r["verification"]["provenance"] == "CALLER_ASSERTED" for r in result["routes"])


def test_native_shaped_supplied_facts_preserve_unverified_origin():
    result = check(request(True))
    assert result["outcome"] == "CONSISTENT"
    assert all(r["source_kind"] == r["source_state"] == "NATIVE_PROCFS_UNVERIFIED" and
               r["origin_attestation"] == "UNVERIFIED_NATIVE_CAPTURE" for r in result["routes"])


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("endpoint", ["frame_start", "frame_end", "read_start", "read_end"])
@pytest.mark.parametrize("delta", [1, 5, 6])
def test_route_timestamps_use_skew_tolerance(native, endpoint, delta):
    data = request(native)
    frames = data["routes"][1]["capture"]["frames"]
    if endpoint == "frame_start":
        # The second frame has room before its first read. Keep read ordering valid.
        frames[1]["start_ns"] += delta
        for process in frames[1]["processes"]:
            for read in process["reads"]:
                read["start_ns"] += delta
                read["end_ns"] += delta
    elif endpoint == "frame_end":
        frames[0]["end_ns"] -= delta
    else:
        # Last read has room after it, so shifting either endpoint stays valid.
        read = frames[0]["processes"][-1]["reads"][-1]
        read["end_ns"] += delta
        if endpoint == "read_start":
            read["start_ns"] += delta
    result = check(rebind(data))
    expect(result, "CONSISTENT" if delta <= 5 else "INCOMPLETE",
           *(() if delta <= 5 else ("ROUTE_SKEW_EXCEEDED",)))


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("max_read_ns", [49, 50, 51])
def test_frame_duration_has_a_distinct_inclusive_limit(native, max_read_ns):
    data = request(native)
    data["limits"]["max_read_ns"] = max_read_ns
    expect(check(data), "INCOMPLETE" if max_read_ns < 50 else "CONSISTENT",
           *(("FRAME_DURATION_EXCEEDED",) if max_read_ns < 50 else ()))


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("upstream_invalid", [False, True])
def test_timing_reasons_accumulate_with_invalid_taking_precedence(native, upstream_invalid):
    data = request(native)
    data["limits"]["max_read_ns"] = 49
    data["routes"][1]["capture"]["frames"][0]["end_ns"] -= 6
    rebind(data)
    if upstream_invalid:
        route = data["routes"][0]
        route["verification"] = verification(route["capture"], invalid=("SCHEMA_INVALID",))
    result = check(data)
    expect(result, "INVALID" if upstream_invalid else "INCOMPLETE",
           "FRAME_DURATION_EXCEEDED", "ROUTE_SKEW_EXCEEDED",
           *(("UPSTREAM_INVALID",) if upstream_invalid else ()))
    assert result["invalid_reason_codes"] == (["UPSTREAM_INVALID"] if upstream_invalid else [])
    assert result["incomplete_reason_codes"] == ["FRAME_DURATION_EXCEEDED", "ROUTE_SKEW_EXCEEDED"]


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("field", ["sha256", "byte_count"])
def test_route_byte_fact_disagreement_is_distinct_from_timing(native, field):
    data = request(native)
    read = data["routes"][1]["capture"]["frames"][0]["processes"][0]["reads"][0]
    read[field] = "b" * 64 if field == "sha256" else 17
    expect(check(rebind(data)), "INCOMPLETE", "SOURCE_DISAGREEMENT")


def test_route_descriptor_disagreement_is_structural():
    data = request()
    for frame in data["routes"][1]["capture"]["frames"]:
        frame["processes"][0]["descriptors"][0]["st_ino"] = 9000
    expect(check(rebind(data)), "INCOMPLETE", "SOURCE_DISAGREEMENT")


def test_route_paths_and_pids_are_compared_as_sets():
    data = request()
    for frame in data["routes"][1]["capture"]["frames"]:
        frame["observed_pids"].reverse()
        for process in frame["processes"]:
            process["descriptors"].reverse()
            # Swap read paths with identical byte facts, keeping monotonic timing.
            process["reads"][0]["path_id"], process["reads"][1]["path_id"] = (
                process["reads"][1]["path_id"], process["reads"][0]["path_id"])
    expect(check(rebind(data)), "CONSISTENT")


@pytest.mark.parametrize("mode,opt_in", [("NATIVE", False), ("NATIVE_OPT_IN", False),
    ("SUPPLIED_ONLY", True), ("SUPPLIED_ONLY", adapter.NATIVE_OPT_IN), ("SUPPLIED_ONLY", 0),
    ("SUPPLIED_ONLY", None), ([], False)])
def test_native_denial_before_callback_inspection(mode, opt_in):
    class Explosive:
        def __getattribute__(self, name):
            raise AssertionError("callback inspected")

        def __call__(self):
            raise AssertionError("callback called")

    data = request()
    data.update(mode=mode, native_opt_in=opt_in)
    result = check(data, callbacks=(Explosive(), Explosive()))
    assert result["reason_codes"] == ["NATIVE_MODE_DENIED"]


@pytest.mark.parametrize("encoded", [False, True])
def test_native_denial_precedes_unknown_fields_in_both_input_forms(encoded):
    data = request()
    data.update(mode="NATIVE_OPT_IN", extra="ignored before schema validation")
    if encoded:
        data = json.dumps(data).encode()
    result = integration.integrate_native_evidence(data, callbacks=(ArtificialCallback(),)).to_dict()
    expect(result, "INVALID", "NATIVE_MODE_DENIED")


def test_hostile_non_json_mode_cannot_execute_equality():
    class Hostile:
        def __eq__(self, other):
            raise AssertionError("untrusted equality invoked")
    data = request()
    data["mode"] = Hostile()
    result = integration.integrate_native_evidence(data).to_dict()
    assert result["reason_codes"] == ["NATIVE_MODE_DENIED"]


@pytest.mark.parametrize("key,value", [("source_state", "NATIVE_SOURCE_VERIFIED"),
    ("source_state", []), ("source_kind", "NATIVE_PROCFS_UNVERIFIED"),
    ("origin_attestation", "UNVERIFIED_NATIVE_CAPTURE"), ("clock_kind", "LOCAL_MONOTONIC_NS")])
def test_injected_cannot_be_promoted(key, value):
    data = request()
    data["routes"][0]["capture"][key] = value
    expect(check(rebind(data)), "INVALID", "SOURCE_LABEL_CONFLICT")


def test_mixed_origins_fail_closed():
    data = request()
    data["routes"][1] = request(True)["routes"][1]
    result = check(data)
    expect(result, "INVALID", "CLOCK_DOMAIN_UNCOMPARABLE", "SOURCE_LABEL_CONFLICT")


def test_native_data_origin_cannot_contradict_capture_source_state():
    data = request(True)
    data["routes"][0]["provenance"]["data_origin"] = "INJECTED_TEST_ONLY"
    expect(check(data), "INVALID", "SOURCE_LABEL_CONFLICT")


@pytest.mark.parametrize("field", ["route_id", "provider_id", "callback_id", "method_id", "collection_domain"])
def test_claimed_route_method_or_kernel_alias(field):
    data = request()
    data["routes"][1]["provenance"][field] = data["routes"][0]["provenance"][field]
    assert check(data)["reason_codes"] == ["SOURCE_ALIAS"]


class ArtificialCallback:
    def __call__(self):
        raise AssertionError("identity-only callbacks must never execute")

    def collect(self):
        raise AssertionError("identity-only callbacks must never execute")


@pytest.mark.parametrize("contract", ["list", "empty_list", "short_tuple", "long_tuple",
                                     "noncallable_left", "noncallable_right"])
def test_main_entry_callback_contracts_fail_closed(contract):
    left, right = ArtificialCallback(), ArtificialCallback()
    callbacks = {"list": [left, right], "empty_list": [], "short_tuple": (left,),
                 "long_tuple": (left, right, ArtificialCallback()),
                 "noncallable_left": (None, right), "noncallable_right": (left, None)}[contract]
    result = check(callbacks=callbacks)
    expect(result, "INVALID", "CALLBACK_CONTRACT_INVALID")
    assert result["invalid_reason_codes"] == ["CALLBACK_CONTRACT_INVALID"]
    assert result["incomplete_reason_codes"] == []
    assert result["bridge_preview"] is None


@pytest.mark.parametrize("pair", ["function", "object", "method_owner", "owner_method", "methods"])
def test_callback_aliases(pair):
    def function():
        raise AssertionError("callback called")
    owner = ArtificialCallback()
    choices = {"function": (function, function), "object": (owner, owner),
               "method_owner": (owner.collect, owner), "owner_method": (owner, owner.collect),
               "methods": (owner.collect, owner.__call__)}
    assert check(callbacks=choices[pair])["reason_codes"] == ["SOURCE_ALIAS"]


def test_distinct_identity_only_callbacks_never_execute_or_establish_independence():
    assert check(callbacks=(ArtificialCallback(), ArtificialCallback()))["outcome"] == "CONSISTENT"


def test_alias_detection_does_not_use_arbitrary_attribute_access():
    class Opaque:
        def __getattribute__(self, name):
            raise AssertionError("attribute inspected")

        def __call__(self):
            raise AssertionError("called")
    assert check(callbacks=(Opaque(), Opaque()))["outcome"] == "CONSISTENT"


@pytest.mark.parametrize("shared", ["route", "capture", "frame", "verification"])
def test_shared_mutable_response_trees_alias(shared):
    data = request()
    left, right = data["routes"]
    if shared == "route":
        data["routes"][1] = left
    elif shared == "frame":
        right["capture"]["frames"][0] = left["capture"]["frames"][0]
    else:
        right[shared] = left[shared]
    expect(check(data), "INCOMPLETE", "SOURCE_ALIAS")


@pytest.mark.parametrize("field,value,code", [("starttime_ticks", 999, "PID_REUSE"),
    ("ppid", 42, "PROCESS_REPARENTED"), ("ppid", 200, "IDENTITY_INVALID"),
    ("pid", True, "INTEGER_INVALID")])
def test_exact_process_identity(field, value, code):
    data = request()
    data["routes"][0]["capture"]["frames"][0]["processes"][1]["identity"][field] = value
    if code in integration.INVALID_CODES:
        expect(check(rebind(data)), "INVALID", code)
    else:
        expect(check(rebind(data)), "INCOMPLETE", code, "SOURCE_DISAGREEMENT")


@pytest.mark.parametrize("where", ["reference", "capture", "observed", "process"])
def test_duplicate_pids_rejected(where):
    data = request()
    cap = data["routes"][0]["capture"]
    if where in ("reference", "capture"):
        target = data["reference"] if where == "reference" else cap
        target["roster"].append(copy.deepcopy(target["roster"][0]))
    elif where == "observed":
        cap["frames"][0]["observed_pids"].append(200)
    else:
        cap["frames"][0]["processes"].append(copy.deepcopy(cap["frames"][0]["processes"][0]))
    expect(check(rebind(data)), "INVALID", "DUPLICATE_IDENTITY")


@pytest.mark.parametrize("frame_index,appearance", [(0, "WORKER_LATE_OBSERVATION"),
                                                     (1, "WORKER_EARLY_LAST_OBSERVATION")])
def test_missing_worker_appearance_does_not_mean_absence_or_exit(frame_index, appearance):
    data = request()
    for route in data["routes"]:
        frame = route["capture"]["frames"][frame_index]
        frame["observed_pids"].remove(200)
        frame["processes"].pop()
    result = check(rebind(data))
    expect(result, "INCOMPLETE", "MISSING_WORKER", appearance)


def test_unregistered_and_out_of_roster_observations():
    data = request()
    data["routes"][0]["capture"]["frames"][0]["observed_pids"].append(300)
    result = check(rebind(data))
    expect(result, "INCOMPLETE", "UNKNOWN_PROCESS", "PARTIAL_FRAME", "SOURCE_DISAGREEMENT")


def test_unregistered_process_record_is_not_suppressed():
    data = request()
    extra = copy.deepcopy(data["routes"][0]["capture"]["frames"][0]["processes"][1])
    extra["identity"]["pid"] = 300
    extra["identity"]["starttime_ticks"] = 30
    for k, desc in enumerate(extra["descriptors"]):
        desc["path_id"] = desc["path_id"].replace("/200/", "/300/")
        if desc["role"] != "NSFS_TARGET":
            desc["st_ino"] += 100
    for read in extra["reads"]:
        read["path_id"] = read["path_id"].replace("/200/", "/300/")
        read["start_ns"] += 10
        read["end_ns"] += 10
    frame = data["routes"][0]["capture"]["frames"][0]
    frame["processes"].append(extra)
    frame["observed_pids"].append(300)
    result = check(rebind(data))
    expect(result, "INCOMPLETE", "UNKNOWN_PROCESS", "SOURCE_DISAGREEMENT")


def test_missing_capture_roster_registration_stays_incomplete():
    data = request()
    data["routes"][0]["capture"]["roster"].pop()
    result = check(rebind(data))
    expect(result, "INCOMPLETE", "ROSTER_DRIFT", "MISSING_WORKER")


def test_extra_capture_roster_registration_stays_incomplete():
    data = request()
    data["routes"][0]["capture"]["roster"].append({"pid": 300, "ppid": 100, "starttime_ticks": 30})
    expect(check(rebind(data)), "INCOMPLETE", "ROSTER_DRIFT", "UNKNOWN_PROCESS")


@pytest.mark.parametrize("field,value,code", [("starttime_ticks", 999, "PID_REUSE"),
                                             ("ppid", 42, "PROCESS_REPARENTED")])
def test_roster_drift_is_not_repaired(field, value, code):
    data = request()
    data["routes"][0]["capture"]["roster"][1][field] = value
    result = check(rebind(data))
    expect(result, "INCOMPLETE", "ROSTER_DRIFT", code)


@pytest.mark.parametrize("change,code", [
    ("boot", "BOOT_ID_CONFLICT"), ("uppercase_boot", "BOOT_ID_NONCANONICAL"),
    ("namespace", "NAMESPACE_CONTRADICTION"), ("namespace_label", "NAMESPACE_UNCOMPARABLE"),
    ("proc_type", "MOUNT_CONTRADICTION"), ("ns_type", "MOUNT_CONTRADICTION"),
    ("same_device", "MOUNT_CONTRADICTION"), ("same_mount", "MOUNT_CONTRADICTION"),
    ("descriptor_device", "MOUNT_CONTRADICTION"), ("descriptor_alias", "DESCRIPTOR_ALIAS"),
    ("changed_descriptor", "DESCRIPTOR_CHANGED"), ("target_inode", "NAMESPACE_CONTRADICTION"),
    ("descriptor_role", "DESCRIPTOR_INVALID")])
def test_environment_and_descriptor_contradictions(change, code):
    data = request()
    cap = data["routes"][0]["capture"]
    desc = cap["frames"][0]["processes"][0]["descriptors"]
    if change == "boot":
        cap["boot_id"] = "02345678-1234-5678-90ab-123456789abc"
    elif change == "uppercase_boot":
        cap["boot_id"] = BOOT.upper()
    elif change == "namespace":
        cap["namespace"]["value"] = 88
    elif change == "namespace_label":
        cap["namespace"] = {"kind": "LABEL", "value": "scope_a"}
    elif change == "proc_type":
        cap["procfs"]["filesystem"] = "nsfs"
    elif change == "ns_type":
        cap["nsfs"]["filesystem"] = "proc"
    elif change == "same_device":
        cap["nsfs"]["st_dev"] = cap["procfs"]["st_dev"]
    elif change == "same_mount":
        cap["nsfs"]["mount_id"] = cap["procfs"]["mount_id"]
    elif change == "descriptor_device":
        desc[0]["st_dev"] = 999
    elif change == "descriptor_alias":
        desc[1]["st_ino"] = desc[0]["st_ino"]
    elif change == "changed_descriptor":
        cap["frames"][1]["processes"][0]["descriptors"][0]["st_ino"] = 999
    elif change == "target_inode":
        desc[2]["st_ino"] = 88
    else:
        desc[0]["role"] = "NSFS_TARGET"
    expect(check(rebind(data)), "INVALID" if code in integration.INVALID_CODES else "INCOMPLETE", code)


@pytest.mark.parametrize("path", ["/proc/100/stat", "../stat", "pids/300/identity", "pids/100/status",
                                   "pids/100/../../secret"])
def test_symbolic_path_bounds(path):
    data = request()
    data["routes"][0]["capture"]["frames"][0]["processes"][0]["reads"][0]["path_id"] = path
    result = check(rebind(data))
    expect(result, "INVALID", "PATH_POLICY_VIOLATION")
    assert path not in json.dumps(result)


def test_duplicate_read_paths_are_named_explicitly():
    data = request()
    reads = data["routes"][0]["capture"]["frames"][0]["processes"][0]["reads"]
    reads[1]["path_id"] = reads[0]["path_id"]
    expect(check(rebind(data)), "INVALID", "DUPLICATE_READ")


@pytest.mark.parametrize("change,code", [("regression", "CLOCK_REGRESSION"),
    ("read_regression", "CLOCK_REGRESSION"), ("read_outside", "READ_WINDOW_INVALID"),
    ("duration", "FRAME_DURATION_EXCEEDED"), ("gap", "READ_GAP_EXCEEDED"),
    ("missing_frame", "FRAME_MISSING"), ("coverage", "COVERAGE_GAP"),
    ("partial", "PARTIAL_FRAME"), ("clock_domain", "CLOCK_DOMAIN_UNCOMPARABLE"),
    ("frame_outside", "READ_WINDOW_INVALID"), ("extra_frame", "FRAME_MISSING")])
def test_windows_and_coverage(change, code):
    data = request()
    frames = data["routes"][0]["capture"]["frames"]
    if change == "regression":
        frames[0]["end_ns"] = 99
    elif change == "read_regression":
        frames[0]["processes"][0]["reads"][0]["end_ns"] = 99
    elif change == "read_outside":
        frames[0]["processes"][0]["reads"][0]["end_ns"] = 151
    elif change == "duration":
        data["limits"]["max_read_ns"] = 49
    elif change == "gap":
        data["limits"]["max_gap_ns"] = 49
    elif change == "missing_frame":
        frames.pop()
    elif change == "coverage":
        data["reference"]["window"]["end_ns"] = 251
    elif change == "partial":
        frames[0]["read_complete"] = False
    elif change == "frame_outside":
        data["reference"]["window"]["start_ns"] = 101
    elif change == "extra_frame":
        extra = copy.deepcopy(frames[-1])
        extra.update(index=2, start_ns=250, end_ns=250)
        for process in extra["processes"]:
            for read in process["reads"]:
                read.update(start_ns=250, end_ns=250)
        frames.append(extra)
    else:
        data["reference"]["clock_kind"] = "LOCAL_MONOTONIC_NS"
    extra_codes = {"missing_frame": ("COVERAGE_GAP", "SOURCE_DISAGREEMENT"),
                   "extra_frame": ("SOURCE_DISAGREEMENT",), "partial": ("SOURCE_DISAGREEMENT",)}
    expect(check(rebind(data)), "INVALID" if code in integration.INVALID_CODES else "INCOMPLETE",
           code, *extra_codes.get(change, ()))


@pytest.mark.parametrize("reason", integration.READ_CODES)
def test_failed_supplied_reads_cannot_be_consistent(reason):
    data = request()
    read = data["routes"][0]["capture"]["frames"][0]["processes"][0]["reads"][0]
    read.update(status="FAILED", reason_codes=[reason], sha256=None)
    expect(check(rebind(data)), "INCOMPLETE", reason, "SOURCE_DISAGREEMENT")


@pytest.mark.parametrize("validator", list(integration.VERIFIERS))
@pytest.mark.parametrize("classification", ["INVALID", "INCOMPLETE", "CONSISTENT"])
def test_namespaced_upstream_outcome_precedence(validator, classification):
    data = request()
    _, bad, gaps, _ = integration.VERIFIERS[validator]
    route = data["routes"][0]
    route["verification"] = verification(route["capture"], validator,
        invalid=(bad[0],) if classification == "INVALID" else (),
        incomplete=(gaps[0],) if classification == "INCOMPLETE" else ())
    result = check(data)
    expect(result, classification, *(() if classification == "CONSISTENT" else ("UPSTREAM_" + classification,)))


@pytest.mark.parametrize("validator", list(integration.VERIFIERS))
def test_predecessor_read_skew_remains_namespaced(validator):
    data = request()
    route = data["routes"][0]
    route["verification"] = verification(route["capture"], validator, incomplete=("READ_SKEW_EXCEEDED",))
    result = check(data)
    expect(result, "INCOMPLETE", "UPSTREAM_INCOMPLETE")
    assert result["routes"][0]["verification"]["reason_codes"] == ["READ_SKEW_EXCEEDED"]


@pytest.mark.parametrize("validator", ["BRIDGE_H0", "PROBE_B3A"])
def test_injected_verification_cannot_authenticate_native(validator):
    data = request(True)
    route = data["routes"][0]
    route["verification"] = verification(route["capture"], validator)
    expect(check(data), "INVALID", "SOURCE_LABEL_CONFLICT")


def test_invalid_dominates_alias_and_upstream_incomplete():
    data = request()
    data["routes"][1]["provenance"]["collection_domain"] = data["routes"][0]["provenance"]["collection_domain"]
    data["routes"][0]["verification"] = verification(data["routes"][0]["capture"], invalid=["SCHEMA_INVALID"])
    data["routes"][1]["verification"] = verification(data["routes"][1]["capture"], incomplete=["READ_FAILED"])
    result = check(data)
    assert result["outcome"] == "INVALID"
    assert result["reason_codes"] == ["SOURCE_ALIAS", "UPSTREAM_INCOMPLETE", "UPSTREAM_INVALID"]


@pytest.mark.parametrize("change,code", [("unknown_code", "REASON_CODE_INVALID"),
    ("wrong_class", "OUTCOME_CONFLICT"), ("wrong_outcome", "OUTCOME_CONFLICT"),
    ("tamper", "DIGEST_INVALID"), ("bad_digest", "DIGEST_INVALID"),
    ("unknown_validator", "SCHEMA_INVALID"), ("wrong_upstream_schema", "SCHEMA_INVALID")])
def test_verification_summary_is_closed_and_bound(change, code):
    data = request()
    v = data["routes"][0]["verification"]
    if change == "unknown_code":
        v["reason_codes"] = ["INDEPENDENT_KERNEL_ATTESTED"]
    elif change == "wrong_class":
        v["reason_codes"] = ["READ_FAILED"]
    elif change == "wrong_outcome":
        v["outcome"] = "INVALID"
    elif change == "tamper":
        data["routes"][0]["capture"]["frames"][0]["read_complete"] = False
    elif change == "bad_digest":
        v["report_sha256"] = "z" * 64
    elif change == "unknown_validator":
        v["validator"] = "ASSESSMENT_D2B2"
    else:
        v["upstream_schema"] = "v99"
    extra_codes = ("PARTIAL_FRAME",) if change == "tamper" else ()
    expect(check(data), "INVALID", code, *extra_codes)


@pytest.mark.parametrize("schema", [integration.ADAPTER_SCHEMA, probe.SCHEMA + ".report",
    integration.ASSESSMENT_SCHEMA, bridge.SCHEMA + ".report"])
def test_raw_upstream_conversion_is_explicitly_not_implemented(schema):
    data = request()
    data["routes"][0]["capture"] = {"schema": schema}
    result = check(data)
    assert result["outcome"] == "INCOMPLETE"
    assert result["reason_codes"] == ["UPSTREAM_CONVERSION_NOT_IMPLEMENTED"]


def test_probe_report_schema_is_accepted_in_caller_asserted_summary():
    data = request()
    route = data["routes"][0]
    route["verification"] = verification(route["capture"], "PROBE_B3A")
    # Use the upstream report identity directly, independently of VERIFIERS.
    route["verification"]["upstream_schema"] = probe.SCHEMA + ".report"
    result = check(data)
    expect(result, "CONSISTENT")
    assert result["routes"][0]["verification"]["provenance"] == "CALLER_ASSERTED"


def test_emitted_probe_report_hits_explicit_conversion_boundary():
    # Even an upstream rejection is an actual report, with the output schema.
    # Invalid request shape must prevent these artificial callbacks from running.
    callback = ArtificialCallback()
    original = probe.probe_local_provenance({}, reader=callback, descriptor=callback, clock=callback)
    data = request()
    data["routes"][0]["capture"] = original.to_dict()
    expect(check(data), "INCOMPLETE", "UPSTREAM_CONVERSION_NOT_IMPLEMENTED")


def test_bare_probe_request_schema_is_not_an_upstream_report():
    data = request()
    data["routes"][0]["capture"] = {"schema": probe.SCHEMA}
    expect(check(data), "INVALID", "SCHEMA_INVALID")
    data = request()
    route = data["routes"][0]
    route["verification"] = verification(route["capture"], "PROBE_B3A")
    route["verification"]["upstream_schema"] = probe.SCHEMA
    expect(check(data), "INVALID", "SCHEMA_INVALID")


@pytest.mark.parametrize("known", [(), ("READ_FAILED",)])
@pytest.mark.parametrize("unknown", ["MISSPELLED_INTERNAL_CODE", "READ_SKEW_EXCEEDED"])
def test_unknown_internal_codes_are_sealed_as_invalid(known, unknown):
    result = integration._finish({unknown, *known}).to_dict()
    expect(result, "INVALID", "REASON_CODE_INVALID", *known)
    assert result["invalid_reason_codes"] == ["REASON_CODE_INVALID"]
    assert result["qualification"] == "NONQUALIFYING"
    assert result["structure_consistent"] is False


@pytest.mark.parametrize("raw", [b"{", b"\xff", b'{"a":1,"a":2}', b"NaN", b"Infinity", b"null"])
def test_strict_json_bytes(raw):
    result = integration.integrate_native_evidence(raw).to_dict()
    assert result["outcome"] == "INVALID"
    assert result["reason_codes"] == (["DUPLICATE_KEY"] if raw == b'{"a":1,"a":2}' else
                                      ["SCHEMA_INVALID"] if raw == b"null" else ["INPUT_NOT_JSON"])


def test_raw_bytes_digest_is_distinct_from_canonical_digest():
    data = request()
    raw = json.dumps(data).encode()
    first = integration.integrate_native_evidence(raw)
    second = integration.integrate_native_evidence(b"  " + raw)
    assert first.to_dict()["outcome"] == "CONSISTENT"
    assert first.to_dict()["request_sha256"] == second.to_dict()["request_sha256"]
    assert first.to_dict()["raw_input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert first.to_dict()["raw_input_sha256"] != second.to_dict()["raw_input_sha256"]


@pytest.mark.parametrize("change,code", [("bool_int", "INTEGER_INVALID"), ("float", "INPUT_NOT_JSON"),
    ("nan", "INPUT_NOT_JSON"), ("nul", "INPUT_NOT_JSON"), ("surrogate", "INPUT_NOT_JSON"),
    ("cycle", "INPUT_NOT_JSON"), ("depth", "INPUT_CAP_EXCEEDED"),
    ("nodes", "INPUT_CAP_EXCEEDED"), ("string", "INPUT_CAP_EXCEEDED"),
    ("unknown_field", "SCHEMA_INVALID"), ("schema", "SCHEMA_INVALID"), ("subclass", "INPUT_NOT_JSON")])
def test_input_hardening(change, code):
    data = request()
    if change == "bool_int":
        data["reference"]["window"]["start_ns"] = True
    elif change in ("float", "nan", "nul", "surrogate"):
        data["extra"] = {"float": 1.5, "nan": float("nan"), "nul": "\x00", "surrogate": "\ud800"}[change]
    elif change == "cycle":
        data["extra"] = data
    elif change == "depth":
        value = []
        for _ in range(integration.MAX_DEPTH + 1):
            value = [value]
        data["extra"] = value
    elif change == "nodes":
        data["extra"] = [None] * integration.MAX_NODES
    elif change == "string":
        data["extra"] = "a" * (integration.MAX_STRING + 1)
    elif change == "unknown_field":
        data["extra"] = None
    elif change == "schema":
        data["schema"] += ".v2"
    else:
        class Active(dict):
            def items(self):
                raise AssertionError("subclass executed")
        data["extra"] = Active()
    result = integration.integrate_native_evidence(data).to_dict()
    assert result["reason_codes"] == [code]


def test_encoded_payload_size_cap():
    result = integration.integrate_native_evidence(b" " * (integration.MAX_BYTES + 1)).to_dict()
    assert result["reason_codes"] == ["INPUT_CAP_EXCEEDED"]


@pytest.mark.parametrize("label", ["native", "authen-tic", "QUALIFIED", "attest", "corroborated", "ver_ified",
    "injected_test_only", "not_established", "consistent", "../secret", "a/b", "a\n", "a" * 65])
def test_label_injection(label):
    data = request()
    data["routes"][0]["provenance"]["route_id"] = label
    expect(check(data), "INVALID", "LABEL_INVALID")


def test_reports_are_deterministic_detached_frozen_and_do_not_leak_labels():
    data = request()
    data["routes"][0]["provenance"]["route_id"] = "private_secret_label"
    before = copy.deepcopy(data)
    first = integration.integrate_native_evidence(data)
    assert first.serialized == integration.integrate_native_evidence(data).serialized
    assert first.sha256 == hashlib.sha256(first.serialized.encode()).hexdigest()
    assert data == before
    detached = first.to_dict()
    detached["qualification"] = "anything"
    detached["routes"].clear()
    assert first.to_dict()["qualification"] == "NONQUALIFYING"
    assert first.to_dict()["routes"]
    with pytest.raises(FrozenInstanceError):
        first.serialized = "changed"
    data["routes"][0]["capture"]["frames"].clear()
    assert first.to_dict()["outcome"] == "CONSISTENT"
    for secret in ("private_secret_label", "artificial bytes", "pids/100", "/proc", "vmrss", "vmhwm"):
        assert secret not in first.serialized


def bridge_request():
    return {"schema": bridge.SCHEMA, "mode": "INJECTED_TEST_ONLY", "native_opt_in": False,
            "clock_domain": bridge.CLOCK_DOMAIN, "sweeps": 2,
            "limits": {"max_elapsed_ns": 100000, "max_read_ns": 100, "max_gap_ns": 100,
                       "max_age_ns": 100000, "max_source_skew_ns": 1000}}


class BridgeFixture:
    """Finite artificial operation table. No operating-system descriptors."""

    def __init__(self, name, hook=None):
        self.name, self.hook, self.sequence, self.next_handle = name, hook, 0, 0
        self.active = {}
        self.paths = ["boot_id", "proc_mount"] + [f"pids/{p['pid']}/{leaf}" for p in identities()
            for leaf in ("identity", "ns_link", "ns_target")]

    def provider(self):
        return bridge.Provider(self.name, self.name + "_source", self.name + "_fixture", self)

    def __call__(self, op):
        assert type(op) is bridge.Operation and op.path_id in self.paths and op.sweep in (0, 1)
        path = op.path_id
        if self.hook:
            self.hook(op)
        if op.action == "OPEN":
            self.next_handle += 1
            handle = bridge.Handle(self.name + str(self.next_handle))
            self.active[handle.token] = path
            return handle
        assert type(op.handle) is bridge.Handle and self.active[op.handle.token] == path
        if op.action == "CLOSE":
            del self.active[op.handle.token]
            return None
        identity = next((p for p in identities() if path.startswith(f"pids/{p['pid']}/")), None)
        target, link = path.endswith("/ns_target"), path.endswith("/ns_link")
        if op.action == "DESCRIBE":
            return {"path_id": path, "role": "NSFS_TARGET" if target else "PROCFS_LINK_LOCATION" if link else "PROCFS_OBJECT",
                    "st_dev": 4 if target else 5, "st_ino": 77 if target else 100 + self.paths.index(path),
                    "mount_id": 10 if target else 9, "filesystem": "nsfs" if target else "proc", "symlink": link,
                    "binding": "INJECTED_DESCRIPTOR_RELATIVE_NO_FOLLOW", "identity": identity}
        assert op.action == "READ" and op.max_bytes == bridge.MAX_RAW_BYTES + 1
        if path == "boot_id":
            payload = {"boot_id": BOOT}
        elif path == "proc_mount":
            payload = {"mount_id": 9, "st_dev": 5, "filesystem": "proc"}
        elif path.endswith("/identity"):
            payload = {"identity": identity, "cpu_ticks": 50, "vmhwm_kib": 100, "rss_kib": 80}
        elif link:
            payload = {"namespace_inode": 77}
        else:
            payload = {"st_dev": 4, "st_ino": 77}
        self.sequence += 1
        return {"payload": payload, "raw": None, "sha256": integration.digest(payload),
                "method": "INJECTED_STRUCTURED", "declared_origin": "INJECTED_TEST_ONLY",
                "sequence": self.sequence, "status": "OK", "reason": None}


class ArtificialClock:
    def __init__(self):
        self.tick = 1000

    def __call__(self):
        self.tick += 1
        return self.tick


def preview(data=None, hook=None):
    left, right = BridgeFixture("left", hook), BridgeFixture("right")
    report = integration.preview_injected_bridge(request() if data is None else data, bridge_request(),
        providers=(left.provider(), right.provider()), clock=ArtificialClock())
    assert not left.active and not right.active
    return report


def test_preview_preserves_actual_bridge_digest_without_trust_promotion():
    report = preview()
    original = bridge.acquire_provenance_bridge(identities(), bridge_request(),
        providers=(BridgeFixture("left").provider(), BridgeFixture("right").provider()), clock=ArtificialClock())
    result = report.to_dict()
    assert result["outcome"] == result["bridge_preview"]["outcome"] == "CONSISTENT"
    assert result["bridge_preview"]["sha256"] == hashlib.sha256(original.serialized.encode()).hexdigest()
    assert result["source_origin_authenticated"] is False
    assert result["qualification"] == "NONQUALIFYING"


def test_bridge_invalid_preview_has_exact_integration_reasons():
    configured = bridge_request()
    # Valid integration input; only the artificial bridge request is invalid.
    # H0 rejects before registering its roster or calling providers/the clock.
    configured["sweeps"] = 3

    def forbidden(op):
        raise AssertionError("provider executed")

    left, right = BridgeFixture("left", forbidden), BridgeFixture("right", forbidden)
    providers = (left.provider(), right.provider())
    result = integration.preview_injected_bridge(request(), configured,
        providers=providers, clock=ArtificialCallback()).to_dict()
    expect(result, "INVALID", "PREVIEW_ROSTER_MISMATCH", "UPSTREAM_INVALID")
    assert result["invalid_reason_codes"] == ["PREVIEW_ROSTER_MISMATCH", "UPSTREAM_INVALID"]
    assert result["incomplete_reason_codes"] == []
    assert result["bridge_preview"]["outcome"] == "INVALID"
    assert result["bridge_preview"]["reason_codes"] == ["SCHEMA_INVALID"]
    assert result["qualification"] == result["bridge_preview"]["qualification"] == "NONQUALIFYING"
    assert result["source_origin_authenticated"] is False
    assert not left.active and not right.active


@pytest.mark.parametrize("change,codes", [
    ("partial", ("PARTIAL_FRAME",)),
    ("missing_frame", ("COVERAGE_GAP", "FRAME_MISSING")),
])
def test_incomplete_base_frames_skip_bridge_preview(monkeypatch, change, codes):
    data = request()
    for route in data["routes"]:
        frames = route["capture"]["frames"]
        if change == "partial":
            frames[0]["read_complete"] = False
        else:
            frames.pop()
    rebind(data)
    base = check(data)
    expect(base, "INCOMPLETE", *codes)

    def forbidden(*args, **kwargs):
        raise AssertionError("bridge entered for incomplete base frames")

    monkeypatch.setattr(bridge, "acquire_provenance_bridge", forbidden)
    result = integration.preview_injected_bridge(data, bridge_request(),
        providers=(ArtificialCallback(), ArtificialCallback()), clock=ArtificialCallback()).to_dict()
    expect(result, "INCOMPLETE", *codes)
    assert result["bridge_preview"] is None
    assert result == base


def test_native_preview_denied_before_bridge_or_callbacks(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("bridge entered")
    monkeypatch.setattr(bridge, "acquire_provenance_bridge", forbidden)
    result = integration.preview_injected_bridge(request(True), bridge_request(),
        providers=(ArtificialCallback(), ArtificialCallback()), clock=ArtificialCallback()).to_dict()
    assert result["reason_codes"] == ["NATIVE_MODE_DENIED"]
    assert result["bridge_preview"] is None


def test_bridge_native_opt_in_denied_before_any_callback():
    data = bridge_request()
    data["native_opt_in"] = adapter.NATIVE_OPT_IN
    result = integration.preview_injected_bridge(request(), data,
        providers=(ArtificialCallback(), ArtificialCallback()), clock=ArtificialCallback()).to_dict()
    assert result["reason_codes"] == ["NATIVE_MODE_DENIED"]


def test_preview_input_mutation_detected():
    data = request()
    def change(op):
        data["limits"]["max_gap_ns"] = 61
    result = preview(data, change).to_dict()
    assert result["reason_codes"] == ["INPUT_CHANGED"]


def test_preview_malformed_input_mutation_is_still_input_changed():
    data = request()
    def change(op):
        data["unexpected_cycle"] = data
    result = preview(data, change).to_dict()
    assert result["reason_codes"] == ["INPUT_CHANGED"]


@pytest.mark.parametrize("target", ["bridge_request", "providers"])
def test_preview_checks_caller_request_and_provider_list_stability(target):
    configured = bridge_request()
    providers = []
    def change(op):
        if target == "bridge_request":
            configured["limits"]["max_gap_ns"] = 101
        else:
            providers[1] = replacement
    left, right, replacement_fixture = BridgeFixture("left", change), BridgeFixture("right"), BridgeFixture("other")
    replacement = replacement_fixture.provider()
    providers.extend((left.provider(), right.provider()))
    result = integration.preview_injected_bridge(request(), configured, providers=providers, clock=ArtificialClock()).to_dict()
    assert result["reason_codes"] == ["INPUT_CHANGED"]
    assert not left.active and not right.active and not replacement_fixture.active


def test_preview_failure_propagates_without_exception_text():
    def fail(op):
        if op.action == "READ":
            raise RuntimeError("private host path /home/secret")
    report = preview(hook=fail)
    assert report.to_dict()["outcome"] == "INCOMPLETE"
    assert "UPSTREAM_INCOMPLETE" in report.to_dict()["reason_codes"]
    assert "private host path" not in report.serialized


def test_import_and_construction_are_inert_and_source_has_no_native_imports():
    # Replay module execution with dependencies already imported. Interpreter
    # source loading is the one permitted source read, not evidence collection.
    source = MODULE_PATH.read_text()
    namespace = {"__name__": integration.__name__}
    exec(compile(source, str(MODULE_PATH), "exec"), namespace)
    report = namespace["IntegrationReport"]("{}")
    assert report.to_dict() == {}
    tree = ast.parse(source)
    allowed = {"dataclasses", "types", "hashlib", "json", "re", "scripts.benchmarks"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module in allowed
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            assert name not in {"open", "stat", "lstat", "readlink", "fork", "spawn", "sysconf", "exec", "eval",
                                "getattr", "hasattr", "__import__", "NativeProcfsAdapter", "_NativeIO"}


def test_schema_and_reason_vocabulary_drift_guards():
    assert integration.ADAPTER_SCHEMA == adapter.RESULT_SCHEMA
    assert integration.ADAPTER_INVALID == adapter.INVALID_CODES
    assert integration.ADAPTER_INVALID + integration.ADAPTER_INCOMPLETE == adapter.KNOWN_CODES
    assert integration.PROBE_SCHEMA == probe.SCHEMA + ".report"
    assert integration.PROBE_INVALID == probe.INVALID_CODES
    assert integration.PROBE_INCOMPLETE == probe.INCOMPLETE_CODES
    assert not set(integration.INVALID_CODES) & set(integration.INCOMPLETE_CODES)
    assert {"FRAME_DURATION_EXCEEDED", "ROUTE_SKEW_EXCEEDED"} <= set(integration.INCOMPLETE_CODES)
    assert "READ_SKEW_EXCEEDED" not in integration.INVALID_CODES + integration.INCOMPLETE_CODES


@pytest.mark.parametrize("action", ["proc", "sys", "clock", "spawn", "write", "stat", "socket"])
def test_guard_negative_controls(action, forbid_native_io):
    operations = {"proc": lambda: builtins.open("/proc/self/stat"), "sys": lambda: io.open("/sys/kernel"),
                  "clock": time.monotonic_ns, "spawn": lambda: subprocess.run(["never-executed"]),
                  "write": lambda: builtins.open("/tmp/never-written", "w"),
                  "stat": lambda: os.stat("/proc"), "socket": socket.socket}
    with pytest.raises(HarnessViolation):
        operations[action]()
    assert forbid_native_io == ["forbidden operation"]
    forbid_native_io.clear()
