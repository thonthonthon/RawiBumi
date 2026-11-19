"""S15: the run time-series route, the full export deliverable, readiness warnings on runs, one DC nameplate (D14)."""

import csv
from hashlib import sha256
from io import BytesIO, StringIO
import json
from zipfile import ZipFile

import pandas as pd
import pytest

from apps.api.catalog import catalog_summaries
from components.design_integration import module_nameplate_w
from reporting.exports.csv_export import ExportSource
from reporting.exports.series import monthly, run_series
from tests.unit.test_rb_fix_s16_multi_group import make_design  # noqa: F401 (fixture)
from tests.unit.test_rb_fix_s2_honest_preflight import MODULE, Project


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    """One project of 20 modules (one 20-module string) with a completed run on the fixture weather day."""
    p = Project(tmp_path_factory.mktemp("s15"), 20, weather=True, strings=True)
    run = p.client.post(p.url + "/simulate", json={})
    assert run.status_code == 200, run.text
    return p, run.json()


def _series(p, run_id):
    response = p.client.get(p.url + f"/runs/{run_id}/timeseries")
    assert response.status_code == 200, response.text
    return response.json()


def _export(p, run_id, **body):
    request = {"format": "csv", "resolution": "hourly", "level": "project", "columns": ["pcc_power_w", "poa_global_w_m2"], **body}
    return p.client.post(p.url + f"/runs/{run_id}/exports", json=request)


# --- the time-series route ------------------------------------------------------------------------------------------

def test_route_returns_local_day_by_hour_matrices_from_the_stored_series(ran):
    p, run = ran
    view = _series(p, run["simulation_run_id"])
    frame = pd.read_parquet(p.study.run_root / p.pid / run["simulation_run_id"] / "timeseries.parquet")
    assert view["timezone"] == "Asia/Jakarta" and view["days"] == ["2025-01-01"] and view["period"]["hours"] == 24
    assert set(view["hourly"]) == {"ac_kw", "poa_w_m2", "ghi_w_m2", "cell_temperature_c", "ambient_temperature_c"}
    ac = view["hourly"]["ac_kw"]
    assert ac["unit"] == "kW" and ac["source_column"] == "pcc_power_w" and len(ac["values"]) == 1 and len(ac["values"][0]) == 24
    assert ac["values"][0] == pytest.approx((frame["pcc_power_w"] / 1000).round(6).tolist(), abs=1e-9)
    assert view["hourly"]["poa_w_m2"]["values"][0] == pytest.approx(frame["poa_global_w_m2"].round(6).tolist(), abs=1e-9)
    assert view["quality"] == {"repeated_local_hours_averaged": 0, "missing_hour_cells": 0}


def test_monthly_table_reconciles_with_the_summary(ran):
    p, run = ran
    view = _series(p, run["simulation_run_id"])
    summary = run["summary_result"]
    [month] = view["monthly"]
    assert month["month"] == "2025-01" and month["energy_kwh"] == pytest.approx(summary["total_energy_wh"] / 1000, rel=1e-6)
    # kWp is the D14 nameplate: 20 × the datasheet nominal power.
    nominal = module_nameplate_w(p.bundle()["pinned_components"]["modules"][MODULE])
    assert view["dc_kwp"] == pytest.approx(20 * nominal / 1000, rel=1e-9)
    assert month["specific_yield_kwh_kwp"] == pytest.approx(summary["specific_yield_wh_per_wp"], rel=1e-6)
    # One month: the monthly PR is the engine's period PR.
    assert month["performance_ratio"] == pytest.approx(summary["performance_ratio"], rel=1e-5)
    lost = {item["loss_type"]: item["lost_energy_wh"] / 1000 for item in summary["loss_summary"]}
    assert set(month["losses_kwh"]) == set(lost)
    for name, kwh in month["losses_kwh"].items():
        assert kwh == pytest.approx(lost[name], abs=1e-6), name
    assert all(c["monthly"] for c in view["loss_channels"])


def test_a_summary_that_does_not_reconcile_is_refused(ran):
    p, run = ran
    source = p.study.csv_export_source(p.pid, run["simulation_run_id"])
    summary = json.loads((p.study.run_root / p.pid / run["simulation_run_id"] / "summary-result.json").read_text())
    with pytest.raises(ValueError, match="does not reconcile"):
        monthly(source, {**summary, "total_energy_wh": summary["total_energy_wh"] * 1.01})
    with pytest.raises(ValueError, match="monthly energy"):
        monthly(source, {**summary, "monthly_energy": [{"month": "2025-02", "energy_wh": summary["total_energy_wh"]}]})
    broken = [{**item, "lost_energy_wh": item["lost_energy_wh"] + 5.0} if item["loss_type"] == "soiling" else item for item in summary["loss_summary"]]
    with pytest.raises(ValueError, match="soiling"):
        monthly(source, {**summary, "loss_summary": broken})


