/**
 * DEMO MODE ONLY: the engine's UNC1 annual-Pxx rules (engine/uncertainty/annual_pxx.py, a native port of the
 * Uncertainty Engine's U1 analytical method) for the in-browser demo. The engine is authoritative; screens never
 * import this file. Same refusals, reason codes and z values; Φ for the negative-support probability uses an
 * erf approximation (|error| < 1.5e-7), adequate for a stamped demo.
 */
import type { AnnualPxxView, UncertaintyLedger } from "../types";

const Z = { P50: 0, P75: -0.6744897501960817, P90: -1.2815515655446008, P95: -1.6448536269514715 } as const;
const P99 = { status: "unavailable" as const, reason: "P99_NOT_QUALIFIED", message: "The Gaussian tail beyond P95 is not qualified by the U1 method." };

export class DemoPxxError extends Error {
  constructor(public readonly code: string, message: string, public readonly path = "") {
    super(path ? `${code}: ${path}: ${message}` : `${code}: ${message}`);
  }
}
const fail = (code: string, message: string, path = ""): never => { throw new DemoPxxError(code, message, path); };
const text = (v: unknown, path: string) => (typeof v === "string" && v.trim() ? v : fail("MISSING_PROVENANCE", "Must be a nonempty string", path));
const finite = (v: unknown, path: string) => (typeof v === "number" && Number.isFinite(v) ? v : fail("INVALID_NUMBER", "Must be a finite number (not Boolean)", path));

function erf(x: number) {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? y : -y;
}

function correlation(ledger: UncertaintyLedger, n: number): number[][] {
  const c = ledger.correlation;
  if (c.mode === "independent_explicit") {
    text(c.independence_basis, "/correlation/independence_basis");
    return Array.from({ length: n }, (_, i) => Array.from({ length: n }, (_, j) => (i === j ? 1 : 0)));
  }
  if (c.mode !== "matrix_explicit") return fail("UNSUPPORTED_CORRELATION", "Use independent_explicit or matrix_explicit", "/correlation/mode");
  text(c.matrix_basis, "/correlation/matrix_basis");
  const m = c.matrix;
  if (!Array.isArray(m) || m.length !== n || m.some((row) => !Array.isArray(row) || row.length !== n)) fail("MATRIX_SHAPE", "Correlation matrix must be n x n", "/correlation/matrix");
  m.forEach((row, i) => row.forEach((v, j) => {
    finite(v, `/correlation/matrix/${i}/${j}`);
    if (i === j && Math.abs(v - 1) > 1e-10) fail("CORRELATION_DIAGONAL", "Diagonal must be one", `/correlation/matrix/${i}/${i}`);
    if (Math.abs(v) > 1 + 1e-12) fail("CORRELATION_RANGE", "Correlation coefficient outside [-1,1]", `/correlation/matrix/${i}/${j}`);
    if (Math.abs(v - m[j][i]) > 1e-10) fail("CORRELATION_NOT_SYMMETRIC", "Correlation matrix must be symmetric", `/correlation/matrix/${i}/${j}`);
  }));
  // U1's unpivoted semidefinite elimination.
  const a = m.map((row) => [...row]);
  for (let k = 0; k < n; k++) {
    const pivot = a[k][k];
    if (pivot < -1e-10) fail("CORRELATION_NOT_PSD", "Negative Schur pivot", `/correlation/matrix/${k}/${k}`);
    if (pivot <= 1e-10) {
      if (a.slice(k + 1).some((row) => Math.abs(row[k]) > 2e-10)) fail("CORRELATION_NOT_PSD", "Zero pivot with nonzero residual cross-term", `/correlation/matrix/${k}`);
      continue;
    }
    for (let i = k + 1; i < n; i++) for (let j = i; j < n; j++) { a[j][i] -= (a[i][k] * a[j][k]) / pivot; a[i][j] = a[j][i]; }
  }
  return m;
}

