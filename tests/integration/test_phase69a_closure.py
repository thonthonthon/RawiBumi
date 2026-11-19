"""Dark producer execution and evidence-bound quality continuation."""
from copy import deepcopy
from dataclasses import replace
import json

import pandas as pd
import pytest
from jsonschema import ValidationError

from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
from tests.unit.test_phase69a_canonical_dispatch import _run
from engine.simulation.detailed_inputs import freeze_detailed_selection, pin_detailed_module_inputs
from engine.simulation.detailed_dispatch import _prepare_backend
from engine.simulation.detailed_backend import execute_detailed_mppt_backend, DetailedMPPTBackendResult
from engine.simulation.detailed_downstream import compact_selected_states, execute_detailed_downstream, CompactDetailedMPPTResult
from engine.simulation.artifacts import verify_run_package


def _declare(store, relationship):
    bundle = store.detailed_electrical_inputs.replay()
    evidence = next(iter(bundle['pinned_electrical_shading_assets']['electrical_parameterization_evidence'].values()))
    evidence['module_quality_declaration'] = {
        'relationship': relationship, 'module_quality_loss_fraction': -.0075,
        'source_ids': evidence['source_ids'],
        'rationale': 'Controlled test declaration for this exact validated calibration; not a manufacturer independence claim.'}
    return replace(store, detailed_electrical_inputs=freeze_detailed_selection(bundle))


def test_daylight_dark_daylight_replay_night_and_duration(tmp_path):
    project, config, store, _, _ = _canonical_fixture()
    config.setdefault('numerical_options', {}).setdefault('module_overrides', {})['module_quality_loss_fraction'] = 0.
    components = deepcopy(dict(store.component_revisions))
    inverter = next(c for c in components.values() if c['schema_name'] == 'InverterDefinition')
    inverter.setdefault('operating_thresholds', {})['night_loss_w'] = 2.
    weather = next(iter(store.weather_revisions.values())).copy()
    assert len(weather.series) >= 3
    weather.series.loc[weather.series.index[1], ['ghi_w_m2', 'dni_w_m2', 'dhi_w_m2']] = 0.
    store = replace(store, component_revisions=components, weather_revisions={weather.dataset['revision_id']: weather})
    first = _run(tmp_path, project, config, store, name='transition')
    assert first.summary_result is not None, first.simulation_run
    payload = first.detailed_backend_result.replay()
    compact = compact_selected_states(first.detailed_backend_result).replay()
    assert [i['mppts'][0]['active'] for i in compact['intervals'][:3]] == [True, False, True]
    dark = payload['intervals'][1]
    for s in dark['strings'].values():
        assert s['curve'] is None
    m = dark['mppts'][0]
    assert m['selected_operating_point'] is m['tracker_state'] is m['combined_curve'] is None
    assert m['inactive_reason'] == 'no_photovoltaic_operating_point'
    assert m['power_w'] == 0.
    for key in ('voltage_v', 'current_a', 'isc_a', 'voc_v', 'combined_curve_sha256'):
        assert compact['intervals'][1]['mppts'][0][key] is None
    f = first.backend_result.timeseries
    assert f.raw_array_mpp_w.iloc[1] == 0.
    assert f.night_consumption_w.iloc[1] == 2.
    assert f.pcc_power_w.iloc[1] == -2.
    assert pd.isna(first.standard_timeseries.mppt_1_mppt_vmp_v.iloc[1])
    assert first.summary_result['total_energy_wh'] == pytest.approx(sum(f.pcc_power_w * f.duration_seconds / 3600))
    args = _prepare_backend(config, store, next(iter(store.scene_revisions.values())),
        next(iter(store.electrical_revisions.values())), [], 'duration', project['project_revision_id'], '2026-10-03T00:00:00Z')
    short_payload = deepcopy(compact)
    short_interval = short_payload['intervals'][1]
    short_payload['intervals'] = [short_interval]
    short_interval['duration_seconds'] = 900
    short_interval['interval_end'] = (pd.Timestamp(short_interval['interval_start']) + pd.Timedelta(seconds=900)).isoformat()
    short = execute_detailed_downstream(CompactDetailedMPPTResult.freeze(short_payload),
        module_configs=args['module_configs'], module_inputs=args['module_inputs'])
    assert short.energy.annual['pcc_power_kwh'] == pytest.approx(-.0005)
    second = _run(tmp_path, project, config, store, name='transition-replay')
    assert first.detailed_backend_result == second.detailed_backend_result
    pd.testing.assert_frame_equal(first.standard_timeseries, second.standard_timeseries)
    verify_run_package(first.artifact_directory)
    verify_run_package(second.artifact_directory)
    # Reject manufactured operating-point diagnostics even when rehashed.
    dark['mppts'][0]['selected_operating_point'] = {'voltage_v': 0., 'current_a': 0., 'power_w': 0.}
    with pytest.raises((ValueError, ValidationError), match='null|inactive_dark'):
        DetailedMPPTBackendResult.freeze(payload)


