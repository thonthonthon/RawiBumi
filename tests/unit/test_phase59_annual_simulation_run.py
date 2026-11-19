import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from engine.simulation.artifacts import verify_run_package
from geometry.shading import clear_global_exact_shading_cache


ROOT = Path(__file__).resolve().parents[2]


def _load_phase58h():
    path = ROOT / "tests/unit/test_phase58h_preannual_hardening.py"
    spec = importlib.util.spec_from_file_location(
        "_rawibumi_phase58h_for_phase59",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _r4_context(case_id: str):
    phase58h = _load_phase58h()
    return (*phase58h._r4_ground_context(case_id), phase58h)


def test_phase59_simulationrun_owns_one_authoritative_shading_dataset(tmp_path):
    phase55, ref, project, weather, config, _ = _r4_context(
        "r4-phase59-artifact"
    )
    config = deepcopy(config)
    config["simulation_configuration_id"] = "simcfg-phase59-artifact"
    config["shading_configuration"]["cache_policy"] = {"mode": "exact"}

    clear_global_exact_shading_cache()
    result = phase55._run(
        ref,
        project,
        weather,
        config,
        tmp_path,
        "phase59-artifact",
    )

    shading_result = result.simulation_run["shading_result"]
    receiver_reference = result.simulation_run[
        "shading_receiver_factor_reference"
    ]

    assert shading_result["storage_mode"] == "dataset_reference"
    assert shading_result["dataset_reference"] == receiver_reference
    assert shading_result["record_count"] == receiver_reference["row_count"]
    assert receiver_reference["physical_content_sha256"]
    assert shading_result["physical_result_sha256"]
    assert shading_result["shading_result_id"] == (
        "shading-result:" + shading_result["physical_result_sha256"][:16]
    )

    persisted = json.loads(
        (result.artifact_directory / "shading-result.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted == shading_result

    manifest = verify_run_package(result.artifact_directory)
    roles = {item["role"] for item in manifest["artifacts"]}
    assert {
        "simulation_run",
        "summary_result",
        "reproducibility_manifest",
        "validation_findings",
        "model_resolution",
        "shading_result",
        "standard_timeseries",
        "shading_receiver_factors",
    }.issubset(roles)


def test_phase59_none_and_exact_keep_execution_identity_distinct_but_share_physics(
    tmp_path,
):
    phase55, ref, project, weather, config, phase58h = _r4_context(
        "r4-phase59-none-exact"
    )

    exact_config = deepcopy(config)
    exact_config["simulation_configuration_id"] = "simcfg-phase59-exact"
    exact_config["shading_configuration"]["cache_policy"] = {"mode": "exact"}

    reference_config = deepcopy(exact_config)
    reference_config["simulation_configuration_id"] = "simcfg-phase59-none"
    reference_config["shading_configuration"]["cache_policy"] = {"mode": "none"}

    clear_global_exact_shading_cache()
    reference = phase55._run(
        ref,
        project,
        weather,
        reference_config,
        tmp_path,
        "phase59-none",
    )
    exact = phase55._run(
        ref,
        project,
        weather,
        exact_config,
        tmp_path,
        "phase59-exact",
    )

    phase58h._assert_numeric_frames_equal(
        reference.standard_timeseries,
        exact.standard_timeseries,
    )
    assert reference.simulation_run["input_hash"] != exact.simulation_run[
        "input_hash"
    ]
    assert (
        reference.simulation_run["result_reference"]["logical_content_sha256"]
        == exact.simulation_run["result_reference"]["logical_content_sha256"]
    )

    ref_receiver = reference.simulation_run[
        "shading_receiver_factor_reference"
    ]
    exact_receiver = exact.simulation_run[
        "shading_receiver_factor_reference"
    ]
    assert (
        ref_receiver["physical_content_sha256"]
        == exact_receiver["physical_content_sha256"]
    )
    # Full logical rows retain execution/config-derived snapshot IDs.
    assert (
        ref_receiver["logical_content_sha256"]
        != exact_receiver["logical_content_sha256"]
    )

    ref_shading = reference.simulation_run["shading_result"]
    exact_shading = exact.simulation_run["shading_result"]
    assert (
        ref_shading["physical_result_sha256"]
        == exact_shading["physical_result_sha256"]
    )
    assert ref_shading["shading_result_id"] == exact_shading["shading_result_id"]
    assert (
        ref_shading["shading_configuration_hash"]
        != exact_shading["shading_configuration_hash"]
    )


def test_phase59_cold_and_warm_exact_packages_share_scientific_results(tmp_path):
    phase55, ref, project, weather, config, _ = _r4_context(
        "r4-phase59-cold-warm"
    )
    config = deepcopy(config)
    config["simulation_configuration_id"] = "simcfg-phase59-cold-warm"
    config["shading_configuration"]["cache_policy"] = {"mode": "exact"}

    clear_global_exact_shading_cache()
    cold = phase55._run(
        ref,
        project,
        weather,
        config,
        tmp_path,
        "phase59-cold",
    )
    warm = phase55._run(
        ref,
        project,
        weather,
        config,
        tmp_path,
        "phase59-warm",
    )

    verify_run_package(cold.artifact_directory)
    verify_run_package(warm.artifact_directory)

    assert cold.simulation_run["input_hash"] == warm.simulation_run["input_hash"]
    assert (
        cold.simulation_run["result_reference"]["logical_content_sha256"]
        == warm.simulation_run["result_reference"]["logical_content_sha256"]
    )
    assert (
        cold.simulation_run["shading_receiver_factor_reference"][
            "logical_content_sha256"
        ]
        == warm.simulation_run["shading_receiver_factor_reference"][
            "logical_content_sha256"
        ]
    )
    assert (
        cold.simulation_run["shading_result"]["physical_result_sha256"]
        == warm.simulation_run["shading_result"]["physical_result_sha256"]
    )

    cold_summary = deepcopy(cold.summary_result)
    warm_summary = deepcopy(warm.summary_result)
    cold_summary.pop("simulation_run_id")
    warm_summary.pop("simulation_run_id")
    assert cold_summary == warm_summary

    cold_accel = cold.simulation_run["execution_telemetry"][
        "shading_acceleration"
    ]
    warm_accel = warm.simulation_run["execution_telemetry"][
        "shading_acceleration"
    ]
    assert cold_accel["static_cache_miss_count"] > 0
    assert warm_accel["static_cache_hit_count"] > 0


def test_phase59_run_package_verification_fails_closed_after_tamper(tmp_path):
    phase55, ref, project, weather, config, _ = _r4_context(
        "r4-phase59-package-tamper"
    )
    config = deepcopy(config)
    config["simulation_configuration_id"] = "simcfg-phase59-package-tamper"

    result = phase55._run(
        ref,
        project,
        weather,
        config,
        tmp_path,
        "phase59-package-tamper",
    )
    verify_run_package(result.artifact_directory)

    summary_path = result.artifact_directory / "summary-result.json"
    value = json.loads(summary_path.read_text(encoding="utf-8"))
    value["total_energy_wh"] += 1.0
    summary_path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        verify_run_package(result.artifact_directory)
