"""Phase-5.8 exact prepared directional geometry.

The Phase-5.3 and Phase-5.7 public reference solvers remain the correctness
oracle.  This module precomputes only direction-independent receiver/occluder
work and evaluates the same polygon-projection equations against that prepared
state.

No angular quantization or geometric approximation is introduced here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import Any, Mapping, Sequence

import numpy as np
import shapely
from shapely import geos_version_string
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union

from .beam import (
    _shadow_union,
    _fallback_evidence,
    BEAM_SOLVER_ID,
    BEAM_SOLVER_VERSION,
    DEFAULT_BEAM_TOLERANCES,
    BeamShadowError,
    BeamShadowTolerances,
    _clip_face_to_receiver_sunward_halfspace,
    _dot,
    _find_receiver,
    _normalize,
    _point3,
    _polygon_from_uv,
    _polygon_geometry_payloads_uv,
    _polygon_payload_uv,
    _polygonal_area,
    _project_to_receiver_plane,
    _receiver_basis,
    _sub,
    _to_uv,
)
from .contract import FACTOR_CONVENTION, SUN_VECTOR_CONVENTION
from .directional import (
    DIRECTIONAL_VISIBILITY_SOLVER_ID,
    DIRECTIONAL_VISIBILITY_SOLVER_VERSION,
    DirectionalVisibilityError,
)


PREPARED_DIRECTIONAL_ENGINE_ID = "rawibumi.directional_visibility.prepared_exact"
PREPARED_DIRECTIONAL_ENGINE_VERSION = "0.1"


class PreparedDirectionalError(ValueError):
    """Raised when exact prepared query state cannot be built or consumed."""


@dataclass(frozen=True)
class PreparedOccluderFace:
    occluder_id: str
    face_id: str
    vertices_3d: tuple[tuple[float, float, float], ...]


@dataclass(frozen=True)
class PreparedDirectionalReceiver:
    compiled_geometry_hash: str
    receiver_id: str
    receiver_source_entity_type: str
    receiver_source_entity_id: str
    origin_xyz: tuple[float, float, float]
    normal_xyz: tuple[float, float, float]
    u_axis_xyz: tuple[float, float, float]
    v_axis_xyz: tuple[float, float, float]
    receiver_polygon_uv: Polygon
    receiver_area_m2: float
    receiver_planarity_max_error_m: float
    self_shading_enabled: bool
    participating_occluder_count: int
    prepared_faces: tuple[PreparedOccluderFace, ...]
    tolerances: BeamShadowTolerances
    _bounds: Any = field(default=None, compare=False, repr=False)

    @property
    def prepared_face_count(self) -> int:
        return len(self.prepared_faces)


def _geometry_engine() -> dict[str, str]:
    return {
        "library": "Shapely",
        "shapely_version": str(shapely.__version__),
        "backend": "GEOS",
        "geos_version": str(geos_version_string),
    }


def prepare_directional_receiver(
    compiled_geometry: Mapping[str, Any],
    *,
    receiver_id: str,
    self_shading_enabled: bool,
    tolerances: BeamShadowTolerances = DEFAULT_BEAM_TOLERANCES,
) -> PreparedDirectionalReceiver:
    """Compile direction-independent exact query state for one receiver."""
    if not isinstance(self_shading_enabled, bool):
        raise PreparedDirectionalError(
            "self_shading_enabled must be explicit boolean"
        )

    geometry_hash = str(compiled_geometry.get("geometry_payload_sha256") or "")
    if (
        len(geometry_hash) != 64
        or any(character not in "0123456789abcdef" for character in geometry_hash)
    ):
        raise PreparedDirectionalError(
            "compiled geometry must provide lowercase geometry_payload_sha256"
        )

    try:
        receiver = _find_receiver(compiled_geometry, receiver_id)
        origin, normal, u_axis, v_axis = _receiver_basis(
            receiver["vertices_3d"],
            receiver["normal_xyz"],
        )
        planarity = max(
            abs(_dot(normal, _sub(_point3(point), origin)))
            for point in receiver["vertices_3d"]
        )
        if planarity > tolerances.plane_distance_m:
            raise PreparedDirectionalError(
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
    except BeamShadowError as exc:
        raise PreparedDirectionalError(str(exc)) from exc

    if receiver_polygon is None:
        raise PreparedDirectionalError(
            "receiver polygon is invalid or degenerate"
        )

    receiver_area = float(receiver_polygon.area)
    declared_area = float(receiver.get("area_m2", receiver_area))
    if abs(declared_area - receiver_area) > max(
        tolerances.area_m2,
        receiver_area * 1e-9,
    ):
        raise PreparedDirectionalError(
            "receiver area_m2 disagrees with receiver vertices beyond tolerance"
        )

    receiver_source_type = str(receiver.get("source_entity_type") or "")
    receiver_source_id = str(receiver.get("source_entity_id") or "")

    participating_occluders = 0
    prepared_faces: list[PreparedOccluderFace] = []

    for occluder in sorted(
        compiled_geometry.get("occluders", []),
        key=lambda item: str(item.get("occluder_id", "")),
    ):
        if occluder.get("shading_enabled") is not True:
            continue

        source_type = str(occluder.get("source_entity_type") or "")
        source_id = str(occluder.get("source_entity_id") or "")
        if source_type == receiver_source_type and source_id == receiver_source_id:
            continue
        if source_type == "module_instance" and not self_shading_enabled:
            continue
        if occluder.get("geometry_type") != "polygon_faces":
            raise PreparedDirectionalError(
                "unsupported occluder geometry_type for prepared exact kernel: "
                f"{occluder.get('geometry_type')!r}"
            )

        participating_occluders += 1
        occluder_id = str(occluder.get("occluder_id") or "")
        for face in occluder.get("faces", []):
            try:
                clipped = _clip_face_to_receiver_sunward_halfspace(
                    face.get("vertices_3d") or [],
                    receiver_origin=origin,
                    receiver_normal=normal,
                    tolerance_m=tolerances.plane_distance_m,
                )
            except BeamShadowError as exc:
                raise PreparedDirectionalError(str(exc)) from exc
            if len(clipped) < 3:
                continue
            prepared_faces.append(
                PreparedOccluderFace(
                    occluder_id=occluder_id,
                    face_id=str(face.get("face_id") or ""),
                    vertices_3d=tuple(
                        tuple(float(value) for value in point)
                        for point in clipped
                    ),
                )
            )

    prepared = PreparedDirectionalReceiver(
        compiled_geometry_hash=geometry_hash,
        receiver_id=receiver_id,
        receiver_source_entity_type=receiver_source_type,
        receiver_source_entity_id=receiver_source_id,
        origin_xyz=tuple(float(value) for value in origin),
        normal_xyz=tuple(float(value) for value in normal),
        u_axis_xyz=tuple(float(value) for value in u_axis),
        v_axis_xyz=tuple(float(value) for value in v_axis),
        receiver_polygon_uv=receiver_polygon,
        receiver_area_m2=receiver_area,
        receiver_planarity_max_error_m=float(planarity),
        self_shading_enabled=self_shading_enabled,
        participating_occluder_count=participating_occluders,
        prepared_faces=tuple(prepared_faces),
        tolerances=tolerances,
    )
    if len(prepared.prepared_faces) >= 64:
        prepared = replace(prepared, _bounds=_build_bound_state(prepared))
    return prepared


def _validate_prepared_source(
    prepared: PreparedDirectionalReceiver,
    source_direction_xyz: Sequence[float],
) -> tuple[tuple[float, float, float], float]:
    try:
        source = _normalize(_point3(source_direction_xyz), name="source direction")
    except BeamShadowError as exc:
        raise PreparedDirectionalError(str(exc)) from exc
    return source, _dot(prepared.normal_xyz, source)


def _evaluate_front_source_reference(
    prepared: PreparedDirectionalReceiver,
    source_direction: tuple[float, float, float],
    receiver_source_dot: float,
    *,
    diagnostic_collector: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tolerances = prepared.tolerances

    if diagnostic_collector is not None:
        diagnostic_collector.clear()
        diagnostic_collector.update(
            {
                "receiver_id": prepared.receiver_id,
                "receiver_plane_basis": {
                    "origin_xyz": list(prepared.origin_xyz),
                    "normal_xyz": list(prepared.normal_xyz),
                    "u_axis_xyz": list(prepared.u_axis_xyz),
                    "v_axis_xyz": list(prepared.v_axis_xyz),
                },
                "receiver_polygon_uv": _polygon_payload_uv(
                    prepared.receiver_polygon_uv
                ),
                "projected_faces": [],
                "shadow_union_polygons_uv": [],
            }
        )

    shadow_polygons: list[Polygon] = []
    contributing: set[str] = set()
    projected_face_count = 0
    clipped_shadow_polygon_count = 0

    if abs(receiver_source_dot) <= tolerances.parallel_dot:
        return {
            "shaded_area_m2": 0.0,
            "visibility_factor": 1.0,
            "shaded_fraction": 0.0,
            "contributing_occluder_ids": [],
            "projected_face_count": 0,
            "clipped_shadow_polygon_count": 0,
            "unioned": GeometryCollection(),
        }

    contributing_faces: dict[str, bool] = {}
    for face in prepared.prepared_faces:
        projected = [
            _project_to_receiver_plane(
                point,
                receiver_origin=prepared.origin_xyz,
                receiver_normal=prepared.normal_xyz,
                sun_vector=source_direction,
                receiver_sun_dot=receiver_source_dot,
            )
            for point in face.vertices_3d
        ]
        projected_face_count += 1

        try:
            polygon = _polygon_from_uv(
                [
                    _to_uv(
                        point,
                        origin=prepared.origin_xyz,
                        u_axis=prepared.u_axis_xyz,
                        v_axis=prepared.v_axis_xyz,
                    )
                    for point in projected
                ],
                area_tolerance_m2=tolerances.area_m2,
            )
        except BeamShadowError as exc:
            raise PreparedDirectionalError(str(exc)) from exc
        if polygon is None:
            continue

        clipped_shadow = polygon.intersection(prepared.receiver_polygon_uv)
        area = _polygonal_area(clipped_shadow)
        if diagnostic_collector is not None:
            diagnostic_collector["projected_faces"].append(
                {
                    "occluder_id": face.occluder_id,
                    "face_id": face.face_id,
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
        contributing_faces[face.occluder_id] = True
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

    contributing.update(contributing_faces)

    fallback_evidence = {}
    if shadow_polygons:
        unioned, fallback_evidence = _shadow_union(
            shadow_polygons, prepared.receiver_polygon_uv, receiver_id=prepared.receiver_id,
            occluder_ids=contributing, source=source_direction,
        )
        shaded_area = _polygonal_area(unioned)
    else:
        unioned = GeometryCollection()
        shaded_area = 0.0

    shaded_area = min(prepared.receiver_area_m2, max(0.0, shaded_area))
    shaded_fraction = shaded_area / prepared.receiver_area_m2
    visibility = 1.0 - shaded_fraction

    if abs(shaded_area) <= tolerances.area_m2:
        shaded_area = 0.0
        shaded_fraction = 0.0
        visibility = 1.0
    elif abs(prepared.receiver_area_m2 - shaded_area) <= tolerances.area_m2:
        shaded_area = prepared.receiver_area_m2
        shaded_fraction = 1.0
        visibility = 0.0

    if not math.isfinite(visibility) or visibility < 0.0 or visibility > 1.0:
        raise PreparedDirectionalError(
            "prepared exact visibility escaped canonical [0, 1] bounds"
        )

    if diagnostic_collector is not None:
        diagnostic_collector["shadow_union_polygons_uv"] = (
            _polygon_geometry_payloads_uv(unioned)
        )

    return {
        "shaded_area_m2": float(shaded_area),
        "visibility_factor": float(visibility),
        "shaded_fraction": float(shaded_fraction),
        "contributing_occluder_ids": sorted(contributing),
        "projected_face_count": projected_face_count,
        "clipped_shadow_polygon_count": clipped_shadow_polygon_count,
        "unioned": unioned,
        **fallback_evidence,
    }


def calculate_prepared_directional_receiver_visibility(
    prepared: PreparedDirectionalReceiver,
    *,
    source_direction_xyz: Sequence[float],
    diagnostic_collector: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Exact prepared equivalent of the Phase-5.7 directional reference solver."""
    source, receiver_source_dot = _validate_prepared_source(
        prepared,
        source_direction_xyz,
    )

    base = {
        "schema_name": "DirectionalVisibilityQueryResult",
        "schema_version": "0.1",
        "solver_id": DIRECTIONAL_VISIBILITY_SOLVER_ID,
        "solver_version": DIRECTIONAL_VISIBILITY_SOLVER_VERSION,
        "compiled_geometry_hash": prepared.compiled_geometry_hash,
        "receiver_id": prepared.receiver_id,
        "source_direction_xyz": list(source),
        "projection_direction": "opposite_source_direction",
        "factor_convention": FACTOR_CONVENTION,
        "receiver_area_m2": prepared.receiver_area_m2,
        "receiver_source_dot": receiver_source_dot,
        "receiver_planarity_max_error_m": (
            prepared.receiver_planarity_max_error_m
        ),
        "self_shading_enabled": prepared.self_shading_enabled,
        "geometry_engine": _geometry_engine(),
        "tolerances": prepared.tolerances.as_dict(),
    }

    if receiver_source_dot <= prepared.tolerances.incidence_dot:
        if diagnostic_collector is not None:
            diagnostic_collector.clear()
            diagnostic_collector.update(
                {
                    "receiver_id": prepared.receiver_id,
                    "receiver_plane_basis": {
                        "origin_xyz": list(prepared.origin_xyz),
                        "normal_xyz": list(prepared.normal_xyz),
                        "u_axis_xyz": list(prepared.u_axis_xyz),
                        "v_axis_xyz": list(prepared.v_axis_xyz),
                    },
                    "receiver_polygon_uv": _polygon_payload_uv(
                        prepared.receiver_polygon_uv
                    ),
                    "projected_faces": [],
                    "shadow_union_polygons_uv": [],
                    "status": "source_behind_receiver",
                }
            )
        return {
            **base,
            "status": "source_behind_receiver",
            "shaded_area_m2": 0.0,
            "visibility_factor": 1.0,
            "shaded_fraction": 0.0,
            "contributing_occluder_ids": [],
            "projected_face_count": 0,
            "clipped_shadow_polygon_count": 0,
        }

    evaluated = _evaluate_front_source(
        prepared,
        source,
        receiver_source_dot,
        diagnostic_collector=diagnostic_collector,
    )
    if diagnostic_collector is not None:
        diagnostic_collector["status"] = "evaluated"

    return {
        **base,
        "status": "evaluated",
        **_fallback_evidence(evaluated),
        "shaded_area_m2": evaluated["shaded_area_m2"],
        "visibility_factor": evaluated["visibility_factor"],
        "shaded_fraction": evaluated["shaded_fraction"],
        "contributing_occluder_ids": evaluated["contributing_occluder_ids"],
        "projected_face_count": evaluated["projected_face_count"],
        "clipped_shadow_polygon_count": (
            evaluated["clipped_shadow_polygon_count"]
        ),
    }


