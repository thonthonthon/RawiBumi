import { afterEach, describe, expect, it, vi } from "vitest";
import { exportAPI, type RunTimeSeriesView } from "../../src/api";
import { demoSeries } from "../../src/demo/series";
import { PENDING } from "../../src/pending";
import { coveredMonths, fromDemo, fromEngine, largestLosses, meanDayOfMonth } from "../../src/results/series";
import { moduleNameplateW } from "../../src/types";

// S15: the engine's run series in the Results shape, the D14 nameplate, and the export and series requests.
const view = (): RunTimeSeriesView => ({
  schema_name: "RunTimeSeriesView", run_id: "r", timezone: "Asia/Jakarta", interval_seconds: 3600,
  period: { start: "2025-01-31T00:00:00+07:00", end: "2025-02-02T00:00:00+07:00", hours: 48 },
  days: ["2025-01-31", "2025-02-01"],
  hourly: {
    ac_kw: { label: "AC", unit: "kW", source_column: "pcc_power_w", values: [Array.from({ length: 24 }, (_, h) => h), Array.from({ length: 24 }, (_, h) => (h === 5 ? null : 2 * h))] },
    poa_w_m2: { label: "POA", unit: "W/m²", source_column: "poa_global_w_m2", values: [Array(24).fill(100), Array(24).fill(200)] },
  },
  quality: { repeated_local_hours_averaged: 0, missing_hour_cells: 1 },
  dc_kwp: 10, dc_kwp_basis: "", pr_basis: "",
  monthly: [
    { month: "2025-01", energy_kwh: 5, poa_unshaded_kwh_m2: 0.6, ghi_kwh_m2: 0.7, specific_yield_kwh_kwp: 0.5, performance_ratio: 0.83, losses_kwh: { soiling: 0.2, dc_wiring: 0.05 } },
    { month: "2025-02", energy_kwh: 9, poa_unshaded_kwh_m2: 1.1, ghi_kwh_m2: 1.2, specific_yield_kwh_kwp: 0.9, performance_ratio: 0.82, losses_kwh: { soiling: 0.3, dc_wiring: 0.1 } },
  ],
  loss_channels: [{ loss_type: "soiling", stage: "optical", monthly: true }, { loss_type: "dc_wiring", stage: "array_dc", monthly: true }, { loss_type: "unknown_stage", stage: "x", monthly: false }],
});

describe("engine series in the Results shape", () => {
  it("places months at their calendar index, NaN where the run doesn't reach, and keeps only stored loss channels", () => {
    const s = fromEngine(view());
    expect(s.authority).toBe("ENGINE");
    expect(s.monthly.energyKwh.slice(0, 3)).toEqual([5, 9, NaN]);
    expect(s.monthly.performanceRatio[1]).toBe(0.82);
    expect(s.monthly.lossesKwh.map((l) => l.lossType)).toEqual(["soiling", "dc_wiring"]);
    expect(s.monthly.lossesKwh[0].values.slice(0, 2)).toEqual([0.2, 0.3]);
    expect(s.ac[1][5]).toBeNaN();
    // No cell temperature in this view: a NaN matrix of the same shape.
    expect(s.tcell).toHaveLength(2); expect(s.tcell[0].every(Number.isNaN)).toBe(true);
    expect(s.acBeforeLimit).toBeNull(); expect(s.load).toBeNull();
  });

  it("averages a month's days hour by hour, ignoring missing hours", () => {
    const s = fromEngine(view());
    expect(coveredMonths(s)).toEqual([0, 1]);
    expect(meanDayOfMonth(s, s.ac, 1)[4]).toBe(8);
    expect(meanDayOfMonth(s, s.ac, 1)[5]).toBeNaN();
    expect(meanDayOfMonth(s, s.ac, 0)[3]).toBe(3);
    expect(meanDayOfMonth(s, s.ac, 6).every(Number.isNaN)).toBe(true);
  });

  it("charts the largest losses first", () => {
    expect(largestLosses(fromEngine(view()), 1).map((l) => l.lossType)).toEqual(["soiling"]);
  });

  it("the demo year keeps its synthetic series in the same shape, stamped", () => {
    const s = fromDemo(demoSeries(10, 8), 10, [{ lossType: "soiling", fraction: 0.03 }]);
    expect(s.authority).toBe("DEMO_SYNTHETIC");
    expect(s.days).toHaveLength(365); expect(s.days[31]).toBe("2025-02-01");
    expect(s.monthly.energyKwh.every((x) => x > 0)).toBe(true);
    expect(s.acBeforeLimit).not.toBeNull();
  });
});

describe("D14", () => {
  it("the DC nameplate is the datasheet nominal power, else the STC Pmp", () => {
    expect(moduleNameplateW({ pmp_w: 550.0956, nominal_power_w: 550 })).toBe(550);
    expect(moduleNameplateW({ pmp_w: 410.5 })).toBe(410.5);
    expect(moduleNameplateW({ pmp_w: 410.5, nominal_power_w: null })).toBe(410.5);
  });
});

describe("requests", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reads the series from the run's timeseries route", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(view()), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    expect((await exportAPI.runSeries("p 1", "run#1")).run_id).toBe("r");
    expect(fetch.mock.calls[0][0]).toBe("/api/projects/p%201/runs/run%231/timeseries");
  });

  it("sends the formats and the deliverable flag with the export", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(new Blob(["PK"]), { status: 200, headers: { "Content-Type": "application/zip" } }));
    vi.stubGlobal("fetch", fetch);
    await exportAPI.exportCSV("p", "r", { format: "csv", resolution: "hourly", level: "project", columns: ["pcc_power_w"], formats: ["csv", "parquet"], deliverable: true });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ format: "csv", resolution: "hourly", level: "project", columns: ["pcc_power_w"], formats: ["csv", "parquet"], deliverable: true });
  });

  it("the series and export badges are gone", () => {
    expect(PENDING).not.toHaveProperty("timeSeries");
    expect(PENDING).not.toHaveProperty("exportBundle");
  });
});
