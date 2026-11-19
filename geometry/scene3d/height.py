"""Deterministic height/plane math for Phase 4.4+ 3-D verification."""

from __future__ import annotations

import math
from typing import Any, Sequence

from geometry.scene.surface_plane import (
    Point3D,
    SurfacePlane,
    azimuth_direction,
    row_direction,
)


HEIGHT_MODEL_VERSION = "opensimpv-height3d-0.2"


def _finite(name: str, value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def module_axes(
    azimuth_deg: float,
    tilt_deg: float,
) -> tuple[Point3D, Point3D, Point3D]:
    """Return horizontal row axis, module-plane downhill axis, upward normal."""
    tilt = _finite("tilt_deg", tilt_deg)
    if tilt < 0.0 or tilt > 90.0:
        raise ValueError("module tilt_deg must satisfy 0 <= tilt <= 90")
    azimuth = _finite("azimuth_deg", azimuth_deg) % 360.0

    row_x, row_y = row_direction(azimuth)
    down_x, down_y = azimuth_direction(azimuth)
    cosine = math.cos(math.radians(tilt))
    sine = math.sin(math.radians(tilt))

    row_axis = (row_x, row_y, 0.0)
    downhill_axis = (down_x * cosine, down_y * cosine, -sine)
    normal = (down_x * sine, down_y * sine, cosine)
    return row_axis, downhill_axis, normal


def module_corners(
    center_xyz: Point3D,
    physical_width_m: float,
    physical_height_m: float,
    azimuth_deg: float,
    tilt_deg: float,
) -> list[Point3D]:
    width = _finite("physical_width_m", physical_width_m)
    height = _finite("physical_height_m", physical_height_m)
    if width <= 0.0 or height <= 0.0:
        raise ValueError("module physical dimensions must be positive")

    row_axis, downhill_axis, _ = module_axes(azimuth_deg, tilt_deg)
    cx, cy, cz = center_xyz

    def point(row_sign: float, down_sign: float) -> Point3D:
        return (
            cx
            + row_sign * width / 2.0 * row_axis[0]
            + down_sign * height / 2.0 * downhill_axis[0],
            cy
            + row_sign * width / 2.0 * row_axis[1]
            + down_sign * height / 2.0 * downhill_axis[1],
            cz
            + row_sign * width / 2.0 * row_axis[2]
            + down_sign * height / 2.0 * downhill_axis[2],
        )

    return [
        point(-1.0, -1.0),
        point(1.0, -1.0),
        point(1.0, 1.0),
        point(-1.0, 1.0),
    ]


def distance3d(first: Point3D, second: Point3D) -> float:
    return math.sqrt(
        (second[0] - first[0]) ** 2
        + (second[1] - first[1]) ** 2
        + (second[2] - first[2]) ** 2
    )


def bounds3d(points: Sequence[Point3D]) -> dict[str, list[float]] | None:
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    return {
        "min_xyz": [min(xs), min(ys), min(zs)],
        "max_xyz": [max(xs), max(ys), max(zs)],
    }
