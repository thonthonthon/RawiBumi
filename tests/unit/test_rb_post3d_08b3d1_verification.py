"""Independent input-only verification, with actual small B2 numerical fixtures."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from engine.simulation.artifacts import canonical_object_sha256
from engine.simulation.detailed_dispatch import (
    LIMITATIONS, derive_assumption_limitations, scientific_configuration, verify_detailed_context,
)
from engine.simulation.detailed_inputs import (
    DETAILED_SCOPE, DetailedInputError, SnapshotWitnessError, freeze_detailed_selection,
    pin_detailed_module_inputs, semantic_scientific_payload,
)
from shading.electrical.contract import ElectricalShadingContractError, NumericalAssumptionInputError
from shading.electrical.parameterization import ElectricalParameterizationError
from tests.unit.test_rb_post3d_08b2_region_physics import _candidate, _seal
from tests.unit.test_rb_post3d_08b3b_snapshot_witness import _raw_frozen, _seal_selection
from tests.unit.test_phase69a_canonical_dispatch import _context


def _rehash(context, bundle=None):
    if bundle is not None:
        snapshot = _raw_frozen(bundle)
        payload = json.loads(snapshot.canonical_payload)
        context['selection_snapshot'] = dict(payload=payload,
            payload_sha256=snapshot.payload_sha256, scientific_input_sha256=snapshot.scientific_input_sha256)
        context['inputs']['frozen_selection'] = semantic_scientific_payload(payload)
    context['input_hashes'] = {k: canonical_object_sha256(semantic_scientific_payload(v))
                               for k, v in context['inputs'].items()}
    identity = context['identity']
    identity['scientific_input_sha256'] = canonical_object_sha256(context['input_hashes'])
    identity.pop('execution_identity_sha256', None)
    identity['execution_identity_sha256'] = canonical_object_sha256(identity)
    return context


@pytest.fixture(scope='module')
def real_candidate():
    return _candidate()


def _fixture(candidate):
    _, config, _, bundle = _context()
    module, topology, definition, evidence, sources = deepcopy(candidate)
    revision = module['revision_id']
    bundle['pinned_components']['modules'] = {revision: module}
    bundle['pinned_electrical_shading_assets'].update(
        module_topologies={topology['revision_id']: topology},
        electrical_parameterization_definitions={definition['revision_id']: definition},
        electrical_parameterization_evidence={evidence['evidence_id']: evidence}, sources=sources)
    selection = bundle['electrical_shading_selections'][revision]
    selection.update(module_topology_revision_id=topology['revision_id'],
                     region_parameterization_evidence_id=evidence['evidence_id'])
    _seal_selection(selection)
    config['shading_configuration']['electrical_shading_configuration']['scientific_options']['allow_synthetic_regions'] = True
    scene = {'module_instances': [dict(enabled=True, module_instance_id='M', module_definition_revision_id=revision)]}
    payload = dict(module=module, topology=topology, parameterization=definition, evidence=evidence, sources=sources)
    fields = ('project_revision', 'electrical_design', 'weather_dataset', 'component_revisions')
    inputs = {k: {} for k in fields}
    inputs['component_revisions'] = {revision: deepcopy(module)}
    inputs.update(simulation_configuration=scientific_configuration(config), scene=scene,
                  weather_series_logical_sha256='a'*64, engine_version='input-only-test', frozen_selection=None)
    identity = dict(schema_name='DetailedExecutionIdentity', schema_version='0.1',
        requested_fidelity='level_2_bypass_substring', resolved_fidelity='level_2_bypass_substring',
        fallback_policy='fail_closed', fallback_applied=False, fallback_reason=None,
        failure_reasons=[], runtime_support_result='backend_not_connected', execution_scope=DETAILED_SCOPE,
        limitations=derive_assumption_limitations({revision: payload}, scene), numerical_result_sha256=None)
    context = dict(schema_name='DetailedExecutionContext', schema_version='0.1', inputs=inputs, identity=identity)
    return _rehash(context, bundle), bundle


def test_valid_current_verifier_recomputes(real_candidate, monkeypatch):
    import shading.electrical.parameterization as physics
    context, _ = _fixture(real_candidate)
    original = physics._evaluate_numerical_candidate_physics
    calls = []
    def real(*args):
        calls.append(args)
        return original(*args)
    def forbidden(*args):
        raise AssertionError('producer cache used')
    monkeypatch.setattr(physics, '_evaluate_numerical_candidate_physics', real)
    monkeypatch.setattr(physics, '_cached_numerical_candidate', forbidden)
    verify_detailed_context(context)
    assert len(calls) == 1


@pytest.mark.parametrize('value,error,message', [
    (None, NumericalAssumptionInputError, 'scientific opt-in'),
    (False, NumericalAssumptionInputError, 'scientific opt-in'),
    ('true', SnapshotWitnessError, 'must be an explicit boolean'),
    (1, SnapshotWitnessError, 'must be an explicit boolean'),
])
def test_scientific_opt_in_required(real_candidate, value, error, message):
    context, _ = _fixture(real_candidate)
    options = context['inputs']['simulation_configuration']['shading_configuration']['electrical_shading_configuration']['scientific_options']
    if value is None:
        options.pop('allow_synthetic_regions')
    else:
        options['allow_synthetic_regions'] = value
    with pytest.raises(error, match=message) as excinfo:
        verify_detailed_context(_rehash(context))
    # Dispatch permits availability fallback only for DetailedInputError.
    assert not isinstance(excinfo.value, DetailedInputError)


@pytest.mark.parametrize('where', ['configuration', 'selection', 'identity'])
def test_fail_closed_required(real_candidate, where):
    context, bundle = _fixture(real_candidate)
    if where == 'configuration':
        context['inputs']['simulation_configuration']['shading_configuration']['electrical_shading_configuration']['fallback_policy'] = 'explicit_lower_fidelity'
    elif where == 'identity':
        context['identity']['fallback_policy'] = 'explicit_lower_fidelity'
    else:
        selection = next(iter(bundle['electrical_shading_selections'].values()))
        selection['fallback_policy'] = 'explicit_lower_fidelity'
        _seal_selection(selection)
    error = DetailedInputError if where == "identity" else NumericalAssumptionInputError
    with pytest.raises(error, match="fail_closed policy"):
        verify_detailed_context(_rehash(context, bundle))


@pytest.mark.parametrize('fault', ['declaration', 'missing_source',
    'pan_digest', 'topology_revision', 'parameterization_revision'])
def test_rehashed_scientific_tampering(real_candidate, fault):
    candidate = deepcopy(real_candidate)
    if fault == 'declaration':
        candidate[3]['assumption_declaration']['rationale'] += ' changed'
    elif fault == 'missing_source':
        del candidate[4]['b2-assumption']
    elif fault == 'pan_digest':
        candidate[4]['b2-retained']['file_hash'] = 'f'*64
    elif fault == 'topology_revision':
        candidate[1]['revision_id'] += '-foreign'
    else:
        candidate[2]['revision_id'] += '-foreign'
    context, _ = _fixture(candidate)
    errors = {
        "declaration": (ElectricalShadingContractError, "assumption_declaration digest mismatch"),
        "missing_source": (ValueError, r"unpinned SourceRecord ids.*b2-assumption"),
        "pan_digest": (ValueError, "two distinct resolved SourceRecords"),
        "topology_revision": (ValueError, "stale topology revision binding"),
        "parameterization_revision": (SnapshotWitnessError, "selected parameterization revision mismatch"),
    }
    error, message = errors[fault]
    with pytest.raises(error, match=message):
        verify_detailed_context(context)


@pytest.mark.parametrize('fault', ['missing', 'reordered', 'foreign'])
def test_rehashed_limitations_rejected(real_candidate, fault):
    context, _ = _fixture(real_candidate)
    values = context['identity']['limitations']
    if fault == 'missing':
        values.pop()
    elif fault == 'reordered':
        values[-1], values[-2] = values[-2], values[-1]
    else:
        values[-1] = 'Foreign revision disclosure.'
    with pytest.raises(ValueError, match='limitations'):
        verify_detailed_context(_rehash(context))


def test_distinct_revision_slices_are_not_deduplicated(real_candidate):
    payload = {'evidence': real_candidate[3]}
    scene = {'module_instances': [dict(enabled=True, module_definition_revision_id=r) for r in ('b', 'a', 'a')]}
    expected = list(real_candidate[3]['assumption_declaration']['scientific_limitations'])
    assert derive_assumption_limitations({'b': payload, 'a': payload}, scene) == LIMITATIONS + expected + expected


def test_physics_unavailable_fails_closed(real_candidate, monkeypatch):
    def unavailable(*args):
        raise RuntimeError('kernel unavailable')
    monkeypatch.setattr('shading.electrical.parameterization._evaluate_numerical_candidate_physics', unavailable)
    context, _ = _fixture(real_candidate)
    with pytest.raises(NumericalAssumptionInputError, match='kernel unavailable'):
        verify_detailed_context(context)


@pytest.mark.parametrize('fault', ['missing_snapshot', 'foreign_snapshot', 'dark_missing_source'])
def test_snapshot_and_dark_integrity(real_candidate, fault):
    context, bundle = _fixture(real_candidate)
    if fault == 'missing_snapshot':
        context['selection_snapshot'] = None
    elif fault == 'foreign_snapshot':
        foreign = deepcopy(bundle)
        foreign['pinned_electrical_shading_assets']['sources']['b2-retained']['title'] = 'Foreign context'
        other = deepcopy(context)
        _rehash(other, foreign)
        context['selection_snapshot'] = other['selection_snapshot']
    else:
        # No irradiance/interval availability participates in input authority.
        context['inputs']['scene']['module_instances'] = []
        del bundle['pinned_electrical_shading_assets']['sources']['b2-assumption']
        _rehash(context, bundle)
    errors = {
        "missing_snapshot": (NumericalAssumptionInputError, "EXECUTION_DENIED"),
        "foreign_snapshot": (DetailedInputError, "selection does not match scientific inputs"),
        "dark_missing_source": (ValueError, r"unpinned SourceRecord ids.*b2-assumption"),
    }
    error, message = errors[fault]
    with pytest.raises(error, match=message):
        verify_detailed_context(context)


def test_execution_stays_disabled(real_candidate):
    context, bundle = _fixture(real_candidate)
    verify_detailed_context(context)
    module, topology, definition, evidence, sources = real_candidate
    with pytest.raises(NumericalAssumptionInputError, match='EXECUTION_DENIED'):
        pin_detailed_module_inputs(module=module, topology=topology, parameterization=definition,
                                  evidence=evidence, sources=sources)
    frozen = freeze_detailed_selection(bundle)
    assert frozen.replay() == _raw_frozen(bundle).replay()
    from engine.simulation.detailed_inputs import authorize_selected_assumptions
    configuration = deepcopy(context['inputs']['simulation_configuration'])
    configuration['shading_configuration']['electrical_shading_configuration']['execution_options'] = {}
    configuration['shading_configuration']['electrical_shading_configuration']['scientific_options']['allow_synthetic_regions'] = False
    with pytest.raises(NumericalAssumptionInputError, match='requires scientific opt-in'):
        authorize_selected_assumptions(configuration, frozen)


def test_foreign_attribution_cannot_replace_integrity_failure(real_candidate):
    from engine.simulation.detailed_attribution import verify_attribution_sources
    context, _ = _fixture(real_candidate)
    source = SimpleNamespace(replay_stream=lambda: dict(scientific_input_sha256='f'*64,
        source_numerical_result_sha256=None, source_electrical_design_sha256='f'*64))
    with pytest.raises(ValueError, match='source identity'):
        verify_attribution_sources(source, context)


# Reuse unchanged repository entry-point regressions, including real persisted
# v0.1 package verification and historical abbreviated dark attribution.
from tests.unit.test_rb_post3d_08b3c_context_propagation import (
    test_abbreviated_dark_completed_pass_stays_in_parent,
    test_legacy_fallback,
)
from tests.unit.test_phase69a_canonical_dispatch import (
    test_workspace_freezes_into_store_and_detailed_run_identity,
    test_increment2_scaffolding_context_remains_verifiable,
)
from tests.unit.test_rb_post3d_08b1_evidence_foundation import (
    test_assumptions_cannot_execute_or_grant_detailed_capability,
)


def test_package_entry_rejects_rehashed_semantic_tampering(real_candidate, tmp_path):
    import hashlib
    import json
    from engine.simulation.artifacts import verify_run_package
    context, _ = _fixture(real_candidate)
    context['identity']['limitations'].pop()
    _rehash(context)
    encoded = json.dumps(context).encode()
    (tmp_path / 'detailed-execution-context.json').write_bytes(encoded)
    manifest = dict(package_state='complete', artifact_count=1, artifacts=[dict(
        relative_path='detailed-execution-context.json', sha256=hashlib.sha256(encoded).hexdigest(),
        byte_size=len(encoded))])
    manifest['manifest_payload_sha256'] = canonical_object_sha256(manifest)
    (tmp_path / 'run-package-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='limitations'):
        verify_run_package(tmp_path)


@pytest.mark.parametrize('field', ['assumption_id', 'assumption_revision_id'])
def test_missing_assumption_identity_rejected(real_candidate, field):
    context, bundle = _fixture(real_candidate)
    evidence = next(iter(bundle['pinned_electrical_shading_assets']['electrical_parameterization_evidence'].values()))
    del evidence['assumption_declaration'][field]
    with pytest.raises(ElectricalShadingContractError, match=f"{field}.*required property"):
        verify_detailed_context(_rehash(context, bundle))


def test_foreign_attribution_module_fingerprint(real_candidate):
    from engine.simulation.detailed_attribution import verify_attribution_sources
    context, _ = _fixture(real_candidate)
    context['inputs']['detailed_numerical_policy'] = {'string_sample_count': 201}
    _rehash(context)
    payload = dict(scientific_input_sha256=context['identity']['scientific_input_sha256'],
        source_numerical_result_sha256=None,
        source_electrical_design_sha256=canonical_object_sha256(context['inputs']['electrical_design']),
        source_module_input_hashes={'M': 'f'*64}, region_solvers={'M': 'lambertw'})
    with pytest.raises(ValueError, match='module/solver binding'):
        verify_attribution_sources(SimpleNamespace(replay_stream=lambda: payload), context)


@pytest.mark.parametrize('fault', ['missing', 'foreign'])
def test_component_revision_binding(real_candidate, fault):
    context, _ = _fixture(real_candidate)
    revisions = context['inputs']['component_revisions']
    if fault == 'missing':
        revisions.clear()
    else:
        next(iter(revisions.values()))['manufacturer'] = 'Foreign'
    with pytest.raises(DetailedInputError, match='canonical component revision'):
        verify_detailed_context(_rehash(context))


@pytest.mark.parametrize('field,value', [
    ('requested_fidelity', 'level_0_geometric_only'),
    ('resolved_fidelity', 'level_0_geometric_only'),
    ('fallback_applied', True), ('fallback_reason', 'foreign fallback'),
])
def test_assumption_identity_requires_level_two_without_fallback(real_candidate, field, value):
    context, _ = _fixture(real_candidate)
    context['identity'][field] = value
    with pytest.raises(DetailedInputError, match='Level-2 fidelity without fallback'):
        verify_detailed_context(_rehash(context))


@pytest.mark.parametrize('change', ['voltage', 'status'])
def test_resealed_record_reaches_real_kernel_comparison(real_candidate, change):
    candidate = deepcopy(real_candidate)
    record = candidate[3]['consistency_record']
    if change == 'voltage':
        sample = record['cases'][0]['samples'][0]
        sample['module_voltage_v'] += 0.001
        sample['assembled_voltage_v'] += 0.001
        sample['residual_v'] = sample['assembled_voltage_v'] - sample['module_voltage_v']
        record['max_abs_residual_v'] = max(abs(s['residual_v'])
            for case in record['cases'] for s in case['samples'])
    else:
        record['passed'] = False
    _seal(candidate)
    context, _ = _fixture(candidate)
    with pytest.raises(NumericalAssumptionInputError, match='real-kernel recomputation'):
        verify_detailed_context(context)


def test_same_id_foreign_definition_revision_rejected(real_candidate):
    context, bundle = _fixture(real_candidate)
    definitions = bundle['pinned_electrical_shading_assets']['electrical_parameterization_definitions']
    definition = deepcopy(definitions.pop(real_candidate[2]['revision_id']))
    definition['revision_id'] += '-foreign'
    # Keep the parameterization ID identical, with a consistent registry key.
    definitions[definition['revision_id']] = definition
    with pytest.raises(SnapshotWitnessError, match='selected parameterization revision mismatch'):
        verify_detailed_context(_rehash(context, bundle))


def test_same_id_foreign_definition_payload_rejected(real_candidate):
    context, bundle = _fixture(real_candidate)
    definitions = bundle['pinned_electrical_shading_assets']['electrical_parameterization_definitions']
    revision = real_candidate[2]['revision_id']
    foreign = deepcopy(definitions[revision])
    foreign['revision_id'] += '-foreign'
    definitions[foreign['revision_id']] = foreign
    # Both revisions remain resolvable. A foreign payload under the selected
    # exact key cannot be accepted merely because its parameterization ID agrees.
    definitions[revision] = deepcopy(foreign)
    with pytest.raises(ElectricalParameterizationError, match='parameterization payload hash mismatch'):
        verify_detailed_context(_rehash(context, bundle))


def test_snapshot_requires_context_verification_even_without_schema_name(real_candidate):
    from engine.simulation.detailed_attribution import verify_attribution_sources
    context, _ = _fixture(real_candidate)
    context.pop('schema_name')
    context['inputs']['frozen_selection'] = None
    with pytest.raises(DetailedInputError, match='unsupported detailed execution context'):
        verify_attribution_sources(SimpleNamespace(), context)


def test_mixed_bundle_keeps_definition_registry_checks(real_candidate):
    context, bundle = _fixture(real_candidate)
    definitions = bundle['pinned_electrical_shading_assets']['electrical_parameterization_definitions']
    foreign = deepcopy(real_candidate[2])
    foreign['revision_id'] = 'unused-foreign-revision'
    definitions['wrong-registry-key'] = foreign
    with pytest.raises(DetailedInputError, match='registry key does not match revision_id'):
        verify_detailed_context(_rehash(context, bundle))
