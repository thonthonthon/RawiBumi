"""Tiny synthetic contracts only. No measurement children or live M0a calls."""

import ast
import copy
import json
import platform
import sys
from types import SimpleNamespace

import pytest

from scripts.benchmarks import rb_post3d_08p2e2_r2e_memory as h


FUTURE_TASK = b"Future independently approved scope\nR2E_MEMORY_EXECUTION_AUTHORIZED: M0a,M0b,M1\n"


def forbidden(*args, **kwargs):
    raise AssertionError("Real measurement/process execution is forbidden in synthetic tests")


@pytest.fixture(autouse=True)
def prohibit_real_measurements(monkeypatch):
    monkeypatch.setattr(h, "page_touched", forbidden)
    monkeypatch.setattr(h, "collect_preflight", forbidden)
    monkeypatch.setattr(h.subprocess, "Popen", forbidden)
    monkeypatch.setattr(h.tracemalloc, "start", forbidden)
    monkeypatch.setattr(h, "read_watchdog_rss", forbidden)
    monkeypatch.setattr(h.os, "killpg", forbidden)
    monkeypatch.setattr(h.time, "sleep", forbidden)


@pytest.fixture
def auth():
    return h.authorize(FUTURE_TASK, h.sha256(FUTURE_TASK))


def status_values(rss=32 * h.MIB, hwm=None, swap=0):
    return {"VmRSS": rss, "VmHWM": rss if hwm is None else hwm,
            "RssAnon": rss // 2, "VmSwap": swap}


def status_text():
    return "Name:\tsynthetic\nVmRSS: 32768 kB\nVmHWM: 40960 kB\nRssAnon: 16384 kB\nVmSwap: 0 kB\n"


def smaps_text():
    return "00400000-00500000 ---p 00000000 00:00 0 [rollup]\nRss: 32768 kB\nAnonHugePages: 0 kB\nSwap: 0 kB\n"


def cgroup_files():
    return {"/proc/self/cgroup": "0::/example\n",
            "/sys/fs/cgroup/example/memory.max": "max\n",
            "/sys/fs/cgroup/example/memory.current": "1024\n",
            "/sys/fs/cgroup/example/memory.swap.max": "0\n",
            "/sys/fs/cgroup/example/memory.swap.current": "0\n",
            "/sys/fs/cgroup/example/memory.events": "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n",
            "/sys/fs/cgroup/example/cpuset.cpus.effective": "0-1\n"}


def facts():
    return {"head": h.EXPECTED_HEAD, "branch": h.EXPECTED_BRANCH, "dirty_state": "synthetic",
            "implementation": "CPython", "version": [3, 12, 3], "system": "Linux",
            "kernel": "synthetic-linux", "machine": "x86_64", "python_build": ["synthetic", "date"],
            "executable": "/synthetic/python", "python_version": "CPython 3.12.3 synthetic",
            "allocated_blocks": 123, "page_size_bytes": 4096,
            "compiler": "synthetic", "with_pymalloc": 1, "py_debug": 0, "debug_refcounts": False,
            "gc_enabled": True, "gc_thresholds": [700, 10, 10], "tracing": False,
            "trace_hook": False, "profile_hook": False, "dev_mode": False,
            "ignore_environment": False, "hash_randomization": 0, "allocator_environment": {}, "hashseed": "0",
            "clear_refs_exists": True, "clear_refs_writable": True,
            "status_text": status_text(), "smaps_text": smaps_text(),
            "meminfo_text": "MemTotal: 8388608 kB\nMemAvailable: 4194304 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n",
            "swaps_text": "Filename\tType\tSize\tUsed\tPriority\n",
            "thp_enabled": "always [madvise] never\n", "thp_defrag": "always defer [madvise] never\n",
            "cgroup": h.cgroup_facts(cgroup_files().__getitem__), "affinity": [0, 1], "boot_id": "synthetic-boot"}


def source_bytes():
    return (h.ROOT / h.SOURCE).read_bytes()


def snapshot(rss):
    return {"status": status_values(rss), "smaps_rollup": {"Rss": rss, "AnonHugePages": 0, "Swap": 0}}


def fake_statistics(role):
    capacity = 256 if role.endswith("BASE") else 1024
    # Occupancy metadata only. No workload dictionary or retained-entry allocation.
    return {"slot_count": 512, "capacity_per_slot": capacity,
            "retained_entries": 512 * capacity, "occupancy": [capacity] * 512}


def fake_payload(role):
    if role == "M0a":
        return h.inspect_preflight(facts(), source_bytes())
    statistics = fake_statistics(role) if role in h.M1_ROLES else None
    if role.startswith("T-"):
        increment = h.KNOWN_BYTES if role == "T-KNOWN" else (1000 if role.endswith("BASE") else 2000)
        return {"role": role, "mode": "TRACED", "statistics": statistics,
                "traced_baseline_bytes": 128, "traced_current_bytes": 128 + increment,
                "traced_peak_bytes": 256 + increment, "traced_increment_bytes": increment,
                "post_release_traced_current_bytes": 128, "post_release_traced_peak_bytes": 256 + increment}
    baseline = 32 * h.MIB
    increment = (0 if role == "R-NULL" else
                 (16 * h.MIB if role == "R-KNOWN" or role.endswith("BASE") else 32 * h.MIB))
    released = snapshot(baseline)
    released["status"]["VmHWM"] = baseline + increment
    return {"role": role, "mode": "RSS", "statistics": statistics,
            "reset": {"verified": True, "before": status_values(hwm=40 * h.MIB),
                      "after": status_values()},
            "before": snapshot(baseline), "retained": snapshot(baseline + increment),
            "post_release": released}


def fake_results(roles):
    return [{"role": role, "outcome": None, "payload": fake_payload(role)} for role in roles]


def historical_r2fb_results():
    # Literal R2F-B readings, SHA-256 292f407c3fb935b00932468c844f084bdefce25e43fe1762f3afc29bf0963cbe.
    # A counterfactual fixture only: never read or rewrite the gitignored report.
    results = fake_results(h.M1_ROLES)
    for item, current, peak, released in zip(
            results[:2], (25340056, 101245080), (25340206, 101245230), (4888, 19224)):
        item["payload"].update(traced_baseline_bytes=0, traced_current_bytes=current,
                               traced_increment_bytes=current, traced_peak_bytes=peak,
                               post_release_traced_current_bytes=released,
                               post_release_traced_peak_bytes=peak)
    # A1, B1, B2, A2; snapshots are (VmRSS, VmHWM, RssAnon, smaps Rss).
    readings = (
        (33198080, (24920064, 24920064, 14155776, 24920064),
         (51310592, 51310592, 40546304, 51310592),
         (31391744, 51154944, 20627456, 31391744)),
        (33333248, (24944640, 24944640, 14155776, 24944640),
         (135028736, 135028736, 124239872, 135032832),
         (29679616, 134914048, 18890752, 29679616)),
        (33402880, (25067520, 25067520, 14155776, 25067520),
         (135151616, 135151616, 124239872, 135155712),
         (29442048, 134983680, 18530304, 29442048)),
        (33144832, (24907776, 24907776, 14151680, 24907776),
         (51298304, 51298304, 40542208, 51298304),
         (31690752, 51101696, 20934656, 31690752)))
    for item, (prior_hwm, before, retained, released) in zip(results[2:], readings):
        child = item["payload"]
        for point, (rss, hwm, anon, smaps_rss) in zip(
                ("before", "retained", "post_release"), (before, retained, released)):
            child[point] = {"status": {"VmRSS": rss, "VmHWM": hwm, "RssAnon": anon, "VmSwap": 0},
                            "smaps_rollup": {"Rss": smaps_rss, "AnonHugePages": 0, "Swap": 0}}
        child["reset"] = {"verified": True, "after": dict(child["before"]["status"]),
                          "before": {**child["before"]["status"], "VmHWM": prior_hwm},
                          "verification_rule": "prior_hwm_above_rss_then_hwm_drops_to_current_rss"}
        child.update(null_window=None, pre_window_spike_bytes=8388608)
    return results


def fake_report(auth, stage="M0b"):
    report = h.new_report(auth, stage)
    report["preflight"] = fake_payload("M0a")
    report["provenance"]["measurement_identity"] = h.measurement_identity(report["preflight"])
    report["calibration"] = h.calibration_outcome(fake_results(h.CALIBRATION_ROLES))
    report["outcome"] = "CALIBRATION_PASS"
    return report


def test_required_platform_and_dictionary_growth():
    assert platform.python_implementation() == "CPython"
    assert sys.version_info[:3] == (3, 12, 3)
    assert platform.system() == "Linux"
    dictionary = {}
    sizes = {0: sys.getsizeof(dictionary)}
    for index in range(1, 685):
        dictionary[index] = float(index)
        sizes[index] = sys.getsizeof(dictionary)
    changes = [index for index in range(1, 685) if sizes[index] != sizes[index - 1]]
    assert changes == [1, 6, 11, 22, 43, 86, 171, 342, 683]
    assert sizes[171] == sizes[256] == sizes[341]
    assert sizes[342] == sizes[682]
    assert sizes[683] == sizes[684]


def test_exact_real_source_guard_and_tampered_copy(tmp_path):
    original = source_bytes()
    assert h.guard_source(original) == {"sha256": h.SOURCE_SHA256, "ast_memo_limit": 256}
    tampered = tmp_path / "source.py"
    tampered.write_bytes(original + b"\n# changed bytes\n")
    with pytest.raises(h.HarnessError, match="SHA-256"):
        h.guard_source(tampered.read_bytes())


@pytest.mark.parametrize("code", [
    "", "# _BRANCH_CURRENT_MEMO_LIMIT = 256\n", "_BRANCH_CURRENT_MEMO_LIMIT = 1024\n",
    "_BRANCH_CURRENT_MEMO_LIMIT = True\n", "_BRANCH_CURRENT_MEMO_LIMIT = 256.0\n",
    "_BRANCH_CURRENT_MEMO_LIMIT = 256\n_BRANCH_CURRENT_MEMO_LIMIT = 256\n",
    "def f():\n    _BRANCH_CURRENT_MEMO_LIMIT = 256\n", "_BRANCH_CURRENT_MEMO_LIMIT += 256\n",
])
def test_ast_rejects_noncanonical_limits_even_with_matching_fixture_hash(code):
    raw = code.encode()
    with pytest.raises(h.HarnessError):
        h.guard_source(raw, h.sha256(raw))


def test_ast_accepts_single_integer_assignment():
    raw = b"_BRANCH_CURRENT_MEMO_LIMIT = 256\n"
    assert h.guard_source(raw, h.sha256(raw))["ast_memo_limit"] == 256


def test_stdlib_only_and_no_production_imports():
    tree = ast.parse(h.Path(h.__file__).read_bytes())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module.split(".")[0])
    assert imports and set(imports) <= sys.stdlib_module_names


def test_experiment_and_source_safety_invariants():
    assert h.SOURCE_SHA256 == "45157f6a93c9e066b54ddffe70875cf06bed4a17816ca8a0cd797d4120b1a3ba"
    assert h.SLOTS == 512 and h.ADDITIONAL_ENTRIES == 393216
    assert h.CALIBRATION_ROLES == ("R-NULL", "R-KNOWN", "T-KNOWN")
    assert h.M1_ROLES == ("T-BASE", "T-CAND", "R-BASE", "R-CAND", "R-CAND", "R-BASE")
    assert 0 < h.EXIT_GRACE_SECONDS <= 0.5
    assert type(h.EXIT_GRACE_POLLS) is int and h.EXIT_GRACE_POLLS > 0
    assert h.SCHEMA == "rb-post3d-08p2e2-r2e-memory-v1"
    tree = ast.parse(h.Path(h.__file__).read_bytes())
    reset_opens = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name) and node.func.id == "open"
                   and node.args and isinstance(node.args[0], ast.Constant)
                   and node.args[0].value == "/proc/self/clear_refs"]
    assert len(reset_opens) == 1
    assert reset_opens[0].args[1].value == "w"
    # Incompatible hosts must fail; decorators and runtime skips cannot hide them.
    tests = ast.parse(h.Path(__file__).read_bytes())
    prohibited = {"skip", "skipif", "xfail", "importorskip"}
    assert not [node for node in ast.walk(tests)
                if isinstance(node, ast.Attribute) and node.attr in prohibited]


