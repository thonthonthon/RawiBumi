"""Native CSV numeric and timestamp refusals at reader and service boundaries."""
import pytest
from weather.csv import read_opensimpv_weather_csv_bytes
from tests.unit.test_rb_fix_s12b_weather_import import http,upload,NATIVE,tree


def malformed(kind):
    lines=NATIVE.decode().splitlines()
    first=next(i for i,line in enumerate(lines) if not line.startswith('#'))+1
    if kind=='repeated':
        return ('\n'.join(lines[:first])+ '\n'+(lines[first]+'\n')*500000).encode()
    token={'inf':'inf','nan':'nan','overflow':'1e309','long_digits':'7'*(40*1024*1024)}[kind]
    row=lines[first].split(',');row[1]=token;lines[first]=','.join(row)
    return ('\n'.join(lines)+'\n').encode()


def read(raw):
    return read_opensimpv_weather_csv_bytes(raw,weather_dataset_id='r1-csv',revision_id='r1-csv-r1',name='R1',site_id='r1-site',filename='r1.csv')


@pytest.mark.parametrize('kind',['long_digits','repeated'])
def test_service_already_refuses_fable_weather_files(http,kind):
    _,client,pid,root=http
    before=tree(root)
    response=upload(client,pid,malformed(kind))
    assert response.status_code==422
    detail=response.json()['detail']
    assert detail['code']=='weather_quality_failed'
    assert tree(root)==before



def test_valid_native_weather_values_and_intervals_are_unchanged(http):
    weather=read(NATIVE)
    assert weather.series['ghi_w_m2'].tolist()==[0,100,400,200]
    assert [t.isoformat() for t in weather.series.index]==[f'2026-01-01T0{h}:00:00+07:00' for h in range(4)]
    _,client,pid,_=http
    assert upload(client,pid,NATIVE).status_code==200


@pytest.mark.parametrize('kind',['inf','negative_inf','overflow'])
def test_infinite_weather_is_refused_by_reader_and_service(http,kind):
    raw=malformed('inf' if kind=='negative_inf' else kind)
    if kind=='negative_inf': raw=raw.replace(b',inf,',b',-inf,')
    with pytest.raises(ValueError,match='infinite numeric value'): read(raw)
    _,client,pid,root=http
    before=tree(root)
    response=upload(client,pid,raw)
    assert response.status_code==422
    assert response.json()['detail']['code']=='weather_parse_failed'
    assert 'infinite numeric value' in response.json()['detail']['message']
    assert tree(root)==before


@pytest.mark.parametrize('token',[b'nan',b''])
def test_missing_values_keep_the_quality_check_path(http,token):
    raw=NATIVE.replace(b',100,120,40,',b','+token+b',120,40,')
    assert read(raw).series['ghi_w_m2'].isna().sum()==1
    _,client,pid,_=http
    assert upload(client,pid,raw,dry=True).json()['qc']['status']=='failed'
    assert upload(client,pid,raw).json()['detail']['code']=='weather_quality_failed'
