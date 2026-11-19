import { beforeEach, expect, it, vi } from "vitest";
import { createElement, isValidElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import i18n from "../../src/i18n";
import fixture from "./s7b-engine-fixture.json";
import type { SimulationDefaults } from "../../src/types";

const h = vi.hoisted(() => ({ slots: [] as unknown[], cursor: 0, effects: [] as Array<() => unknown>, keys: [] as string[], defaults: vi.fn() }));
vi.mock("react", async (load) => ({ ...await load<typeof import("react")>(),
  useState: (initial: unknown) => { const i = h.cursor++; if (!(i in h.slots)) h.slots[i] = initial; return [h.slots[i], (v: unknown) => { h.slots[i] = v; }]; },
  useEffect: (effect: () => unknown) => { h.effects.push(effect); }
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: i18n.t.bind(i18n) }), initReactI18next: { type: "3rdParty", init() {} } }));
vi.mock("../../src/client", () => ({ engine: { simulationDefaults: h.defaults, weatherSources: async () => [] } }));
vi.mock("../../src/state/store", () => ({ useStore: () => ({ state: { view: fixture.views.before }, dispatch: vi.fn(), run: vi.fn(), toast: vi.fn() }),
  useForm: (key: string, initial: unknown) => { h.keys.push(key); return [initial, vi.fn()]; }
}));
import { MeteoPanel } from "../../src/panels/MeteoPanel";
import { AppliedDefaults, LossesGridPanel } from "../../src/panels/LossesGridPanel";
import { LossesPanel } from "../../src/panels/LossesPanel";
import { OpticsThermalPanel } from "../../src/panels/OpticsThermalPanel";
import { Section, Segmented, NotWired } from "../../src/ui/kit";

const values: SimulationDefaults = { albedo: 0.37, thermal: { u_c_w_m2k: 27, u_v_w_m2k_per_ms: 2.5 },
  losses: { module_mismatch_loss_fraction: 0.04, string_mismatch_loss_fraction: 0.07, dc_array_resistance_ohm: 0.8 },
  simulation_timestep_seconds: 3600, module_quality: { source: "pinned_module_definition", fallback_loss_fraction: 0 },
  not_modelled: ["soiling", "lid", "ac_ohmic", "availability", "degradation"] };
function tree(value: unknown): ReactElement<any>[] {
  if (Array.isArray(value)) return value.flatMap(tree);
  if (!isValidElement(value)) return [];
  const node = value as ReactElement<any>; return [node, ...tree(node.props.children)];
}
function render(panel = () => LossesGridPanel()) { h.cursor = 0; h.effects = []; return tree(panel()); }
beforeEach(async () => { h.slots = []; h.keys = []; h.defaults.mockReset().mockResolvedValue(values); await i18n.changeLanguage("en"); });
it("keeps pinned module-quality information read-only beside the editable optics form", () => {
  const html = renderToStaticMarkup(createElement(AppliedDefaults, { values }));
  for (const text of ["Applied by the engine",
    "Module quality: from the pinned module definition (default 0 %; negative = gain)"]) expect(html).toContain(text);
  expect(html).not.toMatch(/<input|<select|<textarea/);
});
it("loads defaults through the adapter and does not keep session-only loss or timestep forms", async () => {
  render(); for (const effect of h.effects) effect(); await Promise.resolve();
  const nodes = render(); const applied = nodes.find((n) => n.type === AppliedDefaults)!;
  expect(h.defaults).toHaveBeenCalledTimes(1); expect(applied.props.values).toEqual(values);
  expect(h.keys).not.toContain("meteo.losses"); expect(h.keys).not.toContain("meteo.timestep");
  const section = nodes.find((n) => n.type === Section && n.props.title === "Losses")!;
  expect(tree(section.props.children).some((n) => n.type === "input")).toBe(false);
  expect(section.props.aside).toBeUndefined();
  expect(tree(section.props.children).some((n) => n.type === LossesPanel)).toBe(true);
  expect(tree(nodes.find((n) => n.type === Section && n.props.title === "Optics & thermal")!.props.children).some((n) => n.type === OpticsThermalPanel)).toBe(true);
});
it("offers only 60 min and visibly marks the three unsupported sub-hourly choices", () => {
  const nodes = render(() => MeteoPanel({ onImport: vi.fn() })); const timestep = nodes.find((n) => n.type === Segmented)!;
  expect(timestep.props.value).toBe("60");
  expect(timestep.props.options).toEqual(["1", "5", "15"].map((value) => ({ value, label: value, disabled: true })).concat([{ value: "60", label: "60 min (engine)", disabled: false }]));
  expect(nodes.some((n) => n.type === NotWired && n.props.id === "subHourlyTimestep")).toBe(true);
  expect(renderToStaticMarkup(createElement(Segmented, timestep.props)).match(/ disabled=""/g)).toHaveLength(3);
});
it("a failed defaults fetch shows unavailable, without any invented loss values", async () => {
  h.defaults.mockRejectedValue(new Error("Offline")); render(); for (const effect of h.effects) effect();
  await Promise.resolve(); await Promise.resolve(); const nodes = render();
  expect(nodes.some((n) => n.type === AppliedDefaults)).toBe(false);
  expect(nodes.some((n) => n.props.role === "status" && n.props.children === "Engine defaults unavailable.")).toBe(true);
});
