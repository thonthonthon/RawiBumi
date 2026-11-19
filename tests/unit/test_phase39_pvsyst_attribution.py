import json
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft202012Validator

from components.candidates import build_module_candidate
from components.pan import parse_pan_text
from components.pan.mapper import map_pan
from validation.attribution import (
    assess_pvsyst_case_readiness,
    build_pvsyst_attribution_report,
    extract_opensimpv_attribution_metrics,
    load_pvsyst_attribution_campaign,
    pvsyst_reference_metrics,
    validate_pvsyst_reference_campaign,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas/pvsyst-attribution-report.schema.json"


def _campaign():
    return load_pvsyst_attribution_campaign()


def _module_definition():
    mapping = map_pan(
        parse_pan_text(
            (
                ROOT / "tests/fixtures/panond/synthetic_module.pan"
            ).read_text(encoding="utf-8")
        )
    )
    candidate = build_module_candidate(
        mapping,
        candidate_id="cand-phase39-module",
        module_definition_id="mod-phase39-module",
        revision_id="mod-phase39-module-r1",
        source_id="src-phase39-module",
    )
    assert candidate["definition_schema_ready"] is True
    return candidate["canonical_data"]


def test_verified_reference_campaign_is_internally_consistent():
    result = validate_pvsyst_reference_campaign(_campaign())

    assert result == {
        "status": "passed",
        "finding_count": 0,
        "findings": [],
    }


def test_reference_campaign_freezes_hourly_and_minute_loss_diagrams():
    campaign = _campaign()
    cases = campaign["cases"]

    assert cases["VC0"]["targets"]["loss_diagram"][
        "array_virtual_mpp_kwh"
    ] == 183905
    assert cases["VC1"]["targets"]["loss_diagram"][
        "array_virtual_mpp_kwh"
    ] == 184003
    assert cases["VC6"]["targets"]["loss_diagram"][
        "inverter_clipping_loss_pct"
    ] == -5.23
    assert cases["VC7"]["targets"]["loss_diagram"][
        "inverter_clipping_loss_pct"
    ] == -6.35

    # EArray is lower than EArrMPP once inverter operating-point displacement
    # becomes material. This is why Phase 3.9 excludes EArray from the present
    # OpenSIMPV acceptance mapping.
    displacement = {
        case_id: pvsyst_reference_metrics(case)[
            "dc_operating_displacement_kwh"
        ]
        for case_id, case in cases.items()
    }
    assert displacement["VC0"] == 2
    assert displacement["VC1"] == 41
    assert displacement["VC2"] == 284
    assert displacement["VC3"] == 775
    assert displacement["VC4"] == 4589
    assert displacement["VC5"] == 5981
    assert displacement["VC6"] == 14228
    assert displacement["VC7"] == 17305


def test_hourly_case_is_acceptance_ready_only_with_same_interval_weather():
    case = _campaign()["cases"]["VC0"]

    blocked = assess_pvsyst_case_readiness(
        case,
        same_interval_weather_series=False,
        verified_subhourly_perez_coefficients=False,
    )
    assert blocked.status == "blocked_external_input"
    assert blocked.acceptance_admissible is False
    assert [item["blocker_id"] for item in blocked.blockers] == [
        "PVSYST_METEONORM9_INTERVAL_WEATHER_NOT_ALIGNED"
    ]

    ready = assess_pvsyst_case_readiness(
        case,
        same_interval_weather_series=True,
        verified_subhourly_perez_coefficients=False,
    )
    assert ready.status == "acceptance_ready_annual_monthly_only"
    assert ready.acceptance_admissible is True


def test_minute_case_requires_both_same_weather_and_verified_perez_coefficients():
    case = _campaign()["cases"]["VC1"]

    multiple = assess_pvsyst_case_readiness(
        case,
        same_interval_weather_series=False,
        verified_subhourly_perez_coefficients=False,
    )
    assert multiple.status == "blocked_multiple_external_dependencies"
    assert multiple.acceptance_admissible is False
    assert {item["blocker_id"] for item in multiple.blockers} == {
        "PVSYST_METEONORM9_INTERVAL_WEATHER_NOT_ALIGNED",
        "PVSYST81_SUBHOURLY_PEREZ_COEFFICIENTS_UNVERIFIED",
    }

    perez_only = assess_pvsyst_case_readiness(
        case,
        same_interval_weather_series=True,
        verified_subhourly_perez_coefficients=False,
    )
    assert perez_only.status == "blocked_external_model_data"

    ready = assess_pvsyst_case_readiness(
        case,
        same_interval_weather_series=True,
        verified_subhourly_perez_coefficients=True,
    )
    assert ready.status == "acceptance_ready_annual_monthly_only"
    assert ready.acceptance_admissible is True


def test_exact_reference_observation_passes_frozen_acceptance_thresholds():
    campaign = _campaign()
    case = campaign["cases"]["VC0"]
    observed = pvsyst_reference_metrics(case)

    report = build_pvsyst_attribution_report(
        case,
        observed,
        campaign=campaign,
        same_interval_weather_series=True,
        verified_subhourly_perez_coefficients=False,
    )

    assert report["acceptance_status"] == "pass"
    assert report["readiness_status"] == "acceptance_ready_annual_monthly_only"
    assert report["first_nonpassing_stage"] is None
    assert report["monthly_grid_comparison"]["status"] == "pass"
    assert all(
        item["status"] == "pass"
        for item in report["metric_comparisons"]
    )

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)


