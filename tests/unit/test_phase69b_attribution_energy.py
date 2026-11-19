"""Compact-fixture energy contracts; never invoke counterfactual electrical physics."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from time import perf_counter

import pandas as pd
import pytest
from jsonschema import FormatChecker

from engine.simulation.artifacts import canonical_object_sha256, verify_run_package
from engine.simulation.attribution_energy import (aggregate_persisted_attribution,
    DetailedDCAttributionEnergySummary, verify_energy_summary)
from engine.simulation.detailed_attribution import DetailedDCAttributionResult, explain, integrate_channels
from shading.electrical.dc_attribution import basis

REFERENCE = Path(__file__).resolve().parents[1]/'fixtures/phase69b/compact-attribution-reference.json'


def _source(tmp_path, specs):
    """Controlled schema-valid scalar ledger variations, not new physics claims."""
    record = json.loads(REFERENCE.read_text())
    payload = record['payload']; template = payload['intervals'][0]
    intervals = []
    for start, seconds, values, reason in specs:
        row = deepcopy(template)
        row.update(interval_start=start, interval_end=(pd.Timestamp(start)+pd.Timedelta(seconds=seconds)).isoformat(),
                   evaluation_time=start, duration_seconds=seconds)
        def state(key, divisor=1):
            if values is None:
                return basis(status='not_applicable',reasons=['inactive_dark_no_photovoltaic_operating_point'])
            if values[key] is None:
                return basis(status='unavailable',reasons=sorted(set(reason)))
            return basis(values[key]/divisor)
        for m in row['modules']:
            m['bases']={k:state(k,len(row['modules'])) for k in 'UNB'}
            m['counterfactual_curve_hashes']={}
        for s in row['strings']:
            s['basis']=state('S',len(row['strings']))
            if values is None:s['source_curve_sha256']=None
        mppt=row['mppts'][0]
        mppt.update(explain({k:state(k) for k in 'UNBSCT'}))
        if values is not None and values['C'] != values['T']:
            mppt['tracker_model_id']='test.controlled.nonideal_tracker'
        mppt['actual_dc_power_w']=0. if values is None else values['T']
        row['ledger']=explain({k:state(k) for k in 'UNBSCT'})
        intervals.append(row)
    payload['intervals']=intervals;payload['energy']=integrate_channels(intervals)
    payload['scientific_input_sha256']=canonical_object_sha256({'controlled_scalar_fixture':specs})
    payload['source_numerical_result_sha256']=canonical_object_sha256({'controlled_scalar_intervals':intervals})
    source=DetailedDCAttributionResult.freeze(payload)
    path=tmp_path/'detailed-dc-attribution.json';path.write_text(json.dumps(source.record()))
    return path


def _powers():return dict(zip('UNBSCT',[100.,90.,95.,85.,80.,80.]))
def _period(summary,kind='run_total',key=None):
    return next(p for p in summary.replay()['periods'] if p['period_kind']==kind and (key is None or p['period_key']==key))


@pytest.fixture
def without_attribution_date_time_format_check(monkeypatch):
    # Exercise production semantics even when optional RFC3339 checking is absent.
    monkeypatch.setattr('engine.simulation.detailed_attribution.FormatChecker',
                        lambda: FormatChecker(formats=[]))


@pytest.mark.parametrize('field', ['interval_start', 'interval_end', 'evaluation_time'])
@pytest.mark.parametrize('interval_index', [0, 1])
@pytest.mark.parametrize('decoded', [False, True])
def test_timezone_naive_timestamp_fails_at_attribution_boundary(
        tmp_path, without_attribution_date_time_format_check, field, interval_index, decoded):
    path = _source(tmp_path, [
        ('2026-01-01T00:00:00+07:00', 3600, _powers(), []),
        ('2026-01-01T01:00:00+07:00', 3600, _powers(), [])])
    # Only an attribution record exists: no energy-summary reducer is exercised.
    assert list(tmp_path.iterdir()) == [path]
    record = json.loads(path.read_text())
    row = record['payload']['intervals'][interval_index]
    row[field] = pd.Timestamp(row[field]).tz_localize(None).isoformat()
    record['attribution_result_sha256'] = canonical_object_sha256(record['payload'])
    path.write_text(json.dumps(record))
    persisted = json.loads(path.read_text())
    result = DetailedDCAttributionResult(
        canonical_payload=json.dumps(persisted['payload'], sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode(),
        attribution_result_sha256=persisted['attribution_result_sha256'])
    with pytest.raises(ValueError, match='attribution interval timestamp must be timezone-aware'):
        result.replay_stream()
    with pytest.raises(ValueError, match='attribution interval timestamp must be timezone-aware'):
        DetailedDCAttributionResult.freeze(persisted['payload'], _decoded=decoded)


@pytest.mark.parametrize('offset', ['+07:00', 'Z'])
@pytest.mark.parametrize('decoded', [False, True])
def test_timezone_aware_attribution_preserves_payload_and_hash(tmp_path, offset, decoded):
    path = _source(tmp_path, [
        (f'2026-01-01T00:00:00{offset}', 3600, _powers(), []),
        (f'2026-01-01T01:00:00{offset}', 3600, _powers(), [])])
    record = json.loads(path.read_text())
    result = DetailedDCAttributionResult.freeze(record['payload'], _decoded=decoded)
    assert result.replay() == record['payload']
    assert result.attribution_result_sha256 == record['attribution_result_sha256']


def test_timezone_naive_attribution_interval_fails_closed_in_energy_path(
        tmp_path, without_attribution_date_time_format_check):
    path = _source(tmp_path, [('2026-01-01T00:00:00+07:00', 3600, _powers(), [])])
    aggregate_persisted_attribution(path)
    record = json.loads(path.read_text())
    row = record['payload']['intervals'][0]
    # Remove awareness consistently, preserving local times and explicit duration.
    for key in ('interval_start', 'interval_end', 'evaluation_time'):
        row[key] = pd.Timestamp(row[key]).tz_localize(None).isoformat()
    record['attribution_result_sha256'] = canonical_object_sha256(record['payload'])
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='attribution interval timestamp must be timezone-aware'):
        aggregate_persisted_attribution(path)


@pytest.mark.parametrize('change', ['gap', 'duration'])
def test_attribution_interval_alignment_fails_closed_with_recomputed_hash(tmp_path, change):
    path = _source(tmp_path, [
        ('2026-01-01T00:00:00+07:00', 3600, _powers(), []),
        ('2026-01-01T01:00:00+07:00', 3600, _powers(), [])])
    aggregate_persisted_attribution(path)
    record = json.loads(path.read_text())
    row = record['payload']['intervals'][1]
    if change == 'gap':
        # Shift the whole interval: its own duration stays consistent and ordered.
        for key in ('interval_start', 'interval_end', 'evaluation_time'):
            row[key] = (pd.Timestamp(row[key]) + pd.Timedelta(seconds=60)).isoformat()
    else:
        row['duration_seconds'] += 1
    record['attribution_result_sha256'] = canonical_object_sha256(record['payload'])
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='attribution interval alignment mismatch'):
        aggregate_persisted_attribution(path)


@pytest.mark.parametrize('change', ['gap', 'duration'])
def test_energy_summary_interval_alignment_fails_closed(tmp_path, change):
    path = _source(tmp_path, [
        ('2026-01-01T00:00:00+07:00', 3600, _powers(), []),
        ('2026-01-01T01:00:00+07:00', 3600, _powers(), [])])
    payload = aggregate_persisted_attribution(path).replay()
    row = payload['interval_audit'][1]
    if change == 'gap':
        for key in ('interval_start', 'interval_end', 'evaluation_time'):
            row[key] = (pd.Timestamp(row[key]) + pd.Timedelta(seconds=60)).isoformat()
    else:
        row['duration_seconds'] += 1
    # freeze computes a fresh summary hash before running production semantics.
    with pytest.raises(ValueError, match='attribution energy interval identity/duration mismatch'):
        DetailedDCAttributionEnergySummary.freeze(payload)


def test_explicit_irregular_duration_and_local_month_start(tmp_path):
    # First interval crosses midnight/month: its entire 10 minutes belongs to January.
    path=_source(tmp_path,[('2026-01-31T23:55:00+07:00',600,_powers(),[]),
        ('2026-02-01T00:05:00+07:00',1800,_powers(),[]),
        ('2026-02-01T00:35:00+07:00',900,_powers(),[])])
    result=aggregate_persisted_attribution(path)
    total=_period(result)['channels']['regional_mismatch']
    assert total['observed_signed_energy_wh']==pytest.approx(10*3300/3600)
    assert total['applicable_duration_seconds']==3300
    assert _period(result,'monthly','2026-01')['channels']['regional_mismatch']['complete_signed_energy_wh']==pytest.approx(10/6)
    assert _period(result,'monthly','2026-02')['channels']['regional_mismatch']['complete_signed_energy_wh']==7.5
    assert _period(result,'daily','2026-01-31')['duration_seconds']==600
    assert len([p for p in result.replay()['periods'] if p['period_kind']=='monthly'])==2
    assert result.replay()['observed_duration_seconds']==3300
    assert not any(p['period_kind']=='annual' for p in result.replay()['periods'])


def test_signed_cancellation_small_values_and_energy_telescope(tmp_path):
    a=_powers();b=_powers();c=_powers()
    # Equal regional reduction/recovery cancels; a small third term survives.
    b['U']=80.;c['U']=90.00033148579314
    path=_source(tmp_path,[('2026-10-01T12:00:00+07:00',900,a,[]),
        ('2026-10-01T12:15:00+07:00',900,c,[]),
        ('2026-10-01T12:30:00+07:00',900,b,[])])
    result=aggregate_persisted_attribution(path);p=_period(result)
    expected=(c['U']-c['N'])*.25
    assert p['channels']['regional_mismatch']['observed_signed_energy_wh']==expected and expected>0
    assert p['channels']['bypass_interaction']['observed_signed_energy_wh']==-3.75
    assert p['telescope']['status']=='complete'
    assert abs(p['telescope']['energy_residual_wh'])<=p['telescope']['energy_allowed_residual_wh']
    assert p['telescope']['max_abs_interval_power_residual_w']==0.
    assert p['channels']['tracker_interaction']['observed_signed_energy_wh']==0.
    audit=result.replay()['interval_audit']
    assert audit[0]['channel_energy']['regional_mismatch']['signed_energy_wh']==2.5
    assert audit[2]['channel_energy']['regional_mismatch']['signed_energy_wh']==-2.5


@pytest.mark.parametrize('tracker_delta',[0.,2.5])
def test_tracker_calculated_and_small_series_not_zeroed(tmp_path,tracker_delta):
    values=_powers();values['S']=values['B']-.00033148579314
    values['C']=values['T']+tracker_delta
    path=_source(tmp_path,[('2026-10-01T12:00:00+07:00',1800,values,[])])
    p=_period(aggregate_persisted_attribution(path))
    assert p['channels']['tracker_interaction']['observed_signed_energy_wh']==tracker_delta*.5
    small=(values['B']-values['S'])*.5
    assert p['channels']['series_interaction']['observed_signed_energy_wh']==small and small>0.
    assert p['telescope']['status']=='complete'


def test_partial_n_unrelated_channels_no_extrapolation_and_reasons(tmp_path):
    missing=_powers();missing['N']=None
    path=_source(tmp_path,[('2026-10-01T12:00:00+07:00',900,_powers(),[]),
        ('2026-10-01T12:15:00+07:00',1800,missing,['z_domain','a_domain']),
        ('2026-10-01T12:45:00+07:00',900,None,[])])
    p=_period(aggregate_persisted_attribution(path));channel=p['channels']['regional_mismatch']
    assert channel['completeness']=='partial' and channel['availability']=='available'
    assert channel['applicable_interval_count']==2 and channel['applicable_duration_seconds']==2700
    assert channel['available_interval_count']==1 and channel['available_duration_seconds']==900
    assert channel['unavailable_interval_count']==1 and channel['unavailable_duration_seconds']==1800
    assert channel['not_applicable_interval_count']==1 and channel['not_applicable_duration_seconds']==900
    assert channel['availability_fraction']==1/3
    assert channel['observed_signed_energy_wh']==2.5 and channel['complete_signed_energy_wh'] is None
    assert channel['unavailable_reason_codes']==['a_domain','z_domain']
    assert all(v['duration_seconds']==1800 and v['interval_count']==1 for v in channel['unavailable_reasons'])
    for name in ('series_interaction','parallel_interaction','tracker_interaction','total_detailed_dc_delta'):
        assert p['channels'][name]['completeness']=='complete'
    assert p['channels']['series_interaction']['observed_signed_energy_wh']==7.5
    assert p['telescope']['status']=='partial' and p['telescope']['energy_residual_wh'] is None
    assert p['telescope']['blocking_bases']==['N']
    assert p['telescope']['common_available_duration_seconds']==900
    assert p['telescope']['common_available_energy_residual_wh']==0.


def test_unavailable_and_entirely_dark_periods(tmp_path):
    missing=_powers();missing['N']=None
    path=_source(tmp_path,[('2026-01-31T23:45:00+07:00',900,missing,['bounded_domain']),
        ('2026-02-01T00:00:00+07:00',1800,None,[])])
    result=aggregate_persisted_attribution(path)
    unavailable=_period(result,'monthly','2026-01')['channels']['regional_mismatch']
    assert unavailable['completeness']=='unavailable' and unavailable['availability']=='unavailable'
    assert unavailable['availability_fraction']==0.
    assert unavailable['observed_signed_energy_wh'] is None
    dark=_period(result,'monthly','2026-02')
    assert dark['telescope']['status']=='not_applicable'
    for c in dark['channels'].values():
        assert c['completeness']=='not_applicable' and c['availability']=='not_applicable'
        assert c['applicable_interval_count']==c['unavailable_interval_count']==0
        assert c['availability_fraction'] is None and c['observed_signed_energy_wh'] is None
        assert c['unavailable_reason_codes']==[]


def test_unavailable_reasons_aggregate_across_intervals(tmp_path):
    missing=_powers();missing['N']=None
    path=_source(tmp_path,[('2026-10-01T12:00:00+07:00',900,missing,['z','a']),
        ('2026-10-01T12:15:00+07:00',1800,missing,['z'])])
    c=_period(aggregate_persisted_attribution(path))['channels']['regional_mismatch']
    assert c['unavailable_reason_codes']==['a','z']
    assert c['unavailable_reasons']==[{'reason_code':'a','interval_count':1,'duration_seconds':900.},
        {'reason_code':'z','interval_count':2,'duration_seconds':2700.}]


def test_reference_series_term_persisted_replay_hash_and_no_physics(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('aggregation called physics')
    monkeypatch.setattr('engine.simulation.detailed_attribution.execute_detailed_dc_attribution',forbidden)
    monkeypatch.setattr('shading.electrical.dc_attribution.evaluate_independent_module_bases',forbidden)
    monkeypatch.setattr('engine.simulation.detailed_attribution.evaluate_independent_module_bases',forbidden)
    start=perf_counter();result=aggregate_persisted_attribution(REFERENCE)
    print({'aggregation_seconds':perf_counter()-start,'summary_canonical_bytes':len(result.canonical_payload),
           'source_bytes':REFERENCE.stat().st_size})
    assert result==aggregate_persisted_attribution(REFERENCE)
    verify_energy_summary(result,REFERENCE)
    assert DetailedDCAttributionEnergySummary.freeze(result.replay())==result
    source=json.loads(REFERENCE.read_text())['payload']
    expected=source['intervals'][0]['ledger']['channels']['series_interaction']['value_w']*source['intervals'][0]['duration_seconds']/3600
    assert _period(result)['channels']['series_interaction']['observed_signed_energy_wh']==expected
    with pytest.raises(ValueError,match='hash mismatch'):replace(result,canonical_payload=b'{}').replay()
    tamper=result.replay();tamper['periods'][0]['channels']['series_interaction']['observed_signed_energy_wh']+=1
    with pytest.raises(ValueError,match='semantics mismatch'):DetailedDCAttributionEnergySummary.freeze(tamper)
    bad=deepcopy(json.loads(REFERENCE.read_text()));bad['attribution_result_sha256']='0'*64
    path=tmp_path/'bad.json';path.write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='source hash mismatch'):aggregate_persisted_attribution(path)


def test_summary_source_binding_rejects_consistent_rehashed_forgery(tmp_path):
    source=_source(tmp_path,[('2026-10-01T12:00:00+07:00',900,_powers(),[])])
    result=aggregate_persisted_attribution(source)
    p=result.replay();p['source_identity']['scientific_input_sha256']='0'*64
    forged=DetailedDCAttributionEnergySummary.freeze(p)
    with pytest.raises(ValueError,match='source binding mismatch'):verify_energy_summary(forged,source)


def test_legacy_result_and_summary_compatibility(tmp_path):
    from tests.unit.test_phase38e_canonical_simulation_run import _inputs
    from tests.unit.test_phase69a_canonical_dispatch import _run
    project,configuration,store=_inputs()
    legacy=_run(tmp_path,project,configuration,store,name='legacy-energy')
    assert legacy.summary_result is not None
    assert not (legacy.artifact_directory/'detailed-dc-attribution-energy-summary.json').exists()
    assert not any('attribution' in k for k in legacy.summary_result)
    verify_run_package(legacy.artifact_directory)


def test_stage3b_exact_stage3a_reducer_compatibility(tmp_path):
    import runpy
    oracle = runpy.run_path(str(REFERENCE.parent / "stage3a_energy_reducer.py"))["_assemble"]
    missing = _powers(); missing['B'] = None
    path = _source(tmp_path, [
        ('2026-01-31T23:55:00+07:00', 600, _powers(), []),
        ('2026-02-01T00:05:00+07:00', 900, missing, ['controlled_missing']),
        ('2026-02-01T00:20:00+07:00', 900, None, []),
        ('2026-02-01T00:35:00+07:00', 900, _powers(), [])])
    summary = aggregate_persisted_attribution(path)
    payload = summary.replay()
    expected = oracle(payload['source_identity'], payload['source_attribution_result_sha256'],
                      payload['scope_identity'], payload['interval_audit'])
    assert summary.canonical_payload == json.dumps(expected, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()
    assert summary.energy_summary_sha256 == canonical_object_sha256(expected)


def test_energy_uses_no_whole_attribution_decode(tmp_path, monkeypatch):
    path = _source(tmp_path, [('2026-10-01T12:00:00+07:00', 900, _powers(), [])])
    original = json.loads
    decoded = []
    def loads(value, *args, **kwargs):
        result = original(value, *args, **kwargs)
        if isinstance(result, dict) and (result.get('schema_name') == 'DetailedDCAttributionResult'
                or 'attribution_result_sha256' in result):
            decoded.append(result)
        return result
    def full_replay_forbidden(self):
        raise AssertionError('energy aggregation must not materialize compatibility replay')
    monkeypatch.setattr(json, 'loads', loads)
    monkeypatch.setattr(DetailedDCAttributionResult, 'replay', full_replay_forbidden)
    summary = aggregate_persisted_attribution(path)
    assert len(decoded) == 0
    decoded.clear()
    verify_energy_summary(summary, path)
    assert len(decoded) == 0


def test_stage3b_replay_remains_isolated(tmp_path):
    from engine.simulation.attribution_energy import load_compact_attribution
    path = _source(tmp_path, [('2026-10-01T12:00:00+07:00', 900, _powers(), [])])
    source = load_compact_attribution(path)
    first = source.replay()
    first['intervals'][0]['ledger']['bases']['U']['power_w'] = -999.
    assert source.replay()['intervals'][0]['ledger']['bases']['U']['power_w'] == 100.


def test_stage3b_fsum_sensitive_reducer_compatibility(tmp_path):
    import runpy
    oracle = runpy.run_path(str(REFERENCE.parent / 'stage3a_energy_reducer.py'))['_assemble']
    powers = [dict(zip('UNBSCT', values)) for values in (
        (1e16, 0., 0., 0., 0., 0.),
        (1., 0., 0., 0., 0., 0.),
        (0., 1e16, 0., 0., 0., 0.))]
    path = _source(tmp_path, [(f'2026-10-01T{hour:02d}:00:00+07:00', 3600, values, [])
                              for hour, values in zip((12, 13, 14), powers)])
    summary = aggregate_persisted_attribution(path)
    payload = summary.replay()
    expected = oracle(payload['source_identity'], payload['source_attribution_result_sha256'],
                      payload['scope_identity'], payload['interval_audit'])
    assert summary.canonical_payload == json.dumps(expected, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()
    assert payload['periods'][0]['channels']['regional_mismatch']['observed_signed_energy_wh'] == 1.
    # Built-in sum compensates float additions on Python 3.12 and later.
    naive_total = 0.
    for value in (1e16, 1., -1e16):
        naive_total += value
    assert naive_total == 0.


def test_stage3b_reused_source_binding_rejects_other_attribution(tmp_path):
    from engine.simulation.attribution_energy import load_compact_attribution
    path = _source(tmp_path, [('2026-10-01T12:00:00+07:00', 900, _powers(), [])])
    summary = aggregate_persisted_attribution(path)
    source = load_compact_attribution(REFERENCE)
    with pytest.raises(ValueError, match='source binding mismatch'):
        verify_energy_summary(summary, path, _source=source)
