"""B2B authored HTTP regressions; never run during the authoring stage.

Synthetic registered packages and renderer sentinels only. These tests make no
claim about live Chromium, hosted authorization, or production isolation.
"""
from copy import deepcopy
from hashlib import sha256
from urllib.parse import quote, urlsplit, urlunsplit, parse_qs
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from apps.api.server import create_app
from engine.simulation.artifacts import canonical_json_bytes
from reporting.exports import native_pdf as pdf
from tests.unit.test_phase7_csv_export import persisted, REQUEST
from tests.unit.test_phase7_report_contract import report_case, save_registration


CAPABILITY = "/api/reporting/native-pdf/capability"
PDF = b"%PDF-1.7\n%\x80\xff\x00\nsynthetic transport fixture\n%%EOF\n"
PRIVATE = "/private/runtime/secret worker-stderr TOKEN=private-token"
UNAVAILABLE = "Verified report is unavailable for this project and run."


@pytest.fixture(autouse=True)
def default_off(monkeypatch):
    monkeypatch.delenv("RAWIBUMI_DEPLOYMENT_EDITION", raising=False)
    monkeypatch.delenv("RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED", raising=False)


def enable(monkeypatch):
    monkeypatch.setenv("RAWIBUMI_DEPLOYMENT_EDITION", "community_self_hosted")
    monkeypatch.setenv("RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED", "1")


def url(case):
    return case.path + "/native-pdf"


def snapshot(case):
    return {p.relative_to(case.directory): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in case.directory.rglob("*") if p.is_file()}


def download(client, path, method, **kwargs):
    if method == 'GET': return client.get(path, **kwargs)
    parts=urlsplit(path)
    locale=parse_qs(parts.query,keep_blank_values=True).get('locale',['en'])[-1]
    params=kwargs.pop('params',None) or {}
    return client.post(urlunsplit(parts._replace(query='')),json={'locale':params.get('locale',locale)},**kwargs)


def assert_safe(response, status, detail):
    assert response.status_code == status, response.text
    assert response.json() == {"detail": detail}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert PRIVATE not in response.text
    assert "Traceback" not in response.text


@pytest.mark.parametrize("edition,flag,enabled", [
    (None, None, False), (None, "1", False), ("community_self_hosted", None, False),
    ("community_self_hosted", "1", True), ("hosted", "1", False),
    ("hosted_paid", "1", False), ("guest", "1", False), ("registered_free", "1", False),
    ("", "1", False), ("community", "1", False), ("COMMUNITY_SELF_HOSTED", "1", False),
    (" community_self_hosted", "1", False), ("community_self_hosted ", "1", False),
    ("community_self_hosted,hosted", "1", False),
    ("community_self_hosted", "true", False), ("community_self_hosted", "01", False),
    ("community_self_hosted", "1 ", False), ("community_self_hosted", "0", False),
    ("community_self_hosted", "", False),
])
@pytest.mark.parametrize("method",["GET","POST"])
def test_effective_gate_capability_and_early_denial(tmp_path, monkeypatch, edition, flag, enabled, method):
    # DEC-P2: with no flag the PDF follows the renderer; these rows mean "no renderer configured".
    for name in ("RAWIBUMI_PDF_NODE", "RAWIBUMI_PDF_RUNTIME_ROOT", "RAWIBUMI_PDF_CHROMIUM_EXECUTABLE"):
        monkeypatch.delenv(name, raising=False)
    if edition is not None:
        monkeypatch.setenv("RAWIBUMI_DEPLOYMENT_EDITION", edition)
    if flag is not None:
        monkeypatch.setenv("RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED", flag)
    app = create_app(store_root=tmp_path / "projects")
    renderer = Mock(return_value=PDF)
    monkeypatch.setattr(app.state.study_service, "native_pdf_document", renderer)
    with TestClient(app) as client:
        capability = client.get(CAPABILITY)
        assert capability.status_code == 200
        assert capability.json() == {"enabled": enabled, "format": "pdf", "text_based": True, "locales": ["en", "id"]}
        assert capability.headers["cache-control"] == "no-store"
        renderer.assert_not_called()
        response = download(client, '/api/projects/p/runs/r/exports/native-pdf', method=method)
        if enabled:
            assert response.status_code == 200
            renderer.assert_called_once_with("p", "r", locale="en")
        else:
            assert_safe(response, 404, "Native PDF download is unavailable.")
            assert_safe(download(client, '/api/projects/p/runs/r/exports/native-pdf?locale=invalid', method=method),
                        404, "Native PDF download is unavailable.")
            renderer.assert_not_called()


