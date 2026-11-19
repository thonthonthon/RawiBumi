"""Verified package snapshots: no simulations and no mutable-design substitution."""
from copy import deepcopy
from hashlib import sha256
import json
import pytest
from apps.api.history import design_fingerprint
from engine.simulation.artifacts import canonical_json_bytes
from tests.unit.test_phase7_csv_export import persisted,rewrite_run
from tests.unit.test_rb_rpt1_free_csv import package


@pytest.fixture
def snapshot_case(package):
    def make(**kwargs):
        case=package(**kwargs);projects=case.app.state.project_service
        bundle=projects.get_bundle(case.project_id);fingerprint=design_fingerprint(bundle)
        bundle['simulation_runs'][0]['design_fingerprint']=fingerprint;projects.save_bundle(bundle)
        case.url=f'/api/projects/{case.project_id}/runs/{case.run_id}/report-snapshot'
        return case
    return make


def test_verified_snapshot_stable_complete_and_read_only(snapshot_case):
    case=snapshot_case();project=case.app.state.project_service.store.path_for(case.project_id)
    before={p:p.read_bytes() for p in case.directory.rglob('*') if p.is_file()};before[project]=project.read_bytes()
    response=case.client.get(case.url);assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    snapshot=response.json();assert snapshot==case.client.get(case.url).json()
    digest=snapshot.pop('snapshot_sha256');assert digest==sha256(canonical_json_bytes(snapshot)).hexdigest()
    assert snapshot['schema']=='rawibumi.report_snapshot.v1'
    assert snapshot['summary']==case.summary
    assert 'result_rules' not in snapshot['checks']
    assert set(snapshot['checks'])=={'design-validation-report.json','validation-findings.json'}
    assert 'history' not in snapshot['design_view']
    assert 'design_workspace_state' not in snapshot['design_view']['bundle']
    assert snapshot['monthly']['period']['pr']==pytest.approx(case.summary['performance_ratio'],rel=1e-9)
    assert snapshot['provenance']['free_csv_schema']=='rawibumi.free_csv.v1'
    assert snapshot['annual_pxx']['P99'] is None
    assert snapshot['annual_pxx']['P99_reason']=='no_uncertainty_ledger'
    assert snapshot['annual_pxx']['P99_message']
    assert before=={p:p.read_bytes() for p in before}


def test_snapshot_refuses_tampering_earlier_design_and_forged_registration(snapshot_case):
    case=snapshot_case();projects=case.app.state.project_service
    bundle=projects.get_bundle(case.project_id);bundle['project']['site']['latitude_deg']+=.1;projects.save_bundle(bundle)
    r=case.client.get(case.url);assert r.status_code==422 and 'earlier_design' in r.text
    case=snapshot_case();projects=case.app.state.project_service;bundle=projects.get_bundle(case.project_id);bundle['simulation_runs'][0]['input_hash']='b'*64;projects.save_bundle(bundle)
    assert case.client.get(case.url).status_code==422
    case=snapshot_case();(case.directory/'timeseries.parquet').write_bytes(b'tampered')
    assert case.client.get(case.url).status_code==422


def test_metadata_changes_snapshot_hash_but_not_design_binding(snapshot_case):
    case=snapshot_case();before=case.client.get(case.url);assert before.status_code==200
    projects=case.app.state.project_service;bundle=projects.get_bundle(case.project_id)
    bundle['project']['site']['address']={'text':'Synthetic road','source':'user','lat':-6.2,'lon':106.8,'attribution':None,'updatedAt':'2026-11-16T00:00:00Z'}
    projects.save_bundle(bundle);after=case.client.get(case.url)
    assert after.status_code==200 and before.json()['snapshot_sha256']!=after.json()['snapshot_sha256']


def test_lid_and_stc_metadata_are_not_simulation_settings():
    from reporting.exports.report_snapshot import module_stc_notice,loss_disclosures
    def module(power):
        return {'revision_id':'synthetic','stc':{'pmp_w':1000},'electrical_models':[{'validation':{'stc':{'modeled':{'pmp_w':power}}}}]}
    assert module_stc_notice(module(1004)) is None
    assert module_stc_notice(module(1005)) is None
    notice=module_stc_notice(module(1006));assert notice['deviation_fraction']==pytest.approx(.006)
    settings={'lid_fraction':0,'ac_wiring_nominal_fraction':0,'unavailability_fraction':0}
    before=deepcopy(settings);rows=loss_disclosures(settings,[{'revision_id':'m','quality':{'lid_loss_fraction':.0275}}])
    assert len(rows)==3 and all(row['not_included'] for row in rows)
    assert rows[0]['suggestions'][0]['fraction']==.0275 and not rows[0]['suggestions'][0]['applied']
    assert loss_disclosures(settings,[{}])[0]['suggestions'][0]['reason']=='pan_lid_not_supplied'
    assert settings==before
    assert not loss_disclosures({'lid_fraction':.01},[])[0]['not_included']


