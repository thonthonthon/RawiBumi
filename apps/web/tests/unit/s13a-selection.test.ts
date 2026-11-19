import { afterEach, describe, expect, it } from "vitest";
import { boxSelect } from "../../src/canvas/boxSelect";
import { resetStore, uiStore } from "../../src/state/store";
import type { Vec2 } from "../../src/geometry";

const rectangle = (x0: number, y0: number, x1: number, y1: number): Vec2[] => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
afterEach(resetStore);
describe("S13a A1 world-space box selection", () => {
  it.each([
    ["inside", rectangle(2, 2, 4, 4), true, true],
    ["partly inside", rectangle(8, 8, 12, 12), false, true],
    ["outside", rectangle(12, 12, 14, 14), false, false],
    ["enclosing", rectangle(-1, -1, 11, 11), false, false],
    ["module touching edge", rectangle(0, 2, 2, 4), false, true],
    ["corner contact outside", rectangle(10, 10, 12, 12), false, true],
    ["collinear but disjoint", rectangle(12, 0, 14, 2), false, false],
    ["thin polygon crossing without contained vertices", rectangle(-2, 4, 12, 6), false, true]
  ] as const)("%s", (_label, polygon, window, crossing) => {
    for (const ring of [polygon, [...polygon].reverse()]) {
      expect(boxSelect(ring, [0, 0], [10, 10], false)).toBe(window);
      expect(boxSelect(ring, [10, 10], [0, 0], true)).toBe(crossing);
    }
  });
  it("does not select empty or incomplete footprints", () => {
    expect(boxSelect([], [0, 0], [10, 10], true)).toBe(false);
    expect(boxSelect([[1, 1]], [0, 0], [10, 10], false)).toBe(false);
  });
  it("toggles scene and module ids and adds box results without duplicates", () => {
    const { dispatch } = uiStore.getState();
    dispatch({ type: "selectToggle", id: "roof" });
    dispatch({ type: "selectToggle", id: "module" });
    expect(uiStore.getState().state.selection).toEqual(["roof", "module"]);
    dispatch({ type: "selectAdd", ids: ["roof", "module", "module", "obstacle"] });
    expect(uiStore.getState().state.selection).toEqual(["roof", "module", "obstacle"]);
    dispatch({ type: "selectToggle", id: "module" });
    expect(uiStore.getState().state.selection).toEqual(["roof", "obstacle"]);
    dispatch({ type: "selectToggle", id: "roof" });
    expect(uiStore.getState().state.selection).toEqual(["obstacle"]);
  });
});
