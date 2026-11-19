"""Bounded synthetic E1 contracts. No fixture build or 10/50-module simulation."""
from tests.unit._availability import missing_git, missing_private_path
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import tracemalloc
from types import CodeType, SimpleNamespace

import pytest
from scripts.benchmarks import rb_post3d_08p2e1_root_work as bench

_GIT_REASON = missing_git()
if not _GIT_REASON:
    _CURRENT_HEAD = bench.git('rev-parse', 'HEAD')
_HISTORICAL_E1 = pytest.mark.skipif(
    bool(_GIT_REASON) or _CURRENT_HEAD != bench.BASE_COMMIT,
    reason=_GIT_REASON or f"historical E1 benchmark evidence is valid only at commit 3508f7f; current HEAD is {_CURRENT_HEAD}",
)

ALLOWED = {'.ai/TASK.md', 'scripts/benchmarks/rb_post3d_08p2e1_root_work.py',
           'tests/unit/test_rb_post3d_08p2e1_contract.py',
           'docs/validation/rb_post3d_08p2e1_root_work.md'}


@_HISTORICAL_E1
def test_authorized_scope_committed_and_worktree():
    def paths(*args):
        return set(subprocess.check_output(['git', *args], cwd=bench.ROOT).decode().split('\0')) - {''}
    assert (paths('diff', '--name-only', '-z', bench.BASE, 'HEAD') |
            paths('diff', '--name-only', '-z', bench.BASE) |
            paths('ls-files', '--others', '--exclude-standard', '-z')) <= ALLOWED


def options(**changes):
    return SimpleNamespace(**(dict(modules=10, intervals=1, workers=1, wall_cap_seconds=2,
        memory_limit_mib=4096, focused_trace=False, mode='counts', child=False,
        measurement_mode='both', cache_state='both', compare_baseline=None, compare_counts=None) | changes))


@pytest.mark.parametrize('change', [dict(modules=1), dict(modules=190), dict(intervals=2),
    dict(workers=2), dict(wall_cap_seconds=901), dict(wall_cap_seconds=0),
    dict(wall_cap_seconds=float('nan')), dict(wall_cap_seconds=float('inf')),
    dict(memory_limit_mib=4097), dict(memory_limit_mib=0)])
def test_reject_unbounded_controls(change):
    with pytest.raises(ValueError):
        bench.controls(options(**change))


@pytest.mark.parametrize('modules', [10, 50])
def test_supported_controls_without_execution(modules):
    bench.controls(options(modules=modules))
    assert bench.parser().parse_args(['--output', 'unused.json']).workers == 1


@pytest.fixture
def evidence(monkeypatch, tmp_path):
    # Synthetic report tests use a temporary stand-in for the authorized root.
    monkeypatch.setattr(bench, 'EVIDENCE', tmp_path / 'evidence')
    bench.EVIDENCE.mkdir()
    return bench.EVIDENCE


def test_output_rejected_before_any_work(monkeypatch, evidence, tmp_path):
    monkeypatch.setattr(sys, 'argv', ['e1', '--output', str(tmp_path / 'outside.json')])
    monkeypatch.setattr(bench, 'parent', lambda *a: pytest.fail('parent ran'))
    with pytest.raises(ValueError, match='inside'):
        bench.main()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (evidence / 'escape').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='inside'):
        bench.validate_output(evidence / 'escape' / 'x.json')
    (evidence / 'taken.json').write_text('{}')
    with pytest.raises(ValueError, match='already exists'):
        bench.validate_output(evidence / 'taken.json')
    (evidence / 'side.json.sha256').symlink_to(tmp_path / 'outside.sha256')
    with pytest.raises(ValueError, match='inside'):
        bench.validate_output(evidence / 'side.json')
    assert bench.validate_output(evidence / 'new.json') == evidence / 'new.json'


def counts(observer, suffix):
    return sum(v for values in observer.counters.values() for key, v in values.items() if key.endswith(suffix))


@pytest.mark.parametrize('mode', ['counts', 'trace'])
def test_stateful_order_exception_identity_accounting_and_restore(mode):
    seen = []
    error = ValueError('original')
    def callback(value):
        seen.append(value)
        if value == 3:
            raise error
        return (
            value
        )
    old = sys.getprofile(), sys.gettrace()
    observer = bench.Observer(mode, targets={callback.__code__})
    with pytest.raises(ValueError) as exc:
        with observer.installed():
            assert [callback(i) for i in (2, 1, 2)] == [2, 1, 2]
            callback(3)
    assert exc.value is error
    assert seen == [2, 1, 2, 3]
    assert (sys.getprofile(), sys.gettrace()) == old
    assert counts(observer, ':calls') == counts(observer, ':returns_or_unwinds') == 4
    assert not observer.active and not observer.trace_state and observer.phase == 'setup'
    if mode == 'trace':
        assert counts(observer, ':propagated_failure:ValueError') == 1
        assert counts(observer, ':return_opcodes') == 3


@pytest.mark.parametrize('hook', ['profile', 'trace', 'tracemalloc'])
def test_existing_hooks_fail_closed(hook):
    def sentinel(*args):
        return sentinel
    old_profile, old_trace = sys.getprofile(), sys.gettrace()
    try:
        if hook == 'tracemalloc':
            tracemalloc.start()
        else:
            (sys.setprofile if hook == 'profile' else sys.settrace)(sentinel)
        with pytest.raises(RuntimeError, match='exclusive'):
            with bench.Observer('trace').installed():
                pytest.fail('hook overwritten')
        if hook == 'tracemalloc':
            assert tracemalloc.is_tracing()
        else:
            assert (sys.getprofile if hook == 'profile' else sys.gettrace)() is sentinel
    finally:
        sys.setprofile(old_profile)
        sys.settrace(old_trace)
        if hook == 'tracemalloc':
            tracemalloc.stop()


def test_unrelated_events_do_not_spend_cap():
    def selected():
        return 1
    def unrelated():
        return sum(range(10))
    observer = bench.Observer(cap=2, targets={selected.__code__})
    with observer.installed():
        for _ in range(100):
            unrelated()
        assert selected() == 1
    assert observer.events == 2 and not observer.overflow
    assert counts(observer, ':calls') == counts(observer, ':returns_or_unwinds') == 1


def test_high_volume_events_have_fixed_retained_state():
    def selected():
        return 1
    observer = bench.Observer(targets={selected.__code__})
    with observer.installed():
        selected()
        keys = observer.counter_keys
        for _ in range(1_700_000):
            selected()
    # Exceeds both the rejected two-million limit and the supplied 3.39M evidence.
    assert observer.events == 3_400_002 and not observer.overflow and observer.cap is None
    assert counts(observer, ':calls') == counts(observer, ':returns_or_unwinds') == 1_700_001
    assert observer.counter_keys == keys == 3 and len(observer.plans) == 1
    assert not observer.active and not observer.trace_state
    assert (sys.getprofile(), sys.gettrace()) == (None, None)


@pytest.mark.parametrize('bound', ['keys', 'key_length', 'frames'])
@pytest.mark.parametrize('mode', ['counts', 'trace'])
def test_retained_state_bounds_fail_closed(monkeypatch, bound, mode):
    def target(depth=2):
        if depth:
            return target(depth - 1)
        return 1
    observer = bench.Observer(mode, targets={target.__code__})
    attribute, limit = {'keys': ('MAX_COUNTER_KEYS', 1), 'key_length': ('MAX_KEY_LENGTH', 1),
                        'frames': ('MAX_ACTIVE_FRAMES', 1)}[bound]
    monkeypatch.setattr(observer, attribute, limit)
    with pytest.raises(bench.ObservationOverflow):
        with observer.installed():
            target()
    assert observer.overflow and observer.overflow_reason
    assert observer.counter_keys <= observer.MAX_COUNTER_KEYS
    assert not observer.active and not observer.trace_state and observer.phase == 'setup'
    assert sys.getprofile() is None and sys.gettrace() is None and not tracemalloc.is_tracing()


@pytest.mark.parametrize('mode', ['counts', 'trace'])
def test_overflow_cleanup_and_partial_evidence(mode):
    def _evaluate_interval():
        return (
            1 + 2
        )
    observer = bench.Observer(mode, cap=1, targets={_evaluate_interval.__code__})
    with pytest.raises(bench.ObservationOverflow):
        with observer.installed():
            _evaluate_interval()
    assert observer.events == 1 and observer.overflow == 1
    assert 'cap 1 exhausted' in observer.overflow_reason
    assert counts(observer, ':calls') == 1
    assert not observer.active and not observer.trace_state and observer.phase == 'setup'
    assert sys.getprofile() is None and sys.gettrace() is None and not tracemalloc.is_tracing()


def test_caught_hook_failure_still_invalidates_evidence(monkeypatch):
    def target():
        return 1
    error = RuntimeError('diagnostic hook failed')
    observer = bench.Observer(targets={target.__code__})
    def fail(*args):
        raise error
    monkeypatch.setattr(observer, 'classify', fail)
    with pytest.raises(bench._InstrumentationAbort) as exc:
        with observer.installed():
            try:
                target()
            except BaseException as caught:
                assert caught.__cause__ is error
    assert exc.value.__cause__ is error and observer.hook_error is error
    assert not observer.active and sys.getprofile() is None


