"""Free CSV through registered, verified packages; the fixture forbids simulation."""
from copy import deepcopy
import csv
from hashlib import sha256
from io import BytesIO, StringIO
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile
import numpy as np
import pandas as pd
import pytest
from engine.simulation.artifacts import canonical_json_bytes
from tests.unit.test_phase7_csv_export import persisted, rewrite_run, reseal

COLUMNS=['timestamp','ghi_wm2','dni_wm2','dhi_wm2','poa_wm2','t_ambient_c','t_cell_c','e_dc_inverter_kwh','e_ac_pcc_kwh','pr']
KWP=2.345678912


def frame(index=None, seconds=3600):
    if index is None:index=pd.date_range('2024-01-31T23:00:00+07:00',periods=4,freq='h')
    n=len(index);poa=np.resize([0.,1e-12,200.,1000.],n);energy=np.resize([-1.,-1e-6,100.,800.],n)*seconds/3600
    return pd.DataFrame({'timestamp':index,'interval_seconds':seconds,'ghi_w_m2':poa,'dni_w_m2':poa*.8,
        'dhi_w_m2':poa*.2,'poa_global_w_m2':poa,'ambient_temperature_c':25.,'cell_temperature_c':35.,
        'inverter_input_power_w':np.resize([0.,0.,150.,1000.],n),'pcc_power_w':energy*3600/seconds,'interval_energy_wh':energy})


@pytest.fixture
def package(persisted):
    def make(data=None, *, shaded=False, summary_change=None, transformations=None):
        data=frame() if data is None else data.copy()
        if shaded:
            data['poa_global_unshaded_w_m2']=data['poa_global_w_m2']
            data['poa_global_w_m2']*=.6
        case=persisted(frame=data)
        poa='poa_global_unshaded_w_m2' if shaded else 'poa_global_w_m2'
        total=float(data.interval_energy_wh.sum()) if 'interval_energy_wh' in data else float((data.pcc_power_w*data.interval_seconds/3600).sum())
        h=float((data[poa]*data.interval_seconds/3.6e6).sum())
        months=data.timestamp.dt.strftime('%Y-%m')
        monthly=(data.interval_energy_wh if 'interval_energy_wh' in data else data.pcc_power_w*data.interval_seconds/3600).groupby(months).sum()
        dt=int(data.interval_seconds.iloc[0]);duration=float(data.interval_seconds.sum()/3600)
        summary={'schema_name':'SummaryResult','schema_version':'0.1','simulation_run_id':case.run_id,
            'annual_energy_wh':total if duration in (8760.,8784.) else None,'total_energy_wh':total,
            'specific_yield_wh_per_wp':total/(KWP*1000),'performance_ratio':(total/1000)/(KWP*h) if h else 0.,
            'capacity_factor':.01,'monthly_energy':[{'month':m,'energy_wh':float(e)} for m,e in monthly.items()],
            'loss_summary':[],'peak_dc_power_w':1000.,'peak_ac_power_w':800.,'clipping_energy_wh':0.,'shading_energy_loss_wh':None,
            'data_quality_summary':{},'period_start_time':data.timestamp.iloc[0].isoformat(),
            'period_end_time':(data.timestamp.iloc[-1]+pd.Timedelta(seconds=dt)).isoformat(),'period_duration_hours':duration,
            'capacity_factor_basis':'installed_dc_nameplate_over_executed_period','resolved_loss_settings':{'simulated_dc_nameplate_w':KWP*1000}}
        if summary_change:summary_change(summary)
        (case.directory/'summary-result.json').write_bytes(canonical_json_bytes(summary))
        def update(run):
            run['summary_result']=summary
            run['reproducibility_manifest'].update(simulation_timestep_seconds=dt,working_weather_resolution_seconds=dt,
                native_weather_resolution_seconds=dt,weather_transformations=transformations or [])
            (case.directory/'reproducibility-manifest.json').write_bytes(canonical_json_bytes(run['reproducibility_manifest']))
        rewrite_run(case,update)
        case.summary=summary;case.study=case.app.state.study_service
        return case
    return make


