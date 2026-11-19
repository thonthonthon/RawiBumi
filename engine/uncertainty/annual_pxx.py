"""Annual available-AC energy exceedance (P50/P75/P90/P95), analytical Gaussian method.

A native implementation of the standalone Uncertainty Engine's U1 *Annual Analytical Pxx* v1.0 method
(`rawibumi_uncertainty.annual_analytical_v1`), which is its specification and numerical reference. The engineer
supplies every uncertainty term with its source and a correlation assumption; there are **no numerical defaults**.

    Y = μ + Σ ε_i,  ε ~ N(0, Σ),  Σ_ij = σ_i σ_j ρ_ij,  Var(Y) = 1ᵀ Σ 1
    P_xx = μ + Φ⁻¹(1 − xx/100) · √Var(Y)        for xx in 50, 75, 90, 95

A negative reported quantile is refused, never clipped. P99 is not qualified by U1 and is reported as unavailable.
The result is a model-based, assumption-based estimate, never field-validated.
"""
from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Mapping

METHOD_ID = "annual_gaussian"
METHOD_VERSION = "1.0.0"
METHOD_REFERENCE = "rawibumi_uncertainty U1 annual_analytical_v1 1.0.0 (native port)"
LEDGER_SCHEMA_VERSION = "1.0"
LEVELS = (50, 75, 90, 95)
MAX_TERMS = 64
SCOPES = ("project_persistent", "annual_weather", "intraday_operating")
PROVENANCE_TYPES = ("user_assumption", "versioned_software_catalog", "measured_or_derived")
SIGMA_UNITS = ("kwh", "fraction_of_annual_mean")
P99_UNAVAILABLE = {"status": "unavailable", "reason": "P99_NOT_QUALIFIED",
                   "message": "The Gaussian tail beyond P95 is not qualified by the U1 method."}
# U1's illustrative source taxonomy: categories and double-count guidance only, never numbers.
SOURCE_CATEGORIES = (
    ("interannual_solar_variability", "annual_weather", "solar_resource_weather",
     "Do not add resource variability twice if already included in a provider combined resource uncertainty."),
    ("solar_resource_reference_bias", "project_persistent", "solar_resource_reference",
     "Persistent source bias distinct from interannual variation; TMY does not identify it alone."),
    ("model_translation_uncertainty", "project_persistent", "physical_model",
     "Only residual model error not already captured in module/inverter component uncertainties."),
    ("module_specification_uncertainty", "project_persistent", "module_parameter",
     "Account for correlation with electrical-model calibration where applicable."),
    ("loss_assumption_uncertainty", "project_persistent", "loss_ledger",
     "Shading/soiling/availability already in mean model; sigma is uncertainty of estimate, not an extra deterministic loss."),
    ("annual_operating_availability_uncertainty", "annual_weather", "annual_availability",
     "Do not invent outage probability from unspecified operational records."),
)
LIMITATIONS = (
    "The run's annual energy is treated as the annual mean (simplified method); a single weather year is not a long-term mean.",
    "The normal additive approximation may be inappropriate for large or non-Gaussian uncertainties.",
    "P90 is the energy exceeded with 90% probability, not the worst possible annual yield.",
    "Load, import/export, BESS, hourly Pxx and multi-year lifetime outcomes are outside this method.",
)


class AnnualPxxError(ValueError):
    """A refused ledger or result: a U1 reason code, a message and the JSON path it concerns."""

    def __init__(self, code: str, message: str, path: str = ""):
        super().__init__(f"{code}: {path}: {message}" if path else f"{code}: {message}")
        self.code, self.message, self.path = code, message, path


def _fail(code: str, message: str, path: str = "") -> None:
    raise AnnualPxxError(code, message, path)


def _number(v: Any, path: str, min_value: float | None = None) -> float:
    if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v):
        _fail("INVALID_NUMBER", "Must be a finite number (not Boolean)", path)
    z = float(v)
    if min_value is not None and z < min_value:
        _fail("NEGATIVE_OR_OUT_OF_RANGE", f"Must be >= {min_value}", path)
    return z


def _text(v: Any, path: str, code: str = "MISSING_PROVENANCE") -> str:
    if not isinstance(v, str) or not v.strip():
        _fail(code, "Must be a nonempty string", path)
    if len(v) > 2000:
        _fail("TEXT_TOO_LONG", "At most 2,000 characters", path)
    return v


