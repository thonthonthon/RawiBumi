"""Transaction reuse regressions; all positive acceptance uses the real kernel."""
from copy import deepcopy
import json
import shutil

import pytest

from engine.simulation.artifacts import verify_run_package, _build_run_package_manifest, canonical_object_sha256
from engine.simulation.detailed_dispatch import (
    _detailed_verification_transaction, verify_detailed_context,
)
from engine.simulation.detailed_attribution import (
    verify_attribution_sources, _verify_attribution_sources_transaction,
)
from engine.simulation.detailed_inputs import DetailedInputError
from tests.unit.test_rb_post3d_08b2_region_physics import _candidate
from tests.unit.test_rb_post3d_08b3d2_activation import _fixture
from tests.unit.test_rb_post3d_08b3d1_verification import _rehash
from tests.unit.test_phase69a_canonical_dispatch import _run


@pytest.fixture(scope='module')
def candidate():
    return _candidate()


@pytest.fixture(scope='module')
def completed(tmp_path_factory, candidate):
    from engine.simulation import detailed_inputs
    from shading.electrical import parameterization as physics
    fixture = _fixture(candidate)
    project, config, store, _, _, _ = fixture
    counts = {'physics': 0, 'fresh': 0, 'context': 0}
    original_physics = physics._evaluate_numerical_candidate_physics
    original_acceptance = physics.validate_numerical_assumption_acceptance
    import engine.simulation.detailed_dispatch as dispatch
    original_context = dispatch.verify_detailed_context

    def evaluate(*args, **kwargs):
        counts['physics'] += 1
        return original_physics(*args, **kwargs)

    def accept(*args, **kwargs):
        counts['fresh'] += kwargs.get('use_cache') is False
        return original_acceptance(*args, **kwargs)

    def context_check(*args, **kwargs):
        counts['context'] += 1
        return original_context(*args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(physics, '_evaluate_numerical_candidate_physics', evaluate)
        patch.setattr(physics, 'validate_numerical_assumption_acceptance', accept)
        patch.setattr(dispatch, 'verify_detailed_context', context_check)
        detailed_inputs._validated_producer_physics.cache_clear()
        physics._cached_numerical_candidate.cache_clear()
        result = _run(tmp_path_factory.mktemp('transaction'), project, config, store, name='transaction')
    assert result.summary_result is not None, result.simulation_run
    # One cold producer computation, pre-write validation, fresh disk verifier.
    assert counts == {'physics': 3, 'fresh': 2, 'context': 2}
    return fixture, result


def _context(result):
    return json.loads((result.artifact_directory / 'detailed-execution-context.json').read_text())


def test_real_package_fresh_invocations_ignore_producer_cache(completed, monkeypatch):
    from shading.electrical import parameterization as physics
    _, result = completed
    original = physics._evaluate_numerical_candidate_physics
    calls = []

    def evaluate(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError('producer cache cannot supply verifier acceptance')

    monkeypatch.setattr(physics, '_evaluate_numerical_candidate_physics', evaluate)
    monkeypatch.setattr(physics, '_cached_numerical_candidate', forbidden)
    before = _context(result)['identity']['numerical_result_sha256']
    for expected in (1, 2):
        verify_run_package(result.artifact_directory)
        assert len(calls) == expected
    assert _context(result)['identity']['numerical_result_sha256'] == before


def test_exact_binding_and_expiration(completed, monkeypatch):
    from shading.electrical import parameterization as physics
    _, result = completed
    context = _context(result)
    original = physics._evaluate_numerical_candidate_physics
    calls = []

    def evaluate(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(physics, '_evaluate_numerical_candidate_physics', evaluate)
    with _detailed_verification_transaction(context) as check:
        _verify_attribution_sources_transaction(result.detailed_attribution_result, deepcopy(context),
            None, result.detailed_backend_result, _context_check=check)
        assert len(calls) == 1
        changed = deepcopy(context)
        changed['identity']['limitations'][-1] += ' changed'
        _rehash(changed)
        with pytest.raises(DetailedInputError, match='transaction context mismatch'):
            _verify_attribution_sources_transaction(result.detailed_attribution_result, changed,
                _context_check=check)
        # Even non-scientific metadata participates in exact full-context binding.
        changed = deepcopy(context)
        changed['canonical_input_hash'] = 'f' * 64
        with pytest.raises(DetailedInputError, match='transaction context mismatch'):
            check(changed)
    with pytest.raises(DetailedInputError, match='expired'):
        check(context)


def test_standalone_verifiers_are_fresh_and_strict(completed, monkeypatch):
    from shading.electrical import parameterization as physics
    _, result = completed
    context = _context(result)
    original = physics._evaluate_numerical_candidate_physics
    calls = []

    def evaluate(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(physics, '_evaluate_numerical_candidate_physics', evaluate)
    verify_detailed_context(context)
    verify_attribution_sources(result.detailed_attribution_result, context,
        None, result.detailed_backend_result)
    assert len(calls) == 2
    context['identity']['limitations'].pop()
    _rehash(context)
    with pytest.raises(DetailedInputError, match='limitations mismatch'):
        verify_attribution_sources(result.detailed_attribution_result, context)


def test_foreign_attribution_source_rejected_in_transaction(completed):
    from types import SimpleNamespace
    _, result = completed
    context = _context(result)
    # Streaming replay retains the sealed interval store; compatibility replay
    # provides an isolated decoded payload that can safely be corrupted.
    payload = result.detailed_attribution_result.replay()
    module_id = next(iter(payload['source_module_input_hashes']))
    payload['source_module_input_hashes'][module_id] = 'f' * 64
    # Negative-only fake transport: context acceptance still uses real B2.
    foreign = SimpleNamespace(replay_stream=lambda: payload)
    with _detailed_verification_transaction(context) as check:
        with pytest.raises(ValueError, match='module/solver binding mismatch'):
            _verify_attribution_sources_transaction(foreign, context, _context_check=check)



@pytest.mark.parametrize('fault,diagnostic', [
    ('module', 'snapshot witness selected registry identity mismatch'),
    ('topology', 'snapshot witness selected registry identity mismatch'),
    ('parameterization', 'selected parameterization revision mismatch: exact revision unavailable'),
    ('digest', 'assumption_declaration digest mismatch'),
    ('limitations', 'assumption scientific limitations mismatch'),
    ('provenance', 'unpinned SourceRecord ids'),
])
def test_rehashed_package_corruption_rejects(completed, tmp_path, fault, diagnostic):
    _, result = completed
    directory = tmp_path / fault
    shutil.copytree(result.artifact_directory, directory)
    context = _context(result)
    bundle = deepcopy(context['selection_snapshot']['payload'])
    assets = bundle['pinned_electrical_shading_assets']
    evidence = next(iter(assets['electrical_parameterization_evidence'].values()))
    if fault == 'module':
        next(iter(bundle['pinned_components']['modules'].values()))['revision_id'] += '-foreign'
    elif fault == 'topology':
        next(iter(assets['module_topologies'].values()))['revision_id'] += '-foreign'
    elif fault == 'parameterization':
        definitions = assets['electrical_parameterization_definitions']
        revision = evidence['parameterization_revision_id']
        definitions[revision + '-foreign'] = definitions.pop(revision)
        definitions[revision + '-foreign']['revision_id'] = revision + '-foreign'
    elif fault == 'digest':
        evidence['assumption_declaration']['digest_sha256'] = 'f' * 64
    elif fault == 'provenance':
        assets['sources'].pop('b2-assumption')
    elif fault == 'limitations':
        context['identity']['limitations'].pop()
    _rehash(context, bundle)
    with pytest.raises(ValueError, match=diagnostic):
        verify_detailed_context(context)
    # Synchronize superficial run bindings too: rejection must be scientific.
    run_path = directory / 'simulation-run.json'
    run = json.loads(run_path.read_text())
    identity = context['identity']
    run['detailed_execution_identity'] = identity
    run['input_hash'] = canonical_object_sha256({
        'canonical_input_hash': context['canonical_input_hash'],
        'detailed_scientific_input_sha256': identity['scientific_input_sha256'],
        'detailed_execution_identity_sha256': identity['execution_identity_sha256'],
    })
    reproduction = run.get('reproducibility_manifest')
    if reproduction is not None:
        reproduction['detailed_execution_identity'] = identity
        reproduction['input_hashes'].update(
            detailed_scientific_input_sha256=identity['scientific_input_sha256'],
            detailed_execution_identity_sha256=identity['execution_identity_sha256'],
            combined_input_sha256=run['input_hash'])
        (directory / 'reproducibility-manifest.json').write_text(json.dumps(reproduction))
    run_path.write_text(json.dumps(run))
    (directory / 'detailed-execution-context.json').write_text(json.dumps(context))
    (directory / 'run-package-manifest.json').write_text(json.dumps(
        _build_run_package_manifest(directory, simulation_run_id=result.simulation_run['simulation_run_id'])))
    with pytest.raises(ValueError, match=diagnostic):
        verify_run_package(directory)


def test_historical_v01_package_verification(tmp_path):
    from engine.simulation.canonical import run_canonical_simulation
    from tests.unit.test_phase610_stage3a_interval_contract import dark_canonical_fixture
    fixture = dark_canonical_fixture()
    result = run_canonical_simulation(fixture['project'], fixture['configuration'],
        revision_store=fixture['store'], output_directory=tmp_path,
        engine_version='transaction-legacy', simulation_run_id='transaction-legacy')
    try:
        assert result.standard_timeseries is not None, result.simulation_run
        context = _context(result)
        registry = context['inputs']['frozen_selection']['pinned_electrical_shading_assets'][
            'electrical_parameterization_evidence']
        assert registry and all(e['schema_version'] == '0.1' for e in registry.values())
        verify_run_package(result.artifact_directory)
    finally:
        if result.detailed_backend_result is not None:
            result.detailed_backend_result.close()
        if result.detailed_attribution_result is not None:
            result.detailed_attribution_result.close()


def test_caller_callable_cannot_replace_verification(completed):
    _, result = completed
    with pytest.raises(ValueError, match='invalid detailed verification transaction result'):
        verify_attribution_sources(result.detailed_attribution_result, _context(result),
            _context_check=lambda context: None)


# Worker authority, Level-3 denial, legacy bytes/dark execution and serial/spawn
# numerical parity remain covered by test_rb_post3d_08b3d2_activation.py in the
# orchestrator selection; do not collect those expensive tests twice here.
