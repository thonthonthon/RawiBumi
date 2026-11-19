"""Storage/lifetime boundaries, independent of the electrical numerical kernels."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.simulation.artifacts import (ElectricalIntervalStore, StoredElectricalPayload,
    canonical_json_bytes, canonical_object_sha256, persist_electrical_interval_result,
    load_electrical_interval_result, verify_run_package)
from engine.simulation.detailed_backend import DetailedMPPTBackendResult
from engine.simulation.detailed_attribution import (DetailedAttributionChunkCollector,
    execute_detailed_dc_attribution, DetailedDCAttributionResult)
from engine.simulation.detailed_downstream import compact_selected_states


def dark_payload(count=3):
    intervals = []
    for hour in range(count):
        start = f"2026-03-21T{hour:02d}:00:00+07:00"
        end = f"2026-03-21T{hour + 1:02d}:00:00+07:00"
        intervals.append({"interval_start": start, "interval_end": end,
            "evaluation_time": f"2026-03-21T{hour:02d}:30:00+07:00", "duration_seconds": 3600,
            "modules": {"m": {"region_map": {}, "visibility": {},
                "local_irradiance": {"state_payload_sha256": "b" * 64,
                    "module_temperature_c": 20., "regions": [{"effective_irradiance_w_m2": 0.,
                        "unshaded_poa": {"beam_w_m2": 0., "sky_diffuse_w_m2": 0., "ground_reflected_w_m2": 0.}}]},
                "thermal_incident_poa_w_m2": 0., "thermal_efficiency_effective_irradiance_w_m2": 0.}},
            "strings": {"s": {"curve": None, "state": {"source_module_ids": ["m"]}}},
            "mppts": [{"mppt_instance_id": "mppt", "mppt_index": 1,
                "availability": "inactive_dark", "inactive_reason": "no_photovoltaic_operating_point",
                "power_w": 0., "selected_operating_point": None, "tracker_state": None,
                "combined_curve": None, "tracker_model_id": "rawibumi.mppt.ideal_global_mpp.v0.1",
                "constraint_flags": {"operating_current_limit_known": False, "operating_current_above_limit": None},
                "combined_state": {"source_string_ids": ["s"]}}]})
    return {"schema_name": "DetailedMPPTBackendResult", "schema_version": "0.1",
        "scientific_input_sha256": "a" * 64, "temporal_metadata": {"working_interval_count": count},
        "temperature_metadata": {"m": {}}, "model_resolution_metadata": {}, "weather_qc": {},
        "numerical_policy": {"string_sample_count": 101}, "intervals": intervals,
        "downstream_continuation": "unavailable_phase69a_mppt_boundary"}


def spooled(payload, chunk_size):
    store = ElectricalIntervalStore(chunk_size)
    for interval in payload["intervals"]:
        store.append(deepcopy(interval))
    store.seal()
    return DetailedMPPTBackendResult.freeze({**payload, "intervals": store})


def collector(chunk_size, diagnostics=False):
    pinned = SimpleNamespace(scientific_input_sha256="c" * 64,
        replay=lambda: {"parameterization": {"parameterization_payload_sha256": "d" * 64}})
    return DetailedAttributionChunkCollector(chunk_size=chunk_size,
        module_inputs={"m": pinned}, module_configs={"m": SimpleNamespace(module_solver="lambertw")},
        electrical_design={"strings": [{"string_id": "s", "enabled": True, "module_instance_ids": ["m"]}]},
        retain_diagnostics=diagnostics)


@pytest.mark.parametrize("size", [1, 2, 10])
def test_carrier_reference_replay_hash_and_compact_equivalence(size):
    payload = dark_payload()
    retained = DetailedMPPTBackendResult.freeze(payload)
    bounded = spooled(payload, size)
    assert isinstance(bounded._canonical_payload, StoredElectricalPayload)
    assert isinstance(bounded.interval_store, ElectricalIntervalStore)
    assert bounded == retained
    assert bounded.canonical_payload == retained.canonical_payload
    assert bounded.numerical_result_sha256 == retained.numerical_result_sha256
    assert bounded.replay() == payload
    assert list(bounded.replay_stream()["intervals"]) == payload["intervals"]
    assert compact_selected_states(bounded) == compact_selected_states(retained)
    independent = bounded.replay()
    independent["intervals"][0]["modules"].clear()
    assert bounded.replay() == payload
    assert replace(retained, canonical_payload=retained.canonical_payload).replay() == payload
    with pytest.raises(ValueError, match="hash mismatch"):
        replace(bounded, canonical_payload=b"{}").replay()
    directory = bounded.interval_store.directory
    bounded.close()
    assert not directory.exists()
    with pytest.raises(ValueError, match="closed"):
        bounded.replay_stream()


@pytest.mark.parametrize("size", [1, 2, 10])
@pytest.mark.parametrize("diagnostics", [False, True])
def test_completed_physical_chunk_attribution_and_final_binding(size, diagnostics):
    payload = dark_payload()
    explanation = collector(size, diagnostics)
    for start in range(0, 3, size):
        explanation(DetailedMPPTBackendResult.freeze({**payload, "intervals": payload["intervals"][start:start+size]}))
    numerical = spooled(payload, size)
    result = explanation.finish(numerical)
    retained = execute_detailed_dc_attribution(numerical, **explanation.arguments)
    assert retained == result
    assert DetailedDCAttributionResult.freeze(result.replay()) == replace(result, diagnostic_payload=None)
    source = result.replay()
    assert source["source_numerical_result_sha256"] == numerical.numerical_result_sha256
    assert len(source["intervals"]) == 3
    assert all(i["ledger"]["bases"]["N"]["status"] == "not_applicable" for i in source["intervals"])
    assert (result.diagnostic_payload is not None) is diagnostics
    if diagnostics:
        assert len(result.diagnostic_rows()) == 3
        assert json.loads(result.diagnostic_payload) == list(result.diagnostic_rows())
    result.close()
    numerical.close()


def test_final_source_binding_rejects_missing_physical_interval():
    payload = dark_payload()
    explanation = collector(1)
    explanation(DetailedMPPTBackendResult.freeze({**payload, "intervals": payload["intervals"][:1]}))
    with pytest.raises(ValueError, match="coverage"):
        explanation.finish(spooled(payload, 1))


@pytest.mark.parametrize("kind", ["missing", "duplicate", "reordered", "hash", "source"])
def test_persisted_interval_reference_rejects_corruption(tmp_path, kind):
    result = spooled(dark_payload(), 1)
    persist_electrical_interval_result(tmp_path, result)
    assert load_electrical_interval_result(tmp_path).replay() == result.replay()
    path = tmp_path / "detailed-electrical-interval-index.json"
    index = json.loads(path.read_text())
    directory = tmp_path / "detailed-electrical-intervals"
    if kind == "missing":
        (directory / index["intervals"]["chunks"][0]["path"]).unlink()
    elif kind == "duplicate":
        index["intervals"]["chunks"].append(index["intervals"]["chunks"][0])
    elif kind == "reordered":
        index["intervals"]["chunks"].reverse()
    elif kind == "hash":
        (directory / index["intervals"]["chunks"][0]["path"]).write_text("[]")
    else:
        index["numerical_result_sha256"] = "f" * 64
    body = dict(index)
    body.pop("index_payload_sha256")
    index["index_payload_sha256"] = canonical_object_sha256(body)
    path.write_bytes(canonical_json_bytes(index))
    with pytest.raises(ValueError):
        load_electrical_interval_result(tmp_path)
    with pytest.raises(ValueError, match="incomplete"):
        verify_run_package(tmp_path)


@pytest.mark.parametrize("kind", ["duplicate", "reordered"])
def test_append_rejects_wrong_interval_order(kind):
    rows = dark_payload()["intervals"]
    store = ElectricalIntervalStore(1)
    store.append(rows[1])
    with pytest.raises(ValueError, match="order/coverage"):
        store.append(rows[1] if kind == "duplicate" else rows[0])
    store.close()


def test_incomplete_interrupted_store_cannot_be_sealed(monkeypatch):
    store = ElectricalIntervalStore(2)
    store.append({"x": 1})
    with pytest.raises(ValueError, match="incomplete"):
        list(store)
    original = Path.open
    def interrupt(path, *args, **kwargs):
        if path.parent == store.directory:
            raise OSError("controlled interrupted persistence")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", interrupt)
    with pytest.raises(OSError, match="interrupted"):
        store.seal()
    with pytest.raises(ValueError, match="failed"):
        store.seal()
    store.close()


def test_record_retrieval_is_deterministic_and_isolated():
    store = ElectricalIntervalStore(2)
    for i in range(5):
        store.append({"x": [i]})
    store.seal()
    reference = store.reference()
    reference["chunks"].clear()
    store[0]["x"].clear()
    assert list(store) == [{"x": [i]} for i in range(5)]
    assert store.pending == []
    assert store.peak_buffered_records == 2
    store.close()


def test_indexed_schema_access_reads_only_the_requested_chunk(monkeypatch):
    store = ElectricalIntervalStore(2)
    for i in range(100):
        store.append({"x": i})
    store.seal()
    reads = []
    original = store._read_chunk
    def counted(entry):
        reads.append(entry["ordinal"])
        return original(entry)
    monkeypatch.setattr(store, "_read_chunk", counted)
    assert store[99] == {"x": 99}
    assert reads == [49]
    store.close()


def dark_canonical_fixture():
    import pandas as pd
    from tools.benchmark_phase610_fixtures import build_fixture
    f = build_fixture("B1")
    weather = f["weather"]
    weather.series = pd.concat([weather.series.iloc[:1]] * 3, ignore_index=True)
    weather.series.index = pd.date_range("2026-03-21T10:00:00+07:00", periods=3, freq="h")
    weather.series[["ghi_w_m2", "dni_w_m2", "dhi_w_m2"]] = 0.
    weather.dataset["end_time"] = (weather.series.index[-1] + pd.Timedelta(hours=1)).isoformat()
    f["configuration"]["end_time"] = weather.dataset["end_time"]
    f["store"] = replace(f["store"], weather_revisions={weather.dataset["revision_id"]: weather})
    return f


def test_physical_failure_after_a_completed_chunk_is_not_completed_output(tmp_path, monkeypatch):
    from engine.simulation import detailed_backend as backend
    from engine.simulation.canonical import run_canonical_simulation
    f = dark_canonical_fixture()
    original = backend.build_phase66_series_module_operating_model
    calls = 0
    def physical_failure(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 5:
            raise ValueError("controlled second physical interval failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(backend, "build_phase66_series_module_operating_model", physical_failure)
    result = run_canonical_simulation(f["project"], f["configuration"], revision_store=f["store"],
        output_directory=tmp_path, engine_version="stage3a-test", simulation_run_id="failed-after-chunk")
    assert calls == 5
    assert result.simulation_run["status"] == "failed"
    assert result.summary_result is None and result.detailed_backend_result is None
    assert not (result.artifact_directory / "detailed-electrical-interval-index.json").exists()
    # Existing failed-run evidence packages remain verifiable; they contain no
    # completed numerical output or consumable partial chunk set.
    verify_run_package(result.artifact_directory)


def test_interrupted_package_copy_has_no_completion_manifest(tmp_path, monkeypatch):
    import shutil
    from engine.simulation.canonical import run_canonical_simulation
    f = dark_canonical_fixture()
    def interrupt(*args, **kwargs):
        raise OSError("controlled interrupted package copy")
    monkeypatch.setattr(shutil, "copyfile", interrupt)
    with pytest.raises(OSError, match="interrupted"):
        run_canonical_simulation(f["project"], f["configuration"], revision_store=f["store"],
            output_directory=tmp_path, engine_version="stage3a-test", simulation_run_id="interrupted")
    with pytest.raises(ValueError, match="incomplete"):
        verify_run_package(tmp_path / "interrupted")


def test_disabled_attribution_does_not_change_completed_physical_execution(monkeypatch):
    monkeypatch.setattr("engine.simulation.detailed_attribution.execute_detailed_dc_attribution",
                        lambda *args, **kwargs: None)
    explanation = collector(1, True)
    numerical = spooled(dark_payload(), 1)
    for row in numerical.replay_stream()["intervals"]:
        explanation(DetailedMPPTBackendResult.freeze({**dark_payload(), "intervals": [row]}))
    assert explanation.finish(numerical) is None
    assert explanation.intervals.closed and explanation.diagnostics.closed
    assert numerical.replay() == dark_payload()
    numerical.close()


@pytest.mark.parametrize("field,value", [("ordinal", False), ("first_index", False),
    ("byte_size", True), ("sha256", "not-a-hash")])
def test_malformed_chunk_metadata_rejected(field, value):
    store = ElectricalIntervalStore(1)
    store.append({"x": 1})
    store.seal()
    reference = store.reference()
    reference["chunks"][0][field] = value
    with pytest.raises(ValueError, match="metadata"):
        ElectricalIntervalStore.open(store.directory, reference)
    store.close()


@pytest.mark.parametrize("index_name", ["detailed-electrical-interval-index.json",
    "detailed-attribution-diagnostic-index.json"])
def test_missing_store_index_rejected_with_refreshed_completion_manifest(tmp_path, index_name):
    from engine.simulation.canonical import run_canonical_simulation
    from engine.simulation.artifacts import _build_run_package_manifest, persist_json_artifact
    f = dark_canonical_fixture()
    f["configuration"]["output_configuration"]["detailed_diagnostics"] = True
    result = run_canonical_simulation(f["project"], f["configuration"], revision_store=f["store"],
        output_directory=tmp_path, engine_version="stage3a-test", simulation_run_id="missing-index")
    directory = result.artifact_directory
    verify_run_package(directory)
    (directory / index_name).unlink()
    manifest = _build_run_package_manifest(directory, simulation_run_id="missing-index")
    persist_json_artifact(directory / "run-package-manifest.json", manifest)
    with pytest.raises(ValueError, match="index is missing"):
        verify_run_package(directory)
    result.detailed_backend_result.close()
    result.detailed_attribution_result.close()


@pytest.mark.parametrize("size", [1, 2, 10])
@pytest.mark.parametrize("diagnostics", [False, True])
def test_canonical_chunk_policy_is_supported_and_not_scientific(tmp_path, size, diagnostics):
    from engine.simulation.canonical import run_canonical_simulation
    from engine.simulation.detailed_dispatch import scientific_configuration
    f = dark_canonical_fixture()
    before = scientific_configuration(f["configuration"])
    request = f["configuration"]["shading_configuration"]["electrical_shading_configuration"]
    request["execution_options"]["electrical_chunk_size"] = size
    f["configuration"]["output_configuration"]["detailed_diagnostics"] = diagnostics
    assert scientific_configuration(f["configuration"]) == before
    result = run_canonical_simulation(f["project"], f["configuration"], revision_store=f["store"],
        output_directory=tmp_path, engine_version="stage3a-test", simulation_run_id="chunk-policy")
    assert result.standard_timeseries is not None
    assert result.detailed_backend_result.interval_store.chunk_size == size
    assert len(result.detailed_backend_result.replay_stream()["intervals"]) == 3
    verify_run_package(result.artifact_directory)
    result.detailed_backend_result.close()
    result.detailed_attribution_result.close()


@pytest.mark.parametrize("options", [{"electrical_chunk_size": 0}, {"electrical_chunk_size": True},
    {"electrical_chunk_size": 1.5}, {"electrical_chunk_size": 1, "unexpected_policy": True}])
def test_invalid_or_unknown_chunk_policy_remains_fail_closed(options):
    from engine.simulation.detailed_dispatch import _resolve
    from engine.simulation.detailed_inputs import DetailedInputError
    f = dark_canonical_fixture()
    f["configuration"]["shading_configuration"]["electrical_shading_configuration"]["execution_options"] = options
    scene = next(iter(f["store"].scene_revisions.values()))
    design = next(iter(f["store"].electrical_revisions.values()))
    with pytest.raises(DetailedInputError):
        _resolve(f["configuration"], f["store"], scene, design)
