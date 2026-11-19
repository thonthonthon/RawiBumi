import type { FillZoneRequest } from "../../src/engine/layout";

/** The plan's golden fill request (B5): 2 rows per table, 5 cm gaps, 1 m aisle, 40 cm setback, flat. */
export function goldenRequest(over: Partial<FillZoneRequest> = {}): FillZoneRequest {
  return {
    pv_field_id: null,
    name: "Golden",
    support_surface_id: "srf",
    module_definition_revision_id: "mod",
    orientation: "portrait",
    azimuth_deg: 0,
    tilt_deg: 0,
    mounting_height_m: 0.2,
    rows_per_table: 2,
    module_gap_m: 0.05,
    in_table_gap_m: 0.05,
    pitch: { mode: "fixed_aisle", aisle_m: 1 },
    edge_setbacks_m: [0.4, 0.4, 0.4, 0.4],
    keepout_offset_m: 0.3,
    leftover_depth: "smaller_table",
    walkway: null,
    max_table_columns: null,
    ...over
  };
}
