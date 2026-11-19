import { beforeAll, describe, expect, it } from "vitest";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { buildResultModel, checkResultRules, modelFingerprint } from "../../src/results/model";
import { renderReportHtml, type ReportInput } from "../../src/report/template";
import { beyondSimulation, EMPTY_SYSTEM, formatEnergy, formatPower, formatPvCapacity, loadSystem, type SystemInfo } from "../../src/site/systemInfo";
import type { ProjectView } from "../../src/types";

// F7.2 (owner's direction, 22 Oct): the cover's first section also gives the installation type,
// the PV capacity (kWp or MWp) and the BESS capacity (kWh or MWh).

let view: ProjectView;
const t = (key: string, o: Record<string, unknown> = {}) => (key === "results.monthsShort" ? "Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec" : `${key}${Object.keys(o).length ? JSON.stringify(o) : ""}`);

beforeAll(async () => {
  setDemoLatency(0);
  view = await mockApi.project("demo-project");
});

const report = (system: SystemInfo, over: Partial<ReportInput> = {}) => {
  const m = over.model ?? buildResultModel(view, view.bundle.simulation_runs[0], { authority: "DEMO_SYNTHETIC", hourlyAcKw: null });
  return renderReportHtml({
    model: m,
    rules: checkResultRules(m, { strings: view.bundle.electrical_design.strings.length }),
    tier: "free",
    branding: "",
    planFigure: null,
    sldSvg: "<svg></svg>",
    charts: { monthly: "<svg></svg>", waterfall: null, heatmap: null },
    fingerprint: modelFingerprint(m),
    generatedAt: "2026-10-22 08:00 UTC",
    identity: { address: "Jl. Contoh 1", addressAttribution: null, latitude: -6.2, longitude: 106.82, elevationM: 12, issuedOn: "2026-10-22", system },
    css: "",
    t,
    ...over
  });
};
const cover = (h: string) => h.slice(h.indexOf("data-cover"), h.indexOf("data-toc"));
const cell = (h: string, attr: string) => {
  const i = h.indexOf(attr);
  return h.slice(h.indexOf("<td>", i) + 4, h.indexOf("</td>", i));
};

describe("F7.2 units", () => {
  it("writes PV capacity in kWp below 1 MWp and in MWp from there", () => {
    expect(formatPvCapacity(41.8)).toBe("41.8 kWp");
    expect(formatPvCapacity(999.94)).toBe("999.9 kWp");
    expect(formatPvCapacity(1000)).toBe("1.00 MWp");
    expect(formatPvCapacity(12345.6)).toBe("12.35 MWp");
  });
  it("writes energy in kWh below 1 MWh and in MWh from there; power in kW or MW", () => {
    expect(formatEnergy(215)).toBe("215 kWh");
    expect(formatEnergy(232.5)).toBe("232.5 kWh");
    expect(formatEnergy(2000)).toBe("2.00 MWh");
    expect(formatPower(500)).toBe("500 kW");
    expect(formatPower(1250)).toBe("1.25 MW");
  });
});

describe("F7.2 cover: installation type, PV capacity, BESS capacity", () => {
  it("shows the design's PV capacity and says when type and BESS are not given", () => {
    const c = cover(report(EMPTY_SYSTEM));
    expect(cell(c, "data-pv-capacity")).toBe("41.8 kWp");
    expect(cell(c, "data-installation-type")).toContain("report.addressNone");
    expect(cell(c, "data-bess")).toContain("report.addressNone");
    expect(c).not.toContain("data-not-simulated");
    // Order: project, installation type, PV, BESS, then address.
    const order = ["report.project", "data-installation-type", "data-pv-capacity", "data-bess", "data-address"].map((k) => c.indexOf(k));
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it("an on-grid system without battery states no limitation", () => {
    const c = cover(report({ installationType: "on_grid", bessEnergyKwh: 0, bessPowerKw: null }));
    expect(cell(c, "data-installation-type")).toBe("site.type_on_grid");
    expect(cell(c, "data-bess")).toBe("report.bessNone");
    expect(c).not.toContain("data-not-simulated");
  });

  it("a hybrid system with a battery shows power / energy and says the battery is not simulated", () => {
    const s: SystemInfo = { installationType: "hybrid", bessEnergyKwh: 1000, bessPowerKw: 500 };
    expect(beyondSimulation(s)).toBe(true);
    const h = report(s);
    const c = cover(h);
    expect(cell(c, "data-installation-type")).toBe("site.type_hybrid");
    expect(cell(c, "data-bess")).toBe("500 kW / 1.00 MWh");
    expect(c).toContain("data-not-simulated");
    expect(h).toContain("report.scopeSystem");
  });

  it("off-grid or zero export alone also carries the not-simulated note", () => {
    for (const x of ["off_grid", "on_grid_zero_export"] as const) expect(cover(report({ installationType: x, bessEnergyKwh: null, bessPowerKw: null }))).toContain("data-not-simulated");
  });

  it("shows MWp on a large design", () => {
    const m = buildResultModel(view, view.bundle.simulation_runs[0], { authority: "DEMO_SYNTHETIC", hourlyAcKw: null });
    expect(cell(cover(report(EMPTY_SYSTEM, { model: { ...m, dcKwp: 2400 } })), "data-pv-capacity")).toBe("2.40 MWp");
  });

  it("refuses stored values it cannot trust: an unknown type or a negative capacity reads as not given", () => {
    const store = new Map<string, string>();
    (globalThis as unknown as { window: unknown }).window = { localStorage: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => store.set(k, v) } };
    window.localStorage.setItem("rawibumi.systemInfo.p1", JSON.stringify({ installationType: "nuclear", bessEnergyKwh: -5, bessPowerKw: 100 }));
    expect(loadSystem("p1")).toEqual({ installationType: null, bessEnergyKwh: null, bessPowerKw: 100 });
    expect(loadSystem("missing")).toEqual(EMPTY_SYSTEM);
    delete (globalThis as unknown as { window?: unknown }).window;
  });
});
