"""Deterministic planar geometry helpers for the constrained 2-D scene editor.

The module deliberately implements only the small set of operations required by
OpenSIMPV's engineering editor. It is not a general CAD kernel.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence


Point2D = tuple[float, float]
EPSILON = 1e-9


def _finite(name: str, value: float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def as_point(value: Sequence[float]) -> Point2D:
    if len(value) != 2:
        raise ValueError("2-D point must contain exactly two coordinates")
    return (_finite("x", value[0]), _finite("y", value[1]))


def segment_length(start: Point2D, end: Point2D) -> float:
    return math.hypot(end[0] - start[0], end[1] - start[1])


def segment_azimuth_deg(start: Point2D, end: Point2D) -> float:
    """Return local engineering azimuth: 0=N, 90=E, clockwise positive."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if abs(dx) < EPSILON and abs(dy) < EPSILON:
        return 0.0
    return math.degrees(math.atan2(dx, dy)) % 360.0


def signed_area(vertices: Sequence[Point2D]) -> float:
    points = [as_point(point) for point in vertices]
    if len(points) < 3:
        return 0.0
    total = 0.0
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        total += start[0] * end[1] - end[0] * start[1]
    return total / 2.0


def winding(vertices: Sequence[Point2D]) -> str:
    return "counterclockwise" if signed_area(vertices) > 0.0 else "clockwise"


def normalize_winding(
    vertices: Sequence[Point2D],
    desired: str = "counterclockwise",
) -> list[Point2D]:
    points = [as_point(point) for point in vertices]
    if desired not in {"clockwise", "counterclockwise"}:
        raise ValueError("desired winding must be clockwise or counterclockwise")
    if len(points) >= 3 and winding(points) != desired:
        points.reverse()
    return points


def polygon_segments(vertices: Sequence[Point2D]) -> list[tuple[Point2D, Point2D]]:
    points = [as_point(point) for point in vertices]
    return [
        (points[index], points[(index + 1) % len(points)])
        for index in range(len(points))
    ]


def polyline_segments(vertices: Sequence[Point2D]) -> list[tuple[Point2D, Point2D]]:
    points = [as_point(point) for point in vertices]
    return [
        (points[index], points[index + 1])
        for index in range(len(points) - 1)
    ]


def _orientation(a: Point2D, b: Point2D, c: Point2D) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (
        c[0] - a[0]
    )


def _on_segment(a: Point2D, b: Point2D, p: Point2D) -> bool:
    if abs(_orientation(a, b, p)) > EPSILON:
        return False
    return (
        min(a[0], b[0]) - EPSILON <= p[0] <= max(a[0], b[0]) + EPSILON
        and min(a[1], b[1]) - EPSILON <= p[1] <= max(a[1], b[1]) + EPSILON
    )


def segments_intersect(
    a1: Point2D,
    a2: Point2D,
    b1: Point2D,
    b2: Point2D,
) -> bool:
    o1 = _orientation(a1, a2, b1)
    o2 = _orientation(a1, a2, b2)
    o3 = _orientation(b1, b2, a1)
    o4 = _orientation(b1, b2, a2)

    if ((o1 > EPSILON and o2 < -EPSILON) or (o1 < -EPSILON and o2 > EPSILON)) and (
        (o3 > EPSILON and o4 < -EPSILON)
        or (o3 < -EPSILON and o4 > EPSILON)
    ):
        return True

    for value, start, end, point in (
        (o1, a1, a2, b1),
        (o2, a1, a2, b2),
        (o3, b1, b2, a1),
        (o4, b1, b2, a2),
    ):
        if abs(value) <= EPSILON and _on_segment(start, end, point):
            return True
    return False


