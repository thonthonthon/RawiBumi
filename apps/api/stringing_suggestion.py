"""USE1 Suggest stringing: an engine-sized MPPT layout for one inverter, verified by the design validation.

Candidates are sized from the validation's own temperature-dependent module envelopes (cold Voc, hot and cold Vmp,
design Isc) against the inverter's limits. The best candidate is applied to a throwaway copy of the project and kept
only when the same design validation the readiness uses reports nothing INVALID for this inverter. An operating
current above the MPPT limit is allowed: the inverter clips it (USE-D5), and the suggestion says so.
"""

from __future__ import annotations

from copy import deepcopy
from heapq import nsmallest
from math import floor, inf
from typing import Any

from components.design_integration import inverter_design_snapshot, inverter_inputs_per_mppt
from validation.engineering.electrical import module_design_state

from .live_checks import validate_design
from .study import _validation_configuration

MAX_VERIFIED_CANDIDATES = 8


def _distribute(strings: int, caps: list[float]) -> list[int]:
    """Round-robin strings over the MPPTs, never above a cap."""
    counts = [0] * len(caps)
    while strings:
        open_ = [i for i, c in enumerate(caps) if counts[i] < c]
        if not open_:
            break
        i = min(open_, key=lambda k: (counts[k], k))
        counts[i] += 1
        strings -= 1
    return counts