def test_multiline_loops_returns_and_caught_exception():
    def root_like(n, fail=False):
        total = 0
        for index in range(
            n
        ):
            total += (
                index
                + 1
            )
        while (
            total < 8
        ):
            total += (
                2
            )
        try:
            raise LookupError('caught')
        except LookupError:
            pass
        if fail:
            raise ValueError('propagates')
        return (
            total
            + 1
        )
    observer = bench.Observer('trace', targets={root_like.__code__})
    with observer.installed():
        assert root_like(3) == 9
        assert root_like(0) == 9
        with pytest.raises(ValueError):
            root_like(3, True)
    values = observer.counters['setup']
    entries = [v for k, v in values.items() if ':iteration_entry:' in k]
    assert sorted(entries) == [6, 6]  # for: 3+0+3; while: 1+4+1
    assert counts(observer, ':return_opcodes') == 2
    assert counts(observer, ':propagated_failure:ValueError') == 1
    assert counts(observer, ':propagated_failure:LookupError') == 0


def nested_codes(function):
    def walk(code):
        yield code
        for const in code.co_consts:
            if isinstance(const, CodeType):
                yield from walk(const)
    return set(walk(function.__code__))


@pytest.mark.parametrize('family', ['module', 'string'])
@pytest.mark.parametrize('iterations', [0, 1])
def test_real_isc_source_classification_with_synthetic_objectives(monkeypatch, family, iterations):
    from shading.electrical import module_iv, string_iv
    def _module_state_at_current(topology, states, current):
        return 4.0 - current, []
    def _string_state_at_current(models, current, **kwargs):
        return 4.0 - current, []
    if family == 'module':
        owner, root, objective = module_iv, module_iv._solve_module_isc, _module_state_at_current
        arguments = ({}, {})
    else:
        owner, root, objective = string_iv, string_iv._solve_string_isc, _string_state_at_current
        arguments = ([],)
    monkeypatch.setattr(owner, objective.__name__, objective)
    observer = bench.Observer('trace', targets={root.__code__, objective.__code__})
    with observer.installed():
        assert root(*arguments, current_ceiling_a=8., voltage_tolerance_v=1e-8,
                    current_tolerance_a=1e-8, max_iterations=iterations) == 4.
    values = observer.counters['setup']
    assert values[root.__name__ + ':bracket_evaluations'] == 2
    assert values.get(root.__name__ + ':bisection_refinement', 0) == iterations
    assert values[root.__name__ + ':objective_evaluations'] == 2 + iterations
    assert counts(observer, ':iterations') == iterations
    assert not observer.limitations()


def test_early_endpoint_zero_iterations(monkeypatch):
    from shading.electrical import module_iv
    def _module_state_at_current(*args):
        return 0., []
    monkeypatch.setattr(module_iv, '_module_state_at_current', _module_state_at_current)
    root = module_iv._solve_module_isc
    observer = bench.Observer('trace', targets={root.__code__, _module_state_at_current.__code__})
    with observer.installed():
        assert root({}, {}, current_ceiling_a=8., voltage_tolerance_v=1e-8,
                    current_tolerance_a=1e-8, max_iterations=100) == 0.
    assert counts(observer, ':iterations') == 0
    assert observer.counters['setup'][root.__name__ + ':bracket_evaluations'] == 1


def branch_stubs(monkeypatch):
    from shading.electrical import substring_reference as owner
    monkeypatch.setattr(owner, '_branch_ceiling_with_reuse', lambda *a: 10.)
    monkeypatch.setattr(owner, '_branch_open_with_reuse', lambda *a: 10.)
    monkeypatch.setattr(owner, '_branch_end_with_reuse', lambda *a: 0.)
    def _branch_current_at_voltage(branch, states, *, voltage_v, **kwargs):
        return 10. - voltage_v
    def evaluate_series_branch_voltage(branch, states, *, current_a):
        return 10. - current_a
    monkeypatch.setattr(owner, '_branch_current_at_voltage', _branch_current_at_voltage)
    monkeypatch.setattr(owner, 'evaluate_series_branch_voltage', evaluate_series_branch_voltage)
    return owner, _branch_current_at_voltage, evaluate_series_branch_voltage


@pytest.mark.parametrize('current', [0., 5.])
def test_parallel_bracket_refinement_and_post_solve_separation(monkeypatch, current):
    owner, branch_current, voltage = branch_stubs(monkeypatch)
    root = owner.solve_parallel_branches_at_current
    observer = bench.Observer('trace', targets=nested_codes(root) | {branch_current.__code__, voltage.__code__})
    with observer.installed():
        result = root([{'series_region_ids': ['a', 'b'], 'branch_id': 'b'}], {}, total_current_a=current)
    assert result is not None
    values = observer.counters['setup']
    if current:
        assert values[root.__name__ + ':bracketing'] == 1
        assert values[root.__name__ + ':bisection_refinement'] == 1
        assert values[root.__name__ + ':post_solve_reconstruction'] == 1
        assert values[root.__name__ + ':objective_evaluations'] == 2
    else:
        assert root.__name__ + ':objective_evaluations' not in values
    assert counts(observer, ':iterations') == int(bool(current))


def test_generic_branch_root_classification(monkeypatch):
    owner, branch_current, voltage = branch_stubs(monkeypatch)
    root = owner._branch_current_at_voltage_uncached
    observer = bench.Observer('trace', targets={root.__code__, voltage.__code__})
    with observer.installed():
        assert root({'series_region_ids': ['a', 'b']}, {}, voltage_v=5.,
                    voltage_tolerance_v=1e-8, current_tolerance_a=1e-8, max_iterations=4) == 5.
    assert observer.counters['setup'][root.__name__ + ':bisection_refinement'] == 1
    assert root.__name__ + ':bracket_evaluations' not in observer.counters['setup']
    assert counts(observer, ':iterations') == 1


def test_golden_section_has_no_mid_assumption():
    from shading.electrical.parameterization import _resolve_uniform_mpp_for_temperature_gate as root
    calls = []
    class Adapter:
        def voltage_at_current(self, current):
            calls.append(current)
            return {'protected_substrings': [], 'terminal_voltage_v': 10. - current}
    observer = bench.Observer('trace', targets=nested_codes(root) | {Adapter.voltage_at_current.__code__})
    with observer.installed():
        result = root(Adapter(), 10., bracket_scale=.01)
    assert result['evaluations'] == len(calls)
    values = observer.counters['setup']
    assert values[root.__name__ + ':golden_section_mpp_evaluations'] == len(calls)
    assert values[root.__name__ + ':golden_section_initial'] == 4
    assert values[root.__name__ + ':post_solve_reconstruction'] == 1
    assert values[root.__name__ + ':objective_evaluations'] == len(calls) - 1
    assert values[root.__name__ + ':golden_section_refinement'] == len(calls) - 5
    assert next(iter(observer.limitations().values()))['status'] == 'not_observed'


@pytest.mark.parametrize('mode', ['counts', 'trace'])
def test_phases_and_b2_numerical_acceptance_are_separate(mode):
    def _evaluate_interval():
        return 1
    def verify_run_package():
        return _evaluate_numerical_candidate_physics()
    def persist_run_package():
        _evaluate_numerical_candidate_physics()
        verify_run_package()
    def _evaluate_numerical_candidate_physics():
        return _evaluate_interval()
    observer = bench.Observer(mode, targets={f.__code__ for f in
        (_evaluate_interval, verify_run_package, persist_run_package, _evaluate_numerical_candidate_physics)})
    with observer.installed():
        _evaluate_interval()
        verify_run_package()
        _evaluate_numerical_candidate_physics()
        persist_run_package()
    assert sum(v for k, v in observer.counters['producer'].items() if k.endswith(':calls')) == 1
    assert sum(v for k, v in observer.counters['verification'].items() if k.endswith(':calls')) == 2
    assert sum(v for k, v in observer.counters['persistence'].items() if k.endswith(':calls')) == 1
    assert sum(v for k, v in observer.counters['b2_numerical_acceptance'].items() if k.endswith(':calls')) == 8
    assert not observer.counters['compatibility_controls']
    for phase, calls in (('setup', 2), ('persistence', 2), ('verification', 4)):
        assert sum(v for k, v in observer.b2_context_counters[phase].items() if k.endswith(':calls')) == calls
        assert sum(v for k, v in observer.b2_context_counters[phase].items() if k.endswith(':returns_or_unwinds')) == calls
    for key, value in observer.counters['b2_numerical_acceptance'].items():
        assert sum(c.get(key, 0) for c in observer.b2_context_counters.values()) == pytest.approx(value)
    assert observer.phase == 'setup'
    assert all(v['status'] == 'not_observed' for v in bench.coverage().values())


