"""ENG2: beta-only acceptance, preserved evidence and independent voltage bounds."""
from tests.unit._availability import missing_commit
import ast
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import numpy as np
import pvlib
import pytest

from apps.api.catalog import load_reference_catalog
from apps.api.component_library import definition_readiness
from apps.api.server import create_app
from apps.api.study import _validation_configuration
from components.candidates import build_module_candidate, finalize_candidate
from components.pan import map_pan, parse_pan_bytes
from components.pan.pvsyst_sdm import validate_at_stc, validate_off_stc_matrix, calculate_pvsyst_diode_parameters
from components.source_overlay import ComponentSourceFragment, build_candidate_from_fragments, _module_model_validation_passed
from components.validation import pvsyst_sdm_readiness, module_capabilities, validate_module
from engine.module.pvsyst import extract_validated_pvsyst_parameter_set
from engine.simulation.models.module_resolver import resolve_module_model
from validation.engineering import electrical
from components.design_integration import module_nameplate_w  # D14: the DC nameplate basis

ROOT = Path(__file__).resolve().parents[2]
PAN = (ROOT/'tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN').read_bytes()


def variant(sign):
    # Signed offset by 15% of the original magnitude, as approved in A1.
    return PAN.replace(b'muVocSpec=-137.9', f'muVocSpec={-137.9 + sign * .15 * 137.9:.12g}'.encode())


def candidate(raw=PAN):
    return build_module_candidate(map_pan(parse_pan_bytes(raw)), candidate_id='eng2-test',
        module_definition_id='eng2-module', revision_id='eng2-module-r1', source_id='eng2-public-fixture')


