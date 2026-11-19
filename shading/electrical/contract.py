"""Machine-enforced Phase-6.1 electrical-shading contract.

This module deliberately contains no production mismatch, bypass, module-IV,
string-IV, or MPPT operating-point solver. It freezes the canonical conventions
and capability gates that later Phase-6 tranches must consume.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


ELECTRICAL_SHADING_CONTRACT_VERSION = "0.1"

# Intrinsic module coordinates are independent of portrait/landscape placement.
# They are viewed from the module front side:
#   U = 0..1 from intrinsic module left to right across mechanical.width_m
#   V = 0..1 from intrinsic module bottom to top across mechanical.height_m
# Scene placement/orientation transforms this intrinsic plane into local ENU.
MODULE_LOCAL_COORDINATE_CONVENTION = "module_front_uv_normalized_width_height"
MODULE_ORIENTATION_REFERENCE = "viewed_from_module_front"

THERMAL_STATE_SCOPE = "single_module_temperature"

FIDELITY_LEVELS = (
    "level_0_geometric_only",
    "level_1_module_approximation",
    "level_2_bypass_substring",
    "level_3_cell_submodule_iv",
)
FIDELITY_ORDER = {name: index for index, name in enumerate(FIDELITY_LEVELS)}

REGION_RESOLUTIONS = {
    "cell",
    "half_cell",
    "grouped_cells",
    "submodule",
}

BYPASS_MODEL_TYPES = {
    "ideal",
    "constant_forward_drop",
    "parameterized_iv",
}

EXECUTABLE_TOPOLOGY_CLASS = "series_substrings_parallel_branches"

_TRUSTED_TOPOLOGY_STATES = {
    "reviewed",
    "manufacturer_verified",
}
_TOPOLOGY_STATES = {
    "unverified",
    "source_attached",
    "auto_validated",
    "reviewed",
    "manufacturer_verified",
}
_TOPOLOGY_PROVENANCE = {
    "direct_source",
    "manual_verified",
    "derived_validated",
    "inferred",
    "unresolved",
}
_TRUSTED_TOPOLOGY_PROVENANCE = {
    "direct_source",
    "manual_verified",
    "derived_validated",
}


_PARAMETERIZATION_SCOPES = {
    "region_substring",
    "cell",
}
_PARAMETERIZATION_VERIFICATION_STATES = {
    "auto_validated",
    "reviewed",
    "manufacturer_verified",
}
_PARAMETERIZATION_PROVENANCE = {
    "direct_source",
    "manual_verified",
    "derived_validated",
}


_BYPASS_MODEL_AUTHORITIES = {
    "component_model",
    "explicit_simulation_assumption",
}
_BYPASS_COMPONENT_VERIFICATION_STATES = {
    "unverified",
    "source_attached",
    "auto_validated",
    "reviewed",
    "manufacturer_verified",
}
_BYPASS_READY_COMPONENT_STATES = {
    "auto_validated",
    "reviewed",
    "manufacturer_verified",
}
_BYPASS_COMPONENT_PROVENANCE = {
    "direct_source",
    "manual_verified",
    "derived_validated",
}


class NumericalAssumptionInputError(ValueError):
    """Scientific integrity/authorization failure; never availability fallback."""


def deny_numerical_assumption_execution(evidence: Mapping[str, Any], *, authority=None) -> None:
    """Require a fully validated selected scientific authority for v0.2."""
    if evidence.get("schema_version") == "0.2" or "evidence_class" in evidence:
        from engine.simulation.detailed_inputs import (
            NumericalAssumptionAuthority, validate_assumption_authorization_witness, _bytes,
        )
        if type(authority) is NumericalAssumptionAuthority:
            checked = validate_assumption_authorization_witness(authority.witness)
            if (checked == authority and evidence.get("schema_version") == "0.2" and
                    authority.witness.evidence_sha256 == hashlib.sha256(_bytes(evidence)).hexdigest()):
                return
        raise NumericalAssumptionInputError(
            "NUMERICAL_ASSUMPTION_EXECUTION_DENIED: v0.2 requires the B3 authorization boundary"
        )


class ElectricalShadingContractError(ValueError):
    """Raised when Phase-6.1 electrical-shading semantics are violated."""


@dataclass(frozen=True)
class ResolvedModuleCapabilitySnapshot:
    module_revision_id: str | None
    resolution_id: str | None
    detailed_sdm_ready: bool
    findings: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class TopologyValidationResult:
    topology_present: bool
    topology_revision_id: str | None
    module_revision_id: str | None
    topology_structurally_valid: bool
    topology_trusted: bool
    region_geometry_execution_ready: bool
    bypass_coverage_complete: bool
    region_resolution: str | None
    findings: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class BypassModelEvidence:
    topology_revision_id: str | None
    bypass_models_ready: bool
    readiness_mode: str | None
    assumption_ids: tuple[str, ...] = ()
    findings: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ValidatedParameterizationEvidence:
    parameterization_scope: str
    ready: bool
    evidence_id: str | None
    module_revision_id: str | None
    topology_revision_id: str | None
    findings: tuple[dict[str, Any], ...] = ()


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ElectricalShadingContractError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ElectricalShadingContractError(f"{label} must be finite")
    return result


def validate_normalized_uv_polygon(
    vertices: Sequence[Sequence[float]],
) -> tuple[tuple[float, float], ...]:
    """Validate a non-degenerate polygon in normalized intrinsic module UV."""
    if len(vertices) < 3:
        raise ElectricalShadingContractError(
            "electrical region polygon requires at least three vertices"
        )

    normalized: list[tuple[float, float]] = []
    for index, vertex in enumerate(vertices):
        if not isinstance(vertex, Sequence) or len(vertex) != 2:
            raise ElectricalShadingContractError(
                f"polygon vertex {index} must contain exactly [u, v]"
            )
        u = _finite_number(vertex[0], f"polygon vertex {index}.u")
        v = _finite_number(vertex[1], f"polygon vertex {index}.v")
        if not 0.0 <= u <= 1.0 or not 0.0 <= v <= 1.0:
            raise ElectricalShadingContractError(
                "module-local UV coordinates must remain within [0, 1]"
            )
        normalized.append((u, v))

    # Structural topology validation deliberately stops at bounded, non-zero
    # polygon data. Simple-polygon and inter-region overlap checks belong to the
    # separate region-geometry execution-readiness gate below.
    area_twice = 0.0
    for index, (u1, v1) in enumerate(normalized):
        u2, v2 = normalized[(index + 1) % len(normalized)]
        area_twice += u1 * v2 - u2 * v1
    if abs(area_twice) <= 1e-12:
        raise ElectricalShadingContractError(
            "electrical region polygon must have non-zero area"
        )
    return tuple(normalized)


def _orientation(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_on_segment(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    eps: float = 1e-12,
) -> bool:
    if abs(_orientation(a, b, point)) > eps:
        return False
    return (
        min(a[0], b[0]) - eps <= point[0] <= max(a[0], b[0]) + eps
        and min(a[1], b[1]) - eps <= point[1] <= max(a[1], b[1]) + eps
    )


def _segments_properly_intersect(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
    *,
    eps: float = 1e-12,
) -> bool:
    o1 = _orientation(a1, a2, b1)
    o2 = _orientation(a1, a2, b2)
    o3 = _orientation(b1, b2, a1)
    o4 = _orientation(b1, b2, a2)
    return (
        ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps))
        and ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps))
    )


def _polygon_is_simple(
    polygon: Sequence[tuple[float, float]],
    *,
    eps: float = 1e-12,
) -> bool:
    count = len(polygon)
    if count < 3:
        return False

    # Repeated non-closing vertices create ambiguous zero-length or pinched edges.
    for i in range(count):
        for j in range(i + 1, count):
            if (
                abs(polygon[i][0] - polygon[j][0]) <= eps
                and abs(polygon[i][1] - polygon[j][1]) <= eps
            ):
                return False

    for i in range(count):
        a1 = polygon[i]
        a2 = polygon[(i + 1) % count]
        for j in range(i + 1, count):
            # Adjacent edges are expected to meet at their shared endpoint.
            if j == i or j == (i + 1) % count or (j + 1) % count == i:
                continue
            b1 = polygon[j]
            b2 = polygon[(j + 1) % count]

            if _segments_properly_intersect(a1, a2, b1, b2, eps=eps):
                return False

            # Non-adjacent endpoint/collinear contact is also non-simple.
            for point in (a1, a2):
                if _point_on_segment(point, b1, b2, eps=eps):
                    return False
            for point in (b1, b2):
                if _point_on_segment(point, a1, a2, eps=eps):
                    return False

    return True


def _point_location_in_polygon(
    point: tuple[float, float],
    polygon: Sequence[tuple[float, float]],
    *,
    eps: float = 1e-12,
) -> str:
    """Return outside, boundary, or inside for a simple polygon."""
    inside = False
    x, y = point
    count = len(polygon)

    for index in range(count):
        a = polygon[index]
        b = polygon[(index + 1) % count]
        if _point_on_segment(point, a, b, eps=eps):
            return "boundary"

        y1, y2 = a[1], b[1]
        if (y1 > y) == (y2 > y):
            continue
        x_cross = a[0] + (y - y1) * (b[0] - a[0]) / (y2 - y1)
        if x_cross > x + eps:
            inside = not inside

    return "inside" if inside else "outside"


def _polygons_have_positive_area_overlap(
    first: Sequence[tuple[float, float]],
    second: Sequence[tuple[float, float]],
    *,
    eps: float = 1e-12,
) -> bool:
    # Any proper boundary crossing implies positive-area interior overlap.
    for i in range(len(first)):
        a1 = first[i]
        a2 = first[(i + 1) % len(first)]
        for j in range(len(second)):
            b1 = second[j]
            b2 = second[(j + 1) % len(second)]
            if _segments_properly_intersect(a1, a2, b1, b2, eps=eps):
                return True

    # Containment catches nested/partially coincident polygons. Boundary-only
    # touching remains allowed.
    if any(_point_location_in_polygon(p, second, eps=eps) == "inside" for p in first):
        return True
    if any(_point_location_in_polygon(p, first, eps=eps) == "inside" for p in second):
        return True

    # Collinear boundary overlap can create positive-area overlap while all
    # vertices lie on/outside the other polygon. Edge midpoints catch the common
    # rectilinear/module-region cases without treating shared boundaries as area.
    first_midpoints = [
        (
            (first[i][0] + first[(i + 1) % len(first)][0]) / 2.0,
            (first[i][1] + first[(i + 1) % len(first)][1]) / 2.0,
        )
        for i in range(len(first))
    ]
    second_midpoints = [
        (
            (second[i][0] + second[(i + 1) % len(second)][0]) / 2.0,
            (second[i][1] + second[(i + 1) % len(second)][1]) / 2.0,
        )
        for i in range(len(second))
    ]
    if any(
        _point_location_in_polygon(p, second, eps=eps) == "inside"
        for p in first_midpoints
    ):
        return True
    if any(
        _point_location_in_polygon(p, first, eps=eps) == "inside"
        for p in second_midpoints
    ):
        return True

    # Identical polygons have all vertices on the opposite boundary, so the
    # strict-inside tests above do not fire.
    first_set = {(round(p[0], 12), round(p[1], 12)) for p in first}
    second_set = {(round(p[0], 12), round(p[1], 12)) for p in second}
    return len(first_set) == len(first) and first_set == second_set


def resolve_region_geometry_execution_readiness(
    topology_definition: Mapping[str, Any] | None,
    *,
    topology_structurally_valid: bool,
    findings: list[dict[str, Any]] | None = None,
) -> bool:
    """Check whether physical-region polygons are safe for geometry-dependent execution.

    Structural topology validity answers whether the electrical mapping is
    intelligible. This gate separately requires simple polygons and rejects
    positive-area overlap between distinct physical regions. Shared boundaries
    and point/edge touching remain valid.
    """
    if not topology_structurally_valid or topology_definition is None:
        return False

    sink = findings if findings is not None else []
    regions = topology_definition.get("physical_regions") or []
    normalized: list[tuple[str, tuple[tuple[float, float], ...]]] = []

    for region in regions:
        region_id = str(region.get("region_id") or "unknown")
        polygon = validate_normalized_uv_polygon(region.get("polygon_normalized") or [])
        if not _polygon_is_simple(polygon):
            sink.append(
                {
                    "code": "ELECTRICAL_SHADING_REGION_GEOMETRY_SELF_INTERSECTION",
                    "severity": "warning",
                    "message": (
                        f"Physical region {region_id} is structurally recorded but "
                        "its polygon is not simple; geometry-dependent Level 2 "
                        "execution remains disabled."
                    ),
                }
            )
            return False
        normalized.append((region_id, polygon))

    for index, (first_id, first_polygon) in enumerate(normalized):
        for second_id, second_polygon in normalized[index + 1 :]:
            if _polygons_have_positive_area_overlap(first_polygon, second_polygon):
                sink.append(
                    {
                        "code": "ELECTRICAL_SHADING_REGION_GEOMETRY_OVERLAP",
                        "severity": "warning",
                        "message": (
                            f"Physical regions {first_id} and {second_id} overlap "
                            "with positive area; geometry-dependent Level 2 "
                            "execution remains disabled."
                        ),
                    }
                )
                return False

    return True


def assert_bypass_model_contract(
    model: Mapping[str, Any],
    *,
    device_id: str = "unknown",
) -> None:
    """Validate stored bypass-model semantics without claiming execution readiness."""
    model_type = model.get("model_type")
    if model_type not in BYPASS_MODEL_TYPES:
        raise ElectricalShadingContractError(
            f"bypass device {device_id} uses unsupported model_type"
        )

    for field in ("model_id", "model_version"):
        value = model.get(field)
        if not isinstance(value, str) or not value:
            raise ElectricalShadingContractError(
                f"bypass device {device_id} {field} must be explicit"
            )

    authority = model.get("model_authority")
    if authority not in _BYPASS_MODEL_AUTHORITIES:
        raise ElectricalShadingContractError(
            f"bypass device {device_id} model_authority must distinguish "
            "component_model from explicit_simulation_assumption"
        )

    parameters = model.get("parameters")
    if not isinstance(parameters, Mapping):
        raise ElectricalShadingContractError(
            f"bypass device {device_id} model parameters must be an object"
        )
    if model_type == "constant_forward_drop":
        forward_voltage = _finite_number(
            parameters.get("forward_voltage_v"),
            f"bypass device {device_id} forward_voltage_v",
        )
        if forward_voltage < 0.0:
            raise ElectricalShadingContractError(
                f"bypass device {device_id} forward_voltage_v must be non-negative"
            )
    if model_type == "parameterized_iv" and not parameters:
        raise ElectricalShadingContractError(
            f"bypass device {device_id} parameterized_iv requires parameters"
        )

    source_ids = model.get("source_ids")
    if (
        not isinstance(source_ids, list)
        or any(not isinstance(value, str) or not value for value in source_ids)
        or len(set(source_ids)) != len(source_ids)
    ):
        raise ElectricalShadingContractError(
            f"bypass device {device_id} source_ids must be a unique string array"
        )

    payload_hash = model.get("model_payload_sha256")
    if (
        not isinstance(payload_hash, str)
        or len(payload_hash) != 64
        or any(ch not in "0123456789abcdef" for ch in payload_hash)
    ):
        raise ElectricalShadingContractError(
            f"bypass device {device_id} model_payload_sha256 must be a lowercase SHA-256 hex digest"
        )

    validation_record_id = model.get("validation_record_id")
    assumption_id = model.get("assumption_id")
    assumption_rationale = model.get("assumption_rationale")
    verification_state = model.get("verification_state")
    provenance = model.get("model_provenance")

    if authority == "component_model":
        if verification_state not in _BYPASS_COMPONENT_VERIFICATION_STATES:
            raise ElectricalShadingContractError(
                f"bypass device {device_id} component-model verification_state is invalid"
            )
        if provenance not in _BYPASS_COMPONENT_PROVENANCE:
            raise ElectricalShadingContractError(
                f"bypass device {device_id} component-model provenance is invalid"
            )
        if validation_record_id is not None and (
            not isinstance(validation_record_id, str) or not validation_record_id
        ):
            raise ElectricalShadingContractError(
                f"bypass device {device_id} validation_record_id must be string or null"
            )
        if assumption_id is not None or assumption_rationale is not None:
            raise ElectricalShadingContractError(
                f"bypass device {device_id} component_model cannot carry assumption identity"
            )
        return

    if verification_state != "not_applicable":
        raise ElectricalShadingContractError(
            f"bypass device {device_id} simulation assumption verification_state must be not_applicable"
        )
    if provenance != "simulation_assumption":
        raise ElectricalShadingContractError(
            f"bypass device {device_id} simulation assumption provenance must be simulation_assumption"
        )
    if validation_record_id is not None:
        raise ElectricalShadingContractError(
            f"bypass device {device_id} simulation assumption cannot claim a validation record"
        )
    if not isinstance(assumption_id, str) or not assumption_id:
        raise ElectricalShadingContractError(
            f"bypass device {device_id} simulation assumption requires assumption_id"
        )
    if not isinstance(assumption_rationale, str) or not assumption_rationale:
        raise ElectricalShadingContractError(
            f"bypass device {device_id} simulation assumption requires assumption_rationale"
        )


def assert_module_topology_definition(topology: Mapping[str, Any]) -> None:
    """Fail closed when a ModuleTopologyDefinition is internally ambiguous.

    The v0.1 executable topology class represents protected substrings in series.
    Each protected substring may contain one or more parallel branches, and each
    branch preserves an explicit ordered list of physical electrical regions.
    The contract does not infer wiring from cell count or bypass-diode count.
    """
    if topology.get("schema_name") != "ModuleTopologyDefinition":
        raise ElectricalShadingContractError(
            "schema_name must be 'ModuleTopologyDefinition'"
        )
    if topology.get("schema_version") != "0.1":
        raise ElectricalShadingContractError(
            "ModuleTopologyDefinition schema_version must be '0.1'"
        )
    if topology.get("contract_version") != ELECTRICAL_SHADING_CONTRACT_VERSION:
        raise ElectricalShadingContractError(
            "module topology contract_version must be '0.1'"
        )
    topology_id = topology.get("module_topology_id")
    if not isinstance(topology_id, str) or not topology_id:
        raise ElectricalShadingContractError("module_topology_id must be explicit")
    topology_version = topology.get("topology_version")
    if not isinstance(topology_version, str) or not topology_version:
        raise ElectricalShadingContractError("topology_version must be explicit")
    if topology.get("orientation_reference") != MODULE_ORIENTATION_REFERENCE:
        raise ElectricalShadingContractError(
            "module topology orientation_reference does not match Phase-6.1"
        )
    if topology.get("coordinate_convention") != MODULE_LOCAL_COORDINATE_CONVENTION:
        raise ElectricalShadingContractError(
            "module topology coordinate_convention does not match Phase-6.1"
        )
    if topology.get("topology_class") != EXECUTABLE_TOPOLOGY_CLASS:
        raise ElectricalShadingContractError(
            "unsupported v0.1 topology_class; do not coerce unusual wiring into "
            "the common series-substrings/parallel-branches contract"
        )

    module_revision_id = topology.get("module_definition_revision_id")
    if not isinstance(module_revision_id, str) or not module_revision_id:
        raise ElectricalShadingContractError(
            "module_definition_revision_id must be explicit"
        )

    region_resolution = topology.get("region_resolution")
    if region_resolution not in REGION_RESOLUTIONS:
        raise ElectricalShadingContractError(
            "region_resolution must be one of "
            + ", ".join(sorted(REGION_RESOLUTIONS))
        )

    verification_state = topology.get("verification_state")
    if verification_state not in _TOPOLOGY_STATES:
        raise ElectricalShadingContractError(
            "module topology verification_state is invalid"
        )
    topology_provenance = topology.get("topology_provenance")
    if topology_provenance not in _TOPOLOGY_PROVENANCE:
        raise ElectricalShadingContractError(
            "module topology topology_provenance is invalid"
        )
    source_ids = topology.get("source_ids")
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or any(not isinstance(value, str) or not value for value in source_ids)
    ):
        raise ElectricalShadingContractError(
            "module topology requires at least one explicit source_id"
        )

    regions = topology.get("physical_regions")
    if not isinstance(regions, list) or not regions:
        raise ElectricalShadingContractError(
            "physical_regions must contain at least one explicit region"
        )

    region_ids: set[str] = set()
    declared_substring_by_region: dict[str, str] = {}
    for region in regions:
        if not isinstance(region, Mapping):
            raise ElectricalShadingContractError(
                "physical_regions entries must be objects"
            )
        region_id = region.get("region_id")
        if not isinstance(region_id, str) or not region_id:
            raise ElectricalShadingContractError("physical region_id is required")
        if region_id in region_ids:
            raise ElectricalShadingContractError(
                f"duplicate physical region_id: {region_id}"
            )
        region_ids.add(region_id)
        region_type = region.get("region_type")
        if region_type != region_resolution:
            raise ElectricalShadingContractError(
                f"physical region {region_id} region_type {region_type!r} "
                f"does not match declared region_resolution {region_resolution!r}"
            )
        validate_normalized_uv_polygon(region.get("polygon_normalized") or [])
        declared_substring = region.get("electrical_substring_id")
        if not isinstance(declared_substring, str) or not declared_substring:
            raise ElectricalShadingContractError(
                f"physical region {region_id} requires electrical_substring_id"
            )
        declared_substring_by_region[region_id] = declared_substring
        count = region.get("equivalent_element_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ElectricalShadingContractError(
                f"physical region {region_id} requires equivalent_element_count >= 1"
            )

    substrings = topology.get("electrical_substrings")
    if not isinstance(substrings, list) or not substrings:
        raise ElectricalShadingContractError(
            "electrical_substrings must contain at least one protected substring"
        )

    substring_ids: set[str] = set()
    series_orders: set[int] = set()
    mapped_regions: set[str] = set()
    for substring in substrings:
        if not isinstance(substring, Mapping):
            raise ElectricalShadingContractError(
                "electrical_substrings entries must be objects"
            )
        substring_id = substring.get("substring_id")
        if not isinstance(substring_id, str) or not substring_id:
            raise ElectricalShadingContractError("substring_id is required")
        if substring_id in substring_ids:
            raise ElectricalShadingContractError(
                f"duplicate substring_id: {substring_id}"
            )
        substring_ids.add(substring_id)

        series_order = substring.get("series_order")
        if (
            isinstance(series_order, bool)
            or not isinstance(series_order, int)
            or series_order < 0
        ):
            raise ElectricalShadingContractError(
                f"substring {substring_id} requires non-negative series_order"
            )
        if series_order in series_orders:
            raise ElectricalShadingContractError(
                f"duplicate substring series_order: {series_order}"
            )
        series_orders.add(series_order)

        declared_region_ids = substring.get("physical_region_ids")
        if (
            not isinstance(declared_region_ids, list)
            or not declared_region_ids
            or len(set(declared_region_ids)) != len(declared_region_ids)
        ):
            raise ElectricalShadingContractError(
                f"substring {substring_id} requires unique physical_region_ids"
            )
        for region_id in declared_region_ids:
            if region_id not in region_ids:
                raise ElectricalShadingContractError(
                    f"substring {substring_id} references unknown region {region_id}"
                )
            if declared_substring_by_region.get(region_id) != substring_id:
                raise ElectricalShadingContractError(
                    f"region {region_id} electrical_substring_id does not match "
                    f"substring {substring_id}"
                )

        branches = substring.get("parallel_branches")
        if not isinstance(branches, list) or not branches:
            raise ElectricalShadingContractError(
                f"substring {substring_id} requires at least one parallel branch"
            )
        branch_ids: set[str] = set()
        substring_branch_regions: set[str] = set()
        for branch in branches:
            if not isinstance(branch, Mapping):
                raise ElectricalShadingContractError(
                    f"substring {substring_id} branch must be an object"
                )
            branch_id = branch.get("branch_id")
            if not isinstance(branch_id, str) or not branch_id:
                raise ElectricalShadingContractError(
                    f"substring {substring_id} branch_id is required"
                )
            if branch_id in branch_ids:
                raise ElectricalShadingContractError(
                    f"duplicate branch_id {branch_id} in substring {substring_id}"
                )
            branch_ids.add(branch_id)

            ordered_regions = branch.get("series_region_ids")
            if not isinstance(ordered_regions, list) or not ordered_regions:
                raise ElectricalShadingContractError(
                    f"branch {branch_id} requires ordered series_region_ids"
                )
            for region_id in ordered_regions:
                if region_id not in region_ids:
                    raise ElectricalShadingContractError(
                        f"branch {branch_id} references unknown region {region_id}"
                    )
                if region_id in mapped_regions:
                    raise ElectricalShadingContractError(
                        f"physical region {region_id} appears in more than one "
                        "electrical branch; cross-tied/custom wiring requires a "
                        "future explicit topology class"
                    )
                mapped_regions.add(region_id)
                substring_branch_regions.add(region_id)

        if substring_branch_regions != set(declared_region_ids):
            raise ElectricalShadingContractError(
                f"substring {substring_id} physical_region_ids must exactly match "
                "the union of its parallel branch region IDs"
            )

    expected_orders = set(range(len(substrings)))
    if series_orders != expected_orders:
        raise ElectricalShadingContractError(
            "substring series_order must be contiguous from 0"
        )
    if mapped_regions != region_ids:
        missing = sorted(region_ids - mapped_regions)
        raise ElectricalShadingContractError(
            "every physical region must map to exactly one explicit branch; "
            f"unmapped regions: {missing}"
        )

    devices = topology.get("bypass_devices")
    if not isinstance(devices, list):
        raise ElectricalShadingContractError("bypass_devices must be an array")

    device_ids: set[str] = set()
    protected_substrings: set[str] = set()
    for device in devices:
        if not isinstance(device, Mapping):
            raise ElectricalShadingContractError("bypass device must be an object")
        device_id = device.get("bypass_device_id")
        if not isinstance(device_id, str) or not device_id:
            raise ElectricalShadingContractError("bypass_device_id is required")
        if device_id in device_ids:
            raise ElectricalShadingContractError(
                f"duplicate bypass_device_id: {device_id}"
            )
        device_ids.add(device_id)

        if device.get("device_type") != "bypass_diode":
            raise ElectricalShadingContractError(
                f"bypass device {device_id} device_type must be bypass_diode"
            )

        model = device.get("forward_voltage_model")
        if model is not None:
            if not isinstance(model, Mapping):
                raise ElectricalShadingContractError(
                    f"bypass device {device_id} forward_voltage_model must be an object or null"
                )
            assert_bypass_model_contract(model, device_id=device_id)

        protected = device.get("protects_substring_ids")
        if not isinstance(protected, list) or not protected:
            raise ElectricalShadingContractError(
                f"bypass device {device_id} must protect explicit substring IDs"
            )
        for substring_id in protected:
            if substring_id not in substring_ids:
                raise ElectricalShadingContractError(
                    f"bypass device {device_id} references unknown substring "
                    f"{substring_id}"
                )
            protected_substrings.add(substring_id)

    # Coverage describes known wiring only. Forward-voltage model completeness
    # is a separate Level-2 capability requirement.
    if topology.get("bypass_coverage_complete") is True:
        if protected_substrings != substring_ids:
            raise ElectricalShadingContractError(
                "bypass_coverage_complete=true requires every substring to be "
                "protected by an explicit bypass device"
            )

    device_by_id = {
        str(device.get("bypass_device_id")): device
        for device in devices
        if isinstance(device, Mapping) and device.get("bypass_device_id")
    }
    for substring in substrings:
        substring_id = str(substring["substring_id"])
        declared_device_id = substring.get("bypass_device_id")
        if declared_device_id is None:
            continue
        device = device_by_id.get(str(declared_device_id))
        if device is None:
            raise ElectricalShadingContractError(
                f"substring {substring_id} references unknown bypass_device_id "
                f"{declared_device_id}"
            )
        if substring_id not in set(device.get("protects_substring_ids") or []):
            raise ElectricalShadingContractError(
                f"substring {substring_id} bypass_device_id does not protect it"
            )


def _resolve_bypass_model_readiness(
    topology_definition: Mapping[str, Any] | None,
    *,
    topology_valid: bool,
    findings: list[dict[str, Any]],
) -> tuple[bool, str | None, list[str]]:
    """Resolve executable bypass-model readiness without conflating assumptions with truth."""
    if not topology_valid or topology_definition is None:
        return False, None, []

    devices = topology_definition.get("bypass_devices") or []
    if not devices:
        return False, None, []

    modes: list[str] = []
    assumption_ids: list[str] = []
    ready = True

    for device in devices:
        if not isinstance(device, Mapping):
            ready = False
            continue
        device_id = str(device.get("bypass_device_id") or "unknown")
        model = device.get("forward_voltage_model")
        if not isinstance(model, Mapping):
            findings.append(
                {
                    "code": "ELECTRICAL_SHADING_BYPASS_MODEL_MISSING",
                    "severity": "info",
                    "message": f"Bypass device {device_id} has no forward-voltage model.",
                }
            )
            ready = False
            continue

        try:
            assert_bypass_model_contract(model, device_id=device_id)
        except ElectricalShadingContractError as exc:
            findings.append(
                {
                    "code": "ELECTRICAL_SHADING_BYPASS_MODEL_INVALID",
                    "severity": "warning",
                    "message": str(exc),
                }
            )
            ready = False
            continue

        authority = model.get("model_authority")
        if authority == "component_model":
            verified = (
                model.get("verification_state") in _BYPASS_READY_COMPONENT_STATES
                and model.get("model_provenance") in _BYPASS_COMPONENT_PROVENANCE
                and isinstance(model.get("validation_record_id"), str)
                and bool(model.get("validation_record_id"))
                and isinstance(model.get("source_ids"), list)
                and bool(model.get("source_ids"))
            )
            if not verified:
                findings.append(
                    {
                        "code": "ELECTRICAL_SHADING_BYPASS_COMPONENT_MODEL_NOT_VERIFIED",
                        "severity": "info",
                        "message": (
                            f"Bypass device {device_id} has a component model, but "
                            "its verification/provenance/validation evidence is not "
                            "sufficient for Level 2 execution."
                        ),
                    }
                )
                ready = False
                continue
            modes.append("validated_component_model")
            continue

        assumption_id = str(model.get("assumption_id"))
        assumption_ids.append(assumption_id)
        modes.append("explicit_simulation_assumption")
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_BYPASS_ASSUMPTION_ACTIVE",
                "severity": "info",
                "message": (
                    f"Bypass device {device_id} uses explicit simulation assumption "
                    f"{assumption_id}; this is not source-validated component truth."
                ),
            }
        )

    if not ready:
        return False, None, sorted(set(assumption_ids))

    unique_modes = set(modes)
    if unique_modes == {"validated_component_model"}:
        mode = "validated_component_models"
    elif unique_modes == {"explicit_simulation_assumption"}:
        mode = "explicit_simulation_assumptions"
    else:
        mode = "mixed_validated_and_assumed"
    return True, mode, sorted(set(assumption_ids))


REQUIRED_NUMERICAL_ASSUMPTION_LIMITATIONS = (
    "Hypothetical internal substring connectivity.",
    "Hypothetical regional parameter distribution.",
    "Lack of independent region-level calibration.",
    "Lack of manufacturer topology confirmation.",
    "Uniform-IV agreement is not physical-yield validation.",
    "Assumed bypass-diode and reverse-bias behavior.",
    "Single-module temperature scope.",
    "Finite sampled-IV/interpolation limitations.",
)
NUMERICAL_ASSUMPTION_POLICY_ID = "rawibumi.level2.uniform_iv_equal_series"
NUMERICAL_ASSUMPTION_POLICY_VERSION = "1.0.0"
NUMERICAL_ASSUMPTION_CURRENT_FRACTIONS = (0.10, 0.30, 0.50, 0.70, 0.90)


def numerical_assumption_object_sha256(payload: Mapping[str, Any]) -> str:
    """Hash all supplied fields except this object's own digest; insert no defaults."""
    return _canonical_sha256({k: v for k, v in payload.items() if k != "digest_sha256"})


