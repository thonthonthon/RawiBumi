from apps.api.catalog import catalog_summaries, load_reference_catalog


def test_phase62_reference_catalog_exposes_topology_without_auto_upgrading_capability():
    catalog = load_reference_catalog()
    assert set(catalog) >= {
        "modules",
        "inverters",
        "module_topologies",
        "electrical_parameterization_evidence",
        "sources",
    }

    topology = catalog["module_topologies"]["topology-rawibumi-uat-550-r1"]
    assert topology["module_definition_revision_id"] == "mod-rawibumi-uat-550-r1"
    assert topology["source_ids"] == ["src-rawibumi-uat-topology-fixture"]
    assert topology["source_ids"][0] in catalog["sources"]
    assert catalog["electrical_parameterization_evidence"] == {}

    summaries = catalog_summaries()
    uat = next(
        item for item in summaries["modules"]
        if item["revision_id"] == "mod-rawibumi-uat-550-r1"
    )
    electrical = uat["electrical_shading"]
    assert electrical["topology_revision_ids"] == [
        "topology-rawibumi-uat-550-r1"
    ]
    assert electrical["topology_selection_required"] is True
    # The UAT PAN now resolves a validated whole-module SDM. Phase 6.4 makes
    # Level 1 topology-independent, while topology alone still cannot unlock Level 2.
    assert electrical["maximum_fidelity_without_topology_selection"] == (
        "level_1_module_approximation"
    )

    topology_summary = summaries["module_topologies"][0]
    assert topology_summary["region_resolution"] == "grouped_cells"
    assert topology_summary["topology_provenance"] == "manual_verified"
