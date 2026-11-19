import type { ReactNode } from "react";
import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";
import type { ProjectView } from "../types";
import { enginePlaneToUi, type PlaneDef, type Vec2 } from "../geometry";
import type { OpenSIMPVDesignWorkspaceStateV01 } from "../generated/schemas/design-workspace-state";
import { tableModules, type FillPreview } from "../engine/layout";
import { notationOfInverter } from "../electrical/sync";
import { fieldSupportIds } from "../types";
import { ApiError, isMutationView } from "../types";
import { engine } from "../client";
import i18n from "../i18n";
import { VIEW_PRESETS, selectedRoof, type GeometryView, type CameraFrame } from "../canvas/viewPresets";
import type { ViewT, Size } from "../canvas/plan/viewport";

/**
 * Snap preferences in the engine's own shape (design-workspace-state
 * snap_preferences), plus the UI-only 15° constraint while Shift is held.
 */
export type SnapPreferences = OpenSIMPVDesignWorkspaceStateV01["snap_preferences"] & { angle15: boolean };

export type Step = "site" | "scene" | "layout" | "components" | "systems" | "electrical" | "meteo" | "losses" | "simulate" | "results" | "export";
export type Tool =
  | "select"
  | "move"
  | "rotate"
  | "polygon"
  | "rect_engine"
  | "box_obstacle"
  | "obstacle"
  | "keepout"
  | "measure"
  | "hole"
  // Electrical step (B6)
  | "string_path"
  | "assign"
  | "lasso"
  | "split"
  | "join"
  | "reverse"
  | "move_module"
  | "swap_modules";
export type CanvasView = GeometryView | "sld";
export type EntityKind = "surface" | "obstacle" | "keepout";

export interface Entity {
  id: string;
  kind: EntityKind;
  subtype: string;
  name: string;
  polygon: Vec2[];
  holes: Vec2[][];
  plane: PlaneDef;
  height_m: number; // obstacles: extrusion height above base
  source: "engine" | "draft";
  /** Engine geometry changed locally by an operation whose endpoint is not wired yet. */
  modified: boolean;
  /** Pending endpoint ids required to commit this entity to the engine. */
  pending: string[];
  locked: boolean;
  hidden: boolean;
  hostsPvField: boolean;
}

export interface ModuleShape {
  id: string;
  fieldId: string;
  polygon: Vec2[];
  stringId: string | null;
  mpptKey: string | null; // `${inverterId}#${mpptIndex}`
}

export interface ElectricalDraft {
  notation: string;
  /** S14b: the engine's pairing of this inverter (read from the view, never edited locally). */
  pairedFieldIds: string[];
  inputsPerMppt: number | null;
  inputsSource: string;
  /** The inverter revision the draft was made for; Change model resets the draft. */
  definitionId?: string;
}


export interface Toast {
  id: number;
  tone: "info" | "ok" | "error" | "pending";
  text: string;
}

/**
 * One undo step. Local drafts are undone here; engine commands are undone by the
 * engine session, so the UI only records that one happened.
 */
export type HistoryEntry = { kind: "local"; entities: Entity[] } | { kind: "engine"; label: string; entryId?: string; localBefore?: Entity[]; localAfter?: Entity[] };

export interface UIState {
  view: ProjectView | null;
  entities: Entity[];
  modules: ModuleShape[];
  selection: string[];
  tool: Tool;
  step: Step;
  canvasView: CanvasView;
  planViewport: { view: ViewT; size: Size } | null;
  cameraFrame: CameraFrame | null;
  topToolNote: boolean;
  past: HistoryEntry[];
  future: HistoryEntry[];
  /** The fill preview shown on the plan before Apply (B5); never undoable, never sent. */
  layoutPreview: FillPreview | null;
  /** Active MPPT target of the electrical tools (B6): an mppt_instance_id. */
  target: string | null;
  snap: SnapPreferences;
  /** UXF1 (U2-14): plan grid lines, a per-viewer view choice (browser storage, never the project). */
  showGrid: boolean;
  electrical: Record<string, ElectricalDraft>;
  forms: Record<string, unknown>;
  busy: string | null;
  toasts: Toast[];
  hover: string | null;
  /** UX3: the selected vertex of the selected object, shared by the plan and the Inspector. */
  vertex: { id: string; ring: number; index: number } | null;
}

