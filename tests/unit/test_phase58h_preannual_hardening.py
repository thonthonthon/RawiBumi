import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.simulation.artifacts import (
    ReceiverFactorParquetSink,
    dataframe_logical_sha256,
    persist_receiver_factor_result,
)
from geometry.shading import (
    ExactStaticShadingCache,
    ShadingAccelerationError,
    ShadingContractError,
    assert_shading_result_storage_consistency,
    build_shading_acceleration_context,
    clear_global_exact_shading_cache,
    evaluate_beam_shading_snapshot,
)


ROOT = Path(__file__).resolve().parents[2]


def _load_phase57():
    path = ROOT / "tests/unit/test_phase57_ground_vertical_slice.py"
    spec = importlib.util.spec_from_file_location(
        "_rawibumi_phase57_for_phase58h",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_phase54():
    path = ROOT / "tests/unit/test_phase54_beam_shading_snapshots.py"
    spec = importlib.util.spec_from_file_location(
        "_rawibumi_phase54_for_phase58h",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _r4_ground_context(case_id):
    phase57 = _load_phase57()
    phase56 = phase57._load_phase56_module()
    phase55 = phase56._load_phase55_module()
    phase49c = phase55._load_phase49c_reference_module()
    ref = phase49c._reference("R4")
    project, weather, _, beam_config = phase55._rebind_project_and_configs(
        ref,
        case_id,
    )
    sky_config = phase56._sky_config(beam_config, f"{case_id}-sky")
    ground_config = phase57._ground_config(
        sky_config,
        f"{case_id}-ground",
    )
    return phase55, ref, project, weather, ground_config


def _assert_numeric_frames_equal(left, right):
    assert list(left.columns) == list(right.columns)
    assert left.index.equals(right.index)
    for column in left.columns:
        a = left[column]
        b = right[column]
        if pd.api.types.is_numeric_dtype(a.dtype):
            assert np.allclose(
                a.to_numpy(dtype=float),
                b.to_numpy(dtype=float),
                rtol=0.0,
                atol=0.0,
                equal_nan=True,
            ), column
        else:
            assert a.equals(b), column


def _factor_physics(frame):
    identity_columns = {
        "shading_result_id",
        "sky_shading_result_id",
        "ground_shading_result_id",
    }
    return frame[
        [column for column in frame.columns if column not in identity_columns]
    ].copy()


def _factor_fixture():
    index = pd.date_range("2026-01-01T00:00:00Z", periods=4, freq="h")
    return pd.DataFrame(
        {
            "interval_start": [
                index[0],
                index[0],
                index[1],
                index[1],
            ],
            "evaluation_time": [
                index[0] + pd.Timedelta(minutes=30),
                index[0] + pd.Timedelta(minutes=30),
                index[1] + pd.Timedelta(minutes=30),
                index[1] + pd.Timedelta(minutes=30),
            ],
            "receiver_id": ["r1", "r2", "r1", "r2"],
            "receiver_area_m2": [2.0, 2.0, 2.0, 2.0],
            "beam_visibility_factor": [1.0, 0.5, 0.75, 1.0],
            "quality_flags_json": ["[]", "[]", "[]", "[]"],
            "shading_result_id": ["s1", "s1", "s2", "s2"],
            "sky_visibility_factor": [0.9, 0.8, 0.9, 0.8],
            "ground_visibility_factor": [1.0, 0.95, 1.0, 0.95],
        }
    )


def test_phase58h_streaming_receiver_factor_sink_preserves_logical_content(tmp_path):
    frame = _factor_fixture()

    conventional = persist_receiver_factor_result(
        frame,
        output_directory=tmp_path,
        simulation_run_id="in-memory",
    )

    sink = ReceiverFactorParquetSink(
        output_directory=tmp_path,
        simulation_run_id="streamed",
    )
    sink.write(frame.iloc[:2])
    sink.write(frame.iloc[2:])
    streamed = sink.finalize()

    assert streamed["row_count"] == conventional["row_count"] == 4
    assert streamed["columns"] == conventional["columns"]
    assert streamed["logical_content_sha256"] == conventional[
        "logical_content_sha256"
    ]
    assert streamed["logical_content_sha256"] == dataframe_logical_sha256(
        frame.sort_values(
            ["interval_start", "receiver_id"],
            kind="stable",
        ).reset_index(drop=True)
    )
    assert sink.max_chunk_rows == 2
    assert sink.chunk_count == 2


@pytest.mark.parametrize(
    "value,match",
    [
        (
            {
                "storage_mode": "inline",
                "record_count": 2,
                "inline_records": [{}],
            },
            "record_count",
        ),
        (
            {
                "storage_mode": "inline",
                "record_count": 1,
                "inline_records": [{}],
                "dataset_reference": {"row_count": 1},
            },
            "dataset_reference",
        ),
        (
            {
                "storage_mode": "dataset_reference",
                "record_count": 2,
                "dataset_reference": {"row_count": 1},
            },
            "record_count",
        ),
        (
            {
                "storage_mode": "dataset_reference",
                "record_count": 1,
                "inline_records": [{}],
                "dataset_reference": {"row_count": 1},
            },
            "inline_records",
        ),
    ],
)
def test_phase58h_shading_result_storage_invariants_fail_closed(value, match):
    with pytest.raises(ShadingContractError, match=match):
        assert_shading_result_storage_consistency(value)


def test_phase58h_below_horizon_snapshot_queries_one_receiver_only(monkeypatch):
    phase54 = _load_phase54()

    compiled = phase54._compiled()
    config = phase54._configuration()
    config["cache_policy"] = {"mode": "none"}

    import geometry.shading.snapshot as snapshot_module

    original = snapshot_module.calculate_direct_beam_shadow
    calls = []

    def counted(*args, **kwargs):
        calls.append(kwargs["receiver_id"])
        return original(*args, **kwargs)

    monkeypatch.setattr(
        snapshot_module,
        "calculate_direct_beam_shadow",
        counted,
    )

    result = evaluate_beam_shading_snapshot(
        compiled,
        shading_configuration=config,
        sun_vector_xyz=(0.0, 0.0, -1.0),
        receiver_ids=["receiver:module:m1", "receiver:module:m2"],
    ).shading_result

    assert calls == ["receiver:module:m1"]
    assert result["record_count"] == 2
    assert {
        item["beam_visibility_factor"]
        for item in result["inline_records"]
    } == {1.0}
    resolution = result["solver_manifest"]["beam"]["resolution"]
    assert resolution["global_below_horizon_short_circuit"] is True
    assert resolution["receiver_geometry_query_count"] == 1


def test_phase58h_cache_identity_uses_full_execution_plan_hash():
    phase57 = _load_phase57()
    phase56 = phase57._load_phase56_module()
    phase55 = phase56._load_phase55_module()
    phase49c = phase55._load_phase49c_reference_module()
    ref = phase49c._reference("R1")

    from geometry.shading import compile_shading_geometry

    compiled = compile_shading_geometry(ref["scene"])
    config = {
        "beam_method": "opensimpv.beam_shadow.polygon_projection",
        "diffuse_method": "opensimpv.sky_visibility.weighted_dome",
        "albedo_method": "opensimpv.ground_visibility.weighted_dome",
        "fidelity_level": "engineering",
        "geometry_contract_version": "0.1",
        "coordinate_basis": "scene_local_east_north_up_m",
        "sun_vector_convention": "receiver_to_sun",
        "factor_convention": "visibility_one_clear_zero_blocked",
        "receiver_granularity": "module",
        "self_shading_enabled": False,
        "sun_position_resolution_seconds": None,
        "electrical_shading_method": None,
        "cache_policy": {"mode": "exact"},
        "geometric_resolution": {
            "receiver_subdivision_u": 1,
            "receiver_subdivision_v": 1,
        },
        "sky_dome_resolution": {
            "azimuth_sectors": 8,
            "elevation_bands": 4,
            "horizon_azimuth_sectors": 8,
            "horizon_elevation_bands": 2,
            "horizon_band_elevation_deg": 15.0,
        },
        "ground_dome_resolution": {
            "azimuth_sectors": 8,
            "depression_bands": 4,
        },
        "model_options": {},
    }

    receiver_id = sorted(
        item["receiver_id"]
        for item in compiled["receivers"]
        if item["source_entity_type"] == "module_instance"
    )[0]
    store = ExactStaticShadingCache(max_entries=4)

    first = build_shading_acceleration_context(
        compiled,
        shading_configuration=config,
        receiver_ids=[receiver_id],
        source_execution_plan_id="execution-plan:same-short-id",
        source_execution_plan_payload_sha256="1" * 64,
        static_store=store,
    )
    payload = {
        "source_scene_revision_id": first.source_scene_revision_id,
        "compiled_geometry_hash": first.compiled_geometry_hash,
        "shading_configuration_hash": first.shading_configuration_hash,
        "receiver_set_sha256": first.receiver_set_sha256,
        "result_payload_sha256": "2" * 64,
        "source_execution_plan_id": first.source_execution_plan_id,
        "channels": ["sky_visibility", "directional_diffuse_visibility"],
        "storage_mode": "inline",
        "record_count": 1,
        "inline_records": [{"receiver_id": receiver_id}],
    }
    first.put_static_result("sky_visibility", payload)

    second = build_shading_acceleration_context(
        compiled,
        shading_configuration=config,
        receiver_ids=[receiver_id],
        source_execution_plan_id="execution-plan:same-short-id",
        source_execution_plan_payload_sha256="3" * 64,
        static_store=store,
    )
    assert second.get_static_result("sky_visibility") is None


def test_phase58h_static_cache_hit_revalidates_payload_provenance():
    from geometry.shading import compile_shading_geometry

    phase57 = _load_phase57()
    phase56 = phase57._load_phase56_module()
    phase55 = phase56._load_phase55_module()
    phase49c = phase55._load_phase49c_reference_module()
    ref = phase49c._reference("R1")
    compiled = compile_shading_geometry(ref["scene"])
    receiver_id = sorted(
        item["receiver_id"]
        for item in compiled["receivers"]
        if item["source_entity_type"] == "module_instance"
    )[0]
    config = {
        "fidelity_level": "engineering",
        "self_shading_enabled": False,
        "cache_policy": {"mode": "exact"},
    }
    store = ExactStaticShadingCache(max_entries=4)
    context = build_shading_acceleration_context(
        compiled,
        shading_configuration=config,
        receiver_ids=[receiver_id],
        source_execution_plan_id="execution-plan:cache-hit-test",
        source_execution_plan_payload_sha256="4" * 64,
        static_store=store,
    )

    poisoned = {
        "source_scene_revision_id": "wrong-scene",
        "compiled_geometry_hash": context.compiled_geometry_hash,
        "shading_configuration_hash": context.shading_configuration_hash,
        "receiver_set_sha256": context.receiver_set_sha256,
        "result_payload_sha256": "5" * 64,
        "source_execution_plan_id": context.source_execution_plan_id,
        "channels": ["sky_visibility", "directional_diffuse_visibility"],
        "storage_mode": "inline",
        "record_count": 1,
        "inline_records": [{"receiver_id": receiver_id}],
    }
    store.put(context._static_key("sky_visibility"), poisoned)

    with pytest.raises(ShadingAccelerationError, match="source_scene_revision_id"):
        context.get_static_result("sky_visibility")


def test_phase58h_full_channel_reference_and_exact_are_physically_identical(tmp_path):
    phase55, ref, project, weather, config = _r4_ground_context(
        "r4-phase58h-parity"
    )

    exact_config = deepcopy(config)
    exact_config["simulation_configuration_id"] = "simcfg-phase58h-full-exact"
    exact_config["shading_configuration"]["cache_policy"] = {"mode": "exact"}

    reference_config = deepcopy(exact_config)
    reference_config["simulation_configuration_id"] = "simcfg-phase58h-full-none"
    reference_config["shading_configuration"]["cache_policy"] = {"mode": "none"}

    clear_global_exact_shading_cache()
    reference = phase55._run(
        ref,
        project,
        weather,
        reference_config,
        tmp_path,
        "phase58h-full-none",
    )
    exact = phase55._run(
        ref,
        project,
        weather,
        exact_config,
        tmp_path,
        "phase58h-full-exact",
    )

    assert reference.backend_result is not None
    assert exact.backend_result is not None
    _assert_numeric_frames_equal(
        reference.standard_timeseries,
        exact.standard_timeseries,
    )
    _assert_numeric_frames_equal(
        _factor_physics(reference.backend_result.shading_receiver_factors),
        _factor_physics(exact.backend_result.shading_receiver_factors),
    )
    assert reference.summary_result["total_energy_wh"] == exact.summary_result[
        "total_energy_wh"
    ]


def test_phase58h_exact_cold_and_warm_runs_have_same_model_provenance(tmp_path):
    phase55, ref, project, weather, config = _r4_ground_context(
        "r4-phase58h-cold-warm"
    )
    config = deepcopy(config)
    config["simulation_configuration_id"] = "simcfg-phase58h-cold-warm"
    config["shading_configuration"]["cache_policy"] = {"mode": "exact"}

    clear_global_exact_shading_cache()
    cold = phase55._run(
        ref,
        project,
        weather,
        config,
        tmp_path,
        "phase58h-cold",
    )
    warm = phase55._run(
        ref,
        project,
        weather,
        config,
        tmp_path,
        "phase58h-warm",
    )

    assert cold.simulation_run["model_manifest"] == warm.simulation_run[
        "model_manifest"
    ]
    assert cold.simulation_run["reproducibility_manifest"]["model_manifest"] == (
        warm.simulation_run["reproducibility_manifest"]["model_manifest"]
    )
    assert cold.simulation_run["input_hash"] == warm.simulation_run["input_hash"]
    assert cold.simulation_run["result_reference"]["logical_content_sha256"] == (
        warm.simulation_run["result_reference"]["logical_content_sha256"]
    )
    assert cold.simulation_run[
        "shading_receiver_factor_reference"
    ]["logical_content_sha256"] == warm.simulation_run[
        "shading_receiver_factor_reference"
    ]["logical_content_sha256"]

    cold_accel = cold.simulation_run["execution_telemetry"][
        "shading_acceleration"
    ]
    warm_accel = warm.simulation_run["execution_telemetry"][
        "shading_acceleration"
    ]
    assert cold_accel["static_cache_miss_count"] == 2
    assert cold_accel["static_cache_hit_count"] == 0
    assert warm_accel["static_cache_hit_count"] == 2
    assert warm_accel["static_cache_miss_count"] == 0


def test_phase58h_forced_streaming_matches_in_memory_canonical_factor_hash(
    tmp_path,
    monkeypatch,
):
    phase55, ref, project, weather, config = _r4_ground_context(
        "r4-phase58h-streaming"
    )
    config = deepcopy(config)
    config["simulation_configuration_id"] = "simcfg-phase58h-streaming"
    config["shading_configuration"]["cache_policy"] = {"mode": "exact"}

    import engine.simulation.canonical as canonical_module

    clear_global_exact_shading_cache()
    monkeypatch.setattr(
        canonical_module,
        "RECEIVER_FACTOR_STREAMING_ROW_THRESHOLD",
        10**9,
    )
    retained = phase55._run(
        ref,
        project,
        weather,
        config,
        tmp_path,
        "phase58h-retained",
    )
    retained_reference = retained.simulation_run[
        "shading_receiver_factor_reference"
    ]
    retained_hash = retained_reference["logical_content_sha256"]
    retained_physical_hash = retained_reference["physical_content_sha256"]

    clear_global_exact_shading_cache()
    monkeypatch.setattr(
        canonical_module,
        "RECEIVER_FACTOR_STREAMING_ROW_THRESHOLD",
        1,
    )
    streamed = phase55._run(
        ref,
        project,
        weather,
        config,
        tmp_path,
        "phase58h-streamed",
    )

    assert streamed.backend_result is not None
    assert streamed.backend_result.shading_receiver_factors is None
    streamed_reference = streamed.simulation_run[
        "shading_receiver_factor_reference"
    ]
    assert streamed_reference["logical_content_sha256"] == retained_hash
    assert (
        streamed_reference["physical_content_sha256"]
        == retained_physical_hash
    )
    assert streamed_reference["row_count"] == 216 * 3

    telemetry = streamed.simulation_run["execution_telemetry"][
        "receiver_factor_persistence"
    ]
    assert telemetry["streaming_enabled"] is True
    assert telemetry["row_count"] == 216 * 3
    assert telemetry["max_chunk_rows"] <= (
        canonical_module.RECEIVER_FACTOR_STREAMING_CHUNK_ROWS + 215
    )
