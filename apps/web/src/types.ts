import type { TableLayoutView } from "./engine/layout";
import type { TopologyChecks } from "./engine/topology";
export type WorkspaceMode = "map_overlay" | "blank_engineering_plane";

export type ModuleCommandInput = {
  module_instance_ids: string[];
  discard_dependent_strings?: boolean;
  dry_run?: boolean;
} & ({ command: "delete_modules" } | { command: "move_modules"; dx_m: number; dy_m: number; on_conflict?: "reject" | "fill" });
export interface ModuleDeletePreview {
  dry_run: true;
  command: "delete_modules";
  module_count: number;
  string_ids: string[];
  requires_discard_dependent_strings: boolean;
  fields: Array<{
    pv_field_id: string; name: string;
    module_count_before: number; module_count_after: number;
    stc_power_w_before: number; stc_power_w_after: number;
    string_ids: string[]; field_becomes_empty: boolean;
  }>;
}
export interface ModuleMoveReason { code: string; count: number; message: string; name?: string; setback?: number }
export interface ModuleFillPreview {
  dry_run: true; mode: "fill"; placed_count: number; removed_count: number;
  placed_ids: string[]; removed_ids: string[]; string_ids: string[];
  requires_discard_dependent_strings: boolean; stc_power_w_before: number; stc_power_w_after: number;
  reasons: ModuleMoveReason[];
}
export interface ModuleMovePreview {
  dry_run: true; command: "move_modules"; moved_count: number;
  reasons?: ModuleMoveReason[];
  conflicts: Array<{ code: string; module_instance_id: string | null; other_id: string | null; pv_field_id: string | null }>;
}
export type ModuleCommandResult<I extends ModuleCommandInput> = I extends { dry_run: true }
  ? I extends { command: "delete_modules" } ? ModuleDeletePreview
    : I extends { on_conflict: "fill" } ? ModuleMovePreview | ModuleFillPreview : ModuleMovePreview
  : ProjectView;

export interface SceneCommandInput {
  command_id?: string;
  command_type: "set_reference_anchor" | "scale" | "edit_exact_angle" | "rotate" | "move" | "move_vertex" | "insert_vertex" | "delete_vertex" | "move_edge" | "edit_height" | "edit_plane" | "add_hole" | "remove_hole" | "edit_exact_dimension" | "edit_elevation" | "delete" | "draw_polygon" | "copy" | "group" | "ungroup";
  target_entity_ids: string[];
  parameters: Record<string, unknown>;
}
export interface SceneConflictOptions {
  dependent_fields?: "reject" | "apply";
  on_module_conflict?: "reject" | "remove_modules" | "refill_field";
  discard_dependent_strings?: boolean;
  discard_manual_layout?: boolean;
  dry_run?: boolean;
}
export interface ObstacleConflictDetail {
  message?: string;
  conflicts: Array<Record<string, unknown>>;
  options: {
    remove_modules: { module_instance_ids: string[]; module_count: number; stc_power_w: number; string_ids: string[] };
    refill_field: {
      available: boolean; reason?: string; message?: string; string_ids?: string[];
      requires_discard_manual_layout?: boolean;
      fields?: Array<{ pv_field_id: string; module_count_before: number; module_count_after: number; stc_power_w_before: number; stc_power_w_after: number }>;
    };
  };
}
export interface DependentFieldPreview {
  pv_field_id: string; name: string; action: "refill" | "delete";
  module_count_before: number; module_count_after: number;
  stc_power_w_before: number; stc_power_w_after: number;
  string_ids: string[]; requires_discard_dependent_strings: boolean;
  requires_discard_manual_layout: boolean; conflicts: Array<Record<string, unknown>>;
}
export interface ScenePreview {
  ignored_by_fields?: Array<{ pv_field_id: string; reason: "field_exclusion_rules_ignore_keepout" }>;
  dependent_fields?: DependentFieldPreview[];
  dry_run: true;
  conflicts: Array<Record<string, unknown>>;
  options?: ObstacleConflictDetail["options"];
}
export type SceneResult<O> = O extends { dry_run: true } ? ScenePreview : ProjectView;
export interface PolygonObstacleInput {
  name: string;
  vertices: [number, number][];
  base_elevation_m: number;
  height_m: number;
}


export interface ProjectSummary {
  project_id: string;
  name: string;
  /** "unreadable" (DATA1): the file is damaged; it is listed, with `reason`, so it can be restored from a backup. */
  status: string;
  reason?: string;
  latitude_deg: number | null;
  longitude_deg: number | null;
  timezone: string | null;
  updated_at?: string | null;
}

export interface ProjectSystemSummary {
  modules: { model: string; manufacturer?: string | null; count: number; rating_w: number | null }[];
  dc_kwp: number;
  inverters: { model: string; manufacturer?: string | null; count: number; rating_w: number | null }[];
  ac_kw: number;
  last_run: null | { simulation_run_id: string; period_start_time?: string; period_end_time?: string; energy_kwh: number; annual: boolean;
    specific_yield_kwh_kwp: number; performance_ratio: number | null };
}

/** DATA1: a rolling (last 20 saves) or protected backup of a project file. */
export interface ProjectBackup { backup_id: string; saved_at: string; revision_number: number | null; protected: boolean; reason: string | null; bytes: number }


export type ElectricalShadingFidelity =
  | "level_0_geometric_only"
  | "level_1_module_approximation"
  | "level_2_bypass_substring"
  | "level_3_cell_submodule_iv";


export interface ElectricalShadingCapabilitySummary {
  module_revision_id: string;
  topology_revision_ids: string[];
  topology_selection_required: boolean;
  maximum_fidelity_without_topology_selection: ElectricalShadingFidelity;
  available_fidelity_without_topology_selection: ElectricalShadingFidelity[];
  findings: Array<Record<string, unknown>>;
}


export interface CatalogTopology {
  source?: "reference";
  revision_id: string;
  module_definition_revision_id: string;
  region_resolution: string;
  verification_state: string;
  topology_provenance: string;
  source_ids: string[];
  bypass_coverage_complete: boolean;
  synthetic_reference: boolean;
}


