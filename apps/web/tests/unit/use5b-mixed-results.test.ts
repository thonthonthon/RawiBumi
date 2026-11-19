import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import i18n from "../../src/i18n";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { MixedOrientationResults } from "../../src/results/MixedOrientation";
import { ResultsView } from "../../src/results/ResultsView";
import { buildResultModel } from "../../src/results/model";
import { fromDemo, largestLosses } from "../../src/results/series";
import { demoSeries } from "../../src/demo/series";
import { waterfallOption, paletteFromTokens } from "../../src/results/chartOptions";
import type { ProjectBundle, ProjectView, SimulationRunRecord } from "../../src/types";

const screen = vi.hoisted(() => ({ view: null as ProjectView | null }));
vi.mock("../../src/state/store", async load => ({ ...await load<typeof import("../../src/state/store")>(),
  useStore: () => ({ state: { view: screen.view, busy: null }, dispatch: vi.fn(), toast: vi.fn(), run: vi.fn() }),
  useForm: (key: string, initial: unknown) => [key === "results.tab" ? "losses" : initial, vi.fn()]
}));
let original: ProjectView;
beforeAll(async () => { setDemoLatency(0); original = structuredClone(await mockApi.project("demo-project")); });
afterEach(async () => { await i18n.changeLanguage("en"); });

function fixture() {
  const view = structuredClone(original), run = view.bundle.simulation_runs[0];
  const inverter = view.bundle.electrical_design.inverter_instances[0];
  view.bundle.electrical_design.inverter_instances = [
    { ...inverter, inverter_instance_id: "inv-a", name: "Roof inverter A", mppt_instance_ids: ["p1"] },
    { ...inverter, inverter_instance_id: "inv-b", name: "Roof inverter B", mppt_instance_ids: ["p2"] }
  ];
  view.bundle.electrical_design.mppt_instances = [
    { inverter_instance_id: "inv-a", mppt_instance_id: "p1", index: 2 },
    { inverter_instance_id: "inv-b", mppt_instance_id: "p2", index: 7 }
  ];
  view.bundle.pinned_components = { modules: {
    "module-data-r1": { model: "Recorded data module" }, "module-fallback-r1": { model: "Recorded fallback module" },
    partial: { model: "Recorded partial module" }, zero: { model: "Recorded zero-diode module" }
  } };
  run.mixed_orientation = {
    model_id: "rawibumi.mixed_orientation.v0.1", scope_label: "Recorded mixed run", shading_basis: "orientation_class_average", tracker_basis: "ideal_global_mpp",
    mixed_string_ids: ["composite"], mixed_mppt_instance_ids: ["p1", "p2"],
    bypass_basis_by_module_revision: {
      "module-data-r1": { diode_count: 3, forward_voltage_v: .5, count_basis: "data", forward_voltage_basis: "data", no_bypass_current_limited: false, source_paths: [] },
      "module-fallback-r1": { diode_count: 3, forward_voltage_v: .7, count_basis: "assumed", forward_voltage_basis: "assumed", no_bypass_current_limited: false, source_paths: [] }
    },
    mppts: [
      { inverter_instance_id: "inv-a", mppt_instance_id: "p1", multi_peak_interval_count: 10, multi_peak_duration_hours: 2.5, energy_gaps_wh: { simple_tracker: 1001, second_highest: 2001, lowest: 3001 } },
      { inverter_instance_id: "inv-b", mppt_instance_id: "p2", multi_peak_interval_count: 20, multi_peak_duration_hours: 5, energy_gaps_wh: { simple_tracker: 1002, second_highest: 2002, lowest: 3002 } }
    ],
    // Sentinel totals deliberately differ from the rows: the UI must read, not derive, the recorded total.
    period_totals: { start_time: "2025-01-01T00:00:00+07:00", end_time: "2025-01-04T00:00:00+07:00", duration_hours: 72,
      multi_peak_interval_count: 17, multi_peak_duration_hours: 4.25, multi_peak_mppt_interval_count: 30, multi_peak_mppt_duration_hours: 7.5,
      energy_gaps_wh: { simple_tracker: 12345, second_highest: 2345, lowest: 34567 } },
    is_complete_year: false
  };
  run.summary_result!.loss_summary.push({ loss_type: "orientation_mismatch", stage: "array_dc", reference_energy_wh: 1000000, lost_energy_wh: 1234, loss_fraction: .001234 });
  return { view, run };
}
const render = (run: SimulationRunRecord, bundle: ProjectBundle) => renderToStaticMarkup(createElement(MixedOrientationResults, { run, bundle }));