def test_keys_identity_sharing_distinct_values_and_signed_zero():
    payload = h.build_payload(2, 4, unique_count=6)
    assert all(type(slot) is dict for slot in payload.slots)
    assert payload.slots[0] is not payload.slots[1]
    keys = [key for slot in payload.slots for key in slot]
    assert keys[0][0] == float.hex(0.0) and keys[1][0] == float.hex(-0.0)
    assert keys[0] != keys[1]
    assert all(key[1] is keys[0][1] and key[2] is keys[0][2] and key[3] == 200 for key in keys)
    assert keys[0][0] == keys[4][0] and keys[0][0] is not keys[4][0]
    values = [value for slot in payload.slots for value in slot.values()]
    assert len({id(value) for value in values}) == len(values)
    unshared = h.make_key(0.0, float(str(keys[0][1])), float(str(keys[0][2])))
    assert unshared == keys[0]
    assert unshared[1] is not keys[0][1] and unshared[2] is not keys[0][2]


def test_first_n_admission_hits_saturation_and_discarded_overflow():
    currents = {}
    for index in range(3):
        assert h.admit(currents, index, float(index), 3) == "admitted"
    before = list(currents.items())
    assert h.admit(currents, 1, -99.0, 3) == "hit"
    assert h.admit(currents, 4, 4.0, 3) == "discarded"
    assert list(currents.items()) == before


def test_deterministic_stream_and_capacity_prefix():
    stream = list(h.voltage_stream(1, 8))
    assert stream == list(h.voltage_stream(1, 8))
    assert {kind for kind, _ in stream} == {"miss", "hit", "overflow"}
    assert stream[0][1].hex() == "0x0.0p+0"
    assert stream[2][1].hex() == "-0x0.0p+0"
    base = h.build_payload(2, 3, 8)
    candidate = h.build_payload(2, 8, 8)
    assert base.statistics["retained_entries"] == 6
    assert candidate.statistics["retained_entries"] == 16
    for left, right in zip(base.slots, candidate.slots):
        assert list(left.items()) == list(right.items())[:3]
    assert base.statistics["admission_counts"]["discarded"] > 0
    assert base.statistics["admission_counts"]["hit"] > 0
    assert candidate.statistics["admission_counts"]["discarded"] == 4


def test_proc_parsers_and_injected_readers():
    assert h.parse_status(status_text())["VmHWM"] == 40 * h.MIB
    assert h.parse_smaps(smaps_text())["AnonHugePages"] == 0
    reads = []

    def read(name):
        reads.append(name)
        return status_text() if name.endswith("status") else smaps_text()

    assert h.proc_snapshot(read)["status"]["VmSwap"] == 0
    assert reads == ["/proc/self/status", "/proc/self/smaps_rollup"]


@pytest.mark.parametrize("bad", [
    "VmRSS: 1 MB\n", "VmRSS: -1 kB\n", "VmRSS: unknown kB\n", "",
    status_text() + "VmRSS: 32768 kB\n", status_text().replace("VmSwap: 0 kB\n", ""),
    status_text().replace("VmHWM: 40960", "VmHWM: 1"),
    status_text().replace("RssAnon: 16384", "RssAnon: 32769"),
])
def test_bad_status_fails_closed(bad):
    with pytest.raises(h.HarnessError):
        h.parse_status(bad)


@pytest.mark.parametrize("bad", ["", "Rss: 2 kB\nAnonHugePages: 3 kB\nSwap: 0 kB\n",
    smaps_text().replace("Swap: 0 kB", "Swap: 0 bytes"),
    smaps_text().replace("Swap: 0 kB\n", ""), smaps_text() + "Rss: 32768 kB\n",
    smaps_text().replace("Rss: 32768", "Rss: -1"),
    smaps_text().replace("Rss: 32768", "Rss: unknown")])
def test_bad_smaps_fails_closed(bad):
    with pytest.raises(h.HarnessError):
        h.parse_smaps(bad)


def test_host_parsers_and_unknown_cgroup():
    parsed = h.cgroup_facts(cgroup_files().__getitem__)
    assert parsed["memory.max"] == "max" and parsed["memory.current"] == 1024
    swap = h.parse_swaps("Filename Type Size Used Priority\n/swap file 4096 1024 -2\n")
    assert swap[0]["used_bytes"] == h.MIB
    assert h.selected_thp("always [never]")["selected"] == "never"
    for text in ("1:memory:/v1", "0::/../escape", ""):
        with pytest.raises(h.HarnessError):
            h.cgroup_facts(lambda name: text)
    with pytest.raises(h.HarnessError):
        h.parse_swaps("unexpected format")
    with pytest.raises(h.HarnessError):
        h.selected_thp("unknown")
    for cpus in ("", "unknown", "2-1", "0-2,1", "0,0", h.CPUSET_ABSENT):
        files = cgroup_files()
        files["/sys/fs/cgroup/example/cpuset.cpus.effective"] = cpus
        with pytest.raises(h.HarnessError):
            h.cgroup_facts(files.__getitem__)


def test_absent_cpuset_controller_allows_synthetic_preflight():
    files = cgroup_files()
    optional_path = "/sys/fs/cgroup/example/cpuset.cpus.effective"
    reads = []

    def read(name):
        reads.append(name)
        if name == optional_path:
            raise FileNotFoundError(name)
        return files[name]

    fixture = facts()
    fixture["cgroup"] = h.cgroup_facts(read)
    assert optional_path in reads
    assert fixture["cgroup"]["cpuset.cpus.effective"] == h.CPUSET_ABSENT
    preflight = h.inspect_preflight(fixture, source_bytes())
    assert preflight["outcome"] == "PREFLIGHT_PASS"
    identity = h.measurement_identity(preflight)
    assert identity["affinity"] == [0, 1]
    assert identity["cgroup_configuration"]["cpuset.cpus.effective"] == h.CPUSET_ABSENT
    assert identity != h.measurement_identity(h.inspect_preflight(facts(), source_bytes()))


@pytest.mark.parametrize("missing", ["memory.max", "memory.current", "memory.swap.max",
                                     "memory.swap.current", "memory.events"])
def test_required_cgroup_memory_files_remain_fail_closed(missing):
    files = cgroup_files()

    def read(name):
        if name.endswith("/" + missing):
            raise FileNotFoundError(name)
        return files[name]

    with pytest.raises(FileNotFoundError):
        h.cgroup_facts(read)


def test_cpuset_permission_failure_is_not_absence():
    def read(name):
        if name.endswith("/cpuset.cpus.effective"):
            raise PermissionError(name)
        return cgroup_files()[name]

    with pytest.raises(PermissionError):
        h.cgroup_facts(read)


def test_injected_preflight_is_read_only_and_passes():
    # No collector, git command, proc open or reset is involved.
    result = h.inspect_preflight(facts(), source_bytes())
    assert result["outcome"] == "PREFLIGHT_PASS"
    assert result["clear_refs_probe"] == "availability_only_no_write"


@pytest.mark.parametrize("key,value", [
    ("head", "0" * 40), ("branch", "wrong"), ("implementation", "PyPy"), ("version", [3, 12, 4]),
    ("system", "Darwin"), ("python_build", []), ("with_pymalloc", 0), ("py_debug", 1),
    ("debug_refcounts", True), ("gc_enabled", False), ("gc_thresholds", [700, True, 10]),
    ("tracing", True), ("trace_hook", True), ("profile_hook", True), ("dev_mode", True),
    ("allocator_environment", {"PYTHONMALLOC": "malloc"}), ("hashseed", None),
    ("ignore_environment", True), ("hash_randomization", 1),
    ("clear_refs_exists", False), ("clear_refs_writable", False),
    ("status_text", ""), ("smaps_text", ""), ("meminfo_text", ""), ("affinity", []),
    ("kernel", ""), ("boot_id", ""),
    ("allocated_blocks", None), ("executable", ""), ("page_size_bytes", 0),
])
def test_injected_preflight_incompatibility_fails(key, value):
    fixture = facts()
    fixture[key] = value
    with pytest.raises(h.HarnessError):
        h.inspect_preflight(fixture, source_bytes())


def test_allocator_environment_sanitization():
    dirty = {"PYTHONHASHSEED": "random", "PYTHONPATH": "bad", "PYTHONHOME": "bad",
             "PYTHONMALLOC": "debug", "PYTHONTRACEMALLOC": "1", "PYTHONDEVMODE": "1",
             "MALLOC_ARENA_MAX": "1", "LD_PRELOAD": "bad", "GLIBC_TUNABLES": "bad", "PATH": "/bin"}
    assert set(h.allocator_environment(dirty)) == {
        "PYTHONMALLOC", "PYTHONTRACEMALLOC", "PYTHONDEVMODE", "MALLOC_ARENA_MAX", "LD_PRELOAD", "GLIBC_TUNABLES"}
    assert h.sanitized_environment(dirty) == {"PATH": "/bin", "PYTHONHASHSEED": "0"}


def test_reset_requires_active_authorized_child_and_observed_drop(auth, monkeypatch):
    writes = []
    before, after = status_values(hwm=40 * h.MIB), status_values()
    args = {"child_role": "R-NULL", "task_reader": lambda: FUTURE_TASK,
            "read_status": forbidden, "write_reset": lambda: writes.append("5")}
    with pytest.raises(h.HarnessError, match="active child"):
        h.reset_high_water(auth, "M0b", **args)
    assert writes == []
    monkeypatch.setattr(h, "_CHILD_ROLE", "R-NULL")
    args["read_status"] = iter((before, after)).__next__
    assert h.reset_high_water(auth, "M0b", **args)["verified"]
    assert writes == ["5"]
    args["read_status"] = iter((before, before)).__next__
    with pytest.raises(h.HarnessError, match="not independently verified"):
        h.reset_high_water(auth, "M0b", **args)
    assert writes == ["5", "5"]  # Exactly one write per request, never a retry.
    with pytest.raises(h.HarnessError):
        h.reset_high_water(None, "M0b", **args)
    with pytest.raises(h.HarnessError):
        h.verify_reset(after, after)


@pytest.fixture
def synthetic_child(monkeypatch):
    """Exercise real child control flow with tiny payloads and fake instruments."""
    actual_gate = h.gate
    actual_builder = h.build_payload
    calls = {"payload": [], "probe": []}
    monkeypatch.setattr(h, "gate", lambda auth, stage: actual_gate(
        auth, stage, task_reader=lambda: FUTURE_TASK))
    monkeypatch.setattr(h, "sys", SimpleNamespace(
        version_info=(3, 12, 3), flags=SimpleNamespace(
            ignore_environment=0, hash_randomization=0, dev_mode=False),
        gettrace=lambda: None, getprofile=lambda: None, getsizeof=sys.getsizeof))
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setattr(h, "allocator_environment", lambda env: {})
    monkeypatch.setattr(h.tracemalloc, "is_tracing", lambda: False)
    monkeypatch.setattr(h.gc, "collect", lambda: 0)

    def tiny_builder(slot_count, capacity):
        calls["payload"].append((slot_count, capacity))
        return actual_builder(2, 2 if capacity == 256 else 4, unique_count=4)

    def tiny_probe(size):
        calls["probe"].append(size)
        return bytearray(8)

    def reset(auth, stage, *, child_role):
        assert h._CHILD_ROLE == child_role
        assert stage == h.role_stage(child_role)
        return h.verify_reset(status_values(hwm=40 * h.MIB), status_values())

    monkeypatch.setattr(h, "build_payload", tiny_builder)
    monkeypatch.setattr(h, "page_touched", tiny_probe)
    monkeypatch.setattr(h, "reset_high_water", reset)
    return calls


