"""Exact finite polygon-surface integrity for the new MESH1 object kinds.

Meshes are two-sided surface sets, not inferred solids. Native extrusions keep
an explicit containment check. Legacy-only layout policy lives in scene_layout.
"""
from __future__ import annotations

import math
import numpy as np
from shapely.geometry import Polygon, Point, box
from shapely import STRtree

CONTACT_M = 1e-9
OVERLAP_M2 = 1e-6


def _basis(points):
    p=np.asarray(points,dtype=float);u=p[1]-p[0];u=u/np.linalg.norm(u)
    n=np.cross(p[1]-p[0],p[2]-p[0]);n=n/np.linalg.norm(n)
    return p[0],u,np.cross(n,u),n


def _uv(point,basis):
    origin,u,v,_=basis;delta=np.asarray(point)-origin
    return (float(np.dot(delta,u)),float(np.dot(delta,v)))


def _segment_distance(a,b,c,d):
    a,b,c,d=(np.asarray(p,dtype=float) for p in (a,b,c,d))
    u,v,w=b-a,d-c,a-c
    aa,bb,cc,dd,ee=float(u@u),float(u@v),float(v@v),float(u@w),float(v@w)
    if aa==0:return float(np.linalg.norm(a-(c+np.clip(ee/cc,0,1)*v))) if cc else float(np.linalg.norm(a-c))
    if cc==0:return float(np.linalg.norm(c-(a+np.clip(-dd/aa,0,1)*u)))
    denominator=aa*cc-bb*bb
    s=float(np.clip((bb*ee-cc*dd)/denominator,0,1)) if denominator>0 else 0.
    t=(bb*s+ee)/cc
    if t<0:t=0.;s=float(np.clip(-dd/aa,0,1))
    elif t>1:t=1.;s=float(np.clip((bb-dd)/aa,0,1))
    return float(np.linalg.norm(w+s*u-t*v))


def _point_triangle_distance(point,triangle):
    p=np.asarray(point,dtype=float);a,b,c=np.asarray(triangle,dtype=float)
    ab,ac,ap=b-a,c-a,p-a;d1,d2=float(ab@ap),float(ac@ap)
    if d1<=0 and d2<=0:return float(np.linalg.norm(ap))
    bp=p-b;d3,d4=float(ab@bp),float(ac@bp)
    if d3>=0 and d4<=d3:return float(np.linalg.norm(bp))
    vc=d1*d4-d3*d2
    if vc<=0 and d1>=0 and d3<=0:return float(np.linalg.norm(p-(a+(d1/(d1-d3))*ab)))
    cp=p-c;d5,d6=float(ab@cp),float(ac@cp)
    if d6>=0 and d5<=d6:return float(np.linalg.norm(cp))
    vb=d5*d2-d1*d6
    if vb<=0 and d2>=0 and d6<=0:return float(np.linalg.norm(p-(a+(d2/(d2-d6))*ac)))
    va=d3*d6-d5*d4
    if va<=0 and d4-d3>=0 and d5-d6>=0:return float(np.linalg.norm(p-(b+((d4-d3)/((d4-d3)+(d5-d6)))*(c-b))))
    denominator=va+vb+vc
    if denominator==0:
        return min(_segment_distance(p,p,x,y) for x,y in zip((a,b,c),(b,c,a)))
    return float(np.linalg.norm(p-(a+ab*(vb/denominator)+ac*(vc/denominator))))


def _edges(points):
    return zip(points,points[1:]+points[:1])


def _plane_hits(first,second):
    basis=_basis(second);origin,_,_,normal=basis;shape=Polygon([_uv(p,basis) for p in second]);hits=[]
    for a,b in _edges(first):
        da=float(np.dot(np.asarray(a)-origin,normal));db=float(np.dot(np.asarray(b)-origin,normal))
        points=[]
        if abs(da)<=CONTACT_M:points.append(a)
        if da*db<0:points.append((np.asarray(a)+(np.asarray(b)-a)*(da/(da-db))).tolist())
        for point in points:
            if shape.covers(Point(_uv(point,basis))):hits.append(point)
    return hits


def polygon_surface_distance(first,second):
    """Minimum Euclidean distance between planar convex polygons."""
    if _plane_hits(first,second) or _plane_hits(second,first):return 0.
    triangles=lambda p:[[p[0],p[i],p[i+1]] for i in range(1,len(p)-1)]
    distance=min(_segment_distance(a,b,c,d) for a,b in _edges(first) for c,d in _edges(second))
    for p in first:
        distance=min(distance,*( _point_triangle_distance(p,t) for t in triangles(second)))
    for p in second:
        distance=min(distance,*( _point_triangle_distance(p,t) for t in triangles(first)))
    return distance


