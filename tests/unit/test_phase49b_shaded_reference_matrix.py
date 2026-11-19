from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests/benchmarks/phase49b_shaded_reference_matrix_20260924.yaml"


def _manifest():
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_phase49b_manifest_freezes_six_csv_shd_pairs():
    manifest = _manifest()

    assert manifest["oracle_id"] == "P49B-SHADED-PVSYST816-20260924"
    assert manifest["software"]["version"] == "8.1.6"
    assert manifest["software"]["simulation_step_seconds"] == 3600
    assert set(manifest["cases"]) == {f"VC{i}" for i in range(6)}

    for case_id, case in manifest["cases"].items():
        assert case["rows"] == 8760
        assert case["columns"] == 107
        assert case["csv"]["file"].endswith(f"_Var3_{case_id}_HourlyRes_0.CSV")
        assert case["shd"]["file"].endswith(f"Var3{case_id}.SHD")
        assert re.fullmatch(r"[0-9a-f]{64}", case["csv"]["sha256"])
        assert re.fullmatch(r"[0-9a-f]{64}", case["shd"]["sha256"])


def test_phase49b_common_pv_geometry_is_frozen_from_shd():
    baseline = _manifest()["baseline"]

    assert baseline == {
        "module_model": "JKM550M-72HL4-V",
        "module_width_m": 1.134,
        "module_height_m": 2.278,
        "module_count": 216,
        "dc_kwp": 118.8,
        "inverter_count": 1,
        "module_orientation": "portrait",
        "field_tilt_deg": 20.0,
        "field_azimuth_deg": 0.0,
        "table_count": 12,
        "modules_per_table": 18,
        "table_spacing_x_m": 0.02,
        "table_spacing_y_m": 0.02,
        "table_long_shed_m": 20.752,
        "table_width_shed_m": 2.278,
    }


def test_phase49b_exact_case_geometry_does_not_assume_directional_symmetry():
    cases = _manifest()["cases"]

    expected = {
        "VC0": (
            [-21.0, -18.0, -15.0, -12.0, -9.0, -6.0],
            [[-8.256538, -5.0, 0.0, 40.0, 10.0, 5.0]],
        ),
        "VC1": (
            [8.0, 11.0, 14.0, 17.0, 20.0, 23.0],
            [[-8.256538, -5.0, 0.0, 40.0, 10.0, 5.0]],
        ),
        "VC2": (
            [-21.0, -18.0, -15.0, -12.0, -9.0, -6.0],
            [[35.794541, -24.427654, 0.0, 10.0, 20.0, 5.0]],
        ),
        "VC3": (
            [-21.0, -18.0, -15.0, -12.0, -9.0, -6.0],
            [[-21.702076, -24.427654, 0.0, 10.0, 20.0, 5.0]],
        ),
        "VC4": (
            [-21.0, -18.0, -15.0, -12.0, -9.0, -6.0],
            [
                [-21.702076, -24.427654, 0.0, 10.0, 20.0, 5.0],
                [35.024096, -24.141728, 0.0, 10.0, 20.0, 5.0],
            ],
        ),
        "VC5": (
            [8.0, 11.0, 14.0, 17.0, 20.0, 23.0],
            [
                [-8.256538, -5.0, 0.0, 40.0, 10.0, 5.0],
                [-8.24263, 24.358715, 0.0, 40.0, 10.0, 5.0],
            ],
        ),
    }

    for case_id, (expected_y, expected_obstacles) in expected.items():
        geometry = cases[case_id]["geometry"]
        assert geometry["table_origin_x_m"] == [0.0, 23.0]
        assert geometry["table_origin_y_m"] == expected_y
        actual_obstacles = [
            obstacle["origin_m"] + obstacle["size_xyz_m"]
            for obstacle in geometry["obstacles"]
        ]
        assert actual_obstacles == expected_obstacles

    invariants = _manifest()["invariants"]
    assert invariants["north_south_not_assumed_symmetric"] is True
    assert invariants["east_west_not_assumed_symmetric"] is True


