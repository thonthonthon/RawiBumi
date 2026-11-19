"""Read-only exact-work observer; no numerical result or authorization replacement."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BASELINE = '3873f0f'
LIMITATIONS = [
    'Counts are invocations, not disjoint timings or claimed savings.',
    'Cross-instance field comparisons retain provenance differences; candidates are not proven equivalent.',
    'Physical backend source inputs are not captured for physical-versus-B comparisons.',
    'Only the two harness physics caches are cleared; other process state may be warm.',
    'Scientific hashes alone do not prove cross-module physical equivalence.',
    'Overflow makes distinct/repeated counts lower bounds; totals remain exact.',
    'Observer covers the current thread; fixture requires one worker.',
]


def exact(value):
    """Lossless floats in diagnostic payloads, including signed zero."""
    if isinstance(value, float):
        return {'float.hex': value.hex()}
    if isinstance(value, dict):
        return {k: exact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [exact(v) for v in value]
    return value


def encoded(value):
    return json.dumps(exact(value), sort_keys=True, separators=(',', ':'), allow_nan=False)


class ByteBudget:
    """Global retained serialized-payload budget (container overhead is separately capped)."""
    def __init__(self, limit):
        self.limit, self.used, self.overflow = limit, 0, 0

    def reserve(self, payload):
        size = len(payload.encode('utf-8'))
        if self.used + size > self.limit:
            self.overflow += 1
            return False
        self.used += size
        return True


def field_differences(left, right, path=''):
    """Exact leaf comparison, preserving every field including provenance."""
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in sorted(left.keys() | right.keys()):
            child = path + '/' + key
            if key not in left or key not in right:
                result.append(child)
            else:
                result.extend(field_differences(left[key], right[key], child))
        return result
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [difference for i, (a, b) in enumerate(zip(left, right))
                for difference in field_differences(a, b, path + '/' + str(i))]
    return [] if left == right else [path]


class Assembly:
    def __init__(self, context, cap=4096, budget=None):
        self.budget = budget
        self.context, self.cap = context, cap
        self.currents, self.modules, self.previous_bypass = {}, {}, {}
        self.stages = Counter()
        self.total = self.overflow = self.module_total = self.module_repeats = 0
        self.module_overflow = self.changed_results = 0
        self.bypass_active = self.bypass_changes = self.negative_voltage = 0

    def current(self, current, stage):
        self.total += 1
        self.stages[stage] += 1
        key = float(current).hex()
        if key in self.currents:
            self.currents[key]['count'] += 1
            self.currents[key]['stages'][stage] += 1
        elif len(self.currents) < self.cap and (self.budget is None or self.budget.reserve(key)):
            self.currents[key] = {'count': 1, 'stages': Counter({stage: 1})}
        else:
            self.overflow += 1

    def module(self, model, current, tolerance, state):
        self.module_total += 1
        # Object identity is deliberately local to this assembly. No cross-model reuse.
        key = (id(model), float(current).hex(), float(tolerance).hex())
        payload = encoded(state)
        if key in self.modules:
            if self.modules[key] == payload:
                self.module_repeats += 1
            else:
                self.changed_results += 1
        elif (len(self.modules) < self.cap and len(payload) <= 16384
              and (self.budget is None or self.budget.reserve(payload))):
            self.modules[key] = payload
        else:
            self.module_overflow += 1
        flags = tuple(s['bypass_active'] for s in state['protected_substrings'])
        self.bypass_active += int(any(flags))
        self.negative_voltage += int(state['terminal_voltage_v'] < 0)
        identity = id(model)
        if identity in self.previous_bypass:
            self.bypass_changes += int(self.previous_bypass[identity] != flags)
        if identity in self.previous_bypass or len(self.previous_bypass) < self.cap:
            self.previous_bypass[identity] = flags

    def report(self):
        return dict(context=self.context, total_string_states=self.total,
                    distinct_exact_currents=len(self.currents),
                    repeated_exact_values=sum(v['count'] > 1 for v in self.currents.values()),
                    repeated_evaluations=sum(v['count'] - 1 for v in self.currents.values()),
                    exact_currents=self.currents, stages=dict(self.stages),
                    module_evaluations=self.module_total, repeated_full_module_states=self.module_repeats,
                    changed_results_at_identical_request=self.changed_results,
                    bypass_active_evaluations=self.bypass_active,
                    bypass_flag_changes_in_evaluation_order=self.bypass_changes,
                    negative_module_voltage_evaluations=self.negative_voltage,
                    current_overflow=self.overflow, module_overflow=self.module_overflow)


class Audit:
    """Profile real Python calls, including imported aliases, without wrapping results."""
    def __init__(self, assembly_cap=512, point_cap=4096, context_bytes=65536, payload_bytes=64 * 1024**2):
        self.budget = ByteBudget(payload_bytes)
        self.assembly_cap, self.point_cap, self.context_bytes = assembly_cap, point_cap, context_bytes
        self.counts, self.records = Counter(), []
        self.active = []
        self.skipped_assemblies = self.context_overflow = self.cache_hits = 0
        self.targets = {}
        for module_name, names in (
            ('string_iv', ('assemble_general_series_string_iv', '_solve_string_isc',
                           '_string_state_at_current', '_evaluate_module')),
            ('dc_attribution', ('optimize_independent_module', 'evaluate_independent_module_bases')),
            ('module_iv', ('_module_state_at_current', '_solve_module_isc')),
            ('substring_reference', ('_branch_current_at_voltage', '_branch_current_at_voltage_uncached',
                                     'evaluate_protected_substring_at_current')),
        ):
            module = importlib.import_module('shading.electrical.' + module_name)
            for name in names:
                self.targets[getattr(module, name).__code__] = module_name + '.' + name

    def context(self, frame):
        local = frame.f_locals
        context = {'basis': 'physical', 'solver': {k: local[k] for k in
                   ('sample_count', 'voltage_tolerance_v', 'current_tolerance_a', 'max_iterations')},
                   'models': [{'instance': m.module_instance_id, 'scientific_input_sha256': m.scientific_input_sha256,
                               'model_id': m.model_id, 'model_version': m.model_version,
                               'ceiling_a': m.current_domain_ceiling_a} for m in local['module_models'].values()]}
        parent = frame.f_back
        while parent is not None:
            if parent.f_code.co_name == 'evaluate_independent_module_bases':
                values = parent.f_locals
                context['basis'] = values['name']
                context['interval'] = {k: values['local'].get(k) for k in
                                       ('interval_start', 'evaluation_time')}
                # Capture complete source inputs. No invented normalized equivalence hash.
                physical = encoded({'pinned': values['pinned'], 'region_map': values['region_map'],
                                    'local': values.get('state', values['local']) if values['name'] != 'N' else values['local'],
                                    'region_solver': values['region_solver']})
                if len(physical) <= self.context_bytes and self.budget.reserve(physical):
                    context['complete_source_inputs_exact_json'] = physical
                else:
                    self.context_overflow += 1
                break
            parent = parent.f_back
        return exact(context)

    def observe(self, frame, event, arg):
        target = self.targets.get(frame.f_code)
        if target is None:
            return
        name = frame.f_code.co_name
        if event == 'call':
            self.counts[target] += 1
            if name == 'assemble_general_series_string_iv':
                record = None
                if len(self.records) < self.assembly_cap:
                    record = Assembly(self.context(frame), self.point_cap, self.budget)
                    self.records.append(record)
                else:
                    self.skipped_assemblies += 1
                self.active.append(record)
            elif name == '_string_state_at_current' and self.active and self.active[-1]:
                caller = frame.f_back
                if caller.f_code.co_name == '_solve_string_isc':
                    stage = 'isc_bisection' if 'mid' in caller.f_locals else 'isc_endpoint'
                else:
                    stage = 'sampling' if 'index' in caller.f_locals else 'voc'
                self.active[-1].current(frame.f_locals['current_a'], stage)
        elif event == 'return':
            if name == '_branch_current_at_voltage' and isinstance(arg, (int, float)):
                values = frame.f_locals
                slot, key = values.get('slot'), values.get('key')
                if slot is not None and key in slot.currents and 'value' not in values:
                    self.cache_hits += 1
            if name == '_evaluate_module' and self.active and self.active[-1] and isinstance(arg, dict):
                values = frame.f_locals
                self.active[-1].module(values['model'], values['current_a'], values['current_tolerance_a'], arg)
            elif name == 'assemble_general_series_string_iv':
                record = self.active.pop()
                if record:
                    record.context['completion'] = 'completed' if arg is not None else 'rejected'

    @contextmanager
    def installed(self):
        if sys.getprofile() is not None:
            raise RuntimeError('another profiler is installed; refusing to replace it')
        sys.setprofile(self.observe)
        try:
            yield self
        finally:
            sys.setprofile(None)
            self.active.clear()

    def report(self):
        requests = self.counts['substring_reference._branch_current_at_voltage']
        misses = self.counts['substring_reference._branch_current_at_voltage_uncached']
        groups = {}
        for index, record in enumerate(self.records):
            # Exact complete context comparison only. Never compare scientific hashes alone.
            context = record.context
            if 'complete_source_inputs_exact_json' in context:
                key = encoded({k: v for k, v in context.items() if k != 'completion'})
                groups.setdefault(key, []).append(index)
        # Compare each module to the first captured module at the same interval/basis.
        # Linear bounded output, not quadratic all-pairs payload duplication. No hash
        # normalization or inference that different provenance means different physics.
        anchors, comparisons = {}, []
        for index, record in enumerate(self.records):
            context = record.context
            if 'complete_source_inputs_exact_json' not in context:
                continue
            key = encoded({'basis': context['basis'], 'interval': context['interval']})
            if key not in anchors:
                anchors[key] = index
                continue
            anchor = anchors[key]
            previous = self.records[anchor].context
            if previous['models'][0]['instance'] == context['models'][0]['instance']:
                continue
            differences = field_differences(
                json.loads(previous['complete_source_inputs_exact_json']),
                json.loads(context['complete_source_inputs_exact_json']), '/source_inputs')
            differences += field_differences(previous['solver'], context['solver'], '/solver')
            differences += field_differences(previous['models'], context['models'], '/models')
            comparisons.append({'assemblies': [anchor, index], 'basis': context['basis'],
                'interval': context['interval'], 'differing_fields': differences,
                'all_unlisted_fields_equal_exactly': True, 'status': 'candidate, not proven'})
        return dict(source_function_counts=dict(self.counts), assemblies=[r.report() for r in self.records],
                    repetition_distribution=dict(Counter(str(sum(v['count'] - 1 for v in r.currents.values()))
                                                         for r in self.records)),
                    cache_reuse={'branch_requests': requests, 'uncached_invocations': misses,
                                 'actual_cache_hit_returns': self.cache_hits,
                                 'apparent_hits_from_request_minus_uncached': requests - misses,
                                 'scope': 'B2 model-local branch holder; no shared module-state cache'},
                    exact_complete_context_repeat_groups=[v for v in groups.values() if len(v) > 1],
                    potential_cross_module_equivalence_groups=comparisons,
                    cross_module_equivalence_status='not_proven; per-field cross-instance evidence reported',
                    retained_payload_bytes=self.budget.used, payload_byte_limit=self.budget.limit,
                    payload_budget_overflow=self.budget.overflow,
                    absent_electrical_stages={'mpp_candidate_evaluation': 0, 'candidate_refinement': 0,
                                              'final_operating_state_reconstruction': 0},
                    skipped_assemblies=self.skipped_assemblies, context_overflow=self.context_overflow,
                    evidence_limitations=LIMITATIONS)


def fingerprints(result):
    if result.detailed_backend_result is None or result.detailed_attribution_result is None:
        raise RuntimeError('authenticated Level-2 execution did not complete')
    # Entire scientific/provenance streams, not wall time or run-directory metadata.
    return {name: hashlib.sha256(encoded(stream.replay()).encode()).hexdigest() for name, stream in (
        ('backend', result.detailed_backend_result), ('attribution', result.detailed_attribution_result))}


def child(size):
    signal.alarm(600)
    resource.setrlimit(resource.RLIMIT_AS, (4096 * 1024**2, 4096 * 1024**2))
    from scripts.benchmarks.rb_post3d_08p1 import build_fixture, clear_physics_caches
    from tests.unit.test_phase69a_canonical_dispatch import _run
    from engine.simulation.artifacts import verify_run_package
    project, config, store, *_ = build_fixture(size)
    audit = Audit()
    with tempfile.TemporaryDirectory(prefix='rb-c3a-') as directory:
        clear_physics_caches()
        control = _run(Path(directory) / 'control', project, config, store, name='c3a')
        control_hashes = fingerprints(control)
        verify_run_package(control.artifact_directory)
        clear_physics_caches()
        with audit.installed():
            observed = _run(Path(directory) / 'observed', project, config, store, name='c3a')
        observed_hashes = fingerprints(observed)
        verify_run_package(observed.artifact_directory)
    equal = control_hashes == observed_hashes
    return dict(baseline_commit=BASELINE, workload_size=size,
                completion_status='completed' if equal else 'fingerprint_mismatch',
                output_fingerprints_unchanged=equal, control_fingerprints=control_hashes,
                observed_fingerprints=observed_hashes, **audit.report())


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--size', type=int, choices=(10, 50), default=10)
    result.add_argument('--output', type=Path, required=True)
    result.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    return result


def main():
    args = parser().parse_args()
    if args.child:
        args.output.write_text(json.dumps(child(args.size), indent=2) + '\n')
        return
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    with tempfile.TemporaryDirectory(prefix='rb-c3a-child-') as directory:
        output = Path(directory) / 'audit.json'
        try:
            with tempfile.TemporaryFile() as transcript:
                completed = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                    '--child', '--size', str(args.size), '--output', str(output)],
                    env=env, stdout=transcript, stderr=transcript, timeout=600)
                transcript.seek(0, 2)
                length = transcript.tell()
                transcript.seek(max(0, length - 8000))
                detail = transcript.read().decode(errors='replace')
            report = json.loads(output.read_text()) if completed.returncode == 0 else dict(
                completion_status='blocked', blocker='diagnostic child failed', exit_code=completed.returncode,
                diagnostic=detail)
        except subprocess.TimeoutExpired:
            report = dict(completion_status='blocked', blocker='600-second execution budget exhausted')
    report.update(baseline_commit=BASELINE, workload_size=args.size)
    report.setdefault('evidence_limitations', LIMITATIONS)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    if report['completion_status'] != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
