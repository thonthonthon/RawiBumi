"""S18a independent scalar/I²R/AC oracles and real project adapter regressions."""

from copy import deepcopy
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from electrical.mppt import MPPTAggregationResult
from engine.losses.settings import (
    default_loss_settings,
    patch_loss_settings,
    resolve_loss_settings,
    circuit_reference,
)
from engine.losses.staged import (
    apply_circuit_losses,
    apply_ac_wiring,
    apply_plant_losses,
)
from engine.losses.array import apply_pre_inverter_array_losses
from engine.losses.soiling import apply_soiling
from engine.optical import OpticalResult
from tests.unit.test_rb_fix_s2_honest_preflight import Project


def settings(**overrides):
    # LID1: these hand oracles assume LID 0, i.e. the v1 defaults.
    return resolve_loss_settings(
        patch_loss_settings({**default_loss_settings(), "defaults_id": "recommended_defaults.v1"}, {"overrides": overrides})
    )


def bank(voltages=(128.0,), currents=(8.0,)):
    index = pd.date_range(
        "2025-01-01", periods=2, freq="h", tz="Asia/Jakarta", name="interval_start"
    )
    return {
        j: MPPTAggregationResult(
            j,
            (f"S{j}",),
            pd.DataFrame(
                {
                    "mppt_vmp_v": [v, 0.0],
                    "mppt_imp_a": [i, 0.0],
                    "mppt_pmp_w": [v * i, 0.0],
                    "mppt_voc_v": [v * 1.2, 0.0],
                    "mppt_isc_a": [i * 1.2, 0.0],
                    "active": [True, False],
                },
                index=index,
            ),
            {"min_operating_voltage_v": 100.0, "max_operating_voltage_v": 1000.0},
        )
        for j, (v, i) in enumerate(zip(voltages, currents), 1)
    }


def reference(key=1, resistance=0.5, module=0.0, string=0.0):
    return {
        "mppt_index": key,
        "resistance_ohm": resistance,
        "module_mismatch_fraction": module,
        "string_mismatch_fraction": string,
    }


def test_each_scalar_and_per_circuit_hand_oracle():
    s = settings(lid_fraction=0.125, annual_degradation_fraction=0.25, operating_year=1)
    result = apply_circuit_losses(
        bank(), s, {1: reference(module=0.125, string=0.25)}, quality=-0.125
    )
    raw = 1024.0
    lid = 128.0
    q = (raw - lid) * (-0.125)
    mm = (raw - lid - q) * 0.125
    sm = (raw - lid - q - mm) * 0.25
    age = (raw - lid - q - mm - sm) * 0.125
    current = (raw - lid - q - mm - sm - age) / 128
    wire = current * current * 0.5
    f = result.frame.iloc[0]
    assert f.lid_loss_w == lid
    assert f.module_quality_loss_w == q
    assert f.module_mismatch_loss_w == mm
    assert f.string_mismatch_loss_w == sm
    assert f.degradation_loss_w == age
    assert f.dc_wiring_loss_w == wire
    assert f.array_virtual_mpp_w == 128 * current - wire
    assert (
        f.raw_array_mpp_w
        - f[
            [
                "lid_loss_w",
                "module_quality_loss_w",
                "module_mismatch_loss_w",
                "string_mismatch_loss_w",
                "degradation_loss_w",
                "dc_wiring_loss_w",
            ]
        ].sum()
        == f.array_virtual_mpp_w
    )


@pytest.mark.parametrize("v,i,r", [(128.0, 8.0, 0.5), (131.73, 7.13, 0.437)])
def test_identical_circuits_global_oracle(v, i, r):
    inputs = bank((v, v), (i, i))
    s = settings(lid_fraction=0, annual_degradation_fraction=0)
    actual = apply_circuit_losses(
        inputs, s, {1: reference(1, r), 2: reference(2, r)}, quality=0
    )
    expected = apply_pre_inverter_array_losses(inputs, dc_array_resistance_ohm=r / 2)
    if v == 128:
        np.testing.assert_array_equal(
            actual.frame.dc_wiring_loss_w, expected.frame.dc_wiring_loss_w
        )
    else:
        np.testing.assert_allclose(
            actual.frame.dc_wiring_loss_w,
            expected.frame.dc_wiring_loss_w,
            atol=1e-9,
            rtol=1e-12,
        )
    for key in inputs:
        np.testing.assert_array_equal(
            actual.mppt_bank[key].frame.voltage_within_window,
            expected.mppt_bank[key].frame.voltage_within_window,
        )
        np.testing.assert_array_equal(
            actual.mppt_bank[key].frame.mppt_vmp_v,
            expected.mppt_bank[key].frame.mppt_vmp_v,
        )


