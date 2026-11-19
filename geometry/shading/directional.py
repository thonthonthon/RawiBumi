"""Phase-5.7 generic finite-receiver directional visibility.

This kernel is deliberately source-agnostic. It evaluates geometric visibility
from an arbitrary normalized direction to a receiver using the same frozen
receiver-plane, polygon clipping, and polygon-union primitives as the Phase-5.3
direct-beam solver.

Unlike the public direct-beam wrapper, this module applies no global
sun-above-horizon rule. That distinction is required for lower-hemisphere
ground/albedo source directions.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import shapely
from shapely import geos_version_string
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union

from .beam import (
    _shadow_union,
    _fallback_evidence,
    DEFAULT_BEAM_TOLERANCES,
    BeamShadowError,
    BeamShadowTolerances,
    _clip_face_to_receiver_sunward_halfspace,
    _dot,
    _find_receiver,
    _normalize,
    _point3,
    _polygon_geometry_payloads_uv,
    _polygon_payload_uv,
    _polygon_from_uv,
    _polygonal_area,
    _project_to_receiver_plane,
    _receiver_basis,
    _sub,
    _to_uv,
)
from .contract import FACTOR_CONVENTION


DIRECTIONAL_VISIBILITY_SOLVER_ID = (
    "rawibumi.directional_visibility.polygon_projection"
)
DIRECTIONAL_VISIBILITY_SOLVER_VERSION = "0.1"


class DirectionalVisibilityError(ValueError):
    """Raised when generic directional visibility cannot be evaluated safely."""


def calculate_directional_receiver_visibility(
    compiled_geometry: Mapping[str, Any],
    *,
    receiver_id: str,
    source_direction_xyz: Sequence[float],
    self_shading_enabled: bool,
    tolerances: BeamShadowTolerances = DEFAULT_BEAM_TOLERANCES,
    _diagnostic_collector: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate finite-area receiver visibility from one arbitrary direction.

    The supplied vector points from receiver toward the radiance/source
    direction. Occluders on the receiver-front side are projected opposite that
    vector onto the receiver plane, clipped to the receiver polygon, and unioned
    before shaded area is calculated.

    No global z/horizon rule is applied. A source direction only needs to be on
    the receiver front side. This makes the function suitable for both upper-
    hemisphere sky directions and lower-hemisphere ground directions.
    """
    if not isinstance(self_shading_enabled, bool):
        raise DirectionalVisibilityError(
            "self_shading_enabled must be explicit boolean"
        )

    geometry_hash = str(
        compiled_geometry.get("geometry_payload_sha256") or ""
    )
    if (
        len(geometry_hash) != 64
        or any(character not in "0123456789abcdef" for character in geometry_hash)
    ):
        raise DirectionalVisibilityError(
            "compiled geometry must provide a lowercase SHA-256 "
            "geometry_payload_sha256"
        )

    try:
        receiver = _find_receiver(compiled_geometry, receiver_id)
        source_direction = _normalize(
            _point3(source_direction_xyz),
            name="source direction",
        )
        origin, normal, u_axis, v_axis = _receiver_basis(
            receiver["vertices_3d"],
            receiver["normal_xyz"],
        )
    except BeamShadowError as exc:
        raise DirectionalVisibilityError(str(exc)) from exc

    receiver_source_dot = _dot(normal, source_direction)
    try:
        receiver_planarity_max_error_m = max(
            abs(_dot(normal, _sub(_point3(point), origin)))
            for point in receiver["vertices_3d"]
        )
    except BeamShadowError as exc:
        raise DirectionalVisibilityError(str(exc)) from exc

    if receiver_planarity_max_error_m > tolerances.plane_distance_m:
        raise DirectionalVisibilityError(
            "receiver vertices are not coplanar with receiver normal within "
            "plane_distance_m tolerance"
        )

    try:
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
        raise DirectionalVisibilityError(str(exc)) from exc
    if receiver_polygon is None:
        raise DirectionalVisibilityError(
            "receiver polygon is invalid or degenerate"
        )

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
        raise DirectionalVisibilityError(
            "receiver area_m2 disagrees with receiver vertices beyond tolerance"
        )

    base_result = {
        "schema_name": "DirectionalVisibilityQueryResult",
        "schema_version": "0.1",
        "solver_id": DIRECTIONAL_VISIBILITY_SOLVER_ID,
        "solver_version": DIRECTIONAL_VISIBILITY_SOLVER_VERSION,
        "compiled_geometry_hash": geometry_hash,
        "receiver_id": receiver_id,
        "source_direction_xyz": list(source_direction),
        "projection_direction": "opposite_source_direction",
        "factor_convention": FACTOR_CONVENTION,
        "receiver_area_m2": receiver_area,
        "receiver_source_dot": receiver_source_dot,
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

    if receiver_source_dot <= tolerances.incidence_dot:
        if _diagnostic_collector is not None:
            _diagnostic_collector["status"] = "source_behind_receiver"
        return {
            **base_result,
            "status": "source_behind_receiver",
            "shaded_area_m2": 0.0,
            "visibility_factor": 1.0,
            "shaded_fraction": 0.0,
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

        if (
            source_type == receiver_source_type
            and source_id == receiver_source_id
        ):
            continue
        if source_type == "module_instance" and not self_shading_enabled:
            continue
        if occluder.get("geometry_type") != "polygon_faces":
            raise DirectionalVisibilityError(
                "unsupported occluder geometry_type for reference kernel: "
                f"{occluder.get('geometry_type')!r}"
            )

        occluder_has_shadow = False
        for face in occluder.get("faces", []):
            try:
                clipped_face = _clip_face_to_receiver_sunward_halfspace(
                    face.get("vertices_3d") or [],
                    receiver_origin=origin,
                    receiver_normal=normal,
                    tolerance_m=tolerances.plane_distance_m,
                )
            except BeamShadowError as exc:
                raise DirectionalVisibilityError(str(exc)) from exc
            if len(clipped_face) < 3:
                continue

            if abs(receiver_source_dot) <= tolerances.parallel_dot:
                continue

            projected = [
                _project_to_receiver_plane(
                    point,
                    receiver_origin=origin,
                    receiver_normal=normal,
                    sun_vector=source_direction,
                    receiver_sun_dot=receiver_source_dot,
                )
                for point in clipped_face
            ]
            projected_face_count += 1

            try:
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
            except BeamShadowError as exc:
                raise DirectionalVisibilityError(str(exc)) from exc
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
                    if (
                        isinstance(item, Polygon)
                        and item.area > tolerances.area_m2
                    ):
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
            occluder_ids=contributing, source=source_direction,
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

    if (
        not math.isfinite(visibility)
        or visibility < 0.0
        or visibility > 1.0
    ):
        raise DirectionalVisibilityError(
            "directional visibility escaped canonical [0, 1] bounds"
        )

    return {
        **base_result,
        "status": "evaluated",
        **fallback_evidence,
        "shaded_area_m2": shaded_area,
        "visibility_factor": visibility,
        "shaded_fraction": shaded_fraction,
        "contributing_occluder_ids": sorted(contributing),
        "projected_face_count": projected_face_count,
        "clipped_shadow_polygon_count": clipped_shadow_polygon_count,
    }


def calculate_directional_receiver_visibility_with_diagnostics(
    compiled_geometry: Mapping[str, Any],
    *,
    receiver_id: str,
    source_direction_xyz: Sequence[float],
    self_shading_enabled: bool,
    tolerances: BeamShadowTolerances = DEFAULT_BEAM_TOLERANCES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return scalar generic visibility plus non-authoritative projected geometry."""
    diagnostic: dict[str, Any] = {}
    result = calculate_directional_receiver_visibility(
        compiled_geometry,
        receiver_id=receiver_id,
        source_direction_xyz=source_direction_xyz,
        self_shading_enabled=self_shading_enabled,
        tolerances=tolerances,
        _diagnostic_collector=diagnostic,
    )
    return result, diagnostic
