"""Phase-6.4 Level-1 module electrical-shading approximation.

Level 1 produces one validated whole-module electrical state per module. Spatial
nonuniformity inside a module is not electrically solved: there is no substring IV,
bypass state, nonuniform module-IV assembly, string-IV aggregation, or MPPT model here.

Two equivalent-irradiance adapters are provided:

1. direct module receiver: topology-independent and therefore the canonical Level-1
   path when only a validated whole-module SDM is available;
2. area-weighted regional collapse: optional adapter over Phase-6.3 local irradiance
   when an explicit ElectricalRegionMap covers the complete module receiver.

Both routes preserve the Phase-6 ordering:

    unshaded channel -> geometric visibility -> optical modifier -> electrical input

and both book geometric irradiance upstream rather than as electrical mismatch loss.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

import pandas as pd

from engine.module import (
    MODULE_PVSYST_SDM,
    calculate_pvsyst_module_electrical,
    extract_validated_pvsyst_parameter_set,
)
from engine.optical import OpticalResult
from engine.thermal import ThermalResult
from geometry.shading.beam import (
    BEAM_SOLVER_ID,
    BEAM_SOLVER_VERSION,
    calculate_direct_beam_shadow,
)
from geometry.shading.ground import (
    GROUND_VISIBILITY_SOLVER_ID,
    GROUND_VISIBILITY_SOLVER_VERSION,
    GroundDomeResolution,
    calculate_ground_visibility,
)
from geometry.shading.sky import (
    SKY_VISIBILITY_SOLVER_ID,
    SKY_VISIBILITY_SOLVER_VERSION,
    SkyDomeResolution,
    calculate_sky_visibility,
)

from .contract import (
    ELECTRICAL_SHADING_CONTRACT_VERSION,
    THERMAL_STATE_SCOPE,
    assert_requested_fidelity_available,
    electrical_shading_execution_sha256,
    electrical_shading_scientific_sha256,
    resolve_electrical_shading_capability,
    resolve_module_capability_snapshot,
)


LEVEL1_MODULE_SOLVER_ID = "opensimpv.electrical_shading.level1.module_equivalent_sdm"
LEVEL1_MODULE_SOLVER_VERSION = "0.1"
MODULE_VISIBILITY_ORCHESTRATOR_ID = "opensimpv.module_visibility_snapshot"
MODULE_VISIBILITY_ORCHESTRATOR_VERSION = "0.1"
MODULE_RECEIVER_EQUIVALENT_METHOD = (
    "module_receiver_channel_visibility_uniform_equivalent"
)
REGIONAL_EQUIVALENT_METHOD = (
    "area_weighted_complete_region_collapse_uniform_equivalent"
)
IRRADIANCE_MAPPING_ORDER = (
    "unshaded_poa_by_channel_then_geometry_visibility_then_optical_treatment"
)
LOSS_ACCOUNTING_BOUNDARY = "geometry_then_electrical_mismatch_then_mppt"
ATTRIBUTION_DELTA_CONVENTION = "reference_minus_evaluated_positive_is_loss"

_CHANNELS = ("beam_w_m2", "sky_diffuse_w_m2", "ground_reflected_w_m2")
_OPTICAL_KEYS = {
    "beam_w_m2": "beam",
    "sky_diffuse_w_m2": "sky_diffuse",
    "ground_reflected_w_m2": "ground_reflected",
}


class Level1ModuleApproximationError(ValueError):
    """Raised when the Level-1 approximation cannot be executed defensibly."""


@dataclass(frozen=True)
class Level1ModuleApproximationResult:
    module_state: dict[str, Any]
    electrical_shading_result: dict[str, Any]


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256(value: Any, *, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise Level1ModuleApproximationError(f"{label} must be a lowercase SHA-256")
    return text


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Level1ModuleApproximationError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise Level1ModuleApproximationError(f"{label} must be finite")
    return number


def _fraction(value: Any, *, label: str) -> float:
    number = _finite(value, label=label)
    if not 0.0 <= number <= 1.0:
        raise Level1ModuleApproximationError(f"{label} must lie within [0, 1]")
    return number


def _canonical_time(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Level1ModuleApproximationError(f"{label} must be a non-empty ISO-8601 string")
    text = value.strip()
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise Level1ModuleApproximationError(f"{label} must be valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Level1ModuleApproximationError(f"{label} must include a timezone offset")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _three_channels(value: Mapping[str, Any], *, label: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for field in _CHANNELS:
        number = _finite(value.get(field), label=f"{label}.{field}")
        if number < 0.0:
            raise Level1ModuleApproximationError(f"{label}.{field} must be non-negative")
        result[field] = number
    return result


def _optical_modifiers(value: Mapping[str, Any]) -> dict[str, float]:
    return {
        key: _fraction(value.get(key), label=f"optical_modifier.{key}")
        for key in ("beam", "sky_diffuse", "ground_reflected")
    }


def _optical_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    model_id = value.get("model_id")
    model_version = value.get("model_version")
    if not isinstance(model_id, str) or not model_id:
        raise Level1ModuleApproximationError("optical_model_manifest.model_id is required")
    if not isinstance(model_version, str) or not model_version:
        raise Level1ModuleApproximationError(
            "optical_model_manifest.model_version is required"
        )
    return deepcopy(dict(value))


def _normalized_sun_vector(value: Sequence[float]) -> list[float]:
    if len(value) != 3:
        raise Level1ModuleApproximationError("sun_vector_xyz must contain three values")
    vector = [_finite(item, label="sun_vector_xyz") for item in value]
    norm = math.sqrt(sum(item * item for item in vector))
    if norm <= 0.0:
        raise Level1ModuleApproximationError("sun_vector_xyz must be non-zero")
    return [item / norm for item in vector]


def _module_receiver(
    compiled_geometry: Mapping[str, Any],
    module_instance_id: str,
) -> Mapping[str, Any]:
    matches = [
        receiver
        for receiver in compiled_geometry.get("receivers") or []
        if receiver.get("source_entity_type") == "module_instance"
        and str(receiver.get("source_entity_id") or "") == str(module_instance_id)
    ]
    if len(matches) != 1:
        raise Level1ModuleApproximationError(
            "compiled geometry must contain exactly one receiver for the module instance"
        )
    receiver = matches[0]
    if receiver.get("receiver_type") != "module_plane":
        raise Level1ModuleApproximationError("Level 1 requires a module_plane receiver")
    if receiver.get("enabled") is not True:
        raise Level1ModuleApproximationError("module receiver is disabled")
    return receiver


def evaluate_module_receiver_visibility(
    compiled_geometry: Mapping[str, Any],
    *,
    module_instance_id: str,
    sun_vector_xyz: Sequence[float],
    self_shading_enabled: bool,
    sky_resolution: SkyDomeResolution,
    ground_resolution: GroundDomeResolution,
    timestamp: str | None = None,
    fidelity_level: str = "engineering",
) -> dict[str, Any]:
    """Create one canonical geometry-only ShadingResult for a module receiver."""
    if not isinstance(self_shading_enabled, bool):
        raise Level1ModuleApproximationError("self_shading_enabled must be explicit boolean")
    if fidelity_level not in {"preview", "fast", "engineering", "detailed", "research"}:
        raise Level1ModuleApproximationError("unsupported geometric fidelity_level")
    geometry_hash = _sha256(
        compiled_geometry.get("geometry_payload_sha256"),
        label="compiled geometry hash",
    )
    receiver = _module_receiver(compiled_geometry, module_instance_id)
    receiver_id = str(receiver["receiver_id"])
    sun_vector = _normalized_sun_vector(sun_vector_xyz)
    utc_timestamp = None if timestamp is None else _canonical_time(timestamp, label="timestamp")

    beam = calculate_direct_beam_shadow(
        compiled_geometry,
        receiver_id=receiver_id,
        sun_vector_xyz=sun_vector,
        self_shading_enabled=self_shading_enabled,
    )
    sky = calculate_sky_visibility(
        compiled_geometry,
        receiver_id=receiver_id,
        self_shading_enabled=self_shading_enabled,
        resolution=sky_resolution,
    )
    ground = calculate_ground_visibility(
        compiled_geometry,
        receiver_id=receiver_id,
        self_shading_enabled=self_shading_enabled,
        resolution=ground_resolution,
    )
    flags: list[str] = []
    if beam.get("status") != "evaluated":
        flags.append(str(beam.get("status")))
    if sky.get("has_front_sky_view") is False:
        flags.append("no_front_sky_view")
    if ground.get("has_front_ground_view") is False:
        flags.append("no_front_ground_view")

    record = {
        "receiver_id": receiver_id,
        "timestamp": utc_timestamp,
        "sun_vector_xyz": deepcopy(sun_vector),
        "beam_visibility_factor": float(beam["beam_visibility_factor"]),
        "sky_visibility_factor": float(sky["sky_visibility_factor"]),
        "ground_visibility_factor": float(ground["ground_visibility_factor"]),
        "quality_flags": sorted(set(flags)),
    }
    config_payload = {
        "self_shading_enabled": self_shading_enabled,
        "fidelity_level": fidelity_level,
        "sky_dome_resolution": sky_resolution.as_dict(),
        "ground_dome_resolution": ground_resolution.as_dict(),
        "module_instance_id": str(module_instance_id),
    }
    config_hash = _canonical_sha256(config_payload)
    physical_payload = {
        "compiled_geometry_hash": geometry_hash,
        "receiver_id": receiver_id,
        "sun_vector_xyz": sun_vector,
        "timestamp": utc_timestamp,
        "record": record,
        "solver_ids": [
            [BEAM_SOLVER_ID, BEAM_SOLVER_VERSION],
            [SKY_VISIBILITY_SOLVER_ID, SKY_VISIBILITY_SOLVER_VERSION],
            [GROUND_VISIBILITY_SOLVER_ID, GROUND_VISIBILITY_SOLVER_VERSION],
        ],
        "configuration": config_payload,
    }
    physical_hash = _canonical_sha256(physical_payload)
    return {
        "schema_name": "ShadingResult",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "shading_result_id": f"shading:module:{module_instance_id}:{physical_hash[:16]}",
        "source_scene_revision_id": str(compiled_geometry["source_scene_revision_id"]),
        "compiled_geometry_hash": geometry_hash,
        "shading_configuration_hash": config_hash,
        "scientific_shading_configuration_sha256": config_hash,
        "solver_manifest": {
            "beam": {
                "model_id": BEAM_SOLVER_ID,
                "model_version": BEAM_SOLVER_VERSION,
                "resolution": {"geometry": "exact_polygon_projection"},
            },
            "sky_diffuse": {
                "model_id": SKY_VISIBILITY_SOLVER_ID,
                "model_version": SKY_VISIBILITY_SOLVER_VERSION,
                "resolution": sky_resolution.as_dict(),
            },
            "ground": {
                "model_id": GROUND_VISIBILITY_SOLVER_ID,
                "model_version": GROUND_VISIBILITY_SOLVER_VERSION,
                "resolution": ground_resolution.as_dict(),
            },
        },
        "fidelity_level": fidelity_level,
        "receiver_granularity": "module",
        "factor_convention": "visibility_one_clear_zero_blocked",
        "electrical_shading_scope": "not_modeled",
        "channels": ["beam_visibility", "sky_visibility", "ground_visibility"],
        "storage_mode": "inline",
        "record_count": 1,
        "inline_records": [record],
        "orchestrator_manifest": {
            "orchestrator_id": MODULE_VISIBILITY_ORCHESTRATOR_ID,
            "orchestrator_version": MODULE_VISIBILITY_ORCHESTRATOR_VERSION,
        },
        "receiver_set_sha256": _canonical_sha256([receiver_id]),
        "sun_state_sha256": _canonical_sha256(
            {"sun_vector_xyz": sun_vector, "timestamp": utc_timestamp}
        ),
        "source_execution_plan_id": None,
        "result_payload_sha256": physical_hash,
        "physical_result_sha256": physical_hash,
        "approximation_manifest": [],
        "findings": [],
    }


def build_module_equivalent_irradiance_from_module_shading(
    module_shading_result: Mapping[str, Any],
    *,
    module_instance_id: str,
    module_definition_revision_id: str,
    receiver_id: str,
    unshaded_poa: Mapping[str, Any],
    optical_modifier: Mapping[str, Any],
    optical_model_manifest: Mapping[str, Any],
    module_temperature_c: float,
    interval_start: str,
    evaluation_time: str,
) -> dict[str, Any]:
    """Build the topology-independent canonical Level-1 module input state."""
    if module_shading_result.get("receiver_granularity") != "module":
        raise Level1ModuleApproximationError(
            "direct Level-1 input requires module receiver granularity"
        )
    if module_shading_result.get("electrical_shading_scope") != "not_modeled":
        raise Level1ModuleApproximationError(
            "source geometric shading must not already include electrical shading"
        )
    shading_hash = _sha256(
        module_shading_result.get("physical_result_sha256"),
        label="source shading physical_result_sha256",
    )
    expected_receiver_id = f"receiver:module:{module_instance_id}"
    if str(receiver_id) != expected_receiver_id:
        raise Level1ModuleApproximationError(
            "module receiver ID does not bind to the requested module instance"
        )
    records = {
        str(record.get("receiver_id") or ""): record
        for record in module_shading_result.get("inline_records") or []
    }
    if set(records) != {str(receiver_id)}:
        raise Level1ModuleApproximationError(
            "module ShadingResult receiver set must exactly match the requested module receiver"
        )
    record = records[str(receiver_id)]
    unshaded = _three_channels(unshaded_poa, label="unshaded_poa")
    optics = _optical_modifiers(optical_modifier)
    optical_manifest = _optical_manifest(optical_model_manifest)
    temperature = _finite(module_temperature_c, label="module_temperature_c")
    interval = _canonical_time(interval_start, label="interval_start")
    evaluation = _canonical_time(evaluation_time, label="evaluation_time")

    visibility = {
        "beam": _fraction(record.get("beam_visibility_factor"), label="beam_visibility_factor"),
        "sky_diffuse": _fraction(record.get("sky_visibility_factor"), label="sky_visibility_factor"),
        "ground": _fraction(record.get("ground_visibility_factor"), label="ground_visibility_factor"),
    }
    post_geometry = {
        "beam_w_m2": unshaded["beam_w_m2"] * visibility["beam"],
        "sky_diffuse_w_m2": unshaded["sky_diffuse_w_m2"] * visibility["sky_diffuse"],
        "ground_reflected_w_m2": unshaded["ground_reflected_w_m2"] * visibility["ground"],
    }
    post_optical = {
        channel: post_geometry[channel] * optics[_OPTICAL_KEYS[channel]]
        for channel in _CHANNELS
    }
    equivalent = {
        "aggregation_method": MODULE_RECEIVER_EQUIVALENT_METHOD,
        "source_scene_revision_id": str(module_shading_result["source_scene_revision_id"]),
        "source_module_instance_id": str(module_instance_id),
        "source_module_definition_revision_id": str(module_definition_revision_id),
        "source_receiver_id": str(receiver_id),
        "source_shading_result_id": str(module_shading_result["shading_result_id"]),
        "source_shading_physical_result_hash": shading_hash,
        "source_local_irradiance_state_id": None,
        "source_local_irradiance_state_hash": None,
        "source_electrical_region_map_id": None,
        "source_electrical_region_map_hash": None,
        "source_module_topology_revision_id": None,
        "mapped_region_area_fraction": None,
        "interval_start": interval,
        "evaluation_time": evaluation,
        "irradiance_mapping_order": IRRADIANCE_MAPPING_ORDER,
        "thermal_state_scope": THERMAL_STATE_SCOPE,
        "module_temperature_c": temperature,
        "unshaded_poa": unshaded,
        "post_geometry_poa": post_geometry,
        "optical_modifier": optics,
        "post_optical_poa": post_optical,
        "equivalent_incident_poa_global_w_m2": float(sum(post_geometry.values())),
        "equivalent_effective_irradiance_w_m2": float(sum(post_optical.values())),
        "optical_model_manifest": optical_manifest,
        "quality_flags": sorted(set(record.get("quality_flags") or [])),
    }
    equivalent["equivalent_state_sha256"] = _canonical_sha256(equivalent)
    return equivalent


def collapse_local_irradiance_to_module_equivalent(
    region_map: Mapping[str, Any],
    local_state: Mapping[str, Any],
    *,
    complete_coverage_tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Collapse a complete Phase-6.3 regional state into one Level-1 module state.

    This adapter is optional. Level 1 itself does not require topology. Incomplete
    region coverage fails closed because an area-weighted whole-module equivalent
    cannot be reconstructed defensibly from unknown/missing receiver area.
    """
    tolerance = _finite(
        complete_coverage_tolerance,
        label="complete_coverage_tolerance",
    )
    if tolerance < 0.0:
        raise Level1ModuleApproximationError(
            "complete_coverage_tolerance must be non-negative"
        )
    map_id = str(region_map.get("electrical_region_map_id") or "")
    map_hash = _sha256(region_map.get("mapping_payload_sha256"), label="region map hash")
    if str(local_state.get("source_electrical_region_map_id") or "") != map_id:
        raise Level1ModuleApproximationError("local state and region map ID mismatch")
    if str(local_state.get("source_electrical_region_map_hash") or "") != map_hash:
        raise Level1ModuleApproximationError("local state and region map hash mismatch")
    if str(local_state.get("source_scene_revision_id") or "") != str(
        region_map.get("source_scene_revision_id") or ""
    ):
        raise Level1ModuleApproximationError("local state and region map scene mismatch")
    if str(local_state.get("source_module_instance_id") or "") != str(
        region_map.get("source_module_instance_id") or ""
    ):
        raise Level1ModuleApproximationError("local state and region map module mismatch")
    if str(local_state.get("source_module_definition_revision_id") or "") != str(
        region_map.get("source_module_definition_revision_id") or ""
    ):
        raise Level1ModuleApproximationError(
            "local state and region map ModuleDefinition revision mismatch"
        )
    if local_state.get("irradiance_mapping_order") != IRRADIANCE_MAPPING_ORDER:
        raise Level1ModuleApproximationError(
            "local state irradiance mapping order is not the frozen Phase-6 ordering"
        )
    if local_state.get("thermal_state_scope") != THERMAL_STATE_SCOPE:
        raise Level1ModuleApproximationError(
            "local state thermal scope is not the frozen single-module scope"
        )

    coverage = _finite(
        region_map.get("mapped_region_area_fraction"),
        label="mapped_region_area_fraction",
    )
    if abs(coverage - 1.0) > tolerance:
        raise Level1ModuleApproximationError(
            "regional Level-1 collapse requires complete mapped module area coverage"
        )
    total_area = _finite(region_map.get("mapped_region_area_m2"), label="mapped_region_area_m2")
    if total_area <= 0.0:
        raise Level1ModuleApproximationError("mapped region area must be positive")

    map_regions = {
        str(region["region_id"]): region for region in region_map.get("regions") or []
    }
    state_regions = {
        str(region["region_id"]): region for region in local_state.get("regions") or []
    }
    if set(map_regions) != set(state_regions) or not map_regions:
        raise Level1ModuleApproximationError(
            "local irradiance region set must exactly match the ElectricalRegionMap"
        )

    weighted_post_geometry = {channel: 0.0 for channel in _CHANNELS}
    weighted_post_optical = {channel: 0.0 for channel in _CHANNELS}
    summed_region_area = 0.0
    reference_unshaded: dict[str, float] | None = None
    reference_optics: dict[str, float] | None = None
    quality_flags: set[str] = set(local_state.get("quality_flags") or [])

    for region_id in sorted(map_regions):
        map_region = map_regions[region_id]
        state_region = state_regions[region_id]
        area = _finite(map_region.get("area_m2"), label=f"{region_id}.area_m2")
        if area <= 0.0:
            raise Level1ModuleApproximationError(f"{region_id}.area_m2 must be positive")
        summed_region_area += area
        weight = area / total_area
        unshaded = _three_channels(state_region.get("unshaded_poa") or {}, label=f"{region_id}.unshaded_poa")
        optics = _optical_modifiers(state_region.get("optical_modifier") or {})
        if reference_unshaded is None:
            reference_unshaded = unshaded
        elif unshaded != reference_unshaded:
            raise Level1ModuleApproximationError(
                "regional Level-1 collapse requires one common unshaded POA basis"
            )
        if reference_optics is None:
            reference_optics = optics
        elif optics != reference_optics:
            raise Level1ModuleApproximationError(
                "regional Level-1 collapse requires one common optical modifier basis"
            )
        post_geometry = _three_channels(
            state_region.get("post_geometry_poa") or {},
            label=f"{region_id}.post_geometry_poa",
        )
        post_optical = {
            channel: post_geometry[channel] * optics[_OPTICAL_KEYS[channel]]
            for channel in _CHANNELS
        }
        expected_effective = float(sum(post_optical.values()))
        actual_effective = _finite(
            state_region.get("effective_irradiance_w_m2"),
            label=f"{region_id}.effective_irradiance_w_m2",
        )
        if not math.isclose(actual_effective, expected_effective, rel_tol=1e-12, abs_tol=1e-9):
            raise Level1ModuleApproximationError(
                f"{region_id} effective irradiance does not reconcile with channel state"
            )
        for channel in _CHANNELS:
            weighted_post_geometry[channel] += weight * post_geometry[channel]
            weighted_post_optical[channel] += weight * post_optical[channel]
        quality_flags.update(state_region.get("quality_flags") or [])

    if reference_unshaded is None or reference_optics is None:
        raise Level1ModuleApproximationError("regional Level-1 collapse has no region states")
    area_abs_tol = max(1e-12, tolerance * max(1.0, total_area))
    if not math.isclose(
        summed_region_area, total_area, rel_tol=tolerance, abs_tol=area_abs_tol
    ):
        raise Level1ModuleApproximationError(
            "sum of ElectricalRegionMap region areas does not match mapped_region_area_m2"
        )
    state_hash = _sha256(local_state.get("state_payload_sha256"), label="local state hash")
    shading_hash = _sha256(
        local_state.get("source_shading_physical_result_hash"),
        label="source shading physical result hash",
    )
    equivalent = {
        "aggregation_method": REGIONAL_EQUIVALENT_METHOD,
        "source_scene_revision_id": str(local_state["source_scene_revision_id"]),
        "source_module_instance_id": str(local_state["source_module_instance_id"]),
        "source_module_definition_revision_id": str(
            local_state["source_module_definition_revision_id"]
        ),
        "source_receiver_id": str(region_map["source_receiver_id"]),
        "source_shading_result_id": str(local_state["source_shading_result_id"]),
        "source_shading_physical_result_hash": shading_hash,
        "source_local_irradiance_state_id": str(local_state["state_id"]),
        "source_local_irradiance_state_hash": state_hash,
        "source_electrical_region_map_id": map_id,
        "source_electrical_region_map_hash": map_hash,
        "source_module_topology_revision_id": str(
            region_map["source_module_topology_revision_id"]
        ),
        "mapped_region_area_fraction": coverage,
        "interval_start": _canonical_time(local_state["interval_start"], label="interval_start"),
        "evaluation_time": _canonical_time(local_state["evaluation_time"], label="evaluation_time"),
        "irradiance_mapping_order": str(local_state["irradiance_mapping_order"]),
        "thermal_state_scope": str(local_state["thermal_state_scope"]),
        "module_temperature_c": _finite(
            local_state["module_temperature_c"], label="module_temperature_c"
        ),
        "unshaded_poa": reference_unshaded,
        "post_geometry_poa": {
            channel: float(weighted_post_geometry[channel]) for channel in _CHANNELS
        },
        "optical_modifier": reference_optics,
        "post_optical_poa": {
            channel: float(weighted_post_optical[channel]) for channel in _CHANNELS
        },
        "equivalent_incident_poa_global_w_m2": float(
            sum(weighted_post_geometry.values())
        ),
        "equivalent_effective_irradiance_w_m2": float(
            sum(weighted_post_optical.values())
        ),
        "optical_model_manifest": deepcopy(
            dict(local_state.get("optical_model_manifest") or {})
        ),
        "quality_flags": sorted(quality_flags),
    }
    equivalent["equivalent_state_sha256"] = _canonical_sha256(equivalent)
    return equivalent


