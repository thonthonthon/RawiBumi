"""Bounded synthetic E2 contracts only; no fixture build, simulation or benchmark."""
from tests.unit._availability import missing_git, missing_private_path
import gc
import io
import inspect
import json
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import weakref

import pytest

from scripts.benchmarks import rb_post3d_08p2e2_memo_opportunity as bench
from shading.electrical import substring_reference as kernel, dc_attribution


def state():
    return kernel.AnalyticalRegionReferenceState('r', 'r', 's', 1,
        1000., 1000., 10., 20., 1., 20.)


def model(region=None):
    branches = [dict(branch_id='b', series_region_ids=['r'])]
    states = {'r': region or state()}
    return branches[0], states, kernel._BranchEndpointHolder(branches, states)


def call(branch, states, holder, voltage=1., **options):
    return kernel._branch_current_at_voltage(branch, states, voltage_v=voltage,
        _reuse=holder, **(dict(voltage_tolerance_v=1e-9, current_tolerance_a=1e-9,
                             max_iterations=200) | options))


def observer(**options):
    return bench.Observer(bench.Journal(io.BytesIO(), 4 * 1024**2), **options)


def event(key, *, actual='miss', success=True, admitted=True, slot=1, phase='producer', i_calls=0):
    return dict(slot=slot, phase=phase, key=bench.encode_key(key), actual=actual,
        success=success, admitted=admitted, uncached_calls=int(actual != 'hit'),
        i_from_v_calls=i_calls)


def key(voltage, tol=1e-9, iterations=200):
    return (float(voltage).hex(), tol, 1e-9, iterations)


def save_journal(path, raw):
    path.write_bytes(raw)
    Path(str(path) + '.sha256').write_text(bench.e1.digest(raw) + '\n')


def test_rank_replay_saturation_all_capacities_and_last_key():
    replay = bench.Replay(max_keys=5000)
    replay.register(1)
    for i in range(4100):
        replay.event(event(key(i), admitted=i < 256))
    replay.event(event(key(300), admitted=False, i_calls=7))
    replay.event(event(key(300), admitted=False, i_calls=9))
    replay.event(event(key(0), actual='hit', admitted=False))
    counts = replay.derived['producer']
    assert counts['256']['hits'] == 1
    assert counts['256']['misses'] == 4102
    for n in (512, 1024, 2048, 4096):
        assert counts[str(n)]['hits'] == 3
        assert counts[str(n)]['successful_admissions'] == n
        assert counts[str(n)]['potential_avoided_uncached_evaluations'] == 2
        assert counts[str(n)]['potential_avoided_observed_i_from_v'] == 16
    assert counts['bounded_unlimited']['successful_admissions'] == 4100
    assert counts['last_key']['hits'] == 1
    assert counts['last_key']['potential_additional_uncached_evaluations'] == 1
    assert counts['last_key']['counterfactual_minus_actual_uncached_evaluations'] == 0
    assert counts['256_plus_last_key']['hits'] == 2
    assert counts['256_plus_last_key']['potential_avoided_uncached_evaluations'] == 1
    assert counts['256_plus_last_key']['potential_avoided_observed_i_from_v'] == 9
    assert counts['256_plus_last_key']['potential_additional_uncached_evaluations'] == 0
    assert counts['256_plus_last_key']['counterfactual_minus_actual_uncached_evaluations'] == -1
    assert counts['1024']['counterfactual_minus_actual_uncached_evaluations'] == -2
    assert replay.memory()['modeled_incremental_bytes']['1024'] == 768 * bench.ENTRY_ESTIMATE


def test_failure_is_never_admitted_or_retained_as_last_key():
    replay = bench.Replay()
    replay.register(1)
    for _ in range(3):
        replay.event(event(key(1), success=False, admitted=False))
    assert not replay.slots[1].ranks and replay.slots[1].last is None
    replay.event(event(key(1)))
    assert replay.slots[1].ranks[key(1)] == 1
    with pytest.raises(ValueError, match='later failed'):
        replay.event(event(key(1), actual='hit', success=False, admitted=False))


@pytest.mark.parametrize('bad', [dict(actual='hit', admitted=False),
    dict(admitted=False), dict(uncached_calls=0)])
def test_256_must_reconcile_each_event(bad):
    replay = bench.Replay()
    replay.register(1)
    with pytest.raises(ValueError, match='reconciliation'):
        replay.event(event(key(1)) | bad)


def test_voltage_signed_zero_and_option_exact_equality():
    replay = bench.Replay()
    replay.register(1)
    for voltage in (0., -0.):
        replay.event(event(key(voltage)))
    assert len(replay.slots[1].ranks) == 2
    # Preserve raw types in evidence but use exactly production tuple equality.
    for option in (1, 1., True):
        original = (float(4).hex(), option, -0., 1)
        assert bench.decode_key(bench.encode_key(original)) == original
    zero1 = (float(4).hex(), 0., 0., 1)
    zero2 = (float(4).hex(), -0., -0., True)
    replay.event(event(zero1))
    replay.event(event(zero2, actual='hit', admitted=False))
    assert len(replay.slots[1].ranks) == 3


@pytest.mark.parametrize('item', [object(), float('nan'), float('inf'), 2**100, '1'])
def test_unknown_options_fail_without_conversion(item):
    with pytest.raises(ValueError, match='solver-option'):
        bench.encode_key((float(1).hex(), item, 1e-9, 200))


def test_bounded_no_cap_exhaustion_and_slot_exhaustion():
    replay = bench.Replay(max_slots=1, max_keys=2)
    replay.register(1)
    with pytest.raises(OverflowError, match='slot'):
        replay.register(2)
    replay.event(event(key(1)))
    replay.event(event(key(2)))
    with pytest.raises(OverflowError, match='key cap'):
        replay.event(event(key(3)))


