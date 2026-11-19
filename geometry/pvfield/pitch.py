"""Shading-free row pitch (USE1): rows spaced so the row in front casts no shadow at a design sun position."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .models import ModuleFootprint

SHADING_FREE_PITCH_BASIS = "plan_depth_plus_shadow_at_design_sun.v1"


def shading_free_row_pitch(
    module_definition: Mapping[str, Any],
    *,
    orientation: str,
    tilt_deg: float,
    design_sun_elevation_deg: float,
    sun_azimuth_offset_deg: float = 0.0,
    rows_per_table: int = 1,
    module_gap_y_m: float = 0.0,
) -> dict[str, Any]:
    """Centre-to-centre plan pitch for one-row tables.

    With the sloped row depth ``L`` (the packed module height), tilt ``β``, sun elevation ``α``
    and the angle ``γ`` between the sun and the direction the modules face, the row's top
    edge at height ``L·sin β`` throws a shadow ``L·sin β·cos γ / tan α`` along the row
    normal, so ``pitch = L·cos β + L·sin β·cos γ / tan α``. From 90° off the facing
    direction the sun lights the row from the side and the pitch is the plan depth.
    """
    elevation, offset = float(design_sun_elevation_deg), abs(float(sun_azimuth_offset_deg))
    if not math.isfinite(elevation) or not 0.0 < elevation < 90.0:
        raise ValueError("design_sun_elevation_deg must be between 0 and 90 (exclusive)")
    if not math.isfinite(offset) or offset > 180.0:
        raise ValueError("sun_azimuth_offset_deg must be within ±180")
    footprint = ModuleFootprint.from_definition(module_definition, orientation, tilt_deg)
    if type(rows_per_table) is not int or rows_per_table < 1:
        raise ValueError("rows_per_table must be a positive integer")
    if not math.isfinite(module_gap_y_m) or module_gap_y_m < 0:
        raise ValueError("module_gap_y_m must be finite and nonnegative")
    depth = (rows_per_table * footprint.packed_height_m + (rows_per_table - 1) * module_gap_y_m
             if rows_per_table > 1 else footprint.packed_height_m)
    beta = math.radians(footprint.tilt_deg)
    plan_depth = depth * math.cos(beta)
    shadow = depth * math.sin(beta) * max(math.cos(math.radians(offset)), 0.0) / math.tan(math.radians(elevation))
    return {
        "row_pitch_m": plan_depth + shadow,
        "plan_depth_m": plan_depth,
        "shadow_length_m": shadow,
        "ground_coverage_ratio": plan_depth / (plan_depth + shadow),
        "basis": SHADING_FREE_PITCH_BASIS,
        "inputs": {"module_definition_revision_id": footprint.module_definition_revision_id, "orientation": orientation,
                   "tilt_deg": footprint.tilt_deg, "design_sun_elevation_deg": elevation,
                   "sun_azimuth_offset_deg": float(sun_azimuth_offset_deg),
                   **({"rows_per_table": rows_per_table} if rows_per_table > 1 else {})},
    }
