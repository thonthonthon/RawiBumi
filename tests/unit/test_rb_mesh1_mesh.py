"""Synthetic independent geometric checks for opaque mesh surfaces."""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from geometry.scene.mesh import make_mesh_obstacle, resolve_mesh
from geometry.scene3d import generate_scene3d
from geometry.shading import compile_shading_geometry, calculate_direct_beam_shadow
from tests.unit.test_phase51_compiled_shading_geometry import _scene, _registry


def mesh(vertices=None, faces=None, **kw):
    return make_mesh_obstacle(obstacle_id='mesh-1',scene_object_id='obj-mesh-1',name='Synthetic mesh',
        mesh={'vertices_m':vertices if vertices is not None else [[0,0,1],[2,0,1],[2,2,1],[0,2,1]],'faces':faces if faces is not None else [[0,1,2,3]],**kw},provenance={'source_id':'synthetic'})


def scene_with(obstacle):
    scene=_scene();scene['obstacles']=[obstacle];scene['module_instances']=[];scene['pv_fields']=[]
    surface=scene['surfaces'][0];surface['boundary_2d']['vertices']=[[0,0],[4,0],[4,4],[0,4]];surface['base_elevation_m']=0.;surface['shading_receiver']=True
    return scene


def shade(obstacle,sun=(0,0,1)):
    compiled=compile_shading_geometry(scene_with(obstacle))
    assert not [f for f in compiled['findings'] if f['severity']=='error'],compiled['findings']
    result=calculate_direct_beam_shadow(compiled,receiver_id='receiver:surface:roof',sun_vector_xyz=sun,self_shading_enabled=True)
    return result['beam_shaded_fraction']


def test_open_face_is_two_sided_and_preserves_original_vertices():
    m=mesh();before=deepcopy(m);r=resolve_mesh(m)
    assert m==before and r['vertices_3d']==m['mesh']['vertices_m']
    assert r['topology']['components'][0]['topology_class']=='open_manifold_surface'
    assert shade(m)==pytest.approx(.25)
    m['mesh']['faces'][0].reverse()
    assert shade(m)==pytest.approx(.25)


def test_stepped_mesh_differs_from_max_height_footprint_by_analytic_area():
    # Sun x/z=1: height-1 slab [1,2] projects to [0,1]; height-2
    # slab [2,3] also projects to [0,1]. The max-height surrogate projects
    # the whole [1,3] footprint to [-1,1], losing half outside the receiver.
    # Use x/z=0.5 instead: true union [0.5,2] length1.5; surrogate [0,2] length2.
    m=mesh([[1,0,1],[2,0,1],[2,2,1],[1,2,1],[2,0,2],[3,0,2],[3,2,2],[2,2,2]],[[0,1,2,3],[4,5,6,7]])
    assert shade(m,(.5,0,1))==pytest.approx(3/16)
    surrogate=mesh([[1,0,2],[3,0,2],[3,2,2],[1,2,2]])
    assert shade(surrogate,(.5,0,1))==pytest.approx(4/16)
    assert shade(surrogate,(.5,0,1))-shade(m,(.5,0,1))==pytest.approx(1/16)


def test_raised_overhang_and_open_gap_are_not_extruded():
    slab=mesh([[0,0,2],[2,0,2],[2,2,2],[0,2,2]])
    assert shade(slab)==pytest.approx(.25)
    # An off-axis sun moves the slab projection away; a fabricated wall to ground
    # would still intercept rays near its base.
    assert shade(slab,(2,0,1))==0


def test_concave_polygon_triangulates_without_hull_or_reordering():
    m=mesh([[0,0,2],[3,0,2],[3,1,2],[1,1,2],[1,3,2],[0,3,2]],[[0,1,2,3,4,5]])
    r=resolve_mesh(m);assert len(r['triangles'])==4
    assert r['faces'][0]['projected_area_m2']==pytest.approx(5)
    assert r['faces'][0]['surface_area_m2']==pytest.approx(5)
    assert shade(m)==pytest.approx(5/16)
    assert set(i for t in r['triangles'] for i in t)==set(range(6))


def test_a1_slight_nonplanarity_retains_vertices_and_projected_area():
    m=mesh([[0,0,1],[2,0,1],[2,2,1.002],[0,2,1]])
    r=resolve_mesh(m);f=r['faces'][0]
    assert f['nonplanar_within_tolerance'] is True
    assert .00049<f['maximum_plane_deviation_m']<.00051
    assert r['vertices_3d']==m['mesh']['vertices_m']
    assert len(f['triangles'])==2
    assert f['surface_area_m2']>f['projected_area_m2']
    assert sorted({i for t in f['triangles'] for i in t})==[0,1,2,3]
    # Independent triangle area in the original world coordinates.
    import numpy as np
    area=sum(np.linalg.norm(np.cross(np.subtract(r['vertices_3d'][t[1]],r['vertices_3d'][t[0]]),np.subtract(r['vertices_3d'][t[2]],r['vertices_3d'][t[0]])))/2 for t in f['triangles'])
    assert f['surface_area_m2']==area


