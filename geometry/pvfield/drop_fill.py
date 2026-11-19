"""Pure DEC-58 planning over the unchanged field packer's physical slots."""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping, Sequence

from shapely import STRtree
from shapely.geometry import Point, Polygon, box

from .geometry import rectangle_polygon
from .models import ModuleFootprint
from .packing import pack_field


class DropFillError(ValueError):
    def __init__(self, code: str, message: str, **parameters):
        super().__init__(message)
        self.code = code
        self.parameters = parameters


def reading_order(module):
    """One-millimetre row-major quantization, with a stable ID for coincident ties."""
    t = module["transform"]
    return (-round(float(t["position_y_m"]), 3), round(float(t["position_x_m"]), 3), str(module["module_instance_id"]))


def drop_fill(scene: Mapping[str, Any], field: Mapping[str, Any], module_definition: Mapping[str, Any],
              moved_ids: Sequence[str], dx_m: float, dy_m: float) -> dict[str, Any]:
    ids = list(moved_ids)
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("moved_ids must be nonempty and unique")
    dx, dy = float(dx_m), float(dy_m)
    if not all(math.isfinite(v) for v in (dx, dy)):
        raise ValueError("move delta must be finite")
    by_id = {str(m["module_instance_id"]): m for m in scene["module_instances"]}
    if set(ids) - by_id.keys():
        raise ValueError(f"module instances not found: {sorted(set(ids) - by_id.keys())}")
    moved = sorted((by_id[mid] for mid in ids), key=reading_order)
    if any(m["pv_field_id"] != field["pv_field_id"] for m in moved):
        raise DropFillError("drop_fill_one_field", "Fill works within one field.")
    from .explicit import assert_packable_field
    assert_packable_field(scene, field)
    support = next(s for s in scene["surfaces"] if s["surface_id"] == field["support_surface_id"])
    footprint = ModuleFootprint.from_definition(module_definition, str(field["orientation"]), float(field["tilt_deg"]))

    def polygon(module, shape, x=0., y=0.):
        t = module["transform"]
        return Polygon(rectangle_polygon((float(t["position_x_m"]) + x, float(t["position_y_m"]) + y),
            shape.plan_projection_width_m, shape.plan_projection_height_m, float(t["rotation_z_deg"])))

    translated = [polygon(m, footprint, dx, dy) for m in moved]
    centroid = Point(sum(p.centroid.x for p in translated) / len(moved), sum(p.centroid.y for p in translated) / len(moved))
    # Own-roof membership is its outer ring; holes are excluded by the packer.
    if not Polygon(support["boundary_2d"]["vertices"]).covers(centroid):
        name = str(support.get("name") or support["surface_id"])
        raise DropFillError("drop_fill_own_roof", f"Modules can only move within their own roof ({name})", name=name)
    margin = .5 * max(footprint.plan_projection_width_m, footprint.plan_projection_height_m)
    region = box(min(p.bounds[0] for p in translated) - margin, min(p.bounds[1] for p in translated) - margin,
                 max(p.bounds[2] for p in translated) + margin, max(p.bounds[3] for p in translated) + margin)
    expanded = deepcopy(dict(field))
    expanded["packing_parameters"] = deepcopy(field.get("packing_parameters") or {})
    for key in ("requested_row_count", "requested_modules_per_row"):
        expanded["packing_parameters"].pop(key, None)
    result = pack_field(deepcopy(dict(scene)), expanded, module_definition)
    fields = {f["pv_field_id"]: f for f in scene["pv_fields"]}
    occupied = []
    wanted = set(ids)
    for module in scene["module_instances"]:
        if module["module_instance_id"] in wanted:
            continue
        other_field = fields[module["pv_field_id"]]
        shape = ModuleFootprint.from_mapping(other_field["module_footprint"], fallback_tilt_deg=float(other_field["tilt_deg"]))
        occupied.append(polygon(module, shape))
    tree = STRtree(occupied) if occupied else None
    candidates = []
    for slot in result.module_instances:
        shape = polygon(slot, footprint)
        if not region.covers(shape.centroid):
            continue
        if tree is not None and any(shape.intersection(occupied[index]).area > 1e-6 for index in tree.query(shape)):
            continue
        candidates.append(slot)
    candidates.sort(key=lambda s: (
        (s["transform"]["position_x_m"] - centroid.x) ** 2 + (s["transform"]["position_y_m"] - centroid.y) ** 2,
        -s["transform"]["position_y_m"], s["transform"]["position_x_m"], s["module_instance_id"],
    ))
    chosen = sorted(candidates[:len(moved)], key=reading_order)
    if not chosen:
        raise DropFillError("drop_fill_no_slots", "No modules fit in this space.")
    placements = {}
    for module, slot in zip(moved, chosen):
        placements[str(module["module_instance_id"])] = {
            "transform": deepcopy(slot["transform"]),
            **{key: slot[key] for key in ("row_index", "column_index", "table_index")},
            "metadata": {key: slot["metadata"][key] for key in ("grid_row_index", "grid_column_index", "table_row_offset") if key in slot["metadata"]},
        }
    return {"placements": placements, "placed_ids": list(placements),
            "removed_ids": [m["module_instance_id"] for m in moved[len(chosen):]], "reasons": [],
            "region": list(region.bounds), "margin_m": margin}
