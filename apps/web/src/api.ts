import type { InverterSizing } from "./types";
import { ApiError, newCommandId, markMutationView } from "./types";
import i18n from "./i18n";
import { notifyTakenModules } from "./electrical/takenNotice";
export { ApiError, newCommandId } from "./types";
import type {
  ShadingAccuracyPatch, OpticsThermalPatch, LossPatch, Catalog, SiteChanges, SimulationDefaults, ComponentCompletionInput, ComponentLibraryPreview, ComponentLibraryEntry, ComponentLibraryCommit,
  BrowserSimulationRequest,
  CreateProjectInput,
  ElectricalRegionMap,
  Level1ModuleSnapshotRequest,
  Level1ModuleSnapshotResult,
  ElectricalShadingFidelity,
  ExecutionReadiness,
  ProjectSummary,
  ProjectView, HistoryFence,
  SceneCommandInput, SceneConflictOptions, SceneResult, PolygonObstacleInput,
  SimulationRunRecord,
  WeatherSource, WeatherImportPreview, WeatherImportResult,
  WorkspaceMode, AnnualPxxView, UncertaintyLedger, MpptLayoutSuggestion, ShadingFreePitch, InverterLifecycleResult, ProjectSystemSummary
} from "./types";
import type { ModuleCommandInput, ModuleCommandResult, ImageryAsset, ProjectBackup } from "./types";
import type { MapLayerConfiguration } from "./imagery/config";
import type { FillPreview, FillZoneRequest, LegacyFieldInput, TableEditCommand, PvFieldChanges, PvFieldOptions, PvFieldUpdatePreview, PvFieldDeletePreview } from "./engine/layout";
import type { TopologyCommand } from "./engine/topology";
import { NotWiredError } from "./pending";

/** A route the engine does not have yet: reject with the pending id (src/pending.ts). */
const pendingRoute = <T,>(id: string): Promise<T> => Promise.reject(new NotWiredError(id));

/** Preserve engine messages; FastAPI validation details must not become [object Object]. */
export function responseError(payload: unknown, fallback: string): string {
  const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string" && detail.trim()) return detail.replace(
    /These modules are already in (.+?)\. Remove them from (.+?) first, or use Move module\./g,
    (_match, locations: string, strings: string) => i18n.t("str1.assigned", { locations: locations.replaceAll(" on MPPT ", i18n.t("str1.onMppt")), strings })
  );
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") {
    if ("findings" in detail && Array.isArray(detail.findings)) return detail.message + i18n.t("electrical.consistencyCount", { count: detail.findings.length });
    const conflicts = "conflicts" in detail && Array.isArray(detail.conflicts) ? detail.conflicts.length : null;
    return detail.message + (conflicts !== null ? ` (${conflicts} conflicts)` : "");
  }
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item: unknown) => {
      if (!item || typeof item !== "object") return [];
      const { loc, msg } = item as { loc?: unknown; msg?: unknown };
      if (typeof msg !== "string") return [];
      const path = Array.isArray(loc) ? loc.filter((p) => typeof p === "string" || typeof p === "number").join(".") : "";
      return [path ? `${path}: ${msg}` : msg];
    });
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}

/** Entity ids remain engine data; only the short connective text is translated. */
export function repairRefusalSummary(detail: unknown): string {
  if (!detail || typeof detail !== "object" || !("findings" in detail) || !Array.isArray(detail.findings)) return "";
  const ids = detail.findings.flatMap((finding: unknown) => finding && typeof finding === "object" && "entity_id" in finding && typeof finding.entity_id === "string" ? [finding.entity_id] : []);
  if (!ids.length) return "";
  const more = ids.length > 3 ? i18n.t("electrical.consistencyMore", { count: ids.length - 3 }) : "";
  return i18n.t("electrical.consistencyEntities", { ids: ids.slice(0, 3).join(", "), more });
}

/** Match the S5 allocator: the first free S### across every electrical collection. */
export function nextElectricalStringId(view: ProjectView): string {
  const design = view.bundle.electrical_design as unknown as Record<string, unknown>;
  const used = new Set<string>();
  for (const [collection, key] of [["inverter_instances", "inverter_instance_id"], ["mppt_instances", "mppt_instance_id"], ["strings", "string_id"], ["connections", "connection_id"]]) {
    const items = design[collection];
    if (!Array.isArray(items)) throw new Error(`Current project view is missing electrical ${collection}; reload before drawing a string.`);
    for (const item of items) if (item && typeof item === "object" && item[key] != null) used.add(String(item[key]));
  }
  let counter = 1;
  while (used.has(`S${String(counter).padStart(3, "0")}`)) counter++;
  return `S${String(counter).padStart(3, "0")}`;
}