def _psd_checked(a: list[list[float]], *, tol: float = 1e-10) -> None:
    """U1's unpivoted semidefinite elimination on a unit-scale symmetric matrix: a materially negative eigenmode
    fails during elimination; a zero pivot requires its residual row and column to vanish."""
    n = len(a)
    m = [row[:] for row in a]
    for k in range(n):
        pivot = m[k][k]
        if pivot < -tol:
            _fail("CORRELATION_NOT_PSD", "Negative Schur pivot", f"/correlation/matrix/{k}/{k}")
        if pivot <= tol:
            if any(abs(m[i][k]) > 2 * tol for i in range(k + 1, n)):
                _fail("CORRELATION_NOT_PSD", "Zero pivot with nonzero residual cross-term", f"/correlation/matrix/{k}")
            continue
        for i in range(k + 1, n):
            for j in range(i, n):
                m[j][i] -= m[i][k] * m[j][k] / pivot
                m[i][j] = m[j][i]


def _correlation(correlation: Any, n: int) -> list[list[float]]:
    if not isinstance(correlation, Mapping):
        _fail("MISSING_CORRELATION", "Explicit correlation mode required", "/correlation")
    extra = set(correlation) - {"mode", "independence_basis", "matrix", "matrix_basis"}
    if extra:
        _fail("UNKNOWN_FIELD", f"Unknown correlation fields: {sorted(extra)}", "/correlation")
    mode, matrix = correlation.get("mode"), correlation.get("matrix")
    statement, basis = correlation.get("independence_basis"), correlation.get("matrix_basis")
    if mode == "independent_explicit":
        if matrix is not None:
            _fail("UNEXPECTED_MATRIX", "Independence mode must not include a matrix", "/correlation/matrix")
        _text(statement, "/correlation/independence_basis")
        if basis is not None:
            _fail("UNEXPECTED_MATRIX_BASIS", "No matrix basis in independence mode", "/correlation/matrix_basis")
        return [[float(i == j) for j in range(n)] for i in range(n)]
    if mode != "matrix_explicit":
        _fail("UNSUPPORTED_CORRELATION", "Use independent_explicit or matrix_explicit", "/correlation/mode")
    if statement is not None:
        _fail("UNEXPECTED_INDEPENDENCE_BASIS", "Remove independence statement for explicit matrix", "/correlation/independence_basis")
    _text(basis, "/correlation/matrix_basis")
    if not isinstance(matrix, list) or len(matrix) != n or any(not isinstance(row, list) or len(row) != n for row in matrix):
        _fail("MATRIX_SHAPE", "Correlation matrix must be n x n", "/correlation/matrix")
    m = [[_number(v, f"/correlation/matrix/{i}/{j}") for j, v in enumerate(row)] for i, row in enumerate(matrix)]
    for i in range(n):
        if not math.isclose(m[i][i], 1.0, abs_tol=1e-10, rel_tol=0):
            _fail("CORRELATION_DIAGONAL", "Diagonal must be one", f"/correlation/matrix/{i}/{i}")
        for j in range(n):
            if abs(m[i][j]) > 1 + 1e-12:
                _fail("CORRELATION_RANGE", "Correlation coefficient outside [-1,1]", f"/correlation/matrix/{i}/{j}")
            if not math.isclose(m[i][j], m[j][i], abs_tol=1e-10, rel_tol=0):
                _fail("CORRELATION_NOT_SYMMETRIC", "Correlation matrix must be symmetric", f"/correlation/matrix/{i}/{j}")
    _psd_checked(m)
    return m


def validate_ledger(ledger: Any) -> dict[str, Any]:
    """Check a project uncertainty-assumption ledger on its own (no annual mean needed); return it unchanged."""
    if not isinstance(ledger, Mapping):
        _fail("EXPECTED_OBJECT", "Expected a ledger object")
    extra = set(ledger) - {"schema_version", "terms", "correlation"}
    if extra:
        _fail("UNKNOWN_FIELD", f"Unknown ledger fields: {sorted(extra)}")
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        _fail("SCHEMA_VERSION", f"Ledger schema_version must be {LEDGER_SCHEMA_VERSION}", "/schema_version")
    terms = ledger.get("terms")
    if not isinstance(terms, list) or not 1 <= len(terms) <= MAX_TERMS:
        _fail("SOURCE_COUNT", "Provide 1–64 explicit uncertainty terms; no inferred defaults", "/terms")
    keys: set[str] = set()
    groups: set[str] = set()
    allowed = {"source_key", "double_count_group", "scope", "sigma_value", "sigma_unit", "provenance_type", "source_ref", "justification"}
    for i, term in enumerate(terms):
        p = f"/terms/{i}"
        if not isinstance(term, Mapping):
            _fail("INVALID_SOURCE", "Each term must be an object", p)
        if set(term) - allowed:
            _fail("UNKNOWN_FIELD", f"Unknown term fields: {sorted(set(term) - allowed)}", p)
        key = _text(term.get("source_key"), p + "/source_key")
        group = _text(term.get("double_count_group"), p + "/double_count_group")
        if key in keys:
            _fail("DUPLICATE_SOURCE", "Source repeated", p + "/source_key")
        if group in groups:
            _fail("DOUBLE_COUNT_GROUP", "Potentially overlapping uncertainty sources; explicitly partition before running", p + "/double_count_group")
        keys.add(key)
        groups.add(group)
        if term.get("scope") not in SCOPES:
            _fail("INVALID_SCOPE", "Unrecognized uncertainty scope", p + "/scope")
        if term.get("provenance_type") not in PROVENANCE_TYPES:
            _fail("SOURCE_PROVENANCE", "Explicit provenance required", p + "/provenance_type")
        _text(term.get("source_ref"), p + "/source_ref")
        _text(term.get("justification"), p + "/justification")
        _number(term.get("sigma_value"), p + "/sigma_value", 0)
        if term.get("sigma_unit") not in SIGMA_UNITS:
            _fail("UNSUPPORTED_SIGMA_UNIT", "Use kwh or fraction_of_annual_mean", p + "/sigma_unit")
    _correlation(ledger.get("correlation"), len(terms))
    return dict(ledger)


