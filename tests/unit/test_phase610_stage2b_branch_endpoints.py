"""Exact, model-local endpoint reuse contracts; no new scientific fixtures."""
from dataclasses import asdict, replace
import json
import math

import pytest

from shading.electrical import substring_reference as ref
from shading.electrical.parameterization import build_pvsyst_region_electrical_states
from tests.unit.test_phase65_substring_bypass_reference import _topology, _states
from tests.unit import test_phase66_nonuniform_module_iv as phase66


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


def invert(branch, states, voltage, holder=None):
    return ref._branch_current_at_voltage(
        branch, states, voltage_v=voltage, voltage_tolerance_v=1e-10,
        current_tolerance_a=1e-10, max_iterations=200, _reuse=holder)


def outcome(call):
    try:
        return ("value", encoded(call()))
    except ValueError as exc:
        return (type(exc), str(exc))


@pytest.mark.parametrize("regions", [["r0"], ["r0", "r1"]])
@pytest.mark.parametrize("dark", [False, True])
def test_exact_inversion_and_endpoints(regions, dark):
    topology = _topology([regions])
    states = _states(topology, {r: 0.0 if dark else 1000.0 / (i + 1)
                               for i, r in enumerate(regions)})
    branch = topology["electrical_substrings"][0]["parallel_branches"][0]
    holder = ref._BranchEndpointHolder([branch], states)
    slot = holder.bind(branch, states)
    ceiling = ref._branch_current_ceiling(branch, states)
    v0 = ref.evaluate_series_branch_voltage(branch, states, current_a=0.0)
    vend = ref.evaluate_series_branch_voltage(branch, states, current_a=ceiling)
    for voltage in [v0, vend, 0.0, -0.5, (v0 + vend) / 2,
                    v0 - 1e-10, math.nextafter(v0 - 1e-10, -math.inf),
                    vend - 1e-10, math.nextafter(vend - 1e-10, -math.inf)]:
        assert outcome(lambda: invert(branch, states, voltage, holder)) == outcome(
            lambda: invert(branch, states, voltage))
    assert encoded(slot.values.ceiling) == encoded(ceiling)
    assert encoded(slot.values.open_voltage) == encoded(v0)
    assert encoded(slot.values.end_voltage) == encoded(vend)


def test_real_pvsyst_exact_values_and_state_rebinding():
    topology = phase66._topology()
    parameterization = phase66._parameterization(topology)
    region_map, local = phase66._handoff(topology)
    states = build_pvsyst_region_electrical_states(
        topology, region_map, local, parameterization, phase66._evidence(parameterization))
    branches = [b for s in topology["electrical_substrings"] for b in s["parallel_branches"]]
    holder = ref._BranchEndpointHolder(branches, states)
    branch = branches[0]
    ceiling = ref._branch_current_ceiling(branch, states)
    for voltage in [0.0, -0.5, ref.evaluate_series_branch_voltage(branch, states, current_a=ceiling),
                    ref.evaluate_series_branch_voltage(branch, states, current_a=0.0)]:
        assert outcome(lambda: invert(branch, states, voltage, holder)) == outcome(
            lambda: invert(branch, states, voltage))
    region = branch["series_region_ids"][0]
    original = states[region]
    for replacement in [replace(original, effective_irradiance_w_m2=500.0),
                        replace(original, cell_temperature_c=40.0),
                        replace(original, solver="newton")]:
        states[region] = replacement
        assert holder.bind(branch, states) is None
        assert outcome(lambda: invert(branch, states, 0.0, holder)) == outcome(
            lambda: invert(branch, states, 0.0))


