"""Synthetic unit fixtures only; orchestrator executes this suite after review.

Goldens were computed by the read-only planner at predecessor 552292e6b1a27998
c98a410f858b6f1df0186000, with the existing Phase-6.6 synthetic REGION fixture.
V(I) digest: sha256 of canonical JSON of [V(0), V(ceiling/2), V(ceiling)].
No simulation, worker, live clock or process observation is involved.
"""

import ast
from dataclasses import fields
import gc
import hashlib
import inspect
import json
from pathlib import Path
import weakref

import pytest

from shading.electrical import dc_attribution as attribution
from shading.electrical import module_series_adapter as adapter
from shading.electrical import substring_reference as reference
from shading.electrical.branch_memo_lifecycle import (
    BranchMemoLifecycleSink, LifecycleContractError, validate_lifecycle_sink,
)
from shading.electrical.string_iv import SeriesModuleOperatingModel
from tests.unit import test_phase66_nonuniform_module_iv as phase66


GOLDENS = {
    "normal": (
        "260ae0db6e15aaa11ee74df8979ecafc4fe66aeffe8a5b4a74993e7ba817cbbf",
        "9743019ac43278b172591c6e2095ad16f7d37271789ef75c0d650af4889c68ce",
        "rawibumi.phase67.phase66_series_module_adapter.v0.1",
    ),
    "bypass_off": (
        "d63c72bf40e7bbce2c11ed5ff847950bc19e0a4fb4683a15a2b656d66fd7d3d2",
        "1016421cd03c7589dffb5be7d90cd4ba3997dbf0a1d918f6ec135587e211b66c",
        "rawibumi.phase69b.detailed_dc_attribution.v0.1.bypass_off",
    ),
}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fixture(overrides=None):
    topology = phase66._topology()
    parameterization = phase66._parameterization(topology)
    region_map, local = phase66._handoff(topology, irradiance_overrides=overrides)
    return (dict(topology=topology, parameterization=parameterization,
                 evidence=phase66._evidence(parameterization)), region_map, local)


def build(role, data, **kwargs):
    pinned, region_map, local = data
    if role == "normal":
        return adapter.build_phase66_series_module_operating_model(
            pinned["topology"], region_map, local, pinned["parameterization"],
            pinned["evidence"], **kwargs)
    return attribution.build_bypass_off_module_model(pinned, region_map, local, **kwargs)


def module_for(role):
    return adapter if role == "normal" else attribution


def outputs(model):
    ceiling = model.current_domain_ceiling_a
    return [model.voltage_at_current(current) for current in (0., ceiling / 2, ceiling)]


def sink(**kwargs):
    return BranchMemoLifecycleSink(identity_namespace="synthetic", **kwargs)


def unresolved(report):
    assert report["coverage_status"] == "UNRESOLVED"
    assert report["model_owner_provenance"] == "INCOMPLETE"
    assert report["holder_release"] == report["owner_termination"] == "NOT_OBSERVED"
    assert report["production_memory_qualification"] == "INCONCLUSIVE"
    assert report["production_chronological_peak"] == "NOT_OBSERVED"
    assert all(holder["coverage_status"] == "UNRESOLVED" for holder in report["holders"])
    assert all(event["event"] in ("CREATE", "OWNER_RETURN") for event in report["events"])
    assert "HOLDER_RELEASE_OBSERVED" not in encoded(report)
    assert "OWNER_TERMINATION_OBSERVED" not in encoded(report)
    assert "COMPLETE" not in (report["coverage_status"],)
    assert "holder_coverage" not in report


