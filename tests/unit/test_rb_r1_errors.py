"""Unexpected failures are logged; deliberate validation remains unchanged."""
import pytest
from fastapi.testclient import TestClient
from tests.unit.test_rb_fix_s12b_weather_import import http, upload
from tests.unit.test_rb_r1_meteonorm import dat


def test_unexpected_api_error_is_plain_and_detail_is_logged(http,monkeypatch,caplog):
    app,_,pid,_=http
    def fail(*args,**kwargs):
        raise RuntimeError('/tmp/private-r1-path')
    monkeypatch.setattr(app.state.project_service,'project_view',fail)
    with TestClient(app,raise_server_exceptions=False) as client:
        response=client.get(f'/api/projects/{pid}')
    assert response.status_code==500
    assert response.json()=={'detail':{'code':'unexpected_error','message':'The request could not be completed. Please try again.'}}
    assert 'private-r1' not in response.text
    assert 'private-r1' in caplog.text


def test_deliberate_validation_message_is_preserved(http,monkeypatch):
    app,client,pid,_=http
    def fail(*args,**kwargs):raise ValueError('Existing deliberate validation.')
    monkeypatch.setattr(app.state.project_service,'project_view',fail)
    response=client.get(f'/api/projects/{pid}')
    assert response.status_code==422
    assert response.json()=={'detail':'Existing deliberate validation.'}


@pytest.mark.parametrize('filename,raw,reason',[
    ('short.epw',b'LOCATION,x\n','EPW location header is incomplete'),
    ('hour.dat',dat().replace(b'1 1 1 1 0 ',b'1 1 1 99999999999999999999 0 ',1),'Meteonorm DAT hour must be within 0..24'),
])
def test_unreadable_weather_import_has_plain_reason(http,caplog,filename,raw,reason):
    _,client,pid,_=http
    response=upload(client,pid,raw,filename)
    assert response.status_code==422
    detail=response.json()['detail']
    assert detail['code']=='weather_parse_failed'
    assert reason in detail['message']
    assert not any(word in detail['message'] for word in ['KeyError','OverflowError',"'altitude'",'Python int'])
    assert caplog.records


def test_unexpected_reader_failure_does_not_become_a_raw_parse_message(http,monkeypatch,caplog):
    from apps.api import study
    _,client,pid,_=http
    def fail(*args,**kwargs):raise KeyError('private-reader-field')
    monkeypatch.setattr(study,'read_weather_bytes',fail)
    response=upload(client,pid)
    assert response.status_code==422
    assert response.json()['detail']=={'code':'weather_parse_failed','message':'The weather file could not be parsed: the file contains invalid or incomplete data.'}
    assert 'private-reader-field' in caplog.text


def test_unexpected_component_parser_failure_is_logged_not_returned(http,monkeypatch,caplog):
    from apps.api import component_library
    app,_,_,_=http
    def fail(*args,**kwargs):raise KeyError('private-component-field')
    monkeypatch.setattr(component_library,'parse_pan_text',fail)
    with TestClient(app,raise_server_exceptions=False) as client:
        response=client.post('/api/component-library/imports',params={'filename':'synthetic.pan'},content=b'PVObject=PVModule\n')
    assert response.status_code==500
    assert response.json()['detail']['code']=='unexpected_error'
    assert 'private-component-field' not in response.text
    assert 'private-component-field' in caplog.text
