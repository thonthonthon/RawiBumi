"""Derived receiver/execution grouping for Phase 5.2.

This module separates canonical topology interpretation from the limitations of
the legacy homogeneous numerical worker. It does not execute shading or
electrical mismatch physics.

Execution groups are derived from canonical Scene + ElectricalDesignRevision.
They group strings that share the same irradiance/electrical state signature:

- inverter instance
- module revision
- module count per string
- tilt
- azimuth
- resolved albedo

MPPT identity is deliberately *not* part of the grouping signature. This allows
homogeneous strings on several MPPTs to remain one execution group while still
detecting heterogeneous groups that share one MPPT.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping


EXECUTION_GROUP_PLAN_VERSION = "0.1"
EXECUTION_GROUP_BUILDER_ID = "rawibumi.simulation_execution_groups"
EXECUTION_GROUP_BUILDER_VERSION = "0.1"


def _canonical_hash(value: Mapping[str, Any] | list[Any]) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_angle(value: Any) -> float:
    result = float(value) % 360.0
    if not math.isfinite(result):
        raise ValueError("angle must be finite")
    return result


def _finite(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def orientation_tolerance_deg(electrical: Mapping[str, Any]) -> float | None:
    """S14b: the normal-angle tolerance of the design's orientation policy, or None (exact comparison)."""
    policy = electrical.get("orientation_policy")
    if not isinstance(policy, Mapping):
        return None
    value = _finite(policy.get("normal_angle_tolerance_deg", 1.0), "normal_angle_tolerance_deg")
    if value < 0.0:
        raise ValueError("normal_angle_tolerance_deg must be non-negative")
    return value


def _unit_normal(tilt_deg: float, azimuth_deg: float) -> tuple[float, float, float]:
    t, a = math.radians(tilt_deg), math.radians(azimuth_deg)
    return (math.sin(t) * math.sin(a), math.sin(t) * math.cos(a), math.cos(t))


def normal_angle_deg(first: tuple[float, float], second: tuple[float, float]) -> float:
    """Angle between two module normals given as (tilt, azimuth) in degrees."""
    a, b = _unit_normal(*first), _unit_normal(*second)
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))))


def _merged_state(states, orientations, tolerance):
    """One state at the module-weighted mean normal when `states` differ only in orientation and every pair of
    `orientations` (one per module) is within `tolerance`; otherwise None."""
    if len({(s[0], s[1], s[2], s[5]) for s in states}) != 1:
        return None
    distinct = sorted(set(orientations))
    largest = max((normal_angle_deg(a, b) for i, a in enumerate(distinct) for b in distinct[i + 1:]), default=0.0)
    if largest > tolerance:
        return None
    x, y, z = (sum(component) for component in zip(*(_unit_normal(*o) for o in orientations)))
    length = math.sqrt(x * x + y * y + z * z)
    tilt = round(math.degrees(math.acos(max(-1.0, min(1.0, z / length)))), 9)
    azimuth = round(math.degrees(math.atan2(x, y)) % 360.0, 9)
    base = next(iter(states))
    merge = {"tolerance_deg": tolerance, "max_normal_angle_deg": round(largest, 9),
             "source_orientations": [list(o) for o in distinct]}
    return (base[0], base[1], base[2], tilt, azimuth, base[5]), merge


def _finding(
    severity: str,
    code: str,
    entity_id: str | None,
    message: str,
    *,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "entity_id": entity_id,
        "message": message,
        "context": dict(context or {}),
    }


def _resolved_albedo(
    surface: Mapping[str, Any] | None,
    numerical_options: Mapping[str, Any],
) -> tuple[float, str]:
    if surface is not None and surface.get("albedo") is not None:
        value = _finite(surface["albedo"], "surface albedo")
        source = "scene.support_surface.albedo"
    elif numerical_options.get("albedo") is not None:
        value = _finite(numerical_options["albedo"], "numerical albedo")
        source = "simulation_configuration.numerical_options.albedo"
    else:
        value = 0.20
        source = "documented_generic_default_0.20"
    if value < 0.0 or value > 1.0:
        raise ValueError("resolved albedo must be within [0, 1]")
    if numerical_options.get("optics_thermal_settings") is not None:
        from .optics_thermal import resolve_optics_thermal_settings, uses_legacy_optics_values
        settings = resolve_optics_thermal_settings(numerical_options["optics_thermal_settings"])
        monthly = settings["values"]["albedo"]["monthly_values"]
        # Preserve the scalar descriptor and identity only for the explicit
        # legacy policy when the existing surface/numerical resolution agrees.
        # The actual new-block sources remain in the separate immutable snapshot.
        if not (uses_legacy_optics_values(settings) and value == monthly[0]):
            return monthly[0], "simulation_configuration.optics_thermal_settings.albedo"
    return value, source


