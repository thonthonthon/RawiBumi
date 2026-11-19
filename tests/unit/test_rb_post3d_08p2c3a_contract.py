"""Diagnostic contracts; positive physics uses the existing real Phase-6.6 adapter."""
import copy
import json
import subprocess
import math
import sys

import pytest

from scripts.benchmarks.rb_post3d_08p2c3a_audit import Assembly, Audit, ByteBudget, encoded, parser
from shading.electrical import string_iv
from shading.electrical.module_series_adapter import build_phase66_series_module_operating_model
from tests.unit.test_phase66_nonuniform_module_iv import _topology, _parameterization, _evidence, _handoff
from tests.unit.test_phase67_general_series_string_iv import _string


def real_model(*, shaded=False, temperature=None):
    topology = _topology()
    definition = _parameterization(topology)
    region_map, local = _handoff(topology, irradiance_overrides={'s1-r1': 0.0} if shaded else {})
    if temperature is not None:
        local['module_temperature_c'] = temperature
        local.pop('state_payload_sha256', None)
    return build_phase66_series_module_operating_model(
        topology, region_map, local, definition, _evidence(definition))


def test_exact_current_and_bounded_storage():
    record = Assembly({}, cap=2)
    record.current(1., 'isc_endpoint')
    record.current(1., 'sampling')
    record.current(math.nextafter(1., 2.), 'sampling')
    for index in range(100):
        record.current(2. + index, 'sampling')
    report = record.report()
    assert report['distinct_exact_currents'] == 2
    assert report['repeated_evaluations'] == 1
    assert report['current_overflow'] == 100
    assert report['total_string_states'] == 103
    assert len(record.currents) == 2
    nearby = Assembly({})
    nearby.current(1., 'sampling')
    nearby.current(1. + 1e-12, 'sampling')
    assert nearby.report()['distinct_exact_currents'] == 2


def test_real_assembly_preserves_every_output_and_restores_observer():
    model = real_model()
    models = {model.module_instance_id: model}
    circuit = _string(models)
    control = string_iv.assemble_general_series_string_iv(circuit, models, sample_count=25)
    original = string_iv._evaluate_module
    observer = Audit()
    with observer.installed():
        actual = string_iv.assemble_general_series_string_iv(circuit, models, sample_count=25)
    assert actual == control
    assert string_iv._evaluate_module is original
    assert sys.getprofile() is None
    assert observer.active == []
    record = observer.records[0].report()
    assert record['exact_currents'][0.0.hex()]['count'] == 3
    assert record['stages']['sampling'] == 25
    assert record['stages']['voc'] == 1
    assert record['total_string_states'] == sum(record['stages'].values())
    assert record['repeated_full_module_states'] >= 2
    assert record['changed_results_at_identical_request'] == 0
    assert not any('witness' in k or 'authorization' in k for k in observer.__dict__)


def test_real_module_states_bypass_reverse_and_full_repeat_bound():
    uniform, shaded = real_model(), real_model(shaded=True)
    record = Assembly({}, cap=1)
    inactive = string_iv._evaluate_module(uniform, 0., current_tolerance_a=1e-9)
    assert not any(s['bypass_active'] for s in inactive['protected_substrings'])
    record.module(uniform, 0., 1e-9, inactive)
    record.module(uniform, 0., 1e-9, inactive)
    active = string_iv._evaluate_module(shaded, shaded.current_domain_ceiling_a, current_tolerance_a=1e-9)
    assert any(s['bypass_active'] for s in active['protected_substrings'])
    assert active['terminal_voltage_v'] < 0
    record.module(shaded, shaded.current_domain_ceiling_a, 1e-9, active)
    assert record.bypass_active == 1
    assert record.negative_voltage == 1
    assert record.module_repeats == 1
    assert record.module_overflow == 1
    assert len(record.modules) == 1


def test_module_identity_and_tolerances_never_merge():
    model = real_model()
    state = string_iv._evaluate_module(model, 0., current_tolerance_a=1e-9)
    distinct = real_model()
    record = Assembly({})
    record.module(model, 0., 1e-9, state)
    record.module(model, 0., 1e-8, state)
    record.module(distinct, 0., 1e-9, state)
    assert record.module_repeats == 0
    assert len(record.modules) == 3


@pytest.fixture
def attribution_observer():
    from shading.electrical import dc_attribution as dc
    from tests.unit.test_phase69a_detailed_inputs import _inputs
    pinned = _inputs()
    region_map, local = _handoff(pinned['topology'], irradiance_overrides={'s1-r1': 900.})
    observer = Audit()
    with observer.installed():
        bases, curves = dc.evaluate_independent_module_bases(pinned,
            {'region_map': region_map, 'local_irradiance': local}, sample_count=25)
    assert set(curves) == set('UNB'), bases
    return observer, region_map, local


