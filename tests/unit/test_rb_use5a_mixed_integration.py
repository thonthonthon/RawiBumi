"""Real standard dispatch, reconciled physical circuits and persisted records."""
from tests.unit._availability import missing_commit
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urlparse, unquote
import numpy as np
import pandas as pd
import pytest
from jsonschema import Draft202012Validator
from tests.unit.test_rb_s14b_electrical import _two_fields, _ok, _command, _mppts
from tests.unit.test_phase52_execution_groups import _registry, ROOT
from engine.simulation.artifacts import verify_run_package


def execute(tmp_path, *, composite=False):
    p,a,b=_two_fields(tmp_path,50.,weather=True)
    if composite:
        _ok(p,_command('swap_modules',{'first_module_instance_id':a[0],'second_module_instance_id':b[0]}))
    ready=p.client.get(p.url+'/execution-readiness').json()
    assert ready['ready'],ready
    before=p.path.read_bytes()
    assert p.client.get(p.url+'/execution-readiness').json()==ready
    assert p.path.read_bytes()==before
    response=p.client.post(p.url+'/simulate',json={})
    assert response.status_code==200,response.text
    record=response.json()
    assert record['status'] in {'completed','completed_with_warnings'},record
    return p,record


@pytest.mark.parametrize('composite',[False,True])
def test_standard_mixes_reconcile_and_persist(tmp_path,composite):
    p,record=execute(tmp_path,composite=composite)
    run=p.study.run_root/p.pid/record['simulation_run_id']
    verify_run_package(run)
    canonical=json.loads((run/'simulation-run.json').read_text())
    assert canonical['mixed_orientation']==record['mixed_orientation']
    assert record['mixed_orientation']['dc_wiring_basis']=='nested_terminal_envelope_difference'
    assert p.service.get_bundle(p.pid)['simulation_runs'][-1]['mixed_orientation']==record['mixed_orientation']
    summary=record['summary_result'];breakdown=summary['execution_breakdown']
    assert breakdown['groups']==[] and len(breakdown['orientation_classes'])==2
    assert len(breakdown['mixed_mppts'])==1
    physical=breakdown['mixed_mppts'][0]
    assert physical['raw_dc_energy_wh']-physical['combined_dc_energy_wh']==pytest.approx(physical['dc_loss_energy_wh']['orientation_mismatch_loss_w'],abs=1e-6)
    frame=pd.read_parquet(run/'timeseries.parquet')
    assert (frame['orientation_mismatch_loss_w']>=0).all()
    assert np.allclose(frame['mismatch_loss_w'],frame['module_mismatch_loss_w']+frame['string_mismatch_loss_w'])
    from engine.losses.ledger import with_orientation_mismatch,with_current_limit
    from engine.losses.staged import OPTICAL_CHANNELS,NEW_CHANNELS
    channels=with_current_limit(with_orientation_mismatch((*OPTICAL_CHANNELS,*NEW_CHANNELS),frame),frame)
    for _,loss,up,down in channels:
        assert np.max(abs(frame[up]-frame[loss]-frame[down]))<=1e-6
    names=[c[0] for c in channels]
    assert names.index('orientation_mismatch')<names.index('lid')<names.index('module_quality')
    assert record['mixed_orientation']['is_complete_year'] is False
    assert record['mixed_orientation']['period_totals']['duration_hours']==24
    assert len([a for a in canonical['assumptions'] if a['assumption_id'].startswith('mixed-bypass:')])==1


