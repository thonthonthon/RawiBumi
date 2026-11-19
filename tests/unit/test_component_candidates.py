import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from components.candidates import (
    build_inverter_candidate,
    build_module_candidate,
    finalize_candidate,
)
from components.ond import parse_ond_text
from components.ond.mapper import map_ond
from components.pan import parse_pan_text
from components.pan.mapper import map_pan
from components.pan.pvsyst_sdm import (
    PVSystOffSTCValidationConfig,
    PVSystSDMValidationConfig,
    derive_reference_currents,
    validate_at_stc,
    validate_off_stc_matrix,
)
from components.validation import (
    ValidationConfig,
    inverter_capabilities,
    module_capabilities,
    validate_inverter,
    validate_module,
)


ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_component_candidate_schema_and_fixture():
    schema = json.loads(
        (ROOT / "components/schema/component-candidate.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    fixture = json.loads(
        (ROOT / "tests/fixtures/schema/component-candidate.example.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(fixture)


def test_pan_mapping_builds_validated_pvsyst_sdm_candidate():
    mapping = map_pan(parse_pan_text(_text("tests/fixtures/panond/synthetic_module.pan")))
    candidate = build_module_candidate(
        mapping,
        candidate_id="cand-mod-001",
        module_definition_id="mod-001",
        revision_id="mod-001-r1",
        source_id="src-pan-001",
    )

    data = candidate["canonical_data"]
    assert candidate["definition_schema_ready"] is True
    assert candidate["status"] == "schema_ready"
    assert data["manufacturer"] == "OpenSIMPV Synthetic"
    assert data["stc"]["nominal_power_w"] == 550.0
    assert data["stc"]["pmp_w"] == pytest.approx(41.96 * 13.11)
    assert candidate["derivations"][0]["target_path"] == "stc.pmp_w"
    assert candidate["derivations"][0]["estimated"] is False

    assert data["technology"] == "crystalline_silicon_mono"
    assert data["temperature_coefficients"]["alpha_isc_per_c"] == pytest.approx(0.00728)
    assert data["temperature_coefficients"]["beta_voc_per_c"] == pytest.approx(-0.128)
    assert data["temperature_coefficients"]["gamma_pmp_per_c"] == pytest.approx(
        -0.0034 * data["stc"]["pmp_w"]
    )
    assert data["temperature_coefficients"]["coefficient_basis"] == "absolute"

    model = data["electrical_models"][0]
    assert model["model_type"] == "pvsyst_singlediode"
    assert model["validation"]["status"] == "passed"
    assert model["validation"]["passed"] is True
    assert model["validation"]["stc"]["status"] == "passed"
    assert model["validation"]["stc"]["implementation"] == "pvlib-python"
    assert model["validation"]["off_stc"]["status"] == "passed"
    assert model["validation"]["off_stc"]["implementation"] == "pvlib-python"
    assert model["validation"]["off_stc"]["grid"]["point_count"] == 12
    assert model["parameter_set"]["energy_bandgap_ref_ev"] == pytest.approx(1.121)
    assert model["parameter_set"]["photocurrent_ref_a"] == pytest.approx(
        14.009473333391727, rel=1e-10
    )
    assert model["parameter_set"]["saturation_current_ref_a"] == pytest.approx(
        1.538465928882609e-11, rel=1e-10
    )

    assert candidate["capability_flags"]["layout_ready"] is True
    assert candidate["capability_flags"]["basic_yield_ready"] is True
    assert candidate["capability_flags"]["detailed_sdm_ready"] is True

    finalized = finalize_candidate(candidate)
    assert finalized["verification_state"] == "auto_validated"


def test_module_basic_yield_requires_temperature_coefficients_and_source():
    data = {
        "manufacturer": "Example",
        "model": "M1",
        "source_ids": ["src-1"],
        "mechanical": {"width_m": 1.1, "height_m": 2.0},
        "stc": {
            "pmp_w": 500.0,
            "voc_v": 50.0,
            "isc_a": 13.0,
            "vmp_v": 40.0,
            "imp_a": 12.5,
            "reference_irradiance_w_m2": 1000.0,
            "reference_cell_temperature_c": 25.0,
        },
    }
    findings = validate_module(data)
    assert module_capabilities(data, findings)["basic_yield_ready"] is False

    data["temperature_coefficients"] = {
        "alpha_isc_per_c": 0.0004,
        "beta_voc_per_c": -0.0025,
        "gamma_pmp_per_c": -0.003,
    }
    findings = validate_module(data)
    assert module_capabilities(data, findings)["basic_yield_ready"] is True


def test_module_validation_detects_electrical_inconsistency_and_configurable_pmp_tolerance():
    data = {
        "manufacturer": "Example",
        "model": "Bad",
        "source_ids": ["src-1"],
        "mechanical": {"width_m": 1.0, "height_m": 2.0},
        "stc": {
            "pmp_w": 500.0,
            "voc_v": 39.0,
            "isc_a": 10.0,
            "vmp_v": 40.0,
            "imp_a": 11.0,
            "reference_irradiance_w_m2": 1000.0,
            "reference_cell_temperature_c": 25.0,
        },
        "limits": {"max_system_voltage_v": 30.0},
    }
    findings = validate_module(data, config=ValidationConfig(stc_power_relative_tolerance=0.01))
    rule_ids = {item["rule_id"] for item in findings}

    assert "MODULE_VOC_NOT_ABOVE_VMP" in rule_ids
    assert "MODULE_ISC_BELOW_IMP" in rule_ids
    assert "MODULE_PMP_VMP_IMP_MISMATCH" in rule_ids
    assert "MODULE_SYSTEM_VOLTAGE_BELOW_VOC" in rule_ids


def test_ond_mapping_builds_partial_inverter_candidate_without_fabricating_missing_limits():
    mapping = map_ond(parse_ond_text(_text("tests/fixtures/panond/synthetic_inverter.ond")))
    candidate = build_inverter_candidate(
        mapping,
        candidate_id="cand-inv-001",
        inverter_definition_id="inv-001",
        revision_id="inv-001-r1",
        source_id="src-ond-001",
    )

    data = candidate["canonical_data"]
    assert data["manufacturer"] == "OpenSIMPV Synthetic"
    assert data["dc_limits"]["max_dc_voltage_v"] == 1500.0
    assert data["mppt_template"]["count"] == 12
    assert "max_operating_current_a" not in data["mppt_template"]
    assert data["ac_limits"]["nominal_ac_power_w"] == pytest.approx(250000.0)
    assert data["ac_limits"]["max_ac_power_w"] == pytest.approx(250000.0)
    assert "nominal_ac_voltage_v" not in data["ac_limits"]
    assert "nominal_frequency_hz" not in data["ac_limits"]
    assert "efficiency_model" not in data

    assert candidate["definition_schema_ready"] is False
    assert candidate["status"] == "needs_review"
    assert candidate["capability_flags"]["mppt_design_ready"] is False
    assert candidate["capability_flags"]["basic_design_ready"] is False
    assert candidate["capability_flags"]["basic_yield_ready"] is False

    with pytest.raises(ValueError, match="definition-schema ready"):
        finalize_candidate(candidate)


def test_inverter_validation_and_capabilities_for_complete_manual_candidate():
    data = {
        "manufacturer": "Example",
        "model": "INV1",
        "source_ids": ["src-1"],
        "phase_configuration": "three_phase",
        "dc_limits": {"max_dc_voltage_v": 1100.0},
        "ac_limits": {
            "nominal_ac_power_w": 100000.0,
            "nominal_ac_voltage_v": 400.0,
            "nominal_frequency_hz": 50.0,
        },
        "mppt_template": {
            "count": 4,
            "min_operating_voltage_v": 200.0,
            "max_operating_voltage_v": 1000.0,
            "max_operating_current_a": 32.0,
            "max_short_circuit_current_a": 40.0,
        },
        "efficiency_model": {
            "model_type": "constant",
            "efficiency_fraction": 0.98,
        },
    }

    findings = validate_inverter(data)
    capabilities = inverter_capabilities(data, findings)
    assert not [item for item in findings if item["severity"] in {"error", "blocking_error"}]
    assert capabilities["mppt_design_ready"] is True
    assert capabilities["basic_design_ready"] is True
    assert capabilities["basic_yield_ready"] is True


def test_inverter_validation_catches_bad_mppt_range_and_current_order():
    data = {
        "manufacturer": "Example",
        "model": "INV-BAD",
        "source_ids": ["src-1"],
        "phase_configuration": "three_phase",
        "dc_limits": {"max_dc_voltage_v": 900.0},
        "ac_limits": {
            "nominal_ac_power_w": 100000.0,
            "nominal_ac_voltage_v": 400.0,
            "nominal_frequency_hz": 50.0,
        },
        "mppt_template": {
            "count": 2,
            "min_operating_voltage_v": 950.0,
            "max_operating_voltage_v": 1000.0,
            "max_operating_current_a": 40.0,
            "max_short_circuit_current_a": 35.0,
        },
    }
    findings = validate_inverter(data)
    rule_ids = {item["rule_id"] for item in findings}

    assert "INVERTER_MPPT_MAX_ABOVE_ABSOLUTE_DC_MAX" in rule_ids
    assert "INVERTER_MPPT_ISC_BELOW_OPERATING_CURRENT" in rule_ids


def test_finalize_rejects_engineering_errors_even_when_schema_ready_flag_is_forced():
    mapping = map_pan(parse_pan_text(_text("tests/fixtures/panond/synthetic_module.pan")))
    candidate = build_module_candidate(
        mapping,
        candidate_id="cand-mod-002",
        module_definition_id="mod-002",
        revision_id="mod-002-r1",
        source_id="src-pan-001",
    )
    candidate = deepcopy(candidate)
    candidate["validation_findings"].append(
        {
            "rule_id": "SYNTHETIC_ERROR",
            "severity": "error",
            "category": "test",
            "field_path": None,
            "message": "Synthetic error",
            "measured_value": None,
            "limit_value": None,
            "unit": None,
            "context": {},
        }
    )

    with pytest.raises(ValueError, match="engineering validation errors"):
        finalize_candidate(candidate)


def test_reference_current_derivation_matches_independent_analytical_values():
    result = derive_reference_currents(
        isc_a=14.0,
        voc_v=49.9,
        r_series_ohm=0.203,
        r_shunt_ref_ohm=300.0,
        gamma_ref=0.98,
        cells_in_series=72,
        reference_cell_temperature_c=25.0,
    )
    assert result["photocurrent_ref_a"] == pytest.approx(14.009473333391727, rel=1e-10)
    assert result["saturation_current_ref_a"] == pytest.approx(
        1.538465928882609e-11, rel=1e-10
    )
    assert result["n_ns_vth_ref_v"] == pytest.approx(1.8128683827838175, rel=1e-10)


def test_pvsyst_sdm_validation_fails_when_series_resistance_is_perturbed():
    mapping = map_pan(parse_pan_text(_text("tests/fixtures/panond/synthetic_module.pan")))
    candidate = build_module_candidate(
        mapping,
        candidate_id="cand-mod-perturb-source",
        module_definition_id="mod-perturb-source",
        revision_id="mod-perturb-source-r1",
        source_id="src-pan-001",
    )
    data = deepcopy(candidate["canonical_data"])
    params = deepcopy(data["electrical_models"][0]["parameter_set"])
    params["r_series_ohm"] = 2.0

    validation = validate_at_stc(
        data,
        params,
        config=PVSystSDMValidationConfig(point_relative_tolerance=0.02),
    )
    assert validation["passed"] is False
    assert validation["status"] == "failed"
    assert any(
        not residual["within_tolerance"]
        for residual in validation["residuals"].values()
    )



def test_off_stc_matrix_reproduces_regression_anchor_points_and_temperature_slopes():
    mapping = map_pan(parse_pan_text(_text("tests/fixtures/panond/synthetic_module.pan")))
    candidate = build_module_candidate(
        mapping,
        candidate_id="cand-off-stc",
        module_definition_id="mod-off-stc",
        revision_id="mod-off-stc-r1",
        source_id="src-pan-001",
    )
    data = candidate["canonical_data"]
    validation = data["electrical_models"][0]["validation"]["off_stc"]

    assert validation["status"] == "passed"
    assert validation["point_check_summary"] == {
        "passed": True,
        "passed_count": 12,
        "total_count": 12,
    }
    assert validation["trend_check_summary"]["passed"] is True
    assert validation["coefficient_check_summary"]["passed"] is True

    by_point = {
        (
            point["effective_irradiance_w_m2"],
            point["cell_temperature_c"],
        ): point["modeled"]
        for point in validation["points"]
    }

    anchor_200_0 = by_point[(200.0, 0.0)]
    assert anchor_200_0["isc_a"] == pytest.approx(2.7648429649, rel=1e-7)
    assert anchor_200_0["voc_v"] == pytest.approx(50.3203762489, rel=1e-7)
    assert anchor_200_0["pmp_w"] == pytest.approx(115.7705775445, rel=1e-7)

    anchor_600_50 = by_point[(600.0, 50.0)]
    assert anchor_600_50["isc_a"] == pytest.approx(8.5100311327, rel=1e-7)
    assert anchor_600_50["voc_v"] == pytest.approx(45.7227744393, rel=1e-7)
    assert anchor_600_50["pmp_w"] == pytest.approx(305.2207439830, rel=1e-7)

    anchor_1000_75 = by_point[(1000.0, 75.0)]
    assert anchor_1000_75["isc_a"] == pytest.approx(14.3637538147, rel=1e-7)
    assert anchor_1000_75["voc_v"] == pytest.approx(43.5137691114, rel=1e-7)
    assert anchor_1000_75["pmp_w"] == pytest.approx(467.0618304409, rel=1e-7)

    alpha = validation["coefficient_checks"]["alpha_isc_per_c"]
    beta = validation["coefficient_checks"]["beta_voc_per_c"]
    gamma = validation["coefficient_checks"]["gamma_pmp_per_c"]

    assert alpha["modeled_value"] == pytest.approx(0.007275077188, rel=1e-7)
    assert beta["modeled_value"] == pytest.approx(-0.125667825869, rel=1e-7)
    assert gamma["modeled_value"] == pytest.approx(-1.62032724977, rel=1e-7)

    assert alpha["relative_error"] < 0.02
    assert beta["relative_error"] < 0.05
    assert gamma["relative_error"] < 0.15


def test_off_stc_matrix_is_incomplete_without_source_temperature_coefficients():
    mapping = map_pan(parse_pan_text(_text("tests/fixtures/panond/synthetic_module.pan")))
    candidate = build_module_candidate(
        mapping,
        candidate_id="cand-off-stc-missing",
        module_definition_id="mod-off-stc-missing",
        revision_id="mod-off-stc-missing-r1",
        source_id="src-pan-001",
    )
    data = deepcopy(candidate["canonical_data"])
    del data["temperature_coefficients"]["beta_voc_per_c"]
    params = data["electrical_models"][0]["parameter_set"]

    validation = validate_off_stc_matrix(data, params)

    assert validation["status"] == "incomplete"
    assert validation["passed"] is False
    assert validation["missing_source_coefficients"] == ["beta_voc_per_c"]


def test_off_stc_matrix_detects_too_tight_source_coefficient_tolerance():
    mapping = map_pan(parse_pan_text(_text("tests/fixtures/panond/synthetic_module.pan")))
    candidate = build_module_candidate(
        mapping,
        candidate_id="cand-off-stc-tight",
        module_definition_id="mod-off-stc-tight",
        revision_id="mod-off-stc-tight-r1",
        source_id="src-pan-001",
    )
    data = candidate["canonical_data"]
    params = data["electrical_models"][0]["parameter_set"]

    validation = validate_off_stc_matrix(
        data,
        params,
        config=PVSystOffSTCValidationConfig(gamma_pmp_relative_tolerance=0.01),
    )

    assert validation["status"] == "failed"
    assert validation["passed"] is False
    assert validation["coefficient_checks"]["gamma_pmp_per_c"]["passed"] is False
    assert validation["point_check_summary"]["passed"] is True
    assert validation["trend_check_summary"]["passed"] is True



def test_manufacturer_jinko_pan_builds_real_module_candidate():
    mapping = map_pan(
        parse_pan_text(
            _text("tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN")
        )
    )
    candidate = build_module_candidate(
        mapping,
        candidate_id="cand-jinko-jkm550",
        module_definition_id="mod-jinko-jkm550m-72hl4-v",
        revision_id="mod-jinko-jkm550m-72hl4-v-r1",
        source_id="src-manufacturer-jinko-jkm550m-72hl4-v",
    )

    data = candidate["canonical_data"]
    assert candidate["definition_schema_ready"] is True
    assert data["manufacturer"] == "Jinkosolar"
    assert data["model"] == "JKM550M-72HL4-V"
    assert data["stc"]["nominal_power_w"] == pytest.approx(550.0)
    assert data["stc"]["pmp_w"] == pytest.approx(40.90 * 13.45)
    assert data["capability_flags"]["layout_ready"] is True
    assert data["capability_flags"]["basic_yield_ready"] is True

    assert data["optical"]["absorptance_fraction"] == pytest.approx(0.90)
    assert data["optical"]["absorptance_source_ids"] == [
        "src-manufacturer-jinko-jkm550m-72hl4-v"
    ]
    iam = data["optical"]["iam"]
    assert iam["model_type"] == "tabulated"
    assert iam["execution_model_id"] == "iam.tabulated.pvlib_interp.v0.1"
    assert iam["interpolation_method"] == "cubic"
    assert iam["normalize"] is True
    assert iam["source_mode"] == "UserProfile"
    assert iam["source_profile_type"] == "TCubicProfile"
    assert iam["source_interpolation_mode_code"] == 3
    assert len(iam["points"]) == 9
    assert iam["points"][0] == {"angle_deg": 0.0, "modifier": 1.0}
    assert iam["points"][-1] == {"angle_deg": 90.0, "modifier": 0.0}
    assert iam["source_ids"] == ["src-manufacturer-jinko-jkm550m-72hl4-v"]

    quality = data["quality"]
    tolerance = quality["nameplate_power_tolerance"]
    assert tolerance["lower_fraction"] == pytest.approx(0.0)
    assert tolerance["upper_fraction"] == pytest.approx(0.03)
    assert quality["default_module_quality_loss_fraction"] == pytest.approx(-0.0075)
    assert quality["default_module_quality_method"] == (
        "pvsyst_tolerance_quarter_range.v0.1"
    )

    derivation_targets = {item["target_path"] for item in candidate["derivations"]}
    assert "optical.iam" in derivation_targets
    assert "quality.default_module_quality_loss_fraction" in derivation_targets

    model = data["electrical_models"][0]
    assert model["model_type"] == "pvsyst_singlediode"
    assert model["validation"]["stc"]["status"] == "passed"
    # The real manufacturer PAN must be run through the same off-STC gate as
    # synthetic fixtures; no manufacturer-specific bypass is allowed.
    assert model["validation"]["off_stc"]["status"] in {"passed", "failed"}
    assert model["validation"]["off_stc"]["grid"]["point_count"] == 12


def test_manufacturer_huawei_ond_builds_power_efficiency_and_derating_candidate_but_keeps_current_gap():
    mapping = map_ond(
        parse_ond_text(
            _text("tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND")
        )
    )
    candidate = build_inverter_candidate(
        mapping,
        candidate_id="cand-huawei-100ktl-m1",
        inverter_definition_id="inv-huawei-sun2000-100ktl-m1",
        revision_id="inv-huawei-sun2000-100ktl-m1-r1",
        source_id="src-manufacturer-huawei-sun2000-100ktl-m1",
    )

    data = candidate["canonical_data"]
    assert data["manufacturer"] == "Huawei Technologies"
    assert data["model"] == "SUN2000-100KTL-M1"

    assert data["dc_limits"]["max_dc_voltage_v"] == pytest.approx(1100.0)
    assert data["mppt_template"]["count"] == 10
    assert data["mppt_template"]["total_input_count"] == 20
    assert data["mppt_template"]["min_operating_voltage_v"] == pytest.approx(200.0)
    assert data["mppt_template"]["max_operating_voltage_v"] == pytest.approx(1000.0)
    assert data["mppt_template"]["nominal_voltage_v"] == pytest.approx(1000.0)
    assert "max_operating_current_a" not in data["mppt_template"]

    assert data["ac_limits"]["nominal_ac_power_w"] == pytest.approx(100000.0)
    assert data["ac_limits"]["max_ac_power_w"] == pytest.approx(110000.0)
    assert data["ac_limits"]["nominal_ac_voltage_v"] == pytest.approx(380.0)
    assert data["ac_limits"]["nominal_ac_current_a"] == pytest.approx(152.0)
    assert data["ac_limits"]["max_ac_current_a"] == pytest.approx(168.8)

    assert data["array_sizing_limits"]["nominal_pv_array_power_w"] == pytest.approx(130000.0)
    assert data["array_sizing_limits"]["max_pv_array_power_w"] == pytest.approx(130000.0)
    assert data["array_sizing_limits"]["max_pv_current_a"] == pytest.approx(40.0)

    efficiency = data["efficiency_model"]
    assert efficiency["model_type"] == "voltage_dependent_curves"
    assert efficiency["curve_power_basis"] == "dc_input_to_ac_output"
    assert efficiency["voltage_interpolation"] == "quadratic"
    assert efficiency["reference_metrics"]["max_efficiency_fraction"] == pytest.approx(0.9897)
    assert efficiency["reference_metrics"]["european_efficiency_fraction"] == pytest.approx(0.9882)
    assert [curve["dc_voltage_v"] for curve in efficiency["curves"]] == [200.0, 650.0, 1000.0]
    assert all(len(curve["points"]) == 8 for curve in efficiency["curves"])
    assert efficiency["curves"][1]["points"][6] == {
        "dc_power_w": 60000.0,
        "ac_power_w": 59280.0,
        "efficiency_fraction": pytest.approx(0.988),
    }
    assert efficiency["curves"][2]["points"][7]["efficiency_fraction"] == pytest.approx(0.986604)

    derating = data["temperature_derating_model"]
    assert derating["max_power_temperature_c"] == pytest.approx(30.0)
    assert derating["nominal_power_temperature_c"] == pytest.approx(40.0)
    assert derating["limit1_temperature_c"] == pytest.approx(60.0)
    assert derating["limit1_power_w"] == pytest.approx(36000.0)
    assert derating["absolute_limit_temperature_c"] == pytest.approx(62.0)
    assert derating["temperature_basis"] == "unknown"
    assert derating["source_model"] == "pvsyst_special_output_conditions"

    assert data["operating_thresholds"]["night_loss_w"] == pytest.approx(2.0)
    assert candidate["derivations"]
    assert candidate["derivations"][0]["target_path"] == "efficiency_model.curves"

    # The OND now provides most simulation semantics, but it still does not
    # provide a verified physical max operating current per MPPT (Huawei's
    # datasheet value is 26 A). Design/current-limit readiness remains false,
    # while voltage/efficiency-based energy simulation is still available.
    assert candidate["capability_flags"]["mppt_voltage_ready"] is True
    assert candidate["capability_flags"]["mppt_current_limit_ready"] is False
    assert candidate["capability_flags"]["mppt_design_ready"] is False
    assert candidate["capability_flags"]["basic_design_ready"] is False
    assert candidate["capability_flags"]["basic_yield_ready"] is True
    assert candidate["capability_flags"]["detailed_efficiency_ready"] is True
    assert candidate["capability_flags"]["derating_ready"] is True

    # Nominal grid frequency remains unknown because this OND does not
    # establish it. The canonical schema now preserves that absence instead of
    # requiring a guessed 50/60 Hz value. This is separate from the real MPPT
    # current-limit capability gap above.
    assert data["ac_limits"].get("nominal_frequency_hz") is None
    assert candidate["definition_schema_ready"] is True
    assert candidate["status"] == "schema_ready"
    assert not any(
        item["rule_id"] == "INVERTER_DEFINITION_SCHEMA_INCOMPLETE"
        for item in candidate["validation_findings"]
    )

    error_findings = [
        item for item in candidate["validation_findings"]
        if item["severity"] in {"error", "blocking_error"}
    ]
    assert not error_findings

