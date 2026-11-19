"""SHD structural reader and reconstruction gates; no mesh approximation."""

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import itertools
import json
import math
import re

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union
from .source import Node, SourceError, vector
from .project import Finding, ProjectPlan


COMMON = {
    "Comment",
    "Version",
    "Flags",
    "Source",
    "ColorSurf",
    "ColorBord",
    "ColorTechn",
}
KEYS = {
    "pvShading": COMMON
    | set(
        "NOrient_Shd NOrientTables Precision FracOmbreMod FracOmbreThin OrientTolerance OrientUseZones OrientTiltZero IsBacktracking Pitch LargCapt LargHaut LargBas BTNoTrackers GCROffset DisplayedRef ObjectsGroup PartialOmbrageNoRefField PartialOmbrageNoSubField".split()
    ),
    "pvShdArrayTable": COMMON
    | set(
        "NoObjCreated NPElemRes NElements DOrigine DInclin DAzimut NElemChamps NoOrient PanneauPVName ModSpacingX ModSpacingY NModInHeight NModInWidth ModuleOrient LongShed LargShed Cadre TypeOrigine".split()
    ),
    "pvShdGenObject": COMMON
    | set(
        "NoObjCreated NPElements NElements DOrigine DInclin DAzimut Faces Faces_contd".split()
    )
    | {"Sommets, TPoly3D"},
    "pvShdObjectGroup": COMMON | {"Objects", "Objects_contd"},
    "pvShdFTable": COMMON
    | set(
        "CalcVersion FOCalcul NoOrientPC Precision SFTable NBinX ExtX XDeb YDeb InclP AzimP".split()
    ),
}
KEYS["pvShading"].update({"ObjectsGroups, list of", "ListeObjets, list of"})


@dataclass(frozen=True)
class Table:
    object_id: str
    origin: tuple
    tilt: float
    azimuth: float
    width: float
    upslope: float
    anchor_code: int
    columns: int | None
    rows: int | None
    gap_x: float
    gap_y: float
    landscape: bool

    @property
    def modules(self):
        return (
            None
            if self.columns is None or self.rows is None
            else self.columns * self.rows
        )

    def corners(self, anchor):
        """Discrete anchors in the source plane axes; never optimize a translation."""
        theta, beta = math.radians(self.azimuth), math.radians(self.tilt)
        u = np.array([math.cos(theta), math.sin(theta), 0.0])
        v = np.array(
            [
                math.sin(theta) * math.cos(beta),
                -math.cos(theta) * math.cos(beta),
                math.sin(beta),
            ]
        )
        base = (
            np.array(self.origin)
            - anchor[0] * self.width * u
            - anchor[1] * self.upslope * v
        )
        return np.array(
            [
                base,
                base + self.width * u,
                base + self.width * u + self.upslope * v,
                base + self.upslope * v,
            ]
        )

    def fits_module_dimensions(self, width, height, tolerance=0.002):
        if self.modules is None:
            return False
        w, h = (height, width) if self.landscape else (width, height)
        return (
            self.columns * w + (self.columns - 1) * self.gap_x <= self.width + tolerance
            and self.rows * h + (self.rows - 1) * self.gap_y <= self.upslope + tolerance
        )


