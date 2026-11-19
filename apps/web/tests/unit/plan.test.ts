import { describe, expect, it } from "vitest";
import type { Vec2 } from "../../src/geometry";
import { corners } from "../../src/canvas/gl/modules";
import { ModuleIndex } from "../../src/canvas/plan/moduleIndex";
import { syntheticCount, syntheticModules } from "../../src/canvas/plan/synthetic";
import { clampScale, fitView, MAX_SCALE, MIN_SCALE, niceStep, toScreen, toWorld, unionBox, visibleBox, zoomAt } from "../../src/canvas/plan/viewport";
import type { ModuleShape } from "../../src/state/store";

const size = { w: 1000, h: 600 };
const view = { cx: 10, cy: 5, scale: 20 };

describe("plan viewport", () => {
  it("toScreen and toWorld are inverse, with Y north up", () => {
    const p: Vec2 = [12.5, -3.25];
    const s = toScreen(view, size, p);
    expect(toWorld(view, size, s)[0]).toBeCloseTo(p[0], 9);
    expect(toWorld(view, size, s)[1]).toBeCloseTo(p[1], 9);
    expect(toScreen(view, size, [10, 5])).toEqual([500, 300]);
    // One metre north is 20 px up the screen.
    expect(toScreen(view, size, [10, 6])).toEqual([500, 280]);
  });

  it("zoomAt keeps the world point under the cursor fixed", () => {
    const s: Vec2 = [730, 120];
    const before = toWorld(view, size, s);
    const after = toWorld(zoomAt(view, size, s, 2.5), size, s);
    expect(after[0]).toBeCloseTo(before[0], 9);
    expect(after[1]).toBeCloseTo(before[1], 9);
  });

  it("fitView shows the whole box inside the margin", () => {
    const box = { minX: -40, minY: 0, maxX: 160, maxY: 30 };
    const v = fitView(box, size, 60);
    const vb = visibleBox(v, size);
    expect(vb.minX).toBeLessThanOrEqual(box.minX);
    expect(vb.maxX).toBeGreaterThanOrEqual(box.maxX);
    expect(vb.minY).toBeLessThanOrEqual(box.minY);
    expect(vb.maxY).toBeGreaterThanOrEqual(box.maxY);
    // Width-limited: 200 m into 880 px.
    expect(v.scale).toBeCloseTo(880 / 200, 9);
  });

  it("scale is clamped and survives bad input", () => {
    expect(clampScale(1e9)).toBe(MAX_SCALE);
    expect(clampScale(0)).toBe(MIN_SCALE);
    expect(clampScale(Number.NaN)).toBe(18);
  });

  it("niceStep picks the next round step", () => {
    expect(niceStep(0.07)).toBe(0.1);
    expect(niceStep(3)).toBe(5);
    expect(niceStep(5)).toBe(5);
    expect(niceStep(240)).toBe(500);
    expect(niceStep(1e6)).toBe(10000);
  });

  it("unionBox ignores empty inputs", () => {
    expect(unionBox(null, null)).toBeNull();
    expect(unionBox({ minX: 0, minY: 0, maxX: 1, maxY: 1 }, null, { minX: -2, minY: 0.5, maxX: 0.5, maxY: 3 })).toEqual({ minX: -2, minY: 0, maxX: 1, maxY: 3 });
  });
});

const rect = (id: string, x: number, y: number, w = 1, h = 2): ModuleShape => ({
  id,
  fieldId: "f",
  polygon: [
    [x, y],
    [x + w, y],
    [x + w, y + h],
    [x, y + h]
  ],
  stringId: null,
  mpptKey: null
});

describe("module index (flatbush)", () => {
  it("picks the module under the point and nothing in the gaps", () => {
    const idx = new ModuleIndex([rect("a", 0, 0), rect("b", 1.1, 0), rect("c", 0, 2.1)]);
    expect(idx.pick([0.5, 1])).toBe("a");
    expect(idx.pick([1.5, 1.9])).toBe("b");
    expect(idx.pick([0.2, 3])).toBe("c");
    expect(idx.pick([1.05, 1])).toBeNull();
    expect(idx.bounds).toEqual({ minX: 0, minY: 0, maxX: 2.1, maxY: 4.1 });
  });

  it("uses the polygon, not only the box, for rotated modules", () => {
    const diamond: ModuleShape = { ...rect("d", 0, 0), polygon: [[1, 0], [2, 1], [1, 2], [0, 1]] };
    const idx = new ModuleIndex([diamond]);
    expect(idx.pick([1, 1])).toBe("d");
    expect(idx.pick([0.1, 0.1])).toBeNull(); // inside the box, outside the diamond
  });

  it("the last module wins where footprints overlap", () => {
    const idx = new ModuleIndex([rect("under", 0, 0), rect("over", 0.5, 0)]);
    expect(idx.pick([0.75, 1])).toBe("over");
  });

  it("an empty layout has no bounds and picks nothing", () => {
    const idx = new ModuleIndex([]);
    expect(idx.bounds).toBeNull();
    expect(idx.pick([0, 0])).toBeNull();
  });

  it("picks among 100k modules in well under 16 ms (ADR 0002 gate)", () => {
    const mods = syntheticModules(100_000);
    expect(mods).toHaveLength(100_000);
    const idx = new ModuleIndex(mods);
    const b = idx.bounds!;
    let worst = 0;
    let hits = 0;
    for (let i = 0; i < 2000; i++) {
      const p: Vec2 = [b.minX + ((i * 7919) % 1000) / 1000 * (b.maxX - b.minX), b.minY + ((i * 104729) % 1000) / 1000 * (b.maxY - b.minY)];
      const t0 = performance.now();
      if (idx.pick(p)) hits++;
      worst = Math.max(worst, performance.now() - t0);
    }
    expect(hits).toBeGreaterThan(0);
    expect(worst).toBeLessThan(16);
    // A module's own centre always picks that module.
    const m = mods[54_321];
    const c: Vec2 = [m.polygon.reduce((s, p) => s + p[0], 0) / 4, m.polygon.reduce((s, p) => s + p[1], 0) / 4];
    expect(idx.pick(c)).toBe(m.id);
  });
});

describe("synthetic layout and module quads", () => {
  it("parses ?synthetic and caps it", () => {
    expect(syntheticCount("?synthetic=100000")).toBe(100000);
    expect(syntheticCount("?synthetic=1e9")).toBe(250000);
    expect(syntheticCount("?synthetic=abc")).toBeNull();
    expect(syntheticCount("?perf")).toBeNull();
  });

  it("synthetic modules are 1.134 × 2.278 m and some are unassigned", () => {
    const mods = syntheticModules(2000);
    const [p0, p1, , p3] = mods[0].polygon;
    expect(Math.hypot(p1[0] - p0[0], p1[1] - p0[1])).toBeCloseTo(1.134, 6);
    expect(Math.hypot(p3[0] - p0[0], p3[1] - p0[1])).toBeCloseTo(2.278, 6);
    expect(mods.some((m) => m.mpptKey === null)).toBe(true);
    expect(new Set(mods.map((m) => m.id)).size).toBe(2000);
  });

  it("corners keep four-cornered footprints and box anything else", () => {
    const quad: Vec2[] = [[0, 0], [2, 0.2], [2.1, 1], [0, 1]];
    expect(corners(quad)).toEqual(quad);
    expect(corners([[0, 0], [2, 0], [1, 3]])).toEqual([[0, 0], [2, 0], [2, 3], [0, 3]]);
  });
});
