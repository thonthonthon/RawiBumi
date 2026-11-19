#!/usr/bin/env python3
"""Phase-5.9 annual geometry-aware SimulationRun validation.

Default mode executes the complete annual acceptance matrix:
- R1 full-year clear/no-loss reference with cache none;
- R1 full-year exact cold and exact warm;
- R4 full-year exact beam+sky+ground geometry.

--quick keeps the same artifact/identity assertions on the existing short R4
fixture and is intended for normal PR iteration. Timing is evidence only.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np
import pandas as pd
import pvlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.simulation.artifacts import verify_run_package
from geometry.shading import clear_global_exact_shading_cache
from weather.core import build_time_semantics, build_weather_dataset


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _modules():
    phase57 = _load(
        "tests/unit/test_phase57_ground_vertical_slice.py",
        "_opensimpv_phase57_phase59_bench",
    )
    phase56 = phase57._load_phase56_module()
    phase55 = phase56._load_phase55_module()
    phase49c = phase55._load_phase49c_reference_module()
    return phase49c, phase55, phase56, phase57


def _annual_weather(project_id: str):
    index = pd.date_range(
        "2026-01-01T00:00:00+07:00",
        periods=8760,
        freq="h",
    )
    evaluation = index + pd.Timedelta(minutes=30)
    latitude = -6.4245
    longitude = 106.8307
    elevation = 82.0

    location = pvlib.location.Location(
        latitude,
        longitude,
        tz="Asia/Jakarta",
        altitude=elevation,
    )
    clear = location.get_clearsky(evaluation, model="ineichen")
    series = pd.DataFrame(
        {
            "ghi_w_m2": clear["ghi"].to_numpy(dtype=float),
            "dni_w_m2": clear["dni"].to_numpy(dtype=float),
            "dhi_w_m2": clear["dhi"].to_numpy(dtype=float),
            "ambient_temperature_c": np.full(8760, 30.0),
            "wind_speed_m_s": np.full(8760, 1.0),
            "pressure_pa": np.full(8760, 100500.0),
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
        series,
        weather_dataset_id=f"wx-{project_id}-phase59-annual",
        revision_id=f"wx-{project_id}-phase59-annual-r1",
        name=f"{project_id} Phase 5.9 annual clear-sky benchmark weather",
        site_id=f"site-{project_id}",
        timezone="UTC+07:00",
        native_resolution_seconds=3600,
        source_format="synthetic_phase59_clear_sky",
        source_timestamp_convention="interval_start",
        location={
            "latitude_deg": latitude,
            "longitude_deg": longitude,
            "elevation_m": elevation,
        },
        native_series_origin="opensimpv_derived",
        series_origin="opensimpv_derived",
        upstream_generation={
            "provider": "pvlib",
            "synthetic": True,
            "base_resolution_seconds": 3600,
            "method": "ineichen_clear_sky_at_interval_midpoint",
            "evidence": "opensimpv_transformation",
            "evidence_detail": (
                "Synthetic deterministic annual weather for Phase-5.9 "
                "integration/regression only; not a resource-yield reference."
            ),
        },
        time_semantics=semantics,
    )


def _annual_context(case_id: str):
    phase49c, phase55, phase56, phase57 = _modules()
    ref = phase49c._reference(case_id)
    _, _, _, beam_config = phase55._rebind_project_and_configs(
        ref,
        f"{case_id.lower()}-phase59-template",
    )
    sky_config = phase56._sky_config(
        beam_config,
        f"{case_id.lower()}-phase59-sky",
    )
    config = phase57._ground_config(
        sky_config,
        f"{case_id.lower()}-phase59-ground",
    )
    weather = _annual_weather(ref["project_id"])
    project = phase49c.build_project_revision_from_design(
        ref["scene"],
        ref["electrical"],
        project_revision_id=ref["project_revision"]["project_revision_id"],
        revision_number=1,
        weather_dataset_revision_id=weather.dataset["revision_id"],
        change_summary=f"Phase 5.9 {case_id} annual benchmark revision.",
    )
    config = deepcopy(config)
    config["weather_dataset_revision_id"] = weather.dataset["revision_id"]
    config["start_time"] = None
    config["end_time"] = None
    return phase55, ref, project, weather, config


def _run(phase55, ref, project, weather, config, output, suffix):
    start = perf_counter()
    result = phase55._run(
        ref,
        project,
        weather,
        config,
        output,
        suffix,
    )
    elapsed = perf_counter() - start
    verify_run_package(result.artifact_directory)
    return result, elapsed


def _identity(result):
    shading = result.simulation_run["shading_result"]
    receiver = result.simulation_run["shading_receiver_factor_reference"]
    return {
        "input_hash": result.simulation_run["input_hash"],
        "standard_logical_sha256": result.simulation_run["result_reference"][
            "logical_content_sha256"
        ],
        "receiver_logical_sha256": receiver["logical_content_sha256"],
        "receiver_physical_sha256": receiver["physical_content_sha256"],
        "shading_result_id": shading["shading_result_id"],
        "shading_physical_result_sha256": shading["physical_result_sha256"],
    }


def _quick(output: Path):
    phase58h = _load(
        "tests/unit/test_phase58h_preannual_hardening.py",
        "_opensimpv_phase58h_phase59_bench",
    )
    phase55, ref, project, weather, config = phase58h._r4_ground_context(
        "r4-phase59-quick"
    )
    exact = deepcopy(config)
    exact["simulation_configuration_id"] = "simcfg-phase59-quick-exact"
    exact["shading_configuration"]["cache_policy"] = {"mode": "exact"}
    none = deepcopy(exact)
    none["simulation_configuration_id"] = "simcfg-phase59-quick-none"
    none["shading_configuration"]["cache_policy"] = {"mode": "none"}

    clear_global_exact_shading_cache()
    ref_run, ref_seconds = _run(
        phase55, ref, project, weather, none, output, "phase59-quick-none"
    )
    exact_run, exact_seconds = _run(
        phase55, ref, project, weather, exact, output, "phase59-quick-exact"
    )

    a = _identity(ref_run)
    b = _identity(exact_run)
    if a["standard_logical_sha256"] != b["standard_logical_sha256"]:
        raise AssertionError("Phase-5.9 quick none/exact standard result mismatch")
    if a["receiver_physical_sha256"] != b["receiver_physical_sha256"]:
        raise AssertionError("Phase-5.9 quick none/exact factor physics mismatch")
    if (
        a["shading_physical_result_sha256"]
        != b["shading_physical_result_sha256"]
    ):
        raise AssertionError("Phase-5.9 quick none/exact shading identity mismatch")

    return {
        "mode": "quick",
        "none_seconds": ref_seconds,
        "exact_seconds": exact_seconds,
        "none_identity": a,
        "exact_identity": b,
    }


def _full(output: Path):
    phase55, r1, p1, w1, r1_base = _annual_context("R1")

    r1_none_cfg = deepcopy(r1_base)
    r1_none_cfg["simulation_configuration_id"] = "simcfg-phase59-r1-annual-none"
    r1_none_cfg["shading_configuration"]["cache_policy"] = {"mode": "none"}

    r1_exact_cfg = deepcopy(r1_base)
    r1_exact_cfg["simulation_configuration_id"] = "simcfg-phase59-r1-annual-exact"
    r1_exact_cfg["shading_configuration"]["cache_policy"] = {"mode": "exact"}

    clear_global_exact_shading_cache()
    r1_none, r1_none_seconds = _run(
        phase55, r1, p1, w1, r1_none_cfg, output, "phase59-r1-annual-none"
    )
    r1_cold, r1_cold_seconds = _run(
        phase55, r1, p1, w1, r1_exact_cfg, output, "phase59-r1-annual-cold"
    )
    r1_warm, r1_warm_seconds = _run(
        phase55, r1, p1, w1, r1_exact_cfg, output, "phase59-r1-annual-warm"
    )

    r1_ids = [_identity(item) for item in (r1_none, r1_cold, r1_warm)]
    if len({item["standard_logical_sha256"] for item in r1_ids}) != 1:
        raise AssertionError("R1 annual none/cold/warm standard results diverged")
    if len({item["receiver_physical_sha256"] for item in r1_ids}) != 1:
        raise AssertionError("R1 annual none/cold/warm factor physics diverged")
    if len({item["shading_physical_result_sha256"] for item in r1_ids}) != 1:
        raise AssertionError("R1 annual none/cold/warm shading physics diverged")

    for run in (r1_none, r1_cold, r1_warm):
        if run.summary_result["annual_energy_wh"] is None:
            raise AssertionError("R1 full-year run did not publish annual energy")
        loss = run.summary_result["shading_energy_loss_wh"]
        if loss is None or abs(float(loss)) > 1e-6:
            raise AssertionError(f"R1 clear annual shading loss is not zero: {loss}")

    phase55, r4, p4, w4, r4_cfg = _annual_context("R4")
    r4_cfg = deepcopy(r4_cfg)
    r4_cfg["simulation_configuration_id"] = "simcfg-phase59-r4-annual-exact"
    r4_cfg["shading_configuration"]["cache_policy"] = {"mode": "exact"}

    clear_global_exact_shading_cache()
    r4_run, r4_seconds = _run(
        phase55, r4, p4, w4, r4_cfg, output, "phase59-r4-annual-exact"
    )
    if r4_run.summary_result["annual_energy_wh"] is None:
        raise AssertionError("R4 full-year run did not publish annual energy")
    if r4_run.summary_result["shading_energy_loss_wh"] is None:
        raise AssertionError("R4 full-year run did not quantify geometric shading loss")
    if r4_run.summary_result["shading_energy_loss_basis"] is None:
        raise AssertionError("R4 full-year shading loss lacks counterfactual provenance")

    receiver = r4_run.simulation_run["shading_receiver_factor_reference"]
    if receiver["row_count"] != 216 * 8760:
        raise AssertionError(
            f"R4 annual receiver rows {receiver['row_count']} != {216 * 8760}"
        )
    telemetry = r4_run.simulation_run["execution_telemetry"][
        "receiver_factor_persistence"
    ]
    if telemetry["streaming_enabled"] is not True:
        raise AssertionError("R4 annual factor persistence did not stream")

    factors = r4_run.standard_timeseries
    nontrivial = (
        (factors["beam_visibility_factor_group"] < 1.0).any()
        or (factors["sky_visibility_factor_group"] < 1.0).any()
        or (factors["ground_visibility_factor_group"] < 1.0).any()
    )
    if not nontrivial:
        raise AssertionError("R4 annual geometry produced no nontrivial shading")

    return {
        "mode": "full",
        "r1": {
            "none_seconds": r1_none_seconds,
            "cold_exact_seconds": r1_cold_seconds,
            "warm_exact_seconds": r1_warm_seconds,
            "identities": r1_ids,
            "annual_energy_wh": r1_cold.summary_result["annual_energy_wh"],
            "shading_energy_loss_wh": r1_cold.summary_result[
                "shading_energy_loss_wh"
            ],
        },
        "r4": {
            "exact_seconds": r4_seconds,
            "identity": _identity(r4_run),
            "annual_energy_wh": r4_run.summary_result["annual_energy_wh"],
            "shading_energy_loss_wh": r4_run.summary_result[
                "shading_energy_loss_wh"
            ],
            "receiver_factor_rows": receiver["row_count"],
            "streaming_telemetry": telemetry,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run short R4 artifact/identity validation instead of the full annual matrix.",
    )
    args = parser.parse_args()

    with TemporaryDirectory(prefix="opensimpv-phase59-") as directory:
        result = _quick(Path(directory)) if args.quick else _full(Path(directory))
    output = {
        "benchmark_id": "opensimpv.phase59.full_geometry_aware_annual.v0.1",
        "timing_is_acceptance_gate": False,
        "physical_identity_is_acceptance_gate": True,
        "annual_result_is_acceptance_gate": not args.quick,
        "result": result,
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
