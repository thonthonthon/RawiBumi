"""Artificial byte fixtures only; verification is run by the orchestrator.

No source-file reads, native APIs, clocks, subprocesses or external test imports.
The orchestrator owns source-hash guards and the exact 14-suite command.
"""

import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
from types import CodeType

import pytest

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_native_evidence_assembly as assembly

integration = assembly.integration
semantic = assembly.semantic
BOOT = "12345678-1234-5678-90ab-123456789abc"
RAW = b"opaque artificial read\xff\x00"


@pytest.fixture(autouse=True)
def inert_seams(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("native acquisition or preview reached")

    monkeypatch.setattr(integration, "preview_injected_bridge", forbidden)
    monkeypatch.setattr(integration.bridge, "acquire_provenance_bridge", forbidden)
    yield
    assert calls == []


def roster(count=2):
    return [{"pid": 100 + n * 100, "ppid": 1 if n == 0 else 100, "starttime_ticks": 10 + n}
            for n in range(count)]


def environment(native=False):
    return {"boot_id": BOOT, "namespace": {"kind": "INODE", "value": 77},
            "procfs": {"filesystem": "proc", "mount_id": 9, "st_dev": 5},
            "nsfs": {"filesystem": "nsfs", "mount_id": 10, "st_dev": 4},
            "clock_kind": "LOCAL_MONOTONIC_NS" if native else "INJECTED_MONOTONIC_NS"}


def fixture(native=False, frames=2, pids=2, payload=RAW):
    """Independent toy supplied request; no acquisition helpers are imported."""
    state = "NATIVE_PROCFS_UNVERIFIED" if native else "INJECTED_TEST_ONLY"
    routes, raw_reads = [], []
    for route_index, label in enumerate(("left", "right")):
        cap = {"schema": integration.CAPTURE_SCHEMA, "source_state": state,
               "source_kind": integration.ORIGINS[state][0], "origin_attestation": integration.ORIGINS[state][1],
               **environment(native), "roster": roster(pids), "frames": []}
        for frame_index in range(frames):
            start = 100 + frame_index * 1000
            frame = {"index": frame_index, "start_ns": start, "end_ns": start + 500,
                     "observed_pids": [p["pid"] for p in roster(pids)], "processes": [],
                     "read_complete": True, "reason_codes": []}
            tick = start
            for number, identity in enumerate(roster(pids)):
                process = {"identity": identity, "descriptors": [], "reads": []}
                for k, leaf in enumerate(("identity", "ns_link", "ns_target")):
                    path = f"pids/{identity['pid']}/{leaf}"
                    target = leaf == "ns_target"
                    process["descriptors"].append({"path_id": path,
                        "role": "NSFS_TARGET" if target else "PROCFS_LINK_LOCATION" if leaf == "ns_link" else "PROCFS_OBJECT",
                        **cap["nsfs" if target else "procfs"], "st_ino": 77 if target else 1000 + number * 10 + k})
                    process["reads"].append({"path_id": path, "start_ns": tick, "end_ns": tick + 1,
                        "status": "OK", "sha256": hashlib.sha256(payload).hexdigest(), "byte_count": len(payload), "reason_codes": []})
                    raw_reads.append({"route_index": route_index, "frame_index": frame_index,
                                      "pid": identity["pid"], "path_id": path, "payload": payload})
                    tick += 2
                frame["processes"].append(process)
            cap["frames"].append(frame)
        schema, _, _, success = integration.VERIFIERS["ADAPTER_D2B2"]
        routes.append({"provenance": {**{key: label + "_" + key for key in
            ("route_id", "provider_id", "callback_id", "method_id", "collection_domain")}, "data_origin": state},
            "capture": cap, "verification": {"schema": integration.VERIFICATION_SCHEMA, "validator": "ADAPTER_D2B2",
                "upstream_schema": schema, "outcome": success, "reason_codes": [], "invalid_reason_codes": [],
                "incomplete_reason_codes": [], "report_sha256": "a" * 64, "capture_sha256": integration.digest(cap)}})
    return {"schema": integration.SCHEMA, "mode": "SUPPLIED_ONLY", "native_opt_in": False,
            "reference": {**environment(native), "roster": roster(pids),
                          "window": {"start_ns": 100, "end_ns": 100 + (frames - 1) * 1000 + 500}, "frame_count": frames},
            "routes": routes, "limits": {"max_read_ns": 500, "max_gap_ns": 500, "max_route_skew_ns": 5}}, raw_reads


def rebind(data):
    """Only fixture callers can update their own verification assertions."""
    for route in data["routes"]:
        route["verification"]["capture_sha256"] = integration.digest(route["capture"])
    return data


def read_at(data, route=1, frame=0, process=0, leaf=0):
    return data["routes"][route]["capture"]["frames"][frame]["processes"][process]["reads"][leaf]


def raw_key(item):
    return tuple(item[k] for k in ("route_index", "frame_index", "pid", "path_id"))


def retain_referenced_reads(data, raw):
    keys = {(ri, frame["index"], process["identity"]["pid"], read["path_id"])
            for ri, route in enumerate(data["routes"]) for frame in route["capture"]["frames"]
            for process in frame["processes"] for read in process["reads"] if read["status"] == "OK"}
    return [item for item in raw if raw_key(item) in keys]


def assert_trust(result):
    for key, value in semantic._trust().items():
        assert type(result[key]) is type(value)
        assert result[key] == value
    assert result["source_authenticity"] == "NOT_ESTABLISHED"


def check(data, raw, upstream=None, evaluated=True):
    before = copy.deepcopy((data, raw, upstream))
    report = assembly.assemble_supplied_evidence(data, raw, upstream)
    result = report.to_dict()
    assert (data, raw, upstream) == before
    assert_trust(result)
    assert report.sha256 == hashlib.sha256(report.serialized.encode()).hexdigest()
    assert report.serialized == integration.canonical_json(result)
    for layer in (result, result["assembly"]):
        bad, gaps = layer["invalid_reason_codes"], layer["incomplete_reason_codes"]
        assert layer["reason_codes"] == sorted(set(bad + gaps))
        assert not set(bad) & set(gaps)
        assert layer["classification"] == ("INVALID" if bad else "INCOMPLETE" if gaps else "ASSEMBLED_NONQUALIFYING")
    if evaluated:
        request = report.to_request()
        assert request is not None
        predecessor = integration.integrate_native_evidence(copy.deepcopy(request), callbacks=())
        correlated = semantic.correlate_native_semantics(copy.deepcopy(request), callbacks=())
        assert result["integration_report"] == predecessor.to_dict()
        assert result["integration_report_sha256"] == predecessor.sha256
        assert result["semantic_report"] == correlated.to_dict()
        assert result["semantic_report_sha256"] == correlated.sha256
        assert result["semantic_report"]["predecessor_report_embedded"] == predecessor.to_dict()
        assert set(predecessor.to_dict()["reason_codes"]) <= set(result["reason_codes"])
        assert set(correlated.to_dict()["reason_codes"]) <= set(result["reason_codes"])
    else:
        assert report.to_request() is None
        assert result["integration_report"] is result["semantic_report"] is None
        assert result["integration_evaluation"] == result["semantic_evaluation"] == "NOT_EVALUATED"
    return report, result


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("frames", [2, 3, 8, 32])
@pytest.mark.parametrize("placeholders", [False, True])
def test_full_assembly(native, frames, placeholders):
    data, raw = fixture(native, frames)
    if placeholders:
        for route in data["routes"]:
            for frame in route["capture"]["frames"]:
                for process in frame["processes"]:
                    for read in process["reads"]:
                        read.update(sha256=None, byte_count=None)
    report, result = check(data, raw)
    assert result["classification"] == "ASSEMBLED_NONQUALIFYING"
    assert result["integration_report"]["outcome"] == result["semantic_report"]["outcome"] == "CONSISTENT"
    assert result["schema"] == assembly.SCHEMA + ".report"
    assert result["request_sha256"] == integration.digest(report.to_request())
    for item, summary, key in zip(sorted(raw, key=raw_key), result["reads"], report.custody.read_keys):
        assert key == raw_key(item)
        assert report.custody.read_bytes(*key) == item["payload"]
        assert summary["sha256"] == hashlib.sha256(item["payload"]).hexdigest()
        assert summary["byte_count"] == len(item["payload"])
    for route in result["routes"]:
        assert route["source_state"] == ("NATIVE_PROCFS_UNVERIFIED" if native else "INJECTED_TEST_ONLY")
    assert all(r["custody"] == "NOT_SUPPLIED" and r["verification_provenance"] == "CALLER_ASSERTED"
               for r in result["upstream_reports"])
    assert "opaque artificial" not in report.serialized
    assert "left_provider_id" not in report.serialized
    assert "opaque artificial" not in repr(report) + repr(report.custody) + repr(report.custody.reads)


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("leaf", [0, 1, 2])
def test_route_bytes_remain_distinct(native, leaf):
    data, raw = fixture(native)
    record = next(item for item in raw if raw_key(item) == (1, 0, 100, f"pids/100/{('identity', 'ns_link', 'ns_target')[leaf]}"))
    record["payload"] += b"x"
    read_at(data, leaf=leaf).update(sha256=hashlib.sha256(record["payload"]).hexdigest(), byte_count=len(record["payload"]))
    report, result = check(rebind(data), raw)
    assert result["classification"] == "INCOMPLETE"
    assert result["integration_report"]["reason_codes"] == ["SOURCE_DISAGREEMENT"]
    sem = result["semantic_report"]["semantic"]
    assert sem["classification"] == ("STABLE_IDENTITY_CORRELATED" if leaf == 0 else "NOT_CORRELATED")
    if leaf == 0:
        difference = sem["volatile_divergences"][0]
        assert difference["left_sha256"] != difference["right_sha256"]
        assert difference["left_byte_count"] + 1 == difference["right_byte_count"]
    assert report.custody.read_bytes(*raw_key(record)) == record["payload"]


@pytest.mark.parametrize("case", ["byte_flip", "digest", "length", "digest_only", "count_only", "missing", "extra", "duplicate"])
def test_read_binding_rejections(case):
    data, raw = fixture()
    read = read_at(data, route=0)
    expected = "RAW_CLAIM_CONFLICT"
    if case == "byte_flip":
        raw[0]["payload"] = b"X" + raw[0]["payload"][1:]
    elif case == "digest":
        read["sha256"] = "b" * 64
    elif case == "length":
        read["byte_count"] += 1
    elif case == "digest_only":
        read["byte_count"] = None
    elif case == "count_only":
        read["sha256"] = None
    elif case == "missing":
        raw.pop()
        expected = "RAW_READ_MISSING"
    elif case == "extra":
        raw.append({**raw[0], "frame_index": 3})
        expected = "RAW_READ_UNEXPECTED"
    else:
        raw.append(dict(raw[0]))
        expected = "DUPLICATE_READ"
    report, result = check(data, raw, evaluated=False)
    assert result["classification"] == ("INCOMPLETE" if case == "missing" else "INVALID")
    assert result["reason_codes"] == [expected]
    if case == "byte_flip":
        assert report.custody.read_bytes(*raw_key(raw[0])) == raw[0]["payload"]


@pytest.mark.parametrize("offset", range(len(RAW)))
def test_each_byte_corruption_is_detected(offset):
    data, raw = fixture()
    corrupted = bytearray(raw[0]["payload"])
    corrupted[offset] ^= 1
    raw[0]["payload"] = bytes(corrupted)
    report, result = check(data, raw, evaluated=False)
    assert result["classification"] == "INVALID"
    assert result["reason_codes"] == ["RAW_CLAIM_CONFLICT"]
    assert report.custody.read_bytes(*raw_key(raw[0])) == bytes(corrupted)


def test_invalid_takes_precedence_over_missing_payload():
    data, raw = fixture()
    raw.pop()
    raw[0]["payload"] += b"corruption"
    _, result = check(data, raw, evaluated=False)
    assert result["classification"] == "INVALID"
    assert result["invalid_reason_codes"] == ["RAW_CLAIM_CONFLICT"]
    assert result["incomplete_reason_codes"] == ["RAW_READ_MISSING"]


@pytest.mark.parametrize("code", integration.READ_CODES)
@pytest.mark.parametrize("case", ["clean", "raw", "empty_raw", "digest", "count"])
def test_failed_read_custody(code, case):
    data, raw = fixture()
    read = read_at(data, route=0)
    timestamps = (read["start_ns"], read["end_ns"])
    read.update(status="FAILED", sha256=None, byte_count=0, reason_codes=[code])
    if case == "clean":
        raw.pop(0)
    elif case == "empty_raw":
        raw[0]["payload"] = b""
    elif case == "digest":
        raw.pop(0)
        read["sha256"] = hashlib.sha256(b"").hexdigest()
    elif case == "count":
        raw.pop(0)
        read["byte_count"] = 1
    report, result = check(rebind(data), raw, evaluated=case == "clean")
    if case == "clean":
        assert result["classification"] == "INCOMPLETE"
        assert code in result["integration_report"]["reason_codes"]
        kept = read_at(report.to_request(), route=0)
        assert kept["sha256"] is None and kept["byte_count"] == 0
        assert (kept["start_ns"], kept["end_ns"]) == timestamps
    else:
        assert result["classification"] == "INVALID"
        assert result["reason_codes"] == ["FAILED_READ_BYTES"]
    assert result["worker_absence_proven"] is False


@pytest.mark.parametrize("field,code", [("ppid", "PROCESS_REPARENTED"), ("starttime_ticks", "PID_REUSE")])
@pytest.mark.parametrize("frame", [0, 1])
def test_identity_diagnostics(field, code, frame):
    data, raw = fixture()
    data["routes"][1]["capture"]["frames"][frame]["processes"][0]["identity"][field] += 1
    _, result = check(rebind(data), raw)
    assert result["classification"] == "INCOMPLETE"
    assert result["integration_report"]["reason_codes"] == sorted([code, "SOURCE_DISAGREEMENT"])


@pytest.mark.parametrize("case,code", [("boot", "BOOT_ID_CONFLICT"), ("namespace", "NAMESPACE_CONTRADICTION"),
    ("procfs", "MOUNT_CONTRADICTION"), ("nsfs", "MOUNT_CONTRADICTION"),
    ("descriptor_alias", "DESCRIPTOR_ALIAS"), ("descriptor_changed", "DESCRIPTOR_CHANGED"),
    ("source", "SOURCE_LABEL_CONFLICT"), ("domain", "SOURCE_ALIAS"), ("label", "LABEL_INVALID"),
    ("window", "READ_WINDOW_INVALID")])
def test_predecessor_failures_are_preserved(case, code):
    data, raw = fixture()
    route = data["routes"][1]
    cap = route["capture"]
    if case == "boot":
        cap["boot_id"] = "22345678-1234-5678-90ab-123456789abc"
    elif case == "namespace":
        cap["namespace"]["value"] += 1
    elif case in ("procfs", "nsfs"):
        cap[case]["mount_id"] += 1
    elif case == "descriptor_alias":
        cap["frames"][0]["processes"][0]["descriptors"][0]["st_ino"] = 1001
    elif case == "descriptor_changed":
        cap["frames"][1]["processes"][0]["descriptors"][0]["st_ino"] += 100
    elif case == "source":
        cap["source_kind"] = "NATIVE_PROCFS_UNVERIFIED"
    elif case == "domain":
        route["provenance"]["collection_domain"] = data["routes"][0]["provenance"]["collection_domain"]
    elif case == "label":
        route["provenance"]["route_id"] = "/private/secret"
    else:
        data["reference"]["window"]["end_ns"] -= 1
    _, result = check(rebind(data), raw)
    assert code in result["integration_report"]["reason_codes"]
    assert result["classification"] == ("INVALID" if code in integration.INVALID_CODES else "INCOMPLETE")
    assert "/private/secret" not in integration.canonical_json(result)


@pytest.mark.parametrize("case,code", [("read", "PARTIAL_FRAME"), ("frame", "FRAME_MISSING"),
    ("worker_first", "WORKER_LATE_OBSERVATION"), ("worker_last", "WORKER_EARLY_LAST_OBSERVATION"),
    ("roster", "ROSTER_DRIFT"), ("coverage", "COVERAGE_GAP"), ("partial", "PARTIAL_FRAME")])
def test_incomplete_structure_is_not_repaired(case, code):
    data, raw = fixture()
    cap = data["routes"][1]["capture"]
    if case == "read":
        cap["frames"][0]["processes"][0]["reads"].pop()
    elif case == "frame":
        cap["frames"].pop()
    elif case.startswith("worker"):
        frame = cap["frames"][0 if case == "worker_first" else -1]
        frame["observed_pids"].pop()
        frame["processes"].pop()
    elif case == "roster":
        cap["roster"].reverse()
    elif case == "coverage":
        data["reference"]["window"]["end_ns"] += 1
    else:
        cap["frames"][0]["read_complete"] = False
    raw = retain_referenced_reads(data, raw)
    _, result = check(rebind(data), raw)
    assert result["classification"] == "INCOMPLETE"
    assert code in result["integration_report"]["reason_codes"]
    assert result["semantic_report"]["semantic"]["classification"] == "NOT_EVALUATED"


@pytest.mark.parametrize("case", ["frame", "read"])
@pytest.mark.parametrize("delta", [5, 6])
def test_inclusive_route_skew(case, delta):
    data, raw = fixture()
    if case == "frame":
        # Shortening this frame also widens the gap before the next frame.
        data["limits"]["max_gap_ns"] = 1000
        data["routes"][1]["capture"]["frames"][0]["end_ns"] -= delta
    else:
        read_at(data, process=1, leaf=2)["end_ns"] += delta
    _, result = check(rebind(data), raw)
    assert result["integration_report"]["reason_codes"] == ([] if delta == 5 else ["ROUTE_SKEW_EXCEEDED"])
    assert result["classification"] == ("ASSEMBLED_NONQUALIFYING" if delta == 5 else "INCOMPLETE")


@pytest.mark.parametrize("limit,code", [("max_read_ns", "FRAME_DURATION_EXCEEDED"), ("max_gap_ns", "READ_GAP_EXCEEDED")])
@pytest.mark.parametrize("value", [499, 500])
def test_inclusive_duration_and_gap(limit, code, value):
    data, raw = fixture()
    data["limits"][limit] = value
    _, result = check(data, raw)
    assert result["integration_report"]["reason_codes"] == ([code] if value == 499 else [])


@pytest.mark.parametrize("size", [0, 65536, 65537])
def test_read_size_boundaries(size):
    data, raw = fixture(payload=b"x" * size)
    _, result = check(data, raw, evaluated=size <= 65536)
    assert result["classification"] == ("ASSEMBLED_NONQUALIFYING" if size <= 65536 else "INVALID")
    if size > 65536:
        assert result["reason_codes"] == ["INPUT_CAP_EXCEEDED"]


@pytest.mark.parametrize("frames,pids,valid", [(2, 64, True), (2, 65, False), (32, 2, True), (33, 2, False),
    (1, 2, False), (0, 2, False), (32, 64, False)])
def test_capacity_intersection(frames, pids, valid):
    data, raw = fixture(frames=frames, pids=pids)
    if frames == 0:
        data["reference"]["window"] = {"start_ns": 100, "end_ns": 100}
    _, result = check(data, raw, evaluated=valid)
    assert result["classification"] == ("ASSEMBLED_NONQUALIFYING" if valid else "INVALID")
    if (frames, pids) == (32, 64):
        assert result["reason_codes"] == ["INPUT_CAP_EXCEEDED"]


def budget_fixture(extra=0):
    data, raw = fixture(frames=12, pids=2, payload=b"")
    available = assembly.MAX_PAYLOAD_BYTES + extra - sum(
        assembly.READ_ENTRY_OVERHEAD + len(item["path_id"].encode("ascii")) for item in raw)
    for item in raw:
        count = min(assembly.MAX_READ_BYTES, available)
        item["payload"] = b"x" * count
        available -= count
    assert available == 0
    for item in raw:
        read = next(r for r in data["routes"][item["route_index"]]["capture"]["frames"][item["frame_index"]]["processes"]
                    [(item["pid"] - 100) // 100]["reads"] if r["path_id"] == item["path_id"])
        read.update(sha256=hashlib.sha256(item["payload"]).hexdigest(), byte_count=len(item["payload"]))
    return rebind(data), raw


@pytest.mark.parametrize("extra", [0, 1])
def test_total_payload_and_overhead_exact_boundary(extra):
    data, raw = budget_fixture(extra)
    report, result = check(data, raw, evaluated=extra == 0)
    if extra:
        assert result["reason_codes"] == ["INPUT_CAP_EXCEEDED"]
        assert report.custody.read_keys == ()
    else:
        assert result["payload_budget_bytes"] == assembly.MAX_PAYLOAD_BYTES
        # Byte differences between frames are real evidence, never repaired.
        assert result["classification"] == "INCOMPLETE"
        assert "STABLE_READ_DISAGREEMENT" in result["semantic_report"]["reason_codes"]


class DictSubclass(dict):
    pass


class ListSubclass(list):
    pass


class BytesSubclass(bytes):
    pass


@pytest.mark.parametrize("case", ["dict_subclass", "list_subclass", "tuple", "generator", "payload_text", "bytearray",
    "memoryview", "bytes_subclass", "bool_index", "path_os", "path_pid", "path_zero", "path_leaf", "native_mode",
    "native_opt_in", "alias_template", "alias_index", "alias_cross_inputs", "cycle", "depth", "nodes",
    "invalid_utf8", "duplicate_json", "nan", "overflow", "duplicate_frame", "duplicate_read", "partial_placeholder"])
def test_exact_types_and_bounded_inputs(case):
    data, raw = fixture()
    if case == "dict_subclass":
        data = DictSubclass(data)
    elif case == "list_subclass":
        raw = ListSubclass(raw)
    elif case == "tuple":
        raw = tuple(raw)
    elif case == "generator":
        raw = iter(raw)
    elif case == "payload_text":
        raw[0]["payload"] = "secret text"
    elif case == "bytearray":
        raw[0]["payload"] = bytearray(RAW)
    elif case == "memoryview":
        raw[0]["payload"] = memoryview(RAW)
    elif case == "bytes_subclass":
        raw[0]["payload"] = BytesSubclass(RAW)
    elif case == "bool_index":
        raw[0]["route_index"] = False
    elif case.startswith("path_"):
        raw[0]["path_id"] = {"path_os": "/proc/100/stat", "path_pid": "pids/200/identity",
                              "path_zero": "pids/0100/identity", "path_leaf": "pids/100/stat"}[case]
    elif case == "native_mode":
        data["mode"] = "NATIVE"
    elif case == "native_opt_in":
        data["native_opt_in"] = True
    elif case == "alias_template":
        data["routes"][1]["capture"]["namespace"] = data["reference"]["namespace"]
    elif case == "alias_index":
        raw.append(raw[0])
    elif case == "alias_cross_inputs":
        data["extra"] = raw[0]
    elif case == "cycle":
        data["cycle"] = data
    elif case == "depth":
        data = None
        for _ in range(integration.MAX_DEPTH + 1):
            data = [data]
    elif case == "nodes":
        data = [None] * integration.MAX_NODES
    elif case == "invalid_utf8":
        data = b"\xff"
    elif case == "duplicate_json":
        data = b'{"schema":1,"schema":2}'
    elif case == "nan":
        data = b'{"value":NaN}'
    elif case == "overflow":
        read_at(data)["end_ns"] = 1 << 64
    elif case == "duplicate_frame":
        data["routes"][0]["capture"]["frames"][1]["index"] = 0
    elif case == "duplicate_read":
        process = data["routes"][0]["capture"]["frames"][0]["processes"][0]
        process["reads"][1] = copy.deepcopy(process["reads"][0])
    else:
        read_at(data)["sha256"] = None
    # Generators/memoryviews need no deepcopy and must never be consumed.
    report = assembly.assemble_supplied_evidence(data, raw)
    result = report.to_dict()
    assert_trust(result)
    assert result["classification"] == "INVALID"
    assert result["integration_evaluation"] == "NOT_EVALUATED"
    assert "secret text" not in report.serialized
    if case == "overflow":
        assert result["reason_codes"] == ["INTEGER_INVALID"]


def test_caller_mutation_and_immutable_custody():
    data, raw = fixture()
    report, result = check(data, raw)
    serialized, digest = report.serialized, report.sha256
    key = raw_key(raw[0])
    mutable_source = bytearray(RAW)
    # Admission uses bytes, so mutation of a source buffer cannot affect it.
    raw[0]["payload"] = bytes(mutable_source)
    second = assembly.assemble_supplied_evidence(data, raw)
    mutable_source[0] ^= 1
    data.clear()
    raw.clear()
    detached = report.to_dict()
    detached["reads"].clear()
    request = report.to_request()
    request["routes"].clear()
    assert report.serialized == serialized and report.sha256 == digest
    assert report.to_dict() == result
    assert report.custody.read_bytes(*key) == second.custody.read_bytes(*key) == RAW
    with pytest.raises(FrozenInstanceError):
        report.serialized = "changed"
    with pytest.raises(FrozenInstanceError):
        report.custody.reads = ()
    with pytest.raises(FrozenInstanceError):
        report.custody.reads[0].payload = b"changed"
    with pytest.raises(TypeError):
        report.custody.read_keys[0] = key
    with pytest.raises(KeyError):
        report.custody.read_bytes(1, 31, 999, "pids/999/identity")


def test_summary_bindings_are_never_repaired():
    data, raw = fixture()
    read_at(data)["sha256"] = read_at(data)["byte_count"] = None
    # Caller hashes the unfinished capture, which must fail after binding.
    rebind(data)
    original = copy.deepcopy(data["routes"][1]["verification"])
    report, result = check(data, raw)
    assert result["classification"] == "INVALID"
    assert "DIGEST_INVALID" in result["integration_report"]["reason_codes"]
    assert report.to_request()["routes"][1]["verification"] == original


def test_determinism_and_reason_sealing():
    data, raw = fixture()
    first, result = check(data, raw)
    second = assembly.assemble_supplied_evidence(integration.canonical_json(data).encode(), list(reversed(raw)))
    assert first.serialized == second.serialized
    assert first.sha256 == second.sha256
    assert assembly._partitions({"untrusted secret", "RAW_READ_MISSING"}) == {
        "classification": "INVALID", "reason_codes": ["RAW_READ_MISSING", "REASON_CODE_INVALID"],
        "invalid_reason_codes": ["REASON_CODE_INVALID"], "incomplete_reason_codes": ["RAW_READ_MISSING"]}
    assert len(first.serialized.encode()) <= assembly.MAX_REPORT_BYTES


def seal_adapter(report):
    report.pop("integrity", None)
    report["integrity"] = {"algorithm": "sha256", "scope": "canonical result excluding integrity",
                           "sha256": integration.digest(report)}
    return report


def original_adapter(native=False):
    """Literal accepted original envelope; no adapter calls or conversions."""
    success = "CAPTURE_CONSISTENT_NONQUALIFYING"
    identities = [dict(p, boot_id=BOOT, pid_namespace_id="pidns:77",
                       role="parent" if p["pid"] == 100 else "worker") for p in roster()]
    report = {**semantic.ADAPTER_FIXED, "schema": integration.ADAPTER_SCHEMA,
        "source_kind": "NATIVE_PROCFS_UNVERIFIED" if native else "TEST_INJECTED",
        "origin_attestation": "UNVERIFIED_NATIVE_CAPTURE" if native else "UNVERIFIED",
        "clock_kind": "LOCAL_MONOTONIC_NS" if native else "INJECTED_MONOTONIC_NS",
        "outcome": success, "invalid_reason_codes": [], "incomplete_reason_codes": [], "reasons": [],
        "worker_coverage": "REGISTERED_ROSTER_OBSERVED", "run_id": "literal.fixture", "input_sha256": "c" * 64,
        "config": {"clock_ticks_per_second": 100, "boot_id": BOOT, "pid_namespace_id": "pidns:77",
            "max_read_skew_ns": 10000, "max_bytes": 4096, "max_total_bytes": 1048576,
            "max_read_attempts": 1000, "max_read_iterations": 128, "smaps_rollup_policy": "NOT_SAMPLED"},
        "roster": {"parent": copy.deepcopy(identities[0]), "workers": copy.deepcopy(identities[1:]), "complete": True},
        "frames_requested": 2, "frames": [], "read_attempts": 24, "open_attempts": 17,
        "total_bytes": 0, "first_read_start_ns": 0, "last_read_end_ns": 23, "read_skew_ns": 23}
    for index in range(2):
        processes = []
        for number, identity in enumerate(identities):
            pid, ppid, ticks = (identity[k] for k in ("pid", "ppid", "starttime_ticks"))
            parsed = {"pid": pid, "ppid": ppid, "starttime_ticks": ticks, "state": "R"}
            reads = []
            for stage, label in enumerate(("stat_before", "status", "stat_after")):
                raw = (f"{pid} (fixture) R {ppid} " + "0 " * 17 + f"{ticks}\n").encode() if label != "status" else (
                    f"Name:\tfixture\nState:\tR (running)\nTgid:\t{pid}\nPid:\t{pid}\nPPid:\t{ppid}\nVmRSS:\t5 kB\nVmHWM:\t20 kB\n").encode()
                start = 2 * (index * 6 + stage * 2 + number)
                reads.append({"label": label, "kind": "status" if label == "status" else "stat", "pid": pid,
                    "status": "OK", "start_ns": start, "end_ns": start + 1, "byte_length": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(), "byte_provenance_complete": True, "read_calls": 2,
                    "requested_limits": [4097, 4097 - len(raw)], "reason_codes": [], "exception_class": None})
                report["total_bytes"] += len(raw)
            processes.append({"identity": copy.deepcopy(identity), "status": success, "reason_codes": [],
                "reads": reads, "stat_before_identity": copy.deepcopy(parsed), "stat_after_identity": copy.deepcopy(parsed),
                "open_exception_class": None, "vmrss_bytes": 5120, "vmhwm_bytes": 20480, "smaps_rollup": None})
        report["frames"].append({"index": index, "status": success, "reason_codes": [], "processes": processes,
            "observed_pids": [100, 200], "roster_complete": True, "first_read_start_ns": index * 12,
            "last_read_end_ns": index * 12 + 11, "read_skew_ns": 11, "read_window_complete": True})
    return seal_adapter(report)


def original_bridge(method="INJECTED_STRUCTURED"):
    report = {**semantic.BRIDGE_FIXED, "schema": integration.VERIFIERS["BRIDGE_H0"][0], "outcome": "CONSISTENT",
        "reason_codes": [], "invalid_reason_codes": [], "incomplete_reason_codes": [], "request_sha256": "a" * 64,
        "registered_roster": roster(), "source_acquisition": "CALLER_CONFIGURED_ONLY",
        "cross_source_structural_agreement": "AGREES", "observations": [],
        "providers": [{"provider_id": name, "source_id": name + "_source", "fixture_id": name + "_fixture",
                       "declared_origin": "INJECTED_TEST_ONLY"} for name in ("left", "right")]}
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
                    "provider_status": "OK", "provider_reason": None, "status": "OK", "reason_codes": [], "operation_errors": []})
    return report


def original_probe():
    report = {**semantic.PROBE_FIXED, "schema": integration.PROBE_SCHEMA, "outcome": "CONSISTENT",
        "invalid_reason_codes": [], "incomplete_reason_codes": [], "reason_codes": [],
        "trust_level": "INJECTED_LOCAL_PROBE", "context_pid": 100, "context_identity": roster()[0],
        "target_pids": [200], "target_identities": roster()[1:], "input_sha256": "a" * 64,
        "reference_sha256": None, "frame_coverage": "CALLER_ASSERTED_WINDOWS_ONLY", "reads": []}
    paths = ["boot_id", "mount", "pids/100/identity", "pids/100/namespace", "pids/200/identity", "pids/200/namespace"]
    for index, path in enumerate(paths * 2):
        report["reads"].append({"source": path, "start_ns": index * 2, "end_ns": index * 2 + 1, "failure_codes": [],
            "provenance": "INJECTED_LOCAL_PROBE", "sha256": "b" * 64, "descriptor_stable": True})
    return report


def original(kind, native=False, method="INJECTED_STRUCTURED"):
    return original_adapter(native) if kind == "ADAPTER_D2B2" else original_probe() if kind == "PROBE_B3A" else original_bridge(method)


def submitted_reports(data, kinds=("ADAPTER_D2B2", "BRIDGE_H0"), pretty=True, method="INJECTED_STRUCTURED"):
    submitted = []
    for route_index, kind in enumerate(kinds):
        route = data["routes"][route_index]
        source = original(kind, route["capture"]["source_state"] == "NATIVE_PROCFS_UNVERIFIED", method)
        payload = integration.canonical_json(source).encode() if pretty else json.dumps(source).encode()
        verification = route["verification"]
        verification.update(validator=kind, upstream_schema=source["schema"], outcome=source["outcome"],
                            report_sha256=hashlib.sha256(payload).hexdigest())
        submitted.append({"route_index": route_index, "kind": kind, "payload": payload})
    return submitted


@pytest.mark.parametrize("kinds,native", [(("ADAPTER_D2B2", "BRIDGE_H0"), False),
    (("PROBE_B3A", "ADAPTER_D2B2"), False), (("ADAPTER_D2B2", "ADAPTER_D2B2"), True)])
@pytest.mark.parametrize("pretty", [False, True])
@pytest.mark.parametrize("method", ["INJECTED_STRUCTURED", "INJECTED_JSON_BYTES"])
def test_original_report_custody_and_unsupported_conversion(kinds, native, pretty, method):
    data, raw = fixture(native)
    upstream = submitted_reports(data, kinds, pretty, method)
    report, result = check(data, raw, upstream)
    assert result["classification"] == "ASSEMBLED_NONQUALIFYING"
    assert result["reason_codes"] == []
    for item, summary in zip(upstream, result["upstream_reports"]):
        imported = semantic.import_upstream_report(item["kind"], item["payload"])
        assert summary["raw_sha256"] == hashlib.sha256(item["payload"]).hexdigest()
        assert summary["import_report"] == imported.to_dict()
        assert summary["import_report_sha256"] == imported.sha256
        assert summary["import_report"]["canonical_report_sha256"] == integration.digest(json.loads(item["payload"]))
        assert summary["import_report"]["conversion"] == "UNSUPPORTED_LOSSLESS_CONVERSION"
        assert summary["import_report"]["converted_capture"] is None
        assert summary["summary_binding"] == "HASH_AND_ENVELOPE_MATCH_CALLER_ASSERTED"
        assert summary["verification_provenance"] == "CALLER_ASSERTED" and not summary["source_authenticated"]
        assert report.custody.upstream_bytes(item["route_index"], item["kind"]) == item["payload"]
    assert "literal.fixture" not in report.serialized
    assert report.custody.upstream_keys == tuple((i, k) for i, k in enumerate(kinds))


@pytest.mark.parametrize("case", ["hash", "kind", "schema", "outcome", "reason_codes", "invalid_reason_codes",
    "incomplete_reason_codes", "origin_injected", "origin_native", "duplicate", "malformed", "duplicate_json",
    "summary_substitution", "fabricated_success", "bridge_missing_path", "report_nonbytes", "report_unknown_kind"])
def test_upstream_binding_rejects_conflicts(case):
    native = case == "origin_injected"
    data, raw = fixture(native)
    upstream = submitted_reports(data, ("ADAPTER_D2B2", "ADAPTER_D2B2"))
    verification = data["routes"][0]["verification"]
    if case == "hash":
        verification["report_sha256"] = "b" * 64
    elif case == "kind":
        verification["validator"] = "PROBE_B3A"
    elif case == "schema":
        verification["upstream_schema"] = integration.PROBE_SCHEMA
    elif case == "outcome":
        verification["outcome"] = "INVALID"
    elif case.endswith("reason_codes"):
        verification[case] = ["SCHEMA_INVALID"]
    elif case in ("origin_injected", "origin_native"):
        source = original_adapter(native=case == "origin_native")
        upstream[0]["payload"] = integration.canonical_json(source).encode()
    elif case == "duplicate":
        upstream[1] = dict(upstream[0])
    elif case == "malformed":
        upstream[0]["payload"] = b"\xff"
    elif case == "duplicate_json":
        upstream[0]["payload"] = b'{"schema":1,"schema":2}'
    elif case == "summary_substitution":
        upstream[0]["payload"] = integration.canonical_json(verification).encode()
    elif case == "fabricated_success":
        source = original_adapter()
        source.update(worker_coverage="NOT_ESTABLISHED", frames=[], run_id=None, config=None, roster=None,
                      input_sha256=None, frames_requested=None)
        upstream[0]["payload"] = integration.canonical_json(seal_adapter(source)).encode()
    elif case == "bridge_missing_path":
        upstream = submitted_reports(data, ("BRIDGE_H0", "ADAPTER_D2B2"))
        source = json.loads(upstream[0]["payload"])
        source["observations"].pop()
        upstream[0]["payload"] = integration.canonical_json(source).encode()
    elif case == "report_nonbytes":
        upstream[0]["payload"] = bytearray(upstream[0]["payload"])
    else:
        upstream[0]["kind"] = "UNKNOWN"
    if type(upstream[0]["payload"]) is bytes and case not in ("hash", "duplicate"):
        data["routes"][0]["verification"]["report_sha256"] = hashlib.sha256(upstream[0]["payload"]).hexdigest()
    evaluated = case not in ("duplicate", "report_nonbytes", "report_unknown_kind")
    report, result = check(data, raw, upstream, evaluated=evaluated)
    assert result["classification"] == "INVALID"
    if evaluated:
        assert result["upstream_reports"][0]["summary_binding"] == "CONFLICT"
        assert report.custody.upstream_bytes(0, upstream[0]["kind"]) == upstream[0]["payload"]


@pytest.mark.parametrize("outcome,code", [("INVALID", "SCHEMA_INVALID"), ("INCOMPLETE", "PERMISSION_DENIED")])
def test_original_unfavorable_verdict_is_retained(outcome, code):
    data, raw = fixture()
    upstream = submitted_reports(data, ("ADAPTER_D2B2", "ADAPTER_D2B2"))
    source = json.loads(upstream[0]["payload"])
    source.update(outcome=outcome, worker_coverage="UNCERTAIN", reasons=[{"code": code, "location": "frame/0"}],
                  invalid_reason_codes=[code] if outcome == "INVALID" else [],
                  incomplete_reason_codes=[code] if outcome == "INCOMPLETE" else [])
    if outcome == "INVALID":
        # A literal preflight rejection has no attempted capture metadata.
        source.update(worker_coverage="NOT_ESTABLISHED", run_id=None, input_sha256=None, config=None, roster=None,
                      frames_requested=None, frames=[], read_attempts=0, open_attempts=0, total_bytes=0,
                      first_read_start_ns=None, last_read_end_ns=None, read_skew_ns=None,
                      reasons=[{"code": code, "location": "request"}])
    else:
        frame = source["frames"][0]
        frame.update(status="INCOMPLETE", reason_codes=[code])
        process = frame["processes"][0]
        process.update(status="INCOMPLETE", reason_codes=[code])
        failed = process["reads"][1]
        source["total_bytes"] -= failed["byte_length"]
        failed.update(status="FAILED", sha256=None, byte_length=0, byte_provenance_complete=False,
                      reason_codes=[code], exception_class="PermissionError")
    payload = integration.canonical_json(seal_adapter(source)).encode()
    upstream[0]["payload"] = payload
    data["routes"][0]["verification"].update(outcome=outcome, reason_codes=[code],
        invalid_reason_codes=source["invalid_reason_codes"].copy(),
        incomplete_reason_codes=source["incomplete_reason_codes"].copy(), report_sha256=hashlib.sha256(payload).hexdigest())
    report, result = check(data, raw, upstream)
    assert result["classification"] == outcome
    imported = result["upstream_reports"][0]["import_report"]
    assert imported["original"]["original_outcome"] == outcome
    assert imported["original"]["original_reason_codes"] == [code]
    assert result["upstream_reports"][0]["summary_binding"] == "HASH_AND_ENVELOPE_MATCH_CALLER_ASSERTED"
    assert ("UPSTREAM_INVALID" if outcome == "INVALID" else "UPSTREAM_INCOMPLETE") in result["reason_codes"]
    assert report.custody.upstream_bytes(0, "ADAPTER_D2B2") == payload


def test_upstream_bytes_share_total_budget_and_do_not_establish_independence():
    data, raw = budget_fixture()
    upstream = submitted_reports(data, ("ADAPTER_D2B2", "ADAPTER_D2B2"))
    _, result = check(data, raw, upstream, evaluated=False)
    assert result["reason_codes"] == ["INPUT_CAP_EXCEEDED"]
    data, raw = fixture()
    upstream = submitted_reports(data, ("ADAPTER_D2B2", "ADAPTER_D2B2"))
    assert upstream[0]["payload"] == upstream[1]["payload"]
    report, result = check(data, raw, upstream)
    assert result["independence"] == "INDEPENDENCE_NOT_ESTABLISHED"
    before = report.serialized
    upstream[0]["payload"] = b"changed"
    upstream.clear()
    assert report.serialized == before
    with pytest.raises(KeyError):
        report.custody.upstream_bytes(0, "BRIDGE_H0")


def test_admitted_originals_are_visible_when_template_binding_fails():
    data, raw = fixture()
    upstream = submitted_reports(data)
    read_at(data)["sha256"] = None  # A contradictory, half-filled placeholder.
    report, result = check(data, raw, upstream, evaluated=False)
    assert result["reason_codes"] == ["RAW_CLAIM_CONFLICT"]
    for item, summary in zip(upstream, result["upstream_reports"]):
        assert summary["custody"] == "EXACT_BYTES_RETAINED"
        assert summary["import_evaluation"] == "NOT_EVALUATED"
        assert summary["import_report"] is None
        assert summary["raw_sha256"] == hashlib.sha256(item["payload"]).hexdigest()
        assert report.custody.upstream_bytes(item["route_index"], item["kind"]) == item["payload"]


def test_report_budget_fallback_is_explicit(monkeypatch):
    data, raw = fixture()
    monkeypatch.setattr(assembly, "MAX_REPORT_BYTES", 1)
    report = assembly.assemble_supplied_evidence(data, raw)
    result = report.to_dict()
    assert result["classification"] == "INVALID"
    assert result["read_summary_omitted"] is True and result["reads"] == []
    assert result["read_count"] == len(raw)
    assert len(report.custody.read_keys) == len(raw)
    assert result["integration_report"]["outcome"] == "CONSISTENT"


def test_implementation_has_only_inert_dependencies_and_calls():
    """Inspect in-memory code objects without opening source files or hooks."""
    forbidden = {"open", "read_text", "read_bytes", "readlink", "stat", "lstat", "clock_gettime", "monotonic_ns",
                 "time_ns", "perf_counter", "run", "Popen", "socket", "urlopen", "eval", "exec", "__import__",
                 "preview_injected_bridge", "acquire_provenance_bridge"}

    def inspect_code(code):
        assert not set(code.co_names) & forbidden
        for constant in code.co_consts:
            if type(constant) is CodeType:
                inspect_code(constant)

    for value in vars(assembly).values():
        if type(value) is type(fixture) and value.__module__ == assembly.__name__:
            inspect_code(value.__code__)
        elif type(value) is type and value.__module__ == assembly.__name__:
            for member in vars(value).values():
                if type(member) is property:
                    inspect_code(member.fget.__code__)
                elif type(member) is type(fixture):
                    inspect_code(member.__code__)
    assert {name for name, value in vars(assembly).items() if type(value).__name__ == "module"} == {
        "hashlib", "json", "re", "semantic", "integration"}
