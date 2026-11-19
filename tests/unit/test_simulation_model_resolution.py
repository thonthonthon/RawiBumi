import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from components.candidates import build_inverter_candidate, build_module_candidate
from components.ond import parse_ond_text
from components.ond.mapper import map_ond
from components.pan import parse_pan_text
from components.pan.mapper import map_pan
from components.source_overlay import ComponentSourceFragment, build_candidate_from_fragments
from components.user_csv import parse_inverter_component_csv, parse_module_component_csv
from engine.simulation.models import (
    resolve_inverter_model,
    resolve_module_model,
    resolve_simulation_models,
)
from shading.electrical import (
    assert_resolved_module_capability_evidence,
    resolve_module_capability_snapshot,
)


ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _synthetic_validated_module():
    mapping = map_pan(parse_pan_text(_text("tests/fixtures/panond/synthetic_module.pan")))
    return build_module_candidate(
        mapping,
        candidate_id="candidate-phase1-module",
        module_definition_id="module-phase1-synthetic",
        revision_id="module-phase1-synthetic-r1",
        source_id="src-phase1-synthetic-pan",
    )["canonical_data"]


def _jinko_module():
    mapping = map_pan(
        parse_pan_text(
            _text("tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN")
        )
    )
    return build_module_candidate(
        mapping,
        candidate_id="candidate-phase1-jinko",
        module_definition_id="module-jinko-jkm550m-72hl4-v",
        revision_id="module-jinko-jkm550m-72hl4-v-r1",
        source_id="src-manufacturer-jinko-jkm550m-72hl4-v",
    )["canonical_data"]


def _huawei_ond_inverter():
    mapping = map_ond(
        parse_ond_text(
            _text("tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND")
        )
    )
    return build_inverter_candidate(
        mapping,
        candidate_id="candidate-phase1-huawei",
        inverter_definition_id="inv-huawei-sun2000-100ktl-m1",
        revision_id="inv-huawei-sun2000-100ktl-m1-r1",
        source_id="src-manufacturer-huawei-sun2000-100ktl-m1",
    )["canonical_data"]


def _basic_csv_module():
    text = (
        "source_id,source_kind,manufacturer,model,width_mm,height_mm,pmp_w,voc_v,"
        "isc_a,vmp_v,imp_a,reference_irradiance_w_m2,reference_cell_temperature_c,"
        "alpha_isc_pct_per_c,beta_voc_pct_per_c,gamma_pmp_pct_per_c\n"
        "src-basic-module,manufacturer_datasheet,Example Solar,BASIC-550,1134,2278,"
        "550,49.5,14.0,41.0,13.4146341463,1000,25,0.045,-0.28,-0.35\n"
    )
    fragment = parse_module_component_csv(text)[0]
    return build_candidate_from_fragments(
        "module",
        [fragment],
        candidate_id="candidate-basic-module",
        definition_id="module-basic-550",
        revision_id="module-basic-550-r1",
    )["canonical_data"]


def _constant_csv_inverter():
    text = (
        "source_id,source_kind,manufacturer,model,phase_configuration,max_dc_voltage_v,"
        "nominal_ac_power_w,nominal_ac_voltage_v,nominal_frequency_hz,mppt_count,"
        "mppt_min_voltage_v,mppt_max_voltage_v,constant_efficiency_pct\n"
        "src-basic-inverter,manufacturer_datasheet,Example Power,BASIC-100K,"
        "three_phase,1100,100000,400,50,10,200,1000,98.5\n"
    )
    fragment = parse_inverter_component_csv(text)[0]
    return build_candidate_from_fragments(
        "inverter",
        [fragment],
        candidate_id="candidate-basic-inverter",
        definition_id="inverter-basic-100k",
        revision_id="inverter-basic-100k-r1",
    )["canonical_data"]