def assert_numerical_assumption_evidence_structure(evidence: Mapping[str, Any]) -> None:
    """Validate B1 recorded evidence integrity, without physics or execution authority.

    Production readiness deliberately continues to use the v0.1-only validator.
    Isc fractions, selected asset fingerprints and physical gates require B2+.
    """
    from pathlib import Path

    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError

    if evidence.get("schema_version") != "0.2":
        raise ElectricalShadingContractError("numerical evidence schema_version must be '0.2'")
    schema = json.loads(
        Path(__file__).with_name("electrical-parameterization-evidence.schema.json")
        .read_text(encoding="utf-8")
    )
    try:
        Draft202012Validator(schema).validate(evidence)
    except ValidationError as exc:
        raise ElectricalShadingContractError(f"invalid numerical evidence: {exc.message}") from exc

    def strict_values(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key.endswith("sha256") and (
                    not isinstance(child, str) or len(child) != 64
                    or any(character not in "0123456789abcdef" for character in child)
                ):
                    raise ElectricalShadingContractError("digests must be lowercase 64-hex SHA-256")
                strict_values(child)
        elif isinstance(value, list):
            for child in value:
                strict_values(child)
        elif isinstance(value, str) and not value.strip():
            raise ElectricalShadingContractError("typed numerical evidence strings must be meaningful")
        elif type(value) in (int, float):
            if not math.isfinite(value) or (value == 0 and math.copysign(1, value) < 0):
                raise ElectricalShadingContractError("numerical evidence requires finite values without negative zero")

    declaration = evidence["assumption_declaration"]
    record = evidence["consistency_record"]
    strict_values({"parameterization_payload_sha256": evidence["parameterization_payload_sha256"]})
    strict_values(declaration)
    strict_values(record)
    if type(declaration["region_count"]) is not int:
        raise ElectricalShadingContractError("region_count must be an integer")
    limitations = declaration["scientific_limitations"]
    if (tuple(limitations[:8]) != REQUIRED_NUMERICAL_ASSUMPTION_LIMITATIONS
            or limitations[8:] != sorted(limitations[8:])):
        raise ElectricalShadingContractError("scientific limitations must have the canonical ordered prefix")
    for name, value in (("assumption_declaration", declaration), ("consistency_record", record)):
        if numerical_assumption_object_sha256(value) != value["digest_sha256"]:
            raise ElectricalShadingContractError(f"{name} digest mismatch")
    bindings = (
        (evidence["evidence_class"], declaration["evidence_class"]),
        (evidence["parameterization_id"], declaration["parameterization"]["parameterization_id"]),
        (evidence["parameterization_revision_id"], declaration["parameterization"]["parameterization_revision_id"]),
        (evidence["parameterization_payload_sha256"], declaration["parameterization"]["parameterization_sha256"]),
        (evidence["module_definition_revision_id"], declaration["module_source"]["revision_id"]),
        (evidence["module_topology_revision_id"], declaration["topology"]["topology_revision_id"]),
        (record["assumption_digest_sha256"], declaration["digest_sha256"]),
    )
    if any(left != right for left, right in bindings):
        raise ElectricalShadingContractError("numerical evidence cross-field binding mismatch")
    residuals = []
    for case, conditions in zip(record["cases"], ((1000, 25), (800, 45), (400, 15))):
        if (case["irradiance_w_m2"], case["cell_temperature_c"]) != conditions:
            raise ElectricalShadingContractError("consistency cases must follow policy order")
        previous_current = -1
        for sample in case["samples"]:
            current = sample["current_a"]
            if current <= previous_current:
                raise ElectricalShadingContractError("consistency currents must be strictly ascending")
            previous_current = current
            residual = sample["assembled_voltage_v"] - sample["module_voltage_v"]
            if sample["residual_v"] != residual:
                raise ElectricalShadingContractError("consistency residual must be assembled minus module voltage")
            residuals.append(abs(residual))
    maximum = max(residuals)
    if record["max_abs_residual_v"] != maximum:
        raise ElectricalShadingContractError("consistency maximum residual mismatch")
    # This is only the recorded-value gate. A false result may reflect deferred
    # physical gates; a true result cannot override failure of this necessary gate.
    if record["passed"] and maximum > record["voltage_tolerance_v"]:
        raise ElectricalShadingContractError("consistency passed contradicts recorded residuals")


def assert_electrical_parameterization_evidence(
    evidence: Mapping[str, Any],
    *,
    expected_scope: str | None = None,
) -> None:
    """Validate revision-bound evidence for detailed electrical parameterization.

    This object proves more than availability: it identifies the parameterization,
    its model/version, validation record, provenance, exact module/topology
    revisions, and immutable payload hash. Capability booleans are derived from
    this evidence; they are never accepted as authoritative resolver inputs.
    """
    if evidence.get("schema_name") != "ElectricalParameterizationEvidence":
        raise ElectricalShadingContractError(
            "schema_name must be 'ElectricalParameterizationEvidence'"
        )
    if evidence.get("schema_version") != "0.1":
        raise ElectricalShadingContractError(
            "ElectricalParameterizationEvidence schema_version must be '0.1'"
        )
    if evidence.get("contract_version") != ELECTRICAL_SHADING_CONTRACT_VERSION:
        raise ElectricalShadingContractError(
            "parameterization evidence contract_version must be '0.1'"
        )

    scope = evidence.get("parameterization_scope")
    if scope not in _PARAMETERIZATION_SCOPES:
        raise ElectricalShadingContractError(
            "parameterization_scope must be 'region_substring' or 'cell'"
        )
    if expected_scope is not None and scope != expected_scope:
        raise ElectricalShadingContractError(
            f"parameterization evidence scope {scope!r} does not match "
            f"required scope {expected_scope!r}"
        )

    required_strings = (
        "evidence_id",
        "parameterization_id",
        "module_definition_revision_id",
        "module_topology_revision_id",
        "model_id",
        "model_version",
        "validation_record_id",
    )
    for field in required_strings:
        value = evidence.get(field)
        if not isinstance(value, str) or not value:
            raise ElectricalShadingContractError(
                f"parameterization evidence {field} must be explicit"
            )

    if evidence.get("validation_status") != "passed":
        raise ElectricalShadingContractError(
            "parameterization evidence validation_status must be 'passed'"
        )
    if evidence.get("verification_state") not in _PARAMETERIZATION_VERIFICATION_STATES:
        raise ElectricalShadingContractError(
            "parameterization evidence verification_state is not capability-authorizing"
        )
    if evidence.get("parameterization_provenance") not in _PARAMETERIZATION_PROVENANCE:
        raise ElectricalShadingContractError(
            "parameterization evidence provenance must be direct or validated"
        )

    source_ids = evidence.get("source_ids")
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or any(not isinstance(value, str) or not value for value in source_ids)
        or len(set(source_ids)) != len(source_ids)
    ):
        raise ElectricalShadingContractError(
            "parameterization evidence requires unique explicit source_ids"
        )

    payload_hash = evidence.get("parameterization_payload_sha256")
    if (
        not isinstance(payload_hash, str)
        or len(payload_hash) != 64
        or any(ch not in "0123456789abcdef" for ch in payload_hash)
    ):
        raise ElectricalShadingContractError(
            "parameterization_payload_sha256 must be a lowercase SHA-256 hex digest"
        )


