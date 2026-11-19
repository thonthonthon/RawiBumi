"""Independent optics/thermal oracles and real browser-adapter regressions."""

from copy import deepcopy
import pytest
from tests.unit.test_rb_fix_s2_honest_preflight import Project
from tests.unit.test_rb_fix_s16_multi_group import make_design


@pytest.mark.parametrize(
    "patch",
    [
        {"overrides": {}},
        {"overrides": {"lid_fraction": None}},
    ],
)
def test_legacy_loss_noop_writes_nothing(tmp_path, patch):
    p = Project(tmp_path, count=18)
    bundle = p.bundle()
    bundle.pop("loss_settings", None)
    p.service.store.save(bundle)
    before, stat = p.path.read_bytes(), p.path.stat().st_mtime_ns
    response = p.client.patch(p.url + "/losses", json=patch)
    assert response.status_code == 200, response.text
    assert p.path.read_bytes() == before
    assert p.path.stat().st_mtime_ns == stat
    assert "loss_settings" not in p.bundle()


def test_present_loss_block_skips_discarded_legacy_array_chain(
    make_design, monkeypatch
):
    import engine.simulation.multi_group as multi

    d = make_design("duplicate")

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "present loss block must not compute discarded legacy losses"
        )

    monkeypatch.setattr(multi, "apply_pre_inverter_array_losses", forbidden)
    response = d.client.post(d.url + "/simulate", json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] in ("completed", "completed_with_warnings")


from engine.simulation.optics_thermal import (
    default_optics_thermal_settings,
    patch_optics_thermal_settings,
    resolve_optics_thermal_settings,
    albedo_for_index,
    resolve_iam,
)


def test_settings_patch_merge_inheritance_and_local_month():
    import pandas as pd

    base = default_optics_thermal_settings()
    patched = patch_optics_thermal_settings(
        base,
        {
            "overrides": {
                "albedo": {"monthly_values": [0.1, 0.3] + [0.2] * 10},
                "thermal": {
                    "irradiance_basis": "incident_pre_iam",
                    "mounting_preset": "open_rack",
                },
            }
        },
    )
    resolved = resolve_optics_thermal_settings(patched)
    assert resolved["values"]["thermal"]["u_c_w_m2k"] == 29
    assert resolved["values"]["thermal"]["irradiance_basis"] == "incident_pre_iam"
    index = pd.DatetimeIndex(["2025-01-31T23:00:00+07:00", "2025-02-01T00:00:00+07:00"])
    assert list(albedo_for_index(resolved, index)) == [0.1, 0.3]
    undone = patch_optics_thermal_settings(
        patched, {"overrides": {"albedo": None, "thermal": None}}
    )
    assert undone == base
    assert base["overrides"] == {}


@pytest.mark.parametrize(
    "overrides",
    [
        {"unknown": 3},
        {"transposition": "invented"},
        {"iam": {"selection": "magic"}},
        {"thermal": {"u_c_w_m2k": 0}},
        {"thermal": {"u_v_w_m2k_per_ms": -1}},
        {"thermal": {"u_c_w_m2k": float("nan")}},
        {"thermal": {"mounting_preset": "open_rack", "u_c_w_m2k": 20}},
        {"albedo": {"monthly_values": [0.2] * 11}},
        {"albedo": {"annual_value": 1.1}},
        {"albedo": {"annual_value": 0.2, "monthly_values": [0.2] * 12}},
    ],
)
def test_strict_optics_settings(overrides):
    with pytest.raises(ValueError):
        patch_optics_thermal_settings(
            default_optics_thermal_settings(), {"overrides": overrides}
        )


def test_real_http_optics_noop_edit_reset_and_snapshot(tmp_path):
    p = Project(tmp_path, count=18)
    original = p.path.read_bytes()
    for patch in [{"overrides": {}}, {"reset_to_recommended_defaults": True}]:
        r = p.client.patch(p.url + "/optics-thermal", json=patch)
        assert r.status_code == 200, r.text
        assert p.path.read_bytes() == original
    response = p.client.patch(
        p.url + "/optics-thermal",
        json={
            "overrides": {
                "thermal": {"irradiance_basis": "incident_pre_iam", "u_c_w_m2k": 29}
            }
        },
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["resolved_optics_thermal_settings"]["values"]["thermal"][
            "irradiance_basis"
        ]
        == "incident_pre_iam"
    )
    saved = p.path.read_bytes()
    refusal = p.client.patch(
        p.url + "/optics-thermal", json={"overrides": {"albedo": {"annual_value": 2}}}
    )
    assert refusal.status_code == 422
    assert p.path.read_bytes() == saved
    run = p.client.post(p.url + "/simulate", json={})
    assert run.status_code == 200, run.text
    assert run.json()["status"] in ("completed", "completed_with_warnings"), run.text
    snapshot = run.json()["resolved_optics_thermal_settings"]
    assert snapshot["values"]["thermal"]["u_c_w_m2k"] == 29
    assert len(snapshot["modules"]) == 18
    assert {v["iam_source"] for v in snapshot["modules"].values()} <= {
        "module_table",
        "fallback_physical_glass",
    }
    assert (
        p.client.patch(
            p.url + "/optics-thermal", json={"reset_to_recommended_defaults": True}
        ).status_code
        == 200
    )
    assert (
        p.bundle()["simulation_runs"][0]["resolved_optics_thermal_settings"] == snapshot
    )


