"""Phase-5.3 deterministic direct-beam geometric shadow kernel.

The solver projects compiled polygonal occluder faces opposite the frozen
receiver-to-sun vector onto one receiver plane, clips the projected geometry to
the receiver polygon, unions all shadow polygons, and reports geometric beam
visibility.

This module intentionally performs no diffuse, ground, electrical-mismatch, or
annual-simulation physics.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Iterable, Mapping, Sequence

import shapely
from shapely import geos_version_string
from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from .contract import FACTOR_CONVENTION, SUN_VECTOR_CONVENTION


BEAM_SOLVER_ID = "rawibumi.beam_shadow.polygon_projection"
BEAM_SOLVER_VERSION = "0.1"

Point3D = tuple[float, float, float]


class BeamShadowError(ValueError):
    """Raised when a direct-beam query cannot be evaluated defensibly."""


SHADOW_UNION_FALLBACK_FLAG = "shadow_union_precision_fallback"
SHADOW_UNION_GRIDS_M = (1e-10, 1e-9, 1e-8, 1e-7, 1e-6)


def _shadow_union(polygons, receiver_polygon, *, receiver_id, occluder_ids, source):
    """Exact first; bounded precision overlay only after a GEOS failure.

    Inputs are already receiver-clipped. Do not re-intersect exact successes:
    even redundant overlay can change their binary64 representation.
    """
    try:
        return unary_union(polygons), {}
    except GEOSException as original:
        for grid in SHADOW_UNION_GRIDS_M:
            try:
                unioned = shapely.union_all(polygons, grid_size=grid)
                unioned = unioned.intersection(receiver_polygon)
            except GEOSException:
                continue
            perimeter = sum(polygon.length for polygon in polygons)
            event = {
                "receiver_id": receiver_id,
                "occluder_ids": sorted(occluder_ids),
                "source_direction_xyz": list(source),
                "grid_size_m": grid,
                "perimeter_m": perimeter,
                "area_bound_m2": perimeter * grid,
            }
            return unioned, {
                "quality_flags": [SHADOW_UNION_FALLBACK_FLAG],
                "shadow_union_precision_fallback_events": [event],
            }
        raise BeamShadowError(
            "shadow union failed after exact overlay and all precision steps; "
            f"receiver={receiver_id}; occluders={sorted(occluder_ids)}; "
            f"timestamp=unavailable; original={original}"
        ) from original


def _fallback_evidence(result, *, timestamp=None, channel=None):
    """Copy conditional evidence, adding context only at its owning boundary."""
    events = result.get("shadow_union_precision_fallback_events")
    if not events:
        return {}
    return {
        "quality_flags": [SHADOW_UNION_FALLBACK_FLAG],
        "shadow_union_precision_fallback_events": [
            {**event, **({"timestamp": timestamp, "channel": channel}
                        if channel is not None else {})}
            for event in events
        ],
    }


def _fallback_totals(events):
    if not events:
        return {}
    histogram = {}
    for event in events:
        key = str(event["grid_size_m"])
        histogram[key] = histogram.get(key, 0) + 1
    return {"shadow_union_precision_fallback": {
        "count": len(events),
        "grid_size_m_histogram": dict(sorted(histogram.items())),
        "max_area_bound_m2": max(event["area_bound_m2"] for event in events),
        "events": events,
        "counting_policy": "snapshot_events_static_once_per_execution_group",
    }}


@dataclass(frozen=True)
class BeamShadowTolerances:
    """Numerical tolerances frozen for the Phase-5.3 reference kernel."""

    plane_distance_m: float = 1e-9
    parallel_dot: float = 1e-12
    area_m2: float = 1e-10
    horizon_z: float = 1e-12
    incidence_dot: float = 1e-12

    def as_dict(self) -> dict[str, float]:
        return {
            "plane_distance_m": float(self.plane_distance_m),
            "parallel_dot": float(self.parallel_dot),
            "area_m2": float(self.area_m2),
            "horizon_z": float(self.horizon_z),
            "incidence_dot": float(self.incidence_dot),
        }


DEFAULT_BEAM_TOLERANCES = BeamShadowTolerances()


def _point3(value: Sequence[float]) -> Point3D:
    if len(value) != 3:
        raise BeamShadowError("3-D point must have exactly three coordinates")
    point = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in point):
        raise BeamShadowError("3-D point coordinates must be finite")
    return point  # type: ignore[return-value]


def _dot(a: Point3D, b: Point3D) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a: Point3D, b: Point3D) -> Point3D:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Point3D, b: Point3D) -> Point3D:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Point3D, factor: float) -> Point3D:
    return (a[0] * factor, a[1] * factor, a[2] * factor)


def _cross(a: Point3D, b: Point3D) -> Point3D:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: Point3D) -> float:
    return math.sqrt(_dot(a, a))


def _normalize(a: Point3D, *, name: str) -> Point3D:
    length = _norm(a)
    if not math.isfinite(length) or length <= 0.0:
        raise BeamShadowError(f"{name} must have non-zero finite magnitude")
    return (a[0] / length, a[1] / length, a[2] / length)


def _receiver_basis(
    vertices: Sequence[Sequence[float]],
    normal_xyz: Sequence[float],
) -> tuple[Point3D, Point3D, Point3D, Point3D]:
    points = [_point3(item) for item in vertices]
    if len(points) < 3:
        raise BeamShadowError("receiver requires at least three vertices")
    origin = points[0]
    normal = _normalize(_point3(normal_xyz), name="receiver normal")

    candidates: list[tuple[float, int, Point3D]] = []
    for index in range(len(points)):
        edge = _sub(points[(index + 1) % len(points)], points[index])
        candidates.append((_norm(edge), index, edge))
    length, _, selected = max(candidates, key=lambda item: (item[0], -item[1]))
    if length <= 0.0:
        raise BeamShadowError("receiver polygon has no non-zero edge")

    normal_component = _scale(normal, _dot(selected, normal))
    tangent = _sub(selected, normal_component)
    u_axis = _normalize(tangent, name="receiver plane axis")
    v_axis = _normalize(_cross(normal, u_axis), name="receiver plane axis")
    return origin, normal, u_axis, v_axis


def _to_uv(
    point: Sequence[float],
    *,
    origin: Point3D,
    u_axis: Point3D,
    v_axis: Point3D,
) -> tuple[float, float]:
    delta = _sub(_point3(point), origin)
    return (_dot(delta, u_axis), _dot(delta, v_axis))


def _dedupe_ring(points: Sequence[Point3D], tolerance: float) -> list[Point3D]:
    result: list[Point3D] = []
    for point in points:
        if not result or _norm(_sub(point, result[-1])) > tolerance:
            result.append(point)
    if len(result) >= 2 and _norm(_sub(result[0], result[-1])) <= tolerance:
        result.pop()
    return result


def _clip_face_to_receiver_sunward_halfspace(
    vertices: Sequence[Sequence[float]],
    *,
    receiver_origin: Point3D,
    receiver_normal: Point3D,
    tolerance_m: float,
) -> list[Point3D]:
    """Clip one 3-D face to n·(x-receiver_origin) >= tolerance."""
    polygon = [_point3(item) for item in vertices]
    if len(polygon) < 3:
        return []

    def distance(point: Point3D) -> float:
        return _dot(receiver_normal, _sub(point, receiver_origin))

    output: list[Point3D] = []
    previous = polygon[-1]
    previous_d = distance(previous)
    previous_inside = previous_d >= tolerance_m

    for current in polygon:
        current_d = distance(current)
        current_inside = current_d >= tolerance_m

        if current_inside != previous_inside:
            denominator = previous_d - current_d
            if abs(denominator) > 0.0:
                fraction = (previous_d - tolerance_m) / denominator
                intersection = _add(
                    previous,
                    _scale(_sub(current, previous), fraction),
                )
                output.append(intersection)

        if current_inside:
            output.append(current)

        previous = current
        previous_d = current_d
        previous_inside = current_inside

    return _dedupe_ring(output, tolerance_m)


def _project_to_receiver_plane(
    point: Point3D,
    *,
    receiver_origin: Point3D,
    receiver_normal: Point3D,
    sun_vector: Point3D,
    receiver_sun_dot: float,
) -> Point3D:
    distance = _dot(receiver_normal, _sub(point, receiver_origin))
    travel = distance / receiver_sun_dot
    return _sub(point, _scale(sun_vector, travel))


def _polygon_from_uv(
    coordinates: Sequence[tuple[float, float]],
    *,
    area_tolerance_m2: float,
) -> Polygon | None:
    if len(coordinates) < 3:
        return None
    polygon = Polygon(coordinates)
    if polygon.is_empty:
        return None
    area = float(polygon.area)
    if not polygon.is_valid:
        if area <= area_tolerance_m2:
            return None
        raise BeamShadowError(
            "projected polygon is topologically invalid above area tolerance"
        )
    if area <= area_tolerance_m2:
        return None
    return polygon


def _canonical_ring_uv(coordinates: Iterable[Sequence[float]]) -> list[list[float]]:
    points = [
        (float(item[0]), float(item[1]))
        for item in coordinates
    ]
    if len(points) >= 2 and points[0] == points[-1]:
        points.pop()
    if not points:
        return []

    minimum = min(points)
    candidates = []
    for index, point in enumerate(points):
        if point == minimum:
            rotated = points[index:] + points[:index]
            candidates.append(rotated)
    selected = min(candidates)
    return [[x, y] for x, y in selected]


def _polygon_payload_uv(polygon: Polygon) -> dict[str, Any]:
    normalized = orient(polygon, sign=1.0)
    holes = [
        _canonical_ring_uv(ring.coords)
        for ring in normalized.interiors
    ]
    holes.sort(
        key=lambda ring: json.dumps(
            ring,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return {
        "exterior_uv": _canonical_ring_uv(normalized.exterior.coords),
        "holes_uv": holes,
    }


def _polygon_geometry_payloads_uv(geometry: Any) -> list[dict[str, Any]]:
    polygons: list[Polygon] = []
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        polygons = [geometry]
    elif isinstance(geometry, MultiPolygon):
        polygons = list(geometry.geoms)
    elif isinstance(geometry, GeometryCollection):
        for item in geometry.geoms:
            if isinstance(item, Polygon):
                polygons.append(item)
            elif isinstance(item, MultiPolygon):
                polygons.extend(item.geoms)

    payloads = [_polygon_payload_uv(item) for item in polygons]
    payloads.sort(
        key=lambda item: json.dumps(
            item,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return payloads


def _polygonal_area(geometry: Any) -> float:
    if geometry.is_empty:
        return 0.0
    if isinstance(geometry, Polygon):
        return float(geometry.area)
    if isinstance(geometry, MultiPolygon):
        return float(sum(item.area for item in geometry.geoms))
    if isinstance(geometry, GeometryCollection):
        return float(
            sum(
                item.area
                for item in geometry.geoms
                if isinstance(item, (Polygon, MultiPolygon))
            )
        )
    return float(getattr(geometry, "area", 0.0))


def _find_receiver(
    compiled_geometry: Mapping[str, Any],
    receiver_id: str,
) -> Mapping[str, Any]:
    matches = [
        item
        for item in compiled_geometry.get("receivers", [])
        if str(item.get("receiver_id")) == receiver_id
    ]
    if len(matches) != 1:
        raise BeamShadowError(
            f"receiver_id must resolve exactly once: {receiver_id!r}"
        )
    receiver = matches[0]
    if receiver.get("enabled") is not True:
        raise BeamShadowError(f"receiver is disabled: {receiver_id}")
    return receiver


def calculate_direct_beam_shadow(
    compiled_geometry: Mapping[str, Any],
    *,
    receiver_id: str,
    sun_vector_xyz: Sequence[float],
    self_shading_enabled: bool,
    tolerances: BeamShadowTolerances = DEFAULT_BEAM_TOLERANCES,
    _diagnostic_collector: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate direct-beam geometric visibility for one receiver.

    Shadow direction is opposite the frozen receiver-to-sun vector. Occluder
    faces are clipped to the sunward half-space of the receiver plane before
    projection. Every projected polygon is clipped to the receiver polygon and
    all resulting shadows are unioned before area is measured.
    """
    if not isinstance(self_shading_enabled, bool):
        raise BeamShadowError("self_shading_enabled must be explicit boolean")

    geometry_hash = str(
        compiled_geometry.get("geometry_payload_sha256") or ""
    )
    if (
        len(geometry_hash) != 64
        or any(character not in "0123456789abcdef" for character in geometry_hash)
    ):
        raise BeamShadowError(
            "compiled geometry must provide a lowercase SHA-256 geometry_payload_sha256"
        )

    receiver = _find_receiver(compiled_geometry, receiver_id)
    sun_vector = _normalize(_point3(sun_vector_xyz), name="sun vector")
    origin, normal, u_axis, v_axis = _receiver_basis(
        receiver["vertices_3d"],
        receiver["normal_xyz"],
    )
    receiver_sun_dot = _dot(normal, sun_vector)
    receiver_planarity_max_error_m = max(
        abs(_dot(normal, _sub(_point3(point), origin)))
        for point in receiver["vertices_3d"]
    )
    if receiver_planarity_max_error_m > tolerances.plane_distance_m:
        raise BeamShadowError(
            "receiver vertices are not coplanar with receiver normal within "
            "plane_distance_m tolerance"
        )

    receiver_polygon = _polygon_from_uv(
        [
            _to_uv(
                point,
                origin=origin,
                u_axis=u_axis,
                v_axis=v_axis,
            )
            for point in receiver["vertices_3d"]
        ],
        area_tolerance_m2=tolerances.area_m2,
    )
    if receiver_polygon is None:
        raise BeamShadowError("receiver polygon is invalid or degenerate")

    if _diagnostic_collector is not None:
        _diagnostic_collector.clear()
        _diagnostic_collector.update(
            {
                "receiver_id": receiver_id,
                "receiver_plane_basis": {
                    "origin_xyz": list(origin),
                    "normal_xyz": list(normal),
                    "u_axis_xyz": list(u_axis),
                    "v_axis_xyz": list(v_axis),
                },
                "receiver_polygon_uv": _polygon_payload_uv(receiver_polygon),
                "projected_faces": [],
                "shadow_union_polygons_uv": [],
            }
        )

    receiver_area = float(receiver_polygon.area)
    declared_area = float(receiver.get("area_m2", receiver_area))
    if abs(declared_area - receiver_area) > max(
        tolerances.area_m2,
        receiver_area * 1e-9,
    ):
        raise BeamShadowError(
            "receiver area_m2 disagrees with receiver vertices beyond tolerance"
        )

    base_result = {
        "schema_name": "BeamShadowQueryResult",
        "schema_version": "0.1",
        "solver_id": BEAM_SOLVER_ID,
        "solver_version": BEAM_SOLVER_VERSION,
        "compiled_geometry_hash": geometry_hash,
        "receiver_id": receiver_id,
        "sun_vector_xyz": list(sun_vector),
        "sun_vector_convention": SUN_VECTOR_CONVENTION,
        "projection_direction": "opposite_sun_vector",
        "factor_convention": FACTOR_CONVENTION,
        "receiver_area_m2": receiver_area,
        "receiver_sun_dot": receiver_sun_dot,
        "receiver_planarity_max_error_m": receiver_planarity_max_error_m,
        "self_shading_enabled": self_shading_enabled,
        "geometry_engine": {
            "library": "Shapely",
            "shapely_version": str(shapely.__version__),
            "backend": "GEOS",
            "geos_version": str(geos_version_string),
        },
        "tolerances": tolerances.as_dict(),
    }

    if sun_vector[2] <= tolerances.horizon_z:
        if _diagnostic_collector is not None:
            _diagnostic_collector["status"] = "no_direct_beam_sun_below_horizon"
        return {
            **base_result,
            "status": "no_direct_beam_sun_below_horizon",
            "shaded_area_m2": 0.0,
            "beam_visibility_factor": 1.0,
            "beam_shaded_fraction": 0.0,
            "contributing_occluder_ids": [],
            "projected_face_count": 0,
            "clipped_shadow_polygon_count": 0,
        }

    if receiver_sun_dot <= tolerances.incidence_dot:
        if _diagnostic_collector is not None:
            _diagnostic_collector["status"] = "no_direct_beam_receiver_backside"
        return {
            **base_result,
            "status": "no_direct_beam_receiver_backside",
            "shaded_area_m2": 0.0,
            "beam_visibility_factor": 1.0,
            "beam_shaded_fraction": 0.0,
            "contributing_occluder_ids": [],
            "projected_face_count": 0,
            "clipped_shadow_polygon_count": 0,
        }

    shadow_polygons: list[Polygon] = []
    contributing: set[str] = set()
    projected_face_count = 0
    clipped_shadow_polygon_count = 0

    receiver_source_type = str(receiver.get("source_entity_type") or "")
    receiver_source_id = str(receiver.get("source_entity_id") or "")

    for occluder in sorted(
        compiled_geometry.get("occluders", []),
        key=lambda item: str(item.get("occluder_id", "")),
    ):
        if occluder.get("shading_enabled") is not True:
            continue

        occluder_id = str(occluder.get("occluder_id") or "")
        source_type = str(occluder.get("source_entity_type") or "")
        source_id = str(occluder.get("source_entity_id") or "")

        if source_type == receiver_source_type and source_id == receiver_source_id:
            continue
        if source_type == "module_instance" and not self_shading_enabled:
            continue
        if occluder.get("geometry_type") != "polygon_faces":
            raise BeamShadowError(
                f"unsupported occluder geometry_type for reference kernel: "
                f"{occluder.get('geometry_type')!r}"
            )

        occluder_has_shadow = False
        for face in occluder.get("faces", []):
            clipped_face = _clip_face_to_receiver_sunward_halfspace(
                face.get("vertices_3d") or [],
                receiver_origin=origin,
                receiver_normal=normal,
                tolerance_m=tolerances.plane_distance_m,
            )
            if len(clipped_face) < 3:
                continue

            if abs(receiver_sun_dot) <= tolerances.parallel_dot:
                continue

            projected = [
                _project_to_receiver_plane(
                    point,
                    receiver_origin=origin,
                    receiver_normal=normal,
                    sun_vector=sun_vector,
                    receiver_sun_dot=receiver_sun_dot,
                )
                for point in clipped_face
            ]
            projected_face_count += 1

            polygon = _polygon_from_uv(
                [
                    _to_uv(
                        point,
                        origin=origin,
                        u_axis=u_axis,
                        v_axis=v_axis,
                    )
                    for point in projected
                ],
                area_tolerance_m2=tolerances.area_m2,
            )
            if polygon is None:
                continue

            clipped_shadow = polygon.intersection(receiver_polygon)
            area = _polygonal_area(clipped_shadow)
            if _diagnostic_collector is not None:
                _diagnostic_collector["projected_faces"].append(
                    {
                        "occluder_id": occluder_id,
                        "face_id": str(face.get("face_id") or ""),
                        "projected_polygon_uv": _polygon_payload_uv(polygon),
                        "receiver_clipped_shadow_polygons_uv": (
                            _polygon_geometry_payloads_uv(clipped_shadow)
                        ),
                        "receiver_clipped_shadow_area_m2": area,
                    }
                )
            if area <= tolerances.area_m2:
                continue

            clipped_shadow_polygon_count += 1
            occluder_has_shadow = True
            if isinstance(clipped_shadow, Polygon):
                shadow_polygons.append(clipped_shadow)
            elif isinstance(clipped_shadow, MultiPolygon):
                shadow_polygons.extend(
                    item
                    for item in clipped_shadow.geoms
                    if item.area > tolerances.area_m2
                )
            elif isinstance(clipped_shadow, GeometryCollection):
                for item in clipped_shadow.geoms:
                    if isinstance(item, Polygon) and item.area > tolerances.area_m2:
                        shadow_polygons.append(item)
                    elif isinstance(item, MultiPolygon):
                        shadow_polygons.extend(
                            part
                            for part in item.geoms
                            if part.area > tolerances.area_m2
                        )

        if occluder_has_shadow:
            contributing.add(occluder_id)

    fallback_evidence = {}
    if shadow_polygons:
        unioned, fallback_evidence = _shadow_union(
            shadow_polygons, receiver_polygon, receiver_id=receiver_id,
            occluder_ids=contributing, source=sun_vector,
        )
        shaded_area = _polygonal_area(unioned)
    else:
        unioned = GeometryCollection()
        shaded_area = 0.0

    if _diagnostic_collector is not None:
        _diagnostic_collector["status"] = "evaluated"
        _diagnostic_collector["shadow_union_polygons_uv"] = (
            _polygon_geometry_payloads_uv(unioned)
        )

    shaded_area = min(receiver_area, max(0.0, shaded_area))
    shaded_fraction = shaded_area / receiver_area
    visibility = 1.0 - shaded_fraction
    if abs(shaded_area) <= tolerances.area_m2:
        shaded_area = 0.0
        shaded_fraction = 0.0
        visibility = 1.0
    elif abs(receiver_area - shaded_area) <= tolerances.area_m2:
        shaded_area = receiver_area
        shaded_fraction = 1.0
        visibility = 0.0

    return {
        **base_result,
        "status": "evaluated",
        **fallback_evidence,
        "shaded_area_m2": shaded_area,
        "beam_visibility_factor": visibility,
        "beam_shaded_fraction": shaded_fraction,
        "contributing_occluder_ids": sorted(contributing),
        "projected_face_count": projected_face_count,
        "clipped_shadow_polygon_count": clipped_shadow_polygon_count,
    }

def calculate_direct_beam_shadow_with_diagnostics(
    compiled_geometry: Mapping[str, Any],
    *,
    receiver_id: str,
    sun_vector_xyz: Sequence[float],
    self_shading_enabled: bool,
    tolerances: BeamShadowTolerances = DEFAULT_BEAM_TOLERANCES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the normal scalar beam result plus optional derived geometry.

    The scalar result is produced by the same calculation path as
    calculate_direct_beam_shadow(). The additional diagnostic payload is
    non-authoritative and intended for engineering inspection, tests, and
    future interactive preview.
    """
    diagnostic: dict[str, Any] = {}
    result = calculate_direct_beam_shadow(
        compiled_geometry,
        receiver_id=receiver_id,
        sun_vector_xyz=sun_vector_xyz,
        self_shading_enabled=self_shading_enabled,
        tolerances=tolerances,
        _diagnostic_collector=diagnostic,
    )
    return result, diagnostic

