"""Same-process exactness proof for the certified prepared broad phase."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import ast
import hashlib
import json
import math
from pathlib import Path
import random
import struct

import numpy as np
import pytest

from geometry.shading import (
    compile_shading_geometry, prepare_directional_receiver,
    calculate_prepared_direct_beam_shadow,
)
from geometry.shading.prepared import (
    _build_bound_state, _project_bound_vertices, _certify_convex,
)
from geometry.shading.beam import _project_to_receiver_plane, _to_uv, _dot, _normalize
from geometry.shading.snapshot import evaluate_beam_shading_snapshot
from geometry.shading.sky_snapshot import evaluate_sky_shading_snapshot
from geometry.shading.ground_snapshot import evaluate_ground_shading_snapshot
from geometry.scene.mesh import make_mesh_obstacle
from geometry.pvfield.explicit import create_explicit_field
from geometry.pvfield.models import ModuleFootprint
from apps.api.study import _phase5_configuration
from tests.unit.test_phase38e_canonical_simulation_run import _project_revision
from tests.unit.test_phase51_compiled_shading_geometry import _scene, MODULE
from engine.simulation.artifacts import canonical_json_bytes

REFERENCE_SHA256 = '20a84c1dbb83aee3a23551c2caf15e3f4046e702c7489fd88f6e0a76b848db25'


def exact_payload(actual, expected, *, label):
    """JSON equivalence plus raw binary64 comparison, including signed zero."""
    differences=[]
    def walk(a,b,path):
        if isinstance(a,float) and isinstance(b,float):
            if struct.pack('>d',a)!=struct.pack('>d',b):
                differences.append({'path':path,'expected':b.hex(),'actual':a.hex(),'absolute':abs(a-b)})
        elif isinstance(a,dict) and isinstance(b,dict):
            assert set(a)==set(b),(label,path,set(a)^set(b))
            for k in a:walk(a[k],b[k],path+'.'+k)
        elif isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)):
            assert len(a)==len(b),(label,path)
            for i,(x,y) in enumerate(zip(a,b)):walk(x,y,f'{path}[{i}]')
        else:assert a==b,(label,path,a,b)
    walk(actual,expected,'result')
    assert not differences, {'case':label,'maximum_absolute_difference':max(d['absolute'] for d in differences),'differences':differences[:10]}
    assert canonical_json_bytes(actual)==canonical_json_bytes(expected),label


def forced_maps(compiled):
    reference={};fast={}
    for r in compiled['receivers']:
        if not r['enabled']:continue
        rid=r['receiver_id'];p=prepare_directional_receiver(compiled,receiver_id=rid,self_shading_enabled=True)
        reference[rid]=replace(p,_bounds=None)
        fast[rid]=replace(p,_bounds=_build_bound_state(p))
    return reference,fast


def synthetic_scene(seed):
    rng=random.Random(seed)
    scene=_scene()
    field=scene['pv_fields'][0]
    tilt=rng.uniform(0,60);az=rng.uniform(0,360)
    field.update(tilt_deg=tilt,azimuth_deg=az,mounting_height_m=5.)
    field['module_footprint']=ModuleFootprint.from_definition(MODULE,field['orientation'],tilt).to_mapping()
    for i,m in enumerate(scene['module_instances']):
        m['transform'].update(position_x_m=2.+(i%3)*3,position_y_m=2.+(i//3)*4,position_z_m=13.,rotation_z_deg=az)
    if seed%3!=0:
        if seed%3==1:scene['pv_fields']=[];scene['module_instances']=[]
        tables=[]
        for i in range(2):
            tables.append({'table_id':f'random-table-{i}','anchor_xyz_m':[18.+i*4,rng.uniform(1,10),rng.uniform(10,14)],'anchor_convention':'center','tilt_deg':rng.uniform(0,70),'azimuth_deg':rng.uniform(0,360),'module_definition_revision_id':MODULE['revision_id'],'modules_across':1,'modules_up':1,'module_orientation':'portrait' if i==0 else 'landscape','module_gap_across_m':0.,'module_gap_up_m':0.})
        new,modules=create_explicit_field(scene,{MODULE['revision_id']:MODULE},pv_field_id='random-explicit',name='Synthetic random tables',tables=tables,provenance={'source_id':'synthetic'})
        scene['pv_fields'].append(new);scene['module_instances'].extend(modules)
    for i in range(seed%3+1):
        x,y,z=rng.uniform(0,20),rng.uniform(0,10),rng.uniform(8,12)
        w,h,height=rng.uniform(.3,3),rng.uniform(.3,3),rng.uniform(.5,3)
        vertices=[[x,y,z],[x+w,y,z],[x+w,y+h,z],[x,y+h,z],[x,y,z+height],[x+w,y,z+height],[x+w,y+h,z+height],[x,y+h,z+height]]
        faces=[[3,2,1,0],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]
        if seed%4==1:faces=faces[1:3] # Legal open surface set.
        if seed%4==2:vertices[6][2]+=.0005
        obstacle=make_mesh_obstacle(obstacle_id=f'random-mesh-{i}',scene_object_id=f'obj-random-mesh-{i}',name='Synthetic mesh',mesh={'vertices_m':vertices,'faces':faces},provenance={'source_id':'synthetic'})
        scene['obstacles'].append(obstacle)
    return scene


def configuration():
    c=_phase5_configuration(_project_revision(),configuration_id='mesh1-exact-proof')['shading_configuration']
    c['self_shading_enabled']=True
    c['receiver_granularity']='mixed'
    return c


def test_reference_evaluator_body_is_retained_verbatim():
    path=Path('geometry/shading/prepared.py');source=path.read_text()
    fn=next(n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.FunctionDef) and n.name=='_evaluate_front_source_reference')
    text=ast.get_source_segment(source,fn).replace('def _evaluate_front_source_reference(', 'def _evaluate_front_source(',1)
    substitution = """    fallback_evidence = {}
    if shadow_polygons:
        unioned, fallback_evidence = _shadow_union(
            shadow_polygons, prepared.receiver_polygon_uv, receiver_id=prepared.receiver_id,
            occluder_ids=contributing, source=source_direction,
        )"""
    assert text.count(substitution) == 1
    assert text.count("        **fallback_evidence,\n") == 1
    text = text.replace(substitution, "    if shadow_polygons:\n        unioned = unary_union(shadow_polygons)")
    text = text.replace("        **fallback_evidence,\n", "")
    assert hashlib.sha256(text.encode()).hexdigest()==REFERENCE_SHA256


@pytest.mark.parametrize('seed',range(64))
def test_seeded_same_process_factor_and_projected_coordinate_bits(seed):
    compiled=compile_shading_geometry(synthetic_scene(seed))
    assert not [f for f in compiled['findings'] if f['severity']=='error'],compiled['findings']
    reference,fast=forced_maps(compiled);config=configuration();rng=random.Random(9173+seed)
    directions=[(rng.uniform(-1,1),rng.uniform(-1,1),rng.uniform(.01,1)) for _ in range(3)]
    directions += [(0,0,-1),(.3,-.7,1e-11)]
    for raw in directions:
        direction=_normalize(tuple(raw),name='source')
        for rid,p in fast.items():
            dot=_dot(p.normal_xyz,direction)
            if abs(dot)>p.tolerances.parallel_dot:
                uv=_project_bound_vertices(p,direction,dot)
                for at,index in enumerate(p._bounds.indices):
                    face=p.prepared_faces[index]
                    for j,point in enumerate(face.vertices_3d):
                        projected=_project_to_receiver_plane(point,receiver_origin=p.origin_xyz,receiver_normal=p.normal_xyz,sun_vector=direction,receiver_sun_dot=dot)
                        old=_to_uv(projected,origin=p.origin_xyz,u_axis=p.u_axis_xyz,v_axis=p.v_axis_xyz)
                        exact_payload(uv[at,j].tolist(),list(old),label=f'seed={seed}, receiver={rid}, projection={index}:{j}')
        kwargs=dict(shading_configuration=config,receiver_ids=list(reference),sun_vector_xyz=raw)
        actual=evaluate_beam_shading_snapshot(compiled,prepared_queries=fast,**kwargs).shading_result
        expected=evaluate_beam_shading_snapshot(compiled,prepared_queries=reference,**kwargs).shading_result
        exact_payload(actual,expected,label=f'seed={seed}, sun={raw}')
    for name,fn in (('sky+horizon',evaluate_sky_shading_snapshot),('ground',evaluate_ground_shading_snapshot)):
        kwargs=dict(shading_configuration=config,receiver_ids=list(reference))
        actual=fn(compiled,prepared_queries=fast,**kwargs).shading_result
        expected=fn(compiled,prepared_queries=reference,**kwargs).shading_result
        exact_payload(actual,expected,label=f'seed={seed}, channel={name}')


def test_interval_certificate_agrees_with_exact_rational_turns():
    rng=random.Random(70831)
    polygons=[]
    for i in range(256):
        scale=10.**rng.uniform(-150,150)
        x,y=rng.uniform(-2,2)*scale,rng.uniform(-2,2)*scale
        w,h=rng.uniform(.1,3)*scale,rng.uniform(.1,3)*scale
        polygons.append([[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
    polygons += [[[0.,0.],[1.,1.],[0.,1.],[1.,0.]], [[0.,0.],[1.,0.],[2.,0.],[0.,1.]], [[1e308,1e308],[-1e308,1e308],[-1e308,-1e308],[1e308,-1e308]]]
    certificates=_certify_convex(np.asarray(polygons,dtype=np.float64))
    for points,certified in zip(polygons,certificates):
        if not certified:continue
        exact=[(Fraction.from_float(p[0]),Fraction.from_float(p[1])) for p in points]
        signs=[]
        for i,a in enumerate(exact):
            b,c=exact[(i+1)%4],exact[(i+2)%4]
            signs.append((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
        assert all(v>0 for v in signs) or all(v<0 for v in signs)
    assert not any(certificates[-3:])


def shape_oracles():
    from tests.unit.test_rb_mesh1_mesh import mesh,scene_with
    cases={}
    cases['stepped']=scene_with(mesh([[1,0,1],[2,0,1],[2,2,1],[1,2,1],[2,0,2],[3,0,2],[3,2,2],[2,2,2]],[[0,1,2,3],[4,5,6,7],[1,4,7,2]]))
    cases['overhang']=scene_with(mesh([[0,0,2],[2,0,2],[2,2,2],[0,2,2]]))
    cases['concave']=scene_with(mesh([[0,0,2],[3,0,2],[3,1,2],[1,1,2],[1,3,2],[0,3,2]],[[0,1,2,3,4,5]]))
    cases['nonplanar']=scene_with(mesh([[0,0,1],[2,0,1],[2,2,1.002],[0,2,1]]))
    return cases


@pytest.mark.parametrize('name',list(shape_oracles()))
def test_mesh1_oracle_shapes_have_identical_full_channels(name):
    compiled=compile_shading_geometry(shape_oracles()[name]);reference,fast=forced_maps(compiled);config=configuration()
    for source in ((0,0,1),(.5,0,1),(2,0,1),(-.2,.3,.001)):
        kwargs=dict(shading_configuration=config,receiver_ids=list(reference),sun_vector_xyz=source)
        exact_payload(evaluate_beam_shading_snapshot(compiled,prepared_queries=fast,**kwargs).shading_result,evaluate_beam_shading_snapshot(compiled,prepared_queries=reference,**kwargs).shading_result,label=f'{name}:beam:{source}')
    for channel,fn in (('sky+horizon',evaluate_sky_shading_snapshot),('ground',evaluate_ground_shading_snapshot)):
        kwargs=dict(shading_configuration=config,receiver_ids=list(reference))
        exact_payload(fn(compiled,prepared_queries=fast,**kwargs).shading_result,fn(compiled,prepared_queries=reference,**kwargs).shading_result,label=f'{name}:{channel}')


def test_row_shadow_matches_independent_parallel_plane_geometry():
    from tests.unit.test_rb_mesh1_tables import definition,table
    scene=_scene();scene['surfaces']=[];scene['obstacles']=[];scene['pv_fields']=[];scene['module_instances']=[]
    tables=[table(table_id='front',anchor_xyz_m=[0,0,2],tilt_deg=30.),table(table_id='rear',anchor_xyz_m=[0,5,2],tilt_deg=30.)]
    f,modules=create_explicit_field(scene,{'module-r1':definition()},pv_field_id='row-oracle',name='Row oracle',tables=tables,provenance={'source_id':'synthetic'})
    scene['pv_fields']=[f];scene['module_instances']=modules
    compiled=compile_shading_geometry(scene);reference,fast=forced_maps(compiled)
    module=next(m for m in modules if m['table_id']=='rear');rid='receiver:module:'+module['module_instance_id']
    elevation=math.radians(10);tilt=math.radians(30)
    # Equal parallel planes: projected centre shift along upslope is
    # -spacing*sin(elevation)/sin(tilt+elevation); widths coincide exactly.
    expected=1-5*math.sin(elevation)/math.sin(tilt+elevation)/4
    sun=(0,-math.cos(elevation),math.sin(elevation))
    actual=calculate_prepared_direct_beam_shadow(fast[rid],sun_vector_xyz=sun)
    old=calculate_prepared_direct_beam_shadow(reference[rid],sun_vector_xyz=sun)
    exact_payload(actual,old,label='row-shadow')
    assert actual['beam_shaded_fraction']==pytest.approx(expected,abs=1e-12)


def _box_sky_ray_reference(width,height,azimuth_sectors,elevation_bands):
    """Independent midpoint ray/slab integration for a known opaque AABB.

    Flat receiver z=1, box x=[3,5], y=[-20,20], z=[0,8].
    Receiver spatial quadrature is independent of the product's polygon solver.
    """
    xs=(np.arange(width)+.5)/width-0.5
    ys=2*((np.arange(height)+.5)/height-0.5)
    positions=np.asarray([(x,y,1.) for x in xs for y in ys])
    az=(np.arange(azimuth_sectors)+.5)*2*math.pi/azimuth_sectors
    mu=(np.arange(elevation_bands)+.5)/elevation_bands
    weighted=0.
    for cosine in mu:
        horizontal=math.sqrt(1-cosine*cosine)
        directions=np.stack((horizontal*np.sin(az),horizontal*np.cos(az),np.full_like(az,cosine)),axis=1)
        with np.errstate(divide='ignore',invalid='ignore'):
            low=(np.asarray([3.,-20.,0.])-positions[:,None,:])/directions[None,:,:]
            high=(np.asarray([5.,20.,8.])-positions[:,None,:])/directions[None,:,:]
            enter=np.max(np.minimum(low,high),axis=2)
            leave=np.min(np.maximum(low,high),axis=2)
        blocked=(leave>=np.maximum(enter,0)) & (leave>0)
        weighted+=cosine*(1-float(np.mean(blocked)))
    return weighted/float(np.sum(mu))


def test_closed_mesh_box_sky_has_independent_ray_reference_and_exact_acceleration():
    from geometry.shading import calculate_sky_visibility,SkyDomeResolution
    from tests.unit.test_rb_mesh1_tables import definition,table
    scene=_scene();scene['surfaces']=[];scene['obstacles']=[];scene['pv_fields']=[];scene['module_instances']=[]
    d=definition();d['mechanical'].update(width_m=1.,height_m=2.)
    f,modules=create_explicit_field(scene,{'module-r1':d},pv_field_id='sky-oracle',name='Sky oracle',tables=[table(anchor_xyz_m=[0,0,1],tilt_deg=0.)],provenance={'source_id':'synthetic'})
    scene['pv_fields']=[f];scene['module_instances']=modules
    vertices=[[3,-20,0],[5,-20,0],[5,20,0],[3,20,0],[3,-20,8],[5,-20,8],[5,20,8],[3,20,8]]
    scene['obstacles']=[make_mesh_obstacle(obstacle_id='sky-box',scene_object_id='sky-box-object',name='Sky box',mesh={'vertices_m':vertices,'faces':[[3,2,1,0],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]},provenance={'source_id':'synthetic'})]
    compiled=compile_shading_geometry(scene);reference,fast=forced_maps(compiled);rid=next(iter(reference))
    low=_box_sky_ray_reference(8,16,360,90)
    high=_box_sky_ray_reference(16,32,720,180)
    assert abs(high-low)<=.001,{'coarse_ray':low,'fine_ray':high}
    from geometry.scene import SceneEditorSession
    native_scene=deepcopy(scene);native_scene['obstacles']=[]
    editor=SceneEditorSession(native_scene)
    editor.draw_box_obstacle(obstacle_id='sky-box',scene_object_id='sky-box-object',name='Sky box',origin_x_m=3.,origin_y_m=-20.,width_m=2.,depth_m=40.,base_elevation_m=0.,height_m=8.)
    native_compiled=compile_shading_geometry(editor.scene)
    _,native_fast=forced_maps(native_compiled)
    for sectors,bands in ((12,3),(72,18)):
        resolution=SkyDomeResolution(sectors,bands,sectors,1,10.)
        kwargs=dict(receiver_id=rid,self_shading_enabled=True,resolution=resolution)
        new=calculate_sky_visibility(compiled,prepared_query=fast[rid],**kwargs)
        old=calculate_sky_visibility(compiled,prepared_query=reference[rid],**kwargs)
        exact_payload(new,old,label=f'box-sky-{sectors}x{bands}')
        native=calculate_sky_visibility(native_compiled,prepared_query=native_fast[rid],**kwargs)
        for factor in ('sky_visibility_factor','horizon_visibility_factor'):
            exact_payload(new[factor],native[factor],label=f'mesh-native-box-{sectors}x{bands}:{factor}')
        error=abs(new['sky_visibility_factor']-high)
        if (sectors,bands)==(72,18):
            assert error<=.01
        else:
            # A4: existing coarse quadrature accuracy is measured, not gated.
            print(json.dumps({'measurement':'existing_12x3_sky_quadrature_accuracy','product':new['sky_visibility_factor'],'reference':float(high),'absolute_error':float(error)}))
