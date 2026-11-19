/**
 * DEMO MODE ONLY — the demo engine's table-level fill (B5), standing in for the
 * engine's packing until proposal 0003 (Track E: E2, E3, E4) is implemented.
 * The browser itself never runs this outside demo mode.
 *
 * Model, in the field's own frame: u along the rows, v from the front (the side
 * the modules face) to the back. A table is `rows` module rows deep. Inside a
 * table, lengths lie in the tilted module plane and are projected by cos(tilt);
 * between tables, lengths lie on the support surface.
 *
 * Validity of a slot is exact for convex support surfaces: the slot lies inside
 * every edge's setback half-plane, keeps the keep-out offset from each obstacle,
 * and does not overlap a pinned table.
 */
import type { Vec2 } from "../geometry";
import {
  fieldAxes,
  moduleCountOf,
  tableFootprint,
  tableModules,
  type FillPreview,
  type FillZoneRequest,
  type LayoutDiff,
  type LayoutFinding,
  type Orientation,
  type RemovedSlot,
  type TableRecord
} from "../engine/layout";

export interface FillInput {
  surface: Vec2[];
  obstacles: Vec2[][];
  module: { width_m: number; height_m: number };
  request: FillZoneRequest;
  fieldId: string;
  /** Pinned tables of this field, kept as they are and kept clear of. */
  pinned: TableRecord[];
  /** Footprints of other fields' modules on the same surface: fields never overlap. */
  occupied?: Vec2[][];
}

export interface FillResult {
  tables: TableRecord[];
  pitch_m: number;
  usable_region: Vec2[][];
  findings: LayoutFinding[];
}

const EPS = 1e-9;
const RAD = Math.PI / 180;

const dot = (a: Vec2, b: Vec2) => a[0] * b[0] + a[1] * b[1];

function signedArea(poly: readonly Vec2[]): number {
  let s = 0;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i];
    const b = poly[(i + 1) % poly.length];
    s += a[0] * b[1] - b[0] * a[1];
  }
  return s / 2;
}

/** True when every turn of the ring has the same sense (collinear vertices allowed). */
export function isConvex(poly: readonly Vec2[]): boolean {
  let sign = 0;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i];
    const b = poly[(i + 1) % poly.length];
    const c = poly[(i + 2) % poly.length];
    const z = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
    if (Math.abs(z) < 1e-12) continue;
    const s = Math.sign(z);
    if (sign && s !== sign) return false;
    sign = s;
  }
  return true;
}

/** Inward unit normal of edge i of a ring with the given orientation sign. */
function inwardNormal(poly: readonly Vec2[], i: number, ccw: boolean): Vec2 {
  const a = poly[i];
  const b = poly[(i + 1) % poly.length];
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const l = Math.hypot(dx, dy) || 1;
  return ccw ? [-dy / l, dx / l] : [dy / l, -dx / l];
}

/** Clips a convex ring by the half-plane n·p ≥ c (Sutherland–Hodgman). */
function clipHalfPlane(ring: Vec2[], n: Vec2, c: number): Vec2[] {
  const out: Vec2[] = [];
  for (let i = 0; i < ring.length; i++) {
    const p = ring[i];
    const q = ring[(i + 1) % ring.length];
    const fp = dot(n, p) - c;
    const fq = dot(n, q) - c;
    if (fp >= -EPS) out.push(p);
    if ((fp >= -EPS) !== (fq >= -EPS)) {
      const t = fp / (fp - fq);
      out.push([p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])]);
    }
  }
  return out;
}

/**
 * The part of a convex surface at least `setbacks[i]` from the line of each edge i.
 * Empty when the setbacks leave nothing. Shared with the plan's setback preview.
 */
export function setbackRegion(surface: readonly Vec2[], setbacks: readonly number[]): Vec2[] {
  const ccw = signedArea(surface) > 0;
  let ring = surface.slice();
  for (let i = 0; i < surface.length && ring.length >= 3; i++) {
    const n = inwardNormal(surface, i, ccw);
    ring = clipHalfPlane(ring, n, dot(n, surface[i]) + (setbacks[i] ?? 0));
  }
  return ring.length >= 3 && Math.abs(signedArea(ring)) > 1e-9 ? ring : [];
}

function insideConvex(ring: readonly Vec2[], p: Vec2, ccw: boolean): boolean {
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i];
    const b = ring[(i + 1) % ring.length];
    const z = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
    if (ccw ? z < -1e-7 : z > 1e-7) return false;
  }
  return true;
}

function segDist(p: Vec2, a: Vec2, b: Vec2): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const den = dx * dx + dy * dy;
  const t = den > 0 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / den)) : 0;
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}

