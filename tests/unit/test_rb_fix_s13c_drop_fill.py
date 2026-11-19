"""DEC-58 HTTP regressions and independent physical-slot oracle; disposable stores only."""
from copy import deepcopy
import json
import math

import pytest
from shapely.geometry import box, Point

from geometry.pvfield import PVFieldPackingSession
from geometry.pvfield.drop_fill import drop_fill, reading_order
from geometry.pvfield.packing import pack_field, validate_field_layout
from geometry.pvfield.scene_layout import validate_scene_layout
from tests.unit.test_rb_fix_s1_geometry_integrity import Project
from tests.unit.test_rb_fix_s13b_module_edits import command
from components.design_integration import module_nameplate_w  # D14: the DC nameplate basis


def partial_project(tmp_path):
    p = Project(tmp_path, height=14)
    p.executable()
    selected = [m for m in p.modules() if m['row_index'] < 2 and m['column_index'] < 3]
    targets = [m for m in p.modules() if m['row_index'] in (2, 3) and m['column_index'] < 3]
    r = command(p, 'delete_modules', [m['module_instance_id'] for m in targets], discard_dependent_strings=True)
    assert r.status_code == 200, r.text
    obstacle = targets[1]['transform']
    p.service.add_box_obstacle(p.pid, name='AHU-1', origin_x_m=obstacle['position_x_m']-.2,
        origin_y_m=obstacle['position_y_m']-.2, width_m=.4, depth_m=.4, base_elevation_m=6.1, height_m=2)
    return p, [m['module_instance_id'] for m in selected]


def oracle(bundle, ids, dx, dy):
    scene = bundle['scene']; field = deepcopy(scene['pv_fields'][0]); shape = field['module_footprint']
    # All oracle fixtures are azimuth-zero; construct rectangles independently.
    w, h = shape['plan_projection_width_m'], shape['plan_projection_height_m']
    def rectangle(m, dx=0, dy=0):
        t=m['transform']; x=t['position_x_m']+dx; y=t['position_y_m']+dy
        return box(x-w/2,y-h/2,x+w/2,y+h/2)
    selected=[m for m in scene['module_instances'] if m['module_instance_id'] in ids]
    translated=[rectangle(m,dx,dy) for m in selected]
    margin=max(w,h)/2
    region=box(min(p.bounds[0] for p in translated)-margin,min(p.bounds[1] for p in translated)-margin,
               max(p.bounds[2] for p in translated)+margin,max(p.bounds[3] for p in translated)+margin)
    centre=Point(sum(p.centroid.x for p in translated)/len(ids),sum(p.centroid.y for p in translated)/len(ids))
    for key in ('requested_row_count','requested_modules_per_row'): field['packing_parameters'].pop(key,None)
    slots=pack_field(scene,field,bundle['pinned_components']['modules'][field['module_definition_revision_id']]).module_instances
    occupied=[rectangle(m) for m in scene['module_instances'] if m['module_instance_id'] not in ids]
    candidates=[s for s in slots if region.covers(rectangle(s).centroid) and not any(rectangle(s).intersection(p).area>1e-6 for p in occupied)]
    candidates.sort(key=lambda s: (rectangle(s).centroid.distance(centre)**2,-s['transform']['position_y_m'],s['transform']['position_x_m']))
    order=lambda m:(-round(m['transform']['position_y_m'],3),round(m['transform']['position_x_m'],3),m['module_instance_id'])
    chosen=sorted(candidates[:len(ids)],key=order); selected.sort(key=order)
    return dict(zip([m['module_instance_id'] for m in selected],chosen)),[m['module_instance_id'] for m in selected[len(chosen):]],region


