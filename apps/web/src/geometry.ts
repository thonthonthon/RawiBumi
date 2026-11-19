export type Vec2 = [number, number];

export const DEG = Math.PI / 180;

export function add(a: Vec2, b: Vec2): Vec2 {
  return [a[0] + b[0], a[1] + b[1]];
}
export function sub(a: Vec2, b: Vec2): Vec2 {
  return [a[0] - b[0], a[1] - b[1]];
}
export function len(a: Vec2): number {
  return Math.hypot(a[0], a[1]);
}
export function dist(a: Vec2, b: Vec2): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

/** Signed area (m²). Positive = counter-clockwise. */
export function signedArea(poly: Vec2[]): number {
  let s = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    s += x1 * y2 - x2 * y1;
  }
  return s / 2;
}

export function area(poly: Vec2[], holes: Vec2[][] = []): number {
  return Math.abs(signedArea(poly)) - holes.reduce((t, h) => t + Math.abs(signedArea(h)), 0);
}

export function perimeter(poly: Vec2[]): number {
  let p = 0;
  for (let i = 0; i < poly.length; i++) p += dist(poly[i], poly[(i + 1) % poly.length]);
  return p;
}

export function centroid(poly: Vec2[]): Vec2 {
  const a = signedArea(poly);
  if (Math.abs(a) < 1e-12) {
    const n = poly.length || 1;
    return [poly.reduce((s, p) => s + p[0], 0) / n, poly.reduce((s, p) => s + p[1], 0) / n];
  }
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i];
    const [x2, y2] = poly[(i + 1) % poly.length];
    const f = x1 * y2 - x2 * y1;
    cx += (x1 + x2) * f;
    cy += (y1 + y2) * f;
  }
  return [cx / (6 * a), cy / (6 * a)];
}

export function bounds(polys: Vec2[][]) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const poly of polys)
    for (const [x, y] of poly) {
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
  if (!Number.isFinite(minX)) return { minX: -15, minY: -10, maxX: 15, maxY: 10 };
  return { minX, minY, maxX, maxY };
}

export function pointInPolygon(p: Vec2, poly: Vec2[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function pointInShape(p: Vec2, poly: Vec2[], holes: Vec2[][] = []): boolean {
  return pointInPolygon(p, poly) && !holes.some((h) => pointInPolygon(p, h));
}

export function distToSegment(p: Vec2, a: Vec2, b: Vec2): number {
  const ab = sub(b, a);
  const l2 = ab[0] * ab[0] + ab[1] * ab[1];
  if (l2 === 0) return dist(p, a);
  let t = ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / l2;
  t = Math.max(0, Math.min(1, t));
  return dist(p, [a[0] + t * ab[0], a[1] + t * ab[1]]);
}

/** Perpendicular distance from p to the infinite line through a–b (horizontal plane). */
export function distToLine(p: Vec2, a: Vec2, b: Vec2): number {
  const ab = sub(b, a);
  const l = len(ab);
  if (l === 0) return dist(p, a);
  return Math.abs(ab[0] * (a[1] - p[1]) - (a[0] - p[0]) * ab[1]) / l;
}

function segmentsIntersect(p1: Vec2, p2: Vec2, p3: Vec2, p4: Vec2): boolean {
  const d = (a: Vec2, b: Vec2, c: Vec2) => (c[0] - a[0]) * (b[1] - a[1]) - (b[0] - a[0]) * (c[1] - a[1]);
  const d1 = d(p3, p4, p1);
  const d2 = d(p3, p4, p2);
  const d3 = d(p1, p2, p3);
  const d4 = d(p1, p2, p4);
  return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
}

export interface PolygonIssue {
  code: "too_few_vertices" | "self_intersection" | "short_edge" | "duplicate_vertex";
  message: string;
}

/** Fail-closed polygon validation (UI spec §6.3). */
export function validatePolygon(poly: Vec2[], minEdgeM = 0.05): PolygonIssue[] {
  const issues: PolygonIssue[] = [];
  if (poly.length < 3) {
    issues.push({ code: "too_few_vertices", message: "A polygon needs at least 3 vertices." });
    return issues;
  }
  const n = poly.length;
  for (let i = 0; i < n; i++) {
    const l = dist(poly[i], poly[(i + 1) % n]);
    if (l < 1e-6) issues.push({ code: "duplicate_vertex", message: `Vertices ${i + 1} and ${((i + 1) % n) + 1} coincide.` });
    else if (l < minEdgeM)
      issues.push({ code: "short_edge", message: `Edge ${i + 1} is ${(l * 1000).toFixed(0)} mm, below the ${minEdgeM * 1000} mm minimum.` });
  }
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (Math.abs(i - j) <= 1 || (i === 0 && j === n - 1)) continue;
      if (segmentsIntersect(poly[i], poly[(i + 1) % n], poly[j], poly[(j + 1) % n])) {
        issues.push({ code: "self_intersection", message: `Edges ${i + 1} and ${j + 1} cross.` });
        return issues;
      }
    }
  }
  return issues;
}

