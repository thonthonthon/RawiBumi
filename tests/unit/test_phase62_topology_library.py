from copy import deepcopy
import json
from pathlib import Path

import pytest

from components.topology_library import (
    index_module_topologies,
    index_source_records,
    resolve_library_electrical_shading_capability,
    resolve_selected_library_assets,
    select_module_topology,
    topology_revisions_for_module,
)

ROOT = Path(__file__).resolve().parents[2]


def _topology():
    return json.loads(
        (ROOT / "components/reference/module-topology-uat-550.json").read_text(
            encoding="utf-8"
        )
    )


def _sources():
    source = json.loads(
        (ROOT / "components/reference/source-topology-uat-550.json").read_text(
            encoding="utf-8"
        )
    )
    parameter_source = {
        **source,
        "source_id": "src-param",
        "title": "Synthetic parameterization test source",
        "filename": None,
        "source_notes": "Synthetic test-only parameterization source.",
    }
    return index_source_records([source, parameter_source])


def _module(revision_id="mod-rawibumi-uat-550-r1"):
    return {
        "schema_name": "ModuleDefinition",
        "schema_version": "0.1",
        "module_definition_id": "mod-rawibumi-uat-550",
        "revision_id": revision_id,
        "manufacturer": "RawiBumi Synthetic",
        "model": "SYN-MOD-550-UAT",
        "verification_state": "reviewed",
        "source_ids": ["src-module"],
        "mechanical": {"width_m": 1.134, "height_m": 2.278},
        "stc": {
            "pmp_w": 550.0,
            "voc_v": 49.9,
            "isc_a": 14.0,
            "vmp_v": 41.96,
            "imp_a": 13.11,
            "reference_irradiance_w_m2": 1000.0,
            "reference_cell_temperature_c": 25.0,
        },
        "temperature_coefficients": {
            "alpha_isc_per_c": 0.00052,
            "beta_voc_per_c": -0.00256,
            "gamma_pmp_per_c": -0.0034,
            "coefficient_basis": "relative",
        },
        "electrical_models": [],
        "limits": {"max_system_voltage_v": 1500.0},
        "capability_flags": {"detailed_sdm_ready": True},
    }


def _resolved_sdm():
    return {
        "schema_name": "ResolvedComponentModel",
        "schema_version": "0.1",
        "resolution_id": "resolved-sdm-r1",
        "component_type": "module",
        "component_definition_id": "mod-rawibumi-uat-550",
        "component_revision_id": "mod-rawibumi-uat-550-r1",
        "status": "resolved",
        "requested_model_id": None,
        "selected_model": {
            "model_id": "module.pvsyst_singlediode.v6",
            "component_type": "module",
            "model_family": "single_diode",
            "fidelity_rank": 300,
            "source_model_type": "pvsyst_singlediode",
            "implementation_status": "validated_contract",
            "description": "Synthetic validated model.",
            "component_model_version": "6.0",
            "parameter_source_path": "electrical_models[pvsyst_singlediode].parameter_set",
            "validation_status": "passed",
        },
        "enabled_refinements": [],
        "unavailable_refinements": [],
        "assumptions": [],
        "warnings": [],
        "source_ids": ["src-module"],
        "capability_snapshot": {"detailed_sdm_ready": True},
    }


def _evidence(scope, *, topology_revision_id="topology-rawibumi-uat-550-r1"):
    suffix = "region" if scope == "region_substring" else "cell"
    return {
        "schema_name": "ElectricalParameterizationEvidence",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "evidence_id": f"evidence-{suffix}",
        "parameterization_scope": scope,
        "parameterization_id": f"param-{suffix}",
        "module_definition_revision_id": "mod-rawibumi-uat-550-r1",
        "module_topology_revision_id": topology_revision_id,
        "model_id": f"parameterization.synthetic.{suffix}",
        "model_version": "0.1",
        "validation_record_id": f"validation-{suffix}",
        "validation_status": "passed",
        "verification_state": "auto_validated",
        "parameterization_provenance": "derived_validated",
        "source_ids": ["src-param"],
        "parameterization_payload_sha256": "a" * 64,
    }


def test_phase62_reference_topology_is_exact_revision_indexed_and_never_inferred():
    indexed = index_module_topologies([_topology()])
    assert topology_revisions_for_module(
        "mod-rawibumi-uat-550-r1", indexed
    ) == ["topology-rawibumi-uat-550-r1"]
    assert topology_revisions_for_module("other-r1", indexed) == []

    assert select_module_topology(
        _module(), indexed, topology_revision_id=None
    ) is None

    with pytest.raises(ValueError):
        select_module_topology(
            _module("other-r1"),
            indexed,
            topology_revision_id="topology-rawibumi-uat-550-r1",
        )


