import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
import { engine } from "../../src/client";
import { ownBox, rotateClockwise } from "../../src/canvas/plan/edit";
import { useEntityEdits } from "../../src/canvas/useEntityEdits";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { resetStore, uiStore } from "../../src/state/store";
import { Inspector } from "../../src/Inspector";
import { Field, NumberInput } from "../../src/ui/kit";
import type { ReferenceAnchor } from "../../src/types";

const h = vi.hoisted(() => ({ slots: [] as unknown[], cursor: 0 }));
vi.mock("react", async load => ({ ...await load<typeof import("react")>(), useMemo: (f: () => unknown) => f(), useCallback: (f: unknown) => f,
  useState: (initial: unknown) => { const i = h.cursor++; if (!(i in h.slots)) h.slots[i] = initial; return [h.slots[i], (v: unknown) => { h.slots[i] = v; }]; } }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }), initReactI18next: { type: "3rdParty", init() {} } }));
vi.mock("../../src/state/store", async load => ({ ...await load<typeof import("../../src/state/store")>(),
  useActions: () => uiStore.getState(), useUI: (select: (state: unknown) => unknown) => select(uiStore.getState().state) }));

const ring = rotateClockwise([[0, 0], [10, 0], [10, 6], [0, 6]], [0, 0], 30);
const values = ["start", "center", "end"] as const;
let id: string;
function entity() { return uiStore.getState().state.entities.find(e => e.id === id)!; }
function tree(value: unknown): ReactElement<any>[] {
  if (Array.isArray(value)) return value.flatMap(tree);
  if (!isValidElement(value)) return [];
  const n = value as ReactElement<any>; return [n, ...tree(n.props.children)];
}
function inspector() {
  h.cursor = 0;
  const child = tree(Inspector()).find(n => typeof n.type === "function" && n.type.name === "EntityInspector")!;
  return tree((child.type as Function)(child.props));
}
function typeField(label: string, value: number) {
  const field = inspector().find(n => n.type === Field && n.props.label === label)!;
  const input = tree(field.props.children).find(n => n.type === NumberInput)!;
  expect(input.props.commit).toBe(true);
  input.props.onChange(value);
}

beforeEach(async () => {
  resetStore(); setDemoLatency(0); h.slots = [];
  vi.spyOn(engine, "sceneCommand").mockImplementation((_pid, cmd, options) => mockApi.sceneCommand("p", cmd, options));
  await mockApi.createProject({ name: "BLD1", latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" });
  const view = await mockApi.sceneCommand("p", { command_type: "draw_polygon", target_entity_ids: [], parameters: { name: "Roof", surface_type: "flat_roof", vertices: ring } });
  id = view.bundle.scene.surfaces.at(-1)!.surface_id;
  uiStore.getState().dispatch({ type: "setView", view });
  uiStore.getState().dispatch({ type: "select", ids: [id] });
});
afterEach(() => { vi.restoreAllMocks(); resetStore(); setDemoLatency(1); });

it("locates all nine own-box points on a rotated rectangle, including clockwise winding", () => {
  for (const u of values) for (const v of values) {
    const fraction = { start: 0, center: .5, end: 1 };
    const expected = rotateClockwise([[10 * fraction[u], 6 * fraction[v]]], [0, 0], 30)[0];
    const box = ownBox(ring, { u, v });
    box.point.forEach((x, axis) => expect(x).toBeCloseTo(expected[axis], 9));
    expect(box.bearing).toBeCloseTo(120, 9);
    expect(box.length).toBeCloseTo(10, 9); expect(box.width).toBeCloseTo(6, 9);
  }
  const reversed = [...ring].reverse();
  expect(ownBox(reversed).point).toEqual(ownBox(ring).point);
});

it.each([0, 1] as const)("Position axis %i typed in Inspector sends the anchor delta", async axis => {
  await useEntityEdits().setReferenceAnchor(entity(), { u: "center", v: "center" });
  const point = ownBox(entity().polygon, { u: "center", v: "center" }).point;
  const move = vi.spyOn(engine, "moveSceneEntity").mockImplementation((_pid, input, options) => mockApi.moveSceneEntity("p", input, options));
  typeField(axis === 0 ? "bld1.positionX" : "bld1.positionY", 20);
  await vi.waitFor(() => expect(move).toHaveBeenCalledWith(expect.any(String), { entity_id: id, dx_m: axis === 0 ? 20 - point[0] : 0, dy_m: axis === 1 ? 20 - point[1] : 0 }, {}));
  await vi.waitFor(() => expect(uiStore.getState().state.busy).toBeNull());
});

it("Orientation typed in Inspector rotates to the bearing about the anchor", async () => {
  await useEntityEdits().setReferenceAnchor(entity(), { u: "end", v: "center" });
  const point = ownBox(entity().polygon, { u: "end", v: "center" }).point;
  const call = vi.spyOn(engine, "sceneCommand").mockImplementation((_pid, cmd, options) => mockApi.sceneCommand("p", cmd, options));
  typeField("bld1.orientation", 45);
  await vi.waitFor(() => expect(call).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ command_type: "rotate", parameters: { angle_deg: -75, origin: point } }), {}));
  await vi.waitFor(() => expect(uiStore.getState().state.busy).toBeNull());
  expect(ownBox(entity().polygon).bearing).toBeCloseTo(45, 9);
});

