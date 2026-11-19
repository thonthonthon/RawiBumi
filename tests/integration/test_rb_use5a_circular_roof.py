"""Annual physical plausibility and the common runtime fixture construction."""
from copy import deepcopy
from dataclasses import replace
import json
import numpy as np
import pandas as pd
import pytest
from pvlib.location import Location

from engine.simulation.execution_groups import build_simulation_execution_plan, execution_units
from engine.simulation.multi_group import run_multi_group_physics
from engine.simulation.unshaded import UnshadedFixedTiltConfiguration
from engine.irradiance import POA_ISOTROPIC
from engine.inverter import INVERTER_VOLTAGE_DEPENDENT_BOUNDED
from geometry.shading import compile_shading_geometry
from engine.losses.settings import default_loss_settings,resolve_loss_settings
from tests.unit.test_rb_fix_s2_honest_preflight import Project,MODULE,INVERTER
from weather.core import build_weather_dataset,build_time_semantics


def annual_weather(periods=8760):
    index=pd.date_range('2025-01-01',periods=periods,freq='h',tz='Asia/Jakarta')
    site=Location(-6.2,106.8,tz='Asia/Jakarta',altitude=25)
    sky=site.get_clearsky(index+pd.Timedelta(minutes=30))
    sky.index=index
    series=pd.DataFrame({'ghi_w_m2':sky.ghi,'dni_w_m2':sky.dni,'dhi_w_m2':sky.dhi,
        'ambient_temperature_c':28.,'wind_speed_m_s':1.,'pressure_pa':101025.},index=index)
    semantics=build_time_semantics(canonical_timezone='Asia/Jakarta',source_timestamp_convention='interval_start',
        native_interval_seconds=3600,current_interval_seconds=3600,source_timezone='Asia/Jakarta',source_utc_offset_hours=7.)
    return build_weather_dataset(series,weather_dataset_id='use5-weather',revision_id='use5-weather-r1',
        name='Synthetic Ineichen clear sky, Jakarta 2025',site_id='use5-site',timezone='Asia/Jakarta',
        native_resolution_seconds=3600,source_format='synthetic_reference',source_timestamp_convention='interval_start',
        location={'latitude_deg':-6.2,'longitude_deg':106.8,'elevation_m':25.},native_series_origin='provider_generated',
        series_origin='provider_generated',time_semantics=semantics)


