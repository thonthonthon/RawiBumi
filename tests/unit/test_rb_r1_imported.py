"""Imported provenance belongs only to saved project run records."""
import json
from tests.unit.test_rb_data1_project_files import p, state, export, delete, import_


def test_import_marks_records_without_changing_run_packages_or_numbers(p):
    before=state(p)
    local=p.bundle()['simulation_runs']
    assert local and all('origin' not in run for run in local)
    data=export(p)
    delete(p)
    response=import_(p,data)
    assert response.status_code==200,response.text
    imported=p.bundle()['simulation_runs']
    assert all(run.get('origin')=='imported' for run in imported)
    assert [{k:v for k,v in run.items() if k!='origin'} for run in imported]==local
    after=state(p)
    for key in ('weather','runs','imagery'): assert after[key]==before[key]
    for data in after['runs'].values():
        if data.startswith(b'{'):
            assert 'origin' not in json.loads(data)
    computed=p.client.post(p.url+'/simulate',json={})
    assert computed.status_code==200,computed.text
    assert 'origin' not in p.bundle()['simulation_runs'][-1]
