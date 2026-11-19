import importlib.util
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.irradiance import (
    PlaneOfArrayResult,
    SIGNED_HORIZON_POLICY,
    apply_sky_diffuse_visibility_to_poa,
)
from engine.simulation import (
    DIFFUSE_VISIBILITY_AGGREGATION_METHOD_ID,
)
from geometry.shading import SKY_VISIBILITY_SOLVER_ID


ROOT = Path(__file__).resolve().parents[2]


def _load_phase55_module():
    path = ROOT / "tests/unit/test_phase55_beam_vertical_slice.py"
    spec = importlib.util.spec_from_file_location(
        "_rawibumi_phase55_for_phase56",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sky_config(beam_config, case_id):
    config = deepcopy(beam_config)
    config["simulation_configuration_id"] = f"simcfg-phase56-{case_id}-beam-sky"
    shading = deepcopy(config["shading_configuration"])
    shading["diffuse_method"] = SKY_VISIBILITY_SOLVER_ID
    shading["sky_dome_resolution"] = {
        "azimuth_sectors": 16,
        "elevation_bands": 4,
        "horizon_azimuth_sectors": 16,
        "horizon_elevation_bands": 2,
        "horizon_band_elevation_deg": 15.0,
    }
    config["shading_configuration"] = shading
    return config


def test_phase56_component_diffuse_modifier_reconciles_without_changing_beam_or_ground():
    index = pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="h")
    frame = pd.DataFrame(
        {
            "evaluation_time": index + pd.Timedelta(minutes=30),
            "aoi_deg": [20.0, 20.0],
            "solar_elevation_deg": [45.0, 45.0],
            "dni_extra_w_m2": [1400.0, 1400.0],
            "relative_airmass": [1.2, 1.2],
            "poa_beam_w_m2": [300.0, 300.0],
            "poa_sky_diffuse_w_m2": [120.0, 110.0],
            "poa_ground_diffuse_w_m2": [10.0, 10.0],
            "poa_diffuse_w_m2": [130.0, 120.0],
            "poa_global_w_m2": [430.0, 420.0],
            "poa_isotropic_w_m2": [60.0, 100.0],
            "poa_circumsolar_w_m2": [40.0, 20.0],
            "poa_horizon_w_m2": [20.0, -10.0],
            "pvsyst_low_sun_cutoff_applied": [False, False],
        },
        index=index,
    )
    source = PlaneOfArrayResult(
        frame=frame,
        metadata={"model_id": "test", "unshaded": True},
    )

    shaded = apply_sky_diffuse_visibility_to_poa(
        source,
        sky_visibility_factor=pd.Series([0.5, 1.0], index=index),
        circumsolar_visibility_factor=pd.Series([0.25, 1.0], index=index),
        horizon_visibility_factor=pd.Series([0.75, 0.5], index=index),
        aggregation_method_id=DIFFUSE_VISIBILITY_AGGREGATION_METHOD_ID,
    )

    assert shaded.frame["poa_beam_w_m2"].tolist() == [300.0, 300.0]
    assert shaded.frame["poa_ground_diffuse_w_m2"].tolist() == [10.0, 10.0]

    # Interval 1: 60*0.5 + 40*0.25 + 20*0.75 = 55 W/m2.
    assert shaded.frame.iloc[0]["poa_sky_diffuse_w_m2"] == pytest.approx(55.0)
    assert shaded.frame.iloc[0]["poa_global_w_m2"] == pytest.approx(365.0)
    assert shaded.frame.iloc[0]["near_shading_sky_diffuse_loss_w_m2"] == pytest.approx(
        65.0
    )

    # Interval 2 deliberately uses a negative Perez horizon correction.
    # Linear scaling -10*0.5 -> -5 makes total sky 115 rather than clamping
    # or pretending the horizon term is positive radiance.
    assert shaded.frame.iloc[1]["poa_horizon_shaded_w_m2"] == pytest.approx(-5.0)
    assert shaded.frame.iloc[1]["near_shading_horizon_delta_w_m2"] == pytest.approx(
        -5.0
    )
    assert shaded.frame.iloc[1]["poa_sky_diffuse_w_m2"] == pytest.approx(115.0)
    assert shaded.frame.iloc[1]["near_shading_sky_diffuse_loss_w_m2"] == pytest.approx(
        -5.0
    )
    assert shaded.metadata["horizon_obstruction_policy"] == SIGNED_HORIZON_POLICY

    assert np.allclose(
        shaded.frame["poa_isotropic_w_m2"]
        + shaded.frame["poa_circumsolar_w_m2"]
        + shaded.frame["poa_horizon_w_m2"],
        shaded.frame["poa_sky_diffuse_w_m2"],
        rtol=0.0,
        atol=1e-12,
    )
    assert np.allclose(
        shaded.frame["poa_beam_w_m2"]
        + shaded.frame["poa_sky_diffuse_w_m2"]
        + shaded.frame["poa_ground_diffuse_w_m2"],
        shaded.frame["poa_global_w_m2"],
        rtol=0.0,
        atol=1e-12,
    )


