"""UNC1: annual P50–P95 (U1 analytical Gaussian, native), the project ledger, the route and the export."""

from copy import deepcopy
from io import BytesIO
import json
import math
from zipfile import ZipFile

import pandas as pd
import pytest

from apps.api.history import design_fingerprint, validate_restored_bundle
from engine.uncertainty.annual_pxx import AnnualPxxError, annual_pxx, validate_ledger
from tests.unit.test_rb_fix_s10_weather_window import payload
from tests.unit.test_rb_fix_s2_honest_preflight import Project

# Reference results of the standalone U1 v1.0 package (RawiBumi_U1_Annual_Analytical_Pxx_v1.0_2026-10-15.zip, SHA-256
# ed6097c2228381bb112e597614f47457143a2e800365a699b2bc56eda36a7fa9), examples/*.result.json. Synthetic test values.
U1_TERMS = [
    {"source_key": "interannual_weather", "double_count_group": "resource_weather", "scope": "annual_weather", "provenance_type": "user_assumption",
     "source_ref": "illustrative_synthetic_fixture_only", "justification": "Example 4% annual weather variation", "sigma_value": 0.04, "sigma_unit": "fraction_of_annual_mean"},
    {"source_key": "persistent_resource_model", "double_count_group": "resource_reference_bias", "scope": "project_persistent", "provenance_type": "user_assumption",
     "source_ref": "illustrative_synthetic_fixture_only", "justification": "Example 3% persistent resource bias", "sigma_value": 0.03, "sigma_unit": "fraction_of_annual_mean"},
]
U1_REFERENCE = {
    "independent": ({"P50": 450000.0, "P75": 434823.9806205882, "P90": 421165.08977524645, "P95": 412990.7933935919}, 22500.0, [324000000.0, 182250000.0]),
    "correlated": ({"P50": 450000.0, "P75": 430948.20152358443, "P90": 413800.9885890888, "P95": 403539.07184687303}, 28246.23868765539, [469800000.0, 328050000.0]),
    "explicit_zero": ({"P50": 450000.0, "P75": 450000.0, "P90": 450000.0, "P95": 450000.0}, 0.0, [0.0]),
}
INDEPENDENT = {"mode": "independent_explicit", "independence_basis": "Synthetic fixture assumption of independence"}


def ledger(terms=None, correlation=None):
    return {"schema_version": "1.0", "terms": deepcopy(U1_TERMS if terms is None else terms), "correlation": deepcopy(correlation or INDEPENDENT)}


# --- the kernel against U1 ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("case", ["independent", "correlated", "explicit_zero"])
def test_kernel_reproduces_the_u1_reference_exactly(case):
    if case == "correlated":
        book = ledger(correlation={"mode": "matrix_explicit", "matrix": [[1, 0.6], [0.6, 1]], "matrix_basis": "Synthetic demonstration only"})
    elif case == "explicit_zero":
        book = ledger(terms=[dict(U1_TERMS[0], sigma_value=0.0)])
    else:
        book = ledger()
    quantiles, sigma, allocations = U1_REFERENCE[case]
    result = annual_pxx(450000.0, book)
    assert {k: v["energy_kwh"] for k, v in result["quantiles"].items()} == quantiles
    assert result["annual_sigma_kwh"] == sigma
    assert [t["signed_covariance_allocation_kwh2"] for t in result["terms"]] == allocations
    assert result["gaussian_negative_support_probability"] == 0.0
    assert result["P99"]["status"] == "unavailable" and result["P99"]["reason"] == "P99_NOT_QUALIFIED"
    assert (result["calculation_evidence"], result["publication_status"]) == ("assumption_based", "model_based_estimate")


def test_kwh_and_fraction_sigmas_are_equivalent():
    as_kwh = ledger(terms=[dict(t, sigma_value=t["sigma_value"] * 450000.0, sigma_unit="kwh") for t in U1_TERMS])
    assert annual_pxx(450000.0, as_kwh)["quantiles"] == annual_pxx(450000.0, ledger())["quantiles"]


