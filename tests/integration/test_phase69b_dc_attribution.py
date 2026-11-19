"""Bounded explanatory DC attribution; actual execution remains authoritative."""
from copy import deepcopy
from dataclasses import replace
import json
from time import perf_counter

import pandas as pd
import pytest

from tests.integration.test_phase69a_detailed_backend import _canonical_fixture, REF
from tests.integration.test_phase69a_closure import _declare
from tests.unit.test_phase69a_canonical_dispatch import _run
from engine.simulation.detailed_dispatch import _prepare_backend
from engine.simulation.detailed_backend import DetailedMPPTBackendResult
from engine.simulation.detailed_attribution import (DetailedDCAttributionResult,
    execute_detailed_dc_attribution, explain, integrate_channels, POLICY, verify_attribution_sources)
from engine.simulation.detailed_inputs import pin_detailed_module_inputs
from engine.simulation.artifacts import verify_run_package, canonical_object_sha256, _build_run_package_manifest
from engine.losses.energy import aggregate_interval_quantities
from shading.electrical.dc_attribution import (basis, evaluate_independent_module_bases,
    optimize_independent_module, uniform_effective_input, build_bypass_off_module_model,
    BypassOffUnavailable)
from shading.electrical import (build_phase66_series_module_operating_model,
    assemble_general_series_string_iv, assemble_parallel_mppt_iv, select_mppt_operating_point,
    finalize_parameterization_payload, build_local_electrical_irradiance_state)


def _geometry(topology, cover_fraction=0.):
    geometry = deepcopy(REF['_four_module_geometry']())
    if cover_fraction:
        region_map, _, _ = REF['_module_handoff'](geometry, topology, REF['MODULE_A_WEAK'])
        cover = REF['_occluder_over_region'](REF['_mapped_region'](region_map, 's1-r1'))
        vertices = cover['faces'][0]['vertices_3d']
        left = min(v[0] for v in vertices)
        for vertex in vertices:
            vertex[0] = left + cover_fraction * (vertex[0] - left)
        geometry['occluders'] = [cover]
    geometry['geometry_payload_sha256'] = canonical_object_sha256(geometry)
    return geometry


def _pinned(topology, bounded=False):
    definition = REF['_parameterization'](topology)
    if bounded:
        # Narrow the supported reverse domain; never extend the reference model.
        next(r for r in definition['region_parameterizations'] if r['region_id'] == 's1-r1')['reverse_bias']['minimum_supported_voltage_v'] = -.7997
        definition = finalize_parameterization_payload(definition)
    return {'topology': topology, 'parameterization': definition, 'evidence': REF['_evidence'](definition)}


@pytest.fixture(scope='module')
def independent_cases():
    topology = REF['_topology']()
    results = {}
    for name, coverage, bounded in [('uniform', 0., False), ('mild', .1, False),
                                    ('recovery', 1., False), ('bounded', 1., True)]:
        region_map, _, local = REF['_module_handoff'](_geometry(topology, coverage), topology, REF['MODULE_A_WEAK'])
        pinned = _pinned(topology, bounded)
        diagnostic = {'region_map': region_map, 'local_irradiance': local}
        bases, curves = evaluate_independent_module_bases(pinned, diagnostic, sample_count=101)
        results[name] = pinned, diagnostic, bases, curves
    return results


def test_uniform_and_nonuniform_without_active_bypass(independent_cases):
    _, _, uniform, _ = independent_cases['uniform']
    assert all(v['status'] == 'available' for v in uniform.values())
    assert uniform['U']['power_w'] == pytest.approx(uniform['N']['power_w'], abs=1e-7, rel=1e-9)
    assert uniform['N']['power_w'] == pytest.approx(uniform['B']['power_w'], abs=1e-7, rel=1e-9)
    pinned, d, mild, curves = independent_cases['mild']
    assert mild['U']['power_w'] > mild['N']['power_w']
    assert mild['N']['power_w'] == pytest.approx(mild['B']['power_w'], abs=1e-7, rel=1e-9)
    model = build_phase66_series_module_operating_model(pinned['topology'], d['region_map'],
        d['local_irradiance'], pinned['parameterization'], pinned['evidence'])
    assert not any(s['bypass_active'] for s in model.voltage_at_current(curves['B']['global_mpp']['current_a'])['protected_substrings'])
    u = uniform_effective_input(d['region_map'], d['local_irradiance'])
    assert u['schema_name'] != d['local_irradiance']['schema_name']
    assert u['module_temperature_c'] == d['local_irradiance']['module_temperature_c']
    assert u['source_actual_local_state_sha256'] == d['local_irradiance']['state_payload_sha256']