def test_route_refusals(ran):
    p, run = ran
    unknown = p.client.get(p.url + "/runs/run-404/timeseries")
    assert unknown.status_code == 422 and "run not found" in unknown.text
    bundle = p.service.get_bundle(p.pid)
    [record] = bundle["simulation_runs"]
    record["package_omitted"] = True
    p.service.store.save(bundle)
    try:
        omitted = p.client.get(p.url + f"/runs/{run['simulation_run_id']}/timeseries")
        assert omitted.status_code == 422 and "wasn't included in the imported file" in omitted.text
    finally:
        record.pop("package_omitted")
        p.service.store.save(bundle)


def test_daylight_saving_repeated_hour_is_averaged_and_missing_hour_is_null():
    stamps = pd.date_range("2025-10-26 00:00", periods=25, freq="h", tz="Europe/Berlin")
    frame = pd.DataFrame({"timestamp": stamps, "interval_seconds": 3600, "pcc_power_w": [float(i) * 1000 for i in range(25)]})
    source = ExportSource("p", {"simulation_run_id": "r"}, {}, {}, frame, [])
    summary = {"total_energy_wh": float(frame["pcc_power_w"].sum()), "specific_yield_wh_per_wp": 0.0,
               "monthly_energy": [{"month": "2025-10", "energy_wh": float(frame["pcc_power_w"].sum())}], "loss_summary": []}
    view = run_series(source, summary)
    assert view["days"] == ["2025-10-26"] and view["quality"]["repeated_local_hours_averaged"] == 1
    row = view["hourly"]["ac_kw"]["values"][0]
    assert row[2] == pytest.approx((2 + 3) / 2)  # 02:00 happens twice on the fall-back day
    assert row[23] == 24.0 and view["dc_kwp"] is None and view["monthly"][0]["performance_ratio"] is None


def test_multi_inverter_run_has_a_plant_series(make_design):
    design = make_design("duplicate")
    run = design.post("/simulate", {})
    view = design.client.get(design.url + f"/runs/{run['simulation_run_id']}/timeseries")
    assert view.status_code == 200, view.text
    view = view.json()
    assert view["monthly"][0]["energy_kwh"] == pytest.approx(run["summary_result"]["total_energy_wh"] / 1000, rel=1e-6)


# --- the export deliverable -----------------------------------------------------------------------------------------

def test_default_export_is_unchanged(ran):
    p, run = ran
    first, second = _export(p, run["simulation_run_id"]), _export(p, run["simulation_run_id"])
    assert first.status_code == 200 and first.content == second.content
    assert 'filename="RawiBumi_numerical_export.zip"' in first.headers["content-disposition"]
    archive = ZipFile(BytesIO(first.content))
    assert archive.namelist() == ["timeseries.csv", "export-manifest.json"]
    manifest = json.loads(archive.read("export-manifest.json"))
    assert "files" not in manifest and "formats" not in manifest and "deliverable" not in manifest
    assert manifest["csv_sha256"] == sha256(archive.read("timeseries.csv")).hexdigest()


