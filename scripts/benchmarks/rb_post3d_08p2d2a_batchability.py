"""Bounded read-only D2-A observation. Never replaces production mathematics."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from importlib.metadata import version
import json
import math
from pathlib import Path
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pvlib
from shading.electrical import substring_reference as kernel
from shading.electrical.parameterization import PVSystRegionElectricalState
from scripts.benchmarks.rb_post3d_08p2d1_kernel import (
    cases, compare, raw_batch, raw_scalar, raw_outcomes, compare_outcomes,
)

SIZES = (1, 2, 3, 4, 6, 12)
LIMITATIONS = (
    'Synthetic Phase-6.6 fixtures, not manufacturer or annual validation.',
    'One protected module, three scenarios, at most four operating currents each; no string assembly.',
    'Only currents_at frames are independent groups. Protected reconstruction interleaves V(I) and is excluded.',
    'dc_attribution bypass-off generator and arbitrary external callables are outside observation scope.',
    'Profiling and Python memory tracing distort runtime; native memory is partly untracked.',
    'Groups are mathematical independence observations, not an admitted production batch boundary.',
    'Raw timing and parity exclude production guards; first-error ordering remains unproven.',
    'Groups larger than observed maximum are mechanism probes only; no end-to-end speedup.',
)


def trusted(state):
    # Exact type matches the source-backed frozen numerical law, never a name.
    return type(state) is PVSystRegionElectricalState and state.diode_parameters is not None


class Observation:
    def __init__(self, cap=4096):
        if not 1 <= cap <= 20000:
            raise ValueError('record cap must be 1..20000')
        self.cap = cap
        self.records = []
        self.groups = []
        self.active = []
        self.regional_calls = self.numerical_calls = self.overflow = 0
        self.guards = self.reverse_or_dark = self.ungrouped = 0
        self.excluded_callable_calls = 0

    def profile(self, frame, event, arg):
        if (frame.f_code.co_name == 'currents_at'
                and frame.f_code.co_filename == kernel.__file__):
            if event == 'call':
                group = {'id': len(self.groups), 'requests': [], 'completed': False,
                         'depends_on_prior_evaluation': 'low_currents' in frame.f_back.f_locals}
                if len(self.groups) < self.cap:
                    self.groups.append(group)
                else:
                    self.overflow += 1
                    group['overflowed'] = True
                self.active.append(group)
            elif event == 'return':
                self.active.pop()['completed'] = arg is not None

    @contextmanager
    def installed(self):
        if sys.getprofile() is not None:
            raise RuntimeError('diagnostic requires exclusive profiler ownership')
        original = PVSystRegionElectricalState.current_at_voltage
        numerical = pvlib.pvsystem.i_from_v
        current = []

        def scalar(*args, **kwargs):
            if current:
                record = current[-1]
                self.numerical_calls += 1
                record['numerical'] = True
                if not self.active:
                    self.ungrouped += 1
            return numerical(*args, **kwargs)

        def regional(state, voltage):
            self.regional_calls += 1
            record = {'region_id': state.region_id, 'voltage_hex': float(voltage).hex(),
                      'trusted': trusted(state), 'numerical': False, 'exception': None}
            if not trusted(state):
                self.excluded_callable_calls += 1
            if math.isfinite(voltage) and (voltage < 0 or state.isc_a <= 1e-12):
                self.reverse_or_dark += 1
            current.append(record)
            try:
                result = original(state, voltage)
                record['result_hex'] = float(result).hex()
                return result
            except Exception as exc:
                record.update(exception=type(exc).__name__, message=str(exc))
                self.guards += 1
                raise
            finally:
                current.pop()
                if len(self.records) < self.cap:
                    self.records.append(record)
                    if self.active and not self.active[-1].get('overflowed') and record['numerical']:
                        self.active[-1]['requests'].append(record)
                else:
                    self.overflow += 1

        PVSystRegionElectricalState.current_at_voltage = regional
        pvlib.pvsystem.i_from_v = scalar
        sys.setprofile(self.profile)
        try:
            yield self
        finally:
            sys.setprofile(None)
            pvlib.pvsystem.i_from_v = numerical
            PVSystRegionElectricalState.current_at_voltage = original

    def summary(self):
        sizes = [len(g['requests']) for g in self.groups if g['completed'] and
                 all(r['trusted'] and r['exception'] is None for r in g['requests'])]
        return {'total_regional_calls': self.regional_calls,
                'total_regional_numerical_calls': self.numerical_calls,
                'calls_in_independent_groups': sum(n for n in sizes if n > 1),
                'independent_group_distribution': {str(n): sizes.count(n) for n in (1, 2, 3)} |
                    {'4+': sum(n >= 4 for n in sizes)},
                'empty_groups': sizes.count(0),
                'maximum_independent_group_size': max(sizes, default=0),
                'sequentially_dependent_requests': sum(len(g['requests']) for g in self.groups
                    if g['depends_on_prior_evaluation']),
                'ungrouped_numerical_requests': self.ungrouped,
                'dependency_note': 'Each group is separate; its next voltage depends on previous summed currents.',
                'regional_guard_rejections': self.guards,
                'bypass_or_reverse_or_dark_calls': self.reverse_or_dark,
                'excluded_callable_calls': self.excluded_callable_calls,
                'uncaptured_or_overflowed_observations': self.overflow,
                'records': self.records, 'groups': self.groups}


def fixture(irradiance):
    from tests.unit.test_phase66_nonuniform_module_iv import _topology, _parameterization, _evidence, _handoff
    from shading.electrical.module_series_adapter import build_phase66_series_module_operating_model
    topology = _topology()
    definition = _parameterization(topology)
    mapping, local = _handoff(topology, irradiance_overrides=dict(zip(
        [r['region_id'] for r in topology['physical_regions']], irradiance)))
    return build_phase66_series_module_operating_model(
        topology, mapping, local, definition, _evidence(definition))


def observe(currents=2, cap=4096):
    observer = Observation(cap)
    models = []
    outputs = []
    # Model construction is outside observation: acceptance probes are not solver iterations.
    for irradiance in ((1000.,)*6, (1000., 200., 600.)*2, (0.,)*6):
        model = fixture(irradiance)
        models.append(model)
    with observer.installed():
        for model in models:
            for fraction in (.2, .5, .8, 1.)[:currents]:
                outputs.append(model.voltage_at_current(model.current_domain_ceiling_a * fraction))
    return observer.summary(), [m.model_id for m in models], outputs


def small_batches(inputs, repeats):
    forward = [(s, v) for s, v, m in inputs if m['layer'] == 'single_diode']
    results = []
    for size in SIZES:
        requests = [forward[i % len(forward)] for i in range(size)]
        parity = compare(raw_scalar(requests), raw_batch(requests))
        samples = []
        # Warm up both public paths. Array creation and extraction remain in total time.
        raw_scalar(requests)
        raw_batch(requests)
        for _ in range(repeats):
            start = time.perf_counter()
            raw_scalar(requests)
            scalar_elapsed = time.perf_counter() - start
            start = time.perf_counter()
            voltages = np.asarray([v for _, v in requests])
            parameters = np.asarray([s.diode_parameters for s, _ in requests]).T
            prepared = time.perf_counter()
            values = pvlib.pvsystem.i_from_v(voltages, *parameters, method='lambertw')
            calculated = time.perf_counter()
            [float(v) for v in values]
            extracted = time.perf_counter()
            samples.append({'scalar_seconds': scalar_elapsed, 'batch_seconds': extracted-start,
                'scalar_seconds_per_point': scalar_elapsed/size,
                'batch_seconds_per_point': (extracted-start)/size,
                'array_construction_seconds': prepared-start,
                'kernel_seconds': calculated-prepared,
                'result_extraction_seconds': extracted-calculated})
        results.append({'points': size, 'samples': samples, 'parity': parity,
                        'median_scalar_seconds': float(np.median([s['scalar_seconds'] for s in samples])),
                        'median_batch_seconds': float(np.median([s['batch_seconds'] for s in samples]))})
    return results


def failures(inputs):
    results = []
    # Retain all original regional guards and raw invalid-domain evidence.
    from scripts.benchmarks.rb_post3d_08p2d1_kernel import outcome
    for state, voltage, metadata in inputs:
        if metadata['boundary'] == 'interior' and metadata['category'] != 'dark':
            continue
        mixed = [(state, 0.), (state, voltage), (state, state.voc_v*.5)]
        reference = raw_outcomes(mixed, 'scalar')
        candidate = raw_outcomes(mixed, 'public_batch')
        record = compare_outcomes(reference, candidate, [dict(metadata, position=i) for i in range(3)])
        # Array dispatch cannot certify scalar first-failure position, even for same type/message.
        stopped_at = None
        executed = 0
        for index, request in enumerate(mixed):
            executed += 1
            if raw_outcomes([request], 'scalar')['exception'] is not None:
                stopped_at = index
                break
        record['scalar_first_error_position'] = stopped_at
        record['scalar_executed_request_slots'] = executed
        record['batch_first_error_position'] = None
        record['error_order_parity'] = None if reference['exception'] or candidate['exception'] else True
        record['regional'] = outcome(lambda: state.current_at_voltage(voltage))
        record['raw_applicable_to_production'] = metadata['layer'] == 'single_diode'
        results.append(record)
    return results


def run(currents=2, repeats=3, cap=4096):
    if not 1 <= currents <= 4 or not 1 <= repeats <= 7 or not 1 <= cap <= 20000:
        raise ValueError('bounded budgets: currents 1..4, repeats 1..7, records 1..20000')
    start = time.perf_counter()
    owned_trace = not tracemalloc.is_tracing()
    if owned_trace:
        tracemalloc.start()
    try:
        observation, models, _ = observe(currents, cap)
        inputs = cases()
        timings = small_batches(inputs, repeats)
        return {'schema_version': '1', 'status': 'completed',
            'versions': {k: version(k) for k in ('pvlib', 'numpy', 'scipy')},
            'fixtures': ['tests/unit/test_phase66_nonuniform_module_iv.py',
                         'components/reference/module-topology-uat-550.json'],
            'model_ids': models, 'workload': {'modules': 3, 'currents_per_module': currents,
                                            'repeats': repeats, 'record_cap': cap},
            'observation': observation, 'small_batches': timings, 'error_parity': failures(inputs),
            'runtime_seconds': time.perf_counter()-start,
            'peak_python_traced_bytes': tracemalloc.get_traced_memory()[1],
            'limitations': list(LIMITATIONS), 'production_eligible': False,
            'decision': 'BLOCKED: no validated ordered-error batch boundary; close batching for existing solver unless separately authorized evidence resolves this.'}
    finally:
        if owned_trace:
            tracemalloc.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--currents', type=int, default=2)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--records', type=int, default=4096)
    args = parser.parse_args(argv)
    try:
        report = run(args.currents, args.repeats, args.records)
        code = 0
    except Exception as exc:
        report = {'schema_version': '1', 'status': 'error', 'error_type': type(exc).__name__,
                  'error': str(exc), 'production_eligible': False, 'limitations': list(LIMITATIONS)}
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
