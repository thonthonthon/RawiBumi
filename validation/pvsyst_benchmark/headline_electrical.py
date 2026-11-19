"""Deterministic integer topology and source-derived loss references, not fitting."""

import numpy as np

from geometry.pvfield.explicit import table_axes, table_rectangle
from engine.inverter.model import evaluate_voltage_dependent_conversion
from .source import SourceError


def balanced_counts(count, parts):
    if type(count) is not int or type(parts) is not int or count < 0 or parts <= 0:
        raise SourceError("invalid integer allocation")
    q, r = divmod(count, parts)
    return [q+int(i < r) for i in range(parts)]


def spatial_module_order(scene, field_id):
    field = next(f for f in scene["pv_fields"] if f["pv_field_id"] == field_id)
    ranked = []
    for table in field["tables"]:
        right, up, _ = table_axes(table["azimuth_deg"], table["tilt_deg"])
        centre = np.mean(table_rectangle(table), axis=0)
        source_id = int(table["table_id"].removeprefix("table-"))
        ranked.append(((-float(np.dot(centre, up)), float(np.dot(centre, right)), source_id), table))
    ids = []
    for _, table in sorted(ranked, key=lambda x: x[0]):
        modules = sorted((m for m in scene["module_instances"]
                          if m["pv_field_id"] == field_id and m["table_id"] == table["table_id"]),
                         key=lambda m: (m["row_index"], m["column_index"], m["module_instance_id"]))
        ids.extend(m["module_instance_id"] for m in modules)
    if len(ids) != len(set(ids)):
        raise SourceError("duplicate placed module")
    return ids


def topology_commands(scene, electrical, plan, field_subarrays, inverter_groups):
    commands, assignments = [], []
    def command(kind, parameters, identity):
        return {"schema_name": "ElectricalTopologyCommand", "schema_version": "0.1",
                "command_id": identity, "command_type": kind, "parameters": parameters}
    total = set()
    for sub in plan.subarrays:
        fid = next(f for f, index in field_subarrays.items() if index == sub["index"])
        ids = spatial_module_order(scene, fid)
        ns, length = sub["strings"], sub["modules_per_string"]
        if len(ids) != ns*length or total.intersection(ids):
            raise SourceError("string/module counts do not reconcile")
        total.update(ids)
        inverters = inverter_groups[sub["index"]]
        if len(inverters) != sub["inverters"]:
            raise SourceError("inverter/sub-array counts do not reconcile")
        offset = 0
        for iid, count in zip(inverters, balanced_counts(ns, len(inverters))):
            mppts = sorted((m for m in electrical["mppt_instances"]
                            if m["inverter_instance_id"] == iid and m["enabled"]),
                           key=lambda m: m["index"])
            if not mppts or count == 0:
                raise SourceError("enabled inverter has no strings or MPPTs")
            for mppt, tracker_count in zip(mppts, balanced_counts(count, len(mppts))):
                for _ in range(tracker_count):
                    sid = f"{plan.label}-A{sub['index']}-S{offset+1:04d}"
                    path = ids[offset*length:(offset+1)*length]
                    commands.append(command("create_string", {"string_id": sid, "module_instance_ids": path}, "create-"+sid))
                    commands.append(command("assign_strings_to_mppt", {"string_ids": [sid], "mppt_instance_id": mppt["mppt_instance_id"]}, "assign-"+sid))
                    assignments.append({"subarray": sub["index"], "string_id": sid,
                                        "module_ids": path, "inverter_id": iid,
                                        "mppt_id": mppt["mppt_instance_id"], "mppt_index": mppt["index"]})
                    offset += 1
        if offset != ns:
            raise SourceError("some source strings were not assigned")
    if total != {m["module_instance_id"] for m in scene["module_instances"] if m["enabled"]}:
        raise SourceError("some placed modules are excluded")
    return commands, assignments


def reference_power(plan, module_definitions, inverter_definition, inverter_groups):
    """PNom DC at STC, unchanged native OND interpolation, before clipping/losses."""
    rows = []
    for sub in plan.subarrays:
        d = module_definitions[sub["module_ref"]]
        nominal = float(d["stc"]["nominal_power_w"])
        voltage = sub["modules_per_string"]*d["stc"]["vmp_v"]
        rated = inverter_definition["ac_limits"]["nominal_ac_power_w"]
        for iid, strings in zip(inverter_groups[sub["index"]], balanced_counts(sub["strings"], sub["inverters"])):
            pdc = nominal*sub["modules_per_string"]*strings
            pac, eta = evaluate_voltage_dependent_conversion(
                inverter_definition["efficiency_model"], dc_power_w=pdc,
                tracker_voltages_v=np.array([voltage]), tracker_powers_w=np.array([pdc]))
            rows.append({"subarray": sub["index"], "inverter_id": iid, "strings": strings,
                         "stc_nameplate_dc_w": pdc, "stc_voltage_v": voltage,
                         "nominal_ac_w": rated, "dc_ac_ratio": pdc/rated,
                         "unclipped_stc_ac_w": pac, "efficiency": eta})
    return {"basis": "PAN PNom; unclipped native OND conversion at STC voltage",
            "reference_power_w": sum(r["unclipped_stc_ac_w"] for r in rows), "inverters": rows}


def loss_patch(plan, bundle, inverter_groups, reference_power_w, plant_loss_fraction):
    for key in ("lid_fraction", "module_mismatch_fraction", "string_mismatch_fraction"):
        if len({s[key] for s in plan.subarrays}) != 1:
            raise SourceError("scalar losses differ between source sub-arrays")
    sub = plan.subarrays[0]
    return {"overrides": {
        "soiling": {"monthly_fractions": [plan.settings["soiling_fraction"]]*12},
        "lid_fraction": sub["lid_fraction"],
        "module_mismatch_fraction": sub["module_mismatch_fraction"],
        "string_mismatch_fraction": sub["string_mismatch_fraction"],
        "annual_degradation_fraction": 0., "operating_year": 1,
        "unavailability_fraction": 0., "ac_wiring_nominal_fraction": 0.,
        "transformer": {"enabled": False},
        "plant_ac_wiring": {"mode": "percent", "loss_fraction": plant_loss_fraction,
                            "reference": "custom", "reference_power_w": reference_power_w},
        "circuit_overrides": {
            "binding": {"electrical_revision_id": bundle["electrical_design"]["electrical_revision_id"]},
            "inverters": {iid: {"dc_wiring_stc_fraction": s["dc_wiring_stc_fraction"],
                                "module_quality_fraction": s["quality_fraction"]}
                          for s in plan.subarrays for iid in inverter_groups[s["index"]]},
            "mppts": {},
        },
    }}
