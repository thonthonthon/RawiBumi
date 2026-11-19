"""S11b real HTTP, physical support gaps and exact plane/packing regressions."""
from tests.unit._availability import missing_commit
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

import pytest
from shapely.geometry import Polygon

from geometry.scene import SceneEditorSession
from geometry.scene.surface_plane import SurfacePlane
from geometry.scene3d import generate_scene3d
from geometry.shading import compile_shading_geometry
from geometry.pvfield import PVFieldPackingSession
from geometry.pvfield.packing import pack_field, validate_field_layout
from tests.unit.test_phase43_pvfield_packing import _roof_scene, _new_session, MODULE
from tests.unit.test_rb_fix_s1_geometry_integrity import Project
from tests.unit.test_rb_fix_s3_scene_commands import _send, _surface
from tests.unit.test_rb_fix_s11a_scene_edits import module_polygon

HOLE = [[2, 2], [4, 2], [4, 4], [2, 4]]
PLANE = dict(slope_deg=5, azimuth_deg=180, base_elevation_m=6.1,
             elevation_reference={"mode": "explicit_xy", "x_m": 0, "y_m": 0})


def test_01_plane_persists_z_identity_xy_and_staleness(tmp_path):
    p = Project(tmp_path); before = p.bundle(); snapshot=p.path.read_bytes()
    preview=_send(p,'edit_plane',[p.surface_id],PLANE,dry_run=True)
    assert preview.status_code==200 and preview.json()['conflicts']==[]
    assert p.path.read_bytes()==snapshot
    response=_send(p,'edit_plane',[p.surface_id],PLANE)
    assert response.status_code==200,response.text
    after=p.bundle();plane=SurfacePlane.from_surface(after['scene']['surfaces'][0])
    for old,m in zip(before['scene']['module_instances'],after['scene']['module_instances']):
        assert old['module_instance_id']==m['module_instance_id']
        for key in ('position_x_m','position_y_m'): assert old['transform'][key]==m['transform'][key]
        t=m['transform']; mounting=after['scene']['pv_fields'][0]['mounting_height_m']
        assert abs(t['position_z_m']-(plane.elevation_at(t['position_x_m'],t['position_y_m'])+mounting))<=1e-9
    readiness=p.client.get(p.url+'/execution-readiness').json()
    assert any(f['rule_id']=='SCENE_PV_FIELD_LAYOUT_STALE' for f in readiness['findings'])
    editor=SceneEditorSession(before['scene']);editor.edit_plane(p.surface_id,**PLANE)
    assert editor.undo_depth==1;editor.undo();assert editor.scene==before['scene']


@pytest.mark.parametrize('change',[{'slope_deg':90},{'slope_deg':-1},{'azimuth_deg':360},{'azimuth_deg':-1},
    {'base_elevation_m':10001},{'extra':1},{'elevation_reference':{'mode':'explicit_xy','x_m':50001,'y_m':0}},
    {'elevation_reference':{'mode':'boundary_centroid','x_m':0}}])
def test_01_plane_validation_no_write(tmp_path,change):
    p=Project(tmp_path);snapshot=p.path.read_bytes()
    r=_send(p,'edit_plane',[p.surface_id],{**PLANE,**change})
    assert r.status_code==422 and p.path.read_bytes()==snapshot


def test_02_plane_new_vertical_overlap_refused_without_options(tmp_path):
    p=Project(tmp_path);module=p.modules()[0];t=module['transform']
    r=p.client.post(p.url+'/obstacles/box',json={'name':'Above','origin_x_m':t['position_x_m']-.1,
        'origin_y_m':t['position_y_m']-.1,'width_m':.2,'depth_m':.2,'base_elevation_m':9,'height_m':1})
    assert r.status_code==200
    params={**PLANE,'base_elevation_m':9.2,'slope_deg':0}
    snapshot=p.path.read_bytes()
    preview=_send(p,'edit_plane',[p.surface_id],params,dry_run=True)
    assert preview.status_code==200 and preview.json()['conflicts']
    result=_send(p,'edit_plane',[p.surface_id],params)
    assert result.status_code==422 and 'options' not in result.json()['detail']
    assert p.path.read_bytes()==snapshot
    oid=p.bundle()['scene']['obstacles'][0]['obstacle_id']
    assert _send(p,'edit_plane',[oid],PLANE).status_code==422