def validate_parameterization_for_electrical_shading(
    evidence: Mapping[str, Any] | None,
    *,
    expected_scope: str,
    module_definition: Mapping[str, Any],
    topology_definition: Mapping[str, Any] | None,
) -> ValidatedParameterizationEvidence:
    """Validate raw parameterization evidence before pure capability derivation."""
    findings: list[dict[str, Any]] = []
    module_revision_id = module_definition.get("revision_id")
    topology_revision_id = (
        topology_definition.get("revision_id")
        if topology_definition is not None
        else None
    )

    if evidence is None:
        return ValidatedParameterizationEvidence(
            parameterization_scope=expected_scope,
            ready=False,
            evidence_id=None,
            module_revision_id=(
                str(module_revision_id) if isinstance(module_revision_id, str) else None
            ),
            topology_revision_id=(
                str(topology_revision_id)
                if isinstance(topology_revision_id, str)
                else None
            ),
        )

    try:
        assert_electrical_parameterization_evidence(
            evidence,
            expected_scope=expected_scope,
        )
    except ElectricalShadingContractError as exc:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_PARAMETERIZATION_EVIDENCE_INVALID",
                "severity": "warning",
                "message": str(exc),
            }
        )
        return ValidatedParameterizationEvidence(
            parameterization_scope=expected_scope,
            ready=False,
            evidence_id=(
                str(evidence.get("evidence_id"))
                if evidence.get("evidence_id") is not None
                else None
            ),
            module_revision_id=(
                str(module_revision_id) if isinstance(module_revision_id, str) else None
            ),
            topology_revision_id=(
                str(topology_revision_id)
                if isinstance(topology_revision_id, str)
                else None
            ),
            findings=tuple(findings),
        )

    if evidence.get("module_definition_revision_id") != module_revision_id:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_PARAMETERIZATION_MODULE_REVISION_MISMATCH",
                "severity": "warning",
                "message": (
                    "Electrical parameterization evidence must reference the exact "
                    "selected ModuleDefinition revision."
                ),
            }
        )

    if topology_definition is None:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_PARAMETERIZATION_TOPOLOGY_REQUIRED",
                "severity": "warning",
                "message": (
                    "Electrical parameterization evidence cannot authorize detailed "
                    "fidelity without the topology revision it is bound to."
                ),
            }
        )
    elif evidence.get("module_topology_revision_id") != topology_revision_id:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_PARAMETERIZATION_TOPOLOGY_REVISION_MISMATCH",
                "severity": "warning",
                "message": (
                    "Electrical parameterization evidence must reference the exact "
                    "selected ModuleTopologyDefinition revision."
                ),
            }
        )

    return ValidatedParameterizationEvidence(
        parameterization_scope=expected_scope,
        ready=not findings,
        evidence_id=str(evidence.get("evidence_id")),
        module_revision_id=(
            str(module_revision_id) if isinstance(module_revision_id, str) else None
        ),
        topology_revision_id=(
            str(topology_revision_id)
            if isinstance(topology_revision_id, str)
            else None
        ),
        findings=tuple(findings),
    )