@pytest.mark.parametrize("role", ["R-NULL", "R-KNOWN", "R-BASE", "R-CAND"])
def test_rss_child_produces_serializable_validated_payload(auth, monkeypatch, synthetic_child, role):
    monkeypatch.setattr(h, "_CHILD_ROLE", role)
    retained = 32 * h.MIB if role == "R-NULL" else 48 * h.MIB
    released = snapshot(32 * h.MIB)
    released["status"]["VmHWM"] = retained
    readings = iter((snapshot(32 * h.MIB), snapshot(retained), released))
    monkeypatch.setattr(h, "proc_snapshot", lambda: next(readings))
    payload = json.loads(json.dumps(h.child_measurement(auth, role)))
    envelope = {"role": role, "outcome": None, "payload": payload}
    assert h.payloads([envelope], (role,)) == [payload]
    assert payload["mode"] == "RSS"
    assert payload["post_release"]["status"]["VmRSS"] == 32 * h.MIB
    assert synthetic_child["probe"] == ([8 * h.MIB, h.KNOWN_BYTES] if role == "R-KNOWN"
                                         else [8 * h.MIB])
    if role in h.M1_ROLES:
        capacity = 256 if role == "R-BASE" else 1024
        assert synthetic_child["payload"] == [(512, capacity)]
        assert payload["statistics"]["retained_entries"] == (4 if capacity == 256 else 8)
    else:
        assert synthetic_child["payload"] == []
        assert payload["statistics"] is None
        assert payload["null_window"] == ("no_intentional_payload" if role == "R-NULL" else None)


@pytest.mark.parametrize("role", ["R-NULL", "R-KNOWN", "R-BASE", "R-CAND"])
def test_rss_child_resets_exactly_once_before_window(auth, monkeypatch, synthetic_child, role):
    monkeypatch.setattr(h, "_CHILD_ROLE", role)
    events = []
    reset = h.reset_high_water

    def record_reset(*args, **kwargs):
        events.append("reset")
        return reset(*args, **kwargs)

    def record_snapshot():
        events.append("snapshot")
        return snapshot(32 * h.MIB)

    monkeypatch.setattr(h, "reset_high_water", record_reset)
    monkeypatch.setattr(h, "proc_snapshot", record_snapshot)
    h.child_measurement(auth, role)
    assert events == ["reset", "snapshot", "snapshot", "snapshot"]


@pytest.mark.parametrize("role", ["T-KNOWN", "T-BASE", "T-CAND"])
def test_traced_child_with_fake_tracer_and_tiny_payload(auth, monkeypatch, synthetic_child, role):
    monkeypatch.setattr(h, "_CHILD_ROLE", role)
    monkeypatch.setattr(h, "proc_snapshot", forbidden)
    readings = iter(((128, 128), (1128, 1256), (128, 1256)))
    events = []
    monkeypatch.setattr(h.tracemalloc, "start", lambda depth: events.append(("start", depth)))
    monkeypatch.setattr(h.tracemalloc, "reset_peak", lambda: events.append("reset_peak"))
    monkeypatch.setattr(h.tracemalloc, "get_traced_memory", lambda: next(readings))
    monkeypatch.setattr(h.tracemalloc, "stop", lambda: events.append("stop"))
    payload = json.loads(json.dumps(h.child_measurement(auth, role)))
    assert h.payloads([{"role": role, "outcome": None, "payload": payload}], (role,)) == [payload]
    assert events == [("start", 1), "reset_peak", "stop"]
    assert payload["traced_increment_bytes"] == 1000
    if role == "T-KNOWN":
        assert synthetic_child["probe"] == [h.KNOWN_BYTES]
        assert synthetic_child["payload"] == []
        assert payload["statistics"] is None
    else:
        capacity = 256 if role == "T-BASE" else 1024
        assert synthetic_child["payload"] == [(512, capacity)]
        assert synthetic_child["probe"] == []
        assert payload["statistics"]["retained_entries"] == (4 if capacity == 256 else 8)


@pytest.mark.parametrize("role,field,value,expected", [
    ("R-NULL", "VmHWM", 4 * h.MIB, "CALIBRATION_PASS"),
    ("R-NULL", "VmHWM", 4 * h.MIB + 1, "INVALID_EXPERIMENT"),
    ("R-KNOWN", "VmRSS", 12 * h.MIB, "CALIBRATION_PASS"),
    ("R-KNOWN", "VmRSS", 24 * h.MIB, "CALIBRATION_PASS"),
    ("R-KNOWN", "VmRSS", 12 * h.MIB - 1, "INVALID_EXPERIMENT"),
    ("R-KNOWN", "VmRSS", 24 * h.MIB + 1, "INVALID_EXPERIMENT"),
])
def test_rss_calibration_intervals(role, field, value, expected):
    results = fake_results(h.CALIBRATION_ROLES)
    child = next(item["payload"] for item in results if item["role"] == role)
    child["retained"]["status"][field] = child["before"]["status"][field] + value
    if field == "VmRSS":
        child["retained"]["status"]["VmHWM"] = child["retained"]["status"]["VmRSS"]
    child["post_release"]["status"]["VmHWM"] = child["retained"]["status"]["VmHWM"]
    outcome = h.calibration_outcome(results)
    assert outcome["outcome"] == expected and "error" not in outcome
    assert outcome["vmhwm_signed_differences"][role] == {
        "retained_minus_before_bytes": value, "post_release_minus_retained_bytes": 0}


