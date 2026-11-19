"""Synthetic M0/M1 allocator harness. Measurement execution is currently on HOLD.

Standard library only; never imports production code. See the companion validation
document for the future authorization protocol and the limits of these instruments.
Importing this module performs no preflight, allocation experiment or filesystem write.
"""

from __future__ import annotations

import argparse
import ast
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import tracemalloc
from dataclasses import dataclass


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "shading/electrical/substring_reference.py"
SOURCE_SHA256 = "45157f6a93c9e066b54ddffe70875cf06bed4a17816ca8a0cd797d4120b1a3ba"
EXPECTED_HEAD = "5a88b22eb3633d5b90282416bc8f87f4a96c9bb6"
EXPECTED_BRANCH = "ai/rb-post3d-08p2-e2-r2a-memo-observe"
OUTPUT_RELATIVE = ".ai/validation/rb_post3d_08p2e2_r2e"
OUTPUT_ROOT = ROOT / OUTPUT_RELATIVE
MIB = 1024 * 1024
KNOWN_BYTES = 16 * MIB
SLOTS = 512
ADDITIONAL_ENTRIES = SLOTS * (1024 - 256)
REPORT_LIMIT = MIB
STDERR_PREVIEW_BYTES = 4096
EXIT_GRACE_SECONDS = 0.5
EXIT_GRACE_POLLS = 10
CPUSET_ABSENT = "ABSENT_CONTROLLER_NOT_ENABLED"
RSS_LIMIT = 1024 * MIB
STAGE_SECONDS = 900
REPORT_ALLOWANCE = 50
CALIBRATION_ROLES = ("R-NULL", "R-KNOWN", "T-KNOWN")
M1_ROLES = ("T-BASE", "T-CAND", "R-BASE", "R-CAND", "R-CAND", "R-BASE")
STATUS_FIELDS = ("VmRSS", "VmHWM", "RssAnon", "VmSwap")
SMAPS_FIELDS = ("Rss", "AnonHugePages", "Swap")
FAILURES = {"INFRASTRUCTURE_FAILURE", "INVALID_EXPERIMENT", "INCONCLUSIVE", "RESOURCE_LIMIT"}
AUTH_MARKER = "R2E_MEMORY_EXECUTION_AUTHORIZED: "
SCHEMA = "rb-post3d-08p2e2-r2e-memory-v1"
_CHILD_ROLE = None


class HarnessError(RuntimeError):
    def __init__(self, message, outcome="INVALID_EXPERIMENT"):
        super().__init__(message)
        self.outcome = outcome


class ExitStatusUnavailable(HarnessError):
    """The task_mem fields can disappear before process exit is observable."""


def require(condition, message, outcome="INVALID_EXPERIMENT"):
    if not condition:
        raise HarnessError(message, outcome)


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Authorization:
    task_sha256: str
    stages: tuple[str, ...]
    expected_head: str = EXPECTED_HEAD
    expected_branch: str = EXPECTED_BRANCH


def authorize(task_bytes, supplied_digest, *, expected_head=EXPECTED_HEAD,
              expected_branch=EXPECTED_BRANCH):
    """An affirmative future TASK scope update AND its explicit digest are required."""
    require(supplied_digest == sha256(task_bytes), "Explicit current TASK SHA-256 required")
    text = task_bytes.decode("utf-8")
    require("M0/M1 EXECUTION HOLD" not in text, "Current TASK holds M0/M1 execution")
    lines = [line for line in text.splitlines() if line.startswith(AUTH_MARKER)]
    require(len(lines) == 1, "Future TASK must contain exactly one authorization line")
    stages = tuple(lines[0][len(AUTH_MARKER):].split(","))
    require(bool(stages) and len(set(stages)) == len(stages)
            and set(stages) <= {"M0a", "M0b", "M1"}, "Invalid authorized stages")
    require(re.fullmatch(r"[0-9a-f]{40}", expected_head) is not None, "Invalid expected HEAD")
    require(bool(expected_branch) and not expected_branch.startswith("-"), "Invalid branch")
    return Authorization(supplied_digest, stages, expected_head, expected_branch)


def gate(auth, stage, *, task_reader=None):
    require(isinstance(auth, Authorization), "Measurement authorization required")
    reader = task_reader or (lambda: (ROOT / ".ai/TASK.md").read_bytes())
    checked = authorize(reader(), auth.task_sha256, expected_head=auth.expected_head,
                        expected_branch=auth.expected_branch)
    require(checked == auth and stage in checked.stages, f"Stage {stage} is not authorized")


def guard_source(source_bytes, expected_digest=SOURCE_SHA256):
    require(sha256(source_bytes) == expected_digest, "Production source SHA-256 mismatch")
    try:
        tree = ast.parse(source_bytes)
    except (SyntaxError, ValueError) as exc:
        raise HarnessError("Production source AST unavailable") from exc
    assignments = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(part, ast.Name) and part.id == "_BRANCH_CURRENT_MEMO_LIMIT"
                   for target in targets for part in ast.walk(target)):
                assignments.append(node)
    require(len(assignments) == 1, "Expected one module-level memo-limit assignment")
    node = assignments[0]
    require(isinstance(node, (ast.Assign, ast.AnnAssign))
            and isinstance(node.value, ast.Constant)
            and type(node.value.value) is int and node.value.value == 256,
            "Production memo limit must be integer 256")
    return {"sha256": sha256(source_bytes), "ast_memo_limit": 256}


def parse_kib_fields(text, required):
    result = {}
    for line in text.splitlines():
        name, sep, raw = line.partition(":")
        if name not in required:
            continue
        require(sep and name not in result, f"Duplicate or malformed {name}")
        match = re.fullmatch(r"\s*(\d+)\s+kB\s*", raw)
        require(match is not None, f"Invalid /proc units or value: {name}")
        result[name] = int(match.group(1)) * 1024
    require(set(result) == set(required), "Missing required /proc fields")
    return result


def parse_status(text):
    result = parse_kib_fields(text, STATUS_FIELDS)
    require(result["VmHWM"] >= result["VmRSS"], "VmHWM below VmRSS")
    require(result["RssAnon"] <= result["VmRSS"], "RssAnon above VmRSS")
    return result


def watchdog_status_rss(text):
    """Recognize only the all-memory-fields-absent exit pattern for grace."""
    if not any(re.match(r"^(?:" + "|".join(STATUS_FIELDS) + r")(?:\s|:|$)", line.lstrip())
               for line in text.splitlines()):
        raise ExitStatusUnavailable("Missing watchdog /proc memory fields",
                                    "INFRASTRUCTURE_FAILURE")
    return parse_status(text)["VmRSS"]


def read_watchdog_rss(pid):
    return watchdog_status_rss(Path(f"/proc/{pid}/status").read_text())


def parse_smaps(text):
    result = parse_kib_fields(text, SMAPS_FIELDS)
    require(result["AnonHugePages"] <= result["Rss"], "Huge pages above RSS")
    return result


def proc_snapshot(read_text=None):
    read = read_text or (lambda name: Path(name).read_text())
    return {"status": parse_status(read("/proc/self/status")),
            "smaps_rollup": parse_smaps(read("/proc/self/smaps_rollup"))}


