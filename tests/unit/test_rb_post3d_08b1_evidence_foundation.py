"""B1 stored-value integrity regressions; no physical consistency claim."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shading.electrical.contract import (
    REQUIRED_NUMERICAL_ASSUMPTION_LIMITATIONS,
    ElectricalShadingContractError,
    BypassModelEvidence,
    ResolvedModuleCapabilitySnapshot,
    TopologyValidationResult,
    assert_electrical_parameterization_evidence,
    assert_numerical_assumption_evidence_structure,
    numerical_assumption_object_sha256,
    resolve_electrical_shading_capability,
    validate_parameterization_for_electrical_shading,
)
from shading.electrical.parameterization import assert_parameterization_evidence_binding

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / 'shading/electrical/electrical-parameterization-evidence.schema.json').read_text())
VALIDATOR = Draft202012Validator(SCHEMA)


def legacy():
    return dict(schema_name='ElectricalParameterizationEvidence', schema_version='0.1',
                contract_version='0.1', evidence_id='e', parameterization_scope='region_substring',
                parameterization_id='p', module_definition_revision_id='m1',
                module_topology_revision_id='t1', model_id='model', model_version='0.1',
                validation_record_id='validation', validation_status='passed',
                verification_state='auto_validated', parameterization_provenance='derived_validated',
                source_ids=['source'], parameterization_payload_sha256='a' * 64)


def seal(evidence):
    declaration = evidence['assumption_declaration']
    declaration['digest_sha256'] = numerical_assumption_object_sha256(declaration)
    record = evidence['consistency_record']
    record['assumption_digest_sha256'] = declaration['digest_sha256']
    record['digest_sha256'] = numerical_assumption_object_sha256(record)
    return evidence


def assumed():
    e = legacy()
    e.update(schema_version='0.2', evidence_class='NUMERICAL_ASSUMPTION',
             parameterization_revision_id='p1', validation_record_id=None,
             validation_status='not_applicable', verification_state='not_applicable',
             parameterization_provenance='simulation_assumption')
    e['assumption_declaration'] = dict(
        assumption_id='hypothesis', assumption_revision_id='hypothesis1',
        assumption_source_id='manual-source', author='Test fixture author',
        rationale='Synthetic equal-series hypothesis for contract tests.',
        evidence_class='NUMERICAL_ASSUMPTION', region_count=3,
        module_source=dict(component_id='module', revision_id='m1',
                           original_pan_sha256='b'*64, retained_pan_sha256='c'*64),
        topology=dict(topology_id='topology', topology_revision_id='t1', topology_sha256='d'*64),
        parameterization=dict(parameterization_id='p', parameterization_revision_id='p1',
                              parameterization_sha256='a'*64),
        scientific_limitations=list(REQUIRED_NUMERICAL_ASSUMPTION_LIMITATIONS))
    e['consistency_record'] = dict(
        policy_id='rawibumi.level2.uniform_iv_equal_series', policy_version='1.0.0',
        model_family='pvsyst_sdm', voltage_tolerance_v=0.0001, max_abs_residual_v=0.0,
        passed=True, cases=[dict(irradiance_w_m2=g, cell_temperature_c=t,
            samples=[dict(current_a=i, module_voltage_v=40.0-i,
                          assembled_voltage_v=40.0-i, residual_v=0.0)
                     for i in (1., 3., 5., 7., 9.)]) for g,t in ((1000,25),(800,45),(400,15))])
    return seal(e)


def at(e, path):
    keys = path.split('.')
    target = e
    for key in keys[:-1]:
        target = target[int(key)] if isinstance(target, list) else target[key]
    key = int(keys[-1]) if isinstance(target, list) else keys[-1]
    return target, key


def test_schema_and_valid_record_are_nonmutating():
    Draft202012Validator.check_schema(SCHEMA)
    e = assumed()
    before = copy.deepcopy(e)
    VALIDATOR.validate(e)
    assert_numerical_assumption_evidence_structure(e)
    assert e == before


@pytest.mark.parametrize('metadata', [{}, {'arbitrary': [None, 3]},
    {'numerical_assumption': {'allow_synthetic_regions': True, 'topology_trusted': True}}])
def test_legacy_acceptance_hash_and_readiness_unchanged(metadata):
    e = legacy()
    e['metadata'] = metadata
    before = json.dumps(e, sort_keys=True)
    VALIDATOR.validate(e)
    assert_electrical_parameterization_evidence(e)
    result = validate_parameterization_for_electrical_shading(e, expected_scope='region_substring',
        module_definition={'revision_id':'m1'}, topology_definition={'revision_id':'t1'})
    baseline = validate_parameterization_for_electrical_shading(legacy(), expected_scope='region_substring',
        module_definition={'revision_id':'m1'}, topology_definition={'revision_id':'t1'})
    assert result == baseline
    assert result.ready
    assert json.dumps(e, sort_keys=True) == before


@pytest.mark.parametrize('path,value', [
    ('schema_version','0.3'), ('evidence_class','SOURCE_VALIDATED'),
    ('validation_status','passed'), ('verification_state','reviewed'),
    ('parameterization_provenance','derived_validated'), ('validation_record_id','fake'),
    ('parameterization_payload_sha256','A'*64),
    ('assumption_declaration.module_source.original_pan_sha256','ABC'),
    ('assumption_declaration.module_source.retained_pan_sha256','g'*64),
    ('assumption_declaration.topology.topology_sha256','D'*64),
    ('assumption_declaration.parameterization.parameterization_sha256','short'),
    ('assumption_declaration.author','  '), ('assumption_declaration.rationale',''),
    ('assumption_declaration.assumption_source_id',''), ('assumption_declaration.region_count',True),
    ('assumption_declaration.region_count',3.0), ('assumption_declaration.region_count',4),
    ('consistency_record.policy_id','other'), ('consistency_record.policy_version','2.0.0'),
    ('consistency_record.model_family','other'), ('consistency_record.voltage_tolerance_v',0.01),
    ('consistency_record.cases.0.samples.0.current_a',True),
    ('consistency_record.cases.0.samples.0.current_a',-1),
    ('consistency_record.cases.0.samples.0.current_a',-0.0),
    ('consistency_record.cases.0.samples.0.module_voltage_v',float('nan')),
    ('consistency_record.cases.0.samples.0.assembled_voltage_v',float('inf')),
    ('consistency_record.cases.0.samples.0.residual_v',0.001),
    ('consistency_record.max_abs_residual_v',0.001),
])
def test_invalid_values_rejected_even_if_rehashed(path, value):
    e = assumed()
    target,key = at(e,path)
    target[key] = value
    # Nonfinite JSON cannot be signed by the canonical serializer.
    if isinstance(value,float) and not __import__('math').isfinite(value):
        with pytest.raises(ValueError):
            seal(e)
    else:
        seal(e)
    with pytest.raises(ElectricalShadingContractError):
        assert_numerical_assumption_evidence_structure(e)


@pytest.mark.parametrize('path', ['schema_version','assumption_declaration','consistency_record',
    'assumption_declaration.author','assumption_declaration.rationale',
    'assumption_declaration.assumption_source_id'])
def test_required_fields(path):
    e = assumed()
    target,key = at(e,path)
    del target[key]
    assert not VALIDATOR.is_valid(e)
    with pytest.raises(ElectricalShadingContractError):
        assert_numerical_assumption_evidence_structure(e)


@pytest.mark.parametrize('path', ['', 'assumption_declaration', 'assumption_declaration.module_source',
    'assumption_declaration.topology', 'assumption_declaration.parameterization',
    'consistency_record','consistency_record.cases.0','consistency_record.cases.0.samples.0'])
def test_extra_typed_fields(path):
    e = assumed()
    target = e if not path else at(e,path)[0][at(e,path)[1]]
    target['unauthorized'] = 1
    assert not VALIDATOR.is_valid(e)
    with pytest.raises(ElectricalShadingContractError):
        assert_numerical_assumption_evidence_structure(e)


def leaf_paths(value, prefix=''):
    if isinstance(value, dict):
        for key,child in value.items():
            yield from leaf_paths(child, f'{prefix}.{key}' if prefix else key)
    elif isinstance(value,list):
        for key,child in enumerate(value):
            yield from leaf_paths(child, f'{prefix}.{key}')
    else:
        yield prefix


@pytest.mark.parametrize('path', list(leaf_paths(assumed()['assumption_declaration'], 'assumption_declaration')) +
    list(leaf_paths(assumed()['consistency_record'], 'consistency_record')))
def test_every_digest_bound_leaf_mutation_is_detected(path):
    e = assumed()
    target,key = at(e,path)
    value = target[key]
    target[key] = not value if isinstance(value,bool) else value+1 if isinstance(value,(int,float)) else value+'x'
    with pytest.raises(ElectricalShadingContractError):
        assert_numerical_assumption_evidence_structure(e)


@pytest.mark.parametrize('index', range(8))
def test_each_limitation_required(index):
    e = assumed()
    del e['assumption_declaration']['scientific_limitations'][index]
    seal(e)
    with pytest.raises(ElectricalShadingContractError):
        assert_numerical_assumption_evidence_structure(e)


@pytest.mark.parametrize('mutation', ['missing_case','extra_case','case_order','missing_sample',
    'sample_order','signed_residual','forged_pass','digest_link','limitations_order','extras_order'])
def test_record_semantics_after_resigning(mutation):
    e = assumed()
    r = e['consistency_record']; cases = r['cases']; samples = cases[0]['samples']
    if mutation == 'missing_case': cases.pop()
    elif mutation == 'extra_case': cases.append(copy.deepcopy(cases[0]))
    elif mutation == 'case_order': cases.reverse()
    elif mutation == 'missing_sample': samples.pop()
    elif mutation == 'sample_order': samples.reverse()
    elif mutation in ('signed_residual','forged_pass'):
        samples[0]['assembled_voltage_v'] += 1
        samples[0]['residual_v'] = -1. if mutation == 'signed_residual' else 1.
        r['max_abs_residual_v'] = 1.
    elif mutation == 'limitations_order': e['assumption_declaration']['scientific_limitations'].reverse()
    elif mutation == 'extras_order': e['assumption_declaration']['scientific_limitations'] += ['Z extra','A extra']
    seal(e)
    if mutation == 'digest_link':
        r['assumption_digest_sha256'] = 'e'*64
        r['digest_sha256'] = numerical_assumption_object_sha256(r)
    with pytest.raises(ElectricalShadingContractError):
        assert_numerical_assumption_evidence_structure(e)


def test_canonical_digest_matches_approved_bytes_and_key_order():
    value = {'z':1.0,'author':'Régression','digest_sha256':'ignored','a':3}
    canonical = json.dumps({k:v for k,v in value.items() if k != 'digest_sha256'},
        sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    assert numerical_assumption_object_sha256(value) == hashlib.sha256(canonical).hexdigest()
    assert numerical_assumption_object_sha256(dict(reversed(list(value.items())))) == numerical_assumption_object_sha256(value)
    assert numerical_assumption_object_sha256({'n':1}) != numerical_assumption_object_sha256({'n':1.0})


@pytest.mark.parametrize('trusted', [False, True])
@pytest.mark.parametrize('scope', ['region_substring','cell'])
def test_assumptions_cannot_execute_or_grant_detailed_capability(trusted, scope):
    e = assumed(); e['parameterization_scope'] = scope
    assert_numerical_assumption_evidence_structure(e)
    with pytest.raises(ElectricalShadingContractError):
        assert_electrical_parameterization_evidence(e)
    with pytest.raises(ValueError) as error:
        assert_parameterization_evidence_binding({}, e)
    from engine.simulation.detailed_inputs import DetailedInputError
    assert not isinstance(error.value, DetailedInputError)
    result = validate_parameterization_for_electrical_shading(e, expected_scope=scope,
        module_definition={'revision_id':'m1'}, topology_definition={'revision_id':'t1'})
    assert not result.ready
    topology = TopologyValidationResult(True,'t1','m1',True,trusted,True,True,'half_cell')
    capability = resolve_electrical_shading_capability(
        ResolvedModuleCapabilitySnapshot('m1','resolution',True), topology,
        bypass_model_evidence=BypassModelEvidence('t1',True,'validated'),
        **{('region_parameterization_evidence' if scope == 'region_substring' else 'cell_parameterization_evidence'):result})
    assert capability['topology_trusted'] is trusted
    assert 'level_2_bypass_substring' not in capability['available_fidelity_levels']
    assert 'level_3_cell_submodule_iv' not in capability['available_fidelity_levels']


@pytest.mark.parametrize('field', ['parameterization_id','parameterization_revision_id',
    'module_definition_revision_id','module_topology_revision_id','parameterization_payload_sha256'])
def test_envelope_binding_mismatch(field):
    e = assumed()
    e[field] = 'f'*64 if field.endswith('sha256') else 'different-revision'
    with pytest.raises(ElectricalShadingContractError):
        assert_numerical_assumption_evidence_structure(e)


def test_failed_record_can_report_deferred_physical_failure():
    e = assumed(); e['consistency_record']['passed'] = False; seal(e)
    assert_numerical_assumption_evidence_structure(e)
    with pytest.raises(ElectricalShadingContractError):
        assert_electrical_parameterization_evidence(e)


def test_legacy_enums_and_property_set_are_not_broadened():
    e = assumed(); e['schema_version'] = '0.1'
    assert not VALIDATOR.is_valid(e)
    for field,value in [('validation_status','not_applicable'),
        ('verification_state','not_applicable'),('parameterization_provenance','simulation_assumption')]:
        e = legacy(); e[field] = value
        assert not VALIDATOR.is_valid(e)
        with pytest.raises(ElectricalShadingContractError):
            assert_electrical_parameterization_evidence(e)