@pytest.mark.parametrize("numerator,offset,expected", [
    (95, 0, "CALIBRATION_PASS"), (105, 0, "CALIBRATION_PASS"),
    (95, -1, "INVALID_EXPERIMENT"), (105, 1, "INVALID_EXPERIMENT"),
])
def test_traced_calibration_intervals(numerator, offset, expected):
    results = fake_results(h.CALIBRATION_ROLES)
    child = results[2]["payload"]
    # KNOWN_BYTES is not divisible by 100: use the inner integer at each edge.
    delta = ((numerator * h.KNOWN_BYTES + 99) // 100 if numerator == 95
             else numerator * h.KNOWN_BYTES // 100) + offset
    child.update(traced_increment_bytes=delta, traced_current_bytes=128 + delta,
                 traced_peak_bytes=256 + delta, post_release_traced_peak_bytes=256 + delta)
    assert h.calibration_outcome(results)["outcome"] == expected


def test_historical_r_known_vmhwm_decrease_is_diagnostic_only():
    # Owner-provided historical readings, not a reread or reclassification of M0b.
    results = fake_results(h.CALIBRATION_ROLES)
    known = results[1]["payload"]
    known["before"] = snapshot(24883200)
    known["retained"] = snapshot(41664512)
    known["retained"]["status"]["RssAnon"] = 30916608
    known["post_release"] = snapshot(24883200)
    known["post_release"]["status"]["VmHWM"] = 41549824
    original = copy.deepcopy(results)
    assert h.payloads(results, h.CALIBRATION_ROLES) == [item["payload"] for item in results]
    outcome = h.calibration_outcome(results)
    assert outcome["outcome"] == "CALIBRATION_PASS"
    assert outcome["known_rss_increase_bytes"] == 16781312
    assert outcome["vmhwm_signed_differences"]["R-KNOWN"] == {
        "retained_minus_before_bytes": 16781312,
        "post_release_minus_retained_bytes": -114688}
    assert results == original  # No corrected readings or clamping.


def test_monotonic_vmhwm_diagnostics_and_unchanged_intervals():
    results = fake_results(h.CALIBRATION_ROLES)
    results[1]["payload"]["post_release"]["status"]["VmHWM"] += 1024
    outcome = h.calibration_outcome(results)
    assert outcome["outcome"] == "CALIBRATION_PASS"
    assert outcome["vmhwm_signed_differences"] == {
        "interpretation": "informational_only",
        "R-NULL": {"retained_minus_before_bytes": 0, "post_release_minus_retained_bytes": 0},
        "R-KNOWN": {"retained_minus_before_bytes": 16 * h.MIB,
                    "post_release_minus_retained_bytes": 1024}}
    assert outcome["intervals"] == {"null_hwm_bytes": [0, 4 * h.MIB],
                                    "known_rss_bytes": [12 * h.MIB, 24 * h.MIB],
                                    "known_traced_percent": [95, 105]}


@pytest.mark.parametrize("role,expected", [("R-NULL", "INVALID_EXPERIMENT"),
                                           ("R-KNOWN", "CALIBRATION_PASS")])
def test_retained_vmhwm_below_before_preserves_signed_evidence_and_null_bound(role, expected):
    results = fake_results(h.CALIBRATION_ROLES)
    child = next(item["payload"] for item in results if item["role"] == role)
    child["before"]["status"]["VmHWM"] = child["retained"]["status"]["VmHWM"] + 1024
    assert h.payloads(results, h.CALIBRATION_ROLES)
    outcome = h.calibration_outcome(results)
    assert outcome["outcome"] == expected and "error" not in outcome
    assert outcome["vmhwm_signed_differences"][role]["retained_minus_before_bytes"] == -1024
    if role == "R-NULL":
        assert outcome["null_hwm_increase_bytes"] == -1024


@pytest.mark.parametrize("role", ["R-BASE", "R-CAND"])
def test_shared_payload_validation_accepts_m1_cross_snapshot_vmhwm_decreases(role):
    results = fake_results((role,))
    child = results[0]["payload"]
    child["before"]["status"]["VmHWM"] = child["retained"]["status"]["VmHWM"] + 1024
    child["post_release"]["status"]["VmHWM"] -= 1024
    assert h.payloads(results, (role,)) == [child]


@pytest.mark.parametrize("failure", ["unverified", "no_prior_high_water", "no_drop", "unequal_after"])
def test_calibration_still_rejects_unverified_reset(failure):
    results = fake_results(h.CALIBRATION_ROLES)
    reset = results[1]["payload"]["reset"]
    if failure == "unverified":
        reset["verified"] = False
    elif failure == "no_prior_high_water":
        reset["before"] = status_values()
    elif failure == "no_drop":
        reset["after"] = status_values(40 * h.MIB)
    else:
        reset["after"]["VmHWM"] += 1024
    if failure != "unverified":
        with pytest.raises(h.HarnessError):
            h.verify_reset(reset["before"], reset["after"])
    outcome = h.calibration_outcome(results)
    assert outcome["outcome"] == "INVALID_EXPERIMENT" and "error" in outcome
    assert "vmhwm_signed_differences" not in outcome


@pytest.mark.parametrize("point", ["before", "retained", "post_release"])
@pytest.mark.parametrize("instrument,field,value,error", [
    ("status", "VmSwap", -1, "Invalid instrument reading"),
    ("status", "VmRSS", True, "Invalid instrument reading"),
    ("status", "VmHWM", 1.0, "Invalid instrument reading"),
    ("status", "VmHWM", 0, "Invalid RSS relationships"),
    ("status", "RssAnon", 100 * h.MIB, "Invalid RSS relationships"),
    ("smaps_rollup", "Swap", -1, "Invalid instrument reading"),
    ("smaps_rollup", "AnonHugePages", 100 * h.MIB, "Invalid RSS relationships"),
    ("status", "VmSwap", None, "Incomplete instrument readings"),
    ("smaps_rollup", "Swap", None, "Incomplete instrument readings"),
    ("status", "unexpected", 0, "Incomplete instrument readings"),
    ("smaps_rollup", "unexpected", 0, "Incomplete instrument readings"),
])
def test_calibration_still_fails_closed_for_invalid_snapshots(point, instrument, field, value, error):
    results = fake_results(h.CALIBRATION_ROLES)
    readings = results[1]["payload"][point][instrument]
    if value is None:
        del readings[field]
    else:
        readings[field] = value
    outcome = h.calibration_outcome(results)
    assert outcome["outcome"] == "INVALID_EXPERIMENT"
    assert outcome["error"] == error
    assert "vmhwm_signed_differences" not in outcome


@pytest.mark.parametrize("failure", ["incomplete", "reordered", "wrong_role"])
def test_calibration_still_rejects_invalid_child_sequence(failure):
    results = fake_results(h.CALIBRATION_ROLES)
    if failure == "incomplete":
        results.pop()
    elif failure == "reordered":
        results.reverse()
    else:
        results[0]["payload"]["role"] = "R-KNOWN"
    outcome = h.calibration_outcome(results)
    assert outcome["outcome"] == "INVALID_EXPERIMENT" and "error" in outcome
    assert "vmhwm_signed_differences" not in outcome


def test_calibration_swap_gate_preserved_with_diagnostics():
    for instrument, field in (("status", "VmSwap"), ("smaps_rollup", "Swap")):
        results = fake_results(h.CALIBRATION_ROLES)
        results[1]["payload"]["post_release"][instrument][field] = 1024
        outcome = h.calibration_outcome(results)
        assert outcome["outcome"] == "INVALID_EXPERIMENT" and "error" not in outcome
        assert outcome["swap_observed"] is True
        assert "vmhwm_signed_differences" in outcome


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.pauses = []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.pauses.append(seconds)
        self.value += seconds


class FakeProcess:
    pid = 123456

    def __init__(self, exit_after=None, exit_code=0):
        self.returncode = None
        self.polls = 0
        self.exit_after = exit_after
        self.exit_code = exit_code

    def poll(self):
        self.polls += 1
        if self.returncode is None and self.exit_after is not None and self.polls >= self.exit_after:
            self.returncode = self.exit_code
        return self.returncode


def watchdog_case(*, samples=None, exit_after=4, exit_code=0,
                  output=b'{"synthetic":true}', diagnostic=b""):
    """A one-launch supervisor rig: every sample, exit and pause is synthetic."""
    samples = iter(samples if samples is not None else (
        h.ExitStatusUnavailable("synthetic missing memory fields"),))
    case = SimpleNamespace(clock=FakeClock(), process=FakeProcess(exit_after, exit_code),
                           reads=[], spawns=[], killed=[], descriptors=[])

    def read(pid):
        case.reads.append(pid)
        value = next(samples)  # Extra sampling fails, rather than retrying the instrument.
        if isinstance(value, BaseException):
            raise value
        return value

    def spawn(command, **kwargs):
        case.spawns.append(command)
        case.descriptors.extend(kwargs.get("pass_fds", ()))
        kwargs["stdout"].write(output)
        kwargs["stderr"].write(diagnostic)
        return case.process

    def kill(child):
        case.killed.append(child.pid)
        child.returncode = -9

    def run(timeout=2, **kwargs):
        return h.watch_child(["fake"], timeout, popen=spawn,
                             clock=kwargs.pop("clock", case.clock),
                             sleep=kwargs.pop("sleep", case.clock.sleep),
                             read_rss=read, kill=kill, **kwargs)

    case.run = run
    return case


def fake_watch(*, exit_after=None, sample=1, spawn_error=False, diagnostic=b""):
    calls, killed = [], []
    clock = FakeClock()
    process = FakeProcess(exit_after)

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        if spawn_error:
            raise OSError("synthetic spawn failure")
        kwargs["stdout"].write(b'{"synthetic":true}')
        kwargs["stderr"].write(diagnostic)
        return process

    def kill(child):
        killed.append(child.pid)
        child.returncode = -9

    result = h.watch_child(["never-executed"], 0.1, popen=spawn, clock=clock,
                           sleep=clock.sleep, read_rss=lambda pid: sample, kill=kill, environment={})
    return result, calls, killed


def test_watchdog_timeout_no_retry():
    result, calls, killed = fake_watch()
    assert result["outcome"] == "RESOURCE_LIMIT"
    assert len(calls) == 1 and killed == [123456]
    assert calls[0][1]["start_new_session"] is True
    assert calls[0][1]["env"] == {"PYTHONHASHSEED": "0"}


def test_watchdog_rss_limit_spawn_failure_and_success():
    result, calls, killed = fake_watch(sample=h.RSS_LIMIT + 1)
    assert result["outcome"] == "RESOURCE_LIMIT" and len(calls) == 1 and len(killed) == 1
    result, calls, killed = fake_watch(spawn_error=True)
    assert result["outcome"] == "INFRASTRUCTURE_FAILURE" and len(calls) == 1 and killed == []
    result, calls, killed = fake_watch(exit_after=2)
    assert result["outcome"] is None and result["payload"] == {"synthetic": True}
    assert len(calls) == 1 and killed == []
    assert result["rss_sampling_caveat"].startswith("Resource guard only")
    assert "VmHWM" not in result["payload"]
    assert "sampled_rss_max_bytes" in result
    assert set(result) == {"outcome", "payload", "elapsed_seconds", "sampled_rss_max_bytes",
                           "stderr", "stderr_bytes", "stderr_sha256", "stderr_truncated",
                           "rss_sampling_caveat"}


@pytest.mark.parametrize("text", ["", "Name: synthetic\nPid: 123456\nState: Z (zombie)\n"])
def test_watchdog_status_exit_pattern_is_distinct_from_strict_parser(text):
    with pytest.raises(h.ExitStatusUnavailable):
        h.watchdog_status_rss(text)
    with pytest.raises(h.HarnessError):
        h.parse_status(text)
    assert h.watchdog_status_rss(status_text()) == 32 * h.MIB


@pytest.mark.parametrize("text", [
    "VmRSS: 1 kB\n", status_text().replace("VmSwap: 0 kB\n", ""),
    status_text() + "VmRSS: 32768 kB\n",
    status_text().replace("32768 kB", "32768 MB"),
    status_text().replace("32768 kB", "unknown kB"),
    status_text().replace("32768 kB", "-1 kB"),
    status_text().replace("VmHWM: 40960", "VmHWM: 1"),
    status_text().replace("RssAnon: 16384", "RssAnon: 50000"),
    "VmRSS 1 kB\n", "  VmRSS: 1 kB\n",
])
@pytest.mark.parametrize("exit_after", [None, 2])
def test_malformed_watchdog_status_is_never_excused(text, exit_after):
    with pytest.raises(h.HarnessError) as caught:
        h.watchdog_status_rss(text)
    assert not isinstance(caught.value, h.ExitStatusUnavailable)
    case = watchdog_case(samples=[caught.value], exit_after=exit_after)
    result = case.run()
    assert result["outcome"] == "INFRASTRUCTURE_FAILURE"
    assert str(caught.value) in result["error"]
    assert case.clock.pauses == [] and len(case.reads) == 1
    assert case.killed == ([case.process.pid] if exit_after is None else [])


@pytest.mark.parametrize("sample", [True, -1, 1.0, None])
@pytest.mark.parametrize("exit_after", [None, 2])
def test_invalid_watchdog_values_fail_without_grace(sample, exit_after):
    case = watchdog_case(samples=[sample], exit_after=exit_after)
    result = case.run()
    assert result["outcome"] == "INFRASTRUCTURE_FAILURE"
    assert "Invalid watchdog RSS reading" in result["error"]
    assert case.clock.pauses == [] and len(case.reads) == 1


@pytest.mark.parametrize("error_type", [PermissionError, OSError, h.HarnessError])
@pytest.mark.parametrize("exit_after", [None, 2])
def test_genuine_instrument_errors_fail_even_if_exit_is_visible(error_type, exit_after):
    case = watchdog_case(samples=[error_type("synthetic instrument failure")], exit_after=exit_after)
    result = case.run()
    assert result["outcome"] == "INFRASTRUCTURE_FAILURE"
    assert "synthetic instrument failure" in result["error"]
    assert case.clock.pauses == []
    assert case.killed == ([case.process.pid] if exit_after is None else [])
    assert set(result) == {"outcome", "error", "stderr", "stderr_bytes",
                           "stderr_sha256", "stderr_truncated"}


@pytest.mark.parametrize("error_type", [h.ExitStatusUnavailable, FileNotFoundError, ProcessLookupError])
@pytest.mark.parametrize("exit_after", [2, 4, None])
def test_exit_race_confirmation_without_resampling(error_type, exit_after):
    case = watchdog_case(samples=[error_type("synthetic exit race")], exit_after=exit_after)
    result = case.run()
    assert len(case.spawns) == len(case.reads) == 1
    assert sum(case.clock.pauses) <= 0.5
    if exit_after is None:
        assert result["outcome"] == "INFRASTRUCTURE_FAILURE"
        assert "synthetic exit race" in result["error"]
        assert case.killed == [case.process.pid]
        assert sum(case.clock.pauses) == pytest.approx(0.5)
    else:
        assert result["outcome"] is None and result["payload"] == {"synthetic": True}
        assert result["sampled_rss_max_bytes"] == 0  # No successful samples; existing sentinel.
        assert case.killed == []
        assert bool(case.clock.pauses) == (exit_after != 2)


def test_exit_race_preserves_only_prior_real_sample_maximum():
    case = watchdog_case(samples=[5, 7, h.ExitStatusUnavailable("exit")], exit_after=6)
    result = case.run()
    assert result["outcome"] is None and result["sampled_rss_max_bytes"] == 7
    assert len(case.reads) == 3 and len(case.spawns) == 1 and case.killed == []


def test_exit_grace_is_bounded_with_frozen_clock():
    case = watchdog_case(exit_after=None)
    result = case.run(clock=lambda: 0)
    assert result["outcome"] == "INFRASTRUCTURE_FAILURE"
    assert len(case.clock.pauses) == h.EXIT_GRACE_POLLS
    assert sum(case.clock.pauses) <= 0.5 and len(case.reads) == 1
    assert case.killed == [case.process.pid]


def test_exit_grace_stops_at_child_deadline():
    case = watchdog_case(samples=[5, h.ExitStatusUnavailable("exit")], exit_after=None)
    result = case.run(timeout=0.08)
    assert result["outcome"] == "RESOURCE_LIMIT"
    assert result["error"] == "Child deadline exceeded"
    assert result["elapsed_seconds"] == pytest.approx(0.08)
    assert result["sampled_rss_max_bytes"] == 5
    assert case.killed == [case.process.pid] and len(case.reads) == 2


def test_child_exiting_beyond_deadline_is_still_resource_limited():
    case = watchdog_case(exit_after=3)

    def delayed_pause(seconds):
        case.clock.sleep(seconds + 0.1)  # Scheduling delay while the child exits.

    result = case.run(timeout=0.02, sleep=delayed_pause)
    assert result["outcome"] == "RESOURCE_LIMIT"
    assert result["error"] == "Child completed beyond deadline"
    assert case.killed == [] and len(case.reads) == 1


@pytest.mark.parametrize("output,expected", [
    (b'{"outcome":"INVALID_EXPERIMENT","error":"synthetic"}', "INVALID_EXPERIMENT"),
    (b"malformed", "INFRASTRUCTURE_FAILURE"),
])
def test_nonzero_exit_after_race_keeps_final_exit_validation(output, expected):
    diagnostic = b"synthetic stderr\n" * 400
    case = watchdog_case(exit_code=1, output=output, diagnostic=diagnostic)
    result = case.run()
    assert result["outcome"] == expected and result["returncode"] == 1
    assert result["stderr"] == diagnostic[:h.STDERR_PREVIEW_BYTES].decode()
    assert result["stderr_bytes"] == len(diagnostic)
    assert result["stderr_sha256"] == h.sha256(diagnostic)
    assert case.killed == [] and len(case.reads) == len(case.spawns) == 1


def test_exit_race_keeps_bounded_nonzero_error_text():
    output = json.dumps({"outcome": "INVALID_EXPERIMENT", "error": "x" * 8192}).encode()
    case = watchdog_case(exit_code=1, output=output)
    result = case.run()
    assert result["outcome"] == "INVALID_EXPERIMENT" and result["returncode"] == 1
    assert result["error"] == "x" * h.STDERR_PREVIEW_BYTES


def test_exit_race_still_validates_successful_child_json():
    case = watchdog_case(output=b"malformed")
    result = case.run()
    assert result["outcome"] == "INFRASTRUCTURE_FAILURE"
    assert result["error"] == "Malformed child IPC" and case.killed == []


def test_exit_race_keeps_final_ipc_ceiling(monkeypatch):
    monkeypatch.setattr(h, "REPORT_LIMIT", 128)
    case = watchdog_case(output=b"x" * 129)
    result = case.run()
    assert result["outcome"] == "RESOURCE_LIMIT"
    assert result["error"] == "Child IPC ceiling exceeded"
    assert case.killed == [] and len(case.reads) == len(case.spawns) == 1


def test_resource_limit_from_reader_is_preserved():
    case = watchdog_case(samples=[h.HarnessError("synthetic limit", "RESOURCE_LIMIT")], exit_after=None)
    result = case.run()
    assert result["outcome"] == "RESOURCE_LIMIT" and result["error"] == "synthetic limit"
    assert case.clock.pauses == [] and case.killed == [case.process.pid]


def test_interrupted_grace_cleans_up_and_reraises():
    case = watchdog_case(exit_after=None)

    def interrupt(seconds):
        raise KeyboardInterrupt("synthetic interrupt")

    with pytest.raises(KeyboardInterrupt, match="synthetic interrupt"):
        case.run(sleep=interrupt, permit={"synthetic": True})
    assert case.killed == [case.process.pid] and len(case.reads) == len(case.spawns) == 1
    descriptor, = case.descriptors
    with pytest.raises(OSError):
        h.os.fstat(descriptor)


@pytest.mark.parametrize("exit_after", [1, 4, None])
def test_permit_descriptors_close_on_success_race_and_live_failure(exit_after):
    case = watchdog_case(exit_after=exit_after)
    result = case.run(permit={"synthetic": True})
    assert result["outcome"] == ("INFRASTRUCTURE_FAILURE" if exit_after is None else None)
    descriptor, = case.descriptors
    with pytest.raises(OSError):
        h.os.fstat(descriptor)
    assert len(case.spawns) == 1


@pytest.mark.parametrize("missing", [False, True])
def test_kill_child_process_group_and_reap_are_preserved(monkeypatch, missing):
    calls = []

    def killpg(pid, sig):
        calls.append((pid, sig))
        if missing:
            raise ProcessLookupError("synthetic already exited")

    waits = []
    process = SimpleNamespace(pid=123456, wait=lambda **kwargs: waits.append(kwargs))
    monkeypatch.setattr(h.os, "killpg", killpg)
    h.kill_child(process)
    assert calls == [(process.pid, h.signal.SIGKILL)] and waits == [{"timeout": 5}]


def test_noisy_child_stderr_is_bounded_hashed_and_reportable(auth, tmp_path):
    diagnostic = b"synthetic stderr\n" * 4096
    result, calls, killed = fake_watch(exit_after=2, diagnostic=diagnostic)
    assert result["outcome"] is None and len(calls) == 1 and killed == []
    assert result["stderr"] == diagnostic[:h.STDERR_PREVIEW_BYTES].decode()
    assert result["stderr_bytes"] == len(diagnostic)
    assert result["stderr_sha256"] == h.sha256(diagnostic)
    assert result["stderr_truncated"] is True
    report = fake_report(auth)
    # All nine calibration/M1 children may be noisy; their previews remain small.
    report["diagnostic_children"] = [result] * 9
    h.write_report(report, "noisy.json", root=tmp_path)
    assert (tmp_path / "noisy.json").stat().st_size < h.REPORT_LIMIT


def test_stderr_evidence_survives_ipc_ceiling_failure(monkeypatch):
    monkeypatch.setattr(h, "REPORT_LIMIT", 128)
    monkeypatch.setattr(h, "STDERR_PREVIEW_BYTES", 32)
    diagnostic = b"x" * 256
    result, calls, killed = fake_watch(diagnostic=diagnostic)
    assert result["outcome"] == "RESOURCE_LIMIT"
    assert len(calls) == 1 and killed == [123456]
    assert result["stderr"] == "x" * 32
    assert result["stderr_bytes"] == 256
    assert result["stderr_sha256"] == h.sha256(diagnostic)
    assert result["stderr_truncated"] is True


def test_failed_child_retains_bounded_stderr():
    diagnostic = b"failed child\n" * 1024
    process = FakeProcess()
    process.returncode = 1

    def spawn(command, **kwargs):
        kwargs["stdout"].write(b'{"outcome":"INVALID_EXPERIMENT","error":"synthetic"}')
        kwargs["stderr"].write(diagnostic)
        return process

    result = h.watch_child(["fake"], 1, popen=spawn, clock=lambda: 0,
                           read_rss=forbidden, kill=forbidden)
    assert result["outcome"] == "INVALID_EXPERIMENT"
    assert result["stderr"] == diagnostic[:h.STDERR_PREVIEW_BYTES].decode()
    assert result["stderr_bytes"] == len(diagnostic)
    assert result["stderr_sha256"] == h.sha256(diagnostic)


@pytest.mark.parametrize("error_type", [OSError, h.HarnessError])
def test_watchdog_proc_failure_is_infrastructure_failure(error_type):
    process = FakeProcess()
    killed = []

    def read(pid):
        raise error_type("synthetic proc failure")

    def kill(child):
        killed.append(child.pid)
        child.returncode = -9

    result = h.watch_child(["fake"], 1, popen=lambda *args, **kwargs: process,
                           clock=lambda: 0, read_rss=read, kill=kill)
    assert result["outcome"] == "INFRASTRUCTURE_FAILURE" and killed == [process.pid]


def test_internal_children_require_parent_and_calibration_evidence(auth):
    permit = {"protocol": "r2e-child-v1", "role": "R-CAND", "task_sha256": auth.task_sha256,
              "parent_pid": 123, "preflight_sha256": "1" * 64, "calibration_sha256": "2" * 64}
    h.verify_child_permit(auth, "R-CAND", permit, 123)
    with pytest.raises(h.HarnessError, match="supervised-child"):
        h.verify_child_permit(auth, "R-CAND", permit, 124)
    missing = {**permit, "calibration_sha256": None}
    with pytest.raises(h.HarnessError, match="calibration_sha256"):
        h.verify_child_permit(auth, "R-CAND", missing, 123)
    with pytest.raises(h.HarnessError, match="inherited parent permit"):
        h.read_child_permit(auth, "R-CAND", None)
    with pytest.raises(h.HarnessError, match="calibration_sha256"):
        h.run_sequence(auth, ("R-CAND",), 120, 850, launcher=forbidden, clock=lambda: 0,
                       evidence={"preflight_sha256": "1" * 64})


def test_read_child_permit_from_real_pipe(auth):
    permit = {"protocol": "r2e-child-v1", "role": "R-CAND", "task_sha256": auth.task_sha256,
              "parent_pid": h.os.getppid(), "preflight_sha256": "1" * 64,
              "calibration_sha256": "2" * 64}
    read_end, write_end = h.os.pipe()
    # Only a tiny FIFO handoff; no child process is started.
    with h.os.fdopen(write_end, "wb") as stream:
        stream.write(h.canonical_bytes(permit))
    assert h.read_child_permit(auth, "R-CAND", read_end) == permit
    with pytest.raises(OSError):
        h.os.fstat(read_end)  # The reader owns and closes its inherited descriptor.


def test_inherited_pipe_handoff_with_fake_process(auth):
    permit = {"protocol": "r2e-child-v1", "role": "M0a", "task_sha256": auth.task_sha256,
              "parent_pid": h.os.getpid(), "preflight_sha256": None, "calibration_sha256": None}
    received = []

    def spawn(command, **kwargs):
        descriptor = int(command[command.index("--parent-permit-fd") + 1])
        assert kwargs["pass_fds"] == (descriptor,)
        with h.os.fdopen(h.os.dup(descriptor), "rb") as stream:
            received.append(json.loads(stream.read()))
        kwargs["stdout"].write(b'{"synthetic":true}')
        return FakeProcess(exit_after=1)

    result = h.watch_child(["fake"], 10, permit=permit, popen=spawn, clock=lambda: 0,
                           read_rss=forbidden, kill=forbidden)
    assert result["outcome"] is None and received == [permit]


def test_sequence_order_limits_and_stop_on_first_failure(auth):
    calls = []
    evidence = {"preflight_sha256": "1" * 64, "calibration_sha256": "2" * 64}

    def launch(command, timeout, *, permit):
        role = command[command.index("--child") + 1]
        h.verify_child_permit(auth, role, permit, h.os.getpid())
        calls.append((role, timeout))
        return {"outcome": None, "payload": fake_payload(role)}

    results = h.run_sequence(auth, h.M1_ROLES, 120, 850, launcher=launch, clock=lambda: 0, evidence=evidence)
    assert [role for role, _ in calls] == list(h.M1_ROLES)
    assert all(seconds == 120 for _, seconds in calls)
    assert len(results) == 6
    calls.clear()

    def fail(command, timeout, *, permit):
        calls.append(timeout)
        return {"outcome": "RESOURCE_LIMIT", "error": "synthetic limit"}

    results = h.run_sequence(auth, h.M1_ROLES, 120, 10, launcher=fail, clock=lambda: 0, evidence=evidence)
    assert calls == [10] and len(results) == 1
    assert h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})["outcome"] == "RESOURCE_LIMIT"
    calls.clear()
    results = h.run_sequence(auth, h.M1_ROLES, 120, 0, launcher=fail, clock=lambda: 0)
    assert calls == [] and results[0]["outcome"] == "RESOURCE_LIMIT"