it("moves by u/v distances using a single scene move", async () => {
  const move = vi.spyOn(engine, "moveSceneEntity").mockImplementation((_pid, input, options) => mockApi.moveSceneEntity("p", input, options));
  await useEntityEdits().moveBy(entity(), [2, 3], true);
  const input = move.mock.calls[0][1];
  expect(input.dx_m).toBeCloseTo(2 * Math.sqrt(3) / 2 + 1.5, 9);
  expect(input.dy_m).toBeCloseTo(-1 + 3 * Math.sqrt(3) / 2, 9);
});

it.each([["bld1.length", 0], ["bld1.width", 1]] as const)("%s typed sends rectangle dimension and keeps the centre", async (label, edge) => {
  await useEntityEdits().setReferenceAnchor(entity(), { u: "center", v: "center" });
  const anchor: ReferenceAnchor = { u: "center", v: "center" }, point = ownBox(entity().polygon, anchor).point;
  const call = vi.spyOn(engine, "sceneCommand").mockImplementation((_pid, cmd, options) => mockApi.sceneCommand("p", cmd, options));
  typeField(label, 14);
  await vi.waitFor(() => expect(call).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ command_type: "edit_exact_dimension", parameters: { edge_index: edge, length_m: 14, preserve: "rectangle" } }), {}));
  await vi.waitFor(() => expect(uiStore.getState().state.busy).toBeNull());
  ownBox(entity().polygon, anchor).point.forEach((x, i) => expect(x).toBeCloseTo(point[i], 9));
});

it("demo rejects invalid anchors without saving", async () => {
  const before = await mockApi.project("p");
  await expect(mockApi.sceneCommand("p", { command_type: "set_reference_anchor", target_entity_ids: [id], parameters: { u: "bad", v: "start" } })).rejects.toThrow("Invalid reference anchor");
  expect(await mockApi.project("p")).toEqual(before);
});

it("demo stores and undoes the reference choice without moving geometry", async () => {
  const before = await mockApi.project("p");
  const chosen = await mockApi.sceneCommand("p", { command_type: "set_reference_anchor", target_entity_ids: [id], parameters: { u: "center", v: "end" } });
  expect(chosen.bundle.scene.surfaces.find(s => s.surface_id === id)!.reference_anchor).toEqual({ u: "center", v: "end" });
  expect(chosen.scene_view.local_features.find(f => f.id === id)!.polygon).toEqual(ring);
  const undone = await mockApi.undo("p");
  expect(undone.bundle.scene.surfaces).toEqual(before.bundle.scene.surfaces);
});

it("demo resizes about all nine anchors for either winding", async () => {
  for (const vertices of [ring, [...ring].reverse()]) for (const u of values) for (const v of values) {
    let view = await mockApi.sceneCommand("p", { command_type: "draw_polygon", target_entity_ids: [], parameters: { name: "Nine", surface_type: "flat_roof", vertices } });
    const target = view.bundle.scene.surfaces.at(-1)!.surface_id;
    await mockApi.sceneCommand("p", { command_type: "set_reference_anchor", target_entity_ids: [target], parameters: { u, v } });
    const point = ownBox(vertices, { u, v }).point;
    for (const edge_index of [0, 1]) {
      view = await mockApi.sceneCommand("p", { command_type: "edit_exact_dimension", target_entity_ids: [target], parameters: { edge_index, length_m: 14, preserve: "rectangle" } });
      const polygon = view.scene_view.local_features.find(f => f.id === target)!.polygon;
      ownBox(polygon, { u, v }).point.forEach((x, i) => expect(x).toBeCloseTo(point[i], 9));
    }
  }
});