@dataclass
class Mesh:
    object_id: str
    vertices: np.ndarray
    faces: list[list[int]]
    unresolved_transform: tuple[str, ...] = ()

    def topology(self, tolerance=0.002):
        if self.unresolved_transform:
            return "transform_unresolved"
        edge_counts = Counter()
        planar = True
        for face in self.faces:
            points = self.vertices[face]
            if len(set(face)) != len(face) or len(face) < 3:
                return "invalid_mesh"
            singular = np.linalg.svd(points - points.mean(axis=0), compute_uv=False)
            if len(singular) > 2 and singular[-1] > tolerance:
                planar = False
            if np.linalg.matrix_rank(points - points[0], tol=tolerance) < 2:
                return "invalid_mesh"
            for a, b in zip(face, face[1:] + face[:1]):
                edge_counts[tuple(sorted((a, b)))] += 1
        if any(n != 2 for n in edge_counts.values()):
            return "open_or_nonmanifold_mesh"
        if not planar:
            return "nonplanar_closed_mesh"
        z = self.vertices[:, 2]
        low, high = float(z.min()), float(z.max())
        if high - low <= tolerance:
            return "degenerate_mesh"
        if not np.all((abs(z - low) <= tolerance) | (abs(z - high) <= tolerance)):
            return "multi_level_mesh"
        bottom, top = [], []
        for face in self.faces:
            p = self.vertices[face]
            if np.all(abs(p[:, 2] - low) <= tolerance):
                bottom.append(Polygon(p[:, :2]))
            elif np.all(abs(p[:, 2] - high) <= tolerance):
                top.append(Polygon(p[:, :2]))
            elif len({tuple(np.round(v[:2], 6)) for v in p}) != 2:
                return "non_prismatic_two_level_mesh"
        if (
            not bottom
            or not top
            or any(not p.is_valid or p.area <= 0 for p in bottom + top)
        ):
            return "invalid_mesh"
        b, t = unary_union(bottom), unary_union(top)
        if (
            b.geom_type != "Polygon"
            or b.interiors
            or b.hausdorff_distance(t) > tolerance
        ):
            return "non_prismatic_two_level_mesh"
        return "vertical_prism"

    def facts(self):
        edges = Counter()
        for face in self.faces:
            for a, b in zip(face, face[1:] + face[:1]):
                edges[tuple(sorted((a, b)))] += 1
        return {
            "object_id": self.object_id,
            "vertices": len(self.vertices),
            "faces": len(self.faces),
            "z_levels": len(set(np.round(self.vertices[:, 2], 3))),
            "edge_incidence_counts": dict(Counter(edges.values())),
            "faces_with_repeated_indices": sum(
                len(set(f)) != len(f) for f in self.faces
            ),
            "topology_class": self.topology(),
            "unresolved_transform": list(self.unresolved_transform),
        }

    def support_faces(self):
        if self.unresolved_transform:
            return []
        result = []
        for face in self.faces:
            p = self.vertices[face]
            polygon = Polygon(p[:, :2])
            if not polygon.is_valid or polygon.area <= 1e-8:
                continue
            design = np.column_stack([p[:, 0], p[:, 1], np.ones(len(p))])
            abc = np.linalg.lstsq(design, p[:, 2], rcond=None)[0]
            if np.max(abs(design @ abc - p[:, 2])) <= 0.002:
                result.append((polygon, abc))
        return result

    def world_signature(self):
        return sorted(
            tuple(sorted(tuple(np.round(p, 3)) for p in self.vertices[face]))
            for face in self.faces
        )


@dataclass
class Scene:
    tables: list[Table]
    meshes: list[Mesh]
    orientations: list[tuple[float, float]]
    unsupported: list[Finding]
    groups: list[list[str]]
    frame: str | None


def _integer_stream(node, key):
    values = node.values(key)
    if len(values) > 1:
        raise SourceError("duplicate list declaration")
    records = [
        (field, value)
        for field, value in node.records
        if field in {key, key + "_contd"}
    ]
    result = []
    for index, (field, value) in enumerate(records):
        parts = [p.strip() for p in value.rstrip(",").split(",")]
        if parts[-1] == "contd":
            if index + 1 == len(records) or records[index + 1][0] != key + "_contd":
                raise SourceError("missing continuation records")
            parts = parts[:-1]
        if any(not re.fullmatch(r"-?\d+", p) for p in parts):
            raise SourceError("invalid integer list token")
        result.extend(int(p) for p in parts)
    return result


def _mesh(node):
    numbered = []
    for key, value in node.records:
        if re.fullmatch(r"Point_\d+", key):
            numbered.append((int(key.split("_")[1]), vector(value, size=3)))
    numbered.sort()
    if [i for i, _ in numbered] != list(range(1, len(numbered) + 1)):
        raise SourceError("incomplete mesh vertex numbering")
    tokens = _integer_stream(node, "Faces")
    if not tokens or tokens[0] != -1 or len(tokens) != node.integer("NPElements"):
        raise SourceError("invalid face stream prefix or count")
    faces = []
    for token in tokens:
        if token == -1:
            faces.append([])
        elif token < 0 or token >= len(numbered):
            raise SourceError("face index outside vertex array")
        else:
            faces[-1].append(token)
    if len(faces) != node.integer("NElements") or any(len(f) < 3 for f in faces):
        raise SourceError("face count or minimum vertices mismatch")
    unresolved = tuple(
        k for k in ("DOrigine", "DInclin", "DAzimut") if node.one(k) is None
    )
    if not unresolved and node.number("DInclin") != 0:
        unresolved = ("nonzero_DInclin_transform_order",)
    p = np.array([v for _, v in numbered])
    if not unresolved:
        theta = math.radians(node.number("DAzimut"))
        rotation = np.array(
            [
                [math.cos(theta), -math.sin(theta), 0],
                [math.sin(theta), math.cos(theta), 0],
                [0, 0, 1],
            ]
        )
        p = p @ rotation.T + np.array(vector(node.one("DOrigine"), size=3))
    return Mesh(node.one("NoObjCreated"), p, faces, unresolved)