def test_partial_preview_commit_independent_oracle_atomic_strings_indices(tmp_path):
    p,ids=partial_project(tmp_path); before=p.bundle(); raw=p.path.read_bytes()
    expected,removed,_=oracle(before,ids,0,5.2)
    assert 0<len(expected)<6
    body=dict(ids=ids,dx_m=0,dy_m=5.2,on_conflict='fill')
    first=command(p,**body,dry_run=True); assert first.status_code==200, first.text
    preview=first.json(); assert preview==command(p,**body,dry_run=True).json()
    strings=sorted(s['string_id'] for s in before['electrical_design']['strings'] if set(removed).intersection(s['module_instance_ids']))
    assert preview['mode']=='fill' and preview['placed_ids']==list(expected) and preview['removed_ids']==removed
    assert preview['placed_count']==len(expected) and preview['removed_count']==len(removed)
    power=module_nameplate_w(before['pinned_components']['modules'][before['scene']['pv_fields'][0]['module_definition_revision_id']])
    assert preview['stc_power_w_before']==pytest.approx(6*power) and preview['stc_power_w_after']==pytest.approx(power*len(expected))
    assert preview['string_ids']==strings and preview['requires_discard_dependent_strings']
    assert any('obstacle AHU-1' in r['message'] for r in preview['reasons'])
    assert p.path.read_bytes()==raw
    assert command(p,**body).status_code==422; assert p.path.read_bytes()==raw
    r=command(p,**body,discard_dependent_strings=True); assert r.status_code==200,r.text
    after=p.bundle(); actual={m['module_instance_id']:m for m in after['scene']['module_instances']}
    for mid,slot in expected.items():
        assert actual[mid]['transform']==slot['transform']
        for k in ('row_index','column_index','table_index'): assert actual[mid][k]==slot[k]
        for k in ('grid_row_index','grid_column_index'): assert actual[mid]['metadata'][k]==slot['metadata'][k]
        assert actual[mid]['metadata']['manual_edit_kind']=='move_fill'
    assert not set(removed).intersection(actual)
    assert after['electrical_design']['strings']==[s for s in before['electrical_design']['strings'] if s['string_id'] not in strings]
    assert after['scene']['revision_number']==before['scene']['revision_number']+1
    assert after['electrical_design']['revision_number']==before['electrical_design']['revision_number']+1
    assert after['scene']['pv_fields'][0]['layout_status']=='manual'
    assert validate_field_layout(after['scene'],p.field_id)['conflicts']==[]
    assert validate_scene_layout(after['scene'],after['pinned_components']['modules'])['conflicts']==[]
    ready=p.study.execution_readiness(p.pid); assert ready['ready'],ready
    r=p.client.post(p.url+'/simulate',json={}); assert r.status_code==200,r.text
    assert r.json()['status'] in ('completed','completed_with_warnings')


def test_exact_fill_preserves_delta_and_multifield_exact_is_allowed(tmp_path):
    p=Project(tmp_path); p.service.add_surface_rectangle(p.pid,name='Other roof',origin_x_m=20,origin_y_m=0,width_m=8,height_m=8.5,base_elevation_m=6.1)
    support=p.bundle()['scene']['surfaces'][-1]['surface_id'];p.service.create_pv_field(p.pid,name='Other field',**{**p.fill,'support_surface_id':support})
    b=p.bundle(); ids=[next(m['module_instance_id'] for m in b['scene']['module_instances'] if m['pv_field_id']==f['pv_field_id']) for f in b['scene']['pv_fields']]
    r=command(p,ids=ids,dx_m=.005,dy_m=0,on_conflict='fill'); assert r.status_code==200,r.text
    for old,new in zip(b['scene']['module_instances'],p.bundle()['scene']['module_instances']):
        if old['module_instance_id'] in ids: assert new['transform']['position_x_m']==old['transform']['position_x_m']+.005
        else: assert new==old
    raw=p.path.read_bytes();r=command(p,ids=ids,dx_m=1,dy_m=0,on_conflict='fill')
    assert r.status_code==422 and 'one field' in r.text;assert p.path.read_bytes()==raw


def test_default_reject_and_snap_no_removal_preserves_strings(tmp_path):
    p=Project(tmp_path);p.executable();ids=[m['module_instance_id'] for m in p.modules()[:3]];b=p.bundle();raw=p.path.read_bytes()
    r=command(p,ids=ids,dx_m=.3,dy_m=0);assert r.status_code==422,r.text
    assert r.json()['detail']['conflicts'] and r.json()['detail']['reasons'];assert p.path.read_bytes()==raw
    preview=command(p,ids=ids,dx_m=.3,dy_m=0,on_conflict='fill',dry_run=True).json()
    assert preview['placed_count']==3 and preview['removed_count']==0 and not preview['requires_discard_dependent_strings']
    r=command(p,ids=ids,dx_m=.3,dy_m=0,on_conflict='fill');assert r.status_code==200,r.text
    assert p.bundle()['electrical_design']==b['electrical_design']
    assert {m['module_instance_id']:m['transform'] for m in p.modules()}=={m['module_instance_id']:m['transform'] for m in b['scene']['module_instances']}


