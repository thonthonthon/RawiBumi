"""S17 session history: exact projections, transaction fences and bounded resources."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient

from apps.api.history import DesignHistory, HistorySettings, HistoryConflictError, projection
from apps.api.server import create_app
from tests.unit.test_rb_fix_s2_honest_preflight import Project, INVERTER, MODULE


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path, 18, weather=False, strings=False)


def view(p):
    return p.client.get(p.url).json()


def fence(v, redo=False):
    entries = v['history']['future' if redo else 'past']
    edge = entries[0] if redo else entries[-1]
    return {'expected_project_revision_id': v['bundle']['project']['project_revision']['project_revision_id'],
            'expected_entry_id': edge['entry_id']}


def restore(p, v=None, *, redo=False):
    r = p.client.post(p.url + ('/redo' if redo else '/undo'), json=fence(v or view(p), redo))
    assert r.status_code == 200, r.text
    return r.json()


def command(kind, ids, parameters=None):
    return {'command': {'schema_name':'SceneEditorCommand','schema_version':'0.1','command_id':'s17-command',
                        'command_type':kind,'target_entity_ids':ids,'parameters':parameters or {}}}


def electrical(kind, params):
    return {'commands':[{'schema_name':'ElectricalTopologyCommand','schema_version':'0.1',
                         'command_id':'s17-electrical','command_type':kind,'parameters':params}]}


@pytest.mark.parametrize('route', [
    'metadata','site','losses','optics','accuracy','selection','rectangle','move','box','extrusion',
    'scene','bulk','fill','refill','field_delete','module_delete','module_move','inverter','strings','assign','electrical',
])
def test_every_undoable_route_roundtrips_design(project, route):
    p = project
    b = p.bundle(); sid = b['scene']['surfaces'][0]['surface_id']; fid = b['scene']['pv_fields'][0]['pv_field_id']
    iid = b['electrical_design']['inverter_instances'][0]['inverter_instance_id']
    if route in {'assign', 'electrical', 'refill', 'field_delete'}:
        p.service.create_strings(p.pid, string_length=18, allow_shorter_remainder=True)
    before = projection(p.bundle())
    current = p.bundle()
    mid = current['scene']['module_instances'][0]['module_instance_id']
    string_ids = [s['string_id'] for s in current['electrical_design']['strings']]
    rectangle = {'name':'Second roof','origin_x_m':100,'origin_y_m':100,'width_m':12,'height_m':8,'base_elevation_m':6}
    if route == 'metadata': r = p.client.patch(p.url, json={'name':'Renamed'})
    elif route == 'site': r = p.client.patch(p.url+'/site', json={'elevation_m':26})
    elif route == 'losses': r = p.client.patch(p.url+'/losses', json={'overrides':{'lid_fraction':0.02}})
    elif route == 'optics': r = p.client.patch(p.url+'/optics-thermal', json={'overrides':{'albedo':{'annual_value':0.3}}})
    elif route == 'accuracy': r = p.client.patch(p.url+'/shading-accuracy', json={'overrides':{'level':'high'}})
    elif route == 'selection': r = p.client.post(p.url+'/electrical-shading/selection', json={'module_revision_id':MODULE,'requested_fidelity':'level_0_geometric_only','fallback_policy':'fail_closed'})
    elif route == 'rectangle': r = p.client.post(p.url+'/surfaces/rectangle', json=rectangle)
    elif route in {'move','scene'}:
        free = p.client.post(p.url+'/surfaces/rectangle', json=rectangle).json()['bundle']['scene']['surfaces'][-1]['surface_id']
        before = projection(p.bundle())
        r = (p.client.post(p.url+'/scene/move', json={'entity_id':free,'dx_m':1,'dy_m':0}) if route == 'move'
             else p.client.post(p.url+'/scene/commands', json=command('move_vertex',[free],{'vertex_index':0,'target_x_m':101,'target_y_m':101})))
    elif route == 'box': r = p.client.post(p.url+'/obstacles/box', json={'name':'AHU','origin_x_m':100,'origin_y_m':100,'width_m':2,'depth_m':2,'height_m':2})
    elif route == 'extrusion': r = p.client.post(p.url+'/obstacles/extrusion', json={'name':'Poly','vertices':[[100,100],[102,100],[102,102],[100,102]],'height_m':2})
    elif route == 'bulk':
        r = p.client.post(p.url+'/scene/geometry',json={'operations':[{'operation_id':'s17-mesh','operation_type':'create_mesh','obstacle_id':'mesh-s17','scene_object_id':'mesh-object-s17','name':'Mesh','mesh':{'vertices_m':[[100,100,0],[101,100,0],[100,101,0]],'faces':[[0,1,2]]},'provenance':{'source_id':'synthetic'}}]})
    elif route == 'fill':
        roof = p.client.post(p.url+'/surfaces/rectangle', json=rectangle).json()['bundle']['scene']['surfaces'][-1]['surface_id']
        before = projection(p.bundle())
        r = p.client.post(p.url+'/pv-fields',json={'support_surface_id':roof,'module_definition_revision_id':MODULE,'tilt_deg':10})
    elif route == 'refill': r = p.client.patch(p.url+'/pv-fields/'+fid,json={'tilt_deg':15,'discard_dependent_strings':True})
    elif route == 'field_delete': r = p.client.delete(p.url+'/pv-fields/'+fid+'?discard_dependent_strings=true')
    elif route.startswith('module_'):
        r = p.client.post(p.url+'/pv-fields/modules/commands',json={'command':'delete_modules' if route=='module_delete' else 'move_modules','module_instance_ids':[mid],**({} if route=='module_delete' else {'dx_m':0,'dy_m':0.01})})
    elif route == 'inverter': r = p.client.post(p.url+'/inverters',json={'name':'INV2','inverter_definition_revision_id':INVERTER})
    elif route == 'strings': r = p.client.post(p.url+'/strings',json={'string_length':18,'allow_shorter_remainder':True})
    elif route == 'assign': r = p.client.post(p.url+'/assignments',json={'inverter_instance_id':iid,'string_ids':string_ids})
    else: r = p.client.post(p.url+'/electrical/commands',json=electrical('delete_string',{'string_id':string_ids[0]}))
    assert r.status_code == 200, r.text
    after = projection(p.bundle())
    assert after != before
    n = p.bundle()['project']['project_revision']['revision_number']
    restored = restore(p)
    assert projection(restored['bundle']) == before
    assert restored['bundle']['project']['project_revision']['revision_number'] == n+1
    redone = restore(p, restored, redo=True)
    assert projection(redone['bundle']) == after
    assert redone['bundle']['project']['project_revision']['revision_number'] == n+2


def test_successive_undo_undo_redo_and_runs_are_immutable(project):
    p = project
    raw = p.bundle(); raw['simulation_runs'] = [{'simulation_run_id':'saved','status':'completed','project_revision_id':'saved-r1','scene_revision_id':'saved-scene','electrical_revision_id':'saved-electrical','weather_dataset_revision_id':'saved-weather','opaque_evidence':[1,2,3]}]
    p.service.save_bundle(raw, history_mode='neutral')
    initial = projection(p.bundle())
    v1 = p.service.update_project(p.pid, name='One')
    v2 = p.service.update_project(p.pid, description='Two')
    runs = json.dumps(p.bundle()['simulation_runs'],sort_keys=True)
    n = v2['bundle']['project']['project_revision']['revision_number']
    a=restore(p,v2); b=restore(p,a); c=restore(p,b,redo=True)
    assert projection(a['bundle']) == projection(v1['bundle'])
    assert projection(b['bundle']) == initial
    assert projection(c['bundle']) == projection(v1['bundle'])
    assert [x['bundle']['project']['project_revision']['revision_number'] for x in (a,b,c)] == [n+1,n+2,n+3]
    assert json.dumps(p.bundle()['simulation_runs'],sort_keys=True) == runs


def test_same_revision_two_tab_rename_and_stale_projection_fences(project):
    p=project
    a=p.service.update_project(p.pid,name='First')
    b=p.service.update_project(p.pid,name='Other tab')
    assert a['bundle']['project']['project_revision']==b['bundle']['project']['project_revision']
    saved=p.path.read_bytes()
    refusal=p.client.post(p.url+'/undo',json=fence(a))
    assert refusal.status_code==409 and refusal.json()['detail']['reason']=='revision_mismatch'
    assert p.path.read_bytes()==saved and not view(p)['history']['past']
    current=p.service.update_project(p.pid,name='New edit')
    raw=p.service.store.load(p.pid);raw['project']['description']='External write';p.service.store.save(raw)
    saved=p.path.read_bytes()
    refusal=p.client.post(p.url+'/undo',json=fence(current))
    assert refusal.status_code==409 and refusal.json()['detail']['reason']=='revision_mismatch'
    assert p.path.read_bytes()==saved


def test_failed_save_and_failed_restore_are_atomic(project, monkeypatch):
    p=project
    before=p.path.read_bytes(); history=deepcopy(view(p)['history'])
    original=p.service.store.save
    def fail(_): raise OSError('disk failure')
    monkeypatch.setattr(p.service.store,'save',fail)
    with pytest.raises(OSError):p.service.update_project(p.pid,name='Not saved')
    assert p.path.read_bytes()==before and view(p)['history']==history
    monkeypatch.setattr(p.service.store,'save',original)
    v=p.service.update_project(p.pid,name='Restorable')
    before=p.path.read_bytes(); history=deepcopy(v['history'])
    def reject(*_):raise ValueError('structural validation failed')
    monkeypatch.setattr(p.service,'_validate_changed_scene_bounds',reject)
    r=p.client.post(p.url+'/undo',json=fence(v))
    assert r.status_code==422
    assert p.path.read_bytes()==before and view(p)['history']==history


def test_neutral_saves_noops_and_barriers(project):
    p=project
    v=p.service.update_project(p.pid,name='Changed')
    h=v['history']
    p.service.set_workspace_mode(p.pid,mode='blank_engineering_plane')
    p.service.update_project(p.pid,name='Changed')
    assert view(p)['history']==h
    p.service.save_bundle(p.bundle(), history_mode='barrier')
    stored=p.path.read_bytes()
    r=p.client.post(p.url+'/undo',json=fence(v))
    assert r.status_code==409 and r.json()['detail']['reason']=='history_unavailable'
    assert p.path.read_bytes()==stored


def test_weather_barrier_site_restore_missing_weather_and_busy(tmp_path):
    p=Project(tmp_path,18)
    assert not view(p)['history']['past']  # actual weather acquisition is a barrier
    old=projection(p.bundle())
    v=p.study.update_site(p.pid,elevation_m=27,clear_weather_selection=True)
    restored=restore(p,v)
    assert projection(restored['bundle'])==old
    cleared=restore(p,restored,redo=True)
    selection=restored['bundle']['weather_selection']
    directory=p.study.weather._directory(p.pid,selection['revision_id'])
    (directory/'weather-series.parquet').unlink()
    before=p.path.read_bytes(); h=deepcopy(cleared['history'])
    r=p.client.post(p.url+'/undo',json=fence(cleared))
    assert r.status_code==422 and 'weather' in r.text
    assert p.path.read_bytes()==before and view(p)['history']==h


def test_restart_and_deleted_project_never_resurrect(project):
    p=project;v=p.service.update_project(p.pid,name='Edit')
    restarted=TestClient(create_app(store_root=p.service.store.root))
    r=restarted.post(p.url+'/undo',json=fence(v))
    assert r.status_code==409 and r.json()['detail']['reason']=='history_unavailable'
    p.study.delete_project(p.pid,confirm=p.pid)
    assert p.client.post(p.url+'/undo',json=fence(v)).status_code==404
    assert not p.path.exists()


@pytest.mark.parametrize('steps',[1,10,100])
def test_exact_step_limits_and_adjacency(project,steps):
    p=project;p.service.history=DesignHistory(HistorySettings(steps=steps))
    for i in range(steps+1):p.service.update_project(p.pid,name=f'Step {i}')
    ring=p.service.history.rings[p.pid]
    assert len(ring.past)==steps
    assert all(left.after is right.before for left,right in zip(ring.past,ring.past[1:]))
    v=view(p)
    for _ in range(steps):v=restore(p,v)
    assert len(v['history']['future'])==steps and not v['history']['past']
    r=p.client.post(p.url+'/undo',json={'expected_project_revision_id':v['bundle']['project']['project_revision']['project_revision_id'],'expected_entry_id':'old'})
    assert r.status_code==409


def test_byte_lru_expiry_and_large_state_limits(project):
    p=project; b=p.bundle()
    # Synthetic 2600-module memory shape, not a fabricated valid layout.
    b['scene']['module_instances']=[{**b['scene']['module_instances'][0],'module_instance_id':f'synthetic-{i}'} for i in range(2600)]
    size=len(projection(b));now=[0.0]
    hist=DesignHistory(HistorySettings(steps=100,project_bytes_max=size*3+500,total_bytes_max=size*6+1000,idle_seconds=10),clock=lambda:now[0])
    for i in range(5):
        a=deepcopy(b);a['project']['name']=f'large-{i}'
        hist.publish('one',hist.prepare('one',b,a,'Name'));b=a;now[0]+=0.1
    assert len(hist.view('one')['past'])==2
    for key in ('two','three'):
        a=deepcopy(b);a['project']['name']=key
        hist.publish(key,hist.prepare(key,b,a,'Name'));now[0]+=0.1
    assert not hist.view('one')['past'] and hist.view('two')['past']
    now[0]+=11
    assert not hist.view('two')['past']
    tiny=DesignHistory(HistorySettings(project_bytes_max=1))
    a=deepcopy(b);a['project']['name']='Oversized edit'
    tiny.publish('p',tiny.prepare('p',b,a,'Edit'))
    assert tiny.view('p')['reason']=='byte_limit'


@pytest.mark.parametrize('edition,expected',[(None,10),('commercial',100),('community_self_hosted',10),('hosted_paid',10),(' commercial ',10)])
def test_settings_edition(monkeypatch,edition,expected):
    for key in ('STEPS','PROJECT_BYTES_MAX','TOTAL_BYTES_MAX','IDLE_SECONDS'):monkeypatch.delenv('RAWIBUMI_UNDO_'+('HISTORY_STEPS' if key=='STEPS' else key),raising=False)
    if edition is None:monkeypatch.delenv('RAWIBUMI_DEPLOYMENT_EDITION',raising=False)
    else:monkeypatch.setenv('RAWIBUMI_DEPLOYMENT_EDITION',edition)
    assert HistorySettings.from_env().steps==expected
    monkeypatch.setenv('RAWIBUMI_UNDO_HISTORY_STEPS','17')
    assert HistorySettings.from_env().steps==17


@pytest.mark.parametrize('key,value',[('HISTORY_STEPS','0'),('HISTORY_STEPS','101'),('HISTORY_STEPS','nan'),('PROJECT_BYTES_MAX','-1'),('TOTAL_BYTES_MAX','1.5'),('IDLE_SECONDS','0'),
    ('HISTORY_STEPS',' 10'),('HISTORY_STEPS','+10'),('HISTORY_STEPS','1_0'),('IDLE_SECONDS','10 '),('PROJECT_BYTES_MAX','\u0661\u0660')])
def test_invalid_settings_refused_at_startup(tmp_path,monkeypatch,key,value):
    monkeypatch.setenv('RAWIBUMI_UNDO_'+key,value)
    with pytest.raises(ValueError,match='RAWIBUMI_UNDO_'):create_app(store_root=tmp_path/'projects')


def test_unbumped_project_edits_are_labelled_from_their_operation(project):
    p=project
    p.service.update_project(p.pid,name='Labelled')
    p.service.update_project(p.pid,description='Only the description')
    labels=[e['label'] for e in view(p)['history']['past']]
    assert labels[-2:]==['Rename project','Edit project details']


def test_actual_asset_and_file_weather_barriers(project):
    p=project
    p.service.update_project(p.pid,name='Before asset')
    topology=deepcopy(p.service.catalog['module_topologies']['topology-rawibumi-uat-550-r1'])
    source=deepcopy(p.service.catalog['sources']['src-rawibumi-uat-topology-fixture'])
    r=p.client.post(p.url+'/electrical-shading/assets/import',json={'asset_kind':'module_topology','asset':topology,'sources':[source]})
    assert r.status_code==200,r.text
    assert not view(p)['history']['past']
    p.service.update_project(p.pid,name='Before weather')
    from tests.unit.test_rb_fix_s12b_weather_import import NATIVE
    r=p.client.post(p.url+'/weather/import?filename=synthetic.csv&dry_run=false&accept_distant_location=true',content=NATIVE,headers={'Content-Type':'application/octet-stream'})
    assert r.status_code==200,r.text
    assert not view(p)['history']['past']


def test_real_run_package_is_byte_identical_across_history(tmp_path):
    import hashlib
    p=Project(tmp_path,18)
    response=p.client.post(p.url+"/simulate",json={})
    assert response.status_code==200,response.text
    run=response.json()
    directory=p.study.run_root/p.pid/run['simulation_run_id']
    def hashes():return {str(f.relative_to(directory)):hashlib.sha256(f.read_bytes()).hexdigest() for f in directory.rglob('*') if f.is_file()}
    before=hashes();records=deepcopy(p.bundle()['simulation_runs'])
    assert before
    changed=p.service.update_project(p.pid,name='After saved run')
    restore(p,changed);restore(p,redo=True)
    assert hashes()==before and p.bundle()['simulation_runs']==records


def test_ordinary_cas_and_busy_site_restore_are_preserved(project):
    from apps.api.service import ProjectConflictError
    from apps.api.study import ProjectBusyError
    p=project; stale=p.bundle();p.service.update_project(p.pid,name='Newer')
    with pytest.raises(ProjectConflictError,match='project changed concurrently; reload and retry'):
        p.service.save_bundle(stale)
    v=p.service.update_site(p.pid,elevation_m=28)
    old=p.path.read_bytes();h=deepcopy(v['history'])
    def busy(_):raise ProjectBusyError('project has a simulation or weather acquisition in progress')
    with pytest.raises(ProjectBusyError):p.service.restore_history(p.pid,**fence(v),require_idle=busy)
    assert p.path.read_bytes()==old and view(p)['history']==h
