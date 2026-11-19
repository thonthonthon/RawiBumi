import { beforeAll, describe, expect, it } from "vitest";
import { demoSeries } from "../../src/demo/series";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { can } from "../../src/platform/entitlements";
import { buildResultModel, checkResultRules, isAnnualResult, modelFingerprint, reportModel, ResultRuleError, weeklyHeatmap, type ResultModel } from "../../src/results/model";
import { buildReport } from "../../src/report/build";
import { CHAPTERS, renderReportHtml, type ReportInput } from "../../src/report/template";
import type { ProjectView } from "../../src/types";
import { EMPTY_SYSTEM } from "../../src/site/systemInfo";

// F7 done-when (plan C2): S10's result rules ported as tests. Each test names the S10 rule it
// ports (s10/tests/report.test.ts "S03 …", s10/tests/s06_report_test.py "a01…a21"). The S10
// fixture had per-inverter energy and a separate PCC boundary; the engine's summary result has
// neither yet, so those rules report "unavailable" here and say why.

let view: ProjectView;
let hourly: number[][];
const t = (key: string, o: Record<string, unknown> = {}) => (key === "results.monthsShort" ? "Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec" : `${key}${Object.keys(o).length ? JSON.stringify(o) : ""}`);

beforeAll(async () => {
  setDemoLatency(0);
  view = await mockApi.project("demo-project");
  const m = buildResultModel(view, view.bundle.simulation_runs[0], { authority: "DEMO_SYNTHETIC", hourlyAcKw: null });
  hourly = demoSeries(m.dcKwp, m.acKw || 1).acAfter;
});

const runId = () => view.bundle.simulation_runs[0].simulation_run_id;
const model = (): ResultModel => buildResultModel(view, view.bundle.simulation_runs[0], { authority: "DEMO_SYNTHETIC", hourlyAcKw: hourly });
const rule = (m: ResultModel, id: string) => checkResultRules(m, { strings: view.bundle.electrical_design.strings.length }).find((r) => r.id === id)!;
const periodView = (): ProjectView => {
  const v = structuredClone(view);
  const s = v.bundle.simulation_runs[0].summary_result!;
  const total = 12267.756220626674;
  Object.assign(s, {
    period_start_time: "2025-01-01T00:00:00+07:00",
    period_end_time: "2025-01-01T04:00:00+07:00",
    period_duration_hours: 4,
    total_energy_wh: total,
    annual_energy_wh: null,
    monthly_energy: [{ month: "2025-01", energy_wh: total }],
    specific_yield_wh_per_wp: total / 1000 / model().dcKwp,
    clipping_energy_wh: 0,
    loss_summary: [{ loss_type: "inverter_efficiency", stage: "inverter", reference_energy_wh: total + 1000, lost_energy_wh: 1000, loss_fraction: 1000 / (total + 1000), method: "test" }]
  });
  return v;
};
const report = (over: Partial<ReportInput> = {}) =>
  renderReportHtml({
    model: model(),
    rules: checkResultRules(model(), { strings: view.bundle.electrical_design.strings.length }),
    tier: "free",
    branding: "",
    planFigure: { png: "data:image/png;base64,AAAA", width: 900, height: 540 },
    sldSvg: "<svg></svg>",
    charts: { monthly: "<svg data-c='m'></svg>", waterfall: "<svg data-c='w'></svg>", heatmap: "<svg data-c='h'></svg>" },
    fingerprint: modelFingerprint(model()),
    generatedAt: "2026-10-22 08:00 UTC",
    identity: { address: "Jl. Contoh 1, Bandung", addressAttribution: "© OpenStreetMap contributors", latitude: -6.2, longitude: 106.82, elevationM: 12, issuedOn: "2026-10-22", system: EMPTY_SYSTEM },
    css: "",
    t,
    ...over
  });

