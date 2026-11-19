"""S10: exact local weather windows; all provider data here is fictional."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
import pandas as pd
import pytest

from tests.unit.test_rb_fix_s2_honest_preflight import Project
from apps.api.server import create_app
from weather.core import build_weather_dataset
from weather.providers.base import WeatherAcquisitionRequest
from weather.providers.open_meteo import OpenMeteoHistoricalAdapter
from weather.providers.snapshot_store import FileSystemWeatherSnapshotStore
from weather.validation.qc import run_weather_qc


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/weather"


def request(start="2025-01-01", end=None, zone="Asia/Jakarta"):
    return WeatherAcquisitionRequest(
        source_id="open_meteo_archive_era5", latitude_deg=-6.2,
        longitude_deg=106.8, timezone=zone, start_date=start,
        end_date=end or start, elevation_m=25,
    )


def payload(start="2024-12-31T00:00Z", hours=72):
    """Fictional zero solar/constant states; never inferred observations."""
    value = deepcopy(json.loads((FIXTURES / "open_meteo_era5_phase60d_uat.json").read_bytes()))
    index = pd.date_range(start, periods=hours, freq="h")
    constants = dict(temperature_2m=25., relative_humidity_2m=70.,
        dew_point_2m=20., surface_pressure=1000., wind_speed_10m=1.,
        shortwave_radiation=0., direct_normal_irradiance=0., diffuse_radiation=0.)
    value["hourly"] = {"time": [int(t.timestamp()) for t in index],
                       **{key: [v] * hours for key, v in constants.items()}}
    value["_opensimpv_fixture_note"] = "Entirely fictional S10 test data; not ERA5 or interpolation."
    return value


def parse(value, req=None, **kwargs):
    raw = json.dumps(value).encode()
    return OpenMeteoHistoricalAdapter().parse_response(
        raw, request=req or request(), weather_dataset_id="s10-weather",
        revision_id="s10-weather-r1", name="Fictional S10 weather", site_id="s10-site",
        synthetic=True, **kwargs,
    )


def trim_record(result):
    return next(t for t in result.weather.dataset["transformations"]
                if t["algorithm"] == "local_window_trim")


def test_01_padding_clamp_and_transport_url_preserve_local_request(monkeypatch):
    adapter = OpenMeteoHistoricalAdapter()
    req = request("2023-01-01", "2023-12-31")
    parameters = adapter.build_request_parameters(req)
    assert parameters["start_date"] == "2022-12-31"
    assert parameters["end_date"] == "2024-01-01"
    assert parameters["timezone"] == "GMT"
    assert req.start_date == "2023-01-01" and req.end_date == "2023-12-31"

    # Freeze UTC today independently of the workstation's local timezone.
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return cls(2026, 10, 31, 0, 30, tzinfo=timezone.utc)

    monkeypatch.setattr("weather.providers.open_meteo.datetime", Clock)
    recent = request("2026-10-30")
    assert adapter.build_request_parameters(recent)["end_date"] == "2026-10-31"
    assert adapter.build_request_parameters(replace(recent, end_date="2026-10-31"))["end_date"] == "2026-10-31"
    assert recent.end_date == "2026-10-30"

    raw = json.dumps(payload()).encode()
    urls = []
    monkeypatch.setattr(adapter, "_get_bytes", lambda url, **kw: urls.append(url) or raw)
    result = adapter.acquire(request(), weather_dataset_id="s10", revision_id="s10-r1",
        name="Mock transport", site_id="s10-site")
    query = parse_qs(urlparse(urls[0]).query)
    assert query["start_date"] == ["2024-12-31"]
    assert query["end_date"] == ["2025-01-02"]
    assert result.manifest["raw_response"]["source_url"] == urls[0]
    assert result.weather.dataset["source_metadata"]["request_url"] == urls[0]
    assert result.manifest["request"]["start_time"] == "2025-01-01T00:00:00+07:00"
    assert result.manifest["request"]["end_time"] == "2025-01-02T00:00:00+07:00"


def test_transport_crossing_utc_midnight_keeps_the_actual_padded_dates(monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 10, 30, 23, 59, 59, tzinfo=timezone.utc)
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return cls.current

    monkeypatch.setattr("weather.providers.open_meteo.datetime", Clock)
    adapter = OpenMeteoHistoricalAdapter()
    sent = []
    raw = json.dumps(payload("2026-10-29T00:00Z", 48)).encode()
    def transport(url, **kwargs):
        sent.append(url)
        Clock.current = datetime(2026, 10, 31, 0, 0, 1, tzinfo=timezone.utc)
        return raw
    monkeypatch.setattr(adapter, "_get_bytes", transport)
    result = adapter.acquire(request("2026-10-30"), weather_dataset_id="s10-midnight",
        revision_id="s10-midnight-r1", name="Fictional midnight transport", site_id="s10-site")
    assert parse_qs(urlparse(sent[0]).query)["end_date"] == ["2026-10-30"]
    assert result.manifest["request"]["parameters"]["end_date"] == "2026-10-30"
    assert trim_record(result)["parameters"]["fetched_utc_dates"] == {
        "start_date": "2026-10-29", "end_date": "2026-10-30"}
    assert result.manifest["raw_response"]["source_url"] == sent[0]
    assert len(result.weather.series) == 24


@pytest.mark.parametrize("zone,day,expected_hours", [
    ("Asia/Jakarta", "2025-01-01", 24),
    ("America/New_York", "2023-03-12", 23),
    ("America/New_York", "2023-11-05", 25),
    ("Etc/GMT+12", "2025-01-01", 24),
    ("Pacific/Kiritimati", "2025-01-01", 24),
    ("Asia/Kolkata", "2025-01-01", 24),
    ("Asia/Kathmandu", "2025-01-01", 24),
])
def test_02_03_local_day_and_independent_source_value_mapping(zone, day, expected_hours):
    utc_day_before = date.fromisoformat(day) - timedelta(days=1)
    value = payload(utc_day_before.isoformat() + "T00:00Z")
    # Distinct benign values make a wrong slice or extra one-hour shift visible.
    for i in range(72):
        value["hourly"]["temperature_2m"][i] = 20. + i / 10
        value["hourly"]["shortwave_radiation"][i] = float(i)
        value["hourly"]["direct_normal_irradiance"][i] = float(i + 10)
        value["hourly"]["diffuse_radiation"][i] = float(i) / 2
        value["hourly"]["wind_speed_10m"][i] = 1. + i / 100
    result = parse(value, request(day, zone=zone))
    data = result.weather.series
    local_start = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(zone))
    local_end = datetime.combine(date.fromisoformat(day) + timedelta(days=1),
                                 datetime.min.time(), tzinfo=ZoneInfo(zone))
    # Enumerate physical hours between independently constructed local bounds.
    expected_utc = []
    current = local_start.astimezone(timezone.utc)
    # Provider labels are UTC whole hours, including when local clocks are not.
    if current.minute:
        current = current.replace(minute=0) + timedelta(hours=1)
    while current < local_end.astimezone(timezone.utc):
        expected_utc.append(current)
        current += timedelta(hours=1)
    assert len(data) == len(expected_utc) == expected_hours
    assert list(data.index.tz_convert("UTC").to_pydatetime()) == expected_utc
    assert not data.index.has_duplicates
    assert data.index[0].hour == 0 and data.index[-1].hour == 23
    if day == "2023-03-12":
        assert 2 not in data.index.hour
    fields = {"ghi_w_m2": ("shortwave_radiation", 1),
              "dni_w_m2": ("direct_normal_irradiance", 1),
              "dhi_w_m2": ("diffuse_radiation", 1),
              "ambient_temperature_c": ("temperature_2m", 1),
              "relative_humidity_fraction": ("relative_humidity_2m", .01),
              "dew_point_temperature_c": ("dew_point_2m", 1),
              "pressure_pa": ("surface_pressure", 100),
              "wind_speed_m_s": ("wind_speed_10m", 1)}
    for utc, (_, row) in zip(expected_utc, data.iterrows()):
        source_label = int((utc + timedelta(hours=1)).timestamp())
        source_row = value["hourly"]["time"].index(source_label)
        for canonical, (source, factor) in fields.items():
            assert row[canonical] == pytest.approx(value["hourly"][source][source_row] * factor)
    assert result.weather.dataset["start_time"] == local_start.isoformat()
    assert result.weather.dataset["end_time"] == local_end.isoformat()
    assert not [f for f in result.qc_report["findings"] if f["rule_id"] == "WX_TIME_GAPS"]


def test_04_full_local_year_real_api_simulation_has_twelve_months(tmp_path):
    project = Project(tmp_path, weather=False)
    raw = json.dumps(payload("2022-12-31T00:00Z", 8760 + 48)).encode()
    project.study.acquire_weather(project.pid, source_id="open_meteo_archive_era5",
        start_date="2023-01-01", end_date="2023-12-31", raw_response=raw)
    selection = project.bundle()["weather_selection"]
    weather = project.study.weather.load(project.pid, selection["revision_id"])
    assert len(weather.series) == 8760
    assert weather.series.index[0].isoformat() == "2023-01-01T00:00:00+07:00"
    assert weather.series.index[-1].isoformat() == "2023-12-31T23:00:00+07:00"
    assert weather.dataset["qc_summary"]["status"] == "passed"
    response = project.client.post(project.url + "/simulate")
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] in {"completed", "completed_with_warnings"}, run["validation_findings"]
    months = run["summary_result"]["monthly_energy"]
    assert len(months) == 12
    assert [m["month"] for m in months] == [f"2023-{month:02d}" for month in range(1, 13)]
    assert project.study.runs(project.pid)[-1]["summary_result"]["monthly_energy"] == months


def test_05_missing_first_padded_day_is_retained_and_reported():
    # First available label is Jan 1 UTC: canonical first local start is 06:00.
    value = payload("2025-01-01T00:00Z", 48)
    result = parse(value)
    assert len(result.weather.series) == 18
    assert result.weather.series.index[0].isoformat() == "2025-01-01T06:00:00+07:00"
    assert result.qc_report["status"] == "failed"
    finding, = [f for f in result.qc_report["findings"] if f["rule_id"] == "WX_TIME_GAPS"]
    assert finding["severity"] == "error" and finding["count"] == 6
    assert finding["examples"] == [f"2025-01-01T{hour:02d}:00:00+07:00" for hour in range(5)]
    assert trim_record(result)["parameters"]["rows_after"] == 18


@pytest.mark.parametrize("leading,trailing", [(5, 0), (0, 7), (3, 4), (24, 0)])
def test_boundary_coverage_exact_counts_including_empty_retained_window(leading, trailing):
    value = payload()
    # A nonempty source wholly outside the window must return empty data + QC.
    start_label = int(pd.Timestamp("2024-12-31T18:00Z").timestamp())
    keep = [i for i, label in enumerate(value["hourly"]["time"])
            if start_label + leading * 3600 <= label < start_label + (24 - trailing) * 3600]
    if leading == 24:
        keep = list(range(4))
    for key, values in value["hourly"].items():
        value["hourly"][key] = [values[i] for i in keep]
    result = parse(value)
    assert len(result.weather.series) == 24 - leading - trailing
    finding, = [f for f in result.qc_report["findings"] if f["rule_id"] == "WX_TIME_GAPS"]
    assert finding["severity"] == "error"
    assert finding["count"] == leading + trailing
    assert finding["context"]["missing_boundary_intervals"] == leading + trailing
    missing = list(range(leading)) + list(range(24 - trailing, 24))
    assert finding["examples"] == [f"2025-01-01T{hour:02d}:00:00+07:00" for hour in missing[:5]]
    assert result.qc_report["base_simulation_input_ready"] is False
    assert result.manifest["status"] == "failed"
    assert result.weather.dataset["start_time"] == "2025-01-01T00:00:00+07:00"
    assert result.weather.dataset["end_time"] == "2025-01-02T00:00:00+07:00"


def test_non_s10_dataset_and_existing_internal_gap_rule_stay_unchanged():
    partial = parse(json.loads((FIXTURES / "open_meteo_era5_hourly.json").read_bytes())).weather
    partial.dataset["transformations"] = [t for t in partial.dataset["transformations"]
                                          if t["algorithm"] != "local_window_trim"]
    assert run_weather_qc(partial)["status"] == "passed"
    full = parse(payload()).weather
    full.series = full.series.drop(full.series.index[10])
    finding, = [f for f in run_weather_qc(full)["findings"] if f["rule_id"] == "WX_TIME_GAPS"]
    assert finding["count"] == 1
    assert finding["context"] == {"expected_resolution_seconds": 3600}


def test_06_provenance_raw_snapshot_schema_and_trim_counts(tmp_path):
    value = payload()
    raw = json.dumps(value).encode()
    result = parse(value, snapshot_store=FileSystemWeatherSnapshotStore(tmp_path / "snapshots"))
    digest = sha256(raw).hexdigest()
    assert result.raw_response == raw
    assert result.manifest["raw_response"]["sha256"] == digest
    assert (tmp_path / "snapshots/sha256" / digest[:2] / (digest + ".json")).read_bytes() == raw
    transform = trim_record(result)
    assert transform["transformation_type"] == "timezone_normalization"
    assert transform["algorithm_version"] == "0.1"
    assert transform["parameters"] == {
        "local_start": "2025-01-01T00:00:00+07:00",
        "local_end_exclusive": "2025-01-02T00:00:00+07:00",
        "requested_start_date": "2025-01-01", "requested_end_date": "2025-01-01",
        "fetched_utc_dates": {"start_date": "2024-12-31", "end_date": "2025-01-02"},
        "rows_before": 72, "rows_after": 24, "rows_dropped_start": 18, "rows_dropped_end": 30,
    }
    shift, = [t for t in result.weather.dataset["transformations"]
              if t["algorithm"] == "open_meteo_hour_label_to_canonical_interval_start"]
    assert shift["parameters"]["interval_shift_seconds"] == -3600
    assert shift["parameters"]["state_interpolation_applied"] is False
    assert result.weather.dataset["source_timestamp_convention"] == (
        "mixed_open_meteo_hourly_label:solar_preceding_hour_mean;state_instant_at_label")
    for filename, document in [("weather-dataset.schema.json", result.weather.dataset),
                               ("weather-source-acquisition-manifest.schema.json", result.manifest)]:
        schema = json.loads((ROOT / "weather/schema" / filename).read_bytes())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def test_explicit_period_is_optional_and_default_behavior_is_unchanged():
    series = parse(json.loads((FIXTURES / "open_meteo_era5_hourly.json").read_bytes())).weather.series
    kwargs = dict(weather_dataset_id="x", revision_id="r", name="Fictional weather",
        site_id="s", timezone="Asia/Jakarta", native_resolution_seconds=3600,
        source_format="test", source_timestamp_convention="interval_start")
    default = build_weather_dataset(series, **kwargs)
    assert default.dataset["start_time"] == "2025-01-01T10:00:00+07:00"
    assert default.dataset["end_time"] == "2025-01-01T14:00:00+07:00"
    pd.testing.assert_frame_equal(default.series, series)
    with pytest.raises(ValueError, match="at least one row"):
        build_weather_dataset(series.iloc[:0], **kwargs)
    with pytest.raises(ValueError, match="both start_time and end_time"):
        build_weather_dataset(series, **kwargs, start_time="2025-01-01T00:00:00+07:00")
    with pytest.raises(ValueError, match="ordered timezone-aware"):
        build_weather_dataset(series, **kwargs, start_time="2025-01-02T00:00:00+07:00",
                              end_time="2025-01-01T00:00:00+07:00")


def test_companions_preserve_original_rows_and_documented_hour_ranges():
    original = json.loads((FIXTURES / "open_meteo_era5_phase60d_uat.json").read_bytes())
    day = json.loads((FIXTURES / "open_meteo_era5_phase60d_uat_padded_s10.json").read_bytes())
    annual = json.loads((FIXTURES / "open_meteo_era5_annual_padded_s10.json").read_bytes())
    for companion, start, count in [(day, "2024-12-31T00:00Z", 72),
                                     (annual, "2024-12-30T00:00Z", 8832)]:
        expected = [int(t.timestamp()) for t in pd.date_range(start, periods=count, freq="h")]
        assert companion["hourly"]["time"] == expected
        assert all(len(v) == count for v in companion["hourly"].values())
    for i, label in enumerate(original["hourly"]["time"]):
        j = day["hourly"]["time"].index(label)
        for key, values in original["hourly"].items():
            assert day["hourly"][key][j] == values[i]


@pytest.mark.parametrize("zone,day,rows,start,end", [
    ("America/Havana", "2023-11-05", 25,
     "2023-11-05T00:00:00-04:00", "2023-11-06T00:00:00-05:00"),
    ("America/Sao_Paulo", "2018-11-04", 23,
     "2018-11-04T01:00:00-02:00", "2018-11-05T00:00:00-02:00"),
    ("Asia/Kathmandu", "1986-01-01", 24,
     "1986-01-01T00:15:00+05:45", "1986-01-02T00:00:00+05:45"),
])
def test_a6_first_real_instant_preserves_repeated_and_skipped_hours(zone, day, rows, start, end):
    before = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    value = payload(before + "T00:00Z")
    value["hourly"]["shortwave_radiation"] = list(range(72))
    result = parse(value, request(day, zone=zone))
    data = result.weather.series
    assert len(data) == rows
    assert result.weather.dataset["start_time"] == start
    assert result.weather.dataset["end_time"] == end
    assert result.qc_report["status"] == "passed"
    assert not data.index.has_duplicates
    if zone == "America/Havana":
        midnights = data.index[data.index.hour == 0]
        assert len(midnights) == 2
        assert [t.strftime("%z") for t in midnights] == ["-0400", "-0500"]
    if zone == "America/Sao_Paulo":
        assert data.index[0].hour == 1 and 0 not in data.index.hour
    for index, row in data.iterrows():
        label = int(index.tz_convert("UTC").timestamp()) + 3600
        original = value["hourly"]["time"].index(label)
        assert row["ghi_w_m2"] == value["hourly"]["shortwave_radiation"][original]


@pytest.mark.parametrize("zone,transition,rows", [
    ("America/Havana", "2023-11-05", 73),
    ("America/Sao_Paulo", "2018-11-04", 71),
])
def test_a6_consecutive_local_days_tile_across_midnight_transitions(zone, transition, rows):
    day = date.fromisoformat(transition)
    value = payload((day - timedelta(days=2)).isoformat() + "T00:00Z", 120)
    days = [day + timedelta(days=i) for i in (-1, 0, 1)]
    pieces = [parse(value, request(d.isoformat(), zone=zone)) for d in days]
    for left, right in zip(pieces, pieces[1:]):
        assert left.weather.dataset["end_time"] == right.weather.dataset["start_time"]
    together = pd.concat([piece.weather.series for piece in pieces])
    full = parse(value, request(days[0].isoformat(), days[-1].isoformat(), zone))
    pd.testing.assert_frame_equal(together, full.weather.series)
    assert len(together) == rows and not together.index.has_duplicates
    assert all(piece.qc_report["status"] == "passed" for piece in pieces)
    assert full.qc_report["status"] == "passed"


def test_a6_wholly_skipped_apia_date_is_422_before_any_provider_call(tmp_path, monkeypatch):
    app = create_app(store_root=tmp_path / "projects")
    client = TestClient(app)
    created = client.post("/api/projects", json={"name": "S10 Apia skipped date",
        "latitude_deg": -13.8, "longitude_deg": -171.75, "timezone": "Pacific/Apia"})
    assert created.status_code == 201, created.text
    pid = created.json()["bundle"]["project"]["project_id"]
    path = app.state.project_service.store.path_for(pid)
    before = path.read_bytes()
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError("wholly skipped local date must never reach provider transport")
    monkeypatch.setattr(app.state.study_service.open_meteo, "_get_bytes", forbidden)
    response = client.post(f"/api/projects/{pid}/weather/acquire", json={
        "source_id": "open_meteo_archive_era5", "start_date": "2011-12-30", "end_date": "2011-12-30"})
    assert response.status_code == 422, response.text
    assert "no real instants" in response.json()["detail"]
    assert calls == [] and path.read_bytes() == before


def test_a6_skipped_start_date_with_real_following_day_preserves_requested_dates():
    result = parse(payload("2011-12-29T00:00Z", 120),
                   request("2011-12-30", "2011-12-31", "Pacific/Apia"))
    assert len(result.weather.series) == 24
    assert result.weather.dataset["start_time"] == "2011-12-31T00:00:00+14:00"
    assert result.weather.dataset["end_time"] == "2012-01-01T00:00:00+14:00"
    assert trim_record(result)["parameters"]["requested_start_date"] == "2011-12-30"
    assert trim_record(result)["parameters"]["requested_end_date"] == "2011-12-31"
    assert result.qc_report["status"] == "passed"