def test_breakdown_empty_groups_conditional_exception(tmp_path):
    p,record=execute(tmp_path)
    schema=json.loads((ROOT/'schemas/execution-breakdown.schema.json').read_text())
    validator=Draft202012Validator(schema,registry=_registry())
    mixed=record['summary_result']['execution_breakdown']
    validator.validate(mixed)
    absent=deepcopy(mixed);absent.pop('mixed_mppts')
    assert list(validator.iter_errors(absent))
    empty=deepcopy(mixed);empty['mixed_mppts']=[]
    assert list(validator.iter_errors(empty))
    # Exercise an existing separable breakdown producer without changing its fixture.
    _ok(p,_command('assign_strings_to_mppt',{'mppt_instance_id':_mppts(p)[1],'string_ids':['S002']}))
    response=p.client.post(p.url+'/simulate',json={})
    assert response.status_code==200,response.text
    legacy=response.json()['summary_result']['execution_breakdown']
    assert len(legacy['groups'])==2 and 'mixed_mppts' not in legacy
    validator.validate(legacy)


@pytest.mark.parametrize('kind', ['s18a_mixed', 'orientation_mixed'])
def test_browser_detailed_readiness_bytes_match_273cd92(detailed_snapshot_pair, kind):
    expected, actual = detailed_snapshot_pair(kind)
    assert actual['readiness'] == expected['readiness']
    assert 'USE5c' not in json.dumps(actual['readiness'])


def test_nested_losses_reconcile_hourly_under_binding_limits(tmp_path):
    from dataclasses import replace
    from engine.simulation.multi_group import run_multi_group_physics
    from tests.integration.test_rb_use5a_circular_roof import physics_fixture
    weather,bindings,plan,compiled,shading=physics_fixture(tmp_path,periods=24)
    for binding in bindings.values():
        definition=deepcopy(binding['config'].inverter_definition)
        definition['mppt_template'].update(max_operating_current_a=6.,min_operating_voltage_v=450.,max_operating_voltage_v=500.)
        binding['config']=replace(binding['config'],inverter_definition=definition)
    result,_=run_multi_group_physics(weather,bindings=bindings,plan=plan,compiled_geometry=compiled,
                                    shading_configuration=shading,geometry=False)
    frame=result.electrical.ledger.frame
    assert frame.mppt_current_limit_loss_w.sum()>0
    assert frame.dc_wiring_loss_w.sum()>0
    assert frame.dc_voltage_threshold_loss_w.sum()>0
    assert np.max(abs(frame.filter(like='_reconciliation_residual_w').to_numpy()))<1e-6
    for chain in result.inverters.values():
        for item in chain.array_losses.mppt_bank.values():
            env=item.metadata['mixed_terminal_envelopes'];active=env.wiv>0
            assert (env.loc[active,'current_a']<=6.+1e-8).all()
            assert env.loc[active,'voltage_v'].between(450.-1e-8,500.+1e-8).all()
            assert item.metadata['dc_wiring_basis']=='nested_terminal_envelope_difference'


@pytest.mark.parametrize('kind', ['s18a_mixed', 'orientation_mixed'])
def test_detailed_dispatch_results_and_identities_bytes_match_273cd92(detailed_snapshot_pair, kind):
    expected, actual = detailed_snapshot_pair(kind)
    assert actual == expected
    assert actual['successful_detailed_dispatches'] >= 1


def test_diagnostics_use_interval_durations_and_distinct_plant_intervals(tmp_path):
    from types import SimpleNamespace
    from engine.simulation.mixed_orientation import run_record
    index=pd.date_range('2025-01-01',periods=3,freq='30min',tz='UTC')
    timeline=pd.DataFrame({'duration_seconds':[1800,1800,1800],
        'interval_end':index+pd.Timedelta(minutes=30)},index=index)
    context=SimpleNamespace(temporal=SimpleNamespace(timeline=SimpleNamespace(frame=timeline)))
    masks=[np.array([True,False,True]),np.array([True,True,False])]
    rows=[{'inverter_instance_id':f'inv-{i}','mppt_instance_id':'mppt-1',
        'multi_peak_interval_count':2,'multi_peak_duration_hours':1.,'multi_peak_mask':mask,
        'energy_gaps_wh':{'simple_tracker':1.,'second_highest':2.,'lowest':3.}} for i,mask in enumerate(masks)]
    unit=SimpleNamespace(config=SimpleNamespace(module_definition={'revision_id':'module-r1'}))
    plan={'mixed_orientation':{'mppts':[{'mppt_instance_id':'mppt-1','strings':[{'string_id':'s','composition':{'a':5,'b':5}}]}]}}
    record=run_record(plan,{'class':unit},rows,context)
    totals=record['period_totals']
    assert totals['multi_peak_interval_count']==3
    assert totals['multi_peak_mppt_interval_count']==4
    assert totals['multi_peak_duration_hours']==1.5
    assert totals['multi_peak_mppt_duration_hours']==2.
    assert totals['energy_gaps_wh']=={'simple_tracker':2.,'second_highest':4.,'lowest':6.}
    assert len({(r['inverter_instance_id'],r['mppt_instance_id']) for r in record['mppts']})==2
    assert not record['is_complete_year']