def test_unequal_circuits_and_signed_ac_oracles():
    b = bank((128.0, 256.0), (8.0, 4.0))
    s = resolve_loss_settings(patch_loss_settings(
        {**default_loss_settings(), "defaults_id": "recommended_defaults.v1"},
        {"overrides": {"annual_degradation_fraction": 0}},
    ))
    result = apply_circuit_losses(
        b, s, {1: reference(1, 0.5), 2: reference(2, 2.0)}, quality=0
    )
    assert result.frame.iloc[0].dc_wiring_loss_w == 8**2 * 0.5 + 4**2 * 2.0
    p = pd.Series([800.0, -10.0, 0.0])
    ac = apply_ac_wiring(p, 0.02, 1000)
    np.testing.assert_array_equal(ac.ac_wiring_loss_w, 0.02 * p**2 / 1000)
    s = settings(
        transformer={
            "enabled": True,
            "reference_power_w": 2000.0,
            "copper_fraction": 0.01,
            "iron_fraction": 0.001,
        },
        unavailability_fraction=0.1,
    )
    plant = apply_plant_losses(ac.after_ac_wiring_w, s, nominal_w=1234.0)
    iron = 2.0
    copper = 0.01 * ac.after_ac_wiring_w**2 / 2000
    before = ac.after_ac_wiring_w - iron - copper
    np.testing.assert_array_equal(
        plant.pcc_power_w, before - 0.1 * before.clip(lower=0)
    )
    assert plant.pcc_power_w.iloc[2] == -2.0  # Energized transformer at night.


def test_local_month_soiling_and_full_attenuation():
    index = pd.DatetimeIndex(["2025-01-31T23:00+07:00", "2025-02-01T00:00+07:00"])
    optical = OpticalResult(
        pd.DataFrame(
            {
                "effective_irradiance_w_m2": [800.0, 800.0],
                "effective_poa_beam_w_m2": [700.0, 700.0],
                "effective_poa_diffuse_w_m2": [100.0, 100.0],
                "incident_poa_global_w_m2": [900.0, 900.0],
                "iam_beam": [0.9, 0.9],
            },
            index=index,
        ),
        {"model_id": "iam.none.v0.1"},
    )
    result = apply_soiling(
        optical, settings(soiling={"monthly_fractions": [0.0, 1.0] + [0.03] * 10})
    )
    assert result.frame.effective_irradiance_w_m2.tolist() == [800.0, 0.0]
    assert result.frame.soiling_loss_w_m2.tolist() == [0.0, 800.0]
    assert result.frame.iam_beam.tolist() == [0.9, 0.9]
    assert result.frame.incident_poa_global_w_m2.tolist() == [900.0, 900.0]


@pytest.mark.parametrize(
    "patch",
    [
        {"unknown": 0},
        {"lid_fraction": 1},
        {"lid_fraction": float("nan")},
        {"soiling": {"monthly_fractions": [0.03]}},
        {"soiling": {"annual_fraction": 0.1, "monthly_fractions": [0.1] * 12}},
        {"operating_year": True},
        {"annual_degradation_fraction": 0.1, "operating_year": 100},
        {"transformer": {"enabled": True}},
        {"transformer": {"unknown_switch": False}},
    ],
)
def test_strict_settings(patch):
    with pytest.raises(ValueError):
        settings(**patch)


def test_automatic_circuit_rules_nominal_reference_and_unknown():
    module = json.loads(Path("components/reference/module-ref-650.json").read_text())
    s = settings()
    ref = circuit_reference(
        s, module, modules_in_series=10, parallel_strings=3, mppt_index=2
    )
    assert ref["reference_voltage_v"] == 430
    assert ref["reference_current_a"] == 15.12 * 3
    assert ref["resistance_ohm"] == 0.015 * 430 / (15.12 * 3)
    assert (
        ref["module_mismatch_fraction"] == 0.02
        and ref["string_mismatch_fraction"] == 0.001
    )
    module["technology"] = "unknown"
    module["cell_architecture"]["cell_technology"] = None
    with pytest.raises(ValueError, match="technology"):
        circuit_reference(
            s, module, modules_in_series=10, parallel_strings=3, mppt_index=2
        )
    ref = circuit_reference(
        settings(module_mismatch_fraction=0.01),
        module,
        modules_in_series=10,
        parallel_strings=3,
        mppt_index=2,
    )
    assert ref["module_mismatch_fraction"] == 0.01


