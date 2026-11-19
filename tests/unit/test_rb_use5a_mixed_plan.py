"""Mixed plan partition, conservation and legacy identity."""
from tests.unit._availability import missing_commit
from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator
from engine.simulation.execution_groups import build_simulation_execution_plan, _legacy_execution_plan, detailed_inverter_scope_finding
from tests.unit.test_phase52_execution_groups import _scene, _electrical, _compiled, _validate, _registry, ROOT


def test_unmixed_plan_bytes_and_hash_unchanged():
    for east in (False,True):
        for tolerance in (None,.25,1.):
            scene, electrical = _scene(east_second=east), _electrical()
            if tolerance is not None:
                electrical['orientation_policy']={'normal_angle_tolerance_deg':tolerance}
            kw={'compiled_shading_geometry':_compiled()}
            assert json.dumps(build_simulation_execution_plan(scene,electrical,**kw)) == json.dumps(_legacy_execution_plan(scene,electrical,**kw))


def test_chain_partition_is_complete_linkage_in_module_order():
    scene, electrical = _scene(), _electrical(both_strings_same_mppt=True)
    third = deepcopy(scene['pv_fields'][0]);third.update(pv_field_id='field-c',tilt_deg=21.5)
    scene['pv_fields'].append(third)
    scene['pv_fields'][1]['tilt_deg']=20.75
    scene['module_instances'][3]['pv_field_id']='field-c'
    electrical['orientation_policy']={'normal_angle_tolerance_deg':1.}
    plan=build_simulation_execution_plan(scene,electrical,compiled_shading_geometry=_compiled())
    assert plan['execution_class']=='mixed_orientation_coupled'
    assert [c['module_instance_ids'] for c in plan['mixed_orientation']['classes']]==[
        ['module-a1','module-a2','module-b1'],['module-b2']]
    assert plan['groups']==[] and plan['group_count']==0
    assert sum(sum(s['composition'].values()) for m in plan['mixed_orientation']['mppts'] for s in m['strings'])==4
    _validate(plan)


@pytest.mark.parametrize('kind',['type','length'])
def test_unsupported_mixes_are_refused_for_use5c(kind):
    scene,electrical=_scene(east_second=True),_electrical(both_strings_same_mppt=True)
    if kind=='type':scene['module_instances'][-1]['module_definition_revision_id']='other'
    else:electrical['strings'][1]['module_instance_ids'].pop()
    plan=build_simulation_execution_plan(scene,electrical)
    assert 'mixed_orientation' not in plan
    assert any('USE5c' in f['message'] and f['severity']=='error' for f in plan['findings'])


@pytest.mark.parametrize('kind', ['orientation', 'length'])
def test_detailed_plan_and_inverter_scope_bytes_match_273cd92(kind):
    if reason := missing_commit('273cd92'):
        pytest.skip(reason)
    import subprocess, types
    reference = types.ModuleType('engine.simulation._use5_head_reference')
    reference.__package__ = 'engine.simulation'
    source = subprocess.check_output(['git', '--no-optional-locks', 'show', '273cd92:engine/simulation/execution_groups.py'], cwd=ROOT, text=True)
    exec(compile(source, '273cd92:engine/simulation/execution_groups.py', 'exec'), reference.__dict__)
    scene, electrical = _scene(east_second=True), _electrical(both_strings_same_mppt=True)
    if kind == 'length':
        electrical['strings'][1]['module_instance_ids'].pop()
    actual = build_simulation_execution_plan(scene, electrical, detailed=True)
    assert json.dumps(actual).encode() == json.dumps(reference.build_simulation_execution_plan(scene, electrical)).encode()
    assert 'mixed_orientation' not in actual
    for multiple in (False, True):
        if multiple:
            electrical['inverter_instances'].append({**electrical['inverter_instances'][0], 'inverter_instance_id': 'extra-inverter', 'name': 'Extra inverter'})
        assert json.dumps(detailed_inverter_scope_finding(scene, electrical)).encode() == json.dumps(reference.detailed_inverter_scope_finding(scene, electrical)).encode()


def test_successful_policy_merges_stay_byte_identical():
    scene=_scene(east_second=True)
    scene['pv_fields'][1].update(tilt_deg=20.5,azimuth_deg=0.)
    electrical=_electrical(both_strings_same_mppt=True)
    electrical['orientation_policy']={'normal_angle_tolerance_deg':1.}
    actual=build_simulation_execution_plan(scene,electrical)
    assert actual==_legacy_execution_plan(scene,electrical)
    assert 'mixed_orientation' not in actual
    _validate(actual)
