import importlib.util
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.irradiance import (
    PlaneOfArrayResult,
    apply_ground_visibility_to_poa,
)
from engine.simulation import GROUND_VISIBILITY_AGGREGATION_METHOD_ID
from geometry.shading import GROUND_VISIBILITY_SOLVER_ID


ROOT = Path(__file__).resolve().parents[2]


def _load_phase56_module():
    path = ROOT / "tests/unit/test_phase56_diffuse_vertical_slice.py"
    spec = importlib.util.spec_from_file_location(
        "_rawibumi_phase56_for_phase57",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ground_config(sky_config, case_id):
    config = deepcopy(sky_config)
    config["simulation_configuration_id"] = f"simcfg-phase57-{case_id}"
    shading = deepcopy(config["shading_configuration"])
    shading["albedo_method"] = GROUND_VISIBILITY_SOLVER_ID
    shading["ground_dome_resolution"] = {
        "azimuth_sectors": 16,
        "depression_bands": 8,
    }
    config["shading_configuration"] = shading
    return config


def test_phase57_ground_poa_modifier_changes_ground_only_and_reconciles():
    index = pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="h")
    frame = pd.DataFrame(
        {
            "evaluation_time": index + pd.Timedelta(minutes=30),
            "aoi_deg": [20.0, 30.0],
            "solar_elevation_deg": [50.0, 40.0],
            "dni_extra_w_m2": [1400.0, 1400.0],
            "relative_airmass": [1.2, 1.4],
            "poa_beam_w_m2": [300.0, 400.0],
            "poa_sky_diffuse_w_m2": [120.0, 100.0],
            "poa_ground_diffuse_w_m2": [20.0, 10.0],
            "poa_diffuse_w_m2": [140.0, 110.0],
            "poa_global_w_m2": [440.0, 510.0],
            "poa_isotropic_shaded_w_m2": [60.0, 50.0],
            "poa_circumsolar_shaded_w_m2": [40.0, 30.0],
            "poa_horizon_shaded_w_m2": [20.0, 20.0],
            "pvsyst_low_sun_cutoff_applied": [False, False],
        },
        index=index,
    )
    source = PlaneOfArrayResult(
        frame=frame,
        metadata={"model_id": "test", "unshaded": False},
    )

    shaded = apply_ground_visibility_to_poa(
        source,
        pd.Series([0.5, 1.0], index=index),
        aggregation_method_id=GROUND_VISIBILITY_AGGREGATION_METHOD_ID,
    )

    assert shaded.frame["poa_ground_diffuse_w_m2"].tolist() == [10.0, 10.0]
    assert shaded.frame["near_shading_ground_diffuse_loss_w_m2"].tolist() == [
        10.0,
        0.0,
    ]
    assert shaded.frame["poa_global_w_m2"].tolist() == [430.0, 510.0]

    for column in (
        "poa_beam_w_m2",
        "poa_sky_diffuse_w_m2",
        "poa_isotropic_shaded_w_m2",
        "poa_circumsolar_shaded_w_m2",
        "poa_horizon_shaded_w_m2",
    ):
        assert np.array_equal(
            shaded.frame[column].to_numpy(),
            source.frame[column].to_numpy(),
        )

    assert np.allclose(
        shaded.frame["poa_beam_w_m2"]
        + shaded.frame["poa_sky_diffuse_w_m2"]
        + shaded.frame["poa_ground_diffuse_w_m2"],
        shaded.frame["poa_global_w_m2"],
        rtol=0.0,
        atol=1e-12,
    )


