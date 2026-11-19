import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, nextElectricalStringId, repairRefusalSummary, responseError } from "../../src/api";
import { ELECTRICAL_TOOLS, TOOLS } from "../../src/canvas/tools";
import type { TopologyCommand } from "../../src/engine/topology";
import { PENDING } from "../../src/pending";
import { engineCommand } from "../../src/state/history";
import { resetStore, uiStore } from "../../src/state/store";
import type { ProjectView } from "../../src/types";
import i18n from "../../src/i18n";
import fixture from "./s7b-engine-fixture.json";

let view: ProjectView;
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const command = (command_type: string, parameters: unknown) => ({ schema_name: "ElectricalTopologyCommand", schema_version: "0.1", command_id: expect.any(String), command_type, parameters });
let fetch: ReturnType<typeof vi.fn>;
beforeEach(async () => {
  resetStore(); await i18n.changeLanguage("en");
  view = structuredClone(fixture.views.before) as unknown as ProjectView; view.bundle.project.project_id = "p";
  fetch = vi.fn().mockImplementation(() => Promise.resolve(response({ ...view, command_results: [] })));
  vi.stubGlobal("fetch", fetch);
});
afterEach(() => { vi.unstubAllGlobals(); resetStore(); });
function body(index = 0) { return JSON.parse(fetch.mock.calls[index][1].body); }

describe("S7c atomic electrical mapping", () => {
  it.each([null, "mppt-1"])("creates a path with target %s in exactly one request", async (target) => {
    const result = await api.topologyCommand("p", { command_type: "create_string", parameters: { module_instance_ids: ["m3", "m1", "m2"], mppt_instance_id: target } }, view);
    expect(result).toHaveProperty("command_results"); expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/projects/p/electrical/commands");
    expect(body()).toEqual({ commands: [command("create_string", { string_id: "S001", module_instance_ids: ["m3", "m1", "m2"], take_from_unassigned: true }),
      ...(target ? [command("assign_strings_to_mppt", { string_ids: ["S001"], mppt_instance_id: target })] : [])] });
    expect(new Set(body().commands.map((c: { command_id: string }) => c.command_id)).size).toBe(body().commands.length);
  });
  it.each<TopologyCommand>([
    { command_type: "assign_strings_to_mppt", parameters: { string_ids: ["S003", "S001"], mppt_instance_id: "mppt2" } },
    { command_type: "unassign_strings", parameters: { string_ids: ["S003", "S001"] } },
  ])("maps $command_type without altering its parameters", async (c) => {
    await api.topologyCommand("p", c); expect(fetch).toHaveBeenCalledTimes(1);
    expect(body()).toEqual({ commands: [command(c.command_type, c.parameters)] });
  });
  it("deletes three strings in the given order, in one batch", async () => {
    await api.topologyCommand("p", { command_type: "delete_strings", parameters: { string_ids: ["S007", "S002", "S004"] } });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(body()).toEqual({ commands: ["S007", "S002", "S004"].map((string_id) => command("delete_string", { string_id })) });
  });
  it.each([ ["row_major", false], ["row_major", true], ["selection", false], ["selection", true] ] as const)("maps selected modules: %s, shorter=%s", async (ordering, shorter) => {
    await api.topologyCommand("p", { command_type: "create_strings", parameters: { module_instance_ids: ["m2", "m1"], pv_field_id: "field", string_length: 2, ordering, allow_shorter_remainder: shorter } });
    expect(body()).toEqual({ commands: [command("create_strings", { module_instance_ids: ["m2", "m1"], string_length: 2, ordering, remainder_policy: shorter ? "allow_shorter" : "error" })] });
    expect(body().commands[0].parameters).not.toHaveProperty("id_prefix");
  });
  it("preserves both legacy routes and their request shapes", async () => {
    await api.topologyCommand("p/a", { command_type: "create_strings", parameters: { string_length: 20, pv_field_id: "f", ordering: "row_major", allow_shorter_remainder: false } });
    expect(fetch.mock.calls[0][0]).toBe("/api/projects/p%2Fa/strings"); expect(body()).toEqual({ string_length: 20, pv_field_id: "f", allow_shorter_remainder: false });
    await api.topologyCommand("p/a", { command_type: "assign_strings", parameters: { inverter_instance_id: "inv" } });
    expect(fetch.mock.calls[1][0]).toBe("/api/projects/p%2Fa/assignments"); expect(body(1)).toEqual({ inverter_instance_id: "inv", string_ids: null });
  });
  it("rejects a missing current view before fetching (A1)", async () => {
    await expect(api.topologyCommand("p", { command_type: "create_string", parameters: { module_instance_ids: ["m1"] } })).rejects.toThrow(/current project view/);
    expect(fetch).not.toHaveBeenCalled();
  });
  it("skips every kind of occupied electrical entity id and picks the first free gap", async () => {
    Object.assign(view.bundle.electrical_design, { inverter_instances: [{ inverter_instance_id: "S001" }], mppt_instances: [{ mppt_instance_id: "S002" }], strings: [{ string_id: "S003" }, { string_id: "S999" }], connections: [{ connection_id: "S004" }] });
    expect(nextElectricalStringId(view)).toBe("S005"); expect(nextElectricalStringId(view)).toBe("S005");
    await api.topologyCommand("p", { command_type: "create_string", parameters: { module_instance_ids: ["m"] } }, view);
    expect(body().commands[0].parameters.string_id).toBe("S005");
    Object.assign(view.bundle.electrical_design, { mppt_instances: [] }); expect(nextElectricalStringId(view)).toBe("S002");
  });
  it("does not retry or rename a client id refused by the engine", async () => {
    fetch.mockImplementation(() => Promise.resolve(response({ detail: "command 0 (id, create_string): entity id S001 already exists" }, 422)));
    await expect(api.topologyCommand("p", { command_type: "create_string", parameters: { module_instance_ids: ["m"] } }, view)).rejects.toThrow(/S001 already exists/);
    expect(fetch).toHaveBeenCalledTimes(1); expect(body().commands[0].parameters.string_id).toBe("S001");
  });
});