def test_bypass_recovery_signed_and_multiple_local_maxima(independent_cases):
    _, _, bases, curves = independent_cases['recovery']
    assert bases['N']['power_w'] - bases['B']['power_w'] < 0
    assert len(curves['B']['local_mpp_candidates']) >= 2
    assert len(curves['N']['local_mpp_candidates']) >= 2
    print({'independent_recovery': bases})


def test_real_bypass_off_domain_rejection_keeps_protected_power(independent_cases):
    pinned, d, bases, _ = independent_cases['bounded']
    assert bases['U']['status'] == bases['B']['status'] == 'available'
    assert bases['N']['status'] == 'unavailable' and bases['N']['power_w'] is None
    assert bases['N']['reason_codes'] == ['bypass_off_positive_power_domain_not_covered']
    with pytest.raises(BypassOffUnavailable, match='no global MPP claim'):
        build_bypass_off_module_model(pinned, d['region_map'], d['local_irradiance'])


def test_series_mismatch_with_uniform_but_unequal_modules(independent_cases):
    pinned, diagnostic, bases, _ = independent_cases['uniform']
    region_map = diagnostic['region_map']
    _, visibility, _ = REF['_module_handoff'](_geometry(pinned['topology']), pinned['topology'],
                                             REF['MODULE_A_WEAK'])
    local = build_local_electrical_irradiance_state(region_map, visibility,
        unshaded_poa={'beam_w_m2':500.,'sky_diffuse_w_m2':0.,'ground_reflected_w_m2':0.},
        optical_modifier={'beam':1.,'sky_diffuse':1.,'ground_reflected':1.},
        optical_model_manifest={'model_id':'phase69b.reference.unity','model_version':'0.1'},
        module_temperature_c=25., interval_start='2026-10-01T11:00:00+07:00',
        evaluation_time='2026-10-01T12:00:00+07:00')
    weak = build_phase66_series_module_operating_model(pinned['topology'],region_map,local,
        pinned['parameterization'],pinned['evidence'])
    clear_map, _, clear_local = REF['_module_handoff'](_geometry(pinned['topology']),
        pinned['topology'], REF['MODULE_A_CLEAR'])
    clear = build_phase66_series_module_operating_model(pinned['topology'],clear_map,
        clear_local,pinned['parameterization'],pinned['evidence'])
    independent = optimize_independent_module(weak,sample_count=101)['global_mpp']['power_w'] + bases['B']['power_w']
    circuit={'string_id':'unequal-module-reference','project_revision_id':'reference',
        'module_instance_ids':[weak.module_instance_id,clear.module_instance_id],'polarity':'normal','enabled':True}
    series=assemble_general_series_string_iv(circuit,{m.module_instance_id:m for m in (weak,clear)},sample_count=101)
    delta=independent-series.curve['global_mpp']['power_w']
    assert delta > 100.
    print({'unequal_uniform_modules_series_interaction_w':delta,'B_w':independent,
           'S_w':series.curve['global_mpp']['power_w']})