def annual_pxx(annual_mean_kwh: float, ledger: Mapping[str, Any]) -> dict[str, Any]:
    """P50/P75/P90/P95 of one operating year's available AC energy (kWh), conditional on the ledger."""
    mu = _number(annual_mean_kwh, "/annual_mean_kwh", 0)
    validate_ledger(ledger)
    terms = ledger["terms"]
    sigma, out_terms = [], []
    for i, term in enumerate(terms):
        value = float(term["sigma_value"])
        sig = value if term["sigma_unit"] == "kwh" else value * mu
        if not math.isfinite(sig):
            _fail("SIGMA_OVERFLOW", "Converted sigma is not finite", f"/terms/{i}/sigma_value")
        sigma.append(sig)
        out_terms.append({"source_key": term["source_key"], "scope": term["scope"], "double_count_group": term["double_count_group"],
                          "provenance_type": term["provenance_type"], "source_ref": term["source_ref"], "sigma_kwh": sig})
    correlation = ledger["correlation"]
    corr = _correlation(correlation, len(terms))
    cov = [[sigma[i] * sigma[j] * corr[i][j] for j in range(len(sigma))] for i in range(len(sigma))]
    variance = math.fsum(math.fsum(row) for row in cov)
    if not math.isfinite(variance):
        _fail("VARIANCE_OVERFLOW", "Variance is not finite")
    diagonal = math.fsum(cov[i][i] for i in range(len(sigma)))
    # Exact PSD implies a nonnegative variance; tolerate cancellation error at scale.
    if variance < -1e-10 * max(1, diagonal):
        _fail("NEGATIVE_VARIANCE", "Combined uncertainty variance is negative", "/correlation/matrix")
    combined = math.sqrt(max(0.0, variance))
    quantiles = {}
    for level in LEVELS:
        z = NormalDist().inv_cdf(1 - level / 100)
        value = mu + z * combined if combined else mu
        if not math.isfinite(value):
            _fail("QUANTILE_OVERFLOW", "Quantile not finite")
        if value < 0:
            _fail("NEGATIVE_GAUSSIAN_TAIL", "Gaussian yield quantile is negative; no silent zero-clipping. Revise the assumptions.", "/terms")
        quantiles[f"P{level}"] = {"exceedance_probability": level / 100, "lower_cdf_quantile": 1 - level / 100,
                                  "normal_z": z, "energy_kwh": value}
    for term, allocation in zip(out_terms, (math.fsum(row) for row in cov)):
        term["signed_covariance_allocation_kwh2"] = allocation
    mode = correlation["mode"]
    return {
        "method_id": METHOD_ID, "method_version": METHOD_VERSION, "method_reference": METHOD_REFERENCE,
        "metric_boundary": "pv_ac_available", "unit": "kwh", "time_horizon": "one_operating_year", "statistic": "annual_exceedance",
        "annual_mean_kwh": mu, "annual_sigma_kwh": combined, "annual_sigma_fraction": combined / mu if mu else None,
        "variance_kwh2": max(0.0, variance), "variance_diagonal_kwh2": diagonal,
        "variance_correlation_contribution_kwh2": variance - diagonal,
        "gaussian_negative_support_probability": NormalDist(mu, combined).cdf(0) if combined else 0.0,
        "positive_support_policy": "reject_negative_reported_pxx_no_silent_clipping",
        "correlation_mode": mode,
        "correlation_basis": correlation["matrix_basis"] if mode == "matrix_explicit" else correlation["independence_basis"],
        "correlation_matrix": corr, "covariance_matrix_kwh2": cov,
        "allocation_note": "Signed covariance allocations can be negative; they are not physical losses or variance shares.",
        "terms": out_terms, "quantiles": quantiles, "P99": dict(P99_UNAVAILABLE),
        "calculation_evidence": "assumption_based", "publication_status": "model_based_estimate",
        "limitations": list(LIMITATIONS),
    }