describe("pending actions never fetch", () => {
  it("replaces the generic badge with specific pending ids; leaves scene badges alone", () => {
    expect(PENDING).not.toHaveProperty("topologyCommands");
    expect(ELECTRICAL_TOOLS.filter((t) => ["string_path", "assign"].includes(t.tool)).map((t) => t.pending)).toEqual([null, null]);
    expect(ELECTRICAL_TOOLS.filter((t) => ["split", "join", "reverse"].includes(t.tool)).map((t) => t.pending)).toEqual([null, null, null]);
    expect(TOOLS.find((t) => t.tool === "hole")?.pending).toBeNull(); expect(TOOLS.find((t) => t.tool === "keepout")?.pending).toBeNull();
  });
});

it.each(["en", "id"])("formats repair findings and the toast's first three affected entities (%s)", async (language) => {
  await i18n.changeLanguage(language);
  const findings = ["S001", "S002", "S003", "S004", "S005"].map((entity_id) => ({ entity_id, code: "string_unknown_module", message: "Module missing", origin: "pre-existing" }));
  const detail = { message: "Repair before committing (5 errors).", findings };
  const suffix = language === "en" ? " (5 consistency errors)" : " (5 kesalahan konsistensi)";
  expect(responseError({ detail }, "Fallback")).toBe(detail.message + suffix);
  const summary = repairRefusalSummary(detail);
  expect(summary).toContain("S001, S002, S003"); expect(summary).toContain(language === "en" ? "and 2 more" : "dan 2 lainnya"); expect(summary).not.toContain("S004");
  fetch.mockImplementation(() => Promise.resolve(response({ detail }, 422)));
  await engineCommand("Repair refusal", () => api.topologyCommand("p", { command_type: "unassign_strings", parameters: { string_ids: ["S001"] } }));
  const toast = uiStore.getState().state.toasts.at(-1)!;
  expect(toast.text).toBe(detail.message + suffix + summary); expect(toast.tone).toBe("error"); expect(toast.text).not.toContain("origin");
});
