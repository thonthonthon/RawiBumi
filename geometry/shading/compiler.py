"""Deterministic Scene -> CompiledShadingGeometry compiler for Phase 5.1.

The canonical Scene remains authoritative. This compiler deliberately reuses the
Phase-4 GeneratedScene3D height/module geometry semantics and converts that
derived verification representation into a solver-neutral shading artifact.

No shadow, ray, sky-view, ground-view, cache, or electrical-mismatch physics is
implemented here.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable, Mapping, Sequence

from geometry.scene.serialization import canonical_scene_hash
from geometry.scene.surface_plane import SurfacePlane
from geometry.scene3d import generate_scene3d

from .contract import CONTRACT_VERSION, COORDINATE_BASIS
from .serialization import canonical_geometry_payload_hash


COMPILER_ID = "rawibumi.shading_geometry_compiler.native"
COMPILER_VERSION = "0.1"

_SUPPORTED_OBSTACLE_TYPES = {
    "box",
    "cylinder",
    "extruded_polygon",
    "parapet",
    "wall",
    "pole",
    "simplified_tree",
}
_IMPORTED_MESH_TYPE = "imported_mesh"
_EPSILON = 1e-12

Point3D = tuple[float, float, float]


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _point3(value: Sequence[float]) -> Point3D:
    if len(value) != 3:
        raise ValueError("3-D point must contain exactly three coordinates")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ValueError("3-D point coordinates must be finite")
    return result  # type: ignore[return-value]


def _finding(
    severity: str,
    code: str,
    entity_id: str | None,
    message: str,
    *,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "entity_id": entity_id,
        "message": message,
        "context": dict(context or {}),
    }


def _newell_normal(vertices: Sequence[Sequence[float]]) -> Point3D:
    points = [_point3(item) for item in vertices]
    if len(points) < 3:
        raise ValueError("polygon face requires at least three vertices")

    nx = ny = nz = 0.0
    for current, following in zip(points, points[1:] + points[:1]):
        nx += (current[1] - following[1]) * (current[2] + following[2])
        ny += (current[2] - following[2]) * (current[0] + following[0])
        nz += (current[0] - following[0]) * (current[1] + following[1])

    norm = math.sqrt(nx * nx + ny * ny + nz * nz)
    if norm <= _EPSILON:
        raise ValueError("polygon face is degenerate")
    return (nx / norm, ny / norm, nz / norm)


def _polygon_area_3d(vertices: Sequence[Sequence[float]]) -> float:
    points = [_point3(item) for item in vertices]
    if len(points) < 3:
        raise ValueError("polygon requires at least three vertices")

    nx = ny = nz = 0.0
    for current, following in zip(points, points[1:] + points[:1]):
        nx += (current[1] - following[1]) * (current[2] + following[2])
        ny += (current[2] - following[2]) * (current[0] + following[0])
        nz += (current[0] - following[0]) * (current[1] + following[1])
    area = 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)
    if not math.isfinite(area) or area <= _EPSILON:
        raise ValueError("polygon area must be positive")
    return area


def _bounds3d(vertices: Iterable[Sequence[float]]) -> dict[str, list[float]]:
    points = [_point3(item) for item in vertices]
    if not points:
        raise ValueError("bounds require at least one 3-D point")
    return {
        "min_xyz": [
            min(point[0] for point in points),
            min(point[1] for point in points),
            min(point[2] for point in points),
        ],
        "max_xyz": [
            max(point[0] for point in points),
            max(point[1] for point in points),
            max(point[2] for point in points),
        ],
    }


def _signed_area_xy(vertices: Sequence[Sequence[float]]) -> float:
    points = [_point3(item) for item in vertices]
    return 0.5 * sum(
        current[0] * following[1] - following[0] * current[1]
        for current, following in zip(points, points[1:] + points[:1])
    )


def _ccw_xy(vertices: Sequence[Sequence[float]]) -> list[list[float]]:
    points = [list(_point3(item)) for item in vertices]
    if abs(_signed_area_xy(points)) <= _EPSILON:
        raise ValueError("horizontal polygon projection is degenerate")
    if _signed_area_xy(points) < 0.0:
        points.reverse()
    return points


def _face(face_id: str, vertices: Sequence[Sequence[float]]) -> dict[str, Any]:
    points = [list(_point3(item)) for item in vertices]
    return {
        "face_id": face_id,
        "vertices_3d": points,
        "normal_xyz": list(_newell_normal(points)),
    }


def _obstacle_faces(
    obstacle_id: str,
    base_vertices: Sequence[Sequence[float]],
    top_vertices: Sequence[Sequence[float]],
) -> list[dict[str, Any]]:
    if len(base_vertices) != len(top_vertices):
        raise ValueError("obstacle base/top vertex counts must match")
    if len(base_vertices) < 3:
        raise ValueError("obstacle footprint requires at least three vertices")

    base = _ccw_xy(base_vertices)
    top_by_xy = {
        (float(item[0]), float(item[1])): list(_point3(item))
        for item in top_vertices
    }
    try:
        top = [top_by_xy[(item[0], item[1])] for item in base]
    except KeyError as exc:
        raise ValueError(
            "obstacle top vertices do not align with base footprint"
        ) from exc

    height = max(point[2] for point in top) - min(point[2] for point in base)
    if abs(height) <= _EPSILON:
        return [_face(f"{obstacle_id}:top", top)]

    faces = [
        _face(f"{obstacle_id}:base", list(reversed(base))),
        _face(f"{obstacle_id}:top", top),
    ]
    for index in range(len(base)):
        following = (index + 1) % len(base)
        faces.append(
            _face(
                f"{obstacle_id}:side:{index:04d}",
                [
                    base[index],
                    base[following],
                    top[following],
                    top[index],
                ],
            )
        )
    return faces


def _polygon_centroid_xy(vertices: Sequence[Sequence[float]]) -> tuple[float, float]:
    points = [(float(item[0]), float(item[1])) for item in vertices]
    if len(points) < 3:
        raise ValueError("polygon centroid requires at least three vertices")
    cross_sum = 0.0
    x_sum = 0.0
    y_sum = 0.0
    for current, following in zip(points, points[1:] + points[:1]):
        cross = current[0] * following[1] - following[0] * current[1]
        cross_sum += cross
        x_sum += (current[0] + following[0]) * cross
        y_sum += (current[1] + following[1]) * cross
    if abs(cross_sum) <= _EPSILON:
        raise ValueError("polygon centroid is undefined for zero projected area")
    return (
        x_sum / (3.0 * cross_sum),
        y_sum / (3.0 * cross_sum),
    )


def _compiled_module_receiver(
    generated_module: Mapping[str, Any],
) -> dict[str, Any]:
    module_id = str(generated_module["module_instance_id"])
    corners = [list(_point3(item)) for item in generated_module["corners_3d"]]
    return {
        "receiver_id": f"receiver:module:{module_id}",
        "source_entity_type": "module_instance",
        "source_entity_id": module_id,
        "receiver_type": "module_plane",
        "vertices_3d": corners,
        "center_xyz": list(_point3(generated_module["center_xyz"])),
        "normal_xyz": list(_point3(generated_module["normal_xyz"])),
        "area_m2": _polygon_area_3d(corners),
        "enabled": bool(generated_module["enabled"]),
        "pv_field_id": str(generated_module["pv_field_id"]),
        "support_surface_id": (
            str(generated_module["support_surface_id"])
            if generated_module.get("support_surface_id") is not None
            else None
        ),
        "module_instance_id": module_id,
        "metadata": {
            "module_definition_revision_id": str(
                generated_module["module_definition_revision_id"]
            ),
            "row_index": int(generated_module["row_index"]),
            "column_index": int(generated_module["column_index"]),
            "table_index": generated_module.get("table_index"),
            "orientation": generated_module.get("orientation"),
            "azimuth_deg": generated_module.get("azimuth_deg"),
            "tilt_deg": generated_module.get("tilt_deg"),
        },
    }


def _compiled_module_occluder(
    generated_module: Mapping[str, Any],
) -> dict[str, Any]:
    module_id = str(generated_module["module_instance_id"])
    corners = [list(_point3(item)) for item in generated_module["corners_3d"]]
    return {
        "occluder_id": f"occluder:module:{module_id}",
        "source_entity_type": "module_instance",
        "source_entity_id": module_id,
        "geometry_type": "polygon_faces",
        "faces": [_face(f"module:{module_id}:plane", corners)],
        "bounds_3d": _bounds3d(corners),
        "shading_enabled": bool(generated_module["enabled"]),
        "metadata": {
            "occluder_class": "pv_module_plane",
            "pv_field_id": str(generated_module["pv_field_id"]),
            "support_surface_id": generated_module.get("support_surface_id"),
            "self_shading_controlled_by_configuration": True,
        },
    }


def _compiled_surface_receiver(
    source_surface: Mapping[str, Any],
    generated_surface: Mapping[str, Any],
) -> dict[str, Any]:
    surface_id = str(source_surface["surface_id"])
    holes = source_surface["boundary_2d"].get("holes", [])
    if holes:
        raise ValueError(
            "surface receiver holes are not representable by the Phase-5.0 "
            "aggregate-plane receiver contract"
        )
    vertices = [
        list(_point3(item)) for item in generated_surface["boundary_vertices_3d"]
    ]
    plane = SurfacePlane.from_surface(source_surface)
    center_xy = _polygon_centroid_xy(source_surface["boundary_2d"]["vertices"])
    center = plane.lift(center_xy)
    return {
        "receiver_id": f"receiver:surface:{surface_id}",
        "source_entity_type": "surface",
        "source_entity_id": surface_id,
        "receiver_type": "aggregate_plane",
        "vertices_3d": vertices,
        "center_xyz": list(center),
        "normal_xyz": list(plane.normal_xyz),
        "area_m2": _polygon_area_3d(vertices),
        "enabled": True,
        "pv_field_id": None,
        "support_surface_id": surface_id,
        "module_instance_id": None,
        "metadata": {
            "surface_type": str(source_surface["surface_type"]),
            "aggregate_receiver_only": True,
        },
    }


def _compiled_obstacle_occluder(
    source_obstacle: Mapping[str, Any],
    generated_obstacle: Mapping[str, Any],
) -> dict[str, Any]:
    obstacle_id = str(source_obstacle["obstacle_id"])
    if source_obstacle.get("obstacle_type") == _IMPORTED_MESH_TYPE:
        if "mesh" not in source_obstacle:
            raise ValueError("imported_mesh requires mesh vertices and faces; footprint extrusion is not accepted as a substitute")
        mesh = generated_obstacle["mesh"]
        vertices = mesh["vertices_3d"]
        faces = [_face(f"mesh:{obstacle_id}:face:{fi:06d}:triangle:{ti:04d}",
                       [vertices[index] for index in triangle])
                 for fi, record in enumerate(mesh["faces"])
                 for ti, triangle in enumerate(record["triangles"])]
        return {"occluder_id": f"occluder:obstacle:{obstacle_id}",
                "source_entity_type": "obstacle", "source_entity_id": obstacle_id,
                "geometry_type": "polygon_faces", "faces": faces,
                "bounds_3d": _bounds3d(vertices),
                "shading_enabled": bool(source_obstacle["shading_enabled"]),
                "metadata": {"obstacle_type": _IMPORTED_MESH_TYPE,
                    "compiled_from": mesh["adapter_version"],
                    "mesh_content_sha256": mesh["mesh_content_sha256"],
                    "mesh_planarity_tolerance_m": mesh["mesh_planarity_tolerance_m"],
                    "source_face_records": mesh["faces"], "topology": mesh["topology"]}}
    holes = source_obstacle["footprint"].get("holes", [])
    if holes:
        raise ValueError(
            "obstacle footprint holes are not supported by the Phase-5.1 "
            "native polygon-face compiler"
        )

    obstacle_type = str(source_obstacle["obstacle_type"])
    if obstacle_type not in _SUPPORTED_OBSTACLE_TYPES:
        raise ValueError(f"unsupported obstacle_type: {obstacle_type}")

    base = generated_obstacle["base_vertices_3d"]
    top = generated_obstacle["top_vertices_3d"]
    faces = _obstacle_faces(obstacle_id, base, top)
    face_vertices = [
        vertex for face in faces for vertex in face["vertices_3d"]
    ]
    return {
        "occluder_id": f"occluder:obstacle:{obstacle_id}",
        "source_entity_type": "obstacle",
        "source_entity_id": obstacle_id,
        "geometry_type": "polygon_faces",
        "faces": faces,
        "bounds_3d": _bounds3d(face_vertices),
        "shading_enabled": bool(source_obstacle["shading_enabled"]),
        "metadata": {
            "obstacle_type": obstacle_type,
            "compiled_from": "canonical_footprint_vertical_extrusion",
        },
    }


def compilation_input_hash(
    scene: Mapping[str, Any],
    generated_scene3d: Mapping[str, Any],
) -> str:
    """Hash every versioned dependency that defines compiled shading geometry."""
    return _sha256_json(
        {
            "contract_version": CONTRACT_VERSION,
            "compiler_id": COMPILER_ID,
            "compiler_version": COMPILER_VERSION,
            "source_scene_hash": canonical_scene_hash(dict(scene)),
            "height_model_version": generated_scene3d["generator_version"],
            "scene3d_generation_input_hash": generated_scene3d[
                "generation_input_hash"
            ],
        }
    )


def compile_shading_geometry(scene: Mapping[str, Any]) -> dict[str, Any]:
    """Compile one canonical Scene into deterministic solver-neutral geometry.

    Phase 5.1 compiles:
    - every resolved module plane as a receiver;
    - every resolved enabled/disabled module plane as an occluder record whose
      participation is controlled later by self_shading_enabled;
    - every explicitly shading_receiver surface as an aggregate receiver when
      its current polygon contract is representable without holes;
    - every native canonical obstacle as a vertical polygon-face extrusion.

    It deliberately does not infer surface-occluder enablement because the
    canonical Surface contract currently has no shading_enabled engineering
    field. Imported meshes are not approximated from their footprint.
    """
    source_scene = dict(scene)
    source_hash = canonical_scene_hash(source_scene)
    scene3d = generate_scene3d(source_scene)

    receivers: list[dict[str, Any]] = []
    occluders: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for item in scene3d.get("findings", []):
        findings.append(
            _finding(
                str(item["severity"]),
                f"scene3d.{item['code']}",
                (
                    str(item["entity_id"])
                    if item.get("entity_id") is not None
                    else None
                ),
                str(item["message"]),
                context={
                    "source": "GeneratedScene3D",
                    "entity_type": str(item["entity_type"]),
                },
            )
        )

    source_surfaces = {
        str(item["surface_id"]): item for item in source_scene.get("surfaces", [])
    }
    for generated_surface in scene3d.get("surfaces", []):
        surface_id = str(generated_surface.get("surface_id", ""))
        source_surface = source_surfaces.get(surface_id)
        if (
            source_surface is None
            or not bool(source_surface.get("shading_receiver", False))
        ):
            continue
        if generated_surface.get("status") != "resolved":
            findings.append(
                _finding(
                    "error",
                    "surface_receiver_unresolved",
                    surface_id,
                    "Surface is marked shading_receiver but its 3-D geometry is unresolved.",
                )
            )
            continue
        try:
            receivers.append(
                _compiled_surface_receiver(source_surface, generated_surface)
            )
        except Exception as exc:
            findings.append(
                _finding(
                    "error",
                    "surface_receiver_compile_failed",
                    surface_id,
                    str(exc),
                    context={"surface_type": source_surface.get("surface_type")},
                )
            )

    for generated_module in scene3d.get("modules", []):
        module_id = str(generated_module.get("module_instance_id", ""))
        if generated_module.get("status") != "resolved":
            findings.append(
                _finding(
                    "error",
                    "module_receiver_unresolved",
                    module_id,
                    "Module 3-D geometry is unresolved and cannot become a shading receiver.",
                )
            )
            continue
        try:
            receiver = _compiled_module_receiver(generated_module)
            occluder = _compiled_module_occluder(generated_module)
        except Exception as exc:
            findings.append(
                _finding(
                    "error",
                    "module_compile_failed",
                    module_id,
                    str(exc),
                )
            )
            continue
        receivers.append(receiver)
        occluders.append(occluder)

    source_obstacles = {
        str(item["obstacle_id"]): item
        for item in source_scene.get("obstacles", [])
    }
    generated_obstacles = {
        str(item["obstacle_id"]): item
        for item in scene3d.get("obstacles", [])
    }
    for obstacle_id, source_obstacle in sorted(source_obstacles.items()):
        if bool(source_obstacle.get("receiver_enabled", False)):
            findings.append(
                _finding(
                    "warning",
                    "obstacle_receiver_not_supported_phase51",
                    obstacle_id,
                    "Obstacle receiver_enabled is not compiled in Phase 5.1; "
                    "the current shading receiver contract is PV/surface oriented.",
                )
            )
        generated_obstacle = generated_obstacles.get(obstacle_id)
        if generated_obstacle is None:
            findings.append(
                _finding(
                    "error",
                    "obstacle_geometry_unresolved",
                    obstacle_id,
                    "Obstacle has no resolved GeneratedScene3D geometry.",
                )
            )
            continue
        try:
            occluders.append(
                _compiled_obstacle_occluder(
                    source_obstacle,
                    generated_obstacle,
                )
            )
        except Exception as exc:
            findings.append(
                _finding(
                    "error",
                    "obstacle_compile_failed",
                    obstacle_id,
                    str(exc),
                    context={
                        "obstacle_type": source_obstacle.get("obstacle_type"),
                    },
                )
            )

    receivers.sort(key=lambda item: item["receiver_id"])
    occluders.sort(key=lambda item: item["occluder_id"])
    findings.sort(
        key=lambda item: (
            {"error": 0, "warning": 1, "info": 2}[item["severity"]],
            item["code"],
            item["entity_id"] or "",
            item["message"],
        )
    )

    geometry_vertices: list[Sequence[float]] = []
    for receiver in receivers:
        geometry_vertices.extend(receiver["vertices_3d"])
    for occluder in occluders:
        for face in occluder["faces"]:
            geometry_vertices.extend(face["vertices_3d"])

    compiled_bounds = (
        _bounds3d(geometry_vertices) if geometry_vertices else None
    )
    geometry_payload = {
        "coordinate_basis": COORDINATE_BASIS,
        "receivers": receivers,
        "occluders": occluders,
        "bounds_3d": compiled_bounds,
    }
    geometry_hash = canonical_geometry_payload_hash(geometry_payload)
    input_hash = compilation_input_hash(source_scene, scene3d)

    return {
        "schema_name": "CompiledShadingGeometry",
        "schema_version": "0.1",
        "contract_version": CONTRACT_VERSION,
        "authority": "derived_numerical_only",
        "editable": False,
        "source_scene_id": str(source_scene["scene_id"]),
        "source_scene_revision_id": str(source_scene["revision_id"]),
        "coordinate_system_id": str(source_scene["coordinate_system_id"]),
        "coordinate_basis": COORDINATE_BASIS,
        "source_scene_hash": source_hash,
        "compiler_id": COMPILER_ID,
        "compiler_version": COMPILER_VERSION,
        "compilation_input_hash": input_hash,
        "compiled_geometry_id": (
            f"{source_scene['scene_id']}:{source_scene['revision_id']}:"
            f"{COMPILER_ID}:{COMPILER_VERSION}:{geometry_hash[:16]}"
        ),
        "geometry_payload_sha256": geometry_hash,
        "receivers": receivers,
        "occluders": occluders,
        "bounds_3d": compiled_bounds,
        "finding_count": len(findings),
        "findings": findings,
    }