def download(case):
    response=case.client.get(case.path+'/free-csv')
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    assert response.headers['content-type']=='application/zip'
    with ZipFile(BytesIO(response.content)) as z:
        assert z.namelist()==['rawibumi_free.csv','export-manifest.json']
        raw=z.read('rawibumi_free.csv');manifest=json.loads(z.read('export-manifest.json'))
    assert b'\r\n' not in raw
    return list(csv.DictReader(StringIO(raw.decode()))),manifest,raw


@pytest.mark.parametrize('writer', ['free','selectable'])
def test_each_interval_csv_writer_refuses_hostile_cells(package,writer):
    from reporting.exports.csv_export import export_zip
    case=package()
    source=case.study.csv_export_source(case.project_id,case.run_id)
    for hostile in [float('inf'),'=1+1','+cmd','-2+3','@SUM','\t=1','\r=1','Hostile field name']:
        source.frame['ambient_temperature_c']=hostile
        with pytest.raises(ValueError):
            if writer=='selectable':export_zip(source,['ambient_temperature_c'])
            else:
                from reporting.exports.free_csv import free_csv_zip
                free_csv_zip(source,case.summary)


def test_fixed_columns_units_offsets_provenance_and_immutability(package):
    case=package();before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in case.directory.rglob('*') if p.is_file()}
    project=case.app.state.project_service.store.path_for(case.project_id);project_before=project.read_bytes()
    rows,m,raw=download(case)
    assert list(rows[0])==COLUMNS and all(len(row)==10 for row in rows)
    assert len(rows)==4 and rows[0]['timestamp'].endswith('+07:00')
    assert math.isclose(sum(float(r['e_ac_pcc_kwh']) for r in rows)*1000,898.999999,rel_tol=1e-9)
    assert math.isclose(sum(float(r['e_dc_inverter_kwh']) for r in rows),1.15,rel_tol=1e-9)
    assert m['schema']=='rawibumi.free_csv.v1' and m['capability']=='export.csv.basic'
    assert m['csv_sha256']==sha256(raw).hexdigest()
    assert m['source_package_manifest_sha256'] and m['source_input_hashes'] and m['source_dataset']['sha256']
    assert m['aggregates']['period']['scope']=='period'
    assert m['dhi_basis']['state']=='not recorded'
    assert m['annual_pxx']['status']=='no_uncertainty_ledger'
    assert m['annual_pxx']['P99'] is None and m['annual_pxx']['P99_reason']=='P99_NOT_QUALIFIED'
    assert project.read_bytes()==project_before
    assert before=={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in case.directory.rglob('*') if p.is_file()}


@pytest.mark.parametrize('shaded',[False,True])
def test_pr_uses_engine_reference_and_energy_sum_ratios(package,shaded):
    case=package(shaded=shaded);rows,m,_=download(case)
    assert rows[0]['pr']=='' and float(rows[1]['pr'])<0
    assert float(rows[2]['pr'])==pytest.approx(.1/(KWP*.2),rel=1e-12)
    assert m['null_rules']['pr']['reasons']['no_poa_reference']==1
    assert m['bases']['poa_key']==('poa_global_unshaded_w_m2' if shaded else 'poa_global_w_m2')
    assert m['aggregates']['period']['pr']==pytest.approx(case.summary['performance_ratio'],rel=1e-9)
    month=m['aggregates']['monthly'][1]
    assert month['pr']==pytest.approx((.9-1e-9)/(KWP*(1.2+1e-15)),rel=1e-9)
    assert not math.isclose(month['pr'],np.mean([float(r['pr']) for r in rows[1:]]),rel_tol=1e-3)
    assert m['bases']['P_STC_kwp']==pytest.approx(KWP,rel=1e-12)


def test_mismatched_summary_pr_is_refused(package):
    case=package(summary_change=lambda s:s.update(performance_ratio=.123))
    r=case.client.get(case.path+'/free-csv');assert r.status_code==422 and 'performance_ratio' in r.text


def test_missing_source_is_empty_with_reason(package):
    case=package(frame().drop(columns=['ambient_temperature_c','inverter_input_power_w']))
    rows,m,_=download(case)
    for c in ('t_ambient_c','e_dc_inverter_kwh'):
        assert all(r[c]=='' for r in rows)
        assert m['null_rules'][c]['null_count']==4
        assert m['null_rules'][c]['reasons']=={'not_in_run_dataset':4}


