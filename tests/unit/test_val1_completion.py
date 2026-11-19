from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from apps.api.server import create_app
from validation.pvsyst_benchmark.completion import complete_inverter

ROOT = Path(__file__).resolve().parents[2]
SPEC = {
    "model_token": "FICT-10",
    "identity_checks": {"mppt_template.count": 2},
    "fields": {
        "mppt_template.max_operating_current_a": 12.0,
        "mppt_template.max_short_circuit_current_a": 20.0,
    },
    "source": {
        "document": "Fictional source for synthetic test only",
        "page_or_section": "Input table",
        "url": "https://example.com/invented",
    },
}


def test_actual_completion_route_keeps_sources_and_new_revision(tmp_path):
    protected = ROOT / "var/component-library"
    existed = protected.exists()
    app = create_app(
        store_root=tmp_path / "projects", library_root=tmp_path / "library"
    )
    with TestClient(app) as client:
        result = complete_inverter(
            client, ROOT / "tests/fixtures/val1/invented.ond", SPEC
        )
        assert result["base_hidden"]
        assert result["readiness"]["ready"], result
        assert result["citation"]["source"] == SPEC["source"]
        assert result["citation"]["fields"] == SPEC["fields"]
        entries = app.state.project_service.library.entries(include_hidden=True)
        base = next(
            e
            for e in entries
            if e["definition"]["revision_id"] == result["base_revision_id"]
        )
        assert (
            base["definition"]["mppt_template"].get("max_operating_current_a") is None
        )
        assert result["definition"]["mppt_template"]["max_operating_current_a"] == 12
        assert list((tmp_path / "library/sources/sha256").glob("*.ond"))
        assert protected.exists() == existed
        assert app.state.project_service.library.root.resolve().is_relative_to(
            tmp_path.resolve()
        )


def test_completion_rejects_mismatched_model(tmp_path):
    app = create_app(
        store_root=tmp_path / "projects", library_root=tmp_path / "library"
    )
    with TestClient(app) as c:
        with pytest.raises(ValueError, match="identity"):
            complete_inverter(
                c,
                ROOT / "tests/fixtures/val1/invented.ond",
                {**SPEC, "model_token": "unrelated"},
            )