def test_phase57_r1_open_ground_path_matches_phase56_numerically(tmp_path):
    phase56 = _load_phase56_module()
    phase55 = phase56._load_phase55_module()
    phase49c = phase55._load_phase49c_reference_module()
    ref = phase49c._reference("R1")

    project, weather, _, beam_config = phase55._rebind_project_and_configs(
        ref,
        "r1-phase57",
    )
    sky_config = phase56._sky_config(beam_config, "r1-phase57-sky")
    ground_config = _ground_config(sky_config, "r1-ground")

    sky = phase55._run(
        ref, project, weather, sky_config, tmp_path, "phase57-r1-sky"
    )
    ground = phase55._run(
        ref, project, weather, ground_config, tmp_path, "phase57-r1-ground"
    )

    assert sky.backend_result is not None
    assert ground.backend_result is not None
    ts_sky = sky.standard_timeseries
    ts_ground = ground.standard_timeseries

    assert (ts_ground["ground_visibility_factor_group"] == 1.0).all()
    assert (ts_ground["near_shading_ground_diffuse_loss_w_m2"] == 0.0).all()

    for column in (
        "beam_visibility_factor_group",
        "poa_beam_w_m2",
        "sky_visibility_factor_group",
        "circumsolar_visibility_factor_group",
        "horizon_visibility_factor_group",
        "poa_isotropic_shaded_w_m2",
        "poa_circumsolar_shaded_w_m2",
        "poa_horizon_shaded_w_m2",
        "poa_sky_diffuse_w_m2",
        "poa_ground_diffuse_w_m2",
        "poa_global_w_m2",
        "effective_irradiance_w_m2",
        "pcc_power_w",
    ):
        assert np.allclose(
            ts_ground[column],
            ts_sky[column],
            rtol=0.0,
            atol=1e-9 if column != "pcc_power_w" else 1e-7,
        )

    assert ground.simulation_run["model_manifest"]["execution_scope"] == (
        "fixed_tilt_beam_sky_ground_shaded_homogeneous_single_inverter.v0.1"
    )
    assumption_ids = {
        item["assumption_id"]
        for item in ground.simulation_run["assumptions"]
    }
    assert "phase57_uniform_ground_view_geometry_approximation" in assumption_ids


def test_phase57_r4_ground_channel_preserves_phase56_beam_and_sky(tmp_path):
    phase56 = _load_phase56_module()
    phase55 = phase56._load_phase55_module()
    phase49c = phase55._load_phase49c_reference_module()
    ref = phase49c._reference("R4")

    project, weather, _, beam_config = phase55._rebind_project_and_configs(
        ref,
        "r4-phase57",
    )
    sky_config = phase56._sky_config(beam_config, "r4-phase57-sky")
    ground_config = _ground_config(sky_config, "r4-ground")

    sky = phase55._run(
        ref, project, weather, sky_config, tmp_path, "phase57-r4-sky"
    )
    ground = phase55._run(
        ref, project, weather, ground_config, tmp_path, "phase57-r4-ground"
    )

    assert sky.backend_result is not None
    assert ground.backend_result is not None
    ts_sky = sky.standard_timeseries
    ts_ground = ground.standard_timeseries

    for column in (
        "beam_visibility_factor_group",
        "poa_beam_unshaded_w_m2",
        "poa_beam_shaded_w_m2",
        "near_shading_beam_loss_w_m2",
        "poa_beam_w_m2",
        "sky_visibility_factor_group",
        "circumsolar_visibility_factor_group",
        "horizon_visibility_factor_group",
        "poa_isotropic_shaded_w_m2",
        "poa_circumsolar_shaded_w_m2",
        "poa_horizon_shaded_w_m2",
        "poa_sky_diffuse_w_m2",
    ):
        assert np.allclose(
            ts_ground[column],
            ts_sky[column],
            rtol=0.0,
            atol=1e-12,
        )

    assert (ts_ground["ground_visibility_factor_group"] >= 0.0).all()
    assert (ts_ground["ground_visibility_factor_group"] <= 1.0).all()
    assert np.allclose(
        ts_ground["poa_ground_diffuse_unshaded_w_m2"],
        ts_sky["poa_ground_diffuse_w_m2"],
        rtol=0.0,
        atol=0.0,
    )
    assert np.all(
        ts_ground["poa_ground_diffuse_shaded_w_m2"].to_numpy(dtype=float)
        <= ts_ground["poa_ground_diffuse_unshaded_w_m2"].to_numpy(dtype=float)
        + 1e-12
    )
    assert np.allclose(
        ts_ground["poa_beam_w_m2"]
        + ts_ground["poa_sky_diffuse_w_m2"]
        + ts_ground["poa_ground_diffuse_w_m2"],
        ts_ground["poa_global_w_m2"],
        rtol=0.0,
        atol=1e-8,
    )

    assert (
        ground.summary_result["total_energy_wh"]
        <= sky.summary_result["total_energy_wh"] + 1e-9
    )

    factors = ground.backend_result.shading_receiver_factors
    assert factors is not None
    assert len(factors) == 216 * 3
    assert "ground_visibility_factor" in factors.columns
    assert (factors["ground_visibility_factor"] >= 0.0).all()
    assert (factors["ground_visibility_factor"] <= 1.0).all()

    runtime = ground.simulation_run["model_manifest"]["near_shading_runtime"]
    assert runtime["ground_visibility_solver_id"] == GROUND_VISIBILITY_SOLVER_ID
    assert runtime["ground_aggregation_method_id"] == (
        GROUND_VISIBILITY_AGGREGATION_METHOD_ID
    )
    assert runtime["ground_source_model"] == (
        "existing_uniform_lambertian_scalar_albedo_poa_component"
    )
