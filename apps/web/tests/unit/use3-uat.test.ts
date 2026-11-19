import { describe, expect, it } from "vitest";
import { isParallelToRoof, parallelMounting } from "../../src/panels/LayoutPanel";
import { brandsOf, filterComponents, NO_FILTER } from "../../src/ui/ComponentFilter";

// USE3: the components filter and parallel-to-roof mounting.
const items = [
  { revision_id: "h20", manufacturer: "Huawei", model: "SUN2000-20KTL-M2", synthetic_reference: false, simulation_ready: false },
  { revision_id: "h50", manufacturer: "Huawei", model: "SUN2000-50KTL-M3", synthetic_reference: false, simulation_ready: true },
  { revision_id: "s10", manufacturer: "Sungrow", model: "SG10RT", synthetic_reference: false, simulation_ready: true },
  { revision_id: "test", manufacturer: "RawiBumi", model: "UAT", synthetic_reference: true, simulation_ready: true },
  { revision_id: "old", manufacturer: "Huawei", model: "SUN2000-20KTL-M2", synthetic_reference: false, superseded_by: "h20b" }
];
const ids = (xs: { revision_id: string }[]) => xs.map((x) => x.revision_id);

describe("components filter", () => {
  it("filters by brand, status and text; hides test and superseded parts; keeps the current choice", () => {
    expect(ids(filterComponents(items, NO_FILTER, false))).toEqual(["h20", "h50", "s10"]);
    expect(ids(filterComponents(items, { ...NO_FILTER, brand: "Huawei" }, false))).toEqual(["h20", "h50"]);
    expect(ids(filterComponents(items, { ...NO_FILTER, status: "layout_only" }, false))).toEqual(["h20"]);
    expect(ids(filterComponents(items, { ...NO_FILTER, status: "ready" }, true))).toEqual(["h50", "s10", "test"]);
    expect(ids(filterComponents(items, { ...NO_FILTER, query: "50ktl" }, false))).toEqual(["h50"]);
    expect(ids(filterComponents(items, { ...NO_FILTER, brand: "Sungrow" }, false, "h20"))).toEqual(["h20", "s10"]);
    expect(brandsOf(items, false)).toEqual(["Huawei", "Sungrow"]);
  });
});

describe("parallel to roof", () => {
  const roof = { slope_deg: 12, azimuth_deg: 180 };
  it("takes tilt and azimuth from a sloped roof, tilt 0 on a flat one, and nothing in rack mode", () => {
    expect(parallelMounting({ tilt: 10, azimuth: 0, parallel: true }, roof)).toEqual({ tilt: 12, azimuth: 180, azimuthFromRoof: true });
    expect(parallelMounting({ tilt: 10, azimuth: 90, parallel: true }, { slope_deg: 0 })).toEqual({ tilt: 0, azimuth: 90, azimuthFromRoof: false });
    expect(parallelMounting({ tilt: 10, azimuth: 0, parallel: false }, roof)).toEqual({ tilt: 10, azimuth: 0, azimuthFromRoof: false });
  });
  it("recognises a stored parallel field", () => {
    expect(isParallelToRoof({ tilt_deg: 12, azimuth_deg: 180 }, roof)).toBe(true);
    expect(isParallelToRoof({ tilt_deg: 12, azimuth_deg: 0 }, roof)).toBe(false);
    expect(isParallelToRoof({ tilt_deg: 0, azimuth_deg: 37 }, { slope_deg: 0 })).toBe(true);
    expect(isParallelToRoof({ tilt_deg: 10, azimuth_deg: 0 }, { slope_deg: 0 })).toBe(false);
  });
});