@pytest.mark.parametrize('second_inverter',[False,True])
def test_mixed_and_legacy_circuits_have_one_nameplate_and_no_zero_channel_on_unmixed_inverter(tmp_path,second_inverter):
    from tests.unit.test_rb_fix_s2_honest_preflight import INVERTER
    p,a,b=_two_fields(tmp_path,50.,weather=True,count=20)
    target=_mppts(p)[1]
    if second_inverter:
        p.service.add_inverter(p.pid,inverter_definition_revision_id=INVERTER,name='Unmixed inverter')
        design=p.bundle()['electrical_design'];iid=design['inverter_instances'][-1]['inverter_instance_id']
        target=next(m['mppt_instance_id'] for m in design['mppt_instances'] if m['inverter_instance_id']==iid and m['index']==1)
    _ok(p,_command('delete_string',{'string_id':'S001'},'delete-a'),_command('delete_string',{'string_id':'S002'},'delete-b'),
        _command('create_string',{'string_id':'S001','module_instance_ids':a[:10]},'new-a'),
        _command('create_string',{'string_id':'S002','module_instance_ids':b[:10]},'new-b'),
        _command('create_string',{'string_id':'S003','module_instance_ids':a[10:]},'new-c'),
        _command('assign_strings_to_mppt',{'mppt_instance_id':_mppts(p)[0],'string_ids':['S001','S002']},'mix'),
        _command('assign_strings_to_mppt',{'mppt_instance_id':target,'string_ids':['S003']},'unmixed'))
    response=p.client.post(p.url+'/simulate',json={})
    assert response.status_code==200,response.text
    summary=response.json()['summary_result'];breakdown=summary['execution_breakdown']
    assert breakdown['simulated_dc_nameplate_w']==16500.
    assert len(breakdown['groups'])==1 and len(breakdown['orientation_classes'])==2
    assert sum(c['simulated_dc_nameplate_w'] for c in breakdown['groups']+breakdown['orientation_classes'])==16500.
    if second_inverter:
        row=next(i for i in breakdown['inverters'] if i['name']=='Unmixed inverter')
        assert 'orientation_mismatch' not in {r['loss_type'] for r in row['loss_summary']}


