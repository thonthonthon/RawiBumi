"""Exact reuse versus the unchanged real electrical reference algorithm."""
from copy import deepcopy
from math import nextafter

import pytest

from engine.simulation.artifacts import canonical_object_sha256
from shading.electrical import dc_attribution
from shading.electrical import substring_reference as kernel
from shading.electrical.parameterization import (
    PVSystRegionElectricalState, build_pvsyst_region_electrical_states,
)
from tests.unit.test_phase66_nonuniform_module_iv import (
    _topology, _parameterization, _evidence, _handoff,
)
# Collect the established real authorization tests here as well. No PASS mocks.
from tests.unit.test_rb_post3d_08b3d2_activation import (
    candidate, test_strict_opt_in_required, test_unsupported_execution_policy_denies,
)


def fixture(irradiance, temperature):
    topology = _topology()
    definition = _parameterization(topology)
    region_map, local = _handoff(topology, irradiance_overrides=dict(zip(
        [r['region_id'] for r in topology['physical_regions']], irradiance)))
    local['module_temperature_c'] = temperature
    states = build_pvsyst_region_electrical_states(
        topology, region_map, local, definition, _evidence(definition))
    branches = [b for s in topology['electrical_substrings'] for b in s['parallel_branches']]
    return topology, states, branches


@pytest.mark.parametrize('irradiance', [(1000.,)*3, (1000., 200., 600.), (0.,)*3])
@pytest.mark.parametrize('temperature', [15., 45.])
def test_real_protected_states_exact(irradiance, temperature, monkeypatch):
    topology, states, branches = fixture(irradiance, temperature)
    holder = kernel._BranchEndpointHolder(branches, states)
    evaluate = kernel.evaluate_protected_substring_at_current
    requests = []
    for substring in topology['electrical_substrings']:
        sid = substring['substring_id']
        initial = evaluate(topology, sid, states, current_a=0.)
        transition = initial['pv_current_at_bypass_clamp_a']
        currents = [0., 1e-8, 2., 6., 7.9, 8., 10.,
                    nextafter(transition, 0.), transition, nextafter(transition, float('inf'))]
        requests.extend((sid, current) for current in currents)
    optimized = [evaluate(topology, sid, states, current_a=current, _reuse=holder)
                 for sid, current in requests]
    monkeypatch.setattr(kernel, '_branch_current_at_voltage', kernel._branch_current_at_voltage_uncached)
    reference = [evaluate(topology, sid, states, current_a=current)
                 for sid, current in requests]
    assert optimized == reference
    assert canonical_object_sha256(optimized) == canonical_object_sha256(reference)


def test_exact_call_reduction_and_bound(monkeypatch):
    _, states, branches = fixture((1000., 200., 600.), 25.)
    branch = branches[0]
    holder = kernel._BranchEndpointHolder(branches, states)
    original = PVSystRegionElectricalState.current_at_voltage
    calls = []
    def counted(self, voltage):
        calls.append(voltage)
        return original(self, voltage)
    monkeypatch.setattr(PVSystRegionElectricalState, 'current_at_voltage', counted)
    workload = [i / 20 for i in range(1, 120)]
    def sweep(reuse):
        return [kernel.solve_parallel_branches_at_current([branch], states,
                total_current_a=i, _reuse=reuse) for i in workload]
    reference = sweep(None)
    before = len(calls)
    calls.clear()
    assert sweep(holder) == reference
    assert len(calls) < before
    for slot in holder._slots.values():
        assert len(slot.currents) <= kernel._BRANCH_CURRENT_MEMO_LIMIT
    assert len(holder._slots) == len(branches)


@pytest.mark.parametrize('iterations', [1, 200])
def test_iteration_exhaustion_and_settings(iterations):
    _, states, branches = fixture((1000.,)*3, 25.)
    holder = kernel._BranchEndpointHolder(branches, states)
    for tolerance in [1e-10, 1e-9]:
        kwargs = dict(total_current_a=3.14159, max_iterations=iterations,
                      current_tolerance_a=tolerance, voltage_tolerance_v=tolerance)
        assert kernel.solve_parallel_branches_at_current(branches[:1], states, _reuse=holder, **kwargs) == kernel.solve_parallel_branches_at_current(branches[:1], states, **kwargs)