def test_03_holes_rings_locks_validation_and_undo():
    e=SceneEditorSession(_roof_scene());before=e.scene
    e.add_hole('roof',vertices=HOLE);assert e.undo_depth==1
    for vertices in ([[0,2],[1,2],[1,3]],[[20,20],[21,20],[21,21]],[[3,3],[5,3],[5,5]],HOLE):
        saved=e.scene
        with pytest.raises(ValueError):e.add_hole('roof',vertices=vertices)
        assert e.scene==saved
    e.insert_vertex('roof',ring=1,edge_index=0,x_m=3,y_m=1.8)
    assert len(e.scene['surfaces'][0]['boundary_2d']['holes'][0])==5
    e.delete_vertex('roof',ring=1,vertex_index=1)
    e.move_vertex('roof',ring=1,vertex_index=0,target_x_m=2.1,target_y_m=2)
    e.move_edge('roof',ring=1,edge_index=2,dx_m=0,dy_m=.1)
    snapshot=e.scene
    with pytest.raises(ValueError):e.move_vertex('roof',ring=1,vertex_index=0,target_x_m=-1,target_y_m=2)
    assert e.scene==snapshot
    with pytest.raises(ValueError):e.move_edge('roof',edge_index=0,dx_m=0,dy_m=3)
    assert e.scene==snapshot
    e.remove_hole('roof',hole_index=0);assert e.scene['surfaces'][0]['boundary_2d']['holes']==[]
    e.undo();assert e.scene==snapshot
    locked=e.scene;locked['surfaces'][0]['locked']=True
    for kind,params in [('add_hole',{'vertices':HOLE}),('remove_hole',{'hole_index':0}),('edit_plane',PLANE)]:
        with pytest.raises(ValueError,match='locked'):getattr(SceneEditorSession(locked),kind)('roof',**params)
    first=SceneEditorSession(before);first.add_hole('roof',vertices=HOLE);first.undo();assert first.scene==before


@pytest.mark.parametrize('kind,params,expected',[
 ('move',{'dx_m':20,'dy_m':-1},[[22,1],[24,1],[24,3],[22,3]]),
 ('rotate',{'angle_deg':90,'origin':(0,0)},[[2,-2],[2,-4],[4,-4],[4,-2]]),
 ('scale',{'factor':2,'origin':(0,0)},[[4,4],[8,4],[8,8],[4,8]])])
def test_03_transforms_carry_holes_once_and_undo(kind,params,expected):
    e=SceneEditorSession(_roof_scene());e.add_hole('roof',vertices=HOLE);before=e.scene
    getattr(e,kind)(['roof'],**params)
    actual=e.scene['surfaces'][0]['boundary_2d']['holes'][0]
    for a,b in zip(actual,expected):assert a==pytest.approx(b,abs=1e-12)
    assert e.undo_depth==2;e.undo();assert e.scene==before


def test_04_packing_and_validator_independent_hole_oracle():
    e=SceneEditorSession(_roof_scene());e.add_hole('roof',vertices=HOLE)
    session=_new_session(e.scene,setback=.3);session.fill_area('field-1')
    scene=session.scene;hole=Polygon(HOLE)
    for m in scene['module_instances']:
        # The fixture has the known 1 x 2 module tilted 10 degrees.
        from geometry.pvfield import rectangle_polygon
        import math
        t=m['transform'];poly=Polygon(rectangle_polygon((t['position_x_m'],t['position_y_m']),1,2*math.cos(math.radians(10)),0))
        assert not poly.intersects(hole)
        assert poly.distance(hole)>=.3-1e-9
    assert validate_field_layout(scene,'field-1')['status']=='valid'
    broken=deepcopy(scene);broken['module_instances'][0]['transform'].update(position_x_m=3,position_y_m=3)
    report=validate_field_layout(broken,'field-1')
    assert any(c['code']=='module_outside_support_or_setback' and 'hole' in c['message'] for c in report['conflicts'])
    from jsonschema import Draft202012Validator
    root=Path(__file__).resolve().parents[2]
    Draft202012Validator(json.loads((root/'schemas/pv-field-conflict-report.schema.json').read_text())).validate(report)


