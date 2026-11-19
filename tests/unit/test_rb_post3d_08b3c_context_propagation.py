"""B3C transport/boundary regressions. Plumbing tests grant no execution permit."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import pickle
from types import SimpleNamespace

import pytest

from engine.simulation import detailed_inputs as inputs
from engine.simulation import detailed_backend as backend
from engine.simulation import detailed_attribution as attribution
from shading.electrical.contract import NumericalAssumptionInputError
from shading.electrical import dc_attribution as dc
from shading.electrical.module_series_adapter import build_phase66_series_module_operating_model, Phase66SeriesModuleAdapterError
from shading.electrical.module_iv import assemble_nonuniform_module_iv, NonuniformModuleIVError
from shading.electrical.parameterization import build_pvsyst_region_electrical_states, ElectricalParameterizationError
from tests.unit import test_rb_post3d_08b3b_snapshot_witness as b3b
from tests.unit.test_phase69a_detailed_inputs import _inputs
from tests.unit.test_phase66_nonuniform_module_iv import (
    _topology, _parameterization, _evidence, _handoff,
)


def _boundary():
    configuration, frozen, snapshot = b3b._b2_witness_fixture()
    transport = inputs.prepare_execution_transport({'M': snapshot}, configuration, frozen)
    return {**transport, 'module_inputs': {'M': json.loads(snapshot.canonical_payload)}}, snapshot


def test_legacy_payload_bytes_and_replay():
    payload = _inputs()
    snapshot = inputs.pin_detailed_module_inputs(**payload)
    assert snapshot.canonical_payload == inputs._bytes(payload)
    assert snapshot.scientific_input_sha256 == hashlib.sha256(inputs._bytes(payload)).hexdigest()
    assert snapshot.replay() == payload
    assert set(snapshot.replay()) == {'module', 'topology', 'parameterization', 'evidence', 'sources'}
    context = inputs.prepare_execution_transport({'M': snapshot})
    assert context['module_witnesses'] == {'M': None}
    inputs.validate_execution_transport({**context, 'module_inputs': {'M': snapshot.replay()}})


@pytest.mark.parametrize('field', ['module_revision_id', 'topology_revision_id', 'parameterization_revision_id'])
def test_revision_membership_rejected(field):
    context, snapshot = _boundary()
    context['module_witnesses']['M'] = replace(snapshot.witness, **{field: 'foreign'})
    with pytest.raises(inputs.SnapshotWitnessError, match='witness'):
        inputs.validate_execution_transport(context)


@pytest.mark.parametrize('foreign', ['configuration', 'selection'])
def test_foreign_trusted_inputs_rejected(foreign):
    b3b.test_foreign_self_consistent_context_rejected(foreign)


@pytest.mark.parametrize('initializer', [backend._initialize_interval_worker, attribution._initialize_attribution_worker])
@pytest.mark.parametrize('fault', ['missing', 'boolean', 'foreign_revision', 'foreign_module', 'missing_expected'])
def test_worker_boundary_denies_invalid_context(initializer, fault):
    context, snapshot = _boundary()
    if fault == 'missing': context['module_witnesses'] = {}
    elif fault == 'boolean': context['module_witnesses']['M'] = True
    elif fault == 'foreign_revision': context['expected_module_revisions']['M'] = 'foreign'
    elif fault == 'foreign_module': context['module_witnesses']['foreign'] = snapshot.witness
    else: context['expected_witness_context'] = None
    diagnostic = {'missing': 'missing numerical-assumption worker context',
        'boolean': 'witness type', 'foreign_revision': 'foreign worker module revision membership',
        'foreign_module': 'foreign worker module membership',
        'missing_expected': 'missing independently expected worker context'}[fault]
    with pytest.raises(inputs.SnapshotWitnessError, match=diagnostic):
        initializer(context)


def test_pickle_shared_identity_is_membership_only():
    context, snapshot = _boundary()
    context['module_witnesses']['duplicate'] = snapshot.witness
    context['module_inputs']['duplicate'] = context['module_inputs']['M']
    context['expected_module_revisions']['duplicate'] = snapshot.witness.module_revision_id
    restored = pickle.loads(pickle.dumps(context))
    assert restored['module_witnesses']['M'].context is restored['module_witnesses']['duplicate'].context
    inputs.validate_execution_transport(restored)
    assert inputs.DetailedModuleInputSnapshot(snapshot.canonical_payload, snapshot.scientific_input_sha256,
        restored['module_witnesses']['M']).replay() == restored['module_inputs']['M']
    restored['module_witnesses']['foreign'] = snapshot.witness
    with pytest.raises(inputs.SnapshotWitnessError, match='foreign worker module membership'):
        inputs.validate_execution_transport(restored)


@pytest.mark.parametrize('kernel', [build_phase66_series_module_operating_model,
                                    assemble_nonuniform_module_iv, build_pvsyst_region_electrical_states])
@pytest.mark.parametrize('witness_kind', ['valid', 'missing', 'boolean'])
def test_public_kernel_cannot_authorize(kernel, witness_kind):
    _, _, snapshot = b3b._b2_witness_fixture(False)
    payload = json.loads(snapshot.canonical_payload)
    region_map, local = _handoff(payload['topology'])
    witness = {'valid': snapshot.witness, 'missing': None, 'boolean': True}[witness_kind]
    error = inputs.SnapshotWitnessError if witness_kind == 'boolean' else NumericalAssumptionInputError
    diagnostic = {'valid': 'requires scientific opt-in', 'missing': 'B3 authorization boundary',
                  'boolean': 'witness type'}[witness_kind]
    with pytest.raises(error, match=diagnostic):
        kernel(payload['topology'], region_map, local, payload['parameterization'], payload['evidence'],
               authorization_witness=witness)


@pytest.mark.parametrize('dark', [False, True])
def test_assumed_attribution_never_becomes_unavailable(dark):
    _, _, snapshot = b3b._witness_fixture()
    payload = json.loads(snapshot.canonical_payload)
    region_map, local = _handoff(payload['topology'])
    if dark:
        for region in local['regions']: region['effective_irradiance_w_m2'] = 0
    with pytest.raises(NumericalAssumptionInputError, match='EXECUTION_DENIED'):
        dc.evaluate_independent_module_bases(payload, {'region_map': region_map, 'local_irradiance': local},
                                            sample_count=101, authorization_witness=snapshot.witness)


@pytest.mark.parametrize('error', [NumericalAssumptionInputError, inputs.SnapshotWitnessError])
def test_broad_value_error_does_not_swallow_integrity(monkeypatch, error):
    payload = _inputs()
    region_map, local = _handoff(payload['topology'])
    def reject(*args, **kwargs): raise error('integrity denial')
    monkeypatch.setattr(dc, 'build_phase66_series_module_operating_model', reject)
    monkeypatch.setattr(dc, 'build_bypass_off_module_model', reject)
    with pytest.raises(error, match='integrity denial'):
        dc.evaluate_independent_module_bases(payload, {'region_map': region_map, 'local_irradiance': local}, sample_count=101)


def test_legacy_unavailable_reason_codes(monkeypatch):
    payload = _inputs()
    region_map, local = _handoff(payload['topology'])
    def reject(*args, **kwargs): raise ValueError('bounded solver domain')
    monkeypatch.setattr(dc, 'build_phase66_series_module_operating_model', reject)
    monkeypatch.setattr(dc, 'build_bypass_off_module_model', reject)
    bases, curves = dc.evaluate_independent_module_bases(payload, {'region_map': region_map, 'local_irradiance': local}, sample_count=101)
    assert not curves
    assert bases['U']['reason_codes'] == ['independent_module_iv_unavailable']
    assert bases['N']['reason_codes'] == ['bypass_off_domain_unsupported']


def test_serial_attribution_plumbing_forwards_same_witness(monkeypatch):
    configuration, frozen, snapshot = b3b._b2_witness_fixture()
    context = attribution._attribution_context({'M': snapshot}, {'M': SimpleNamespace(module_solver='lambertw')},
                                              {'strings': []}, 101, False, configuration, frozen)
    observed = []
    def reject(*args, **kwargs):
        observed.append(kwargs['authorization_witness'])
        raise NumericalAssumptionInputError('plumbing stops before execution')
    monkeypatch.setattr(attribution, 'evaluate_independent_module_bases', reject)
    with pytest.raises(NumericalAssumptionInputError, match='plumbing stops'):
        attribution._evaluate_attribution_interval(context, {'modules': {'M': {}}})
    assert observed == [snapshot.witness]
    assert observed[0] is snapshot.witness


def test_series_adapter_retains_original_solver_and_negative_voltage():
    from shading.electrical.module_series_adapter import _build_series_model_from_checked_states
    topology = _topology()
    definition = _parameterization(topology)
    evidence = _evidence(definition)
    region_map, local = _handoff(topology)
    states = build_pvsyst_region_electrical_states(topology, region_map, local, definition, evidence)
    original = _build_series_model_from_checked_states(topology, region_map, local, definition, evidence, states)
    transported = build_phase66_series_module_operating_model(topology, region_map, local, definition, evidence)
    assert transported.scientific_input_sha256 == original.scientific_input_sha256
    ceiling = transported.current_domain_ceiling_a
    for current in [0, ceiling * .5, ceiling]:
        assert transported.voltage_at_current(current) == original.voltage_at_current(current)
    assert transported.voltage_at_current(ceiling)['terminal_voltage_v'] < 0


def test_parameterization_resolution_exact_and_legacy_unique():
    payload = _inputs()
    definition = payload['parameterization']
    assets = {'electrical_parameterization_definitions': {definition['revision_id']: definition}}
    assert inputs.resolve_selected_parameterization(assets, payload['evidence']) == definition
    other = deepcopy(definition)
    other['revision_id'] += '-foreign'
    assets['electrical_parameterization_definitions'][other['revision_id']] = other
    with pytest.raises(inputs.DetailedInputError, match='ambiguous'):
        inputs.resolve_selected_parameterization(assets, payload['evidence'])
    _, _, snapshot = b3b._witness_fixture()
    assumed = json.loads(snapshot.canonical_payload)
    assets = {'electrical_parameterization_definitions': {assumed['parameterization']['revision_id']: assumed['parameterization']}}
    assert inputs.resolve_selected_parameterization(assets, assumed['evidence']) == assumed['parameterization']
    assets['electrical_parameterization_definitions'] = {other['revision_id']: other}
    with pytest.raises(inputs.SnapshotWitnessError, match='revision mismatch'):
        inputs.resolve_selected_parameterization(assets, assumed['evidence'])


def test_cell_scope_specific_denial():
    _, _, snapshot = b3b._witness_fixture()
    payload = json.loads(snapshot.canonical_payload)
    payload['evidence']['parameterization_scope'] = 'cell'
    with pytest.raises(NumericalAssumptionInputError, match='unsupported numerical-assumption scope'):
        inputs.deny_selected_numerical_evidence(payload['evidence'], module=payload['module'], topology=payload['topology'],
                                              parameterization=payload['parameterization'])


def test_replay_cache_avoids_full_context_and_schema_validation(monkeypatch):
    _, _, snapshot = b3b._witness_fixture()
    inputs._cached_witness_context_inputs.cache_clear()
    inputs._cached_selected_witness_bytes.cache_clear()
    inputs._cached_detailed_snapshot_witness.cache_clear()
    calls = []
    original = inputs._schema
    def count(*args):
        calls.append(args[1])
        return original(*args)
    monkeypatch.setattr(inputs, '_schema', count)
    with pytest.raises(NumericalAssumptionInputError): snapshot.replay()
    first_count = len(calls)
    assert first_count > 0
    for _ in range(3):
        with pytest.raises(NumericalAssumptionInputError): snapshot.replay()
    assert len(calls) == first_count
    assert inputs._cached_witness_context_inputs.cache_info().maxsize == 16
    assert inputs._cached_selected_witness_bytes.cache_info().maxsize == 128
    # These caches retain structural inputs/bytes only. A hit still denies execution.
    assert type(inputs._cached_selected_witness_bytes(snapshot.witness.context, snapshot.witness.module_revision_id,
                                                     inputs._WITNESS_CACHE_POLICY)) is bytes


def test_cached_membership_retains_each_callers_context_identity():
    configuration, frozen, snapshot = b3b._witness_fixture()
    first = snapshot.witness.context
    second_frozen = replace(frozen)
    second = inputs.build_snapshot_witness_context(configuration, second_frozen)
    assert first == second and first is not second
    inputs._cached_detailed_snapshot_witness.cache_clear()
    for context in (first, second, first):
        witness = inputs.build_detailed_snapshot_witness(context, snapshot.witness.module_revision_id)
        assert witness.context is context
        assert witness.context.frozen_selection is context.frozen_selection
    assert inputs._cached_detailed_snapshot_witness.cache_info().hits == 2
    membership = inputs._cached_detailed_snapshot_witness(
        second, snapshot.witness.module_revision_id, inputs._WITNESS_CACHE_POLICY)
    assert type(membership) is tuple
    assert all(type(value) in (str, bool) for value in membership)


def test_cache_bounded_eviction_and_rehashed_tampering():
    configuration, frozen, snapshot = b3b._witness_fixture()
    inputs._cached_witness_context_inputs.cache_clear()
    for value in range(18):
        changed = deepcopy(configuration)
        b3b._request(changed)['scientific_options']['string_sample_count'] = 101 + value
        inputs.build_snapshot_witness_context(changed, frozen)
    assert inputs._cached_witness_context_inputs.cache_info().currsize == 16
    forged = replace(snapshot.witness.context, canonical_configuration=b'{}')
    with pytest.raises(inputs.SnapshotWitnessError):
        inputs.compare_snapshot_witness_context(replace(snapshot.witness, context=forged), configuration, frozen)


@pytest.mark.parametrize('policy', ['fail_closed', 'explicit_lower_fidelity'])
def test_public_dispatch_denied_without_downgrade(tmp_path, policy):
    b3b.test_schema_valid_selected_v02_dispatch_denied_without_downgrade(tmp_path, policy, False)


def test_unselected_v02_level_zero(tmp_path):
    b3b.test_unselected_v02_allows_legacy_level_zero(tmp_path)


def test_legacy_fallback(tmp_path):
    b3b.test_legacy_fallback_preserved(tmp_path)


def test_shared_context_without_large_copies():
    b3b.test_shared_bytes_across_distinct_module_snapshots_and_foreign_membership()


def test_backend_plumbing_forwards_original_witness(monkeypatch):
    context, snapshot = _boundary()
    context.update(strings=[], mppts=[], policy={}, mppt_templates={}, module_solvers={'M': 'lambertw'})
    payload = context['module_inputs']['M']
    region_map, local = _handoff(payload['topology'])
    observed = []
    def reject(*args, **kwargs):
        observed.append(kwargs['authorization_witness'])
        raise NumericalAssumptionInputError('plumbing stops before execution')
    monkeypatch.setattr(backend, 'build_phase66_series_module_operating_model', reject)
    with pytest.raises(NumericalAssumptionInputError, match='plumbing stops'):
        backend._evaluate_interval(context, {}, {'M': {'region_map': region_map, 'local_irradiance': local}})
    assert observed[0] is snapshot.witness


def test_adapter_plumbing_forwards_regional_witness(monkeypatch):
    from shading.electrical import module_series_adapter as adapter
    _, _, snapshot = b3b._witness_fixture()
    payload = json.loads(snapshot.canonical_payload)
    region_map, local = _handoff(payload['topology'])
    observed = []
    def reject(*args, **kwargs):
        observed.append(kwargs['authorization_witness'])
        raise NumericalAssumptionInputError('plumbing stops before execution')
    monkeypatch.setattr(adapter, 'build_pvsyst_region_electrical_states', reject)
    with pytest.raises(NumericalAssumptionInputError, match='plumbing stops'):
        adapter.build_phase66_series_module_operating_model(payload['topology'], region_map, local,
            payload['parameterization'], payload['evidence'], authorization_witness=snapshot.witness)
    assert observed[0] is snapshot.witness


def test_source_backed_adapter_unchanged_with_default_context():
    payload = _inputs()
    region_map, local = _handoff(payload['topology'])
    args = (payload['topology'], region_map, local, payload['parameterization'], payload['evidence'])
    legacy = build_phase66_series_module_operating_model(*args)
    transported = build_phase66_series_module_operating_model(*args, authorization_witness=None)
    assert legacy.scientific_input_sha256 == transported.scientific_input_sha256
    for fraction in [0, .5, 1]:
        current = fraction * legacy.current_domain_ceiling_a
        assert legacy.voltage_at_current(current) == transported.voltage_at_current(current)


def test_repeated_interval_entries_do_not_revalidate_schemas(monkeypatch):
    # Boundary plumbing: both real interval entries stop before numerical work.
    context, snapshot = _boundary()
    context.update(strings={}, mppts={}, policy={}, mppt_templates={},
                   sample_count=101, retain_diagnostics=False,
                   region_solvers={'M': 'lambertw'}, module_solvers={'M': 'lambertw'})
    calls = []
    original = inputs._schema
    def count(*args):
        calls.append(args[1])
        return original(*args)
    inputs.validate_execution_transport(context)
    monkeypatch.setattr(inputs, '_schema', count)
    def reject(*args, **kwargs):
        raise NumericalAssumptionInputError('interval denial')
    monkeypatch.setattr(attribution, 'evaluate_independent_module_bases', reject)
    monkeypatch.setattr(backend, 'build_phase66_series_module_operating_model', reject)
    region_map, local = _handoff(context['module_inputs']['M']['topology'])
    for _ in range(4):
        with pytest.raises(NumericalAssumptionInputError, match='interval denial'):
            attribution._evaluate_attribution_interval(context, {'modules': {'M': {}}})
        with pytest.raises(NumericalAssumptionInputError, match='interval denial'):
            backend._evaluate_interval(context, {}, {'M': {'region_map': region_map, 'local_irradiance': local}})
    assert calls == []
    # A structural cache hit is never authority for a foreign transport.
    context['module_witnesses']['M'] = replace(snapshot.witness, module_revision_id='foreign')
    with pytest.raises(inputs.SnapshotWitnessError):
        inputs.validate_execution_transport(context)
    assert snapshot.replay() == json.loads(snapshot.canonical_payload)


def test_cached_structures_cannot_be_mutated_through_public_internal_reader():
    _, _, snapshot = b3b._witness_fixture()
    configuration, bundle = inputs._witness_context_inputs(snapshot.witness.context)
    configuration.clear()
    bundle.clear()
    restored, selection = inputs._witness_context_inputs(snapshot.witness.context)
    assert restored and selection
    with pytest.raises(NumericalAssumptionInputError):
        snapshot.replay()


def test_pinned_phase66_reverse_voltage_reference():
    # Established pre-B3C fixture/reference in Phase-6.6 regression suite.
    from tests.unit.test_phase66_nonuniform_module_iv import (
        test_phase66_effective_current_ceiling_intersects_current_and_voltage_domains,
    )
    test_phase66_effective_current_ceiling_intersects_current_and_voltage_domains()


def _ambiguous_legacy_bundle():
    payload = _inputs()
    module, topology, definition, evidence = (payload[k] for k in
                                             ['module', 'topology', 'parameterization', 'evidence'])
    other = deepcopy(definition)
    other['revision_id'] += '-foreign'
    return payload, {
        'electrical_shading_selections': {module['revision_id']: {
            'module_topology_revision_id': topology['revision_id'],
            'region_parameterization_evidence_id': evidence['evidence_id']}},
        'pinned_electrical_shading_assets': {
            'module_topologies': {topology['revision_id']: topology},
            'electrical_parameterization_evidence': {evidence['evidence_id']: evidence},
            'electrical_parameterization_definitions': {definition['revision_id']: definition,
                                                      other['revision_id']: other},
            'sources': payload['sources']},
    }


def test_prepare_backend_rejects_ambiguous_legacy_definition(monkeypatch):
    from engine.simulation import detailed_dispatch as dispatch
    import geometry.shading
    payload, bundle = _ambiguous_legacy_bundle()
    module = {'module_instance_id': 'M', 'enabled': True,
              'module_definition_revision_id': payload['module']['revision_id']}
    monkeypatch.setattr(geometry.shading, 'compile_shading_geometry', lambda scene: {
        'findings': [], 'receivers': [{'source_entity_id': 'M', 'source_entity_type': 'module_instance'}]})
    store = SimpleNamespace(detailed_electrical_inputs=SimpleNamespace(replay=lambda: bundle),
        component_revisions={payload['module']['revision_id']: payload['module'], 'inverter': {}})
    with pytest.raises(inputs.DetailedInputError, match='ambiguous'):
        dispatch._prepare_backend({}, store, {'module_instances': [module], 'surfaces': []},
            {'inverter_instances': [{'enabled': True, 'inverter_definition_revision_id': 'inverter'}]},
            [], 'run', 'project', 'time')


def test_attribution_verifier_rejects_ambiguous_legacy_definition():
    from engine.simulation.artifacts import canonical_object_sha256
    payload, bundle = _ambiguous_legacy_bundle()
    design = {'strings': []}
    source = {'scientific_input_sha256': 'scientific',
              'source_numerical_result_sha256': 'numerical',
              'source_electrical_design_sha256': canonical_object_sha256(design)}
    result = SimpleNamespace(replay_stream=lambda: source)
    context = {'identity': {'scientific_input_sha256': 'scientific', 'numerical_result_sha256': 'numerical'},
        'inputs': {'electrical_design': design, 'frozen_selection': bundle,
                   'scene': {'module_instances': [{'enabled': True, 'module_instance_id': 'M',
                       'module_definition_revision_id': payload['module']['revision_id']}]}}}
    with pytest.raises(inputs.DetailedInputError, match='ambiguous'):
        attribution.verify_attribution_sources(result, context)


@pytest.mark.parametrize('workers', [1, 2, 4])
@pytest.mark.parametrize('diagnostics', [False, True])
def test_abbreviated_dark_completed_pass_stays_in_parent(monkeypatch, workers, diagnostics):
    from tests.unit.test_phase610_stage3a_interval_contract import collector, dark_payload
    numerical = backend.DetailedMPPTBackendResult.freeze(dark_payload())
    serial = collector(1, diagnostics)
    expected = attribution.execute_detailed_dc_attribution(numerical, **serial.arguments)
    def forbidden(*args, **kwargs):
        raise AssertionError('dark-only path must perform no numerical transport or work')
    monkeypatch.setattr(attribution, 'ProcessPoolExecutor', forbidden)
    monkeypatch.setattr(attribution, 'evaluate_independent_module_bases', forbidden)
    parallel = collector(1, diagnostics)
    result = attribution.execute_detailed_attribution_pass(numerical, collector=parallel,
                                                          attribution_worker_count=workers)
    try:
        assert result == expected
        assert all(not m['counterfactual_curve_hashes'] for i in result.replay()['intervals'] for m in i['modules'])
    finally:
        result.close()
        expected.close()
        serial.close()


def test_abbreviated_dark_chunks_recheck_later_illuminated_interval():
    from tests.unit.test_phase610_stage3a_interval_contract import collector, dark_payload
    explanation = collector(1)
    payload = dark_payload(2)
    try:
        explanation(backend.DetailedMPPTBackendResult.freeze({**payload, 'intervals': payload['intervals'][:1]}))
        payload['intervals'][1]['modules']['m']['local_irradiance']['regions'][0]['effective_irradiance_w_m2'] = 1
        with pytest.raises(inputs.SnapshotWitnessError, match='entirely dark'):
            # Raw interval targets the attribution gate; freezing this deliberately
            # inconsistent physical state would reject it in the backend first.
            attribution._evaluate_attribution_interval(explanation._execution_context, payload['intervals'][1])
    finally:
        explanation.close()


@pytest.mark.parametrize('fault', ['selected', 'missing_registry', 'stripped_snapshot', 'missing_witness', 'boolean'])
def test_dark_input_never_authorizes_selected_assumptions(fault):
    from tests.unit.test_phase610_stage3a_interval_contract import collector, dark_payload
    configuration, frozen, snapshot = b3b._witness_fixture()
    explanation = collector(1)
    arguments = explanation.arguments
    arguments.update(scientific_configuration=configuration, frozen_selection=frozen)
    if fault == 'missing_registry':
        bundle = json.loads(frozen.canonical_payload)
        bundle['pinned_electrical_shading_assets']['electrical_parameterization_evidence'].clear()
        arguments['frozen_selection'] = bundle
    elif fault == 'stripped_snapshot':
        payload = json.loads(snapshot.canonical_payload)
        payload.pop('evidence')
        arguments['module_inputs'] = {'m': SimpleNamespace(scientific_input_sha256=snapshot.scientific_input_sha256,
                                                         replay=lambda: payload)}
    elif fault == 'missing_witness':
        arguments['module_inputs'] = {'m': inputs.DetailedModuleInputSnapshot(snapshot.canonical_payload,
                                                                            snapshot.scientific_input_sha256)}
    elif fault == 'boolean':
        arguments['frozen_selection'] = None
        arguments['module_inputs']['m'].witness = True
    try:
        error_match = {
            'selected': 'EXECUTION_DENIED',
            'missing_registry': 'dark attribution selected evidence invalid',
            'stripped_snapshot': 'EXECUTION_DENIED',
            'missing_witness': 'EXECUTION_DENIED',
            'boolean': 'without witness',
        }[fault]
        with pytest.raises((NumericalAssumptionInputError, inputs.SnapshotWitnessError), match=error_match):
            attribution.execute_detailed_dc_attribution(backend.DetailedMPPTBackendResult.freeze(dark_payload()), **arguments)
    finally:
        explanation.close()


def test_dark_only_context_rejected_at_worker_boundary():
    from tests.unit.test_phase610_stage3a_interval_contract import collector
    explanation = collector(1)
    try:
        args = explanation.arguments
        context = attribution._attribution_context(args['module_inputs'], args['module_configs'],
                                                   args['electrical_design'], 101, False)
        assert 'expected_module_revisions' not in context
        assert 'module_witnesses' not in context
        with pytest.raises(inputs.SnapshotWitnessError, match='worker boundary'):
            attribution._initialize_attribution_worker(context)
    finally:
        explanation.close()


@pytest.mark.parametrize('fault', ['configuration', 'selection', 'missing'])
def test_parent_transport_rejects_foreign_expected_inputs(fault):
    configuration, frozen, snapshot = b3b._witness_fixture()
    if fault == 'configuration':
        configuration = deepcopy(configuration)
        b3b._request(configuration)['scientific_options']['string_sample_count'] = 103
    elif fault == 'selection':
        bundle = json.loads(frozen.canonical_payload)
        bundle['pinned_electrical_shading_assets']['sources']['b3b-original']['title'] += ' changed'
        frozen = b3b._raw_frozen(bundle)
    else:
        configuration = None
    with pytest.raises(inputs.SnapshotWitnessError, match=(
            'missing independently expected run context' if fault == 'missing'
            else 'foreign configuration or selection')):
        inputs.prepare_execution_transport({'M': snapshot}, configuration, frozen)


@pytest.mark.parametrize('fault', ['selection', 'missing_replay', 'noncallable_replay', 'invalid_replay'])
def test_dark_compatibility_classifies_malformed_inputs(fault):
    from tests.unit.test_phase610_stage3a_interval_contract import collector
    explanation = collector(1)
    arguments = dict(explanation.arguments)
    arguments['sample_count'] = 101
    if fault == 'selection':
        arguments['frozen_selection'] = object()
        message = 'selected evidence invalid'
    else:
        malformed = {
            'missing_replay': SimpleNamespace(),
            'noncallable_replay': SimpleNamespace(replay=None),
            'invalid_replay': SimpleNamespace(replay=lambda: None),
        }[fault]
        arguments['module_inputs'] = {'m': malformed}
        message = 'legacy input invalid'
    try:
        with pytest.raises(inputs.SnapshotWitnessError, match=message):
            attribution._attribution_context(**arguments)
    finally:
        explanation.close()


def test_dark_compatibility_preserves_final_physical_coverage():
    from tests.unit.test_phase610_stage3a_interval_contract import collector, dark_payload
    explanation = collector(1)
    payload = dark_payload(2)
    try:
        explanation(backend.DetailedMPPTBackendResult.freeze({**payload, 'intervals': payload['intervals'][:1]}))
        with pytest.raises(ValueError, match='coverage'):
            explanation.finish(backend.DetailedMPPTBackendResult.freeze(payload))
    finally:
        explanation.close()


@pytest.mark.parametrize('initializer', [backend._initialize_interval_worker, attribution._initialize_attribution_worker])
def test_worker_rejects_foreign_expected_configuration(initializer):
    context, snapshot = _boundary()
    configuration, frozen, _ = b3b._witness_fixture()
    b3b._request(configuration)['scientific_options']['string_sample_count'] = 103
    context['expected_witness_context'] = inputs.build_snapshot_witness_context(
        configuration, frozen)
    with pytest.raises(inputs.SnapshotWitnessError, match='foreign configuration or selection'):
        initializer(context)


@pytest.mark.parametrize('valid_physics', [False, True])
def test_foreign_membership_precedes_b2_acceptance(monkeypatch, valid_physics):
    if valid_physics:
        context, snapshot = _boundary()
    else:
        config, frozen, snapshot = b3b._witness_fixture()
        context = {**inputs.prepare_execution_transport({'M': snapshot}, config, frozen),
                   'module_inputs': {'M': json.loads(snapshot.canonical_payload)}}
    context['module_witnesses']['foreign'] = snapshot.witness
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError('foreign membership reached B2')
    monkeypatch.setattr(inputs, 'validate_assumption_authorization_witness', forbidden)
    with pytest.raises(inputs.SnapshotWitnessError, match='foreign worker module membership'):
        inputs.validate_execution_transport(context)
    assert calls == []


def test_regional_authority_is_evaluated_once(monkeypatch):
    _, _, snapshot = b3b._b2_witness_fixture()
    payload = json.loads(snapshot.canonical_payload)
    original = inputs.validate_assumption_authorization_witness
    calls = []
    def real(witness):
        calls.append(witness)
        return original(witness)
    monkeypatch.setattr(inputs, 'validate_assumption_authorization_witness', real)
    inputs.validate_regional_transport(snapshot.witness, payload['topology'],
                                      payload['parameterization'], payload['evidence'])
    assert calls == [snapshot.witness]
    calls.clear()
    inputs.deny_selected_numerical_evidence(payload['evidence'], module=payload['module'],
        topology=payload['topology'], parameterization=payload['parameterization'],
        authorization_witness=snapshot.witness)
    assert calls == [snapshot.witness]
