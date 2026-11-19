import type { Vec2 } from "../../geometry";

/** Plan view: world point at the centre of the stage and the zoom in pixels per metre. */
export interface ViewT {
  cx: number;
  cy: number;
  scale: number;
}

export interface Size {
  w: number;
  h: number;
}

export interface Box {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export const MIN_SCALE = 0.02;
export const MAX_SCALE = 400;

/** World metres (X east, Y north) to stage pixels (Y down). */
export function toScreen(view: ViewT, size: Size, p: Vec2): Vec2 {
  return [(p[0] - view.cx) * view.scale + size.w / 2, size.h / 2 - (p[1] - view.cy) * view.scale];
}

/** Stage pixels to world metres. */
export function toWorld(view: ViewT, size: Size, s: Vec2): Vec2 {
  return [(s[0] - size.w / 2) / view.scale + view.cx, (size.h / 2 - s[1]) / view.scale + view.cy];
}

/** World box visible on the stage. */
export function visibleBox(view: ViewT, size: Size): Box {
  const hw = size.w / 2 / view.scale;
  const hh = size.h / 2 / view.scale;
  return { minX: view.cx - hw, maxX: view.cx + hw, minY: view.cy - hh, maxY: view.cy + hh };
}

/** View that shows the whole box with a margin of `pad` pixels on every side. */
export function fitView(box: Box, size: Size, pad = 60): ViewT {
  const w = Math.max(box.maxX - box.minX, 4);
  const h = Math.max(box.maxY - box.minY, 4);
  const scale = Math.min((size.w - 2 * pad) / w, (size.h - 2 * pad) / h);
  return { cx: (box.minX + box.maxX) / 2, cy: (box.minY + box.maxY) / 2, scale: clampScale(scale) };
}

/** Zoom by factor `k` keeping the world point under screen point `s` fixed. */
export function zoomAt(view: ViewT, size: Size, s: Vec2, k: number): ViewT {
  const before = toWorld(view, size, s);
  const scale = clampScale(view.scale * k);
  return { cx: before[0] - (s[0] - size.w / 2) / scale, cy: before[1] - (size.h / 2 - s[1]) / scale, scale };
}

export function clampScale(scale: number): number {
  if (!Number.isFinite(scale)) return 18;
  return Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale));
}

/** Round step for grid lines and the scale bar: the smallest of 0.1, 0.2, 0.5, 1, 2, 5… at or above the input. */
export function niceStep(metres: number): number {
  const steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000];
  return steps.find((s) => s >= metres) ?? 10000;
}

/** Union of boxes; null when every input is empty. */
export function unionBox(...boxes: Array<Box | null>): Box | null {
  let out: Box | null = null;
  for (const b of boxes) {
    if (!b || !Number.isFinite(b.minX)) continue;
    out = out ? { minX: Math.min(out.minX, b.minX), minY: Math.min(out.minY, b.minY), maxX: Math.max(out.maxX, b.maxX), maxY: Math.max(out.maxY, b.maxY) } : { ...b };
  }
  return out;
}
