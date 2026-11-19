import { tableFootprint, tableModules, type FillPreview, type TableRecord } from "../../engine/layout";
import type { Vec2 } from "../../geometry";
import { alpha, drawingFont, token } from "../../ui/palette";

/**
 * The PV layout step's overlay on the plan (ADR 0010: previews and markers go on
 * the Canvas 2D layer above the WebGL geometry):
 * - the usable region left by the setbacks, dashed;
 * - table outlines, with pinned tables marked and deleted pinned tables hatched;
 * - the fill preview before Apply, with tables to be removed outlined in red;
 * - tables being dragged.
 */
export interface LayoutOverlayInput {
  ctx: CanvasRenderingContext2D;
  toScreen: (p: Vec2) => Vec2;
  scale: number;
  tables: readonly TableRecord[];
  preview: FillPreview | null;
  /** Tables of the previewed field before the re-fill (to show what goes). */
  previewBefore: readonly TableRecord[];
  dragging: { ids: ReadonlySet<string>; delta: Vec2 } | null;
  labels: { preview: string; pinned: string; removed: string };
}

function path(ctx: CanvasRenderingContext2D, toScreen: (p: Vec2) => Vec2, poly: readonly Vec2[]) {
  ctx.beginPath();
  poly.forEach((p, i) => {
    const s = toScreen(p);
    if (i === 0) ctx.moveTo(s[0], s[1]);
    else ctx.lineTo(s[0], s[1]);
  });
  ctx.closePath();
}

const shift = (poly: readonly Vec2[], d: Vec2): Vec2[] => poly.map((p) => [p[0] + d[0], p[1] + d[1]]);

/** A pin: a small filled circle on a stem, at the table's front-left corner. */
function pinMark(ctx: CanvasRenderingContext2D, at: Vec2) {
  ctx.strokeStyle = token("role-info-on-stage");
  ctx.fillStyle = token("role-info-on-stage");
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(at[0], at[1]);
  ctx.lineTo(at[0] + 5, at[1] - 7);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(at[0] + 6.5, at[1] - 9, 3.2, 0, Math.PI * 2);
  ctx.fill();
}

export function drawLayoutOverlay(o: LayoutOverlayInput): void {
  const { ctx, toScreen, scale } = o;
  ctx.save();

  // Committed tables: outlines once a table is a few pixels across.
  if (scale > 3) {
    for (const t of o.tables) {
      const fp = tableFootprint(t);
      if (t.status === "deleted") {
        path(ctx, toScreen, fp);
        ctx.setLineDash([4, 3]);
        ctx.strokeStyle = token("role-stage-muted");
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.setLineDash([]);
        if (scale > 10) {
          const s = toScreen(fp[0]);
          ctx.font = drawingFont(10);
          ctx.fillStyle = token("role-stage-muted");
          ctx.textAlign = "left";
          ctx.textBaseline = "bottom";
          ctx.fillText(o.labels.removed, s[0] + 3, s[1] - 2);
        }
        continue;
      }
      path(ctx, toScreen, fp);
      ctx.strokeStyle = t.pinned ? token("role-info-on-stage") : alpha("role-stage-text", 0.45);
      ctx.lineWidth = t.pinned ? 1.5 : 1;
      ctx.stroke();
      if (t.pinned) pinMark(ctx, toScreen(fp[0]));
    }
  }

  const p = o.preview;
  if (p) {
    // Usable region after setbacks and keep-out offsets.
    for (const ring of p.usable_region) {
      path(ctx, toScreen, ring);
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = token("role-info-on-stage");
      ctx.lineWidth = 1.25;
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // Tables the re-fill would remove.
    const after = new Set(p.tables.map((t) => t.table_id));
    for (const t of o.previewBefore) {
      if (after.has(t.table_id) || t.status === "deleted") continue;
      path(ctx, toScreen, tableFootprint(t));
      // Dim the modules that go, so the new tables read on top of them.
      ctx.fillStyle = alpha("role-stage-deep", 0.72);
      ctx.fill();
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = token("role-error-glyph");
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // The preview's modules (or table footprints when zoomed far out).
    ctx.fillStyle = alpha("role-valid", 0.28);
    ctx.strokeStyle = token("role-valid");
    ctx.lineWidth = 1;
    for (const t of p.tables) {
      if (t.pinned) continue;
      if (scale > 3) for (const m of tableModules(t)) {
        path(ctx, toScreen, m.polygon);
        ctx.fill();
        ctx.stroke();
      }
      else {
        path(ctx, toScreen, tableFootprint(t));
        ctx.fill();
      }
    }
    // Label above the top-right corner of the usable region (the surface's name sits top-left).
    const ring = p.usable_region[0];
    if (ring?.length) {
      const xs = ring.map((q) => q[0]);
      const ys = ring.map((q) => q[1]);
      const s = toScreen([Math.max(...xs), Math.max(...ys)]);
      ctx.font = drawingFont(11);
      const text = o.labels.preview;
      const w = ctx.measureText(text).width + 10;
      ctx.fillStyle = token("role-stage-deep");
      ctx.fillRect(s[0] - w, s[1] - 30, w, 17);
      ctx.fillStyle = token("role-valid");
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(text, s[0] - w + 5, s[1] - 21.5);
    }
  }

  // Tables being dragged.
  if (o.dragging) {
    for (const t of o.tables) {
      if (!o.dragging.ids.has(t.table_id)) continue;
      path(ctx, toScreen, shift(tableFootprint(t), o.dragging.delta));
      ctx.strokeStyle = token("role-selection");
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }
  ctx.restore();
}
