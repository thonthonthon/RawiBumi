import type { Vec2 } from "../../geometry";
import type { ModuleShape } from "../../state/store";

/**
 * Synthetic module layout for renderer performance checks only (`?synthetic=100000`
 * in demo mode). It is not a placement result and never reaches the engine.
 *
 * Tables of 2 × 14 portrait modules (1.134 × 2.278 m, about 600 Wp), 5 cm gaps,
 * 4 m row pitch, laid out in a square block and rotated 7° so module edges are
 * not axis-aligned, as on a real site.
 */
export function syntheticModules(count: number): ModuleShape[] {
  const w = 1.134;
  const h = 2.278;
  const gap = 0.05;
  const perTable = 28;
  const tableW = 14 * (w + gap);
  const tableH = 2 * (h + gap);
  const pitchX = tableW + 1.5;
  const pitchY = tableH + 4;
  const tables = Math.ceil(count / perTable);
  const cols = Math.max(1, Math.round(Math.sqrt((tables * pitchY) / pitchX)));
  const rot = (7 * Math.PI) / 180;
  const c = Math.cos(rot);
  const s = Math.sin(rot);
  const r = (x: number, y: number): Vec2 => [x * c - y * s, x * s + y * c];
  const out: ModuleShape[] = [];
  for (let t = 0; t < tables && out.length < count; t++) {
    const tx = (t % cols) * pitchX;
    const ty = Math.floor(t / cols) * pitchY;
    for (let k = 0; k < perTable && out.length < count; k++) {
      const x = tx + (k % 14) * (w + gap);
      const y = ty + Math.floor(k / 14) * (h + gap);
      const n = out.length;
      const string = Math.floor(n / 16);
      out.push({
        id: `syn-${n}`,
        fieldId: "syn-field",
        polygon: [r(x, y), r(x + w, y), r(x + w, y + h), r(x, y + h)],
        stringId: `S${string + 1}`,
        // Leave every 23rd string unassigned so the hatch is exercised.
        mpptKey: string % 23 === 22 ? null : `syn-inv-${Math.floor(string / 12)}#${string % 4}`
      });
    }
  }
  return out;
}

/** Module count requested with `?synthetic=N` (demo builds only), else null. */
export function syntheticCount(search: string): number | null {
  const v = new URLSearchParams(search).get("synthetic");
  if (v === null) return null;
  const n = Math.round(Number(v));
  return Number.isFinite(n) && n > 0 ? Math.min(n, 250_000) : null;
}
