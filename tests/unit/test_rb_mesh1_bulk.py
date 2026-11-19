"""Real disposable HTTP geometry batches and exact editor transaction history."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from apps.api.server import create_app
from geometry.scene import SceneEditorSession
from geometry.scene.bulk import GeometryBatchError,validate_batch_limits
from tests.unit.test_rb_mesh1_tables import base_scene,definition,table


def mesh_op(kind='create_mesh',**overrides):
    return {'operation_id':'mesh-op','operation_type':kind,'obstacle_id':'mesh-a',**({'scene_object_id':'obj-mesh-a'} if kind=='create_mesh' else {}),'name':'Mesh A','mesh':{'vertices_m':[[20,20,5],[24,20,5],[24,24,5],[20,24,5]],'faces':[[0,1,2,3]]},'provenance':{'source_id':'synthetic'},**overrides}


def field_op(**overrides):
    return {'operation_id':'field-op','operation_type':'create_explicit_field','pv_field_id':'explicit-a','name':'Explicit A','tables':[table(anchor_xyz_m=[2,2,3],tilt_deg=0.)],'provenance':{'source_id':'synthetic'},**overrides}


@pytest.fixture
def project(tmp_path):
    app=create_app(store_root=tmp_path/'projects',library_root=tmp_path/'library')
    client=TestClient(app);response=client.post('/api/projects',json={'name':'MESH1 disposable','latitude_deg':-6.425,'longitude_deg':106.831,'timezone':'Asia/Jakarta'})
    assert response.status_code==201,response.text
    view=response.json();pid=view['bundle']['project']['project_id'];service=app.state.project_service
    # Synthetic pinned definition, using the low-level store for fixture assembly.
    bundle=service.get_bundle(pid);bundle['pinned_components']['modules']['module-r1']=definition();service.store.save(bundle)
    return app,client,pid,tmp_path


def url(pid):return f'/api/projects/{pid}'


def test_editor_batch_is_one_frame_with_exact_undo_redo_and_failure_rollback():
    scene=base_scene();editor=SceneEditorSession(scene);before=editor.canonical_json()
    editor.geometry_batch([mesh_op(),field_op()],{'module-r1':definition()});after=editor.canonical_json()
    assert editor.undo_depth==1 and editor.undo() and editor.canonical_json()==before
    assert editor.redo() and editor.canonical_json()==after
    with pytest.raises(GeometryBatchError):editor.geometry_batch([mesh_op(obstacle_id='other',scene_object_id='obj-other'),field_op(operation_id='later')],{'module-r1':definition()})
    assert editor.canonical_json()==after and editor.undo_depth==1


def test_http_preview_commit_noop_and_exact_3d_readback(project):
    app,c,pid,tmp=project;prefix=url(pid);before=c.get(prefix).json();bundle_bytes=(tmp/'projects'/f'{pid}.json').read_bytes()
    body={'operations':[mesh_op(),field_op()]}
    preview=c.post(prefix+'/scene/geometry',json={**body,'dry_run':True});assert preview.status_code==200,preview.text
    assert preview.json()['after']['module_count']==1 and preview.json()['after']['mesh_count']==1
    assert (tmp/'projects'/f'{pid}.json').read_bytes()==bundle_bytes
    response=c.post(prefix+'/scene/geometry',json=body);assert response.status_code==200,response.text
    after=response.json();assert len(after['bundle']['scene']['pv_fields'])==1 and len(after['bundle']['scene']['obstacles'])==1
    assert after['bundle']['project']['project_revision']['revision_number']==before['bundle']['project']['project_revision']['revision_number']+1
    assert after['bundle']['electrical_design']['electrical_revision_id']==before['bundle']['electrical_design']['electrical_revision_id']
    derived=c.get(prefix+'/scene/geometry-3d');assert derived.status_code==200,derived.text
    assert derived.json()['source_scene_hash']==after['identity']['scene_hash']
    assert derived.json()['obstacles'][0]['mesh']['vertices_3d']==mesh_op()['mesh']['vertices_m']
    assert derived.json()['modules'][0]['center_xyz']==[2.,2.,3.]
    current=(tmp/'projects'/f'{pid}.json').read_bytes()
    response=c.post(prefix+'/scene/geometry',json={'operations':[mesh_op('replace_mesh')]});assert response.status_code==200,response.text
    assert (tmp/'projects'/f'{pid}.json').read_bytes()==current


@pytest.mark.parametrize('bad',[
    field_op(tables=[table(module_definition_revision_id='missing')]),
    mesh_op(operation_id='bad',obstacle_id='bad-mesh',scene_object_id='bad-object',mesh={'vertices_m':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,999]]}),
    {'operation_id':'bad','operation_type':'unknown','obstacle_id':'bad'},
    {'operation_id':'mesh-op','operation_type':'delete_mesh','obstacle_id':'missing'},
])
def test_later_refusal_has_context_and_leaves_bytes_pins_and_revisions_unchanged(project,bad):
    app,c,pid,tmp=project;path=tmp/'projects'/f'{pid}.json';before=path.read_bytes()
    response=c.post(url(pid)+'/scene/geometry',json={'operations':[mesh_op(),bad]})
    assert response.status_code==422,response.text
    detail=response.json()['detail'];assert detail['operation_index']==1 and detail['operation_id']==bad['operation_id']
    assert path.read_bytes()==before


def test_physical_contact_refuses_whole_batch_and_preview_names_face(project):
    app,c,pid,tmp=project;path=tmp/'projects'/f'{pid}.json';before=path.read_bytes()
    obstacle=mesh_op(mesh={'vertices_m':[[-2,-2,3],[6,-2,3],[6,6,3],[-2,6,3]],'faces':[[0,1,2,3]]})
    body={'operations':[obstacle,field_op()]}
    preview=c.post(url(pid)+'/scene/geometry',json={**body,'dry_run':True});assert preview.status_code==200,preview.text
    conflict=preview.json()['conflicts'][0];assert conflict['code']=='module_obstacle_overlap' and conflict['other_id']=='mesh-a' and conflict['face_index']==0
    result=c.post(url(pid)+'/scene/geometry',json=body);assert result.status_code==422,result.text
    assert path.read_bytes()==before


def test_vertical_module_has_line_readback_and_real_3d_corners(project):
    app,c,pid,tmp=project
    response=c.post(url(pid)+'/scene/geometry',json={'operations':[field_op(tables=[table(anchor_xyz_m=[0,0,3],tilt_deg=90.)])]});assert response.status_code==200,response.text
    view=response.json();objects=view['scene_view']['geometry_objects'];assert objects[0]['plan_geometry']['type']=='LineString'
    assert not [f for f in view['scene_view']['local_features'] if f['category']=='module']
    three=c.get(url(pid)+'/scene/geometry-3d').json();assert len(three['modules'][0]['corners_3d'])==4


def test_locked_mesh_and_readonly_commands_refuse_and_legacy_delete_still_works(project):
    app,c,pid,tmp=project;prefix=url(pid)
    assert c.post(prefix+'/scene/geometry',json={'operations':[mesh_op(),field_op()]}).status_code==200
    current=(tmp/'projects'/f'{pid}.json').read_bytes()
    moved=c.post(prefix+'/scene/move',json={'entity_id':'obj-mesh-a','dx_m':1,'dy_m':0});assert moved.status_code==422 and 'read-only' in moved.text
    update=c.patch(prefix+'/pv-fields/explicit-a',json={'tilt_deg':15});assert update.status_code==422 and 'read-only' in update.text
    assert (tmp/'projects'/f'{pid}.json').read_bytes()==current
    deleted=c.delete(prefix+'/pv-fields/explicit-a?dry_run=true');assert deleted.status_code==200,deleted.text
    assert deleted.json()['module_count']==1
    assert c.delete(prefix+'/pv-fields/explicit-a').status_code==200
    service=app.state.project_service;bundle=service.get_bundle(pid);bundle['scene']['obstacles'][0]['locked']=True;service.store.save(bundle);current=(tmp/'projects'/f'{pid}.json').read_bytes()
    refused=c.post(prefix+'/scene/geometry',json={'operations':[{'operation_id':'delete','operation_type':'delete_mesh','obstacle_id':'mesh-a'}]});assert refused.status_code==422 and 'locked' in refused.text
    assert (tmp/'projects'/f'{pid}.json').read_bytes()==current


@pytest.mark.parametrize('operations',[[None],[],[{'operation_id':'x','operation_type':'create_explicit_field','tables':[{'modules_across':50000,'modules_up':2}]}]])
def test_limits_fail_before_materialization_with_structured_error(operations):
    with pytest.raises(GeometryBatchError):validate_batch_limits(operations)


def test_raw_json_limit_and_malformed_body_are_structured(project):
    app,c,pid,tmp=project
    for content in (b'{',b'{}',b'[]'):
        response=c.post(url(pid)+'/scene/geometry',content=content,headers={'content-type':'application/json'});assert response.status_code==422,response.text
        assert 'message' in response.json()['detail']
    response=c.post(url(pid)+'/scene/geometry',content=b' '*(16*1024*1024+1),headers={'content-type':'application/json'});assert response.status_code==413


def test_delete_discards_whole_dependent_string_only_after_confirmation(project):
    app,c,pid,tmp=project;prefix=url(pid)
    response=c.post(prefix+'/scene/geometry',json={'operations':[field_op(tables=[table(anchor_xyz_m=[2,2,3],tilt_deg=0.,modules_across=2)])]})
    assert response.status_code==200,response.text
    service=app.state.project_service;bundle=service.get_bundle(pid)
    mids=[m['module_instance_id'] for m in bundle['scene']['module_instances']]
    bundle['electrical_design']['strings']=[{'string_id':'S001','name':'Dependent string','module_instance_ids':mids,'target_mppt_instance_id':None,'enabled':True}]
    service.store.save(bundle);path=tmp/'projects'/f'{pid}.json';before=path.read_bytes()
    body={'operations':[{'operation_id':'delete','operation_type':'delete_explicit_field','pv_field_id':'explicit-a'}]}
    preview=c.post(prefix+'/scene/geometry',json={**body,'dry_run':True});assert preview.status_code==200,preview.text
    assert preview.json()['string_ids']==['S001'] and preview.json()['requires_discard_dependent_strings']
    assert path.read_bytes()==before
    refused=c.post(prefix+'/scene/geometry',json=body);assert refused.status_code==422,refused.text
    assert path.read_bytes()==before
    committed=c.post(prefix+'/scene/geometry',json={**body,'discard_dependent_strings':True});assert committed.status_code==200,committed.text
    after=committed.json()['bundle'];assert after['electrical_design']['strings']==[] and after['scene']['module_instances']==[]
    assert after['project']['project_revision']['revision_number']==bundle['project']['project_revision']['revision_number']+1
    assert after['electrical_design']['electrical_revision_id']!=bundle['electrical_design']['electrical_revision_id']


def test_failed_save_never_changes_persisted_geometry_or_pins(project,monkeypatch):
    app,c,pid,tmp=project;service=app.state.project_service;path=tmp/'projects'/f'{pid}.json';before=path.read_bytes()
    def fail(*args,**kwargs):raise OSError('synthetic storage failure')
    monkeypatch.setattr(service.store,'save',fail)
    with pytest.raises(OSError,match='synthetic storage failure'):
        c.post(url(pid)+'/scene/geometry',json={'operations':[mesh_op(),field_op()]})
    assert path.read_bytes()==before


def test_nonfinite_raw_json_is_refused_atomically(project):
    app,c,pid,tmp=project;path=tmp/'projects'/f'{pid}.json';before=path.read_bytes()
    op=field_op(tables=[table(anchor_xyz_m=[float('nan'),0,3])])
    response=c.post(url(pid)+'/scene/geometry',content=json.dumps({'operations':[mesh_op(),op]}),headers={'content-type':'application/json'})
    assert response.status_code==422,response.text
    assert 'finite' in response.json()['detail']['message'] and path.read_bytes()==before


def test_batch_limit_accepts_required_scale_without_materializing():
    tables=[table(table_id=f'table-{i}') for i in range(1000)]
    operations=[field_op(tables=tables)]+[mesh_op(operation_id=f'mesh-{i}',obstacle_id=f'mesh-{i}',scene_object_id=f'obj-{i}') for i in range(300)]
    validate_batch_limits(operations)
    assert len(json.dumps({'operations':operations}).encode())<16*1024*1024


def test_browser_self_shading_is_on_for_every_layout():
    # RB-4D (user, 2026-11-08): generated, mesh-only and explicit scenes all run with module self-shading,
    # and the policy changes nothing else in the configuration.
    from apps.api.study import _phase5_configuration
    from tests.unit.test_rb_mesh1_tables import create
    from tests.unit.test_phase49c_reference_projects import _reference
    project=_reference('R1')['project_revision']
    native=base_scene();explicit,_,_=create()
    mesh_only=deepcopy(native)
    from geometry.scene.bulk import apply_geometry_operations
    apply_geometry_operations(mesh_only,[mesh_op()],{'module-r1':definition()})
    baseline=_phase5_configuration(project,configuration_id='policy')
    assert baseline['shading_configuration']['self_shading_enabled'] is True
    for scene in (native,mesh_only,explicit):
        assert _phase5_configuration(project,configuration_id='policy',scene=scene)==baseline
