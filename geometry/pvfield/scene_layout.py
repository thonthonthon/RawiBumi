"""Scene-wide S1 layout integrity and packer-selected keep-out warnings.

``position_z_m`` is the module centre: packing uses surface_plane.module_center_z
and scene3d uses that position as its physical rectangle centre. The vertical
half-span is half the oriented up-slope dimension times sin(tilt): definition
height for portrait, width for landscape. No mounting structure is inferred.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from shapely import STRtree
from shapely.errors import ShapelyError
from shapely.geometry import Polygon, box

from .geometry import rectangle_polygon, polygons_overlap_or_touch
from .models import ModuleFootprint
from .packing import _resolved_exclusions
from geometry.scene.geometry2d import EPSILON


def _validate_legacy_scene_layout(
    scene: Mapping[str, Any],
    module_definitions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Report S1 overlaps/setbacks and plan-only keep-out contact.

    STRtrees restrict exact polygon operations to nearby footprints. Module
    pairs are checked across all fields, independently of support-surface ids.
    Setback warnings remain in ``conflicts``; callers decide blocking severity.
    Unresolvable entities are reported and skipped, so damaged stored bundles
    cannot prevent inspection of the remaining, resolvable geometry.
    """
    fields = {str(item["pv_field_id"]): item for item in scene.get("pv_fields", [])}
    candidates = sorted(
        (item for item in scene.get("module_instances", []) if item.get("enabled", True)),
        key=lambda item: str(item["module_instance_id"]),
    )
    footprints: dict[tuple[str, str, float], ModuleFootprint] = {}
    modules = []
    polygons = []
    heights = []
    setbacks = []
    conflicts = []

    def unresolved(code, entity, reason):
        conflicts.append({
            "code": code,
            "module_instance_id": (
                str(entity["module_instance_id"]) if code == "module_unresolved" else None
            ),
            "other_id": str(entity.get("obstacle_id") or ""),
            "pv_field_id": entity.get("pv_field_id"),
            "other_pv_field_id": None,
            "reason": reason,
        })

    for module in candidates:
        field = fields.get(str(module.get("pv_field_id")))
        if field is None:
            unresolved("module_unresolved", module, "pv_field_missing")
            continue
        definition = module_definitions.get(str(module.get("module_definition_revision_id")))
        if definition is None:
            unresolved("module_unresolved", module, "definition_missing")
            continue
        try:
            if (definition.get("capability_flags") or {}).get("layout_ready") is False:
                unresolved("module_unresolved", module, "definition_not_layout_ready")
                continue
            key = (
                str(module["module_definition_revision_id"]),
                str(field["orientation"]),
                float(field["tilt_deg"]),
            )
            if key not in footprints:
                footprints[key] = ModuleFootprint.from_definition(definition, key[1], key[2])
            footprint = footprints[key]
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            unresolved("module_unresolved", module, "module_footprint_invalid")
            continue
        try:
            transform = module["transform"]
            x, y, centre, azimuth = (
                float(transform[name]) for name in (
                    "position_x_m", "position_y_m", "position_z_m", "rotation_z_deg"
                )
            )
            setback = float((field.get("setback_configuration") or {}).get(
                "obstacle_setback_m"
            ) or 0.0)
            if not all(math.isfinite(value) for value in (x, y, centre, azimuth, setback)) or setback < 0:
                raise ValueError("invalid module geometry")
            polygon = Polygon(rectangle_polygon(
                (x, y), footprint.plan_projection_width_m,
                footprint.plan_projection_height_m, azimuth,
            ))
            if not polygon.is_valid or polygon.is_empty:
                raise ValueError("invalid module footprint")
            half_span = footprint.packed_height_m * math.sin(math.radians(key[2])) / 2.0
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError, ShapelyError):
            unresolved("module_unresolved", module, "module_geometry_invalid")
            continue
        modules.append(module)
        polygons.append(polygon)
        heights.append((centre - half_span, centre + half_span))
        setbacks.append(setback)

    def record(code, index, other_id, other_field_id=None):
        module = modules[index]
        conflicts.append({
            "code": code,
            "module_instance_id": str(module["module_instance_id"]),
            "other_id": str(other_id),
            "pv_field_id": str(module["pv_field_id"]),
            "other_pv_field_id": other_field_id,
        })

    if polygons:
        tree = STRtree(polygons)
        first, second = tree.query(polygons)
        for i, j in zip(first, second):
            if i < j and polygons[i].intersection(polygons[j]).area > 1e-6:
                record("module_module_overlap", i, modules[j]["module_instance_id"],
                       str(modules[j]["pv_field_id"]))

    obstacles = []
    obstacle_polygons = []
    obstacle_heights = []
    for obstacle in sorted(scene.get("obstacles", []), key=lambda item: str(item["obstacle_id"])):
        try:
            polygon = Polygon(obstacle["footprint"]["vertices"])
            base = float(obstacle["base_elevation_m"])
            height = float(obstacle["height_m"])
            top = base + height
            if (not polygon.is_valid or polygon.is_empty or polygon.area <= 0
                    or not all(math.isfinite(value) for value in (base, height, top)) or height < 0):
                raise ValueError("invalid obstacle geometry")
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError, ShapelyError):
            unresolved("obstacle_unresolved", obstacle, "obstacle_geometry_invalid")
            continue
        obstacles.append(obstacle)
        obstacle_polygons.append(polygon)
        obstacle_heights.append((base, top))
    if obstacle_polygons:
        tree = STRtree(obstacle_polygons)
        for i, polygon in enumerate(polygons):
            setback = setbacks[i]
            min_x, min_y, max_x, max_y = polygon.bounds
            search = box(min_x - setback, min_y - setback, max_x + setback, max_y + setback)
            for j in tree.query(search):
                obstacle = obstacles[j]
                base, top = obstacle_heights[j]
                if base > heights[i][1] or top < heights[i][0]:
                    continue
                other = obstacle_polygons[j]
                if polygon.intersection(other).area > 1e-6:
                    record("module_obstacle_overlap", i, obstacle["obstacle_id"])
                elif setback > 0.0 and polygon.distance(other) < setback - 1e-9:
                    record("module_obstacle_setback", i, obstacle["obstacle_id"])

    # Keep-outs are design exclusions, resolved with the packer's own selection
    # and contact primitive. They have neither a height check nor a setback.
    # Skip malformed legacy surfaces without altering the existing S1 findings.
    surfaces = []
    for surface in scene.get("surfaces", []):
        try:
            shape = Polygon(surface["boundary_2d"]["vertices"])
            if surface.get("surface_id") and shape.is_valid and not shape.is_empty and shape.area > 0:
                surfaces.append(surface)
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError, ShapelyError):
            continue
    supports = {str(surface["surface_id"]): surface for surface in surfaces}
    selection_scene = {**scene, "surfaces": surfaces, "obstacles": []}
    for field_id in sorted({str(module["pv_field_id"]) for module in modules}):
        field = fields[field_id]
        support = supports.get(str(field.get("support_surface_id")))
        if support is None:
            continue
        try:
            exclusions, _ = _resolved_exclusions(selection_scene, field, support)
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            continue
        if not exclusions:
            continue
        tree = STRtree([Polygon(vertices) for _, vertices in exclusions])
        for i, module in enumerate(modules):
            if str(module["pv_field_id"]) != field_id:
                continue
            min_x, min_y, max_x, max_y = polygons[i].bounds
            nearby = box(min_x - EPSILON, min_y - EPSILON, max_x + EPSILON, max_y + EPSILON)
            vertices = list(polygons[i].exterior.coords)[:-1]
            for j in tree.query(nearby):
                other_id, excluded = exclusions[j]
                if polygons_overlap_or_touch(vertices, excluded):
                    record("module_exclusion_overlap", i, other_id)

    # Physical support gaps use the S11b positive-area readiness rule. The
    # packer's stricter contact/setback policy applies only when filling.
    for i, module in enumerate(modules):
        field = fields[str(module["pv_field_id"])]
        support = supports.get(str(field.get("support_surface_id")))
        if support is None:
            continue
        for hole_index, vertices in enumerate(support["boundary_2d"].get("holes", [])):
            try:
                hole = Polygon(vertices)
                if hole.is_valid and not hole.is_empty and polygons[i].intersection(hole).area > 1e-6:
                    record("module_over_hole", i, f"{support['surface_id']}:hole:{hole_index}")
            except (ValueError, TypeError, OverflowError, ShapelyError):
                continue

    conflicts.sort(key=lambda item: (
        item["code"], item["module_instance_id"] or "", item["other_id"],
        item["pv_field_id"] or "", item["other_pv_field_id"] or "",
    ))
    return {"status": "conflict" if conflicts else "ok", "conflicts": conflicts}


def validate_scene_layout(scene, module_definitions):
    """Retain legacy S1 exactly; new kinds use their physical 3-D surfaces."""
    explicit_ids={f['pv_field_id'] for f in scene.get('pv_fields',[]) if f.get('field_kind')=='explicit_layout'}
    meshes=any(o.get('obstacle_type')=='imported_mesh' for o in scene.get('obstacles',[]))
    if not explicit_ids and not meshes:
        return _validate_legacy_scene_layout(scene,module_definitions)
    legacy={**scene,'module_instances':[m for m in scene.get('module_instances',[]) if m.get('pv_field_id') not in explicit_ids],
            'obstacles':[o for o in scene.get('obstacles',[]) if o.get('obstacle_type')!='imported_mesh']}
    conflicts=_validate_legacy_scene_layout(legacy,module_definitions)['conflicts']
    from geometry.scene.physical import validate_new_scene_geometry
    conflicts.extend(validate_new_scene_geometry(scene,module_definitions))
    conflicts.sort(key=lambda item:(item['code'],item['module_instance_id'] or '',item['other_id'],item['pv_field_id'] or '',item['other_pv_field_id'] or ''))
    return {'status':'conflict' if conflicts else 'ok','conflicts':conflicts}
