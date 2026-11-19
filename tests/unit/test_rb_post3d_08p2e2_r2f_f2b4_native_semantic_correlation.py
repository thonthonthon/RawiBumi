"""Artificial supplied facts only. The orchestrator executes this suite."""

import ast
import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path

import pytest

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_native_semantic_correlation as semantic

integration = semantic.integration
ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_native_semantic_correlation.py"
BOOT = "12345678-1234-5678-90ab-123456789abc"
TRUST = {
    "qualification": "NONQUALIFYING", "independence": "INDEPENDENCE_NOT_ESTABLISHED",
    "source_origin_authenticated": False, "worker_roster_complete": False,
    "production_memory_qualified": False, "peak_observed": False,
    "native_origin_authentication": "NOT_IMPLEMENTED", "live_native_integration": "NOT_IMPLEMENTED",
    "independent_kernel_attestation": "NOT_ESTABLISHED", "worker_absence_proven": False,
    "holder_release": "NOT_ESTABLISHED", "production_memory_qualification": "INCONCLUSIVE",
    "production_chronological_peak": "NOT_OBSERVED", "production_workload_measured": False,
    "bound_claim": "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK", "atomic_snapshot": False,
    "verification_provenance": "CALLER_ASSERTED", "memo_cap": 256,
    "continuous_time_coverage": False, "merged_rss_peak": False,
}


