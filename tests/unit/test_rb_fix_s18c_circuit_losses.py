"""Independent circuit/cable oracles and real HTTP loss-setting regressions."""

from copy import deepcopy
import math
import numpy as np
import pandas as pd
import pytest
from engine.losses.settings import (
    default_loss_settings,
    patch_loss_settings,
    resolve_loss_settings,
    validate_ac_segment,
    bind_circuit_overrides,
    resolve_circuit_loss_settings,
    resolve_ac_segment,
    circuit_topology_sha256,
)
from tests.unit.test_rb_fix_s2_honest_preflight import Project


def cable(material="copper", **changes):
    return {
        "mode": "cable",
        "length_one_way_m": 40.0,
        "cross_section_per_phase_mm2": 120.0,
        "material": material,
        "line_voltage_v": 400.0,
        "conductor_temperature_c": 50.0,
        "phase_system": "balanced_three_phase",
        "power_factor": 1,
        **changes,
    }


def override_patch(bundle, *, inverters=None, mppts=None):
    return {
        "overrides": {
            "circuit_overrides": {
                "binding": {
                    "electrical_revision_id": bundle["electrical_design"][
                        "electrical_revision_id"
                    ]
                },
                "inverters": inverters or {},
                "mppts": mppts or {},
            }
        }
    }


def resolution(bundle, patch):
    s = patch_loss_settings(bundle.get("loss_settings", default_loss_settings()), patch)
    s = bind_circuit_overrides(s, bundle["scene"], bundle["electrical_design"])
    components = {
        **bundle["pinned_components"]["modules"],
        **bundle["pinned_components"]["inverters"],
    }
    return resolve_circuit_loss_settings(
        s, bundle["scene"], bundle["electrical_design"], components
    )


@pytest.mark.parametrize(
    "material,rho20,alpha",
    [("copper", 0.017241, 0.00393), ("aluminium", 0.028264, 0.00403)],
)
def test_cable_reference_independent_three_conductor_oracle(material, rho20, alpha):
    spec = cable(material)
    r = resolve_ac_segment(spec, rated_power_w=100000.0)
    resistance = rho20 * (1 + alpha * 30) * 40 / 120
    current = 100000 / (math.sqrt(3) * 400)
    expected = 3 * current * current * resistance
    assert r["resistance_per_phase_ohm"] == pytest.approx(resistance)
    assert r["quadratic_coefficient_per_w"] * 100000**2 == pytest.approx(expected)
    assert r["conductor_temperature_c"] == 50


@pytest.mark.parametrize(
    "change",
    [
        {"length_one_way_m": 0},
        {"cross_section_per_phase_mm2": -1},
        {"line_voltage_v": float("nan")},
        {"conductor_temperature_c": None},
        {"conductor_temperature_c": 101},
        {"power_factor": True},
        {"phase_system": "single_phase"},
        {"material": "unknown"},
        {"extra": 0},
    ],
)
def test_cable_inputs_fail_closed(change):
    with pytest.raises(ValueError):
        validate_ac_segment(cable(**change))


def test_identity_precedence_exact_redundancy_and_one_ulp(tmp_path):
    p = Project(tmp_path, count=18)
    b = p.bundle()
    iid = b["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    mid = next(
        m["mppt_instance_id"]
        for m in b["electrical_design"]["mppt_instances"]
        if m["connected_string_ids"]
    )
    inherited = resolve_loss_settings(b["loss_settings"])["values"][
        "dc_wiring_stc_fraction"
    ]
    eq = resolution(
        b, override_patch(b, inverters={iid: {"dc_wiring_stc_fraction": inherited}})
    )
    assert eq["active"] is False
    one = math.nextafter(inherited, math.inf)
    changed = resolution(
        b, override_patch(b, inverters={iid: {"dc_wiring_stc_fraction": one}})
    )
    assert (
        changed["active"] and changed["circuits"][mid]["dc_wiring_stc_fraction"] == one
    )
    specific = resolution(
        b,
        override_patch(
            b,
            inverters={
                iid: {"dc_wiring_stc_fraction": 0.1, "module_quality_fraction": -0.0075}
            },
            mppts={
                mid: {"dc_wiring_stc_fraction": 0.0, "module_quality_fraction": 0.01}
            },
        ),
    )
    assert specific["circuits"][mid]["dc_wiring_stc_fraction"] == 0
    assert set(specific["circuits"][mid]["module_quality_by_module"].values()) == {0.01}
    assert specific["circuits"][mid]["dc_wiring_source"] == "mppt_override"