def test_http_settings_roundtrip_noop_revision_and_defaults_run(tmp_path):
    p = Project(tmp_path, count=18)
    before = p.bundle()
    url = p.url + "/losses"
    response = p.client.patch(
        url, json={"overrides": {"soiling": {"annual_fraction": 0.08}}}
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert (
        saved["resolved_loss_settings"]["values"]["soiling"]["monthly_fractions"]
        == [0.08] * 12
    )
    after = p.bundle()
    assert (
        after["scene"] == before["scene"]
        and after["electrical_design"] == before["electrical_design"]
    )
    assert (
        after["project"]["project_revision"]["revision_number"]
        == before["project"]["project_revision"]["revision_number"] + 1
    )
    revision = after["updated_at"]
    assert (
        p.client.patch(
            url, json={"overrides": {"soiling": {"annual_fraction": 0.08}}}
        ).status_code
        == 200
    )
    assert p.bundle()["updated_at"] == revision
    run = p.client.post(p.url + "/simulate", json={})
    assert run.status_code == 200, run.text
    run = run.json()
    assert run["status"] in ("completed", "completed_with_warnings"), run
    assert (
        run["resolved_loss_settings"]["values"]["soiling"]["monthly_fractions"]
        == [0.08] * 12
    )
    assert [x["loss_type"] for x in run["summary_result"]["loss_summary"]][:3] == [
        "soiling",
        "module_operating_effects",
        "lid",
    ]
    assert (
        p.client.patch(url, json={"reset_to_recommended_defaults": True}).status_code
        == 200
    )
    assert p.bundle()["loss_settings"]["overrides"] == {}
    assert (
        p.bundle()["simulation_runs"][0]["resolved_loss_settings"]
        == run["resolved_loss_settings"]
    )


@pytest.mark.parametrize("mixed", [False, True])
def test_detailed_soiling_and_dispersion_do_not_downgrade(tmp_path, mixed):
    from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
    from tests.unit.test_phase69a_canonical_dispatch import _run

    project, config, store, scene, electrical = _canonical_fixture()
    if mixed:
        from dataclasses import replace

        scene, electrical = deepcopy(scene), deepcopy(electrical)
        removed = electrical["strings"][-1]["module_instance_ids"].pop()
        scene["module_instances"] = [
            m for m in scene["module_instances"] if m["module_instance_id"] != removed
        ]
        scene["pv_fields"][0]["generated_module_instance_ids"].remove(removed)
        scene["pv_fields"][0]["modules_per_row"] = 3
        store = replace(
            store,
            scene_revisions={scene["revision_id"]: scene},
            electrical_revisions={electrical["electrical_revision_id"]: electrical},
        )
    config["numerical_options"]["module_overrides"] = {
        "module_quality_loss_fraction": 0.0
    }
    config["numerical_options"]["loss_settings"] = patch_loss_settings(
        default_loss_settings(),
        {
            "overrides": {
                "module_mismatch_fraction": 0.012,
                "string_mismatch_fraction": 0.007,
            }
        },
    )
    result = _run(tmp_path, project, config, store, name="s18a-detailed")
    assert result.summary_result is not None, result.simulation_run
    assert result.simulation_run["status"] in (
        "completed",
        "completed_with_warnings",
    ), result.simulation_run
    snapshot = result.summary_result["resolved_loss_settings"]
    assert snapshot["method"] == "detailed_iv_plus_dispersion_scalar"
    if mixed:
        assert all(
            ref["method"] == "pinned_clear_stc_iv"
            for ref in snapshot["circuits"].values()
        )
        for ref in snapshot["circuits"].values():
            assert ref["reference_voltage_v"] > 0 and ref["reference_current_a"] > 0
            assert ref["module_revision_id"] is None
            assert (
                ref["reference_irradiance_w_m2"] == 1000
                and ref["reference_temperature_c"] == 25
            )
    for ref in snapshot["circuits"].values():
        assert (
            ref["module_mismatch_fraction"] == 0.012
            and ref["string_mismatch_fraction"] == 0.007
        )
    for interval in result.detailed_backend_result.replay()["intervals"]:
        for m in interval["modules"].values():
            assert m["thermal_efficiency_effective_irradiance_w_m2"] == pytest.approx(
                m["post_iam_pre_soiling_w_m2"] * 0.97, abs=1e-9
            )
            assert m["soiling_loss_w_m2"] == pytest.approx(
                m["post_iam_pre_soiling_w_m2"] * 0.03, abs=1e-9
            )
            assert (
                m["local_irradiance"]["optical_model_manifest"]["loss_settings_sha256"]
                == snapshot["settings_sha256"]
            )
    frame = result.backend_result.electrical.ledger.frame
    np.testing.assert_allclose(
        frame.module_mismatch_loss_w, frame.after_module_quality_w * 0.012, atol=1e-9
    )
    np.testing.assert_allclose(
        frame.string_mismatch_loss_w, frame.after_module_mismatch_w * 0.007, atol=1e-9
    )

    if not mixed:
        from engine.simulation.canonical import _select_weather_period
        from engine.simulation.detailed_dispatch import (
            _prepare_backend,
            scientific_configuration,
        )
        from engine.simulation.detailed_backend import execute_detailed_mppt_backend
        from engine.simulation.detailed_downstream import (
            compact_selected_states,
            execute_detailed_downstream,
        )
        from engine.simulation.artifacts import canonical_object_sha256

        args = _prepare_backend(
            config,
            store,
            scene,
            electrical,
            [],
            "unbounded",
            project["project_revision_id"],
            "2026-11-02T00:00:00Z",
        )
        unbounded = execute_detailed_mppt_backend(
            _select_weather_period(
                next(iter(store.weather_revisions.values())), config
            ),
            scientific_input_sha256=result.detailed_backend_result.replay()[
                "scientific_input_sha256"
            ],
            scientific_configuration=config,
            frozen_selection=store.detailed_electrical_inputs,
            **args,
        )
        try:
            assert unbounded.interval_store is None
            assert result.detailed_backend_result.interval_store is not None
            assert (
                unbounded.numerical_result_sha256
                == result.detailed_backend_result.numerical_result_sha256
            )
            replay = execute_detailed_downstream(
                compact_selected_states(unbounded),
                module_configs=args["module_configs"],
                module_inputs=args["module_inputs"],
            )
            pd.testing.assert_frame_equal(
                replay.electrical.ledger.frame,
                result.backend_result.electrical.ledger.frame,
            )
        finally:
            unbounded.close()
        changed = deepcopy(config)
        changed["numerical_options"]["loss_settings"] = patch_loss_settings(
            config["numerical_options"]["loss_settings"],
            {"overrides": {"soiling": {"annual_fraction": 0.08}}},
        )
        assert canonical_object_sha256(
            scientific_configuration(changed)
        ) != canonical_object_sha256(scientific_configuration(config))


from tests.unit.test_rb_fix_s16_multi_group import make_design


def test_multi_inverter_plant_losses_and_circuit_reconciliation(make_design):
    d = make_design("clipping")
    r = d.client.patch(
        d.url + "/losses",
        json={
            "overrides": {
                "ac_wiring_nominal_fraction": 0.01,
                "transformer": {"enabled": True, "copper_fraction": 0.015},
                "unavailability_fraction": 0.02,
            }
        },
    )
    assert r.status_code == 200, r.text
    run = d.post("/simulate", {})
    assert run["status"] in ("completed", "completed_with_warnings"), run
    summary = run["summary_result"]
    breakdown = summary["execution_breakdown"]
    assert len(breakdown["inverters"]) == 2
    from tests.unit.test_rb_fix_s16_multi_group import parquet

    frames = parquet(breakdown["inverter_timeseries_reference"])
    assert len({row["nominal_ac_power_w"] for row in breakdown["inverters"]}) == 2
    for row in breakdown["inverters"]:
        frame = frames[frames.inverter_instance_id == row["inverter_instance_id"]]
        np.testing.assert_allclose(
            frame.ac_wiring_loss_w,
            0.01 * frame.ac_net_output_w**2 / row["nominal_ac_power_w"],
            atol=1e-9,
            rtol=1e-12,
        )
    assert breakdown["inverter_subtotal_energy_wh"] - sum(
        breakdown["plant_adjustments"].values()
    ) == pytest.approx(summary["total_energy_wh"], abs=1e-6)
    assert breakdown["plant_adjustments"]["transformer_iron"] > 0
    assert all(
        next(l for l in row["loss_summary"] if l["loss_type"] == "ac_wiring")[
            "lost_energy_wh"
        ]
        > 0
        for row in breakdown["inverters"]
    )


def test_zero_new_stages_preserve_common_single_circuit_values():
    inputs = bank((131.73,), (7.13,))
    s = settings(annual_degradation_fraction=0, lid_fraction=0)
    actual = apply_circuit_losses(inputs, s, {1: reference(1, 0)}, quality=-0.0075)
    expected = apply_pre_inverter_array_losses(
        inputs, module_quality_loss_fraction=-0.0075
    )
    for column in expected.frame:
        if column in actual.frame:
            np.testing.assert_array_equal(actual.frame[column], expected.frame[column])
    pd.testing.assert_frame_equal(
        actual.mppt_bank[1].frame, expected.mppt_bank[1].frame
    )


def test_circuit_excessive_voltage_drop_refuses():
    with pytest.raises(ValueError, match="voltage drop"):
        apply_circuit_losses(
            bank(),
            resolve_loss_settings(patch_loss_settings(
                {**default_loss_settings(), "defaults_id": "recommended_defaults.v1"},
                {"overrides": {"annual_degradation_fraction": 0}},
            )),
            {1: reference(resistance=100)},
            quality=0,
        )


def test_two_genuinely_different_synthetic_modules_and_per_circuit_reference(
    make_design, tmp_path
):
    from components.candidates import build_module_candidate
    from components.pan import map_pan, parse_pan_text
    from engine.module import extract_validated_pvsyst_parameter_set
    from tests.unit.test_rb_fix_s16_multi_group import command, parquet

    d = make_design("orientations")
    source = Path("components/reference/module-uat-550.pan").read_text()
    # Synthetic second product: a full extra series-cell pair. All V-related source
    # parameters scale together; electrical model fitting/validation remains real.
    source = (
        source.replace("NCelS=72", "NCelS=74")
        .replace("Voc=49.90", "Voc=51.286111111111")
        .replace("Vmp=41.96", "Vmp=43.125555555556")
        .replace("PNom=550.0", "PNom=565.277777777778")
        .replace("muVocSpec=-128.0", "muVocSpec=-131.555555555556")
        .replace("RSerie=0.203", "RSerie=0.208638888889")
    )
    # Also change current by 2%, scaling the electrical resistances consistently.
    source = (
        source.replace("Isc=14.000", "Isc=14.280")
        .replace("Imp=13.110", "Imp=13.3722")
        .replace("muISC=7.28", "muISC=7.4256")
        .replace("PNom=565.277777777778", "PNom=576.583333333333")
        .replace("RSerie=0.208638888889", "RSerie=0.204547930283")
        .replace("RShunt=300", "RShunt=302.287581699346")
        .replace("Rp_0=2000", "Rp_0=2015.25054466231")
    )
    candidate = build_module_candidate(
        map_pan(parse_pan_text(source)),
        candidate_id="s18a-synthetic",
        module_definition_id="s18a-second",
        revision_id="s18a-second-r1",
        source_id="s18a-fictional-pan",
    )
    module = candidate["canonical_data"]
    extract_validated_pvsyst_parameter_set(module)
    service = d.app.state.project_service
    service.catalog["modules"][module["revision_id"]] = module
    bundle = d.bundle()
    second = bundle["scene"]["pv_fields"][1]
    changed = d.client.patch(
        d.url + "/pv-fields/" + second["pv_field_id"],
        json={
            "module_definition_revision_id": module["revision_id"],
            "discard_dependent_strings": True,
        },
    )
    assert changed.status_code == 200, changed.text
    b = d.bundle()
    field = next(
        f for f in b["scene"]["pv_fields"] if f["pv_field_id"] == second["pv_field_id"]
    )
    ids = [
        m["module_instance_id"]
        for m in b["scene"]["module_instances"]
        if m["pv_field_id"] == field["pv_field_id"]
    ]
    target = b["electrical_design"]["mppt_instances"][1]["mppt_instance_id"]
    d.post(
        "/electrical/commands",
        {
            "commands": [
                command("create_string", string_id="S002", module_instance_ids=ids),
                command(
                    "assign_strings_to_mppt",
                    string_ids=["S002"],
                    mppt_instance_id=target,
                ),
            ]
        },
    )
    summary, result = d.execute(
        "adapter",
        tmp_path / "execution",
        lambda c: c["numerical_options"].update(loss_settings=default_loss_settings()),
    )
    groups = list(result.backend_result.groups.values())
    assert len({g.config.module_definition["revision_id"] for g in groups}) == 2
    refs = []
    for group in groups:
        ref = next(iter(group.array_losses.metadata["circuits"].values()))
        refs.append(ref)
        stc = group.config.module_definition["stc"]
        ns = group.config.modules_in_series
        expected_r = 0.015 * (ns * stc["vmp_v"]) / (stc["imp_a"])
        assert ref["resistance_ohm"] == expected_r
        current = group.array_losses.frame.before_dc_wiring_w / (
            group.dc.coupled_module.electrical.frame.vmp_v * ns
        )
        expected_loss = (current.fillna(0) ** 2) * expected_r
        np.testing.assert_allclose(
            group.array_losses.frame.dc_wiring_loss_w,
            expected_loss,
            atol=1e-7,
            rtol=1e-12,
        )
    assert refs[0]["reference_voltage_v"] != refs[1]["reference_voltage_v"]
    assert refs[0]["reference_current_a"] != refs[1]["reference_current_a"]


def test_http_invalid_loss_patch_is_atomic_and_old_projects_inherit_without_write(
    tmp_path,
):
    p = Project(tmp_path, count=18)
    bundle = p.bundle()
    bundle.pop("loss_settings")
    p.service.store.save(bundle)
    before = p.path.read_bytes()
    view = p.client.get(p.url)
    assert view.status_code == 200
    assert view.json()["resolved_loss_settings"]["status"] == "recommended_defaults"
    assert p.path.read_bytes() == before
    for body in (
        {"overrides": {"lid_fraction": 1}},
        {"overrides": {"transformer": {"enabled": True}}},
        {"wat": True},
        {"overrides": {"soiling": {"monthly_fractions": [0.1] * 11}}},
    ):
        response = p.client.patch(p.url + "/losses", json=body)
        assert response.status_code == 422, response.text
        assert isinstance(response.json()["detail"], str)
        assert p.path.read_bytes() == before
    run = p.client.post(p.url + "/simulate", json={})
    assert run.status_code == 200, run.text
    assert (
        run.json()["resolved_loss_settings"]["defaults_id"] == "recommended_defaults.v1"
    )
    assert (
        run.json()["resolved_loss_settings"]["values"]["degradation_fraction"] == 0.002
    )
    assert "pvsyst" not in json.dumps(run.json()["resolved_loss_settings"]).lower()
    payload = p.client.get("/api/simulation-defaults").json()
    assert "pvsyst" not in json.dumps(payload).lower()


def test_settings_reference_default_version_schema_and_repeated_partial_patch():
    import jsonschema

    schema = json.loads(Path("schemas/loss-settings.schema.json").read_text())
    original = default_loss_settings()
    jsonschema.validate(original, schema)
    one = patch_loss_settings(
        original,
        {
            "overrides": {
                "soiling": {"annual_fraction": 0.04},
                "module_mismatch_fraction": 0.0,
            }
        },
    )
    two = patch_loss_settings(
        one,
        {
            "overrides": {
                "soiling": {"monthly_fractions": [0.01] * 12},
                "module_mismatch_fraction": None,
            }
        },
    )
    jsonschema.validate(two, schema)
    assert (
        resolve_loss_settings(two)["values"]["soiling"]["monthly_fractions"]
        == [0.01] * 12
    )
    assert "module_mismatch_fraction" not in two["overrides"]
    assert resolve_loss_settings(one)["sources"]["module_mismatch_fraction"] == "user"
    assert resolve_loss_settings(one)["sources"]["soiling.monthly_fractions"] == "user"
    assert original["overrides"] == {}
    with pytest.raises(ValueError, match="unsupported"):
        resolve_loss_settings({**original, "defaults_id": "unknown"})


def test_dark_state_and_zero_power_full_soiling_no_fabricated_voltage():
    b = bank()
    f = b[1].frame
    f["active"] = False
    f["availability"] = "inactive_dark"
    f["mppt_pmp_w"] = 0.0
    for key in ("mppt_vmp_v", "mppt_imp_a", "mppt_voc_v", "mppt_isc_a"):
        f[key] = np.nan
    resolved = resolve_loss_settings({**default_loss_settings(), "defaults_id": "recommended_defaults.v1"})
    result = apply_circuit_losses(b, resolved, {1: reference()}, quality=0)
    assert result.frame.array_virtual_mpp_w.eq(0).all()
    assert (
        result.mppt_bank[1]
        .frame[["mppt_vmp_v", "mppt_imp_a", "mppt_voc_v", "mppt_isc_a"]]
        .isna()
        .all()
        .all()
    )


def test_unknown_technology_is_a_readiness_finding_until_explicit_override(tmp_path):
    p = Project(tmp_path, count=18)
    b = p.bundle()
    for module in b["pinned_components"]["modules"].values():
        module["technology"] = "unknown"
    p.service.store.save(b)
    ready = p.readiness()
    assert ready["ready"] is False
    assert any(
        f["rule_id"] == "LOSS_SETTINGS_INVALID" and "technology" in f["message"]
        for f in ready["findings"]
    )
    before = p.path.read_bytes()
    response = p.client.post(p.url + "/simulate", json={})
    assert response.status_code == 422
    assert p.path.read_bytes() == before
    response = p.client.patch(
        p.url + "/losses", json={"overrides": {"module_mismatch_fraction": 0.02}}
    )
    assert response.status_code == 200, response.text
    assert p.readiness()["ready"] is True


def test_browser_readiness_reports_explicit_global_resistance_before_run(
    make_design, monkeypatch
):
    import apps.api.study as study

    d = make_design("orientations")
    original = study._phase5_options

    def options():
        result = original()
        result["numerical_options"]["losses"]["dc_array_resistance_ohm"] = 0.1
        return result

    monkeypatch.setattr(study, "_phase5_options", options)
    readiness = d.client.get(d.url + "/execution-readiness")
    assert readiness.status_code == 200
    assert readiness.json()["ready"] is False
    assert any(
        f["rule_id"] == "SIMULATION_SCOPE_MULTI_GROUP_DC_RESISTANCE"
        for f in readiness.json()["findings"]
    )
    before = d.app.state.project_service.store.path_for(d.project_id).read_bytes()
    response = d.client.post(d.url + "/simulate", json={})
    assert response.status_code == 422
    assert (
        d.app.state.project_service.store.path_for(d.project_id).read_bytes() == before
    )


@pytest.mark.parametrize("technology", [None, "n_type", "p_type", "unknown"])
def test_doping_does_not_invent_an_automatic_material_category(technology):
    module = json.loads(Path("components/reference/module-ref-650.json").read_text())
    module["technology"] = technology
    module["cell_architecture"]["cell_technology"] = "n_type"
    with pytest.raises(ValueError, match="technology"):
        circuit_reference(
            settings(), module, modules_in_series=10, parallel_strings=1, mppt_index=1
        )


@pytest.mark.parametrize(
    "year, loss, after", [(1, 2.048, 1021.952), (10, 38.912, 985.088)]
)
def test_midpoint_ageing_year_one_and_ten_hand_values(year, loss, after):
    resolved = resolve_loss_settings(patch_loss_settings(
        {**default_loss_settings(), "defaults_id": "recommended_defaults.v1"},
        {"overrides": {"annual_degradation_fraction": 0.004, "operating_year": year}},
    ))
    result = apply_circuit_losses(
        bank(), resolved, {1: reference(resistance=0)}, quality=0
    )
    assert result.frame.iloc[0].degradation_loss_w == loss
    assert result.frame.iloc[0].array_virtual_mpp_w == after


@pytest.mark.parametrize(
    "fraction, expected", [(0.0, [100.0, -10.0, 0.0]), (1.0, [0.0, -10.0, 0.0])]
)
def test_unavailability_boundaries_preserve_imports(fraction, expected):
    output = apply_plant_losses(
        pd.Series([100.0, -10.0, 0.0]),
        settings(unavailability_fraction=fraction),
        nominal_w=1000.0,
    )
    assert output.pcc_power_w.tolist() == expected


@pytest.mark.parametrize(
    "technology, series_table",
    [
        ("topcon", [(1, 0.0), (2, 0.005), (3, 0.01), (4, 0.02)]),
        ("cdte", [(1, 0.0), (2, 0.0025), (3, 0.005), (4, 0.01)]),
    ],
)
def test_version_one_automatic_tables_at_every_boundary(technology, series_table):
    module = {
        "revision_id": "synthetic-table-basis-r1",
        "technology": technology,
        "stc": {"vmp_v": 40.0, "imp_a": 10.0},
    }
    for count, expected_module in series_table:
        for parallel, expected_string in [
            (1, 0.0),
            (2, 0.0005),
            (3, 0.001),
            (10, 0.001),
            (11, 0.0015),
        ]:
            reference = circuit_reference(
                settings(),
                module,
                modules_in_series=count,
                parallel_strings=parallel,
                mppt_index=1,
            )
            assert reference["module_mismatch_fraction"] == expected_module
            assert reference["string_mismatch_fraction"] == expected_string


def _a2_browser_project(tmp_path, *, mixed=False):
    from tests.unit.test_phase69b_browser_launch import setup_project
    from fastapi.testclient import TestClient

    app, pid, bundle = setup_project(tmp_path, dark=True)
    if mixed:
        removed = bundle["electrical_design"]["strings"][-1][
            "module_instance_ids"
        ].pop()
        bundle["scene"]["module_instances"] = [
            m
            for m in bundle["scene"]["module_instances"]
            if m["module_instance_id"] != removed
        ]
        bundle["scene"]["pv_fields"][0]["generated_module_instance_ids"].remove(removed)
        bundle["scene"]["pv_fields"][0]["modules_per_row"] = 3
        app.state.project_service.store.save(bundle)
    return app, pid, TestClient(app)


def test_a2_agreeing_automatic_detailed_fractions_run_without_override(tmp_path):
    from tests.unit.test_phase69b_browser_launch import REQUEST

    app, pid, client = _a2_browser_project(tmp_path)
    url = f"/api/projects/{pid}"
    ready = client.get(
        url + "/execution-readiness", params=REQUEST["electrical_shading_configuration"]
    )
    assert ready.status_code == 200 and ready.json()["ready"], ready.text
    response = client.post(url + "/simulate", json=REQUEST)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] in ("completed", "completed_with_warnings"), run
    for reference in run["resolved_loss_settings"]["circuits"].values():
        assert reference["module_mismatch_fraction"] == 0.005
        assert reference["string_mismatch_fraction"] == 0.0005
        assert reference["module_mismatch_source"] == "recommended_defaults"


