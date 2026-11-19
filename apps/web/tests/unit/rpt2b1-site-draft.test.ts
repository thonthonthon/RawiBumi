import { beforeEach, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
import i18n from "../../src/i18n";
import fixture from "./s7b-engine-fixture.json";
import type { ProjectView } from "../../src/types";
import { SitePanel } from "../../src/panels/SitePanel";

const ui = vi.hoisted(() => ({ view: null as ProjectView | null, states: [] as unknown[], cursor: 0,
  deps: [] as (readonly unknown[])[], effectCursor: 0, pending: [] as (() => void)[] }));
vi.mock("react", async load => ({ ...await load<typeof import("react")>(),
  useState: (initial: unknown) => {
    const index = ui.cursor++;
    if (!(index in ui.states)) ui.states[index] = initial;
    return [ui.states[index], (next: unknown) => { ui.states[index] = next; }];
  },
  useEffect: (effect: () => void, deps: readonly unknown[]) => {
    const index = ui.effectCursor++, previous = ui.deps[index];
    if (!previous || deps.some((value, i) => !Object.is(value, previous[i]))) {
      ui.deps[index] = deps; ui.pending.push(effect);
    }
  }
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: i18n.t.bind(i18n) }),
  initReactI18next: { type: "3rdParty", init() {} } }));
vi.mock("../../src/state/store", () => ({ useStore: () => ({ state: { view: ui.view, busy: null }, dispatch: vi.fn(), run: vi.fn() }) }));

type Node = ReactElement<{ children?: unknown; label?: string; value?: string;
  onChange?: (event: { target: { value: string } }) => void; onClick?: () => void }>;
function nodes(value: unknown): Node[] {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!isValidElement(value)) return [];
  const node = value as Node; return [node, ...nodes(node.props.children)];
}
function render() {
  const draw = () => { ui.cursor = 0; ui.effectCursor = 0; return nodes(SitePanel()); };
  draw(); for (const effect of ui.pending.splice(0)) effect();
  return draw();
}
const latitude = (tree: Node[]) => nodes(tree.find(node => node.props.label === "Latitude")!.props.children).find(node => node.type === "input")!;
const confirmation = (tree: Node[]) => tree.find(node => node.props.label === "Clear pinned weather?");

beforeEach(async () => {
  await i18n.changeLanguage("en"); ui.view = structuredClone(fixture.views.before) as unknown as ProjectView;
  ui.view.bundle.weather_selection = { revision_id: "synthetic-weather" } as ProjectView["bundle"]["weather_selection"];
  ui.states = []; ui.deps = []; ui.pending = [];
});

it.each(["address", "installation"] as const)("keeps the site draft and confirmation after a late %s save, but resets for a stored coordinate change", field => {
  latitude(render()).props.onChange!({ target: { value: "-7.25" } });
  render().find(node => node.props.children === "Apply")!.props.onClick!();
  expect(confirmation(render())).toBeDefined();
  const updated = structuredClone(ui.view!);
  if (field === "address") updated.bundle.project.site.address = { text: "Synthetic address", source: "user", lat: -6.2, lon: 106.8, attribution: null, updatedAt: "2026-11-16T00:00:00Z" };
  else updated.bundle.project.site.installation = { installationType: "hybrid", bessEnergyKwh: 10, bessPowerKw: 2 };
  ui.view = updated;
  const late = render();
  expect(latitude(late).props.value).toBe("-7.25");
  expect(confirmation(late)).toBeDefined();
  ui.view = structuredClone(updated); ui.view.bundle.project.site.latitude_deg = -8;
  const changed = render();
  expect(latitude(changed).props.value).toBe("-8");
  expect(confirmation(changed)).toBeUndefined();
});