def test_iam_library_and_literal_interpolation_oracles():
    import numpy as np
    import pvlib
    from engine.optical.iam import (
        evaluate_physical_glass_iam,
        physical_glass_diffuse_factors,
        evaluate_tabulated_iam,
        TabulatedIAMProfile,
    )

    angles = np.array([0.0, 30.0, 60.0, 80.0, 90.0, 100.0])
    expected = pvlib.iam.physical(angles, n=1.526, K=4.0, L=0.002, n_ar=None)
    assert np.array_equal(
        evaluate_physical_glass_iam(angles)[angles < 90], expected[angles < 90]
    )
    assert (
        evaluate_physical_glass_iam(angles)[angles >= 90] == 0
    ).all()  # existing front-side/grazing policy
    direct = {
        k: pvlib.iam.marion_integrate(
            lambda a: pvlib.iam.physical(a, n=1.526, K=4, L=0.002, n_ar=None), 30, k
        )
        for k in ("sky", "horizon", "ground")
    }
    assert physical_glass_diffuse_factors(30) == direct
    table = TabulatedIAMProfile.from_points([(0, 1), (30, 0.98), (60, 0.8), (90, 0)])
    assert evaluate_tabulated_iam(45, table) == pytest.approx(0.89, abs=1e-15)
    resolved = resolve_optics_thermal_settings(default_optics_thermal_settings())
    assert (
        resolve_iam(resolved, {"revision_id": "no-table"})[2]
        == "fallback_physical_glass"
    )
    with pytest.raises(ValueError, match="unusable IAM"):
        resolve_iam(
            resolved, {"revision_id": "broken", "optical": {"iam": {"points": []}}}
        )


def test_exact_zero_limit_preserves_nonzero_rows_and_does_not_mask_other_nan():
    import numpy as np
    import pandas as pd
    from engine.irradiance import PlaneOfArrayResult, IrradianceCompletionResult
    from engine.simulation.optics_thermal import zero_horizontal_irradiance_limit

    index = pd.date_range("2025-01-01T12:00:00+07:00", periods=3, freq="h")
    source = pd.DataFrame(
        {
            "ghi_w_m2": [0.0, 100.0, 0.0],
            "dni_w_m2": [0.0, 50.0, 0.0],
            "dhi_w_m2": [0.0, 0.0, 0.0],
        },
        index=index,
    )
    cols = [
        "poa_beam_w_m2",
        "poa_sky_diffuse_w_m2",
        "poa_ground_diffuse_w_m2",
        "poa_diffuse_w_m2",
        "poa_global_w_m2",
        "poa_isotropic_w_m2",
        "poa_circumsolar_w_m2",
        "poa_horizon_w_m2",
    ]
    frame = pd.DataFrame({k: [np.nan, np.nan, np.nan] for k in cols}, index=index)
    poa = PlaneOfArrayResult(frame, {"existing": "retained"})
    irradiance = IrradianceCompletionResult(source, {})
    result = zero_horizontal_irradiance_limit(poa, irradiance)
    assert (result.frame.iloc[[0, 2]][cols] == 0).all().all()
    pd.testing.assert_series_equal(result.frame.iloc[1], frame.iloc[1])
    assert result.frame.iloc[1].isna().all()  # GHI > 0 is never repaired.
    assert frame.isna().all().all() and source.iloc[1].ghi_w_m2 == 100
    assert result.metadata["zero_input_interval_count"] == 2


@pytest.mark.parametrize(
    "u_c,u_v,wind", [(29.0, 0.0, 2.0), (15.0, 0.0, 2.0), (24.0, 1.5, 3.0)]
)
def test_effective_thermal_basis_hand_oracle(u_c, u_v, wind):
    import pandas as pd
    import numpy as np
    from engine.irradiance import PlaneOfArrayResult
    from engine.optical import OpticalResult
    from engine.module import solve_pvsyst_module_thermal_coupling
    from engine.simulation.unshaded import _module_runtime_properties
    from tests.unit.test_phase49c_reference_projects import _reference

    r = _reference("R1")
    weather = deepcopy(r["weather"])
    weather.series["wind_speed_m_s"] = wind
    definition = next(
        v for v in r["components"].values() if v["schema_name"] == "ModuleDefinition"
    )
    params, area, _, mass = _module_runtime_properties(definition)
    index = weather.series.index
    # Hold real SDM/coupling fixed; the oracle uses the returned effective-basis efficiency.
    incident = pd.DataFrame({"poa_global_w_m2": [800.0] * len(index)}, index=index)
    optical = pd.DataFrame(
        {
            "effective_irradiance_w_m2": [600.0] * len(index),
            "incident_poa_global_w_m2": [800.0] * len(index),
        },
        index=index,
    )
    result = solve_pvsyst_module_thermal_coupling(
        PlaneOfArrayResult(incident, {}),
        OpticalResult(optical, {}),
        weather,
        parameter_set=params,
        module_area_m2=area,
        u_c_w_m2k=u_c,
        u_v_w_m2k_per_ms=u_v,
        alpha_absorption=0.9,
        thermal_irradiance_basis="effective",
    )
    eta = result.electrical.frame.module_efficiency_on_effective_irradiance_fraction
    expected = weather.series.ambient_temperature_c + 0.9 * 600 * (1 - eta) / (
        u_c + u_v * wind
    )
    np.testing.assert_allclose(
        result.thermal.frame.cell_temperature_c, expected, rtol=0, atol=1e-4
    )
    assert (result.electrical.frame.incident_poa_global_w_m2 == 800).all()