def test_a2_disagreeing_automatic_fractions_refused_before_dispatch(
    tmp_path, monkeypatch
):
    from tests.unit.test_phase69b_browser_launch import REQUEST

    app, pid, client = _a2_browser_project(tmp_path, mixed=True)
    url = f"/api/projects/{pid}"
    before = app.state.project_service.store.path_for(pid).read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "dispersion preflight must refuse before numerical dispatch"
        )

    monkeypatch.setattr("apps.api.study.run_validated_design_simulation", forbidden)
    for policy in ("fail_closed", "explicit_lower_fidelity"):
        request = deepcopy(REQUEST)
        request["electrical_shading_configuration"]["fallback_policy"] = policy
        ready = client.get(
            url + "/execution-readiness",
            params=request["electrical_shading_configuration"],
        )
        assert ready.status_code == 200, ready.text
        assert ready.json()["ready"] is False
        assert ready.json()["execution_class"] == "blocked_detailed_inputs"
        message = " ".join(f["message"] for f in ready.json()["findings"])
        for text in ("INV-01", "MPPT 1", "0%", "0.5%", "override"):
            assert text in message, message
        assert client.post(url + "/simulate", json=request).status_code == 422
        assert app.state.project_service.store.path_for(pid).read_bytes() == before
        assert client.get(url + "/runs").json() == []


