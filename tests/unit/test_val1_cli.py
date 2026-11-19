import pytest
from tests.unit._availability import missing_git
from pathlib import Path
from validation.pvsyst_benchmark.cli import prepare
from tests.fixtures.val1.synthetic import csv_bytes, project_sources, scene_bytes
from tests.unit.test_val1_completion import SPEC

ROOT = Path(__file__).resolve().parents[2]


def test_full_synthetic_preparation_emits_blocked_without_simulation(
    tmp_path, monkeypatch
):
    if reason := missing_git():
        pytest.skip(reason)
    from apps.api.study import BrowserStudyService

    def forbidden(*args, **kwargs):
        raise AssertionError("tooling must never simulate")

    monkeypatch.setattr(BrowserStudyService, "run_study", forbidden)
    manifest = {}
    for label in ["P2", "P3"]:
        case = tmp_path / label
        case.mkdir()
        vc, prj = project_sources()
        vc = vc.replace(
            b"End of PVObject pvVCalcul",
            scene_bytes().decode("utf-8-sig").encode() + b"End of PVObject pvVCalcul",
        )
        paths = {
            "csv": case / "invented.CSV",
            "vc": case / "invented.VC0",
            "prj": case / "invented.PRJ",
            "shd": case / "invented.SHD",
        }
        for k, content in [
            ("csv", csv_bytes(rows=8760)),
            ("vc", vc),
            ("prj", prj),
            ("shd", scene_bytes()),
        ]:
            paths[k].write_bytes(content)
        pan = case / "invented.pan"
        pan.write_bytes(
            (ROOT / "tests/fixtures/panond/synthetic_module.pan").read_bytes()
        )
        manifest[label] = {
            **{k: str(v) for k, v in paths.items()},
            "modules": [str(pan)],
            "inverter": str(ROOT / "tests/fixtures/val1/invented.ond"),
            "completion": SPEC,
        }
    result = prepare(
        manifest, scratch=tmp_path / "scratch", output=tmp_path / "reports"
    )
    assert [c["status"] for c in result["cases"]] == ["blocked", "blocked"]
    assert not list((tmp_path / "scratch").glob("runs/**/*"))
    assert (
        "energy_verdict" not in (tmp_path / "reports/private-report.json").read_text()
    )