def test_regional_component_oracle_signed_horizon_and_fail_closed():
    from shading.electrical.local_irradiance import component_irradiance_channels

    source = {
        "beam": 600.0,
        "isotropic": 100.0,
        "circumsolar": 50.0,
        "horizon": -10.0,
        "ground": 20.0,
    }
    vis = {"beam": 0.25, "sky": 0.8, "horizon": 0.5, "ground": 0.6}
    opt = {"beam": 0.9, "sky": 0.95, "horizon": 0.7, "ground": 0.8}
    geometry, effective = component_irradiance_channels(source, vis, opt)
    assert geometry == {
        "beam": 150.0,
        "isotropic": 80.0,
        "circumsolar": 12.5,
        "horizon": -5.0,
        "ground": 12.0,
    }
    assert effective == {
        "beam": 135.0,
        "isotropic": 76.0,
        "circumsolar": 11.25,
        "horizon": -3.5,
        "ground": 9.600000000000001,
    }
    assert sum(effective.values()) == pytest.approx(228.35)


@pytest.mark.parametrize("zero", [False, True])
def test_detailed_defaults_component_mapping_and_zero_input(tmp_path, zero):
    from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
    from tests.unit.test_phase69a_canonical_dispatch import _run
    from engine.simulation.optics_thermal import configure_optics_thermal
    from dataclasses import replace

    project, config, store, scene, electrical = _canonical_fixture()
    configure_optics_thermal(config, default_optics_thermal_settings())
    config["numerical_options"]["module_overrides"] = {
        "module_quality_loss_fraction": 0.0
    }
    if zero:
        weather = next(iter(store.weather_revisions.values()))
        # Only the synthetic fixture's irradiance channels are zeroed; no real files.
        weather = deepcopy(weather)
        for key in ["ghi_w_m2", "dni_w_m2", "dhi_w_m2"]:
            if key in weather.series:
                weather.series[key] = 0.0
        store = replace(
            store, weather_revisions={weather.dataset["revision_id"]: weather}
        )
    result = _run(
        tmp_path,
        project,
        config,
        store,
        name="s18b-detailed-zero" if zero else "s18b-detailed",
    )
    assert result.summary_result is not None, result.simulation_run
    assert result.simulation_run["status"] in ("completed", "completed_with_warnings")
    identity = result.simulation_run["detailed_execution_identity"]
    assert (
        identity["resolved_fidelity"] == "level_2_bypass_substring"
        and identity["fallback_applied"] is False
    )
    assert (
        len(result.simulation_run["resolved_optics_thermal_settings"]["modules"]) == 4
    )
    payload = result.detailed_backend_result.replay()
    for interval in payload["intervals"]:
        for module in interval["modules"].values():
            for region in module["local_irradiance"]["regions"]:
                assert "component_state" in region
                assert region["effective_irradiance_w_m2"] == pytest.approx(
                    sum(region["component_state"]["post_optical"].values())
                )
                if zero:
                    assert region["effective_irradiance_w_m2"] == 0

    if not zero:
        from engine.simulation.canonical import _select_weather_period
        from engine.simulation.detailed_dispatch import _prepare_backend
        from engine.simulation.detailed_backend import execute_detailed_mppt_backend

        args = _prepare_backend(
            config,
            store,
            scene,
            electrical,
            [],
            "unbounded",
            project["project_revision_id"],
            "2026-11-03T00:00:00Z",
        )
        unbounded = execute_detailed_mppt_backend(
            _select_weather_period(
                next(iter(store.weather_revisions.values())), config
            ),
            scientific_input_sha256=payload["scientific_input_sha256"],
            scientific_configuration=config,
            frozen_selection=store.detailed_electrical_inputs,
            **args
        )
        try:
            assert (
                unbounded.numerical_result_sha256
                == result.detailed_backend_result.numerical_result_sha256
            )
        finally:
            unbounded.close()
        changed = deepcopy(config)
        changed["numerical_options"]["optics_thermal_settings"] = (
            patch_optics_thermal_settings(
                default_optics_thermal_settings(),
                {"overrides": {"albedo": {"annual_value": 0.3}}},
            )
        )
        from engine.simulation.detailed_inputs import _scientific_configuration_bytes

        assert _scientific_configuration_bytes(
            changed
        ) != _scientific_configuration_bytes(config)


@pytest.mark.parametrize(
    "patch",
    [
        {"overrides": {"unknown": None}},
        {"overrides": {"thermal": {"unknown": None}}},
        {"reset_to_recommended_defaults": 1},
        {"overrides": {"thermal": {"mounting_preset": {}}}},
    ],
)
def test_bad_shapes_and_unknown_nulls_are_not_silently_dropped(patch):
    with pytest.raises(ValueError):
        patch_optics_thermal_settings(default_optics_thermal_settings(), patch)