function electricalCommand(command_type: string, parameters: Record<string, unknown>) {
  return { schema_name: "ElectricalTopologyCommand", schema_version: "0.1", command_id: newCommandId(), command_type, parameters };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  await checkResponse(response);
  const value: T = await response.json();
  if (init?.method && init.method !== "GET" && !/\/(undo|redo)$/.test(path)
      && value && typeof value === "object" && "bundle" in value && "history" in value
      // Only server-owned history is pushed centrally; demo history is recorded by engineCommand.
      && (value as { history?: { authority?: string } | null }).history?.authority !== "demo") markMutationView(value);
  return value;
}

async function checkResponse(response: Response): Promise<void> {
  if (!response.ok) {
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      // Keep HTTP status text when a non-JSON proxy/server error is returned.
    }
    const detail = payload && typeof payload === "object" && "detail" in payload ? payload.detail : undefined;
    throw new ApiError((responseError(payload, response.statusText) || `Request failed: ${response.status}`) + repairRefusalSummary(detail), response.status, detail);
  }
}

export interface CSVExportSchema {
  project_id: string;
  run_id: string;
  format: "csv";
  resolution: "hourly";
  level: "project";
  row_count: number;
  timestamp_convention: "interval_start";
  timezone: string;
  interval_seconds: number;
  columns: Array<{ id: string; label: string; unit: string; required: boolean }>;
}

export interface CSVExportRequest {
  format: "csv";
  resolution: "hourly";
  level: "project";
  columns: string[];
  /** S15: hourly file formats (default CSV only) and the full deliverable (monthly table, package documents, run record). */
  formats?: Array<"csv" | "parquet">;
  deliverable?: boolean;
}

/** S15: a run's stored hourly series as site-local day × hour matrices, with its reconciled monthly table. */
export interface RunTimeSeriesView {
  schema_name: "RunTimeSeriesView";
  run_id: string;
  timezone: string;
  interval_seconds: number;
  period: { start: string; end: string; hours: number };
  days: string[];
  hourly: Partial<Record<"ac_kw" | "poa_w_m2" | "ghi_w_m2" | "cell_temperature_c" | "ambient_temperature_c",
    { label: string; unit: string; source_column: string; values: Array<Array<number | null>> }>>;
  quality: { repeated_local_hours_averaged: number; missing_hour_cells: number };
  dc_kwp: number | null;
  dc_kwp_basis: string;
  pr_basis: string;
  monthly: Array<{ month: string; energy_kwh: number | null; poa_unshaded_kwh_m2: number | null; ghi_kwh_m2: number | null;
    specific_yield_kwh_kwp: number | null; performance_ratio: number | null; losses_kwh: Record<string, number | null> }>;
  loss_channels: Array<{ loss_type: string; stage: string; monthly: boolean }>;
}

export interface NativePDFCapability {
  enabled: boolean;
  format: "pdf";
  text_based: true;
  locales: ["en", "id"];
}

const exportPath = (projectId: string, runId: string) =>
  `/api/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/exports`;

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body ?? {})
  });
}

