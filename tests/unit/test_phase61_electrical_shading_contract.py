import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from components.validation import module_capabilities
from geometry.shading import (
    COORDINATE_BASIS,
    FACTOR_CONVENTION,
    SUN_VECTOR_CONVENTION,
    ShadingContractError,
    assert_geometry_aware_shading_configuration,
)
from shading.electrical import (
    ElectricalShadingContractError,
    assert_electrical_iv_curve,
    assert_bypass_model_contract,
    assert_electrical_parameterization_evidence,
    assert_module_topology_definition,
    assert_requested_fidelity_available,
    assert_resolved_module_capability_evidence,
    electrical_shading_execution_sha256,
    electrical_shading_scientific_sha256,
    resolve_bypass_model_evidence,
    resolve_electrical_shading_capability,
    resolve_module_capability_snapshot,
    resolve_region_geometry_execution_readiness,
    validate_parameterization_for_electrical_shading,
    validate_topology_for_electrical_shading,
    validate_normalized_uv_polygon,
)


ROOT = Path(__file__).resolve().parents[2]


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _registry() -> Registry:
    registry = Registry()
    for directory in (
        ROOT / "schemas",
        ROOT / "components/schema",
        ROOT / "weather/schema",
        ROOT / "geometry/scene",
        ROOT / "geometry/coordinates",
        ROOT / "geometry/scene3d",
        ROOT / "geometry/shading",
        ROOT / "shading/electrical",
        ROOT / "electrical/schema",
        ROOT / "apps/web/schema",
        ROOT / "apps/api/schema",
    ):
        for path in directory.glob("*.schema.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in schema:
                registry = registry.with_resource(
                    schema["$id"], Resource.from_contents(schema)
                )
    return registry


def _topology():
    return {
        "schema_name": "ModuleTopologyDefinition",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "module_topology_id": "topology-synthetic-halfcell",
        "revision_id": "topology-synthetic-halfcell-r1",
        "module_definition_revision_id": "module-synthetic-r1",
        "topology_version": "0.1",
        "orientation_reference": "viewed_from_module_front",
        "coordinate_convention": "module_front_uv_normalized_width_height",
        "topology_class": "series_substrings_parallel_branches",
        "region_resolution": "half_cell",
        "physical_regions": [
            {
                "region_id": "r0",
                "region_type": "half_cell",
                "polygon_normalized": [[0.0, 0.0], [0.25, 0.0], [0.25, 0.5], [0.0, 0.5]],
                "electrical_substring_id": "s0",
                "equivalent_element_count": 30,
            },
            {
                "region_id": "r1",
                "region_type": "half_cell",
                "polygon_normalized": [[0.0, 0.5], [0.25, 0.5], [0.25, 1.0], [0.0, 1.0]],
                "electrical_substring_id": "s0",
                "equivalent_element_count": 30,
            },
            {
                "region_id": "r2",
                "region_type": "half_cell",
                "polygon_normalized": [[0.25, 0.0], [0.5, 0.0], [0.5, 0.5], [0.25, 0.5]],
                "electrical_substring_id": "s1",
                "equivalent_element_count": 30,
            },
            {
                "region_id": "r3",
                "region_type": "half_cell",
                "polygon_normalized": [[0.25, 0.5], [0.5, 0.5], [0.5, 1.0], [0.25, 1.0]],
                "electrical_substring_id": "s1",
                "equivalent_element_count": 30,
            },
        ],
        "electrical_substrings": [
            {
                "substring_id": "s0",
                "series_order": 0,
                "physical_region_ids": ["r0", "r1"],
                "parallel_branches": [
                    {"branch_id": "s0-a", "series_region_ids": ["r0"]},
                    {"branch_id": "s0-b", "series_region_ids": ["r1"]},
                ],
                "bypass_device_id": "d0",
            },
            {
                "substring_id": "s1",
                "series_order": 1,
                "physical_region_ids": ["r2", "r3"],
                "parallel_branches": [
                    {"branch_id": "s1-a", "series_region_ids": ["r2"]},
                    {"branch_id": "s1-b", "series_region_ids": ["r3"]},
                ],
                "bypass_device_id": "d1",
            },
        ],
        "bypass_devices": [
            {
                "bypass_device_id": "d0",
                "device_type": "bypass_diode",
                "protects_substring_ids": ["s0"],
                "forward_voltage_model": {
                    "model_type": "constant_forward_drop",
                    "model_id": "bypass.constant_drop.reference",
                    "model_version": "0.1",
                    "model_authority": "component_model",
                    "verification_state": "reviewed",
                    "model_provenance": "direct_source",
                    "validation_record_id": "validation-bypass-reference-r1",
                    "assumption_id": None,
                    "assumption_rationale": None,
                    "parameters": {"forward_voltage_v": 0.55},
                    "source_ids": ["source-synthetic-topology"],
                    "model_payload_sha256": "b" * 64,
                },
            },
            {
                "bypass_device_id": "d1",
                "device_type": "bypass_diode",
                "protects_substring_ids": ["s1"],
                "forward_voltage_model": {
                    "model_type": "constant_forward_drop",
                    "model_id": "bypass.constant_drop.reference",
                    "model_version": "0.1",
                    "model_authority": "component_model",
                    "verification_state": "reviewed",
                    "model_provenance": "direct_source",
                    "validation_record_id": "validation-bypass-reference-r1",
                    "assumption_id": None,
                    "assumption_rationale": None,
                    "parameters": {"forward_voltage_v": 0.55},
                    "source_ids": ["source-synthetic-topology"],
                    "model_payload_sha256": "b" * 64,
                },
            },
        ],
        "bypass_coverage_complete": True,
        "verification_state": "reviewed",
        "topology_provenance": "direct_source",
        "source_ids": ["source-synthetic-topology"],
        "notes": "Synthetic contract fixture only.",
        "metadata": {},
    }

def _module():
    return {
        "revision_id": "module-synthetic-r1",
        "cell_architecture": {
            "physical_cell_count": 120,
            "half_cell": True,
            "bypass_diode_count": 2,
        },
        "capability_flags": {
            "detailed_sdm_ready": True,
        },
    }


def _module_capability_evidence():
    return {
        "schema_name": "ResolvedComponentModel",
        "schema_version": "0.1",
        "resolution_id": "resolve-module-synthetic-r1",
        "component_type": "module",
        "component_definition_id": "module-synthetic",
        "component_revision_id": "module-synthetic-r1",
        "status": "resolved",
        "requested_model_id": None,
        "selected_model": {
            "model_id": "module.pvsyst_singlediode.v6",
            "component_type": "module",
            "model_family": "single_diode",
            "fidelity_rank": 300,
            "source_model_type": "pvsyst_singlediode",
            "implementation_status": "validated_contract",
            "description": "Synthetic validated detailed SDM fixture.",
            "component_model_version": "6.0",
            "parameter_source_path": (
                "electrical_models[pvsyst_singlediode].parameter_set"
            ),
            "validation_status": "passed",
        },
        "enabled_refinements": [],
        "unavailable_refinements": [],
        "assumptions": [],
        "warnings": [],
        "source_ids": ["source-synthetic-module"],
        "capability_snapshot": {
            "layout_ready": True,
            "basic_yield_ready": True,
            "detailed_sdm_ready": True,
            "bifacial_ready": False,
            "detailed_shading_ready": False,
            "independent_iv_validated": False,
        },
    }


def _parameterization_evidence(scope="region_substring"):
    suffix = "region" if scope == "region_substring" else "cell"
    return {
        "schema_name": "ElectricalParameterizationEvidence",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "evidence_id": f"evidence-{suffix}-r1",
        "parameterization_scope": scope,
        "parameterization_id": f"parameterization-{suffix}-r1",
        "module_definition_revision_id": "module-synthetic-r1",
        "module_topology_revision_id": "topology-synthetic-halfcell-r1",
        "model_id": f"electrical.parameterization.{suffix}",
        "model_version": "0.1",
        "validation_record_id": f"validation-{suffix}-r1",
        "validation_status": "passed",
        "verification_state": "auto_validated",
        "parameterization_provenance": "derived_validated",
        "source_ids": ["source-synthetic-topology"],
        "parameterization_payload_sha256": "a" * 64,
        "notes": "Synthetic contract fixture only.",
        "metadata": {},
    }


_DEFAULT_MODULE_CAPABILITY_EVIDENCE = object()


def _resolve_capability(
    module,
    topology=None,
    *,
    module_capability_evidence=_DEFAULT_MODULE_CAPABILITY_EVIDENCE,
    region_parameterization_evidence=None,
    cell_parameterization_evidence=None,
):
    if module_capability_evidence is _DEFAULT_MODULE_CAPABILITY_EVIDENCE:
        module_capability_evidence = _module_capability_evidence()

    module_snapshot = resolve_module_capability_snapshot(
        module,
        module_capability_evidence,
    )
    topology_result = validate_topology_for_electrical_shading(
        module,
        topology,
    )
    bypass_evidence = resolve_bypass_model_evidence(
        topology,
        topology_result,
    )
    region_evidence = validate_parameterization_for_electrical_shading(
        region_parameterization_evidence,
        expected_scope="region_substring",
        module_definition=module,
        topology_definition=topology,
    )
    cell_evidence = validate_parameterization_for_electrical_shading(
        cell_parameterization_evidence,
        expected_scope="cell",
        module_definition=module,
        topology_definition=topology,
    )
    return resolve_electrical_shading_capability(
        module_snapshot,
        topology_result,
        bypass_model_evidence=bypass_evidence,
        region_parameterization_evidence=region_evidence,
        cell_parameterization_evidence=cell_evidence,
    )


def _electrical_configuration():
    return {
        "schema_name": "ElectricalShadingConfiguration",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "requested_fidelity": "level_2_bypass_substring",
        "fallback_policy": "fail_closed",
        "thermal_state_scope": "single_module_temperature",
        "loss_accounting_boundary": "geometry_then_electrical_mismatch_then_mppt",
        "model_selections": {
            "module_electrical_model_id": "module.pvsyst_singlediode.v6",
            "region_parameterization_model_id": "region.parameterization.reference",
            "cell_parameterization_model_id": None,
            "bypass_model_family_id": "bypass.constant_drop.reference",
            "module_iv_assembly_model_id": None,
            "string_iv_assembly_model_id": None,
            "mppt_operating_point_model_id": None,
        },
        "scientific_options": {
            "iv_interpolation": "linear",
        },
        "execution_options": {
            "cache_mode": "none",
            "storage_mode": "inline",
            "parallel_workers": 1,
        },
    }


def _phase5_configuration():
    return {
        "beam_method": "polygon_projection.v0.1",
        "diffuse_method": "sky_dome_isotropic.v0.1",
        "albedo_method": "ground_view.v0.1",
        "fidelity_level": "engineering",
        "sun_position_resolution_seconds": None,
        "electrical_shading_method": None,
        "geometry_contract_version": "0.1",
        "coordinate_basis": COORDINATE_BASIS,
        "sun_vector_convention": SUN_VECTOR_CONVENTION,
        "factor_convention": FACTOR_CONVENTION,
        "receiver_granularity": "module",
        "self_shading_enabled": True,
        "cache_policy": {"mode": "exact"},
        "geometric_resolution": {
            "receiver_subdivision_u": 1,
            "receiver_subdivision_v": 1,
        },
        "model_options": {},
    }


def test_phase61_new_schemas_are_valid_and_referenceable():
    registry = _registry()
    schemas = [
        "components/schema/module-topology-definition.schema.json",
        "shading/electrical/electrical-parameterization-evidence.schema.json",
        "shading/electrical/electrical-shading-configuration.schema.json",
        "shading/electrical/electrical-region-map.schema.json",
        "shading/electrical/local-electrical-irradiance-state.schema.json",
        "shading/electrical/electrical-iv-curve.schema.json",
        "shading/electrical/electrical-shading-result.schema.json",
    ]
    for path in schemas:
        schema = _load(path)
        Draft202012Validator.check_schema(schema)

    Draft202012Validator(
        _load("components/schema/module-topology-definition.schema.json"),
        registry=registry,
    ).validate(_topology())
    Draft202012Validator(
        _load("shading/electrical/electrical-parameterization-evidence.schema.json"),
        registry=registry,
    ).validate(_parameterization_evidence())
    Draft202012Validator(
        _load("schemas/resolved-component-model.schema.json"),
        registry=registry,
    ).validate(_module_capability_evidence())
    Draft202012Validator(
        _load("shading/electrical/electrical-shading-configuration.schema.json"),
        registry=registry,
    ).validate(_electrical_configuration())


def test_phase61_topology_internal_consistency_and_uv_contract():
    topology = _topology()
    assert_module_topology_definition(topology)

    assert validate_normalized_uv_polygon(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    )

    outside = copy.deepcopy(topology)
    outside["physical_regions"][0]["polygon_normalized"][0][0] = -0.01
    with pytest.raises(ElectricalShadingContractError, match=r"within \[0, 1\]"):
        assert_module_topology_definition(outside)

    duplicate_mapping = copy.deepcopy(topology)
    duplicate_mapping["electrical_substrings"][1]["parallel_branches"][0][
        "series_region_ids"
    ] = ["r0"]
    with pytest.raises(ElectricalShadingContractError, match="more than one"):
        assert_module_topology_definition(duplicate_mapping)

    unmapped = copy.deepcopy(topology)
    unmapped["electrical_substrings"][1]["physical_region_ids"] = ["r3"]
    unmapped["electrical_substrings"][1]["parallel_branches"] = [
        {"branch_id": "s1-b", "series_region_ids": ["r3"]}
    ]
    with pytest.raises(ElectricalShadingContractError, match="unmapped regions"):
        assert_module_topology_definition(unmapped)

    no_source = copy.deepcopy(topology)
    no_source["source_ids"] = []
    with pytest.raises(ElectricalShadingContractError, match="source_id"):
        assert_module_topology_definition(no_source)

    wrong_region_type = copy.deepcopy(topology)
    wrong_region_type["physical_regions"][0]["region_type"] = "submodule"
    with pytest.raises(ElectricalShadingContractError, match="region_resolution"):
        assert_module_topology_definition(wrong_region_type)

    bad_bypass = copy.deepcopy(topology)
    bad_bypass["bypass_devices"][0]["forward_voltage_model"]["parameters"] = {}
    with pytest.raises(ElectricalShadingContractError, match="forward_voltage_v"):
        assert_module_topology_definition(bad_bypass)


def test_phase61_region_geometry_readiness_separates_structure_from_execution():
    module = _module()
    topology = _topology()

    # Baseline fixture uses adjacent regions that share edges/points only.
    assert_module_topology_definition(topology)
    findings = []
    assert resolve_region_geometry_execution_readiness(
        topology,
        topology_structurally_valid=True,
        findings=findings,
    ) is True
    assert findings == []

    capability = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=_parameterization_evidence(),
    )
    assert capability["topology_valid"] is True
    assert capability["topology_structurally_valid"] is True
    assert capability["region_geometry_execution_ready"] is True
    assert capability["maximum_fidelity_level"] == "level_2_bypass_substring"


