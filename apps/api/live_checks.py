"""S14a live string checks: the engine's design validation, regrouped per string for the browser (TopologyChecks).

The checks come from `validation.engineering.validate_engineering_design` (Phase 4.7) at its configured design
cell temperatures, the same call the execution readiness makes; the browser only shows them. `vmp_v` is the string's
Vmp at STC reference conditions and `window_v` the MPPT operating window, for orientation on screen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from components.design_integration import inverter_design_snapshot

from .orientation_policy import overrides as orientation_overrides

CODES = ("voltage_window", "max_voltage", "current", "unequal_lengths", "orientation", "inputs", "pairing")
_WINDOW = ("STRING_VMPP_MIN_TEMP_OUTSIDE_MPPT_WINDOW", "STRING_VMPP_MAX_TEMP_OUTSIDE_MPPT_WINDOW")
_WINDOW_NEAR = ("STRING_VMPP_MIN_TEMP_FALLBACK_UNCERTAINTY_NEAR_MPPT_WINDOW", "STRING_VMPP_MAX_TEMP_FALLBACK_UNCERTAINTY_NEAR_MPPT_WINDOW")
_MAX_VOLTAGE = ("STRING_VOC_EXCEEDS_INVERTER_MAX_DC", "STRING_VOC_EXCEEDS_MODULE_SYSTEM_VOLTAGE")
_CURRENT = ("MPPT_OPERATING_CURRENT_EXCEEDED", "MPPT_SHORT_CIRCUIT_CURRENT_EXCEEDED")
_CURRENT_UNKNOWN = ("MPPT_OPERATING_CURRENT_LIMIT_UNAVAILABLE", "MPPT_SHORT_CIRCUIT_CURRENT_LIMIT_UNAVAILABLE")


def _check(code: str, state: str, message: str) -> dict[str, str]:
    return {"code": code, "state": state, "message": message}


def _number(value: Any) -> str:
    return f"{value:.1f}" if isinstance(value, float) and abs(value) < 100 else f"{value:.0f}" if isinstance(value, (int, float)) else str(value)


def _message(finding: dict[str, Any]) -> str:
    """The engine's message plus its measured value, limit and temperature condition, when it gives them."""
    measured, limit, unit = finding.get("measured_value"), finding.get("limit_value"), finding.get("unit") or ""
    parts = []
    sep = "" if unit == "°" else " "
    if isinstance(measured, (int, float)) and not isinstance(measured, bool):
        parts.append(f"{_number(measured)}{sep}{unit}".strip())
    if isinstance(limit, dict) and any(limit.get(k) is not None for k in ("minimum_v", "maximum_v")):
        parts.append(f"window {_number(limit.get('minimum_v') if limit.get('minimum_v') is not None else '–')}–"
                     f"{_number(limit.get('maximum_v') if limit.get('maximum_v') is not None else '–')} {unit}".strip())
    elif isinstance(limit, (int, float)) and not isinstance(limit, bool):
        parts.append(f"limit {_number(limit)}{sep}{unit}".strip())
    condition = (finding.get("context") or {}).get("temperature_condition")
    if condition:
        parts.append(str(condition).replace("_", " "))
    return f"{finding['message']} ({'; '.join(parts)})" if parts else finding["message"]


def _first(findings: dict[str, dict[str, Any]], rules: tuple[str, ...]) -> dict[str, Any] | None:
    return next((findings[r] for r in rules if r in findings), None)


def _configuration(design: dict[str, Any] | None = None) -> dict[str, Any]:
    from .study import _validation_configuration
    return _validation_configuration(design)


def basis(configuration: dict[str, Any] | None = None) -> str:
    c = configuration or _configuration()
    angle = "between module normals" if c.get("orientation_comparison") == "normal_angle" else "in tilt and azimuth"
    return (f"Engine design validation at {c['minimum_cell_temperature_c']:g} °C and {c['maximum_cell_temperature_c']:g} °C "
            f"cell temperature, orientation tolerance {c['orientation_tolerance_deg']:g}° {angle}; Vmp shown at STC.")


def validate_design(bundle: dict[str, Any]) -> dict[str, Any]:
    """The validation call the execution readiness makes, on a snapshot of the current electrical design."""
    from validation.engineering import validate_engineering_design
    from .study import BrowserStudyService

    electrical = BrowserStudyService._simulation_electrical_snapshot(bundle["electrical_design"], project_revision_id="browser-live-checks",
                                                                     snapshot_id="browser-live-checks-electrical")
    components = {**bundle["pinned_components"]["modules"], **bundle["pinned_components"]["inverters"]}
    return validate_engineering_design(bundle["scene"], electrical, project_revision_id="browser-live-checks",
                                       component_revisions=components, configuration=_configuration(electrical),
                                       design_validation_report_id="browser-live-checks",
                                       generated_at=datetime.now(timezone.utc).isoformat())


