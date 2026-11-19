import { isExplicitField } from "../types";
import type { Vec2 } from "../geometry";

/**
 * Table-level PV layout contract, as proposed to the engine in
 * docs/proposals/0003-table-level-layout-and-fill-zone.md (Track E: E2, E3, E4, E6).
 * The draft schema is docs/proposals/0003-table-layout.schema.draft.json. When the
 * engine accepts it, these hand-written types are replaced by generated ones.
 *
 * Conventions, the same as the engine's:
 * - plan coordinates in metres, x east, y north;
 * - azimuth 0° = north, clockwise; it is the direction the modules face;
 * - tilt from horizontal, 0 ≤ tilt < 90;
 * - lengths inside a table (module gap, in-table gap) are measured in the module
 *   plane; lengths between tables (aisle, setbacks, walkways) on the support surface.
 */

export type Orientation = "portrait" | "landscape";

/** How the distance from one table to the next is set (B5, E4). */
export type PitchRule =
  /** A fixed clear aisle on the roof between the back of one table and the front of the next. */
  | { mode: "fixed_aisle"; aisle_m: number }
  /** Ground coverage ratio: table slant depth ÷ pitch. */
  | { mode: "gcr"; gcr: number }
  /**
   * No row-to-row shading while the sun is at least this high and within this
   * angle of the array's facing direction. The engine is to derive both from a
   * time window at the site (proposal 0003); the demo takes them directly.
   */
  | { mode: "shading_free"; sun_elevation_deg: number; sun_azimuth_offset_deg: number };

export type LeftoverDepth =
  /** Use the leftover depth for a table with fewer rows, if at least one row fits. */
  | "smaller_table"
  | "smaller_table_front"
  /** Leave it empty: every table has the full number of rows. */
  | "leave_empty";

export interface FillZoneRequest {
  pv_field_id: string | null; // null: a new field
  name: string;
  support_surface_id: string;
  module_definition_revision_id: string;
  orientation: Orientation;
  azimuth_deg: number;
  tilt_deg: number;
  mounting_height_m: number;
  rows_per_table: number;
  module_gap_m: number;
  in_table_gap_m: number;
  pitch: PitchRule;
  /** Setback from each edge of the support surface, by edge index (edge i runs from vertex i to i+1). */
  edge_setbacks_m: number[];
  /** Clearance around obstacles and keep-out zones. */
  keepout_offset_m: number;
  leftover_depth: LeftoverDepth;
  /** A cross walkway after every N modules along a row; null for none. */
  walkway: { every_modules: number; width_m: number } | null;
  /** Largest table, in modules along the row; null for no cap. */
  max_table_columns: number | null;
  /** UXF1 (U2-6): along the rows (start = row start). Absent: start. */
  row_alignment?: Alignment;
  /** UXF1 (U2-6): across the rows (start = back/high side, end = front/low side). Absent: the most-modules grid. */
  depth_alignment?: Alignment | null;
}
export type Alignment = "start" | "center" | "end";

/** A removed slot: [row, column, why]. Row 0 is the front row; column 0 the first along the row. */
export type RemovedSlot = [row: number, column: number, reason: "geometry" | "manual"];

/**
 * One table (E2): a rows × columns grid of identical slots, placed by its
 * front-left corner and the field's azimuth. Modules are the slots that are not
 * removed. Module ids are `${table_id}/${row}.${column}`.
 */
export interface TableRecord {
  table_id: string;
  pv_field_id: string;
  /** Front-left corner of the table footprint in plan, m. */
  origin_m: Vec2;
  /** Facing direction, the field's azimuth. */
  azimuth_deg: number;
  rows: number;
  columns: number;
  orientation: Orientation;
  /** Plan footprint of one module (along the row, front to back), m. */
  module_plan_m: [number, number];
  /** Plan distance between slot origins (along the row, front to back), m. */
  slot_pitch_m: [number, number];
  removed_slots: RemovedSlot[];
  /** Pinned tables survive a re-fill unchanged; a manual edit pins a table. */
  pinned: boolean;
  /** A pinned deleted table keeps its footprint empty on re-fill. */
  status: "active" | "deleted";
}

export interface TableLayoutView {
  /** Fill request of each table-level field, so a re-fill can start from it. */
  requests: Record<string, FillZoneRequest>;
  tables: TableRecord[];
}

