import type { Vec2 } from "../geometry";

/** A1: enclosing the box alone never selects a polygon. All bounds are world metres. */
export function boxSelect(polygon: readonly Vec2[], start: Vec2, end: Vec2, crossing: boolean): boolean {
  if (polygon.length < 3) return false;
  const minX = Math.min(start[0], end[0]), maxX = Math.max(start[0], end[0]);
  const minY = Math.min(start[1], end[1]), maxY = Math.max(start[1], end[1]);
  if (polygon.every(([x, y]) => x > minX && x < maxX && y > minY && y < maxY)) return true;
  if (!crossing) return false;
  const corners: Vec2[] = [[minX, minY], [maxX, minY], [maxX, maxY], [minX, maxY]];
  return polygon.some((a, i) => corners.some((c, j) => intersects(a, polygon[(i + 1) % polygon.length], c, corners[(j + 1) % 4])));
}

function intersects(a: Vec2, b: Vec2, c: Vec2, d: Vec2): boolean {
  if (Math.max(a[0], b[0]) < Math.min(c[0], d[0]) || Math.max(c[0], d[0]) < Math.min(a[0], b[0]) ||
      Math.max(a[1], b[1]) < Math.min(c[1], d[1]) || Math.max(c[1], d[1]) < Math.min(a[1], b[1])) return false;
  const cross = (p: Vec2, q: Vec2, r: Vec2) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  const opposite = (x: number, y: number) => x === 0 || y === 0 || (x < 0) !== (y < 0);
  return opposite(cross(a, b, c), cross(a, b, d)) && opposite(cross(c, d, a), cross(c, d, b));
}