def _layouts(lengths: list[int], caps: list[float], modules: int,
             limit: int = MAX_VERIFIED_CANDIDATES) -> list[tuple[tuple, list[list[int]]]]:
    """Ranked per-MPPT layouts (USE3b): one string length everywhere, or two lengths split over the MPPTs.

    Ranked by modules strung, then fewer distinct lengths, then the longest shortest string, then longer strings,
    then balance across MPPTs. Each MPPT carries strings of one length.
    """
    if not lengths or not caps or modules <= 0 or limit <= 0:
        return []
    lengths = list(dict.fromkeys(lengths))
    max_strings = modules // min(lengths)
    # Counts of the two lengths determine used modules; share their DP across every length pair.
    states = {(0, 0, modules, 0): None}
    for cap in caps:
        counts = range(int(min(cap, max_strings)), 0, -1)
        choices = [(c, 0, c, 1) for c in counts] + [(0, c, c, 2) for c in counts] + [(0, 0, 0, 0)]
        following = {}
        for (a, b, least, most), node in states.items():
            for da, db, c, bit in choices:
                aa, bb = a + da, b + db
                if aa + bb <= max_strings:
                    state = (aa, bb, min(least, c), max(most, c))
                    if state not in following:
                        following[state] = (node, bit, c)
        states = following

    def candidates():
        for n in lengths:
            counts = _distribute(int(min(modules // n, sum(caps))), caps)
            strings = sum(counts)
            if strings:
                node = None
                for c in counts:
                    node = (node, 1, c)
                yield (-n * strings, 1, -n, -float(n), max(counts) - min(counts)), n, n, node
        for long in lengths:
            for short in lengths:
                if short >= long:
                    continue
                for (a, b, least, most), node in states.items():
                    used = a * long + b * short
                    if a and b and used <= modules:
                        yield (-used, 2, -short, -used / (a + b), most - least), long, short, node

    # Unique lengths and DP states identify unique notations; nsmallest keeps the original stable tie order.
    result = []
    for key, long, short, node in nsmallest(limit, candidates(), key=lambda item: item[0]):
        layout = []
        while node is not None:
            node, bit, c = node
            layout.append([long if bit == 1 else short] * c if c else [0])
        result.append((key, layout[::-1]))
    return result


def _unavailable(reason: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"schema_name": "MpptLayoutSuggestion", "schema_version": "0.1", "status": "no_solution",
            "reasons": [{"code": reason, "message": message}], **extra}


def stringing_limits(definition, module, design, module_count):
    """One temperature-envelope sizing rule for Suggest and the read-only inverter card."""
    snapshot = inverter_design_snapshot(definition)
    specs = snapshot["mppts"]
    try:
        state = module_design_state(module, _validation_configuration(design))
    except ValueError as exc:
        return _unavailable("MODULE_MODEL_UNAVAILABLE", f"The module has no temperature model for sizing: {exc}")
    uv, ui = state.voltage_uncertainty_fraction, state.current_uncertainty_fraction
    voc_cold, vmp_cold = state.voc_min_temp_v * (1 + uv), state.vmp_min_temp_v * (1 + uv)
    vmp_hot, isc = state.vmp_max_temp_v * (1 - uv), state.isc_max_temp_a * (1 + ui)
    absolute = min(float(snapshot["dc_limits"].get("max_dc_voltage_v") or inf), float(state.max_system_voltage_v or inf))
    low = max(float(s.get("min_operating_voltage_v") or 0) for s in specs)
    high = min(float(s.get("max_operating_voltage_v") or inf) for s in specs)
    lengths = [n for n in range(1, module_count + 1) if n * voc_cold <= absolute and n * vmp_hot >= low and n * vmp_cold <= high]
    if not lengths:
        return _unavailable("NO_STRING_LENGTH", "No string length keeps cold Voc under the voltage limit and Vmp inside "
                            "the MPPT window at the design temperatures.")
    inputs, inputs_source = inverter_inputs_per_mppt(definition, int(specs[0]["index"]))
    mppts = []
    caps = []
    for spec in specs:
        mppt_inputs, source = inverter_inputs_per_mppt(definition, int(spec["index"]))
        isc_cap = floor(float(spec["max_short_circuit_current_a"]) / isc) if spec.get("max_short_circuit_current_a") else None
        mppts.append({"index": int(spec["index"]), "inputs": mppt_inputs, "inputs_source": source, "max_strings_by_isc": isc_cap})
        cap = float(mppt_inputs) if mppt_inputs else inf
        if spec.get("max_short_circuit_current_a"):
            cap = min(cap, floor(float(spec["max_short_circuit_current_a"]) / isc))
        caps.append(cap)
    return {"lengths": lengths, "caps": caps, "inputs": inputs, "inputs_source": inputs_source, "mppts": mppts}


def suggest_mppt_layout(service: Any, bundle: dict[str, Any], inverter_instance_id: str,
                        pv_field_ids: list[str] | None = None) -> dict[str, Any]:
    design = bundle["electrical_design"]
    inverter = next((i for i in design["inverter_instances"] if i["inverter_instance_id"] == inverter_instance_id), None)
    if inverter is None:
        raise KeyError(f"inverter not found: {inverter_instance_id}")
    definition = bundle["pinned_components"]["inverters"][inverter["inverter_definition_revision_id"]]
    snapshot = inverter_design_snapshot(definition)
    specs = snapshot["mppts"]
    fields = list(pv_field_ids or inverter.get("paired_pv_field_ids") or [f["pv_field_id"] for f in bundle["scene"].get("pv_fields", [])])
    mine = {m["mppt_instance_id"] for m in design["mppt_instances"] if m["inverter_instance_id"] == inverter_instance_id}
    taken = {mid for s in design.get("strings", []) if s.get("target_mppt_instance_id") and s["target_mppt_instance_id"] not in mine
             for mid in s.get("module_instance_ids", [])}
    pool = [m for m in bundle["scene"].get("module_instances", []) if m["pv_field_id"] in fields and m["module_instance_id"] not in taken]
    if not pool:
        return _unavailable("NO_MODULES", "No free modules in the inverter's PV fields.")
    revisions = {m["module_definition_revision_id"] for m in pool}
    if len(revisions) != 1:
        return _unavailable("MIXED_MODULES", "The fields hold more than one module type; pair the inverter with one type.")
    module = bundle["pinned_components"]["modules"][next(iter(revisions))]
    limits = stringing_limits(definition, module, design, len(pool))
    if limits.get("status") == "no_solution":
        return limits
    lengths, caps = limits["lengths"], limits["caps"]
    inputs, inputs_source = limits["inputs"], limits["inputs_source"]
    candidates = _layouts(lengths, caps, len(pool), limit=MAX_VERIFIED_CANDIDATES)
    if not candidates:
        return _unavailable("ISC_LIMIT", "One string's short-circuit current already exceeds the MPPT limit.")
    # Most modules strung first. Within one module count, layouts that keep the existing strings (Apply reuses those of
    # the right length) come before a restring, which replaces the inverter's own and the free strings in its fields in
    # the same commit as the layout.
    replaceable = sorted(s["string_id"] for s in design.get("strings", [])
                         if (s.get("target_mppt_instance_id") in mine or not s.get("target_mppt_instance_id"))
                         and s.get("module_instance_ids") and all(m in {x["module_instance_id"] for x in pool} for m in s["module_instance_ids"]))
    rejected = []
    shortlist = candidates[:MAX_VERIFIED_CANDIDATES]
    attempts = [(c, replace) for used in sorted({c[0][0] for c in shortlist})
                for replace in (([], replaceable) if replaceable else ([],)) for c in shortlist if c[0][0] == used]
    for (_, layout), replace in attempts:
        strings = [n for mppt in layout for n in mppt if n]
        notation = " ; ".join(",".join(str(n) for n in mppt) for mppt in layout)
        trial = deepcopy(bundle)
        session = service._electrical_session(trial)
        try:
            for string_id in replace:
                session.delete_string(string_id)
            session.apply_mppt_layout(inverter_instance_id, layout, pv_field_ids=fields)
        except ValueError as exc:
            rejected.append({"layout": notation, "rule_ids": [], "reason": str(exc)})
            continue
        trial["electrical_design"] = session.electrical_design
        report = validate_design(trial)
        relevant = {inverter_instance_id, *mine,
                    *(s["string_id"] for s in trial["electrical_design"]["strings"] if s.get("target_mppt_instance_id") in mine)}
        findings = [f for f in report["findings"] if str(f.get("entity_id")) in relevant]
        invalid = [f for f in findings if f["classification"] == "INVALID"]
        if invalid:
            rejected.append({"layout": notation, "rule_ids": sorted({f["rule_id"] for f in invalid})})
            continue
        return {"schema_name": "MpptLayoutSuggestion", "schema_version": "0.1", "status": "suggestion_available",
                "inverter_instance_id": inverter_instance_id, "pv_field_ids": fields, "layout": layout,
                "replace_string_ids": list(replace),
                "string_length": max(strings), "string_lengths": sorted(set(strings), reverse=True),
                "string_count": len(strings), "modules_used": sum(strings), "modules_left": len(pool) - sum(strings),
                "inputs_per_mppt": inputs, "inputs_per_mppt_source": inputs_source,
                "warnings": [{"rule_id": f["rule_id"], "entity_id": f.get("entity_id"), "message": f["message"]}
                             for f in findings if f["classification"] == "WARNING"],
                "basis": "Sized from the design validation's module envelopes; verified by the same validation.",
                "rejected": rejected, "reasons": []}
    return _unavailable("NO_VALID_LAYOUT", "Every sized layout still fails the design validation.", rejected=rejected)