def test_transposition_and_monthly_ground_direct_library_oracles():
    import numpy as np
    import pvlib
    from engine.irradiance import calculate_poa, POA_PVSYST81_PEREZ
    from tests.unit.test_phase38c_pvsyst81_perez import _index, _solar, _completed

    index = _index(periods=2)
    solar = _solar(
        index,
        true_zenith=[40.0, 50.0],
        apparent_zenith=[40.0, 50.0],
        azimuth=[170.0, 190.0],
    )
    irr = _completed(index, ghi=[800.0, 700.0], dni=[600.0, 500.0], dhi=[200.0, 200.0])
    rho = np.array([0.1, 0.4])
    tilt = 30.0
    result = calculate_poa(
        irr,
        solar,
        surface_tilt_deg=tilt,
        surface_azimuth_deg=180.0,
        albedo=rho,
        model_id=POA_PVSYST81_PEREZ,
        simulation_timestep_seconds=3600,
    )
    times = __import__("pandas").DatetimeIndex(solar.frame.evaluation_time)
    extra = pvlib.irradiance.get_extra_radiation(times)
    air = pvlib.atmosphere.get_relative_airmass(np.array([40.0, 50.0]))
    direct = pvlib.irradiance.perez(
        tilt,
        180.0,
        np.array([200.0, 200.0]),
        np.array([600.0, 500.0]),
        extra,
        np.array([40.0, 50.0]),
        np.array([170.0, 190.0]),
        air,
        model="allsitescomposite1990",
        return_components=True,
    )
    for key, column in [
        ("poa_isotropic", "poa_isotropic_w_m2"),
        ("poa_circumsolar", "poa_circumsolar_w_m2"),
        ("poa_horizon", "poa_horizon_w_m2"),
    ]:
        np.testing.assert_array_equal(result.frame[column], direct[key])
    ground = np.array([800.0, 700.0]) * rho * (1 - np.cos(np.deg2rad(tilt))) / 2
    np.testing.assert_array_equal(result.frame.poa_ground_diffuse_w_m2, ground)


def test_two_orientations_with_default_optics_reconcile_and_record_each_module(
    make_design,
):
    d = make_design("orientations")
    response = d.client.post(d.url + "/simulate", json={})
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] in ("completed", "completed_with_warnings"), run
    snapshot = run["resolved_optics_thermal_settings"]
    assert snapshot["values"]["transposition"] == "perez_hourly"
    breakdown = run["summary_result"]["execution_breakdown"]
    assert len(breakdown["groups"]) == 2
    assert len(snapshot["modules"]) == sum(
        len(g["module_instance_ids"]) for g in breakdown["groups"]
    )
    assert sum(i["total_energy_wh"] for i in breakdown["inverters"]) - sum(
        breakdown["plant_adjustments"].values()
    ) == pytest.approx(run["summary_result"]["total_energy_wh"], abs=1e-6)


@pytest.mark.parametrize("with_losses", [False, True])
def test_explicit_legacy_block_is_byte_exact_to_absent_in_same_uri_root(
    tmp_path, with_losses
):
    import hashlib, shutil
    from tests.unit.test_phase49c_reference_projects import _reference
    from engine.simulation import (
        build_design_revision_store,
        run_validated_design_simulation,
    )
    from engine.simulation.optics_thermal import configure_optics_thermal
    from engine.simulation.artifacts import canonical_json_bytes, verify_run_package
    from engine.losses.settings import default_loss_settings

    r = _reference("R1")
    config = deepcopy(r["configuration"])
    if with_losses:
        config["numerical_options"]["loss_settings"] = default_loss_settings()
    store = build_design_revision_store(
        r["scene"], r["electrical"], r["weather"], r["components"]
    )

    def run():
        return run_validated_design_simulation(
            r["project_revision"],
            config,
            revision_store=store,
            design_validation_report=r["validation"],
            output_directory=tmp_path,
            simulation_run_id="explicit-legacy",
            engine_version="s18b-oracle",
            executed_at="2026-11-03T00:00:00Z",
        )

    a = run()
    verify_run_package(a.artifact_directory)
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    before = {
        name: digest(a.artifact_directory / name)
        for name in ("summary-result.json", "timeseries.parquet")
    }
    loss_before = canonical_json_bytes(
        a.backend_result.electrical.ledger.summary.reset_index().to_dict(
            orient="records"
        )
    )
    loss_frame = a.backend_result.electrical.ledger.frame.copy()
    assert a.artifact_directory.resolve().is_relative_to(tmp_path.resolve())
    shutil.rmtree(a.artifact_directory)
    configure_optics_thermal(
        config,
        patch_optics_thermal_settings(
            default_optics_thermal_settings(),
            {
                "overrides": {
                    "transposition": "isotropic",
                    "iam": {"selection": "none"},
                    "thermal": {"irradiance_basis": "incident_pre_iam"},
                }
            },
        ),
    )
    b = run()
    verify_run_package(b.artifact_directory)
    assert {name: digest(b.artifact_directory / name) for name in before} == before
    assert (
        canonical_json_bytes(
            b.backend_result.electrical.ledger.summary.reset_index().to_dict(
                orient="records"
            )
        )
        == loss_before
    )
    __import__("pandas").testing.assert_frame_equal(
        loss_frame, b.backend_result.electrical.ledger.frame, check_exact=True
    )
    assert (
        b.simulation_run["resolved_optics_thermal_settings"]["values"]["iam"][
            "selection"
        ]
        == "none"
    )