def calculate_prepared_direct_beam_shadow(
    prepared: PreparedDirectionalReceiver,
    *,
    sun_vector_xyz: Sequence[float],
    diagnostic_collector: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Exact prepared equivalent of calculate_direct_beam_shadow()."""
    try:
        sun = _normalize(_point3(sun_vector_xyz), name="sun vector")
    except BeamShadowError as exc:
        raise PreparedDirectionalError(str(exc)) from exc

    receiver_sun_dot = _dot(prepared.normal_xyz, sun)
    base = {
        "schema_name": "BeamShadowQueryResult",
        "schema_version": "0.1",
        "solver_id": BEAM_SOLVER_ID,
        "solver_version": BEAM_SOLVER_VERSION,
        "compiled_geometry_hash": prepared.compiled_geometry_hash,
        "receiver_id": prepared.receiver_id,
        "sun_vector_xyz": list(sun),
        "sun_vector_convention": SUN_VECTOR_CONVENTION,
        "projection_direction": "opposite_sun_vector",
        "factor_convention": FACTOR_CONVENTION,
        "receiver_area_m2": prepared.receiver_area_m2,
        "receiver_sun_dot": receiver_sun_dot,
        "receiver_planarity_max_error_m": (
            prepared.receiver_planarity_max_error_m
        ),
        "self_shading_enabled": prepared.self_shading_enabled,
        "geometry_engine": _geometry_engine(),
        "tolerances": prepared.tolerances.as_dict(),
    }

    def empty(status: str) -> dict[str, Any]:
        if diagnostic_collector is not None:
            diagnostic_collector.clear()
            diagnostic_collector.update(
                {
                    "receiver_id": prepared.receiver_id,
                    "receiver_plane_basis": {
                        "origin_xyz": list(prepared.origin_xyz),
                        "normal_xyz": list(prepared.normal_xyz),
                        "u_axis_xyz": list(prepared.u_axis_xyz),
                        "v_axis_xyz": list(prepared.v_axis_xyz),
                    },
                    "receiver_polygon_uv": _polygon_payload_uv(
                        prepared.receiver_polygon_uv
                    ),
                    "projected_faces": [],
                    "shadow_union_polygons_uv": [],
                    "status": status,
                }
            )
        return {
            **base,
            "status": status,
            "shaded_area_m2": 0.0,
            "beam_visibility_factor": 1.0,
            "beam_shaded_fraction": 0.0,
            "contributing_occluder_ids": [],
            "projected_face_count": 0,
            "clipped_shadow_polygon_count": 0,
        }

    if sun[2] <= prepared.tolerances.horizon_z:
        return empty("no_direct_beam_sun_below_horizon")
    if receiver_sun_dot <= prepared.tolerances.incidence_dot:
        return empty("no_direct_beam_receiver_backside")

    evaluated = _evaluate_front_source(
        prepared,
        sun,
        receiver_sun_dot,
        diagnostic_collector=diagnostic_collector,
    )
    if diagnostic_collector is not None:
        diagnostic_collector["status"] = "evaluated"

    return {
        **base,
        "status": "evaluated",
        **_fallback_evidence(evaluated),
        "shaded_area_m2": evaluated["shaded_area_m2"],
        "beam_visibility_factor": evaluated["visibility_factor"],
        "beam_shaded_fraction": evaluated["shaded_fraction"],
        "contributing_occluder_ids": evaluated["contributing_occluder_ids"],
        "projected_face_count": evaluated["projected_face_count"],
        "clipped_shadow_polygon_count": (
            evaluated["clipped_shadow_polygon_count"]
        ),
    }


def prepared_to_directional_error(exc: PreparedDirectionalError) -> DirectionalVisibilityError:
    """Translate prepared-path failures for callers preserving old API errors."""
    return DirectionalVisibilityError(str(exc))


@dataclass
class _BoundState:
    """Operational arrays only; never serialized into scientific artifacts."""

    indices: np.ndarray
    vertex_counts: np.ndarray
    vertices: np.ndarray
    distances: np.ndarray
    metrics: dict[str, int] = field(default_factory=lambda: {
        "queries": 0, "faces": 0, "candidates": 0,
        "uncertain": 0, "rejected": 0, "retained": 0,
    })


def _build_bound_state(prepared: PreparedDirectionalReceiver) -> _BoundState:
    indices = [i for i, face in enumerate(prepared.prepared_faces)
               if len(face.vertices_3d) in (3, 4)]
    vertices = np.empty((len(indices), 4, 3), dtype=np.float64)
    distances = np.empty((len(indices), 4), dtype=np.float64)
    counts = np.empty(len(indices), dtype=np.int64)
    for at, index in enumerate(indices):
        points = prepared.prepared_faces[index].vertices_3d
        counts[at] = len(points)
        for j in range(4):
            point = points[min(j, len(points)-1)]
            vertices[at, j] = point
            # Exactly the reference's direction-independent scalar operation.
            distances[at, j] = _dot(prepared.normal_xyz, _sub(point, prepared.origin_xyz))
    packed = np.asarray(indices, dtype=np.int64)
    for array in (packed, counts, vertices, distances):
        array.setflags(write=False)
    return _BoundState(packed, counts, vertices, distances)


def _project_bound_vertices(prepared, source_direction, receiver_source_dot):
    """Bounds-only projection with explicitly ordered binary64 operations."""
    state = prepared._bounds
    with np.errstate(over="ignore", invalid="ignore", divide="ignore", under="ignore"):
        travel = np.divide(state.distances, receiver_source_dot)
        projected = np.subtract(
            state.vertices,
            np.multiply(np.asarray(source_direction, dtype=np.float64), travel[:, :, None]),
        )
        delta = np.subtract(projected, np.asarray(prepared.origin_xyz, dtype=np.float64))
        coordinates = []
        for axis in (prepared.u_axis_xyz, prepared.v_axis_xyz):
            # Deliberately no dot/reduction, reassociation, BLAS or fused operation.
            first = np.multiply(delta[:, :, 0], axis[0])
            second = np.multiply(delta[:, :, 1], axis[1])
            third = np.multiply(delta[:, :, 2], axis[2])
            coordinates.append(np.add(np.add(first, second), third))
        return np.stack(coordinates, axis=2)


def _interval_product(a_lo, a_hi, b_lo, b_hi):
    products = np.stack((a_lo*b_lo, a_lo*b_hi, a_hi*b_lo, a_hi*b_hi))
    return (np.nextafter(np.min(products, axis=0), -np.inf),
            np.nextafter(np.max(products, axis=0), np.inf))


def _certify_convex(projected_uv: np.ndarray) -> np.ndarray:
    """Sufficient validity certificate for only triangles/quads, not a repair.

    Every endpoint encloses exact arithmetic on the supplied binary64 inputs.
    Overflow, collapsed points, and any uncertain turn keep the reference path.
    """
    if projected_uv.shape[1] not in (3, 4):
        return np.zeros(len(projected_uv), dtype=bool)
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        first = np.subtract(np.roll(projected_uv, -1, axis=1), projected_uv)
        second = np.subtract(np.roll(projected_uv, -2, axis=1), projected_uv)
        a_lo, a_hi = np.nextafter(first, -np.inf), np.nextafter(first, np.inf)
        b_lo, b_hi = np.nextafter(second, -np.inf), np.nextafter(second, np.inf)
        left_lo, left_hi = _interval_product(a_lo[:, :, 0], a_hi[:, :, 0], b_lo[:, :, 1], b_hi[:, :, 1])
        right_lo, right_hi = _interval_product(a_lo[:, :, 1], a_hi[:, :, 1], b_lo[:, :, 0], b_hi[:, :, 0])
        lower = np.nextafter(np.subtract(left_lo, right_hi), -np.inf)
        upper = np.nextafter(np.subtract(left_hi, right_lo), np.inf)
        finite = np.all(np.isfinite(lower) & np.isfinite(upper), axis=1)
        return finite & (np.all(lower > 0, axis=1) | np.all(upper < 0, axis=1))


def _candidate_face_indices(prepared, source_direction, receiver_source_dot):
    state = prepared._bounds
    total = len(prepared.prepared_faces)
    metrics = state.metrics
    metrics["queries"] += 1
    metrics["faces"] += total
    if not len(state.indices):
        metrics["uncertain"] += total
        metrics["retained"] += total
        return np.arange(total)
    uv = _project_bound_vertices(prepared, source_direction, receiver_source_dot)
    finite = np.all(np.isfinite(uv), axis=(1, 2))
    with np.errstate(over="ignore", invalid="ignore"):
        lo = np.nextafter(np.min(uv, axis=1), -np.inf)
        hi = np.nextafter(np.max(uv, axis=1), np.inf)
    rx0, ry0, rx1, ry1 = prepared.receiver_polygon_uv.bounds
    outside = finite & ((hi[:, 0] < rx0) | (lo[:, 0] > rx1) |
                        (hi[:, 1] < ry0) | (lo[:, 1] > ry1))
    rejected = np.zeros(len(state.indices), dtype=bool)
    for count in (3, 4):
        positions = np.flatnonzero(outside & (state.vertex_counts == count))
        if len(positions):
            rejected[positions] = _certify_convex(uv[positions, :count])
    keep = np.ones(total, dtype=bool)
    keep[state.indices[rejected]] = False
    removed = int(np.count_nonzero(rejected))
    candidates = int(np.count_nonzero(finite & ~outside))
    metrics["rejected"] += removed
    metrics["candidates"] += candidates
    metrics["uncertain"] += total - candidates - removed
    metrics["retained"] += total - removed
    return np.flatnonzero(keep)


def _evaluate_front_source(prepared, source_direction, receiver_source_dot, *, diagnostic_collector=None):
    if (prepared._bounds is None or diagnostic_collector is not None or
            abs(receiver_source_dot) <= prepared.tolerances.parallel_dot):
        return _evaluate_front_source_reference(
            prepared, source_direction, receiver_source_dot,
            diagnostic_collector=diagnostic_collector,
        )
    indices = _candidate_face_indices(prepared, source_direction, receiver_source_dot)
    if len(indices) == len(prepared.prepared_faces):
        selected = prepared
    else:
        selected = replace(prepared, prepared_faces=tuple(prepared.prepared_faces[i] for i in indices))
    result = _evaluate_front_source_reference(selected, source_direction, receiver_source_dot)
    # Valid disjoint faces would be projected, then contribute no intersection.
    result["projected_face_count"] = len(prepared.prepared_faces)
    return result