def test_phase56_r1_open_sky_path_matches_phase55_beam_only(tmp_path):
    phase55 = _load_phase55_module()
    phase49c = phase55._load_phase49c_reference_module()
    ref = phase49c._reference("R1")
    project, weather, _, beam_config = phase55._rebind_project_and_configs(
        ref,
        "r1-phase56",
    )
    sky_config = _sky_config(beam_config, "r1")

    beam = phase55._run(
        ref,
        project,
        weather,
        beam_config,
        tmp_path,
        "phase56-r1-beam",
    )
    sky = phase55._run(
        ref,
        project,
        weather,
        sky_config,
        tmp_path,
        "phase56-r1-sky",
    )

    assert beam.backend_result is not None
    assert sky.backend_result is not None
    ts_beam = beam.standard_timeseries
    ts_sky = sky.standard_timeseries

    assert (ts_sky["sky_visibility_factor_group"] == 1.0).all()
    assert (ts_sky["horizon_visibility_factor_group"] == 1.0).all()
    assert (ts_sky["circumsolar_visibility_factor_group"] == 1.0).all()
    assert (ts_sky["near_shading_sky_diffuse_loss_w_m2"] == 0.0).all()

    # Phase-5.6 must not perturb any Phase-5.5 beam channel.
    for column in (
        "beam_visibility_factor_group",
        "poa_beam_unshaded_w_m2",
        "poa_beam_shaded_w_m2",
        "near_shading_beam_loss_w_m2",
        "poa_beam_w_m2",
    ):
        assert np.allclose(
            ts_sky[column],
            ts_beam[column],
            rtol=0.0,
            atol=1e-12,
        )

    assert np.allclose(
        ts_sky["poa_ground_diffuse_w_m2"],
        ts_beam["poa_ground_diffuse_w_m2"],
        rtol=0.0,
        atol=0.0,
    )
    assert np.allclose(
        ts_sky["effective_irradiance_w_m2"],
        ts_beam["effective_irradiance_w_m2"],
        rtol=0.0,
        atol=1e-9,
    )
    assert np.allclose(
        ts_sky["pcc_power_w"],
        ts_beam["pcc_power_w"],
        rtol=0.0,
        atol=1e-7,
    )

    factors = sky.backend_result.shading_receiver_factors
    assert factors is not None
    assert len(factors) == 18 * 3
    assert set(
        (
            "sky_visibility_factor",
            "circumsolar_visibility_factor",
            "horizon_visibility_factor",
        )
    ).issubset(factors.columns)
    assert (factors["sky_visibility_factor"] == 1.0).all()

    assert sky.simulation_run["model_manifest"]["execution_scope"] == (
        "fixed_tilt_beam_sky_shaded_homogeneous_single_inverter.v0.1"
    )


