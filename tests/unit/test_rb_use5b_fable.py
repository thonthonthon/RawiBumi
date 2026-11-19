"""Fable F1: equal-state composite strings retain the certified uniform limit."""
from copy import deepcopy
import numpy as np
import pytest

from apps.api.catalog import load_reference_catalog
from components.pan.pvsyst_sdm import calculate_pvsyst_diode_parameters
from engine.simulation.mixed_orientation import BatchCurves
from engine.simulation.unshaded import _module_runtime_properties


@pytest.fixture(scope='module')
def equal_state_weather():
    ps = _module_runtime_properties(load_reference_catalog()['modules']['mod-rawibumi-uat-550-r1'])[0]
    rng = np.random.default_rng(7)
    irradiance = np.r_[rng.uniform(1e-3, 5., 200), rng.uniform(5., 300., 200), rng.uniform(300., 1300., 200)]
    temperature = rng.uniform(15., 70., 600)
    def parameters(delta=0.):
        return np.stack(np.broadcast_arrays(*calculate_pvsyst_diode_parameters(
            effective_irradiance_w_m2=irradiance+delta, cell_temperature_c=temperature, parameter_set=ps)), axis=-1)
    return parameters


@pytest.mark.parametrize('splits,diodes,delta', [
    ([[26,0],[0,26]],3,0.), ([[26,0],[13,13]],3,0.),
    ([[13,13],[5,21]],3,0.), ([[10,16],[7,19]],0,0.),
    ([[9,9,8],[5,10,11]],3,0.), ([[13,13],[5,21]],3,1e-13),
    ([[13,13],[5,21]],3,1e-10), ([[13,13],[5,21]],3,1e-8),
    ([[8,7],[3,12]],3,0.), ([[10,10],[3,17]],3,0.),
])
@pytest.mark.parametrize('options', [{}, {'k':.97,'resistance_ohm':.2}, {'current_limit_a':8.},
    {'voltage_window':(400.,1000.)}, {'k':.97,'resistance_ohm':.2,'current_limit_a':8.,'voltage_window':(400.,1000.)}])
def test_identical_and_near_identical_splits_match_uniform(equal_state_weather, splits, diodes, delta, options):
    p = equal_state_weather()
    classes = np.stack([p, equal_state_weather(delta), *([p] if len(splits[0])==3 else [])], axis=1)
    n = len(splits[0])
    actual = BatchCurves(classes, splits, [diodes]*n, [.7]*n).nested(**options)
    uniform = BatchCurves(p[:,None,:], [[sum(splits[0])]]*2, [diodes], [.7]).nested(**options)
    for envelope in ('raw','w0','wi','wiv'):
        np.testing.assert_allclose(actual[envelope]['power_w'], uniform[envelope]['power_w'], rtol=1e-6, atol=1e-8)
        assert np.all(actual[envelope]['error_bound_w'] <= np.maximum(1e-7, actual[envelope]['power_w']*1e-7))


def test_diffuse_daylight_composite_splits_on_product_path(tmp_path, monkeypatch, record_property):
    from tests.integration.test_rb_use5a_circular_roof import physics_fixture
    from engine.simulation.multi_group import run_multi_group_physics
    import engine.simulation.mixed_orientation as mixed
    weather, bindings, plan, compiled, shading = physics_fixture(tmp_path, periods=24*15)
    plan = deepcopy(plan)
    classes = plan['mixed_orientation']['classes'][:2]
    plan['mixed_orientation']['classes'] = classes
    physical = plan['mixed_orientation']['mppts'][0]
    a,b = [c['execution_group_id'] for c in classes]
    physical['modules_in_series'] = 15
    physical['strings'] = [dict(string_id='ten-five', module_instance_ids=classes[0]['module_instance_ids'][:10]+classes[1]['module_instance_ids'][:5], composition={a:10,b:5}),
        dict(string_id='four-eleven', module_instance_ids=classes[0]['module_instance_ids'][10:14]+classes[1]['module_instance_ids'][5:16], composition={a:4,b:11})]
    plan['mixed_orientation']['mppts'] = [physical]
    classes[0]['module_instance_ids'] = classes[0]['module_instance_ids'][:14]
    classes[1]['module_instance_ids'] = classes[1]['module_instance_ids'][:16]
    bindings = {key:{**value,'group':next(c for c in classes if c['execution_group_id']==key)} for key,value in bindings.items() if key in (a,b)}
    from dataclasses import replace
    inverter = deepcopy(next(iter(bindings.values()))['config'].inverter_definition)
    inverter['mppt_template'].update(count=1,total_input_count=2,input_count_per_mppt=2)
    bindings = {key:{**value,'config':replace(value['config'],inverter_definition=inverter)} for key,value in bindings.items()}
    series = weather.series
    daylight = (series.index.hour>=7)&(series.index.hour<=16)
    series['dni_w_m2'] = 0.
    series['dhi_w_m2'] = np.where(daylight, np.linspace(.01,5.,len(series)), 0.)
    series['ghi_w_m2'] = series['dhi_w_m2']
    observed = []
    original = mixed.class_parameters
    def capture(*args):
        p = original(*args); observed.append(p.copy()); return p
    monkeypatch.setattr(mixed,'class_parameters',capture)
    result,_ = run_multi_group_physics(weather, bindings=bindings, plan=plan, compiled_geometry=compiled,
        shading_configuration=shading, geometry=False)
    assert len(observed)==2
    assert np.array_equal(observed[0],observed[1])
    record_property('diffuse_class_states_bit_identical', True)
    assert np.max(abs(result.timeseries['orientation_mismatch_loss_w']))<1e-6
    assert result.metadata['mixed_orientation']['period_totals']['duration_hours']==360.


