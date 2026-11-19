"""Independent fixed-reference quadrature checks through actual browser execution."""
from copy import deepcopy
from pathlib import Path
import json

import pandas as pd
import pytest
from electrical.topology import ElectricalTopologyEditorSession
from geometry.shading import compile_shading_geometry, prepare_directional_receiver, calculate_sky_visibility, calculate_ground_visibility, SkyDomeResolution, GroundDomeResolution
from geometry.scene.mesh import make_mesh_obstacle
from geometry.pvfield.explicit import create_explicit_field
from tests.unit.test_phase51_compiled_shading_geometry import _scene, MODULE as GEOMETRY_MODULE
from tests.unit.test_rb_mesh1_tables import table
from tests.unit.test_rb_fix_s2_honest_preflight import Project, MODULE, INVERTER


def box(oid,x0,x1,y0,y1,height):
    return make_mesh_obstacle(obstacle_id=oid,scene_object_id='obj-'+oid,name=oid,
        mesh={'vertices_m':[[x0,y0,0],[x1,y0,0],[x1,y1,0],[x0,y1,0],[x0,y0,height],[x1,y0,height],[x1,y1,height],[x0,y1,height]],
              'faces':[[3,2,1,0],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]},provenance={'source_id':'synthetic-sky1'})


def layout(name):
    if name=='A':return [table(anchor_xyz_m=[0,0,1],tilt_deg=0.)],[box('wall',3,5,-20,20,8)],None
    if name=='B':return [table(anchor_xyz_m=[0,0,1],tilt_deg=0.)],[box('building',10,25,-30,30,8)],None
    if name=='C':return [table(anchor_xyz_m=[0,0,.3],tilt_deg=10.)],[box('parapet',1.5,1.7,-20,20,1.2)],None
    if name=='D':return [table(table_id=f't{r}-{c}',anchor_xyz_m=[c*1.05,r*3.,.8],tilt_deg=15.) for r in range(5) for c in range(9)],[],'t2-4'
    if name=='G1':return [table(anchor_xyz_m=[0,0,1.5],tilt_deg=35.,azimuth_deg=90.)],[box('wall',3,5,-20,20,8)],None
    if name=='G2':return [table(table_id=f't{r}-{c}',anchor_xyz_m=[c*1.05,r*3.,1.2],tilt_deg=35.) for r in range(5) for c in range(9)],[],'t2-4'
    if name=='G3':return [table(anchor_xyz_m=[0,0,3],tilt_deg=30.)],[box(f'leg-{i}',x-.1,x+.1,y-.1,y+.1,2.3) for i,(x,y) in enumerate([(-.4,-.65),(.4,-.65),(-.4,.65),(.4,.65)])],None
    raise AssertionError(name)


def geometry(name, scene=None, definition=None):
    scene=deepcopy(scene or _scene());definition=deepcopy(definition or GEOMETRY_MODULE)
    definition['mechanical'].update(width_m=1.,height_m=2.)
    scene.update(surfaces=[],obstacles=[],pv_fields=[],module_instances=[])
    tables,obstacles,target=layout(name)
    for t in tables:t['module_definition_revision_id']=definition['revision_id']
    field,modules=create_explicit_field(scene,{definition['revision_id']:definition},pv_field_id='sky1-field',name='Synthetic sky layout',tables=tables,provenance={'source_id':'synthetic-sky1'})
    scene.update(pv_fields=[field],module_instances=modules,obstacles=obstacles)
    mid=next(m['module_instance_id'] for m in modules if target is None or m.get('table_id')==target)
    return scene,definition,mid


def http_project(tmp_path,name):
    p=Project(tmp_path,18,strings=False);b=p.bundle()
    scene,definition,mid=geometry(name,b['scene'],b['pinned_components']['modules'][MODULE])
    b['pinned_components']['modules'][MODULE]=definition
    # Synthetic electrical envelope for a one-module geometric oracle; no
    # manufacturer low-voltage capability is asserted by this fixture.
    inverter=b['pinned_components']['inverters'][INVERTER]
    inverter['mppt_template']['min_operating_voltage_v']=.01
    inverter['dc_limits']['startup_voltage_v']=.01
    session=ElectricalTopologyEditorSession(scene,b['electrical_design'],project_revision_id=b['project']['project_revision']['project_revision_id'],module_definitions=b['pinned_components']['modules'],inverter_definitions=b['pinned_components']['inverters'])
    mids=[m['module_instance_id'] for m in scene['module_instances']]
    mppts=[m['mppt_instance_id'] for m in b['electrical_design']['mppt_instances']]
    for i,start in enumerate(range(0,len(mids),15)):
        sid=f'SKY{i+1}';session.create_string(string_id=sid,module_instance_ids=mids[start:start+15]);session.assign_strings_to_mppt([sid],mppt_instance_id=mppts[i%len(mppts)])
    electrical=session.commit_revision(electrical_revision_id='sky1-electrical',revision_number=20,change_summary='Synthetic optical oracle wiring',created_at='2026-11-05T00:00:00Z')
    b.update(scene=scene,electrical_design=electrical);p.service.store.save(b)
    # One actual daylight interval suffices for a static visibility oracle.
    selection=b['weather_selection'];weather=p.study.weather.load(p.pid,selection['revision_id']);day=weather.series[weather.series.ghi_w_m2>100].iloc[:1].copy();assert len(day)==1
    weather.series=day;weather.dataset['start_time']=day.index[0].isoformat();weather.dataset['end_time']=(day.index[-1]+pd.Timedelta(hours=1)).isoformat()
    current=p.bundle();current['weather_selection']=p.study.weather.save(p.pid,weather);p.service.save_bundle(current)
    return p,mid


