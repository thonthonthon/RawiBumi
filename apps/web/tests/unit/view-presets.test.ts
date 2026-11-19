import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { OrthographicCamera, PerspectiveCamera, Vector3 } from "three";
import i18n from "../../src/i18n";
import { planeZ, type Vec2 } from "../../src/geometry";
import { presetCamera, selectedRoof, VIEW_PRESETS, type GeometryView } from "../../src/canvas/viewPresets";
import { ViewControls } from "../../src/canvas/ViewControls";
import { ContextMenu } from "../../src/ui/ContextMenu";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { resetStore, uiStore, viewStorageKey, type Entity, type UIState } from "../../src/state/store";

vi.mock("../../src/state/store", async load => ({
  ...await load<typeof import("../../src/state/store")>(),
  useUI: (select: (s: UIState) => unknown) => select(uiStore.getState().state),
  useActions: () => uiStore.getState()
}));
beforeAll(async () => { setDemoLatency(0); await i18n.changeLanguage("en"); });
afterEach(() => { resetStore(); vi.unstubAllGlobals(); });
const frame = { centre: [4, 7, 10] as [number, number, number], span: 20 };
const roof = (plane: Entity["plane"], polygon: Vec2[] = [[0, 0], [8, 6], [5, 10], [-3, 4]]): Entity => ({
  id: "roof", kind: "surface", subtype: "pitched_roof", name: "Roof", polygon, plane, holes: [], height_m: 0,
  source: "engine", modified: false, pending: [], hidden: false, locked: false, hostsPvField: false
});

it.each<[GeometryView, number[]]>([
  ["plan", [0, 0, -1]], ["front", [0, 1, 0]], ["back", [0, -1, 0]],
  ["left", [1, 0, 0]], ["right", [-1, 0, 0]]
])("%s is orthographic and looks along the scene axes", (preset, direction) => {
  const { camera, target } = presetCamera(preset, frame, 2);
  expect(camera).toBeInstanceOf(OrthographicCamera);
  const actual = camera.getWorldDirection(new Vector3());
  actual.toArray().forEach((v, i) => expect(v).toBeCloseTo(direction[i], 12));
  expect(camera.position.distanceTo(target)).toBeCloseTo(25);
  expect(camera.position.toArray()).toEqual(direction.map((v, i) => frame.centre[i] - v * 25));
  expect(target.toArray()).toEqual(frame.centre);
  if (camera instanceof OrthographicCamera) { expect(camera.right - camera.left).toBe(40); expect(camera.top - camera.bottom).toBe(20); }
});

it("Isometric keeps the default southwest perspective camera, 35 degrees above the horizon", () => {
  const { camera, target } = presetCamera("isometric", frame, 1.5);
  expect(camera).toBeInstanceOf(PerspectiveCamera);
  const offset = camera.position.clone().sub(target).normalize();
  expect(offset.x).toBeCloseTo(-0.6 * Math.cos(35 * Math.PI / 180));
  expect(offset.y).toBeCloseTo(-0.8 * Math.cos(35 * Math.PI / 180));
  expect(offset.z).toBeCloseTo(Math.sin(35 * Math.PI / 180));
  expect(camera.getWorldDirection(new Vector3()).dot(offset)).toBeCloseTo(-1);
});

it.each<Entity["plane"]>([
  { mode: "edge_tilt", edgeIndex: 0, zRef_m: 8, tilt_deg: 30, direction: "up" },
  { mode: "datum_tilt_azimuth", datum: [2, 3], z_m: 8, tilt_deg: 35, slopeAzimuth_deg: 127 },
  { mode: "flat", z_m: 8 }
])("face camera is perpendicular to the actual plane of a rotated roof: %j", plane => {
  const r = roof(plane);
  const { camera, target } = presetCamera("face", frame, 0.7, r);
  expect(camera).toBeInstanceOf(OrthographicCamera);
  const dir = camera.getWorldDirection(new Vector3());
  const a = r.polygon[0];
  const tangent = (b: Vec2) => new Vector3(b[0] - a[0], b[1] - a[1], planeZ(r.polygon, plane, b)! - planeZ(r.polygon, plane, a)!);
  expect(dir.dot(tangent(r.polygon[1]))).toBeCloseTo(0, 10);
  expect(dir.dot(tangent(r.polygon[3]))).toBeCloseTo(0, 10);
  expect(target.z).toBeCloseTo(planeZ(r.polygon, plane, [target.x, target.y])!);
  expect(dir.z).toBeLessThan(0);
  // Every roof corner fits, even in a tall/narrow stage.
  for (const [x, y] of r.polygon) {
    camera.updateMatrixWorld();
    const p = new Vector3(x, y, planeZ(r.polygon, plane, [x, y])!).project(camera);
    expect(Math.abs(p.x)).toBeLessThan(1); expect(Math.abs(p.y)).toBeLessThan(1);
  }
});

it("only selected, visible roofs enable the face preset", () => {
  const r = roof({ mode: "flat", z_m: 8 });
  expect(selectedRoof([r], [])).toBeUndefined();
  expect(selectedRoof([{ ...r, hidden: true }], [r.id])).toBeUndefined();
  expect(selectedRoof([{ ...r, subtype: "ground" }], [r.id])).toBeUndefined();
  expect(selectedRoof([r], [r.id])).toBe(r);
});

