import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { api, responseError } from "../../src/api";
import { notifyTakenModules } from "../../src/electrical/takenNotice";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { applyTopologyCommand, type TopologyContext } from "../../src/demo/topologyEngine";
import { ElectricalPanel } from "../../src/panels/ElectricalPanel";
import { resetStore, uiStore } from "../../src/state/store";
import i18n from "../../src/i18n";
import type { ProjectView } from "../../src/types";

vi.mock("../../src/state/store", async (load) => {
  const actual = await load<typeof import("../../src/state/store")>();
  return { ...actual, useStore: () => actual.uiStore.getState() };
});
let view: ProjectView;
beforeEach(async () => {
  resetStore(); setDemoLatency(0); await i18n.changeLanguage("en");
  view = structuredClone(await mockApi.project("demo-project"));
});
afterEach(() => vi.unstubAllGlobals());

it.each(["draw", "new on MPPT", "append"])("%s sends take_from_unassigned", async (action) => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(view), { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  Object.assign(view.bundle.electrical_design, { mppt_instances: [], connections: [] });
  const parameters = { module_instance_ids: ["module-a"] };
  const mppt = view.topology_view.inverters[0].mppts[0].mppt_instance_id;
  await api.topologyCommand(view.bundle.project.project_id, action === "append"
    ? { command_type: "append_to_string", parameters: { ...parameters, string_id: "S001" } }
    : { command_type: "create_string", parameters: { ...parameters, ...(action === "new on MPPT" ? { mppt_instance_id: mppt } : {}) } }, view);
  const commands = JSON.parse(fetcher.mock.calls[0][1].body).commands;
  expect(commands[0].parameters.take_from_unassigned).toBe(true);
  expect(commands[0].parameters.module_instance_ids).toEqual(["module-a"]);
  expect(commands.map((c: { command_type: string }) => c.command_type)).toEqual(action === "append" ? ["create_string", "join_strings"] : action === "new on MPPT" ? ["create_string", "assign_strings_to_mppt"] : ["create_string"]);
});

it("shows a short transfer notice in both languages", async () => {
  const result = { ...view, command_results: [{ result: { taken_from: { S001: ["a", "b", "c"] }, deleted_string_ids: ["S001"] } }] };
  await notifyTakenModules(result);
  expect(uiStore.getState().state.toasts.at(-1)?.text).toBe("3 modules moved from unassigned S001; S001 removed");
  await i18n.changeLanguage("id"); await notifyTakenModules(result);
  expect(uiStore.getState().state.toasts.at(-1)?.text).toBe("3 modul dipindahkan dari S001 yang belum ditetapkan; S001 dihapus");
});

it.each(["definition", "catalog", "missing"])("inputs and source follow %s data", (source) => {
  const inv = view.topology_view.inverters[0];
  const catalog = view.catalog.inverters.find((c) => c.revision_id === inv.inverter_definition_revision_id)!;
  for (const m of inv.mppts) m.input_count = source === "definition" ? 3 : null;
  catalog.inputs_per_mppt = source === "catalog" ? 2 : null;
  uiStore.getState().dispatch({ type: "setView", view });
  const html = renderToStaticMarkup(createElement(ElectricalPanel));
  const fields = html.slice(html.indexOf("Inputs per MPPT"), html.indexOf("MPPT layout", html.indexOf("Inputs per MPPT")));
  if (source === "missing") {
    expect(fields).toContain("Not in the inverter file; enter from the datasheet");
    expect(fields).not.toContain('readOnly=""');
  } else {
    expect(fields.match(/readOnly=""/g)).toHaveLength(2);
    expect(fields).toContain(`value="${source === "definition" ? 3 : 2}"`);
    expect(fields).toContain(source === "definition" ? "Inverter definition" : "Inverter file");
  }
});

