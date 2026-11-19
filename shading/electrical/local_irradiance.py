"""Phase-6.3 region-level geometric visibility and local irradiance handoff.

This module reuses the validated Phase-5 beam/sky/ground geometry kernels on
ElectricalRegionMap-derived receiver polygons. It stops before any substring,
bypass, IV-assembly, string, or MPPT electrical interaction.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from geometry.shading.beam import (
    _fallback_evidence,
    BeamShadowError,
    BEAM_SOLVER_ID,
    BEAM_SOLVER_VERSION,
    calculate_direct_beam_shadow,
)
from geometry.shading.sky import (
    SKY_VISIBILITY_SOLVER_ID,
    SKY_VISIBILITY_SOLVER_VERSION,
    SkyDomeResolution,
    SkyVisibilityError,
    calculate_sky_visibility,
)
from geometry.shading.ground import (
    GROUND_VISIBILITY_SOLVER_ID,
    GROUND_VISIBILITY_SOLVER_VERSION,
    GroundDomeResolution,
    GroundVisibilityError,
    calculate_ground_visibility,
)


REGION_VISIBILITY_ORCHESTRATOR_ID = "opensimpv.electrical_region_visibility_snapshot"
REGION_VISIBILITY_ORCHESTRATOR_VERSION = "0.1"
LOCAL_IRRADIANCE_MAPPER_ID = "opensimpv.local_electrical_irradiance.three_channel"
LOCAL_IRRADIANCE_MAPPER_VERSION = "0.1"
FACTOR_CONVENTION = "visibility_one_clear_zero_blocked"
IRRADIANCE_MAPPING_ORDER = (
    "unshaded_poa_by_channel_then_geometry_visibility_then_optical_treatment"
)

_CHANNELS = ("beam_w_m2", "sky_diffuse_w_m2", "ground_reflected_w_m2")
_VISIBILITY_FIELDS = {
    "beam_w_m2": "beam_visibility_factor",
    "sky_diffuse_w_m2": "sky_visibility_factor",
    "ground_reflected_w_m2": "ground_visibility_factor",
}
_OPTICAL_FIELDS = {
    "beam_w_m2": "beam",
    "sky_diffuse_w_m2": "sky_diffuse",
    "ground_reflected_w_m2": "ground_reflected",
}


class LocalElectricalIrradianceError(ValueError):
    """Raised when region geometry/visibility/irradiance identities do not bind."""


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hash(value: Any, *, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise LocalElectricalIrradianceError(f"{label} must be a lowercase SHA-256")
    return text


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LocalElectricalIrradianceError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise LocalElectricalIrradianceError(f"{label} must be finite")
    return number


def _bounded_fraction(value: Any, *, label: str) -> float:
    number = _finite(value, label=label)
    if not 0.0 <= number <= 1.0:
        raise LocalElectricalIrradianceError(f"{label} must be within [0, 1]")
    return number


def _canonical_time(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        raise LocalElectricalIrradianceError("timestamp must be non-empty when supplied")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise LocalElectricalIrradianceError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LocalElectricalIrradianceError("timestamp must include a timezone offset")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _find_source_module_receiver(
    compiled_geometry: Mapping[str, Any],
    region_map: Mapping[str, Any],
) -> Mapping[str, Any]:
    receiver_id = str(region_map.get("source_receiver_id") or "")
    matches = [
        item
        for item in compiled_geometry.get("receivers", [])
        if str(item.get("receiver_id") or "") == receiver_id
    ]
    if len(matches) != 1:
        raise LocalElectricalIrradianceError(
            "ElectricalRegionMap source_receiver_id must resolve exactly once"
        )
    receiver = matches[0]
    if receiver.get("source_entity_type") != "module_instance":
        raise LocalElectricalIrradianceError("ElectricalRegionMap must bind a module receiver")
    if str(receiver.get("module_instance_id") or "") != str(
        region_map.get("source_module_instance_id") or ""
    ):
        raise LocalElectricalIrradianceError("region-map module/receiver binding mismatch")
    return receiver


def build_electrical_region_query_geometry(
    compiled_geometry: Mapping[str, Any],
    region_map: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an ephemeral geometry-kernel view whose receivers are electrical regions.

    The occluder geometry is copied verbatim from the canonical Phase-5 compiled
    geometry. The new hash is bound to both that parent geometry and the exact
    ElectricalRegionMap; this query view is not a new editable geometry authority.
    """
    parent_hash = _hash(
        compiled_geometry.get("geometry_payload_sha256"),
        label="compiled geometry hash",
    )
    map_hash = _hash(region_map.get("mapping_payload_sha256"), label="region map hash")
    if str(region_map.get("source_compiled_geometry_hash") or "") != parent_hash:
        raise LocalElectricalIrradianceError(
            "ElectricalRegionMap is not bound to the supplied compiled geometry"
        )
    if str(region_map.get("source_scene_revision_id") or "") != str(
        compiled_geometry.get("source_scene_revision_id") or ""
    ):
        raise LocalElectricalIrradianceError("region-map/compiled scene revision mismatch")

    source_receiver = _find_source_module_receiver(compiled_geometry, region_map)
    normal = deepcopy(source_receiver["normal_xyz"])
    receivers: list[dict[str, Any]] = []
    for region in sorted(
        region_map.get("regions") or [],
        key=lambda item: str(item.get("region_id") or ""),
    ):
        vertices = [list(map(float, point)) for point in region["vertices_3d"]]
        if len(vertices) < 3:
            raise LocalElectricalIrradianceError("electrical region requires >=3 vertices")
        center = [
            sum(point[index] for point in vertices) / len(vertices)
            for index in range(3)
        ]
        receivers.append(
            {
                "receiver_id": str(region["region_id"]),
                "source_entity_type": "module_instance",
                "source_entity_id": str(region_map["source_module_instance_id"]),
                "receiver_type": "module_plane",
                "vertices_3d": vertices,
                "center_xyz": center,
                "normal_xyz": deepcopy(normal),
                "area_m2": float(region["area_m2"]),
                "enabled": True,
                "pv_field_id": source_receiver.get("pv_field_id"),
                "support_surface_id": source_receiver.get("support_surface_id"),
                "module_instance_id": str(region_map["source_module_instance_id"]),
                "metadata": {
                    "electrical_region_map_id": str(region_map["electrical_region_map_id"]),
                    "source_topology_region_id": str(region["source_topology_region_id"]),
                    "source_electrical_substring_id": str(
                        region["source_electrical_substring_id"]
                    ),
                },
            }
        )

    query_hash = _canonical_sha256(
        {
            "parent_compiled_geometry_hash": parent_hash,
            "electrical_region_map_hash": map_hash,
            "receivers": receivers,
        }
    )
    return {
        "source_scene_revision_id": str(region_map["source_scene_revision_id"]),
        "geometry_payload_sha256": query_hash,
        "parent_compiled_geometry_hash": parent_hash,
        "source_electrical_region_map_id": str(region_map["electrical_region_map_id"]),
        "source_electrical_region_map_hash": map_hash,
        "receivers": receivers,
        "occluders": deepcopy(list(compiled_geometry.get("occluders") or [])),
    }


