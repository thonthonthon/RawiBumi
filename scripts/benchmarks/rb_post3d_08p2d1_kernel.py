"""Bounded D1 diagnostics; no production optimization or global numerical cache."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import struct
import sys
import time
import tracemalloc
from importlib.metadata import version

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pvlib

MAX_POINTS = 256
MAX_REPEATS = 7
FIXTURE = 'tests/unit/test_phase66_nonuniform_module_iv.py'
LIMITATIONS = (
    'Synthetic executable regional fixtures; no manufacturer validation or pilot qualification.',
    'Raw pvlib comparisons do not certify regional guards, branch errors, or scientific fingerprints.',
    'Private dispatcher bypass is compatibility-risky and retains NumPy wrapper allocations.',
    'Batching is diagnostic only; adaptive iterations are sequential and arbitrary callables cannot be batched.',
    'No B2 holder is used or modified. Timings are uncached kernel requests, not full-simulation speedups.',
    'No production eligibility until boundary/error/call-order parity and end-to-end benefit are established.',
)


def compare(reference, candidate):
    """Lossless binary64 comparison; nonfinite differences remain unavailable."""
    pairs = []
    for a, b in zip(reference, candidate, strict=True):
        a, b = float(a), float(b)
        finite = math.isfinite(a) and math.isfinite(b)
        def ordered(x):
            bits = struct.unpack('>Q', struct.pack('>d', x))[0]
            return (~bits & ((1 << 64) - 1)) if bits >> 63 else bits | (1 << 63)
        pairs.append({'reference_hex': a.hex(), 'candidate_hex': b.hex(),
                      'reference_class': classify(a), 'candidate_class': classify(b),
                      'exact_equal': finite and a.hex() == b.hex(),
                      'bit_identical': struct.pack('>d', a) == struct.pack('>d', b),
                      'signed_zero_equal': (math.copysign(1, a) == math.copysign(1, b))
                          if a == b == 0 else None,
                      'absolute_difference': abs(a-b) if finite else None,
                      'relative_difference': (abs(a-b)/abs(a) if a else (0.0 if b == 0 else None))
                          if finite else None,
                      'ulp_difference': abs(ordered(a)-ordered(b)) if finite else None})
    def maximum(key):
        return max((p[key] for p in pairs if p[key] is not None), default=None)
    return {'exact_equal': all(p['exact_equal'] for p in pairs), 'pairs': pairs,
            'max_absolute_difference': maximum('absolute_difference'),
            'max_relative_difference': maximum('relative_difference'),
            'max_ulp_difference': maximum('ulp_difference')}


def classify(x):
    return 'nan' if math.isnan(x) else ('positive_infinity' if x == math.inf else
           'negative_infinity' if x == -math.inf else 'finite')


def cases():
    from tests.unit.test_phase66_nonuniform_module_iv import _topology, _parameterization, _evidence, _handoff
    from shading.electrical.parameterization import build_pvsyst_region_electrical_states
    topology = _topology()
    parameterization = _parameterization(topology)
    result = []
    for category, irradiances, temperature in (
        ('uniform', (1000.,)*6, 25.), ('nonuniform', (1000.,200.,600.)*2, 25.),
        ('different_temperatures', (1000.,)*6, 45.), ('cold_temperature', (1000.,)*6, 15.),
        ('low_irradiance', (100.,)*6, 25.), ('dark', (0.,)*6, 25.)):
        ids = [r['region_id'] for r in topology['physical_regions']]
        mapping, local = _handoff(topology, irradiance_overrides=dict(zip(ids, irradiances)))
        local['module_temperature_c'] = temperature
        states = build_pvsyst_region_electrical_states(topology, mapping, local,
                                                      parameterization, _evidence(parameterization))
        for state in states.values():
            # The topology's constant bypass diode clamp is -0.55 V.
            for boundary, voltage in (
                ('near_short_circuit', 0.0), ('interior', state.voc_v * .5),
                ('near_open_circuit', state.voc_v), ('above_open_circuit', state.voc_v + 1e-8),
                ('reverse_domain', max(state.minimum_supported_voltage_v, -.1)),
                ('bypass_transition', -.55),
                ('below_reverse_domain', state.minimum_supported_voltage_v - 1e-6),
                ('nonfinite', math.nan)):
                layer = 'single_diode' if (math.isfinite(voltage) and 0 <= voltage <= state.voc_v
                                         and state.isc_a > 1e-12) else 'regional_guard_or_linear_reverse'
                result.append((state, voltage, {'category': category, 'boundary': boundary,
                    'layer': layer, 'region_id': state.region_id, 'voltage_hex': voltage.hex(),
                    'irradiance_w_m2': state.effective_irradiance_w_m2,
                    'temperature_c': state.cell_temperature_c, 'fixture': FIXTURE,
                    'bypass_note': 'regional clamp query only; no protected transition certification'}))
    return result


def outcome(function):
    try:
        value = float(function())
        return {'value_hex': value.hex(), 'class': classify(value), 'exception': None}
    except Exception as exc:
        return {'exception': type(exc).__name__, 'message': str(exc)}


def raw_scalar(requests, private=False):
    if private:
        from pvlib.singlediode import _lambertw_i_from_v
        function = _lambertw_i_from_v
    else:
        function = pvlib.pvsystem.i_from_v
    return [function(v, *s.diode_parameters) if private else
            function(v, *s.diode_parameters, method=s.solver) for s, v in requests]


def raw_batch(requests):
    voltages = np.asarray([v for _, v in requests])
    parameters = np.asarray([s.diode_parameters for s, _ in requests]).T
    return pvlib.pvsystem.i_from_v(voltages, *parameters, method='lambertw')


def measure(function, repeats, points):
    function()  # One discarded warm-up, included in point counts.
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        samples.append(time.perf_counter()-start)
    return {'seconds': samples, 'min_seconds': min(samples),
            'median_seconds': float(np.median(samples)), 'max_seconds': max(samples),
            'warmup_points': points, 'evaluated_points': points * repeats, 'points_per_sample': points,
            'median_seconds_per_point': float(np.median(samples))/points}


def raw_outcomes(requests, mechanism):
    """Capture raw-layer errors without imposing the regional guard semantics."""
    function = raw_batch if mechanism == 'public_batch' else (
        lambda items: raw_scalar(items, private=mechanism == 'private_dispatch'))
    try:
        values = function(requests)
        return {'exception': None, 'outcomes': [outcome(lambda v=v: v) for v in values]}
    except ImportError as exc:
        return {'exception': type(exc).__name__, 'message': str(exc), 'unavailable': True}
    except Exception as exc:
        return {'exception': type(exc).__name__, 'message': str(exc)}


def compare_outcomes(reference, candidate, metadata):
    record = {'metadata': metadata, 'reference': reference, 'candidate': candidate}
    record['exception_equal'] = (reference.get('exception'), reference.get('message')) == (
        candidate.get('exception'), candidate.get('message'))
    if reference.get('outcomes') is not None and candidate.get('outcomes') is not None:
        comparison = compare([float.fromhex(x['value_hex']) for x in reference['outcomes']],
                             [float.fromhex(x['value_hex']) for x in candidate['outcomes']])
        for pair, label in zip(comparison['pairs'], metadata, strict=True):
            pair['metadata'] = label
        record['comparison'] = comparison
    return record


def branch_groups(inputs):
    """Only single-region branches at one shared voltage; no adaptive reordering."""
    from tests.unit.test_phase66_nonuniform_module_iv import _topology
    topology = _topology()
    categories = list(dict.fromkeys(m['category'] for _, _, m in inputs))
    for category in categories:
        states = {s.region_id: s for s, _, m in inputs if m['category'] == category}
        for substring in topology['electrical_substrings']:
            regions = []
            for branch in substring['parallel_branches']:
                if len(branch['series_region_ids']) != 1:
                    raise ValueError('diagnostic requires single-region branches')
                regions.append(states[branch['series_region_ids'][0]])
            # Shared forward probes inside the common regional forward domain.
            for boundary, voltage in (('near_short_circuit', 0.),
                                      ('interior', min(s.voc_v for s in regions)*.5),
                                      ('near_open_circuit', min(s.voc_v for s in regions))):
                metadata = [{'category': category, 'boundary': boundary,
                             'substring_id': substring['substring_id'],
                             'region_id': s.region_id, 'voltage_hex': voltage.hex()}
                            for s in regions]
                yield [(s, voltage) for s in regions], metadata


def _run(points, repeats):
    inputs = cases()
    forward = [(s,v,m) for s,v,m in inputs if m['layer'] == 'single_diode']
    selected = [forward[i % len(forward)] for i in range(points)]
    requests = [(s,v) for s,v,_ in selected]
    reference = raw_scalar(requests)
    batch = raw_batch(requests)
    private_available = not raw_outcomes(requests[:1], 'private_dispatch').get('unavailable', False)
    equivalence = {'public_batch': compare(reference, batch)}
    if private_available:
        equivalence['private_dispatch'] = compare(reference, raw_scalar(requests, True))
    else:
        equivalence['private_dispatch'] = {'unavailable': True}
    for comparison in equivalence.values():
        for pair, (_,_,metadata) in zip(comparison.get('pairs', []), selected):
            pair['metadata'] = metadata
    boundaries = []
    raw_attempts = 0
    for state, voltage, metadata in inputs:
        request = [(state, voltage)]
        scalar = raw_outcomes(request, 'scalar')
        candidates = {}
        for mechanism in ('public_batch', 'private_dispatch'):
            candidate = raw_outcomes(request, mechanism)
            candidates[mechanism] = compare_outcomes(scalar, candidate, [metadata])
        # Mixed valid/boundary/valid array reveals whole-array failures and NaN masking.
        mixed = [(state, 0.), (state, voltage), (state, state.voc_v*.5)]
        scalar_sequence = raw_outcomes(mixed, 'scalar')
        mixed_batch = raw_outcomes(mixed, 'public_batch')
        boundaries.append(dict(metadata,
            result=outcome(lambda s=state,v=voltage: s.current_at_voltage(v)),
            raw_candidates=candidates,
            mixed_batch=compare_outcomes(scalar_sequence, mixed_batch,
                [dict(metadata, position=i, voltage_hex=v.hex()) for i,(_,v) in enumerate(mixed)]),
            error_order_note='Scalar sequence stops at first error; array preparation may fail before any kernel call.'))
        raw_attempts += 9  # Request slots submitted, including whole-call failures.
    shaped = []
    timed_groups = []
    for requests_at_voltage, metadata in branch_groups(inputs):
        scalar = raw_outcomes(requests_at_voltage, 'scalar')
        candidate = raw_outcomes(requests_at_voltage, 'public_batch')
        shaped.append(compare_outcomes(scalar, candidate, metadata))
        if scalar['exception'] is None and candidate['exception'] is None:
            timed_groups.append(requests_at_voltage)
    branch_points = sum(len(group) for group in timed_groups)
    reference_timing = measure(lambda: raw_scalar(requests), repeats, points)
    candidates = {'public_batch': measure(lambda: raw_batch(requests), repeats, points)}
    if private_available:
        candidates['private_dispatch'] = measure(lambda: raw_scalar(requests, True), repeats, points)
    else:
        candidates['private_dispatch'] = {'unavailable': True}
    branch_timings = {
        'scalar_sequence': measure(lambda: [raw_scalar(g) for g in timed_groups], repeats, branch_points),
        'public_batch': measure(lambda: [raw_batch(g) for g in timed_groups], repeats, branch_points)}
    mechanisms = 3 if private_available else 2
    counts = {'per_sample': points, 'repeats': repeats,
              'raw_comparison': mechanisms*points, 'regional_boundary': len(inputs),
              'boundary_raw_request_slots': raw_attempts,
              'branch_comparison_request_slots': sum(2*len(r['metadata']) for r in shaped),
              'timed': mechanisms*points*repeats + 2*branch_points*repeats,
              'warmup': mechanisms*points + 2*branch_points,
              'availability_probe_request_slots': 1}
    counts['total_request_slots'] = sum(counts[k] for k in (
        'raw_comparison', 'regional_boundary', 'boundary_raw_request_slots',
        'branch_comparison_request_slots', 'timed', 'warmup', 'availability_probe_request_slots'))
    return {'schema_version': '1', 'status': 'completed',
        'versions': {k: version(k) for k in ('pvlib','numpy','scipy')},
        'fixtures': [FIXTURE, 'components/reference/module-topology-uat-550.json'],
        'cases': boundaries, 'equivalence': equivalence,
        'branch_equivalence': shaped, 'branch_timings': branch_timings,
        'branch_timed_points_per_sample': branch_points,
        'output_semantics': {'scalar': type(reference[0]).__name__, 'batch': type(batch).__name__,
                             'batch_shape': list(batch.shape)},
        'reference_timings': reference_timing, 'candidate_timings': candidates,
        'point_counts': counts, 'timing_samples': repeats,
        'point_counts_note': 'Request slots include failed calls; failed scalar sequences may stop early. Timing counts are successful evaluated points.',
        'limitations': list(LIMITATIONS), 'production_eligible': False}


def run(points=128, repeats=3):
    if not 1 <= points <= MAX_POINTS or not 1 <= repeats <= MAX_REPEATS:
        raise ValueError('budget exceeds bounded diagnostic limits')
    owned_trace = not tracemalloc.is_tracing()
    if owned_trace:
        tracemalloc.start()
    try:
        report = _run(points, repeats)
        report['peak_memory'] = tracemalloc.get_traced_memory()[1]
        report['peak_memory_note'] = ('Python traced bytes; excludes some native allocations. '
            'Tracing affects timings; an existing caller trace may include earlier allocations.')
        return report
    finally:
        if owned_trace:
            tracemalloc.stop()


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--points', type=int, choices=range(1,MAX_POINTS+1), default=128)
    p.add_argument('--repeats', type=int, choices=range(1,MAX_REPEATS+1), default=3)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        report = run(args.points, args.repeats)
        code = 0
    except Exception as exc:
        report = {'schema_version': '1', 'status': 'error', 'error_type': type(exc).__name__,
                  'error': str(exc), 'limitations': list(LIMITATIONS)}
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