@pytest.mark.parametrize("detailed", [False, True])
def test_other_nan_sources_are_never_repaired(tmp_path, monkeypatch, detailed):
    import numpy as np
    from engine.irradiance import PlaneOfArrayResult

    target = (
        "engine.simulation.detailed_backend"
        if detailed
        else "engine.simulation.unshaded"
    )
    import importlib

    module = importlib.import_module(target)
    original = module.calculate_poa

    def inject(irradiance, solar, **kwargs):
        poa = original(irradiance, solar, **kwargs)
        frame = poa.frame.copy()
        row = irradiance.frame.index[irradiance.frame.ghi_w_m2 > 0][0]
        frame.loc[row, ["poa_sky_diffuse_w_m2", "poa_isotropic_w_m2"]] = np.nan
        return PlaneOfArrayResult(frame, poa.metadata)

    monkeypatch.setattr(module, "calculate_poa", inject)
    if not detailed:
        p = Project(tmp_path, count=18)
        with pytest.raises((RuntimeError, ValueError), match="reconcile|finite"):
            p.client.post(p.url + "/simulate", json={})
    else:
        from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
        from tests.unit.test_phase69a_canonical_dispatch import _run
        from engine.simulation.optics_thermal import configure_optics_thermal

        project, config, store, _, _ = _canonical_fixture()
        configure_optics_thermal(config, default_optics_thermal_settings())
        result = _run(tmp_path, project, config, store, name="nonzero-nan")
        assert result.summary_result is None
        assert result.simulation_run["status"] == "failed"
        assert any(
            "finite" in f["message"]
            for f in result.simulation_run["validation_findings"]
        )


def test_component_collapse_rejects_negative_combined_signed_horizon():
    from shading.electrical.local_irradiance import (
        build_local_electrical_irradiance_state,
        LocalElectricalIrradianceError,
    )

    # A signed empirical term is valid, but cannot make the combined sky negative.
    h = "a" * 64
    region_map = {
        "mapping_payload_sha256": h,
        "electrical_region_map_id": "map",
        "source_scene_revision_id": "scene",
        "source_module_instance_id": "module",
        "source_module_definition_revision_id": "definition",
        "regions": [{"region_id": "r"}],
    }
    visibility = {
        "source_electrical_region_map_id": "map",
        "source_electrical_region_map_hash": h,
        "source_scene_revision_id": "scene",
        "physical_result_sha256": h,
        "receiver_granularity": "electrical_region",
        "electrical_shading_scope": "not_modeled",
        "inline_records": [
            {
                "receiver_id": "r",
                "beam_visibility_factor": 0.0,
                "sky_visibility_factor": 0.0,
                "ground_visibility_factor": 1.0,
                "directional_diffuse_visibility": {"horizon": 1.0},
                "quality_flags": [],
            }
        ],
    }
    with pytest.raises(
        LocalElectricalIrradianceError,
        match="combined component irradiance is negative",
    ):
        build_local_electrical_irradiance_state(
            region_map,
            visibility,
            unshaded_poa={
                "beam_w_m2": 100.0,
                "sky_diffuse_w_m2": 100.0,
                "ground_reflected_w_m2": 0.0,
            },
            optical_modifier={"beam": 1.0, "sky_diffuse": 1.0, "ground_reflected": 1.0},
            optical_model_manifest={
                "model_id": "independent-fixture",
                "model_version": "1",
            },
            module_temperature_c=25,
            interval_start="2025-01-01T00:00:00+00:00",
            evaluation_time="2025-01-01T00:30:00+00:00",
            component_poa={
                "beam": 100.0,
                "isotropic": 110.0,
                "circumsolar": 0.0,
                "horizon": -10.0,
                "ground": 0.0,
            },
            component_optical_modifier={
                "beam": 1.0,
                "sky": 1.0,
                "horizon": 1.0,
                "ground": 1.0,
            },
        )