@pytest.fixture(autouse=True)
def inert_seams(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("acquisition or preview reached")

    # Module-local seams only; pytest's filesystem and clock hooks stay intact.
    monkeypatch.setattr(integration, "preview_injected_bridge", forbidden)
    monkeypatch.setattr(integration.bridge, "acquire_provenance_bridge", forbidden)
    yield
    assert calls == []


def roster():
    return [{"pid": 100, "ppid": 1, "starttime_ticks": 10},
            {"pid": 200, "ppid": 100, "starttime_ticks": 20}]


def environment(native=False):
    return {"boot_id": BOOT, "namespace": {"kind": "INODE", "value": 77},
            "procfs": {"filesystem": "proc", "mount_id": 9, "st_dev": 5},
            "nsfs": {"filesystem": "nsfs", "mount_id": 10, "st_dev": 4},
            "clock_kind": "LOCAL_MONOTONIC_NS" if native else "INJECTED_MONOTONIC_NS"}


def request(native=False, frames=2):
    state = "NATIVE_PROCFS_UNVERIFIED" if native else "INJECTED_TEST_ONLY"
    routes = []
    for label in ("left", "right"):
        capture = {"schema": integration.CAPTURE_SCHEMA, "source_state": state,
                   "source_kind": integration.ORIGINS[state][0],
                   "origin_attestation": integration.ORIGINS[state][1],
                   **environment(native), "roster": roster(), "frames": []}
        for index in range(frames):
            start = 100 + 100 * index
            frame = {"index": index, "start_ns": start, "end_ns": start + 50,
                     "observed_pids": [100, 200], "processes": [], "read_complete": True, "reason_codes": []}
            tick = start
            for n, identity in enumerate(roster()):
                process = {"identity": identity, "descriptors": [], "reads": []}
                for k, leaf in enumerate(("identity", "ns_link", "ns_target")):
                    path = f"pids/{identity['pid']}/{leaf}"
                    target = leaf == "ns_target"
                    process["descriptors"].append({"path_id": path,
                        "role": "NSFS_TARGET" if target else "PROCFS_LINK_LOCATION" if leaf == "ns_link" else "PROCFS_OBJECT",
                        **capture["nsfs" if target else "procfs"], "st_ino": 77 if target else 1000 + 10 * n + k})
                    process["reads"].append({"path_id": path, "start_ns": tick, "end_ns": tick + 1,
                        "status": "OK", "sha256": hashlib.sha256(b"artificial bytes").hexdigest(),
                        "byte_count": 16, "reason_codes": []})
                    tick += 2
                frame["processes"].append(process)
            capture["frames"].append(frame)
        schema, _, _, success = integration.VERIFIERS["ADAPTER_D2B2"]
        routes.append({"provenance": {**{key: label + "_" + key for key in
            ("route_id", "provider_id", "callback_id", "method_id", "collection_domain")}, "data_origin": state},
            "capture": capture, "verification": {"schema": integration.VERIFICATION_SCHEMA,
                "validator": "ADAPTER_D2B2", "upstream_schema": schema, "outcome": success,
                "reason_codes": [], "invalid_reason_codes": [], "incomplete_reason_codes": [],
                "report_sha256": "a" * 64, "capture_sha256": integration.digest(capture)}})
    return {"schema": integration.SCHEMA, "mode": "SUPPLIED_ONLY", "native_opt_in": False,
            "reference": {**environment(native), "roster": roster(),
                          "window": {"start_ns": 100, "end_ns": 100 * frames + 50}, "frame_count": frames},
            "routes": routes, "limits": {"max_read_ns": 60, "max_gap_ns": 60, "max_route_skew_ns": 5}}


def rebind(data):
    for route in data["routes"]:
        route["verification"]["capture_sha256"] = integration.digest(route["capture"])
    return data


def right(data, frame=0):
    return data["routes"][1]["capture"]["frames"][frame]


def trust(result):
    for key, value in TRUST.items():
        assert type(result[key]) is type(value)
        assert result[key] == value


def check(data=None, **kwargs):
    data = request() if data is None else data
    before = copy.deepcopy(data)
    predecessor = integration.integrate_native_evidence(data, **kwargs)
    report = semantic.correlate_native_semantics(data, **kwargs)
    assert data == before
    result = report.to_dict()
    trust(result)
    assert result["predecessor_report_embedded"] == predecessor.to_dict()
    assert result["predecessor_report_sha256"] == predecessor.sha256
    assert result["predecessor_outcome"] == predecessor.to_dict()["outcome"]
    assert result["predecessor_reason_codes"] == predecessor.to_dict()["reason_codes"]
    assert set(result["predecessor_reason_codes"]) <= set(result["reason_codes"])
    severity = {"CONSISTENT": 0, "INCOMPLETE": 1, "INVALID": 2}
    assert severity[result["outcome"]] >= severity[result["predecessor_outcome"]]
    for layer in (result, result["semantic"]):
        bad, gaps = set(layer["invalid_reason_codes"]), set(layer["incomplete_reason_codes"])
        assert not bad & gaps
        assert layer["reason_codes"] == sorted(bad | gaps)
        assert layer["outcome"] == ("INVALID" if bad else "INCOMPLETE" if gaps else "CONSISTENT")
    return result


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("frames", [2, 3, 8, 32])
def test_fully_covered_identity_only(native, frames):
    result = check(request(native, frames))
    assert result["outcome"] == "CONSISTENT"
    assert result["semantic"]["classification"] == "STABLE_IDENTITY_CORRELATED"
    assert result["semantic"]["volatile_divergences"] == []
    assert {r["source_state"] for r in result["predecessor_report_embedded"]["routes"]} == {
        "NATIVE_PROCFS_UNVERIFIED" if native else "INJECTED_TEST_ONLY"}


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("change_count", [False, True])
def test_volatile_divergence_preserves_original_verdict(native, change_count):
    data = request(native)
    read = right(data)["processes"][0]["reads"][0]
    original_hash = read["sha256"]
    read["sha256"] = "b" * 64
    if change_count:
        read["byte_count"] += 1
    result = check(rebind(data))
    assert result["outcome"] == result["predecessor_outcome"] == "INCOMPLETE"
    assert result["reason_codes"] == result["predecessor_reason_codes"] == ["SOURCE_DISAGREEMENT"]
    assert result["semantic"]["classification"] == "STABLE_IDENTITY_CORRELATED"
    assert result["semantic"]["volatile_divergences"] == [{"frame_index": 0,
        "path_id": "pids/100/identity", "reason": "VOLATILE_IDENTITY_READ_BYTES_DIFFER",
        "left_sha256": original_hash, "right_sha256": "b" * 64,
        "left_byte_count": 16, "right_byte_count": 17 if change_count else 16}]


@pytest.mark.parametrize("leaf", [0, 1, 2])
def test_equal_hash_unequal_size_is_invalid(leaf):
    data = request()
    right(data)["processes"][0]["reads"][leaf]["byte_count"] += 1
    result = check(rebind(data))
    assert result["outcome"] == "INVALID"
    assert "READ_SIZE_CONTRADICTION" in result["reason_codes"]
    assert result["semantic"]["classification"] != "STABLE_IDENTITY_CORRELATED"


@pytest.mark.parametrize("leaf", [1, 2])
def test_namespace_read_bytes_are_not_volatile(leaf):
    data = request()
    right(data)["processes"][0]["reads"][leaf]["sha256"] = "b" * 64
    result = check(rebind(data))
    assert result["semantic"]["classification"] == "NOT_CORRELATED"
    assert result["reason_codes"] == ["SOURCE_DISAGREEMENT", "STABLE_READ_DISAGREEMENT"]


@pytest.mark.parametrize("field,code", [("ppid", "PROCESS_REPARENTED"), ("starttime_ticks", "PID_REUSE")])
@pytest.mark.parametrize("frame", [0, 1])
def test_identity_changes_across_routes_and_frames(field, code, frame):
    data = request()
    right(data, frame)["processes"][1]["identity"][field] += 1
    result = check(rebind(data))
    assert result["outcome"] == "INCOMPLETE"
    assert result["predecessor_reason_codes"] == sorted([code, "SOURCE_DISAGREEMENT"])
    assert result["semantic"]["classification"] == "NOT_EVALUATED"


@pytest.mark.parametrize("field,code", [("boot_id", "BOOT_ID_CONFLICT"),
    ("namespace", "NAMESPACE_CONTRADICTION"), ("procfs", "MOUNT_CONTRADICTION"), ("nsfs", "MOUNT_CONTRADICTION")])
def test_environment_conflicts(field, code):
    data = request()
    cap = data["routes"][1]["capture"]
    if field == "boot_id":
        cap[field] = "22345678-1234-5678-90ab-123456789abc"
    elif field == "namespace":
        cap[field]["value"] += 1
    else:
        cap[field]["mount_id"] += 2
    result = check(rebind(data))
    assert result["outcome"] == "INVALID"
    assert code in result["predecessor_reason_codes"]


@pytest.mark.parametrize("equal", [False, True])
def test_label_namespaces_never_correlate(equal):
    data = request()
    data["reference"]["namespace"] = {"kind": "LABEL", "value": "fixture_one"}
    for index, route in enumerate(data["routes"]):
        route["capture"]["namespace"] = {"kind": "LABEL", "value": "fixture_one" if equal or not index else "fixture_two"}
    result = check(rebind(data))
    assert result["predecessor_reason_codes"] == ["NAMESPACE_UNCOMPARABLE"]
    assert result["semantic"]["classification"] == "NOT_EVALUATED"


@pytest.mark.parametrize("field,code", [("st_ino", "DESCRIPTOR_ALIAS"), ("st_dev", "MOUNT_CONTRADICTION"),
    ("mount_id", "MOUNT_CONTRADICTION"), ("path_id", "PATH_POLICY_VIOLATION"), ("role", "DESCRIPTOR_INVALID")])
def test_descriptor_conflicts(field, code):
    data = request()
    desc = right(data)["processes"][0]["descriptors"][0]
    desc[field] = desc[field] + 1 if type(desc[field]) is int else "bad_path"
    result = check(rebind(data))
    assert result["outcome"] == "INVALID"
    assert result["predecessor_reason_codes"] == [code]
    assert result["semantic"]["reason_codes"] == [code]
    assert result["semantic"]["classification"] == "NOT_EVALUATED"


def test_cross_route_stable_descriptor_disagreement():
    data = request()
    for frame in data["routes"][1]["capture"]["frames"]:
        frame["processes"][0]["descriptors"][0]["st_ino"] += 100
    result = check(rebind(data))
    assert result["predecessor_reason_codes"] == ["SOURCE_DISAGREEMENT"]
    assert result["semantic"]["reason_codes"] == ["STABLE_IDENTITY_MISMATCH"]


@pytest.mark.parametrize("code", ["READ_FAILED", "PROCESS_VANISHED", "PERMISSION_DENIED"])
@pytest.mark.parametrize("both", [False, True])
def test_failed_reads_never_correlate(code, both):
    data = request()
    for route in data["routes"] if both else data["routes"][1:]:
        read = route["capture"]["frames"][0]["processes"][0]["reads"][0]
        read.update(status="FAILED", sha256=None, byte_count=0, reason_codes=[code])
    result = check(rebind(data))
    assert result["outcome"] == "INCOMPLETE"
    assert code in result["predecessor_reason_codes"]
    assert result["semantic"]["classification"] == "NOT_EVALUATED"


@pytest.mark.parametrize("edge,code", [(0, "WORKER_LATE_OBSERVATION"), (1, "WORKER_EARLY_LAST_OBSERVATION")])
def test_missing_first_or_last_worker(edge, code):
    data = request()
    frame = right(data, edge)
    frame["observed_pids"].pop()
    frame["processes"].pop()
    result = check(rebind(data))
    assert result["outcome"] == "INCOMPLETE"
    assert code in result["predecessor_reason_codes"]
    assert "MISSING_WORKER" in result["predecessor_reason_codes"]


@pytest.mark.parametrize("case,codes", [
    ("missing_read", ["PARTIAL_FRAME", "SOURCE_DISAGREEMENT"]),
    ("partial", ["PARTIAL_FRAME", "SOURCE_DISAGREEMENT"]),
    ("missing_frame", ["COVERAGE_GAP", "FRAME_MISSING", "SOURCE_DISAGREEMENT"]),
    ("extra_pid", ["PARTIAL_FRAME", "SOURCE_DISAGREEMENT", "UNKNOWN_PROCESS"]),
    ("different_pid", ["PATH_POLICY_VIOLATION", "UNKNOWN_PROCESS"]),
    ("roster_missing", ["MISSING_WORKER", "ROSTER_DRIFT"]),
    ("roster_extra", ["ROSTER_DRIFT", "UNKNOWN_PROCESS"]),
    ("roster_reordered", ["ROSTER_DRIFT"]), ("duplicate_pid", ["DUPLICATE_IDENTITY"]),
    ("duplicate_read", ["DUPLICATE_READ"])])
def test_roster_presence_and_frame_structure(case, codes):
    data = request()
    frame = right(data)
    cap = data["routes"][1]["capture"]
    if case == "missing_read":
        frame["processes"][0]["reads"].pop()
    elif case == "partial":
        frame["read_complete"] = False
    elif case == "missing_frame":
        cap["frames"].pop()
    elif case == "extra_pid":
        frame["observed_pids"].append(300)
    elif case == "different_pid":
        frame["processes"][0]["identity"]["pid"] = 300
    elif case == "roster_missing":
        cap["roster"].pop()
    elif case == "roster_extra":
        cap["roster"].append({"pid": 300, "ppid": 100, "starttime_ticks": 30})
    elif case == "roster_reordered":
        cap["roster"].reverse()
    elif case == "duplicate_pid":
        frame["observed_pids"].append(100)
    else:
        frame["processes"][0]["reads"][1] = copy.deepcopy(frame["processes"][0]["reads"][0])
    result = check(rebind(data))
    assert result["predecessor_reason_codes"] == codes
    assert result["semantic"]["reason_codes"] == codes
    assert result["outcome"] == ("INVALID" if set(codes) & set(semantic.INVALID_CODES) else "INCOMPLETE")
    assert result["semantic"]["classification"] == "NOT_EVALUATED"


@pytest.mark.parametrize("endpoint", ["frame_start", "frame_end", "read_start", "read_end"])
@pytest.mark.parametrize("delta", [5, 6])
def test_inclusive_route_boundaries(endpoint, delta):
    data = request()
    if endpoint == "frame_start":
        frame = right(data, 1)
        frame["start_ns"] += delta
        for process in frame["processes"]:
            for read in process["reads"]:
                read["start_ns"] += delta
                read["end_ns"] += delta
    elif endpoint == "frame_end":
        right(data)["end_ns"] -= delta
    else:
        read = right(data)["processes"][-1]["reads"][-1]
        read["end_ns"] += delta
        if endpoint == "read_start":
            read["start_ns"] += delta
    result = check(rebind(data))
    assert result["predecessor_reason_codes"] == ([] if delta == 5 else ["ROUTE_SKEW_EXCEEDED"])
    assert result["semantic"]["classification"] == ("STABLE_IDENTITY_CORRELATED" if delta == 5 else "NOT_EVALUATED")


@pytest.mark.parametrize("duration_limit", [49, 50])
def test_inclusive_duration(duration_limit):
    data = request()
    data["limits"]["max_read_ns"] = duration_limit
    result = check(data)
    assert result["predecessor_reason_codes"] == (["FRAME_DURATION_EXCEEDED"] if duration_limit == 49 else [])


@pytest.mark.parametrize("gap_limit", [49, 50])
def test_gap_boundary(gap_limit):
    data = request()
    data["limits"]["max_gap_ns"] = gap_limit
    result = check(data)
    assert result["predecessor_reason_codes"] == (["READ_GAP_EXCEEDED"] if gap_limit == 49 else [])


@pytest.mark.parametrize("delta", [5, 6])
def test_closed_overlap_boundary_with_point_reads(delta):
    data = request()
    for route in data["routes"]:
        read = route["capture"]["frames"][0]["processes"][-1]["reads"][-1]
        read["end_ns"] = read["start_ns"]
    read = right(data)["processes"][-1]["reads"][-1]
    read["start_ns"] += delta
    read["end_ns"] += delta
    result = check(rebind(data))
    assert result["outcome"] == ("CONSISTENT" if delta == 5 else "INCOMPLETE")
    # The predecessor gate rejects +1 ns before the subordinate rule runs.
    assert result["semantic"]["reason_codes"] == ([] if delta == 5 else ["ROUTE_SKEW_EXCEEDED"])
    codes = set()
    semantic._paired_time({"start_ns": 0, "end_ns": 0}, {"start_ns": delta, "end_ns": delta}, 5, codes)
    assert codes == (set() if delta == 5 else {"ROUTE_SKEW_EXCEEDED", "TEMPORAL_NONOVERLAP"})


@pytest.mark.parametrize("case,codes", [("outside", ["READ_WINDOW_INVALID"]), ("coverage", ["COVERAGE_GAP"]),
    ("clock", ["CLOCK_DOMAIN_UNCOMPARABLE"]), ("origin", ["SOURCE_LABEL_CONFLICT"]),
    ("mixed", ["CLOCK_DOMAIN_UNCOMPARABLE", "SOURCE_LABEL_CONFLICT"]), ("status", ["OUTCOME_CONFLICT"])])
def test_windows_origins_and_status_fail_closed(case, codes):
    data = request()
    if case == "outside":
        data["reference"]["window"]["end_ns"] -= 1
    elif case == "coverage":
        data["reference"]["window"]["end_ns"] += 1
    elif case == "clock":
        data["reference"]["clock_kind"] = "LOCAL_MONOTONIC_NS"
    elif case == "origin":
        data["routes"][1]["provenance"]["data_origin"] = "NATIVE_PROCFS_UNVERIFIED"
    elif case == "mixed":
        data["routes"][1] = request(True)["routes"][1]
    else:
        right(data)["processes"][0]["reads"][0]["status"] = "FAILED"
    result = check(rebind(data))
    assert result["predecessor_reason_codes"] == codes
    assert result["semantic"]["reason_codes"] == codes
    assert result["semantic"]["classification"] == "NOT_EVALUATED"


@pytest.mark.parametrize("key", ["route_id", "provider_id", "callback_id", "method_id", "collection_domain"])
def test_source_labels_must_not_alias(key):
    data = request()
    data["routes"][1]["provenance"][key] = data["routes"][0]["provenance"][key]
    assert check(data)["predecessor_reason_codes"] == ["SOURCE_ALIAS"]


def test_container_aliases_preserve_predecessor_and_add_stricter_policy():
    data = request()
    data["routes"][1]["capture"] = data["routes"][0]["capture"]
    result = check(data)
    assert result["predecessor_reason_codes"] == ["SOURCE_ALIAS"]
    assert result["outcome"] == "INVALID"
    assert "INPUT_ALIAS" in result["reason_codes"]
    data = request()
    right(data, 1)["processes"][0]["identity"] = right(data)["processes"][0]["identity"]
    result = check(rebind(data))
    assert result["predecessor_outcome"] == "CONSISTENT"
    assert result["reason_codes"] == ["INPUT_ALIAS"]


def test_callbacks_and_provider_contract_are_identity_only():
    class Stub:
        def __init__(self):
            self.calls = 0

        def callback(self, *args):
            self.calls += 1
            raise AssertionError("callback executed")

    left, right_stub = Stub(), Stub()
    provider = integration.bridge.Provider("fixture_left", "source_left", "bundle_left", left.callback)
    assert provider.callback.__self__ is left
    assert check(callbacks=(provider.callback, right_stub.callback))["outcome"] == "CONSISTENT"
    assert check(callbacks=(left.callback, left.callback))["predecessor_reason_codes"] == ["SOURCE_ALIAS"]
    assert left.calls == right_stub.calls == 0
    assert check(callbacks=[left.callback, right_stub.callback])["outcome"] == "INVALID"


def test_mutation_after_predecessor_is_detected(monkeypatch):
    original = integration.integrate_native_evidence

    def mutate(data, **kwargs):
        report = original(data, **kwargs)
        data["reference"]["window"]["end_ns"] += 1
        return report

    monkeypatch.setattr(integration, "integrate_native_evidence", mutate)
    result = semantic.correlate_native_semantics(request()).to_dict()
    trust(result)
    assert result["reason_codes"] == ["INPUT_CHANGED"]
    assert result["predecessor_outcome"] == "CONSISTENT"


def test_late_mutation_discards_volatile_evidence(monkeypatch):
    data = request()
    right(data)["processes"][0]["reads"][0]["sha256"] = "b" * 64
    rebind(data)
    correlate = semantic._correlate

    def mutate(copied, codes):
        divergences = correlate(copied, codes)
        assert divergences
        data["reference"]["window"]["end_ns"] += 1
        return divergences

    monkeypatch.setattr(semantic, "_correlate", mutate)
    result = semantic.correlate_native_semantics(data).to_dict()
    trust(result)
    assert result["outcome"] == "INVALID"
    assert result["predecessor_reason_codes"] == ["SOURCE_DISAGREEMENT"]
    assert result["semantic"]["reason_codes"] == ["INPUT_CHANGED"]
    assert result["semantic"]["classification"] == "NOT_EVALUATED"
    assert result["semantic"]["volatile_divergences"] == []


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'\xff', b'"\\ud800"', b'"\\u0000"',
    b'NaN', b'1.5', b'[' * 1000 + b']' * 1000, b'{}' + b' ' * integration.MAX_BYTES])
