import { beforeEach, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
import { SystemsPanel } from "../../src/panels/SystemsPanel";
import { demoSystemsOverview, mockApi, setDemoLatency } from "../../src/demo/mockApi";
import i18n from "../../src/i18n";
import type { InverterSizing, ProjectView, SystemsOverview } from "../../src/types";

type Bag = { states: unknown[]; cursor: number; effectCursor: number;
  effects: Array<{ deps?: readonly unknown[]; cleanup?: () => void }>; pending: Array<() => void> };
const ui = vi.hoisted(() => ({ current: null as Bag | null, view: null as ProjectView | null,
  fetchOverview: vi.fn(), fetchSizing: vi.fn(), topology: vi.fn(), command: vi.fn(), toast: vi.fn() }));
vi.mock("react", async load => ({ ...await load<typeof import("react")>(),
  useState: (initial: unknown) => {
    const bag = ui.current!, index = bag.cursor++;
    if (!(index in bag.states)) bag.states[index] = typeof initial === "function" ? initial() : initial;
    return [bag.states[index], (next: unknown) => { bag.states[index] = typeof next === "function" ? next(bag.states[index]) : next; }];
  },
  useEffect: (effect: () => void | (() => void), deps?: readonly unknown[]) => {
    const bag = ui.current!, index = bag.effectCursor++, previous = bag.effects[index];
    if (!previous || !deps || deps.length !== previous.deps?.length || deps.some((d, i) => !Object.is(d, previous.deps?.[i]))) {
      previous?.cleanup?.();
      const slot = { deps, cleanup: undefined as (() => void) | undefined }; bag.effects[index] = slot;
      bag.pending.push(() => { const cleanup = effect(); if (typeof cleanup === "function") slot.cleanup = cleanup; });
    }
  }
}));
vi.mock("../../src/client", () => ({ DEMO: true, engine: {
  systemsOverview: (...args: unknown[]) => ui.fetchOverview(...args), inverterSizing: (...args: unknown[]) => ui.fetchSizing(...args),
  topologyCommand: (...args: unknown[]) => ui.topology(...args)
} }));
vi.mock("../../src/state/history", () => ({ engineCommand: (...args: unknown[]) => ui.command(...args) }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: i18n.t.bind(i18n) }), initReactI18next: { type: "3rdParty", init() {} } }));
vi.mock("../../src/state/store", async load => ({ ...await load<typeof import("../../src/state/store")>(),
  useStore: () => ({ state: { view: ui.view, busy: null }, toast: ui.toast, dispatch: vi.fn(), run: vi.fn() }),
  useForm: (_key: string, initial: unknown) => [initial, vi.fn()]
}));

type Inverter = ProjectView["bundle"]["electrical_design"]["inverter_instances"][number];
type Node = ReactElement<{ children?: unknown; label?: string; checked?: boolean; disabled?: boolean;
  inv?: Inverter; overview?: SystemsOverview; onChange?: (checked: boolean) => void; onClick?: () => void }>;
function nodes(value: unknown): Node[] {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!isValidElement(value)) return [];
  const node = value as Node;
  return [node, ...nodes(node.props.children)];
}
const bag = (): Bag => ({ states: [], cursor: 0, effectCursor: 0, effects: [], pending: [] });
function render(state: Bag, component: () => unknown): Node[] {
  const draw = () => { ui.current = state; state.cursor = 0; state.effectCursor = 0; return nodes(component()); };
  draw(); for (const effect of state.pending.splice(0)) effect();
  return draw();
}
let overview: SystemsOverview, drawCard: () => Node[], resolveSizing: (value: InverterSizing) => void;
const sizing = (): InverterSizing => ({ pv_field_ids: ["field-a", "field-b"], area_kwp: 20, ac_kw: 30, dc_ac_ratio: 2/3,
  distance_warnings: [], reasons: [], mppts: [], string_length_min: 1, string_length_max: 20 } as unknown as InverterSizing);
const roof = (tree: Node[], name: string) => tree.find(n => n.props.label === name)!;
const save = (tree: Node[]) => tree.find(n => n.props.children === "Save area")!;
const apply = (tree: Node[]) => tree.find(n => n.props.children === "Apply MPPT layout")!;