def _module_area(module_definition: Mapping[str, Any]) -> float:
    mechanical = module_definition.get("mechanical") or {}
    width = _finite(mechanical.get("width_m"), label="module mechanical.width_m")
    height = _finite(mechanical.get("height_m"), label="module mechanical.height_m")
    if width <= 0.0 or height <= 0.0:
        raise Level1ModuleApproximationError("module mechanical dimensions must be positive")
    return width * height


def _single_interval_inputs(
    equivalent_state: Mapping[str, Any],
) -> tuple[OpticalResult, ThermalResult]:
    interval = pd.Timestamp(str(equivalent_state["interval_start"]))
    evaluation = pd.Timestamp(str(equivalent_state["evaluation_time"]))
    index = pd.DatetimeIndex([interval], name="interval_start")
    optical = OpticalResult(
        frame=pd.DataFrame(
            {
                "evaluation_time": [evaluation],
                "effective_irradiance_w_m2": [
                    float(equivalent_state["equivalent_effective_irradiance_w_m2"])
                ],
                "incident_poa_global_w_m2": [
                    float(equivalent_state["equivalent_incident_poa_global_w_m2"])
                ],
            },
            index=index,
        ),
        metadata={
            "model_id": LEVEL1_MODULE_SOLVER_ID,
            "input_state_sha256": str(equivalent_state["equivalent_state_sha256"]),
        },
    )
    temperature = float(equivalent_state["module_temperature_c"])
    thermal = ThermalResult(
        frame=pd.DataFrame(
            {
                "evaluation_time": [evaluation],
                "cell_temperature_c": [temperature],
                "module_temperature_c": [temperature],
            },
            index=index,
        ),
        metadata={
            "model_id": "phase64.explicit_single_module_temperature",
            "temperature_state": THERMAL_STATE_SCOPE,
        },
    )
    return optical, thermal


