import { describe, expect, it } from "vitest";
import type { Vec2 } from "../../src/geometry";
import { diffLayouts, fillZone, geometryOf, pitchOf, previewOf, setbackRegion, type FillInput } from "../../src/demo/fillEngine";
import { moduleCountOf, slotOf, tableFootprint, tableModules, type FillZoneRequest, type TableRecord } from "../../src/engine/layout";
import { goldenRequest } from "./golden";

// Golden case (plan B5): 2 × 1 m modules on an 8 × 12 m plane, 5 cm gaps, 1 m aisle,
// 40 cm setback. Portrait gives 30 (tables 2×10 + 1×10); landscape gives 25 (2×5 + 2×5 + 1×5).
// The rows run along the 12 m side, so the plane is 12 m east–west and 8 m north–south.
const GOLDEN_SURFACE: Vec2[] = [
  [0, 0],
  [12, 0],
  [12, 8],
  [0, 8]
];


const input = (over: Partial<FillZoneRequest> = {}, extra: Partial<FillInput> = {}): FillInput => ({
  surface: GOLDEN_SURFACE,
  obstacles: [],
  module: { width_m: 1, height_m: 2 },
  request: goldenRequest(over),
  fieldId: "fld",
  pinned: [],
  ...extra
});

const shape = (tables: TableRecord[]) => tables.map((t) => `${t.rows}×${t.columns}`).sort();

describe("demo fill engine: golden case", () => {
  it("portrait gives 30 modules in tables 2×10 + 1×10", () => {
    const res = fillZone(input());
    expect(res.findings).toEqual([]);
    expect(moduleCountOf(res.tables)).toBe(30);
    expect(shape(res.tables)).toEqual(["1×10", "2×10"]);
  });

  it("landscape gives 25 modules in tables 2×5 + 2×5 + 1×5", () => {
    const res = fillZone(input({ orientation: "landscape" }));
    expect(moduleCountOf(res.tables)).toBe(25);
    expect(shape(res.tables)).toEqual(["1×5", "2×5", "2×5"]);
  });

  it("the preview compares both orientations", () => {
    const p = previewOf(input(), [], []);
    expect(p.compare).toEqual({ portrait: 30, landscape: 25 });
    expect(p.module_count).toBe(30);
    expect(p.pitch_m).toBeCloseTo(4.05 + 1, 9);
  });

  it("every module lies inside the 40 cm setback and modules do not overlap", () => {
    const mods = fillZone(input()).tables.flatMap(tableModules);
    for (const m of mods)
      for (const p of m.polygon) {
        expect(p[0]).toBeGreaterThanOrEqual(0.4 - 1e-9);
        expect(p[0]).toBeLessThanOrEqual(11.6 + 1e-9);
        expect(p[1]).toBeGreaterThanOrEqual(0.4 - 1e-9);
        expect(p[1]).toBeLessThanOrEqual(7.6 + 1e-9);
      }
    // Gaps: neighbours along the row are 1.05 m apart, rows inside a table 2.05 m.
    const t = fillZone(input()).tables.find((x) => x.rows === 2)!;
    expect(t.slot_pitch_m[0]).toBeCloseTo(1.05, 12);
    expect(t.slot_pitch_m[1]).toBeCloseTo(2.05, 12);
  });

  it("leave_empty drops the leftover single-row table", () => {
    expect(moduleCountOf(fillZone(input({ leftover_depth: "leave_empty" })).tables)).toBe(20);
  });
});