@pytest.mark.parametrize("method",["GET","POST"])
def test_browser_claims_cannot_enable_server_gate(report_case, monkeypatch, method):
    case = report_case()
    renderer = Mock(return_value=PDF)
    monkeypatch.setattr(case.study, "native_pdf_document", renderer)
    claims = {"edition": "community_self_hosted", "RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED": "1", "enabled": "true"}
    headers = {"X-Deployment-Edition": "community_self_hosted", "X-Forwarded-Edition": "community_self_hosted",
               "Authorization": "Bearer invented", "Cookie": "edition=community_self_hosted; enabled=1"}
    assert case.client.get(CAPABILITY, params=claims, headers=headers).json()["enabled"] is False
    assert_safe(download(case.client, url(case), method=method, params=claims, headers=headers), 404, "Native PDF download is unavailable.")
    renderer.assert_not_called()


@pytest.mark.parametrize("locale", ["", "EN", "en-US", "fr", "id-ID", " en", "id ", PRIVATE, "\x00"])
@pytest.mark.parametrize("method",["GET","POST"])
def test_locale_is_strict_and_diagnostic_is_fixed(report_case, monkeypatch, locale, method):
    enable(monkeypatch)
    case = report_case()
    renderer = Mock(return_value=PDF)
    monkeypatch.setattr(case.study, "native_pdf_document", renderer)
    assert_safe(download(case.client, url(case), method=method, params={'locale': locale}), 422, "Native PDF locale must be en or id.")
    renderer.assert_not_called()


@pytest.mark.parametrize("method",["GET","POST"])
def test_verified_context_locale_digest_source_and_csv_parity(report_case, monkeypatch, method):
    enable(monkeypatch)
    case = report_case(status="completed_with_warnings")
    before = snapshot(case)
    contexts = []

    def render(context, **options):
        data=deepcopy(context);digest=data.pop("snapshot_sha256")
        assert digest == sha256(canonical_json_bytes(data)).hexdigest()
        contexts.append((deepcopy(context), options))
        return PDF

    monkeypatch.setattr(pdf, "render_native_pdf", render)
    monkeypatch.setattr(case.study, "run_result", Mock(side_effect=AssertionError("Mutable results used")))
    csv_before = case.client.post(case.path, json=REQUEST)
    assert csv_before.status_code == 200
    for locale in ("en", "id"):
        # Neither query claims nor an unsolicited body can supply report data or a worker.
        response = case.client.request(method, url(case), params={"locale": locale, "worker": PRIVATE, "digest": "forged"},
                                       json={"html": PRIVATE, "data": {"summary": "forged"}})
        if method == 'POST':
            assert response.status_code == 422
            response=download(case.client,url(case),method,params={'locale':locale})
        assert response.status_code == 200
        assert response.content == PDF
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == 'attachment; filename="RawiBumi_verified_report.pdf"'
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert int(response.headers["content-length"]) == len(PDF)
    assert [c[1] for c in contexts] == [{"locale":"en","plan_figure_png":None},{"locale":"id","plan_figure_png":None}]
    assert contexts[0][0] == contexts[1][0]
    assert contexts[0][0]["snapshot_sha256"] == contexts[1][0]["snapshot_sha256"]
    assert PRIVATE not in str(contexts)
    csv_after = case.client.post(case.path, json=REQUEST)
    assert csv_after.content == csv_before.content
    assert snapshot(case) == before


@pytest.mark.parametrize("kind", ["missing_project", "missing_run", "unregistered", "foreign", "identity", "incomplete"])
@pytest.mark.parametrize("method",["GET","POST"])
def test_registered_membership_and_identity_required(report_case, monkeypatch, kind, method):
    enable(monkeypatch)
    case = report_case()
    renderer = Mock(return_value=PDF)
    monkeypatch.setattr(pdf, "render_native_pdf", renderer)
    path, status = url(case), 422
    if kind == "missing_project":
        path, status = path.replace(case.project_id, "missing-project"), 404
    elif kind == "missing_run":
        path = path.replace(case.run_id, "missing-run")
    elif kind == "identity":
        save_registration(case, lambda r: r.__setitem__("input_hash", "b" * 64))
    elif kind == "incomplete":
        save_registration(case, lambda r: r.__setitem__("status", "running"))
    else:
        projects = case.app.state.project_service
        bundle = projects.get_bundle(case.project_id)
        bundle["simulation_runs"] = []
        # A foreign project's existing registration cannot authorize this run.
        if kind == "foreign":
            other = report_case()
            bundle["simulation_runs"] = other.app.state.project_service.get_bundle(other.project_id)["simulation_runs"]
        projects.save_bundle(bundle)
    assert_safe(download(case.client, path, method=method), status, UNAVAILABLE)
    renderer.assert_not_called()


@pytest.mark.parametrize("project,run", [("..%2Foutside", "synthetic-run"), (None, "..%2Foutside"),
    (None, "a%5Cb"), (None, "%00bad"), (None, "%2Ftmp%2Foutside")])
