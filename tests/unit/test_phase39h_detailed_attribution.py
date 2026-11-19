import json
from pathlib import Path

import pandas as pd
import pytest
import yaml
from jsonschema import Draft202012Validator

from components.candidates import build_module_candidate
from components.pan import parse_pan_text
from components.pan.mapper import map_pan
from validation.attribution import (
    PVsystDetailedOutput,
    build_pvsyst_detailed_hourly_attribution_report,
    detailed_hourly_case_from_output,
    detailed_hourly_interval_statistics,
    detailed_hourly_grid_residual_decomposition,
    pvsyst_azimuth_to_canonical,
    pvsyst_detailed_hourly_reference_metrics,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas/pvsyst-detailed-hourly-attribution-report.schema.json"


def _module_definition():
    mapping = map_pan(
        parse_pan_text(
            (
                ROOT
                / "tests/fixtures/panond/manufacturer/"
                / "JKM550M-72HL4-V_SGS_6079M3.PAN"
            ).read_text(encoding="utf-8")
        )
    )
    candidate = build_module_candidate(
        mapping,
        candidate_id="cand-p39h-module",
        module_definition_id="mod-p39h-module",
        revision_id="mod-p39h-module-r1",
        source_id="src-p39h-module",
    )
    assert candidate["definition_schema_ready"] is True
    return candidate["canonical_data"]


def _output():
    dates = pd.date_range("1990-01-01 00:00", periods=3, freq="h")
    frame = pd.DataFrame(
        {
            "date": dates,
            "HSol": [45.0, 45.0, 45.0],
            "AzSol": [0.0, -90.0, 90.0],
            "AngInc": [20.0, 20.0, 20.0],
            "GlobHor": [800.0, 800.0, 800.0],
            "DiffHor": [200.0, 200.0, 200.0],
            "BeamHor": [600.0, 600.0, 600.0],
            "T_Amb": [30.0, 30.0, 30.0],
            "WindVel": [1.5, 1.5, 1.5],
            "GlobInc": [850.0, 850.0, 850.0],
            "GlobIAM": [845.0, 845.0, 845.0],
            "GlobEff": [845.0, 845.0, 845.0],
            "EArrRef": [100.0, 100.0, 100.0],
            "EArrNom": [99.5, 99.5, 99.5],
            "GIncLss": [0.1, 0.1, 0.1],
            "TempLss": [9.0, 9.0, 9.0],
            "ModQual": [-0.7, -0.7, -0.7],
            "MisLoss": [1.8, 1.8, 1.8],
            "OhmLoss": [0.9, 0.9, 0.9],
            "EArrMPP": [88.4, 88.4, 88.4],
            "EArray": [87.9, 87.9, 87.9],
            "TArray": [45.0, 45.0, 45.0],
            "InvLoss": [2.5, 2.5, 2.5],
            "IL_Oper": [1.9, 1.9, 1.9],
            "IL_Pmin": [0.0, 0.0, 0.0],
            "IL_Vmin": [0.0, 0.0, 0.0],
            "IL_Pmax": [0.3, 0.3, 0.3],
            "ILPmxSH": [0.2, 0.2, 0.2],
            "IL_Vmax": [0.0, 0.0, 0.0],
            "IL_Imax": [0.0, 0.0, 0.0],
            "IL_Nigh": [0.1, 0.1, 0.1],
            "EOutInv": [85.9, 85.9, 85.9],
            "E_Grid": [85.9, 85.9, 85.9],
        }
    )
    return PVsystDetailedOutput(
        frame=frame,
        units={column: "" for column in frame.columns},
        metadata={
            "variant_id": "VC0",
            "weather_filename": "Home_MN90_SYN_1MIN.MET",
            "simulation_date": "23/09/26 20h03",
            "interval_seconds": 3600,
            "row_count": 3,
        },
        source={
            "filename": "vc0.csv",
            "sha256": "a" * 64,
            "byte_size": 1234,
        },
    )


def _standard():
    timestamps = pd.date_range(
        "1990-01-01 00:00",
        periods=3,
        freq="h",
        tz="UTC+07:00",
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "interval_seconds": [3600.0] * 3,
            "ghi_w_m2": [800.0] * 3,
            "dhi_w_m2": [200.0] * 3,
            "ambient_temperature_c": [30.0] * 3,
            "solar_elevation_deg": [45.0, 45.0, 45.0],
            "solar_azimuth_deg": [0.0, 90.0, 270.0],
            "aoi_deg": [20.0] * 3,
            "poa_global_w_m2": [850.0] * 3,
            "effective_irradiance_w_m2": [845.0] * 3,
            "cell_temperature_c": [45.0] * 3,
            "gross_dc_power_w": [86400.0] * 3,
            "module_quality_loss_w": [-700.0] * 3,
            "mismatch_loss_w": [1800.0] * 3,
            "dc_wiring_loss_w": [900.0] * 3,
            "net_dc_power_w": [88400.0] * 3,
            "inverter_input_power_w": [88400.0] * 3,
            "conversion_loss_w": [1900.0] * 3,
            "clipping_loss_w": [300.0] * 3,
            "pcc_power_w": [85900.0] * 3,
        }
    )