def physics_fixture(tmp_path, *, circular=False, baseline=False, periods=8760, canonical=False):
    azimuths=[354.,0.,6.] if circular else [300.,330.,0.,30.,60.]
    per_field=5 if circular else 20
    p=Project(tmp_path,per_field,weather=False,strings=False)
    for field_index in range(1,len(azimuths)):
        roof=p.service.add_surface_rectangle(p.pid,name=f'Class {field_index}',origin_x_m=field_index*80,origin_y_m=0,
            width_m=1+per_field*1.154-.01,height_m=3.45,base_elevation_m=6.1,surface_type='flat_roof',usable_for_pv=True)
        surface=roof['bundle']['scene']['surfaces'][-1]['surface_id']
        p.service.create_pv_field(p.pid,name=f'Class {field_index}',support_surface_id=surface,
            module_definition_revision_id=MODULE,tilt_deg=10.,row_pitch_m=3.2,perimeter_setback_m=.5,obstacle_setback_m=.3)
    bundle=p.bundle();scene=bundle['scene'];electrical=deepcopy(bundle['electrical_design'])
    fields=scene['pv_fields']
    for field,azimuth in zip(fields,azimuths):field['azimuth_deg']=0. if baseline and circular else azimuth
    placements=[[m['module_instance_id'] for m in scene['module_instances'] if m['pv_field_id']==f['pv_field_id']] for f in fields]
    iid=electrical['inverter_instances'][0]['inverter_instance_id']
    module=deepcopy(bundle['pinned_components']['modules'][MODULE])
    inverter=deepcopy(bundle['pinned_components']['inverters'][INVERTER])
    count=1 if circular else 10
    inverter['revision_id']='inv-use5-runtime-synthetic-r1'
    inverter.setdefault('metadata',{})['synthetic_use5_fixture']=True
    inverter['mppt_template'].update(count=count,total_input_count=count,input_count_per_mppt=1)
    electrical['inverter_instances'][0]['inverter_definition_revision_id']=inverter['revision_id']
    electrical['mppt_instances']=[];electrical['strings']=[]
    for i in range(count):
        sid=f'use5-S{i:02d}';mid=f'use5-M{i:02d}'
        ids=sum(placements,[]) if circular else (placements[i//2][(i%2)*10:(i%2+1)*10] if baseline else sum([ids[i*2:i*2+2] for ids in placements],[]))
        electrical['mppt_instances'].append({'mppt_instance_id':mid,'inverter_instance_id':iid,'index':i+1,'enabled':True,'connected_string_ids':[sid]})
        electrical['strings'].append({'string_id':sid,'module_instance_ids':ids,'target_mppt_instance_id':mid,'enabled':True})
    compiled=compile_shading_geometry(scene)
    plan=build_simulation_execution_plan(scene,electrical,compiled_shading_geometry=compiled)
    bindings={}
    settings=resolve_loss_settings(default_loss_settings())
    for unit in execution_units(plan):
        is_class=unit not in plan['groups']
        assignments={m['index']:tuple(m['connected_string_ids']) for m in electrical['mppt_instances'] if m['mppt_instance_id'] in unit.get('mppt_instance_ids',[])}
        config=UnshadedFixedTiltConfiguration(simulation_timestep_seconds=3600,
            surface_tilt_deg=unit['surface_tilt_deg'],surface_azimuth_deg=unit['surface_azimuth_deg'],poa_model_id=POA_ISOTROPIC,
            module_definition=module,inverter_definition=inverter,modules_in_series=15 if circular else 10,
            string_ids=tuple(unit.get('string_ids',[])),mppt_assignments=assignments,u_c_w_m2k=20.,u_v_w_m2k_per_ms=0.,
            inverter_instance_id=iid,inverter_model_id=INVERTER_VOLTAGE_DEPENDENT_BOUNDED,loss_settings=settings)
        bindings[unit['execution_group_id']]={'group':unit,'config':config,'shading_mode':'beam_only_geometry','is_class':is_class}
    # Use the same product geometry contract, with beam-only optics for this fixture.
    from apps.api.study import _phase5_configuration
    from tests.unit.test_phase49c_reference_projects import _reference
    shading=_phase5_configuration(_reference('R1')['project_revision'],configuration_id='use5-runtime')['shading_configuration']
    shading.update(diffuse_method='none',albedo_method='none')
    weather=annual_weather(periods)
    if canonical:
        from electrical.topology import ElectricalTopologyEditorSession,new_electrical_design
        from engine.simulation import build_project_revision_from_design,build_design_revision_store
        session=ElectricalTopologyEditorSession(scene,new_electrical_design(project_id=scene['project_id'],
            electrical_revision_id='use5-runtime-electrical',pcc_id='use5-runtime-pcc'),
            project_revision_id='use5-runtime-project',module_definitions={module['revision_id']:module},
            inverter_definitions={inverter['revision_id']:inverter})
        session.add_inverter(inverter_instance_id=iid,inverter_definition_revision_id=inverter['revision_id'],name='USE5 synthetic inverter')
        for i,string in enumerate(electrical['strings']):
            session.create_string(string_id=string['string_id'],module_instance_ids=string['module_instance_ids'])
            session.assign_strings_to_mppt([string['string_id']],mppt_instance_id=f'{iid}-mppt-{i+1:02d}')
        electrical=session.commit_revision(electrical_revision_id='use5-runtime-electrical-r1',revision_number=2,
            change_summary='USE5 matched runtime fixture',created_at='2026-11-14T00:00:00Z')
        project=build_project_revision_from_design(scene,electrical,project_revision_id='use5-runtime-project',
            revision_number=1,weather_dataset_revision_id=weather.dataset['revision_id'])
        configuration=_phase5_configuration(project,configuration_id='use5-runtime-config')
        configuration['shading_configuration']=shading
        components={module['revision_id']:module,inverter['revision_id']:inverter}
        return project,configuration,build_design_revision_store(scene,electrical,weather,components)
    return weather,bindings,plan,compiled,shading


def test_circular_roof_annual_mismatch_low_sun_and_pr(tmp_path,record_property):
    weather,bindings,plan,compiled,shading=physics_fixture(tmp_path/'mixed',circular=True)
    mixed,_=run_multi_group_physics(weather,bindings=bindings,plan=plan,compiled_geometry=compiled,
        shading_configuration=shading,geometry=False)
    weather,b,pl,c,s=physics_fixture(tmp_path/'uniform',circular=True,baseline=True)
    uniform,_=run_multi_group_physics(weather,bindings=b,plan=pl,compiled_geometry=c,shading_configuration=s,geometry=False)
    frame=mixed.timeseries
    energy=mixed.energy.annual
    mismatch=100*energy['orientation_mismatch_loss_kwh']/energy['raw_array_mpp_kwh']
    low=(90-frame['solar_zenith_deg'])<20
    total=frame['orientation_mismatch_loss_w'].sum()
    low_share=100*frame.loc[low,'orientation_mismatch_loss_w'].sum()/total if total else 0.
    pr_difference=mixed.kpis['performance_ratio']-uniform.kpis['performance_ratio']
    print(f'USE5 circular roof: annual_mismatch_pct={mismatch:.9f}, low_sun_share_pct={low_share:.6f}, PR_difference={pr_difference:.9f}')
    for key,value in [('annual_mismatch_pct',mismatch),('low_sun_share_pct',low_share),('pr_difference',pr_difference)]:record_property(key,float(value))
    assert 0<=mismatch<1
    assert abs(pr_difference)<.01
    assert mixed.metadata['mixed_orientation']['is_complete_year']
