from copy import deepcopy
from pathlib import Path
import pytest
from apps.api.server import create_app
from fastapi.testclient import TestClient


def project(tmp_path):
    app=create_app(store_root=tmp_path/'projects',library_root=tmp_path/'library')
    view=app.state.project_service.create_project(name='Synthetic site',latitude_deg=-6.2,longitude_deg=106.8,elevation_m=25,timezone_name='Asia/Jakarta',workspace_mode='blank_engineering_plane')
    pid=view['project']['project_id']
    return app,TestClient(app),pid


def test_old_project_unchanged_and_report_site_details_roundtrip(tmp_path):
    app,client,pid=project(tmp_path);path=app.state.project_service.store.path_for(pid);before=path.read_bytes()
    url=f'/api/projects/{pid}';view=client.get(url).json();fingerprint=view['design_fingerprint']
    assert path.read_bytes()==before and 'address' not in view['bundle']['project']['site']
    address={'text':'Synthetic road','source':'user','lat':-6.2,'lon':106.8,'attribution':None,'updatedAt':'2026-11-16T00:00:00Z'}
    installation={'installationType':'hybrid','bessEnergyKwh':12.,'bessPowerKw':3.}
    response=client.patch(url+'/site/details',json={'address':address,'installation':installation})
    assert response.status_code==200,response.text
    saved=client.get(url).json();assert saved['design_fingerprint']==fingerprint
    assert saved['bundle']['project']['site']['address']==address
    assert saved['bundle']['project']['site']['installation']==installation


@pytest.mark.parametrize('payload',[
    {'address':{'text':'x'*2001,'source':'user','lat':0,'lon':0,'attribution':None,'updatedAt':'2026-11-16T00:00:00Z'}},
    {'address':{'text':'x','source':'user','lat':91,'lon':0,'attribution':None,'updatedAt':'2026-11-16T00:00:00Z'}},
    {'installation':{'installationType':'invented','bessEnergyKwh':0,'bessPowerKw':0}},
    {'installation':{'installationType':'hybrid','bessEnergyKwh':-1,'bessPowerKw':0}}])
def test_invalid_site_details_refused_without_mutation(tmp_path,payload):
    app,client,pid=project(tmp_path);path=app.state.project_service.store.path_for(pid)
    assert client.patch(f'/api/projects/{pid}/site/details',json={'address':None}).status_code==200
    before=path.read_bytes()
    assert client.patch(f'/api/projects/{pid}/site/details',json=payload).status_code==422
    assert path.read_bytes()==before


def test_browser_copy_cannot_overwrite_a_project_value(tmp_path):
    app,client,pid=project(tmp_path);url=f'/api/projects/{pid}/site/details'
    address={'text':'Existing project address','source':'user','lat':0,'lon':0,'attribution':None,'updatedAt':'2026-11-16T00:00:00Z'}
    assert client.patch(url,json={'address':address}).status_code==200
    response=client.patch(url,json={'address':{**address,'text':'Old browser value'},'copy_if_missing':True})
    assert response.status_code==200,response.text
    assert response.json()['bundle']['project']['site']['address']==address


def test_details_do_not_rebuild_lcs_bump_revision_or_create_undo_entries(tmp_path, monkeypatch):
    app,client,pid=project(tmp_path);service=app.state.project_service
    before=deepcopy(service.get_bundle(pid));url=f'/api/projects/{pid}'
    from apps.api.service import LocalCoordinateSystem
    class NoNewOrigin:
        from_mapping=staticmethod(LocalCoordinateSystem.from_mapping)
        def __new__(cls,*args,**kwargs):raise AssertionError('metadata must not rebuild the local coordinate system')
    monkeypatch.setattr('apps.api.service.LocalCoordinateSystem',NoNewOrigin)
    response=client.patch(url+'/site/details',json={'installation':{'installationType':'hybrid'}})
    assert response.status_code==200,response.text
    saved=response.json()['bundle']
    assert saved['project']['project_revision']==before['project']['project_revision']
    assert saved['project']['site']['local_coordinate_system']==before['project']['site']['local_coordinate_system']
    assert response.json()['history']['past']==[]
    assert saved['scene']==before['scene']
    for body in ({'latitude_deg':-7},{'clear_weather_selection':True},{'copy_if_missing':True},{}):
        assert client.patch(url+'/site/details',json=body).status_code==422
    for key,value in [('address',None),('installation',None),('copy_if_missing',True)]:
        assert client.patch(url+'/site',json={key:value}).status_code==422