def test_phase61_self_intersecting_region_is_structural_but_not_execution_ready():
    module = _module()
    topology = _topology()

    # Asymmetric bow-tie: non-zero shoelace area, so the stored topology remains
    # structurally intelligible, but the region polygon is not simple.
    topology["physical_regions"][0]["polygon_normalized"] = [
        [0.0, 0.0],
        [0.25, 0.5],
        [0.05, 0.5],
        [0.25, 0.1],
    ]

    assert_module_topology_definition(topology)

    capability = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=_parameterization_evidence(),
    )
    assert capability["topology_valid"] is True
    assert capability["topology_structurally_valid"] is True
    assert capability["region_geometry_execution_ready"] is False
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert any(
        item["code"] == "ELECTRICAL_SHADING_REGION_GEOMETRY_SELF_INTERSECTION"
        for item in capability["findings"]
    )


def test_phase61_positive_area_region_overlap_blocks_execution_but_not_structure():
    module = _module()
    topology = _topology()

    # r0 occupies x=[0, 0.25], y=[0, 0.5]. Move r2 left so that the two
    # physical regions overlap by positive area while all electrical references
    # remain structurally coherent.
    topology["physical_regions"][2]["polygon_normalized"] = [
        [0.20, 0.0],
        [0.50, 0.0],
        [0.50, 0.5],
        [0.20, 0.5],
    ]

    assert_module_topology_definition(topology)

    capability = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=_parameterization_evidence(),
    )
    assert capability["topology_valid"] is True
    assert capability["topology_structurally_valid"] is True
    assert capability["region_geometry_execution_ready"] is False
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert any(
        item["code"] == "ELECTRICAL_SHADING_REGION_GEOMETRY_OVERLAP"
        for item in capability["findings"]
    )


