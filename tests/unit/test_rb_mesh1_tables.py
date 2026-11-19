"""Hand-computed front-view anchor and explicit module-placement oracles."""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from geometry.pvfield.explicit import create_explicit_field, explicit_module_geometry, table_rectangle
from geometry.scene.surface_plane import synchronize_scene_module_center_z
from geometry.scene3d import generate_scene3d
from geometry.shading import compile_shading_geometry, calculate_direct_beam_shadow
from shading.electrical.region_map import derive_electrical_region_map
from tests.unit.test_phase51_compiled_shading_geometry import _scene, _registry, MODULE
from tests.unit.test_phase63_electrical_regions import _topology


# Deliberately independent of the implementation's anchor lookup.
ORACLE_ANCHORS = {
    "lower_left": (0.,0.), "lower_center": (.5,0.), "lower_right": (1.,0.),
    "left_center": (0.,.5), "center": (.5,.5), "right_center": (1.,.5),
    "upper_left": (0.,1.), "upper_center": (.5,1.), "upper_right": (1.,1.),
}


def base_scene():
    s=_scene();s['module_instances']=[];s['pv_fields']=[];s['obstacles']=[]
    return s


def table(**changes):
    return {'table_id':'table-a','anchor_xyz_m':[10.,20.,10.],'anchor_convention':'center','tilt_deg':25.,'azimuth_deg':180.,'module_definition_revision_id':'module-r1','modules_across':1,'modules_up':1,'module_orientation':'portrait','module_gap_across_m':.02,'module_gap_up_m':.03,**changes}


def definition():
    d=deepcopy(MODULE);d['revision_id']='module-r1';d['mechanical'].update(width_m=2.,height_m=4.)
    return d


def create(scene=None,tables=None):
    scene=scene or base_scene()
    f,modules=create_explicit_field(scene,{'module-r1':definition()},pv_field_id='explicit-f',name='Explicit tables',tables=tables or [table()],provenance={'source_id':'synthetic'})
    scene=deepcopy(scene);scene['pv_fields'].append(f);scene['module_instances'].extend(modules)
    return scene,f,modules


@pytest.mark.parametrize('anchor',list(ORACLE_ANCHORS))
@pytest.mark.parametrize('orientation',['portrait','landscape'])
def test_all_front_view_anchors_have_hand_computed_world_corners(anchor,orientation):
    t=table(anchor_convention=anchor,module_orientation=orientation,azimuth_deg=123.,tilt_deg=35.)
    s,f,modules=create(tables=[t]);generated=generate_scene3d(s)['modules'][0]
    w,h=(2.,4.) if orientation=='portrait' else (4.,2.)
    a,b=ORACLE_ANCHORS[anchor];az=math.radians(123);tilt=math.radians(35)
    right=(-math.cos(az),math.sin(az),0)
    up=(-math.sin(az)*math.cos(tilt),-math.cos(az)*math.cos(tilt),math.sin(tilt))
    expected=[[t['anchor_xyz_m'][i]+(x-a)*w*right[i]+(y-b)*h*up[i] for i in range(3)] for x,y in ((0,1),(1,1),(1,0),(0,0))]
    for actual,point in zip(table_rectangle(f['tables'][0]),expected):assert actual==pytest.approx(point,abs=1e-12)
    # Internal module corners intentionally keep the old order, not the new front-label order.
    for point in expected:assert min(math.dist(point,p) for p in generated['corners_3d'])<1e-12
    assert generated['support_surface_id'] is None and generated['center_z_residual_m']==0
    compiled=compile_shading_geometry(s)
    mapped=derive_electrical_region_map(compiled,_topology(),module_instance_id=modules[0]['module_instance_id'])
    assert mapped['mapped_region_area_m2']==pytest.approx(8,abs=1e-12)


