"""Small deterministic planar-geometry helpers for Phase 4.3 PV packing."""

from __future__ import annotations

import math
from typing import Sequence

from geometry.scene.geometry2d import (
    EPSILON,
    Point2D,
    polygon_centroid,
    polygon_segments,
    project_point_to_segment,
    rotate_point_clockwise,
    segment_length,
    segments_intersect,
)


def point_on_segment(point: Point2D, start: Point2D, end: Point2D) -> bool:
    projected, distance = project_point_to_segment(point, start, end)
    return distance <= EPSILON and segment_length(projected, point) <= EPSILON


def point_in_polygon(
    point: Point2D,
    vertices: Sequence[Point2D],
    *,
    include_boundary: bool = True,
) -> bool:
    points = [tuple(map(float, item)) for item in vertices]
    if len(points) < 3:
        return False
    for start, end in polygon_segments(points):
        if point_on_segment(point, start, end):
            return include_boundary
    x, y = point
    inside = False
    previous = points[-1]
    for current in points:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection_x:
                inside = not inside
        previous = current
    return inside


def point_to_polygon_boundary_distance(
    point: Point2D,
    vertices: Sequence[Point2D],
) -> float:
    return min(
        project_point_to_segment(point, start, end)[1]
        for start, end in polygon_segments(vertices)
    )


def segment_distance(
    first_start: Point2D,
    first_end: Point2D,
    second_start: Point2D,
    second_end: Point2D,
) -> float:
    if segments_intersect(first_start, first_end, second_start, second_end):
        return 0.0
    return min(
        project_point_to_segment(first_start, second_start, second_end)[1],
        project_point_to_segment(first_end, second_start, second_end)[1],
        project_point_to_segment(second_start, first_start, first_end)[1],
        project_point_to_segment(second_end, first_start, first_end)[1],
    )


def polygons_overlap_or_touch(
    first: Sequence[Point2D],
    second: Sequence[Point2D],
) -> bool:
    first_points = [tuple(map(float, point)) for point in first]
    second_points = [tuple(map(float, point)) for point in second]
    for a1, a2 in polygon_segments(first_points):
        for b1, b2 in polygon_segments(second_points):
            if segments_intersect(a1, a2, b1, b2):
                return True
    return (
        point_in_polygon(first_points[0], second_points, include_boundary=True)
        or point_in_polygon(second_points[0], first_points, include_boundary=True)
    )


def polygon_distance(
    first: Sequence[Point2D],
    second: Sequence[Point2D],
) -> float:
    if polygons_overlap_or_touch(first, second):
        return 0.0
    return min(
        segment_distance(a1, a2, b1, b2)
        for a1, a2 in polygon_segments(first)
        for b1, b2 in polygon_segments(second)
    )


def polygon_contains_polygon(
    container: Sequence[Point2D],
    candidate: Sequence[Point2D],
    *,
    clearance_m: float = 0.0,
) -> bool:
    """Constrained simple-polygon containment with edge clearance."""
    clearance = float(clearance_m)
    if clearance < 0.0:
        raise ValueError("clearance_m must be non-negative")
    container_points = [tuple(map(float, point)) for point in container]
    candidate_points = [tuple(map(float, point)) for point in candidate]

    probes = list(candidate_points)
    for start, end in polygon_segments(candidate_points):
        probes.append(((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0))

    for probe in probes:
        if not point_in_polygon(probe, container_points, include_boundary=True):
            return False

    if clearance > 0.0:
        minimum_boundary_distance = min(
            segment_distance(candidate_start, candidate_end, boundary_start, boundary_end)
            for candidate_start, candidate_end in polygon_segments(candidate_points)
            for boundary_start, boundary_end in polygon_segments(container_points)
        )
        if minimum_boundary_distance < clearance - EPSILON:
            return False
    return True


def rectangle_polygon(
    center: Point2D,
    width_m: float,
    height_m: float,
    azimuth_deg: float,
) -> list[Point2D]:
    """Rectangle whose local +Y axis points at engineering azimuth."""
    width = float(width_m)
    height = float(height_m)
    if width <= 0.0 or height <= 0.0:
        raise ValueError("rectangle dimensions must be positive")
    local = [
        (-width / 2.0, -height / 2.0),
        (width / 2.0, -height / 2.0),
        (width / 2.0, height / 2.0),
        (-width / 2.0, height / 2.0),
    ]
    rotated = [
        rotate_point_clockwise(point, (0.0, 0.0), azimuth_deg)
        for point in local
    ]
    return [
        (center[0] + point[0], center[1] + point[1])
        for point in rotated
    ]


def scene_to_field(point: Point2D, azimuth_deg: float) -> Point2D:
    return rotate_point_clockwise(point, (0.0, 0.0), -float(azimuth_deg))


def field_to_scene(point: Point2D, azimuth_deg: float) -> Point2D:
    return rotate_point_clockwise(point, (0.0, 0.0), float(azimuth_deg))


def field_bounds(
    vertices: Sequence[Point2D],
    azimuth_deg: float,
) -> tuple[float, float, float, float]:
    transformed = [scene_to_field(point, azimuth_deg) for point in vertices]
    xs = [point[0] for point in transformed]
    ys = [point[1] for point in transformed]
    return min(xs), min(ys), max(xs), max(ys)


def edge_azimuth_deg(start: Point2D, end: Point2D) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if math.hypot(dx, dy) <= EPSILON:
        raise ValueError("edge must have non-zero length")
    return math.degrees(math.atan2(dx, dy)) % 360.0


def polygons_overlap_strict(
    first: Sequence[Point2D],
    second: Sequence[Point2D],
) -> bool:
    """Return True for positive-area overlap; edge/corner touching is allowed."""
    first_points = [tuple(map(float, point)) for point in first]
    second_points = [tuple(map(float, point)) for point in second]
    if any(
        point_in_polygon(point, second_points, include_boundary=False)
        for point in first_points
    ):
        return True
    if any(
        point_in_polygon(point, first_points, include_boundary=False)
        for point in second_points
    ):
        return True

    # Coincident rectangles/polygons can have every vertex on the opposite
    # boundary, so vertex-only tests miss their positive-area overlap.
    # Interior representative points close that case without turning ordinary
    # edge/corner contact into overlap.
    if point_in_polygon(
        polygon_centroid(first_points),
        second_points,
        include_boundary=False,
    ):
        return True
    if point_in_polygon(
        polygon_centroid(second_points),
        first_points,
        include_boundary=False,
    ):
        return True

    for a1, a2 in polygon_segments(first_points):
        for b1, b2 in polygon_segments(second_points):
            if not segments_intersect(a1, a2, b1, b2):
                continue
            # Pure touching/collinear contact is not positive-area overlap.
            if (
                point_on_segment(a1, b1, b2)
                or point_on_segment(a2, b1, b2)
                or point_on_segment(b1, a1, a2)
                or point_on_segment(b2, a1, a2)
            ):
                continue
            return True
    return False
