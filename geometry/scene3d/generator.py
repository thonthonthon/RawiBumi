"""Generate a deterministic, non-authoritative 3-D verification scene."""

from __future__ import annotations

import hashlib
import math
from typing import Any, Mapping

from geometry.scene.serialization import canonical_scene_json
from geometry.scene.surface_plane import module_center_z

from .height import (
    HEIGHT_MODEL_VERSION,
    Point3D,
    SurfacePlane,
    bounds3d,
    module_axes,
    module_corners,
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def generation_input_hash(scene: Mapping[str, Any]) -> str:
    return _sha256_text(
        HEIGHT_MODEL_VERSION + "\n" + canonical_scene_json(dict(scene))
    )


def _finding(
    severity: str,
    code: str,
    entity_type: str,
    entity_id: str | None,
    message: str,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "message": message,
    }


def _field_map(scene: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(field["pv_field_id"]): field
        for field in scene.get("pv_fields", [])
    }


def _surface_map(scene: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(surface["surface_id"]): surface
        for surface in scene.get("surfaces", [])
    }


def _surface_geometry(
    surface: Mapping[str, Any],
) -> tuple[dict[str, Any], SurfacePlane, list[Point3D]]:
    plane = SurfacePlane.from_surface(surface)
    vertices_2d = [
        (float(point[0]), float(point[1]))
        for point in surface["boundary_2d"]["vertices"]
    ]
    vertices_3d = [plane.lift(point) for point in vertices_2d]
    holes_2d = [
        [(float(point[0]), float(point[1])) for point in ring]
        for ring in surface["boundary_2d"].get("holes", [])
    ]
    holes_3d = [
        [plane.lift(point) for point in ring]
        for ring in holes_2d
    ]
    geometry = {
        "surface_id": str(surface["surface_id"]),
        "scene_object_id": str(surface["scene_object_id"]),
        "surface_type": str(surface["surface_type"]),
        "status": "resolved",
        "plane": plane.to_mapping(),
        "boundary_vertices_3d": [list(point) for point in vertices_3d],
        "holes_3d": [
            [list(point) for point in ring]
            for ring in holes_3d
        ],
        "visible": bool(surface.get("visible", True)),
    }
    flattened_holes = [point for ring in holes_3d for point in ring]
    return geometry, plane, vertices_3d + flattened_holes


def _unresolved_surface(
    surface: Mapping[str, Any],
    message: str,
) -> dict[str, Any]:
    return {
        "surface_id": str(surface.get("surface_id", "")),
        "scene_object_id": str(surface.get("scene_object_id", "")),
        "surface_type": str(surface.get("surface_type", "reference")),
        "status": "unresolved",
        "plane": None,
        "boundary_vertices_3d": [],
        "holes_3d": [],
        "visible": bool(surface.get("visible", True)),
        "unresolved_reason": message,
    }


def _obstacle_geometry(
    obstacle: Mapping[str, Any],
) -> tuple[dict[str, Any], list[Point3D]]:
    if obstacle.get("obstacle_type") == "imported_mesh" and "mesh" in obstacle:
        from geometry.scene.mesh import resolve_mesh
        mesh = resolve_mesh(obstacle)
        geometry = {
            "obstacle_id": str(obstacle["obstacle_id"]),
            "scene_object_id": str(obstacle["scene_object_id"]),
            "obstacle_type": "imported_mesh", "status": "resolved",
            "mesh": mesh, "visible": bool(obstacle.get("visible", True)),
            "shading_enabled": bool(obstacle["shading_enabled"]),
        }
        return geometry, [tuple(p) for p in mesh["vertices_3d"]]
    base = float(obstacle["base_elevation_m"])
    height = float(obstacle["height_m"])
    if height < 0.0:
        raise ValueError("obstacle height_m must be non-negative")
    footprint = [
        (float(point[0]), float(point[1]))
        for point in obstacle["footprint"]["vertices"]
    ]
    holes = [
        [(float(point[0]), float(point[1])) for point in ring]
        for ring in obstacle["footprint"].get("holes", [])
    ]
    base_vertices = [(x, y, base) for x, y in footprint]
    top_vertices = [(x, y, base + height) for x, y in footprint]
    base_holes = [
        [(x, y, base) for x, y in ring]
        for ring in holes
    ]
    top_holes = [
        [(x, y, base + height) for x, y in ring]
        for ring in holes
    ]
    geometry = {
        "obstacle_id": str(obstacle["obstacle_id"]),
        "scene_object_id": str(obstacle["scene_object_id"]),
        "obstacle_type": str(obstacle["obstacle_type"]),
        "status": "resolved",
        "base_elevation_m": base,
        "height_m": height,
        "base_vertices_3d": [list(point) for point in base_vertices],
        "top_vertices_3d": [list(point) for point in top_vertices],
        "base_holes_3d": [
            [list(point) for point in ring]
            for ring in base_holes
        ],
        "top_holes_3d": [
            [list(point) for point in ring]
            for ring in top_holes
        ],
        "visible": bool(obstacle.get("visible", True)),
        "shading_enabled": bool(obstacle.get("shading_enabled", True)),
    }
    flattened_holes = [
        point
        for ring in base_holes + top_holes
        for point in ring
    ]
    return geometry, base_vertices + top_vertices + flattened_holes


def _reference_geometry(
    reference: Mapping[str, Any],
) -> tuple[dict[str, Any], list[Point3D]]:
    elevation = float(reference.get("base_elevation_m", 0.0))
    points = [
        (float(point[0]), float(point[1]), elevation)
        for point in reference["vertices"]
    ]
    geometry = {
        "reference_line_id": str(reference["reference_line_id"]),
        "scene_object_id": str(reference["scene_object_id"]),
        "line_type": str(reference["line_type"]),
        "vertices_3d": [list(point) for point in points],
        "visible": bool(reference.get("visible", True)),
    }
    return geometry, points


def _module_geometry(
    module: Mapping[str, Any],
    field: Mapping[str, Any],
    plane: SurfacePlane,
) -> tuple[dict[str, Any], list[Point3D], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    field_id = str(field["pv_field_id"])
    module_id = str(module["module_instance_id"])
    footprint = field.get("module_footprint")
    if not footprint:
        raise ValueError(
            "PV field has no stored module_footprint; physical module geometry is unresolved"
        )

    physical_width = float(footprint["physical_width_m"])
    physical_height = float(footprint["physical_height_m"])
    orientation = str(footprint["orientation"])
    if orientation == "portrait":
        plane_width = physical_width
        plane_height = physical_height
    elif orientation == "landscape":
        plane_width = physical_height
        plane_height = physical_width
    else:
        raise ValueError("unsupported module footprint orientation")
    if min(physical_width, physical_height, plane_width, plane_height) <= 0.0:
        raise ValueError("module physical dimensions must be positive")

    x = float(module["transform"]["position_x_m"])
    y = float(module["transform"]["position_y_m"])
    mounting_height = float(field["mounting_height_m"])
    if mounting_height < 0.0:
        findings.append(
            _finding(
                "warning",
                "negative_mounting_height",
                "module_instance",
                module_id,
                "PV field mounting_height_m is negative; module center is below the support plane datum.",
            )
        )

    support_z = plane.elevation_at(x, y)
    expected_center_z = module_center_z(
        plane, x, y, mounting_height, field=field,
        table_row_offset=(module.get("metadata") or {}).get("table_row_offset", 0),
    )
    canonical_center_z = float(module["transform"]["position_z_m"])
    center_z_residual = canonical_center_z - expected_center_z
    if abs(center_z_residual) > 1e-9:
        findings.append(
            _finding(
                "error",
                "module_center_z_inconsistent",
                "module_instance",
                module_id,
                (
                    "Canonical ModuleInstance.position_z_m does not equal "
                    "support-plane elevation at module XY plus mounting_height_m; "
                    f"residual is {center_z_residual:.9f} m."
                ),
            )
        )
    center: Point3D = (x, y, canonical_center_z)
    azimuth = float(
        module["transform"].get(
            "rotation_z_deg", field["azimuth_deg"]
        )
    ) % 360.0
    tilt = float(field["tilt_deg"])
    row_axis, downhill_axis, normal = module_axes(azimuth, tilt)
    corners = module_corners(
        center,
        plane_width,
        plane_height,
        azimuth,
        tilt,
    )
    plan_projection_width = plane_width
    plan_projection_height = plane_height * math.cos(math.radians(tilt))
    stored_plan_width = footprint.get("plan_projection_width_m")
    stored_plan_height = footprint.get("plan_projection_height_m")
    if (
        stored_plan_width is not None
        and abs(float(stored_plan_width) - plan_projection_width) > 1e-9
    ) or (
        stored_plan_height is not None
        and abs(float(stored_plan_height) - plan_projection_height) > 1e-9
    ):
        findings.append(
            _finding(
                "error",
                "module_plan_projection_inconsistent",
                "module_instance",
                module_id,
                "Stored module plan projection does not match physical dimensions and tilt.",
            )
        )

    clearances = [
        corner[2] - plane.elevation_at(corner[0], corner[1])
        for corner in corners
    ]
    minimum_clearance = min(clearances)
    maximum_clearance = max(clearances)
    if minimum_clearance < -1e-9:
        findings.append(
            _finding(
                "error",
                "module_intersects_support_plane",
                "module_instance",
                module_id,
                (
                    "Resolved module plane penetrates its support surface; "
                    f"minimum vertical clearance is {minimum_clearance:.6f} m."
                ),
            )
        )

    geometry = {
        "module_instance_id": module_id,
        "pv_field_id": field_id,
        "module_definition_revision_id": str(
            module["module_definition_revision_id"]
        ),
        "support_surface_id": str(field["support_surface_id"]),
        "status": "resolved",
        "enabled": bool(module.get("enabled", True)),
        "center_xyz": list(center),
        "canonical_center_z_m": canonical_center_z,
        "expected_center_z_m": expected_center_z,
        "center_z_residual_m": center_z_residual,
        "row_axis_xyz": list(row_axis),
        "downhill_axis_xyz": list(downhill_axis),
        "normal_xyz": list(normal),
        "corners_3d": [list(point) for point in corners],
        "physical_width_m": physical_width,
        "physical_height_m": physical_height,
        "plane_width_m": plane_width,
        "plane_height_m": plane_height,
        "plan_projection_width_m": plan_projection_width,
        "plan_projection_height_m": plan_projection_height,
        "plan_projection_corners_xy": [
            [point[0], point[1]] for point in corners
        ],
        "orientation": orientation,
        "azimuth_deg": azimuth,
        "tilt_deg": tilt,
        "mounting_height_m": mounting_height,
        "support_elevation_at_center_m": support_z,
        "minimum_support_clearance_m": minimum_clearance,
        "maximum_support_clearance_m": maximum_clearance,
        "row_index": int(module["row_index"]),
        "column_index": int(module["column_index"]),
        "table_index": module.get("table_index"),
    }
    return geometry, corners, findings


def _unresolved_module(
    module: Mapping[str, Any],
    field: Mapping[str, Any] | None,
    message: str,
) -> dict[str, Any]:
    return {
        "module_instance_id": str(module.get("module_instance_id", "")),
        "pv_field_id": str(module.get("pv_field_id", "")),
        "module_definition_revision_id": str(
            module.get("module_definition_revision_id", "")
        ),
        "support_surface_id": (
            str(field.get("support_surface_id"))
            if field is not None
            else None
        ),
        "status": "unresolved",
        "enabled": bool(module.get("enabled", True)),
        "center_xyz": None,
        "row_axis_xyz": None,
        "downhill_axis_xyz": None,
        "normal_xyz": None,
        "corners_3d": [],
        "physical_width_m": None,
        "physical_height_m": None,
        "plane_width_m": None,
        "plane_height_m": None,
        "orientation": (
            str((field.get("module_footprint") or {}).get("orientation"))
            if field is not None and field.get("module_footprint")
            else None
        ),
        "azimuth_deg": (
            float(field.get("azimuth_deg", 0.0))
            if field is not None
            else None
        ),
        "tilt_deg": (
            float(field.get("tilt_deg", 0.0))
            if field is not None
            else None
        ),
        "mounting_height_m": (
            float(field.get("mounting_height_m", 0.0))
            if field is not None
            else None
        ),
        "support_elevation_at_center_m": None,
        "minimum_support_clearance_m": None,
        "maximum_support_clearance_m": None,
        "row_index": int(module.get("row_index", 0)),
        "column_index": int(module.get("column_index", 0)),
        "table_index": module.get("table_index"),
        "unresolved_reason": message,
    }


def generate_scene3d(scene: Mapping[str, Any]) -> dict[str, Any]:
    """Generate deterministic 3-D verification geometry without mutating Scene."""
    source_scene = dict(scene)
    source_json = canonical_scene_json(source_scene)
    source_hash = _sha256_text(source_json)
    input_hash = generation_input_hash(source_scene)

    generated_surfaces: list[dict[str, Any]] = []
    surface_planes: dict[str, SurfacePlane] = {}
    generated_obstacles: list[dict[str, Any]] = []
    generated_references: list[dict[str, Any]] = []
    generated_modules: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    points_for_bounds: list[Point3D] = []

    for surface in sorted(
        scene.get("surfaces", []),
        key=lambda item: str(item.get("surface_id", "")),
    ):
        surface_id = str(surface.get("surface_id", ""))
        try:
            geometry, plane, points = _surface_geometry(surface)
        except Exception as exc:
            message = str(exc)
            generated_surfaces.append(_unresolved_surface(surface, message))
            findings.append(
                _finding(
                    "error",
                    "surface_height_unresolved",
                    "surface",
                    surface_id,
                    message,
                )
            )
            continue
        generated_surfaces.append(geometry)
        surface_planes[surface_id] = plane
        points_for_bounds.extend(points)

    for obstacle in sorted(
        scene.get("obstacles", []),
        key=lambda item: str(item.get("obstacle_id", "")),
    ):
        obstacle_id = str(obstacle.get("obstacle_id", ""))
        try:
            geometry, points = _obstacle_geometry(obstacle)
        except Exception as exc:
            findings.append(
                _finding(
                    "error",
                    "obstacle_height_unresolved",
                    "obstacle",
                    obstacle_id,
                    str(exc),
                )
            )
            continue
        generated_obstacles.append(geometry)
        points_for_bounds.extend(points)

    for reference in sorted(
        scene.get("reference_lines", []),
        key=lambda item: str(item.get("reference_line_id", "")),
    ):
        geometry, points = _reference_geometry(reference)
        generated_references.append(geometry)
        points_for_bounds.extend(points)

    fields = _field_map(scene)
    for module in sorted(
        scene.get("module_instances", []),
        key=lambda item: str(item.get("module_instance_id", "")),
    ):
        module_id = str(module.get("module_instance_id", ""))
        field_id = str(module.get("pv_field_id", ""))
        field = fields.get(field_id)
        if field is None:
            message = f"PV field not found: {field_id}"
            generated_modules.append(
                _unresolved_module(module, None, message)
            )
            findings.append(
                _finding(
                    "error",
                    "module_field_unresolved",
                    "module_instance",
                    module_id,
                    message,
                )
            )
            continue

        if field.get("field_kind") == "explicit_layout":
            from geometry.pvfield.explicit import explicit_module_geometry
            try:
                geometry, points, module_findings = explicit_module_geometry(module, field, source_scene.get("surfaces", []))
                generated_modules.append(geometry)
                points_for_bounds.extend(points)
                findings.extend(module_findings)
            except (ValueError, KeyError, TypeError) as exc:
                generated_modules.append(_unresolved_module(module, field, str(exc)))
                findings.append(_finding("error", "module_geometry_unresolved", "module_instance", module_id, str(exc)))
            continue
        support_id = str(field.get("support_surface_id", ""))
        plane = surface_planes.get(support_id)
        if plane is None:
            message = f"Support surface height unresolved: {support_id}"
            generated_modules.append(
                _unresolved_module(module, field, message)
            )
            findings.append(
                _finding(
                    "error",
                    "module_support_unresolved",
                    "module_instance",
                    module_id,
                    message,
                )
            )
            continue

        try:
            geometry, points, module_findings = _module_geometry(
                module, field, plane
            )
        except Exception as exc:
            message = str(exc)
            generated_modules.append(
                _unresolved_module(module, field, message)
            )
            findings.append(
                _finding(
                    "warning",
                    "module_geometry_unresolved",
                    "module_instance",
                    module_id,
                    message,
                )
            )
            continue
        generated_modules.append(geometry)
        points_for_bounds.extend(points)
        findings.extend(module_findings)

    findings.sort(
        key=lambda item: (
            {"error": 0, "warning": 1, "info": 2}[item["severity"]],
            item["code"],
            item["entity_type"],
            item["entity_id"] or "",
            item["message"],
        )
    )

    return {
        "schema_name": "GeneratedScene3D",
        "schema_version": "0.1",
        "generator_version": HEIGHT_MODEL_VERSION,
        "authority": "derived_verification_only",
        "editable": False,
        "mesh_editing_supported": False,
        "source_scene_id": str(scene["scene_id"]),
        "source_scene_revision_id": str(scene["revision_id"]),
        "coordinate_system_id": str(scene["coordinate_system_id"]),
        "source_scene_hash": source_hash,
        "generation_input_hash": input_hash,
        "scene_3d_id": (
            f"{scene['scene_id']}:{scene['revision_id']}:{HEIGHT_MODEL_VERSION}"
        ),
        "surfaces": generated_surfaces,
        "obstacles": generated_obstacles,
        "reference_lines": generated_references,
        "modules": generated_modules,
        "bounds_3d": bounds3d(points_for_bounds),
        "finding_count": len(findings),
        "findings": findings,
    }
