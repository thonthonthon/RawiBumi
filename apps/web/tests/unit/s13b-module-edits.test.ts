import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { api } from "../../src/api";
import { engine } from "../../src/client";
import { resetStore, uiStore } from "../../src/state/store";
import { cancelModuleDelete, confirmModuleDelete, moduleDeletion, moduleDeleteFlags, moduleDragDelta, moduleNudge, moveModules, previewModuleDelete } from "../../src/canvas/useModuleEdits";
import type { ModuleCommandInput, ModuleDeletePreview, ProjectView } from "../../src/types";
import { ApiError } from "../../src/types";

it("S13b preflight: the unchanged demo seed provides modules outside active tables", async () => {
  setDemoLatency(0);
  const view = await mockApi.project("demo-project");
  expect(view.bundle.scene.module_instances).toHaveLength(76);
  expect((view.table_layout?.tables ?? []).filter((table) => table.status === "active")).toEqual([]);
  setDemoLatency(1);
});

describe("S13b adapter, gestures and preview contract", () => {
  let view: ProjectView;
  beforeEach(async () => {
    setDemoLatency(0); resetStore(); cancelModuleDelete();
    await mockApi.createProject({ name: "S13b unit", latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" });
    view = await mockApi.addSurface("demo-project", { name: "Roof", origin_x_m: 0, origin_y_m: 0, width_m: 12, height_m: 10, base_elevation_m: 6, surface_type: "flat_roof" });
    view = await mockApi.createPvField("demo-project", { name: "Manual field", support_surface_id: view.bundle.scene.surfaces[0].surface_id,
      module_definition_revision_id: "mod-demo-550", orientation: "portrait", azimuth_deg: 0, tilt_deg: 10,
      module_gap_x_m: .02, module_gap_y_m: .02, row_pitch_m: 3.1, mounting_height_m: .2, perimeter_setback_m: .3, obstacle_setback_m: .3 });
    uiStore.getState().dispatch({ type: "setView", view });
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); cancelModuleDelete(); resetStore(); setDemoLatency(1); });

  it.each([
    { command: "delete_modules", module_instance_ids: ["m1"], dry_run: true },
    { command: "delete_modules", module_instance_ids: ["m1", "m2"], discard_dependent_strings: true },
    { command: "move_modules", module_instance_ids: ["m1", "m2"], dx_m: .1, dy_m: -1 }
  ] satisfies ModuleCommandInput[])("sends the exact $command body", async (input) => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(view), { status: 200 })); vi.stubGlobal("fetch", fetch);
    await api.moduleCommands("project/id", input);
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0][0]).toBe("/api/projects/project%2Fid/pv-fields/modules/commands");
    expect(fetch.mock.calls[0][1].method).toBe("POST");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(input);
  });

  it("uses the exact rigid drag delta, Shift tenth-metre steps, and 0.10/1.00 m nudges", () => {
    expect(moduleDragDelta([4, 5], [4.26, 4.66], false)).toEqual([4.26 - 4, 4.66 - 5]);
    expect(moduleDragDelta([4, 5], [4.26, 4.66], true)).toEqual([.3, -.3]);
    expect(moduleNudge("ArrowUp", false)).toEqual([0, .1]);
    expect(moduleNudge("ArrowLeft", true)).toEqual([-1, 0]); expect(moduleNudge("Delete", false)).toBeNull();
  });

  it("previews without history; Cancel makes no commit; Confirm sends only required flags", async () => {
    view = await mockApi.createStrings("demo-project", { string_length: 6, allow_shorter_remainder: true });
    uiStore.getState().dispatch({ type: "setView", view });
    const ids = view.bundle.scene.module_instances.slice(0, 3).map((m) => m.module_instance_id);
    const calls = vi.spyOn(engine, "moduleCommands").mockImplementation((id, input) => mockApi.moduleCommands(id, input));
    await previewModuleDelete(ids); expect(moduleDeletion.getState().pending!.preview.requires_discard_dependent_strings).toBe(true);
    expect(uiStore.getState().state.past).toHaveLength(0); expect((await mockApi.project("demo-project")).bundle.scene.module_instances).toEqual(view.bundle.scene.module_instances);
    cancelModuleDelete(); expect(calls).toHaveBeenCalledTimes(1);
    await previewModuleDelete(ids); const preview = moduleDeletion.getState().pending!.preview;
    expect(moduleDeleteFlags(preview)).toEqual({ discard_dependent_strings: true });
    expect(moduleDeleteFlags({ ...preview, requires_discard_dependent_strings: false })).toEqual({});
    await confirmModuleDelete();
    expect(calls.mock.calls.at(-1)![1]).toEqual({ command: "delete_modules", module_instance_ids: ids, discard_dependent_strings: true });
    expect(moduleDeletion.getState().pending).toBeNull(); expect(uiStore.getState().state.past).toHaveLength(1);
    const after = await mockApi.project("demo-project");
    expect(after.bundle.scene.module_instances.map((m) => m.module_instance_id)).toEqual(view.bundle.scene.module_instances.filter((m) => !ids.includes(m.module_instance_id)).map((m) => m.module_instance_id));
    expect(after.bundle.electrical_design.strings).toEqual(view.bundle.electrical_design.strings.filter((s) => !preview.string_ids.includes(s.string_id)));
    expect(after.bundle.scene.pv_fields[0].layout_status).toBe("manual");
  });

  it("mock delete validates ids, flags and empty fields without partial mutations", async () => {
    const ids = view.bundle.scene.module_instances.map((m) => m.module_instance_id);
    const raw = structuredClone(view);
    for (const input of [
      { command: "delete_modules", module_instance_ids: [] }, { command: "delete_modules", module_instance_ids: [ids[0], ids[0]] },
      { command: "delete_modules", module_instance_ids: ["missing"] }, { command: "delete_modules", module_instance_ids: [ids[0]], dx_m: 0 }
    ]) await expect(mockApi.moduleCommands("demo-project", input as ModuleCommandInput)).rejects.toThrow();
    expect(await mockApi.project("demo-project")).toEqual(raw);
    const preview = await mockApi.moduleCommands("demo-project", { command: "delete_modules", module_instance_ids: ids, dry_run: true });
    expect(preview.fields[0].field_becomes_empty).toBe(true);
    const after = await mockApi.moduleCommands("demo-project", { command: "delete_modules", module_instance_ids: ids });
    expect(after.bundle.scene.pv_fields).toHaveLength(1); expect(after.bundle.scene.module_instances).toHaveLength(0);
  });

  it("mock refuses overlap and leaving support, permits A1 contact, and preserves group identity", async () => {
    const modules = view.scene_view.local_features.filter((f) => f.category === "module"), first = modules[0], second = modules[1];
    const centre = (polygon: number[][]) => polygon.reduce(([x, y], p) => [x + p[0] / polygon.length, y + p[1] / polygon.length], [0, 0]);
    const a = centre(first.polygon), b = centre(second.polygon);
    const before = await mockApi.project("demo-project");
    await expect(mockApi.moduleCommands("demo-project", { command: "move_modules", module_instance_ids: [first.id], dx_m: b[0] - a[0], dy_m: b[1] - a[1] })).rejects.toThrow("conflicts");
    await expect(mockApi.moduleCommands("demo-project", { command: "move_modules", module_instance_ids: [first.id], dx_m: -100, dy_m: 0 })).rejects.toThrow("conflicts");
    expect(await mockApi.project("demo-project")).toEqual(before);
    await mockApi.moduleCommands("demo-project", { command: "move_modules", module_instance_ids: [first.id], dx_m: .02, dy_m: 0 });
    const after = await mockApi.project("demo-project"); expect(after.bundle.scene.module_instances).toEqual(before.bundle.scene.module_instances);
    expect(after.bundle.electrical_design).toEqual(before.bundle.electrical_design);
    expect(after.bundle.scene.pv_fields[0].layout_status).toBe("manual");
  });

  it("ignores moves while busy and uses the existing 409 reload behavior", async () => {
    const calls = vi.spyOn(engine, "moduleCommands"); const id = view.bundle.scene.module_instances[0].module_instance_id;
    uiStore.getState().dispatch({ type: "busy", label: "Other edit" }); await moveModules([id], [.1, 0]); expect(calls).not.toHaveBeenCalled();
    uiStore.getState().dispatch({ type: "busy", label: null });
    calls.mockRejectedValueOnce(new ApiError("project changed concurrently; reload and retry", 409, "project changed concurrently; reload and retry"));
    const reload = vi.spyOn(engine, "project").mockResolvedValue(view);
    await moveModules([id], [.1, 0]); expect(reload).toHaveBeenCalledOnce(); expect(calls).toHaveBeenCalledOnce();
    expect(uiStore.getState().state.busy).toBeNull();
  });
});
