"""Invented geometry only; these are not reference-file excerpts."""
from copy import deepcopy
import math

import numpy as np
import pytest

from geometry.pvfield.explicit import table_rectangle
from validation.pvsyst_benchmark.headline_scene import (
    anchor_name, excluded_face_evidence, mesh_operation, build_geometry,
    structural_terminators,
)
from validation.pvsyst_benchmark.scene import Mesh
from validation.pvsyst_benchmark.source import Node, SourceError, read_objects
from validation.pvsyst_benchmark.project import extract_project
from tests.fixtures.val1.synthetic import scene_bytes, project_sources


@pytest.mark.parametrize("code,x,y", [(1,0,0),(2,.5,0),(3,1,0),(5,.5,1),(7,.5,.5)])
@pytest.mark.parametrize("opposite", [False, True])
def test_all_observed_anchors_against_hand_rectangle(code, x, y, opposite):
    if opposite:
        x = 1-x
    tilt = math.radians(30)
    points = table_rectangle({"anchor_convention": anchor_name(code, opposite_view=opposite),
                              "anchor_xyz_m": [5,7,2], "azimuth_deg":180., "tilt_deg":30.,
                              "rectangle":{"width_m":4.,"height_m":2.}})
    expected = [[5+(a-x)*4,7+(b-y)*2*math.cos(tilt),2+(b-y)*2*math.sin(tilt)]
                for a,b in [(0,1),(1,1),(1,0),(0,0)]]
    np.testing.assert_allclose(points, expected, rtol=0, atol=1e-14)


@pytest.mark.parametrize("code", [4,6,0,9,True,"1"])
def test_unproved_anchor_is_refused(code):
    with pytest.raises(SourceError):anchor_name(code)


def thin_mesh():
    # A fictional bow-tie loop near a straight line; three retained triangles.
    vertices=[[0,0,0],[20,.0005,0],[20,0,0],[0,.0005,0], [0,0,2],[1,0,2],[0,1,2]]
    faces=[[4,5,6],[4,6,5],[5,4,6],[0,1,2,3]]
    n=Node("pvShdGenObject","synthetic",1,records=[("NoObjCreated","154"),
           ("DOrigine","3,4,5"),("DInclin","0"),("DAzimut","0")]+
           [(f"Point_{i}",",".join(map(str,p))) for i,p in enumerate(vertices,1)])
    return n,Mesh("154",np.asarray(vertices,float),faces),vertices


def test_exact_exception_preserves_every_vertex_and_other_face_with_bounds():
    n,m,vertices=thin_mesh();original=deepcopy(m.faces)
    op,receipt=mesh_operation(n,m,label="P3")
    assert op["mesh"]["vertices_m"]==vertices and op["mesh"]["faces"]==original[:3]
    assert m.faces==original
    assert op["mesh"]["transform"]=={"rotation_matrix":np.eye(3).tolist(),"translation_m":[3.,4.,5.]}
    evidence=receipt["omissions"][0]
    assert evidence["maximum_line_offset_m"]<=.001
    assert evidence["absolute_signed_area_m2"]<.1
    assert evidence["shadow_bound"]["conservative_convex_hull_envelope_m2"]>=evidence["shadow_bound"]["source_signed_area_estimate_m2"]
    assert evidence["shadow_bound"]["minimum_solar_elevation_deg"]==7.


@pytest.mark.parametrize("identity",[("P2","154",3),("P3","155",3),("P3","154",2)])
def test_no_generic_face_filter(identity):
    _,m,v=thin_mesh()
    with pytest.raises(SourceError):excluded_face_evidence(*identity,v,m.faces[3])


def test_exception_rejects_valid_or_noncollinear_or_large_face():
    for v in ([[0,0,0],[20,0,0],[20,.0005,0],[0,.0005,0]],
              [[0,0,0],[20,.01,0],[20,0,0],[0,.01,0]],
              [[0,0,0],[1000,.0009,0],[1000,0,0],[0,.0001,0]]):
        with pytest.raises(SourceError):excluded_face_evidence("P3","154",3,v,[0,1,2,3])


@pytest.mark.parametrize("angle", ["DInclin","DAzimut"])
def test_unproved_mesh_rotation_refused(angle):
    n,m,_=thin_mesh();n.records=[(k,"1" if k==angle else v) for k,v in n.records]
    with pytest.raises(SourceError,match="identity"):mesh_operation(n,m,label="P3")


def source_plan(label):
    vc,prj=project_sources()
    return extract_project(read_objects(vc),read_objects(prj),label=label)


def test_rectangle_policy_counts_and_unknown_objects():
    definition={"revision_id":"synthetic-r1","mechanical":{"width_m":1.,"height_m":1.}}
    source=read_objects(scene_bytes())
    for label,rectangle in [("P2",True),("P3",False)]:
        ops,facts=build_geometry(source,source_plan(label),{"invented.pan":definition})
        assert facts["counts"]["counts_match"] and facts["counts"]["orientations_match"]
        tables=[t for op in ops if op["operation_type"]=="create_explicit_field" for t in op["tables"]]
        assert len(tables)==2 and all(("rectangle" in t)==rectangle for t in tables)
    bad=deepcopy(source);bad.children.append(Node("futureSolid","unknown",99))
    with pytest.raises(SourceError,match="unmapped"):build_geometry(bad,source_plan("P2"),{"invented.pan":definition})
    plan=source_plan("P2");plan.subarrays[0]["module_count"]+=1
    with pytest.raises(SourceError,match="reconcile"):build_geometry(source,plan,{"invented.pan":definition})


def test_typed_closures_require_exact_known_matching_declaration_and_count():
    source=read_objects(scene_bytes())
    source.records.extend([("ListeObjets, list of","3 TShdObject"),
                           ("__unparsed_structure__","End of ListeObjets")])
    mesh=next(source.walk("pvShdGenObject"))
    mesh.records.extend([("Sommets, TPoly3D","8 Point3D"),
                         ("__unparsed_structure__","End of TPoly3D")])
    assert len(structural_terminators(source))==2
    definition={"revision_id":"synthetic-r1","mechanical":{"width_m":1.,"height_m":1.}}
    assert len(build_geometry(source,source_plan("P2"),{"invented.pan":definition})[1]["verified_structural_terminators"])==2
    for records in [[("__unparsed_structure__","End of futureGeometry")],
                    [("__unparsed_structure__","End of TPoly3D")],
                    [("Sommets, TPoly3D","7 Point3D"),("__unparsed_structure__","End of TPoly3D")]]:
        bad=deepcopy(source);node=next(bad.walk("pvShdGenObject"));node.records=[(k,v) for k,v in node.records if k not in {"Sommets, TPoly3D","__unparsed_structure__"}]+records
        with pytest.raises(SourceError):structural_terminators(bad)
