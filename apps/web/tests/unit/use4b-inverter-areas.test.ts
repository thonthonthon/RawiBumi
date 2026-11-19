import { beforeEach, describe, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
import { api } from "../../src/api";
import { applyTopologyCommand, orderModules, type TopologyContext } from "../../src/demo/topologyEngine";
import { SystemsPanel, servesFieldIds, inverterSourceOptions, mixesOrientations, invertersForTarget, tableRowLayout } from "../../src/panels/SystemsPanel";
import { formatNotation, parseNotation } from "../../src/electrical/notation";
import { demoSystemsOverview, mockApi, setDemoLatency } from "../../src/demo/mockApi";
import i18n from "../../src/i18n";
import type { SystemsOverview, ProjectView } from "../../src/types";
import type { TopologyCommand } from "../../src/engine/topology";

const panel = vi.hoisted(() => ({ view: null as ProjectView | null, states: [] as unknown[], stateCursor: 0, effectCursor: 0,
  effects: [] as Array<{ deps?: readonly unknown[]; cleanup?: () => void }>, pending: [] as Array<() => void>,
  fetchOverview: vi.fn(), updateProject: vi.fn(), dispatch: vi.fn(), toast: vi.fn(), run: vi.fn() }));
vi.mock("react", async load => ({ ...await load<typeof import("react")>(),
  useState: (initial: unknown) => {
    const i = panel.stateCursor++;
    if (!(i in panel.states)) panel.states[i] = typeof initial === "function" ? initial() : initial;
    return [panel.states[i], (value: unknown) => { panel.states[i] = value; }];
  },
  useEffect: (effect: () => void | (() => void), deps?: readonly unknown[]) => {
    const i = panel.effectCursor++, previous = panel.effects[i];
    if (!previous || !deps || deps.length !== previous.deps?.length || deps.some((d, k) => !Object.is(d, previous.deps?.[k]))) {
      previous?.cleanup?.();
      const slot = { deps, cleanup: undefined as (() => void) | undefined }; panel.effects[i] = slot;
      panel.pending.push(() => { const cleanup = effect(); if (typeof cleanup === "function") slot.cleanup = cleanup; });
    }
  }
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: i18n.t.bind(i18n) }), initReactI18next: { type: "3rdParty", init() {} } }));
vi.mock("../../src/client", () => ({ engine: { systemsOverview: (...args: unknown[]) => panel.fetchOverview(...args), updateProject: (...args: unknown[]) => panel.updateProject(...args) } }));
vi.mock("../../src/state/store", async load => ({ ...await load<typeof import("../../src/state/store")>(),
  useStore: () => ({ state: { view: panel.view, busy: null }, dispatch: panel.dispatch, toast: panel.toast, run: panel.run }) }));

type PanelNode = ReactElement<{children?: unknown; label?: string; value?: string; type?: string;
  onChange?: (e: { currentTarget: { value: string } }) => void; onClick?: () => void}>;
function nodes(value: unknown): PanelNode[] {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!isValidElement(value)) return [];
  const node = value as PanelNode;
  return [node, ...nodes(node.props.children)];
}
function renderPanel(): PanelNode[] {
  const render = () => { panel.stateCursor = 0; panel.effectCursor = 0; return nodes(SystemsPanel()); };
  render(); for (const effect of panel.pending.splice(0)) effect();
  return render();
}
function thresholdInput(tree: PanelNode[]) {
  return nodes(tree.find(n => n.props.label === "Distance warning threshold")!.props.children).find(n => n.type === "input")!;
}