def _direct_reference(bounded=False):
    """Exact Phase 6.8C kernels/geometry at 1000 W/m², 25°C, unity optics."""
    project, config, store, _, design = _canonical_fixture()
    args = _prepare_backend(config, store, next(iter(store.scene_revisions.values())), design, [],
        'direct-reference', project['project_revision_id'], '2026-10-04T00:00:00Z')
    topology = REF['_topology']()
    pinned_cf = _pinned(topology, bounded)
    geometry = _geometry(topology, 1.)
    modules, models = {}, {}
    for module_id, snapshot in args['module_inputs'].items():
        region_map, visibility, local = REF['_module_handoff'](geometry, topology, module_id)
        if bounded:
            original = snapshot.replay()
            args['module_inputs'][module_id] = pin_detailed_module_inputs(module=original['module'],
                sources=original['sources'], **pinned_cf)
        model = build_phase66_series_module_operating_model(topology, region_map, local,
            pinned_cf['parameterization'], pinned_cf['evidence'])
        models[module_id] = model
        modules[module_id] = {'region_map': region_map, 'visibility': visibility, 'local_irradiance': local,
            'thermal_incident_poa_w_m2': sum(local['regions'][0]['unshaded_poa'].values()),
            'thermal_efficiency_effective_irradiance_w_m2': 1000.,
            'module_operating_model': {'scientific_input_sha256': model.scientific_input_sha256}}
    strings = {s['string_id']: assemble_general_series_string_iv(s,
        {m: models[m] for m in s['module_instance_ids']}, sample_count=101) for s in design['strings']}
    mppt = design['mppt_instances'][0]
    combined = assemble_parallel_mppt_iv(mppt, {s: r.curve for s,r in strings.items()},
        source_electrical_revision_id=design['electrical_revision_id'])
    tracker = select_mppt_operating_point(combined.curve,
        source_electrical_revision_id=design['electrical_revision_id'],
        mppt_operating_point_model_id=config['shading_configuration']['electrical_shading_configuration']['model_selections']['mppt_operating_point_model_id'],
        mppt_template=args['mppt_templates'][mppt['mppt_instance_id']])
    numerical = DetailedMPPTBackendResult.freeze({'schema_name':'DetailedMPPTBackendResult','schema_version':'0.1',
        'scientific_input_sha256':'a'*64, 'temporal_metadata':{}, 'weather_qc':{},
        'temperature_metadata':{m:{} for m in modules}, 'model_resolution_metadata':{},
        'numerical_policy':{'string_sample_count':101}, 'downstream_continuation':'unavailable_phase69a_mppt_boundary',
        'intervals':[{'interval_start':'2026-10-01T11:00:00+07:00','interval_end':'2026-10-01T12:00:00+07:00',
            'evaluation_time':'2026-10-01T12:00:00+07:00','duration_seconds':3600,'modules':modules,
            'strings':{s:{'curve':r.curve,'state':r.state} for s,r in strings.items()},
            'mppts':[{'mppt_instance_id':mppt['mppt_instance_id'],'mppt_index':1,
                'selected_operating_point':tracker.state['selected_operating_point'],
                'tracker_model_id':tracker.state['mppt_operating_point_model_id'],
                'constraint_flags':tracker.state['constraint_evaluation'],'tracker_state':tracker.state,
                'combined_curve':combined.curve,'combined_state':combined.state}]}]})
    return numerical, args


@pytest.fixture(scope='module', params=[False, True], ids=['reference','bounded-N'])
def direct_case(request):
    numerical, args = _direct_reference(request.param)
    start = perf_counter()
    result = execute_detailed_dc_attribution(numerical, module_inputs=args['module_inputs'],
        module_configs=args['module_configs'], electrical_design=args['electrical_design'], retain_diagnostics=True)
    print({'direct_reference_bounded':request.param,'attribution_seconds':perf_counter()-start,
           'compact_bytes':len(result.canonical_payload),'diagnostic_bytes':len(result.diagnostic_payload),
           'ledger':result.replay()['intervals'][0]['ledger']})
    return request.param, numerical, args, result


def test_series_parallel_tracker_and_telescope(direct_case):
    bounded, _, _, result = direct_case
    ledger = result.replay()['intervals'][0]['ledger']
    assert ledger['channels']['series_interaction']['value_w'] > 0
    assert ledger['channels']['parallel_interaction']['value_w'] > 0
    assert ledger['channels']['tracker_interaction']['value_w'] == pytest.approx(0., abs=1e-7)
    assert ledger['channels']['total_detailed_dc_delta']['status'] == 'available'
    if bounded:
        assert ledger['telescope']['status'] == 'partial'
        assert ledger['telescope']['residual_w'] is None
        for name in ('regional_mismatch','bypass_interaction'):
            assert ledger['channels'][name]['status'] == 'unavailable'
            assert ledger['channels'][name]['value_w'] is None
    else:
        assert ledger['channels']['bypass_interaction']['value_w'] < 0
        assert ledger['telescope']['status'] == 'complete'
        assert ledger['telescope']['residual_w'] == pytest.approx(0., abs=1e-7)
        values = ledger['channels']
        assert sum(values[k]['value_w'] for k in values if k != 'total_detailed_dc_delta') == pytest.approx(values['total_detailed_dc_delta']['value_w'], abs=1e-7, rel=1e-9)