def test_phase61_bypass_model_presence_alone_does_not_unlock_level2():
    module = _module()
    topology = _topology()
    model = topology["bypass_devices"][0]["forward_voltage_model"]

    # Stored component model remains structurally valid but is not executable
    # until verification/validation evidence is sufficient.
    model["verification_state"] = "source_attached"
    model["validation_record_id"] = None
    assert_bypass_model_contract(model, device_id="d0")
    assert_module_topology_definition(topology)

    capability = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=_parameterization_evidence(),
    )
    assert capability["topology_valid"] is True
    assert capability["bypass_models_ready"] is False
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert any(
        item["code"] == "ELECTRICAL_SHADING_BYPASS_COMPONENT_MODEL_NOT_VERIFIED"
        for item in capability["findings"]
    )


def test_phase61_bypass_component_model_without_sources_is_not_execution_ready():
    module = _module()
    topology = _topology()

    for device in topology["bypass_devices"]:
        model = device["forward_voltage_model"]
        model["source_ids"] = []
        assert_bypass_model_contract(model, device_id=device["bypass_device_id"])

    # Empty sources are structurally storable but cannot establish verified
    # component truth for Level-2 execution.
    assert_module_topology_definition(topology)
    capability = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=_parameterization_evidence(),
    )
    assert capability["bypass_models_ready"] is False
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert any(
        item["code"] == "ELECTRICAL_SHADING_BYPASS_COMPONENT_MODEL_NOT_VERIFIED"
        for item in capability["findings"]
    )


