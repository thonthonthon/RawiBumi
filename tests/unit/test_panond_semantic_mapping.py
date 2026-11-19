from pathlib import Path

import pytest

from components.candidates import build_inverter_candidate
import yaml
from jsonschema import Draft202012Validator

from components.mapping import load_mapping_ledger, semantic_map_document
from components.ond import parse_ond_text
from components.ond.mapper import LEDGER_PATH as OND_LEDGER_PATH, map_ond
from components.pan import parse_pan_text
from components.pan.mapper import LEDGER_PATH as PAN_LEDGER_PATH, map_pan
from components.panond_inventory import build_field_inventory


ROOT = Path(__file__).resolve().parents[2]
LEDGER_SCHEMA = ROOT / "components/schema/field-mapping-ledger.schema.json"


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_mapping_ledgers_validate_and_do_not_auto_map_unknown_rules():
    import json

    schema = json.loads(LEDGER_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    for ledger_path in (PAN_LEDGER_PATH, OND_LEDGER_PATH):
        data = yaml.safe_load(ledger_path.read_text(encoding="utf-8"))
        validator.validate(data)
        assert all(
            not item["auto_map"] or item["confidence"] not in {"unknown", "inferred"}
            for item in data["rules"]
        )


def test_pan_semantic_mapping_maps_supported_fields_and_preserves_unknowns():
    document = parse_pan_text(_text("tests/fixtures/panond/synthetic_module.pan"))
    result = map_pan(document)
    values = result.values_by_canonical_path

    assert values["manufacturer"] == "OpenSIMPV Synthetic"
    assert values["model"] == "SYN-MOD-550"
    assert values["mechanical.width_m"] == 1.134
    assert values["mechanical.height_m"] == 2.278
    assert values["stc.reference_irradiance_w_m2"] == 1000.0
    assert values["stc.reference_cell_temperature_c"] == 25.0
    assert values["stc.nominal_power_w"] == 550.0
    assert "stc.pmp_w" not in values
    assert values["stc.voc_v"] == 49.9
    assert values["stc.isc_a"] == 14.0
    assert values["stc.vmp_v"] == 41.96
    assert values["stc.imp_a"] == 13.11
    assert values["cell_architecture.cells_in_series"] == 72
    assert values["cell_architecture.cells_in_parallel"] == 2
    assert values["cell_architecture.bypass_diode_count"] == 3
    assert values["cell_architecture.source_layout_code"] == "slSyntheticHalfCells"
    assert values["electrical_models[pvsyst_singlediode].parameter_set.r_series_ohm"] == 0.203
    assert values["electrical_models[pvsyst_singlediode].parameter_set.r_shunt_ref_ohm"] == 300.0
    assert values["limits.max_system_voltage_iec_v"] == 1500.0
    assert values["limits.max_system_voltage_ul_v"] == 1500.0
    assert values["technology"] == "crystalline_silicon_mono"
    assert values["temperature_coefficients.alpha_isc_per_c"] == 0.00728
    assert values["temperature_coefficients.beta_voc_per_c"] == -0.128
    assert values["temperature_coefficients.gamma_pmp_relative_per_c"] == pytest.approx(-0.0034)

    unmapped_keys = [item["key"] for item in result.unmapped_fields]
    assert "Technol" not in unmapped_keys
    assert "muISC" not in unmapped_keys
    assert "muVocSpec" not in unmapped_keys
    assert "muPmpReq" not in unmapped_keys
    assert "UnknownFutureField" in unmapped_keys


def test_ond_semantic_mapping_maps_only_supported_nonambiguous_fields():
    document = parse_ond_text(_text("tests/fixtures/panond/synthetic_inverter.ond"))
    result = map_ond(document)
    values = result.values_by_canonical_path

    assert values["manufacturer"] == "OpenSIMPV Synthetic"
    assert values["model"] == "SYN-INV-250K"
    assert values["dc_limits.max_dc_voltage_v"] == 1500.0
    assert values["mppt_template.min_operating_voltage_v"] == 500.0
    assert values["mppt_template.max_operating_voltage_v"] == 1500.0
    assert values["mppt_template.count"] == 12
    assert values["mppt_template.total_input_count"] == 36
    assert values["phase_configuration"] == "three_phase"
    assert values["operating_thresholds.minimum_input_power_w"] == 500.0
    assert values["ac_limits.nominal_ac_power_w"] == pytest.approx(250000.0)
    assert values["ac_limits.max_ac_power_w"] == pytest.approx(250000.0)

    unmapped_keys = [item["key"] for item in result.unmapped_fields]
    assert "PNomConv" not in unmapped_keys
    assert "PMaxOUT" not in unmapped_keys
    assert "UnknownFutureField" in unmapped_keys


def test_duplicate_source_path_is_ambiguous_not_last_write_wins():
    _, rules = load_mapping_ledger(PAN_LEDGER_PATH)
    document = parse_pan_text(
        "PVObject_=pvModule\n"
        "  PVObject_Commercial=pvCommercial\n"
        "    Manufacturer=A\n"
        "    Manufacturer=B\n"
    )
    result = semantic_map_document(document, rules)

    assert "manufacturer" not in result.values_by_canonical_path
    assert any("Ambiguous duplicate source path" in warning for warning in result.warnings)


def test_field_inventory_collects_paths_files_counts_and_examples():
    pan = parse_pan_text(_text("tests/fixtures/panond/synthetic_module.pan"))
    ond = parse_ond_text(_text("tests/fixtures/panond/synthetic_inverter.ond"))
    inventory = build_field_inventory([("synthetic.pan", pan), ("synthetic.ond", ond)])

    by_path = {tuple(item["path"]): item for item in inventory}
    manufacturer = by_path[("PVObject_", "PVObject_Commercial", "Manufacturer")]
    assert manufacturer["occurrences"] == 2
    assert manufacturer["files"] == ["synthetic.ond", "synthetic.pan"]
    assert "OpenSIMPV Synthetic" in manufacturer["example_values"]


def test_unknown_pvsyst_technology_is_not_guessed():
    document = parse_pan_text(
        "PVObject_=pvModule\n"
        "  Technol=mtFutureUnknown\n"
    )
    result = map_pan(document)

    assert "technology" not in result.values_by_canonical_path
    assert any("unsupported PVsyst technology code" in warning for warning in result.warnings)
    assert any(item["key"] == "Technol" for item in result.unmapped_fields)



def test_manufacturer_jinko_pan_maps_optical_quality_and_iam_semantics():
    document = parse_pan_text(
        _text("tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN")
    )
    result = map_pan(document)
    values = result.values_by_canonical_path

    assert values["manufacturer"] == "Jinkosolar"
    assert values["model"] == "JKM550M-72HL4-V"
    assert values["technology"] == "crystalline_silicon_mono"
    assert values["mechanical.width_m"] == pytest.approx(1.134)
    assert values["mechanical.height_m"] == pytest.approx(2.278)
    assert values["stc.nominal_power_w"] == pytest.approx(550.0)
    assert values["stc.isc_a"] == pytest.approx(14.03)
    assert values["stc.voc_v"] == pytest.approx(49.62)
    assert values["stc.imp_a"] == pytest.approx(13.45)
    assert values["stc.vmp_v"] == pytest.approx(40.90)
    assert values["temperature_coefficients.alpha_isc_per_c"] == pytest.approx(0.00657)
    assert values["temperature_coefficients.beta_voc_per_c"] == pytest.approx(-0.1379)
    assert values["temperature_coefficients.gamma_pmp_relative_per_c"] == pytest.approx(-0.00345)
    assert values["cell_architecture.cells_in_series"] == 72
    assert values["cell_architecture.cells_in_parallel"] == 2
    assert values["cell_architecture.bypass_diode_count"] == 3
    assert values["electrical_models[pvsyst_singlediode].parameter_set.r_series_ohm"] == pytest.approx(0.238)
    assert values["electrical_models[pvsyst_singlediode].parameter_set.r_shunt_ref_ohm"] == pytest.approx(1100.0)
    assert values["limits.max_system_voltage_iec_v"] == pytest.approx(1500.0)
    assert values["limits.max_system_voltage_ul_v"] == pytest.approx(1500.0)

    assert values["quality.nameplate_power_tolerance.lower_fraction"] == pytest.approx(0.0)
    assert values["quality.nameplate_power_tolerance.upper_fraction"] == pytest.approx(0.03)
    assert values["optical.absorptance_fraction"] == pytest.approx(0.90)

    assert values["pan_iam_source.mode"] == "UserProfile"
    assert values["pan_iam_source.profile_type"] == "TCubicProfile"
    assert values["pan_iam_source.point_count"] == 9
    assert values["pan_iam_source.source_interpolation_mode_code"] == 3
    assert values["pan_iam_source.point_1"] == {
        "angle_deg": 0.0,
        "modifier": 1.0,
    }
    assert values["pan_iam_source.point_8"] == {
        "angle_deg": 85.0,
        "modifier": pytest.approx(0.743),
    }
    assert values["pan_iam_source.point_9"] == {
        "angle_deg": 90.0,
        "modifier": 0.0,
    }

    unmapped_keys = {item["key"] for item in result.unmapped_fields}
    for mapped_key in (
        "PNomTolLow",
        "PNomTolUp",
        "Absorb",
        "IAMMode",
        "IAMProfile",
        "NPtsEff",
        "Mode",
        "Point_1",
        "Point_2",
        "Point_3",
        "Point_4",
        "Point_5",
        "Point_6",
        "Point_7",
        "Point_8",
        "Point_9",
    ):
        assert mapped_key not in unmapped_keys

    # These source fields remain raw because 3.8A does not assign unsupported
    # electrical/reverse-bias/air-mass semantics merely to empty the unmapped ledger.
    assert "ARev" in unmapped_keys
    assert "BRev" in unmapped_keys
    assert "RDiode" in unmapped_keys
    assert "VRevDiode" not in unmapped_keys
    assert values["cell_architecture.bypass_diode_forward_voltage_v"] == pytest.approx(0.70)
    assert "AirMassRef" in unmapped_keys
    assert "CellArea" in unmapped_keys
    assert "SandiaAMCorr" in unmapped_keys


def test_manufacturer_huawei_ond_candidate_is_schema_ready_without_guessed_frequency():
    document = parse_ond_text(
        _text("tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND")
    )
    candidate = build_inverter_candidate(
        map_ond(document),
        candidate_id="cand-huawei-schema-ready",
        inverter_definition_id="inv-huawei-schema-ready",
        revision_id="inv-huawei-schema-ready-r1",
        source_id="src-huawei-schema-ready",
    )

    assert candidate["definition_schema_ready"] is True
    assert candidate["canonical_data"]["ac_limits"].get(
        "nominal_frequency_hz"
    ) is None
    assert not any(
        item["rule_id"] == "INVERTER_DEFINITION_SCHEMA_INCOMPLETE"
        for item in candidate["validation_findings"]
    )


def test_manufacturer_huawei_ond_maps_verified_power_efficiency_and_derating_fields():
    document = parse_ond_text(
        _text("tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND")
    )
    result = map_ond(document)
    values = result.values_by_canonical_path

    assert values["manufacturer"] == "Huawei Technologies"
    assert values["model"] == "SUN2000-100KTL-M1"
    assert values["dc_limits.max_dc_voltage_v"] == pytest.approx(1100.0)
    assert values["mppt_template.min_operating_voltage_v"] == pytest.approx(200.0)
    assert values["mppt_template.max_operating_voltage_v"] == pytest.approx(1000.0)
    assert values["mppt_template.nominal_voltage_v"] == pytest.approx(1000.0)
    assert values["mppt_template.count"] == 10
    assert values["mppt_template.total_input_count"] == 20
    assert values["phase_configuration"] == "three_phase"
    assert values["operating_thresholds.minimum_input_power_w"] == pytest.approx(500.0)
    assert values["operating_thresholds.night_loss_w"] == pytest.approx(2.0)

    assert values["ac_limits.nominal_ac_power_w"] == pytest.approx(100000.0)
    assert values["ac_limits.max_ac_power_w"] == pytest.approx(110000.0)
    assert values["ac_limits.nominal_ac_voltage_v"] == pytest.approx(380.0)
    assert values["ac_limits.nominal_ac_current_a"] == pytest.approx(152.0)
    assert values["ac_limits.max_ac_current_a"] == pytest.approx(168.8)

    assert values["array_sizing_limits.nominal_pv_array_power_w"] == pytest.approx(130000.0)
    assert values["array_sizing_limits.max_pv_array_power_w"] == pytest.approx(130000.0)
    assert values["array_sizing_limits.max_pv_current_a"] == pytest.approx(40.0)

    assert values["efficiency_model.reference_metrics.max_efficiency_fraction"] == pytest.approx(0.9897)
    assert values["efficiency_model.reference_metrics.european_efficiency_fraction"] == pytest.approx(0.9882)
    assert values["ond_efficiency_source.voltages_v"] == [200.0, 650.0, 1000.0]
    assert values["ond_efficiency_source.profile_mode"] == "POutf_PIn"
    assert values["ond_efficiency_source.profiles.v1.point_count"] == 8
    assert values["ond_efficiency_source.profiles.v2.point_count"] == 8
    assert values["ond_efficiency_source.profiles.v3.point_count"] == 8
    assert values["ond_efficiency_source.profiles.v2.point_7"] == {
        "dc_power_w": 60000.0,
        "ac_power_w": 59280.0,
    }
    assert values["ond_efficiency_source.profiles.v3.point_8"] == {
        "dc_power_w": 100000.0,
        "ac_power_w": 98660.4,
    }

    assert values["temperature_derating_model.max_power_temperature_c"] == pytest.approx(30.0)
    assert values["temperature_derating_model.nominal_power_temperature_c"] == pytest.approx(40.0)
    assert values["temperature_derating_model.limit1_temperature_c"] == pytest.approx(60.0)
    assert values["temperature_derating_model.limit1_power_w"] == pytest.approx(36000.0)
    assert values["temperature_derating_model.absolute_limit_temperature_c"] == pytest.approx(62.0)

    unmapped_keys = {item["key"] for item in result.unmapped_fields}
    # Current scope is deliberately conservative. IDCMax=0 is not promoted to
    # a physical MPPT operating-current limit, and the OND does not encode the
    # Huawei datasheet's separate 26 A max operating current per MPPT.
    assert "IDCMax" in unmapped_keys
    assert "IMaxDC" not in unmapped_keys

    # These efficiency metadata fields are still preserved until their exact
    # canonical role is needed; the actual Pin/Pout profiles are already mapped.
    assert "EfficMaxV" in unmapped_keys
    assert "EfficEuroV" in unmapped_keys
    assert "PInEffMax" in unmapped_keys
    assert "PThreshEff" in unmapped_keys


def test_manufacturer_fixture_inventory_exposes_real_nested_profiles_for_future_mapping():
    pan = parse_pan_text(
        _text("tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN")
    )
    ond = parse_ond_text(
        _text("tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND")
    )
    inventory = build_field_inventory([
        ("JKM550M-72HL4-V_SGS_6079M3.PAN", pan),
        ("Huawei_Sun2000_100KTL_M1.OND", ond),
    ])

    paths = {tuple(item["path"]) for item in inventory}
    assert ("PVObject_", "PVObject_IAM", "IAMProfile", "Point_9") in paths
    assert ("PVObject_", "Converter", "ProfilPIO", "Point_8") in paths
    assert ("PVObject_", "Converter", "ProfilPIOV3", "Point_8") in paths
