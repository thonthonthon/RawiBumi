import numpy as np
import pandas as pd
import pytest
from validation.pvsyst_benchmark.reference import Basis
from validation.pvsyst_benchmark.compare import (
    stage_metrics,
    grid_verdict,
    factor_metrics,
)
from validation.pvsyst_benchmark.report import (
    blocked_report,
    public_summary,
    write_reports,
)


def test_hand_bias_rmse_monthly_signed_sums_and_basis_gate():
    idx = pd.to_datetime(["1990-01-01", "1990-01-02", "1990-02-01"])
    r = pd.Series([1.0, 3.0, -1.0], index=idx)
    a = pd.Series([2.0, 2.0, -2.0], index=idx)
    m = stage_metrics(r, a, reference_basis=Basis.PLANT, actual_basis=Basis.PLANT)
    assert m["hourly_bias"] == pytest.approx(-1 / 3) and m["hourly_rmse"] == 1
    assert m["annual_reference_integral"] == 3 and m["annual_actual_integral"] == 2
    assert [v["reference_integral"] for v in m["monthly"]] == [4, -1]
    assert [v["actual_integral"] for v in m["monthly"]] == [4, -2]
    assert (
        stage_metrics(
            r, a, reference_basis=Basis.ORIENTATION_2, actual_basis=Basis.PLANT
        )["status"]
        == "unavailable"
    )
    with pytest.raises(ValueError):
        stage_metrics(
            r, a.iloc[:-1], reference_basis=Basis.PLANT, actual_basis=Basis.PLANT
        )
    factors = factor_metrics(
        pd.Series([1.0, 1.0]), pd.Series([0.5, 0.0]), pd.Series([2.0, 0.0])
    )
    assert factors["weighted_mae"] == 0.5 and factors["zero_source_rows"] == 1


@pytest.mark.parametrize(
    "annual,month,expected",
    [
        (0.0299, 0.0499, "pass"),
        (0.0301, 0, "fail"),
        (0, 0.0501, "fail"),
        (0.03, 0.05, "pass"),
        (-0.0301, 0, "fail"),
        (0, -0.0501, "fail"),
    ],
)
def test_binding_verdict_boundaries_synthetic_only(annual, month, expected):
    assert grid_verdict(annual, [month] * 12) == expected
    assert grid_verdict(annual, [month] * 11) == "unavailable"


def test_blocked_public_report_cannot_emit_energy_or_private_fields(tmp_path):
    secret = {
        "latitude_deg": 12.345,
        "customer": "Invented private token",
        "absolute_energy": 123456,
    }
    r = blocked_report(
        "P2",
        reasons=[{"public_code": "mesh_pending", "private": secret}],
        evidence=secret,
    )
    assert "energy_verdict" not in r and r["status"] == "blocked"
    public = write_reports(tmp_path, [r])
    assert public == {
        "phase": "tooling_only",
        "cases": [
            {"case": "P2", "status": "blocked", "reason_codes": ["mesh_pending"]}
        ],
    }
    for name in ["public-summary.json", "public-summary.md"]:
        assert (
            "123456" not in (tmp_path / name).read_text()
            and "latitude" not in (tmp_path / name).read_text()
        )
    with pytest.raises(ValueError):
        public_summary([{**r, "status": "pass"}])
