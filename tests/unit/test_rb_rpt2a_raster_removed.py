"""Only the retired capability name remains; no renderer or service survives."""
from tests.unit._availability import missing_git
import importlib
from pathlib import Path
import subprocess
import pytest


def test_raster_renderer_service_worker_tests_and_documentation_are_removed():
    if reason := missing_git():
        pytest.skip(reason)
    with pytest.raises(ModuleNotFoundError):importlib.import_module('reporting.exports.raster_pdf')
    from apps.api.study import BrowserStudyService
    assert not hasattr(BrowserStudyService,'raster_pdf_document')
    root=Path(__file__).resolve().parents[2]
    assert not (root/'reporting/exports/raster_pdf_worker.cjs').exists()
    assert not (root/'tests/unit/test_phase7_raster_pdf.py').exists()
    allowed={'apps/web/src/platform/entitlements.ts','apps/web/tests/unit/rpt1-capabilities.test.ts',str(Path(__file__).relative_to(root))}
    references=[]
    for name in subprocess.check_output(['git','ls-files'],cwd=root,text=True).splitlines():
        if name in allowed or name.startswith(('.ai/','var/')):continue
        path=root/name
        if not path.is_file():continue
        try:content=path.read_text()
        except (UnicodeError,OSError):continue
        if any(token in content for token in ('raster_pdf','raster PDF','raster-pdf')):references.append(name)
    assert references==[]
