import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../src/api";
import { engine } from "../../src/client";
import { entitySceneCommand } from "../../src/canvas/useEntityEdits";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { cancelSceneRefusal, confirmSceneRefusal, sceneEdit, sceneRefusal } from "../../src/state/history";
import { resetStore, uiStore } from "../../src/state/store";
import { ApiError, type ObstacleConflictDetail, type ProjectView, type SceneCommandInput } from "../../src/types";

const input = { name: "S7b demo", latitude_deg: -6.9, longitude_deg: 107.6, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" as const };
const box = { name: "Box", origin_x_m: 1, origin_y_m: 1, width_m: 0.8, depth_m: 1, base_elevation_m: 0, height_m: 2 };
const polygon = { name: "Polygon obstacle", vertices: [[20, 20], [22, 20], [21, 22]] as [number, number][], base_elevation_m: 0, height_m: 2 };
const command: SceneCommandInput = { command_type: "rotate", target_entity_ids: ["roof"], parameters: { angle_deg: 30, origin: [2, 3] } };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
const detail = (): ObstacleConflictDetail => ({ message: "Obstacle overlaps modules", conflicts: [{ module_instance_id: "m1", other_id: "obstacle" }], options: {
  remove_modules: { module_instance_ids: ["m1"], module_count: 1, stc_power_w: 550, string_ids: ["string1"] },
  refill_field: { available: true, fields: [{ pv_field_id: "field", module_count_before: 4, module_count_after: 2, stc_power_w_before: 2200, stc_power_w_after: 1100 }], string_ids: ["string2"], requires_discard_manual_layout: true }
} });
let view: ProjectView;
beforeEach(async () => {
  setDemoLatency(0); resetStore(); cancelSceneRefusal();
  view = await mockApi.createProject(input);
  uiStore.getState().dispatch({ type: "setView", view });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); cancelSceneRefusal(); resetStore(); setDemoLatency(1); });

describe("S7b HTTP adapter", () => {
  it.each<SceneCommandInput["command_type"]>(["rotate", "move", "move_vertex", "edit_exact_dimension", "edit_elevation", "delete", "draw_polygon"])("wraps %s with a unique canonical envelope", async (kind) => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(response(view))); vi.stubGlobal("fetch", fetch);
    const options = { on_module_conflict: "remove_modules" as const, discard_dependent_strings: true, discard_manual_layout: true };
    await api.sceneCommand("project/id", { ...command, command_type: kind }, options);
    await api.sceneCommand("project/id", { ...command, command_type: kind }, options);
    expect(fetch.mock.calls[0][0]).toBe("/api/projects/project%2Fid/scene/commands");
    const bodies = fetch.mock.calls.map((call) => JSON.parse(call[1].body));
    expect(bodies[0]).toEqual({ command: { ...command, command_type: kind, schema_name: "SceneEditorCommand", schema_version: "0.1", command_id: expect.any(String) }, ...options });
    expect(bodies[1].command.command_id).not.toBe(bodies[0].command.command_id);
  });
  it("replaces caller envelope metadata with canonical schema and a fresh command id", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(response(view))); vi.stubGlobal("fetch", fetch);
    const supplied = { ...command, command_id: "stale", schema_name: "Wrong", schema_version: "9" };
    await api.sceneCommand("p", supplied);
    const envelope = JSON.parse(fetch.mock.calls[0][1].body).command;
    expect(envelope.schema_name).toBe("SceneEditorCommand"); expect(envelope.schema_version).toBe("0.1"); expect(envelope.command_id).not.toBe("stale");
  });
  it("types dry-run responses and sends extrusion and existing-route conflict options", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(response({ dry_run: true, conflicts: [] }))); vi.stubGlobal("fetch", fetch);
    const options = { on_module_conflict: "reject" as const, dry_run: true as const };
    const preview = await api.sceneCommand("p", command, options); expect(preview.dry_run).toBe(true);
    await api.addPolygonObstacle("p", polygon, options);
    await api.addObstacle("p", box, options);
    await api.moveSceneEntity("p", { entity_id: "box", dx_m: 3, dy_m: 1 }, options);
    for (const [index, route, body] of [[1, "obstacles/extrusion", polygon], [2, "obstacles/box", box], [3, "scene/move", { entity_id: "box", dx_m: 3, dy_m: 1 }]] as const) {
      expect(fetch.mock.calls[index][0]).toBe(`/api/projects/p/${route}`);
      expect(JSON.parse(fetch.mock.calls[index][1].body)).toEqual({ ...body, ...options });
    }
  });
});

