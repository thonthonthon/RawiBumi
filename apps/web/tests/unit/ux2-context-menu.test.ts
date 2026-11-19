import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import i18n from "../../src/i18n";
import { buildMenu, type MenuState } from "../../src/canvas/contextMenu";
import { planeMarks } from "../../src/canvas/plan/planeMarks";
import { ELECTRICAL_TOOLS, TOOLS } from "../../src/canvas/tools";
import { nextMenuIndex, placeMenu } from "../../src/ui/ContextMenu";
import { planeZ, referenceEdgePlane, vertexLabel, type PlaneDef, type Vec2 } from "../../src/geometry";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { useEntityEdits } from "../../src/canvas/useEntityEdits";
import { resetStore, uiStore, type Entity } from "../../src/state/store";
vi.mock("react", async (load) => ({ ...await load<typeof import("react")>(), useCallback: (fn: unknown) => fn }));
vi.mock("../../src/state/store", async (load) => ({ ...await load<typeof import("../../src/state/store")>(), useActions: () => uiStore.getState(), useUI: (select: (state: unknown) => unknown) => select(uiStore.getState().state) }));

const t = (key: string, o?: Record<string, unknown>) => i18n.t(key, o);
beforeAll(async () => { await i18n.changeLanguage("en"); });
const square: Vec2[] = [[0, 0], [10, 0], [10, 6], [0, 6]];
const entity = (over: Partial<Entity> = {}): Entity => ({ id: "roof", kind: "surface", subtype: "flat_roof", name: "Roof", polygon: square, holes: [],
  plane: { mode: "flat", z_m: 6 }, height_m: 0, source: "engine", modified: false, pending: [], locked: false, hidden: false, hostsPvField: false, ...over });
const state = (over: Partial<MenuState> = {}): MenuState => ({ target: { kind: "selection" }, selected: [entity()], selectedModules: 0, activeTables: 0,
  step: "scene", busy: false, canUndo: true, canRedo: false, undoLabel: "Scene command move", tools: TOOLS, anyVisible: true, meshIds: new Set(), ...over });
const ids = (s: MenuState) => buildMenu(s, t).map((i) => i.id);
const item = (s: MenuState, id: string) => buildMenu(s, t).find((i) => i.id === id)!;

it("always starts with Undo and Redo, matching the toolbar's enabled state", () => {
  expect(ids(state()).slice(0, 2)).toEqual(["undo", "redo"]);
  expect(item(state(), "undo")).toMatchObject({ disabled: undefined, keys: "$mod+z", title: "Scene command move" });
  expect(item(state(), "redo").disabled).toBe("Nothing to redo");
  expect(item(state({ busy: true }), "undo").disabled).toBe(t("commands.running"));
});

it("offers a roof's actions in order, and an obstacle's without roof-only items", () => {
  expect(ids(state())).toEqual(["undo", "redo", "properties", "zoomSelection", "duplicate", "move", "rotate", "addHole", "lock", "hide", "delete"]);
  const obstacle = state({ selected: [entity({ kind: "obstacle", subtype: "box" })] });
  expect(ids(obstacle)).not.toContain("addHole");
  expect(ids({ ...obstacle, target: { kind: "edge", entityId: "roof", ring: 0, index: 0, at: [1, 0] } })).not.toContain("referenceEdge");
});

it("keeps disabled items visible with their reason", () => {
  const locked = state({ selected: [entity({ locked: true })] });
  expect(item(locked, "move").disabled).toBe(t("tools.locked", { name: "Roof" }));
  expect(item(locked, "delete").disabled).toBe(t("tools.locked", { name: "Roof" }));
  expect(ids(locked)).toContain("unlock");
  expect(item(locked, "duplicate").disabled).toBeUndefined();
  const drafted = state({ selected: [entity({ modified: true })] });
  expect(item(drafted, "rotate").disabled).toBe(t("s7b.discardReason"));
  expect(item(drafted, "duplicate").disabled).toBe(t("s7b.discardReason"));
  expect(item(state({ busy: true }), "duplicate").disabled).toBe(t("commands.running"));
  expect(item(state({ meshIds: new Set(["roof"]) }), "duplicate").disabled).toBe("Imported meshes are read-only");
});

