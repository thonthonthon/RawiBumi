"""Verified snapshot/source regressions migrated from the retired B1 contract."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json

import pandas as pd
import pytest

from engine.simulation.artifacts import canonical_json_bytes, canonical_object_sha256
from reporting.exports.csv_export import export_zip
from reporting.exports import native_pdf as pdf
from apps.api.history import design_fingerprint
from tests.unit.test_rb_rpt1_free_csv import package, KWP
from tests.unit.test_phase7_csv_export import persisted, reseal, rewrite_run


def read_run(case):
    return json.loads((case.directory / "simulation-run.json").read_text())


def save_registration(case, change):
    projects = case.app.state.project_service
    bundle = projects.get_bundle(case.project_id)
    change(bundle["simulation_runs"][0])
    projects.save_bundle(bundle)


def edit_manifest(case, change):
    path = case.directory / "run-package-manifest.json"
    manifest = json.loads(path.read_text())
    change(manifest)
    manifest["artifact_count"] = len(manifest["artifacts"])
    payload = {k: v for k, v in manifest.items() if k != "manifest_payload_sha256"}
    manifest["manifest_payload_sha256"] = canonical_object_sha256(payload)
    path.write_bytes(canonical_json_bytes(manifest))


def change_summary(case, change, *, embedded=True):
    path = case.directory / "summary-result.json"
    summary = json.loads(path.read_text())
    change(summary)
    path.write_bytes(canonical_json_bytes(summary))
    if embedded:
        rewrite_run(case, lambda run: run.__setitem__("summary_result", summary))
    else:
        reseal(case)


@pytest.fixture
def report_case(persisted):
    def make(*, frame=None, status="completed"):
        if frame is None:
            frame=pd.DataFrame({'timestamp':pd.date_range('2026-10-01T10:00:00+07:00',periods=3,freq='h'), 'interval_seconds':3600.,'pcc_power_w':[-1.25,1234.5678901234567,2400.125]})
        data=frame.copy()
        if 'interval_seconds' not in data: data['interval_seconds']=3600
        if 'interval_energy_wh' not in data: data['interval_energy_wh']=data.pcc_power_w*data.interval_seconds/3600
        duration=float(data.interval_seconds.sum())/3600
        total=float(data.interval_energy_wh.sum())
        if 'ghi_w_m2' not in data: data['ghi_w_m2']=500.
        if 'poa_global_w_m2' not in data: data['poa_global_w_m2']=max(total/(.75*KWP*duration),1.)
        case=package.__wrapped__(persisted)(data=data)
        if frame is not None and duration==3 and total>0:
            # Preserve the exact numeric mutation target used by these integrity tests.
            change_summary(case, lambda summary:summary.__setitem__('performance_ratio',.75))
        if status!='completed': rewrite_run(case,lambda run:run.__setitem__('status',status))
        projects=case.app.state.project_service;bundle=projects.get_bundle(case.project_id)
        bundle['simulation_runs'][0]['status']=status
        bundle['simulation_runs'][0]['design_fingerprint']=design_fingerprint(bundle);projects.save_bundle(bundle)
        return case
    return make


def context(case, **kwargs):
    source,_=case.study._registered_report_source(case.project_id,case.run_id,require_hourly=False)
    pdf.verify_report_source(source,case.study.run_root/case.project_id/case.run_id)
    result=case.study.report_snapshot(case.project_id,case.run_id)
    pdf.prepare_snapshot(result,locale=kwargs.get('locale','en'))
    return result


def test_complete_registered_run_digest_locale_and_read_only(report_case):
    case=report_case(status='completed_with_warnings')
    before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in case.directory.rglob('*') if p.is_file()}
    result=context(case);assert result==context(case,locale='id')
    data=deepcopy(result);digest=data.pop('snapshot_sha256')
    assert digest==sha256(canonical_json_bytes(data)).hexdigest()
    assert result['identity']['project_id']==case.project_id and result['identity']['simulation_run_id']==case.run_id
    assert result['provenance']['source_dataset']['sha256']==read_run(case)['result_reference']['sha256']
    assert result['identity']['package_manifest_sha256']
    assert before=={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in before}


def test_summary_bytes_independently_checked_after_rpt3_read(report_case, monkeypatch):
    case=report_case();original=pdf.load_source
    def mutate(*args,**kwargs):
        source=original(*args,**kwargs);path=case.directory/'summary-result.json'
        path.write_bytes(path.read_bytes().replace(b'0.75',b'0.76',1));return source
    monkeypatch.setattr(pdf,'load_source',mutate)
    with pytest.raises(ValueError,match='summary-result.json byte hash'): context(case)


def test_separate_summary_supported_when_embedded_summary_is_null(report_case):
    case=report_case();rewrite_run(case,lambda run:run.__setitem__('summary_result',None))
    assert context(case)['summary']['period_duration_hours']==3


def test_saved_package_manifest_pin_and_digest_changes(report_case):
    case=report_case();before=context(case)
    manifest=json.loads((case.directory/'run-package-manifest.json').read_text())
    save_registration(case,lambda saved:saved.__setitem__('detailed_electrical_shading',{'package_manifest_sha256':manifest['manifest_payload_sha256']}))
    source,_=case.study._registered_report_source(case.project_id,case.run_id,require_hourly=False)
    assert source.package["manifest_payload_sha256"]==manifest["manifest_payload_sha256"]
    change_summary(case,lambda summary:summary['data_quality_summary'].update(audit_tag=5))
    with pytest.raises(ValueError,match='saved completion reference'):context(case)
    save_registration(case,lambda saved:saved.pop('detailed_electrical_shading'))
    assert context(case)['snapshot_sha256']!=before['snapshot_sha256']


def test_csv_unchanged_and_numerical_interval_unit_parity(report_case):
    case=report_case();source=case.study.csv_export_source(case.project_id,case.run_id)
    selected=[c['id'] for c in source.columns];before=case.study.csv_export(case.project_id,case.run_id,selected)
    data=context(case)
    assert before==case.study.csv_export(case.project_id,case.run_id,selected)==export_zip(source,selected)
    assert data['hourly_ac']['interval_seconds']==3600
    assert data['monthly']['period']['e_ac_pcc_kwh']==pytest.approx(case.frame.interval_energy_wh.sum()/1000,rel=1e-12)
    assert data['summary']['total_energy_wh']==float(case.frame.interval_energy_wh.sum())
    units={c['id']:c['unit'] for c in source.columns};assert units['pcc_power_w']=='W' and units['interval_energy_wh']=='Wh' and units['ghi_w_m2']=='W/m²'


@pytest.mark.parametrize("operation", ["one_byte", "absent", "unlisted", "mislabelled", "malformed", "duplicate_key", "nan", "overflow", "invalid_utf8", "schema"])
def test_summary_integrity_strict_json_and_schema(report_case, operation):
    case = report_case()
    path = case.directory / "summary-result.json"
    if operation == "one_byte":
        path.write_bytes(path.read_bytes().replace(b"0.75", b"0.76", 1))
    elif operation == "absent":
        path.unlink()
        reseal(case)
    elif operation == "unlisted":
        edit_manifest(case, lambda m: m.__setitem__("artifacts", [a for a in m["artifacts"] if a["relative_path"] != path.name]))
    elif operation == "mislabelled":
        edit_manifest(case, lambda m: next(a for a in m["artifacts"] if a["relative_path"] == path.name).__setitem__("role", "other"))
    elif operation == "schema":
        change_summary(case, lambda s: s.pop("total_energy_wh"), embedded=False)
    else:
        raw = path.read_bytes()
        raw = {
            "malformed": b"{", "duplicate_key": b'{"x":1,"x":2}',
            "nan": raw.replace(b"0.75", b"NaN", 1),
            "overflow": raw.replace(b"0.75", b"1e999", 1), "invalid_utf8": b"\xff",
        }[operation]
        path.write_bytes(raw)
        reseal(case)
    with pytest.raises(ValueError):
        context(case)


@pytest.mark.parametrize("artifact", ["timeseries.parquet", "simulation-run.json", "reproducibility-manifest.json", "run-package-manifest.json"])
def test_package_tampering(report_case, artifact):
    case = report_case()
    path = case.directory / artifact
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(ValueError):
        context(case)


def test_incomplete_package(report_case):
    case = report_case()
    edit_manifest(case, lambda m: m.__setitem__("package_state", "incomplete"))
    with pytest.raises(ValueError):
        context(case)


@pytest.mark.parametrize("field", ["sha256", "logical_content_sha256"])
def test_dataset_byte_and_logical_disagreement_after_reseal(report_case, field):
    case = report_case()
    def change(run):
        run["result_reference"][field] = "b" * 64
        key = "result_file_sha256" if field == "sha256" else "result_logical_content_sha256"
        run["reproducibility_manifest"][key] = "b" * 64
        (case.directory / "reproducibility-manifest.json").write_text(json.dumps(run["reproducibility_manifest"]))
    rewrite_run(case, change)
    with pytest.raises(ValueError):
        context(case)


@pytest.mark.parametrize("key,value", [
    ("simulation_run_id", "other-run"), ("period_start_time", "bad-time"),
    ("period_end_time", "2026-10-01T14:00:00+07:00"),
    ("period_duration_hours", 8760), ("annual_energy_wh", 999.), ("total_energy_wh", 999.),
])
def test_summary_identity_period_and_energy_binding(report_case, key, value):
    case = report_case()
    change_summary(case, lambda s: s.__setitem__(key, value))
    with pytest.raises(ValueError):
        context(case)


def test_embedded_summary_disagreement(report_case):
    case = report_case()
    change_summary(case, lambda s: s.__setitem__("performance_ratio", 0.5), embedded=False)
    with pytest.raises(ValueError, match="summary"):
        context(case)


@pytest.mark.parametrize("key,value", [
    ("project_revision_id", "other-r1"), ("input_hash", "b" * 64),
    ("status", "running"), ("status", "completed_with_warnings"),
    ("weather_dataset_revision_id", "other-weather"),
])
def test_actual_registered_boundary_rejects_saved_disagreement(report_case, key, value):
    case = report_case()
    save_registration(case, lambda saved: saved.__setitem__(key, value))
    with pytest.raises(ValueError):
        context(case)


def test_registered_revision_required_before_fingerprint_bound_design(report_case):
    case = report_case()
    save_registration(case, lambda saved: saved.pop("project_revision_id"))
    with pytest.raises(ValueError, match="project revision"):
        context(case)


@pytest.mark.parametrize("status", ["running", "failed", "queued", "cancelled"])
def test_actual_boundary_noncompleted_package(report_case, status):
    with pytest.raises(ValueError):
        context(report_case(status=status))


def test_actual_boundary_requires_membership_in_requested_project(report_case):
    case, other = report_case(), report_case()
    # Both fixtures use the same run ID. Remove the requested project's record;
    # the other project's record/package cannot authorize this request.
    projects = case.app.state.project_service
    bundle = projects.get_bundle(case.project_id)
    bundle["simulation_runs"] = []
    projects.save_bundle(bundle)
    with pytest.raises(ValueError, match="not found"):
        context(case)
    assert context(other)["identity"]["project_id"] == other.project_id
    # Install a foreign saved record without moving its package.
    foreign = deepcopy(read_run(other))
    bundle["simulation_runs"] = [foreign]
    projects.save_bundle(bundle)
    with pytest.raises(ValueError):
        context(case)


@pytest.mark.parametrize("bad", ["..", "../outside", "/tmp/outside", "a/b", "a\\b", "\x00bad"])
def test_actual_boundary_traversal(report_case, bad):
    case = report_case()
    with pytest.raises(ValueError):
        case.study.native_pdf_document(case.project_id, bad)
    with pytest.raises(ValueError):
        case.study.native_pdf_document(bad, case.run_id)


@pytest.mark.parametrize("kind", ["run", "project", "artifact", "nested", "ancestor"])
def test_actual_boundary_symlinks(report_case, tmp_path, kind):
    case = report_case()
    if kind == "run":
        target = case.directory.with_name("moved-run")
        case.directory.rename(target)
        case.directory.symlink_to(target, target_is_directory=True)
    elif kind == "project":
        target = case.directory.parent.with_name("moved-project")
        case.directory.parent.rename(target)
        case.directory.parent.symlink_to(target, target_is_directory=True)
    elif kind == "artifact":
        path = case.directory / "summary-result.json"
        target = tmp_path / "summary.json"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    elif kind == "nested":
        (case.directory / "unrelated-link").symlink_to(tmp_path / "absent")
    else:
        alias = tmp_path / "runs-alias"
        alias.symlink_to(case.study.run_root, target_is_directory=True)
        case.study.run_root = alias
    with pytest.raises(ValueError, match="symlink"):
        context(case)


def test_builder_rechecks_directory_and_mutated_source(report_case):
    case,other=report_case(),report_case();source=case.study.csv_export_source(case.project_id,case.run_id)
    with pytest.raises(ValueError):pdf.verify_report_source(source,other.directory)
    altered=source.frame.copy(deep=True);altered.loc[0,'pcc_power_w']=123.
    with pytest.raises(ValueError,match='source'):pdf.verify_report_source(replace(source,frame=altered),case.directory)
    (case.directory/'summary-result.json').write_bytes(b'{}')
    with pytest.raises(ValueError):pdf.verify_report_source(source,case.directory)


def test_unproven_or_earlier_design_refused_and_opaque_metadata_not_rendered(report_case):
    case=report_case();save_registration(case,lambda run:run.pop('design_fingerprint'))
    with pytest.raises(ValueError,match='earlier_design'):context(case)
    case=report_case();projects=case.app.state.project_service;bundle=projects.get_bundle(case.project_id)
    bundle['project']['site']['latitude_deg']+=.1;projects.save_bundle(bundle)
    with pytest.raises(ValueError,match='earlier_design'):context(case)

    good=report_case();private='file:///home/private/SYNTHETIC-NOT-PUBLISHED';secret='SYNTHETIC-SECRET'
    def change(run):
        run['model_manifest']['private']={'uri':private,'secret':secret}
        run['reproducibility_manifest']['model_manifest']=deepcopy(run['model_manifest'])
        (good.directory/'reproducibility-manifest.json').write_text(json.dumps(run['reproducibility_manifest']))
    rewrite_run(good,change)
    data=context(good);payload=pdf.prepare_snapshot(data)
    assert private in payload['snapshot_json']
    from tests.unit.test_phase7_native_pdf import worker_html
    html=worker_html(payload);assert private not in html and secret not in html


def test_path_like_public_identity_rejected(report_case):
    case = report_case()
    def change(run):
        run["engine_version"] = "/home/private/engine"
        run["reproducibility_manifest"]["engine_version"] = run["engine_version"]
        (case.directory / "reproducibility-manifest.json").write_text(json.dumps(run["reproducibility_manifest"]))
    rewrite_run(case, change)
    save_registration(case, lambda saved: saved.__setitem__("engine_version", "/home/private/engine"))
    with pytest.raises(ValueError, match="public identifier"):
        context(case)


@pytest.mark.parametrize("locale", ["", "fr", "en-US", "EN", "../en", None, [], 1])
def test_invalid_and_unsupported_locales(report_case, locale):
    with pytest.raises(ValueError, match="locale"):
        context(report_case(), locale=locale)


@pytest.mark.parametrize("hours", [1, 3, 72, 168])
def test_partial_samples_remain_executed_periods(report_case, hours):
    frame=pd.DataFrame({'timestamp':pd.date_range('2026-10-01T10:00:00+07:00',periods=hours,freq='h'),'interval_seconds':3600,'pcc_power_w':5.,'interval_energy_wh':5.})
    data=context(report_case(frame=frame))
    assert data['summary']['period_duration_hours']==hours
    assert data['summary']['annual_energy_wh'] is None and data['summary']['total_energy_wh']==hours*5.
    assert data['hourly_ac']['interval_seconds']==3600
    assert data['annual_pxx']['P99'] is None


@pytest.mark.parametrize("key,value", [("simulation_timestep_seconds", 1800), ("working_weather_resolution_seconds", 1800),
                                       ("timezone", "UTC"), ("project_revision_id", "other-r1")])
def test_source_resolution_timezone_and_reproduction_identity(report_case, key, value):
    case = report_case()
    def change(run):
        run["reproducibility_manifest"][key] = value
        (case.directory / "reproducibility-manifest.json").write_text(json.dumps(run["reproducibility_manifest"]))
    rewrite_run(case, change)
    with pytest.raises(ValueError):
        context(case)


@pytest.mark.parametrize("key,value", [("started_at", "invalid"), ("completed_at", "2026-10-01T00:00:00"),
                                       ("completed_at", "2026-09-01T00:00:00Z")])
def test_run_timestamps(report_case, key, value):
    case = report_case()
    rewrite_run(case, lambda run: run.__setitem__(key, value))
    with pytest.raises(ValueError):
        context(case)


def test_input_and_reproducibility_disagreement(report_case):
    case = report_case()
    def change(run):
        run["reproducibility_manifest"]["input_hashes"]["combined_input_sha256"] = "b" * 64
        (case.directory / "reproducibility-manifest.json").write_text(json.dumps(run["reproducibility_manifest"]))
    rewrite_run(case, change)
    with pytest.raises(ValueError, match="input identity"):
        context(case)


def test_large_integer_refusal_and_daylight_saving_parity(report_case):
    stamps=pd.date_range('2026-11-01T00:00:00',periods=4,freq='h',tz='America/New_York')
    frame=pd.DataFrame({'timestamp':stamps,'interval_seconds':3600,'pcc_power_w':[9007199254740993]*4})
    case=report_case(frame=frame)
    def change(run):
        run['reproducibility_manifest']['timezone']='America/New_York'
        (case.directory/'reproducibility-manifest.json').write_text(json.dumps(run['reproducibility_manifest']))
    rewrite_run(case,change)
    with pytest.raises(ValueError,match='safe integer'):context(case)
    assert stamps[1].isoformat().endswith('-04:00') and stamps[2].isoformat().endswith('-05:00')
    # A valid same-offset source keeps the two DST intervals distinct, without rebinning.
    frame['pcc_power_w']=5.;frame['interval_energy_wh']=5.;case=report_case(frame=frame);rewrite_run(case,change)
    result=context(case);assert result['provenance']['source_timezone']=='America/New_York'
    assert result['summary']['period_duration_hours']==4 and len(case.frame)==4


def test_nullable_values_preserved_without_fabricated_totals(report_case):
    frame=pd.DataFrame({'timestamp':pd.date_range('2026-10-01T10:00:00+07:00',periods=3,freq='h'),'interval_seconds':3600.,'pcc_power_w':[0.,float('nan'),-1.5]})
    case=report_case(frame=frame)
    with pytest.raises(ValueError):context(case)
    case=report_case();data=context(case)
    assert data['annual_pxx']['P99'] is None
    assert data['method']['loss_disclosures'][0]['suggestions'][0]['fraction'] is None