def test_front_column_axis_is_east_for_south_facing_and_north_for_east_facing():
    for az,axis in ((180.,0),(90.,1)):
        s,f,modules=create(tables=[table(anchor_convention='lower_left',anchor_xyz_m=[0,0,10],azimuth_deg=az,modules_across=2)])
        bycol=sorted(modules,key=lambda m:m['column_index'])
        assert bycol[0]['transform'][('position_x_m','position_y_m')[axis]]>0
        assert bycol[1]['transform'][('position_x_m','position_y_m')[axis]]>bycol[0]['transform'][('position_x_m','position_y_m')[axis]]
        t=f['tables'][0];corners=table_rectangle(t)
        assert corners[1][axis]>corners[0][axis]


def test_grid_gaps_unused_margins_and_identity_are_deterministic():
    t=table(modules_across=2,modules_up=2,rectangle={'width_m':6.,'height_m':10.})
    s,f,modules=create(tables=[t,table(table_id='table-b',anchor_xyz_m=[30,30,10])])
    second,ff,mm=create(tables=[table(table_id='table-b',anchor_xyz_m=[30,30,10]),t])
    assert ff==f and mm==modules and len(modules)==5
    selected=sorted((m for m in modules if m['table_id']=='table-a'),key=lambda m:(m['row_index'],m['column_index']))
    assert selected[1]['transform']['position_x_m']-selected[0]['transform']['position_x_m']==pytest.approx(2.02)
    compiled=compile_shading_geometry(s)
    assert len([o for o in compiled['occluders'] if o['source_entity_type']=='module_instance'])==5
    before=deepcopy(s);assert synchronize_scene_module_center_z(s)==[];assert s==before


@pytest.mark.parametrize('changes,reason',[
    ({'rectangle':{'width_m':1.999,'height_m':4.}},'occupancy'),
    ({'tilt_deg':91},'tilt'),({'azimuth_deg':360},'azimuth'),
    ({'modules_up':True},'counts'),({'modules_across':50000,'modules_up':2},'50000'),
    ({'module_gap_up_m':-.1},'gaps'),({'anchor_xyz_m':[0,0,float('nan')]},'finite'),
    ({'support_surface_id':'missing'},'support'),({'anchor_convention':'made-up'},'anchor'),
])
def test_invalid_explicit_tables_refuse_without_changing_source(changes,reason):
    s=base_scene();before=deepcopy(s)
    with pytest.raises(ValueError,match=reason):create(s,[table(**changes)])
    assert s==before


def test_declared_support_checks_full_polygon_and_does_not_reheight_modules():
    s=base_scene();surface=s['surfaces'][0];surface['base_elevation_m']=0
    t=table(anchor_xyz_m=[4,4,3],tilt_deg=0,support_surface_id='roof')
    result,f,modules=create(s,[t]);before=[m['transform']['position_z_m'] for m in modules]
    synchronize_scene_module_center_z(result)
    assert [m['transform']['position_z_m'] for m in result['module_instances']]==before
    s['surfaces'][0]['boundary_2d']['holes']=[[[3.9,3.9],[4.1,3.9],[4.1,4.1],[3.9,4.1]]]
    with pytest.raises(ValueError,match='holes'):create(s,[t])


@pytest.mark.parametrize('tilt',[0.,90.])
def test_flat_and_vertical_tables_use_physical_rectangles(tilt):
    s,f,modules=create(tables=[table(tilt_deg=tilt)])
    generated=generate_scene3d(s)['modules'][0]
    assert generated['status']=='resolved'
    assert math.dist(generated['corners_3d'][0],generated['corners_3d'][1])==pytest.approx(2)
    assert math.dist(generated['corners_3d'][1],generated['corners_3d'][2])==pytest.approx(4)
    Draft202012Validator(json.loads(Path('geometry/scene3d/generated-scene3d.schema.json').read_text()),registry=_registry()).validate(generate_scene3d(s))


def test_explicit_field_scene_schema_and_layout_tampering_are_checked():
    s,f,modules=create()
    Draft202012Validator(json.loads(Path('geometry/scene/scene.schema.json').read_text()),registry=_registry()).validate(s)
    modules[0]['transform']['position_z_m']+=1
    with pytest.raises(ValueError,match='disagrees'):explicit_module_geometry(modules[0],f,s['surfaces'])


