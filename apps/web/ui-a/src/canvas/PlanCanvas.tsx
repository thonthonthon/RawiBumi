import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DEMO, engine } from "../client";
import {
  bearingDeg,
  bounds,
  centroid,
  dist,
  distToSegment,
  pointInPolygon,
  pointInShape,
  rotatePoly,
  translatePoly,
  validatePolygon,
  Vec2
} from "../geometry";
import { Entity, useStore } from "../state/store";


interface ViewT {
  cx: number;
  cy: number;
  scale: number; // px per metre
}


type Drag =
  | { kind: "pan"; start: Vec2; startView: ViewT }
  | { kind: "move"; id: string; startWorld: Vec2; original: Vec2[]; originalHoles: Vec2[][]; delta: Vec2 }
  | { kind: "vertex"; id: string; ring: number; index: number; original: Vec2[]; current: Vec2 }
  | { kind: "rotate"; id: string; pivot: Vec2; startAngle: number; original: Vec2[]; originalHoles: Vec2[][]; angle: number }
  | { kind: "rect"; start: Vec2; current: Vec2 };


const MPPT_COLORS = ["#1d4f8f", "#0f7a6c", "#7a4fa3", "#a8641a", "#2f6fbf", "#4f8a2f", "#a33a5b", "#56657a", "#c08a00", "#1b8aa8"];


const tileCache = new Map<string, HTMLImageElement>();


function niceStep(metersPer100px: number) {
  const steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500];
  return steps.find((s) => s >= metersPer100px) ?? 1000;
}