// Kept separate from `api`: EngineAdapter is typeof api, and its demo contract
// cannot supply persisted run artifacts. Numerical export always uses HTTP.
export const exportAPI = {
  freeCSV: async (projectId: string, runId: string): Promise<Blob> => {
    const response = await fetch(`${exportPath(projectId, runId)}/free-csv`, { cache: "no-store" });
    await checkResponse(response);
    if (response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() !== "application/zip") {
      throw new Error("Export response is not an application/zip download");
    }
    return response.blob();
  },
  nativePDFCapability: async (): Promise<NativePDFCapability> => {
    const value = await request<NativePDFCapability>("/api/reporting/native-pdf/capability", { cache: "no-store" });
    if (!value || typeof value.enabled !== "boolean" || value.format !== "pdf" || value.text_based !== true
        || !Array.isArray(value.locales) || value.locales.length !== 2 || value.locales[0] !== "en" || value.locales[1] !== "id") {
      throw new Error("Native PDF capability is unavailable");
    }
    return value;
  },
  nativePDF: async (projectId: string, runId: string, locale: "en" | "id", planFigurePng: string | null = null): Promise<Blob> => {
    if (locale !== "en" && locale !== "id") throw new Error("Native PDF locale must be en or id");
    const response = await fetch(`${exportPath(projectId, runId)}/native-pdf`, { method: "POST", cache: "no-store", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ locale, plan_figure_png: planFigurePng }) });
    await checkResponse(response);
    if (response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() !== "application/pdf") {
      throw new Error("Export response is not an application/pdf download");
    }
    const blob = await response.blob();
    if (blob.size < 5 || blob.size > 8 * 1024 * 1024) throw new Error("Native PDF response has an invalid size");
    const signature = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
    if (![37, 80, 68, 70, 45].every((byte, index) => signature[index] === byte)) {
      throw new Error("Export response is not a PDF document");
    }
    return blob;
  },
  exportSchema: (projectId: string, runId: string) =>
    request<CSVExportSchema>(`${exportPath(projectId, runId)}/schema`),
  /** S15: the run's stored series; never derived from demo physics. */
  runSeries: (projectId: string, runId: string, signal?: AbortSignal) =>
    request<RunTimeSeriesView>(`/api/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/timeseries`, { signal }),
  exportCSV: async (projectId: string, runId: string, input: CSVExportRequest): Promise<Blob> => {
    const response = await fetch(exportPath(projectId, runId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input)
    });
    await checkResponse(response);
    if (response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() !== "application/zip") {
      throw new Error("Export response is not an application/zip download");
    }
    return response.blob();
  },
};

