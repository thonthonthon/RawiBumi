import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { engine } from "../../src/client";
import { isRectangle, rotateClockwise, setEdgeLength, type Preserve } from "../../src/canvas/plan/edit";
import { useEntityEdits } from "../../src/canvas/useEntityEdits";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import type { Vec2 } from "../../src/geometry";
import { resetStore, uiStore } from "../../src/state/store";

vi.mock("react", async (importOriginal) => ({ ...await importOriginal<typeof import("react")>(), useCallback: (fn: unknown) => fn }));
vi.mock("../../src/state/store", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../src/state/store")>(),
  useActions: () => uiStore.getState(),
  useUI: (select: (state: unknown) => unknown) => select(uiStore.getState().state)
}));

const rectangle = rotateClockwise([[0, 0], [10, 0], [10, 6], [0, 6]], [5, 3], 30);
// Shared hard-coded oracle with tests/unit/test_rb_rot1_rectangle_dimension.py.
const expected: Vec2[] = [
  [-0.8301270189221936, 2.901923788646684],
  [9.562177826491071, -3.098076211353316],
  [12.562177826491071, 2.098076211353316],
  [2.1698729810778064, 8.098076211353316]
];
const trapezoid: Vec2[] = [[0, 0], [10, 0], [8, 6], [0, 6]];
const pentagon: Vec2[] = [[0, 0], [10, 0], [10, 3], [8, 6], [0, 6]];

function samePoints(actual: Vec2[], target: Vec2[]) {
  expect(actual).toHaveLength(target.length);
  actual.forEach((p, i) => p.forEach((v, axis) => expect(Math.abs(v - target[i][axis])).toBeLessThanOrEqual(1e-9)));
}

describe("rectangle dimensions", () => {
  it("matches the Python oracle and keeps the start side fixed", () => {
    const result = setEdgeLength(rectangle, 0, 12, "rectangle");
    samePoints(result, expected);
    expect(isRectangle(result)).toBe(true);
    expect(result[0]).toEqual(rectangle[0]);
    expect(result[3]).toEqual(rectangle[3]);
  });

  it.each([0, 1, 2, 3])("preserves right angles and adjacent edges for edge %i, either winding and resizing direction", (edge) => {
    for (const ring of [rectangle, [...rectangle].reverse()]) for (const length of [4, 12]) {
      const original = structuredClone(ring);
      const result = setEdgeLength(ring, edge, length, "rectangle");
      expect(isRectangle(result)).toBe(true);
      expect(result[edge]).toEqual(ring[edge]);
      expect(result[(edge + 3) % 4]).toEqual(ring[(edge + 3) % 4]);
      for (let i = 0; i < 4; i++) {
        const next = (i + 1) % 4;
        const actual: Vec2 = [result[next][0] - result[i][0], result[next][1] - result[i][1]];
        const before: Vec2 = [ring[next][0] - ring[i][0], ring[next][1] - ring[i][1]];
        if (i === edge || i === (edge + 2) % 4) expect(Math.hypot(...actual)).toBeCloseTo(length, 9);
        else samePoints([actual], [before]);
      }
      expect(ring).toEqual(original);
    }
  });

  it("recognises rectangles and rejects trapezoids, extra vertices, open rings and zero edges", () => {
    expect(isRectangle(rectangle)).toBe(true);
    expect(isRectangle([[0, 0], [10, 0], [10, 6], [0, 6]])).toBe(true);
    for (const ring of [trapezoid, pentagon, [], [[0, 0], [0, 0], [10, 6], [0, 6]] as Vec2[]]) {
      expect(isRectangle(ring)).toBe(false);
      if (ring.length) expect(() => setEdgeLength(ring, 0, 12, "rectangle")).toThrow("preserve rectangle needs a rectangle");
    }
    expect(() => setEdgeLength(rectangle, 0, 12, "rectangle", false)).toThrow("preserve rectangle needs a rectangle");
  });

  it.each([[0.5e-9, true], [2e-9, false]] as const)("uses the unit dot product tolerance (skew=%s)", (skew, accepted) => {
    const ring: Vec2[] = [[0, 0], [10, 0], [10 + 6 * skew, 6], [6 * skew, 6]];
    expect(isRectangle(ring)).toBe(accepted);
    if (accepted) expect(() => setEdgeLength(ring, 0, 12, "rectangle")).not.toThrow();
    else expect(() => setEdgeLength(ring, 0, 12, "rectangle")).toThrow("preserve rectangle needs a rectangle");
  });

  it("keeps start and default edits unchanged", () => {
    const target = [rectangle[0], expected[1], rectangle[2], rectangle[3]];
    samePoints(setEdgeLength(rectangle, 0, 12, "start"), target);
    samePoints(setEdgeLength(rectangle, 0, 12), target);
    expect(() => setEdgeLength(rectangle, 0, 12, "unknown" as Preserve)).toThrow("preserve must be start, end, midpoint, or rectangle");
  });
});