export interface LayoutDiff {
  modules_before: number;
  modules_after: number;
  tables_added: number;
  tables_removed: number;
  tables_unchanged: number;
  tables_pinned_kept: number;
  /** Strings that lose at least one module. */
  strings_affected: string[];
}

export interface LayoutFinding {
  severity: "blocking" | "warning" | "info";
  code: string;
  message: string;
}

export interface FillPreview {
  request: FillZoneRequest;
  tables: TableRecord[];
  module_count: number;
  /** The same request in each orientation, for the comparison before Apply. */
  compare: Record<Orientation, number>;
  /** Pitch the rule produced, m, front of one table to the front of the next. */
  pitch_m: number;
  /** Usable region after setbacks and keep-out offsets, plan polygons. */
  usable_region: Vec2[][];
  diff: LayoutDiff;
  findings: LayoutFinding[];
}

export type TableEditCommand =
  | { kind: "move_tables"; table_ids: string[]; dx_m: number; dy_m: number }
  | { kind: "delete_tables"; table_ids: string[] }
  | { kind: "delete_modules"; module_instance_ids: string[] }
  | { kind: "unpin_tables"; table_ids: string[] };

/** Splits a module id into its table and slot. Null for modules not in a table record. */
export function slotOf(moduleId: string): { tableId: string; row: number; column: number } | null {
  const m = /^(.+)\/(\d+)\.(\d+)$/.exec(moduleId);
  return m ? { tableId: m[1], row: Number(m[2]), column: Number(m[3]) } : null;
}

export const moduleIdOf = (tableId: string, row: number, column: number) => `${tableId}/${row}.${column}`;

/** Unit vectors of a field: along the row, and front to back (away from the azimuth). */
export function fieldAxes(azimuthDeg: number): { along: Vec2; back: Vec2 } {
  const a = (azimuthDeg * Math.PI) / 180;
  const facing: Vec2 = [Math.sin(a), Math.cos(a)];
  return { along: [facing[1], -facing[0]], back: [-facing[0], -facing[1]] };
}

/** Plan polygon of one slot of a table. */
export function slotPolygon(t: TableRecord, row: number, column: number): Vec2[] {
  const { along, back } = fieldAxes(t.azimuth_deg);
  const u0 = column * t.slot_pitch_m[0];
  const v0 = row * t.slot_pitch_m[1];
  const [w, d] = t.module_plan_m;
  const at = (u: number, v: number): Vec2 => [t.origin_m[0] + along[0] * u + back[0] * v, t.origin_m[1] + along[1] * u + back[1] * v];
  return [at(u0, v0), at(u0 + w, v0), at(u0 + w, v0 + d), at(u0, v0 + d)];
}

/** Plan footprint of a whole table, all slots included. */
export function tableFootprint(t: TableRecord): Vec2[] {
  const { along, back } = fieldAxes(t.azimuth_deg);
  const w = (t.columns - 1) * t.slot_pitch_m[0] + t.module_plan_m[0];
  const d = (t.rows - 1) * t.slot_pitch_m[1] + t.module_plan_m[1];
  const at = (u: number, v: number): Vec2 => [t.origin_m[0] + along[0] * u + back[0] * v, t.origin_m[1] + along[1] * u + back[1] * v];
  return [at(0, 0), at(w, 0), at(w, d), at(0, d)];
}

/** The modules of a table: every slot that is not removed. */
export function tableModules(t: TableRecord): Array<{ id: string; row: number; column: number; polygon: Vec2[] }> {
  if (t.status === "deleted") return [];
  const removed = new Set(t.removed_slots.map(([r, c]) => `${r}.${c}`));
  const out: Array<{ id: string; row: number; column: number; polygon: Vec2[] }> = [];
  for (let r = 0; r < t.rows; r++)
    for (let c = 0; c < t.columns; c++) {
      if (removed.has(`${r}.${c}`)) continue;
      out.push({ id: moduleIdOf(t.table_id, r, c), row: r, column: c, polygon: slotPolygon(t, r, c) });
    }
  return out;
}

export const moduleCountOf = (tables: readonly TableRecord[]) =>
  tables.reduce((n, t) => n + (t.status === "deleted" ? 0 : t.rows * t.columns - t.removed_slots.length), 0);

