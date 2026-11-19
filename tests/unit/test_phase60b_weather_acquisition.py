import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from weather.providers import (
    FileSystemWeatherSnapshotStore,
    OpenMeteoHistoricalAdapter,
    WeatherAcquisitionError,
    WeatherAcquisitionRequest,
)


ROOT = Path(__file__).resolve().parents[2]


def _fixture_bytes() -> bytes:
    return (ROOT / "tests/fixtures/weather/open_meteo_era5_hourly.json").read_bytes()


def _request() -> WeatherAcquisitionRequest:
    return WeatherAcquisitionRequest(
        source_id="open_meteo_archive_era5",
        latitude_deg=-6.2,
        longitude_deg=106.8,
        elevation_m=25.0,
        timezone="Asia/Jakarta",
        start_date="2025-01-01",
        end_date="2025-01-01",
        cell_selection="land",
    )


def _parse(tmp_path: Path, *, synthetic: bool = True, **kwargs):
    adapter = OpenMeteoHistoricalAdapter()
    return adapter.parse_response(
        _fixture_bytes(),
        request=_request(),
        weather_dataset_id="wx-open-meteo-era5-001",
        revision_id="wx-open-meteo-era5-001-r1",
        name="Open-Meteo ERA5 fixture",
        site_id="site-weather-001",
        snapshot_store=FileSystemWeatherSnapshotStore(tmp_path / "snapshots"),
        requested_at="2026-09-25T02:00:00+00:00",
        synthetic=synthetic,
        **kwargs,
    )