describe("scene conflict flow", () => {
  it("intercepts options before the toast; Remove repeats the geometry with a new id and only required flags", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response({ detail: detail() }, 422)).mockResolvedValueOnce(response(view)); vi.stubGlobal("fetch", fetch);
    await sceneEdit("Rotate", (options) => api.sceneCommand("p", command, options));
    expect(sceneRefusal.getState().pending?.detail).toEqual(detail()); expect(uiStore.getState().state.toasts).toEqual([]);
    await confirmSceneRefusal("remove_modules");
    const before = JSON.parse(fetch.mock.calls[0][1].body); const after = JSON.parse(fetch.mock.calls[1][1].body);
    expect(after.command.command_id).not.toBe(before.command.command_id);
    expect(after).toEqual({ command: { ...before.command, command_id: after.command.command_id }, on_module_conflict: "remove_modules", discard_dependent_strings: true });
    expect(uiStore.getState().state.past).toHaveLength(1);
  });
  it.each([false, true])("only sends required discard flags (required=%s)", async (required) => {
    const refusal = detail(); refusal.options.refill_field.requires_discard_manual_layout = required;
    refusal.options.refill_field.string_ids = required ? ["string2"] : [];
    const op = vi.fn().mockRejectedValueOnce(new ApiError("Conflict", 422, refusal)).mockResolvedValueOnce(view);
    await sceneEdit("Edit", op); await confirmSceneRefusal("refill_field");
    expect(op.mock.calls[1][0]).toEqual({ on_module_conflict: "refill_field", ...(required ? { discard_dependent_strings: true, discard_manual_layout: true } : {}) });
  });
  it("removes unstrung modules without a string flag and Cancel sends nothing", async () => {
    const refusal = detail(); refusal.options.remove_modules.string_ids = [];
    const op = vi.fn().mockRejectedValueOnce(new ApiError("Conflict", 422, refusal)).mockResolvedValue(view);
    await sceneEdit("Edit", op); cancelSceneRefusal(); expect(op).toHaveBeenCalledTimes(1);
    op.mockRejectedValueOnce(new ApiError("Conflict", 422, refusal)); await sceneEdit("Edit", op); await confirmSceneRefusal("remove_modules");
    expect(op.mock.calls[2][0]).toEqual({ on_module_conflict: "remove_modules" });
  });
  it("retains no-options elevation conflicts without destructive choices; normal errors still toast", async () => {
    const blocked = { message: "Elevation creates overlaps", conflicts: [{ module_instance_id: "m1" }] };
    await sceneEdit("Elevation", async () => { throw new ApiError(blocked.message, 422, blocked); });
    expect(sceneRefusal.getState().pending?.detail).toEqual(blocked);
    expect(uiStore.getState().state.toasts).toEqual([]);
    await confirmSceneRefusal("remove_modules"); expect(uiStore.getState().state.past).toEqual([]);
    cancelSceneRefusal();
    await sceneEdit("Ordinary error", async () => { throw new Error("Original error"); });
    expect(uiStore.getState().state.toasts.at(-1)?.text).toBe("Original error");
  });
});

