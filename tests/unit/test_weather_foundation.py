import json
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft202012Validator

from weather.core import CanonicalWeather, interval_energy_wh_m2
from weather.csv import (
    read_opensimpv_weather_csv_bytes,
    write_opensimpv_weather_csv,
)
from weather.disaggregation import resample_weather
from weather.epw import read_epw_weather_bytes
from weather.importer import detect_weather_format, read_weather_bytes
from weather.meteonorm import read_meteonorm_dat_bytes
from weather.pvsyst import (
    probe_pvsyst_weather_bytes,
    read_pvsyst_standard_weather_bytes,
)
from weather.tmy3 import read_tmy3_weather_bytes
from weather.validation import attach_weather_qc, run_weather_qc


ROOT = Path(__file__).resolve().parents[2]


def _bytes(relative: str) -> bytes:
    return (ROOT / relative).read_bytes()


def _native():
    return read_opensimpv_weather_csv_bytes(
        _bytes("tests/fixtures/weather/opensimpv_hourly.csv"),
        weather_dataset_id="wx-native-001",
        revision_id="wx-native-001-r1",
        name="Native fixture",
        site_id="site-weather-001",
        filename="opensimpv_hourly.csv",
        source_id="src-native-weather",
    )


def _synthetic_tmy3_year_bytes(year: int) -> bytes:
    """Build a redistributable hourly TMY3-style actual-year fixture."""
    header = (
        "999999,Synthetic Actual Year,NA,7.0,-6.2,106.8,20\n"
        "Date (MM/DD/YYYY),Time (HH:MM),GHI (W/m^2),DNI (W/m^2),"
        "DHI (W/m^2),Dry-bulb (C),Pressure (mbar),Wspd (m/s),"
        "RHum (%),Alb (unitless),Pwat (cm),Dew-point (C)\n"
    )
    starts = pd.date_range(
        start=pd.Timestamp(year=year, month=1, day=1, hour=1),
        end=pd.Timestamp(year=year + 1, month=1, day=1, hour=0),
        freq="h",
    )
    rows = []
    for timestamp in starts:
        if timestamp.hour == 0:
            source_date = timestamp - pd.Timedelta(days=1)
            source_time = "24:00"
        else:
            source_date = timestamp
            source_time = f"{timestamp.hour:02d}:00"
        rows.append(
            f"{source_date:%m/%d/%Y},{source_time},100,120,40,"
            "25.0,1008,1.2,82,0.20,4.1,21.7"
        )
    return (header + "\n".join(rows) + "\n").encode("utf-8")


def _mixed_year_tmy3_bytes() -> bytes:
    """Build a small conventional mixed-source-year TMY transition."""
    return """999999,Synthetic Typical Year,NA,7.0,-6.2,106.8,20
Date (MM/DD/YYYY),Time (HH:MM),GHI (W/m^2),DNI (W/m^2),DHI (W/m^2),Dry-bulb (C)
02/28/1996,23:00,100,120,40,25.0
02/28/1996,24:00,100,120,40,25.0
03/01/1990,01:00,100,120,40,25.0
03/01/1990,02:00,100,120,40,25.0
""".encode("utf-8")


def _synthetic_pvsyst_text_met() -> bytes:
    return b"""PVObject_=pvMeteo
  Version=8.1.3
  NomSite=Synthetic Site
  PasAccum=60
  PVObject_MeteoVar=pvMeteoVar
    NomVar=GlobHor
    Day_0101=+0+0+0+ABC
  End of PVObject pvMeteoVar
End of PVObject pvMeteo
"""


def _synthetic_meteonorm_dat(resolution_minutes: int) -> bytes:
    """Build one redistributable Meteonorm-style day at a selected cadence."""
    if 60 % resolution_minutes != 0:
        raise ValueError("test cadence must divide one hour")

    header = (
        "Synthetic Meteonorm Site\n"
        "0.359 [deg N], 102.089 [deg E], 22 [m], 7 [timezone h], "
        "-30 [time ref. min]\n"
        "m\tdm\tdy\th\tmi\tG_Gh\ths\tG_Gex\tG_Gh_hr\tG_Dh\t"
        "G_Gk\tG_Dk\tG_Bn\tTa\tFF\tG_Gcs\tTd\tPVprod\n"
    )
    source_date = pd.Timestamp("2001-12-31")
    rows = []
    end = source_date + pd.Timedelta(minutes=resolution_minutes)
    final_end = source_date + pd.Timedelta(days=1)
    while end <= final_end:
        interval_start = end - pd.Timedelta(minutes=resolution_minutes)
        hour = int(interval_start.hour)
        ghi = 100 + 10 * hour
        dhi = 20 + 2 * hour
        dni = 50 + 5 * hour
        temp = 25.0 + 0.1 * hour
        wind = 1.0 + 0.01 * hour
        dew = 20.0 + 0.05 * hour

        if end == final_end:
            source_hour = 24
            source_minute = 0
        else:
            source_hour = int(end.hour)
            source_minute = int(end.minute)

        rows.append(
            "\t".join(
                [
                    "12",
                    "31",
                    "365",
                    str(source_hour),
                    str(source_minute),
                    str(ghi),
                    "0",
                    "0",
                    str(ghi),
                    str(dhi),
                    "0",
                    "0",
                    str(dni),
                    f"{temp:.3f}",
                    f"{wind:.3f}",
                    "0",
                    f"{dew:.3f}",
                    "0",
                ]
            )
        )
        end += pd.Timedelta(minutes=resolution_minutes)

    return (header + "\n".join(rows) + "\n").encode("utf-8")