/** The ledger's checks, as the engine makes them on save. */
export function validateDemoLedger(ledger: UncertaintyLedger) {
  if (ledger.schema_version !== "1.0") fail("SCHEMA_VERSION", "Ledger schema_version must be 1.0", "/schema_version");
  if (!Array.isArray(ledger.terms) || ledger.terms.length < 1 || ledger.terms.length > 64) fail("SOURCE_COUNT", "Provide 1–64 explicit uncertainty terms; no inferred defaults", "/terms");
  const keys = new Set<string>(), groups = new Set<string>();
  ledger.terms.forEach((t, i) => {
    const p = `/terms/${i}`;
    const key = text(t.source_key, `${p}/source_key`), group = text(t.double_count_group, `${p}/double_count_group`);
    if (keys.has(key)) fail("DUPLICATE_SOURCE", "Source repeated", `${p}/source_key`);
    if (groups.has(group)) fail("DOUBLE_COUNT_GROUP", "Potentially overlapping uncertainty sources; explicitly partition before running", `${p}/double_count_group`);
    keys.add(key); groups.add(group);
    if (!["project_persistent", "annual_weather", "intraday_operating"].includes(t.scope)) fail("INVALID_SCOPE", "Unrecognized uncertainty scope", `${p}/scope`);
    if (!["user_assumption", "versioned_software_catalog", "measured_or_derived"].includes(t.provenance_type)) fail("SOURCE_PROVENANCE", "Explicit provenance required", `${p}/provenance_type`);
    text(t.source_ref, `${p}/source_ref`); text(t.justification, `${p}/justification`);
    if (finite(t.sigma_value, `${p}/sigma_value`) < 0) fail("NEGATIVE_OR_OUT_OF_RANGE", "Must be >= 0", `${p}/sigma_value`);
    if (t.sigma_unit !== "kwh" && t.sigma_unit !== "fraction_of_annual_mean") fail("UNSUPPORTED_SIGMA_UNIT", "Use kwh or fraction_of_annual_mean", `${p}/sigma_unit`);
  });
  correlation(ledger, ledger.terms.length);
}

/** The demo's annual-Pxx view for a run (mirrors GET /runs/{id}/annual-pxx). */
export function demoAnnualPxx(runId: string, annualEnergyWh: number | null | undefined, ledger: UncertaintyLedger | undefined): AnnualPxxView {
  const reasons: AnnualPxxView["reasons"] = [];
  if (annualEnergyWh === null || annualEnergyWh === undefined) reasons.push({ code: "RUN_NOT_ANNUAL", message: "Annual Pxx needs a run over one complete year (8,760 or 8,784 hours)." });
  if (!ledger) reasons.push({ code: "NO_ASSUMPTIONS", message: "Enter at least one uncertainty term with its value, source and justification." });
  const view: AnnualPxxView = {
    schema_name: "AnnualPxxView", run_id: runId, status: "unavailable", reasons,
    basis: { annual_mean_basis: "historical_year_as_mean", weather_calendar_type: null, mean_source: "the run's annual PCC energy (summary annual_energy_wh), treated as the annual mean", mean_source_sha256: null },
    ledger_sha256: null, result: null, P99: { ...P99 },
    label: { calculation_evidence: "assumption_based", publication_status: "model_based_estimate" }
  };
  if (reasons.length || !ledger || annualEnergyWh == null) return view;
  try {
    validateDemoLedger(ledger);
    const mu = annualEnergyWh / 1000;
    const sigma = ledger.terms.map((t) => (t.sigma_unit === "kwh" ? t.sigma_value : t.sigma_value * mu));
    const corr = correlation(ledger, sigma.length);
    const cov = sigma.map((si, i) => sigma.map((sj, j) => si * sj * corr[i][j]));
    const variance = cov.flat().reduce((a, b) => a + b, 0);
    const s = Math.sqrt(Math.max(0, variance));
    const quantiles = Object.fromEntries(Object.entries(Z).map(([k, z]) => {
      const energy = s ? mu + z * s : mu;
      if (energy < 0) fail("NEGATIVE_GAUSSIAN_TAIL", "Gaussian yield quantile is negative; no silent zero-clipping. Revise the assumptions.", "/terms");
      return [k, { exceedance_probability: Number(k.slice(1)) / 100, normal_z: z, energy_kwh: energy }];
    })) as NonNullable<AnnualPxxView["result"]>["quantiles"];
    view.result = {
      annual_mean_kwh: mu, annual_sigma_kwh: s, annual_sigma_fraction: mu ? s / mu : null,
      gaussian_negative_support_probability: s ? 0.5 * (1 + erf((0 - mu) / (s * Math.SQRT2))) : 0,
      correlation_mode: ledger.correlation.mode,
      correlation_basis: ledger.correlation.mode === "matrix_explicit" ? ledger.correlation.matrix_basis : ledger.correlation.independence_basis,
      quantiles,
      terms: ledger.terms.map((t, i) => ({ source_key: t.source_key, sigma_kwh: sigma[i], signed_covariance_allocation_kwh2: cov[i].reduce((a, b) => a + b, 0) })),
      limitations: ["The run's annual energy is treated as the annual mean (simplified method); a single weather year is not a long-term mean.",
        "The normal additive approximation may be inappropriate for large or non-Gaussian uncertainties.",
        "P90 is the energy exceeded with 90% probability, not the worst possible annual yield.",
        "Load, import/export, BESS, hourly Pxx and multi-year lifetime outcomes are outside this method."]
    };
    view.status = "available";
  } catch (e) {
    if (!(e instanceof DemoPxxError)) throw e;
    view.reasons = [{ code: e.code, message: e.message.split(": ").slice(-1)[0], path: e.path }];
  }
  return view;
}