const context = (): TopologyContext => ({
  inverters: [], tables: [], fields: new Map(),
  strings: [
    { string_id: "S001", module_instance_ids: ["a", "b"], enabled: false, target_mppt_instance_id: null },
    { string_id: "S002", module_instance_ids: ["c", "d", "e"], enabled: false, target_mppt_instance_id: null }
  ],
  modules: new Map(["a", "b", "c", "d", "e"].map((id) => [id, { id, enabled: true, fieldId: "f", centre: [0, 0], slot: null }]))
});
it("demo reclaims entire and partial unassigned strings without mutating its input", () => {
  const ctx = context(); const before = structuredClone(ctx.strings);
  const strings = applyTopologyCommand(ctx, { command_type: "create_string", parameters: { module_instance_ids: ["a", "b", "d"] } });
  expect(strings.map((s) => s.module_instance_ids)).toEqual([["c", "e"], ["a", "b", "d"]]);
  expect(ctx.strings).toEqual(before);
});
it("demo append takes unassigned modules and refuses assigned ownership atomically", () => {
  const ctx = context();
  expect(() => applyTopologyCommand(ctx, { command_type: "append_to_string", parameters: { string_id: "S002", module_instance_ids: ["d"] } })).toThrow("These modules are already in S002.");
  expect(applyTopologyCommand(ctx, { command_type: "append_to_string", parameters: { string_id: "S002", module_instance_ids: ["a", "b"] } }).map((s) => s.module_instance_ids)).toEqual([["c", "d", "e", "a", "b"]]);
  ctx.inverters = [{ inverter_instance_id: "inv", inverter_definition_revision_id: "inv-demo-30k", name: "INV", enabled: true, mppt_instance_ids: ["mppt1", "mppt2"] }];
  ctx.strings[0].target_mppt_instance_id = "mppt2";
  expect(() => applyTopologyCommand(ctx, { command_type: "create_string", parameters: { module_instance_ids: ["d", "a"] } })).toThrow("These modules are already in S001 on MPPT 2. Remove them from S001 first, or use Move module.");
  expect(ctx.strings[1].module_instance_ids).toEqual(["c", "d", "e"]);
});

it("file values replace stale local input counts while missing values preserve datasheet entries", () => {
  const inv = view.topology_view.inverters[0];
  const id = inv.inverter_instance_id;
  const catalog = view.catalog.inverters.find((c) => c.revision_id === inv.inverter_definition_revision_id)!;
  uiStore.getState().dispatch({ type: "setView", view });
  uiStore.getState().dispatch({ type: "setElectrical", inverterId: id, patch: { inputsPerMppt: 99, inputsSource: "manual" } });
  inv.mppts.forEach((m) => { m.input_count = 3; });
  uiStore.getState().dispatch({ type: "setView", view });
  expect(uiStore.getState().state.electrical[id].inputsPerMppt).toBe(3);
  inv.mppts.forEach((m) => { m.input_count = null; }); catalog.inputs_per_mppt = null;
  uiStore.getState().dispatch({ type: "setElectrical", inverterId: id, patch: { inputsPerMppt: 4, inputsSource: "datasheet page 2" } });
  uiStore.getState().dispatch({ type: "setView", view });
  expect(uiStore.getState().state.electrical[id]).toMatchObject({ inputsPerMppt: 4, inputsSource: "datasheet page 2" });
});

it("preserves command context while translating the assigned-string refusal", async () => {
  const detail = "command 0 (str1, create_string): These modules are already in S004 on MPPT 2. Remove them from S004 first, or use Move module.";
  expect(responseError({ detail }, "failed")).toBe(detail);
  await i18n.changeLanguage("id");
  expect(responseError({ detail }, "failed")).toBe("command 0 (str1, create_string): Modul ini sudah berada di S004 di MPPT 2. Keluarkan dari S004 terlebih dahulu, atau gunakan Pindahkan modul.");
});

it("demo reports a removed inverter's reclaimed modules and one undo restores the topology", async () => {
  const pid = view.bundle.project.project_id;
  const inv = view.bundle.electrical_design.inverter_instances[0];
  await mockApi.removeInverter(pid, inv.inverter_instance_id);
  const before = structuredClone((await mockApi.project(pid)).bundle.electrical_design);
  const source = before.strings.find((s) => !s.target_mppt_instance_id)!;
  const moved = await mockApi.topologyCommand(pid, { command_type: "create_string", parameters: { module_instance_ids: source.module_instance_ids } });
  expect(moved).toHaveProperty("command_results.0.result.taken_from", { [source.string_id]: source.module_instance_ids });
  expect(moved).toHaveProperty("command_results.0.result.deleted_string_ids", [source.string_id]);
  expect(uiStore.getState().state.toasts.at(-1)?.text).toContain(`modules moved from unassigned ${source.string_id}; ${source.string_id} removed`);
  expect((await mockApi.undo(pid)).bundle.electrical_design).toEqual(before);
  await mockApi.undo(pid); // Restore the seeded inverter for other tests in this file.
});