def test_first_divergence_is_reported_without_inventing_a_cause():
    campaign = _campaign()
    case = campaign["cases"]["VC0"]
    observed = pvsyst_reference_metrics(case)
    observed["glob_hor_kwh_m2"] *= 1.01

    report = build_pvsyst_attribution_report(
        case,
        observed,
        campaign=campaign,
        same_interval_weather_series=True,
        verified_subhourly_perez_coefficients=False,
    )

    assert report["acceptance_status"] == "fail"
    assert report["first_nonpassing_stage"] == "weather"
    assert report["attribution_status"] == "unresolved_requires_evidence"
    weather = next(
        item
        for item in report["metric_comparisons"]
        if item["metric"] == "glob_hor_kwh_m2"
    )
    assert weather["status"] == "fail"

    # Known differences are possible candidates only. The report does not say
    # any one of them caused this synthetic weather mismatch.
    assert report["known_difference_candidates"]
    assert "cause" not in report


def test_different_weather_family_can_be_diagnostic_but_never_acceptance_evidence():
    campaign = _campaign()
    case = campaign["cases"]["VC0"]
    observed = pvsyst_reference_metrics(case)

    report = build_pvsyst_attribution_report(
        case,
        observed,
        campaign=campaign,
        same_interval_weather_series=False,
        verified_subhourly_perez_coefficients=False,
    )

    assert report["acceptance_status"] == "not_admissible"
    assert report["acceptance_admissible"] is False
    assert all(
        item["status"] == "not_admissible"
        for item in report["metric_comparisons"]
    )
    assert report["monthly_grid_comparison"]["status"] == "not_admissible"


def test_pvsyst_earray_is_explicitly_excluded_from_acceptance_mapping():
    campaign = _campaign()
    case = campaign["cases"]["VC6"]

    report = build_pvsyst_attribution_report(
        case,
        pvsyst_reference_metrics(case),
        campaign=campaign,
        same_interval_weather_series=True,
        verified_subhourly_perez_coefficients=False,
    )

    excluded = report["excluded_reference_metrics"]
    assert excluded["e_array_kwh"] == 261488
    assert excluded["dc_operating_displacement_kwh"] == 14228
    assert "operating-point displacement" in excluded["reason"]


def test_opensimpv_metric_extractor_builds_pvsyst_loss_diagram_analogue():
    module = _module_definition()
    index = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-01-15T12:00:00+07:00"),
            pd.Timestamp("2026-02-15T12:00:00+07:00"),
        ]
    )
    frame = pd.DataFrame(
        {
            "timestamp": index,
            "interval_seconds": [3600.0, 3600.0],
            "ghi_w_m2": [800.0, 600.0],
            "dhi_w_m2": [250.0, 200.0],
            "ambient_temperature_c": [30.0, 28.0],
            "poa_global_w_m2": [900.0, 700.0],
            "effective_irradiance_w_m2": [890.0, 690.0],
            "cell_temperature_c": [45.0, 40.0],
            "gross_dc_power_w": [10000.0, 8000.0],
            # Negative loss = gain under the OpenSIMPV signed-loss convention.
            "module_quality_loss_w": [-75.0, -60.0],
            "mismatch_loss_w": [200.0, 160.0],
            "dc_wiring_loss_w": [100.0, 80.0],
            "net_dc_power_w": [9775.0, 7820.0],
            "inverter_input_power_w": [9775.0, 7820.0],
            "conversion_loss_w": [150.0, 120.0],
            "clipping_loss_w": [25.0, 0.0],
            "pcc_power_w": [9600.0, 7700.0],
        }
    )
    simulation_run = {
        "status": "completed",
    }

    metrics = extract_opensimpv_attribution_metrics(
        simulation_run,
        frame,
        module,
        module_count=18,
    )

    assert metrics["glob_hor_kwh_m2"] == pytest.approx(1.4)
    assert metrics["diff_hor_kwh_m2"] == pytest.approx(0.45)
    assert metrics["glob_inc_kwh_m2"] == pytest.approx(1.6)
    assert metrics["glob_eff_kwh_m2"] == pytest.approx(1.58)
    assert metrics["ambient_temp_c"] == pytest.approx(29.0)
    assert metrics["array_virtual_mpp_kwh"] == pytest.approx(17.595)
    assert metrics["e_grid_kwh"] == pytest.approx(17.3)
    assert metrics["module_quality_effect_pct"] > 0.0
    assert metrics["mismatch_loss_pct"] < 0.0
    assert metrics["dc_wiring_loss_pct"] < 0.0
    assert metrics["inverter_conversion_loss_pct"] < 0.0
    assert metrics["inverter_clipping_loss_pct"] < 0.0
    assert metrics["pvsyst_e_array_kwh"] is None
    assert metrics["pvsyst_e_array_mapping_status"] == (
        "not_comparable_dc_operating_feedback_not_modelled"
    )
    assert metrics["monthly_keys"] == ["2026-01", "2026-02"]
    assert len(metrics["monthly_e_grid_kwh"]) == 2