@pytest.mark.parametrize('mode', ['counts', 'trace'])
def test_reentrant_b2_preserves_producer_and_attribution_context(mode):
    def voltage_at_current():
        return 1
    def _evaluate_numerical_candidate_physics(depth=1):
        if depth:
            return _evaluate_numerical_candidate_physics(depth - 1)
        return voltage_at_current()
    def _evaluate_interval():
        return _evaluate_numerical_candidate_physics()
    def _evaluate_attribution_interval():
        return _evaluate_numerical_candidate_physics()
    observer = bench.Observer(mode, targets={f.__code__ for f in (
        voltage_at_current, _evaluate_numerical_candidate_physics,
        _evaluate_interval, _evaluate_attribution_interval)})
    with observer.installed():
        assert _evaluate_interval() == _evaluate_attribution_interval() == 1
    for phase in ('producer', 'attribution'):
        assert sum(v for k, v in observer.counters[phase].items() if k.endswith(':calls')) == 1
        assert sum(v for k, v in observer.b2_context_counters[phase].items() if k.endswith(':calls')) == 3
        assert sum(v for k, v in observer.b2_context_counters[phase].items() if k.endswith(':returns_or_unwinds')) == 3
    assert sum(v for k, v in observer.counters['b2_numerical_acceptance'].items() if k.endswith(':calls')) == 6
    assert not observer.b2_context_counters['b2_numerical_acceptance']
    assert observer.phase == 'setup' and observer.b2_context is None


def completed(identity='fixture', physical='p', mode='baseline', selection='both'):
    empty = lambda: {p: {} for p in bench.PHASES}
    return dict(status='completed', child_status='completed', child_exit_code=0,
        measurement_mode=mode, cache_selection=selection, cache_semantics=bench.CACHE_SEMANTICS,
        priming=None, overflow=0, hook_failure=None, fixture_identity=bench.digest(identity.encode()),
        counters=empty(), b2_context_counters=empty(), observation_events=2, runs=[
            dict(cache_state=t, status='completed', completed_operations=list(bench.OPERATIONS),
                 numerical_fingerprints=dict(physical=bench.digest(physical.encode()), attribution=bench.digest(b'a')),
                 cache_before={'hits': 0}, cache_after_execution={'hits': 0}, cache_after_verification={'hits': 0},
                 counters=empty() if mode != 'baseline' else None,
                 b2_context_counters=empty() if mode != 'baseline' else None)
            for t in bench.CACHE_STATES[selection]])


def test_incomplete_mismatch_and_overflow_are_not_acceptance():
    assert bench.comparison([completed(), completed()]) == 'MATCH'
    assert bench.comparison([completed(), completed(physical='changed')]) == 'MISMATCH'
    assert bench.comparison([completed()]) == 'INCOMPLETE'
    for status in ('failed', 'overflow', 'wall_capped', 'memory_capped', 'child_exit_failed'):
        assert bench.comparison([completed(), dict(status=status)]) == 'INCOMPLETE'
    assert bench.comparison([dict(status='completed'), completed()]) == 'INCOMPLETE'


def test_fingerprint_serialization_exact_stable_and_no_filtering(evidence):
    assert bench.fingerprint({'b': [1., 2.], 'a': -0.}) == bench.fingerprint({'a': -0., 'b': [1., 2.]})
    assert bench.fingerprint(-0.) != bench.fingerprint(0.)
    assert bench.fingerprint({'timestamp': 1}) != bench.fingerprint({'timestamp': 2})
    for value in (float('nan'), float('inf')):
        with pytest.raises(ValueError):
            bench.fingerprint(value)
    report = dict(status='PENDING_MEASUREMENT', evidence={'sha256': None},
                  payload={'fingerprint': bench.fingerprint({'x': [-0., 1.]})})
    expected = bench.digest(json.dumps(report, sort_keys=True, separators=(',', ':')).encode())
    output = evidence / 'numerical.json'
    bench.write_report(output, report)
    assert json.loads(output.read_text())['evidence']['sha256'] == expected
    assert output.with_suffix('.json.sha256').read_text().strip() == bench.digest(output.read_bytes())


def test_input_identity_weather_and_frozen_store():
    import pandas as pd
    @dataclass(frozen=True)
    class Store:
        payload: bytes
        weather: object
    frame = pd.DataFrame({'ghi': [400., 600.]}, index=pd.date_range('2026-01-01', periods=2, tz='UTC'))
    first = bench.fingerprint(bench.input_identity(Store(b'original', frame)))
    assert first == bench.fingerprint(bench.input_identity(Store(b'original', frame.copy())))
    frame.iloc[0, 0] = 401.
    assert first != bench.fingerprint(bench.input_identity(Store(b'original', frame)))
    with pytest.raises(TypeError, match='unsupported'):
        bench.input_identity(object())


def test_metadata_real_hashes_and_indirect_imports():
    if reason := missing_git() or missing_private_path('.ai/TASK.md'):
        pytest.skip(reason)
    record = bench.metadata()
    assert record['task_sha256'] == bench.digest((bench.ROOT / '.ai/TASK.md').read_bytes())
    for collection in ('source_hashes', 'fixture_hashes'):
        assert all(h == bench.digest((bench.ROOT / p).read_bytes()) for p, h in record[collection].items())
    loaded = bench.loaded_source_hashes()
    assert 'scripts/benchmarks/rb_post3d_08p2e1_root_work.py' in loaded
    assert 'tests/unit/test_rb_post3d_08p2e1_contract.py' in loaded
    json.dumps(record, allow_nan=False)


def synthetic_workload(monkeypatch, *, cap=None, fail=False, catch=None, replace_abort=False):
    log = []
    error = ValueError('workload original')
    def _evaluate_interval():
        log.append('producer')
        if fail:
            raise error
        return 1
    def verify_run_package(path):
        log.append('verification')
    fixture = SimpleNamespace(cache_stats=lambda: {'hits': len(log)})
    payload = {'intervals': [{'modules': {'m': {'local_irradiance': {
        'regions': [{'unshaded_poa': {'diffuse': 400.}}]}}}}]}
    result = SimpleNamespace(summary_result={}, detailed_backend_result=SimpleNamespace(replay=lambda: payload),
        detailed_attribution_result=SimpleNamespace(replay=lambda: {'physical': 1.}), artifact_directory=Path('synthetic'))
    def run(*args, **kwargs):
        try:
            _evaluate_interval()
        except (catch or ()):
            log.append('caught')
            if replace_abort:
                raise error
        return result
    original = bench.Observer
    monkeypatch.setattr(bench, 'Observer', lambda mode: original(mode, cap=cap or 1000,
        targets={_evaluate_interval.__code__, verify_run_package.__code__}))
    def prepare(modules):
        assert sys.getprofile() is None and sys.gettrace() is None
        return fixture, run, SimpleNamespace(verify_run_package=verify_run_package), ({}, {}, {}, {}, {}, {}), 'id', {'synthetic': True}
    monkeypatch.setattr(bench, 'prepare_workload', prepare)
    return error, log


def test_child_completed_cold_warm_and_partial_exception(monkeypatch, evidence):
    if reason := missing_private_path('.ai/TASK.md'):
        pytest.skip(reason)
    error, log = synthetic_workload(monkeypatch)
    result = bench.child(options())
    assert result['status'] == 'completed'
    assert log == ['producer', 'verification', 'producer', 'verification']
    for run in result['runs']:
        assert sum(v for k, v in run['counters']['producer'].items() if k.endswith(':calls')) == 1
        assert sum(v for k, v in run['counters']['verification'].items() if k.endswith(':calls')) == 1


@pytest.mark.parametrize('failure', ['exception', 'overflow'])
def test_child_partial_reports(monkeypatch, evidence, failure):
    synthetic_workload(monkeypatch, fail=failure == 'exception', cap=1 if failure == 'overflow' else None)
    result = bench.child(options())
    assert result['status'] == ('failed' if failure == 'exception' else 'overflow')
    assert result['exception_type'] == ('ValueError' if failure == 'exception' else 'ObservationOverflow')
    assert result['counters']['producer']
    if failure == 'overflow':
        assert result['overflow'] == 1 and 'cap 1' in result['overflow_reason']
    else:
        assert result['exception_message'] == 'workload original'
    assert sys.getprofile() is None and sys.gettrace() is None


@pytest.mark.parametrize('mode', ['counts', 'trace'])
@pytest.mark.parametrize('catch,replace_abort', [(RuntimeError, False), (BaseException, False),
                                               (BaseException, True)])
def test_child_overflow_survives_workload_handlers(monkeypatch, evidence, mode, catch, replace_abort):
    _, log = synthetic_workload(monkeypatch, cap=1, catch=catch, replace_abort=replace_abort)
    result = bench.child(options(mode=mode))
    assert result['status'] == 'overflow' and result['overflow'] == 1
    assert ('caught' in log) == (catch is BaseException)
    assert result['original_child_status'] == ('failed' if replace_abort else 'overflow')
    assert result['exception_type'] == ('ValueError' if replace_abort else 'ObservationOverflow')
    assert result['hook_failure']['exception_type'] == 'ObservationOverflow'
    assert result['overflow_reason'] and result['counters']['producer']
    if catch is RuntimeError or replace_abort:
        assert not result['runs']
    assert sys.getprofile() is None and sys.gettrace() is None and not tracemalloc.is_tracing()


