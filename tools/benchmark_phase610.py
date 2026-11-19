#!/usr/bin/env python3
"""Phase 6.10 Stage 1: fresh-process measurements, never optimizations.

Timing workers are uninstrumented. Counter workers forward production calls
unchanged. References are guarded against changes outside the three harness files.
"""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
from contextlib import ExitStack, contextmanager, nullcontext
import functools
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
VERSION = "phase610-stage1-v1"
COMPARISON_VERSION = "phase610-stage2-comparison-v1"
CHECKPOINT = "b0d979f6f86b5f5eea929a801aa924318b286a29"
BASE_COMMIT = "5613086b072d7cad57dc230c12a6acc7934a1d4e"
BASE_TREE = "19d3f30d65b4d7aafc3fc6728e02f3e73eb86015"
PERMITTED = frozenset({"tools/benchmark_phase610.py", "tools/benchmark_phase610_fixtures.py",
                       "tests/unit/test_phase610_benchmark_contract.py"})


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def source_guard():
    base_commit = git("rev-parse", "phase-6.9-validated^{}")
    base_tree = git("rev-parse", "phase-6.9-validated^{tree}")
    changed = set(git("diff", "--name-only", "phase-6.9-validated", "--").splitlines())
    changed.update(git("ls-files", "--others", "--exclude-standard").splitlines())
    forbidden = sorted(changed - PERMITTED)
    if base_commit != BASE_COMMIT or base_tree != BASE_TREE or forbidden:
        raise ValueError(f"scientific source guard blocked: base={base_commit}/{base_tree}; forbidden={forbidden}")
    contents = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in sorted(PERMITTED) if (ROOT / name).exists()}
    return {"head_commit": git("rev-parse", "HEAD"), "head_tree": git("rev-parse", "HEAD^{tree}"),
        "validated_commit": base_commit, "validated_tree": base_tree,
        "branch": git("branch", "--show-current"), "dirty": bool(git("status", "--porcelain")),
        "status": git("status", "--porcelain"), "changed_files": sorted(changed),
        "permitted_files": sorted(PERMITTED), "harness_version": VERSION,
        "harness_content_sha256": digest(contents), "file_content_hashes": contents}


def environment(source=None):
    packages = {}
    for name in ("pvlib", "numpy", "scipy", "pandas", "shapely", "jsonschema", "referencing", "pyarrow", "pytest"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    normalized = "\n".join(sorted(line.strip() for line in freeze.splitlines() if line.strip())) + "\n"
    cpu = None
    if Path("/proc/cpuinfo").exists():
        cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")), None)
    quota = {}
    for name in ("cpu.max", "cpuset.cpus.effective", "memory.max"):
        path = Path("/sys/fs/cgroup") / name
        quota[name] = path.read_text().strip() if path.exists() else None
    try:
        import shapely
        geos = shapely.geos_version_string
    except (ImportError, AttributeError):
        geos = None
    try:
        distribution = platform.freedesktop_os_release()
    except OSError:
        distribution = None
    return {"python": {"version": platform.python_version(), "implementation": platform.python_implementation(),
        "executable": sys.executable}, "packages": packages, "geos": geos,
        "dependency_freeze_sha256": hashlib.sha256(normalized.encode()).hexdigest(),
        "normalized_pip_freeze": normalized, "os_distribution": distribution,
        "kernel": platform.release(), "platform": platform.platform(), "architecture": platform.machine(),
        "wsl": "microsoft" in platform.release().lower(), "cpu_model": cpu,
        "visible_logical_cpu_count": os.cpu_count(),
        "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "cgroup": quota, "thread_environment": {k: os.environ.get(k) for k in
            ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
             "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS")}, "source": source if source is not None else source_guard()}


def execution_identity(env):
    """Strict compatibility; only the separately guarded source identity differs."""
    return {k: v for k, v in env.items() if k != "source"}


def benchmark_identity():
    return {"comparison_version": COMPARISON_VERSION, "reference_schema": "Phase610Stage1Manifest/0.1",
        "snapshot_schema": "exact_scientific_snapshot_v1", "harness_version": VERSION,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixtures_sha256": hashlib.sha256((ROOT / "tools/benchmark_phase610_fixtures.py").read_bytes()).hexdigest(),
        "measurement_scopes": {p: measurement_scope(p) for p in "ABC"}}


def production_patch(base):
    paths = ["."] + [":(exclude)" + p for p in sorted(PERMITTED)]
    return subprocess.check_output(["git", "-c", "core.quotePath=false", "diff", "--binary", "--full-index",
        "--no-ext-diff", "--no-textconv", "--no-renames", base, "--", *paths], cwd=ROOT)