def assert_resolved_module_capability_evidence(
    evidence: Mapping[str, Any],
    *,
    expected_module_revision_id: str,
) -> None:
    """Validate the trusted component-resolution handoff for detailed SDM use.

    The authoritative fact is not a raw capability boolean. Detailed-SDM
    readiness requires a resolved module artifact bound to the exact component
    revision whose selected model is the validated detailed single-diode model.
    The capability snapshot must agree with that resolved model state.
    """
    if evidence.get("schema_name") != "ResolvedComponentModel":
        raise ElectricalShadingContractError(
            "module capability evidence must be a ResolvedComponentModel"
        )
    if evidence.get("schema_version") != "0.1":
        raise ElectricalShadingContractError(
            "ResolvedComponentModel schema_version must be '0.1'"
        )
    resolution_id = evidence.get("resolution_id")
    if not isinstance(resolution_id, str) or not resolution_id:
        raise ElectricalShadingContractError(
            "ResolvedComponentModel resolution_id must be explicit"
        )
    if evidence.get("component_type") != "module":
        raise ElectricalShadingContractError(
            "module capability evidence component_type must be 'module'"
        )
    if evidence.get("component_revision_id") != expected_module_revision_id:
        raise ElectricalShadingContractError(
            "module capability evidence must reference the exact selected ModuleDefinition revision"
        )
    if evidence.get("status") != "resolved":
        raise ElectricalShadingContractError(
            "module capability evidence status must be 'resolved'"
        )

    selected = evidence.get("selected_model")
    if not isinstance(selected, Mapping):
        raise ElectricalShadingContractError(
            "module capability evidence requires an explicit selected_model"
        )
    if selected.get("component_type") != "module":
        raise ElectricalShadingContractError(
            "resolved selected_model component_type must be 'module'"
        )
    if selected.get("model_id") != "module.pvsyst_singlediode.v6":
        raise ElectricalShadingContractError(
            "detailed electrical shading requires resolved model module.pvsyst_singlediode.v6"
        )
    if selected.get("model_family") != "single_diode":
        raise ElectricalShadingContractError(
            "resolved detailed module model must declare single_diode model_family"
        )
    if selected.get("implementation_status") != "validated_contract":
        raise ElectricalShadingContractError(
            "resolved detailed module model must use a validated_contract implementation"
        )
    if selected.get("validation_status") != "passed":
        raise ElectricalShadingContractError(
            "resolved detailed module model validation_status must be 'passed'"
        )
    parameter_source_path = selected.get("parameter_source_path")
    if not isinstance(parameter_source_path, str) or not parameter_source_path:
        raise ElectricalShadingContractError(
            "resolved detailed module model parameter_source_path must be explicit"
        )

    source_ids = evidence.get("source_ids")
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or any(not isinstance(value, str) or not value for value in source_ids)
        or len(set(source_ids)) != len(source_ids)
    ):
        raise ElectricalShadingContractError(
            "ResolvedComponentModel requires unique explicit source_ids"
        )

    snapshot = evidence.get("capability_snapshot")
    if not isinstance(snapshot, Mapping):
        raise ElectricalShadingContractError(
            "ResolvedComponentModel capability_snapshot must be an object"
        )
    if snapshot.get("detailed_sdm_ready") is not True:
        raise ElectricalShadingContractError(
            "resolved capability_snapshot does not confirm detailed_sdm_ready"
        )


