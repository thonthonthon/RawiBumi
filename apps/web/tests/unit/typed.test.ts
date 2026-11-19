import { describe, expect, it } from "vitest";
import { evalExpr, parseAngle, parsePoint, resolvePoint, TypedError } from "../../src/canvas/plan/typed";

describe("typed input", () => {
  it("evaluates arithmetic and units", () => {
    expect(evalExpr("12-2*0.4")).toBeCloseTo(11.2, 12);
    expect(evalExpr("(1+2)*3")).toBe(9);
    expect(evalExpr("250cm")).toBeCloseTo(2.5, 12);
    expect(evalExpr("1200mm+0.3")).toBeCloseTo(1.5, 12);
    expect(evalExpr("-3")).toBe(-3);
    expect(() => evalExpr("2/0")).toThrow(TypedError);
    expect(() => evalExpr("abc")).toThrow(TypedError);
  });

  it("reads absolute, relative, polar and distance entries", () => {
    expect(parsePoint("3,4", false)).toEqual({ kind: "absolute", p: [3, 4] });
    expect(parsePoint("@2,-1", true)).toEqual({ kind: "relative", d: [2, -1] });
    expect(parsePoint("10<90", true)).toEqual({ kind: "polar", distance: 10, bearingDeg: 90 });
    expect(parsePoint("@5<-90", true)).toEqual({ kind: "polar", distance: 5, bearingDeg: 270 });
    expect(parsePoint("6", true)).toEqual({ kind: "distance", distance: 6 });
    expect(parsePoint("(1+1),3*2", false)).toEqual({ kind: "absolute", p: [2, 6] });
  });

  it("refuses entries that need a previous point, and ambiguous ones", () => {
    expect(() => parsePoint("@1,1", false)).toThrow(TypedError);
    expect(() => parsePoint("5<45", false)).toThrow(TypedError);
    expect(() => parsePoint("5", false)).toThrow(TypedError);
    expect(() => parsePoint("1,2,3", false)).toThrow(TypedError);
  });

  it("resolves to world points with bearings from north, clockwise", () => {
    const last: [number, number] = [10, 10];
    const east = resolvePoint({ kind: "polar", distance: 2, bearingDeg: 90 }, last, null);
    expect(east[0]).toBeCloseTo(12, 12);
    expect(east[1]).toBeCloseTo(10, 12);
    const north = resolvePoint({ kind: "polar", distance: 2, bearingDeg: 0 }, last, null);
    expect(north[1]).toBeCloseTo(12, 12);
    expect(resolvePoint({ kind: "relative", d: [1, -2] }, last, null)).toEqual([11, 8]);
    const along = resolvePoint({ kind: "distance", distance: 5 }, [0, 0], [3, 4]);
    expect(along[0]).toBeCloseTo(3, 12);
    expect(along[1]).toBeCloseTo(4, 12);
  });

  it("reads rotation angles in degrees, clockwise positive", () => {
    expect(parseAngle("15")).toBe(15);
    expect(parseAngle("-90°")).toBe(-90);
    expect(parseAngle("45deg")).toBe(45);
    expect(() => parseAngle("10cm")).toThrow(TypedError);
  });
});
