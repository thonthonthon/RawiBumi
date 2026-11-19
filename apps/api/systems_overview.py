"""Read-only systems view; canonical assignment clustering remains the orientation authority."""
from itertools import combinations

from shapely.geometry import Polygon
from shapely.ops import unary_union

from components.design_integration import module_nameplate_w
from engine.simulation.execution_groups import string_compatibility_keys, module_execution_signature
from geometry.pvfield.explicit import table_for_module
from .orientation_policy import tolerance_deg


def systems_overview(bundle):
    scene = bundle["scene"]
    surfaces = {s["surface_id"]: s for s in scene.get("surfaces", [])}
    fields = {f["pv_field_id"]: f for f in scene.get("pv_fields", [])}
    definitions = (bundle.get("pinned_components") or {}).get("modules", {})
    buildings = scene.get("buildings", [])
    if len({b["building_id"] for b in buildings}) != len(buildings):
        raise ValueError("building_id must be unique")
    if any(s.get("group_id") is not None and s["group_id"] not in {b["building_id"] for b in buildings} for s in surfaces.values()):
        raise ValueError("surface group_id must name an existing building")

    def support_ids(field):
        if field.get("field_kind") == "explicit_layout":
            return {t["support_surface_id"] for t in field.get("tables", []) if t.get("support_surface_id")}
        return {field["support_surface_id"]}

    def module_support(module):
        field = fields[module["pv_field_id"]]
        return (table_for_module(module, field).get("support_surface_id") if field.get("field_kind") == "explicit_layout"
                else field["support_surface_id"])

    modules = [m for fid in fields for m in scene.get("module_instances", []) if m["pv_field_id"] == fid and m.get("enabled", True)]
    supports = {m["module_instance_id"]: module_support(m) for m in modules}
    def kwp(items):
        return sum(module_nameplate_w(definitions[m["module_definition_revision_id"]]) for m in items) / 1000.

    entries = []
    def entry(building_id, name, ids):
        items = [m for m in modules if supports[m["module_instance_id"]] in ids]
        return {"building_id": building_id, "name": name, "surface_ids": ids,
                "pv_field_ids": [fid for fid, f in fields.items() if support_ids(f).intersection(ids)],
                "module_count": len(items), "stc_kwp": kwp(items)}
    for b in buildings:
        entries.append(entry(b["building_id"], b["name"], [sid for sid, s in surfaces.items() if s.get("group_id") == b["building_id"]]))
    hosted = {sid for field in fields.values() for sid in support_ids(field)}
    for sid, s in surfaces.items():
        if s.get("group_id") is None and sid in hosted:
            entries.append(entry(None, s.get("name") or sid, [sid]))

    polygons = {sid: Polygon(s["boundary_2d"]["vertices"]) for sid, s in surfaces.items()}
    eligible = sorted(sid for sid, s in surfaces.items() if s.get("usable_for_pv") is not False)
    parent = {sid: sid for sid in eligible}
    def find(sid):
        while parent[sid] != sid:
            parent[sid] = parent[parent[sid]]
            sid = parent[sid]
        return sid
    for a, b in combinations(eligible, 2):
        if polygons[a].distance(polygons[b]) <= 1.0:
            parent[find(b)] = find(a)
    clusters = {}
    for sid in eligible:
        clusters.setdefault(find(sid), []).append(sid)
    suggestions = [{"name": f"Building {i + 1}", "surface_ids": ids,
                    "matches_confirmed": any(e["building_id"] is not None and set(e["surface_ids"]) == set(ids) for e in entries)}
                   for i, ids in enumerate(sorted(clusters.values(), key=lambda ids: ids[0]))]
    threshold = bundle["project"].get("distance_warning_m", 50.)
    footprints = [unary_union([polygons[sid] for sid in e["surface_ids"]]) for e in entries]
    distances = []
    for a, b in combinations(range(len(entries)), 2):
        distance = float(footprints[a].distance(footprints[b]))
        distances.append({"from_index": a, "to_index": b, "distance_m": distance, "over_threshold": distance > threshold})

    tolerance = tolerance_deg(bundle.get("electrical_design") or {})
    representatives = {}
    representative_ids = {}
    for m in modules:
        sid = supports[m["module_instance_id"]]
        signature, _ = module_execution_signature(m, fields[m["pv_field_id"]], surfaces.get(sid), {"albedo": .2}, "", 1)
        representative = representatives.setdefault(signature, m["module_instance_id"])
        representative_ids[m["module_instance_id"]] = representative
    # Identical states add no complete-linkage constraints; cluster each state only once.
    strings = [{"string_id": mid, "module_instance_ids": [mid]} for mid in representatives.values()]
    keys = string_compatibility_keys(scene, strings, orientation_tolerance_deg=tolerance)
    grouped = {}
    for m in modules:
        grouped.setdefault(keys[representative_ids[m["module_instance_id"]]], []).append(m)
    orientations = []
    for items in grouped.values():
        first = items[0]
        sid = supports[first["module_instance_id"]]
        signature, _ = module_execution_signature(first, fields[first["pv_field_id"]], surfaces.get(sid), {"albedo": .2}, "", 1)
        ids = list(dict.fromkeys(supports[m["module_instance_id"]] for m in items))
        orientations.append({"label": f"{signature[3]:.1f}° / {signature[4]:.1f}°",
                             "module_definition_revision_ids": list(dict.fromkeys(m["module_definition_revision_id"] for m in items)),
                             "pv_field_ids": list(dict.fromkeys(m["pv_field_id"] for m in items)),
                             "surface_ids": [sid for sid in ids if sid is not None],
                             "building_ids": list(dict.fromkeys(surfaces.get(sid, {}).get("group_id") for sid in ids)),
                             "module_count": len(items), "stc_kwp": kwp(items)})
    return {"schema_name": "SystemsOverview", "schema_version": "0.1", "buildings": entries,
            "suggested_buildings": suggestions, "distances": distances, "threshold_m": threshold,
            "orientation_groups": orientations, "tolerance_deg": tolerance}