def test_real_attribution_capture_and_report(attribution_observer):
    from shading.electrical.dc_attribution import uniform_effective_input
    observer, region_map, local = attribution_observer
    assert [r.context['basis'] for r in observer.records] == list('UNB')
    captured = [json.loads(r.context['complete_source_inputs_exact_json']) for r in observer.records]
    assert captured[0]['local'] == json.loads(encoded(uniform_effective_input(region_map, local)))
    assert captured[1]['local'] == captured[2]['local'] == json.loads(encoded(local))
    assert observer.records[1].context['models'][0]['model_id'] != observer.records[2].context['models'][0]['model_id']
    report = observer.report()
    assert not report['exact_complete_context_repeat_groups']
    assert not report['potential_cross_module_equivalence_groups']
    assert sum(report['repetition_distribution'].values()) == 3
    assert all(v == 0 for v in report['absent_electrical_stages'].values())
    assert report['cache_reuse']['actual_cache_hit_returns'] >= 0
    assert report['cache_reuse']['branch_requests'] >= report['cache_reuse']['actual_cache_hit_returns']


@pytest.mark.parametrize('field,value', [
    ('basis', 'N'), ('model_id', 'different-model'), ('irradiance', 999.),
    ('temperature', 26.), ('current_tolerance_a', 1e-8),
    ('voltage_tolerance_v', 1e-8), ('max_iterations', 100)])
def test_report_separates_captured_contexts(attribution_observer, field, value):
    observer, _, _ = attribution_observer
    context = copy.deepcopy(observer.records[2].context)
    duplicate = Assembly(copy.deepcopy(context))
    observer.records = [Assembly(context), duplicate]
    assert observer.report()['exact_complete_context_repeat_groups'] == [[0, 1]]
    changed = duplicate.context
    if field == 'basis':
        changed[field] = value
    elif field == 'model_id':
        changed['models'][0][field] = value
    elif field in ('irradiance', 'temperature'):
        inputs = json.loads(changed['complete_source_inputs_exact_json'])
        if field == 'irradiance':
            inputs['local']['regions'][0]['effective_irradiance_w_m2'] = json.loads(encoded(value))
        else:
            inputs['local']['module_temperature_c'] = json.loads(encoded(value))
        changed['complete_source_inputs_exact_json'] = json.dumps(inputs, sort_keys=True)
    else:
        changed['solver'][field] = json.loads(encoded(value))
    assert not observer.report()['exact_complete_context_repeat_groups']


def test_cross_instance_comparison_retains_field_evidence(attribution_observer):
    observer, _, _ = attribution_observer
    context = copy.deepcopy(observer.records[2].context)
    other = copy.deepcopy(context)
    other['models'][0]['instance'] = 'another-module'
    other['models'][0]['scientific_input_sha256'] = 'different-provenance'
    inputs = json.loads(other['complete_source_inputs_exact_json'])
    inputs['local']['source_module_instance_id'] = 'another-module'
    other['complete_source_inputs_exact_json'] = json.dumps(inputs, sort_keys=True)
    observer.records = [Assembly(context), Assembly(other)]
    comparison, = observer.report()['potential_cross_module_equivalence_groups']
    assert comparison['assemblies'] == [0, 1]
    assert comparison['status'] == 'candidate, not proven'
    assert '/source_inputs/local/source_module_instance_id' in comparison['differing_fields']
    assert not any('effective_irradiance' in p or 'temperature' in p for p in comparison['differing_fields'])
    other['basis'] = 'U'
    assert not observer.report()['potential_cross_module_equivalence_groups']


def test_global_payload_budget():
    budget = ByteBudget(0)
    record = Assembly({}, budget=budget)
    for current in range(100):
        record.current(float(current), 'sampling')
    assert budget.used == 0
    assert budget.overflow == record.overflow == 100
    observer = Audit(payload_bytes=0)
    assert observer.report()['payload_byte_limit'] == 0


def test_observer_restored_on_exception_and_assembly_limit():
    observer = Audit(assembly_cap=0)
    model = real_model()
    with pytest.raises(RuntimeError), observer.installed():
        string_iv.assemble_general_series_string_iv(_string([model.module_instance_id]),
            {model.module_instance_id: model}, sample_count=25)
        raise RuntimeError('contract exit')
    assert observer.skipped_assemblies == 1
    assert observer.records == []
    assert sys.getprofile() is None


def test_cli_contract():
    assert parser().parse_args(['--size', '10', '--output', '/tmp/audit.json']).size == 10
    with pytest.raises(SystemExit):
        parser().parse_args(['--size', '190', '--output', '/tmp/audit.json'])
    with pytest.raises(SystemExit):
        parser().parse_args([])


@pytest.mark.parametrize('failure', ['exit', 'timeout', 'fingerprint'])
def test_cli_failure_json(monkeypatch, tmp_path, failure):
    from scripts.benchmarks import rb_post3d_08p2c3a_audit as diagnostic
    output = tmp_path / 'result.json'
    monkeypatch.setattr(sys, 'argv', ['audit', '--output', str(output)])
    def run(command, **kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(command, 600)
        if failure == 'fingerprint':
            child_output = command[command.index('--output') + 1]
            from pathlib import Path
            Path(child_output).write_text(json.dumps({'completion_status': 'fingerprint_mismatch',
                                                     'output_fingerprints_unchanged': False}))
            return subprocess.CompletedProcess(command, 0)
        return subprocess.CompletedProcess(command, 1)
    monkeypatch.setattr(diagnostic.subprocess, 'run', run)
    with pytest.raises(SystemExit) as exc:
        diagnostic.main()
    assert exc.value.code == 1
    report = json.loads(output.read_text())
    assert report['completion_status'] == ('fingerprint_mismatch' if failure == 'fingerprint' else 'blocked')
    assert report['baseline_commit'] == '3873f0f'
    assert report['evidence_limitations']
