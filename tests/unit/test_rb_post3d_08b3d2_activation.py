"""Controlled activation: real canonical execution and independent verification.

Positive paths never replace an electrical kernel or manufacture a run package.
Timing is emitted for the orchestrator, not asserted as a resource target.
"""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import math
import shutil
from time import perf_counter

import pandas as pd
import pytest

from engine.simulation.artifacts import verify_run_package, _build_run_package_manifest
from engine.simulation.detailed_dispatch import (
    _prepare_backend, _resolve, derive_assumption_limitations, verify_detailed_context,
)
from engine.simulation.detailed_inputs import (
    DetailedModuleInputSnapshot, DetailedInputError, SnapshotWitnessError, _bytes, _selected_witness_payload,
    authorize_selected_assumptions, build_snapshot_witness_context,
    build_detailed_snapshot_witness, freeze_detailed_selection,
    pin_detailed_module_inputs, prepare_execution_transport, validate_execution_transport,
    validate_regional_transport,
)
from shading.electrical.contract import (
    ElectricalShadingContractError, NumericalAssumptionInputError, deny_numerical_assumption_execution,
)
from tests.unit.test_rb_post3d_08b2_region_physics import _candidate, _seal
from tests.unit.test_rb_post3d_08b3b_snapshot_witness import _raw_frozen, _seal_selection
from tests.unit.test_rb_post3d_08b3d1_verification import _rehash
from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
from tests.unit.test_phase69a_canonical_dispatch import _run



@pytest.fixture(scope='module')
def candidate():
    return _candidate()


def _fixture(candidate, *, validate_selection=True):
    project, config, store, scene, design = _canonical_fixture()
    module, topology, definition, evidence, sources = deepcopy(candidate)
    revision = module['revision_id']
    bundle = store.detailed_electrical_inputs.replay()
    bundle['pinned_components']['modules'] = {revision: module}
    bundle['pinned_electrical_shading_assets'].update(
        module_topologies={topology['revision_id']: topology},
        electrical_parameterization_definitions={definition['revision_id']: definition},
        electrical_parameterization_evidence={evidence['evidence_id']: evidence}, sources=sources)
    selection = bundle['electrical_shading_selections'][revision]
    selection.update(module_topology_revision_id=topology['revision_id'],
        region_parameterization_evidence_id=evidence['evidence_id'])
    _seal_selection(selection)
    # One module, three equivalent regions, one string/MPPT, one diffuse interval.
    scene['module_instances'] = scene['module_instances'][:1]
    instance = scene['module_instances'][0]
    scene['pv_fields'][0]['generated_module_instance_ids'] = [instance['module_instance_id']]
    scene['pv_fields'][0]['modules_per_row'] = 1
    scene['pv_fields'][0]['module_footprint'].update(
        physical_width_m=module['mechanical']['width_m'], physical_height_m=module['mechanical']['height_m'],
        packed_width_m=module['mechanical']['width_m'], packed_height_m=module['mechanical']['height_m'])
    design['strings'] = design['strings'][:1]
    design['strings'][0]['module_instance_ids'] = [instance['module_instance_id']]
    design['mppt_instances'][0]['connected_string_ids'] = [design['strings'][0]['string_id']]
    config['shading_configuration']['electrical_shading_configuration']['scientific_options']['allow_synthetic_regions'] = True
    config['output_configuration']['detailed_diagnostics'] = False
    config.setdefault('numerical_options', {}).setdefault('module_overrides', {})['module_quality_loss_fraction'] = 0.
    components = deepcopy(dict(store.component_revisions))
    components[revision] = module
    weather = next(iter(store.weather_revisions.values())).copy()
    weather.series = weather.series.iloc[:1].copy()
    weather.dataset['start_time'] = weather.series.index[0].isoformat()
    weather.dataset['end_time'] = (weather.series.index[-1] + pd.Timedelta(hours=1)).isoformat()
    store = replace(store, scene_revisions={scene['revision_id']: scene},
        electrical_revisions={design['electrical_revision_id']: design}, component_revisions=components,
        weather_revisions={weather.dataset['revision_id']: weather},
        detailed_electrical_inputs=(freeze_detailed_selection(bundle) if validate_selection else _raw_frozen(bundle)))
    return project, config, store, scene, design, bundle