@pytest.mark.parametrize('dx,dy,code',[(0,2.6,'drop_fill_no_slots'),(24,0,'drop_fill_own_roof')])
def test_refusals_keep_storage(tmp_path,dx,dy,code):
    p=Project(tmp_path)
    if code=='drop_fill_own_roof':
        p.service.add_surface_rectangle(p.pid,name='Other roof',origin_x_m=20,origin_y_m=0,width_m=8,height_m=8.5,base_elevation_m=6.1)
    ids=[m['module_instance_id'] for m in p.modules()[:6]];raw=p.path.read_bytes()
    r=command(p,ids=ids,dx_m=dx,dy_m=dy,on_conflict='fill');assert r.status_code==422,r.text
    assert r.json()['detail']['reasons'][0]['code']==code and r.json()['detail']['conflicts'];assert p.path.read_bytes()==raw


def test_caps_pure_region_pairing_and_no_input_mutation(tmp_path):
    p,ids=partial_project(tmp_path);b=p.bundle();scene=b['scene'];f=scene['pv_fields'][0]
    f['packing_parameters'].update(requested_row_count=1,requested_modules_per_row=1)
    original=deepcopy(b);definition=b['pinned_components']['modules'][f['module_definition_revision_id']]
    plan=drop_fill(scene,f,definition,list(reversed(ids)),0,5.2);expected,removed,region=oracle(b,ids,0,5.2)
    assert plan['region']==list(region.bounds) and plan['margin_m']==max(f['module_footprint']['plan_projection_width_m'],f['module_footprint']['plan_projection_height_m'])/2
    assert plan['placed_ids']==list(expected) and plan['removed_ids']==removed
    assert b==original
    editor=PVFieldPackingSession(scene,b['pinned_components']['modules']);editor.fill_move_modules(ids,0,5.2)
    assert editor.undo_depth==1;assert editor.undo();assert editor.scene==scene


def test_quantized_pairing_and_nearest_tie_order(tmp_path):
    p=Project(tmp_path);b=p.bundle();scene=b['scene'];f=scene['pv_fields'][0];definition=b['pinned_components']['modules'][f['module_definition_revision_id']]
    ids=[m['module_instance_id'] for m in p.modules()[:2]]
    a,c=[next(m for m in scene['module_instances'] if m['module_instance_id']==mid) for mid in ids]
    # The two Y coordinates share the same millimetre bin, so X determines reading order.
    a['transform']['position_y_m']+=.0001;c['transform']['position_y_m']+=.0002
    assert sorted([c,a],key=reading_order)==[a,c]
    plan=drop_fill(scene,f,definition,ids,.577,0)
    expected,removed,_=oracle(b,ids,.577,0)
    assert plan['placed_ids']==list(expected) and plan['removed_ids']==removed
    for mid,slot in expected.items():assert plan['placements'][mid]['transform']==slot['transform']


@pytest.mark.parametrize('code,phrase',[
 ('module_module_overlap','2 modules would overlap other modules'),('module_obstacle_overlap','2 modules would overlap obstacle AHU'),
 ('module_obstacle_setback','closer than 0.3 m to obstacle AHU'),('module_outside_support_or_setback','leave roof Roof or its 0.3 m'),
 ('module_over_hole','cover a hole in Roof'),('module_exclusion_overlap','enter keep-out Keep-out'),('unknown_rule','unknown_rule')])