def test_independent_lazy_components_and_no_requested_result_cache(monkeypatch):
    topology = _topology([["r0"], ["r1"]])
    states = _states(topology, {"r0": 1000.0, "r1": 500.0})
    branches = topology["electrical_substrings"][0]["parallel_branches"]
    events = []
    original_ceiling = ref._branch_current_ceiling
    original_voltage = ref.evaluate_series_branch_voltage
    def ceiling(*args):
        events.append("ceiling")
        return original_ceiling(*args)
    def voltage(*args, current_a):
        events.append(current_a)
        return original_voltage(*args, current_a=current_a)
    monkeypatch.setattr(ref, "_branch_current_ceiling", ceiling)
    monkeypatch.setattr(ref, "evaluate_series_branch_voltage", voltage)
    holder = ref._BranchEndpointHolder(branches, states)
    assert events == []
    slot = holder.bind(branches[0], states)
    assert asdict(slot.values) == dict(ceiling=None, open_voltage=None, end_voltage=None)
    ref._branch_open_with_reuse(branches[0], states, slot)
    assert events == [0.0]
    assert slot.values.ceiling is None and slot.values.end_voltage is None
    c = ref._branch_ceiling_with_reuse(branches[0], states, slot)
    assert events == [0.0, "ceiling"] and slot.values.end_voltage is None
    ref._branch_end_with_reuse(branches[0], states, c, slot)
    assert events == [0.0, "ceiling", c]
    for _ in range(2):
        ref._branch_open_with_reuse(branches[0], states, slot)
        ref._branch_ceiling_with_reuse(branches[0], states, slot)
        ref._branch_end_with_reuse(branches[0], states, c, slot)
        ref.evaluate_series_branch_voltage(branches[0], states, current_a=1.0)
    assert events == [0.0, "ceiling", c, 1.0, 1.0]
    assert asdict(holder.bind(branches[1], states).values) == dict(
        ceiling=None, open_voltage=None, end_voltage=None)
    other = holder.bind(branches[1], states)
    ref._branch_end_with_reuse(branches[1], states, 10.0, other)
    assert other.values.end_voltage is not None
    assert other.values.ceiling is None and other.values.open_voltage is None


@pytest.mark.parametrize("failed", ["ceiling", "open", "end"])
def test_failed_component_is_retried_in_original_order(monkeypatch, failed):
    topology = _topology([["r0"]])
    states = _states(topology, {"r0": 1000.0})
    branch = topology["electrical_substrings"][0]["parallel_branches"][0]
    holder = ref._BranchEndpointHolder([branch], states)
    original_ceiling, original_voltage = ref._branch_current_ceiling, ref.evaluate_series_branch_voltage
    events = []
    failing = True
    def mark(component):
        events.append(component)
        if failing and component == failed:
            raise ref.SubstringReferenceError("controlled endpoint failure")
    def ceiling(*args):
        mark("ceiling")
        return original_ceiling(*args)
    def voltage(*args, current_a):
        mark("open" if current_a == 0.0 else "end")
        return original_voltage(*args, current_a=current_a)
    monkeypatch.setattr(ref, "_branch_current_ceiling", ceiling)
    monkeypatch.setattr(ref, "evaluate_series_branch_voltage", voltage)
    expected = outcome(lambda: invert(branch, states, 0.0))
    original_order = events[:]
    events.clear()
    assert outcome(lambda: invert(branch, states, 0.0, holder)) == expected
    assert events == original_order
    values = holder.bind(branch, states).values
    assert getattr(values, {"ceiling": "ceiling", "open": "open_voltage", "end": "end_voltage"}[failed]) is None
    events.clear()
    assert outcome(lambda: invert(branch, states, 0.0, holder)) == expected
    assert events[0] == failed
    failing = False
    assert outcome(lambda: invert(branch, states, 0.0, holder)) == outcome(
        lambda: invert(branch, states, 0.0))


def test_invalid_requested_voltage_precedes_endpoint_work():
    branch = {"series_region_ids": []}
    states = {}
    holder = ref._BranchEndpointHolder([branch], states)
    for voltage in [True, float("nan"), "invalid"]:
        assert outcome(lambda: invert(branch, states, voltage, holder)) == outcome(
            lambda: invert(branch, states, voltage))
        assert holder.bind(branch, states).values.ceiling is None