def evaluate_electrical_region_visibility(
    compiled_geometry: Mapping[str, Any],
    region_map: Mapping[str, Any],
    *,
    sun_vector_xyz: Sequence[float],
    self_shading_enabled: bool,
    sky_resolution: SkyDomeResolution,
    ground_resolution: GroundDomeResolution,
    timestamp: str | None = None,
    fidelity_level: str = "detailed",
    include_components: bool = False,
) -> dict[str, Any]:
    """Evaluate beam/sky/ground geometry factors for every electrical region."""
    if not isinstance(self_shading_enabled, bool):
        raise LocalElectricalIrradianceError("self_shading_enabled must be explicit boolean")
    if fidelity_level not in {"preview", "fast", "engineering", "detailed", "research"}:
        raise LocalElectricalIrradianceError("unsupported geometric fidelity_level")
    if len(sun_vector_xyz) != 3:
        raise LocalElectricalIrradianceError("sun_vector_xyz must contain three values")
    sun_vector = [_finite(value, label="sun_vector_xyz") for value in sun_vector_xyz]
    norm = math.sqrt(sum(value * value for value in sun_vector))
    if norm <= 0.0:
        raise LocalElectricalIrradianceError("sun_vector_xyz must be non-zero")
    sun_vector = [value / norm for value in sun_vector]
    utc_timestamp = _canonical_time(timestamp)

    query = build_electrical_region_query_geometry(compiled_geometry, region_map)
    records: list[dict[str, Any]] = []
    for receiver in query["receivers"]:
        receiver_id = str(receiver["receiver_id"])
        try:
            beam = calculate_direct_beam_shadow(
                query,
                receiver_id=receiver_id,
                sun_vector_xyz=sun_vector,
                self_shading_enabled=self_shading_enabled,
            )
            sky = calculate_sky_visibility(
                query,
                receiver_id=receiver_id,
                self_shading_enabled=self_shading_enabled,
                resolution=sky_resolution,
            )
            ground = calculate_ground_visibility(
                query,
                receiver_id=receiver_id,
                self_shading_enabled=self_shading_enabled,
                resolution=ground_resolution,
            )
        except (BeamShadowError, SkyVisibilityError, GroundVisibilityError) as exc:
            raise LocalElectricalIrradianceError(
                f"region visibility failed; timestamp={utc_timestamp}: {exc}"
            ) from exc
        fallback_events = [
            event for result, channel, time in (
                (beam, "beam", utc_timestamp), (sky, None, None), (ground, None, None)
            ) for event in _fallback_evidence(result, timestamp=time, channel=channel).get(
                "shadow_union_precision_fallback_events", [])
        ]
        evidence = _fallback_evidence({"shadow_union_precision_fallback_events": fallback_events})
        flags: list[str] = list(evidence.get("quality_flags", []))
        if beam.get("status") != "evaluated":
            flags.append(str(beam.get("status")))
        if sky.get("has_front_sky_view") is False:
            flags.append("no_front_sky_view")
        if ground.get("has_front_ground_view") is False:
            flags.append("no_front_ground_view")
        records.append(
            {
                "receiver_id": receiver_id,
                **{key: value for key, value in evidence.items() if key != "quality_flags"},
                "timestamp": utc_timestamp,
                "sun_vector_xyz": deepcopy(sun_vector),
                "beam_visibility_factor": float(beam["beam_visibility_factor"]),
                "sky_visibility_factor": float(sky["sky_visibility_factor"]),
                "ground_visibility_factor": float(ground["ground_visibility_factor"]),
                **({"directional_diffuse_visibility": {"horizon": float(sky["horizon_visibility_factor"]), "circumsolar": float(beam["beam_visibility_factor"])}} if include_components else {}),
                "quality_flags": sorted(set(flags)),
            }
        )

    records.sort(key=lambda item: item["receiver_id"])
    receiver_ids = [item["receiver_id"] for item in records]
    config_payload = {
        "self_shading_enabled": self_shading_enabled,
        "fidelity_level": fidelity_level,
        "sky_dome_resolution": sky_resolution.as_dict(),
        "ground_dome_resolution": ground_resolution.as_dict(),
        "source_electrical_region_map_hash": query["source_electrical_region_map_hash"],
    }
    if include_components:
        config_payload["component_visibility"] = "separate_isotropic_circumsolar_horizon"
    config_hash = _canonical_sha256(config_payload)
    physical_payload = {
        "compiled_query_geometry_hash": query["geometry_payload_sha256"],
        "parent_compiled_geometry_hash": query["parent_compiled_geometry_hash"],
        "source_electrical_region_map_hash": query["source_electrical_region_map_hash"],
        "sun_vector_xyz": sun_vector,
        "timestamp": utc_timestamp,
        "records": records,
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
        "shading_result_id": f"shading:electrical-regions:{physical_hash[:20]}",
        "source_scene_revision_id": str(region_map["source_scene_revision_id"]),
        "compiled_geometry_hash": str(query["geometry_payload_sha256"]),
        "source_parent_compiled_geometry_hash": str(query["parent_compiled_geometry_hash"]),
        "source_electrical_region_map_id": str(region_map["electrical_region_map_id"]),
        "source_electrical_region_map_hash": str(query["source_electrical_region_map_hash"]),
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
        "receiver_granularity": "electrical_region",
        "factor_convention": FACTOR_CONVENTION,
        "electrical_shading_scope": "not_modeled",
        "channels": ["beam_visibility", "sky_visibility", "ground_visibility"],
        "storage_mode": "inline",
        "record_count": len(records),
        "inline_records": records,
        "orchestrator_manifest": {
            "orchestrator_id": REGION_VISIBILITY_ORCHESTRATOR_ID,
            "orchestrator_version": REGION_VISIBILITY_ORCHESTRATOR_VERSION,
        },
        "receiver_set_sha256": _canonical_sha256(receiver_ids),
        "sun_state_sha256": _canonical_sha256(
            {"sun_vector_xyz": sun_vector, "timestamp": utc_timestamp}
        ),
        "source_execution_plan_id": None,
        "result_payload_sha256": physical_hash,
        "physical_result_sha256": physical_hash,
        "approximation_manifest": [],
        "findings": [],
    }


