#!/usr/bin/env python3
"""Phase-5.11 closure benchmark and reproducibility evidence.

Timing and memory values are evidence only; no universal hardware threshold is
an acceptance gate.  The benchmark fails on deterministic identity drift,
cache-behavior regression, or loss of the annual save/reload closure chain.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import platform
import resource
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.simulation.artifacts import canonical_object_sha256
from engine.simulation.design import (
    load_design_state_package,
    persist_design_state_package,
)
from geometry.shading import (
    SkyDomeResolution,
    calculate_direct_beam_shadow,
    calculate_sky_visibility,
    clear_global_exact_shading_cache,
    compile_shading_geometry,
    sun_vector_from_azimuth_elevation,
)


def _benchmark_environment():
    cpu_model = ""
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                cpu_model = line.split(":", 1)[1].strip()
                break

    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_model": cpu_model or None,
        "logical_cpu_count": os.cpu_count(),
        "github_actions": os.environ.get("GITHUB_ACTIONS") == "true",
        "runner_os": os.environ.get("RUNNER_OS"),
        "runner_arch": os.environ.get("RUNNER_ARCH"),
        "timing_clock": "time.perf_counter",
        "memory_measurements": [
            "tracemalloc_python_heap",
            "resource_ru_maxrss_process_high_water",
        ],
    }


def _max_rss_bytes():
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform.startswith("linux"):
        return value * 1024, value, "KiB"
    if sys.platform == "darwin":
        return value, value, "bytes"
    return None, value, "platform_native"


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _phase49c():
    return _load(
        "tests/unit/test_phase49c_reference_projects.py",
        "_opensimpv_phase49c_phase511_bench",
    )


def _phase58h():
    return _load(
        "tests/unit/test_phase58h_preannual_hardening.py",
        "_opensimpv_phase58h_phase511_bench",
    )


def _phase59():
    return _load(
        "tools/benchmark_phase59.py",
        "_opensimpv_phase59_phase511_bench",
    )


def _module_receiver_ids(compiled):
    return sorted(
        str(item["receiver_id"])
        for item in compiled["receivers"]
        if item.get("enabled") is True
        and item.get("source_entity_type") == "module_instance"
    )


def _measure_geometry_costs(*, quick: bool):
    ref = _phase49c()._reference("R4")

    tracemalloc.start()
    compile_start = perf_counter()
    compiled = compile_shading_geometry(ref["scene"])
    compile_seconds = perf_counter() - compile_start

    receiver_ids = _module_receiver_ids(compiled)
    selected = receiver_ids[: (1 if quick else 12)]
    directions = [
        sun_vector_from_azimuth_elevation(75.0, 25.0),
        sun_vector_from_azimuth_elevation(150.0, 45.0),
    ]
    if not quick:
        directions.extend(
            [
                sun_vector_from_azimuth_elevation(225.0, 35.0),
                sun_vector_from_azimuth_elevation(300.0, 20.0),
            ]
        )

    beam_start = perf_counter()
    beam_queries = 0
    for receiver_id in selected:
        for direction in directions:
            result = calculate_direct_beam_shadow(
                compiled,
                receiver_id=receiver_id,
                sun_vector_xyz=direction,
                self_shading_enabled=True,
            )
            if not 0.0 <= float(result["beam_visibility_factor"]) <= 1.0:
                raise AssertionError("beam visibility escaped [0, 1]")
            beam_queries += 1
    beam_seconds = perf_counter() - beam_start

    resolution = SkyDomeResolution(
        azimuth_sectors=8 if quick else 16,
        elevation_bands=2 if quick else 4,
        horizon_azimuth_sectors=8 if quick else 16,
        horizon_elevation_bands=1 if quick else 2,
        horizon_band_elevation_deg=15.0,
    )
    sky_start = perf_counter()
    sky_queries = 0
    for receiver_id in selected:
        result = calculate_sky_visibility(
            compiled,
            receiver_id=receiver_id,
            self_shading_enabled=True,
            resolution=resolution,
        )
        if not 0.0 <= float(result["sky_visibility_factor"]) <= 1.0:
            raise AssertionError("sky visibility escaped [0, 1]")
        sky_queries += 1
    sky_seconds = perf_counter() - sky_start

    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "case": "R4_geometry_costs",
        "quick": quick,
        "receiver_count_total": len(receiver_ids),
        "receiver_count_measured": len(selected),
        "compile_seconds": compile_seconds,
        "beam_query_count": beam_queries,
        "beam_query_seconds": beam_seconds,
        "beam_seconds_per_query": beam_seconds / beam_queries,
        "sky_query_count": sky_queries,
        "sky_view_seconds": sky_seconds,
        "sky_seconds_per_receiver": sky_seconds / sky_queries,
        "python_memory_current_bytes": current_bytes,
        "python_memory_peak_bytes": peak_bytes,
        "compiled_geometry_sha256": compiled["geometry_payload_sha256"],
    }


def _measure_cache_behavior():
    phase58h = _phase58h()
    phase55, ref, project, weather, config = phase58h._r4_ground_context(
        "r4-phase511-cache"
    )
    config = deepcopy(config)
    config["simulation_configuration_id"] = "simcfg-phase511-cache"
    config["shading_configuration"]["cache_policy"] = {"mode": "exact"}

    with TemporaryDirectory(prefix="opensimpv-phase511-cache-") as directory:
        output = Path(directory)
        clear_global_exact_shading_cache()

        start = perf_counter()
        cold = phase55._run(
            ref, project, weather, config, output, "phase511-cache-cold"
        )
        cold_seconds = perf_counter() - start

        start = perf_counter()
        warm = phase55._run(
            ref, project, weather, config, output, "phase511-cache-warm"
        )
        warm_seconds = perf_counter() - start

    cold_accel = cold.simulation_run["execution_telemetry"]["shading_acceleration"]
    warm_accel = warm.simulation_run["execution_telemetry"]["shading_acceleration"]

    if cold_accel["static_cache_miss_count"] <= 0:
        raise AssertionError("cold exact run recorded no static cache miss")
    if warm_accel["static_cache_hit_count"] <= 0:
        raise AssertionError("warm exact run recorded no static cache hit")

    if (
        cold.simulation_run["result_reference"]["logical_content_sha256"]
        != warm.simulation_run["result_reference"]["logical_content_sha256"]
    ):
        raise AssertionError("cold/warm standard result identity diverged")
    if (
        cold.simulation_run["shading_result"]["physical_result_sha256"]
        != warm.simulation_run["shading_result"]["physical_result_sha256"]
    ):
        raise AssertionError("cold/warm shading physical identity diverged")

    return {
        "case": "R4_short_exact_cache",
        "cold_seconds": cold_seconds,
        "warm_seconds": warm_seconds,
        "cold_static_cache_miss_count": cold_accel["static_cache_miss_count"],
        "cold_static_cache_hit_count": cold_accel["static_cache_hit_count"],
        "warm_static_cache_miss_count": warm_accel["static_cache_miss_count"],
        "warm_static_cache_hit_count": warm_accel["static_cache_hit_count"],
        "standard_logical_sha256": cold.simulation_run["result_reference"][
            "logical_content_sha256"
        ],
        "shading_physical_result_sha256": cold.simulation_run["shading_result"][
            "physical_result_sha256"
        ],
        "physical_parity": True,
    }


def _annual_r1_save_reload_reproducibility():
    phase59 = _phase59()
    phase49c = phase59._modules()[0]
    phase55, ref, project, weather, config = phase59._annual_context("R1")

    config = deepcopy(config)
    config["simulation_configuration_id"] = "simcfg-phase511-r1-annual-exact"
    config["shading_configuration"]["cache_policy"] = {"mode": "exact"}

    scene_sha = canonical_object_sha256(ref["scene"])
    config_sha = canonical_object_sha256(config)
    geometry_sha = compile_shading_geometry(ref["scene"])[
        "geometry_payload_sha256"
    ]

    with TemporaryDirectory(prefix="opensimpv-phase511-r1-") as directory:
        output = Path(directory)
        clear_global_exact_shading_cache()
        before, before_seconds = phase59._run(
            phase55,
            ref,
            project,
            weather,
            config,
            output,
            "phase511-r1-before-save",
        )

        saved = persist_design_state_package(
            output / "saved-design",
            scene=ref["scene"],
            electrical_design=ref["electrical"],
            project_revision=project,
            simulation_configuration=config,
            design_validation_report=ref["validation"],
        )
        loaded = load_design_state_package(saved)

        loaded_ref = deepcopy(ref)
        loaded_ref["scene"] = loaded.scene
        loaded_ref["electrical"] = loaded.electrical_design
        loaded_ref["validation"] = loaded.design_validation_report

        if canonical_object_sha256(loaded.scene) != scene_sha:
            raise AssertionError("annual R1 Scene hash changed after save/reload")
        if canonical_object_sha256(loaded.simulation_configuration) != config_sha:
            raise AssertionError("annual R1 configuration identity changed")
        if (
            compile_shading_geometry(loaded.scene)["geometry_payload_sha256"]
            != geometry_sha
        ):
            raise AssertionError("annual R1 compiled geometry hash changed")

        clear_global_exact_shading_cache()
        after, after_seconds = phase59._run(
            phase55,
            loaded_ref,
            loaded.project_revision,
            weather,
            loaded.simulation_configuration,
            output,
            "phase511-r1-after-reload",
        )

    before_identity = phase59._identity(before)
    after_identity = phase59._identity(after)

    for field in (
        "input_hash",
        "standard_logical_sha256",
        "receiver_physical_sha256",
        "shading_result_id",
        "shading_physical_result_sha256",
    ):
        if before_identity[field] != after_identity[field]:
            raise AssertionError(f"annual R1 reproducibility drift: {field}")

    before_energy = float(before.summary_result["annual_energy_wh"])
    after_energy = float(after.summary_result["annual_energy_wh"])
    energy_delta = after_energy - before_energy
    if abs(energy_delta) > 1e-6:
        raise AssertionError(
            f"annual R1 energy changed after save/reload: {energy_delta} Wh"
        )

    return {
        "case": "R1_annual_save_reload_compile_shade_run",
        "scene_sha256": scene_sha,
        "compiled_geometry_sha256": geometry_sha,
        "configuration_sha256": config_sha,
        "before_seconds": before_seconds,
        "after_seconds": after_seconds,
        "before_identity": before_identity,
        "after_identity": after_identity,
        "annual_energy_wh": before_energy,
        "annual_energy_delta_wh": energy_delta,
        "deterministic_tolerance_wh": 1e-6,
        "pass": True,
    }


def _annual_r4_runtime():
    phase59 = _phase59()
    phase55, ref, project, weather, config = phase59._annual_context("R4")
    config = deepcopy(config)
    config["simulation_configuration_id"] = "simcfg-phase511-r4-annual-exact"
    config["shading_configuration"]["cache_policy"] = {"mode": "exact"}

    rss_before_bytes, rss_before_raw, rss_raw_unit = _max_rss_bytes()
    with TemporaryDirectory(prefix="opensimpv-phase511-r4-") as directory:
        clear_global_exact_shading_cache()
        result, seconds = phase59._run(
            phase55,
            ref,
            project,
            weather,
            config,
            Path(directory),
            "phase511-r4-annual",
        )
    rss_after_bytes, rss_after_raw, _ = _max_rss_bytes()

    receiver = result.simulation_run["shading_receiver_factor_reference"]
    if receiver["row_count"] != 216 * 8760:
        raise AssertionError("R4 annual receiver-factor scale changed")
    if result.summary_result["shading_energy_loss_wh"] is None:
        raise AssertionError("R4 annual geometric shading loss is missing")

    return {
        "case": "R4_annual_geometry_aware_runtime",
        "elapsed_seconds": seconds,
        "receiver_factor_rows": receiver["row_count"],
        "annual_energy_wh": result.summary_result["annual_energy_wh"],
        "shading_energy_loss_wh": result.summary_result[
            "shading_energy_loss_wh"
        ],
        "rss_max_before_bytes": rss_before_bytes,
        "rss_max_after_bytes": rss_after_bytes,
        "rss_growth_bytes": (
            rss_after_bytes - rss_before_bytes
            if rss_before_bytes is not None and rss_after_bytes is not None
            else None
        ),
        "rss_max_before_raw": rss_before_raw,
        "rss_max_after_raw": rss_after_raw,
        "rss_raw_unit": rss_raw_unit,
        "rss_measurement": (
            "resource.ru_maxrss process high-water mark; normalized to bytes "
            "where the platform contract is known; evidence only"
        ),
        "identity": phase59._identity(result),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip full annual closure runs; retain geometry/cache evidence.",
    )
    args = parser.parse_args()

    results = {
        "benchmark_id": "opensimpv.phase511.closure_hardening.v0.1",
        "quick": bool(args.quick),
        "timing_is_acceptance_gate": False,
        "memory_is_acceptance_gate": False,
        "universal_hardware_target_frozen": False,
        "environment": _benchmark_environment(),
        "geometry_costs": _measure_geometry_costs(quick=bool(args.quick)),
        "cache_behavior": _measure_cache_behavior(),
        "annual_reproducibility": None,
        "annual_shading_runtime": None,
    }

    if not args.quick:
        results["annual_reproducibility"] = _annual_r1_save_reload_reproducibility()
        results["annual_shading_runtime"] = _annual_r4_runtime()

    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
