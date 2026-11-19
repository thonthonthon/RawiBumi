import { bounds, centroid, type Vec2 } from "../geometry";
import type { Entity, ModuleShape } from "../state/store";
import { drawingFont, token } from "../ui/palette";
import { PlanRenderer } from "./gl/planRenderer";
import { drawElectricalOverlay, type OverlayString } from "./plan/electricalOverlay";
import { drawEntityLabels } from "./plan/labels";
import { fitView, niceStep, toScreen as screenOf, unionBox, type Size, type ViewT } from "./plan/viewport";

/**
 * The plan figure for the report (F7, ADR 0016), drawn by the workstation's own renderer:
 * - a second `PlanRenderer` (the plan's WebGL layer: surfaces, keep-outs, modules, obstacles);
 * - the plan overlay functions: `drawElectricalOverlay` and `drawEntityLabels`;
 * - a north arrow and a scale bar, as on the plan.
 * The three layers are composited into one PNG, framed to the whole design.
 */
export interface PlanFigureInput {
  entities: readonly Entity[];
  modules: readonly ModuleShape[];
  strings: readonly OverlayString[];
  /** Colour modules by MPPT and draw strings, as in the electrical step. */
  electrical: boolean;
  size: Size;
  /** Device pixel ratio of the image; 2 gives a print-quality figure. */
  dpr?: number;
  labels: { north: string; draft: string; /** A line written into the figure, bottom right (overlay caption). */ note?: string };
  /** UXF1 (U2-15): the user's calibrated image overlay, drawn under the design (never provider tiles). */
  overlay?: import("../imagery/overlayImage").FigureOverlay | null;
  /** Frame to this view instead of the whole design (the parity test uses the plan's own view). */
  view?: ViewT;
  /** Only the WebGL layer, on a transparent background (the parity test). */
  glOnly?: boolean;
}

export interface PlanFigure {
  png: string;
  width: number;
  height: number;
  /** Metres per CSS pixel at the figure's scale, for the caption. */
  metresPerPx: number;
}

function drawBase(ctx: CanvasRenderingContext2D, size: Size): void {
  ctx.fillStyle = token("role-stage-bg");
  ctx.fillRect(0, 0, size.w, size.h);
}

function drawFurniture(ctx: CanvasRenderingContext2D, size: Size, scale: number, north: string): void {
  const text = token("role-stage-text");
  // North arrow, top right (true north up, as on the plan).
  const x = size.w - 28;
  const y = 30;
  ctx.fillStyle = text;
  ctx.beginPath();
  ctx.moveTo(x, y - 14);
  ctx.lineTo(x + 7, y + 12);
  ctx.lineTo(x, y + 7);
  ctx.lineTo(x - 7, y + 12);
  ctx.closePath();
  ctx.fill();
  ctx.font = drawingFont(12);
  ctx.textAlign = "center";
  ctx.textBaseline = "bottom";
  ctx.fillText("N", x, y - 16);
  ctx.textAlign = "right";
  ctx.textBaseline = "top";
  ctx.fillStyle = token("role-stage-muted");
  ctx.fillText(north, size.w - 12, y + 18);
  // Scale bar, bottom left.
  const metres = niceStep(120 / scale);
  const px = metres * scale;
  ctx.strokeStyle = text;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(16, size.h - 18);
  ctx.lineTo(16 + px, size.h - 18);
  ctx.moveTo(16, size.h - 23);
  ctx.lineTo(16, size.h - 13);
  ctx.moveTo(16 + px, size.h - 23);
  ctx.lineTo(16 + px, size.h - 13);
  ctx.stroke();
  ctx.fillStyle = text;
  ctx.textAlign = "left";
  ctx.textBaseline = "bottom";
  ctx.fillText(`${metres} m`, 16, size.h - 26);
}

export function renderPlanFigure(input: PlanFigureInput): PlanFigure {
  const dpr = input.dpr ?? 2;
  const size = input.size;
  const visible = input.entities.filter((e) => !e.hidden).map((e) => e.polygon);
  const moduleBox = input.modules.length ? bounds(input.modules.map((m) => m.polygon)) : null;
  const box = unionBox(visible.length ? bounds(visible) : null, moduleBox) ?? { minX: -10, minY: -10, maxX: 10, maxY: 10 };
  const view = input.view ?? fitView(box, size, 48);
  const toScreen = (p: Vec2): Vec2 => screenOf(view, size, p);

  const out = document.createElement("canvas");
  out.width = Math.round(size.w * dpr);
  out.height = Math.round(size.h * dpr);
  const ctx = out.getContext("2d")!;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  if (!input.glOnly) drawBase(ctx, size);
  if (!input.glOnly && input.overlay) {
    // Same placement as the plan canvas: offset in metres, rotation clockwise, scale in metres per image pixel.
    const t = input.overlay.transform;
    const o = toScreen(t.offset);
    ctx.save();
    ctx.globalAlpha = input.overlay.opacity;
    ctx.translate(o[0], o[1]);
    ctx.rotate((-t.rotationDeg * Math.PI) / 180);
    ctx.drawImage(input.overlay.image, 0, 0, input.overlay.width * t.sx * view.scale, input.overlay.height * t.sy * view.scale);
    ctx.restore();
  }

  // WebGL layer: the plan's renderer on an off-screen canvas, read back right after the frame.
  const glCanvas = document.createElement("canvas");
  const gl = new PlanRenderer(glCanvas);
  try {
    gl.setSize(size, dpr);
    gl.setView(view);
    gl.setEntities(input.entities);
    gl.setModules(input.modules);
    gl.setModuleLooks(input.electrical, new Set());
    gl.renderNow();
    ctx.drawImage(glCanvas, 0, 0, size.w, size.h);
  } finally {
    gl.dispose();
  }

  if (input.glOnly) return { png: out.toDataURL("image/png"), width: size.w, height: size.h, metresPerPx: 1 / view.scale };

  // Overlay: the plan's own lettering and string drawing.
  if (input.electrical) {
    const centres = new Map(input.modules.map((m) => [m.id, centroid(m.polygon)] as const));
    drawElectricalOverlay({ ctx, toScreen, scale: view.scale, centres, strings: input.strings, highlighted: new Set(), path: [], pathCursor: null, lasso: [] });
  }
  if (view.scale > 6) drawEntityLabels(ctx, input.entities, toScreen, input.labels.draft);
  drawFurniture(ctx, size, view.scale, input.labels.north);
  if (input.labels.note) {
    ctx.font = drawingFont(11);
    ctx.textAlign = "right";
    ctx.textBaseline = "bottom";
    ctx.fillStyle = token("role-stage-muted");
    ctx.fillText(input.labels.note, size.w - 12, size.h - 10);
  }

  return { png: out.toDataURL("image/png"), width: size.w, height: size.h, metresPerPx: 1 / view.scale };
}
