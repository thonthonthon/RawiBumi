"""Read-only, verified report data. No simulation or mutation of run loss settings."""
from copy import deepcopy
from hashlib import sha256
from math import isclose,isfinite
from components.design_integration import module_nameplate_w
import numpy as np
from engine.simulation.artifacts import canonical_json_bytes
from reporting.exports.csv_export import source_provenance
from reporting.exports.series import monthly,run_series

SCHEMA='rawibumi.report_snapshot.v1'
# The scope is the audit's §5.2; these are limitations, never accuracy claims.
LIMITS=(
 ('AUDIT_01_FIELD_VALIDATION','No measured-plant field validation has been performed.','Belum ada validasi lapangan terhadap pembangkit terukur.'),
 ('AUDIT_02_PVSYST_SCOPE','PVsyst agreement covers two projects in one climate, crystalline modules, hourly data and specific inverters; it does not establish general accuracy.','Kesesuaian PVsyst mencakup dua proyek dalam satu iklim, modul kristalin, data per jam, dan inverter tertentu; bukan bukti akurasi umum.'),
 ('AUDIT_03_MIXED_REFERENCE','Mixed-orientation results have no external reference validation.','Hasil orientasi campuran belum divalidasi terhadap referensi eksternal.'),
 ('AUDIT_04_SHADED_MISMATCH','The standard path does not model electrical mismatch under uneven shading.','Jalur standar tidak memodelkan mismatch listrik akibat bayangan tidak merata.'),
 ('AUDIT_05_INVERTER_THERMAL','Inverter temperature derating is not modelled.','Derating suhu inverter tidak dimodelkan.'),
 ('AUDIT_06_MPPT_WINDOW','Uniform MPPTs deliver zero outside their voltage window; this is not a physical prediction of edge operation.','MPPT seragam menghasilkan nol di luar jendela tegangan; ini bukan prediksi fisik operasi pada batas jendela.'),
 ('AUDIT_07_FAR_HORIZON','Far-horizon shading is not modelled; there is no horizon-profile input.','Bayangan horizon jauh tidak dimodelkan; tidak ada masukan profil horizon.'),
 ('AUDIT_08_SUBHOURLY','Subhourly simulation and transient thermal behaviour have not been benchmarked.','Simulasi subjam dan perilaku termal transien belum melalui benchmark.'),
 ('AUDIT_09_REACTIVE_KVA','Reactive power, power-factor and kVA limits are not modelled.','Daya reaktif, faktor daya, dan batas kVA tidak dimodelkan.'),
 ('AUDIT_10_DEFAULT_LOSSES','Default losses do not establish the losses at a real site.','Rugi bawaan tidak membuktikan rugi di lokasi nyata.'),
 ('AUDIT_11_WEATHER_TIMING','Weather-format timing was audited end to end only for the PVsyst CSV route; unit tests on other formats are not an end-to-end timing audit.','Waktu format cuaca diaudit menyeluruh hanya untuk jalur CSV PVsyst; uji unit format lain bukan audit waktu menyeluruh.'),
 ('AUDIT_12_DAYLIGHT_SAVING','Daylight-saving time zones have not been validated by this audit.','Zona waktu dengan daylight saving belum divalidasi oleh audit ini.'),
)


def module_stc_notice(module):
    nameplate=module_nameplate_w(module) if (module.get('stc') or {}).get('pmp_w') is not None else None
    if not isinstance(nameplate,(int,float)) or not isfinite(nameplate) or nameplate<=0:return None
    model=next((m for m in module.get('electrical_models',[]) if m.get('model_type')=='pvsyst_singlediode'),None)
    if model is None:model=next(iter(module.get('electrical_models',[])),None)
    if model is None:return None
    modeled=((model.get('validation') or {}).get('stc') or {}).get('modeled',{}).get('pmp_w')
    basis='pinned_module.electrical_models.validation.stc.modeled.pmp_w'
    if modeled is None and model.get('model_type')=='pvsyst_singlediode':
        from components.pan.pvsyst_sdm import validate_at_stc
        modeled=validate_at_stc(module,model['parameter_set']).get('modeled',{}).get('pmp_w')
        basis='deterministic pinned-module SDM: components.pan.pvsyst_sdm.validate_at_stc'
    if modeled is None or not isfinite(float(modeled)):return None
    deviation=(float(modeled)-nameplate)/nameplate
    if abs(deviation)<=.005:return None
    return {'module_revision_id':module.get('revision_id'),'nameplate_w':nameplate,'model_stc_w':modeled,
            'deviation_fraction':deviation,'basis':basis,'acceptance_tolerance_fraction':.02}