def test_key_ceiling_defaults_and_planning_allowances():
    assert bench.MAX_KEYS == 3145728
    for constructor in (bench.Replay, bench.Observer, bench.verify_journal):
        assert inspect.signature(constructor).parameters['max_keys'].default == 3145728
    args = bench.parser().parse_args(['--output', 'unused.json', '--reference-e1', 'unused-e1.json',
        '--reference-e1-counts', 'unused-counts.json'])
    assert args.max_keys == 3145728
    bench.controls(args)
    replay = bench.Replay()
    assert not replay.slots and replay.keys == 0
    memory = replay.memory()
    assert memory['diagnostic_key_retention_allowance_bytes'] == 3072 * 1024**2
    assert memory['diagnostic_retention_allowance_bytes'] == 3104 * 1024**2
    assert memory['online_replay_allowance_bytes'] == memory['offline_replay_allowance_bytes'] == 3104 * 1024**2
    assert memory['sequential_verification_peak_allowance_bytes'] == 3136 * 1024**2
    assert memory['chronological_peak_incremental_production_bytes']['status'] == 'NOT_OBSERVED'
    assert args.max_events == bench.MAX_EVENTS == 150000000
    for constructor in (bench.Observer, bench.verify_journal):
        assert inspect.signature(constructor).parameters['max_events'].default == 150000000
    assert args.wall_cap_seconds == 900
    assert args.memory_limit_mib == 4096
    assert memory['target_bytes'] == 256 * 1024**2
    assert memory['observed_rss']['status'] == 'NOT_OBSERVED'


@pytest.mark.parametrize('maximum', [1, 3145728])
def test_key_ceiling_permitted_boundary_without_large_allocation(maximum):
    bench.controls(options(max_keys=maximum))
    replay = bench.Replay(max_keys=maximum)
    replay.register(1)
    # Seed only the global budget counter, representing prior retained slot keys.
    # The slot's real rank/equality/admission behavior still uses a tiny dictionary.
    replay.keys = maximum - 1
    replay.event(event(key(1)))
    assert replay.keys == maximum and len(replay.slots[1].ranks) == 1
    replay.event(event(key(1), actual='hit', admitted=False))
    replay.event(event(key(2), success=False, admitted=False))
    assert replay.keys == maximum and replay.slots[1].last == key(1)
    before = json.dumps(replay.derived, sort_keys=True)
    with pytest.raises(OverflowError, match='key cap'):
        replay.event(event(key(2)))
    assert json.dumps(replay.derived, sort_keys=True) == before
    assert replay.keys == maximum and replay.slots[1].ranks == {key(1): 1}
    assert replay.slots[1].last == key(1)


@pytest.mark.parametrize('maximum', [0, -1, 3145729])
def test_key_ceiling_rejected_by_all_configuration_paths(tmp_path, maximum):
    with pytest.raises(ValueError, match='max_keys'):
        bench.controls(options(max_keys=maximum))
    with pytest.raises(ValueError, match='max_keys'):
        bench.Replay(max_keys=maximum)
    with pytest.raises(ValueError, match='max_keys'):
        observer(max_keys=maximum)
    with pytest.raises(ValueError, match='max_keys'):
        bench.verify_journal(tmp_path / 'not-opened.jsonl', max_keys=maximum)


def test_offline_key_ceiling_and_global_slot_budget(tmp_path):
    path = tmp_path / 'bounded.jsonl'
    journal = bench.Journal(io.BytesIO(), 4096)
    for sequence, slot in enumerate((1, 2), 1):
        journal.append(event(key(1), slot=slot) | {'sequence': sequence})
    save_journal(path, journal.stream.getvalue())
    assert bench.verify_journal(path, max_keys=3145728)['events'] == 2
    assert bench.verify_journal(path, max_keys=2)['events'] == 2
    with pytest.raises(OverflowError, match='key cap'):
        bench.verify_journal(path, max_keys=1)


def test_256_plus_last_key_before_and_after_saturation(tmp_path):
    replay = bench.Replay()
    replay.register(1)
    journal = bench.Journal(io.BytesIO(), 1024**2)
    def access(k, *, actual='miss', admitted=False, success=True, hybrid_hit=False, i_calls=0):
        assert replay.slots[1].predict(k)['256_plus_last_key'] is hybrid_hit
        row = event(k, actual=actual, admitted=admitted, success=success, i_calls=i_calls)
        replay.event(row)
        journal.append(row | {'sequence': journal.events + 1})
    access(key(0), admitted=True)
    access(key(1), admitted=True)
    access(key(0), actual='hit', hybrid_hit=True)
    for i in range(2, 256):
        access(key(i), admitted=True)
    first_256 = dict(replay.slots[1].ranks)
    access(key(300))  # nonrepeated unadmitted key is a miss
    access(key(300), hybrid_hit=True, i_calls=7)  # repeated unadmitted key
    access(key(301))
    access(key(302), success=False)  # failure must preserve last successful key
    access(key(302), success=False)
    assert replay.slots[1].last == key(301)
    access(key(301), hybrid_hit=True, i_calls=9)
    access(key(0), actual='hit', hybrid_hit=True)  # returning to an admitted key
    assert replay.slots[1].last == key(0)
    access(key(301))  # successful actual hit above must have updated last key
    assert {k: v for k, v in replay.slots[1].ranks.items() if v <= 256} == first_256
    counts = replay.derived['producer']['256_plus_last_key']
    assert counts['hits'] == 4 and counts['misses'] == 261
    assert counts['successful_admissions'] == 259
    assert counts['potential_avoided_uncached_evaluations'] == 2
    assert counts['potential_avoided_observed_i_from_v'] == 16
    assert counts['potential_additional_uncached_evaluations'] == 0
    assert counts['counterfactual_minus_actual_uncached_evaluations'] == -2
    assert replay.memory()['modeled_incremental_bytes']['256_plus_last_key'] == bench.ENTRY_ESTIMATE
    path = tmp_path / 'hybrid.jsonl'
    save_journal(path, journal.stream.getvalue())
    assert bench.verify_journal(path)['counterfactuals'] == replay.derived


def test_256_plus_last_key_exact_signed_zero_and_options_after_saturation(tmp_path):
    replay = bench.Replay()
    replay.register(1)
    journal = bench.Journal(io.BytesIO(), 1024**2)
    for i in range(1, 257):
        row = event(key(i), admitted=i <= 256)
        replay.event(row)
        journal.append(row | {'sequence': journal.events + 1})
    zero1 = (float(0.).hex(), 0., 0., 1)
    zero2 = (float(-0.).hex(), -0., -0., True)
    zero3 = (float(-0.).hex(), 0, 0., 1.)
    for k, expected in ((zero1, False), (zero2, False), (zero3, True), (zero1, False), (zero1, True)):
        assert replay.slots[1].predict(k)['256_plus_last_key'] is expected
        row = event(k, admitted=False)
        replay.event(row)
        journal.append(row | {'sequence': journal.events + 1})
    assert replay.derived['producer']['256_plus_last_key']['hits'] == 2
    path = tmp_path / 'zero.jsonl'
    save_journal(path, journal.stream.getvalue())
    assert bench.verify_journal(path)['counterfactuals'] == replay.derived