def test_phase56_r4_diffuse_obstruction_is_independent_of_phase55_beam(tmp_path):
    phase55 = _load_phase55_module()
    phase49c = phase55._load_phase49c_reference_module()
    ref = phase49c._reference("R4")
    project, weather, _, beam_config = phase55._rebind_project_and_configs(
        ref,
        "r4-phase56",
    )
    sky_config = _sky_config(beam_config, "r4")

    beam = phase55._run(
        ref,
        project,
        weather,
        beam_config,
        tmp_path,
        "phase56-r4-beam",
    )
    sky = phase55._run(
        ref,
        project,
        weather,
        sky_config,
        tmp_path,
        "phase56-r4-sky",
    )

    assert beam.backend_result is not None
    assert sky.backend_result is not None
    ts_beam = beam.standard_timeseries
    ts_sky = sky.standard_timeseries

    # Existing direct-beam geometry is unchanged by enabling sky diffuse.
    for column in (
        "beam_visibility_factor_group",
        "poa_beam_unshaded_w_m2",
        "poa_beam_shaded_w_m2",
        "near_shading_beam_loss_w_m2",
        "poa_beam_w_m2",
    ):
        assert np.allclose(
            ts_sky[column],
            ts_beam[column],
            rtol=0.0,
            atol=1e-12,
        )

    # Ground obstruction is Phase 5.7 and therefore still exactly unchanged.
    assert np.allclose(
        ts_sky["poa_ground_diffuse_w_m2"],
        ts_beam["poa_ground_diffuse_w_m2"],
        rtol=0.0,
        atol=0.0,
    )

    assert (ts_sky["sky_visibility_factor_group"] <= 1.0).all()
    assert (ts_sky["horizon_visibility_factor_group"] <= 1.0).all()
    assert (
        (ts_sky["sky_visibility_factor_group"] < 1.0).any()
        or (ts_sky["horizon_visibility_factor_group"] < 1.0).any()
    )

    # Sky subcomponents reconcile after obstruction.
    assert np.allclose(
        ts_sky["poa_isotropic_shaded_w_m2"]
        + ts_sky["poa_circumsolar_shaded_w_m2"]
        + ts_sky["poa_horizon_shaded_w_m2"],
        ts_sky["poa_sky_diffuse_shaded_w_m2"],
        rtol=0.0,
        atol=1e-8,
    )
    assert np.allclose(
        ts_sky["poa_beam_w_m2"]
        + ts_sky["poa_sky_diffuse_w_m2"]
        + ts_sky["poa_ground_diffuse_w_m2"],
        ts_sky["poa_global_w_m2"],
        rtol=0.0,
        atol=1e-8,
    )

    # Circumsolar obstruction is directional and must exactly reuse the
    # Phase-5.5 beam group visibility.
    assert np.allclose(
        ts_sky["circumsolar_visibility_factor_group"],
        ts_sky["beam_visibility_factor_group"],
        rtol=0.0,
        atol=0.0,
    )

    # At least one positive component loss must exist. Horizon itself may carry
    # a signed Perez correction, so it is not constrained non-negative.
    assert (
        (ts_sky["near_shading_isotropic_loss_w_m2"] > 0.0).any()
        or (ts_sky["near_shading_circumsolar_loss_w_m2"] > 0.0).any()
    )

    assert (
        sky.summary_result["total_energy_wh"]
        <= beam.summary_result["total_energy_wh"] + 1e-9
    )

    factors = sky.backend_result.shading_receiver_factors
    assert factors is not None
    assert len(factors) == 216 * 3
    assert (factors["sky_visibility_factor"] <= 1.0).all()
    assert (
        (factors["sky_visibility_factor"] < 1.0).any()
        or (factors["horizon_visibility_factor"] < 1.0).any()
    )

    runtime = sky.simulation_run["model_manifest"]["near_shading_runtime"]
    assert runtime["sky_visibility_solver_id"] == SKY_VISIBILITY_SOLVER_ID
    assert runtime["diffuse_aggregation_method_id"] == (
        DIFFUSE_VISIBILITY_AGGREGATION_METHOD_ID
    )
    assert runtime["horizon_signed_component_policy"] == SIGNED_HORIZON_POLICY

    assumption_ids = {
        item["assumption_id"]
        for item in sky.simulation_run["assumptions"]
    }
    assert "phase55_beam_visibility_area_weighted_electrical_approximation" in (
        assumption_ids
    )
    assert "phase56_component_diffuse_geometry_approximation" in assumption_ids