def test_stale_unknown_ids_and_snapshot_identity(tmp_path):
    p = Project(tmp_path, count=18)
    b = p.bundle()
    iid = b["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    with pytest.raises(ValueError, match="unknown"):
        resolution(
            b, override_patch(b, inverters={"missing": {"dc_wiring_stc_fraction": 0.1}})
        )
    raw = patch_loss_settings(
        b["loss_settings"],
        override_patch(b, inverters={iid: {"dc_wiring_stc_fraction": 0.1}}),
    )
    bound = bind_circuit_overrides(raw, b["scene"], b["electrical_design"])
    e = deepcopy(b["electrical_design"])
    e["electrical_revision_id"] = "snapshot"
    e["inverter_instances"][0]["name"] = "renamed"
    assert (
        circuit_topology_sha256(b["scene"], e)
        == bound["overrides"]["circuit_overrides"]["binding"]["topology_sha256"]
    )
    e["inverter_instances"][0]["enabled"] = False
    with pytest.raises(ValueError, match="stale"):
        resolve_circuit_loss_settings(
            bound,
            b["scene"],
            e,
            {
                **b["pinned_components"]["modules"],
                **b["pinned_components"]["inverters"],
            },
        )


@pytest.mark.parametrize(
    "material,rho20,alpha",
    [("copper", 0.017241, 0.00393), ("aluminium", 0.028264, 0.00403)],
)
def test_real_segment_adapter_and_plant_transformer_order(material, rho20, alpha):
    from engine.losses.staged import apply_ac_segment, apply_plant_losses

    power = pd.Series(
        [100000.0, 50000.0, 0.0, -500.0],
        index=pd.date_range("2025-01-01", periods=4, freq="h"),
    )
    segment = resolve_ac_segment(cable(material), rated_power_w=100000.0)
    segment["active"] = True
    stage = apply_ac_segment(power, segment)
    r = rho20 * (1 + alpha * 30) * 40 / 120
    for p, l in zip(power, stage.loss_w):
        current = p / (math.sqrt(3) * 400)
        assert l == pytest.approx(3 * current**2 * r)
    settings = resolve_loss_settings(
        patch_loss_settings(
            default_loss_settings(),
            {
                "overrides": {
                    "transformer": {
                        "enabled": True,
                        "reference_power_w": 100000.0,
                        "iron_fraction": 0.01,
                        "copper_fraction": 0.02,
                    }
                }
            },
        )
    )
    plant = apply_plant_losses(
        power, settings, nominal_w=100000.0, plant_ac_segment=segment
    )
    np.testing.assert_allclose(plant.after_plant_ac_wiring_w, power - stage.loss_w)
    np.testing.assert_allclose(
        plant.transformer_copper_loss_w, 0.02 * (power - stage.loss_w) ** 2 / 100000
    )
    assert plant.pcc_power_w.iloc[-1] < power.iloc[-1]


def test_percentage_two_levels_named_reference_and_refusals():
    from engine.losses.staged import apply_ac_segment

    segment = resolve_ac_segment(
        {
            "mode": "percent",
            "loss_fraction": 0.02,
            "reference": "custom",
            "reference_power_w": 80000.0,
        },
        rated_power_w=100000.0,
    )
    result = apply_ac_segment(pd.Series([80000.0, 40000.0]), segment)
    assert result.loss_w.tolist() == [1600.0, 400.0]
    for bad in (
        {"mode": "percent", "loss_fraction": 0.01, "reference": "STC"},
        {
            "mode": "percent",
            "loss_fraction": 0.01,
            "reference": "rated_ac",
            "reference_power_w": 1,
        },
    ):
        with pytest.raises(ValueError):
            validate_ac_segment(bad)
    with pytest.raises(ValueError, match="bus voltage"):
        apply_ac_segment(
            pd.Series([1e20]), resolve_ac_segment(cable(), rated_power_w=100000.0)
        )


def test_real_http_overrides_plant_run_snapshot_reload_reset_and_noop(tmp_path):
    p = Project(tmp_path, count=18)
    before = p.bundle()
    iid = before["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    patch = override_patch(
        before,
        inverters={
            iid: {"dc_wiring_stc_fraction": 0.012, "module_quality_fraction": -0.0075}
        },
    )
    patch["overrides"]["plant_ac_wiring"] = cable()
    response = p.client.patch(p.url + "/losses", json=patch)
    assert response.status_code == 200, response.text
    current = p.bundle()
    revision = current["project"]["project_revision"]
    assert current["pinned_components"] == before["pinned_components"]
    assert p.client.patch(p.url + "/losses", json=patch).status_code == 200
    assert p.bundle()["project"]["project_revision"] == revision
    ready = p.client.get(p.url + "/execution-readiness")
    assert ready.status_code == 200 and ready.json()["ready"], ready.text
    response = p.client.post(p.url + "/simulate", json={})
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] in {"completed", "completed_with_warnings"}, run
    audit = run["circuit_loss_resolution"]
    assert run["resolved_loss_settings"]["status"] == "edited"
    assert audit["active"]
    assert audit["inverters"][iid]["ac_wiring"]["active"] is False
    assert audit["plant_ac_wiring"]["material"] == "copper"
    assert all(
        c["module_quality_fraction"] == -0.0075 for c in audit["circuits"].values()
    )
    rows = run["summary_result"]["loss_summary"]
    assert any(r["loss_type"] == "plant_ac_wiring" for r in rows), rows
    summary = audit["ac_summary"]
    assert summary["inverter_subtotal_energy_wh"] - sum(
        summary[k]
        for k in (
            "plant_ac_wiring_loss_energy_wh",
            "transformer_iron_loss_energy_wh",
            "transformer_copper_loss_energy_wh",
            "unavailability_loss_energy_wh",
        )
    ) == pytest.approx(summary["pcc_energy_wh"], abs=1e-6)
    assert (
        p.client.patch(
            p.url + "/losses", json={"reset_to_recommended_defaults": True}
        ).status_code
        == 200
    )
    saved = p.bundle()
    assert saved["loss_settings"] == default_loss_settings()
    assert saved["simulation_runs"][0]["circuit_loss_resolution"] == audit


