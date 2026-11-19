"""D1 real kernel and diagnostic reporting contracts (no timing thresholds)."""
from tests.unit._availability import missing_git
import ast
import json
import math
from pathlib import Path
import subprocess

import numpy as np
import pvlib
import pytest

from scripts.benchmarks import rb_post3d_08p2d1_kernel as diagnostic
from shading.electrical.parameterization import ElectricalParameterizationError
from shading.electrical.substring_reference import SubstringReferenceError, solve_parallel_branches_at_current


_D1_RECORDED_COMMIT = "8251d37d71aff0bd9689d55a03ca6ea0383c4c8c"
_D1_GIT_REASON = missing_git()
if not _D1_GIT_REASON:
    _D1_CURRENT_HEAD = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=Path(diagnostic.__file__).resolve().parents[2], text=True,
    ).strip()
_HISTORICAL_D1_SCOPE = pytest.mark.skipif(
    bool(_D1_GIT_REASON) or _D1_CURRENT_HEAD != _D1_RECORDED_COMMIT,
    reason=_D1_GIT_REASON or f"historical D1 benchmark scope is valid only at commit 8251d37; current HEAD is {_D1_CURRENT_HEAD}",
)


@pytest.fixture(scope='module')
def report():
    return diagnostic.run(points=4, repeats=2)


def test_real_reference_and_scalar_array_semantics():
    state, voltage, _ = next(x for x in diagnostic.cases() if x[2]['layer'] == 'single_diode')
    scalar = diagnostic.raw_scalar([(state,voltage)])[0]
    array = diagnostic.raw_batch([(state,voltage)])
    assert isinstance(scalar, float)
    assert isinstance(array, np.ndarray) and array.shape == (1,)
    assert state.current_at_voltage(voltage) == max(0., scalar)
    comparison = diagnostic.compare([scalar], array)
    assert comparison['pairs'][0]['candidate_hex'] == float(array[0]).hex()


def test_case_completeness_and_real_boundary_execution(report):
    assert {'uniform','nonuniform','different_temperatures','low_irradiance','dark'} <= {
        c['category'] for c in report['cases']}
    assert {'near_short_circuit','near_open_circuit','reverse_domain','bypass_transition',
            'below_reverse_domain','nonfinite'} <= {c['boundary'] for c in report['cases']}
    assert all(c['fixture'] == diagnostic.FIXTURE for c in report['cases'])
    assert any(c['result']['exception'] == 'ElectricalParameterizationError' for c in report['cases'])
    assert any(c['layer'] == 'single_diode' and c['result']['exception'] is None for c in report['cases'])


def test_lossless_equality_signed_zero_and_one_ulp():
    assert diagnostic.compare([1.], [1.])['exact_equal']
    zeros = diagnostic.compare([0.], [-0.])
    assert not zeros['exact_equal']
    assert zeros['pairs'][0]['signed_zero_equal'] is False
    adjacent = float(np.nextafter(1., math.inf))
    comparison = diagnostic.compare([1.], [adjacent])
    assert comparison['max_ulp_difference'] == 1
    assert comparison['max_absolute_difference'] == adjacent-1.
    assert comparison['max_relative_difference'] == adjacent-1.
    with pytest.raises(ValueError):
        diagnostic.compare([1.], [])


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_nonfinite_reporting(value):
    for a,b in ((value,1.), (1.,value), (value,value)):
        comparison = diagnostic.compare([a],[b])
        assert not comparison['exact_equal']
        assert comparison['max_ulp_difference'] is None
        assert comparison['max_absolute_difference'] is None
        json.dumps(comparison, allow_nan=False)


def test_error_propagation_without_cache():
    state, _, _ = diagnostic.cases()[0]
    voltage = state.minimum_supported_voltage_v-1e-6
    with pytest.raises(ElectricalParameterizationError) as error:
        state.current_at_voltage(voltage)
    for _ in range(2):
        result = diagnostic.outcome(lambda: state.current_at_voltage(voltage))
        assert result == {'exception': 'ElectricalParameterizationError', 'message': str(error.value)}
    with pytest.raises(SubstringReferenceError) as branch_error:
        solve_parallel_branches_at_current([], {}, total_current_a=1.)
    result = diagnostic.outcome(lambda: solve_parallel_branches_at_current([], {}, total_current_a=1.))
    assert result['exception'] == 'SubstringReferenceError'
    assert result['message'] == str(branch_error.value)


def test_schema_and_bounded_counts(report):
    assert {'versions','fixtures','cases','equivalence','reference_timings','candidate_timings',
            'point_counts','timing_samples','peak_memory','limitations','status'} <= report.keys()
    assert report['status'] == 'completed' and report['production_eligible'] is False
    branch_points = report['branch_timed_points_per_sample']
    mechanisms = 2 + ('seconds' in report['candidate_timings']['private_dispatch'])
    assert report['point_counts']['timed'] == mechanisms*4*2 + 2*branch_points*2
    assert report['point_counts']['total_request_slots'] < 20000
    assert isinstance(report['peak_memory'], int)
    for timing in [report['reference_timings'], *report['candidate_timings'].values()]:
        if not timing.get('unavailable'):
            assert len(timing['seconds']) == 2 and timing['evaluated_points'] == 8
    json.dumps(report, allow_nan=False)
    for points,repeats in ((0,1),(257,1),(1,8)):
        with pytest.raises(ValueError):
            diagnostic.run(points,repeats)