def topology_checks(bundle: dict[str, Any], validate: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Per-string checks for the current design. `validate(bundle)` returns the engine's design validation report."""
    design = bundle["electrical_design"]
    pinned = bundle.get("pinned_components") or {}
    modules = {m["module_instance_id"]: m for m in bundle["scene"].get("module_instances", [])}
    module_defs, inverter_defs = pinned.get("modules") or {}, pinned.get("inverters") or {}
    mppts = {m["mppt_instance_id"]: m for m in design.get("mppt_instances", [])}
    inverters = {i["inverter_instance_id"]: i for i in design.get("inverter_instances", [])}
    field_of = {mid: m.get("pv_field_id") for mid, m in modules.items()}
    field_name = {f["pv_field_id"]: f.get("name") or f["pv_field_id"] for f in bundle["scene"].get("pv_fields", [])}
    accepted = orientation_overrides(design)
    # The checks are informational and part of every project view: a design the validator can't read must still open.
    try:
        findings, failure = (validate or validate_design)(bundle)["findings"], None
    except Exception as exc:  # noqa: BLE001
        findings, failure = [], f"Design validation is unavailable: {exc}"
    by_entity: dict[str, dict[str, dict[str, Any]]] = {}
    for finding in findings:
        by_entity.setdefault(str(finding.get("entity_id")), {}).setdefault(finding["rule_id"], finding)

    def spec(mppt: dict[str, Any] | None) -> dict[str, Any] | None:
        inverter = inverters.get(mppt["inverter_instance_id"]) if mppt else None
        definition = inverter_defs.get(inverter["inverter_definition_revision_id"]) if inverter else None
        if not definition:
            return None
        try:
            snapshot = inverter_design_snapshot(definition)
        except Exception:  # noqa: BLE001 - an unreadable definition only hides the window and input count
            return None
        return next((m for m in snapshot.get("mppts", []) if int(m["index"]) == int(mppt["index"])), None)

    strings = []
    for string in design.get("strings", []):
        string_id, ids = string["string_id"], string.get("module_instance_ids", [])
        vmps = [((module_defs.get(modules.get(mid, {}).get("module_definition_revision_id")) or {}).get("stc") or {}).get("vmp_v") for mid in ids]
        vmp = round(float(sum(vmps)), 6) if ids and all(v is not None for v in vmps) else None
        mppt_id = string.get("target_mppt_instance_id")
        mppt = mppts.get(mppt_id) if mppt_id else None
        limits = spec(mppt)
        low, high = (limits or {}).get("min_operating_voltage_v"), (limits or {}).get("max_operating_voltage_v")
        window = [float(low), float(high)] if low is not None and high is not None else None
        own, shared = by_entity.get(string_id, {}), by_entity.get(str(mppt_id), {}) if mppt_id else {}
        if failure:
            checks = [_check(code, "unavailable", failure) for code in CODES]
        elif mppt is None:
            reason = "Assign the string to an MPPT to check it against the inverter."
            checks = [_check(code, "unavailable", reason) for code in CODES]
            if (hit := _first(own, _MAX_VOLTAGE)) is not None:
                checks[1] = _check("max_voltage", "fail", _message(hit))
        else:
            window_hit, near = _first(own, _WINDOW), _first(own, _WINDOW_NEAR)
            voltage_hit = _first(own, _MAX_VOLTAGE)
            # Isc above its limit is a design error; operating current above its limit is clipped by the inverter (USE-D5).
            isc_hit, current_hit = shared.get(_CURRENT[1]), shared.get(_CURRENT[0])
            current_unknown = _first(shared, _CURRENT_UNKNOWN)
            unequal = shared.get("MPPT_UNEQUAL_STRING_LENGTH")
            orientation = shared.get("MPPT_ORIENTATION_MISMATCH")
            paired = set((inverters.get(mppt["inverter_instance_id"]) or {}).get("paired_pv_field_ids") or [])
            outside = sorted({str(field_name.get(field_of.get(mid), field_of.get(mid))) for mid in ids if field_of.get(mid) not in paired}) if paired else []
            connected = len(mppt.get("connected_string_ids") or [])
            capacity = (limits or {}).get("input_count")
            checks = [
                _check("voltage_window", "fail", _message(window_hit)) if window_hit
                else _check("voltage_window", "warn", _message(near)) if near
                else _check("voltage_window", "pass", "Vmp stays inside the MPPT window at the design temperatures."),
                _check("max_voltage", "fail", _message(voltage_hit)) if voltage_hit
                else _check("max_voltage", "pass", "Voc stays within the inverter and module voltage limits."),
                _check("current", "fail", _message(isc_hit)) if isc_hit
                else _check("current", "warn", _message(current_hit)) if current_hit
                else _check("current", "unavailable", _message(current_unknown)) if current_unknown
                else _check("current", "pass", "The MPPT currents stay within their limits."),
                _check("unequal_lengths", "warn", _message(unequal)) if unequal
                else _check("unequal_lengths", "pass", "Strings on this MPPT have equal lengths."),
                _check("orientation", "pass", f"Mixed orientation accepted by override: {accepted[str(mppt_id)]}")
                if orientation and str(mppt_id) in accepted
                else _check("orientation", "warn", _message(orientation))
                if orientation and string_id in (orientation.get("context") or {}).get("string_ids", [])
                else _check("orientation", "pass", "This string matches the orientation of the MPPT."),
                _check("inputs", "unavailable", "The inverter gives no input count for this MPPT.") if capacity is None
                else _check("inputs", "fail" if connected > capacity else "pass", f"{connected} of {capacity} DC inputs used."),
                _check("pairing", "pass", "The inverter has no paired fields.") if not paired
                else _check("pairing", "warn", f"Modules outside the inverter's paired fields: {', '.join(outside)}.") if outside
                else _check("pairing", "pass", "All modules are in the inverter's paired fields."),
            ]
        strings.append({"string_id": string_id, "vmp_v": vmp, "window_v": window, "checks": checks})
    return {"basis": basis(_configuration(design)), "strings": strings}
