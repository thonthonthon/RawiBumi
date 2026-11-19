"""Canonical support-surface plane semantics shared by 2-D/3-D geometry."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from .geometry2d import Point2D, polygon_centroid


Point3D = tuple[float, float, float]
SURFACE_PLANE_MODEL_VERSION = "opensimpv-surface-plane-0.1"


def _finite(name: str, value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def azimuth_direction(azimuth_deg: float) -> Point2D:
    """Horizontal unit vector toward engineering azimuth."""
    angle = math.radians(_finite("azimuth_deg", azimuth_deg) % 360.0)
    return math.sin(angle), math.cos(angle)


def row_direction(azimuth_deg: float) -> Point2D:
    """Horizontal +row direction, 90 degrees clockwise from facing +Y."""
    angle = math.radians(_finite("azimuth_deg", azimuth_deg) % 360.0)
    return math.cos(angle), -math.sin(angle)


@dataclass(frozen=True)
class SurfacePlane:
    """Canonical Z resolver for a planar Scene surface.

    boundary_2d and all XY inputs are horizontal engineering-plan coordinates.
    base_elevation_m is the plane elevation at the configured reference XY.
    """

    surface_id: str
    reference_x_m: float
    reference_y_m: float
    reference_elevation_m: float
    slope_deg: float
    azimuth_deg: float
    elevation_reference_mode: str

    @classmethod
    def from_surface(cls, surface: Mapping[str, Any]) -> "SurfacePlane":
        slope = _finite("slope_deg", surface.get("slope_deg", 0.0))
        if slope < 0.0 or slope >= 90.0:
            raise ValueError("surface slope_deg must satisfy 0 <= slope < 90")
        vertices = [
            (float(point[0]), float(point[1]))
            for point in surface["boundary_2d"]["vertices"]
        ]
        if len(vertices) < 3:
            raise ValueError("surface boundary requires at least three vertices")
        reference = surface.get("elevation_reference")
        if reference is None or reference.get("mode") == "boundary_centroid":
            reference_mode = "boundary_centroid"
            ref_x, ref_y = polygon_centroid(vertices)
        elif reference.get("mode") == "explicit_xy":
            reference_mode = "explicit_xy"
            ref_x = _finite("elevation_reference.x_m", reference["x_m"])
            ref_y = _finite("elevation_reference.y_m", reference["y_m"])
        else:
            raise ValueError("unsupported surface elevation_reference mode")
        return cls(
            surface_id=str(surface["surface_id"]),
            reference_x_m=ref_x,
            reference_y_m=ref_y,
            reference_elevation_m=_finite(
                "base_elevation_m", surface.get("base_elevation_m", 0.0)
            ),
            slope_deg=slope,
            azimuth_deg=_finite(
                "azimuth_deg", surface.get("azimuth_deg", 0.0)
            ) % 360.0,
            elevation_reference_mode=reference_mode,
        )

    @property
    def downhill_xy(self) -> Point2D:
        return azimuth_direction(self.azimuth_deg)

    @property
    def normal_xyz(self) -> Point3D:
        slope = math.radians(self.slope_deg)
        dx, dy = self.downhill_xy
        return (
            math.sin(slope) * dx,
            math.sin(slope) * dy,
            math.cos(slope),
        )

    def elevation_at(self, x_m: float, y_m: float) -> float:
        x = _finite("x_m", x_m)
        y = _finite("y_m", y_m)
        dx, dy = self.downhill_xy
        projected_downhill = (
            (x - self.reference_x_m) * dx
            + (y - self.reference_y_m) * dy
        )
        return (
            self.reference_elevation_m
            - math.tan(math.radians(self.slope_deg)) * projected_downhill
        )

    def lift(self, point: Point2D) -> Point3D:
        return (
            float(point[0]),
            float(point[1]),
            self.elevation_at(point[0], point[1]),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "reference_point_xy_m": [
                self.reference_x_m,
                self.reference_y_m,
            ],
            "reference_elevation_m": self.reference_elevation_m,
            "slope_deg": self.slope_deg,
            "azimuth_deg": self.azimuth_deg,
            "normal_xyz": list(self.normal_xyz),
            "elevation_reference_mode": self.elevation_reference_mode,
            "coordinate_basis": "horizontal_engineering_xy",
            "model_version": SURFACE_PLANE_MODEL_VERSION,
        }


def module_center_z(
    surface: Mapping[str, Any],
    x_m: float,
    y_m: float,
    mounting_height_m: float,
    *, field: Mapping[str, Any] | None = None, table_row_offset: int = 0,
) -> float:
    """Canonical module-center Z using a vertical mounting-height offset."""
    mounting = _finite("mounting_height_m", mounting_height_m)
    plane = surface if isinstance(surface, SurfacePlane) else SurfacePlane.from_surface(surface)
    if table_row_offset:
        if field is None or type(table_row_offset) is not int or table_row_offset < 0:
            raise ValueError("table row offset requires a field and a nonnegative integer")
        footprint = field["module_footprint"]
        step = float(footprint["packed_height_m"]) + float(field["module_gap_y_m"])
        beta = math.radians(float(field["tilt_deg"]))
        dx, dy = azimuth_direction(float(field["azimuth_deg"]))
        distance = table_row_offset * step
        return plane.elevation_at(x_m + distance * math.cos(beta) * dx,
                                  y_m + distance * math.cos(beta) * dy) + mounting + distance * math.sin(beta)
    return plane.elevation_at(x_m, y_m) + mounting


def module_position_z_basis(module: Mapping[str, Any]) -> str:
    return ("table_plane_from_front_row.v1" if (module.get("metadata") or {}).get("table_row_offset", 0)
            else "support_plane_plus_vertical_mounting_height")


def synchronize_scene_module_center_z(scene: dict[str, Any]) -> list[str]:
    """Recompute canonical module-center Z after authoritative Scene edits.

    This is derived-coordinate maintenance, not layout redesign: module X/Y,
    identity, field membership, row/column lineage and electrical references
    are untouched.
    """
    surfaces = {
        str(item["surface_id"]): item
        for item in scene.get("surfaces", [])
    }
    fields = {
        str(item["pv_field_id"]): item
        for item in scene.get("pv_fields", [])
    }
    updated: list[str] = []
    for module in scene.get("module_instances", []):
        field = fields.get(str(module.get("pv_field_id", "")))
        if field is None or field.get("field_kind") == "explicit_layout":
            continue
        support = surfaces.get(str(field.get("support_surface_id", "")))
        if support is None:
            continue
        transform = module.get("transform") or {}
        if "position_x_m" not in transform or "position_y_m" not in transform:
            continue
        z = module_center_z(
            support,
            float(transform["position_x_m"]),
            float(transform["position_y_m"]),
            float(field.get("mounting_height_m", 0.0)),
            field=field, table_row_offset=(module.get("metadata") or {}).get("table_row_offset", 0),
        )
        if abs(float(transform.get("position_z_m", z)) - z) > 1e-12:
            transform["position_z_m"] = z
            updated.append(str(module.get("module_instance_id", "")))
        module.setdefault("metadata", {})[
            "position_z_basis"
        ] = module_position_z_basis(module)
    return sorted(updated)
