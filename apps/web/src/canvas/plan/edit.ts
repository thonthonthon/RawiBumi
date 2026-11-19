import type { ReferenceAnchor } from "../../types";
import type { Vec2 } from "../../geometry";

/**
 * Exact edits, ported from the engine (geometry/scene/geometry2d.py) so a
 * typed edit gives the same vertices in the browser as in the engine. The
 * parity test (tests/unit/edit.test.ts) runs both on one fixture
 * (scripts/gen-edit-fixture.py).
 */

const EPSILON = 1e-9;
const RAD = Math.PI / 180;

export type Preserve = "start" | "end" | "midpoint" | "rectangle";

export function isRectangle(ring: readonly Vec2[]): boolean {
  if (ring.length !== 4) return false;
  const unitEdges = ring.map((p, i) => {
    const q = ring[(i + 1) % 4];
    const size = Math.hypot(q[0] - p[0], q[1] - p[1]);
    return size > EPSILON ? [(q[0] - p[0]) / size, (q[1] - p[1]) / size] : [NaN, NaN];
  });
  return unitEdges.every(([x, y], i) => {
    const [nx, ny] = unitEdges[(i + 1) % 4];
    return Math.abs(x * nx + y * ny) <= EPSILON;
  });
}

/** rotate_points_clockwise: positive angles turn clockwise seen from above. */
export function rotateClockwise(points: readonly Vec2[], origin: Vec2, angleDeg: number): Vec2[] {
  const a = angleDeg * RAD;
  const c = Math.cos(a);
  const s = Math.sin(a);
  return points.map(([x, y]) => {
    const dx = x - origin[0];
    const dy = y - origin[1];
    return [origin[0] + dx * c + dy * s, origin[1] - dx * s + dy * c];
  });
}

function edgeIndices(count: number, edge: number, closed: boolean): [number, number] {
  const edges = closed ? count : count - 1;
  if (edge < 0 || edge >= edges) throw new RangeError("edge_index is outside geometry");
  return [edge, (edge + 1) % count];
}

/** set_edge_length. */
export function setEdgeLength(vertices: readonly Vec2[], edge: number, lengthM: number, preserve: Preserve = "start", closed = true): Vec2[] {
  if (!Number.isFinite(lengthM) || lengthM <= 0) throw new RangeError("length_m must be positive");
  const pts = vertices.map((p) => [p[0], p[1]] as Vec2);
  const [si, ei] = edgeIndices(pts.length, edge, closed);
  if (preserve === "rectangle" && (!closed || !isRectangle(pts))) throw new RangeError("preserve rectangle needs a rectangle");
  const a = pts[si];
  const b = pts[ei];
  const cur = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (cur <= EPSILON) throw new RangeError("cannot edit dimension of zero-length edge");
  const ux = (b[0] - a[0]) / cur;
  const uy = (b[1] - a[1]) / cur;
  if (preserve === "start") pts[ei] = [a[0] + ux * lengthM, a[1] + uy * lengthM];
  else if (preserve === "end") pts[si] = [b[0] - ux * lengthM, b[1] - uy * lengthM];
  else if (preserve === "midpoint") {
    const m: Vec2 = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const h = lengthM / 2;
    pts[si] = [m[0] - ux * h, m[1] - uy * h];
    pts[ei] = [m[0] + ux * h, m[1] + uy * h];
  } else if (preserve === "rectangle") {
    const dx = (lengthM - cur) * ux;
    const dy = (lengthM - cur) * uy;
    for (const i of [ei, (edge + 2) % 4]) pts[i] = [pts[i][0] + dx, pts[i][1] + dy];
  } else throw new RangeError("preserve must be start, end, midpoint, or rectangle");
  return pts;
}