export function rotatePoly(poly: Vec2[], pivot: Vec2, deg: number): Vec2[] {
  const c = Math.cos(deg * DEG);
  const s = Math.sin(deg * DEG);
  return poly.map(([x, y]) => {
    const dx = x - pivot[0];
    const dy = y - pivot[1];
    return [pivot[0] + dx * c - dy * s, pivot[1] + dx * s + dy * c];
  });
}

export function translatePoly(poly: Vec2[], d: Vec2): Vec2[] {
  return poly.map((p) => add(p, d));
}

export function scalePoly(poly: Vec2[], pivot: Vec2, sx: number, sy = sx): Vec2[] {
  return poly.map(([x, y]) => [pivot[0] + (x - pivot[0]) * sx, pivot[1] + (y - pivot[1]) * sy]);
}

/** Angle of a→b measured clockwise from north (Y+), degrees 0–360. */
export function bearingDeg(a: Vec2, b: Vec2): number {
  const d = Math.atan2(b[0] - a[0], b[1] - a[1]) / DEG;
  return (d + 360) % 360;
}

// ---------------------------------------------------------------------------
// Plane definitions and automatic height (UI spec §6.4). Browser PREVIEW only:
// canonical Z is derived by the engine on commit.
// ---------------------------------------------------------------------------

/** Vertex letters shared by the Inspector and the plan: A…Z, then V27, V28… */
export function vertexLabel(i: number): string {
  return i < 26 ? String.fromCharCode(65 + i) : `V${i + 1}`;
}

export type PlaneDef =
  | { mode: "flat"; z_m: number }
  | { mode: "edge_tilt"; edgeIndex: number; zRef_m: number; tilt_deg: number; direction: "down" | "up" }
  | { mode: "datum_tilt_azimuth"; datum: Vec2; z_m: number; tilt_deg: number; slopeAzimuth_deg: number };

/** The plane with `edgeIndex` as reference edge: keeps an edge-tilt plane's values, else the Inspector's defaults. */
export function referenceEdgePlane(plane: PlaneDef, edgeIndex: number): PlaneDef {
  if (plane.mode === "edge_tilt") return { ...plane, edgeIndex };
  return { mode: "edge_tilt", edgeIndex, zRef_m: plane.mode === "flat" ? plane.z_m : 8, tilt_deg: 5, direction: "down" };
}

/** Z of a point in the plane. Returns null if the definition is incomplete. */
export function planeZ(poly: Vec2[], plane: PlaneDef, p: Vec2): number | null {
  if (plane.mode === "flat") return plane.z_m;
  if (plane.mode === "edge_tilt") {
    const n = poly.length;
    if (n < 3 || plane.edgeIndex < 0 || plane.edgeIndex >= n) return null;
    const a = poly[plane.edgeIndex];
    const b = poly[(plane.edgeIndex + 1) % n];
    // Sign: which side of AB the polygon interior lies on.
    const c = centroid(poly);
    const cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    const pCross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
    const side = Math.sign(pCross) === Math.sign(cross) || pCross === 0 ? 1 : -1;
    const s = plane.direction === "down" ? 1 : -1;
    return plane.zRef_m - s * side * distToLine(p, a, b) * Math.tan(plane.tilt_deg * DEG);
  }
  // datum + tilt + azimuth of downslope direction (clockwise from north)
  const az = plane.slopeAzimuth_deg * DEG;
  const down: Vec2 = [Math.sin(az), Math.cos(az)];
  const d = (p[0] - plane.datum[0]) * down[0] + (p[1] - plane.datum[1]) * down[1];
  return plane.z_m - d * Math.tan(plane.tilt_deg * DEG);
}

