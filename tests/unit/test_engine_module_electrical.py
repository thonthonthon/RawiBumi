from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from components.candidates import build_module_candidate
from components.pan import map_pan, parse_pan_text
from engine.irradiance import PlaneOfArrayResult
from engine.module import (
    MODULE_PVSYST_SDM,
    calculate_pvsyst_module_electrical,
    extract_validated_pvsyst_parameter_set,
    solve_pvsyst_module_thermal_coupling,
)
from engine.optical import OpticalResult
from engine.thermal import ThermalResult
from weather.core import build_time_semantics, build_weather_dataset


ROOT = Path(__file__).resolve().parents[2]


def _candidate(relative_path: str, *, candidate_id: str):
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    mapping = map_pan(parse_pan_text(text))
    return build_module_candidate(
        mapping,
        candidate_id=candidate_id,
        module_definition_id=f"{candidate_id}-definition",
        revision_id=f"{candidate_id}-r1",
        source_id=f"{candidate_id}-source",
    )


def _index(periods=1):
    return pd.date_range(
        "2026-03-21T10:00:00+07:00",
        periods=periods,
        freq="1h",
    )


def _optical(index, *, effective, incident=None):
    effective_values = np.broadcast_to(
        np.asarray(effective, dtype=float), len(index)
    )
    if incident is None:
        incident_values = effective_values.copy()
    else:
        incident_values = np.broadcast_to(
            np.asarray(incident, dtype=float), len(index)
        )
    frame = pd.DataFrame(
        {
            "evaluation_time": index + pd.Timedelta(minutes=30),
            "effective_irradiance_w_m2": effective_values,
            "incident_poa_global_w_m2": incident_values,
        },
        index=index,
    )
    return OpticalResult(frame=frame, metadata={"model_id": "synthetic"})


def _thermal(index, *, temperature):
    values = np.broadcast_to(np.asarray(temperature, dtype=float), len(index))
    frame = pd.DataFrame(
        {
            "evaluation_time": index + pd.Timedelta(minutes=30),
            "cell_temperature_c": values,
            "module_temperature_c": values,
        },
        index=index,
    )
    return ThermalResult(frame=frame, metadata={"model_id": "synthetic"})


