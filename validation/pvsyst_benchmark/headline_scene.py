"""Approved scene reconstruction for the two active benchmark labels.

No source-file defaults, general repairs, packing, or shading approximations.
The one source-data exception is identity-specific and measured before use.
"""

from copy import deepcopy
import math

import numpy as np
from shapely.geometry import Polygon

from geometry.scene.mesh import make_mesh_obstacle
from .source import SourceError, vector
from .scene import read_scene, reconstruction_counts


ANCHOR_CODES = {
    1: "lower_left", 2: "lower_center", 3: "lower_right",
    5: "upper_center", 7: "center",
}


def structural_terminators(root):
    """Recognize exact typed-block closures, with declarations/counts checked."""
    declarations = {
        ("pvShading", "End of ListeObjets"): "ListeObjets, list of",
        ("pvShading", "End of List ObjectsGroups"): "ObjectsGroups, list of",
        ("pvShdGenObject", "End of TPoly3D"): "Sommets, TPoly3D",
        ("pvShdFTable", "End of TInterpole2D"): "SFTable",
    }
    verified = []
    for node in root.walk():
        markers = [v for k, v in node.records if k == "__unparsed_structure__"]
        if len(markers) != len(set(markers)):
            raise SourceError("duplicate typed-block terminator")
        for marker in markers:
            key = declarations.get((node.kind, marker))
            start = node.one(key) if key else None
            if start is None:
                raise SourceError("unmapped or unmatched typed-block terminator")
            if key == "SFTable":
                if start != "TInterpole2D":
                    raise SourceError("unexpected shading-table type")
            else:
                tokens = start.split()
                expected_type, count = {
                    "ListeObjets, list of": ("TShdObject", sum(n.kind in {"pvShdArrayTable", "pvShdGenObject"} for n in node.children)),
                    "ObjectsGroups, list of": ("TGroupeObjetsOmbrage", sum(n.kind == "pvShdObjectGroup" for n in node.children)),
                    "Sommets, TPoly3D": ("Point3D", sum(k.startswith("Point_") for k, _ in node.records)),
                }[key]
                if len(tokens) != 2 or tokens[1] != expected_type or tokens[0] != str(count):
                    raise SourceError("typed-block declaration count/type mismatch")
            verified.append({"kind": node.kind, "terminator": marker})
    return verified


def anchor_name(code, *, opposite_view=False):
    if type(code) is not int or code not in ANCHOR_CODES:
        raise SourceError("unproved table anchor code")
    name = ANCHOR_CODES[code]
    if opposite_view:
        name = {"lower_left": "lower_right", "lower_right": "lower_left"}.get(name, name)
    return name


def excluded_face_evidence(label, object_id, face_index, vertices, face):
    """A1 permits exactly one invalid, almost collinear source edge loop."""
    if (label, object_id, face_index) != ("P3", "154", 3):
        raise SourceError("no source-face exclusion is approved for this identity")
    p = np.asarray([vertices[i] for i in face], dtype=float)
    if len(p) != 4 or not np.isfinite(p).all():
        raise SourceError("approved edge loop must have four finite corners")
    pairs = [(float(np.linalg.norm(a-b)), i, j)
             for i, a in enumerate(p) for j, b in enumerate(p) if i < j]
    length, i, j = max(pairs)
    if length == 0:
        raise SourceError("approved edge loop has no end-to-end line")
    offset = float(np.max(np.linalg.norm(np.cross(p-p[i], (p[j]-p[i])/length), axis=1)))
    area = float(np.linalg.norm(np.cross(p, np.roll(p, -1, axis=0)).sum(axis=0))/2)
    # This exception is the horizontal invalid loop, never a valid small surface.
    if (offset > .001 or area >= .1 or np.ptp(p[:, 2]) > 1e-9
            or Polygon(p[:, :2]).is_valid):
        raise SourceError("approved edge loop does not meet its geometric guards")
    hull_area = float(Polygon(p[:, :2]).convex_hull.area)
    return {
        "code": "approved_source_edge_loop_omitted", "case": label,
        "object_id": object_id, "original_face_index": face_index,
        "corner_count": len(face), "end_to_end_length_m": length,
        "maximum_line_offset_m": offset, "absolute_signed_area_m2": area,
        "convex_hull_area_m2": hull_area,
        "shadow_bound": {
            "basis": "area/sin(solar elevation), horizontal projected area; not an all-angle annual energy bound",
            "minimum_solar_elevation_deg": 7.,
            "source_signed_area_estimate_m2": area/math.sin(math.radians(7)),
            "conservative_convex_hull_envelope_m2": hull_area/math.sin(math.radians(7)),
        },
        "all_other_faces_and_vertices_preserved": True,
    }


