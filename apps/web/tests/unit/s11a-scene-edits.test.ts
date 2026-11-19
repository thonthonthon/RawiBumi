import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../src/api";
import { edgeMoveParameters, entitySceneCommand } from "../../src/canvas/useEntityEdits";
import { offsetEdge } from "../../src/canvas/plan/edit";
import { TOOLS } from "../../src/canvas/tools";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { PENDING } from "../../src/pending";
import { cancelSceneRefusal } from "../../src/state/history";
import { resetStore, uiStore } from "../../src/state/store";
import type { ProjectView, SceneCommandInput } from "../../src/types";
import type { Vec2 } from "../../src/geometry";

let view: ProjectView;
const project = { name: "S11a demo", latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" as const };
const polygon: Vec2[] = [[0, 0], [8, 0], [8, 8], [0, 8]];
const commands: Array<[SceneCommandInput["command_type"], Record<string, unknown>]> = [
  ["insert_vertex", { edge_index: 0, x_m: 4, y_m: -1 }],
  ["delete_vertex", { vertex_index: 1 }],
  ["move_edge", { edge_index: 2, dx_m: .25, dy_m: 1.5 }],
  ["edit_height", { height_m: 2.75 }]
];
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
beforeEach(async () => {
  setDemoLatency(0); resetStore(); cancelSceneRefusal();
  view = await mockApi.createProject(project);
  view = await mockApi.sceneCommand("demo-project", { command_type: "draw_polygon", target_entity_ids: [], parameters: { name: "Free roof", surface_type: "flat_roof", vertices: polygon } });
  uiStore.getState().dispatch({ type: "setView", view });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); cancelSceneRefusal(); resetStore(); setDemoLatency(1); });

describe("S11a canonical command bodies", () => {
  it.each(commands)("sends %s parameters unchanged through the command envelope", async (kind, parameters) => {
    const fetch = vi.fn().mockResolvedValue(response(view)); vi.stubGlobal("fetch", fetch);
    const options = { dry_run: true as const, dependent_fields: "apply" as const, on_module_conflict: "remove_modules" as const, discard_dependent_strings: true };
    await api.sceneCommand("project/id", { command_id: "s11a", command_type: kind, target_entity_ids: ["entity"], parameters }, options);
    expect(fetch.mock.calls[0][0]).toBe("/api/projects/project%2Fid/scene/commands");
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ command: { schema_name: "SceneEditorCommand", schema_version: "0.1", command_id: "s11a", command_type: kind, target_entity_ids: ["entity"], parameters }, ...options });
  });
  it("uses exactly the same edge vector as the preview, including the closing edge and both windings", () => {
    const shapes: Vec2[][] = [polygon, [[1, 2], [7, 4], [6, 9], [-2, 7]]];
    for (const shape of shapes) for (const vertices of [shape, [...shape].reverse()]) for (const offset of [-1.3, .75]) for (let edge = 0; edge < vertices.length; edge++) {
      const p = edgeMoveParameters(vertices, edge, offset);
      const expected = offsetEdge(vertices, edge, offset);
      for (let i = 0; i < vertices.length; i++) for (let axis = 0; axis < 2; axis++) {
        const moved = i === edge || i === (edge + 1) % vertices.length;
        const value = vertices[i][axis] + (moved ? (axis === 0 ? p.dx_m : p.dy_m) : 0);
        expect(Math.abs(value - expected[i][axis])).toBeLessThanOrEqual(1e-9);
      }
    }
  });
  it("blocks every new command on an engine entity with an unsaved hole draft", async () => {
    const entity = uiStore.getState().state.entities[0];
    uiStore.getState().dispatch({ type: "updateEntity", id: entity.id, patch: { modified: true, pending: ["editVertices"] } });
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    for (const [kind, parameters] of commands) await entitySceneCommand(entity, kind, parameters);
    expect(fetch).not.toHaveBeenCalled();
    expect(uiStore.getState().state.toasts.some((t) => t.text.includes("Discard"))).toBe(true);
  });
});

