"""RB-LID1: versioned automatic LID, circuit provenance and history restoration."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from engine.losses.settings import (
    circuit_reference, default_loss_settings, patch_loss_settings,
    resolve_detailed_losses, resolve_lid, resolve_loss_settings, validate_loss_settings,
)
from engine.losses.staged import apply_circuit_losses
from reporting.exports.report_snapshot import loss_disclosures
from tests.unit.test_rb_fix_s18a_losses import bank
from tests.unit.test_rb_fix_s2_honest_preflight import Project
from tests.unit.test_rb_s17_history import fence


def settings(version="v2", **overrides):
    return resolve_loss_settings({**default_loss_settings(), "defaults_id": f"recommended_defaults.{version}", "overrides": overrides})


def module(technology="perc", lid=None, revision="module"):
    return {"revision_id": revision, "technology": technology, "quality": {"lid_loss_fraction": lid}, "stc": {"vmp_v": 32., "imp_a": 8.}}


def reference(s, m, index=1):
    return circuit_reference(s, m, modules_in_series=4, parallel_strings=1, mppt_index=index)


@pytest.mark.parametrize("technology,expected", [
    ("topcon", .005), ("hjt", .005), ("N-type TOPCon", .005),
    ("silicon heterojunction", .005), ("IBC", .005),
    *[(t, .015) for t in ("crystalline_silicon_mono", "crystalline_silicon_poly", "crystalline_silicon_multi", "crystalline_silicon", "monocrystalline_silicon", "polycrystalline_silicon", "mono_si", "multi_si", "c_si", "perc", "unknown", "", None)],
    *[(t, 0.) for t in ("cdte", "cadmium_telluride", "cigs", "cis", "a_si", "amorphous_silicon", "thin_film", "thinfilm")],
])
def test_generic_classes_and_v1_zero(technology, expected):
    assert resolve_lid(settings(), module(technology)) == {"lid_fraction": expected, "lid_source": "generic_default"}
    assert resolve_lid(settings("v1"), module(technology, .03))["lid_fraction"] == 0


@pytest.mark.parametrize("value", [-.01, 1., 2., float("nan"), float("inf"), True, "0.02", None])
def test_invalid_module_lid_falls_back(value):
    assert resolve_lid(settings(), module("topcon", value)) == {"lid_fraction": .005, "lid_source": "generic_default"}


@pytest.mark.parametrize("value", [0., .023, .999])
def test_file_value_and_explicit_user_precedence(value):
    m = module(lid=value)
    assert resolve_lid(settings(), m) == {"lid_fraction": value, "lid_source": "module_file"}
    for version in ("v1", "v2"):
        assert resolve_lid(settings(version, lid_fraction=.07), m) == {"lid_fraction": .07, "lid_source": "user"}


def test_two_models_keep_independent_values_sources_and_loss_energy():
    s = settings(annual_degradation_fraction=0, module_mismatch_fraction=0, string_mismatch_fraction=0, dc_wiring_stc_fraction=0)
    modules = [module(lid=.02, revision="file"), module("hjt", revision="generic")]
    refs = {i: reference(s, m, i) for i, m in enumerate(modules, 1)}
    result = apply_circuit_losses(bank((128., 128.), (8., 8.)), s, refs, quality=0)
    assert result.frame.iloc[0].lid_loss_w == 1024 * (.02 + .005)
    assert result.mppt_bank[1].frame.iloc[0].mppt_pmp_w == 1024 * (1 - .02)
    assert result.mppt_bank[2].frame.iloc[0].mppt_pmp_w == 1024 * (1 - .005)
    assert [c["lid_source"] for c in result.metadata["circuits"].values()] == ["module_file", "generic_default"]
    recorded = {**s, "circuits": result.metadata["circuits"]}
    assert [m["applied"] for m in loss_disclosures(recorded, modules)[0]["suggestions"]] == [True, False]
    assert not loss_disclosures(settings("v1"), modules)[0]["suggestions"][0]["applied"]


def test_versions_and_clear_override():
    assert default_loss_settings()["defaults_id"] == "recommended_defaults.v2"
    assert settings()["values"]["lid_fraction"] is None
    assert settings("v1")["values"]["lid_fraction"] == 0
    edited = patch_loss_settings(default_loss_settings(), {"overrides": {"lid_fraction": .03}})
    cleared = patch_loss_settings(edited, {"overrides": {"lid_fraction": None}})
    assert resolve_lid(resolve_loss_settings(cleared), module(lid=.02))["lid_fraction"] == .02
    with pytest.raises(ValueError, match="unsupported"):
        validate_loss_settings({**default_loss_settings(), "defaults_id": "unknown"})
    with pytest.raises(ValueError, match="omit"):
        validate_loss_settings({**default_loss_settings(), "overrides": {"lid_fraction": None}})


@pytest.mark.parametrize("stored", [True, False])
def test_v1_run_bytes_match_pre_lid1_commit(tmp_path, stored):
    p = Project(tmp_path, count=18)
    bundle = p.bundle()
    if stored:
        bundle["loss_settings"]["defaults_id"] = "recommended_defaults.v1"
    else:
        bundle.pop("loss_settings")
    p.service.save_bundle(bundle)
    run = p.study.run_study(p.pid)
    path = p.study.run_root / p.pid / run["simulation_run_id"]
    # Captured with the same project on the starting commit, before RB-LID1 edits.
    assert sha256((path / "timeseries.parquet").read_bytes()).hexdigest() == "d3fbb8794f18ebe459dccaa95b2096372294733fa9f7a2dea0b7df597192e2a4"
    payload = json.dumps(run["resolved_loss_settings"], sort_keys=True, separators=(",", ":")).encode()
    assert sha256(payload).hexdigest() == "3bf69349b74677789989afa2f4dd8006cc52b3088dae6e1f299b33a076c8dff9"


def test_v2_run_records_lid_and_source(tmp_path):
    p = Project(tmp_path, count=18)
    run = p.study.run_study(p.pid)
    circuits = run["resolved_loss_settings"]["circuits"]
    assert circuits
    for c in circuits.values():
        definition = p.bundle()["pinned_components"]["modules"][c["module_revision_id"]]
        assert {k: c[k] for k in ("lid_fraction", "lid_source")} == resolve_lid(settings(), definition)


def test_upgrade_is_one_undoable_save_preserving_overrides(tmp_path):
    p = Project(tmp_path, count=18, weather=False)
    before = p.service.update_losses(p.pid, {"defaults_id": "recommended_defaults.v1", "overrides": {"lid_fraction": .03, "dc_wiring_stc_fraction": .01}})
    after = p.service.update_losses(p.pid, {"defaults_id": "recommended_defaults.v2", "overrides": {}})
    assert after["bundle"]["loss_settings"]["overrides"] == before["bundle"]["loss_settings"]["overrides"]
    assert len(after["history"]["past"]) == len(before["history"]["past"]) + 1
    undone = p.service.restore_history(p.pid, **fence(after))
    assert undone["bundle"]["loss_settings"] == before["bundle"]["loss_settings"]
    redone = p.service.restore_history(p.pid, redo=True, **fence(undone, True))
    assert redone["bundle"]["loss_settings"] == after["bundle"]["loss_settings"]


def test_project_with_two_module_models_records_per_circuit_lid(tmp_path):
    p = Project(tmp_path, count=36, strings=False)
    bundle = p.bundle()
    original_id, original = next(iter(bundle["pinned_components"]["modules"].items()))
    original.setdefault("quality", {})["lid_loss_fraction"] = .02
    second_id = "mod-lid1-second-r1"
    second = deepcopy(original)
    second["revision_id"] = second_id
    second["quality"].pop("lid_loss_fraction")
    bundle["pinned_components"]["modules"][second_id] = second
    first_field = bundle["scene"]["pv_fields"][0]
    second_field = deepcopy(first_field)
    second_field["pv_field_id"] += "-second"
    second_field["module_definition_revision_id"] = second_id
    second_field["generated_module_instance_ids"] = [m["module_instance_id"] for m in bundle["scene"]["module_instances"][18:]]
    first_field["generated_module_instance_ids"] = [m["module_instance_id"] for m in bundle["scene"]["module_instances"][:18]]
    first_field["modules_per_row"] = second_field["modules_per_row"] = 18
    bundle["scene"]["pv_fields"].append(second_field)
    for m in bundle["scene"]["module_instances"][18:]:
        m["module_definition_revision_id"] = second_id
        m["pv_field_id"] = second_field["pv_field_id"]
    p.service.save_bundle(bundle)
    p.service.create_strings(p.pid, string_length=18, allow_shorter_remainder=False)
    inverter = p.bundle()["electrical_design"]["inverter_instances"][0]
    p.service.assign_strings(p.pid, inverter_instance_id=inverter["inverter_instance_id"])
    run = p.study.run_study(p.pid)
    circuits = run["resolved_loss_settings"]["circuits"]
    actual = {c["module_revision_id"]: (c["lid_fraction"], c["lid_source"]) for c in circuits.values()}
    assert actual == {original_id: (.02, "module_file"), second_id: (.015, "generic_default")}


def test_automatic_lid_requires_a_resolved_circuit_reference():
    ref = reference(settings(), module())
    ref.pop("lid_fraction")
    with pytest.raises(ValueError, match="resolve automatic LID"):
        apply_circuit_losses(bank(), settings(), {1: ref}, quality=0)


@pytest.mark.parametrize("version,override", [("v2", None), ("v1", None), ("v2", 0.), ("v2", .012)])
def test_mixed_detailed_carrier_requires_explicit_lid_when_values_differ(version, override):
    resolved = settings(version, **({} if override is None else {"lid_fraction": override}))
    args = dict(
        strings=[{"module_instance_ids": ["file", "generic"]}],
        modules={"file": module(lid=.02), "generic": module("hjt")},
        inverter_name="INV-01", mppt_name="1",
    )
    if version == "v2" and override is None:
        with pytest.raises(ValueError, match=r"INV-01, MPPT 1: automatic LID.*0.5%.*2%.*explicit LID override; 0%"):
            resolve_detailed_losses(resolved, **args)
    else:
        assert resolve_detailed_losses(resolved, **args) == {
            "module_mismatch_fraction": .005, "string_mismatch_fraction": 0.,
        }


def test_detailed_carrier_accepts_equal_lid_from_different_sources():
    assert resolve_detailed_losses(
        settings(), strings=[{"module_instance_ids": ["file", "generic"]}],
        modules={"file": module(lid=.005), "generic": module("hjt")},
        inverter_name="INV-01", mppt_name="1",
    )["module_mismatch_fraction"] == .005


def test_missing_settings_view_and_unrelated_edit_preserve_v1(tmp_path):
    p = Project(tmp_path, count=18, weather=False)
    bundle = p.bundle()
    bundle.pop("loss_settings")
    p.service.save_bundle(bundle)
    view = p.service.project_view(p.pid)
    assert view["resolved_loss_settings"]["defaults_id"] == "recommended_defaults.v1"
    assert view["resolved_loss_settings"]["values"]["lid_fraction"] == 0.
    edited = p.service.update_losses(p.pid, {"overrides": {"dc_wiring_stc_fraction": .01}})
    assert edited["bundle"]["loss_settings"]["defaults_id"] == "recommended_defaults.v1"
    assert edited["resolved_loss_settings"]["values"]["lid_fraction"] == 0.


def test_detailed_execution_refuses_mixed_lid_before_building_references():
    from engine.simulation.detailed_backend import _loss_circuit_references

    context = {
        "strings": [{"string_id": "S1", "module_instance_ids": ["file", "generic"]}],
        "module_inputs": {"file": {"module": module(lid=.02)}, "generic": {"module": module("hjt")}},
        "mppts": [{"connected_string_ids": ["S1"], "inverter_instance_id": "INV-01", "index": 1}],
    }
    with pytest.raises(ValueError, match="automatic LID fractions differ"):
        _loss_circuit_references(context, {}, settings())