export interface ElectricalShadingSelection {
  state_version: string;
  module_definition_revision_id: string;
  module_topology_revision_id: string | null;
  region_parameterization_evidence_id: string | null;
  cell_parameterization_evidence_id: string | null;
  requested_fidelity: ElectricalShadingFidelity;
  resolved_fidelity: ElectricalShadingFidelity;
  fallback_policy: "fail_closed" | "explicit_lower_fidelity";
  fallback_applied: boolean;
  fallback_reason: string | null;
  selection_payload_sha256: string;
  capability_snapshot: {
    available_fidelity_levels: ElectricalShadingFidelity[];
    maximum_fidelity_level: ElectricalShadingFidelity;
    bypass_assumption_ids: string[];
    findings: Array<Record<string, unknown>>;
  };
}


export interface ComponentLibraryFinding {
  rule_id: string; message: string; severity: string; classification?: string;
}
export interface ComponentCompletionSource { document: string; page_or_section: string; url?: string }
export interface ComponentCompletionInput { fields: Record<string, number>; source: ComponentCompletionSource }
export interface ComponentCompletionField { path: string; unit: string; max: number }
export interface ComponentLibraryReason { code: string; message: string; rule_ids?: string[]; rule_id?: string }
export interface ComponentLibraryPreview {
  kind: "modules" | "inverters"; manufacturer: string | null; model: string | null;
  revision_id: string; duplicate_of: string | null;
  remapped_from?: string | null;
  parameters: Record<string, number | string | null>;
  findings: ComponentLibraryFinding[]; schema_ready: boolean; simulation_ready: boolean;
  readiness_findings: ComponentLibraryFinding[]; reasons: ComponentLibraryReason[];
  completion_fields?: ComponentCompletionField[];
  completed_from?: string | null;
  completed_fields?: { path: string; value: number; unit: string; source: ComponentCompletionSource }[];
}
export interface ComponentLibraryEntry {
  completion_preview?: ComponentLibraryPreview;
  kind: "modules" | "inverters";
  definition: { revision_id: string; manufacturer: string; model: string };
  library: {
    definition_id: string; revision_number: number; source_filename: string; source_sha256: string;
    source_format: "pan" | "ond"; source_encoding: "utf-8" | "cp1252"; imported_at: string; hidden: boolean;
    importer_version?: number; remapped_from?: string;
    findings: ComponentLibraryFinding[]; schema_ready: boolean;
    readiness: { ready: boolean; findings: ComponentLibraryFinding[] };
  };
}
export interface ComponentLibraryCommit { entry: ComponentLibraryPreview; created: boolean }

/** Library suffixes are display text; reference labels remain unchanged. */
export function componentCatalogLabel(item: { source?: "reference" | "library"; simulation_ready?: boolean }, base: string, library: string, layoutOnly: string): string {
  return base + (item.source === "library" ? ` · ${library}${item.simulation_ready ? "" : ` · ${layoutOnly}`}` : "");
}


/** D14: one module's DC nameplate, the kWp basis everywhere (the engine's installed-DC rule). */
export const moduleNameplateW = (m: Pick<CatalogModule, "pmp_w" | "nominal_power_w">): number => m.nominal_power_w ?? m.pmp_w;

export interface CatalogModule {
  source?: "reference" | "library";
  revision_id: string;
  manufacturer: string;
  model: string;
  /** STC maximum power (the module model's value for a PAN import). */
  pmp_w: number;
  /** D14: the DC nameplate (datasheet nominal power, else STC Pmp); absent from older servers and the demo. */
  nominal_power_w?: number | null;
  width_m: number;
  height_m: number;
  synthetic_reference: boolean;
  simulation_ready?: boolean;
  electrical_shading?: ElectricalShadingCapabilitySummary;
  superseded_by?: string;
}


export interface CatalogInverter {
  source?: "reference" | "library";
  revision_id: string;
  manufacturer: string;
  model: string;
  nominal_ac_power_w: number;
  mppt_count: number;
  synthetic_reference: boolean;
  simulation_ready?: boolean;
  execution_readiness_findings?: ExecutionReadinessFinding[];
  /** USE-D4: DC inputs per MPPT, stated or derived from the total; with where it came from. */
  inputs_per_mppt?: number | null;
  inputs_per_mppt_source?: string | null;
  /** USE1: a hidden revision completed from datasheet values names its successor. */
  superseded_by?: string;
}


export interface Catalog {
  modules: CatalogModule[];
  inverters: CatalogInverter[];
  module_topologies: CatalogTopology[];
}


export interface LocalFeature {
  id: string;
  category: "surface" | "obstacle" | "module";
  subtype: string;
  name: string;
  pv_field_id?: string;
  polygon: [number, number][];
}


export interface SiteSummary {
  latitude_deg: number;
  longitude_deg: number;
  elevation_m?: number | null;
  timezone: string;
  north_reference: string;
}


export interface SceneGeoJsonFeature {
  type: "Feature";
  id?: string | number;
  properties: Record<string, unknown> | null;
  geometry: {
    type: "Polygon";
    coordinates: number[][][];
  };
}


export interface SceneGeoJson {
  type: "FeatureCollection";
  features: SceneGeoJsonFeature[];
}


export interface SceneView {
  geometry_objects?: Array<{id: string; kind: "mesh" | "explicit_module"; name: string; pv_field_id?: string;
    status?: "resolved" | "unresolved"; message?: string;
    plan_geometry: {type: "Polygon"; coordinates: number[][][]} | {type: "LineString"; coordinates: number[][]} | {type: "Point"; coordinates: number[]} | null}>;
  local_features: LocalFeature[];
  geojson: SceneGeoJson;
  site: SiteSummary;
}


/** Generated fields retain the existing field-wide packing inputs. */
export interface GeneratedPvField {
  field_kind?: "generated";