def resolve_module_capability_snapshot(
    module_definition: Mapping[str, Any],
    evidence: Mapping[str, Any] | None,
) -> ResolvedModuleCapabilitySnapshot:
    """Produce the validated module capability snapshot consumed by shading."""
    findings: list[dict[str, Any]] = []
    revision_id = module_definition.get("revision_id")
    normalized_revision_id = (
        str(revision_id) if isinstance(revision_id, str) and revision_id else None
    )

    if evidence is None:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_MODULE_CAPABILITY_EVIDENCE_REQUIRED",
                "severity": "info",
                "message": (
                    "Level 1+ electrical shading requires the ResolvedComponentModel "
                    "produced by the trusted component/model-resolution pipeline."
                ),
            }
        )
        return ResolvedModuleCapabilitySnapshot(
            module_revision_id=normalized_revision_id,
            resolution_id=None,
            detailed_sdm_ready=False,
            findings=tuple(findings),
        )

    if normalized_revision_id is None:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_MODULE_REVISION_REQUIRED",
                "severity": "warning",
                "message": "ModuleDefinition revision_id must be explicit.",
            }
        )
        return ResolvedModuleCapabilitySnapshot(
            module_revision_id=None,
            resolution_id=(
                str(evidence.get("resolution_id"))
                if evidence.get("resolution_id") is not None
                else None
            ),
            detailed_sdm_ready=False,
            findings=tuple(findings),
        )

    try:
        assert_resolved_module_capability_evidence(
            evidence,
            expected_module_revision_id=normalized_revision_id,
        )
    except ElectricalShadingContractError as exc:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_MODULE_CAPABILITY_EVIDENCE_INVALID",
                "severity": "warning",
                "message": str(exc),
            }
        )
        return ResolvedModuleCapabilitySnapshot(
            module_revision_id=normalized_revision_id,
            resolution_id=(
                str(evidence.get("resolution_id"))
                if evidence.get("resolution_id") is not None
                else None
            ),
            detailed_sdm_ready=False,
            findings=tuple(findings),
        )

    return ResolvedModuleCapabilitySnapshot(
        module_revision_id=normalized_revision_id,
        resolution_id=str(evidence.get("resolution_id")),
        detailed_sdm_ready=True,
    )