def read_scene(root: Node, *, require_layout=True):
    if root.kind != "pvShading":
        nodes = list(root.walk("pvShading"))
        if len(nodes) != 1:
            raise SourceError("missing unique shading scene")
        root = nodes[0]
    tables, meshes, orientations, unsupported, groups = [], [], [], [], []
    for node in root.walk():
        if node.kind not in KEYS:
            unsupported.append(
                Finding("scene_object_unknown", node.kind, "Unknown source object type")
            )
        for key, _ in node.records:
            if (
                key not in KEYS.get(node.kind, set())
                and not (
                    node.kind == "pvShdGenObject" and re.fullmatch(r"Point_\d+", key)
                )
                and not (node.kind == "pvShdFTable" and re.fullmatch(r"Line_\d+", key))
            ):
                unsupported.append(
                    Finding(
                        "scene_key_unknown",
                        node.kind + "." + key,
                        "No source semantics established",
                    )
                )
        if node.kind == "pvShdArrayTable":
            has_layout = (
                node.one("NModInWidth") is not None
                and node.one("NModInHeight") is not None
            )
            if require_layout and not has_layout:
                raise SourceError("missing saved table module counts")
            if require_layout and node.one("ModuleOrient") not in {
                "moPortrait",
                "moLandScape",
            }:
                raise SourceError("missing or unknown saved module orientation")
            columns = node.integer("NModInWidth") if has_layout else None
            rows = node.integer("NModInHeight") if has_layout else None
            if has_layout and (columns == 0 or rows == 0):
                raise SourceError("empty saved table")
            t = Table(
                node.one("NoObjCreated"),
                tuple(vector(node.one("DOrigine"), size=3)),
                node.number("DInclin"),
                node.number("DAzimut"),
                node.number("LongShed"),
                node.number("LargShed"),
                node.integer("TypeOrigine"),
                columns,
                rows,
                (
                    node.number("ModSpacingX")
                    if require_layout
                    else float(node.one("ModSpacingX", "0"))
                ),
                (
                    node.number("ModSpacingY")
                    if require_layout
                    else float(node.one("ModSpacingY", "0"))
                ),
                node.one("ModuleOrient") == "moLandScape",
            )
            if (
                not 0 <= t.tilt < 90
                or t.width <= 0
                or t.upslope <= 0
                or not math.isfinite(t.gap_x + t.gap_y)
                or min(t.gap_x, t.gap_y) < 0
            ):
                raise SourceError("invalid table dimensions or angles")
            if t.anchor_code != 1:
                unsupported.append(
                    Finding(
                        "origin_code_unknown",
                        node.kind + ".TypeOrigine",
                        "No interpretation established for this origin code",
                    )
                )
            tables.append(t)
        elif node.kind == "pvShdGenObject":
            mesh = _mesh(node)
            meshes.append(mesh)
            if mesh.unresolved_transform:
                unsupported.append(
                    Finding(
                        "mesh_transform_unresolved",
                        node.kind + "." + mesh.object_id,
                        "No world-coordinate substitution for absent or unproved transforms: "
                        + ", ".join(mesh.unresolved_transform),
                    )
                )
        elif node.kind == "pvShdFTable":
            if node.one("FOCalcul") != "foLinear":
                raise SourceError("only foLinear shading is authorized")
            orientations.append((node.number("InclP"), node.number("AzimP")))
        elif node.kind == "pvShdObjectGroup":
            ids = [str(v) for v in _integer_stream(node, "Objects")]
            groups.append(ids)
    ids = [t.object_id for t in tables] + [m.object_id for m in meshes]
    if len(ids) != len(set(ids)) or None in ids:
        raise SourceError("duplicate or missing object ID")
    if any(i not in ids for g in groups for i in g):
        raise SourceError("group references missing object")
    if len(orientations) != root.integer("NOrientTables") or len(
        orientations
    ) != root.integer("NOrient_Shd"):
        raise SourceError("declared scene orientation count mismatch")
    return Scene(
        tables, meshes, orientations, unsupported, groups, root.one("DisplayedRef")
    )