def test_circuit_quality_and_wiring_independent_hand_oracles():
    from tests.unit.test_rb_fix_s18a_losses import bank, reference, settings
    from engine.losses.staged import apply_circuit_losses

    refs = {
        1: {**reference(1, 0.2), "module_quality_fraction": -0.0075},
        2: {**reference(2, 0.8), "module_quality_fraction": 0.01},
    }
    result = apply_circuit_losses(
        bank((100.0, 200.0), (10.0, 20.0)),
        settings(annual_degradation_fraction=0),
        refs,
        quality=0.0,
    )
    q1 = 1000 * (-0.0075)
    q2 = 4000 * 0.01
    i1 = (1000 - q1) / 100
    i2 = (4000 - q2) / 200
    assert result.frame.module_quality_loss_w.iloc[0] == q1 + q2
    assert result.frame.dc_wiring_loss_w.iloc[0] == pytest.approx(
        i1 * i1 * 0.2 + i2 * i2 * 0.8
    )
    assert result.metadata["circuits"]["1"]["module_quality_fraction"] == -0.0075


from tests.unit.test_rb_fix_s16_multi_group import make_design


def test_unequal_inverters_two_orientations_overrides_and_plant_conservation(
    make_design,
):
    d = make_design("clipping")
    b = d.bundle()
    from tests.unit.test_rb_fix_s16_multi_group import command

    second_inv = b["electrical_design"]["inverter_instances"][1]["inverter_instance_id"]
    tracker = next(
        m
        for m in b["electrical_design"]["mppt_instances"]
        if m["inverter_instance_id"] == second_inv and m["connected_string_ids"]
    )
    original = next(
        s
        for s in b["electrical_design"]["strings"]
        if s["string_id"] in tracker["connected_string_ids"]
    )
    batch = [command("delete_string", string_id=original["string_id"])]
    for i, path in enumerate(
        (original["module_instance_ids"][:9], original["module_instance_ids"][9:])
    ):
        sid = f"S18c-{i}"
        batch.extend(
            [
                command("create_string", string_id=sid, module_instance_ids=path),
                command(
                    "assign_strings_to_mppt",
                    string_ids=[sid],
                    mppt_instance_id=tracker["mppt_instance_id"],
                ),
            ]
        )
    for i, c in enumerate(batch):
        c["command_id"] = f"s18c-{i}"
    d.post("/electrical/commands", {"commands": batch})
    b = d.bundle()
    ids = [
        i["inverter_instance_id"] for i in b["electrical_design"]["inverter_instances"]
    ]
    rows = {
        ids[0]: {
            "dc_wiring_stc_fraction": 0.0108,
            "module_quality_fraction": -0.0075,
            "ac_wiring": {
                "mode": "percent",
                "loss_fraction": 0.007,
                "reference": "custom",
                "reference_power_w": 100000.0,
            },
        },
        ids[1]: {"dc_wiring_stc_fraction": 0.025, "module_quality_fraction": 0.01},
    }
    patch = override_patch(b, inverters=rows)
    patch["overrides"]["plant_ac_wiring"] = cable("aluminium")
    r = d.client.patch(d.url + "/losses", json=patch)
    assert r.status_code == 200, r.text
    r = d.client.post(d.url + "/simulate", json={})
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] in {"completed", "completed_with_warnings"}, run
    audit = run["circuit_loss_resolution"]
    for c in audit["circuits"].values():
        q = rows[c["inverter_instance_id"]]
        assert c["dc_wiring_stc_fraction"] == q["dc_wiring_stc_fraction"]
        assert c["module_quality_fraction"] == q["module_quality_fraction"]
        assert (
            c["resistance_ohm"]
            == q["dc_wiring_stc_fraction"]
            * c["reference_voltage_v"]
            / c["reference_current_a"]
        )
    assert len({c["reference_current_a"] for c in audit["circuits"].values()}) == 2
    breakdown = run["summary_result"]["execution_breakdown"]
    assert breakdown["plant_adjustments"]["plant_ac_wiring"] > 0
    assert breakdown["inverter_subtotal_energy_wh"] - sum(
        breakdown["plant_adjustments"].values()
    ) == pytest.approx(run["summary_result"]["total_energy_wh"], abs=1e-6)
    from tests.unit.test_rb_fix_s16_multi_group import parquet

    groups = parquet(breakdown["group_timeseries_reference"])
    for group in breakdown["groups"]:
        data = groups[groups.execution_group_id == group["execution_group_id"]]
        ref = next(
            c
            for c in audit["circuits"].values()
            if c["inverter_instance_id"] == group["inverter_instance_id"]
        )
        np.testing.assert_allclose(
            data.dc_wiring_loss_w,
            data.dc_array_current_a**2 * ref["resistance_ohm"],
            rtol=0,
            atol=1e-9,
        )
    for inv in breakdown["inverters"]:
        qloss = next(
            row["lost_energy_wh"]
            for row in inv["loss_summary"]
            if row["loss_type"] == "module_quality"
        )
        assert (qloss < 0) == (inv["inverter_instance_id"] == ids[0])
    frames = parquet(breakdown["inverter_timeseries_reference"])
    first = frames[frames.inverter_instance_id == ids[0]]
    np.testing.assert_allclose(
        first.ac_wiring_loss_w,
        0.007 * first.ac_net_output_w**2 / 100000,
        rtol=0,
        atol=1e-12,
    )


