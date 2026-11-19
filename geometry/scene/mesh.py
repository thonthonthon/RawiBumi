"""Strict opaque surface meshes. Original vertices are never repaired or moved."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import math
from typing import Any, Mapping

import numpy as np
from shapely.geometry import LineString, Point, Polygon

MESH_ADAPTER_VERSION = "rawibumi.opaque_surface_mesh.v1"
MESH_PLANARITY_TOLERANCE_M = 0.001
PLANAR_M = 1e-9
AREA_M2 = 1e-10


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}: expected a finite number")
    return float(value)


def _triple(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label}: expected three coordinates")
    return [_number(v, label) for v in value]


def _cross2(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def triangulate_face(vertices, indices, *, label):
    """Ear clipping in a best-fit plane; emitted indices use untouched 3D points."""
    if not isinstance(indices, list) or not 3 <= len(indices) <= 512:
        raise ValueError(f"{label}: face must have 3 to 512 indices")
    if any(type(i) is not int or not 0 <= i < len(vertices) for i in indices):
        raise ValueError(f"{label}: face index is not an in-range integer")
    if len(set(indices)) != len(indices):
        raise ValueError(f"{label}: repeated vertex index")
    points = np.asarray([vertices[i] for i in indices], dtype=float)
    if len({tuple(p) for p in points}) != len(points):
        raise ValueError(f"{label}: repeated geometric corner")
    relative = points - points.mean(axis=0)
    newell = np.cross(relative, np.roll(relative, -1, axis=0)).sum(axis=0)
    if float(np.linalg.norm(newell))/2 <= AREA_M2:
        raise ValueError(f"{label}: zero or unrepresentable face area")
    # SVD is only a measurement/projection basis; no original vertex is changed.
    _, _, vh = np.linalg.svd(relative, full_matrices=False)
    normal = vh[-1]
    if float(np.dot(normal, newell)) < 0:
        normal = -normal
    deviation = float(np.max(np.abs(relative @ normal)))
    if deviation > MESH_PLANARITY_TOLERANCE_M:
        raise ValueError(f"{label}: non-planar face deviation {deviation:.9g} m exceeds 0.001 m")
    axis = np.eye(3)[int(np.argmin(np.abs(normal)))]
    u = axis - float(np.dot(axis, normal))*normal
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    xy = np.column_stack((relative @ u, relative @ v)).tolist()
    polygon = Polygon(xy)
    if not polygon.is_valid or polygon.is_empty or polygon.area <= AREA_M2:
        raise ValueError(f"{label}: face projection is not a simple positive-area polygon")
    orientation = 1 if sum(xy[i][0]*xy[(i+1)%len(xy)][1]-xy[(i+1)%len(xy)][0]*xy[i][1] for i in range(len(xy))) > 0 else -1
    remaining = list(range(len(indices)))
    triangles = []
    while len(remaining) > 3:
        chosen = None
        for i in sorted(remaining):
            at = remaining.index(i)
            a, c = remaining[at-1], remaining[(at+1)%len(remaining)]
            if orientation*_cross2(xy[a], xy[i], xy[c]) <= AREA_M2*2:
                continue
            tri = Polygon([xy[a], xy[i], xy[c]])
            current = Polygon([xy[k] for k in remaining])
            diagonal = LineString([xy[a], xy[c]])
            if not current.covers(diagonal) or not current.covers(tri):
                continue
            if any(tri.covers(Point(xy[k])) for k in remaining if k not in (a, i, c)):
                continue
            chosen = (a, i, c)
            break
        if chosen is None:
            raise ValueError(f"{label}: deterministic triangulation cannot retain every original corner")
        triangles.append([indices[k] for k in chosen])
        remaining.remove(chosen[1])
    triangles.append([indices[k] for k in remaining])
    local = {index: i for i, index in enumerate(indices)}
    projected = [Polygon([xy[local[k]] for k in tri]) for tri in triangles]
    if any(t.area <= AREA_M2 for t in projected):
        raise ValueError(f"{label}: triangulation produces an unrepresentable triangle")
    from shapely.ops import unary_union
    union = unary_union(projected)
    tolerance = max(AREA_M2, polygon.area*1e-12)
    if (len(triangles) != len(indices)-2 or polygon.symmetric_difference(union).area > tolerance
            or abs(sum(t.area for t in projected)-polygon.area) > tolerance):
        raise ValueError(f"{label}: triangulation failed projected coverage/area conservation")
    areas = [float(np.linalg.norm(np.cross(np.asarray(vertices[t[1]])-vertices[t[0]], np.asarray(vertices[t[2]])-vertices[t[0]])))/2 for t in triangles]
    return {"vertex_indices": list(indices), "triangles": triangles,
            "maximum_plane_deviation_m": deviation,
            "nonplanar_within_tolerance": deviation > PLANAR_M,
            "projected_area_m2": float(polygon.area), "surface_area_m2": sum(areas)}


def _topology(faces, vertex_count):
    edges, incident, directed = defaultdict(list), defaultdict(set), Counter()
    for fi, face in enumerate(faces):
        for i, a in enumerate(face):
            b = face[(i+1)%len(face)]
            edges[tuple(sorted((a, b)))].append(fi)
            directed[(a, b)] += 1
            incident[a].add(fi)
    adjacency = {i: set() for i in range(len(faces))}
    for ids in incident.values():
        for i in ids: adjacency[i].update(ids-{i})
    todo = set(adjacency); components = []
    while todo:
        seed = min(todo); group = set(); stack = [seed]
        while stack:
            i = stack.pop()
            if i in group: continue
            group.add(i); stack.extend(adjacency[i]-group)
        todo -= group
        group_edges = [ids for ids in edges.values() if ids[0] in group]
        boundary = any(len(ids)==1 for ids in group_edges)
        bad_link = False
        for vertex in {v for i in group for v in faces[i]}:
            links = defaultdict(list)
            for i in incident[vertex]:
                face=faces[i]; at=face.index(vertex)
                a,b=face[at-1],face[(at+1)%len(face)]
                links[a].append(b);links[b].append(a)
            visited=set(); stack=[next(iter(links))]
            while stack:
                a=stack.pop()
                if a in visited:continue
                visited.add(a);stack.extend(links[a])
            degrees=[len(v) for v in links.values()]
            valid=all(d==2 for d in degrees) or (degrees.count(1)==2 and all(d in (1,2) for d in degrees))
            bad_link |= len(visited)!=len(links) or not valid
        kind = "nonmanifold_surface_set" if bad_link or any(len(ids)>2 for ids in group_edges) else ("open_manifold_surface" if boundary else "closed_manifold")
        components.append({"face_indices": sorted(group), "topology_class": kind})
    return {"components": components, "component_count": len(components),
            "edge_incidence_counts": dict(sorted(Counter(len(v) for v in edges.values()).items())),
            "winding_consistent": all(len(ids)!=2 or (directed[(a,b)]==1 and directed[(b,a)]==1) for (a,b),ids in edges.items()),
            "unused_vertex_count": vertex_count-len(incident), "role": "two_sided_opaque_surface_union"}


def resolve_mesh(obstacle: Mapping[str, Any]):
    """Return validated world geometry; no inference from any footprint is legal."""
    label = f"mesh {obstacle.get('obstacle_id', '<missing>')}"
    if obstacle.get("obstacle_type") != "imported_mesh" or obstacle.get("role") != "opaque_occluder" or obstacle.get("receiver_enabled") is not False:
        raise ValueError(f"{label}: role must be opaque_occluder with receiver_enabled=false")
    mesh = obstacle.get("mesh")
    if not isinstance(mesh, dict) or not {"vertices_m", "faces"} <= mesh.keys():
        raise ValueError(f"{label}: imported_mesh requires mesh vertices and faces")
    if set(mesh)-{"vertices_m", "faces", "transform"}:
        raise ValueError(f"{label}: unknown mesh payload key")
    vertices, faces = mesh["vertices_m"], mesh["faces"]
    if not isinstance(vertices,list) or not 3<=len(vertices)<=50000 or not isinstance(faces,list) or not 1<=len(faces)<=50000:
        raise ValueError(f"{label}: invalid vertex or face count")
    points=np.asarray([_triple(p,label) for p in vertices],dtype=float)
    transform=mesh.get("transform")
    if transform is not None:
        if not isinstance(transform,dict) or set(transform)!={"rotation_matrix","translation_m"}:
            raise ValueError(f"{label}: transform requires rotation_matrix and translation_m only")
        rows=transform["rotation_matrix"]
        if not isinstance(rows,list) or len(rows)!=3:raise ValueError(f"{label}: rotation matrix must be 3 by 3")
        rotation=np.asarray([_triple(r,label) for r in rows]);translation=np.asarray(_triple(transform['translation_m'],label))
        if np.max(np.abs(rotation.T@rotation-np.eye(3)))>1e-12 or abs(float(np.linalg.det(rotation))-1)>1e-12:
            raise ValueError(f"{label}: transform must be a proper rigid rotation, with no scale, shear or reflection")
        points=points@rotation.T+translation
    if not np.isfinite(points).all():raise ValueError(f"{label}: transformed coordinates must be finite")
    if np.max(np.abs(points[:,:2]))>50000 or np.max(np.ptp(points[:,:2],axis=0))>10000:
        raise ValueError(f"{label}: XY coordinates/bounds exceed scene limits")
    if not -1000<=float(points[:,2].min())<=10000 or np.ptp(points[:,2])>1000:
        raise ValueError(f"{label}: Z base/span exceeds scene limits")
    world=points.tolist()
    records=[triangulate_face(world,face,label=f"{label} face {i}") for i,face in enumerate(faces)]
    digest=hashlib.sha256(json.dumps(mesh,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return {"vertices_3d":world,"faces":records,"triangles":[t for f in records for t in f['triangles']],
            "topology":_topology(faces,len(vertices)),"mesh_content_sha256":digest,
            "mesh_planarity_tolerance_m":MESH_PLANARITY_TOLERANCE_M,"adapter_version":MESH_ADAPTER_VERSION}


def make_mesh_obstacle(*, obstacle_id, scene_object_id, name, mesh, provenance, role="opaque_occluder", shading_enabled=True):
    if not all(isinstance(s,str) and s.strip() for s in (obstacle_id,scene_object_id,name)):
        raise ValueError("mesh identity and name must be nonblank strings")
    if not isinstance(provenance,dict):raise ValueError(f"mesh {obstacle_id}: provenance must be an object")
    if not isinstance(shading_enabled,bool):raise ValueError(f"mesh {obstacle_id}: shading_enabled must be boolean")
    source={"obstacle_id":obstacle_id,"scene_object_id":scene_object_id,"name":name,
            "obstacle_type":"imported_mesh","role":role,"receiver_enabled":False,
            "shading_enabled":shading_enabled,"visible":True,"locked":False,"selectable":True,
            "mesh":deepcopy(mesh),"provenance":deepcopy(provenance)}
    resolved=resolve_mesh(source)
    source['mesh_validation']={k:deepcopy(resolved[k]) for k in ('faces','topology','mesh_content_sha256','mesh_planarity_tolerance_m','adapter_version')}
    json.dumps(source,allow_nan=False)
    return source