      pv_field_id: string;
      name: string;
      support_surface_id: string;
      module_definition_revision_id: string;
      row_count: number;
      modules_per_row: number;
      orientation: string;
      azimuth_deg: number;
      tilt_deg: number;
      module_gap_x_m?: number;
      module_gap_y_m?: number;
      row_pitch_m?: number;
      mounting_height_m?: number;
      setback_configuration?: { perimeter_setback_m?: number; obstacle_setback_m?: number };
      layout_status?: string;
      exclusion_rules?: { use_scene_exclusion_surfaces?: boolean; surface_types?: string[]; surface_ids?: string[] };
    }
export interface ExplicitTable {
  table_id: string;
  module_definition_revision_id: string;
  support_surface_id?: string;
  tilt_deg: number;
  azimuth_deg: number;
  module_orientation: "portrait" | "landscape";
  modules_across: number;
  modules_up: number;
}
export interface ExplicitPvField {
  field_kind: "explicit_layout";
  pv_field_id: string;
  name: string;
  tables: ExplicitTable[];
  layout_status?: string;
}
export type PvField = GeneratedPvField | ExplicitPvField;
export const isExplicitField = (field: PvField): field is ExplicitPvField => field.field_kind === "explicit_layout";
export const isGeneratedField = (field: PvField): field is GeneratedPvField => !isExplicitField(field);
export function fieldSupportIds(field: PvField): string[] {
  return isExplicitField(field) ? [...new Set(field.tables.flatMap(t => t.support_surface_id ? [t.support_surface_id] : []))] : [field.support_surface_id];
}
/** Resolve the actual module/table, never a first-table surrogate. */
export function modulePlacement(view: ProjectView, moduleId: string) {
  const instance = view.bundle.scene.module_instances.find(m => m.module_instance_id === moduleId);
  const field = view.bundle.scene.pv_fields.find(f => f.pv_field_id === instance?.pv_field_id);
  if (!field) return undefined;
  if (isExplicitField(field)) {
    const table = field.tables.find(t => t.table_id === instance?.table_id);
    if (!table) return undefined;
    return { field, tableId: table.table_id, revisionId: table.module_definition_revision_id,
      tiltDeg: table.tilt_deg, azimuthDeg: table.azimuth_deg, orientation: table.module_orientation };
  }
  return { field, tableId: null, revisionId: field.module_definition_revision_id,
    tiltDeg: field.tilt_deg, azimuthDeg: field.azimuth_deg, orientation: field.orientation };
}
export interface ExactSceneGeometry {
  source_scene_hash: string;
  source_scene_revision_id: string;
  obstacles: Array<{obstacle_id: string; obstacle_type: string; visible: boolean;
    mesh?: {vertices_3d: [number,number,number][]; triangles: [number,number,number][]; faces: Array<{vertex_indices: number[]}>}} >;
  modules: Array<{module_instance_id: string; pv_field_id: string; status: "resolved" | "unresolved";
    corners_3d: [number,number,number][]; unresolved_reason?: string}>;
  bounds_3d: {min_xyz: [number,number,number]; max_xyz: [number,number,number]} | null;
}

export type ShadingAccuracySettings = import("./generated/schemas/shading-accuracy-settings").ShadingAccuracySettings;
export type ShadingAccuracyPatch = { overrides: { level?: "standard" | "high" | null } } | { reset_to_recommended_defaults: true };
export interface ResolvedShadingAccuracy {
  schema_version: "0.1";
  defaults_id: "shading_accuracy.v1";
  level: "standard" | "high";
  source: "recommended_defaults" | "project_override";
  sky_dome_resolution: { azimuth_sectors: number; elevation_bands: number; horizon_azimuth_sectors: number; horizon_elevation_bands: number; horizon_band_elevation_deg: number };
  ground_dome_resolution: { azimuth_sectors: number; depression_bands: number };
  ground_source: "preset_mapping";
}

export interface ProjectBundle {
  pinned_components?: { modules: Record<string, { model: string; technology?: string; quality?: { lid_loss_fraction?: number | null } } | undefined>; inverters?: Record<string, unknown> };
  /** UX1 context-only imagery; never part of the scene, its hash or the RES1 fingerprint. */
  imagery?: import("./imagery/config").MapLayerConfiguration | null;
  /** UNC1: the engineer's annual-Pxx uncertainty ledger (no numerical defaults); absent until entered. */
  uncertainty_assumptions?: UncertaintyLedger;
  shading_accuracy?: ShadingAccuracySettings;
  optics_thermal_settings?: OpticsThermalSettings;
  loss_settings?: LossSettings;
  schema_name: string;
  schema_version: string;
  project: {
    project_id: string;
    name: string;
    distance_warning_m?: number;
    status: string;
    site: {
      address?: ProjectSiteAddress | null; installation?: ProjectInstallation | null;
      name?: string;
      latitude_deg: number;
      longitude_deg: number;
      elevation_m?: number | null;
      timezone: string;
      north_reference: string;
    };
    project_revision: {
      project_revision_id: string;
      revision_number: number;
      scene_revision_id: string;
      electrical_revision_id: string;
    };
  };
  scene: {
    buildings?: Array<{ building_id: string; name: string }>;
    revision_id: string;
    surfaces: Array<{
      reference_anchor?: ReferenceAnchor;
      locked?: boolean;
      surface_id: string;
      group_id?: string | null;
      usable_for_pv?: boolean;
      name: string;
      surface_type: string;
      base_elevation_m: number;
      slope_deg?: number; azimuth_deg?: number;
      elevation_reference?: import("./geometry").EngineElevationReference | null;
      boundary_2d?: { vertices: [number, number][]; holes: [number, number][][] };
    }>;
    obstacles: Array<{
      reference_anchor?: ReferenceAnchor;
      locked?: boolean;
      obstacle_id: string; name: string; obstacle_type: string;
      base_elevation_m?: number; height_m?: number;
    }>;
    pv_fields: PvField[];
    module_instances: Array<{
      module_instance_id: string;
      pv_field_id: string;
      module_definition_revision_id?: string;
      table_id?: string;
      enabled: boolean;
    }>;
  };
  electrical_design: {
    electrical_revision_id: string;
    mppt_instances?: Array<{ mppt_instance_id: string; inverter_instance_id: string; index: number }>;
    inverter_instances: Array<{
      inverter_instance_id: string;
      inverter_definition_revision_id: string;
      name: string;
      enabled: boolean;
      mppt_instance_ids: string[];
      /** S14b: the PV fields this inverter is paired with (advisory). */
      paired_pv_field_ids?: string[];
    }>;
    /** S14b: absent means the app default, 1° between module normals and no overrides. */
    orientation_policy?: { normal_angle_tolerance_deg?: number | null; overrides?: Array<{ mppt_instance_id: string; reason: string }> };
    strings: Array<{
      string_id: string;
      module_instance_ids: string[];
      target_mppt_instance_id: string | null;
      enabled: boolean;
    }>;
  };
  site_workspace_bootstrap: {
    workspace_context: {
      mode: WorkspaceMode;
      map_layer_configuration_id: string | null;
      show_true_north: boolean;
      show_metric_grid: boolean;
    };
  };
  workspace_state: {
    panel_state: {
      site_workspace_mode: WorkspaceMode;
    };
  };
  pinned_electrical_shading_assets?: {
    module_topologies: Record<string, Record<string, unknown>>;
    electrical_parameterization_evidence: Record<string, Record<string, unknown>>;
    sources: Record<string, Record<string, unknown>>;
  };
  electrical_shading_selections?: Record<string, ElectricalShadingSelection>;
  weather_selection: WeatherSelection | null;
  simulation_runs: SimulationRunRecord[];
  updated_at: string;
}


