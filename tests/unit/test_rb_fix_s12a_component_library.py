"""S12a: real HTTP, disposable libraries; all new byte variants are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
from itertools import product
import json
from pathlib import Path
import shutil

from fastapi.testclient import TestClient
import pytest

from apps.api.server import create_app
from apps.api.catalog import catalog_summaries, load_reference_catalog
from apps.api.component_library import ComponentLibraryStore, definition_readiness, preview_parameters
from apps.api.execution_readiness import phase5_module_definition_readiness, phase5_inverter_definition_readiness
from components.candidates import build_module_candidate
from components.pan import parse_pan_bytes, map_pan
from validation.engineering.electrical import inverter_design_capability_issues

ROOT = Path(__file__).resolve().parents[2]
PAN = (ROOT/'tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN').read_bytes()
OND = (ROOT/'tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND').read_bytes()
SYNTHETIC_OND = (ROOT/'tests/fixtures/panond/synthetic_inverter.ond').read_bytes()


@pytest.fixture
def project_api(tmp_path):
    app=create_app(store_root=tmp_path/'projects', library_root=tmp_path/'library')
    with TestClient(app) as client:
        yield app,client,tmp_path/'library'


def upload(client, data=PAN, filename='module.PAN', dry=False):
    return client.post('/api/component-library/imports',params={'filename':filename,'dry_run':str(dry).lower()},content=data,headers={'Content-Type':'application/octet-stream'})


def commit(client,data=PAN,filename='module.PAN'):
    r=upload(client,data,filename);assert r.status_code==200,r.text;return r.json()['entry']


def tree(root):
    return {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_preview_independent_canonical_paths_and_zero_writes(project_api):
    app,c,root=project_api
    r=upload(c,dry=True);assert r.status_code==200,r.text
    preview=r.json();assert preview['schema_ready'] and preview['simulation_ready']
    candidate=build_module_candidate(map_pan(parse_pan_bytes(PAN)),candidate_id='independent',module_definition_id='independent',revision_id='independent',source_id='source')
    d=candidate['canonical_data'];expected={k:d['stc'][k] for k in ('pmp_w','voc_v','isc_a','vmp_v','imp_a')}
    expected.update(width_m=d['mechanical']['width_m'],height_m=d['mechanical']['height_m'],cell_count=d['cell_architecture'].get('physical_cell_count'),gamma_pmp_pct_per_c=100*d['temperature_coefficients']['gamma_pmp_per_c']/d['stc']['pmp_w'],mu_voc_v_per_c=d['temperature_coefficients']['beta_voc_per_c'],technology=d['technology'])
    assert preview['parameters']==expected
    assert preview['parameters']['gamma_pmp_pct_per_c']==pytest.approx(-.345)
    assert not root.exists()
    assert c.get('/api/component-library').json()==[] and not root.exists()


def test_commit_persists_source_identity_and_second_instance(project_api,tmp_path):
    app,c,root=project_api;e=commit(c);rid=e['revision_id']
    entries=c.get('/api/component-library').json();assert len(entries)==1
    stored=entries[0];meta=stored['library'];assert meta['source_encoding']=='utf-8' and meta['revision_number']==1
    assert meta['source_sha256']==hashlib.sha256(PAN).hexdigest()
    assert (root/'sources/sha256'/f"{meta['source_sha256']}.pan").read_bytes()==PAN
    assert len(tree(root))==2
    assert rid.startswith('lib-mod-jinkosolar-jkm550m-72hl4-v-') and rid.endswith('-r1')
    item=next(x for x in c.get('/api/catalog').json()['modules'] if x['revision_id']==rid)
    assert item['source']=='library' and not item['synthetic_reference'] and item['simulation_ready']
    other=create_app(store_root=tmp_path/'other-projects',library_root=root)
    assert rid in other.state.project_service.catalog['modules']
    assert TestClient(other).get('/api/component-library').json()==entries


def test_duplicate_and_new_revision_preserve_every_old_byte(project_api):
    _,c,root=project_api;e=commit(c);before=tree(root)
    p=upload(c,dry=True).json();assert p['duplicate_of']==e['revision_id']
    r=upload(c);assert r.json()['created'] is False and r.json()['entry']['revision_id']==e['revision_id'];assert tree(root)==before
    # Fictional dimension edit, not a manufacturer source revision.
    variant=PAN.replace(b'Width=1.134',b'Width=1.200');assert variant!=PAN
    second=commit(c,variant);assert second['revision_id']==e['revision_id'][:-1]+'2'
    assert all(tree(root)[name]==data for name,data in before.items())


def test_huawei_layout_only_shared_rules_and_no_limit_invention(project_api):
    app,c,root=project_api;e=commit(c,OND,'Huawei.OND');assert e['schema_ready'] and not e['simulation_ready']
    codes={f['rule_id'] for f in e['readiness_findings']}
    assert {'INVERTER_BASIC_DESIGN_READY_FALSE','INVERTER_MPPT_DESIGN_READY_FALSE'}<=codes
    assert {'mppt_operating_current_missing', 'basic_design_incomplete_due_to_mppt'} <= {r['code'] for r in e['reasons']}
    assert not any('frequency' in r['message'] for r in e['reasons'])
    frequency_warning=next(f for f in e['findings'] if f['rule_id']=='INVERTER_AC_FREQUENCY_NOT_SPECIFIED')
    assert frequency_warning['severity']=='warning' and frequency_warning['category']=='ac'
    params=e['parameters'];assert params['max_dc_power_w'] is None and params['max_input_current_a'] is None and params['mppt_max_operating_current_a'] is None
    d=app.state.project_service.catalog['inverters'][e['revision_id']]
    assert params=={'nominal_ac_power_w':d['ac_limits']['nominal_ac_power_w'],'max_dc_power_w':d['dc_limits'].get('max_dc_power_w'),'mppt_count':d['mppt_template']['count'],'mppt_v_min':d['mppt_template']['min_operating_voltage_v'],'mppt_v_max':d['mppt_template']['max_operating_voltage_v'],'max_dc_voltage_v':d['dc_limits']['max_dc_voltage_v'],'max_input_current_a':d['dc_limits'].get('max_dc_current_a'),'mppt_max_operating_current_a':d['mppt_template'].get('max_operating_current_a'),'efficiency_fraction':d['efficiency_model']['reference_metrics']['european_efficiency_fraction'],'efficiency_metric':'european'}
    assert d['capability_flags']['basic_design_ready'] is False
    assert phase5_inverter_definition_readiness(d)['ready'] # narrower helper remains unchanged
    assert not definition_readiness('inverters',d)['ready']
    before=tree(root);r=upload(c,SYNTHETIC_OND,'synthetic.ond');assert r.status_code==422 and r.json()['detail']['code']=='component_schema_incomplete';assert tree(root)==before


@pytest.mark.parametrize('raw,filename,status,code',[(b'\xff\x00\x01','bad.pan',422,'legacy_binary_pan_unsupported'),(b'pvModule;SYNTHETIC LEGACY\x00\xff','old.pan',422,'legacy_binary_pan_unsupported'),(b'\x00\x01','bad.OND',422,'legacy_binary_pan_unsupported'),(b'text','file.txt',422,'unsupported_component_format'),(b'x'*(2*1024*1024+1),'large.pan',413,'component_file_too_large')])
def test_refusals_structured_no_writes(project_api,raw,filename,status,code):
    _,c,root=project_api;r=upload(c,raw,filename);assert r.status_code==status,r.text
    assert r.json()['detail']['code']==code and r.json()['detail']['message'];assert not root.exists()


@pytest.mark.parametrize('encoding',['utf-8-sig','cp1252'])
def test_synthetic_encodings_original_bytes_and_duplicate(project_api,encoding):
    _,c,root=project_api
    # Generated degree-sign comment only; no private/user file is copied.
    text=OND.decode().replace('PVObject_=pvGInverter','PVObject_=pvGInverter\n  Comment=Synthetic 25° test')
    raw=text.encode(encoding);e=commit(c,raw,'encoding.ond');rid=e['revision_id']
    entry=next(x for x in c.get('/api/component-library').json() if x['definition']['revision_id']==rid)
    expected='cp1252' if encoding=='cp1252' else 'utf-8';assert entry['library']['source_encoding']==expected
    assert (root/'sources/sha256'/f"{hashlib.sha256(raw).hexdigest()}.ond").read_bytes()==raw
    before=tree(root);assert upload(c,raw,'renamed.ond').json()['created'] is False;assert tree(root)==before
    assert e['parameters']['nominal_ac_power_w']==100000 and not e['simulation_ready']


def executable(app,c,module,inverter):
    r=c.post('/api/projects',json={'name':'S12a synthetic test project','latitude_deg':-6.2,'longitude_deg':106.8,'elevation_m':25,'timezone':'Asia/Jakarta'});assert r.status_code==201
    pid=r.json()['bundle']['project']['project_id'];url=f'/api/projects/{pid}'
    r=c.post(url+'/surfaces/rectangle',json={'name':'Roof','width_m':1+18*1.154-.01,'height_m':3.45,'base_elevation_m':6.1});assert r.status_code==200
    sid=r.json()['bundle']['scene']['surfaces'][0]['surface_id']
    for endpoint,body in [('/pv-fields',{'name':'Library array','support_surface_id':sid,'module_definition_revision_id':module,'tilt_deg':10,'row_pitch_m':3.2,'perimeter_setback_m':.5}),('/inverters',{'name':'INV','inverter_definition_revision_id':inverter}),('/strings',{'string_length':18})]:
        r=c.post(url+endpoint,json=body);assert r.status_code==200,r.text
    iid=r.json()['bundle']['electrical_design']['inverter_instances'][0]['inverter_instance_id'];r=c.post(url+'/assignments',json={'inverter_instance_id':iid});assert r.status_code==200,r.text
    app.state.study_service.acquire_weather(pid,source_id='open_meteo_archive_era5',start_date='2025-01-01',end_date='2025-01-01',raw_response=(ROOT/'tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json').read_bytes())
    return pid,url


def simulate(c,url):
    ready=c.get(url+'/execution-readiness');assert ready.status_code==200 and ready.json()['ready'],ready.text
    r=c.post(url+'/simulate',json={});assert r.status_code==200,r.text;assert r.json()['status'] in ('completed','completed_with_warnings');return r.json()


def test_simulate_hide_unhide_new_revision_and_library_removal_preserve_pins(project_api,tmp_path):
    app,c,root=project_api;e=commit(c);rid=e['revision_id'];pid,url=executable(app,c,rid,'inv-rawibumi-uat-150k-r1')
    run=simulate(c,url);assert run['model_manifest']['near_shading_runtime']['electrical_shading_scope']=='not_modeled'
    before=deepcopy(c.get(url).json()['bundle']['pinned_components']['modules'][rid]);assert before['revision_id']==rid
    assert c.post(f'/api/component-library/{rid}/hide').status_code==200
    assert rid not in [m['revision_id'] for m in c.get('/api/catalog').json()['modules']]
    assert c.get('/api/component-library').json()==[]
    assert c.get('/api/component-library?include_hidden=true').json()[0]['library']['hidden']
    assert rid in app.state.project_service.catalog['modules']
    local=next(m for m in c.get(url).json()['catalog']['modules'] if m['revision_id']==rid)
    assert local['pmp_w']==before['stc']['pmp_w'] and local['source']=='library' and local['simulation_ready']
    simulate(c,url)
    assert c.post(f'/api/component-library/{rid}/unhide').status_code==200
    assert rid in [m['revision_id'] for m in c.get('/api/catalog').json()['modules']]
    commit(c,PAN.replace(b'Width=1.134',b'Width=1.200'))
    assert c.get(url).json()['bundle']['pinned_components']['modules'][rid]==before
    shutil.rmtree(root) # disposable tmp_path library only
    other=create_app(store_root=tmp_path/'projects',library_root=root)
    with TestClient(other) as client:
        assert client.get(url).status_code==200
        assert client.get(url).json()['bundle']['pinned_components']['modules'][rid]==before
        local=next(m for m in client.get(url).json()['catalog']['modules'] if m['revision_id']==rid)
        assert local['pmp_w']==before['stc']['pmp_w'] and local['source']=='library'
        assert rid not in [m['revision_id'] for m in client.get('/api/catalog').json()['modules']]
        simulate(client,url)
    assert not root.exists()


def test_library_huawei_cannot_bypass_design_gate_or_save_failed_run(project_api):
    app,c,_=project_api;m=commit(c);inv=commit(c,OND,'Huawei.ond');pid,url=executable(app,c,m['revision_id'],inv['revision_id'])
    ready=c.get(url+'/execution-readiness').json();assert not ready['ready']
    assert {'INVERTER_BASIC_DESIGN_READY_FALSE','INVERTER_MPPT_DESIGN_READY_FALSE'}<={f['rule_id'] for f in ready['findings']}
    r=c.post(url+'/simulate',json={});assert r.status_code==422
    b=c.get(url).json()['bundle'];assert b['simulation_runs']==[]
    assert inv['revision_id'] in b['pinned_components']['inverters']
    assert c.post(f"/api/component-library/{inv['revision_id']}/hide").status_code==200
    assert inv['revision_id'] not in [i['revision_id'] for i in c.get('/api/catalog').json()['inverters']]
    local=next(i for i in c.get(url).json()['catalog']['inverters'] if i['revision_id']==inv['revision_id'])
    assert local['model']=='SUN2000-100KTL-M1' and local['nominal_ac_power_w']==100000 and not local['simulation_ready']
    other=c.post('/api/projects',json={'name':'Other project','latitude_deg':-6.2,'longitude_deg':106.8,'timezone':'Asia/Jakarta'}).json()
    assert inv['revision_id'] not in [i['revision_id'] for i in other['catalog']['inverters']]


def test_reference_catalogue_unchanged_except_additive_source(project_api):
    _,c,_=project_api
    baseline=catalog_summaries();commit(c);actual=c.get('/api/catalog').json()
    for kind,items in baseline.items():
        if kind=='module_topologies':assert actual[kind]==items;continue
        refs=[x for x in actual[kind] if x['source']=='reference'];assert refs==items
        assert all(x['source']=='reference' for x in items)
    assert set(load_reference_catalog()['modules'])=={x['revision_id'] for x in baseline['modules']}


def test_concurrent_duplicate_import_and_library_root_default(tmp_path):
    app=create_app(store_root=tmp_path/'projects');store=app.state.project_service.library;assert store.root==tmp_path/'component-library'
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:store.import_bytes('same.pan',PAN),range(3)))
    assert sum(r['created'] for r in results)==1 and len(store.entries())==1
    assert len(tree(store.root))==2


def test_shared_helper_exact_flag_semantics_and_null_parameter_variants():
    missing=object()
    for values in product((missing,None,False,True),repeat=3):
        caps={k:v for k,v in zip(('basic_design_ready','mppt_design_ready','basic_yield_ready'),values) if v is not missing}
        issues=inverter_design_capability_issues({'capability_flags':caps})
        assert [i['rule_id'] for i in issues]==[f'INVERTER_{k.upper()}_FALSE' for k in ('basic_design_ready','mppt_design_ready') if caps.get(k) is False]+(['INVERTER_BASIC_SIMULATION_CAPABILITY_UNAVAILABLE'] if caps.get('basic_yield_ready') is False else [])
        assert all(i['severity']==('blocking_error' if i['classification']=='INVALID' else 'warning') for i in issues)
    for value in (missing,None,False,True):
        caps={} if value is missing else {'detailed_sdm_ready':value}
        r=phase5_module_definition_readiness({'revision_id':'module','capability_flags':caps});assert r['ready']==(value is True)
    d={'temperature_coefficients':{'gamma_pmp_per_c':-.003,'coefficient_basis':'relative'}}
    assert preview_parameters('modules',d)['gamma_pmp_pct_per_c']==pytest.approx(-.3)
    d['temperature_coefficients']['coefficient_basis']='manufacturer_defined';assert preview_parameters('modules',d)['gamma_pmp_pct_per_c'] is None
    inv={'efficiency_model':{'reference_metrics':{'max_efficiency_fraction':.99},'curves':[{'points':[{'efficiency_fraction':1}]}]}}
    assert preview_parameters('inverters',inv)['efficiency_fraction']==.99 and preview_parameters('inverters',inv)['efficiency_metric']=='maximum'


def test_malformed_text_preview_and_missing_hide_are_structured(project_api):
    _,c,root=project_api;r=upload(c,b'PVObject_=pvGInverter\nEnd of PVObject pvGInverter\n','empty.ond',True)
    assert r.status_code==200 and not r.json()['schema_ready'],r.text
    r=upload(c,b'PVObject_=pvGInverter\nEnd of PVObject pvGInverter\n','empty.ond');assert r.status_code==422
    assert c.post('/api/component-library/not-a-revision/hide').json()['detail']['code']=='component_revision_not_found'
    assert not root.exists()


@pytest.mark.parametrize('path,method',[
    ('/api/component-library/imports','post'),
    ('/api/component-library/imports?filename=synthetic.pan&dry_run=invalid','post'),
    ('/api/component-library?include_hidden=invalid','get'),
])
def test_library_query_validation_uses_its_structured_error_contract(project_api,path,method):
    _,client,root=project_api
    response=getattr(client,method)(path)
    assert response.status_code==422
    detail=response.json()['detail']
    assert detail['code']=='invalid_component_library_request' and detail['message']
    assert isinstance(detail['errors'],list)
    assert not root.exists()