export function PlanCanvas() {
  const { state, dispatch, run, toast } = useStore();
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [view, setView] = useState<ViewT>({ cx: 20, cy: 9, scale: 18 });
  const [cursor, setCursor] = useState<Vec2 | null>(null);
  const [draft, setDraft] = useState<Vec2[]>([]);
  const [measure, setMeasure] = useState<Vec2[]>([]);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [shift, setShift] = useState(false);
  const fittedRef = useRef<string | null>(null);
  const [, forceTick] = useState(0);


  const { entities, modules, selection, tool, underlay, snap, view: pview, step } = state;
  const selected = entities.find((e) => selection.includes(e.id)) ?? null;
  const electrical = step === "electrical";


  // ---- sizing -------------------------------------------------------------
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);


  const toScreen = useCallback((p: Vec2): Vec2 => [(p[0] - view.cx) * view.scale + size.w / 2, size.h / 2 - (p[1] - view.cy) * view.scale], [view, size]);
  const toWorld = useCallback((s: Vec2): Vec2 => [(s[0] - size.w / 2) / view.scale + view.cx, (size.h / 2 - s[1]) / view.scale + view.cy], [view, size]);


  // Demo builds expose the transform so screenshot scripts can click world coordinates.
  useEffect(() => {
    if (!DEMO) return;
    const r = () => canvasRef.current?.getBoundingClientRect();
    (window as unknown as { __rawibumiPlan: unknown }).__rawibumiPlan = {
      toPage: (x: number, y: number) => {
        const s = toScreen([x, y]);
        const b = r();
        return [s[0] + (b?.left ?? 0), s[1] + (b?.top ?? 0)];
      }
    };
  }, [toScreen]);


  const fit = useCallback(() => {
    const polys = [...entities.map((e) => e.polygon), ...modules.slice(0, 5000).map((m) => m.polygon)];
    const b = bounds(polys);
    const w = Math.max(b.maxX - b.minX, 4);
    const h = Math.max(b.maxY - b.minY, 4);
    const scale = Math.min((size.w - 120) / w, (size.h - 120) / h);
    setView({ cx: (b.minX + b.maxX) / 2, cy: (b.minY + b.maxY) / 2, scale: Math.max(0.05, Math.min(400, scale)) });
  }, [entities, modules, size]);


  useEffect(() => {
    const key = pview?.bundle.project.project_id ?? null;
    if (key && fittedRef.current !== key && size.w > 200) {
      fittedRef.current = key;
      fit();
    }
  }, [pview, fit, size.w]);


  // ---- image underlay loading --------------------------------------------
  useEffect(() => {
    if (!underlay.imageDataUrl) {
      imgRef.current = null;
      return;
    }
    const img = new Image();
    img.onload = () => forceTick((t) => t + 1);
    img.src = underlay.imageDataUrl;
    imgRef.current = img;
  }, [underlay.imageDataUrl]);


  // ---- snapping -----------------------------------------------------------
  const allVertices = useMemo(() => entities.filter((e) => !e.hidden).flatMap((e) => [...e.polygon, ...e.holes.flat()]), [entities]);


  const snapPoint = useCallback(
    (w: Vec2, from?: Vec2): { p: Vec2; snapped: string | null } => {
      if (snap.vertex) {
        let best: Vec2 | null = null;
        let bestD = 10 / view.scale;
        for (const v of allVertices) {
          const d = dist(v, w);
          if (d < bestD) {
            best = v;
            bestD = d;
          }
        }
        if (best) return { p: [best[0], best[1]], snapped: "vertex" };
      }
      if (from && shift && snap.angle) {
        const ang = Math.atan2(w[1] - from[1], w[0] - from[0]);
        const q = (Math.round(ang / (Math.PI / 12)) * Math.PI) / 12;
        const r = dist(w, from);
        return { p: [from[0] + r * Math.cos(q), from[1] + r * Math.sin(q)], snapped: "15°" };
      }
      if (snap.grid) {
        const g = snap.gridStep;
        return { p: [Math.round(w[0] / g) * g, Math.round(w[1] / g) * g], snapped: "grid" };
      }
      return { p: w, snapped: null };
    },
    [snap, view.scale, allVertices, shift]
  );


  // ---- drawing ------------------------------------------------------------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size.w * dpr;
    canvas.height = size.h * dpr;
    const ctx = canvas.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#e9eef1";
    ctx.fillRect(0, 0, size.w, size.h);


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


    // Underlay: tiles
    if (underlay.kind === "tiles" && underlay.tileUrl && pview) {
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
      const lonA = lon0 + tl[0] / mPerDegLon;
      const lonB = lon0 + br[0] / mPerDegLon;
      const latA = lat0 + tl[1] / mPerDegLat;
      const latB = lat0 + br[1] / mPerDegLat;
      const x0 = Math.floor(lonToX(lonA));
      const x1 = Math.floor(lonToX(lonB));
      const y0 = Math.floor(latToY(latA));
      const y1 = Math.floor(latToY(latB));
      ctx.globalAlpha = underlay.opacity;
      if ((x1 - x0 + 1) * (y1 - y0 + 1) <= 64)
        for (let tx = x0; tx <= x1; tx++)
          for (let ty = y0; ty <= y1; ty++) {
            const url = underlay.tileUrl.replace("{z}", String(z)).replace("{x}", String(tx)).replace("{y}", String(ty)).replace("{key}", underlay.apiKey);
            let img = tileCache.get(url);
            if (!img) {
              img = new Image();
              img.crossOrigin = "anonymous";
              img.onload = () => forceTick((t) => t + 1);
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


    // Underlay: uploaded image
    const img = imgRef.current;
    if (underlay.kind === "image" && img && img.complete && img.naturalWidth) {
      const o = toScreen(underlay.imageOffset);
      ctx.save();
      ctx.globalAlpha = underlay.opacity;
      ctx.translate(o[0], o[1]);
      ctx.rotate((-underlay.imageRotationDeg * Math.PI) / 180);
      const k = underlay.imageMetersPerPixel * view.scale;
      ctx.drawImage(img, 0, 0, img.naturalWidth * k, img.naturalHeight * k);
      ctx.restore();
    }


    // Grid
    const step = niceStep(100 / view.scale);
    const minor = step / 5;
    const tl = toWorld([0, 0]);
    const br = toWorld([size.w, size.h]);
    const drawGrid = (g: number, color: string) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
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
      ctx.stroke();
    };
    if (underlay.kind === "none") {
      if (minor * view.scale > 6) drawGrid(minor, "#dfe6ea");
      drawGrid(step, "#cfd8de");
    }
    // Origin
    const o = toScreen([0, 0]);
    ctx.strokeStyle = "#8795a1";
    ctx.beginPath();
    ctx.moveTo(o[0] - 8, o[1]);
    ctx.lineTo(o[0] + 8, o[1]);
    ctx.moveTo(o[0], o[1] - 8);
    ctx.lineTo(o[0], o[1] + 8);
    ctx.stroke();


    const hatch = (color: string) => {
      const pc = document.createElement("canvas");
      pc.width = pc.height = 8;
      const g = pc.getContext("2d")!;
      g.strokeStyle = color;
      g.lineWidth = 1.2;
      g.beginPath();
      g.moveTo(0, 8);
      g.lineTo(8, 0);
      g.stroke();
      return ctx.createPattern(pc, "repeat")!;
    };


    // Surfaces
    for (const e of entities) {
      if (e.hidden || e.kind !== "surface") continue;
      path(e.polygon, e.holes);
      ctx.fillStyle = e.source === "draft" ? "rgba(214,176,74,0.20)" : "rgba(150,170,186,0.42)";
      ctx.fill("evenodd");
      ctx.setLineDash(e.source === "draft" || e.modified ? [6, 4] : []);
      ctx.strokeStyle = e.source === "draft" ? "#9a7412" : "#51677a";
      ctx.lineWidth = 1.4;
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // Keepouts
    const ko = hatch("#b42318");
    for (const e of entities) {
      if (e.hidden || e.kind !== "keepout") continue;
      path(e.polygon, e.holes);
      ctx.fillStyle = ko;
      ctx.fill("evenodd");
      ctx.strokeStyle = "#b42318";
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // Modules
    const showEdges = view.scale > 7;
    for (const m of modules) {
      path(m.polygon);
      let fill = "#1d4f8f";
      if (electrical) {
        if (!m.mpptKey) fill = m.stringId ? "#8a97a3" : "#c3ccd3";
        else fill = MPPT_COLORS[Number(m.mpptKey.split("#")[1]) % MPPT_COLORS.length];
      }
      ctx.fillStyle = selection.includes(m.id) ? "#d98e04" : fill;
      ctx.fill();
      if (showEdges) {
        ctx.strokeStyle = electrical ? "rgba(255,255,255,0.7)" : "#6d93c7";
        ctx.lineWidth = 0.8;
        ctx.stroke();
      }
    }
    // String labels in electrical overlay
    if (electrical && view.scale > 10) {
      const firstOf = new Map<string, Vec2>();
      for (const m of modules) if (m.stringId && !firstOf.has(m.stringId)) firstOf.set(m.stringId, centroid(m.polygon));
      ctx.font = "600 11px 'Barlow Semi Condensed', sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      for (const [sid, p] of firstOf) {
        const s = toScreen(p);
        ctx.fillStyle = "rgba(255,255,255,0.92)";
        ctx.fillRect(s[0] - 13, s[1] - 8, 26, 16);
        ctx.fillStyle = "#1c2630";
        ctx.fillText(sid, s[0], s[1]);
      }
    }
    // Obstacles
    for (const e of entities) {
      if (e.hidden || e.kind !== "obstacle") continue;
      path(e.polygon, e.holes);
      ctx.fillStyle = e.source === "draft" ? "rgba(138,90,68,0.35)" : "rgba(122,78,58,0.72)";
      ctx.fill("evenodd");
      ctx.setLineDash(e.source === "draft" || e.modified ? [6, 4] : []);
      ctx.strokeStyle = "#5a3627";
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.setLineDash([]);
    }


    // Entity names
    if (view.scale > 6) {
      ctx.font = "600 12px 'Barlow Semi Condensed', sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      for (const e of entities) {
        if (e.hidden || e.kind === "keepout") continue;
        const b = bounds([e.polygon]);
        const s = toScreen([b.minX, b.maxY]);
        const label = e.source === "draft" ? `${e.name} · draft` : e.name;
        ctx.fillStyle = e.kind === "obstacle" ? "#5a3627" : e.source === "draft" ? "#7a5a0a" : "#3c5063";
        if (e.kind === "obstacle") ctx.fillText(label, s[0], s[1] - 16);
        else ctx.fillText(label, s[0] + 6, s[1] + 5);
      }
    }


    // Hover outline
    const hov = entities.find((e) => e.id === state.hover);
    if (hov && !selection.includes(hov.id)) {
      path(hov.polygon, hov.holes);
      ctx.strokeStyle = "#d98e04";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }


    // Selection
    const sel = selected ? previewEntity(selected, drag) : null;
    if (sel) {
      path(sel.polygon, sel.holes);
      ctx.strokeStyle = "#d98e04";
      ctx.lineWidth = 2;
      ctx.stroke();
      // edge lengths
      ctx.font = "500 11px 'Barlow Semi Condensed', sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const n = sel.polygon.length;
      for (let i = 0; i < n; i++) {
        const a = sel.polygon[i];
        const b = sel.polygon[(i + 1) % n];
        const l = dist(a, b);
        const sa = toScreen(a);
        const sb = toScreen(b);
        if (Math.hypot(sb[0] - sa[0], sb[1] - sa[1]) < 48) continue;
        const mx = (sa[0] + sb[0]) / 2;
        const my = (sa[1] + sb[1]) / 2;
        const label = `${l.toFixed(2)} m`;
        const w = ctx.measureText(label).width + 8;
        ctx.fillStyle = "rgba(255,255,255,0.92)";
        ctx.fillRect(mx - w / 2, my - 8, w, 16);
        ctx.fillStyle = "#6b4700";
        ctx.fillText(label, mx, my);
      }
      if (!selected!.locked) {
        for (const ring of [sel.polygon, ...sel.holes])
          for (const v of ring) {
            const s = toScreen(v);
            ctx.fillStyle = "#fff";
            ctx.strokeStyle = "#d98e04";
            ctx.lineWidth = 1.5;
            ctx.fillRect(s[0] - 4.5, s[1] - 4.5, 9, 9);
            ctx.strokeRect(s[0] - 4.5, s[1] - 4.5, 9, 9);
          }
        const rh = rotateHandle(sel.polygon);
        const s = toScreen(rh.handle);
        const c = toScreen(rh.anchor);
        ctx.strokeStyle = "#d98e04";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(c[0], c[1]);
        ctx.lineTo(s[0], s[1] + 22);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(s[0], s[1] + 22, 6, 0, Math.PI * 2);
        ctx.fillStyle = "#fff";
        ctx.fill();
        ctx.stroke();
      }
      if (drag?.kind === "rotate") {
        const c = toScreen(drag.pivot);
        ctx.fillStyle = "#6b4700";
        ctx.font = "600 12px 'Barlow Semi Condensed', sans-serif";
        ctx.fillText(`${drag.angle.toFixed(1)}°`, c[0], c[1] - 14);
      }
      if (drag?.kind === "move") {
        const c = toScreen(centroid(sel.polygon));
        ctx.fillStyle = "#6b4700";
        ctx.font = "600 12px 'Barlow Semi Condensed', sans-serif";
        ctx.fillText(`Δ ${drag.delta[0].toFixed(2)}, ${drag.delta[1].toFixed(2)} m`, c[0], c[1] - 14);
      }
    }


    // Drawing preview
    if (draft.length && cursor) {
      const snapNext = snapPoint(cursor, draft[draft.length - 1]).p;
      const pts = [...draft, snapNext];
      ctx.beginPath();
      pts.forEach((p, i) => {
        const s = toScreen(p);
        if (i === 0) ctx.moveTo(s[0], s[1]);
        else ctx.lineTo(s[0], s[1]);
      });
      ctx.strokeStyle = "#9a7412";
      ctx.lineWidth = 1.6;
      ctx.setLineDash([5, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
      for (const p of draft) {
        const s = toScreen(p);
        ctx.fillStyle = "#fff";
        ctx.strokeStyle = "#9a7412";
        ctx.fillRect(s[0] - 4, s[1] - 4, 8, 8);
        ctx.strokeRect(s[0] - 4, s[1] - 4, 8, 8);
      }
      const a = draft[draft.length - 1];
      const l = dist(a, snapNext);
      const s = toScreen(snapNext);
      const label = `${l.toFixed(2)} m · ${bearingDeg(a, snapNext).toFixed(1)}°`;
      ctx.font = "600 12px 'Barlow Semi Condensed', sans-serif";
      const w = ctx.measureText(label).width + 10;
      ctx.fillStyle = "#1c2630";
      ctx.fillRect(s[0] + 12, s[1] + 10, w, 20);
      ctx.fillStyle = "#fff";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(label, s[0] + 17, s[1] + 20);
      if (draft.length >= 3 && dist(toScreen(draft[0]), toScreen(cursor)) < 10) {
        const f = toScreen(draft[0]);
        ctx.strokeStyle = "#2f7a4a";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(f[0], f[1], 8, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    // Engine rectangle preview
    if (drag?.kind === "rect") {
      const a = toScreen(drag.start);
      const b = toScreen(drag.current);
      ctx.strokeStyle = "#1d4f8f";
      ctx.setLineDash([5, 4]);
      ctx.strokeRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
      ctx.setLineDash([]);
      const w = Math.abs(drag.current[0] - drag.start[0]);
      const h = Math.abs(drag.current[1] - drag.start[1]);
      ctx.fillStyle = "#1d4f8f";
      ctx.font = "600 12px 'Barlow Semi Condensed', sans-serif";
      ctx.fillText(`${w.toFixed(2)} × ${h.toFixed(2)} m`, Math.max(a[0], b[0]) + 8, Math.max(a[1], b[1]) + 14);
    }
    // Measure
    if (tool === "measure" && measure.length) {
      const pts = measure.length === 1 && cursor ? [measure[0], snapPoint(cursor).p] : measure;
      const a = toScreen(pts[0]);
      const b = toScreen(pts[1] ?? pts[0]);
      ctx.strokeStyle = "#0f7a6c";
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
      ctx.stroke();
      if (pts[1]) {
        const label = `${dist(pts[0], pts[1]).toFixed(3)} m · ${bearingDeg(pts[0], pts[1]).toFixed(1)}° from N`;
        ctx.font = "600 12px 'Barlow Semi Condensed', sans-serif";
        const w = ctx.measureText(label).width + 10;
        ctx.fillStyle = "#0f7a6c";
        ctx.fillRect((a[0] + b[0]) / 2 - w / 2, (a[1] + b[1]) / 2 - 22, w, 20);
        ctx.fillStyle = "#fff";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(label, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 12);
      }
    }
  }, [size, view, entities, modules, selection, selected, drag, draft, cursor, tool, measure, underlay, electrical, state.hover, pview, snapPoint, toScreen, toWorld]);


  // ---- helpers ------------------------------------------------------------
  function rotateHandle(poly: Vec2[]) {
    const b = bounds([poly]);
    const anchor: Vec2 = [(b.minX + b.maxX) / 2, b.maxY];
    return { anchor, handle: anchor };
  }


  function previewEntity(e: Entity, d: Drag | null): Entity {
    if (!d) return e;
    if (d.kind === "move" && d.id === e.id)
      return { ...e, polygon: translatePoly(d.original, d.delta), holes: d.originalHoles.map((h) => translatePoly(h, d.delta)) };
    if (d.kind === "vertex" && d.id === e.id) {
      if (d.ring === 0) {
        const poly = d.original.slice();
        poly[d.index] = d.current;
        return { ...e, polygon: poly };
      }
      const holes = e.holes.map((h, i) => (i === d.ring - 1 ? h.map((p, j) => (j === d.index ? d.current : p)) : h));
      return { ...e, holes };
    }
    if (d.kind === "rotate" && d.id === e.id)
      return { ...e, polygon: rotatePoly(d.original, d.pivot, d.angle), holes: d.originalHoles.map((h) => rotatePoly(h, d.pivot, d.angle)) };
    return e;
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
    for (let i = modules.length - 1; i >= 0; i--) if (pointInPolygon(w, modules[i].polygon)) return modules[i].id;
    return null;
  }


  function finishPolygon(points: Vec2[]) {
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
      dispatch({
        type: "updateEntity",
        id: selected.id,
        patch: {
          holes: [...selected.holes, points],
          modified: selected.source === "engine" ? true : selected.modified,
          pending: [...new Set([...selected.pending, selected.source === "engine" ? "editVertices" : "polygonSurface"])]
        }
      });
      dispatch({ type: "setTool", tool: "select" });
      return;
    }
    const kind = tool === "obstacle" ? "obstacle" : tool === "keepout" ? "keepout" : "surface";
    const count = entities.filter((e) => e.kind === kind).length + 1;
    const pending = kind === "surface" ? "polygonSurface" : kind === "obstacle" ? "polygonObstacle" : "keepout";
    dispatch({
      type: "addEntity",
      entity: {
        id: `draft-${kind}-${Date.now().toString(36)}`,
        kind,
        subtype: kind === "surface" ? "flat_roof" : kind === "obstacle" ? "extrusion" : "exclusion_zone",
        name: kind === "surface" ? `Surface ${count}` : kind === "obstacle" ? `Obstacle ${count}` : `Keep-out ${count}`,
        polygon: points,
        holes: [],
        plane: { mode: "flat", z_m: kind === "surface" ? 0 : 0 },
        height_m: kind === "obstacle" ? 1.5 : 0,
        source: "draft",
        modified: false,
        pending: [pending],
        locked: false,
        hidden: false,
        hostsPvField: false
      }
    });
    dispatch({ type: "setTool", tool: "select" });
  }


  // ---- pointer handlers ---------------------------------------------------
  function localPoint(ev: React.PointerEvent | React.MouseEvent | React.WheelEvent): Vec2 {
    const r = canvasRef.current!.getBoundingClientRect();
    return [ev.clientX - r.left, ev.clientY - r.top];
  }


  function onPointerDown(ev: React.PointerEvent) {
    const sp = localPoint(ev);
    const w = toWorld(sp);
    (ev.target as HTMLElement).setPointerCapture(ev.pointerId);
    if (ev.button === 1 || ev.button === 2) {
      setDrag({ kind: "pan", start: sp, startView: view });
      return;
    }
    if (tool === "polygon" || tool === "obstacle" || tool === "keepout" || tool === "hole") {
      if (draft.length >= 3 && dist(toScreen(draft[0]), sp) < 10) {
        finishPolygon(draft);
        setDraft([]);
        return;
      }
      const p = snapPoint(w, draft[draft.length - 1]).p;
      setDraft([...draft, p]);
      return;
    }
    if (tool === "rect_engine") {
      const p = snapPoint(w).p;
      setDrag({ kind: "rect", start: p, current: p });
      return;
    }
    if (tool === "measure") {
      const p = snapPoint(w).p;
      setMeasure(measure.length === 1 ? [measure[0], p] : [p]);
      return;
    }
    // select tool
    if (selected && !selected.locked) {
      const rings = [selected.polygon, ...selected.holes];
      for (let r = 0; r < rings.length; r++)
        for (let i = 0; i < rings[r].length; i++) {
          if (dist(toScreen(rings[r][i]), sp) < 8) {
            if (ev.altKey) {
              if (rings[r].length <= 3) return toast("error", "A polygon needs at least 3 vertices.");
              const next = rings[r].filter((_, j) => j !== i);
              commitGeometry(selected, r === 0 ? next : selected.polygon, r === 0 ? selected.holes : selected.holes.map((h, k) => (k === r - 1 ? next : h)), "editVertices");
              return;
            }
            setDrag({ kind: "vertex", id: selected.id, ring: r, index: i, original: rings[r].slice(), current: rings[r][i] });
            return;
          }
        }
      const rh = rotateHandle(selected.polygon);
      const hs = toScreen(rh.handle);
      if (Math.hypot(hs[0] - sp[0], hs[1] + 22 - sp[1]) < 9) {
        const pivot = centroid(selected.polygon);
        setDrag({ kind: "rotate", id: selected.id, pivot, startAngle: Math.atan2(w[1] - pivot[1], w[0] - pivot[0]), original: selected.polygon, originalHoles: selected.holes, angle: 0 });
        return;
      }
    }
    const hit = hitEntity(w);
    const mod = !hit || hit.kind === "surface" ? hitModule(w) : null;
    if (mod) {
      dispatch({ type: "select", ids: ev.shiftKey ? [...selection, mod] : [mod] });
      return;
    }
    if (hit) {
      dispatch({ type: "select", ids: [hit.id] });
      if (!hit.locked) setDrag({ kind: "move", id: hit.id, startWorld: w, original: hit.polygon, originalHoles: hit.holes, delta: [0, 0] });
      return;
    }
    dispatch({ type: "select", ids: [] });
    setDrag({ kind: "pan", start: sp, startView: view });
  }


  function onPointerMove(ev: React.PointerEvent) {
    const sp = localPoint(ev);
    const w = toWorld(sp);
    setCursor(w);
    if (!drag) {
      if (tool === "select") {
        const h = hitEntity(w);
        dispatch({ type: "hover", id: h?.id ?? null });
      }
      return;
    }
    if (drag.kind === "pan") {
      setView({ ...drag.startView, cx: drag.startView.cx - (sp[0] - drag.start[0]) / view.scale, cy: drag.startView.cy + (sp[1] - drag.start[1]) / view.scale });
    } else if (drag.kind === "move") {
      let d: Vec2 = [w[0] - drag.startWorld[0], w[1] - drag.startWorld[1]];
      if (snap.grid) d = [Math.round(d[0] / snap.gridStep) * snap.gridStep, Math.round(d[1] / snap.gridStep) * snap.gridStep];
      setDrag({ ...drag, delta: d });
    } else if (drag.kind === "vertex") {
      const neighbours = drag.original;
      setDrag({ ...drag, current: snapPoint(w, neighbours[(drag.index - 1 + neighbours.length) % neighbours.length]).p });
    } else if (drag.kind === "rotate") {
      let a = ((Math.atan2(w[1] - drag.pivot[1], w[0] - drag.pivot[0]) - drag.startAngle) * 180) / Math.PI;
      if (ev.shiftKey || snap.angle) a = Math.round(a / (ev.shiftKey ? 15 : 1)) * (ev.shiftKey ? 15 : 1);
      setDrag({ ...drag, angle: a });
    } else if (drag.kind === "rect") {
      setDrag({ ...drag, current: snapPoint(w).p });
    }
  }


  function commitGeometry(e: Entity, polygon: Vec2[], holes: Vec2[][], pendingId: string) {
    const issues = validatePolygon(polygon);
    if (issues.length) {
      toast("error", `Edit rejected: ${issues[0].message}`);
      return;
    }
    dispatch({
      type: "updateEntity",
      id: e.id,
      patch: {
        polygon,
        holes,
        modified: e.source === "engine" ? true : e.modified,
        pending: e.source === "engine" ? [...new Set([...e.pending, pendingId])] : e.pending
      }
    });
    if (e.source === "engine") toast("pending", `Local edit kept as draft. Commit needs ${pendingId} endpoint.`);
  }


  async function onPointerUp() {
    const d = drag;
    setDrag(null);
    if (!d) return;
    if (d.kind === "move") {
      const e = entities.find((x) => x.id === d.id);
      if (!e || (Math.abs(d.delta[0]) < 1e-6 && Math.abs(d.delta[1]) < 1e-6)) return;
      if (e.source === "engine" && !e.modified) {
        // Wired path: engine move command. Engine is fail-closed for surfaces hosting PV fields.
        const v = await run("Moving", () => engine.moveSceneEntity(pview!.bundle.project.project_id, { entity_id: e.id, dx_m: d.delta[0], dy_m: d.delta[1] }));
        if (v) {
          dispatch({ type: "checkpoint" });
          dispatch({ type: "setView", view: v });
        }
        return;
      }
      commitGeometry(e, translatePoly(d.original, d.delta), d.originalHoles.map((h) => translatePoly(h, d.delta)), "editVertices");
    } else if (d.kind === "vertex") {
      const e = entities.find((x) => x.id === d.id);
      if (!e) return;
      const p = previewEntity(e, d);
      commitGeometry(e, p.polygon, p.holes, "editVertices");
    } else if (d.kind === "rotate") {
      const e = entities.find((x) => x.id === d.id);
      if (!e || Math.abs(d.angle) < 1e-9) return;
      commitGeometry(e, rotatePoly(d.original, d.pivot, d.angle), d.originalHoles.map((h) => rotatePoly(h, d.pivot, d.angle)), "rotateEntity");
    } else if (d.kind === "rect") {
      const w = Math.abs(d.current[0] - d.start[0]);
      const h = Math.abs(d.current[1] - d.start[1]);
      if (w < 0.2 || h < 0.2) return;
      const count = state.view?.bundle.scene.surfaces.length ?? 0;
      const v = await run("Creating surface", () =>
        engine.addSurface(pview!.bundle.project.project_id, {
          name: `Roof ${String.fromCharCode(65 + count)}`,
          origin_x_m: Math.min(d.start[0], d.current[0]),
          origin_y_m: Math.min(d.start[1], d.current[1]),
          width_m: w,
          height_m: h,
          base_elevation_m: 0,
          surface_type: "flat_roof",
          usable_for_pv: true
        })
      );
      if (v) {
        dispatch({ type: "setView", view: v });
        dispatch({ type: "setTool", tool: "select" });
        toast("ok", "Surface created in the engine.");
      }
    }
  }


  function onDoubleClick(ev: React.MouseEvent) {
    const sp = localPoint(ev);
    const w = toWorld(sp);
    if ((tool === "polygon" || tool === "obstacle" || tool === "keepout" || tool === "hole") && draft.length >= 3) {
      finishPolygon(draft.slice(0, -1).length >= 3 ? draft.slice(0, -1) : draft);
      setDraft([]);
      return;
    }
    if (tool === "select" && selected && !selected.locked) {
      const n = selected.polygon.length;
      for (let i = 0; i < n; i++) {
        const a = selected.polygon[i];
        const b = selected.polygon[(i + 1) % n];
        if (distToSegment(w, a, b) * view.scale < 7) {
          const poly = [...selected.polygon.slice(0, i + 1), w, ...selected.polygon.slice(i + 1)];
          commitGeometry(selected, poly, selected.holes, "editVertices");
          return;
        }
      }
    }
  }


  function onWheel(ev: React.WheelEvent) {
    const sp = localPoint(ev);
    const before = toWorld(sp);
    const k = Math.exp(-ev.deltaY * 0.0015);
    const scale = Math.max(0.05, Math.min(400, view.scale * k));
    const cx = before[0] - (sp[0] - size.w / 2) / scale;
    const cy = before[1] - (size.h / 2 - sp[1]) / scale;
    setView({ cx, cy, scale });
  }


  // ---- keyboard -------------------------------------------------------------
  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      const t = ev.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
      setShift(ev.shiftKey);
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") {
        ev.preventDefault();
        dispatch({ type: ev.shiftKey ? "redo" : "undo" });
        return;
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "y") {
        ev.preventDefault();
        dispatch({ type: "redo" });
        return;
      }
      if (ev.key === "Escape") {
        setDraft([]);
        setMeasure([]);
        setDrag(null);
        dispatch({ type: "setTool", tool: "select" });
        return;
      }
      if (ev.key === "Enter" && draft.length >= 3) {
        finishPolygon(draft);
        setDraft([]);
        return;
      }
      if (ev.key === "Backspace" && draft.length) {
        setDraft(draft.slice(0, -1));
        return;
      }
      if ((ev.key === "Delete" || ev.key === "Backspace") && selected && !selected.locked) {
        window.dispatchEvent(new CustomEvent("rawibumi:delete-request", { detail: selected.id }));
        return;
      }
      const map: Record<string, typeof tool> = { v: "select", p: "polygon", r: "rect_engine", o: "obstacle", k: "keepout", m: "measure", h: "hole" };
      const next = map[ev.key.toLowerCase()];
      if (next && !ev.ctrlKey && !ev.metaKey) {
        setDraft([]);
        dispatch({ type: "setTool", tool: next });
      }
      if (ev.key.toLowerCase() === "f" && !ev.ctrlKey) fit();
    }
    function onKeyUp(ev: KeyboardEvent) {
      setShift(ev.shiftKey);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKeyUp);
    };
  });


  useEffect(() => {
    function onFit() {
      fit();
    }
    window.addEventListener("rawibumi:fit", onFit);
    return () => window.removeEventListener("rawibumi:fit", onFit);
  }, [fit]);


  const cursorStyle =
    tool === "select" ? (drag?.kind === "pan" ? "grabbing" : drag ? "move" : state.hover ? "pointer" : "grab") : "crosshair";
  const barMeters = niceStep(100 / view.scale);


  return (
    <div className="plan" ref={wrapRef}>
      <canvas
        ref={canvasRef}
        className="plan__canvas"
        style={{ width: size.w, height: size.h, cursor: cursorStyle }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={() => void onPointerUp()}
        onPointerLeave={() => setCursor(null)}
        onDoubleClick={onDoubleClick}
        onWheel={onWheel}
        onContextMenu={(e) => e.preventDefault()}
        aria-label="PV plan editor"
      />
      <div className="plan__north" aria-label="True north up">
        <svg width="30" height="48" viewBox="-15 -32 30 48">
          <path d="M 0 -16 L 7 10 L 0 5 L -7 10 Z" fill="#1c2630" />
          <text x="0" y="-20" textAnchor="middle" fontSize="12" fontWeight="600" fill="#1c2630">
            N
          </text>
        </svg>
      </div>
      <div className="plan__scale">
        <div className="plan__scalebar" style={{ width: barMeters * view.scale }} />
        <span>{barMeters} m</span>
      </div>
      <div className="plan__readout">
        {cursor ? `X ${cursor[0].toFixed(2)}  Y ${cursor[1].toFixed(2)} m` : "Local metric plane · X east, Y north"}
        {tool !== "select" && <span className="plan__hint">{toolHint(tool, draft.length)}</span>}
      </div>
      {underlay.kind === "tiles" && underlay.tileAttribution && <div className="plan__attrib">{underlay.tileAttribution}</div>}
    </div>
  );
}


function toolHint(tool: string, n: number) {
  if (tool === "polygon" || tool === "obstacle" || tool === "keepout" || tool === "hole")
    return n < 3 ? "Click to place vertices · Shift snaps 15° · Esc cancels" : "Click the first vertex, press Enter or double-click to close";
  if (tool === "rect_engine") return "Drag a rectangle · created directly in the engine";
  if (tool === "measure") return "Click two points";
  return "";
}