/** set_edge_azimuth: the edge's bearing, 0° north, clockwise. */
export function setEdgeAzimuth(vertices: readonly Vec2[], edge: number, azimuthDeg: number, preserve: Preserve = "start", closed = true): Vec2[] {
  const pts = vertices.map((p) => [p[0], p[1]] as Vec2);
  const [si, ei] = edgeIndices(pts.length, edge, closed);
  const a = pts[si];
  const b = pts[ei];
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (len <= EPSILON) throw new RangeError("cannot edit angle of zero-length edge");
  const az = (((azimuthDeg % 360) + 360) % 360) * RAD;
  const dx = len * Math.sin(az);
  const dy = len * Math.cos(az);
  if (preserve === "start") pts[ei] = [a[0] + dx, a[1] + dy];
  else if (preserve === "end") pts[si] = [b[0] - dx, b[1] - dy];
  else {
    const m: Vec2 = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    pts[si] = [m[0] - dx / 2, m[1] - dy / 2];
    pts[ei] = [m[0] + dx / 2, m[1] + dy / 2];
  }
  return pts;
}

/** Outward unit normal of edge `edge` of a closed ring (either winding). */
export function edgeNormal(vertices: readonly Vec2[], edge: number): Vec2 {
  const [si, ei] = edgeIndices(vertices.length, edge, true);
  const a = vertices[si];
  const b = vertices[ei];
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (len <= EPSILON) return [0, 0];
  let area = 0;
  for (let i = 0; i < vertices.length; i++) {
    const p = vertices[i];
    const q = vertices[(i + 1) % vertices.length];
    area += p[0] * q[1] - q[0] * p[1];
  }
  // Counter-clockwise rings have the outside on the right of a→b.
  const sign = area >= 0 ? 1 : -1;
  return [(sign * (b[1] - a[1])) / len, (sign * -(b[0] - a[0])) / len];
}

/** Moves edge `edge` along its outward normal by `offsetM` (both of its vertices). */
export function offsetEdge(vertices: readonly Vec2[], edge: number, offsetM: number): Vec2[] {
  const pts = vertices.map((p) => [p[0], p[1]] as Vec2);
  const [si, ei] = edgeIndices(pts.length, edge, true);
  const [nx, ny] = edgeNormal(vertices, edge);
  pts[si] = [pts[si][0] + nx * offsetM, pts[si][1] + ny * offsetM];
  pts[ei] = [pts[ei][0] + nx * offsetM, pts[ei][1] + ny * offsetM];
  return pts;
}

/** First-edge axes and the nine points of the box aligned with them. */
export function ownBox(points: readonly Vec2[], anchor: ReferenceAnchor = { u: "start", v: "start" }) {
  const dx = points[1][0] - points[0][0], dy = points[1][1] - points[0][1];
  const size = Math.hypot(dx, dy);
  const u: Vec2 = [dx / size, dy / size], v: Vec2 = [-u[1], u[0]];
  const us = points.map(p => p[0] * u[0] + p[1] * u[1]);
  const vs = points.map(p => p[0] * v[0] + p[1] * v[1]);
  const length = Math.max(...us) - Math.min(...us), width = Math.max(...vs) - Math.min(...vs);
  const fraction = { start: 0, center: 0.5, end: 1 };
  const a = Math.min(...us) + fraction[anchor.u] * length, b = Math.min(...vs) + fraction[anchor.v] * width;
  const point: Vec2 = [a * u[0] + b * v[0], a * u[1] + b * v[1]];
  return { u, v, point, length, width, bearing: (Math.atan2(u[0], u[1]) / RAD + 360) % 360 };
}

export function ownAxesDelta(points: readonly Vec2[], dx: number, dy: number): Vec2 {
  const { u, v } = ownBox(points);
  return [dx * u[0] + dy * v[0], dx * u[1] + dy * v[1]];
}

export function anchoredRectangle(points: readonly Vec2[], edge: number, length: number, anchor?: ReferenceAnchor): Vec2[] {
  const updated = setEdgeLength(points, edge, length, "rectangle");
  const before = ownBox(points, anchor).point, after = ownBox(updated, anchor).point;
  return updated.map(p => [p[0] + before[0] - after[0], p[1] + before[1] - after[1]]);
}