def test_m1_signed_deltas_occupancy_and_fixed_claims(auth):
    calibration = h.calibration_outcome(fake_results(h.CALIBRATION_ROLES))
    results = fake_results(h.M1_ROLES)
    outcome = h.m1_outcome(results, calibration)
    assert outcome["outcome"] == "M1_ALLOCATOR_CALIBRATED"
    comparison = outcome["traced"]["traced_current_bytes"]
    assert comparison["candidate_minus_baseline_bytes"] == 1000
    assert comparison["incremental_bytes_per_entry"] == 1000 / 393216
    assert len(outcome["rss_pairwise_A1_B1_A2_B2"]) == 2
    assert outcome["rss_means"]["VmRSS"]["candidate_minus_baseline_bytes"] == 16 * h.MIB
    # Reduce the candidate without changing any occupancy metadata.
    results[1]["payload"].update(traced_current_bytes=1000, traced_increment_bytes=872)
    outcome = h.m1_outcome(results, calibration)
    assert outcome["outcome"] == "INCONCLUSIVE"
    assert outcome["traced"]["traced_current_bytes"]["candidate_minus_baseline_bytes"] == -128
    assert h.signed_comparison(2, 1)["incremental_bytes_per_entry"] == -1 / 393216
    report = fake_report(auth)
    assert report["production_chronological_peak"] == "NOT_OBSERVED"
    assert report["production_memory_qualification"] == "INCONCLUSIVE"
    assert report["projection_717_slots"]["outcome"] == "NOT_EVALUABLE"


