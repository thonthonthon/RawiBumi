import { beforeAll, beforeEach, expect, it } from "vitest";
import i18n from "../../src/i18n";
import { clearClipboard, copyToClipboard, pasteOffset, pasteProblem, readClipboard } from "../../src/canvas/clipboard";
import { buildMenu, type MenuState } from "../../src/canvas/contextMenu";
import { TOOLS } from "../../src/canvas/tools";
import { resetStore, uiStore, type Entity } from "../../src/state/store";

const roof = (over: Partial<Entity> = {}): Entity => ({ id: "roof", kind: "surface", subtype: "flat_roof", name: "Roof", polygon: [[0, 0], [10, 0], [10, 6], [0, 6]], holes: [],
  plane: { mode: "flat", z_m: 6 }, height_m: 0, source: "engine", modified: false, pending: [], locked: false, hidden: false, hostsPvField: true, ...over });
beforeAll(async () => { await i18n.changeLanguage("en"); });
beforeEach(() => { clearClipboard(); resetStore(); });

it("the clipboard refers to its source within one project and pastes at a point or beside the original", () => {
  expect(pasteProblem(readClipboard(), "p1", [roof()])).toBe("ux3.clipboardEmpty");
  const clip = copyToClipboard("p1", roof());
  expect(clip).toEqual({ projectId: "p1", entityId: "roof", name: "Roof", centre: [5, 3], width: 10 });
  expect(pasteProblem(clip, "p1", [roof()])).toBeNull();
  expect(pasteProblem(clip, "p2", [roof()])).toBe("ux3.otherProject");
  expect(pasteProblem(clip, "p1", [])).toBe("ux3.sourceGone");
  expect(pasteOffset(clip, [25, -4])).toEqual([20, -7]);
  expect(pasteOffset(clip, null)).toEqual([11, 0]);
});

it("Copy and Paste appear only with a clipboard, and Paste says why it can't run", () => {
  const t = (k: string, o?: Record<string, unknown>) => i18n.t(k, o);
  const state: MenuState = { target: { kind: "selection" }, selected: [roof()], selectedModules: 0, activeTables: 0, step: "scene", busy: false,
    canUndo: false, canRedo: false, tools: TOOLS, anyVisible: true, meshIds: new Set() };
  expect(buildMenu(state, t).map((i) => i.id)).not.toContain("copy");
  const withClip = buildMenu({ ...state, pasteProblem: "ux3.clipboardEmpty" }, t);
  expect(withClip.find((i) => i.id === "copy")).toMatchObject({ keys: "$mod+c", disabled: undefined });
  expect(withClip.find((i) => i.id === "paste")).toMatchObject({ keys: "$mod+v", disabled: "Copy a roof, obstacle or keep-out first" });
  const empty = buildMenu({ ...state, target: { kind: "empty" }, pasteProblem: null }, t);
  expect(empty.find((i) => i.id === "paste")?.disabled).toBeUndefined();
  expect(buildMenu({ ...state, meshIds: new Set(["roof"]), pasteProblem: null }, t).find((i) => i.id === "copy")?.disabled).toBe("Imported meshes are read-only");
});

it("the selected vertex is shared through the store and cleared by opening another project", () => {
  const { dispatch } = uiStore.getState();
  dispatch({ type: "setVertex", vertex: { id: "roof", ring: 0, index: 2 } });
  const first = uiStore.getState().state;
  expect(first.vertex).toEqual({ id: "roof", ring: 0, index: 2 });
  dispatch({ type: "setVertex", vertex: { id: "roof", ring: 0, index: 2 } });
  expect(uiStore.getState().state).toBe(first);
  dispatch({ type: "setView", view: null });
  expect(uiStore.getState().state.vertex).toBeNull();
});
