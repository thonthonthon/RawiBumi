import { beforeEach, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement, createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { LossesPanel, lossDraft, lossFormErrors, lossFormPatch, moduleLid } from "../../src/panels/LossesPanel";
import type { ProjectView, ResolvedLossSettings } from "../../src/types";
import fixture from "./s7b-engine-fixture.json";
import i18n from "../../src/i18n";

const harness = vi.hoisted(() => ({ view: null as ProjectView | null, update: vi.fn(), dispatch: vi.fn() }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: i18n.t.bind(i18n) }), initReactI18next: { type: "3rdParty", init() {} } }));
vi.mock("../../src/client", () => ({ engine: { updateLosses: harness.update } }));
vi.mock("../../src/state/store", () => ({ useStore: () => ({ state: { view: harness.view, busy: false }, dispatch: harness.dispatch, run: async (_label: string, operation: () => Promise<unknown>) => operation() }) }));
vi.mock("react", async (load) => ({ ...await load<typeof import("react")>(), useState: (value: unknown) => [typeof value === "function" ? value() : value, vi.fn()], useEffect: () => undefined }));
function nodes(value: unknown): ReactElement<any>[] {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!isValidElement(value)) return [];
  const n = value as ReactElement<any>; return [n, ...nodes(n.props.children)];
}
const settings: ResolvedLossSettings = {
  schema_name: "LossSettings", schema_version: "0.1", defaults_id: "recommended_defaults.v2", overrides: {}, status: "recommended_defaults", settings_sha256: "test", sources: {},
  values: { soiling: { monthly_fractions: Array(12).fill(.03) }, lid_fraction: null, module_mismatch_fraction: null, string_mismatch_fraction: null, dc_wiring_stc_fraction: .015, ac_wiring_nominal_fraction: 0, annual_degradation_fraction: .004, operating_year: 1, degradation_fraction: .002, transformer: { enabled: false, reference_power_w: null, iron_fraction: .001, copper_fraction: null }, unavailability_fraction: 0 },
};
beforeEach(async () => {
  await i18n.changeLanguage("en");
  harness.view = { ...structuredClone(fixture.views.before), resolved_loss_settings: structuredClone(settings) } as unknown as ProjectView;
  harness.view.bundle.pinned_components = { modules: { file: { model: "File", technology: "perc", quality: { lid_loss_fraction: .02 } }, generic: { model: "Generic", technology: "topcon" } } };
  harness.update.mockReset().mockResolvedValue(harness.view); harness.dispatch.mockReset();
});
it("shows module-file, generic and user labels", () => {
  const html = () => renderToStaticMarkup(createElement(LossesPanel));
  expect(html()).toContain("From module file (2 %)");
  expect(html()).toContain("Generic for topcon (0.5 %) — check the datasheet");
  harness.view!.resolved_loss_settings!.overrides.lid_fraction = .07;
  harness.view!.resolved_loss_settings!.values.lid_fraction = .07;
  expect(html()).toContain("User value (7 %)");
});
it("typing overrides and clearing restores the automatic input", () => {
  const initial = lossDraft(settings);
  expect(initial.lid_fraction).toBe(""); expect(lossFormErrors(initial)).toEqual([]);
  const edited = { ...initial, lid_fraction: "2.5" };
  expect(lossFormPatch(initial, edited)).toEqual({ overrides: { lid_fraction: .025 } });
  expect(lossFormPatch(edited, initial)).toEqual({ overrides: { lid_fraction: null } });
  expect(moduleLid(settings, { technology: "hjt" })).toEqual({ fraction: .005, source: "generic_default" });
  expect(moduleLid(settings, { technology: "cdte", quality: { lid_loss_fraction: NaN } }).fraction).toBe(0);
  expect(moduleLid(settings, { technology: "unknown" }).fraction).toBe(.015);
});
it("v1 switch sends one save, preserves overrides, and refreshes the view", async () => {
  harness.view!.resolved_loss_settings = { ...settings, defaults_id: "recommended_defaults.v1", overrides: { lid_fraction: .03 }, values: { ...settings.values, lid_fraction: .03 } };
  const html = renderToStaticMarkup(createElement(LossesPanel));
  expect(html).toContain("Earlier defaults: LID 0 %.");
  const button = nodes(LossesPanel({})).find((n) => n.props.children === "Use the current defaults")!;
  button.props.onClick();
  await vi.waitFor(() => expect(harness.update).toHaveBeenCalledExactlyOnceWith(harness.view!.bundle.project.project_id, { defaults_id: "recommended_defaults.v2", overrides: {} }));
  await vi.waitFor(() => expect(harness.dispatch).toHaveBeenCalledWith({ type: "setView", view: harness.view }));
});
it("demo defaults and override/clear use v2", async () => {
  const { mockApi, setDemoLatency } = await import("../../src/demo/mockApi"); setDemoLatency(0);
  try {
    expect((await mockApi.simulationDefaults()).loss_settings?.defaults_id).toBe("recommended_defaults.v2");
    const edited = await mockApi.updateLosses("demo", { overrides: { lid_fraction: .02 } });
    expect(edited.resolved_loss_settings?.values.lid_fraction).toBe(.02);
    const cleared = await mockApi.updateLosses("demo", { overrides: { lid_fraction: null } });
    expect(cleared.resolved_loss_settings?.values.lid_fraction).toBeNull();
    expect(cleared.bundle.loss_settings?.defaults_id).toBe("recommended_defaults.v2");
  } finally { setDemoLatency(1); }
});
