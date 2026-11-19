"""An unsupported file explains the supported export route without adding a reader."""
from tests.unit.test_rb_fix_s12b_weather_import import http,upload


def test_unknown_weather_file_explains_meteonorm_and_pvsyst_exports(http):
    _,client,pid,_=http
    response=upload(client,pid,b'unrecognised weather file','unknown.dat')
    assert response.status_code==422
    detail=response.json()['detail']
    assert detail['code']=='weather_format_unsupported'
    assert 'Meteonorm or PVsyst' in detail['message'] and 'TMY3' in detail['message'] and '"PVsyst Standard" CSV' in detail['message']