export type Action =
  | { type: "setView"; view: ProjectView | null }
  | { type: "setStep"; step: Step }
  | { type: "setTool"; tool: Tool }
  | { type: "setCanvasView"; view: CanvasView }
  | { type: "setPlanViewport"; viewport: UIState["planViewport"] }
  | { type: "setCameraFrame"; frame: CameraFrame }
  | { type: "select"; ids: string[] }
  | { type: "selectToggle"; id: string }
  | { type: "selectAdd"; ids: string[] }
  | { type: "hover"; id: string | null }
  | { type: "setVertex"; vertex: UIState["vertex"] }
  | { type: "addEntity"; entity: Entity }
  | { type: "updateEntity"; id: string; patch: Partial<Entity>; history?: boolean }
  | { type: "deleteEntity"; id: string }
  | { type: "discardEntityDraft"; id: string }
  | { type: "checkpoint" }
  | { type: "clearHistory" }
  | { type: "deleteEntities"; ids: string[]; mergeEngine?: boolean }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "engineCommitted"; view: ProjectView; label: string }
  | { type: "engineUndone"; view: ProjectView }
  | { type: "engineRedone"; view: ProjectView }
  | { type: "setLayoutPreview"; preview: FillPreview | null }
  | { type: "setTarget"; target: string | null }
  | { type: "setSnap"; patch: Partial<UIState["snap"]> }
  | { type: "setShowGrid"; show: boolean }
  | { type: "setElectrical"; inverterId: string; patch: Partial<ElectricalDraft> }
  | { type: "setForm"; key: string; value: unknown }
  | { type: "busy"; label: string | null }
  | { type: "toast"; toast: Omit<Toast, "id"> }
  | { type: "dismissToast"; id: number };

let toastSeq = 1;

function entitiesFromView(view: ProjectView, previous: Entity[]): Entity[] {
  const b = view.bundle;
  const hostIds = new Set(b.scene.pv_fields.flatMap(fieldSupportIds));
  const keep = new Map(previous.filter((e) => e.source === "engine" && e.modified).map((e) => [e.id, e]));
  const out: Entity[] = [];
  for (const f of view.scene_view.local_features) {
    if (f.category === "module") continue;
    if (keep.has(f.id)) {
      out.push({ ...keep.get(f.id)!, hostsPvField: hostIds.has(f.id) });
      continue;
    }
    const prev = previous.find((e) => e.id === f.id);
    if (f.category === "surface") {
      const s = b.scene.surfaces.find((x) => x.surface_id === f.id);
      out.push({
        id: f.id,
        kind: ["exclusion_area", "walkway"].includes(s?.surface_type ?? f.subtype) ? "keepout" : "surface",
        subtype: f.subtype,
        name: f.name,
        polygon: f.polygon.map((p) => [p[0], p[1]] as Vec2),
        holes: (s?.boundary_2d?.holes ?? []).map(h => h.map(p => [p[0], p[1]] as Vec2)),
        plane: enginePlaneToUi(f.polygon, s ?? {}, prev?.plane),
        height_m: 0,
        source: "engine",
        modified: false,
        pending: [],
        locked: prev?.locked ?? false,
        hidden: prev?.hidden ?? false,
        hostsPvField: hostIds.has(f.id)
      });
    } else {
      const o = b.scene.obstacles.find((x) => x.obstacle_id === f.id);
      out.push({
        id: f.id,
        kind: "obstacle",
        subtype: f.subtype,
        name: f.name,
        polygon: f.polygon.map((p) => [p[0], p[1]] as Vec2),
        holes: [],
        plane: { mode: "flat", z_m: o?.base_elevation_m ?? 0 },
        height_m: o?.height_m ?? 1,
        source: "engine",
        modified: false,
        pending: [],
        locked: prev?.locked ?? false,
        hidden: prev?.hidden ?? false,
        hostsPvField: false
      });
    }
  }
  return [...out, ...previous.filter((e) => e.source === "draft")];
}

