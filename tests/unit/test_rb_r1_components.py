"""Component input line bounds preserve accepted source text."""
import pytest
from components.pan import parse_pan_text
from components.ond import parse_ond_text
from tests.unit.test_rb_fix_s12a_component_library import project_api


@pytest.mark.parametrize('reader',[parse_pan_text,parse_ond_text])
def test_component_reader_refuses_5001_lines(reader):
    with pytest.raises(ValueError,match='no more than 5,000 lines'):
        reader('a=b\n'*5001)


@pytest.mark.parametrize('reader',[parse_pan_text,parse_ond_text])
def test_component_reader_preserves_5000_lines(reader):
    text='a=b\n'*5000
    result=reader(text)
    assert result.raw_text==text and len(result.lines)==5000


@pytest.mark.parametrize('filename',['JKM550M-72HL4-V_SGS_6079M3.PAN','Huawei_Sun2000_100KTL_M1.OND'])
def test_public_manufacturer_fixtures_still_import(project_api,filename):
    from pathlib import Path
    from tests.unit.test_rb_fix_s12a_component_library import upload
    _,client,_=project_api
    raw=(Path(__file__).parents[1]/'fixtures/panond/manufacturer'/filename).read_bytes()
    assert len(raw.splitlines())<=150
    response=upload(client,raw,filename)
    assert response.status_code==200,response.text
