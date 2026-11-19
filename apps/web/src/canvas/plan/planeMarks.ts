import { centroid, planeZ, type PlaneDef, type Vec2 } from "../../geometry";

export interface PlaneMarks {
  /** Index of the reference edge (edge-tilt planes only). */
  referenceEdge: number | null;
  /** Downhill arrow in world metres, from the centroid; null on a flat plane. */
  arrow: { from: Vec2; to: Vec2 } | null;
  /** The highest and lowest vertex, from the same plane maths as the Inspector's Z column. */
  high: Vec2 | null;
  low: Vec2 | null;
}

const FLAT_M = 1e-6;

/** What the plan draws for a roof's plane (UX2, U6). Pure; uses planeZ, so the plan and the Inspector agree. */
export function planeMarks(poly: Vec2[], plane: PlaneDef): PlaneMarks {
  const referenceEdge = plane.mode === "edge_tilt" && plane.edgeIndex >= 0 && plane.edgeIndex < poly.length ? plane.edgeIndex : null;
  const none = { referenceEdge, arrow: null, high: null, low: null };
  if (plane.mode === "flat" || poly.length < 3 || !(plane.tilt_deg > 0)) return none;
  const zs = poly.map((p) => planeZ(poly, plane, p));
  if (zs.some((z) => z === null)) return none;
  const values = zs as number[];
  const max = Math.max(...values), min = Math.min(...values);
  if (max - min < FLAT_M) return none;
  const c = centroid(poly);
  const z0 = planeZ(poly, plane, c)!;
  // Finite difference of the plane at the centroid; the downhill direction is minus the gradient.
  const h = 0.01;
  const gx = (planeZ(poly, plane, [c[0] + h, c[1]])! - z0) / h;
  const gy = (planeZ(poly, plane, [c[0], c[1] + h])! - z0) / h;
  const g = Math.hypot(gx, gy);
  const span = Math.max(...poly.map((p) => Math.hypot(p[0] - c[0], p[1] - c[1])));
  const arrow = g > 0 ? { from: c, to: [c[0] - (gx / g) * span * 0.4, c[1] - (gy / g) * span * 0.4] as Vec2 } : null;
  return { referenceEdge, arrow, high: poly[values.indexOf(max)], low: poly[values.indexOf(min)] };
}
