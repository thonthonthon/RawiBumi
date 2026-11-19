"""Late report metadata must neither consume nor invalidate a design undo/redo."""
from copy import deepcopy
import pytest
from apps.api.history import projection
from tests.unit.test_rb_rpt2b1_site import project
from tests.unit.test_rb_s17_history import fence


def details(text,source='lookup'):
    return {'address':{'text':text,'source':source,'lat':-6.2,'lon':106.8,
                       'attribution':None,'updatedAt':'2026-11-16T00:00:00Z'},
            'installation':{'installationType':'hybrid','bessEnergyKwh':12.,'bessPowerKw':3.}}


@pytest.mark.parametrize('latest',[details('Late automatic lookup'),{'address':None,'installation':None}])
def test_issued_undo_and_redo_preserve_current_site_details(tmp_path,latest):
    app,client,pid=project(tmp_path);url=f'/api/projects/{pid}'
    assert client.patch(url+'/site/details',json=details('Older typed value','user')).status_code==200
    before=client.get(url).json()
    response=client.post(url+'/surfaces/rectangle',json={'name':'Synthetic roof','width_m':10.,'height_m':6.,'base_elevation_m':6.})
    assert response.status_code==200,response.text
    edited=response.json();issued=fence(edited)
    response=client.patch(url+'/site/details',json=latest);assert response.status_code==200,response.text
    assert response.json()['history']==edited['history']
    undone=client.post(url+'/undo',json=issued);assert undone.status_code==200,undone.text
    undone=undone.json()
    assert projection(undone['bundle'])==projection(before['bundle'])
    assert {key:undone['bundle']['project']['site'][key] for key in latest}==latest
    issued_redo=fence(undone,True)
    newer=details('Typed after Undo','user')
    assert client.patch(url+'/site/details',json=newer).status_code==200
    redone=client.post(url+'/redo',json=issued_redo);assert redone.status_code==200,redone.text
    redone=redone.json()
    assert projection(redone['bundle'])==projection(edited['bundle'])
    assert {key:redone['bundle']['project']['site'][key] for key in newer}==newer


def test_typed_details_do_not_add_an_undo_step_or_mutate_design(tmp_path):
    app,client,pid=project(tmp_path);url=f'/api/projects/{pid}'
    before=client.get(url).json();original=deepcopy(before['bundle'])
    response=client.patch(url+'/site/details',json=details('Typed address','user'))
    assert response.status_code==200,response.text
    after=response.json()
    assert after['history']==before['history']
    assert projection(after['bundle'])==projection(original)
    assert after['bundle']['project']['project_revision']==original['project']['project_revision']
