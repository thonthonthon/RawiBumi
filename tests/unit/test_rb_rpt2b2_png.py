import base64
import struct
import zlib
from io import BytesIO
import pytest
from PIL import Image,PngImagePlugin
from reporting.exports.native_pdf import validate_plan_png


def encoded(raw):return 'data:image/png;base64,'+base64.b64encode(raw).decode()

def png(size=(3,4),**kwargs):
    output=BytesIO();Image.new('RGB',size,'red').save(output,format='PNG',**kwargs);return output.getvalue()

def test_reencodes_valid_png_and_strips_metadata():
    meta=PngImagePlugin.PngInfo();meta.add_text('private','SECRET')
    result=validate_plan_png(encoded(png(pnginfo=meta)))
    raw=base64.b64decode(result.split(',',1)[1]);assert b'SECRET' not in raw
    with Image.open(BytesIO(raw)) as image:assert image.size==(3,4) and image.convert('RGB').getpixel((0,0))==(255,0,0) and not image.info
    assert validate_plan_png(None) is None

@pytest.mark.parametrize('kind',['not_png','oversize','pixels','apng','apng_single','truncated','polyglot','base64','type'])
def test_refuses_invalid_plan_figure(kind):
    raw=png()
    if kind=='not_png':raw=b'not PNG'
    elif kind=='oversize':raw=b'x'*(4*1024*1024+1)
    elif kind=='pixels':raw=png((4097,1))
    elif kind=='apng':raw=png(save_all=True,append_images=[Image.new('RGB',(3,4),'blue')],duration=100,loop=0)
    elif kind=='apng_single':
        # Pillow writes a static PNG for save_all with one image: construct valid APNG controls explicitly.
        def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
        raw=raw[:33]+chunk(b'acTL',struct.pack('>II',1,0))+chunk(b'fcTL',struct.pack('>IIIIIHHBB',0,3,4,0,0,100,1000,0,0))+raw[33:]
        with Image.open(BytesIO(raw)) as single:assert single.n_frames==1
    elif kind=='truncated':raw=raw[:-8]
    elif kind=='polyglot':raw+=b'<script>alert(1)</script>'
    value=123 if kind=='type' else 'data:image/png;base64,???' if kind=='base64' else encoded(raw)
    with pytest.raises(ValueError,match='plan_figure_png'):validate_plan_png(value)

from tests.unit.test_phase7_csv_export import persisted
from tests.unit.test_rb_rpt1_free_csv import package
from tests.unit.test_rb_rpt2b1_snapshot import snapshot_case


def test_post_accepts_only_locale_and_validated_figure_and_keeps_get_alias(snapshot_case,monkeypatch):
    case=snapshot_case();monkeypatch.setenv('RAWIBUMI_DEPLOYMENT_EDITION','community_self_hosted');monkeypatch.setenv('RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED','1')
    calls=[]
    monkeypatch.setattr(case.study,'native_pdf_document',lambda *args,**kwargs:calls.append((args,kwargs)) or b'%PDF-synthetic')
    url=case.path+'/native-pdf'
    assert case.client.get(url).status_code==200 and calls[-1][1]=={'locale':'en'}
    assert case.client.post(url,json={'locale':'id','plan_figure_png':encoded(png())}).status_code==200
    assert calls[-1][1]['locale']=='id'
    for body in [{'locale':'fr'},{'snapshot':{}},{'html':'<html>'},{'plan_figure_png':'bad'}]:
        before=len(calls);r=case.client.post(url,json=body);assert r.status_code==422 and len(calls)==before
    monkeypatch.setenv('RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED','0')
    assert case.client.post(url,content=b'not JSON').status_code==404

@pytest.mark.parametrize('length',['bad','-1',str(6*1024*1024+1)])
def test_post_refuses_invalid_or_oversize_declared_body_without_rendering(snapshot_case,monkeypatch,length):
    case=snapshot_case();monkeypatch.setenv('RAWIBUMI_DEPLOYMENT_EDITION','community_self_hosted');monkeypatch.setenv('RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED','1')
    monkeypatch.setattr(case.study,'native_pdf_document',lambda *args,**kwargs:pytest.fail('invalid request reached renderer'))
    response=case.client.post(case.path+'/native-pdf',content=b'{"locale":"en"}',headers={'content-length':length,'content-type':'application/json'})
    assert response.status_code==422
    assert response.headers['cache-control']=='no-store' and response.headers['x-content-type-options']=='nosniff'