@pytest.mark.parametrize("role", GOLDENS)
def test_disabled_golden_and_enabled_scientific_parity(role):
    data = fixture()
    data_before = encoded(data)
    recorder = sink(identity_metadata={"fake_pid": 19, "fake_start": "declared"})
    models = [build(role, data), build(role, data, lifecycle_sink=None),
              build(role, data, lifecycle_sink=recorder)]
    expected_hash, expected_vi, expected_id = GOLDENS[role]
    for model in models:
        assert model.scientific_input_sha256 == expected_hash
        assert model.current_domain_ceiling_a.hex() == "0x1.8000000000000p+4"
        assert model.module_instance_id == "phase66-module-instance"
        assert model.model_id == expected_id
        assert model.model_version == "0.1"
        assert hashlib.sha256(encoded(outputs(model)).encode()).hexdigest() == expected_vi
    assert outputs(models[0]) == outputs(models[1]) == outputs(models[2])
    if role == "normal":
        assert outputs(models[0])[-1]["terminal_voltage_v"] < 0
    assert encoded(data) == data_before
    assert [field.name for field in fields(SeriesModuleOperatingModel)] == [
        "module_instance_id", "current_domain_ceiling_a", "scientific_input_sha256",
        "model_id", "model_version", "voltage_at_current",
    ]
    assert models[0].voltage_at_current.__code__.co_freevars == models[2].voltage_at_current.__code__.co_freevars
    assert not any("lifecycle" in name for name in models[2].voltage_at_current.__code__.co_freevars)


@pytest.mark.parametrize("role", GOLDENS)
def test_default_path_never_calls_or_imports_hooks(monkeypatch, role):
    import builtins
    import shading.electrical.branch_memo_lifecycle as lifecycle

    def forbidden(*args, **kwargs):
        raise AssertionError("disabled path touched instrumentation")

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if "branch_memo_lifecycle" in name:
            forbidden()
        return original_import(name, *args, **kwargs)

    data = fixture()
    monkeypatch.setattr(lifecycle, "validate_lifecycle_sink", forbidden)
    monkeypatch.setattr(BranchMemoLifecycleSink, "holder_created", forbidden)
    monkeypatch.setattr(BranchMemoLifecycleSink, "owner_returned", forbidden)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert build(role, data).voltage_at_current(0.)["terminal_voltage_v"] > 0
    assert build(role, data, lifecycle_sink=None).scientific_input_sha256 == GOLDENS[role][0]


@pytest.mark.parametrize("function,positional,other", [
    (adapter.build_phase66_series_module_operating_model,
     ["topology_definition", "electrical_region_map", "local_irradiance_state",
      "parameterization_definition", "parameterization_evidence"],
     ["region_solver", "authorization_witness"]),
    (adapter._build_series_model_from_checked_states,
     ["topology", "region_map", "local_state", "parameterization", "evidence", "region_states"],
     ["region_solver"]),
    (attribution.build_bypass_off_module_model, ["pinned", "region_map", "local"],
     ["region_solver", "authorization_witness"]),
])
def test_signatures_preserve_positional_and_existing_keywords(function, positional, other):
    parameters = inspect.signature(function).parameters
    assert list(parameters) == positional + other + ["lifecycle_sink"]
    assert all(parameters[name].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for name in positional)
    assert all(parameters[name].kind is inspect.Parameter.KEYWORD_ONLY for name in other + ["lifecycle_sink"])
    assert parameters["lifecycle_sink"].default is None
    assert parameters["region_solver"].default == "lambertw"
    if "authorization_witness" in parameters:
        assert parameters["authorization_witness"].default is None


def test_legacy_internal_positional_call_and_opt_in_forwarding():
    pinned, region_map, local = fixture()
    args = (pinned["topology"], region_map, local, pinned["parameterization"], pinned["evidence"])
    states = adapter.build_pvsyst_region_electrical_states(*args)
    recorder = sink()
    baseline = adapter._build_series_model_from_checked_states(*args, states)
    enabled = adapter._build_series_model_from_checked_states(*args, states, lifecycle_sink=recorder)
    assert baseline.scientific_input_sha256 == enabled.scientific_input_sha256 == GOLDENS["normal"][0]
    assert outputs(baseline) == outputs(enabled)
    assert [event["event"] for event in recorder.report()["events"]] == ["CREATE", "OWNER_RETURN"]