@pytest.fixture(scope='module')
def detailed_head273(tmp_path_factory):
    """A read-only git archive, isolated from the working tree and forbidden stores."""
    if reason := missing_commit('273cd92'):
        pytest.skip(reason)
    import io, subprocess, tarfile
    root = tmp_path_factory.mktemp('use5-head273')
    paths = ['apps', 'components', 'docs', 'electrical', 'engine', 'geometry', 'reporting',
             'schemas', 'shading', 'tests', 'tools', 'validation', 'weather']
    archive = subprocess.check_output(['git', '--no-optional-locks', 'archive', '273cd92', *paths], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(root, filter='data')
    return root


@pytest.fixture(scope='module')
def detailed_snapshot_pair(tmp_path_factory, detailed_head273):
    cache = {}
    def pair(kind):
        if kind not in cache:
            cache[kind] = _detailed_pair(tmp_path_factory.mktemp(kind), detailed_head273, kind)
        return cache[kind]
    return pair


def _detailed_pair(tmp_path, reference, kind):
    import inspect, os, shutil, subprocess, sys, textwrap
    source = textwrap.dedent(inspect.getsource(_detailed_snapshot))
    source += "\nimport json,sys\nfrom pathlib import Path\n_detailed_snapshot(sys.argv[1],Path(sys.argv[2]),Path(sys.argv[3]))\n"
    results = []
    for label, code_root in [('head273', reference), ('working', ROOT)]:
        # The destination is an input too: persisted file URIs must be identical.
        work = tmp_path/'case'
        if work.exists(): shutil.rmtree(work)
        work.mkdir()
        output = tmp_path/(label+'-snapshot.json')
        env = {**os.environ, 'PYTHONPATH': str(code_root), 'PYTHONDONTWRITEBYTECODE': '1',
               'RAWIBUMI_PROJECT_STORE': str(work/'global-projects'), 'TMPDIR': str(work)}
        env.pop('PYTHONSTARTUP', None)
        run = subprocess.run([sys.executable, '-c', source, kind, str(work), str(output)], cwd=code_root,
                             env=env, text=True, capture_output=True, timeout=180)
        assert run.returncode == 0, run.stdout+run.stderr
        results.append(json.loads(output.read_text()))
    return results


def _detailed_snapshot(kind, work, output):
    """Run the same deterministic detailed requests through each complete source tree."""
    import datetime, hashlib, json, sys, uuid
    from copy import deepcopy
    from pathlib import Path
    original_uuid = uuid.uuid4
    counter = [0]
    def stable_uuid():
        counter[0] += 1
        return uuid.UUID(int=counter[0] << 96)
    uuid.uuid4 = stable_uuid
    from fastapi.testclient import TestClient
    from tests.unit.test_rb_fix_s18a_losses import _a2_browser_project
    from tests.unit.test_phase69b_browser_launch import REQUEST
    from apps.api.study import _phase5_configuration, browser_electrical_configuration
    from engine.simulation import build_project_revision_from_design, build_design_revision_store, run_canonical_simulation
    from engine.simulation.detailed_inputs import freeze_detailed_selection
    from engine.simulation.optics_thermal import configure_optics_thermal, default_optics_thermal_settings
    original_datetime = datetime.datetime
    class FixedDatetime(original_datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 11, 14, tzinfo=datetime.timezone.utc)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)
    for name, module in list(sys.modules.items()):
        if name.split('.')[0] in {'apps','engine','geometry','electrical','components','weather','shading','reporting','validation'} and module:
            if getattr(module, 'datetime', None) is original_datetime: module.datetime = FixedDatetime
            if getattr(module, 'uuid4', None) is original_uuid: module.uuid4 = stable_uuid
    counter[0] = 0
    app, pid, client = _a2_browser_project(work/'project', mixed=kind=='s18a_mixed')
    service, study = app.state.project_service, app.state.study_service
    bundle = service.get_bundle(pid)
    bundle['loss_settings'] = {'schema_name':'LossSettings','schema_version':'0.1','defaults_id':'recommended_defaults.v1','overrides':{}}; service.store.save(bundle)  # LID1: v1 here and at 273cd92
    if kind == 'orientation_mixed':
        first = bundle['scene']['pv_fields'][0]
        second = deepcopy(first)
        ids = bundle['electrical_design']['strings'][1]['module_instance_ids']
        second.update(pv_field_id='orientation-b', tilt_deg=20., mounting_height_m=1., generated_module_instance_ids=list(ids), modules_per_row=2)
        first['generated_module_instance_ids'] = [m for m in first['generated_module_instance_ids'] if m not in ids]
        first['modules_per_row'] = 2
        bundle['scene']['pv_fields'].append(second)
        for module in bundle['scene']['module_instances']:
            if module['module_instance_id'] in ids:
                module['pv_field_id'] = 'orientation-b'
                module['column_index'] = ids.index(module['module_instance_id'])
                module['transform']['position_z_m'] += .8
        service.store.save(bundle)
    url = f'/api/projects/{pid}'
    result = {'readiness': {}, 'dispatch': {}, 'canonical': {}, 'successful_detailed_dispatches': 0}
    for stage in ('automatic', 'override', 'geometry', 'fallback', 'multiple_inverters'):
        if stage == 'override':
            response = client.patch(url+'/losses', json={'overrides': {'module_mismatch_fraction': 0.}})
            assert response.status_code == 200, response.text
        request = deepcopy(REQUEST)
        if stage == 'geometry': request['electrical_shading_configuration']['requested_fidelity'] = 'level_0_geometric_only'
        if stage == 'fallback':
            bundle = service.get_bundle(pid)
            bundle['electrical_shading_selections'] = {}
            service.store.save(bundle)
            request['electrical_shading_configuration']['fallback_policy'] = 'explicit_lower_fidelity'
        if stage == 'multiple_inverters':
            bundle = service.get_bundle(pid)
            design = bundle['electrical_design']
            extra = deepcopy(design['inverter_instances'][0])
            extra.update(inverter_instance_id='extra-inverter', name='Unused detailed inverter', mppt_instance_ids=['extra-mppt'])
            mppt = deepcopy(design['mppt_instances'][0])
            mppt.update(inverter_instance_id='extra-inverter', mppt_instance_id='extra-mppt', connected_string_ids=[])
            design['inverter_instances'].append(extra)
            design['mppt_instances'].append(mppt)
            design['orientation_policy'] = {'normal_angle_tolerance_deg': 1., 'overrides': [
                {'mppt_instance_id': design['mppt_instances'][0]['mppt_instance_id'], 'reason': 'compatibility fixture'}]}
            service.store.save(bundle)
        ready = client.get(url+'/execution-readiness', params=request['electrical_shading_configuration'])
        result['readiness'][stage] = [ready.status_code, ready.content.decode()]
        launched = client.post(url+'/simulate', json=request)
        result['dispatch'][stage] = [launched.status_code, launched.content.decode()]
        if launched.status_code == 200:
            record = launched.json()
            if record['status'] in {'completed','completed_with_warnings'} and record.get('detailed_electrical_shading',{}).get('execution_identity',{}).get('resolved_fidelity') == 'level_2_bypass_substring':
                result['successful_detailed_dispatches'] += 1
        bundle = service.get_bundle(pid)
        weather = study.weather.load(pid,bundle['weather_selection']['revision_id'])
        electrical = study._simulation_electrical_snapshot(bundle['electrical_design'],project_revision_id='compat-project',snapshot_id='compat-electrical')
        project = build_project_revision_from_design(bundle['scene'], electrical, project_revision_id='compat-project',
            revision_number=1, weather_dataset_revision_id=weather.dataset['revision_id'])
        config = _phase5_configuration(project,configuration_id='compat-config',scene=bundle['scene'])
        config['numerical_options']['loss_settings'] = deepcopy(bundle['loss_settings'])
        configure_optics_thermal(config, bundle.get('optics_thermal_settings',default_optics_thermal_settings()))
        config['shading_configuration']['electrical_shading_configuration'] = browser_electrical_configuration(request['electrical_shading_configuration'])
        components = {**bundle['pinned_components']['modules'],**bundle['pinned_components']['inverters']}
        store = build_design_revision_store(bundle['scene'],electrical,weather,components,detailed_electrical_inputs=freeze_detailed_selection(bundle))
        executed = run_canonical_simulation(project,config,revision_store=store,output_directory=work/stage,
            simulation_run_id='compat-'+stage,engine_version='compat-273cd92',executed_at='2026-11-14T00:00:00Z')
        result['canonical'][stage] = {p.relative_to(executed.artifact_directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in executed.artifact_directory.rglob('*') if p.is_file()}
    output.write_text(json.dumps(result))
