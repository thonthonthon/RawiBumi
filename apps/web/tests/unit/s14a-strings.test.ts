import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../src/api";
import { ELECTRICAL_KEYS, ELECTRICAL_TOOLS } from "../../src/canvas/tools";
import type { TopologyCommand } from "../../src/engine/topology";
import { PENDING } from "../../src/pending";
import { resetStore } from "../../src/state/store";
import type { ProjectView } from "../../src/types";
import fixture from "./s7b-engine-fixture.json";

// S14a: split, join, reverse, move and swap reach the engine as one batch each; serpentine strings too.
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

describe("string edits", () => {
  it.each<TopologyCommand>([
    { command_type: "split_string", parameters: { string_id: "S001", after_module_instance_id: "m3" } },
    { command_type: "join_strings", parameters: { first_string_id: "S001", second_string_id: "S002" } },
    { command_type: "reverse_string", parameters: { string_id: "S001" } },
    { command_type: "move_module", parameters: { module_instance_id: "m1", to_string_id: "S002", index: 0 } },
    { command_type: "move_module", parameters: { module_instance_id: "m1", to_string_id: null, index: null } },
    { command_type: "swap_modules", parameters: { first_module_instance_id: "m1", second_module_instance_id: "m9" } },
  ])("$command_type is one electrical batch with its parameters unchanged", async (c) => {
    await api.topologyCommand("p", c, view);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/projects/p/electrical/commands");
    expect(body()).toEqual({ commands: [command(c.command_type, c.parameters)] });
  });

  it("the tools reach the engine and are no longer pending", () => {
    expect(PENDING).not.toHaveProperty("topologyEdit");
    expect(PENDING).not.toHaveProperty("serpentineOrdering");
    expect(PENDING).not.toHaveProperty("stringChecks");
    expect(ELECTRICAL_TOOLS.map((t) => [t.tool, t.key, t.pending])).toEqual([
      ["select", "v", null], ["string_path", "s", null], ["assign", "a", null], ["lasso", "l", null],
      ["split", "x", null], ["join", "j", null], ["reverse", "r", null], ["move_module", "m", null], ["swap_modules", "w", null],
    ]);
    expect(new Set(ELECTRICAL_TOOLS.map((t) => t.key)).size).toBe(ELECTRICAL_TOOLS.length);
    expect(ELECTRICAL_KEYS.map(([k]) => k)).toContain("Delete");
  });
});

describe("serpentine strings", () => {
  const free = () => {
    const strung = new Set(view.bundle.electrical_design.strings.flatMap((s) => s.module_instance_ids));
    return view.bundle.scene.module_instances.filter((m) => m.enabled && !strung.has(m.module_instance_id));
  };

  it("a selection goes to the engine in serpentine order", async () => {
    await api.topologyCommand("p", { command_type: "create_strings", parameters: { module_instance_ids: ["m2", "m1"], string_length: 2, ordering: "serpentine", allow_shorter_remainder: false } }, view);
    expect(body()).toEqual({ commands: [command("create_strings", { module_instance_ids: ["m2", "m1"], string_length: 2, ordering: "serpentine", remainder_policy: "error" })] });
  });

  it("without a selection it takes the enabled unstrung modules, of the field when one is given", async () => {
    // Two fields of three modules; m2 is disabled and m5 already strung.
    view.bundle.scene.module_instances = ["m1", "m2", "m3", "m4", "m5", "m6"].map((id, i) => ({ module_instance_id: id, pv_field_id: i < 3 ? "fa" : "fb", enabled: id !== "m2" })) as unknown as ProjectView["bundle"]["scene"]["module_instances"];
    view.bundle.electrical_design.strings = [{ string_id: "S001", module_instance_ids: ["m5"] }] as unknown as ProjectView["bundle"]["electrical_design"]["strings"];
    const all = free();
    expect(all.map((m) => m.module_instance_id)).toEqual(["m1", "m3", "m4", "m6"]);
    await api.topologyCommand("p", { command_type: "create_strings", parameters: { string_length: 4, ordering: "serpentine", allow_shorter_remainder: true } }, view);
    expect(body().commands[0].parameters).toEqual({ module_instance_ids: all.map((m) => m.module_instance_id), string_length: 4, ordering: "serpentine", remainder_policy: "allow_shorter" });
    fetch.mockClear();
    await api.topologyCommand("p", { command_type: "create_strings", parameters: { string_length: 4, pv_field_id: "fb", ordering: "serpentine", allow_shorter_remainder: true } }, view);
    expect(body().commands[0].parameters.module_instance_ids).toEqual(["m4", "m6"]);
  });

  it("refuses without the current view or free modules, and never fetches", async () => {
    const c: TopologyCommand = { command_type: "create_strings", parameters: { string_length: 4, ordering: "serpentine", allow_shorter_remainder: true } };
    await expect(api.topologyCommand("p", c)).rejects.toThrow(/current project view/);
    await expect(api.topologyCommand("p", { ...c, parameters: { ...c.parameters, pv_field_id: "no-such-field" } }, view)).rejects.toThrow(/No enabled unstrung modules/);
    expect(fetch).not.toHaveBeenCalled();
  });
});
