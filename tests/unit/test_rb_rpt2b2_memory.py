"""Trusted operator memory configuration; malformed settings never start a worker."""
import pytest
from reporting.exports import native_pdf as pdf
from tests.unit.test_phase7_native_pdf import configured_runtime, report_case, persisted


def test_memory_default_and_supported_operator_limits(monkeypatch):
    monkeypatch.delenv('RAWIBUMI_PDF_MEMORY_LIMIT_MIB',raising=False)
    assert pdf._memory_limit_bytes()==pdf.MAX_RSS_BYTES
    assert 768*1024**2<=pdf.MAX_RSS_BYTES<=2*1024**3
    for mib in [768,1024,2048]:
        monkeypatch.setenv('RAWIBUMI_PDF_MEMORY_LIMIT_MIB',str(mib))
        assert pdf._memory_limit_bytes()==mib*1024**2


@pytest.mark.parametrize('setting',['','0','767','2049','-1','1024.5','NaN',' 1024','1024 ','1e3','01024'])
def test_invalid_memory_configuration_is_closed_before_worker(monkeypatch,setting,tmp_path):
    monkeypatch.setenv('RAWIBUMI_PDF_MEMORY_LIMIT_MIB',setting)
    def forbidden(*args,**kwargs):raise AssertionError('worker must not start')
    monkeypatch.setattr(pdf.subprocess,'Popen',forbidden)
    with pytest.raises(pdf.NativePDFError,match='memory limit configuration'):
        pdf._run_worker(b'{}',tmp_path,tmp_path/'chromium',tmp_path/'node')


def test_configured_memory_limit_is_enforced(monkeypatch,configured_runtime,report_case):
    monkeypatch.setenv('RAWIBUMI_PDF_MEMORY_LIMIT_MIB','768')
    monkeypatch.setattr(pdf,'_group_rss',lambda *args:769*1024**2)
    monkeypatch.setattr(pdf,'_group_pss',lambda *args:769*1024**2)
    case=report_case()
    with pytest.raises(pdf.NativePDFError,match='memory limit exceeded'):
        case.study.native_pdf_document(case.project_id,case.run_id)