def test_distinct_rss_replicates_preserve_pairing_and_window_shape():
    results = fake_results(h.M1_ROLES)
    # A1, B1, B2, A2 have different initial, retained and released readings.
    readings = ((30, 50, 32), (31, 71, 34), (33, 93, 36), (32, 62, 33))
    for item, (before, retained, released) in zip(results[2:], readings):
        child = item["payload"]
        child["before"] = snapshot(before * h.MIB)
        child["retained"] = snapshot(retained * h.MIB)
        child["post_release"] = snapshot(released * h.MIB)
        child["post_release"]["status"]["VmHWM"] = retained * h.MIB
    outcome = h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "M1_ALLOCATOR_CALIBRATED"
    for table, expected in (("rss_pairwise_A1_B1_A2_B2", (21, 31)),
                            ("smaps_pairwise_A1_B1_A2_B2", (21, 31)),
                            ("post_release_rss_pairwise_A1_B1_A2_B2", (2, 3)),
                            ("rss_window_increment_pairwise", (20, 30))):
        metric = "Rss" if table.startswith("smaps") else "VmRSS"
        comparisons = outcome[table]
        assert [entry[metric]["candidate_minus_baseline_bytes"] for entry in comparisons] == [
            value * h.MIB for value in expected]
    assert outcome["rss_means"]["VmRSS"] == h.signed_comparison(56 * h.MIB, 82 * h.MIB)
    assert outcome["smaps_means"]["Rss"] == h.signed_comparison(56 * h.MIB, 82 * h.MIB)
    assert outcome["post_release_rss_means"]["VmRSS"] == h.signed_comparison(32.5 * h.MIB, 35 * h.MIB)


@pytest.mark.parametrize("point", ["before", "retained", "post_release"])
@pytest.mark.parametrize("side,delta", [(2, -2 * h.MIB), (3, 2 * h.MIB)])
def test_huge_page_differences_are_signed_and_inconclusive(point, side, delta):
    results = fake_results(h.M1_ROLES)
    results[side]["payload"][point]["smaps_rollup"]["AnonHugePages"] = 2 * h.MIB
    outcome = h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "INCONCLUSIVE"
    difference, = outcome["huge_page_difference_points"]
    assert difference["pair"] == 1 and difference["point"] == point
    assert difference["candidate_minus_baseline_bytes"] == delta
    if point == "retained":
        assert outcome["smaps_pairwise_A1_B1_A2_B2"][0]["AnonHugePages"][
            "candidate_minus_baseline_bytes"] == delta


def test_negative_post_release_rss_and_smaps_deltas_are_not_clamped():
    results = fake_results(h.M1_ROLES)
    child = results[3]["payload"]
    child["post_release"]["status"]["VmRSS"] -= 1024
    child["retained"]["smaps_rollup"]["Rss"] = results[2]["payload"]["retained"][
        "smaps_rollup"]["Rss"] - 2048
    outcome = h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "INCONCLUSIVE"
    assert outcome["post_release_rss_pairwise_A1_B1_A2_B2"][0]["VmRSS"][
        "candidate_minus_baseline_bytes"] == -1024
    assert outcome["smaps_pairwise_A1_B1_A2_B2"][0]["Rss"]["candidate_minus_baseline_bytes"] == -2048


def test_isolated_negative_post_release_rss_is_diagnostic_only():
    results = fake_results(h.M1_ROLES)
    assert h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})["outcome"] == "M1_ALLOCATOR_CALIBRATED"
    results[3]["payload"]["post_release"]["status"]["VmRSS"] -= 1024
    outcome = h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "M1_ALLOCATOR_CALIBRATED"
    assert outcome["unexplained_negative_metrics"] == ["VmRSS", "VmRSS"]
    assert outcome["huge_page_difference_points"] == [] and outcome["swap_observed"] is False
    assert outcome["post_release_rss_pairwise_A1_B1_A2_B2"][0]["VmRSS"][
        "candidate_minus_baseline_bytes"] == -1024
    assert outcome["post_release_rss_means"]["VmRSS"]["candidate_minus_baseline_bytes"] == -512
    assert outcome["acceptance_blocking_negative_metrics"] == []
    assert [(entry["comparison"], entry["candidate_minus_baseline_bytes"])
            for entry in outcome["post_release_negative_diagnostics"]] == [("pair_1", -1024), ("mean", -512)]


def test_historical_r2fb_prospective_classification_preserves_release_evidence():
    results = historical_r2fb_results()
    original = copy.deepcopy(results)
    outcome = h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "M1_ALLOCATOR_CALIBRATED"
    assert outcome["acceptance_blocking_negative_metrics"] == []
    assert outcome["unexplained_negative_metrics"] == ["VmRSS", "VmRSS", "VmRSS"]
    assert outcome["swap_observed"] is False and outcome["huge_page_difference_points"] == []
    comparisons = [
        {"baseline_bytes": 31391744, "candidate_bytes": 29679616,
         "candidate_minus_baseline_bytes": -1712128, "incremental_bytes_per_entry": -4.354166666666667},
        {"baseline_bytes": 31690752, "candidate_bytes": 29442048,
         "candidate_minus_baseline_bytes": -2248704, "incremental_bytes_per_entry": -5.71875},
        {"baseline_bytes": 31541248.0, "candidate_bytes": 29560832.0,
         "candidate_minus_baseline_bytes": -1980416.0, "incremental_bytes_per_entry": -5.036458333333333}]
    assert outcome["post_release_rss_pairwise_A1_B1_A2_B2"] == [
        {"VmRSS": comparison} for comparison in comparisons[:2]]
    assert outcome["post_release_rss_means"] == {"VmRSS": comparisons[2]}
    assert outcome["post_release_negative_diagnostics"] == [
        {"source": source, "comparison": label, "metric": "VmRSS", **comparison}
        for source, label, comparison in zip(
            ("post_release_rss_pairwise_A1_B1_A2_B2", "post_release_rss_pairwise_A1_B1_A2_B2",
             "post_release_rss_means"), ("pair_1", "pair_2", "mean"), comparisons)]
    for entry, expected_type in zip(outcome["post_release_negative_diagnostics"], (int, int, float)):
        for key in ("baseline_bytes", "candidate_bytes", "candidate_minus_baseline_bytes"):
            assert type(entry[key]) is expected_type
    assert results == original
    assert h.canonical_bytes(outcome) == h.canonical_bytes(
        h.m1_outcome(copy.deepcopy(results), {"outcome": "CALIBRATION_PASS"}))


@pytest.mark.parametrize("release_increment", [0, 1024])
def test_nonnegative_release_comparisons_have_no_negative_labels(release_increment):
    results = fake_results(h.M1_ROLES)
    for index in (3, 4):
        results[index]["payload"]["post_release"]["status"]["VmRSS"] += release_increment
    outcome = h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "M1_ALLOCATOR_CALIBRATED"
    assert outcome["acceptance_blocking_negative_metrics"] == []
    assert outcome["post_release_negative_diagnostics"] == []
    assert outcome["unexplained_negative_metrics"] == []


@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize("metric", ["traced_current_bytes", "traced_peak_bytes", "traced_increment_bytes"])
def test_each_negative_traced_comparison_still_blocks(metric, historical):
    results = historical_r2fb_results() if historical else fake_results(h.M1_ROLES)
    base, cand = [item["payload"] for item in results[:2]]
    # Isolate one negative traced comparison, keeping the traced invariants valid.
    base.update(traced_baseline_bytes=100, traced_current_bytes=1000,
                traced_increment_bytes=900, traced_peak_bytes=2000,
                post_release_traced_current_bytes=0, post_release_traced_peak_bytes=2000)
    cand.update(traced_baseline_bytes=100, traced_current_bytes=1100,
                traced_increment_bytes=1000, traced_peak_bytes=2100,
                post_release_traced_current_bytes=0, post_release_traced_peak_bytes=2100)
    if metric == "traced_current_bytes":
        cand.update(traced_baseline_bytes=0, traced_current_bytes=999, traced_increment_bytes=999)
    elif metric == "traced_peak_bytes":
        cand["traced_peak_bytes"] = 1999
    else:
        cand.update(traced_baseline_bytes=201, traced_increment_bytes=899)
    outcome = h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "INCONCLUSIVE"
    assert outcome["acceptance_blocking_negative_metrics"] == [{
        "source": "traced", "comparison": "candidate_minus_baseline", "metric": metric,
        "baseline_bytes": base[metric], "candidate_bytes": cand[metric],
        "candidate_minus_baseline_bytes": -1, "incremental_bytes_per_entry": -1 / 393216}]
    assert len(outcome["post_release_negative_diagnostics"]) == (3 if historical else 0)


@pytest.mark.parametrize("instrument,metric,source,mean_source", [
    ("status", "VmRSS", "rss_pairwise_A1_B1_A2_B2", "rss_means"),
    ("status", "VmHWM", "rss_pairwise_A1_B1_A2_B2", "rss_means"),
    ("status", "RssAnon", "rss_pairwise_A1_B1_A2_B2", "rss_means"),
    ("smaps_rollup", "Rss", "smaps_pairwise_A1_B1_A2_B2", "smaps_means")])
@pytest.mark.parametrize("pair_numbers", [(1,), (2,), (1, 2)])
def test_negative_retained_pairs_and_means_still_block(instrument, metric, source, mean_source, pair_numbers):
    results = historical_r2fb_results()
    for pair_number in pair_numbers:
        base_index, cand_index = (2, 3) if pair_number == 1 else (5, 4)
        base, cand = [results[index]["payload"]["retained"][instrument]
                      for index in (base_index, cand_index)]
        cand[metric] = base[metric] - 1024
        if metric == "VmRSS":
            cand["RssAnon"] = min(cand["RssAnon"], cand["VmRSS"])
        elif metric == "VmHWM":
            cand["VmRSS"] = min(cand["VmRSS"], cand["VmHWM"])
            cand["RssAnon"] = min(cand["RssAnon"], cand["VmRSS"])
    outcome = h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "INCONCLUSIVE"
    entries = outcome["acceptance_blocking_negative_metrics"]
    labels = [entry["comparison"] for entry in entries if entry["source"] == source and entry["metric"] == metric]
    assert labels == [f"pair_{number}" for number in pair_numbers]
    for entry in entries:
        if entry["source"] == source and entry["metric"] == metric:
            assert type(entry["candidate_minus_baseline_bytes"]) is int
            assert entry["candidate_minus_baseline_bytes"] == -1024
    mean_entries = [entry for entry in entries if entry["source"] == mean_source and entry["metric"] == metric]
    if len(pair_numbers) == 2:
        entry, = mean_entries
        assert entry == {"source": mean_source, "comparison": "mean", "metric": metric,
                         **outcome[mean_source][metric]}
        assert type(entry["candidate_minus_baseline_bytes"]) is float
        assert entry["candidate_minus_baseline_bytes"] == -1024.0
    else:
        assert mean_entries == []
    assert len(outcome["post_release_negative_diagnostics"]) == 3


@pytest.mark.parametrize("base_index,cand_index,label", [(2, 3, "pair_1"), (5, 4, "pair_2")])
def test_negative_before_normalized_window_still_blocks(base_index, cand_index, label):
    results = historical_r2fb_results()
    base, cand = [results[index]["payload"] for index in (base_index, cand_index)]
    baseline_window = base["retained"]["status"]["VmRSS"] - base["before"]["status"]["VmRSS"]
    cand["before"]["status"]["VmRSS"] = cand["retained"]["status"]["VmRSS"] - baseline_window + 1024
    cand["before"]["status"]["VmHWM"] = cand["before"]["status"]["VmRSS"]
    outcome = h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "INCONCLUSIVE"
    entry, = [entry for entry in outcome["acceptance_blocking_negative_metrics"]
              if entry["source"] == "rss_window_increment_pairwise" and entry["metric"] == "VmRSS"]
    assert entry == {"source": "rss_window_increment_pairwise", "comparison": label, "metric": "VmRSS",
                     "baseline_bytes": baseline_window, "candidate_bytes": baseline_window - 1024,
                     "candidate_minus_baseline_bytes": -1024, "incremental_bytes_per_entry": -1024 / 393216}
    assert all(comparison["candidate_minus_baseline_bytes"] >= 0
               for table in outcome["rss_pairwise_A1_B1_A2_B2"] for comparison in table.values())