@pytest.mark.parametrize(
    "relationship,quality,expected",
    [
        ("separate_from_parameterization", -0.0075, -0.0075),
        ("embedded_in_parameterization", -0.0075, 0.0),
        ("unknown", 0.0, 0.0),
    ],
)
def test_detailed_per_mppt_evidence_ownership(relationship, quality, expected):
    from engine.losses.settings import resolve_detailed_circuit_quality

    r = {
        "active": True,
        "circuits": {
            "mppt-a": {"module_quality_by_module": {"a": quality}},
            "mppt-b": {"module_quality_by_module": {"b": 0.01}},
        },
    }
    inputs = {
        "a": {
            "evidence": {
                "evidence_id": "ea",
                "module_quality_declaration": {
                    "relationship": relationship,
                    "module_quality_loss_fraction": quality,
                },
            }
        },
        "b": {
            "evidence": {
                "evidence_id": "eb",
                "module_quality_declaration": {
                    "relationship": "separate_from_parameterization",
                    "module_quality_loss_fraction": 0.01,
                },
            }
        },
    }
    got = resolve_detailed_circuit_quality(r, inputs)
    assert got["mppt-a"]["applied_module_quality_fraction"] == expected
    assert got["mppt-b"]["applied_module_quality_fraction"] == 0.01
    if quality:
        inputs["a"]["evidence"]["module_quality_declaration"][
            "relationship"
        ] = "unknown"
        with pytest.raises(ValueError, match="calibration"):
            resolve_detailed_circuit_quality(r, inputs)
    inputs["a"]["evidence"]["module_quality_declaration"]["relationship"] = relationship
    r["circuits"]["mppt-a"]["module_quality_by_module"]["b"] = 0.01
    with pytest.raises(ValueError, match="different effective"):
        resolve_detailed_circuit_quality(r, inputs)