def _receiver_map(
    compiled_shading_geometry: Mapping[str, Any] | None,
) -> tuple[dict[str, str], str | None]:
    if compiled_shading_geometry is None:
        return {}, None
    mapping = {
        str(item["module_instance_id"]): str(item["receiver_id"])
        for item in compiled_shading_geometry.get("receivers", [])
        if item.get("source_entity_type") == "module_instance"
        and item.get("module_instance_id") is not None
    }
    return mapping, (
        str(compiled_shading_geometry.get("geometry_payload_sha256"))
        if compiled_shading_geometry.get("geometry_payload_sha256")
        else None
    )


def module_execution_signature(instance, field, surface, numerical, inverter_id, length):
    """The canonical electrical/irradiance state, shared with assignment planning."""
    if field.get("field_kind") == "explicit_layout":
        from geometry.pvfield.explicit import table_for_module
        field = table_for_module(instance, field)
    albedo, source = _resolved_albedo(surface, numerical)
    tilt = _finite(field["tilt_deg"], "tilt_deg")
    azimuth = _normalize_angle(field["azimuth_deg"])
    revision = str(instance.get("module_definition_revision_id") or "")
    return (inverter_id, revision, length, tilt, azimuth, albedo), source


def string_compatibility_keys(scene, strings, *, numerical_options=None, orientation_tolerance_deg=None):
    """Resolve unassigned strings without manufacturing an execution-plan topology.

    With a tolerance (S14b), a string whose modules agree within it is one state, and strings whose orientations stay
    within it of a cluster's members share that cluster's key, as the execution plan would group them on one MPPT."""
    modules = {m["module_instance_id"]: m for m in scene.get("module_instances", [])}
    fields = {f["pv_field_id"]: f for f in scene.get("pv_fields", [])}
    surfaces = {s["surface_id"]: s for s in scene.get("surfaces", [])}
    result = {}
    clusters: list[dict[str, Any]] = []
    for string in strings:
        ids = string.get("module_instance_ids") or []
        states = set()
        orientations: list[tuple[float, float]] = []
        for mid in ids:
            module = modules[mid]
            field = fields[module["pv_field_id"]]
            if field.get("field_kind") == "explicit_layout":
                from geometry.pvfield.explicit import table_for_module
                mount = table_for_module(module, field)
                support = surfaces.get(mount.get("support_surface_id"))
                if mount.get("support_surface_id") is not None and support is None:
                    raise ValueError(f"Module {mid}: explicit support is missing")
            else:
                support = surfaces[field["support_surface_id"]]
            state, _ = module_execution_signature(module, field,
                support, numerical_options or {"albedo": .20}, "", len(ids))
            states.add(state)
            orientations.append((state[3], state[4]))
        if len(states) != 1 and orientation_tolerance_deg is not None:
            merged = _merged_state(states, orientations, orientation_tolerance_deg)
            if merged is not None:
                states = {merged[0]}
        if len(states) != 1:
            raise ValueError(f"String {string['string_id']} combines different module/orientation states; create homogeneous strings before auto-assignment.")
        state = next(iter(states))
        if orientation_tolerance_deg is None:
            result[string["string_id"]] = state[1:]
            continue
        rest = (state[1], state[2], state[5])
        cluster = next((c for c in clusters if c["rest"] == rest and all(
            normal_angle_deg(o, p) <= orientation_tolerance_deg for o in c["orientations"] for p in orientations)), None)
        if cluster is None:
            cluster = {"rest": rest, "key": state[1:], "orientations": []}
            clusters.append(cluster)
        cluster["orientations"].extend(sorted(set(orientations)))
        result[string["string_id"]] = cluster["key"]
    return result


