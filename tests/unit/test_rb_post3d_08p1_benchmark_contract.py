"""Harness contracts; never run the numerical benchmark in this test file."""
import ast
from pathlib import Path
import subprocess

import pytest

from scripts.benchmarks import rb_post3d_08p1 as bench


def test_workload_and_resource_contract():
    assert bench.SIZES == (1, 10, 50)
    assert bench.WALL_CAP_SECONDS == 600
    assert bench.MEMORY_MIB == 4096
    with pytest.raises(ValueError, match='only 1, 10 and 50'):
        bench.build_fixture(190)


@pytest.mark.parametrize('size', bench.SIZES)
def test_fixture_membership_and_validated_freeze(size):
    from engine.simulation.detailed_inputs import freeze_detailed_selection
    _, config, store, scene, design, bundle = bench.build_fixture(size)
    modules = scene['module_instances']
    ids = [m['module_instance_id'] for m in modules]
    assert len(ids) == len(set(ids)) == size
    revision = next(iter(bundle['electrical_shading_selections']))
    assert {m['module_definition_revision_id'] for m in modules} == {revision}
    assert scene['pv_fields'][0]['generated_module_instance_ids'] == ids
    assert len({m['transform']['position_x_m'] for m in modules}) == size
    assert [mid for string in design['strings'] for mid in string['module_instance_ids']] == ids
    assert all(1 <= len(string['module_instance_ids']) <= 10 for string in design['strings'])
    assert design['mppt_instances'][0]['connected_string_ids'] == [s['string_id'] for s in design['strings']]
    assert store.detailed_electrical_inputs == freeze_detailed_selection(bundle)
    options = config['shading_configuration']['electrical_shading_configuration']
    assert options['scientific_options']['allow_synthetic_regions'] is True
    assert options['execution_options']['electrical_worker_count'] == 1
    assert options['execution_options']['attribution_worker_count'] == 1


def test_fixture_requires_production_opt_in():
    from engine.simulation.detailed_inputs import authorize_selected_assumptions
    from shading.electrical.contract import NumericalAssumptionInputError
    _, config, store, _, _, _ = bench.build_fixture(1)
    config['shading_configuration']['electrical_shading_configuration']['scientific_options'].pop('allow_synthetic_regions')
    with pytest.raises(NumericalAssumptionInputError, match='requires scientific opt-in'):
        authorize_selected_assumptions(config, store.detailed_electrical_inputs)


@pytest.mark.parametrize('previous_size,next_size', [(1, 10), (10, 50)])
def test_staging_relies_on_safe_completion_and_hard_caps(previous_size, next_size):
    # Fixed startup time/RSS must not be multiplied to prevent the next attempt.
    previous = dict(status='completed', size=previous_size, elapsed_seconds=599,
                    passes=[{'peak_process_mib': 4000}])
    assert bench.practical_next(previous, next_size)
    for status in ('timeout', 'terminated', 'invalid_child_output', 'skipped'):
        assert not bench.practical_next(dict(previous, status=status), next_size)


def test_incremental_memory_is_measured_difference():
    def completed(size, peak):
        run = dict(execution_wall_seconds=10., counts={}, inclusive_call_seconds={})
        return dict(status='completed', size=size, passes=[
            dict(peak_process_mib=peak, runs=[run]), dict(runs=[run])])
    baseline = completed(1, 200.)
    metrics = bench.scaling(completed(10, 218.), baseline)
    assert metrics['incremental_peak_mib_per_added_module'] == 2.
    assert 'solver_seconds_per_module' not in metrics
    assert bench.scaling(baseline)['incremental_peak_mib_per_added_module'] is None


def test_wrappers_forward_identity_arguments_and_exceptions():
    counts, seconds, calls = {}, {}, []
    result = object()
    def original(*args, **kwargs):
        calls.append((args, kwargs))
        return result
    wrapper = bench.forwarding_wrapper(original, 'b2_requests', counts, seconds)
    argument = object()
    assert wrapper(argument, use_cache=False) is result
    assert calls == [((argument,), {'use_cache': False})]
    assert counts == {'fresh_b2_requests': 1}
    assert seconds['fresh_b2_requests'] >= 0
    error = ValueError('denied')
    def deny(*args, **kwargs):
        raise error
    with pytest.raises(ValueError) as rejected:
        bench.forwarding_wrapper(deny, 'witness', counts, seconds)(argument)
    assert rejected.value is error
    assert counts['witness'] == 1


def test_only_forwarding_patches_and_no_permission_bypass():
    tree = ast.parse(Path(bench.__file__).read_text())
    patch_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                   and node.func.value.id == 'patch']
    assert len(patch_calls) == 1
    assert patch_calls[0].func.attr == 'object'
    assert isinstance(patch_calls[0].args[2], ast.Call)
    assert patch_calls[0].args[2].func.id == 'forwarding_wrapper'
    forward = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'forward')
    returns = [node for node in ast.walk(forward) if isinstance(node, ast.Return)]
    assert len(returns) == 1
    assert isinstance(returns[0].value, ast.Call)
    assert returns[0].value.func.id == 'original'
    assert not any(isinstance(node, ast.Name) and node.id == '_raw_frozen' for node in ast.walk(tree))
    # Fixture construction uses validated freeze; no replacement acceptance or authority.
    source = Path(bench.__file__).read_text()
    assert 'freeze_detailed_selection(bundle)' in source
    assert 'allow_synthetic_regions' not in source  # explicit opt-in comes only from accepted fixture


class FakeProcess:
    pid = 12345
    returncode = -9
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        kwargs['stdout'].write('resource failure')
    def wait(self, timeout=None):
        if timeout is not None and self.timeout:
            raise subprocess.TimeoutExpired('benchmark', timeout)
        return self.returncode
    timeout = False


def test_termination_is_not_completed_measurement(monkeypatch):
    monkeypatch.setattr(bench.subprocess, 'Popen', FakeProcess)
    result = bench.run_case(1)
    assert result['status'] == 'terminated'
    assert result['exit_code'] == -9
    assert result['passes'] == []
    assert bench.scaling(result) is None


def test_timeout_kills_process_group(monkeypatch):
    class TimeoutProcess(FakeProcess):
        timeout = True
    killed = []
    monkeypatch.setattr(bench.subprocess, 'Popen', TimeoutProcess)
    monkeypatch.setattr(bench.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    result = bench.run_case(1)
    assert result['status'] == 'timeout'
    assert killed == [(12345, bench.signal.SIGKILL)]
    assert result['passes'] == []
    assert bench.scaling(result) is None