def test_detailed_actual_backend_two_mppt_wiring_and_plant(tmp_path):
    from dataclasses import replace
    from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
    from tests.unit.test_phase69a_canonical_dispatch import _run

    project, config, store, scene, electrical = _canonical_fixture()
    from tests.integration.test_phase69a_closure import _declare

    store = _declare(store, "separate_from_parameterization")
    electrical = deepcopy(electrical)
    first = electrical["mppt_instances"][0]
    second = deepcopy(first)
    second["mppt_instance_id"] = "s18c-mppt-two"
    second["index"] = 2
    strings = electrical["strings"]
    first["connected_string_ids"] = [strings[0]["string_id"]]
    second["connected_string_ids"] = [strings[1]["string_id"]]
    strings[1]["target_mppt_instance_id"] = second["mppt_instance_id"]
    electrical["mppt_instances"].append(second)
    electrical["inverter_instances"][0]["mppt_instance_ids"].append(
        second["mppt_instance_id"]
    )
    iid = electrical["inverter_instances"][0]["inverter_instance_id"]
    # Canonical fixture has no independent physical wire elements to remap.
    holder = {"electrical_design": electrical, "scene": scene}
    raw = patch_loss_settings(
        {**default_loss_settings(), "defaults_id": "recommended_defaults.v1"},  # LID1: hand oracle assumes LID 0 (v1)
        override_patch(
            holder,
            mppts={
                first["mppt_instance_id"]: {
                    "dc_wiring_stc_fraction": 0.01,
                    "module_quality_fraction": -0.0075,
                },
                second["mppt_instance_id"]: {
                    "dc_wiring_stc_fraction": 0.03,
                    "module_quality_fraction": 0.0,
                },
            },
        ),
    )
    raw = patch_loss_settings(
        raw,
        {
            "overrides": {
                "plant_ac_wiring": {
                    "mode": "percent",
                    "loss_fraction": 0.01,
                    "reference": "custom",
                    "reference_power_w": 5000.0,
                }
            }
        },
    )
    config["numerical_options"]["loss_settings"] = bind_circuit_overrides(
        raw, scene, electrical
    )
    store = replace(
        store, electrical_revisions={electrical["electrical_revision_id"]: electrical}
    )
    result = _run(tmp_path, project, config, store, name="s18c-detailed-two")
    assert result.summary_result is not None, result.simulation_run
    assert result.simulation_run["status"] in {
        "completed",
        "completed_with_warnings",
    }, result.simulation_run
    refs = result.simulation_run["circuit_loss_resolution"]["circuits"]
    assert refs[first["mppt_instance_id"]]["dc_wiring_stc_fraction"] == 0.01
    assert refs[second["mppt_instance_id"]]["dc_wiring_stc_fraction"] == 0.03
    assert refs[first["mppt_instance_id"]]["module_quality_fraction"] == -0.0075
    assert refs[second["mppt_instance_id"]]["module_quality_fraction"] == 0
    from engine.simulation.detailed_downstream import (
        selected_states_to_mppt_bank,
        compact_selected_states,
    )

    bank = selected_states_to_mppt_bank(
        compact_selected_states(result.detailed_backend_result)
    )
    np.testing.assert_allclose(
        result.backend_result.electrical.ledger.frame.module_quality_loss_w,
        bank[1].frame.mppt_pmp_w * (-0.0075),
        rtol=0,
        atol=1e-9,
    )
    assert any(
        r["loss_type"] == "plant_ac_wiring"
        for r in result.summary_result["loss_summary"]
    )