def test_replay_hash_tamper_and_future_tracker_semantics(direct_case):
    _, _, _, result = direct_case
    payload = result.replay()
    assert DetailedDCAttributionResult.freeze(payload) == replace(result, diagnostic_payload=None)
    with pytest.raises(ValueError, match='hash mismatch'):
        replace(result, canonical_payload=b'{}').replay()
    payload['intervals'][0]['ledger']['channels']['series_interaction']['value_w'] += 1.
    with pytest.raises(ValueError, match='semantics mismatch'):
        DetailedDCAttributionResult.freeze(payload)
    base = {k:basis(float(v)) for k,v in zip('UNBSCT',[100,95,97,94,92,90])}
    future = explain(base)
    assert future['channels']['parallel_interaction']['value_w'] == 2.
    assert future['channels']['tracker_interaction']['value_w'] == 2.
    assert future['channels']['bypass_interaction']['value_w'] == -2.
    assert future['telescope']['residual_w'] == 0.


@pytest.fixture(scope='module')
def completed(tmp_path_factory):
    project, config, store, scene, design = _canonical_fixture()
    config['output_configuration']['detailed_diagnostics'] = False
    config.setdefault('numerical_options', {}).setdefault('module_overrides', {})['module_quality_loss_fraction'] = 0.
    start = perf_counter()
    result = _run(tmp_path_factory.mktemp('phase69b'), project, config, store, name='attribution')
    assert result.summary_result is not None, result.simulation_run
    args = _prepare_backend(config, store, scene, design, [], 'parity',project['project_revision_id'],'2026-10-04T00:00:00Z')
    print({'canonical_seconds':perf_counter()-start,
           'compact_attribution_bytes':(result.artifact_directory/'detailed-dc-attribution.json').stat().st_size,
           'package_bytes':sum(p.stat().st_size for p in result.artifact_directory.iterdir())})
    return project, config, store, args, result


def test_direct_kernel_orchestration_parity_diagnostics_and_energy(completed):
    _, _, _, args, actual = completed
    expected = execute_detailed_dc_attribution(actual.detailed_backend_result, module_inputs=args['module_inputs'],
        module_configs=args['module_configs'], electrical_design=args['electrical_design'], retain_diagnostics=True)
    assert expected.canonical_payload == actual.detailed_attribution_result.canonical_payload
    assert actual.detailed_attribution_result.diagnostic_payload is None
    assert expected.diagnostic_payload is not None
    p = expected.replay()
    for name, energy in p['energy'].items():
        if energy['status'] == 'available':
            direct = sum(i['ledger']['channels'][name]['value_w'] * i['duration_seconds']/3600
                         for i in p['intervals'] if i['ledger']['channels'][name]['status']=='available')
            atol = POLICY['energy_absolute_tolerance_wh_per_second'] * sum(i['duration_seconds'] for i in p['intervals'])
            assert energy['energy_wh'] == pytest.approx(direct, abs=atol, rel=1e-9)
    # Compare against the existing independent duration-based energy integrator.
    names = [name for name in p['energy'] if p['energy'][name]['status']=='available']
    frame = pd.DataFrame({name+'_w':[i['ledger']['channels'][name]['value_w'] for i in p['intervals']] for name in names},
        index=pd.DatetimeIndex([i['interval_start'] for i in p['intervals']]))
    energy = aggregate_interval_quantities(frame, interval_seconds=[i['duration_seconds'] for i in p['intervals']], power_columns_w=list(frame))
    for name in names:
        assert p['energy'][name]['energy_wh'] == pytest.approx(energy.annual[name+'_kwh']*1000, abs=1e-7, rel=1e-9)
    verify_run_package(actual.artifact_directory)
    assert not (actual.artifact_directory/'detailed-dc-attribution-diagnostics.json').exists()
    assert not (actual.artifact_directory/'detailed-mppt-result.json').exists()
    assert (actual.artifact_directory/'detailed-dc-attribution.json').stat().st_size < len(actual.detailed_backend_result.canonical_payload)/10


def test_no_double_counting_and_frozen_actual_parity(tmp_path, monkeypatch, completed):
    project, config, store, args, actual = completed
    # Disable explanation alone: the exact unchanged Phase 6.9A path still runs.
    monkeypatch.setattr('engine.simulation.detailed_attribution.execute_detailed_dc_attribution', lambda *a,**k:None)
    baseline = _run(tmp_path,project,config,store,name='physical-only')
    assert baseline.detailed_backend_result == actual.detailed_backend_result
    assert baseline.simulation_run['input_hash'] == actual.simulation_run['input_hash']
    assert baseline.summary_result == actual.summary_result | {'simulation_run_id':'physical-only'}
    pd.testing.assert_frame_equal(baseline.standard_timeseries, actual.standard_timeseries)
    pd.testing.assert_frame_equal(baseline.backend_result.electrical.ledger.frame, actual.backend_result.electrical.ledger.frame)
    assert actual.summary_result['shading_energy_loss_wh'] is None
    assert not any(name in actual.backend_result.electrical.ledger.frame for name in actual.detailed_attribution_result.replay()['energy'])