def test_detailed_reference_uses_sequential_pvsyst_loss_boundaries():
    metrics = pvsyst_detailed_hourly_reference_metrics(
        _output(),
        installed_dc_kwp=118.8,
    )

    assert metrics["array_nominal_energy_kwh"] == pytest.approx(298.5)
    assert metrics["irradiance_level_loss_pct"] == pytest.approx(
        ((298.5 - 0.3) / 298.5 - 1.0) * 100.0
    )
    raw = 298.5 - 0.3 - 27.0
    after_quality = raw - (-2.1)
    assert metrics["module_quality_effect_pct"] == pytest.approx(
        (after_quality / raw - 1.0) * 100.0
    )
    assert metrics["array_virtual_mpp_kwh"] == pytest.approx(265.2)
    assert metrics["inverter_subhourly_clipping_correction_kwh"] == pytest.approx(
        0.6
    )
    assert metrics["grid_energy_plus_reported_subhourly_correction_kwh"] == pytest.approx(
        258.3
    )


def test_pvsyst_solar_azimuth_conversion_is_explicit_and_wrapped():
    converted = pvsyst_azimuth_to_canonical([0.0, -90.0, 90.0, 180.0])
    assert converted.tolist() == pytest.approx([0.0, 90.0, 270.0, 180.0])


def test_interval_statistics_reconcile_exact_stage_boundaries():
    stats = detailed_hourly_interval_statistics(_output(), _standard())

    for name in (
        "solar_elevation",
        "solar_azimuth",
        "incidence_angle",
        "poa_global",
        "effective_irradiance",
        "module_temperature",
        "array_virtual_mpp",
        "grid_power",
    ):
        assert stats["metrics"][name]["status"] == "compared"
        assert stats["metrics"][name]["mae"] == pytest.approx(0.0)
        assert stats["metrics"][name]["rmse"] == pytest.approx(0.0)


def test_interval_statistics_fail_closed_on_timestamp_shift():
    shifted = _standard()
    shifted["timestamp"] = shifted["timestamp"] + pd.Timedelta(hours=1)

    with pytest.raises(ValueError, match="align exactly"):
        detailed_hourly_interval_statistics(_output(), shifted)


def test_detailed_case_replaces_old_pdf_targets_instead_of_mixing_snapshots():
    from validation.attribution import load_pvsyst_attribution_campaign

    campaign = load_pvsyst_attribution_campaign()
    case = detailed_hourly_case_from_output(_output(), campaign["cases"]["VC0"])

    assert case["report_filename"] == "vc0.csv"
    assert case["targets"]["annual"]["e_grid_kwh"] == pytest.approx(257.7)
    assert case["targets"]["loss_diagram"]["array_virtual_mpp_kwh"] == pytest.approx(
        265.2
    )
    assert case["targets"]["annual"]["e_grid_kwh"] != (
        campaign["cases"]["VC0"]["targets"]["annual"]["e_grid_kwh"]
    )