def _validate_weather_dataset(weather: CanonicalWeather):
    schema = json.loads(
        (ROOT / "weather/schema/weather-dataset.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(weather.dataset)


def test_native_csv_import_preserves_interval_semantics_and_provenance():
    weather = _native()

    assert weather.dataset["source_format"] == "opensimpv_csv_v0.1"
    assert weather.dataset["native_resolution_seconds"] == 3600
    assert weather.dataset["series_resolution_seconds"] == 3600
    assert weather.dataset["native_series_origin"] == "unknown"
    assert weather.dataset["series_origin"] == "unknown"
    assert weather.dataset["upstream_generation"] is None
    assert weather.dataset["timestamp_convention"] == "interval_start"
    assert weather.dataset["timezone"] == "Asia/Jakarta"
    assert weather.dataset["time_semantics"]["canonical"] == {
        "timezone": "Asia/Jakarta",
        "timestamp_convention": "interval_start",
        "interval_seconds": 3600,
    }
    assert weather.dataset["time_semantics"]["origin_source"]["timestamp_convention"] == (
        "interval_start"
    )
    assert weather.dataset["time_semantics"]["representative_time"] == {
        "policy": "interval_midpoint",
        "solar_evaluation_offset_minutes": 0.0,
        "solar_evaluation_offset_source": "none",
    }
    assert weather.dataset["start_time"] == "2026-01-01T00:00:00+07:00"
    assert weather.dataset["end_time"] == "2026-01-01T04:00:00+07:00"
    assert len(weather.dataset["source_files"][0]["sha256"]) == 64
    assert weather.dataset["source_files"][0]["byte_size"] == len(
        _bytes("tests/fixtures/weather/opensimpv_hourly.csv")
    )
    assert weather.series.index[0] == pd.Timestamp(
        "2026-01-01T00:00:00+07:00"
    )
    assert interval_energy_wh_m2(weather) == pytest.approx(700.0)
    _validate_weather_dataset(weather)


def test_native_csv_export_round_trip_keeps_series_values_and_time():
    source = _native()
    exported = write_opensimpv_weather_csv(source)
    imported = read_opensimpv_weather_csv_bytes(
        exported.encode("utf-8"),
        weather_dataset_id="wx-roundtrip-001",
        revision_id="wx-roundtrip-001-r1",
        name="Round trip",
        site_id="site-weather-001",
        filename="roundtrip.csv",
        source_id="src-roundtrip",
    )

    pd.testing.assert_index_equal(imported.series.index, source.series.index)
    pd.testing.assert_frame_equal(
        imported.series,
        source.series,
        check_dtype=False,
    )
    assert interval_energy_wh_m2(imported) == pytest.approx(
        interval_energy_wh_m2(source)
    )
    assert imported.dataset["time_semantics"] == source.dataset["time_semantics"]


def test_tmy3_import_normalizes_end_labels_to_interval_start():
    weather = read_tmy3_weather_bytes(
        _bytes("tests/fixtures/weather/tmy3_minimal.csv"),
        weather_dataset_id="wx-tmy3-001",
        revision_id="wx-tmy3-001-r1",
        name="TMY3 fixture",
        site_id="site-weather-001",
        filename="tmy3_minimal.csv",
        source_id="src-tmy3",
    )

    assert weather.dataset["source_format"] == "tmy3"
    assert weather.dataset["source_timestamp_convention"] == "interval_end"
    assert weather.dataset["source_metadata"]["calendar_classification"] == (
        "partial_time_series"
    )
    time_semantics = weather.dataset["time_semantics"]
    assert time_semantics["origin_source"]["timezone"] == "UTC+07:00"
    assert time_semantics["origin_source"]["utc_offset_hours"] == pytest.approx(7.0)
    assert time_semantics["origin_source"]["timestamp_convention"] == "interval_end"
    assert time_semantics["origin_source"]["interval_seconds"] == 3600
    assert time_semantics["origin_source"]["reference"] == {
        "kind": "none",
        "offset_minutes": None,
        "applied_to_canonical_timestamp": False,
        "applied_to_solar_evaluation": False,
    }
    assert time_semantics["representative_time"]["solar_evaluation_offset_minutes"] == 0.0
    assert weather.series.index[0] == pd.Timestamp(
        "1990-01-01T00:00:00+07:00"
    )
    assert weather.series.iloc[0]["pressure_pa"] == pytest.approx(100800.0)
    assert weather.series.iloc[0]["relative_humidity_fraction"] == pytest.approx(
        0.82
    )
    assert weather.series.iloc[0]["precipitable_water_mm"] == pytest.approx(41.0)
    assert interval_energy_wh_m2(weather) == pytest.approx(700.0)
    assert any(
        item["algorithm"] == "tmy3_interval_end_to_interval_start"
        for item in weather.dataset["transformations"]
    )
    _validate_weather_dataset(weather)


def test_tmy3_actual_leap_year_preserves_feb29_and_24_hour_boundaries():
    weather = read_tmy3_weather_bytes(
        _synthetic_tmy3_year_bytes(2020),
        weather_dataset_id="wx-tmy3-leap-2020",
        revision_id="wx-tmy3-leap-2020-r1",
        name="Synthetic actual leap year",
        site_id="site-weather-001",
        filename="actual_2020.csv",
        source_id="src-tmy3-leap",
    )

    assert len(weather.series) == 8784
    assert weather.series.index.is_monotonic_increasing
    assert not weather.series.index.has_duplicates
    assert pd.Timestamp("2020-02-29T00:00:00+07:00") in weather.series.index
    assert weather.series.index[0] == pd.Timestamp(
        "2020-01-01T00:00:00+07:00"
    )
    assert weather.series.index[-1] == pd.Timestamp(
        "2020-12-31T23:00:00+07:00"
    )
    assert weather.dataset["start_time"] == "2020-01-01T00:00:00+07:00"
    assert weather.dataset["end_time"] == "2021-01-01T00:00:00+07:00"
    assert weather.dataset["calendar_type"] == "gregorian"
    assert weather.dataset["leap_year_handling"] == "source_preserved"
    assert weather.dataset["source_metadata"]["calendar_classification"] == (
        "actual_year"
    )
    assert weather.dataset["source_metadata"]["source_years"] == [2020]
    assert weather.dataset["source_metadata"]["calendar_anchor_year"] is None

    report = run_weather_qc(weather)
    assert report["status"] == "passed"
    assert report["base_simulation_input_ready"] is True
    _validate_weather_dataset(weather)


def test_tmy3_mixed_source_years_normalize_to_typical_year_anchor():
    weather = read_tmy3_weather_bytes(
        _mixed_year_tmy3_bytes(),
        weather_dataset_id="wx-tmy3-typical",
        revision_id="wx-tmy3-typical-r1",
        name="Synthetic typical year",
        site_id="site-weather-001",
        filename="typical_mixed_years.csv",
        source_id="src-tmy3-typical",
    )

    assert weather.series.index.is_monotonic_increasing
    assert not weather.series.index.has_duplicates
    assert list(weather.series.index) == [
        pd.Timestamp("2001-02-28T22:00:00+07:00"),
        pd.Timestamp("2001-02-28T23:00:00+07:00"),
        pd.Timestamp("2001-03-01T00:00:00+07:00"),
        pd.Timestamp("2001-03-01T01:00:00+07:00"),
    ]
    assert weather.dataset["calendar_type"] == "typical_year"
    assert weather.dataset["leap_year_handling"] == (
        "tmy3_typical_year_normalized"
    )
    assert weather.dataset["source_metadata"]["calendar_classification"] == (
        "typical_year"
    )
    assert weather.dataset["source_metadata"]["source_years"] == [1990, 1996]
    assert weather.dataset["source_metadata"]["calendar_anchor_year"] == 2001
    _validate_weather_dataset(weather)


@pytest.mark.parametrize(
    ("resolution_minutes", "expected_rows"),
    [(60, 24), (15, 96), (10, 144), (1, 1440)],
)
def test_meteonorm_dat_import_infers_resolution_and_normalizes_interval_end(
    resolution_minutes,
    expected_rows,
):
    data = _synthetic_meteonorm_dat(resolution_minutes)
    weather = read_meteonorm_dat_bytes(
        data,
        weather_dataset_id=f"wx-mn-{resolution_minutes}",
        revision_id=f"wx-mn-{resolution_minutes}-r1",
        name="Synthetic Meteonorm",
        site_id="site-weather-001",
        filename=f"synthetic-{resolution_minutes}min.dat",
        source_id="src-meteonorm",
    )

    assert len(weather.series) == expected_rows
    assert weather.dataset["source_format"] == "meteonorm_dat"
    assert weather.dataset["source_timestamp_convention"] == "interval_end"
    assert weather.dataset["native_resolution_seconds"] == resolution_minutes * 60
    assert weather.dataset["series_resolution_seconds"] == resolution_minutes * 60
    if resolution_minutes < 60:
        assert weather.dataset["native_series_origin"] == "provider_generated"
        assert weather.dataset["series_origin"] == "provider_generated"
        assert weather.dataset["upstream_generation"] == {
            "provider": "Meteonorm",
            "synthetic": True,
            "base_resolution_seconds": 3600,
            "method": "meteonorm_provider_subhourly_generation",
            "evidence": "source_structure",
            "evidence_detail": (
                "Subhourly G_Gh series is accompanied by G_Gh_hr hourly-reference "
                "values in the source DAT structure."
            ),
        }
    else:
        assert weather.dataset["native_series_origin"] == "unknown"
        assert weather.dataset["series_origin"] == "unknown"
        assert weather.dataset["upstream_generation"] is None
    assert weather.dataset["timezone"] == "UTC+07:00"
    assert weather.dataset["calendar_type"] == "typical_year"
    assert weather.dataset["source_metadata"]["calendar_anchor_year"] == 2001
    assert weather.dataset["source_metadata"]["calendar_classification"] == (
        "yearless_partial_series"
    )
    assert weather.dataset["source_metadata"]["source_time_reference_minutes"] == (
        -30.0
    )
    time_semantics = weather.dataset["time_semantics"]
    assert time_semantics["origin_source"]["timestamp_convention"] == "interval_end"
    assert time_semantics["origin_source"]["interval_seconds"] == resolution_minutes * 60
    assert time_semantics["origin_source"]["reference"] == {
        "kind": "provider_declared_time_reference",
        "offset_minutes": -30.0,
        "applied_to_canonical_timestamp": False,
        "applied_to_solar_evaluation": False,
    }
    assert time_semantics["representative_time"] == {
        "policy": "interval_midpoint",
        "solar_evaluation_offset_minutes": 0.0,
        "solar_evaluation_offset_source": "none",
    }
    assert weather.series.index[0] == pd.Timestamp(
        "2001-12-31T00:00:00+07:00"
    )
    assert weather.dataset["end_time"] == "2002-01-01T00:00:00+07:00"
    assert weather.series.index.is_monotonic_increasing
    assert not weather.series.index.has_duplicates
    assert weather.series.iloc[0]["ghi_w_m2"] == pytest.approx(100.0)
    assert weather.series.iloc[0]["dhi_w_m2"] == pytest.approx(20.0)
    assert weather.series.iloc[0]["dni_w_m2"] == pytest.approx(50.0)
    assert weather.series.iloc[0]["ambient_temperature_c"] == pytest.approx(25.0)
    assert weather.dataset["transformations"][0]["parameters"][
        "source_time_reference_applied_to_timestamp"
    ] is False

    report = run_weather_qc(weather)
    assert report["status"] == "passed"
    assert report["base_simulation_input_ready"] is True
    _validate_weather_dataset(weather)


def test_meteonorm_dat_autodetection_and_unified_dispatch():
    data = _synthetic_meteonorm_dat(15)
    assert detect_weather_format(data, filename="weather.dat") == "meteonorm_dat"

    weather = read_weather_bytes(
        data,
        weather_dataset_id="wx-mn-dispatch",
        revision_id="wx-mn-dispatch-r1",
        name="Meteonorm dispatch",
        site_id="site-weather-001",
        filename="weather.dat",
        source_id="src-meteonorm",
    )
    assert weather.dataset["source_format"] == "meteonorm_dat"
    assert weather.dataset["native_resolution_seconds"] == 900


def test_meteonorm_cross_resolution_series_agree_after_aggregation():
    minute = read_meteonorm_dat_bytes(
        _synthetic_meteonorm_dat(1),
        weather_dataset_id="wx-mn-1",
        revision_id="wx-mn-1-r1",
        name="Meteonorm 1 minute",
        site_id="site-weather-001",
        filename="synthetic-1min.dat",
    )

    for resolution_minutes in (10, 15, 60):
        direct = read_meteonorm_dat_bytes(
            _synthetic_meteonorm_dat(resolution_minutes),
            weather_dataset_id=f"wx-mn-{resolution_minutes}",
            revision_id=f"wx-mn-{resolution_minutes}-r1",
            name=f"Meteonorm {resolution_minutes} minute",
            site_id="site-weather-001",
            filename=f"synthetic-{resolution_minutes}min.dat",
        )
        aggregated = resample_weather(
            minute,
            target_resolution_seconds=resolution_minutes * 60,
        )
        pd.testing.assert_index_equal(aggregated.series.index, direct.series.index)
        pd.testing.assert_frame_equal(
            aggregated.series,
            direct.series,
            check_dtype=False,
            atol=1e-12,
            rtol=0,
        )
        assert interval_energy_wh_m2(aggregated) == pytest.approx(
            interval_energy_wh_m2(direct),
            abs=1e-12,
        )
        assert aggregated.dataset["native_series_origin"] == "provider_generated"
        assert aggregated.dataset["series_origin"] == "opensimpv_derived"
        assert aggregated.dataset["upstream_generation"] == minute.dataset[
            "upstream_generation"
        ]
        assert aggregated.dataset["transformations"][-1]["parameters"][
            "input_series_origin"
        ] == "provider_generated"
        assert aggregated.dataset["transformations"][-1]["parameters"][
            "output_series_origin"
        ] == "opensimpv_derived"


def test_meteonorm_temporal_provenance_survives_native_csv_round_trip():
    source = read_meteonorm_dat_bytes(
        _synthetic_meteonorm_dat(1),
        weather_dataset_id="wx-mn-provenance",
        revision_id="wx-mn-provenance-r1",
        name="Meteonorm provenance",
        site_id="site-weather-001",
        filename="synthetic-1min.dat",
    )
    exported = write_opensimpv_weather_csv(source)
    imported = read_opensimpv_weather_csv_bytes(
        exported.encode("utf-8"),
        weather_dataset_id="wx-mn-provenance-roundtrip",
        revision_id="wx-mn-provenance-roundtrip-r1",
        name="Meteonorm provenance round trip",
        site_id="site-weather-001",
        filename="roundtrip.csv",
    )

    assert imported.dataset["native_series_origin"] == "provider_generated"
    assert imported.dataset["series_origin"] == "provider_generated"
    assert imported.dataset["upstream_generation"] == source.dataset[
        "upstream_generation"
    ]
    assert imported.dataset["time_semantics"] == source.dataset["time_semantics"]
    _validate_weather_dataset(imported)


def test_meteonorm_signed_coordinate_is_not_flipped_by_hemisphere_token():
    text = _synthetic_meteonorm_dat(60).decode("utf-8")
    text = text.replace(
        "0.359 [deg N], 102.089 [deg E]",
        "-6.425 [deg N], 106.831 [deg E]",
        1,
    )
    weather = read_meteonorm_dat_bytes(
        text.encode("utf-8"),
        weather_dataset_id="wx-mn-signed-coordinate",
        revision_id="wx-mn-signed-coordinate-r1",
        name="Signed Meteonorm coordinate",
        site_id="site-weather-001",
        filename="signed.dat",
    )

    assert weather.dataset["location"]["latitude_deg"] == pytest.approx(-6.425)
    assert weather.dataset["location"]["longitude_deg"] == pytest.approx(106.831)


def test_meteonorm_day_of_year_mismatch_is_rejected():
    text = _synthetic_meteonorm_dat(60).decode("utf-8")
    bad = text.replace("12\t31\t365\t1\t0", "12\t31\t364\t1\t0", 1)
    with pytest.raises(ValueError, match="day-of-year"):
        read_meteonorm_dat_bytes(
            bad.encode("utf-8"),
            weather_dataset_id="wx-mn-bad-dy",
            revision_id="wx-mn-bad-dy-r1",
            name="Bad Meteonorm day of year",
            site_id="site-weather-001",
            filename="bad.dat",
        )


def test_epw_import_normalizes_units_and_interval_start():
    weather = read_epw_weather_bytes(
        _bytes("tests/fixtures/weather/epw_minimal.epw"),
        weather_dataset_id="wx-epw-001",
        revision_id="wx-epw-001-r1",
        name="EPW fixture",
        site_id="site-weather-001",
        filename="epw_minimal.epw",
        source_id="src-epw",
    )

    assert weather.dataset["source_format"] == "epw"
    assert weather.dataset["time_semantics"]["origin_source"][
        "timestamp_convention"
    ] == "epw_hour_1_24_interval"
    assert weather.dataset["time_semantics"]["origin_source"][
        "utc_offset_hours"
    ] == pytest.approx(7.0)
    assert weather.dataset["time_semantics"]["representative_time"][
        "solar_evaluation_offset_minutes"
    ] == 0.0
    assert weather.series.index[0] == pd.Timestamp(
        "2026-01-01T00:00:00+07:00"
    )
    assert weather.series.iloc[0]["pressure_pa"] == pytest.approx(100800.0)
    assert weather.series.iloc[0]["relative_humidity_fraction"] == pytest.approx(
        0.82
    )
    assert weather.series.iloc[0]["precipitable_water_mm"] == pytest.approx(41.0)
    assert interval_energy_wh_m2(weather) == pytest.approx(700.0)
    _validate_weather_dataset(weather)


def test_pvsyst_standard_weather_import_uses_documented_interval_start_convention():
    weather = read_pvsyst_standard_weather_bytes(
        _bytes("tests/fixtures/weather/pvsyst_standard_hourly.csv"),
        weather_dataset_id="wx-pvsyst-001",
        revision_id="wx-pvsyst-001-r1",
        name="PVsyst standard fixture",
        site_id="site-weather-001",
        filename="pvsyst_standard_hourly.csv",
        source_id="src-pvsyst-standard",
    )

    assert weather.dataset["source_format"] == "pvsyst_standard_weather_csv"
    assert weather.series.index[0] == pd.Timestamp(
        "2026-01-01T00:00:00+07:00"
    )
    assert weather.dataset["location"]["latitude_deg"] == pytest.approx(-6.2)
    assert weather.series.iloc[1]["ghi_w_m2"] == pytest.approx(100.0)
    assert weather.series.iloc[1]["relative_humidity_fraction"] == pytest.approx(
        0.80
    )
    assert weather.series.iloc[1]["precipitable_water_mm"] == pytest.approx(40.0)
    assert interval_energy_wh_m2(weather) == pytest.approx(700.0)
    _validate_weather_dataset(weather)


def test_pvsyst_declared_time_shift_is_split_into_timestamp_and_solar_remainder():
    text = """#Weather data hourly data
#Site;Shift Test
#Country;Indonesia
#Data Source;Synthetic
#Time step;10 min
#Year;2026
#Latitude;-6.2
#Longitude;106.8
#Altitude;20
#Time Zone;7
#Time Shift;25
Year;Month;Day;Hour;Minute;GHI;Tamb
-;-;-;-;-;W/m2;deg.C
2026;1;1;12;0;500;30
2026;1;1;12;10;500;30
2026;1;1;12;20;500;30
"""
    weather = read_pvsyst_standard_weather_bytes(
        text.encode("utf-8"),
        weather_dataset_id="wx-shift-001",
        revision_id="wx-shift-001-r1",
        name="PVsyst shift fixture",
        site_id="site-weather-001",
        filename="shift.csv",
    )

    assert weather.series.index[0] == pd.Timestamp(
        "2026-01-01T12:20:00+07:00"
    )
    assert weather.dataset["source_metadata"]["solar_time_shift_minutes"] == pytest.approx(
        5.0
    )
    time_semantics = weather.dataset["time_semantics"]
    assert time_semantics["origin_source"]["timestamp_convention"] == "interval_start"
    assert time_semantics["origin_source"]["timezone"] == "UTC+07:00"
    assert time_semantics["canonical"]["timezone"] == "UTC+07:00"
    assert time_semantics["canonical"]["interval_seconds"] == 600
    assert time_semantics["representative_time"] == {
        "policy": "interval_midpoint",
        "solar_evaluation_offset_minutes": 5.0,
        "solar_evaluation_offset_source": "pvsyst_declared_time_shift_remainder",
    }
    shift = [
        item
        for item in weather.dataset["transformations"]
        if item["algorithm"] == "pvsyst_declared_time_shift_v8_1"
    ][0]
    assert shift["parameters"]["timestamp_shift_seconds"] == 1200


def test_pvsyst_source_time_reference_is_separate_from_solar_remainder():
    text = """#Weather data hourly data
#Site;Reference Test
#Country;Indonesia
#Data Source;Synthetic
#Time step;60 min
#Year;2026
#Latitude;-6.2
#Longitude;106.8
#Altitude;20
#Time Zone;7
#Time reference;UT
Year;Month;Day;Hour;Minute;GHI;Tamb
-;-;-;-;-;W/m2;deg.C
2026;1;1;5;0;500;30
2026;1;1;6;0;500;30
"""
    weather = read_pvsyst_standard_weather_bytes(
        text.encode("utf-8"),
        weather_dataset_id="wx-reference-001",
        revision_id="wx-reference-001-r1",
        name="PVsyst reference fixture",
        site_id="site-weather-001",
        filename="reference.csv",
    )

    semantics = weather.dataset["time_semantics"]
    assert semantics["origin_source"]["timezone"] == "UTC+00:00"
    assert semantics["origin_source"]["utc_offset_hours"] == pytest.approx(0.0)
    assert semantics["canonical"]["timezone"] == "UTC+07:00"
    assert semantics["representative_time"]["solar_evaluation_offset_minutes"] == 0.0
    assert weather.series.index[0] == pd.Timestamp("2026-01-01T12:00:00+07:00")


def test_pvsyst_standard_probe_detects_documented_csv():
    data = _bytes("tests/fixtures/weather/pvsyst_standard_hourly.csv")
    probe = probe_pvsyst_weather_bytes(data, filename="weather.csv")

    assert probe["format_id"] == "pvsyst_standard_csv"
    assert probe["is_pvsyst_weather"] is True
    assert probe["import_supported"] is True
    assert probe["container"] == "text"
    assert probe["confidence"] == "high"
    assert probe["internal_object"] is None


def test_pvsyst_text_met_probe_is_structured_but_not_decoded():
    data = _synthetic_pvsyst_text_met()
    probe = probe_pvsyst_weather_bytes(data, filename="user_weather.MET")

    assert probe["format_id"] == "pvsyst_internal_met_text"
    assert probe["is_pvsyst_weather"] is True
    assert probe["import_supported"] is False
    assert probe["container"] == "text"
    assert probe["confidence"] == "high"
    assert probe["internal_object"]["object_type"] == "pvMeteo"
    assert probe["internal_object"]["version"] == "8.1.3"
    assert probe["internal_object"]["has_encoded_daily_payload"] is True
    assert probe["internal_object"]["encoded_day_record_count_in_probe_window"] == 1
    assert probe["internal_object"]["meteo_variable_object_count_in_probe_window"] == 1
    assert detect_weather_format(data, filename="user_weather.MET") == (
        "pvsyst_internal_met_text"
    )

    with pytest.raises(
        NotImplementedError,
        match=r"pvsyst_internal_met_text version=8\.1\.3",
    ):
        read_weather_bytes(
            data,
            weather_dataset_id="wx-internal-met-text",
            revision_id="wx-internal-met-text-r1",
            name="Internal text MET",
            site_id="site-weather-001",
            filename="user_weather.MET",
        )


def test_pvsyst_binary_met_probe_is_explicitly_unsupported():
    data = b"PVsyst\x00MET\x00\x01\x02\xffbinary-payload"
    probe = probe_pvsyst_weather_bytes(data, filename="database.MET")

    assert probe["format_id"] == "pvsyst_internal_met_binary"
    assert probe["is_pvsyst_weather"] is True
    assert probe["import_supported"] is False
    assert probe["container"] == "binary"
    assert probe["confidence"] == "medium"
    assert probe["internal_object"] is None
    assert detect_weather_format(data, filename="database.MET") == (
        "pvsyst_internal_met_binary"
    )

    with pytest.raises(NotImplementedError, match="pvsyst_internal_met_binary"):
        read_weather_bytes(
            data,
            weather_dataset_id="wx-internal-met-binary",
            revision_id="wx-internal-met-binary-r1",
            name="Internal binary MET",
            site_id="site-weather-001",
            filename="database.MET",
        )


def test_pvsyst_unrecognized_met_is_not_silently_guessed():
    data = b"This is a text file with a MET extension but no recognized PVsyst header.\n"
    probe = probe_pvsyst_weather_bytes(data, filename="unknown.MET")

    assert probe["format_id"] == "pvsyst_met_unrecognized"
    assert probe["is_pvsyst_weather"] is True
    assert probe["import_supported"] is False
    assert probe["confidence"] == "low"

    with pytest.raises(NotImplementedError, match="pvsyst_met_unrecognized"):
        read_weather_bytes(
            data,
            weather_dataset_id="wx-unrecognized-met",
            revision_id="wx-unrecognized-met-r1",
            name="Unrecognized MET",
            site_id="site-weather-001",
            filename="unknown.MET",
        )


def test_pvsyst_shd_pvobject_is_not_misclassified_as_weather():
    data = b"PVObject_=pvShading\n  Version=8.0.21\nEnd of PVObject pvShading\n"
    probe = probe_pvsyst_weather_bytes(data, filename="scene.SHD")

    assert probe["is_pvsyst_weather"] is False
    assert probe["format_id"] is None

    with pytest.raises(ValueError, match="unable to detect weather format"):
        detect_weather_format(data, filename="scene.SHD")


def test_pvsyst_standard_parser_rejects_internal_met_directly():
    with pytest.raises(ValueError, match="not a documented PVsyst Standard"):
        read_pvsyst_standard_weather_bytes(
            _synthetic_pvsyst_text_met(),
            weather_dataset_id="wx-internal-met",
            revision_id="wx-internal-met-r1",
            name="Internal MET",
            site_id="site-weather-001",
            filename="internal.MET",
        )


def test_weather_qc_passes_clean_complete_fixture_and_schema_validates():
    weather, report = attach_weather_qc(_native())

    assert report["status"] == "passed"
    assert report["base_simulation_input_ready"] is True
    assert report["finding_counts"]["error"] == 0
    assert weather.dataset["data_quality_status"] == "passed"

    schema = json.loads(
        (ROOT / "weather/schema/weather-qc-report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(report)
    _validate_weather_dataset(weather)


def test_weather_qc_allows_missing_dni_dhi_with_explicit_decomposition_warning():
    weather = _native().copy()
    weather.series = weather.series.drop(columns=["dni_w_m2", "dhi_w_m2"])
    report = run_weather_qc(weather)

    assert report["status"] == "warning"
    assert report["base_simulation_input_ready"] is True

    completion = [
        item
        for item in report["findings"]
        if item["rule_id"] == "WX_IRRADIANCE_DECOMPOSITION_REQUIRED"
    ]
    assert len(completion) == 1
    completion = completion[0]

    assert completion["count"] == len(weather.series)
    assert completion["context"]["completion_scope"] == "full_ghi_available_series"
    assert completion["context"]["ghi_available_intervals"] == len(weather.series)
    assert completion["context"]["intervals_requiring_completion"] == len(
        weather.series
    )
    assert completion["context"]["missing_components"] == [
        "dni_w_m2",
        "dhi_w_m2",
    ]
    for variable in ("dni_w_m2", "dhi_w_m2"):
        component = completion["context"]["components"][variable]
        assert component["availability"] == "absent"
        assert component["column_present"] is False
        assert component["missing_count"] == len(weather.series)
        assert component["completion_count"] == len(weather.series)
        assert component["completion_fraction_of_ghi_available"] == pytest.approx(
            1.0
        )

    assert not any(
        item["rule_id"] == "WX_OPTIONAL_VARIABLE_MISSING_VALUES"
        and item["variable"] in {"dni_w_m2", "dhi_w_m2"}
        for item in report["findings"]
    )


def test_weather_qc_detects_partial_dni_dhi_as_interval_completion_need():
    weather = _native().copy()
    dni_gap = weather.series.index[1]
    dhi_gap = weather.series.index[2]
    weather.series.loc[dni_gap, "dni_w_m2"] = float("nan")
    weather.series.loc[dhi_gap, "dhi_w_m2"] = float("nan")

    report = run_weather_qc(weather)
    completion = [
        item
        for item in report["findings"]
        if item["rule_id"] == "WX_IRRADIANCE_DECOMPOSITION_REQUIRED"
    ][0]

    assert report["status"] == "warning"
    assert report["base_simulation_input_ready"] is True
    assert completion["count"] == 2
    assert completion["context"]["completion_scope"] == "partial_intervals"
    assert completion["context"]["intervals_requiring_completion"] == 2
    assert completion["context"]["missing_components"] == [
        "dni_w_m2",
        "dhi_w_m2",
    ]
    assert completion["examples"] == [
        pd.Timestamp(dni_gap).isoformat(),
        pd.Timestamp(dhi_gap).isoformat(),
    ]

    dni = completion["context"]["components"]["dni_w_m2"]
    dhi = completion["context"]["components"]["dhi_w_m2"]
    assert dni["availability"] == "partial"
    assert dni["missing_count"] == 1
    assert dni["completion_count"] == 1
    assert dni["examples"] == [pd.Timestamp(dni_gap).isoformat()]
    assert dhi["availability"] == "partial"
    assert dhi["missing_count"] == 1
    assert dhi["completion_count"] == 1
    assert dhi["examples"] == [pd.Timestamp(dhi_gap).isoformat()]

    assert not any(
        item["rule_id"] == "WX_OPTIONAL_VARIABLE_MISSING_VALUES"
        and item["variable"] in {"dni_w_m2", "dhi_w_m2"}
        for item in report["findings"]
    )


def test_weather_qc_completion_excludes_intervals_without_ghi():
    weather = _native().copy()
    unusable_gap = weather.series.index[1]
    completion_gap = weather.series.index[2]
    weather.series.loc[unusable_gap, "ghi_w_m2"] = float("nan")
    weather.series.loc[unusable_gap, "dni_w_m2"] = float("nan")
    weather.series.loc[completion_gap, "dhi_w_m2"] = float("nan")

    report = run_weather_qc(weather)
    completion = [
        item
        for item in report["findings"]
        if item["rule_id"] == "WX_IRRADIANCE_DECOMPOSITION_REQUIRED"
    ][0]

    assert report["status"] == "failed"
    assert report["base_simulation_input_ready"] is False
    assert completion["context"]["ghi_available_intervals"] == len(weather.series) - 1
    assert completion["context"]["intervals_requiring_completion"] == 1
    assert completion["count"] == 1
    assert completion["examples"] == [pd.Timestamp(completion_gap).isoformat()]
    assert completion["context"]["components"]["dni_w_m2"]["missing_count"] == 1
    assert completion["context"]["components"]["dni_w_m2"]["completion_count"] == 0
    assert completion["context"]["components"]["dhi_w_m2"]["missing_count"] == 1
    assert completion["context"]["components"]["dhi_w_m2"]["completion_count"] == 1


def test_weather_qc_detects_gap_negative_irradiance_and_invalid_fraction():
    weather = _native().copy()
    weather.series = weather.series.drop(weather.series.index[1])
    weather.series.loc[weather.series.index[0], "ghi_w_m2"] = -10
    weather.series.loc[weather.series.index[0], "albedo"] = 1.5

    report = run_weather_qc(weather)
    rules = {item["rule_id"] for item in report["findings"]}

    assert report["status"] == "failed"
    assert report["base_simulation_input_ready"] is False
    assert "WX_TIME_GAPS" in rules
    assert "WX_NEGATIVE_IRRADIANCE" in rules
    assert "WX_FRACTION_OUT_OF_RANGE" in rules


def test_hourly_to_five_minute_disaggregation_preserves_irradiance_energy():
    source = _native()
    result = resample_weather(source, target_resolution_seconds=300)

    assert len(result.series) == len(source.series) * 12
    assert result.dataset["native_resolution_seconds"] == 3600
    assert result.dataset["series_resolution_seconds"] == 300
    assert result.dataset["derived_subhourly"] is True
    assert result.dataset["native_series_origin"] == "unknown"
    assert result.dataset["series_origin"] == "opensimpv_derived"
    assert result.dataset["time_semantics"]["origin_source"]["interval_seconds"] == 3600
    assert result.dataset["time_semantics"]["canonical"]["interval_seconds"] == 300
    assert result.dataset["transformations"][-1]["parameters"][
        "input_series_origin"
    ] == "unknown"
    assert result.dataset["transformations"][-1]["parameters"][
        "output_series_origin"
    ] == "opensimpv_derived"
    assert result.series.iloc[0]["ghi_w_m2"] == pytest.approx(0.0)
    assert result.series.iloc[12]["ghi_w_m2"] == pytest.approx(100.0)
    assert interval_energy_wh_m2(result) == pytest.approx(
        interval_energy_wh_m2(source),
        abs=1e-12,
    )
    transform = result.dataset["transformations"][-1]
    assert transform["algorithm"] == "interval_mean_hold"
    assert transform["parameters"]["synthetic_subinterval"] is True
    assert transform["parameters"]["energy_preservation_check"]["ghi_w_m2"][
        "relative_error"
    ] <= 1e-12


def test_subhourly_back_to_hourly_preserves_energy_and_values():
    source = _native()
    subhourly = resample_weather(source, target_resolution_seconds=300)
    hourly = resample_weather(subhourly, target_resolution_seconds=3600)

    pd.testing.assert_index_equal(hourly.series.index, source.series.index)
    pd.testing.assert_frame_equal(
        hourly.series,
        source.series,
        check_dtype=False,
    )
    assert interval_energy_wh_m2(hourly) == pytest.approx(700.0)
    assert hourly.dataset["native_series_origin"] == "unknown"
    assert hourly.dataset["series_origin"] == "opensimpv_derived"


def test_non_integer_resolution_conversion_is_rejected():
    with pytest.raises(ValueError, match="divide source resolution"):
        resample_weather(_native(), target_resolution_seconds=700)