def _three_channel_irradiance(value: Mapping[str, Any], *, label: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for field in _CHANNELS:
        number = _finite(value.get(field), label=f"{label}.{field}")
        if number < 0.0:
            raise LocalElectricalIrradianceError(f"{label}.{field} must be non-negative")
        result[field] = number
    return result


def _nonnegative_optical_factor(value: Any, *, label: str) -> float:
    number = _finite(value, label=label)
    if number < 0:
        raise LocalElectricalIrradianceError(f"{label} must be non-negative")
    return number


def _optical_modifiers(value: Mapping[str, Any]) -> dict[str, float]:
    return {
        field: _bounded_fraction(value.get(field), label=f"optical_modifier.{field}")
        for field in ("beam", "sky_diffuse", "ground_reflected")
    }


def build_local_electrical_irradiance_state(
    region_map: Mapping[str, Any],
    region_shading_result: Mapping[str, Any],
    *,
    unshaded_poa: Mapping[str, Any],
    optical_modifier: Mapping[str, Any],
    optical_model_manifest: Mapping[str, Any],
    module_temperature_c: float,
    interval_start: str,
    evaluation_time: str,
    component_poa: Mapping[str, Any] | None = None,
    component_optical_modifier: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Map region geometry factors and POA channels into local effective irradiance."""
    map_hash = _hash(region_map.get("mapping_payload_sha256"), label="region map hash")
    if str(region_shading_result.get("source_electrical_region_map_id") or "") != str(
        region_map.get("electrical_region_map_id") or ""
    ):
        raise LocalElectricalIrradianceError("regional ShadingResult map ID mismatch")
    if str(region_shading_result.get("source_electrical_region_map_hash") or "") != map_hash:
        raise LocalElectricalIrradianceError("regional ShadingResult map hash mismatch")
    if str(region_shading_result.get("source_scene_revision_id") or "") != str(
        region_map.get("source_scene_revision_id") or ""
    ):
        raise LocalElectricalIrradianceError("regional ShadingResult scene mismatch")
    shading_physical_hash = _hash(
        region_shading_result.get("physical_result_sha256"),
        label="regional shading physical_result_sha256",
    )
    if region_shading_result.get("receiver_granularity") != "electrical_region":
        raise LocalElectricalIrradianceError(
            "local electrical irradiance requires electrical_region shading granularity"
        )
    if region_shading_result.get("electrical_shading_scope") != "not_modeled":
        raise LocalElectricalIrradianceError(
            "geometric source shading must not include electrical mismatch physics"
        )

    unshaded = _three_channel_irradiance(unshaded_poa, label="unshaded_poa")
    # Component evidence is used only by the opt-in optics/thermal path.
    # Preserve the legacy validator, including its [0, 1] refusal, unchanged.
    optics = ({field: _nonnegative_optical_factor(optical_modifier.get(field), label=f"optical_modifier.{field}")
               for field in ("beam", "sky_diffuse", "ground_reflected")}
              if component_poa is not None else _optical_modifiers(optical_modifier))
    temperature = _finite(module_temperature_c, label="module_temperature_c")
    interval = _canonical_time(interval_start)
    evaluation = _canonical_time(evaluation_time)
    if interval is None or evaluation is None:
        raise LocalElectricalIrradianceError("interval/evaluation timestamps are required")

    model_id = optical_model_manifest.get("model_id")
    model_version = optical_model_manifest.get("model_version")
    if not isinstance(model_id, str) or not model_id or not isinstance(model_version, str) or not model_version:
        raise LocalElectricalIrradianceError(
            "optical_model_manifest requires model_id and model_version"
        )

    expected_region_ids = {
        str(region["region_id"]) for region in region_map.get("regions") or []
    }
    records = {
        str(record["receiver_id"]): record
        for record in region_shading_result.get("inline_records") or []
    }
    if set(records) != expected_region_ids:
        raise LocalElectricalIrradianceError(
            "regional ShadingResult receiver set must exactly match ElectricalRegionMap regions"
        )

    region_states: list[dict[str, Any]] = []
    for region in sorted(
        region_map.get("regions") or [],
        key=lambda item: str(item["region_id"]),
    ):
        region_id = str(region["region_id"])
        record = records[region_id]
        visibility = {
            "beam": _bounded_fraction(
                record.get("beam_visibility_factor"),
                label=f"{region_id}.beam_visibility_factor",
            ),
            "sky_diffuse": _bounded_fraction(
                record.get("sky_visibility_factor"),
                label=f"{region_id}.sky_visibility_factor",
            ),
            "ground": _bounded_fraction(
                record.get("ground_visibility_factor"),
                label=f"{region_id}.ground_visibility_factor",
            ),
        }
        post_geometry = {
            "beam_w_m2": unshaded["beam_w_m2"] * visibility["beam"],
            "sky_diffuse_w_m2": (
                unshaded["sky_diffuse_w_m2"] * visibility["sky_diffuse"]
            ),
            "ground_reflected_w_m2": (
                unshaded["ground_reflected_w_m2"] * visibility["ground"]
            ),
        }
        effective = sum(
            post_geometry[channel] * optics[_OPTICAL_FIELDS[channel]]
            for channel in _CHANNELS
        )
        region_states.append(
            {
                "region_id": region_id,
                "unshaded_poa": deepcopy(unshaded),
                "visibility_factor": visibility,
                "post_geometry_poa": post_geometry,
                "optical_modifier": deepcopy(optics),
                "effective_irradiance_w_m2": float(effective),
                "quality_flags": sorted(set(record.get("quality_flags") or [])),
            }
        )

    if component_poa is not None:
        if component_optical_modifier is None:
            raise LocalElectricalIrradianceError("component optical modifiers are required")
        components = _component_values(component_poa)
        factors = {k: _nonnegative_optical_factor(component_optical_modifier.get(k), label=f"component optics.{k}")
                   for k in ("beam", "sky", "horizon", "ground")}
        expected_source = {"beam_w_m2": components["beam"],
            "sky_diffuse_w_m2": components["isotropic"] + components["circumsolar"] + components["horizon"],
            "ground_reflected_w_m2": components["ground"]}
        if any(not math.isclose(unshaded[k], v, abs_tol=1e-9, rel_tol=1e-12) for k,v in expected_source.items()):
            raise LocalElectricalIrradianceError("component source does not reconcile with unshaded POA")
        for state in region_states:
            record = records[state["region_id"]]
            visibility = {"beam": state["visibility_factor"]["beam"],
                "sky": state["visibility_factor"]["sky_diffuse"],
                "horizon": _bounded_fraction((record.get("directional_diffuse_visibility") or {}).get("horizon"), label="horizon visibility"),
                "ground": state["visibility_factor"]["ground"]}
            geometry, optical = component_irradiance_channels(components, visibility, factors)
            sky = sum(geometry[k] for k in ("isotropic", "circumsolar", "horizon"))
            effective = sum(optical.values())
            if sky < 0 or effective < 0:
                raise LocalElectricalIrradianceError(f"{region_map['source_module_instance_id']} at {interval}: combined component irradiance is negative")
            state["post_geometry_poa"] = {"beam_w_m2": geometry["beam"], "sky_diffuse_w_m2": sky, "ground_reflected_w_m2": geometry["ground"]}
            state["effective_irradiance_w_m2"] = effective
            state["component_state"] = {"unshaded": components, "post_geometry": geometry,
                "post_optical": optical, "visibility": visibility, "optical_modifier": factors}

    identity_payload = {
        "source_scene_revision_id": str(region_map["source_scene_revision_id"]),
        "source_module_instance_id": str(region_map["source_module_instance_id"]),
        "source_module_definition_revision_id": str(
            region_map["source_module_definition_revision_id"]
        ),
        "source_electrical_region_map_id": str(region_map["electrical_region_map_id"]),
        "source_electrical_region_map_hash": map_hash,
        "source_shading_result_id": str(region_shading_result["shading_result_id"]),
        "source_shading_physical_result_hash": shading_physical_hash,
        "interval_start": interval,
        "evaluation_time": evaluation,
        "irradiance_mapping_order": IRRADIANCE_MAPPING_ORDER,
        "irradiance_side_scope": "front_side_only_v0.1",
        "thermal_state_scope": "single_module_temperature",
        "module_temperature_c": temperature,
        "optical_model_manifest": deepcopy(dict(optical_model_manifest)),
        "regions": region_states,
    }
    digest = _canonical_sha256(identity_payload)
    return {
        "schema_name": "LocalElectricalIrradianceState",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "state_id": f"local-electrical-irradiance:{region_map['source_module_instance_id']}:{digest[:16]}",
        **identity_payload,
        "state_payload_sha256": digest,
        "quality_flags": [],
    }


_COMPONENTS = ("beam", "isotropic", "circumsolar", "horizon", "ground")


def _component_values(value):
    if set(value) != set(_COMPONENTS):
        raise LocalElectricalIrradianceError("component POA requires beam, isotropic, circumsolar, horizon and ground")
    result = {k: _finite(value[k], label=f"component {k}") for k in _COMPONENTS}
    if any(result[k] < 0 for k in _COMPONENTS if k not in {"isotropic", "horizon"}):
        raise LocalElectricalIrradianceError("only the empirical isotropic and horizon components may be signed")
    return result


def component_irradiance_channels(components, visibility, optics):
    """Five-component oracle boundary: preserve the signed horizon correction."""
    direction = {"beam": "beam", "isotropic": "sky", "circumsolar": "beam", "horizon": "horizon", "ground": "ground"}
    geometry = {k: components[k] * visibility[direction[k]] for k in _COMPONENTS}
    optical = {k: geometry[k] * optics[direction[k]] for k in _COMPONENTS}
    return geometry, optical


def collapse_component_irradiance(region_map, local):
    """Area-weight component evidence without the legacy three-channel optical approximation.

    Legacy collapse remains unchanged. All mapping/coverage/hash/closure checks
    are enforced here before the detailed thermal handoff.
    """
    for field, expected in (("source_electrical_region_map_id", region_map["electrical_region_map_id"]),
                            ("source_electrical_region_map_hash", region_map["mapping_payload_sha256"]),
                            ("source_scene_revision_id", region_map["source_scene_revision_id"]),
                            ("source_module_instance_id", region_map["source_module_instance_id"]),
                            ("source_module_definition_revision_id", region_map["source_module_definition_revision_id"])):
        if local.get(field) != expected: raise LocalElectricalIrradianceError(f"component collapse binding mismatch: {field}")
    payload = {k:v for k,v in local.items() if k not in {"schema_name", "schema_version", "contract_version", "state_id", "state_payload_sha256", "quality_flags"}}
    if _canonical_sha256(payload) != local["state_payload_sha256"]:
        raise LocalElectricalIrradianceError("component irradiance state hash mismatch")
    if abs(float(region_map["mapped_region_area_fraction"]) - 1.0) > 1e-9:
        raise LocalElectricalIrradianceError("component collapse requires complete module coverage")
    total = _finite(region_map["mapped_region_area_m2"], label="mapped region area")
    if total <= 0: raise LocalElectricalIrradianceError("mapped region area must be positive")
    mapped = {r["region_id"]:r for r in region_map["regions"]}
    records = {r["region_id"]:r for r in local["regions"]}
    if len(records) != len(local["regions"]) or set(mapped) != set(records) or not mapped:
        raise LocalElectricalIrradianceError("component collapse requires exact region coverage")
    geometry = {k:0.0 for k in _COMPONENTS}; optical = dict(geometry); area = 0.0
    for rid, record in records.items():
        a = _finite(mapped[rid]["area_m2"], label="region area")
        if a <= 0: raise LocalElectricalIrradianceError("region area must be positive")
        area += a; evidence = record["component_state"]
        g,e = component_irradiance_channels(evidence["unshaded"], evidence["visibility"], evidence["optical_modifier"])
        if g != evidence["post_geometry"] or e != evidence["post_optical"] or not math.isclose(sum(e.values()),record["effective_irradiance_w_m2"],abs_tol=1e-9,rel_tol=1e-12):
            raise LocalElectricalIrradianceError("regional component irradiance does not reconcile")
        for k in _COMPONENTS:
            geometry[k] += a / total * g[k]; optical[k] += a / total * e[k]
    if not math.isclose(area,total,abs_tol=max(1e-12,total*1e-9),rel_tol=1e-9):
        raise LocalElectricalIrradianceError("regional area does not match total")
    return {"post_geometry_components": geometry, "post_optical_components": optical,
        "post_geometry_poa": {"beam_w_m2":geometry["beam"], "sky_diffuse_w_m2":sum(geometry[k] for k in ("isotropic","circumsolar","horizon")), "ground_reflected_w_m2":geometry["ground"]},
        "equivalent_incident_poa_global_w_m2":sum(geometry.values()),
        "equivalent_effective_irradiance_w_m2":sum(optical.values())}