def test_strict_raw_inputs(raw):
    result = semantic.correlate_native_semantics(raw).to_dict()
    trust(result)
    assert result["outcome"] == "INVALID"


@pytest.mark.parametrize("value", [1.5, float("nan"), {1: "bad"}, {"a": object()}, "text", None])
def test_exact_tree_types(value):
    result = semantic.correlate_native_semantics(value).to_dict()
    trust(result)
    assert result["outcome"] == "INVALID"


def test_subclasses_cycles_and_budgets():
    class DictSubclass(dict):
        pass

    class IntSubclass(int):
        pass

    class StrSubclass(str):
        pass

    class ListSubclass(list):
        pass

    for value in (DictSubclass(request()), [IntSubclass(1)], [StrSubclass("x")], ListSubclass(),
                  ["a" * (integration.MAX_STRING + 1)], [None] * integration.MAX_NODES):
        result = semantic.correlate_native_semantics(value).to_dict()
        trust(result)
        assert result["outcome"] == "INVALID"
    data = request()
    data["cycle"] = data
    result = semantic.correlate_native_semantics(data).to_dict()
    trust(result)
    assert result["outcome"] == "INVALID"
    data = request()
    data["reference"]["frame_count"] = True
    assert check(data)["outcome"] == "INVALID"


def test_determinism_serialization_and_immutable_returns():
    data = request()
    one = semantic.correlate_native_semantics(data)
    assert one.serialized == semantic.correlate_native_semantics(data).serialized
    assert one.sha256 == hashlib.sha256(one.serialized.encode()).hexdigest()
    assert one.serialized == integration.canonical_json(one.to_dict())
    raw = integration.canonical_json(data).encode()
    result = check(raw)
    expected = one.to_dict()
    assert result["request_sha256"] == expected["request_sha256"]
    assert result["semantic"] == expected["semantic"]
    assert result["raw_input_sha256"] == hashlib.sha256(raw).hexdigest()
    detached = one.to_dict()
    detached["semantic"]["classification"] = "changed"
    assert one.to_dict()["semantic"]["classification"] == "STABLE_IDENTITY_CORRELATED"
    with pytest.raises(FrozenInstanceError):
        one.serialized = "changed"
    # observed PID and descriptor order are noncontractual; chronological read
    # and process order remain constrained by the predecessor's read ordering.
    for route in data["routes"]:
        for frame in route["capture"]["frames"]:
            frame["observed_pids"].reverse()
            for process in frame["processes"]:
                process["descriptors"].reverse()
    assert check(rebind(data))["semantic"] == expected["semantic"]