@pytest.mark.parametrize("book, code", [
    (ledger(terms=[U1_TERMS[0], dict(U1_TERMS[1], source_key="interannual_weather")]), "DUPLICATE_SOURCE"),
    (ledger(terms=[U1_TERMS[0], dict(U1_TERMS[1], double_count_group="resource_weather")]), "DOUBLE_COUNT_GROUP"),
    (ledger(terms=[dict(U1_TERMS[0], sigma_value=-0.01)]), "NEGATIVE_OR_OUT_OF_RANGE"),
    (ledger(terms=[dict(U1_TERMS[0], sigma_value=float("nan"))]), "INVALID_NUMBER"),
    (ledger(terms=[dict(U1_TERMS[0], sigma_value=True)]), "INVALID_NUMBER"),
    (ledger(terms=[dict(U1_TERMS[0], sigma_unit="percent")]), "UNSUPPORTED_SIGMA_UNIT"),
    (ledger(terms=[dict(U1_TERMS[0], justification="  ")]), "MISSING_PROVENANCE"),
    (ledger(terms=[dict(U1_TERMS[0], scope="lifetime")]), "INVALID_SCOPE"),
    (ledger(terms=[dict(U1_TERMS[0], provenance_type="guess")]), "SOURCE_PROVENANCE"),
    (ledger(terms=[dict(U1_TERMS[0], distribution="normal")]), "UNKNOWN_FIELD"),
    (ledger(terms=[]), "SOURCE_COUNT"),
    ({**ledger(), "schema_version": "2.0"}, "SCHEMA_VERSION"),
    (ledger(correlation={"mode": "independent_explicit"}), "MISSING_PROVENANCE"),
    (ledger(correlation={"mode": "independent_explicit", "independence_basis": "x", "matrix": [[1, 0], [0, 1]]}), "UNEXPECTED_MATRIX"),
    (ledger(correlation={"mode": "matrix_explicit", "matrix": [[1, 0.5]], "matrix_basis": "x"}), "MATRIX_SHAPE"),
    (ledger(correlation={"mode": "matrix_explicit", "matrix": [[1, 0.5], [0.4, 1]], "matrix_basis": "x"}), "CORRELATION_NOT_SYMMETRIC"),
    (ledger(correlation={"mode": "matrix_explicit", "matrix": [[0.9, 0.5], [0.5, 1]], "matrix_basis": "x"}), "CORRELATION_DIAGONAL"),
    (ledger(correlation={"mode": "matrix_explicit", "matrix": [[1, 1.2], [1.2, 1]], "matrix_basis": "x"}), "CORRELATION_RANGE"),
    (ledger(correlation={"mode": "copula"}), "UNSUPPORTED_CORRELATION"),
])
def test_kernel_refusals(book, code):
    with pytest.raises(AnnualPxxError) as caught:
        annual_pxx(450000.0, book)
    assert caught.value.code == code


def test_non_psd_matrix_is_refused_and_a_singular_psd_one_is_accepted():
    third = dict(U1_TERMS[0], source_key="third", double_count_group="third_group")
    terms = [*U1_TERMS, third]
    bad = ledger(terms=terms, correlation={"mode": "matrix_explicit", "matrix": [[1, 0.9, -0.9], [0.9, 1, 0.9], [-0.9, 0.9, 1]], "matrix_basis": "x"})
    with pytest.raises(AnnualPxxError) as caught:
        annual_pxx(450000.0, bad)
    assert caught.value.code == "CORRELATION_NOT_PSD"
    perfect = ledger(correlation={"mode": "matrix_explicit", "matrix": [[1, 1], [1, 1]], "matrix_basis": "fully correlated"})
    assert annual_pxx(450000.0, perfect)["annual_sigma_kwh"] == pytest.approx(0.07 * 450000.0)


def test_a_negative_gaussian_tail_is_refused_not_clipped():
    with pytest.raises(AnnualPxxError) as caught:
        annual_pxx(450000.0, ledger(terms=[dict(U1_TERMS[0], sigma_value=0.7)]))
    assert caught.value.code == "NEGATIVE_GAUSSIAN_TAIL"
    near = annual_pxx(450000.0, ledger(terms=[dict(U1_TERMS[0], sigma_value=0.5)]))
    assert near["gaussian_negative_support_probability"] == pytest.approx(0.0227501, rel=1e-5)  # Φ(−2)