def test_signed_perez_isotropic_is_preserved_when_combined_sky_is_positive():
    import numpy as np
    import pvlib
    import json
    from jsonschema import Draft202012Validator
    from shading.electrical.local_irradiance import build_local_electrical_irradiance_state

    sky = pvlib.irradiance.perez(30., 180., np.array([5.]), np.array([20.]), np.array([1365.]),
        np.array([0.]), np.array([180.]), np.array([1.]), model="allsitescomposite1990", return_components=True)
    source = {"beam": float(20 * np.cos(np.deg2rad(30))),
        "isotropic": float(sky["poa_isotropic"][0]), "circumsolar": float(sky["poa_circumsolar"][0]),
        "horizon": float(sky["poa_horizon"][0]), "ground": float(25 * .2 * (1 - np.cos(np.deg2rad(30))) / 2)}
    assert source["isotropic"] < 0 and float(sky["poa_sky_diffuse"][0]) > 0
    h = "a" * 64
    region_map = {"mapping_payload_sha256": h, "electrical_region_map_id": "map", "source_scene_revision_id": "scene",
        "source_module_instance_id": "module", "source_module_definition_revision_id": "definition", "regions": [{"region_id": "r"}]}
    visibility = {"shading_result_id": "shading:independent-fixture", "source_electrical_region_map_id": "map", "source_electrical_region_map_hash": h,
        "source_scene_revision_id": "scene", "physical_result_sha256": h, "receiver_granularity": "electrical_region",
        "electrical_shading_scope": "not_modeled", "inline_records": [{"receiver_id": "r", "beam_visibility_factor": .6,
            "sky_visibility_factor": .75, "ground_visibility_factor": .25, "directional_diffuse_visibility": {"horizon": .5}, "quality_flags": []}]}
    local = build_local_electrical_irradiance_state(region_map, visibility,
        unshaded_poa={"beam_w_m2": source["beam"], "sky_diffuse_w_m2": float(sky["poa_sky_diffuse"][0]), "ground_reflected_w_m2": source["ground"]},
        optical_modifier={"beam": .9, "sky_diffuse": .8, "ground_reflected": .6},
        optical_model_manifest={"model_id": "independent-fixture", "model_version": "1"}, module_temperature_c=25,
        interval_start="2025-01-01T00:00:00+00:00", evaluation_time="2025-01-01T00:30:00+00:00",
        component_poa=source, component_optical_modifier={"beam": .9, "sky": .8, "horizon": .7, "ground": .6})
    state = local["regions"][0]
    expected = source["beam"]*.6*.9 + source["isotropic"]*.75*.8 + source["circumsolar"]*.6*.9 + source["horizon"]*.5*.7 + source["ground"]*.25*.6
    assert state["component_state"]["post_geometry"]["isotropic"] == source["isotropic"]*.75
    assert state["effective_irradiance_w_m2"] == pytest.approx(expected, rel=0, abs=1e-12)
    schema = json.loads((__import__("pathlib").Path(__file__).resolve().parents[2] / "shading/electrical/local-electrical-irradiance-state.schema.json").read_text())
    Draft202012Validator(schema).validate(local)


def _a6_mapper_inputs():
    h = "a" * 64
    region_map = {"mapping_payload_sha256": h, "electrical_region_map_id": "map", "source_scene_revision_id": "scene",
        "source_module_instance_id": "module", "source_module_definition_revision_id": "definition", "regions": [{"region_id": "r"}]}
    visibility = {"shading_result_id": "shading:synthetic-a6", "source_electrical_region_map_id": "map", "source_electrical_region_map_hash": h,
        "source_scene_revision_id": "scene", "physical_result_sha256": h, "receiver_granularity": "electrical_region",
        "electrical_shading_scope": "not_modeled", "inline_records": [{"receiver_id": "r", "beam_visibility_factor": .6,
            "sky_visibility_factor": .75, "ground_visibility_factor": .25, "directional_diffuse_visibility": {"horizon": .5}, "quality_flags": []}]}
    kwargs = dict(unshaded_poa={"beam_w_m2": 100., "sky_diffuse_w_m2": 55., "ground_reflected_w_m2": 20.},
        optical_modifier={"beam": 1.001, "sky_diffuse": 1.002, "ground_reflected": 1.003},
        optical_model_manifest={"model_id": "synthetic-a6", "model_version": "1"}, module_temperature_c=25.,
        interval_start="2025-01-01T00:00:00+00:00", evaluation_time="2025-01-01T00:30:00+00:00",
        component_poa={"beam": 100., "isotropic": 40., "circumsolar": 10., "horizon": 5., "ground": 20.},
        component_optical_modifier={"beam": 1.001, "sky": 1.002, "horizon": 1.003, "ground": 1.004})
    return region_map, visibility, kwargs