it("blocks a modified engine entity and Discard draft restores all its engine geometry", async () => {
  view = await mockApi.addSurface("p", { name: "Free roof", origin_x_m: 0, origin_y_m: 0, width_m: 8, height_m: 8, base_elevation_m: 1, surface_type: "flat_roof" });
  const { dispatch } = uiStore.getState(); dispatch({ type: "setView", view });
  const entity = uiStore.getState().state.entities[0];
  dispatch({ type: "updateEntity", id: entity.id, patch: { modified: true, pending: ["editVertices"], polygon: [[0, 0], [20, 0], [0, 20]], holes: [[[1, 1], [2, 1], [1, 2]]], plane: { mode: "flat", z_m: 100 } } });
  const call = vi.spyOn(engine, "sceneCommand").mockResolvedValue(view);
  await entitySceneCommand(entity, "rotate", { angle_deg: 30 });
  expect(call).not.toHaveBeenCalled(); expect(uiStore.getState().state.toasts.at(-1)?.text).toBe("Discard the local draft edits first");
  dispatch({ type: "discardEntityDraft", id: entity.id });
  expect(uiStore.getState().state.entities[0]).toEqual(entity);
  await entitySceneCommand(entity, "rotate", { angle_deg: 30 }); expect(call).toHaveBeenCalledTimes(1);
});

it("engine move retains its existing route and returns success or refusal to the 3D caller", async () => {
  view = await mockApi.addSurface("p", { name: "Free roof", origin_x_m: 0, origin_y_m: 0, width_m: 8, height_m: 8, base_elevation_m: 1, surface_type: "flat_roof" });
  uiStore.getState().dispatch({ type: "setView", view });
  const entity = uiStore.getState().state.entities[0];
  const call = vi.spyOn(engine, "moveSceneEntity").mockResolvedValueOnce(view).mockRejectedValueOnce(new ApiError("Conflict", 422, detail()));
  expect(await entitySceneCommand(entity, "move", { dx_m: 2, dy_m: 3 })).toEqual(view);
  expect(call).toHaveBeenCalledWith(view.bundle.project.project_id, { entity_id: entity.id, dx_m: 2, dy_m: 3 }, {});
  expect(await entitySceneCommand(entity, "move", { dx_m: 2, dy_m: 3 })).toBeUndefined();
  expect(sceneRefusal.getState().pending?.detail).toEqual(detail());
  expect(uiStore.getState().state.past).toHaveLength(1);
});

async function roof() {
  const v = await mockApi.addSurface("p", { name: "Roof", origin_x_m: 0, origin_y_m: 0, width_m: 10, height_m: 8, base_elevation_m: 0, surface_type: "flat_roof" });
  return v.bundle.scene.surfaces.at(-1)!.surface_id;
}
async function fill(id: string) {
  return mockApi.createPvField("p", { name: "Field", support_surface_id: id, module_definition_revision_id: "mod-demo-550", orientation: "portrait", azimuth_deg: 0, tilt_deg: 0, module_gap_x_m: 0.02, module_gap_y_m: 0.02, row_pitch_m: 2.4, mounting_height_m: 0.2, perimeter_setback_m: 0.5, obstacle_setback_m: 0.1 });
}
const cmd = (kind: SceneCommandInput["command_type"], id: string, parameters: Record<string, unknown> = {}) => mockApi.sceneCommand("p", { command_type: kind, target_entity_ids: [id], parameters });

