"""Full numerical report parity from verified synthetic packages, never a re-simulation."""
from copy import deepcopy
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import re
import time
from zipfile import ZipFile
import pandas as pd
import pikepdf
from PIL import Image
import pytest
from engine.simulation.artifacts import canonical_json_bytes
from reporting.exports import native_pdf as pdf
from tests.unit.test_phase7_csv_export import persisted
from tests.unit.test_rb_rpt1_free_csv import package, frame
from tests.unit.test_rb_rpt2b1_snapshot import snapshot_case
from tests.unit.test_rb_unc1_annual_pxx import ledger
from tests.unit.test_phase7_native_pdf import worker_html, Document


def populated(summary):
    remaining=summary['total_energy_wh']/0.8
    fraction=1-0.8**(1/9)
    summary['loss_summary']=[]
    for label in ['iam','soiling','temperature','module_quality','mismatch','dc_wiring','inverter_conversion','inverter_clipping','ac_wiring']:
        lost=remaining*fraction
        summary['loss_summary'].append({'loss_type':label,'stage':'system','reference_energy_wh':remaining,'lost_energy_wh':lost,'loss_fraction':fraction,'method':'synthetic_fixture','notes':''})
        remaining-=lost
    summary['resolved_loss_settings']['values']={'lid_fraction':0.,'ac_wiring_nominal_fraction':0.,'unavailability_fraction':0.}