@pytest.mark.parametrize("override", [0.0, 0.012])
def test_a2_explicit_zero_and_nonzero_detailed_overrides_run(tmp_path, override):
    from tests.unit.test_phase69b_browser_launch import REQUEST

    app, pid, client = _a2_browser_project(tmp_path, mixed=True)
    url = f"/api/projects/{pid}"
    response = client.patch(
        url + "/losses", json={"overrides": {"module_mismatch_fraction": override}}
    )
    assert response.status_code == 200, response.text
    ready = client.get(
        url + "/execution-readiness", params=REQUEST["electrical_shading_configuration"]
    )
    assert ready.status_code == 200 and ready.json()["ready"], ready.text
    response = client.post(url + "/simulate", json=REQUEST)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] in ("completed", "completed_with_warnings"), run
    assert (
        run["resolved_loss_settings"]["method"] == "detailed_iv_plus_dispersion_scalar"
    )
    for reference in run["resolved_loss_settings"]["circuits"].values():
        assert reference["module_mismatch_fraction"] == override
        assert reference["module_mismatch_source"] == "user"
        assert reference["string_mismatch_fraction"] == 0.0005


def test_a2_different_material_rules_share_the_same_detailed_policy():
    from engine.losses.settings import resolve_detailed_dispersion

    strings = [{"string_id": "S1", "module_instance_ids": ["a", "b", "c", "d"]}]
    modules = {mid: {"technology": "topcon"} for mid in "abcd"}
    modules["d"] = {"technology": "cdte"}
    with pytest.raises(ValueError, match=r"INV-A.*MPPT west.*1%.*2%.*override"):
        resolve_detailed_dispersion(
            settings(),
            strings=strings,
            modules=modules,
            inverter_name="INV-A",
            mppt_name="west",
        )
    resolved = resolve_detailed_dispersion(
        settings(module_mismatch_fraction=0.0),
        strings=strings,
        modules=modules,
        inverter_name="INV-A",
        mppt_name="west",
    )
    assert resolved == {
        "module_mismatch_fraction": 0.0,
        "string_mismatch_fraction": 0.0,
    }


