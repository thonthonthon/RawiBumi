"""Canonical detailed preflight identity and persistence, without new physics."""

from copy import deepcopy
from dataclasses import replace
import json

import pandas as pd
import pytest

from apps.api.electrical_shading_state import (
    import_project_electrical_shading_asset,
    set_project_module_electrical_shading_selection,
)
from engine.simulation import build_design_revision_store, run_canonical_simulation
from engine.simulation.artifacts import verify_run_package
from engine.simulation.detailed_inputs import freeze_detailed_selection, FrozenDetailedSelectionSnapshot
from tests.unit.test_phase69a_detailed_inputs import _inputs, _configuration
from tests.unit.test_phase38e_canonical_simulation_run import (
    _project_revision, _configuration as _legacy_configuration, _scene, _electrical,
    _weather, _inverter_definition, _inputs as _legacy_inputs,
)


def _context(policy="fail_closed"):
    assets = _inputs()
    catalog = {
        "modules": {assets["module"]["revision_id"]: assets["module"]},
        "module_topologies": {assets["topology"]["revision_id"]: assets["topology"]},
        "electrical_parameterization_evidence": {assets["evidence"]["evidence_id"]: assets["evidence"]},
        "sources": assets["sources"],
    }
    bundle = {"pinned_components": {"modules": {}, "inverters": {}}}
    set_project_module_electrical_shading_selection(
        bundle, catalog, module_revision_id=assets["module"]["revision_id"],
        topology_revision_id=assets["topology"]["revision_id"],
        region_parameterization_evidence_id=assets["evidence"]["evidence_id"],
        requested_fidelity="level_2_bypass_substring", fallback_policy=policy,
    )
    import_project_electrical_shading_asset(
        bundle, asset_kind="electrical_parameterization_definition",
        asset=assets["parameterization"], sources=list(assets["sources"].values()),
    )
    frozen = freeze_detailed_selection(bundle)
    inverter = _inverter_definition()
    scene = _scene(assets["module"]["revision_id"])
    electrical = _electrical(inverter["revision_id"])
    store = build_design_revision_store(
        scene, electrical, _weather(),
        {assets["module"]["revision_id"]: assets["module"], inverter["revision_id"]: inverter},
        detailed_electrical_inputs=frozen,
    )
    config = _legacy_configuration()
    config["shading_configuration"] = _configuration()["shading_configuration"]
    config["shading_configuration"]["self_shading_enabled"] = False
    config["shading_configuration"]["sky_dome_resolution"] = {
        "azimuth_sectors": 4, "elevation_bands": 2,
        "horizon_azimuth_sectors": 4, "horizon_elevation_bands": 1,
        "horizon_band_elevation_deg": 10.0,
    }
    config["shading_configuration"]["ground_dome_resolution"] = {
        "azimuth_sectors": 4, "depression_bands": 2,
    }
    config["shading_configuration"]["electrical_shading_configuration"]["fallback_policy"] = policy
    return _project_revision(), config, store, bundle


def _run(tmp_path, project, config, store, name="detail", **kwargs):
    return run_canonical_simulation(
        project, config, revision_store=store, output_directory=tmp_path,
        simulation_run_id=name, engine_version="phase69a-test", **kwargs,
    )


def test_workspace_freezes_into_store_and_detailed_run_identity(tmp_path, monkeypatch):
    project, config, store, bundle = _context()
    original = store.detailed_electrical_inputs.record()
    bundle["electrical_shading_selections"].clear()
    def unexpected(*args, **kwargs):
        raise AssertionError("numerical backend must not execute")
    monkeypatch.setattr("engine.simulation.canonical.run_unshaded_fixed_tilt", unexpected)
    monkeypatch.setattr("engine.simulation.canonical.run_beam_sky_ground_shaded_fixed_tilt", unexpected)
    result = _run(tmp_path, project, config, store)
    identity = result.simulation_run["detailed_execution_identity"]
    assert identity["runtime_support_result"] == "numerical_failed"
    assert identity["resolved_fidelity"] == "level_2_bypass_substring"
    assert result.simulation_run["status"] == "failed"
    assert result.backend_result is None
    persisted = json.loads((result.artifact_directory / "detailed-execution-context.json").read_text())
    assert persisted["selection_snapshot"] == original
    assert persisted["identity"] == identity
    assert "DETAILED_NUMERICAL_EXECUTION_FAILED" in {
        item["rule_id"] for item in result.simulation_run["validation_findings"]}
    verify_run_package(result.artifact_directory)


def test_replay_hashes_exclude_execution_time_paths_and_storage(tmp_path):
    project, config, store, _ = _context()
    first = _run(tmp_path / "a", project, config, store, executed_at="2026-10-03T01:00:00Z")
    config = deepcopy(config)
    config["output_configuration"]["storage_location"] = "/different/storage"
    config["shading_configuration"]["cache_policy"] = {"mode": "none"}
    second = _run(tmp_path / "b", project, config, store, executed_at="2026-10-04T01:00:00Z")
    assert first.simulation_run["detailed_execution_identity"] == second.simulation_run["detailed_execution_identity"]
    assert first.simulation_run["input_hash"] == second.simulation_run["input_hash"]