def test_reason_mapping_groups_both_sides_names_counts(tmp_path,code,phrase):
    p=Project(tmp_path);b=p.bundle();scene=b['scene'];scene['obstacles'].append({'obstacle_id':'obs','name':'AHU'})
    scene['surfaces'].append({'surface_id':'keep','name':'Keep-out'})
    conflicts=[{'code':code,'module_instance_id':mid,'other_id':('keep' if code=='module_exclusion_overlap' else 'obs'),'pv_field_id':p.field_id} for mid in ('a','b')]
    reasons=p.service._module_command_reasons(scene,conflicts+conflicts,['a','b'])
    assert len(reasons)==1 and reasons[0]['count']==2 and phrase in reasons[0]['message']
    if code=='module_module_overlap':
        assert p.service._module_command_reasons(scene,[{'code':code,'module_instance_id':'a','other_id':'b'}],['a','b'])[0]['count']==2


def test_injected_postcheck_failure_is_never_saved(tmp_path,monkeypatch):
    p=Project(tmp_path);raw=p.path.read_bytes();original=p.service._module_move_conflicts;calls=0
    def check(*args):
        nonlocal calls
        calls+=1
        return original(*args) if calls==1 else [{'code':'injected_postcheck','module_instance_id':p.modules()[0]['module_instance_id']}]
    monkeypatch.setattr(p.service,'_module_move_conflicts',check)
    r=command(p,ids=[m['module_instance_id'] for m in p.modules()[:3]],dx_m=.3,dy_m=0,on_conflict='fill')
    assert r.status_code==422 and 'post-check' in r.text;assert p.path.read_bytes()==raw


@pytest.mark.parametrize('extra',[{'on_conflict':'invalid'},{'on_conflict':'fill','dx_m':math.nan},{'module_instance_ids':[]},{'module_instance_ids':['missing']}])
def test_every_422_has_reasons(tmp_path,extra):
    p=Project(tmp_path);data={'command':'move_modules','module_instance_ids':[p.modules()[0]['module_instance_id']],'dx_m':0,'dy_m':0,**extra}
    r=p.client.post(p.url+'/pv-fields/modules/commands',content=json.dumps(data),headers={'Content-Type':'application/json'})
    assert r.status_code==422 and r.json()['detail']['reasons'],r.text


def test_pure_nearest_ties_and_unmoved_modules_from_other_fields(tmp_path, monkeypatch):
    """Exactly equidistant slots choose high Y, then low X, even across fields."""
    from types import SimpleNamespace
    from importlib import import_module
    p=Project(tmp_path);b=p.bundle();scene=b['scene'];field=scene['pv_fields'][0]
    original=deepcopy(scene['module_instances'][0]);original['transform'].update(position_x_m=4.,position_y_m=4.)
    scene['module_instances']=[original]
    slots=[]
    for index,(x,y) in enumerate([(5.,3.),(5.,5.),(3.,3.),(3.,5.)]):
        slot=deepcopy(original);slot['module_instance_id']=f'slot-{index}'
        slot['transform'].update(position_x_m=x,position_y_m=y)
        slots.append(slot)
    monkeypatch.setattr(import_module('geometry.pvfield.drop_fill'),'pack_field',lambda *args:SimpleNamespace(module_instances=slots))
    definition=b['pinned_components']['modules'][field['module_definition_revision_id']]
    # The region includes X=3 and X=5, and all four have identical distance sqrt(2).
    chosen=drop_fill(scene,field,definition,[original['module_instance_id']],0,0)
    assert chosen['placements'][original['module_instance_id']]['transform']==slots[3]['transform']
    other_field=deepcopy(field);other_field['pv_field_id']='other-field';scene['pv_fields'].append(other_field)
    occupied=deepcopy(slots[3]);occupied['module_instance_id']='occupied';occupied['pv_field_id']='other-field'
    scene['module_instances'].append(occupied)
    chosen=drop_fill(scene,field,definition,[original['module_instance_id']],0,0)
    assert chosen['placements'][original['module_instance_id']]['transform']==slots[1]['transform']


def test_failed_fill_save_does_not_publish_scene_or_electrical_revision(tmp_path, monkeypatch):
    p,ids=partial_project(tmp_path);raw=p.path.read_bytes()
    def fail(*args,**kwargs):raise OSError('injected storage failure')
    monkeypatch.setattr(p.service,'_save',fail)
    with pytest.raises(OSError,match='injected storage failure'):
        command(p,ids=ids,dx_m=0,dy_m=5.2,on_conflict='fill',discard_dependent_strings=True)
    assert p.path.read_bytes()==raw
