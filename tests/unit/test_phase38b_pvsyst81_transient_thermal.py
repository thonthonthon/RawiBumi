from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from components.candidates import build_module_candidate
from components.pan import map_pan, parse_pan_text
from engine.irradiance import PlaneOfArrayResult
from engine.module import (
    extract_validated_pvsyst_parameter_set,
    solve_pvsyst_module_thermal_coupling,
)
from engine.optical import OpticalResult
from engine.thermal import (
    DEFAULT_PVSYST81_UNIT_MASS_KG_M2,
    THERMAL_PVSYST,
    THERMAL_PVSYST81_TRANSIENT,
    ThermalResult,
    calculate_pvsyst81_transient_temperature,
)
from weather.core import build_time_semantics, build_weather_dataset


ROOT = Path(__file__).resolve().parents[2]


def _index(*, periods=4, interval_seconds=60):
    return pd.date_range(
        "2026-03-21T10:00:00+07:00",
        periods=periods,
        freq=pd.Timedelta(seconds=interval_seconds),
    )


def _weather(
    index,
    *,
    interval_seconds,
    ambient=25.0,
    wind=0.0,
    include_wind=True,
):
    frame = pd.DataFrame(
        {
            "ghi_w_m2": np.full(len(index), 500.0),
            "ambient_temperature_c": np.broadcast_to(
                np.asarray(ambient, dtype=float), len(index)
            ),
        },
        index=index,
    )
    if include_wind:
        frame["wind_speed_m_s"] = np.broadcast_to(
            np.asarray(wind, dtype=float), len(index)
        )
    semantics = build_time_semantics(
        canonical_timezone="UTC+07:00",
        source_timestamp_convention="interval_start",
        native_interval_seconds=interval_seconds,
        current_interval_seconds=interval_seconds,
        source_timezone="UTC+07:00",
        source_utc_offset_hours=7.0,
    )
    return build_weather_dataset(
        frame,
        weather_dataset_id="wx-phase38b",
        revision_id="wx-phase38b-r1",
        name="Phase 3.8B thermal test",
        site_id="site-phase38b",
        timezone="UTC+07:00",
        native_resolution_seconds=interval_seconds,
        source_format="synthetic_test",
        source_timestamp_convention="interval_start",
        location={
            "latitude_deg": -6.425,
            "longitude_deg": 106.831,
            "elevation_m": 93.0,
        },
        time_semantics=semantics,
    )


def _steady(index, temperatures, *, ambient=25.0, eta=0.20):
    temperature = np.broadcast_to(
        np.asarray(temperatures, dtype=float), len(index)
    )
    ambient_values = np.broadcast_to(
        np.asarray(ambient, dtype=float), len(index)
    )
    efficiency = np.broadcast_to(np.asarray(eta, dtype=float), len(index))
    frame = pd.DataFrame(
        {
            "ambient_temperature_c": ambient_values,
            "wind_speed_m_s": np.zeros(len(index), dtype=float),
            "module_efficiency_fraction": efficiency,
            "temperature_rise_c": temperature - ambient_values,
            "cell_temperature_c": temperature,
            "module_temperature_c": temperature,
        },
        index=index,
    )
    return ThermalResult(
        frame=frame,
        metadata={
            "schema_name": "ThermalResult",
            "schema_version": "0.1",
            "model_id": THERMAL_PVSYST,
            "temperature_state": "steady_state",
        },
    )


def _poa(index, *, incident):
    values = np.broadcast_to(np.asarray(incident, dtype=float), len(index))
    zeros = np.zeros(len(index), dtype=float)
    frame = pd.DataFrame(
        {
            "evaluation_time": index + (index[1] - index[0]) / 2
            if len(index) > 1
            else index,
            "aoi_deg": zeros,
            "poa_beam_w_m2": values,
            "poa_sky_diffuse_w_m2": zeros,
            "poa_ground_diffuse_w_m2": zeros,
            "poa_diffuse_w_m2": zeros,
            "poa_global_w_m2": values,
            "poa_isotropic_w_m2": zeros,
            "poa_circumsolar_w_m2": zeros,
            "poa_horizon_w_m2": zeros,
        },
        index=index,
    )
    return PlaneOfArrayResult(frame=frame, metadata={"model_id": "synthetic"})