@pytest.mark.parametrize('relationship',['separate_from_parameterization','embedded_in_parameterization','unknown'])
def test_nonzero_quality_declaration_does_not_enter_dc_attribution(tmp_path, completed, relationship):
    project, config, store, _, actual = completed
    config = deepcopy(config)
    config['numerical_options']['module_overrides'].pop('module_quality_loss_fraction')
    weather = next(iter(store.weather_revisions.values()))
    config['end_time'] = (weather.series.index[0]+pd.Timedelta(hours=1)).isoformat()
    config['output_configuration']['detailed_diagnostics'] = relationship == 'embedded_in_parameterization'
    qualified = _run(tmp_path,project,config,_declare(store,relationship),name=relationship)
    assert (qualified.summary_result is None) == (relationship == 'unknown'), qualified.simulation_run
    first = qualified.detailed_attribution_result.replay()['intervals'][0]
    reference = actual.detailed_attribution_result.replay()['intervals'][0]['ledger']
    for group, value_key in [('bases','power_w'),('channels','value_w')]:
        for name, value in first['ledger'][group].items():
            assert value['status'] == reference[group][name]['status']
            assert value['reason_codes'] == reference[group][name]['reason_codes']
            assert value[value_key] == pytest.approx(reference[group][name][value_key],abs=1e-7,rel=1e-9)
    assert first['ledger']['telescope'] == reference['telescope']
    # Energy summaries consume the persisted compact result; quality is downstream.
    from engine.simulation.attribution_energy import aggregate_persisted_attribution
    energy = aggregate_persisted_attribution(qualified.artifact_directory/'detailed-dc-attribution.json')
    zero_energy = aggregate_persisted_attribution(actual.artifact_directory/'detailed-dc-attribution.json')
    for name, value in energy.replay()['interval_audit'][0]['channel_energy'].items():
        expected = zero_energy.replay()['interval_audit'][0]['channel_energy'][name]
        assert value['status'] == expected['status']
        assert value['signed_energy_wh'] == pytest.approx(expected['signed_energy_wh'],abs=1e-7,rel=1e-9)
    if relationship == 'unknown':
        assert qualified.simulation_run['detailed_execution_identity']['runtime_support_result'] == 'mppt_complete'
        verify_run_package(qualified.artifact_directory)
        return
    raw = qualified.backend_result.timeseries.raw_array_mpp_w
    after = qualified.backend_result.timeseries.after_module_quality_w
    assert after.to_numpy() == pytest.approx(raw.to_numpy() * (1.0075 if relationship.startswith('separate') else 1.))
    assert (qualified.artifact_directory/'detailed-dc-attribution-diagnostics.json').exists() == (relationship == 'embedded_in_parameterization')
    verify_run_package(qualified.artifact_directory)


