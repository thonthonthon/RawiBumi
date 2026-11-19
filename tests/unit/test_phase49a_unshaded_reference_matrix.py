from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests/benchmarks/phase49a_unshaded_reference_matrix_20260924.yaml"


def _manifest():
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_phase49a_manifest_freezes_nine_external_hourly_oracles():
    manifest = _manifest()

    assert manifest["oracle_id"] == "P49A-UNSHADED-PVSYST816-20260924"
    assert manifest["software"]["version"] == "8.1.6"
    assert manifest["software"]["simulation_step_seconds"] == 3600
    assert set(manifest["cases"]) == {f"VC{i}" for i in range(9)}

    for case_id, case in manifest["cases"].items():
        assert case["rows"] == 8760
        assert re.fullmatch(r"[0-9a-f]{64}", case["sha256"])
        assert case["file"].endswith(f"_{case_id}_HourlyRes_0.CSV")
        assert case["configuration"]["reconstruction"] == (
            "partial_pending_orientation_topology_metadata"
        )


def test_phase49a_manifest_does_not_invent_missing_orientation_topology():
    manifest = _manifest()

    assert manifest["provenance"]["orientation_angles"] == (
        "not recoverable from aggregate CSV"
    )
    assert manifest["provenance"][
        "orientation_string_mppt_allocation"
    ] == "not recoverable from aggregate CSV"

    assert all(
        "azimuth_deg" not in case["configuration"]
        and "tilt_deg" not in case["configuration"]
        and "mppt_string_counts" not in case["configuration"]
        for case in manifest["cases"].values()
    )


def test_phase49a_size_ladders_are_consistent_with_phase3_component_baseline():
    manifest = _manifest()
    cases = manifest["cases"]

    expected = {
        "VC0": (216, 12, 1, 118.8, 1.188),
        "VC1": (252, 14, 1, 138.6, 1.386),
        "VC2": (288, 16, 1, 158.4, 1.584),
        "VC3": (324, 18, 1, 178.2, 1.782),
        "VC4": (216, 12, 1, 118.8, 1.188),
        "VC5": (252, 14, 1, 138.6, 1.386),
        "VC6": (288, 16, 1, 158.4, 1.584),
        "VC7": (324, 18, 1, 178.2, 1.782),
        "VC8": (864, 48, 4, 475.2, 1.188),
    }
    for case_id, values in expected.items():
        modules, strings, inverters, dc_kwp, dc_ac = values
        config = cases[case_id]["configuration"]
        assert config["modules"] == modules
        assert config["strings_at_18_modules"] == strings
        assert config["inverters"] == inverters
        assert config["dc_kwp"] == pytest.approx(dc_kwp)
        assert config["dc_ac"] == pytest.approx(dc_ac)


def test_phase49a_vc8_is_clean_array_scaling_vs_vc4_before_inverter_boundary():
    manifest = _manifest()
    vc4 = manifest["cases"]["VC4"]["annual"]
    vc8 = manifest["cases"]["VC8"]["annual"]

    for key in (
        "glob_inc_kwh_m2",
        "glob_eff_kwh_m2",
    ):
        assert vc8[key] == pytest.approx(vc4[key], abs=1e-7)

    assert vc8["e_arr_nom_kwh"] == pytest.approx(
        4.0 * vc4["e_arr_nom_kwh"], abs=0.5
    )
    assert vc8["e_arr_mpp_kwh"] == pytest.approx(
        4.0 * vc4["e_arr_mpp_kwh"], abs=0.001
    )

    # The controlled relation deliberately breaks at the inverter operating
    # point/clipping stage: four inverters nearly remove the one-inverter
    # clipping signature.
    assert vc8["il_pmax_kwh"] < 0.01 * (4.0 * vc4["il_pmax_kwh"])
    assert vc8["e_grid_kwh"] > 4.0 * vc4["e_grid_kwh"]


def test_phase49a_source_channels_capture_mixloss_family_difference():
    cases = _manifest()["cases"]

    for case_id in ("VC0", "VC1", "VC2", "VC3"):
        assert cases[case_id]["channels"]["MixLoss"] is True
        assert cases[case_id]["annual"]["mix_loss_kwh"] > 0.0

    for case_id in ("VC4", "VC5", "VC6", "VC7", "VC8"):
        assert cases[case_id]["channels"]["MixLoss"] is False
        assert cases[case_id]["annual"]["mix_loss_kwh"] is None


def test_phase49a_monthly_targets_reconcile_to_annual_source_totals():
    cases = _manifest()["cases"]
    for case in cases.values():
        assert sum(case["monthly_e_grid_kwh"]) == pytest.approx(
            case["annual"]["e_grid_kwh"], abs=0.001
        )
        assert sum(case["monthly_e_arr_mpp_kwh"]) == pytest.approx(
            case["annual"]["e_arr_mpp_kwh"], abs=0.001
        )


def test_phase49a_vc8_ground_role_does_not_claim_scene_physics_evidence():
    scope = _manifest()["invariants"]["vc8_ground_use"]

    assert scope["opensimpv_role"] == (
        "exercise ground support-surface semantics plus multi-inverter topology"
    )
    assert "no 3D scene-dependent ground-vs-roof physics claim" in (
        scope["pvsyst_oracle_scope"]
    )


def test_phase49a_multi_orientation_ladder_is_not_mislabeled_as_pure_loading():
    manifest = _manifest()
    cases = manifest["cases"]
    glob_inc = [cases[f"VC{i}"]["annual"]["glob_inc_kwh_m2"] for i in range(4, 8)]

    assert max(glob_inc) - min(glob_inc) == pytest.approx(
        manifest["invariants"]["vc4_vc7_poa_range_kwh_m2"],
        abs=1e-7,
    )
    assert manifest["invariants"]["vc4_vc7_same_aggregate_poa"] is False
    assert "do not attribute all inter-case energy change to DC/AC ratio" in (
        manifest["invariants"]["vc4_vc7_interpretation"]
    )