export interface TopologyView {
  electrical_revision_id: string;
  inverters: Array<{
    inverter_instance_id: string;
    name: string;
    inverter_definition_revision_id: string;
    enabled: boolean;
    mppts: Array<{
      mppt_instance_id: string;
      /** 1-based position on the inverter (schema minimum 1). */
      index: number;
      /** DC inputs of this MPPT when the inverter definition states them (electrical-topology-view schema). */
      input_count?: number | null;
      strings: Array<{
        string_id: string;
        name: string;
        module_count: number;
        enabled: boolean;
      }>;
    }>;
  }>;
  unassigned_strings: Array<{
    string_id: string;
    name: string;
    module_count: number;
    enabled: boolean;
  }>;
}


export interface TopologyConsistency {
  blocking_count: number;
  draft_count: number;
  findings: Array<{
    severity: string;
    code: string;
    entity_id: string;
    message: string;
  }>;
}


// Transport-local response ownership; never serialized or persisted in a bundle.
const mutationViews = new WeakSet<object>();
export const markMutationView = (view: object): void => { mutationViews.add(view); };
export const isMutationView = (value: unknown): value is ProjectView =>
  typeof value === "object" && value !== null && mutationViews.has(value);

export interface ProjectHistory {
  limit: number;
  past: { entry_id: string; label: string }[];
  future: { entry_id: string; label: string }[];
  reason: string | null;
  authority?: "demo";
}
export interface HistoryFence { expected_project_revision_id: string; expected_entry_id: string }

export interface ProjectView {
  /** Transient API evidence; never persisted in the project bundle. */
  history?: ProjectHistory;
  /** Transient fingerprint of the current design (RES1); compared with each run's. */
  design_fingerprint?: string;
  resolved_shading_accuracy?: ResolvedShadingAccuracy;
  loss_binding_findings?: Array<{ rule_id: string; message: string }>;
  resolved_optics_thermal_settings?: ResolvedOpticsThermalSettings;
  resolved_loss_settings?: ResolvedLossSettings;
  bundle: ProjectBundle;
  /**
   * Table-level layout of the fields filled by table (proposal 0003, Track E2).
   * The demo engine sends it today; the engine will once the proposal lands.
   */
  table_layout?: TableLayoutView;
  /** Live checks per string (proposal 0004, Track E5): shown as icons, never computed in the browser. */
  topology_checks?: TopologyChecks;
  scene_view: SceneView;
  topology_view: TopologyView;
  topology_consistency: TopologyConsistency;
  identity: {
    scene_hash: string;
    electrical_hash: string;
  };
  catalog: Catalog;
}


export interface CreateProjectInput {
  name: string;
  latitude_deg: number;
  longitude_deg: number;
  elevation_m?: number | null;
  timezone: string;
  workspace_mode: WorkspaceMode;
}




export interface WeatherImportWarning { code: string; message: string; distance_km?: number; difference_m?: number }
export interface WeatherImportPreview {
  format: string; filename: string; sha256: string;
  location: {latitude_deg?: number | null; longitude_deg?: number | null; elevation_m?: number | null} | null;
  site: {latitude_deg: number; longitude_deg: number; elevation_m: number | null; timezone: string};
  distance_km: number | null;
  time_zone: {source_timezone: string | null; source_utc_offset_hours: number | null; canonical_timezone: string; site_timezone: string; site_standard_utc_offset_hours: number};
  period: {start: string; end: string}; step_minutes: number; row_count: number; variables: string[]; typical_year: boolean;
  monthly_ghi_kwh_m2: (number | null)[]; annual_ghi_kwh_m2: number | null;
  qc: {status: string; findings: {rule_id: string; severity: string; message: string}[]};
  warnings: WeatherImportWarning[]; requires_accept_distant_location: boolean;
}
export interface WeatherImportResult {selection: WeatherSelection; manifest: Record<string, unknown>; preview: WeatherImportPreview; duplicate: boolean}

export interface WeatherSelection {
  weather_dataset_id: string;
  revision_id: string;
  source_id: string | null;
  name?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  timezone?: string | null;
  data_quality_status?: string | null;
  manifest?: Record<string, unknown> | null;
}


export interface WeatherSource {
  provider_id: string;
  source_id: string;
  label: string;
  acquisition_type: string;
  rawibumi_resource_projection_applied: boolean;
}


export interface InverterExecutionResult {
  inverter_instance_id: string;
  name: string;
  inverter_revision_id: string;
  simulated_dc_nameplate_w: number;
  nominal_ac_power_w: number;
  total_energy_wh: number;
  annual_energy_wh: number | null;
  specific_yield_wh_per_wp: number;
  performance_ratio: number;
  monthly_energy: Array<{ month: string; energy_wh: number }>;
  clipping_energy_wh: number;
  voltage_threshold_energy_wh: number;
  startup_threshold_energy_wh: number;
  conversion_energy_wh: number;
  self_consumption_energy_wh: number;
  loss_summary: SummaryResult["loss_summary"];
}

