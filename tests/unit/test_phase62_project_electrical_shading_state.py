import json
from copy import deepcopy
from pathlib import Path

import pytest

from apps.api.catalog import load_reference_catalog
from apps.api.electrical_shading_state import (
    assert_electrical_shading_selection_state,
    ensure_electrical_shading_bundle_state,
    import_project_electrical_shading_asset,
    resolve_project_module_electrical_shading_capability,
    set_project_module_electrical_shading_selection,
)
from shading.electrical import ElectricalShadingContractError


def _bundle():
    return {
        "schema_name": "ProjectWorkspaceBundle",
        "schema_version": "0.1",
        "pinned_components": {"modules": {}, "inverters": {}},
    }


def test_phase62_project_selection_pins_topology_and_source_without_polluting_component_pins():
    catalog = load_reference_catalog()
    bundle = _bundle()
    ensure_electrical_shading_bundle_state(bundle)

    result = set_project_module_electrical_shading_selection(
        bundle,
        catalog,
        module_revision_id="mod-rawibumi-uat-550-r1",
        topology_revision_id="topology-rawibumi-uat-550-r1",
        requested_fidelity="level_0_geometric_only",
    )
    assert result["selection"]["resolved_fidelity"] == "level_0_geometric_only"
    assert "topology-rawibumi-uat-550-r1" in (
        bundle["pinned_electrical_shading_assets"]["module_topologies"]
    )
    assert "src-rawibumi-uat-topology-fixture" in (
        bundle["pinned_electrical_shading_assets"]["sources"]
    )
    assert set(bundle["pinned_components"]) == {"modules", "inverters"}
    assert "mod-rawibumi-uat-550-r1" in bundle["pinned_components"]["modules"]


def test_phase62_project_selection_is_fail_closed_or_explicitly_falls_back():
    catalog = load_reference_catalog()
    bundle = _bundle()

    with pytest.raises(ElectricalShadingContractError):
        set_project_module_electrical_shading_selection(
            bundle,
            catalog,
            module_revision_id="mod-rawibumi-uat-550-r1",
            topology_revision_id="topology-rawibumi-uat-550-r1",
            requested_fidelity="level_2_bypass_substring",
            fallback_policy="fail_closed",
        )

    result = set_project_module_electrical_shading_selection(
        bundle,
        catalog,
        module_revision_id="mod-rawibumi-uat-550-r1",
        topology_revision_id="topology-rawibumi-uat-550-r1",
        requested_fidelity="level_2_bypass_substring",
        fallback_policy="explicit_lower_fidelity",
    )
    selection = result["selection"]
    assert selection["resolved_fidelity"] == "level_1_module_approximation"
    assert selection["fallback_applied"] is True
    assert selection["fallback_reason"]


def test_phase62_project_selection_roundtrips_as_json_with_exact_asset_identity():
    catalog = load_reference_catalog()
    bundle = _bundle()
    result = set_project_module_electrical_shading_selection(
        bundle,
        catalog,
        module_revision_id="mod-rawibumi-uat-550-r1",
        topology_revision_id="topology-rawibumi-uat-550-r1",
        requested_fidelity="level_0_geometric_only",
    )
    original_hash = result["selection"]["selection_payload_sha256"]
    reopened = json.loads(json.dumps(bundle))
    selection = reopened["electrical_shading_selections"][
        "mod-rawibumi-uat-550-r1"
    ]
    assert selection["module_topology_revision_id"] == (
        "topology-rawibumi-uat-550-r1"
    )
    assert selection["selection_payload_sha256"] == original_hash

    capability = resolve_project_module_electrical_shading_capability(
        reopened,
        catalog,
        module_revision_id="mod-rawibumi-uat-550-r1",
        topology_revision_id=selection["module_topology_revision_id"],
    )
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"


def test_phase62_selection_integrity_requires_exact_hash_and_project_pins():
    catalog = load_reference_catalog()
    bundle = _bundle()
    set_project_module_electrical_shading_selection(
        bundle, catalog,
        module_revision_id="mod-rawibumi-uat-550-r1",
        topology_revision_id="topology-rawibumi-uat-550-r1",
        requested_fidelity="level_0_geometric_only",
    )
    assert_electrical_shading_selection_state(bundle)

    tampered = deepcopy(bundle)
    tampered["electrical_shading_selections"]["mod-rawibumi-uat-550-r1"]["resolved_fidelity"] = "level_1_module_approximation"
    with pytest.raises(ValueError, match="identity hash mismatch"):
        assert_electrical_shading_selection_state(tampered)

    missing_pin = deepcopy(bundle)
    del missing_pin["pinned_electrical_shading_assets"]["module_topologies"]["topology-rawibumi-uat-550-r1"]
    with pytest.raises(ValueError, match="not project-pinned"):
        assert_electrical_shading_selection_state(missing_pin)


def test_phase62_user_json_asset_import_requires_explicit_source_records():
    catalog = load_reference_catalog()
    topology = deepcopy(catalog["module_topologies"]["topology-rawibumi-uat-550-r1"])
    source = deepcopy(catalog["sources"]["src-rawibumi-uat-topology-fixture"])
    bundle = _bundle()
    result = import_project_electrical_shading_asset(
        bundle,
        asset_kind="module_topology",
        asset=topology,
        sources=[source],
    )
    assert result["asset_id"] == "topology-rawibumi-uat-550-r1"
    assert result["sources"]["src-rawibumi-uat-topology-fixture"]["schema_name"] == "SourceRecord"

    with pytest.raises(ValueError, match="unavailable SourceRecord"):
        import_project_electrical_shading_asset(
            _bundle(),
            asset_kind="module_topology",
            asset=topology,
            sources=[],
        )