def _optical(index, *, effective, incident):
    effective_values = np.broadcast_to(
        np.asarray(effective, dtype=float), len(index)
    )
    incident_values = np.broadcast_to(
        np.asarray(incident, dtype=float), len(index)
    )
    frame = pd.DataFrame(
        {
            "evaluation_time": index,
            "effective_irradiance_w_m2": effective_values,
            "incident_poa_global_w_m2": incident_values,
        },
        index=index,
    )
    return OpticalResult(frame=frame, metadata={"model_id": "synthetic"})


def _synthetic_module():
    text = (
        ROOT / "tests/fixtures/panond/synthetic_module.pan"
    ).read_text(encoding="utf-8")
    return build_module_candidate(
        map_pan(parse_pan_text(text)),
        candidate_id="cand-phase38b",
        module_definition_id="mod-phase38b",
        revision_id="mod-phase38b-r1",
        source_id="src-phase38b",
    )["canonical_data"]


def test_pvsyst81_relaxation_rate_uses_documented_wind_and_unit_mass_equation():
    index = _index(periods=2, interval_seconds=60)
    weather = _weather(
        index,
        interval_seconds=60,
        wind=[0.0, 2.0],
    )

    result = calculate_pvsyst81_transient_temperature(
        _steady(index, [25.0, 25.0]),
        weather,
    )

    expected = np.array(
        [
            0.0046 - 0.00023 * 11.0,
            0.0046 + 0.00046 * 2.0 - 0.00023 * 11.0
            - 0.000016 * 2.0 * 11.0,
        ]
    )
    assert result.metadata["model_id"] == THERMAL_PVSYST81_TRANSIENT
    assert result.metadata["module_unit_mass_kg_m2"] == pytest.approx(
        DEFAULT_PVSYST81_UNIT_MASS_KG_M2
    )
    assert result.metadata["module_unit_mass_source"] == (
        "pvsyst81_default_missing_mass"
    )
    assert np.allclose(
        result.frame["thermal_relaxation_rate_s_inv"],
        expected,
        atol=1e-15,
        rtol=0.0,
    )


def test_pvsyst81_transient_temperature_delays_a_one_minute_step_change():
    index = _index(periods=5, interval_seconds=60)
    weather = _weather(index, interval_seconds=60, wind=0.0)
    steady = _steady(index, [20.0, 20.0, 60.0, 60.0, 60.0])

    result = calculate_pvsyst81_transient_temperature(
        steady,
        weather,
        module_unit_mass_kg_m2=11.0,
    )

    actual = result.frame["cell_temperature_c"].to_numpy(dtype=float)
    assert actual[0] == pytest.approx(20.0)
    assert actual[1] == pytest.approx(20.0)
    assert 20.0 < actual[2] < 60.0
    assert actual[2] < actual[3] < 60.0
    assert actual[3] < actual[4] < 60.0
    assert np.allclose(
        result.frame["steady_state_cell_temperature_c"],
        [20.0, 20.0, 60.0, 60.0, 60.0],
        atol=0.0,
        rtol=0.0,
    )


def test_pvsyst81_hourly_cutoff_edge_keeps_immediate_previous_state():
    index = _index(periods=2, interval_seconds=3600)
    weather = _weather(index, interval_seconds=3600, wind=0.0)

    result = calculate_pvsyst81_transient_temperature(
        _steady(index, [20.0, 60.0]),
        weather,
        module_unit_mass_kg_m2=11.0,
    )

    rate = 0.0046 - 0.00023 * 11.0
    x = rate * 3600.0
    response = 1.0 + np.expm1(-x) / x
    expected_second = 20.0 + (60.0 - 20.0) * response

    assert result.metadata["cutoff_seconds"] < 3600.0
    assert result.metadata["history_lag_count"] == 1
    assert result.metadata["cutoff_under_timestep_policy"] == (
        "always_include_immediate_previous_steady_state_sample"
    )
    assert result.frame.iloc[1]["cell_temperature_c"] == pytest.approx(
        expected_second,
        rel=1e-12,
    )


