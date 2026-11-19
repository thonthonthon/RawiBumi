"""Deterministic attribution scheduling and scientific parity regressions."""
from copy import deepcopy
import json

import pandas as pd
import pytest

from engine.simulation import detailed_attribution as attribution
from engine.simulation import detailed_backend as backend
from engine.simulation.artifacts import verify_run_package
from engine.simulation.detailed_dispatch import _resolve, scientific_configuration
from engine.simulation.detailed_inputs import DetailedInputError
from tests.unit.test_phase610_stage3a_interval_contract import dark_canonical_fixture
from tools.benchmark_phase610_fixtures import build_fixture, prepare_physical


@pytest.mark.parametrize("options", [{}, {"attribution_worker_count": 1}, {"attribution_worker_count": 2}])
def test_option_execution_only(options):
    f = dark_canonical_fixture()
    before = scientific_configuration(f["configuration"])
    f["configuration"]["shading_configuration"]["electrical_shading_configuration"]["execution_options"] = options
    assert scientific_configuration(f["configuration"]) == before
    _resolve(f["configuration"], f["store"], f["scene"], f["design"])


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.0, "2", None])
def test_invalid_option(value):
    f = dark_canonical_fixture()
    f["configuration"]["shading_configuration"]["electrical_shading_configuration"]["execution_options"] = {"attribution_worker_count": value}
    with pytest.raises(DetailedInputError, match="attribution_worker_count"):
        _resolve(f["configuration"], f["store"], f["scene"], f["design"])


def test_unknown_option_rejected():
    f = dark_canonical_fixture()
    f["configuration"]["shading_configuration"]["electrical_shading_configuration"]["execution_options"] = {"attribution_worker_count": 2, "unknown": 1}
    with pytest.raises(DetailedInputError):
        _resolve(f["configuration"], f["store"], f["scene"], f["design"])


@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("diagnostics", [False, True])
def test_spawn_exact_parity_and_storage_neutrality(dark, diagnostics):
    f = dark_canonical_fixture() if dark else build_fixture("B2")
    if not dark:
        f["weather"].series = f["weather"].series.iloc[10:13].copy()
        f["weather"].dataset["start_time"] = f["weather"].series.index[0].isoformat()
        f["weather"].dataset["end_time"] = (f["weather"].series.index[-1] + pd.Timedelta(hours=1)).isoformat()
    args = prepare_physical(f)
    results, physicals = [], []
    try:
        for size in (2, 10):
            physical = backend.execute_detailed_mppt_backend(f["weather"], **args,
                scientific_input_sha256="a" * 64, electrical_chunk_size=size)
            physicals.append(physical)
            results.append(attribution.execute_detailed_dc_attribution(physical,
                module_inputs=args["module_inputs"], module_configs=args["module_configs"],
                electrical_design=args["electrical_design"], retain_diagnostics=diagnostics))
            collector = attribution.DetailedAttributionChunkCollector(chunk_size=size,
                module_inputs=args["module_inputs"], module_configs=args["module_configs"],
                electrical_design=args["electrical_design"], retain_diagnostics=diagnostics)
            results.append(attribution.execute_detailed_attribution_pass(physical,
                collector=collector, attribution_worker_count=2))
        for result in results[1:]:
            assert result.record() == results[0].record()
            assert result.diagnostic_payload == results[0].diagnostic_payload
        rows = results[0].replay()["intervals"]
        assert len(rows) == 3
        assert [r["interval_start"] for r in rows] == sorted(r["interval_start"] for r in rows)
        if dark:
            assert all(r["ledger"]["telescope"]["status"] == "not_applicable" for r in rows)
            assert all(attribution.DARK_REASON in r["ledger"]["telescope"]["reason_codes"] for r in rows)
    finally:
        for result in results + physicals:
            result.close()


def test_bounded_order_and_failure_cancellation(monkeypatch):
    submitted, emitted, cancelled = [], [], []
    class Future:
        def __init__(self, value):
            self.value = value
            self.done = False
        def result(self):
            assert self.done
            if self.value == 5:
                raise ValueError("worker failed")
            emitted.append(self.value)
            return self.value
        def cancel(self):
            cancelled.append(self.value)
    class Executor:
        def __init__(self, **kwargs):
            assert kwargs["mp_context"].get_start_method() == "spawn"
        def submit(self, fn, value):
            assert len(submitted) - len(emitted) < 4
            future = Future(value)
            submitted.append(future)
            if len(submitted) == 4:
                for item in reversed(submitted):
                    item.done = True
            elif len(submitted) > 4:
                future.done = True
            return future
        def shutdown(self, **kwargs):
            assert kwargs == {"wait": True, "cancel_futures": True}
    monkeypatch.setattr(attribution, "ProcessPoolExecutor", Executor)
    with pytest.raises(ValueError, match="worker failed"):
        list(attribution._ordered_attribution_results({}, range(12), 2))
    assert emitted == list(range(5))
    assert cancelled == [6, 7, 8]


def test_real_spawn_failure():
    # Invalid physical module diagnostics raise in the child, without monkeypatching it.
    context = {"module_inputs": {}, "region_solvers": {}, "strings": {},
        "sample_count": 10, "retain_diagnostics": False}
    with pytest.raises(KeyError, match="missing"):
        list(attribution._ordered_attribution_results(context, [{"modules": {"missing": {}}}] * 6, 2))


