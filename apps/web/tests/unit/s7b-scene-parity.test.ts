import { describe, expect, it } from "vitest";
import { rotateClockwise, setEdgeLength } from "../../src/canvas/plan/edit";
import type { Vec2 } from "../../src/geometry";
import type { ProjectView } from "../../src/types";
import fixture from "./s7b-engine-fixture.json";

// Captured from create_app(store_root=TemporaryDirectory()) at 2de4940.
// The complete ProjectView responses follow these HTTP operations in order:
// rectangle (20,0), 4×3; rotate 30° about (22,1.5); edge 0 → 5 m,
// preserve start; vertex 2 → (25,3). No network is used by these tests.
const views = fixture.views as unknown as Record<keyof typeof fixture.views, ProjectView>;
const ring = (view: ProjectView): Vec2[] => view.scene_view.local_features
  .find((feature) => feature.id === fixture.id)!.polygon.map(([x, y]) => [x, y]);

function sameRing(actual: Vec2[], expected: Vec2[]) {
  expect(actual).toHaveLength(expected.length);
  for (let i = 0; i < expected.length; i++) {
    expect(Math.abs(actual[i][0] - expected[i][0])).toBeLessThanOrEqual(1e-9);
    expect(Math.abs(actual[i][1] - expected[i][1])).toBeLessThanOrEqual(1e-9);
  }
}

describe("S7b engine and UI geometry conventions (DEC-28)", () => {
  it("keeps the engine's stored open ring order and clockwise pivot", () => {
    expect(ring(views.before)).toEqual([[20, 0], [24, 0], [24, 3], [20, 3]]);
    sameRing(rotateClockwise(ring(views.before), [22, 1.5], 30), ring(views.rotated));
  });

  it("changes the same edge endpoint when preserving the start", () => {
    sameRing(setEdgeLength(ring(views.rotated), 0, 5, "start"), ring(views.dimensioned));
  });

  it("moves vertex i at the same stored index without closing or reordering", () => {
    const preview = ring(views.dimensioned).map((p, i): Vec2 => i === 2 ? [25, 3] : p);
    sameRing(preview, ring(views.vertexMoved));
  });
});
