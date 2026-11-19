"""Deterministic PV field packing over canonical Phase-4 scene geometry."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from geometry.scene.geometry2d import polygon_segments
from geometry.scene.surface_plane import module_center_z

from .geometry import (
    edge_azimuth_deg,
    field_bounds,
    field_to_scene,
    polygon_contains_polygon,
    polygon_distance,
    polygons_overlap_or_touch,
    polygons_overlap_strict,
    rectangle_polygon,
)
from .identity import (
    MODULE_IDENTITY_VERSION,
    generated_module_id,
    placement_fingerprint,
    replacement_generated_module_id,
)
from .models import (
    ModuleFootprint,
    PACKING_COMMAND_VERSION,
    PackingConflict,
    PackingResult,
)


def _surface(scene: Mapping[str, Any], surface_id: str) -> dict[str, Any]:
    for surface in scene.get("surfaces", []):
        if surface.get("surface_id") == surface_id:
            return surface
    raise KeyError(f"support surface not found: {surface_id}")


def _field(scene: Mapping[str, Any], pv_field_id: str) -> dict[str, Any]:
    for field in scene.get("pv_fields", []):
        if field.get("pv_field_id") == pv_field_id:
            return field
    raise KeyError(f"PV field not found: {pv_field_id}")


def _surface_vertices(surface: Mapping[str, Any]) -> list[tuple[float, float]]:
    return [tuple(point) for point in surface["boundary_2d"]["vertices"]]


def _obstacle_vertices(obstacle: Mapping[str, Any]) -> list[tuple[float, float]]:
    return [tuple(point) for point in obstacle["footprint"]["vertices"]]


def _resolved_exclusions(
    scene: Mapping[str, Any],
    field: Mapping[str, Any],
    support: Mapping[str, Any],
) -> tuple[
    list[tuple[str, list[tuple[float, float]]]],
    list[tuple[str, list[tuple[float, float]]]],
]:
    rules = field.get("exclusion_rules") or {}
    support_id = support["surface_id"]
    support_vertices = _surface_vertices(support)

    explicit_surface_ids = set(rules.get("surface_ids") or [])
    use_scene_surfaces = bool(rules.get("use_scene_exclusion_surfaces", True))
    surface_types = set(
        rules.get("surface_types") or ["exclusion_area", "walkway"]
    )
    exclusion_surfaces: list[
        tuple[str, list[tuple[float, float]]]
    ] = []
    for item in scene.get("surfaces", []):
        if item.get("surface_id") == support_id:
            continue
        selected = item.get("surface_id") in explicit_surface_ids
        selected = selected or (
            use_scene_surfaces and item.get("surface_type") in surface_types
        )
        if not selected:
            continue
        vertices = _surface_vertices(item)
        if polygons_overlap_or_touch(support_vertices, vertices):
            exclusion_surfaces.append((str(item["surface_id"]), vertices))

    explicit_obstacle_ids = set(rules.get("obstacle_ids") or [])
    use_scene_obstacles = bool(rules.get("use_scene_obstacles", True))
    obstacles: list[tuple[str, list[tuple[float, float]]]] = []
    for obstacle in scene.get("obstacles", []):
        selected = obstacle.get("obstacle_id") in explicit_obstacle_ids
        selected = selected or use_scene_obstacles
        if not selected:
            continue
        vertices = _obstacle_vertices(obstacle)
        if polygons_overlap_or_touch(support_vertices, vertices):
            obstacles.append((str(obstacle["obstacle_id"]), vertices))

    exclusion_surfaces.sort(key=lambda item: item[0])
    obstacles.sort(key=lambda item: item[0])
    return exclusion_surfaces, obstacles


def _packing_snapshot(
    scene: Mapping[str, Any],
    field: Mapping[str, Any],
    support: Mapping[str, Any],
    footprint: ModuleFootprint,
) -> dict[str, Any]:
    exclusion_surfaces, obstacles = _resolved_exclusions(
        scene, field, support
    )
    return {
        "packing_command_version": PACKING_COMMAND_VERSION,
        "support_surface_id": support["surface_id"],
        "support_boundary_2d": support["boundary_2d"],
        "support_base_elevation_m": support.get("base_elevation_m", 0.0),
        "support_slope_deg": support.get("slope_deg", 0.0),
        "support_azimuth_deg": support.get("azimuth_deg", 0.0),
        "support_elevation_reference": support.get("elevation_reference"),
        "coordinate_basis": "horizontal_engineering_xy",
        "module_footprint": footprint.to_mapping(),
        "orientation": field["orientation"],
        "azimuth_deg": field["azimuth_deg"],
        "tilt_deg": field["tilt_deg"],
        "mounting_height_m": field["mounting_height_m"],
        "module_gap_x_m": field["module_gap_x_m"],
        "module_gap_y_m": field["module_gap_y_m"],
        "row_pitch_m": field["row_pitch_m"],
        "setback_configuration": field.get("setback_configuration") or {},
        "table_configuration": field.get("table_configuration"),
        "packing_parameters": field.get("packing_parameters") or {},
        "exclusion_rules": field.get("exclusion_rules") or {},
        "resolved_exclusion_surfaces": [
            {"entity_id": entity_id, "vertices": vertices}
            for entity_id, vertices in exclusion_surfaces
        ],
        "resolved_obstacles": [
            {"entity_id": entity_id, "vertices": vertices}
            for entity_id, vertices in obstacles
        ],
    }


def packing_input_hash(
    scene: Mapping[str, Any],
    field: Mapping[str, Any],
    footprint: ModuleFootprint | None = None,
) -> str:
    support = _surface(scene, str(field["support_surface_id"]))
    if footprint is None:
        stored = field.get("module_footprint") or {}
        footprint = ModuleFootprint.from_mapping(
            stored,
            fallback_tilt_deg=float(field.get("tilt_deg", 0.0)),
        )
    encoded = json.dumps(
        _packing_snapshot(scene, field, support, footprint),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _x_positions(
    min_x: float,
    max_x: float,
    *,
    width_m: float,
    module_gap_m: float,
    perimeter_setback_m: float,
    row_alignment: str,
    table_configuration: Mapping[str, Any] | None,
) -> list[float]:
    left = min_x + perimeter_setback_m + width_m / 2.0
    right = max_x - perimeter_setback_m - width_m / 2.0
    if right < left - 1e-12:
        return []

    modules_per_table = 1
    table_gap = module_gap_m
    if table_configuration:
        modules_per_table = int(
            table_configuration.get("modules_per_table_x") or 1
        )
        if modules_per_table < 1:
            raise ValueError("modules_per_table_x must be at least one")
        raw_table_gap = table_configuration.get("table_gap_x_m")
        if raw_table_gap is not None:
            table_gap = float(raw_table_gap)
            if table_gap < 0.0:
                raise ValueError("table_gap_x_m must be non-negative")

    positions = [left]
    next_column = 1
    while True:
        gap = (
            table_gap
            if next_column % modules_per_table == 0
            else module_gap_m
        )
        candidate = positions[-1] + width_m + gap
        if candidate > right + 1e-12:
            break
        positions.append(candidate)
        next_column += 1

    used_width = positions[-1] - positions[0] + width_m
    available_width = max_x - min_x - 2.0 * perimeter_setback_m
    slack = max(0.0, available_width - used_width)
    if row_alignment == "start":
        shift = 0.0
    elif row_alignment == "center":
        shift = slack / 2.0
    elif row_alignment == "end":
        shift = slack
    else:
        raise ValueError("row_alignment must be start, center, or end")
    return [value + shift for value in positions]


def _candidate_valid(
    polygon: Sequence[tuple[float, float]],
    support_vertices: Sequence[tuple[float, float]],
    exclusion_surfaces: Sequence[
        tuple[str, Sequence[tuple[float, float]]]
    ],
    obstacles: Sequence[tuple[str, Sequence[tuple[float, float]]]],
    *,
    perimeter_setback_m: float,
    obstacle_setback_m: float,
    support_holes: Sequence[Sequence[tuple[float, float]]] = (),
) -> bool:
    if not polygon_contains_polygon(
        support_vertices,
        polygon,
        clearance_m=perimeter_setback_m,
    ):
        return False
    for hole in support_holes:
        if polygons_overlap_or_touch(polygon, hole):
            return False
        if perimeter_setback_m > 0 and polygon_distance(polygon, hole) < perimeter_setback_m - 1e-9:
            return False
    for _, excluded in exclusion_surfaces:
        if polygons_overlap_or_touch(polygon, excluded):
            return False
    for _, obstacle in obstacles:
        if polygons_overlap_or_touch(polygon, obstacle):
            return False
        if (
            obstacle_setback_m > 0.0
            and polygon_distance(polygon, obstacle)
            < obstacle_setback_m - 1e-9
        ):
            return False
    return True


def _phase_estimator(support_vertices, support_holes, exclusion_surfaces, obstacles, perimeter_setback,
                     obstacle_setback, x_positions, azimuth, footprint, requested_rows, requested_per_row):
    """A vectorised upper bound of the exact accepted count; never the placement rule."""
    try:
        import numpy as np
        import shapely
        from shapely.geometry import Polygon
    except ImportError:  # pragma: no cover - shapely is a runtime dependency
        return None
    tolerance = 1e-7  # Widen beyond the exact geometry rule's 1e-9 boundary tolerance.
    allowed = Polygon(support_vertices).buffer(tolerance - perimeter_setback)
    for hole in support_holes:
        allowed = allowed.difference(Polygon(hole).buffer(perimeter_setback - tolerance))
    for _, excluded in exclusion_surfaces:
        allowed = allowed.difference(Polygon(excluded).buffer(-tolerance))
    for _, obstacle in obstacles:
        allowed = allowed.difference(Polygon(obstacle).buffer(obstacle_setback - tolerance))
    if allowed.is_empty:
        return lambda rows: 0
    shapely.prepare(allowed)
    xs = np.asarray(list(x_positions), dtype=float)
    hw, hh = footprint.plan_projection_width_m / 2.0, footprint.plan_projection_height_m / 2.0

    def count(rows):
        if not len(xs) or not rows:
            return 0
        counts = []
        for y in rows:
            # The exact containment rule checks corners and edge midpoints, even on concave supports.
            probes = [field_to_scene((x + dx, y + dy), azimuth) for x in xs for dx, dy in
                      ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh), (0, -hh), (hw, 0), (0, hh), (-hw, 0))]
            points = shapely.points(np.asarray(probes, dtype=float).reshape(len(xs), 8, 2))
            inside = int(np.count_nonzero(np.all(shapely.covers(allowed, points), axis=1)))
            if requested_per_row is not None:
                inside = min(inside, int(requested_per_row))
            counts.append(inside)
        # Optimistic false positives must not consume the requested-row budget before better rows.
        return sum(sorted(counts, reverse=True)[:int(requested_rows)]) if requested_rows is not None else sum(counts)

    return count


# USE-D14: candidate row-grid offsets per pitch tried by the packer.
ROW_PHASE_STEPS = 16


def _table_rows(low: float, high: float, length: float, gap: float, tilt: float,
                pitch: float, rows: int, leftover: str, offset: float) -> list[tuple[float, int, int]]:
    """Module-row centres, table lineage and front-row offsets, sorted back to front."""
    cosine = math.cos(math.radians(tilt))
    step = (length + gap) * cosine
    depth = lambda count: (count * length + (count - 1) * gap) * cosine
    aisle = max(0.0, pitch - depth(rows))
    front_first = leftover == "smaller_table"
    edge = high - offset if front_first else low + offset
    result = []
    table = 0
    while True:
        available = edge - low if front_first else high - edge
        count = rows
        if leftover != "leave_empty":
            while count > 0 and depth(count) > available + 1e-12:
                count -= 1
        if count < 1 or depth(count) > available + 1e-12:
            break
        front = edge if front_first else edge + depth(count)
        result.extend((front - length * cosine / 2 - k * step, table, k) for k in range(count))
        edge += -(depth(count) + aisle) if front_first else depth(count) + aisle
        table += 1
    return sorted(result)


def pack_field(
    scene: Mapping[str, Any],
    pv_field: Mapping[str, Any],
    module_definition: Mapping[str, Any],
) -> PackingResult:
    """Pack horizontal plan projections of physical module planes.

    Scene X/Y and support boundary_2d are horizontal engineering-plan
    coordinates. The module physical plane remains defined by component
    dimensions + orientation + tilt; its XY packing footprint is the horizontal
    projection of that plane.
    """
    field = deepcopy(dict(pv_field))
    orientation = str(field["orientation"])
    footprint = ModuleFootprint.from_definition(
        module_definition,
        orientation,
        float(field.get("tilt_deg", 0.0)),
    )
    if footprint.module_definition_revision_id != str(
        field["module_definition_revision_id"]
    ):
        raise ValueError(
            "field module_definition_revision_id does not match supplied component revision"
        )

    support = _surface(scene, str(field["support_surface_id"]))
    if support.get("usable_for_pv") is False:
        raise ValueError("support surface is not usable_for_pv")
    support_vertices = _surface_vertices(support)
    support_holes = support["boundary_2d"].get("holes", [])

    azimuth = float(field["azimuth_deg"]) % 360.0
    gap_x = float(field["module_gap_x_m"])
    gap_y = float(field["module_gap_y_m"])
    row_pitch = float(field["row_pitch_m"])
    if min(gap_x, gap_y, row_pitch) < 0.0:
        raise ValueError("module gaps and row pitch must be non-negative")
    table_config = field.get("table_configuration") or {}
    rows_per_table = table_config.get("rows_per_table", 1)
    leftover = table_config.get("leftover_depth", "smaller_table")
    if type(rows_per_table) is not int or rows_per_table < 1:
        raise ValueError("rows_per_table must be a positive integer")
    if leftover not in {"smaller_table", "smaller_table_front", "leave_empty"}:
        raise ValueError("unsupported leftover_depth")
    if rows_per_table > 1:
        field["module_footprint"] = footprint.to_mapping()
    minimum_pitch = ((rows_per_table * footprint.packed_height_m + (rows_per_table - 1) * gap_y)
                     * math.cos(math.radians(footprint.tilt_deg)) if rows_per_table > 1
                     else footprint.plan_projection_height_m + gap_y)
    if row_pitch + 1e-12 < minimum_pitch:
        raise ValueError(
            "tables would overlap" if rows_per_table > 1 else "row_pitch_m must be at least packed module height + module_gap_y_m"
        )

    setback = field.get("setback_configuration") or {}
    perimeter_setback = float(setback.get("perimeter_setback_m") or 0.0)
    obstacle_setback = float(setback.get("obstacle_setback_m") or 0.0)
    if perimeter_setback < 0.0 or obstacle_setback < 0.0:
        raise ValueError("setbacks must be non-negative")
    if setback.get("edge_specific_setbacks"):
        raise ValueError(
            "edge_specific_setbacks are not yet supported by Phase 4.3 packing"
        )

    parameters = field.get("packing_parameters") or {}
    row_alignment = str(parameters.get("row_alignment") or "start")
    depth_alignment = parameters.get("depth_alignment")
    if depth_alignment not in (None, "start", "center", "end"):
        raise ValueError("depth_alignment must be start, center, or end")
    requested_rows = parameters.get("requested_row_count")
    requested_per_row = parameters.get("requested_modules_per_row")
    if rows_per_table > 1 and requested_rows is not None:
        raise ValueError("requested_row_count is unsupported for multi-row tables")
    if requested_rows is not None and int(requested_rows) < 1:
        raise ValueError("requested_row_count must be positive")
    if requested_per_row is not None and int(requested_per_row) < 1:
        raise ValueError("requested_modules_per_row must be positive")

    exclusion_surfaces, obstacles = _resolved_exclusions(
        scene, field, support
    )
    min_x, min_y, max_x, max_y = field_bounds(
        support_vertices, azimuth
    )
    x_positions = _x_positions(
        min_x,
        max_x,
        width_m=footprint.plan_projection_width_m,
        module_gap_m=gap_x,
        perimeter_setback_m=perimeter_setback,
        row_alignment=row_alignment,
        table_configuration=field.get("table_configuration"),
    )

    first_y = (
        min_y + perimeter_setback + footprint.plan_projection_height_m / 2.0
    )
    last_y = (
        max_y - perimeter_setback - footprint.plan_projection_height_m / 2.0
    )
    def table_rows(offset: float):
        return _table_rows(min_y + perimeter_setback, max_y - perimeter_setback,
                           footprint.packed_height_m, gap_y, footprint.tilt_deg, row_pitch,
                           rows_per_table, leftover, offset)

    def rows_from(offset: float) -> list[float]:
        if rows_per_table > 1:
            return [y for y, _, _ in table_rows(offset)]
        values: list[float] = []
        value = first_y + offset
        while value <= last_y + 1e-12:
            values.append(value)
            value += row_pitch
        return values

    def accepted_count(rows: list[float]) -> int:
        total = occupied = 0
        for y in rows:
            if requested_rows is not None and occupied >= int(requested_rows):
                break
            in_row = 0
            for x in x_positions:
                center = field_to_scene((x, y), azimuth)
                polygon = rectangle_polygon(center, footprint.plan_projection_width_m,
                                            footprint.plan_projection_height_m, azimuth)
                if _candidate_valid(polygon, support_vertices, exclusion_surfaces, obstacles,
                                    support_holes=support_holes, perimeter_setback_m=perimeter_setback,
                                    obstacle_setback_m=obstacle_setback):
                    in_row += 1
                    if requested_per_row is not None and in_row >= int(requested_per_row):
                        break
            total += in_row
            occupied += 1 if in_row else 0
        return total

    # USE-D14: a roof edge slightly off the rows can reject a whole row at the anchored phase. Slide the row grid in
    # steps of 1/ROW_PHASE_STEPS of the pitch. Upper bounds order exact checks and prune only proven ties or worse.
    chosen_offset = 0.0
    y_positions = rows_from(0.0)
    estimate = _phase_estimator(support_vertices, support_holes, exclusion_surfaces, obstacles, perimeter_setback,
                                obstacle_setback, x_positions, azimuth, footprint, requested_rows, requested_per_row)
    if estimate is not None:
        scores = [estimate(rows_from(row_pitch * step / ROW_PHASE_STEPS)) for step in range(ROW_PHASE_STEPS)]
        best_count = accepted_count(y_positions)
        for step in sorted(range(1, ROW_PHASE_STEPS), key=lambda k: (-scores[k], k)):
            if scores[step] <= best_count:
                break
            candidate = rows_from(row_pitch * step / ROW_PHASE_STEPS)
            count = accepted_count(candidate)
            if count > best_count:
                y_positions = candidate
                chosen_offset = row_pitch * step / ROW_PHASE_STEPS
                best_count = count
    # UXF1 (U2-6): an across-row anchor moves the rows within the leftover depth (start = back/high side at min y,
    # end = front/low side), but only among offsets that keep the highest module count found above.
    if depth_alignment is not None and y_positions:
        best_count = accepted_count(y_positions)
        base = rows_from(0.0)
        slack = min(row_pitch, max(0.0, last_y - base[-1])) if base else 0.0
        target = {"start": 0.0, "center": slack / 2.0, "end": slack}[depth_alignment]
        offsets = {target, *(row_pitch * k / ROW_PHASE_STEPS for k in range(ROW_PHASE_STEPS))}
        for offset in sorted(offsets, key=lambda value: (abs(value - target), value)):
            candidate = rows_from(offset)
            if candidate and accepted_count(candidate) >= best_count:
                y_positions, chosen_offset = candidate, offset
                break

    result_modules: list[dict[str, Any]] = []
    row_layouts: list[dict[str, Any]] = []
    rejected = 0
    occupied_row_index = 0
    table_index = 0
    modules_per_table = int(
        (field.get("table_configuration") or {}).get(
            "modules_per_table_x"
        )
        or 1
    )

    table_lineage = {y: (table, k) for y, table, k in table_rows(chosen_offset)} if rows_per_table > 1 else {}
    multi_table_ids = {}
    if rows_per_table > 1:
        columns_by_table = {}
        for y in y_positions:
            table, _ = table_lineage[y]
            columns = columns_by_table.setdefault(table, set())
            accepted_columns = []
            for column, x in enumerate(x_positions):
                polygon = rectangle_polygon(field_to_scene((x, y), azimuth), footprint.plan_projection_width_m,
                                            footprint.plan_projection_height_m, azimuth)
                if _candidate_valid(polygon, support_vertices, exclusion_surfaces, obstacles,
                                    perimeter_setback_m=perimeter_setback, obstacle_setback_m=obstacle_setback,
                                    support_holes=support_holes):
                    accepted_columns.append(column)
                    if requested_per_row is not None and len(accepted_columns) >= int(requested_per_row):
                        break
            columns.update(accepted_columns)
        next_table = 0
        for table, columns in columns_by_table.items():
            previous, used = None, 0
            for column in sorted(columns):
                if previous is None or column != previous + 1 or used >= modules_per_table:
                    index = next_table
                    next_table += 1
                    used = 0
                multi_table_ids[table, column] = index
                previous = column
                used += 1
    for grid_row, y in enumerate(y_positions):
        if (
            requested_rows is not None
            and occupied_row_index >= int(requested_rows)
        ):
            break
        accepted: list[
            tuple[
                int,
                tuple[float, float],
                list[tuple[float, float]],
            ]
        ] = []
        for grid_column, x in enumerate(x_positions):
            center = field_to_scene((x, y), azimuth)
            polygon = rectangle_polygon(
                center,
                footprint.plan_projection_width_m,
                footprint.plan_projection_height_m,
                azimuth,
            )
            if not _candidate_valid(
                polygon,
                support_vertices,
                exclusion_surfaces,
                obstacles,
                support_holes=support_holes,
                perimeter_setback_m=perimeter_setback,
                obstacle_setback_m=obstacle_setback,
            ):
                rejected += 1
                continue
            accepted.append((grid_column, center, polygon))
            if (
                requested_per_row is not None
                and len(accepted) >= int(requested_per_row)
            ):
                break

        if not accepted:
            continue

        module_ids: list[str] = []
        previous_grid_column: int | None = None
        in_table_count = 0
        for occupied_column, (
            grid_column,
            center,
            _,
        ) in enumerate(accepted):
            if (
                previous_grid_column is None
                or grid_column != previous_grid_column + 1
                or in_table_count >= modules_per_table
            ):
                if previous_grid_column is not None:
                    table_index += 1
                in_table_count = 0
            module = {
                "module_instance_id": "",
                "pv_field_id": field["pv_field_id"],
                "module_definition_revision_id": (
                    footprint.module_definition_revision_id
                ),
                "transform": {
                    "position_x_m": center[0],
                    "position_y_m": center[1],
                    "position_z_m": module_center_z(
                        support, center[0], center[1], float(field["mounting_height_m"]),
                        field=field, table_row_offset=table_lineage[y][1] if rows_per_table > 1 else 0,
                    ),
                    "rotation_x_deg": 0.0,
                    "rotation_y_deg": 0.0,
                    "rotation_z_deg": azimuth,
                    "scale_x": 1.0,
                    "scale_y": 1.0,
                    "scale_z": 1.0,
                },
                "row_index": occupied_row_index,
                "column_index": occupied_column,
                "table_index": table_index,
                "enabled": True,
                "electrical_connection_id": None,
                "metadata": {
                    "packing_command_version": PACKING_COMMAND_VERSION,
                    "grid_row_index": grid_row,
                    "grid_column_index": grid_column,
                    "manual_position_override": False,
                    "module_identity_version": MODULE_IDENTITY_VERSION,
                    "position_z_basis": "support_plane_plus_vertical_mounting_height",
                },
            }
            if rows_per_table > 1:
                table, k = table_lineage[y]
                module["table_index"] = multi_table_ids[table, grid_column]
                module["metadata"]["table_row_offset"] = k
                if k:
                    module["metadata"]["position_z_basis"] = "table_plane_from_front_row.v1"
            module_id = generated_module_id(field, module)
            module["module_instance_id"] = module_id
            module["metadata"]["placement_fingerprint"] = (
                placement_fingerprint(field, module)
            )
            module["metadata"]["identity_origin"] = "generated"
            module_ids.append(module_id)
            result_modules.append(module)
            previous_grid_column = grid_column
            in_table_count += 1
        table_index += 1
        row_layouts.append(
            {
                "row_index": occupied_row_index,
                "field_y_m": y,
                "module_count": len(module_ids),
                "module_instance_ids": module_ids,
            }
        )
        occupied_row_index += 1

    field["row_count"] = len(row_layouts)
    field["modules_per_row"] = max(
        (row["module_count"] for row in row_layouts), default=0
    )
    field["generated_module_instance_ids"] = [
        module["module_instance_id"] for module in result_modules
    ]
    field["row_layouts"] = row_layouts
    field["module_footprint"] = footprint.to_mapping()
    field["packing_command_version"] = PACKING_COMMAND_VERSION
    field["layout_source"] = "fill_command"
    field["layout_status"] = "packed"
    field["resolved_exclusion_ids"] = list(
        dict.fromkeys(
            [entity_id for entity_id, _ in exclusion_surfaces]
            + [entity_id for entity_id, _ in obstacles]
        )
    )
    input_hash = packing_input_hash(scene, field, footprint)
    field["packing_input_hash"] = input_hash

    return PackingResult(
        pv_field=field,
        module_instances=tuple(result_modules),
        rejected_candidate_count=rejected,
        packing_input_hash=input_hash,
    )


def replace_field_layout(
    scene: Mapping[str, Any],
    result: PackingResult,
) -> dict[str, Any]:
    """Replace one generated field while preserving only equivalent identities.

    Existing IDs, including Phase-4.3 row/column IDs, survive an explicit
    rebuild only when the new generated placement has the same canonical
    placement fingerprint. Changed placements keep their new deterministic
    placement-derived IDs. Electrical topology is deliberately not modified.
    """
    updated = deepcopy(dict(scene))
    field_id = str(result.pv_field["pv_field_id"])
    new_field = deepcopy(result.pv_field)
    old_field = next(
        (
            item
            for item in scene.get("pv_fields", [])
            if item.get("pv_field_id") == field_id
        ),
        None,
    )
    old_modules = [
        deepcopy(item)
        for item in scene.get("module_instances", [])
        if item.get("pv_field_id") == field_id
    ]
    new_modules = deepcopy(list(result.module_instances))

    old_by_fingerprint: dict[str, list[dict[str, Any]]] = {}
    old_by_id = {
        str(module["module_instance_id"]): module
        for module in old_modules
    }
    if old_field is not None:
        for module in old_modules:
            fingerprint = placement_fingerprint(old_field, module)
            old_by_fingerprint.setdefault(fingerprint, []).append(module)
        for modules in old_by_fingerprint.values():
            modules.sort(key=lambda item: str(item["module_instance_id"]))

    id_map: dict[str, str] = {}
    used_old_ids: set[str] = set()
    final_ids: set[str] = set()
    for module in new_modules:
        provisional_id = str(module["module_instance_id"])
        fingerprint = placement_fingerprint(new_field, module)
        preserved_id = None
        for candidate in old_by_fingerprint.get(fingerprint, []):
            candidate_id = str(candidate["module_instance_id"])
            if candidate_id not in used_old_ids:
                preserved_id = candidate_id
                used_old_ids.add(candidate_id)
                break
        final_id = preserved_id or provisional_id
        replacement_guarded = False
        if preserved_id is None and old_field is not None:
            conflicting_old = old_by_id.get(final_id)
            if conflicting_old is not None:
                conflicting_fingerprint = placement_fingerprint(
                    old_field, conflicting_old
                )
                if conflicting_fingerprint != fingerprint:
                    replacement_guarded = True
                    disambiguator = 0
                    while True:
                        candidate = replacement_generated_module_id(
                            new_field,
                            module,
                            conflicting_old_id=final_id,
                            conflicting_old_fingerprint=(
                                conflicting_fingerprint
                            ),
                            disambiguator=disambiguator,
                        )
                        if candidate not in final_ids and candidate not in old_by_id:
                            final_id = candidate
                            break
                        disambiguator += 1
        if final_id in final_ids:
            raise ValueError(
                f"generated module identity collision in {field_id}: {final_id}"
            )
        final_ids.add(final_id)
        id_map[provisional_id] = final_id
        module["module_instance_id"] = final_id
        metadata = module.setdefault("metadata", {})
        metadata["module_identity_version"] = MODULE_IDENTITY_VERSION
        metadata["placement_fingerprint"] = fingerprint
        metadata["identity_origin"] = (
            "preserved_equivalent_placement"
            if preserved_id is not None
            else "generated_replacement"
            if replacement_guarded
            else "generated"
        )

    new_field["generated_module_instance_ids"] = [
        id_map.get(str(value), str(value))
        for value in new_field.get("generated_module_instance_ids", [])
    ]
    for row in new_field.get("row_layouts", []):
        row["module_instance_ids"] = [
            id_map.get(str(value), str(value))
            for value in row.get("module_instance_ids", [])
        ]
    new_field.setdefault("metadata", {})["module_identity_version"] = (
        MODULE_IDENTITY_VERSION
    )

    updated["pv_fields"] = [
        deepcopy(new_field)
        if item.get("pv_field_id") == field_id
        else deepcopy(item)
        for item in updated.get("pv_fields", [])
    ]
    if not any(
        item.get("pv_field_id") == field_id
        for item in updated.get("pv_fields", [])
    ):
        updated.setdefault("pv_fields", []).append(deepcopy(new_field))
    updated["module_instances"] = [
        deepcopy(item)
        for item in updated.get("module_instances", [])
        if item.get("pv_field_id") != field_id
    ]
    updated["module_instances"].extend(new_modules)
    return updated


def _stored_footprint(field: Mapping[str, Any]) -> ModuleFootprint:
    stored = field.get("module_footprint")
    if not stored:
        raise ValueError("PV field has no stored module_footprint")
    return ModuleFootprint.from_mapping(
        stored,
        fallback_tilt_deg=float(field.get("tilt_deg", 0.0)),
    )


def validate_field_layout(
    scene: Mapping[str, Any],
    pv_field_id: str,
) -> dict[str, Any]:
    """Inspect current placements without mutating or rebuilding them."""
    field = _field(scene, pv_field_id)
    support = _surface(scene, str(field["support_surface_id"]))
    support_vertices = _surface_vertices(support)
    footprint = _stored_footprint(field)
    setback = field.get("setback_configuration") or {}
    perimeter_setback = float(
        setback.get("perimeter_setback_m") or 0.0
    )
    obstacle_setback = float(
        setback.get("obstacle_setback_m") or 0.0
    )
    exclusion_surfaces, obstacles = _resolved_exclusions(
        scene, field, support
    )
    conflicts: list[PackingConflict] = []

    current_hash = packing_input_hash(scene, field, footprint)
    stored_hash = field.get("packing_input_hash")
    if stored_hash and stored_hash != current_hash:
        conflicts.append(
            PackingConflict(
                "packing_inputs_changed",
                None,
                None,
                (
                    "Support/exclusion geometry or packing inputs changed "
                    "after the last rebuild."
                ),
            )
        )

    modules = [
        item
        for item in scene.get("module_instances", [])
        if item.get("pv_field_id") == pv_field_id
        and item.get("enabled", True)
    ]
    module_polygons: list[
        tuple[str, list[tuple[float, float]]]
    ] = []
    for module in modules:
        center = (
            float(module["transform"]["position_x_m"]),
            float(module["transform"]["position_y_m"]),
        )
        azimuth = float(module["transform"]["rotation_z_deg"])
        polygon = rectangle_polygon(
            center,
            footprint.plan_projection_width_m,
            footprint.plan_projection_height_m,
            azimuth,
        )
        module_id = str(module["module_instance_id"])
        module_polygons.append((module_id, polygon))

        for hole in support["boundary_2d"].get("holes", []):
            if (polygons_overlap_or_touch(polygon, hole)
                    or (perimeter_setback > 0 and polygon_distance(polygon, hole) < perimeter_setback - 1e-9)):
                conflicts.append(PackingConflict("module_outside_support_or_setback", module_id, str(support["surface_id"]),
                    "Module overlaps/touches a support hole or violates its perimeter setback."))
                break

        if not polygon_contains_polygon(
            support_vertices,
            polygon,
            clearance_m=perimeter_setback,
        ):
            conflicts.append(
                PackingConflict(
                    "module_outside_support_or_setback",
                    module_id,
                    str(support["surface_id"]),
                    (
                        "Module violates support boundary or perimeter "
                        "setback."
                    ),
                )
            )
        for entity_id, excluded in exclusion_surfaces:
            if polygons_overlap_or_touch(polygon, excluded):
                conflicts.append(
                    PackingConflict(
                        "module_exclusion_overlap",
                        module_id,
                        entity_id,
                        "Module overlaps an exclusion/walkway surface.",
                    )
                )
        for entity_id, obstacle in obstacles:
            if polygons_overlap_or_touch(polygon, obstacle):
                conflicts.append(
                    PackingConflict(
                        "module_obstacle_overlap",
                        module_id,
                        entity_id,
                        "Module overlaps an obstacle.",
                    )
                )
            elif (
                obstacle_setback > 0.0
                and polygon_distance(polygon, obstacle)
                < obstacle_setback - 1e-9
            ):
                conflicts.append(
                    PackingConflict(
                        "module_obstacle_setback",
                        module_id,
                        entity_id,
                        "Module violates obstacle setback.",
                    )
                )

    for first_index, (
        first_id,
        first_polygon,
    ) in enumerate(module_polygons):
        for second_id, second_polygon in module_polygons[
            first_index + 1 :
        ]:
            if polygons_overlap_strict(
                first_polygon, second_polygon
            ):
                conflicts.append(
                    PackingConflict(
                        "module_module_overlap",
                        first_id,
                        second_id,
                        "Two module footprints overlap or touch.",
                    )
                )

    return {
        "schema_name": "PVFieldConflictReport",
        "schema_version": "0.1",
        "pv_field_id": pv_field_id,
        "status": "valid" if not conflicts else "conflict",
        "module_count": len(modules),
        "stored_packing_input_hash": stored_hash,
        "current_packing_input_hash": current_hash,
        "conflict_count": len(conflicts),
        "conflicts": [item.to_mapping() for item in conflicts],
    }


def packing_snap_edges(
    scene: Mapping[str, Any],
) -> dict[
    str,
    list[
        tuple[
            str,
            tuple[float, float],
            tuple[float, float],
        ]
    ],
]:
    module_edges: list[
        tuple[
            str,
            tuple[float, float],
            tuple[float, float],
        ]
    ] = []
    row_edges: list[
        tuple[
            str,
            tuple[float, float],
            tuple[float, float],
        ]
    ] = []
    fields = {
        item["pv_field_id"]: item
        for item in scene.get("pv_fields", [])
    }
    modules_by_field: dict[str, list[dict[str, Any]]] = {}
    for module in scene.get("module_instances", []):
        modules_by_field.setdefault(
            str(module["pv_field_id"]), []
        ).append(module)

    for field_id in sorted(fields):
        field = fields[field_id]
        if not field.get("module_footprint"):
            continue
        footprint = _stored_footprint(field)
        rows: dict[int, list[dict[str, Any]]] = {}
        for module in modules_by_field.get(field_id, []):
            center = (
                float(module["transform"]["position_x_m"]),
                float(module["transform"]["position_y_m"]),
            )
            polygon = rectangle_polygon(
                center,
                footprint.plan_projection_width_m,
                footprint.plan_projection_height_m,
                float(module["transform"]["rotation_z_deg"]),
            )
            module_id = str(module["module_instance_id"])
            for start, end in polygon_segments(polygon):
                module_edges.append((module_id, start, end))
            rows.setdefault(int(module["row_index"]), []).append(
                module
            )

        for row_index in sorted(rows):
            row = sorted(
                rows[row_index],
                key=lambda item: int(item["column_index"]),
            )
            if not row:
                continue
            azimuth = float(field["azimuth_deg"])
            first_center = (
                float(row[0]["transform"]["position_x_m"]),
                float(row[0]["transform"]["position_y_m"]),
            )
            last_center = (
                float(row[-1]["transform"]["position_x_m"]),
                float(row[-1]["transform"]["position_y_m"]),
            )
            half = footprint.plan_projection_width_m / 2.0
            row_axis_azimuth = (azimuth + 90.0) % 360.0
            dx = half * math.sin(math.radians(row_axis_azimuth))
            dy = half * math.cos(math.radians(row_axis_azimuth))
            start = (first_center[0] - dx, first_center[1] - dy)
            end = (last_center[0] + dx, last_center[1] + dy)
            row_edges.append(
                (f"{field_id}:row:{row_index}", start, end)
            )

    return {
        "module_edge": module_edges,
        "row_edge": row_edges,
    }


def support_edge_azimuth(
    scene: Mapping[str, Any],
    support_surface_id: str,
    edge_index: int,
) -> float:
    support = _surface(scene, support_surface_id)
    vertices = _surface_vertices(support)
    if edge_index < 0 or edge_index >= len(vertices):
        raise IndexError("support edge_index is outside boundary")
    return edge_azimuth_deg(
        vertices[edge_index],
        vertices[(edge_index + 1) % len(vertices)],
    )