# --- the project, the route and the export --------------------------------------------------------------------------

def clear_sky_year():
    """Entirely fictional full local year 2023 at the test site: a pvlib Ineichen clear sky, not ERA5."""
    import pvlib
    value = payload("2022-12-31T00:00Z", 8760 + 48)
    stamps = pd.to_datetime(value["hourly"]["time"], unit="s", utc=True)
    # Open-Meteo radiation is the mean of the preceding hour: a clear sky at mid-interval.
    sky = pvlib.location.Location(-6.2, 106.8, altitude=25).get_clearsky(stamps - pd.Timedelta(minutes=30), model="ineichen")
    for column, key in (("ghi", "shortwave_radiation"), ("dni", "direct_normal_irradiance"), ("dhi", "diffuse_radiation")):
        value["hourly"][key] = sky[column].round(3).tolist()
    value["_opensimpv_fixture_note"] = "Entirely fictional UNC1 test year: pvlib Ineichen clear sky; not ERA5."
    return json.dumps(value).encode()


@pytest.fixture(scope="module")
def annual(tmp_path_factory):
    p = Project(tmp_path_factory.mktemp("unc1"), 20, weather=False, strings=True)
    p.study.acquire_weather(p.pid, source_id="open_meteo_archive_era5", start_date="2023-01-01", end_date="2023-12-31", raw_response=clear_sky_year())
    run = p.client.post(p.url + "/simulate", json={})
    assert run.status_code == 200, run.text
    assert run.json()["summary_result"]["annual_energy_wh"] is not None
    return p, run.json()


def project_ledger():
    return ledger(terms=[
        {"source_key": "interannual_solar_variability", "double_count_group": "solar_resource_weather", "scope": "annual_weather", "provenance_type": "user_assumption",
         "source_ref": "UNC1 test", "justification": "test value only", "sigma_value": 0.04, "sigma_unit": "fraction_of_annual_mean"},
        {"source_key": "solar_resource_reference_bias", "double_count_group": "solar_resource_reference", "scope": "project_persistent", "provenance_type": "user_assumption",
         "source_ref": "UNC1 test", "justification": "test value only", "sigma_value": 0.03, "sigma_unit": "fraction_of_annual_mean"},
    ], correlation={"mode": "independent_explicit", "independence_basis": "declared independent for the test"})


def put(p, book):
    return p.client.put(p.url + "/uncertainty-assumptions", json={"ledger": book})


def pxx(p, run_id):
    response = p.client.get(p.url + f"/runs/{run_id}/annual-pxx")
    assert response.status_code == 200, response.text
    return response.json()


def test_route_without_assumptions_says_so(annual):
    p, run = annual
    put(p, None)
    view = pxx(p, run["simulation_run_id"])
    assert view["status"] == "unavailable" and [r["code"] for r in view["reasons"]] == ["NO_ASSUMPTIONS"]
    assert view["result"] is None and view["P99"]["reason"] == "P99_NOT_QUALIFIED"
    assert view["basis"]["annual_mean_basis"] == "historical_year_as_mean" and view["basis"]["weather_calendar_type"] == "gregorian"