def test_binding_mismatch_is_uncached_and_storage_never_grows():
    topology = _topology([["r0", "r1"]])
    states = _states(topology, {"r0": 1000.0, "r1": 500.0})
    branch = topology["electrical_substrings"][0]["parallel_branches"][0]
    holder = ref._BranchEndpointHolder([branch], states)
    invert(branch, states, 0.0, holder)
    frozen_values = holder.bind(branch, states).values
    for ids in [["r1", "r0"], ["r0"], ["missing"], ["r0", "r1"]]:
        branch["series_region_ids"] = ids
        for mapping in [states, dict(states)]:
            assert outcome(lambda: invert(branch, mapping, 0.0, holder)) == outcome(
                lambda: invert(branch, mapping, 0.0))
    for _ in range(20):
        new_branch = dict(branch)
        assert holder.bind(new_branch, states) is None
        assert outcome(lambda: invert(new_branch, states, 0.0, holder)) == outcome(
            lambda: invert(new_branch, states, 0.0))
    assert len(holder._slots) == 1
    assert holder.bind(branch, states).values is frozen_values
    assert ref._BranchEndpointHolder([branch], states).bind(branch, states).values.ceiling is None


@pytest.mark.parametrize("irradiance", [0.0, 500.0, 1000.0])
def test_protected_bypass_reverse_domain_exact_payload_and_hash(irradiance):
    from engine.simulation.artifacts import canonical_object_sha256
    topology = _topology([["r0"], ["r1"]])
    states = _states(topology, {"r0": irradiance, "r1": 1000.0})
    branches = topology["electrical_substrings"][0]["parallel_branches"]
    holder = ref._BranchEndpointHolder(branches, states)
    before = encoded({r: s.as_dict() for r, s in states.items()})
    for current in [0.0, 2.5, 5.0, 7.5, 10.0, 15.0]:
        def solve(context):
            return ref.evaluate_protected_substring_at_current(
                topology, "s0", states, current_a=current, _reuse=context)
        assert outcome(lambda: solve(holder)) == outcome(lambda: solve(None))
        prepared = solve(holder)
        assert canonical_object_sha256(prepared) == canonical_object_sha256(solve(None))
        assert "BranchEndpoint" not in encoded(prepared)
    assert encoded({r: s.as_dict() for r, s in states.items()}) == before
    assert len(holder._slots) == len(branches)


def test_model_owned_state_is_separate_and_absent_from_scientific_outputs(monkeypatch):
    from dataclasses import fields
    from shading.electrical.module_series_adapter import build_phase66_series_module_operating_model
    from shading.electrical.dc_attribution import build_bypass_off_module_model
    from shading.electrical.string_iv import SeriesModuleOperatingModel
    topology = phase66._topology()
    parameterization = phase66._parameterization(topology)
    evidence = phase66._evidence(parameterization)
    region_map, local = phase66._handoff(topology)
    pinned = dict(topology=topology, parameterization=parameterization, evidence=evidence)
    def protected():
        return build_phase66_series_module_operating_model(
            topology, region_map, local, parameterization, evidence)
    def unprotected():
        return build_bypass_off_module_model(pinned, region_map, local)
    models = [protected(), protected(), unprotected(), unprotected()]
    holders = []
    scientific = []
    for model in models:
        holder = next(cell.cell_contents for cell in model.voltage_at_current.__closure__
                      if isinstance(cell.cell_contents, ref._BranchEndpointHolder))
        holders.append(holder)
        scientific.append([outcome(lambda current=current: model.voltage_at_current(current))
                           for current in [0.0, model.current_domain_ceiling_a / 2, model.current_domain_ceiling_a]])
        assert len(holder._slots) == sum(len(s["parallel_branches"])
                                        for s in topology["electrical_substrings"])
    assert len({id(holder) for holder in holders}) == 4
    assert not any("reuse" in f.name or "endpoint" in f.name for f in fields(SeriesModuleOperatingModel))
    monkeypatch.setattr(ref._BranchEndpointHolder, "bind", lambda *args: None)
    for index, factory in enumerate([protected, protected, unprotected, unprotected]):
        uncached = factory()
        assert uncached.scientific_input_sha256 == models[index].scientific_input_sha256
        assert uncached.current_domain_ceiling_a == models[index].current_domain_ceiling_a
        assert [outcome(lambda current=current: uncached.voltage_at_current(current))
                for current in [0.0, uncached.current_domain_ceiling_a / 2, uncached.current_domain_ceiling_a]] == scientific[index]