@pytest.mark.parametrize("point", ["before", "retained", "post_release"])
@pytest.mark.parametrize("index", [2, 3, 4, 5])
@pytest.mark.parametrize("instrument,metric", [("status", "VmSwap"), ("smaps_rollup", "Swap")])
def test_swap_independently_blocks_with_release_negatives(point, index, instrument, metric):
    results = historical_r2fb_results()
    results[index]["payload"][point][instrument][metric] = 1024
    outcome = h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "INCONCLUSIVE" and outcome["swap_observed"] is True
    assert len(outcome["post_release_negative_diagnostics"]) == 3
    if point == "post_release" or (point == "before" and instrument == "smaps_rollup"):
        assert outcome["acceptance_blocking_negative_metrics"] == []
    if point == "retained" and index in (2, 5):
        source = "rss_pairwise_A1_B1_A2_B2" if instrument == "status" else "smaps_pairwise_A1_B1_A2_B2"
        mean_source = "rss_means" if instrument == "status" else "smaps_means"
        entries = [entry for entry in outcome["acceptance_blocking_negative_metrics"]
                   if entry["metric"] == metric and entry["source"] in (source, mean_source)]
        assert [(entry["source"], entry["comparison"], entry["candidate_minus_baseline_bytes"])
                for entry in entries] == [(source, "pair_1" if index == 2 else "pair_2", -1024),
                                          (mean_source, "mean", -512.0)]


@pytest.mark.parametrize("point", ["before", "retained", "post_release"])
@pytest.mark.parametrize("index,pair,delta", [(2, 1, -1024), (3, 1, 1024), (4, 2, 1024), (5, 2, -1024)])
def test_huge_pages_independently_block_with_release_negatives(point, index, pair, delta):
    results = historical_r2fb_results()
    results[index]["payload"][point]["smaps_rollup"]["AnonHugePages"] = 1024
    outcome = h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "INCONCLUSIVE"
    difference, = outcome["huge_page_difference_points"]
    assert difference == {"pair": pair, "point": point,
                          "baseline_bytes": 1024 if delta < 0 else 0,
                          "candidate_bytes": 1024 if delta > 0 else 0,
                          "candidate_minus_baseline_bytes": delta,
                          "incremental_bytes_per_entry": delta / 393216}
    assert len(outcome["post_release_negative_diagnostics"]) == 3
    if point != "retained":
        assert outcome["acceptance_blocking_negative_metrics"] == []
    elif delta < 0:
        entries = [entry for entry in outcome["acceptance_blocking_negative_metrics"]
                   if entry["metric"] == "AnonHugePages"]
        assert [(entry["source"], entry["comparison"], entry["candidate_minus_baseline_bytes"])
                for entry in entries] == [("smaps_pairwise_A1_B1_A2_B2", f"pair_{pair}", -1024),
                                          ("smaps_means", "mean", -512.0)]


def assert_invalid_m1_without_diagnostics(results, error, calibration=None):
    outcome = h.m1_outcome(results, calibration or {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "INVALID_EXPERIMENT"
    assert outcome["error"] == error
    assert "acceptance_blocking_negative_metrics" not in outcome
    assert "post_release_negative_diagnostics" not in outcome


@pytest.mark.parametrize("failure,error", [
    ("unverified", "Missing reset verification"),
    ("no_prior_high_water", "Reset lacks an independently observed prior high water"),
    ("no_drop", "High-water reset was not independently verified"),
    ("unequal_after", "High-water reset was not independently verified")])
def test_m1_invalid_reset_fails_closed_with_release_negatives(failure, error):
    results = historical_r2fb_results()
    reset = results[3]["payload"]["reset"]
    if failure == "unverified":
        reset["verified"] = False
    elif failure == "no_prior_high_water":
        reset["before"] = dict(reset["after"])
    elif failure == "no_drop":
        reset["after"]["VmHWM"] = reset["before"]["VmHWM"]
    else:
        reset["after"]["VmHWM"] += 1024
    assert_invalid_m1_without_diagnostics(results, error)


@pytest.mark.parametrize("point", ["before", "retained", "post_release"])
@pytest.mark.parametrize("instrument,metric", [("status", "VmSwap"), ("smaps_rollup", "Swap")])
@pytest.mark.parametrize("value", [None, -1, True, 1.0, "malformed"])
def test_m1_invalid_proc_readings_fail_closed_with_release_negatives(point, instrument, metric, value):
    results = historical_r2fb_results()
    readings = results[3]["payload"][point][instrument]
    if value is None:
        del readings[metric]
    else:
        readings[metric] = value
    assert_invalid_m1_without_diagnostics(
        results, "Incomplete instrument readings" if value is None else "Invalid instrument reading")


@pytest.mark.parametrize("field,value", [("slot_count", 511), ("capacity_per_slot", 256),
                                         ("retained_entries", 1), ("occupancy", [1024] * 511),
                                         ("occupancy", [256] * 512)])
def test_m1_invalid_occupancy_still_fails_closed(field, value):
    results = historical_r2fb_results()
    results[3]["payload"]["statistics"][field] = value
    assert_invalid_m1_without_diagnostics(results, "Incorrect measured M1 occupancy")


@pytest.mark.parametrize("failure,error", [
    ("incomplete", "Incomplete or reordered child sequence"),
    ("reordered", "Incomplete or reordered child sequence"),
    ("wrong_role", "Wrong child result role"),
    ("mixed_modes", "Mixed measurement modes"),
    ("calibration", "M0b calibration must pass before M1")])
def test_m1_invalid_sequence_or_calibration_still_fails_closed(failure, error):
    results = historical_r2fb_results()
    calibration = {"outcome": "CALIBRATION_PASS"}
    if failure == "incomplete":
        results.pop()
    elif failure == "reordered":
        results[2], results[3] = results[3], results[2]
    elif failure == "wrong_role":
        results[3]["payload"]["role"] = "R-BASE"
    elif failure == "mixed_modes":
        results[3]["payload"]["mode"] = "TRACED"
    else:
        calibration["outcome"] = "INVALID_EXPERIMENT"
    assert_invalid_m1_without_diagnostics(results, error, calibration)


def test_negative_groups_preserve_legacy_traversal_labels_and_values():
    results = historical_r2fb_results()
    base, cand = [item["payload"] for item in results[:2]]
    cand.update(traced_current_bytes=base["traced_current_bytes"] - 1024,
                traced_increment_bytes=base["traced_increment_bytes"] - 1024,
                traced_peak_bytes=base["traced_peak_bytes"] - 1024)
    for base_index, cand_index in ((2, 3), (5, 4)):
        baseline, candidate = [results[index]["payload"] for index in (base_index, cand_index)]
        for metric in ("VmRSS", "VmHWM", "RssAnon"):
            candidate["retained"]["status"][metric] = baseline["retained"]["status"][metric] - 1024
        candidate["retained"]["smaps_rollup"]["Rss"] = baseline["retained"]["smaps_rollup"]["Rss"] - 1024
    outcome = h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})
    assert outcome["outcome"] == "INCONCLUSIVE"
    blocking = outcome["acceptance_blocking_negative_metrics"]
    released = outcome["post_release_negative_diagnostics"]
    expected_groups = [
        ("traced", "candidate_minus_baseline", ["traced_current_bytes", "traced_peak_bytes", "traced_increment_bytes"]),
        ("rss_pairwise_A1_B1_A2_B2", "pair_1", ["VmRSS", "VmHWM", "RssAnon"]),
        ("rss_pairwise_A1_B1_A2_B2", "pair_2", ["VmRSS", "VmHWM", "RssAnon"]),
        ("rss_means", "mean", ["VmRSS", "VmHWM", "RssAnon"]),
        ("rss_window_increment_pairwise", "pair_1", ["VmRSS", "VmHWM", "RssAnon"]),
        ("rss_window_increment_pairwise", "pair_2", ["VmRSS", "VmHWM", "RssAnon"]),
        ("smaps_pairwise_A1_B1_A2_B2", "pair_1", ["Rss"]),
        ("smaps_pairwise_A1_B1_A2_B2", "pair_2", ["Rss"]),
        ("smaps_means", "mean", ["Rss"])]
    assert [(entry["source"], entry["comparison"], entry["metric"]) for entry in blocking] == [
        (source, label, metric) for source, label, metrics in expected_groups for metric in metrics]
    legacy_tables = [outcome["traced"], *outcome["rss_pairwise_A1_B1_A2_B2"], outcome["rss_means"],
                     *outcome["rss_window_increment_pairwise"], *outcome["smaps_pairwise_A1_B1_A2_B2"],
                     outcome["smaps_means"], *outcome["post_release_rss_pairwise_A1_B1_A2_B2"],
                     outcome["post_release_rss_means"]]
    assert outcome["unexplained_negative_metrics"] == [
        metric for table in legacy_tables for metric, comparison in table.items()
        if comparison["candidate_minus_baseline_bytes"] < 0]
    assert outcome["unexplained_negative_metrics"] == [entry["metric"] for entry in blocking + released]
    labels = [(entry["source"], entry["comparison"], entry["metric"]) for entry in blocking + released]
    assert len(labels) == len(set(labels))
    for entry in blocking + released:
        table = outcome[entry["source"]]
        if entry["comparison"].startswith("pair_"):
            table = table[int(entry["comparison"][-1]) - 1]
        comparison = table[entry["metric"]]
        assert entry == {"source": entry["source"], "comparison": entry["comparison"],
                         "metric": entry["metric"], **comparison}
        for key, value in comparison.items():
            assert type(entry[key]) is type(value)
    assert h.canonical_bytes(outcome) == h.canonical_bytes(
        h.m1_outcome(copy.deepcopy(results), {"outcome": "CALIBRATION_PASS"}))


def test_prospective_m1_diagnostics_round_trip_and_integrity(auth, tmp_path):
    report = fake_report(auth, stage="M1")
    report["m1"] = h.m1_outcome(historical_r2fb_results(), report["calibration"])
    report["outcome"] = report["m1"]["outcome"]
    result = h.write_report(report, "prospective.json", root=tmp_path)
    raw = (tmp_path / "prospective.json").read_bytes()
    assert result["sha256"] == h.sha256(raw)
    assert (tmp_path / "prospective.json.sha256").read_text() == result["sha256"] + "  prospective.json\n"
    loaded = h.read_report(tmp_path / "prospective.json", result["sha256"], root=tmp_path)
    assert loaded == report
    assert loaded["schema"] == "rb-post3d-08p2e2-r2e-memory-v1"
    assert loaded["outcome"] == "M1_ALLOCATOR_CALIBRATED"
    assert len(loaded["m1"]["post_release_negative_diagnostics"]) == 3
    for entry, expected_type, delta in zip(loaded["m1"]["post_release_negative_diagnostics"],
                                           (int, int, float), (-1712128, -2248704, -1980416.0)):
        assert type(entry["candidate_minus_baseline_bytes"]) is expected_type
        assert entry["candidate_minus_baseline_bytes"] == delta
    (tmp_path / "prospective.json").write_bytes(raw + b"\n")
    with pytest.raises(h.HarnessError, match="SHA-256"):
        h.read_report(tmp_path / "prospective.json", result["sha256"], root=tmp_path)


def test_forbidden_production_claims_and_cross_process_peak_instrument_absent(auth):
    report = fake_report(auth)
    report["m1"] = h.m1_outcome(fake_results(h.M1_ROLES), report["calibration"])
    for text in (h.Path(h.__file__).read_text(), json.dumps(report)):
        assert "MEMORY_SCREEN_MET" not in text
        assert "ru_maxrss" not in text