def test_phase61_explicit_bypass_assumption_is_executable_but_not_component_truth():
    module = _module()
    topology = _topology()

    for index, device in enumerate(topology["bypass_devices"]):
        model = device["forward_voltage_model"]
        model.update(
            {
                "model_authority": "explicit_simulation_assumption",
                "verification_state": "not_applicable",
                "model_provenance": "simulation_assumption",
                "validation_record_id": None,
                "assumption_id": f"assumption-bypass-drop-{index}",
                "assumption_rationale": (
                    "Reference constant-drop assumption selected explicitly for "
                    "contract-level execution."
                ),
                "source_ids": [],
            }
        )
        assert_bypass_model_contract(model, device_id=device["bypass_device_id"])

    Draft202012Validator(
        _load("components/schema/module-topology-definition.schema.json"),
        registry=_registry(),
    ).validate(topology)
    assert_module_topology_definition(topology)

    capability = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=_parameterization_evidence(),
    )
    assert capability["bypass_models_ready"] is True
    assert (
        capability["bypass_model_readiness_mode"]
        == "explicit_simulation_assumptions"
    )
    assert capability["maximum_fidelity_level"] == "level_2_bypass_substring"
    assert capability["bypass_assumption_ids"] == [
        "assumption-bypass-drop-0",
        "assumption-bypass-drop-1",
    ]
    assert any(
        item["code"] == "ELECTRICAL_SHADING_BYPASS_ASSUMPTION_ACTIVE"
        for item in capability["findings"]
    )


def test_phase61_bypass_model_authority_semantics_fail_closed():
    topology = _topology()
    model = topology["bypass_devices"][0]["forward_voltage_model"]

    no_authority = copy.deepcopy(model)
    no_authority.pop("model_authority")
    with pytest.raises(ElectricalShadingContractError, match="model_authority"):
        assert_bypass_model_contract(no_authority, device_id="d0")

    false_assumption = copy.deepcopy(model)
    false_assumption["model_authority"] = "explicit_simulation_assumption"
    false_assumption["verification_state"] = "reviewed"
    false_assumption["model_provenance"] = "direct_source"
    false_assumption["validation_record_id"] = "validation-bypass-reference-r1"
    false_assumption["assumption_id"] = "assumption-1"
    false_assumption["assumption_rationale"] = "Explicit test assumption."
    with pytest.raises(ElectricalShadingContractError, match="not_applicable"):
        assert_bypass_model_contract(false_assumption, device_id="d0")


def test_phase61_module_capability_flag_cannot_authorize_embedded_topology():
    module = {
        "stc": {
            "pmp_w": 550.0,
            "voc_v": 49.0,
            "isc_a": 14.0,
            "vmp_v": 41.0,
            "imp_a": 13.4,
            "reference_irradiance_w_m2": 1000.0,
            "reference_cell_temperature_c": 25.0,
        },
        "electrical_models": [
            {
                "model_type": "pvsyst_singlediode",
                "parameter_set": {
                    "r_series_ohm": 0.2,
                    "r_shunt_ref_ohm": 500.0,
                    "r_shunt_0_ohm": 1500.0,
                    "r_shunt_exp": 5.5,
                    "gamma_ref": 1.1,
                    "mu_gamma": -0.0003,
                },
            }
        ],
        "module_topology": {"legacy_embedded_shortcut": True},
    }
    capabilities = module_capabilities(
        module,
        [],
        model_validation_passed=True,
    )
    assert capabilities["detailed_sdm_ready"] is True
    assert capabilities["detailed_shading_ready"] is False


def test_phase61_raw_module_capability_flag_cannot_unlock_detailed_sdm_fidelity():
    module = _module()

    # A raw ModuleDefinition capability flag is no longer authoritative.
    raw_only = _resolve_capability(
        module,
        module_capability_evidence=None,
    )
    assert raw_only["available_fidelity_levels"] == ["level_0_geometric_only"]
    assert raw_only["maximum_fidelity_level"] == "level_0_geometric_only"
    assert raw_only["detailed_sdm_ready"] is False
    assert raw_only["module_capability_resolution_id"] is None
    assert any(
        item["code"] == "ELECTRICAL_SHADING_MODULE_CAPABILITY_EVIDENCE_REQUIRED"
        for item in raw_only["findings"]
    )

    evidence = _module_capability_evidence()
    assert_resolved_module_capability_evidence(
        evidence,
        expected_module_revision_id=module["revision_id"],
    )
    resolved = _resolve_capability(
        module,
        module_capability_evidence=evidence,
    )
    assert resolved["available_fidelity_levels"] == [
        "level_0_geometric_only",
        "level_1_module_approximation",
    ]
    assert resolved["maximum_fidelity_level"] == "level_1_module_approximation"
    assert resolved["detailed_sdm_ready"] is True
    assert (
        resolved["module_capability_resolution_id"]
        == evidence["resolution_id"]
    )


def test_phase61_counts_alone_never_unlock_detailed_topology_fidelity():
    module = _module()
    evidence = _module_capability_evidence()

    capability = _resolve_capability(
        module,
        module_capability_evidence=evidence,
    )
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert capability["topology_present"] is False

    # Cell/bypass counts are intentionally ignored as topology authority.
    richer_counts = copy.deepcopy(module)
    richer_counts["cell_architecture"].update(
        {
            "cell_rows": 12,
            "cell_columns": 10,
            "cells_in_series": 60,
            "cells_in_parallel": 2,
            "source_layout_code": "synthetic-layout-code",
        }
    )
    assert (
        _resolve_capability(
            richer_counts,
            module_capability_evidence=evidence,
        )["maximum_fidelity_level"]
        == "level_1_module_approximation"
    )


