"""Deterministic command/session kernel for the Phase-4.2 2-D scene editor."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
from typing import Iterable, Sequence

from .geometry2d import (
    Point2D,
    bounding_box,
    mirror_points,
    polygon_centroid,
    polygon_segments,
    polyline_segments,
    rotate_points_clockwise,
    segment_azimuth_deg,
    segment_length,
    set_edge_azimuth,
    set_edge_length,
    translate_points,
    validate_polygon,
)
from .primitives import (
    DIMENSION_SOURCES,
    circle_polygon,
    make_obstacle,
    make_reference_line,
    make_surface,
    rectangle_vertices,
    wall_footprint,
)
from .serialization import canonical_scene_hash, canonical_scene_json
from .snapping import SnapEngine
from .surface_plane import SurfacePlane, synchronize_scene_module_center_z


_COLLECTIONS = ("surfaces", "obstacles", "reference_lines")


def _entity_id(entity: dict) -> str:
    return str(
        entity.get("surface_id")
        or entity.get("obstacle_id")
        or entity.get("reference_line_id")
        or entity.get("scene_object_id")
    )


def _entity_points(collection: str, entity: dict) -> list[Point2D]:
    if collection == "surfaces":
        return [
            tuple(point)
            for point in entity["boundary_2d"]["vertices"]
        ]
    if collection == "obstacles":
        if entity.get("obstacle_type") == "imported_mesh":
            raise ValueError(f"mesh {entity['obstacle_id']}: read-only; use whole-mesh replacement or delete")
        return [tuple(point) for point in entity["footprint"]["vertices"]]
    if collection == "reference_lines":
        return [tuple(point) for point in entity["vertices"]]
    raise ValueError(f"unsupported entity collection: {collection}")


def _set_entity_points(
    collection: str,
    entity: dict,
    points: Sequence[Point2D],
) -> None:
    if collection in {"surfaces", "obstacles"}:
        resolved = validate_polygon(points, normalize=False)
        target = (
            entity["boundary_2d"]
            if collection == "surfaces"
            else entity["footprint"]
        )
        target["vertices"] = [list(point) for point in resolved]
        from .geometry2d import winding as _winding
        target["winding"] = _winding(resolved)
        target["closed"] = True
        return
    if collection == "reference_lines":
        resolved = [tuple(map(float, point)) for point in points]
        if len(resolved) < 2:
            raise ValueError("reference line requires at least two vertices")
        if any(
            segment_length(resolved[index], resolved[index + 1]) <= 0.0
            for index in range(len(resolved) - 1)
        ):
            raise ValueError("reference line contains a zero-length segment")
        entity["vertices"] = [list(point) for point in resolved]
        return
    raise ValueError(f"unsupported entity collection: {collection}")


def _validate_surface_holes(entity: dict) -> None:
    from shapely.geometry import Polygon
    outer = Polygon(entity["boundary_2d"]["vertices"])
    holes = []
    for vertices in entity["boundary_2d"].get("holes", []):
        validate_polygon(vertices, normalize=False)
        hole = Polygon(vertices)
        if not outer.contains(hole) or not outer.boundary.disjoint(hole):
            raise ValueError("a hole must lie strictly inside the outer ring")
        if any(hole.intersects(other) for other in holes):
            raise ValueError("holes must not overlap or touch")
        holes.append(hole)


def _ring_points(collection: str, entity: dict, ring: int) -> list[Point2D]:
    if not isinstance(ring, int) or isinstance(ring, bool) or ring < 0:
        raise ValueError("ring must be a non-negative integer")
    if ring == 0:
        return _entity_points(collection, entity)
    if collection != "surfaces":
        raise ValueError("hole rings require a surface")
    holes = entity["boundary_2d"].get("holes", [])
    if ring > len(holes):
        raise IndexError("ring is outside geometry")
    return [tuple(point) for point in holes[ring - 1]]


def _set_ring_points(collection: str, entity: dict, points, ring: int) -> None:
    if ring == 0:
        _set_entity_points(collection, entity, points)
    else:
        entity["boundary_2d"]["holes"][ring - 1] = [
            list(point) for point in validate_polygon(points, normalize=False)
        ]
    if collection == "surfaces":
        _validate_surface_holes(entity)


def _closed(collection: str) -> bool:
    return collection in {"surfaces", "obstacles"}


def _edge_count(collection: str, entity: dict) -> int:
    count = len(_entity_points(collection, entity))
    return count if _closed(collection) else count - 1


def _update_edge_provenance(
    entity: dict,
    *,
    edge_index: int,
    original_value_m: float,
    value_m: float,
    source: str,
) -> None:
    values = entity.setdefault("edge_dimension_sources", [])
    record = {
        "edge_index": int(edge_index),
        "source": source,
        "value_m": float(value_m),
        "source_reference_id": None,
        "original_value_m": float(original_value_m),
    }
    for index, existing in enumerate(values):
        if existing.get("edge_index") == edge_index:
            values[index] = record
            break
    else:
        values.append(record)
    values.sort(key=lambda item: item["edge_index"])


def _refresh_edge_provenance(
    collection: str,
    entity: dict,
    *,
    explicit_edge_index: int | None = None,
) -> None:
    points = _entity_points(collection, entity)
    records = entity.setdefault("edge_dimension_sources", [])
    record_by_index = {
        int(record["edge_index"]): record
        for record in records
        if "edge_index" in record
    }
    count = _edge_count(collection, entity)
    for edge_index in range(count):
        end_index = (edge_index + 1) % len(points)
        actual = segment_length(points[edge_index], points[end_index])
        record = record_by_index.get(edge_index)
        if record is None:
            record = {
                "edge_index": edge_index,
                "source": "derived",
                "value_m": actual,
                "source_reference_id": None,
                "original_value_m": None,
            }
            records.append(record)
            continue
        previous = float(record.get("value_m", actual))
        if edge_index != explicit_edge_index and abs(previous - actual) > 1e-9:
            if record.get("original_value_m") is None:
                record["original_value_m"] = previous
            record["source"] = "derived"
            record["source_reference_id"] = None
        record["value_m"] = actual
    records.sort(key=lambda item: int(item["edge_index"]))


def _reference_point(points, anchor):
    x, y = points[0]
    dx, dy = points[1][0] - x, points[1][1] - y
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    us = [px * ux + py * uy for px, py in points]
    vs = [-px * uy + py * ux for px, py in points]
    fraction = {"start": 0, "center": 0.5, "end": 1}
    u = min(us) + (max(us) - min(us)) * fraction[anchor.get("u", "start")]
    v = min(vs) + (max(vs) - min(vs)) * fraction[anchor.get("v", "start")]
    return (u * ux - v * uy, u * uy + v * ux)


class SceneEditorSession:
    """Editable draft session.

    Selection and undo/redo are session state. Canonical engineering state becomes
    immutable only when commit_revision() emits a new Scene revision.
    """

    def __init__(self, scene: dict) -> None:
        self._scene = deepcopy(scene)
        self._scene.setdefault("surfaces", [])
        self._scene.setdefault("obstacles", [])
        self._scene.setdefault("reference_lines", [])
        self._scene.setdefault("pv_fields", [])
        self._scene.setdefault("module_instances", [])
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._selection: list[str] = []

    @property
    def scene(self) -> dict:
        return deepcopy(self._scene)

    @property
    def selected_entity_ids(self) -> tuple[str, ...]:
        return tuple(self._selection)

    @property
    def undo_depth(self) -> int:
        return len(self._undo)

    @property
    def redo_depth(self) -> int:
        return len(self._redo)

    def canonical_json(self) -> str:
        return canonical_scene_json(self._scene)

    def canonical_hash(self) -> str:
        return canonical_scene_hash(self._scene)

    def _find(self, entity_id: str) -> tuple[str, dict]:
        for collection in _COLLECTIONS:
            for entity in self._scene.get(collection, []):
                if entity_id in {
                    _entity_id(entity),
                    str(entity.get("scene_object_id")),
                }:
                    return collection, entity
        raise KeyError(f"scene entity not found: {entity_id}")

    def _assert_editable(self, entity: dict, *, mesh_delete=False) -> None:
        if entity.get("locked", False):
            raise ValueError(f"entity {_entity_id(entity)} is locked")
        if entity.get("obstacle_type") == "imported_mesh" and not mesh_delete:
            raise ValueError(f"mesh {entity['obstacle_id']}: read-only; use whole-mesh replacement or delete")
        supports=[f['pv_field_id'] for f in self._scene.get('pv_fields',[]) if f.get('field_kind')=='explicit_layout'
                  and any(t.get('support_surface_id')==entity.get('surface_id') for t in f.get('tables',[])) and entity.get('surface_id') is not None]
        if supports:
            raise ValueError(f"support surface carries explicit fields {supports}; delete those fields first")

    def _assert_unique_ids(
        self,
        entity_id: str,
        scene_object_id: str,
    ) -> None:
        for collection in _COLLECTIONS:
            for entity in self._scene.get(collection, []):
                if entity_id == _entity_id(entity):
                    raise ValueError(f"duplicate entity ID: {entity_id}")
                if scene_object_id == entity.get("scene_object_id"):
                    raise ValueError(
                        f"duplicate scene_object_id: {scene_object_id}"
                    )

    def _mutate(self, operation, *, synchronize=True) -> None:
        before = deepcopy(self._scene)
        try:
            operation()
            if synchronize:
                synchronize_scene_module_center_z(self._scene)
        except Exception:
            self._scene = before
            raise
        self._undo.append(before)
        self._redo.clear()

    def select(
        self,
        entity_ids: Iterable[str],
        *,
        additive: bool = False,
    ) -> tuple[str, ...]:
        selected = list(self._selection) if additive else []
        for entity_id in entity_ids:
            _, entity = self._find(entity_id)
            if entity.get("visible", True) is False:
                continue
            if entity.get("selectable", True) is False:
                continue
            canonical_id = _entity_id(entity)
            if canonical_id not in selected:
                selected.append(canonical_id)
        self._selection = selected
        return tuple(selected)

    def clear_selection(self) -> None:
        self._selection = []

    def draw_polygon(
        self,
        *,
        surface_id: str,
        scene_object_id: str,
        name: str,
        surface_type: str,
        vertices: Sequence[Point2D],
        base_elevation_m: float = 0.0,
        slope_deg: float = 0.0,
        azimuth_deg: float = 0.0,
        usable_for_pv: bool = True,
        geometry_source: str = "user_override",
    ) -> str:
        self._assert_unique_ids(surface_id, scene_object_id)
        item = make_surface(
            scene_id=self._scene["scene_id"],
            surface_id=surface_id,
            scene_object_id=scene_object_id,
            name=name,
            surface_type=surface_type,
            vertices=vertices,
            base_elevation_m=base_elevation_m,
            slope_deg=slope_deg,
            azimuth_deg=azimuth_deg,
            usable_for_pv=usable_for_pv,
            geometry_source=geometry_source,
        )
        self._mutate(lambda: self._scene["surfaces"].append(item))
        return surface_id

    def draw_rectangle(
        self,
        *,
        surface_id: str,
        scene_object_id: str,
        name: str,
        surface_type: str,
        origin_x_m: float,
        origin_y_m: float,
        width_m: float,
        height_m: float,
        base_elevation_m: float = 0.0,
        usable_for_pv: bool = True,
        geometry_source: str = "user_override",
    ) -> str:
        return self.draw_polygon(
            surface_id=surface_id,
            scene_object_id=scene_object_id,
            name=name,
            surface_type=surface_type,
            vertices=rectangle_vertices(
                origin_x_m, origin_y_m, width_m, height_m
            ),
            base_elevation_m=base_elevation_m,
            usable_for_pv=usable_for_pv,
            geometry_source=geometry_source,
        )

    def draw_line(
        self,
        *,
        reference_line_id: str,
        scene_object_id: str,
        name: str,
        vertices: Sequence[Point2D],
        line_type: str = "reference",
        base_elevation_m: float = 0.0,
        geometry_source: str = "user_override",
    ) -> str:
        self._assert_unique_ids(reference_line_id, scene_object_id)
        item = make_reference_line(
            scene_id=self._scene["scene_id"],
            reference_line_id=reference_line_id,
            scene_object_id=scene_object_id,
            name=name,
            vertices=vertices,
            line_type=line_type,
            base_elevation_m=base_elevation_m,
            geometry_source=geometry_source,
        )
        self._mutate(lambda: self._scene["reference_lines"].append(item))
        return reference_line_id

    def draw_box_obstacle(
        self,
        *,
        obstacle_id: str,
        scene_object_id: str,
        name: str,
        origin_x_m: float,
        origin_y_m: float,
        width_m: float,
        depth_m: float,
        base_elevation_m: float,
        height_m: float,
        geometry_source: str = "user_override",
    ) -> str:
        return self._draw_obstacle(
            obstacle_id=obstacle_id,
            scene_object_id=scene_object_id,
            name=name,
            obstacle_type="box",
            vertices=rectangle_vertices(
                origin_x_m, origin_y_m, width_m, depth_m
            ),
            base_elevation_m=base_elevation_m,
            height_m=height_m,
            dimensions={"width_m": width_m, "depth_m": depth_m},
            geometry_source=geometry_source,
        )

    def draw_polygon_extrusion(
        self,
        *,
        obstacle_id: str,
        scene_object_id: str,
        name: str,
        vertices: Sequence[Point2D],
        base_elevation_m: float,
        height_m: float,
        geometry_source: str = "user_override",
    ) -> str:
        return self._draw_obstacle(
            obstacle_id=obstacle_id,
            scene_object_id=scene_object_id,
            name=name,
            obstacle_type="extruded_polygon",
            vertices=vertices,
            base_elevation_m=base_elevation_m,
            height_m=height_m,
            geometry_source=geometry_source,
        )

    def draw_cylinder_obstacle(
        self,
        *,
        obstacle_id: str,
        scene_object_id: str,
        name: str,
        center_x_m: float,
        center_y_m: float,
        radius_m: float,
        base_elevation_m: float,
        height_m: float,
        segments: int = 32,
        obstacle_type: str = "cylinder",
        geometry_source: str = "user_override",
    ) -> str:
        return self._draw_obstacle(
            obstacle_id=obstacle_id,
            scene_object_id=scene_object_id,
            name=name,
            obstacle_type=obstacle_type,
            vertices=circle_polygon(
                center_x_m,
                center_y_m,
                radius_m,
                segments=segments,
            ),
            base_elevation_m=base_elevation_m,
            height_m=height_m,
            dimensions={"radius_m": radius_m, "segments": segments},
            geometry_source=geometry_source,
        )

    def draw_wall_obstacle(
        self,
        *,
        obstacle_id: str,
        scene_object_id: str,
        name: str,
        start: Point2D,
        end: Point2D,
        width_m: float,
        base_elevation_m: float,
        height_m: float,
        parapet: bool = False,
        geometry_source: str = "user_override",
    ) -> str:
        return self._draw_obstacle(
            obstacle_id=obstacle_id,
            scene_object_id=scene_object_id,
            name=name,
            obstacle_type="parapet" if parapet else "wall",
            vertices=wall_footprint(start, end, width_m),
            base_elevation_m=base_elevation_m,
            height_m=height_m,
            dimensions={
                "width_m": width_m,
                "length_m": segment_length(start, end),
            },
            geometry_source=geometry_source,
        )

    def draw_pole_obstacle(self, **kwargs) -> str:
        kwargs["obstacle_type"] = "pole"
        return self.draw_cylinder_obstacle(**kwargs)

    def draw_simplified_tree(self, **kwargs) -> str:
        kwargs["obstacle_type"] = "simplified_tree"
        return self.draw_cylinder_obstacle(**kwargs)

    def _draw_obstacle(
        self,
        *,
        obstacle_id: str,
        scene_object_id: str,
        name: str,
        obstacle_type: str,
        vertices: Sequence[Point2D],
        base_elevation_m: float,
        height_m: float,
        dimensions: dict | None = None,
        geometry_source: str,
    ) -> str:
        self._assert_unique_ids(obstacle_id, scene_object_id)
        item = make_obstacle(
            scene_id=self._scene["scene_id"],
            obstacle_id=obstacle_id,
            scene_object_id=scene_object_id,
            name=name,
            obstacle_type=obstacle_type,
            vertices=vertices,
            base_elevation_m=base_elevation_m,
            height_m=height_m,
            dimensions=dimensions,
            geometry_source=geometry_source,
        )
        self._mutate(lambda: self._scene["obstacles"].append(item))
        return obstacle_id

    def move(
        self,
        entity_ids: Iterable[str],
        *,
        dx_m: float,
        dy_m: float,
    ) -> None:
        ids = tuple(entity_ids)

        def operation():
            for entity_id in ids:
                collection, entity = self._find(entity_id)
                self._assert_editable(entity)
                _set_entity_points(
                    collection,
                    entity,
                    translate_points(
                        _entity_points(collection, entity),
                        dx_m,
                        dy_m,
                    ),
                )

                if collection == "surfaces" and entity["boundary_2d"].get("holes"):
                    entity["boundary_2d"]["holes"] = [
                        [list(point) for point in translate_points(hole, dx_m, dy_m)]
                        for hole in entity["boundary_2d"]["holes"]
                    ]

        self._mutate(operation)

    def rotate(
        self,
        entity_ids: Iterable[str],
        *,
        angle_deg: float,
        origin: Point2D | None = None,
    ) -> None:
        ids = tuple(entity_ids)
        if not ids:
            return
        if origin is None:
            points: list[Point2D] = []
            for entity_id in ids:
                collection, entity = self._find(entity_id)
                points.extend(_entity_points(collection, entity))
            min_x, min_y, max_x, max_y = bounding_box(points)
            origin = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)

        def operation():
            for entity_id in ids:
                collection, entity = self._find(entity_id)
                self._assert_editable(entity)
                _set_entity_points(
                    collection,
                    entity,
                    rotate_points_clockwise(
                        _entity_points(collection, entity),
                        origin,
                        angle_deg,
                    ),
                )

                if collection == "surfaces" and entity["boundary_2d"].get("holes"):
                    entity["boundary_2d"]["holes"] = [
                        [list(point) for point in rotate_points_clockwise(hole, origin, angle_deg)]
                        for hole in entity["boundary_2d"]["holes"]
                    ]

        self._mutate(operation)

    def scale(
        self,
        entity_ids: Iterable[str],
        *,
        factor: float,
        origin: Point2D | None = None,
    ) -> None:
        factor = float(factor)
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("factor must be finite and positive")
        ids = tuple(entity_ids)
        if not ids:
            return
        if origin is None:
            points = []
            for entity_id in ids:
                collection, entity = self._find(entity_id)
                points.extend(_entity_points(collection, entity))
            min_x, min_y, max_x, max_y = bounding_box(points)
            origin = ((min_x + max_x) / 2, (min_y + max_y) / 2)
        if len(origin) != 2 or not all(math.isfinite(float(value)) for value in origin):
            raise ValueError("origin must contain two finite coordinates")
        ox, oy = map(float, origin)

        def scaled(points):
            return [(ox + (x - ox) * factor, oy + (y - oy) * factor) for x, y in points]

        def operation():
            for entity_id in ids:
                collection, entity = self._find(entity_id)
                self._assert_editable(entity)
                _set_entity_points(collection, entity, scaled(_entity_points(collection, entity)))
                if collection in {"surfaces", "obstacles"}:
                    ring = entity["boundary_2d" if collection == "surfaces" else "footprint"]
                    if "holes" in ring:
                        ring["holes"] = [
                            [list(point) for point in validate_polygon(scaled(hole), normalize=False)]
                            for hole in ring["holes"]
                        ]
                _refresh_edge_provenance(collection, entity)
                entity["geometry_source"] = "user_override"
                if collection == "obstacles":
                    entity.setdefault("dimensions", {})["parameterization_valid"] = False

        self._mutate(operation)

    def copy(
        self,
        entity_id: str,
        *,
        new_entity_id: str,
        new_scene_object_id: str,
        dx_m: float = 0.0,
        dy_m: float = 0.0,
    ) -> str:
        collection, entity = self._find(entity_id)
        self._assert_unique_ids(new_entity_id, new_scene_object_id)
        clone = deepcopy(entity)
        id_key = {
            "surfaces": "surface_id",
            "obstacles": "obstacle_id",
            "reference_lines": "reference_line_id",
        }[collection]
        clone[id_key] = new_entity_id
        clone["scene_object_id"] = new_scene_object_id
        clone["name"] = f"{entity.get('name', entity_id)} copy"
        _set_entity_points(
            collection,
            clone,
            translate_points(
                _entity_points(collection, clone),
                dx_m,
                dy_m,
            ),
        )
        self._mutate(lambda: self._scene[collection].append(clone))
        return new_entity_id

    def array(
        self,
        entity_id: str,
        *,
        copies: int,
        step_dx_m: float,
        step_dy_m: float,
        entity_id_prefix: str,
        scene_object_id_prefix: str,
    ) -> tuple[str, ...]:
        if copies < 1:
            raise ValueError("copies must be at least 1")
        collection, entity = self._find(entity_id)
        id_key = {
            "surfaces": "surface_id",
            "obstacles": "obstacle_id",
            "reference_lines": "reference_line_id",
        }[collection]
        clones = []
        created = []
        for index in range(1, copies + 1):
            new_entity_id = f"{entity_id_prefix}-{index}"
            new_scene_object_id = f"{scene_object_id_prefix}-{index}"
            self._assert_unique_ids(new_entity_id, new_scene_object_id)
            clone = deepcopy(entity)
            clone[id_key] = new_entity_id
            clone["scene_object_id"] = new_scene_object_id
            clone["name"] = f"{entity.get('name', entity_id)} array {index}"
            _set_entity_points(
                collection,
                clone,
                translate_points(
                    _entity_points(collection, clone),
                    step_dx_m * index,
                    step_dy_m * index,
                ),
            )
            clones.append(clone)
            created.append(new_entity_id)

        self._mutate(
            lambda: self._scene[collection].extend(deepcopy(clones))
        )
        return tuple(created)

    def mirror(
        self,
        entity_ids: Iterable[str],
        *,
        line_start: Point2D,
        line_end: Point2D,
    ) -> None:
        ids = tuple(entity_ids)

        def operation():
            for entity_id in ids:
                collection, entity = self._find(entity_id)
                self._assert_editable(entity)
                _set_entity_points(
                    collection,
                    entity,
                    mirror_points(
                        _entity_points(collection, entity),
                        line_start,
                        line_end,
                    ),
                )

        self._mutate(operation)

    def delete(self, entity_ids: Iterable[str]) -> None:
        ids = set(entity_ids)

        def operation():
            for entity_id in ids:
                _, entity = self._find(entity_id)
                self._assert_editable(entity, mesh_delete=True)
            for collection in _COLLECTIONS:
                self._scene[collection] = [
                    entity
                    for entity in self._scene.get(collection, [])
                    if _entity_id(entity) not in ids
                    and str(entity.get("scene_object_id")) not in ids
                ]

        self._mutate(operation)
        self._selection = [
            value for value in self._selection if value not in ids
        ]

    def move_vertex(
        self,
        entity_id: str,
        *,
        vertex_index: int,
        ring: int = 0,
        target_x_m: float,
        target_y_m: float,
        snap_tolerance_m: float | None = None,
        snap_kinds: Iterable[str] | None = None,
        grid_spacing_m: float | None = None,
        snap_override: bool = False,
    ) -> dict:
        """Move one explicit geometry vertex without changing object identity.

        Snapping is visible/explicit. The edited entity is excluded from snap
        candidates so a vertex cannot silently snap back to its own geometry.
        """
        collection, entity = self._find(entity_id)
        self._assert_editable(entity)
        points = _ring_points(collection, entity, ring)
        if vertex_index < 0 or vertex_index >= len(points):
            raise IndexError("vertex_index is outside geometry")

        raw = (float(target_x_m), float(target_y_m))
        snapped = raw
        snap_result = None
        if snap_tolerance_m is not None:
            engine = SnapEngine(
                self._scene,
                exclude_entity_ids={entity_id, str(entity.get("scene_object_id"))},
            )
            kwargs = {
                "tolerance_m": float(snap_tolerance_m),
                "override": bool(snap_override),
                "grid_spacing_m": grid_spacing_m,
            }
            if snap_kinds is not None:
                kwargs["enabled_kinds"] = tuple(snap_kinds)
            snap_result = engine.resolve(raw, **kwargs)
            snapped = snap_result.snapped_point

        updated = list(points)
        updated[vertex_index] = snapped
        # Validate before opening an undo transaction so invalid edits fail closed.
        if collection in {"surfaces", "obstacles"}:
            validate_polygon(updated, normalize=False)
        elif collection == "reference_lines":
            for index in range(len(updated) - 1):
                if segment_length(updated[index], updated[index + 1]) <= 0.0:
                    raise ValueError(
                        "reference line contains a zero-length segment"
                    )

        def operation():
            _, target = self._find(entity_id)
            _set_ring_points(collection, target, updated, ring)
            _refresh_edge_provenance(collection, target)
            target["geometry_source"] = "user_override"
            target.setdefault("metadata", {})["last_vertex_edit"] = {
                "vertex_index": int(vertex_index),
                "target_x_m": float(snapped[0]),
                "target_y_m": float(snapped[1]),
                "source": "user_override",
            }
            if collection == "obstacles":
                target.setdefault("dimensions", {})[
                    "parameterization_valid"
                ] = False

        self._mutate(operation)
        return {
            "entity_id": entity_id,
            "vertex_index": int(vertex_index),
            "raw_point": [raw[0], raw[1]],
            "resolved_point": [snapped[0], snapped[1]],
            "snap": (
                {
                    "applied": snap_result.applied,
                    "kind": snap_result.kind,
                    "source_entity_id": snap_result.source_entity_id,
                    "feature_index": snap_result.feature_index,
                    "distance_m": snap_result.distance_m,
                    "visible_marker": snap_result.visible_marker,
                }
                if snap_result is not None
                else {
                    "applied": False,
                    "kind": None,
                    "source_entity_id": None,
                    "feature_index": None,
                    "distance_m": 0.0,
                    "visible_marker": None,
                }
            ),
        }

    def insert_vertex(self, entity_id: str, *, edge_index: int, x_m: float, y_m: float, ring: int = 0) -> None:
        collection, entity = self._find(entity_id)
        self._assert_editable(entity)
        if not isinstance(edge_index, int) or isinstance(edge_index, bool):
            raise ValueError("edge_index must be an integer")
        if edge_index < 0 or edge_index >= (len(_ring_points(collection, entity, ring)) if ring or _closed(collection) else _edge_count(collection, entity)):
            raise IndexError("edge_index is outside geometry")
        point = (float(x_m), float(y_m))
        if not all(math.isfinite(value) for value in point):
            raise ValueError("vertex coordinates must be finite")
        points = _ring_points(collection, entity, ring)
        updated = points[:edge_index + 1] + [point] + points[edge_index + 1:]

        def operation():
            _, target = self._find(entity_id)
            _set_ring_points(collection, target, updated, ring)
            # Splitting an edge creates two derived dimensions. Preserve the
            # provenance of the other edges under their new indices.
            if ring == 0:
                target["edge_dimension_sources"] = [
                    {**record, "edge_index": int(record["edge_index"]) + (int(record["edge_index"]) > edge_index)}
                    for record in target.get("edge_dimension_sources", [])
                    if int(record["edge_index"]) != edge_index
                ]
            _refresh_edge_provenance(collection, target)
            target["geometry_source"] = "user_override"
            if collection == "obstacles":
                target.setdefault("dimensions", {})["parameterization_valid"] = False

        self._mutate(operation)

    def delete_vertex(self, entity_id: str, *, vertex_index: int, ring: int = 0) -> None:
        collection, entity = self._find(entity_id)
        self._assert_editable(entity)
        points = _ring_points(collection, entity, ring)
        if not isinstance(vertex_index, int) or isinstance(vertex_index, bool):
            raise ValueError("vertex_index must be an integer")
        if vertex_index < 0 or vertex_index >= len(points):
            raise IndexError("vertex_index is outside geometry")
        minimum = 3 if _closed(collection) else 2
        if len(points) <= minimum:
            raise ValueError(f"geometry must keep at least {minimum} vertices")
        updated = points[:vertex_index] + points[vertex_index + 1:]
        replaced_edges = {vertex_index}
        if vertex_index > 0 or _closed(collection):
            replaced_edges.add((vertex_index - 1) % len(points))

        def operation():
            _, target = self._find(entity_id)
            _set_ring_points(collection, target, updated, ring)
            if ring == 0:
                target["edge_dimension_sources"] = [
                    {**record, "edge_index": int(record["edge_index"]) - (int(record["edge_index"]) > vertex_index)}
                    for record in target.get("edge_dimension_sources", [])
                    if int(record["edge_index"]) not in replaced_edges
                ]
            _refresh_edge_provenance(collection, target)
            target["geometry_source"] = "user_override"
            if collection == "obstacles":
                target.setdefault("dimensions", {})["parameterization_valid"] = False

        self._mutate(operation)

    def move_edge(self, entity_id: str, *, edge_index: int, dx_m: float, dy_m: float, ring: int = 0) -> None:
        collection, entity = self._find(entity_id)
        self._assert_editable(entity)
        if not isinstance(edge_index, int) or isinstance(edge_index, bool):
            raise ValueError("edge_index must be an integer")
        if edge_index < 0 or edge_index >= (len(_ring_points(collection, entity, ring)) if ring or _closed(collection) else _edge_count(collection, entity)):
            raise IndexError("edge_index is outside geometry")
        dx, dy = float(dx_m), float(dy_m)
        if not all(math.isfinite(value) for value in (dx, dy)):
            raise ValueError("edge movement must be finite")
        points = _ring_points(collection, entity, ring)
        moved = {edge_index, (edge_index + 1) % len(points)}
        updated = [(x + dx, y + dy) if i in moved else (x, y)
                   for i, (x, y) in enumerate(points)]

        def operation():
            _, target = self._find(entity_id)
            _set_ring_points(collection, target, updated, ring)
            _refresh_edge_provenance(collection, target)
            target["geometry_source"] = "user_override"
            if collection == "obstacles":
                target.setdefault("dimensions", {})["parameterization_valid"] = False

        self._mutate(operation)

    def edit_plane(self, entity_id: str, *, slope_deg: float, azimuth_deg: float,
                   base_elevation_m: float, elevation_reference=None) -> None:
        collection, entity = self._find(entity_id)
        self._assert_editable(entity)
        if collection != "surfaces":
            raise ValueError("edit_plane requires a surface")
        if not 0 <= float(azimuth_deg) < 360:
            raise ValueError("azimuth_deg must be within [0, 360)")
        values = dict(slope_deg=float(slope_deg), azimuth_deg=float(azimuth_deg),
                      base_elevation_m=float(base_elevation_m), elevation_reference=deepcopy(elevation_reference))
        SurfacePlane.from_surface({**entity, **values})

        def operation():
            _, target = self._find(entity_id)
            target.update(values)
            target["geometry_source"] = "user_override"
            _refresh_edge_provenance(collection, target)

        self._mutate(operation)

    def add_hole(self, entity_id: str, *, vertices) -> None:
        collection, entity = self._find(entity_id)
        self._assert_editable(entity)
        if collection != "surfaces":
            raise ValueError("add_hole requires a surface")
        resolved = validate_polygon(vertices, normalize=False)

        def operation():
            _, target = self._find(entity_id)
            target["boundary_2d"].setdefault("holes", []).append([list(point) for point in resolved])
            _validate_surface_holes(target)
            target["geometry_source"] = "user_override"
            _refresh_edge_provenance(collection, target)

        self._mutate(operation)

    def remove_hole(self, entity_id: str, *, hole_index: int) -> None:
        collection, entity = self._find(entity_id)
        self._assert_editable(entity)
        if collection != "surfaces":
            raise ValueError("remove_hole requires a surface")
        if not isinstance(hole_index, int) or isinstance(hole_index, bool):
            raise ValueError("hole_index must be an integer")
        if not 0 <= hole_index < len(entity["boundary_2d"].get("holes", [])):
            raise IndexError("hole_index is outside geometry")

        def operation():
            _, target = self._find(entity_id)
            del target["boundary_2d"]["holes"][hole_index]
            target["geometry_source"] = "user_override"
            _refresh_edge_provenance(collection, target)

        self._mutate(operation)

    def edit_height(self, entity_id: str, *, height_m: float) -> None:
        collection, entity = self._find(entity_id)
        self._assert_editable(entity)
        if collection != "obstacles":
            raise ValueError("edit_height requires an obstacle")
        height = float(height_m)
        if not math.isfinite(height) or height < 0:
            raise ValueError("height_m must be finite and non-negative")

        def operation():
            _, target = self._find(entity_id)
            target["height_m"] = height
            target.setdefault("dimensions", {})["parameterization_valid"] = False
            target["geometry_source"] = "user_override"
            _refresh_edge_provenance(collection, target)

        self._mutate(operation)

    def edit_exact_dimension(
        self,
        entity_id: str,
        *,
        edge_index: int,
        length_m: float,
        preserve: str = "start",
        source: str = "user_override",
    ) -> None:
        if source not in DIMENSION_SOURCES:
            raise ValueError(f"unsupported geometry source: {source}")
        collection, entity = self._find(entity_id)
        self._assert_editable(entity)
        points = _entity_points(collection, entity)
        count = _edge_count(collection, entity)
        if edge_index < 0 or edge_index >= count:
            raise IndexError("edge_index is outside geometry")
        end_index = (edge_index + 1) % len(points)
        original_length = segment_length(
            points[edge_index], points[end_index]
        )
        updated = set_edge_length(
            points,
            edge_index,
            length_m,
            preserve=preserve,
            closed=_closed(collection),
        )

        if preserve == "rectangle" and collection in {"surfaces", "obstacles"}:
            anchor = entity.get("reference_anchor", {})
            before = _reference_point(points, anchor)
            after = _reference_point(updated, anchor)
            updated = translate_points(updated, before[0] - after[0], before[1] - after[1])

        def operation():
            _, target = self._find(entity_id)
            _set_entity_points(collection, target, updated)
            _update_edge_provenance(
                target,
                edge_index=edge_index,
                original_value_m=original_length,
                value_m=length_m,
                source=source,
            )
            _refresh_edge_provenance(
                collection,
                target,
                explicit_edge_index=edge_index,
            )
            if collection == "obstacles":
                target.setdefault("dimensions", {})[
                    "parameterization_valid"
                ] = False
            target["geometry_source"] = source

        self._mutate(operation)

    def edit_exact_angle(
        self,
        entity_id: str,
        *,
        edge_index: int,
        azimuth_deg: float,
        preserve: str = "start",
    ) -> None:
        collection, entity = self._find(entity_id)
        self._assert_editable(entity)
        updated = set_edge_azimuth(
            _entity_points(collection, entity),
            edge_index,
            azimuth_deg,
            preserve=preserve,
            closed=_closed(collection),
        )

        def operation():
            _, target = self._find(entity_id)
            _set_entity_points(collection, target, updated)
            target.setdefault("metadata", {})[
                "last_angle_override"
            ] = {
                "edge_index": edge_index,
                "azimuth_deg": float(azimuth_deg) % 360.0,
                "source": "user_override",
            }
            _refresh_edge_provenance(collection, target)
            if collection == "obstacles":
                target.setdefault("dimensions", {})[
                    "parameterization_valid"
                ] = False
            target["geometry_source"] = "user_override"

        self._mutate(operation)

    def edit_elevation(
        self,
        entity_id: str,
        *,
        base_elevation_m: float,
    ) -> None:
        def operation():
            _, entity = self._find(entity_id)
            self._assert_editable(entity)
            entity["base_elevation_m"] = float(base_elevation_m)
            entity.setdefault("metadata", {})[
                "elevation_source"
            ] = "user_override"

        self._mutate(operation)

    def measure_edge(
        self,
        entity_id: str,
        *,
        edge_index: int,
    ) -> dict:
        collection, entity = self._find(entity_id)
        points = _entity_points(collection, entity)
        count = _edge_count(collection, entity)
        if edge_index < 0 or edge_index >= count:
            raise IndexError("edge_index is outside geometry")
        end_index = (edge_index + 1) % len(points)
        start = points[edge_index]
        end = points[end_index]
        provenance = next(
            (
                value
                for value in entity.get("edge_dimension_sources", [])
                if value.get("edge_index") == edge_index
            ),
            None,
        )
        return {
            "entity_id": _entity_id(entity),
            "edge_index": edge_index,
            "start": list(start),
            "end": list(end),
            "length_m": segment_length(start, end),
            "azimuth_deg": segment_azimuth_deg(start, end),
            "dimension_source": (
                provenance.get("source")
                if provenance is not None
                else entity.get("geometry_source", "unknown")
            ),
        }

    def align(
        self,
        entity_ids: Sequence[str],
        *,
        mode: str,
        reference_entity_id: str | None = None,
    ) -> None:
        ids = tuple(entity_ids)
        if len(ids) < 2:
            return
        reference_id = reference_entity_id or ids[0]
        ref_collection, ref_entity = self._find(reference_id)
        ref_box = bounding_box(
            _entity_points(ref_collection, ref_entity)
        )

        def target_value(box):
            if mode == "min_x":
                return box[0]
            if mode == "max_x":
                return box[2]
            if mode == "center_x":
                return (box[0] + box[2]) / 2.0
            if mode == "min_y":
                return box[1]
            if mode == "max_y":
                return box[3]
            if mode == "center_y":
                return (box[1] + box[3]) / 2.0
            raise ValueError("unsupported align mode")

        reference_value = target_value(ref_box)

        def operation():
            for entity_id in ids:
                if entity_id == reference_id:
                    continue
                collection, entity = self._find(entity_id)
                self._assert_editable(entity)
                points = _entity_points(collection, entity)
                box = bounding_box(points)
                delta = reference_value - target_value(box)
                dx = delta if mode.endswith("x") else 0.0
                dy = delta if mode.endswith("y") else 0.0
                _set_entity_points(
                    collection,
                    entity,
                    translate_points(points, dx, dy),
                )

        self._mutate(operation)

    def distribute(
        self,
        entity_ids: Sequence[str],
        *,
        axis: str,
    ) -> None:
        ids = tuple(entity_ids)
        if len(ids) < 3:
            raise ValueError("distribute requires at least three entities")
        if axis not in {"x", "y"}:
            raise ValueError("axis must be x or y")

        records = []
        for entity_id in ids:
            collection, entity = self._find(entity_id)
            box = bounding_box(_entity_points(collection, entity))
            center = (
                (box[0] + box[2]) / 2.0
                if axis == "x"
                else (box[1] + box[3]) / 2.0
            )
            records.append((center, entity_id))
        records.sort(key=lambda item: (item[0], item[1]))
        start = records[0][0]
        end = records[-1][0]
        spacing = (end - start) / (len(records) - 1)

        def operation():
            for index, (current, entity_id) in enumerate(records):
                if index in {0, len(records) - 1}:
                    continue
                target = start + spacing * index
                collection, entity = self._find(entity_id)
                self._assert_editable(entity)
                points = _entity_points(collection, entity)
                dx = target - current if axis == "x" else 0.0
                dy = target - current if axis == "y" else 0.0
                _set_entity_points(
                    collection,
                    entity,
                    translate_points(points, dx, dy),
                )

        self._mutate(operation)

    def _building_targets(self, entity_ids):
        ids = tuple(entity_ids)
        if not ids:
            raise ValueError("a building command requires at least one entity")
        targets = []
        for entity_id in ids:
            try:
                collection, entity = self._find(entity_id)
            except KeyError as exc:
                raise ValueError(f"unknown entity: {entity_id}") from exc
            if collection == "obstacles" and entity.get("obstacle_type") == "imported_mesh":
                self._assert_editable(entity)
            if entity.get("locked", False):
                raise ValueError(f"entity {entity_id} is locked")
            targets.append(entity)
        return targets

    def _default_building_name(self):
        used = {b["name"] for b in self._scene.get("buildings", [])}
        number = 1
        while f"Building {number}" in used:
            number += 1
        return f"Building {number}"

    def _upkeep_buildings(self):
        buildings = self._scene.get("buildings", [])
        ids = [b["building_id"] for b in buildings]
        if len(set(ids)) != len(ids):
            raise ValueError("building_id must be unique")
        used = list(dict.fromkeys(e["group_id"] for kind in _COLLECTIONS for e in self._scene.get(kind, [])
                                  if e.get("group_id") is not None))
        for group_id in used:
            if group_id not in ids:
                self._scene.setdefault("buildings", []).append({"building_id": group_id, "name": self._default_building_name()})
                ids.append(group_id)
        buildings = self._scene.get("buildings", [])
        if "buildings" in self._scene:
            self._scene["buildings"] = [b for b in buildings if b["building_id"] in used]

    def group(self, entity_ids: Iterable[str], *, group_id: str, name: str | None = None) -> None:
        targets = self._building_targets(entity_ids)
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError("group_id must not be empty")
        if name is not None and (not isinstance(name, str) or not name.strip() or len(name) > 80):
            raise ValueError("building name must contain 1 to 80 characters")
        existing = next((b for b in self._scene.get("buildings", []) if b["building_id"] == group_id), None)

        def operation():
            if existing is None:
                self._scene.setdefault("buildings", []).append({"building_id": group_id, "name": name.strip() if name is not None else self._default_building_name()})
            elif name is not None:
                existing["name"] = name.strip()
            for entity in targets:
                entity["group_id"] = group_id
            self._upkeep_buildings()

        self._mutate(operation, synchronize=False)

    def ungroup(self, entity_ids: Iterable[str]) -> None:
        targets = self._building_targets(entity_ids)

        def operation():
            for entity in targets:
                entity["group_id"] = None
            self._upkeep_buildings()

        self._mutate(operation, synchronize=False)

    def set_reference_anchor(self, entity_id: str, *, u: str, v: str) -> None:
        if u not in {"start", "center", "end"} or v not in {"start", "center", "end"}:
            raise ValueError("reference anchor must be start, center, or end")
        collection, entity = self._find(entity_id)
        if collection not in {"surfaces", "obstacles"}:
            raise ValueError("reference anchor requires a surface or obstacle")
        self._assert_editable(entity)
        self._mutate(lambda: entity.update(reference_anchor={"u": u, "v": v}), synchronize=False)

    def set_locked(
        self,
        entity_ids: Iterable[str],
        *,
        locked: bool,
    ) -> None:
        ids = tuple(entity_ids)

        def operation():
            for entity_id in ids:
                _, entity = self._find(entity_id)
                if entity.get("locked", False) and locked:
                    continue
                entity["locked"] = bool(locked)

        self._mutate(operation)

    def set_visible(
        self,
        entity_ids: Iterable[str],
        *,
        visible: bool,
    ) -> None:
        ids = tuple(entity_ids)

        def operation():
            for entity_id in ids:
                _, entity = self._find(entity_id)
                entity["visible"] = bool(visible)

        self._mutate(operation)
        if not visible:
            hidden = set(ids)
            self._selection = [
                value
                for value in self._selection
                if value not in hidden
            ]

    def geometry_batch(self, operations, module_definitions):
        from .bulk import apply_geometry_operations
        effects=[]
        redo=list(self._redo)
        def operation():
            effects.extend(apply_geometry_operations(self._scene,operations,module_definitions))
        self._mutate(operation,synchronize=False)
        if canonical_scene_json(self._scene) == canonical_scene_json(self._undo[-1]):
            self._scene=self._undo.pop()
            self._redo=redo
        return effects

    def snap_engine(self, **kwargs) -> SnapEngine:
        if any(o.get('obstacle_type')=='imported_mesh' for o in self._scene.get('obstacles',[])):
            scene={**self._scene,'obstacles':[o for o in self._scene['obstacles'] if o.get('obstacle_type')!='imported_mesh']}
            return SnapEngine(scene, **kwargs)
        return SnapEngine(self._scene, **kwargs)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(deepcopy(self._scene))
        self._scene = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(deepcopy(self._scene))
        self._scene = self._redo.pop()
        return True

    def commit_revision(
        self,
        *,
        revision_id: str,
        revision_number: int,
        change_summary: str,
        created_by: str | None = None,
        created_at: str | None = None,
        status: str = "active",
    ) -> dict:
        if not revision_id:
            raise ValueError("revision_id must not be empty")
        if revision_number < 1:
            raise ValueError("revision_number must be at least 1")
        previous_revision_id = self._scene["revision_id"]
        committed = deepcopy(self._scene)
        committed["revision_id"] = revision_id
        committed["revision_number"] = revision_number
        committed["supersedes_revision_id"] = previous_revision_id
        committed["change_summary"] = change_summary
        committed["created_by"] = created_by
        committed["created_at"] = created_at or datetime.now(
            timezone.utc
        ).isoformat().replace("+00:00", "Z")
        committed["status"] = status
        self._scene = deepcopy(committed)
        self._undo.clear()
        self._redo.clear()
        self._selection.clear()
        return committed
