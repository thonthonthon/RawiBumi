import importlib.util
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pvlib
import pytest

from engine.irradiance import PlaneOfArrayResult, apply_beam_visibility_to_poa
from engine.simulation import (
    BEAM_VISIBILITY_AGGREGATION_METHOD_ID,
    build_design_revision_store,
    run_validated_design_simulation,
)
from geometry.shading import (
    BEAM_SOLVER_ID,
    COORDINATE_BASIS,
    FACTOR_CONVENTION,
    SUN_VECTOR_CONVENTION,
)
from weather.core import build_time_semantics, build_weather_dataset


ROOT = Path(__file__).resolve().parents[2]


def _load_phase49c_reference_module():
    path = ROOT / "tests/unit/test_phase49c_reference_projects.py"
    spec = importlib.util.spec_from_file_location(
        "_rawibumi_phase49c_reference_for_phase55",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _beam_weather(project_id: str):
    index = pd.DatetimeIndex(
        [
            "2026-06-21T08:00:00+07:00",
            "2026-06-21T09:00:00+07:00",
            "2026-06-21T10:00:00+07:00",
        ]
    )
    evaluation = index + pd.Timedelta(minutes=30)
    latitude = -6.4245
    longitude = 106.8307
    elevation = 82.0
    temperature = 30.0
    pressure = 100500.0

    solar = pvlib.solarposition.spa_python(
        evaluation,
        latitude=latitude,
        longitude=longitude,
        altitude=elevation,
        pressure=pressure,
        temperature=temperature,
        how="numpy",
        numthreads=1,
    )
    cos_zenith = np.maximum(
        np.cos(np.radians(solar["apparent_zenith"].to_numpy(dtype=float))),
        0.0,
    )
    dni = np.array([720.0, 780.0, 820.0], dtype=float)
    dhi = np.array([110.0, 120.0, 130.0], dtype=float)
    ghi = dni * cos_zenith + dhi

    series = pd.DataFrame(
        {
            "ghi_w_m2": ghi,
            "dni_w_m2": dni,
            "dhi_w_m2": dhi,
            "ambient_temperature_c": [temperature] * len(index),
            "wind_speed_m_s": [1.0, 1.0, 1.0],
            "pressure_pa": [pressure] * len(index),
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
        weather_dataset_id=f"wx-{project_id}-beam",
        revision_id=f"wx-{project_id}-beam-r1",
        name=f"{project_id} Phase 5.5 beam-bearing test weather",
        site_id=f"site-{project_id}",
        timezone="UTC+07:00",
        native_resolution_seconds=3600,
        source_format="synthetic_phase55_beam_integration",
        source_timestamp_convention="interval_start",
        location={
            "latitude_deg": latitude,
            "longitude_deg": longitude,
            "elevation_m": elevation,
        },
        native_series_origin="opensimpv_derived",
        series_origin="opensimpv_derived",
        upstream_generation={
            "provider": "RawiBumi test fixture",
            "synthetic": True,
            "base_resolution_seconds": 3600,
            "method": "phase55_beam_vertical_slice_fixture",
            "evidence": "opensimpv_transformation",
            "evidence_detail": (
                "Synthetic beam-bearing weather used only to validate Phase 5.5 "
                "geometry-aware beam propagation."
            ),
        },
        time_semantics=semantics,
    )


def _rebind_project_and_configs(ref, case_id: str):
    phase49c = _load_phase49c_reference_module()
    weather = _beam_weather(case_id)
    project_revision_id = ref["project_revision"]["project_revision_id"]
    project_revision = phase49c.build_project_revision_from_design(
        ref["scene"],
        ref["electrical"],
        project_revision_id=project_revision_id,
        revision_number=1,
        weather_dataset_revision_id=weather.dataset["revision_id"],
        change_summary=f"Phase 5.5 {case_id} beam-bearing project revision.",
    )

    unshaded = deepcopy(ref["configuration"])
    unshaded["simulation_configuration_id"] = f"simcfg-phase55-{case_id}-unshaded"
    unshaded["weather_dataset_revision_id"] = weather.dataset["revision_id"]
    unshaded["shading_configuration"] = {
        "beam_method": "none",
        "diffuse_method": "none",
        "albedo_method": "support_surface",
        "fidelity_level": "engineering",
        "sun_position_resolution_seconds": None,
        "electrical_shading_method": None,
    }

    shaded = deepcopy(unshaded)
    shaded["simulation_configuration_id"] = f"simcfg-phase55-{case_id}-beam"
    shaded["shading_configuration"] = {
        "beam_method": BEAM_SOLVER_ID,
        "diffuse_method": "none",
        "albedo_method": "none",
        "fidelity_level": "engineering",
        "sun_position_resolution_seconds": None,
        "electrical_shading_method": None,
        "geometry_contract_version": "0.1",
        "coordinate_basis": COORDINATE_BASIS,
        "sun_vector_convention": SUN_VECTOR_CONVENTION,
        "factor_convention": FACTOR_CONVENTION,
        "receiver_granularity": "module",
        "self_shading_enabled": False,
        "cache_policy": {"mode": "exact"},
        "geometric_resolution": {
            "receiver_subdivision_u": 1,
            "receiver_subdivision_v": 1,
        },
        "model_options": {},
    }
    return project_revision, weather, unshaded, shaded


def _run(ref, project_revision, weather, configuration, tmp_path, suffix):
    store = build_design_revision_store(
        ref["scene"],
        ref["electrical"],
        weather,
        ref["components"],
    )
    return run_validated_design_simulation(
        project_revision,
        configuration,
        revision_store=store,
        design_validation_report=ref["validation"],
        output_directory=tmp_path / suffix,
        simulation_run_id=f"run-phase55-{suffix}",
        engine_version="rawibumi-test@phase55",
        executed_at="2026-09-24T09:00:00Z",
    )


def test_phase55_beam_poa_modifier_changes_beam_only_and_reconciles():
    index = pd.date_range("2026-01-01T00:00:00Z", periods=2, freq="h")
    frame = pd.DataFrame(
        {
            "evaluation_time": index + pd.Timedelta(minutes=30),
            "aoi_deg": [20.0, 30.0],
            "solar_elevation_deg": [50.0, 40.0],
            "dni_extra_w_m2": [1400.0, 1400.0],
            "relative_airmass": [1.2, 1.4],
            "poa_beam_w_m2": [600.0, 400.0],
            "poa_sky_diffuse_w_m2": [120.0, 100.0],
            "poa_ground_diffuse_w_m2": [20.0, 10.0],
            "poa_diffuse_w_m2": [140.0, 110.0],
            "poa_global_w_m2": [740.0, 510.0],
            "poa_isotropic_w_m2": [120.0, 100.0],
            "poa_circumsolar_w_m2": [0.0, 0.0],
            "poa_horizon_w_m2": [0.0, 0.0],
            "pvsyst_low_sun_cutoff_applied": [False, False],
        },
        index=index,
    )
    source = PlaneOfArrayResult(
        frame=frame,
        metadata={"model_id": "test", "unshaded": True},
    )

    shaded = apply_beam_visibility_to_poa(
        source,
        pd.Series([0.5, 1.0], index=index),
        aggregation_method_id=BEAM_VISIBILITY_AGGREGATION_METHOD_ID,
    )

    assert shaded.frame["poa_beam_w_m2"].tolist() == pytest.approx([300.0, 400.0])
    assert shaded.frame["near_shading_beam_loss_w_m2"].tolist() == pytest.approx(
        [300.0, 0.0]
    )
    assert shaded.frame["poa_global_w_m2"].tolist() == pytest.approx([440.0, 510.0])
    pd.testing.assert_series_equal(
        shaded.frame["poa_sky_diffuse_w_m2"],
        source.frame["poa_sky_diffuse_w_m2"],
    )
    pd.testing.assert_series_equal(
        shaded.frame["poa_ground_diffuse_w_m2"],
        source.frame["poa_ground_diffuse_w_m2"],
    )


def test_phase55_clear_r1_geometry_path_matches_unshaded_numerically(tmp_path):
    phase49c = _load_phase49c_reference_module()
    ref = phase49c._reference("R1")
    project, weather, unshaded_cfg, shaded_cfg = _rebind_project_and_configs(
        ref, "r1"
    )

    base = _run(
        ref, project, weather, unshaded_cfg, tmp_path, "r1-unshaded"
    )
    shaded = _run(
        ref, project, weather, shaded_cfg, tmp_path, "r1-beam"
    )

    assert base.simulation_run["status"] in {"completed", "completed_with_warnings"}
    assert shaded.simulation_run["status"] == "completed_with_warnings"
    assert shaded.backend_result is not None
    assert shaded.backend_result.shading_receiver_factors is not None
    assert len(shaded.backend_result.shading_receiver_factors) == 54

    ts = shaded.standard_timeseries
    assert (ts["beam_visibility_factor_group"] == 1.0).all()
    assert (ts["near_shading_beam_loss_w_m2"] == 0.0).all()
    assert np.allclose(
        ts["poa_beam_unshaded_w_m2"],
        base.standard_timeseries["poa_beam_w_m2"],
        rtol=0.0,
        atol=1e-10,
    )
    assert np.allclose(
        ts["poa_beam_w_m2"],
        base.standard_timeseries["poa_beam_w_m2"],
        rtol=0.0,
        atol=1e-10,
    )
    assert np.allclose(
        ts["effective_irradiance_w_m2"],
        base.standard_timeseries["effective_irradiance_w_m2"],
        rtol=0.0,
        atol=1e-9,
    )
    assert np.allclose(
        ts["pcc_power_w"],
        base.standard_timeseries["pcc_power_w"],
        rtol=0.0,
        atol=1e-7,
    )

    reference = shaded.simulation_run["shading_receiver_factor_reference"]
    assert reference is not None
    assert reference["row_count"] == 54
    assert (
        shaded.simulation_run["reproducibility_manifest"][
            "shading_receiver_factor_reference"
        ]["logical_content_sha256"]
        == reference["logical_content_sha256"]
    )
    assert shaded.summary_result["shading_energy_loss_wh"] is None
    assert base.summary_result["shading_energy_loss_wh"] == 0.0


def test_phase55_r4_beam_loss_propagates_through_existing_electrical_chain(tmp_path):
    phase49c = _load_phase49c_reference_module()
    ref = phase49c._reference("R4")
    project, weather, unshaded_cfg, shaded_cfg = _rebind_project_and_configs(
        ref, "r4"
    )

    base = _run(
        ref, project, weather, unshaded_cfg, tmp_path, "r4-unshaded"
    )
    shaded = _run(
        ref, project, weather, shaded_cfg, tmp_path, "r4-beam"
    )

    assert base.simulation_run["status"] in {"completed", "completed_with_warnings"}
    assert shaded.simulation_run["status"] == "completed_with_warnings"
    assert shaded.backend_result is not None
    factors = shaded.backend_result.shading_receiver_factors
    assert factors is not None
    assert len(factors) == 216 * 3

    ts = shaded.standard_timeseries
    base_ts = base.standard_timeseries

    assert (ts["beam_visibility_factor_group"] <= 1.0).all()
    assert (ts["beam_visibility_factor_group"] < 1.0).any()
    assert (ts["near_shading_beam_loss_w_m2"] > 0.0).any()
    assert np.allclose(
        ts["poa_beam_unshaded_w_m2"],
        base_ts["poa_beam_w_m2"],
        rtol=0.0,
        atol=1e-9,
    )
    assert np.allclose(
        ts["poa_sky_diffuse_w_m2"],
        base_ts["poa_sky_diffuse_w_m2"],
        rtol=0.0,
        atol=0.0,
    )
    assert np.allclose(
        ts["poa_ground_diffuse_w_m2"],
        base_ts["poa_ground_diffuse_w_m2"],
        rtol=0.0,
        atol=0.0,
    )
    assert np.allclose(
        ts["poa_beam_shaded_w_m2"]
        + ts["near_shading_beam_loss_w_m2"],
        ts["poa_beam_unshaded_w_m2"],
        rtol=0.0,
        atol=1e-9,
    )
    assert np.allclose(
        ts["poa_beam_w_m2"]
        + ts["poa_sky_diffuse_w_m2"]
        + ts["poa_ground_diffuse_w_m2"],
        ts["poa_global_w_m2"],
        rtol=0.0,
        atol=1e-8,
    )

    # Verify the persisted group factor is the documented area-weighted mean of
    # the separately preserved module receiver factors.
    for interval_start, subset in factors.groupby("interval_start", sort=True):
        weighted = np.average(
            subset["beam_visibility_factor"].to_numpy(dtype=float),
            weights=subset["receiver_area_m2"].to_numpy(dtype=float),
        )
        assert ts.loc[interval_start, "beam_visibility_factor_group"] == pytest.approx(
            weighted,
            abs=1e-12,
        )

    assert (
        shaded.summary_result["total_energy_wh"]
        < base.summary_result["total_energy_wh"]
    )
    assert shaded.summary_result["shading_energy_loss_wh"] is None

    manifest = shaded.simulation_run["model_manifest"]
    runtime = manifest["near_shading_runtime"]
    assert runtime["aggregation_method_id"] == (
        BEAM_VISIBILITY_AGGREGATION_METHOD_ID
    )
    assert runtime["electrical_shading_scope"] == "not_modeled"
    assert manifest["execution_scope"] == (
        "fixed_tilt_beam_shaded_homogeneous_single_inverter.v0.1"
    )
    approximation_ids = {
        item["assumption_id"]
        for item in shaded.simulation_run["assumptions"]
    }
    assert (
        "phase55_beam_visibility_area_weighted_electrical_approximation"
        in approximation_ids
    )

    receiver_ref = shaded.simulation_run["shading_receiver_factor_reference"]
    assert receiver_ref is not None
    assert receiver_ref["row_count"] == 648
    assert receiver_ref["logical_content_sha256"] == manifest[
        "shading_receiver_factor_logical_content_sha256"
    ]


def test_phase55_historical_r4_external_reference_is_not_reinterpreted(tmp_path):
    phase49c = _load_phase49c_reference_module()
    ref = phase49c._reference("R4")
    store = build_design_revision_store(
        ref["scene"],
        ref["electrical"],
        ref["weather"],
        ref["components"],
    )
    result = run_validated_design_simulation(
        ref["project_revision"],
        ref["configuration"],
        revision_store=store,
        design_validation_report=ref["validation"],
        output_directory=tmp_path / "historical-r4",
        simulation_run_id="run-phase55-historical-r4",
        engine_version="rawibumi-test@phase55",
        executed_at="2026-09-24T09:00:00Z",
    )
    assert result.simulation_run["status"] == "failed"
    rules = {
        item["rule_id"]
        for item in result.simulation_run["validation_findings"]
    }
    assert "SIMULATION_SCOPE_UNSHADED_ONLY" in rules