def test_early_upstream_incomplete_is_not_a_validation_base():
    data = request()
    data["routes"][0]["capture"] = {"schema": integration.ADAPTER_SCHEMA}
    # The predecessor stops here without validating the second route.
    data["routes"][1]["capture"] = {"schema": "broken"}
    result = check(data)
    assert result["predecessor_reason_codes"] == ["UPSTREAM_CONVERSION_NOT_IMPLEMENTED"]
    assert result["semantic"]["classification"] == "NOT_EVALUATED"


def test_precedence_and_unknown_internal_reason_sealing():
    result = semantic._partitions({"invented", "SOURCE_DISAGREEMENT"})
    assert result == {"outcome": "INVALID", "reason_codes": ["REASON_CODE_INVALID", "SOURCE_DISAGREEMENT"],
                      "invalid_reason_codes": ["REASON_CODE_INVALID"], "incomplete_reason_codes": ["SOURCE_DISAGREEMENT"]}


def test_source_is_inert_and_uses_only_safe_dependencies():
    tree = ast.parse(SOURCE.read_text())
    imports = []
    forbidden = {"open", "eval", "exec", "__import__", "monotonic_ns", "time_ns", "perf_counter",
                 "readlink", "socket", "Popen", "acquire_provenance_bridge", "preview_injected_bridge"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module)
            if node.module == "scripts.benchmarks":
                assert [alias.name for alias in node.names] == ["rb_post3d_08p2e2_r2f_f2b4_native_evidence_integration"]
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            assert name not in forbidden
    assert sorted(imports) == ["dataclasses", "hashlib", "json", "re", "scripts.benchmarks"]
    for node in tree.body:
        assert isinstance(node, (ast.Expr, ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef, ast.ClassDef))
        if isinstance(node, ast.Assign):
            assert not any(isinstance(child, ast.Call) for child in ast.walk(node.value))
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant) and type(node.value.value) is str


@pytest.mark.parametrize("name,expected", [
    ("native_evidence_integration", "8a422078f7c0a2cfc7e168b19471fa9fc056aff23acef7de38020d5bb4e6ce71"),
    ("native_provenance_bridge", "e9c80ac9cf2d735127548919055d790eabf6993f81e81aa041cfe314f2171c42")])