def parse_swaps(text):
    lines = text.splitlines()
    require(bool(lines) and lines[0].split() == ["Filename", "Type", "Size", "Used", "Priority"],
            "Unknown /proc/swaps format")
    devices = []
    for line in lines[1:]:
        fields = line.split()
        require(len(fields) == 5, "Malformed swap device")
        require(fields[2].isdigit() and fields[3].isdigit()
                and re.fullmatch(r"-?\d+", fields[4]) is not None, "Malformed swap counts")
        devices.append({"device": fields[0], "type": fields[1],
                        "size_bytes": int(fields[2]) * 1024,
                        "used_bytes": int(fields[3]) * 1024, "priority": int(fields[4])})
    return devices


def selected_thp(text):
    selected = re.findall(r"\[([^\]]+)\]", text)
    require(len(selected) == 1 and selected[0] in
            {"always", "madvise", "never", "defer", "defer+madvise"}, "Unknown THP configuration")
    return {"raw": text.strip(), "selected": selected[0]}


def validate_cgroup(result):
    require(result["membership"].startswith("0::/"), "Unknown cgroup membership")
    for name in ("memory.max", "memory.current", "memory.swap.max", "memory.swap.current"):
        value = result[name]
        require((type(value) is int and value >= 0) or (name.endswith(".max") and value == "max"),
                f"Unknown cgroup {name}")
    events = result["memory.events"]
    require({"low", "high", "max", "oom", "oom_kill"} <= events.keys()
            and all(type(value) is int and value >= 0 for value in events.values()), "Invalid cgroup events")
    cpus = result["cpuset.cpus.effective"]
    # CPU affinity is required separately. A disabled cpuset controller need not
    # expose this optional file; present but malformed controls still fail closed.
    if cpus == CPUSET_ABSENT:
        return result
    require(isinstance(cpus, str) and re.fullmatch(r"\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*", cpus) is not None,
            "Unknown cgroup CPU set")
    previous = -1
    for interval in cpus.split(","):
        ends = [int(value) for value in interval.split("-")]
        require(previous < ends[0] <= ends[-1], "Invalid cgroup CPU interval")
        previous = ends[-1]
    return result


def cgroup_facts(read_text):
    lines = read_text("/proc/self/cgroup").splitlines()
    require(len(lines) == 1 and lines[0].startswith("0::/"), "Only known cgroup v2 layout supported")
    relative = Path(lines[0][4:])
    require(not relative.is_absolute() and ".." not in relative.parts, "Unknown cgroup path")
    base = Path("/sys/fs/cgroup") / relative
    result = {"membership": lines[0], "path": str(base)}
    for name in ("memory.max", "memory.current", "memory.swap.max", "memory.swap.current"):
        value = read_text(str(base / name)).strip()
        require(value.isdigit() or (name.endswith(".max") and value == "max"),
                f"Unknown cgroup {name}")
        result[name] = value if value == "max" else int(value)
    events = {}
    for line in read_text(str(base / "memory.events")).splitlines():
        fields = line.split()
        require(len(fields) == 2 and fields[1].isdigit() and fields[0] not in events,
                "Unknown cgroup events")
        events[fields[0]] = int(fields[1])
    require({"low", "high", "max", "oom", "oom_kill"} <= events.keys(), "Missing cgroup events")
    result["memory.events"] = events
    try:
        result["cpuset.cpus.effective"] = read_text(str(base / "cpuset.cpus.effective")).strip()
        require(result["cpuset.cpus.effective"] != CPUSET_ABSENT, "Unknown cgroup CPU set")
    except FileNotFoundError:
        result["cpuset.cpus.effective"] = CPUSET_ABSENT
    return validate_cgroup(result)


def allocator_environment(env):
    names = {name: value for name, value in env.items()
             if name.startswith(("PYTHONMALLOC", "PYTHONTRACEMALLOC", "PYTHONDEVMODE", "MALLOC_"))
             or name in {"LD_PRELOAD", "LD_AUDIT", "GLIBC_TUNABLES"}}
    return names