def test_m1_rejects_modes_wrong_occupancy_and_failed_calibration():
    for field, value in (("slot_count", 511), ("retained_entries", 1), ("occupancy", [256])):
        results = fake_results(h.M1_ROLES)
        results[0]["payload"]["statistics"][field] = value
        assert h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})["outcome"] == "INVALID_EXPERIMENT"
    results = fake_results(h.M1_ROLES)
    results[0]["payload"]["before"] = snapshot(h.MIB)
    assert h.m1_outcome(results, {"outcome": "CALIBRATION_PASS"})["outcome"] == "INVALID_EXPERIMENT"
    assert h.m1_outcome([], {"outcome": "INVALID_EXPERIMENT"})["outcome"] == "INVALID_EXPERIMENT"


def test_combined_stage_uses_only_fake_children_in_exact_order(auth):
    calls = []

    def launch(command, timeout, *, permit):
        role = command[command.index("--child") + 1]
        h.verify_child_permit(auth, role, permit, h.os.getpid())
        calls.append((role, timeout))
        return {"outcome": None, "payload": fake_payload(role)}

    report = h.run_stage(auth, "all", launcher=launch, clock=lambda: 0, task_reader=lambda: FUTURE_TASK)
    assert report["outcome"] == "M1_ALLOCATOR_CALIBRATED"
    assert [role for role, _ in calls] == ["M0a", *h.CALIBRATION_ROLES, *h.M1_ROLES]
    assert [seconds for _, seconds in calls] == [10, 40, 40, 40, 120, 120, 120, 120, 120, 120]
    assert report["calibration_payload_sha256"] == h.sha256(h.canonical_bytes(report["calibration"]))


def test_calibration_failure_blocks_all_m1_launches(auth):
    calls = []

    def launch(command, timeout, *, permit):
        role = command[command.index("--child") + 1]
        calls.append(role)
        payload = fake_payload(role)
        if role == "R-KNOWN":
            payload["retained"] = snapshot(33 * h.MIB)
        return {"outcome": None, "payload": payload}

    report = h.run_stage(auth, "all", launcher=launch, clock=lambda: 0, task_reader=lambda: FUTURE_TASK)
    assert report["outcome"] == "INVALID_EXPERIMENT"
    assert calls == ["M0a", *h.CALIBRATION_ROLES]
    assert "m1" not in report


def test_report_integrity_exclusive_creation_and_binding(auth, tmp_path):
    report = fake_report(auth)
    children = report["calibration"]["children"]
    children[1]["payload"]["post_release"]["status"]["VmHWM"] -= 114688
    report["calibration"] = h.calibration_outcome(children)
    result = h.write_report(report, "synthetic.json", root=tmp_path)
    raw = (tmp_path / "synthetic.json").read_bytes()
    assert result["sha256"] == h.sha256(raw)
    assert (tmp_path / "synthetic.json.sha256").read_text() == result["sha256"] + "  synthetic.json\n"
    loaded = h.read_report(tmp_path / "synthetic.json", result["sha256"], root=tmp_path)
    assert loaded == report
    assert h.bind_calibration(loaded, report["provenance"]) == report["calibration"]
    with pytest.raises(FileExistsError):
        h.write_report(report, "synthetic.json", root=tmp_path)
    assert (tmp_path / "synthetic.json").read_bytes() == raw
    with pytest.raises(h.HarnessError, match="SHA-256"):
        h.read_report(tmp_path / "synthetic.json", "0" * 64, root=tmp_path)
    changed = copy.deepcopy(report["provenance"])
    changed["harness_sha256"] = "0" * 64
    with pytest.raises(h.HarnessError, match="provenance mismatch"):
        h.bind_calibration(loaded, changed)
    changed = copy.deepcopy(report["provenance"])
    changed["measurement_identity"]["cgroup_configuration"]["cpuset.cpus.effective"] = h.CPUSET_ABSENT
    with pytest.raises(h.HarnessError, match="provenance mismatch: measurement_identity"):
        h.bind_calibration(loaded, changed)


@pytest.mark.parametrize("tamper", ["missing", "changed", "unsigned", "wrong_type", "label"])
def test_binding_rejects_inconsistent_vmhwm_diagnostics(auth, tmp_path, tamper):
    report = fake_report(auth)
    report["calibration"]["children"][1]["payload"]["post_release"]["status"]["VmHWM"] -= 114688
    report["calibration"] = h.calibration_outcome(report["calibration"]["children"])
    assert report["calibration"]["outcome"] == "CALIBRATION_PASS"
    evidence = report["calibration"]["vmhwm_signed_differences"]
    assert evidence["R-KNOWN"]["post_release_minus_retained_bytes"] == -114688
    if tamper == "missing":
        del report["calibration"]["vmhwm_signed_differences"]
    elif tamper == "changed":
        evidence["R-KNOWN"]["retained_minus_before_bytes"] += 1
    elif tamper == "unsigned":
        evidence["R-KNOWN"]["post_release_minus_retained_bytes"] = 114688
    elif tamper == "wrong_type":
        evidence["R-NULL"]["retained_minus_before_bytes"] = False
    else:
        evidence["interpretation"] = "acceptance_gate"
    # Valid serialization/sidecar cannot make inconsistent derived evidence bind.
    result = h.write_report(report, "tampered.json", root=tmp_path)
    loaded = h.read_report(tmp_path / "tampered.json", result["sha256"], root=tmp_path)
    with pytest.raises(h.HarnessError, match="VmHWM diagnostic evidence mismatch"):
        h.bind_calibration(loaded, report["provenance"])


def test_report_size_and_provenance_guards(auth, tmp_path):
    report = fake_report(auth)
    report["padding"] = "x" * h.REPORT_LIMIT
    with pytest.raises(h.HarnessError, match="1 MiB"):
        h.write_report(report, "oversize.json", root=tmp_path)
    assert list(tmp_path.iterdir()) == []
    del report["padding"]
    del report["provenance"]["task_sha256"]
    with pytest.raises(h.HarnessError, match="provenance"):
        h.write_report(report, "incomplete.json", root=tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["../escape.json", "/tmp/escape.json", "child/escape.json", "..", "x.txt"])
def test_output_name_confinement(auth, tmp_path, name):
    with pytest.raises(h.HarnessError):
        h.write_report(fake_report(auth), name, root=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_report_symlinks_sidecar_collision_and_root_escape(auth, tmp_path):
    report = fake_report(auth)
    target = tmp_path / "target"
    target.write_text("preserve")
    (tmp_path / "link.json").symlink_to(target)
    with pytest.raises(FileExistsError):
        h.write_report(report, "link.json", root=tmp_path)
    (tmp_path / "parent").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        h.write_report(report, "via-parent.json", root=tmp_path / "parent")
    with pytest.raises(h.HarnessError):
        h.write_report(report, "escape.json", root=tmp_path / ".." / "escape")
    (tmp_path / "collision.json.sha256").write_text("preserve sidecar")
    with pytest.raises(FileExistsError):
        h.write_report(report, "collision.json", root=tmp_path)
    assert not (tmp_path / "collision.json").exists()
    with pytest.raises(OSError):
        h.read_report(tmp_path / "link.json", "0" * 64, root=tmp_path)
    with pytest.raises(h.HarnessError):
        h.read_report(tmp_path.parent / "outside.json", "0" * 64, root=tmp_path)
    with pytest.raises(h.HarnessError):
        h.read_report(tmp_path / ".." / "outside.json", "0" * 64, root=tmp_path)
    assert target.read_text() == "preserve"
    assert (tmp_path / "collision.json.sha256").read_text() == "preserve sidecar"


def test_successful_child_cli_with_synthetic_payload_and_pipe(auth, monkeypatch, tmp_path, capsys):
    task_directory = tmp_path / ".ai"
    task_directory.mkdir()
    (task_directory / "TASK.md").write_bytes(FUTURE_TASK)
    monkeypatch.setattr(h, "ROOT", tmp_path)
    expected = fake_payload("R-NULL")

    def child(child_auth, role):
        assert child_auth == auth and role == h._CHILD_ROLE == "R-NULL"
        return expected

    monkeypatch.setattr(h, "child_measurement", child)
    permit = {"protocol": "r2e-child-v1", "role": "R-NULL", "task_sha256": auth.task_sha256,
              "parent_pid": h.os.getppid(), "preflight_sha256": "1" * 64,
              "calibration_sha256": None}
    read_end, write_end = h.os.pipe()
    with h.os.fdopen(write_end, "wb") as stream:
        stream.write(h.canonical_bytes(permit))
    assert h.main(["--child", "R-NULL", "--task-sha256", auth.task_sha256,
                   "--parent-permit-fd", str(read_end)]) == 0
    assert json.loads(capsys.readouterr().out) == expected
    assert h._CHILD_ROLE is None
    assert sorted(path.name for path in tmp_path.iterdir()) == [".ai"]


def test_successful_stage_cli_with_fake_stage_and_temp_report(auth, monkeypatch, tmp_path, capsys):
    expected = fake_report(auth)
    task_directory = tmp_path / ".ai"
    task_directory.mkdir()
    (task_directory / "TASK.md").write_bytes(FUTURE_TASK)
    monkeypatch.setattr(h, "ROOT", tmp_path)
    calls = []

    def run(stage_auth, stage, **kwargs):
        assert stage_auth == auth and stage == "M0b"
        assert kwargs == {"calibration_path": None, "calibration_digest": None}
        calls.append(stage)
        return expected

    actual_write = h.write_report
    report_root = tmp_path / "reports"
    monkeypatch.setattr(h, "run_stage", run)
    monkeypatch.setattr(h, "write_report", lambda report, name: actual_write(report, name, root=report_root))
    monkeypatch.setattr(h.signal, "signal", lambda sig, handler: "synthetic_previous_handler")
    alarms = []
    monkeypatch.setattr(h.signal, "setitimer", lambda timer, seconds: alarms.append(seconds))
    assert h.main(["--stage", "M0b", "--task-sha256", auth.task_sha256,
                   "--output", "cli.json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    raw = (report_root / "cli.json").read_bytes()
    assert calls == ["M0b"] and alarms == [900, 0]
    assert printed == {"outcome": "CALIBRATION_PASS", "report": str(report_root / "cli.json"),
                       "sha256": h.sha256(raw)}
    assert json.loads(raw) == expected


def test_authorization_and_stage_refusal(auth, capsys):
    for stage in ("M0a", "M0b", "M1", "all", "M2", "M3"):
        with pytest.raises(h.HarnessError):
            h.run_stage(None, stage, launcher=forbidden, task_reader=lambda: FUTURE_TASK)
    with pytest.raises(h.HarnessError):
        h.gate(auth, "M1", task_reader=lambda: FUTURE_TASK + b"changed")
    limited_task = b"R2E_MEMORY_EXECUTION_AUTHORIZED: M0a\n"
    limited = h.authorize(limited_task, h.sha256(limited_task))
    with pytest.raises(h.HarnessError):
        h.run_stage(limited, "M0b", launcher=forbidden, task_reader=lambda: limited_task)
    held = FUTURE_TASK + b"M0/M1 EXECUTION HOLD\n"
    with pytest.raises(h.HarnessError, match="holds"):
        h.authorize(held, h.sha256(held))
    actual_task = (h.ROOT / ".ai/TASK.md").read_bytes()
    for args in (["--stage", "M0a"], ["--stage", "M0b"], ["--stage", "M1"], ["--child", "R-NULL"]):
        assert h.main([*args, "--task-sha256", h.sha256(actual_task)]) == 1
        assert json.loads(capsys.readouterr().out)["outcome"] == "INVALID_EXPERIMENT"
    with pytest.raises(SystemExit) as error:
        h.main(["--stage", "M2"])
    assert error.value.code == 2
    assert h.OUTPUT_ROOT == h.ROOT / ".ai/validation/rb_post3d_08p2e2_r2e"