@pytest.mark.parametrize("role", GOLDENS)
def test_deterministic_events_closure_lifetime_and_no_premature_release(role):
    reports = []
    data = fixture()
    for _ in range(2):
        ticks = iter([11, 17])
        recorder = sink(clock=lambda: next(ticks), clock_id="fake_integer_ticks")
        model = build(role, data, lifecycle_sink=recorder)
        report = recorder.report()
        assert report["events"] == [
            {"sequence": 1, "event": "CREATE", "holder_id": "synthetic:holder:1",
             "owner_id": "synthetic:owner:1", "factory_role": role, "slot_count": 6, "clock_tick": 11},
            {"sequence": 2, "event": "OWNER_RETURN", "holder_id": "synthetic:holder:1",
             "owner_id": "synthetic:owner:1", "factory_role": role, "slot_count": 6, "clock_tick": 17},
        ]
        assert report["clock_id"] == "fake_integer_ticks"
        assert report["clock_provenance"] == "TEST_SUPPLIED_UNAUTHENTICATED"
        assert "declared_identity_metadata" not in report
        assert report["holders"][0]["owner_return_observed"] is True
        unresolved(report)
        assert outputs(model)[0]["terminal_voltage_v"] > 0
        assert recorder.report() == report
        model_ref = weakref.ref(model)
        closure_ref = weakref.ref(model.voltage_at_current)
        del model
        gc.collect()
        assert model_ref() is None and closure_ref() is None
        assert recorder.report() == report
        reports.append(encoded(report))
    assert reports[0] == reports[1]


@pytest.mark.parametrize("role", GOLDENS)
def test_recorder_retains_only_primitives_and_no_observed_objects(role):
    recorder = sink()
    model = build(role, fixture(), lifecycle_sink=recorder)

    def primitive_tree(value):
        if type(value) in (str, int, bool, float) or value is None:
            return
        assert type(value) in (list, dict)
        if type(value) is dict:
            for key in value:
                assert type(key) is str
            value = value.values()
        for child in value:
            primitive_tree(child)

    for name in BranchMemoLifecycleSink.__slots__:
        primitive_tree(getattr(recorder, name))
    assert model.voltage_at_current(0.)["terminal_voltage_v"] > 0
    assert recorder.report()["clock_provenance"] == "NOT_SUPPLIED"
    assert all(event["clock_tick"] is None for event in recorder.report()["events"])


@pytest.mark.parametrize("role", GOLDENS)
def test_constructor_failure_has_no_create_and_consumes_no_identity(monkeypatch, role):
    data, recorder = fixture(), sink()

    class AllocationFailure(Exception):
        pass

    def fail(*args, **kwargs):
        raise AllocationFailure("synthetic")

    with monkeypatch.context() as patch:
        patch.setattr(module_for(role), "_BranchEndpointHolder", fail)
        with pytest.raises(AllocationFailure):
            build(role, data, lifecycle_sink=recorder)
    assert recorder.report()["events"] == recorder.report()["holders"] == []
    build(role, data, lifecycle_sink=recorder)
    assert recorder.report()["events"][0]["holder_id"] == "synthetic:holder:1"


@pytest.mark.parametrize("role", GOLDENS)
def test_post_allocation_model_constructor_failure_stays_unresolved(monkeypatch, role):
    recorder, data = sink(), fixture()

    class ModelFailure(Exception):
        pass

    def fail(*args, **kwargs):
        raise ModelFailure("synthetic")

    monkeypatch.setattr(module_for(role), "SeriesModuleOperatingModel", fail)
    with pytest.raises(ModelFailure):
        build(role, data, lifecycle_sink=recorder)
    report = recorder.report()
    assert [event["event"] for event in report["events"]] == ["CREATE"]
    assert report["holders"][0]["owner_return_observed"] is False
    unresolved(report)