def module_interiors_cross(first,second):
    """Allow pure module edge/corner contact, including crossing plane edges."""
    basis=_basis(first);origin,_,_,normal=basis
    if max(abs(float(np.dot(np.asarray(p)-origin,normal))) for p in second)<=CONTACT_M:
        return Polygon([_uv(p,basis) for p in first]).intersection(Polygon([_uv(p,basis) for p in second])).area>OVERLAP_M2
    hits=_plane_hits(first,second)+_plane_hits(second,first)
    other=_basis(second)
    for a in hits:
        for b in hits:
            if math.dist(a,b)<=CONTACT_M:continue
            middle=(np.asarray(a)+b)/2
            if (Polygon([_uv(p,basis) for p in first]).contains(Point(_uv(middle,basis)))
                    and Polygon([_uv(p,other) for p in second]).contains(Point(_uv(middle,other)))):return True
    return False


def module_descriptor(module,field,definition,surfaces):
    from geometry.pvfield.explicit import is_explicit,explicit_module_geometry
    if is_explicit(field):return explicit_module_geometry(module,field,surfaces)[0]
    from geometry.pvfield.models import ModuleFootprint
    from geometry.scene3d.height import module_corners
    footprint=ModuleFootprint.from_definition(definition,field['orientation'],field['tilt_deg'])
    transform=module['transform'];centre=tuple(float(transform[k]) for k in ('position_x_m','position_y_m','position_z_m'))
    azimuth=float(transform.get('rotation_z_deg',field['azimuth_deg']))
    corners=module_corners(centre,footprint.packed_width_m,footprint.packed_height_m,azimuth,float(field['tilt_deg']))
    return {'corners_3d':[list(p) for p in corners],'support_surface_id':field.get('support_surface_id')}