def line_intersection(
    a1: Point2D,
    a2: Point2D,
    b1: Point2D,
    b2: Point2D,
    *,
    segment_only: bool = True,
) -> Point2D | None:
    """Return a unique intersection point; collinear overlap returns None."""
    x1, y1 = a1
    x2, y2 = a2
    x3, y3 = b1
    x4, y4 = b2
    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) <= EPSILON:
        return None
    det1 = x1 * y2 - y1 * x2
    det2 = x3 * y4 - y3 * x4
    px = (det1 * (x3 - x4) - (x1 - x2) * det2) / denominator
    py = (det1 * (y3 - y4) - (y1 - y2) * det2) / denominator
    point = (px, py)
    if segment_only and not (
        _on_segment(a1, a2, point) and _on_segment(b1, b2, point)
    ):
        return None
    return point


def validate_polygon(
    vertices: Sequence[Point2D],
    *,
    normalize: bool = True,
) -> list[Point2D]:
    points = [as_point(point) for point in vertices]
    if len(points) < 3:
        raise ValueError("polygon requires at least three vertices")
    if len(set(points)) < 3:
        raise ValueError("polygon requires at least three unique vertices")
    edges = polygon_segments(points)
    for first_index, first in enumerate(edges):
        for second_index in range(first_index + 1, len(edges)):
            second = edges[second_index]
            if second_index in {
                first_index,
                (first_index + 1) % len(edges),
                (first_index - 1) % len(edges),
            }:
                continue
            if first_index == 0 and second_index == len(edges) - 1:
                continue
            if segments_intersect(first[0], first[1], second[0], second[1]):
                raise ValueError("polygon must not self-intersect")
    if abs(signed_area(points)) <= EPSILON:
        raise ValueError("polygon area must be non-zero")
    if normalize:
        return normalize_winding(points, "counterclockwise")
    return points