@pytest.mark.parametrize("workers", [1, 2])
def test_canonical_pool_lifecycle_and_package(tmp_path, monkeypatch, workers):
    from engine.simulation.canonical import run_canonical_simulation
    active, pools = [], []
    def instrument(real, name):
        def create(**kwargs):
            assert not active, "physical and attribution pools overlap"
            active.append(name)
            pools.append(name)
            executor = real(**kwargs)
            shutdown = executor.shutdown
            def close(**options):
                try:
                    return shutdown(**options)
                finally:
                    active.remove(name)
            executor.shutdown = close
            return executor
        return create
    if workers == 1:
        def forbidden(**kwargs):
            raise AssertionError("serial path constructed a pool")
        monkeypatch.setattr(backend, "ProcessPoolExecutor", forbidden)
        monkeypatch.setattr(attribution, "ProcessPoolExecutor", forbidden)
    else:
        monkeypatch.setattr(backend, "ProcessPoolExecutor", instrument(backend.ProcessPoolExecutor, "physical"))
        monkeypatch.setattr(attribution, "ProcessPoolExecutor", instrument(attribution.ProcessPoolExecutor, "attribution"))
    f = dark_canonical_fixture()
    results = []
    try:
        for count in (1, workers):
            config = deepcopy(f["configuration"])
            options = config["shading_configuration"]["electrical_shading_configuration"]["execution_options"]
            options.update(electrical_worker_count=count, attribution_worker_count=count)
            result = run_canonical_simulation(f["project"], config, revision_store=f["store"],
                output_directory=tmp_path / str(len(results)), engine_version="stage3d-a2-test",
                simulation_run_id="attribution-parity", executed_at="2026-10-04T00:00:00Z")
            results.append(result)
            assert result.summary_result is not None, result.simulation_run
            verify_run_package(result.artifact_directory)
            manifest = json.loads((result.artifact_directory / "reproducibility-manifest.json").read_text())
            assert manifest["shading_configuration"]["electrical_shading_configuration"]["execution_options"]["attribution_worker_count"] == count
        assert results[0].detailed_backend_result.record() == results[1].detailed_backend_result.record()
        assert results[0].detailed_attribution_result.record() == results[1].detailed_attribution_result.record()
        assert results[0].simulation_run["detailed_execution_identity"] == results[1].simulation_run["detailed_execution_identity"]
        assert results[0].summary_result == results[1].summary_result
        assert not active
        assert pools == ([] if workers == 1 else ["physical", "attribution"])
    finally:
        for result in results:
            if result.detailed_backend_result is not None:
                result.detailed_backend_result.close()
            if result.detailed_attribution_result is not None:
                result.detailed_attribution_result.close()


def test_pass_failure_closes_parent_stores(monkeypatch):
    f = dark_canonical_fixture()
    args = prepare_physical(f)
    physical = backend.execute_detailed_mppt_backend(f["weather"], **args, scientific_input_sha256="a" * 64)
    collector = attribution.DetailedAttributionChunkCollector(chunk_size=2,
        module_inputs=args["module_inputs"], module_configs=args["module_configs"],
        electrical_design=args["electrical_design"], retain_diagnostics=True)
    def failed(*args, **kwargs):
        raise ValueError("attribution failure")
        yield
    monkeypatch.setattr(attribution, "_ordered_attribution_results", failed)
    try:
        with pytest.raises(ValueError, match="attribution failure"):
            attribution.execute_detailed_attribution_pass(physical, collector=collector, attribution_worker_count=2)
        assert collector.intervals.closed
        assert collector.diagnostics.closed
    finally:
        physical.close()


def test_dispatch_failure_cannot_produce_success(tmp_path, monkeypatch):
    from engine.simulation.canonical import run_canonical_simulation
    f = dark_canonical_fixture()
    f["configuration"]["shading_configuration"]["electrical_shading_configuration"]["execution_options"]["attribution_worker_count"] = 2
    physicals, collectors = [], []
    real_backend = backend.execute_detailed_mppt_backend
    def capture(*args, **kwargs):
        result = real_backend(*args, **kwargs)
        physicals.append(result)
        return result
    def failed(numerical, *, collector, **kwargs):
        collectors.append(collector)
        raise ValueError("deterministic attribution failure")
    monkeypatch.setattr(backend, "execute_detailed_mppt_backend", capture)
    monkeypatch.setattr(attribution, "execute_detailed_attribution_pass", failed)
    result = run_canonical_simulation(f["project"], f["configuration"], revision_store=f["store"],
        output_directory=tmp_path, engine_version="stage3d-a2-test",
        simulation_run_id="attribution-failure", executed_at="2026-10-04T00:00:00Z")
    assert result.summary_result is None
    assert result.detailed_backend_result is None
    assert result.detailed_attribution_result is None
    assert result.simulation_run["detailed_execution_identity"]["runtime_support_result"] == "numerical_failed"
    assert physicals[0].interval_store.closed
    assert collectors[0].intervals.closed