def _legacy_execution_plan(
    scene: Mapping[str, Any],
    electrical: Mapping[str, Any],
    *,
    numerical_options: Mapping[str, Any] | None = None,
    compiled_shading_geometry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic derived execution groups.

    The plan is intentionally richer than the legacy worker. Multiple groups are
    valid if they are electrically separable by MPPT. Multiple distinct groups
    sharing one MPPT are marked electrically coupled and remain unsupported
    until a higher-fidelity electrical model is introduced.
    """
    numerical = dict(numerical_options or {})
    module_instances = {
        str(item["module_instance_id"]): item
        for item in scene.get("module_instances", [])
    }
    pv_fields = {
        str(item["pv_field_id"]): item
        for item in scene.get("pv_fields", [])
    }
    surfaces = {
        str(item["surface_id"]): item
        for item in scene.get("surfaces", [])
    }
    enabled_inverters = {
        str(item["inverter_instance_id"]): item
        for item in electrical.get("inverter_instances", [])
        if item.get("enabled") is True
    }
    enabled_mppts = {
        str(item["mppt_instance_id"]): item
        for item in electrical.get("mppt_instances", [])
        if item.get("enabled") is True
    }
    enabled_strings = sorted(
        (
            item
            for item in electrical.get("strings", [])
            if item.get("enabled") is True
        ),
        key=lambda item: str(item.get("string_id", "")),
    )
    receiver_by_module, compiled_geometry_hash = _receiver_map(
        compiled_shading_geometry
    )

    findings: list[dict[str, Any]] = []
    group_records: dict[tuple[Any, ...], dict[str, Any]] = {}
    entries: list[dict[str, Any]] = []
    tolerance = orientation_tolerance_deg(electrical)
    mppt_to_group_signatures: dict[str, set[tuple[Any, ...]]] = {}

    for string in enabled_strings:
        string_id = str(string.get("string_id", ""))
        module_ids = [str(value) for value in string.get("module_instance_ids", [])]
        target_mppt_id = string.get("target_mppt_instance_id")
        if not module_ids:
            findings.append(
                _finding(
                    "error",
                    "execution_group_empty_string",
                    string_id,
                    "Enabled string contains no module instances.",
                )
            )
            continue
        if target_mppt_id is None:
            findings.append(
                _finding(
                    "error",
                    "execution_group_string_unassigned",
                    string_id,
                    "Enabled string has no target MPPT.",
                )
            )
            continue
        target_mppt_id = str(target_mppt_id)
        mppt = enabled_mppts.get(target_mppt_id)
        if mppt is None:
            findings.append(
                _finding(
                    "error",
                    "execution_group_mppt_unresolved",
                    string_id,
                    "String target MPPT is missing or disabled.",
                    context={"target_mppt_instance_id": target_mppt_id},
                )
            )
            continue

        inverter_id = str(mppt.get("inverter_instance_id") or "")
        inverter = enabled_inverters.get(inverter_id)
        if inverter is None:
            findings.append(
                _finding(
                    "error",
                    "execution_group_inverter_unresolved",
                    target_mppt_id,
                    "MPPT references a missing or disabled inverter.",
                    context={"inverter_instance_id": inverter_id},
                )
            )
            continue

        module_states: set[tuple[Any, ...]] = set()
        module_details: list[dict[str, Any]] = []
        string_albedo_sources: set[str] = set()
        for module_id in module_ids:
            instance = module_instances.get(module_id)
            if instance is None or instance.get("enabled") is not True:
                findings.append(
                    _finding(
                        "error",
                        "execution_group_module_unresolved",
                        module_id,
                        "String references a missing or disabled module.",
                        context={"string_id": string_id},
                    )
                )
                continue
            field_id = str(instance.get("pv_field_id") or "")
            field = pv_fields.get(field_id)
            if field is None:
                findings.append(
                    _finding(
                        "error",
                        "execution_group_field_unresolved",
                        field_id,
                        "Module references a missing PV field.",
                        context={
                            "string_id": string_id,
                            "module_instance_id": module_id,
                        },
                    )
                )
                continue
            if field.get("field_kind") == "explicit_layout":
                from geometry.pvfield.explicit import table_for_module
                try:
                    mount = table_for_module(instance, field)
                except (ValueError, KeyError, TypeError) as exc:
                    findings.append(_finding("error", "execution_group_field_unresolved", field_id,
                        str(exc), context={"string_id": string_id, "module_instance_id": module_id}))
                    continue
                surface_id = mount.get("support_surface_id")
            else:
                surface_id = str(field.get("support_surface_id") or "")
            surface = surfaces.get(surface_id)
            if surface is None and not (field.get("field_kind") == "explicit_layout" and surface_id is None):
                findings.append(
                    _finding(
                        "error",
                        "execution_group_surface_unresolved",
                        surface_id,
                        "PV field references a missing support surface.",
                        context={
                            "string_id": string_id,
                            "module_instance_id": module_id,
                            "pv_field_id": field_id,
                        },
                    )
                )
                continue
            try:
                state, albedo_source = module_execution_signature(
                    instance, field, surface, numerical, inverter_id, len(module_ids))
                _, module_revision_id, _, tilt, azimuth, albedo = state
            except Exception as exc:
                findings.append(
                    _finding(
                        "error",
                        "execution_group_irradiance_state_invalid",
                        module_id,
                        str(exc),
                        context={"string_id": string_id, "pv_field_id": field_id},
                    )
                )
                continue

            module_states.add(state)
            string_albedo_sources.add(albedo_source)
            module_details.append(
                {
                    "module_instance_id": module_id,
                    "pv_field_id": field_id,
                    "support_surface_id": surface_id,
                    "receiver_id": receiver_by_module.get(module_id),
                    "module_revision_id": module_revision_id,
                    "tilt_deg": tilt,
                    "azimuth_deg": azimuth,
                    "albedo": albedo,
                    "albedo_source": albedo_source,
                }
            )

        if any(
            item["code"] in {
                "execution_group_module_unresolved",
                "execution_group_field_unresolved",
                "execution_group_surface_unresolved",
                "execution_group_irradiance_state_invalid",
            }
            and item["context"].get("string_id") == string_id
            for item in findings
        ):
            continue

        orientation_merge = None
        if len(module_states) != 1 and tolerance is not None:
            merged = _merged_state(module_states, [(d["tilt_deg"], d["azimuth_deg"]) for d in module_details], tolerance)
            if merged is not None:
                module_states, orientation_merge = {merged[0]}, merged[1]
        if len(module_states) != 1:
            findings.append(
                _finding(
                    "error",
                    "execution_group_string_spans_irradiance_states",
                    string_id,
                    "One electrical string spans more than one module/orientation/"
                    "albedo state and cannot be separated geometrically without "
                    "series-string electrical coupling.",
                    context={
                        "state_count": len(module_states),
                        "module_states": [
                            {
                                "inverter_instance_id": state[0],
                                "module_revision_id": state[1],
                                "modules_in_series": state[2],
                                "tilt_deg": state[3],
                                "azimuth_deg": state[4],
                                "albedo": state[5],
                            }
                            for state in sorted(module_states)
                        ],
                    },
                )
            )
            continue

        entries.append({
            "string_id": string_id,
            "signature": next(iter(module_states)),
            "inverter": inverter,
            "inverter_id": inverter_id,
            "mppt_id": target_mppt_id,
            "mppt_index": int(mppt["index"]),
            "module_ids": module_ids,
            "module_details": module_details,
            "albedo_sources": string_albedo_sources,
            "orientation_merge": orientation_merge,
        })

    # S14b: strings on one MPPT whose orientations agree within the tolerance run as one group.
    if tolerance is not None:
        by_mppt: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            by_mppt.setdefault(entry["mppt_id"], []).append(entry)
        for mppt_entries in by_mppt.values():
            signatures = {entry["signature"] for entry in mppt_entries}
            if len(signatures) < 2:
                continue
            orientations = [(d["tilt_deg"], d["azimuth_deg"]) for entry in mppt_entries for d in entry["module_details"]]
            merged = _merged_state(signatures, orientations, tolerance)
            if merged is None:
                continue
            for entry in mppt_entries:
                entry["signature"], entry["orientation_merge"] = merged

    for entry in entries:
        signature = entry["signature"]
        (
            _,
            module_revision_id,
            modules_in_series,
            tilt,
            azimuth,
            albedo,
        ) = signature
        record = group_records.setdefault(
            signature,
            {
                "signature": signature,
                "inverter_instance_id": entry["inverter_id"],
                "inverter_definition_revision_id": str(
                    entry["inverter"].get("inverter_definition_revision_id") or ""
                ),
                "module_revision_id": module_revision_id,
                "modules_in_series": modules_in_series,
                "surface_tilt_deg": tilt,
                "surface_azimuth_deg": azimuth,
                "albedo": albedo,
                "albedo_sources": set(),
                "string_ids": [],
                "module_instance_ids": [],
                "receiver_ids": [],
                "missing_receiver_module_ids": [],
                "pv_field_ids": set(),
                "support_surface_ids": set(),
                "mppt_instance_ids": set(),
                "mppt_indices": set(),
                "orientation_merges": [],
            },
        )
        record["string_ids"].append(entry["string_id"])
        record["albedo_sources"].update(entry["albedo_sources"])
        record["module_instance_ids"].extend(entry["module_ids"])
        if entry["orientation_merge"] is not None:
            record["orientation_merges"].append(entry["orientation_merge"])
        for detail in entry["module_details"]:
            record["pv_field_ids"].add(detail["pv_field_id"])
            if detail["support_surface_id"] is not None:
                record["support_surface_ids"].add(detail["support_surface_id"])
            if detail["receiver_id"] is None:
                record["missing_receiver_module_ids"].append(
                    detail["module_instance_id"]
                )
            else:
                record["receiver_ids"].append(detail["receiver_id"])
        record["mppt_instance_ids"].add(entry["mppt_id"])
        record["mppt_indices"].add(entry["mppt_index"])
        mppt_to_group_signatures.setdefault(entry["mppt_id"], set()).add(signature)

    groups: list[dict[str, Any]] = []
    for signature, record in group_records.items():
        payload = {
            "inverter_instance_id": record["inverter_instance_id"],
            "inverter_definition_revision_id": record[
                "inverter_definition_revision_id"
            ],
            "module_revision_id": record["module_revision_id"],
            "modules_in_series": record["modules_in_series"],
            "surface_tilt_deg": record["surface_tilt_deg"],
            "surface_azimuth_deg": record["surface_azimuth_deg"],
            "albedo": record["albedo"],
            "albedo_sources": sorted(record["albedo_sources"]),
            "string_ids": sorted(record["string_ids"]),
            "module_instance_ids": sorted(record["module_instance_ids"]),
            "receiver_ids": sorted(set(record["receiver_ids"])),
            "missing_receiver_module_ids": sorted(
                set(record["missing_receiver_module_ids"])
            ),
            "pv_field_ids": sorted(record["pv_field_ids"]),
            "support_surface_ids": sorted(record["support_surface_ids"]),
            "mppt_instance_ids": sorted(record["mppt_instance_ids"]),
            "mppt_indices": sorted(record["mppt_indices"]),
        }
        if record["orientation_merges"]:
            sources = sorted({tuple(o) for merge in record["orientation_merges"] for o in merge["source_orientations"]})
            payload["orientation_merge"] = {
                "tolerance_deg": record["orientation_merges"][0]["tolerance_deg"],
                "max_normal_angle_deg": max(merge["max_normal_angle_deg"] for merge in record["orientation_merges"]),
                "source_orientations": [list(o) for o in sources],
                "representative": "module_weighted_mean_normal",
            }
        group_hash = _canonical_hash(payload)
        payload["execution_group_id"] = f"execgrp:{group_hash[:16]}"
        payload["execution_group_payload_sha256"] = group_hash
        groups.append(payload)

    groups.sort(key=lambda item: item["execution_group_id"])

    heterogeneous_mppts = sorted(
        mppt_id
        for mppt_id, signatures in mppt_to_group_signatures.items()
        if len(signatures) > 1
    )
    if heterogeneous_mppts:
        findings.append(
            _finding(
                "error",
                "execution_group_mppt_heterogeneous",
                None,
                "One or more MPPTs contain strings from multiple execution "
                "groups. Their IV interaction is not representable by the "
                "Phase-5 geometry-only electrical boundary.",
                context={"mppt_instance_ids": heterogeneous_mppts},
            )
        )

    findings.sort(
        key=lambda item: (
            {"error": 0, "warning": 1, "info": 2}[item["severity"]],
            item["code"],
            item["entity_id"] or "",
            item["message"],
        )
    )

    has_error = any(item["severity"] == "error" for item in findings)
    if has_error:
        execution_class = (
            "electrically_coupled_heterogeneous"
            if heterogeneous_mppts
            else "invalid"
        )
    elif len(groups) <= 1:
        execution_class = "homogeneous_single_group"
    else:
        execution_class = "separable_multi_group"

    plan_payload = {
        "source_scene_revision_id": str(scene.get("revision_id") or ""),
        "source_electrical_revision_id": str(
            electrical.get("electrical_revision_id") or ""
        ),
        "compiled_geometry_hash": compiled_geometry_hash,
        "execution_class": execution_class,
        "groups": groups,
        "heterogeneous_mppt_instance_ids": heterogeneous_mppts,
    }
    plan_hash = _canonical_hash(plan_payload)
    return {
        "schema_name": "SimulationExecutionGroupPlan",
        "schema_version": "0.1",
        "plan_version": EXECUTION_GROUP_PLAN_VERSION,
        "builder_id": EXECUTION_GROUP_BUILDER_ID,
        "builder_version": EXECUTION_GROUP_BUILDER_VERSION,
        "authority": "derived_execution_only",
        "source_scene_revision_id": plan_payload["source_scene_revision_id"],
        "source_electrical_revision_id": plan_payload[
            "source_electrical_revision_id"
        ],
        "compiled_geometry_hash": compiled_geometry_hash,
        "execution_plan_id": f"execution-plan:{plan_hash[:16]}",
        "execution_plan_payload_sha256": plan_hash,
        "execution_class": execution_class,
        "group_count": len(groups),
        "groups": groups,
        "heterogeneous_mppt_instance_ids": heterogeneous_mppts,
        "legacy_homogeneous_backend_compatible": (
            execution_class == "homogeneous_single_group"
            and len(groups) == 1
        ),
        "finding_count": len(findings),
        "findings": findings,
    }


def execution_units(plan):
    """Optical calculation units, retaining the legacy order for unmixed plans."""
    return [*plan.get("groups", []), *plan.get("mixed_orientation", {}).get("classes", [])]


def circuit_units(plan):
    """Physical wiring references, never an electrical circuit per optical class."""
    classes = {c["execution_group_id"]:c for c in plan.get("mixed_orientation",{}).get("classes",[])}
    return [*plan.get("groups",[]), *[{"module_revision_id":classes[next(iter(m["strings"][0]["composition"]))]["module_revision_id"],
        "modules_in_series":m["modules_in_series"],"mppt_instance_ids":[m["mppt_instance_id"]]}
        for m in plan.get("mixed_orientation",{}).get("mppts",[])]]


def build_simulation_execution_plan(scene, electrical, *, numerical_options=None, compiled_shading_geometry=None, detailed=False):
    old = _legacy_execution_plan(scene, electrical, numerical_options=numerical_options,
                                 compiled_shading_geometry=compiled_shading_geometry)
    if detailed:
        # Detailed requests and their fallbacks retain the pre-USE5 plan.
        return old
    coupling_codes = {"execution_group_mppt_heterogeneous", "execution_group_string_spans_irradiance_states"}
    if not any(f["code"] in coupling_codes for f in old["findings"]):
        return old
    # Structural errors retain their original refusal and excluded-module accounting.
    if any(f["severity"] == "error" and f["code"] not in coupling_codes for f in old["findings"]):
        return old
    strings = sorted((s for s in electrical.get("strings", []) if s.get("enabled") is True),
                     key=lambda s: s["string_id"])
    coupled = set(old["heterogeneous_mppt_instance_ids"])
    rejected = {f["entity_id"] for f in old["findings"] if f["code"] == "execution_group_string_spans_irradiance_states"}
    coupled.update(s["target_mppt_instance_id"] for s in strings if s["string_id"] in rejected)
    modules = {m["module_instance_id"]: m for m in scene.get("module_instances", [])}
    fields = {f["pv_field_id"]: f for f in scene.get("pv_fields", [])}
    surfaces = {f["surface_id"]: f for f in scene.get("surfaces", [])}
    mppts = {m["mppt_instance_id"]: m for m in electrical.get("mppt_instances", [])}
    inverters = {i["inverter_instance_id"]: i for i in electrical.get("inverter_instances", [])}
    for mid in sorted(coupled):
        selected = [s for s in strings if s["target_mppt_instance_id"] == mid]
        revisions = {modules[m]["module_definition_revision_id"] for s in selected for m in s["module_instance_ids"]}
        if len(revisions) != 1 or len({len(s["module_instance_ids"]) for s in selected}) != 1:
            old["findings"].append(_finding("error", "execution_group_use5c_required", mid,
                "Mixed module types or string lengths require USE5c; use one module type and one string length per MPPT."))
            old["finding_count"] = len(old["findings"])
            return old
    filtered = {**electrical, "strings": [s for s in electrical.get("strings", []) if s.get("target_mppt_instance_id") not in coupled]}
    plan = _legacy_execution_plan(scene, filtered, numerical_options=numerical_options,
                                  compiled_shading_geometry=compiled_shading_geometry)
    receivers, _ = _receiver_map(compiled_shading_geometry)
    tolerance = orientation_tolerance_deg(electrical)
    classes, composition = [], {}
    for string in strings:
        mid = string["target_mppt_instance_id"]
        if mid not in coupled:
            continue
        iid = mppts[mid]["inverter_instance_id"]
        counts = {}
        for module_id in string["module_instance_ids"]:
            module = modules[module_id]
            field = fields[module["pv_field_id"]]
            if field.get("field_kind") == "explicit_layout":
                from geometry.pvfield.explicit import table_for_module
                support_id = table_for_module(module, field).get("support_surface_id")
            else:
                support_id = field["support_surface_id"]
            state, source = module_execution_signature(module, field, surfaces.get(support_id), numerical_options or {}, iid, 1)
            rest, orientation = (state[0], state[1], state[5]), (state[3], state[4])
            cluster = next((c for c in classes if c["rest"] == rest and all(
                (o == orientation if tolerance is None else normal_angle_deg(o, orientation) <= tolerance)
                for o in c["orientations"])), None)
            if cluster is None:
                cluster = {"rest": rest, "orientations": [], "members": [], "sources": set(), "fields": set(), "surfaces": set()}
                classes.append(cluster)
            cluster["orientations"].append(orientation)
            cluster["members"].append(module_id)
            cluster["sources"].add(source)
            cluster["fields"].add(module["pv_field_id"])
            if support_id is not None:
                cluster["surfaces"].add(support_id)
            index = classes.index(cluster)
            counts[index] = counts.get(index, 0) + 1
        composition[string["string_id"]] = counts
    payloads = []
    for cluster in classes:
        iid, revision, albedo = cluster["rest"]
        tilt, azimuth = cluster["orientations"][0]
        if tolerance is not None:
            states = {(iid, revision, 1, t, a, albedo) for t, a in cluster["orientations"]}
            merged = _merged_state(states, cluster["orientations"], tolerance)
            if merged is not None:
                tilt, azimuth = merged[0][3:5]
        payload = {"inverter_instance_id": iid,
            "inverter_definition_revision_id": inverters[iid]["inverter_definition_revision_id"],
            "module_revision_id": revision, "surface_tilt_deg": tilt, "surface_azimuth_deg": azimuth,
            "albedo": albedo, "albedo_sources": sorted(cluster["sources"]),
            "module_instance_ids": cluster["members"],
            "receiver_ids": sorted({receivers[m] for m in cluster["members"] if m in receivers}),
            "missing_receiver_module_ids": [m for m in cluster["members"] if m not in receivers],
            "pv_field_ids": sorted(cluster["fields"]), "support_surface_ids": sorted(cluster["surfaces"])}
        digest = _canonical_hash(payload)
        payload.update(execution_group_id="orientation-class:" + digest[:16], execution_group_payload_sha256=digest)
        payloads.append(payload)
    physical = []
    for mid in sorted(coupled):
        m = mppts[mid]
        selected = [s for s in strings if s["target_mppt_instance_id"] == mid]
        physical.append({"mppt_instance_id": mid, "inverter_instance_id": m["inverter_instance_id"],
            "mppt_index": m["index"], "modules_in_series": len(selected[0]["module_instance_ids"]),
            "strings": [{"string_id": s["string_id"], "module_instance_ids": s["module_instance_ids"],
                "composition": {payloads[c]["execution_group_id"]: n for c, n in composition[s["string_id"]].items()}}
                for s in selected]})
    plan.update(execution_class="mixed_orientation_coupled", legacy_homogeneous_backend_compatible=False,
        heterogeneous_mppt_instance_ids=sorted(coupled), mixed_orientation={
            "model_id": "rawibumi.mixed_orientation.v0.1", "classes": payloads, "mppts": physical})
    digest = _canonical_hash({k: plan[k] for k in ("source_scene_revision_id", "source_electrical_revision_id",
        "compiled_geometry_hash", "execution_class", "groups", "heterogeneous_mppt_instance_ids", "mixed_orientation")})
    plan.update(execution_plan_payload_sha256=digest, execution_plan_id="execution-plan:" + digest[:16])
    return plan


def standard_execution_scope_findings(scene, electrical, plan, *, numerical_options=None):
    """Shared scope refusals for the separable standard adapter and readiness."""
    findings = []
    inverters = {str(i['inverter_instance_id']): i for i in electrical.get('inverter_instances', []) if i.get('enabled') is True}
    mppts = {str(m['mppt_instance_id']): m for m in electrical.get('mppt_instances', [])}
    for mppt_id in ([] if plan.get('mixed_orientation') else plan.get('heterogeneous_mppt_instance_ids', [])):
        mppt = mppts[mppt_id]
        iid = str(mppt['inverter_instance_id'])
        name = str(inverters.get(iid, {}).get('name') or iid)
        mppt_name = str(mppt.get('name') or mppt['index'])
        groups = [g for g in plan['groups'] if mppt_id in g['mppt_instance_ids']]
        findings.append({'rule_id': 'SIMULATION_SCOPE_MIXED_STRINGS_ON_ONE_MPPT',
            'entity_id': mppt_id,
            'message': f'MPPT {mppt_name} on inverter {name} combines strings with different orientation, module or length. Put each kind of string on its own MPPT.',
            'context': {'mppt_instance_id': mppt_id, 'mppt_name': mppt_name,
                'inverter_instance_id': iid, 'inverter_name': name, 'groups': groups}})
    used = {g['inverter_instance_id'] for g in execution_units(plan)}
    for iid, inverter in sorted(inverters.items()):
        if iid not in used:
            name = str(inverter.get('name') or iid)
            findings.append({'rule_id': 'SIMULATION_INVERTER_HAS_NO_SIMULATED_STRINGS',
                'entity_id': iid, 'message': f'Inverter {name} has no simulated strings; assign strings to it or disable it.',
                'context': {'inverter_instance_id': iid, 'inverter_name': name}})
    if not inverters:
        findings.append({'rule_id': 'SIMULATION_NO_ENABLED_INVERTER', 'entity_id': None,
                         'message': 'Enable an inverter and assign strings to it.', 'context': {}})
    multi = len(inverters) > 1 or len(execution_units(plan)) > 1
    resistance = ((numerical_options or {}).get('losses') or {}).get('dc_array_resistance_ohm', 0)
    if multi and float(resistance) != 0:
        findings.append({'rule_id': 'SIMULATION_SCOPE_MULTI_GROUP_DC_RESISTANCE', 'entity_id': None,
            'message': 'Multi-group simulation requires zero global DC-array resistance; use the per-circuit wiring settings instead.',
            'context': {'dc_array_resistance_ohm': resistance}})
    if numerical_options is not None:
        from engine.losses.settings import assert_compatible_wiring_modes
        try:
            assert_compatible_wiring_modes(per_circuit="loss_settings" in numerical_options,
                global_resistance_ohm=resistance)
        except ValueError as exc:
            findings.append({'rule_id': 'LOSS_SETTINGS_DC_WIRING_MODE_CONFLICT', 'entity_id': None,
                'message': str(exc), 'context': {'dc_array_resistance_ohm': resistance}})
    return findings


def detailed_inverter_scope_finding(scene, electrical):
    """Reject multi-inverter detailed requests before either fallback/dispatch path."""
    inverters = [i for i in electrical.get('inverter_instances', []) if i.get('enabled') is True]
    if len(inverters) <= 1:
        return None
    names = [str(i.get('name') or i['inverter_instance_id']) for i in inverters]
    plan = build_simulation_execution_plan(scene, electrical, numerical_options={'albedo': .20}, detailed=True)
    return {'rule_id': 'SIMULATION_SCOPE_DETAILED_SHADING_SINGLE_INVERTER',
        'message': 'Detailed electrical shading supports one enabled inverter. This design has ' + ', '.join(names) + '. Select the standard shading path or use one inverter.',
        'entity_id': str(electrical.get('electrical_revision_id') or ''),
        'context': {'inverters': [{'inverter_instance_id': i['inverter_instance_id'], 'name': n} for i,n in zip(inverters,names)], 'groups': plan['groups']}}
