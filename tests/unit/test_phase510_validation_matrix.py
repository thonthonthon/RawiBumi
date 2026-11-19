from pathlib import Path

import pytest

from validation.shading.phase510 import (
    ExternalComparisonContext,
    Phase510ValidationError,
    build_external_oracle_evidence,
    compare_external_case,
    load_pvsyst_vc_oracle,
    phase510_validation_hierarchy_manifest,
)


ROOT = Path(__file__).resolve().parents[2]
ORACLE = (
    ROOT / "tests/benchmarks/phase49b_shaded_reference_matrix_20260924.yaml"
)


def _oracle():
    return load_pvsyst_vc_oracle(ORACLE)


def test_phase510_validation_hierarchy_preserves_analytical_priority():
    manifest = phase510_validation_hierarchy_manifest()
    assert manifest["hierarchy"] == {
        "A": "analytical_geometry_truth",
        "B": "controlled_synthetic_opensimpv",
        "C": "independent_open_implementation",
        "D": "external_cross_software",
        "E": "regression_only",
    }
    assert "PVsyst is not" in manifest["decision_rule"]
    assert "solar-position" in manifest["prohibited_shortcut"]


def test_phase510_frozen_vc0_vc5_oracle_reconciles_separate_shading_channels():
    evidence = build_external_oracle_evidence(_oracle())
    assert evidence["source_reconciliation_pass"] is True
    assert set(evidence["cases"]) == {"VC0", "VC1", "VC2", "VC3", "VC4", "VC5"}
    for case in evidence["cases"].values():
        assert abs(case["component_reconciliation_residual_kwh_m2"]) <= 1e-3


def test_phase510_external_directional_signatures_are_preserved_not_symmetrized():
    evidence = build_external_oracle_evidence(_oracle())
    directional = evidence["directional_signatures"]
    assert directional["VC2_east_morning_dominant"] is True
    assert directional["VC3_west_afternoon_dominant"] is True
    assert directional["VC2_morning_kwh_m2"] > directional["VC2_afternoon_kwh_m2"]
    assert directional["VC3_afternoon_kwh_m2"] > directional["VC3_morning_kwh_m2"]


def test_phase510_combined_external_cases_are_not_constructed_as_simple_sums():
    combined = build_external_oracle_evidence(_oracle())[
        "combined_case_nonadditivity"
    ]
    assert combined["VC4_is_not_simple_sum"] is True
    assert combined["VC5_is_not_simple_sum"] is True
    assert combined["VC4_east_west_reported_kwh_m2"] < combined[
        "VC2_plus_VC3_kwh_m2"
    ]
    assert combined["VC5_north_south_reported_kwh_m2"] < combined[
        "VC0_plus_VC1_kwh_m2"
    ]


def test_phase510_quantitative_external_comparison_fails_closed_when_basis_differs():
    oracle = _oracle()
    result = compare_external_case(
        case_id="VC2",
        opensimpv={"shading_loss_kwh_m2": 80.0},
        pvsyst_case=oracle["cases"]["VC2"],
        context={
            "weather": False,
            "scene_geometry": True,
            "simulation_timestep": True,
            "solar_time_semantics": True,
            "pre_shading_irradiance": False,
            "channel_semantics": True,
        },
    )
    assert result["status"] == "not_quantitatively_comparable"
    assert set(result["basis_mismatches"]) == {
        "weather",
        "pre_shading_irradiance",
    }
    assert result["residuals"] == {}


def test_phase510_matched_external_comparison_reports_decomposed_residuals_only():
    oracle = _oracle()
    source = oracle["cases"]["VC1"]["annual"]
    result = compare_external_case(
        case_id="VC1",
        opensimpv={
            "beam_shading_loss_kwh_m2": source["beam_shading_loss_kwh_m2"] + 1.0,
            "diffuse_shading_loss_kwh_m2": source["diffuse_shading_loss_kwh_m2"] - 2.0,
            "shading_loss_kwh_m2": source["shading_loss_kwh_m2"] + 0.5,
        },
        pvsyst_case=oracle["cases"]["VC1"],
        context=ExternalComparisonContext(
            weather=True,
            scene_geometry=True,
            simulation_timestep=True,
            solar_time_semantics=True,
            pre_shading_irradiance=True,
            channel_semantics=True,
        ),
    )
    assert result["status"] == "quantitative_residuals_reported_no_fit_or_winner"
    assert result["residuals"]["beam_shading_loss_kwh_m2"][
        "signed_residual"
    ] == pytest.approx(1.0)
    assert result["residuals"]["diffuse_shading_loss_kwh_m2"][
        "signed_residual"
    ] == pytest.approx(-2.0)


def test_phase510_matched_comparison_requires_at_least_one_aligned_metric():
    oracle = _oracle()
    with pytest.raises(Phase510ValidationError, match="no aligned numerical fields"):
        compare_external_case(
            case_id="VC0",
            opensimpv={"unrelated": 1.0},
            pvsyst_case=oracle["cases"]["VC0"],
            context={field: True for field in (
                "weather",
                "scene_geometry",
                "simulation_timestep",
                "solar_time_semantics",
                "pre_shading_irradiance",
                "channel_semantics",
            )},
        )
