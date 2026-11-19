import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { api } from "../../src/api";
import { buildMenu, type MenuState } from "../../src/canvas/contextMenu";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { edgeMisalignment } from "../../src/panels/LayoutPanel";
import type { ProjectView } from "../../src/types";

// USE3b: right-click assignment of unstrung modules, the roof-edge hint, and the append request.
const t = (key: string, o: Record<string, unknown> = {}) => `${key}${Object.keys(o).length ? JSON.stringify(o) : ""}`;
const base: MenuState = { target: { kind: "selection" }, selected: [], selectedModules: 2, activeTables: 0, step: "electrical", busy: false,
  canUndo: false, canRedo: false, tools: [], anyVisible: true, meshIds: new Set() };

describe("right-click on unstrung modules", () => {
  const assign = { count: 2, strings: [{ id: "S001", label: "S001 · INV-02 · MPPT 1 · 12" }], mppts: [{ id: "m1", label: "INV-02 · MPPT 1" }, { id: "m2", label: "INV-02 · MPPT 2" }] };
  it("offers each string and each MPPT in Electrical only", () => {
    const ids = buildMenu({ ...base, unstrungAssign: assign }, t).map((i) => i.id);
    expect(ids).toEqual(expect.arrayContaining(["addToString:S001", "newString:m1", "newString:m2"]));
    expect(buildMenu({ ...base, step: "layout", unstrungAssign: assign }, t).some((i) => i.id.startsWith("addToString:"))).toBe(false);
    expect(buildMenu({ ...base, unstrungAssign: { ...assign, count: 0 } }, t).some((i) => i.id.startsWith("newString:"))).toBe(false);
  });
});

describe("roof edge versus plane azimuth", () => {
  const roof = (azimuth: number) => ({ slope_deg: 9, azimuth_deg: azimuth, boundary_2d: { vertices: [[0, 0], [24, -0.2], [24, 11.45], [0, 11.65]] as [number, number][] } });
  it("names the low edge when the plane is slightly off it, and nothing when aligned or flat", () => {
    const edgeAzimuth = edgeMisalignment(roof(180))!.edgeAzimuth;
    expect(edgeMisalignment(roof(180))).toMatchObject({ edgeIndex: 0 });
    expect(edgeMisalignment(roof(edgeAzimuth))).toBeNull();
    expect(edgeMisalignment({ ...roof(180), slope_deg: 0 })).toBeNull();
    expect(edgeMisalignment(roof(200))).toBeNull(); // more than 5° off: a deliberate design, not a drawing slip
  });
});

describe("append to string", () => {
  let view: ProjectView;
  beforeAll(async () => {
    setDemoLatency(0);
    // The engine's bundle shape: the new string's ID is chosen against every electrical ID, MPPTs included.
    view = structuredClone(await mockApi.project("demo-project"));
    Object.assign(view.bundle.electrical_design, { mppt_instances: [], connections: [] });
  });
  afterEach(() => vi.unstubAllGlobals());
  it("is one batch: a string from the modules, joined onto the target", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })));
    vi.stubGlobal("fetch", fetch);
    const pid = view.bundle.project.project_id;
    await api.topologyCommand(pid, { command_type: "append_to_string", parameters: { string_id: "S001", module_instance_ids: ["a", "b"] } }, view);
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.commands.map((c: { command_type: string }) => c.command_type)).toEqual(["create_string", "join_strings"]);
    expect(body.commands[1].parameters).toEqual({ first_string_id: "S001", second_string_id: body.commands[0].parameters.string_id });
  });
});