function segmentsCross(a: Vec2, b: Vec2, c: Vec2, d: Vec2): boolean {
  const o = (p: Vec2, q: Vec2, r: Vec2) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  const d1 = o(c, d, a);
  const d2 = o(c, d, b);
  const d3 = o(a, b, c);
  const d4 = o(a, b, d);
  return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
}

function pointInRing(ring: readonly Vec2[], p: Vec2): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i];
    const b = ring[j];
    if (a[1] > p[1] !== b[1] > p[1] && p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

/** Distance between two simple polygons; 0 when they overlap or touch. */
export function polygonDistance(a: readonly Vec2[], b: readonly Vec2[]): number {
  for (let i = 0; i < a.length; i++)
    for (let j = 0; j < b.length; j++)
      if (segmentsCross(a[i], a[(i + 1) % a.length], b[j], b[(j + 1) % b.length])) return 0;
  if (pointInRing(b, a[0]) || pointInRing(a, b[0])) return 0;
  let d = Infinity;
  for (let i = 0; i < a.length; i++)
    for (let j = 0; j < b.length; j++) {
      d = Math.min(d, segDist(a[i], b[j], b[(j + 1) % b.length]), segDist(b[j], a[i], a[(i + 1) % a.length]));
    }
  return d;
}

/** Overlap of interiors (touching edges is not an overlap). */
function overlaps(a: readonly Vec2[], b: readonly Vec2[]): boolean {
  for (let i = 0; i < a.length; i++)
    for (let j = 0; j < b.length; j++)
      if (segmentsCross(a[i], a[(i + 1) % a.length], b[j], b[(j + 1) % b.length])) return true;
  const centre = (r: readonly Vec2[]): Vec2 => [r.reduce((s, p) => s + p[0], 0) / r.length, r.reduce((s, p) => s + p[1], 0) / r.length];
  return pointInRing(b, centre(a)) || pointInRing(a, centre(b));
}

/** FNV-1a, base 36: stable ids for identical tables, so a re-fill keeps their module ids. */
function hashId(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(36);
}

export interface Geometry {
  /** Module along the row and up the module plane, m. */
  along: number;
  slant: number;
  cosT: number;
  sinT: number;
  /** Slant depth of a table with n rows, m. */
  slantDepth: (n: number) => number;
  /** Plan depth of a table with n rows, m. */
  planDepth: (n: number) => number;
  /** Plan distance between row origins inside a table, m. */
  rowPitch: number;
}

export function geometryOf(module: { width_m: number; height_m: number }, orientation: Orientation, tiltDeg: number, inTableGap: number): Geometry {
  // Portrait: the long side runs up the slope (B5).
  const long = Math.max(module.width_m, module.height_m);
  const short = Math.min(module.width_m, module.height_m);
  const along = orientation === "portrait" ? short : long;
  const slant = orientation === "portrait" ? long : short;
  const cosT = Math.cos(tiltDeg * RAD);
  const sinT = Math.sin(tiltDeg * RAD);
  const slantDepth = (n: number) => n * slant + (n - 1) * inTableGap;
  return { along, slant, cosT, sinT, slantDepth, planDepth: (n) => slantDepth(n) * cosT, rowPitch: (slant + inTableGap) * cosT };
}

/**
 * Pitch from the front of one full table to the front of the next, m (E4).
 * - fixed aisle: plan depth + aisle;
 * - GCR: slant depth ÷ GCR;
 * - shading-free: plan depth + table height × cos(sun azimuth offset) ÷ tan(sun elevation).
 */
export function pitchOf(g: Geometry, rows: number, rule: FillZoneRequest["pitch"]): number {
  switch (rule.mode) {
    case "fixed_aisle":
      return g.planDepth(rows) + rule.aisle_m;
    case "gcr":
      return g.slantDepth(rows) / rule.gcr;
    case "shading_free": {
      const h = g.slantDepth(rows) * g.sinT;
      const shadow = (h * Math.cos(rule.sun_azimuth_offset_deg * RAD)) / Math.tan(rule.sun_elevation_deg * RAD);
      return g.planDepth(rows) + Math.max(0, shadow);
    }
  }
}

function validate(r: FillZoneRequest): LayoutFinding[] {
  const f: LayoutFinding[] = [];
  const bad = (code: string, message: string) => f.push({ severity: "blocking", code, message });
  if (!(r.tilt_deg >= 0 && r.tilt_deg < 90)) bad("tilt_range", "Tilt must be at least 0° and below 90°.");
  if (!Number.isInteger(r.rows_per_table) || r.rows_per_table < 1) bad("rows_per_table", "Rows per table must be a whole number of at least 1.");
  if (r.module_gap_m < 0 || r.in_table_gap_m < 0) bad("gap_negative", "Gaps cannot be negative.");
  if (r.keepout_offset_m < 0 || r.edge_setbacks_m.some((s) => s < 0)) bad("setback_negative", "Setbacks and offsets cannot be negative.");
  if (r.pitch.mode === "fixed_aisle" && r.pitch.aisle_m < 0) bad("aisle_negative", "The aisle cannot be negative.");
  if (r.pitch.mode === "gcr" && !(r.pitch.gcr > 0 && r.pitch.gcr <= 1)) bad("gcr_range", "GCR must be above 0 and at most 1.");
  if (r.pitch.mode === "shading_free" && !(r.pitch.sun_elevation_deg > 0 && r.pitch.sun_elevation_deg < 90))
    bad("sun_elevation", "The design sun elevation must be above 0° and below 90°.");
  if (r.walkway && (!Number.isInteger(r.walkway.every_modules) || r.walkway.every_modules < 1 || r.walkway.width_m < 0))
    bad("walkway", "A walkway needs a whole number of modules (at least 1) and a width of at least 0 m.");
  if (r.max_table_columns !== null && (!Number.isInteger(r.max_table_columns) || r.max_table_columns < 1))
    bad("size_cap", "The table size cap must be a whole number of at least 1.");
  return f;
}

/** Fills one zone. Pinned tables are returned unchanged after the generated ones. */
export function fillZone(input: FillInput): FillResult {
  const r = input.request;
  const findings = validate(r);
  if (findings.length) return { tables: [...input.pinned], pitch_m: 0, usable_region: [], findings };
  if (!isConvex(input.surface)) {
    findings.push({ severity: "blocking", code: "surface_not_convex", message: "The demo engine fills convex surfaces only; the engine fills any shape (proposal 0003)." });
    return { tables: [...input.pinned], pitch_m: 0, usable_region: [], findings };
  }
  const g = geometryOf(input.module, r.orientation, r.tilt_deg, r.in_table_gap_m);
  const pitch = pitchOf(g, r.rows_per_table, r.pitch);
  if (pitch + 1e-9 < g.planDepth(r.rows_per_table))
    findings.push({
      severity: "blocking",
      code: "pitch_overlap",
      message: `The pitch (${pitch.toFixed(3)} m) is shorter than the table's plan depth (${g.planDepth(r.rows_per_table).toFixed(3)} m): tables would overlap.`
    });
  const region = setbackRegion(input.surface, input.surface.map((_, i) => r.edge_setbacks_m[i] ?? r.edge_setbacks_m[0] ?? 0));
  if (!region.length) findings.push({ severity: "blocking", code: "setback_empty", message: "The setbacks leave no usable area." });
  if (findings.some((x) => x.severity === "blocking")) return { tables: [...input.pinned], pitch_m: pitch, usable_region: region.length ? [region] : [], findings };

  const ccw = signedArea(region) > 0;
  const { along, back } = fieldAxes(r.azimuth_deg);
  const toPlan = (u: number, v: number): Vec2 => [along[0] * u + back[0] * v, along[1] * u + back[1] * v];
  const us = region.map((p) => dot(p, along));
  const vs = region.map((p) => dot(p, back));
  const [uMin, uMax, vMin, vMax] = [Math.min(...us), Math.max(...us), Math.min(...vs), Math.max(...vs)];

  const blockers = [...input.pinned.map(tableFootprint), ...(input.occupied ?? [])];
  const obstacles = input.obstacles;
  const slotOk = (u: number, v: number): boolean => {
    const poly = [toPlan(u, v), toPlan(u + g.along, v), toPlan(u + g.along, v + g.planDepth(1)), toPlan(u, v + g.planDepth(1))];
    if (!poly.every((p) => insideConvex(region, p, ccw))) return false;
    for (const o of obstacles) if (polygonDistance(poly, o) < r.keepout_offset_m - 1e-9 || overlaps(poly, o)) return false;
    for (const b of blockers) if (overlaps(poly, b)) return false;
    return true;
  };

  // Column positions along the row, with cross walkways.
  const cols: number[] = [];
  const breakAfter = new Set<number>();
  for (let k = 0; ; k++) {
    const walks = r.walkway ? Math.floor(k / r.walkway.every_modules) : 0;
    const u = uMin + k * (g.along + r.module_gap_m) + walks * ((r.walkway?.width_m ?? 0) - r.module_gap_m);
    if (u + g.along > uMax + 1e-9) break;
    cols.push(u);
    if (r.walkway && (k + 1) % r.walkway.every_modules === 0) breakAfter.add(k);
  }

  const tables: TableRecord[] = [];
  const pushTable = (u0: number, v: number, rows: number, colIdx: number[], valid: boolean[][]) => {
    const removed: RemovedSlot[] = [];
    colIdx.forEach((_, c) => {
      for (let row = 0; row < rows; row++) if (!valid[c][row]) removed.push([row, c, "geometry"]);
    });
    const origin = toPlan(u0, v);
    const key = `${input.fieldId}|${origin[0].toFixed(4)}|${origin[1].toFixed(4)}|${rows}|${colIdx.length}|${r.orientation}|${r.azimuth_deg}|${r.tilt_deg}`;
    tables.push({
      table_id: `t${hashId(key)}`,
      pv_field_id: input.fieldId,
      origin_m: origin,
      azimuth_deg: r.azimuth_deg,
      rows,
      columns: colIdx.length,
      orientation: r.orientation,
      module_plan_m: [g.along, g.planDepth(1)],
      slot_pitch_m: [g.along + r.module_gap_m, g.rowPitch],
      removed_slots: removed,
      pinned: false,
      status: "active"
    });
  };

  const starts: Array<{ v: number; rows: number }> = [];
  const reverse = r.rows_per_table > 1 && r.leftover_depth !== "smaller_table";
  const aisle = pitch - g.planDepth(r.rows_per_table);
  for (let edge = reverse ? vMax : vMin; ; ) {
    const available = reverse ? edge - vMin : vMax - edge;
    let rows = r.rows_per_table;
    if (g.planDepth(rows) > available + 1e-9) {
      if (r.leftover_depth === "leave_empty") break;
      while (rows > 0 && g.planDepth(rows) > available + 1e-9) rows--;
    }
    if (rows < 1 || g.planDepth(rows) > available + 1e-9) break;
    starts.push({ v: reverse ? edge - g.planDepth(rows) : edge, rows });
    edge += (reverse ? -1 : 1) * (g.planDepth(rows) + aisle);
  }
  for (const { v, rows } of starts) {
    const valid = cols.map((u) => Array.from({ length: rows }, (_, row) => slotOk(u, v + row * g.rowPitch)));
    let run: number[] = [];
    const flush = () => {
      if (run.length)
        pushTable(
          cols[run[0]],
          v,
          rows,
          run,
          run.map((k) => valid[k])
        );
      run = [];
    };
    for (let k = 0; k < cols.length; k++) {
      if (!valid[k].some(Boolean)) {
        flush();
        continue;
      }
      run.push(k);
      if (breakAfter.has(k) || (r.max_table_columns !== null && run.length >= r.max_table_columns)) flush();
    }
    flush();
  }
  if (!tables.length) findings.push({ severity: "warning", code: "no_modules", message: "No module fits with these settings." });
  return { tables: [...tables, ...input.pinned], pitch_m: pitch, usable_region: [region], findings };
}

/** Compares a field's current tables with a new fill (E2 re-fill diff). */
export function diffLayouts(before: readonly TableRecord[], after: readonly TableRecord[], strings: ReadonlyArray<{ string_id: string; module_instance_ids: string[] }>): LayoutDiff {
  const sig = (t: TableRecord) => `${t.table_id}|${t.status}|${t.removed_slots.map((s) => `${s[0]}.${s[1]}`).sort().join(",")}`;
  const beforeSigs = new Set(before.map(sig));
  const afterSigs = new Set(after.map(sig));
  const kept = after.filter((t) => beforeSigs.has(sig(t)));
  const afterModules = new Set(after.flatMap((t) => tableModules(t).map((m) => m.id)));
  return {
    modules_before: moduleCountOf(before),
    modules_after: moduleCountOf(after),
    tables_added: after.filter((t) => !beforeSigs.has(sig(t))).length,
    tables_removed: before.filter((t) => !afterSigs.has(sig(t))).length,
    tables_unchanged: kept.filter((t) => !t.pinned).length,
    tables_pinned_kept: kept.filter((t) => t.pinned).length,
    strings_affected: strings.filter((s) => s.module_instance_ids.some((id) => id.includes("/") && !afterModules.has(id))).map((s) => s.string_id)
  };
}

/** A full preview: the fill in the requested orientation, the other orientation's count, and the diff. */
export function previewOf(input: FillInput, before: readonly TableRecord[], strings: ReadonlyArray<{ string_id: string; module_instance_ids: string[] }>): FillPreview {
  const main = fillZone(input);
  const other: Orientation = input.request.orientation === "portrait" ? "landscape" : "portrait";
  const alt = fillZone({ ...input, request: { ...input.request, orientation: other } });
  const blocked = main.findings.some((f) => f.severity === "blocking");
  const count = (res: FillResult) => (res.findings.some((f) => f.severity === "blocking") ? 0 : moduleCountOf(res.tables));
  return {
    request: input.request,
    tables: main.tables,
    module_count: blocked ? 0 : moduleCountOf(main.tables),
    compare: { [input.request.orientation]: count(main), [other]: count(alt) } as Record<Orientation, number>,
    pitch_m: main.pitch_m,
    usable_region: main.usable_region,
    diff: diffLayouts(before, main.tables, strings),
    findings: main.findings
  };
}