describe("demo and dimension callers", () => {
  beforeEach(async () => {
    resetStore(); setDemoLatency(0);
    await mockApi.createProject({ name: "RB-ROT1", latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" });
  });
  afterEach(() => { vi.restoreAllMocks(); resetStore(); setDemoLatency(1); });

  async function draw(ring: Vec2[], kind = "flat_roof") {
    const view = await mockApi.sceneCommand("p", { command_type: "draw_polygon", target_entity_ids: [], parameters: { name: "Rectangle", surface_type: kind, vertices: ring } });
    uiStore.getState().dispatch({ type: "setView", view });
    return view.bundle.scene.surfaces.at(-1)!.surface_id;
  }

  it.each([undefined, "start", "end", "midpoint", "rectangle"] as const)("honours preserve=%s in the demo engine", async (preserve) => {
    const id = await draw(rectangle);
    const view = await mockApi.sceneCommand("p", { command_type: "edit_exact_dimension", target_entity_ids: [id], parameters: { edge_index: 0, length_m: 12, ...(preserve ? { preserve } : {}) } });
    const polygon = view.scene_view.local_features.find(f => f.id === id)!.polygon;
    samePoints(polygon, preserve === "rectangle" ? expected : setEdgeLength(rectangle, 0, 12, preserve));
  });

  it("rejects rectangle mode on a trapezoid without saving in the demo", async () => {
    const id = await draw(trapezoid), before = await mockApi.project("p");
    await expect(mockApi.sceneCommand("p", { command_type: "edit_exact_dimension", target_entity_ids: [id], parameters: { edge_index: 0, length_m: 12, preserve: "rectangle" } })).rejects.toThrow("preserve rectangle needs a rectangle");
    expect(await mockApi.project("p")).toEqual(before);
  });

  it.each(["engine", "draft"] as const)("selects the same mode for %s edits and previews", async (source) => {
    for (const ring of [rectangle, trapezoid]) {
      const id = await draw(ring);
      const entity = uiStore.getState().state.entities.find(e => e.id === id)!;
      const preserve = isRectangle(ring) ? "rectangle" : "start";
      const call = vi.spyOn(engine, "sceneCommand").mockImplementation((_pid, command) => mockApi.sceneCommand("p", command));
      if (source === "draft") uiStore.getState().dispatch({ type: "updateEntity", id, patch: { source: "draft" } });
      await useEntityEdits().editDimension({ ...entity, source }, 0, 12);
      if (source === "engine") expect(call).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ parameters: { edge_index: 0, length_m: 12, preserve } }), {});
      else expect(call).not.toHaveBeenCalled();
      samePoints(uiStore.getState().state.entities.find(e => e.id === id)!.polygon, setEdgeLength(ring, 0, 12, preserve));
      call.mockRestore();
    }
  });
});