def test_immutable_dependencies(name, expected):
    path = ROOT / f"scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_{name}.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def upstream(kind):
    """Literal original error envelopes, without invoking any upstream API.

    Adapter: sample(None); probe: invalid request before reads; bridge: denied
    mode before provider/clock validation. These are original report schemas,
    not the B3-B2 caller-asserted verification summary schema.
    """
    schema = integration.VERIFIERS[kind][0]
    if kind == "ADAPTER_D2B2":
        result = {"schema": schema, "source_kind": "TEST_INJECTED", "origin_attestation": "UNVERIFIED",
            "qualification": "NONQUALIFYING", "independent_verification": "REQUIRED_NOT_PERFORMED",
            "production_memory_qualification": "INCONCLUSIVE", "production_chronological_peak": "NOT_OBSERVED",
            "production_workload_measured": False, "atomic_snapshot": False,
            "bound_claim": "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK", "holder_release": "NOT_ESTABLISHED",
            "owner_termination": "NOT_ESTABLISHED", "simultaneous_holder_occupancy": "NOT_ESTABLISHED",
            "worker_absence_proven": False, "unregistered_worker_coverage": "NOT_ESTABLISHED",
            "roster_provenance": "CALLER_ASSERTED_ONLY", "worker_coverage": "NOT_ESTABLISHED",
            "environment_provenance": "CALLER_ASSERTED_ONLY", "procfs_mount_verified": False,
            "starttime_alignment": "NOT_CALIBRATED", "clock_kind": "INJECTED_MONOTONIC_NS", "cgroup": "DISABLED",
            "run_id": None, "input_sha256": None, "config": None, "roster": None, "frames_requested": None,
            "frames": [], "reasons": [{"code": "SCHEMA_INVALID", "location": "request"}], "outcome": "INVALID",
            "read_attempts": 0, "open_attempts": 0, "total_bytes": 0,
            "first_read_start_ns": None, "last_read_end_ns": None, "read_skew_ns": None,
            "invalid_reason_codes": ["SCHEMA_INVALID"], "incomplete_reason_codes": []}
        return seal_adapter(result)
    if kind == "PROBE_B3A":
        return {"schema": schema, "source_kind": "INJECTED_LOCAL_PROBE", "qualification": "NONQUALIFYING",
            "outcome": "INVALID", "trust_level": "CALLER_ASSERTED_ONLY", "clock_domain": "INJECTED_MONOTONIC_NS",
            "context_pid": None, "target_pids": [], "context_identity": None, "target_identities": [],
            "input_sha256": integration.digest(None), "reference_sha256": None,
            "reason_codes": ["SCHEMA_INVALID"], "invalid_reason_codes": ["SCHEMA_INVALID"],
            "incomplete_reason_codes": [], "reads": [], "native_adapter": "NOT_IMPLEMENTED",
            "independent_trust_root_gate": "NOT_IMPLEMENTED", "independent_verification": "REQUIRED_NOT_PERFORMED",
            "procfs_mount_authenticated": False, "namespace_authenticated": False,
            "mount_namespace_binding": "UNVERIFIED", "frame_coverage": "UNBOUNDED",
            "production_memory_qualification": "INCONCLUSIVE", "production_chronological_peak": "NOT_OBSERVED",
            "production_workload_measured": False, "holder_release": "NOT_ESTABLISHED",
            "rss_reclamation": "NOT_ESTABLISHED", "worker_discovery": "NOT_ESTABLISHED",
            "worker_absence_proven": False, "atomic_snapshot": False}
    return {"schema": schema, "source_state": "INJECTED_TEST_ONLY", "qualification": "NONQUALIFYING",
        "outcome": "INVALID", "reason_codes": ["NATIVE_MODE_DENIED"], "invalid_reason_codes": ["NATIVE_MODE_DENIED"],
        "incomplete_reason_codes": [], "clock_domain": "INJECTED_MONOTONIC_NS", "request_sha256": None,
        "registered_roster": [], "providers": [], "observations": [], "source_acquisition": "NOT_ACQUIRED",
        "independent_corroboration": "NOT_ESTABLISHED", "cross_source_structural_agreement": "NOT_ESTABLISHED",
        "native_origin_authentication": "NOT_IMPLEMENTED", "independent_host_attestation": "NOT_IMPLEMENTED",
        "worker_roster_completeness": "NOT_ESTABLISHED", "whole_process_tree_coverage": "NOT_ESTABLISHED",
        "rss_chronological_qualification": "NOT_ESTABLISHED", "rss_sampling": "SEQUENTIAL_NONATOMIC",
        "production_memory_qualification": "INCONCLUSIVE", "production_chronological_peak": "NOT_OBSERVED",
        "production_workload_measured": False, "holder_release": "NOT_ESTABLISHED",
        "rss_reclamation": "NOT_ESTABLISHED", "atomic_snapshot": False}


def seal_adapter(result):
    result.pop("integrity", None)
    result["integrity"] = {"algorithm": "sha256", "scope": "canonical result excluding integrity",
                           "sha256": integration.digest(result)}
    return result


def consistent_adapter():
    """Literal adapter success shape, with artificial bytes; no adapter calls."""
    success = "CAPTURE_CONSISTENT_NONQUALIFYING"
    identities = [dict(p, boot_id=BOOT, pid_namespace_id="pidns:77",
                       role="parent" if p["pid"] == 100 else "worker") for p in roster()]
    config = {"clock_ticks_per_second": 100, "boot_id": BOOT, "pid_namespace_id": "pidns:77",
        "max_read_skew_ns": 10000, "max_bytes": 4096, "max_total_bytes": 1048576,
        "max_read_attempts": 1000, "max_read_iterations": 128, "smaps_rollup_policy": "NOT_SAMPLED"}
    registered = {"parent": identities[0], "workers": identities[1:], "complete": True}
    supplied_request = {"schema": integration.ADAPTER_SCHEMA.removesuffix(".result"),
        "source_kind": "TEST_INJECTED", "capture_mode": "INJECTED", "run_id": "fixture-run",
        "config": config, "roster": registered, "frame_rosters": [[100, 200], [100, 200]], "cgroup": None}
    report = upstream("ADAPTER_D2B2")
    report.update(outcome=success, reasons=[], invalid_reason_codes=[], worker_coverage="REGISTERED_ROSTER_OBSERVED",
        run_id="fixture-run", input_sha256=integration.digest(supplied_request), config=copy.deepcopy(config),
        roster=copy.deepcopy(registered), frames_requested=2, read_attempts=24, open_attempts=17)
    for index in range(2):
        processes = []
        for number, identity in enumerate(identities):
            pid, ppid, ticks = (identity[k] for k in ("pid", "ppid", "starttime_ticks"))
            parsed = {"pid": pid, "ppid": ppid, "starttime_ticks": ticks, "state": "R"}
            reads = []
            for stage, label in enumerate(("stat_before", "status", "stat_after")):
                raw = ((f"{pid} (fixture) R {ppid} " + "0 " * 17 + f"{ticks}\n").encode()
                       if label != "status" else
                       f"Name:\tfixture\nState:\tR (running)\nTgid:\t{pid}\nPid:\t{pid}\nPPid:\t{ppid}\nVmRSS:\t5 kB\nVmHWM:\t20 kB\n".encode())
                start = 2 * (index * 6 + stage * 2 + number)
                reads.append({"label": label, "kind": "status" if label == "status" else "stat", "pid": pid,
                    "status": "OK", "start_ns": start, "end_ns": start + 1, "byte_length": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(), "byte_provenance_complete": True,
                    "read_calls": 2, "requested_limits": [4097, 4097 - len(raw)],
                    "reason_codes": [], "exception_class": None})
            processes.append({"identity": copy.deepcopy(identity), "status": success, "reason_codes": [],
                "reads": reads, "stat_before_identity": copy.deepcopy(parsed), "stat_after_identity": copy.deepcopy(parsed),
                "open_exception_class": None, "vmrss_bytes": 5120, "vmhwm_bytes": 20480, "smaps_rollup": None})
        report["frames"].append({"index": index, "status": success, "reason_codes": [], "processes": processes,
            "observed_pids": [100, 200], "roster_complete": True, "first_read_start_ns": index * 12,
            "last_read_end_ns": index * 12 + 11, "read_skew_ns": 11, "read_window_complete": True})
    report.update(first_read_start_ns=0, last_read_end_ns=23, read_skew_ns=23,
                  total_bytes=sum(r["byte_length"] for f in report["frames"] for p in f["processes"] for r in p["reads"]))
    return seal_adapter(report)


