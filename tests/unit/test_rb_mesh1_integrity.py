"""Independent physical-surface oracles and fail-closed new-kind readiness."""
from copy import deepcopy
import math
import pytest
from geometry.scene.physical import polygon_surface_distance,module_interiors_cross
from geometry.pvfield.scene_layout import validate_scene_layout
from geometry.scene.mesh import make_mesh_obstacle
from tests.unit.test_rb_mesh1_tables import create,table,definition
from apps.api.execution_readiness import scene_layout_readiness_findings


def mesh(points,faces=None):
    return make_mesh_obstacle(obstacle_id='mesh-1',scene_object_id='obj-mesh-1',name='Physical mesh',mesh={'vertices_m':points,'faces':faces or [list(range(len(points)))]},provenance={'source_id':'synthetic'})


def conflicts(scene):return validate_scene_layout(scene,{'module-r1':definition()})['conflicts']


@pytest.mark.parametrize('second,blocked',[
    ({'anchor_xyz_m':[0,0,3]},True),
    ({'anchor_xyz_m':[0,0,4]},False),
    ({'anchor_xyz_m':[2,0,3]},False),
    ({'anchor_xyz_m':[2,4,3]},False),
    ({'anchor_xyz_m':[1.5,0,3]},True),
    ({'anchor_xyz_m':[0,0,3],'tilt_deg':90.},True),
    ({'anchor_xyz_m':[0,0,5],'tilt_deg':90.},False),
])
def test_explicit_rectangles_allow_stack_contact_but_refuse_interiors(second,blocked):
    scene,_,_=create(tables=[table(table_id='first',anchor_xyz_m=[0,0,3],tilt_deg=0.),table(table_id='second',**{'tilt_deg':0.,**second})])
    result=conflicts(scene)
    assert bool([c for c in result if c['code']=='module_module_overlap']) is blocked
    assert not [c for c in result if c['code'].endswith('_unresolved')]


@pytest.mark.parametrize('z,clearance,code',[(3.,0.,'module_obstacle_overlap'),(3.+.5e-9,0.,'module_obstacle_overlap'),(4.,0.,None),(3.2,.3,'module_obstacle_clearance'),(3.4,.3,None)])
def test_mesh_contact_and_true_3d_clearance(z,clearance,code):
    scene,field,modules=create(tables=[table(anchor_xyz_m=[0,0,3],tilt_deg=0.)])
    scene['pv_fields'][0]['setback_configuration']={'obstacle_setback_m':clearance}
    scene['obstacles']=[mesh([[-2,-3,z],[2,-3,z],[2,3,z],[-2,3,z]])]
    found=conflicts(scene)
    assert [c['code'] for c in found]==([code] if code else [])
    if code:
        assert found[0]['other_id']=='mesh-1' and found[0]['face_index']==0
        assert found[0]['distance_m']==pytest.approx(abs(z-3),abs=1e-9)


def test_open_overhang_and_closed_surface_set_never_invent_solid_volume():
    scene,_,_=create(tables=[table(anchor_xyz_m=[0,0,3],tilt_deg=0.)])
    scene['obstacles']=[mesh([[-5,-5,10],[5,-5,10],[5,5,10],[-5,5,10]])]
    assert conflicts(scene)==[]
    vertices=[[-5,-5,0],[5,-5,0],[5,5,0],[-5,5,0],[-5,-5,10],[5,-5,10],[5,5,10],[-5,5,10]]
    scene['obstacles']=[mesh(vertices,[[0,1,2,3],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]])]
    assert conflicts(scene)==[]


def test_native_extrusion_is_solid_for_explicit_module():
    from geometry.scene import SceneEditorSession
    scene,_,_=create(tables=[table(anchor_xyz_m=[0,0,3],tilt_deg=0.)]);editor=SceneEditorSession(scene)
    editor.draw_box_obstacle(obstacle_id='native',scene_object_id='obj-native',name='Native box',origin_x_m=-5,origin_y_m=-5,width_m=10,depth_m=10,base_elevation_m=0,height_m=10)
    assert [c['code'] for c in conflicts(editor.scene)]==['module_obstacle_overlap']


@pytest.mark.parametrize('damage',['table_missing','definition_missing','bad_dimension','placement','mesh_missing','mesh_face','field_empty_modules'])
def test_damaged_new_entities_report_blocking_findings_instead_of_raising(damage):
    scene,_,_=create(tables=[table(anchor_xyz_m=[0,0,3],tilt_deg=0.)]);definitions={'module-r1':definition()}
    if damage=='table_missing':scene['pv_fields'][0]['tables']=[]
    elif damage=='definition_missing':definitions={}
    elif damage=='bad_dimension':scene['pv_fields'][0]['tables'][0]['plane_module_width_m']=99
    elif damage=='placement':scene['module_instances'][0]['transform']['position_z_m']+=1
    elif damage=='field_empty_modules':scene['module_instances']=[]
    else:
        scene['obstacles']=[mesh([[-5,-5,10],[5,-5,10],[5,5,10],[-5,5,10]])]
        if damage=='mesh_missing':del scene['obstacles'][0]['mesh']
        else:scene['obstacles'][0]['mesh']['faces'][0][0]=999
    findings=scene_layout_readiness_findings({'scene':scene,'pinned_components':{'modules':definitions}})
    assert any(f['rule_id']=='SCENE_LAYOUT_UNRESOLVED' and f['severity']=='blocking_error' for f in findings)


def test_minimum_distance_has_independent_plane_edge_corner_oracles():
    square=[[-1,-1,0],[1,-1,0],[1,1,0],[-1,1,0]]
    assert polygon_surface_distance(square,[[-.5,-.5,2],[.5,-.5,2],[0,.5,2]])==pytest.approx(2,abs=1e-12)
    assert polygon_surface_distance(square,[[2,2,0],[3,2,0],[2,3,0]])==pytest.approx(math.sqrt(2),abs=1e-12)
    assert polygon_surface_distance(square,[[0,0,-1],[0,0,1],[3,0,1]])==0