def test_phase61_resolved_module_capability_evidence_fails_closed_when_stale_or_fabricated():
    module = _module()

    wrong_revision = _module_capability_evidence()
    wrong_revision["component_revision_id"] = "module-other-r1"
    capability = _resolve_capability(
        module,
        module_capability_evidence=wrong_revision,
    )
    assert capability["maximum_fidelity_level"] == "level_0_geometric_only"
    assert any(
        item["code"] == "ELECTRICAL_SHADING_MODULE_CAPABILITY_EVIDENCE_INVALID"
        for item in capability["findings"]
    )

    raw_bool_only = _module_capability_evidence()
    raw_bool_only["selected_model"]["model_id"] = "module.stc_tempco_linear.v0.1"
    raw_bool_only["selected_model"]["model_family"] = "stc_temperature_coefficient"
    raw_bool_only["selected_model"]["implementation_status"] = "resolution_contract"
    raw_bool_only["selected_model"]["validation_status"] = "engineering_validated_inputs"
    raw_bool_only["capability_snapshot"]["detailed_sdm_ready"] = True
    capability = _resolve_capability(
        module,
        module_capability_evidence=raw_bool_only,
    )
    assert capability["maximum_fidelity_level"] == "level_0_geometric_only"
    assert any(
        item["code"] == "ELECTRICAL_SHADING_MODULE_CAPABILITY_EVIDENCE_INVALID"
        for item in capability["findings"]
    )

    invalidated_model = _module_capability_evidence()
    invalidated_model["selected_model"]["validation_status"] = "failed"
    capability = _resolve_capability(
        module,
        module_capability_evidence=invalidated_model,
    )
    assert capability["maximum_fidelity_level"] == "level_0_geometric_only"


def test_phase61_trusted_topology_needs_revision_bound_parameterization_evidence():
    module = _module()
    topology = _topology()

    topology_only = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
    )
    assert topology_only["topology_valid"] is True
    assert topology_only["topology_trusted"] is True
    assert topology_only["maximum_fidelity_level"] == "level_1_module_approximation"
    assert topology_only["region_parameterization_ready"] is False
    assert any(
        item["code"] == "ELECTRICAL_SHADING_LEVEL2_PARAMETERIZATION_REQUIRED"
        for item in topology_only["findings"]
    )

    region_evidence = _parameterization_evidence("region_substring")
    assert_electrical_parameterization_evidence(
        region_evidence,
        expected_scope="region_substring",
    )
    level2 = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=region_evidence,
    )
    assert level2["maximum_fidelity_level"] == "level_2_bypass_substring"
    assert level2["region_parameterization_ready"] is True
    assert (
        level2["region_parameterization_evidence_id"]
        == region_evidence["evidence_id"]
    )

    cell_evidence = _parameterization_evidence("cell")
    level3 = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=region_evidence,
        cell_parameterization_evidence=cell_evidence,
    )
    assert level3["maximum_fidelity_level"] == "level_3_cell_submodule_iv"
    assert level3["cell_parameterization_ready"] is True
    assert level3["cell_parameterization_evidence_id"] == cell_evidence["evidence_id"]

    # The old caller-asserted boolean API is intentionally gone.
    with pytest.raises(TypeError):
        resolve_electrical_shading_capability(
            resolve_module_capability_snapshot(
                module,
                _module_capability_evidence(),
            ),
            region_parameterization_available=True,
        )


def test_phase61_parameterization_evidence_fails_closed_when_stale_or_unvalidated():
    module = _module()
    topology = _topology()

    wrong_module = _parameterization_evidence()
    wrong_module["module_definition_revision_id"] = "module-other-r1"
    capability = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=wrong_module,
    )
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert any(
        item["code"] == "ELECTRICAL_SHADING_PARAMETERIZATION_MODULE_REVISION_MISMATCH"
        for item in capability["findings"]
    )

    wrong_topology = _parameterization_evidence()
    wrong_topology["module_topology_revision_id"] = "topology-other-r1"
    capability = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=wrong_topology,
    )
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert any(
        item["code"] == "ELECTRICAL_SHADING_PARAMETERIZATION_TOPOLOGY_REVISION_MISMATCH"
        for item in capability["findings"]
    )

    failed_validation = _parameterization_evidence()
    failed_validation["validation_status"] = "failed"
    capability = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=failed_validation,
    )
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert any(
        item["code"] == "ELECTRICAL_SHADING_PARAMETERIZATION_EVIDENCE_INVALID"
        for item in capability["findings"]
    )

    no_sources = _parameterization_evidence()
    no_sources["source_ids"] = []
    with pytest.raises(ElectricalShadingContractError, match="source_ids"):
        assert_electrical_parameterization_evidence(no_sources)


def test_phase61_parameterization_scope_and_topology_revision_binding_fail_closed():
    module = _module()
    topology = _topology()
    region_evidence = _parameterization_evidence("region_substring")

    # Region/sub-string evidence cannot be reused as cell-level authorization.
    capability = _resolve_capability(
        module,
        topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=region_evidence,
        cell_parameterization_evidence=copy.deepcopy(region_evidence),
    )
    assert capability["maximum_fidelity_level"] == "level_2_bypass_substring"
    assert capability["cell_parameterization_ready"] is False
    assert any(
        item["code"] == "ELECTRICAL_SHADING_PARAMETERIZATION_EVIDENCE_INVALID"
        for item in capability["findings"]
    )

    # revision_id is the canonical identity of the separately revisioned
    # topology object. Evidence bound to the prior revision must fail closed.
    revised_topology = copy.deepcopy(topology)
    revised_topology["revision_id"] = "topology-synthetic-halfcell-r2"
    capability = _resolve_capability(
        module,
        revised_topology,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=region_evidence,
    )
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert capability["region_parameterization_ready"] is False
    assert any(
        item["code"] == "ELECTRICAL_SHADING_PARAMETERIZATION_TOPOLOGY_REVISION_MISMATCH"
        for item in capability["findings"]
    )


