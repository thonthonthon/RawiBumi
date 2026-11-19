"""The fixed Free CSV: stored intervals, converter DC and incident-reference PR."""
from copy import deepcopy
import csv
from hashlib import sha256
from io import StringIO
from math import isclose, isfinite

import numpy as np
import pandas as pd

from engine.simulation.artifacts import canonical_json_bytes
from .csv_cells import csv_cell
from .csv_export import ExportSource, _zip, source_provenance
from .series import monthly

# Headers and definitions are constants; no project/field names enter CSV cells.
COLUMNS = (
    ('timestamp','ISO 8601','timestamp','Stored interval start with its offset'),
    ('ghi_wm2','W/m²','ghi_w_m2','Interval-mean global horizontal irradiance'),
    ('dni_wm2','W/m²','dni_w_m2','Interval-mean direct normal irradiance'),
    ('dhi_wm2','W/m²','dhi_w_m2','Interval-mean diffuse horizontal irradiance'),
    ('poa_wm2','W/m²',None,'Incident unshaded, pre-IAM POA, on the engine PR basis'),
    ('t_ambient_c','°C','ambient_temperature_c','Ambient temperature'),
    ('t_cell_c','°C','cell_temperature_c','Modelled cell temperature'),
    ('e_dc_inverter_kwh','kWh','inverter_input_power_w','DC energy taken by the inverter converter'),
    ('e_ac_pcc_kwh','kWh','interval_energy_wh','Modelled PV-attributable PCC AC interval energy'),
    ('pr','1',None,'e_ac_pcc_kwh / (P_STC_kwp × poa_wm2 × interval_seconds / 3.6e6)'),
)


def _dhi_basis(transformations):
    evidence = []
    source = modeled = analytical = 0
    for item in transformations:
        params = item.get('parameters', {})
        if not isinstance(params, dict):continue
        if any(k in params for k in ('source_preserved_dhi_intervals','modeled_dhi_intervals','analytical_dhi_intervals')):
            source += int(params.get('source_preserved_dhi_intervals',0))
            modeled += int(params.get('modeled_dhi_intervals',0))
            analytical += int(params.get('analytical_dhi_intervals',0))
            evidence.append(item)
    states = []
    if source:states.append('source')
    if modeled:states.append('engine decomposition')
    if analytical:states.append('engine completion')
    return {'state':' and '.join(states) if states else 'not recorded','recorded_transformations':evidence}


def _pxx(view):
    if view is None:
        return {'status':'no_uncertainty_ledger','P99':None,'P99_reason':'P99_NOT_QUALIFIED'}
    result = deepcopy(view)
    for obj in (result, result.get('result')):
        if isinstance(obj,dict):
            reason = (obj.get('P99') or {}).get('reason','P99_NOT_QUALIFIED')
            obj.update(P99=None,P99_reason=reason)
    return result