def test_256_plus_last_key_online_independent_branch_slots(monkeypatch, tmp_path):
    monkeypatch.setattr(kernel, '_branch_current_at_voltage_uncached', lambda *args, **kwargs: 7.)
    observed = observer()
    with observed.installed():
        observed.phase = 'producer'
        branches = [dict(branch_id=name, series_region_ids=['r']) for name in ('a', 'b')]
        states = {'r': state()}
        holder = kernel._BranchEndpointHolder(branches, states)
        for branch in branches:
            for i in range(256):
                call(branch, states, holder, i)
        call(branches[0], states, holder, 300.)
        call(branches[1], states, holder, 300.)  # other slot must still miss
        call(branches[0], states, holder, 301.)
        call(branches[1], states, holder, 300.)  # other's access cannot replace this last key
        call(branches[0], states, holder, 300.)  # no eviction of the first 256
        call(branches[0], states, holder, 0.)
        assert all(len(holder.bind(b, states).currents) == 256 for b in branches)
    report = observed.report(('producer',))
    assert report['status'] == 'COMPLETED', report['reasons']
    assert report['slot_lifetimes_observed'] == 2
    counts = report['counterfactuals']['producer']['256_plus_last_key']
    assert counts['hits'] == 2 and counts['misses'] == 516
    assert counts['potential_avoided_uncached_evaluations'] == 1
    assert counts['potential_additional_uncached_evaluations'] == 0
    assert report['direct_observations']['producer']['admissions'] == 512
    assert report['direct_observations']['producer']['hits'] == 1
    path = tmp_path / 'slots.jsonl'
    save_journal(path, observed.journal.stream.getvalue())
    assert bench.verify_journal(path)['counterfactuals'] == json.loads(json.dumps(report))['counterfactuals']


def test_wrapper_real_256_misses_independent_profile_journal_and_restore(tmp_path):
    old = sys.getprofile(), sys.gettrace(), kernel._branch_current_at_voltage, dc_attribution._branch_current_at_voltage
    observed = observer()
    with observed.installed():
        b, states, holder = model()
        observed.phase = 'producer'
        for i in range(258):
            call(b, states, holder, i / 100.)
        for voltage in (0., 2.57, 2.57):
            call(b, states, holder, voltage)
        assert len(holder.bind(b, states).currents) == 256
    assert (sys.getprofile(), sys.gettrace(), kernel._branch_current_at_voltage,
            dc_attribution._branch_current_at_voltage) == old
    report = observed.report(required_phases=('producer',))
    assert report['status'] == 'COMPLETED', report['reasons']
    direct = report['direct_observations']['producer']
    assert direct['hits'] == 1 and direct['misses'] == 260
    assert direct['original_uncached_calls'] == 260
    assert direct['admissions'] == 256 and direct['saturation_rejections'] == 4
    assert report['counterfactuals']['producer']['512']['potential_avoided_uncached_evaluations'] == 2
    hybrid = report['counterfactuals']['producer']['256_plus_last_key']
    assert hybrid['hits'] == 2 and hybrid['potential_avoided_uncached_evaluations'] == 1
    assert hybrid['potential_additional_uncached_evaluations'] == 0
    journal = tmp_path / 'synthetic.jsonl'
    save_journal(journal, observed.journal.stream.getvalue())
    assert bench.verify_journal(journal) == (report['exact_stream'] | {'counterfactuals': report['counterfactuals']})


def test_completed_report_requires_hybrid_counts_and_memory():
    observed = observer()
    with observed.installed():
        for phase in ('producer', 'attribution', 'b2_numerical_acceptance'):
            observed.phase = phase
            observed.context = 'producer' if phase == 'b2_numerical_acceptance' else None
            b, states, holder = model()
            call(b, states, holder)
    report = dict(status='COMPLETED', observation=observed.report(), overflow=False,
        hook_failure=None, numerical_comparison='MATCH', independent_journal_verification='MATCH',
        journal_sidecar_verification='MATCH',
        independent_e1_call_counts='MATCH', cache_selection='warm', modules=10,
        source_hashes={'synthetic': 'unchanged'}, source_hashes_after={'synthetic': 'unchanged'},
        harness_sha256='unchanged', harness_sha256_after='unchanged')
    report['sequential_verification'] = dict(online_replay_released=True,
        observation_snapshot_sha256=bench.e1.digest(bench.observation_bytes(report['observation'])))
    args = options()
    args.cache_state = 'warm'
    serialized = json.loads(json.dumps(report))
    assert bench.completed_child(serialized, args)
    assert 'Same eligible exact access stream' in serialized['observation']['hypotheses']
    del serialized['observation']['counterfactuals']['producer']['256_plus_last_key']
    serialized['sequential_verification']['observation_snapshot_sha256'] = bench.e1.digest(
        bench.observation_bytes(serialized['observation']))
    assert not bench.completed_child(serialized, args)
    serialized = json.loads(json.dumps(report))
    del serialized['observation']['memory']['modeled_incremental_bytes']['256_plus_last_key']
    serialized['sequential_verification']['observation_snapshot_sha256'] = bench.e1.digest(
        bench.observation_bytes(serialized['observation']))
    assert not bench.completed_child(serialized, args)
    for field in ('diagnostic_key_retention_allowance_bytes', 'online_replay_allowance_bytes',
                  'offline_replay_allowance_bytes', 'sequential_verification_peak_allowance_bytes',
                  'chronological_peak_incremental_production_bytes'):
        serialized = json.loads(json.dumps(report))
        del serialized['observation']['memory'][field]
        serialized['sequential_verification']['observation_snapshot_sha256'] = bench.e1.digest(
            bench.observation_bytes(serialized['observation']))
        assert not bench.completed_child(serialized, args)
    for field in ('journal_sidecar_verification', 'sequential_verification'):
        serialized = json.loads(json.dumps(report))
        del serialized[field]
        assert not bench.completed_child(serialized, args)


def test_signed_zero_tolerances_iterations_and_model_identity():
    observed = observer()
    with observed.installed():
        observed.phase = 'producer'
        b, states, holder = model()
        b2, states2, holder2 = model()
        for voltage in (0., -0., 0., -0.):
            call(b, states, holder, voltage)
        call(b, states, holder, 1., voltage_tolerance_v=1e-10)
        call(b, states, holder, 1., current_tolerance_a=1e-10)
        call(b, states, holder, 1., max_iterations=1)
        call(b2, states2, holder2, 0.)
    report = observed.report(('producer',))
    assert report['status'] == 'COMPLETED', report['reasons']
    assert report['direct_observations']['producer']['hits'] == 2
    assert report['successful_keys_retained'] == 6
    assert report['slot_lifetimes_observed'] == 2