def _assert_equivalent_state(value: Mapping[str, Any]) -> None:
    method = value.get("aggregation_method")
    if method not in {MODULE_RECEIVER_EQUIVALENT_METHOD, REGIONAL_EQUIVALENT_METHOD}:
        raise Level1ModuleApproximationError("unsupported Level-1 aggregation_method")
    if value.get("irradiance_mapping_order") != IRRADIANCE_MAPPING_ORDER:
        raise Level1ModuleApproximationError("equivalent state has invalid irradiance mapping order")
    if value.get("thermal_state_scope") != THERMAL_STATE_SCOPE:
        raise Level1ModuleApproximationError("equivalent state has invalid thermal_state_scope")
    for field in (
        "source_scene_revision_id",
        "source_module_instance_id",
        "source_module_definition_revision_id",
        "source_shading_result_id",
    ):
        if not isinstance(value.get(field), str) or not str(value[field]).strip():
            raise Level1ModuleApproximationError(f"equivalent state {field} is required")
    _sha256(value.get("source_shading_physical_result_hash"), label="source shading physical result hash")
    _canonical_time(value.get("interval_start"), label="interval_start")
    _canonical_time(value.get("evaluation_time"), label="evaluation_time")
    _finite(value.get("module_temperature_c"), label="module_temperature_c")
    post_geometry = _three_channels(value.get("post_geometry_poa") or {}, label="post_geometry_poa")
    post_optical = _three_channels(value.get("post_optical_poa") or {}, label="post_optical_poa")
    incident = _finite(value.get("equivalent_incident_poa_global_w_m2"), label="equivalent_incident_poa_global_w_m2")
    effective = _finite(value.get("equivalent_effective_irradiance_w_m2"), label="equivalent_effective_irradiance_w_m2")
    if not math.isclose(incident, sum(post_geometry.values()), rel_tol=1e-12, abs_tol=1e-9):
        raise Level1ModuleApproximationError("equivalent incident POA does not reconcile with channels")
    if not math.isclose(effective, sum(post_optical.values()), rel_tol=1e-12, abs_tol=1e-9):
        raise Level1ModuleApproximationError("equivalent effective irradiance does not reconcile with channels")
    stored_hash = _sha256(value.get("equivalent_state_sha256"), label="equivalent state hash")
    payload = {key: deepcopy(item) for key, item in value.items() if key != "equivalent_state_sha256"}
    if stored_hash != _canonical_sha256(payload):
        raise Level1ModuleApproximationError("equivalent_state_sha256 does not match payload")