def test_pvsyst81_invalid_large_unit_mass_uses_documented_default():
    index = _index(periods=2, interval_seconds=60)
    weather = _weather(index, interval_seconds=60, wind=0.0)

    result = calculate_pvsyst81_transient_temperature(
        _steady(index, [25.0, 30.0]),
        weather,
        module_unit_mass_kg_m2=25.0,
    )

    assert result.metadata["module_unit_mass_kg_m2"] == pytest.approx(11.0)
    assert result.metadata["module_unit_mass_source"] == (
        "pvsyst81_default_invalid_mass_ge_20"
    )


def test_pvsyst81_transient_requires_wind_even_when_steady_uv_is_zero():
    index = _index(periods=2, interval_seconds=60)
    weather = _weather(
        index,
        interval_seconds=60,
        include_wind=False,
    )

    with pytest.raises(ValueError, match="requires weather wind_speed_m_s"):
        calculate_pvsyst81_transient_temperature(
            _steady(index, [25.0, 30.0]),
            weather,
            module_unit_mass_kg_m2=11.0,
        )


def test_transient_thermal_is_inside_the_electrical_efficiency_fixed_point():
    module = _synthetic_module()
    params = extract_validated_pvsyst_parameter_set(module)
    area = float(module["mechanical"]["width_m"]) * float(
        module["mechanical"]["height_m"]
    )
    index = _index(periods=6, interval_seconds=60)
    incident = np.array([0.0, 300.0, 900.0, 900.0, 300.0, 0.0])
    effective = incident * 0.98
    weather = _weather(
        index,
        interval_seconds=60,
        ambient=[25.0, 25.0, 26.0, 27.0, 27.0, 26.0],
        wind=1.5,
    )

    result = solve_pvsyst_module_thermal_coupling(
        _poa(index, incident=incident),
        _optical(index, effective=effective, incident=incident),
        weather,
        parameter_set=params,
        module_area_m2=area,
        u_c_w_m2k=20.0,
        u_v_w_m2k_per_ms=0.0,
        alpha_absorption=0.90,
        thermal_model_id=THERMAL_PVSYST81_TRANSIENT,
        module_unit_mass_kg_m2=11.0,
        temperature_tolerance_c=1e-5,
        efficiency_tolerance_fraction=1e-9,
        max_iterations=30,
    )

    assert result.metadata["converged"] is True
    assert result.metadata["thermal_model_id"] == THERMAL_PVSYST81_TRANSIENT
    assert result.thermal.metadata["base_steady_state_model_id"] == THERMAL_PVSYST
    assert result.metadata["returned_temperature_residual_c"] <= 1e-5
    assert result.metadata["returned_efficiency_residual_fraction"] <= 1e-9

    steady_temperature = result.thermal.frame[
        "steady_state_cell_temperature_c"
    ].to_numpy(dtype=float)
    transient_temperature = result.thermal.frame[
        "cell_temperature_c"
    ].to_numpy(dtype=float)
    assert not np.allclose(
        transient_temperature,
        steady_temperature,
        atol=1e-6,
        rtol=0.0,
    )
    assert np.allclose(
        result.electrical.frame["module_efficiency_fraction"],
        result.thermal.frame["module_efficiency_fraction"],
        atol=1e-9,
        rtol=0.0,
    )


def test_jinko_mass_produces_expected_pvsyst81_unit_mass():
    text = (
        ROOT
        / "tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN"
    ).read_text(encoding="utf-8")
    module = build_module_candidate(
        map_pan(parse_pan_text(text)),
        candidate_id="cand-phase38b-jinko",
        module_definition_id="mod-phase38b-jinko",
        revision_id="mod-phase38b-jinko-r1",
        source_id="src-phase38b-jinko",
    )["canonical_data"]
    mechanical = module["mechanical"]

    assert mechanical["mass_kg"] == pytest.approx(28.0)
    unit_mass = mechanical["mass_kg"] / (
        mechanical["width_m"] * mechanical["height_m"]
    )
    assert unit_mass == pytest.approx(10.839050932700333)
