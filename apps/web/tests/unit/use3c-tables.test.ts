import { describe, expect, it } from "vitest";
import { legacyFieldInput, legacyRefillRequest, pvFieldChanges, moduleCountOf, type FillZoneRequest, type StoredPvField } from "../../src/engine/layout";
import { fillZone } from "../../src/demo/fillEngine";

const module = { width_m: 1, height_m: 2 };
const request = (changes: Partial<FillZoneRequest> = {}): FillZoneRequest => ({
  pv_field_id: null, name: "Tables", support_surface_id: "roof", module_definition_revision_id: "module",
  orientation: "portrait", azimuth_deg: 0, tilt_deg: 10, mounting_height_m: 1,
  rows_per_table: 2, module_gap_m: 0, in_table_gap_m: .2, pitch: { mode: "fixed_aisle", aisle_m: 1 },
  edge_setbacks_m: [0, 0, 0, 0], keepout_offset_m: 0, leftover_depth: "smaller_table_front", walkway: null, max_table_columns: null,
  ...changes
});

describe("USE3C table fill", () => {
  it("maps all pitch modes and the leftover choice", () => {
    const mapped = legacyFieldInput(request(), module);
    expect(mapped.reasons).toEqual([]);
    expect(mapped.input).toMatchObject({ rows_per_table: 2, leftover_depth: "smaller_table_front", module_gap_y_m: .2 });
    expect(mapped.input!.row_pitch_m).toBeCloseTo(4.2 * Math.cos(Math.PI / 18) + 1, 12);
    expect(legacyFieldInput(request({ pitch: { mode: "gcr", gcr: .5 } }), module).input!.row_pitch_m).toBe(8.4);
    expect(legacyFieldInput(request({ pitch: { mode: "shading_free", sun_elevation_deg: 30, sun_azimuth_offset_deg: 0 } }), module, 6).input!.row_pitch_m).toBe(6);
  });

  it("round trips rows, leftover and aisle; reverting to one row sends the reset", () => {
    const input = legacyFieldInput(request(), module).input!;
    const field = { ...input, pv_field_id: "field", table_configuration: { rows_per_table: 2, leftover_depth: "smaller_table_front" },
      setback_configuration: { perimeter_setback_m: 0, obstacle_setback_m: 0 } } as StoredPvField;
    const refill = legacyRefillRequest(field, module, 4)!;
    expect(refill.rows_per_table).toBe(2);
    expect(refill.leftover_depth).toBe("smaller_table_front");
    expect(refill.pitch).toEqual({ mode: "fixed_aisle", aisle_m: 1 });
    expect(pvFieldChanges(refill, field, module)).toEqual({ changes: {}, reasons: [] });
    expect(pvFieldChanges({ ...refill, rows_per_table: 1 }, field, module).changes.rows_per_table).toBe(1);
    expect(pvFieldChanges({ ...refill, leftover_depth: "smaller_table" }, field, module).changes.leftover_depth).toBe("smaller_table");
  });

  it("demo puts the smaller table on the chosen side and preserves the aisle", () => {
    for (const leftover_depth of ["smaller_table", "smaller_table_front", "leave_empty"] as const) {
      const result = fillZone({ surface: [[0, 0], [3, 0], [3, 12], [0, 12]], obstacles: [], module,
        request: request({ tilt_deg: 0, in_table_gap_m: 0, leftover_depth }), fieldId: "field", pinned: [] });
      expect(result.findings).toEqual([]);
      expect(moduleCountOf(result.tables)).toBe(leftover_depth === "leave_empty" ? 12 : 15);
      const tables = [...result.tables].sort((a, b) => a.origin_m[1] - b.origin_m[1]);
      if (leftover_depth !== "leave_empty") expect(tables[leftover_depth === "smaller_table" ? 0 : tables.length - 1].rows).toBe(1);
      for (let i = 1; i < tables.length; i++)
        expect(tables[i].origin_m[1] - tables[i].rows * 2 - tables[i - 1].origin_m[1]).toBeCloseTo(1, 12);
    }
  });
});
