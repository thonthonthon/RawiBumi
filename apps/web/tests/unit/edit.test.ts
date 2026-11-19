import { describe, expect, it } from "vitest";
import fixture from "../fixtures/edit-cases.json";
import type { Vec2 } from "../../src/geometry";
import { offsetEdge, rotateClockwise, setEdgeAzimuth, setEdgeLength, type Preserve } from "../../src/canvas/plan/edit";

// Parity with the engine's exact edits (geometry/scene/geometry2d.py);
// fixture from scripts/gen-edit-fixture.py.
interface Case {
  case: number;
  op: "length" | "azimuth" | "rotate";
  points: Vec2[];
  edge?: number;
  preserve?: Preserve;
  closed?: boolean;
  origin?: Vec2;
  value: number;
  expected: Vec2[];
}
const cases = (fixture as unknown as { cases: Case[] }).cases;

describe("exact edits match the engine", () => {
  it.each(cases.map((c) => [c.case, c.op, c] as const))("case %i (%s)", (_n, _op, c) => {
    const out =
      c.op === "rotate"
        ? rotateClockwise(c.points, c.origin!, c.value)
        : c.op === "length"
          ? setEdgeLength(c.points, c.edge!, c.value, c.preserve, c.closed)
          : setEdgeAzimuth(c.points, c.edge!, c.value, c.preserve, c.closed);
    expect(out).toHaveLength(c.expected.length);
    out.forEach((p, i) => {
      expect(p[0]).toBeCloseTo(c.expected[i][0], 9);
      expect(p[1]).toBeCloseTo(c.expected[i][1], 9);
    });
  });
});

describe("edge offset (handle drag along the normal)", () => {
  const square: Vec2[] = [[0, 0], [4, 0], [4, 3], [0, 3]];
  it("moves an edge outward for positive offsets, either winding", () => {
    expect(offsetEdge(square, 1, 1)).toEqual([[0, 0], [5, 0], [5, 3], [0, 3]]);
    const cw = [...square].reverse();
    // In the clockwise copy, edge 0 is (0,3)→(4,3): the top edge.
    expect(offsetEdge(cw, 0, 0.5)).toEqual([[0, 3.5], [4, 3.5], [4, 0], [0, 0]]);
  });
});