def test_phase61_inferred_auto_validated_or_wrong_revision_topology_does_not_unlock_level2():
    module = _module()

    auto_validated = _topology()
    auto_validated["verification_state"] = "auto_validated"
    capability = _resolve_capability(
        module,
        auto_validated,
        module_capability_evidence=_module_capability_evidence(),
        region_parameterization_evidence=_parameterization_evidence(),
    )
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert capability["topology_trusted"] is False
    assert any(
        item["code"] == "ELECTRICAL_SHADING_TOPOLOGY_NOT_VERIFIED"
        for item in capability["findings"]
    )

    inferred = _topology()
    inferred["topology_provenance"] = "inferred"
    capability = _resolve_capability(
        module,
        inferred,
        module_capability_evidence=_module_capability_evidence(),
    )
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert capability["topology_trusted"] is False

    wrong_revision = _topology()
    wrong_revision["module_definition_revision_id"] = "other-module-revision"
    capability = _resolve_capability(
        module,
        wrong_revision,
        module_capability_evidence=_module_capability_evidence(),
    )
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert any(
        item["code"] == "ELECTRICAL_SHADING_TOPOLOGY_MODULE_REVISION_MISMATCH"
        for item in capability["findings"]
    )


def test_phase61_capability_resolver_is_pure_derivation_over_validated_snapshots():
    module = _module()
    topology = _topology()
    module_evidence = _module_capability_evidence()
    region_raw = _parameterization_evidence()

    module_snapshot = resolve_module_capability_snapshot(module, module_evidence)
    topology_result = validate_topology_for_electrical_shading(module, topology)
    bypass_evidence = resolve_bypass_model_evidence(topology, topology_result)
    region_evidence = validate_parameterization_for_electrical_shading(
        region_raw,
        expected_scope="region_substring",
        module_definition=module,
        topology_definition=topology,
    )

    # Mutate the raw source objects after validation. Pure capability derivation
    # consumes only the frozen validation results above and never re-reads them.
    module["capability_flags"]["detailed_sdm_ready"] = False
    module_evidence["selected_model"]["validation_status"] = "failed"
    topology["verification_state"] = "unverified"
    topology["physical_regions"][0]["polygon_normalized"] = [
        [0.0, 0.0],
        [0.25, 0.5],
        [0.05, 0.5],
        [0.25, 0.1],
    ]
    region_raw["validation_status"] = "failed"

    capability = resolve_electrical_shading_capability(
        module_snapshot,
        topology_result,
        bypass_model_evidence=bypass_evidence,
        region_parameterization_evidence=region_evidence,
    )
    assert capability["maximum_fidelity_level"] == "level_2_bypass_substring"
    assert capability["detailed_sdm_ready"] is True
    assert capability["topology_structurally_valid"] is True
    assert capability["region_geometry_execution_ready"] is True
    assert capability["region_parameterization_ready"] is True


def test_phase61_pure_resolver_rejects_cross_revision_snapshot_mixing():
    module = _module()
    topology = _topology()

    module_snapshot = resolve_module_capability_snapshot(
        module,
        _module_capability_evidence(),
    )
    topology_result = validate_topology_for_electrical_shading(module, topology)
    bypass_evidence = resolve_bypass_model_evidence(topology, topology_result)
    region_evidence = validate_parameterization_for_electrical_shading(
        _parameterization_evidence(),
        expected_scope="region_substring",
        module_definition=module,
        topology_definition=topology,
    )

    stale_region = replace(
        region_evidence,
        module_revision_id="module-stale-r1",
    )
    capability = resolve_electrical_shading_capability(
        module_snapshot,
        topology_result,
        bypass_model_evidence=bypass_evidence,
        region_parameterization_evidence=stale_region,
    )
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert any(
        item["code"]
        == "ELECTRICAL_SHADING_VALIDATED_REGION_PARAMETERIZATION_BINDING_MISMATCH"
        for item in capability["findings"]
    )

    stale_bypass = replace(
        bypass_evidence,
        topology_revision_id="topology-stale-r1",
    )
    capability = resolve_electrical_shading_capability(
        module_snapshot,
        topology_result,
        bypass_model_evidence=stale_bypass,
        region_parameterization_evidence=region_evidence,
    )
    assert capability["maximum_fidelity_level"] == "level_1_module_approximation"
    assert any(
        item["code"] == "ELECTRICAL_SHADING_VALIDATED_BYPASS_BINDING_MISMATCH"
        for item in capability["findings"]
    )


def test_phase61_fidelity_fallback_is_never_silent():
    capability = _resolve_capability(
        _module(),
        module_capability_evidence=_module_capability_evidence(),
    )

    with pytest.raises(
        ElectricalShadingContractError,
        match="requested fidelity level_2_bypass_substring is not available",
    ):
        assert_requested_fidelity_available(
            "level_2_bypass_substring",
            capability,
        )

    resolved = assert_requested_fidelity_available(
        "level_2_bypass_substring",
        capability,
        fallback_policy="explicit_lower_fidelity",
    )
    assert resolved == "level_1_module_approximation"


def test_phase61_scientific_identity_excludes_execution_only_choices():
    base = _electrical_configuration()
    scientific_a = electrical_shading_scientific_sha256(base)
    execution_a = electrical_shading_execution_sha256(base)

    changed_execution = copy.deepcopy(base)
    changed_execution["execution_options"] = {
        "cache_mode": "exact",
        "storage_mode": "parquet",
        "parallel_workers": 16,
    }
    assert electrical_shading_scientific_sha256(changed_execution) == scientific_a
    assert electrical_shading_execution_sha256(changed_execution) != execution_a

    changed_science = copy.deepcopy(base)
    changed_science["scientific_options"]["iv_interpolation"] = "monotone_cubic"
    assert electrical_shading_scientific_sha256(changed_science) != scientific_a