@pytest.mark.parametrize(
    "technology,ready",
    [
        ("mtSiMono", True),
        ("mtSiPoly", True),
        ("mtCdTe", False),
        ("mtFutureUnknown", False),
    ],
)
def test_eng3_synthetic_import_readiness_provenance_and_overlay(
    tmp_path, technology, ready
):
    from pathlib import Path
    from apps.api.server import create_app
    from fastapi.testclient import TestClient
    from components.source_overlay import (
        ComponentSourceFragment,
        build_candidate_from_fragments,
    )

    raw = (
        (Path(__file__).resolve().parents[1] / "fixtures/panond/synthetic_module.pan")
        .read_bytes()
        .replace(b"mtSiMono", technology.encode())
    )
    app = create_app(
        store_root=tmp_path / "projects", library_root=tmp_path / "library"
    )
    with TestClient(app) as c:
        r = c.post(
            "/api/component-library/imports",
            params={"filename": "invented.pan"},
            content=raw,
        )
        assert r.status_code == 200, r.text
        entry = r.json()["entry"]
        assert entry["simulation_ready"] == ready
        saved = next(
            e
            for e in app.state.project_service.library.entries(include_hidden=True)
            if e["definition"]["revision_id"] == entry["revision_id"]
        )
        if ready:
            model = saved["definition"]["electrical_models"][0]
            assert model["parameter_set"]["energy_bandgap_ref_ev"] == 1.121
            derivation = next(
                d
                for d in saved["library"]["derivations"]
                if d.get("method") == "pvsyst_crystalline_silicon_default_bandgap"
            )
            assert derivation["value"] == 1.121 and derivation["inputs"][
                "technology"
            ] == (
                "crystalline_silicon_poly"
                if technology == "mtSiPoly"
                else "crystalline_silicon_mono"
            )
            merged = build_candidate_from_fragments(
                "module",
                [ComponentSourceFragment("synthetic-source", saved["definition"])],
                candidate_id="overlay",
                definition_id="overlay",
                revision_id="overlay-r1",
            )
            assert merged["canonical_data"]["capability_flags"]["detailed_sdm_ready"]
        else:
            assert not saved["definition"]["capability_flags"]["detailed_sdm_ready"]