def test_generic_one_iteration_exhaustion_preserves_exact_value():
    b = dict(series_region_ids=['r', 'r2'])
    states = {'r': state(), 'r2': state()}
    expected = call(b, states, None, max_iterations=1)
    assert expected == 5.
    observed = observer()
    with observed.installed():
        observed.phase = 'producer'
        holder = kernel._BranchEndpointHolder([b], states)
        assert call(b, states, holder, max_iterations=1) == expected
        assert call(b, states, holder, max_iterations=1) == expected
    report = observed.report(('producer',))
    assert report['status'] == 'COMPLETED', report['reasons']
    assert report['direct_observations']['producer']['hits'] == 1


@pytest.mark.parametrize('error', [ValueError('original sentinel'),
    KeyboardInterrupt('original sentinel'), SystemExit(7)])
def test_original_failure_identity_and_failure_admission(monkeypatch, error):
    calls = []
    def uncached(*args, **kwargs):
        calls.append(kwargs['voltage_v'])
        raise error
    monkeypatch.setattr(kernel, '_branch_current_at_voltage_uncached', uncached)
    observed = observer()
    with observed.installed():
        observed.phase = 'producer'
        b, states, holder = model()
        for _ in range(2):
            with pytest.raises(type(error)) as caught:
                call(b, states, holder)
            assert caught.value is error
        assert not holder.bind(b, states).currents
    assert calls == [1., 1.]
    report = observed.report(('producer',))
    assert report['status'] == 'COMPLETED', report['reasons']
    assert report['direct_observations']['producer']['failures'] == 2
    assert report['successful_keys_retained'] == 0
    hybrid = report['counterfactuals']['producer']['256_plus_last_key']
    assert hybrid['hits'] == 0 and hybrid['misses'] == 2
    assert hybrid['successful_admissions'] == 0
    assert all(s.last is None for s in observed.replay.slots.values())


def test_observer_fault_cannot_replace_result_exception_or_admission(monkeypatch):
    error, result = ValueError('original'), object()
    calls = []
    def uncached(*args, **kwargs):
        calls.append(kwargs['voltage_v'])
        if kwargs['voltage_v'] == 2.:
            raise error
        return result
    monkeypatch.setattr(kernel, '_branch_current_at_voltage_uncached', uncached)
    observed = observer()
    monkeypatch.setattr(observed.journal, 'append', lambda event: (_ for _ in ()).throw(RuntimeError('sink error')))
    with observed.installed():
        b, states, holder = model()
        assert call(b, states, holder) is result
        assert call(b, states, holder) is result
        with pytest.raises(ValueError) as caught:
            call(b, states, holder, 2.)
        assert caught.value is error
        assert len(holder.bind(b, states).currents) == 1
    assert calls == [1., 2.]
    assert observed.report(())['status'] == 'INCOMPLETE'
    assert not observed.pending and not observed.active_memos


def test_telemetry_exception_with_hostile_attribute_access_cannot_escape(monkeypatch):
    class Fault(Exception):
        def __getattribute__(self, name):
            if name == 'args':
                raise AssertionError('observer inspected custom exception')
            return super().__getattribute__(name)
        def __str__(self):
            raise AssertionError('observer stringified custom exception')
    observed = observer()
    def sink(event):
        raise Fault('sink fault')
    monkeypatch.setattr(observed.journal, 'append', sink)
    with observed.installed():
        b, states, holder = model()
        assert call(b, states, holder) == 9.5
        assert len(holder.bind(b, states).currents) == 1
    assert observed.report(())['status'] == 'INCOMPLETE'


def test_unknown_types_stateful_callable_and_changed_bindings_bypass():
    class Custom:
        current_ceiling_a = 20.
        def __init__(self):
            self.calls = []
        def voltage_at_current(self, current):
            self.calls.append(('v', current))
            return 20. - current
        def current_at_voltage(self, voltage):
            self.calls.append(('i', voltage))
            return 20. - voltage
    custom = Custom()
    observed = observer()
    with observed.installed():
        observed.phase = 'producer'
        b, states, holder = model(custom)
        for _ in range(2):
            assert call(b, states, holder) == 19.
        assert not holder.bind(b, states).currents
        # Original endpoint reuse still occurs on the unknown region path.
        assert custom.calls == [('v', 0.), ('v', 20.), ('i', 1.), ('i', 1.)]
        b2, states2, holder2 = model()
        call(b2, dict(states2), holder2)
        call(dict(b2), states2, holder2)
        states2['r'] = state()
        call(b2, states2, holder2)
        b2['series_region_ids'] = ['r', 'r']
        call(b2, states2, holder2, max_iterations=1)
    report = observed.report(('producer',))
    assert report['status'] == 'COMPLETED', report['reasons']
    assert report['direct_observations']['producer']['bypasses'] == 6
    assert report['successful_keys_retained'] == 0


def test_exact_subclass_is_ineligible():
    class Subclass(kernel.AnalyticalRegionReferenceState):
        pass
    region = Subclass(**vars(state()))
    observed = observer()
    with observed.installed():
        observed.phase = 'producer'
        b, states, holder = model(region)
        call(b, states, holder)
        call(b, states, holder)
    assert observed.report(('producer',))['direct_observations']['producer']['bypasses'] == 2


def test_unknown_option_observation_does_not_add_hash_or_compare_calls():
    class Tolerance(float):
        def __hash__(self):
            seen.append('hash')
            return super().__hash__()
    seen = []
    b, states, holder = model()
    call(b, states, holder, voltage_tolerance_v=Tolerance(1e-9))
    expected = seen[:]
    seen.clear()
    observed = observer()
    with observed.installed():
        b, states, holder = model()
        call(b, states, holder, voltage_tolerance_v=Tolerance(1e-9))
    assert seen == expected
    assert observed.report(())['status'] == 'INCOMPLETE'


def test_missing_original_wrapper_preexisting_holder_and_missing_phase_fail_closed():
    old = kernel._branch_current_at_voltage
    observed = observer()
    with observed.installed():
        b, states, holder = model()
        old(b, states, voltage_v=1., _reuse=holder, voltage_tolerance_v=1e-9,
            current_tolerance_a=1e-9, max_iterations=200)
    assert observed.report(())['status'] == 'INCOMPLETE'
    b, states, holder = model()
    observed2 = observer()
    with observed2.installed():
        call(b, states, holder)
    assert 'holder lifetime' in observed2.fault
    observed3 = observer()
    with observed3.installed():
        b, states, holder = model()
        call(b, states, holder)
    assert observed3.report()['status'] == 'INCOMPLETE'
    assert observed3.report()['counterfactuals']['status'] == 'NOT_OBSERVED'


