"""Phase-6.3 deterministic module-topology -> electrical-region geometry mapping.

The canonical Scene/CompiledShadingGeometry remains the geometry authority and
ModuleTopologyDefinition remains the component-internal electrical authority.
ElectricalRegionMap is a hashable derived bridge only; it is never editable.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from .contract import (
    MODULE_LOCAL_COORDINATE_CONVENTION,
    ElectricalShadingContractError,
    assert_module_topology_definition,
    resolve_region_geometry_execution_readiness,
)


ELECTRICAL_REGION_MAPPER_ID = "opensimpv.electrical_region_mapper.module_uv"
ELECTRICAL_REGION_MAPPER_VERSION = "0.1"
LANDSCAPE_ROTATION_CONVENTION = "clockwise_90_viewed_from_module_front"

Point3D = tuple[float, float, float]
_EPS = 1e-10


class ElectricalRegionMapError(ValueError):
    """Raised when a selected topology cannot be mapped to one module receiver."""


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _point3(value: Sequence[float], *, label: str) -> Point3D:
    if len(value) != 3:
        raise ElectricalRegionMapError(f"{label} must contain exactly three coordinates")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise ElectricalRegionMapError(f"{label} coordinates must be finite")
    return result  # type: ignore[return-value]


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


def _dot(a: Point3D, b: Point3D) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: Point3D) -> float:
    return math.sqrt(_dot(a, a))


def _polygon_area_3d(vertices: Sequence[Sequence[float]]) -> float:
    points = [_point3(item, label="region vertex") for item in vertices]
    if len(points) < 3:
        raise ElectricalRegionMapError("region polygon requires at least three vertices")
    nx = ny = nz = 0.0
    for current, following in zip(points, points[1:] + points[:1]):
        nx += (current[1] - following[1]) * (current[2] + following[2])
        ny += (current[2] - following[2]) * (current[0] + following[0])
        nz += (current[0] - following[0]) * (current[1] + following[1])
    area = 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)
    if not math.isfinite(area) or area <= _EPS:
        raise ElectricalRegionMapError("derived electrical region area must be positive")
    return area


def _sha256_string(value: Any, *, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ElectricalRegionMapError(f"{label} must be a lowercase SHA-256")
    return text


def _find_module_receiver(
    compiled_geometry: Mapping[str, Any],
    module_instance_id: str,
) -> Mapping[str, Any]:
    matches = [
        receiver
        for receiver in compiled_geometry.get("receivers", [])
        if receiver.get("source_entity_type") == "module_instance"
        and str(receiver.get("module_instance_id") or "") == str(module_instance_id)
    ]
    if len(matches) != 1:
        raise ElectricalRegionMapError(
            "module_instance_id must resolve to exactly one compiled module receiver"
        )
    receiver = matches[0]
    if receiver.get("receiver_type") != "module_plane":
        raise ElectricalRegionMapError("electrical regions require a module_plane receiver")
    if receiver.get("enabled") is not True:
        raise ElectricalRegionMapError("electrical regions cannot execute on a disabled receiver")
    if len(receiver.get("vertices_3d") or []) != 4:
        raise ElectricalRegionMapError(
            "Phase-6.3 v0.1 requires the canonical four-corner module receiver"
        )
    return receiver


def _intrinsic_affine_basis(receiver: Mapping[str, Any]) -> tuple[Point3D, Point3D, Point3D, str]:
    """Return origin, +U vector and +V vector for intrinsic module-front UV.

    GeneratedScene3D stores module corners in this order:
      C0=(-row,-down), C1=(+row,-down), C2=(+row,+down), C3=(-row,+down).

    Viewed from the module front, portrait intrinsic UV therefore maps:
      (0,0)->C2, (1,0)->C3, (1,1)->C0, (0,1)->C1.

    Landscape is frozen here as a 90-degree clockwise rotation viewed from the
    module front:
      (0,0)->C1, (1,0)->C2, (1,1)->C3, (0,1)->C0.
    """
    corners = [
        _point3(value, label=f"receiver corner {index}")
        for index, value in enumerate(receiver.get("vertices_3d") or [])
    ]
    c0, c1, c2, c3 = corners
    orientation = str((receiver.get("metadata") or {}).get("orientation") or "")
    if orientation == "portrait":
        origin, u_end, v_end, opposite = c2, c3, c1, c0
    elif orientation == "landscape":
        origin, u_end, v_end, opposite = c1, c2, c0, c3
    else:
        raise ElectricalRegionMapError(
            "module receiver metadata.orientation must be portrait or landscape"
        )

    u_vector = _sub(u_end, origin)
    v_vector = _sub(v_end, origin)
    predicted_opposite = _add(_add(origin, u_vector), v_vector)
    closure_error = _norm(_sub(predicted_opposite, opposite))
    if closure_error > 1e-8:
        raise ElectricalRegionMapError(
            "module receiver is not an affine rectangle in the frozen intrinsic-UV mapping"
        )

    normal = _point3(receiver.get("normal_xyz") or [], label="receiver normal")
    handedness = _dot(_cross(u_vector, v_vector), normal)
    if handedness <= _EPS:
        raise ElectricalRegionMapError(
            "intrinsic +U/+V mapping must preserve the module-front normal"
        )

    basis_area = _norm(_cross(u_vector, v_vector))
    declared_area = float(receiver.get("area_m2") or 0.0)
    if not math.isfinite(declared_area) or declared_area <= 0.0:
        raise ElectricalRegionMapError("module receiver area_m2 must be positive")
    if abs(basis_area - declared_area) > max(1e-8, declared_area * 1e-8):
        raise ElectricalRegionMapError(
            "module receiver area disagrees with intrinsic UV affine basis"
        )
    return origin, u_vector, v_vector, orientation


def _uv_to_xyz(
    uv: Sequence[float],
    *,
    origin: Point3D,
    u_vector: Point3D,
    v_vector: Point3D,
) -> list[float]:
    if len(uv) != 2:
        raise ElectricalRegionMapError("topology UV vertex must contain exactly [u, v]")
    u = float(uv[0])
    v = float(uv[1])
    if not math.isfinite(u) or not math.isfinite(v) or not (0.0 <= u <= 1.0) or not (0.0 <= v <= 1.0):
        raise ElectricalRegionMapError("topology UV coordinates must remain within [0, 1]")
    point = _add(origin, _add(_scale(u_vector, u), _scale(v_vector, v)))
    return [float(point[0]), float(point[1]), float(point[2])]


def derive_electrical_region_map(
    compiled_geometry: Mapping[str, Any],
    topology_definition: Mapping[str, Any],
    *,
    module_instance_id: str,
) -> dict[str, Any]:
    """Derive one immutable ElectricalRegionMap from exact geometry + topology revisions."""
    try:
        assert_module_topology_definition(topology_definition)
    except ElectricalShadingContractError as exc:
        raise ElectricalRegionMapError(str(exc)) from exc

    readiness_findings: list[dict[str, Any]] = []
    if not resolve_region_geometry_execution_readiness(
        topology_definition,
        topology_structurally_valid=True,
        findings=readiness_findings,
    ):
        message = readiness_findings[0]["message"] if readiness_findings else (
            "topology region geometry is not execution-ready"
        )
        raise ElectricalRegionMapError(str(message))

    geometry_hash = _sha256_string(
        compiled_geometry.get("geometry_payload_sha256"),
        label="compiled geometry geometry_payload_sha256",
    )
    scene_revision_id = str(compiled_geometry.get("source_scene_revision_id") or "")
    if not scene_revision_id:
        raise ElectricalRegionMapError("compiled geometry requires source_scene_revision_id")

    receiver = _find_module_receiver(compiled_geometry, module_instance_id)
    receiver_id = str(receiver.get("receiver_id") or "")
    module_revision_id = str((receiver.get("metadata") or {}).get("module_definition_revision_id") or "")
    if not module_revision_id:
        raise ElectricalRegionMapError(
            "compiled module receiver must carry module_definition_revision_id metadata"
        )
    topology_module_revision = str(topology_definition.get("module_definition_revision_id") or "")
    if topology_module_revision != module_revision_id:
        raise ElectricalRegionMapError(
            "selected topology is not bound to the module receiver's exact ModuleDefinition revision"
        )
    topology_revision_id = str(topology_definition.get("revision_id") or "")
    if not topology_revision_id:
        raise ElectricalRegionMapError("selected topology requires revision_id")

    origin, u_vector, v_vector, orientation = _intrinsic_affine_basis(receiver)
    regions: list[dict[str, Any]] = []
    mapped_area = 0.0
    for source_region in sorted(
        topology_definition.get("physical_regions") or [],
        key=lambda item: str(item.get("region_id") or ""),
    ):
        topology_region_id = str(source_region["region_id"])
        polygon_uv = [
            [float(vertex[0]), float(vertex[1])]
            for vertex in source_region["polygon_normalized"]
        ]
        vertices_3d = [
            _uv_to_xyz(
                vertex,
                origin=origin,
                u_vector=u_vector,
                v_vector=v_vector,
            )
            for vertex in polygon_uv
        ]
        area_m2 = _polygon_area_3d(vertices_3d)
        mapped_area += area_m2
        regions.append(
            {
                "region_id": f"electrical-region:{module_instance_id}:{topology_region_id}",
                "source_topology_region_id": topology_region_id,
                "source_electrical_substring_id": str(
                    source_region["electrical_substring_id"]
                ),
                "region_type": str(source_region["region_type"]),
                "equivalent_element_count": int(source_region["equivalent_element_count"]),
                "polygon_uv": polygon_uv,
                "vertices_3d": vertices_3d,
                "area_m2": float(area_m2),
                "metadata": {
                    "placement_orientation": orientation,
                    "source_shading_weight": source_region.get("shading_weight"),
                    "source_active_area_fraction": source_region.get("active_area_fraction"),
                },
            }
        )

    receiver_area = float(receiver["area_m2"])
    mapped_fraction = mapped_area / receiver_area
    if mapped_fraction > 1.0 + 1e-8:
        raise ElectricalRegionMapError(
            "mapped electrical region area exceeds the module receiver area"
        )

    mapper_manifest = {
        "mapper_id": ELECTRICAL_REGION_MAPPER_ID,
        "mapper_version": ELECTRICAL_REGION_MAPPER_VERSION,
        "landscape_rotation_convention": LANDSCAPE_ROTATION_CONVENTION,
    }
    identity_payload = {
        "mapper_manifest": mapper_manifest,
        "source_scene_revision_id": scene_revision_id,
        "source_module_instance_id": str(module_instance_id),
        "source_module_definition_revision_id": module_revision_id,
        "source_module_topology_revision_id": topology_revision_id,
        "source_receiver_id": receiver_id,
        "source_compiled_geometry_hash": geometry_hash,
        "coordinate_convention": MODULE_LOCAL_COORDINATE_CONVENTION,
        "placement_orientation": orientation,
        "source_receiver_area_m2": receiver_area,
        "mapped_region_area_m2": float(mapped_area),
        "mapped_region_area_fraction": float(mapped_fraction),
        "regions": regions,
    }
    digest = _canonical_sha256(identity_payload)
    return {
        "schema_name": "ElectricalRegionMap",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "authority": "derived_physics_only",
        "editable": False,
        "electrical_region_map_id": f"electrical-region-map:{module_instance_id}:{digest[:16]}",
        **identity_payload,
        "mapping_payload_sha256": digest,
        "findings": [],
    }
