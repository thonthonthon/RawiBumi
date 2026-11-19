"""Offline contracts: mock ERA5 transport; never run the numerical engine."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from tools import rb_post3d_02_era5_validation as runner
from weather.providers.base import WeatherAcquisitionError, fingerprint_canonical_weather
from weather.providers.open_meteo import OpenMeteoHistoricalAdapter


@pytest.fixture(scope="module")
def payload():
    index = pd.date_range("2024-12-31T00:00:00Z", periods=8784, freq="h")
    values = {"temperature_2m": (25., "°C"), "dew_point_2m": (20., "°C"),
              "relative_humidity_2m": (70., "%"), "surface_pressure": (1000., "hPa"),
              "wind_speed_10m": (1., "m/s"), "shortwave_radiation": (0., "W/m²"),
              "direct_normal_irradiance": (0., "W/m²"), "diffuse_radiation": (0., "W/m²")}
    return {"latitude": -6.425, "longitude": 106.831, "elevation": 110.,
            "hourly_units": {"time": "unixtime", **{k: unit for k, (_, unit) in values.items()}},
            "hourly": {"time": [int(x.timestamp()) for x in index],
                       **{k: [v] * len(index) for k, (v, _) in values.items()}}}


def parse(payload, request=None):
    return OpenMeteoHistoricalAdapter().parse_response(json.dumps(payload).encode(),
        request=request or runner.request(), weather_dataset_id="test-era5", revision_id="test-era5-r1",
        name="offline mocked ERA5", site_id="test-site")


@pytest.fixture(scope="module")
def acquired(payload):
    from pathlib import Path
    companion = Path(__file__).resolve().parents[1] / "fixtures/weather/open_meteo_era5_annual_padded_s10.json"
    return parse(json.loads(companion.read_bytes()))


def test_complete_coverage_and_boundaries(acquired):
    weather = acquired.weather
    before = fingerprint_canonical_weather(weather)
    report = runner.check_coverage(weather)
    assert report["source"]["rows"] == 8784
    assert report["local_year"] == {"rows": 8760, "local_start": "2025-01-01T00:00:00+07:00",
        "local_end_exclusive": "2026-01-01T00:00:00+07:00", "utc_start": "2024-12-31T17:00:00+00:00",
        "utc_end_exclusive": "2025-12-31T17:00:00+00:00"}
    assert fingerprint_canonical_weather(weather) == before
    assert weather.dataset["location"]["elevation_m"] is None
    assert acquired.manifest["provider_location"]["elevation_m"] == 110


@pytest.mark.parametrize("damage", ["missing", "duplicate"])
def test_bad_hourly_labels(payload, damage):
    value = deepcopy(payload)
    if damage == "missing":
        for array in value["hourly"].values():
            del array[100]
    else:
        value["hourly"]["time"][100] = value["hourly"]["time"][99]
    with pytest.raises(WeatherAcquisitionError, match="continuous 1-hour"):
        parse(value)


@pytest.mark.parametrize("column", ["ghi_w_m2", "dni_w_m2", "dhi_w_m2", "ambient_temperature_c", "wind_speed_m_s"])
def test_mandatory_variables(acquired, column):
    weather = acquired.weather.copy()
    weather.series = weather.series.drop(columns=column)
    with pytest.raises(ValueError, match="missing mandatory variable"):
        runner.check_coverage(weather)


def test_radiation_label_not_dni_or_double_shift(payload):
    value = deepcopy(payload)
    value["hourly"]["shortwave_radiation"][1] = 123.
    value["hourly"]["direct_normal_irradiance"][1] = 77.
    value["hourly"]["direct_radiation"] = [999.] * 8784
    value["hourly"]["temperature_2m"][1] = 27.
    weather = parse(value).weather
    row = weather.series.loc[pd.Timestamp("2024-12-31T00:00:00Z")]
    assert row["ghi_w_m2"] == 123.
    assert row["dni_w_m2"] == 77.
    assert row["ambient_temperature_c"] == 27.


def test_explicit_source_no_fallback(monkeypatch):
    adapter = OpenMeteoHistoricalAdapter()
    calls = []
    monkeypatch.setattr(adapter, "_get_bytes", lambda *a, **k: calls.append(a))
    params = adapter.build_request_parameters(runner.request())
    assert params["models"] == "era5"
    assert params["timezone"] == "GMT"
    assert "elevation" not in params
    assert params["cell_selection"] == "land"
    with pytest.raises(WeatherAcquisitionError):
        adapter.acquire(replace(runner.request(), source_id="best_match"),
            weather_dataset_id="x", revision_id="r", name="x", site_id="s")
    assert not calls


@pytest.mark.parametrize("model", ["best_match", "era5_land", None])
def test_source_metadata_must_be_era5(acquired, model):
    weather = acquired.weather.copy()
    weather.dataset["source_metadata"]["provider_model_parameter"] = model
    with pytest.raises(ValueError, match="explicit chronological ERA5"):
        runner.check_coverage(weather)


def test_fixed_period_and_annual_refusal(acquired):
    config = {"start_time": runner.START, "end_time": runner.END, "simulation_timestep_seconds": 3600}
    selected = runner.check_period(acquired.weather, config)
    assert len(selected) == 48
    assert selected[0].tz_convert("UTC") == pd.Timestamp("2025-06-29T17:00Z")
    assert selected[-1]+pd.Timedelta(hours=1) == pd.Timestamp(runner.END)
    for start, end in [(None, None), ("2025-01-01T00:00:00+07:00", "2026-01-01T00:00:00+07:00"),
                       (runner.START, "2025-07-03T00:00:00+07:00")]:
        with pytest.raises(ValueError, match="annual execution prohibited"):
            runner.check_period(acquired.weather, {**config, "start_time": start, "end_time": end})


@pytest.mark.parametrize("changed", [{"runtime_support_result": "mppt_complete"},
    {"runtime_support_result": "numerical_failed"}, {"resolved_fidelity": "geometry_only"}, {"fallback_applied": True}])
def test_detailed_fail_closed(changed):
    identity = {"runtime_support_result": "pcc_complete", "resolved_fidelity": runner.FIDELITY, "fallback_applied": False}
    result = SimpleNamespace(detailed_backend_result=SimpleNamespace(replay=lambda: {"intervals": [None]*48}))
    runner.require_detailed(identity, result)
    with pytest.raises(ValueError, match="failed closed"):
        runner.require_detailed({**identity, **changed}, result)


def test_b2_preservation_and_bindings(acquired):
    from tools.benchmark_phase610_fixtures import build_fixture
    fixture = build_fixture("B2")
    original = runner.fixture_identity(fixture)
    runner.bind_fixture(fixture, acquired.weather)
    assert runner.fixture_identity(fixture) == original == runner.fixture_identity(build_fixture("B2"))
    revision = acquired.weather.dataset["revision_id"]
    assert fixture["project"]["weather_dataset_revision_id"] == revision
    assert fixture["configuration"]["weather_dataset_revision_id"] == revision
    assert list(fixture["store"].weather_revisions) == [revision]
    opts = fixture["configuration"]["shading_configuration"]["electrical_shading_configuration"]["execution_options"]
    assert opts["electrical_worker_count"] == opts["attribution_worker_count"] == 1
    assert fixture["configuration"]["output_configuration"]["detailed_diagnostics"] is False


def test_preflight_has_no_network_or_execution(monkeypatch, capsys):
    import urllib.request
    import engine.simulation.canonical as canonical
    import engine.simulation.design as design
    def forbidden(*a, **k):
        raise AssertionError("forbidden side effect")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(OpenMeteoHistoricalAdapter, "acquire", forbidden)
    monkeypatch.setattr(canonical, "run_canonical_simulation", forbidden)
    for name in ("run_validated_design_simulation", "prepare_design_simulation", "design_validation_gate"):
        if hasattr(design, name):
            monkeypatch.setattr(design, name, forbidden)
    assert runner.main(["--preflight"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["engineering_design_validation"] == "not_exercised"
    assert report["execution_entry_point"] == "run_canonical_simulation"
    assert report["reference_design"] == "phase610_b2_numerical_fixture"
    with pytest.raises(SystemExit) as exc:
        runner.main(["--help"])
    assert exc.value.code == 0
    with pytest.raises(SystemExit):
        runner.main([])


def test_full_source_qc_precedes_execution(monkeypatch, tmp_path, acquired):
    import weather.validation as validation
    import engine.simulation.canonical as canonical
    import engine.solar.position as position
    import tools.benchmark_phase610_fixtures as fixtures
    from apps.api.weather_store import FileWeatherRevisionStore
    calls = []
    monkeypatch.setattr(OpenMeteoHistoricalAdapter, "acquire", lambda *a, **k: acquired)
    monkeypatch.setattr(FileWeatherRevisionStore, "save", lambda *a, **k: None)
    monkeypatch.setattr(fixtures, "prepare_physical", lambda *a: {"module_configs": {"m": SimpleNamespace(solar_delta_t_seconds=None)}})
    monkeypatch.setattr(position, "solar_position_from_weather", lambda weather, **k: SimpleNamespace(
        frame=pd.DataFrame({"evaluation_time": weather.series.index+pd.Timedelta(minutes=30)}, index=weather.series.index), metadata={}))
    def qc(weather):
        calls.append(("base", len(weather.series)))
        return {"status": "passed", "findings": []}
    def solar_qc(weather, solar):
        calls.append(("solar", len(weather.series)))
        return {"status": "failed", "findings": [{"severity": "error", "code": "test"}]}
    monkeypatch.setattr(validation, "run_weather_qc", qc)
    monkeypatch.setattr(validation, "run_solar_aware_weather_qc", solar_qc)
    monkeypatch.setattr(canonical, "run_canonical_simulation", lambda *a, **k: calls.append(("simulation", 48)))
    with pytest.raises(ValueError, match="full-source weather QC failed"):
        runner.simulation_job(tmp_path)
    assert calls == [("base", 8784), ("solar", 8784)]
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["status"] == "FAIL"
    assert report["stages"]["full_source_validation"]["solar_qc"]["findings"]


def test_independent_verifier_failure(monkeypatch, tmp_path):
    import engine.simulation.artifacts as artifacts
    runner.write_json(tmp_path / "report.json", {"stages": {"simulation": {"output_path": "no-package"}}})
    def fail(*a):
        raise ValueError("invalid package")
    monkeypatch.setattr(artifacts, "verify_run_package", fail)
    with pytest.raises(ValueError, match="invalid package"):
        runner.verification_job(tmp_path)
    assert not (tmp_path / "verification.json").exists()


@pytest.mark.parametrize("failure", ["exit", "timeout", "verifier_status"])
def test_verification_failure_propagation(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(runner, "process_tree_pss", lambda *a: 1)
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda *a: SimpleNamespace(free=30*runner.GIB))
    commands = []
    def supervise(command, directory, stage, seconds):
        commands.append(command)
        if stage == "verification" and failure != "verifier_status":
            raise TimeoutError("verifier timeout") if failure == "timeout" else RuntimeError("verifier exit")
        if stage == "verification":
            runner.write_json(directory / "verification.json", {"status": "failed"})
    monkeypatch.setattr(runner, "supervise", supervise)
    report, directory = runner.execute(tmp_path)
    assert report["status"] == "FAIL"
    assert "verification_job" in commands[1][2]
    assert commands[1][0] == runner.sys.executable
    assert report["engineering_design_validation"] == "not_exercised"


@pytest.mark.parametrize("limit", ["timeout", "memory", "disk", "unavailable"])
def test_resource_supervision_kills_group(monkeypatch, tmp_path, limit):
    import signal
    killed = []
    class Child:
        pid = 999999
        def poll(self):
            return None
        def wait(self):
            return -9
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: Child())
    monkeypatch.setattr(runner.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda *a: SimpleNamespace(free=(1 if limit == "disk" else 30*runner.GIB)))
    def sample(pid):
        if limit == "unavailable":
            raise RuntimeError("PSS monitor unavailable")
        return runner.PSS_MAX+1 if limit == "memory" else 1
    monkeypatch.setattr(runner, "process_tree_pss", sample)
    with pytest.raises((TimeoutError, RuntimeError)):
        runner.supervise(["mock"], tmp_path, "test", 0 if limit == "timeout" else 1)
    assert killed == [(999999, signal.SIGKILL)]
    assert (tmp_path / "test-resources.json").exists()


def test_insufficient_disk_never_launches(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda *a: SimpleNamespace(free=1))
    monkeypatch.setattr(runner, "supervise", lambda *a: pytest.fail("must not launch"))
    with pytest.raises(RuntimeError, match="20 GiB"):
        runner.execute(tmp_path)


def test_one_job_lock():
    with runner.job_lock():
        with pytest.raises(RuntimeError, match="another ERA5"):
            with runner.job_lock():
                pytest.fail("concurrent job permitted")


def test_grid_screen():
    assert runner.distance_km(-6.425, 106.831) == 0
    assert runner.distance_km(-6.4, 106.8) < 40
    assert runner.distance_km(0., 0.) > 40
    with pytest.raises(ValueError, match="invalid provider"):
        runner.distance_km(float("nan"), 106.)


@pytest.mark.parametrize("runtime_status", ["pcc_complete", "mppt_complete"])
def test_simulation_job_through_persistence(monkeypatch, tmp_path, acquired, runtime_status):
    import weather.validation as validation
    import engine.simulation.canonical as canonical
    import engine.simulation.artifacts as artifacts
    import engine.solar.position as position
    import tools.benchmark_phase610_fixtures as fixtures
    from apps.api.weather_store import FileWeatherRevisionStore
    from weather.providers.snapshot_store import FileSystemWeatherSnapshotStore

    calls = []
    expected_namespace = fixtures.build_fixture("B2")["project"]["project_revision_id"]
    original_identity = runner.fixture_identity(fixtures.build_fixture("B2"))
    def acquire(*args, **kwargs):
        kwargs["snapshot_store"].put(acquired.raw_response)
        return acquired
    monkeypatch.setattr(OpenMeteoHistoricalAdapter, "acquire", acquire)
    monkeypatch.setattr(fixtures, "prepare_physical", lambda *a: {
        "module_configs": {"m": SimpleNamespace(solar_delta_t_seconds=None)}})
    monkeypatch.setattr(position, "solar_position_from_weather", lambda weather, **k: SimpleNamespace(
        frame=pd.DataFrame({"evaluation_time": weather.series.index+pd.Timedelta(minutes=30)},
                           index=weather.series.index), metadata={}))
    def qc(label, weather):
        calls.append((label, len(weather.series)))
        return {"status": "passed", "findings": []}
    monkeypatch.setattr(validation, "run_weather_qc", lambda weather: qc("base", weather))
    monkeypatch.setattr(validation, "run_solar_aware_weather_qc", lambda weather, solar: qc("solar", weather))
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda *a: SimpleNamespace(free=30*runner.GIB))
    def simulate(project, config, **kwargs):
        calls.append(("simulation", 48))
        assert calls == [("base", 8784), ("solar", 8784), ("simulation", 48)]
        assert "project_id" not in project
        assert kwargs["design_validation_evidence"] is None
        assert config["start_time"] == runner.START and config["end_time"] == runner.END
        assert config["simulation_timestep_seconds"] == 3600
        assert config["output_configuration"]["detailed_diagnostics"] is False
        opts = config["shading_configuration"]["electrical_shading_configuration"]["execution_options"]
        assert opts["electrical_worker_count"] == opts["attribution_worker_count"] == 1
        revision = acquired.weather.dataset["revision_id"]
        assert project["weather_dataset_revision_id"] == config["weather_dataset_revision_id"] == revision
        assert list(kwargs["revision_store"].weather_revisions) == [revision]
        assert kwargs["revision_store"].weather_revisions[revision] is acquired.weather
        package = kwargs["output_directory"] / kwargs["simulation_run_id"]
        package.mkdir(parents=True)
        runner.write_json(package / "detailed-execution-context.json", {
            "identity": {"runtime_support_result": runtime_status,
                         "resolved_fidelity": runner.FIDELITY, "fallback_applied": False},
            "input_hashes": {"mock": "offline"}})
        return SimpleNamespace(artifact_directory=package, simulation_run={"status": "completed"},
            summary_result={"mock": True}, detailed_backend_result=SimpleNamespace(
                replay=lambda: {"intervals": [None]*48}))
    monkeypatch.setattr(canonical, "run_canonical_simulation", simulate)
    if runtime_status != "pcc_complete":
        with pytest.raises(ValueError, match="failed closed"):
            runner.simulation_job(tmp_path)
        report = json.loads((tmp_path / "report.json").read_text())
        assert report["status"] == "FAIL"
        assert report["stages"]["simulation"]["identity"]["runtime_support_result"] == runtime_status
        assert not (tmp_path / "verification.json").exists()
        return
    runner.simulation_job(tmp_path)
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["status"] == "AWAITING_INDEPENDENT_VERIFICATION"
    assert report["fixture_identity"] == original_identity
    identity = report["weather_identity"]
    assert identity["project_id"] == expected_namespace
    assert identity["project_binding"] == identity["configuration_binding"] == identity["revision_id"]
    persisted = FileWeatherRevisionStore(tmp_path / "weather").load(expected_namespace, identity["revision_id"])
    assert fingerprint_canonical_weather(persisted) == identity["before"] == identity["after"]
    assert FileSystemWeatherSnapshotStore(tmp_path / "snapshots").get(identity["raw_response_sha256"]) == acquired.raw_response
    verified_paths = []
    def verify(path):
        verified_paths.append(path)
        return {"mock_verified": True}
    monkeypatch.setattr(artifacts, "verify_run_package", verify)
    runner.verification_job(tmp_path)
    assert verified_paths == [runner.Path(report["stages"]["simulation"]["output_path"])]
    assert json.loads((tmp_path / "verification.json").read_text()) == {
        "status": "passed", "package_manifest": {"mock_verified": True}}
    assert report["engineering_design_validation"] == "not_exercised"


def test_execute_success_and_main_exit(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(runner, "process_tree_pss", lambda *a: 1)
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda *a: SimpleNamespace(free=30*runner.GIB))
    stages = []
    def supervise(command, directory, stage, seconds):
        stages.append((command, stage, seconds))
        if stage == "execution":
            report = runner.evidence()
            report["status"] = "AWAITING_INDEPENDENT_VERIFICATION"
            runner.write_json(directory / "report.json", report)
        else:
            runner.write_json(directory / "verification.json", {"status": "passed", "package_manifest": {}})
    monkeypatch.setattr(runner, "supervise", supervise)
    assert runner.main(["--execute", "--output", str(tmp_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "PASS"
    report = json.loads(runner.Path(output["report"]).read_text())
    assert report["status"] == "PASS"
    assert report["stages"]["independent_verification"]["status"] == "passed"
    assert report["engineering_design_validation"] == "not_exercised"
    assert [(stage, seconds) for _, stage, seconds in stages] == [("execution", 7200), ("verification", 3600)]
    assert "simulation_job" in stages[0][0][2]
    assert "verification_job" in stages[1][0][2]
    assert all(command[0] == runner.sys.executable for command, _, _ in stages)


def test_fixture_output_settings_are_preserved(acquired):
    from tools.benchmark_phase610_fixtures import build_fixture
    fixture = build_fixture("B2")
    before = runner.fixture_identity(fixture)
    fixture["configuration"]["output_configuration"]["detailed_diagnostics"] = True
    assert runner.fixture_identity(fixture) != before
    with pytest.raises(ValueError, match="diagnostics must remain disabled"):
        runner.bind_fixture(fixture, acquired.weather)
