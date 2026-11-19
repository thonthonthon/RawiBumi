"""B3B content witnesses and public fail-closed dispatch regressions."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from functools import lru_cache
import json

import pytest

from components.topology_library import canonical_topology_asset_sha256
from engine.simulation.artifacts import canonical_object_sha256
from engine.simulation.detailed_dispatch import scientific_configuration
from engine.simulation.detailed_inputs import (
    AssumptionSnapshotWitness, DetailedModuleInputSnapshot,
    FrozenDetailedSelectionSnapshot, SnapshotWitnessError, _bytes,
    build_snapshot_witness_context, build_detailed_snapshot_witness,
    compare_snapshot_witness_context, freeze_detailed_selection,
    pin_detailed_module_inputs, semantic_scientific_payload,
)
from shading.electrical.contract import (
    NumericalAssumptionInputError, assert_numerical_assumption_evidence_structure,
    validate_parameterization_for_electrical_shading,
)
from shading.electrical.parameterization import finalize_parameterization_payload
from tests.unit.test_phase69a_detailed_inputs import _inputs, _configuration
from tests.unit.test_phase69a_canonical_dispatch import _context, _run
from tests.unit.test_rb_post3d_08b1_evidence_foundation import assumed, seal, VALIDATOR
from tests.unit.test_rb_post3d_08b2_region_physics import _source


def _request(config):
    return config['shading_configuration']['electrical_shading_configuration']


def _raw_frozen(bundle):
    payload = {key: deepcopy(bundle[key]) for key in (
        'pinned_components', 'pinned_electrical_shading_assets', 'electrical_shading_selections')}
    payload['pinned_components'] = {'modules': payload['pinned_components']['modules']}
    encoded = _bytes(payload)
    return FrozenDetailedSelectionSnapshot(encoded, hashlib.sha256(encoded).hexdigest(),
        canonical_object_sha256(semantic_scientific_payload(payload)))


def _seal_selection(selection):
    fields = ('state_version', 'module_definition_revision_id', 'module_topology_revision_id',
              'region_parameterization_evidence_id', 'cell_parameterization_evidence_id',
              'requested_fidelity', 'resolved_fidelity', 'fallback_policy')
    selection['selection_payload_sha256'] = canonical_object_sha256(
        {key: selection.get(key) for key in fields})


def _add_assumed(bundle, module_revision=None, suffix=''):
    assets = bundle['pinned_electrical_shading_assets']
    selection = next(iter(bundle['electrical_shading_selections'].values()))
    original_revision = selection['module_definition_revision_id']
    module = deepcopy(bundle['pinned_components']['modules'][original_revision])
    topology = deepcopy(assets['module_topologies'][selection['module_topology_revision_id']])
    definition = deepcopy(next(iter(assets['electrical_parameterization_definitions'].values())))
    selection = deepcopy(selection)
    if module_revision is not None:
        module['revision_id'] = module_revision
        topology['revision_id'] += suffix
        topology['module_definition_revision_id'] = module_revision
        definition['revision_id'] += suffix
        definition['module_definition_revision_id'] = module_revision
        definition['module_topology_revision_id'] = topology['revision_id']
        definition = finalize_parameterization_payload(definition)
    topology.update(verification_state='unverified', topology_provenance='inferred')
    evidence = assumed()
    evidence.update(evidence_id='b3b-evidence'+suffix,
        parameterization_id=definition['parameterization_id'],
        parameterization_revision_id=definition['revision_id'],
        module_definition_revision_id=module['revision_id'],
        module_topology_revision_id=topology['revision_id'],
        model_id=definition['model_id'], model_version=definition['model_version'],
        parameterization_payload_sha256=definition['parameterization_payload_sha256'],
        source_ids=['b3b-original'+suffix, 'b3b-retained'+suffix, 'b3b-assumption'+suffix])
    declaration = evidence['assumption_declaration']
    declaration['assumption_source_id'] = 'b3b-assumption'+suffix
    declaration['module_source'].update(component_id=module['module_definition_id'], revision_id=module['revision_id'])
    declaration['topology'].update(topology_id=topology['module_topology_id'],
        topology_revision_id=topology['revision_id'], topology_sha256=canonical_topology_asset_sha256(topology))
    declaration['parameterization'].update(parameterization_id=definition['parameterization_id'],
        parameterization_revision_id=definition['revision_id'],
        parameterization_sha256=definition['parameterization_payload_sha256'])
    seal(evidence)
    for key, digest, kind in (
        ('b3b-original'+suffix, declaration['module_source']['original_pan_sha256'], 'pan'),
        ('b3b-retained'+suffix, declaration['module_source']['retained_pan_sha256'], 'pan'),
        ('b3b-assumption'+suffix, declaration['digest_sha256'], 'manual_entry')):
        assets['sources'][key] = _source(key, digest, kind)
    assets['module_topologies'][topology['revision_id']] = topology
    assets['electrical_parameterization_definitions'][definition['revision_id']] = definition
    assets['electrical_parameterization_evidence'][evidence['evidence_id']] = evidence
    bundle['pinned_components']['modules'][module['revision_id']] = module
    selection.update(module_definition_revision_id=module['revision_id'],
        module_topology_revision_id=topology['revision_id'],
        region_parameterization_evidence_id=evidence['evidence_id'])
    _seal_selection(selection)
    bundle['electrical_shading_selections'][module['revision_id']] = selection
    VALIDATOR.validate(evidence)
    assert_numerical_assumption_evidence_structure(evidence)
    return module['revision_id']


def _witness_fixture(opt_in=True, second=False):
    _, config, _, bundle = _context()
    if opt_in is not None:
        _request(config)['scientific_options']['allow_synthetic_regions'] = opt_in
    revision = _add_assumed(bundle)
    if second:
        _add_assumed(bundle, revision+'-second', '-second')
    frozen = _raw_frozen(bundle)
    context = build_snapshot_witness_context(config, frozen)
    witness = build_detailed_snapshot_witness(context, revision)
    assets = bundle['pinned_electrical_shading_assets']
    evidence = assets['electrical_parameterization_evidence'][witness.evidence_id]
    payload = dict(module=bundle['pinned_components']['modules'][revision],
        topology=assets['module_topologies'][witness.topology_revision_id],
        parameterization=assets['electrical_parameterization_definitions'][witness.parameterization_revision_id],
        evidence=evidence, sources=assets['sources'])
    encoded = _bytes(payload)
    snapshot = DetailedModuleInputSnapshot(encoded, hashlib.sha256(encoded).hexdigest(), witness)
    return config, frozen, snapshot


@lru_cache(maxsize=1)
def _b2_candidate_template():
    from tests.unit.test_rb_post3d_08b2_region_physics import _candidate
    return _candidate()


def _add_b2_assumed(bundle, module_revision=None, suffix=''):
    """Real equal-series B2 physics; revision variants retain the same SDM."""
    from tests.unit.test_rb_post3d_08b2_region_physics import _seal
    module, topology, definition, evidence, sources = deepcopy(_b2_candidate_template())
    if module_revision is not None:
        module['revision_id'] = module_revision
        topology['revision_id'] += suffix
        topology['module_definition_revision_id'] = module_revision
        definition['revision_id'] += suffix
        definition['module_definition_revision_id'] = module_revision
        definition['module_topology_revision_id'] = topology['revision_id']
        evidence.update(evidence_id=evidence['evidence_id']+suffix,
            module_definition_revision_id=module_revision,
            module_topology_revision_id=topology['revision_id'],
            parameterization_revision_id=definition['revision_id'])
        declaration = evidence['assumption_declaration']
        declaration['module_source']['revision_id'] = module_revision
        declaration['topology']['topology_revision_id'] = topology['revision_id']
        declaration['parameterization']['parameterization_revision_id'] = definition['revision_id']
        _seal((module, topology, definition, evidence, sources))
        # Each declaration needs its own source record in the shared registry.
        assumption_id = 'b2-assumption'+suffix
        declaration['assumption_source_id'] = assumption_id
        for asset in (topology, definition, evidence):
            asset['source_ids'] = [assumption_id if x == 'b2-assumption' else x for x in asset['source_ids']]
        _seal((module, topology, definition, evidence, sources))
        source = sources.pop('b2-assumption')
        source.update(source_id=assumption_id, file_hash=declaration['digest_sha256'])
        sources[assumption_id] = source
    assets = bundle['pinned_electrical_shading_assets']
    assets['module_topologies'][topology['revision_id']] = topology
    assets['electrical_parameterization_definitions'][definition['revision_id']] = definition
    assets['electrical_parameterization_evidence'][evidence['evidence_id']] = evidence
    assets['sources'].update(sources)
    bundle['pinned_components']['modules'][module['revision_id']] = module
    selection = deepcopy(next(iter(bundle['electrical_shading_selections'].values())))
    selection.update(module_definition_revision_id=module['revision_id'],
        module_topology_revision_id=topology['revision_id'],
        region_parameterization_evidence_id=evidence['evidence_id'])
    _seal_selection(selection)
    bundle['electrical_shading_selections'][module['revision_id']] = selection
    return module['revision_id']


def _b2_witness_fixture(opt_in=True, second=False):
    _, config, _, bundle = _context()
    if opt_in is not None:
        _request(config)['scientific_options']['allow_synthetic_regions'] = opt_in
    revision = _add_b2_assumed(bundle)
    if second:
        _add_b2_assumed(bundle, revision+'-second', '-second')
    frozen = _raw_frozen(bundle)
    context = build_snapshot_witness_context(config, frozen)
    witness = build_detailed_snapshot_witness(context, revision)
    from engine.simulation.detailed_inputs import _selected_witness_bytes
    encoded = _selected_witness_bytes(context, revision)
    return config, frozen, DetailedModuleInputSnapshot(encoded, hashlib.sha256(encoded).hexdigest(), witness)


def test_legacy_constructor_replay_bytes_and_hash():
    inputs = _inputs()
    encoded = _bytes(inputs)
    digest = hashlib.sha256(encoded).hexdigest()
    snapshot = DetailedModuleInputSnapshot(encoded, digest)
    assert snapshot.witness is None
    assert snapshot.replay() == inputs
    assert snapshot == pin_detailed_module_inputs(**inputs)
    assert set(snapshot.replay()) == {'module', 'topology', 'parameterization', 'evidence', 'sources'}
    assert snapshot.canonical_payload == encoded
    assert snapshot.scientific_input_sha256 == digest


def test_exact_identity_bindings():
    config, frozen, snapshot = _witness_fixture()
    witness = snapshot.witness
    assert witness.context.configuration_sha256 == canonical_object_sha256(
        semantic_scientific_payload(scientific_configuration(config)))
    assert witness.context.frozen_selection is frozen
    assert witness.context.frozen_selection.payload_sha256 == hashlib.sha256(frozen.canonical_payload).hexdigest()
    payload = json.loads(snapshot.canonical_payload)
    assert witness.module_revision_id == payload['module']['revision_id']
    assert witness.topology_revision_id == payload['topology']['revision_id']
    assert witness.parameterization_revision_id == payload['parameterization']['revision_id']
    assert witness.evidence_sha256 == canonical_object_sha256(payload['evidence'])
    assert witness.assumption_sha256 == payload['evidence']['assumption_declaration']['digest_sha256']
    assert witness.consistency_sha256 == payload['evidence']['consistency_record']['digest_sha256']
    assert witness.module_input_sha256 == snapshot.scientific_input_sha256
    compare_snapshot_witness_context(witness, config, frozen)


@pytest.mark.parametrize('opt_in', [None, False, True])
def test_opt_in_and_self_consistent_external_witness_never_execute(opt_in):
    config, frozen, snapshot = _b2_witness_fixture(opt_in)
    assert snapshot.witness.effective_opt_in is (opt_in is True)
    reconstructed = AssumptionSnapshotWitness(**vars(snapshot.witness))
    compare_snapshot_witness_context(reconstructed, config, frozen)
    if opt_in is True:
        assert replace(snapshot, witness=reconstructed).replay() == json.loads(snapshot.canonical_payload)
        foreign = deepcopy(config)
        _request(foreign)['scientific_options']['allow_synthetic_regions'] = False
        with pytest.raises(SnapshotWitnessError, match='foreign configuration or selection'):
            compare_snapshot_witness_context(reconstructed, foreign, frozen)
    else:
        with pytest.raises(NumericalAssumptionInputError, match='requires scientific opt-in'):
            replace(snapshot, witness=reconstructed).replay()
    with pytest.raises(NumericalAssumptionInputError, match='authenticated execution is not enabled'):
        replace(snapshot, witness=None).replay()


@pytest.mark.parametrize('bad', [True, False, 1, {}, 'witness', object()])
def test_invalid_witness_types_rejected_on_replay(bad):
    _, _, snapshot = _witness_fixture()
    with pytest.raises(SnapshotWitnessError, match='witness type'):
        replace(snapshot, witness=bad).replay()


@pytest.mark.parametrize('field', ['module_revision_id', 'topology_revision_id',
    'parameterization_revision_id', 'evidence_id', 'evidence_sha256', 'assumption_sha256',
    'consistency_sha256', 'module_input_sha256', 'effective_opt_in'])
def test_revision_digest_membership_and_opt_in_substitution(field):
    _, _, snapshot = _witness_fixture()
    value = False if field == 'effective_opt_in' else 'foreign'
    with pytest.raises(SnapshotWitnessError, match='snapshot witness'):
        replace(snapshot, witness=replace(snapshot.witness, **{field: value})).replay()


@pytest.mark.parametrize('mutation', ['configuration_hash', 'configuration_bytes',
    'selection_hash', 'selection_bytes', 'context_type', 'integer_opt_in'])
def test_structural_context_corruption(mutation):
    _, _, snapshot = _witness_fixture()
    witness = snapshot.witness
    context = witness.context
    if mutation == 'configuration_hash': context = replace(context, configuration_sha256='0'*64)
    elif mutation == 'configuration_bytes': context = replace(context, canonical_configuration=b'[]')
    elif mutation == 'selection_hash':
        context = replace(context, frozen_selection=replace(context.frozen_selection, scientific_input_sha256='0'*64))
    elif mutation == 'selection_bytes':
        context = replace(context, frozen_selection=replace(context.frozen_selection, canonical_payload=b'{}'))
    elif mutation == 'context_type': context = True
    elif mutation == 'integer_opt_in': witness = replace(witness, effective_opt_in=1)
    with pytest.raises(SnapshotWitnessError, match='snapshot witness'):
        replace(snapshot, witness=replace(witness, context=context)).replay()


@pytest.mark.parametrize('foreign', ['configuration', 'selection'])
def test_foreign_self_consistent_context_rejected(foreign):
    config, frozen, snapshot = _witness_fixture()
    if foreign == 'configuration':
        config = deepcopy(config)
        _request(config)['scientific_options']['allow_synthetic_regions'] = False
    else:
        payload = json.loads(frozen.canonical_payload)
        payload['pinned_electrical_shading_assets']['sources']['b3b-original']['title'] += ' changed'
        frozen = _raw_frozen(payload)
    context = build_snapshot_witness_context(config, frozen)
    other = build_detailed_snapshot_witness(context, snapshot.witness.module_revision_id)
    original_config, original_frozen, _ = _witness_fixture()
    with pytest.raises(SnapshotWitnessError, match='foreign configuration or selection'):
        compare_snapshot_witness_context(other, original_config, original_frozen)


def test_shared_bytes_across_distinct_module_snapshots_and_foreign_membership():
    _, _, snapshot = _b2_witness_fixture(second=True)
    first = snapshot.witness
    second = build_detailed_snapshot_witness(first.context, first.module_revision_id+'-second')
    bundle = json.loads(first.context.frozen_selection.canonical_payload)
    assets = bundle['pinned_electrical_shading_assets']
    second_payload = dict(module=bundle['pinned_components']['modules'][second.module_revision_id],
        topology=assets['module_topologies'][second.topology_revision_id],
        parameterization=assets['electrical_parameterization_definitions'][second.parameterization_revision_id],
        evidence=assets['electrical_parameterization_evidence'][second.evidence_id], sources=assets['sources'])
    encoded = _bytes(second_payload)
    second_snapshot = DetailedModuleInputSnapshot(encoded, hashlib.sha256(encoded).hexdigest(), second)
    assert snapshot.witness.context is second_snapshot.witness.context
    assert snapshot.witness.context.canonical_configuration is second_snapshot.witness.context.canonical_configuration
    assert snapshot.witness.context.frozen_selection.canonical_payload is second_snapshot.witness.context.frozen_selection.canonical_payload
    assert second_snapshot.replay() == second_payload
    with pytest.raises(NumericalAssumptionInputError, match='authenticated execution is not enabled'):
        replace(second_snapshot, witness=None).replay()
    assert first.module_revision_id != second.module_revision_id
    with pytest.raises(SnapshotWitnessError, match='module payload membership'):
        replace(snapshot, witness=second).replay()


@pytest.mark.parametrize('malformed', ['string', 'list_id', 'missing'])
@pytest.mark.parametrize('policy', ['fail_closed', 'explicit_lower_fidelity'])
def test_malformed_persisted_selection_public_boundaries(tmp_path, malformed, policy):
    project, config, store, bundle = _context(policy)
    revision, selection = next(iter(bundle['electrical_shading_selections'].items()))
    if malformed == 'string': bundle['electrical_shading_selections'][revision] = 'bad'
    elif malformed == 'list_id':
        selection['region_parameterization_evidence_id'] = ['bad']
        _seal_selection(selection)
    else: del selection['state_version']
    with pytest.raises(ValueError, match='selection|parameterization evidence'):
        freeze_detailed_selection(bundle)
    frozen = _raw_frozen(bundle)
    with pytest.raises(ValueError, match='selection|parameterization evidence'):
        frozen.replay()
    result = _run(tmp_path, project, config, replace(store, detailed_electrical_inputs=frozen))
    identity = result.simulation_run['detailed_execution_identity']
    assert identity['runtime_support_result'] == 'blocked'
    assert identity['resolved_fidelity'] is None
    assert not identity['fallback_applied']


@pytest.mark.parametrize('policy', ['fail_closed', 'explicit_lower_fidelity'])
@pytest.mark.parametrize('quality', [False, True])
def test_schema_valid_selected_v02_dispatch_denied_without_downgrade(tmp_path, policy, quality):
    project, config, store, bundle = _context(policy)
    _request(config)['scientific_options']['allow_synthetic_regions'] = (policy == 'explicit_lower_fidelity')
    revision = _add_b2_assumed(bundle)
    selection = bundle['electrical_shading_selections'][revision]
    evidence = bundle['pinned_electrical_shading_assets']['electrical_parameterization_evidence'][
        selection['region_parameterization_evidence_id']]
    VALIDATOR.validate(evidence)
    if quality:
        evidence['module_quality_declaration'] = {'source_ids': ['missing']}
    result = _run(tmp_path, project, config, replace(store, detailed_electrical_inputs=_raw_frozen(bundle)))
    identity = result.simulation_run['detailed_execution_identity']
    assert identity['runtime_support_result'] == 'blocked'
    assert identity['resolved_fidelity'] is None
    assert not identity['fallback_applied']
    assert 'NUMERICAL_ASSUMPTION_EXECUTION_DENIED' in str(identity['failure_reasons'])
    if not quality:
        diagnostic = 'require fail_closed policy' if policy == 'explicit_lower_fidelity' else 'requires scientific opt-in'
        assert diagnostic in str(identity['failure_reasons'])


def test_selection_integrity_diagnostic_precedes_numerical_denial():
    _, _, _, bundle = _context()
    revision = _add_assumed(bundle)
    bundle['electrical_shading_selections'][revision]['selection_payload_sha256'] = '0'*64
    with pytest.raises(ValueError, match='selection identity hash mismatch'):
        _raw_frozen(bundle).replay()


def test_unselected_v02_allows_legacy_level_zero(tmp_path):
    project, config, store, bundle = _context()
    unused = assumed()
    bundle['pinned_electrical_shading_assets']['electrical_parameterization_evidence'][unused['evidence_id']] = unused
    frozen = freeze_detailed_selection(bundle)
    _request(config)['requested_fidelity'] = 'level_0_geometric_only'
    result = _run(tmp_path, project, config, replace(store, detailed_electrical_inputs=frozen))
    assert result.simulation_run['detailed_execution_identity']['runtime_support_result'] == 'geometry_only'


def test_legacy_fallback_preserved(tmp_path):
    project, config, store, _ = _context('explicit_lower_fidelity')
    _request(config)['scientific_options']['allow_synthetic_regions'] = True
    config['numerical_options']['losses']['module_mismatch_loss_fraction'] = 0.01
    result = _run(tmp_path, project, config, store)
    identity = result.simulation_run['detailed_execution_identity']
    assert identity['runtime_support_result'] == 'fallback_to_geometry_only'
    assert identity['fallback_applied']


def test_no_level_two_or_three_readiness():
    from components.topology_library import resolve_library_electrical_shading_capability
    _, _, snapshot = _witness_fixture()
    payload = json.loads(snapshot.canonical_payload)
    result = validate_parameterization_for_electrical_shading(payload['evidence'],
        expected_scope='region_substring', module_definition=payload['module'], topology_definition=payload['topology'])
    assert not result.ready
    capability = resolve_library_electrical_shading_capability(payload['module'],
        topology_definition=payload['topology'], region_parameterization_evidence=payload['evidence'],
        source_records=payload['sources'])
    assert capability['topology_trusted'] is False
    assert 'level_2_bypass_substring' not in capability['available_fidelity_levels']
    assert 'level_3_cell_submodule_iv' not in capability['available_fidelity_levels']


def test_execution_option_does_not_authorize_or_change_scientific_identity():
    config, frozen, snapshot = _witness_fixture(None)
    _request(config)['execution_options']['allow_synthetic_regions'] = True
    context = build_snapshot_witness_context(config, frozen)
    assert context.configuration_sha256 == snapshot.witness.context.configuration_sha256
    assert build_detailed_snapshot_witness(context, snapshot.witness.module_revision_id).effective_opt_in is False


@pytest.mark.parametrize('bad', [1, 'true', None, [], {}])
def test_witness_construction_validates_strict_scientific_option(bad):
    config, frozen, _ = _witness_fixture()
    _request(config)['scientific_options']['allow_synthetic_regions'] = bad
    with pytest.raises(SnapshotWitnessError, match='explicit boolean'):
        build_snapshot_witness_context(config, frozen)


def test_rehashed_configuration_cannot_override_retained_effective_opt_in():
    _, _, snapshot = _witness_fixture()
    context = snapshot.witness.context
    configuration = json.loads(context.canonical_configuration)
    _request(configuration)['scientific_options']['allow_synthetic_regions'] = False
    encoded = _bytes(configuration)
    forged_context = replace(context, canonical_configuration=encoded,
        configuration_sha256=hashlib.sha256(encoded).hexdigest())
    with pytest.raises(SnapshotWitnessError, match='membership or digest mismatch'):
        replace(snapshot, witness=replace(snapshot.witness, context=forged_context)).replay()


def test_legacy_snapshot_rejects_foreign_numerical_witness():
    _, _, snapshot = _witness_fixture()
    legacy = pin_detailed_module_inputs(**_inputs())
    with pytest.raises(SnapshotWitnessError, match='module payload membership'):
        replace(legacy, witness=snapshot.witness).replay()


def test_attached_witness_outer_hash_error_is_not_fallback_eligible():
    _, _, snapshot = _witness_fixture()
    with pytest.raises(SnapshotWitnessError, match='snapshot hash mismatch'):
        replace(snapshot, scientific_input_sha256='0'*64).replay()