def loss_disclosures(settings,modules):
    values=settings.get("values",settings)
    rows=[]
    for key,label in [('lid_fraction','LID'),('ac_wiring_nominal_fraction','AC wiring'),('unavailability_fraction','Unavailability')]:
        value=values.get(key)
        row={'code':key,'label':label,'fraction':value,'not_included':value==0}
        if key=='lid_fraction':
            row['suggestions']=[{'module_revision_id':m.get('revision_id'),'fraction':(m.get('quality') or {}).get('lid_loss_fraction'),
                'applied':any(c.get('lid_source')=='module_file' and c.get('module_revision_id')==m.get('revision_id') for c in settings.get('circuits',{}).values()),'reason':None if (m.get('quality') or {}).get('lid_loss_fraction') is not None else 'pan_lid_not_supplied'} for m in modules]
            if not row['suggestions']:row['suggestions']=[{'fraction':None,'applied':False,'reason':'pan_lid_not_supplied'}]
        rows.append(row)
    return rows


def annual_pxx_record(view):
    if view is None:
        return {'status':'no_uncertainty_ledger','P99':None,'P99_reason':'no_uncertainty_ledger',
            'P99_message':'No uncertainty ledger is supplied. / Ledger ketidakpastian belum diisi.'}
    result=deepcopy(view)
    for obj in (result,result.get('result')):
        if not isinstance(obj,dict):continue
        old=obj.get('P99') or result.get('P99') or {}
        obj.update(P99=None,P99_reason=old.get('reason','P99_NOT_QUALIFIED'),
                   P99_message=old.get('message','P99 is not qualified by the current uncertainty method.'))
    return result


def _safe_integers(value):
    if isinstance(value, dict):
        for child in value.values(): _safe_integers(child)
    elif isinstance(value, (list, tuple)):
        for child in value: _safe_integers(child)
    elif isinstance(value, (int, np.integer)) and not isinstance(value, bool) and abs(int(value)) > 2**53-1:
        raise ValueError('report snapshot exceeds the JavaScript safe integer range')