export interface ExecutionBreakdown {
  schema_version: "0.1";
  simulated_dc_nameplate_w: number;
  plant_poa_basis: "simulated_dc_nameplate_weighted";
  inverters: InverterExecutionResult[];
  groups: Array<{
    execution_group_id: string;
    inverter_instance_id: string;
    module_revision_id: string;
    simulated_dc_nameplate_w: number;
    poa_unshaded_wh_m2: number;
    poa_wh_m2: number;
    raw_dc_energy_wh: number;
    post_array_loss_dc_energy_wh: number;
  }>;
  group_timeseries_reference: Record<string, unknown>;
  inverter_timeseries_reference: Record<string, unknown>;
}

export interface SummaryResult {
  resolved_loss_settings?: ResolvedLossSettings;
  execution_breakdown?: ExecutionBreakdown;
  simulation_run_id: string;
  period_start_time: string;
  period_end_time: string;
  period_duration_hours: number;
  total_energy_wh: number;
  annual_energy_wh: number | null;
  specific_yield_wh_per_wp: number;
  performance_ratio: number;
  capacity_factor: number;
  monthly_energy: Array<{ month: string; energy_wh: number }>;
  loss_summary: Array<{
    loss_type: string;
    stage: string;
    reference_energy_wh: number;
    lost_energy_wh: number;
    loss_fraction: number;
    method: string;
    notes?: string | null;
  }>;
  peak_dc_power_w: number;
  peak_ac_power_w: number;
  clipping_energy_wh: number;
  shading_energy_loss_wh: number | null;
  /** The engine's counterfactual behind the shading loss (artifacts.py); not in the generated schema yet. */
  shading_energy_loss_basis?: Record<string, unknown> | null;
}


export interface SimulationRunRecord {
  mixed_orientation?: import("./generated/schemas/simulation-run").OpenSIMPVSimulationRunV01["mixed_orientation"];
  /** S15: the non-blocking readiness findings at launch; absent on runs saved before S15. */
  readiness_warnings?: Array<{ rule_id: string; severity: string; entity_id: string | null; message: string; category?: string }>;
  resolved_shading_accuracy?: ResolvedShadingAccuracy;
  model_manifest?: Record<string, unknown>;
  circuit_loss_resolution?: CircuitLossResolution;
  resolved_optics_thermal_settings?: ResolvedOpticsThermalSettings;
  resolved_loss_settings?: ResolvedLossSettings;
  detailed_electrical_shading?: DetailedElectricalShading | null;
  simulation_run_id: string;
  status: string;
  project_revision_id: string;
  scene_revision_id: string;
  electrical_revision_id: string;
  weather_dataset_revision_id: string;
  input_hash?: string | null;
  /** The design the run simulated (RES1); absent on runs saved before design tracking. */
  design_fingerprint?: string | null;
  /** RB-4D: modules shaded one another (rows included). Absent on runs saved before it was always on. */
  module_self_shading?: boolean;
  /** DATA1: imported without its result package; only the saved summary remains. */
  package_omitted?: boolean;
  summary_result?: SummaryResult | null;
  validation_findings?: Array<{
    rule_id: string;
    severity: string;
    category: string;
    message: string;
  }>;
  assumptions?: Array<{
    assumption_id?: string;
    severity?: string;
    statement?: string;
  }>;
  weather_source?: {
    source_id?: string | null;
    source_product_name?: string | null;
    start_time?: string | null;
    end_time?: string | null;
  };
}






export interface ElectricalRegionMapRegion {
  region_id: string;
  source_topology_region_id: string;
  source_electrical_substring_id: string;
  region_type: "cell" | "half_cell" | "grouped_cells" | "submodule";
  equivalent_element_count: number;
  polygon_uv: Array<[number, number]>;
  vertices_3d: Array<[number, number, number]>;
  area_m2: number;
  metadata: Record<string, unknown>;
}


export interface ElectricalRegionMap {
  schema_name: "ElectricalRegionMap";
  schema_version: string;
  contract_version: string;
  authority: "derived_physics_only";
  editable: false;
  electrical_region_map_id: string;
  source_scene_revision_id: string;
  source_module_instance_id: string;
  source_module_definition_revision_id: string;
  source_module_topology_revision_id: string;
  source_receiver_id: string;
  source_compiled_geometry_hash: string;
  coordinate_convention: "module_front_uv_normalized_width_height";
  placement_orientation: "portrait" | "landscape";
  mapper_manifest: {
    mapper_id: string;
    mapper_version: string;
    landscape_rotation_convention: "clockwise_90_viewed_from_module_front";
  };
  source_receiver_area_m2: number;
  mapped_region_area_m2: number;
  mapped_region_area_fraction: number;
  mapping_payload_sha256: string;
  regions: ElectricalRegionMapRegion[];
  findings: Array<Record<string, unknown>>;
}


export interface ExecutionReadinessFinding {
  rule_id: string;
  severity: string;
  category: string;
  entity_id?: string | null;
  message: string;
  context?: Record<string, unknown>;
}


export interface BrowserSimulationRequest {
  electrical_shading_configuration: {
    requested_fidelity: "level_2_bypass_substring";
    fallback_policy: "fail_closed" | "explicit_lower_fidelity";
  };
}

export interface ExecutionReadiness {
  schema_name: "Phase5ExecutionReadiness";
  schema_version: string;
  readiness_version: string;
  ready: boolean;
  execution_class?: string | null;
  legacy_homogeneous_backend_compatible?: boolean | null;
  findings: ExecutionReadinessFinding[];
}