def test_one_dark_substring_bypass_off_no_model_is_not_release():
    recorder = sink()
    with pytest.raises(attribution.BypassOffUnavailable) as failure:
        build("bypass_off", fixture({"s0-r0": 0, "s0-r1": 0}), lifecycle_sink=recorder)
    assert failure.value.reason_code == "bypass_off_positive_power_domain_not_covered"
    report = recorder.report()
    assert [event["event"] for event in report["events"]] == ["CREATE"]
    assert report["holders"][0]["owner_return_observed"] is False
    unresolved(report)


@pytest.mark.parametrize("role", GOLDENS)
def test_dark_factory_still_returns_model(role):
    data = fixture({region["region_id"]: 0 for region in phase66._topology()["physical_regions"]})
    recorder = sink()
    model = build(role, data, lifecycle_sink=recorder)
    assert model.current_domain_ceiling_a == 15.
    assert [event["event"] for event in recorder.report()["events"]] == ["CREATE", "OWNER_RETURN"]
    assert all(event["slot_count"] == 6 for event in recorder.report()["events"])
    unresolved(recorder.report())


@pytest.mark.parametrize("role", GOLDENS)
def test_region_authorization_failure_propagates_without_events(monkeypatch, role):
    from shading.electrical.contract import NumericalAssumptionInputError
    from engine.simulation.detailed_inputs import SnapshotWitnessError

    data = fixture()
    for error_type in (NumericalAssumptionInputError, SnapshotWitnessError):
        recorder = sink()

        def denied(*args, **kwargs):
            raise error_type("synthetic authorization denial")

        monkeypatch.setattr(module_for(role), "build_pvsyst_region_electrical_states", denied)
        with pytest.raises(error_type):
            build(role, data, lifecycle_sink=recorder)
        assert recorder.report()["events"] == []


def test_nonpositive_normal_ceiling_rejected_before_allocation(monkeypatch):
    recorder, data = sink(), fixture()
    monkeypatch.setattr(adapter, "_module_current_ceiling", lambda *args: 0.)
    with pytest.raises(adapter.Phase66SeriesModuleAdapterError, match="must be positive"):
        build("normal", data, lifecycle_sink=recorder)
    assert recorder.report()["events"] == []


@pytest.mark.parametrize("role", GOLDENS)
@pytest.mark.parametrize("phase", ["CREATE", "OWNER_RETURN"])
def test_clock_failure_propagates_as_lifecycle_error_without_success(monkeypatch, role, phase):
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        if calls == (1 if phase == "CREATE" else 2):
            raise ValueError("synthetic clock failure")
        return calls

    recorder = sink(clock=clock, clock_id="fake")
    with pytest.raises(LifecycleContractError, match="injected clock failed"):
        build(role, fixture(), lifecycle_sink=recorder)
    report = recorder.report()
    assert [event["event"] for event in report["events"]] == ([] if phase == "CREATE" else ["CREATE"])
    assert report["instrumentation_status"] == "FAILED"
    unresolved(report)
    with pytest.raises(LifecycleContractError, match="previously failed"):
        validate_lifecycle_sink(recorder)


@pytest.mark.parametrize("role", GOLDENS)
def test_hook_failure_is_not_masked_as_numerical_value_error(monkeypatch, role):
    def failure(*args, **kwargs):
        raise LifecycleContractError("synthetic hook failure")

    monkeypatch.setattr(BranchMemoLifecycleSink, "owner_returned", failure)
    recorder = sink()
    with pytest.raises(LifecycleContractError, match="synthetic hook failure"):
        build(role, fixture(), lifecycle_sink=recorder)
    assert [event["event"] for event in recorder.report()["events"]] == ["CREATE"]
    unresolved(recorder.report())


@pytest.mark.parametrize("role", GOLDENS)
@pytest.mark.parametrize("invalid", [False, {}, object(), "sink", 17])
def test_invalid_sink_rejected_before_scientific_work(monkeypatch, role, invalid):
    def forbidden(*args, **kwargs):
        raise AssertionError("scientific work ran with invalid sink")

    data = fixture()
    monkeypatch.setattr(module_for(role), "build_pvsyst_region_electrical_states", forbidden)
    with pytest.raises(LifecycleContractError, match="exact BranchMemoLifecycleSink"):
        build(role, data, lifecycle_sink=invalid)


