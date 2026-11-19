from pathlib import Path
import json
from validation.pvsyst_benchmark.report import privacy_violations, public_summary
from validation.pvsyst_benchmark.completion import require_external
import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_val1_candidate_files_and_public_schema_do_not_disclose_private_data(tmp_path):
    paths = (
        [p for p in (ROOT / "validation/pvsyst_benchmark").iterdir() if p.is_file()]
        + [p for p in (ROOT / "tests/fixtures/val1").iterdir() if p.is_file()]
        + list((ROOT / "tests/unit").glob("test_val1_*.py"))
    )
    path_token = "Database" + "Referances"
    assert privacy_violations(paths, forbidden_tokens=[path_token]) == []
    # Public output is an allowlist: neither absolute energies nor arbitrary
    # input/source fields can be serialized through it.
    out = public_summary(
        [
            {
                "case": "P3",
                "status": "blocked",
                "reasons": [{"public_code": "module_not_ready"}],
                "evidence": {"input_path": str(tmp_path), "energy_wh": 99999},
            }
        ]
    )
    assert set(out) == {"phase", "cases"} and set(out["cases"][0]) == {
        "case",
        "status",
        "reason_codes",
    }
    assert "99999" not in json.dumps(out)
    private = tmp_path / "private.md"
    private.write_text("/" + "home/" + "fictional/source\n" + str(123) + " k" + "Wh")
    assert privacy_violations([private])
    with pytest.raises(ValueError):
        require_external(ROOT / "var/component-library", ROOT)
    assert require_external(tmp_path, ROOT) == tmp_path.resolve()
