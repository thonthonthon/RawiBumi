import { beforeEach, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { LOSS_FIELDS, LossesPanel, lossDraft, lossFormErrors, lossFormPatch, RunLossSettings } from "../../src/panels/LossesPanel";
import type { ResolvedLossSettings, SimulationRunRecord } from "../../src/types";
import { buildResultModel } from "../../src/results/model";
import fixture from "./s7b-engine-fixture.json";
import type { ProjectView } from "../../src/types";
import i18n from "../../src/i18n";

const harness = vi.hoisted(() => ({ view: null as ProjectView | null, busy: false, slots: [] as unknown[], cursor: 0, update: vi.fn(), dispatch: vi.fn() }));
vi.mock("react", async (load) => ({ ...await load<typeof import("react")>(),
  useState: (initial: unknown) => { const i = harness.cursor++; if (!(i in harness.slots)) harness.slots[i] = typeof initial === "function" ? initial() : initial; return [harness.slots[i], (value: unknown) => { harness.slots[i] = value; }]; }, useEffect: () => undefined }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: i18n.t.bind(i18n) }), initReactI18next: { type: "3rdParty", init() {} } }));
vi.mock("../../src/client", () => ({ engine: { updateLosses: harness.update } }));
vi.mock("../../src/state/store", () => ({ useStore: () => ({ state: { view: harness.view, busy: harness.busy }, dispatch: harness.dispatch,
  run: async (_label: string, operation: () => Promise<unknown>) => operation() }) }));
function tree(value: unknown): ReactElement<any>[] {
  if (Array.isArray(value)) return value.flatMap(tree);
  if (!isValidElement(value)) return [];
  const n = value as ReactElement<any>; return [n, ...tree(n.props.children)];
}
beforeEach(async () => { harness.cursor = 0; harness.slots = []; harness.busy = false; harness.dispatch.mockReset(); harness.update.mockReset(); await i18n.changeLanguage("en"); harness.view = { ...structuredClone(fixture.views.before), resolved_loss_settings: settings } as unknown as ProjectView; harness.update.mockImplementation(async () => harness.view); });

const settings: ResolvedLossSettings = { schema_name: "LossSettings", schema_version: "0.1", defaults_id: "recommended_defaults.v1", overrides: {},
  settings_sha256: "frozen-run-hash", status: "recommended_defaults", sources: {}, values: {
    soiling: { monthly_fractions: Array(12).fill(.03) }, lid_fraction: 0, module_mismatch_fraction: null, string_mismatch_fraction: null,
    dc_wiring_stc_fraction: .015, ac_wiring_nominal_fraction: 0, annual_degradation_fraction: .004, operating_year: 1, degradation_fraction: .002,
    transformer: { enabled: false, reference_power_w: null, iron_fraction: .001, copper_fraction: null }, unavailability_fraction: 0 } };
it("form uses fractions, automatic blanks, validates ranges and sends only deliberate changes", () => {
  const initial = lossDraft(settings);
  expect(initial.month1).toBe("3"); expect(initial.dc_wiring_stc_fraction).toBe("1.5"); expect(initial.module_mismatch_fraction).toBe("");
  expect(lossFormErrors(initial)).toEqual([]);
  const changed = { ...initial, month1: "8", module_mismatch_fraction: "2.5" };
  expect(lossFormPatch(initial, changed)).toEqual({ overrides: { soiling: { monthly_fractions: [.08, ...Array(11).fill(.03)] }, module_mismatch_fraction: .025 } });
  expect(lossFormErrors({ ...initial, annual_degradation_fraction: "50", operating_year: "5" })).toContain("annual_degradation_fraction");
  expect(lossFormErrors({ ...initial, "transformer.enabled": "true" })).toContain("transformer.copper_fraction");
  for (const bad of ["NaN", "Infinity", "", "-1", "101"]) expect(lossFormErrors({ ...initial, month1: bad })).toContain("month1");
  expect(lossFormPatch({ ...initial, module_mismatch_fraction: "2" }, initial)).toEqual({ overrides: { module_mismatch_fraction: null } });
});
it("selected run shows its recorded settings and legacy runs never substitute the project's defaults", async () => {
  await i18n.changeLanguage("en");
  const run = { simulation_run_id: "recorded", resolved_loss_settings: { ...settings, status: "edited", overrides: { soiling: { annual_fraction: .08 } }, values: { ...settings.values, soiling: { monthly_fractions: Array(12).fill(.08) } } } } as SimulationRunRecord;
  const html = renderToStaticMarkup(createElement(RunLossSettings, { run }));
  expect(html).toContain("Edited"); expect(html).toContain("frozen-run-hash"); expect(html).toContain("8");
  const legacy = renderToStaticMarkup(createElement(RunLossSettings, { run: { simulation_run_id: "old" } as SimulationRunRecord }));
  expect(legacy).toContain("Legacy settings (recorded)"); expect(legacy).not.toContain("frozen-run-hash");
});
it("waterfall includes the optical bridge, signed operating gain, new electrical and plant stages and closes", () => {
  const losses = [["soiling",100], ["module_operating_effects",-10],["lid",20],["module_quality",-5],["module_mismatch",10],["string_mismatch",5],["degradation",10],["dc_wiring",15],["inverter_conversion",30],["ac_wiring",5],["transformer_iron",2],["transformer_copper",3],["unavailability",5]] as const;
  let upstream = 1000;
  const loss_summary = losses.map(([loss_type, lost_energy_wh]) => { const reference_energy_wh = upstream; upstream -= lost_energy_wh; return { loss_type, lost_energy_wh, reference_energy_wh, loss_fraction: lost_energy_wh / reference_energy_wh, method: "test", notes: "signed", stage: "test" }; });
  const run = { simulation_run_id: "s18a", summary_result: { total_energy_wh: upstream, loss_summary, monthly_energy: [], period_start_time: "2025-01-01", period_end_time: "2025-01-02" } } as unknown as SimulationRunRecord;
  const model = buildResultModel(fixture.views.before as unknown as ProjectView, run, { authority: "ENGINE", hourlyAcKw: null });
  expect(model.losses.at(-1)?.remainingKwh).toBeCloseTo(upstream/1000, 14);
  expect(model.losses[0].label).toBe("soiling"); expect(model.losses[1].lossKwh).toBe(-.01);
});
it("new loss vocabulary and defaults identifiers contain no third-party branding in either language", async () => {
  for (const language of ["en", "id"]) { await i18n.changeLanguage(language); const texts = LOSS_FIELDS.map((key) => i18n.t(`losses.${key.replaceAll(".", "_")}`)).join(" "); expect(texts).not.toMatch(/pvsyst/i); }
});

