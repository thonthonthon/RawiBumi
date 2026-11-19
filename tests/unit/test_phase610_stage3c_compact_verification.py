"""Persisted compact verification reuses one fully validated decoded graph."""
from collections import Counter
from dataclasses import replace
import json
import shutil

import pytest

from engine.simulation.artifacts import (
    _build_run_package_manifest, canonical_object_sha256, verify_run_package,
)
from engine.simulation.detailed_downstream import CompactDetailedMPPTResult
from tests.unit.test_phase610_stage3a_interval_contract import dark_canonical_fixture


@pytest.fixture
def package(tmp_path, request):
    from engine.simulation.canonical import run_canonical_simulation
    fixture = dark_canonical_fixture()
    fixture["configuration"]["output_configuration"]["detailed_diagnostics"] = request.param
    result = run_canonical_simulation(fixture["project"], fixture["configuration"],
        revision_store=fixture["store"], output_directory=tmp_path,
        engine_version="stage3c-test", simulation_run_id="compact-verification")
    assert result.standard_timeseries is not None
    if not request.param:
        # Exercise the supported compact-only verification path as well as the
        # package with retained physical evidence; neither requires a replay.
        (result.artifact_directory / "detailed-electrical-interval-index.json").unlink()
        shutil.rmtree(result.artifact_directory / "detailed-electrical-intervals")
        _refresh_manifest(result.artifact_directory)
    yield result.artifact_directory
    result.detailed_backend_result.close()
    result.detailed_attribution_result.close()


def _refresh_manifest(directory):
    manifest = _build_run_package_manifest(directory, simulation_run_id="compact-verification")
    (directory / "run-package-manifest.json").write_text(json.dumps(manifest))


def _bind_compact_hash(directory, digest):
    # Rebind outer identities so a forged compact reaches the source checks.
    path = directory / "detailed-execution-context.json"
    context = json.loads(path.read_text())
    identity = context["identity"]
    identity["compact_result_sha256"] = digest
    del identity["execution_identity_sha256"]
    identity["execution_identity_sha256"] = canonical_object_sha256(identity)
    path.write_text(json.dumps(context))
    path = directory / "simulation-run.json"
    run = json.loads(path.read_text())
    run["detailed_execution_identity"] = identity
    run["input_hash"] = canonical_object_sha256({
        "canonical_input_hash": context["canonical_input_hash"],
        "detailed_scientific_input_sha256": identity["scientific_input_sha256"],
        "detailed_execution_identity_sha256": identity["execution_identity_sha256"],
    })
    path.write_text(json.dumps(run))


@pytest.mark.parametrize("package", [False, True], indirect=True)
def test_one_persisted_decode_and_no_persisted_replay(package, monkeypatch):
    counts = Counter()
    decoded_compact = []
    validated_compact = []
    original_loads = json.loads
    original_validate = CompactDetailedMPPTResult._validate_payload
    original_projection = __import__(
        "engine.simulation.detailed_downstream", fromlist=["compact_selected_states"]
    ).compact_selected_states
    in_projection = False

    def loads(value, *args, **kwargs):
        result = original_loads(value, *args, **kwargs)
        if isinstance(result, dict):
            payload = result.get("payload", result)
            name = payload.get("schema_name") if isinstance(payload, dict) else None
            if name in ("CompactDetailedMPPTResult", "DetailedDCAttributionResult",
                        "DetailedDCAttributionEnergySummary") and not in_projection:
                counts[name] += 1
                if name == "CompactDetailedMPPTResult":
                    decoded_compact.append(payload)
        return result

    def projection(numerical):
        nonlocal in_projection
        in_projection = True
        try:
            return original_projection(numerical)
        finally:
            in_projection = False

    original_replay = CompactDetailedMPPTResult.replay
    def replay(self):
        assert in_projection, "persisted compact must not replay during verification"
        return original_replay(self)

    def validate(self, payload):
        if not in_projection:
            validated_compact.append(payload)
        return original_validate(self, payload)

    monkeypatch.setattr(json, "loads", loads)
    monkeypatch.setattr(CompactDetailedMPPTResult, "replay", replay)
    monkeypatch.setattr(CompactDetailedMPPTResult, "_validate_payload", validate)
    monkeypatch.setattr("engine.simulation.detailed_downstream.compact_selected_states", projection)
    verify_run_package(package)
    assert counts == {"CompactDetailedMPPTResult": 1,
                      "DetailedDCAttributionEnergySummary": 1}
    assert validated_compact
    assert all(payload is decoded_compact[0] for payload in validated_compact)


@pytest.mark.parametrize("package", [False], indirect=True)
@pytest.mark.parametrize("change, error", [
    ("hash", "compact detailed result identity mismatch"),
    ("schema", "unsupported compact detailed result"),
    ("duration", "compact detailed interval duration mismatch"),
    ("scientific", "compact detailed scientific/diagnostic identity mismatch"),
    ("attribution", "attribution selected-MPPT source mismatch"),
    ("missing", "compact detailed result is missing"),
])
def test_compact_corruption_fails_closed(package, change, error):
    path = package / "detailed-selected-mppt.json"
    record = json.loads(path.read_text())
    payload = record["payload"]
    if change == "missing":
        path.unlink()
    else:
        if change == "hash":
            record["compact_result_sha256"] = "0" * 64
        elif change == "schema":
            payload["schema_version"] = "invalid"
        elif change == "duration":
            payload["intervals"][0]["duration_seconds"] += 1
        elif change == "scientific":
            payload["scientific_input_sha256"] = "0" * 64
        else:
            for interval in payload["intervals"]:
                interval["mppts"][0]["mppt_index"] += 100
        if change != "hash":
            record["compact_result_sha256"] = canonical_object_sha256(payload)
            _bind_compact_hash(package, record["compact_result_sha256"])
        path.write_text(json.dumps(record))
    _refresh_manifest(package)
    with pytest.raises(ValueError, match=error):
        verify_run_package(package)


@pytest.mark.parametrize("package", [True], indirect=True)
def test_physical_projection_mismatch_fails_closed(package):
    path = package / "detailed-selected-mppt.json"
    record = json.loads(path.read_text())
    record["payload"]["intervals"][0]["modules"][0]["incident_poa_w_m2"] += 1
    record["compact_result_sha256"] = canonical_object_sha256(record["payload"])
    path.write_text(json.dumps(record))
    _bind_compact_hash(package, record["compact_result_sha256"])
    _refresh_manifest(package)
    with pytest.raises(ValueError, match="does not match diagnostic projection"):
        verify_run_package(package)


@pytest.mark.parametrize("package", [False], indirect=True)
def test_public_replay_is_isolated_and_checks_hash(package):
    record = json.loads((package / "detailed-selected-mppt.json").read_text())
    compact = CompactDetailedMPPTResult.freeze(record["payload"])
    assert compact == CompactDetailedMPPTResult.freeze(record["payload"], _decoded=True)
    replayed = compact.replay()
    replayed["intervals"].clear()
    assert compact.replay() == record["payload"]
    with pytest.raises(ValueError, match="hash mismatch"):
        replace(compact, compact_result_sha256="0" * 64).replay()