def validate_topology_for_electrical_shading(
    module_definition: Mapping[str, Any],
    topology_definition: Mapping[str, Any] | None,
) -> TopologyValidationResult:
    """Validate topology/trust/geometry upstream of pure fidelity derivation."""
    findings: list[dict[str, Any]] = []
    module_revision_id = module_definition.get("revision_id")
    normalized_module_revision_id = (
        str(module_revision_id)
        if isinstance(module_revision_id, str) and module_revision_id
        else None
    )

    if topology_definition is None:
        return TopologyValidationResult(
            topology_present=False,
            topology_revision_id=None,
            module_revision_id=normalized_module_revision_id,
            topology_structurally_valid=False,
            topology_trusted=False,
            region_geometry_execution_ready=False,
            bypass_coverage_complete=False,
            region_resolution=None,
        )

    topology_revision_id = topology_definition.get("revision_id")
    normalized_topology_revision_id = (
        str(topology_revision_id)
        if isinstance(topology_revision_id, str) and topology_revision_id
        else None
    )

    structurally_valid = False
    try:
        assert_module_topology_definition(topology_definition)
        structurally_valid = True
    except ElectricalShadingContractError as exc:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_TOPOLOGY_INVALID",
                "severity": "warning",
                "message": str(exc),
            }
        )

    trusted = False
    if structurally_valid:
        exact_module = (
            topology_definition.get("module_definition_revision_id")
            == module_revision_id
        )
        if not exact_module:
            findings.append(
                {
                    "code": "ELECTRICAL_SHADING_TOPOLOGY_MODULE_REVISION_MISMATCH",
                    "severity": "warning",
                    "message": (
                        "Module topology must reference the exact selected "
                        "ModuleDefinition revision."
                    ),
                }
            )
        verification = topology_definition.get("verification_state")
        provenance = topology_definition.get("topology_provenance")
        trusted_state = verification in _TRUSTED_TOPOLOGY_STATES
        trusted_provenance = provenance in _TRUSTED_TOPOLOGY_PROVENANCE
        if not trusted_state:
            findings.append(
                {
                    "code": "ELECTRICAL_SHADING_TOPOLOGY_NOT_VERIFIED",
                    "severity": "info",
                    "message": (
                        "Detailed topology exists but has not reached a trusted "
                        "verification state."
                    ),
                }
            )
        if not trusted_provenance:
            findings.append(
                {
                    "code": "ELECTRICAL_SHADING_TOPOLOGY_PROVENANCE_UNTRUSTED",
                    "severity": "info",
                    "message": (
                        "Detailed topology cannot be enabled from inferred or "
                        "unresolved wiring semantics."
                    ),
                }
            )
        trusted = exact_module and trusted_state and trusted_provenance

    geometry_ready = resolve_region_geometry_execution_readiness(
        topology_definition,
        topology_structurally_valid=structurally_valid,
        findings=findings,
    )

    return TopologyValidationResult(
        topology_present=True,
        topology_revision_id=normalized_topology_revision_id,
        module_revision_id=normalized_module_revision_id,
        topology_structurally_valid=structurally_valid,
        topology_trusted=trusted,
        region_geometry_execution_ready=geometry_ready,
        bypass_coverage_complete=(
            structurally_valid
            and topology_definition.get("bypass_coverage_complete") is True
        ),
        region_resolution=(
            str(topology_definition.get("region_resolution"))
            if topology_definition.get("region_resolution") is not None
            else None
        ),
        findings=tuple(findings),
    )


def resolve_bypass_model_evidence(
    topology_definition: Mapping[str, Any] | None,
    topology_validation_result: TopologyValidationResult,
) -> BypassModelEvidence:
    """Classify bypass readiness upstream of pure fidelity derivation."""
    findings: list[dict[str, Any]] = []
    ready, mode, assumption_ids = _resolve_bypass_model_readiness(
        topology_definition,
        topology_valid=topology_validation_result.topology_structurally_valid,
        findings=findings,
    )
    return BypassModelEvidence(
        topology_revision_id=topology_validation_result.topology_revision_id,
        bypass_models_ready=ready,
        readiness_mode=mode,
        assumption_ids=tuple(assumption_ids),
        findings=tuple(findings),
    )


