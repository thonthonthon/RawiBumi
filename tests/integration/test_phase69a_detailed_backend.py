"""Phase 6.9A MPPT boundary: direct-kernel parity and canonical execution."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import runpy
from time import perf_counter

import pandas as pd
import pytest

from engine.irradiance import POA_PEREZ
from engine.thermal import THERMAL_PVSYST81_TRANSIENT
from engine.simulation.detailed_backend import (execute_detailed_mppt_backend, DetailedMPPTBackendResult,
    POWER_ABSOLUTE_TOLERANCE_W, POWER_RELATIVE_TOLERANCE)
from engine.simulation.detailed_dispatch import _prepare_backend
from engine.simulation.detailed_inputs import freeze_detailed_selection
from engine.simulation.artifacts import verify_run_package
from shading.electrical import (build_phase66_series_module_operating_model,
    assemble_general_series_string_iv, assemble_parallel_mppt_iv, select_mppt_operating_point,
    build_local_electrical_irradiance_state, collapse_local_irradiance_to_module_equivalent)
from tests.unit.test_phase69a_canonical_dispatch import _context, _run

ROOT = Path(__file__).resolve().parents[2]
REF = runpy.run_path(str(ROOT / "tests/integration/test_phase68_real_parallel_mppt.py"))


def _canonical_fixture():
    project, config, store, bundle = _context()
    config.setdefault("output_configuration", {})["detailed_diagnostics"] = True  # Reference/parity execution explicitly retains curves.
    config["shading_configuration"]["electrical_shading_configuration"]["scientific_options"] = {"string_sample_count": 101}
    scene = deepcopy(next(iter(store.scene_revisions.values())))
    electrical = deepcopy(next(iter(store.electrical_revisions.values())))
    ids = [REF[n] for n in ("MODULE_A_WEAK", "MODULE_A_CLEAR", "MODULE_B_CLEAR_1", "MODULE_B_CLEAR_2")]
    scene["module_instances"] = scene["module_instances"][:4]
    for m, module_id, x in zip(scene["module_instances"], ids, [-12., -7., 7., 12.]):
        m["module_instance_id"] = module_id
        m["transform"]["position_x_m"] = x
    field = scene["pv_fields"][0]
    field["generated_module_instance_ids"] = ids
    field["modules_per_row"] = 4
    # Controlled 6.8C receiver dimensions; canonical compiler remains authoritative.
    field["module_footprint"] = {"physical_width_m": 3., "physical_height_m": 2., "orientation": "portrait",
        "source_revision_id": field["module_definition_revision_id"], "packed_width_m": 3., "packed_height_m": 2., "packing_basis": "horizontal_plan_projection"}
    electrical["strings"] = [REF["_string_circuit"](REF["STRING_A"], ids[:2]), REF["_string_circuit"](REF["STRING_B"], ids[2:])]
    for s in electrical["strings"]:
        s["project_revision_id"] = project["project_revision_id"]
    mppt = REF["_mppt_instance"]()
    mppt["mppt_definition_id"] = "mppt-def-001"
    mppt["index"] = 1  # canonical/inverter contract is 1-based; standalone fixture uses 0.
    mppt["inverter_instance_id"] = electrical["inverter_instances"][0]["inverter_instance_id"]
    electrical["mppt_instances"] = [mppt]
    electrical["inverter_instances"][0]["mppt_instance_ids"] = [mppt["mppt_instance_id"]]
    # Use exactly the validated 6.8C regional calibration and provenance.
    topology = REF["_topology"]()
    definition = REF["_parameterization"](topology)
    evidence = REF["_evidence"](definition)
    assets = bundle["pinned_electrical_shading_assets"]
    assets["electrical_parameterization_definitions"] = {definition["revision_id"]: definition}
    assets["electrical_parameterization_evidence"] = {evidence["evidence_id"]: evidence}
    # Existing fixture uses the same synthetic source authority as pinned UAT assets.
    selection = next(iter(bundle["electrical_shading_selections"].values()))
    selection["region_parameterization_evidence_id"] = evidence["evidence_id"]
    inverter_id = electrical["inverter_instances"][0]["inverter_definition_revision_id"]
    components = deepcopy(dict(store.component_revisions))
    components[inverter_id]["mppt_template"].update(min_operating_voltage_v=0., max_operating_voltage_v=1000., max_operating_current_a=None)
    module = components[topology["module_definition_revision_id"]]
    module.setdefault("quality", {})["default_module_quality_loss_fraction"] = -0.0075
    bundle["pinned_components"]["modules"][module["revision_id"]] = deepcopy(module)
    source = deepcopy(assets["sources"]["phase66-synthetic-region-source"])
    source["source_id"] = "phase66-integration-region-source"
    source["title"] = "Validated Phase 6.8C controlled integration regional calibration"
    assets["sources"][source["source_id"]] = source
    # Nonunity IAM makes accidental double application visible.
    from engine.optical import IAM_TABULATED
    module.setdefault("optical", {})["iam"] = {"model_type": "tabulated", "execution_model_id": IAM_TABULATED,
        "points": [{"angle_deg": 0., "modifier": 1.}, {"angle_deg": 60., "modifier": .8}, {"angle_deg": 90., "modifier": 0.}],
        "interpolation_method": "linear", "normalize": True}
    bundle["pinned_components"]["modules"][module["revision_id"]] = deepcopy(module)
    config["model_selections"].pop("iam", None)
    # Place a real canonical box over the weak module to produce partial sky shading.
    from geometry.scene.editor import SceneEditorSession
    editor = SceneEditorSession(scene)
    editor.draw_box_obstacle(obstacle_id="phase69a-cover", scene_object_id="obj-phase69a-cover", name="regional cover",
        origin_x_m=-12.5, origin_y_m=-.5, width_m=1., depth_m=1., base_elevation_m=9., height_m=.2)
    scene = editor.scene
    from apps.api.electrical_shading_state import set_project_module_electrical_shading_selection
    bundle["electrical_shading_selections"] = {}
    set_project_module_electrical_shading_selection(bundle, {"modules": {module["revision_id"]: module}, **assets},
        module_revision_id=module["revision_id"], topology_revision_id=topology["revision_id"],
        region_parameterization_evidence_id=evidence["evidence_id"],
        requested_fidelity="level_2_bypass_substring", fallback_policy="fail_closed")
    store = replace(store, scene_revisions={scene["revision_id"]: scene},
        electrical_revisions={electrical["electrical_revision_id"]: electrical}, component_revisions=components,
        detailed_electrical_inputs=freeze_detailed_selection(bundle))
    return project, config, store, scene, electrical


@pytest.fixture(scope="module")
def canonical_result(tmp_path_factory):
    project, config, store, scene, electrical = _canonical_fixture()
    started = perf_counter()
    result = _run(tmp_path_factory.mktemp("phase69a"), project, config, store)
    elapsed = perf_counter() - started
    assert result.detailed_backend_result is not None, result.simulation_run["detailed_execution_identity"]
    return project, config, store, scene, electrical, result, elapsed


def _direct_parity(payload, store, configuration, electrical):
    frozen = store.detailed_electrical_inputs.replay()
    assets = frozen["pinned_electrical_shading_assets"]
    topology = next(iter(assets["module_topologies"].values()))
    definition = next(iter(assets["electrical_parameterization_definitions"].values()))
    evidence = next(iter(assets["electrical_parameterization_evidence"].values()))
    for interval in payload["intervals"]:
        models = {}
        for m, d in interval["modules"].items():
            local = d["local_irradiance"]
            first = local["regions"][0]
            rebuilt = build_local_electrical_irradiance_state(d["region_map"], d["visibility"],
                unshaded_poa=first["unshaded_poa"], optical_modifier=first["optical_modifier"],
                optical_model_manifest=local["optical_model_manifest"], module_temperature_c=local["module_temperature_c"],
                interval_start=local["interval_start"], evaluation_time=local["evaluation_time"])
            assert rebuilt == local
            models[m] = build_phase66_series_module_operating_model(topology, d["region_map"], rebuilt, definition, evidence)
            assert d["module_operating_model"] == {"scientific_input_sha256": models[m].scientific_input_sha256,
                "current_domain_ceiling_a": models[m].current_domain_ceiling_a, "model_id": models[m].model_id,
                "model_version": models[m].model_version}
        strings = {}
        for string in electrical["strings"]:
            direct = assemble_general_series_string_iv(string, {m: models[m] for m in string["module_instance_ids"]}, sample_count=101)
            assert direct.curve == interval["strings"][string["string_id"]]["curve"]
            assert direct.state == interval["strings"][string["string_id"]]["state"]
            strings[string["string_id"]] = direct.curve
        inverter = next(c for c in store.component_revisions.values() if c["schema_name"] == "InverterDefinition")
        for mppt, diagnostic in zip(electrical["mppt_instances"], interval["mppts"]):
            combined = assemble_parallel_mppt_iv(mppt, {s: strings[s] for s in mppt["connected_string_ids"]},
                source_electrical_revision_id=electrical["electrical_revision_id"])
            assert combined.curve == diagnostic["combined_curve"]
            assert combined.state == diagnostic["combined_state"]
            tracker = select_mppt_operating_point(combined.curve, source_electrical_revision_id=electrical["electrical_revision_id"],
                mppt_operating_point_model_id=diagnostic["tracker_model_id"], mppt_template=inverter["mppt_template"])
            assert tracker.state == diagnostic["tracker_state"]


def test_canonical_simulation_intermediates_equal_direct_phase68(canonical_result):
    _, config, store, _, electrical, result, _ = canonical_result
    _direct_parity(result.detailed_backend_result.replay(), store, config, electrical)
    assert result.simulation_run["detailed_execution_identity"]["runtime_support_result"] == "mppt_complete"
    assert result.backend_result is None and result.summary_result is None and result.standard_timeseries is None
    verify_run_package(result.artifact_directory)


def test_shading_iam_thermal_and_electrical_order(canonical_result):
    _, _, _, _, _, result, _ = canonical_result
    payload = result.detailed_backend_result.replay()
    partial = False
    for interval in payload["intervals"]:
        for d in interval["modules"].values():
            local = d["local_irradiance"]
            equivalent = collapse_local_irradiance_to_module_equivalent(d["region_map"], local)
            assert d["thermal_incident_poa_w_m2"] == pytest.approx(equivalent["equivalent_incident_poa_global_w_m2"], abs=1e-10)
            assert d["thermal_efficiency_effective_irradiance_w_m2"] == pytest.approx(equivalent["equivalent_effective_irradiance_w_m2"], abs=1e-10)
            for r in local["regions"]:
                source, shaded, vis, iam = r["unshaded_poa"], r["post_geometry_poa"], r["visibility_factor"], r["optical_modifier"]
                assert shaded["beam_w_m2"] == source["beam_w_m2"] * vis["beam"]
                assert shaded["sky_diffuse_w_m2"] == source["sky_diffuse_w_m2"] * vis["sky_diffuse"]
                assert shaded["ground_reflected_w_m2"] == source["ground_reflected_w_m2"] * vis["ground"]
                assert r["effective_irradiance_w_m2"] == sum(shaded[c] * iam[f] for c, f in
                    (("beam_w_m2", "beam"), ("sky_diffuse_w_m2", "sky_diffuse"), ("ground_reflected_w_m2", "ground_reflected")))
                partial |= 0 < vis["sky_diffuse"] < 1 and 0 < iam["sky_diffuse"] < 1
    assert partial
    for metadata in payload["temperature_metadata"].values():
        assert metadata["module_quality_loss_fraction"] == -.0075
        assert metadata["module_quality_application"] == "pending_calibration_independence_not_applied"
        assert metadata["coupling"]["converged"]


def test_tracker_pvi_unknown_limits_interval_alignment_immutable_result(canonical_result):
    _, _, store, _, electrical, result, _ = canonical_result
    payload = result.detailed_backend_result.replay()
    expected_index = next(iter(store.weather_revisions.values())).series.index
    assert [pd.Timestamp(i["interval_start"]) for i in payload["intervals"]] == list(expected_index)
    for interval in payload["intervals"]:
        assert pd.Timestamp(interval["evaluation_time"]) > pd.Timestamp(interval["interval_start"])
        for d in interval["modules"].values():
            assert pd.Timestamp(d["local_irradiance"]["interval_start"]) == pd.Timestamp(interval["interval_start"])
            assert pd.Timestamp(d["local_irradiance"]["evaluation_time"]) == pd.Timestamp(interval["evaluation_time"])
        for m in interval["mppts"]:
            p = m["selected_operating_point"]
            assert p["power_w"] == pytest.approx(p["voltage_v"] * p["current_a"], rel=POWER_RELATIVE_TOLERANCE, abs=POWER_ABSOLUTE_TOLERANCE_W)
            assert m["constraint_flags"]["operating_current_limit_known"] is False
            assert m["constraint_flags"]["operating_current_above_limit"] is None
    payload["intervals"].clear()
    assert result.detailed_backend_result.replay()["intervals"]
    with pytest.raises(ValueError, match="hash mismatch"):
        replace(result.detailed_backend_result, canonical_payload=b"{}").replay()


def test_replay_and_module_temperature_order_are_deterministic(tmp_path, canonical_result):
    project, config, store, scene, electrical, first, _ = canonical_result
    reordered = deepcopy(scene)
    reordered["module_instances"].reverse()
    # Scientific array order is retained in canonical identity; execution order
    # is sorted by module identity and histories do not cross-contaminate.
    args = _prepare_backend(config, store, reordered, electrical, [], "test", project["project_revision_id"], "2026-10-03T00:00:00Z")
    weather = next(iter(store.weather_revisions.values()))
    replay = execute_detailed_mppt_backend(weather, scientific_input_sha256=first.detailed_backend_result.replay()["scientific_input_sha256"], **args)
    assert replay == first.detailed_backend_result
    second = _run(tmp_path, project, config, store, name="replay", executed_at="2026-10-05T00:00:00Z")
    assert second.detailed_backend_result == first.detailed_backend_result
    assert second.simulation_run["input_hash"] == first.simulation_run["input_hash"]


def test_binding_current_limit_fails_closed_without_clipping(tmp_path, canonical_result):
    project, config, store, _, _, original, _ = canonical_result
    components = deepcopy(dict(store.component_revisions))
    inverter = next(c for c in components.values() if c["schema_name"] == "InverterDefinition")
    inverter["mppt_template"]["max_operating_current_a"] = .1
    constrained = _run(tmp_path, project, config, replace(store, component_revisions=components), name="binding")
    assert constrained.simulation_run["status"] == "failed"
    assert constrained.simulation_run["detailed_execution_identity"]["runtime_support_result"] == "constraint_blocked"
    for first, second in zip(original.detailed_backend_result.replay()["intervals"], constrained.detailed_backend_result.replay()["intervals"]):
        a, b = first["mppts"][0], second["mppts"][0]
        assert a["selected_operating_point"] == b["selected_operating_point"]
        assert b["constraint_flags"]["operating_current_above_limit"] is True
        assert "no_clipping" in b["constraint_flags"]["enforcement_policy"]
    verify_run_package(constrained.artifact_directory)


@pytest.mark.parametrize("mutation", ["missing_module", "duplicate_module", "missing_string", "extra_string"])
def test_exact_module_string_mppt_coverage_fails_closed(tmp_path, canonical_result, mutation):
    project, config, store, _, electrical, _, _ = canonical_result
    design = deepcopy(electrical)
    if mutation == "missing_module": design["strings"][0]["module_instance_ids"].pop()
    if mutation == "duplicate_module": design["strings"][0]["module_instance_ids"].append(design["strings"][1]["module_instance_ids"][0])
    if mutation == "missing_string": design["mppt_instances"][0]["connected_string_ids"].pop()
    if mutation == "extra_string": design["mppt_instances"][0]["connected_string_ids"].append("unbound-string")
    result = _run(tmp_path, project, config, replace(store, electrical_revisions={design["electrical_revision_id"]: design}), name=mutation)
    assert result.detailed_backend_result is None
    assert result.simulation_run["detailed_execution_identity"]["runtime_support_result"] == "blocked"


def test_legacy_never_calls_detailed_backend(tmp_path, monkeypatch):
    from tests.unit.test_phase38e_canonical_simulation_run import _inputs
    from engine.simulation import run_canonical_simulation
    project, config, store = _inputs()
    def forbidden(*a, **kw): raise AssertionError("legacy entered detailed physics")
    monkeypatch.setattr("engine.simulation.detailed_backend.execute_detailed_mppt_backend", forbidden)
    result = run_canonical_simulation(project, config, revision_store=store, output_directory=tmp_path,
        simulation_run_id="legacy", engine_version="legacy-test")
    assert result.detailed_backend_result is None
    assert result.simulation_run["status"] == "completed_with_warnings"


def test_exact_phase68c_controlled_four_module_reference(monkeypatch, canonical_result, tmp_path):
    """Boundary isolation: reproduce the existing 1000 W/m² / 25°C fixture.

    Solar direction, weather and constant module temperature are deliberately
    controlled here; canonical tests above use real SPA and thermal coupling.
    No Phase 6.6–6.8 kernel is stubbed.
    """
    project, config, store, scene, electrical, _, _ = canonical_result
    arguments = _prepare_backend(config, store, scene, electrical, [], "reference", project["project_revision_id"], "2026-10-03T00:00:00Z")
    clear_geometry = REF["_four_module_geometry"]()
    topology = REF["_topology"]()
    weak_map, _, _ = REF["_module_handoff"](clear_geometry, topology, REF["MODULE_A_WEAK"])
    geometry = deepcopy(clear_geometry)
    geometry["source_scene_revision_id"] = "phase68-four-module-scene-r2"
    geometry["geometry_payload_sha256"] = "a" * 64
    geometry["occluders"] = [REF["_occluder_over_region"](REF["_mapped_region"](weak_map, "s1-r1"))]
    arguments["compiled_geometry"] = geometry
    arguments["shading_configuration"] = deepcopy(arguments["shading_configuration"])
    arguments["shading_configuration"]["sky_dome_resolution"] = {"azimuth_sectors": 4, "elevation_bands": 1,
        "horizon_azimuth_sectors": 4, "horizon_elevation_bands": 1, "horizon_band_elevation_deg": 10.}
    arguments["shading_configuration"]["ground_dome_resolution"] = {"azimuth_sectors": 4, "depression_bands": 1}
    from engine.optical import IAM_NONE
    arguments["module_configs"] = {m: replace(c, iam_model_id=IAM_NONE) for m,c in arguments["module_configs"].items()}
    weather = next(iter(store.weather_revisions.values())).copy()
    weather.series = weather.series.iloc[:1].copy()
    weather.series.index = pd.DatetimeIndex(["2026-10-01T11:00:00+07:00"])
    weather.series["ghi_w_m2"] = 1000.
    weather.series["dni_w_m2"] = 1000.
    weather.series["dhi_w_m2"] = 0.
    weather.dataset["start_time"] = weather.series.index[0].isoformat()
    weather.dataset["end_time"] = (weather.series.index[0] + pd.Timedelta(hours=1)).isoformat()
    from engine.solar import SolarPositionResult
    import engine.simulation.detailed_backend as backend
    original_solar = backend.solar_position_from_weather
    def vertical_solar(*a, **kw):
        result = original_solar(*a, **kw)
        frame = result.frame.copy()
        for column in ("solar_zenith_deg", "solar_apparent_zenith_deg", "solar_azimuth_deg"): frame[column] = 0.
        for column in ("solar_elevation_deg", "solar_apparent_elevation_deg"): frame[column] = 90.
        frame["evaluation_time"] = [pd.Timestamp("2026-10-01T12:00:00+07:00")]
        return SolarPositionResult(frame, result.metadata)
    monkeypatch.setattr(backend, "solar_position_from_weather", vertical_solar)
    monkeypatch.setattr(backend, "sun_vector_from_azimuth_elevation", lambda *a: [0., 0., 1.])
    from types import SimpleNamespace
    def fixed_fixture_temperature(poa, optical, weather, **kwargs):
        return SimpleNamespace(thermal=SimpleNamespace(frame=pd.DataFrame({"cell_temperature_c": [25.]}, index=poa.frame.index)),
            metadata={"converged": True, "fixture_override": "phase68c_fixed_25c_boundary_isolation"})
    monkeypatch.setattr(backend, "solve_pvsyst_module_thermal_coupling", fixed_fixture_temperature)
    import resource
    memory_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = perf_counter()
    result = execute_detailed_mppt_backend(weather, scientific_input_sha256="b" * 64, **arguments)
    elapsed = perf_counter() - started
    memory_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    payload = result.replay()
    interval = payload["intervals"][0]
    direct_models = {}
    definition, evidence = REF["_parameterization"](topology), None
    evidence = REF["_evidence"](definition)
    for m, diagnostic in interval["modules"].items():
        region_map, visibility, local = REF["_module_handoff"](geometry, topology, m)
        assert diagnostic["region_map"] == region_map
        assert diagnostic["visibility"] == visibility
        assert diagnostic["local_irradiance"]["module_temperature_c"] == local["module_temperature_c"]
        assert diagnostic["local_irradiance"]["regions"] == local["regions"]
        direct_models[m] = build_phase66_series_module_operating_model(topology, region_map, local, definition, evidence)
    direct_strings = {}
    for s in electrical["strings"]:
        direct = assemble_general_series_string_iv(s, {m: direct_models[m] for m in s["module_instance_ids"]}, sample_count=101)
        assert direct.curve["points"] == interval["strings"][s["string_id"]]["curve"]["points"]
        direct_strings[s["string_id"]] = direct.curve
    mppt = electrical["mppt_instances"][0]
    combined = assemble_parallel_mppt_iv(mppt, direct_strings, source_electrical_revision_id=electrical["electrical_revision_id"])
    diagnostic = interval["mppts"][0]
    assert combined.curve["points"] == diagnostic["combined_curve"]["points"]
    assert combined.curve["local_mpp_candidates"] == diagnostic["combined_curve"]["local_mpp_candidates"]
    assert len(combined.curve["local_mpp_candidates"]) >= 2
    tracker = select_mppt_operating_point(combined.curve, source_electrical_revision_id=electrical["electrical_revision_id"],
        mppt_operating_point_model_id=diagnostic["tracker_model_id"], mppt_template=arguments["mppt_templates"][mppt["mppt_instance_id"]])
    assert tracker.state["selected_operating_point"] == diagnostic["selected_operating_point"]
    assert tracker.state["constraint_evaluation"] == diagnostic["constraint_flags"]
    print(f"Phase 6.8C fixture backend: {elapsed:.3f}s; process peak RSS {memory_after} KiB; peak RSS increment {memory_after-memory_before} KiB; immutable payload {len(result.canonical_payload)} bytes")


def test_numerical_package_tampering_is_detected(tmp_path, canonical_result):
    from shutil import copytree
    _, _, _, _, _, result, _ = canonical_result
    directory = tmp_path / "tampered"
    copytree(result.artifact_directory, directory)
    path = directory / "detailed-mppt-result.json"
    record = json.loads(path.read_text())
    record["payload"]["intervals"][0]["mppts"][0]["selected_operating_point"]["power_w"] += 1.
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        verify_run_package(directory)


def test_invalid_selected_power_is_rejected(canonical_result):
    _, _, _, _, _, result, _ = canonical_result
    payload = result.detailed_backend_result.replay()
    m = payload["intervals"][0]["mppts"][0]
    m["selected_operating_point"]["power_w"] += 1.
    m["tracker_state"]["selected_operating_point"] = deepcopy(m["selected_operating_point"])
    with pytest.raises(ValueError, match="voltage times current"):
        DetailedMPPTBackendResult.freeze(payload)


def test_unshaded_source_and_direct_temperature_history(canonical_result):
    project, config, store, scene, electrical, result, _ = canonical_result
    from engine.simulation.temporal import prepare_temporal_execution
    from engine.solar import solar_position_from_weather
    from engine.irradiance import calculate_poa, complete_irradiance, PlaneOfArrayResult
    from engine.simulation.unshaded import resolve_module_runtime_inputs, _module_runtime_properties
    from engine.optical import apply_iam
    from engine.module import solve_pvsyst_module_thermal_coupling
    args = _prepare_backend(config, store, scene, electrical, [], "direct-temperature", project["project_revision_id"], "2026-10-03T00:00:00Z")
    weather = next(iter(store.weather_revisions.values()))
    temporal = prepare_temporal_execution(weather, simulation_timestep_seconds=config["simulation_timestep_seconds"])
    solar = solar_position_from_weather(temporal.weather, timeline=temporal.timeline)
    irradiance = complete_irradiance(temporal.weather, solar)
    payload = result.detailed_backend_result.replay()
    for module_id, c in args["module_configs"].items():
        poa = calculate_poa(irradiance, solar, surface_tilt_deg=c.surface_tilt_deg,
            surface_azimuth_deg=c.surface_azimuth_deg, albedo=c.albedo, model_id=c.poa_model_id,
            simulation_timestep_seconds=c.simulation_timestep_seconds)
        incident_frame = poa.frame.copy()
        for interval in payload["intervals"]:
            d = interval["modules"][module_id]
            local = d["local_irradiance"]
            start = pd.Timestamp(interval["interval_start"])
            original = poa.frame.loc[start]
            for r in local["regions"]:
                assert r["unshaded_poa"] == {"beam_w_m2": original["poa_beam_w_m2"],
                    "sky_diffuse_w_m2": original["poa_sky_diffuse_w_m2"], "ground_reflected_w_m2": original["poa_ground_diffuse_w_m2"]}
            eq = collapse_local_irradiance_to_module_equivalent(d["region_map"], local)
            shaded = eq["post_geometry_poa"]
            for column, channel in (("poa_beam_w_m2", "beam_w_m2"), ("poa_sky_diffuse_w_m2", "sky_diffuse_w_m2"),
                ("poa_isotropic_w_m2", "sky_diffuse_w_m2"), ("poa_ground_diffuse_w_m2", "ground_reflected_w_m2")):
                incident_frame.loc[start,column] = shaded[channel]
            incident_frame.loc[start,"poa_global_w_m2"] = eq["equivalent_incident_poa_global_w_m2"]
        incident = PlaneOfArrayResult(incident_frame, poa.metadata)
        runtime = resolve_module_runtime_inputs(c.module_definition, iam_model_id=c.iam_model_id)
        optical = apply_iam(incident, model_id=runtime.iam_model_id, profile=runtime.iam_profile, surface_tilt_deg=c.surface_tilt_deg)
        parameters, area, _, mass = _module_runtime_properties(c.module_definition)
        direct = solve_pvsyst_module_thermal_coupling(incident, optical, temporal.weather,
            parameter_set=parameters, module_area_m2=area, u_c_w_m2k=c.u_c_w_m2k,
            u_v_w_m2k_per_ms=c.u_v_w_m2k_per_ms, alpha_absorption=runtime.alpha_absorption,
            thermal_model_id=c.thermal_model_id, module_unit_mass_kg_m2=mass)
        assert direct.metadata == payload["temperature_metadata"][module_id]["coupling"]
        assert direct.thermal.frame["cell_temperature_c"].tolist() == [i["modules"][module_id]["local_irradiance"]["module_temperature_c"] for i in payload["intervals"]]


@pytest.mark.parametrize("field,value", [("transposition", POA_PEREZ),
    ("temperature", THERMAL_PVSYST81_TRANSIENT)])
def test_unsupported_physics_is_blocked_before_backend(tmp_path, monkeypatch, canonical_result, field, value):
    project, configuration, store, _, _, _, _ = canonical_result
    config = deepcopy(configuration)
    config["model_selections"][field] = value
    def forbidden(*a, **kw): raise AssertionError("unsupported configuration reached numerical backend")
    monkeypatch.setattr("engine.simulation.detailed_backend.execute_detailed_mppt_backend", forbidden)
    result = _run(tmp_path, project, config, store, name=field)
    assert result.detailed_backend_result is None
    assert result.simulation_run["detailed_execution_identity"]["runtime_support_result"] == "blocked"


def test_known_zero_current_limit_is_invalid_and_never_becomes_unknown(tmp_path, canonical_result):
    project, config, store, _, _, _, _ = canonical_result
    components = deepcopy(dict(store.component_revisions))
    inverter = next(c for c in components.values() if c["schema_name"] == "InverterDefinition")
    inverter["mppt_template"]["max_operating_current_a"] = 0.
    result = _run(tmp_path, project, config, replace(store, component_revisions=components), name="invalid-current")
    assert result.detailed_backend_result is None
    assert result.simulation_run["status"] == "failed"
    assert any("exclusiveMinimum" in r or "must be positive" in r
        for r in result.simulation_run["detailed_execution_identity"]["failure_reasons"])


def test_zero_generation_interval_is_explicitly_inactive(tmp_path, canonical_result):
    project, config, store, _, _, _, _ = canonical_result
    config = deepcopy(config)
    config.setdefault("numerical_options", {}).setdefault("module_overrides", {})["module_quality_loss_fraction"] = 0.
    weather = next(iter(store.weather_revisions.values())).copy()
    weather.series.loc[weather.series.index[0], ["ghi_w_m2", "dni_w_m2", "dhi_w_m2"]] = 0.
    result = _run(tmp_path, project, config, replace(store, weather_revisions={weather.dataset["revision_id"]: weather}), name="dark")
    assert result.summary_result is not None, result.simulation_run
    m = result.detailed_backend_result.replay()["intervals"][0]["mppts"][0]
    assert m["availability"] == "inactive_dark"
    assert m["selected_operating_point"] is None
    assert m["combined_curve"] is None
    assert m["tracker_state"] is None
    assert m["power_w"] == 0.
    verify_run_package(result.artifact_directory)