/** Plan modules from a view: legacy module features and table slots, with their string and MPPT. */
export function modulesFromView(view: ProjectView): ModuleShape[] {
  const stringOf = new Map<string, string>();
  const mpptOf = new Map<string, string>();
  const mpptKey = new Map<string, string>();
  for (const inv of view.bundle.electrical_design.inverter_instances)
    inv.mppt_instance_ids.forEach((m, i) => mpptKey.set(m, `${inv.inverter_instance_id}#${i}`));
  for (const s of view.bundle.electrical_design.strings)
    for (const m of s.module_instance_ids) {
      stringOf.set(m, s.string_id);
      if (s.target_mppt_instance_id) mpptOf.set(m, mpptKey.get(s.target_mppt_instance_id) ?? "");
    }
  const legacy = view.scene_view.local_features
    .filter((f) => f.category === "module")
    .map((f) => ({
      id: f.id,
      fieldId: f.pv_field_id ?? "",
      polygon: f.polygon.map((p) => [p[0], p[1]] as Vec2),
      stringId: stringOf.get(f.id) ?? null,
      mpptKey: mpptOf.get(f.id) ?? null
    }));
  // Table-level fields arrive as tables (E2); their modules are the tables' slots.
  const fromTables = (view.table_layout?.tables ?? []).flatMap((t) =>
    tableModules(t).map((m) => ({ id: m.id, fieldId: t.pv_field_id, polygon: m.polygon, stringId: stringOf.get(m.id) ?? null, mpptKey: mpptOf.get(m.id) ?? null }))
  );
  return fromTables.length ? [...legacy, ...fromTables] : legacy;
}

const withView = (state: UIState, view: ProjectView): UIState => {
  const modules = modulesFromView(view);
  const ids = new Set([...modules.map((m) => m.id), ...view.scene_view.local_features.map((f) => f.id)]);
  return {
    ...state,
    view,
    entities: entitiesFromView(view, state.entities),
    modules,
    electrical: electricalFromView(view, state.electrical),
    // A selection of modules or entities the engine removed goes with them.
    selection: state.selection.filter((id) => ids.has(id) || state.entities.some((e) => e.id === id && e.source === "draft"))
  };
};

function electricalFromView(view: ProjectView, prev: Record<string, ElectricalDraft>): Record<string, ElectricalDraft> {
  const out: Record<string, ElectricalDraft> = {};
  for (const inv of view.topology_view.inverters) {
    // Notation sync (B6): the notation always shows the engine's topology; edits are a preview in the panel.
    const notation = notationOfInverter(inv);
    const instance = view.bundle.electrical_design.inverter_instances.find((i) => i.inverter_instance_id === inv.inverter_instance_id);
    const pairedFieldIds = instance?.paired_pv_field_ids ?? [];
    const definitionId = instance?.inverter_definition_revision_id;
    const before = prev[inv.inverter_instance_id];
    // USE-D4: inputs per MPPT as the definition states them, or derived from its total input count.
    const stated = Math.max(0, ...inv.mppts.map((m) => m.input_count ?? 0));
    const catalog = view.catalog.inverters.find((c) => c.revision_id === definitionId);
    const width = stated || catalog?.inputs_per_mppt || Math.max(1, ...inv.mppts.map((m) => m.strings.length));
    const inputsSource = stated ? "Engine topology view (inverter definition)"
      : catalog?.inputs_per_mppt ? `Inverter file (${catalog.inputs_per_mppt_source === "definition" ? "stated" : catalog.inputs_per_mppt_source})`
      : width > 1 ? "Inferred from current topology — confirm with datasheet" : "";
    if (before && before.definitionId === definitionId) {
      out[inv.inverter_instance_id] = { ...before, notation, pairedFieldIds,
        ...(stated || catalog?.inputs_per_mppt ? { inputsPerMppt: width, inputsSource } : {}) };
      continue;
    }
    out[inv.inverter_instance_id] = {
      notation,
      pairedFieldIds,
      definitionId,
      inputsPerMppt: stated || catalog?.inputs_per_mppt ? width : width > 1 ? width : null,
      inputsSource
    };
  }
  return out;
}

const local = (state: UIState): HistoryEntry => ({ kind: "local", entities: state.entities });

const historyLimit = (state: UIState) => state.view?.history?.limit ?? 100;
const retainedPast = (state: UIState) => state.past.slice(-(historyLimit(state) - 1) || state.past.length);
const isRealHistory = (view: ProjectView) => view.history && view.history.authority !== "demo";

function reconcileHistory(state: UIState, view: ProjectView): UIState {
  if (!isRealHistory(view)) return state;
  const ids = new Set([...view.history!.past, ...view.history!.future].map(e => e.entry_id));
  const lastMissing = state.past.reduce((last, e, i) => e.kind === "engine" && e.entryId && !ids.has(e.entryId) ? i : last, -1);
  const futureMissing = state.future.findIndex(e => e.kind === "engine" && e.entryId && !ids.has(e.entryId));
  return { ...state, past: state.past.slice(lastMissing + 1), future: futureMissing < 0 ? state.future : state.future.slice(0, futureMissing) };
}

