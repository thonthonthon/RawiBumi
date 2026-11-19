import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from engine.irradiance import PlaneOfArrayResult
from engine.optical import (
    IAM_NONE,
    IAM_TABULATED,
    TabulatedIAMProfile,
    apply_iam,
    diffuse_iam_factors,
    evaluate_tabulated_iam,
)
from engine.thermal import THERMAL_PVSYST, calculate_pvsyst_temperature
from weather.core import build_time_semantics, build_weather_dataset


ROOT = Path(__file__).resolve().parents[2]


def _index(periods=3):
    return pd.date_range(
        "2026-03-21T10:00:00+07:00",
        periods=periods,
        freq="1h",
    )


def _reference_profile():
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
    return TabulatedIAMProfile.from_points(
        shared["iam_profile"],
        interpolation_method=shared["iam_interpolation_method"],
    )


def _unity_profile():
    return TabulatedIAMProfile.from_points(
        [(0.0, 1.0), (30.0, 1.0), (60.0, 1.0), (90.0, 1.0)],
        interpolation_method="cubic",
    )


def _poa(
    *,
    index=None,
    aoi=30.0,
    beam=500.0,
    isotropic=100.0,
    circumsolar=50.0,
    horizon=20.0,
    ground=30.0,
):
    index = _index(1) if index is None else index
    n = len(index)
    beam_values = np.broadcast_to(np.asarray(beam, dtype=float), n)
    iso_values = np.broadcast_to(np.asarray(isotropic, dtype=float), n)
    circ_values = np.broadcast_to(np.asarray(circumsolar, dtype=float), n)
    horizon_values = np.broadcast_to(np.asarray(horizon, dtype=float), n)
    ground_values = np.broadcast_to(np.asarray(ground, dtype=float), n)
    sky_values = iso_values + circ_values + horizon_values
    global_values = beam_values + sky_values + ground_values
    frame = pd.DataFrame(
        {
            "evaluation_time": index + pd.Timedelta(minutes=30),
            "aoi_deg": np.broadcast_to(np.asarray(aoi, dtype=float), n),
            "poa_beam_w_m2": beam_values,
            "poa_sky_diffuse_w_m2": sky_values,
            "poa_ground_diffuse_w_m2": ground_values,
            "poa_diffuse_w_m2": sky_values + ground_values,
            "poa_global_w_m2": global_values,
            "poa_isotropic_w_m2": iso_values,
            "poa_circumsolar_w_m2": circ_values,
            "poa_horizon_w_m2": horizon_values,
        },
        index=index,
    )
    return PlaneOfArrayResult(frame=frame, metadata={"model_id": "synthetic"})


def _weather(index, *, ambient=25.0, wind=None):
    frame = pd.DataFrame(
        {
            "ghi_w_m2": np.full(len(index), 500.0),
            "ambient_temperature_c": np.broadcast_to(
                np.asarray(ambient, dtype=float), len(index)
            ),
        },
        index=index,
    )
    if wind is not None:
        frame["wind_speed_m_s"] = np.broadcast_to(
            np.asarray(wind, dtype=float), len(index)
        )

    semantics = build_time_semantics(
        canonical_timezone="UTC+07:00",
        source_timestamp_convention="interval_start",
        native_interval_seconds=3600,
        current_interval_seconds=3600,
        source_timezone="UTC+07:00",
        source_utc_offset_hours=7.0,
    )
    return build_weather_dataset(
        frame,
        weather_dataset_id="wx-optical-thermal-test",
        revision_id="wx-optical-thermal-test-r1",
        name="Optical thermal test",
        site_id="site-test",
        timezone="UTC+07:00",
        native_resolution_seconds=3600,
        source_format="synthetic_test",
        source_timestamp_convention="interval_start",
        location={
            "latitude_deg": -6.425,
            "longitude_deg": 106.831,
            "elevation_m": 93.0,
        },
        time_semantics=semantics,
    )