/** Angle between two module normals given tilt/azimuth (deg). UI spec §6.8.5. */
export function normalAngleDeg(t1: number, az1: number, t2: number, az2: number): number {
  const c =
    Math.cos(t1 * DEG) * Math.cos(t2 * DEG) + Math.sin(t1 * DEG) * Math.sin(t2 * DEG) * Math.cos((az1 - az2) * DEG);
  return Math.acos(Math.max(-1, Math.min(1, c))) / DEG;
}


export type EngineElevationReference = { mode: "boundary_centroid" } | { mode: "explicit_xy"; x_m: number; y_m: number };
export interface EnginePlaneDefinition {
  slope_deg: number; azimuth_deg: number; base_elevation_m: number;
  elevation_reference: EngineElevationReference | null;
}

/** Exact canonical-plane parameters; planeZ remains the preview authority. */
export function uiPlaneToEngine(poly: Vec2[], plane: PlaneDef): EnginePlaneDefinition {
  if (plane.mode === "flat") return { slope_deg: 0, azimuth_deg: 0, base_elevation_m: plane.z_m, elevation_reference: null };
  if (plane.mode === "datum_tilt_azimuth") return { slope_deg: plane.tilt_deg, azimuth_deg: plane.slopeAzimuth_deg,
    base_elevation_m: plane.z_m, elevation_reference: { mode: "explicit_xy", x_m: plane.datum[0], y_m: plane.datum[1] } };
  const a = poly[plane.edgeIndex], b = poly[(plane.edgeIndex + 1) % poly.length];
  if (!a || !b) throw new Error("Choose a valid reference edge.");
  const c = centroid(poly), dx = b[0] - a[0], dy = b[1] - a[1];
  const cross = dx * (c[1] - a[1]) - dy * (c[0] - a[0]);
  if (cross === 0 && plane.tilt_deg !== 0) {
    const error = new Error("Choose another reference edge, or use datum + tilt + azimuth.");
    error.name = "AmbiguousEdgePlaneError"; throw error;
  }
  const sign = (plane.direction === "down" ? 1 : -1) * Math.sign(cross);
  const azimuth = (Math.atan2(-dy * sign, dx * sign) / DEG + 360) % 360;
  return { slope_deg: plane.tilt_deg, azimuth_deg: azimuth, base_elevation_m: plane.zRef_m,
    elevation_reference: { mode: "explicit_xy", x_m: (a[0] + b[0]) / 2, y_m: (a[1] + b[1]) / 2 } };
}

export function enginePlaneToUi(poly: Vec2[], surface: Partial<EnginePlaneDefinition>, preferred?: PlaneDef): PlaneDef {
  const reference = surface.elevation_reference;
  const canonical: PlaneDef = (surface.slope_deg ?? 0) === 0
    ? { mode: "flat", z_m: surface.base_elevation_m ?? 0 }
    : { mode: "datum_tilt_azimuth", datum: reference?.mode === "explicit_xy" ? [reference.x_m, reference.y_m] : centroid(poly),
        z_m: surface.base_elevation_m ?? 0, tilt_deg: surface.slope_deg ?? 0, slopeAzimuth_deg: surface.azimuth_deg ?? 0 };
  // Preserve the user's equivalent edge/datum representation after the response.
  if (preferred && preferred.mode !== "flat" && canonical.mode !== "flat"
      && poly.every(p => Math.abs((planeZ(poly, preferred, p) ?? Infinity) - (planeZ(poly, canonical, p) ?? -Infinity)) <= 1e-9)) return preferred;
  return canonical;
}
