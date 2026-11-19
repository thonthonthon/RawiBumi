from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from components.candidates import build_inverter_candidate
from components.ond import parse_ond_text
from components.ond.mapper import map_ond
from electrical.mppt import MPPTAggregationResult
from engine.losses import (
    aggregate_interval_quantities,
    apply_pre_inverter_array_losses,
    calculate_pv_kpis,
    simulate_electrical_loss_chain,
)


ROOT = Path(__file__).resolve().parents[2]


def _index(periods=1, freq="1h"):
    return pd.date_range(
        "2026-01-31T23:00:00+07:00",
        periods=periods,
        freq=freq,
    )


def _mppt(
    *,
    mppt_index=1,
    pmp=10000.0,
    vmp=500.0,
    voc=800.0,
    active=True,
    periods=1,
    freq="1h",
):
    index = _index(periods=periods, freq=freq)
    p = np.broadcast_to(np.asarray(pmp, dtype=float), periods)
    v = np.broadcast_to(np.asarray(vmp, dtype=float), periods)
    is_active = np.broadcast_to(np.asarray(active, dtype=bool), periods)
    imp = np.divide(p, v, out=np.zeros_like(p), where=v > 0)
    imp[~is_active] = 0.0
    p = np.where(is_active, p, 0.0)
    v = np.where(is_active, v, 0.0)
    voc_values = np.where(
        is_active,
        np.broadcast_to(np.asarray(voc, dtype=float), periods),
        0.0,
    )

    frame = pd.DataFrame(
        {
            "evaluation_time": index + pd.Timedelta(minutes=30),
            "mppt_isc_a": imp * 1.05,
            "mppt_voc_v": voc_values,
            "mppt_imp_a": imp,
            "mppt_vmp_v": v,
            "mppt_pmp_w": p,
            "string_count": 1,
            "active": is_active,
            "pmp_identity_relative_error": 0.0,
            "voltage_below_min": False,
            "voltage_above_max": False,
            "voltage_within_window": is_active,
            "operating_current_limit_known": False,
            "operating_current_above_limit": pd.array(
                [pd.NA] * periods,
                dtype="boolean",
            ),
        },
        index=index,
    )
    return MPPTAggregationResult(
        mppt_index=mppt_index,
        string_ids=(f"S{mppt_index:02d}",),
        frame=frame,
        metadata={
            "model_id": "mppt.synthetic",
            "min_operating_voltage_v": 200.0,
            "max_operating_voltage_v": 1000.0,
        },
    )


def _huawei_inverter():
    text = (
        ROOT
        / "tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND"
    ).read_text(encoding="utf-8")
    mapping = map_ond(parse_ond_text(text))
    candidate = build_inverter_candidate(
        mapping,
        candidate_id="cand-phase37-huawei",
        inverter_definition_id="inv-huawei-sun2000-100ktl-m1",
        revision_id="inv-huawei-sun2000-100ktl-m1-r1",
        source_id="src-manufacturer-huawei-sun2000-100ktl-m1",
    )
    return candidate["canonical_data"]