def test_pvsyst_reference_iam_profile_reproduces_control_points():
    profile = _reference_profile()

    assert profile.interpolation_method == "cubic"
    assert evaluate_tabulated_iam(0.0, profile) == pytest.approx(1.0, abs=1e-12)
    assert evaluate_tabulated_iam(60.0, profile) == pytest.approx(
        0.999, abs=1e-12
    )
    assert evaluate_tabulated_iam(80.0, profile) == pytest.approx(
        0.925, abs=1e-12
    )
    assert evaluate_tabulated_iam(85.0, profile) == pytest.approx(
        0.743, abs=1e-12
    )
    assert evaluate_tabulated_iam(90.0, profile) == 0.0
    assert evaluate_tabulated_iam(100.0, profile) == 0.0


def test_unity_profile_integrates_to_unity_for_diffuse_regions():
    factors = diffuse_iam_factors(_unity_profile(), surface_tilt_deg=20.0)

    assert factors["sky"] == pytest.approx(1.0, abs=2e-12)
    assert factors["horizon"] == pytest.approx(1.0, abs=2e-12)
    assert factors["ground"] == pytest.approx(1.0, abs=2e-12)


def test_reference_diffuse_iam_factors_are_deterministic_and_physical():
    profile = _reference_profile()
    first = diffuse_iam_factors(profile, surface_tilt_deg=20.0)
    second = diffuse_iam_factors(profile, surface_tilt_deg=20.0)

    assert first == second
    for value in first.values():
        assert 0.0 <= value <= 1.01


def test_identity_iam_preserves_all_poa_energy():
    poa = _poa(aoi=80.0)

    result = apply_iam(
        poa,
        model_id=IAM_NONE,
        surface_tilt_deg=20.0,
    )

    assert np.allclose(
        result.frame["effective_irradiance_w_m2"],
        poa.frame["poa_global_w_m2"],
        atol=1e-12,
        rtol=0.0,
    )
    assert np.allclose(result.frame["iam_delta_w_m2"], 0.0, atol=1e-12)
    assert result.metadata["model_id"] == IAM_NONE


def test_component_aware_tabulated_iam_applies_beam_to_circumsolar():
    poa = _poa(
        aoi=80.0,
        beam=500.0,
        isotropic=100.0,
        circumsolar=50.0,
        horizon=20.0,
        ground=30.0,
    )
    profile = _reference_profile()
    factors = diffuse_iam_factors(profile, surface_tilt_deg=20.0)

    result = apply_iam(
        poa,
        model_id=IAM_TABULATED,
        surface_tilt_deg=20.0,
        profile=profile,
    )
    row = result.frame.iloc[0]

    assert row["iam_beam"] == pytest.approx(0.925, abs=1e-12)
    assert row["effective_poa_beam_w_m2"] == pytest.approx(
        500.0 * 0.925, abs=1e-9
    )
    assert row["effective_poa_circumsolar_w_m2"] == pytest.approx(
        50.0 * 0.925, abs=1e-9
    )
    assert row["effective_poa_isotropic_w_m2"] == pytest.approx(
        100.0 * factors["sky"], abs=1e-9
    )
    assert row["effective_poa_horizon_w_m2"] == pytest.approx(
        20.0 * factors["horizon"], abs=1e-9
    )
    assert row["effective_poa_ground_diffuse_w_m2"] == pytest.approx(
        30.0 * factors["ground"], abs=1e-9
    )
    expected = (
        500.0 * 0.925
        + 50.0 * 0.925
        + 100.0 * factors["sky"]
        + 20.0 * factors["horizon"]
        + 30.0 * factors["ground"]
    )
    assert row["effective_irradiance_w_m2"] == pytest.approx(expected, abs=1e-9)
    assert row["iam_delta_w_m2"] == pytest.approx(
        poa.frame.iloc[0]["poa_global_w_m2"] - expected,
        abs=1e-9,
    )
    assert result.metadata["circumsolar_policy"] == "beam_iam_at_solar_aoi"
    assert result.metadata["profile"]["interpolation_method"] == "cubic"


def test_tabulated_iam_requires_explicit_profile():
    with pytest.raises(ValueError, match="requires an explicit profile"):
        apply_iam(
            _poa(),
            model_id=IAM_TABULATED,
            surface_tilt_deg=20.0,
        )