export const api = {
  reportSnapshot: (projectId: string, runId: string, signal?: AbortSignal) =>
    request<import("./report/snapshot").VerifiedReportSnapshot>(`/api/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/report-snapshot`, { cache: "no-store", signal }),

  sceneGeometry3d: (projectId: string, signal?: AbortSignal) => request<import("./types").ExactSceneGeometry>(
    `/api/projects/${encodeURIComponent(projectId)}/scene/geometry-3d`, {signal}),
  componentLibrary: (includeHidden = false) => request<ComponentLibraryEntry[]>(`/api/component-library?include_hidden=${includeHidden}`),
  previewComponent: (file: File) => request<ComponentLibraryPreview>(`/api/component-library/imports?filename=${encodeURIComponent(file.name)}&dry_run=true`, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  importComponent: (file: File) => request<ComponentLibraryCommit>(`/api/component-library/imports?filename=${encodeURIComponent(file.name)}&dry_run=false`, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  previewComponentCompletion: (revisionId: string, input: ComponentCompletionInput) => post<ComponentLibraryPreview>(`/api/component-library/${encodeURIComponent(revisionId)}/complete`, { ...input, dry_run: true }),
  completeComponent: (revisionId: string, input: ComponentCompletionInput) => post<ComponentLibraryCommit>(`/api/component-library/${encodeURIComponent(revisionId)}/complete`, { ...input, dry_run: false }),
  hideComponent: (revisionId: string) => post<ComponentLibraryEntry>(`/api/component-library/${encodeURIComponent(revisionId)}/hide`),
  unhideComponent: (revisionId: string) => post<ComponentLibraryEntry>(`/api/component-library/${encodeURIComponent(revisionId)}/unhide`),
  systemsOverview: (projectId: string) => request<import("./types").SystemsOverview>(`/api/projects/${encodeURIComponent(projectId)}/systems/overview`),
  updateProject: (projectId: string, changes: { name?: string; description?: string; distance_warning_m?: number }) =>
    request<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}`, { method: "PATCH", body: JSON.stringify(changes) }),
  updateSite: (projectId: string, changes: SiteChanges, options?: { clear_weather_selection?: boolean }) =>
    request<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/site`, { method: "PATCH", body: JSON.stringify({ ...changes, ...options }) }),
  updateSiteDetails: (projectId: string, changes: import("./types").ReportSiteChanges) =>
    request<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/site/details`, { method: "PATCH", body: JSON.stringify(changes) }),
  deleteProject: (projectId: string, confirmProjectId: string) =>
    request<{ deleted_project_id: string; removed: { bundle: boolean; runs: boolean; weather: boolean } }>(`/api/projects/${encodeURIComponent(projectId)}?confirm=${encodeURIComponent(confirmProjectId)}`, { method: "DELETE" }),
  updateLosses: (projectId: string, patch: LossPatch) => request<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/losses`, { method: "PATCH", body: JSON.stringify(patch) }),
  updateOpticsThermal: (projectId: string, patch: OpticsThermalPatch) => request<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/optics-thermal`, { method: "PATCH", body: JSON.stringify(patch) }),
  /** UX1: upload an overlay image (PNG/JPEG/WebP, at most 10 MB and 8,192 px per side). */
  uploadImageryAsset: (projectId: string, file: Blob, filename: string) => request<ImageryAsset>(`/api/projects/${encodeURIComponent(projectId)}/imagery/assets?filename=${encodeURIComponent(filename)}`, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  /** UX1: persist the project's imagery (one undo step, no scene revision), or clear it with null. */
  /** UNC1: save (or clear with null) the project's annual-Pxx uncertainty ledger; an undo step. */
  updateUncertaintyAssumptions: (projectId: string, ledger: UncertaintyLedger | null) =>
    request<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/uncertainty-assumptions`, { method: "PUT", body: JSON.stringify({ ledger }) }),
  /** UNC1: a run's annual P50–P95 under the project ledger, or the reasons it is unavailable. */
  annualPxx: (projectId: string, runId: string) =>
    request<AnnualPxxView>(`/api/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/annual-pxx`),
  updateImagery: (projectId: string, config: MapLayerConfiguration | null) => request<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/imagery`, { method: "PUT", body: JSON.stringify(config) }),
  imageryAssetUrl: (projectId: string, assetId: string) => `/api/projects/${encodeURIComponent(projectId)}/imagery/assets/${encodeURIComponent(assetId)}`,
  updateShadingAccuracy: (projectId: string, patch: ShadingAccuracyPatch) => request<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/shading-accuracy`, { method: "PATCH", body: JSON.stringify(patch) }),
  simulationDefaults: () => request<SimulationDefaults>("/api/simulation-defaults"),
  sceneCommand: <O extends SceneConflictOptions = SceneConflictOptions>(projectId: string, command: SceneCommandInput, options?: O) =>
    post<SceneResult<O>>(`/api/projects/${encodeURIComponent(projectId)}/scene/commands`, {
      command: { ...command, schema_name: "SceneEditorCommand", schema_version: "0.1", command_id: options?.dependent_fields === "apply" && command.command_id ? command.command_id : newCommandId() }, ...options
    }),
  addPolygonObstacle: <O extends SceneConflictOptions = SceneConflictOptions>(projectId: string, input: PolygonObstacleInput, options?: O) =>
    post<SceneResult<O>>(`/api/projects/${encodeURIComponent(projectId)}/obstacles/extrusion`, { ...input, ...options }),
  health: () => request<{ status: string; phase: string }>("/api/health"),
  catalog: () => request<Catalog>("/api/catalog"),
  previewWeatherFile: (projectId: string, file: File) => request<WeatherImportPreview>(`/api/projects/${encodeURIComponent(projectId)}/weather/import?filename=${encodeURIComponent(file.name)}&dry_run=true`, {method: "POST", body: file, headers: {"Content-Type": "application/octet-stream"}}),
  importWeatherFile: (projectId: string, file: File, acceptDistantLocation = false) => request<WeatherImportResult>(`/api/projects/${encodeURIComponent(projectId)}/weather/import?filename=${encodeURIComponent(file.name)}&dry_run=false&accept_distant_location=${acceptDistantLocation}`, {method: "POST", body: file, headers: {"Content-Type": "application/octet-stream"}}),
  weatherSources: () => request<WeatherSource[]>("/api/weather-sources"),
  projects: () => request<ProjectSummary[]>("/api/projects"),
  /** DATA1: the whole project as one .rawibumi file; results (run packages) are optional. */
  exportProject: async (projectId: string, includeResults: boolean): Promise<{ filename: string; blob: Blob }> => {
    const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/export?include_results=${includeResults}`);
    await checkResponse(response);
    const filename = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? `${projectId}.rawibumi`;
    return { filename, blob: await response.blob() };
  },
  /** DATA1: import keeps the project ID; a clash is 409 project_exists unless `replace`. */
  importProject: (file: Blob, filename: string, replace = false) => request<ProjectView>(`/api/projects/import?filename=${encodeURIComponent(filename)}&replace=${replace}`, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  projectBackups: (projectId: string) => request<ProjectBackup[]>(`/api/projects/${encodeURIComponent(projectId)}/backups`),
  restoreBackup: (projectId: string, backupId: string) => request<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/backups/${encodeURIComponent(backupId)}/restore`, { method: "POST" }),
  project: (projectId: string) =>
    request<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}`),
  createProject: (input: CreateProjectInput) =>
    post<ProjectView>("/api/projects", input),
  setWorkspaceMode: (projectId: string, mode: WorkspaceMode) =>
    request<ProjectView>(
      `/api/projects/${encodeURIComponent(projectId)}/workspace`,
      {
        method: "PATCH",
        body: JSON.stringify({ mode }),
        headers: { "Content-Type": "application/json" }
      }
    ),
  addSurface: (
    projectId: string,
    input: {
      name: string;
      origin_x_m: number;
      origin_y_m: number;
      width_m: number;
      height_m: number;
      base_elevation_m: number;
      surface_type: string;
      usable_for_pv: boolean;
    }
  ) => post<ProjectView>(
    `/api/projects/${encodeURIComponent(projectId)}/surfaces/rectangle`,
    input
  ),
  moveSceneEntity: <O extends SceneConflictOptions = SceneConflictOptions>(
    projectId: string,
    input: {
      entity_id: string;
      dx_m: number;
      dy_m: number;
    },
    options?: O
  ) => post<SceneResult<O>>(
    `/api/projects/${encodeURIComponent(projectId)}/scene/move`,
    { ...input, ...options }
  ),
  addObstacle: <O extends SceneConflictOptions = SceneConflictOptions>(
    projectId: string,
    input: {
      name: string;
      origin_x_m: number;
      origin_y_m: number;
      width_m: number;
      depth_m: number;
      base_elevation_m: number;
      height_m: number;
    },
    options?: O
  ) => post<SceneResult<O>>(
    `/api/projects/${encodeURIComponent(projectId)}/obstacles/box`,
    { ...input, ...options }
  ),
  createPvField: (
    projectId: string,
    input: {
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
    }
  ) => post<ProjectView>(
    `/api/projects/${encodeURIComponent(projectId)}/pv-fields`,
    input
  ),
  moduleCommands: <I extends ModuleCommandInput>(projectId: string, input: I) =>
    post<ModuleCommandResult<I>>(`/api/projects/${encodeURIComponent(projectId)}/pv-fields/modules/commands`, input),
  /** S4 previews are read-only; commits return the engine project view. */
  previewPvFieldUpdate: (projectId: string, fieldId: string, changes: PvFieldChanges) =>
    request<PvFieldUpdatePreview>(`/api/projects/${encodeURIComponent(projectId)}/pv-fields/${encodeURIComponent(fieldId)}`, {
      method: "PATCH", body: JSON.stringify({ ...changes, dry_run: true })
    }),
  updatePvField: (projectId: string, fieldId: string, changes: PvFieldChanges, options: PvFieldOptions = {}) =>
    request<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/pv-fields/${encodeURIComponent(fieldId)}`, {
      method: "PATCH", body: JSON.stringify({ ...changes, ...options })
    }),
  previewPvFieldDelete: (projectId: string, fieldId: string) =>
    request<PvFieldDeletePreview>(`/api/projects/${encodeURIComponent(projectId)}/pv-fields/${encodeURIComponent(fieldId)}?dry_run=true`, { method: "DELETE" }),
  deletePvField: (projectId: string, fieldId: string, options: Pick<PvFieldOptions, "discard_dependent_strings"> = {}) =>
    request<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/pv-fields/${encodeURIComponent(fieldId)}${options.discard_dependent_strings ? "?discard_dependent_strings=true" : ""}`, { method: "DELETE" }),
  /** Table-level fill preview (proposal 0003). */
  previewFill: (_projectId: string, _request: FillZoneRequest) => pendingRoute<FillPreview>("fillPreview"),
  /**
   * Table-level fill (proposal 0003). Until that route exists, a request that the
   * existing PV field route can express is sent there as `legacy` (see legacyFieldInput).
   */
  applyFill: (projectId: string, _request: FillZoneRequest, legacy: LegacyFieldInput | null) =>
    legacy
      ? post<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/pv-fields`, legacy)
      : pendingRoute<ProjectView>("fillApply"),
  /** Table edits; each pins the tables it touches (proposal 0003). */
  editTables: (_projectId: string, _pvFieldId: string, _command: TableEditCommand) => pendingRoute<ProjectView>("tableEdit"),
  /** Translate UI intents to one atomic S5 batch; legacy automation keeps its routes. */
  topologyCommand: async (projectId: string, command: TopologyCommand, view?: ProjectView): Promise<ProjectView> => {
    const id = encodeURIComponent(projectId);
    const batch = (commands: ReturnType<typeof electricalCommand>[]) => post<ProjectView>(`/api/projects/${id}/electrical/commands`, { commands });
    switch (command.command_type) {
      // S14a: split names its new string in the engine (the next free S###); the others edit strings in place.
      case "split_string": case "join_strings": case "reverse_string": case "move_module": case "swap_modules":
        return batch([electricalCommand(command.command_type, command.parameters)]);
      // S14b: replicate, notation Apply, the orientation policy and pairing are engine commands too.
      case "replicate_pattern": case "set_orientation_tolerance": case "set_orientation_override": case "set_inverter_pairing":
        return batch([electricalCommand(command.command_type, command.parameters)]);
      case "apply_mppt_layout": {
        const { pv_field_ids, ...rest } = command.parameters;
        return batch([electricalCommand("apply_mppt_layout", pv_field_ids?.length ? { ...rest, pv_field_ids } : rest)]);
      }
      case "create_string": {
        if (!view || view.bundle.project.project_id !== projectId) throw new Error("Drawing a string requires the current project view; reload and try again.");
        const string_id = nextElectricalStringId(view);
        const commands = [electricalCommand("create_string", { string_id, module_instance_ids: command.parameters.module_instance_ids, take_from_unassigned: true })];
        if (command.parameters.mppt_instance_id) commands.push(electricalCommand("assign_strings_to_mppt", { string_ids: [string_id], mppt_instance_id: command.parameters.mppt_instance_id }));
        return notifyTakenModules(await batch(commands));
      }
      case "append_to_string": {
        // The engine joins strings, so the modules become a string first and are then joined onto the target.
        if (!view || view.bundle.project.project_id !== projectId) throw new Error("Adding to a string requires the current project view; reload and try again.");
        const added = nextElectricalStringId(view);
        return notifyTakenModules(await batch([electricalCommand("create_string", { string_id: added, module_instance_ids: command.parameters.module_instance_ids, take_from_unassigned: true }),
          electricalCommand("join_strings", { first_string_id: command.parameters.string_id, second_string_id: added })]));
      }
      case "assign_strings_to_mppt": case "unassign_strings":
        return batch([electricalCommand(command.command_type, command.parameters)]);
      case "delete_strings":
        return batch(command.parameters.string_ids.map((string_id) => electricalCommand("delete_string", { string_id })));
      case "create_strings": {
        const p = command.parameters;
        if (!p.module_instance_ids && p.ordering === "serpentine") {
          // The same modules the row-major route takes: enabled, not yet strung, in the field when one is given.
          if (!view || view.bundle.project.project_id !== projectId) throw new Error("Serpentine strings require the current project view; reload and try again.");
          const strung = new Set(view.bundle.electrical_design.strings.flatMap((s) => s.module_instance_ids));
          const free = view.bundle.scene.module_instances
            .filter((m) => m.enabled === true && !strung.has(m.module_instance_id) && (p.pv_field_id == null || m.pv_field_id === p.pv_field_id))
            .map((m) => m.module_instance_id);
          if (!free.length) throw new Error("No enabled unstrung modules are available.");
          return batch([electricalCommand("create_strings", { module_instance_ids: free, string_length: p.string_length, ordering: "serpentine", remainder_policy: p.allow_shorter_remainder ? "allow_shorter" : "error" })]);
        }
        if (!p.module_instance_ids && p.ordering === "row_major") return post<ProjectView>(`/api/projects/${id}/strings`, {
          string_length: p.string_length, pv_field_id: p.pv_field_id ?? null, allow_shorter_remainder: p.allow_shorter_remainder
        });
        return batch([electricalCommand("create_strings", { module_instance_ids: p.module_instance_ids, string_length: p.string_length, ordering: p.ordering, remainder_policy: p.allow_shorter_remainder ? "allow_shorter" : "error" })]);
      }
      case "assign_strings":
        return post<ProjectView>(`/api/projects/${id}/assignments`, { inverter_instance_id: command.parameters.inverter_instance_id, string_ids: command.parameters.string_ids ?? null });
    }
  },
  /** Engine-session undo and redo of the last scene, layout or electrical command. */
  undo: (projectId: string, fence?: HistoryFence) => post<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/undo`, fence),
  redo: (projectId: string, fence?: HistoryFence) => post<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/redo`, fence),
  addInverter: (
    projectId: string,
    input: {
      inverter_definition_revision_id: string;
      name: string;
    }
  ) => post<ProjectView>(
    `/api/projects/${encodeURIComponent(projectId)}/inverters`,
    input
  ),
  /** USE3b: one project's PV, inverters and last successful run, for its expandable row on the projects page. */
  projectSummary: (projectId: string) => request<ProjectSystemSummary>(`/api/projects/${encodeURIComponent(projectId)}/summary`),
  /** USE1: remove an inverter; its strings stay, unassigned. One undo step. */
  removeInverter: (projectId: string, inverterId: string) =>
    request<ProjectView & { command_results: InverterLifecycleResult[] }>(
      `/api/projects/${encodeURIComponent(projectId)}/inverters/${encodeURIComponent(inverterId)}`, { method: "DELETE" }),
  /** USE1: change an inverter's model or revision in place; strings stay where the MPPT index exists. */
  changeInverter: (projectId: string, inverterId: string, revisionId: string) =>
    request<ProjectView & { command_results: InverterLifecycleResult[] }>(
      `/api/projects/${encodeURIComponent(projectId)}/inverters/${encodeURIComponent(inverterId)}`,
      { method: "PUT", body: JSON.stringify({ inverter_definition_revision_id: revisionId }) }),
  /** USE1: run commands without committing; returns the trial topology and the engine's live checks for it. */
  electricalDryRun: (projectId: string, commands: { command_type: string; parameters: Record<string, unknown> }[]) =>
    post<{ dry_run: true; topology_view: ProjectView["topology_view"]; topology_checks: NonNullable<ProjectView["topology_checks"]> }>(
      `/api/projects/${encodeURIComponent(projectId)}/electrical/commands`,
      { dry_run: true, commands: commands
        // The UI's delete_strings is one engine delete_string per string, as for a committed batch.
        .flatMap((c) => c.command_type === "delete_strings" ? (c.parameters.string_ids as string[]).map((string_id) => ({ command_type: "delete_string", parameters: { string_id } })) : [c])
        .map((c) => ({ schema_name: "ElectricalTopologyCommand", schema_version: "0.1", command_id: newCommandId(), ...c })) }),
  inverterSizing: (projectId: string, inverterId: string) => request<InverterSizing>(
    `/api/projects/${encodeURIComponent(projectId)}/inverters/${encodeURIComponent(inverterId)}/sizing`),
  /** USE1: a suggested restring in one commit: the replaced strings go, then the layout is applied. */
  applyLayoutReplacing: (projectId: string, inverterId: string, layout: number[][], pvFieldIds: string[], replaceStringIds: string[], sources?: (string[] | null)[] | null) =>
    post<ProjectView>(`/api/projects/${encodeURIComponent(projectId)}/electrical/commands`, { commands: [
      ...replaceStringIds.map((string_id) => ({ schema_name: "ElectricalTopologyCommand", schema_version: "0.1", command_id: newCommandId(), command_type: "delete_string", parameters: { string_id } })),
      { schema_name: "ElectricalTopologyCommand", schema_version: "0.1", command_id: newCommandId(), command_type: "apply_mppt_layout",
        parameters: { inverter_instance_id: inverterId, layout, pv_field_ids: pvFieldIds, ...(replaceStringIds.length ? {} : { release_modules: true }), ...(sources === undefined ? {} : { sources }) } }] }),
  /** USE1: an engine-sized MPPT layout for one inverter (read-only). */
  suggestLayout: (projectId: string, inverterId: string, pvFieldIds?: string[] | null) =>
    post<MpptLayoutSuggestion>(`/api/projects/${encodeURIComponent(projectId)}/inverters/${encodeURIComponent(inverterId)}/suggest-layout`,
      { pv_field_ids: pvFieldIds?.length ? pvFieldIds : null }),
  /** USE1: the row pitch that keeps rows unshaded at a design sun position (read-only). */
  shadingFreePitch: (projectId: string, input: { module_definition_revision_id: string; orientation: "portrait" | "landscape"; tilt_deg: number; design_sun_elevation_deg: number; sun_azimuth_offset_deg: number; rows_per_table?: number; module_gap_y_m?: number }) =>
    post<ShadingFreePitch>(`/api/projects/${encodeURIComponent(projectId)}/pv-fields/shading-free-pitch`, input),
  createStrings: (
    projectId: string,
    input: {
      string_length: number;
      pv_field_id?: string | null;
      allow_shorter_remainder: boolean;
    }
  ) => post<ProjectView>(
    `/api/projects/${encodeURIComponent(projectId)}/strings`,
    input
  ),
  assignStrings: (
    projectId: string,
    input: {
      inverter_instance_id: string;
      string_ids?: string[] | null;
    }
  ) => post<ProjectView>(
    `/api/projects/${encodeURIComponent(projectId)}/assignments`,
    input
  ),
  acquireWeather: (
    projectId: string,
    input: { source_id: string; start_date: string; end_date: string }
  ) => post<{
    selection: ProjectView["bundle"]["weather_selection"];
    manifest: Record<string, unknown>;
    qc_report: Record<string, unknown>;
  }>(
    `/api/projects/${encodeURIComponent(projectId)}/weather/acquire`,
    input
  ),
  electricalShadingCapability: (
    projectId: string,
    moduleRevisionId: string,
    topologyRevisionId?: string | null
  ) => {
    const params = new URLSearchParams({ module_revision_id: moduleRevisionId });
    if (topologyRevisionId) params.set("topology_revision_id", topologyRevisionId);
    return request<Record<string, unknown>>(
      `/api/projects/${encodeURIComponent(projectId)}/electrical-shading/capability?${params.toString()}`
    );
  },
  setElectricalShadingSelection: (
    projectId: string,
    input: {
      module_revision_id: string;
      requested_fidelity: ElectricalShadingFidelity;
      fallback_policy: "fail_closed" | "explicit_lower_fidelity";
      topology_revision_id?: string | null;
      region_parameterization_evidence_id?: string | null;
      cell_parameterization_evidence_id?: string | null;
    }
  ) => post<Record<string, unknown>>(
    `/api/projects/${encodeURIComponent(projectId)}/electrical-shading/selection`,
    input
  ),
  importElectricalShadingAsset: (
    projectId: string,
    input: { asset_kind: string; asset: Record<string, unknown>; sources: Array<Record<string, unknown>> }
  ) => post<Record<string, unknown>>(
    `/api/projects/${encodeURIComponent(projectId)}/electrical-shading/assets/import`,
    input
  ),
  electricalRegionMap: (projectId: string, moduleInstanceId: string) => {
    const params = new URLSearchParams({ module_instance_id: moduleInstanceId });
    return request<ElectricalRegionMap>(
      `/api/projects/${encodeURIComponent(projectId)}/electrical-shading/region-map?${params.toString()}`
    );
  },
  level1ModuleSnapshot: (projectId: string, input: Level1ModuleSnapshotRequest) =>
    post<Level1ModuleSnapshotResult>(
      `/api/projects/${encodeURIComponent(projectId)}/electrical-shading/level1-module-snapshot`,
      input
    ),
  executionReadiness: (projectId: string, input?: BrowserSimulationRequest) =>
    request<ExecutionReadiness>(
      `/api/projects/${encodeURIComponent(projectId)}/execution-readiness${input ? `?${new URLSearchParams(input.electrical_shading_configuration)}` : ""}`
    ),
  simulate: async (projectId: string, input?: BrowserSimulationRequest): Promise<SimulationRunRecord> => {
    const id = encodeURIComponent(projectId);
    type Pending = { job_id: string; status: "running" };
    let r = await post<SimulationRunRecord | Pending>(`/api/projects/${id}/simulate`, input);
    // BETA1: a run longer than the server's wait answers 202 with a job; poll it until the run record arrives.
    while ("job_id" in r && r.status === "running") {
      await new Promise((done) => setTimeout(done, 2000));
      r = await request<SimulationRunRecord | Pending>(`/api/projects/${id}/simulate/jobs/${encodeURIComponent(r.job_id)}`);
    }
    return r as SimulationRunRecord;
  },
  runResult: (projectId: string, runId: string) =>
    request<SimulationRunRecord>(
      `/api/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/result`
    ),
  runs: (projectId: string) =>
    request<SimulationRunRecord[]>(
      `/api/projects/${encodeURIComponent(projectId)}/runs`
    ),
  save: (projectId: string) =>
    post<{
      project_id: string;
      updated_at: string;
      scene_hash: string;
      electrical_hash: string;
      project_revision_id: string;
    }>(`/api/projects/${encodeURIComponent(projectId)}/save`)
};
