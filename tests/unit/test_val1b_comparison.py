"""Synthetic basis, attribution, verdict and privacy oracles."""

import json
import pandas as pd
import pytest

from validation.pvsyst_benchmark.reference import Basis, basis_of
from validation.pvsyst_benchmark.headline_comparison import (
    column_register, qualified_metrics, perez_diffuse_attribution, public_summary,
)


def test_reader_corrections_and_strict_case_register():
    assert basis_of("AngInc") == Basis.ORIENTATION_1
    assert basis_of("FIAMBm") == Basis.ORIENTATION_2
    assert basis_of("FIAMAlb") == Basis.UNAVAILABLE
    assert basis_of("CircEff", proven_bases={}) == Basis.UNAVAILABLE
    assert basis_of("GlobIAM", proven_bases={"GlobIAM": Basis.PLANT}) == Basis.PLANT


def test_only_unique_proved_columns_are_registered():
    record = column_register(["AngInc", "GlobIAM", "DifITrp", "missing", "FIAMAlb"], {
        "AngInc": {"supported": ["orientation_1"], "proof": ["independent geometry"]},
        "GlobIAM": {"supported": ["plant"]},
        "DifITrp": {"supported": ["orientation_1", "orientation_2"], "proof": ["same tilt"]},
        "FIAMAlb": {"supported": ["orientation_2"], "proof": ["invalid raw factor"]},
    })
    assert record["AngInc"]["basis"] == "orientation_1"
    assert all(record[c]["status"] == "unavailable" for c in record if c != "AngInc")


def test_unavailable_and_cross_orientation_comparisons_fail_closed():
    s = pd.Series([1., 2., 3.], index=pd.date_range("1990-01-01", periods=3, freq="h"))
    records = column_register(["beam"], {"beam": {"supported": ["orientation_2"], "proof": ["geometry"]}})
    assert qualified_metrics(s, s, column="beam", register=records, actual_basis=Basis.ORIENTATION_1)["status"] == "unavailable"
    assert qualified_metrics(s, s, column="unknown", register=records, actual_basis=Basis.PLANT)["status"] == "unavailable"
    assert qualified_metrics(s, s, column="beam", register=records, actual_basis=Basis.ORIENTATION_2)["hourly_rmse"] == 0


def test_a6_retains_the_failed_historical_sum_and_requires_both_conditions():
    result = perez_diffuse_attribution(.0004, .00038)
    assert result["accepted"]
    assert result["superseded_A5"]["status"] == "over-conservative, failed"
    assert not perez_diffuse_attribution(.0006, .00059)["accepted"]
    assert not perez_diffuse_attribution(.0004, -.0004)["accepted"]
    assert not perez_diffuse_attribution(.0005, .0004)["accepted"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_nonfinite_diagnostics_are_refused(bad):
    with pytest.raises(ValueError):
        perez_diffuse_attribution(bad, .0)


def test_public_output_is_allowlisted_and_signed_verdict_uses_all_months():
    result = public_summary(label="P2", annual=-.01, monthly=[.01]*11+[-.049], runtime_seconds=1.)
    assert result["energy_verdict"] == "pass"
    assert result["worst_month_relative_deviation"] == -.049
    assert set(result) == {"label", "energy_verdict", "annual_relative_deviation", "worst_month_relative_deviation", "runtime_seconds"}
    assert "kwh" not in json.dumps(result).lower()
    assert public_summary(label="P3", annual=.01, monthly=[0.]*11+[.051], runtime_seconds=1.)["energy_verdict"] == "fail"
    with pytest.raises(ValueError):
        public_summary(label="private/source/path", annual=0., monthly=[0.]*12, runtime_seconds=1.)