@pytest.mark.parametrize('relationship', ['separate_from_parameterization', 'embedded_in_parameterization', 'unknown'])
def test_quality_declaration_jinko_and_identity(tmp_path, relationship):
    project, config, store, _, _ = _canonical_fixture()
    original = store.detailed_electrical_inputs.scientific_input_sha256
    store = _declare(store, relationship)
    assert original != store.detailed_electrical_inputs.scientific_input_sha256
    if relationship == 'unknown':
        weather = next(iter(store.weather_revisions.values())).copy()
        weather.series[['ghi_w_m2', 'dni_w_m2', 'dhi_w_m2']] = 0.
        store = replace(store, weather_revisions={weather.dataset['revision_id']: weather})
    result = _run(tmp_path, project, config, store, name=relationship)
    assert result.detailed_backend_result is not None
    if relationship == 'unknown':
        assert result.summary_result is None
        assert result.simulation_run['detailed_execution_identity']['runtime_support_result'] == 'mppt_complete'
        assert all(i['mppts'][0]['availability'] == 'inactive_dark' for i in result.detailed_backend_result.replay()['intervals'])
        assert any('unknown declaration' in r for r in result.simulation_run['detailed_execution_identity']['failure_reasons'])
    else:
        assert result.summary_result is not None, result.simulation_run
        f = result.backend_result.timeseries
        factor = 1.0075 if relationship == 'separate_from_parameterization' else 1.
        assert f.after_module_quality_w.to_numpy() == pytest.approx(f.raw_array_mpp_w.to_numpy() * factor)
        assert f.module_quality_loss_w.to_numpy() == pytest.approx(f.raw_array_mpp_w.to_numpy() * (1 - factor))
        declaration = next(iter(result.simulation_run['reproducibility_manifest']['numerical_options']['module_quality_declarations'].values()))
        assert declaration['declaration']['relationship'] == relationship
        assert declaration['resolved_module_quality_loss_fraction'] == -.0075
    verify_run_package(result.artifact_directory)
    args = _prepare_backend(config, store, next(iter(store.scene_revisions.values())),
        next(iter(store.electrical_revisions.values())), [], 'zero', project['project_revision_id'], '2026-10-03T00:00:00Z')
    zero_configs = {m: replace(c, module_quality_loss_fraction=0.) for m,c in args['module_configs'].items()}
    zero = execute_detailed_downstream(compact_selected_states(result.detailed_backend_result),
        module_configs=zero_configs, module_inputs=args['module_inputs'])
    assert zero.timeseries.module_quality_loss_w.eq(0).all()
    if relationship == 'separate_from_parameterization':
        # Refresh outer checksums: the declaration must still be bound by the
        # scientific context hash, independently of the package file checksums.
        from engine.simulation.artifacts import _build_run_package_manifest
        path = result.artifact_directory / 'detailed-execution-context.json'
        context = json.loads(path.read_text())
        evidence = next(iter(context['inputs']['frozen_selection']['pinned_electrical_shading_assets']['electrical_parameterization_evidence'].values()))
        evidence['module_quality_declaration']['relationship'] = 'embedded_in_parameterization'
        path.write_text(json.dumps(context))
        manifest = _build_run_package_manifest(result.artifact_directory, simulation_run_id=relationship)
        (result.artifact_directory / 'run-package-manifest.json').write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match='scientific input hash mismatch'):
            verify_run_package(result.artifact_directory)