function committed(state: UIState, view: ProjectView, label: string): UIState {
  if (!isRealHistory(view)) return { ...withView(state, view), past: [...retainedPast(state), { kind: "engine", label }], future: [] };
  const entry = view.history!.past.at(-1);
  const updated = reconcileHistory(state, view);
  if (!entry || entry.entry_id === state.view?.history?.past.at(-1)?.entry_id || state.past.some(e => e.kind === "engine" && e.entryId === entry.entry_id)) return withView(updated, view);
  return { ...withView(updated, view), past: [...retainedPast(updated), { kind: "engine", label: entry.label, entryId: entry.entry_id }], future: [] };
}

function reducer(state: UIState, action: Action): UIState {
  switch (action.type) {
    case "setView": {
      if (!action.view) return { ...state, view: null, entities: [], modules: [], selection: [], past: [], future: [], layoutPreview: null, electrical: {}, forms: {}, target: null, tool: "select", vertex: null };
      if (action.view.bundle.project.project_id !== state.view?.bundle.project.project_id) {
        // UXF3 (U2-27): opening a project (also after a reload) resumes the engine's saved undo and redo steps.
        const saved = (entries?: { entry_id: string; label: string }[]) =>
          isRealHistory(action.view!) ? (entries ?? []).map((e) => ({ kind: "engine" as const, label: e.label, entryId: e.entry_id })) : [];
        const opened = withView({ ...state, entities: [], modules: [], selection: [], past: saved(action.view.history?.past), future: saved(action.view.history?.future),
          layoutPreview: null, electrical: {}, forms: {}, target: null, tool: "select", vertex: null,
          canvasView: storedCanvasView(action.view.bundle.project.project_id), planViewport: null, cameraFrame: null, topToolNote: false }, action.view);
        if (opened.canvasView === "face") {
          let roofId: string | null = null;
          try { roofId = window.localStorage.getItem(`${viewStorageKey(action.view.bundle.project.project_id)}.roof`); } catch { /* Optional memory. */ }
          const roof = selectedRoof(opened.entities, roofId ? [roofId] : []);
          return { ...opened, canvasView: roof ? "face" : "plan", selection: roof ? [roof.id] : [] };
        }
        return opened;
      }
      if (isMutationView(action.view)) return committed(state, action.view, "Edit design");
      return withView(reconcileHistory(state, action.view), action.view);
    }
    case "engineCommitted":
      return committed(state, action.view, action.label);
    case "engineUndone": {
      const top = state.past[state.past.length - 1];
      if (top?.kind !== "engine") return state;
      return { ...withView(state, action.view), ...(top.localBefore ? { entities: [...withView(state, action.view).entities.filter(e => e.source !== "draft"), ...top.localBefore] } : {}), past: state.past.slice(0, -1), future: [top, ...state.future] };
    }
    case "engineRedone": {
      const [next, ...rest] = state.future;
      if (next?.kind !== "engine") return state;
      return { ...withView(state, action.view), ...(next.localAfter ? { entities: [...withView(state, action.view).entities.filter(e => e.source !== "draft"), ...next.localAfter] } : {}), past: [...state.past, next], future: rest };
    }
    case "setLayoutPreview":
      return { ...state, layoutPreview: action.preview };
    case "setTarget":
      return state.target === action.target ? state : { ...state, target: action.target };
    case "setStep":
      return { ...state, step: action.step };
    case "setTool": {
      const topOnly = state.canvasView !== "plan" && state.canvasView !== "sld" && action.tool !== "select";
      return { ...state, tool: topOnly ? "select" : action.tool, topToolNote: topOnly };
    }
    case "setPlanViewport":
      return { ...state, planViewport: action.viewport };
    case "setCameraFrame":
      return { ...state, cameraFrame: action.frame };
    case "setCanvasView": {
      if (action.view === "face" && !selectedRoof(state.entities, state.selection)) return state;
      const topOnly = action.view !== "plan" && action.view !== "sld" && state.tool !== "select";
      return { ...state, canvasView: action.view, tool: topOnly ? "select" : state.tool,
        topToolNote: topOnly, cameraFrame: state.canvasView === "plan" ? null : state.cameraFrame };
    }
    case "select":
      return { ...state, selection: action.ids };
    case "selectToggle":
      return { ...state, selection: state.selection.includes(action.id) ? state.selection.filter((id) => id !== action.id) : [...new Set([...state.selection, action.id])] };
    case "selectAdd":
      return { ...state, selection: [...new Set([...state.selection, ...action.ids])] };
    case "hover":
      return state.hover === action.id ? state : { ...state, hover: action.id };
    case "setVertex": {
      const v = action.vertex, c = state.vertex;
      return v === c || (v && c && v.id === c.id && v.ring === c.ring && v.index === c.index) ? state : { ...state, vertex: v };
    }
    case "clearHistory":
      return { ...state, past: [], future: [] };
    case "deleteEntities": {
      const entities = state.entities.filter(e => !action.ids.includes(e.id));
      if (entities.length === state.entities.length) return state;
      const top = state.past.at(-1);
      const past: HistoryEntry[] = action.mergeEngine && top?.kind === "engine"
        ? [...state.past.slice(0, -1), { ...top, localBefore: state.entities.filter(e => e.source === "draft"), localAfter: entities.filter(e => e.source === "draft") }]
        : [...retainedPast(state), local(state)];
      return { ...state, entities, past, future: [], selection: state.selection.filter(id => !action.ids.includes(id)) };
    }
    case "checkpoint":
      return { ...state, past: [...retainedPast(state), local(state)], future: [] };
    case "addEntity":
      return {
        ...state,
        past: [...retainedPast(state), local(state)],
        future: [],
        entities: [...state.entities, action.entity],
        selection: [action.entity.id]
      };
    case "updateEntity": {
      const entities = state.entities.map((e) => (e.id === action.id ? { ...e, ...action.patch } : e));
      if (action.history === false) return { ...state, entities };
      if (!state.entities.some(e => e.id === action.id && Object.entries(action.patch).some(([key, value]) => JSON.stringify(e[key as keyof Entity]) !== JSON.stringify(value)))) return state;
      return { ...state, past: [...retainedPast(state), local(state)], future: [], entities };
    }
    case "discardEntityDraft": {
      if (!state.view) return state;
      const entities = entitiesFromView(state.view, state.entities.map((e) => e.id === action.id ? { ...e, modified: false } : e));
      return { ...state, entities };
    }
    case "deleteEntity":
      return {
        ...state,
        past: [...retainedPast(state), local(state)],
        future: [],
        entities: state.entities.filter((e) => e.id !== action.id),
        selection: state.selection.filter((s) => s !== action.id)
      };
    // Local steps only; an engine step on top is undone through src/state/history.ts.
    case "undo": {
      const prev = state.past[state.past.length - 1];
      if (prev?.kind !== "local") return state;
      return { ...state, entities: prev.entities, past: state.past.slice(0, -1), future: [local(state), ...state.future] };
    }
    case "redo": {
      const [next, ...rest] = state.future;
      if (next?.kind !== "local") return state;
      return { ...state, entities: next.entities, past: [...state.past, local(state)], future: rest };
    }
    case "setSnap":
      return { ...state, snap: { ...state.snap, ...action.patch } };
    case "setShowGrid":
      return { ...state, showGrid: action.show };
    case "setElectrical":
      return {
        ...state,
        electrical: { ...state.electrical, [action.inverterId]: { ...state.electrical[action.inverterId], ...action.patch } }
      };
    case "setForm":
      return { ...state, forms: { ...state.forms, [action.key]: action.value } };
    case "busy":
      return { ...state, busy: action.label };
    case "toast":
      return { ...state, toasts: [...state.toasts.slice(-3), { ...action.toast, id: toastSeq++ }] };
    case "dismissToast":
      return { ...state, toasts: state.toasts.filter((t) => t.id !== action.id) };
  }
}