@pytest.mark.parametrize("method",["GET","POST"])
def test_traversal_is_refused_without_rendering(report_case, monkeypatch, project, run, method):
    enable(monkeypatch)
    case = report_case()
    renderer = Mock(return_value=PDF)
    monkeypatch.setattr(pdf, "render_native_pdf", renderer)
    path = f"/api/projects/{project or quote(case.project_id, safe='')}/runs/{run}/exports/native-pdf"
    response = download(case.client, path, method=method)
    assert response.status_code in ({404, 422} if method == "GET" else {404, 405, 422})
    assert "outside" not in response.text
    assert str(case.directory) not in response.text
    renderer.assert_not_called()


@pytest.mark.parametrize("kind", ["run", "project", "artifact"])
@pytest.mark.parametrize("method",["GET","POST"])
def test_symlinks_are_refused(report_case, monkeypatch, tmp_path, kind, method):
    enable(monkeypatch)
    case = report_case()
    renderer = Mock(return_value=PDF)
    monkeypatch.setattr(pdf, "render_native_pdf", renderer)
    original = case.directory if kind == "run" else case.directory.parent if kind == "project" else case.directory / "summary-result.json"
    target = tmp_path / "moved"
    original.rename(target)
    original.symlink_to(target, target_is_directory=kind != "artifact")
    assert_safe(download(case.client, url(case), method=method), 422, UNAVAILABLE)
    renderer.assert_not_called()


@pytest.mark.parametrize("artifact", ["timeseries.parquet", "simulation-run.json", "summary-result.json", "run-package-manifest.json"])
@pytest.mark.parametrize("mode", ["corrupt", "missing"])
@pytest.mark.parametrize("method",["GET","POST"])
def test_corrupt_or_missing_artifacts_fail_closed(report_case, monkeypatch, artifact, mode, method):
    enable(monkeypatch)
    case = report_case()
    renderer = Mock(return_value=PDF)
    monkeypatch.setattr(pdf, "render_native_pdf", renderer)
    path = case.directory / artifact
    if mode == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"corrupt")
    response = download(case.client, url(case), method=method)
    assert response.status_code in ({404, 422} if method == "GET" else {404, 405, 422})
    assert response.json() == {"detail": UNAVAILABLE}
    assert str(case.directory) not in response.text
    renderer.assert_not_called()


@pytest.mark.parametrize("error,status,detail", [
    (pdf.NativePDFError(PRIVATE), 503, "Native PDF service is unavailable. Please retry later."),
    (pdf.NativePDFError("native PDF worker timeout " + PRIVATE), 503, "Native PDF service is unavailable. Please retry later."),
    (RuntimeError(PRIVATE), 500, "Native PDF download failed."),
    (OSError(PRIVATE), 500, "Native PDF download failed."),
    (ValueError(PRIVATE), 422, UNAVAILABLE), (KeyError(PRIVATE), 422, UNAVAILABLE),
    (FileNotFoundError(PRIVATE), 404, UNAVAILABLE),
])
@pytest.mark.parametrize("method",["GET","POST"])
def test_exceptions_and_worker_diagnostics_are_sanitized(report_case, monkeypatch, error, status, detail, method):
    enable(monkeypatch)
    case = report_case()
    monkeypatch.setattr(case.study, "native_pdf_document", Mock(side_effect=error))
    assert_safe(download(case.client, url(case), method=method), status, detail)


@pytest.mark.parametrize("kind", ["empty", "short", "json", "html", "string", "oversized", "maximum"])
@pytest.mark.parametrize("method",["GET","POST"])
def test_pdf_signature_type_and_bounded_payload(report_case, monkeypatch, kind, method):
    enable(monkeypatch)
    case = report_case()
    values = {"empty": b"", "short": b"%PDF", "json": b'{"detail":"error"}', "html": b"<html>error</html>", "string": "%PDF-invalid"}
    content = b"%PDF-" + b"x" * (pdf.MAX_PDF_BYTES - 5 + (kind == "oversized")) if kind in {"maximum", "oversized"} else values[kind]
    monkeypatch.setattr(case.study, "native_pdf_document", Mock(return_value=content))
    response = download(case.client, url(case), method=method)
    if kind == "maximum":
        assert response.status_code == 200
        assert response.content == content
    else:
        assert_safe(response, 500, "Native PDF download failed.")


def test_csv_error_translation_is_preserved(report_case, monkeypatch):
    case = report_case()
    monkeypatch.setattr(case.study, "csv_export", Mock(side_effect=ValueError("existing CSV diagnostic")))
    response = case.client.post(case.path, json=REQUEST)
    assert response.status_code == 422
    assert response.json() == {"detail": "existing CSV diagnostic"}