def candidate_source_guard(baseline, review):
    """A separate explicit patch guard; the Stage 1 guard is never widened."""
    if git("rev-parse", "phase-6.9-validated^{}") != BASE_COMMIT or git("rev-parse", "phase-6.9-validated^{tree}") != BASE_TREE:
        raise ValueError("candidate source guard blocked: validated tag changed")
    base = baseline["baseline_source"]["head_commit"]
    if review["baseline_commit"] != base or git("rev-parse", base + "^{tree}") != baseline["baseline_source"]["head_tree"]:
        raise ValueError("candidate source guard blocked: baseline identity mismatch")
    changed = set(git("diff", "--name-only", base, "--").splitlines())
    untracked = set(git("ls-files", "--others", "--exclude-standard").splitlines())
    if untracked - PERMITTED:
        raise ValueError("candidate source guard blocked: untracked candidate files")
    production = sorted(changed - PERMITTED)
    allowed = review["production_files"]
    if not isinstance(allowed, list) or allowed != sorted(set(allowed)) or any(
            not isinstance(p, str) or p.startswith("/") or ".." in Path(p).parts or p in PERMITTED for p in allowed):
        raise ValueError("candidate source guard blocked: invalid reviewed scope")
    patch_hash = hashlib.sha256(production_patch(base)).hexdigest()
    if production != allowed or patch_hash != review["production_diff_sha256"]:
        raise ValueError("candidate source guard blocked: reviewed patch scope/hash mismatch")
    contents = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sorted(PERMITTED)}
    return {"head_commit": git("rev-parse", "HEAD"), "head_tree": git("rev-parse", "HEAD^{tree}"),
        "working_tree_base": base, "changed_files": sorted(changed | untracked),
        "production_changed_files": production, "production_diff_sha256": patch_hash,
        "file_content_hashes": contents, "review_sha256": digest(review)}


