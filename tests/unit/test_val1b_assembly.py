from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.server import create_app
from validation.pvsyst_benchmark.headline_assembly import assemble_case
from validation.pvsyst_benchmark.report import privacy_violations
from tests.fixtures.val1b.synthetic import assembly_sources


def test_complete_synthetic_http_assembly_without_running_engine(tmp_path, monkeypatch):
    from apps.api.study import BrowserStudyService
    def forbidden(*args, **kwargs):
        raise AssertionError("assembly must not simulate")
    monkeypatch.setattr(BrowserStudyService,"run_study",forbidden)
    paths=assembly_sources(tmp_path/"sources")
    app=create_app(store_root=tmp_path/"projects",library_root=tmp_path/"library")
    with TestClient(app) as client:
        receipt={}
        assemble_case(client,"P2",paths,plant_loss_fraction=.01,receipt=receipt)
        assert receipt["status"]=="ready_for_annual_approval"
        assert receipt["readiness_assertions"]=={
            "ready":True,"blocker_count":0,"excluded_module_count":0,
            "placed_modules":36,"simulated_modules":36,"execution_groups":2}
        assert receipt["asserted_settings"]["all_assertions_passed"]
        assert receipt["simulation_calls"]==0 and not receipt["annual_run_authorized"]
        assert all("/simulate" not in r["path"] for r in receipt["http"])
        assert receipt["weather_hours"]==8760


def test_new_tooling_and_fixtures_privacy():
    root=Path(__file__).resolve().parents[2]
    paths=list((root/"validation/pvsyst_benchmark").glob("headline_*.py"))
    paths+=list((root/"tests/fixtures/val1b").glob("*.py"))
    paths+=list((root/"tests/unit").glob("test_val1b_*.py"))
    assert privacy_violations(paths,forbidden_tokens=["Database"+"Referances"])==[]