def test_eng3_real_http_poly_repin_strings_and_default_losses_simulate(tmp_path):
    from pathlib import Path

    p = Project(tmp_path, count=18)
    raw = (
        (Path(__file__).resolve().parents[1] / "fixtures/panond/synthetic_module.pan")
        .read_bytes()
        .replace(b"mtSiMono", b"mtSiPoly")
    )
    imported = p.client.post(
        "/api/component-library/imports",
        params={"filename": "invented-poly.pan"},
        content=raw,
    )
    assert imported.status_code == 200, imported.text
    revision = imported.json()["entry"]["revision_id"]
    before = p.bundle()
    fid = before["scene"]["pv_fields"][0]["pv_field_id"]
    response = p.client.patch(
        p.url + "/pv-fields/" + fid,
        json={
            "module_definition_revision_id": revision,
            "discard_dependent_strings": True,
        },
    )
    assert response.status_code == 200, response.text
    assert (
        p.bundle()["scene"]["pv_fields"][0]["module_definition_revision_id"] == revision
    )
    assert not p.bundle()["electrical_design"]["strings"]
    view = p.service.create_strings(
        p.pid, string_length=18, allow_shorter_remainder=False
    )
    ids = [s["string_id"] for s in view["bundle"]["electrical_design"]["strings"]]
    iid = before["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    p.service.assign_strings(p.pid, inverter_instance_id=iid, string_ids=ids)
    assert p.readiness()["ready"], p.readiness()
    response = p.client.post(p.url + "/simulate", json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] in {
        "completed",
        "completed_with_warnings",
    }, response.text
    assert response.json()["summary_result"]["total_energy_wh"] > 0


@pytest.mark.parametrize(
    "bad",
    [
        {"unknown": 1},
        {"binding": {"electrical_revision_id": "x"}, "mppts": []},
        {
            "binding": {"electrical_revision_id": "x"},
            "inverters": {"i": {"dc_wiring_stc_fraction": True}},
        },
        {
            "binding": {"electrical_revision_id": "x"},
            "mppts": {
                "m": {
                    "ac_wiring": {
                        "mode": "percent",
                        "loss_fraction": 0,
                        "reference": "rated_ac",
                    }
                }
            },
        },
        {
            "binding": {"electrical_revision_id": "x"},
            "mppts": {"m": {"module_quality_fraction": float("inf")}},
        },
        {"binding": {"electrical_revision_id": "x"}, "inverters": {"i": {"extra": 0}}},
    ],
)
def test_unknown_or_malformed_override_shape_never_silently_disappears(bad):
    with pytest.raises(ValueError):
        patch_loss_settings(
            default_loss_settings(), {"overrides": {"circuit_overrides": bad}}
        )


def test_http_unknown_stale_binding_reset_and_ordinary_noop(tmp_path):
    p = Project(tmp_path, count=18)
    b = p.bundle()
    iid = b["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    before = p.path.read_bytes()
    assert (
        p.client.patch(
            p.url + "/losses",
            json=override_patch(
                b, inverters={"not-an-inverter": {"dc_wiring_stc_fraction": 0.01}}
            ),
        ).status_code
        == 422
    )
    assert p.path.read_bytes() == before
    assert (
        p.client.patch(
            p.url + "/losses",
            json=override_patch(b, inverters={iid: {"dc_wiring_stc_fraction": 0.01}}),
        ).status_code
        == 200
    )
    b = p.bundle()
    b["electrical_design"]["strings"][0]["module_instance_ids"].reverse()
    p.service.store.save(b)
    view = p.client.get(p.url)
    assert view.status_code == 200, view.text
    assert view.json()["loss_binding_findings"][0]["rule_id"] == "LOSS_SETTINGS_INVALID"
    assert any(
        f["rule_id"] == "LOSS_SETTINGS_INVALID" for f in p.readiness()["findings"]
    )
    saved = p.path.read_bytes()
    assert p.client.post(p.url + "/simulate", json={}).status_code == 422
    assert p.path.read_bytes() == saved
    assert (
        p.client.patch(
            p.url + "/losses", json={"reset_to_recommended_defaults": True}
        ).status_code
        == 200
    )
    saved = p.path.read_bytes()
    assert p.client.patch(p.url + "/losses", json={"overrides": {}}).status_code == 200
    assert p.path.read_bytes() == saved


def test_derived_ac_values_fail_closed_on_overflow_or_underflow():
    for bad in (
        cable(line_voltage_v=1e308),
        cable(line_voltage_v=1e-308),
        cable(length_one_way_m=1e308, cross_section_per_phase_mm2=1e-308),
    ):
        with pytest.raises(ValueError):
            resolve_ac_segment(bad, rated_power_w=100000.0)


def test_real_http_mppt_precedes_inverter_and_records_origins(tmp_path):
    p = Project(tmp_path, count=18)
    b = p.bundle()
    iid = b["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    mid = next(
        m["mppt_instance_id"]
        for m in b["electrical_design"]["mppt_instances"]
        if m["connected_string_ids"]
    )
    patch = override_patch(
        b,
        inverters={
            iid: {"dc_wiring_stc_fraction": 0.1, "module_quality_fraction": 0.01}
        },
        mppts={
            mid: {"dc_wiring_stc_fraction": 0.02, "module_quality_fraction": -0.0075}
        },
    )
    response = p.client.patch(p.url + "/losses", json=patch)
    assert response.status_code == 200, response.text
    response = p.client.post(p.url + "/simulate", json={})
    assert response.status_code == 200, response.text
    ref = response.json()["circuit_loss_resolution"]["circuits"][mid]
    assert (
        ref["dc_wiring_source"] == "mppt_override"
        and ref["dc_wiring_stc_fraction"] == 0.02
    )
    assert ref["module_quality_fraction"] == -0.0075 and set(
        ref["module_quality_sources"].values()
    ) == {"mppt_override"}


def test_nullable_pinned_quality_keeps_existing_generic_zero_fallback(tmp_path):
    p = Project(tmp_path, count=18)
    b = p.bundle()
    for module in b["pinned_components"]["modules"].values():
        module.setdefault("quality", {})["default_module_quality_loss_fraction"] = None
    iid = b["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    r = resolution(
        b, override_patch(b, inverters={iid: {"dc_wiring_stc_fraction": 0.01}})
    )
    assert all(
        set(c["module_quality_by_module"].values()) == {0.0}
        for c in r["circuits"].values()
    )
    assert all(
        set(c["module_quality_sources"].values()) == {"generic_default_zero"}
        for c in r["circuits"].values()
    )
    with pytest.raises(ValueError):
        resolve_ac_segment(cable(material={}), rated_power_w=100000.0)


def test_eng3_explicit_version5_reimport_preserves_old_definition(
    tmp_path, monkeypatch
):
    from pathlib import Path
    import components.mapping as mapping
    import apps.api.component_library as library
    from apps.api.server import create_app
    from fastapi.testclient import TestClient

    raw = (
        (Path(__file__).resolve().parents[1] / "fixtures/panond/synthetic_module.pan")
        .read_bytes()
        .replace(b"mtSiMono", b"mtSiPoly")
    )
    app = create_app(
        store_root=tmp_path / "projects", library_root=tmp_path / "library"
    )
    original = mapping._convert

    def old_mapping(value, rule):
        if rule.conversion_rule == "pvsyst_technology_code" and value == "mtSiPoly":
            raise ValueError("unsupported PVsyst technology code")
        return original(value, rule)

    with TestClient(app) as client:
        with monkeypatch.context() as old:
            old.setattr(mapping, "_convert", old_mapping)
            old.setattr(library, "IMPORTER_VERSION", 4)
            imported = client.post(
                "/api/component-library/imports",
                params={"filename": "invented-poly.pan"},
                content=raw,
            )
            assert imported.status_code == 200, imported.text
            first = imported.json()["entry"]
            assert first["simulation_ready"] is False
        base = next(
            e
            for e in app.state.project_service.library.entries(include_hidden=True)
            if e["definition"]["revision_id"] == first["revision_id"]
        )
        definition = deepcopy(base["definition"])
        response = client.post(
            "/api/component-library/imports",
            params={"filename": "invented-poly.pan"},
            content=raw,
        )
        assert response.status_code == 200, response.text
        second = response.json()["entry"]
        assert (
            second["simulation_ready"] and second["revision_id"] != first["revision_id"]
        )
        assert second["remapped_from"] == first["revision_id"]
        old = next(
            e
            for e in app.state.project_service.library.entries(include_hidden=True)
            if e["definition"]["revision_id"] == first["revision_id"]
        )
        assert old["definition"] == definition and old["library"]["hidden"]


@pytest.mark.parametrize("relationship", ["unknown", "separate_from_parameterization"])
def test_detailed_loss_evidence_is_loss_settings_blocker_under_both_policies(
    tmp_path, monkeypatch, relationship
):
    from fastapi.testclient import TestClient
    from tests.unit.test_phase69b_browser_launch import setup_project, REQUEST

    app, pid, bundle = setup_project(tmp_path, dark=True)
    assets = bundle["pinned_electrical_shading_assets"]
    for evidence in assets["electrical_parameterization_evidence"].values():
        evidence["module_quality_declaration"]["relationship"] = relationship
    app.state.project_service.save_bundle(bundle)
    client = TestClient(app)
    url = f"/api/projects/{pid}"
    iid = bundle["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
    patched = client.patch(url + "/losses", json=override_patch(
        bundle, inverters={iid: {"module_quality_fraction": 0.01}}
    ))
    assert patched.status_code == 200, patched.text
    before = app.state.project_service.store.path_for(pid).read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid quality evidence must not dispatch simulation")

    monkeypatch.setattr("apps.api.study.run_validated_design_simulation", forbidden)
    for policy in ("fail_closed", "explicit_lower_fidelity"):
        request = deepcopy(REQUEST)
        request["electrical_shading_configuration"]["fallback_policy"] = policy
        ready = client.get(url + "/execution-readiness",
                           params=request["electrical_shading_configuration"])
        assert ready.status_code == 200, ready.text
        data = ready.json()
        assert data["ready"] is False
        assert data["execution_class"] == "blocked_detailed_inputs"
        findings = [f for f in data["findings"] if f["rule_id"] == "LOSS_SETTINGS_INVALID"]
        assert len(findings) == 1, data
        assert findings[0]["severity"] == "blocking_error"
        assert "module quality" in findings[0]["message"]
        assert not any(f["rule_id"] == "DETAILED_EXECUTION_PREFLIGHT" for f in data["findings"])
        assert client.post(url + "/simulate", json=request).status_code == 422
        assert app.state.project_service.store.path_for(pid).read_bytes() == before
        assert client.get(url + "/runs").json() == []