@pytest.mark.parametrize('name',['A','B','C','D'])
def test_browser_http_sky_and_horizon_match_fixed_reference(tmp_path,name):
    p,mid=http_project(tmp_path,name);scene=p.bundle()['scene'];compiled=compile_shading_geometry(scene)
    rid=next(r['receiver_id'] for r in compiled['receivers'] if r.get('module_instance_id')==mid)
    prepared=prepare_directional_receiver(compiled,receiver_id=rid,self_shading_enabled=True)
    def reference(a,e):return calculate_sky_visibility(compiled,receiver_id=rid,self_shading_enabled=True,resolution=SkyDomeResolution(a,e,a,1,10.),prepared_query=prepared)
    fine=reference(288,72);coarse=reference(144,36)
    assert abs(fine['sky_visibility_factor']-coarse['sky_visibility_factor'])<=.001
    for level,az,bands in [('standard',48,12),('high',72,18)]:
        assert p.client.patch(p.url+'/shading-accuracy',json={'overrides':{'level':level}}).status_code==200
        response=p.client.post(p.url+'/simulate',json={});assert response.status_code==200,response.text
        run=response.json();assert run['status']!='failed',run
        snapshot=run['resolved_shading_accuracy'];assert snapshot['level']==level
        root=p.study.run_root/p.pid/run['simulation_run_id'];manifest=json.loads((root/'reproducibility-manifest.json').read_text())
        assert manifest['shading_configuration']['sky_dome_resolution']==snapshot['sky_dome_resolution']
        frame=pd.read_parquet(root/'shading-receiver-factors.parquet');record=frame[frame.receiver_id==rid].iloc[0]
        assert abs(record.sky_visibility_factor-fine['sky_visibility_factor'])<=.005
        # Check the actual HTTP-produced receiver horizon as well as the grid.
        runtime=manifest['model_manifest']['near_shading_runtime']
        direct=reference(az,bands)
        assert abs(record.horizon_visibility_factor-fine['horizon_visibility_factor'])<=.01
        assert record.horizon_visibility_factor==direct['horizon_visibility_factor']
        assert snapshot['sky_dome_resolution']['horizon_azimuth_sectors']==az
        assert runtime['sky_solver_manifest']['resolution']['horizon_azimuth_sectors']==az
        # HTTP really computed the same per-receiver sky factor, not just a label.
        assert record.sky_visibility_factor==direct['sky_visibility_factor']


@pytest.mark.parametrize('name',['G1','G2','G3'])
def test_ground_g1_g3_fixed_reference_and_convergence(name):
    scene,_,mid=geometry(name);compiled=compile_shading_geometry(scene);rid=next(r['receiver_id'] for r in compiled['receivers'] if r.get('module_instance_id')==mid)
    prepared=prepare_directional_receiver(compiled,receiver_id=rid,self_shading_enabled=True)
    def factor(a,e):return calculate_ground_visibility(compiled,receiver_id=rid,self_shading_enabled=True,resolution=GroundDomeResolution(a,e),prepared_query=prepared)['ground_visibility_factor']
    fine=factor(288,72);assert abs(factor(144,36)-fine)<=.001
    assert abs(factor(48,12)-fine)<=.01
    assert abs(factor(72,18)-fine)<=.005


def test_closed_box_standard_matches_independent_ray_reference():
    from tests.unit.test_rb_mesh1_acceleration import _box_sky_ray_reference
    scene,_,mid=geometry('A');compiled=compile_shading_geometry(scene);rid=next(r['receiver_id'] for r in compiled['receivers'] if r.get('module_instance_id')==mid)
    low=_box_sky_ray_reference(8,16,360,90);fine=_box_sky_ray_reference(16,32,720,180)
    assert abs(low-fine)<=.001
    actual=calculate_sky_visibility(compiled,receiver_id=rid,self_shading_enabled=True,resolution=SkyDomeResolution(48,12,48,1,10.),prepared_query=prepare_directional_receiver(compiled,receiver_id=rid,self_shading_enabled=True))
    assert abs(actual['sky_visibility_factor']-fine)<=.005
