import type { Vec2 } from "../geometry";
import type { Entity, Tool } from "../state/store";
import type { ToolDef } from "./tools";

/** What the right-click (or Shift+F10) landed on. Vertex and edge targets exist only on the selected editable object. */
export type MenuTarget =
  | { kind: "drawing"; points: number }
  | { kind: "vertex"; entityId: string; ring: number; index: number }
  | { kind: "edge"; entityId: string; ring: number; index: number; at: Vec2 }
  | { kind: "selection" }
  | { kind: "empty" };

export type MenuAction =
  | "undo" | "redo" | "finishPolygon" | "removePoint" | "cancelDrawing"
  | "deleteVertex" | "insertVertex" | "edgeLength" | "referenceEdge"
  | "properties" | "zoomSelection" | "duplicate" | "move" | "rotate" | "addHole" | "lock" | "unlock" | "hide" | "delete"
  | "deleteModules" | "deleteTables" | "selectAll" | "clearSelection" | "zoomAll"
  | "overlayLock" | "overlayUnlock" | "overlayCalibrate" | "copy" | "paste"
  | `tool:${Tool}`
  /** USE3b: unstrung modules appended to a string, or made a new string on an MPPT. */
  | `addToString:${string}` | `newString:${string}`;

export interface MenuItem {
  id: MenuAction;
  label: string;
  /** tinykeys string of the existing shortcut, shown on the right. */
  keys?: string;
  /** Why the item can't run now; the item stays visible. */
  disabled?: string;
  danger?: boolean;
  /** Items with different groups are separated. */
  group: number;
  /** Secondary text, e.g. the history entry an undo would revert. */
  title?: string;
}

export interface MenuState {
  target: MenuTarget;
  /** Selected scene objects (roofs, obstacles, keep-outs). */
  selected: Entity[];
  selectedModules: number;
  activeTables: number;
  step: string;
  busy: boolean;
  canUndo: boolean;
  canRedo: boolean;
  undoLabel?: string;
  redoLabel?: string;
  /** Tools of the current step (`toolsForStep`). */
  tools: readonly ToolDef[];
  anyVisible: boolean;
  /** Selected obstacle ids that are imported meshes (read-only in the engine). */
  meshIds: ReadonlySet<string>;
  /** UX1: the project's image overlay, if any. */
  overlay?: "locked" | "unlocked" | null;
  /** UX3 clipboard: why Paste can't run (an i18n key), or null when it can; undefined means no clipboard here
   *  (Copy and Paste are hidden). */
  pasteProblem?: string | null;
  /** USE3b (Electrical): the selection's unstrung modules and where they can go. */
  unstrungAssign?: { count: number; strings: { id: string; label: string }[]; mppts: { id: string; label: string }[] };
}

type T = (key: string, options?: Record<string, unknown>) => string;

/** Tools that start from nothing; move, rotate and hole need a selected object and appear in its menu. */
const CANVAS_TOOLS: ReadonlySet<Tool> = new Set<Tool>(["rect_engine", "polygon", "box_obstacle", "obstacle", "keepout", "measure", "string_path", "assign", "lasso"]);