def build_report_snapshot(source,summary,view,*,annual_pxx=None,package_checks=None,registered_run=None):
    for column in source.frame.select_dtypes(include=['integer']).columns:
        values=source.frame[column]
        if (values>2**53-1).any() or (values<-(2**53-1)).any():
            raise ValueError('report snapshot exceeds the JavaScript safe integer range')
    run={**deepcopy(registered_run or {}),**deepcopy(source.run)};run['summary_result']=deepcopy(summary)
    design=deepcopy({key:view[key] for key in ('bundle','design_fingerprint','scene_view','topology_view','topology_checks','catalog','table_layout') if key in view})
    bundle={key:design['bundle'][key] for key in ('schema_name','schema_version','project','scene','electrical_design','pinned_components') if key in design['bundle']}
    design['bundle']=bundle;bundle['simulation_runs']=[run]
    modules=bundle.get('pinned_components',{}).get('modules',{})
    inverters=bundle.get('pinned_components',{}).get('inverters',{})
    # Restrict the report catalogue to the design's pinned definitions, never the mutable library.
    design['catalog']={**design['catalog'],'modules':[m for m in design['catalog']['modules'] if m['revision_id'] in modules],
        'inverters':[i for i in design['catalog']['inverters'] if i['revision_id'] in inverters]}
    if 'interval_energy_wh' not in source.frame or 'pcc_power_w' not in source.frame:
        raise ValueError('report snapshot requires the stored interval energy and AC power')
    table=monthly(source,summary,full_precision=True)
    if not np.isfinite(source.frame.interval_energy_wh.to_numpy(dtype=float)).all():
        raise ValueError('report snapshot requires complete finite stored interval energy')
    energy=float(source.frame.interval_energy_wh.sum())/1000
    if not isclose(energy*1000,float(summary['total_energy_wh']),rel_tol=1e-9,abs_tol=0):
        raise ValueError('report snapshot interval energy does not reconcile with summary total')
    poa_key='poa_global_unshaded_w_m2' if 'poa_global_unshaded_w_m2' in source.frame else 'poa_global_w_m2'
    if poa_key not in source.frame:raise ValueError('report snapshot needs the stored PR irradiance reference')
    irradiation=float((source.frame[poa_key]*source.frame.interval_seconds/3.6e6).sum())
    if table['dc_kwp'] is None:raise ValueError('report snapshot DC nameplate basis is unavailable')
    pr=energy/(table['dc_kwp']*irradiation) if irradiation else None
    if not isclose(pr if pr is not None else 0,summary['performance_ratio'],rel_tol=1e-9,abs_tol=0):
        raise ValueError('report snapshot period PR does not reconcile with summary performance_ratio')
    table['period']={'e_ac_pcc_kwh':energy,'h_poa_kwh_m2':irradiation,'pr':pr}
    dt=source.frame.interval_seconds.to_numpy(dtype=float)
    if not np.isfinite(dt).all() or (dt<=0).any() or not (dt==dt[0]).all():raise ValueError('report snapshot needs a uniform stored cadence')
    if dt[0]==3600:
        series=run_series(source,summary)
        hourly={'days':series['days'],'values':series['hourly'].get('ac_kw',{}).get('values'),
            'interval_seconds':3600,'quality':series['quality']}
    else:
        hourly={'interval_seconds':float(dt[0]),'timestamps':[t.isoformat() for t in source.frame.timestamp],
            'power_kw':(source.frame.pcc_power_w/1000).tolist(),'values':None,'reason':'native_nonhourly_series_not_resampled'}
    mixed=bool(run.get('mixed_orientation'))
    detailed=bool(run.get('detailed_electrical_shading') or run.get('detailed_execution_identity'))
    mixed_ids={m.get('mppt_instance_id') for m in (run.get('mixed_orientation') or {}).get('mppts',[])}
    assigned_ids={row.get('target_mppt_instance_id') for row in bundle['electrical_design']['strings'] if row.get('target_mppt_instance_id')}
    limits=[{'code':code,'en':en,'id':id_,'applies':not (
        (code=='AUDIT_03_MIXED_REFERENCE' and not mixed)
        or (code=='AUDIT_04_SHADED_MISMATCH' and detailed)
        or (code=='AUDIT_06_MPPT_WINDOW' and mixed and not (assigned_ids-mixed_ids))
        or (code=='AUDIT_08_SUBHOURLY' and dt[0]>=3600))} for code,en,id_ in LIMITS]
    if mixed:limits.append({'code':'MPPT_WINDOW_MIXED_EDGE','applies':True,'en':'Mixed-orientation MPPTs hold the voltage-window edge.','id':'MPPT orientasi campuran menahan operasi pada batas jendela tegangan.'})
    schedule=[]
    for kind,definitions,instances,id_key in [('modules',modules,bundle['scene']['module_instances'],'module_definition_revision_id'),
        ('inverters',inverters,bundle['electrical_design']['inverter_instances'],'inverter_definition_revision_id')]:
        for revision,definition in definitions.items():
            count=sum(row.get(id_key)==revision for row in instances)
            schedule.append({'kind':kind,'revision_id':revision,'manufacturer':definition.get('manufacturer'),
                'model':definition.get('model'),'count':count,'rating_w':module_nameplate_w(definition) if kind=='modules' else definition.get('ac_limits',{}).get('nominal_ac_power_w')})
    result={'schema':SCHEMA,'identity':{'project_id':source.project_id,'name':bundle['project']['name'],
        **{k:run.get(k) for k in ('simulation_run_id','input_hash','project_revision_id','scene_revision_id','electrical_revision_id','weather_revision_id','engine_version')},
        'package_manifest_sha256':source.package['manifest_payload_sha256']},
        'site':deepcopy(bundle['project']['site']),'equipment':schedule,'design_view':design,
        'summary':deepcopy(summary),'production_label':{'en':'Reference Production','id':'Produksi Referensi'},
        'monthly':table,'hourly_ac':hourly,'annual_pxx':annual_pxx_record(annual_pxx),
        'method':{'limits':limits,'recorded_assumptions':deepcopy(run.get('assumptions',[])),
            'loss_disclosures':loss_disclosures(summary.get('resolved_loss_settings') or {},list(modules.values())),
            'stc_notices':[n for m in modules.values() if (n:=module_stc_notice(m)) is not None]},
        'checks':deepcopy(package_checks or {}),
        'provenance':{**source_provenance(source),'free_csv_schema':'rawibumi.free_csv.v1'}}
    result['site'].setdefault('address',None);result['site'].setdefault('installation',None)
    result['provenance']['source_interval']['interval_seconds']=float(dt[0])
    _safe_integers(result)
    result['snapshot_sha256']=sha256(canonical_json_bytes(result)).hexdigest()
    return result