export const viewStorageKey = (projectId: string) => `rawibumi.view.${projectId}`;
function storedCanvasView(projectId: string): CanvasView {
  try {
    const view = window.localStorage.getItem(viewStorageKey(projectId));
    if (view === "sld" || VIEW_PRESETS.some(p => p.id === view)) return view as CanvasView;
  } catch { /* Storage is optional. */ }
  return "plan";
}

export const GRID_KEY = "rawibumi.plan.grid";
function storedShowGrid(): boolean {
  try {
    return window.localStorage.getItem(GRID_KEY) !== "0";
  } catch {
    return true;
  }
}

const initial: UIState = {
  showGrid: storedShowGrid(),
  view: null,
  entities: [],
  modules: [],
  selection: [],
  tool: "select",
  step: "scene",
  canvasView: "plan",
  planViewport: null,
  cameraFrame: null,
  topToolNote: false,
  past: [],
  future: [],
  layoutPreview: null,
  target: null,
  snap: {
    enabled: true,
    vertex: true,
    endpoint: true,
    edge: true,
    midpoint: true,
    intersection: true,
    parallel: true,
    perpendicular: true,
    module_edge: true,
    row_edge: false,
    user_grid: false,
    grid_spacing_m: 0.5,
    angle15: true
  },
  electrical: {},
  forms: {},
  busy: null,
  toasts: [],
  hover: null,
  vertex: null
};