describe("S10 result rules on the demo run", () => {
  it("passes every rule it can check, and says which it cannot", () => {
    const rules = checkResultRules(model(), { strings: view.bundle.electrical_design.strings.length });
    expect(rules.filter((r) => r.state === "fail")).toEqual([]);
    expect(rules.find((r) => r.id === "S03.pcc-distinct")!.state).toBe("unavailable");
    expect(() => reportModel(view, runId(), { authority: "DEMO_SYNTHETIC", hourlyAcKw: hourly })).not.toThrow();
  });

  it("S03: twelve monthly bins", () => expect(rule(model(), "S03.twelve-months").state).toBe("pass"));

  it("S06 a03/a04: monthly energy reconciles to the annual energy; a broken month is refused", () => {
    expect(rule(model(), "S06.a04").state).toBe("pass");
    const bad = { ...model(), monthlyAcKwh: model().monthlyAcKwh.map((v, i) => (i === 1 ? 999_999 : v)) };
    expect(rule(bad, "S06.a04").state).toBe("fail");
  });

  it("S03 / S06 a10: the loss waterfall reconciles to the AC energy; an unreconciled ledger is refused", () => {
    const m = model();
    expect(rule(m, "S03.loss-reconciles").state).toBe("pass");
    expect(m.losses[m.losses.length - 1].remainingKwh).toBeCloseTo(m.periodAcKwh, 3);
    const bad = { ...m, losses: m.losses.map((l, i) => (i === m.losses.length - 1 ? { ...l, remainingKwh: l.remainingKwh + 5000 } : l)) };
    expect(rule(bad, "S03.loss-reconciles").state).toBe("fail");
  });

  it("S03: the inverter AC and PCC boundaries are not conflated (reported unavailable until the engine separates them)", () => {
    expect(rule(model(), "S03.pcc-distinct")).toMatchObject({ state: "unavailable", blocking: false });
  });

  it("S06 a05 / S03: a full year with no missing hour; a missing hour fails (a12)", () => {
    expect(rule(model(), "S03.full-year").state).toBe("pass");
    expect(rule(model(), "S06.a05").state).toBe("pass");
    const gap = hourly.map((d, i) => (i === 100 ? d.map((x, h) => (h === 12 ? NaN : x)) : d));
    const m = buildResultModel(view, view.bundle.simulation_runs[0], { authority: "DEMO_SYNTHETIC", hourlyAcKw: gap });
    expect(m.coverage!.missingHours).toBe(1);
    expect(rule(m, "S06.a05").state).toBe("fail");
  });

  it("S03: the 52-week view shows 8,736 hours and leaves out 24 (view only, not missing data)", () => {
    const w = weeklyHeatmap(hourly);
    expect([w.values.length, w.values[0].length]).toEqual([52, 24]);
    expect(w.coverage).toMatchObject({ sourceHours: 8760, missingHours: 0, weeklyShown: 8736, weeklyExcluded: 24, excludedDays: [364] });
    expect(rule(model(), "S03.weekly-reduction").state).toBe("pass");
    // Week 1, 12:00 is the mean of days 0–6 at 12:00.
    expect(w.values[0][12]).toBeCloseTo(hourly.slice(0, 7).reduce((s, d) => s + d[12], 0) / 7, 9);
    // A leap year leaves out 48 hours.
    expect(weeklyHeatmap([...hourly, hourly[0]]).coverage).toMatchObject({ sourceHours: 8784, weeklyShown: 8736, weeklyExcluded: 48 });
  });

  it("S06 a13: a non-finite number is refused", () => {
    const bad = { ...model(), monthlyAcKwh: model().monthlyAcKwh.map((v, i) => (i === 0 ? NaN : v)) };
    expect(rule(bad, "S06.a13").state).toBe("fail");
  });

  it("S01: specific yield agrees with energy ÷ installed DC capacity from the catalogue Pmp", () => {
    const m = model();
    expect(m.dcKwp).toBeCloseTo((76 * 550) / 1000, 6);
    expect(rule(m, "S01.dc-quantity").state).toBe("pass");
  });

  it("S06 a06 / a11: every assigned string appears once in the topology table", () => {
    const m = model();
    expect(m.topology.map((r) => r.string)).toEqual(["S1", "S2", "S3", "S4", "S5"]);
    expect(m.topology.find((r) => r.string === "S5")).toMatchObject({ inverter: "INV-01", mppt: 4, modules: 14 });
    expect(rule({ ...m, topology: [...m.topology, m.topology[0]] }, "S06.a06").state).toBe("fail");
  });

  it("S06 a14: no uncertainty (P50/P90) is modelled", () => expect(model().uncertainty).toBe("NOT_MODELED"));

  it("S03: an unknown run gets no report; a blocking failure refuses the report", () => {
    expect(() => reportModel(view, "fake-run", { authority: "DEMO_SYNTHETIC", hourlyAcKw: hourly })).toThrow(/not part of this project/);
    const broken: ProjectView = structuredClone(view);
    broken.bundle.simulation_runs[0].summary_result!.monthly_energy[0].energy_wh += 5e8;
    let err: unknown;
    try {
      reportModel(broken, runId(), { authority: "DEMO_SYNTHETIC", hourlyAcKw: hourly });
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(ResultRuleError);
    expect((err as ResultRuleError).failures.map((f) => f.id)).toEqual(["S06.a04"]);
  });

  it("S06 a02: the fingerprint is stable for the same input and changes with it", () => {
    expect(modelFingerprint(model())).toBe(modelFingerprint(model()));
    expect(modelFingerprint({ ...model(), annualAcKwh: model().annualAcKwh! + 1 })).not.toBe(modelFingerprint(model()));
  });
});

describe("F8.1 period energy and Phase 7 annual eligibility", () => {
  it("keeps four-hour energy separate from unavailable annual energy and validates the period ledger and yield", () => {
    const v = periodView();
    const m = buildResultModel(v, v.bundle.simulation_runs[0], { authority: "ENGINE", hourlyAcKw: null });
    expect(m.periodAcKwh).toBeCloseTo(12.267756220626674, 9);
    expect(m.annualAcKwh).toBeNull();
    expect(m.periodHours).toBe(4);
    expect(m.monthlyAcKwh).toHaveLength(1);
    expect(isAnnualResult(m)).toBe(false);
    expect(rule(m, "S06.a04").state).toBe("unavailable");
    expect(rule(m, "S03.annual-energy-available")).toMatchObject({ state: "fail", blocking: true });
    expect(rule(m, "S03.full-year")).toMatchObject({ state: "fail", blocking: true });
    expect(rule(m, "S06.a13").state).toBe("pass");
    for (const id of ["S03.loss-reconciles", "S01.dc-quantity"]) {
      expect(rule(m, id)).toMatchObject({ state: "pass", message: expect.stringContaining("simulated-period") });
      const bad = { ...m, periodAcKwh: m.periodAcKwh + 100 };
      expect(rule(bad, id).state).toBe("fail");
    }
    expect(() => reportModel(v, runId(), { authority: "ENGINE", hourlyAcKw: null })).toThrow(ResultRuleError);
    // Direct template callers cannot bypass the guard with a stale/passing rule list.
    expect(() => report({ model: m, rules: [] })).toThrow(/Annual report requires/);
    expect(() => buildReport({ view: v, entities: [], modules: [], runId: runId(), authority: "ENGINE", hourlyAcKw: null, tier: "free", branding: "", address: null, t })).toThrow(ResultRuleError);
  });

  it("uses annual_energy_wh for eligible annual reconciliation and report energy, independently of total_energy_wh", () => {
    const v = structuredClone(view);
    const s = v.bundle.simulation_runs[0].summary_result!;
    s.total_energy_wh = 12267.756220626674;
    const { model: m } = reportModel(v, runId(), { authority: "ENGINE", hourlyAcKw: null });
    expect(m.periodAcKwh).toBeCloseTo(12.267756220626674, 9);
    expect(m.annualAcKwh).toBe(s.annual_energy_wh! / 1000);
    expect(isAnnualResult(m)).toBe(true);
    for (const id of ["S06.a04", "S03.loss-reconciles", "S01.dc-quantity"]) expect(rule(m, id).state).toBe("pass");
    const html = report({ model: m });
    expect(html).toContain(`<strong>${(m.annualAcKwh! / 1000).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}</strong><em>MWh</em>`);
    expect(html).toContain(`<td class="num">${m.annualAcKwh!.toLocaleString("en-US", { maximumFractionDigits: 0 })}</td>`);
  });

  it.each([null, NaN, Infinity, -1])("blocks missing or invalid annual energy (%s) even with 8,760 hours and 12 bins", (annual) => {
    const v = structuredClone(view);
    v.bundle.simulation_runs[0].summary_result!.annual_energy_wh = annual;
    const m = buildResultModel(v, v.bundle.simulation_runs[0], { authority: "ENGINE", hourlyAcKw: null });
    expect(isAnnualResult(m)).toBe(false);
    expect(rule(m, "S06.a04").state).not.toBe("pass");
    expect(rule(m, "S03.annual-energy-available")).toMatchObject({ state: "fail", blocking: true });
    expect(() => reportModel(v, runId(), { authority: "ENGINE", hourlyAcKw: null })).toThrow(ResultRuleError);
    expect(() => report({ model: m })).toThrow(/Annual report requires/);
  });

  it.each([4, 8784, 8759.999, 8760.001])("refuses %s period hours as a Phase 7 annual result even when annual energy and 12 bins exist", (hours) => {
    const v = structuredClone(view);
    v.bundle.simulation_runs[0].summary_result!.period_duration_hours = hours;
    const m = buildResultModel(v, v.bundle.simulation_runs[0], { authority: "ENGINE", hourlyAcKw: null });
    expect(m.periodHours).toBe(hours);
    expect(isAnnualResult(m)).toBe(false);
    expect(rule(m, "S03.full-year")).toMatchObject({ state: "fail", blocking: true });
    expect(rule(m, "S06.a04").state).not.toBe("pass");
    expect(() => reportModel(v, runId(), { authority: "ENGINE", hourlyAcKw: null })).toThrow(ResultRuleError);
    expect(() => report({ model: m })).toThrow(/Annual report requires/);
  });

  it.each([1, 11, 13])("requires exactly 12 monthly bins, refusing %s even with annual energy and 8,760 hours", (bins) => {
    const v = structuredClone(view);
    const s = v.bundle.simulation_runs[0].summary_result!;
    s.monthly_energy = Array.from({ length: bins }, (_, i) => ({ month: String(i + 1), energy_wh: s.annual_energy_wh! / bins }));
    const m = buildResultModel(v, v.bundle.simulation_runs[0], { authority: "ENGINE", hourlyAcKw: null });
    expect(isAnnualResult(m)).toBe(false);
    expect(rule(m, "S03.twelve-months")).toMatchObject({ state: "fail", blocking: true });
    expect(() => reportModel(v, runId(), { authority: "ENGINE", hourlyAcKw: null })).toThrow(ResultRuleError);
    expect(() => report({ model: m })).toThrow(/Annual report requires/);
  });

  it("accepts a finite zero annual energy rather than treating it as unavailable", () => {
    const v = structuredClone(view);
    const s = v.bundle.simulation_runs[0].summary_result!;
    s.annual_energy_wh = 0;
    s.total_energy_wh = 0;
    s.specific_yield_wh_per_wp = 0;
    s.monthly_energy = s.monthly_energy.map((m) => ({ ...m, energy_wh: 0 }));
    s.loss_summary = [];
    const { model: m } = reportModel(v, runId(), { authority: "ENGINE", hourlyAcKw: null });
    expect(m.annualAcKwh).toBe(0);
    expect(isAnnualResult(m)).toBe(true);
    expect(rule(m, "S06.a04").state).toBe("pass");
    expect(report({ model: m })).toContain("<strong>0.0</strong><em>MWh</em>");
  });
});

describe("S10 report rules on the HTML template", () => {
  it("S06 a01 / a07: synthetic data is stamped and never presented as an engine run", () => {
    const h = report();
    expect(h).toContain('data-authority="DEMO_SYNTHETIC"');
    expect(h).toContain("report.syntheticStamp");
    expect(h).toContain("report.authoritySynthetic");
    const real = report({ model: { ...model(), authority: "ENGINE" } });
    expect(real).not.toContain("report.syntheticStamp");
    expect(real).toContain("report.authorityEngine");
  });

  it("S06 a17: branding is escaped", () => {
    const h = report({ tier: "branded", branding: "<script>alert(1)</script>" });
    expect(h).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
    expect(h).not.toContain("<script>alert(1)</script>");
  });

  it("S06 a18: the free report carries no branding", () => {
    const h = report({ tier: "free", branding: "SECRET COMPANY" });
    expect(h).not.toContain("SECRET COMPANY");
    expect(h).not.toContain("data-branding");
    expect(h).toContain("report.footFree");
  });

  it("S06 a20 / S03: no entitled export is claimed: branding is a paid feature, off when self-hosted", () => {
    expect(can("report.branded")).toBe(false);
  });

  it("S06 a19: the heatmap caption says the weekly view leaves hours out, and that no source hour is missing", () => {
    const h = report();
    // The stub translator prints its options; the template escapes them like any other text.
    expect(h).toContain("&quot;shown&quot;:&quot;8,736&quot;");
    expect(h).toContain("&quot;excluded&quot;:&quot;24&quot;");
    expect(h).toContain("&quot;missing&quot;:&quot;0&quot;");
  });

  it("S06 a21: every chapter is present, in order: topology, monthly, waterfall, 52-week heatmap, checks, scope", () => {
    const h = report();
    const order = CHAPTERS.map((c) => h.indexOf(`data-chapter="${c}"`));
    expect(order.every((i) => i > 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(CHAPTERS).toHaveLength(12);
    for (const k of ["report.ch_topology", "report.ch_losses", "report.ch_heatmap", "report.scopeValidation", "report.scopeUncertainty"]) expect(h).toContain(k);
    expect(h).toContain("data-plan-figure");
  });

  it("is deterministic: the same inputs give the same document", () => {
    expect(report()).toBe(report());
  });
});
