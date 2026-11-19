"""Exact scientific parity across serial and spawned interval orchestration."""
from copy import deepcopy
import json

import pandas as pd
import pytest

from engine.simulation import detailed_backend as backend
from engine.simulation.artifacts import verify_run_package
from engine.simulation.detailed_dispatch import _resolve, scientific_configuration
from engine.simulation.detailed_inputs import DetailedInputError
from tests.unit.test_phase610_stage3a_interval_contract import dark_canonical_fixture
from tools.benchmark_phase610_fixtures import build_fixture, prepare_physical


@pytest.mark.parametrize("options", [{}, {"electrical_worker_count": 1},
    {"electrical_worker_count": 2, "electrical_chunk_size": 2}])
def test_worker_option_accepted_and_execution_only(options):
    f = dark_canonical_fixture()
    before = scientific_configuration(f["configuration"])
    f["configuration"]["shading_configuration"]["electrical_shading_configuration"]["execution_options"] = options
    assert scientific_configuration(f["configuration"]) == before
    _resolve(f["configuration"], f["store"], f["scene"], f["design"])


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "2", None])
def test_invalid_worker_option(value):
    f = dark_canonical_fixture()
    f["configuration"]["shading_configuration"]["electrical_shading_configuration"]["execution_options"] = {"electrical_worker_count": value}
    with pytest.raises(DetailedInputError, match="electrical_worker_count"):
        _resolve(f["configuration"], f["store"], f["scene"], f["design"])


def test_unknown_option_still_rejected():
    f = dark_canonical_fixture()
    f["configuration"]["shading_configuration"]["electrical_shading_configuration"]["execution_options"] = {"electrical_worker_count": 2, "unexpected": 1}
    with pytest.raises(DetailedInputError):
        _resolve(f["configuration"], f["store"], f["scene"], f["design"])


@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("size", [1, 2])
def test_real_spawn_backend_and_chunk_parity(dark, size):
    f = dark_canonical_fixture() if dark else build_fixture("B2")
    if not dark:
        # Retain three daylight intervals from the existing diffuse-day fixture.
        f["weather"].series = f["weather"].series.iloc[10:13].copy()
        f["weather"].dataset["start_time"] = f["weather"].series.index[0].isoformat()
        f["weather"].dataset["end_time"] = (f["weather"].series.index[-1] + pd.Timedelta(hours=1)).isoformat()
    args = prepare_physical(f)
    results, chunks = [], []
    try:
        for workers in (1, 2):
            emitted = []
            results.append(backend.execute_detailed_mppt_backend(f["weather"], **args,
                scientific_input_sha256="a" * 64, electrical_worker_count=workers,
                electrical_chunk_size=size, completed_chunk=lambda result: emitted.append(result.record())))
            chunks.append(emitted)
        assert results[0].record() == results[1].record()
        assert chunks[0] == chunks[1]
        rows = results[1].replay()["intervals"]
        assert [r["interval_start"] for r in rows] == sorted(r["interval_start"] for r in rows)
        assert [len(c["payload"]["intervals"]) for c in chunks[1]] == ([1, 1, 1] if size == 1 else [2, 1])
        if dark:
            assert all(m["availability"] == "inactive_dark" for r in rows for m in r["mppts"])
        else:
            assert all(m["selected_operating_point"] is not None for r in rows for m in r["mppts"])
    finally:
        for result in results:
            result.close()


def test_default_serial_never_creates_pool(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("serial execution constructed a process pool")
    monkeypatch.setattr(backend, "ProcessPoolExecutor", forbidden)
    f = dark_canonical_fixture()
    result = backend.execute_detailed_mppt_backend(f["weather"], **prepare_physical(f), scientific_input_sha256="a" * 64)
    assert len(result.replay()["intervals"]) == 3
    result.close()


def test_real_worker_failure_propagates():
    # Malformed prepared diagnostics fail inside the real spawned helper, before
    # any interval result can be emitted. No child monkeypatch is needed.
    context = {"strings": [], "mppts": [], "policy": {}, "mppt_templates": {}, "module_inputs": {}}
    results = backend._ordered_interval_results(context, [({}, {"missing": {}})] * 5, 2)
    with pytest.raises(KeyError, match="missing"):
        list(results)


def test_bounded_submission_and_order_despite_reverse_completion(monkeypatch):
    submitted, emitted, futures = [], [], []
    class Future:
        def __init__(self, ordinal):
            self.ordinal = ordinal
            self.done = False
        def result(self):
            assert self.done
            emitted.append(self.ordinal)
            return self.ordinal
        def cancel(self):
            pass
    class Executor:
        def __init__(self, **kwargs):
            assert kwargs["mp_context"].get_start_method() == "spawn"
        def submit(self, fn, ordinal, modules):
            submitted.append(ordinal)
            assert len(submitted) - len(emitted) <= 4
            future = Future(ordinal)
            futures.append(future)
            # Complete each batch in reverse order, independently of emission.
            if len(submitted) == 4:
                for item in reversed(futures):
                    item.done = True
            elif len(submitted) > 4:
                future.done = True
            return future
        def shutdown(self, **kwargs):
            assert kwargs["cancel_futures"]
    monkeypatch.setattr(backend, "ProcessPoolExecutor", Executor)
    assert list(backend._ordered_interval_results({}, [(i, {}) for i in range(11)], 2)) == list(range(11))


def test_canonical_scientific_parity_and_independent_package_verification(tmp_path):
    from engine.simulation.canonical import run_canonical_simulation
    f = dark_canonical_fixture()
    results = []
    try:
        for workers in (1, 2):
            configuration = deepcopy(f["configuration"])
            configuration["shading_configuration"]["electrical_shading_configuration"]["execution_options"]["electrical_worker_count"] = workers
            result = run_canonical_simulation(f["project"], configuration, revision_store=f["store"],
                output_directory=tmp_path / str(workers), engine_version="stage3d-test",
                simulation_run_id="worker-parity", executed_at="2026-10-04T00:00:00Z")
            results.append(result)
            verify_run_package(result.artifact_directory)
            provenance = json.loads((result.artifact_directory / "reproducibility-manifest.json").read_text())
            assert provenance["shading_configuration"]["electrical_shading_configuration"]["execution_options"]["electrical_worker_count"] == workers
            assert result.summary_result is not None, result.simulation_run
        serial, parallel = results
        assert serial.detailed_backend_result.record() == parallel.detailed_backend_result.record()
        assert serial.detailed_attribution_result.record() == parallel.detailed_attribution_result.record()
        assert serial.summary_result == parallel.summary_result
        assert serial.simulation_run["detailed_execution_identity"] == parallel.simulation_run["detailed_execution_identity"]
        # Compact selected state includes scientific hashes and source bindings.
        from engine.simulation.detailed_downstream import compact_selected_states
        assert compact_selected_states(serial.detailed_backend_result).record() == compact_selected_states(parallel.detailed_backend_result).record()
        assert serial.standard_timeseries.equals(parallel.standard_timeseries)
        # Provenance and directory-dependent transport metadata may differ;
        # packages are verified separately, never compared as raw bytes.
    finally:
        for result in results:
            if result.detailed_backend_result is not None:
                result.detailed_backend_result.close()
            if result.detailed_attribution_result is not None:
                result.detailed_attribution_result.close()