def test_pvsyst_thermal_equation_matches_closed_form():
    index = _index(1)
    poa = _poa(
        index=index,
        beam=1000.0,
        isotropic=0.0,
        circumsolar=0.0,
        horizon=0.0,
        ground=0.0,
    )
    weather = _weather(index, ambient=25.0, wind=2.0)

    result = calculate_pvsyst_temperature(
        poa,
        weather,
        u_c_w_m2k=20.0,
        u_v_w_m2k_per_ms=5.0,
        alpha_absorption=0.90,
        module_efficiency=0.20,
    )
    row = result.frame.iloc[0]

    expected_heat = 1000.0 * 0.90 * (1.0 - 0.20)
    expected_loss_coefficient = 20.0 + 5.0 * 2.0
    expected_rise = expected_heat / expected_loss_coefficient

    assert expected_heat == pytest.approx(720.0)
    assert expected_rise == pytest.approx(24.0)
    assert row["heat_input_w_m2"] == pytest.approx(expected_heat, abs=1e-12)
    assert row["heat_loss_coefficient_w_m2k"] == pytest.approx(
        expected_loss_coefficient, abs=1e-12
    )
    assert row["temperature_rise_c"] == pytest.approx(24.0, abs=1e-12)
    assert row["cell_temperature_c"] == pytest.approx(49.0, abs=1e-12)
    assert row["module_temperature_c"] == pytest.approx(49.0, abs=1e-12)
    assert result.metadata["model_id"] == THERMAL_PVSYST
    assert result.metadata["irradiance_basis"] == (
        "incident_poa_global_before_iam"
    )


def test_pvsyst_uv_zero_does_not_require_wind_data():
    index = _index(1)
    poa = _poa(
        index=index,
        beam=800.0,
        isotropic=0.0,
        circumsolar=0.0,
        horizon=0.0,
        ground=0.0,
    )
    weather = _weather(index, ambient=30.0)

    result = calculate_pvsyst_temperature(
        poa,
        weather,
        u_c_w_m2k=20.0,
        u_v_w_m2k_per_ms=0.0,
        alpha_absorption=0.90,
        module_efficiency=0.20,
    )

    assert result.metadata["wind_speed_source"] == "not_required_uv_zero"
    assert result.frame.iloc[0]["wind_speed_m_s"] == 0.0


def test_pvsyst_nonzero_uv_requires_complete_wind():
    index = _index(1)
    weather = _weather(index, ambient=30.0)

    with pytest.raises(ValueError, match="wind_speed_m_s is required"):
        calculate_pvsyst_temperature(
            _poa(index=index),
            weather,
            u_c_w_m2k=20.0,
            u_v_w_m2k_per_ms=5.0,
            alpha_absorption=0.90,
            module_efficiency=0.20,
        )


def test_zero_poa_returns_ambient_temperature():
    index = _index(2)
    poa = _poa(
        index=index,
        beam=[0.0, 0.0],
        isotropic=[0.0, 0.0],
        circumsolar=[0.0, 0.0],
        horizon=[0.0, 0.0],
        ground=[0.0, 0.0],
    )
    weather = _weather(index, ambient=[28.0, 29.0])

    result = calculate_pvsyst_temperature(
        poa,
        weather,
        u_c_w_m2k=20.0,
        u_v_w_m2k_per_ms=0.0,
        alpha_absorption=0.90,
        module_efficiency=[0.0, 0.0],
    )

    assert np.allclose(
        result.frame["cell_temperature_c"],
        [28.0, 29.0],
        atol=1e-12,
        rtol=0.0,
    )
    assert np.allclose(result.frame["temperature_rise_c"], 0.0, atol=1e-12)


def test_reference_pan_area_efficiency_and_absorption_are_frozen():
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
    module = shared["module"]
    thermal = shared["thermal"]

    assert module["area_m2"] == pytest.approx(
        module["width_m"] * module["height_m"], abs=1e-12
    )
    assert module["stc_efficiency_fraction"] == pytest.approx(
        module["unit_nominal_power_wp"] / (1000.0 * module["area_m2"]),
        abs=1e-15,
    )
    assert module["absorption_coefficient"] == 0.90
    assert shared["iam_profile_type"] == "TCubicProfile"
    assert shared["iam_interpolation_method"] == "cubic"
    assert thermal["uc_w_m2k"] == 20.0
    assert thermal["uv_w_m2k_per_ms"] == 0.0
    assert thermal["module_efficiency_policy"] == (
        "dynamic_from_module_electrical_model"
    )