def test_holder_lifetime_not_extended_and_replacement_never_shared():
    observed = observer()
    with observed.installed():
        observed.phase = 'producer'
        region = state()
        reference = weakref.ref(region)
        b, states, holder = model(region)
        call(b, states, holder)
        del b, states, holder, region
        gc.collect()
        assert reference() is None
        b, states, holder = model()
        call(b, states, holder)
    assert observed.report(('producer',))['status'] == 'COMPLETED'
    assert observed.replay.keys == 2


@pytest.mark.parametrize('kind', ['event', 'slot', 'key', 'journal'])
def test_overflow_preserves_solver_and_fails_closed(kind):
    options = {'max_events': 1} if kind == 'event' else {'max_slots': 1} if kind == 'slot' else {'max_keys': 1} if kind == 'key' else {}
    observed = observer(**options)
    if kind == 'journal':
        observed.journal.byte_cap = 1
    with observed.installed():
        b, states, holder = model()
        assert call(b, states, holder) == 9.5
        assert call(b, states, holder, 2.) == 9.
        if kind == 'slot':
            model()
        assert len(holder.bind(b, states).currents) == 2
    assert observed.report(())['status'] == 'OVERFLOW'
    assert sys.getprofile() is None and sys.gettrace() is None


def test_cleanup_on_external_exception_and_exclusive_hooks():
    error = RuntimeError('scope error')
    original = kernel._branch_current_at_voltage
    observed = observer()
    with pytest.raises(RuntimeError) as caught:
        with observed.installed():
            b, states, holder = model()
            call(b, states, holder)
            raise error
    assert caught.value is error and kernel._branch_current_at_voltage is original
    sentinel = lambda *args: None
    sys.setprofile(sentinel)
    try:
        with pytest.raises(RuntimeError, match='exclusive'):
            with observer().installed():
                pytest.fail('existing hook overwritten')
        assert sys.getprofile() is sentinel
    finally:
        sys.setprofile(None)


def test_alias_imported_during_observation_restored_after_fault(monkeypatch):
    module = ModuleType('synthetic_memo_alias')
    monkeypatch.setitem(sys.modules, module.__name__, module)
    original = kernel._branch_current_at_voltage
    observed = observer(max_events=1)
    with observed.installed():
        module.memo = kernel._branch_current_at_voltage
        b, states, holder = model()
        call(b, states, holder)
    assert module.memo is original
    assert observed.report(())['status'] == 'OVERFLOW'


def test_changed_bindings_and_hooks_detected_without_overwriting_foreign_changes(monkeypatch):
    observed = observer()
    original = dc_attribution._branch_current_at_voltage
    sentinel = lambda *args, **kwargs: 42
    try:
        with observed.installed():
            b, states, holder = model()
            call(b, states, holder)
            dc_attribution._branch_current_at_voltage = sentinel
        assert dc_attribution._branch_current_at_voltage is sentinel
    finally:
        dc_attribution._branch_current_at_voltage = original
    assert observed.report(())['status'] == 'INCOMPLETE'
    observed2 = observer()
    with observed2.installed():
        sys.settrace(None)
    assert observed2.report(())['status'] == 'INCOMPLETE'


def test_phases_b2_contexts_and_observed_descendant_kernel_calls(monkeypatch):
    import pvlib
    def i_from_v():
        return 1.
    def uncached(*args, **kwargs):
        return pvlib.pvsystem.i_from_v()
    monkeypatch.setattr(pvlib.pvsystem, 'i_from_v', i_from_v)
    monkeypatch.setattr(kernel, '_branch_current_at_voltage_uncached', uncached)
    observed = observer()
    def producer():
        call(b, states, holder)
        b2()
        call(b, states, holder)
    def attribution():
        call(b, states, holder)
        b2()
    def b2():
        newb, news, newh = model()
        call(newb, news, newh)
    observed.phase_codes.update({producer.__code__: 'producer', attribution.__code__: 'attribution',
                                b2.__code__: 'b2_numerical_acceptance'})
    with observed.installed():
        b, states, holder = model()
        producer()
        attribution()
    report = observed.report()
    assert report['status'] == 'COMPLETED', report['reasons']
    assert report['direct_observations']['producer']['hits'] == 1
    assert report['direct_observations']['producer']['i_from_v_calls'] == 1
    assert report['direct_observations']['b2_numerical_acceptance']['i_from_v_calls'] == 2
    assert report['b2_parent_contexts']['producer']['memo_calls'] == 1
    assert report['b2_parent_contexts']['attribution']['memo_calls'] == 1


def options(**changes):
    return SimpleNamespace(**(dict(modules=10, intervals=1, workers=1, wall_cap_seconds=900.,
        memory_limit_mib=4096, max_events=150000000, max_slots=4096, max_keys=3145728,
        journal_limit_mib=2048) | changes))


@pytest.mark.parametrize('change', [dict(modules=190), dict(intervals=2), dict(workers=2),
    dict(wall_cap_seconds=0), dict(wall_cap_seconds=2401), dict(wall_cap_seconds=math.nan),
    dict(memory_limit_mib=4097), dict(max_events=150000001), dict(max_slots=4097),
    dict(max_keys=3145729), dict(journal_limit_mib=2049)])
def test_resource_controls_without_workload_execution(change):
    with pytest.raises(ValueError):
        bench.controls(options(**change))


def test_output_separate_from_e1_and_all_companions_protected(monkeypatch, tmp_path):
    root = tmp_path / 'e2'
    root.mkdir()
    monkeypatch.setattr(bench, 'EVIDENCE', root)
    assert bench.validate_output(root / 'new.json') == root / 'new.json'
    with pytest.raises(ValueError, match='inside'):
        bench.validate_output(tmp_path / 'e1' / 'old.json')
    (root / 'bad.json.events.jsonl').symlink_to(tmp_path / 'external')
    with pytest.raises(ValueError):
        bench.validate_output(root / 'bad.json')
    (root / 'existing.json.child.json').write_text('{}')
    with pytest.raises(ValueError, match='exists'):
        bench.validate_output(root / 'existing.json')


