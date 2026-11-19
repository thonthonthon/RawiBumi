"""RPT1: the downloadable CSV cell grammar and its existing writer boundaries."""
import csv
from io import StringIO
import pandas as pd
import pytest


@pytest.mark.parametrize('value', ['=1+1','+cmd','-2+3','@SUM','\t=1','\r=1','a project name','-2',float('inf'),float('-inf'),True])
def test_cell_refuses_untrusted_text_and_nonfinite_values(value):
    from reporting.exports.csv_cells import csv_cell
    with pytest.raises(ValueError): csv_cell(value)


def test_cell_preserves_numbers_missing_timestamps_and_months():
    from reporting.exports.csv_cells import csv_cell
    assert [csv_cell(v) for v in (None,float('nan'),pd.NA,-2.,9007199254740993)]==['','','','-2','9007199254740993']
    assert csv_cell(pd.Timestamp('2025-01-01T00:00:00+07:00'))=='2025-01-01T00:00:00+07:00'
    assert csv_cell('2025-02')=='2025-02'
    for value in ('2025-13','2025-01-99T00:00:00+07:00','2025-01-01T00:00:00'):
        with pytest.raises(ValueError):csv_cell(value)


@pytest.mark.parametrize('value', ['=1+1','+cmd','-2+3','@SUM','\t=1','\r=1','Hostile field name'])
def test_monthly_writer_refuses_text_cells(value):
    from reporting.exports.series import monthly_csv, MONTHLY_COLUMNS
    row={name:0. for name,_,_ in MONTHLY_COLUMNS};row.update(month=value,losses_kwh={})
    with pytest.raises(ValueError):monthly_csv({'monthly':[row],'loss_channels':[]})
