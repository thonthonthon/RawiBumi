/**
 * Electrical topology commands and live checks, as proposed to the engine in
 * docs/proposals/0004-topology-commands-and-live-checks.md (Track E: E5, E6).
 *
 * The envelope follows the engine's ElectricalTopologyCommand v0.1
 * (apps/web/schema/electrical-topology-command.schema.json): `command_type` and
 * `parameters`. Types already in the engine session keep its names and parameters
 * (create_string, assign_strings_to_mppt, unassign_strings, delete_string,
 * create_strings, assign_strings). The rest are new (E5). Every command is one
 * engine-session undo step; the engine refuses a command that would leave the
 * consistency report with an error.
 */

export type StringOrdering = "row_major" | "serpentine" | "selection";

export type TopologyCommand =
  /** String path (S): modules in wiring order, + first. Optionally assigned to an MPPT in the same step. */
  | { command_type: "create_string"; parameters: { module_instance_ids: string[]; mppt_instance_id?: string | null } }
  | { command_type: "delete_strings"; parameters: { string_ids: string[] } }
  /** Assign brush (A) and MPPT target. */
  | { command_type: "assign_strings_to_mppt"; parameters: { string_ids: string[]; mppt_instance_id: string } }
  | { command_type: "unassign_strings"; parameters: { string_ids: string[] } }
  /** Split (X): the modules after `after_module_instance_id` become a new string; both keep the MPPT. */
  | { command_type: "split_string"; parameters: { string_id: string; after_module_instance_id: string } }
  /** Join (J): `second` is appended to the end of `first` and removed; `first` keeps its MPPT. */
  | { command_type: "join_strings"; parameters: { first_string_id: string; second_string_id: string } }
  /** Reverse (R): wiring order and polarity end swap. */
  | { command_type: "reverse_string"; parameters: { string_id: string } }
  /** Move one module out of its string, optionally into another string at `index` (null: append). */
  | { command_type: "move_module"; parameters: { module_instance_id: string; to_string_id: string | null; index: number | null } }
  /** USE3b: unstrung modules appended to the end of an existing string (one commit). */
  | { command_type: "append_to_string"; parameters: { string_id: string; module_instance_ids: string[] } }
  | { command_type: "swap_modules"; parameters: { first_module_instance_id: string; second_module_instance_id: string } }
  /** Uniform strings; `module_instance_ids` limits them to a selection (lasso), `pv_field_id` to a field. */
  | {
      command_type: "create_strings";
      parameters: { string_length: number; module_instance_ids?: string[] | null; pv_field_id?: string | null; ordering: StringOrdering; allow_shorter_remainder: boolean };
    }
  /** Auto-assign: the given strings (or all unassigned ones) across the inverter's MPPTs. */
  | { command_type: "assign_strings"; parameters: { inverter_instance_id: string; string_ids?: string[] | null } }
  /** Replicate pattern: wire identical explicit tables like the source table (S14b; table ids are per field). */
  | { command_type: "replicate_pattern"; parameters: { source_pv_field_id: string; source_table_id: string; targets?: Array<{ pv_field_id: string; table_id: string }> | null } }
  /**
   * Notation sync: make the inverter's MPPTs carry strings of these lengths
   * (one array per MPPT, one length per input, 0 = empty). Matching strings are kept,
   * missing ones are created from unstrung modules of the paired fields.
   */
  | { command_type: "apply_mppt_layout"; parameters: { inverter_instance_id: string; layout: number[][]; pv_field_ids?: string[] | null; sources?: (string[] | null)[] | null;
      /** UXF3 (U2-25): delete this inverter's released strings so their modules can be re-strung. */ release_modules?: boolean } }
  /** S14b orientation policy: the normal-angle tolerance (≤ 1°), and a per-MPPT override with a reason (null clears). */
  | { command_type: "set_orientation_tolerance"; parameters: { tolerance_deg: number } }
  | { command_type: "set_orientation_override"; parameters: { mppt_instance_id: string; reason: string | null } }
  /** S14b pairing (advisory): the PV fields an inverter draws from; [] clears. */
  | { command_type: "set_inverter_pairing"; parameters: { inverter_instance_id: string; pv_field_ids: string[] } };

export type TopologyCommandType = TopologyCommand["command_type"];

/** One live check on a string or MPPT, from the engine (UI spec B6). The UI shows it, never computes it. */
export interface LiveCheck {
  code: "voltage_window" | "max_voltage" | "current" | "unequal_lengths" | "orientation" | "inputs" | "pairing";
  state: "pass" | "warn" | "fail" | "unavailable";
  message: string;
}

export interface StringCheck {
  string_id: string;
  /** Operating voltage at reference conditions, V, and the MPPT window it is judged against. */
  vmp_v: number | null;
  window_v: [number, number] | null;
  checks: LiveCheck[];
}

export interface TopologyChecks {
  /** Basis of the voltages, e.g. "stc_reference_conditions_only" or the engine's design-temperature rule. */
  basis: string;
  strings: StringCheck[];
}

/** Worst state of a set of checks, for one icon. */
export function worstCheck(checks: readonly LiveCheck[]): LiveCheck["state"] {
  const order: LiveCheck["state"][] = ["fail", "warn", "unavailable", "pass"];
  return order.find((s) => checks.some((c) => c.state === s)) ?? "pass";
}