def test_subclass_duck_typed_and_internal_invalid_sinks_fail_closed(monkeypatch):
    class Subclass(BranchMemoLifecycleSink):
        pass

    class Duck:
        def holder_created(self, **kwargs):
            raise AssertionError("duck accepted")

    for invalid in (Subclass(identity_namespace="fake"), Duck()):
        with pytest.raises(LifecycleContractError):
            validate_lifecycle_sink(invalid)
        with pytest.raises(LifecycleContractError):
            adapter._build_series_model_from_checked_states(None, None, None, None, None, None,
                                                           lifecycle_sink=invalid)


@pytest.mark.parametrize("kwargs", [
    {"identity_namespace": None}, {"identity_namespace": ""}, {"identity_namespace": " "},
    {"identity_namespace": "\ud800"}, {"identity_namespace": "x" * 65},
    {"max_events": 0}, {"max_events": -1}, {"max_events": True}, {"max_events": 4097},
    {"max_events": 2.0}, {"clock": object(), "clock_id": "fake"},
    {"clock": lambda: 0}, {"clock_id": "fake"},
    {"clock": lambda: 0, "clock_id": ""}, {"clock": lambda: 0, "clock_id": 5},
    {"identity_metadata": []}, {"identity_metadata": {"value": object()}},
    {"identity_metadata": {"value": float("nan")}},
    {"identity_metadata": {"value": float("inf")}},
    {"identity_metadata": {"value": "\ud800"}}, {"identity_metadata": {1: "value"}},
    {"identity_metadata": {"value": "x" * 4097}},
    {"identity_metadata": {"value": 1 << 65}},
    {"identity_metadata": {"values": list(range(257))}},
])
def test_invalid_configuration_is_rejected(kwargs):
    config = {"identity_namespace": "fake"}
    config.update(kwargs)
    with pytest.raises(LifecycleContractError):
        BranchMemoLifecycleSink(**config)


def test_cyclic_deep_and_aggregate_oversized_metadata_rejected():
    cyclic = {}
    cyclic["self"] = cyclic
    nested = {}
    for _ in range(10):
        nested = {"child": nested}
    for metadata in (cyclic, nested, {"a": "x" * 2500, "b": "y" * 2500}):
        with pytest.raises(LifecycleContractError):
            sink(identity_metadata=metadata)


@pytest.mark.parametrize("tick", [None, True, -1, 0.0, "1", 1 << 65])
def test_invalid_clock_tick_fails_without_recording(tick):
    recorder = sink(clock=lambda: tick, clock_id="fake")
    with pytest.raises(LifecycleContractError):
        recorder.holder_created(factory_role="normal", slot_count=0)
    assert recorder.report()["events"] == []
    assert recorder.report()["instrumentation_status"] == "FAILED"


def test_decreasing_clock_does_not_record_owner_return():
    ticks = iter([9, 8])
    recorder = sink(clock=lambda: next(ticks), clock_id="fake")
    token = recorder.holder_created(factory_role="normal", slot_count=0)
    with pytest.raises(LifecycleContractError, match="decreased"):
        recorder.owner_returned(*token)
    assert [event["event"] for event in recorder.report()["events"]] == ["CREATE"]
    unresolved(recorder.report())


def test_equal_ticks_and_multiple_identities_are_ordered_by_sequence():
    recorder = sink(clock=lambda: 0, clock_id="fake")
    first = recorder.holder_created(factory_role="normal", slot_count=0)
    second = recorder.holder_created(factory_role="bypass_off", slot_count=6)
    recorder.owner_returned(*second)
    recorder.owner_returned(*first)
    assert first == ("synthetic:holder:1", "synthetic:owner:1")
    assert second == ("synthetic:holder:2", "synthetic:owner:2")
    assert [event["sequence"] for event in recorder.report()["events"]] == [1, 2, 3, 4]
    assert [event["holder_id"] for event in recorder.report()["events"]] == [first[0], second[0], second[0], first[0]]
    unresolved(recorder.report())