/** The engine's existing PV field route (POST /api/projects/{id}/pv-fields). */
export interface LegacyFieldInput {
  rows_per_table?: number;
  leftover_depth?: LeftoverDepth;
  name: string;
  support_surface_id: string;
  module_definition_revision_id: string;
  orientation: string;
  azimuth_deg: number;
  tilt_deg: number;
  module_gap_x_m: number;
  module_gap_y_m: number;
  row_pitch_m: number;
  mounting_height_m: number;
  perimeter_setback_m: number;
  obstacle_setback_m: number;
  row_alignment?: Alignment;
  depth_alignment?: Alignment;
}

/**
 * Maps a fill request onto the route the engine already has, when the request
 * uses only what that route supports: one setback for every
 * edge, no walkway, no size cap, and a fixed aisle or a GCR. Converting the aisle
 * or GCR to the route's row pitch uses the module's own length and the tilt; the
 * engine then checks the pitch again. Anything else returns the reasons, and the
 * fill waits for proposal 0003.
 */
export function legacyFieldInput(
  r: FillZoneRequest,
  module: { width_m: number; height_m: number },
  /** USE1: the engine's shading-free row pitch for this request, once fetched (POST /pv-fields/shading-free-pitch). */
  shadingFreePitchM?: number | null
): { input: LegacyFieldInput; reasons: [] } | { input: null; reasons: string[] } {
  const reasons: string[] = [];
  if (r.pv_field_id) reasons.push("re-fill of an existing field");
  const s = r.edge_setbacks_m;
  if (s.some((x) => Math.abs(x - s[0]) > 1e-9)) reasons.push("different setbacks per edge");
  if (r.walkway) reasons.push("walkways");
  if (r.max_table_columns !== null) reasons.push("a table size cap");
  if (r.pitch.mode === "shading_free" && !(shadingFreePitchM && shadingFreePitchM > 0)) reasons.push("the shading-free pitch mode");
  if (reasons.length) return { input: null, reasons };
  const slant = r.orientation === "portrait" ? Math.max(module.width_m, module.height_m) : Math.min(module.width_m, module.height_m);
  const depth = r.rows_per_table * slant + (r.rows_per_table - 1) * r.in_table_gap_m;
  const plan = depth * Math.cos((r.tilt_deg * Math.PI) / 180);
  const pitch = r.pitch.mode === "fixed_aisle" ? plan + r.pitch.aisle_m : r.pitch.mode === "gcr" ? depth / r.pitch.gcr : shadingFreePitchM!;
  return {
    input: {
      ...(r.rows_per_table > 1 ? { rows_per_table: r.rows_per_table, leftover_depth: r.leftover_depth } : {}),
      name: r.name,
      support_surface_id: r.support_surface_id,
      module_definition_revision_id: r.module_definition_revision_id,
      orientation: r.orientation,
      azimuth_deg: r.azimuth_deg,
      tilt_deg: r.tilt_deg,
      module_gap_x_m: r.module_gap_m,
      module_gap_y_m: r.in_table_gap_m,
      row_pitch_m: pitch,
      mounting_height_m: r.mounting_height_m,
      perimeter_setback_m: s[0] ?? 0,
      obstacle_setback_m: r.keepout_offset_m,
      // Sent only when chosen, so a default fill sends the same request as before.
      ...(r.row_alignment && r.row_alignment !== "start" ? { row_alignment: r.row_alignment } : {}),
      ...(r.depth_alignment ? { depth_alignment: r.depth_alignment } : {})
    },
    reasons: []
  };
}

/** Re-fill preserves its roof and untouched inputs; RF1 permits a module rebind. */
export type StoredPvField = import("../types").ProjectBundle["scene"]["pv_fields"][number]
  & Pick<import("../generated/schemas/scene").PvField, "table_configuration" | "packing_parameters">;
export type PvFieldChanges = Partial<Omit<LegacyFieldInput, "support_surface_id">>;
export interface PvFieldOptions { discard_dependent_strings?: boolean; discard_manual_layout?: boolean }
export interface PvFieldDeletePreview {
  dry_run: true; pv_field_id: string; module_count: number; stc_power_w: number;
  string_ids: string[]; requires_discard_dependent_strings: boolean;
}
export interface PvFieldUpdatePreview {
  dry_run: true; pv_field_id: string;
  module_count_before: number; module_count_after: number;
  stc_power_w_before: number; stc_power_w_after: number;
  string_ids: string[]; requires_discard_dependent_strings: boolean;
  requires_discard_manual_layout: boolean; conflicts: unknown[];
}