def reference_inventory(root):
    result = {}
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise ValueError("baseline contains a symlink")
        if p.is_file() and p != root / "baseline-seal.json":
            result[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def seal_baseline(root, manifest, records, historical=None):
    if manifest["environment"]["source"]["head_commit"] != CHECKPOINT:
        raise ValueError("persistent baseline requires the Stage 1 checkpoint")
    if any(r["status"] not in {"completed", "not_applicable"} for r in records):
        raise ValueError("cannot seal an incomplete baseline")
    seal = {"comparison_version": COMPARISON_VERSION, "baseline_source": manifest["environment"]["source"],
        "benchmark_identity": benchmark_identity(), "execution_identity": execution_identity(manifest["environment"]),
        "diagnostics": manifest["diagnostics"], "cases": manifest["cases"],
        "snapshots": {r["case"] + "/" + r["path"]: {"fixture": r["fixture"],
            "scientific_snapshot_sha256": r["scientific_snapshot_sha256"], "scientific_hashes": r["scientific_hashes"],
            "package_verification": "passed" if r["path"] == "C" else "not_applicable"}
            for r in records if r["status"] == "completed"},
        "historical_metadata": historical, "files_sha256": reference_inventory(root)}
    with (root / "baseline-seal.json").open("x") as stream:
        stream.write(json.dumps(seal, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return seal


def load_baseline(root, expected_hash=None):
    seal_path = root / "baseline-seal.json"
    if expected_hash is not None and hashlib.sha256(seal_path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("baseline seal hash mismatch")
    seal = json.loads(seal_path.read_text())
    if seal["comparison_version"] != COMPARISON_VERSION or reference_inventory(root) != seal["files_sha256"]:
        raise ValueError("baseline reference integrity mismatch")
    return seal


def comparison_compatibility(seal, env, fixture, case, path, diagnostics):
    if seal["benchmark_identity"] != benchmark_identity():
        raise ValueError("benchmark semantics/harness identity mismatch")
    if seal["execution_identity"] != execution_identity(env):
        raise ValueError("execution environment/dependency compatibility mismatch")
    if diagnostics != seal["diagnostics"] or (fixture is not None and fixture != seal["snapshots"][case + "/" + path]["fixture"]):
        raise ValueError("fixture/numerical policy/diagnostics mismatch")


def rss_bytes():
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(raw * 1024) if sys.platform.startswith("linux") else int(raw) if sys.platform == "darwin" else None


class Counters:
    """Scoped counting only; no argument, result, ordering or exception changes."""
    def __init__(self):
        self.counts = Counter()
        self.isc_depth = 0
        self.labels = {}
        self.observed_ceilings = OrderedDict()
        self.endpoint_observation_complete = True

    @contextmanager
    def installed(self):
        import pvlib
        import shading.electrical.substring_reference as branch
        import shading.electrical.string_iv as string
        import shading.electrical.mppt_parallel as parallel
        import shading.electrical.dc_attribution as dc
        with ExitStack() as stack:
            def wrap(module, name, key, before=None, after=None):
                original = getattr(module, name)
                @functools.wraps(original)
                def forwarded(*args, **kwargs):
                    self.counts[key] += 1
                    token = before(args, kwargs) if before else None
                    try:
                        result = original(*args, **kwargs)
                        if after:
                            after(result, args, kwargs)
                        return result
                    finally:
                        if token == "isc":
                            self.isc_depth -= 1
                stack.enter_context(patch.object(module, name, forwarded))
            wrap(pvlib.pvsystem, "v_from_i", "pvlib_v_from_i")
            wrap(pvlib.pvsystem, "i_from_v", "pvlib_i_from_v")
            # dc_attribution owns an imported alias, unlike branch solver globals.
            wrap(branch, "_branch_current_at_voltage", "branch_current_inversion")
            wrap(dc, "_branch_current_at_voltage", "branch_current_inversion")
            def ceiling_observed(result, args, kwargs):
                key = (id(args[0]), id(args[1]))
                self.observed_ceilings[key] = (args[0], args[1], result)
                self.observed_ceilings.move_to_end(key)
                if len(self.observed_ceilings) > 64:
                    self.observed_ceilings.popitem(last=False)
            def voltage_observed(args, kwargs):
                current = kwargs.get("current_a")
                if current == 0.0:
                    self.counts["branch_open_voltage_evaluations"] += 1
                found = self.observed_ceilings.get((id(args[0]), id(args[1])))
                if found is not None and found[0] is args[0] and found[1] is args[1]:
                    if current == found[2]:
                        self.counts["branch_endpoint_voltage_evaluations"] += 1
                else:
                    self.endpoint_observation_complete = False
            wrap(branch, "_branch_current_ceiling", "branch_current_ceiling_evaluations", after=ceiling_observed)
            wrap(dc, "_branch_current_ceiling", "branch_current_ceiling_evaluations", after=ceiling_observed)
            wrap(branch, "evaluate_series_branch_voltage", "branch_voltage_evaluations", before=voltage_observed)
            wrap(dc, "evaluate_series_branch_voltage", "branch_voltage_evaluations", before=voltage_observed)
            def enter_isc(args, kwargs):
                self.isc_depth += 1
                return "isc"
            def state(args, kwargs):
                if self.isc_depth:
                    self.counts["string_states_during_isc"] += 1
            wrap(string, "_solve_string_isc", "string_isc_solves", before=enter_isc)
            wrap(string, "_string_state_at_current", "string_state_evaluations", before=state)
            wrap(parallel, "_combined_state_at_voltage", "mppt_combined_state_evaluations")
            wrap(parallel, "_current_at_voltage", "mppt_current_interpolation_evaluations")
            wrap(parallel, "_interval_vertex", "interval_vertex_attempts",
                 after=lambda result, a, k: self.counts.update({"interval_vertex_accepted": int(result is not None)}))
            def label_protected(result, args, kwargs):
                self.labels[id(result)] = "U" if args[2].get("schema_name") == "UniformRegionalEffectiveIrradianceCounterfactual" else "B"
            wrap(dc, "build_phase66_series_module_operating_model", "protected_counterfactual_models", after=label_protected)
            wrap(dc, "build_bypass_off_module_model", "bypass_off_models",
                 after=lambda result, a, k: self.labels.__setitem__(id(result), "N"))
            def optimize_before(args, kwargs):
                self.counts["independent_" + self.labels[id(args[0])] + "_attempts"] += 1
            def optimize_after(result, args, kwargs):
                self.counts["independent_" + self.labels[id(args[0])] + "_results"] += 1
            wrap(dc, "optimize_independent_module", "independent_optimization_attempts",
                 before=optimize_before, after=optimize_after)
            yield self

    def record(self):
        keys = ("pvlib_v_from_i", "pvlib_i_from_v", "branch_current_inversion", "string_isc_solves",
            "string_state_evaluations", "string_states_during_isc", "mppt_combined_state_evaluations",
            "mppt_current_interpolation_evaluations", "interval_vertex_attempts", "interval_vertex_accepted",
            "independent_optimization_attempts", "protected_counterfactual_models", "bypass_off_models")
        result = {k: self.counts[k] for k in keys}
        result.update({f"independent_{basis}_{field}": self.counts[f"independent_{basis}_{field}"]
                       for basis in "UNB" for field in ("attempts", "results")})
        result["mppt_base_knot_count"] = None
        result["mppt_base_knot_unavailable_reason"] = "No exposed base-grid diagnostic; production knot logic is not duplicated."
        result.update({k: self.counts[k] for k in ("branch_current_ceiling_evaluations",
            "branch_voltage_evaluations", "branch_open_voltage_evaluations")})
        result["branch_endpoint_voltage_evaluations"] = self.counts["branch_endpoint_voltage_evaluations"] if self.endpoint_observation_complete else None
        result["endpoint_observation_complete"] = self.endpoint_observation_complete
        result["endpoint_observation_method"] = "Exact current equality against an observed production ceiling; bounded 64-entry tracker; no ceiling recomputation."
        return result


def measurement_scope(path):
    return {"A": {"entry_point": "execute_detailed_mppt_backend", "includes": ["physics", "freeze", "hash", "validation"],
                  "excludes": ["imports", "fixture", "_prepare_backend", "B0_overrides", "compact_projection", "post_return_verification"]},
            "B": {"entry_point": "execute_detailed_dc_attribution", "includes": ["source_replay", "counterfactuals", "hash", "freeze", "validation"],
                  "excludes": ["imports", "fixture", "physical_source_load", "physical_execution", "post_return_verification"]},
            "C": {"entry_point": "run_canonical_simulation", "includes": ["preflight", "preparation", "physics", "downstream", "attribution", "persistence"],
                  "excludes": ["imports", "fixture", "empty_destination_creation", "post_return_package_verification"]}}[path]


def scientific_snapshot(numerical, attribution=None, canonical=None):
    from engine.simulation.detailed_downstream import compact_selected_states
    from engine.simulation.artifacts import dataframe_logical_sha256
    compact = compact_selected_states(numerical)
    value = {"physical_canonical_sha256": hashlib.sha256(numerical.canonical_payload).hexdigest(),
        "physical_numerical_sha256": numerical.numerical_result_sha256,
        "compact_canonical_sha256": hashlib.sha256(compact.canonical_payload).hexdigest(),
        "compact_result_sha256": compact.compact_result_sha256,
        "physical": numerical.replay(), "compact": compact.replay()}
    if attribution is not None:
        value.update(attribution_canonical_sha256=hashlib.sha256(attribution.canonical_payload).hexdigest(),
            attribution_result_sha256=attribution.attribution_result_sha256, attribution=attribution.replay(),
            attribution_diagnostic_sha256=hashlib.sha256(attribution.diagnostic_payload).hexdigest() if attribution.diagnostic_payload is not None else None)
    if canonical is not None:
        value["timeseries_logical_sha256"] = dataframe_logical_sha256(canonical.standard_timeseries)
        value["downstream_timeseries_logical_sha256"] = dataframe_logical_sha256(canonical.backend_result.timeseries)
        # Summary embeds transport/Parquet file identity, kept separately for audit.
        summary = dict(canonical.summary_result)
        for key in ("simulation_run_id", "generated_at", "result_reference"):
            summary.pop(key, None)
        value["summary_scientific"] = summary
        value["energy_summary"] = json.loads((canonical.artifact_directory / "detailed-dc-attribution-energy-summary.json").read_text())["payload"]
    return value, compact


def parity(actual, expected):
    mismatches = sorted(k for k in set(actual) | set(expected)
        if k not in actual or k not in expected or encoded(actual[k]) != encoded(expected[k]))
    return {"status": "passed" if not mismatches else "failed", "comparison": "exact_json_values_and_canonical_payload_hashes",
            "mismatched_sections": mismatches}


def worker(options):
    from benchmark_phase610_fixtures import (build_fixture, prepare_physical, boundary_overrides,
        fixture_identity, assert_b0_direct)
    from engine.simulation.detailed_backend import execute_detailed_mppt_backend, DetailedMPPTBackendResult
    from engine.simulation.detailed_attribution import execute_detailed_dc_attribution
    from engine.simulation.canonical import run_canonical_simulation
    from engine.simulation.artifacts import verify_run_package
    record = {"schema_name": "Phase610Stage1Benchmark", "schema_version": "0.1", "process_mode": "fresh",
        "pid": os.getpid(), "case": options.case, "path": options.path, "mode": options.mode,
        "repetition": options.repetition, "diagnostics": options.diagnostics,
        "environment_sha256": options.environment_hash, "measurement_scope": measurement_scope(options.path),
        "status": "failed", "timing": None, "memory": None, "counters": None, "sizes": None,
        "parity": None, "failure": None}
    if options.case == "B0" and options.path == "C":
        record.update(status="not_applicable", failure={"reason": "Historical B0 boundary isolation is not a canonical fixture."})
        return record
    setup_start = time.perf_counter_ns()
    review = json.loads(options.comparison_review.read_text()) if options.comparison_review else None
    seal = load_baseline(options.reference, review["baseline_seal_sha256"]) if review else None
    guard = candidate_source_guard(seal, review) if review else source_guard()
    record["source"] = guard
    candidate_env = environment(guard) if review else None
    if review and digest(candidate_env) != options.environment_hash:
        raise ValueError("candidate identity/environment changed since controller validation")
    reference_manifest = json.loads((options.reference / "manifest.json").read_text()) if not options.preparing else None
    if reference_manifest and not review and (reference_manifest["environment_sha256"] != options.environment_hash):
        raise ValueError("reference environment/harness differs; prepare a new reference directory")
    f = build_fixture(options.case)
    f["configuration"]["output_configuration"]["detailed_diagnostics"] = options.diagnostics == "on"
    canonical = attribution = numerical = None
    # C must perform _prepare_backend only inside canonical execution.
    args = prepare_physical(f) if options.path != "C" else None
    prepared_identity = fixture_identity(f, args) if args is not None else None
    if review and options.path != "C":
        comparison_compatibility(seal, candidate_env, prepared_identity, options.case, options.path, options.diagnostics)
    if options.path == "B":
        source_dir = options.reference / options.case / options.diagnostics / "A"
        source_record = json.loads((source_dir / "physical.json").read_text())
        numerical = DetailedMPPTBackendResult(bytes.fromhex(source_record["canonical_hex"]), source_record["numerical_result_sha256"])
        numerical.replay()
        source_meta = json.loads((source_dir / "record.json").read_text())
        if source_meta["fixture"] != prepared_identity:
            raise ValueError("attribution source fixture mismatch")
    package_root = options.destination / "package"
    if options.path == "C":
        package_root.mkdir(parents=True, exist_ok=False)
    counters = Counters() if options.mode == "counters" else None
    with boundary_overrides(options.case), (counters.installed() if counters else nullcontext()):
        setup_wall = (time.perf_counter_ns() - setup_start) / 1e9
        setup_rss = rss_bytes()
        cpu_start, wall_start = time.process_time_ns(), time.perf_counter_ns()
        if options.path == "A":
            # Stable benchmark input identity, distinct from canonical dispatch identity.
            numerical = execute_detailed_mppt_backend(f["weather"], scientific_input_sha256=prepared_identity["sha256"], **args)
        elif options.path == "B":
            attribution = execute_detailed_dc_attribution(numerical, module_inputs=args["module_inputs"],
                module_configs=args["module_configs"], electrical_design=args["electrical_design"],
                retain_diagnostics=options.diagnostics == "on")
        else:
            canonical = run_canonical_simulation(f["project"], f["configuration"], revision_store=f["store"],
                output_directory=package_root, simulation_run_id="phase610-" + options.case,
                engine_version="phase610-benchmark", executed_at="2026-10-04T00:00:00Z")
            numerical, attribution = canonical.detailed_backend_result, canonical.detailed_attribution_result
        wall = (time.perf_counter_ns() - wall_start) / 1e9
        cpu = (time.process_time_ns() - cpu_start) / 1e9
        execution_rss = rss_bytes()
    record["timing"] = {"setup_wall_seconds": setup_wall, "execution_wall_seconds": wall,
        "execution_cpu_seconds": cpu, "authoritative": options.mode == "timing", "postprocessing_wall_seconds": None}
    record["memory"] = {"method": "resource_RUSAGE_SELF_ru_maxrss", "setup_high_water_bytes": setup_rss,
        "execution_high_water_bytes": execution_rss, "verification_high_water_bytes": None,
        "scope": "whole fresh process including imports and setup; no isolated allocation subtraction"}
    post_start = time.perf_counter_ns()
    if canonical and canonical.standard_timeseries is None:
        record.update(status="blocked", failure={"reason": "canonical execution did not complete", "run": canonical.simulation_run})
        return record
    if args is None:
        args = prepare_physical(f)
    record["fixture"] = prepared_identity if prepared_identity is not None else fixture_identity(f, args)
    if review:
        comparison_compatibility(seal, candidate_env, record["fixture"], options.case, options.path, options.diagnostics)
        if candidate_source_guard(seal, review) != guard:
            raise ValueError("candidate source changed during execution")
        record["comparison"] = {"baseline_source": seal["baseline_source"], "candidate_source": guard,
            "baseline_snapshot": seal["snapshots"][options.case + "/" + options.path],
            "baseline_seal_sha256": review["baseline_seal_sha256"],
            "benchmark_identity": benchmark_identity(), "execution_compatibility_sha256": digest(execution_identity(candidate_env))}
    snapshot, compact = scientific_snapshot(numerical, attribution, canonical)
    if options.preparing and options.case == "B0" and options.path == "A":
        assert_b0_direct(numerical, f, args)
        record["b0_direct_reference_assertions"] = "passed"
    if options.preparing and options.case == "B0" and attribution is not None:
        from math import isclose
        bases = snapshot["attribution"]["intervals"][0]["ledger"]["bases"]
        for key, expected in zip("UNBSCT", (2543.1186253936125, 2424.1372911652925, 2426.7174557099297,
                                           2426.7171242241366, 2264.1653389107187, 2264.1653389107187)):
            assert bases[key]["status"] == "available" and isclose(bases[key]["power_w"], expected, abs_tol=1e-7, rel_tol=1e-9)
        record["b0_attribution_reference_assertions"] = "passed"
    reference_dir = options.reference / options.case / options.diagnostics / options.path
    if options.preparing:
        source_guard()  # Recheck before writing reference outputs.
        record["parity"] = {"status": "reference_created", "base_commit": BASE_COMMIT}
    else:
        record["parity"] = parity(snapshot, json.loads((reference_dir / "scientific.json").read_text()))
        record["parity"]["reference_scientific_sha256"] = digest(json.loads((reference_dir / "scientific.json").read_text()))
        if options.timing_results is not None:
            timing_manifest = json.loads((options.timing_results / "manifest.json").read_text())
            if timing_manifest["environment_sha256"] != options.environment_hash or timing_manifest["mode"] != "timing":
                raise ValueError("paired timing series environment/mode mismatch")
            timing_dir = options.timing_results / options.case / options.path / str(options.repetition)
            timing_record = json.loads((timing_dir / "record.json").read_text())
            if timing_record["status"] != "completed" or timing_record["diagnostics"] != options.diagnostics:
                raise ValueError("paired timing result is incomplete or diagnostics differ")
            record["instrumented_vs_timing_parity"] = parity(snapshot, json.loads((timing_dir / "scientific.json").read_text()))
    files = {}
    raw_hashes = {}
    if canonical:
        verify_run_package(canonical.artifact_directory)
        for file in sorted(canonical.artifact_directory.rglob("*")):
            if file.is_file():
                name = str(file.relative_to(canonical.artifact_directory))
                files[name] = file.stat().st_size
                raw_hashes[name] = hashlib.sha256(file.read_bytes()).hexdigest()
    record["sizes"] = {"physical_diagnostic_canonical_bytes": len(numerical.canonical_payload),
        "compact_physical_canonical_bytes": len(compact.canonical_payload),
        "compact_attribution_canonical_bytes": len(attribution.canonical_payload) if attribution else None,
        "attribution_diagnostic_canonical_bytes": len(attribution.diagnostic_payload) if attribution and attribution.diagnostic_payload is not None else None,
        "persisted_artifact_file_bytes": files if canonical else None,
        "canonical_package_bytes": sum(files.values()) if canonical else None}
    record["scientific_hashes"] = {k: v for k, v in snapshot.items() if k.endswith("sha256")}
    record["scientific_snapshot_sha256"] = digest(snapshot)
    record["raw_package_file_sha256"] = raw_hashes if canonical else None
    record["raw_package_hash_scope"] = "audit only; not a scientific parity target"
    record["package_verification"] = "passed" if canonical else "not_applicable"
    record["mppt_returned_counts"] = [{"interval_start": interval["interval_start"], "mppt_instance_id": m["mppt_instance_id"],
        "curve_points": len(m["combined_curve"]["points"]) if m["combined_curve"] is not None else None,
        "voltage_samples": len(m["combined_state"]["voltage_samples"]) if m["combined_curve"] is not None else None}
        for interval in snapshot["physical"]["intervals"] for m in interval["mppts"]]
    record["scope_counts"] = {"intervals": len(snapshot["physical"]["intervals"]),
        "dark_mppt_intervals": sum(m.get("availability") == "inactive_dark" for i in snapshot["physical"]["intervals"] for m in i["mppts"])}
    if counters:
        record["counters"] = counters.record()
        record["counters"]["basis_availability"] = {k: dict(Counter(m["bases"][k]["status"] for i in snapshot["attribution"]["intervals"] for m in i["modules"]))
                                                   for k in "UNB"} if attribution else None
    record["memory"]["verification_high_water_bytes"] = rss_bytes()
    record["timing"]["postprocessing_wall_seconds"] = (time.perf_counter_ns() - post_start) / 1e9
    passed = record["parity"]["status"] in {"passed", "reference_created"}
    passed = passed and record.get("instrumented_vs_timing_parity", {"status": "passed"})["status"] == "passed"
    record["status"] = "completed" if passed else "failed"
    if not passed:
        record["failure"] = {"reason": "scientific parity mismatch"}
    write_json(options.destination / "scientific.json", snapshot)
    if options.preparing:
        write_json(options.destination / "physical.json", {"canonical_hex": numerical.canonical_payload.hex(),
                                                         "numerical_result_sha256": numerical.numerical_result_sha256})
        write_json(options.destination / "canonical-payloads.json", {
            "physical_hex": numerical.canonical_payload.hex(), "compact_physical_hex": compact.canonical_payload.hex(),
            "attribution_hex": attribution.canonical_payload.hex() if attribution else None})
    return record


def statistics_for(records):
    groups = {}
    for record in records:
        if record["status"] != "completed" or record["mode"] != "timing":
            continue
        key = record["case"] + "-" + record["path"]
        groups.setdefault(key, []).append(record["timing"]["execution_wall_seconds"])
    return {key: {"samples_seconds": values, "median_seconds": statistics.median(values),
                  "min_seconds": min(values), "max_seconds": max(values)} for key, values in groups.items()}


def human_summary(records, env_hash, stats):
    lines = ["# Phase 6.10 Stage 1", "", f"Environment identity: `{env_hash}`", "",
        "All repetitions use fresh processes. Counter durations are instrumented and are not primary timings.", "",
        "| Case/path | Mode | Status | Wall s | CPU s | Execution peak RSS MiB | Parity | Canonical bytes: physical / compact / attribution / attribution diagnostics | Package bytes |",
        "|---|---|---|---:|---:|---:|---|---|---:|"]
    for r in records:
        t, m, s = r.get("timing") or {}, r.get("memory") or {}, r.get("sizes") or {}
        fmt = lambda value: f"{value:.3f}" if value is not None else "—"
        sizes = " / ".join(str(s.get(k)) if s.get(k) is not None else "—" for k in
            ("physical_diagnostic_canonical_bytes", "compact_physical_canonical_bytes", "compact_attribution_canonical_bytes", "attribution_diagnostic_canonical_bytes"))
        lines.append(f"| {r['case']}/{r['path']} | {r['mode']} | {r['status']} | {fmt(t.get('execution_wall_seconds'))} | {fmt(t.get('execution_cpu_seconds'))} | {fmt(m['execution_high_water_bytes']/1048576 if m.get('execution_high_water_bytes') is not None else None)} | {(r.get('parity') or {}).get('status', '—')} | {sizes} | {s.get('canonical_package_bytes', '—')} |")
        if r.get("counters"):
            lines.extend(["", f"{r['case']}/{r['path']} counters: `{json.dumps(r['counters'], sort_keys=True)}`", ""])
    lines.extend(["", "Timing statistics (individual samples retained):", "", "```json", json.dumps(stats, indent=2), "```", "",
        "Limitations: RSS includes imports/setup/source loading; high-water differences are not allocation measurements. "
        "B0 excludes real thermal coupling. Day fixtures are synthetic diffuse-only. History-wide thermal stopping is unchanged. "
        "OS caches and machine load are uncontrolled. Base MPPT knot counts are unavailable. "
        "Diagnostics-off still constructs physical diagnostics. Package hashes are audit metadata, not scientific parity targets."])
    return "\n".join(lines) + "\n"


def controller(options):
    review = json.loads(options.comparison_review.read_text()) if options.command == "compare" else None
    baseline = load_baseline(options.reference, review["baseline_seal_sha256"]) if review else None
    source = candidate_source_guard(baseline, review) if review else source_guard()
    if options.seal_baseline and source["head_commit"] != CHECKPOINT:
        raise ValueError("persistent baseline requires checkpoint b0d979f")
    if options.output.exists():
        raise FileExistsError("output directory must be new; references/results are never overwritten")
    env = environment(source)
    env_hash = digest(env)
    if review:
        comparison_compatibility(baseline, env, None, None, None, options.diagnostics)
        if not set(options.cases) <= set(baseline["cases"]):
            raise ValueError("comparison case absent from baseline")
    reference_seal = load_baseline(options.reference) if options.command == "run" and (options.reference / "baseline-seal.json").exists() else None
    options.output.mkdir(parents=True)
    reference = options.output if options.command == "prepare" else options.reference
    manifest = {"schema_name": "Phase610Stage1Manifest", "schema_version": "0.1", "environment": env,
        "environment_sha256": env_hash, "process_mode": "fresh", "command": options.command,
        "cases": options.cases, "paths": options.paths, "mode": options.mode, "diagnostics": options.diagnostics,
        "reference": str(reference.resolve())}
    manifest["benchmark_identity"] = benchmark_identity()
    manifest["execution_compatibility_sha256"] = digest(execution_identity(env))
    if review:
        manifest["comparison"] = {"baseline_identity": baseline, "candidate_identity": source,
            "review": review, "review_sha256": digest(review)}
    write_json(options.output / "manifest.json", manifest)
    records = []
    stop = False
    for case in options.cases:
        if stop:
            break
        for path in options.paths:
            if stop:
                break
            for repetition in range(1, options.repeat + 1):
                destination = options.output / case / options.diagnostics / path if options.command == "prepare" else options.output / case / path / str(repetition)
                destination.mkdir(parents=True)
                command = [sys.executable, "-B", str(Path(__file__).resolve()), "_worker", "--case", case,
                    "--path", path, "--mode", options.mode, "--diagnostics", options.diagnostics,
                    "--reference", str(reference.resolve()), "--destination", str(destination.resolve()),
                    "--environment-hash", env_hash, "--repetition", str(repetition)]
                if options.command == "prepare":
                    command.append("--preparing")
                if options.timing_results is not None:
                    command.extend(["--timing-results", str(options.timing_results.resolve())])
                if review:
                    command.extend(["--comparison-review", str(options.comparison_review.resolve())])
                print(f"Starting fresh {case}/{path} {options.mode} repetition {repetition}", flush=True)
                result = subprocess.run(command, cwd=ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                        capture_output=True, text=True)
                if (destination / "record.json").exists():
                    record = json.loads((destination / "record.json").read_text())
                else:
                    record = {"case": case, "path": path, "mode": options.mode, "status": "failed",
                              "failure": {"stderr": result.stderr, "stdout": result.stdout, "returncode": result.returncode}}
                records.append(record)
                with (options.output / "workers.jsonl").open("a") as stream:
                    stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                print(f"Finished {case}/{path}: {record['status']}", flush=True)
                if record["status"] in {"failed", "blocked"}:
                    print(json.dumps(record.get("failure")), flush=True)
                    stop = True
                    break
    stats = statistics_for(records) if options.command in {"run", "compare"} else {}
    summary = {"schema_name": "Phase610Stage1Summary", "schema_version": "0.1", "environment_sha256": env_hash,
               "records": records, "timing_statistics": stats}
    write_json(options.output / "summary.json", summary)
    (options.output / "summary.md").write_text(human_summary(records, env_hash, stats))
    if review:
        load_baseline(options.reference, review["baseline_seal_sha256"])
        if candidate_source_guard(baseline, review) != source:
            raise ValueError("candidate source changed during controller execution")
    if reference_seal is not None:
        if load_baseline(options.reference) != reference_seal:
            raise ValueError("baseline changed during run")
    if options.seal_baseline:
        if source_guard() != source:
            raise ValueError("baseline source changed during preparation")
        historical = json.loads(options.historical_metadata.read_text()) if options.historical_metadata else None
        seal_baseline(options.output, manifest, records, historical)
    return int(any(r["status"] in {"failed", "blocked"} for r in records))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--cases", nargs="+", choices=("B0", "B1", "B2", "B3"), default=["B0", "B1"])
        p.add_argument("--paths", nargs="+", choices=("A", "B", "C"), default=["A", "B", "C"])
        p.add_argument("--output", type=Path, required=True)
        p.add_argument("--reference", type=Path)
        p.add_argument("--timing-results", type=Path, help="paired uninstrumented series, required for counter runs")
        p.add_argument("--diagnostics", choices=("off", "on"), default="off")
        p.add_argument("--mode", choices=("timing", "counters"), default="timing")
        p.add_argument("--repeat", type=int, default=1)
        p.add_argument("--comparison-review", type=Path, help="reviewed exact production patch and pinned baseline seal; compare only")
        p.add_argument("--seal-baseline", action="store_true", help="prepare only; checkpoint-bound immutable reference inventory")
        p.add_argument("--historical-metadata", type=Path, help="prepare/seal only; historical values are audit metadata")
    p = sub.add_parser("_worker")
    for name in ("case", "path", "mode", "diagnostics", "environment-hash"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    p.add_argument("--repetition", type=int, required=True)
    p.add_argument("--preparing", action="store_true")
    p.add_argument("--timing-results", type=Path)
    p.add_argument("--comparison-review", type=Path)
    options = parser.parse_args()
    if options.command != "_worker":
        if options.repeat < 1 or (options.command in {"run", "compare"} and options.reference is None):
            parser.error("repeat must be positive; run requires --reference")
        if options.command == "prepare" and (options.paths != ["A", "B", "C"] or options.repeat != 1 or options.mode != "timing"):
            parser.error("prepare requires paths A B C, one uninstrumented repetition")
        if options.command in {"run", "compare"} and options.mode == "counters" and options.timing_results is None:
            parser.error("counter runs require --timing-results for direct instrumented/uninstrumented parity")
        if options.command == "prepare" and options.timing_results is not None:
            parser.error("prepare does not accept --timing-results")
        if (options.command == "compare") != bool(options.comparison_review):
            parser.error("compare requires --comparison-review; other commands reject it")
        if (options.seal_baseline or options.historical_metadata) and options.command != "prepare":
            parser.error("baseline sealing/historical metadata are prepare-only")
        if options.historical_metadata and not options.seal_baseline:
            parser.error("historical metadata requires --seal-baseline")
        return controller(options)
    try:
        record = worker(options)
    except Exception as exc:
        record = {"schema_name": "Phase610Stage1Benchmark", "schema_version": "0.1", "process_mode": "fresh",
            "case": options.case, "path": options.path, "mode": options.mode, "repetition": options.repetition,
            "status": "failed", "failure": {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}}
    write_json(options.destination / "record.json", record)
    return int(record["status"] in {"failed", "blocked"})


if __name__ == "__main__":
    sys.exit(main())