@pytest.mark.parametrize('method', ['envelope','nested'])
def test_solver_failure_is_clear_422_with_mppt_and_interval(tmp_path, monkeypatch, method):
    from fastapi.testclient import TestClient
    from tests.unit.test_rb_s14b_electrical import _two_fields, _mppts
    p,_,_ = _two_fields(tmp_path,50.,weather=True)
    p.client = TestClient(p.app, raise_server_exceptions=False)
    original = BatchCurves.__init__
    failures = []
    def capture(self,*args,**kwargs):
        original(self,*args,**kwargs)
        # Preserve the failing batch's real active-interval ordinal.
        failures.append(self.h)
    def fail(self,*args,**kwargs):
        error = RuntimeError('injected uncertifiable segment')
        error.rows = np.array([1])
        raise error
    monkeypatch.setattr(BatchCurves,'__init__',capture)
    monkeypatch.setattr(BatchCurves,method,fail)
    before = p.path.read_bytes()
    response = p.client.post(p.url+'/simulate',json={})
    assert response.status_code==422, response.text
    detail = response.json()['detail']
    assert 'Mixed-orientation simulation could not be solved' in detail
    assert _mppts(p)[0] in detail and 'MPPT 1' in detail
    assert '2025-01-01T11:00:00+07:00' in detail
    assert 'injected uncertifiable segment' in detail
    assert failures and p.path.read_bytes()==before


from tests.unit.test_rb_use5a_mixed_integration import detailed_head273


@pytest.mark.parametrize('kind', ['single_group','multi_group'])
def test_standard_unmixed_bytes_match_273cd92(tmp_path, detailed_head273, kind):
    import inspect, os, shutil, subprocess, sys, textwrap, json
    from tests.unit.test_phase52_execution_groups import ROOT
    source = textwrap.dedent(inspect.getsource(_standard_snapshot))
    source += '\nimport sys\nfrom pathlib import Path\n_standard_snapshot(sys.argv[1],Path(sys.argv[2]),Path(sys.argv[3]))\n'
    snapshots = []
    for label, root in [('head273',detailed_head273),('working',ROOT)]:
        work = tmp_path/'case'
        if work.exists(): shutil.rmtree(work)
        work.mkdir()
        output = tmp_path/(label+'.json')
        env = {**os.environ, 'PYTHONPATH':str(root), 'PYTHONDONTWRITEBYTECODE':'1',
            'RAWIBUMI_PROJECT_STORE':str(work/'global-projects'), 'TMPDIR':str(work)}
        env.pop('PYTHONSTARTUP',None)
        run = subprocess.run([sys.executable,'-c',source,kind,str(work),str(output)],cwd=root,env=env,
            capture_output=True,text=True,timeout=180)
        assert run.returncode==0, run.stdout+run.stderr
        snapshots.append(json.loads(output.read_text()))
    assert snapshots[1]==snapshots[0]


def _standard_snapshot(kind, work, output):
    import datetime, hashlib, json, sys, uuid
    original_uuid = uuid.uuid4
    counter = [0]
    def stable_uuid():
        counter[0] += 1
        return uuid.UUID(int=counter[0] << 96)
    uuid.uuid4 = stable_uuid
    from tests.unit.test_rb_s14b_electrical import _two_fields, _ok, _command, _mppts
    original_datetime = datetime.datetime
    class FixedDatetime(original_datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026,11,14,tzinfo=datetime.timezone.utc)
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)
    for name,module in list(sys.modules.items()):
        if name.split('.')[0] in {'apps','engine','geometry','electrical','components','weather','shading','reporting','validation'} and module:
            if getattr(module,'datetime',None) is original_datetime: module.datetime = FixedDatetime
            if getattr(module,'uuid4',None) is original_uuid: module.uuid4 = stable_uuid
    counter[0] = 0
    p,_,_ = _two_fields(work, 10. if kind=='single_group' else 30., weather=True)
    pinned = p.service.get_bundle(p.pid); pinned['loss_settings'] = {'schema_name':'LossSettings','schema_version':'0.1','defaults_id':'recommended_defaults.v1','overrides':{}}; p.service.store.save(pinned)  # LID1: v1 here and at 273cd92
    if kind=='multi_group':
        _ok(p,_command('assign_strings_to_mppt',{'mppt_instance_id':_mppts(p)[1],'string_ids':['S002']}))
    ready = p.client.get(p.url+'/execution-readiness')
    assert ready.status_code==200 and ready.json()['ready'], ready.text
    assert ready.json()['execution_plan']['group_count']==(1 if kind=='single_group' else 2)
    assert 'mixed_orientation' not in ready.json()['execution_plan']
    response = p.client.post(p.url+'/simulate',json={})
    assert response.status_code==200, response.text
    record = response.json()
    assert record['status'] in {'completed','completed_with_warnings'}
    assert 'mixed_orientation' not in record
    directory = p.study.run_root/p.pid/record['simulation_run_id']
    artifacts = {f.relative_to(directory).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in directory.rglob('*') if f.is_file()}
    assert 'timeseries.parquet' in artifacts and 'simulation-run.json' in artifacts
    output.write_text(json.dumps({'readiness_bytes':ready.content.hex(),'dispatch_bytes':response.content.hex(),'artifact_bytes_sha256':artifacts}))