def test_full_detailed_report_is_admissible_and_schema_valid():
    report = build_pvsyst_detailed_hourly_attribution_report(
        _output(),
        {"status": "completed"},
        _standard(),
        _module_definition(),
        module_count=216,
    )

    assert report["acceptance_report"]["acceptance_admissible"] is True
    assert report["acceptance_report"]["readiness_status"] == (
        "acceptance_ready_with_interval_attribution"
    )
    assert report["subhourly_clipping_boundary"]["pvsyst_ilpmxsh_kwh"] == pytest.approx(
        0.6
    )
    assert report["subhourly_clipping_boundary"]["opensimpv_model_status"] == (
        "not_implemented_named_difference"
    )

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)


def test_vc0_evidence_envelope_passes_the_frozen_thresholds_without_claiming_exact_spa():
    evidence = yaml.safe_load(
        (
            ROOT
            / "tests/benchmarks/phase39_vc0_attribution_evidence_20260923.yaml"
        ).read_text(encoding="utf-8")
    )
    result = evidence["acceptance_candidate_pvsyst_geometry"]
    proxy = evidence["independent_solar_geometry_proxy"]
    largest = evidence["largest_residuals_within_acceptance"]

    assert evidence["status"] == (
        "acceptance_candidate_pass_pending_exact_canonical_spa_execution"
    )
    assert result["frozen_threshold_result"] == "pass"
    assert result["first_nonpassing_stage"] is None
    assert proxy["frozen_threshold_result"] == "pass"
    assert proxy["first_nonpassing_stage"] is None

    assert abs(largest["array_nominal_energy_relative_error_pct"]) < 1.0
    assert abs(largest["irradiance_level_effect_delta_percentage_point"]) < 0.5
    assert abs(largest["temperature_effect_delta_percentage_point"]) < 0.5
    assert abs(largest["array_virtual_mpp_relative_error_pct"]) < 2.0
    assert abs(largest["e_grid_relative_error_pct"]) < 3.0
    assert result["monthly_grid"]["rms_relative_error_pct"] < 3.0
    assert result["monthly_grid"]["maximum_absolute_relative_error_pct"] < 5.0


def test_grid_residual_decomposition_reconciles_and_exposes_cancellation():
    result = detailed_hourly_grid_residual_decomposition(_output(), _standard())

    assert result["actual_grid_delta_kwh"] == pytest.approx(0.0)
    assert result["expected_grid_delta_from_components_kwh"] == pytest.approx(0.0)
    assert result["reconciliation_residual_kwh"] == pytest.approx(0.0)
    assert result["components"]["pvsyst_subhourly_clipping_correction"][
        "reference_kwh"
    ] == pytest.approx(0.6)
    assert result["components"]["pvsyst_subhourly_clipping_correction"][
        "grid_delta_contribution_kwh"
    ] == pytest.approx(0.6)
    assert result["components"]["other_earr_mpp_to_grid_losses"][
        "grid_delta_contribution_kwh"
    ] == pytest.approx(-0.6)
    assert result["cancellation_detected"] is True


def test_full_report_contains_grid_residual_decomposition():
    report = build_pvsyst_detailed_hourly_attribution_report(
        _output(),
        {"status": "completed"},
        _standard(),
        _module_definition(),
        module_count=216,
    )
    assert "grid_residual_decomposition" in report
    assert report["grid_residual_decomposition"]["cancellation_detected"] is True


def test_vc2_evidence_passes_frozen_gates_but_exposes_grid_cancellation():
    evidence = yaml.safe_load(
        (
            ROOT
            / "tests/benchmarks/phase39_vc2_attribution_evidence_20260923.yaml"
        ).read_text(encoding="utf-8")
    )

    assert evidence["status"] == (
        "acceptance_candidate_pass_with_grid_cancellation_pending_exact_canonical_spa_execution"
    )
    comparison = evidence["frozen_threshold_comparison"]
    assert comparison["frozen_threshold_result"] == "pass"
    assert comparison["first_nonpassing_stage"] is None

    residual = evidence["grid_residual_decomposition"]
    assert residual["cancellation_detected"] is True
    assert residual["cancellation_ratio"] < 0.25
    assert abs(residual["reconciliation_residual_kwh"]) < 1e-6
    assert residual["components"]["pvsyst_subhourly_clipping_correction"][
        "reference_kwh"
    ] == pytest.approx(536.7011)

    inverter = evidence["inverter_oracle_dc_isolation"]
    assert abs(inverter["conversion_loss_relative_error_pct"]) < 0.5
    assert abs(inverter["adjusted_grid_relative_error_pct"]) < 0.1


