from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import subprocess
import pytest
from reporting.exports import native_pdf as pdf
from engine.simulation.artifacts import canonical_json_bytes
from tests.unit.test_phase7_csv_export import persisted
from tests.unit.test_phase7_report_contract import report_case,context
from tests.unit.test_phase7_native_pdf import configured_runtime,node_binary,worker_html,seal


def test_worker_hashes_exact_python_bytes_and_rejects_changed_bytes(report_case):
    source=context(report_case());payload=pdf.prepare_snapshot(source)
    raw=payload['snapshot_json'].encode();assert sha256(raw).hexdigest()==source['snapshot_sha256']
    assert b'1000.0' in raw  # Re-serializing parsed JS numbers would change these bytes.
    assert source['snapshot_sha256'] in worker_html(payload)
    changed={**payload,'snapshot_json':payload['snapshot_json']+' '}
    with pytest.raises(AssertionError,match='PDF_SNAPSHOT_DIGEST'):worker_html(changed)


def test_bounds_retain_all_families_and_accept_full_address(report_case,monkeypatch):
    source=context(report_case());source['site']['address']={'text':'a'*2000,'source':'user','lat':-6.2,'lon':106.8,'attribution':None,'updatedAt':'2026-01-01T00:00:00Z'}
    assert 'a'*2000 in pdf.prepare_snapshot(seal(source))['snapshot_json']
    for value,reason in [({'k'+str(i):None for i in range(129)},'object'),(['x']*(pdf.MAX_LIST_ITEMS+1),'list'),('x'*2049,'string')]:
        with pytest.raises(pdf.NativePDFError,match=reason):pdf._bound_tree(value)
    nested=None
    for _ in range(34):nested=[nested]
    with pytest.raises(pdf.NativePDFError,match='nesting'):pdf._bound_tree(nested)
    monkeypatch.setattr(pdf,'MAX_NODES',4)
    with pytest.raises(pdf.NativePDFError,match='node'):pdf._bound_tree([None]*5)
    monkeypatch.setattr(pdf,'MAX_NODES',4_000_000);monkeypatch.setattr(pdf,'MAX_TREE_BYTES',16)
    with pytest.raises(pdf.NativePDFError,match='size'):pdf._bound_tree(['12345'])


@pytest.mark.parametrize('mode',['missing','syntax','export','outside'])
def test_bundle_failures_are_closed_before_chromium(report_case,configured_runtime,tmp_path,mode):
    bundle=configured_runtime/'dist/report-render/report-render.cjs'
    if mode=='missing':bundle.unlink()
    elif mode=='syntax':bundle.write_text('this is not javascript')
    elif mode=='export':bundle.write_text('module.exports={};')
    else:
        external=tmp_path/'outside.cjs';external.write_text("throw new Error('EXTERNAL EXECUTED');")
        bundle.unlink();bundle.symlink_to(external)
    with pytest.raises(pdf.NativePDFError,match='PDF_(REPORT_RENDER_FAILED|RUNTIME_UNAVAILABLE)'):
        pdf.render_native_pdf(context(report_case()))


@pytest.mark.parametrize('mode',['hang','memory'])
def test_node_render_stage_is_inside_process_limits(report_case,configured_runtime,monkeypatch,mode):
    bundle=configured_runtime/'dist/report-render/report-render.cjs'
    bundle.write_text("module.exports={renderReport:()=>{"+("const hold=Buffer.alloc(80*1024*1024,1);" if mode=='memory' else '')+"while(true){} }};")
    monkeypatch.setattr(pdf,'WORKER_TIMEOUT_SECONDS',1 if mode=='hang' else 5)
    if mode=='memory':monkeypatch.setattr(pdf,'MAX_RSS_BYTES',64*1024*1024)
    with pytest.raises(pdf.NativePDFError,match='timeout' if mode=='hang' else 'memory limit'):
        pdf.render_native_pdf(context(report_case()))


def test_worker_refuses_oversize_wire_input_before_parsing():
    result=subprocess.run([node_binary(),str(pdf.WORKER)],input=b'x'*(pdf.MAX_PROJECTION_BYTES+1),capture_output=True,timeout=10)
    assert result.returncode!=0 and result.stdout==b'' and result.stderr==b'PDF_INPUT_LIMIT\n'