def evaluate_level1_module_approximation(
    module_definition: Mapping[str, Any],
    resolved_component_model: Mapping[str, Any],
    equivalent_state: Mapping[str, Any],
    *,
    source_electrical_revision_id: str,
    requested_fidelity: str = "level_1_module_approximation",
    fallback_policy: str = "fail_closed",
    solver: str = "lambertw",
) -> Level1ModuleApproximationResult:
    """Evaluate one Level-1 whole-module SDM state and result envelope."""
    _assert_equivalent_state(equivalent_state)
    module_revision_id = str(module_definition.get("revision_id") or "")
    if not module_revision_id:
        raise Level1ModuleApproximationError("ModuleDefinition revision_id is required")
    if str(equivalent_state.get("source_module_definition_revision_id") or "") != module_revision_id:
        raise Level1ModuleApproximationError(
            "equivalent irradiance state is bound to a different ModuleDefinition revision"
        )
    electrical_revision_id = str(source_electrical_revision_id or "")
    if not electrical_revision_id:
        raise Level1ModuleApproximationError("source_electrical_revision_id is required")

    module_snapshot = resolve_module_capability_snapshot(
        module_definition,
        resolved_component_model,
    )
    capability = resolve_electrical_shading_capability(module_snapshot)
    try:
        resolved_fidelity = assert_requested_fidelity_available(
            requested_fidelity,
            capability,
            fallback_policy=fallback_policy,
        )
    except Exception as exc:
        raise Level1ModuleApproximationError(str(exc)) from exc
    if resolved_fidelity != "level_1_module_approximation":
        raise Level1ModuleApproximationError(
            "Phase 6.4 evaluator executes only resolved Level-1 module approximation"
        )

    parameter_set = extract_validated_pvsyst_parameter_set(dict(module_definition))
    optical, thermal = _single_interval_inputs(equivalent_state)
    electrical = calculate_pvsyst_module_electrical(
        optical,
        thermal,
        parameter_set=parameter_set,
        module_area_m2=_module_area(module_definition),
        solver=solver,
    )
    row = electrical.frame.iloc[0]
    mpp = {
        "isc_a": float(row["isc_a"]),
        "voc_v": float(row["voc_v"]),
        "imp_a": float(row["imp_a"]),
        "vmp_v": float(row["vmp_v"]),
        "pmp_w": float(row["pmp_w"]),
        "active": bool(row["active"]),
    }
    fallback_applied = resolved_fidelity != requested_fidelity
    fallback_reason = (
        f"requested {requested_fidelity}; resolved {resolved_fidelity} by explicit policy"
        if fallback_applied
        else None
    )
    state_payload = {
        "source_scene_revision_id": str(equivalent_state["source_scene_revision_id"]),
        "source_electrical_revision_id": electrical_revision_id,
        "source_module_instance_id": str(equivalent_state["source_module_instance_id"]),
        "source_module_definition_revision_id": module_revision_id,
        "source_shading_result_id": str(equivalent_state["source_shading_result_id"]),
        "source_shading_physical_result_hash": _sha256(
            equivalent_state["source_shading_physical_result_hash"],
            label="source shading physical result hash",
        ),
        "source_local_irradiance_state_id": equivalent_state.get(
            "source_local_irradiance_state_id"
        ),
        "source_local_irradiance_state_hash": equivalent_state.get(
            "source_local_irradiance_state_hash"
        ),
        "source_electrical_region_map_id": equivalent_state.get(
            "source_electrical_region_map_id"
        ),
        "source_electrical_region_map_hash": equivalent_state.get(
            "source_electrical_region_map_hash"
        ),
        "source_module_topology_revision_id": equivalent_state.get(
            "source_module_topology_revision_id"
        ),
        "interval_start": str(equivalent_state["interval_start"]),
        "evaluation_time": str(equivalent_state["evaluation_time"]),
        "aggregation_method": str(equivalent_state["aggregation_method"]),
        "irradiance_mapping_order": str(equivalent_state["irradiance_mapping_order"]),
        "thermal_state_scope": THERMAL_STATE_SCOPE,
        "module_temperature_c": float(equivalent_state["module_temperature_c"]),
        "unshaded_poa": deepcopy(dict(equivalent_state["unshaded_poa"])),
        "post_geometry_poa": deepcopy(dict(equivalent_state["post_geometry_poa"])),
        "optical_modifier": deepcopy(dict(equivalent_state["optical_modifier"])),
        "post_optical_poa": deepcopy(dict(equivalent_state["post_optical_poa"])),
        "equivalent_incident_poa_global_w_m2": float(
            equivalent_state["equivalent_incident_poa_global_w_m2"]
        ),
        "equivalent_effective_irradiance_w_m2": float(
            equivalent_state["equivalent_effective_irradiance_w_m2"]
        ),
        "mapped_region_area_fraction": equivalent_state.get(
            "mapped_region_area_fraction"
        ),
        "module_mpp": mpp,
        "model_manifest": {
            "module_electrical_model_id": MODULE_PVSYST_SDM,
            "module_electrical_model_solver": solver,
            "resolved_component_model_resolution_id": str(
                resolved_component_model.get("resolution_id") or ""
            ),
            "level1_solver_id": LEVEL1_MODULE_SOLVER_ID,
            "level1_solver_version": LEVEL1_MODULE_SOLVER_VERSION,
        },
        "internal_nonuniformity_scope": "collapsed_uniform_equivalent",
        "bypass_scope": "not_modeled",
        "quality_flags": sorted(set(equivalent_state.get("quality_flags") or [])),
    }
    state_hash = _canonical_sha256(state_payload)
    module_state = {
        "schema_name": "ModuleLevelElectricalApproximationState",
        "schema_version": "0.1",
        "contract_version": ELECTRICAL_SHADING_CONTRACT_VERSION,
        "state_id": (
            f"level1-module:{state_payload['source_module_instance_id']}:{state_hash[:16]}"
        ),
        **state_payload,
        "state_payload_sha256": state_hash,
    }

    config = {
        "contract_version": ELECTRICAL_SHADING_CONTRACT_VERSION,
        "requested_fidelity": requested_fidelity,
        "fallback_policy": fallback_policy,
        "thermal_state_scope": THERMAL_STATE_SCOPE,
        "loss_accounting_boundary": LOSS_ACCOUNTING_BOUNDARY,
        "model_selections": {
            "module_electrical_model_id": MODULE_PVSYST_SDM,
            "region_parameterization_model_id": None,
            "cell_parameterization_model_id": None,
            "bypass_model_family_id": None,
            "module_iv_assembly_model_id": None,
            "string_iv_assembly_model_id": None,
            "mppt_operating_point_model_id": None,
        },
        "scientific_options": {
            "level1_aggregation_method": state_payload["aggregation_method"],
            "irradiance_mapping_order": state_payload["irradiance_mapping_order"],
            "internal_nonuniformity_scope": "collapsed_uniform_equivalent",
            "module_solver": solver,
        },
        "execution_options": {
            "cache_mode": "none",
            "storage_mode": "inline",
            "parallelization": "none",
        },
    }
    scientific_configuration_hash = electrical_shading_scientific_sha256(config)
    execution_configuration_hash = electrical_shading_execution_sha256(config)
    scientific_input_payload = {
        "scientific_configuration_sha256": scientific_configuration_hash,
        "module_state_sha256": state_hash,
        "module_definition_revision_id": module_revision_id,
        "resolved_component_model_resolution_id": str(
            resolved_component_model.get("resolution_id") or ""
        ),
        "source_scene_revision_id": state_payload["source_scene_revision_id"],
        "source_electrical_revision_id": electrical_revision_id,
        "source_shading_physical_result_hash": state_payload[
            "source_shading_physical_result_hash"
        ],
    }
    scientific_input_hash = _canonical_sha256(scientific_input_payload)
    physical_payload = {
        "resolved_fidelity": resolved_fidelity,
        "module_state_sha256": state_hash,
        "scientific_input_sha256": scientific_input_hash,
        "module_mpp": mpp,
        "attribution": {
            "geometric_irradiance": "upstream_not_rebooked",
            "electrical_mismatch": "not_modeled",
            "bypass_interaction": "not_modeled",
            "mppt_operating_point": "not_modeled",
        },
    }
    physical_hash = _canonical_sha256(physical_payload)
    execution_hash = _canonical_sha256(
        {
            "physical_result_sha256": physical_hash,
            "execution_configuration_sha256": execution_configuration_hash,
        }
    )
    topology_revision = equivalent_state.get("source_module_topology_revision_id")
    map_hash = equivalent_state.get("source_electrical_region_map_hash")
    electrical_result = {
        "schema_name": "ElectricalShadingResult",
        "schema_version": "0.1",
        "contract_version": ELECTRICAL_SHADING_CONTRACT_VERSION,
        "electrical_shading_result_id": (
            f"electrical-shading:level1:{state_payload['source_module_instance_id']}:{physical_hash[:16]}"
        ),
        "source_scene_revision_id": state_payload["source_scene_revision_id"],
        "source_electrical_revision_id": electrical_revision_id,
        "source_shading_result_id": state_payload["source_shading_result_id"],
        "source_shading_physical_result_hash": state_payload[
            "source_shading_physical_result_hash"
        ],
        "requested_fidelity": requested_fidelity,
        "resolved_fidelity": resolved_fidelity,
        "fallback_applied": fallback_applied,
        "fallback_reason": fallback_reason,
        "thermal_state_scope": THERMAL_STATE_SCOPE,
        "source_module_topology_revision_ids": (
            [str(topology_revision)] if topology_revision else []
        ),
        "source_region_map_hashes": ([str(map_hash)] if map_hash else []),
        "scientific_model_manifest": {
            **config["model_selections"],
            "level1_aggregation_model_id": state_payload["aggregation_method"],
            "module_approximation_state_sha256": state_hash,
            "resolved_component_model_resolution_id": str(
                resolved_component_model.get("resolution_id") or ""
            ),
        },
        "execution_manifest": {
            "solver_id": LEVEL1_MODULE_SOLVER_ID,
            "solver_version": LEVEL1_MODULE_SOLVER_VERSION,
            "cache_mode": "none",
            "storage_mode": "inline",
            "parallelization": "none",
            "execution_configuration_sha256": execution_configuration_hash,
        },
        "loss_accounting_boundary": LOSS_ACCOUNTING_BOUNDARY,
        "attribution_delta_convention": ATTRIBUTION_DELTA_CONVENTION,
        "attribution_channels": {
            "geometric_irradiance": {
                "status": "upstream",
                "accounting_rule": "upstream_not_rebooked",
            },
            "electrical_mismatch": {
                "status": "not_modeled",
                "counterfactual_basis": (
                    "uniform_same_area_weighted_effective_irradiance_to_nonuniform_bypass_forced_off"
                ),
            },
            "bypass_interaction": {
                "status": "not_modeled",
                "counterfactual_basis": (
                    "nonuniform_bypass_forced_off_to_nonuniform_bypass_enabled"
                ),
                "signed_delta": True,
            },
            "mppt_operating_point": {
                "status": "not_modeled",
                "counterfactual_basis": (
                    "ideal_global_mpp_to_selected_tracker_operating_point"
                ),
            },
        },
        "scientific_input_sha256": scientific_input_hash,
        "physical_result_sha256": physical_hash,
        "execution_payload_sha256": execution_hash,
        "approximation_manifest": [
            {
                "approximation_id": "level1.uniform_module_equivalent",
                "statement": (
                    "Spatial irradiance nonuniformity is collapsed to one module-equivalent "
                    "irradiance and one validated whole-module SDM state; internal mismatch "
                    "and bypass interaction are not modeled."
                ),
                "scope": "one_module_one_interval",
            }
        ],
        "findings": [
            {
                "severity": "info",
                "code": "ELECTRICAL_SHADING_LEVEL1_INTERNAL_MISMATCH_NOT_MODELED",
                "message": (
                    "Level 1 reports one whole-module electrical state only; substring, "
                    "bypass, nonuniform module-IV, string-IV and MPPT interaction remain unmodeled."
                ),
                "entity_id": state_payload["source_module_instance_id"],
                "context": {
                    "aggregation_method": state_payload["aggregation_method"],
                    "module_state_sha256": state_hash,
                },
            }
        ],
    }
    return Level1ModuleApproximationResult(
        module_state=module_state,
        electrical_shading_result=electrical_result,
    )
