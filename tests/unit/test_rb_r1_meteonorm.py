"""Only the supported declared Meteonorm time reference is accepted."""
import pytest
from weather.meteonorm import read_meteonorm_dat_bytes


def dat(reference=-30):
    header=f'Fictional R1 site\n6.2 [deg S], 106.8 [deg E], 20 [m], 7 [timezone h], {reference} [time ref. min]\nm dm dy h mi G_Gh G_Dh G_Bn Ta FF\n'
    return (header+'\n'.join(f'1 1 1 {h} 0 0 0 0 25 1' for h in [1,2,3])+'\n').encode()


def read(data):
    return read_meteonorm_dat_bytes(data,weather_dataset_id='r1-weather',revision_id='r1-weather-r1',name='R1',site_id='r1-site',filename='r1.dat')


@pytest.mark.parametrize('reference',[0,30])
def test_unsupported_time_reference_is_refused(reference):
    with pytest.raises(ValueError,match='Export with the standard -30-minute reference'):
        read(dat(reference))


def test_standard_time_reference_keeps_interval_start_and_values():
    weather=read(dat())
    assert weather.series.index[0].isoformat()=='2001-01-01T00:00:00+07:00'
    assert weather.series['ambient_temperature_c'].tolist()==[25,25,25]
    assert weather.dataset['source_metadata']['source_time_reference_minutes']==-30