def test_array_losses_apply_signed_quality_mismatch_and_i2r_once():
    bank = {
        1: _mppt(mppt_index=1, pmp=10000.0, vmp=500.0),
        2: _mppt(mppt_index=2, pmp=10000.0, vmp=500.0),
    }

    result = apply_pre_inverter_array_losses(
        bank,
        module_quality_loss_fraction=-0.01,
        module_mismatch_loss_fraction=0.02,
        string_mismatch_loss_fraction=0.005,
        dc_array_resistance_ohm=0.1,
    )
    row = result.frame.iloc[0]

    raw = 20000.0
    quality_loss = raw * -0.01
    after_quality = raw - quality_loss
    module_mismatch = after_quality * 0.02
    after_module = after_quality - module_mismatch
    string_mismatch = after_module * 0.005
    before_wiring = after_module - string_mismatch
    current = before_wiring / 500.0
    wiring = current**2 * 0.1
    expected = before_wiring - wiring

    assert row["raw_array_mpp_w"] == pytest.approx(raw)
    assert row["module_quality_loss_w"] == pytest.approx(quality_loss)
    assert row["after_module_quality_w"] == pytest.approx(after_quality)
    assert row["module_mismatch_loss_w"] == pytest.approx(module_mismatch)
    assert row["string_mismatch_loss_w"] == pytest.approx(string_mismatch)
    assert row["dc_array_current_a"] == pytest.approx(current)
    assert row["dc_wiring_voltage_drop_v"] == pytest.approx(current * 0.1)
    assert row["dc_wiring_loss_w"] == pytest.approx(wiring)
    assert row["array_virtual_mpp_w"] == pytest.approx(expected)

    adjusted_total = sum(
        item.frame.iloc[0]["mppt_pmp_w"]
        for item in result.mppt_bank.values()
    )
    assert adjusted_total == pytest.approx(expected)
    assert result.metadata["module_quality_sign_convention"] == (
        "positive_loss_negative_gain"
    )


def test_global_array_resistance_refuses_heterogeneous_tracker_voltage():
    bank = {
        1: _mppt(mppt_index=1, pmp=10000.0, vmp=500.0),
        2: _mppt(mppt_index=2, pmp=10000.0, vmp=600.0),
    }

    with pytest.raises(ValueError, match="common active MPPT voltage"):
        apply_pre_inverter_array_losses(
            bank,
            dc_array_resistance_ohm=0.05,
        )


def test_interval_energy_uses_explicit_duration_not_timestamp_inference():
    index = _index(periods=2, freq="1h")
    frame = pd.DataFrame(
        {
            "power_w": [1000.0, 2000.0],
            "poa_w_m2": [500.0, 1000.0],
        },
        index=index,
    )

    result = aggregate_interval_quantities(
        frame,
        interval_seconds=[60.0, 120.0],
        power_columns_w=["power_w"],
        irradiance_columns_w_m2=["poa_w_m2"],
    )

    assert result.interval.iloc[0]["power_wh"] == pytest.approx(
        1000.0 * 60.0 / 3600.0
    )
    assert result.interval.iloc[1]["power_wh"] == pytest.approx(
        2000.0 * 120.0 / 3600.0
    )
    assert result.annual["power_kwh"] == pytest.approx(
        (1000.0 * 60.0 + 2000.0 * 120.0) / 3_600_000.0
    )
    assert result.metadata["duration_source_policy"] == (
        "caller_supplied_canonical_interval_seconds"
    )


def test_monthly_aggregation_respects_local_interval_start_month():
    index = _index(periods=2, freq="1h")
    frame = pd.DataFrame({"power_w": [1000.0, 2000.0]}, index=index)

    result = aggregate_interval_quantities(
        frame,
        interval_seconds=3600.0,
        power_columns_w=["power_w"],
    )

    assert list(result.monthly.index) == ["2026-01", "2026-02"]
    assert result.monthly.loc["2026-01", "power_kwh"] == pytest.approx(1.0)
    assert result.monthly.loc["2026-02", "power_kwh"] == pytest.approx(2.0)


def test_kpis_specific_yield_reference_yield_and_pr():
    result = calculate_pv_kpis(
        grid_energy_kwh=181376.0,
        installed_dc_kwp=118.8,
        incident_poa_kwh_m2=1754.9,
    )

    assert result["specific_yield_kwh_per_kwp"] == pytest.approx(
        181376.0 / 118.8
    )
    assert result["reference_yield_h"] == pytest.approx(1754.9)
    assert result["performance_ratio"] == pytest.approx(
        (181376.0 / 118.8) / 1754.9
    )