def _resolution_registry():
    paths = [
        ROOT / "schemas/simulation-assumption.schema.json",
        ROOT / "schemas/resolved-component-model.schema.json",
        ROOT / "schemas/simulation-model-resolution.schema.json",
    ]
    resources = []
    for path in paths:
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def _validate_resolution(result, schema_name: str):
    schema = json.loads((ROOT / f"schemas/{schema_name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, registry=_resolution_registry()).validate(result)


def test_validated_synthetic_pan_resolves_detailed_pvsyst_sdm():
    module = _synthetic_validated_module()
    result = resolve_module_model(module, resolution_id="resolve-module-detailed")

    assert result["status"] == "resolved"
    assert result["selected_model"]["model_id"] == "module.pvsyst_singlediode.v6"
    assert result["selected_model"]["fidelity_rank"] == 300
    assert result["selected_model"]["validation_status"] == "passed"
    assert not any(item["severity"] == "blocking" for item in result["assumptions"])
    assert_resolved_module_capability_evidence(
        result,
        expected_module_revision_id=module["revision_id"],
    )
    snapshot = resolve_module_capability_snapshot(module, result)
    assert snapshot.detailed_sdm_ready is True
    assert snapshot.module_revision_id == module["revision_id"]
    assert snapshot.resolution_id == result["resolution_id"]
    _validate_resolution(result, "resolved-component-model")


def test_basic_csv_module_resolves_explicit_stc_temperature_fallback():
    result = resolve_module_model(
        _basic_csv_module(),
        resolution_id="resolve-module-basic",
    )

    assert result["status"] == "resolved"
    assert result["selected_model"]["model_id"] == "module.stc_tempco_linear.v0.1"
    assert any(item["kind"] == "fallback" for item in result["assumptions"])


def test_explicit_unavailable_module_model_blocks_instead_of_silent_fallback():
    result = resolve_module_model(
        _basic_csv_module(),
        resolution_id="resolve-module-explicit",
        requested_model_id="module.pvsyst_singlediode.v6",
    )

    assert result["status"] == "blocked"
    assert result["selected_model"] is None
    assert any(
        item["kind"] == "explicit_requirement" and item["severity"] == "blocking"
        for item in result["assumptions"]
    )


def test_real_jinko_pan_resolves_according_to_actual_sdm_validation_evidence():
    module = _jinko_module()
    result = resolve_module_model(module, resolution_id="resolve-module-jinko")

    assert result["status"] == "resolved"
    validation_passed = module["electrical_models"][0]["validation"]["passed"]
    expected = (
        "module.pvsyst_singlediode.v6"
        if validation_passed
        else "module.stc_tempco_linear.v0.1"
    )
    assert result["selected_model"]["model_id"] == expected


def test_huawei_ond_uses_detailed_efficiency_without_inventing_current_limit():
    inverter = _huawei_ond_inverter()
    result = resolve_inverter_model(
        inverter,
        resolution_id="resolve-inverter-huawei",
    )

    assert result["status"] == "resolved"
    assert (
        result["selected_model"]["model_id"]
        == "inverter.voltage_dependent_efficiency.v0.1"
    )
    enabled = {item["refinement_id"] for item in result["enabled_refinements"]}
    unavailable = {
        item["refinement_id"]: item for item in result["unavailable_refinements"]
    }

    assert "temperature_derating" in enabled
    assert "night_loss" in enabled
    assert "startup_threshold" in enabled
    assert "mppt_current_limit" not in enabled
    assert unavailable["mppt_current_limit"]["reason_code"] == (
        "PHYSICAL_MPPT_CURRENT_LIMIT_UNAVAILABLE"
    )
    assert result["capability_snapshot"]["basic_yield_ready"] is True
    assert result["capability_snapshot"]["mppt_current_limit_ready"] is False
    _validate_resolution(result, "resolved-component-model")


def test_huawei_datasheet_overlay_enables_current_limit_refinement_without_changing_efficiency_model():
    base = _huawei_ond_inverter()
    base_fragment = ComponentSourceFragment(
        source_id="src-manufacturer-huawei-sun2000-100ktl-m1",
        source_kind="manufacturer_component_file",
        priority=50,
        data=base,
    )
    overlay = parse_inverter_component_csv(
        "source_id,source_kind,source_priority,manufacturer,model,nominal_frequency_hz,"
        "mppt_max_operating_current_a,mppt_max_short_circuit_current_a\n"
        "src-huawei-datasheet,manufacturer_datasheet,100,Huawei Technologies,"
        "SUN2000-100KTL-M1,50,26,40\n"
    )[0]
    merged = build_candidate_from_fragments(
        "inverter",
        [base_fragment, overlay],
        candidate_id="candidate-phase1-huawei-overlay",
        definition_id="inv-huawei-sun2000-100ktl-m1",
        revision_id="inv-huawei-sun2000-100ktl-m1-r2",
    )["canonical_data"]

    result = resolve_inverter_model(
        merged,
        resolution_id="resolve-inverter-huawei-overlay",
    )

    assert result["status"] == "resolved"
    assert (
        result["selected_model"]["model_id"]
        == "inverter.voltage_dependent_efficiency.v0.1"
    )
    enabled = {item["refinement_id"] for item in result["enabled_refinements"]}
    assert "mppt_current_limit" in enabled
    assert result["capability_snapshot"]["mppt_current_limit_ready"] is True
    assert result["capability_snapshot"]["mppt_design_ready"] is True


def test_constant_efficiency_user_inverter_resolves_lower_fidelity_model():
    result = resolve_inverter_model(
        _constant_csv_inverter(),
        resolution_id="resolve-inverter-constant",
    )

    assert result["status"] == "resolved"
    assert (
        result["selected_model"]["model_id"]
        == "inverter.constant_efficiency.v0.1"
    )
    assert any(item["kind"] == "fallback" for item in result["assumptions"])
    assert result["capability_snapshot"]["basic_yield_ready"] is True
    assert result["capability_snapshot"]["mppt_current_limit_ready"] is False


def test_required_current_limit_blocks_huawei_ond_only_resolution():
    result = resolve_inverter_model(
        _huawei_ond_inverter(),
        resolution_id="resolve-inverter-required-current",
        required_refinements={"mppt_current_limit"},
    )

    assert result["status"] == "blocked"
    assert result["selected_model"] is not None
    assert any(
        item["kind"] == "explicit_requirement" and item["severity"] == "blocking"
        for item in result["assumptions"]
    )


def test_incomplete_inverter_without_efficiency_model_is_blocked():
    inverter = deepcopy(_constant_csv_inverter())
    inverter.pop("efficiency_model")

    result = resolve_inverter_model(
        inverter,
        resolution_id="resolve-inverter-incomplete",
    )

    assert result["status"] == "blocked"
    assert result["selected_model"] is None
    assert any(
        "supported executable efficiency_model" in item["source_paths"]
        for item in result["assumptions"]
        if item["severity"] == "blocking"
    )


def test_unknown_explicit_inverter_model_blocks_instead_of_substituting():
    result = resolve_inverter_model(
        _constant_csv_inverter(),
        resolution_id="resolve-inverter-explicit-unknown",
        requested_model_id="inverter.future_magic.v9",
    )

    assert result["status"] == "blocked"
    assert result["selected_model"] is None


def test_combined_resolution_is_schema_valid_and_collects_assumption_ledger():
    result = resolve_simulation_models(
        _synthetic_validated_module(),
        _huawei_ond_inverter(),
        resolution_id="resolve-system-001",
    )

    assert result["status"] == "resolved"
    assert result["module"]["status"] == "resolved"
    assert result["inverter"]["status"] == "resolved"
    assert len(result["assumptions"]) == (
        len(result["module"]["assumptions"])
        + len(result["inverter"]["assumptions"])
    )
    _validate_resolution(result, "simulation-model-resolution")


def test_resolution_schemas_are_valid_draft_2020_12():
    for filename in (
        "simulation-assumption.schema.json",
        "resolved-component-model.schema.json",
        "simulation-model-resolution.schema.json",
    ):
        schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