describe("demo scene commands", () => {
  it("persists rotate, vertex, exact dimension, elevation and delete; dry run changes nothing", async () => {
    const id = await roof();
    const before = await mockApi.project("p");
    expect((await mockApi.sceneCommand("p", { command_type: "rotate", target_entity_ids: [id], parameters: { angle_deg: 30, origin: [5, 4] } }, { dry_run: true })).dry_run).toBe(true);
    expect(await mockApi.project("p")).toEqual(before);
    let v = await cmd("rotate", id, { angle_deg: 30, origin: [0, 0] });
    expect(v.scene_view.local_features.find((f) => f.id === id)!.polygon[1][0]).toBeCloseTo(10 * Math.cos(Math.PI / 6), 12);
    v = await cmd("move_vertex", id, { vertex_index: 0, target_x_m: -1, target_y_m: 0 });
    expect(v.scene_view.local_features.find((f) => f.id === id)!.polygon[0]).toEqual([-1, 0]);
    v = await cmd("edit_exact_dimension", id, { edge_index: 0, length_m: 6 });
    const ring = v.scene_view.local_features.find((f) => f.id === id)!.polygon;
    expect(Math.hypot(ring[1][0] - ring[0][0], ring[1][1] - ring[0][1])).toBeCloseTo(6, 12);
    v = await cmd("edit_elevation", id, { base_elevation_m: 4 }); expect(v.bundle.scene.surfaces[0].base_elevation_m).toBe(4);
    v = await cmd("delete", id); expect(v.bundle.scene.surfaces).toEqual([]);
  });
  it("creates polygon surfaces and obstacles, and refuses atomic multi-delete of a support", async () => {
    const id = await roof(); await fill(id);
    let v = await mockApi.sceneCommand("p", { command_type: "draw_polygon", target_entity_ids: [], parameters: { name: "Triangle", vertices: polygon.vertices, base_elevation_m: 3, surface_type: "flat_roof" } });
    const free = v.bundle.scene.surfaces.at(-1)!.surface_id;
    v = await mockApi.addPolygonObstacle("p", polygon);
    expect(v.bundle.scene.obstacles.at(-1)!.obstacle_type).toBe("extruded_polygon");
    expect(v.scene_view.local_features.find((f) => f.name === polygon.name)!.polygon).toEqual(polygon.vertices);
    const before = await mockApi.project("p");
    await expect(mockApi.sceneCommand("p", { command_type: "delete", target_entity_ids: [free, id], parameters: {} })).rejects.toThrow(/PV fields/);
    expect(await mockApi.project("p")).toEqual(before);
    for (const kind of ["rotate", "move_vertex", "edit_exact_dimension", "move"] as const) await expect(cmd(kind, id)).rejects.toThrow(/PV fields/);
  });
  it("previews conflicts without saving, removes exactly previewed modules and whole affected strings", async () => {
    const id = await roof(); let v = await fill(id);
    const field = v.bundle.scene.pv_fields[0].pv_field_id;
    v = await mockApi.createStrings("p", { string_length: 6, pv_field_id: field, allow_shorter_remainder: true });
    const before = v;
    const preview = await mockApi.addObstacle("p", box, { dry_run: true });
    expect(preview.options!.remove_modules.module_count).toBeGreaterThan(0);
    expect(preview.options!.refill_field.available).toBe(false); expect(preview.options!.refill_field.reason).toMatch(/Demo/);
    await expect(mockApi.addObstacle("p", box)).rejects.toBeInstanceOf(ApiError);
    expect(await mockApi.project("p")).toEqual(before);
    v = await mockApi.addObstacle("p", box, { on_module_conflict: "remove_modules", discard_dependent_strings: true });
    const gone = before.bundle.scene.module_instances.filter((m) => !v.bundle.scene.module_instances.some((n) => n.module_instance_id === m.module_instance_id)).map((m) => m.module_instance_id).sort();
    expect(gone).toEqual(preview.options!.remove_modules.module_instance_ids);
    expect(v.bundle.electrical_design.strings.map((s) => s.string_id)).toEqual(before.bundle.electrical_design.strings.filter((s) => !preview.options!.remove_modules.string_ids.includes(s.string_id)).map((s) => s.string_id));
    expect(v.bundle.scene.pv_fields[0].layout_status).toBe("manual");
    const obstacle = v.bundle.scene.obstacles.at(-1)!.obstacle_id;
    const moved = await mockApi.moveSceneEntity("p", { entity_id: obstacle, dx_m: 20, dy_m: 0 });
    expect(moved.scene_view.local_features.find((f) => f.id === obstacle)!.polygon[0][0]).toBe(21);
  });
});
