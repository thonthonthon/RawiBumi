"""S12b HTTP import: public/synthetic bytes, disposable stores, no network provider."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import csv
import hashlib
import io
import json
from pathlib import Path
from threading import Event

import numpy as np
import pandas as pd
from pvlib.solarposition import get_solarposition
from fastapi.testclient import TestClient
import pytest

from apps.api.server import create_app
from weather.core import build_time_semantics
from weather.importer import read_weather_bytes

ROOT=Path(__file__).resolve().parents[2]
FIX=ROOT/'tests/fixtures/weather'
NATIVE=(FIX/'opensimpv_hourly.csv').read_bytes()


def synthetic_dat():
    header='Synthetic fictional Meteonorm\n6.2 [deg S], 106.8 [deg E], 20 [m], 7 [timezone h], -30 [time ref. min]\nm dm dy h mi G_Gh G_Dh G_Bn Ta FF\n'
    return (header+'\n'.join(f'1 1 1 {h} 0 {h*10} {h*2} {h*12} 25 1' for h in range(1,25))+'\n').encode()


def synthetic_full_year():
    """In-test fictional solar-shaped profile, not observations or a copied private file."""
    index=pd.date_range('2001-01-01','2002-01-01',freq='h',inclusive='left',tz='Asia/Jakarta')
    position=get_solarposition(index+pd.Timedelta(minutes=30),-6.2,106.8)
    cosine=np.maximum(0,np.cos(np.deg2rad(position.apparent_zenith)))
    header=('# format=OpenSIMPV Weather CSV v0.1\n# timezone=Asia/Jakarta\n# native_resolution_seconds=3600\n'
        '# latitude_deg=-6.2\n# longitude_deg=106.8\n# elevation_m=20\n# provenance=Fictional deterministic test profile\n')
    table=pd.DataFrame({'timestamp':[t.isoformat() for t in index],'ghi_w_m2':800*cosine,
        'dni_w_m2':np.where(cosine>0,700,0),'dhi_w_m2':100*cosine,'ambient_temperature_c':25,'wind_speed_m_s':1})
    return (header+table.to_csv(index=False,float_format='%.6f')).encode()


@pytest.fixture
def http(tmp_path):
    app=create_app(store_root=tmp_path/'projects',library_root=tmp_path/'library')
    with TestClient(app) as c:
        r=c.post('/api/projects',json={'name':'Synthetic weather import','latitude_deg':-6.2,'longitude_deg':106.8,'timezone':'Asia/Jakarta','elevation_m':20})
        assert r.status_code==201
        pid=r.json()['bundle']['project']['project_id']
        yield app,c,pid,tmp_path


def upload(c,pid,raw=NATIVE,filename='synthetic.csv',dry=False,accept=False):
    return c.post(f'/api/projects/{pid}/weather/import',params={'filename':filename,'dry_run':dry,'accept_distant_location':accept},content=raw,headers={'Content-Type':'application/octet-stream'})


def tree(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def source_monthly(raw,filename):
    """Independent source-column energy oracle; no route/canonical frame access."""
    text=raw.decode();lines=text.splitlines();values=[]
    if filename.endswith('.epw'):
        for row in csv.reader(lines[8:]):values.append((int(row[1]),float(row[13])/1000))
    elif filename.endswith('.tm3'):
        for row in csv.DictReader(lines[1:]):values.append((int(row['Date (MM/DD/YYYY)'].split('/')[0]),float(row['GHI (W/m^2)'])/1000))
    elif filename.endswith('.dat'):
        for line in lines[3:]:
            row=line.split();values.append((int(row[0]),float(row[5])/1000))
    elif text.startswith('#Weather'):
        start=next(i for i,line in enumerate(lines) if line.startswith('Year;'))
        reader=csv.DictReader([lines[start],*lines[start+2:]],delimiter=';')
        values=[(int(row['Month']),float(row['GHI'])/1000) for row in reader]
    else:
        reader=csv.DictReader(line for line in lines if not line.startswith('#'))
        values=[(int(row['timestamp'][5:7]),float(row['ghi_w_m2'])/1000) for row in reader]
    return [sum(v for m,v in values if m==month) for month in range(1,13)]


@pytest.mark.parametrize('filename,raw,kind,count',[
    ('synthetic.epw',(FIX/'epw_minimal.epw').read_bytes(),'epw',4),
    ('synthetic.tm3',(FIX/'tmy3_minimal.csv').read_bytes(),'tmy3',4),
    ('synthetic.csv',NATIVE,'opensimpv_csv',4),
    ('synthetic.csv',(FIX/'pvsyst_standard_hourly.csv').read_bytes(),'pvsyst_standard_csv',4),
    ('synthetic.dat',synthetic_dat(),'meteonorm_dat',24),
])
def test_each_format_preview_then_commit_and_independent_energy(http,filename,raw,kind,count):
    app,c,pid,root=http;before=tree(root)
    r=upload(c,pid,raw,filename,dry=True);assert r.status_code==200,r.text
    p=r.json();assert p['format']==kind and p['row_count']==count and p['step_minutes']==60
    assert p['period']['start'].endswith('+07:00') and p['period']['end'].endswith('+07:00')
    assert p['monthly_ghi_kwh_m2']==pytest.approx(source_monthly(raw,filename))
    assert p['annual_ghi_kwh_m2']==pytest.approx(sum(source_monthly(raw,filename)))
    assert p['qc']['status'] in {'passed','warning'} and p['distance_km']==pytest.approx(0)
    assert tree(root)==before
    r=upload(c,pid,raw,filename);assert r.status_code==200,r.text
    result=r.json();selection=result['selection'];digest=hashlib.sha256(raw).hexdigest()
    bundle=c.get(f'/api/projects/{pid}').json()['bundle']
    assert bundle['weather_selection']==selection
    assert bundle['project']['project_revision']['weather_dataset_revision_id']==selection['revision_id']
    manifest=result['manifest'];assert manifest==selection['manifest']
    assert manifest['kind']=='file_import' and manifest['sha256']==digest and manifest['size']==len(raw)
    assert manifest['format']==kind and manifest['filename']==filename
    assert manifest['importer'] and manifest['importer_version'] and manifest['imported_at']
    assert manifest['location']==p['location'] and manifest['distance_km']==p['distance_km']
    assert manifest['warnings']==p['warnings'] and not manifest['accepted_distant_location']
    assert app.state.study_service.snapshots.get(digest,suffix='.weather')==raw


def test_dedup_reselects_original_revision_and_rechecks_site(http):
    app,c,pid,root=http
    first=upload(c,pid).json()['selection'];weather_before=tree(root/'weather')
    other=upload(c,pid,NATIVE.replace(b',100,120,40,',b',101,120,40,'),'other.csv').json()['selection']
    assert other['revision_id']!=first['revision_id']
    r=upload(c,pid,filename='renamed.csv');assert r.status_code==200 and r.json()['duplicate']
    assert r.json()['selection']==first
    assert len(list((root/'weather'/pid).iterdir()))==2
    assert all(tree(root/'weather')[p]==v for p,v in weather_before.items())
    assert c.patch(f'/api/projects/{pid}/site',json={'latitude_deg':-5.12,'clear_weather_selection':True}).status_code==200
    before=tree(root)
    r=upload(c,pid);assert r.status_code==422 and r.json()['detail']['code']=='weather_location_distant'
    assert tree(root)==before


@pytest.mark.parametrize('delta,requires',[(.27,False),(1.08,True)])
def test_distance_thresholds_and_acceptance(http,delta,requires):
    _,c,pid,root=http
    raw=NATIVE.replace(b'# latitude_deg=-6.2',f'# latitude_deg={-6.2+delta}'.encode())
    p=upload(c,pid,raw,dry=True).json()
    assert p['requires_accept_distant_location']==requires
    assert (110<p['distance_km']<130) if requires else (20<p['distance_km']<40)
    assert any(w['code']=='weather_location_distant' for w in p['warnings'])
    before=tree(root);r=upload(c,pid,raw)
    if requires:
        assert r.status_code==422 and tree(root)==before
        r=upload(c,pid,raw,accept=True)
    assert r.status_code==200,r.text
    assert r.json()['manifest']['accepted_distant_location']==requires


def test_unknown_location_elevation_and_timezone_warning_without_retiming(http):
    app,c,pid,_=http
    raw=b'\n'.join(line for line in NATIVE.splitlines() if not line.startswith((b'# latitude_deg=',b'# longitude_deg=')))+b'\n'
    raw=raw.replace(b'# elevation_m=20',b'# elevation_m=1000').replace(b'Asia/Jakarta',b'UTC')
    # Explicit source offset preserved by the existing native CSV metadata contract.
    metadata=build_time_semantics(canonical_timezone='UTC',source_timezone='UTC',source_utc_offset_hours=0,
        source_timestamp_convention='interval_start',native_interval_seconds=3600,current_interval_seconds=3600)
    raw=(f'# time_semantics_json={json.dumps(metadata)}\n'.encode()+raw)
    # Detector requires the format marker first.
    lines=raw.splitlines();raw=b'\n'.join([lines[1],lines[0],*lines[2:]])+b'\n'
    p=upload(c,pid,raw,dry=True);assert p.status_code==200,p.text
    assert {'weather_location_unknown','weather_elevation_differs','weather_timezone_differs'}<={w['code'] for w in p.json()['warnings']}
    expected=read_weather_bytes(raw,weather_dataset_id='independent',revision_id='independent-r1',site_id='site',name='test',filename='synthetic.csv')
    r=upload(c,pid,raw);assert r.status_code==200,r.text
    saved=app.state.study_service.weather.load(pid,r.json()['selection']['revision_id'])
    assert saved.series.index.equals(expected.series.index)


@pytest.mark.parametrize('raw,filename,code',[(b'','empty.csv','weather_file_empty'),(b'nothing recognized','unknown.txt','weather_format_unsupported'),
    (b'PVObject_=pvMeteo\n Day_0101=synthetic\n','synthetic.MET','pvsyst_met_not_supported'),
    (b'\x00\xff','synthetic.MET','pvsyst_met_not_supported'),
    (b'LOCATION,broken\n','broken.epw','weather_parse_failed'),
    (NATIVE.replace(b'# latitude_deg=-6.2',b'# latitude_deg=nan'),'bad-location.csv','weather_parse_failed'),
    (NATIVE.replace(b',100,120,40,',b',-100,120,40,'),'failed.csv','weather_quality_failed'),
    (NATIVE.replace(b',100,120,40,',b',nan,120,40,'),'missing.csv','weather_quality_failed')])
def test_refusal_nothing_written(http,raw,filename,code):
    _,c,pid,root=http;before=tree(root)
    r=upload(c,pid,raw,filename);assert r.status_code==422,r.text
    assert r.json()['detail']['code']==code and r.json()['detail']['message']
    assert tree(root)==before


def test_oversize_unknown_project_and_failed_preview(http):
    _,c,pid,root=http;before=tree(root)
    r=upload(c,pid,b'x'*(50*1024*1024+1));assert r.status_code==413 and r.json()['detail']['code']=='weather_file_too_large'
    assert upload(c,'project-missing').status_code==404
    p=upload(c,pid,NATIVE.replace(b',100,120,40,',b',nan,120,40,'),dry=True)
    assert p.status_code==200 and p.json()['qc']['status']=='failed'
    assert p.json()['monthly_ghi_kwh_m2'][0] is None and p.json()['annual_ghi_kwh_m2'] is None
    assert tree(root)==before


@pytest.mark.parametrize("reverse",[True,False])
def test_mixed_epw_refusal_and_continuous_cross_year_allowed(http,reverse):
    _,c,pid,root=http;lines=(FIX/'epw_minimal.epw').read_text().splitlines()
    def variant(labels):
        rows=[]
        for label,row in zip(labels,lines[8:]):
            cells=row.split(',');cells[:4]=map(str,label);rows.append(','.join(cells))
        return ('\n'.join(lines[:8]+rows)+'\n').encode()
    raw=variant([(1996 if reverse else 1990,2,28,23),(1996 if reverse else 1990,2,28,24),(1990 if reverse else 1996,3,1,1),(1990 if reverse else 1996,3,1,2)])
    before=tree(root);preview=upload(c,pid,raw,'mixed.epw',dry=True)
    assert preview.status_code==200 and preview.json()['qc']['status']=='failed'
    assert any(w['code']=='weather_typical_year_mixed_years' for w in preview.json()['warnings'])
    r=upload(c,pid,raw,'mixed.epw');assert r.status_code==422
    assert r.json()['detail']['code']=='weather_quality_failed' and r.json()['detail']['reason_code']=='weather_typical_year_mixed_years'
    assert "PVsyst Standard" in r.json()['detail']['message'] and tree(root)==before
    raw=variant([(2025,12,31,23),(2025,12,31,24),(2026,1,1,1),(2026,1,1,2)])
    r=upload(c,pid,raw,'continuous.epw');assert r.status_code==200,r.text
    assert not any(w['code']=='weather_typical_year_mixed_years' for w in r.json()['manifest']['warnings'])


def test_busy_guard_and_scene_edit_during_import_is_preserved(http,monkeypatch):
    app,c,pid,root=http;study=app.state.study_service;before=tree(root)
    with study._project_operation(pid):
        r=upload(c,pid);assert r.status_code==409 and 'in progress' in r.json()['detail']
    assert tree(root)==before
    import apps.api.study as module
    real=module.read_weather_bytes;entered=Event();release=Event()
    def slow(*args,**kwargs):
        entered.set();assert release.wait(15);return real(*args,**kwargs)
    monkeypatch.setattr(module,'read_weather_bytes',slow)
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(upload,c,pid)
        try:
            assert entered.wait(10)
            assert c.patch(f'/api/projects/{pid}/site',json={'elevation_m':50}).status_code==409
            changed=c.post(f'/api/projects/{pid}/surfaces/rectangle',json={'name':'Concurrent roof','width_m':8,'height_m':8})
            assert changed.status_code==200,changed.text
        finally:release.set()
        assert future.result().status_code==200
    assert any(s['name']=='Concurrent roof' for s in c.get(f'/api/projects/{pid}').json()['bundle']['scene']['surfaces'])


def test_full_year_simulation_and_provider_run_provenance_preserved(http):
    app,c,pid,root=http;url=f'/api/projects/{pid}'
    pan=(ROOT/'tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN').read_bytes()
    module=c.post('/api/component-library/imports?filename=public.pan',content=pan).json()['entry']['revision_id']
    roof=c.post(url+'/surfaces/rectangle',json={'name':'Synthetic roof','width_m':1+8*1.154-.01,'height_m':3.45,'base_elevation_m':6.1})
    assert roof.status_code==200;sid=roof.json()['bundle']['scene']['surfaces'][0]['surface_id']
    for endpoint,body in [('/pv-fields',{'name':'Synthetic array','support_surface_id':sid,'module_definition_revision_id':module,'tilt_deg':10,'row_pitch_m':3.2,'perimeter_setback_m':.5}),
        ('/inverters',{'name':'INV','inverter_definition_revision_id':'inv-rawibumi-uat-150k-r1'}),('/strings',{'string_length':8})]:
        r=c.post(url+endpoint,json=body);assert r.status_code==200,r.text
    iid=r.json()['bundle']['electrical_design']['inverter_instances'][0]['inverter_instance_id']
    assert c.post(url+'/assignments',json={'inverter_instance_id':iid}).status_code==200
    study=app.state.study_service
    study.acquire_weather(pid,source_id='open_meteo_archive_era5',start_date='2025-01-01',end_date='2025-01-01',raw_response=(FIX/'open_meteo_era5_phase60d_uat_padded_s10.json').read_bytes())
    first=c.post(url+'/simulate',json={});assert first.status_code==200 and first.json()['status'].startswith('completed'),first.text
    old=deepcopy(app.state.project_service.get_bundle(pid)['simulation_runs']);artifacts=tree(root/'runs'/pid)
    raw=synthetic_full_year();p=upload(c,pid,raw,'full.csv',dry=True);assert p.status_code==200 and p.json()['row_count']==8760
    assert p.json()['monthly_ghi_kwh_m2']==pytest.approx(source_monthly(raw,'full.csv'))
    imported=upload(c,pid,raw,'full.csv');assert imported.status_code==200,imported.text
    assert app.state.project_service.get_bundle(pid)['simulation_runs']==old and tree(root/'runs'/pid)==artifacts
    ready=c.get(url+'/execution-readiness');assert ready.status_code==200 and ready.json()['ready'],ready.text
    run=c.post(url+'/simulate',json={});assert run.status_code==200 and run.json()['status'].startswith('completed'),run.text
    assert run.json()['weather_dataset_revision_id']==imported.json()['selection']['revision_id']
    assert app.state.project_service.get_bundle(pid)['simulation_runs'][0]==old[0]
    assert all(tree(root/'runs'/pid)[p]==v for p,v in artifacts.items())


def test_pvsyst_source_utc_warning_preserves_importer_shift(http):
    app,c,pid,_=http
    raw=(FIX/'pvsyst_standard_hourly.csv').read_bytes().replace(b'#Time Zone;7',b'#Time Zone;7\n#Time reference;UT')
    expected=read_weather_bytes(raw,weather_dataset_id='independent',revision_id='independent-r1',name='source UTC',site_id='site',filename='source.csv')
    preview=upload(c,pid,raw,dry=True).json()
    assert preview['time_zone']['source_utc_offset_hours']==0
    assert preview['time_zone']['canonical_timezone']=='UTC+07:00'
    assert any(w['code']=='weather_timezone_differs' for w in preview['warnings'])
    result=upload(c,pid,raw);assert result.status_code==200,result.text
    actual=app.state.study_service.weather.load(pid,result.json()['selection']['revision_id'])
    assert actual.series.index.equals(expected.series.index)