interface Ctx {
  state: UIState;
  dispatch: (a: Action) => void;
  run: <T>(label: string, op: () => Promise<T>) => Promise<T | undefined>;
  toast: (tone: Toast["tone"], text: string) => void;
}

/**
 * UI state lives in one zustand store (ADR 0012). The reducer above is
 * unchanged; zustand adds subscriptions by selector, so a component that reads
 * only the hover id or the tool re-renders only when that value changes.
 */
export const uiStore = create<Ctx>()((set, get) => {
  const dispatch = (a: Action) => {
    const prev = get().state;
    const next = reducer(prev, a);
    if (next !== prev) set({ state: next });
    if (a.type === "setCanvasView" && next.view) {
      try {
        const key = viewStorageKey(next.view.bundle.project.project_id);
        window.localStorage.setItem(key, next.canvasView);
        if (next.canvasView === "face") window.localStorage.setItem(`${key}.roof`, selectedRoof(next.entities, next.selection)!.id);
      } catch { /* Still switches without storage. */ }
    }
  };
  const toast = (tone: Toast["tone"], text: string) => dispatch({ type: "toast", toast: { tone, text } });
  const run = async <T,>(label: string, op: () => Promise<T>) => {
    if (get().state.busy) {
      toast("info", i18n.t("commands.running"));
      return undefined;
    }
    dispatch({ type: "busy", label });
    try {
      const value = await op();
      if (isMutationView(value)) {
        const view = value;
        if (view.bundle.project.project_id === get().state.view?.bundle.project.project_id) dispatch({ type: "setView", view });
      }
      return value;
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        if (err.detail && typeof err.detail === "object" && "reason" in err.detail && ["revision_mismatch", "history_unavailable"].includes(String(err.detail.reason))) {
          dispatch({ type: "clearHistory" });
          toast("info", i18n.t("history.unavailable"));
          return undefined;
        }
        if (typeof err.detail === "string" && err.detail.startsWith("project has a simulation or weather acquisition in progress")) {
          toast("error", err.message);
          return undefined;
        }
        const id = get().state.view?.bundle.project.project_id;
        if (id) {
          try {
            const view = await engine.project(id);
            if (get().state.view?.bundle.project.project_id === id) dispatch({ type: "setView", view });
            toast("info", i18n.t("s7a.concurrentReload"));
          } catch (reloadError) {
            toast("error", reloadError instanceof Error ? reloadError.message : String(reloadError));
          }
        } else toast("error", err.message);
        return undefined;
      }
      const msg = err instanceof Error ? err.message : String(err);
      dispatch({ type: "toast", toast: { tone: msg.startsWith("Not wired") ? "pending" : "error", text: msg } });
      return undefined;
    } finally {
      dispatch({ type: "busy", label: null });
    }
  };
  return { state: initial, dispatch, run, toast };
});

/** Kept for the component tree's shape; the store itself is module-level. */
export function StoreProvider({ children }: { children: ReactNode }) {
  return children;
}

/** The whole state: re-renders on every change. Prefer `useUI` with a selector in hot paths. */
export function useStore(): Ctx {
  return uiStore();
}

/** One slice of the state; re-renders only when it changes (shallow compare for objects and arrays). */
export function useUI<T>(selector: (s: UIState) => T): T {
  return uiStore(useShallow((c: Ctx) => selector(c.state)));
}

/** Actions only; never re-renders. */
export function useActions(): Pick<Ctx, "dispatch" | "run" | "toast"> {
  return uiStore(useShallow((c: Ctx) => ({ dispatch: c.dispatch, run: c.run, toast: c.toast })));
}

/** Test and tooling hook: put the store back to its first state. */
export function resetStore(): void {
  uiStore.setState({ state: initial });
}

export function useForm<T>(key: string, initialValue: T): [T, (v: T) => void] {
  const stored = useUI((s) => (key in s.forms ? { v: s.forms[key] } : null));
  const { dispatch } = useActions();
  const value = (stored ? stored.v : initialValue) as T;
  return [value, (v: T) => dispatch({ type: "setForm", key, value: v })];
}