def resolve_electrical_shading_capability(
    module_capability_snapshot: ResolvedModuleCapabilitySnapshot,
    topology_validation_result: TopologyValidationResult | None = None,
    *,
    bypass_model_evidence: BypassModelEvidence | None = None,
    region_parameterization_evidence: ValidatedParameterizationEvidence | None = None,
    cell_parameterization_evidence: ValidatedParameterizationEvidence | None = None,
) -> dict[str, Any]:
    """Purely derive fidelity from already validated upstream evidence.

    This function performs no component/source verification, topology validation,
    polygon computation, bypass-model validation, or parameterization validation.
    Its inputs are immutable-style validation results produced by the dedicated
    upstream contract helpers.
    """
    topology = topology_validation_result or TopologyValidationResult(
        topology_present=False,
        topology_revision_id=None,
        module_revision_id=module_capability_snapshot.module_revision_id,
        topology_structurally_valid=False,
        topology_trusted=False,
        region_geometry_execution_ready=False,
        bypass_coverage_complete=False,
        region_resolution=None,
    )
    bypass = bypass_model_evidence or BypassModelEvidence(
        topology_revision_id=topology.topology_revision_id,
        bypass_models_ready=False,
        readiness_mode=None,
    )
    region_parameterization = region_parameterization_evidence or (
        ValidatedParameterizationEvidence(
            parameterization_scope="region_substring",
            ready=False,
            evidence_id=None,
            module_revision_id=module_capability_snapshot.module_revision_id,
            topology_revision_id=topology.topology_revision_id,
        )
    )
    cell_parameterization = cell_parameterization_evidence or (
        ValidatedParameterizationEvidence(
            parameterization_scope="cell",
            ready=False,
            evidence_id=None,
            module_revision_id=module_capability_snapshot.module_revision_id,
            topology_revision_id=topology.topology_revision_id,
        )
    )

    findings: list[dict[str, Any]] = [
        *module_capability_snapshot.findings,
        *topology.findings,
        *bypass.findings,
        *region_parameterization.findings,
        *cell_parameterization.findings,
    ]
    available = ["level_0_geometric_only"]

    topology_binding_ready = (
        not topology.topology_present
        or topology.module_revision_id == module_capability_snapshot.module_revision_id
    )
    bypass_binding_ready = (
        not topology.topology_present
        or bypass.topology_revision_id == topology.topology_revision_id
    )
    region_parameterization_binding_ready = (
        not region_parameterization.ready
        or (
            region_parameterization.module_revision_id
            == module_capability_snapshot.module_revision_id
            and region_parameterization.topology_revision_id
            == topology.topology_revision_id
        )
    )
    cell_parameterization_binding_ready = (
        not cell_parameterization.ready
        or (
            cell_parameterization.module_revision_id
            == module_capability_snapshot.module_revision_id
            and cell_parameterization.topology_revision_id
            == topology.topology_revision_id
        )
    )

    if not topology_binding_ready:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_VALIDATED_TOPOLOGY_BINDING_MISMATCH",
                "severity": "warning",
                "message": (
                    "Validated topology result is bound to a different module "
                    "revision than the resolved module capability snapshot."
                ),
            }
        )
    if not bypass_binding_ready:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_VALIDATED_BYPASS_BINDING_MISMATCH",
                "severity": "warning",
                "message": (
                    "Validated bypass-model evidence is bound to a different "
                    "topology revision than the topology validation result."
                ),
            }
        )
    if not region_parameterization_binding_ready:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_VALIDATED_REGION_PARAMETERIZATION_BINDING_MISMATCH",
                "severity": "warning",
                "message": (
                    "Validated region parameterization evidence does not match "
                    "the selected module/topology validation results."
                ),
            }
        )
    if not cell_parameterization_binding_ready:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_VALIDATED_CELL_PARAMETERIZATION_BINDING_MISMATCH",
                "severity": "warning",
                "message": (
                    "Validated cell parameterization evidence does not match "
                    "the selected module/topology validation results."
                ),
            }
        )

    detailed_sdm_ready = module_capability_snapshot.detailed_sdm_ready
    if detailed_sdm_ready:
        available.append("level_1_module_approximation")

    topology_level2_prerequisites = (
        detailed_sdm_ready
        and topology_binding_ready
        and bypass_binding_ready
        and topology.topology_structurally_valid
        and topology.topology_trusted
        and topology.region_geometry_execution_ready
        and topology.bypass_coverage_complete
    )
    if topology_level2_prerequisites and not bypass.bypass_models_ready:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_BYPASS_MODEL_REQUIRED",
                "severity": "info",
                "message": (
                    "Level 2 requires every bypass device to have either a "
                    "validated component model or an explicitly recorded simulation "
                    "assumption. Structural model presence alone is insufficient."
                ),
            }
        )

    level2_physics_prerequisites = (
        topology_level2_prerequisites and bypass.bypass_models_ready
    )
    if level2_physics_prerequisites and not region_parameterization.ready:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_LEVEL2_PARAMETERIZATION_REQUIRED",
                "severity": "info",
                "message": (
                    "Level 2 requires revision-bound validated region/sub-string "
                    "electrical parameterization evidence; module-level SDM "
                    "parameters are not silently divided or scaled into substring "
                    "parameters."
                ),
            }
        )

    level2_ready = (
        level2_physics_prerequisites
        and region_parameterization.ready
        and region_parameterization_binding_ready
    )
    if level2_ready:
        available.append("level_2_bypass_substring")

    level3_ready = (
        level2_ready
        and topology.region_resolution in {"cell", "half_cell"}
        and cell_parameterization.ready
        and cell_parameterization_binding_ready
    )
    if level3_ready:
        available.append("level_3_cell_submodule_iv")
    elif level2_ready:
        findings.append(
            {
                "code": "ELECTRICAL_SHADING_LEVEL3_PARAMETERIZATION_REQUIRED",
                "severity": "info",
                "message": (
                    "Level 3 requires cell/half-cell topology plus revision-bound "
                    "validated cell-level electrical parameterization evidence."
                ),
            }
        )

    return {
        "contract_version": ELECTRICAL_SHADING_CONTRACT_VERSION,
        "available_fidelity_levels": available,
        "maximum_fidelity_level": available[-1],
        "detailed_sdm_ready": detailed_sdm_ready,
        "module_capability_resolution_id": module_capability_snapshot.resolution_id,
        "topology_present": topology.topology_present,
        "topology_valid": topology.topology_structurally_valid,
        "topology_structurally_valid": topology.topology_structurally_valid,
        "region_geometry_execution_ready": topology.region_geometry_execution_ready,
        "topology_trusted": topology.topology_trusted,
        "bypass_models_ready": bypass.bypass_models_ready,
        "bypass_model_readiness_mode": bypass.readiness_mode,
        "bypass_assumption_ids": list(bypass.assumption_ids),
        "region_parameterization_ready": region_parameterization.ready,
        "cell_parameterization_ready": cell_parameterization.ready,
        "region_parameterization_evidence_id": (
            region_parameterization.evidence_id
            if region_parameterization.ready
            else None
        ),
        "cell_parameterization_evidence_id": (
            cell_parameterization.evidence_id
            if cell_parameterization.ready
            else None
        ),
        "findings": findings,
    }


def _represented_power_local_extrema(
    points: Sequence[tuple[float, float, float]],
    *,
    power_tolerance_w: float,
) -> tuple[tuple[float, float, float], ...]:
    """Return sampled local power maxima using only represented discrete points."""
    extrema: list[tuple[float, float, float]] = []
    for index, point in enumerate(points):
        power = point[2]
        left_power = points[index - 1][2] if index > 0 else None
        right_power = points[index + 1][2] if index + 1 < len(points) else None

        left_ok = left_power is None or power >= left_power - power_tolerance_w
        right_ok = right_power is None or power >= right_power - power_tolerance_w
        if left_ok and right_ok:
            extrema.append(point)
    return tuple(extrema)


