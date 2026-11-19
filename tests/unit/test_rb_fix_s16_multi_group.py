"""S16: real HTTP and independent single-group/inverter-kernel oracles."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import importlib.util
import json
from urllib.parse import unquote, urlparse

from fastapi.testclient import TestClient
import numpy as np
import pandas as pd
import pytest

from apps.api.server import create_app
from apps.api.study import _phase5_configuration, _validation_configuration
from components.validation import validate_inverter, inverter_capabilities, validate_module, module_capabilities
from electrical.topology import ElectricalTopologyEditorSession, new_electrical_design
from engine.inverter import simulate_voltage_dependent_inverter, evaluate_voltage_dependent_conversion, INVERTER_VOLTAGE_DEPENDENT_BOUNDED
from engine.simulation import (build_design_revision_store, build_project_revision_from_design,
    run_validated_design_simulation)
from engine.simulation.artifacts import verify_run_package
from engine.simulation.execution_groups import build_simulation_execution_plan
from validation.engineering import validate_engineering_design

ROOT = Path(__file__).resolve().parents[2]
MODULE = 'mod-rawibumi-uat-550-r1'
INVERTER = 'inv-rawibumi-uat-150k-r1'
WEATHER = ROOT/'tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json'


def command(kind, **parameters):
    return {'schema_name':'ElectricalTopologyCommand','schema_version':'0.1',
            'command_id':'s16-'+kind,'command_type':kind,'parameters':parameters}


def parquet(reference):
    return pd.read_parquet(Path(unquote(urlparse(reference['uri']).path)))


@dataclass
class Design:
    app: object
    client: TestClient
    project_id: str
    url: str

    def bundle(self):
        return self.client.get(self.url).json()['bundle']

    def post(self, path, body):
        r = self.client.post(self.url+path,json=body)
        assert r.status_code==200,r.text
        return r.json()

    def execute(self, transport, folder, configure=None):
        bundle = self.bundle()
        readiness = self.client.get(self.url+'/execution-readiness')
        assert readiness.status_code==200 and readiness.json()['ready'],readiness.text
        if transport == 'http':
            run = self.post('/simulate', {})
            assert run['status'] in {'completed','completed_with_warnings'},run
            directory = self.app.state.study_service.run_root/self.project_id/run['simulation_run_id']
            verify_run_package(directory)
            return run['summary_result'],None
        weather = self.app.state.study_service.weather.load(self.project_id,bundle['weather_selection']['revision_id'])
        electrical = self.app.state.study_service._simulation_electrical_snapshot(
            bundle['electrical_design'], project_revision_id='s16-adapter-project', snapshot_id='s16-adapter-electrical')
        project = build_project_revision_from_design(bundle['scene'],electrical,
            project_revision_id='s16-adapter-project',revision_number=1,
            weather_dataset_revision_id=weather.dataset['revision_id'])
        config = _phase5_configuration(project,configuration_id='s16-adapter-config')
        if configure is not None:configure(config)
        components = {**bundle['pinned_components']['modules'],**bundle['pinned_components']['inverters']}
        report = validate_engineering_design(bundle['scene'],electrical,
            project_revision_id=project['project_revision_id'],component_revisions=components,
            configuration=_validation_configuration(),design_validation_report_id='s16-validation',generated_at='2026-11-02T00:00:00Z')
        assert not report['blocking_simulation'],report
        result = run_validated_design_simulation(project,config,
            revision_store=build_design_revision_store(bundle['scene'],electrical,weather,components),
            design_validation_report=report,output_directory=folder,simulation_run_id='s16-adapter-run',
            engine_version='s16-test',executed_at='2026-11-02T00:00:00Z')
        assert result.simulation_run['status'] in {'completed','completed_with_warnings'},result.simulation_run
        run=result.simulation_run
        expected_warnings=(sum(f['severity']=='warning' for f in run['validation_findings'])
            +sum(a.get('severity')=='warning' for a in run['assumptions'])
            +sum(len(r['resolution'].get('warnings') or []) for r in run.get('execution_model_resolutions',[]))
            +len((run.get('model_resolution') or {}).get('warnings') or []))
        assert run['warning_summary']['warning_count']==expected_warnings
        verify_run_package(result.artifact_directory)
        return result.summary_result,result


def _variant(app, kind):
    definition = deepcopy(app.state.project_service.catalog['inverters'][INVERTER])
    definition['revision_id']='inv-s16-'+kind+'-r1'
    definition['inverter_definition_id']='inv-s16-'+kind
    definition['manufacturer']='S16 synthetic fixture'
    definition['model']=kind
    definition.setdefault('metadata',{})['synthetic_s16_fixture']=True
    if kind=='clipped':
        factor=1000/definition['ac_limits']['nominal_ac_power_w']
        definition['ac_limits']['nominal_ac_power_w']=1000.
        definition['ac_limits']['max_ac_power_w']=1000.
        for curve in definition['efficiency_model']['curves']:
            for point in curve['points']:
                point['dc_power_w']*=factor;point['ac_power_w']*=factor
    elif kind=='threshold':
        definition['mppt_template']['min_operating_voltage_v']=12.558633853403908
        definition['operating_thresholds'].update(startup_power_w=0.,minimum_input_power_w=0.,night_loss_w=0.,standby_loss_w=0.)
        lo=definition['mppt_template']['min_operating_voltage_v'];hi=definition['mppt_template']['max_operating_voltage_v']
        definition['efficiency_model']['curves']=[{'dc_voltage_v':v,'points':[
            {'dc_power_w':0.,'ac_power_w':0.,'efficiency_fraction':0.},
            {'dc_power_w':180000.,'ac_power_w':171000.,'efficiency_fraction':.95}]} for v in [lo,(lo+hi)/2,hi]]
    else:
        raise AssertionError(kind)
    findings=validate_inverter(definition)
    assert not [f for f in findings if f['severity'] in {'error','blocking_error'}],findings
    definition['capability_flags']=inverter_capabilities(definition,findings)
    assert definition['capability_flags']['basic_design_ready'] and definition['capability_flags']['detailed_efficiency_ready']
    app.state.project_service.catalog['inverters'][definition['revision_id']]=definition
    return definition['revision_id']


@pytest.fixture
def make_design(tmp_path):
    clients=[]
    def make(scenario='orientations'):
        base=tmp_path/scenario
        app=create_app(store_root=base/'projects',library_root=base/'library')
        client=TestClient(app);client.__enter__();clients.append(client)
        created=client.post('/api/projects',json={'name':'S16 '+scenario,'latitude_deg':-6.2,
            'longitude_deg':106.8,'elevation_m':25,'timezone':'Asia/Jakarta'})
        assert created.status_code==201,created.text
        pid=created.json()['bundle']['project']['project_id'];d=Design(app,client,pid,'/api/projects/'+pid)
        inverter_revisions=[INVERTER]
        module_revision=MODULE
        if scenario=='clipping':
            inverter_revisions=[_variant(app,'clipped'),INVERTER]
            module=deepcopy(app.state.project_service.catalog['modules'][MODULE])
            module_revision=module['revision_id']='mod-s16-quality-gain-r1'
            module['module_definition_id']='mod-s16-quality-gain'
            module.setdefault('quality',{})['default_module_quality_loss_fraction']=-.0075
            module.setdefault('metadata',{})['synthetic_s16_fixture']=True
            findings=validate_module(module)
            assert not [f for f in findings if f['severity'] in {'error','blocking_error'}]
            assert len(module['electrical_models'])==1
            model=module['electrical_models'][0]
            assert model['validation']['passed'] is True
            module['capability_flags']=module_capabilities(module,findings,
                model_validation_passed=model['validation']['passed'])
            app.state.project_service.catalog['modules'][module_revision]=module
        if scenario=='threshold':inverter_revisions=[_variant(app,'threshold')]
        if scenario=='duplicate':inverter_revisions=[INVERTER,INVERTER]
        for index,rid in enumerate(inverter_revisions):
            d.post('/inverters',{'name':f'INV-{index+1}','inverter_definition_revision_id':rid})
        fields=[]
        for index in range(1 if scenario=='threshold' else 2):
            v=d.post('/surfaces/rectangle',{'name':f'Roof {index+1}',
                'origin_x_m':0 if scenario=='cross_group' else index*100,
                'origin_y_m':index*5 if scenario=='cross_group' else 0,
                'width_m':1+18*1.154-.01,'height_m':3.45,
                'base_elevation_m':6.1+index*14 if scenario=='cross_group' else 6.1})
            surface=v['bundle']['scene']['surfaces'][-1]['surface_id']
            v=d.post('/pv-fields',{'name':f'Array {index+1}','support_surface_id':surface,
                'module_definition_revision_id':module_revision,'tilt_deg':10 if scenario in {'duplicate','threshold'} or index==0 else 15,
                'row_pitch_m':3.2,'perimeter_setback_m':.5})
            field=next(f for f in v['bundle']['scene']['pv_fields'] if f['support_surface_id']==surface)
            ids=[m['module_instance_id'] for m in v['bundle']['scene']['module_instances'] if m['pv_field_id']==field['pv_field_id']]
            assert len(ids)==18
            fields.append(ids)
        paths=[fields[0][:8],fields[0][8:]] if scenario=='threshold' else fields
        if scenario=='unequal_strings':paths=[fields[0],fields[1][:12]]
        design=d.bundle()['electrical_design'];inverters=design['inverter_instances']
        commands=[]
        for i,ids in enumerate(paths):
            sid=f'S{i+1:03d}'
            commands.append(command('create_string',string_id=sid,module_instance_ids=ids))
            inverter=inverters[i] if len(inverters)==2 else inverters[0]
            index=1 if len(inverters)==2 else i+1
            target=next(m['mppt_instance_id'] for m in design['mppt_instances'] if m['inverter_instance_id']==inverter['inverter_instance_id'] and m['index']==index)
            commands.append(command('assign_strings_to_mppt',string_ids=[sid],mppt_instance_id=target))
        for i,c in enumerate(commands):c['command_id']+=str(i)
        d.post('/electrical/commands',{'commands':commands})
        raw=WEATHER.read_bytes()
        if scenario=='threshold':
            payload=json.loads(raw)
            # Set only a daytime interval to fictional near-dark diffuse irradiance.
            changed=0
            for i,t in enumerate(payload['hourly']['time']):
                if pd.Timestamp(t,unit='s',tz='UTC')==pd.Timestamp('2025-01-01T05:00Z'):
                    for key in ['shortwave_radiation','diffuse_radiation']:payload['hourly'][key][i]=.1
                    payload['hourly']['direct_normal_irradiance'][i]=0.
                    changed+=1
            assert changed==1
            raw=json.dumps(payload).encode()
        app.state.study_service.acquire_weather(pid,source_id='open_meteo_archive_era5',
            start_date='2025-01-01',end_date='2025-01-01',raw_response=raw)
        return d
    yield make
    for client in reversed(clients):client.__exit__(None,None,None)


def standalone(design, group, folder, configure=None):
    """Old single-group canonical path, same full occluding scene and pinned inputs."""
    b=design.bundle();scene=b['scene'];components={**b['pinned_components']['modules'],**b['pinned_components']['inverters']}
    original=b['electrical_design'];iid=group['inverter_instance_id']
    original_inverter=next(i for i in original['inverter_instances'] if i['inverter_instance_id']==iid)
    session=ElectricalTopologyEditorSession(scene,new_electrical_design(project_id=scene['project_id'],
        electrical_revision_id='standalone-electrical',pcc_id='standalone-pcc'),
        project_revision_id='standalone-project',module_definitions=b['pinned_components']['modules'],inverter_definitions=b['pinned_components']['inverters'])
    session.add_inverter(inverter_instance_id=iid,inverter_definition_revision_id=original_inverter['inverter_definition_revision_id'],name='Standalone')
    for sid in group['string_ids']:
        string=next(s for s in original['strings'] if s['string_id']==sid)
        session.create_string(string_id=sid,module_instance_ids=string['module_instance_ids'])
        mppt=next(m for m in original['mppt_instances'] if m['mppt_instance_id']==string['target_mppt_instance_id'])
        session.assign_strings_to_mppt([sid],mppt_instance_id=f"{iid}-mppt-{mppt['index']:02d}")
    electrical=session.commit_revision(electrical_revision_id='standalone-committed',revision_number=2,
        change_summary='Independent S16 oracle',created_at='2026-11-02T00:00:00Z')
    wx=design.app.state.study_service.weather.load(design.project_id,b['weather_selection']['revision_id'])
    project=build_project_revision_from_design(scene,electrical,project_revision_id='standalone-project',revision_number=1,weather_dataset_revision_id=wx.dataset['revision_id'])
    configuration=_phase5_configuration(project,configuration_id='standalone-config')
    if configure is not None:configure(configuration)
    report=validate_engineering_design(scene,electrical,project_revision_id=project['project_revision_id'],
        component_revisions=components,configuration=_validation_configuration(),design_validation_report_id='standalone-validation',generated_at='2026-11-02T00:00:00Z')
    assert not report['blocking_simulation'],report
    result=run_validated_design_simulation(project,configuration,revision_store=build_design_revision_store(scene,electrical,wx,components),
        design_validation_report=report,output_directory=folder,simulation_run_id='standalone',engine_version='s16-oracle',executed_at='2026-11-02T00:00:00Z')
    assert result.backend_result is not None,result.simulation_run
    assert 'execution_breakdown' not in result.summary_result
    return result.backend_result


def group_oracles(design, summary, tmp_path, configure=None):
    breakdown=summary['execution_breakdown'];actual=parquet(breakdown['group_timeseries_reference'])
    bank_by_inverter={};singles={}
    for group in breakdown['groups']:
        gid=group['execution_group_id'];baseline=standalone(design,group,tmp_path/gid,configure)
        frame=actual[actual.execution_group_id==gid]
        for column in ['raw_array_mpp_w','array_virtual_mpp_w','poa_global_w_m2','effective_irradiance_w_m2','module_pmp_w']:
            np.testing.assert_array_equal(frame[column].to_numpy(),baseline.timeseries[column].to_numpy())
        iid=group['inverter_instance_id'];singles[gid]=baseline
        bank_by_inverter.setdefault(iid,{}).update(baseline.electrical.array_losses.mppt_bank)
    return bank_by_inverter,singles


@pytest.mark.parametrize('transport',['http','adapter'])
def test_two_orientations_dc_and_direct_inverter_oracle(make_design,tmp_path,transport):
    design=make_design();summary,result=design.execute(transport,tmp_path/'actual')
    banks,_=group_oracles(design,summary,tmp_path/'oracles')
    bundle=design.bundle();frames=parquet(summary['execution_breakdown']['inverter_timeseries_reference'])
    for inverter in bundle['electrical_design']['inverter_instances']:
        iid=inverter['inverter_instance_id'];definition=bundle['pinned_components']['inverters'][inverter['inverter_definition_revision_id']]
        oracle=simulate_voltage_dependent_inverter(banks[iid],definition,model_id=INVERTER_VOLTAGE_DEPENDENT_BOUNDED)
        frame=frames[frames.inverter_instance_id==iid]
        for column in ['pcc_power_w','inverter_conversion_loss_w','inverter_clipping_loss_w','dc_voltage_threshold_loss_w']:
            expected='ac_net_output_w' if column=='pcc_power_w' else column
            np.testing.assert_array_equal(frame[column].to_numpy(),oracle.frame[expected].to_numpy())
    assert len(summary['execution_breakdown']['groups'])==2
    assert summary['total_energy_wh']==pytest.approx(sum(i['total_energy_wh'] for i in summary['execution_breakdown']['inverters']),rel=1e-12)


@pytest.mark.parametrize('transport',['http','adapter'])
def test_duplicate_inverters_exact_individual_ac_and_double_pcc(make_design,tmp_path,transport):
    design=make_design('duplicate');summary,_=design.execute(transport,tmp_path/'actual')
    _,singles=group_oracles(design,summary,tmp_path/'oracles')
    actual=parquet(summary['execution_breakdown']['inverter_timeseries_reference'])
    standalone_frames=[]
    for group in summary['execution_breakdown']['groups']:
        baseline=singles[group['execution_group_id']]
        standalone_frames.append(baseline.timeseries['pcc_power_w'].to_numpy())
        frame=actual[actual.inverter_instance_id==group['inverter_instance_id']]
        np.testing.assert_array_equal(frame.pcc_power_w.to_numpy(),baseline.timeseries.pcc_power_w.to_numpy())
    np.testing.assert_array_equal(standalone_frames[0],standalone_frames[1])
    reference_energy=next(iter(singles.values())).energy.annual['pcc_power_kwh']*1000
    assert summary['total_energy_wh']==pytest.approx(2*reference_energy,rel=1e-9)


LOSS_COLUMNS=['lid_loss_w','degradation_loss_w','module_quality_loss_w','module_mismatch_loss_w','string_mismatch_loss_w',
    'dc_wiring_loss_w','dc_voltage_threshold_loss_w','dc_power_threshold_loss_w',
    'inverter_conversion_loss_w','inverter_clipping_loss_w','inverter_self_consumption_w']


@pytest.mark.parametrize('transport',['http','adapter'])
def test_clipping_only_oversized_inverter_and_signed_conservation(make_design,tmp_path,transport):
    design=make_design('clipping');summary,_=design.execute(transport,tmp_path/'actual')
    banks,_=group_oracles(design,summary,tmp_path/'oracles')
    rows=summary['execution_breakdown']['inverters'];by_name={r['name']:r for r in rows}
    assert by_name['INV-1']['clipping_energy_wh']>0
    assert by_name['INV-2']['clipping_energy_wh']==0
    frames=parquet(summary['execution_breakdown']['inverter_timeseries_reference'])
    bundle=design.bundle()
    for row in rows:
        iid=row['inverter_instance_id'];frame=frames[frames.inverter_instance_id==iid]
        definition=bundle['pinned_components']['inverters'][row['inverter_revision_id']]
        oracle=simulate_voltage_dependent_inverter(banks[iid],definition,model_id=INVERTER_VOLTAGE_DEPENDENT_BOUNDED)
        np.testing.assert_array_equal(frame.pcc_power_w.to_numpy(),oracle.frame.ac_net_output_w.to_numpy())
        np.testing.assert_allclose(frame.raw_array_mpp_w-frame[LOSS_COLUMNS].sum(axis=1),frame.pcc_power_w,rtol=1e-12,atol=1e-6)
        assert sum(l['lost_energy_wh'] for l in row['loss_summary'])==pytest.approx(
            row['loss_summary'][0]['reference_energy_wh']-row['total_energy_wh'],rel=1e-9,abs=1e-9)
    assert sum(r['clipping_energy_wh'] for r in rows)==pytest.approx(summary['clipping_energy_wh'])
    assert next(l for l in summary['loss_summary'] if l['loss_type']=='module_quality')['lost_energy_wh']<0  # Preserve the pinned quality gain.
    assert sum(l['lost_energy_wh'] for l in summary['loss_summary'])==pytest.approx(
        summary['loss_summary'][0]['reference_energy_wh']-summary['total_energy_wh'],rel=1e-9,abs=1e-9)


@pytest.mark.parametrize('transport',['http','adapter'])
def test_one_mppt_below_voltage_window_leaves_other_tracker_converting(make_design,tmp_path,transport):
    design=make_design('threshold');summary,_=design.execute(transport,tmp_path/'actual')
    banks,_=group_oracles(design,summary,tmp_path/'oracles')
    bank=next(iter(banks.values()));definition=next(iter(design.bundle()['pinned_components']['inverters'].values()))
    bundle=design.bundle()
    weather=design.app.state.study_service.weather.load(design.project_id,bundle['weather_selection']['revision_id'])
    # The importer owns conversion from provider end labels to canonical starts.
    low=weather.series.index[weather.series['ghi_w_m2'].eq(.1)]
    assert len(low)==1
    when=low[0]
    assert bank[1].frame.loc[when,'mppt_vmp_v']<definition['mppt_template']['min_operating_voltage_v']
    assert bank[2].frame.loc[when,'mppt_vmp_v']>definition['mppt_template']['min_operating_voltage_v']
    oracle=simulate_voltage_dependent_inverter(bank,definition,model_id=INVERTER_VOLTAGE_DEPENDENT_BOUNDED)
    frame=parquet(summary['execution_breakdown']['inverter_timeseries_reference'])
    actual=frame[pd.to_datetime(frame.timestamp)==when].iloc[0]
    assert actual.dc_voltage_threshold_loss_w==pytest.approx(bank[1].frame.loc[when,'mppt_pmp_w'])
    assert actual.dc_voltage_window_accepted_w==pytest.approx(bank[2].frame.loc[when,'mppt_pmp_w'])
    assert actual.pcc_power_w>0
    for column in ['dc_voltage_threshold_loss_w','dc_power_threshold_loss_w','inverter_conversion_loss_w']:
        np.testing.assert_array_equal(frame[column].to_numpy(),oracle.frame[column].to_numpy())
    np.testing.assert_array_equal(frame.pcc_power_w.to_numpy(),oracle.frame.ac_net_output_w.to_numpy())


@pytest.mark.parametrize('policy',['fail_closed','explicit_lower_fidelity'])
def test_detailed_multi_inverter_refused_before_dispatch_and_no_run_saved(make_design,policy):
    design=make_design('duplicate');path=design.app.state.project_service.store.path_for(design.project_id);before=path.read_bytes()
    request={'requested_fidelity':'level_2_bypass_substring','fallback_policy':policy}
    readiness=design.client.get(design.url+'/execution-readiness',params=request)
    assert readiness.status_code==200 and not readiness.json()['ready']
    finding=next(f for f in readiness.json()['findings'] if f['rule_id']=='SIMULATION_SCOPE_DETAILED_SHADING_SINGLE_INVERTER')
    assert all(n in finding['message'] for n in ['INV-1','INV-2'])
    assert len(finding['context']['groups'])==2
    response=design.client.post(design.url+'/simulate',json={'electrical_shading_configuration':request})
    assert response.status_code==422
    assert path.read_bytes()==before and not design.bundle()['simulation_runs']


def test_manual_mixed_mppt_allowed_as_draft_but_readiness_blocks(make_design):
    design=make_design();b=design.bundle();target=b['electrical_design']['mppt_instances'][0]['mppt_instance_id']
    design.post('/electrical/commands',{'commands':[command('assign_strings_to_mppt',string_ids=['S002'],mppt_instance_id=target)]})
    path=design.app.state.project_service.store.path_for(design.project_id);before=path.read_bytes()
    ready=design.client.get(design.url+'/execution-readiness').json()
    assert ready['ready'] and not any(f['rule_id']=='SIMULATION_SCOPE_MIXED_STRINGS_ON_ONE_MPPT' for f in ready['findings'])
    assert path.read_bytes()==before
    response=design.client.post(design.url+'/simulate',json={})
    assert response.status_code==200,response.text
    assert response.json()['mixed_orientation']


def test_enabled_inverter_without_strings_refused_plainly(make_design):
    design=make_design('duplicate')
    design.post('/electrical/commands',{'commands':[command('delete_string',string_id='S002')]})
    ready=design.client.get(design.url+'/execution-readiness').json()
    assert not ready['ready']
    f=next(f for f in ready['findings'] if f['rule_id']=='SIMULATION_INVERTER_HAS_NO_SIMULATED_STRINGS')
    assert 'INV-2' in f['message'] and 'assign strings to it or disable it' in f['message']
    assert design.client.post(design.url+'/simulate',json={}).status_code==422


def test_automatic_assignment_and_rebalance_preserve_group_compatibility(make_design):
    design=make_design();design.post('/electrical/commands',{'commands':[command('unassign_strings',string_ids=['S001','S002'])]})
    iid=design.bundle()['electrical_design']['inverter_instances'][0]['inverter_instance_id']
    design.post('/assignments',{'inverter_instance_id':iid})
    for endpoint in [False,True]:
        if endpoint:design.post('/electrical/commands',{'commands':[command('balance_mppt',inverter_instance_id=iid)]})
        b=design.bundle();plan=build_simulation_execution_plan(b['scene'],b['electrical_design'],numerical_options={'albedo':.2})
        assert plan['execution_class']=='separable_multi_group' and not plan['heterogeneous_mppt_instance_ids']
        assert design.client.get(design.url+'/execution-readiness').json()['ready']


def test_unequal_voltage_and_loading_use_full_inverter_efficiency_once():
    from electrical.mppt import MPPTAggregationResult
    from apps.api.catalog import load_reference_catalog
    inverter=deepcopy(load_reference_catalog()['inverters'][INVERTER])
    inverter['efficiency_model']['curves']=[{'dc_voltage_v':v,'points':[
        {'dc_power_w':0.,'ac_power_w':0.},{'dc_power_w':180000.,'ac_power_w':180000*eta}]} for v,eta in [(400.,.94),(600.,.97),(800.,.98)]]
    index=pd.date_range('2025-01-01T12:00+07:00',periods=1,freq='h');bank={}
    for i,p,v in [(1,2000.,400.),(2,4000.,800.)]:
        frame=pd.DataFrame({'mppt_pmp_w':[p],'mppt_vmp_v':[v],'mppt_voc_v':[v+50],
            'mppt_imp_a':[p/v],'mppt_isc_a':[p/v*1.05],'active':[True]},index=index)
        bank[i]=MPPTAggregationResult(i,(f'S{i}',),frame,{})
    result=simulate_voltage_dependent_inverter(bank,inverter)
    assert result.frame.iloc[0].ac_unclipped_w==pytest.approx(2000*.94+4000*.98,abs=1e-9)
    assert result.metadata['multi_mppt_efficiency_policy']=='power_weighted_voltage_efficiency_at_total_inverter_dc_power'


def test_r5_positive_execution_and_save_reload(tmp_path):
    spec=importlib.util.spec_from_file_location('s16_reference',ROOT/'tests/unit/test_phase49c_reference_projects.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);ref=m._reference('R5')
    saved=m.persist_design_state_package(tmp_path/'saved',scene=ref['scene'],electrical_design=ref['electrical'],
        project_revision=ref['project_revision'],simulation_configuration=ref['configuration'],design_validation_report=ref['validation'])
    loaded=m.load_design_state_package(saved);results=[]
    for label,scene,electrical,project,config,validation in [
        ('before',ref['scene'],ref['electrical'],ref['project_revision'],ref['configuration'],ref['validation']),
        ('after',loaded.scene,loaded.electrical_design,loaded.project_revision,loaded.simulation_configuration,loaded.design_validation_report)]:
        result=run_validated_design_simulation(project,config,revision_store=build_design_revision_store(scene,electrical,ref['weather'],ref['components']),
            design_validation_report=validation,output_directory=tmp_path/label,simulation_run_id='s16-r5',engine_version='s16-test',executed_at='2026-11-02T00:00:00Z')
        assert result.backend_result is not None,result.simulation_run
        results.append(result)
    pd.testing.assert_frame_equal(results[0].standard_timeseries,results[1].standard_timeseries,check_exact=True)
    for key in ['total_energy_wh','specific_yield_wh_per_wp','performance_ratio','loss_summary']:
        assert results[0].summary_result[key]==results[1].summary_result[key]
    for key in ['groups','inverters']:
        assert results[0].summary_result['execution_breakdown'][key]==results[1].summary_result['execution_breakdown'][key]


def test_nameplate_weighted_reference_and_excluded_modules(make_design,tmp_path):
    design=make_design('unequal_strings');summary,result=design.execute('adapter',tmp_path/'actual')
    group_oracles(design,summary,tmp_path/'oracles')
    groups=summary['execution_breakdown']['groups'];capacity=sum(g['simulated_dc_nameplate_w'] for g in groups)
    assert capacity==16500
    reference=sum(g['simulated_dc_nameplate_w']*g['poa_unshaded_wh_m2']/1000 for g in groups)
    assert summary['specific_yield_wh_per_wp']==pytest.approx(summary['total_energy_wh']/capacity,rel=1e-12)
    assert summary['performance_ratio']==pytest.approx(summary['total_energy_wh']/reference,rel=1e-12)
    assert not {'module_temperature_c','cell_temperature_c','module_vmp_v'} & set(result.standard_timeseries)
    warning=next(f for f in design.client.get(design.url+'/execution-readiness').json()['findings'] if f['rule_id']=='MODULES_NOT_SIMULATED')
    assert warning['context']['module_count']==6


def test_global_nonzero_resistance_refused_on_new_multi_path(tmp_path):
    from engine.simulation import run_canonical_simulation
    spec=importlib.util.spec_from_file_location('s16_resistance_ref',ROOT/'tests/unit/test_phase49c_reference_projects.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);ref=m._reference('R5')
    config=deepcopy(ref['configuration']);config['numerical_options']['losses']['dc_array_resistance_ohm']=.1
    result=run_canonical_simulation(ref['project_revision'],config,
        revision_store=build_design_revision_store(ref['scene'],ref['electrical'],ref['weather'],ref['components']),
        output_directory=tmp_path,simulation_run_id='resistance-refusal',engine_version='s16-test')
    assert result.simulation_run['status']=='failed' and result.backend_result is None
    f=next(f for f in result.simulation_run['validation_findings'] if f['rule_id']=='SIMULATION_SCOPE_MULTI_GROUP_DC_RESISTANCE')
    assert 'per-circuit wiring' in f['message']


def test_group_cost_shares_solar_and_solves_module_state_per_group(make_design,tmp_path,monkeypatch):
    import engine.simulation.unshaded as worker
    counts={'solar':0,'module':0};solar=worker.solar_position_from_weather;module=worker.solve_pvsyst_module_thermal_coupling
    def counted_solar(*args,**kwargs):counts['solar']+=1;return solar(*args,**kwargs)
    def counted_module(*args,**kwargs):counts['module']+=1;return module(*args,**kwargs)
    monkeypatch.setattr(worker,'solar_position_from_weather',counted_solar)
    monkeypatch.setattr(worker,'solve_pvsyst_module_thermal_coupling',counted_module)
    design=make_design();counts.update(solar=0,module=0)
    summary,_=design.execute('adapter',tmp_path/'actual')
    assert counts=={'solar':1,'module':len(summary['execution_breakdown']['groups'])}


def test_grouped_assignment_refusal_is_atomic_with_disabled_trackers(make_design):
    design=make_design();design.post('/electrical/commands',{'commands':[command('unassign_strings',string_ids=['S001','S002'])]})
    bundle=design.bundle();electrical=bundle['electrical_design']
    for mppt in electrical['mppt_instances']:mppt['enabled']=mppt['index']==1
    # Valid synthetic draft with one usable tracker; no public command toggles MPPTs yet.
    design.app.state.project_service.store.save(bundle)
    path=design.app.state.project_service.store.path_for(design.project_id);before=path.read_bytes()
    iid=electrical['inverter_instances'][0]['inverter_instance_id']
    response=design.client.post(design.url+'/assignments',json={'inverter_instance_id':iid})
    assert response.status_code==422 and 'Not enough compatible MPPT inputs' in response.text
    assert path.read_bytes()==before


def shading_mode(config, mode):
    shading=config['shading_configuration']
    shading['self_shading_enabled']=True
    if mode in {'beam','unshaded'}:shading['diffuse_method']='none'
    if mode!='full':shading['albedo_method']='none'
    if mode=='unshaded':shading['beam_method']='none'


@pytest.mark.parametrize('mode',['beam','sky','full'])
def test_geometry_modes_keep_cross_group_occluders_and_stream_physics(make_design,tmp_path,mode):
    from engine.simulation.artifacts import receiver_factor_physical_sha256
    design=make_design('cross_group')
    configure=lambda c:shading_mode(c,mode)
    summary,result=design.execute('adapter',tmp_path/'actual',configure)
    _,baselines=group_oracles(design,summary,tmp_path/'independent',configure)
    # Each legacy run retains every roof/module as an occluder while selecting one receiver group.
    retained=pd.concat([b.shading_receiver_factors for b in baselines.values()],ignore_index=True)
    retained=retained.sort_values(['interval_start','receiver_id']).reset_index(drop=True)
    reference=result.simulation_run['shading_receiver_factor_reference']
    streamed=parquet(reference).sort_values(['interval_start','receiver_id']).reset_index(drop=True)
    assert len(streamed)==24*36 and not streamed.duplicated(['interval_start','receiver_id']).any()
    assert receiver_factor_physical_sha256(retained)==receiver_factor_physical_sha256(streamed)
    assert reference['physical_content_sha256']==receiver_factor_physical_sha256(streamed)
    assert result.backend_result.shading_receiver_factors is None
    if mode!='beam':
        assert (streamed['sky_visibility_factor']<1).any()
    assert result.simulation_run['shading_result']['record_count']==len(streamed)


def test_annual_counterfactual_uses_the_whole_plant_clear_run(make_design,tmp_path):
    design=make_design('cross_group')
    # Entirely fictional provider response: diffuse-only daylight, zero night radiation.
    # Padded UTC end labels are decoded and trimmed by the real weather acquisition path.
    raw=json.loads(WEATHER.read_text())
    labels=pd.date_range('2024-12-30', '2026-01-02',freq='h',tz='UTC')
    hour=(labels-pd.Timedelta(hours=1)).tz_convert('Asia/Jakarta').hour
    daylight=(hour>=10)&(hour<16)
    raw['hourly']={key:[values[0]]*len(labels) for key,values in raw['hourly'].items()}
    raw['hourly']['time']=labels.as_unit('s').asi8.tolist()
    for key in ['shortwave_radiation','diffuse_radiation']:
        raw['hourly'][key]=np.where(daylight,500.,0.).tolist()
    raw['hourly']['direct_normal_irradiance']=[0.]*len(labels)
    design.app.state.study_service.acquire_weather(design.project_id,source_id='open_meteo_archive_era5',
        start_date='2025-01-01',end_date='2025-12-31',raw_response=json.dumps(raw).encode())
    actual,result=design.execute('adapter',tmp_path/'actual',lambda c:shading_mode(c,'full'))
    clear,_=design.execute('adapter',tmp_path/'clear',lambda c:shading_mode(c,'unshaded'))
    assert actual['period_duration_hours']==8760 and actual['annual_energy_wh'] is not None
    basis=actual['shading_energy_loss_basis']
    assert basis['actual_pcc_energy_wh']==actual['total_energy_wh']
    assert basis['counterfactual_pcc_energy_wh']==clear['total_energy_wh']
    assert actual['shading_energy_loss_wh']==pytest.approx(clear['total_energy_wh']-actual['total_energy_wh'],abs=1e-8)
    assert actual['shading_energy_loss_wh']>0
    assert result.simulation_run['shading_receiver_factor_reference']['row_count']==8760*36
