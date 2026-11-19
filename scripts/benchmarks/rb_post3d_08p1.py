"""Measurement only. Run from the repository with its test dependencies installed.

Each size has one 600-second budget covering isolated timing/counting children.
No production permission gate is replaced; instrumentation always forwards.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
from functools import wraps
import importlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SIZES = (1, 10, 50)
WALL_CAP_SECONDS = 600
MEMORY_MIB = 4096


def build_fixture(size):
    if size not in SIZES:
        raise ValueError('only 1, 10 and 50 modules are authorized')
    from tests.unit.test_rb_post3d_08b3d2_activation import _fixture
    from tests.unit.test_rb_post3d_08b2_region_physics import _candidate
    from engine.simulation.detailed_inputs import freeze_detailed_selection
    project, config, store, scene, design, bundle = _fixture(_candidate())
    template = deepcopy(scene['module_instances'][0])
    modules = []
    for index in range(size):
        instance = deepcopy(template)
        instance['module_instance_id'] = f'08p1-module-{index:03d}'
        instance['transform']['position_x_m'] = template['transform']['position_x_m'] + 5. * index
        modules.append(instance)
    scene['module_instances'] = modules
    ids = [m['module_instance_id'] for m in modules]
    scene['pv_fields'][0]['generated_module_instance_ids'] = ids
    scene['pv_fields'][0]['modules_per_row'] = size
    string_template = deepcopy(design['strings'][0])
    design['strings'] = []
    for index, start in enumerate(range(0, size, 10)):
        string = deepcopy(string_template)
        string['string_id'] = f'08p1-string-{index:03d}'
        string['module_instance_ids'] = ids[start:start + 10]
        design['strings'].append(string)
    design['mppt_instances'][0]['connected_string_ids'] = [s['string_id'] for s in design['strings']]
    config['shading_configuration']['electrical_shading_configuration']['execution_options'].update(
        electrical_worker_count=1, attribution_worker_count=1)
    store = replace(store, scene_revisions={scene['revision_id']: scene},
        electrical_revisions={design['electrical_revision_id']: design},
        detailed_electrical_inputs=freeze_detailed_selection(bundle))
    return project, config, store, scene, design, bundle


# Times are inclusive and may overlap: never sum them as disjoint costs.
TARGETS = (
    ('engine.simulation.detailed_inputs', 'validate_assumption_authorization_witness', 'witness'),
    ('engine.simulation.detailed_inputs', 'validate_execution_transport', 'transport'),
    ('engine.simulation.detailed_backend', 'validate_execution_transport', 'transport'),
    ('shading.electrical.parameterization', 'validate_numerical_assumption_acceptance', 'b2_requests'),
    ('shading.electrical.parameterization', '_evaluate_numerical_candidate_physics', 'physics'),
    ('engine.simulation.detailed_backend', '_initialize_interval_worker', 'worker_initializations'),
    ('engine.simulation.detailed_attribution', '_initialize_attribution_worker', 'worker_initializations'),
    ('engine.simulation.detailed_backend', '_evaluate_interval', 'solver_intervals'),
    ('engine.simulation.detailed_backend', 'build_phase66_series_module_operating_model', 'module_interval_models'),
    ('engine.simulation.detailed_attribution', '_evaluate_attribution_interval', 'attribution_intervals'),
    ('engine.simulation.detailed_attribution', 'evaluate_independent_module_bases', 'attribution_module_intervals'),
    ('engine.simulation.artifacts', 'persist_run_package', 'persistence'),
    ('engine.simulation.detailed_dispatch', 'persist_run_package', 'persistence'),
    ('engine.simulation.artifacts', 'verify_run_package', 'package_verifier'),
)


def forwarding_wrapper(original, key, counts, seconds):
    @wraps(original)
    def forward(*args, **kwargs):
        label = 'fresh_b2_requests' if key == 'b2_requests' and kwargs.get('use_cache') is False else key
        counts[label] = counts.get(label, 0) + 1
        start = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            seconds[label] = seconds.get(label, 0.) + time.perf_counter() - start
    return forward


def cache_stats():
    from engine.simulation import detailed_inputs
    from shading.electrical import parameterization
    return {name: function.cache_info()._asdict() for name, function in (
        ('producer_physics', detailed_inputs._validated_producer_physics),
        ('candidate_physics', parameterization._cached_numerical_candidate))}


def clear_physics_caches():
    from engine.simulation import detailed_inputs
    from shading.electrical import parameterization
    detailed_inputs._validated_producer_physics.cache_clear()
    parameterization._cached_numerical_candidate.cache_clear()


def child_case(size, instrumented):
    # Enforced before numpy imports; BLAS threads are bounded by parent environment.
    signal.alarm(WALL_CAP_SECONDS)
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_MIB * 1024**2, MEMORY_MIB * 1024**2))
    setup_start = time.perf_counter()
    fixture = build_fixture(size)
    project, config, store, scene, design, bundle = fixture
    from tests.unit.test_phase69a_canonical_dispatch import _run
    from engine.simulation import artifacts
    clear_physics_caches()
    setup_seconds = time.perf_counter() - setup_start
    counts = {key: 0 for _, _, key in TARGETS}
    counts['fresh_b2_requests'] = 0
    seconds, runs = {}, []
    with tempfile.TemporaryDirectory(prefix='rb-08p1-') as directory, ExitStack() as stack:
        if instrumented:
            for module_name, name, key in TARGETS:
                module = importlib.import_module(module_name)
                stack.enter_context(patch.object(module, name, forwarding_wrapper(getattr(module, name), key, counts, seconds)))
        for temperature in ('cold_physics_cache', 'warm_physics_cache'):
            before_counts, before_seconds = dict(counts), dict(seconds)
            before_cache = cache_stats()
            wall, cpu = time.perf_counter(), time.process_time()
            result = _run(Path(directory), project, config, store, name=temperature)
            execution_wall = time.perf_counter() - wall
            execution_cpu = time.process_time() - cpu
            if result.summary_result is None or result.detailed_backend_result is None or result.detailed_attribution_result is None:
                raise RuntimeError(f'production execution failed: {result.simulation_run}')
            physical = result.detailed_backend_result.replay()
            if len(physical['intervals']) != 1:
                raise RuntimeError('expected exactly one interval')
            for diagnostic in physical['intervals'][0]['modules'].values():
                if sum(diagnostic['local_irradiance']['regions'][0]['unshaded_poa'].values()) <= 0:
                    raise RuntimeError('fixture is not daylight')
            run_counts = {k: counts.get(k, 0) - before_counts.get(k, 0) for k in set(counts) | set(before_counts)}
            run_seconds = {k: seconds.get(k, 0.) - before_seconds.get(k, 0.) for k in set(seconds) | set(before_seconds)}
            cache_after_run = cache_stats()
            verifier_counts_before = dict(counts)
            verify_wall, verify_cpu = time.perf_counter(), time.process_time()
            artifacts.verify_run_package(result.artifact_directory)
            verify_seconds = time.perf_counter() - verify_wall
            verify_cpu_seconds = time.process_time() - verify_cpu
            runs.append(dict(cache_state=temperature, execution_wall_seconds=execution_wall,
                execution_cpu_seconds=execution_cpu, verification_wall_seconds=verify_seconds,
                verification_cpu_seconds=verify_cpu_seconds,
                total_wall_seconds=execution_wall + verify_seconds,
                total_cpu_seconds=execution_cpu + verify_cpu_seconds,
                counts=run_counts if instrumented else None,
                inclusive_call_seconds=run_seconds if instrumented else None,
                independent_verification_counts={k: counts.get(k, 0) - verifier_counts_before.get(k, 0) for k in counts} if instrumented else None,
                cache_before=before_cache, cache_after_execution=cache_after_run,
                cache_after_verification=cache_stats()))
    evidence = next(iter(bundle['pinned_electrical_shading_assets']['electrical_parameterization_evidence'].values()))
    return dict(status='completed', size=size, instrumented=instrumented, setup_seconds=setup_seconds,
        process_lifetime_cpu_seconds=(resource.getrusage(resource.RUSAGE_SELF).ru_utime
                                      + resource.getrusage(resource.RUSAGE_SELF).ru_stime),
        peak_process_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        peak_child_process_mib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024,
        memory_basis='Linux process lifetime high-water RSS, not incremental allocation',
        measurement_labels={'timing': 'measured', 'counts': 'measured' if instrumented else 'unmeasured',
                            'worker_pool': 'unmeasured', 'cache_hits': 'measured cache_info counters'},
        assumption=evidence['assumption_declaration'],
        weather_timestamp=next(iter(store.weather_revisions.values())).series.index[0].isoformat(),
        runs=runs)


def practical_next(previous, next_size):
    if previous.get('status') != 'completed':
        return False
    # Both larger sizes rely on enforced case caps, not projections of fixed costs.
    return next_size in SIZES and next_size > previous['size']



def run_case(size):
    start = time.perf_counter()
    passes = []
    for mode in ('timing', 'counts'):
        remaining = WALL_CAP_SECONDS - (time.perf_counter() - start)
        if remaining <= 0:
            return dict(status='timeout', size=size, passes=passes)
        env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
        with tempfile.TemporaryFile(mode='w+') as output, tempfile.TemporaryFile(mode='w+') as errors:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--child', str(size), '--mode', mode],
                stdout=output, stderr=errors, env=env, start_new_session=True)
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                return dict(status='timeout', size=size, passes=passes, elapsed_seconds=time.perf_counter() - start)
            output.seek(0)
            transcript = output.read()
            errors.seek(0)
            stderr = errors.read()
        if process.returncode != 0:
            return dict(status='terminated', size=size, mode=mode, exit_code=process.returncode,
                diagnostic=(transcript + stderr)[-8000:], passes=passes, elapsed_seconds=time.perf_counter() - start)
        try:
            passes.append(json.loads(transcript.strip().splitlines()[-1]))
        except (ValueError, IndexError):
            return dict(status='invalid_child_output', size=size, diagnostic=(transcript + stderr)[-8000:], passes=passes)
    return dict(status='completed', size=size, passes=passes, elapsed_seconds=time.perf_counter() - start)


def scaling(case, baseline=None):
    if case['status'] != 'completed':
        return None
    size = case['size']
    timing, counted = case['passes']
    cold = counted['runs'][0]
    counts, seconds = cold['counts'], cold['inclusive_call_seconds']
    return dict(wall_seconds_per_module=timing['runs'][0]['execution_wall_seconds'] / size,
        backend_interval_inclusive_seconds_per_module=seconds.get('solver_intervals', 0.) / size,
        module_model_inclusive_seconds_per_module=seconds.get('module_interval_models', 0.) / size,
        witness_per_module=counts.get('witness', 0) / size,
        witness_per_module_interval=counts.get('witness', 0) / size,
        physics_per_distinct_assumption=counts.get('physics', 0), distinct_assumptions=1,
        peak_process_mib_per_module=timing['peak_process_mib'] / size,
        incremental_peak_mib_per_added_module=(
            (timing['peak_process_mib'] - baseline['passes'][0]['peak_process_mib']) / (size - 1)
            if size > 1 and baseline is not None and baseline['status'] == 'completed' else None),
        incremental_memory_basis='measured lifetime peak difference versus one module; includes run variability',
        projection_190_execution_seconds=timing['runs'][0]['execution_wall_seconds'] * 190 / size,
        projection_label='linear extrapolation only; no Huawei budget qualification',
        instrumented_to_uninstrumented_wall_ratio=cold['execution_wall_seconds'] / timing['runs'][0]['execution_wall_seconds'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', type=int, choices=SIZES, help=argparse.SUPPRESS)
    parser.add_argument('--mode', choices=('timing', 'counts'), default='timing', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child is not None:
        print(json.dumps(child_case(args.child, args.mode == 'counts')))
        return
    cases = []
    for size in SIZES:
        if cases and not practical_next(cases[-1], size):
            cases.append(dict(status='skipped', size=size, reason='preceding case did not complete safely', preceding_status=cases[-1]['status']))
            continue
        case = run_case(size)
        case['scaling'] = scaling(case, cases[0] if cases else None)
        cases.append(case)
    print(json.dumps(dict(baseline='65b8001', wall_cap_seconds=WALL_CAP_SECONDS,
        memory_ceiling_mib=MEMORY_MIB, intervals=1, workers=1, cases=cases), indent=2))


if __name__ == '__main__':
    main()