def canonical_json(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


@pytest.fixture(scope='module')
def parent_candidate_builder():
    if reason := missing_commit('39dacbc'):
        pytest.skip(reason)
    namespace = {'__file__':str(ROOT/'components/candidates.py'), '__name__':'eng2_parent_candidates'}
    source = subprocess.check_output(['git','show','39dacbc:components/candidates.py'],cwd=ROOT,text=True)
    exec(compile(source,'parent/components/candidates.py','exec'),namespace)
    return namespace['build_module_candidate']


@pytest.fixture(scope='module')
def parent_design_function():
    if reason := missing_commit('39dacbc'):
        pytest.skip(reason)
    source = subprocess.check_output(['git','show','39dacbc:validation/engineering/electrical.py'],cwd=ROOT,text=True)
    node = next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_detailed_module_state')
    namespace = dict(vars(electrical))
    exec(compile(ast.Module(body=[node],type_ignores=[]),'parent/detailed_state','exec'),namespace)
    return namespace['_detailed_module_state']


@pytest.mark.parametrize('sign',[-1,1])
def test_beta_only_acceptance_preserves_every_raw_record_and_replaces_only_its_error(sign,parent_candidate_builder):
    raw = variant(sign)
    actual = candidate(raw)
    original = parent_candidate_builder(map_pan(parse_pan_bytes(raw)),candidate_id='eng2-test',
        module_definition_id='eng2-module',revision_id='eng2-module-r1',source_id='eng2-public-fixture')
    model = actual['canonical_data']['electrical_models'][0]
    old = original['canonical_data']['electrical_models'][0]
    assert not original['capability_flags']['detailed_sdm_ready']
    assert actual['capability_flags']['detailed_sdm_ready']
    assert model['readiness_tolerances'] == ['beta_voc_per_c']
    assert model['validation']['passed'] and model['validation']['status']=='passed'
    assert model['verification_state']=='auto_validated'
    for key in ('stc','off_stc'):
        assert canonical_json(model['validation'][key]) == canonical_json(old['validation'][key])
    off = model['validation']['off_stc']
    assert off['passed'] is False and off['status']=='failed'
    assert model['parameter_set']==old['parameter_set']
    assert actual['derivations']==original['derivations']
    beta = off['coefficient_checks']['beta_voc_per_c']
    warnings = [f for f in actual['validation_findings'] if f['rule_id']=='MODULE_SDM_VOC_TEMPCO_MISMATCH']
    assert len(warnings)==1
    warning = warnings[0]
    assert warning['severity']=='warning' and warning['category']=='electrical'
    assert warning['measured_value']==beta['modeled_value']
    assert warning['limit_value']==beta['source_value']
    assert warning['unit']=='V/°C' and warning['context']['relative_error']==beta['relative_error']
    assert str(beta['modeled_value']) in warning['message'] and str(beta['source_value']) in warning['message']
    assert [f for f in actual['validation_findings'] if f['rule_id']!='MODULE_SDM_VOC_TEMPCO_MISMATCH'] == [
        f for f in original['validation_findings'] if f['rule_id']!='MODULE_SDM_OFF_STC_VALIDATION_FAILED']
    assert finalize_candidate(actual)['capability_flags']['detailed_sdm_ready']
    resolved = resolve_module_model(actual['canonical_data'],resolution_id='eng2-resolver')
    assert resolved['selected_model']['model_id']=='module.pvsyst_singlediode.v6'
    assert resolved['selected_model']['validation_status']=='passed'
    assert resolved['capability_snapshot']['detailed_sdm_ready']
    assert extract_validated_pvsyst_parameter_set(actual['canonical_data'])==model['parameter_set']


@pytest.mark.parametrize('sign',[-1,1])
def test_overlay_recomputation_uses_raw_record_and_stamps_the_same_acceptance(sign):
    module = candidate(variant(sign))['canonical_data']
    # Model an old aggregate; the raw validation record remains authoritative to
    # the shared policy when explicitly rebuilding this component from fragments.
    model = module['electrical_models'][0]
    model['validation']['passed']=False
    model['validation']['status']='failed'
    model['verification_state']='source_attached'
    model.pop('readiness_tolerances')
    module['capability_flags']['detailed_sdm_ready']=False
    before = deepcopy(module)
    assert _module_model_validation_passed(module)
    rebuilt = build_candidate_from_fragments('module',[ComponentSourceFragment('eng2-overlay-fixture',module)],
        candidate_id='eng2-overlay',definition_id='eng2-overlay-def',revision_id='eng2-overlay-r1')
    data = rebuilt['canonical_data']
    assert rebuilt['capability_flags']['detailed_sdm_ready']
    assert data['electrical_models'][0]['validation']['off_stc']==before['electrical_models'][0]['validation']['off_stc']
    assert data['electrical_models'][0]['readiness_tolerances']==['beta_voc_per_c']
    assert sum(f['rule_id']=='MODULE_SDM_VOC_TEMPCO_MISMATCH' for f in rebuilt['validation_findings'])==1
    assert resolve_module_model(data,resolution_id='eng2-overlay-resolve')['selected_model']['model_id']=='module.pvsyst_singlediode.v6'
    assert extract_validated_pvsyst_parameter_set(data)
    assert module==before  # Fragments and their raw evidence were not mutated.


@pytest.mark.parametrize('raw',[PAN,PAN.replace(b'Vmp=40.90',b'Vmp=30.00'),PAN.replace(b'muPmpReq=-0.345',b'muPmpReq=-0.8')])
def test_overlay_aggregate_and_resolver_follow_the_shared_raw_record_decision(raw):
    original=candidate(raw)
    module=deepcopy(original['canonical_data'])
    model=module['electrical_models'][0]
    model['validation']['passed']=not model['validation']['passed']
    model['validation']['status']='passed' if model['validation']['passed'] else 'failed'
    rebuilt=build_candidate_from_fragments('module',[ComponentSourceFragment('eng2-raw-record',module)],
        candidate_id='eng2-recompute',definition_id='eng2-recompute',revision_id='eng2-recompute-r1')
    model=rebuilt['canonical_data']['electrical_models'][0]
    expected=original['canonical_data']['electrical_models'][0]
    assert model['validation']==expected['validation']
    assert rebuilt['capability_flags']['detailed_sdm_ready']==original['capability_flags']['detailed_sdm_ready']
    selected=resolve_module_model(rebuilt['canonical_data'],resolution_id='eng2-recompute-model')['selected_model']['model_id']
    assert selected==('module.pvsyst_singlediode.v6' if expected['validation']['passed'] else 'module.stc_tempco_linear.v0.1')


@pytest.mark.parametrize('replacement',[ (b'Vmp=40.90',b'Vmp=30.00'),(b'muPmpReq=-0.345',b'muPmpReq=-0.8')])
@pytest.mark.parametrize('beta_mismatch',[False,True])
def test_stc_and_gamma_failures_stay_blocked_and_resolve_to_linear(replacement,beta_mismatch):
    raw = variant(-1) if beta_mismatch else PAN
    raw = raw.replace(*replacement)
    actual = candidate(raw)
    model = actual['canonical_data']['electrical_models'][0]
    assert actual['capability_flags']['detailed_sdm_ready'] is False
    assert model['validation']['passed'] is False
    assert model['readiness_tolerances']==[]
    assert not any(f['rule_id']=='MODULE_SDM_VOC_TEMPCO_MISMATCH' for f in actual['validation_findings'])
    assert any(f['severity']=='error' and f['rule_id'].startswith('MODULE_SDM_') for f in actual['validation_findings'])
    assert resolve_module_model(actual['canonical_data'],resolution_id='eng2-broken')['selected_model']['model_id']=='module.stc_tempco_linear.v0.1'
    assert not _module_model_validation_passed(actual['canonical_data'])
    with pytest.raises(ValueError,match='has not passed'):
        extract_validated_pvsyst_parameter_set(actual['canonical_data'])


@pytest.mark.parametrize('failure',['alpha','point','trend','missing'])
def test_the_shared_tolerance_does_not_ignore_other_checks(failure):
    validation = deepcopy(candidate(variant(-1))['canonical_data']['electrical_models'][0]['validation'])
    if failure=='alpha':validation['off_stc']['coefficient_checks']['alpha_isc_per_c']['passed']=False
    elif failure=='point':validation['off_stc']['points'][0]['passed']=False
    elif failure=='trend':validation['off_stc']['trend_checks'][0]['passed']=False
    else:validation['off_stc']['missing_source_coefficients']=['beta_voc_per_c']
    result = pvsyst_sdm_readiness(validation)
    assert not result['passed'] and result['readiness_tolerances']==[] and result['finding'] is None


def test_unchanged_jinko_and_reference_flags_and_design_states_are_identical(parent_candidate_builder,parent_design_function):
    actual = candidate()
    previous = parent_candidate_builder(map_pan(parse_pan_bytes(PAN)),candidate_id='eng2-test',
        module_definition_id='eng2-module',revision_id='eng2-module-r1',source_id='eng2-public-fixture')
    cleaned = deepcopy(actual)
    assert cleaned['canonical_data']['electrical_models'][0].pop('readiness_tolerances')==[]
    assert cleaned==previous
    config={'minimum_cell_temperature_c':-10,'maximum_cell_temperature_c':70,'design_irradiance_w_m2':1000}
    # D14: the only intended difference from the parent is stc_power_w, now the DC nameplate.
    nameplate = lambda state, module: {**asdict(state), 'stc_power_w': module_nameplate_w(module)}
    assert canonical_json(asdict(electrical._detailed_module_state(actual['canonical_data'],**config))) == canonical_json(nameplate(parent_design_function(previous['canonical_data'],**config), previous['canonical_data']))
    namespace={'__file__':str(ROOT/'apps/api/catalog.py'),'__name__':'eng2_parent_catalog','__package__':'apps.api'}
    exec(compile(subprocess.check_output(['git','show','39dacbc:apps/api/catalog.py'],cwd=ROOT,text=True),'parent/catalog','exec'),namespace)
    namespace['build_module_candidate']=parent_candidate_builder
    parent_modules=namespace['load_reference_catalog']()['modules']
    for rid,module in load_reference_catalog()['modules'].items():
        previous_module=parent_modules[rid]
        assert module['capability_flags']==previous_module['capability_flags']
        get_state = electrical._detailed_module_state if module['capability_flags']['detailed_sdm_ready'] else electrical._fallback_module_state
        old_state = parent_design_function if module['capability_flags']['detailed_sdm_ready'] else electrical._fallback_module_state
        assert canonical_json(asdict(get_state(module,**config)))==canonical_json(nameplate(old_state(previous_module,**config), previous_module))


@pytest.mark.parametrize('sign',[-1,1])
@pytest.mark.parametrize('basis',['absolute','relative'])
def test_voltage_envelope_matches_independent_oracle_and_keeps_sdm_currents_power(sign,basis):
    module = candidate(variant(sign))['canonical_data']
    if basis=='relative':
        coeff = module['temperature_coefficients']
        for key,ref in [('alpha_isc_per_c','isc_a'),('beta_voc_per_c','voc_v'),('gamma_pmp_per_c','pmp_w')]:
            coeff[key]/=module['stc'][ref]
        coeff['coefficient_basis']='relative'
    params = module['electrical_models'][0]['parameter_set']
    diode = calculate_pvsyst_diode_parameters(effective_irradiance_w_m2=np.array([1000.,1000.]),
        cell_temperature_c=np.array([-10.,70.]),parameter_set=params)
    solved = pvlib.pvsystem.singlediode(*diode,method='lambertw')
    stc,coeff=module['stc'],module['temperature_coefficients']
    alpha = coeff['alpha_isc_per_c'] if basis=='relative' else coeff['alpha_isc_per_c']/stc['isc_a']
    gamma = coeff['gamma_pmp_per_c'] if basis=='relative' else coeff['gamma_pmp_per_c']/stc['pmp_w']
    beta_absolute=coeff['beta_voc_per_c']*stc['voc_v'] if basis=='relative' else coeff['beta_voc_per_c']
    cold = stc['voc_v'] + beta_absolute*(-10-stc['reference_cell_temperature_c'])
    hot = stc['vmp_v']*(1+(gamma-alpha)*(70-stc['reference_cell_temperature_c']))
    state = electrical._detailed_module_state(module,minimum_cell_temperature_c=-10,maximum_cell_temperature_c=70,design_irradiance_w_m2=1000)
    assert state.voc_min_temp_v==pytest.approx(max(float(solved['v_oc'][0]),cold),rel=0,abs=1e-12)
    assert state.vmp_max_temp_v==pytest.approx(min(float(solved['v_mp'][1]),hot),rel=0,abs=1e-12)
    assert (cold>float(solved['v_oc'][0])) == (sign==-1)
    assert state.model_basis=='validated_pvsyst_singlediode+datasheet_voc_envelope' and not state.downgraded
    assert state.voc_max_temp_v==float(solved['v_oc'][1])
    assert state.vmp_min_temp_v==float(solved['v_mp'][0])
    assert state.imp_min_temp_a==float(solved['i_mp'][0]) and state.imp_max_temp_a==float(solved['i_mp'][1])
    assert state.isc_min_temp_a==float(solved['i_sc'][0]) and state.isc_max_temp_a==float(solved['i_sc'][1])
    assert state.stc_power_w==module_nameplate_w(module)


@pytest.mark.parametrize('missing',['basis','irradiance'])
def test_tolerated_envelope_refuses_missing_linear_inputs(missing):
    module = candidate(variant(-1))['canonical_data']
    if missing=='basis':module['temperature_coefficients'].pop('coefficient_basis')
    else:module['stc'].pop('reference_irradiance_w_m2')
    with pytest.raises(ValueError,match='requires coefficient basis and positive reference irradiance'):
        electrical._detailed_module_state(module,minimum_cell_temperature_c=-10,maximum_cell_temperature_c=70,design_irradiance_w_m2=1000)


@pytest.fixture
def http(tmp_path):
    app = create_app(store_root=tmp_path/'projects',library_root=tmp_path/'component-library')
    with TestClient(app) as client:yield app,client,tmp_path/'component-library'


def upload(client,raw=PAN,dry=False):
    return client.post('/api/component-library/imports',params={'filename':'eng2-synthetic.pan','dry_run':dry},
        content=raw,headers={'Content-Type':'application/octet-stream'})


def test_real_http_tolerated_import_conservative_string_validation_and_completed_simulation(http):
    app,client,_=http
    preview = upload(client,variant(-1),dry=True)
    assert preview.status_code==200 and preview.json()['simulation_ready'],preview.text
    assert any(f['rule_id']=='MODULE_SDM_VOC_TEMPCO_MISMATCH' for f in preview.json()['findings'])
    imported=upload(client,variant(-1));assert imported.status_code==200,imported.text
    rid=imported.json()['entry']['revision_id']
    response=client.post('/api/projects',json={'name':'ENG2 test','latitude_deg':-6.2,'longitude_deg':106.8,'timezone':'Asia/Jakarta'})
    assert response.status_code==201
    pid=response.json()['bundle']['project']['project_id'];url=f'/api/projects/{pid}'
    roof=client.post(url+'/surfaces/rectangle',json={'name':'Roof','width_m':1+18*1.154-.01,'height_m':3.45,'base_elevation_m':6.1})
    assert roof.status_code==200
    sid=roof.json()['bundle']['scene']['surfaces'][0]['surface_id']
    for endpoint,body in [('/pv-fields',{'name':'Array','support_surface_id':sid,'module_definition_revision_id':rid,
        'tilt_deg':10,'row_pitch_m':3.2,'perimeter_setback_m':.5}),
        ('/inverters',{'name':'INV','inverter_definition_revision_id':'inv-rawibumi-uat-150k-r1'}),('/strings',{'string_length':18})]:
        response=client.post(url+endpoint,json=body);assert response.status_code==200,response.text
    iid=response.json()['bundle']['electrical_design']['inverter_instances'][0]['inverter_instance_id']
    assert client.post(url+'/assignments',json={'inverter_instance_id':iid}).status_code==200
    app.state.study_service.acquire_weather(pid,source_id='open_meteo_archive_era5',start_date='2025-01-01',end_date='2025-01-01',
        raw_response=(ROOT/'tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json').read_bytes())
    ready=client.get(url+'/execution-readiness');assert ready.status_code==200 and ready.json()['ready'],ready.text
    bundle=client.get(url).json()['bundle'];module=bundle['pinned_components']['modules'][rid]
    config=_validation_configuration()
    beta=module['temperature_coefficients']['beta_voc_per_c'];stc=module['stc']
    cold=stc['voc_v']+beta*(config['minimum_cell_temperature_c']-stc['reference_cell_temperature_c'])
    report=electrical.validate_engineering_design(bundle['scene'],bundle['electrical_design'],
        project_revision_id=bundle['project']['project_revision']['project_revision_id'],
        component_revisions={**bundle['pinned_components']['modules'],**bundle['pinned_components']['inverters']},
        configuration=config,design_validation_report_id='eng2-http-oracle',generated_at='2026-11-01T00:00:00Z')
    assert not report['blocking_simulation']
    # Read-only counterfactual inverter limit between the SDM and datasheet cold
    # voltages. The real project's reference inverter and bundle stay untouched.
    definitions=deepcopy({**bundle['pinned_components']['modules'],**bundle['pinned_components']['inverters']})
    inverter_id=bundle['electrical_design']['inverter_instances'][0]['inverter_definition_revision_id']
    params=module['electrical_models'][0]['parameter_set']
    diode=calculate_pvsyst_diode_parameters(effective_irradiance_w_m2=stc['reference_irradiance_w_m2'],
        cell_temperature_c=config['minimum_cell_temperature_c'],parameter_set=params)
    sdm_cold=float(pvlib.pvsystem.singlediode(*diode,method='lambertw')['v_oc'])
    count=len(bundle['electrical_design']['strings'][0]['module_instance_ids'])
    limit=count*(sdm_cold+cold)/2
    definitions[inverter_id]['dc_limits']['max_dc_voltage_v']=limit
    constrained=electrical.validate_engineering_design(bundle['scene'],bundle['electrical_design'],
        project_revision_id=bundle['project']['project_revision']['project_revision_id'],component_revisions=definitions,
        configuration=config,design_validation_report_id='eng2-envelope-limit',generated_at='2026-11-01T00:00:00Z')
    voltage=[f for f in constrained['findings'] if f['rule_id']=='STRING_VOC_EXCEEDS_INVERTER_MAX_DC']
    assert len(voltage)==len(bundle['electrical_design']['strings'])
    assert count*sdm_cold<limit<count*cold
    assert all(f['measured_value']==pytest.approx(count*cold) and f['limit_value']==limit for f in voltage)
    assert client.get(url).json()['bundle']==bundle
    simulated=client.post(url+'/simulate',json={})
    assert simulated.status_code==200,simulated.text
    assert simulated.json()['status'] in ('completed','completed_with_warnings')


def test_v2_pan_remap_rebuilds_flags_and_hides_old_revision_without_altering_pins(http):
    if reason := missing_commit('39dacbc'):
        pytest.skip(reason)
    app,client,root=http
    raw=variant(-1)
    imported=upload(client,raw);assert imported.status_code==200
    rid=imported.json()['entry']['revision_id']
    path=root/'modules'/f'{rid}.json';entry=json.loads(path.read_text())
    # Synthetic v2 fixture: reconstruct the immutable parent's actual definition.
    namespace={'__file__':str(ROOT/'components/candidates.py'),'__name__':'eng2_old_import'}
    exec(compile(subprocess.check_output(['git','show','39dacbc:components/candidates.py'],cwd=ROOT,text=True),'parent/candidates','exec'),namespace)
    old=namespace['build_module_candidate'](map_pan(parse_pan_bytes(raw)),candidate_id='legacy-test',
        module_definition_id=entry['library']['definition_id'],revision_id=rid,source_id=entry['definition']['source_ids'][0])
    entry['definition']=old['canonical_data'];entry['library']['importer_version']=2
    entry['library']['findings']=old['validation_findings']
    entry['library']['readiness']=definition_readiness('modules',old['canonical_data'])
    path.write_text(json.dumps(entry,ensure_ascii=False,indent=2)+'\n');before=path.read_bytes()
    assert not entry['definition']['capability_flags']['detailed_sdm_ready']
    app.state.project_service.refresh_catalog()
    response=client.post('/api/projects',json={'name':'Legacy ENG2','latitude_deg':-6.2,'longitude_deg':106.8,'timezone':'Asia/Jakarta'})
    pid=response.json()['bundle']['project']['project_id'];url=f'/api/projects/{pid}'
    roof=client.post(url+'/surfaces/rectangle',json={'name':'Roof','width_m':12,'height_m':10,'base_elevation_m':6})
    field=client.post(url+'/pv-fields',json={'name':'Old','support_surface_id':roof.json()['bundle']['scene']['surfaces'][0]['surface_id'],
        'module_definition_revision_id':rid,'tilt_deg':10,'row_pitch_m':3.2,'perimeter_setback_m':.5})
    assert field.status_code==200,field.text
    stored=client.get(url).json()['bundle']
    before_readiness=client.get(url+'/execution-readiness').json()
    remap=upload(client,raw);assert remap.status_code==200
    preview=remap.json()['entry']
    assert preview['remapped_from']==rid and preview['simulation_ready']
    assert preview['revision_id']==rid[:-1]+'2'
    expected=json.loads(before);expected['library']['hidden']=True
    assert path.read_bytes()==(json.dumps(expected,ensure_ascii=False,indent=2)+'\n').encode()
    assert client.get(url).json()['bundle']==stored
    assert client.get(url+'/execution-readiness').json()==before_readiness
    assert client.get(url).json()['bundle']['pinned_components']['modules'][rid]==old['canonical_data']
    assert not upload(client,raw).json()['created']
