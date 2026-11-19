"""Canonical 2-D scene primitive constructors."""

from __future__ import annotations

import math
from typing import Sequence

from .geometry2d import (
    Point2D,
    normalize_winding,
    segment_length,
    validate_polygon,
)


DIMENSION_SOURCES = {
    "map_measurement",
    "imported_geometry",
    "component_database",
    "user_override",
    "field_measurement",
    "derived",
    "unknown",
}


def _validate_source(source: str) -> str:
    if source not in DIMENSION_SOURCES:
        raise ValueError(f"unsupported geometry source: {source}")
    return source


def edge_dimension_sources(
    vertices: Sequence[Point2D],
    source: str,
) -> list[dict]:
    source = _validate_source(source)
    points = [tuple(point) for point in vertices]
    return [
        {
            "edge_index": index,
            "source": source,
            "value_m": segment_length(
                points[index], points[(index + 1) % len(points)]
            ),
            "source_reference_id": None,
            "original_value_m": None,
        }
        for index in range(len(points))
    ]


def rectangle_vertices(
    origin_x_m: float,
    origin_y_m: float,
    width_m: float,
    height_m: float,
) -> list[Point2D]:
    width = float(width_m)
    height = float(height_m)
    if width <= 0.0 or height <= 0.0:
        raise ValueError("rectangle dimensions must be positive")
    x = float(origin_x_m)
    y = float(origin_y_m)
    return [
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
    ]


def circle_polygon(
    center_x_m: float,
    center_y_m: float,
    radius_m: float,
    *,
    segments: int = 32,
) -> list[Point2D]:
    radius = float(radius_m)
    if radius <= 0.0:
        raise ValueError("radius_m must be positive")
    if segments < 8:
        raise ValueError("circle polygon requires at least 8 segments")
    cx = float(center_x_m)
    cy = float(center_y_m)
    return [
        (
            cx + radius * math.cos(2.0 * math.pi * index / segments),
            cy + radius * math.sin(2.0 * math.pi * index / segments),
        )
        for index in range(segments)
    ]


def wall_footprint(
    start: Point2D,
    end: Point2D,
    width_m: float,
) -> list[Point2D]:
    width = float(width_m)
    if width <= 0.0:
        raise ValueError("wall width must be positive")
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 0.0:
        raise ValueError("wall path must have non-zero length")
    half = width / 2.0
    nx = -dy / length * half
    ny = dx / length * half
    return normalize_winding(
        [
            (start[0] + nx, start[1] + ny),
            (end[0] + nx, end[1] + ny),
            (end[0] - nx, end[1] - ny),
            (start[0] - nx, start[1] - ny),
        ]
    )


def make_surface(
    *,
    scene_id: str,
    surface_id: str,
    scene_object_id: str,
    name: str,
    surface_type: str,
    vertices: Sequence[Point2D],
    base_elevation_m: float = 0.0,
    slope_deg: float = 0.0,
    azimuth_deg: float = 0.0,
    usable_for_pv: bool = True,
    shading_receiver: bool = False,
    geometry_source: str = "user_override",
) -> dict:
    points = validate_polygon(vertices)
    return {
        "surface_id": surface_id,
        "scene_object_id": scene_object_id,
        "name": name,
        "surface_type": surface_type,
        "boundary_2d": {
            "vertices": [list(point) for point in points],
            "holes": [],
            "winding": "counterclockwise",
            "closed": True,
        },
        "base_elevation_m": float(base_elevation_m),
        "slope_deg": float(slope_deg),
        "azimuth_deg": float(azimuth_deg) % 360.0,
        "parent_surface_id": None,
        "material": None,
        "albedo": None,
        "usable_for_pv": bool(usable_for_pv),
        "shading_receiver": bool(shading_receiver),
        "visible": True,
        "locked": False,
        "selectable": True,
        "group_id": None,
        "geometry_source": _validate_source(geometry_source),
        "edge_dimension_sources": edge_dimension_sources(points, geometry_source),
        "metadata": {"scene_id": scene_id},
        "notes": None,
    }


def make_obstacle(
    *,
    scene_id: str,
    obstacle_id: str,
    scene_object_id: str,
    name: str,
    obstacle_type: str,
    vertices: Sequence[Point2D],
    base_elevation_m: float,
    height_m: float,
    dimensions: dict | None = None,
    geometry_source: str = "user_override",
) -> dict:
    points = validate_polygon(vertices)
    if height_m < 0.0:
        raise ValueError("height_m must be non-negative")
    return {
        "obstacle_id": obstacle_id,
        "scene_object_id": scene_object_id,
        "name": name,
        "obstacle_type": obstacle_type,
        "footprint": {
            "vertices": [list(point) for point in points],
            "holes": [],
            "winding": "counterclockwise",
            "closed": True,
        },
        "base_elevation_m": float(base_elevation_m),
        "height_m": float(height_m),
        "dimensions": dimensions or {},
        "shading_enabled": True,
        "receiver_enabled": False,
        "material": None,
        "visible": True,
        "locked": False,
        "selectable": True,
        "group_id": None,
        "geometry_source": _validate_source(geometry_source),
        "edge_dimension_sources": edge_dimension_sources(points, geometry_source),
        "metadata": {"scene_id": scene_id},
    }


def make_reference_line(
    *,
    scene_id: str,
    reference_line_id: str,
    scene_object_id: str,
    name: str,
    vertices: Sequence[Point2D],
    line_type: str = "reference",
    base_elevation_m: float = 0.0,
    geometry_source: str = "user_override",
) -> dict:
    points = [tuple(map(float, point)) for point in vertices]
    if len(points) < 2:
        raise ValueError("reference line requires at least two vertices")
    if any(segment_length(points[i], points[i + 1]) <= 0.0 for i in range(len(points) - 1)):
        raise ValueError("reference line contains a zero-length segment")
    if line_type not in {"reference", "construction", "dimension"}:
        raise ValueError("unsupported reference line type")
    line_sources = [
        {
            "edge_index": index,
            "source": _validate_source(geometry_source),
            "value_m": segment_length(points[index], points[index + 1]),
            "source_reference_id": None,
            "original_value_m": None,
        }
        for index in range(len(points) - 1)
    ]
    return {
        "reference_line_id": reference_line_id,
        "scene_object_id": scene_object_id,
        "name": name,
        "line_type": line_type,
        "vertices": [list(point) for point in points],
        "base_elevation_m": float(base_elevation_m),
        "visible": True,
        "locked": False,
        "selectable": True,
        "group_id": None,
        "geometry_source": _validate_source(geometry_source),
        "edge_dimension_sources": line_sources,
        "metadata": {"scene_id": scene_id},
    }