def _pin(config, store):
    witnesses, payloads = authorize_selected_assumptions(config, store.detailed_electrical_inputs)
    revision = next(iter(payloads))
    return pin_detailed_module_inputs(**payloads[revision], authorization_witness=witnesses[revision])


@pytest.fixture(scope='module')
def completed(tmp_path_factory, candidate):
    fixture = _fixture(candidate)
    project, config, store, scene, design, _ = fixture
    start = perf_counter()
    from engine.simulation import detailed_backend as backend
    original = backend.build_phase66_series_module_operating_model
    calls = []
    from engine.simulation import detailed_inputs as input_boundary
    from shading.electrical import parameterization as physics
    counts = {'witness_revalidations': 0, 'producer_b2_requests': 0,
              'verifier_fresh_b2_requests': 0, 'full_physics_evaluations': 0}
    original_authority = input_boundary.validate_assumption_authorization_witness
    original_acceptance = physics.validate_numerical_assumption_acceptance
    original_physics = physics._evaluate_numerical_candidate_physics
    def authority(*args, **kwargs):
        counts['witness_revalidations'] += 1
        return original_authority(*args, **kwargs)
    def acceptance(*args, **kwargs):
        counts['verifier_fresh_b2_requests' if kwargs.get('use_cache') is False else 'producer_b2_requests'] += 1
        return original_acceptance(*args, **kwargs)
    def evaluate(*args, **kwargs):
        counts['full_physics_evaluations'] += 1
        return original_physics(*args, **kwargs)
    def real(*args, **kwargs):
        calls.append((args[0]['revision_id'], kwargs.get('authorization_witness')))
        return original(*args, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(backend, 'build_phase66_series_module_operating_model', real)
        patch.setattr(input_boundary, 'validate_assumption_authorization_witness', authority)
        patch.setattr(physics, 'validate_numerical_assumption_acceptance', acceptance)
        patch.setattr(physics, '_evaluate_numerical_candidate_physics', evaluate)
        input_boundary._validated_producer_physics.cache_clear()
        physics._cached_numerical_candidate.cache_clear()
        result = _run(tmp_path_factory.mktemp('b3d2'), project, config, store, name='b3d2')
        run_counts = dict(counts)
        verify_run_package(result.artifact_directory)
        verification_counts = {key: counts[key] - run_counts[key] for key in counts}
        print({'one_interval_run_validation_counts': run_counts,
               'independent_package_validation_counts': verification_counts})
    assert calls and all(witness is not None for _, witness in calls)
    assert result.summary_result is not None, result.simulation_run
    assert result.detailed_backend_result is not None
    assert result.detailed_attribution_result is not None
    print({'b3d2_one_module_three_regions_one_interval_seconds': perf_counter() - start})
    return fixture, result


def test_actual_level_two_solver_attribution_and_persisted_package(completed):
    (project, config, store, scene, design, _), result = completed
    args = _prepare_backend(config, store, scene, design, [], 'binding', project['project_revision_id'], '2026-10-12T00:00:00Z')
    physical = result.detailed_backend_result.replay()
    assert len(physical['intervals']) == 1
    mppt = physical['intervals'][0]['mppts'][0]
    assert math.isfinite(mppt['selected_operating_point']['power_w'])
    context = json.loads((result.artifact_directory / 'detailed-execution-context.json').read_text())
    revision = scene['module_instances'][0]['module_definition_revision_id']
    frozen = store.detailed_electrical_inputs._replay_structure()
    payload = _selected_witness_payload(frozen, revision)
    assert context['identity']['limitations'] == derive_assumption_limitations({revision: payload}, scene)
    actual = result.detailed_attribution_result.replay()
    module_id = scene['module_instances'][0]['module_instance_id']
    assert actual['source_module_input_hashes'][module_id] == sha256(_bytes(payload)).hexdigest()
    assert args['module_inputs'][module_id].witness is not None
    verify_run_package(result.artifact_directory)


@pytest.mark.parametrize('value', [False, None, 'true', 1, 0, [], {}])
def test_strict_opt_in_required(candidate, value):
    _, config, store, scene, design, _ = _fixture(candidate)
    options = config['shading_configuration']['electrical_shading_configuration']['scientific_options']
    if value is None:
        options.pop('allow_synthetic_regions')
    else:
        options['allow_synthetic_regions'] = value
    error = NumericalAssumptionInputError if value is False or value is None else SnapshotWitnessError
    diagnostic = 'requires scientific opt-in' if value is False or value is None else 'explicit boolean'
    with pytest.raises(error, match=diagnostic):
        _resolve(config, store, scene, design)


def test_execution_options_never_authorize(candidate):
    _, config, store, _, _, _ = _fixture(candidate)
    electrical = config['shading_configuration']['electrical_shading_configuration']
    electrical['scientific_options'].pop('allow_synthetic_regions')
    electrical['execution_options']['allow_synthetic_regions'] = True
    with pytest.raises(NumericalAssumptionInputError, match='requires scientific opt-in'):
        authorize_selected_assumptions(config, store.detailed_electrical_inputs)


@pytest.mark.parametrize('fault', ['missing_source', 'pan_binding', 'retained_pan_binding', 'topology_revision',
    'parameterization_revision', 'consistency_record', 'secondary_gate', 'cell_scope'])
def test_rehashed_selected_asset_corruption_denies(candidate, fault):
    changed = deepcopy(candidate)
    module, topology, definition, evidence, sources = changed
    if fault == 'missing_source':
        sources.pop('b2-assumption')
    elif fault in {'pan_binding', 'retained_pan_binding'}:
        key = 'original_pan_sha256' if fault == 'pan_binding' else 'retained_pan_sha256'
        evidence['assumption_declaration']['module_source'][key] = 'd'*64
        _seal(changed)
    elif fault == 'topology_revision':
        topology['revision_id'] += '-foreign'
        _seal(changed)
    elif fault == 'parameterization_revision':
        definition['revision_id'] += '-foreign'
        _seal(changed)
    elif fault == 'consistency_record':
        evidence['consistency_record']['cases'][0]['samples'][0]['module_voltage_v'] += 1.
        _seal(changed)
    elif fault == 'secondary_gate':
        # G1 remains unchanged; the declared reverse domain cannot support the
        # approved secondary real-kernel bypass/conservation checks.
        for region in definition['region_parameterizations']:
            region['reverse_bias']['minimum_supported_voltage_v'] = -1e-8
        _seal(changed)
    else:
        evidence['parameterization_scope'] = 'cell'
    _, config, store, _, _, bundle = _fixture(changed, validate_selection=False)
    diagnostics = {
        'missing_source': (SnapshotWitnessError, 'unpinned SourceRecord'),
        'pan_binding': (SnapshotWitnessError, 'original and retained PAN hashes'),
        'retained_pan_binding': (SnapshotWitnessError, 'original and retained PAN hashes'),
        'topology_revision': (SnapshotWitnessError, 'stale topology revision binding'),
        'parameterization_revision': (SnapshotWitnessError, 'exact revision unavailable'),
        'consistency_record': (SnapshotWitnessError, 'consistency residual must be assembled minus module voltage'),
        'secondary_gate': (NumericalAssumptionInputError, 'B3 Phase66SeriesModuleAdapterError:.*reference current ceiling is too low'),
        'cell_scope': (SnapshotWitnessError, 'does not have scope'),
    }
    # Freeze is structural only: it rejects linkage/evidence corruption but
    # leaves the secondary numerical gate to the execution authority boundary.
    if fault == 'secondary_gate':
        assert freeze_detailed_selection(bundle).replay() == bundle
    else:
        freeze_error = (ValueError if fault in {'missing_source', 'topology_revision', 'cell_scope'}
                        else NumericalAssumptionInputError)
        with pytest.raises(freeze_error, match=diagnostics[fault][1]) as rejected:
            freeze_detailed_selection(bundle)
        assert type(rejected.value) is freeze_error
    error, diagnostic = diagnostics[fault]
    with pytest.raises(error, match=diagnostic):
        context = build_snapshot_witness_context(config, store.detailed_electrical_inputs)
        witness = build_detailed_snapshot_witness(context, module['revision_id'])
        from engine.simulation.detailed_inputs import validate_assumption_authorization_witness
        validate_assumption_authorization_witness(witness)


@pytest.mark.parametrize('fidelity,policy', [
    ('level_3_cell_submodule_iv', 'fail_closed'), ('level_2_bypass_substring', 'explicit_lower_fidelity')])
def test_unsupported_execution_policy_denies(candidate, fidelity, policy):
    _, config, store, _, _, bundle = _fixture(candidate)
    electrical = config['shading_configuration']['electrical_shading_configuration']
    electrical.update(requested_fidelity=fidelity, fallback_policy=policy)
    for selection in bundle['electrical_shading_selections'].values():
        selection.update(requested_fidelity=fidelity, resolved_fidelity=fidelity, fallback_policy=policy)
        _seal_selection(selection)
    diagnostic = 'only Level-2' if fidelity == 'level_3_cell_submodule_iv' else 'require fail_closed policy'
    with pytest.raises(NumericalAssumptionInputError, match=diagnostic):
        authorize_selected_assumptions(config, _raw_frozen(bundle))


def test_bare_boolean_and_unwitnessed_replay_denied(candidate):
    _, config, store, _, _, _ = _fixture(candidate)
    snapshot = _pin(config, store)
    payload = json.loads(snapshot.canonical_payload)
    for witness in (True, None):
        error = SnapshotWitnessError if witness is True else NumericalAssumptionInputError
        diagnostic = 'witness type' if witness is True else 'authenticated execution is not enabled'
        with pytest.raises(error, match=diagnostic):
            replace(snapshot, witness=witness).replay()
        diagnostic = 'witness type' if witness is True else 'B3 authorization boundary'
        with pytest.raises(error, match=diagnostic):
            validate_regional_transport(witness, payload['topology'], payload['parameterization'], payload['evidence'])
    with pytest.raises(NumericalAssumptionInputError, match='B3 authorization boundary'):
        deny_numerical_assumption_execution(payload['evidence'], authority=True)


@pytest.mark.parametrize('foreign', ['configuration', 'selection', 'module'])
def test_self_consistent_foreign_witness_not_run_authority(candidate, foreign):
    _, config, store, _, _, bundle = _fixture(candidate)
    snapshot = _pin(config, store)
    if foreign == 'configuration':
        other = deepcopy(config)
        other['numerical_options']['albedo'] = .37
        witness = build_detailed_snapshot_witness(build_snapshot_witness_context(other, store.detailed_electrical_inputs), snapshot.witness.module_revision_id)
        snapshot = replace(snapshot, witness=witness)
    elif foreign == 'selection':
        other = deepcopy(bundle)
        other['pinned_electrical_shading_assets']['sources']['extra'] = {
            'schema_name': 'SourceRecord', 'schema_version': '0.1', 'source_id': 'extra', 'source_type': 'manual_entry'}
        other_frozen = _raw_frozen(other)
        witness = build_detailed_snapshot_witness(build_snapshot_witness_context(config, other_frozen), snapshot.witness.module_revision_id)
        data = _bytes(_selected_witness_payload(other_frozen._replay_structure(), snapshot.witness.module_revision_id))
        snapshot = DetailedModuleInputSnapshot(data, sha256(data).hexdigest(), witness)
    else:
        snapshot = replace(snapshot, witness=replace(snapshot.witness, module_revision_id='foreign'))
    with pytest.raises(SnapshotWitnessError, match='foreign configuration or selection|membership'):
        prepare_execution_transport({'M': snapshot}, config, store.detailed_electrical_inputs)


@pytest.mark.parametrize('fault', ['missing', 'foreign_configuration', 'foreign_revision', 'foreign_membership'])
@pytest.mark.parametrize('worker', ['backend', 'attribution'])
def test_worker_initializers_fail_closed(candidate, fault, worker):
    _, config, store, _, _, _ = _fixture(candidate)
    snapshot = _pin(config, store)
    context = {**prepare_execution_transport({'M': snapshot}, config, store.detailed_electrical_inputs),
        'module_inputs': {'M': snapshot.replay()}}
    if fault == 'missing':
        context['module_witnesses'] = {}
    elif fault == 'foreign_configuration':
        other = deepcopy(config)
        other['numerical_options']['albedo'] = .38
        context['expected_witness_context'] = build_snapshot_witness_context(other, store.detailed_electrical_inputs)
    elif fault == 'foreign_revision':
        context['expected_module_revisions']['M'] = 'foreign'
    else:
        context['module_witnesses']['foreign'] = snapshot.witness
    from engine.simulation import detailed_backend, detailed_attribution
    initialize = detailed_backend._initialize_interval_worker if worker == 'backend' else detailed_attribution._initialize_attribution_worker
    diagnostic = {'missing': 'missing numerical-assumption worker context',
        'foreign_configuration': 'foreign configuration or selection',
        'foreign_revision': 'foreign worker module revision membership',
        'foreign_membership': 'foreign worker module membership'}[fault]
    with pytest.raises(SnapshotWitnessError, match=diagnostic):
        initialize(context)


def test_actual_spawn_run_and_package_parity(completed, tmp_path):
    (project, config, store, _, _, _), serial = completed
    parallel = deepcopy(config)
    parallel['shading_configuration']['electrical_shading_configuration']['execution_options'].update(
        electrical_worker_count=2, attribution_worker_count=2)
    actual = _run(tmp_path, project, parallel, store, name='b3d2-workers')
    assert actual.summary_result is not None, actual.simulation_run
    assert actual.detailed_backend_result.record() == serial.detailed_backend_result.record()
    assert actual.detailed_attribution_result.record() == serial.detailed_attribution_result.record()
    verify_run_package(actual.artifact_directory)


@pytest.mark.parametrize('fault', ['change', 'remove', 'reorder', 'forged_evidence'])
def test_persisted_tampering_with_regenerated_hashes_denied(completed, tmp_path, fault):
    _, result = completed
    directory = tmp_path / fault
    shutil.copytree(result.artifact_directory, directory)
    path = directory / 'detailed-execution-context.json'
    context = json.loads(path.read_text())
    if fault == 'change':
        context['identity']['limitations'][-1] += ' substituted'
    elif fault == 'remove':
        context['identity']['limitations'].pop()
    elif fault == 'reorder':
        context['identity']['limitations'][-2:] = reversed(context['identity']['limitations'][-2:])
    else:
        bundle = deepcopy(context['selection_snapshot']['payload'])
        evidence = next(iter(bundle['pinned_electrical_shading_assets']['electrical_parameterization_evidence'].values()))
        evidence['consistency_record']['passed'] = True
        evidence['consistency_record']['cases'][0]['samples'][0]['assembled_voltage_v'] += .1
        from shading.electrical.contract import numerical_assumption_object_sha256
        evidence['consistency_record']['digest_sha256'] = numerical_assumption_object_sha256(evidence['consistency_record'])
        _rehash(context, bundle)
    _rehash(context)
    path.write_text(json.dumps(context))
    (directory / 'run-package-manifest.json').write_text(json.dumps(
        _build_run_package_manifest(directory, simulation_run_id=result.simulation_run['simulation_run_id'])))
    error = ElectricalShadingContractError if fault == 'forged_evidence' else DetailedInputError
    diagnostic = ('consistency residual must be assembled minus module voltage'
                  if fault == 'forged_evidence' else 'assumption scientific limitations mismatch')
    with pytest.raises(error, match=diagnostic):
        verify_detailed_context(context)
    with pytest.raises(error, match=diagnostic):
        verify_run_package(directory)


def test_verifier_fresh_physics_ignores_producer_cache(completed, monkeypatch):
    _, result = completed
    import shading.electrical.parameterization as physics
    original = physics._evaluate_numerical_candidate_physics
    calls = []
    def real(*args):
        calls.append(args)
        return original(*args)
    def poisoned_cache(*args):
        raise AssertionError('independent verifier consulted producer cache')
    monkeypatch.setattr(physics, '_evaluate_numerical_candidate_physics', real)
    monkeypatch.setattr(physics, '_cached_numerical_candidate', poisoned_cache)
    verify_run_package(result.artifact_directory)
    assert calls
    def reject(*args):
        raise ValueError('fresh verifier physics unavailable')
    monkeypatch.setattr(physics, '_evaluate_numerical_candidate_physics', reject)
    with pytest.raises(NumericalAssumptionInputError, match='fresh verifier physics unavailable'):
        verify_run_package(result.artifact_directory)


# Run established legacy regressions directly, without altering their assertions.
from tests.unit.test_rb_post3d_08b3c_context_propagation import (
    test_legacy_payload_bytes_and_replay,
    test_unselected_v02_level_zero,
    test_source_backed_adapter_unchanged_with_default_context,
    test_pinned_phase66_reverse_voltage_reference,
    test_broad_value_error_does_not_swallow_integrity,
    test_abbreviated_dark_completed_pass_stays_in_parent,
)
from tests.unit.test_phase610_stage3d_parallel_backend import (
    test_canonical_scientific_parity_and_independent_package_verification,
)


@pytest.mark.parametrize('fault', ['missing', 'foreign'])
def test_parent_rejects_unbound_worker_result(candidate, fault):
    from engine.simulation.detailed_inputs import bind_worker_result, accept_worker_result
    _, config, store, _, _, _ = _fixture(candidate)
    snapshot = _pin(config, store)
    context = {**prepare_execution_transport({'M': snapshot}, config, store.detailed_electrical_inputs),
        'module_inputs': {'M': snapshot.replay()}}
    bound = bind_worker_result(context, {'finite_result': 1.})
    result = bound.result if fault == 'missing' else replace(bound, membership_sha256='f'*64)
    with pytest.raises(SnapshotWitnessError, match='missing or foreign numerical worker result authority'):
        accept_worker_result(context, result)


def test_worker_integrity_error_never_falls_back(candidate, tmp_path, monkeypatch):
    from engine.simulation import detailed_backend as backend
    project, config, store, _, _, _ = _fixture(candidate)
    calls = []
    def reject(*args, **kwargs):
        calls.append('worker')
        raise SnapshotWitnessError('foreign numerical worker authority')
    def forbidden(*args, **kwargs):
        raise AssertionError('integrity failure retried through a legacy runner')
    monkeypatch.setattr(backend, '_ordered_interval_results', reject)
    monkeypatch.setattr('engine.simulation.canonical.run_unshaded_fixed_tilt', forbidden)
    monkeypatch.setattr('engine.simulation.canonical.run_beam_sky_ground_shaded_fixed_tilt', forbidden)
    with pytest.raises(SnapshotWitnessError, match='foreign numerical worker authority'):
        _run(tmp_path, project, config, store, name='worker-integrity')
    assert calls == ['worker']
    assert not list(tmp_path.rglob('run-package-manifest.json'))


def test_secondary_failure_is_real_kernel_rejection_after_g1(candidate):
    from shading.electrical.parameterization import evaluate_numerical_assumption_acceptance
    changed = deepcopy(candidate)
    # G1 samples are below Isc and do not use the negative-voltage domain.
    # The secondary bypass gate must reject this insufficient reverse domain.
    for entry in changed[2]['region_parameterizations']:
        entry['reverse_bias']['minimum_supported_voltage_v'] = -1e-8
    _seal(changed)
    assert changed[3]['consistency_record']['passed'] is True
    result = evaluate_numerical_assumption_acceptance(*changed, use_cache=False)
    assert result['accepted'] is False
    assert result['failures']
    assert not any('G1 maximum' in failure for failure in result['failures'])


def test_v02_cannot_pass_legacy_evidence_binding(candidate):
    from shading.electrical.parameterization import (
        assert_parameterization_evidence_binding, ElectricalParameterizationError,
    )
    with pytest.raises(ElectricalParameterizationError, match='schema_version'):
        assert_parameterization_evidence_binding(candidate[2], candidate[3])
