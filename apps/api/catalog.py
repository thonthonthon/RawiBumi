"""Small redistributable reference catalog for Phase 6.0C."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from components.candidates import build_module_candidate
from components.design_integration import inverter_inputs_per_mppt, module_nameplate_w
from components.pan import parse_pan_text
from components.pan.mapper import map_pan
from components.topology_library import (
    build_module_capability_catalog_entry,
    index_module_topologies,
    index_source_records,
)

from .execution_readiness import phase5_inverter_definition_readiness


ROOT = Path(__file__).resolve().parents[2]
REFERENCE_ROOT = ROOT / "components" / "reference"


def _load_json(filename: str) -> dict[str, Any]:
    return json.loads((REFERENCE_ROOT / filename).read_text(encoding="utf-8"))


def _load_uat_module() -> dict[str, Any]:
    source = (REFERENCE_ROOT / "module-uat-550.pan").read_text(encoding="utf-8")
    mapping = map_pan(parse_pan_text(source))
    candidate = build_module_candidate(
        mapping,
        candidate_id="cand-rawibumi-uat-550",
        module_definition_id="mod-rawibumi-uat-550",
        revision_id="mod-rawibumi-uat-550-r1",
        source_id="src-rawibumi-uat-550-pan",
    )
    if candidate.get("definition_schema_ready") is not True:
        raise RuntimeError("RawiBumi UAT module did not map to a valid canonical definition")
    return candidate["canonical_data"]


def load_reference_catalog() -> dict[str, dict[str, dict[str, Any]]]:
    layout_module = _load_json("module-ref-650.json")
    uat_module = _load_uat_module()
    layout_inverter = _load_json("inverter-ref-150k.json")
    uat_inverter = _load_json("inverter-uat-150k.json")
    topology = _load_json("module-topology-uat-550.json")
    topology_source = _load_json("source-topology-uat-550.json")
    topologies = index_module_topologies([topology])
    sources = index_source_records([topology_source])
    return {
        "modules": {
            str(layout_module["revision_id"]): layout_module,
            str(uat_module["revision_id"]): uat_module,
        },
        "inverters": {
            str(layout_inverter["revision_id"]): layout_inverter,
            str(uat_inverter["revision_id"]): uat_inverter,
        },
        "module_topologies": topologies,
        "electrical_parameterization_evidence": {},
        "sources": sources,
    }


def catalog_summaries(catalog=None, *, library_entries=None, pinned_revision_ids=()) -> dict[str, list[dict[str, Any]]]:
    catalog = load_reference_catalog() if catalog is None else catalog
    library_entries = library_entries or {}
    pinned_revision_ids = set(pinned_revision_ids)
    def visible(item):
        return item["revision_id"] in pinned_revision_ids or not (library_entries.get(item["revision_id"], {}).get("library") or {}).get("hidden", False)
    # USE1: a hidden revision completed from datasheet values points at its successor, so projects still on it can switch.
    successors = {(e.get("library") or {}).get("completed_from"): rev for rev, e in library_entries.items()
                  if (e.get("library") or {}).get("completed_from") and not (e.get("library") or {}).get("hidden")}
    def decorate(summary, item, kind):
        entry = library_entries.get(item["revision_id"])
        is_library = entry is not None or item["revision_id"] in pinned_revision_ids
        summary["source"] = "library" if is_library else "reference"
        if entry is not None and (entry.get("library") or {}).get("hidden") and item["revision_id"] in successors:
            summary["superseded_by"] = successors[item["revision_id"]]
        if is_library:
            from .component_library import definition_readiness
            readiness = definition_readiness(kind, item)
            summary.update(synthetic_reference=False, simulation_ready=readiness["ready"])
            if kind == "inverters":
                summary["execution_readiness_findings"] = readiness["findings"]
        return summary
    modules = []
    for item in catalog["modules"].values():
        if not visible(item):
            continue
        electrical_shading = build_module_capability_catalog_entry(
            item, topology_definitions=catalog["module_topologies"]
        )
        modules.append(
            decorate({
                "revision_id": item["revision_id"],
                "manufacturer": item["manufacturer"],
                "model": item["model"],
                "pmp_w": item["stc"]["pmp_w"],
                # D14: the DC nameplate (datasheet nominal power, else STC Pmp), the kWp basis everywhere.
                "nominal_power_w": module_nameplate_w(item),
                "width_m": item["mechanical"]["width_m"],
                "height_m": item["mechanical"]["height_m"],
                "synthetic_reference": True,
                "simulation_ready": bool(
                    item.get("capability_flags", {}).get("detailed_sdm_ready")
                ),
                "electrical_shading": electrical_shading,
            }, item, "modules")
        )
    inverters = [
        decorate({
            "revision_id": item["revision_id"],
            "manufacturer": item["manufacturer"],
            "model": item["model"],
            "nominal_ac_power_w": item["ac_limits"]["nominal_ac_power_w"],
            "mppt_count": (
                len(item.get("mppts") or [])
                if item.get("mppts")
                else int((item.get("mppt_template") or {}).get("count") or 0)
            ),
            "synthetic_reference": True,
            # USE-D4: inputs per MPPT, stated or derived from the total input count.
            **dict(zip(("inputs_per_mppt", "inputs_per_mppt_source"), inverter_inputs_per_mppt(item))),
            "simulation_ready": bool(
                phase5_inverter_definition_readiness(item)["ready"]
            ),
            "execution_readiness_findings": deepcopy(
                phase5_inverter_definition_readiness(item)["findings"]
            ),
        }, item, "inverters")
        for item in catalog["inverters"].values() if visible(item)
    ]
    topology_summaries = [
        {
            "revision_id": item["revision_id"],
            "module_definition_revision_id": item["module_definition_revision_id"],
            "source": "reference",
            "region_resolution": item["region_resolution"],
            "verification_state": item["verification_state"],
            "topology_provenance": item["topology_provenance"],
            "source_ids": deepcopy(item["source_ids"]),
            "bypass_coverage_complete": bool(item["bypass_coverage_complete"]),
            "synthetic_reference": True,
        }
        for item in catalog["module_topologies"].values()
    ]
    return {
        "modules": deepcopy(modules),
        "inverters": deepcopy(inverters),
        "module_topologies": deepcopy(topology_summaries),
    }