def test_cli_success_failure_and_required_output(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        diagnostic.parser().parse_args([])
    output = tmp_path/'report.json'
    assert diagnostic.main(['--output',str(output),'--points','1','--repeats','1']) == 0
    assert json.loads(output.read_text())['status'] == 'completed'
    def fail(*args):
        raise RuntimeError('diagnostic failure')
    monkeypatch.setattr(diagnostic, 'run', fail)
    assert diagnostic.main(['--output',str(output)]) == 1
    assert json.loads(output.read_text())['error_type'] == 'RuntimeError'


def test_no_global_cache_or_library_mutation():
    before = (pvlib.pvsystem.i_from_v, np.exp)
    diagnostic.run(1,1)
    assert before == (pvlib.pvsystem.i_from_v, np.exp)
    assert not any(isinstance(value, dict) for key,value in vars(diagnostic).items()
                   if not key.startswith('__'))
    source = Path(diagnostic.__file__).read_text()
    tree = ast.parse(source)
    assert not any((isinstance(n, ast.Attribute) and n.attr in ('cache','lru_cache'))
                   or (isinstance(n, ast.Name) and n.id in ('cache','lru_cache'))
                   or (isinstance(n, ast.ImportFrom) and n.module == 'functools'
                       and any(a.name in ('cache','lru_cache') for a in n.names))
                   for n in ast.walk(tree))
    assert '_BranchEndpointHolder' not in source


@_HISTORICAL_D1_SCOPE
def test_historical_worktree_scope():
    root = Path(diagnostic.__file__).resolve().parents[2]
    result = subprocess.run(['git','status','--porcelain','--untracked-files=all'],
                            cwd=root, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr.decode()
    authorized = {'scripts/benchmarks/rb_post3d_08p2d1_kernel.py',
                  'tests/unit/test_rb_post3d_08p2d1_kernel_contract.py',
                  'docs/validation/rb_post3d_08p2d1_kernel_audit.md',
                  'docs/validation/rb_post3d_08p2d2a_batchability.md',
                  'scripts/benchmarks/rb_post3d_08p2d2a_batchability.py',
                  'tests/unit/test_rb_post3d_08p2d2a_contract.py'}
    # Orchestrator-owned ignored reports do not appear in porcelain output.
    assert {line[3:] for line in result.stdout.decode().splitlines()} <= authorized


def test_production_unchanged_and_no_authorization_bypass():
    source = Path(diagnostic.__file__).read_text()
    assert 'authorization_witness=' not in source
    assert 'evaluate_numerical_assumption_acceptance' not in source
    assert '_build_pvsyst_region_electrical_states' not in source
    # Fixture hashes are retained verbatim by normal validated public construction;
    # these synthetic v0.1 fixtures are not an authenticated production run.
    assert 'build_pvsyst_region_electrical_states(topology' in source
    assert 'payload_sha256] =' not in source


def test_branch_shaped_comparison_and_timings(report):
    records = report['branch_equivalence']
    assert len(records) == 6*3*3
    assert all(len(r['metadata']) == 2 for r in records)
    assert {r['metadata'][0]['substring_id'] for r in records} == {'s0','s1','s2'}
    for record in records:
        assert len({m['voltage_hex'] for m in record['metadata']}) == 1
        if 'comparison' in record:
            assert len(record['comparison']['pairs']) == 2
            assert all('metadata' in p and 'ulp_difference' in p
                       for p in record['comparison']['pairs'])
    for timing in report['branch_timings'].values():
        assert timing['points_per_sample'] == report['branch_timed_points_per_sample']
        assert len(timing['seconds']) == 2


def test_raw_candidate_boundary_error_and_nonfinite_records(report):
    for case in report['cases']:
        assert set(case['raw_candidates']) == {'public_batch','private_dispatch'}
        for record in case['raw_candidates'].values():
            for side in ('reference','candidate'):
                assert 'exception' in record[side]
                if record[side]['exception'] is not None:
                    assert isinstance(record[side]['message'], str)
        assert 'exception_equal' in case['mixed_batch']
    nan_case = next(c for c in report['cases']
                    if c['category'] == 'uniform' and c['boundary'] == 'nonfinite')
    for record in nan_case['raw_candidates'].values():
        if not record['candidate'].get('unavailable'):
            assert record['comparison']['pairs'][0]['candidate_class'] == 'nan'
    dark = next(c for c in report['cases'] if c['category'] == 'dark')
    assert dark['raw_candidates']['public_batch']['reference']['exception'] is not None
    assert dark['raw_candidates']['public_batch']['candidate']['exception'] is not None
    assert any(c['boundary'] == 'below_reverse_domain' and
               'comparison' in c['raw_candidates']['public_batch'] for c in report['cases'])


def test_bit_identity_separate_from_finiteness():
    pair = diagnostic.compare([math.inf], [math.inf])['pairs'][0]
    assert pair['bit_identical'] and not pair['exact_equal']
    assert not diagnostic.compare([0.], [-0.])['pairs'][0]['bit_identical']


def test_private_api_unavailability_keeps_public_diagnostic(monkeypatch):
    import pvlib.singlediode
    state, voltage, _ = diagnostic.cases()[0]
    monkeypatch.delattr(pvlib.singlediode, '_lambertw_i_from_v')
    # Exercise lazy candidate failure only: pvlib's public dispatcher itself
    # also uses that name internally, so removing it cannot model a working public API.
    result = diagnostic.raw_outcomes([(state, voltage)], 'private_dispatch')
    assert result['unavailable'] and result['exception'] == 'ImportError'
