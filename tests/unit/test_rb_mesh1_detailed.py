"""New-table intrinsic region oracles and unchanged detailed execution contract."""
from copy import deepcopy
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from geometry.shading import compile_shading_geometry,SkyDomeResolution,GroundDomeResolution
from geometry.scene.mesh import make_mesh_obstacle
from geometry.scene3d import generate_scene3d
from shading.electrical import derive_electrical_region_map,evaluate_electrical_region_visibility
from tests.unit.test_rb_mesh1_tables import create,table,_convert_design_to_explicit
from tests.unit.test_phase63_electrical_regions import _topology


@pytest.mark.parametrize('orientation',['portrait','landscape'])
def test_intrinsic_region_corners_are_the_hand_affine_transform(orientation):
    scene,_,modules=create(tables=[table(module_orientation=orientation,tilt_deg=32.,azimuth_deg=123.)])
    corners=generate_scene3d(scene)['modules'][0]['corners_3d']
    # Frozen front-UV convention: independent corner identification, not mapper helper.
    origin,u_end,v_end=(corners[2],corners[3],corners[1]) if orientation=='portrait' else (corners[1],corners[2],corners[0])
    mapped=derive_electrical_region_map(compile_shading_geometry(scene),_topology(),module_instance_id=modules[0]['module_instance_id'])
    expected_regions=_topology()['physical_regions']
    for actual,region in zip(mapped['regions'],expected_regions):
        expected=[[origin[k]+u*(u_end[k]-origin[k])+v*(v_end[k]-origin[k]) for k in range(3)] for u,v in region['polygon_normalized']]
        for point,oracle in zip(actual['vertices_3d'],expected):assert point==pytest.approx(oracle,abs=1e-12)


def test_mesh_over_exact_left_region_shades_that_region_only_at_zenith():
    scene,_,modules=create(tables=[table(anchor_xyz_m=[0,0,0],tilt_deg=0.)])
    scene['obstacles']=[make_mesh_obstacle(obstacle_id='region-cover',scene_object_id='obj-cover',name='Left region cover',mesh={'vertices_m':[[-2,-3,2],[0,-3,2],[0,3,2],[-2,3,2]],'faces':[[0,1,2,3]]},provenance={'source_id':'synthetic-region-oracle'})]
    compiled=compile_shading_geometry(scene)
    region=derive_electrical_region_map(compiled,_topology(),module_instance_id=modules[0]['module_instance_id'])
    factors=evaluate_electrical_region_visibility(compiled,region,sun_vector_xyz=[0,0,1],self_shading_enabled=True,sky_resolution=SkyDomeResolution(azimuth_sectors=12,elevation_bands=3,horizon_azimuth_sectors=12,horizon_elevation_bands=1,horizon_band_elevation_deg=10.),ground_resolution=GroundDomeResolution(azimuth_sectors=12,depression_bands=3))
    values={record['receiver_id'].rsplit(':',1)[-1]:record['beam_visibility_factor'] for record in factors['inline_records']}
    assert values['left']==pytest.approx(0,abs=1e-12)
    assert values['right']==pytest.approx(1,abs=1e-12)


def test_supported_explicit_tables_and_mesh_run_through_actual_detailed_backend(tmp_path):
    from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
    from tests.integration.test_phase69a_closure import _declare
    from engine.simulation import run_canonical_simulation
    from engine.simulation.artifacts import verify_run_package
    project,config,store,scene,electrical=_canonical_fixture();store=_declare(store,'separate_from_parameterization')
    # Deliberately large synthetic support, with no change to table anchor heights.
    surface=scene['surfaces'][0];surface['boundary_2d'].update(vertices=[[-100,-100],[100,-100],[100,100],[-100,100]],holes=[]);surface['slope_deg']=0;surface['base_elevation_m']=0
    scene,electrical=_convert_design_to_explicit(scene,electrical,store.component_revisions)
    for field in scene['pv_fields']:
        for t in field['tables']:t['support_surface_id']=surface['surface_id']
    scene['obstacles'].append(make_mesh_obstacle(obstacle_id='mesh-region-cover',scene_object_id='obj-mesh-region-cover',name='Detailed mesh',mesh={'vertices_m':[[-14,-1,10],[-12,-1,10],[-12,1,10],[-14,1,10]],'faces':[[0,1,2,3]]},provenance={'source_id':'synthetic-detailed'}))
    store=replace(store,scene_revisions={scene['revision_id']:scene},electrical_revisions={electrical['electrical_revision_id']:electrical})
    result=run_canonical_simulation(project,config,revision_store=store,output_directory=tmp_path,simulation_run_id='explicit-supported-mesh-detailed',engine_version='mesh1-test',executed_at='2026-11-04T00:00:00Z')
    assert result.detailed_backend_result is not None,result.simulation_run
    assert result.backend_result is not None,result.simulation_run
    assert result.simulation_run['status'] in {'completed','completed_with_warnings'}
    verify_run_package(result.artifact_directory)


@pytest.mark.parametrize('policy',['fail_closed','explicit_lower_fidelity'])
def test_mesh_geometry_blockers_survive_detailed_fallback_and_never_save_runs(tmp_path,monkeypatch,policy):
    from tests.unit.test_phase69b_browser_launch import setup_project,REQUEST
    app,pid,bundle=setup_project(tmp_path,dark=True)
    scene,electrical=_convert_design_to_explicit(bundle['scene'],bundle['electrical_design'],{**bundle['pinned_components']['modules'],**bundle['pinned_components']['inverters']})
    corners=generate_scene3d(scene)['modules'][0]['corners_3d']
    scene['obstacles'].append(make_mesh_obstacle(obstacle_id='contact',scene_object_id='obj-contact',name='Damaged contact',mesh={'vertices_m':corners,'faces':[[0,1,2,3]]},provenance={'source_id':'damaged-synthetic-project'}))
    bundle.update(scene=scene,electrical_design=electrical);service=app.state.project_service;service.store.save(bundle)
    before=service.store.path_for(pid).read_bytes();client=TestClient(app);url=f'/api/projects/{pid}'
    def forbidden(*args,**kwargs):raise AssertionError('geometry blocker dispatched execution')
    monkeypatch.setattr('apps.api.study.run_validated_design_simulation',forbidden)
    request=deepcopy(REQUEST);request['electrical_shading_configuration']['fallback_policy']=policy
    ready=client.get(url+'/execution-readiness',params=request['electrical_shading_configuration']);assert ready.status_code==200,ready.text
    data=ready.json();assert not data['ready'] and data['execution_class']=='blocked_detailed_inputs'
    assert any(f['rule_id']=='SCENE_MODULE_OBSTACLE_OVERLAP' and f['severity']=='blocking_error' for f in data['findings']),data
    assert client.post(url+'/simulate',json=request).status_code==422
    assert service.store.path_for(pid).read_bytes()==before and client.get(url+'/runs').json()==[]
