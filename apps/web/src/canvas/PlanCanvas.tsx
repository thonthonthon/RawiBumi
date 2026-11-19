import { ViewControls } from "./ViewControls";
﻿import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DEMO, engine } from "../client";
import type { ProjectView } from "../types";
import type { TopologyCommand } from "../engine/topology";
import { bearingDeg, bounds, centroid, dist, distToSegment, pointInPolygon, pointInShape, referenceEdgePlane, translatePoly, validatePolygon, Vec2, vertexLabel } from "../geometry";
import { SCENE_TOOL_OPTIONS, type SceneToolOptions } from "../panels/ScenePanel";
import { Entity, uiStore, useActions, useUI, type Tool } from "../state/store";
import { alpha, drawingFont, token } from "../ui/palette";
import { PlanRenderer, webglAvailable } from "./gl/planRenderer";
import { useEntityEdits } from "./useEntityEdits";
import { boxSelect } from "./boxSelect";
import { moduleDragDelta, moduleNudge, useModuleEdits } from "./useModuleEdits";
import { edgeNormal, isRectangle, offsetEdge, rotateClockwise, setEdgeLength } from "./plan/edit";
import { ModuleIndex } from "./plan/moduleIndex";
import { PerfOverlay, perfRequested, usePerf } from "./plan/perf";
import { enabledKinds, Snapper, type SnapItem, type SnapKind } from "./plan/snap";
import { evalExpr, parseAngle, parsePoint, resolvePoint, startsTyped, typedChar, TypedError } from "./plan/typed";
import { usePlanModules } from "./plan/usePlanModules";
import { DRAW_TOOLS, ELECTRICAL_TOOL_SET, NUDGE_LARGE_M, NUDGE_M, RECT_TOOLS, toolByKey, toolDef, toolsForStep } from "./tools";
import { buildMenu, type MenuAction, type MenuTarget } from "./contextMenu";
import { copyToClipboard, pasteOffset, pasteProblem, readClipboard } from "./clipboard";
import { planeMarks } from "./plan/planeMarks";
import { ContextMenu } from "../ui/ContextMenu";
import { useImagery } from "../imagery/useImagery";
import { overlayImage } from "../imagery/overlayImage";
import { loadKey, tileUrl } from "../imagery/provider";
import { calibrateTwoPoints, moveOverlay, overlayCorners, rotateOverlay, scaleFromCorner, type OverlayTransform } from "../imagery/transform";
import { drawElectricalOverlay, overlayStringsOf, type OverlayString } from "./plan/electricalOverlay";
import { drawEntityLabels } from "./plan/labels";
import { renderPlanFigure } from "./figure";
import { useElectricalTools } from "./useElectricalTools";
import { fitView, niceStep, toScreen as screenOf, toWorld as worldOf, unionBox, visibleBox, zoomAt, type Box, type ViewT } from "./plan/viewport";
import { engineCommand, redo, sceneEdit, undo } from "../state/history";
import { dialogTarget, typingTarget } from "../commands/keys";
import { slotOf } from "../engine/layout";
import { drawLayoutOverlay } from "./plan/layoutOverlay";
import { tablesOfModules, useTableEdits } from "./useTableEdits";

/**
 * Plan view (F2). Three stacked layers share one view transform:
 * 1. base, Canvas 2D: background, map or image underlay, grid, origin;
 * 2. WebGL (three.js): surfaces, keep-outs, all modules as one instanced mesh, obstacles;
 * 3. overlay, Canvas 2D: osifont labels, hover, selection, handles, drafts, measure.
 * Module picking uses a flatbush index. Tools and pointer handling are those of UI-A.
 */

type Drag =
  | { kind: "pan"; start: Vec2; startView: ViewT }
  | { kind: "box"; start: Vec2; current: Vec2; add: boolean; hitId: string | null }
  | { kind: "move"; id: string; startWorld: Vec2; original: Vec2[]; originalHoles: Vec2[][]; delta: Vec2 }
  | { kind: "vertex"; id: string; ring: number; index: number; original: Vec2[]; current: Vec2 }
  | { kind: "edge"; id: string; ring: number; index: number; original: Vec2[]; normal: Vec2; startWorld: Vec2; offset: number }
  /** angle: degrees, clockwise positive (the engine's rotate). */
  | { kind: "rotate"; id: string; pivot: Vec2; startBearing: number; original: Vec2[]; originalHoles: Vec2[][]; angle: number }
  | { kind: "rect"; start: Vec2; current: Vec2 }
  | { kind: "modules"; ids: string[]; startWorld: Vec2; delta: Vec2 }
  /** PV layout step: tables dragged by one of their modules (an engine table edit on release). */
  | { kind: "tables"; ids: string[]; startWorld: Vec2; delta: Vec2 }
  /** UX1: an unlocked image overlay being moved, scaled from a corner, or rotated; one save on release. */
  | { kind: "overlay-move"; startWorld: Vec2; original: OverlayTransform; current: OverlayTransform }
  | { kind: "overlay-scale"; corner: number; original: OverlayTransform; current: OverlayTransform }
  | { kind: "overlay-rotate"; pivot: Vec2; startBearing: number; original: OverlayTransform; current: OverlayTransform };

/** The first pick of a two-step tool, waiting for the second (click or typed). */
type Pick = { kind: "move"; base: Vec2 } | { kind: "rotate"; pivot: Vec2 } | { kind: "rect"; start: Vec2 } | null;

const tileCache = new Map<string, HTMLImageElement>();

/** The overlay's rotation handle: 28 px outside the middle of its top edge (screen points). */
function overlayRotateKnob(corners: Vec2[]): { base: Vec2; at: Vec2 } {
  const base: Vec2 = [(corners[0][0] + corners[1][0]) / 2, (corners[0][1] + corners[1][1]) / 2];
  const centre: Vec2 = [(corners[0][0] + corners[2][0]) / 2, (corners[0][1] + corners[2][1]) / 2];
  const dx = base[0] - centre[0], dy = base[1] - centre[1], l = Math.hypot(dx, dy) || 1;
  return { base, at: [base[0] + (dx / l) * 28, base[1] + (dy / l) * 28] };
}
/** Snap tolerance on screen. */
const SNAP_PX = 10;

/**
 * Snap geometry in the engine's collection order (surfaces, obstacles), then
 * keep-out zones and holes, which the engine scene does not have yet.
 */
function snapItemsOf(entities: readonly Entity[]): SnapItem[] {
  const visible = entities.filter((e) => !e.hidden);
  const ring = (e: Entity): SnapItem => ({ id: e.id, points: e.polygon, closed: true });
  return [
    ...visible.filter((e) => e.kind === "surface").map(ring),
    ...visible.filter((e) => e.kind === "obstacle").map(ring),
    ...visible.filter((e) => e.kind === "keepout").map(ring),
    ...visible.flatMap((e) => e.holes.map((h, k) => ({ id: `${e.id}#hole${k + 1}`, points: h, closed: true })))
  ];
}

/** Snap glyphs on the overlay, one shape per kind (DESIGN.md §6: the active snap shows as a glyph and a label). */
function drawSnapGlyph(ctx: CanvasRenderingContext2D, kind: SnapKind | "angle15", p: Vec2) {
  const [x, y] = p;
  ctx.strokeStyle = token("role-info-on-stage");
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  switch (kind) {
    case "vertex":
    case "endpoint":
      ctx.rect(x - 5, y - 5, 10, 10);
      break;
    case "midpoint":
      ctx.moveTo(x, y - 6);
      ctx.lineTo(x + 6, y + 5);
      ctx.lineTo(x - 6, y + 5);
      ctx.closePath();
      break;
    case "intersection":
      ctx.moveTo(x - 6, y - 6);
      ctx.lineTo(x + 6, y + 6);
      ctx.moveTo(x + 6, y - 6);
      ctx.lineTo(x - 6, y + 6);
      break;
    case "perpendicular":
      ctx.moveTo(x - 6, y + 5);
      ctx.lineTo(x + 6, y + 5);
      ctx.moveTo(x, y + 5);
      ctx.lineTo(x, y - 6);
      break;
    case "parallel":
      ctx.moveTo(x - 6, y + 4);
      ctx.lineTo(x - 1, y - 6);
      ctx.moveTo(x + 1, y + 4);
      ctx.lineTo(x + 6, y - 6);
      break;
    case "user_grid":
      ctx.moveTo(x - 6, y);
      ctx.lineTo(x + 6, y);
      ctx.moveTo(x, y - 6);
      ctx.lineTo(x, y + 6);
      break;
    default:
      // edge, module and row edges, 15° steps
      ctx.moveTo(x, y - 6);
      ctx.lineTo(x + 6, y);
      ctx.lineTo(x, y + 6);
      ctx.lineTo(x - 6, y);
      ctx.closePath();
  }
  ctx.stroke();
}