describe("demo fill engine: geometry and pitch modes (hand calculations)", () => {
  const g = geometryOf({ width_m: 1.134, height_m: 2.278 }, "portrait", 10, 0.02);
  const cos10 = Math.cos((10 * Math.PI) / 180);
  const sin10 = Math.sin((10 * Math.PI) / 180);

  it("projects the slant depth by cos(tilt)", () => {
    expect(g.slantDepth(2)).toBeCloseTo(2 * 2.278 + 0.02, 12);
    expect(g.planDepth(2)).toBeCloseTo((2 * 2.278 + 0.02) * cos10, 12);
    expect(g.rowPitch).toBeCloseTo((2.278 + 0.02) * cos10, 12);
  });

  it("fixed aisle: plan depth + aisle", () => {
    expect(pitchOf(g, 2, { mode: "fixed_aisle", aisle_m: 0.8 })).toBeCloseTo(4.576 * cos10 + 0.8, 9);
  });

  it("GCR: slant depth ÷ GCR", () => {
    expect(pitchOf(g, 2, { mode: "gcr", gcr: 0.5 })).toBeCloseTo(4.576 / 0.5, 9);
  });

  it("shading-free: plan depth + height × cos(offset) ÷ tan(elevation)", () => {
    const h = 4.576 * sin10;
    const expected = 4.576 * cos10 + (h * Math.cos((20 * Math.PI) / 180)) / Math.tan((30 * Math.PI) / 180);
    expect(pitchOf(g, 2, { mode: "shading_free", sun_elevation_deg: 30, sun_azimuth_offset_deg: 20 })).toBeCloseTo(expected, 9);
    // Flat modules cast no row shadow.
    const flat = geometryOf({ width_m: 1, height_m: 2 }, "portrait", 0, 0.05);
    expect(pitchOf(flat, 1, { mode: "shading_free", sun_elevation_deg: 30, sun_azimuth_offset_deg: 0 })).toBeCloseTo(2, 12);
  });

  it("blocks a GCR whose pitch is shorter than the table", () => {
    const res = fillZone(input({ tilt_deg: 0, pitch: { mode: "gcr", gcr: 1.0 } }));
    expect(res.findings).toEqual([]); // GCR 1 on flat modules: rows just touch
    const steep = geometryOf({ width_m: 1, height_m: 2 }, "portrait", 60, 0.05);
    expect(pitchOf(steep, 2, { mode: "gcr", gcr: 1 })).toBeGreaterThan(steep.planDepth(2));
  });

  it("tilted rows on a flat roof: the table's plan depth shrinks and the count can rise", () => {
    // Usable depth 7.2 m. Flat: pitch 2 + 0.5 = 2.5 m, rows at 0, 2.5, 5.0 → 3 rows of 10.
    // 45°: plan depth 2·cos 45° = 1.414 m, pitch 1.914 m, rows at 0, 1.91, 3.83, 5.74 (ends 7.16) → 4 rows.
    const flat = moduleCountOf(fillZone(input({ tilt_deg: 0, rows_per_table: 1, pitch: { mode: "fixed_aisle", aisle_m: 0.5 } })).tables);
    const tilted = moduleCountOf(fillZone(input({ tilt_deg: 45, rows_per_table: 1, pitch: { mode: "fixed_aisle", aisle_m: 0.5 } })).tables);
    expect(flat).toBe(30);
    expect(tilted).toBe(40);
  });
});

describe("demo fill engine: setbacks, keep-outs, walkways, size cap", () => {
  it("per-edge setbacks clip each edge by its own distance", () => {
    const region = setbackRegion(GOLDEN_SURFACE, [0.5, 1, 0, 2]);
    const xs = region.map((p) => p[0]);
    const ys = region.map((p) => p[1]);
    expect(Math.min(...ys)).toBeCloseTo(0.5, 12); // edge 0 runs along y = 0
    expect(Math.max(...xs)).toBeCloseTo(11, 12); // edge 1 along x = 12
    expect(Math.max(...ys)).toBeCloseTo(8, 12); // edge 2 along y = 8
    expect(Math.min(...xs)).toBeCloseTo(2, 12); // edge 3 along x = 0
  });

  it("keeps the keep-out offset around an obstacle", () => {
    const obstacle: Vec2[] = [
      [5, 3],
      [7, 3],
      [7, 5],
      [5, 5]
    ];
    const res = fillZone(input({ keepout_offset_m: 0.5 }, { obstacles: [obstacle] }));
    const count = moduleCountOf(res.tables);
    expect(count).toBeLessThan(30);
    for (const m of res.tables.flatMap(tableModules)) {
      const xs = m.polygon.map((p) => p[0]);
      const ys = m.polygon.map((p) => p[1]);
      const dx = Math.max(0, Math.max(5 - Math.max(...xs), Math.min(...xs) - 7));
      const dy = Math.max(0, Math.max(3 - Math.max(...ys), Math.min(...ys) - 5));
      expect(Math.hypot(dx, dy)).toBeGreaterThanOrEqual(0.5 - 1e-9);
    }
  });

  it("a walkway every 5 modules splits the rows into tables of 5", () => {
    // 10 columns need 10.45 m; a 1 m walkway instead of one 5 cm gap adds 0.95 m → 11.4 m > 11.2 m,
    // so each row keeps 9 modules (5 + 4). A 0.6 m walkway (+0.55 m → 11.0 m) still fits 10.
    const res = fillZone(input({ walkway: { every_modules: 5, width_m: 1 } }));
    expect(res.tables.every((t) => t.columns <= 5)).toBe(true);
    expect(moduleCountOf(res.tables)).toBe(27);
    expect(moduleCountOf(fillZone(input({ walkway: { every_modules: 5, width_m: 0.6 } })).tables)).toBe(30);
  });

  it("a size cap of 4 splits a 10-module row into 4 + 4 + 2", () => {
    const res = fillZone(input({ max_table_columns: 4 }));
    expect(moduleCountOf(res.tables)).toBe(30);
    expect(res.tables.filter((t) => t.rows === 2).map((t) => t.columns)).toEqual([4, 4, 2]);
  });

  it("keeps clear of another field's modules on the same surface", () => {
    const other: Vec2[] = [
      [0, 4],
      [12, 4],
      [12, 8],
      [0, 8]
    ];
    const res = fillZone(input({}, { occupied: [other] }));
    for (const m of res.tables.flatMap(tableModules)) expect(Math.max(...m.polygon.map((p) => p[1]))).toBeLessThanOrEqual(4 + 1e-9);
    expect(moduleCountOf(res.tables)).toBeGreaterThan(0);
  });

  it("blocks a concave surface in the demo", () => {
    const l: Vec2[] = [
      [0, 0],
      [10, 0],
      [10, 4],
      [4, 4],
      [4, 10],
      [0, 10]
    ];
    expect(fillZone(input({}, { surface: l })).findings[0].code).toBe("surface_not_convex");
  });
});