@pytest.mark.parametrize("changes", [
    {"slot_count": -1}, {"slot_count": True}, {"slot_count": 1.0}, {"slot_count": 1 << 65},
    {"factory_role": "producer"}, {"factory_role": object()},
    {"holder_id": "holder"}, {"holder_id": "same", "owner_id": "same"},
    {"holder_id": "", "owner_id": "owner"}, {"holder_id": 1, "owner_id": "owner"},
    {"holder_id": "holder", "owner_id": False},
    {"holder_id": "holder", "owner_id": "\ud800"},
    {"holder_id": "h" * 129, "owner_id": "owner"},
])
def test_invalid_event_contract_is_rejected_and_latched(changes):
    recorder = sink()
    args = {"factory_role": "normal", "slot_count": 0}
    args.update(changes)
    with pytest.raises(LifecycleContractError):
        recorder.holder_created(**args)
    assert recorder.report()["events"] == []
    with pytest.raises(LifecycleContractError, match="previously failed"):
        recorder.holder_created(factory_role="normal", slot_count=0)


@pytest.mark.parametrize("holder,owner", [
    ("holder", "other"), ("other", "owner"), ("owner", "other"), ("other", "holder"),
])
def test_duplicate_or_cross_role_identities_fail_without_overwriting(holder, owner):
    recorder = sink()
    recorder.holder_created(factory_role="normal", slot_count=6, holder_id="holder", owner_id="owner")
    with pytest.raises(LifecycleContractError):
        recorder.holder_created(factory_role="bypass_off", slot_count=0, holder_id=holder, owner_id=owner)
    report = recorder.report()
    assert len(report["events"]) == len(report["holders"]) == 1
    assert report["holders"][0]["slot_count"] == 6


@pytest.mark.parametrize("holder,owner", [("missing", "owner"), ("holder", "other"), (None, "owner"), ("holder", [])])
def test_unknown_mismatched_or_invalid_owner_return_fails(holder, owner):
    recorder = sink()
    recorder.holder_created(factory_role="normal", slot_count=0, holder_id="holder", owner_id="owner")
    with pytest.raises(LifecycleContractError):
        recorder.owner_returned(holder, owner)
    assert [event["event"] for event in recorder.report()["events"]] == ["CREATE"]


def test_duplicate_owner_return_fails_without_duplicate_event():
    recorder = sink()
    token = recorder.holder_created(factory_role="normal", slot_count=0)
    recorder.owner_returned(*token)
    with pytest.raises(LifecycleContractError, match="duplicate owner return"):
        recorder.owner_returned(*token)
    assert [event["event"] for event in recorder.report()["events"]] == ["CREATE", "OWNER_RETURN"]


@pytest.mark.parametrize("role", GOLDENS)
def test_capacity_exhaustion_leaves_owner_unresolved(role):
    recorder = sink(max_events=1)
    with pytest.raises(LifecycleContractError, match="capacity"):
        build(role, fixture(), lifecycle_sink=recorder)
    report = recorder.report()
    assert [event["event"] for event in report["events"]] == ["CREATE"]
    assert report["holders"][0]["owner_return_observed"] is False
    unresolved(report)


def test_no_silent_trimming_at_create_capacity():
    recorder = sink(max_events=1)
    recorder.holder_created(factory_role="normal", slot_count=0)
    with pytest.raises(LifecycleContractError):
        recorder.holder_created(factory_role="normal", slot_count=0)
    assert len(recorder.report()["events"]) == len(recorder.report()["holders"]) == 1