@pytest.mark.parametrize('seconds,periods,freq',[(3600,8760,'h'),(3600,8784,'h'),(60,525600,'min')])
@pytest.mark.parametrize('locale',['en','id'])
def test_full_pdf_screen_csv_and_required_sections(snapshot_case,seconds,periods,freq,locale,tmp_path,monkeypatch):
    import tests.unit.test_rb_rpt1_free_csv as r1
    from apps.api.history import design_fingerprint
    monkeypatch.setattr(r1,'KWP',9.9)
    case=snapshot_case(data=frame(pd.date_range('2024-01-01' if periods==8784 else '2025-01-01',periods=periods,freq=freq,tz='Asia/Jakarta'),seconds),summary_change=populated)
    projects=case.app.state.project_service
    view=projects.add_surface_rectangle(case.project_id,name='Synthetic report roof',origin_x_m=0,origin_y_m=0,width_m=1+18*1.154-.01,height_m=3.45,base_elevation_m=6.1)
    sid=view['bundle']['scene']['surfaces'][0]['surface_id']
    projects.create_pv_field(case.project_id,name='Synthetic report array',support_surface_id=sid,module_definition_revision_id='mod-rawibumi-uat-550-r1',tilt_deg=10,row_pitch_m=3.2,perimeter_setback_m=.5)
    view=projects.add_inverter(case.project_id,name='Report inverter',inverter_definition_revision_id='inv-rawibumi-uat-150k-r1')
    projects.create_strings(case.project_id,string_length=18,allow_shorter_remainder=False)
    projects.assign_strings(case.project_id,inverter_instance_id=view['bundle']['electrical_design']['inverter_instances'][0]['inverter_instance_id'])
    bundle=projects.get_bundle(case.project_id)
    bundle['simulation_runs'][0]['design_fingerprint']=design_fingerprint(bundle)
    bundle['uncertainty_assumptions']=ledger();projects.save_bundle(bundle)
    source=case.study.report_snapshot(case.project_id,case.run_id)
    project=projects.store.path_for(case.project_id)
    before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in [project,*[p for p in case.directory.rglob('*') if p.is_file()]]}
    output=BytesIO();Image.new('RGB',(900,540),'white').save(output,format='PNG')
    import base64
    figure='data:image/png;base64,'+base64.b64encode(output.getvalue()).decode()
    payload=pdf.prepare_snapshot(source,locale=locale,plan_figure_png=figure)
    html=worker_html(payload)
    assert [value for key,value in Document(html).attrs if key=='data-chapter']==['kpis','plan','topology','sld','shading','monthly','losses','heatmap','checks','method','assumptions','scope']
    assert source['snapshot_sha256'] in html and 'rawibumi.free_csv.v1' in html
    for marker in ['data-report-pxx','data-report-method-limits','data-report-loss-disclosures','data-report-provenance','data-report-ledger','data-plan-figure']:
        assert marker in html
    assert ('Illustrative layout, drawn by the browser; not verified' if locale=='en' else 'Denah ilustratif, digambar oleh browser; tidak terverifikasi') in html
    raw=case.study.free_csv_export(case.project_id,case.run_id)
    with ZipFile(BytesIO(raw)) as archive:manifest=json.loads(archive.read('export-manifest.json'))
    assert source['monthly']['period']['e_ac_pcc_kwh']==pytest.approx(manifest['aggregates']['period']['e_ac_pcc_kwh'],rel=1e-9)
    assert source['monthly']['period']['pr']==pytest.approx(manifest['aggregates']['period']['pr'],rel=1e-9)
    for recorded,exported in zip(source['monthly']['monthly'],manifest['aggregates']['monthly']):
        assert recorded['month']==exported['month']
        assert recorded['energy_kwh']==pytest.approx(exported['e_ac_pcc_kwh'],rel=1e-9)
    start=time.monotonic();protected=pdf.render_native_pdf(source,locale=locale,plan_figure_png=figure)
    path=tmp_path/'plain.pdf'
    with pikepdf.open(BytesIO(protected)) as document:
        pages=len(document.pages);assert document.is_encrypted and document.encryption.R==6
        assert 1<=pages<=8 and len(protected)<=8*1024*1024
        document.save(path,encryption=False)
    import subprocess
    text=subprocess.check_output(['pdftotext','-layout',str(path),'-'],text=True)
    assert ('Reference Production' if locale=='en' else 'Produksi Referensi') in text
    assert ('RawiBumi · Free / Community report' if locale=='en' else 'RawiBumi · Laporan Free / Komunitas') in text
    compact=re.sub(r'\s+','',text)
    assert source['snapshot_sha256'] in compact
    class Visible(HTMLParser):
        def __init__(self):super().__init__();self.parts=[]
        def handle_data(self,value):self.parts.append(value)
    parsed=Visible();parsed.feed(re.sub(r'<style[^>]*>[\s\S]*?</style>','',html))
    for number in re.findall(r'(?<![A-Za-z0-9])-?\d[\d,]*(?:\.\d+)?',' '.join(parsed.parts)):
        assert number in compact or number in text,number
    assert 'P50' in text and 'P95' in text and 'P99_NOT_QUALIFIED' in text
    assert before=={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in before}
    print(f'RPT2b2 {periods} intervals/{seconds}s {locale}: {pages} pages; {len(protected)} bytes; {time.monotonic()-start:.3f}s; snapshot {len(canonical_json_bytes(source))} bytes')


def test_no_poa_reference_report_pr_matches_csv_null(snapshot_case):
    data=frame()
    data[['ghi_w_m2','dni_w_m2','dhi_w_m2','poa_global_w_m2','inverter_input_power_w']]=0.
    case=snapshot_case(data=data)
    source=case.study.report_snapshot(case.project_id,case.run_id)
    with ZipFile(BytesIO(case.study.free_csv_export(case.project_id,case.run_id))) as archive:
        manifest=json.loads(archive.read('export-manifest.json'))
    assert source['summary']['performance_ratio']==0
    assert source['monthly']['period']['pr'] is manifest['aggregates']['period']['pr'] is None
    for locale in ['en','id']:
        html=worker_html(pdf.prepare_snapshot(source,locale=locale))
        assert 'data-report-pr-reason="no_poa_reference"' in html
        assert re.search(r'data-report-pr-reason="no_poa_reference"[^>]*>.*?<strong>—</strong>',html,re.S)