def test_explicit_reproduction_has_identical_shading_factors_to_generated_modules():
    original=_scene();oldfield=original['pv_fields'][0]
    original_compiled=compile_shading_geometry(original)
    rows=[table(table_id=m['module_instance_id'],anchor_xyz_m=[m['transform'][k] for k in ('position_x_m','position_y_m','position_z_m')],module_definition_revision_id=m['module_definition_revision_id'],azimuth_deg=oldfield['azimuth_deg'],tilt_deg=oldfield['tilt_deg'],module_gap_across_m=0,module_gap_up_m=0) for m in original['module_instances']]
    explicit=deepcopy(original);explicit['module_instances']=[];explicit['pv_fields']=[]
    f,modules=create_explicit_field(explicit,{MODULE['revision_id']:MODULE},pv_field_id=oldfield['pv_field_id'],name='Exact reproduction',tables=rows,provenance={'source_id':'synthetic'})
    explicit['pv_fields']=[f];explicit['module_instances']=modules
    compiled=compile_shading_geometry(explicit)
    receivers={r['module_instance_id']:r for r in compiled['receivers'] if r['module_instance_id']}
    for m in modules:
        original_id=m['table_id'];new=receivers[m['module_instance_id']]
        old=next(r for r in original_compiled['receivers'] if r['module_instance_id']==original_id)
        assert new['vertices_3d']==old['vertices_3d']
        for sun in ((.4,.2,1),(-.4,.2,1)):
            a=calculate_direct_beam_shadow(compiled,receiver_id=new['receiver_id'],sun_vector_xyz=sun,self_shading_enabled=True)
            b=calculate_direct_beam_shadow(original_compiled,receiver_id=old['receiver_id'],sun_vector_xyz=sun,self_shading_enabled=True)
            assert a['beam_visibility_factor']==b['beam_visibility_factor']


def test_generated_packing_and_manual_commands_refuse_new_kinds_before_mutation():
    from geometry.pvfield.commands import PVFieldPackingSession
    from geometry.pvfield.explicit import assert_packable_field
    from tests.unit.test_rb_mesh1_mesh import mesh
    s,f,modules=create()
    session=PVFieldPackingSession(s,{'module-r1':definition()})
    before=session.scene
    with pytest.raises(ValueError,match='read-only'):session.fill_area(f['pv_field_id'])
    with pytest.raises(ValueError,match='read-only'):session.remove_modules([modules[0]['module_instance_id']])
    assert session.scene==before
    s['obstacles']=[mesh()]
    with pytest.raises(ValueError,match='cannot avoid mesh'):assert_packable_field(s,{'pv_field_id':'g'})
    assert_packable_field(s,{'pv_field_id':'g','exclusion_rules':{'use_scene_obstacles':False}})
    with pytest.raises(ValueError,match='cannot avoid mesh'):assert_packable_field(s,{'pv_field_id':'g','exclusion_rules':{'use_scene_obstacles':False,'obstacle_ids':['mesh-1']}})


def _convert_design_to_explicit(scene, electrical, definitions):
    result=deepcopy(scene);result['pv_fields']=[];result['module_instances']=[];mapping={}
    for oldfield in scene['pv_fields']:
        oldmodules=[m for m in scene['module_instances'] if m['pv_field_id']==oldfield['pv_field_id']]
        if not oldmodules:continue
        rows=[table(table_id=m['module_instance_id'],anchor_xyz_m=[m['transform'][k] for k in ('position_x_m','position_y_m','position_z_m')],module_definition_revision_id=m['module_definition_revision_id'],azimuth_deg=m['transform'].get('rotation_z_deg',oldfield['azimuth_deg']),tilt_deg=oldfield['tilt_deg'],module_orientation=oldfield['orientation']) for m in oldmodules]
        f,modules=create_explicit_field(result,definitions,pv_field_id=oldfield['pv_field_id'],name='Synthetic explicit conversion',tables=rows,provenance={'source_id':'synthetic-test'})
        result['pv_fields'].append(f);result['module_instances'].extend(modules)
        mapping.update({m['table_id']:m['module_instance_id'] for m in modules})
    electrical=deepcopy(electrical)
    for string in electrical['strings']:string['module_instance_ids']=[mapping[mid] for mid in string['module_instance_ids']]
    return result,electrical