/** The context menu for a target: items, order and disabled reasons. Pure, so it is unit-tested. */
export function buildMenu(s: MenuState, t: T): MenuItem[] {
  const items: MenuItem[] = [];
  const add = (item: MenuItem) => items.push(item);
  const busy = s.busy ? t("commands.running") : undefined;
  add({ id: "undo", group: 0, label: t("commands.undo"), keys: "$mod+z", title: s.undoLabel, disabled: busy ?? (s.canUndo ? undefined : t("ux2.nothingToUndo")) });
  add({ id: "redo", group: 0, label: t("commands.redo"), keys: "$mod+Shift+z", title: s.redoLabel, disabled: busy ?? (s.canRedo ? undefined : t("ux2.nothingToRedo")) });

  if (s.target.kind === "drawing") {
    const n = s.target.points;
    add({ id: "finishPolygon", group: 1, label: t("ux2.finishPolygon"), keys: "Enter", disabled: n >= 3 ? undefined : t("ux2.needThree") });
    add({ id: "removePoint", group: 1, label: t("ux2.removePoint"), keys: "Backspace", disabled: n ? undefined : t("ux2.noPoints") });
    add({ id: "cancelDrawing", group: 1, label: t("ux2.cancelDrawing"), keys: "Escape" });
    return items;
  }

  // A right-click on empty canvas keeps the selection but offers the canvas menu.
  const scoped = s.target.kind !== "empty";
  const one = scoped && s.selected.length === 1 && !s.selectedModules ? s.selected[0] : null;
  const engineBlock = (e: Entity) => (e.locked ? t("tools.locked", { name: e.name })
    : e.source === "engine" && e.modified ? t("s7b.discardReason") : e.source === "engine" ? busy : undefined);

  if ((s.target.kind === "vertex" || s.target.kind === "edge") && one) {
    const ring = s.target.ring === 0 ? one.polygon : one.holes[s.target.ring - 1] ?? [];
    const block = engineBlock(one);
    if (s.target.kind === "vertex") {
      add({ id: "deleteVertex", group: 1, label: t("ux2.deleteVertex"), keys: "Delete", danger: true, disabled: block ?? (ring.length > 3 ? undefined : t("ux2.minVertices")) });
    } else {
      const hole = s.target.ring !== 0 ? t("ux2.outerOnly") : undefined;
      add({ id: "insertVertex", group: 1, label: t("ux2.insertVertex"), disabled: block });
      add({ id: "edgeLength", group: 1, label: t("ux2.edgeLength"), disabled: block ?? hole });
      if (one.kind === "surface") add({ id: "referenceEdge", group: 1, label: t("ux2.referenceEdge"), disabled: block ?? hole });
    }
  }

  if (one) {
    const block = engineBlock(one);
    const mesh = s.meshIds.has(one.id) ? t("ux2.meshReadOnly") : undefined;
    add({ id: "properties", group: 2, label: t("ux2.properties") });
    add({ id: "zoomSelection", group: 2, label: t("ux2.zoomSelection"), keys: "z" });
    if (s.pasteProblem !== undefined) add({ id: "copy", group: 3, label: t("ux3.copy"), keys: "$mod+c", disabled: mesh });
    if (s.pasteProblem !== undefined) add({ id: "paste", group: 3, label: t("ux3.paste"), keys: "$mod+v", disabled: s.pasteProblem ? t(s.pasteProblem) : busy });
    add({ id: "duplicate", group: 3, label: t("ux2.duplicate"), disabled: mesh ?? (one.source === "engine" && one.modified ? t("s7b.discardReason") : one.source === "engine" ? busy : undefined) });
    add({ id: "move", group: 3, label: t("tools.move"), keys: "m", disabled: block });
    add({ id: "rotate", group: 3, label: t("tools.rotate"), keys: "r", disabled: block });
    if (one.kind === "surface") add({ id: "addHole", group: 3, label: t("tools.hole"), keys: "h", disabled: block });
    add(one.locked ? { id: "unlock", group: 4, label: t("ux2.unlock") } : { id: "lock", group: 4, label: t("ux2.lock") });
    add({ id: "hide", group: 4, label: t("ux2.hide") });
    add({ id: "delete", group: 5, label: t("ux2.delete"), keys: "Delete", danger: true, disabled: one.locked ? t("tools.locked", { name: one.name }) : busy });
    return items;
  }

  if (scoped && s.selected.length && s.selectedModules) {
    add({ id: "zoomSelection", group: 2, label: t("ux2.zoomSelection"), keys: "z" });
    add({ id: "delete", group: 5, label: t("ux2.delete"), keys: "Delete", danger: true, disabled: t("s13a.mixedDelete") });
    add({ id: "clearSelection", group: 6, label: t("ux2.clearSelection"), keys: "Escape" });
    return items;
  }

  if (scoped && s.selected.length > 1) {
    const unlocked = s.selected.filter((e) => !e.locked);
    add({ id: "zoomSelection", group: 2, label: t("ux2.zoomSelection"), keys: "z" });
    add({ id: "duplicate", group: 3, label: t("ux2.duplicate"), disabled: t("ux2.duplicateOne") });
    add(unlocked.length ? { id: "lock", group: 4, label: t("ux2.lockAll") } : { id: "unlock", group: 4, label: t("ux2.unlockAll") });
    add({ id: "hide", group: 4, label: t("ux2.hideAll") });
    add({ id: "delete", group: 5, label: t("ux2.deleteCount", { count: unlocked.length }), keys: "Delete", danger: true,
      disabled: unlocked.length ? busy : t("s13a.lockedCount", { count: s.selected.length }) });
    add({ id: "clearSelection", group: 6, label: t("ux2.clearSelection"), keys: "Escape" });
    return items;
  }

  if (scoped && s.selectedModules) {
    const layout = s.step === "layout";
    const free = s.step === "electrical" ? s.unstrungAssign : undefined;
    if (free?.count) {
      for (const str of free.strings) add({ id: `addToString:${str.id}`, group: 1, label: t("use3b.addToString", { count: free.count, string: str.label }), disabled: busy });
      for (const m of free.mppts) add({ id: `newString:${m.id}`, group: 1, label: t("use3b.newString", { count: free.count, mppt: m.label }), disabled: busy });
    }
    if (s.step === "scene" || layout) add({ id: "deleteModules", group: 5, label: t("ux2.deleteModules", { count: s.selectedModules }), keys: "Delete", danger: true, disabled: busy });
    if (layout) add({ id: "deleteTables", group: 5, label: t("ux2.deleteTables", { count: s.activeTables }), keys: "Shift+Delete", danger: true, disabled: busy ?? (s.activeTables ? undefined : t("ux2.noTables")) });
    add({ id: "zoomSelection", group: 2, label: t("ux2.zoomSelection"), keys: "z" });
    add({ id: "clearSelection", group: 6, label: t("ux2.clearSelection"), keys: "Escape" });
    return items;
  }

  add({ id: "selectAll", group: 2, label: t("ux2.selectAll"), disabled: s.anyVisible ? undefined : t("ux2.nothingToSelect") });
  add({ id: "clearSelection", group: 2, label: t("ux2.clearSelection"), keys: "Escape", disabled: s.selected.length || s.selectedModules ? undefined : t("ux2.nothingSelected") });
  add({ id: "zoomAll", group: 2, label: t("ux2.zoomAll") });
  if (s.pasteProblem !== undefined) add({ id: "paste", group: 2, label: t("ux3.paste"), keys: "$mod+v", disabled: s.pasteProblem ? t(s.pasteProblem) : busy });
  if (s.overlay === "locked") add({ id: "overlayUnlock", group: 4, label: t("imagery.unlock") });
  if (s.overlay === "unlocked") {
    add({ id: "overlayCalibrate", group: 4, label: t("imagery.calibrate") });
    add({ id: "overlayLock", group: 4, label: t("imagery.lock") });
  }
  for (const d of s.tools) {
    if (!CANVAS_TOOLS.has(d.tool) || d.pending) continue;
    add({ id: `tool:${d.tool}`, group: 3, label: t(d.label), keys: d.key });
  }
  return items;
}