def test_a1_two_mm_deviation_refused_and_planar_face_unchanged():
    with pytest.raises(ValueError,match='mesh mesh-1 face 0.*exceeds'):
        mesh([[0,0,1],[2,0,1],[2,2,1.0081],[0,2,1]])
    f=resolve_mesh(mesh())['faces'][0]
    assert f['maximum_plane_deviation_m']==0
    assert f['nonplanar_within_tolerance'] is False
    assert f['surface_area_m2']==f['projected_area_m2']==4


@pytest.mark.parametrize('mutation,message',[
    (lambda p:p['vertices_m'][0].__setitem__(0,float('nan')),'finite'),
    (lambda p:p.__setitem__('faces',[[0,1,8]]),'in-range'),
    (lambda p:p.__setitem__('faces',[[0,1,1]]),'repeated'),
    (lambda p:p.__setitem__('faces',[[0,True,2]]),'in-range'),
    (lambda p:p.__setitem__('vertices_m',[[0,0,0],[1,0,0],[2,0,0],[3,0,0]]),'area'),
    (lambda p:p.__setitem__('faces',[[0,2,1,3]]),'area|simple'),
    (lambda p:p.__setitem__('faces',[]),'count'),
    (lambda p:p.__setitem__('transform',{'rotation_matrix':[[2,0,0],[0,1,0],[0,0,1]],'translation_m':[0,0,0]}),'rigid'),
    (lambda p:p.__setitem__('transform',{'rotation_matrix':[[-1,0,0],[0,1,0],[0,0,1]],'translation_m':[0,0,0]}),'rigid'),
    (lambda p:p.__setitem__('transform',{'rotation_matrix':[[1,0,0],[0,1,0],[0,0,1]],'translation_m':[50001,0,0]}),'bounds'),
])
def test_malformed_meshes_refuse_without_repair(mutation,message):
    p=deepcopy(mesh()['mesh']);mutation(p);before=deepcopy(p)
    with pytest.raises(ValueError,match=message):mesh(**p)
    # NaN equality is not meaningful, but serialization still captures the unchanged input.
    assert json.dumps(p,sort_keys=True)==json.dumps(before,sort_keys=True)


def test_transform_is_applied_once_and_content_changes_hash():
    m=mesh(transform={'rotation_matrix':[[0,-1,0],[1,0,0],[0,0,1]],'translation_m':[4,5,2]})
    r=resolve_mesh(m);assert r['vertices_3d'][0]==[4,5,3]
    assert r['vertices_3d'][1]==[4,7,3]
    first=compile_shading_geometry(scene_with(m))
    m['mesh']['vertices_m'].append([9,9,1])
    second=compile_shading_geometry(scene_with(m))
    assert first['geometry_payload_sha256']!=second['geometry_payload_sha256']


def test_source_generated_and_compiled_schemas_accept_mesh_without_footprint():
    scene=scene_with(mesh());generated=generate_scene3d(scene);compiled=compile_shading_geometry(scene)
    for path,value in [('geometry/scene/scene.schema.json',scene),('geometry/scene3d/generated-scene3d.schema.json',generated),('geometry/shading/compiled-shading-geometry.schema.json',compiled)]:
        Draft202012Validator(json.loads(Path(path).read_text()),registry=_registry()).validate(value)
    assert 'footprint' not in scene['obstacles'][0]
    assert generated['obstacles'][0]['mesh']['faces'][0]['nonplanar_within_tolerance'] is False


def test_closed_nonmanifold_and_disconnected_surface_classes():
    vertices=[[0,0,1],[2,0,1],[2,2,1],[0,2,1],[0,0,3],[2,0,3],[2,2,3],[0,2,3]]
    faces=[[3,2,1,0],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]
    r=resolve_mesh(mesh(vertices,faces))
    assert r['topology']['components'][0]['topology_class']=='closed_manifold'
    assert r['topology']['winding_consistent']
    m=mesh([[0,0,1],[1,0,1],[0,1,1],[0,0,2],[0,-1,1]],[[0,1,2],[1,0,3],[0,1,4]])
    assert resolve_mesh(m)['topology']['components'][0]['topology_class']=='nonmanifold_surface_set'
    vertices2=vertices+[[x+5,y,z] for x,y,z in vertices]
    faces2=faces+[[i+8 for i in f] for f in faces]
    assert resolve_mesh(mesh(vertices2,faces2))['topology']['component_count']==2


def test_collinear_corner_is_kept_in_triangulation():
    r=resolve_mesh(mesh([[0,0,1],[1,0,1],[2,0,1],[2,2,1],[0,2,1]],[[0,1,2,3,4]]))
    assert len(r['triangles'])==3
    assert set(i for t in r['triangles'] for i in t)==set(range(5))
    assert r['faces'][0]['projected_area_m2']==4