@pytest.mark.parametrize("factor", [-0.001, float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("channel", ["beam", "sky", "horizon", "ground"])
def test_component_path_refuses_bad_optics_and_still_bounds_visibility(factor, channel):
    from shading.electrical.local_irradiance import build_local_electrical_irradiance_state, LocalElectricalIrradianceError
    region_map, visibility, kwargs = _a6_mapper_inputs()
    kwargs["component_optical_modifier"][channel] = factor
    with pytest.raises(LocalElectricalIrradianceError, match="finite|non-negative"):
        build_local_electrical_irradiance_state(region_map, visibility, **kwargs)
    legacy_channel = {"beam": "beam", "sky": "sky_diffuse", "ground": "ground_reflected", "horizon": "beam"}[channel]
    kwargs["component_optical_modifier"][channel] = 1.001
    kwargs["optical_modifier"][legacy_channel] = factor
    with pytest.raises(LocalElectricalIrradianceError, match="finite|non-negative"):
        build_local_electrical_irradiance_state(region_map, visibility, **kwargs)
    kwargs["optical_modifier"][legacy_channel] = 1.001
    field = {"beam": "beam_visibility_factor", "sky": "sky_visibility_factor", "ground": "ground_visibility_factor"}.get(channel)
    if field:
        visibility["inline_records"][0][field] = 1.001
    else:
        visibility["inline_records"][0]["directional_diffuse_visibility"]["horizon"] = 1.001
    with pytest.raises(LocalElectricalIrradianceError, match=r"\[0, 1\]"):
        build_local_electrical_irradiance_state(region_map, visibility, **kwargs)


def test_legacy_mapper_still_refuses_optical_gain():
    from shading.electrical.local_irradiance import build_local_electrical_irradiance_state, LocalElectricalIrradianceError
    region_map, visibility, kwargs = _a6_mapper_inputs()
    kwargs.pop("component_poa"); kwargs.pop("component_optical_modifier")
    with pytest.raises(LocalElectricalIrradianceError, match=r"optical_modifier.beam must be within \[0, 1\]"):
        build_local_electrical_irradiance_state(region_map, visibility, **kwargs)


def test_optical_gain_schema_relaxation_requires_component_evidence():
    import json
    from pathlib import Path
    from jsonschema import Draft202012Validator
    from shading.electrical.local_irradiance import build_local_electrical_irradiance_state
    schema = json.loads((Path(__file__).resolve().parents[2]/"shading/electrical/local-electrical-irradiance-state.schema.json").read_text())
    validator = Draft202012Validator(schema)
    region_map, visibility, kwargs = _a6_mapper_inputs()
    local = build_local_electrical_irradiance_state(region_map, visibility, **kwargs)
    validator.validate(local)
    region = local["regions"][0]
    assert region["optical_modifier"]["beam"] > 1
    assert region["component_state"]["optical_modifier"]["beam"] > 1
    legacy = deepcopy(local);legacy["regions"][0].pop("component_state")
    assert not validator.is_valid(legacy)
    for k in legacy["regions"][0]["optical_modifier"]:
        legacy["regions"][0]["optical_modifier"][k] = 1.
    validator.validate(legacy)
    for field in ("beam", "sky_diffuse", "ground_reflected"):
        bad = deepcopy(legacy);bad["regions"][0]["optical_modifier"][field] = 1.001
        assert not validator.is_valid(bad)
    for field in ("beam", "sky_diffuse", "ground"):
        bad=deepcopy(local);bad["regions"][0]["visibility_factor"][field]=1.001
        assert not validator.is_valid(bad)


def _a6_cubic_profile():
    # Synthetic PAN-shaped profile, defined here; no user file is read or copied.
    from engine.optical import IAM_TABULATED
    return {"model_type": "tabulated", "execution_model_id": IAM_TABULATED,
        "points": [{"angle_deg": a, "modifier": m} for a,m in [(0,1),(15,1),(30,1),(45,1),(60,1),(70,.95),(80,.7),(85,.4),(90,0)]],
        "interpolation_method": "cubic", "normalize": True}


@pytest.mark.parametrize("soiling", [0., .03])
def test_detailed_cubic_iam_gain_with_soiling_reconciles(tmp_path, soiling):
    from dataclasses import replace
    import numpy as np
    from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
    from tests.unit.test_phase69a_canonical_dispatch import _run
    from engine.simulation.detailed_inputs import freeze_detailed_selection
    from engine.simulation.optics_thermal import configure_optics_thermal
    from engine.losses.settings import default_loss_settings, patch_loss_settings
    project, config, store, scene, electrical = _canonical_fixture()
    components=deepcopy(dict(store.component_revisions))
    bundle=store.detailed_electrical_inputs.replay()
    for revision,module in components.items():
        if module.get("schema_name") == "ModuleDefinition":
            module.setdefault("optical",{})["iam"]=_a6_cubic_profile()
            bundle["pinned_components"]["modules"][revision]=deepcopy(module)
    store=replace(store,component_revisions=components,detailed_electrical_inputs=freeze_detailed_selection(bundle))
    # The inherited fixture is diffuse-only. Give this regression real beam
    # irradiance with independently closed synthetic horizontal channels.
    import pandas as pd
    import pvlib
    weather=deepcopy(next(iter(store.weather_revisions.values())))
    evaluation=weather.series.index+pd.Timedelta(minutes=30)
    solar=pvlib.solarposition.get_solarposition(evaluation,-6.425,106.831,
        altitude=93.,pressure=100500.,temperature=30.)
    weather.series["dni_w_m2"]=400.
    weather.series["dhi_w_m2"]=200.
    weather.series["ghi_w_m2"]=200.+400.*np.cos(np.deg2rad(solar["zenith"].to_numpy()))
    store=replace(store,weather_revisions={weather.dataset["revision_id"]:weather})
    configure_optics_thermal(config,default_optics_thermal_settings())
    config["numerical_options"]["module_overrides"]={"module_quality_loss_fraction":0.}
    config["numerical_options"]["loss_settings"]=patch_loss_settings(default_loss_settings(),{"overrides":{"soiling":{"monthly_fractions":[soiling]*12}}})
    result=_run(tmp_path,project,config,store,name="cubic-iam-gain")
    assert result.summary_result is not None,result.simulation_run
    assert result.simulation_run["status"] in ("completed","completed_with_warnings")
    assert all(v["iam_source"]=="module_table" for v in result.simulation_run["resolved_optics_thermal_settings"]["modules"].values())
    assert any("effective irradiance after IAM and soiling (irradiance_basis=effective)" in s for s in result.simulation_run["detailed_execution_identity"]["limitations"])
    seen_gain=False
    for interval in result.detailed_backend_result.replay()["intervals"]:
        for module in interval["modules"].values():
            local=module["local_irradiance"];areas={r["region_id"]:r["area_m2"] for r in module["region_map"]["regions"]}
            total=sum(areas.values());weighted=0.
            for region in local["regions"]:
                c=region["component_state"];g=c["post_geometry"];f=c["optical_modifier"]
                expected=g["beam"]*f["beam"]+g["isotropic"]*f["sky"]+g["circumsolar"]*f["beam"]+g["horizon"]*f["horizon"]+g["ground"]*f["ground"]
                assert region["effective_irradiance_w_m2"]==pytest.approx(expected,abs=1e-10)
                assert region["optical_modifier"]["beam"]/(1-soiling)==pytest.approx(f["beam"]/(1-soiling),abs=1e-15)
                seen_gain |= f["beam"]/(1-soiling)>1 and g["beam"]>0
                weighted+=expected*areas[region["region_id"]]/total
            assert weighted==pytest.approx(module["thermal_efficiency_effective_irradiance_w_m2"],abs=1e-9)
    assert seen_gain,"fixture must execute a beam IAM factor above 1, not merely complete"


def test_real_http_module_table_and_fallback_sources_and_execution(tmp_path,monkeypatch):
    import numpy as np
    import pvlib
    import engine.simulation.unshaded as unshaded
    original=unshaded.apply_iam;observed=[]
    def capture(poa,**kwargs):
        result=original(poa,**kwargs);observed.append((poa,result,kwargs));return result
    monkeypatch.setattr(unshaded,"apply_iam",capture)
    energies=[]
    for with_table in (True,False):
        p=Project(tmp_path/("table" if with_table else "fallback"),count=18)
        bundle=p.bundle()
        for module in bundle["pinned_components"]["modules"].values():
            if with_table:module.setdefault("optical",{})["iam"]=_a6_cubic_profile()
            else:module.get("optical",{}).pop("iam",None)
        p.service.store.save(bundle)
        assert p.client.patch(p.url+"/losses",json={"overrides":{"soiling":{"monthly_fractions":[0.]*12}}}).status_code==200
        start=len(observed);response=p.client.post(p.url+"/simulate",json={})
        assert response.status_code==200,response.text
        run=response.json();assert run["status"] in ("completed","completed_with_warnings"),run
        expected_source="module_table" if with_table else "fallback_physical_glass"
        assert {m["iam_source"] for m in run["resolved_optics_thermal_settings"]["modules"].values()}=={expected_source}
        assert len(observed)>start
        for poa,optical,kwargs in observed[start:]:
            angles=np.asarray(poa.frame["aoi_deg"])
            if with_table:
                points=_a6_cubic_profile()["points"]
                direct=pvlib.iam.interp(angles,[p["angle_deg"] for p in points],[p["modifier"] for p in points],method="cubic",normalize=True)
            else:direct=pvlib.iam.physical(angles,n=1.526,K=4,L=.002,n_ar=None)
            direct=np.where(angles>=90,0,direct)
            np.testing.assert_allclose(optical.frame["iam_beam"],direct,rtol=0,atol=1e-14)
        energies.append(run["summary_result"]["total_energy_wh"])
    assert energies[0]!=pytest.approx(energies[1],rel=1e-6)


def test_basis_only_payload_preserves_default_sources_and_limitations():
    from engine.simulation.detailed_dispatch import detailed_limitations, LIMITATIONS
    settings=patch_optics_thermal_settings(default_optics_thermal_settings(),{"overrides":{"thermal":{"irradiance_basis":"incident_pre_iam"}}})
    resolved=resolve_optics_thermal_settings(settings)
    assert resolved["sources"]["thermal.irradiance_basis"]=="user"
    for key in ("mounting_preset","u_c_w_m2k","u_v_w_m2k_per_ms"):
        assert resolved["sources"]["thermal."+key]=="recommended_defaults"
    assert detailed_limitations({})==LIMITATIONS
    for basis in ("incident_pre_iam","effective"):
        s=patch_optics_thermal_settings(default_optics_thermal_settings(),{"overrides":{"thermal":{"irradiance_basis":basis}}})
        text=detailed_limitations({"numerical_options":{"optics_thermal_settings":s}})
        assert "irradiance_basis="+basis in text[1]
        assert text[:1]+text[2:]==LIMITATIONS[:1]+LIMITATIONS[2:]


def test_legacy_reset_switches_to_the_current_defaults(tmp_path):
    # LID1: on a project without stored settings (v1), "reset to recommended defaults" now means the current v2.
    p = Project(tmp_path, count=18)
    bundle = p.bundle()
    bundle.pop("loss_settings", None)
    p.service.store.save(bundle)
    response = p.client.patch(p.url + "/losses", json={"reset_to_recommended_defaults": True})
    assert response.status_code == 200, response.text
    assert p.bundle()["loss_settings"]["defaults_id"] == "recommended_defaults.v2"