it("remembers views per project and preserves selection, step and the Top viewport", async () => {
  const storage = new Map<string, string>();
  vi.stubGlobal("window", { localStorage: { getItem: (k: string) => storage.get(k), setItem: (k: string, v: string) => storage.set(k, v) } });
  const base = await mockApi.project("demo-project");
  const other = structuredClone(base); other.bundle.project.project_id = "other";
  const { dispatch } = uiStore.getState();
  dispatch({ type: "setView", view: base });
  dispatch({ type: "select", ids: [uiStore.getState().state.entities[0].id] });
  const selection = uiStore.getState().state.selection;
  const viewport = { view: { cx: 22, cy: 9, scale: 30 }, size: { w: 800, h: 600 } };
  dispatch({ type: "setPlanViewport", viewport });
  for (const view of ["front", "isometric", "plan"] as const) {
    dispatch({ type: "setCanvasView", view });
    expect(uiStore.getState().state).toMatchObject({ selection, step: "scene", planViewport: viewport });
  }
  dispatch({ type: "setCanvasView", view: "right" });
  expect(storage.get(viewStorageKey(base.bundle.project.project_id))).toBe("right");
  dispatch({ type: "setView", view: other });
  expect(uiStore.getState().state.canvasView).toBe("plan");
  dispatch({ type: "setCanvasView", view: "sld" });
  dispatch({ type: "setView", view: base });
  expect(uiStore.getState().state.canvasView).toBe("right");
  expect(uiStore.getState().state.planViewport).toBeNull();
  dispatch({ type: "setView", view: other });
  expect(uiStore.getState().state.canvasView).toBe("sld");
});

it("invalid or unavailable local storage falls back to Top and never blocks switching", async () => {
  vi.stubGlobal("window", { localStorage: { getItem: () => "invalid" } });
  const { dispatch } = uiStore.getState();
  const base = await mockApi.project("demo-project");
  dispatch({ type: "setView", view: base });
  expect(uiStore.getState().state.canvasView).toBe("plan");
  dispatch({ type: "setView", view: null });
  vi.stubGlobal("window", { localStorage: { getItem: () => { throw Error("blocked"); }, setItem: () => { throw Error("blocked"); } } });
  dispatch({ type: "setView", view: base });
  dispatch({ type: "setCanvasView", view: "front" });
  expect(uiStore.getState().state.canvasView).toBe("front");
});

it("Top-only tools show a note and become Select, both on switching and when chosen outside Top", () => {
  const { dispatch } = uiStore.getState();
  dispatch({ type: "setTool", tool: "polygon" });
  dispatch({ type: "setCanvasView", view: "front" });
  expect(uiStore.getState().state).toMatchObject({ tool: "select", topToolNote: true });
  dispatch({ type: "setCanvasView", view: "plan" });
  dispatch({ type: "setTool", tool: "polygon" });
  expect(uiStore.getState().state).toMatchObject({ tool: "polygon", topToolNote: false });
  dispatch({ type: "setCanvasView", view: "isometric" });
  dispatch({ type: "setTool", tool: "measure" });
  expect(uiStore.getState().state).toMatchObject({ tool: "select", topToolNote: true });
});

it("the View submenu and compact control share every preset, with a disabled face entry", () => {
  const html = renderToStaticMarkup(createElement(ViewControls, { menu: true }));
  for (const p of VIEW_PRESETS) expect(html).toContain(`aria-label="${i18n.t(`stage.${p.label}`)}"`);
  expect(html.match(/role="menuitemradio"/g)).toHaveLength(7);
  expect(html).toContain('aria-disabled="true"');
  const control = renderToStaticMarkup(createElement(ViewControls));
  expect(control.match(/<button/g)).toHaveLength(7);
  expect(control).toContain('disabled=""');
  const menu = renderToStaticMarkup(createElement(ContextMenu, { items: [], at: { x: 0, y: 0 }, box: { w: 800, h: 600 }, label: "Stage view",
    onSelect: () => {}, onClose: () => {}, submenu: { label: "View", content: () => createElement(ViewControls, { menu: true }) } }));
  expect(menu).toContain('aria-haspopup="menu"'); expect(menu).toContain('View ▸');
  const { dispatch } = uiStore.getState();
  dispatch({ type: "setCanvasView", view: "face" });
  expect(uiStore.getState().state.canvasView).toBe("plan");
  dispatch({ type: "addEntity", entity: roof({ mode: "flat", z_m: 4 }) });
  dispatch({ type: "select", ids: ["roof"] });
  expect(renderToStaticMarkup(createElement(ViewControls, { menu: true }))).not.toContain('aria-disabled="true"');
  dispatch({ type: "setCanvasView", view: "face" });
  expect(uiStore.getState().state.canvasView).toBe("face");
});

it("face view memory restores its roof, and falls back to Top if the roof was removed", async () => {
  const storage = new Map<string, string>();
  vi.stubGlobal("window", { localStorage: { getItem: (k: string) => storage.get(k), setItem: (k: string, v: string) => storage.set(k, v) } });
  const base = await mockApi.project("demo-project");
  const { dispatch } = uiStore.getState();
  dispatch({ type: "setView", view: base });
  const r = uiStore.getState().state.entities.find(e => e.subtype === "flat_roof")!;
  dispatch({ type: "select", ids: [r.id] });
  dispatch({ type: "setCanvasView", view: "face" });
  dispatch({ type: "setView", view: null });
  dispatch({ type: "setView", view: base });
  expect(uiStore.getState().state).toMatchObject({ canvasView: "face", selection: [r.id] });
  dispatch({ type: "setView", view: null });
  storage.set(`${viewStorageKey(base.bundle.project.project_id)}.roof`, "removed");
  dispatch({ type: "setView", view: base });
  expect(uiStore.getState().state.canvasView).toBe("plan");
});