it.each(["exclusion_area", "walkway"])("maps a persisted %s to an engine keep-out with no pending badge", async (surface_type) => {
  view = await mockApi.sceneCommand("demo-project", { command_type: "draw_polygon", target_entity_ids: [], parameters: { name: "Keep-out", surface_type, vertices: [[12, 0], [14, 0], [14, 2], [12, 2]], usable_for_pv: false } });
  uiStore.getState().dispatch({ type: "setView", view });
  const entity = uiStore.getState().state.entities.find((e) => e.name === "Keep-out")!;
  expect(entity).toMatchObject({ kind: "keepout", source: "engine", modified: false, pending: [], subtype: surface_type });
  expect(TOOLS.find((t) => t.tool === "keepout")?.pending).toBeNull();
  expect(PENDING).not.toHaveProperty("keepout");
  expect(PENDING).not.toHaveProperty("editVertices");
  expect(PENDING).not.toHaveProperty("planeDefinition");
});

it("demo insert, edge vector, delete and obstacle height persist through the common session", async () => {
  const id = view.bundle.scene.surfaces[0].surface_id;
  view = await mockApi.sceneCommand("demo-project", { command_type: "insert_vertex", target_entity_ids: [id], parameters: { edge_index: 0, x_m: 4, y_m: -1 } });
  expect(view.scene_view.local_features[0].polygon).toEqual([[0, 0], [4, -1], [8, 0], [8, 8], [0, 8]]);
  view = await mockApi.sceneCommand("demo-project", { command_type: "delete_vertex", target_entity_ids: [id], parameters: { vertex_index: 1 } });
  expect(view.scene_view.local_features[0].polygon).toEqual(polygon);
  const parameters = edgeMoveParameters(polygon, 2, 1.25);
  view = await mockApi.sceneCommand("demo-project", { command_type: "move_edge", target_entity_ids: [id], parameters });
  expect(view.scene_view.local_features[0].polygon).toEqual(offsetEdge(polygon, 2, 1.25));
  view = await mockApi.addObstacle("demo-project", { name: "Free box", origin_x_m: 20, origin_y_m: 0, width_m: 2, depth_m: 2, base_elevation_m: 0, height_m: 1 });
  const oid = view.bundle.scene.obstacles[0].obstacle_id;
  view = await mockApi.sceneCommand("demo-project", { command_type: "edit_height", target_entity_ids: [oid], parameters: { height_m: 2.75 } });
  expect(view.bundle.scene.obstacles[0].height_m).toBe(2.75);
  uiStore.getState().dispatch({ type: "setView", view });
  expect(uiStore.getState().state.entities.every((e) => e.source === "engine" && !e.modified && !e.pending.length)).toBe(true);
});

it("demo keep-out refusal does not save, then removal keeps exactly the preview's module ids out", async () => {
  const sid = view.bundle.scene.surfaces[0].surface_id;
  view = await mockApi.createPvField("demo-project", { name: "Demo field", support_surface_id: sid, module_definition_revision_id: "mod-demo-550", orientation: "portrait", azimuth_deg: 0, tilt_deg: 10, module_gap_x_m: .02, module_gap_y_m: .02, row_pitch_m: 3.1, mounting_height_m: .2, perimeter_setback_m: .3, obstacle_setback_m: .3 });
  const before = structuredClone(view), module = view.scene_view.local_features.find((f) => f.category === "module")!;
  const x = Math.min(...module.polygon.map((p) => p[0])) + .1, y = Math.min(...module.polygon.map((p) => p[1])) + .1;
  const command: SceneCommandInput = { command_type: "draw_polygon", target_entity_ids: [], parameters: { name: "Zone", surface_type: "exclusion_area", vertices: [[x, y], [x + .3, y], [x + .3, y + .3], [x, y + .3]] } };
  const preview = await mockApi.sceneCommand("demo-project", command, { dry_run: true });
  expect(preview.options?.remove_modules.module_count).toBe(1);
  await expect(mockApi.sceneCommand("demo-project", command)).rejects.toMatchObject({ status: 422 });
  expect(await mockApi.project("demo-project")).toEqual(before);
  view = await mockApi.sceneCommand("demo-project", command, { on_module_conflict: "remove_modules" });
  const removed = before.bundle.scene.module_instances.filter((m) => !view.bundle.scene.module_instances.some((n) => n.module_instance_id === m.module_instance_id)).map((m) => m.module_instance_id);
  expect(removed).toEqual(preview.options!.remove_modules.module_instance_ids);
});
