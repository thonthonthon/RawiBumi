import { createContext, ReactNode, useCallback, useContext, useMemo, useReducer } from "react";
import type { ProjectView } from "../types";
import type { PlaneDef, Vec2 } from "../geometry";

export type Step = "site" | "scene" | "layout" | "components" | "electrical" | "meteo" | "simulate" | "results" | "export";
export type Tool = "select" | "polygon" | "rect_engine" | "obstacle" | "keepout" | "measure" | "hole";
export type CanvasView = "plan" | "3d" | "sld";
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
  pairedFieldIds: string[];
  inputsPerMppt: number | null;
  inputsSource: string;
  overrides: Record<number, { on: boolean; reason: string }>;
}

export interface Underlay {
  kind: "none" | "tiles" | "image";
  tileUrl: string;
  tileAttribution: string;
  apiKey: string;
  opacity: number;
  imageDataUrl: string | null;
  imageName: string | null;
  imageMetersPerPixel: number;
  imageOffset: Vec2;
  imageRotationDeg: number;
  registration: "scale" | "similarity" | "perspective";
}

export interface Toast {
  id: number;
  tone: "info" | "ok" | "error" | "pending";
  text: string;
}

export interface UIState {
  view: ProjectView | null;
  entities: Entity[];
  modules: ModuleShape[];
  selection: string[];
  tool: Tool;
  step: Step;
  canvasView: CanvasView;
  past: Entity[][];
  future: Entity[][];
  underlay: Underlay;
  snap: { vertex: boolean; grid: boolean; gridStep: number; angle: boolean };
  electrical: Record<string, ElectricalDraft>;
  forms: Record<string, unknown>;
  busy: string | null;
  toasts: Toast[];
  hover: string | null;
}

type Action =
  | { type: "setView"; view: ProjectView | null }
  | { type: "setStep"; step: Step }
  | { type: "setTool"; tool: Tool }
  | { type: "setCanvasView"; view: CanvasView }
  | { type: "select"; ids: string[] }
  | { type: "hover"; id: string | null }
  | { type: "addEntity"; entity: Entity }
  | { type: "updateEntity"; id: string; patch: Partial<Entity>; history?: boolean }
  | { type: "deleteEntity"; id: string }
  | { type: "checkpoint" }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "setUnderlay"; patch: Partial<Underlay> }
  | { type: "setSnap"; patch: Partial<UIState["snap"]> }
  | { type: "setElectrical"; inverterId: string; patch: Partial<ElectricalDraft> }
  | { type: "setForm"; key: string; value: unknown }
  | { type: "busy"; label: string | null }
  | { type: "toast"; toast: Omit<Toast, "id"> }
  | { type: "dismissToast"; id: number };

let toastSeq = 1;

