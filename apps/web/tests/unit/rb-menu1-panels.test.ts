import { expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
import fixture from "./s7b-engine-fixture.json";

vi.mock("react", async load => ({
  ...await load<typeof import("react")>(),
  useState: (initial: unknown) => [initial, vi.fn()],
  useEffect: vi.fn(),
  useMemo: (calculate: () => unknown) => calculate()
}));
vi.mock("../../src/state/store", () => ({
  useStore: () => ({ state: { view: fixture.views.before, entities: [], strings: [], modules: [], findings: [] }, dispatch: vi.fn(), run: vi.fn(), toast: vi.fn() }),
  useForm: (_key: string, initial: unknown) => [initial, vi.fn()]
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: i18n.t.bind(i18n) }), initReactI18next: { type: "3rdParty", init() {} } }));
vi.mock("../../src/state/derived", () => ({ electricalIssues: () => [] }));

import i18n from "../../src/i18n";
import { MeteoPanel } from "../../src/panels/MeteoPanel";
import { LossesGridPanel } from "../../src/panels/LossesGridPanel";
import { SimulatePanel } from "../../src/panels/SimulatePanel";
import { ShadingAccuracyPanel } from "../../src/panels/ShadingAccuracyPanel";
import { Section } from "../../src/ui/kit";

function tree(value: unknown): ReactElement<any>[] {
  if (Array.isArray(value)) return value.flatMap(tree);
  if (!isValidElement(value)) return [];
  const node = value as ReactElement<any>;
  return [node, ...tree(node.props.children)];
}

it("RB-MENU1 keeps Weather alone and moves settings, load, export limits and shading together", () => {
  const weather = tree(MeteoPanel({ onImport: vi.fn() }));
  expect(weather.filter(node => node.type === Section).map(node => node.props.title)).toEqual(["Weather"]);
  const losses = tree(LossesGridPanel());
  expect(losses.filter(node => node.type === Section).map(node => node.props.title)).toEqual(["Losses", "Optics & thermal", "Load & zero export"]);
  expect(losses.findIndex(node => node.type === ShadingAccuracyPanel)).toBeLessThan(losses.findIndex(node => node.type === Section && node.props.title === "Load & zero export"));
  const simulate = tree(SimulatePanel());
  expect(simulate.some(node => node.type === ShadingAccuracyPanel)).toBe(false);
  expect(simulate.filter(node => node.type === Section).map(node => node.props.title)).toEqual(["Before you run", "Preflight", "Execution options", "Run history"]);
  // RB-SEC1: losses are the main work; model and grid settings start collapsed.
  expect(losses.filter(node => node.type === Section).map(node => !!node.props.primary)).toEqual([true, false, false]);
});