def test_a2_agreeing_mixed_lengths_do_not_require_override():
    from engine.losses.settings import resolve_detailed_dispersion

    strings = [
        {"string_id": "S1", "module_instance_ids": ["a1", "a2", "a3", "a4"]},
        {"string_id": "S2", "module_instance_ids": ["b1", "b2", "b3", "b4", "b5"]},
    ]
    modules = {
        mid: {"technology": "topcon"}
        for string in strings
        for mid in string["module_instance_ids"]
    }
    assert resolve_detailed_dispersion(
        settings(),
        strings=strings,
        modules=modules,
        inverter_name="INV-A",
        mppt_name="west",
    ) == {"module_mismatch_fraction": 0.02, "string_mismatch_fraction": 0.0005}


@pytest.mark.parametrize("detailed", [False, True])
def test_conflicting_wiring_modes_refused_in_single_inverter_readiness(
    tmp_path, monkeypatch, detailed
):
    import apps.api.study as study
    from tests.unit.test_phase69b_browser_launch import REQUEST

    if detailed:
        app, pid, client = _a2_browser_project(tmp_path)
    else:
        p = Project(tmp_path, count=18)
        app, pid, client = p.app, p.pid, p.client
    url = f"/api/projects/{pid}"
    original = study._phase5_options

    def options():
        result = original()
        result["numerical_options"]["losses"]["dc_array_resistance_ohm"] = 0.1
        return result

    monkeypatch.setattr(study, "_phase5_options", options)

    def forbidden(*args, **kwargs):
        raise AssertionError("conflicting wiring must not reach numerical dispatch")

    monkeypatch.setattr(study, "run_validated_design_simulation", forbidden)
    before = app.state.project_service.store.path_for(pid).read_bytes()
    ready = client.get(
        url + "/execution-readiness",
        params=REQUEST["electrical_shading_configuration"] if detailed else {},
    )
    assert ready.status_code == 200 and ready.json()["ready"] is False, ready.text
    assert any(
        f["rule_id"] == "LOSS_SETTINGS_DC_WIRING_MODE_CONFLICT"
        for f in ready.json()["findings"]
    )
    if detailed:
        assert ready.json()["execution_class"] == "blocked_detailed_inputs"
    assert (
        client.post(url + "/simulate", json=REQUEST if detailed else {}).status_code
        == 422
    )
    assert app.state.project_service.store.path_for(pid).read_bytes() == before