def test_integrated_loss_chain_reconciles_every_interval_and_annual_energy():
    inverter = _huawei_inverter()
    bank = {
        1: _mppt(mppt_index=1, pmp=30000.0, vmp=650.0),
        2: _mppt(mppt_index=2, pmp=30000.0, vmp=650.0),
    }

    result = simulate_electrical_loss_chain(
        bank,
        inverter,
        interval_seconds=3600.0,
        module_quality_loss_fraction=-0.0075,
        module_mismatch_loss_fraction=0.02,
        string_mismatch_loss_fraction=0.0005,
        dc_array_resistance_ohm=0.05,
    )

    ledger = result.ledger
    assert ledger.metadata["max_interval_reconciliation_residual_w"] <= 1e-6
    assert abs(ledger.metadata["annual_reconciliation_residual_kwh"]) <= 1e-9
    assert ledger.metadata["pcc_boundary"] == (
        "net_inverter_ac_output_no_downstream_ac_stage"
    )

    signed_losses = ledger.summary["loss_energy_kwh"].sum()
    expected_pcc = (
        ledger.energy.annual["raw_array_mpp_kwh"] - signed_losses
    )
    assert ledger.energy.annual["pcc_power_kwh"] == pytest.approx(expected_pcc)

    quality = ledger.summary.loc[
        ledger.summary["channel"] == "module_quality",
        "classification",
    ].iloc[0]
    assert quality == "gain"


def test_inverter_receives_post_array_loss_mppt_state():
    inverter = _huawei_inverter()
    bank = {1: _mppt(pmp=60000.0, vmp=650.0)}

    baseline = simulate_electrical_loss_chain(
        bank,
        inverter,
        interval_seconds=3600.0,
    )
    lossy = simulate_electrical_loss_chain(
        bank,
        inverter,
        interval_seconds=3600.0,
        module_mismatch_loss_fraction=0.02,
        dc_array_resistance_ohm=0.05,
    )

    assert (
        lossy.inverter.frame.iloc[0]["dc_mpp_available_w"]
        < baseline.inverter.frame.iloc[0]["dc_mpp_available_w"]
    )
    assert lossy.inverter.frame.iloc[0]["dc_mpp_available_w"] == pytest.approx(
        lossy.array_losses.frame.iloc[0]["array_virtual_mpp_w"]
    )


def test_phase3_resistance_values_are_consistent_with_reported_1p5pct_stc_reference():
    suite = yaml.safe_load(
        (ROOT / "tests/benchmarks/phase3_unshaded.yaml").read_text(
            encoding="utf-8"
        )
    )
    family = next(
        item
        for item in suite["families"]
        if item["family_id"] == "SYS-PVSYST-V816-UNSHADED"
    )
    imp_stc_a = 13.45
    module_pnom_w = 550.0
    modules_per_string = family["shared_configuration"]["modules_per_string"]

    for case in family["cases"]:
        strings = case["configuration"]["strings"]
        resistance_ohm = (
            case["configuration"]["dc_array_resistance_mohm"] / 1000.0
        )
        array_current_a = imp_stc_a * strings
        loss_w = array_current_a**2 * resistance_ohm
        nominal_w = module_pnom_w * modules_per_string * strings
        fraction = loss_w / nominal_w
        # The report percentage is rounded to 1.50% while the case resistance is
        # stored as an integer number of milliohms. Allow the rounding envelope.
        assert fraction == pytest.approx(0.015, abs=0.00025)


def test_phase3_array_loss_contract_preserves_quality_mismatch_and_wiring_semantics():
    suite = yaml.safe_load(
        (ROOT / "tests/benchmarks/phase3_unshaded.yaml").read_text(
            encoding="utf-8"
        )
    )
    family = next(
        item
        for item in suite["families"]
        if item["family_id"] == "SYS-PVSYST-V816-UNSHADED"
    )
    shared = family["shared_configuration"]

    assert shared["module_quality_loss_fraction"] == -0.0075
    assert shared["module_mismatch_loss_fraction"] == 0.02
    assert shared["dc_wiring_loss_fraction_at_stc"] == 0.015