def inspect_preflight(facts, source_bytes, expected_head=EXPECTED_HEAD,
                      expected_branch=EXPECTED_BRANCH):
    """Pure validation of injected facts. Missing/unknown capabilities fail closed."""
    try:
        guard = guard_source(source_bytes)
        require(facts["head"] == expected_head and facts["branch"] == expected_branch,
                "Git baseline mismatch")
        require(facts["implementation"] == "CPython" and facts["version"] == [3, 12, 3],
                "CPython 3.12.3 required")
        require(facts["system"] == "Linux" and bool(facts["kernel"]), "Linux kernel required")
        require(bool(facts["python_build"]) and bool(facts["compiler"]), "Unknown interpreter build")
        require(bool(facts["executable"]) and bool(facts["python_version"])
                and type(facts["allocated_blocks"]) is int and facts["allocated_blocks"] >= 0,
                "Missing interpreter/allocation instrument data")
        require(type(facts["page_size_bytes"]) is int and facts["page_size_bytes"] > 0,
                "Unknown OS page size")
        require(facts["with_pymalloc"] == 1 and facts["py_debug"] == 0
                and not facts["debug_refcounts"], "Unknown or debug allocator build")
        require(facts["gc_enabled"] and len(facts["gc_thresholds"]) == 3
                and all(type(x) is int and x > 0 for x in facts["gc_thresholds"]), "Unknown GC configuration")
        require(not any(facts[name] for name in ("tracing", "trace_hook", "profile_hook", "dev_mode")),
                "Allocation/tracing contamination")
        require(not facts["allocator_environment"], "Allocator environment contamination")
        require(facts["hashseed"] == "0" and not facts["ignore_environment"]
                and facts["hash_randomization"] == 0,
                "Effective fixed PYTHONHASHSEED=0 required")
        require(facts["clear_refs_exists"] and facts["clear_refs_writable"],
                "Own clear_refs reset instrument unavailable")
        parse_status(facts["status_text"])
        parse_smaps(facts["smaps_text"])
        mem = parse_kib_fields(facts["meminfo_text"], ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"))
        require(mem["MemAvailable"] > 0 and mem["MemTotal"] >= mem["MemAvailable"]
                and mem["SwapTotal"] >= mem["SwapFree"], "Invalid host memory data")
        require(bool(facts["affinity"]) and all(type(x) is int and x >= 0 for x in facts["affinity"]),
                "CPU affinity unavailable")
        require(bool(facts["boot_id"]) and bool(facts["machine"]), "Unknown host identity")
        validate_cgroup(facts["cgroup"])
        parse_swaps(facts["swaps_text"])
        selected_thp(facts["thp_enabled"])
        selected_thp(facts["thp_defrag"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HarnessError(f"Missing/invalid preflight facts: {exc}", "INFRASTRUCTURE_FAILURE") from exc
    return {"outcome": "PREFLIGHT_PASS", "source_guard": guard, "facts": facts,
            "clear_refs_probe": "availability_only_no_write",
            "kernel_compatibility": "feature_checks_only_reset_calibration_still_required"}


def collect_preflight(auth):
    """Read-only M0a collector; the parent imposes its ten-second deadline."""
    gate(auth, "M0a")
    read = lambda name: Path(name).read_text()

    def git(*args):
        return subprocess.check_output(["git", "--no-optional-locks", *args], cwd=ROOT,
                                       text=True, timeout=2).strip()

    facts = {
        "head": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
        "dirty_state": git("status", "--porcelain", "--untracked-files=all"),
        "implementation": platform.python_implementation(), "version": list(sys.version_info[:3]),
        "system": platform.system(), "kernel": platform.release(), "machine": platform.machine(),
        "python_build": list(platform.python_build()), "compiler": platform.python_compiler(),
        "executable": sys.executable, "python_version": sys.version,
        "with_pymalloc": sysconfig.get_config_var("WITH_PYMALLOC"),
        "py_debug": sysconfig.get_config_var("Py_DEBUG"),
        "debug_refcounts": hasattr(sys, "gettotalrefcount"),
        "gc_enabled": gc.isenabled(), "gc_thresholds": list(gc.get_threshold()),
        "allocated_blocks": sys.getallocatedblocks(),
        "page_size_bytes": os.sysconf("SC_PAGE_SIZE"),
        "tracing": tracemalloc.is_tracing(), "trace_hook": sys.gettrace() is not None,
        "profile_hook": sys.getprofile() is not None, "dev_mode": sys.flags.dev_mode,
        "ignore_environment": sys.flags.ignore_environment,
        "hash_randomization": sys.flags.hash_randomization,
        "hashseed": os.environ.get("PYTHONHASHSEED"),
        "allocator_environment": allocator_environment(os.environ),
        "clear_refs_exists": Path("/proc/self/clear_refs").is_file(),
        "clear_refs_writable": os.access("/proc/self/clear_refs", os.W_OK),
        "status_text": read("/proc/self/status"), "smaps_text": read("/proc/self/smaps_rollup"),
        "meminfo_text": read("/proc/meminfo"), "swaps_text": read("/proc/swaps"),
        "thp_enabled": read("/sys/kernel/mm/transparent_hugepage/enabled"),
        "thp_defrag": read("/sys/kernel/mm/transparent_hugepage/defrag"),
        "cgroup": cgroup_facts(read), "affinity": sorted(os.sched_getaffinity(0)),
        "boot_id": read("/proc/sys/kernel/random/boot_id").strip(),
    }
    return inspect_preflight(facts, (ROOT / SOURCE).read_bytes(),
                             auth.expected_head, auth.expected_branch)


def make_key(voltage, voltage_tol, current_tol, max_iterations=200):
    return (float.hex(voltage), voltage_tol, current_tol, max_iterations)


def admit(currents, key, value, capacity):
    if key in currents:
        return "hit"
    if len(currents) < capacity:
        currents[key] = value
        return "admitted"
    return "discarded"


def voltage_stream(slot, unique_count=1024):
    """Capacity-independent prefix, signed zeros, repeated hits, final overflow."""
    require(unique_count >= 2, "Stream requires signed-zero entries")
    for index in range(unique_count):
        voltage = 0.0 if index == 0 else (-0.0 if index == 1 else float(index - 1 + slot / 1024))
        yield "miss", voltage
        if index % 64 == 0:
            yield "hit", 0.0
    yield "overflow", float(unique_count + 1000 + slot / 1024)
    yield "overflow", float(unique_count + 1001 + slot / 1024)
    yield "hit", -0.0


@dataclass
class Payload:
    slots: list
    statistics: dict


def build_payload(slot_count, capacity, unique_count=1024):
    require(type(slot_count) is int and slot_count > 0, "Invalid slot count")
    require(type(capacity) is int and 2 <= capacity <= unique_count, "Invalid per-slot capacity")
    # Runtime construction prevents accidental float-constant identity sharing.
    voltage_tol = float("0.000001")
    current_tol = float("0.00000001")
    slots = []
    counts = {"hit": 0, "admitted": 0, "discarded": 0}
    for slot_number in range(slot_count):
        currents = {}
        slots.append(currents)
        for index, (_, voltage) in enumerate(voltage_stream(slot_number, unique_count)):
            key = make_key(voltage, voltage_tol, current_tol)
            # As in production, hits avoid computing a value. All retained values
            # are separate runtime float objects, even where their values coincide.
            if key in currents:
                counts["hit"] += 1
                continue
            value = float(index + slot_number / 1024 + 0.125)
            counts[admit(currents, key, value, capacity)] += 1
    occupancy = [len(currents) for currents in slots]
    require(all(count == capacity for count in occupancy), "Wrong per-slot occupancy")
    return Payload(slots, {"slot_count": slot_count, "capacity_per_slot": capacity,
                           "retained_entries": sum(occupancy), "occupancy": occupancy,
                           "admission_counts": counts,
                           "dictionary_bytes": sum(sys.getsizeof(d) for d in slots),
                           "tolerances": "shared_float_objects", "values": "distinct_float_objects"})


def page_touched(size):
    page_size = os.sysconf("SC_PAGE_SIZE")
    require(type(page_size) is int and page_size > 0, "Unknown OS page size")
    payload = bytearray(size)
    for index in range(0, size, page_size):
        payload[index] = 1
    if size:
        payload[-1] = 1
    return payload


def verify_reset(before, after):
    # Exact equality is deliberately conservative: uncertain resets fail closed.
    require(before["VmHWM"] > before["VmRSS"], "Reset lacks an independently observed prior high water")
    require(after["VmHWM"] < before["VmHWM"] and after["VmHWM"] == after["VmRSS"],
            "High-water reset was not independently verified")
    return {"verified": True, "before": before, "after": after,
            "verification_rule": "prior_hwm_above_rss_then_hwm_drops_to_current_rss"}


def reset_high_water(auth, stage, *, child_role=None, read_status=None, write_reset=None,
                     task_reader=None):
    gate(auth, stage, task_reader=task_reader)
    require(child_role in CALIBRATION_ROLES + M1_ROLES and child_role.startswith("R-"),
            "Reset is restricted to authorized RSS children")
    require(_CHILD_ROLE == child_role, "Reset is forbidden outside active child mode")
    read = read_status or (lambda: parse_status(Path("/proc/self/status").read_text()))

    def own_reset():
        # The only proc write anywhere in this module. No alternate path/value.
        with open("/proc/self/clear_refs", "w", encoding="ascii") as handle:
            require(handle.write("5") == 1, "Incomplete own high-water reset")

    before = read()
    (write_reset or own_reset)()
    return verify_reset(before, read())


def rss_measurement(auth, role, stage):
    gate(auth, stage)
    require(_CHILD_ROLE == role and role.startswith("R-"), "RSS measurement requires active child mode")
    require(not tracemalloc.is_tracing() and sys.gettrace() is None and sys.getprofile() is None,
            "RSS child contaminated by tracing")
    # This preparatory spike is outside every measurement window, including NULL.
    spike = page_touched(8 * MIB)
    del spike
    gc.collect()
    reset = reset_high_water(auth, stage, child_role=role)
    before = proc_snapshot()
    if role == "R-NULL":
        payload = None
    elif role == "R-KNOWN":
        payload = page_touched(KNOWN_BYTES)
    else:
        payload = build_payload(SLOTS, 256 if role.endswith("BASE") else 1024)
    retained = proc_snapshot()
    statistics = payload.statistics if isinstance(payload, Payload) else None
    del payload
    gc.collect()
    released = proc_snapshot()
    return {"role": role, "mode": "RSS", "reset": reset,
            "pre_window_spike_bytes": 8 * MIB,
            "before": before, "retained": retained, "post_release": released,
            "statistics": statistics, "null_window": "no_intentional_payload" if role == "R-NULL" else None}


def traced_measurement(auth, role, stage):
    gate(auth, stage)
    require(role in CALIBRATION_ROLES + M1_ROLES and role.startswith("T-"), "Invalid traced child role")
    require(_CHILD_ROLE == role, "Traced measurement requires active child mode")
    require(not tracemalloc.is_tracing() and sys.gettrace() is None and sys.getprofile() is None,
            "Traced child contaminated before tracer startup")
    gc.collect()
    tracemalloc.start(1)
    try:
        baseline, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        payload = (page_touched(KNOWN_BYTES) if role == "T-KNOWN"
                   else build_payload(SLOTS, 256 if role.endswith("BASE") else 1024))
        current, peak = tracemalloc.get_traced_memory()
        statistics = payload.statistics if isinstance(payload, Payload) else None
        del payload
        gc.collect()
        released, released_peak = tracemalloc.get_traced_memory()
        return {"role": role, "mode": "TRACED", "statistics": statistics,
                "traced_baseline_bytes": baseline, "traced_current_bytes": current,
                "traced_peak_bytes": peak, "traced_increment_bytes": current - baseline,
                "post_release_traced_current_bytes": released,
                "post_release_traced_peak_bytes": released_peak}
    finally:
        tracemalloc.stop()


def child_measurement(auth, role):
    stage = role_stage(role)
    gate(auth, stage)
    require(_CHILD_ROLE == role, "Measurement requires active child mode")
    if role == "M0a":
        return collect_preflight(auth)
    # Recheck source/interpreter/allocator contamination in EVERY fresh child.
    guard_source((ROOT / SOURCE).read_bytes())
    require(platform.python_implementation() == "CPython" and sys.version_info[:3] == (3, 12, 3)
            and platform.system() == "Linux", "Incompatible measurement interpreter/platform")
    require(os.environ.get("PYTHONHASHSEED") == "0" and not sys.flags.ignore_environment
            and sys.flags.hash_randomization == 0
            and not allocator_environment(os.environ) and not sys.flags.dev_mode,
            "Contaminated measurement environment")
    return (rss_measurement(auth, role, stage) if role.startswith("R-")
            else traced_measurement(auth, role, stage))


def sanitized_environment(env):
    # -P -s keeps the script/user site off sys.path while allowing the hash seed.
    # -I would ignore PYTHONHASHSEED and therefore is intentionally not used.
    clean = {key: env[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") if key in env}
    clean["PYTHONHASHSEED"] = "0"
    return clean


def child_command(auth, role):
    return [str(ROOT / ".venv/bin/python"), "-P", "-s", "-B", str(Path(__file__).resolve()),
            "--child", role, "--task-sha256", auth.task_sha256,
            "--expected-head", auth.expected_head, "--expected-branch", auth.expected_branch]


def role_stage(role):
    require(role in ("M0a",) + CALIBRATION_ROLES + M1_ROLES, "Unknown child role")
    return "M0a" if role == "M0a" else ("M0b" if role in CALIBRATION_ROLES else "M1")


def verify_child_permit(auth, role, permit, parent_pid):
    """Internal parent handoff, not a replacement for fresh TASK authorization."""
    stage = role_stage(role)
    require(permit["protocol"] == "r2e-child-v1" and permit["role"] == role
            and permit["task_sha256"] == auth.task_sha256
            and type(permit["parent_pid"]) is int and permit["parent_pid"] == parent_pid,
            "Invalid supervised-child permit")
    for field, needed in (("preflight_sha256", stage != "M0a"), ("calibration_sha256", stage == "M1")):
        value = permit.get(field)
        require((isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None)
                if needed else value is None, f"Child lacks required {field} evidence")


def read_child_permit(auth, role, descriptor):
    require(type(descriptor) is int and descriptor >= 3, "Child requires inherited parent permit")
    with os.fdopen(descriptor, "rb") as stream:
        require(stat.S_ISFIFO(os.fstat(stream.fileno()).st_mode), "Child permit must use an inherited pipe")
        raw = stream.read(4097)
    require(len(raw) <= 4096, "Oversized child permit")
    permit = json.loads(raw)
    verify_child_permit(auth, role, permit, os.getppid())
    return permit


def kill_child(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


def stderr_evidence(stream):
    """Bound the embedded preview, retaining the exact full byte count and hash."""
    stream.seek(0)
    digest = hashlib.sha256()
    preview = b""
    length = 0
    while chunk := stream.read(64 * 1024):
        digest.update(chunk)
        length += len(chunk)
        preview += chunk[:max(0, STDERR_PREVIEW_BYTES - len(preview))]
    return {"stderr": preview.decode("utf-8", errors="replace"),
            "stderr_bytes": length, "stderr_sha256": digest.hexdigest(),
            "stderr_truncated": length > STDERR_PREVIEW_BYTES}


def confirm_child_exit(process, deadline, now, pause):
    """Poll only, without re-sampling; bound time and polls even with a frozen clock."""
    if process.poll() is not None:
        return True
    grace_deadline = min(now() + EXIT_GRACE_SECONDS, deadline)
    for _ in range(EXIT_GRACE_POLLS):
        remaining = grace_deadline - now()
        if remaining <= 0:
            break
        pause(min(EXIT_GRACE_SECONDS / EXIT_GRACE_POLLS, remaining))
        if process.poll() is not None:
            return True
    return False


def watch_child(command, timeout, *, popen=None, clock=None, sleep=None,
                read_rss=None, kill=None, environment=None, permit=None):
    """One launch only; samples are resource guards, never a measured peak."""
    spawn = popen or subprocess.Popen
    now = clock or time.monotonic
    pause = sleep or time.sleep
    rss = read_rss or read_watchdog_rss
    stop = kill or kill_child
    start = now()
    process = None
    sampled_max = 0
    failure = None
    pipe_handles = []
    # Files avoid pipe deadlock. They are temporary IPC, never measurement reports.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            spawn_options = {}
            if permit is not None:
                raw_permit = canonical_bytes(permit)
                require(len(raw_permit) <= 4096, "Oversized child permit")
                read_end, write_end = os.pipe()
                pipe_handles.extend((read_end, write_end))
                require(os.write(write_end, raw_permit) == len(raw_permit), "Incomplete child permit")
                os.close(write_end)
                pipe_handles.remove(write_end)
                command = [*command, "--parent-permit-fd", str(read_end)]
                spawn_options["pass_fds"] = (read_end,)
            process = spawn(command, cwd=ROOT, env=sanitized_environment(
                os.environ if environment is None else environment),
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True, **spawn_options)
            for descriptor in pipe_handles:
                os.close(descriptor)
            pipe_handles.clear()
            while process.poll() is None:
                if now() - start >= timeout:
                    failure = ("RESOURCE_LIMIT", "Child deadline exceeded")
                    break
                try:
                    sample = rss(process.pid)
                    require(type(sample) is int and sample >= 0, "Invalid watchdog RSS reading",
                            "INFRASTRUCTURE_FAILURE")
                except (OSError, HarnessError) as exc:
                    if getattr(exc, "outcome", None) == "RESOURCE_LIMIT":
                        raise
                    if isinstance(exc, (ExitStatusUnavailable, FileNotFoundError, ProcessLookupError)):
                        if confirm_child_exit(process, start + timeout, now, pause):
                            break
                        if now() - start >= timeout:
                            failure = ("RESOURCE_LIMIT", "Child deadline exceeded")
                            break
                    raise HarnessError(f"Watchdog /proc failure: {exc}", "INFRASTRUCTURE_FAILURE") from exc
                sampled_max = max(sampled_max, sample)
                if sample > RSS_LIMIT:
                    failure = ("RESOURCE_LIMIT", "Sampled RSS ceiling exceeded")
                    break
                if stdout.tell() > REPORT_LIMIT or stderr.tell() > REPORT_LIMIT:
                    failure = ("RESOURCE_LIMIT", "Child IPC ceiling exceeded")
                    break
                pause(min(0.05, max(0, timeout - (now() - start))))
            if failure:
                stop(process)
            elapsed = now() - start
            if not failure and elapsed > timeout:
                failure = ("RESOURCE_LIMIT", "Child completed beyond deadline")
            if stdout.tell() > REPORT_LIMIT or stderr.tell() > REPORT_LIMIT:
                failure = ("RESOURCE_LIMIT", "Child IPC ceiling exceeded")
            stdout.seek(0)
            raw = stdout.read(REPORT_LIMIT + 1)
            diagnostics = stderr_evidence(stderr)
            if failure:
                return {"outcome": failure[0], "error": failure[1],
                        "elapsed_seconds": elapsed, "sampled_rss_max_bytes": sampled_max,
                        **diagnostics}
            if process.returncode != 0:
                try:
                    error = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    error = {}
                if not isinstance(error, dict):
                    error = {}
                return {"outcome": error.get("outcome") if error.get("outcome") in FAILURES
                        else "INFRASTRUCTURE_FAILURE",
                        "error": str(error.get("error", "Child failed"))[:STDERR_PREVIEW_BYTES],
                        "returncode": process.returncode, **diagnostics}
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                raise HarnessError("Malformed child IPC", "INFRASTRUCTURE_FAILURE") from exc
            require(isinstance(payload, dict), "Invalid child IPC", "INFRASTRUCTURE_FAILURE")
            return {"outcome": None, "payload": payload, "elapsed_seconds": elapsed,
                    "sampled_rss_max_bytes": sampled_max, **diagnostics,
                    "rss_sampling_caveat": "Resource guard only; sampling may miss brief spikes"}
        except (OSError, subprocess.SubprocessError, HarnessError) as exc:
            if process is not None and process.poll() is None:
                stop(process)
            return {"outcome": failure[0] if failure else getattr(exc, "outcome", "INFRASTRUCTURE_FAILURE"),
                    "error": str(exc), **stderr_evidence(stderr)}
        except BaseException:
            if process is not None and process.poll() is None:
                stop(process)
            raise
        finally:
            for descriptor in pipe_handles:
                os.close(descriptor)


def run_sequence(auth, roles, timeout, deadline, *, launcher=None, clock=None, evidence=None):
    launch = launcher or watch_child
    now = clock or time.monotonic
    results = []
    for role in roles:
        remaining = deadline - now()
        if remaining <= 0:
            results.append({"role": role, "outcome": "RESOURCE_LIMIT", "error": "Stage deadline"})
            break
        command = child_command(auth, role)
        permit = {"protocol": "r2e-child-v1", "role": role, "task_sha256": auth.task_sha256,
                  "parent_pid": os.getpid(), "preflight_sha256": None, "calibration_sha256": None,
                  **(evidence or {})}
        verify_child_permit(auth, role, permit, os.getpid())
        result = launch(command, min(timeout, remaining), permit=permit)
        result["role"] = role
        result["command_template"] = command
        result["parent_permit"] = permit
        results.append(result)
        if result["outcome"] is not None:
            break
    return results


def payloads(results, roles):
    for item in results:
        if item.get("outcome") in FAILURES:
            raise HarnessError(item.get("error", "Child failure"), item["outcome"])
    require([r["role"] for r in results] == list(roles), "Incomplete or reordered child sequence")
    for item in results:
        require(item.get("outcome") is None, "Child failure", item.get("outcome") or "INVALID_EXPERIMENT")
        result = item["payload"]
        role = item["role"]
        require(result["role"] == role, "Wrong child result role")
        mode = "TRACED" if role.startswith("T-") else "RSS"
        require(result["mode"] == mode, "Mixed measurement modes")
        if mode == "RSS":
            require(not any("traced" in key for key in result), "RSS result contains tracing")
            reset = result["reset"]
            require(reset["verified"], "Missing reset verification")
            verify_reset(reset["before"], reset["after"])
            for point in ("before", "retained", "post_release"):
                status = result[point]["status"]
                smaps = result[point]["smaps_rollup"]
                require(set(status) == set(STATUS_FIELDS) and set(smaps) == set(SMAPS_FIELDS),
                        "Incomplete instrument readings")
                require(all(type(v) is int and v >= 0 for v in [*status.values(), *smaps.values()]),
                        "Invalid instrument reading")
                require(status["VmHWM"] >= status["VmRSS"] >= status["RssAnon"]
                        and smaps["Rss"] >= smaps["AnonHugePages"], "Invalid RSS relationships")
        else:
            require(not any(key in result for key in ("before", "retained", "post_release", "reset")),
                    "Traced result contains RSS measurements")
            for key in ("traced_baseline_bytes", "traced_current_bytes", "traced_peak_bytes",
                        "post_release_traced_current_bytes", "post_release_traced_peak_bytes"):
                require(type(result[key]) is int and result[key] >= 0, "Invalid traced reading")
            require(result["traced_peak_bytes"] >= result["traced_current_bytes"]
                    and result["post_release_traced_peak_bytes"] >= result["traced_peak_bytes"]
                    and result["post_release_traced_peak_bytes"] >= result["post_release_traced_current_bytes"]
                    and result["traced_increment_bytes"] ==
                    result["traced_current_bytes"] - result["traced_baseline_bytes"], "Invalid traced increment")
    return [r["payload"] for r in results]


def calibration_outcome(results):
    try:
        null, known, traced = payloads(results, CALIBRATION_ROLES)
        null_delta = null["retained"]["status"]["VmHWM"] - null["before"]["status"]["VmHWM"]
        known_delta = known["retained"]["status"]["VmRSS"] - known["before"]["status"]["VmRSS"]
        traced_delta = traced["traced_increment_bytes"]
        valid = (0 <= null_delta <= 4 * MIB and 12 * MIB <= known_delta <= 24 * MIB
                 and 95 * KNOWN_BYTES <= 100 * traced_delta <= 105 * KNOWN_BYTES)
        swapped = any(child[point]["status"]["VmSwap"] or child[point]["smaps_rollup"]["Swap"]
                      for child in (null, known) for point in ("before", "retained", "post_release"))
        valid = valid and not swapped
        # Raw cross-snapshot differences are evidence, not instrument-validity gates.
        hwm_differences = {"interpretation": "informational_only"}
        for child in (null, known):
            before = child["before"]["status"]["VmHWM"]
            retained = child["retained"]["status"]["VmHWM"]
            released = child["post_release"]["status"]["VmHWM"]
            hwm_differences[child["role"]] = {
                "retained_minus_before_bytes": retained - before,
                "post_release_minus_retained_bytes": released - retained}
        return {"outcome": "CALIBRATION_PASS" if valid else "INVALID_EXPERIMENT",
                "null_hwm_increase_bytes": null_delta, "known_rss_increase_bytes": known_delta,
                "known_traced_increase_bytes": traced_delta,
                "vmhwm_signed_differences": hwm_differences,
                "swap_observed": swapped,
                "intervals": {"null_hwm_bytes": [0, 4 * MIB],
                              "known_rss_bytes": [12 * MIB, 24 * MIB],
                              "known_traced_percent": [95, 105]},
                "children": results}
    except (HarnessError, KeyError, TypeError) as exc:
        return {"outcome": getattr(exc, "outcome", "INVALID_EXPERIMENT"),
                "error": str(exc), "children": results}


def signed_comparison(baseline, candidate):
    delta = candidate - baseline
    return {"baseline_bytes": baseline, "candidate_bytes": candidate,
            "candidate_minus_baseline_bytes": delta,
            "incremental_bytes_per_entry": delta / ADDITIONAL_ENTRIES}


def m1_outcome(results, calibration):
    try:
        require(calibration["outcome"] == "CALIBRATION_PASS", "M0b calibration must pass before M1")
        traced_base, traced_cand, rss_a1, rss_b1, rss_b2, rss_a2 = payloads(results, M1_ROLES)
        children = [traced_base, traced_cand, rss_a1, rss_b1, rss_b2, rss_a2]
        for child in children:
            expected = 256 if child["role"].endswith("BASE") else 1024
            counts = child["statistics"]
            require(counts["slot_count"] == SLOTS and counts["capacity_per_slot"] == expected
                    and counts["retained_entries"] == SLOTS * expected
                    and counts["occupancy"] == [expected] * SLOTS, "Incorrect measured M1 occupancy")
        traced = {name: signed_comparison(traced_base[name], traced_cand[name])
                  for name in ("traced_current_bytes", "traced_peak_bytes", "traced_increment_bytes")}
        pairs = []
        for base, cand in ((rss_a1, rss_b1), (rss_a2, rss_b2)):
            pairs.append({name: signed_comparison(base["retained"]["status"][name],
                                                  cand["retained"]["status"][name])
                          for name in STATUS_FIELDS})
        means = {name: signed_comparison(
            (rss_a1["retained"]["status"][name] + rss_a2["retained"]["status"][name]) / 2,
            (rss_b1["retained"]["status"][name] + rss_b2["retained"]["status"][name]) / 2)
                 for name in STATUS_FIELDS}
        window_pairs = []
        for base, cand in ((rss_a1, rss_b1), (rss_a2, rss_b2)):
            window_pairs.append({name: signed_comparison(
                base["retained"]["status"][name] - base["before"]["status"][name],
                cand["retained"]["status"][name] - cand["before"]["status"][name])
                                 for name in STATUS_FIELDS})
        smaps_pairs = []
        release_pairs = []
        huge_page_differences = []
        for pair_number, (base, cand) in enumerate(((rss_a1, rss_b1), (rss_a2, rss_b2)), 1):
            smaps_pairs.append({name: signed_comparison(base["retained"]["smaps_rollup"][name],
                                                        cand["retained"]["smaps_rollup"][name])
                                for name in SMAPS_FIELDS})
            release_pairs.append({"VmRSS": signed_comparison(base["post_release"]["status"]["VmRSS"],
                                                             cand["post_release"]["status"]["VmRSS"])})
            for point in ("before", "retained", "post_release"):
                comparison = signed_comparison(base[point]["smaps_rollup"]["AnonHugePages"],
                                               cand[point]["smaps_rollup"]["AnonHugePages"])
                if comparison["candidate_minus_baseline_bytes"] != 0:
                    huge_page_differences.append({"pair": pair_number, "point": point, **comparison})
        smaps_means = {name: signed_comparison(
            (rss_a1["retained"]["smaps_rollup"][name] + rss_a2["retained"]["smaps_rollup"][name]) / 2,
            (rss_b1["retained"]["smaps_rollup"][name] + rss_b2["retained"]["smaps_rollup"][name]) / 2)
                       for name in SMAPS_FIELDS}
        release_means = {"VmRSS": signed_comparison(
            (rss_a1["post_release"]["status"]["VmRSS"] + rss_a2["post_release"]["status"]["VmRSS"]) / 2,
            (rss_b1["post_release"]["status"]["VmRSS"] + rss_b2["post_release"]["status"]["VmRSS"]) / 2)}
        negatives = [name for table in [traced, *pairs, means, *window_pairs,
                                       *smaps_pairs, smaps_means, *release_pairs, release_means]
                     for name, comparison in table.items()
                     if comparison["candidate_minus_baseline_bytes"] < 0]
        # Keep the legacy names-only list descriptive, including release negatives.
        # These labelled copies preserve each comparison's signed values and types.
        blocking_tables = [
            ("traced", "candidate_minus_baseline", traced),
            ("rss_pairwise_A1_B1_A2_B2", "pair_1", pairs[0]),
            ("rss_pairwise_A1_B1_A2_B2", "pair_2", pairs[1]),
            ("rss_means", "mean", means),
            ("rss_window_increment_pairwise", "pair_1", window_pairs[0]),
            ("rss_window_increment_pairwise", "pair_2", window_pairs[1]),
            ("smaps_pairwise_A1_B1_A2_B2", "pair_1", smaps_pairs[0]),
            ("smaps_pairwise_A1_B1_A2_B2", "pair_2", smaps_pairs[1]),
            ("smaps_means", "mean", smaps_means)]
        release_tables = [
            ("post_release_rss_pairwise_A1_B1_A2_B2", "pair_1", release_pairs[0]),
            ("post_release_rss_pairwise_A1_B1_A2_B2", "pair_2", release_pairs[1]),
            ("post_release_rss_means", "mean", release_means)]
        blocking_negatives, release_negatives = [
            [{"source": source, "comparison": label, "metric": name, **comparison}
             for source, label, table in tables for name, comparison in table.items()
             if comparison["candidate_minus_baseline_bytes"] < 0]
            for tables in (blocking_tables, release_tables)]
        swapped = any(child[point]["status"]["VmSwap"] or child[point]["smaps_rollup"]["Swap"]
                      for child in (rss_a1, rss_b1, rss_b2, rss_a2)
                      for point in ("before", "retained", "post_release"))
        return {"outcome": "INCONCLUSIVE" if blocking_negatives or swapped or huge_page_differences
                else "M1_ALLOCATOR_CALIBRATED",
                "traced": traced, "rss_pairwise_A1_B1_A2_B2": pairs, "rss_means": means,
                "rss_window_increment_pairwise": window_pairs,
                "smaps_pairwise_A1_B1_A2_B2": smaps_pairs, "smaps_means": smaps_means,
                "post_release_rss_pairwise_A1_B1_A2_B2": release_pairs,
                "post_release_rss_means": release_means,
                "huge_page_difference_points": huge_page_differences,
                "unexplained_negative_metrics": negatives, "swap_observed": swapped,
                "acceptance_blocking_negative_metrics": blocking_negatives,
                "post_release_negative_diagnostics": release_negatives,
                "additional_retained_entries": ADDITIONAL_ENTRIES,
                "acceptance_basis": "instrument_validity_and_occupancy_only_no_agreement_threshold",
                "projection_717_slots": {"outcome": "NOT_EVALUABLE", "kind": "projection_not_measurement",
                                         "reason": "Optional projection deferred; policy C not modeled"},
                "children": results}
    except (HarnessError, KeyError, TypeError) as exc:
        return {"outcome": getattr(exc, "outcome", "INVALID_EXPERIMENT"),
                "error": str(exc), "children": results}


def _report_name(name):
    require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*\.json", name) is not None,
            "Report must be a simple .json filename inside the designated root")
    return name


def _open_root(root, *, create=False):
    """Walk with directory descriptors: reject symlinks in ALL root ancestors."""
    root = Path(root)
    require(root.is_absolute() and ".." not in root.parts, "Invalid output root")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in root.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            next_descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                      dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def validate_report_envelope(report):
    require(report["schema"] == SCHEMA, "Wrong report schema")
    require(report["production_chronological_peak"] == "NOT_OBSERVED"
            and report["production_memory_qualification"] == "INCONCLUSIVE", "Invalid production claim")
    provenance = report["provenance"]
    require({"task_sha256", "harness_sha256", "source_sha256", "expected_head", "expected_branch",
             "created_utc", "argv", "environment", "measurement_identity"} <= provenance.keys(),
            "Incomplete report provenance")


def write_report(report, name, *, root=OUTPUT_ROOT):
    """Exclusive JSON+sidecar pair; never follows links or overwrites evidence."""
    _report_name(name)
    validate_report_envelope(report)
    data = canonical_bytes(report)
    require(len(data) <= REPORT_LIMIT, "Consolidated report exceeds 1 MiB", "RESOURCE_LIMIT")
    digest = sha256(data)
    sidecar = name + ".sha256"
    directory = _open_root(root, create=True)
    created = []
    handles = []
    try:
        for leaf in (name, sidecar):
            handle = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
            created.append(leaf)
            handles.append(handle)
        for handle, content in zip(handles, (data, f"{digest}  {name}\n".encode("ascii"))):
            view = memoryview(content)
            while view:
                written = os.write(handle, view)
                require(written > 0, "Incomplete report write", "INFRASTRUCTURE_FAILURE")
                view = view[written:]
            os.fsync(handle)
        os.fsync(directory)
    except BaseException:
        for leaf in created:
            os.unlink(leaf, dir_fd=directory)
        raise
    finally:
        for handle in handles:
            os.close(handle)
        os.close(directory)
    return {"report": str(Path(root) / name), "sha256": digest}


def read_report(path, expected_digest, *, root=OUTPUT_ROOT):
    path, root = Path(path), Path(root)
    require(path.is_absolute() and ".." not in path.parts, "Invalid calibration path")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise HarnessError("Calibration report outside designated output root") from exc
    require(len(relative.parts) == 1, "Calibration report must be directly under output root")
    name = _report_name(relative.name)
    directory = _open_root(root)
    try:
        contents = []
        for leaf in (name, name + ".sha256"):
            handle = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(handle, "rb") as stream:
                info = os.fstat(stream.fileno())
                require(stat.S_ISREG(info.st_mode) and info.st_size <= REPORT_LIMIT,
                        "Invalid calibration artifact")
                content = stream.read(REPORT_LIMIT + 1)
                require(len(content) <= REPORT_LIMIT, "Calibration artifact exceeds ceiling")
                contents.append(content)
        data, sidecar = contents
    finally:
        os.close(directory)
    require(sha256(data) == expected_digest and
            sidecar == f"{expected_digest}  {name}\n".encode("ascii"), "Calibration report SHA-256 mismatch")
    report = json.loads(data)
    validate_report_envelope(report)
    return report


def measurement_identity(preflight):
    facts = preflight["facts"]
    # Bind the optional cpuset's absence sentinel just as an observed CPU set:
    # enabling/disabling the controller invalidates an earlier calibration.
    cgroup = validate_cgroup(facts["cgroup"])
    return {name: facts[name] for name in
            ("head", "branch", "implementation", "version", "system", "kernel", "machine", "python_build",
             "compiler", "with_pymalloc", "py_debug", "page_size_bytes", "gc_enabled", "gc_thresholds",
             "hashseed", "hash_randomization",
             "allocator_environment", "affinity", "boot_id", "thp_enabled", "thp_defrag")} | {
                 "cgroup_configuration": {name: cgroup[name] for name in
                     ("membership", "memory.max", "memory.swap.max", "cpuset.cpus.effective")}}


def bind_calibration(report, current_provenance):
    validate_report_envelope(report)
    require(report["stage"] in ("M0b", "all")
            and report["outcome"] in ("CALIBRATION_PASS", "M1_ALLOCATOR_CALIBRATED")
            and report["preflight"]["outcome"] == "PREFLIGHT_PASS", "Invalid M0b report")
    for key in ("task_sha256", "harness_sha256", "source_sha256", "expected_head", "expected_branch",
                "measurement_identity"):
        require(report["provenance"][key] == current_provenance[key], f"M0b provenance mismatch: {key}")
    calibration = calibration_outcome(report["calibration"]["children"])
    require(calibration["outcome"] == "CALIBRATION_PASS", "Bound calibration does not pass")
    require(canonical_bytes(report["calibration"].get("vmhwm_signed_differences")) ==
            canonical_bytes(calibration["vmhwm_signed_differences"]),
            "M0b VmHWM diagnostic evidence mismatch")
    return calibration


def new_report(auth, stage):
    return {
        "schema": SCHEMA, "stage": stage, "outcome": "INCONCLUSIVE",
        "production_chronological_peak": "NOT_OBSERVED",
        "production_memory_qualification": "INCONCLUSIVE",
        "projection_717_slots": {"outcome": "NOT_EVALUABLE", "kind": "projection_not_measurement"},
        "provenance": {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "task_sha256": auth.task_sha256,
                       "harness_sha256": sha256(Path(__file__).read_bytes()),
                       "source_sha256": sha256((ROOT / SOURCE).read_bytes()),
                       "expected_head": auth.expected_head, "expected_branch": auth.expected_branch,
                       "argv": sys.argv[:], "environment": sanitized_environment(os.environ),
                       "measurement_identity": None},
        "limits": {"m0a_seconds": 10, "m0b_child_seconds": 40, "m1_child_seconds": 120,
                   "stage_seconds": STAGE_SECONDS, "parent_report_allowance_seconds": REPORT_ALLOWANCE,
                   "sampled_child_rss_bytes": RSS_LIMIT, "report_bytes": REPORT_LIMIT,
                   "sequential": True, "retries": 0,
                   "rss_caveat": "Sampled resource guard can miss brief spikes; never a measured peak"},
        "workload": {"slots": SLOTS, "baseline_capacity_per_slot": 256,
                     "candidate_capacity_per_slot": 1024, "baseline_entries": 131072,
                     "candidate_entries": 524288, "additional_entries": ADDITIONAL_ENTRIES,
                     "unshared_tolerance_full_scale": "DEFERRED", "policy_C": "NOT_IMPLEMENTED"},
    }


def run_stage(auth, stage, *, calibration_path=None, calibration_digest=None,
              launcher=None, clock=None, task_reader=None):
    """Future stage entry point. Tests inject a launcher; current TASK forbids runs."""
    require(stage in ("M0a", "M0b", "M1", "all"), "M2/M3 are not implemented")
    required = {"M0a"} | ({"M0b"} if stage in ("M0b", "all") else set()) | (
        {"M1"} if stage in ("M1", "all") else set())
    for needed in required:
        gate(auth, needed, task_reader=task_reader)
    now = clock or time.monotonic
    start = now()
    deadline = start + STAGE_SECONDS - REPORT_ALLOWANCE
    report = new_report(auth, stage)
    try:
        preflight_results = run_sequence(auth, ("M0a",), 10, deadline, launcher=launcher, clock=now)
        report["preflight_children"] = preflight_results
        child = preflight_results[0]
        require(child["outcome"] is None, child.get("error", "M0a failed"),
                child["outcome"] or "INVALID_EXPERIMENT")
        preflight = child["payload"]
        require(preflight["outcome"] == "PREFLIGHT_PASS", "M0a did not pass")
        # Revalidate reported facts rather than trusting an outcome string.
        preflight = inspect_preflight(preflight["facts"], (ROOT / SOURCE).read_bytes(),
                                      auth.expected_head, auth.expected_branch)
        report["preflight"] = preflight
        report["provenance"]["measurement_identity"] = measurement_identity(preflight)
        evidence = {"preflight_sha256": sha256(canonical_bytes(preflight))}
        report["outcome"] = "PREFLIGHT_PASS"
        if stage in ("M0b", "all"):
            children = run_sequence(auth, CALIBRATION_ROLES, 40, deadline, launcher=launcher,
                                    clock=now, evidence=evidence)
            report["calibration"] = calibration_outcome(children)
            report["outcome"] = report["calibration"]["outcome"]
        if stage == "M1":
            require(bool(calibration_path) and bool(calibration_digest), "M1 requires a hashed M0b report")
            bound = read_report(calibration_path, calibration_digest)
            report["calibration"] = bind_calibration(bound, report["provenance"])
            report["calibration_report"] = {"path": str(calibration_path), "sha256": calibration_digest}
        if stage in ("M1", "all"):
            require(report["calibration"]["outcome"] == "CALIBRATION_PASS",
                    "Calibration failure blocks M1", report["calibration"]["outcome"])
            # In combined runs the exact canonical calibration bytes bind M1.
            report["calibration_payload_sha256"] = sha256(canonical_bytes(report["calibration"]))
            evidence["calibration_sha256"] = report["calibration_payload_sha256"]
            children = run_sequence(auth, M1_ROLES, 120, deadline, launcher=launcher,
                                    clock=now, evidence=evidence)
            report["m1"] = m1_outcome(children, report["calibration"])
            report["outcome"] = report["m1"]["outcome"]
    except (HarnessError, OSError, KeyError, TypeError, ValueError) as exc:
        report["outcome"] = getattr(exc, "outcome", "INFRASTRUCTURE_FAILURE")
        report["error"] = str(exc)
    report["elapsed_seconds_before_report"] = now() - start
    if now() > deadline:
        report["outcome"] = "RESOURCE_LIMIT"
        report["error"] = "Measurement budget exhausted; report allowance reserved"
    return report


def main(argv=None):
    global _CHILD_ROLE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("M0a", "M0b", "M1", "all"))
    parser.add_argument("--child", choices=("M0a",) + tuple(dict.fromkeys(CALIBRATION_ROLES + M1_ROLES)),
                        help=argparse.SUPPRESS)
    parser.add_argument("--parent-permit-fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--task-sha256", help="Explicit digest of a separately authorized future TASK")
    parser.add_argument("--expected-head", default=EXPECTED_HEAD)
    parser.add_argument("--expected-branch", default=EXPECTED_BRANCH)
    parser.add_argument("--output", help="Exclusive simple .json filename under the fixed report root")
    parser.add_argument("--calibration-report", type=Path)
    parser.add_argument("--calibration-sha256")
    args = parser.parse_args(argv)
    alarm_installed = False
    previous_handler = None
    try:
        require(bool(args.stage) != bool(args.child), "Specify exactly one stage or child role")
        auth = authorize((ROOT / ".ai/TASK.md").read_bytes(), args.task_sha256,
                         expected_head=args.expected_head, expected_branch=args.expected_branch)
        if args.child:
            require(args.output is None and args.calibration_report is None, "Child cannot write reports")
            read_child_permit(auth, args.child, args.parent_permit_fd)
            _CHILD_ROLE = args.child
            result = child_measurement(auth, args.child)
            print(json.dumps(result, allow_nan=False))
            return 0
        _report_name(args.output)
        require(args.parent_permit_fd is None, "Only supervised children may receive a permit")
        require(args.stage == "M1" or (args.calibration_report is None and args.calibration_sha256 is None),
                "Calibration input only applies to standalone M1")

        def stage_alarm(signum, frame):
            raise HarnessError("900-second overall stage ceiling", "RESOURCE_LIMIT")

        previous_handler = signal.signal(signal.SIGALRM, stage_alarm)
        signal.setitimer(signal.ITIMER_REAL, STAGE_SECONDS)
        alarm_installed = True
        report = run_stage(auth, args.stage, calibration_path=args.calibration_report,
                           calibration_digest=args.calibration_sha256)
        artifact = write_report(report, args.output)
        print(json.dumps({"outcome": report["outcome"], **artifact}))
        return 0 if report["outcome"] in {"PREFLIGHT_PASS", "CALIBRATION_PASS", "M1_ALLOCATOR_CALIBRATED"} else 1
    except (HarnessError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"outcome": getattr(exc, "outcome", "INFRASTRUCTURE_FAILURE"), "error": str(exc)}))
        return 1
    finally:
        _CHILD_ROLE = None
        if alarm_installed:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