function entitiesFromView(view: ProjectView, previous: Entity[]): Entity[] {
  const b = view.bundle;
  const hostIds = new Set(b.scene.pv_fields.map((f) => f.support_surface_id));
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
        kind: "surface",
        subtype: f.subtype,
        name: f.name,
        polygon: f.polygon.map((p) => [p[0], p[1]] as Vec2),
        holes: [],
        plane: { mode: "flat", z_m: s?.base_elevation_m ?? 0 },
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

function modulesFromView(view: ProjectView): ModuleShape[] {
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
  return view.scene_view.local_features
    .filter((f) => f.category === "module")
    .map((f) => ({
      id: f.id,
      fieldId: f.pv_field_id ?? "",
      polygon: f.polygon.map((p) => [p[0], p[1]] as Vec2),
      stringId: stringOf.get(f.id) ?? null,
      mpptKey: mpptOf.get(f.id) ?? null
    }));
}

function electricalFromView(view: ProjectView, prev: Record<string, ElectricalDraft>): Record<string, ElectricalDraft> {
  const out: Record<string, ElectricalDraft> = {};
  for (const inv of view.topology_view.inverters) {
    if (prev[inv.inverter_instance_id]) {
      out[inv.inverter_instance_id] = prev[inv.inverter_instance_id];
      continue;
    }
    const lens = inv.mppts.map((m) => m.strings.map((s) => s.module_count));
    const width = Math.max(1, ...lens.map((l) => l.length));
    const notation = lens.map((l) => [...l, ...Array(width - l.length).fill(0)].join(",")).join(" ; ");
    const fields = new Set<string>();
    const strs = view.bundle.electrical_design.strings.filter((s) => inv.mppts.some((m) => m.mppt_instance_id === s.target_mppt_instance_id));
    for (const s of strs)
      for (const mid of s.module_instance_ids) {
        const mi = view.bundle.scene.module_instances.find((x) => x.module_instance_id === mid);
        if (mi) fields.add(mi.pv_field_id);
      }
    out[inv.inverter_instance_id] = {
      notation,
      pairedFieldIds: [...fields],
      inputsPerMppt: width > 1 ? width : null,
      inputsSource: width > 1 ? "Inferred from current topology — confirm with datasheet" : "",
      overrides: {}
    };
  }
  return out;
}

function reducer(state: UIState, action: Action): UIState {
  switch (action.type) {
    case "setView": {
      if (!action.view) return { ...state, view: null, entities: [], modules: [], selection: [], past: [], future: [] };
      return {
        ...state,
        view: action.view,
        entities: entitiesFromView(action.view, state.entities),
        modules: modulesFromView(action.view),
        electrical: electricalFromView(action.view, state.electrical)
      };
    }
    case "setStep":
      return { ...state, step: action.step };
    case "setTool":
      return { ...state, tool: action.tool };
    case "setCanvasView":
      return { ...state, canvasView: action.view };
    case "select":
      return { ...state, selection: action.ids };
    case "hover":
      return state.hover === action.id ? state : { ...state, hover: action.id };
    case "checkpoint":
      return { ...state, past: [...state.past.slice(-99), state.entities], future: [] };
    case "addEntity":
      return {
        ...state,
        past: [...state.past.slice(-99), state.entities],
        future: [],
        entities: [...state.entities, action.entity],
        selection: [action.entity.id]
      };
    case "updateEntity": {
      const entities = state.entities.map((e) => (e.id === action.id ? { ...e, ...action.patch } : e));
      if (action.history === false) return { ...state, entities };
      return { ...state, past: [...state.past.slice(-99), state.entities], future: [], entities };
    }
    case "deleteEntity":
      return {
        ...state,
        past: [...state.past.slice(-99), state.entities],
        future: [],
        entities: state.entities.filter((e) => e.id !== action.id),
        selection: state.selection.filter((s) => s !== action.id)
      };
    case "undo": {
      if (!state.past.length) return state;
      const prev = state.past[state.past.length - 1];
      return { ...state, entities: prev, past: state.past.slice(0, -1), future: [state.entities, ...state.future] };
    }
    case "redo": {
      if (!state.future.length) return state;
      const [next, ...rest] = state.future;
      return { ...state, entities: next, past: [...state.past, state.entities], future: rest };
    }
    case "setUnderlay":
      return { ...state, underlay: { ...state.underlay, ...action.patch } };
    case "setSnap":
      return { ...state, snap: { ...state.snap, ...action.patch } };
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

const initial: UIState = {
  view: null,
  entities: [],
  modules: [],
  selection: [],
  tool: "select",
  step: "scene",
  canvasView: "plan",
  past: [],
  future: [],
  underlay: {
    kind: "none",
    tileUrl: "",
    tileAttribution: "",
    apiKey: "",
    opacity: 0.85,
    imageDataUrl: null,
    imageName: null,
    imageMetersPerPixel: 0.05,
    imageOffset: [0, 0],
    imageRotationDeg: 0,
    registration: "scale"
  },
  snap: { vertex: true, grid: false, gridStep: 0.5, angle: true },
  electrical: {},
  forms: {},
  busy: null,
  toasts: [],
  hover: null
};

interface Ctx {
  state: UIState;
  dispatch: (a: Action) => void;
  run: <T>(label: string, op: () => Promise<T>) => Promise<T | undefined>;
  toast: (tone: Toast["tone"], text: string) => void;
}

const StoreContext = createContext<Ctx | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial);
  const toast = useCallback((tone: Toast["tone"], text: string) => dispatch({ type: "toast", toast: { tone, text } }), []);
  const run = useCallback(async <T,>(label: string, op: () => Promise<T>) => {
    dispatch({ type: "busy", label });
    try {
      return await op();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      dispatch({ type: "toast", toast: { tone: msg.startsWith("Not wired") ? "pending" : "error", text: msg } });
      return undefined;
    } finally {
      dispatch({ type: "busy", label: null });
    }
  }, []);
  const value = useMemo(() => ({ state, dispatch, run, toast }), [state, run, toast]);
  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): Ctx {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore outside StoreProvider");
  return ctx;
}

export function useForm<T>(key: string, initialValue: T): [T, (v: T) => void] {
  const { state, dispatch } = useStore();
  const value = (key in state.forms ? state.forms[key] : initialValue) as T;
  return [value, (v: T) => dispatch({ type: "setForm", key, value: v })];
}