def reconstruction_counts(scene: Scene, project: ProjectPlan):
    expected = Counter()
    actual = Counter()
    for s in project.subarrays:
        o = project.orientations[s["orientation"] - 1]
        expected[(o["tilt_deg"], o["source_azimuth_deg"])] += s["module_count"]
    for table in scene.tables:
        actual[(table.tilt, table.azimuth)] += table.modules or 0
    planes = {(o["tilt_deg"], o["source_azimuth_deg"]) for o in project.orientations}
    return {
        "counts_match": actual == expected,
        "orientations_match": set(actual) == planes == set(scene.orientations),
        "expected_by_orientation": [(list(k), v) for k, v in sorted(expected.items())],
        "actual_by_orientation": [(list(k), v) for k, v in sorted(actual.items())],
    }


ANCHORS = tuple(itertools.product((0.0, 0.5, 1.0), repeat=2))


def resolve_anchor_hypotheses(tables, supports, *, dimensions=None, tolerance=0.002):
    """Only independent support geometry is evidence; no energy/yield fitting."""
    results = []
    for anchor in ANCHORS:
        matched = 0
        for table in tables:
            if (
                dimensions
                and table.object_id in dimensions
                and not table.fits_module_dimensions(
                    *dimensions[table.object_id], tolerance=tolerance
                )
            ):
                continue
            points = table.corners(anchor)
            footprint = Polygon(points[:, :2])
            for polygon, abc in supports:
                gap = points[:, 2] - (
                    np.column_stack([points[:, :2], np.ones(4)]) @ abc
                )
                if (
                    min(gap) >= -tolerance
                    and np.ptp(gap) <= tolerance
                    and polygon.buffer(tolerance).covers(footprint)
                ):
                    matched += 1
                    break
        results.append(
            {
                "anchor": list(anchor),
                "supported_tables": matched,
                "consistent": bool(tables) and matched == len(tables),
            }
        )
    accepted = [r["anchor"] for r in results if r["consistent"]]
    return {
        "status": (
            "resolved"
            if len(accepted) == 1
            else "ambiguous" if accepted else "inconsistent"
        ),
        "accepted_anchor": accepted[0] if len(accepted) == 1 else None,
        "hypotheses": results,
        "tolerance_m": tolerance,
        "evidence": "independent supporting mesh-face containment and parallel height clearance",
    }


def scene_equivalence(saved: Scene, embedded: Scene):
    if saved.frame != "refGeographical" or embedded.frame != "refGeographical":
        return {
            "world_equivalent_all_anchors": False,
            "status": "unavailable",
            "reason": "source_frame_not_established",
        }
    unresolved = [m for m in saved.meshes + embedded.meshes if m.unresolved_transform]
    if unresolved:
        return {
            "world_equivalent_all_anchors": False,
            "status": "unavailable",
            "reason": "missing_or_unproved_mesh_transform",
            "source_fields": sorted(
                {k for m in unresolved for k in m.unresolved_transform}
            ),
        }

    def digest(scene, anchor):
        geometry = {
            "tables": sorted(
                sorted(tuple(np.round(v, 3)) for v in t.corners(anchor))
                for t in scene.tables
            ),
            "meshes": sorted(m.world_signature() for m in scene.meshes),
        }
        return sha256(json.dumps(geometry, sort_keys=True).encode()).hexdigest()

    # If equality holds under every discrete common anchor, it does not depend
    # on selecting an unresolved TypeOrigine interpretation.
    checks = [digest(saved, a) == digest(embedded, a) for a in ANCHORS]
    codes = {t.anchor_code for t in saved.tables}
    embedded_codes = {t.anchor_code for t in embedded.tables}
    return {
        "world_equivalent_all_anchors": all(checks) and codes == embedded_codes,
        "common_anchor_checks": checks,
        "anchor_codes_match": codes == embedded_codes,
        "precision_m": 0.001,
        "module_metadata_compared": False,
        "reason": "geometry only; added module metadata is checked separately",
    }


def prism_request(mesh: Mesh, *, label):
    """Only a proven vertical prism maps to the existing extrusion request."""
    if mesh.topology() != "vertical_prism":
        raise SourceError("mesh is not exactly representable by a native extrusion")
    low = float(mesh.vertices[:, 2].min())
    high = float(mesh.vertices[:, 2].max())
    bottoms = [
        Polygon(mesh.vertices[f][:, :2])
        for f in mesh.faces
        if np.all(abs(mesh.vertices[f, 2] - low) <= 0.002)
    ]
    footprint = unary_union(bottoms)
    return {
        "method": "POST",
        "path": "/api/projects/{project_id}/obstacles/extrusion",
        "json": {
            "name": f"{label} obstacle {mesh.object_id}",
            "vertices": [list(p) for p in list(footprint.exterior.coords)[:-1]],
            "base_elevation_m": low,
            "height_m": high - low,
            "on_module_conflict": "reject",
            "dry_run": True,
        },
    }