def test_offline_journal_rejects_truncation_and_caps(tmp_path):
    path = tmp_path / 'journal'
    save_journal(path, b'{}')
    with pytest.raises(OverflowError):
        bench.verify_journal(path)
    save_journal(path, b'x' * 4097 + b'\n')
    with pytest.raises(OverflowError):
        bench.verify_journal(path)


@pytest.mark.parametrize('kind', ['wall', 'memory', 'rss_missing', 'no_output', 'invalid_output', 'incomplete_coverage'])
def test_watchdog_or_missing_coverage_never_completes(monkeypatch, tmp_path, kind):
    root = tmp_path / 'e2'
    root.mkdir()
    monkeypatch.setattr(bench, 'EVIDENCE', root)
    args = options()
    args.output = root / 'future.json'
    args.reference_e1 = e1_path(10)
    args.reference_e1_counts = bench.e1.EVIDENCE / 'r3-10-counts-warm.json'
    args.cache_state = 'warm'
    args.child = False
    stopped = []
    class Process:
        pid = 123456789
        returncode = 0
        def poll(self):
            return 0 if kind in ('no_output', 'invalid_output', 'incomplete_coverage') else None
    process = Process()
    monkeypatch.setattr(bench.subprocess, 'Popen', lambda *a, **k: process)
    monkeypatch.setattr(bench.e1, 'stop', lambda p: stopped.append(p))
    monkeypatch.setattr(bench.e1, 'resident_bytes', lambda pid: None if kind == 'rss_missing' else
                        5000 * 1024**2 if kind == 'memory' else 1)
    now = iter([0., 1. if kind == 'memory' else 901.])
    monkeypatch.setattr(bench.time, 'monotonic', lambda: next(now))
    if kind in ('invalid_output', 'incomplete_coverage'):
        child = Path(str(args.output) + '.child.json')
        if kind == 'invalid_output':
            child.write_bytes(b'broken')
        else:
            bench.write_report(child, {'status': 'COMPLETED'})
    report = bench.parent(args)
    assert report['status'] != 'COMPLETED'
    assert stopped == [process]
    assert args.output.exists()
    assert report['status'] == ('MEMORY_CAPPED' if kind == 'memory' else 'WALL_CAPPED'
        if kind in ('wall', 'rss_missing') else 'INCOMPLETE' if kind == 'incomplete_coverage' else 'FAILED')


def test_foreign_thread_wrapper_still_delegates_once_and_invalidates(monkeypatch):
    import threading
    calls, results = [], []
    def uncached(*args, **kwargs):
        calls.append(1)
        return 7.
    monkeypatch.setattr(kernel, '_branch_current_at_voltage_uncached', uncached)
    observed = observer()
    with observed.installed():
        b, states, holder = model()
        worker = threading.Thread(target=lambda: results.append(call(b, states, holder)))
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert calls == [1] and results == [7.]
    assert observed.report(())['status'] == 'INCOMPLETE'


@pytest.mark.parametrize('max_frames,status', [(1, 'OVERFLOW'), (256, 'INCOMPLETE')])
def test_nested_callable_stream_or_frame_cap_preserves_original_exception(monkeypatch, max_frames, status):
    error = ValueError('nested original')
    def uncached(*args, **kwargs):
        if kwargs['voltage_v'] == 1.:
            return call(*args, kwargs['_reuse'], 2.)
        raise error
    monkeypatch.setattr(kernel, '_branch_current_at_voltage_uncached', uncached)
    observed = observer(max_frames=max_frames)
    with observed.installed():
        b, states, holder = model()
        with pytest.raises(ValueError) as caught:
            call(b, states, holder)
        assert caught.value is error
    assert observed.report(())['status'] == status


def test_independent_e1_call_count_mismatch_rejected():
    observed = observer()
    with observed.installed():
        observed.phase = 'producer'
        b, states, holder = model()
        call(b, states, holder)
    report = observed.report(('producer',))
    counters = {p: {} for p in bench.PHASES}
    counters['producer'] = {'synthetic:_branch_current_at_voltage:calls': 1,
                            'synthetic:_branch_current_at_voltage_uncached:calls': 1}
    ref = {'passes': [{'measurement_mode': 'counts', 'runs': [
        {'cache_state': 'warm_physics_cache', 'counters': counters}]}]}
    assert bench.compare_direct_counts(report, ref, 'warm') == 'MATCH'
    counters['producer']['synthetic:_branch_current_at_voltage_uncached:calls'] = 2
    with pytest.raises(ValueError, match='actual call-count mismatch'):
        bench.compare_direct_counts(report, ref, 'warm')


@pytest.mark.parametrize('avoided,extra,decision', [(117494, 0, 'CALL_SCREEN_NOT_MET'),
    (117494, 256 * 1024**2 + 1, 'CALL_SCREEN_NOT_MET'),
    (117495, 256 * 1024**2, 'SCREEN_MET'), (117495, 256 * 1024**2 + 1, 'MEMORY_SCREEN_INCONCLUSIVE')])
def test_whole_run_screening_threshold_and_memory_target(avoided, extra, decision):
    args = options(modules=50)
    args.cache_state = 'warm'
    observation = dict(direct_observations={'producer': {'i_from_v_calls': 2349889}},
        counterfactuals={'producer': {'1024': {'potential_avoided_observed_i_from_v': avoided}}},
        memory={'modeled_incremental_bytes': {'1024': extra}})
    report = dict(status='COMPLETED', child={'observation': observation})
    result = bench.screening(report, args)
    assert result['decision'] == decision
    assert result['memory_screen'] == ('MEMORY_SCREEN_MET' if extra <= 256 * 1024**2
        else 'MEMORY_SCREEN_INCONCLUSIVE')
    assert result['estimated_memory_target_established'] is (extra <= 256 * 1024**2)
    assert result['chronological_peak_incremental_production_bytes']['status'] == 'NOT_OBSERVED'
    args.modules = 10
    assert bench.screening(report, args)['decision']['status'] == 'NOT_OBSERVED'


