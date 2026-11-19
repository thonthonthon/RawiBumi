"""Versioned Stage 1 fixtures; no production physics is implemented here."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from math import sin, pi
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

VERSION = "phase610-stage1-fixtures-v1"
CASES = ("B0", "B1", "B2", "B3")


def build_fixture(case):
    from tests.integration.test_phase69a_detailed_backend import _canonical_fixture, REF
    from weather.core import build_time_semantics, build_weather_dataset
    if case not in CASES:
        raise ValueError(f"unknown case: {case}")
    project, config, store, scene, design = _canonical_fixture()
    config["output_configuration"]["detailed_diagnostics"] = False
    config.setdefault("numerical_options", {}).setdefault("module_overrides", {})["module_quality_loss_fraction"] = 0.0
    original = next(iter(store.weather_revisions.values()))
    weather = original.copy()
    if case == "B0":
        weather.series = weather.series.iloc[:1].copy()
        weather.series.index = pd.DatetimeIndex(["2026-10-01T11:00:00+07:00"])
        weather.series[["ghi_w_m2", "dni_w_m2", "dhi_w_m2"]] = [1000., 1000., 0.]
    elif case == "B1":
        weather.series = weather.series.iloc[:1].copy()
    else:
        cadence = 3600 if case == "B2" else 900
        index = pd.date_range("2026-03-21T00:00:00+07:00", periods=86400 // cadence,
                              freq=pd.Timedelta(seconds=cadence))
        values = []
        for start in index:
            midpoint = start + pd.Timedelta(seconds=cadence / 2)
            hour = midpoint.hour + midpoint.minute / 60
            values.append(600 * sin(pi * (hour - 8) / 8) if 8 < hour < 16 else 0.)
        frame = pd.DataFrame({"ghi_w_m2": values, "dhi_w_m2": values, "dni_w_m2": 0.,
            "ambient_temperature_c": 30., "wind_speed_m_s": 1., "pressure_pa": 100500.}, index=index)
        weather = build_weather_dataset(frame, weather_dataset_id=original.dataset["weather_dataset_id"],
            revision_id=original.dataset["revision_id"], name=f"Phase 6.10 {case} synthetic diffuse day",
            site_id=original.dataset["site_id"], timezone="UTC+07:00", native_resolution_seconds=cadence,
            source_format="synthetic_test", source_timestamp_convention="interval_start",
            location=deepcopy(original.dataset["location"]), native_series_origin="measured",
            series_origin="measured", time_semantics=build_time_semantics(canonical_timezone="UTC+07:00",
                source_timestamp_convention="interval_start", native_interval_seconds=cadence,
                current_interval_seconds=cadence, source_timezone="UTC+07:00", source_utc_offset_hours=7.))
        config["simulation_timestep_seconds"] = cadence
    cadence = config["simulation_timestep_seconds"]
    weather.dataset["start_time"] = weather.series.index[0].isoformat()
    weather.dataset["end_time"] = (weather.series.index[-1] + pd.Timedelta(seconds=cadence)).isoformat()
    config["start_time"], config["end_time"] = weather.dataset["start_time"], weather.dataset["end_time"]
    store = replace(store, weather_revisions={weather.dataset["revision_id"]: weather})
    return {"case": case, "project": project, "configuration": config, "store": store,
            "scene": scene, "design": design, "weather": weather, "REF": REF}


def prepare_physical(fixture):
    from engine.simulation.detailed_dispatch import _prepare_backend
    from engine.optical import IAM_NONE
    f = fixture
    args = _prepare_backend(f["configuration"], f["store"], f["scene"], f["design"], [],
                            "phase610-" + f["case"], f["project"]["project_revision_id"], "2026-10-04T00:00:00Z")
    if f["case"] == "B0":
        ref = f["REF"]
        clear = ref["_four_module_geometry"]()
        region_map, _, _ = ref["_module_handoff"](clear, ref["_topology"](), ref["MODULE_A_WEAK"])
        geometry = deepcopy(clear)
        geometry["source_scene_revision_id"] = "phase68-four-module-scene-r2"
        geometry["geometry_payload_sha256"] = "a" * 64  # Historical controlled fixture identity.
        geometry["occluders"] = [ref["_occluder_over_region"](ref["_mapped_region"](region_map, "s1-r1"))]
        args["compiled_geometry"] = geometry
        args["shading_configuration"] = deepcopy(args["shading_configuration"])
        args["shading_configuration"]["sky_dome_resolution"] = {"azimuth_sectors": 4, "elevation_bands": 1,
            "horizon_azimuth_sectors": 4, "horizon_elevation_bands": 1, "horizon_band_elevation_deg": 10.}
        args["shading_configuration"]["ground_dome_resolution"] = {"azimuth_sectors": 4, "depression_bands": 1}
        args["module_configs"] = {m: replace(c, iam_model_id=IAM_NONE) for m, c in args["module_configs"].items()}
    return args


@contextmanager
def boundary_overrides(case):
    if case != "B0":
        yield
        return
    import engine.simulation.detailed_backend as backend
    from engine.solar import SolarPositionResult
    original = backend.solar_position_from_weather
    def vertical(*args, **kwargs):
        result = original(*args, **kwargs)
        frame = result.frame.copy()
        for column in ("solar_zenith_deg", "solar_apparent_zenith_deg", "solar_azimuth_deg"):
            frame[column] = 0.
        for column in ("solar_elevation_deg", "solar_apparent_elevation_deg"):
            frame[column] = 90.
        frame["evaluation_time"] = [pd.Timestamp("2026-10-01T12:00:00+07:00")]
        return SolarPositionResult(frame, result.metadata)
    def temperature(poa, optical, weather, **kwargs):
        return SimpleNamespace(thermal=SimpleNamespace(frame=pd.DataFrame(
            {"cell_temperature_c": [25.]}, index=poa.frame.index)),
            metadata={"converged": True, "fixture_override": "phase68c_fixed_25c_boundary_isolation"})
    with patch.object(backend, "solar_position_from_weather", vertical), \
         patch.object(backend, "sun_vector_from_azimuth_elevation", lambda *args: [0., 0., 1.]), \
         patch.object(backend, "solve_pvsyst_module_thermal_coupling", temperature):
        yield


def fixture_identity(fixture, args):
    from engine.simulation.artifacts import canonical_object_sha256, weather_series_logical_sha256
    from engine.simulation.detailed_backend import resolved_numerical_policy
    f = fixture
    payload = {"version": VERSION, "case": f["case"], "configuration": f["configuration"],
        "scene": f["scene"], "design": f["design"], "weather_dataset": f["weather"].dataset,
        "weather_logical_sha256": weather_series_logical_sha256(f["weather"].series),
        "compiled_geometry": args["compiled_geometry"],
        "module_inputs": {k: v.scientific_input_sha256 for k, v in args["module_inputs"].items()},
        "policy": resolved_numerical_policy(args["shading_configuration"]),
        "controlled_overrides": ["vertical_sun", "IAM_NONE", "fixed_25C"] if f["case"] == "B0" else [],
        "synthetic_weather": True}
    return {"version": VERSION, "sha256": canonical_object_sha256(payload), "case": f["case"],
        "interval_count": len(f["weather"].series), "cadence_seconds": f["configuration"]["simulation_timestep_seconds"],
        "weather_logical_sha256": payload["weather_logical_sha256"], "weather_dataset": f["weather"].dataset,
        "numerical_policy": payload["policy"], "sample_count": payload["policy"]["string_sample_count"],
        "topology_hashes": {k: canonical_object_sha256(v.replay()["topology"]) for k, v in args["module_inputs"].items()},
        "module_input_hashes": payload["module_inputs"], "geometry_content_sha256": canonical_object_sha256(args["compiled_geometry"]),
        "design_sha256": canonical_object_sha256(f["design"]), "controlled_overrides": payload["controlled_overrides"]}


def assert_b0_direct(numerical, fixture, args):
    """Preserve the historical direct-kernel assertions outside measurement."""
    from shading.electrical import (build_phase66_series_module_operating_model,
        assemble_general_series_string_iv, assemble_parallel_mppt_iv, select_mppt_operating_point)
    ref = fixture["REF"]
    interval = numerical.replay()["intervals"][0]
    topology = ref["_topology"]()
    definition = ref["_parameterization"](topology)
    evidence = ref["_evidence"](definition)
    models = {}
    for module_id, diagnostic in interval["modules"].items():
        region_map, visibility, local = ref["_module_handoff"](args["compiled_geometry"], topology, module_id)
        assert diagnostic["region_map"] == region_map
        assert diagnostic["visibility"] == visibility
        assert diagnostic["local_irradiance"]["regions"] == local["regions"]
        assert diagnostic["local_irradiance"]["module_temperature_c"] == local["module_temperature_c"]
        models[module_id] = build_phase66_series_module_operating_model(topology, region_map, local, definition, evidence)
    curves = {}
    for string in fixture["design"]["strings"]:
        result = assemble_general_series_string_iv(string, {m: models[m] for m in string["module_instance_ids"]}, sample_count=101)
        assert result.curve["points"] == interval["strings"][string["string_id"]]["curve"]["points"]
        curves[string["string_id"]] = result.curve
    mppt = fixture["design"]["mppt_instances"][0]
    combined = assemble_parallel_mppt_iv(mppt, curves, source_electrical_revision_id=fixture["design"]["electrical_revision_id"])
    actual = interval["mppts"][0]
    assert combined.curve["points"] == actual["combined_curve"]["points"]
    assert combined.curve["local_mpp_candidates"] == actual["combined_curve"]["local_mpp_candidates"]
    assert len(combined.curve["local_mpp_candidates"]) >= 2
    tracker = select_mppt_operating_point(combined.curve, source_electrical_revision_id=fixture["design"]["electrical_revision_id"],
        mppt_operating_point_model_id=actual["tracker_model_id"], mppt_template=args["mppt_templates"][mppt["mppt_instance_id"]])
    assert tracker.state["selected_operating_point"] == actual["selected_operating_point"]
    assert tracker.state["constraint_evaluation"] == actual["constraint_flags"]