@pytest.mark.parametrize('seconds',[60,1800])
def test_native_subhourly_cadence_and_energy(package,seconds):
    case=package(frame(pd.date_range('2024-02-01T10:00:00+07:00',periods=4,freq=f'{seconds}s'),seconds))
    rows,m,_=download(case)
    assert len(rows)==4 and m['source_interval']['interval_seconds']==seconds
    assert sum(float(r['e_dc_inverter_kwh']) for r in rows)==pytest.approx(1.15*seconds/3600,rel=1e-9)
    assert rows[1]['timestamp']==case.frame.timestamp.iloc[1].isoformat()


def test_leap_february_and_site_local_months(package):
    case=package(frame(pd.date_range('2024-02-01',periods=29*24,freq='h',tz='Asia/Jakarta')))
    rows,m,_=download(case)
    assert len(rows)==696 and len(m['aggregates']['monthly'])==1
    assert m['aggregates']['monthly'][0]['month']=='2024-02'
    assert m['aggregates']['monthly'][0]['e_ac_pcc_kwh']==pytest.approx(sum(float(r['e_ac_pcc_kwh']) for r in rows),rel=1e-9)


def test_no_daylight_and_missing_nameplate(package):
    data=frame();data[['ghi_w_m2','dni_w_m2','dhi_w_m2','poa_global_w_m2','inverter_input_power_w']]=0.
    data[['pcc_power_w','interval_energy_wh']]=-1.
    case=package(data);rows,m,_=download(case)
    assert all(r['pr']=='' for r in rows)
    assert m['aggregates']['period']['pr'] is None and m['aggregates']['period']['pr_reason']=='no_poa_reference'
    case=package(data,summary_change=lambda s:s.pop('resolved_loss_settings'))
    r=case.client.get(case.path+'/free-csv');assert r.status_code==422 and 'nameplate' in r.text


def test_missing_interval_energy_and_tampered_package_refused(package):
    case=package(frame().drop(columns=['interval_energy_wh']))
    r=case.client.get(case.path+'/free-csv');assert r.status_code==422 and 'interval_energy_wh' in r.text
    case=package();(case.directory/'timeseries.parquet').write_bytes(b'tampered')
    assert case.client.get(case.path+'/free-csv').status_code==422


def test_annual_pxx_matches_existing_view(package):
    from tests.unit.test_rb_unc1_annual_pxx import ledger
    case=package(frame(pd.date_range('2025-01-01',periods=8760,freq='h',tz='Asia/Jakarta')))
    projects=case.app.state.project_service;bundle=projects.get_bundle(case.project_id);bundle['uncertainty_assumptions']=ledger();projects.save_bundle(bundle)
    expected=case.study.annual_pxx(case.project_id,case.run_id)
    _,m,_=download(case)
    assert m['annual_pxx']['result']['quantiles']==expected['result']['quantiles']
    assert m['annual_pxx']['P99'] is None and m['annual_pxx']['P99_reason']=='P99_NOT_QUALIFIED'


def test_minute_full_year_performance_report_only(package,tmp_path):
    case=package(frame(pd.date_range('2025-01-01',periods=365*24*60,freq='min',tz='Asia/Jakarta'),60))
    script='''import json,resource,time,sys
from apps.api.server import create_app
app=create_app(store_root=sys.argv[1]);start=time.perf_counter()
blob=app.state.study_service.free_csv_export(sys.argv[2],sys.argv[3])
print(json.dumps({'wall_seconds':time.perf_counter()-start,'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'zip_bytes':len(blob)}))
'''
    env={**os.environ,'RAWIBUMI_PROJECT_STORE':str(tmp_path/'global'),'PYTHONDONTWRITEBYTECODE':'1'};env.pop('PYTHONSTARTUP',None)
    result=subprocess.run([sys.executable,'-c',script,str(case.app.state.project_service.store.root),case.project_id,case.run_id],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    print('RPT1 1-minute full-year export: '+result.stdout.strip())