export interface ModuleLevelElectricalApproximationState {
  schema_name: "ModuleLevelElectricalApproximationState";
  schema_version: "0.1";
  contract_version: string;
  state_id: string;
  source_scene_revision_id: string;
  source_electrical_revision_id: string;
  source_module_instance_id: string;
  source_module_definition_revision_id: string;
  source_shading_result_id: string;
  source_shading_physical_result_hash: string;
  source_local_irradiance_state_id?: string | null;
  source_local_irradiance_state_hash?: string | null;
  source_electrical_region_map_id?: string | null;
  source_electrical_region_map_hash?: string | null;
  source_module_topology_revision_id?: string | null;
  interval_start: string;
  evaluation_time: string;
  aggregation_method:
    | "module_receiver_channel_visibility_uniform_equivalent"
    | "area_weighted_complete_region_collapse_uniform_equivalent";
  irradiance_mapping_order: "unshaded_poa_by_channel_then_geometry_visibility_then_optical_treatment";
  thermal_state_scope: "single_module_temperature";
  module_temperature_c: number;
  unshaded_poa: { beam_w_m2: number; sky_diffuse_w_m2: number; ground_reflected_w_m2: number };
  post_geometry_poa: { beam_w_m2: number; sky_diffuse_w_m2: number; ground_reflected_w_m2: number };
  optical_modifier: { beam: number; sky_diffuse: number; ground_reflected: number };
  post_optical_poa: { beam_w_m2: number; sky_diffuse_w_m2: number; ground_reflected_w_m2: number };
  equivalent_incident_poa_global_w_m2: number;
  equivalent_effective_irradiance_w_m2: number;
  mapped_region_area_fraction?: number | null;
  module_mpp: {
    isc_a: number;
    voc_v: number;
    imp_a: number;
    vmp_v: number;
    pmp_w: number;
    active: boolean;
  };
  model_manifest: Record<string, unknown>;
  internal_nonuniformity_scope: "collapsed_uniform_equivalent";
  bypass_scope: "not_modeled";
  quality_flags: string[];
  state_payload_sha256: string;
}


export interface Level1ModuleSnapshotRequest {
  module_instance_id: string;
  sun_vector_xyz: [number, number, number];
  unshaded_poa: { beam_w_m2: number; sky_diffuse_w_m2: number; ground_reflected_w_m2: number };
  optical_modifier: { beam: number; sky_diffuse: number; ground_reflected: number };
  optical_model_manifest: Record<string, unknown> & { model_id: string; model_version: string };
  module_temperature_c: number;
  interval_start: string;
  evaluation_time: string;
  self_shading_enabled: boolean;
  sky_dome_resolution: Record<string, unknown>;
  ground_dome_resolution: Record<string, unknown>;
  geometric_fidelity_level?: "preview" | "fast" | "engineering" | "detailed" | "research";
}


