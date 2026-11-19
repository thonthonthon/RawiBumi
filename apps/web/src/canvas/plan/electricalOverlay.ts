import type { Vec2 } from "../../geometry";
import { worstCheck, type LiveCheck } from "../../engine/topology";
import type { ModuleShape } from "../../state/store";
import type { ProjectView } from "../../types";
import { alpha, drawingFont, mpptColor, token } from "../../ui/palette";

/**
 * Electrical lens on the plan overlay (DESIGN.md §6, B6):
 * - each string as a polyline in wiring order, + at the start and – at the end,
 *   in its MPPT's colour (muted when unassigned);
 * - its id at the start with the worst live check as a glyph (engine checks only);
 * - the string path being drawn, the lasso, the first string of a join, and the module picked by Move or Swap.
 * Polylines appear from 4 px per metre, labels from 10 px per metre.
 */
export interface OverlayString {
  id: string;
  modules: readonly string[];
  mpptIndex: number | null;
  worst: LiveCheck["state"] | null;
}

export interface ElectricalOverlayInput {
  ctx: CanvasRenderingContext2D;
  toScreen: (p: Vec2) => Vec2;
  scale: number;
  centres: ReadonlyMap<string, Vec2>;
  strings: readonly OverlayString[];
  highlighted: ReadonlySet<string>;
  path: readonly string[];
  pathCursor: Vec2 | null;
  lasso: readonly Vec2[];
  /** S14a: the module picked by the first click of Move module or Swap modules. */
  picked?: string | null;
}

function glyph(ctx: CanvasRenderingContext2D, x: number, y: number, state: LiveCheck["state"]) {
  if (state === "fail") {
    ctx.fillStyle = token("role-error-glyph");
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = token("role-stage-deep");
    ctx.fillRect(x - 0.8, y - 3, 1.6, 3.6);
    ctx.fillRect(x - 0.8, y + 1.6, 1.6, 1.4);
  } else if (state === "warn") {
    ctx.fillStyle = token("role-warning-glyph");
    ctx.beginPath();
    ctx.moveTo(x, y - 5.5);
    ctx.lineTo(x + 5.5, y + 4.5);
    ctx.lineTo(x - 5.5, y + 4.5);
    ctx.closePath();
    ctx.fill();
  }
}

export function drawElectricalOverlay(o: ElectricalOverlayInput): void {
  const { ctx, toScreen, scale, centres } = o;
  ctx.save();
  ctx.lineJoin = "round";
  ctx.lineCap = "round";

  if (scale > 4)
    for (const s of o.strings) {
      const pts = s.modules.map((id) => centres.get(id)).filter(Boolean) as Vec2[];
      if (!pts.length) continue;
      const colour = s.mpptIndex === null ? token("role-stage-muted") : mpptColor(s.mpptIndex);
      const hi = o.highlighted.has(s.id);
      ctx.strokeStyle = hi ? token("role-selection") : colour;
      ctx.lineWidth = hi ? 2.5 : 1.25;
      ctx.beginPath();
      pts.forEach((p, i) => {
        const q = toScreen(p);
        if (i === 0) ctx.moveTo(q[0], q[1]);
        else ctx.lineTo(q[0], q[1]);
      });
      ctx.stroke();
      if (scale > 10) {
        const a = toScreen(pts[0]);
        const b = toScreen(pts[pts.length - 1]);
        ctx.font = drawingFont(11);
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = token("role-stage-text");
        ctx.fillText("+", a[0] - 7, a[1] - 7);
        ctx.fillText("–", b[0] + 7, b[1] - 7);
        const w = Math.max(24, ctx.measureText(s.id).width + 8) + (s.worst === "fail" || s.worst === "warn" ? 13 : 0);
        ctx.fillStyle = token("role-stage-deep");
        ctx.fillRect(a[0] - w / 2, a[1] + 6, w, 15);
        ctx.fillStyle = hi ? token("role-selection") : token("role-stage-text");
        ctx.fillText(s.id, a[0] - (w > 24 && (s.worst === "fail" || s.worst === "warn") ? 6 : 0), a[1] + 13.5);
        if (s.worst === "fail" || s.worst === "warn") glyph(ctx, a[0] + w / 2 - 8, a[1] + 13.5, s.worst);
      }
    }

  // The string path being drawn (S): numbered stops and a rubber band to the cursor.
  if (o.path.length) {
    const pts = o.path.map((id) => centres.get(id)).filter(Boolean) as Vec2[];
    ctx.strokeStyle = token("role-selection");
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    pts.forEach((p, i) => {
      const q = toScreen(p);
      if (i === 0) ctx.moveTo(q[0], q[1]);
      else ctx.lineTo(q[0], q[1]);
    });
    if (o.pathCursor) {
      const q = toScreen(o.pathCursor);
      ctx.lineTo(q[0], q[1]);
    }
    ctx.stroke();
    ctx.font = drawingFont(10);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    pts.forEach((p, i) => {
      const q = toScreen(p);
      ctx.fillStyle = token("role-selection");
      ctx.beginPath();
      ctx.arc(q[0], q[1], 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = token("role-stage-deep");
      ctx.fillText(String(i + 1), q[0], q[1] + 0.5);
    });
  }

  // The module picked by Move module (M) or Swap modules (W): a ring until the second click.
  const picked = o.picked ? centres.get(o.picked) : undefined;
  if (picked) {
    const q = toScreen(picked);
    ctx.strokeStyle = token("role-selection");
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.arc(q[0], q[1], 9, 0, Math.PI * 2);
    ctx.stroke();
  }

  // Lasso (L).
  if (o.lasso.length > 1) {
    ctx.beginPath();
    o.lasso.forEach((p, i) => {
      const q = toScreen(p);
      if (i === 0) ctx.moveTo(q[0], q[1]);
      else ctx.lineTo(q[0], q[1]);
    });
    ctx.closePath();
    ctx.fillStyle = alpha("role-selection", 0.12);
    ctx.fill();
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = token("role-selection");
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.restore();
}

/** Strings in wiring order with their MPPT colour index and worst engine check (plan and plan figure). */
export function overlayStringsOf(pview: ProjectView | null, modules: readonly ModuleShape[]): OverlayString[] {
  const design = pview?.bundle.electrical_design;
  if (!design) {
    // Synthetic plan (no project): group by string id in module order.
    const by = new Map<string, OverlayString>();
    for (const m of modules)
      if (m.stringId) {
        const s = by.get(m.stringId) ?? { id: m.stringId, modules: [], mpptIndex: m.mpptKey ? Number(m.mpptKey.split("#")[1]) : null, worst: null };
        (s.modules as string[]).push(m.id);
        by.set(m.stringId, s);
      }
    return [...by.values()];
  }
  const mpptIndex = new Map<string, number>();
  for (const inv of design.inverter_instances) inv.mppt_instance_ids.forEach((m, i) => mpptIndex.set(m, i));
  const checks = new Map((pview?.topology_checks?.strings ?? []).map((c) => [c.string_id, c.checks]));
  return design.strings.map((s) => ({
    id: s.string_id,
    modules: s.module_instance_ids,
    mpptIndex: s.target_mppt_instance_id ? (mpptIndex.get(s.target_mppt_instance_id) ?? null) : null,
    worst: checks.has(s.string_id) ? worstCheck(checks.get(s.string_id)!) : null
  }));
}
