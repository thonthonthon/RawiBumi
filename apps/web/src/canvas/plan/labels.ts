import { bounds, type Vec2 } from "../../geometry";
import type { Entity } from "../../state/store";
import { drawingFont, token } from "../../ui/palette";

/**
 * Entity names on the plan overlay (osifont), shared by the workstation plan and the
 * exported plan figure (ADR 0016), so both letter the drawing the same way.
 */
export function drawEntityLabels(ctx: CanvasRenderingContext2D, entities: readonly Entity[], toScreen: (p: Vec2) => Vec2, draftSuffix: string): void {
  ctx.font = drawingFont(12);
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  for (const e of entities) {
    if (e.hidden || e.kind === "keepout") continue;
    const b = bounds([e.polygon]);
    const s = toScreen([b.minX, b.maxY]);
    const label = e.source === "draft" ? `${e.name} · ${draftSuffix}` : e.name;
    ctx.fillStyle = e.kind === "obstacle" ? token("color-chalk-300") : e.source === "draft" ? token("role-warning-glyph") : token("role-stage-text");
    if (e.kind === "obstacle") ctx.fillText(label, s[0], s[1] - 16);
    else ctx.fillText(label, s[0] + 6, s[1] + 5);
  }
}