def test_phase61_phase5_worker_stays_fail_closed_on_phase6_configuration():
    phase5 = _phase5_configuration()
    assert_geometry_aware_shading_configuration(phase5)

    phase6_request = copy.deepcopy(phase5)
    phase6_request["electrical_shading_configuration"] = _electrical_configuration()

    Draft202012Validator(
        _load("geometry/shading/shading-configuration.schema.json"),
        registry=_registry(),
    ).validate(phase6_request)

    with pytest.raises(
        ShadingContractError,
        match="does not consume the Phase-6",
    ):
        assert_geometry_aware_shading_configuration(phase6_request)


def test_phase61_derived_artifact_examples_validate():
    registry = _registry()
    a = "a" * 64
    b = "b" * 64
    c = "c" * 64
    d = "d" * 64

    region_map = {
        "schema_name": "ElectricalRegionMap",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "authority": "derived_physics_only",
        "editable": False,
        "electrical_region_map_id": "ermap-1",
        "source_scene_revision_id": "scene-r1",
        "source_module_instance_id": "module-instance-1",
        "source_module_definition_revision_id": "module-synthetic-r1",
        "source_module_topology_revision_id": "topology-synthetic-halfcell-r1",
        "source_receiver_id": "receiver-module-1",
        "source_compiled_geometry_hash": a,
        "coordinate_convention": "module_front_uv_normalized_width_height",
        "mapper_manifest": {
            "mapper_id": "opensimpv.electrical_region_mapper.module_uv",
            "mapper_version": "0.1",
            "landscape_rotation_convention": "clockwise_90_viewed_from_module_front",
        },
        "placement_orientation": "portrait",
        "source_receiver_area_m2": 0.125,
        "mapped_region_area_m2": 0.125,
        "mapped_region_area_fraction": 1.0,
        "mapping_payload_sha256": b,
        "regions": [
            {
                "region_id": "region-map-r0",
                "source_topology_region_id": "r0",
                "polygon_uv": [
                    [0.0, 0.0],
                    [0.25, 0.0],
                    [0.25, 0.5],
                    [0.0, 0.5],
                ],
                "vertices_3d": [
                    [0.0, 0.0, 1.0],
                    [0.25, 0.0, 1.0],
                    [0.25, 0.5, 1.0],
                    [0.0, 0.5, 1.0],
                ],
                "source_electrical_substring_id": "substring-0",
                "region_type": "submodule",
                "equivalent_element_count": 1,
                "area_m2": 0.125,
                "metadata": {},
            }
        ],
        "findings": [],
    }
    Draft202012Validator(
        _load("shading/electrical/electrical-region-map.schema.json"),
        registry=registry,
    ).validate(region_map)

    state = {
        "schema_name": "LocalElectricalIrradianceState",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "state_id": "state-1",
        "interval_start": "2026-09-25T12:00:00+07:00",
        "evaluation_time": "2026-09-25T12:30:00+07:00",
        "source_scene_revision_id": "scene-r1",
        "source_module_instance_id": "module-instance-1",
        "source_module_definition_revision_id": "module-synthetic-r1",
        "source_electrical_region_map_id": "ermap-1",
        "source_electrical_region_map_hash": b,
        "source_shading_result_id": "shading-1",
        "source_shading_physical_result_hash": c,
        "irradiance_mapping_order": (
            "unshaded_poa_by_channel_then_geometry_visibility_then_optical_treatment"
        ),
        "irradiance_side_scope": "front_side_only_v0.1",
        "thermal_state_scope": "single_module_temperature",
        "module_temperature_c": 45.0,
        "optical_model_manifest": {
            "model_id": "iam.reference",
            "model_version": "0.1",
            "notes": None,
        },
        "regions": [
            {
                "region_id": "region-map-r0",
                "unshaded_poa": {
                    "beam_w_m2": 700.0,
                    "sky_diffuse_w_m2": 120.0,
                    "ground_reflected_w_m2": 20.0,
                },
                "visibility_factor": {
                    "beam": 0.5,
                    "sky_diffuse": 0.9,
                    "ground": 0.95,
                },
                "post_geometry_poa": {
                    "beam_w_m2": 350.0,
                    "sky_diffuse_w_m2": 108.0,
                    "ground_reflected_w_m2": 19.0,
                },
                "optical_modifier": {
                    "beam": 1.0,
                    "sky_diffuse": 0.75,
                    "ground_reflected": 1.0,
                },
                "effective_irradiance_w_m2": 450.0,
                "quality_flags": [],
            }
        ],
        "state_payload_sha256": d,
        "quality_flags": [],
    }
    Draft202012Validator(
        _load("shading/electrical/local-electrical-irradiance-state.schema.json"),
        registry=registry,
    ).validate(state)

    curve = {
        "schema_name": "ElectricalIVCurve",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "curve_id": "iv-module-1",
        "curve_scope": "module",
        "representation": "sampled_voltage_grid",
        "sample_order": "ascending_voltage",
        "sign_convention": "pv_delivery_current_positive_power_equals_v_times_i",
        "mpp_semantics": {
            "declaration_authority": "solver_declared",
            "sample_verification_scope": "represented_samples_only",
            "voltage_tolerance_v": 0.1,
            "power_tolerance_w": 0.5,
            "continuous_curve_guarantee": "none",
            "continuous_curve_guarantee_basis": None,
        },
        "source_module_instance_id": "module-instance-1",
        "source_string_id": None,
        "source_mppt_instance_id": None,
        "points": [
            {"voltage_v": 0.0, "current_a": 12.0, "power_w": 0.0},
            {"voltage_v": 30.0, "current_a": 11.0, "power_w": 330.0},
            {"voltage_v": 50.0, "current_a": 0.0, "power_w": 0.0},
        ],
        "isc_a": 12.0,
        "voc_v": 50.0,
        "global_mpp": {"voltage_v": 30.0, "current_a": 11.0, "power_w": 330.0},
        "local_mpp_candidates": [
            {"voltage_v": 30.0, "current_a": 11.0, "power_w": 330.0}
        ],
        "scientific_model_manifest": {
            "model_id": "contract.fixture",
            "model_version": "0.1",
            "parameterization_id": None,
            "topology_revision_id": "topology-synthetic-halfcell-r1",
            "bypass_model_ids": ["bypass.constant_drop.reference"],
            "notes": None,
        },
        "execution_manifest": {
            "solver_id": "contract.fixture",
            "solver_version": "0.1",
            "voltage_grid_strategy": "fixture",
            "point_count": 3,
            "cache_mode": "none",
            "parallelization": "serial",
        },
        "scientific_input_sha256": a,
        "physical_result_sha256": b,
        "execution_payload_sha256": c,
        "quality_flags": [],
    }
    Draft202012Validator(
        _load("shading/electrical/electrical-iv-curve.schema.json"),
        registry=registry,
    ).validate(curve)
    assert_electrical_iv_curve(curve)

    invalid_curve = copy.deepcopy(curve)
    invalid_curve["points"][1]["power_w"] = 329.0
    with pytest.raises(ElectricalShadingContractError, match="must equal"):
        assert_electrical_iv_curve(invalid_curve)

    nonmonotonic_curve = copy.deepcopy(curve)
    nonmonotonic_curve["points"][1]["voltage_v"] = -1.0
    nonmonotonic_curve["points"][1]["power_w"] = -11.0
    with pytest.raises(ElectricalShadingContractError, match="strictly increasing"):
        assert_electrical_iv_curve(nonmonotonic_curve)

    wrong_global = copy.deepcopy(curve)
    wrong_global["global_mpp"] = {
        "voltage_v": 20.0,
        "current_a": 10.0,
        "power_w": 200.0,
    }
    with pytest.raises(
        ElectricalShadingContractError,
        match="below a represented sampled-curve power maximum",
    ):
        assert_electrical_iv_curve(wrong_global)

    weaker_than_local = copy.deepcopy(curve)
    weaker_than_local["global_mpp"] = {
        "voltage_v": 30.0,
        "current_a": 10.0,
        "power_w": 300.0,
    }
    with pytest.raises(
        ElectricalShadingContractError,
        match="below a represented sampled-curve power maximum",
    ):
        assert_electrical_iv_curve(weaker_than_local)

    nonextremum_local = copy.deepcopy(curve)
    nonextremum_local["local_mpp_candidates"] = [
        {"voltage_v": 0.0, "current_a": 12.0, "power_w": 0.0}
    ]
    with pytest.raises(
        ElectricalShadingContractError,
        match="does not correspond to a represented sampled-curve local power extremum",
    ):
        assert_electrical_iv_curve(nonextremum_local)

    unsupported_continuous_claim = copy.deepcopy(curve)
    unsupported_continuous_claim["mpp_semantics"]["continuous_curve_guarantee"] = (
        "solver_guaranteed"
    )
    unsupported_continuous_claim["mpp_semantics"][
        "continuous_curve_guarantee_basis"
    ] = None
    with pytest.raises(
        ElectricalShadingContractError,
        match="requires an explicit guarantee basis",
    ):
        assert_electrical_iv_curve(unsupported_continuous_claim)

    explicit_continuous_claim = copy.deepcopy(curve)
    explicit_continuous_claim["mpp_semantics"]["continuous_curve_guarantee"] = (
        "solver_guaranteed"
    )
    explicit_continuous_claim["mpp_semantics"][
        "continuous_curve_guarantee_basis"
    ] = "contract.fixture solver guarantees global search over its continuous IV representation"
    assert_electrical_iv_curve(explicit_continuous_claim)

    result = {
        "schema_name": "ElectricalShadingResult",
        "schema_version": "0.1",
        "contract_version": "0.1",
        "electrical_shading_result_id": "eshading-1",
        "source_scene_revision_id": "scene-r1",
        "source_electrical_revision_id": "electrical-r1",
        "source_shading_result_id": "shading-1",
        "source_shading_physical_result_hash": c,
        "requested_fidelity": "level_2_bypass_substring",
        "resolved_fidelity": "level_2_bypass_substring",
        "fallback_applied": False,
        "fallback_reason": None,
        "thermal_state_scope": "single_module_temperature",
        "source_module_topology_revision_ids": [
            "topology-synthetic-halfcell-r1"
        ],
        "source_region_map_hashes": [b],
        "scientific_model_manifest": {
            "module_electrical_model_id": "module.pvsyst_singlediode.v6",
            "region_parameterization_model_id": "region.parameterization.reference",
            "cell_parameterization_model_id": None,
            "bypass_model_family_id": "bypass.constant_drop.reference",
            "module_iv_assembly_model_id": None,
            "string_iv_assembly_model_id": None,
            "mppt_operating_point_model_id": None,
        },
        "execution_manifest": {
            "solver_id": "contract-only",
            "solver_version": "0.1",
            "cache_mode": "none",
            "storage_mode": "inline",
            "parallelization": "serial",
        },
        "loss_accounting_boundary": "geometry_then_electrical_mismatch_then_mppt",
        "attribution_delta_convention": "reference_minus_evaluated_positive_is_loss",
        "attribution_channels": {
            "geometric_irradiance": {
                "status": "upstream",
                "accounting_rule": "upstream_not_rebooked",
            },
            "electrical_mismatch": {
                "status": "not_modeled",
                "counterfactual_basis": (
                    "uniform_same_area_weighted_effective_irradiance_to_"
                    "nonuniform_bypass_forced_off"
                ),
            },
            "bypass_interaction": {
                "status": "not_modeled",
                "counterfactual_basis": (
                    "nonuniform_bypass_forced_off_to_nonuniform_bypass_enabled"
                ),
                "signed_delta": True,
            },
            "mppt_operating_point": {
                "status": "not_modeled",
                "counterfactual_basis": (
                    "ideal_global_mpp_to_selected_tracker_operating_point"
                ),
            },
        },
        "local_state_dataset_reference": None,
        "module_iv_dataset_reference": None,
        "string_iv_dataset_reference": None,
        "mppt_iv_dataset_reference": None,
        "scientific_input_sha256": a,
        "physical_result_sha256": b,
        "execution_payload_sha256": d,
        "approximation_manifest": [],
        "findings": [],
    }
    Draft202012Validator(
        _load("shading/electrical/electrical-shading-result.schema.json"),
        registry=registry,
    ).validate(result)