def test_unordered_dictionary_and_source_registry_order_do_not_change_science():
    _, _, store, bundle = _context()
    reordered = deepcopy(bundle)
    for key, values in reordered["pinned_electrical_shading_assets"].items():
        reordered["pinned_electrical_shading_assets"][key] = dict(reversed(list(values.items())))
    assert freeze_detailed_selection(reordered) == store.detailed_electrical_inputs


def test_unordered_source_id_sets_do_not_change_scientific_hash():
    _, _, _, bundle = _context()
    topology = next(iter(bundle["pinned_electrical_shading_assets"]["module_topologies"].values()))
    topology["source_ids"].append("phase66-synthetic-region-source")
    first = freeze_detailed_selection(bundle)
    topology["source_ids"].reverse()
    second = freeze_detailed_selection(bundle)
    assert first.scientific_input_sha256 == second.scientific_input_sha256
    assert first.payload_sha256 != second.payload_sha256


def test_canonical_component_mutation_fails_closed_without_fallback(tmp_path):
    project, config, store, _ = _context("explicit_lower_fidelity")
    store.component_revisions["mod-rawibumi-uat-550-r1"]["name"] = "changed"
    result = _run(tmp_path, project, config, store)
    identity = result.simulation_run["detailed_execution_identity"]
    assert identity["runtime_support_result"] == "blocked"
    assert identity["fallback_applied"] is False
    assert any("does not match canonical" in reason for reason in identity["failure_reasons"])


def test_snapshot_tamper_fails_closed_even_with_fallback_policy(tmp_path):
    project, config, store, _ = _context("explicit_lower_fidelity")
    snapshot = replace(store.detailed_electrical_inputs, canonical_payload=b"{}")
    store = replace(store, detailed_electrical_inputs=snapshot)
    result = _run(tmp_path, project, config, store)
    assert result.simulation_run["detailed_execution_identity"]["runtime_support_result"] == "blocked"


def test_unsupported_request_fails_closed(tmp_path):
    project, config, store, _ = _context()
    config["numerical_options"]["losses"]["module_mismatch_loss_fraction"] = 0.01
    result = _run(tmp_path, project, config, store)
    identity = result.simulation_run["detailed_execution_identity"]
    assert identity["runtime_support_result"] == "blocked"
    assert identity["resolved_fidelity"] is None
    assert any("residual semantic" in reason for reason in identity["failure_reasons"])


def test_explicit_fallback_executes_legacy_geometry_and_records_reason(tmp_path):
    project, config, store, _ = _context("explicit_lower_fidelity")
    # This canonical fixture has no compiled receiver vertices. Its existing
    # Level-0 path is unshaded; fallback must preserve that requested geometry.
    electrical_request = config["shading_configuration"]["electrical_shading_configuration"]
    config["shading_configuration"] = _legacy_configuration()["shading_configuration"]
    config["shading_configuration"]["electrical_shading_configuration"] = electrical_request
    config["numerical_options"]["losses"]["module_mismatch_loss_fraction"] = 0.01
    result = _run(tmp_path, project, config, store)
    identity = result.simulation_run["detailed_execution_identity"]
    assert identity["runtime_support_result"] == "fallback_to_geometry_only"
    assert identity["resolved_fidelity"] == "level_0_geometric_only"
    assert identity["fallback_applied"] is True
    assert identity["fallback_reason"]
    assert result.backend_result is not None
    assert result.simulation_run["status"] in {"completed", "completed_with_warnings"}
    reproduction = result.simulation_run["reproducibility_manifest"]
    assert reproduction["detailed_execution_identity"] == identity
    assert reproduction["input_hashes"]["combined_input_sha256"] == result.simulation_run["input_hash"]
    verify_run_package(result.artifact_directory)


@pytest.mark.parametrize("artifact", ["detailed-execution-context.json", "simulation-run.json"])
def test_persisted_detailed_input_or_identity_tamper_is_detected(tmp_path, artifact):
    project, config, store, _ = _context()
    result = _run(tmp_path, project, config, store)
    path = result.artifact_directory / artifact
    value = json.loads(path.read_text())
    if artifact == "simulation-run.json":
        value["detailed_execution_identity"]["resolved_fidelity"] = "level_0_geometric_only"
    else:
        value["selection_snapshot"]["payload"]["electrical_shading_selections"].clear()
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        verify_run_package(result.artifact_directory)