def test_cli_commands_parse_without_running_and_reference_remains_read_only():
    # Signed E1 fixtures are historical evidence, not live references after
    # source evolution. Verify their checksum sidecars, demonstrate the exact
    # source-set/source-value drift, and require fail-closed rejection.
    bench.controls(options())
    expected_missing = {'shading/electrical/branch_memo_lifecycle.py'}
    expected_changed = {
        'shading/electrical/dc_attribution.py',
        'shading/electrical/module_series_adapter.py',
    }
    for modules in (10, 50):
        if reason := missing_private_path(str(e1_path(modules).relative_to(bench.e1.ROOT))) or missing_private_path(str((bench.e1.EVIDENCE / f'r3-{modules}-counts-warm.json').relative_to(bench.e1.ROOT))):
            pytest.skip(reason)
        args = bench.parser().parse_args(['--modules', str(modules), '--cache-state', 'warm',
            '--output', str(bench.EVIDENCE / f'reviewed-{modules}-warm.json'),
            '--reference-e1', str(e1_path(modules)), '--reference-e1-counts',
            str(bench.e1.EVIDENCE / f'r3-{modules}-counts-warm.json')])
        baseline, baseline_digest = bench.e1.read_evidence(args.reference_e1)
        counts, counts_digest = bench.e1.read_evidence(args.reference_e1_counts)
        assert len(baseline_digest) == len(counts_digest) == 64
        assert baseline['controls']['modules'] == modules
        assert counts['controls']['modules'] == modules
        assert counts['measurement_mode'] == 'counts'
        recorded = baseline['metadata']['source_hashes']
        assert recorded == counts['metadata']['source_hashes']
        assert set(bench.e1.SOURCE_FILES) - set(recorded) == expected_missing
        assert set(recorded) - set(bench.e1.SOURCE_FILES) == set()
        current = bench.e1.hashes(tuple(recorded))
        # Later authorized source edits may add drift; these historical changes must remain.
        assert expected_changed <= {path for path in recorded if current[path] != recorded[path]}
        with pytest.raises(ValueError, match='incomplete relevant source hashes'):
            bench.reference(args)


def e1_path(modules):
    return bench.e1.EVIDENCE / f'r3-{modules}-baseline-warm.json'


@pytest.mark.parametrize('maximum', [1, 150000000])
def test_event_ceiling_inclusive_without_large_allocation(maximum):
    bench.controls(options(max_events=maximum))
    observed = observer(max_events=maximum)
    observed.events = maximum - 1
    with observed.installed():
        b, states, holder = model()
        assert call(b, states, holder) == 9.5
        assert call(b, states, holder, 2.) == 9.
    assert observed.events == maximum
    assert observed.overflow and observed.report(())['status'] == 'OVERFLOW'
    assert len(holder.bind(b, states).currents) == 2


@pytest.mark.parametrize('maximum', [0, -1, 150000001])
def test_event_ceiling_rejected_everywhere(tmp_path, maximum):
    for constructor in (lambda: bench.controls(options(max_events=maximum)),
                        lambda: observer(max_events=maximum),
                        lambda: bench.verify_journal(tmp_path / 'missing', max_events=maximum)):
        with pytest.raises(ValueError, match='max_events'):
            constructor()


@pytest.mark.parametrize('seconds', [1, 900, 901, 2400])
def test_wall_cap_permitted_without_execution(seconds):
    bench.controls(options(wall_cap_seconds=seconds))


@pytest.mark.parametrize('seconds', [-1, 2400.1, math.inf, -math.inf])
def test_wall_cap_invalid_without_execution(seconds):
    with pytest.raises(ValueError, match='wall cap'):
        bench.controls(options(wall_cap_seconds=seconds))


@pytest.mark.parametrize('damage', ['missing', 'corrupt', 'mismatch', 'partial', 'empty'])
def test_independent_journal_integrity_fails_closed(tmp_path, damage):
    path = tmp_path / 'events.jsonl'
    journal = bench.Journal(io.BytesIO(), 4096)
    journal.append(event(key(1)) | {'sequence': 1})
    path.write_bytes(journal.stream.getvalue())
    bench.write_journal_sidecar(path, journal.identity())
    sidecar = Path(str(path) + '.sha256')
    if damage == 'missing':
        sidecar.unlink()
    elif damage == 'corrupt':
        sidecar.write_text('invalid\n')
    elif damage == 'mismatch':
        sidecar.write_text('0' * 64 + '\n')
    elif damage == 'partial':
        path.write_bytes(path.read_bytes()[:-1])
    else:
        save_journal(path, b'')
    for verify in (lambda: bench.verify_journal(path),
                   lambda: bench.verify_journal_bytes(path, 4096)):
        with pytest.raises((OSError, ValueError, OverflowError)):
            verify()