def mesh_operation(node, mesh, *, label):
    if node.number("DInclin") != 0 or node.number("DAzimut") != 0:
        raise SourceError("only the proved identity mesh rotation is supported")
    numbered = sorted((int(k.split("_")[1]), vector(v, size=3))
                      for k, v in node.records if k.startswith("Point_"))
    vertices = [p for _, p in numbered]
    faces = deepcopy(mesh.faces)
    omissions = []
    if label == "P3" and mesh.object_id == "154":
        if len(faces) <= 3:
            raise SourceError("approved source face is missing")
        omissions.append(excluded_face_evidence(label, mesh.object_id, 3, vertices, faces[3]))
        faces = [f for i, f in enumerate(faces) if i != 3]
    identity = np.eye(3).tolist()
    payload = {"vertices_m": vertices, "faces": faces,
               "transform": {"rotation_matrix": identity,
                             "translation_m": vector(node.one("DOrigine"), size=3)}}
    oid = f"{label}-mesh-{mesh.object_id}"
    op = {"operation_id": oid, "operation_type": "create_mesh",
          "obstacle_id": oid, "scene_object_id": "obj-"+oid,
          "name": oid, "mesh": payload,
          "provenance": {"source_id": label, "source_object_id": mesh.object_id,
                         "source_face_exceptions": omissions}}
    # Every retained face must pass unchanged product validation, no filter/retry.
    validated = make_mesh_obstacle(
        obstacle_id=oid, scene_object_id=op["scene_object_id"], name=oid,
        mesh=payload, provenance=op["provenance"])
    facts = {"object_id": mesh.object_id, "original_face_count": len(mesh.faces),
             "retained_face_count": len(faces), "vertex_count": len(vertices),
             "omissions": omissions,
             "nonplanar_faces": sum(f["nonplanar_within_tolerance"]
                                    for f in validated["mesh_validation"]["faces"])}
    return op, facts


def build_geometry(root, plan, module_definitions):
    if plan.label not in {"P2", "P3"}:
        raise SourceError("only active case labels are supported")
    scene = read_scene(root)
    terminators = structural_terminators(root)
    counts = reconstruction_counts(scene, plan)
    if not counts["counts_match"] or not counts["orientations_match"]:
        raise SourceError("source module counts/orientations do not reconcile")
    # The old reader flags other observed origin enums; A1 now supplies them.
    unknown = [f for f in scene.unsupported
               if f.code != "origin_code_unknown" and not (
                   f.code == "scene_key_unknown" and f.path.endswith(".__unparsed_structure__"))]
    if unknown:
        raise SourceError("unmapped scene semantics: " + repr([f.record() for f in unknown]))
    operations, mesh_facts, extents, field_subarrays = [], [], [], {}
    nodes = {n.one("NoObjCreated"): n for n in root.walk("pvShdGenObject")}
    for mesh in scene.meshes:
        op, facts = mesh_operation(nodes[mesh.object_id], mesh, label=plan.label)
        operations.append(op)
        mesh_facts.append(facts)
    used = set()
    for sub in plan.subarrays:
        orientation = plan.orientations[sub["orientation"]-1]
        definition = module_definitions[sub["module_ref"]]
        tables = []
        for t in scene.tables:
            if (t.tilt, t.azimuth) != (orientation["tilt_deg"], orientation["source_azimuth_deg"]):
                continue
            if t.object_id in used:
                raise SourceError("table cannot be allocated to a unique sub-array")
            used.add(t.object_id)
            w, h = (definition["mechanical"][k] for k in ("width_m", "height_m"))
            pw, ph = (h, w) if t.landscape else (w, h)
            ow = t.columns*pw+(t.columns-1)*t.gap_x
            oh = t.rows*ph+(t.rows-1)*t.gap_y
            extents.append({"table_id": t.object_id,
                            "across_deviation_m": ow-t.width, "upslope_deviation_m": oh-t.upslope,
                            "declared_rectangle_used": plan.label == "P2"})
            table = {"table_id": "table-"+t.object_id, "anchor_xyz_m": list(t.origin),
                     "anchor_convention": anchor_name(t.anchor_code),
                     "tilt_deg": t.tilt, "azimuth_deg": orientation["azimuth_deg"],
                     "module_definition_revision_id": definition["revision_id"],
                     "modules_across": t.columns, "modules_up": t.rows,
                     "module_orientation": "landscape" if t.landscape else "portrait",
                     "module_gap_across_m": t.gap_x, "module_gap_up_m": t.gap_y}
            if plan.label == "P2":
                table["rectangle"] = {"width_m": t.width, "height_m": t.upslope}
            tables.append(table)
        if sum(t["modules_across"]*t["modules_up"] for t in tables) != sub["module_count"]:
            raise SourceError("sub-array/table module count mismatch")
        fid = f"{plan.label}-field-{sub['index']}"
        field_subarrays[fid] = sub["index"]
        operations.append({"operation_id": fid, "operation_type": "create_explicit_field",
                           "pv_field_id": fid, "name": fid, "tables": tables,
                           "provenance": {"source_id": plan.label, "source_subarray": sub["index"]}})
    if used != {t.object_id for t in scene.tables}:
        raise SourceError("unallocated source tables")
    return operations, {"counts": counts, "meshes": mesh_facts,
                        "table_extents": extents, "field_subarrays": field_subarrays,
                        "verified_structural_terminators": terminators}