def test_phase62_topology_without_parameterization_does_not_unlock_level2():
    result = resolve_library_electrical_shading_capability(
        _module(),
        topology_definition=_topology(),
        resolved_component_model=_resolved_sdm(),
        source_records=_sources(),
    )
    assert result["detailed_sdm_ready"] is True
    assert result["topology_structurally_valid"] is True
    assert result["bypass_models_ready"] is True
    assert result["region_parameterization_ready"] is False
    assert result["maximum_fidelity_level"] == "level_1_module_approximation"
    assert result["bypass_assumption_ids"] == [
        "assumption-rawibumi-uat-bypass-055v"
    ]


def _half_cell_topology():
    topology = deepcopy(_topology())
    topology["module_topology_id"] = "topology-rawibumi-uat-550-halfcell"
    topology["revision_id"] = "topology-rawibumi-uat-550-halfcell-r1"
    topology["region_resolution"] = "half_cell"
    for region in topology["physical_regions"]:
        region["region_type"] = "half_cell"
    topology["notes"] = (
        "Synthetic half-cell variant used only to prove the Level-3 capability gate; "
        "it is explicitly authored and not inferred from PAN metadata."
    )
    return topology


def test_phase62_explicit_region_evidence_unlocks_level2_and_cell_evidence_level3():
    indexed = index_module_topologies([_topology()])
    evidence = [_evidence("region_substring"), _evidence("cell")]

    level2 = resolve_selected_library_assets(
        _module(),
        topology_definitions=indexed,
        parameterization_evidence=evidence,
        topology_revision_id="topology-rawibumi-uat-550-r1",
        region_parameterization_evidence_id="evidence-region",
        source_records=_sources(),
    )
    # The helper uses the normal component-model resolver, and this synthetic
    # module intentionally contains no validated SDM; therefore it must remain
    # fail-closed. The evidence cannot fabricate SDM readiness.
    assert level2["maximum_fidelity_level"] == "level_0_geometric_only"

    level2_direct = resolve_library_electrical_shading_capability(
        _module(),
        topology_definition=_topology(),
        region_parameterization_evidence=_evidence("region_substring"),
        resolved_component_model=_resolved_sdm(),
        source_records=_sources(),
    )
    assert level2_direct["maximum_fidelity_level"] == "level_2_bypass_substring"

    # The catalog reference uses grouped-cell regions and therefore correctly
    # stops at Level 2 even if cell evidence is supplied. Level 3 requires a
    # separately explicit cell/half-cell topology revision.
    grouped_with_cell_evidence = resolve_library_electrical_shading_capability(
        _module(),
        topology_definition=_topology(),
        region_parameterization_evidence=_evidence("region_substring"),
        cell_parameterization_evidence=_evidence("cell"),
        resolved_component_model=_resolved_sdm(),
        source_records=_sources(),
    )
    assert grouped_with_cell_evidence["maximum_fidelity_level"] == "level_2_bypass_substring"

    cell_topology = _half_cell_topology()
    cell_topology_revision = cell_topology["revision_id"]
    level3_direct = resolve_library_electrical_shading_capability(
        _module(),
        topology_definition=cell_topology,
        region_parameterization_evidence=_evidence(
            "region_substring", topology_revision_id=cell_topology_revision
        ),
        cell_parameterization_evidence=_evidence(
            "cell", topology_revision_id=cell_topology_revision
        ),
        resolved_component_model=_resolved_sdm(),
        source_records=_sources(),
    )
    assert level3_direct["maximum_fidelity_level"] == "level_3_cell_submodule_iv"


def test_phase62_stale_parameterization_evidence_fails_closed():
    stale = deepcopy(_evidence("region_substring"))
    stale["module_definition_revision_id"] = "stale-module-r1"
    result = resolve_library_electrical_shading_capability(
        _module(),
        topology_definition=_topology(),
        region_parameterization_evidence=stale,
        resolved_component_model=_resolved_sdm(),
        source_records=_sources(),
    )
    assert result["region_parameterization_ready"] is False
    assert result["maximum_fidelity_level"] == "level_1_module_approximation"


def test_phase62_dangling_topology_or_parameterization_source_ids_fail_closed():
    with pytest.raises(ValueError, match="SourceRecord"):
        resolve_library_electrical_shading_capability(
            _module(),
            topology_definition=_topology(),
            resolved_component_model=_resolved_sdm(),
            source_records={},
        )

    bad_evidence = _evidence("region_substring")
    bad_evidence["source_ids"] = ["missing-source"]
    with pytest.raises(ValueError, match="SourceRecord"):
        resolve_library_electrical_shading_capability(
            _module(),
            topology_definition=_topology(),
            region_parameterization_evidence=bad_evidence,
            resolved_component_model=_resolved_sdm(),
            source_records=_sources(),
        )
