"""DEC-P2 (user, 2026-11-08): the report is a supported deliverable. Open-Meteo runs were refused because their
fixed time-convention token joins two parts with ';'. The PDF switch follows the renderer on community self-hosted."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import server
from apps.api.server import create_app
from reporting.exports.native_pdf import NativePDFError, _convention, prepare_snapshot
from reporting.exports.native_pdf import _public_convention
from tests.unit.test_phase7_report_contract import report_case, context
from tests.unit.test_phase7_csv_export import persisted, rewrite_run
from tests.unit.test_phase7_native_pdf import worker_html
from tests.unit.test_rb_fix_s2_honest_preflight import Project

ROOT = Path(__file__).resolve().parents[2]
OPEN_METEO = "mixed_open_meteo_hourly_label:solar_preceding_hour_mean;state_instant_at_label"
# Every source_timestamp_convention the weather importers and providers write today.
VOCABULARY = [OPEN_METEO, "interval_start", "interval_end", "epw_hour_1_24_interval"]
REFUSED = ["a;", ";a", "a;;b", "a; b", "x;../etc", "a;file:secret", "a;.", "with space", "path/to", "a;b/c", "", "a\nb"]


@pytest.mark.parametrize("token", VOCABULARY)
def test_every_source_convention_is_publishable_in_both_guards(token, report_case):
    assert _public_convention(token) == token
    assert _convention(token) == token
    case=report_case()
    def change(run):
        run['reproducibility_manifest']['source_timestamp_convention']=token
        (case.directory/'reproducibility-manifest.json').write_text(__import__('json').dumps(run['reproducibility_manifest']))
    rewrite_run(case,change)
    source=context(case)
    for locale in ('en','id'): assert token in worker_html(prepare_snapshot(source,locale=locale))


@pytest.mark.parametrize("token", REFUSED)
def test_paths_free_text_and_empty_parts_stay_refused(token):
    with pytest.raises(ValueError):
        _public_convention(token)
    with pytest.raises((NativePDFError, ValueError)):
        _convention(token)


def test_open_meteo_provenance_reaches_annual_snapshot_and_positive_full_report(tmp_path, request):
    p = Project(tmp_path, 18, weather=False)
    p.study.acquire_weather(p.pid, source_id="open_meteo_archive_era5", start_date="2025-01-01", end_date="2025-12-31",
                            raw_response=(ROOT / "tests/fixtures/weather/open_meteo_era5_annual_padded_s10.json").read_bytes())
    run = p.client.post(p.url + "/simulate", json={})
    assert run.status_code == 200, run.text
    source=p.study.report_snapshot(p.pid,run.json()['simulation_run_id'])
    assert source['provenance']['source_interval']['source_timestamp_convention']==OPEN_METEO
    # The public all-dark annual fixture has negative standby energy: retain the annual integrity refusal.
    assert source['summary']['annual_energy_wh']<0
    assert prepare_snapshot(source)['snapshot_sha256']==source['snapshot_sha256']
    with pytest.raises(AssertionError,match='PDF_REPORT_RENDER_FAILED'):worker_html(prepare_snapshot(source))
    import pandas as pd
    positive=request.getfixturevalue("report_case")(frame=pd.DataFrame({'timestamp':pd.date_range('2025-01-01',periods=8760,freq='h',tz='Asia/Jakarta'),'interval_seconds':3600,'pcc_power_w':5.,'interval_energy_wh':5.}))
    def change(run):
        run['reproducibility_manifest']['source_timestamp_convention']=OPEN_METEO
        (positive.directory/'reproducibility-manifest.json').write_text(__import__('json').dumps(run['reproducibility_manifest']))
    rewrite_run(positive,change)
    complete=context(positive)
    assert complete['summary']['annual_energy_wh']>0
    assert OPEN_METEO in worker_html(prepare_snapshot(complete))



RENDERER = ("RAWIBUMI_PDF_NODE", "RAWIBUMI_PDF_RUNTIME_ROOT", "RAWIBUMI_PDF_CHROMIUM_EXECUTABLE")


@pytest.mark.parametrize("edition,flag,renderer,enabled", [
    ("community_self_hosted", None, True, True),      # on whenever the renderer is configured
    ("community_self_hosted", None, False, False),    # nothing to render with
    ("community_self_hosted", "0", True, False),      # the operator turned it off
    ("community_self_hosted", "1", False, True),      # explicit on, as before
    ("community_self_hosted", "true", True, False),   # an unclear flag fails closed
    ("community_self_hosted", "", True, False),
    (None, None, True, False),                        # other editions stay off (hosted until Phase 8)
    ("hosted_paid", None, True, False),
    ("hosted_paid", "1", True, False),
    ("COMMUNITY_SELF_HOSTED", None, True, False),
])
def test_pdf_switch_follows_the_renderer_on_community_self_hosted(tmp_path, monkeypatch, edition, flag, renderer, enabled):
    for name, value in (("RAWIBUMI_DEPLOYMENT_EDITION", edition), ("RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED", flag)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    for name in RENDERER:
        if renderer:
            monkeypatch.setenv(name, str(tmp_path))
        else:
            monkeypatch.delenv(name, raising=False)
    assert server._community_native_pdf_enabled() is enabled
    with TestClient(create_app(store_root=tmp_path / "projects")) as client:
        assert client.get("/api/reporting/native-pdf/capability").json()["enabled"] is enabled


def test_renderer_paths_must_be_absolute_and_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("RAWIBUMI_DEPLOYMENT_EDITION", "community_self_hosted")
    monkeypatch.delenv("RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED", raising=False)
    for name in RENDERER:
        monkeypatch.setenv(name, str(tmp_path))
    monkeypatch.setenv("RAWIBUMI_PDF_NODE", "node")
    assert server._community_native_pdf_enabled() is False
    monkeypatch.setenv("RAWIBUMI_PDF_NODE", str(tmp_path / "missing"))
    assert server._community_native_pdf_enabled() is False