function context(): TopologyContext {
  return { inverters: [{ inverter_instance_id: "inv", inverter_definition_revision_id: "inv-demo-30k", name: "Inverter", enabled: true, mppt_instance_ids: ["p1", "p2"] }],
    strings: [{ string_id: "kept", target_mppt_instance_id: "p1", enabled: true, module_instance_ids: ["a0", "a1", "a2", "a3"] },
      { string_id: "free", target_mppt_instance_id: null, enabled: false, module_instance_ids: ["b0", "b1", "b2", "b3"] }],
    modules: new Map(["a", "b"].flatMap((f, x) => Array.from({length: 12}, (_, i) => [`${f}${i}`, { id: `${f}${i}`, fieldId: f, centre: [x * 20 + i, 0] as [number, number], enabled: true, slot: null }] as const))),
    fields: new Map([['a', {module: 'mod-demo-550', tilt: 10, azimuth: 0}], ['b', {module: 'mod-demo-550', tilt: 25, azimuth: 0}]]), tables: [] };
}
const command = (sources?: (string[] | null)[] | null, layout = [[4], [4, 4]]): TopologyCommand => ({ command_type: "apply_mppt_layout", parameters: { inverter_instance_id: "inv", layout, ...(sources === undefined ? {} : { sources }) } });
async function overview(): Promise<SystemsOverview> {
  const view = structuredClone(await mockApi.project("demo-project"));
  view.bundle.scene.buildings = [{ building_id: "main", name: "Main" }];
  view.bundle.scene.surfaces = [0, 20].map((x, i) => ({ surface_id: `s${i}`, name: `Roof ${i}`, group_id: i === 0 ? "main" : null,
    surface_type: "flat_roof", base_elevation_m: 0, boundary_2d: { vertices: [[x, 0], [x + 10, 0], [x + 10, 5], [x, 5]], holes: [] } }));
  view.bundle.scene.pv_fields = [10, 25].map((tilt, i) => ({ pv_field_id: `f${i}`, name: `PV ${i}`, support_surface_id: `s${i}`,
    module_definition_revision_id: view.catalog.modules[0].revision_id, row_count: 1, modules_per_row: 1, orientation: "portrait", azimuth_deg: 0, tilt_deg: tilt }));
  view.bundle.scene.module_instances = [0, 1].map(i => ({ module_instance_id: `m${i}`, pv_field_id: `f${i}`, module_definition_revision_id: view.catalog.modules[0].revision_id, enabled: true }));
  return demoSystemsOverview(view);
}
setDemoLatency(0);
describe("Systems threshold input", () => {
  beforeEach(async () => {
    panel.states = []; panel.effects = []; panel.pending = [];
    panel.view = structuredClone(await mockApi.project("demo-project"));
    delete panel.view.bundle.project.distance_warning_m;
    panel.fetchOverview.mockReset(); panel.updateProject.mockReset(); panel.dispatch.mockReset(); panel.toast.mockReset();
    panel.run.mockReset().mockImplementation((_label: string, op: () => Promise<unknown>) => op());
    panel.dispatch.mockImplementation(action => { if (action.type === "setView") panel.view = action.view; });
    await i18n.changeLanguage("en");
  });
  it("keeps a typed threshold when an overview refresh arrives, and saves that value", async () => {
    let refresh!: (value: SystemsOverview) => void;
    panel.fetchOverview.mockReturnValueOnce(new Promise(() => {}));
    const initial = renderPanel(); expect(thresholdInput(initial).props.value).toBe("50");
    thresholdInput(initial).props.onChange!({ currentTarget: { value: "100" } });
    panel.view!.bundle.scene.revision_id += "-renamed";
    panel.fetchOverview.mockReturnValueOnce(new Promise<SystemsOverview>(resolve => { refresh = resolve; }));
    renderPanel(); refresh(await overview()); await Promise.resolve();
    const updated = renderPanel(); expect(thresholdInput(updated).props.value).toBe("100");
    panel.updateProject.mockResolvedValue(panel.view);
    panel.fetchOverview.mockResolvedValue(await overview());
    updated.find(n => n.props.children === "Save threshold")!.props.onClick!();
    await panel.run.mock.results.at(-1)!.value;
    expect(panel.updateProject).toHaveBeenCalledWith(panel.view!.bundle.project.project_id, { distance_warning_m: 100 });
  });
  it("updates the input when the stored project threshold changes", () => {
    panel.view!.bundle.project.distance_warning_m = 60;
    panel.fetchOverview.mockReturnValue(new Promise(() => {}));
    const initial = renderPanel(); expect(thresholdInput(initial).props.value).toBe("60");
    thresholdInput(initial).props.onChange!({ currentTarget: { value: "100" } });
    panel.view!.bundle.project.distance_warning_m = 75;
    expect(thresholdInput(renderPanel()).props.value).toBe("75");
    delete panel.view!.bundle.project.distance_warning_m;
    expect(thresholdInput(renderPanel()).props.value).toBe("50");
  });
});
describe("USE4B inverter areas", () => {
  it("serves resolves building and roof choices to distinct PV field IDs", async () => {
    const o = await overview();
    expect(servesFieldIds(o.buildings, [0, 1, 0])).toEqual(["f0", "f1"]);
    expect(servesFieldIds(o.buildings, [])).toEqual([]);
    expect(inverterSourceOptions(o, ["f1"])).toEqual([{ value: '["f1"]', label: "25.0° / 0.0°", fields: ["f1"] }]);
  });
  it("notation and table lengths/counts round trip without encoding sources", () => {
    const sources = [["a"], ["b"], null];
    const layout = [tableRowLayout(10, 2), tableRowLayout(12, 1), tableRowLayout(0, 0)];
    const text = formatNotation({ mppts: layout });
    expect(text).toBe("10,10 ; 12 ; 0");
    expect(parseNotation(text).layout?.mppts).toEqual(layout);
    expect(sources).toEqual([["a"], ["b"], null]);
  });
  it("warns about a mixed source or an engine orientation mismatch", async () => {
    const o = await overview();
    expect(mixesOrientations(null, ["f0", "f1"], o)).toBe(true);
    expect(mixesOrientations(["f0"], ["f0", "f1"], o)).toBe(false);
    expect(mixesOrientations(["f0"], ["f0", "f1"], o, true)).toBe(true);
    expect(mixesOrientations(null, ["f1"], o)).toBe(false);
    await i18n.changeLanguage("en");
    expect(i18n.t("systems.mixedOrientation")).toContain("RawiBumi simulates it physically");
    await i18n.changeLanguage("id"); expect(i18n.t("systems.mixedOrientation")).toContain("RawiBumi menyimulasikannya secara fisik");
  });
  it("sizes a count to the user target, refusing invalid target values", () => {
    expect(invertersForTarget(500, 100, 1.25)).toBe(4);
    expect(invertersForTarget(501, 100, 1.25)).toBe(5);
    expect(invertersForTarget(0, 100, 1.25)).toBe(0);
    expect(invertersForTarget(100, 100, 0)).toBeNull();
    expect(invertersForTarget(100, 0, 1.25)).toBeNull();
  });
  it("demo preserves absent/all-null allocation bytes with kept, reused and fresh strings", () => {
    const ctx = context(), before = JSON.stringify([...ctx.strings]);
    const absent = applyTopologyCommand(ctx, command());
    expect(JSON.stringify(applyTopologyCommand(ctx, command([null, null])))).toBe(JSON.stringify(absent));
    expect(absent.find(s => s.string_id === "kept")?.target_mppt_instance_id).toBe("p1");
    expect(absent.find(s => s.string_id === "free")?.target_mppt_instance_id).toBe("p2");
    expect(absent).toHaveLength(3); expect(JSON.stringify([...ctx.strings])).toBe(before);
  });
  it("demo allocates roof B first to restricted MPPT 2 but emits strings in MPPT order", () => {
    const base = context();
    const ctx: TopologyContext = {...base, strings: [],
      fields: new Map([['a-B', base.fields.get('b')!], ['z-A', base.fields.get('a')!]]),
      modules: new Map([...base.modules].filter(([, m]) => Number(m.id.slice(1)) < 10)
        .map(([id, m]) => [id, {...m, fieldId: m.fieldId === 'b' ? 'a-B' : 'z-A'}]))};
    const ordered = orderModules(ctx, [...ctx.modules.keys()], "row_major");
    expect(ordered.slice(0, 10).every(id => id.startsWith('b'))).toBe(true);
    const cmd = command([null, ['a-B']], [[10], [10]]);
    const result = applyTopologyCommand(ctx, cmd);
    expect(result.map(s => [s.string_id, s.target_mppt_instance_id])).toEqual([['S1', 'p1'], ['S2', 'p2']]);
    expect(result[0].module_instance_ids.every(id => id.startsWith('a'))).toBe(true);
    expect(result[1].module_instance_ids.every(id => id.startsWith('b'))).toBe(true);
    expect(result.map(s => s.module_instance_ids.length)).toEqual([10, 10]);
    const ids = result.flatMap(s => s.module_instance_ids); expect(new Set(ids).size).toBe(20);
    expect(JSON.stringify(applyTopologyCommand(ctx, cmd))).toBe(JSON.stringify(result));
  });
  it("demo filters kept/reused strings and fresh modules per MPPT without duplicates", () => {
    const ctx = context();
    const result = applyTopologyCommand(ctx, command([["b"], ["a"]], [[4], [4]]));
    expect(result.find(s => s.string_id === "kept")?.target_mppt_instance_id).toBe("p2");
    expect(result.find(s => s.string_id === "free")?.target_mppt_instance_id).toBe("p1");
    const fresh = applyTopologyCommand({...ctx, strings: []}, command([["b"], ["a"]]));
    for (const s of fresh) expect(s.module_instance_ids.every(id => id.startsWith(s.target_mppt_instance_id === "p1" ? "b" : "a"))).toBe(true);
    const ids = fresh.flatMap(s => s.module_instance_ids); expect(new Set(ids).size).toBe(ids.length);
    expect(() => applyTopologyCommand(ctx, command([["a"], ["a"]], [[8], [8]]))).toThrow(/MPPT 2 source/);
    for (const source of [[null], [[], null], [["missing"], null]]) expect(() => applyTopologyCommand(ctx, command(source))).toThrow();
    const paired = {...ctx, inverters: ctx.inverters.map(i => ({...i, paired_pv_field_ids: ["a"]}))};
    expect(() => applyTopologyCommand(paired, command([["b"], null]))).toThrow(/inverter pool/);
  });
  it("demo sizing uses the served fields and the viewer target", async () => {
    await mockApi.createProject({name: "Sizing", latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane"});
    let v = await mockApi.addSurface("demo-project", {name: "Roof", origin_x_m: 0, origin_y_m: 0, width_m: 30, height_m: 10, base_elevation_m: 6, surface_type: "flat_roof"});
    v = await mockApi.createPvField("demo-project", {name: "PV", support_surface_id: v.bundle.scene.surfaces[0].surface_id, module_definition_revision_id: "mod-demo-550", orientation: "portrait", azimuth_deg: 0, tilt_deg: 10, module_gap_x_m: .02, module_gap_y_m: .02, row_pitch_m: 3.2, mounting_height_m: .5, perimeter_setback_m: .5, obstacle_setback_m: .3});
    v = await mockApi.addInverter("demo-project", {name: "INV", inverter_definition_revision_id: "inv-demo-30k"});
    const inv = v.bundle.electrical_design.inverter_instances[0];
    const sizing = await mockApi.inverterSizing("demo-project", inv.inverter_instance_id);
    expect(sizing.module_count).toBe(v.bundle.scene.module_instances.length);
    expect(sizing.area_kwp).toBeCloseTo(sizing.module_count * .55, 8);
    expect(sizing.ac_kw).toBe(30); expect(sizing.string_length_min).not.toBeNull();
  });
  it("Apply and dry run send the same layout and sources, including a suggested restring", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", {status: 200, headers: {"Content-Type": "application/json"}})));
    vi.stubGlobal("fetch", fetch);
    try {
      const layout = [[10], [12]], sources = [["a"], ["b"]];
      await api.applyLayoutReplacing("p", "inv", layout, ["a", "b"], ["old"], sources);
      await api.electricalDryRun("p", [{command_type: "delete_strings", parameters: {string_ids: ["old"]}},
        {command_type: "apply_mppt_layout", parameters: {inverter_instance_id: "inv", layout, pv_field_ids: ["a", "b"], sources}}]);
      const apply = JSON.parse(fetch.mock.calls[0][1].body), dry = JSON.parse(fetch.mock.calls[1][1].body);
      const intents = (body: {commands: {command_type: string; parameters: unknown}[]}) => body.commands.map(c => [c.command_type, c.parameters]);
      expect(intents(dry)).toEqual(intents(apply));
      expect(apply.commands[1].parameters.sources).toEqual(sources);
      await api.inverterSizing("p", "inv"); expect(fetch.mock.calls[2][0]).toBe("/api/projects/p/inverters/inv/sizing");
    } finally { vi.unstubAllGlobals(); }
  });
});
