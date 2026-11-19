import math

import numpy as np
import pandas as pd
import pytest

from engine.irradiance import (
    DECOMPOSITION_DIRINT,
    DECOMPOSITION_DISC,
    DECOMPOSITION_ERBS,
    POA_HAYDAVIES,
    POA_ISOTROPIC,
    POA_PEREZ,
    POA_PEREZ_DRIESSE,
    IrradianceCompletionResult,
    calculate_poa,
    complete_irradiance,
)
from engine.solar import SolarPositionResult
from weather.core import build_time_semantics, build_weather_dataset


def _index(periods=3, resolution_seconds=3600):
    return pd.date_range(
        "2026-03-21T10:00:00+07:00",
        periods=periods,
        freq=pd.Timedelta(seconds=resolution_seconds),
    )


def _weather(frame, resolution_seconds=3600):
    semantics = build_time_semantics(
        canonical_timezone="UTC+07:00",
        source_timestamp_convention="interval_start",
        native_interval_seconds=resolution_seconds,
        current_interval_seconds=resolution_seconds,
        source_timezone="UTC+07:00",
        source_utc_offset_hours=7.0,
    )
    return build_weather_dataset(
        frame,
        weather_dataset_id="wx-irradiance-test",
        revision_id="wx-irradiance-test-r1",
        name="Irradiance engine test",
        site_id="site-irradiance-test",
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


def _solar(index, zenith, azimuth=180.0):
    zenith_values = np.broadcast_to(np.asarray(zenith, dtype=float), len(index))
    azimuth_values = np.broadcast_to(np.asarray(azimuth, dtype=float), len(index))
    frame = pd.DataFrame(index=index)
    frame["evaluation_time"] = index + pd.Timedelta(minutes=30)
    frame["solar_apparent_zenith_deg"] = zenith_values
    frame["solar_zenith_deg"] = zenith_values
    frame["solar_apparent_elevation_deg"] = 90.0 - zenith_values
    frame["solar_elevation_deg"] = 90.0 - zenith_values
    frame["solar_azimuth_deg"] = azimuth_values
    frame["equation_of_time_minutes"] = 0.0
    return SolarPositionResult(
        frame=frame,
        metadata={
            "model_id": "synthetic_test",
            "azimuth_convention": "0_north_90_east_180_south_270_west",
        },
    )


def _completed(index, ghi, dni, dhi):
    frame = pd.DataFrame(
        {
            "ghi_w_m2": np.broadcast_to(np.asarray(ghi, dtype=float), len(index)),
            "dni_w_m2": np.broadcast_to(np.asarray(dni, dtype=float), len(index)),
            "dhi_w_m2": np.broadcast_to(np.asarray(dhi, dtype=float), len(index)),
            "dni_completion_method": "source",
            "dhi_completion_method": "source",
        },
        index=index,
    )
    return IrradianceCompletionResult(frame=frame, metadata={})


def test_completion_derives_single_missing_components_and_protects_low_sun():
    index = _index()
    frame = pd.DataFrame(
        {
            "ghi_w_m2": [500.0, 500.0, 500.0],
            "dni_w_m2": [600.0, np.nan, np.nan],
            "dhi_w_m2": [np.nan, 200.0, np.nan],
            "ambient_temperature_c": [30.0, 30.0, 30.0],
        },
        index=index,
    )
    weather = _weather(frame)
    solar = _solar(index, [60.0, 60.0, 89.0])

    result = complete_irradiance(weather, solar)

    assert result.frame.iloc[0]["dhi_w_m2"] == pytest.approx(200.0, abs=1e-9)
    assert result.frame.iloc[0]["dni_w_m2"] == 600.0
    assert result.frame.iloc[0]["dhi_completion_method"] == "horizontal_identity"

    assert result.frame.iloc[1]["dni_w_m2"] == pytest.approx(600.0, abs=1e-9)
    assert result.frame.iloc[1]["dhi_w_m2"] == 200.0
    assert result.frame.iloc[1]["dni_completion_method"] == "horizontal_identity"

    assert result.frame.iloc[2]["dni_w_m2"] == 0.0
    assert result.frame.iloc[2]["dhi_w_m2"] == 500.0
    assert result.frame.iloc[2]["dni_completion_method"] == "low_sun_zero_direct"
    assert result.frame.iloc[2]["dhi_completion_method"] == "low_sun_diffuse_only"

    assert result.metadata["decomposition_model_used"] is False
    assert result.metadata["analytical_dni_intervals"] == 1
    assert result.metadata["analytical_dhi_intervals"] == 1
    assert result.metadata["low_sun_dni_intervals"] == 1
    assert result.metadata["low_sun_dhi_intervals"] == 1


def test_completion_requires_explicit_model_when_both_components_missing_in_daylight():
    index = _index(periods=3)
    frame = pd.DataFrame(
        {
            "ghi_w_m2": [400.0, 700.0, 500.0],
            "ambient_temperature_c": [30.0, 30.0, 30.0],
        },
        index=index,
    )
    weather = _weather(frame)
    solar = _solar(index, [55.0, 35.0, 50.0])

    with pytest.raises(ValueError, match="select an explicit decomposition_model_id"):
        complete_irradiance(weather, solar)


@pytest.mark.parametrize(
    "model_id",
    [
        DECOMPOSITION_ERBS,
        DECOMPOSITION_DISC,
        DECOMPOSITION_DIRINT,
    ],
)
def test_explicit_decomposition_models_fill_daytime_components(model_id):
    index = _index(periods=5)
    frame = pd.DataFrame(
        {
            "ghi_w_m2": [150.0, 400.0, 700.0, 650.0, 250.0],
            "ambient_temperature_c": [28.0] * 5,
            "pressure_pa": [100500.0] * 5,
            "dew_point_temperature_c": [22.0] * 5,
        },
        index=index,
    )
    weather = _weather(frame)
    solar = _solar(index, [75.0, 55.0, 30.0, 35.0, 65.0])

    result = complete_irradiance(
        weather,
        solar,
        decomposition_model_id=model_id,
    )

    assert np.isfinite(result.frame["dni_w_m2"]).all()
    assert np.isfinite(result.frame["dhi_w_m2"]).all()
    assert (result.frame["dni_w_m2"] >= 0).all()
    assert (result.frame["dhi_w_m2"] >= 0).all()
    assert result.metadata["decomposition_model_used"] is True
    assert result.metadata["modeled_dni_intervals"] == 5
    assert result.metadata["modeled_dhi_intervals"] == 5


def test_completion_never_overwrites_valid_source_components():
    index = _index(periods=3)
    frame = pd.DataFrame(
        {
            "ghi_w_m2": [500.0, 600.0, 700.0],
            "dni_w_m2": [612.345, np.nan, np.nan],
            "dhi_w_m2": [193.210, np.nan, np.nan],
            "ambient_temperature_c": [30.0] * 3,
        },
        index=index,
    )
    weather = _weather(frame)
    solar = _solar(index, [50.0, 45.0, 40.0])

    result = complete_irradiance(
        weather,
        solar,
        decomposition_model_id=DECOMPOSITION_ERBS,
    )

    assert result.frame.iloc[0]["dni_w_m2"] == 612.345
    assert result.frame.iloc[0]["dhi_w_m2"] == 193.210
    assert result.frame.iloc[0]["dni_completion_method"] == "source"
    assert result.frame.iloc[0]["dhi_completion_method"] == "source"


def test_completion_rejects_materially_inconsistent_analytical_dhi():
    index = _index(periods=1)
    frame = pd.DataFrame(
        {
            "ghi_w_m2": [100.0],
            "dni_w_m2": [1000.0],
        },
        index=index,
    )
    weather = _weather(frame)
    solar = _solar(index, [30.0])

    with pytest.raises(ValueError, match="materially negative"):
        complete_irradiance(weather, solar)


def test_horizontal_plane_poa_reproduces_ghi_for_isotropic_model():
    index = _index(periods=1)
    zenith = 40.0
    dni = 600.0
    dhi = 150.0
    ghi = dni * math.cos(math.radians(zenith)) + dhi

    completed = _completed(index, [ghi], [dni], [dhi])
    solar = _solar(index, [zenith], [160.0])

    result = calculate_poa(
        completed,
        solar,
        surface_tilt_deg=0.0,
        surface_azimuth_deg=180.0,
        albedo=0.2,
        model_id=POA_ISOTROPIC,
    )

    row = result.frame.iloc[0]
    assert row["poa_global_w_m2"] == pytest.approx(ghi, abs=1e-9)
    assert row["poa_ground_diffuse_w_m2"] == pytest.approx(0.0, abs=1e-12)
    assert row["poa_sky_diffuse_w_m2"] == pytest.approx(dhi, abs=1e-9)


def test_direct_beam_is_dni_when_sun_is_normal_to_surface():
    index = _index(periods=1)
    zenith = 30.0
    dni = 800.0
    ghi = dni * math.cos(math.radians(zenith))
    completed = _completed(index, [ghi], [dni], [0.0])
    solar = _solar(index, [zenith], [180.0])

    result = calculate_poa(
        completed,
        solar,
        surface_tilt_deg=30.0,
        surface_azimuth_deg=180.0,
        albedo=0.0,
        model_id=POA_ISOTROPIC,
    )

    row = result.frame.iloc[0]
    assert row["aoi_deg"] == pytest.approx(0.0, abs=1e-8)
    assert row["poa_beam_w_m2"] == pytest.approx(800.0, abs=1e-8)
    assert row["poa_global_w_m2"] == pytest.approx(800.0, abs=1e-8)


def test_isotropic_diffuse_and_ground_terms_match_closed_form():
    index = _index(periods=1)
    completed = _completed(index, [100.0], [0.0], [100.0])
    solar = _solar(index, [60.0], [180.0])

    result = calculate_poa(
        completed,
        solar,
        surface_tilt_deg=60.0,
        surface_azimuth_deg=180.0,
        albedo=0.20,
        model_id=POA_ISOTROPIC,
    )

    row = result.frame.iloc[0]
    expected_sky = 100.0 * (1.0 + math.cos(math.radians(60.0))) / 2.0
    expected_ground = (
        100.0
        * 0.20
        * (1.0 - math.cos(math.radians(60.0)))
        / 2.0
    )
    assert row["poa_sky_diffuse_w_m2"] == pytest.approx(expected_sky, abs=1e-9)
    assert row["poa_ground_diffuse_w_m2"] == pytest.approx(
        expected_ground, abs=1e-9
    )
    assert row["poa_global_w_m2"] == pytest.approx(
        expected_sky + expected_ground,
        abs=1e-9,
    )


@pytest.mark.parametrize(
    "model_id",
    [
        POA_HAYDAVIES,
        POA_PEREZ,
        POA_PEREZ_DRIESSE,
    ],
)
def test_anisotropic_models_expose_reconciled_sky_subcomponents(model_id):
    index = _index(periods=3)
    completed = _completed(
        index,
        [650.0, 750.0, 550.0],
        [600.0, 700.0, 500.0],
        [150.0, 140.0, 160.0],
    )
    solar = _solar(index, [45.0, 30.0, 55.0], [150.0, 180.0, 210.0])

    result = calculate_poa(
        completed,
        solar,
        surface_tilt_deg=20.0,
        surface_azimuth_deg=180.0,
        albedo=0.20,
        model_id=model_id,
    )

    sky_parts = (
        result.frame["poa_isotropic_w_m2"]
        + result.frame["poa_circumsolar_w_m2"]
        + result.frame["poa_horizon_w_m2"]
    )
    assert np.allclose(
        sky_parts,
        result.frame["poa_sky_diffuse_w_m2"],
        atol=1e-7,
        rtol=0.0,
    )
    assert result.metadata["sky_subcomponents_exposed"] is True
    assert result.metadata["unshaded"] is True


def test_poa_rejects_invalid_canonical_surface_azimuth():
    index = _index(periods=1)
    completed = _completed(index, [500.0], [600.0], [100.0])
    solar = _solar(index, [45.0], [180.0])

    with pytest.raises(ValueError, match="0<=azimuth<360"):
        calculate_poa(
            completed,
            solar,
            surface_tilt_deg=20.0,
            surface_azimuth_deg=360.0,
            model_id=POA_ISOTROPIC,
        )
