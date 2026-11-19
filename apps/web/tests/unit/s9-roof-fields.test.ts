import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../src/api";
import { engine } from "../../src/client";
import { entitySceneCommand } from "../../src/canvas/useEntityEdits";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { cancelDependentFields, confirmDependentFields, dependentFields, dependentFieldsBlocked, dependentSceneEdit } from "../../src/state/history";
import { resetStore, uiStore } from "../../src/state/store";
import type { DependentFieldPreview, ProjectView, ScenePreview } from "../../src/types";

let view: ProjectView;
const impact = (strings = true, manual = false): DependentFieldPreview => ({ pv_field_id: "fld-a", name: "Roof A array", action: "refill", module_count_before: 76, module_count_after: 40,
  stc_power_w_before: 41800, stc_power_w_after: 22000, string_ids: strings ? ["S1"] : [], requires_discard_dependent_strings: strings, requires_discard_manual_layout: manual, conflicts: [] });
const preview = (field = impact()): ScenePreview => ({ dry_run: true, dependent_fields: [field], conflicts: [] });
beforeEach(async () => {
  resetStore(); cancelDependentFields(); setDemoLatency(0);
  view = await mockApi.project("demo-project"); uiStore.getState().dispatch({ type: "setView", view });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); cancelDependentFields(); resetStore(); });
it("sends apply dry-run and preserves the identical command id and parameters for confirmation", async () => {
  const fetch = vi.fn().mockImplementationOnce(() => Promise.resolve(new Response(JSON.stringify(preview())))).mockImplementationOnce(() => Promise.resolve(new Response(JSON.stringify(view))));
  vi.stubGlobal("fetch", fetch);
  const command = { command_id: "request-scoped-id", command_type: "scale" as const, target_entity_ids: ["roof"], parameters: { factor: .8, origin: [4, 4] } };
  await dependentSceneEdit("Resize", (options) => api.sceneCommand("p/id", command, options));
  expect(fetch).toHaveBeenCalledTimes(1); expect(uiStore.getState().state.past).toEqual([]); expect(uiStore.getState().state.view).toEqual(view);
  const first = JSON.parse(fetch.mock.calls[0][1].body);
  expect(first).toMatchObject({ dependent_fields: "apply", dry_run: true }); expect(first).not.toHaveProperty("discard_dependent_strings");
  await confirmDependentFields(); const second = JSON.parse(fetch.mock.calls[1][1].body);
  expect(second).toEqual({ command: first.command, dependent_fields: "apply", discard_dependent_strings: true });
  expect(second.command.command_id).toBe("request-scoped-id"); expect(uiStore.getState().state.past).toHaveLength(1);
});
it.each([[false,false],[true,false],[false,true],[true,true]])("confirmation sends only required flags: strings=%s manual=%s", async (strings, manual) => {
  const op = vi.fn().mockResolvedValueOnce(preview(impact(strings,manual))).mockResolvedValueOnce(view);
  await dependentSceneEdit("Edit", op); expect(op).toHaveBeenCalledExactlyOnceWith({ dependent_fields: "apply", dry_run: true });
  await confirmDependentFields(); expect(op.mock.calls[1][0]).toEqual({ dependent_fields:"apply", ...(strings ? {discard_dependent_strings:true}:{}), ...(manual ? {discard_manual_layout:true}:{}) });
});
it("Cancel sends no commit and leaves the project and history unchanged", async () => {
  const op = vi.fn().mockResolvedValue(preview()); await dependentSceneEdit("Edit", op); cancelDependentFields(); await confirmDependentFields();
  expect(op).toHaveBeenCalledTimes(1); expect(uiStore.getState().state.view).toEqual(view); expect(uiStore.getState().state.past).toEqual([]);
});
it.each(["zero", "conflict"])("a %s preview refuses confirmation", async (reason) => {
  const field = impact(); if (reason === "zero") field.module_count_after = 0; else field.conflicts = [{ code: "module_obstacle_overlap" }];
  const op = vi.fn().mockResolvedValue(preview(field)); await dependentSceneEdit("Edit",op); await confirmDependentFields();
  expect(dependentFieldsBlocked([field])).toBe(true); expect(op).toHaveBeenCalledTimes(1);
  const deleted = { ...field, action: "delete" as const, module_count_after: 0, conflicts: [] }; expect(dependentFieldsBlocked([deleted])).toBe(false);
});
it("a hosted-roof entity scale uses the preview flow with an unchanged captured command", async () => {
  const entity = uiStore.getState().state.entities.find((entity) => entity.hostsPvField)!;
  const call = vi.spyOn(engine,"sceneCommand").mockResolvedValueOnce(preview() as unknown as ProjectView).mockResolvedValueOnce(view);
  await entitySceneCommand(entity,"scale",{ factor:.8,origin:[21,9] });
  expect(call.mock.calls[0][1]).toMatchObject({ command_type:"scale",target_entity_ids:[entity.id],parameters:{factor:.8,origin:[21,9]} });
  expect(call.mock.calls[0][2]).toEqual({dependent_fields:"apply",dry_run:true});
  await confirmDependentFields(); expect(call.mock.calls[1][1]).toBe(call.mock.calls[0][1]);
});
it("default caller metadata remains ignored; only apply may retain a request id", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(view)))); vi.stubGlobal("fetch",fetch);
  const command = {command_id:"stale",command_type:"scale" as const,target_entity_ids:["roof"],parameters:{factor:.8}};
  await api.sceneCommand("p",command); expect(JSON.parse(fetch.mock.calls[0][1].body).command.command_id).not.toBe("stale");
});