def validate_new_scene_geometry(scene,definitions):
    from geometry.pvfield.explicit import is_explicit,create_explicit_field
    from geometry.scene.mesh import resolve_mesh,triangulate_face
    from geometry.scene3d.generator import _obstacle_geometry
    from geometry.shading.compiler import _obstacle_faces
    fields={f['pv_field_id']:f for f in scene.get('pv_fields',[])};conflicts=[];invalid_fields=set()
    def record(code,module=None,other='',reason=None,**extra):
        conflicts.append({'code':code,'module_instance_id':module['module_instance_id'] if module else None,'other_id':str(other),'pv_field_id':module['pv_field_id'] if module else extra.pop('pv_field_id',None),'other_pv_field_id':extra.pop('other_pv_field_id',None),**({'reason':reason} if reason else {}),**extra})
    table_keys={'table_id','anchor_xyz_m','anchor_convention','tilt_deg','azimuth_deg','module_definition_revision_id','modules_across','modules_up','module_orientation','module_gap_across_m','module_gap_up_m','rectangle','support_surface_id'}
    for field in fields.values():
        if not is_explicit(field):continue
        try:
            normalized,expected=create_explicit_field(scene,definitions,pv_field_id=field['pv_field_id'],name=field['name'],tables=[{k:v for k,v in t.items() if k in table_keys} for t in field['tables']],provenance=field['provenance'])
            canonical={t['table_id']:t for t in normalized['tables']}
            if any(t!=canonical[t['table_id']] for t in field['tables']):raise ValueError('stored table dimensions or mount disagree with its pinned definition')
            actual=[m for m in scene.get('module_instances',[]) if m.get('pv_field_id')==field['pv_field_id']]
            if {m['module_instance_id'] for m in expected}!={m['module_instance_id'] for m in actual}:raise ValueError('stored module identities do not match explicit tables')
        except (KeyError,ValueError,TypeError,AttributeError,OverflowError,IndexError) as exc:
            invalid_fields.add(field['pv_field_id']);record('field_unresolved',other=field['pv_field_id'],reason=str(exc),pv_field_id=field['pv_field_id'])
    modules=[];rectangles=[];bounds=[];explicit=[];clearances=[]
    for module in sorted(scene.get('module_instances',[]),key=lambda m:str(m.get('module_instance_id'))):
        if not module.get('enabled',True) or module.get('pv_field_id') in invalid_fields:continue
        field=fields.get(module.get('pv_field_id'));definition=definitions.get(module.get('module_definition_revision_id'))
        if field is None or definition is None:
            # Legacy unresolved cases already retain their original S1 findings.
            if field and is_explicit(field):record('module_unresolved',module,reason='pinned module definition missing')
            continue
        try:
            geometry=module_descriptor(module,field,definition,scene.get('surfaces',[]));corners=geometry['corners_3d'];array=np.asarray(corners,dtype=float)
            if not np.isfinite(array).all():raise ValueError('module corners must be finite')
            clearance=float((field.get('setback_configuration') or {}).get('obstacle_setback_m',0.))
            if not math.isfinite(clearance) or clearance<0:raise ValueError('invalid obstacle clearance')
        except (ValueError,KeyError,TypeError,AttributeError,IndexError,OverflowError) as exc:
            if is_explicit(field):record('module_unresolved',module,reason=str(exc))
            continue
        modules.append(module);rectangles.append(corners);bounds.append((array.min(axis=0),array.max(axis=0)));explicit.append(is_explicit(field));clearances.append(clearance)
    if rectangles:
        tree=STRtree([box(low[0],low[1],high[0],high[1]) for low,high in bounds])
        for i,(low,high) in enumerate(bounds):
            for raw in tree.query(box(low[0]-CONTACT_M,low[1]-CONTACT_M,high[0]+CONTACT_M,high[1]+CONTACT_M)):
                j=int(raw)
                if j<=i or not (explicit[i] or explicit[j]):continue
                if high[2]+CONTACT_M<bounds[j][0][2] or bounds[j][1][2]+CONTACT_M<low[2]:continue
                if explicit[i] and explicit[j] and modules[i]['pv_field_id']==modules[j]['pv_field_id'] and modules[i].get('table_id')==modules[j].get('table_id'):continue
                if module_interiors_cross(rectangles[i],rectangles[j]):record('module_module_overlap',modules[i],modules[j]['module_instance_id'],other_pv_field_id=modules[j]['pv_field_id'])
    for obstacle in sorted(scene.get('obstacles',[]),key=lambda o:str(o.get('obstacle_id'))):
        mesh=obstacle.get('obstacle_type')=='imported_mesh'
        if not mesh and not any(explicit):continue
        try:
            if mesh:
                resolved=resolve_mesh(obstacle);vertices=resolved['vertices_3d']
                faces=[(fi,[vertices[k] for k in tri]) for fi,f in enumerate(resolved['faces']) for tri in f['triangles']]
            else:
                geometry,_=_obstacle_geometry(obstacle)
                source_faces=_obstacle_faces(obstacle['obstacle_id'],geometry['base_vertices_3d'],geometry['top_vertices_3d'])
                faces=[]
                for fi,f in enumerate(source_faces):
                    vertices=f['vertices_3d'];t=triangulate_face(vertices,list(range(len(vertices))),label=f"obstacle {obstacle['obstacle_id']} face {fi}")
                    faces.extend((fi,[vertices[k] for k in tri]) for tri in t['triangles'])
        except (KeyError,ValueError,TypeError,AttributeError,IndexError,OverflowError) as exc:
            record('obstacle_unresolved',other=obstacle.get('obstacle_id',''),reason=str(exc))
            continue
        if not faces:continue
        face_bounds=[(np.min(t,axis=0),np.max(t,axis=0)) for _,t in faces];tree=STRtree([box(l[0],l[1],h[0],h[1]) for l,h in face_bounds])
        for i,module in enumerate(modules):
            if not mesh and not explicit[i]:continue
            low,high=bounds[i];clearance=clearances[i];radius=max(clearance,CONTACT_M)
            if not mesh:
                footprint=Polygon(obstacle['footprint']['vertices']);base=float(obstacle['base_elevation_m']);top=base+float(obstacle['height_m'])
                if any(base<=p[2]<=top and footprint.contains(Point(p[:2])) for p in rectangles[i]):
                    record('module_obstacle_overlap',module,obstacle['obstacle_id']);continue
            nearest=math.inf;face_index=None
            for raw in tree.query(box(low[0]-radius,low[1]-radius,high[0]+radius,high[1]+radius)):
                j=int(raw);fl,fh=face_bounds[j]
                if high[2]+radius<fl[2] or fh[2]+radius<low[2]:continue
                distance=polygon_surface_distance(rectangles[i],faces[j][1])
                if distance<nearest:nearest,face_index=distance,faces[j][0]
            if nearest<=CONTACT_M:
                record('module_obstacle_overlap',module,obstacle['obstacle_id'],face_index=face_index,distance_m=nearest)
            elif clearance>0 and nearest<clearance-CONTACT_M:
                record('module_obstacle_clearance',module,obstacle['obstacle_id'],face_index=face_index,distance_m=nearest,clearance_m=clearance)
    return conflicts
