from pathlib import Path

import pytest

from components.candidates import build_inverter_candidate
from components.ond import parse_ond_text
from components.ond.mapper import map_ond
from components.source_overlay import (
    ComponentSourceFragment,
    build_candidate_from_fragments,
    merge_component_fragments,
)
from components.user_csv import (
    parse_inverter_component_csv,
    parse_inverter_efficiency_curve_csv,
    parse_module_component_csv,
)
from components.user_yaml import parse_component_overlay_yaml


ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_module_csv_builds_basic_yield_candidate_without_requiring_pan():
    csv_text = (
        "source_id,source_kind,manufacturer,model,width_mm,height_mm,pmp_w,voc_v,"
        "isc_a,vmp_v,imp_a,reference_irradiance_w_m2,reference_cell_temperature_c,"
        "alpha_isc_pct_per_c,beta_voc_pct_per_c,gamma_pmp_pct_per_c,"
        "max_system_voltage_v\n"
        "src-user-mod,manufacturer_datasheet,Example Solar,EX-550,1134,2278,550,"
        "49.62,14.03,40.90,13.45,1000,25,0.047,-0.278,-0.345,1500\n"
    )
    fragments = parse_module_component_csv(csv_text)
    candidate = build_candidate_from_fragments(
        "module",
        fragments,
        candidate_id="cand-user-module",
        definition_id="mod-user-550",
        revision_id="mod-user-550-r1",
    )

    data = candidate["canonical_data"]
    assert data["mechanical"]["width_m"] == pytest.approx(1.134)
    assert data["mechanical"]["height_m"] == pytest.approx(2.278)
    assert data["temperature_coefficients"]["alpha_isc_per_c"] == pytest.approx(
        0.00047 * 14.03
    )
    assert data["temperature_coefficients"]["beta_voc_per_c"] == pytest.approx(
        -0.00278 * 49.62
    )
    assert data["temperature_coefficients"]["gamma_pmp_per_c"] == pytest.approx(
        -0.00345 * 550.0
    )
    assert candidate["capability_flags"]["layout_ready"] is True
    assert candidate["capability_flags"]["basic_yield_ready"] is True
    assert candidate["capability_flags"]["detailed_sdm_ready"] is False
    assert data["source_ids"] == ["src-user-mod"]


def test_inverter_csv_allows_basic_yield_without_mppt_current_limit():
    csv_text = (
        "source_id,source_kind,manufacturer,model,phase_configuration,max_dc_voltage_v,"
        "nominal_ac_power_w,nominal_ac_voltage_v,nominal_frequency_hz,mppt_count,"
        "mppt_min_voltage_v,mppt_max_voltage_v,constant_efficiency_pct\n"
        "src-user-inv,manufacturer_datasheet,Example Power,EX-100K,three_phase,1100,"
        "100000,400,50,10,200,1000,98.5\n"
    )
    fragments = parse_inverter_component_csv(csv_text)
    candidate = build_candidate_from_fragments(
        "inverter",
        fragments,
        candidate_id="cand-user-inverter",
        definition_id="inv-user-100k",
        revision_id="inv-user-100k-r1",
    )

    caps = candidate["capability_flags"]
    assert caps["mppt_voltage_ready"] is True
    assert caps["mppt_current_limit_ready"] is False
    assert caps["mppt_design_ready"] is False
    assert caps["basic_design_ready"] is False
    assert caps["basic_yield_ready"] is True
    assert caps["detailed_efficiency_ready"] is False
    assert candidate["definition_schema_ready"] is True