/** Sizes a canvas backing store for the device pixel ratio and returns a context in CSS pixels. */
function context2d(canvas: HTMLCanvasElement | null, w: number, h: number, dpr: number): CanvasRenderingContext2D | null {
  if (!canvas) return null;
  const bw = Math.round(w * dpr);
  const bh = Math.round(h * dpr);
  if (canvas.width !== bw || canvas.height !== bh) {
    canvas.width = bw;
    canvas.height = bh;
  }
  const ctx = canvas.getContext("2d");
  ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

/** Keep any selection the user makes while a draw command is pending. */
export function rememberDrawSelection() {
  const remembered = uiStore.getState().state.selection;
  return (id: string) => {
    const { state, dispatch } = uiStore.getState();
    if (state.selection.length === remembered.length && state.selection.every((value, i) => value === remembered[i])) {
      dispatch({ type: "select", ids: [id] });
    }
    dispatch({ type: "setTool", tool: "select" });
  };
}

export function PlanCanvas() {
  const [savedViewport] = useState(() => uiStore.getState().state.planViewport);
  const { t } = useTranslation();
  const { dispatch, run, toast } = useActions();
  const { commitGeometry, commitMove, rotate, moveVertex, insertVertex, deleteVertex, moveEdge, editDimension, addHole, removeHole, editPlane, duplicate } = useEntityEdits();
  const tableEdits = useTableEdits();
  const moduleEdits = useModuleEdits();
  const state = useUI((s) => ({
    entities: s.entities,
    busy: s.busy,
    selection: s.selection,
    tool: s.tool,
    snap: s.snap,
    showGrid: s.showGrid,
    view: s.view,
    step: s.step,
    hover: s.hover,
    layoutPreview: s.layoutPreview,
    canvasView: s.canvasView,
    vertexSel: s.vertex,
    undoTop: s.past.at(-1),
    redoTop: s.future[0],
    toolOptions: (s.forms["scene.tools"] as SceneToolOptions | undefined) ?? SCENE_TOOL_OPTIONS
  }));
  const wrapRef = useRef<HTMLDivElement>(null);
  const baseRef = useRef<HTMLCanvasElement>(null);
  const glRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<PlanRenderer | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [glFailed, setGlFailed] = useState(false);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [dpr, setDpr] = useState(() => window.devicePixelRatio || 1);
  const [view, setView] = useState<ViewT>(savedViewport?.view ?? { cx: 20, cy: 9, scale: 18 });
  const [cursor, setCursor] = useState<Vec2 | null>(null);
  const [draft, setDraft] = useState<Vec2[]>([]);
  const [measure, setMeasure] = useState<Vec2[]>([]);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [shift, setShift] = useState(false);
  const [alt, setAlt] = useState(false);
  const space = useRef(false);
  const [pick, setPick] = useState<Pick>(null);
  const [typed, setTyped] = useState<string | null>(null);
  const [typedError, setTypedError] = useState<string | null>(null);
  const [dimEdit, setDimEdit] = useState<{ id: string; edge: number; value: string; at: Vec2; error?: string } | null>(null);
  // UX2: the context menu, the selected vertex, reference-edge pick mode and the hovered edge of the selection.
  const [menu, setMenu] = useState<{ at: Vec2; target: MenuTarget; selectionKey: string; returnFocus: Element | null } | null>(null);
  const rightPress = useRef<{ start: Vec2; moved: boolean } | null>(null);

  const [refPick, setRefPick] = useState<string | null>(null);
  const [hoverEdge, setHoverEdge] = useState<{ id: string; index: number } | null>(null);
  // UX1: persisted imagery, the overlay image, and two-point calibration (points picked, then the true distance).
  const { imagery, save: saveImagery, projectId: imageryProject } = useImagery();
  const overlayInfo = imagery.overlay;
  const [calib, setCalib] = useState<{ points: Vec2[]; distance: string; error?: string } | null>(null);
  const lastZ = useRef(0);
  const [tick, forceTick] = useState(0);
  const fittedRef = useRef<string | null>(savedViewport ? state.view?.bundle.project.project_id ?? null : null);
  // True once the user pans or zooms; until then the plan re-fits when the stage resizes.
  const userMovedRef = useRef(!!savedViewport);

  const { entities, selection, tool, snap, view: pview, step, layoutPreview, vertexSel } = state;
  const setVertexSel = useCallback((vertex: { id: string; ring: number; index: number } | null) => dispatch({ type: "setVertex", vertex }), [dispatch]);
  const overlayDrag = drag && (drag.kind === "overlay-move" || drag.kind === "overlay-scale" || drag.kind === "overlay-rotate") ? drag : null;
  /** The overlay transform on screen: the gesture's preview, else the saved one. */
  const overlayT: OverlayTransform | null = overlayDrag?.current ?? overlayInfo?.transform ?? null;
  const overlayEditable = !!overlayInfo && !overlayInfo.locked && tool === "select" && !ELECTRICAL_TOOL_SET.has(tool);
  const layoutStep = step === "layout";
  const tables = useMemo(() => pview?.table_layout?.tables ?? [], [pview]);
  const electrical = step === "electrical";
  const selected = entities.find((e) => selection.includes(e.id)) ?? null;
  const editable = selected && !selected.locked ? selected : null;

  // A new tool starts clean.
  useEffect(() => {
    setPick(null);
    setTyped(null);
    setTypedError(null);
    setDraft([]);
  }, [tool]);

  // A vertex selection and a reference-edge pick belong to one object, step and tool.
  const selectedId = selected?.id ?? null;
  useEffect(() => {
    setVertexSel(null);
    setRefPick((id) => (id && id === selectedId ? id : null));
    setHoverEdge(null);
  }, [selectedId, step, tool]);
  useEffect(() => { if (tool !== "select") setRefPick(null); }, [tool]);

  // The menu closes when the step or view changes, or the selection changes from elsewhere.
  const selectionKey = selection.join("|");
  useEffect(() => { setMenu(null); }, [step, state.canvasView]);
  useEffect(() => { setMenu((m) => (m && m.selectionKey !== selectionKey ? null : m)); }, [selectionKey]);

  useEffect(() => {
    const start = () => { dispatch({ type: "setTool", tool: "select" }); setCalib({ points: [], distance: "" }); };
    window.addEventListener("rawibumi:overlay-calibrate", start);
    return () => window.removeEventListener("rawibumi:overlay-calibrate", start);
  }, [dispatch]);

  /** Scale the overlay about the first point so the two points are the typed distance apart; lock it once saved. */
  async function applyCalibration() {
    if (!calib || calib.points.length !== 2 || !overlayInfo) return;
    try {
      const transform = calibrateTwoPoints(overlayInfo.transform, calib.points[0], calib.points[1], Number(calib.distance));
      setCalib(null);
      await saveImagery({ ...imagery, overlay: { ...overlayInfo, transform, locked: true } }, t("imagery.calibrating"));
    } catch (err) {
      setCalib({ ...calib, error: err instanceof Error ? err.message : String(err) });
    }
  }

  useEffect(() => {
    const onPick = (e: Event) => {
      const id = (e as CustomEvent<string>).detail;
      if (!selection.includes(id)) dispatch({ type: "select", ids: [id] });
      dispatch({ type: "setTool", tool: "select" });
      setRefPick(id);
    };
    window.addEventListener("rawibumi:pick-reference-edge", onPick);
    return () => window.removeEventListener("rawibumi:pick-reference-edge", onPick);
  }, [selection, dispatch]);

  // Demo builds can swap in a synthetic layout for the 100k-module performance check.
  const { modules, synthetic } = usePlanModules();
  const index = useMemo(() => new ModuleIndex(modules), [modules]);
  const elec = useElectricalTools(modules);
  const selectedSet = useMemo(() => new Set(selection), [selection]);
  const perf = usePerf(rendererRef, index);

  const toScreen = useCallback((p: Vec2): Vec2 => screenOf(view, size, p), [view, size]);
  const toWorld = useCallback((s: Vec2): Vec2 => worldOf(view, size, s), [view, size]);

  // ---- sizing -------------------------------------------------------------
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setSize({ w: el.clientWidth, h: el.clientHeight });
      setDpr(window.devicePixelRatio || 1);
    });
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // ---- WebGL layer ----------------------------------------------------------
  useEffect(() => {
    const canvas = glRef.current;
    if (!canvas) return;
    if (!webglAvailable()) {
      setGlFailed(true);
      return;
    }
    try {
      rendererRef.current = new PlanRenderer(canvas);
    } catch {
      setGlFailed(true);
      return;
    }
    return () => {
      rendererRef.current?.dispose();
      rendererRef.current = null;
    };
  }, []);

  // Resizing reallocates the drawing buffer, so it runs only when the stage size changes.
  useEffect(() => {
    rendererRef.current?.setSize(size, dpr);
  }, [size, dpr]);

  useEffect(() => {
    const r = rendererRef.current;
    if (!r) return;
    r.setView(view);
    r.invalidate();
  }, [size, dpr, view]);

  useEffect(() => {
    const r = rendererRef.current;
    if (!r) return;
    r.setEntities(entities);
    r.invalidate();
  }, [entities]);

  useEffect(() => {
    const r = rendererRef.current;
    if (!r) return;
    r.setModules(modules);
    r.setModuleLooks(electrical, selectedSet);
    r.invalidate();
  }, [modules, electrical, selectedSet]);

  // Demo builds expose the transform so screenshot scripts can click world coordinates.
  useEffect(() => {
    if (!DEMO) return;
    const r = () => overlayRef.current?.getBoundingClientRect();
    (window as unknown as { __rawibumiPlan: unknown }).__rawibumiPlan = {
      toPage: (x: number, y: number) => {
        const s = toScreen([x, y]);
        const b = r();
        return [s[0] + (b?.left ?? 0), s[1] + (b?.top ?? 0)];
      },
      view,
      /** Centre of the i-th module, in world metres. */
      moduleCentre: (i: number) => (modules[i] ? centroid(modules[i].polygon) : null),
      modulePolygon: (i: number) => modules[i]?.polygon ?? null,
      moduleId: (i: number) => modules[i]?.id ?? null,
      /** String id of the i-th module (electrical tests). */
      moduleString: (i: number) => modules[i]?.stringId ?? null,
      moduleCount: () => modules.length,
      /** F7 parity test: the plan's WebGL layer now, and the report figure renderer at the same view. */
      glSnapshot: () => {
        rendererRef.current?.renderNow();
        return glRef.current?.toDataURL("image/png") ?? null;
      },
      figureGl: () =>
        renderPlanFigure({ entities, modules, strings: [], electrical, size, dpr, view, glOnly: true, labels: { north: "", draft: "" } }).png
    };
  }, [toScreen, view, modules, entities, electrical, size, dpr]);

  useEffect(() => {
    dispatch({ type: "setPlanViewport", viewport: { view, size } });
  }, [dispatch, view, size]);

  // ---- fit ----------------------------------------------------------------
  const fit = useCallback(() => {
    const visible = entities.filter((e) => !e.hidden).map((e) => e.polygon);
    const box = unionBox(visible.length ? bounds(visible) : null, index.bounds) ?? { minX: -15, minY: -10, maxX: 15, maxY: 10 };
    setView(fitView(box, size));
    userMovedRef.current = false;
  }, [entities, index, size]);

  useEffect(() => {
    const key = pview?.bundle.project.project_id ?? null;
    if (!key || size.w <= 200) return;
    if (fittedRef.current !== key || !userMovedRef.current) {
      fittedRef.current = key;
      fit();
    }
    // Re-fit on project change and on stage resize, but not when entities change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pview?.bundle.project.project_id, size.w, size.h, synthetic]);

  const moveView = useCallback((v: ViewT) => {
    userMovedRef.current = true;
    setView(v);
  }, []);

  // ---- image underlay loading --------------------------------------------
  // The persisted overlay image, from the project's asset route (never a data URL in the project).
  const overlaySrc = overlayInfo && imageryProject ? engine.imageryAssetUrl(imageryProject, overlayInfo.assetId) : "";
  useEffect(() => {
    if (!overlaySrc) {
      imgRef.current = null;
      forceTick((n) => n + 1);
      return;
    }
    const img = overlayImage(overlaySrc); // shared with the report figure (UXF1, U2-15)
    imgRef.current = img;
    if (img.complete && img.naturalWidth) forceTick((n) => n + 1);
    else img.addEventListener("load", () => forceTick((n) => n + 1), { once: true });
  }, [overlaySrc]);
  const satellite = imagery.satellite;
  const satelliteKey = satellite ? loadKey(satellite.credentialReference) : "";
  const satelliteShown = !!satellite && (!satellite.template.includes("{key}") || !!satelliteKey);

  // ---- snapping (the engine's SnapEngine rules, src/canvas/plan/snap.ts) ----
  const snapItems = useMemo(() => snapItemsOf(entities), [entities]);
  const moduleEdges = useCallback(
    (box: Box) =>
      index
        .search(box)
        .sort((a, b) => a - b)
        .flatMap((i) => {
          const pts = modules[i].polygon;
          return pts.map((a, k) => [i * 4 + k, modules[i].id, a, pts[(k + 1) % pts.length]] as [number, string, Vec2, Vec2]);
        }),
    [index, modules]
  );
  const snappers = useMemo(() => {
    const cache = new Map<string, Snapper>();
    return (exclude = "") => {
      let s = cache.get(exclude);
      if (!s) {
        s = new Snapper(snapItems, { module_edge: moduleEdges }, exclude ? [exclude] : []);
        cache.set(exclude, s);
      }
      return s;
    };
  }, [snapItems, moduleEdges]);
  const kinds = useMemo(() => enabledKinds(snap), [snap]);

  /**
   * Snap a world point. `from` and `prev` are the last two placed points (for
   * parallel and perpendicular, and the 15° Shift constraint). Alt suspends snapping.
   */
  const snapPoint = useCallback(
    (w: Vec2, from?: Vec2, prev?: Vec2, exclude?: string): { p: Vec2; kind: SnapKind | "angle15" | null } => {
      const dir: Vec2 | null = from && prev && (from[0] !== prev[0] || from[1] !== prev[1]) ? [from[0] - prev[0], from[1] - prev[1]] : null;
      const r = snappers(exclude).resolve(w, {
        toleranceM: SNAP_PX / view.scale,
        enabled: kinds,
        override: alt,
        gridSpacingM: snap.user_grid ? (snap.grid_spacing_m ?? null) : null,
        anchor: dir ? from : null,
        referenceDirection: dir
      });
      if (r.applied) return { p: r.point, kind: r.kind };
      if (from && shift && snap.angle15 && !alt) {
        const ang = Math.atan2(w[1] - from[1], w[0] - from[0]);
        const q = (Math.round(ang / (Math.PI / 12)) * Math.PI) / 12;
        const d = dist(w, from);
        return { p: [from[0] + d * Math.cos(q), from[1] + d * Math.sin(q)], kind: "angle15" };
      }
      return { p: w, kind: null };
    },
    [snappers, kinds, snap, view.scale, shift, alt]
  );

  // ---- layer 1: base (background, underlay, grid, origin) ------------------
  useEffect(() => {
    const ctx = context2d(baseRef.current, size.w, size.h, dpr);
    if (!ctx) return;
    ctx.fillStyle = token("role-stage-bg");
    ctx.fillRect(0, 0, size.w, size.h);

    if (satelliteShown && satellite && pview) {
      const lat0 = pview.scene_view.site.latitude_deg;
      const lon0 = pview.scene_view.site.longitude_deg;
      const mPerDegLon = 111320 * Math.cos((lat0 * Math.PI) / 180);
      const mPerDegLat = 110540;
      const z = Math.max(0, Math.min(21, Math.round(Math.log2(156543.03 * Math.cos((lat0 * Math.PI) / 180) * view.scale))));
      const n = 2 ** z;
      const lonToX = (lon: number) => ((lon + 180) / 360) * n;
      const latToY = (lat: number) => ((1 - Math.log(Math.tan((lat * Math.PI) / 180) + 1 / Math.cos((lat * Math.PI) / 180)) / Math.PI) / 2) * n;
      const xToLon = (x: number) => (x / n) * 360 - 180;
      const yToLat = (y: number) => (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) * 180) / Math.PI;
      const tl = toWorld([0, 0]);
      const br = toWorld([size.w, size.h]);
      const x0 = Math.floor(lonToX(lon0 + tl[0] / mPerDegLon));
      const x1 = Math.floor(lonToX(lon0 + br[0] / mPerDegLon));
      const y0 = Math.floor(latToY(lat0 + tl[1] / mPerDegLat));
      const y1 = Math.floor(latToY(lat0 + br[1] / mPerDegLat));
      ctx.globalAlpha = satellite.opacity;
      if ((x1 - x0 + 1) * (y1 - y0 + 1) <= 64)
        for (let tx = x0; tx <= x1; tx++)
          for (let ty = y0; ty <= y1; ty++) {
            const url = tileUrl(satellite.template, z, tx, ty, satelliteKey);
            let img = tileCache.get(url);
            if (!img) {
              img = new Image();
              img.crossOrigin = "anonymous";
              img.onload = () => forceTick((k) => k + 1);
              img.src = url;
              tileCache.set(url, img);
            }
            if (!img.complete || !img.naturalWidth) continue;
            const a = toScreen([(xToLon(tx) - lon0) * mPerDegLon, (yToLat(ty) - lat0) * mPerDegLat]);
            const b = toScreen([(xToLon(tx + 1) - lon0) * mPerDegLon, (yToLat(ty + 1) - lat0) * mPerDegLat]);
            ctx.drawImage(img, a[0], a[1], b[0] - a[0], b[1] - a[1]);
          }
      ctx.globalAlpha = 1;
    }

    const img = imgRef.current;
    if (overlayInfo && overlayT && img && img.complete && img.naturalWidth) {
      const o = toScreen(overlayT.offset);
      ctx.save();
      ctx.globalAlpha = overlayInfo.opacity;
      ctx.translate(o[0], o[1]);
      ctx.rotate((-overlayT.rotationDeg * Math.PI) / 180);
      // The registration is in the uploaded image's pixels; draw at that size whatever the decoded size.
      ctx.drawImage(img, 0, 0, overlayInfo.width * overlayT.sx * view.scale, overlayInfo.height * overlayT.sy * view.scale);
      ctx.restore();
    }

    // UXF1/UXF2 (U2-14, U2-17, U2-19): a fixed grid at the grid-spacing setting, whatever the zoom, with a stronger line
    // every 10 cells; lines closer than 6 px are skipped. Hairlines; over imagery only the major lines get a faint halo.
    if (state.showGrid) {
      const onImagery = satelliteShown || !!overlayInfo;
      const step = state.snap.grid_spacing_m && state.snap.grid_spacing_m > 0 ? state.snap.grid_spacing_m : 1;
      const major = step * 10;
      const tl = toWorld([0, 0]);
      const br = toWorld([size.w, size.h]);
      const gridPath = (g: number) => {
        ctx.beginPath();
        for (let x = Math.floor(tl[0] / g) * g; x <= br[0]; x += g) {
          const s = toScreen([x, 0]);
          ctx.moveTo(Math.round(s[0]) + 0.5, 0);
          ctx.lineTo(Math.round(s[0]) + 0.5, size.h);
        }
        for (let y = Math.floor(br[1] / g) * g; y <= tl[1]; y += g) {
          const s = toScreen([0, y]);
          ctx.moveTo(0, Math.round(s[1]) + 0.5);
          ctx.lineTo(size.w, Math.round(s[1]) + 0.5);
        }
      };
      const drawGrid = (g: number, color: string, halo: boolean) => {
        if (halo) {
          ctx.strokeStyle = alpha("role-stage-deep", 0.18);
          ctx.lineWidth = 3;
          gridPath(g);
          ctx.stroke();
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        gridPath(g);
        ctx.stroke();
      };
      if (step * view.scale >= 6) drawGrid(step, onImagery ? alpha("role-stage-text", 0.22) : alpha("role-stage-grid", 0.45), false);
      if (major * view.scale >= 6) drawGrid(major, onImagery ? alpha("role-stage-text", 0.5) : token("role-stage-grid"), onImagery);
    }
    // UXF2 (U2-18): the scene origin, X (east) and Y (north) arrows with labels, above the grid and imagery.
    const o = toScreen([0, 0]);
    const arrow = (dx: number, dy: number, label: string) => {
      const tip: Vec2 = [o[0] + dx * 30, o[1] + dy * 30];
      const side: Vec2 = [-dy * 5, dx * 5];
      ctx.beginPath();
      ctx.moveTo(o[0], o[1]);
      ctx.lineTo(tip[0], tip[1]);
      ctx.moveTo(tip[0] - dx * 8 + side[0], tip[1] - dy * 8 + side[1]);
      ctx.lineTo(tip[0], tip[1]);
      ctx.lineTo(tip[0] - dx * 8 - side[0], tip[1] - dy * 8 - side[1]);
      ctx.stroke();
      ctx.fillText(label, tip[0] + dx * 9 + (dy ? 6 : 0), tip[1] + dy * 9 - (dx ? 6 : 0));
    };
    ctx.save();
    ctx.lineCap = "round";
    ctx.font = drawingFont(11);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const [width, color] of [[5, alpha("role-stage-bg", 0.8)], [2, token("role-stage-text")]] as const) {
      ctx.lineWidth = width;
      ctx.strokeStyle = color;
      ctx.fillStyle = token("role-stage-text");
      arrow(1, 0, "X");
      arrow(0, -1, "Y");
    }
    ctx.beginPath();
    ctx.arc(o[0], o[1], 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }, [size, dpr, view, satellite, satelliteKey, satelliteShown, overlayInfo, overlayT, pview, tick, toScreen, toWorld, state.showGrid, state.snap.user_grid, state.snap.grid_spacing_m]);

  // ---- layer 3: overlay (labels, hover, selection, drafts, measure) --------
  // Strings in wiring order with their MPPT colour index and worst engine check (electrical step).
  const overlayStrings = useMemo(() => overlayStringsOf(pview, modules), [pview, modules]);

  useEffect(() => {
    const ctx = context2d(overlayRef.current, size.w, size.h, dpr);
    if (!ctx) return;
    ctx.clearRect(0, 0, size.w, size.h);
    const path = (poly: Vec2[], holes: Vec2[][] = []) => {
      ctx.beginPath();
      for (const ring of [poly, ...holes]) {
        ring.forEach((p, i) => {
          const s = toScreen(p);
          if (i === 0) ctx.moveTo(s[0], s[1]);
          else ctx.lineTo(s[0], s[1]);
        });
        ctx.closePath();
      }
    };

    if (layoutStep)
      drawLayoutOverlay({
        ctx,
        toScreen,
        scale: view.scale,
        tables,
        preview: layoutPreview,
        previewBefore: layoutPreview?.request.pv_field_id ? tables.filter((x) => x.pv_field_id === layoutPreview.request.pv_field_id) : [],
        dragging: drag?.kind === "tables" ? { ids: new Set(drag.ids), delta: drag.delta } : null,
        labels: {
          preview: t("layout.previewLabel", { count: layoutPreview?.module_count ?? 0 }),
          pinned: t("layout.pinned"),
          removed: t("layout.removedByYou")
        }
      });

    // Electrical lens: strings in wiring order, polarity, ids with live-check glyphs, path and lasso.
    if (electrical) {
      const box = visibleBox(view, size);
      const onScreen = (s: OverlayString) =>
        s.modules.some((id) => {
          const p = elec.centres.get(id);
          return !!p && p[0] >= box.minX && p[0] <= box.maxX && p[1] >= box.minY && p[1] <= box.maxY;
        });
      drawElectricalOverlay({
        ctx,
        toScreen,
        scale: view.scale,
        centres: elec.centres,
        strings: overlayStrings.filter(onScreen),
        highlighted: elec.highlighted,
        path: elec.path,
        pathCursor: tool === "string_path" ? cursor : null,
        lasso: elec.lasso,
        picked: elec.picked
      });
    }

    // UX1: an unlocked overlay shows its outline, corner handles and rotation handle.
    if (overlayEditable && overlayInfo && overlayT) {
      const corners = overlayCorners(overlayT, overlayInfo.width, overlayInfo.height).map(toScreen);
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = token("role-info-on-stage");
      ctx.lineWidth = 1.5;
      ctx.beginPath(); corners.forEach((c, i) => (i ? ctx.lineTo(c[0], c[1]) : ctx.moveTo(c[0], c[1]))); ctx.closePath(); ctx.stroke();
      ctx.setLineDash([]);
      for (const c of corners) {
        ctx.fillStyle = token("role-stage-deep");
        ctx.fillRect(c[0] - 5, c[1] - 5, 10, 10);
        ctx.strokeRect(c[0] - 5, c[1] - 5, 10, 10);
      }
      const knob = overlayRotateKnob(corners);
      ctx.beginPath(); ctx.moveTo(knob.base[0], knob.base[1]); ctx.lineTo(knob.at[0], knob.at[1]); ctx.stroke();
      ctx.beginPath(); ctx.arc(knob.at[0], knob.at[1], 6, 0, Math.PI * 2);
      ctx.fillStyle = token("role-stage-deep"); ctx.fill(); ctx.stroke();
    }
    // UX1 two-point calibration: the picked points and the line between them.
    if (calib) {
      const pts = [...calib.points, ...(calib.points.length === 1 && cursor ? [cursor] : [])].map(toScreen);
      ctx.strokeStyle = token("role-info-on-stage");
      ctx.fillStyle = token("role-info-on-stage");
      ctx.lineWidth = 2;
      if (pts.length === 2) { ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]); ctx.lineTo(pts[1][0], pts[1][1]); ctx.stroke(); }
      for (const p of pts) { ctx.beginPath(); ctx.arc(p[0], p[1], 4, 0, Math.PI * 2); ctx.fill(); }
    }

    // Entity names
    if (view.scale > 6) drawEntityLabels(ctx, entities, toScreen, "draft");

    // Hover outline
    const hov = entities.find((e) => e.id === state.hover);
    if (hov && !selection.includes(hov.id)) {
      path(hov.polygon, hov.holes);
      ctx.strokeStyle = alpha("role-selection", 0.6);
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // Selection, with edge lengths and handles
    const sel = selected ? previewEntity(selected, drag) : null;
    if (sel) {
      path(sel.polygon, sel.holes);
      ctx.strokeStyle = token("role-selection");
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.font = drawingFont(11);
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      for (const l of dimensionLabels(sel)) {
        if (dimEdit && dimEdit.id === sel.id && dimEdit.edge === l.edge) continue;
        const label = `${l.len.toFixed(2)} m`;
        const w = ctx.measureText(label).width + 8;
        ctx.fillStyle = token("role-stage-deep");
        ctx.fillRect(l.at[0] - w / 2, l.at[1] - 8, w, 16);
        ctx.fillStyle = token("role-selection");
        ctx.fillText(label, l.at[0], l.at[1]);
      }
      // UX2 (U6): on a single selected roof, vertex letters as in the Inspector, the hovered and reference
      // edges, and the downhill arrow with the high and low vertices, all from planeZ.
      if (sel.kind === "surface" && selection.length === 1) {
        const n = sel.polygon.length;
        const marks = planeMarks(sel.polygon, sel.plane);
        const strokeEdge = (i: number, width: number, colour: string) => {
          const a = toScreen(sel.polygon[i]), b = toScreen(sel.polygon[(i + 1) % n]);
          ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]);
          ctx.strokeStyle = colour; ctx.lineWidth = width; ctx.stroke();
        };
        if (hoverEdge?.id === sel.id && hoverEdge.index < n) strokeEdge(hoverEdge.index, 6, alpha("role-selection", refPick ? 0.8 : 0.45));
        if (marks.referenceEdge !== null) strokeEdge(marks.referenceEdge, 4, token("role-info-on-stage"));
        const c = toScreen(centroid(sel.polygon));
        const outward = (v: Vec2, gap: number): Vec2 => {
          const p = toScreen(v), dx = p[0] - c[0], dy = p[1] - c[1], l = Math.hypot(dx, dy) || 1;
          return [p[0] + (dx / l) * gap, p[1] + (dy / l) * gap];
        };
        ctx.font = drawingFont(12);
        ctx.fillStyle = token("role-selection");
        sel.polygon.forEach((v, i) => { const p = outward(v, 15); ctx.fillText(vertexLabel(i), p[0], p[1]); });
        if (marks.arrow) {
          const a = toScreen(marks.arrow.from), b = toScreen(marks.arrow.to);
          const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
          ctx.strokeStyle = token("role-info-on-stage");
          ctx.fillStyle = token("role-info-on-stage");
          ctx.lineWidth = 2;
          ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
          ctx.beginPath();
          ctx.moveTo(b[0], b[1]);
          ctx.lineTo(b[0] - 10 * Math.cos(ang - 0.45), b[1] - 10 * Math.sin(ang - 0.45));
          ctx.lineTo(b[0] - 10 * Math.cos(ang + 0.45), b[1] - 10 * Math.sin(ang + 0.45));
          ctx.closePath(); ctx.fill();
        }
        ctx.font = drawingFont(11);
        for (const [point, key] of [[marks.high, "ux2.high"], [marks.low, "ux2.low"]] as const) {
          if (!point) continue;
          const p = outward(point, 32), text = t(key), w = ctx.measureText(text).width + 8;
          ctx.fillStyle = token("role-stage-deep");
          ctx.fillRect(p[0] - w / 2, p[1] - 8, w, 16);
          ctx.fillStyle = token("role-info-on-stage");
          ctx.fillText(text, p[0], p[1]);
        }
      }
      if (!selected!.locked) {
        [sel.polygon, ...sel.holes].forEach((ring, r) =>
          ring.forEach((v, i) => {
            const s = toScreen(v);
            const chosen = vertexSel?.id === sel.id && vertexSel.ring === r && vertexSel.index === i;
            ctx.fillStyle = token(chosen ? "role-selection" : "role-stage-deep");
            ctx.strokeStyle = token("role-selection");
            ctx.lineWidth = 1.5;
            ctx.fillRect(s[0] - 4.5, s[1] - 4.5, 9, 9);
            ctx.strokeRect(s[0] - 4.5, s[1] - 4.5, 9, 9);
          }));
        // Edge handles: drag to move the edge along its normal.
        if (tool === "select") {
          const n = sel.polygon.length;
          for (let i = 0; i < n; i++) {
            const a = toScreen(sel.polygon[i]);
            const b = toScreen(sel.polygon[(i + 1) % n]);
            if (Math.hypot(b[0] - a[0], b[1] - a[1]) < 24) continue;
            const m: Vec2 = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
            ctx.fillStyle = token("role-stage-deep");
            ctx.strokeStyle = token("role-selection");
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(m[0], m[1] - 5);
            ctx.lineTo(m[0] + 5, m[1]);
            ctx.lineTo(m[0], m[1] + 5);
            ctx.lineTo(m[0] - 5, m[1]);
            ctx.closePath();
            ctx.fill();
            ctx.stroke();
          }
        }
        const rh = rotateHandle(sel.polygon);
        const s = toScreen(rh.handle);
        const c = toScreen(rh.anchor);
        ctx.strokeStyle = token("role-selection");
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(c[0], c[1]);
        ctx.lineTo(s[0], s[1] + 22);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(s[0], s[1] + 22, 6, 0, Math.PI * 2);
        ctx.fillStyle = token("role-stage-deep");
        ctx.fill();
        ctx.stroke();
      }
      if (drag?.kind === "rotate") {
        const c = toScreen(drag.pivot);
        ctx.fillStyle = token("role-selection");
        ctx.font = drawingFont(12);
        ctx.fillText(t("tools.rotateLabel", { a: drag.angle.toFixed(1) }), c[0], c[1] - 14);
      }
      if (drag?.kind === "move") {
        const c = toScreen(centroid(sel.polygon));
        ctx.fillStyle = token("role-selection");
        ctx.font = drawingFont(12);
        ctx.fillText(`Δ ${drag.delta[0].toFixed(2)}, ${drag.delta[1].toFixed(2)} m`, c[0], c[1] - 14);
      }
    }

    if (drag?.kind === "box") {
      const a = toScreen(drag.start), b = toScreen(drag.current);
      ctx.save();
      ctx.fillStyle = alpha("role-selection", 0.12);
      ctx.strokeStyle = token("role-selection");
      ctx.lineWidth = 1.5;
      ctx.setLineDash(b[0] < a[0] ? [6, 4] : []);
      const x = Math.min(a[0], b[0]), y = Math.min(a[1], b[1]);
      ctx.fillRect(x, y, Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
      ctx.strokeRect(x, y, Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
      ctx.restore();
    }

    if (drag?.kind === "modules") {
      ctx.save();
      ctx.strokeStyle = token("role-selection");
      ctx.fillStyle = alpha("role-selection", .18);
      ctx.lineWidth = 1.5;
      ctx.setLineDash([6, 4]);
      for (const module of modules.filter((m) => drag.ids.includes(m.id))) {
        path(translatePoly(module.polygon, drag.delta)); ctx.fill(); ctx.stroke();
      }
      ctx.restore();
    }
    // Move and rotate tools: the selection where the second pick would put it.
    const snapped = cursor && tool !== "select" && !ELECTRICAL_TOOL_SET.has(tool) ? toolSnapResult(cursor) : null; // electrical tools pick modules, not points
    if (pick && editable && (pick.kind === "move" || pick.kind === "rotate")) {
      const anchorPt = pick.kind === "move" ? pick.base : pick.pivot;
      const a = toScreen(anchorPt);
      ctx.strokeStyle = token("role-info-on-stage");
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(a[0], a[1], 5, 0, Math.PI * 2);
      ctx.stroke();
      const pv = snapped ? pickPreview(editable, snapped.p) : null;
      if (pv && snapped) {
        path(pv.entity.polygon, pv.entity.holes);
        ctx.setLineDash([5, 4]);
        ctx.strokeStyle = token("role-selection");
        ctx.stroke();
        ctx.setLineDash([]);
        const b = toScreen(snapped.p);
        ctx.beginPath();
        ctx.moveTo(a[0], a[1]);
        ctx.lineTo(b[0], b[1]);
        ctx.strokeStyle = token("role-info-on-stage");
        ctx.stroke();
        ctx.font = drawingFont(12);
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        const w = ctx.measureText(pv.label).width + 10;
        ctx.fillStyle = token("role-stage-deep");
        ctx.fillRect(b[0] + 12, b[1] + 10, w, 20);
        ctx.fillStyle = token("role-stage-text");
        ctx.fillText(pv.label, b[0] + 17, b[1] + 20);
      }
    }

    // Drawing preview
    if (draft.length && cursor) {
      const snapNext = snapPoint(cursor, draft[draft.length - 1], draft[draft.length - 2]).p;
      const pts = [...draft, snapNext];
      ctx.beginPath();
      pts.forEach((p, i) => {
        const s = toScreen(p);
        if (i === 0) ctx.moveTo(s[0], s[1]);
        else ctx.lineTo(s[0], s[1]);
      });
      ctx.strokeStyle = token("role-selection");
      ctx.lineWidth = 1.6;
      ctx.setLineDash([5, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
      for (const p of draft) {
        const s = toScreen(p);
        ctx.fillStyle = token("role-stage-deep");
        ctx.strokeStyle = token("role-selection");
        ctx.fillRect(s[0] - 4, s[1] - 4, 8, 8);
        ctx.strokeRect(s[0] - 4, s[1] - 4, 8, 8);
      }
      const a = draft[draft.length - 1];
      const s = toScreen(snapNext);
      const label = `${dist(a, snapNext).toFixed(2)} m · ${bearingDeg(a, snapNext).toFixed(1)}°`;
      ctx.font = drawingFont(12);
      const w = ctx.measureText(label).width + 10;
      ctx.fillStyle = token("role-stage-deep");
      ctx.fillRect(s[0] + 12, s[1] + 10, w, 20);
      ctx.fillStyle = token("role-stage-text");
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(label, s[0] + 17, s[1] + 20);
      if (draft.length >= 3 && dist(toScreen(draft[0]), toScreen(cursor)) < 10) {
        const f = toScreen(draft[0]);
        ctx.strokeStyle = token("role-info-on-stage");
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(f[0], f[1], 8, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    // Engine rectangle preview (drag, or the two-click form)
    const rect = drag?.kind === "rect" ? drag : pick?.kind === "rect" && snapped ? { start: pick.start, current: snapped.p } : null;
    if (rect) {
      const a = toScreen(rect.start);
      const b = toScreen(rect.current);
      ctx.strokeStyle = token("role-info-on-stage");
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 4]);
      ctx.strokeRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
      ctx.setLineDash([]);
      const w = Math.abs(rect.current[0] - rect.start[0]);
      const h = Math.abs(rect.current[1] - rect.start[1]);
      ctx.fillStyle = token("role-info-on-stage");
      ctx.font = drawingFont(12);
      ctx.textAlign = "left";
      ctx.textBaseline = "alphabetic";
      ctx.fillText(`${w.toFixed(2)} × ${h.toFixed(2)} m`, Math.max(a[0], b[0]) + 8, Math.max(a[1], b[1]) + 14);
    }
    // Measure
    if (tool === "measure" && measure.length) {
      const pts = measure.length === 1 && cursor ? [measure[0], snapPoint(cursor).p] : measure;
      const a = toScreen(pts[0]);
      const b = toScreen(pts[1] ?? pts[0]);
      ctx.strokeStyle = token("role-info-on-stage");
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
      ctx.stroke();
      if (pts[1]) {
        const label = `${dist(pts[0], pts[1]).toFixed(3)} m · ${bearingDeg(pts[0], pts[1]).toFixed(1)}° from N`;
        ctx.font = drawingFont(12);
        const w = ctx.measureText(label).width + 10;
        ctx.fillStyle = token("role-stage-deep");
        ctx.fillRect((a[0] + b[0]) / 2 - w / 2, (a[1] + b[1]) / 2 - 22, w, 20);
        ctx.fillStyle = token("role-info-on-stage");
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(label, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 12);
      }
    }
    // Snap marker: a glyph and the snap kind, at the snapped point.
    const marker = drag && (drag.kind === "vertex" || drag.kind === "edge" || drag.kind === "move") && cursor ? snapPoint(cursor, undefined, undefined, drag.id) : snapped;
    if (marker?.kind && typed === null) {
      const m = toScreen(marker.p);
      drawSnapGlyph(ctx, marker.kind, m);
      ctx.font = drawingFont(11);
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillStyle = token("role-info-on-stage");
      ctx.fillText(marker.kind === "angle15" ? t("snap.angle15Label") : t(`snap.${marker.kind}`), m[0] + 10, m[1] - 10);
    }
    // Typed point: a cross where Enter will place it.
    if (typed !== null) {
      const r = interpretTyped(typed);
      if (r.point) {
        const m = toScreen(r.point);
        ctx.strokeStyle = token("role-selection");
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(m[0] - 7, m[1] - 7);
        ctx.lineTo(m[0] + 7, m[1] + 7);
        ctx.moveTo(m[0] + 7, m[1] - 7);
        ctx.lineTo(m[0] - 7, m[1] + 7);
        ctx.stroke();
        const last = typedAnchor();
        if (last) {
          const a = toScreen(last);
          ctx.setLineDash([3, 3]);
          ctx.beginPath();
          ctx.moveTo(a[0], a[1]);
          ctx.lineTo(m[0], m[1]);
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size, dpr, view, entities, overlayStrings, elec.path, elec.lasso, elec.picked, elec.highlighted, elec.centres, selection, selected, drag, draft, cursor, tool, measure, electrical, state.hover, snapPoint, toScreen, pick, typed, shift, alt, dimEdit, layoutStep, tables, layoutPreview, t, vertexSel, refPick, hoverEdge, overlayEditable, overlayInfo, overlayT, calib]);

  // ---- helpers ------------------------------------------------------------
  function rotateHandle(poly: Vec2[]) {
    const b = bounds([poly]);
    const anchor: Vec2 = [(b.minX + b.maxX) / 2, b.maxY];
    return { anchor, handle: anchor };
  }

  /** The engine rotates about the bounding-box centre when no origin is given. */
  function boxCentre(poly: Vec2[]): Vec2 {
    const b = bounds([poly]);
    return [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2];
  }

  function previewEntity(e: Entity, d: Drag | null): Entity {
    if (!d || !("id" in d) || d.id !== e.id) return e;
    if (d.kind === "move") return { ...e, polygon: translatePoly(d.original, d.delta), holes: d.originalHoles.map((h) => translatePoly(h, d.delta)) };
    if (d.kind === "vertex") {
      if (d.ring === 0) {
        const poly = d.original.slice();
        poly[d.index] = d.current;
        return { ...e, polygon: poly };
      }
      const holes = e.holes.map((h, i) => (i === d.ring - 1 ? h.map((p, j) => (j === d.index ? d.current : p)) : h));
      return { ...e, holes };
    }
    if (d.kind === "edge") return d.ring === 0 ? { ...e, polygon: offsetEdge(d.original, d.index, d.offset) } : { ...e, holes: e.holes.map((h, i) => i === d.ring - 1 ? offsetEdge(d.original, d.index, d.offset) : h) };
    if (d.kind === "rotate") return { ...e, polygon: rotateClockwise(d.original, d.pivot, d.angle), holes: d.originalHoles.map((h) => rotateClockwise(h, d.pivot, d.angle)) };
    return e;
  }

  /** Where the second pick of the move or rotate tool would put the selection now. */
  function pickPreview(e: Entity, at: Vec2 | null): { entity: Entity; label: string } | null {
    if (!at || !pick) return null;
    if (pick.kind === "move") {
      const d: Vec2 = [at[0] - pick.base[0], at[1] - pick.base[1]];
      return {
        entity: { ...e, polygon: translatePoly(e.polygon, d), holes: e.holes.map((h) => translatePoly(h, d)) },
        label: `${dist(pick.base, at).toFixed(2)} m · ${bearingDeg(pick.base, at).toFixed(1)}°`
      };
    }
    if (pick.kind === "rotate") {
      const a = rotateAngleAt(at);
      return {
        entity: { ...e, polygon: rotateClockwise(e.polygon, pick.pivot, a), holes: e.holes.map((h) => rotateClockwise(h, pick.pivot, a)) },
        label: t("tools.rotateLabel", { a: a.toFixed(1) })
      };
    }
    return null;
  }

  /** Rotate tool: the bearing from the pivot, 0° north, clockwise; Shift steps 15°. */
  function rotateAngleAt(at: Vec2): number {
    if (!pick || pick.kind !== "rotate" || dist(at, pick.pivot) < 1e-9) return 0;
    const a = bearingDeg(pick.pivot, at);
    const r = a > 180 ? a - 360 : a;
    return shift && snap.angle15 ? Math.round(r / 15) * 15 : r;
  }

  function hitEntity(w: Vec2): Entity | null {
    const order: Entity["kind"][] = ["obstacle", "keepout", "surface"];
    for (const k of order) {
      const list = entities.filter((e) => e.kind === k && !e.hidden).reverse();
      for (const e of list) if (pointInShape(w, e.polygon, e.holes)) return e;
    }
    return null;
  }

  function hitModule(w: Vec2): string | null {
    const t0 = performance.now();
    const id = index.pick(w);
    perf.recordPick(performance.now() - t0);
    return id;
  }

  /** Screen centre and outward direction of each edge-length label of the selection. */
  function dimensionLabels(e: Entity): Array<{ edge: number; at: Vec2; len: number }> {
    const out: Array<{ edge: number; at: Vec2; len: number }> = [];
    const n = e.polygon.length;
    for (let i = 0; i < n; i++) {
      const a = e.polygon[i];
      const b = e.polygon[(i + 1) % n];
      const sa = toScreen(a);
      const sb = toScreen(b);
      if (Math.hypot(sb[0] - sa[0], sb[1] - sa[1]) < 48) continue;
      const nrm = edgeNormal(e.polygon, i);
      // World normal to screen (Y flips). Labels sit outside the edge, clear of the edge handle:
      // further out along X, where the label is wide, than along Y.
      const off = 12 + Math.abs(nrm[0]) * 30 + Math.abs(nrm[1]) * 4;
      out.push({ edge: i, at: [(sa[0] + sb[0]) / 2 + nrm[0] * off, (sa[1] + sb[1]) / 2 - nrm[1] * off], len: dist(a, b) });
    }
    return out;
  }

  async function finishPolygon(points: Vec2[]) {
    const issues = validatePolygon(points);
    if (issues.length) {
      toast("error", `Polygon rejected: ${issues[0].message}`);
      return;
    }
    if (tool === "hole") {
      if (!selected || selected.kind !== "surface") {
        toast("error", "Select a surface before drawing a hole.");
        return;
      }
      if (!points.every((p) => pointInPolygon(p, selected.polygon))) {
        toast("error", "A hole must lie inside its surface.");
        return;
      }
      await addHole(selected, points);
      dispatch({ type: "setTool", tool: "select" });
      return;
    }
    const kind = tool === "obstacle" ? "obstacle" : tool === "keepout" ? "keepout" : "surface";
    const count = entities.filter((e) => e.kind === kind).length + 1;
    const keepoutType = state.toolOptions.keepoutType ?? SCENE_TOOL_OPTIONS.keepoutType;
    const name = kind === "surface" ? `Surface ${count}` : kind === "obstacle" ? `Obstacle ${count}` : t(keepoutType === "walkway" ? "s11a.walkwayName" : "s11a.zoneName", { count });
    const pid = pview!.bundle.project.project_id;
    const selectDrawn = rememberDrawSelection();
    if (kind === "surface") {
      const v = await engineCommand("Creating surface", () => engine.sceneCommand(pid, {
        command_type: "draw_polygon", target_entity_ids: [], parameters: { name, surface_type: "flat_roof", vertices: points, base_elevation_m: state.toolOptions.surfaceBaseM }
      }));
      if (v) selectDrawn(v.bundle.scene.surfaces.at(-1)!.surface_id);
      return;
    }
    if (kind === "obstacle") {
      const input = { name, vertices: points, base_elevation_m: state.toolOptions.obstacleBaseM, height_m: state.toolOptions.obstacleHeightM };
      const v = await sceneEdit("Creating obstacle", (options) => engine.addPolygonObstacle(pid, input, options));
      if (v) selectDrawn(v.bundle.scene.obstacles.at(-1)!.obstacle_id);
      return;
    }
    const v = await sceneEdit("Creating keep-out", (options) => engine.sceneCommand(pid, {
      command_type: "draw_polygon", target_entity_ids: [],
      parameters: { name, surface_type: keepoutType, vertices: points, base_elevation_m: 0, usable_for_pv: false }
    }, options));
    if (v) selectDrawn(v.bundle.scene.surfaces.at(-1)!.surface_id);
  }

  function commitRotate(e: Entity, pivot: Vec2, cwDeg: number) {
    if (Math.abs(cwDeg) < 1e-9) return;
    void rotate(e, pivot, cwDeg);
  }

  /** Rectangle roof (B) or box obstacle (O): created directly in the engine. */
  async function createRect(a: Vec2, b: Vec2) {
    const w = Math.abs(b[0] - a[0]);
    const h = Math.abs(b[1] - a[1]);
    if (w < 0.2 || h < 0.2) {
      toast("error", "A rectangle needs both sides of at least 0.20 m.");
      return;
    }
    const pid = pview!.bundle.project.project_id;
    const o = state.toolOptions;
    const origin = { origin_x_m: Math.min(a[0], b[0]), origin_y_m: Math.min(a[1], b[1]) };
    const v =
      tool === "box_obstacle"
        ? await sceneEdit("Creating obstacle", (options) =>
            engine.addObstacle(pid, {
              name: `Obstacle ${(pview?.bundle.scene.obstacles.length ?? 0) + 1}`,
              ...origin,
              width_m: w,
              depth_m: h,
              base_elevation_m: o.obstacleBaseM,
              height_m: o.obstacleHeightM
            }, options)
          )
        : await engineCommand("Creating surface", () =>
            engine.addSurface(pid, {
              name: `Roof ${String.fromCharCode(65 + (pview?.bundle.scene.surfaces.length ?? 0))}`,
              ...origin,
              width_m: w,
              height_m: h,
              base_elevation_m: o.surfaceBaseM,
              surface_type: "flat_roof",
              usable_for_pv: true
            })
          );
    if (v) {
      toast("ok", tool === "box_obstacle" ? t("tools.obstacleCreated") : t("tools.surfaceCreated"));
    }
  }

  /** The point typed input is relative to, for the active tool. */
  function typedAnchor(): Vec2 | null {
    if (DRAW_TOOLS.has(tool)) return draft[draft.length - 1] ?? null;
    if (pick?.kind === "rect") return pick.start;
    if (pick?.kind === "move") return pick.base;
    if (pick?.kind === "rotate") return pick.pivot;
    if (tool === "measure") return measure.length === 1 ? measure[0] : null;
    return null;
  }

  /** One point placed, by a click (already snapped) or by typed input. */
  async function placePoint(p: Vec2) {
    if (DRAW_TOOLS.has(tool)) {
      if (draft.length >= 3 && dist(toScreen(draft[0]), toScreen(p)) < SNAP_PX) {
        finishPolygon(draft);
        setDraft([]);
      } else setDraft([...draft, p]);
      return;
    }
    if (RECT_TOOLS.has(tool)) {
      if (pick?.kind === "rect") {
        setPick(null);
        await createRect(pick.start, p);
      } else setPick({ kind: "rect", start: p });
      return;
    }
    if (tool === "measure") {
      setMeasure(measure.length === 1 ? [measure[0], p] : [p]);
      return;
    }
    if (tool === "move" || tool === "rotate") {
      if (!editable) {
        toast("info", selected ? t("tools.locked", { name: selected.name }) : t("tools.selectFirst"));
        return;
      }
      if (tool === "move") {
        if (pick?.kind !== "move") return setPick({ kind: "move", base: p });
        setPick(null);
        dispatch({ type: "setTool", tool: "select" });
        await commitMove(editable, [p[0] - pick.base[0], p[1] - pick.base[1]]);
        return;
      }
      if (pick?.kind !== "rotate") return setPick({ kind: "rotate", pivot: p });
      const a = rotateAngleAt(p);
      setPick(null);
      dispatch({ type: "setTool", tool: "select" });
      commitRotate(editable, pick.pivot, a);
    }
  }

  /** Typed input: a point for most tools, an angle for the second step of rotate. */
  function interpretTyped(text: string): { point?: Vec2; angle?: number; error?: string } {
    try {
      if (tool === "rotate" && pick?.kind === "rotate") return { angle: parseAngle(text) };
      const anchor = typedAnchor();
      return { point: resolvePoint(parsePoint(text, anchor !== null), anchor, cursor) };
    } catch (err) {
      if (err instanceof TypedError || err instanceof RangeError) return { error: err.message };
      throw err;
    }
  }

  async function applyTyped(text: string) {
    const r = interpretTyped(text);
    if (r.error) {
      setTypedError(r.error);
      return;
    }
    setTyped(null);
    setTypedError(null);
    if (r.angle !== undefined && pick?.kind === "rotate" && editable) {
      setPick(null);
      dispatch({ type: "setTool", tool: "select" });
      commitRotate(editable, pick.pivot, r.angle);
      return;
    }
    if (r.point) await placePoint(r.point);
  }

  function applyDimension() {
    if (!dimEdit) return;
    const e = entities.find((x) => x.id === dimEdit.id);
    if (!e) return;
    try {
      const length = evalExpr(dimEdit.value);
      setEdgeLength(e.polygon, dimEdit.edge, length, isRectangle(e.polygon) ? "rectangle" : "start");
      if (e.source === "engine" && e.modified) throw new Error("Discard the local draft edits first");
      void editDimension(e, dimEdit.edge, length);
      setDimEdit(null);
    } catch (err) {
      setDimEdit({ ...dimEdit, error: err instanceof Error ? err.message : String(err) });
    }
  }

  /** Z: zoom to the selection; pressed twice within 0.4 s, zoom to everything. */
  function zoomKey() {
    const now = performance.now();
    const twice = now - lastZ.current < 400;
    lastZ.current = now;
    const sel = entities.filter((e) => selection.includes(e.id)).map((e) => e.polygon);
    const mods = selection.length ? modules.filter((m) => selectedSet.has(m.id)).map((m) => m.polygon) : [];
    if (twice || (!sel.length && !mods.length)) return fit();
    setView(fitView(bounds([...sel, ...mods]), size, 120));
    userMovedRef.current = true;
  }

  // ---- context menu (UX2) --------------------------------------------------
  /** A vertex handle of the selected editable object under a screen point, as in onPointerDown. */
  function vertexAt(sp: Vec2): { ring: number; index: number } | null {
    if (!editable) return null;
    const rings = [editable.polygon, ...editable.holes];
    for (let r = 0; r < rings.length; r++)
      for (let i = 0; i < rings[r].length; i++) if (dist(toScreen(rings[r][i]), sp) < 8) return { ring: r, index: i };
    return null;
  }
  /** An edge of the selected editable object near a world point, with the double-click tolerance. */
  function edgeAt(w: Vec2): { ring: number; index: number } | null {
    if (!editable) return null;
    const rings = [editable.polygon, ...editable.holes];
    for (let r = 0; r < rings.length; r++)
      for (let i = 0; i < rings[r].length; i++)
        if (distToSegment(w, rings[r][i], rings[r][(i + 1) % rings[r].length]) * view.scale < 7) return { ring: r, index: i };
    return null;
  }

  /** What a right-click at a point targets; selects an unselected object or module first. */
  function menuTargetAt(sp: Vec2, w: Vec2): { target: MenuTarget; ids: string[] } {
    if (DRAW_TOOLS.has(tool) && draft.length) return { target: { kind: "drawing", points: draft.length }, ids: selection };
    const v = vertexAt(sp);
    if (v && editable) {
      setVertexSel({ id: editable.id, ...v });
      return { target: { kind: "vertex", entityId: editable.id, ...v }, ids: selection };
    }
    const e = edgeAt(w);
    if (e && editable) return { target: { kind: "edge", entityId: editable.id, ...e, at: w }, ids: selection };
    const hit = hitEntity(w);
    const mod = !hit || hit.kind === "surface" ? hitModule(w) : null;
    const id = mod ?? hit?.id;
    if (!id) return { target: { kind: "empty" }, ids: selection };
    if (selection.includes(id)) return { target: { kind: "selection" }, ids: selection };
    dispatch({ type: "select", ids: [id] });
    return { target: { kind: "selection" }, ids: [id] };
  }

  function openMenu(at: Vec2, target: MenuTarget, ids: string[]) {
    setMenu({ at, target, selectionKey: ids.join("|"), returnFocus: document.activeElement });
  }

  /** Shift+F10 or the Menu key: the selection's menu at its centre, or the canvas menu at the view centre. */
  function openKeyboardMenu() {
    if (DRAW_TOOLS.has(tool) && draft.length) return openMenu(toScreen(draft[draft.length - 1]), { kind: "drawing", points: draft.length }, selection);
    if (vertexSel && editable && vertexSel.id === editable.id) {
      const ring = vertexSel.ring === 0 ? editable.polygon : editable.holes[vertexSel.ring - 1];
      if (ring?.[vertexSel.index]) return openMenu(toScreen(ring[vertexSel.index]), { kind: "vertex", entityId: editable.id, ring: vertexSel.ring, index: vertexSel.index }, selection);
    }
    const polys = [...entities.filter((e) => selection.includes(e.id)).map((e) => e.polygon), ...modules.filter((m) => selectedSet.has(m.id)).map((m) => m.polygon)];
    if (polys.length) {
      const b = bounds(polys);
      return openMenu(toScreen([(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2]), { kind: "selection" }, selection);
    }
    openMenu([size.w / 2, size.h / 2], { kind: "empty" }, selection);
  }

  function closeMenu(restoreFocus: boolean) {
    const back = menu?.returnFocus;
    setMenu(null);
    if (restoreFocus && back instanceof HTMLElement && back.isConnected) back.focus();
  }

  // Only while the menu is open: one pass over the modules with the selection set (plans can hold 100k modules).
  const menuSelected = menu ? entities.filter((e) => selectedSet.has(e.id)) : [];
  const menuModules = menu ? modules.filter((m) => selectedSet.has(m.id)).map((m) => m.id) : [];
  const menuTables = menu && layoutStep ? tablesOfModules(menuModules, tables).filter((x) => x.status === "active") : [];
  const historyLabel = (entry: typeof state.undoTop) => (entry?.kind === "engine" ? entry.label : entry ? t("ux2.localEdit") : undefined);
  const menuItems = menu ? buildMenu({
    target: menu.target,
    selected: menuSelected,
    selectedModules: menuModules.length,
    activeTables: menuTables.length,
    step,
    busy: !!state.busy,
    canUndo: !!state.undoTop,
    canRedo: !!state.redoTop,
    undoLabel: historyLabel(state.undoTop),
    redoLabel: historyLabel(state.redoTop),
    tools: toolsForStep(step),
    anyVisible: entities.some((e) => !e.hidden),
    meshIds: new Set((pview?.bundle.scene.obstacles ?? []).filter((o) => o.obstacle_type === "imported_mesh").map((o) => o.obstacle_id)),
    overlay: overlayInfo ? (overlayInfo.locked ? "locked" : "unlocked") : null,
    pasteProblem: pasteProblem(readClipboard(), pview?.bundle.project.project_id, entities),
    unstrungAssign: step === "electrical" && pview ? unstrungTargets(pview, menuModules) : undefined
  }, t) : [];

  // UX3: copy the selected object, and paste it (a roof with its PV) at a point or beside the original.
  function copySelected(e: Entity) {
    const projectId = pview?.bundle.project.project_id;
    if (!projectId) return;
    copyToClipboard(projectId, e);
    toast("ok", t("ux3.copied", { name: e.name }));
  }
  function pasteAt(target: Vec2 | null) {
    const clip = readClipboard();
    const problem = pasteProblem(clip, pview?.bundle.project.project_id, entities);
    if (problem || !clip) return toast("info", t(problem ?? "ux3.clipboardEmpty"));
    const source = entities.find((e) => e.id === clip.entityId)!;
    void duplicate(source, { offset: pasteOffset(clip, target), withPv: true });
  }

  function setReferenceEdge(e: Entity, edgeIndex: number) {
    void editPlane(e, referenceEdgePlane(e.plane, edgeIndex));
  }

  function zoomToSelection() {
    const sel = entities.filter((e) => selection.includes(e.id)).map((e) => e.polygon);
    const mods = modules.filter((m) => selectedSet.has(m.id)).map((m) => m.polygon);
    if (!sel.length && !mods.length) return fit();
    setView(fitView(bounds([...sel, ...mods]), size, 120));
    userMovedRef.current = true;
  }

  /** Every menu action runs the existing path for that action; nothing here re-implements an edit. */
  function runMenu(id: MenuAction) {
    const target = menu?.target;
    const menuAt = menu?.at ?? null;
    setMenu(null);
    const one = menuSelected.length === 1 ? menuSelected[0] : null;
    const entity = target && (target.kind === "vertex" || target.kind === "edge") ? entities.find((e) => e.id === target.entityId) : one;
    if (id.startsWith("tool:")) return dispatch({ type: "setTool", tool: id.slice(5) as Tool });
    if ((id.startsWith("addToString:") || id.startsWith("newString:")) && pview) {
      const ids = unstrungOf(pview, menuModules);
      const pid = pview.bundle.project.project_id;
      const command: TopologyCommand = id.startsWith("addToString:")
        ? { command_type: "append_to_string", parameters: { string_id: id.slice("addToString:".length), module_instance_ids: ids } }
        : { command_type: "create_string", parameters: { module_instance_ids: ids, mppt_instance_id: id.slice("newString:".length) } };
      return void engineCommand(t("use3b.assigning"), () => engine.topologyCommand(pid, command, pview));
    }
    switch (id) {
      case "undo": return void undo();
      case "redo": return void redo();
      case "finishPolygon": finishPolygon(draft); setDraft([]); return;
      case "removePoint": setDraft(draft.slice(0, -1)); return;
      case "cancelDrawing": setDraft([]); dispatch({ type: "setTool", tool: "select" }); return;
      case "deleteVertex":
        if (entity && target?.kind === "vertex") { setVertexSel(null); void deleteVertex(entity, target.index, target.ring); }
        return;
      case "insertVertex":
        if (entity && target?.kind === "edge") void insertVertex(entity, target.index, target.at, target.ring);
        return;
      case "edgeLength":
        if (entity && target?.kind === "edge") {
          const label = dimensionLabels(entity).find((l) => l.edge === target.index);
          const a = entity.polygon[target.index], b = entity.polygon[(target.index + 1) % entity.polygon.length];
          setDimEdit({ id: entity.id, edge: target.index, value: Math.hypot(b[0] - a[0], b[1] - a[1]).toFixed(2), at: label?.at ?? toScreen([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]) });
        }
        return;
      case "referenceEdge":
        if (entity && target?.kind === "edge") setReferenceEdge(entity, target.index);
        return;
      case "properties": window.dispatchEvent(new CustomEvent("rawibumi:show-inspector")); return;
      case "zoomSelection": return zoomToSelection();
      case "zoomAll": return fit();
      case "duplicate": if (entity) void duplicate(entity); return;
      case "move": return dispatch({ type: "setTool", tool: "move" });
      case "rotate": return dispatch({ type: "setTool", tool: "rotate" });
      case "addHole": return dispatch({ type: "setTool", tool: "hole" });
      case "lock": case "unlock":
        for (const e of menuSelected) dispatch({ type: "updateEntity", id: e.id, patch: { locked: id === "lock" }, history: false });
        return;
      case "hide":
        for (const e of menuSelected) dispatch({ type: "updateEntity", id: e.id, patch: { hidden: true }, history: false });
        return;
      case "delete": {
        const targets = menuSelected.filter((e) => !e.locked);
        if (targets.length) window.dispatchEvent(new CustomEvent("rawibumi:delete-request", { detail: targets.map((e) => e.id) }));
        return;
      }
      case "deleteModules":
        if (menuTables.length) void tableEdits.deleteModules(menuModules.filter((m) => slotOf(m)));
        else void moduleEdits.previewDelete(menuModules);
        return;
      case "deleteTables": void tableEdits.deleteTables(menuTables.map((x) => x.table_id)); return;
      case "selectAll": return dispatch({ type: "select", ids: entities.filter((e) => !e.hidden).map((e) => e.id) });
      case "clearSelection": return dispatch({ type: "select", ids: [] });
      case "overlayLock": case "overlayUnlock":
        if (overlayInfo) void saveImagery({ ...imagery, overlay: { ...overlayInfo, locked: id === "overlayLock" } });
        return;
      case "overlayCalibrate": window.dispatchEvent(new Event("rawibumi:overlay-calibrate")); return;
      case "copy": if (one) copySelected(one); return;
      case "paste": return pasteAt(menuAt ? toWorld(menuAt) : null);
    }
  }

  function onContextMenu(ev: React.MouseEvent) {
    ev.preventDefault();
    // A right-drag pans; only a right-click without movement opens the menu.
    if (rightPress.current?.moved) { rightPress.current = null; return; }
    const sp = localPoint(ev);
    const { target, ids } = menuTargetAt(sp, toWorld(sp));
    openMenu(sp, target, ids);
  }

  // ---- pointer handlers ---------------------------------------------------
  function localPoint(ev: React.PointerEvent | React.MouseEvent | React.WheelEvent): Vec2 {
    const r = overlayRef.current!.getBoundingClientRect();
    return [ev.clientX - r.left, ev.clientY - r.top];
  }

  /** Snap for the active tool: from the last placed points; the moved entity never snaps to itself. */
  function toolSnapResult(w: Vec2) {
    if (DRAW_TOOLS.has(tool)) return snapPoint(w, draft[draft.length - 1], draft[draft.length - 2]);
    if (tool === "move" && pick?.kind === "move") return snapPoint(w, pick.base, undefined, editable?.id);
    if (tool === "rotate" && pick?.kind === "rotate") return snapPoint(w, pick.pivot);
    if (pick?.kind === "rect") return snapPoint(w, pick.start);
    if (tool === "measure" && measure.length === 1) return snapPoint(w, measure[0]);
    return snapPoint(w);
  }
  const toolSnap = (w: Vec2): Vec2 => toolSnapResult(w).p;

  function onPointerDown(ev: React.PointerEvent) {
    const sp = localPoint(ev);
    const w = toWorld(sp);
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
    setDimEdit(null);
    rightPress.current = ev.button === 2 ? { start: sp, moved: false } : null;
    if (ev.button === 1 || ev.button === 2 || (ev.button === 0 && space.current)) {
      setDrag({ kind: "pan", start: sp, startView: view });
      return;
    }
    // UX1 two-point calibration: the next two clicks are the known points.
    if (calib && ev.button === 0) {
      if (calib.points.length < 2) setCalib({ ...calib, points: [...calib.points, snapPoint(w).p] });
      return;
    }
    // UX1: an unlocked overlay takes priority with the select tool (rotation handle, corners, then the image).
    if (overlayEditable && overlayInfo && overlayT && ev.button === 0 && !space.current) {
      const corners = overlayCorners(overlayT, overlayInfo.width, overlayInfo.height);
      const screen = corners.map(toScreen);
      if (dist(overlayRotateKnob(screen).at, sp) < 9) {
        const pivot: Vec2 = [(corners[0][0] + corners[2][0]) / 2, (corners[0][1] + corners[2][1]) / 2];
        setDrag({ kind: "overlay-rotate", pivot, startBearing: bearingDeg(pivot, w), original: overlayT, current: overlayT });
        return;
      }
      const corner = screen.findIndex((c) => dist(c, sp) < 8);
      if (corner >= 0) { setDrag({ kind: "overlay-scale", corner, original: overlayT, current: overlayT }); return; }
      if (pointInPolygon(w, corners)) { setDrag({ kind: "overlay-move", startWorld: w, original: overlayT, current: overlayT }); return; }
    }
    // Reference-edge pick mode (UX2): the next click on an outer edge of the roof sets it.
    if (refPick && editable && editable.id === refPick && tool === "select") {
      const e = edgeAt(w);
      if (e && e.ring === 0) {
        setRefPick(null);
        setReferenceEdge(editable, e.index);
        return;
      }
    }
    if (typed !== null) {
      setTyped(null);
      setTypedError(null);
    }
    // Electrical tools (B6): a press they do not use pans.
    if (ELECTRICAL_TOOL_SET.has(tool)) {
      if (!elec.down(w, hitModule(w), ev.shiftKey)) setDrag({ kind: "pan", start: sp, startView: view });
      return;
    }
    if (RECT_TOOLS.has(tool) && pick?.kind !== "rect") {
      const p = toolSnap(w);
      setDrag({ kind: "rect", start: p, current: p });
      return;
    }
    if (tool !== "select") {
      void placePoint(toolSnap(w));
      return;
    }
    // select tool: handles of the selection first
    if (editable) {
      const rings = [editable.polygon, ...editable.holes];
      for (let r = 0; r < rings.length; r++)
        for (let i = 0; i < rings[r].length; i++) {
          if (dist(toScreen(rings[r][i]), sp) < 8) {
            if (ev.altKey) {
              if (rings[r].length <= 3) return toast("error", "A polygon needs at least 3 vertices.");
              void deleteVertex(editable, i, r);
              return;
            }
            setDrag({ kind: "vertex", id: editable.id, ring: r, index: i, original: rings[r].slice(), current: rings[r][i] });
            return;
          }
        }
      for (let ring = 0; ring <= editable.holes.length; ring++) {
      const points = ring === 0 ? editable.polygon : editable.holes[ring - 1];
      const n = points.length;
      for (let i = 0; i < n; i++) {
        const a = toScreen(points[i]);
        const b = toScreen(points[(i + 1) % n]);
        if (Math.hypot(b[0] - a[0], b[1] - a[1]) < 24) continue;
        if (Math.hypot((a[0] + b[0]) / 2 - sp[0], (a[1] + b[1]) / 2 - sp[1]) < 7) {
          setDrag({ kind: "edge", id: editable.id, ring, index: i, original: points.slice(), normal: edgeNormal(points, i), startWorld: w, offset: 0 });
          return;
        }
      }
      }
      // A press on a dimension label keeps the selection (a double-click there edits the length).
      if (dimensionLabels(editable).some((l) => Math.abs(l.at[0] - sp[0]) < 32 && Math.abs(l.at[1] - sp[1]) < 10)) return;
      const rh = rotateHandle(editable.polygon);
      const hs = toScreen(rh.handle);
      if (Math.hypot(hs[0] - sp[0], hs[1] + 22 - sp[1]) < 9) {
        const pivot = boxCentre(editable.polygon);
        setDrag({ kind: "rotate", id: editable.id, pivot, startBearing: bearingDeg(pivot, w), original: editable.polygon, originalHoles: editable.holes, angle: 0 });
        return;
      }
    }
    const hit = hitEntity(w);
    const mod = !hit || hit.kind === "surface" ? hitModule(w) : null;
    if (mod) {
      const inTable = layoutStep && slotOf(mod) && tables.some((x) => x.table_id === slotOf(mod)!.tableId && x.status === "active");
      const activeTable = tablesOfModules([mod], tables).some((x) => x.status === "active");
      const moduleOnly = selection.length > 0 && selection.every((id) => modules.some((m) => m.id === id));
      const ids = selection.includes(mod) && (inTable || (!activeTable && moduleOnly && (step === "scene" || layoutStep))) ? selection : [mod];
      dispatch(ev.shiftKey ? { type: "selectToggle", id: mod } : { type: "select", ids });
      // In the PV layout step a module drags its table (all selected tables when it is selected).
      if (inTable && !ev.shiftKey) setDrag({ kind: "tables", ids: tablesOfModules(ids, tables).map((x) => x.table_id), startWorld: w, delta: [0, 0] });
      if (!activeTable && !ev.shiftKey && !state.busy && (step === "scene" || layoutStep)) setDrag({ kind: "modules", ids, startWorld: w, delta: [0, 0] });
      return;
    }
    if (hit) {
      if (layoutStep && hit.kind === "surface") {
        setDrag({ kind: "box", start: w, current: w, add: ev.shiftKey, hitId: hit.id });
        return;
      }
      if (ev.shiftKey) {
        dispatch({ type: "selectToggle", id: hit.id });
        return;
      }
      dispatch({ type: "select", ids: [hit.id] });
      if (!hit.locked) setDrag({ kind: "move", id: hit.id, startWorld: w, original: hit.polygon, originalHoles: hit.holes, delta: [0, 0] });
      return;
    }
    setDrag({ kind: "box", start: w, current: w, add: ev.shiftKey, hitId: null });
  }

  function onPointerMove(ev: React.PointerEvent) {
    const sp = localPoint(ev);
    const w = toWorld(sp);
    setCursor(w);
    if (ev.altKey !== alt) setAlt(ev.altKey);
    if (ev.shiftKey !== shift) setShift(ev.shiftKey);
    if (!drag) {
      if (ELECTRICAL_TOOL_SET.has(tool)) elec.move(w, hitModule(w), view.scale);
      else if (tool === "select") {
        const h = hitEntity(w);
        dispatch({ type: "hover", id: h?.id ?? null });
        const edge = editable?.kind === "surface" ? edgeAt(w) : null;
        const next = edge && edge.ring === 0 ? { id: editable!.id, index: edge.index } : null;
        if (next?.id !== hoverEdge?.id || next?.index !== hoverEdge?.index) setHoverEdge(next);
      }
      return;
    }
    if (drag.kind === "box") {
      setDrag({ ...drag, current: w });
    } else if (drag.kind === "pan") {
      if (rightPress.current && !rightPress.current.moved && dist(rightPress.current.start, sp) > 4) {
        rightPress.current.moved = true;
        setMenu(null);
      }
      moveView({ ...drag.startView, cx: drag.startView.cx - (sp[0] - drag.start[0]) / view.scale, cy: drag.startView.cy + (sp[1] - drag.start[1]) / view.scale });
    } else if (drag.kind === "move") {
      // The grabbed point snaps (to other entities, never to the moved one).
      const p = snapPoint(w, undefined, undefined, drag.id).p;
      setDrag({ ...drag, delta: [p[0] - drag.startWorld[0], p[1] - drag.startWorld[1]] });
    } else if (drag.kind === "vertex") {
      const neighbours = drag.original;
      setDrag({ ...drag, current: snapPoint(w, neighbours[(drag.index - 1 + neighbours.length) % neighbours.length], undefined, drag.id).p });
    } else if (drag.kind === "edge") {
      const p = snapPoint(w, undefined, undefined, drag.id).p;
      const off = (p[0] - drag.startWorld[0]) * drag.normal[0] + (p[1] - drag.startWorld[1]) * drag.normal[1];
      setDrag({ ...drag, offset: shift ? Math.round(off / NUDGE_M) * NUDGE_M : off });
    } else if (drag.kind === "rotate") {
      let a = bearingDeg(drag.pivot, w) - drag.startBearing;
      if (a > 180) a -= 360;
      if (a < -180) a += 360;
      if (ev.shiftKey || snap.angle15) a = Math.round(a / (ev.shiftKey ? 15 : 1)) * (ev.shiftKey ? 15 : 1);
      setDrag({ ...drag, angle: a });
    } else if (drag.kind === "overlay-move") {
      setDrag({ ...drag, current: moveOverlay(drag.original, [w[0] - drag.startWorld[0], w[1] - drag.startWorld[1]]) });
    } else if (drag.kind === "overlay-scale" && overlayInfo) {
      setDrag({ ...drag, current: scaleFromCorner(drag.original, overlayInfo.width, overlayInfo.height, drag.corner, w, ev.shiftKey) });
    } else if (drag.kind === "overlay-rotate") {
      let a = bearingDeg(drag.pivot, w) - drag.startBearing;
      if (a > 180) a -= 360;
      if (a < -180) a += 360;
      if (ev.shiftKey) a = Math.round(a / 15) * 15;
      // Bearings turn clockwise; the overlay's rotation is counter-clockwise.
      setDrag({ ...drag, current: rotateOverlay(drag.original, drag.pivot, -a) });
    } else if (drag.kind === "rect") {
      setDrag({ ...drag, current: snapPoint(w, drag.start).p });
    } else if (drag.kind === "modules") {
      setDrag({ ...drag, delta: moduleDragDelta(drag.startWorld, w, ev.shiftKey) });
    } else if (drag.kind === "tables") {
      const d: Vec2 = [w[0] - drag.startWorld[0], w[1] - drag.startWorld[1]];
      // Shift: whole 0.10 m steps.
      setDrag({ ...drag, delta: ev.shiftKey ? [Math.round(d[0] / NUDGE_M) * NUDGE_M, Math.round(d[1] / NUDGE_M) * NUDGE_M] : d });
    }
  }

  async function onPointerUp(ev: React.PointerEvent) {
    const d = drag;
    setDrag(null);
    if (ELECTRICAL_TOOL_SET.has(tool)) elec.up();
    if (!d) return;
    const e = "id" in d ? entities.find((x) => x.id === d.id) : undefined;
    if (d.kind === "overlay-move" || d.kind === "overlay-scale" || d.kind === "overlay-rotate") {
      // One gesture, one save, one undo step; a click without movement saves nothing.
      if (overlayInfo && JSON.stringify(d.current) !== JSON.stringify(d.original)) await saveImagery({ ...imagery, overlay: { ...overlayInfo, transform: d.current } });
      return;
    }
    if (d.kind === "box") {
      const end = toWorld(localPoint(ev));
      if (dist(toScreen(d.start), toScreen(end)) < 4) {
        if (d.hitId) dispatch(d.add ? { type: "selectToggle", id: d.hitId } : { type: "select", ids: [d.hitId] });
        else dispatch({ type: "select", ids: [] });
      } else {
        const crossing = end[0] < d.start[0];
        const ids = [
          ...entities.filter((e) => !e.hidden && boxSelect(e.polygon, d.start, end, crossing)).map((e) => e.id),
          ...modules.filter((m) => boxSelect(m.polygon, d.start, end, crossing)).map((m) => m.id)
        ];
        dispatch({ type: d.add ? "selectAdd" : "select", ids });
      }
    } else if (d.kind === "move") {
      if (e) await commitMove({ ...e, polygon: d.original, holes: d.originalHoles }, d.delta);
    } else if (d.kind === "vertex" || d.kind === "edge") {
      if (!e || (d.kind === "edge" && Math.abs(d.offset) < 1e-9)) return;
      // A press on a vertex handle without dragging selects that vertex (UX2); no engine command is sent.
      if (d.kind === "vertex") {
        if (dist(toScreen(d.current), toScreen(d.original[d.index])) < 3) return setVertexSel({ id: d.id, ring: d.ring, index: d.index });
        setVertexSel(null);
      }
      const p = previewEntity(e, d);
      if (d.kind === "edge") await moveEdge(d.ring === 0 ? { ...e, polygon: d.original } : { ...e, holes: e.holes.map((h, i) => i === d.ring - 1 ? d.original : h) }, d.index, d.offset, d.ring);
      else await moveVertex(e, d.index, d.ring === 0 ? p.polygon[d.index] : p.holes[d.ring - 1][d.index], d.ring);
    } else if (d.kind === "rotate") {
      if (e) commitRotate({ ...e, polygon: d.original, holes: d.originalHoles }, d.pivot, d.angle);
    } else if (d.kind === "modules") {
      const delta = moduleDragDelta(d.startWorld, toWorld(localPoint(ev)), ev.shiftKey);
      if (Math.hypot(...delta) * view.scale >= 3) await moduleEdits.dragModules(d.ids, delta);
    } else if (d.kind === "tables") {
      if (Math.hypot(d.delta[0], d.delta[1]) * view.scale >= 3) await tableEdits.moveTables(d.ids, d.delta);
    } else if (d.kind === "rect") {
      // A click without a drag starts the two-click form: the next click or typed point is the opposite corner.
      if (dist(toScreen(d.start), toScreen(d.current)) < 4) setPick({ kind: "rect", start: d.start });
      else await createRect(d.start, d.current);
    }
  }

  function onDoubleClick(ev: React.MouseEvent) {
    const sp = localPoint(ev);
    const w = toWorld(sp);
    if (DRAW_TOOLS.has(tool) && draft.length >= 3) {
      finishPolygon(draft.slice(0, -1).length >= 3 ? draft.slice(0, -1) : draft);
      setDraft([]);
      return;
    }
    if (tool === "select" && editable) {
      // A dimension label: type the exact length, preserving rectangles along their own axes.
      const label = dimensionLabels(editable).find((l) => Math.abs(l.at[0] - sp[0]) < 32 && Math.abs(l.at[1] - sp[1]) < 10);
      if (label) {
        setDimEdit({ id: editable.id, edge: label.edge, value: label.len.toFixed(2), at: label.at });
        return;
      }
      for (let ring = 0; ring <= editable.holes.length; ring++) {
        const points = ring === 0 ? editable.polygon : editable.holes[ring - 1];
        for (let i = 0; i < points.length; i++) {
          if (distToSegment(w, points[i], points[(i + 1) % points.length]) * view.scale < 7) {
            void insertVertex(editable, i, w, ring);
            return;
          }
        }
      }
    }
  }

  // Wheel zoom: a native listener, because React's wheel listener is passive and cannot stop page scroll.
  useEffect(() => {
    const el = overlayRef.current;
    if (!el) return;
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const r = el.getBoundingClientRect();
      moveView(zoomAt(view, size, [ev.clientX - r.left, ev.clientY - r.top], Math.exp(-ev.deltaY * 0.0015)));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [view, size, moveView]);

  // ---- keyboard -------------------------------------------------------------
  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      if (ev.defaultPrevented || typingTarget(ev.target) || dialogTarget(ev.target)) return;
      setShift(ev.shiftKey);
      setAlt(ev.altKey);
      // UX3: Ctrl/Cmd+C copies the selected object and Ctrl/Cmd+V pastes it at the pointer (beside the original
      // without one). Selected page text keeps the browser's own copy.
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && !ev.shiftKey && ["c", "v"].includes(ev.key.toLowerCase())) {
        if (ev.key.toLowerCase() === "c") {
          const one = selection.length === 1 ? entities.find((e) => e.id === selection[0]) : undefined;
          if (!one || window.getSelection()?.toString()) return;
          ev.preventDefault();
          copySelected(one);
        } else if (readClipboard()) {
          ev.preventDefault();
          pasteAt(cursor);
        }
        return;
      }
      if (ev.altKey || ev.ctrlKey || ev.metaKey) return; // Alt and Ctrl combinations belong to workspace commands.
      // UX2: the context menu from the keyboard.
      if ((ev.key === "F10" && ev.shiftKey) || ev.key === "ContextMenu") {
        ev.preventDefault();
        openKeyboardMenu();
        return;
      }
      if (ev.code === "Space") {
        ev.preventDefault();
        space.current = true;
        return;
      }

      // Electrical step: MPPT target keys, string path Enter/Backspace, Escape of a gesture.
      if (elec.key(ev)) {
        ev.preventDefault();
        return;
      }

      // Typed input (dynamic input at the cursor) while a tool that takes it is active.
      if (toolDef(tool).typed) {
        if (typed !== null) {
          ev.preventDefault();
          if (ev.key === "Enter") void applyTyped(typed);
          else if (ev.key === "Escape") {
            setTyped(null);
            setTypedError(null);
          } else if (ev.key === "Backspace") {
            setTyped(typed.length > 1 ? typed.slice(0, -1) : null);
            setTypedError(null);
          } else if (ev.key.length === 1 && typedChar(ev.key)) {
            setTyped(typed + ev.key);
            setTypedError(null);
          }
          return;
        }
        if (startsTyped(ev.key)) {
          ev.preventDefault();
          setTyped(ev.key);
          setTypedError(null);
          return;
        }
      }

      if (ev.key === "Escape") {
        // Innermost first: calibration, reference-edge pick, then the selected vertex, then the existing order.
        if (calib) return setCalib(null);
        if (refPick) return setRefPick(null);
        if (vertexSel) return setVertexSel(null);
        if (pick) return setPick(null);
        if (tool === "select" && !draft.length && !measure.length && !drag) dispatch({ type: "select", ids: [] });
        setDraft([]);
        setMeasure([]);
        setDrag(null);
        dispatch({ type: "setTool", tool: "select" });
        return;
      }
      if (ev.key === "Enter" && draft.length >= 3) {
        // Completion can open a conflict dialog synchronously. The same Enter
        // must not activate its newly focused Cancel button on keyup.
        ev.preventDefault();
        finishPolygon(draft);
        setDraft([]);
        return;
      }
      if (ev.key === "Backspace" && draft.length) {
        setDraft(draft.slice(0, -1));
        return;
      }
      // A selected vertex: Delete removes the vertex, not its object (UX2).
      if ((ev.key === "Delete" || ev.key === "Backspace") && vertexSel && editable && vertexSel.id === editable.id) {
        ev.preventDefault();
        const ring = vertexSel.ring === 0 ? editable.polygon : editable.holes[vertexSel.ring - 1];
        if (!ring || ring.length <= 3) { toast("error", t("ux2.minVertices")); return; }
        setVertexSel(null);
        void deleteVertex(editable, vertexSel.index, vertexSel.ring);
        return;
      }
      if ((ev.key === "Delete" || ev.key === "Backspace") &&
          selection.some((id) => entities.some((e) => e.id === id)) && selection.some((id) => modules.some((m) => m.id === id))) {
        ev.preventDefault();
        toast("info", t("s13a.mixedDelete"));
        return;
      }
      // PV layout step: Delete removes the selected modules, Shift+Delete their whole tables; arrows move tables.
      const selTables = layoutStep && !editable ? tablesOfModules(selection, tables).filter((x) => x.status === "active") : [];
      if ((ev.key === "Delete" || ev.key === "Backspace") && selTables.length) {
        ev.preventDefault();
        if (ev.shiftKey) void tableEdits.deleteTables(selTables.map((x) => x.table_id));
        else void tableEdits.deleteModules(selection.filter((id) => slotOf(id)));
        return;
      }
      const tableArrows: Record<string, Vec2> = { ArrowUp: [0, 1], ArrowDown: [0, -1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] };
      if (tableArrows[ev.key] && selTables.length && tool === "select") {
        ev.preventDefault();
        const k = ev.shiftKey ? NUDGE_LARGE_M : NUDGE_M;
        void tableEdits.moveTables(selTables.map((x) => x.table_id), [tableArrows[ev.key][0] * k, tableArrows[ev.key][1] * k]);
        return;
      }
      const moduleSelection = selection.length > 0 && selection.every((id) => modules.some((m) => m.id === id));
      if ((step === "scene" || layoutStep) && moduleSelection && !tablesOfModules(selection, tables).some((x) => x.status === "active")) {
        if (ev.key === "Delete" || ev.key === "Backspace") {
          ev.preventDefault();
          if (!state.busy) void moduleEdits.previewDelete(selection);
          return;
        }
        const delta = moduleNudge(ev.key, ev.shiftKey);
        if (delta && tool === "select") {
          ev.preventDefault();
          if (!state.busy) void moduleEdits.moveModules(selection, delta);
          return;
        }
      }
      if ((ev.key === "Delete" || ev.key === "Backspace") && selection.some((id) => entities.some((e) => e.id === id))) {
        ev.preventDefault();
        const items = entities.filter((e) => selection.includes(e.id));
        const targets = items.filter((e) => !e.locked);
        if (!targets.length) {
          toast("info", items.length === 1 ? t("tools.locked", { name: items[0].name }) : t("s13a.lockedCount", { count: items.length }));
          return;
        }
        window.dispatchEvent(new CustomEvent("rawibumi:delete-request", { detail: targets.map((e) => e.id) }));
        return;
      }
      const arrows: Record<string, Vec2> = { ArrowUp: [0, 1], ArrowDown: [0, -1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] };
      if (arrows[ev.key] && editable && tool === "select") {
        ev.preventDefault();
        const k = ev.shiftKey ? NUDGE_LARGE_M : NUDGE_M;
        void commitMove(editable, [arrows[ev.key][0] * k, arrows[ev.key][1] * k]);
        return;
      }
      const key = ev.key.toLowerCase();
      if (key === "z") return zoomKey();
      const next = toolByKey(step, key);
      if (next) dispatch({ type: "setTool", tool: next });
    }
    function onKeyUp(ev: KeyboardEvent) {
      if (ev.code === "Space") space.current = false;
      setShift(ev.shiftKey);
      setAlt(ev.altKey);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);
    const onBlur = () => { space.current = false; };
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
    };
  });

  useEffect(() => {
    const onFit = () => fit();
    window.addEventListener("rawibumi:fit", onFit);
    return () => window.removeEventListener("rawibumi:fit", onFit);
  }, [fit]);

  function typedPreviewText(): string {
    if (typed === null) return "";
    const r = interpretTyped(typed);
    if (r.angle !== undefined) return t("tools.typedAngle", { a: r.angle.toFixed(1) });
    if (r.point) return t("tools.typedPoint", { x: r.point[0].toFixed(2), y: r.point[1].toFixed(2) });
    return "";
  }

  const cursorStyle = tool === "select" ? (drag?.kind === "pan" ? "grabbing" : drag ? "move" : state.hover ? "pointer" : "grab") : "crosshair";
  const barMeters = niceStep(100 / view.scale);
  const layerStyle = { width: size.w, height: size.h };

  return (
    <div className="plan" ref={wrapRef}>
      <canvas ref={baseRef} className="plan__layer" style={layerStyle} aria-hidden="true" />
      <canvas ref={glRef} className="plan__layer" style={layerStyle} aria-hidden="true" />
      <canvas
        ref={overlayRef}
        className="plan__layer plan__canvas"
        style={{ ...layerStyle, cursor: cursorStyle }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={(ev) => void onPointerUp(ev)}
        onPointerLeave={() => setCursor(null)}
        onDoubleClick={onDoubleClick}
        onContextMenu={onContextMenu}
        aria-label={t("plan.ariaLabel", { modules: modules.length })}
        // Read-only view transform (centre x, centre y, px per metre) so live tests can aim at world points.
        data-plan-view={`${view.cx} ${view.cy} ${view.scale}`}
      />
      {typed !== null && (
        <div
          className={typedError ? "plan__typed plan__typed--bad" : "plan__typed"}
          style={cursor ? { left: toScreen(cursor)[0] + 16, top: toScreen(cursor)[1] + 16 } : { left: size.w / 2, top: size.h / 2 }}
          role="status"
          aria-live="polite"
          aria-label={t("tools.typedLabel")}
        >
          <span className="plan__typed-text">{typed}</span>
          <span className="plan__typed-note">{typedError ?? typedPreviewText()}</span>
        </div>
      )}
      {dimEdit && (
        <>
        <input
          className="plan__dim"
          style={{ left: dimEdit.at[0], top: dimEdit.at[1] }}
          aria-label={t("tools.dimensionLabel")}
          autoFocus
          value={dimEdit.value}
          aria-invalid={!!dimEdit.error}
          aria-describedby={dimEdit.error ? "scene-dimension-error" : undefined}
          disabled={!!entities.find((e) => e.id === dimEdit.id && e.source === "engine" && e.modified)}
          title={entities.find((e) => e.id === dimEdit.id && e.source === "engine" && e.modified) ? "Discard the local draft edits first" : undefined}
          onChange={(e) => setDimEdit({ ...dimEdit, value: e.target.value, error: undefined })}
          onKeyDown={(e) => {
            if (e.key === "Enter") applyDimension();
            if (e.key === "Escape") setDimEdit(null);
          }}
          onBlur={() => setDimEdit(null)}
        />
        {dimEdit.error && <p id="scene-dimension-error" role="alert" className="plan__typed plan__typed--bad">{dimEdit.error}</p>}
        </>
      )}
      {calib && calib.points.length === 2 && (
        <>
          <input
            className="plan__dim"
            style={{ left: (toScreen(calib.points[0])[0] + toScreen(calib.points[1])[0]) / 2, top: (toScreen(calib.points[0])[1] + toScreen(calib.points[1])[1]) / 2 }}
            aria-label={t("imagery.trueDistance")}
            placeholder={t("imagery.trueDistance")}
            autoFocus
            inputMode="decimal"
            value={calib.distance}
            aria-invalid={!!calib.error}
            onChange={(e) => setCalib({ ...calib, distance: e.target.value, error: undefined })}
            onKeyDown={(e) => {
              if (e.key === "Enter") void applyCalibration();
              if (e.key === "Escape") setCalib(null);
            }}
          />
          {calib.error && <p role="alert" className="plan__typed plan__typed--bad">{calib.error}</p>}
        </>
      )}
      {menu && (
        <ContextMenu
          items={menuItems}
          submenu={{ label: t("stage.view"), content: close => <ViewControls menu onClose={() => { close(); closeMenu(true); }} /> }}
          at={{ x: menu.at[0], y: menu.at[1] }}
          box={size}
          label={t("ux2.menuLabel")}
          onSelect={runMenu}
          onClose={closeMenu}
        />
      )}
      {glFailed && (
        <p className="plan__nogl" role="alert">
          {t("plan.noWebgl")}
        </p>
      )}
      <div className="plan__north" role="img" aria-label={t("plan.north")}>
        <svg width="30" height="48" viewBox="-15 -32 30 48">
          <path d="M 0 -16 L 7 10 L 0 5 L -7 10 Z" fill="currentColor" />
          <text x="0" y="-20" textAnchor="middle" fontSize="12" fill="currentColor" style={{ fontFamily: "var(--rb-font-drawing)" }}>
            N
          </text>
        </svg>
      </div>
      <div className="plan__scale">
        <div className="plan__scalebar" style={{ width: barMeters * view.scale }} />
        <span>{barMeters} m</span>
      </div>
      <div className="plan__readout">
        {cursor ? t("plan.readout", { x: cursor[0].toFixed(2), y: cursor[1].toFixed(2) }) : t("plan.readoutIdle")}
        {selected?.kind === "surface" && selected.holes.map((_, index) => <button key={index} type="button" className="btn btn--danger btn--sm" style={{ pointerEvents: "auto" }} disabled={!!state.busy || selected.modified || selected.locked} onClick={() => void removeHole(selected, index)}>{t("s11b.removeHole", { index: index + 1 })}</button>)}
        {tool !== "select" && <span className="plan__hint">{toolHint(t, tool, draft.length, pick)}</span>}
        {refPick && <span className="plan__hint" role="status" data-reference-pick>{t("ux2.pickHint")}</span>}
        {calib && calib.points.length < 2 && <span className="plan__hint" role="status" data-overlay-calibrate>{t(calib.points.length ? "imagery.calibrateSecond" : "imagery.calibrateFirst")}</span>}
      </div>
      {synthetic && <div className="plan__synthetic">{t("plan.synthetic", { count: modules.length })}</div>}
      {perfRequested() && <PerfOverlay perf={perf} modules={modules.length} />}
      {satelliteShown && satellite?.attribution && <div className="plan__attrib">{satellite.attribution}</div>}
    </div>
  );
}

function toolHint(t: (k: string) => string, tool: Tool, n: number, pick: Pick) {
  if (DRAW_TOOLS.has(tool)) return n < 3 ? t("plan.hintDraw") : t("plan.hintClose");
  if (RECT_TOOLS.has(tool)) return pick?.kind === "rect" ? t("plan.hintRectSecond") : t("plan.hintRect");
  if (tool === "measure") return t("plan.hintMeasure");
  if (tool === "move") return pick?.kind === "move" ? t("plan.hintMoveTo") : t("plan.hintMoveBase");
  if (tool === "rotate") return pick?.kind === "rotate" ? t("plan.hintRotateAngle") : t("plan.hintRotatePivot");
  if (ELECTRICAL_TOOL_SET.has(tool)) return t(`plan.hint_${tool}`);
  return "";
}


/** USE3b: the selected modules that are in no string, in selection order. */
function unstrungOf(view: ProjectView, ids: string[]): string[] {
  const strung = new Set(view.bundle.electrical_design.strings.flatMap((s) => s.module_instance_ids));
  return ids.filter((id) => !strung.has(id));
}

/** USE3b: where a right-clicked unstrung selection can go: an existing string, or a new string on an MPPT. */
function unstrungTargets(view: ProjectView, ids: string[]) {
  const count = unstrungOf(view, ids).length;
  const mpptLabel = new Map(view.topology_view.inverters.flatMap((inv) => inv.mppts.map((m) => [m.mppt_instance_id, `${inv.name} · MPPT ${m.index}`] as const)));
  return {
    count,
    strings: view.bundle.electrical_design.strings.map((s) => ({ id: s.string_id,
      label: `${s.string_id}${s.target_mppt_instance_id ? ` · ${mpptLabel.get(s.target_mppt_instance_id) ?? ""}` : ""} · ${s.module_instance_ids.length}` })),
    mppts: [...mpptLabel].map(([id, label]) => ({ id, label }))
  };
}
