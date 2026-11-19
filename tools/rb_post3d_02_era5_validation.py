"""Explicitly launched, bounded ERA5 integration validation (never annual execution)."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "open_meteo_archive_era5"
START = "2025-06-30T00:00:00+07:00"
END = "2025-07-02T00:00:00+07:00"
GIB = 1024 ** 3
DISK_MIN = 20 * GIB
PSS_MAX = 8 * GIB
FIDELITY = "level_2_bypass_substring"


def evidence():
    return {"status": "NOT_EXECUTED", "engineering_design_validation": "not_exercised",
            "execution_entry_point": "run_canonical_simulation",
            "reference_design": "phase610_b2_numerical_fixture",
            "stages": {}, "physical_yield_accuracy_established": False}


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False))
    temporary.replace(path)


def request():
    from weather.providers.base import WeatherAcquisitionRequest
    return WeatherAcquisitionRequest(SOURCE, -6.425, 106.831, "UTC+07:00",
                                     "2024-12-31", "2025-12-31", elevation_m=None)


def distance_km(lat, lon):
    """WGS-84 Vincenty inverse; nonconvergence fails closed."""
    if not all(math.isfinite(float(x)) for x in (lat, lon)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("invalid provider coordinates")
    a, f = 6378137., 1 / 298.257223563
    b = a * (1 - f)
    u1, u2 = [math.atan((1-f)*math.tan(math.radians(x))) for x in (-6.425, lat)]
    L = math.radians(lon - 106.831)
    lam = L
    for _ in range(200):
        ss = math.hypot(math.cos(u2)*math.sin(lam), math.cos(u1)*math.sin(u2)-math.sin(u1)*math.cos(u2)*math.cos(lam))
        if ss == 0:
            return 0.
        cs = math.sin(u1)*math.sin(u2)+math.cos(u1)*math.cos(u2)*math.cos(lam)
        sigma = math.atan2(ss, cs)
        sa = math.cos(u1)*math.cos(u2)*math.sin(lam)/ss
        c2a = 1-sa*sa
        c2s = cs-2*math.sin(u1)*math.sin(u2)/c2a if c2a else 0.
        C = f/16*c2a*(4+f*(4-3*c2a))
        new = L+(1-C)*f*sa*(sigma+C*ss*(c2s+C*cs*(-1+2*c2s*c2s)))
        if abs(new-lam) < 1e-12:
            break
        lam = new
    else:
        raise ValueError("provider geodesic did not converge")
    u = c2a*(a*a-b*b)/(b*b)
    A = 1+u/16384*(4096+u*(-768+u*(320-175*u)))
    B = u/1024*(256+u*(-128+u*(74-47*u)))
    ds = B*ss*(c2s+B/4*(cs*(-1+2*c2s*c2s)-B/6*c2s*(-3+4*ss*ss)*(-3+4*c2s*c2s)))
    return b*A*(sigma-ds)/1000


def check_coverage(weather):
    import numpy as np
    import pandas as pd
    d, frame = weather.dataset, weather.series
    meta = d.get("source_metadata", {})
    if d.get("source_id") != SOURCE or meta.get("provider_model_parameter") != "era5" or meta.get("calendar_classification") != "multi_year_time_series":
        raise ValueError("explicit chronological ERA5 source required")
    if not meta.get("raw_response_sha256") or not d.get("revision_id"):
        raise ValueError("source fingerprint and revision identity required")
    expected = pd.date_range("2024-12-31T00:00:00+07:00", periods=8784, freq="h")
    if frame.index.tz is None or not frame.index.equals(expected):
        raise ValueError("imported chronology must contain exactly 8784 consecutive hourly starts")
    if d.get("start_time") != expected[0].isoformat() or d.get("end_time") != (expected[-1]+pd.Timedelta(hours=1)).isoformat():
        raise ValueError("source metadata coverage endpoints disagree")
    if d.get("timezone") != "UTC+07:00" or d.get("timestamp_convention") != "interval_start":
        raise ValueError("canonical timezone/time-reference mismatch")
    if d.get("native_resolution_seconds") != 3600 or d.get("series_resolution_seconds") != 3600:
        raise ValueError("native hourly cadence required")
    for column in ("ghi_w_m2", "dni_w_m2", "dhi_w_m2", "ambient_temperature_c", "wind_speed_m_s"):
        if column not in frame or not np.isfinite(frame[column].to_numpy(dtype=float)).all():
            raise ValueError("missing mandatory variable: " + column)
        expected_unit = "degC" if column == "ambient_temperature_c" else "m/s" if column == "wind_speed_m_s" else "W/m2"
        if d.get("variables", {}).get(column, {}).get("canonical_unit") != expected_unit:
            raise ValueError("invalid canonical unit: " + column)
    year = frame.loc[(frame.index >= pd.Timestamp("2025-01-01T00:00:00+07:00")) &
                     (frame.index < pd.Timestamp("2026-01-01T00:00:00+07:00"))]
    if not year.index.equals(pd.date_range("2025-01-01T00:00:00+07:00", periods=8760, freq="h")):
        raise ValueError("local year must contain exactly 8760 hourly rows")
    def bounds(index):
        end = index[-1] + pd.Timedelta(hours=1)
        return {"rows": len(index), "local_start": index[0].isoformat(), "local_end_exclusive": end.isoformat(),
                "utc_start": index[0].tz_convert("UTC").isoformat(), "utc_end_exclusive": end.tz_convert("UTC").isoformat()}
    return {"source": bounds(frame.index), "local_year": bounds(year.index), "time_semantics": d["time_semantics"]}


def check_period(weather, config):
    import pandas as pd
    if config.get("start_time") != START or config.get("end_time") != END or config.get("simulation_timestep_seconds") != 3600:
        raise ValueError("only the fixed 48-hour native period is authorized; annual execution prohibited")
    index = weather.series.index
    selected = index[(index >= pd.Timestamp(START)) & (index < pd.Timestamp(END))]
    if not selected.equals(pd.date_range(START, periods=48, freq="h")):
        raise ValueError("selected period must contain exactly 48 hourly starts")
    return selected


def fixture_identity(fixture):
    from engine.simulation.artifacts import canonical_object_sha256
    from engine.simulation.detailed_dispatch import scientific_configuration
    config = deepcopy(scientific_configuration(fixture["configuration"]))
    for key in ("weather_dataset_revision_id", "start_time", "end_time"):
        config.pop(key, None)
    project = deepcopy(fixture["project"])
    project.pop("weather_dataset_revision_id", None)
    return canonical_object_sha256({"project": project, "configuration": config,
        "output_configuration": fixture["configuration"].get("output_configuration"),
        "scene": fixture["scene"], "design": fixture["design"],
        "components": fixture["store"].component_revisions,
        "selection": fixture["store"].detailed_electrical_inputs.replay()})


def bind_fixture(fixture, weather):
    if fixture["configuration"].get("output_configuration", {}).get("detailed_diagnostics") is not False:
        raise ValueError("B2 detailed diagnostics must remain disabled")
    expected = fixture_identity(fixture)
    fixture["project"] = deepcopy(fixture["project"])
    fixture["configuration"] = deepcopy(fixture["configuration"])
    for value in (fixture["project"], fixture["configuration"]):
        value["weather_dataset_revision_id"] = weather.dataset["revision_id"]
    c = fixture["configuration"]
    c.update(start_time=START, end_time=END)
    c["shading_configuration"]["electrical_shading_configuration"].setdefault("execution_options", {}).update(
        electrical_worker_count=1, attribution_worker_count=1)
    fixture["store"] = replace(fixture["store"], weather_revisions={weather.dataset["revision_id"]: weather})
    check_period(weather, c)
    if fixture_identity(fixture) != expected:
        raise ValueError("B2 scientific fixture identity changed")
    return expected


def require_detailed(identity, result):
    if (identity.get("runtime_support_result") != "pcc_complete" or identity.get("resolved_fidelity") != FIDELITY
            or identity.get("fallback_applied") is not False or result.detailed_backend_result is None):
        raise ValueError("detailed execution failed closed: " + json.dumps(identity))
    if len(result.detailed_backend_result.replay()["intervals"]) != 48:
        raise ValueError("detailed result interval count is not 48")


def simulation_job(directory):
    from tools.benchmark_phase610_fixtures import build_fixture, prepare_physical
    from weather.providers.open_meteo import OpenMeteoHistoricalAdapter
    from weather.providers.snapshot_store import FileSystemWeatherSnapshotStore
    from weather.providers.base import fingerprint_canonical_weather
    from weather.validation import run_weather_qc, run_solar_aware_weather_qc
    from engine.simulation.temporal import prepare_temporal_execution
    from engine.solar.position import solar_position_from_weather
    from apps.api.weather_store import FileWeatherRevisionStore
    from engine.simulation.canonical import run_canonical_simulation
    import pandas as pd
    directory = Path(directory)
    report = evidence()
    try:
        fixture = build_fixture("B2")
        weather_namespace = fixture["project"]["project_revision_id"]
        identifier = "era5-" + directory.name
        acquired = OpenMeteoHistoricalAdapter().acquire(request(), weather_dataset_id=identifier,
            revision_id=identifier+"-r1", name="ERA5 2025 source coverage", site_id=fixture["weather"].dataset["site_id"],
            snapshot_store=FileSystemWeatherSnapshotStore(directory / "snapshots"))
        weather = acquired.weather
        report["stages"]["acquisition"] = acquired.manifest
        write_json(directory / "report.json", report)
        if acquired.manifest["source_id"] != SOURCE or acquired.manifest["request"]["parameters"]["models"] != "era5":
            raise ValueError("ERA5 source fallback prohibited")
        before = fingerprint_canonical_weather(weather)
        if before != acquired.manifest["result"]["weather_dataset_sha256"]:
            raise ValueError("acquired fingerprint mismatch")
        revisions = FileWeatherRevisionStore(directory / "weather")
        if revisions._directory(weather_namespace, weather.dataset["revision_id"]).exists():
            raise FileExistsError("weather revision exists")
        revisions.save(weather_namespace, weather, acquisition_manifest=acquired.manifest)
        coverage = check_coverage(weather)
        if weather.dataset["location"] != {"latitude_deg": -6.425, "longitude_deg": 106.831, "elevation_m": None}:
            raise ValueError("canonical weather request location was changed")
        provider = acquired.manifest["provider_location"]
        distance = distance_km(provider["latitude_deg"], provider["longitude_deg"])
        if distance > 40:
            raise ValueError("provider grid exceeds 40 km spatial screen")
        elevation = provider.get("elevation_m")
        if elevation is not None and not math.isfinite(elevation):
            raise ValueError("nonfinite provider elevation")
        report["location"] = {"canonical": weather.dataset["location"], "provider": provider,
            "distance_km": distance, "distance_method": "WGS84 Vincenty inverse", "fixture_elevation_m": 93,
            "provider_elevation_difference_m": None if elevation is None else elevation-93,
            "canonical_elevation_difference_m": None if weather.dataset["location"].get("elevation_m") is None else weather.dataset["location"]["elevation_m"]-93,
            "absent_elevation_solar_policy": "0 m; complete ERA5 pressure used, otherwise standard atmosphere at 0 m"}
        report["fixture_identity"] = bind_fixture(fixture, weather)
        args = prepare_physical(fixture)
        delta = next(iter(args["module_configs"].values())).solar_delta_t_seconds
        temporal = prepare_temporal_execution(weather, simulation_timestep_seconds=3600)
        solar = solar_position_from_weather(temporal.weather, timeline=temporal.timeline, delta_t_seconds=delta)
        base = run_weather_qc(weather)
        aware = run_solar_aware_weather_qc(temporal.weather, solar)
        report["stages"]["full_source_validation"] = {"coverage": coverage, "base_qc": base, "solar_qc": aware}
        examples = []
        for start in (weather.series.index[0], pd.Timestamp(START)):
            examples.append({"upstream_label_utc": (start+pd.Timedelta(hours=1)).tz_convert("UTC").isoformat(),
                "canonical_start": start.isoformat(), "simulation_midpoint": (start+pd.Timedelta(minutes=30)).isoformat(),
                "solar_evaluation": str(solar.frame.loc[start, "evaluation_time"])})
        report["temporal_examples"] = examples
        report["solar_metadata"] = solar.metadata
        write_json(directory / "report.json", report)
        if base["status"] == "failed" or aware["status"] == "failed":
            raise ValueError("full-source weather QC failed")
        for column in ("ghi_w_m2", "dni_w_m2", "dhi_w_m2", "wind_speed_m_s"):
            if (weather.series[column] < 0).any():
                raise ValueError("negative required irradiance/wind: " + column)
        check_period(weather, fixture["configuration"])
        if shutil.disk_usage(directory).free < DISK_MIN:
            raise RuntimeError("less than 20 GiB free before simulation")
        run_id = "run-" + directory.name
        if (directory / "packages" / run_id).exists():
            raise FileExistsError("canonical package exists")
        result = run_canonical_simulation(fixture["project"], fixture["configuration"], revision_store=fixture["store"],
            output_directory=directory / "packages", simulation_run_id=run_id, engine_version="rb-post3d-02",
            design_validation_evidence=None)
        context = json.loads((result.artifact_directory / "detailed-execution-context.json").read_text())
        report["stages"]["simulation"] = {"run_id": run_id, "output_path": str(result.artifact_directory),
            "identity": context["identity"], "input_hashes": context["input_hashes"],
            "configuration": fixture["configuration"], "simulation_run": result.simulation_run,
            "summary": result.summary_result, "interval_count": 48}
        require_detailed(context["identity"], result)
        after = fingerprint_canonical_weather(weather)
        persisted = fingerprint_canonical_weather(revisions.load(weather_namespace, weather.dataset["revision_id"]))
        snapshot_bytes = FileSystemWeatherSnapshotStore(directory / "snapshots").get(acquired.manifest["raw_response"]["sha256"])
        if persisted != before or snapshot_bytes != acquired.raw_response:
            raise ValueError("persisted revision or source snapshot changed")
        report["weather_identity"] = {"before": before, "after": after, "revision_id": weather.dataset["revision_id"],
            "persisted_fingerprint": persisted, "raw_response_sha256": acquired.manifest["raw_response"]["sha256"],
            "project_id": weather_namespace,
            "project_binding": fixture["project"]["weather_dataset_revision_id"],
            "configuration_binding": fixture["configuration"]["weather_dataset_revision_id"]}
        if before != after or fixture_identity(fixture) != report["fixture_identity"]:
            raise ValueError("source or fixture mutated during execution")
        report["status"] = "AWAITING_INDEPENDENT_VERIFICATION"
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = str(exc)
        raise
    finally:
        write_json(directory / "report.json", report)


def verification_job(directory):
    from engine.simulation.artifacts import verify_run_package
    directory = Path(directory)
    report = json.loads((directory / "report.json").read_text())
    result = verify_run_package(Path(report["stages"]["simulation"]["output_path"]))
    from apps.api.weather_store import FileWeatherRevisionStore
    from weather.providers.base import fingerprint_canonical_weather
    from weather.providers.snapshot_store import FileSystemWeatherSnapshotStore
    identity = report["weather_identity"]
    persisted = FileWeatherRevisionStore(directory / "weather").load(identity["project_id"], identity["revision_id"])
    if fingerprint_canonical_weather(persisted) != identity["before"]:
        raise ValueError("weather source identity changed before independent verification")
    FileSystemWeatherSnapshotStore(directory / "snapshots").get(identity["raw_response_sha256"])
    write_json(directory / "verification.json", {"status": "passed", "package_manifest": result})


def process_tree_pss(pid):
    """Linux sampled descendant PSS; unavailable measurements fail closed."""
    parents = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = path.read_text().rsplit(")", 1)[1].split()
            parents[int(path.parent.name)] = int(fields[1])
        except (FileNotFoundError, ProcessLookupError):
            continue
    selected = {pid}
    while True:
        grown = selected | {p for p, parent in parents.items() if parent in selected}
        if grown == selected:
            break
        selected = grown
    total = 0
    for p in selected:
        try:
            lines = Path(f"/proc/{p}/smaps_rollup").read_text().splitlines()
        except FileNotFoundError:
            if p == pid:
                raise RuntimeError("PSS monitor unavailable")
            continue
        values = [int(line.split()[1])*1024 for line in lines if line.startswith("Pss:")]
        if len(values) != 1:
            raise RuntimeError("PSS monitor unavailable")
        total += values[0]
    return total


def supervise(command, directory, stage, seconds):
    directory = Path(directory)
    started = time.monotonic()
    metrics = {"sampled_peak_pss_bytes": 0, "memory_enforcement": "sampled; not a guaranteed peak bound",
               "minimum_free_disk_bytes": shutil.disk_usage(directory).free}
    with (directory / (stage + ".log")).open("xb") as log:
        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
        try:
            while child.poll() is None:
                if time.monotonic()-started >= seconds:
                    raise TimeoutError(stage + " wall-time limit exceeded")
                try:
                    pss = process_tree_pss(child.pid)
                except Exception:
                    if child.poll() is not None:
                        break
                    raise
                free = shutil.disk_usage(directory).free
                metrics["sampled_peak_pss_bytes"] = max(metrics["sampled_peak_pss_bytes"], pss)
                metrics["minimum_free_disk_bytes"] = min(metrics["minimum_free_disk_bytes"], free)
                if pss > PSS_MAX or free < DISK_MIN:
                    raise RuntimeError(stage + " resource limit exceeded")
                time.sleep(.25)
            if child.wait() != 0:
                raise RuntimeError(stage + " subprocess failed; see retained log")
        except BaseException as exc:
            metrics["error"] = str(exc)
            raise
        finally:
            # Also terminate any surviving descendants after the parent exits.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            metrics["wall_seconds"] = time.monotonic()-started
            write_json(directory / (stage + "-resources.json"), metrics)
    return metrics


@contextmanager
def job_lock():
    # Global per-user lock covers even jobs with different external output roots.
    path = Path("/tmp") / f"rawibumi-era5-{os.getuid()}.lock"
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another ERA5 validation job is running") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def preflight():
    from tools.benchmark_phase610_fixtures import build_fixture
    from weather.providers.open_meteo import OpenMeteoHistoricalAdapter
    fixture = build_fixture("B2")
    report = evidence()
    report.update(status="PREFLIGHT_ONLY", fixture_identity=fixture_identity(fixture),
        request_parameters=OpenMeteoHistoricalAdapter().build_request_parameters(request()),
        selected_period={"start": START, "end_exclusive": END, "interval_count": 48},
        guardrails={"simulation_seconds": 7200, "verification_seconds": 3600, "minimum_free_disk_bytes": DISK_MIN,
                    "sampled_pss_ceiling_bytes": PSS_MAX, "memory_policy": "abort if Linux PSS unavailable"})
    return report


def execute(output):
    with job_lock():
        root = Path(output).resolve()
        root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(root).free < DISK_MIN:
            raise RuntimeError("at least 20 GiB free disk required")
        process_tree_pss(os.getpid())  # require measurable PSS before launching
        directory = root / uuid.uuid4().hex
        directory.mkdir()
        write_json(directory / "report.json", evidence())
        def command(function):
            return [sys.executable, "-c", "from tools.rb_post3d_02_era5_validation import " + function +
                    "; import sys; " + function + "(sys.argv[1])", str(directory)]
        try:
            supervise(command("simulation_job"), directory, "execution", 7200)
            supervise(command("verification_job"), directory, "verification", 3600)
            report = json.loads((directory / "report.json").read_text())
            verified = json.loads((directory / "verification.json").read_text())
            if verified.get("status") != "passed":
                raise ValueError("independent package verification did not pass")
            report["stages"]["independent_verification"] = verified
            report["status"] = "PASS"
        except Exception as exc:
            report = json.loads((directory / "report.json").read_text())
            report.update(status="FAIL", supervision_error=str(exc))
        report["resources"] = {p.stem: json.loads(p.read_text()) for p in directory.glob("*-resources.json")}
        write_json(directory / "report.json", report)
        return report, directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true", help="offline inspection only")
    mode.add_argument("--execute", action="store_true", help="explicitly acquire ERA5 and run the fixed 48-hour validation")
    parser.add_argument("--output", type=Path, default=ROOT / ".ai/validation/rb_post3d_02")
    args = parser.parse_args(argv)
    try:
        if args.preflight:
            print(json.dumps(preflight(), indent=2))
            return 0
        report, directory = execute(args.output)
        print(json.dumps({"status": report["status"], "report": str(directory / "report.json")}))
        return 0 if report["status"] == "PASS" else 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
