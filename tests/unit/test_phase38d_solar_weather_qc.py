import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from jsonschema import Draft202012Validator

from engine.solar import SolarPositionResult, solar_position_from_weather
from weather.core import build_time_semantics, build_weather_dataset
from weather.validation import (
    SOLAR_AWARE_QC_POLICY_ID,
    SolarAwareQCPolicy,
    attach_solar_aware_weather_qc,
    run_solar_aware_weather_qc,
)


ROOT = Path(__file__).resolve().parents[2]


def _index(periods=4, resolution_seconds=3600):
    return pd.date_range(
        "2026-03-21T09:00:00+07:00",
        periods=periods,
        freq=pd.Timedelta(seconds=resolution_seconds),
    )


def _weather(
    *,
    index=None,
    ghi=None,
    dni=None,
    dhi=None,
    temperature=25.0,
    resolution_seconds=3600,
):
    index = index if index is not None else _index(resolution_seconds=resolution_seconds)
    if ghi is None:
        ghi = [350.0, 656.2, 149.5, 0.0]
    if dni is None:
        dni = [500.0, 700.0, 400.0, 0.0]
    if dhi is None:
        dhi = [100.0, 120.0, 80.0, 0.0]

    frame = pd.DataFrame(index=index)
    frame["ghi_w_m2"] = np.broadcast_to(np.asarray(ghi, dtype=float), len(index))
    if dni is not False:
        frame["dni_w_m2"] = np.broadcast_to(np.asarray(dni, dtype=float), len(index))
    if dhi is not False:
        frame["dhi_w_m2"] = np.broadcast_to(np.asarray(dhi, dtype=float), len(index))
    frame["ambient_temperature_c"] = np.broadcast_to(
        np.asarray(temperature, dtype=float), len(index)
    )

    semantics = build_time_semantics(
        canonical_timezone="UTC+07:00",
        source_timestamp_convention="interval_start",
        native_interval_seconds=resolution_seconds,
        current_interval_seconds=resolution_seconds,
        source_timezone="UTC+07:00",
    )
    return build_weather_dataset(
        frame,
        weather_dataset_id="wx-phase38d",
        revision_id="wx-phase38d-r1",
        name="Phase 3.8D synthetic weather",
        site_id="site-phase38d",
        timezone="UTC+07:00",
        native_resolution_seconds=resolution_seconds,
        source_format="synthetic_test",
        source_timestamp_convention="interval_start",
        location={
            "latitude_deg": -6.425,
            "longitude_deg": 106.831,
            "elevation_m": 93.0,
        },
        time_semantics=semantics,
    )


def _solar(
    index,
    *,
    zenith=(60.0, 40.0, 80.0, 100.0),
    resolution_seconds=3600,
):
    z = np.broadcast_to(np.asarray(zenith, dtype=float), len(index))
    frame = pd.DataFrame(index=index)
    frame["evaluation_time"] = (
        index + pd.Timedelta(seconds=resolution_seconds / 2)
    )
    frame["solar_apparent_zenith_deg"] = z
    frame["solar_zenith_deg"] = z
    frame["solar_apparent_elevation_deg"] = 90.0 - z
    frame["solar_elevation_deg"] = 90.0 - z
    frame["solar_azimuth_deg"] = 180.0
    frame["equation_of_time_minutes"] = 0.0
    return SolarPositionResult(
        frame=frame,
        metadata={
            "schema_name": "SolarPositionResult",
            "schema_version": "0.1",
            "model_id": "solar_position.synthetic.phase38d",
            "implementation": "synthetic_test",
            "representative_time_policy": "interval_midpoint",
            "solar_evaluation_offset_minutes": 0.0,
        },
    )


def _rules(report):
    return [finding["rule_id"] for finding in report["findings"]]


