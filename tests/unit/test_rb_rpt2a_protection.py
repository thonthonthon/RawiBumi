"""RPT2a: protection at the renderer boundary and sanitized HTTP failure."""
from hashlib import sha256
from io import BytesIO
import json
import secrets

import pikepdf
import pytest

from reporting.exports import native_pdf as pdf
from tests.unit.test_phase7_csv_export import persisted
from tests.unit.test_phase7_native_pdf import configured_runtime
from tests.unit.test_phase7_report_contract import report_case, context


def plain_pdf():
    with pikepdf.new() as document:
        page=document.add_blank_page()
        page.Contents=document.make_stream(b'q 1 0 0 1 0 0 cm Q\n')
        output=BytesIO();document.save(output)
        return output.getvalue()


def test_passwordless_r6_permissions_random_owner_and_identical_content(report_case,configured_runtime,monkeypatch,capsys):
    payloads=[];plain=plain_pdf()
    def worker(payload,*args):
        payloads.append(payload)
        return plain
    monkeypatch.setattr(pdf,'_run_worker',worker)
    generated=[];generate=secrets.token_urlsafe
    def owner(*args,**kwargs):
        password=generate(*args,**kwargs)
        assert all(password.encode() not in payload for payload in payloads)
        generated.append(sha256(password.encode()).digest())
        return password
    monkeypatch.setattr(secrets,'token_urlsafe',owner)
    envelope=context(report_case())
    first,second=pdf.render_native_pdf(envelope),pdf.render_native_pdf(envelope)
    with pikepdf.open(BytesIO(first)) as a,pikepdf.open(BytesIO(second)) as b:
        assert a.is_encrypted and a.encryption.R==6 and a.encryption.bits==256
        assert a.allow.print_highres and a.allow.print_lowres and a.allow.accessibility
        assert not any((a.allow.modify_other,a.allow.modify_form,a.allow.modify_annotation,a.allow.modify_assembly,a.allow.extract))
        assert a.pages[0].Contents.read_bytes()==b.pages[0].Contents.read_bytes()
    assert len(generated)==2 and generated[0]!=generated[1]
    assert first!=second and payloads[0]==payloads[1]
    assert not {'password','owner'}.intersection(json.loads(payloads[0]))
    assert capsys.readouterr()==('','')


def test_protection_failure_is_sanitized_and_never_serves_plain_pdf(report_case,configured_runtime,monkeypatch,caplog):
    monkeypatch.setenv('RAWIBUMI_DEPLOYMENT_EDITION','community_self_hosted')
    monkeypatch.setenv('RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED','1')
    case=report_case()
    monkeypatch.setattr(pdf,'_run_worker',lambda *args:plain_pdf())
    def broken(*args,**kwargs):raise RuntimeError('PRIVATE protection detail')
    monkeypatch.setattr(pikepdf,'open',broken)
    response=case.client.get(case.path+'/native-pdf')
    assert response.status_code==503
    assert response.json()=={'detail':'Native PDF service is unavailable. Please retry later.'}
    assert response.headers['cache-control']=='no-store'
    assert 'PRIVATE' not in response.text and not response.content.startswith(b'%PDF')
    assert 'Native PDF protection failed' in caplog.text and 'PRIVATE protection detail' in caplog.text