def test_journal_sidecar_exclusive_and_short_write_not_publishable(monkeypatch, tmp_path):
    path = tmp_path / 'short.jsonl'
    class ShortStream(io.BytesIO):
        def write(self, raw):
            return super().write(raw[:len(raw) // 2])
    journal = bench.Journal(ShortStream(), 4096)
    with pytest.raises(OSError, match='short'):
        journal.append(event(key(1)) | {'sequence': 1})
    path.write_bytes(journal.stream.getvalue())
    with pytest.raises(ValueError, match='incomplete'):
        bench.write_journal_sidecar(path, journal.identity())
    assert not Path(str(path) + '.sha256').exists()
    complete = bench.Journal(io.BytesIO(), 4096)
    complete.append(event(key(1)) | {'sequence': 1})
    path.write_bytes(complete.stream.getvalue())
    bench.write_journal_sidecar(path, complete.identity())
    with pytest.raises(FileExistsError):
        bench.write_journal_sidecar(path, complete.identity())
    monkeypatch.setattr(bench, 'EVIDENCE', tmp_path)
    companion = tmp_path / 'occupied.json.events.jsonl.sha256'
    companion.write_text('occupied')
    with pytest.raises(ValueError, match='exists'):
        bench.validate_output(tmp_path / 'occupied.json')


@pytest.fixture
def synthetic_child(monkeypatch, tmp_path):
    """Real observer and child orchestration; replace all workload dispatch."""
    if reason := missing_git() or missing_private_path('.ai/TASK.md'):
        pytest.skip(reason)
    monkeypatch.setattr(bench, 'EVIDENCE', tmp_path)
    args = options(output=tmp_path / 'synthetic.json', cache_state='warm', child=True,
        reference_e1=tmp_path / 'baseline.json', reference_e1_counts=tmp_path / 'counts.json')
    identity = {'synthetic': True}
    measured = {'cache_state': 'warm_physics_cache'}
    counts = {phase: {} for phase in bench.PHASES}
    for phase in ('producer', 'attribution', 'b2_numerical_acceptance'):
        counts[phase] = {'synthetic:_branch_current_at_voltage:calls': 2,
                        'synthetic:_branch_current_at_voltage_uncached:calls': 1}
    baseline = {'passes': [dict(measurement_mode='baseline', fixture_identity=identity, runs=[measured])]}
    count_ref = {'passes': [dict(measurement_mode='counts', runs=[dict(
        cache_state='warm_physics_cache', counters=counts)])]}
    monkeypatch.setattr(bench, 'reference', lambda args: (baseline, 'synthetic', count_ref, 'synthetic'))
    monkeypatch.setattr(bench.e1, 'prepare_workload', lambda modules:
        (None, None, None, None, identity, {'loaded_repository_source_hashes': {}}))
    monkeypatch.setattr(bench.e1, 'run_identity', lambda run, cache: run)
    original_observer, instances, report_calls = bench.Observer, [], []
    def make_observer(*a, **kw):
        observed = original_observer(*a, **kw)
        original_report = observed.report
        def report_once(*a, **kw):
            report_calls.append(1)
            return original_report(*a, **kw)
        monkeypatch.setattr(observed, 'report', report_once)
        instances.append(observed)
        return observed
    monkeypatch.setattr(bench, 'Observer', make_observer)
    def execute(*inputs):
        if inputs[-1] == 'cold_physics_cache':
            assert not instances  # priming remains uninstrumented
            return {'cache_state': inputs[-1]}
        observed = instances[0]
        for phase in ('producer', 'attribution', 'b2_numerical_acceptance'):
            observed.phase = phase
            observed.context = 'producer' if phase == 'b2_numerical_acceptance' else None
            b, states, holder = model()
            assert call(b, states, holder) == call(b, states, holder) == 9.5
        return measured
    monkeypatch.setattr(bench.e1, 'execute_cache_run', execute)
    return args, instances, report_calls


@pytest.mark.parametrize('failure', [None, 'sidecar', 'interrupted', 'incomplete'])
def test_sequential_child_snapshot_release_and_failure_preservation(monkeypatch, synthetic_child, failure):
    args, instances, report_calls = synthetic_child
    original_verify = bench.verify_journal
    snapshots = []
    def verify(path, *limits):
        assert instances[0].replay is None
        assert report_calls == [1]
        snapshots.append(Path(str(path) + '.sha256').read_text())
        if failure == 'sidecar':
            Path(str(path) + '.sha256').unlink()
        elif failure == 'interrupted':
            raise KeyboardInterrupt('synthetic replay interrupt')
        return original_verify(path, *limits)
    monkeypatch.setattr(bench, 'verify_journal', verify)
    if failure == 'incomplete':
        args.max_events = 1
    report = bench.child(args)
    assert report_calls == [1] and instances[0].replay is None
    obs = report['observation']
    assert report['sequential_verification']['observation_snapshot_sha256'] == bench.e1.digest(
        bench.observation_bytes(obs))
    if failure is None:
        assert report['status'] == 'COMPLETED', report.get('error')
        assert bench.completed_child(report, args)
        assert len(snapshots) == 1
        # Frozen bytes are independent of the surviving small observer counters.
        frozen = bench.observation_bytes(obs)
        instances[0].direct['producer']['hits'] += 1
        assert bench.observation_bytes(obs) == frozen
        with pytest.raises(RuntimeError, match='frozen'):
            instances[0].report()
    else:
        assert report['status'] == ('OVERFLOW' if failure == 'incomplete' else 'FAILED')
        assert not bench.completed_child(report, args)
        assert report['independent_journal_verification']['status'] == 'NOT_OBSERVED'
        if failure == 'incomplete':
            assert not snapshots and not Path(str(args.output) + '.events.jsonl.sha256').exists()


@pytest.mark.parametrize('damage', [None, 'missing', 'corrupt', 'journal', 'snapshot'])
def test_parent_independently_requires_journal_and_frozen_snapshot(monkeypatch, synthetic_child, damage):
    args, instances, report_calls = synthetic_child
    report = bench.child(args)
    assert report['status'] == 'COMPLETED', report.get('error')
    if damage == 'snapshot':
        report['observation']['direct_observations']['producer']['hits'] += 1
    bench.write_report(Path(str(args.output) + '.child.json'), report)
    journal = Path(str(args.output) + '.events.jsonl')
    sidecar = Path(str(journal) + '.sha256')
    if damage == 'missing':
        sidecar.unlink()
    elif damage == 'corrupt':
        sidecar.write_text('0' * 64 + '\n')
    elif damage == 'journal':
        journal.write_bytes(journal.read_bytes()[:-1])
    class Process:
        pid, returncode = 123456789, 0
        polls = iter([None, 0])
        def poll(self):
            return next(self.polls)
    stopped = []
    monkeypatch.setattr(bench.subprocess, 'Popen', lambda *a, **kw: Process())
    monkeypatch.setattr(bench.e1, 'stop', lambda process: stopped.append(process))
    monkeypatch.setattr(bench.e1, 'resident_bytes', lambda pid: 1)
    monkeypatch.setattr(bench.time, 'sleep', lambda delay: None)
    parent = bench.parent(args)
    assert len(stopped) == 1
    assert parent['status'] == ('COMPLETED' if damage is None else
        'INCOMPLETE' if damage == 'snapshot' else 'FAILED')
    assert (parent['journal_integrity'] == 'MATCH') is (damage is None)


def test_snapshot_release_drops_rank_graph():
    observed = observer()
    with observed.installed():
        for phase in ('producer', 'attribution', 'b2_numerical_acceptance'):
            observed.phase = phase
            observed.context = 'producer' if phase == 'b2_numerical_acceptance' else None
            b, states, holder = model()
            call(b, states, holder)
    ranks = observed.replay
    assert len(ranks.slots) == 3
    snapshot = observed.snapshot_and_release()
    assert type(snapshot) is bytes
    assert observed.replay is None and not ranks.slots
    assert json.loads(snapshot)['successful_keys_retained'] == 3
    assert json.loads(snapshot)['slot_lifetimes_observed'] == 3
    assert json.loads(snapshot)['status'] == 'COMPLETED'
    with pytest.raises(RuntimeError, match='frozen'):
        observed.snapshot_and_release()


def test_snapshot_serialization_failure_releases_without_retry(monkeypatch, synthetic_child):
    args, instances, report_calls = synthetic_child
    def interrupted_snapshot(observation):
        raise KeyboardInterrupt('synthetic snapshot interrupt')
    monkeypatch.setattr(bench, 'observation_bytes', interrupted_snapshot)
    report = bench.child(args)
    assert report['status'] == 'FAILED'
    assert report['error_type'] == 'KeyboardInterrupt'
    assert instances[0].replay is None and report_calls == [1]
    assert 'observation' not in report
    assert not Path(str(args.output) + '.events.jsonl.sha256').exists()
