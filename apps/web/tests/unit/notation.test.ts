import { describe, expect, it } from "vitest";
import { formatNotation, parseNotation, stringCount, totalModules } from "../../src/electrical/notation";

describe("MPPT notation", () => {
  it("parses the reference layout (16,0;16,0;16,0;14,14)", () => {
    const { layout, issues } = parseNotation("16,0;16,0;16,0;14,14");
    expect(issues.filter((i) => i.severity === "blocking")).toEqual([]);
    expect(layout?.mppts).toEqual([[16, 0], [16, 0], [16, 0], [14, 14]]);
    expect(totalModules(layout!)).toBe(76);
    expect(stringCount(layout!)).toBe(5);
  });

  it("expands the repeat shorthand", () => {
    const { layout } = parseNotation("3x(16,0); 14,14");
    expect(layout?.mppts).toEqual([[16, 0], [16, 0], [16, 0], [14, 14]]);
  });

  it("round-trips through formatNotation", () => {
    const { layout } = parseNotation("16,0;16,0;16,0;14,14");
    expect(parseNotation(formatNotation(layout!)).layout).toEqual(layout);
  });

  it("blocks non-integer entries", () => {
    const { layout, issues } = parseNotation("16,a");
    expect(layout).toBeNull();
    expect(issues.some((i) => i.severity === "blocking" && i.code === "syntax")).toBe(true);
  });
});