def project_point_to_segment(
    point: Point2D,
    start: Point2D,
    end: Point2D,
) -> tuple[Point2D, float]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator <= EPSILON:
        projection = start
    else:
        t = (
            (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
        ) / denominator
        t = min(1.0, max(0.0, t))
        projection = (start[0] + t * dx, start[1] + t * dy)
    return projection, segment_length(point, projection)


def bounding_box(points: Iterable[Point2D]) -> tuple[float, float, float, float]:
    resolved = [as_point(point) for point in points]
    if not resolved:
        raise ValueError("bounding box requires at least one point")
    xs = [point[0] for point in resolved]
    ys = [point[1] for point in resolved]
    return min(xs), min(ys), max(xs), max(ys)


def polygon_centroid(vertices: Sequence[Point2D]) -> Point2D:
    points = [as_point(point) for point in vertices]
    area = signed_area(points)
    if abs(area) <= EPSILON:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
    cx = 0.0
    cy = 0.0
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        cross = start[0] * end[1] - end[0] * start[1]
        cx += (start[0] + end[0]) * cross
        cy += (start[1] + end[1]) * cross
    scale = 1.0 / (6.0 * area)
    return cx * scale, cy * scale


def translate_points(
    points: Sequence[Point2D],
    dx_m: float,
    dy_m: float,
) -> list[Point2D]:
    dx = _finite("dx_m", dx_m)
    dy = _finite("dy_m", dy_m)
    return [(point[0] + dx, point[1] + dy) for point in points]


def rotate_point_clockwise(
    point: Point2D,
    origin: Point2D,
    angle_deg: float,
) -> Point2D:
    angle = math.radians(_finite("angle_deg", angle_deg))
    dx = point[0] - origin[0]
    dy = point[1] - origin[1]
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return (
        origin[0] + dx * cosine + dy * sine,
        origin[1] - dx * sine + dy * cosine,
    )


def rotate_points_clockwise(
    points: Sequence[Point2D],
    origin: Point2D,
    angle_deg: float,
) -> list[Point2D]:
    return [
        rotate_point_clockwise(point, origin, angle_deg) for point in points
    ]


def mirror_point(
    point: Point2D,
    line_start: Point2D,
    line_end: Point2D,
) -> Point2D:
    dx = line_end[0] - line_start[0]
    dy = line_end[1] - line_start[1]
    denominator = dx * dx + dy * dy
    if denominator <= EPSILON:
        raise ValueError("mirror line must have non-zero length")
    t = (
        (point[0] - line_start[0]) * dx
        + (point[1] - line_start[1]) * dy
    ) / denominator
    projection = (line_start[0] + t * dx, line_start[1] + t * dy)
    return (
        2.0 * projection[0] - point[0],
        2.0 * projection[1] - point[1],
    )


def mirror_points(
    points: Sequence[Point2D],
    line_start: Point2D,
    line_end: Point2D,
) -> list[Point2D]:
    return [mirror_point(point, line_start, line_end) for point in points]


def _edge_indices(count: int, edge_index: int, closed: bool) -> tuple[int, int]:
    edge_count = count if closed else count - 1
    if edge_index < 0 or edge_index >= edge_count:
        raise IndexError("edge_index is outside geometry")
    return edge_index, (edge_index + 1) % count


def set_edge_length(
    vertices: Sequence[Point2D],
    edge_index: int,
    length_m: float,
    *,
    preserve: str = "start",
    closed: bool = True,
) -> list[Point2D]:
    length = _finite("length_m", length_m)
    if length <= 0.0:
        raise ValueError("length_m must be positive")
    points = [as_point(point) for point in vertices]
    start_index, end_index = _edge_indices(len(points), edge_index, closed)
    if preserve == "rectangle":
        if not closed or len(points) != 4:
            raise ValueError("preserve rectangle needs a rectangle")
        unit_edges = []
        for index, point in enumerate(points):
            following = points[(index + 1) % 4]
            size = segment_length(point, following)
            if size <= EPSILON:
                raise ValueError("preserve rectangle needs a rectangle")
            unit_edges.append(((following[0] - point[0]) / size,
                               (following[1] - point[1]) / size))
        for index, (x, y) in enumerate(unit_edges):
            nx, ny = unit_edges[(index + 1) % 4]
            if abs(x * nx + y * ny) > EPSILON:
                raise ValueError("preserve rectangle needs a rectangle")
    start = points[start_index]
    end = points[end_index]
    current = segment_length(start, end)
    if current <= EPSILON:
        raise ValueError("cannot edit dimension of zero-length edge")
    ux = (end[0] - start[0]) / current
    uy = (end[1] - start[1]) / current

    if preserve == "start":
        points[end_index] = (start[0] + ux * length, start[1] + uy * length)
    elif preserve == "end":
        points[start_index] = (end[0] - ux * length, end[1] - uy * length)
    elif preserve == "midpoint":
        midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        half = length / 2.0
        points[start_index] = (midpoint[0] - ux * half, midpoint[1] - uy * half)
        points[end_index] = (midpoint[0] + ux * half, midpoint[1] + uy * half)
    elif preserve == "rectangle":
        dx, dy = (length - current) * ux, (length - current) * uy
        for index in (end_index, (edge_index + 2) % 4):
            points[index] = (points[index][0] + dx, points[index][1] + dy)
    else:
        raise ValueError("preserve must be start, end, midpoint, or rectangle")
    return points


def set_edge_azimuth(
    vertices: Sequence[Point2D],
    edge_index: int,
    azimuth_deg: float,
    *,
    preserve: str = "start",
    closed: bool = True,
) -> list[Point2D]:
    points = [as_point(point) for point in vertices]
    start_index, end_index = _edge_indices(len(points), edge_index, closed)
    start = points[start_index]
    end = points[end_index]
    length = segment_length(start, end)
    if length <= EPSILON:
        raise ValueError("cannot edit angle of zero-length edge")
    azimuth = math.radians(_finite("azimuth_deg", azimuth_deg) % 360.0)
    dx = length * math.sin(azimuth)
    dy = length * math.cos(azimuth)

    if preserve == "start":
        points[end_index] = (start[0] + dx, start[1] + dy)
    elif preserve == "end":
        points[start_index] = (end[0] - dx, end[1] - dy)
    elif preserve == "midpoint":
        midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        points[start_index] = (midpoint[0] - dx / 2.0, midpoint[1] - dy / 2.0)
        points[end_index] = (midpoint[0] + dx / 2.0, midpoint[1] + dy / 2.0)
    else:
        raise ValueError("preserve must be start, end, or midpoint")
    return points