describe("demo fill engine: pins and the re-fill diff", () => {
  it("identical tables keep their ids, so a re-fill keeps module ids", () => {
    const a = fillZone(input()).tables;
    const b = fillZone(input()).tables;
    expect(a.map((t) => t.table_id)).toEqual(b.map((t) => t.table_id));
    const id = tableModules(a[0])[0].id;
    expect(slotOf(id)).toEqual({ tableId: a[0].table_id, row: 0, column: 0 });
  });

  it("a pinned table survives a re-fill and stays clear", () => {
    const first = fillZone(input()).tables;
    const pinned = { ...first[0], origin_m: [first[0].origin_m[0], first[0].origin_m[1]] as Vec2, pinned: true };
    const refill = fillZone(input({ rows_per_table: 1, pitch: { mode: "fixed_aisle", aisle_m: 0.6 } }, { pinned: [pinned] }));
    expect(refill.tables).toContainEqual(pinned);
    const fp = tableFootprint(pinned);
    const minX = Math.min(...fp.map((p) => p[0]));
    const maxX = Math.max(...fp.map((p) => p[0]));
    const minY = Math.min(...fp.map((p) => p[1]));
    const maxY = Math.max(...fp.map((p) => p[1]));
    for (const t of refill.tables.filter((x) => !x.pinned))
      for (const m of tableModules(t)) {
        const cx = m.polygon.reduce((s, p) => s + p[0], 0) / 4;
        const cy = m.polygon.reduce((s, p) => s + p[1], 0) / 4;
        expect(cx > minX && cx < maxX && cy > minY && cy < maxY).toBe(false);
      }
  });

  it("a deleted, pinned table keeps its footprint empty", () => {
    const first = fillZone(input()).tables;
    const gone = { ...first[0], pinned: true, status: "deleted" as const };
    const refill = fillZone({ ...input(), pinned: [gone] });
    expect(moduleCountOf(refill.tables)).toBe(30 - first[0].rows * first[0].columns);
  });

  it("the diff counts added, removed, unchanged and pinned tables, and affected strings", () => {
    const before = fillZone(input()).tables;
    const after = fillZone(input({ orientation: "landscape" })).tables;
    const strings = [{ string_id: "S1", module_instance_ids: tableModules(before[0]).map((m) => m.id) }];
    const d = diffLayouts(before, after, strings);
    expect(d.modules_before).toBe(30);
    expect(d.modules_after).toBe(25);
    expect(d.tables_removed).toBe(2);
    expect(d.tables_added).toBe(3);
    expect(d.strings_affected).toEqual(["S1"]);
    const same = diffLayouts(before, fillZone(input()).tables, strings);
    expect(same.tables_unchanged).toBe(2);
    expect(same.strings_affected).toEqual([]);
  });
});

describe("the demo engine's output matches the draft schema of proposal 0003", () => {
  it("validates requests and tables", async () => {
    const { default: Ajv2020 } = await import("ajv/dist/2020");
    const fs = await import("node:fs");
    const schema = JSON.parse(fs.readFileSync(new URL("../../../../docs/proposals/0003-table-layout.schema.draft.json", import.meta.url), "utf8"));
    const validate = new Ajv2020({ allErrors: true, strict: false }).compile(schema);
    const req = goldenRequest({ pv_field_id: "fld", walkway: { every_modules: 5, width_m: 1 }, max_table_columns: 4 });
    const tables = fillZone(input({ walkway: req.walkway, max_table_columns: 4 })).tables;
    tables[0].removed_slots.push([0, 1, "manual"]);
    const ok = validate({ requests: { fld: req }, tables });
    expect(validate.errors ?? []).toEqual([]);
    expect(ok).toBe(true);
  });
});
