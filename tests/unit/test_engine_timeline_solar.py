from pathlib import Path

import pandas as pd
import pytest
import yaml

from engine.solar import (
    SOLAR_POSITION_NREL_SPA,
    calculate_solar_position,
    solar_position_from_weather,
)
from engine.timeline import build_simulation_timeline
from weather.core import build_time_semantics, build_weather_dataset


ROOT = Path(__file__).resolve().parents[2]


def _weather(
    *,
    start: str = "2026-01-01T12:00:00+07:00",
    periods: int = 3,
    resolution_seconds: int = 3600,
    solar_offset_minutes: float = 0.0,
    latitude_deg: float = -6.425,
    longitude_deg: float = 106.831,
    elevation_m: float = 93.0,
):
    index = pd.date_range(
        pd.Timestamp(start),
        periods=periods,
        freq=pd.Timedelta(seconds=resolution_seconds),
    )
    series = pd.DataFrame(
        {
            "ghi_w_m2": [500.0] * periods,
            "dni_w_m2": [600.0] * periods,
            "dhi_w_m2": [100.0] * periods,
            "ambient_temperature_c": [30.0] * periods,
            "pressure_pa": [100500.0] * periods,
        },
        index=index,
    )
    semantics = build_time_semantics(
        canonical_timezone="UTC+07:00",
        source_timestamp_convention="interval_start",
        native_interval_seconds=resolution_seconds,
        current_interval_seconds=resolution_seconds,
        source_timezone="UTC+07:00",
        source_utc_offset_hours=7.0,
        solar_evaluation_offset_minutes=solar_offset_minutes,
        solar_evaluation_offset_source=(
            "test_offset" if solar_offset_minutes else "none"
        ),
    )
    return build_weather_dataset(
        series,
        weather_dataset_id="wx-engine-test",
        revision_id="wx-engine-test-r1",
        name="Engine test weather",
        site_id="site-engine-test",
        timezone="UTC+07:00",
        native_resolution_seconds=resolution_seconds,
        source_format="synthetic_test",
        source_timestamp_convention="interval_start",
        location={
            "latitude_deg": latitude_deg,
            "longitude_deg": longitude_deg,
            "elevation_m": elevation_m,
        },
        time_semantics=semantics,
    )


def test_timeline_uses_interval_start_end_midpoint_and_duration():
    weather = _weather(resolution_seconds=3600)
    timeline = build_simulation_timeline(weather)
    row = timeline.frame.iloc[0]

    assert timeline.frame.index[0] == pd.Timestamp("2026-01-01T12:00:00+07:00")
    assert row["interval_end"] == pd.Timestamp("2026-01-01T13:00:00+07:00")
    assert row["interval_midpoint"] == pd.Timestamp("2026-01-01T12:30:00+07:00")
    assert row["evaluation_time"] == pd.Timestamp("2026-01-01T12:30:00+07:00")
    assert row["duration_seconds"] == 3600
    assert timeline.metadata["representative_time_policy"] == "interval_midpoint"
    assert timeline.metadata["solar_evaluation_offset_minutes"] == 0.0


def test_timeline_applies_only_explicit_solar_evaluation_offset():
    weather = _weather(
        start="2026-01-01T12:00:00+07:00",
        periods=2,
        resolution_seconds=600,
        solar_offset_minutes=5.0,
    )
    timeline = build_simulation_timeline(weather)

    assert timeline.frame.iloc[0]["interval_midpoint"] == pd.Timestamp(
        "2026-01-01T12:05:00+07:00"
    )
    assert timeline.frame.iloc[0]["evaluation_time"] == pd.Timestamp(
        "2026-01-01T12:10:00+07:00"
    )
    assert timeline.metadata["solar_evaluation_offset_source"] == "test_offset"


def test_timeline_does_not_resample_implicitly():
    weather = _weather(resolution_seconds=3600)

    with pytest.raises(ValueError, match="explicitly resample weather"):
        build_simulation_timeline(
            weather,
            simulation_timestep_seconds=300,
        )


