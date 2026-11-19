"""Real native text, reserved margin geometry and baseline numeric equivalence."""
from copy import deepcopy
from io import BytesIO
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pikepdf
import pytest
from engine.simulation.artifacts import canonical_json_bytes
from reporting.exports import native_pdf as pdf
from tests.unit.test_phase7_csv_export import persisted
from tests.unit.test_phase7_native_pdf import worker_html
from tests.unit.test_phase7_report_contract import report_case, context

ROOT=Path(__file__).resolve().parents[2]


def inspect(raw,path):
    with pikepdf.open(BytesIO(raw)) as document:document.save(path,encryption=False)
    text=subprocess.check_output(['pdftotext','-layout',str(path),'-'],text=True)
    bbox=subprocess.check_output(['pdftotext','-bbox',str(path),'-'])
    return text,ET.fromstring(bbox)


@pytest.mark.parametrize('locale,watermark,production',[
    ('en','RawiBumi · Free / Community report','Reference Production'),
    ('id','RawiBumi · Laporan Free / Komunitas','Produksi Referensi')])
def test_every_page_native_watermark_avoids_numbers_and_preserves_baseline_figures(report_case,tmp_path,monkeypatch,locale,watermark,production):
    from html.parser import HTMLParser
    source=context(report_case(),locale=locale);projection=pdf.prepare_snapshot(source,locale=locale)
    assert projection['watermark']=='free_community'
    html=worker_html(projection)
    assert watermark in html and production in html and 'hourly P50' not in html
    assert '@top-center' in html and 'margin-top:16mm' in html
    monkeypatch.setenv('RAWIBUMI_PDF_RUNTIME_ROOT',str(ROOT/'apps/web'))
    monkeypatch.setenv('RAWIBUMI_PDF_CHROMIUM_EXECUTABLE',str(Path.home()/'.cache/ms-playwright/chromium-1248/chrome-linux64/chrome'))
    monkeypatch.setenv('RAWIBUMI_PDF_NODE',shutil.which('node'))
    protected=pdf.render_native_pdf(source,locale=locale)
    text,tree=inspect(protected,tmp_path/'decrypted.pdf')
    pages=tree.findall('.//{*}page');assert 1<len(pages)<=8
    for page in pages:
        words=page.findall('{*}word')
        watermark_words=[w for w in words if float(w.attrib['yMax'])<16*72/25.4 and w.text in watermark.split()]
        assert watermark in ' '.join(w.text or '' for w in watermark_words)
        for word in watermark_words:
            assert 0<=float(word.attrib['yMin'])<float(word.attrib['yMax'])<16*72/25.4
            # All other text includes numbers, table cells and warnings.
            for other in (w for w in words if w not in watermark_words):
                overlaps=(float(word.attrib['xMin'])<float(other.attrib['xMax']) and float(other.attrib['xMin'])<float(word.attrib['xMax'])
                    and float(word.attrib['yMin'])<float(other.attrib['yMax']) and float(other.attrib['yMin'])<float(word.attrib['yMax']))
                assert not overlaps
    class Visible(HTMLParser):
        def __init__(self):super().__init__();self.parts=[]
        def handle_data(self,data):self.parts.append(data)
    parser=Visible();parser.feed(re.sub(r'<style[^>]*>[\s\S]*?</style>','',html))
    visible=' '.join(parser.parts)
    for number in re.findall(r'(?<![A-Za-z0-9])-?\d[\d,]*(?:\.\d+)?',visible):
        assert number in re.sub(r'\s+','',text) or number in text,number
    assert production in text and 'hourly P50' not in text
    assert source['snapshot_sha256'] in re.sub(r'\s+','',text)