export interface Level1ModuleSnapshotResult {
  source_shading_result: Record<string, unknown>;
  module_equivalent_irradiance_state: Record<string, unknown>;
  module_state: ModuleLevelElectricalApproximationState;
  electrical_shading_result: Record<string, unknown>;
}
export interface AttributionCoverage {
  availability: "available" | "unavailable" | "not_applicable";
  completeness: "complete" | "partial" | "unavailable" | "not_applicable";
  observed_signed_energy_wh: number | null;
  complete_signed_energy_wh: number | null;
  applicable_duration_seconds: number;
  available_duration_seconds: number;
  unavailable_duration_seconds: number;
  not_applicable_duration_seconds: number;
  availability_fraction: number | null;
  unavailable_reason_codes: string[];
}
export interface AttributionPeriod {
  period_kind: "run_total" | "daily" | "monthly";
  period_key: string;
  observed_start: string;
  observed_end: string;
  duration_seconds: number;
  channels: Record<string, AttributionCoverage>;
  telescope: { status: string; blocking_bases: string[]; blocking_channels: string[] };
}
export interface DetailedElectricalShading {
  package_manifest_sha256?: string;
  execution_identity: {
    requested_fidelity: string | null;
    resolved_fidelity: string | null;
    runtime_support_result: string;
    limitations: string[];
    failure_reasons: string[];
    fallback_reason: string | null;
    fallback_applied: boolean;
    fallback_policy: "fail_closed" | "explicit_lower_fidelity";
  };
  selected_mppt_result: CompactArtifactReference;
  dc_attribution_result: CompactArtifactReference;
  attribution_energy_result: CompactArtifactReference;
  attribution_energy_summary: {
    energy_summary_model_id: string;
    energy_summary_model_version: string;
    source_identity: { attribution_model_id: string; attribution_model_version: string };
    periods: AttributionPeriod[];
  } | null;
  diagnostic_artifacts: { status: string; artifacts: string[] };
}
export interface CompactArtifactReference {
  status: string;
  artifact: string | null;
  sha256: string | null;
  model_id: string | null;
  unavailable_reason_codes: string[];
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly detail: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ProjectSiteAddress {
  text: string; source: "lookup" | "user"; lat: number; lon: number;
  attribution: string | null; updatedAt: string;
}
export interface ProjectInstallation {
  installationType: "on_grid" | "on_grid_zero_export" | "off_grid" | "hybrid" | null;
  bessEnergyKwh: number | null; bessPowerKw: number | null;
}

export interface ReportSiteChanges {
  address?: ProjectSiteAddress | null; installation?: ProjectInstallation | null; copy_if_missing?: boolean;
}
export interface SiteChanges {
  name?: string; latitude_deg?: number; longitude_deg?: number; elevation_m?: number; timezone?: string;
}
export interface SimulationDefaults {
  shading_accuracy?: ResolvedShadingAccuracy;
  optics_thermal_settings?: ResolvedOpticsThermalSettings;
  loss_settings?: ResolvedLossSettings;
  demo?: boolean;
  albedo: number;
  thermal: { u_c_w_m2k: number; u_v_w_m2k_per_ms: number };
  losses: { module_mismatch_loss_fraction: number; string_mismatch_loss_fraction: number; dc_array_resistance_ohm: number };
  simulation_timestep_seconds: number;
  module_quality: { source: "pinned_module_definition"; fallback_loss_fraction: number };
  not_modelled: string[];
}

// Preview and confirmation share one command id, including over plain HTTP.
export function newCommandId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Fractions dimensionless, reference power W. Omitted overrides inherit their versioned defaults. */
export interface LossValues {
  soiling: { monthly_fractions: number[] };
  lid_fraction: number | null;
  module_mismatch_fraction: number | null;
  string_mismatch_fraction: number | null;
  dc_wiring_stc_fraction: number;
  ac_wiring_nominal_fraction: number;
  annual_degradation_fraction: number;
  operating_year: number;
  transformer: { enabled: boolean; reference_power_w: number | null; iron_fraction: number; copper_fraction: number | null };
  unavailability_fraction: number;
}
export type AcWiringSegment =
  | { mode: "percent"; loss_fraction: number; reference: "rated_ac" }
  | { mode: "percent"; loss_fraction: number; reference: "custom"; reference_power_w: number }
  | { mode: "cable"; length_one_way_m: number; cross_section_per_phase_mm2: number; material: "copper" | "aluminium"; line_voltage_v: number; conductor_temperature_c: number; phase_system: "balanced_three_phase"; power_factor: 1 };
export interface CircuitOverrideRow { dc_wiring_stc_fraction?: number; module_quality_fraction?: number; ac_wiring?: AcWiringSegment }
export interface CircuitOverrides {
  binding: { electrical_revision_id: string; topology_sha256?: string };
  inverters?: Record<string, CircuitOverrideRow>; mppts?: Record<string, Omit<CircuitOverrideRow, "ac_wiring">>;
}
export type CircuitOverridePatch = {
  binding: { electrical_revision_id: string; topology_sha256?: string | null };
  inverters?: Record<string, { dc_wiring_stc_fraction?: number | null; module_quality_fraction?: number | null; ac_wiring?: AcWiringSegment | null } | null>;
  mppts?: Record<string, { dc_wiring_stc_fraction?: number | null; module_quality_fraction?: number | null } | null>;
};
export interface CircuitLossResolution {
  schema_name: "CircuitLossResolution"; schema_version: "0.1"; active: boolean;
  requested_overrides: Record<string, unknown>; binding: Record<string, unknown> | null;
  circuits: Record<string, { inverter_instance_id: string; mppt_instance_id: string; mppt_index: number; dc_wiring_stc_fraction: number; dc_wiring_source: string; module_quality_by_module: Record<string, number>; module_quality_sources: Record<string, string>; reference_voltage_v?: number | null; reference_current_a?: number | null; resistance_ohm?: number; module_quality_fraction?: number }>;
  inverters: Record<string, { name: string; nominal_ac_power_w: number; ac_wiring: AcWiringSegment & { active: boolean; source: string; reference_power_w: number; resistivity_20_ohm_mm2_m?: number; resistivity_ohm_mm2_m?: number; temperature_coefficient_per_c?: number; resistance_per_phase_ohm?: number; quadratic_coefficient_per_w: number } }>;
  plant_ac_wiring: (AcWiringSegment & { active: boolean; reference_power_w: number; resistivity_20_ohm_mm2_m?: number; resistivity_ohm_mm2_m?: number; temperature_coefficient_per_c?: number; resistance_per_phase_ohm?: number; quadratic_coefficient_per_w: number }) | null;
  ac_summary?: Record<string, number>;
}
export type LossOverrides = Partial<Omit<LossValues, "soiling" | "transformer" | "lid_fraction" | "module_mismatch_fraction" | "string_mismatch_fraction">> & {
  circuit_overrides?: CircuitOverrides; plant_ac_wiring?: AcWiringSegment;
  lid_fraction?: number; module_mismatch_fraction?: number; string_mismatch_fraction?: number;
  soiling?: { annual_fraction?: number; monthly_fractions?: number[] };
  transformer?: Partial<{ enabled: boolean; reference_power_w: number; iron_fraction: number; copper_fraction: number }>;
};
/** PATCH null removes an override; persisted LossSettings never stores null leaves. */
export type LossOverridePatch = { [K in keyof Omit<LossValues, "soiling" | "transformer">]?: LossValues[K] | null } & {
  circuit_overrides?: CircuitOverridePatch | null; plant_ac_wiring?: AcWiringSegment | null;
  soiling?: { annual_fraction?: number | null; monthly_fractions?: number[] | null } | null;
  transformer?: { [K in keyof LossValues["transformer"]]?: LossValues["transformer"][K] | null } | null;
};
export interface LossSettings {
  schema_name: "LossSettings"; schema_version: "0.1"; defaults_id: "recommended_defaults.v1" | "recommended_defaults.v2";
  overrides: LossOverrides;
}
export interface ResolvedLossSettings extends LossSettings {
  values: LossValues & { degradation_fraction: number };
  sources: Record<string, string>;
  settings_sha256: string;
  status: "recommended_defaults" | "edited";
  simulated_dc_nameplate_w?: number;
  inverter_reference_power_w?: number;
  transformer_reference_power_w?: number;
  inverters?: Record<string, { nominal_ac_power_w: number }>;
  circuits?: Record<string, { reference_voltage_v: number | null; reference_current_a: number | null; resistance_ohm: number; lid_fraction?: number; lid_source?: string; technology?: string; module_mismatch_fraction: number; string_mismatch_fraction: number }>;
  method?: string;
}
export type LossPatch = { overrides: LossOverridePatch; defaults_id?: LossSettings["defaults_id"] } | { reset_to_recommended_defaults: true };

export type TranspositionChoice = "isotropic" | "hay_davies" | "perez_1990" | "perez_driesse" | "perez_hourly";
export interface OpticsThermalValues {
  transposition: TranspositionChoice;
  iam: { selection: "module_auto" | "module_table" | "physical_glass" | "none"; fallback: "physical_glass" };
  thermal: { model: "steady_state"; mounting_preset: "semi_integrated" | "open_rack" | "insulated_back" | "dome" | "custom"; u_c_w_m2k: number; u_v_w_m2k_per_ms: number; irradiance_basis: "effective" | "incident_pre_iam" };
  albedo: { monthly_values: number[] };
}
type NullableLeaves<T> = { [K in keyof T]?: T[K] | null };
export interface OpticsThermalOverrides {
  transposition?: TranspositionChoice | null;
  iam?: NullableLeaves<OpticsThermalValues["iam"]> | null;
  thermal?: NullableLeaves<OpticsThermalValues["thermal"]> | null;
  albedo?: { monthly_values?: number[] | null; annual_value?: number | null } | null;
}
export interface OpticsThermalSettings { schema_version: "0.1"; defaults_id: "recommended_optics_thermal.v1"; overrides: OpticsThermalOverrides }
export type OpticsThermalPatch = { overrides: OpticsThermalOverrides } | { reset_to_recommended_defaults: true };
export interface ResolvedOpticsThermalSettings extends OpticsThermalSettings {
  values: OpticsThermalValues; sources: Record<string, string>; settings_sha256: string; status: "recommended_defaults" | "edited";
  fallback_parameters: { n: number; K: number; L: number; n_ar: null };
  modules?: Record<string, { module_revision_id: string; iam_source: "module_table" | "fallback_physical_glass" | "physical_glass" | "explicit_none"; alpha_absorption: number; iam_profile_sha256: string | null }>;
}

/** An uploaded overlay image (UX1). */
export interface ImageryAsset { asset_id: string; filename: string; mime: string; width_px: number; height_px: number; bytes: number; sha256: string; created_at: string }

/** UNC1: one uncertainty term of the annual-Pxx ledger (U1 analytical method). Every value comes from the engineer. */
export interface UncertaintyTerm {
  source_key: string;
  double_count_group: string;
  scope: "project_persistent" | "annual_weather" | "intraday_operating";
  sigma_value: number;
  sigma_unit: "kwh" | "fraction_of_annual_mean";
  provenance_type: "user_assumption" | "versioned_software_catalog" | "measured_or_derived";
  source_ref: string;
  justification: string;
}
export type UncertaintyCorrelation =
  | { mode: "independent_explicit"; independence_basis: string }
  | { mode: "matrix_explicit"; matrix: number[][]; matrix_basis: string };
export interface UncertaintyLedger { schema_version: "1.0"; terms: UncertaintyTerm[]; correlation: UncertaintyCorrelation }

/** UNC1: a run's annual P50–P95 under the project ledger, or why it is unavailable. P99 is not qualified. */
/** USE1: POST /inverters/{id}/suggest-layout, an engine-sized MPPT layout verified by the design validation. */
export interface MpptLayoutSuggestion {
  schema_name: "MpptLayoutSuggestion";
  schema_version: string;
  status: "suggestion_available" | "no_solution";
  inverter_instance_id?: string;
  pv_field_ids?: string[];
  layout?: number[][];
  /** Strings Apply replaces in the same commit (a restring); empty when the layout reuses what exists. */
  replace_string_ids?: string[];
  string_length?: number;
  string_count?: number;
  modules_used?: number;
  modules_left?: number;
  inputs_per_mppt?: number | null;
  inputs_per_mppt_source?: string | null;
  warnings?: { rule_id: string; entity_id?: string | null; message: string }[];
  basis?: string;
  rejected?: { string_length: number; rule_ids: string[] }[];
  reasons: { code: string; message: string }[];
}

/** USE1: POST /pv-fields/shading-free-pitch. */
export interface ShadingFreePitch {
  row_pitch_m: number;
  plan_depth_m: number;
  shadow_length_m: number;
  ground_coverage_ratio: number;
  basis: string;
}

/** USE1: what Remove or Change model did to an inverter's strings. */
export interface InverterLifecycleResult {
  inverter_instance_id: string;
  inverter_definition_revision_id?: string;
  kept_string_ids?: string[];
  unassigned_string_ids: string[];
}

export interface AnnualPxxView {
  schema_name: "AnnualPxxView";
  run_id: string;
  status: "available" | "unavailable";
  reasons: Array<{ code: string; message: string; path?: string }>;
  basis: { annual_mean_basis: "typical_year_as_mean" | "historical_year_as_mean"; weather_calendar_type: string | null; mean_source: string; mean_source_sha256: string | null };
  ledger_sha256: string | null;
  result: null | {
    annual_mean_kwh: number; annual_sigma_kwh: number; annual_sigma_fraction: number | null;
    gaussian_negative_support_probability: number; correlation_mode: string; correlation_basis: string;
    quantiles: Record<"P50" | "P75" | "P90" | "P95", { exceedance_probability: number; normal_z: number; energy_kwh: number }>;
    terms: Array<{ source_key: string; sigma_kwh: number; signed_covariance_allocation_kwh2: number }>;
    limitations: string[];
  };
  P99: { status: "unavailable"; reason: string; message: string };
  label: { calculation_evidence: "assumption_based"; publication_status: "model_based_estimate" };
}


export interface SystemsBuilding {
  building_id: string | null; name: string; surface_ids: string[]; pv_field_ids: string[]; module_count: number; stc_kwp: number;
}
export interface SystemsOverview {
  schema_name: "SystemsOverview"; schema_version: "0.1";
  buildings: SystemsBuilding[];
  suggested_buildings: Array<{ name: string; surface_ids: string[]; matches_confirmed: boolean }>;
  distances: Array<{ from_index: number; to_index: number; distance_m: number; over_threshold: boolean }>;
  threshold_m: number; tolerance_deg: number;
  orientation_groups: Array<{ label: string; module_definition_revision_ids: string[]; pv_field_ids: string[]; surface_ids: string[];
    building_ids: Array<string | null>; module_count: number; stc_kwp: number }>;
}

export interface InverterSizing {
  schema_name: "InverterSizing"; schema_version: string;
  pv_field_ids: string[]; module_count: number; area_kwp: number; ac_kw: number; dc_ac_ratio: number | null;
  string_length_min: number | null; string_length_max: number | null;
  reasons: Array<{ code: string; message: string }>;
  mppt_count: number;
  mppts: Array<{ index: number; inputs: number | null; inputs_source: string | null; max_strings_by_isc: number | null }>;
  distance_warnings: Array<{ from_index: number; to_index: number; distance_m: number; over_threshold: boolean; from_name: string; to_name: string }>;
}

export type ReferenceAnchor = { u: "start" | "center" | "end"; v: "start" | "center" | "end" };