it("vertex and edge targets put their own items first", () => {
  const vertex = state({ target: { kind: "vertex", entityId: "roof", ring: 0, index: 1 } });
  expect(ids(vertex).slice(2, 4)).toEqual(["deleteVertex", "properties"]);
  expect(item(vertex, "deleteVertex").disabled).toBeUndefined();
  const triangle = state({ selected: [entity({ polygon: [[0, 0], [1, 0], [0, 1]] })], target: { kind: "vertex", entityId: "roof", ring: 0, index: 0 } });
  expect(item(triangle, "deleteVertex").disabled).toBe("A polygon needs at least 3 vertices");
  const edge = state({ target: { kind: "edge", entityId: "roof", ring: 0, index: 2, at: [5, 6] } });
  expect(ids(edge).slice(2, 5)).toEqual(["insertVertex", "edgeLength", "referenceEdge"]);
  const holeEdge = state({ selected: [entity({ holes: [[[2, 2], [4, 2], [4, 4], [2, 4]]] })], target: { kind: "edge", entityId: "roof", ring: 1, index: 0, at: [3, 2] } });
  expect(item(holeEdge, "insertVertex").disabled).toBeUndefined();
  expect(item(holeEdge, "referenceEdge").disabled).toBe("Only for the outer boundary");
  const holeVertex = state({ selected: [entity({ holes: [[[2, 2], [4, 2], [4, 4], [2, 4]]] })], target: { kind: "vertex", entityId: "roof", ring: 1, index: 0 } });
  expect(item(holeVertex, "deleteVertex").disabled).toBeUndefined();
});

it("several objects, modules and mixed selections get their own menus", () => {
  const many = state({ selected: [entity(), entity({ id: "b", name: "B", locked: true })] });
  expect(ids(many)).toEqual(["undo", "redo", "zoomSelection", "duplicate", "lock", "hide", "delete", "clearSelection"]);
  expect(item(many, "duplicate").disabled).toBe("Duplicate one object at a time");
  expect(item(many, "delete").label).toBe("Delete (1)");
  const allLocked = state({ selected: [entity({ locked: true }), entity({ id: "b", locked: true })] });
  expect(ids(allLocked)).toContain("unlock");
  expect(item(allLocked, "delete").disabled).toBe(t("s13a.lockedCount", { count: 2 }));
  const modules = state({ selected: [], selectedModules: 4, step: "layout", activeTables: 0 });
  expect(ids(modules)).toEqual(["undo", "redo", "deleteModules", "deleteTables", "zoomSelection", "clearSelection"]);
  expect(item(modules, "deleteTables").disabled).toBe("No active tables in the selection");
  expect(ids(state({ selected: [], selectedModules: 4, step: "electrical" }))).not.toContain("deleteModules");
  expect(item(state({ selectedModules: 2 }), "delete").disabled).toBe(t("s13a.mixedDelete"));
});

it("the empty canvas keeps the selection but offers selection, view and the step's start tools", () => {
  const empty = state({ target: { kind: "empty" } });
  expect(ids(empty)).toEqual(["undo", "redo", "selectAll", "clearSelection", "zoomAll", "tool:rect_engine", "tool:polygon", "tool:box_obstacle", "tool:obstacle", "tool:keepout", "tool:measure"]);
  expect(item(state({ target: { kind: "empty" }, selected: [] }), "clearSelection").disabled).toBe("Nothing is selected");
  expect(item(state({ target: { kind: "empty" }, anyVisible: false }), "selectAll").disabled).toBe("Nothing to select");
  const electrical = ids(state({ target: { kind: "empty" }, tools: ELECTRICAL_TOOLS, step: "electrical" }));
  expect(electrical.filter((i) => i.startsWith("tool:"))).toEqual(["tool:string_path", "tool:assign", "tool:lasso"]);
});

it("while drawing, the menu finishes, steps back or cancels", () => {
  expect(ids(state({ target: { kind: "drawing", points: 2 } }))).toEqual(["undo", "redo", "finishPolygon", "removePoint", "cancelDrawing"]);
  expect(item(state({ target: { kind: "drawing", points: 2 } }), "finishPolygon").disabled).toBe("A polygon needs at least 3 points");
  expect(item(state({ target: { kind: "drawing", points: 3 } }), "finishPolygon").disabled).toBeUndefined();
});

it("keyboard movement wraps and the menu stays inside its container", () => {
  expect([nextMenuIndex("ArrowDown", 2, 3), nextMenuIndex("ArrowUp", 0, 3), nextMenuIndex("Home", 2, 3), nextMenuIndex("End", 0, 3), nextMenuIndex("x", 0, 3)]).toEqual([0, 2, 0, 2, null]);
  expect(nextMenuIndex("ArrowDown", 0, 0)).toBeNull();
  expect(placeMenu({ x: 10, y: 10 }, { w: 200, h: 300 }, { w: 800, h: 600 })).toEqual({ x: 10, y: 10 });
  expect(placeMenu({ x: 700, y: 500 }, { w: 200, h: 300 }, { w: 800, h: 600 })).toEqual({ x: 596, y: 200 });
  expect(placeMenu({ x: 100, y: 100 }, { w: 400, h: 700 }, { w: 300, h: 600 })).toEqual({ x: 4, y: 4 });
});