def test_vc4_evidence_passes_frozen_gates_and_identifies_ilpmxsh_as_dominant_gap():
    evidence = yaml.safe_load(
        (
            ROOT
            / "tests/benchmarks/phase39_vc4_attribution_evidence_20260923.yaml"
        ).read_text(encoding="utf-8")
    )

    assert evidence["status"] == (
        "acceptance_candidate_pass_with_ilpmxsh_dominant_grid_gap_pending_exact_canonical_spa_execution"
    )
    comparison = evidence["frozen_threshold_comparison"]
    assert comparison["frozen_threshold_result"] == "pass"
    assert comparison["first_nonpassing_stage"] is None

    residual = evidence["grid_residual_decomposition"]
    assert abs(
        residual["actual_grid_delta_kwh"]
        - residual["expected_grid_delta_from_components_kwh"]
    ) < 1e-6
    assert residual["ilpmxsh_fraction_of_gross_component_contribution"] > 0.60

    monthly = evidence["monthly_grid_sensitivity"]
    assert monthly["direct_rms_relative_error_pct"] < 3.0
    assert monthly["direct_max_absolute_relative_error_pct"] < 5.0
    assert abs(monthly["annual_adjusted_relative_error_pct"]) < 0.1

    earray = evidence["earray_dc_feedback"]
    assert abs(earray["residual_kwh"]) < 0.2

    inverter = evidence["inverter_oracle_dc_isolation"]
    assert abs(inverter["adjusted_grid_relative_error_pct"]) < 0.2


def test_vc6_evidence_passes_frozen_gates_at_strongest_hourly_loading():
    evidence = yaml.safe_load(
        (ROOT / "tests/benchmarks/phase39_vc6_attribution_evidence_20260923.yaml")
        .read_text(encoding="utf-8")
    )

    assert evidence["status"] == (
        "acceptance_candidate_pass_with_high_clipping_and_ilpmxsh_dominance_pending_exact_canonical_spa_execution"
    )
    comparison = evidence["frozen_threshold_comparison"]
    assert comparison["frozen_threshold_result"] == "pass"
    assert comparison["first_nonpassing_stage"] is None
    assert comparison["ordinary_clipping_delta_percentage_point"] < comparison["ordinary_clipping_gate_percentage_point"]
    assert comparison["ordinary_clipping_gate_margin_percentage_point"] > 0

    residual = evidence["grid_residual_decomposition"]
    assert abs(residual["actual_grid_delta_kwh"] - residual["expected_grid_delta_from_components_kwh"]) < 1e-6
    assert residual["ilpmxsh_fraction_of_gross_component_contribution"] > 0.65

    monthly = evidence["monthly_grid_sensitivity"]
    assert monthly["direct_rms_relative_error_pct"] < 3.0
    assert monthly["direct_max_absolute_relative_error_pct"] < 5.0
    assert abs(monthly["annual_adjusted_relative_error_pct"]) < 0.2

    electrical = evidence["electrical_isolation_with_pvsyst_optical_thermal_inputs"]
    assert abs(electrical["array_virtual_mpp_relative_error_pct"]) < 0.1

    earray = evidence["earray_dc_feedback"]
    assert abs(earray["residual_kwh"]) < 0.1

    ladder = evidence["hourly_loading_ladder"]
    assert ladder["cases"] == ["VC0", "VC2", "VC4", "VC6"]
    assert ladder["frozen_gate_result"] == "pass_all_cases"
    assert ladder["first_nonpassing_stage"] is None