def test_ledger_is_undoable_outside_the_fingerprint_and_gives_pxx(annual):
    p, run = annual
    put(p, None)
    before = p.bundle()
    response = put(p, project_ledger())
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["history"]["past"][-1]["label"] == "Edit uncertainty assumptions"
    after = p.bundle()
    assert after["uncertainty_assumptions"] == project_ledger()
    assert design_fingerprint(after) == design_fingerprint(before)
    assert after["project"]["project_revision"] == before["project"]["project_revision"]
    validate_restored_bundle(after)
    result = pxx(p, run["simulation_run_id"])
    mu = run["summary_result"]["annual_energy_wh"] / 1000
    assert result["status"] == "available" and result["reasons"] == []
    assert result["result"]["annual_mean_kwh"] == mu
    assert result["result"]["quantiles"]["P90"]["energy_kwh"] == pytest.approx(mu * (1 - 1.2815515655446008 * math.hypot(0.04, 0.03)))
    from engine.simulation.artifacts import canonical_json_bytes
    from hashlib import sha256
    assert result["ledger_sha256"] == sha256(canonical_json_bytes(project_ledger())).hexdigest()
    entry = view["history"]["past"][-1]["entry_id"]
    undone = p.client.post(p.url + "/undo", json={"expected_project_revision_id": after["project"]["project_revision"]["project_revision_id"], "expected_entry_id": entry})
    assert undone.status_code == 200, undone.text
    assert "uncertainty_assumptions" not in undone.json()["bundle"]


def test_invalid_ledgers_are_refused_with_the_u1_code_and_nothing_is_written(annual):
    p, _ = annual
    put(p, None)
    before = p.path.read_bytes()
    bad = project_ledger()
    bad["terms"][1]["double_count_group"] = bad["terms"][0]["double_count_group"]
    response = put(p, bad)
    assert response.status_code == 422 and "DOUBLE_COUNT_GROUP: /terms/1/double_count_group" in response.text
    assert p.client.put(p.url + "/uncertainty-assumptions", json={"ledger": project_ledger(), "extra": 1}).status_code == 422
    assert p.path.read_bytes() == before


def test_a_negative_tail_or_a_partial_period_run_is_unavailable_with_the_reason(annual, tmp_path):
    p, run = annual
    put(p, ledger(terms=[dict(project_ledger()["terms"][0], sigma_value=0.7)]))
    view = pxx(p, run["simulation_run_id"])
    assert view["status"] == "unavailable" and view["reasons"][0]["code"] == "NEGATIVE_GAUSSIAN_TAIL"
    day = Project(tmp_path, 20, weather=True, strings=True)
    short = day.client.post(day.url + "/simulate", json={}).json()
    codes = [r["code"] for r in pxx(day, short["simulation_run_id"])["reasons"]]
    assert codes == ["RUN_NOT_ANNUAL", "NO_ASSUMPTIONS"]
    assert day.client.get(day.url + "/runs/run-404/annual-pxx").status_code == 422


def test_a_typical_year_weather_labels_its_basis(annual, monkeypatch):
    p, run = annual
    put(p, project_ledger())
    real = p.study.weather.load

    class Typical:
        def __init__(self, inner):
            self.dataset = {**inner.dataset, "calendar_type": "typical_year"}

    monkeypatch.setattr(p.study.weather, "load", lambda project_id, revision: Typical(real(project_id, revision)))
    assert pxx(p, run["simulation_run_id"])["basis"]["annual_mean_basis"] == "typical_year_as_mean"


def test_the_deliverable_carries_annual_pxx_only_with_a_ledger(annual):
    p, run = annual
    body = {"format": "csv", "resolution": "hourly", "level": "project", "columns": ["pcc_power_w"], "deliverable": True}
    put(p, None)
    plain = ZipFile(BytesIO(p.client.post(p.url + f"/runs/{run['simulation_run_id']}/exports", json=body).content))
    assert "annual-pxx.json" not in plain.namelist()
    assert "annual_pxx_status" not in json.loads(plain.read("export-manifest.json"))["deliverable"]
    put(p, project_ledger())
    archive = ZipFile(BytesIO(p.client.post(p.url + f"/runs/{run['simulation_run_id']}/exports", json=body).content))
    assert archive.namelist()[-2:] == ["annual-pxx.json", "export-manifest.json"]
    shipped = json.loads(archive.read("annual-pxx.json"))
    assert shipped == pxx(p, run["simulation_run_id"])
    manifest = json.loads(archive.read("export-manifest.json"))
    assert manifest["deliverable"]["annual_pxx_status"] == "available"
    assert any(f["path"] == "annual-pxx.json" for f in manifest["files"])


def test_validate_ledger_returns_it_unchanged():
    book = project_ledger()
    assert validate_ledger(book) == book
