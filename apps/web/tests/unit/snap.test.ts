import { describe, expect, it } from "vitest";
import fixture from "../fixtures/snap-cases.json";
import type { Vec2 } from "../../src/geometry";
import { pyRound, Snapper, type SnapItem, type SnapKind, type SupplementalEdge } from "../../src/canvas/plan/snap";

// Parity with the engine's SnapEngine (geometry/scene/snapping.py). The cases
// and the engine's answers come from scripts/gen-snap-fixture.py.

interface Case {
  case: number;
  items: SnapItem[];
  supplemental: Partial<Record<"module_edge" | "row_edge", SupplementalEdge[]>>;
  point: Vec2;
  options: { toleranceM: number; enabled: SnapKind[]; override: boolean; gridSpacingM: number | null; anchor: Vec2 | null; referenceDirection: Vec2 | null };
  expected: { applied: boolean; point: Vec2; kind: SnapKind | null; sourceId: string | null; featureIndex: number | null };
}

const cases = (fixture as unknown as { cases: Case[] }).cases;

describe("snapping parity with the engine's SnapEngine", () => {
  it("has a fixture that covers every snap kind the UI offers", () => {
    const kinds = new Set(cases.map((c) => c.expected.kind));
    for (const k of ["vertex", "endpoint", "edge", "midpoint", "intersection", "parallel", "perpendicular", "module_edge", "row_edge", "user_grid", null]) expect(kinds).toContain(k);
    expect(cases.length).toBeGreaterThanOrEqual(600);
  });

  it.each(cases.map((c) => [c.case, c] as const))("case %i matches", (_n, c) => {
    const supplemental = Object.fromEntries(
      Object.entries(c.supplemental).map(([k, list]) => [k, () => (list ?? []).map((e, i) => [i, ...e] as [number, ...SupplementalEdge])])
    );
    const s = new Snapper(c.items, supplemental);
    const r = s.resolve(c.point, c.options);
    expect(r.applied).toBe(c.expected.applied);
    expect(r.kind).toBe(c.expected.kind);
    expect(r.sourceId).toBe(c.expected.sourceId);
    expect(r.featureIndex).toBe(c.expected.featureIndex);
    expect(r.point[0]).toBeCloseTo(c.expected.point[0], 9);
    expect(r.point[1]).toBeCloseTo(c.expected.point[1], 9);
  });
});

describe("snap helpers", () => {
  it("rounds halves to even, like Python", () => {
    expect([pyRound(0.5), pyRound(1.5), pyRound(2.5), pyRound(-0.5), pyRound(-1.5), pyRound(2.4999)]).toEqual([0, 2, 2, 0, -2, 2]);
  });

  it("Alt (override) returns the raw point", () => {
    const s = new Snapper([{ id: "a", points: [[0, 0], [1, 0], [1, 1]], closed: true }]);
    const r = s.resolve([0.01, 0.01], { toleranceM: 1, override: true });
    expect(r.applied).toBe(false);
    expect(r.point).toEqual([0.01, 0.01]);
  });
});