def test_the_full_deliverable_lists_every_file_with_its_hash(ran):
    p, run = ran
    response = _export(p, run["simulation_run_id"], formats=["csv", "parquet"], deliverable=True)
    assert response.status_code == 200, response.text
    assert 'filename="RawiBumi_results_bundle.zip"' in response.headers["content-disposition"]
    archive = ZipFile(BytesIO(response.content))
    assert archive.namelist() == ["timeseries.csv", "timeseries.parquet", "monthly.csv", "summary-result.json",
                                  "design-validation-report.json", "validation-findings.json", "run-record.json", "export-manifest.json"]
    manifest = json.loads(archive.read("export-manifest.json"))
    assert manifest["formats"] == ["csv", "parquet"]
    for entry in manifest["files"]:
        content = archive.read(entry["path"])
        assert entry["sha256"] == sha256(content).hexdigest() and entry["byte_size"] == len(content) and entry["description"]
    directory = p.study.run_root / p.pid / run["simulation_run_id"]
    for name in ("summary-result.json", "design-validation-report.json", "validation-findings.json"):
        assert archive.read(name) == (directory / name).read_bytes()
    record = json.loads(archive.read("run-record.json"))
    assert record["simulation_run_id"] == run["simulation_run_id"] and record["readiness_warnings"] == run["readiness_warnings"]
    assert manifest["deliverable"]["readiness_warnings"] == run["readiness_warnings"]
    assert manifest["deliverable"]["dc_kwp"] == pytest.approx(11.0)
    # Parquet holds exactly the CSV's columns and values.
    table = pd.read_parquet(BytesIO(archive.read("timeseries.parquet")))
    rows = list(csv.reader(StringIO(archive.read("timeseries.csv").decode())))
    assert list(table.columns) == rows[0] == ["timestamp", "interval_seconds", "poa_global_w_m2", "pcc_power_w"]
    assert table["pcc_power_w"].tolist() == [float(r[3]) for r in rows[1:]]
    monthly_rows = list(csv.DictReader(StringIO(archive.read("monthly.csv").decode())))
    assert [r["month"] for r in monthly_rows] == ["2025-01"]
    assert float(monthly_rows[0]["energy_kwh"]) == pytest.approx(run["summary_result"]["total_energy_wh"] / 1000, rel=1e-6)
    assert float(monthly_rows[0]["loss_soiling_kwh"]) > 0
    assert {c["id"] for c in manifest["deliverable"]["monthly_columns"]} == set(monthly_rows[0])


def test_parquet_only_and_format_refusals(ran):
    p, run = ran
    archive = ZipFile(BytesIO(_export(p, run["simulation_run_id"], formats=["parquet"]).content))
    assert archive.namelist() == ["timeseries.parquet", "export-manifest.json"]
    manifest = json.loads(archive.read("export-manifest.json"))
    assert "csv_sha256" not in manifest and manifest["files"][0]["path"] == "timeseries.parquet"
    for bad in (["xls"], [], ["csv", "csv"]):
        assert _export(p, run["simulation_run_id"], formats=bad).status_code == 422, bad
    assert _export(p, run["simulation_run_id"], deliverable="yes").status_code == 422


# --- readiness warnings on the run record ---------------------------------------------------------------------------

def test_new_runs_keep_their_launch_readiness_warnings(tmp_path):
    p = Project(tmp_path, 119, string_length=19)  # 5 modules stay unstrung: a non-blocking warning
    ready = p.client.get(p.url + "/execution-readiness").json()
    expected = [f for f in ready["findings"] if f["severity"] == "warning"]
    assert expected
    run = p.client.post(p.url + "/simulate", json={}).json()
    assert [w["rule_id"] for w in run["readiness_warnings"]] == [f["rule_id"] for f in expected]
    assert run["readiness_warnings"][0]["message"] == expected[0]["message"]
    [saved] = p.bundle()["simulation_runs"]
    assert saved["readiness_warnings"] == run["readiness_warnings"]


# --- D14: one DC nameplate ------------------------------------------------------------------------------------------

def test_one_nameplate_basis_for_a_module_whose_model_pmp_differs(tmp_path):
    p = Project(tmp_path, 20, weather=False, strings=True)
    definition = p.bundle()["pinned_components"]["modules"][MODULE]
    assert definition["stc"]["nominal_power_w"] == 550.0 and definition["stc"]["pmp_w"] != 550.0
    assert module_nameplate_w(definition) == 550.0
    assert module_nameplate_w({"stc": {"pmp_w": 410.5}}) == 410.5  # no nominal: the STC Pmp
    summary = next(m for m in catalog_summaries(p.service.catalog)["modules"] if m["revision_id"] == MODULE)
    assert summary["nominal_power_w"] == 550.0 and summary["pmp_w"] == definition["stc"]["pmp_w"]
    from apps.api.study import _validation_configuration
    from validation.engineering import validate_engineering_design
    b = p.bundle()
    report = validate_engineering_design(b["scene"], b["electrical_design"], project_revision_id=b["electrical_design"]["project_revision_id"],
                                         component_revisions={**b["pinned_components"]["modules"], **b["pinned_components"]["inverters"]},
                                         configuration=_validation_configuration(), design_validation_report_id="d14", generated_at="2026-11-09T00:00:00+00:00")
    ratio = next(f for f in report["findings"] if f["rule_id"] == "INVERTER_DC_AC_RATIO")
    assert ratio["context"]["connected_dc_stc_power_w"] == pytest.approx(20 * 550.0)
