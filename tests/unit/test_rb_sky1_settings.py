"""Versioned browser sampling settings and immutable canonical run evidence."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from engine.simulation.shading_accuracy import (
    default_shading_accuracy, resolve_shading_accuracy, patch_shading_accuracy,
    configure_browser_shading_accuracy, run_shading_accuracy_snapshot,
)
from tests.unit.test_rb_fix_s2_honest_preflight import Project


@pytest.mark.parametrize('level,az,bands',[('standard',48,12),('high',72,18)])
def test_preset_shape_sources_and_defensive_copies(level,az,bands):
    raw=patch_shading_accuracy(default_shading_accuracy(),{'overrides':{'level':level}})
    before=deepcopy(raw);r=resolve_shading_accuracy(raw)
    assert r['level']==level and r['source']=='project_override'
    assert r['sky_dome_resolution']=={'azimuth_sectors':az,'elevation_bands':bands,'horizon_azimuth_sectors':az,'horizon_elevation_bands':1,'horizon_band_elevation_deg':10.}
    assert r['ground_dome_resolution']=={'azimuth_sectors':az,'depression_bands':bands}
    assert r['ground_source']=='preset_mapping'
    r['sky_dome_resolution']['azimuth_sectors']=-1
    assert raw==before and resolve_shading_accuracy(raw)['sky_dome_resolution']['azimuth_sectors']==az


@pytest.mark.parametrize('raw',[None,{},[],{'schema_version':'1','defaults_id':'shading_accuracy.v1','overrides':{}},
 {'schema_version':'0.1','defaults_id':'unknown','overrides':{}},
 {'schema_version':'0.1','defaults_id':'shading_accuracy.v1','overrides':{'level':None}},
 {'schema_version':'0.1','defaults_id':'shading_accuracy.v1','overrides':{'level':True}},
 {'schema_version':'0.1','defaults_id':'shading_accuracy.v1','overrides':{'level':'legacy'}},
 {'schema_version':'0.1','defaults_id':'shading_accuracy.v1','overrides':{'sectors':12}}])
def test_invalid_stored_contract_refuses(raw):
    with pytest.raises(ValueError):resolve_shading_accuracy(raw)


@pytest.mark.parametrize('patch',[None,[],{}, {'level':'high'},{'overrides':{'level':'High'}},{'overrides':{'level':12}},
 {'overrides':{'extra':True}},{'reset_to_recommended_defaults':False},{'reset_to_recommended_defaults':True,'overrides':{}},
 {'overrides':{},'extra':0}])
def test_invalid_patch_is_422_and_does_not_write(tmp_path,patch):
    p=Project(tmp_path,18,weather=False);before=p.path.read_bytes()
    r=p.client.patch(p.url+'/shading-accuracy',json=patch)
    assert r.status_code==422,r.text
    assert p.path.read_bytes()==before


def test_legacy_roundtrip_reload_reset_noop_and_project_revision(tmp_path):
    p=Project(tmp_path,18,weather=False);b=p.bundle();b.pop('shading_accuracy',None);p.service.store.save(b)
    before=p.path.read_bytes();revision=b['project']['project_revision']['revision_number']
    view=p.client.get(p.url).json();assert view['resolved_shading_accuracy']['level']=='standard'
    assert view['resolved_shading_accuracy']['source']=='recommended_defaults' and p.path.read_bytes()==before
    assert p.client.patch(p.url+'/shading-accuracy',json={'reset_to_recommended_defaults':True}).status_code==200
    assert p.path.read_bytes()==before
    high=p.client.patch(p.url+'/shading-accuracy',json={'overrides':{'level':'high'}})
    assert high.status_code==200,high.text
    assert high.json()['bundle']['project']['project_revision']['revision_number']==revision+1
    saved=p.path.read_bytes();assert p.client.get(p.url).json()['resolved_shading_accuracy']['level']=='high'
    assert p.client.patch(p.url+'/shading-accuracy',json={'overrides':{'level':'high'}}).status_code==200
    assert p.path.read_bytes()==saved
    assert p.client.patch(p.url+'/shading-accuracy',json={'overrides':{'level':None}}).status_code==200
    assert p.client.get(p.url).json()['resolved_shading_accuracy']['source']=='recommended_defaults'
    default=p.path.read_bytes()
    assert p.client.patch(p.url+'/shading-accuracy',json={'reset_to_recommended_defaults':True}).status_code==200
    assert p.path.read_bytes()==default


def test_explicit_standard_is_provenance_edit_and_reset_restores_source(tmp_path):
    p=Project(tmp_path,18,weather=False);before=p.path.read_bytes()
    r=p.client.patch(p.url+'/shading-accuracy',json={'overrides':{'level':'standard'}})
    assert r.status_code==200 and r.json()['resolved_shading_accuracy']['source']=='project_override'
    assert p.path.read_bytes()!=before
    assert p.client.patch(p.url+'/shading-accuracy',json={'reset_to_recommended_defaults':True}).json()['resolved_shading_accuracy']['source']=='recommended_defaults'


def test_explicit_engine_configuration_has_no_new_snapshot_or_mutation():
    config={'numerical_options':{},'shading_configuration':{'sky_dome_resolution':{'azimuth_sectors':12,'elevation_bands':3}}}
    before=deepcopy(config);assert run_shading_accuracy_snapshot(config) is None and config==before
    configure_browser_shading_accuracy(config,default_shading_accuracy())
    assert run_shading_accuracy_snapshot(config)['level']=='standard'
    config['shading_configuration']['sky_dome_resolution']['azimuth_sectors']=12
    with pytest.raises(ValueError,match='disagrees'):run_shading_accuracy_snapshot(config)


def test_defaults_match_builder_and_every_run_keeps_its_own_choice(tmp_path):
    p=Project(tmp_path,18);b=p.bundle();b.pop('shading_accuracy',None);p.service.store.save(b)
    defaults=p.client.get('/api/simulation-defaults').json()['shading_accuracy']
    assert defaults['level']=='standard' and defaults['ground_dome_resolution']=={'azimuth_sectors':48,'depression_bands':12}
    first=p.client.post(p.url+'/simulate',json={});assert first.status_code==200,first.text
    standard=first.json();assert standard['status']!='failed',standard
    assert standard['resolved_shading_accuracy']==defaults
    first_path=p.study.run_root/p.pid/standard['simulation_run_id']/'simulation-run.json';first_bytes=first_path.read_bytes()
    assert p.client.patch(p.url+'/shading-accuracy',json={'overrides':{'level':'high'}}).status_code==200
    second=p.client.post(p.url+'/simulate',json={});assert second.status_code==200,second.text
    high=second.json();assert high['status']!='failed',high
    assert high['resolved_shading_accuracy']['level']=='high'
    root=p.study.run_root/p.pid/high['simulation_run_id']
    run=json.loads((root/'simulation-run.json').read_text());manifest=json.loads((root/'reproducibility-manifest.json').read_text())
    snapshot=run['resolved_shading_accuracy'];assert snapshot==high['resolved_shading_accuracy']==manifest['model_manifest']['resolved_shading_accuracy']
    assert manifest['shading_configuration']['sky_dome_resolution']==snapshot['sky_dome_resolution']
    assert manifest['shading_configuration']['ground_dome_resolution']==snapshot['ground_dome_resolution']
    assert p.client.patch(p.url+'/shading-accuracy',json={'reset_to_recommended_defaults':True}).status_code==200
    old=p.client.get(p.url+'/runs').json();assert [r['resolved_shading_accuracy']['level'] for r in old]==['standard','high']
    assert first_path.read_bytes()==first_bytes


@pytest.mark.parametrize('policy',['fail_closed','explicit_lower_fidelity'])
def test_corrupt_settings_block_readiness_without_weather_and_fallback(tmp_path,policy):
    p=Project(tmp_path,18,weather=False);b=p.bundle();b['shading_accuracy']['overrides']['level']='legacy';p.service.store.save(b)
    for params in ({},{'requested_fidelity':'level_2_bypass_substring','fallback_policy':policy}):
        r=p.client.get(p.url+'/execution-readiness',params=params)
        assert r.status_code==200,r.text
        assert not r.json()['ready']
        assert any(f['rule_id']=='SHADING_ACCURACY_INVALID' for f in r.json()['findings'])
        if params:assert r.json()['execution_class']=='blocked_detailed_inputs'