def consistent_bridge(method):
    """Literal two-provider/two-sweep report; never invoke the bridge API."""
    report = upstream("BRIDGE_H0")
    report.update(outcome="CONSISTENT", reason_codes=[], invalid_reason_codes=[], request_sha256="a" * 64,
        registered_roster=roster(), source_acquisition="CALLER_CONFIGURED_ONLY", cross_source_structural_agreement="AGREES",
        providers=[{"provider_id": name, "source_id": name + "_source", "fixture_id": name + "_fixture",
                    "declared_origin": "INJECTED_TEST_ONLY"} for name in ("left", "right")])
    paths = ["boot_id", "proc_mount"] + [f"pids/{p['pid']}/{leaf}" for p in roster()
                                                  for leaf in ("identity", "ns_link", "ns_target")]
    for sweep in (0, 1):
        for provider in (0, 1):
            for number, path in enumerate(paths):
                identity = next((p for p in roster() if path.startswith(f"pids/{p['pid']}/")), None)
                target, link = path.endswith("/ns_target"), path.endswith("/ns_link")
                descriptor = {"path_id": path,
                    "role": "NSFS_TARGET" if target else "PROCFS_LINK_LOCATION" if link else "PROCFS_OBJECT",
                    "st_dev": 4 if target else 5, "st_ino": 77 if target else sorted(paths).index(path) + 100,
                    "mount_id": 10 if target else 9, "filesystem": "nsfs" if target else "proc", "symlink": link,
                    "binding": "INJECTED_DESCRIPTOR_RELATIVE_NO_FOLLOW", "identity": copy.deepcopy(identity)}
                if path == "boot_id":
                    payload = {"boot_id": BOOT}
                elif path == "proc_mount":
                    payload = {"mount_id": 9, "st_dev": 5, "filesystem": "proc"}
                elif path.endswith("/identity"):
                    payload = {"identity": copy.deepcopy(identity), "cpu_ticks": 50, "vmhwm_kib": 100, "rss_kib": 80}
                else:
                    payload = {"namespace_inode": 77} if link else {"st_dev": 4, "st_ino": 77}
                raw = json.dumps(payload, sort_keys=True).encode() if method == "INJECTED_JSON_BYTES" else None
                sha = hashlib.sha256(raw).hexdigest() if raw is not None else integration.digest(payload)
                start = 1000 + 2 * len(report["observations"])
                report["observations"].append({"provider_index": provider, "sweep": sweep, "path_id": path,
                    "clock_domain": "INJECTED_MONOTONIC_NS", "start_ns": start, "end_ns": start + 1,
                    "descriptor_before": descriptor, "descriptor_after": copy.deepcopy(descriptor), "payload": payload,
                    "sha256": sha, "payload_sha256": integration.digest(payload), "method": method,
                    "declared_sha256": sha, "raw_byte_count": len(raw) if raw is not None else None,
                    "declared_origin": "INJECTED_TEST_ONLY", "sequence": sweep * len(paths) + number + 1,
                    "provider_status": "OK", "provider_reason": None, "status": "OK", "reason_codes": [],
                    "operation_errors": []})
    return report


KINDS = ("ADAPTER_D2B2", "PROBE_B3A", "BRIDGE_H0")


@pytest.mark.parametrize("kind,method", [("ADAPTER_D2B2", None),
    ("BRIDGE_H0", "INJECTED_STRUCTURED"), ("BRIDGE_H0", "INJECTED_JSON_BYTES")])