describe("recorded mixed-orientation Results", () => {
  it("shows the banner, each recorded bypass basis and the ideal tracker only with a mixed record", async () => {
    await i18n.changeLanguage("en");
    const { view, run } = fixture(), html = render(run, view.bundle);
    expect(html).toContain("Mixed orientation simulated — beyond what PVsyst/HelioScope simulate.");
    expect(html).toContain("Bypass diodes: from module data");
    expect(html).toContain("assumed 3 × 0.7 V for Recorded fallback module");
    expect(html).toContain("Ideal MPPT: the highest power peak.");
    delete run.mixed_orientation;
    expect(render(run, view.bundle)).toBe("");
  });
  it("shows bundle inverter names, MPPT indices and pinned module models, retaining IDs only as attributes", async () => {
    await i18n.changeLanguage("en");
    const { view, run } = fixture();
    view.catalog.modules[0].model = "Current catalogue model must not replace the pin";
    const html = render(run, view.bundle), text = html.replace(/<[^>]*>/g, "");
    for (const label of ["Roof inverter A / MPPT 2", "Roof inverter B / MPPT 7", "Recorded data module", "Recorded fallback module"]) expect(text).toContain(label);
    for (const id of ["inv-a", "inv-b", "p1", "p2", "module-data-r1", "module-fallback-r1"]) expect(text).not.toContain(id);
    expect(text).not.toContain("Current catalogue model must not replace the pin");
    expect(html).toContain('data-mixed-inverter="inv-a"'); expect(html).toContain('data-mixed-mppt="p1"');
    expect(html).toContain('data-bypass-revision="module-data-r1"');
    expect(html).toContain('data-bypass-revision="module-fallback-r1"');
    delete view.bundle.pinned_components;
    delete view.bundle.electrical_design.mppt_instances;
    view.bundle.electrical_design.inverter_instances = [];
    const unresolved = render(run, view.bundle).replace(/<[^>]*>/g, "");
    expect(unresolved).toContain("not recorded");
    for (const id of ["inv-a", "p1", "module-data-r1"]) expect(unresolved).not.toContain(id);
  });
  it("preserves supplied values and partial provenance, including an explicit zero-diode basis", async () => {
    await i18n.changeLanguage("en");
    const { view, run } = fixture();
    run.mixed_orientation!.bypass_basis_by_module_revision = {
      partial: { diode_count: 2, forward_voltage_v: .7, count_basis: "data", forward_voltage_basis: "assumed", no_bypass_current_limited: false, source_paths: [] },
      zero: { diode_count: 0, forward_voltage_v: .7, count_basis: "data", forward_voltage_basis: "assumed", no_bypass_current_limited: true, source_paths: [] }
    };
    const html = render(run, view.bundle);
    expect(html).toContain("Bypass diodes: 2 × 0.7 V for Recorded partial module");
    expect(html).toContain("Count: from module data; Forward voltage: assumed");
    expect(html).toContain("No bypass protection (0 diodes).");
    expect(html).not.toContain("assumed 3 ×");
  });
  it("reads plant and per-MPPT hours and gaps directly, without deriving or annualising totals", async () => {
    await i18n.changeLanguage("en");
    const { view, run } = fixture(), before = JSON.stringify(run), html = render(run, view.bundle);
    expect(html).toContain('data-multi-peak-hours="4.25"');
    for (const gap of [12345, 2345, 34567, 1001, 2001, 3001, 1002, 2002, 3002]) expect(html).toContain(`data-gap-wh="${gap}"`);
    for (const value of ["−12.345 kWh", "−2.345 kWh", "−34.567 kWh"]) expect(html).toContain(value);
    expect(html).toContain("If a tracker settled on a lower peak");
    expect(html).toContain("Diagnostics only — the result uses the highest peak.");
    expect(html).toContain("Sum across MPPTs: 7.5 multi-peak hours");
    expect(html).toContain("Partial period:"); expect(html).toContain("72 h");
    expect(html).toContain("2025-01-04T00:00:00+07:00");
    expect(JSON.stringify(run)).toBe(before);
    run.mixed_orientation!.is_complete_year = true;
    expect(render(run, view.bundle)).toContain("Complete simulated year");
    expect(render(run, view.bundle)).not.toContain("Partial period:");
  });
  it.each([["en", "Orientation mismatch"], ["id", "Ketidaksesuaian orientasi"]])("labels the loss table and waterfall in %s", async (language, label) => {
    await i18n.changeLanguage(language);
    const { view, run } = fixture(); screen.view = view;
    view.bundle.simulation_runs = [run];
    const model = buildResultModel(view, run, { authority: "ENGINE", hourlyAcKw: null });
    const loss = model.losses.find(l => l.label === label)!;
    expect(loss.lossKwh).toBe(1.234);
    const chart = waterfallOption(paletteFromTokens(), { start: { label: "DC", value: 1000 },
      losses: [{ label: loss.label, value: loss.lossKwh }], end: { label: "AC", value: 900 }, unit: "kWh", aria: "losses" });
    expect(JSON.stringify(chart)).toContain(label);
    const html = renderToStaticMarkup(createElement(ResultsView));
    expect(html).toContain('data-loss-type="orientation_mismatch"');
    expect(html).toContain(label); expect(html).toContain('data-loss-wh="1234"');
    expect(i18n.t("losses.stages.orientation_mismatch")).toBe(label);
  });
  it("keeps the small orientation channel in monthly views even behind eight larger channels", async () => {
    const series = fromDemo(demoSeries(10, 8), 10, Array.from({ length: 9 }, (_, i) => ({ lossType: `loss-${i}`, fraction: .01 })));
    series.monthly.lossesKwh.push({ lossType: "orientation_mismatch", values: [.001, ...Array(11).fill(NaN)] });
    expect(largestLosses(series, 8).some(l => l.lossType === "orientation_mismatch")).toBe(false);
    const visible = largestLosses(series, 8, "orientation_mismatch");
    expect(visible).toHaveLength(8);
    expect(visible.at(-1)!.values[0]).toBe(.001);
    for (const language of ["en", "id"]) {
      await i18n.changeLanguage(language);
      expect(visible.map(l => i18n.t(`losses.stages.${l.lossType}`))).toContain(i18n.t("losses.stages.orientation_mismatch"));
    }
  });
  it("adds nothing to unmixed runs and invents no orientation results for the demo", async () => {
    const demo = await mockApi.simulate("demo-project");
    expect(demo.mixed_orientation).toBeUndefined();
    expect(demo.summary_result!.loss_summary.some(l => l.loss_type === "orientation_mismatch")).toBe(false);
    expect(render(demo, original.bundle)).toBe("");
    screen.view = structuredClone(original);
    const before = JSON.stringify(screen.view.bundle.simulation_runs[0]);
    const html = renderToStaticMarkup(createElement(ResultsView));
    expect(html).not.toContain("data-mixed-diagnostics"); expect(html).not.toContain("data-mixed-orientation-result");
    expect(html).not.toContain("data-loss-type");
    expect(JSON.stringify(screen.view.bundle.simulation_runs[0])).toBe(before);
  });
});