def test_method_catalog_preserves_codes_languages_assumptions_and_applicability(snapshot_case):
    case=snapshot_case();r=case.client.get(case.url);assert r.status_code==200,r.text
    method=r.json()['method'];catalog={item['code']:item for item in method['limits']}
    assert all(any(code.startswith(f'AUDIT_{i:02}_') for code in catalog) for i in range(1,13))
    assert all(item['en'] and item['id'] and 'applies' in item for item in catalog.values())
    assert not catalog['AUDIT_03_MIXED_REFERENCE']['applies']
    assert not any(item['code']=='MPPT_WINDOW_MIXED_EDGE' for item in method['limits'])
    source=case.study.csv_export_source(case.project_id,case.run_id)
    assert method['recorded_assumptions']==source.run['assumptions']


def test_pxx_uses_existing_annual_view_and_retains_p99_reason_message(snapshot_case):
    import pandas as pd
    from tests.unit.test_rb_rpt1_free_csv import frame
    from tests.unit.test_rb_unc1_annual_pxx import ledger
    case=snapshot_case(data=frame(pd.date_range('2025-01-01',periods=8760,freq='h',tz='Asia/Jakarta')))
    projects=case.app.state.project_service;bundle=projects.get_bundle(case.project_id)
    bundle['uncertainty_assumptions']=ledger();projects.save_bundle(bundle)
    expected=case.study.annual_pxx(case.project_id,case.run_id)
    r=case.client.get(case.url);assert r.status_code==200,r.text
    actual=r.json()['annual_pxx']
    assert actual['result']['quantiles']==expected['result']['quantiles']
    assert actual['P99'] is None and actual['P99_reason']==expected['P99']['reason']
    assert actual['P99_message']==expected['P99']['message']


def test_minute_year_snapshot_size_report_only(snapshot_case):
    import pandas as pd
    from time import perf_counter
    from tests.unit.test_rb_rpt1_free_csv import frame
    case=snapshot_case(data=frame(pd.date_range('2025-01-01',periods=525600,freq='min',tz='Asia/Jakarta'),60))
    start=perf_counter();result=case.study.report_snapshot(case.project_id,case.run_id)
    raw=canonical_json_bytes(result)
    assert len(result['hourly_ac']['power_kw'])==525600
    print(f'RPT2b-1 native minute-year snapshot: {len(raw)} bytes; {perf_counter()-start:.3f} seconds')


def test_mixed_window_note_is_conditional_and_original_assumptions_survive(snapshot_case):
    from reporting.exports.report_snapshot import build_report_snapshot
    case=snapshot_case();source=case.study.csv_export_source(case.project_id,case.run_id)
    view=case.app.state.project_service.project_view(case.project_id)
    registered=deepcopy(view['bundle']['simulation_runs'][0]);registered['mixed_orientation']={'mppts':[{'mppt_instance_id':'synthetic'}]}
    result=build_report_snapshot(source,case.summary,view,registered_run=registered)
    by_code={item['code']:item for item in result['method']['limits']}
    assert by_code['MPPT_WINDOW_MIXED_EDGE']['applies']
    assert by_code['AUDIT_03_MIXED_REFERENCE']['applies']
    assert not by_code['AUDIT_06_MPPT_WINDOW']['applies']
    assert result['method']['recorded_assumptions']==source.run['assumptions']


def test_zero_disclosures_read_the_recorded_resolved_values_container():
    from reporting.exports.report_snapshot import loss_disclosures
    settings={'values':{'lid_fraction':0.,'ac_wiring_nominal_fraction':0.,'unavailability_fraction':0.},'simulated_dc_nameplate_w':9900}
    before=deepcopy(settings);rows=loss_disclosures(settings,[])
    assert [row['fraction'] for row in rows]==[0.,0.,0.]
    assert all(row['not_included'] for row in rows)
    settings['values']['lid_fraction']=.015
    assert not loss_disclosures(settings,[])[0]['not_included']
    settings['values']['lid_fraction']=0.
    assert settings==before
