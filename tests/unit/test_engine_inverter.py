from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from components.candidates import build_inverter_candidate
from components.ond import parse_ond_text
from components.ond.mapper import map_ond
from electrical.mppt import MPPTAggregationResult
from engine.inverter import (
    INVERTER_VOLTAGE_DEPENDENT,
    evaluate_voltage_dependent_conversion,
    simulate_voltage_dependent_inverter,
)


ROOT = Path(__file__).resolve().parents[2]


def _huawei_inverter():
    text = (
        ROOT
        / "tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND"
    ).read_text(encoding="utf-8")
    mapping = map_ond(parse_ond_text(text))
    candidate = build_inverter_candidate(
        mapping,
        candidate_id="cand-inverter-runtime-huawei",
        inverter_definition_id="inv-huawei-sun2000-100ktl-m1",
        revision_id="inv-huawei-sun2000-100ktl-m1-r1",
        source_id="src-manufacturer-huawei-sun2000-100ktl-m1",
    )
    return candidate["canonical_data"]


def _index(periods=1):
    return pd.date_range(
        "2026-03-21T10:00:00+07:00",
        periods=periods,
        freq="1h",
    )


def _mppt(
    *,
    mppt_index=1,
    pmp=60000.0,
    vmp=650.0,
    imp=None,
    voc=800.0,
    isc=None,
    active=True,
    periods=1,
):
    index = _index(periods)
    pmp_values = np.broadcast_to(np.asarray(pmp, dtype=float), periods)
    vmp_values = np.broadcast_to(np.asarray(vmp, dtype=float), periods)
    if imp is None:
        imp_values = np.divide(
            pmp_values,
            vmp_values,
            out=np.zeros_like(pmp_values),
            where=vmp_values != 0,
        )
    else:
        imp_values = np.broadcast_to(np.asarray(imp, dtype=float), periods)
    voc_values = np.broadcast_to(np.asarray(voc, dtype=float), periods)
    if isc is None:
        isc_values = imp_values * 1.05
    else:
        isc_values = np.broadcast_to(np.asarray(isc, dtype=float), periods)
    active_values = np.broadcast_to(np.asarray(active, dtype=bool), periods)

    frame = pd.DataFrame(
        {
            "evaluation_time": index + pd.Timedelta(minutes=30),
            "mppt_isc_a": isc_values,
            "mppt_voc_v": voc_values,
            "mppt_imp_a": imp_values,
            "mppt_vmp_v": vmp_values,
            "mppt_pmp_w": pmp_values,
            "string_count": 1,
            "active": active_values,
            "pmp_identity_relative_error": 0.0,
            "voltage_below_min": False,
            "voltage_above_max": False,
            "voltage_within_window": active_values,
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
        metadata={"model_id": "mppt.synthetic"},
    )


def test_huawei_voltage_curve_exact_60kw_650v_anchor():
    inverter = _huawei_inverter()
    model = inverter["efficiency_model"]

    ac, eta = evaluate_voltage_dependent_conversion(
        model,
        dc_power_w=60000.0,
        tracker_voltages_v=np.array([650.0]),
        tracker_powers_w=np.array([60000.0]),
    )

    assert ac == pytest.approx(59280.0, abs=1e-9)
    assert eta == pytest.approx(0.988, abs=1e-12)


def test_huawei_runtime_separates_conversion_loss_from_clipping():
    inverter = _huawei_inverter()

    result = simulate_voltage_dependent_inverter(
        {1: _mppt(pmp=120000.0, vmp=650.0, voc=800.0)},
        inverter,
    )
    row = result.frame.iloc[0]

    endpoint_efficiency = 98660.4 / 100000.0
    expected_unclipped = 120000.0 * endpoint_efficiency

    assert row["dc_to_converter_w"] == pytest.approx(120000.0)
    assert row["inverter_efficiency_fraction"] == pytest.approx(
        endpoint_efficiency, abs=1e-12
    )
    assert row["ac_unclipped_w"] == pytest.approx(expected_unclipped, abs=1e-8)
    assert row["inverter_conversion_loss_w"] == pytest.approx(
        120000.0 - expected_unclipped,
        abs=1e-8,
    )
    assert row["ac_power_limit_w"] == pytest.approx(110000.0)
    assert row["inverter_clipping_loss_w"] == pytest.approx(
        expected_unclipped - 110000.0,
        abs=1e-8,
    )
    assert row["ac_available_w"] == pytest.approx(110000.0)
    assert bool(row["clipped"]) is True
    assert result.metadata["model_id"] == INVERTER_VOLTAGE_DEPENDENT
    assert result.metadata["nominal_ac_power_w"] == pytest.approx(100000.0)
    assert result.metadata["base_max_ac_power_w"] == pytest.approx(110000.0)


def test_two_mppts_do_not_apply_inverter_fixed_losses_twice():
    inverter = _huawei_inverter()

    result = simulate_voltage_dependent_inverter(
        {
            1: _mppt(mppt_index=1, pmp=30000.0, vmp=650.0),
            2: _mppt(mppt_index=2, pmp=30000.0, vmp=650.0),
        },
        inverter,
    )
    row = result.frame.iloc[0]

    assert row["dc_mpp_available_w"] == pytest.approx(60000.0)
    assert row["ac_unclipped_w"] == pytest.approx(59280.0, abs=1e-9)
    assert row["inverter_efficiency_fraction"] == pytest.approx(0.988)


def test_startup_threshold_is_separate_dc_loss_channel():
    inverter = _huawei_inverter()

    result = simulate_voltage_dependent_inverter(
        {1: _mppt(pmp=400.0, vmp=650.0, voc=800.0)},
        inverter,
    )
    row = result.frame.iloc[0]

    assert result.metadata["startup_threshold_w"] == pytest.approx(500.0)
    assert row["dc_mpp_available_w"] == pytest.approx(400.0)
    assert row["dc_power_threshold_loss_w"] == pytest.approx(400.0)
    assert row["dc_to_converter_w"] == 0.0
    assert row["inverter_conversion_loss_w"] == 0.0
    assert row["inverter_clipping_loss_w"] == 0.0
    assert row["ac_available_w"] == 0.0
    assert bool(row["converter_active"]) is False


def test_mppt_voltage_window_loss_is_separate_from_conversion():
    inverter = _huawei_inverter()

    result = simulate_voltage_dependent_inverter(
        {1: _mppt(pmp=60000.0, vmp=150.0, voc=800.0)},
        inverter,
    )
    row = result.frame.iloc[0]

    assert row["dc_voltage_threshold_loss_w"] == pytest.approx(60000.0)
    assert row["dc_voltage_window_accepted_w"] == 0.0
    assert row["dc_to_converter_w"] == 0.0
    assert row["ac_available_w"] == 0.0


def test_night_consumption_is_explicit_and_can_make_net_output_negative():
    inverter = _huawei_inverter()

    result = simulate_voltage_dependent_inverter(
        {
            1: _mppt(
                pmp=0.0,
                vmp=0.0,
                imp=0.0,
                voc=0.0,
                isc=0.0,
                active=False,
            )
        },
        inverter,
    )
    row = result.frame.iloc[0]

    assert result.metadata["night_loss_w"] == pytest.approx(2.0)
    assert row["ac_available_w"] == 0.0
    assert row["night_consumption_w"] == pytest.approx(2.0)
    assert row["standby_consumption_w"] == 0.0
    assert row["inverter_self_consumption_w"] == pytest.approx(2.0)
    assert row["ac_net_output_w"] == pytest.approx(-2.0)


def test_unknown_mppt_current_limit_remains_unmodeled_not_unlimited():
    inverter = _huawei_inverter()

    result = simulate_voltage_dependent_inverter(
        {1: _mppt(pmp=65000.0, vmp=650.0, imp=100.0)},
        inverter,
    )

    assert result.metadata["mppt_current_limit_known"] is False
    assert result.metadata["binding_current_limit_policy"] == (
        "sdm_constrained_operating_point.v1"
    )


def test_binding_verified_current_limit_requires_full_iv_operating_point():
    inverter = _huawei_inverter()
    inverter["mppt_template"]["max_operating_current_a"] = 25.0

    with pytest.raises(ValueError, match="full IV operating-point"):
        simulate_voltage_dependent_inverter(
            {1: _mppt(pmp=650.0 * 26.0, vmp=650.0, imp=26.0)},
            inverter,
        )


def test_temperature_derating_requires_explicit_basis_and_interpolates_power_limit():
    inverter = _huawei_inverter()
    mppt = _mppt(pmp=120000.0, vmp=650.0)

    with pytest.raises(ValueError, match="temperature_basis"):
        simulate_voltage_dependent_inverter(
            {1: mppt},
            inverter,
            inverter_temperature_c=35.0,
        )

    result_35 = simulate_voltage_dependent_inverter(
        {1: mppt},
        inverter,
        inverter_temperature_c=35.0,
        temperature_basis="ambient",
    )
    result_50 = simulate_voltage_dependent_inverter(
        {1: mppt},
        inverter,
        inverter_temperature_c=50.0,
        temperature_basis="ambient",
    )

    assert result_35.frame.iloc[0]["ac_power_limit_w"] == pytest.approx(105000.0)
    assert result_50.frame.iloc[0]["ac_power_limit_w"] == pytest.approx(68000.0)
    assert result_35.metadata["temperature_derating_applied"] is True
    assert result_35.metadata["temperature_basis"] == "ambient"


def test_absolute_temperature_limit_blocks_without_inventing_zero_power_curve():
    inverter = _huawei_inverter()

    with pytest.raises(ValueError, match="absolute limit"):
        simulate_voltage_dependent_inverter(
            {1: _mppt(pmp=60000.0, vmp=650.0)},
            inverter,
            inverter_temperature_c=62.0,
            temperature_basis="ambient",
        )


def test_absolute_dc_voltage_limit_is_a_blocker():
    inverter = _huawei_inverter()

    with pytest.raises(ValueError, match="absolute DC voltage"):
        simulate_voltage_dependent_inverter(
            {1: _mppt(pmp=60000.0, vmp=650.0, voc=1110.0)},
            inverter,
        )


def test_huawei_runtime_interpolation_policy_is_explicit():
    inverter = _huawei_inverter()
    result = simulate_voltage_dependent_inverter(
        {1: _mppt(pmp=60000.0, vmp=650.0)},
        inverter,
    )

    assert result.metadata["efficiency_power_interpolation"] == (
        "bounded_linear_pin_pout_v0.1"
    )
    assert result.metadata["efficiency_power_above_curve_policy"] == (
        "hold_endpoint_efficiency"
    )
    assert result.metadata["efficiency_voltage_interpolation"] == (
        "bounded_quadratic_v0.1"
    )
