"""RF1: isolated persisted HTTP projects, unchanged canonical identity/impact rules."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from apps.api.server import create_app
from geometry.pvfield import PVFieldPackingSession
from geometry.pvfield.packing import pack_field
from tests.unit.test_rb_fix_s1_geometry_integrity import Project, MODULE
from tests.unit.test_rb_fix_s4_pv_field_update import _second_field


def patch(p, field=None, **body):
    return p.client.patch(p.url+'/pv-fields/'+(field or p.field_id),json=body)


def definition(p, *, same_size=True, changed_power=True):
    """Fictional UAT derivative, not a vendor fixture or yield benchmark."""
    old=p.bundle()['pinned_components']['modules'][MODULE]
    new=deepcopy(old);rid='rf1-fictional-'+('same' if same_size else 'different')
    new.update(revision_id=rid,module_definition_id=rid)
    if not same_size:new['mechanical'].update(width_m=1.,height_m=2.)
    if changed_power:new['stc']['pmp_w']=600.;new['stc']['nominal_power_w']=600.  # D14: the nameplate is the power basis
    p.service.catalog['modules'][rid]=new
    return rid,new


def own(bundle,field):
    ids={m['module_instance_id'] for m in bundle['scene']['module_instances'] if m['pv_field_id']==field}
    return (next(f for f in bundle['scene']['pv_fields'] if f['pv_field_id']==field),
            [m for m in bundle['scene']['module_instances'] if m['pv_field_id']==field],
            [s for s in bundle['electrical_design']['strings'] if ids.intersection(s['module_instance_ids'])])


def test_two_roofs_refill_each_preserves_other_field_modules_and_strings(tmp_path):
    p=Project(tmp_path);second=_second_field(p);p.executable()
    for target,untouched in ((second,p.field_id),(p.field_id,second)):
        before=p.bundle();saved=deepcopy(own(before,untouched))
        r=patch(p,target,tilt_deg=15,discard_dependent_strings=True);assert r.status_code==200,r.text
        assert own(p.bundle(),untouched)==saved
        assert own(p.bundle(),target)[0]['tilt_deg']==15


@pytest.mark.parametrize('same_size',[True,False])
def test_module_preview_commit_every_string_new_power_pin_and_revisions(tmp_path,same_size,monkeypatch):
    p=Project(tmp_path);second=_second_field(p);p.service.create_strings(p.pid,string_length=6)
    rid,new=definition(p,same_size=same_size);before=p.bundle();raw=p.path.read_bytes();other=deepcopy(own(before,second))
    oldfield,oldmodules,oldstrings=own(before,p.field_id);oldids={m['module_instance_id'] for m in oldmodules}
    calls=[];original=p.service._pin_component
    def pin(*args,**kwargs):calls.append(args[2]);return original(*args,**kwargs)
    monkeypatch.setattr(p.service,'_pin_component',pin)
    r=patch(p,module_definition_revision_id=rid,dry_run=True);assert r.status_code==200,r.text
    preview=r.json();expected=pack_field(before['scene'],{**oldfield,'module_definition_revision_id':rid,
        'module_footprint':new_footprint(new,oldfield)},new)
    assert preview['module_count_after']==len(expected.module_instances)
    assert preview['stc_power_w_after']==600*len(expected.module_instances)
    assert preview['string_ids']==sorted(s['string_id'] for s in oldstrings)
    assert preview['requires_discard_dependent_strings']
    if same_size:
        assert set(preview['layout_impact']['retained_module_ids'])==oldids
        assert preview['layout_impact']['affected_strings']==[]
    assert calls==[] and p.path.read_bytes()==raw and rid not in p.bundle()['pinned_components']['modules']
    r=patch(p,module_definition_revision_id=rid);assert r.status_code==422 and 'discard_dependent_strings' in r.text
    assert calls==[] and p.path.read_bytes()==raw
    r=patch(p,module_definition_revision_id=rid,discard_dependent_strings=True);assert r.status_code==200,r.text
    after=p.bundle();field,modules,strings=own(after,p.field_id)
    assert field['module_definition_revision_id']==rid
    assert all(m['module_definition_revision_id']==rid for m in modules)
    assert rid in after['pinned_components']['modules'] and calls==[rid]
    assert strings==[] and own(after,second)==other
    if same_size:assert {m['module_instance_id'] for m in modules}==oldids
    for key in ('scene','electrical_design'):assert after[key]['revision_number']==before[key]['revision_number']+1


def new_footprint(module,field):
    from geometry.pvfield import ModuleFootprint
    return ModuleFootprint.from_definition(module,field['orientation'],field['tilt_deg']).to_mapping()


def test_rebound_executable_module_restrings_and_simulates(tmp_path):
    p=Project(tmp_path);p.executable();rid,_=definition(p,changed_power=False)
    r=patch(p,module_definition_revision_id=rid,discard_dependent_strings=True);assert r.status_code==200,r.text
    r=p.client.post(p.url+'/strings',json={'string_length':6});assert r.status_code==200,r.text
    inv=p.bundle()['electrical_design']['inverter_instances'][0]['inverter_instance_id']
    p.service.assign_strings(p.pid,inverter_instance_id=inv)
    ready=p.study.execution_readiness(p.pid);assert ready['ready'],ready
    r=p.client.post(p.url+'/simulate',json={});assert r.status_code==200,r.text
    assert r.json()['status'] in ('completed','completed_with_warnings')


def test_same_revision_preview_and_commit_equal_omitted_key(tmp_path):
    p=Project(tmp_path/'first');b=p.bundle()
    other=create_app(store_root=tmp_path/'second');other.state.project_service.store.save(deepcopy(b));client=TestClient(other)
    for body in ({'tilt_deg':15},{'name':'Renamed'}):
        with_key=patch(p,**body,module_definition_revision_id=MODULE,dry_run=True)
        without=client.patch(p.url+'/pv-fields/'+p.field_id,json={**body,'dry_run':True})
        assert with_key.status_code==without.status_code==200 and with_key.json()==without.json()
        r=patch(p,**body,module_definition_revision_id=MODULE);assert r.status_code==200,r.text
        r=client.patch(p.url+'/pv-fields/'+p.field_id,json=body);assert r.status_code==200,r.text
        a=p.bundle();c=other.state.project_service.get_bundle(p.pid)
        assert a['scene']['pv_fields']==c['scene']['pv_fields']
        assert a['scene']['module_instances']==c['scene']['module_instances']
        assert a['electrical_design']==c['electrical_design']


@pytest.mark.parametrize('body',[{'module_definition_revision_id':'missing'}, {'support_surface_id':'other'}])
def test_bad_revision_and_surface_are_422_without_writes(tmp_path,body):
    p=Project(tmp_path);raw=p.path.read_bytes()
    for dry in (True,False):
        r=patch(p,**body,dry_run=dry);assert r.status_code==422,r.text
        assert p.path.read_bytes()==raw


def test_session_module_change_undo_exact_prior_scene(tmp_path):
    p=Project(tmp_path);rid,_=definition(p);before=p.bundle()['scene']
    editor=PVFieldPackingSession(before,p.service._component_definitions(p.bundle(),'modules'))
    editor.update_field(p.field_id,module_definition_revision_id=rid)
    assert editor.undo_depth==1 and editor.undo() and editor.scene==before


def test_non_executable_catalogue_revision_keeps_readiness_blockers(tmp_path):
    p=Project(tmp_path);p.executable();rid='mod-rawibumi-ref-650-r1'
    r=patch(p,module_definition_revision_id=rid,discard_dependent_strings=True);assert r.status_code==200,r.text
    p.service.create_strings(p.pid,string_length=6,allow_shorter_remainder=True)
    inv=p.bundle()['electrical_design']['inverter_instances'][0]['inverter_instance_id'];p.service.assign_strings(p.pid,inverter_instance_id=inv)
    assert not p.study.execution_readiness(p.pid)['ready']
    assert p.client.post(p.url+'/simulate',json={}).status_code==422


def test_shared_string_is_deleted_whole_while_unrelated_other_roof_strings_survive(tmp_path):
    p=Project(tmp_path);second=_second_field(p);p.service.create_strings(p.pid,string_length=7,allow_shorter_remainder=True)
    before=p.bundle();ids={m['module_instance_id'] for m in own(before,p.field_id)[1]};other_ids={m['module_instance_id'] for m in own(before,second)[1]}
    shared=[s for s in before['electrical_design']['strings'] if ids.intersection(s['module_instance_ids']) and other_ids.intersection(s['module_instance_ids'])]
    assert len(shared)==1
    affected=sorted(s['string_id'] for s in before['electrical_design']['strings'] if ids.intersection(s['module_instance_ids']))
    untouched=[s for s in before['electrical_design']['strings'] if not ids.intersection(s['module_instance_ids'])]
    rid,_=definition(p);preview=patch(p,module_definition_revision_id=rid,dry_run=True)
    assert preview.status_code==200 and preview.json()['string_ids']==affected
    r=patch(p,module_definition_revision_id=rid,discard_dependent_strings=True);assert r.status_code==200,r.text
    after=p.bundle();assert after['electrical_design']['strings']==untouched
    assert own(after,second)[:2]==own(before,second)[:2]
