import importlib.util
from copy import deepcopy
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


def _load_phase55():
    path = ROOT / "tests/unit/test_phase55_beam_vertical_slice.py"
    spec = importlib.util.spec_from_file_location("_opensimpv_phase55_for_phase58", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase58_r4_reference_none_and_prepared_exact_are_numerically_identical(tmp_path):
    phase55 = _load_phase55()
    phase49c = phase55._load_phase49c_reference_module()
    ref = phase49c._reference("R4")
    project, weather, _, exact_config = phase55._rebind_project_and_configs(
        ref,
        "r4-phase58",
    )

    exact_config = deepcopy(exact_config)
    exact_config["simulation_configuration_id"] = "simcfg-phase58-r4-exact"
    exact_config["shading_configuration"]["cache_policy"] = {"mode": "exact"}

    reference_config = deepcopy(exact_config)
    reference_config["simulation_configuration_id"] = "simcfg-phase58-r4-reference"
    reference_config["shading_configuration"]["cache_policy"] = {"mode": "none"}

    reference = phase55._run(
        ref,
        project,
        weather,
        reference_config,
        tmp_path,
        "phase58-r4-reference",
    )
    exact = phase55._run(
        ref,
        project,
        weather,
        exact_config,
        tmp_path,
        "phase58-r4-exact",
    )

    assert reference.backend_result is not None
    assert exact.backend_result is not None
    assert reference.simulation_run["status"] == "completed_with_warnings"
    assert exact.simulation_run["status"] == "completed_with_warnings"

    reference_ts = reference.standard_timeseries
    exact_ts = exact.standard_timeseries
    assert list(reference_ts.columns) == list(exact_ts.columns)
    assert reference_ts.index.equals(exact_ts.index)

    for column in reference_ts.columns:
        if column == "timestamp":
            assert reference_ts[column].equals(exact_ts[column])
            continue
        a = reference_ts[column].to_numpy()
        b = exact_ts[column].to_numpy()
        if np.issubdtype(a.dtype, np.number):
            assert np.allclose(a, b, rtol=0.0, atol=0.0, equal_nan=True), column
        else:
            assert reference_ts[column].equals(exact_ts[column]), column

    reference_factors = reference.backend_result.shading_receiver_factors
    exact_factors = exact.backend_result.shading_receiver_factors
    assert reference_factors is not None
    assert exact_factors is not None
    assert reference_factors["interval_start"].equals(
        exact_factors["interval_start"]
    )
    assert reference_factors["receiver_id"].equals(exact_factors["receiver_id"])
    assert np.allclose(
        reference_factors["beam_visibility_factor"].to_numpy(dtype=float),
        exact_factors["beam_visibility_factor"].to_numpy(dtype=float),
        rtol=0.0,
        atol=0.0,
    )

    reference_runtime = reference.simulation_run["model_manifest"][
        "near_shading_runtime"
    ]
    exact_runtime = exact.simulation_run["model_manifest"]["near_shading_runtime"]

    assert reference_runtime["shading_acceleration"]["cache_mode"] == "none"
    assert reference_runtime["shading_cache_manifest"]["entry_count"] == 0

    assert exact_runtime["shading_acceleration"]["cache_mode"] == "exact"
    assert exact_runtime["shading_acceleration"]["exact_physics"] is True
    assert exact_runtime["shading_acceleration"]["angular_quantization"] is False
    assert exact_runtime["shading_cache_manifest"]["cache_policy"] == {
        "mode": "exact"
    }

    reference_telemetry = reference.simulation_run["execution_telemetry"][
        "shading_acceleration"
    ]
    exact_telemetry = exact.simulation_run["execution_telemetry"][
        "shading_acceleration"
    ]
    assert reference_telemetry["prepared_receiver_count"] == 0
    assert exact_telemetry["prepared_receiver_count"] == 216
    assert exact_telemetry["prepared_query_build_count"] == 216

    assert reference.summary_result["total_energy_wh"] == exact.summary_result[
        "total_energy_wh"
    ]


def test_phase58_non_null_sun_position_resolution_fails_closed(tmp_path):
    phase55 = _load_phase55()
    phase49c = phase55._load_phase49c_reference_module()
    ref = phase49c._reference("R1")
    project, weather, _, config = phase55._rebind_project_and_configs(
        ref,
        "r1-phase58-sampling",
    )
    config = deepcopy(config)
    config["simulation_configuration_id"] = "simcfg-phase58-sun-coarsening"
    config["shading_configuration"]["sun_position_resolution_seconds"] = 1800

    result = phase55._run(
        ref,
        project,
        weather,
        config,
        tmp_path,
        "phase58-sun-coarsening",
    )
    assert result.simulation_run["status"] == "failed"
    assert result.backend_result is None
    rules = {
        item["rule_id"]
        for item in result.simulation_run["validation_findings"]
    }
    assert "SIMULATION_SCOPE_SUN_POSITION_RESOLUTION_NOT_EXECUTABLE" in rules