def test_compact_package_tamper_even_with_refreshed_manifest(tmp_path, completed):
    from shutil import copytree
    directory = tmp_path/'tamper'
    copytree(completed[-1].artifact_directory, directory)
    path = directory/'detailed-dc-attribution.json'
    record = json.loads(path.read_text())
    record['payload']['intervals'][0]['ledger']['channels']['parallel_interaction']['value_w'] += 1
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='artifact hash mismatch'):
        verify_run_package(directory)
    manifest = _build_run_package_manifest(directory,simulation_run_id='attribution')
    (directory/'run-package-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='semantics mismatch|hash mismatch'):
        verify_run_package(directory)
    # Rehashing an internally consistent record cannot forge its scientific source.
    payload = completed[-1].detailed_attribution_result.replay()
    payload['intervals'][0]['modules'][0]['source_parameterization_sha256'] = '0'*64
    forged = DetailedDCAttributionResult.freeze(payload)
    context = json.loads((completed[-1].artifact_directory/'detailed-execution-context.json').read_text())
    with pytest.raises(ValueError,match='parameterization evidence binding mismatch'):
        verify_attribution_sources(forged, context)


def test_dark_not_applicable_partial_energy_and_night_remains_actual(tmp_path):
    project, config, store, _, _ = _canonical_fixture()
    config.setdefault('numerical_options',{}).setdefault('module_overrides',{})['module_quality_loss_fraction']=0.
    weather = next(iter(store.weather_revisions.values())).copy()
    weather.series[['ghi_w_m2','dni_w_m2','dhi_w_m2']] = 0.
    components = deepcopy(dict(store.component_revisions))
    inverter = next(c for c in components.values() if c['schema_name']=='InverterDefinition')
    inverter.setdefault('operating_thresholds',{})['night_loss_w'] = 2.
    result = _run(tmp_path,project,config,replace(store,component_revisions=components,
        weather_revisions={weather.dataset['revision_id']:weather}),name='dark-attribution')
    assert result.summary_result is not None, result.simulation_run
    p = result.detailed_attribution_result.replay()
    for interval in p['intervals']:
        assert all(b['status']=='not_applicable' and b['power_w'] is None for b in interval['ledger']['bases'].values())
        assert interval['ledger']['telescope']['status']=='not_applicable'
        assert interval['mppts'][0]['actual_dc_power_w']==0.
        assert not interval['modules'][0]['counterfactual_curve_hashes']
    assert all(v['status']=='not_applicable' and v['energy_wh'] is None for v in p['energy'].values())
    assert result.backend_result.timeseries.pcc_power_w.eq(-2.).all()
    assert result.backend_result.timeseries.raw_array_mpp_w.eq(0.).all()
    verify_run_package(result.artifact_directory)
    # Unavailable intervals never silently contribute zero to a complete total.
    complete = explain({k:basis(float(100-idx)) for idx,k in enumerate('UNBSCT')})
    missing = deepcopy(complete['bases']); missing['N']=basis(status='unavailable',reasons=['bounded_domain'])
    intervals = [{'duration_seconds':900,'ledger':complete}, {'duration_seconds':1800,'ledger':explain(missing)}]
    integrated = integrate_channels(intervals)
    assert integrated['regional_mismatch']['energy_wh'] is None
    assert integrated['regional_mismatch']['available_subtotal_wh']==.25
    assert integrated['regional_mismatch']['unavailable_duration_seconds']==1800
    assert integrated['series_interaction']['energy_wh']==.75


def test_legacy_contract_and_execution_do_not_invoke_attribution(tmp_path,monkeypatch):
    from tests.unit.test_phase38e_canonical_simulation_run import _inputs
    project,config,store=_inputs()
    def forbidden(*a,**k):raise AssertionError('legacy invoked detailed attribution')
    monkeypatch.setattr('engine.simulation.detailed_attribution.execute_detailed_dc_attribution',forbidden)
    legacy=_run(tmp_path,project,config,store,name='legacy-69b')
    assert legacy.summary_result is not None
    assert legacy.detailed_attribution_result is None
    assert not (legacy.artifact_directory/'detailed-dc-attribution.json').exists()


def test_persisted_energy_summary_binding_tamper_and_actual_ledger_isolation(tmp_path,completed):
    from shutil import copytree
    from engine.simulation.attribution_energy import aggregate_persisted_attribution
    actual=completed[-1]
    source=actual.artifact_directory/'detailed-dc-attribution.json'
    path=actual.artifact_directory/'detailed-dc-attribution-energy-summary.json'
    saved_ledger=actual.backend_result.electrical.ledger.frame.copy(deep=True)
    saved_summary=deepcopy(actual.summary_result)
    expected=aggregate_persisted_attribution(source)
    assert json.loads(path.read_text())==expected.record()
    pd.testing.assert_frame_equal(saved_ledger,actual.backend_result.electrical.ledger.frame)
    assert saved_summary==actual.summary_result
    assert not any('attribution' in k for k in saved_summary)
    context=json.loads((actual.artifact_directory/'detailed-execution-context.json').read_text())
    assert context['dc_attribution_energy_reference']['energy_summary_sha256']==expected.energy_summary_sha256
    directory=tmp_path/'energy-tamper';copytree(actual.artifact_directory,directory)
    target=directory/path.name
    forged=json.loads(target.read_text())
    forged['payload']['periods'][0]['channels']['parallel_interaction']['observed_signed_energy_wh']+=1
    target.write_text(json.dumps(forged))
    with pytest.raises(ValueError,match='artifact hash mismatch'):verify_run_package(directory)
    manifest=_build_run_package_manifest(directory,simulation_run_id='attribution')
    (directory/'run-package-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='semantics mismatch|hash mismatch'):verify_run_package(directory)