def test_04_every_phase43_and_reference_parent_capture_is_identical(tmp_path):
    # Replay all parent fixtures independently; no dependency on ignored audit files.
    if reason := missing_commit('d600c81'):
        pytest.skip(reason)
    root=Path(__file__).resolve().parents[2]
    script=r"""
import json, subprocess, sys, types
from dataclasses import asdict
from pathlib import Path
import pytest
import geometry.pvfield.packing as packing
import geometry.pvfield.commands as commands
parent=types.ModuleType('geometry.pvfield._s11b_parent')
parent.__package__='geometry.pvfield'
sys.modules[parent.__name__]=parent
exec(compile(subprocess.check_output(['git','show','d600c81:geometry/pvfield/packing.py'],text=True),'parent-packing.py','exec'),parent.__dict__)
actual=packing.pack_field
records=[]
current=None
def compare(scene,field,definition):
    old=asdict(parent.pack_field(scene,field,definition))
    result=actual(scene,field,definition)
    assert json.dumps(old,sort_keys=True)==json.dumps(asdict(result),sort_keys=True),current
    records.append(current)
    return result
class Evidence:
    def pytest_runtest_setup(self,item):
        global current
        current=item.nodeid
    def pytest_sessionfinish(self,session,exitstatus):
        Path(sys.argv[1]).write_text(json.dumps(records))
packing.pack_field=commands.pack_field=compare
raise SystemExit(pytest.main(['-q','tests/unit/test_phase43_pvfield_packing.py','tests/unit/test_phase49c_reference_projects.py','tests/reference_projects'],plugins=[Evidence()]))
"""
    evidence=tmp_path/'packing.json'
    result=subprocess.run([sys.executable,'-c',script,str(evidence)],cwd=root,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
    records=json.loads(evidence.read_text())
    assert len(records)==65
    assert len({name for name in records if 'test_phase43_' in name})==11


def test_05_hosted_hole_preview_refill_and_strings_atomic(tmp_path):
    p=Project(tmp_path);p.service.create_strings(p.pid,string_length=6)
    before=p.bundle();snapshot=p.path.read_bytes()
    assert _send(p,'add_hole',[p.surface_id],{'vertices':HOLE}).status_code==422
    preview=_send(p,'add_hole',[p.surface_id],{'vertices':HOLE},dependent_fields='apply',dry_run=True)
    assert preview.status_code==200,preview.text
    field=preview.json()['dependent_fields'][0]
    assert field['module_count_after']<field['module_count_before'] and field['string_ids']
    assert p.path.read_bytes()==snapshot
    assert _send(p,'add_hole',[p.surface_id],{'vertices':HOLE},dependent_fields='apply').status_code==422
    saved=_send(p,'add_hole',[p.surface_id],{'vertices':HOLE},dependent_fields='apply',discard_dependent_strings=True)
    assert saved.status_code==200,saved.text
    for m in p.modules():assert not Polygon(module_polygon(p.bundle(),m)).intersects(Polygon(HOLE))
    assert {item['string_id'] for item in p.bundle()['electrical_design']['strings']} == {item['string_id'] for item in before['electrical_design']['strings']} - set(field['string_ids'])
    for kind,params in [('move_vertex',{'ring':1,'vertex_index':0,'target_x_m':2.1,'target_y_m':2}),
                        ('insert_vertex',{'ring':1,'edge_index':0,'x_m':3,'y_m':1.9}),
                        ('delete_vertex',{'ring':1,'vertex_index':0}),('move_edge',{'ring':1,'edge_index':0,'dx_m':0,'dy_m':.1}),
                        ('remove_hole',{'hole_index':0})]:
        preview=_send(p,kind,[p.surface_id],params,dependent_fields='apply',dry_run=True)
        assert preview.status_code==200 and preview.json()['dependent_fields'],preview.text


def test_06_legacy_module_over_hole_blocks_readiness_and_simulation(tmp_path):
    p=Project(tmp_path);p.executable();bundle=p.bundle()
    m=p.modules()[0];poly=Polygon(module_polygon(bundle,m));x,y=poly.centroid.coords[0]
    bundle['scene']['surfaces'][0]['boundary_2d']['holes']=[[[x-.1,y-.1],[x+.1,y-.1],[x+.1,y+.1],[x-.1,y+.1]]]
    p.service.store.save(bundle)
    response=p.client.get(p.url+'/execution-readiness');assert response.status_code==200
    r=response.json();findings=[f for f in r['findings'] if f['rule_id']=='SCENE_MODULE_OVER_HOLE']
    assert findings and all(f['severity']=='blocking_error' for f in findings) and not r['ready']
    assert p.client.post(p.url+'/simulate',json={}).status_code==422


def test_07_standard_receivers_hole_compiles_and_simulates_aggregate_keeps_error(tmp_path):
    p=Project(tmp_path);p.executable()
    r=_send(p,'add_hole',[p.surface_id],{'vertices':[[.01,.01],[.02,.01],[.02,.02],[.01,.02]]},dependent_fields='apply',discard_dependent_strings=True)
    assert r.status_code==200,r.text
    assert len(p.bundle()['scene']['module_instances']) == 18
    scene=p.bundle()['scene'];compiled=compile_shading_geometry(scene)
    assert not [f for f in compiled['findings'] if f['severity']=='error']
    assert generate_scene3d(scene)['surfaces'][0]['holes_3d']
    result=p.client.post(p.url+'/simulate',json={});assert result.status_code==200,result.text
    assert result.json()['status'] in {'completed','completed_with_warnings'}
    scene['surfaces'][0]['shading_receiver']=True
    assert any(f['code']=='surface_receiver_compile_failed' for f in compile_shading_geometry(scene)['findings'])


def test_08_actual_typescript_and_surface_plane_parity_at_every_vertex():
    import os
    import shutil
    root=Path(__file__).resolve().parents[2]
    node=os.environ.get('RAWIBUMI_PDF_NODE') or shutil.which('node')
    assert node, 'Node >=22 is required for the cross-language plane parity regression'
    script="""import {planeZ,uiPlaneToEngine} from './apps/web/src/geometry.ts';
const rings=[[[0,0],[8,0],[8,6],[0,6]],[[1,2],[8,3],[9,9],[-2,7]]];
const results=[];
for(const ring of rings)for(const poly of [ring,[...ring].reverse()]) {
 const planes=[{mode:'datum_tilt_azimuth',datum:[2,-3],z_m:7,tilt_deg:12,slopeAzimuth_deg:237}];
 for(let edgeIndex=0;edgeIndex<poly.length;edgeIndex++)for(const direction of ['up','down'])planes.push({mode:'edge_tilt',edgeIndex,zRef_m:8,tilt_deg:10,direction});
 for(const p of planes)results.push({poly,parameters:uiPlaneToEngine(poly,p),heights:poly.map(at=>planeZ(poly,p,at))});
}console.log(JSON.stringify(results));"""
    result=subprocess.run([node,'--experimental-strip-types','--input-type=module','-e',script],cwd=root,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    for case in json.loads(result.stdout):
        plane=SurfacePlane.from_surface({'surface_id':'parity','boundary_2d':{'vertices':case['poly']},**case['parameters']})
        for point,height in zip(case['poly'],case['heights']):assert abs(plane.elevation_at(*point)-height)<=1e-9


def test_09_http_hole_parameters_targets_and_bounds_are_atomic(tmp_path):
    p=Project(tmp_path);sid=_surface(p)['surface_id']
    p.service.add_box_obstacle(p.pid,name='Free',origin_x_m=30,origin_y_m=0,width_m=2,depth_m=2,base_elevation_m=0,height_m=1)
    oid=p.bundle()['scene']['obstacles'][0]['obstacle_id'];snapshot=p.path.read_bytes()
    for kind,ids,params in [('add_hole',[oid],{'vertices':HOLE}),('remove_hole',[oid],{'hole_index':0}),
      ('add_hole',[],{'vertices':HOLE}),('add_hole',[sid,p.surface_id],{'vertices':HOLE}),
      ('add_hole',[sid],{'vertices':[[20,1],[50001,1],[20,2]]}),('remove_hole',[sid],{'hole_index':True}),
      ('move_vertex',[sid],{'ring':1,'vertex_index':0,'target_x_m':20,'target_y_m':1}),
      ('add_hole',[sid],{'vertices':HOLE,'extra':1})]:
        response=_send(p,kind,ids,params);assert response.status_code==422,response.text
        assert p.path.read_bytes()==snapshot



def test_10_plane_on_keepout_remains_a_vertical_edit_without_removal_options(tmp_path):
    p=Project(tmp_path);bundle=p.bundle();e=SceneEditorSession(bundle['scene'])
    m=p.modules()[0];x=m['transform']['position_x_m'];y=m['transform']['position_y_m']
    e.draw_polygon(surface_id='legacy-zone',scene_object_id='obj-zone',name='Zone',surface_type='exclusion_area',
        vertices=[[x-.1,y-.1],[x+.1,y-.1],[x+.1,y+.1],[x-.1,y+.1]],base_elevation_m=0,usable_for_pv=False,geometry_source='user_override')
    bundle['scene']=e.scene;p.service.store.save(bundle);before=p.bundle()
    preview=_send(p,'edit_plane',['legacy-zone'],PLANE,dry_run=True)
    assert preview.status_code==200 and preview.json()['conflicts']==[] and 'options' not in preview.json()
    result=_send(p,'edit_plane',['legacy-zone'],PLANE)
    assert result.status_code==200,result.text
    assert p.bundle()['scene']['module_instances']==before['scene']['module_instances']