def free_csv_zip(source: ExportSource, summary: dict, *, annual_pxx=None) -> bytes:
    frame = source.frame
    reproduction = source.run['reproducibility_manifest']
    dt = frame.interval_seconds.to_numpy(dtype=float)
    if (not np.isfinite(dt).all() or (dt<=0).any() or not (dt==dt[0]).all()
            or not (frame.timestamp.diff().dropna()==pd.Timedelta(seconds=float(dt[0]))).all()
            or reproduction['simulation_timestep_seconds']!=dt[0]
            or reproduction['working_weather_resolution_seconds']!=dt[0]):
        raise ValueError('Free CSV requires the verified run’s uniform native cadence and interval_seconds')
    if 'interval_energy_wh' not in frame:
        raise ValueError('Free CSV requires stored interval_energy_wh; it is never reconstructed from power')
    poa_key = 'poa_global_unshaded_w_m2' if 'poa_global_unshaded_w_m2' in frame else 'poa_global_w_m2'
    if poa_key not in frame:
        raise ValueError('Free CSV cannot verify performance_ratio without the stored POA reference')
    poa = frame[poa_key].to_numpy(dtype=float)
    ac = frame.interval_energy_wh.to_numpy(dtype=float)/1000.
    if not np.isfinite(poa).all() or (poa<0).any() or not np.isfinite(ac).all():
        raise ValueError('Free CSV needs complete finite stored POA and interval_energy_wh')
    # Reuse the canonical nameplate derivation and reconciled local-month table,
    # retaining precision for the stricter Free CSV PR contract.
    table = monthly(source,summary,full_precision=True)
    kwp = table['dc_kwp']
    if kwp is None or not isfinite(kwp) or kwp<=0:
        raise ValueError('Free CSV DC nameplate basis is unavailable in the run summary')
    h = poa*dt/3.6e6
    period_energy,period_h = float(ac.sum()),float(h.sum())
    period_pr = period_energy/(kwp*period_h) if period_h else None
    expected = summary.get('performance_ratio')
    if (expected is None or not isfinite(float(expected))
            or not isclose(period_pr if period_pr is not None else 0.,float(expected),rel_tol=1e-9,abs_tol=0.)):
        raise ValueError('Free CSV period PR does not reconcile with summary performance_ratio')
    if not isclose(period_energy*1000,float(summary['total_energy_wh']),rel_tol=1e-9,abs_tol=0.):
        raise ValueError('Free CSV interval_energy_wh does not reconcile with the run summary')
    output = pd.DataFrame(index=frame.index)
    null_rules = {}
    columns = []
    for name,unit,column,definition in COLUMNS:
        if name=='poa_wm2':column=poa_key
        if name=='pr':
            values = np.divide(ac,kwp*h,out=np.full(len(ac),np.nan),where=poa!=0)
            reasons = {'no_poa_reference':int((poa==0).sum())}
        elif column in frame:
            values = frame[column]
            if name=='e_dc_inverter_kwh':values=values*dt/3.6e6
            elif name=='e_ac_pcc_kwh':values=values/1000.
            reasons = {'missing_in_run_dataset':int(pd.isna(values).sum())}
        else:
            values = np.full(len(frame),np.nan)
            reasons = {'not_in_run_dataset':len(frame)}
        output[name] = values
        null_rules[name] = {'null_count':int(pd.isna(values).sum()),'reasons':{k:v for k,v in reasons.items() if v}}
        columns.append({'id':name,'unit':unit,'source_column':column,'definition':definition})
    text = StringIO(newline='');writer=csv.writer(text,lineterminator='\n')
    writer.writerow([c[0] for c in COLUMNS])
    for row in output.itertuples(index=False,name=None):writer.writerow([csv_cell(v) for v in row])
    raw = text.getvalue().encode('utf-8')
    months = frame.timestamp.dt.strftime('%Y-%m')
    aggregates=[]
    for row in table['monthly']:
        selected = (months==row['month']).to_numpy()
        energy,irradiation=float(ac[selected].sum()),float(h[selected].sum())
        if not isclose(energy,row['energy_kwh'],rel_tol=1e-9,abs_tol=0.):
            raise ValueError('Free CSV monthly interval energy does not reconcile')
        aggregates.append({'month':row['month'],'e_ac_pcc_kwh':energy,'h_poa_kwh_m2':irradiation,
            'pr':energy/(kwp*irradiation) if irradiation else None,
            'pr_reason':None if irradiation else 'no_poa_reference'})
    start,end=frame.timestamp.iloc[0],frame.timestamp.iloc[-1]+pd.Timedelta(seconds=float(dt[-1]))
    complete = (summary.get('annual_energy_wh') is not None and start==pd.Timestamp(year=start.year,month=1,day=1,tz=start.tz)
                and end==pd.Timestamp(year=start.year+1,month=1,day=1,tz=start.tz))
    provenance=source_provenance(source)
    provenance['source_interval']={**provenance['source_interval'],'interval_seconds':float(dt[0])}
    manifest={**provenance,'schema':'rawibumi.free_csv.v1','capability':'export.csv.basic','columns':columns,
        'project_id':source.project_id,'run_id':source.run['simulation_run_id'],'row_count':len(frame),
        'resolution':'native','timestamp_convention':'interval_start','timezone':reproduction['timezone'],
        'column_order':[c[0] for c in COLUMNS],'csv_sha256':sha256(raw).hexdigest(),'csv_byte_size':len(raw),
        'bases':{'poa_key':poa_key,'poa_basis':'incident, unshaded and pre-IAM','G_ref_kw_m2':1.,
            'pr_formula':'e_ac_pcc_kwh / (P_STC_kwp * poa_wm2 * interval_seconds / 3.6e6)',
            'P_STC_kwp':kwp,'P_STC_basis':table['dc_kwp_basis'],
            'ac_boundary':'modelled PV-attributable AC energy at the declared PCC after modelled AC losses; not measured grid export',
            'dc_boundary':'DC energy taken by the inverter converter'},
        'null_rules':null_rules,'aggregates':{'monthly':aggregates,'period':{
            'scope':'annual' if complete else 'period','start_time':start.isoformat(),'end_time':end.isoformat(),
            'e_ac_pcc_kwh':period_energy,'h_poa_kwh_m2':period_h,'pr':period_pr,'pr_reason':None if period_h else 'no_poa_reference'}},
        'annual_pxx':_pxx(annual_pxx),'dhi_basis':_dhi_basis(reproduction['weather_transformations']),
        'limitations':['no subhourly samples are invented','t_cell_c is modelled','e_ac_pcc_kwh is not metered']}
    return _zip([('rawibumi_free.csv',raw),('export-manifest.json',canonical_json_bytes(manifest)+b'\n')])