def test_supportless_explicit_field_runs_through_standard_execution(tmp_path):
    from tests.unit.test_phase49c_reference_projects import _reference
    from engine.simulation import build_design_revision_store,run_validated_design_simulation
    from validation.engineering import validate_engineering_design
    from apps.api.study import _validation_configuration
    r=_reference('R1');scene,electrical=_convert_design_to_explicit(r['scene'],r['electrical'],r['components'])
    validation=validate_engineering_design(scene,electrical,project_revision_id=r['project_revision']['project_revision_id'],component_revisions=r['components'],configuration=_validation_configuration(),design_validation_report_id='mesh1-explicit-test',generated_at='2026-11-04T00:00:00Z')
    assert not validation['blocking_simulation'],validation['findings']
    result=run_validated_design_simulation(r['project_revision'],r['configuration'],revision_store=build_design_revision_store(scene,electrical,r['weather'],r['components']),design_validation_report=validation,output_directory=tmp_path,simulation_run_id='explicit-standard-test',engine_version='mesh1-test')
    assert result.backend_result is not None,result.simulation_run
    assert result.simulation_run['status'] in {'completed','completed_with_warnings'}
    assert not any(f.get('code')=='execution_group_surface_unresolved' for f in result.simulation_run.get('validation_findings',[]))


def test_supportless_explicit_field_runs_through_real_detailed_dispatch(tmp_path):
    from dataclasses import replace
    from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
    from tests.integration.test_phase69a_closure import _declare
    from engine.simulation import run_canonical_simulation
    project,config,store,scene,electrical=_canonical_fixture();store=_declare(store,'separate_from_parameterization')
    scene,electrical=_convert_design_to_explicit(scene,electrical,store.component_revisions)
    store=replace(store,scene_revisions={scene['revision_id']:scene},electrical_revisions={electrical['electrical_revision_id']:electrical})
    result=run_canonical_simulation(project,config,revision_store=store,output_directory=tmp_path,simulation_run_id='explicit-detailed-test',engine_version='mesh1-test',executed_at='2026-11-04T00:00:00Z')
    assert result.detailed_backend_result is not None,result.simulation_run
    assert result.backend_result is not None,result.simulation_run
    assert result.simulation_run['status'] in {'completed','completed_with_warnings'}
    compiled=compile_shading_geometry(scene)
    assert all(r['support_surface_id'] is None for r in compiled['receivers'] if r['source_entity_type']=='module_instance')


def test_supportless_explicit_multigroup_has_empty_support_ids_and_valid_summary(tmp_path):
    from tests.unit.test_phase49c_reference_projects import _reference
    from engine.simulation import build_design_revision_store,run_validated_design_simulation
    from validation.engineering import validate_engineering_design
    from apps.api.study import _validation_configuration
    from engine.simulation.artifacts import verify_run_package
    from engine.simulation.execution_groups import build_simulation_execution_plan
    r=_reference('R5');scene,electrical=_convert_design_to_explicit(r['scene'],r['electrical'],r['components'])
    validation=validate_engineering_design(scene,electrical,project_revision_id=r['project_revision']['project_revision_id'],component_revisions=r['components'],configuration=_validation_configuration(),design_validation_report_id='mesh1-supportless-multigroup',generated_at='2026-11-04T00:00:00Z')
    assert not validation['blocking_simulation'],validation['findings']
    result=run_validated_design_simulation(r['project_revision'],r['configuration'],revision_store=build_design_revision_store(scene,electrical,r['weather'],r['components']),design_validation_report=validation,output_directory=tmp_path,simulation_run_id='explicit-multigroup-support-test',engine_version='mesh1-test')
    assert result.backend_result is not None,result.simulation_run
    verify_run_package(result.artifact_directory)
    summary=json.loads((result.artifact_directory/'summary-result.json').read_text())
    assert len(summary['execution_breakdown']['groups'])==2
    assert all(g['support_surface_ids']==[] for g in summary['execution_breakdown']['groups'])