def test_clean_three_component_weather_passes_solar_aware_qc_and_schema():
    index = _index()
    zenith = np.array([60.0, 40.0, 80.0, 100.0])
    dni = np.array([500.0, 700.0, 400.0, 0.0])
    dhi = np.array([100.0, 120.0, 80.0, 0.0])
    ghi = dhi + dni * np.maximum(np.cos(np.radians(zenith)), 0.0)
    weather = _weather(index=index, ghi=ghi, dni=dni, dhi=dhi)
    solar = _solar(index, zenith=zenith)

    report = run_solar_aware_weather_qc(weather, solar)

    assert report["status"] == "passed"
    assert report["base_simulation_input_ready"] is True
    assert report["findings"] == []

    schema = json.loads(
        (ROOT / "weather/schema/weather-qc-report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(report)


def test_component_sum_inconsistency_uses_bsrn_zenith_dependent_tolerance():
    index = _index(periods=2)
    zenith = np.array([60.0, 80.0])
    dni = np.array([500.0, 500.0])
    dhi = np.array([100.0, 100.0])
    sum_sw = dhi + dni * np.cos(np.radians(zenith))

    # 10% high: fails the +/-8% band at SZA<75, but remains inside the
    # +/-15% high-zenith band at SZA=80.
    ghi = np.array([sum_sw[0] * 1.10, sum_sw[1] * 1.10])
    weather = _weather(index=index, ghi=ghi, dni=dni, dhi=dhi)
    solar = _solar(index, zenith=zenith)

    report = run_solar_aware_weather_qc(weather, solar)
    finding = next(
        item
        for item in report["findings"]
        if item["rule_id"] == "WX_SOLAR_COMPONENT_SUM_INCONSISTENT"
    )

    assert report["status"] == "warning"
    assert report["base_simulation_input_ready"] is True
    assert finding["count"] == 1
    assert finding["examples"] == [index[0].isoformat()]
    assert finding["context"]["reference"] == (
        "BSRN_recommended_QC_tests_V2_component_comparison"
    )
    assert finding["context"]["low_zenith_band"][
        "ratio_tolerance_fraction"
    ] == pytest.approx(0.08)
    assert finding["context"]["high_zenith_band"][
        "ratio_tolerance_fraction"
    ] == pytest.approx(0.15)


def test_bsrn_physical_limit_violation_is_error_and_not_clipped():
    index = _index(periods=1)
    weather = _weather(
        index=index,
        ghi=[1100.0],
        dni=[2000.0],
        dhi=[100.0],
    )
    original = weather.series.copy(deep=True)
    solar = _solar(index, zenith=[60.0])

    report = run_solar_aware_weather_qc(weather, solar)

    assert "WX_SOLAR_DNI_ABOVE_PHYSICAL_LIMIT" in _rules(report)
    assert report["status"] == "failed"
    assert report["base_simulation_input_ready"] is False
    pd.testing.assert_frame_equal(weather.series, original)


def test_night_irradiance_is_time_reference_warning_not_automatic_failure():
    index = _index(periods=1)
    weather = _weather(
        index=index,
        ghi=[30.0],
        dni=[0.0],
        dhi=[30.0],
    )
    solar = _solar(index, zenith=[95.0])

    report = run_solar_aware_weather_qc(weather, solar)
    finding = next(
        item
        for item in report["findings"]
        if item["rule_id"] == "WX_SOLAR_IRRADIANCE_WHEN_SUN_BELOW_HORIZON"
    )

    assert report["status"] == "warning"
    assert report["base_simulation_input_ready"] is True
    assert finding["count"] == 1
    assert finding["context"]["solar_elevation_threshold_deg"] == pytest.approx(-3.0)
    assert finding["context"]["source_timestamp_convention"] == "interval_start"
    assert finding["context"]["representative_time_policy"] == "interval_midpoint"


def test_daylight_with_near_zero_ghi_is_warning():
    index = _index(periods=1)
    weather = _weather(index=index, ghi=[0.0], dni=[0.0], dhi=[0.0])
    solar = _solar(index, zenith=[60.0])

    report = run_solar_aware_weather_qc(weather, solar)

    assert "WX_SOLAR_DAYLIGHT_WITH_NEAR_ZERO_GHI" in _rules(report)
    assert report["status"] == "warning"
    assert report["base_simulation_input_ready"] is True


def test_diffuse_ratio_uses_bsrn_geometry_bands():
    index = _index(periods=1)
    weather = _weather(
        index=index,
        ghi=[100.0],
        dni=[0.0],
        dhi=[108.0],
    )
    solar = _solar(index, zenith=[60.0])

    report = run_solar_aware_weather_qc(weather, solar)

    assert "WX_SOLAR_DIFFUSE_RATIO_INCONSISTENT" in _rules(report)


def test_clear_sky_screen_is_opt_in_and_warning_only():
    index = _index(periods=1)
    zenith = 30.0
    dni = 900.0
    dhi = 220.0
    ghi = dhi + dni * math.cos(math.radians(zenith))
    weather = _weather(index=index, ghi=[ghi], dni=[dni], dhi=[dhi])
    solar = _solar(index, zenith=[zenith])

    no_reference = run_solar_aware_weather_qc(weather, solar)
    assert "WX_SOLAR_CLEAR_SKY_GROSS_EXCEEDANCE" not in _rules(no_reference)

    clear_sky = pd.DataFrame(
        {
            "ghi_w_m2": [500.0],
            "dni_w_m2": [500.0],
            "dhi_w_m2": [100.0],
        },
        index=index,
    )
    report = run_solar_aware_weather_qc(
        weather,
        solar,
        clear_sky_reference=clear_sky,
    )
    finding = next(
        item
        for item in report["findings"]
        if item["rule_id"] == "WX_SOLAR_CLEAR_SKY_GROSS_EXCEEDANCE"
        and item["variable"] == "ghi_w_m2"
    )

    assert report["status"] == "warning"
    assert finding["context"]["clear_sky_reference_generated_by_qc"] is False
    assert finding["context"]["screen_type"] == (
        "RawiBumi_warning_only_gross_exceedance"
    )


def test_missing_dni_dhi_preserves_phase2_completion_warning_and_solar_checks_skip_sum():
    index = _index(periods=1)
    weather = _weather(index=index, ghi=[500.0], dni=False, dhi=False)
    solar = _solar(index, zenith=[40.0])

    report = run_solar_aware_weather_qc(weather, solar)

    assert "WX_IRRADIANCE_DECOMPOSITION_REQUIRED" in _rules(report)
    assert "WX_SOLAR_COMPONENT_SUM_INCONSISTENT" not in _rules(report)
    assert report["status"] == "warning"
    assert report["base_simulation_input_ready"] is True


def test_solar_aware_qc_requires_exact_interval_alignment():
    index = _index(periods=2)
    weather = _weather(
        index=index,
        ghi=[350.0, 656.2],
        dni=[500.0, 700.0],
        dhi=[100.0, 120.0],
    )
    shifted = index + pd.Timedelta(minutes=1)
    solar = _solar(shifted, zenith=[60.0, 40.0])

    with pytest.raises(ValueError, match="align exactly"):
        run_solar_aware_weather_qc(weather, solar)


def test_attach_solar_aware_qc_updates_copy_only():
    index = _index(periods=1)
    weather = _weather(index=index, ghi=[0.0], dni=[0.0], dhi=[0.0])
    solar = _solar(index, zenith=[60.0])

    attached, report = attach_solar_aware_weather_qc(weather, solar)

    assert weather.dataset["data_quality_status"] == "not_run"
    assert attached.dataset["data_quality_status"] == "warning"
    assert attached.dataset["qc_summary"]["solar_aware"] is True
    assert attached.dataset["qc_summary"]["solar_aware_policy_id"] == (
        SOLAR_AWARE_QC_POLICY_ID
    )
    assert report["status"] == "warning"


def test_policy_validation_rejects_invalid_bands():
    with pytest.raises(ValueError, match="zenith thresholds"):
        SolarAwareQCPolicy(
            component_sum_low_zenith_deg=95.0,
            component_sum_high_zenith_deg=93.0,
        )


def test_real_solar_position_adapter_integrates_with_solar_aware_qc():
    index = pd.date_range(
        "2026-03-21T10:00:00+07:00",
        periods=3,
        freq="h",
    )
    seed = _weather(
        index=index,
        ghi=[100.0, 100.0, 100.0],
        dni=[0.0, 0.0, 0.0],
        dhi=[100.0, 100.0, 100.0],
    )
    solar = solar_position_from_weather(seed)
    zenith = solar.frame["solar_zenith_deg"].to_numpy(dtype=float)

    dni = np.array([500.0, 600.0, 550.0])
    dhi = np.array([120.0, 130.0, 125.0])
    ghi = dhi + dni * np.maximum(np.cos(np.radians(zenith)), 0.0)
    weather = _weather(index=index, ghi=ghi, dni=dni, dhi=dhi)

    solar = solar_position_from_weather(weather)
    report = run_solar_aware_weather_qc(weather, solar)

    assert report["status"] == "passed"
    assert report["findings"] == []
