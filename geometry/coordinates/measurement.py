"""Dimension and bearing calculations on canonical local geometry."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .core import (
    GeographicPoint,
    LocalCoordinateSystem,
    LocalPoint,
    WorldPixelPoint,
    world_pixel_to_geographic,
)


@dataclass(frozen=True)
class SegmentMeasurement:
    """Engineering measurement between two points."""

    delta_x_m: float
    delta_y_m: float
    delta_z_m: float
    horizontal_distance_m: float
    spatial_distance_m: float
    local_azimuth_deg: float
    true_azimuth_deg: float


def _azimuth_deg(east_or_x: float, north_or_y: float) -> float:
    if abs(east_or_x) < 1e-15 and abs(north_or_y) < 1e-15:
        return 0.0
    return math.degrees(math.atan2(east_or_x, north_or_y)) % 360.0


def measure_local_segment(
    start: LocalPoint,
    end: LocalPoint,
    coordinate_system: LocalCoordinateSystem,
) -> SegmentMeasurement:
    """Measure canonical local points without involving map scale or zoom."""
    dx = end.x_m - start.x_m
    dy = end.y_m - start.y_m
    dz = end.z_m - start.z_m
    horizontal = math.hypot(dx, dy)
    spatial = math.sqrt(horizontal**2 + dz**2)

    east, north, _ = coordinate_system.local_vector_to_enu(dx, dy, dz)
    return SegmentMeasurement(
        delta_x_m=dx,
        delta_y_m=dy,
        delta_z_m=dz,
        horizontal_distance_m=horizontal,
        spatial_distance_m=spatial,
        local_azimuth_deg=_azimuth_deg(dx, dy),
        true_azimuth_deg=_azimuth_deg(east, north),
    )


def measure_geographic_segment(
    start: GeographicPoint,
    end: GeographicPoint,
    coordinate_system: LocalCoordinateSystem,
) -> SegmentMeasurement:
    """Measure map/geographic points by first resolving them into local metres."""
    return measure_local_segment(
        coordinate_system.geographic_to_local(start),
        coordinate_system.geographic_to_local(end),
        coordinate_system,
    )


def measure_world_pixel_segment(
    start: WorldPixelPoint,
    end: WorldPixelPoint,
    coordinate_system: LocalCoordinateSystem,
) -> SegmentMeasurement:
    """Measure web-map pixels through geographic then local conversion."""
    if start.zoom != end.zoom or start.tile_size_px != end.tile_size_px:
        raise ValueError("world pixel points must share zoom and tile size")
    return measure_geographic_segment(
        world_pixel_to_geographic(start),
        world_pixel_to_geographic(end),
        coordinate_system,
    )