def _poa(index, *, incident):
    values = np.broadcast_to(np.asarray(incident, dtype=float), len(index))
    zeros = np.zeros(len(index), dtype=float)
    frame = pd.DataFrame(
        {
            "evaluation_time": index + pd.Timedelta(minutes=30),
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


def _weather(index, *, ambient=25.0):
    frame = pd.DataFrame(
        {
            "ghi_w_m2": np.full(len(index), 500.0),
            "ambient_temperature_c": np.broadcast_to(
                np.asarray(ambient, dtype=float), len(index)
            ),
        },
        index=index,
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
        weather_dataset_id="wx-module-runtime-test",
        revision_id="wx-module-runtime-test-r1",
        name="Module runtime test",
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


def _area_from_definition(module):
    mech = module["mechanical"]
    return float(mech["width_m"]) * float(mech["height_m"])


def test_runtime_reuses_validated_synthetic_pvsyst_parameter_set():
    candidate = _candidate(
        "tests/fixtures/panond/synthetic_module.pan",
        candidate_id="cand-runtime-synthetic",
    )
    module = candidate["canonical_data"]
    params = extract_validated_pvsyst_parameter_set(module)

    assert candidate["capability_flags"]["detailed_sdm_ready"] is True
    assert set(params)
    assert module["electrical_models"][0]["validation"]["passed"] is True


def test_runtime_matches_existing_off_stc_regression_anchor():
    candidate = _candidate(
        "tests/fixtures/panond/synthetic_module.pan",
        candidate_id="cand-runtime-anchor",
    )
    module = candidate["canonical_data"]
    params = extract_validated_pvsyst_parameter_set(module)
    index = _index()

    result = calculate_pvsyst_module_electrical(
        _optical(index, effective=600.0, incident=600.0),
        _thermal(index, temperature=50.0),
        parameter_set=params,
        module_area_m2=_area_from_definition(module),
    )
    row = result.frame.iloc[0]

    assert row["isc_a"] == pytest.approx(8.5100311327, rel=1e-7)
    assert row["voc_v"] == pytest.approx(45.7227744393, rel=1e-7)
    assert row["pmp_w"] == pytest.approx(305.2207439830, rel=1e-7)
    assert row["pmp_w"] == pytest.approx(
        row["vmp_v"] * row["imp_a"], rel=1e-10
    )
    assert 0.0 < row["module_efficiency_fraction"] < 1.0
    assert result.metadata["model_id"] == MODULE_PVSYST_SDM
    assert result.metadata["active_interval_count"] == 1


def test_manufacturer_jinko_runtime_reproduces_stc_reference_points_within_gate():
    candidate = _candidate(
        "tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN",
        candidate_id="cand-runtime-jinko",
    )
    module = candidate["canonical_data"]
    model = module["electrical_models"][0]
    params = model["parameter_set"]
    index = _index()

    result = calculate_pvsyst_module_electrical(
        _optical(index, effective=1000.0, incident=1000.0),
        _thermal(index, temperature=25.0),
        parameter_set=params,
        module_area_m2=_area_from_definition(module),
    )
    row = result.frame.iloc[0]
    stc = module["stc"]

    for actual, expected in (
        (row["isc_a"], stc["isc_a"]),
        (row["voc_v"], stc["voc_v"]),
        (row["imp_a"], stc["imp_a"]),
        (row["vmp_v"], stc["vmp_v"]),
        (row["pmp_w"], stc["pmp_w"]),
    ):
        assert actual == pytest.approx(expected, rel=0.02)

    assert row["module_efficiency_fraction"] == pytest.approx(
        row["pmp_w"] / (1000.0 * _area_from_definition(module)),
        rel=1e-12,
    )


def test_zero_effective_irradiance_returns_zero_iv_state():
    candidate = _candidate(
        "tests/fixtures/panond/synthetic_module.pan",
        candidate_id="cand-runtime-night",
    )
    module = candidate["canonical_data"]
    params = extract_validated_pvsyst_parameter_set(module)
    index = _index(periods=2)

    result = calculate_pvsyst_module_electrical(
        _optical(index, effective=[0.0, 0.0], incident=[0.0, 10.0]),
        _thermal(index, temperature=[25.0, 26.0]),
        parameter_set=params,
        module_area_m2=_area_from_definition(module),
    )

    assert np.allclose(
        result.frame[["isc_a", "voc_v", "imp_a", "vmp_v", "pmp_w"]],
        0.0,
        atol=0.0,
    )
    assert np.allclose(result.frame["module_efficiency_fraction"], 0.0)
    assert result.metadata["active_interval_count"] == 0


def test_external_efficiency_uses_incident_poa_not_effective_irradiance():
    candidate = _candidate(
        "tests/fixtures/panond/synthetic_module.pan",
        candidate_id="cand-runtime-efficiency-basis",
    )
    module = candidate["canonical_data"]
    params = extract_validated_pvsyst_parameter_set(module)
    index = _index()

    result = calculate_pvsyst_module_electrical(
        _optical(index, effective=800.0, incident=900.0),
        _thermal(index, temperature=35.0),
        parameter_set=params,
        module_area_m2=_area_from_definition(module),
    )
    row = result.frame.iloc[0]
    area = _area_from_definition(module)

    assert row["module_efficiency_fraction"] == pytest.approx(
        row["pmp_w"] / (900.0 * area), rel=1e-12
    )
    assert row["module_efficiency_on_effective_irradiance_fraction"] == (
        pytest.approx(row["pmp_w"] / (800.0 * area), rel=1e-12)
    )
    assert (
        row["module_efficiency_fraction"]
        < row["module_efficiency_on_effective_irradiance_fraction"]
    )


def test_coupled_thermal_electrical_solver_converges_to_self_consistent_state():
    candidate = _candidate(
        "tests/fixtures/panond/synthetic_module.pan",
        candidate_id="cand-runtime-coupled",
    )
    module = candidate["canonical_data"]
    params = extract_validated_pvsyst_parameter_set(module)
    area = _area_from_definition(module)
    index = _index(periods=3)
    incident = np.array([400.0, 800.0, 1000.0])
    effective = np.array([390.0, 780.0, 970.0])

    result = solve_pvsyst_module_thermal_coupling(
        _poa(index, incident=incident),
        _optical(index, effective=effective, incident=incident),
        _weather(index, ambient=[25.0, 28.0, 30.0]),
        parameter_set=params,
        module_area_m2=area,
        u_c_w_m2k=20.0,
        u_v_w_m2k_per_ms=0.0,
        alpha_absorption=0.90,
        initial_module_efficiency_fraction=0.0,
        temperature_tolerance_c=1e-5,
        efficiency_tolerance_fraction=1e-9,
        max_iterations=25,
    )

    assert result.metadata["converged"] is True
    assert 1 < result.metadata["iterations"] <= 25
    assert result.metadata["returned_temperature_residual_c"] <= 1e-5
    assert result.metadata["returned_efficiency_residual_fraction"] <= 1e-9

    electrical_eta = result.electrical.frame[
        "module_efficiency_fraction"
    ].to_numpy(dtype=float)
    thermal_eta = result.thermal.frame[
        "module_efficiency_fraction"
    ].to_numpy(dtype=float)
    assert np.allclose(electrical_eta, thermal_eta, atol=1e-9, rtol=0.0)
    assert (
        result.thermal.frame["cell_temperature_c"]
        > result.thermal.frame["ambient_temperature_c"]
    ).all()
    assert (result.electrical.frame["pmp_w"] > 0).all()


def test_extractor_rejects_unvalidated_detailed_model():
    candidate = _candidate(
        "tests/fixtures/panond/synthetic_module.pan",
        candidate_id="cand-runtime-invalid-extract",
    )
    module = candidate["canonical_data"]
    module["electrical_models"][0]["validation"]["passed"] = False

    with pytest.raises(ValueError, match="has not passed detailed validation"):
        extract_validated_pvsyst_parameter_set(module)