def test_legacy_dispatch_ignores_unrequested_detailed_store_inputs(tmp_path):
    project, config, store = _legacy_inputs()
    _, _, detailed_store, _ = _context()
    first = _run(tmp_path, project, config, store, name="legacy-a")
    second = _run(tmp_path, project, config,
                  replace(store, detailed_electrical_inputs=detailed_store.detailed_electrical_inputs), name="legacy-b")
    assert "detailed_execution_identity" not in first.simulation_run
    assert "detailed_execution_identity" not in second.simulation_run
    assert first.simulation_run["input_hash"] == second.simulation_run["input_hash"]
    pd.testing.assert_frame_equal(first.standard_timeseries, second.standard_timeseries)


def test_bodyless_legacy_api_still_executes_existing_phase5(tmp_path):
    from tests.unit.test_phase60d_browser_uat import test_phase60d_fastapi_vertical_slice_uses_pinned_fixture_without_live_network
    test_phase60d_fastapi_vertical_slice_uses_pinned_fixture_without_live_network(tmp_path)


def test_frozen_snapshot_record_roundtrip_and_tamper():
    _, _, store, _ = _context()
    record = store.detailed_electrical_inputs.record()
    assert FrozenDetailedSelectionSnapshot.from_record(record) == store.detailed_electrical_inputs
    record["payload"]["electrical_shading_selections"].clear()
    with pytest.raises(ValueError, match="payload hash mismatch"):
        FrozenDetailedSelectionSnapshot.from_record(record)


@pytest.mark.parametrize("change", ["inputs", "identity"])
def test_detailed_internal_hashes_detect_tamper_even_with_refreshed_package_manifest(tmp_path, change):
    from engine.simulation.artifacts import _build_run_package_manifest
    project, config, store, _ = _context()
    result = _run(tmp_path, project, config, store)
    path = result.artifact_directory / "detailed-execution-context.json"
    context = json.loads(path.read_text())
    if change == "inputs":
        context["inputs"]["engine_version"] = "tampered"
    else:
        context["identity"]["limitations"] = []
    path.write_text(json.dumps(context))
    manifest = _build_run_package_manifest(result.artifact_directory, simulation_run_id="detail")
    (result.artifact_directory / "run-package-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="(scientific input|execution identity) hash mismatch"):
        verify_run_package(result.artifact_directory)


def test_invalid_schema_never_downgrades(tmp_path):
    project, config, store, _ = _context("explicit_lower_fidelity")
    config["shading_configuration"]["electrical_shading_configuration"]["thermal_state_scope"] = "invented"
    result = _run(tmp_path, project, config, store)
    identity = result.simulation_run["detailed_execution_identity"]
    assert identity["runtime_support_result"] == "blocked"
    assert identity["failure_reasons"]
    assert identity["fallback_applied"] is False


def test_shared_canonical_revision_mismatch_gate_is_preserved(tmp_path):
    project, config, store, _ = _context("explicit_lower_fidelity")
    config["project_revision_id"] = "different-project-revision"
    result = _run(tmp_path, project, config, store)
    assert result.simulation_run["detailed_execution_identity"]["runtime_support_result"] == "blocked"
    assert "SIMULATION_PROJECT_REVISION_MISMATCH" in {
        finding["rule_id"] for finding in result.simulation_run["validation_findings"]}


def test_missing_inverter_component_fails_closed(tmp_path):
    project, config, store, _ = _context("explicit_lower_fidelity")
    components = {key: value for key, value in store.component_revisions.items()
                  if value["schema_name"] != "InverterDefinition"}
    result = _run(tmp_path, project, config, replace(store, component_revisions=components))
    identity = result.simulation_run["detailed_execution_identity"]
    assert identity["runtime_support_result"] == "blocked"
    assert identity["fallback_applied"] is False


def test_invalid_legacy_shading_type_still_persists_failed_run(tmp_path):
    project, config, store = _legacy_inputs()
    config["shading_configuration"] = ["invalid"]
    result = _run(tmp_path, project, config, store)
    assert result.simulation_run["status"] == "failed"
    assert "detailed_execution_identity" not in result.simulation_run
    verify_run_package(result.artifact_directory)


def test_increment2_scaffolding_context_remains_verifiable(tmp_path):
    from engine.simulation.detailed_dispatch import verify_detailed_context
    from engine.simulation.artifacts import canonical_object_sha256
    project, config, store, _ = _context()
    result = _run(tmp_path, project, config, store)
    context = json.loads((result.artifact_directory / "detailed-execution-context.json").read_text())
    context["inputs"].pop("detailed_numerical_policy")
    context["input_hashes"].pop("detailed_numerical_policy")
    identity = context["identity"]
    identity.pop("numerical_result_sha256")
    identity["runtime_support_result"] = "backend_not_connected"
    identity["scientific_input_sha256"] = canonical_object_sha256(context["input_hashes"])
    identity.pop("execution_identity_sha256")
    identity["execution_identity_sha256"] = canonical_object_sha256(identity)
    verify_detailed_context(context)
    identity["numerical_result_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="requires pinned numerical policy"):
        verify_detailed_context(context)
