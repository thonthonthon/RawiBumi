"""B3A configuration and selection denial; no numerical authorization."""
from copy import deepcopy
from dataclasses import replace
import hashlib

import pytest

from engine.simulation.artifacts import canonical_object_sha256
from engine.simulation.detailed_dispatch import scientific_configuration
from engine.simulation.detailed_inputs import (
    FrozenDetailedSelectionSnapshot, _bytes, semantic_scientific_payload,
    freeze_detailed_selection, pin_detailed_module_inputs,
    validate_detailed_runtime_support, validate_synthetic_region_option,
)
from shading.electrical.contract import NumericalAssumptionInputError
from tests.unit.test_phase69a_detailed_inputs import _inputs, _configuration
from tests.unit.test_phase69a_canonical_dispatch import _context, _run
from tests.unit.test_rb_post3d_08b1_evidence_foundation import assumed


def _request(config):
    return config['shading_configuration']['electrical_shading_configuration']


def _replace_bundle(store, bundle):
    encoded = _bytes(bundle)
    return replace(store, detailed_electrical_inputs=FrozenDetailedSelectionSnapshot(
        encoded, hashlib.sha256(encoded).hexdigest(),
        hashlib.sha256(_bytes(semantic_scientific_payload(bundle))).hexdigest()))


def test_absent_defaults_false_without_mutation():
    request = {'scientific_options': {}}
    assert validate_synthetic_region_option(request) is False
    assert request == {'scientific_options': {}}


@pytest.mark.parametrize('value', [False, True])
def test_literal_booleans_supported_by_public_preflight(value):
    config = _configuration()
    _request(config)['scientific_options']['allow_synthetic_regions'] = value
    assert validate_detailed_runtime_support(config, pin_detailed_module_inputs(**_inputs()))


@pytest.mark.parametrize('value', ['true', 'false', 0, 1, None, [], {}])
def test_invalid_option_never_falls_back(tmp_path, value):
    project, config, store, _ = _context('explicit_lower_fidelity')
    _request(config)['scientific_options']['allow_synthetic_regions'] = value
    result = _run(tmp_path, project, config, store)
    identity = result.simulation_run['detailed_execution_identity']
    assert identity['runtime_support_result'] == 'blocked'
    assert identity['resolved_fidelity'] is None
    assert identity['fallback_applied'] is False
    assert 'explicit boolean' in str(identity['failure_reasons'])


def test_scientific_identity_and_legacy_module_bytes():
    config = _configuration()
    original = deepcopy(config)
    snapshot = pin_detailed_module_inputs(**_inputs())
    hashes = [canonical_object_sha256(scientific_configuration(config))]
    for value in (False, True):
        _request(config)['scientific_options']['allow_synthetic_regions'] = value
        hashes.append(canonical_object_sha256(scientific_configuration(config)))
        assert pin_detailed_module_inputs(**_inputs()) == snapshot
    assert len(set(hashes)) == 3
    assert set(snapshot.replay()) == {'module', 'topology', 'parameterization', 'evidence', 'sources'}
    assert snapshot.canonical_payload == _bytes(snapshot.replay())
    _request(original)['execution_options']['allow_synthetic_regions'] = True
    assert canonical_object_sha256(scientific_configuration(original)) == hashes[0]
    assert validate_synthetic_region_option(_request(original)) is False


@pytest.mark.parametrize('opt_in', [None, False, True])
@pytest.mark.parametrize('policy', ['fail_closed', 'explicit_lower_fidelity'])
@pytest.mark.parametrize('corruption', ['version', 'class', 'quality', 'revision'])
def test_selected_numerical_evidence_always_denied(tmp_path, opt_in, policy, corruption):
    project, config, store, _ = _context(policy)
    bundle = store.detailed_electrical_inputs.replay()
    evidence = next(iter(bundle['pinned_electrical_shading_assets']['electrical_parameterization_evidence'].values()))
    evidence['schema_version'] = '0.2'
    if corruption == 'class':
        evidence['schema_version'] = '0.1'
        evidence['evidence_class'] = 'NUMERICAL_ASSUMPTION'
    elif corruption == 'quality':
        evidence['module_quality_declaration'] = {'source_ids': ['missing']}
    elif corruption == 'revision':
        evidence['evidence_class'] = 'NUMERICAL_ASSUMPTION'
        evidence['parameterization_revision_id'] = 'missing'
    if opt_in is not None:
        _request(config)['scientific_options']['allow_synthetic_regions'] = opt_in
    _request(config)['execution_options']['allow_synthetic_regions'] = True
    result = _run(tmp_path, project, config, _replace_bundle(store, bundle))
    identity = result.simulation_run['detailed_execution_identity']
    assert identity['runtime_support_result'] == 'blocked'
    assert identity['resolved_fidelity'] is None
    assert not identity['fallback_applied']
    assert 'NUMERICAL_ASSUMPTION_EXECUTION_DENIED' in str(identity['failure_reasons'])


def test_unselected_valid_numerical_record_allows_level_zero(tmp_path):
    project, config, store, bundle = _context()
    unused = assumed()
    bundle['pinned_electrical_shading_assets']['electrical_parameterization_evidence'][unused['evidence_id']] = unused
    frozen = freeze_detailed_selection(bundle)
    assert frozen.replay()['pinned_electrical_shading_assets']['electrical_parameterization_evidence']['e'] == unused
    _request(config)['requested_fidelity'] = 'level_0_geometric_only'
    result = _run(tmp_path, project, config, replace(store, detailed_electrical_inputs=frozen))
    assert result.simulation_run['detailed_execution_identity']['runtime_support_result'] == 'geometry_only'


def test_legacy_metadata_remains_non_authoritative():
    inputs = _inputs()
    inputs['evidence']['metadata'] = {'numerical_assumption': {'allow_synthetic_regions': True}}
    assert pin_detailed_module_inputs(**inputs).replay()['evidence'] == inputs['evidence']


def test_valid_b1_selected_record_remains_nonexecutable():
    inputs = _inputs()
    inputs['evidence'] = assumed()
    with pytest.raises(NumericalAssumptionInputError, match='B3'):
        pin_detailed_module_inputs(**inputs)


def test_opt_in_does_not_promote_numerical_readiness():
    from shading.electrical.contract import validate_parameterization_for_electrical_shading
    config = _configuration()
    _request(config)['scientific_options']['allow_synthetic_regions'] = True
    assert validate_synthetic_region_option(_request(config)) is True
    result = validate_parameterization_for_electrical_shading(
        assumed(), expected_scope='region_substring',
        module_definition={'revision_id': 'm1'}, topology_definition={'revision_id': 't1'})
    assert result.ready is False


def test_b2_scientific_policy_unchanged():
    from shading.electrical.contract import (
        NUMERICAL_ASSUMPTION_POLICY_ID, NUMERICAL_ASSUMPTION_POLICY_VERSION,
        REQUIRED_NUMERICAL_ASSUMPTION_LIMITATIONS,
    )
    evidence = assumed()
    assert NUMERICAL_ASSUMPTION_POLICY_ID == 'rawibumi.level2.uniform_iv_equal_series'
    assert NUMERICAL_ASSUMPTION_POLICY_VERSION == '1.0.0'
    assert evidence['assumption_declaration']['scientific_limitations'] == list(
        REQUIRED_NUMERICAL_ASSUMPTION_LIMITATIONS)
