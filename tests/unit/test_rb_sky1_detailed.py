"""Both sampling levels retain the actual detailed per-region producer path."""
from dataclasses import replace
import json
import pytest

from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
from tests.integration.test_phase69a_closure import _declare
from tests.unit.test_rb_mesh1_tables import _convert_design_to_explicit
from geometry.scene.mesh import make_mesh_obstacle
from engine.simulation.shading_accuracy import default_shading_accuracy, patch_shading_accuracy, configure_browser_shading_accuracy
from engine.simulation import run_canonical_simulation
from engine.simulation.artifacts import verify_run_package


@pytest.mark.parametrize('level',['standard','high'])
def test_full_explicit_mesh_detailed_run_records_actual_resolution_without_fallback(tmp_path,level):
    project,config,store,scene,electrical=_canonical_fixture();store=_declare(store,'separate_from_parameterization')
    surface=scene['surfaces'][0];surface['boundary_2d'].update(vertices=[[-100,-100],[100,-100],[100,100],[-100,100]],holes=[]);surface['slope_deg']=0;surface['base_elevation_m']=0
    scene,electrical=_convert_design_to_explicit(scene,electrical,store.component_revisions)
    for field in scene['pv_fields']:
        for table in field['tables']:table['support_surface_id']=surface['surface_id']
    scene['obstacles'].append(make_mesh_obstacle(obstacle_id='mesh-region-cover',scene_object_id='obj-mesh-cover',name='Synthetic detailed mesh',mesh={'vertices_m':[[-14,-1,10],[-12,-1,10],[-12,1,10],[-14,1,10]],'faces':[[0,1,2,3]]},provenance={'source_id':'synthetic-sky1'}))
    store=replace(store,scene_revisions={scene['revision_id']:scene},electrical_revisions={electrical['electrical_revision_id']:electrical})
    config['shading_configuration']['self_shading_enabled']=True
    configure_browser_shading_accuracy(config,patch_shading_accuracy(default_shading_accuracy(),{'overrides':{'level':level}}))
    result=run_canonical_simulation(project,config,revision_store=store,output_directory=tmp_path,simulation_run_id=f'sky1-detailed-{level}',engine_version='sky1-test',executed_at='2026-11-05T00:00:00Z')
    assert result.detailed_backend_result is not None and result.backend_result is not None,result.simulation_run
    run=result.simulation_run;identity=run['detailed_execution_identity']
    assert identity['resolved_fidelity']=='level_2_bypass_substring' and not identity['fallback_applied']
    assert identity['runtime_support_result']=='pcc_complete'
    snapshot=run['resolved_shading_accuracy'];az,bands=(48,12) if level=='standard' else (72,18)
    assert snapshot['level']==level and snapshot['sky_dome_resolution']['azimuth_sectors']==az
    assert snapshot['ground_dome_resolution']=={'azimuth_sectors':az,'depression_bands':bands}
    context=json.loads((result.artifact_directory/'detailed-execution-context.json').read_text())
    actual=context['inputs']['simulation_configuration']['shading_configuration']
    assert actual['sky_dome_resolution']==snapshot['sky_dome_resolution']
    assert actual['ground_dome_resolution']==snapshot['ground_dome_resolution']
    manifest=json.loads((result.artifact_directory/'reproducibility-manifest.json').read_text())
    assert manifest['model_manifest']['resolved_shading_accuracy']==snapshot
    verify_run_package(result.artifact_directory)


def test_failed_run_still_records_selected_sampling():
    from engine.simulation.canonical import _failed_run
    config={'simulation_configuration_id':'failed','numerical_options':{},'shading_configuration':{}}
    configure_browser_shading_accuracy(config,default_shading_accuracy())
    run=_failed_run(simulation_run_id='failed',project_revision={'project_revision_id':'p'},simulation_configuration=config,engine_version='sky1-test',timestamp='2026-11-05T00:00:00Z',findings=[],assumptions=[],model_resolution=None,component_manifest={},input_hash='a'*64)
    assert run['status']=='failed'
    assert run['resolved_shading_accuracy']['level']=='standard'
    assert run['model_manifest']['resolved_shading_accuracy']==run['resolved_shading_accuracy']