def test_timeline_rejects_weather_cadence_mismatch():
    weather = _weather(resolution_seconds=3600)
    weather.series = weather.series.drop(weather.series.index[1])

    with pytest.raises(ValueError, match="cadence"):
        build_simulation_timeline(weather)


def test_nrel_spa_published_reference_case():
    reference = yaml.safe_load(
        (ROOT / "tests/benchmarks/solar_position_nrel_spa.yaml").read_text(
            encoding="utf-8"
        )
    )
    inputs = reference["inputs"]
    expected = reference["expected"]
    tolerances = reference["tolerances"]

    evaluation_time = pd.Timestamp(inputs["local_time"])
    interval_start = evaluation_time - pd.Timedelta(seconds=30)
    weather = _weather(
        start=interval_start.isoformat(),
        periods=1,
        resolution_seconds=60,
        latitude_deg=inputs["latitude_deg"],
        longitude_deg=inputs["longitude_deg"],
        elevation_m=inputs["elevation_m"],
    )
    timeline = build_simulation_timeline(weather)

    result = calculate_solar_position(
        timeline,
        latitude_deg=inputs["latitude_deg"],
        longitude_deg=inputs["longitude_deg"],
        elevation_m=inputs["elevation_m"],
        pressure_pa=inputs["pressure_pa"],
        temperature_c=inputs["temperature_c"],
        delta_t_seconds=inputs["delta_t_seconds"],
        atmos_refract_deg=inputs["atmos_refract_deg"],
    )

    row = result.frame.iloc[0]
    assert row["evaluation_time"] == evaluation_time
    assert row["solar_apparent_zenith_deg"] == pytest.approx(
        expected["apparent_zenith_deg"],
        abs=tolerances["angle_abs_deg"],
    )
    assert row["solar_azimuth_deg"] == pytest.approx(
        expected["azimuth_deg"],
        abs=tolerances["angle_abs_deg"],
    )
    assert row["equation_of_time_minutes"] == pytest.approx(
        expected["equation_of_time_minutes"],
        abs=tolerances["equation_of_time_abs_minutes"],
    )
    assert row["solar_apparent_elevation_deg"] == pytest.approx(
        90.0 - row["solar_apparent_zenith_deg"],
        abs=1e-10,
    )
    assert result.metadata["model_id"] == SOLAR_POSITION_NREL_SPA
    assert result.metadata["algorithm_family"] == "NREL_SPA"
    assert result.metadata["azimuth_convention"] == (
        "0_north_90_east_180_south_270_west"
    )
    assert result.metadata["delta_t_seconds"] == 67.0
    assert result.metadata["execution_backend"] == "numpy"
    assert result.metadata["numthreads"] == 1


def test_solar_position_from_weather_uses_canonical_met_inputs():
    weather = _weather(periods=2, resolution_seconds=900)
    timeline = build_simulation_timeline(weather)
    result = solar_position_from_weather(
        weather,
        timeline=timeline,
        delta_t_seconds=67.0,
    )

    assert list(result.frame.index) == list(weather.series.index)
    assert result.frame["solar_azimuth_deg"].between(
        0.0, 360.0, inclusive="left"
    ).all()
    assert result.metadata["pressure_source"] == "canonical_weather.pressure_pa"
    assert result.metadata["temperature_source"] == (
        "canonical_weather.ambient_temperature_c"
    )
    assert result.metadata["solar_evaluation_offset_minutes"] == 0.0


def test_solar_position_falls_back_to_elevation_pressure_when_pressure_missing():
    weather = _weather(periods=1)
    weather.series = weather.series.drop(columns=["pressure_pa"])

    result = solar_position_from_weather(weather, delta_t_seconds=67.0)

    assert result.metadata["pressure_source"] == (
        "standard_atmosphere_from_elevation"
    )


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (91.0, 0.0),
        (-91.0, 0.0),
        (0.0, 181.0),
        (0.0, -181.0),
    ],
)
def test_solar_position_rejects_invalid_coordinates(latitude, longitude):
    timeline = build_simulation_timeline(_weather(periods=1))

    with pytest.raises(ValueError):
        calculate_solar_position(
            timeline,
            latitude_deg=latitude,
            longitude_deg=longitude,
        )