@pytest.mark.parametrize("method", ["holder_released", "owner_terminated"])
def test_external_disposal_witness_is_rejected(method):
    recorder = sink()
    token = recorder.holder_created(factory_role="normal", slot_count=0)
    recorder.owner_returned(*token)
    before = recorder.report()["events"]
    with pytest.raises(LifecycleContractError, match="protocol is not validated"):
        if method == "holder_released":
            recorder.holder_released(token[0])
        else:
            recorder.owner_terminated(token[1], witness={"declared_termination": True})
    assert recorder.report()["events"] == before
    unresolved(recorder.report())


def test_metadata_and_reports_are_independent_and_unauthenticated():
    metadata = {"fake_pid": 11, "declared_start": ["fake"], "nested": {"identity": "test"}}
    recorder = sink(identity_metadata=metadata)
    token = recorder.holder_created(factory_role="normal", slot_count=6)
    recorder.owner_returned(*token)
    expected = encoded(recorder.report())
    metadata["declared_start"].append("mutated")
    metadata["nested"]["identity"] = "changed"
    report = recorder.report()
    report["events"][0]["holder_id"] = "forged"
    report["holders"][0]["owner_return_observed"] = False
    report["declared_identity_metadata"]["nested"]["identity"] = "forged"
    assert encoded(recorder.report()) == expected
    assert recorder.report()["identity_provenance"] == "TEST_SUPPLIED_UNAUTHENTICATED"


def test_reentrant_clock_cannot_duplicate_or_forge_success_even_if_error_caught():
    recorder = None

    def clock():
        with pytest.raises(LifecycleContractError, match="reentrant"):
            recorder.holder_created(factory_role="normal", slot_count=0)
        return 0

    recorder = sink(clock=clock, clock_id="fake")
    with pytest.raises(LifecycleContractError, match="previously failed"):
        recorder.holder_created(factory_role="normal", slot_count=0)
    assert recorder.report()["events"] == recorder.report()["holders"] == []


def test_import_and_recorder_are_stdlib_only_and_do_no_io(monkeypatch):
    import builtins
    import os
    import subprocess
    import time
    import shading.electrical.branch_memo_lifecycle as lifecycle

    source = Path(lifecycle.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert {node.names[0].name for node in tree.body if isinstance(node, ast.Import)} == {"json", "math"}
    assert not any(isinstance(node, ast.ImportFrom) for node in ast.walk(tree))
    for node in tree.body:
        assert isinstance(node, (ast.Import, ast.ClassDef, ast.FunctionDef, ast.Assign, ast.Expr))
        if isinstance(node, ast.Assign):
            assert isinstance(node.value, ast.Constant)
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    assert not any(isinstance(node, ast.Call) for node in tree.body)

    def forbidden(*args, **kwargs):
        raise AssertionError("instrumentation performed I/O or sampled a real clock/process")

    code = compile(source, "synthetic_lifecycle_import", "exec")
    namespace = {"__name__": "synthetic_lifecycle_import"}
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        for name in ("open", "getpid", "getppid", "stat", "listdir", "scandir"):
            patch.setattr(os, name, forbidden)
        for name in ("time", "time_ns", "monotonic", "monotonic_ns", "perf_counter", "perf_counter_ns", "process_time"):
            patch.setattr(time, name, forbidden)
        for name in ("Popen", "run", "call", "check_call", "check_output"):
            patch.setattr(subprocess, name, forbidden)
        exec(code, namespace)
        recorder = namespace["BranchMemoLifecycleSink"](identity_namespace="fake")
        token = recorder.holder_created(factory_role="normal", slot_count=0)
        recorder.owner_returned(*token)
        report = recorder.report()
    assert [event["event"] for event in report["events"]] == ["CREATE", "OWNER_RETURN"]
    unresolved(report)


def test_holder_and_memo_invariants_unchanged():
    assert reference._BRANCH_CURRENT_MEMO_LIMIT == 256
    assert reference._BranchEndpointHolder.__slots__ == ("_region_states", "_slots")
    assert hashlib.sha256(Path(reference.__file__).read_bytes()).hexdigest() == (
        "45157f6a93c9e066b54ddffe70875cf06bed4a17816ca8a0cd797d4120b1a3ba"
    )