def test_phase49b_pre_shading_inputs_are_controlled_and_channel_order_is_not():
    manifest = _manifest()
    cases = manifest["cases"]
    common_glob_inc = manifest["invariants"]["common_glob_inc_kwh_m2"]

    assert manifest["invariants"]["critical_pre_shading_series_identical_all_cases"] is True
    assert manifest["invariants"]["channel_sets_identical"] is True
    assert manifest["invariants"]["column_order_identical"] is False
    assert all(
        case["channel_set_sha256"] == manifest["invariants"]["channel_set_sha256"]
        for case in cases.values()
    )
    assert len({cases[f"VC{i}"]["header_order_sha256"] for i in range(1, 6)}) == 1
    assert cases["VC0"]["header_order_sha256"] != cases["VC1"]["header_order_sha256"]
    assert all(
        case["annual"]["glob_inc_kwh_m2"] == pytest.approx(common_glob_inc, abs=1e-7)
        for case in cases.values()
    )


def test_phase49b_directional_hourly_signature_is_preserved_without_symmetry_claim():
    cases = _manifest()["cases"]

    east = cases["VC2"]["directional_signature"]
    west = cases["VC3"]["directional_signature"]

    assert east["beam_plus_circ_morning_kwh_m2"] > 5.0 * east["beam_plus_circ_afternoon_kwh_m2"]
    assert west["beam_plus_circ_afternoon_kwh_m2"] > 5.0 * west["beam_plus_circ_morning_kwh_m2"]

    # Direction is evident, but magnitudes are not forced to be mirror images.
    assert east["beam_plus_circ_morning_kwh_m2"] != pytest.approx(
        west["beam_plus_circ_afternoon_kwh_m2"], rel=0.01
    )


def test_phase49b_combined_obstacle_cases_are_not_treated_as_additive():
    cases = _manifest()["cases"]
    shade = {
        case_id: case["annual"]["shading_loss_kwh_m2"]
        for case_id, case in cases.items()
    }

    assert shade["VC4"] < shade["VC2"] + shade["VC3"]
    assert shade["VC5"] < shade["VC0"] + shade["VC1"]
    assert _manifest()["invariants"]["combined_cases_not_assumed_additive"] is True


def test_phase49b_annual_shading_components_reconcile_to_total():
    cases = _manifest()["cases"]

    for case in cases.values():
        annual = case["annual"]
        component_sum = (
            annual["beam_shading_loss_kwh_m2"]
            + annual["circumsolar_shading_loss_kwh_m2"]
            + annual["diffuse_shading_loss_kwh_m2"]
            + annual["albedo_shading_loss_kwh_m2"]
        )
        assert component_sum == pytest.approx(
            annual["shading_loss_kwh_m2"], abs=0.001
        )
        assert sum(case["monthly_shading_loss_kwh_m2"]) == pytest.approx(
            annual["shading_loss_kwh_m2"], abs=0.001
        )
        assert sum(case["monthly_e_grid_kwh"]) == pytest.approx(
            annual["e_grid_kwh"], abs=0.001
        )


def test_phase49b_source_balance_keeps_il_pmin_at_inverter_boundary():
    manifest = _manifest()
    cases = manifest["cases"]

    assert manifest["invariants"]["dc_operating_displacement_excludes_il_pmin"] is True
    assert "included in InvLoss" in manifest["invariants"]["il_pmin_semantics"]
    assert max(
        case["source_balance_max_abs_kw"][
            "dc_operating_displacement_excluding_il_pmin"
        ]
        for case in cases.values()
    ) <= 0.001
    assert max(
        max(case["source_balance_max_abs_kw"].values())
        for case in cases.values()
    ) <= manifest["invariants"]["external_source_balance_tolerance_kw"]


def test_phase49b_geometry_oracle_does_not_claim_phase5_solver_completion():
    provenance = _manifest()["provenance"]

    assert provenance["geometry_authority"] == "user-supplied PVsyst SHD"
    assert provenance["derived_geometry_is_frozen_not_reverse_engineered_from_hourly_output"] is True
    assert provenance["geometric_shading_oracle_does_not_implement_opensimpv_phase5_solver"] is True