def test_quality_evidence_source_and_value_binding(tmp_path):
    project, config, store, scene, electrical = _canonical_fixture()
    store = _declare(store, 'separate_from_parameterization')
    args = _prepare_backend(config, store, scene, electrical, [], 'binding', project['project_revision_id'], '2026-10-03T00:00:00Z')
    pinned = next(iter(args['module_inputs'].values())).replay()
    bad = deepcopy(pinned)
    bad['evidence']['module_quality_declaration']['source_ids'] = ['missing-quality-source']
    with pytest.raises(ValueError, match='SourceRecord'):
        pin_detailed_module_inputs(**bad)
    bad_bundle = store.detailed_electrical_inputs.replay()
    bad_evidence = next(iter(bad_bundle['pinned_electrical_shading_assets']['electrical_parameterization_evidence'].values()))
    bad_evidence['module_quality_declaration']['source_ids'] = ['missing-quality-source']
    with pytest.raises(ValueError, match='SourceRecord'):
        freeze_detailed_selection(bad_bundle)
    numerical = execute_detailed_mppt_backend(next(iter(store.weather_revisions.values())), scientific_input_sha256='a'*64, **args)
    configs = {m: replace(c, module_quality_loss_fraction=.01) for m,c in args['module_configs'].items()}
    with pytest.raises(ValueError, match='bind the resolved'):
        execute_detailed_downstream(compact_selected_states(numerical), module_configs=configs, module_inputs=args['module_inputs'])


def test_fully_dark_and_mixed_independent_mppts(monkeypatch):
    """Controlled POA boundary: no change to electrical or shading kernels."""
    import engine.simulation.detailed_backend as backend
    project, config, store, scene, electrical = _canonical_fixture()
    config.setdefault('numerical_options', {}).setdefault('module_overrides', {})['module_quality_loss_fraction'] = 0.
    args = _prepare_backend(config, store, scene, electrical, [], 'mixed', project['project_revision_id'], '2026-10-03T00:00:00Z')
    weather = next(iter(store.weather_revisions.values())).copy()
    weather.series = weather.series.iloc[:1].copy()
    weather.dataset['end_time'] = (weather.series.index[0] + pd.Timedelta(hours=1)).isoformat()
    weather.series[['ghi_w_m2', 'dni_w_m2', 'dhi_w_m2']] = 0.
    full = execute_detailed_mppt_backend(weather, scientific_input_sha256='a'*64, **args)
    assert full.replay()['intervals'][0]['mppts'][0]['availability'] == 'inactive_dark'
    assert execute_detailed_downstream(compact_selected_states(full), module_configs=args['module_configs'],
                                      module_inputs=args['module_inputs']).timeseries.raw_array_mpp_w.eq(0).all()
    weather = next(iter(store.weather_revisions.values())).copy()
    weather.series = weather.series.iloc[:1].copy()
    weather.dataset['end_time'] = (weather.series.index[0] + pd.Timedelta(hours=1)).isoformat()
    design = deepcopy(args['electrical_design'])
    original = design['mppt_instances'][0]
    other = deepcopy(original)
    other.update(mppt_instance_id='controlled-second-mppt', index=2,
                 connected_string_ids=[design['strings'][1]['string_id']])
    original['connected_string_ids'] = [design['strings'][0]['string_id']]
    design['mppt_instances'].append(other)
    args['electrical_design'] = design
    args['mppt_templates'] = {**args['mppt_templates'], other['mppt_instance_id']: args['mppt_templates'][original['mppt_instance_id']]}
    dark_modules = set(design['strings'][0]['module_instance_ids'])
    order = iter(sorted(args['module_inputs']))
    original_poa = backend.calculate_poa
    def controlled_poa(*a, **kw):
        result = original_poa(*a, **kw)
        if next(order) in dark_modules:
            frame = result.frame.copy()
            frame.loc[:, [c for c in frame if c.startswith('poa_')]] = 0.
            return backend.PlaneOfArrayResult(frame, result.metadata)
        return result
    monkeypatch.setattr(backend, 'calculate_poa', controlled_poa)
    mixed = execute_detailed_mppt_backend(weather, scientific_input_sha256='b'*64, **args)
    states = compact_selected_states(mixed).replay()['intervals'][0]['mppts']
    assert [m['active'] for m in states] == [False, True]
    downstream = execute_detailed_downstream(compact_selected_states(mixed), module_configs=args['module_configs'],
                                            module_inputs=args['module_inputs'])
    assert downstream.timeseries.raw_array_mpp_w.iloc[0] == states[1]['power_w']
    assert downstream.timeseries.night_consumption_w.iloc[0] == 0.