it("plane marks follow planeZ: reference edge high, arrow downhill, nothing on a flat roof", () => {
  expect(planeMarks(square, { mode: "flat", z_m: 3 })).toEqual({ referenceEdge: null, arrow: null, high: null, low: null });
  const edge: PlaneDef = { mode: "edge_tilt", edgeIndex: 2, zRef_m: 8, tilt_deg: 10, direction: "down" };
  const marks = planeMarks(square, edge);
  expect(marks.referenceEdge).toBe(2);
  expect(planeZ(square, edge, marks.high!)).toBeCloseTo(8, 9);
  expect(marks.high![1]).toBe(6); expect(marks.low![1]).toBe(0);
  expect(marks.arrow!.to[1]).toBeLessThan(marks.arrow!.from[1]);
  const up = planeMarks(square, { ...edge, direction: "up" });
  expect(up.arrow!.to[1]).toBeGreaterThan(up.arrow!.from[1]);
  const south = planeMarks(square, { mode: "datum_tilt_azimuth", datum: [5, 3], z_m: 6, tilt_deg: 15, slopeAzimuth_deg: 180 });
  expect(south.referenceEdge).toBeNull();
  expect(south.arrow!.to[1]).toBeLessThan(south.arrow!.from[1]);
  expect(Math.abs(south.arrow!.to[0] - south.arrow!.from[0])).toBeLessThan(1e-6);
  expect(planeMarks(square, { ...edge, tilt_deg: 0 }).arrow).toBeNull();
});

it("the reference edge helper keeps edge-tilt values and uses the Inspector's defaults otherwise", () => {
  expect(referenceEdgePlane({ mode: "flat", z_m: 4 }, 2)).toEqual({ mode: "edge_tilt", edgeIndex: 2, zRef_m: 4, tilt_deg: 5, direction: "down" });
  expect(referenceEdgePlane({ mode: "datum_tilt_azimuth", datum: [0, 0], z_m: 3, tilt_deg: 9, slopeAzimuth_deg: 90 }, 1)).toEqual({ mode: "edge_tilt", edgeIndex: 1, zRef_m: 8, tilt_deg: 5, direction: "down" });
  expect(referenceEdgePlane({ mode: "edge_tilt", edgeIndex: 0, zRef_m: 7, tilt_deg: 12, direction: "up" }, 3)).toEqual({ mode: "edge_tilt", edgeIndex: 3, zRef_m: 7, tilt_deg: 12, direction: "up" });
  expect([vertexLabel(0), vertexLabel(25), vertexLabel(26)]).toEqual(["A", "Z", "V27"]);
});

beforeEach(() => { resetStore(); setDemoLatency(0); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("Duplicate sends one engine copy beside the original, through the scene-edit path", async () => {
  const view = await mockApi.project("demo-project");
  uiStore.getState().dispatch({ type: "setView", view });
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(view), { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  await useEntityEdits().duplicate(entity({ id: "srf-x", polygon: square }));
  expect(fetch).toHaveBeenCalledTimes(1);
  const body = JSON.parse(fetch.mock.calls[0][1].body);
  expect(body.command).toMatchObject({ command_type: "copy", target_entity_ids: ["srf-x"], parameters: { dx_m: 11, dy_m: 0 } });
});

it("the demo engine copies a roof beside itself, keeps its fields, undoes it, and refuses two targets", async () => {
  const view = await mockApi.project("demo-project");
  const roof = view.bundle.scene.surfaces.find((s) => view.bundle.scene.pv_fields.some((f) => f.support_surface_id === s.surface_id))!;
  const fields = view.bundle.scene.pv_fields.length;
  const copied = await mockApi.sceneCommand("demo-project", { command_type: "copy", target_entity_ids: [roof.surface_id], parameters: { dx_m: 50, dy_m: 0 } });
  const clone = copied.bundle.scene.surfaces.find((s) => s.name === `${roof.name} copy`)!;
  expect(clone.surface_id).not.toBe(roof.surface_id);
  expect(copied.bundle.scene.pv_fields).toHaveLength(fields);
  const undone = await mockApi.undo("demo-project", { expected_project_revision_id: copied.bundle.project.project_revision.project_revision_id, expected_entry_id: "demo" });
  expect(undone.bundle.scene.surfaces.some((s) => s.surface_id === clone.surface_id)).toBe(false);
  await expect(mockApi.sceneCommand("demo-project", { command_type: "copy", target_entity_ids: [roof.surface_id, roof.surface_id], parameters: { dx_m: 1, dy_m: 0 } })).rejects.toThrow("invalid count");
});

it("a Duplicate that lands on modules opens the existing conflict choice instead of an error", async () => {
  const { sceneRefusal } = await import("../../src/state/history");
  const view = await mockApi.project("demo-project");
  uiStore.getState().dispatch({ type: "setView", view });
  const detail = { message: "Obstacle overlaps modules.", conflicts: [{ code: "module_obstacle_overlap", module_instance_id: "m1", other_id: "o2", pv_field_id: "f" }], options: {} };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail }), { status: 422, headers: { "Content-Type": "application/json" } })));
  await useEntityEdits().duplicate(entity({ id: "obs-1", kind: "obstacle", subtype: "box", name: "Vent" }));
  expect(sceneRefusal.getState().pending?.detail.conflicts).toHaveLength(1);
  expect(uiStore.getState().state.toasts.filter((x) => x.tone === "error")).toEqual([]);
  sceneRefusal.setState({ pending: null });
});