export function missingRefillParameters(field: StoredPvField): string[] {
  if (isExplicitField(field)) return ["explicit_layout_read_only"];
  const values = {
    module_gap_x_m: field.module_gap_x_m, module_gap_y_m: field.module_gap_y_m,
    row_pitch_m: field.row_pitch_m, mounting_height_m: field.mounting_height_m,
    "setback_configuration.perimeter_setback_m": field.setback_configuration?.perimeter_setback_m,
    "setback_configuration.obstacle_setback_m": field.setback_configuration?.obstacle_setback_m
  };
  return Object.entries(values).filter(([, v]) => typeof v !== "number" || !Number.isFinite(v)).map(([key]) => key);
}

export function legacyRefillRequest(field: StoredPvField, module: { width_m: number; height_m: number }, edgeCount: number): FillZoneRequest | null {
  if (isExplicitField(field) || missingRefillParameters(field).length) return null;
  const slant = field.orientation === "portrait" ? Math.max(module.width_m, module.height_m) : Math.min(module.width_m, module.height_m);
  const rows = field.table_configuration?.rows_per_table ?? 1;
  const depth = rows * slant + (rows - 1) * field.module_gap_y_m!;
  return {
    pv_field_id: field.pv_field_id, name: field.name, support_surface_id: field.support_surface_id,
    module_definition_revision_id: field.module_definition_revision_id, orientation: field.orientation as Orientation,
    azimuth_deg: field.azimuth_deg, tilt_deg: field.tilt_deg, mounting_height_m: field.mounting_height_m!,
    rows_per_table: rows, module_gap_m: field.module_gap_x_m!, in_table_gap_m: field.module_gap_y_m!,
    pitch: { mode: "fixed_aisle", aisle_m: field.row_pitch_m! - depth * Math.cos(field.tilt_deg * Math.PI / 180) },
    edge_setbacks_m: Array(edgeCount).fill(field.setback_configuration!.perimeter_setback_m!),
    keepout_offset_m: field.setback_configuration!.obstacle_setback_m!,
    leftover_depth: field.table_configuration?.leftover_depth ?? "smaller_table", walkway: null, max_table_columns: null,
    row_alignment: field.packing_parameters?.row_alignment ?? "start", depth_alignment: field.packing_parameters?.depth_alignment ?? null
  };
}

export function pvFieldChanges(request: FillZoneRequest, field: StoredPvField, module: { width_m: number; height_m: number }, shadingFreePitchM?: number | null): { changes: PvFieldChanges; reasons: string[] } {
  if (isExplicitField(field)) return {changes: {}, reasons: ["Explicit layouts are read-only."]};
  const missing = missingRefillParameters(field);
  if (missing.length) return { changes: {}, reasons: missing };
  if (!Number.isFinite(request.azimuth_deg) || request.azimuth_deg < 0 || request.azimuth_deg >= 360)
    return { changes: {}, reasons: ["azimuth_deg must be within [0, 360)"] };
  const mapped = legacyFieldInput({ ...request, pv_field_id: null }, module, shadingFreePitchM);
  if (!mapped.input) return { changes: {}, reasons: mapped.reasons };
  if (request.support_surface_id !== field.support_surface_id)
    return { changes: {}, reasons: ["A re-fill keeps the support surface."] };
  const { support_surface_id: _surface, ...values } = mapped.input;
  if (request.rows_per_table === 1 && (field.table_configuration?.rows_per_table ?? 1) > 1)
    values.rows_per_table = 1;
  if (request.row_alignment && request.row_alignment !== (field.packing_parameters?.row_alignment ?? "start"))
    values.row_alignment = request.row_alignment;
  const stored = { ...field, rows_per_table: field.table_configuration?.rows_per_table ?? 1,
    leftover_depth: field.table_configuration?.leftover_depth ?? "smaller_table", perimeter_setback_m: field.setback_configuration!.perimeter_setback_m,
    obstacle_setback_m: field.setback_configuration!.obstacle_setback_m,
    row_alignment: field.packing_parameters?.row_alignment ?? "start", depth_alignment: field.packing_parameters?.depth_alignment };
  const changes = Object.fromEntries(Object.entries(values).filter(([key, value]) => {
    const previous = stored[key as keyof typeof stored];
    return typeof value === "number" && typeof previous === "number" ? Math.abs(value - previous) > 1e-9 : value !== previous;
  })) as PvFieldChanges;
  return { changes, reasons: [] };
}