def _validator(filename):
    schema = json.loads((ROOT / "weather/schema" / filename).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _assert_no_retrieval_claims(dataset, manifest):
    assert manifest["acquisition"]["method"] == "supplied_payload"
    assert manifest["acquisition"]["network_retrieval"] is False
    assert dataset["source_metadata"]["acquisition"] == manifest["acquisition"]
    assert dataset["native_series_origin"] == "unknown"
    assert dataset["series_origin"] == "unknown"
    assert dataset["source_metadata"]["request_url"] is None
    assert all(item["source_url"] is None for item in dataset["source_files"])
    assert manifest["raw_response"]["retrieved_at"] is None
    assert manifest["raw_response"]["source_url"] is None
    assert "acquired through" not in dataset["upstream_generation"]["evidence_detail"]
    assert manifest["status"] != "retrieved"
    _validator("weather-dataset.schema.json").validate(dataset)
    _validator("weather-source-acquisition-manifest.schema.json").validate(manifest)


def test_open_meteo_request_is_explicit_era5_and_never_best_match():
    adapter = OpenMeteoHistoricalAdapter()
    url = adapter.build_request_url(_request())
    query = parse_qs(urlparse(url).query)

    assert query["models"] == ["era5"]
    assert query["cell_selection"] == ["land"]
    assert query["timeformat"] == ["unixtime"]
    assert query["timezone"] == ["GMT"]
    assert query["wind_speed_unit"] == ["ms"]
    assert query["elevation"] == ["25"]
    assert "best_match" not in url
    assert "era5_seamless" not in url


def test_open_meteo_unknown_source_fails_closed_without_fallback():
    adapter = OpenMeteoHistoricalAdapter()
    request = WeatherAcquisitionRequest(
        source_id="open_meteo_archive_era5_land",
        latitude_deg=-6.2,
        longitude_deg=106.8,
        timezone="Asia/Jakarta",
        start_date="2025-01-01",
        end_date="2025-01-01",
    )
    with pytest.raises(WeatherAcquisitionError, match="no fallback"):
        adapter.build_request_url(request)


def test_open_meteo_fixture_normalizes_to_canonical_weather_and_passes_qc(tmp_path):
    result = _parse(tmp_path)
    weather = result.weather
    manifest = result.manifest

    assert weather.dataset["source_id"] == "open_meteo_archive_era5"
    assert weather.dataset["source_format"] == "open_meteo_historical_json_v0.1"
    _assert_no_retrieval_claims(weather.dataset, manifest)
    assert manifest["acquisition"]["data_origin"] == "synthetic_test_fixture"
    assert weather.dataset["upstream_generation"]["synthetic"] is True
    assert weather.dataset["upstream_generation"]["evidence"] == "user_declared"
    assert weather.dataset["timezone"] == "Asia/Jakarta"
    assert weather.dataset["native_resolution_seconds"] == 3600
    assert weather.dataset["series_resolution_seconds"] == 3600
    assert weather.dataset["start_time"] == "2025-01-01T00:00:00+07:00"
    assert weather.dataset["end_time"] == "2025-01-02T00:00:00+07:00"
    assert weather.series.index[0] == pd.Timestamp("2025-01-01T10:00:00+07:00")

    assert weather.series.iloc[0]["ghi_w_m2"] == pytest.approx(500.0)
    assert weather.series.iloc[0]["dni_w_m2"] == pytest.approx(600.0)
    assert weather.series.iloc[0]["dhi_w_m2"] == pytest.approx(120.0)
    assert weather.series.iloc[0]["ambient_temperature_c"] == pytest.approx(27.0)
    assert weather.series.iloc[0]["relative_humidity_fraction"] == pytest.approx(0.80)
    assert weather.series.iloc[0]["pressure_pa"] == pytest.approx(100800.0)
    assert weather.series.iloc[0]["wind_speed_m_s"] == pytest.approx(1.2)

    assert weather.dataset["variables"]["ghi_w_m2"]["source_temporal_semantics"] == (
        "preceding_hour_mean"
    )
    assert weather.dataset["variables"]["ambient_temperature_c"][
        "source_temporal_semantics"
    ] == "instant_at_source_label"
    assert weather.dataset["variables"]["ambient_temperature_c"][
        "canonical_alignment"
    ] == "assigned_to_preceding_hour_interval_without_interpolation"

    method = weather.dataset["source_metadata"]["source_method"]
    assert method["projection_authority"] == "source_product"
    assert method["opensimpv_resource_projection_applied"] is False
    assert weather.dataset["source_metadata"]["provider_model_parameter"] == "era5"
    assert weather.dataset["source_metadata"]["calendar_classification"] == (
        "partial_time_series"
    )
    assert weather.dataset["source_metadata"]["provider_location"]["latitude_deg"] == (
        pytest.approx(-6.25)
    )

    assert result.qc_report["status"] == "failed"
    assert result.qc_report["base_simulation_input_ready"] is False
    assert manifest["status"] == "failed"
    boundary_gaps = [finding for finding in result.qc_report["findings"]
                     if finding["rule_id"] == "WX_TIME_GAPS"]
    assert len(boundary_gaps) == 1
    assert boundary_gaps[0]["severity"] == "error"
    assert boundary_gaps[0]["count"] == 20
    assert boundary_gaps[0]["context"]["missing_boundary_intervals"] == 20
    assert len(weather.series) == 4
    assert manifest["source_method"]["projection_authority"] == "source_product"
    assert manifest["source_method"]["opensimpv_resource_projection_applied"] is False
    assert manifest["canonical_mapping"]["source_projection_preserved"] is True
    assert manifest["request"]["parameters"]["models"] == "era5"

    digest = sha256(_fixture_bytes()).hexdigest()
    assert manifest["raw_response"]["sha256"] == digest
    assert manifest["raw_response"]["storage_reference"] == (
        f"weather-snapshot://sha256/{digest}"
    )
    snapshot_path = tmp_path / "snapshots" / "sha256" / digest[:2] / f"{digest}.json"
    assert snapshot_path.read_bytes() == _fixture_bytes()


@pytest.mark.parametrize("synthetic", [True, False])
def test_open_meteo_fixture_replay_has_deterministic_canonical_hash(tmp_path, synthetic):
    first = _parse(tmp_path / "first", synthetic=synthetic)
    second = _parse(tmp_path / "second", synthetic=synthetic)

    assert (
        first.manifest["result"]["weather_dataset_sha256"]
        == second.manifest["result"]["weather_dataset_sha256"]
    )
    pd.testing.assert_frame_equal(first.weather.series, second.weather.series)
    assert first.weather.dataset == second.weather.dataset


def test_parser_replay_never_infers_transport_or_generation(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("parser replay must not perform transport or invent a retrieval time/URL")

    adapter = OpenMeteoHistoricalAdapter()
    monkeypatch.setattr(adapter, "_get_bytes", forbidden)
    monkeypatch.setattr(adapter, "build_request_url", forbidden)
    monkeypatch.setattr("weather.providers.open_meteo._utc_now_iso", forbidden)
    result = adapter.parse_response(
        _fixture_bytes(),
        request=_request(),
        weather_dataset_id="wx-replay",
        revision_id="wx-replay-r1",
        name="Unverified payload replay",
        site_id="site-weather-001",
    )
    _assert_no_retrieval_claims(result.weather.dataset, result.manifest)
    assert result.manifest["request"]["requested_at"] is None
    assert result.manifest["acquisition"]["data_origin"] == "unknown"
    assert result.manifest["acquisition"]["evidence"] == "unknown"
    assert result.weather.dataset["upstream_generation"]["synthetic"] is None
    assert result.weather.dataset["upstream_generation"]["provider"] is None
    assert result.weather.dataset["upstream_generation"]["method"] is None
    assert result.manifest["raw_response"]["sha256"] == sha256(_fixture_bytes()).hexdigest()
    pd.testing.assert_frame_equal(result.weather.series, _parse(tmp_path).weather.series)


@pytest.mark.parametrize("synthetic", [True, False])
def test_parser_legacy_retrieval_arguments_are_not_transport_evidence(tmp_path, synthetic):
    declared_url = "https://example.test/caller-declared-payload.json"
    declared_time = "2026-09-25T02:00:01+00:00"
    result = _parse(
        tmp_path,
        synthetic=synthetic,
        request_url=declared_url,
        retrieved_at=declared_time,
    )
    _assert_no_retrieval_claims(result.weather.dataset, result.manifest)
    if synthetic:
        assert "unverified_retrieval_declaration" not in result.manifest["request"]
        assert declared_url not in json.dumps(result.manifest)
        assert declared_time not in json.dumps(result.manifest)
    else:
        assert result.manifest["request"]["unverified_retrieval_declaration"] == {
            "source_url": declared_url, "retrieved_at": declared_time,
        }


@pytest.mark.parametrize("explicit_times", [True, False])
def test_provider_acquisition_records_only_successful_transport(tmp_path, monkeypatch, explicit_times):
    adapter = OpenMeteoHistoricalAdapter()
    events = []
    clock = iter([
        "2026-09-25T02:00:00+00:00", "2026-09-25T02:00:01+00:00",
        "2026-09-26T02:00:00+00:00", "2026-09-26T02:00:01+00:00",
    ])

    def now():
        timestamp = next(clock)
        events.append("clock")
        return timestamp

    def transport(url, *, timeout_seconds):
        events.append("transport")
        assert url == adapter.build_request_url(_request())
        assert timeout_seconds == 7.0
        return _fixture_bytes()  # Stubbed transport contract, not real ERA5 evidence.

    monkeypatch.setattr("weather.providers.open_meteo._utc_now_iso", now)
    monkeypatch.setattr(adapter, "_get_bytes", transport)
    times = ({
        "requested_at": "2026-09-25T02:00:00+00:00",
        "retrieved_at": "2026-09-25T02:00:01+00:00",
    } if explicit_times else {})
    kwargs = dict(
        request=_request(), weather_dataset_id="wx-transport", revision_id="wx-transport-r1",
        name="Stubbed provider transport", site_id="site-weather-001", timeout_seconds=7.0,
        snapshot_store=FileSystemWeatherSnapshotStore(tmp_path / "snapshots"), **times,
    )
    first = adapter.acquire(**kwargs)
    second = adapter.acquire(**kwargs)
    dataset, manifest = first.weather.dataset, first.manifest
    assert events == (["transport"] * 2 if explicit_times else ["clock", "transport", "clock"] * 2)
    assert manifest["acquisition"]["method"] == "provider_transport"
    assert manifest["acquisition"]["network_retrieval"] is True
    assert manifest["acquisition"]["data_origin"] == "provider_generated"
    assert manifest["acquisition"]["evidence"] == "provider_transport"
    assert manifest["request"]["requested_at"] == "2026-09-25T02:00:00+00:00"
    assert manifest["raw_response"]["retrieved_at"] == "2026-09-25T02:00:01+00:00"
    assert dataset["source_id"] == "open_meteo_archive_era5"
    assert dataset["native_series_origin"] == "provider_generated"
    assert dataset["series_origin"] == "provider_generated"
    assert dataset["upstream_generation"]["provider"] == manifest["source_product_name"]
    assert dataset["upstream_generation"]["synthetic"] is None
    assert dataset["upstream_generation"]["method"] == "era5_reanalysis_via_open_meteo"
    assert dataset["upstream_generation"]["evidence"] == "source_metadata"
    url = adapter.build_request_url(_request())
    assert manifest["raw_response"]["source_url"] == url
    assert dataset["source_metadata"]["request_url"] == url
    assert dataset["source_files"][0]["source_url"] == url
    assert dataset["source_files"][0]["attribution"] == manifest["raw_response"]["attribution"]
    assert manifest["raw_response"]["attribution"] == "Open-Meteo; ERA5 upstream data from ECMWF/Copernicus"
    assert "acquisition" not in dataset["source_metadata"]  # Preserve provider dataset fingerprints.
    assert first.weather.dataset == second.weather.dataset
    assert manifest["result"]["weather_dataset_sha256"] == second.manifest["result"]["weather_dataset_sha256"]
    pd.testing.assert_frame_equal(first.weather.series, _parse(tmp_path / "supplied").weather.series)
    _validator("weather-dataset.schema.json").validate(dataset)
    _validator("weather-source-acquisition-manifest.schema.json").validate(manifest)


def test_provider_transport_failure_cannot_return_success(monkeypatch):
    adapter = OpenMeteoHistoricalAdapter()

    def unavailable(*args, **kwargs):
        raise WeatherAcquisitionError("transport unavailable")

    def forbidden(*args, **kwargs):
        pytest.fail("failed transport must not reach payload parsing")

    monkeypatch.setattr(adapter, "_get_bytes", unavailable)
    monkeypatch.setattr(adapter, "_parse_response", forbidden)
    with pytest.raises(WeatherAcquisitionError, match="transport unavailable"):
        adapter.acquire(
            _request(), weather_dataset_id="wx-failed", revision_id="wx-failed-r1",
            name="Failed acquisition", site_id="site-weather-001",
        )


def test_synthetic_uat_injection_persists_honest_provenance(tmp_path, monkeypatch):
    from apps.api.project_store import FileProjectStore
    from apps.api.service import ProjectShellService
    from apps.api.study import BrowserStudyService

    projects = ProjectShellService(FileProjectStore(tmp_path / "projects"))
    study = BrowserStudyService(
        projects, weather_root=tmp_path / "weather", run_root=tmp_path / "runs",
        snapshot_root=tmp_path / "snapshots",
    )
    bundle = projects.create_project(
        name="Synthetic weather provenance", latitude_deg=-6.2, longitude_deg=106.8,
        elevation_m=25.0, timezone_name="Asia/Jakarta",
    )
    project_id = bundle["project"]["project_id"]

    def forbidden(*args, **kwargs):
        pytest.fail("synthetic injection must not acquire from a provider")

    monkeypatch.setattr(study.open_meteo, "_get_bytes", forbidden)
    monkeypatch.setattr(study.open_meteo, "acquire", forbidden)
    raw = (ROOT / "tests/fixtures/weather/open_meteo_era5_phase60d_uat.json").read_bytes()
    acquired = study.acquire_weather(
        project_id, source_id="open_meteo_archive_era5",
        start_date="2025-01-01", end_date="2025-01-01", raw_response=raw,
    )
    revision_id = acquired["selection"]["revision_id"]
    directory = tmp_path / "weather" / project_id / revision_id
    dataset = json.loads((directory / "weather-dataset.json").read_text())
    manifest = json.loads((directory / "acquisition-manifest.json").read_text())
    _assert_no_retrieval_claims(dataset, manifest)
    assert manifest == acquired["manifest"] == study.weather.manifest(project_id, revision_id)
    assert study.weather.load(project_id, revision_id).dataset == dataset
    saved = projects.get_bundle(project_id)
    assert saved["weather_selection"]["manifest"] == manifest
    assert saved["project"]["project_revision"]["weather_dataset_revision_id"] == revision_id
    assert manifest["request"]["requested_at"] is None
    assert dataset["source_id"] == manifest["source_id"] == "open_meteo_archive_era5"
    assert dataset["source_metadata"]["provider_model_parameter"] == "era5"
    assert manifest["source_product_name"] == "ERA5 via Open-Meteo Historical Weather API"
    assert manifest["acquisition"]["data_origin"] == "synthetic_test_fixture"
    assert manifest["acquisition"]["evidence"] == "user_declared"
    upstream = dataset["upstream_generation"]
    assert upstream["synthetic"] is True
    assert upstream["provider"] is None
    assert upstream["method"] == "synthetic_provider_shaped_test_fixture"
    assert upstream["evidence"] == "user_declared"
    assert "BrowserStudyService.acquire_weather(raw_response=...)" in upstream["evidence_detail"]
    assert "Synthetic provider-shaped test payload" in upstream["evidence_detail"]
    assert dataset["source_files"][0]["sha256"] == manifest["raw_response"]["sha256"] == sha256(raw).hexdigest()
    assert study.snapshots.get(sha256(raw).hexdigest()) == raw


def test_provenance_schemas_reject_supplied_payload_network_claims(tmp_path):
    result = _parse(tmp_path)
    manifest = deepcopy(result.manifest)
    manifest["acquisition"]["network_retrieval"] = True
    with pytest.raises(ValidationError):
        _validator("weather-source-acquisition-manifest.schema.json").validate(manifest)
    dataset = deepcopy(result.weather.dataset)
    dataset["source_metadata"]["acquisition"]["data_origin"] = "provider_generated"
    with pytest.raises(ValidationError):
        _validator("weather-dataset.schema.json").validate(dataset)


@pytest.mark.parametrize("false_claim", [
    {"retrieved_at": "2026-09-25T02:00:01+00:00"},
    {"source_url": "https://example.test/generated-request"},
])
def test_manifest_schema_rejects_retrieval_fields_for_supplied_bytes(tmp_path, false_claim):
    manifest = _parse(tmp_path).manifest
    manifest["raw_response"].update(false_claim)
    with pytest.raises(ValidationError):
        _validator("weather-source-acquisition-manifest.schema.json").validate(manifest)


def test_raw_snapshot_store_is_content_addressed_and_hash_checked(tmp_path):
    store = FileSystemWeatherSnapshotStore(tmp_path)
    first = store.put(_fixture_bytes())
    second = store.put(_fixture_bytes())

    assert first.sha256 == second.sha256
    assert first.storage_reference == second.storage_reference
    assert store.get(first.sha256) == _fixture_bytes()


def test_open_meteo_provider_error_payload_is_explicit_failure():
    raw = b'{"error":true,"reason":"source unavailable"}'
    adapter = OpenMeteoHistoricalAdapter()
    with pytest.raises(WeatherAcquisitionError, match="source unavailable") as exc:
        adapter.parse_response(
            raw,
            request=_request(),
            weather_dataset_id="wx-error",
            revision_id="wx-error-r1",
            name="Error",
            site_id="site-weather-001",
            requested_at="2026-09-25T02:00:00+00:00",
            retrieved_at="2026-09-25T02:00:01+00:00",
        )
    assert exc.value.source_id == "open_meteo_archive_era5"
    assert exc.value.finding()["code"] == "WX_PROVIDER_API_ERROR"
