"""Visible, deterministic snapping for the 2-D engineering editor."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence

from .geometry2d import (
    Point2D,
    line_intersection,
    polygon_segments,
    polyline_segments,
    project_point_to_segment,
    segment_length,
)


SNAP_KINDS = {
    "vertex",
    "endpoint",
    "edge",
    "midpoint",
    "intersection",
    "parallel",
    "perpendicular",
    "module_edge",
    "row_edge",
    "user_grid",
}

_KIND_PRIORITY = {
    "vertex": 0,
    "endpoint": 1,
    "intersection": 2,
    "midpoint": 3,
    "edge": 4,
    "module_edge": 5,
    "row_edge": 6,
    "parallel": 7,
    "perpendicular": 8,
    "user_grid": 9,
}


@dataclass(frozen=True)
class SnapResult:
    raw_point: Point2D
    snapped_point: Point2D
    applied: bool
    kind: str | None
    source_entity_id: str | None
    feature_index: int | None
    distance_m: float
    visible_marker: str | None


@dataclass(frozen=True)
class _Candidate:
    kind: str
    point: Point2D
    distance_m: float
    source_entity_id: str | None
    feature_index: int | None


def _scene_geometry(
    scene: Mapping,
    *,
    exclude_entity_ids: Iterable[str] = (),
) -> tuple[list, list]:
    vertices: list[tuple[str, int, Point2D, bool]] = []
    edges: list[tuple[str, int, Point2D, Point2D, str]] = []
    excluded = {str(value) for value in exclude_entity_ids}

    for collection_name in ("surfaces", "obstacles", "reference_lines"):
        for entity in scene.get(collection_name, []):
            if entity.get("visible", True) is False:
                continue
            entity_id = (
                entity.get("surface_id")
                or entity.get("obstacle_id")
                or entity.get("reference_line_id")
                or entity.get("scene_object_id")
            )
            if str(entity_id) in excluded or str(entity.get("scene_object_id")) in excluded:
                continue
            if collection_name == "surfaces":
                points = [
                    tuple(point)
                    for point in entity["boundary_2d"]["vertices"]
                ]
                segments = polygon_segments(points)
                is_open = False
            elif collection_name == "obstacles":
                if entity.get("obstacle_type") == "imported_mesh":
                    continue  # Meshes have no editable 2-D footprint.
                points = [
                    tuple(point)
                    for point in entity["footprint"]["vertices"]
                ]
                segments = polygon_segments(points)
                is_open = False
            else:
                points = [tuple(point) for point in entity["vertices"]]
                segments = polyline_segments(points)
                is_open = True

            for index, point in enumerate(points):
                endpoint = is_open and index in {0, len(points) - 1}
                vertices.append((str(entity_id), index, point, endpoint))
            for index, (start, end) in enumerate(segments):
                edges.append(
                    (str(entity_id), index, start, end, collection_name)
                )
    return vertices, edges


def _project_to_infinite_line(
    point: Point2D,
    anchor: Point2D,
    direction: Point2D,
) -> tuple[Point2D, float]:
    length = math.hypot(direction[0], direction[1])
    if length <= 0.0:
        raise ValueError("reference direction must have non-zero length")
    ux = direction[0] / length
    uy = direction[1] / length
    t = (point[0] - anchor[0]) * ux + (point[1] - anchor[1]) * uy
    projection = (anchor[0] + t * ux, anchor[1] + t * uy)
    return projection, segment_length(point, projection)


class SnapEngine:
    """Resolve visible snap candidates without silently changing geometry."""

    def __init__(
        self,
        scene: Mapping,
        *,
        supplemental_edges: Mapping[
            str, Sequence[tuple[str, Point2D, Point2D]]
        ]
        | None = None,
        exclude_entity_ids: Iterable[str] = (),
    ) -> None:
        self._scene = scene
        self._supplemental_edges = supplemental_edges or {}
        self._exclude_entity_ids = {
            str(value) for value in exclude_entity_ids
        }

    def resolve(
        self,
        point: Point2D,
        *,
        tolerance_m: float,
        enabled_kinds: Iterable[str] = SNAP_KINDS,
        override: bool = False,
        grid_spacing_m: float | None = None,
        anchor: Point2D | None = None,
        reference_direction: Point2D | None = None,
    ) -> SnapResult:
        raw = (float(point[0]), float(point[1]))
        tolerance = float(tolerance_m)
        if tolerance < 0.0:
            raise ValueError("tolerance_m must be non-negative")
        kinds = set(enabled_kinds)
        unsupported = kinds - SNAP_KINDS
        if unsupported:
            raise ValueError(f"unsupported snap kinds: {sorted(unsupported)}")
        if override or not kinds:
            return SnapResult(
                raw, raw, False, None, None, None, 0.0, None
            )

        vertices, edges = _scene_geometry(
            self._scene,
            exclude_entity_ids=self._exclude_entity_ids,
        )
        candidates: list[_Candidate] = []

        if "vertex" in kinds or "endpoint" in kinds:
            for entity_id, index, vertex, endpoint in vertices:
                distance = segment_length(raw, vertex)
                if "vertex" in kinds:
                    candidates.append(
                        _Candidate(
                            "vertex", vertex, distance, entity_id, index
                        )
                    )
                if endpoint and "endpoint" in kinds:
                    candidates.append(
                        _Candidate(
                            "endpoint", vertex, distance, entity_id, index
                        )
                    )

        if "midpoint" in kinds or "edge" in kinds:
            for entity_id, index, start, end, _ in edges:
                if "midpoint" in kinds:
                    midpoint = (
                        (start[0] + end[0]) / 2.0,
                        (start[1] + end[1]) / 2.0,
                    )
                    candidates.append(
                        _Candidate(
                            "midpoint",
                            midpoint,
                            segment_length(raw, midpoint),
                            entity_id,
                            index,
                        )
                    )
                if "edge" in kinds:
                    projection, distance = project_point_to_segment(
                        raw, start, end
                    )
                    candidates.append(
                        _Candidate(
                            "edge",
                            projection,
                            distance,
                            entity_id,
                            index,
                        )
                    )

        if "intersection" in kinds:
            for first_index, first in enumerate(edges):
                for second_index in range(first_index + 1, len(edges)):
                    second = edges[second_index]
                    if (
                        first[0] == second[0]
                        and abs(first[1] - second[1]) <= 1
                    ):
                        continue
                    intersection = line_intersection(
                        first[2],
                        first[3],
                        second[2],
                        second[3],
                        segment_only=True,
                    )
                    if intersection is None:
                        continue
                    candidates.append(
                        _Candidate(
                            "intersection",
                            intersection,
                            segment_length(raw, intersection),
                            f"{first[0]}|{second[0]}",
                            first_index * 1_000_000 + second_index,
                        )
                    )

        for kind in ("module_edge", "row_edge"):
            if kind not in kinds:
                continue
            for index, item in enumerate(
                self._supplemental_edges.get(kind, ())
            ):
                source_id, start, end = item
                if str(source_id) in self._exclude_entity_ids:
                    continue
                projection, distance = project_point_to_segment(
                    raw, start, end
                )
                candidates.append(
                    _Candidate(
                        kind,
                        projection,
                        distance,
                        source_id,
                        index,
                    )
                )

        if "user_grid" in kinds and grid_spacing_m is not None:
            spacing = float(grid_spacing_m)
            if spacing <= 0.0:
                raise ValueError("grid_spacing_m must be positive")
            grid_point = (
                round(raw[0] / spacing) * spacing,
                round(raw[1] / spacing) * spacing,
            )
            candidates.append(
                _Candidate(
                    "user_grid",
                    grid_point,
                    segment_length(raw, grid_point),
                    None,
                    None,
                )
            )

        if (
            anchor is not None
            and reference_direction is not None
            and "parallel" in kinds
        ):
            projection, distance = _project_to_infinite_line(
                raw, anchor, reference_direction
            )
            candidates.append(
                _Candidate(
                    "parallel",
                    projection,
                    distance,
                    None,
                    None,
                )
            )

        if (
            anchor is not None
            and reference_direction is not None
            and "perpendicular" in kinds
        ):
            perpendicular = (
                -reference_direction[1],
                reference_direction[0],
            )
            projection, distance = _project_to_infinite_line(
                raw, anchor, perpendicular
            )
            candidates.append(
                _Candidate(
                    "perpendicular",
                    projection,
                    distance,
                    None,
                    None,
                )
            )

        eligible = [
            candidate
            for candidate in candidates
            if candidate.distance_m <= tolerance
        ]
        if not eligible:
            return SnapResult(
                raw, raw, False, None, None, None, 0.0, None
            )

        chosen = min(
            eligible,
            key=lambda candidate: (
                round(candidate.distance_m, 12),
                _KIND_PRIORITY[candidate.kind],
                candidate.source_entity_id or "",
                candidate.feature_index
                if candidate.feature_index is not None
                else -1,
                round(candidate.point[0], 12),
                round(candidate.point[1], 12),
            ),
        )
        return SnapResult(
            raw_point=raw,
            snapped_point=chosen.point,
            applied=True,
            kind=chosen.kind,
            source_entity_id=chosen.source_entity_id,
            feature_index=chosen.feature_index,
            distance_m=chosen.distance_m,
            visible_marker=chosen.kind,
        )
