import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../src/api";
import { mockApi } from "../../src/demo/mockApi";
import type { TopologyCommand } from "../../src/engine/topology";
import { PENDING } from "../../src/pending";
import { electricalIssues } from "../../src/state/derived";
import { resetStore, uiStore } from "../../src/state/store";
import type { ProjectView } from "../../src/types";
import fixture from "./s7b-engine-fixture.json";

// S14b: replicate, notation Apply, the orientation policy and pairing reach the engine; pairing and overrides come
// from the engine design, not from browser state.
let view: ProjectView;
const response = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
const command = (command_type: string, parameters: unknown) => ({ schema_name: "ElectricalTopologyCommand", schema_version: "0.1", command_id: expect.any(String), command_type, parameters });
let fetch: ReturnType<typeof vi.fn>;
beforeEach(() => {
  resetStore();
  view = structuredClone(fixture.views.before) as unknown as ProjectView; view.bundle.project.project_id = "p";
  fetch = vi.fn().mockImplementation(() => Promise.resolve(response({ ...view, command_results: [] })));
  vi.stubGlobal("fetch", fetch);
});
afterEach(() => { vi.unstubAllGlobals(); resetStore(); });
const body = () => JSON.parse(fetch.mock.calls[0][1].body);

describe("engine mapping", () => {
  it.each<TopologyCommand>([
    { command_type: "replicate_pattern", parameters: { source_pv_field_id: "f", source_table_id: "T1" } },
    { command_type: "replicate_pattern", parameters: { source_pv_field_id: "f", source_table_id: "T1", targets: [{ pv_field_id: "f", table_id: "T2" }] } },
    { command_type: "set_orientation_tolerance", parameters: { tolerance_deg: 0.5 } },
    { command_type: "set_orientation_override", parameters: { mppt_instance_id: "m1", reason: "One roof plane" } },
    { command_type: "set_orientation_override", parameters: { mppt_instance_id: "m1", reason: null } },
    { command_type: "set_inverter_pairing", parameters: { inverter_instance_id: "i", pv_field_ids: ["f", "g"] } },
    { command_type: "apply_mppt_layout", parameters: { inverter_instance_id: "i", layout: [[10, 10], [0]], pv_field_ids: ["f"] } },
  ])("$command_type is one electrical batch with its parameters", async (c) => {
    await api.topologyCommand("p", c, view);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/projects/p/electrical/commands");
    expect(body()).toEqual({ commands: [command(c.command_type, c.parameters)] });
  });

  it("notation Apply without paired fields lets the engine take every field", async () => {
    await api.topologyCommand("p", { command_type: "apply_mppt_layout", parameters: { inverter_instance_id: "i", layout: [[10]], pv_field_ids: [] } }, view);
    expect(body().commands[0].parameters).toEqual({ inverter_instance_id: "i", layout: [[10]] });
  });

  it("the S14b badges are gone", () => {
    for (const id of ["notationApply", "replicatePattern", "tablePairing", "orientationPolicy"]) expect(PENDING).not.toHaveProperty(id);
  });
});

describe("pairing and overrides come from the engine design", () => {
  // The demo project has inverters, strings and fields; the S7b fixture has none.
  beforeEach(async () => { view = structuredClone(await mockApi.project("demo-project")); });

  it("the inverter draft reads the engine pairing on every view", () => {
    const inv = view.bundle.electrical_design.inverter_instances[0];
    const fields = view.bundle.scene.pv_fields.map((f) => f.pv_field_id);
    inv.paired_pv_field_ids = fields.slice(0, 1);
    uiStore.getState().dispatch({ type: "setView", view });
    expect(uiStore.getState().state.electrical[inv.inverter_instance_id].pairedFieldIds).toEqual(fields.slice(0, 1));
    const next = structuredClone(view);
    delete next.bundle.electrical_design.inverter_instances[0].paired_pv_field_ids;
    uiStore.getState().dispatch({ type: "setView", view: next });
    expect(uiStore.getState().state.electrical[inv.inverter_instance_id].pairedFieldIds).toEqual([]);
  });

  it("an engine override is a local finding with its reason; there is none without one", () => {
    const inv = view.bundle.electrical_design.inverter_instances[0];
    uiStore.getState().dispatch({ type: "setView", view });
    expect(electricalIssues(uiStore.getState().state).filter((f) => f.id.includes("-ovr-"))).toEqual([]);
    const next = structuredClone(view);
    next.bundle.electrical_design.orientation_policy = { normal_angle_tolerance_deg: 1, overrides: [{ mppt_instance_id: inv.mppt_instance_ids[1], reason: "One roof plane" }] };
    uiStore.getState().dispatch({ type: "setView", view: next });
    const [finding] = electricalIssues(uiStore.getState().state).filter((f) => f.id.includes("-ovr-"));
    expect(finding.message).toBe(`${inv.name} MPPT 2: mixed-orientation override (One roof plane). Beyond the tolerance this MPPT is simulated with mixed orientations — beyond what PVsyst and HelioScope simulate.`);
  });
});