def test_binding_exact_voltage_and_failure_isolation():
    _, states, branches = fixture((1000.,)*3, 25.)
    holder = kernel._BranchEndpointHolder(branches, states)
    branch = branches[0]
    kwargs = dict(voltage_tolerance_v=1e-10, current_tolerance_a=1e-10, max_iterations=200)
    slot = holder.bind(branch, states)
    for voltage in [1., nextafter(1., 2.)]:
        kernel._branch_current_at_voltage(branch, states, voltage_v=voltage, _reuse=holder, **kwargs)
    assert len(slot.currents) == 2
    assert holder.bind(deepcopy(branch), states) is None
    assert holder.bind(branch, dict(states)) is None
    for irradiance, temperature in [((100.,)*3, 25.), ((1000.,)*3, 45.)]:
        _, changed, _ = fixture(irradiance, temperature)
        assert holder.bind(branch, changed) is None
        assert kernel._branch_current_at_voltage(branch, changed, voltage_v=1., _reuse=holder, **kwargs) == kernel._branch_current_at_voltage(branch, changed, voltage_v=1., **kwargs)
    for _ in range(2):
        with pytest.raises(ValueError) as cached:
            kernel._branch_current_at_voltage(branch, states, voltage_v=-100., _reuse=holder, **kwargs)
        with pytest.raises(ValueError) as fresh:
            kernel._branch_current_at_voltage(branch, states, voltage_v=-100., **kwargs)
        assert type(cached.value) is type(fresh.value)
        assert str(cached.value) == str(fresh.value)
    assert len(slot.currents) == 2


def test_real_execution_attribution_and_fingerprint_equivalence(candidate, tmp_path, monkeypatch):
    from tests.unit.test_rb_post3d_08b3d2_activation import _fixture
    from tests.unit.test_phase69a_canonical_dispatch import _run
    from engine.simulation.artifacts import verify_run_package
    project, config, store, _, _, _ = _fixture(candidate)
    # Spawned workers would re-import unpatched bindings. Keep both real runs
    # in-process so the reference covers the actual and bypass-off paths.
    config['shading_configuration']['electrical_shading_configuration']['execution_options'].update(
        electrical_worker_count=1, attribution_worker_count=1)
    optimized = _run(tmp_path / 'optimized', project, config, store, name='hotpath')
    assert optimized.summary_result is not None, optimized.simulation_run
    verify_run_package(optimized.artifact_directory)
    original_kernel = kernel._branch_current_at_voltage
    original_attribution = dc_attribution._branch_current_at_voltage
    with monkeypatch.context() as uncached:
        uncached.setattr(kernel, '_branch_current_at_voltage', kernel._branch_current_at_voltage_uncached)
        uncached.setattr(dc_attribution, '_branch_current_at_voltage', kernel._branch_current_at_voltage_uncached)
        assert kernel._branch_current_at_voltage is kernel._branch_current_at_voltage_uncached
        assert dc_attribution._branch_current_at_voltage is kernel._branch_current_at_voltage_uncached
        # Each execution constructs its own model-owned endpoint holders; the
        # uncached function never reads or writes their branch inversion memo.
        reference = _run(tmp_path / 'reference', project, config, store, name='hotpath')
        assert reference.summary_result is not None, reference.simulation_run
        verify_run_package(reference.artifact_directory)
    assert kernel._branch_current_at_voltage is original_kernel
    assert dc_attribution._branch_current_at_voltage is original_attribution
    # Real actual DC, independent-module bases, losses and source identities.
    actual = optimized.detailed_attribution_result.replay()
    expected = reference.detailed_attribution_result.replay()
    assert actual['intervals'] == expected['intervals']
    assert actual['source_numerical_result_sha256'] == expected['source_numerical_result_sha256']
    assert actual['source_module_input_hashes'] == expected['source_module_input_hashes']
    assert optimized.detailed_backend_result.replay()['intervals'] == reference.detailed_backend_result.replay()['intervals']