def test_child_overflow_flag_overrides_intercepted_context_abort(monkeypatch, evidence):
    if reason := missing_private_path('.ai/TASK.md'):
        pytest.skip(reason)
    from contextlib import contextmanager
    synthetic_workload(monkeypatch, cap=1, catch=BaseException)
    original = bench.Observer
    @contextmanager
    def intercepted(mode):
        observer = original(mode)
        installed = observer.installed
        @contextmanager
        def suppress_abort():
            try:
                with installed():
                    yield observer
            except BaseException:
                pass
        observer.installed = suppress_abort
        yield observer
    # Simulate interception outside the workload too: child must consult the recorded flag.
    with intercepted('counts') as observer:
        monkeypatch.setattr(bench, 'Observer', lambda mode: observer)
        result = bench.child(options())
    assert result['original_child_status'] == 'completed'
    assert result['status'] == 'overflow' and result['overflow']
    assert result['hook_failure'] and result['overflow_reason'] and result['runs']
    assert sys.getprofile() is None and sys.gettrace() is None


@pytest.mark.parametrize('mode', ['counts', 'trace'])
@pytest.mark.parametrize('catch', ['RuntimeError', 'BaseException'])
def test_real_synthetic_abort_child_to_parent_exit_and_cleanup(monkeypatch, evidence, mode, catch):
    original = subprocess.Popen
    processes = []
    def spawn(command, **kwargs):
        output = command[command.index('--output') + 1]
        code = ('import sys, pathlib, pytest\n'
                'from tests.unit.test_rb_post3d_08p2e1_contract import synthetic_workload\n'
                'from scripts.benchmarks import rb_post3d_08p2e1_root_work as bench\n'
                'patch = pytest.MonkeyPatch()\n'
                f'bench.EVIDENCE = pathlib.Path({output!r}).parent\n'
                f'synthetic_workload(patch, cap=1, catch={catch})\n'
                f'sys.argv = {command[1:]!r}\n'
                'sys.exit(bench.main())\n')
        process = original([sys.executable, '-B', '-c', code], **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(bench.subprocess, 'Popen', spawn)
    monkeypatch.setattr(bench, 'MODES', ('baseline', mode))
    monkeypatch.setattr(bench, 'metadata', lambda: {'synthetic': True})
    report = bench.parent(options(wall_cap_seconds=8), time.monotonic())
    record = report['passes'][-1]
    assert record['status'] == record['child_status'] == 'overflow'
    assert record['child_exit_code'] == 1 and record['original_child_status'] == 'overflow'
    assert record['hook_failure']['exception_type'] == 'ObservationOverflow'
    assert record['overflow_reason'] and record['counters']['producer']
    assert report['fingerprint_comparison'] == 'INCOMPLETE'
    assert report['diagnostic_status'] == 'incomplete_or_mismatch'
    assert report['status'] == 'PENDING_MEASUREMENT'
    output = evidence / 'abort-parent.json'
    bench.write_report(output, report)
    assert json.loads(output.read_text())['passes'][-1] == record
    assert all(process.poll() is not None for process in processes)
    assert all(not alive_non_zombie(process.pid) for process in processes)


def substitute_child(monkeypatch, payload, exit_code=0, *, delay=0., descendant=False):
    """Real isolated subprocess, synthetic JSON only; never invokes the CLI workload."""
    original = subprocess.Popen
    def spawn(command, **kwargs):
        output = command[command.index('--output') + 1]
        code = ('import json, pathlib, subprocess, sys, time\n'
                f'time.sleep({delay!r})\n')
        if descendant:
            code += 'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\nprint(p.pid, flush=True)\n'
        if payload is not None:
            mode = command[command.index('--mode') + 1]
            record = json.loads(json.dumps(payload))
            record['measurement_mode'] = mode
            if mode != 'baseline' and record.get('runs'):
                for run in record['runs']:
                    run['counters'] = {p: {} for p in bench.PHASES}
                    run['b2_context_counters'] = {p: {} for p in bench.PHASES}
            code += f'pathlib.Path({output!r}).write_text({json.dumps(record)!r})\n'
        code += 'print("prefix" + "x" * 9000, flush=True)\nprint("LAST diagnostic", flush=True)\n'
        code += f'sys.exit({exit_code!r})\n'
        return original([sys.executable, '-c', code], **kwargs)
    monkeypatch.setattr(bench.subprocess, 'Popen', spawn)


@pytest.mark.parametrize('status,exit_code', [('completed', 0), ('failed', 1), ('overflow', 1), ('completed', 3)])
def test_complete_child_to_parent_report_path(monkeypatch, evidence, status, exit_code):
    retained = ({p: ({'partial': 3} if p == 'dispatch' else {}) for p in bench.PHASES}
                if status == 'completed' and exit_code == 0 else {'partial': 3})
    payload = completed() | {'status': status, 'counters': retained,
        'exception_type': 'ObservationOverflow' if status == 'overflow' else 'ValueError',
        'exception_message': 'original diagnostic', 'overflow_reason': 'selected cap exhausted'}
    substitute_child(monkeypatch, payload, exit_code)
    monkeypatch.setattr(bench, 'metadata', lambda: {'synthetic': True})
    args = options()
    report = bench.parent(args, time.monotonic())
    record = report['passes'][0]
    assert record['child_status'] == status
    assert record['child_exit_code'] == exit_code
    assert record['status'] == ('child_exit_failed' if status == 'completed' and exit_code else status)
    for key in ('counters', 'exception_type', 'exception_message', 'overflow_reason'):
        assert record[key] == payload[key]
    assert record['diagnostic_log_tail'].endswith('LAST diagnostic\n')
    assert len(record['diagnostic_log_tail']) <= 8000
    output = evidence / 'parent.json'
    bench.write_report(output, report)
    saved = json.loads(output.read_text())
    assert saved['passes'][0] == record
    assert saved['status'] == 'PENDING_MEASUREMENT'
    assert saved['schema_version'] == 2
    assert saved['diagnostic_status'] == ('completed' if status == 'completed' and exit_code == 0 else 'incomplete_or_mismatch')
    assert saved['regression_gates'] == 'NOT_RUN'


def test_main_child_nonzero_json_and_final_report(monkeypatch, evidence):
    synthetic_workload(monkeypatch, cap=1)
    output = evidence / 'child.json'
    monkeypatch.setattr(sys, 'argv', ['e1', '--child', '--mode', 'counts', '--output', str(output), '--wall-cap-seconds', '2'])
    assert bench.main() == 1
    record = bench.collect_child(output, 'counts', 1, 'tail')
    assert record['status'] == record['child_status'] == 'overflow'
    assert record['exception_type'] == 'ObservationOverflow'
    assert record['counters'] and record['overflow_reason']
    assert record['child_exit_code'] == 1


@pytest.mark.parametrize('exit_code', [0, 1])
@pytest.mark.parametrize('child_status', ['completed', 'failed'])
def test_recorded_overflow_overrides_contradictory_child_status(evidence, exit_code, child_status):
    payload = completed() | {'status': child_status, 'overflow': 1,
        'overflow_reason': 'retained state bound', 'counters': {'partial': 1},
        'hook_failure': {'exception_type': 'ObservationOverflow', 'exception_message': 'bound'}}
    output = evidence / 'contradictory.json'
    output.write_text(json.dumps(payload))
    record = bench.collect_child(output, 'counts', exit_code, 'partial log')
    assert record['child_status'] == child_status and record['status'] == 'overflow'
    assert record['child_exit_code'] == exit_code
    for field in ('overflow_reason', 'hook_failure', 'counters'):
        assert record[field] == payload[field]
    assert bench.comparison([completed(), payload]) == 'INCOMPLETE'
    assert bench.comparison([completed(), record]) == 'INCOMPLETE'


class FakeProcess:
    pid = 987654321
    returncode = None
    def __init__(self):
        self.waited = False
    def poll(self):
        return self.returncode
    def wait(self):
        self.waited = True
        if self.returncode is None:
            self.returncode = -9
        return self.returncode


@pytest.mark.parametrize('cause', ['normal', 'wall', 'memory', 'keyboard', 'sigterm', 'parent_error', 'already_exited'])
def test_parent_cleanup_all_paths(monkeypatch, evidence, cause):
    process = FakeProcess()
    killed = []
    def spawn(command, **kwargs):
        if cause in ('normal', 'already_exited'):
            process.returncode = 0
        return process
    monkeypatch.setattr(bench.subprocess, 'Popen', spawn)
    monkeypatch.setattr(bench, 'resident_bytes', lambda pid: 4097 * 1024**2 if cause == 'memory' else 1024)
    def killpg(pid, sig):
        killed.append((pid, sig))
        if cause == 'already_exited':
            raise ProcessLookupError('already gone')
    monkeypatch.setattr(bench.os, 'killpg', killpg)
    def pause(seconds):
        if cause == 'keyboard':
            raise KeyboardInterrupt('stop')
        if cause == 'sigterm':
            os.kill(os.getpid(), signal.SIGTERM)
        if cause == 'parent_error':
            raise RuntimeError('parent original')
    monkeypatch.setattr(bench.time, 'sleep', pause)
    # Let launch happen, then expire during monitor, rather than before launch.
    if cause == 'wall':
        times = iter([0., 2.])
        monkeypatch.setattr(bench.time, 'monotonic', lambda: next(times))
        deadline = 1.
    else:
        deadline = time.monotonic() + 1
    previous = signal.getsignal(signal.SIGTERM)
    result = bench.run_mode(options(), 'counts', deadline)
    assert process.waited and killed == [(process.pid, signal.SIGKILL)]
    assert signal.getsignal(signal.SIGTERM) == previous
    expected = {'wall': 'wall_capped', 'memory': 'memory_capped', 'keyboard': 'interrupted',
                'sigterm': 'parent_terminated', 'parent_error': 'parent_failed'}
    assert result['status'] == expected.get(cause, 'missing_child_output')
    if cause in ('keyboard', 'sigterm', 'parent_error'):
        assert result['parent_error']['exception_message']
    assert bench.comparison([completed(), result]) == 'INCOMPLETE'


def test_parent_exception_after_spawn_still_kills(monkeypatch, evidence):
    process = FakeProcess()
    monkeypatch.setattr(bench.subprocess, 'Popen', lambda *a, **k: process)
    def fail(pid):
        raise ValueError('rss failure')
    monkeypatch.setattr(bench, 'resident_bytes', fail)
    monkeypatch.setattr(bench.os, 'killpg', lambda *a: None)
    result = bench.run_mode(options(), 'counts', time.monotonic() + 1)
    assert process.waited
    assert result['status'] == 'parent_failed'
    assert result['parent_error'] == {'exception_type': 'ValueError', 'exception_message': 'rss failure'}


def test_real_timeout_and_missing_json(monkeypatch, evidence):
    substitute_child(monkeypatch, None, delay=30.)
    start = time.monotonic()
    result = bench.run_mode(options(wall_cap_seconds=.15), 'trace', start + .15)
    assert result['status'] == 'wall_capped'
    assert result['child_status'] == 'missing_child_output'
    assert result['child_exit_code'] == -signal.SIGKILL
    assert time.monotonic() - start < 3


def alive_non_zombie(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().split(') ')[1][0] != 'Z'
    except OSError:  # Includes FileNotFoundError and ProcessLookupError during exit races.
        return False


@pytest.mark.parametrize('error', [ProcessLookupError('exited'), OSError('proc unavailable')])
def test_alive_non_zombie_tolerates_proc_exit_races(monkeypatch, error):
    def disappeared(*args, **kwargs):
        raise error
    monkeypatch.setattr(Path, 'read_text', disappeared)
    assert not alive_non_zombie(987654321)


def test_completed_leader_cleanup_kills_descendants(monkeypatch, evidence):
    original = subprocess.Popen
    def spawn(command, **kwargs):
        output = command[command.index('--output') + 1]
        descendant_code = 'import time; print("ready", flush=True); time.sleep(30)'
        code = ('import pathlib, subprocess, sys\n'
            f'p = subprocess.Popen([sys.executable, "-c", {descendant_code!r}], stdout=subprocess.PIPE)\n'
            'print(p.pid, flush=True)\n'
            'assert p.stdout.readline() == b"ready\\n"\n'
            f'pathlib.Path({output!r}).write_text({json.dumps(completed())!r})\n')
        return original([sys.executable, '-c', code], **kwargs)
    monkeypatch.setattr(bench.subprocess, 'Popen', spawn)
    # Allow scheduling delays; both budgets together remain below the descendant's sleep.
    result = bench.run_mode(options(wall_cap_seconds=10), 'counts', time.monotonic() + 10)
    pid = int(result['diagnostic_log_tail'].strip())
    try:
        assert result['status'] == 'completed'
        assert result['child_exit_code'] == 0
        deadline = time.monotonic() + 5
        while alive_non_zombie(pid) and time.monotonic() < deadline:
            time.sleep(.01)
        assert not alive_non_zombie(pid)
    finally:
        if alive_non_zombie(pid):
            os.kill(pid, signal.SIGKILL)


def test_child_independent_runtime_backstop():
    code = ('import time\nfrom scripts.benchmarks.rb_post3d_08p2e1_root_work import child_backstop\n'
            'with child_backstop(.1):\n    time.sleep(30)\n')
    process = subprocess.Popen([sys.executable, '-c', code], cwd=bench.ROOT, start_new_session=True)
    try:
        assert process.wait(timeout=3) == -signal.SIGALRM
    finally:
        bench.stop(process)


def test_orphan_child_backstop_after_parent_exit(evidence):
    pidfile = evidence / 'orphan.pid'
    child_code = ('import pathlib, os, time\n'
        'from scripts.benchmarks.rb_post3d_08p2e1_root_work import child_backstop\n'
        f'with child_backstop(.15):\n    pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()))\n    time.sleep(30)\n')
    launcher = ('import subprocess, sys\n'
                f'subprocess.Popen([sys.executable, "-c", {child_code!r}], start_new_session=True)\n')
    subprocess.run([sys.executable, '-c', launcher], cwd=bench.ROOT, check=True, timeout=3)
    deadline = time.monotonic() + 2
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert pidfile.exists()
    pid = int(pidfile.read_text())
    try:
        while alive_non_zombie(pid) and time.monotonic() < deadline:
            time.sleep(.01)
        assert not alive_non_zombie(pid)
    finally:
        if alive_non_zombie(pid):
            os.killpg(pid, signal.SIGKILL)


def test_rss_actual_and_unavailable():
    assert bench.resident_bytes(999999999) is None
    if Path('/proc/self/statm').exists():
        assert bench.resident_bytes(os.getpid()) > 0


def test_root_summary_distinguishes_observed_zero_and_unknown(monkeypatch):
    from shading.electrical import module_iv
    def _module_state_at_current(*args):
        return 0., []
    monkeypatch.setattr(module_iv, '_module_state_at_current', _module_state_at_current)
    root = module_iv._solve_module_isc
    for mode in ('counts', 'trace'):
        observer = bench.Observer(mode, targets={root.__code__, _module_state_at_current.__code__})
        with observer.installed():
            root({}, {}, current_ceiling_a=8., voltage_tolerance_v=1e-8,
                 current_tolerance_a=1e-8, max_iterations=100)
        summary = observer.root_observations()
        assert summary['setup'][root.__name__]['solve_calls']['value'] == 1
        assert summary['setup'][root.__name__]['bracket_evaluations']['value'] == 1
        assert summary['setup'][root.__name__]['iterations'] == (
            {'status': 'observed', 'value': 0} if mode == 'trace' else
            bench.not_observed('focused observation disabled or loop entry is ambiguous'))
        assert summary['producer'][root.__name__]['status'] == 'not_observed'
        assert summary['setup'][root.__name__]['termination_reasons']['status'] == 'not_observed'


def test_unprepared_selected_code_fails_closed(monkeypatch):
    def target():
        return 1
    observer = bench.Observer(targets={target.__code__})
    monkeypatch.setattr(observer, 'prepare', lambda: None)
    with pytest.raises(bench._InstrumentationAbort, match='not prepared'):
        with observer.installed():
            target()
    assert observer.hook_error is not None
    assert not observer.active and sys.getprofile() is None


def test_code_registry_cap_fail_closed(monkeypatch):
    def target():
        return 1
    observer = bench.Observer(targets={target.__code__})
    monkeypatch.setattr(observer, 'MAX_CODES', 0)
    with pytest.raises(bench.ObservationOverflow, match='registry'):
        with observer.installed():
            pytest.fail('registry overflow ignored')
    assert observer.overflow == 1 and observer.overflow_reason
    assert sys.getprofile() is None and not observer.active


def test_invalid_or_missing_child_json_and_alarm_status(evidence):
    output = evidence / 'invalid.json'
    output.write_text('{invalid')
    result = bench.collect_child(output, 'counts', 1, 'last error')
    assert result['status'] == result['child_status'] == 'invalid_child_output'
    assert result['output_error'] and result['diagnostic_log_tail'] == 'last error'
    output.write_text('[]')
    assert bench.collect_child(output, 'trace', 1, '')['status'] == 'invalid_child_output'
    result = bench.collect_child(evidence / 'absent.json', 'trace', -signal.SIGALRM, '')
    assert result['status'] == 'child_wall_capped' and result['child_status'] == 'missing_child_output'


def test_unavailable_rss_is_labeled(monkeypatch, evidence):
    substitute_child(monkeypatch, completed())
    monkeypatch.setattr(bench, 'resident_bytes', lambda pid: None)
    result = bench.run_mode(options(), 'baseline', time.monotonic() + 2)
    assert result['status'] == 'completed'
    assert result['memory']['enforcement'] == 'unavailable or incomplete'
    assert result['memory']['sampled_peak_resident_bytes'] is None


def test_default_registry_prepared_without_workload():
    # Only import/plan inspection; no physical evaluations or fixture construction.
    from shading.electrical import module_iv
    observer = bench.Observer()
    with observer.installed():
        pass
    assert module_iv._solve_module_isc.__code__ in observer.plans
    assert len(observer.plans) <= observer.MAX_CODES
    assert observer.events == 0 and not observer.active


def test_incomplete_completed_payloads_fail_closed():
    for runs in (None, [{}, {}], [None, None], [dict(numerical_fingerprints={})] * 2):
        candidate = completed() | {'runs': runs}
        assert bench.comparison([completed(), candidate]) == 'INCOMPLETE'
    candidate = completed()
    candidate['runs'][1]['cache_state'] = 'cold_physics_cache'
    assert bench.comparison([completed(), candidate]) == 'INCOMPLETE'


def test_report_digest_is_repeatable(evidence):
    report = {'status': 'PENDING_MEASUREMENT', 'evidence': {'sha256': None}}
    bench.write_report(evidence / 'first.json', report)
    first = report['evidence']['sha256']
    bench.write_report(evidence / 'second.json', report)
    assert report['evidence']['sha256'] == first
    assert (evidence / 'first.json').read_bytes() == (evidence / 'second.json').read_bytes()


@pytest.mark.parametrize('mode', ['baseline', 'counts', 'both'])
@pytest.mark.parametrize('selection', ['cold', 'warm', 'both'])
def test_cli_independent_selectors_and_defaults(mode, selection):
    args = bench.parser().parse_args(['--output', 'unused.json', '--measurement-mode', mode,
                                     '--cache-state', selection])
    assert args.measurement_mode == mode and args.cache_state == selection
    bench.controls(args)
    default = bench.parser().parse_args(['--output', 'unused.json'])
    assert default.measurement_mode == default.cache_state == 'both'


@pytest.mark.parametrize('mode', ['baseline', 'counts', 'both'])
def test_parent_separate_and_default_operation(monkeypatch, evidence, mode):
    if reason := missing_git() or missing_private_path('.ai/TASK.md'):
        pytest.skip(reason)
    launched = []
    def measure(args, selected, deadline):
        launched.append(selected)
        return completed(mode=selected, selection=args.cache_state)
    monkeypatch.setattr(bench, 'run_mode', measure)
    report = bench.parent(options(measurement_mode=mode), time.monotonic())
    assert launched == (['baseline', 'counts'] if mode == 'both' else [mode])
    assert report['diagnostic_status'] == 'completed'
    assert report['fingerprint_comparison'] == ('MATCH' if mode == 'both' else 'NOT_COMPARED_INDEPENDENT')
    assert report['status'] == 'PENDING_MEASUREMENT'


@pytest.mark.parametrize('failure_mode', ['baseline', 'counts'])
@pytest.mark.parametrize('failure', ['failed', 'wall_capped', 'memory_capped', 'overflow'])
def test_parent_preserves_success_and_attempts_each_independent_mode(monkeypatch, evidence, failure_mode, failure):
    if reason := missing_git() or missing_private_path('.ai/TASK.md'):
        pytest.skip(reason)
    called = []
    def measure(args, mode, deadline):
        called.append(mode)
        return completed(mode=mode) | ({'status': failure} if mode == failure_mode else {})
    monkeypatch.setattr(bench, 'run_mode', measure)
    args = options(output=evidence / 'partial-parent.json')
    report = bench.parent(args, time.monotonic())
    assert called == ['baseline', 'counts']
    assert len(report['passes']) == 2 and report['diagnostic_status'] == 'incomplete_or_mismatch'
    assert report['passes'][called.index(failure_mode)]['status'] == failure
    assert report['passes'][called.index('counts' if failure_mode == 'baseline' else 'baseline')]['status'] == 'completed'
    checkpoint = json.loads(args.output.read_text())
    assert checkpoint['passes'] == report['passes']
    assert checkpoint['diagnostic_status'] == 'in_progress'
    bench.read_evidence(args.output)


def test_independent_deadlines_include_preparation_and_priming(monkeypatch, evidence):
    if reason := missing_git() or missing_private_path('.ai/TASK.md'):
        pytest.skip(reason)
    now = [100.]
    deadlines = []
    def measure(args, mode, deadline):
        deadlines.append(deadline)
        now[0] += args.wall_cap_seconds + 1
        return completed(mode=mode)
    monkeypatch.setattr(bench.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(bench, 'run_mode', measure)
    report = bench.parent(options(wall_cap_seconds=2), now[0])
    assert deadlines == [102., 105.]
    assert report['diagnostic_status'] == 'completed'
    assert report['total_wall_seconds_before_serialization'] == 6


@pytest.mark.parametrize('mode', ['baseline', 'counts'])
def test_independent_child_command_limits_and_selection(monkeypatch, evidence, mode):
    process = FakeProcess()
    command_seen = []
    def spawn(command, **kwargs):
        command_seen.extend(command)
        return process
    monkeypatch.setattr(bench.subprocess, 'Popen', spawn)
    monkeypatch.setattr(bench.os, 'killpg', lambda *a: None)
    monkeypatch.setattr(bench, 'resident_bytes', lambda pid: 3 * 1024**2)
    result = bench.run_mode(options(cache_state='warm', wall_cap_seconds=1.5, memory_limit_mib=2),
                            mode, time.monotonic() + 1.5)
    assert result['status'] == 'memory_capped' and process.waited
    assert command_seen[command_seen.index('--mode') + 1] == mode
    assert command_seen[command_seen.index('--cache-state') + 1] == 'warm'
    assert command_seen[command_seen.index('--memory-limit-mib') + 1] == '2'
    assert 0 < float(command_seen[command_seen.index('--wall-cap-seconds') + 1]) <= 1.5


def ordered_workload(monkeypatch, *, fail_warm=False, wait_warm=False):
    """Stateful synthetic sequence includes verifier cache changes and nested B2."""
    log = []
    state = {'hits': 0}
    names = []
    def step(label):
        log.append((label, sys.getprofile() is not None))
        state['hits'] += 1
    def _evaluate_numerical_candidate_physics():
        step('b2')
    def _evaluate_interval():
        step('producer')
    def _evaluate_attribution_interval():
        step('attribution')
    def verify_run_package(path):
        step('verification')
        _evaluate_numerical_candidate_physics()
    def persist_run_package():
        step('persistence')
        _evaluate_numerical_candidate_physics()
        verify_run_package(None)  # Production persistence has an internal verifier.
    def replay_physical():
        step('physical-replay')
        return {'intervals': [{'modules': {'m': {'local_irradiance': {
            'regions': [{'unshaded_poa': {'diffuse': 400.}}]}}}}]}
    def replay_attribution():
        step('attribution-replay')
        return {'physical': 1.}
    def run(*args, name, **kwargs):
        names.append(name)
        if name == 'warm_physics_cache':
            if fail_warm:
                raise ValueError('warm failed after completed cold')
            if wait_warm:
                time.sleep(30)
        _evaluate_interval()
        _evaluate_attribution_interval()
        persist_run_package()
        return SimpleNamespace(summary_result={},
            detailed_backend_result=SimpleNamespace(replay=replay_physical),
            detailed_attribution_result=SimpleNamespace(replay=replay_attribution), artifact_directory=Path('synthetic'))
    def prepare(modules):
        assert sys.getprofile() is None and sys.gettrace() is None
        state['hits'] = 0
        step('prepare-and-clear')
        return (SimpleNamespace(cache_stats=lambda: dict(state)), run,
                SimpleNamespace(verify_run_package=verify_run_package), ({},) * 6,
                bench.digest(b'fixture'), {})
    original = bench.Observer
    targets = {f.__code__ for f in (_evaluate_interval, _evaluate_attribution_interval,
               _evaluate_numerical_candidate_physics, persist_run_package, verify_run_package)}
    monkeypatch.setattr(bench, 'prepare_workload', prepare)
    monkeypatch.setattr(bench, 'Observer', lambda mode: original(mode, targets=targets))
    return log, names


@pytest.mark.parametrize('mode', ['baseline', 'counts'])
@pytest.mark.parametrize('selection', ['cold', 'warm', 'both'])
def test_child_selection_full_order_warm_priming_equivalence(monkeypatch, evidence, mode, selection):
    if reason := missing_private_path('.ai/TASK.md'):
        pytest.skip(reason)
    log, names = ordered_workload(monkeypatch)
    original_hooks = sys.getprofile(), sys.gettrace()
    original = bench.child(options(mode=mode))
    original_log = list(log)
    log.clear()
    names.clear()
    # New preparation establishes a new cold cache in this synthetic fixture.
    selected = bench.child(options(mode=mode, cache_state=selection))
    assert selected['status'] == 'completed'
    assert (sys.getprofile(), sys.gettrace()) == original_hooks
    assert [r['cache_state'] for r in selected['runs']] == list(bench.CACHE_STATES[selection])
    assert names == (['cold_physics_cache'] if selection == 'cold' else
                     ['cold_physics_cache', 'warm_physics_cache'])
    assert [label for label, hooked in log] == [label for label, hooked in original_log[:len(log)]]
    measured = selected['runs'][0]
    target = original['runs'][1 if selection == 'warm' else 0]
    for field in ('numerical_fingerprints', 'cache_before', 'cache_after_execution', 'cache_after_verification'):
        assert measured[field] == target[field]
    if selection == 'warm':
        priming = selected['priming']
        assert priming['instrumented'] is False and priming['total_wall_seconds'] >= 0
        assert priming['counters'] is None and priming['b2_context_counters'] is None
        for field in ('numerical_fingerprints', 'cache_before', 'cache_after_execution', 'cache_after_verification'):
            assert priming[field] == original['runs'][0][field]
        assert all(not hooked for label, hooked in log[:len(original_log) // 2 + 1])
    else:
        assert selected['priming'] is None
    if mode == 'baseline':
        assert all(not hooked for label, hooked in log)
    else:
        for phase in ('producer', 'attribution', 'persistence', 'verification', 'b2_numerical_acceptance'):
            assert measured['counters'][phase]
        assert measured['counters'].keys() == target['counters'].keys()
        for phase in bench.PHASES:
            # Inclusive elapsed seconds vary; all work counters and stateful order must match.
            for key, value in measured['counters'][phase].items():
                if not key.endswith(':inclusive_seconds'):
                    assert value == target['counters'][phase][key]
        assert selected['observation_events'] == (original['observation_events'] if selection == 'both'
                                                 else original['observation_events'] // 2)
        for key, value in measured['counters']['b2_numerical_acceptance'].items():
            assert sum(c.get(key, 0) for c in measured['b2_context_counters'].values()) == pytest.approx(value)


def test_completed_cold_preserved_on_warm_exception(monkeypatch, evidence):
    ordered_workload(monkeypatch, fail_warm=True)
    args = options(output=evidence / 'child-partial.json')
    report = bench.child(args)
    bench.write_report(args.output, report)
    record = bench.collect_child(args.output, 'counts', 1, 'warm failed')
    assert record['status'] == 'failed' and record['child_status'] == 'failed'
    assert record['exception_message'] == 'warm failed after completed cold'
    assert len(record['runs']) == 1 and record['runs'][0]['status'] == 'completed'
    assert record['runs'][0]['numerical_fingerprints']
    assert record['counters']
    bench.read_evidence(args.output)


def test_checkpoint_survives_real_timeout_after_completed_cold(monkeypatch, evidence):
    original = subprocess.Popen
    def spawn(command, **kwargs):
        output = command[command.index('--output') + 1]
        code = ('import pathlib, pytest, sys\n'
                'from tests.unit.test_rb_post3d_08p2e1_contract import ordered_workload\n'
                'from scripts.benchmarks import rb_post3d_08p2e1_root_work as bench\n'
                'patch = pytest.MonkeyPatch()\n'
                f'bench.EVIDENCE = pathlib.Path({output!r}).parent\n'
                'ordered_workload(patch, wait_warm=True)\n'
                f'sys.argv = {command[1:]!r}\n'
                'sys.exit(bench.main())\n')
        return original([sys.executable, '-B', '-c', code], **kwargs)
    monkeypatch.setattr(bench.subprocess, 'Popen', spawn)
    record = bench.run_mode(options(wall_cap_seconds=1), 'counts', time.monotonic() + 1)
    assert record['status'] in ('wall_capped', 'child_wall_capped')
    assert record['child_status'] == 'in_progress'
    assert len(record['runs']) == 1 and record['runs'][0]['status'] == 'completed'
    assert record['runs'][0]['counters'] and record['counters']
    assert bench.comparison([completed(), record]) == 'INCOMPLETE'


def artifact(mode, selection='both'):
    if reason := missing_git() or missing_private_path('.ai/TASK.md'):
        pytest.skip(reason)
    meta = bench.metadata()
    record = completed(mode=mode, selection=selection)
    if selection == 'warm':
        priming = completed(selection='cold')['runs'][0]
        priming.update(instrumented=False, total_wall_seconds=0.01)
        record['priming'] = priming
    loaded = bench.loaded_source_hashes()
    record['provenance'] = dict(loaded_repository_source_hashes=loaded,
        loaded_repository_sources_after_execution=dict(loaded),
        fixture_and_input_files={k: meta['fixture_hashes'][k] for k in bench.FIXTURE_FILES},
        task_sha256=meta['task_sha256'], task_sha256_after_execution=meta['task_sha256'],
        harness_sha256=meta['harness_sha256'], workload_input_sha256=record['fixture_identity'],
        workload_input_basis='synthetic complete input serialization')
    return dict(schema_name='RawiBumiRootWorkAudit', schema_version=2, base=bench.BASE,
        status='PENDING_MEASUREMENT', diagnostic_status='completed', metadata=meta,
        evidence=bench.evidence_header(), controls=dict(modules=10, intervals=1, workers=1,
        wall_cap_seconds=2, memory_limit_mib=32), measurement_mode=mode, cache_selection=selection,
        fingerprint_comparison='NOT_COMPARED_INDEPENDENT',
        passes=[record])


def save_pair(evidence, *, selection='both'):
    baseline, counts = evidence / 'baseline.json', evidence / 'counts.json'
    bench.write_report(baseline, artifact('baseline', selection))
    bench.write_report(counts, artifact('counts', selection))
    return baseline, counts


@_HISTORICAL_E1
@pytest.mark.parametrize('selection', ['cold', 'warm', 'both'])
def test_cross_evidence_match_read_only_and_independent_verifiability(evidence, selection):
    baseline, counts = save_pair(evidence, selection=selection)
    snapshots = {p: p.read_bytes() for p in (baseline, counts, baseline.with_suffix('.json.sha256'), counts.with_suffix('.json.sha256'))}
    # Resource limits are invocation-specific and need not match.
    right, _ = bench.read_evidence(counts)
    right['controls'].update(wall_cap_seconds=900, memory_limit_mib=4096)
    bench.write_report(counts, right)
    snapshots[counts] = counts.read_bytes()
    snapshots[counts.with_suffix('.json.sha256')] = counts.with_suffix('.json.sha256').read_bytes()
    report = bench.compare_evidence(baseline, counts)
    assert report['fingerprint_comparison'] == 'MATCH' and report['diagnostic_status'] == 'completed'
    assert report['status'] == 'PENDING_MEASUREMENT' and report['regression_gates'] == 'NOT_RUN'
    assert len(report['comparison_inputs']) == 2
    for path, raw in snapshots.items():
        assert path.read_bytes() == raw
    assert bench.artifact_identity(bench.read_evidence(baseline)[0], 'baseline')
    assert bench.artifact_identity(bench.read_evidence(counts)[0], 'counts')


@_HISTORICAL_E1
@pytest.mark.parametrize('field', ['commit', 'source_hashes', 'fixture_hashes', 'harness_version',
                                   'harness_sha256', 'task_sha256', 'environment'])
@pytest.mark.parametrize('mutation', ['missing', 'mismatch'])
def test_cross_evidence_metadata_identity_validation(evidence, field, mutation):
    baseline, counts = save_pair(evidence)
    report, _ = bench.read_evidence(counts)
    if mutation == 'missing':
        report['metadata'].pop(field)
    elif field in ('source_hashes', 'fixture_hashes'):
        key = next(iter(report['metadata'][field]))
        report['metadata'][field][key] = bench.digest(b'changed')
    elif field == 'environment':
        report['metadata'][field]['python'] += '-changed'
    elif field == 'commit':
        report['metadata'][field] = bench.BASE + '1' * (40 - len(bench.BASE))
    elif field.endswith('sha256'):
        report['metadata'][field] = bench.digest(b'changed')
    else:
        report['metadata'][field] = 'changed'
    bench.write_report(counts, report)
    comparison = bench.compare_evidence(baseline, counts)
    assert comparison['fingerprint_comparison'] in ('INCOMPLETE', 'MISMATCH')
    assert comparison['diagnostic_status'] == 'incomplete_or_mismatch'


@_HISTORICAL_E1
@pytest.mark.parametrize('field', ['fixture_identity', 'provenance', 'cache_selection', 'cache_semantics',
    'runs', 'child_status', 'child_exit_code', 'overflow', 'hook_failure', 'counters', 'b2_context_counters'])
def test_cross_evidence_missing_child_identity_fails_closed(evidence, field):
    baseline, counts = save_pair(evidence)
    report, _ = bench.read_evidence(counts)
    report['passes'][0].pop(field)
    bench.write_report(counts, report)
    result = bench.compare_evidence(baseline, counts)
    assert result['fingerprint_comparison'] == 'INCOMPLETE'
    assert result['comparison_error']


@_HISTORICAL_E1
@pytest.mark.parametrize('part', ['physical', 'attribution'])
@pytest.mark.parametrize('selection', ['cold', 'warm', 'both'])
def test_cross_evidence_numerical_fingerprint_mismatch(evidence, part, selection):
    baseline, counts = save_pair(evidence, selection=selection)
    right, _ = bench.read_evidence(counts)
    right['passes'][0]['runs'][-1]['numerical_fingerprints'][part] = bench.digest(b'changed')
    bench.write_report(counts, right)
    assert bench.compare_evidence(baseline, counts)['fingerprint_comparison'] == 'MISMATCH'


@_HISTORICAL_E1
@pytest.mark.parametrize('failure', ['failed', 'wall_capped', 'memory_capped', 'overflow', 'in_progress'])
def test_cross_evidence_incomplete_child_fails_closed(evidence, failure):
    baseline, counts = save_pair(evidence)
    right, _ = bench.read_evidence(counts)
    right['passes'][0]['status'] = failure
    bench.write_report(counts, right)
    assert bench.compare_evidence(baseline, counts)['fingerprint_comparison'] == 'INCOMPLETE'


@_HISTORICAL_E1
@pytest.mark.parametrize('change', ['different_coverage', 'missing_operations', 'missing_cache_snapshot',
    'missing_physical', 'missing_attribution', 'priming_fingerprint', 'priming_instrumented',
    'priming_unverified', 'warm_preconditions', 'missing_priming', 'incomplete_input_hashes',
    'missing_indirect_hashes', 'input_identity', 'nonzero_exit', 'hook_failure', 'overflow',
    'workload_config', 'missing_configuration', 'missing_requested_mode'])
def test_cross_evidence_cache_workload_provenance_and_coverage(evidence, change):
    baseline, counts = save_pair(evidence, selection='warm')
    right, _ = bench.read_evidence(counts)
    record = right['passes'][0]
    if change == 'different_coverage':
        right = artifact('counts', 'cold')
    elif change == 'missing_operations':
        record['runs'][0]['completed_operations'].remove('verification')
    elif change == 'missing_cache_snapshot':
        record['runs'][0].pop('cache_after_verification')
    elif change.startswith('missing_') and change.split('_', 1)[1] in ('physical', 'attribution'):
        record['runs'][0]['numerical_fingerprints'].pop(change.split('_', 1)[1])
    elif change == 'priming_fingerprint':
        record['priming']['numerical_fingerprints']['physical'] = bench.digest(b'changed')
    elif change == 'priming_instrumented':
        record['priming']['instrumented'] = True
    elif change == 'priming_unverified':
        record['priming']['completed_operations'].remove('verification')
    elif change == 'warm_preconditions':
        record['runs'][0]['cache_before']['hits'] += 1
    elif change == 'missing_priming':
        record.pop('priming')
    elif change == 'incomplete_input_hashes':
        record['provenance']['fixture_and_input_files'].pop(bench.FIXTURE_FILES[0])
    elif change == 'missing_indirect_hashes':
        record['provenance'].pop('loaded_repository_source_hashes')
    elif change == 'input_identity':
        record['provenance']['workload_input_sha256'] = bench.digest(b'changed')
    elif change == 'nonzero_exit':
        record['child_exit_code'] = 1
    elif change == 'hook_failure':
        record['hook_failure'] = {'exception_type': 'Error'}
    elif change == 'overflow':
        record['overflow'] = 1
    elif change == 'workload_config':
        right['controls']['modules'] = 50
    elif change == 'missing_configuration':
        right.pop('controls')
    elif change == 'missing_requested_mode':
        right.pop('measurement_mode')
    bench.write_report(counts, right)
    assert bench.compare_evidence(baseline, counts)['fingerprint_comparison'] in ('INCOMPLETE', 'MISMATCH')


@pytest.mark.parametrize('corruption', ['raw', 'sidecar', 'missing_sidecar', 'canonical', 'missing_canonical'])
def test_cross_evidence_digests_fail_closed(evidence, corruption):
    baseline, counts = save_pair(evidence)
    sidecar = counts.with_suffix('.json.sha256')
    if corruption == 'raw':
        counts.write_bytes(counts.read_bytes() + b' ')
    elif corruption == 'sidecar':
        sidecar.write_text(bench.digest(b'wrong'))
    elif corruption == 'missing_sidecar':
        sidecar.unlink()
    else:
        payload = json.loads(counts.read_text())
        if corruption == 'canonical':
            payload['evidence']['sha256'] = bench.digest(b'wrong')
        else:
            payload.pop('evidence')
        counts.write_text(json.dumps(payload))
        sidecar.write_text(bench.digest(counts.read_bytes()))
    result = bench.compare_evidence(baseline, counts)
    assert result['fingerprint_comparison'] == 'INCOMPLETE' and result['comparison_error']


@_HISTORICAL_E1
def test_comparison_cli_runs_no_workload_and_preserves_inputs(monkeypatch, evidence):
    baseline, counts = save_pair(evidence)
    before = baseline.read_bytes(), counts.read_bytes()
    monkeypatch.setattr(bench, 'parent', lambda *a: pytest.fail('measurement ran'))
    monkeypatch.setattr(bench, 'prepare_workload', lambda *a: pytest.fail('fixture ran'))
    output = evidence / 'comparison.json'
    monkeypatch.setattr(sys, 'argv', ['e1', '--compare-baseline', str(baseline), '--compare-counts', str(counts),
                                     '--output', str(output)])
    assert bench.main() == 0
    result, _ = bench.read_evidence(output)
    assert result['fingerprint_comparison'] == 'MATCH'
    assert (baseline.read_bytes(), counts.read_bytes()) == before


@pytest.mark.parametrize('filename', sorted(bench.PROTECTED))
def test_archived_smoke_destinations_are_protected(evidence, filename):
    path = evidence / filename
    with pytest.raises(ValueError, match='protected'):
        bench.validate_output(path)
    with pytest.raises(ValueError, match='protected'):
        bench.write_report(path, {})
    assert not path.exists()


def test_comparison_requires_pair_and_rejects_outside_inputs(monkeypatch, evidence, tmp_path):
    args = options(compare_baseline=evidence / 'a.json')
    with pytest.raises(ValueError, match='both baseline and counts'):
        bench.controls(args)
    baseline, counts = save_pair(evidence)
    result = bench.compare_evidence(tmp_path / 'outside.json', counts)
    assert result['fingerprint_comparison'] == 'INCOMPLETE'
    assert 'outside' in result['comparison_error']
    with pytest.raises(ValueError, match='focused trace'):
        bench.controls(options(measurement_mode='counts', focused_trace=True))
    with pytest.raises(ValueError, match='hidden child'):
        bench.controls(options(child=True, measurement_mode='counts'))


def test_checkpoint_atomic_failure_preserves_previous_complete_records(monkeypatch, evidence):
    output = evidence / 'checkpoint.json'
    report = artifact('baseline')
    bench.write_report(output, report)
    previous = output.read_bytes()
    original_replace = Path.replace
    def fail_replace(path, target):
        if target == output:
            raise OSError('synthetic interrupted checkpoint')
        return original_replace(path, target)
    monkeypatch.setattr(Path, 'replace', fail_replace)
    report['diagnostic_status'] = 'in_progress'
    with pytest.raises(OSError, match='interrupted checkpoint'):
        bench.write_report(output, report)
    assert output.read_bytes() == previous
    bench.read_evidence(output)
    assert sorted(p.name for p in evidence.iterdir()) == ['checkpoint.json', 'checkpoint.json.sha256']


@pytest.mark.parametrize('hook', ['profile', 'trace', 'tracemalloc'])
def test_warm_priming_rejects_existing_instrumentation_without_work(monkeypatch, evidence, hook):
    fixture = SimpleNamespace(cache_stats=lambda: {'hits': 0})
    monkeypatch.setattr(bench, 'prepare_workload', lambda *a: (fixture,
        lambda *a, **k: pytest.fail('priming executed with external instrumentation'),
        None, ({},) * 6, bench.digest(b'fixture'), {}))
    def sentinel(*args):
        return sentinel
    try:
        if hook == 'tracemalloc':
            tracemalloc.start()
        else:
            (sys.setprofile if hook == 'profile' else sys.settrace)(sentinel)
        result = bench.child(options(cache_state='warm'))
        assert result['status'] == 'failed' and not result['runs'] and result['priming'] is None
        assert 'uninstrumented warm priming' in result['exception_message']
        if hook == 'tracemalloc':
            assert tracemalloc.is_tracing()
        else:
            assert (sys.getprofile if hook == 'profile' else sys.gettrace)() is sentinel
    finally:
        sys.setprofile(None)
        sys.settrace(None)
        if hook == 'tracemalloc':
            tracemalloc.stop()


@_HISTORICAL_E1
def test_combined_artifact_requires_all_numerical_members_to_match(evidence):
    baseline, counts = save_pair(evidence)
    left, _ = bench.read_evidence(baseline)
    right, _ = bench.read_evidence(counts)
    left.update(measurement_mode='both', fingerprint_comparison='MATCH')
    left['passes'].append(right['passes'][0])
    bench.write_report(baseline, left)
    assert bench.compare_evidence(baseline, counts)['fingerprint_comparison'] == 'MATCH'
    left['passes'][1]['runs'][0]['numerical_fingerprints']['physical'] = bench.digest(b'changed')
    bench.write_report(baseline, left)
    assert bench.compare_evidence(baseline, counts)['fingerprint_comparison'] == 'INCOMPLETE'


@_HISTORICAL_E1
@pytest.mark.parametrize('field,value', [('wall_cap_seconds', None), ('wall_cap_seconds', 901),
    ('wall_cap_seconds', '900'), ('memory_limit_mib', None), ('memory_limit_mib', 4097)])
def test_cross_evidence_requires_authorized_independent_limits(evidence, field, value):
    baseline, counts = save_pair(evidence)
    right, _ = bench.read_evidence(counts)
    if value is None:
        right['controls'].pop(field)
    else:
        right['controls'][field] = value
    bench.write_report(counts, right)
    report = bench.compare_evidence(baseline, counts)
    assert report['fingerprint_comparison'] == 'INCOMPLETE'
    assert 'independent resource limits' in report['comparison_error']