def assert_electrical_iv_curve(curve: Mapping[str, Any]) -> None:
    """Validate frozen Phase-6.1 sampled-IV and MPP declaration semantics.

    Voltage is measured positive from the PV positive terminal to the negative
    terminal. Current is positive when delivered by the PV source. Therefore
    positive P = V * I is generated electrical power. Negative voltage/power
    remains representable for reverse-biased submodule states.

    global_mpp and local_mpp_candidates are solver-declared metadata. This
    validator independently checks only what the stored sampled curve supports.
    It does not prove continuous-curve optimality unless the solver explicitly
    records such a guarantee.
    """
    if curve.get("schema_name") != "ElectricalIVCurve":
        raise ElectricalShadingContractError(
            "schema_name must be 'ElectricalIVCurve'"
        )
    if curve.get("schema_version") != "0.1":
        raise ElectricalShadingContractError(
            "ElectricalIVCurve schema_version must be '0.1'"
        )
    if curve.get("contract_version") != ELECTRICAL_SHADING_CONTRACT_VERSION:
        raise ElectricalShadingContractError(
            "ElectricalIVCurve contract_version must be '0.1'"
        )
    if curve.get("representation") != "sampled_voltage_grid":
        raise ElectricalShadingContractError(
            "ElectricalIVCurve representation must be sampled_voltage_grid"
        )
    if curve.get("sample_order") != "ascending_voltage":
        raise ElectricalShadingContractError(
            "ElectricalIVCurve sample_order must be ascending_voltage"
        )
    if curve.get("sign_convention") != "pv_delivery_current_positive_power_equals_v_times_i":
        raise ElectricalShadingContractError(
            "ElectricalIVCurve sign_convention does not match Phase-6.1"
        )

    semantics = curve.get("mpp_semantics")
    if not isinstance(semantics, Mapping):
        raise ElectricalShadingContractError("mpp_semantics must be explicit")
    if semantics.get("declaration_authority") != "solver_declared":
        raise ElectricalShadingContractError(
            "MPP declaration_authority must be solver_declared"
        )
    if semantics.get("sample_verification_scope") != "represented_samples_only":
        raise ElectricalShadingContractError(
            "MPP sample_verification_scope must be represented_samples_only"
        )
    voltage_tolerance = _finite_number(
        semantics.get("voltage_tolerance_v"),
        "mpp_semantics.voltage_tolerance_v",
    )
    power_tolerance = _finite_number(
        semantics.get("power_tolerance_w"),
        "mpp_semantics.power_tolerance_w",
    )
    if voltage_tolerance < 0.0 or power_tolerance < 0.0:
        raise ElectricalShadingContractError(
            "MPP verification tolerances must be non-negative"
        )

    continuous_guarantee = semantics.get("continuous_curve_guarantee")
    guarantee_basis = semantics.get("continuous_curve_guarantee_basis")
    if continuous_guarantee == "none":
        if guarantee_basis is not None:
            raise ElectricalShadingContractError(
                "continuous_curve_guarantee_basis must be null when no continuous guarantee is claimed"
            )
    elif continuous_guarantee == "solver_guaranteed":
        if not isinstance(guarantee_basis, str) or not guarantee_basis:
            raise ElectricalShadingContractError(
                "solver_guaranteed continuous MPP requires an explicit guarantee basis"
            )
    else:
        raise ElectricalShadingContractError(
            "continuous_curve_guarantee must be 'none' or 'solver_guaranteed'"
        )

    raw_points = curve.get("points")
    if not isinstance(raw_points, list) or len(raw_points) < 2:
        raise ElectricalShadingContractError(
            "ElectricalIVCurve requires at least two sampled points"
        )

    represented_points: list[tuple[float, float, float]] = []
    previous_voltage: float | None = None
    for index, point in enumerate(raw_points):
        if not isinstance(point, Mapping):
            raise ElectricalShadingContractError(
                f"IV point {index} must be an object"
            )
        voltage = _finite_number(point.get("voltage_v"), f"IV point {index}.voltage_v")
        current = _finite_number(point.get("current_a"), f"IV point {index}.current_a")
        power = _finite_number(point.get("power_w"), f"IV point {index}.power_w")
        if previous_voltage is not None and voltage <= previous_voltage:
            raise ElectricalShadingContractError(
                "ElectricalIVCurve voltages must be strictly increasing"
            )
        previous_voltage = voltage
        expected_power = voltage * current
        point_power_tolerance = max(
            1e-9,
            1e-9 * max(abs(expected_power), abs(power), 1.0),
        )
        if abs(power - expected_power) > point_power_tolerance:
            raise ElectricalShadingContractError(
                f"IV point {index} power_w must equal voltage_v * current_a"
            )
        represented_points.append((voltage, current, power))

    isc = _finite_number(curve.get("isc_a"), "isc_a")
    voc = _finite_number(curve.get("voc_v"), "voc_v")
    if isc < 0.0:
        raise ElectricalShadingContractError("isc_a must be non-negative")
    if voc < 0.0:
        raise ElectricalShadingContractError("voc_v must be non-negative")

    global_point = curve.get("global_mpp")
    if not isinstance(global_point, Mapping):
        raise ElectricalShadingContractError("global_mpp must be explicit")
    global_voltage = _finite_number(
        global_point.get("voltage_v"),
        "global_mpp.voltage_v",
    )
    global_current = _finite_number(
        global_point.get("current_a"),
        "global_mpp.current_a",
    )
    global_power = _finite_number(
        global_point.get("power_w"),
        "global_mpp.power_w",
    )
    global_power_identity_tolerance = max(
        1e-9,
        1e-9 * max(abs(global_voltage * global_current), abs(global_power), 1.0),
    )
    if abs(global_power - global_voltage * global_current) > global_power_identity_tolerance:
        raise ElectricalShadingContractError(
            "global_mpp.power_w must equal voltage_v * current_a"
        )

    sampled_min_voltage = represented_points[0][0]
    sampled_max_voltage = represented_points[-1][0]
    if (
        global_voltage < sampled_min_voltage - voltage_tolerance
        or global_voltage > sampled_max_voltage + voltage_tolerance
    ):
        raise ElectricalShadingContractError(
            "solver-declared global_mpp voltage lies outside the represented sampled voltage domain"
        )

    represented_max_power = max(point[2] for point in represented_points)
    if global_power < represented_max_power - power_tolerance:
        raise ElectricalShadingContractError(
            "solver-declared global_mpp power is below a represented sampled-curve power maximum"
        )

    candidates = curve.get("local_mpp_candidates")
    if not isinstance(candidates, list):
        raise ElectricalShadingContractError(
            "local_mpp_candidates must be an array"
        )

    represented_extrema = _represented_power_local_extrema(
        represented_points,
        power_tolerance_w=power_tolerance,
    )
    declared_candidate_powers: list[float] = []
    for index, point in enumerate(candidates):
        if not isinstance(point, Mapping):
            raise ElectricalShadingContractError(
                f"local_mpp_candidates[{index}] must be an object"
            )
        voltage = _finite_number(
            point.get("voltage_v"),
            f"local_mpp_candidates[{index}].voltage_v",
        )
        current = _finite_number(
            point.get("current_a"),
            f"local_mpp_candidates[{index}].current_a",
        )
        power = _finite_number(
            point.get("power_w"),
            f"local_mpp_candidates[{index}].power_w",
        )
        identity_tolerance = max(
            1e-9,
            1e-9 * max(abs(voltage * current), abs(power), 1.0),
        )
        if abs(power - voltage * current) > identity_tolerance:
            raise ElectricalShadingContractError(
                f"local_mpp_candidates[{index}].power_w must equal voltage_v * current_a"
            )
        if (
            voltage < sampled_min_voltage - voltage_tolerance
            or voltage > sampled_max_voltage + voltage_tolerance
        ):
            raise ElectricalShadingContractError(
                f"local_mpp_candidates[{index}] lies outside the represented sampled voltage domain"
            )

        matches_represented_extremum = any(
            abs(voltage - sample_voltage) <= voltage_tolerance
            and abs(power - sample_power) <= power_tolerance
            for sample_voltage, _sample_current, sample_power in represented_extrema
        )
        if not matches_represented_extremum:
            raise ElectricalShadingContractError(
                f"local_mpp_candidates[{index}] does not correspond to a represented sampled-curve local power extremum within declared tolerances"
            )
        declared_candidate_powers.append(power)

    if declared_candidate_powers:
        strongest_declared_candidate = max(declared_candidate_powers)
        if global_power < strongest_declared_candidate - power_tolerance:
            raise ElectricalShadingContractError(
                "solver-declared global_mpp power is below a declared local-MPP candidate"
            )


def assert_requested_fidelity_available(
    requested_fidelity: str,
    capability: Mapping[str, Any],
    *,
    fallback_policy: str = "fail_closed",
) -> str:
    """Return the requested fidelity or fail; no silent fallback is permitted."""
    if requested_fidelity not in FIDELITY_ORDER:
        raise ElectricalShadingContractError(
            f"unknown electrical-shading fidelity: {requested_fidelity}"
        )

    available = list(capability.get("available_fidelity_levels") or [])
    if requested_fidelity in available:
        return requested_fidelity

    if fallback_policy == "fail_closed":
        raise ElectricalShadingContractError(
            f"requested fidelity {requested_fidelity} is not available; "
            f"maximum available is {capability.get('maximum_fidelity_level')}"
        )

    if fallback_policy != "explicit_lower_fidelity":
        raise ElectricalShadingContractError(
            "fallback_policy must be 'fail_closed' or 'explicit_lower_fidelity'"
        )

    # This policy is only valid when a caller deliberately opts in and records
    # the fallback in the run/model manifest. It never happens implicitly.
    requested_order = FIDELITY_ORDER[requested_fidelity]
    candidates = [
        level
        for level in available
        if FIDELITY_ORDER.get(level, -1) < requested_order
    ]
    if not candidates:
        raise ElectricalShadingContractError(
            f"no lower electrical-shading fidelity is available for {requested_fidelity}"
        )
    return max(candidates, key=lambda level: FIDELITY_ORDER[level])


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def electrical_shading_scientific_identity_payload(
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """Return only material scientific choices from the Phase-6 configuration.

    Execution/storage/cache/parallelization options are intentionally excluded.
    """
    required = (
        "contract_version",
        "requested_fidelity",
        "fallback_policy",
        "thermal_state_scope",
        "loss_accounting_boundary",
        "model_selections",
        "scientific_options",
    )
    missing = [field for field in required if field not in configuration]
    if missing:
        raise ElectricalShadingContractError(
            "electrical-shading scientific identity missing fields: "
            + ", ".join(missing)
        )
    return {field: configuration[field] for field in required}


def electrical_shading_scientific_sha256(
    configuration: Mapping[str, Any],
) -> str:
    """Hash the physical/scientific electrical-shading configuration."""
    return _canonical_sha256(
        electrical_shading_scientific_identity_payload(configuration)
    )


def electrical_shading_execution_sha256(
    configuration: Mapping[str, Any],
) -> str:
    """Hash scientific identity plus non-scientific execution choices."""
    payload = {
        "scientific": electrical_shading_scientific_identity_payload(
            configuration
        ),
        "execution_options": dict(configuration.get("execution_options") or {}),
    }
    return _canonical_sha256(payload)