it("demo settings round-trip and reset preserve the same versioned shape without pretending to run loss physics", async () => {
  const { mockApi, setDemoLatency } = await import("../../src/demo/mockApi"); setDemoLatency(0);
  try {
    const defaults = await mockApi.simulationDefaults(); expect(defaults.loss_settings?.values).toEqual({ ...settings.values, lid_fraction: null });
    const edited = await mockApi.updateLosses("demo", { overrides: { soiling: { annual_fraction: .08 } } });
    expect(edited.resolved_loss_settings?.status).toBe("edited");
    expect(edited.resolved_loss_settings?.values.soiling.monthly_fractions).toEqual(Array(12).fill(.08));
    expect(edited.resolved_loss_settings?.sources["soiling.monthly_fractions"]).toBe("user");
    const reset = await mockApi.updateLosses("demo", { reset_to_recommended_defaults: true });
    expect(reset.resolved_loss_settings?.status).toBe("recommended_defaults"); expect(reset.bundle.loss_settings?.overrides).toEqual({});
  } finally { setDemoLatency(1); }
});


it("form edits persist through the adapter, reset uses the explicit action, and busy buttons cannot send", async () => {
  const render = () => { harness.cursor = 0; return tree(LossesPanel({ defaults: settings })); };
  const field = render().find((n) => n.props.label === "Soiling month 1 (%)")!;
  const input = tree(field.props.children).find((n) => n.type === "input")!;
  input.props.onChange({ target: { value: "8" } });
  const save = render().find((n) => n.props.children === "Save losses")!;
  expect(save.props.disabled).toBe(false); save.props.onClick(); await Promise.resolve(); await Promise.resolve();
  expect(harness.update).toHaveBeenCalledWith(harness.view!.bundle.project.project_id, { overrides: { soiling: { monthly_fractions: [.08, ...Array(11).fill(.03)] } } });
  await vi.waitFor(() => expect(harness.dispatch).toHaveBeenCalledWith({ type: "setView", view: harness.view }));
  harness.view!.resolved_loss_settings = { ...settings, status: "edited" }; harness.cursor = 0; harness.slots = [];
  const reset = render().find((n) => n.props.children === "Reset to recommended defaults")!;
  expect(reset.props.disabled).toBe(false); reset.props.onClick(); await Promise.resolve();
  expect(harness.update).toHaveBeenLastCalledWith(harness.view!.bundle.project.project_id, { reset_to_recommended_defaults: true });
  harness.busy = true;
  for (const node of render().filter((n) => ["Save losses", "Reset to recommended defaults"].includes(n.props.children))) expect(node.props.disabled).toBe(true);
});


it("only detailed run settings describe post-IV dispersion", () => {
  const run = { simulation_run_id: "standard", resolved_loss_settings: { ...settings, method: "manufacturing_dispersion_scalar" } } as SimulationRunRecord;
  expect(renderToStaticMarkup(createElement(RunLossSettings, { run }))).not.toContain("after detailed IV selection");
  run.resolved_loss_settings!.method = "detailed_iv_plus_dispersion_scalar";
  expect(renderToStaticMarkup(createElement(RunLossSettings, { run }))).toContain("after detailed IV selection");
});


it("signed waterfall gains float between the before/after totals rather than below zero", async () => {
  const { echarts } = await import("../../src/results/echarts");
  const { waterfallOption } = await import("../../src/results/chartOptions");
  const palette = { text: "black", muted: "gray", grid: "gray", axis: "gray", bg: "white", series: ["green"], loss: "red", gain: "green", heat: [], font: "sans-serif" };
  const option = waterfallOption(palette, { start: { label: "reference", value: 100 }, losses: [{ label: "operating gain", value: -10 }], end: { label: "AC", value: 110 }, unit: "kWh", aria: "Signed waterfall" });
  const chart = echarts.init(null, null, { renderer: "svg", ssr: true, width: 800, height: 400 });
  try {
    chart.setOption(option);
    const data = chart.getModel().getSeriesByIndex(1).getData();
    const layout = data.getItemLayout(1);
    const before = chart.convertToPixel({ seriesIndex: 1 }, [1, 100]) as number[];
    const after = chart.convertToPixel({ seriesIndex: 1 }, [1, 110]) as number[];
    expect(Math.min(layout.y, layout.y + layout.height)).toBeCloseTo(Math.min(before[1], after[1]), 9);
    expect(Math.max(layout.y, layout.y + layout.height)).toBeCloseTo(Math.max(before[1], after[1]), 9);
    expect(data.getItemVisual(1, "style").fill).toBe(palette.gain);
  } finally { chart.dispose(); }
});