@pytest.mark.parametrize("pretty", [False, True])
def test_literal_successful_adapter_and_bridge_are_unsupported(kind, method, pretty):
    original = consistent_adapter() if kind == "ADAPTER_D2B2" else consistent_bridge(method)
    before = copy.deepcopy(original)
    raw = (json.dumps(original, indent=1) if pretty else integration.canonical_json(original)).encode()
    imported = semantic.import_upstream_report(kind, raw)
    result = imported.to_dict()
    trust(result)
    assert result["outcome"] == "INCOMPLETE"
    assert result["reason_codes"] == ["UNSUPPORTED_LOSSLESS_CONVERSION"]
    assert result["conversion"] == "UNSUPPORTED_LOSSLESS_CONVERSION"
    assert result["converted_capture"] is None
    assert result["original"] == {"original_schema": original["schema"],
        "data_origin": original.get("source_kind", original.get("source_state")),
        "original_outcome": original["outcome"], "original_reason_codes": [],
        "original_invalid_reason_codes": [], "original_incomplete_reason_codes": []}
    assert result["raw_input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["canonical_report_sha256"] == integration.digest(original)
    assert result["original_verification"] == "CALLER_SUPPLIED_NOT_REVERIFIED"
    assert result["validation_scope"] == "ORIGINAL_ENVELOPE_ONLY"
    assert result["custody_limitation"] == "DIGEST_ONLY_EXACT_BYTES_REMAIN_WITH_CALLER_NOT_RETAINED_OR_AUTHENTICATED"
    assert semantic.import_upstream_report(kind, raw).serialized == imported.serialized
    assert original == before
    if kind == "BRIDGE_H0":
        assert len(original["observations"]) == 32
        assert {r["method"] for r in original["observations"]} == {method}


@pytest.mark.parametrize("run_id", ["fixture.run:1", "a" * 96, "CONSISTENT"])
def test_adapter_original_run_label_grammar_is_preserved(run_id):
    report = consistent_adapter()
    report["run_id"] = run_id
    seal_adapter(report)
    result = semantic.import_upstream_report("ADAPTER_D2B2", integration.canonical_json(report).encode()).to_dict()
    trust(result)
    assert result["reason_codes"] == ["UNSUPPORTED_LOSSLESS_CONVERSION"]
    assert result["conversion"] == "UNSUPPORTED_LOSSLESS_CONVERSION"


@pytest.mark.parametrize("method", ["INJECTED_STRUCTURED", "INJECTED_JSON_BYTES"])
@pytest.mark.parametrize("case", ["missing_path", "substituted_mount", "duplicate_path"])
def test_bridge_success_requires_exact_original_path_coverage(method, case):
    report = consistent_bridge(method)
    if case == "missing_path":
        report["observations"].pop()
    elif case == "substituted_mount":
        for read in report["observations"]:
            if read["path_id"] == "proc_mount":
                read["path_id"] = "mount"
                read["descriptor_before"]["path_id"] = "mount"
                read["descriptor_after"]["path_id"] = "mount"
    else:
        report["observations"][-1] = copy.deepcopy(report["observations"][-2])
    result = semantic.import_upstream_report("BRIDGE_H0", integration.canonical_json(report).encode()).to_dict()
    trust(result)
    assert result["outcome"] == "INVALID"
    assert result["reason_codes"] == ["OUTCOME_CONFLICT"]
    assert result["conversion"] == "REJECTED"
    assert result["original"] is None
    assert result["converted_capture"] is None


@pytest.mark.parametrize("case,code", [
    ("unestablished_success", "OUTCOME_CONFLICT"), ("unestablished_run", "OUTCOME_CONFLICT"),
    ("empty_frames", "OUTCOME_CONFLICT"), ("partial_frames", "OUTCOME_CONFLICT"),
    ("null_requested", "INTEGER_INVALID"), ("zero_requested", "INTEGER_INVALID"),
    ("bad_run", "LABEL_INVALID"), ("missing_input_hash", "DIGEST_INVALID"),
    ("bad_config", "SCHEMA_INVALID"), ("bad_roster", "SCHEMA_INVALID"),
    ("uncertain_success", "OUTCOME_CONFLICT"), ("reason_with_observed", "OUTCOME_CONFLICT"),
    ("null_first", "OUTCOME_CONFLICT"), ("wrong_last", "OUTCOME_CONFLICT"),
    ("wrong_skew", "OUTCOME_CONFLICT"), ("wrong_frame_skew", "OUTCOME_CONFLICT"),
    ("changed_read_endpoint", "OUTCOME_CONFLICT"), ("empty_frame_reads", "OUTCOME_CONFLICT"),
    ("false_window_complete", "OUTCOME_CONFLICT"), ("frame_reason_without_report_reason", "OUTCOME_CONFLICT")])
def test_fabricated_successful_adapter_summaries_rejected(case, code):
    report = upstream("ADAPTER_D2B2") if case.startswith("unestablished") else consistent_adapter()
    if case == "unestablished_success":
        report.update(outcome="CAPTURE_CONSISTENT_NONQUALIFYING", reasons=[], invalid_reason_codes=[])
    elif case == "unestablished_run":
        report["run_id"] = "fixture-run"
    elif case == "empty_frames":
        report["frames"] = []
    elif case == "partial_frames":
        report["frames"].pop()
    elif case in ("null_requested", "zero_requested"):
        report["frames_requested"] = None if case == "null_requested" else 0
    elif case == "bad_run":
        report["run_id"] = None
    elif case == "missing_input_hash":
        report["input_sha256"] = None
    elif case in ("bad_config", "bad_roster"):
        report[case.removeprefix("bad_")] = []
    elif case == "uncertain_success":
        report["worker_coverage"] = "UNCERTAIN"
    elif case == "reason_with_observed":
        report.update(outcome="INCOMPLETE", reasons=[{"code": "READ_FAILED", "location": "frames.0"}],
                      incomplete_reason_codes=["READ_FAILED"])
    elif case == "null_first":
        report["first_read_start_ns"] = None
    elif case in ("wrong_last", "wrong_skew"):
        report["last_read_end_ns" if case == "wrong_last" else "read_skew_ns"] += 1
    elif case == "wrong_frame_skew":
        report["frames"][0]["read_skew_ns"] += 1
    elif case == "changed_read_endpoint":
        report["frames"][0]["processes"][0]["reads"][0]["start_ns"] = 1
    elif case == "empty_frame_reads":
        report["frames"][0]["processes"] = []
    elif case == "false_window_complete":
        report["frames"][0]["read_window_complete"] = False
    else:
        report["frames"][0].update(status="INCOMPLETE", reason_codes=["READ_FAILED"])
    seal_adapter(report)  # A self-computable integrity hash cannot excuse a conflict.
    result = semantic.import_upstream_report("ADAPTER_D2B2", integration.canonical_json(report).encode()).to_dict()
    trust(result)
    assert result["outcome"] == "INVALID"
    assert result["reason_codes"] == [code]
    assert result["conversion"] == "REJECTED"
    assert result["original"] is None
    assert result["converted_capture"] is None


def test_incomplete_original_keeps_explicit_upstream_marker():
    report = consistent_adapter()
    report.update(outcome="INCOMPLETE", worker_coverage="UNCERTAIN",
        reasons=[{"code": "READ_FAILED", "location": "root.close"}],
        incomplete_reason_codes=["READ_FAILED"])
    frame = report["frames"][-1]
    frame.update(status="INCOMPLETE", reason_codes=["READ_FAILED"])
    for process in frame["processes"]:
        process.update(status="INCOMPLETE", vmrss_bytes=None, vmhwm_bytes=None)
    seal_adapter(report)
    result = semantic.import_upstream_report("ADAPTER_D2B2", integration.canonical_json(report).encode()).to_dict()
    trust(result)
    assert result["outcome"] == "INCOMPLETE"
    assert result["reason_codes"] == ["UNSUPPORTED_LOSSLESS_CONVERSION", "UPSTREAM_INCOMPLETE"]
    assert result["conversion"] == "UNSUPPORTED_LOSSLESS_CONVERSION"
    assert result["original"]["original_outcome"] == "INCOMPLETE"
    assert result["original"]["original_reason_codes"] == ["READ_FAILED"]
    assert result["original"]["original_incomplete_reason_codes"] == ["READ_FAILED"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("pretty", [False, True])
def test_original_upstream_envelopes_are_explicitly_unsupported(kind, pretty):
    original = upstream(kind)
    raw = (json.dumps(original, indent=1) if pretty else integration.canonical_json(original)).encode()
    imported = semantic.import_upstream_report(kind, raw)
    result = imported.to_dict()
    trust(result)
    assert result["conversion"] == "UNSUPPORTED_LOSSLESS_CONVERSION"
    assert result["converted_capture"] is None
    assert result["outcome"] == "INVALID"  # Preserve upstream invalidity too.
    assert result["reason_codes"] == ["UNSUPPORTED_LOSSLESS_CONVERSION", "UPSTREAM_INVALID"]
    assert result["original"]["original_schema"] == original["schema"]
    assert result["original"]["original_outcome"] == original["outcome"]
    assert result["original"]["original_reason_codes"] == original["invalid_reason_codes"]
    assert result["original"]["data_origin"] == original.get("source_kind", original.get("source_state"))
    assert result["raw_input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["canonical_report_sha256"] == integration.digest(original)
    assert result["original_verification"] == "CALLER_SUPPLIED_NOT_REVERIFIED"
    assert result["validation_scope"] == "ORIGINAL_ENVELOPE_ONLY"
    assert result["custody_limitation"] == "DIGEST_ONLY_EXACT_BYTES_REMAIN_WITH_CALLER_NOT_RETAINED_OR_AUTHENTICATED"
    assert result["missing_semantic_fields"]
    assert semantic.import_upstream_report(kind, raw).serialized == imported.serialized
    if pretty:
        assert result["raw_input_sha256"] != result["canonical_report_sha256"]


def consistent_probe():
    """Supplied original-format successful probe envelope, not re-verification."""
    report = upstream("PROBE_B3A")
    report.update(outcome="CONSISTENT", trust_level="INJECTED_LOCAL_PROBE", context_pid=100,
        context_identity=roster()[0], target_pids=[200], target_identities=roster()[1:],
        input_sha256="a" * 64, reason_codes=[], invalid_reason_codes=[],
        frame_coverage="CALLER_ASSERTED_WINDOWS_ONLY")
    paths = ["boot_id", "mount", "pids/100/identity", "pids/100/namespace", "pids/200/identity", "pids/200/namespace"]
    for index, path in enumerate(paths * 2):
        report["reads"].append({"source": path, "start_ns": index * 2, "end_ns": index * 2 + 1,
            "failure_codes": [], "provenance": "INJECTED_LOCAL_PROBE", "sha256": "b" * 64, "descriptor_stable": True})
    return report


def test_successful_original_outcome_is_preserved_without_conversion():
    original = consistent_probe()
    result = semantic.import_upstream_report("PROBE_B3A", integration.canonical_json(original).encode()).to_dict()
    trust(result)
    assert result["outcome"] == "INCOMPLETE"
    assert result["reason_codes"] == ["UNSUPPORTED_LOSSLESS_CONVERSION"]
    assert result["original"]["original_outcome"] == "CONSISTENT"
    assert result["original"]["original_reason_codes"] == []
    assert result["conversion"] == "UNSUPPORTED_LOSSLESS_CONVERSION"
    assert result["converted_capture"] is None


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", ["schema", "extra", "missing", "outcome", "partitions", "reason", "trust", "hash"])
def test_upstream_substitution_conflicts_and_tampering(kind, case):
    report = upstream(kind)
    if case == "schema":
        report["schema"] = integration.VERIFICATION_SCHEMA
    elif case == "extra":
        report["fabricated_summary"] = True
    elif case == "missing":
        report.pop("qualification")
    elif case == "outcome":
        report["outcome"] = "CONSISTENT"
    elif case == "partitions":
        report["invalid_reason_codes"] = []
    elif case == "reason":
        report["invalid_reason_codes"] = ["INVENTED"]
    elif case == "trust":
        report["atomic_snapshot"] = True
    else:
        report["input_sha256" if kind != "BRIDGE_H0" else "request_sha256"] = "broken"
    if kind == "ADAPTER_D2B2":
        seal_adapter(report)
    result = semantic.import_upstream_report(kind, integration.canonical_json(report).encode()).to_dict()
    trust(result)
    assert result["outcome"] == "INVALID"
    assert result["conversion"] == "REJECTED"
    assert result["original"] is None
    assert result["converted_capture"] is None


@pytest.mark.parametrize("schema", [integration.ASSESSMENT_SCHEMA, integration.CAPTURE_SCHEMA,
    integration.SCHEMA + ".report", "unknown", integration.PROBE_SCHEMA, integration.bridge.SCHEMA + ".report"])
def test_upstream_exact_kind_schema_binding(schema):
    report = upstream("ADAPTER_D2B2")
    report["schema"] = schema
    result = semantic.import_upstream_report("ADAPTER_D2B2", integration.canonical_json(report).encode()).to_dict()
    trust(result)
    assert result["conversion"] == "REJECTED"


def test_adapter_integrity_is_exact_and_no_paths_leak():
    report = upstream("ADAPTER_D2B2")
    report["reasons"][0]["location"] = "/host/private/example"
    result = semantic.import_upstream_report("ADAPTER_D2B2", integration.canonical_json(report).encode())
    trust(result.to_dict())
    assert result.to_dict()["reason_codes"] == ["DIGEST_INVALID"]
    assert "/host/private" not in result.serialized
    seal_adapter(report)
    result = semantic.import_upstream_report("ADAPTER_D2B2", integration.canonical_json(report).encode())
    trust(result.to_dict())
    assert result.to_dict()["conversion"] == "UNSUPPORTED_LOSSLESS_CONVERSION"
    assert "/host/private" not in result.serialized


@pytest.mark.parametrize("case", ["empty", "bad_hash", "read_failure", "unknown_source", "bad_clock", "wrong_roster"])
def test_fabricated_successful_probe_summaries_rejected(case):
    report = consistent_probe()
    if case == "empty":
        report["reads"] = []
    elif case == "bad_hash":
        report["reads"][0]["sha256"] = "wrong"
    elif case == "read_failure":
        report["reads"][0]["failure_codes"] = ["READ_FAILED"]
    elif case == "unknown_source":
        report["reads"][0]["source"] = "/proc/100/stat"
    elif case == "bad_clock":
        report["reads"][0]["end_ns"] = -1
    else:
        report["target_pids"] = [300]
    result = semantic.import_upstream_report("PROBE_B3A", integration.canonical_json(report).encode()).to_dict()
    trust(result)
    assert result["conversion"] == "REJECTED"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("raw", [b'{"schema":1,"schema":2}', b'\xff', b'"\\ud800"', b'"\\u0000"',
    b'NaN', b'{}' + b' ' * integration.MAX_BYTES, {}, "{}", None])
def test_upstream_strict_byte_policy(kind, raw):
    result = semantic.import_upstream_report(kind, raw).to_dict()
    trust(result)
    assert result["outcome"] == "INVALID"
    assert result["conversion"] == "REJECTED"
    assert result["converted_capture"] is None


@pytest.mark.parametrize("kind", ["unknown", [], None, 1])
def test_upstream_kind_is_exact(kind):
    result = semantic.import_upstream_report(kind, b'{}').to_dict()
    trust(result)
    assert result["outcome"] == "INVALID"


def test_namespace_read_stability_and_digest_sizes_across_frames():
    data = request()
    for route in data["routes"]:
        route["capture"]["frames"][1]["processes"][0]["reads"][1]["sha256"] = "b" * 64
    result = check(rebind(data))
    assert result["predecessor_outcome"] == "CONSISTENT"
    assert result["semantic"]["reason_codes"] == ["STABLE_READ_DISAGREEMENT"]
    data = request()
    for route in data["routes"]:
        route["capture"]["frames"][1]["processes"][0]["reads"][0]["byte_count"] += 1
    assert check(rebind(data))["semantic"]["reason_codes"] == ["READ_SIZE_CONTRADICTION"]
