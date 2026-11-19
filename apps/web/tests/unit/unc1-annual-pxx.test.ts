import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../src/api";
import { demoAnnualPxx } from "../../src/demo/annualPxx";
import { CATEGORIES, draftOf, emptyTerm, ledgerOf } from "../../src/results/AnnualPxx";
import type { UncertaintyLedger } from "../../src/types";

// UNC1: the ledger editor's model, the demo mirror of the engine's U1 rules, and the requests.
const terms = (): UncertaintyLedger["terms"] => [
  { source_key: "interannual_weather", double_count_group: "resource_weather", scope: "annual_weather", provenance_type: "user_assumption", source_ref: "fixture", justification: "test", sigma_value: 0.04, sigma_unit: "fraction_of_annual_mean" },
  { source_key: "persistent_resource_model", double_count_group: "resource_reference_bias", scope: "project_persistent", provenance_type: "user_assumption", source_ref: "fixture", justification: "test", sigma_value: 0.03, sigma_unit: "fraction_of_annual_mean" },
];
const independent = (): UncertaintyLedger => ({ schema_version: "1.0", terms: terms(), correlation: { mode: "independent_explicit", independence_basis: "fixture" } });

describe("the demo mirrors the engine's U1 method", () => {
  it("reproduces the U1 reference quantiles (independent and correlated)", () => {
    const a = demoAnnualPxx("r", 450_000_000, independent());
    expect(a.status).toBe("available");
    expect(a.result!.quantiles.P75.energy_kwh).toBeCloseTo(434823.9806205882, 6);
    expect(a.result!.quantiles.P95.energy_kwh).toBeCloseTo(412990.7933935919, 6);
    const c = demoAnnualPxx("r", 450_000_000, { ...independent(), correlation: { mode: "matrix_explicit", matrix: [[1, 0.6], [0.6, 1]], matrix_basis: "fixture" } });
    expect(c.result!.annual_sigma_kwh).toBeCloseTo(28246.23868765539, 6);
    expect(c.result!.quantiles.P90.energy_kwh).toBeCloseTo(413800.9885890888, 6);
    expect(a.P99.reason).toBe("P99_NOT_QUALIFIED");
  });

  it("gives reasons instead of numbers", () => {
    expect(demoAnnualPxx("r", null, undefined).reasons.map((r) => r.code)).toEqual(["RUN_NOT_ANNUAL", "NO_ASSUMPTIONS"]);
    const tail = demoAnnualPxx("r", 450_000_000, { ...independent(), terms: [{ ...terms()[0], sigma_value: 0.7 }] });
    expect([tail.status, tail.reasons[0].code]).toEqual(["unavailable", "NEGATIVE_GAUSSIAN_TAIL"]);
    const group = demoAnnualPxx("r", 450_000_000, { ...independent(), terms: [terms()[0], { ...terms()[1], double_count_group: "resource_weather" }] });
    expect(group.reasons[0].code).toBe("DOUBLE_COUNT_GROUP");
    const psd = demoAnnualPxx("r", 450_000_000, { schema_version: "1.0", terms: [...terms(), { ...terms()[0], source_key: "third", double_count_group: "third" }],
      correlation: { mode: "matrix_explicit", matrix: [[1, 0.9, -0.9], [0.9, 1, 0.9], [-0.9, 0.9, 1]], matrix_basis: "x" } });
    expect(psd.reasons[0].code).toBe("CORRELATION_NOT_PSD");
  });
});

describe("the ledger editor", () => {
  it("round-trips a saved ledger, typing σ as a percent of the mean", () => {
    const draft = draftOf(independent());
    expect(draft.terms.map((t) => [t.category, t.value, t.unit])).toEqual([["custom", "4", "percent"], ["custom", "3", "percent"]]);
    expect(ledgerOf(draft)).toEqual({ ledger: independent() });
    const matrix: UncertaintyLedger = { ...independent(), correlation: { mode: "matrix_explicit", matrix: [[1, 0.6], [0.6, 1]], matrix_basis: "basis" } };
    expect(draftOf(matrix).matrix).toBe("1, 0.6; 0.6, 1");
    expect(ledgerOf(draftOf(matrix))).toEqual({ ledger: matrix });
  });

  it("a category starts with its scope and double-count group but no number", () => {
    const t = emptyTerm(CATEGORIES[0]);
    expect([t.source_key, t.scope, t.double_count_group, t.value]).toEqual(["interannual_solar_variability", "annual_weather", "solar_resource_weather", ""]);
    expect(CATEGORIES).toHaveLength(6);
  });

  it("asks for what is missing instead of guessing", () => {
    const empty = draftOf(undefined);
    expect(ledgerOf(empty)).toEqual({ problem: "unc1.needTerm" });
    const one = { ...empty, terms: [emptyTerm(CATEGORIES[0])] };
    expect(ledgerOf(one)).toEqual({ problem: "unc1.needValue" });
    one.terms[0].value = "4";
    expect(ledgerOf(one)).toEqual({ problem: "unc1.needSource" });
    one.terms[0].source_ref = "site study"; one.terms[0].justification = "why";
    expect(ledgerOf(one)).toEqual({ problem: "unc1.needBasis" });
    expect(ledgerOf({ ...one, basis: "stated", mode: "matrix_explicit", matrix: "1, x" })).toEqual({ problem: "unc1.needMatrix" });
    expect("ledger" in ledgerOf({ ...one, basis: "stated" })).toBe(true);
  });
});

describe("requests", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("saves with PUT {ledger} and reads the run's annual-pxx route", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })));
    vi.stubGlobal("fetch", fetch);
    await api.updateUncertaintyAssumptions("p 1", independent());
    expect(fetch.mock.calls[0][0]).toBe("/api/projects/p%201/uncertainty-assumptions");
    expect(fetch.mock.calls[0][1].method).toBe("PUT");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ ledger: independent() });
    await api.updateUncertaintyAssumptions("p", null);
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ ledger: null });
    await api.annualPxx("p", "run#1");
    expect(fetch.mock.calls[2][0]).toBe("/api/projects/p/runs/run%231/annual-pxx");
  });
});