beforeEach(async () => {
  setDemoLatency(0); await i18n.changeLanguage("en");
  ui.view = structuredClone(await mockApi.project("demo-project"));
  const view = ui.view;
  view.bundle.scene.surfaces = [0, 30].map((x, i) => ({ surface_id: `roof-${i}`, name: `Roof ${i+1}`, group_id: null,
    surface_type: "flat_roof", boundary_2d: { vertices: [[x, 0], [x+10, 0], [x+10, 5], [x, 5]], holes: [] } }));
  view.bundle.scene.pv_fields = ["field-a", "field-b"].map((id, i) => ({ pv_field_id: id, name: id, support_surface_id: `roof-${i}`,
    module_definition_revision_id: view.catalog.modules[0].revision_id, tilt_deg: 10, azimuth_deg: 0 }));
  view.bundle.scene.module_instances = [];
  view.bundle.scene.buildings = [];
  view.bundle.electrical_design.inverter_instances = [view.bundle.electrical_design.inverter_instances[0]];
  view.bundle.electrical_design.inverter_instances[0].paired_pv_field_ids = ["field-a", "field-b"];
  overview = demoSystemsOverview(view);
  ui.fetchOverview.mockReset().mockResolvedValue(overview);
  ui.fetchSizing.mockReset().mockImplementation(() => new Promise<InverterSizing>(resolve => { resolveSizing = resolve; }));
  ui.topology.mockReset(); ui.toast.mockReset();
  ui.command.mockReset().mockImplementation(async (_label: string, action: () => Promise<ProjectView>) => { ui.view = await action(); return ui.view; });
  const root = bag(); render(root, () => SystemsPanel()); await Promise.resolve();
  const wrapper = render(root, () => SystemsPanel()).find(n => n.props.overview)!;
  const Wrapper = wrapper.type as (props: { overview: SystemsOverview }) => ReactElement;
  const card = render(bag(), () => Wrapper({ overview })).find(n => n.props.inv)!;
  const Card = card.type as (props: { inv: Inverter; overview: SystemsOverview }) => ReactElement;
  const cardState = bag();
  drawCard = () => render(cardState, () => Card({ inv: ui.view!.bundle.electrical_design.inverter_instances[0], overview }));
});

it("keeps an unsaved untick and enabled Save through a late sizing response, then reflects a successful Save", async () => {
  const initial = drawCard(); expect(roof(initial, "Roof 2").props.checked).toBe(true);
  expect(apply(initial).props.disabled).toBe(true);
  roof(initial, "Roof 2").props.onChange!(false);
  resolveSizing(sizing()); await Promise.resolve();
  const draft = drawCard();
  expect(roof(draft, "Roof 2").props.checked).toBe(false);
  expect(save(draft).props.disabled).toBe(false);
  const stored = structuredClone(ui.view!);
  stored.bundle.electrical_design.inverter_instances[0].paired_pv_field_ids = ["field-a"];
  stored.bundle.electrical_design.electrical_revision_id += "-saved";
  ui.topology.mockResolvedValue(stored);
  save(draft).props.onClick!(); await ui.command.mock.results.at(-1)!.value;
  expect(ui.topology).toHaveBeenCalledWith(stored.bundle.project.project_id, { command_type: "set_inverter_pairing",
    parameters: { inverter_instance_id: stored.bundle.electrical_design.inverter_instances[0].inverter_instance_id, pv_field_ids: ["field-a"] } });
  const saved = drawCard();
  expect(roof(saved, "Roof 1").props.checked).toBe(true);
  expect(roof(saved, "Roof 2").props.checked).toBe(false);
  expect(save(saved).props.disabled).toBe(true);
  expect(apply(saved).props.disabled).toBe(true);
});

it("resets the area draft when the stored pairing changes", () => {
  const initial = drawCard(); roof(initial, "Roof 2").props.onChange!(false);
  ui.view!.bundle.electrical_design.inverter_instances[0].paired_pv_field_ids = ["field-b"];
  const changed = drawCard();
  expect(roof(changed, "Roof 1").props.checked).toBe(false);
  expect(roof(changed, "Roof 2").props.checked).toBe(true);
  expect(save(changed).props.disabled).toBe(true);
});

it("reflects the stored automatic all-fields pairing after saving an empty selection", async () => {
  drawCard(); resolveSizing(sizing()); await Promise.resolve();
  roof(drawCard(), "Roof 1").props.onChange!(false);
  roof(drawCard(), "Roof 2").props.onChange!(false);
  const stored = structuredClone(ui.view!);
  // The canonical editor removes an empty pairing: unpaired means all fields.
  delete stored.bundle.electrical_design.inverter_instances[0].paired_pv_field_ids;
  stored.bundle.electrical_design.electrical_revision_id += "-unpaired";
  ui.topology.mockResolvedValue(stored);
  save(drawCard()).props.onClick!(); await ui.command.mock.results.at(-1)!.value;
  const saved = drawCard();
  expect(roof(saved, "Roof 1").props.checked).toBe(true);
  expect(roof(saved, "Roof 2").props.checked).toBe(true);
  expect(save(saved).props.disabled).toBe(true);
});