def test_huawei_ond_plus_datasheet_overlay_refines_design_without_replacing_curves():
    base_candidate = build_inverter_candidate(
        map_ond(
            parse_ond_text(
                _text("tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND")
            )
        ),
        candidate_id="cand-huawei-base",
        inverter_definition_id="inv-huawei-base",
        revision_id="inv-huawei-base-r1",
        source_id="src-huawei-ond",
    )
    base_fragment = ComponentSourceFragment(
        source_id="src-huawei-ond",
        source_kind="manufacturer_component_file",
        priority=50,
        data=base_candidate["canonical_data"],
    )

    overlay_csv = (
        "source_id,source_kind,source_priority,manufacturer,model,nominal_frequency_hz,"
        "mppt_max_operating_current_a,mppt_max_short_circuit_current_a\n"
        "src-huawei-datasheet,manufacturer_datasheet,100,Huawei Technologies,"
        "SUN2000-100KTL-M1,50,26,40\n"
    )
    overlay = parse_inverter_component_csv(overlay_csv)[0]

    candidate = build_candidate_from_fragments(
        "inverter",
        [base_fragment, overlay],
        candidate_id="cand-huawei-multisource",
        definition_id="inv-huawei-sun2000-100ktl-m1",
        revision_id="inv-huawei-sun2000-100ktl-m1-r2",
    )

    data = candidate["canonical_data"]
    caps = candidate["capability_flags"]

    assert data["mppt_template"]["max_operating_current_a"] == pytest.approx(26.0)
    assert data["mppt_template"]["max_short_circuit_current_a"] == pytest.approx(40.0)
    assert data["ac_limits"]["nominal_frequency_hz"] == pytest.approx(50.0)
    assert len(data["efficiency_model"]["curves"]) == 3
    assert caps["mppt_voltage_ready"] is True
    assert caps["mppt_current_limit_ready"] is True
    assert caps["mppt_design_ready"] is True
    assert caps["basic_design_ready"] is True
    assert caps["basic_yield_ready"] is True
    assert caps["detailed_efficiency_ready"] is True
    assert caps["derating_ready"] is True
    assert candidate["definition_schema_ready"] is True

    provenance = candidate["field_provenance"]["mppt_template.max_operating_current_a"]
    assert provenance[-1]["source_id"] == "src-huawei-datasheet"


def test_equal_priority_conflicts_require_explicit_resolution():
    a = ComponentSourceFragment(
        source_id="a",
        priority=100,
        data={"manufacturer": "Same", "model": "M1", "stc": {"voc_v": 50.0}},
    )
    b = ComponentSourceFragment(
        source_id="b",
        priority=100,
        data={"manufacturer": "Same", "model": "M1", "stc": {"voc_v": 51.0}},
    )
    with pytest.raises(ValueError, match="equal-priority source conflict"):
        merge_component_fragments([a, b])


def test_component_identity_cannot_be_changed_by_priority():
    a = ComponentSourceFragment(
        source_id="a",
        priority=10,
        data={"manufacturer": "Maker A", "model": "M1"},
    )
    b = ComponentSourceFragment(
        source_id="b",
        priority=1000,
        data={"manufacturer": "Maker B", "model": "M1"},
    )
    with pytest.raises(ValueError, match="component identity conflict"):
        merge_component_fragments([a, b])


def test_inverter_efficiency_curve_csv_builds_voltage_dependent_overlay():
    text = (
        "source_id,manufacturer,model,dc_voltage_v,dc_power_w,ac_power_w,efficiency_pct\n"
        "effsrc,Maker,INV,400,1000,970,\n"
        "effsrc,Maker,INV,400,5000,4900,\n"
        "effsrc,Maker,INV,800,1000,,96\n"
        "effsrc,Maker,INV,800,5000,,98\n"
    )
    fragment = parse_inverter_efficiency_curve_csv(text)[0]
    curves = fragment.data["efficiency_model"]["curves"]

    assert [curve["dc_voltage_v"] for curve in curves] == [400.0, 800.0]
    assert curves[0]["points"][0]["efficiency_fraction"] == pytest.approx(0.97)
    assert curves[1]["points"][0]["ac_power_w"] == pytest.approx(960.0)
    assert curves[1]["points"][1]["efficiency_fraction"] == pytest.approx(0.98)


def test_advanced_yaml_overlay_prunes_null_placeholder_fields():
    text = """
component_type: inverter
source:
  source_id: datasheet-1
  source_kind: manufacturer_datasheet
  priority: 100
data:
  manufacturer: Example
  model: INV-1
  ac_limits:
    nominal_frequency_hz: 50
    max_ac_current_a: null
  efficiency_model:
    curves: []
"""
    component_type, fragment = parse_component_overlay_yaml(text)

    assert component_type == "inverter"
    assert fragment.data == {
        "manufacturer": "Example",
        "model": "INV-1",
        "ac_limits": {"nominal_frequency_hz": 50},
    }
