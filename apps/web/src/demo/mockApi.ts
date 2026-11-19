/**
 * DEMO MODE ONLY — in-browser stand-in for the RawiBumi engineering API.
 * Same method surface as ../api. All numbers are illustrative, labeled as demo
 * in the UI, and are NOT simulation results. Components are synthetic.
 */
import { notifyTakenModules } from "../electrical/takenNotice";
import { canonicalSerialize, type VerifiedReportSnapshot } from "../report/snapshot";
import { buildResultModel } from "../results/model";
import { demoSeries } from "./series";
import { demoAnnualPxx, DemoPxxError, validateDemoLedger } from "./annualPxx";
import type {
  InverterSizing, SystemsOverview, ShadingAccuracyPatch, ShadingAccuracySettings, ResolvedShadingAccuracy, OpticsThermalPatch, ResolvedOpticsThermalSettings, OpticsThermalSettings, Catalog, SiteChanges, SimulationDefaults, ComponentCompletionInput,
  CreateProjectInput,
  ExecutionReadiness,
  LocalFeature,
  ProjectSummary,
  ProjectView,
  SimulationRunRecord,
  WeatherSource,
  DependentFieldPreview, WorkspaceMode, SceneCommandInput, SceneConflictOptions, SceneResult, ScenePreview, ObstacleConflictDetail, PolygonObstacleInput
} from "../types";
import { DemoUnavailableError, type EngineAdapter } from "../engine/adapter";
import { moduleCountOf, slotOf, tableFootprint, tableModules, type FillZoneRequest, type LegacyFieldInput, type TableEditCommand, type TableRecord, type PvFieldChanges, type PvFieldOptions, type PvFieldUpdatePreview, type PvFieldDeletePreview } from "../engine/layout";
import { ApiError, modulePlacement } from "../types";
import { fillZone, polygonDistance, previewOf } from "./fillEngine";
import { applyDesignCommand, applyTopologyCommand, consistencyReport, DEMO_COLD_FACTOR, DEMO_INVERTER_ELECTRICAL, DEMO_MODULE_ELECTRICAL, liveChecks, TopologyError, type ModuleInfo, type TopologyContext } from "./topologyEngine";
import { normalAngleDeg, enginePlaneToUi, planeZ, bounds, pointInPolygon, scalePoly, validatePolygon, type Vec2 } from "../geometry";
import { anchoredRectangle, rotateClockwise, setEdgeLength, type Preserve } from "../canvas/plan/edit";
import { distToSegment, translatePoly } from "../geometry";
import type { ImageryAsset, ProjectBackup, ModuleCommandInput, ModuleCommandResult, ModuleDeletePreview, ModuleMovePreview, UncertaintyLedger, MpptLayoutSuggestion, ShadingFreePitch, ProjectSystemSummary } from "../types";
import type { MapLayerConfiguration } from "../imagery/config";
import { imageHeader } from "../imagery/header";
import i18n from "../i18n";
import { templateProblem } from "../imagery/provider";
import type { TopologyCommand } from "../engine/topology";


function demoShadingAccuracy(raw?: ShadingAccuracySettings): ResolvedShadingAccuracy {
  const level = raw?.overrides.level ?? "standard", [az, bands] = level === "high" ? [72, 18] : [48, 12];
  return { schema_version: "0.1", defaults_id: "shading_accuracy.v1", level,
    source: raw?.overrides.level ? "project_override" : "recommended_defaults",
    sky_dome_resolution: { azimuth_sectors: az, elevation_bands: bands, horizon_azimuth_sectors: az, horizon_elevation_bands: 1, horizon_band_elevation_deg: 10 },
    ground_dome_resolution: { azimuth_sectors: az, depression_bands: bands }, ground_source: "preset_mapping" };
}

function demoOpticsDefaults(): ResolvedOpticsThermalSettings {
  return { schema_version: "0.1", defaults_id: "recommended_optics_thermal.v1", overrides: {},
    status: "recommended_defaults", settings_sha256: "demo-illustrative-optics-defaults", sources: {},
    fallback_parameters: { n:1.526, K:4, L:.002, n_ar:null },
    values: { transposition:"perez_hourly", iam:{selection:"module_auto",fallback:"physical_glass"},
      thermal:{model:"steady_state",mounting_preset:"semi_integrated",u_c_w_m2k:20,u_v_w_m2k_per_ms:0,irradiance_basis:"effective"}, albedo:{monthly_values:Array(12).fill(.2)} } };
}

function demoOpticsPatch(current: ResolvedOpticsThermalSettings | undefined, patch: OpticsThermalPatch): ResolvedOpticsThermalSettings {
  if ("reset_to_recommended_defaults" in patch) return demoOpticsDefaults();
  const resolved=demoOpticsDefaults();
  const overrides=JSON.parse(JSON.stringify(current?.overrides??{})) as Record<string, unknown>;
  function merge(target:Record<string,unknown>, value:Record<string,unknown>) {
    for(const [key,v] of Object.entries(value)) {
      if(v===null) delete target[key];
      else if(v && typeof v==="object" && !Array.isArray(v)) {
        const node=(target[key]??{}) as Record<string,unknown>;
        const input=v as Record<string,unknown>;
        if(key==="albedo") { if(input.annual_value!=null)delete node.monthly_values; if(input.monthly_values!=null)delete node.annual_value; }
        if(key==="thermal") {
          if(input.mounting_preset && input.mounting_preset!=="custom"){delete node.u_c_w_m2k;delete node.u_v_w_m2k_per_ms;}
          else if(input.u_c_w_m2k!=null||input.u_v_w_m2k_per_ms!=null)node.mounting_preset="custom";
        }
        merge(node,input);if(Object.keys(node).length)target[key]=node;else delete target[key];
      } else target[key]=v;
    }
  }
  merge(overrides,patch.overrides as Record<string,unknown>);
  resolved.overrides=overrides as OpticsThermalSettings["overrides"];
  const v=resolved.values;
  if(overrides.transposition)v.transposition=overrides.transposition as typeof v.transposition;
  Object.assign(v.iam,overrides.iam??{});Object.assign(v.thermal,overrides.thermal??{});
  const thermal=overrides.thermal as Record<string,unknown>|undefined;
  if(thermal?.mounting_preset && thermal.mounting_preset!=="custom"){
    v.thermal.u_c_w_m2k=({semi_integrated:20,open_rack:29,insulated_back:15,dome:27} as Record<string,number>)[String(thermal.mounting_preset)];v.thermal.u_v_w_m2k_per_ms=0;
  }
  const albedo=overrides.albedo as {annual_value?:number;monthly_values?:number[]}|undefined;
  v.albedo.monthly_values=albedo?.annual_value!=null?Array(12).fill(albedo.annual_value):albedo?.monthly_values??v.albedo.monthly_values;
  if(!Number.isFinite(v.thermal.u_c_w_m2k)||v.thermal.u_c_w_m2k<=0||!Number.isFinite(v.thermal.u_v_w_m2k_per_ms)||v.thermal.u_v_w_m2k_per_ms<0||v.albedo.monthly_values.length!==12||v.albedo.monthly_values.some(n=>!Number.isFinite(n)||n<0||n>1))throw new ApiError("Invalid optics/thermal settings",422,"Invalid optics/thermal settings");
  function sources(node:Record<string,unknown>,path="") {for(const [k,n] of Object.entries(node)){const p=path?`${path}.${k}`:k;if(n&&typeof n==="object"&&!Array.isArray(n))sources(n as Record<string,unknown>,p);else resolved.sources[p]="user";}}
  sources(overrides);if(albedo?.annual_value!=null)resolved.sources["albedo.monthly_values"]="user";
  resolved.status=Object.keys(overrides).length?"edited":"recommended_defaults";
  resolved.settings_sha256="demo-illustrative-optics-"+JSON.stringify(overrides);
  return resolved;
}

type Rect = { x: number; y: number; w: number; h: number; vertices?: Vec2[] };


const catalog: Catalog = {
  modules: [
    { revision_id: "mod-demo-550", manufacturer: "Demo", model: "550 W mono (synthetic)", pmp_w: 550, width_m: 1.134, height_m: 2.278, synthetic_reference: true, simulation_ready: true },
    { revision_id: "mod-demo-610", manufacturer: "Demo", model: "610 W mono (synthetic)", pmp_w: 610, width_m: 1.134, height_m: 2.382, synthetic_reference: true, simulation_ready: false },
    // The plan's golden case (B5): 2 × 1 m modules on an 8 × 12 m plane give 30 portrait, 25 landscape.
    { revision_id: "mod-demo-golden", manufacturer: "Demo", model: "2 × 1 m golden-case module (synthetic)", pmp_w: 400, width_m: 1, height_m: 2, synthetic_reference: true, simulation_ready: false }
  ],
  inverters: [
    { revision_id: "inv-demo-30k", manufacturer: "Demo", model: "30 kW, 4 MPPT (synthetic)", nominal_ac_power_w: 30000, mppt_count: 4, synthetic_reference: true, simulation_ready: true },
    { revision_id: "inv-demo-100k", manufacturer: "Demo", model: "100 kW, 10 MPPT (synthetic)", nominal_ac_power_w: 100000, mppt_count: 10, synthetic_reference: true, simulation_ready: false }
  ],
  module_topologies: []
};


let seq = 100;
const nid = (p: string) => `${p}-${(seq++).toString(36)}`;
const rectPoly = (r: Rect): [number, number][] => r.vertices ?? [
  [r.x, r.y],
  [r.x + r.w, r.y],
  [r.x + r.w, r.y + r.h],
  [r.x, r.y + r.h]
];
const overlaps = (a: Rect, b: Rect) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;


/** The demo creates only generated fields and native extrusion obstacles. */
type DemoView = Omit<ProjectView, "bundle"> & {bundle: Omit<ProjectView["bundle"], "scene"> & {
  scene: Omit<ProjectView["bundle"]["scene"], "pv_fields" | "obstacles"> & {
    pv_fields: import("../types").GeneratedPvField[];
    obstacles: Array<ProjectView["bundle"]["scene"]["obstacles"][number] & {base_elevation_m: number; height_m: number}>;
  }
}};
interface State {
  view: DemoView;
  rects: Record<string, Rect>;
  /** Table-level fields (proposal 0003): their tables and the request that filled them. */
  tables: TableRecord[];
  requests: Record<string, FillZoneRequest>;
  /** Engine-session history: one snapshot per scene, layout or electrical command. */
  undo: Snapshot[];
  redo: Snapshot[];
}

type Snapshot = Pick<State, "view" | "rects" | "tables" | "requests">;


function monthly(totalKwh: number) {
  const shape = [0.083, 0.078, 0.086, 0.084, 0.087, 0.083, 0.088, 0.092, 0.089, 0.085, 0.074, 0.071];
  const s = shape.reduce((a, b) => a + b, 0);
  return ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"].map(
    (month, i) => ({ month, energy_wh: (totalKwh * 1000 * shape[i]) / s })
  );
}


const SCENE_ENVELOPE = ["revision_id", "revision_number", "supersedes_revision_id", "created_at", "created_by", "status", "change_summary"];
const ELECTRICAL_ENVELOPE = ["electrical_revision_id", "revision_number", "supersedes_electrical_revision_id", "supersedes_revision_id", "project_revision_id", "created_at", "created_by", "status", "change_summary"];
const DESIGN_OPTIONAL_KEYS = ["pinned_components", "pinned_electrical_shading_assets", "electrical_shading_selections", "loss_settings", "optics_thermal_settings", "shading_accuracy", "weather_selection"];
const omit = (o: object, keys: string[]) => Object.fromEntries(Object.entries(o).filter(([k]) => !keys.includes(k)));
const canonicalJson = (x: unknown): string => Array.isArray(x) ? `[${x.map(canonicalJson).join(",")}]`
  : x && typeof x === "object" ? `{${Object.keys(x).sort().filter((k) => (x as Record<string, unknown>)[k] !== undefined).map((k) => `${JSON.stringify(k)}:${canonicalJson((x as Record<string, unknown>)[k])}`).join(",")}}`
  : JSON.stringify(x);
/** Demo-only design fingerprint over the server's RES1 field set; FNV-1a, not the server's SHA-256. */
export function demoDesignFingerprint(bundle: ProjectView["bundle"]): string {
  const b = bundle as unknown as Record<string, unknown>;
  const state = {
    ...Object.fromEntries(DESIGN_OPTIONAL_KEYS.filter((k) => k in b).map((k) => [k, b[k]])),
    project: { ...omit(bundle.project, ["project_revision", "name", "description"]), site: omit(bundle.project.site, ["address", "installation"]) },
    scene: omit(bundle.scene, SCENE_ENVELOPE),
    electrical_design: omit(bundle.electrical_design, ELECTRICAL_ENVELOPE),
    site_workspace_bootstrap: omit(bundle.site_workspace_bootstrap, ["workspace_context"])
  };
  let h = 0x811c9dc5;
  for (const ch of canonicalJson(state)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 0x01000193) >>> 0; }
  return `demo-fnv1a:${h.toString(16).padStart(8, "0")}`;
}

function demoRun(view: ProjectView): SimulationRunRecord & { completed_at: string } {
  const modules = view.bundle.scene.module_instances.length;
  const kwp = (modules * 550) / 1000;
  const total = kwp * 1292; // kWh, illustrative specific yield
  const chain = [
    ["iam", "optical", 0.021],
    ["soiling", "optical", 0.02],
    ["temperature", "array", 0.071],
    ["module_quality", "array", 0.004],
    ["mismatch", "array", 0.01],
    ["dc_ohmic", "array", 0.011],
    ["inverter_efficiency", "inverter", 0.017],
    ["inverter_clipping", "inverter", 0.008],
    ["ac_ohmic", "system", 0.005]
  ] as const;
  let ref = total / chain.reduce((p, c) => p * (1 - c[2]), 1);
  const loss_summary = chain.map(([loss_type, stage, f]) => {
    const lost = ref * f;
    const item = { loss_type, stage, reference_energy_wh: ref * 1000, lost_energy_wh: lost * 1000, loss_fraction: f, method: "demo" };
    ref -= lost;
    return item;
  });
  const b = view.bundle;
  return {
    resolved_shading_accuracy: demoShadingAccuracy(view.bundle.shading_accuracy),
    simulation_run_id: nid("run"),
    status: "completed",
    completed_at: "2026-01-01T00:00:00+07:00",
    design_fingerprint: demoDesignFingerprint(b),
    module_self_shading: true,
    // The demo's readiness has no non-blocking findings (S15 records the engine's at launch).
    readiness_warnings: [],
    project_revision_id: b.project.project_revision.project_revision_id,
    scene_revision_id: b.scene.revision_id,
    electrical_revision_id: b.electrical_design.electrical_revision_id,
    weather_dataset_revision_id: b.weather_selection?.revision_id ?? "none",
    input_hash: "demo0000c0ffee",
    summary_result: {
      simulation_run_id: "demo",
      period_start_time: "2025-01-01T00:00:00+07:00",
      period_end_time: "2026-01-01T00:00:00+07:00",
      period_duration_hours: 8760,
      total_energy_wh: total * 1000,
      annual_energy_wh: total * 1000,
      specific_yield_wh_per_wp: total / kwp,
      performance_ratio: 0.792,
      capacity_factor: total / (kwp * 8760),
      monthly_energy: monthly(total),
      loss_summary,
      peak_dc_power_w: kwp * 820,
      peak_ac_power_w: 30000,
      clipping_energy_wh: loss_summary[7].lost_energy_wh,
      shading_energy_loss_wh: null
    },
    assumptions: [
      { assumption_id: "demo.synthetic_components", severity: "warning", statement: "Demo mode: synthetic module and inverter." },
      { assumption_id: "demo.no_physics", severity: "warning", statement: "Demo mode: results are illustrative, not simulated." }
    ],
    weather_source: { source_id: "demo-tmy", source_product_name: "Demo TMY (synthetic)" }
  };
}


function rebuildFeatures(st: State) {
  const b = st.view.bundle;
  for (const surface of b.scene.surfaces) surface.boundary_2d = {
    vertices: rectPoly(st.rects[surface.surface_id]), holes: surface.boundary_2d?.holes ?? []
  };
  const f: LocalFeature[] = [];
  for (const s of b.scene.surfaces) f.push({ id: s.surface_id, category: "surface", subtype: s.surface_type, name: s.name, polygon: rectPoly(st.rects[s.surface_id]) });
  for (const o of b.scene.obstacles) f.push({ id: o.obstacle_id, category: "obstacle", subtype: o.obstacle_type, name: o.name, polygon: rectPoly(st.rects[o.obstacle_id]) });
  // Table-level fields send tables, not one feature per module (E2: payload size).
  b.scene.module_instances = [
    ...b.scene.module_instances.filter((m) => st.rects[m.module_instance_id]),
    ...st.tables.flatMap((t) => tableModules(t).map((m) => ({ module_instance_id: m.id, pv_field_id: t.pv_field_id, enabled: true })))
  ];
  for (const m of b.scene.module_instances)
    if (st.rects[m.module_instance_id])
      f.push({ id: m.module_instance_id, category: "module", subtype: "module", name: m.module_instance_id, pv_field_id: m.pv_field_id, polygon: rectPoly(st.rects[m.module_instance_id]) });
  for (const fl of b.scene.pv_fields) {
    const own = st.tables.filter((t) => t.pv_field_id === fl.pv_field_id && t.status === "active");
    if (!own.length && !st.requests[fl.pv_field_id]) continue;
    fl.row_count = own.reduce((n, t) => n + t.rows, 0);
    fl.modules_per_row = own.reduce((n, t) => Math.max(n, t.columns), 0);
  }
  // Strings lose modules that no longer exist; empty strings go.
  const live = new Set(b.scene.module_instances.map((m) => m.module_instance_id));
  const e = b.electrical_design;
  e.strings = e.strings.map((x) => ({ ...x, module_instance_ids: x.module_instance_ids.filter((id) => live.has(id)) })).filter((x) => x.module_instance_ids.length);
  st.view.table_layout = { requests: structuredClone(st.requests), tables: structuredClone(st.tables) };
  st.view.scene_view.local_features = f;
  rebuildTopology(st);
  const rev = b.project.project_revision.revision_number + 1;
  b.project.project_revision.revision_number = rev;
  st.view.identity = { scene_hash: `demo-scene-${rev.toString(16).padStart(8, "0")}`, electrical_hash: `demo-elec-${rev.toString(16).padStart(8, "0")}` };
}


function rebuildTopology(st: State) {
  const e = st.view.bundle.electrical_design;
  const mpptOwner = new Map<string, number>();
  st.view.topology_view = {
    electrical_revision_id: e.electrical_revision_id,
    inverters: e.inverter_instances.map((inv) => ({
      inverter_instance_id: inv.inverter_instance_id,
      name: inv.name,
      inverter_definition_revision_id: inv.inverter_definition_revision_id,
      enabled: inv.enabled,
      mppts: inv.mppt_instance_ids.map((mid, index) => {
        mpptOwner.set(mid, index);
        return {
          mppt_instance_id: mid,
          index: index + 1,
          input_count: DEMO_INVERTER_ELECTRICAL[inv.inverter_definition_revision_id]?.inputs ?? null,
          strings: e.strings
            .filter((s) => s.target_mppt_instance_id === mid)
            .map((s) => ({ string_id: s.string_id, name: s.string_id, module_count: s.module_instance_ids.length, enabled: s.enabled }))
        };
      })
    })),
    unassigned_strings: e.strings
      .filter((s) => !s.target_mppt_instance_id)
      .map((s) => ({ string_id: s.string_id, name: s.string_id, module_count: s.module_instance_ids.length, enabled: s.enabled }))
  };
  const ctx = topologyContext(st);
  st.view.topology_consistency = consistencyReport(ctx);
  st.view.topology_checks = liveChecks(ctx);
}

/** What the demo topology engine needs to know about the scene: modules, their place, field and table slot. */
function topologyContext(st: State): TopologyContext {
  const b = st.view.bundle;
  const modules = new Map<string, ModuleInfo>();
  for (const m of b.scene.module_instances) {
    const r = st.rects[m.module_instance_id];
    if (r) modules.set(m.module_instance_id, { id: m.module_instance_id, fieldId: m.pv_field_id, centre: [r.x + r.w / 2, r.y + r.h / 2], enabled: m.enabled, slot: null });
  }
  for (const t of st.tables)
    for (const m of tableModules(t)) {
      const c = m.polygon.reduce((acc, p) => [acc[0] + p[0] / 4, acc[1] + p[1] / 4], [0, 0]) as [number, number];
      modules.set(m.id, { id: m.id, fieldId: t.pv_field_id, centre: c, enabled: true, slot: { tableId: t.table_id, row: m.row, column: m.column } });
    }
  return {
    inverters: b.electrical_design.inverter_instances,
    strings: b.electrical_design.strings,
    modules,
    tables: st.tables.filter((t) => t.status === "active"),
    fields: new Map(b.scene.pv_fields.map((f) => [f.pv_field_id, { module: f.module_definition_revision_id, tilt: f.tilt_deg, azimuth: f.azimuth_deg }])),
    orientation_policy: b.electrical_design.orientation_policy
  };
}

/** Runs one topology command as one session step; a refusal changes nothing. */
function runTopology(st: State, cmd: TopologyCommand): Promise<ProjectView> {
  let strings, design;
  const taken_from: Record<string, string[]> = {};
  if (cmd.command_type === "create_string" || cmd.command_type === "append_to_string") {
    const ids = new Set(cmd.parameters.module_instance_ids);
    for (const s of st.view.bundle.electrical_design.strings) {
      const taken = s.module_instance_ids.filter((id) => ids.has(id));
      if (taken.length) taken_from[s.string_id] = taken;
    }
  }
  try {
    const ctx = topologyContext(st);
    strings = applyTopologyCommand(ctx, cmd);
    design = applyDesignCommand(ctx, cmd);
  } catch (err) {
    return Promise.reject(err instanceof TopologyError ? new Error(err.message) : err);
  }
  commit(st);
  st.view.bundle.electrical_design.strings = strings;
  if (design) {
    st.view.bundle.electrical_design.inverter_instances = design.inverters;
    st.view.bundle.electrical_design.orientation_policy = design.orientation_policy;
  }
  rebuildTopology(st);
  const deleted_string_ids = Object.keys(taken_from).filter((id) => !strings.some((s) => s.string_id === id));
  if (!Object.keys(taken_from).length) return wait(st.view);
  return notifyTakenModules({ ...st.view, command_results: [{ result: { taken_from, deleted_string_ids } }] } as ProjectView).then(wait);
}


function fill(st: State, fieldId: string, surfaceId: string, input: { orientation: string; module_gap_x_m: number; row_pitch_m: number; perimeter_setback_m: number; obstacle_setback_m: number; tilt_deg: number }, limit?: number, maxPerRow?: number) {
  const s = st.rects[surfaceId];
  const mod = catalog.modules[0];
  const portrait = input.orientation !== "landscape";
  const w = portrait ? mod.width_m : mod.height_m;
  const d = (portrait ? mod.height_m : mod.width_m) * Math.cos((input.tilt_deg * Math.PI) / 180);
  const obstacles = st.view.bundle.scene.obstacles.map((o) => {
    const r = st.rects[o.obstacle_id];
    const k = input.obstacle_setback_m;
    return { x: r.x - k, y: r.y - k, w: r.w + 2 * k, h: r.h + 2 * k };
  });
  const field = st.view.bundle.scene.pv_fields.find((f) => f.pv_field_id === fieldId)!;
  const exclusions = st.view.bundle.scene.surfaces.filter((surface) => demoKeepoutSelected(st, field, surface.surface_id));
  const out: Rect[] = [];
  const x0 = s.x + input.perimeter_setback_m;
  const y0 = s.y + input.perimeter_setback_m;
  for (let y = y0; y + d <= s.y + s.h - input.perimeter_setback_m + 1e-9; y += input.row_pitch_m) {
    let inRow = 0;
    for (let x = x0; x + w <= s.x + s.w - input.perimeter_setback_m + 1e-9; x += w + input.module_gap_x_m) {
      if (maxPerRow && inRow >= maxPerRow) break;
      inRow++;
      const r = { x, y, w, h: d };
      if (!obstacles.some((o) => overlaps(o, r)) && !exclusions.some((surface) => polygonDistance(rectPoly(r), rectPoly(st.rects[surface.surface_id])) === 0) && !(st.view.bundle.scene.surfaces.find(s => s.surface_id === surfaceId)?.boundary_2d?.holes ?? []).some(hole => polygonDistance(rectPoly(r), hole) <= input.perimeter_setback_m)) out.push(r);
      if (limit && out.length >= limit) break;
    }
  }
  const cut = limit ? out.slice(0, limit) : out;
  for (const r of cut) {
    const id = nid("m");
    st.rects[id] = r;
    st.view.bundle.scene.module_instances.push({ module_instance_id: id, pv_field_id: fieldId, enabled: true });
  }
  return cut.length;
}


function initialState(input?: CreateProjectInput): State {
  const lat = input?.latitude_deg ?? -6.2;
  const lon = input?.longitude_deg ?? 106.82;
  const site = { name: input?.name ?? "Warehouse site (demo)", latitude_deg: lat, longitude_deg: lon, elevation_m: input?.elevation_m ?? 12, timezone: input?.timezone ?? "Asia/Jakarta", north_reference: "geodetic_true_north" as const };
  const mode = input?.workspace_mode ?? "blank_engineering_plane";
  const view: DemoView = {
    resolved_shading_accuracy: demoShadingAccuracy(),
    bundle: {
      shading_accuracy: {schema_version: "0.1", defaults_id: "shading_accuracy.v1", overrides: {}},
      schema_name: "ProjectBundle",
      schema_version: "demo",
      project: {
        project_id: "demo-project",
        name: input?.name ?? "Warehouse rooftop (demo)",
        status: "draft",
        site,
        project_revision: { project_revision_id: "pr-demo", revision_number: 1, scene_revision_id: "scene-demo", electrical_revision_id: "elec-demo" }
      },
      scene: { revision_id: "scene-demo", surfaces: [], obstacles: [], pv_fields: [], module_instances: [] },
      electrical_design: { electrical_revision_id: "elec-demo", inverter_instances: [], strings: [] },
      site_workspace_bootstrap: { workspace_context: { mode, map_layer_configuration_id: null, show_true_north: true, show_metric_grid: true } },
      workspace_state: { panel_state: { site_workspace_mode: mode } },
      weather_selection: null,
      simulation_runs: [],
      updated_at: new Date().toISOString()
    },
    history: { limit: 100, past: [], future: [], reason: null, authority: "demo" },
    scene_view: { local_features: [], geojson: { type: "FeatureCollection", features: [] }, site },
    topology_view: { electrical_revision_id: "elec-demo", inverters: [], unassigned_strings: [] },
    topology_consistency: { blocking_count: 0, draft_count: 0, findings: [] },
    identity: { scene_hash: "", electrical_hash: "" },
    catalog
  };
  const st: State = { view, rects: {}, tables: [], requests: {}, undo: [], redo: [] };
  if (input) {
    rebuildFeatures(st);
    return st;
  }
  // Seed a representative rooftop.
  st.rects["srf-roof-a"] = { x: 0, y: 0, w: 42, h: 18 };
  view.bundle.scene.surfaces.push({ surface_id: "srf-roof-a", name: "Roof A", surface_type: "flat_roof", base_elevation_m: 8 });
  st.rects["obs-ahu-1"] = { x: 30, y: 11, w: 3.2, h: 2.4 };
  view.bundle.scene.obstacles.push({ obstacle_id: "obs-ahu-1", name: "AHU-1", obstacle_type: "box", base_elevation_m: 8, height_m: 1.6 });
  view.bundle.scene.pv_fields.push({
    pv_field_id: "fld-a",
    name: "Roof A array",
    support_surface_id: "srf-roof-a",
    module_definition_revision_id: "mod-demo-550",
    row_count: 4,
    modules_per_row: 19,
    orientation: "portrait",
    azimuth_deg: 0,
    tilt_deg: 10,
    module_gap_x_m: 0.02, row_pitch_m: 3.1,
    setback_configuration: { perimeter_setback_m: 1.2, obstacle_setback_m: 0.6 },
    module_gap_y_m: 0.02, // Explicit demo-only metadata; the legacy fill did not use this value.
    mounting_height_m: 0.2 // Explicit demo-only metadata; the legacy fill did not use this value.
  });
  fill(st, "fld-a", "srf-roof-a", { orientation: "portrait", module_gap_x_m: 0.02, row_pitch_m: 3.1, perimeter_setback_m: 1.2, obstacle_setback_m: 0.6, tilt_deg: 10 }, 76, 19);
  const mppts = ["mppt-1", "mppt-2", "mppt-3", "mppt-4"];
  view.bundle.electrical_design.inverter_instances.push({ inverter_instance_id: "inv-01", inverter_definition_revision_id: "inv-demo-30k", name: "INV-01", enabled: true, mppt_instance_ids: mppts });
  const ids = view.bundle.scene.module_instances.map((m) => m.module_instance_id);
  const lens = [16, 16, 16, 14, 14];
  const targets = ["mppt-1", "mppt-2", "mppt-3", "mppt-4", "mppt-4"];
  let k = 0;
  lens.forEach((l, i) => {
    view.bundle.electrical_design.strings.push({ string_id: `S${i + 1}`, module_instance_ids: ids.slice(k, k + l), target_mppt_instance_id: targets[i], enabled: true });
    k += l;
  });
  view.bundle.weather_selection = {
    weather_dataset_id: "wx-demo",
    revision_id: "wx-demo-r1",
    source_id: "demo-tmy",
    name: "Demo TMY (synthetic)",
    start_time: "2025-01-01T00:00:00+07:00",
    end_time: "2025-12-31T23:00:00+07:00",
    timezone: "Asia/Jakarta",
    data_quality_status: "passed"
  };
  rebuildFeatures(st);
  view.bundle.simulation_runs.push(demoRun(view));
  return st;
}


const DEMO_REPORT_SITE_KEY = "rawibumi.demo.projectReportSite";
function restoreDemoReportSite(view: ProjectView) {
  try {
    const value = JSON.parse(window.localStorage.getItem(DEMO_REPORT_SITE_KEY) || "{}");
    if (value && typeof value === "object") {
      for (const key of ["address","installation"] as const) if (key in value) Object.assign(view.bundle.project.site,{[key]:value[key]});
    }
  } catch { /* The demo still opens when browser storage is unavailable. */ }
}
function persistDemoReportSite(view: ProjectView) {
  const {address,installation} = view.bundle.project.site;
  try { window.localStorage.setItem(DEMO_REPORT_SITE_KEY,JSON.stringify({address,installation})); } catch { /* Storage may be disabled. */ }
}
let state: State = initialState();
restoreDemoReportSite(state.view);
/** Demo overlay images for this page load (UX1); the engine keeps them per project on disk. */
const demoImagery = new Map<string, { record: ImageryAsset; url: string }>();

/** Records the state before a command, so the session can undo it (scene spec §23). */
function commit(st: State) {
  st.undo.push(structuredClone({ view: st.view, rects: st.rects, tables: st.tables, requests: st.requests }));
  if (st.undo.length > 100) st.undo.shift();
  st.redo = [];
}

function restore(st: State, snap: Snapshot) {
  const currentSite = st.view.bundle.project.site;
  st.view = snap.view;
  for (const key of ["address", "installation"] as const) {
    if (key in currentSite) Object.assign(st.view.bundle.project.site, { [key]: clone(currentSite[key]) });
    else delete st.view.bundle.project.site[key];
  }
  st.rects = snap.rects;
  st.tables = snap.tables;
  st.requests = snap.requests;
}

function fillInput(st: State, request: FillZoneRequest, fieldId: string) {
  const r = st.rects[request.support_surface_id];
  if (!r) throw new Error(`Unknown support surface ${request.support_surface_id}`);
  const mod = catalog.modules.find((m) => m.revision_id === request.module_definition_revision_id) ?? catalog.modules[0];
  return {
    surface: rectPoly(r),
    obstacles: st.view.bundle.scene.obstacles.map((o) => rectPoly(st.rects[o.obstacle_id])),
    module: { width_m: mod.width_m, height_m: mod.height_m },
    request,
    fieldId,
    pinned: st.tables.filter((t) => t.pv_field_id === fieldId && t.pinned),
    occupied: occupiedBy(st, request.support_surface_id, fieldId)
  };
}

/** Module footprints of the other fields on a surface (tables and module-by-module fields). */
function occupiedBy(st: State, surfaceId: string, fieldId: string): [number, number][][] {
  const others = new Set(st.view.bundle.scene.pv_fields.filter((f) => f.support_surface_id === surfaceId && f.pv_field_id !== fieldId).map((f) => f.pv_field_id));
  return [
    ...st.tables.filter((t) => others.has(t.pv_field_id) && t.status === "active").map((t) => tableFootprint(t) as [number, number][]),
    ...st.view.bundle.scene.module_instances.filter((m) => others.has(m.pv_field_id) && st.rects[m.module_instance_id]).map((m) => rectPoly(st.rects[m.module_instance_id]))
  ];
}

function editTables(st: State, fieldId: string, c: TableEditCommand) {
  const own = (id: string) => {
    const t = st.tables.find((x) => x.table_id === id && x.pv_field_id === fieldId);
    if (!t) throw new Error(`Unknown table ${id}`);
    return t;
  };
  switch (c.kind) {
    case "move_tables": {
      const moving = c.table_ids.map(own);
      const others = st.tables.filter((t) => t.status === "active" && !c.table_ids.includes(t.table_id));
      const surfaceId = st.view.bundle.scene.pv_fields.find((f) => f.pv_field_id === fieldId)?.support_surface_id ?? "";
      const surface = rectPoly(st.rects[surfaceId]);
      for (const t of moving) {
        const moved = { ...t, origin_m: [t.origin_m[0] + c.dx_m, t.origin_m[1] + c.dy_m] as [number, number] };
        const fp = tableFootprint(moved);
        const xs = surface.map((p) => p[0]);
        const ys = surface.map((p) => p[1]);
        if (fp.some((p) => p[0] < Math.min(...xs) - 1e-9 || p[0] > Math.max(...xs) + 1e-9 || p[1] < Math.min(...ys) - 1e-9 || p[1] > Math.max(...ys) + 1e-9))
          throw new Error("The table would leave its support surface (fail-closed).");
        for (const o of st.view.bundle.scene.obstacles)
          if (polygonDistance(fp, rectPoly(st.rects[o.obstacle_id])) <= 0) throw new Error(`The table would overlap ${o.name} (fail-closed).`);
        for (const x of others)
          if (polygonDistance(fp, tableFootprint(x)) <= 0 && polygonDistance(shrink(fp), tableFootprint(x)) <= 0)
            throw new Error("The table would overlap another table (fail-closed).");
        t.origin_m = moved.origin_m;
        t.pinned = true;
      }
      return;
    }
    case "delete_tables":
      for (const t of c.table_ids.map(own)) {
        t.status = "deleted";
        t.pinned = true;
      }
      return;
    case "delete_modules":
      for (const id of c.module_instance_ids) {
        const s = slotOf(id);
        if (!s) throw new Error(`Module ${id} is not in a table.`);
        const t = own(s.tableId);
        if (!t.removed_slots.some(([r, k]) => r === s.row && k === s.column)) t.removed_slots.push([s.row, s.column, "manual"]);
        t.pinned = true;
        if (t.removed_slots.length >= t.rows * t.columns) t.status = "deleted";
      }
      return;
    case "unpin_tables":
      for (const t of c.table_ids.map(own)) t.pinned = false;
      st.tables = st.tables.filter((t) => !(c.table_ids.includes(t.table_id) && t.status === "deleted"));
      return;
  }
}

/** A footprint pulled in by 1 mm, so tables that only touch do not count as overlapping. */
function shrink(poly: [number, number][]): [number, number][] {
  const cx = poly.reduce((s, p) => s + p[0], 0) / poly.length;
  const cy = poly.reduce((s, p) => s + p[1], 0) / poly.length;
  return poly.map((p) => {
    const dx = p[0] - cx;
    const dy = p[1] - cy;
    const l = Math.hypot(dx, dy) || 1;
    return [p[0] - (dx / l) * 0.001, p[1] - (dy / l) * 0.001];
  });
}
const clone = <T>(v: T): T => structuredClone(v);
let latencyScale = 1;
/** Tests set 0 so hundreds of demo commands run without simulated network latency. */
export function setDemoLatency(scale: number): void {
  latencyScale = scale;
}
// Every returned view carries its current demo fingerprint (RES1), like the server's transient field.
const stamp = <T,>(v: T): T => {
  if (v && typeof v === "object" && "bundle" in v && "history" in v) (v as unknown as ProjectView).design_fingerprint = demoDesignFingerprint((v as unknown as ProjectView).bundle);
  return v;
};
const wait = <T>(v: T, ms = 120) => new Promise<T>((r) => setTimeout(() => r(stamp(clone(v))), ms * latencyScale));
const notInDemo = (method: string): Promise<never> => Promise.reject(new DemoUnavailableError(method));

function fieldImpact(fieldId: string): PvFieldDeletePreview {
  const field = state.view.bundle.scene.pv_fields.find((f) => f.pv_field_id === fieldId);
  if (!field) throw new Error(`PV field not found: ${fieldId}`);
  const modules = state.view.bundle.scene.module_instances.filter((m) => m.pv_field_id === fieldId);
  const ids = new Set(modules.map((m) => m.module_instance_id));
  const strings = state.view.bundle.electrical_design.strings.filter((s) => s.module_instance_ids.some((id) => ids.has(id))).map((s) => s.string_id).sort();
  return { dry_run: true, pv_field_id: fieldId, module_count: modules.length,
    stc_power_w: modules.length * (catalog.modules.find((m) => m.revision_id === field.module_definition_revision_id)?.pmp_w ?? 0),
    string_ids: strings, requires_discard_dependent_strings: strings.length > 0 };
}

function refillDraft(fieldId: string, changes: PvFieldChanges) {
  const current = state.view.bundle.scene.pv_fields.find((field) => field.pv_field_id === fieldId);
  if (current && changes.module_definition_revision_id !== undefined && changes.module_definition_revision_id !== current.module_definition_revision_id)
    throw new DemoUnavailableError("Changing the module needs the engine");
  if (current && changes.module_definition_revision_id === current.module_definition_revision_id) {
    const { module_definition_revision_id: _unchanged, ...remaining } = changes;
    changes = remaining;
  }
  const before = fieldImpact(fieldId);
  if (state.requests[fieldId]) throw new Error("Use the table-level re-fill for this demo field.");
  const draft: State = { ...clone({ view: state.view, rects: state.rects, tables: state.tables, requests: state.requests }), undo: [], redo: [] };
  const field = draft.view.bundle.scene.pv_fields.find((f) => f.pv_field_id === fieldId)!;
  const repack = Object.keys(changes).some((key) => key !== "name");
  const manual = field.layout_status === "manual" && repack;
  const strings = repack ? before.string_ids : [];
  Object.assign(field, changes);
  field.setback_configuration = { ...field.setback_configuration,
    ...(changes.perimeter_setback_m !== undefined ? { perimeter_setback_m: changes.perimeter_setback_m } : {}),
    ...(changes.obstacle_setback_m !== undefined ? { obstacle_setback_m: changes.obstacle_setback_m } : {}) };
  if (repack) {
    for (const m of draft.view.bundle.scene.module_instances.filter((m) => m.pv_field_id === fieldId)) delete draft.rects[m.module_instance_id];
    draft.view.bundle.scene.module_instances = draft.view.bundle.scene.module_instances.filter((m) => m.pv_field_id !== fieldId);
    fill(draft, fieldId, field.support_surface_id, {
      orientation: field.orientation, tilt_deg: field.tilt_deg, module_gap_x_m: field.module_gap_x_m!,
      row_pitch_m: field.row_pitch_m!, perimeter_setback_m: field.setback_configuration.perimeter_setback_m!,
      obstacle_setback_m: field.setback_configuration.obstacle_setback_m!
    });
    field.layout_status = "packed";
  }
  const count = draft.view.bundle.scene.module_instances.filter((m) => m.pv_field_id === fieldId).length;
  if (!count) throw new Error("PV field packing produced zero modules; adjust surface, setback, orientation, row pitch, or module selection");
  const preview: PvFieldUpdatePreview = { dry_run: true, pv_field_id: fieldId,
    module_count_before: before.module_count, module_count_after: count,
    stc_power_w_before: before.stc_power_w,
    stc_power_w_after: count * (catalog.modules.find((m) => m.revision_id === field.module_definition_revision_id)?.pmp_w ?? 0),
    string_ids: strings, requires_discard_dependent_strings: strings.length > 0, requires_discard_manual_layout: manual, conflicts: [] };
  return { draft, preview };
}

function commitFieldDraft(draft: State, strings: string[]): Promise<ProjectView> {
  commit(state);
  draft.view.bundle.electrical_design.strings = draft.view.bundle.electrical_design.strings.filter((s) => !strings.includes(s.string_id));
  state.view = draft.view; state.rects = draft.rects; state.tables = draft.tables; state.requests = draft.requests;
  rebuildFeatures(state);
  return wait(state.view);
}


function sceneDraft(): State {
  return { ...clone({ view: state.view, rects: state.rects, tables: state.tables, requests: state.requests }), undo: [], redo: [] };
}
function setDemoGeometry(draft: State, id: string, vertices: Vec2[]) {
  const issues = validatePolygon(vertices);
  if (issues.length) throw new Error(issues[0].message);
  const box = bounds([vertices]);
  draft.rects[id] = { x: box.minX, y: box.minY, w: box.maxX - box.minX, h: box.maxY - box.minY, vertices };
}

/** Illustrative demo geometry only; no engineering result is produced here. */
function moduleObstacleConflicts(draft: State, obstacleId?: string) {
  const scene = draft.view.bundle.scene;
  const modules = [
    ...scene.module_instances.filter((m) => draft.rects[m.module_instance_id]).map((m) => ({ id: m.module_instance_id, fieldId: m.pv_field_id, polygon: rectPoly(draft.rects[m.module_instance_id]) })),
    ...draft.tables.flatMap((t) => tableModules(t).map((m) => ({ id: m.id, fieldId: t.pv_field_id, polygon: m.polygon })))
  ];
  const conflicts: Array<{ module_instance_id: string; pv_field_id: string; other_id: string; code: string }> = [];
  for (const module of modules) {
    const field = scene.pv_fields.find((f) => f.pv_field_id === module.fieldId)!;
    const surface = scene.surfaces.find((s) => s.surface_id === field.support_surface_id)!;
    const definition = catalog.modules.find((m) => m.revision_id === field.module_definition_revision_id)!;
    const points = module.polygon;
    const center: Vec2 = [points.reduce((n,p)=>n+p[0],0)/points.length, points.reduce((n,p)=>n+p[1],0)/points.length];
    const bottom = (planeZ(rectPoly(draft.rects[surface.surface_id]), enginePlaneToUi(rectPoly(draft.rects[surface.surface_id]), surface), center) ?? surface.base_elevation_m) + (field.mounting_height_m ?? 0.2);
    const top = bottom + (field.orientation === "portrait" ? definition.height_m : definition.width_m) * Math.sin(field.tilt_deg * Math.PI / 180);
    for (const obstacle of scene.obstacles.filter((o) => !obstacleId || o.obstacle_id === obstacleId)) {
      if (obstacle.base_elevation_m > top || obstacle.base_elevation_m + obstacle.height_m < bottom) continue;
      const polygon = rectPoly(draft.rects[obstacle.obstacle_id]);
      const overlap = polygonDistance(shrink(module.polygon), shrink(polygon)) === 0;
      const setback = field.setback_configuration?.obstacle_setback_m ?? 0;
      if (overlap || (setback > 0 && polygonDistance(module.polygon, polygon) < setback)) conflicts.push({ module_instance_id: module.id, pv_field_id: module.fieldId, other_id: obstacle.obstacle_id, code: overlap ? "module_obstacle_overlap" : "module_obstacle_setback" });
    }
  }
  return conflicts;
}
function demoKeepoutSelected(draft: State, field: DemoView["bundle"]["scene"]["pv_fields"][number], id: string) {
  const surface = draft.view.bundle.scene.surfaces.find((s) => s.surface_id === id);
  if (!surface || field.support_surface_id === id) return false;
  const rules = field.exclusion_rules ?? {};
  const types = rules.surface_types?.length ? rules.surface_types : ["exclusion_area", "walkway"];
  const selected = rules.surface_ids?.includes(id) || ((rules.use_scene_exclusion_surfaces ?? true) && types.includes(surface.surface_type));
  return !!selected && polygonDistance(rectPoly(draft.rects[field.support_surface_id]), rectPoly(draft.rects[id])) === 0;
}

/** Demo interaction only; the real packer is the engineering authority. */
function moduleKeepoutConflicts(draft: State, id: string) {
  const modules = [
    ...draft.view.bundle.scene.module_instances.filter((m) => draft.rects[m.module_instance_id]).map((m) => ({ id: m.module_instance_id, fieldId: m.pv_field_id, polygon: rectPoly(draft.rects[m.module_instance_id]) })),
    ...draft.tables.flatMap((table) => tableModules(table).map((m) => ({ id: m.id, fieldId: table.pv_field_id, polygon: m.polygon })))
  ];
  return modules.filter((module) => {
    const field = draft.view.bundle.scene.pv_fields.find((f) => f.pv_field_id === module.fieldId)!;
    return demoKeepoutSelected(draft, field, id) && polygonDistance(module.polygon, rectPoly(draft.rects[id])) === 0;
  }).map((module) => ({ module_instance_id: module.id, pv_field_id: module.fieldId, other_id: id, code: "module_exclusion_overlap" }));
}

async function finishSceneDraft(draft: State, obstacleId: string | undefined, policy: SceneConflictOptions, keepoutId?: string): Promise<ProjectView | ScenePreview> {
  const conflicts = keepoutId ? moduleKeepoutConflicts(draft, keepoutId) : obstacleId ? moduleObstacleConflicts(draft, obstacleId) : [];
  const affected = new Set(conflicts.filter((c) => c.code === (keepoutId ? "module_exclusion_overlap" : "module_obstacle_overlap")).map((c) => c.pv_field_id));
  const ids = [...new Set(conflicts.filter((c) => affected.has(c.pv_field_id)).map((c) => c.module_instance_id))].sort();
  const strings = draft.view.bundle.electrical_design.strings.filter((s) => s.module_instance_ids.some((id) => ids.includes(id))).map((s) => s.string_id).sort();
  const power = ids.reduce((sum, id) => {
    const field = draft.view.bundle.scene.pv_fields.find((f) => f.pv_field_id === conflicts.find((c) => c.module_instance_id === id)!.pv_field_id)!;
    return sum + catalog.modules.find((m) => m.revision_id === field.module_definition_revision_id)!.pmp_w;
  }, 0);
  const options: ObstacleConflictDetail["options"] = {
    remove_modules: { module_instance_ids: ids, module_count: ids.length, stc_power_w: power, string_ids: strings },
    refill_field: { available: false, reason: keepoutId ? "Demo mode: keep-out re-fill requires the real engine." : "Demo mode: obstacle re-fill requires the real engine.", fields: [], string_ids: [] }
  };
  if (policy.dry_run) return { dry_run: true, conflicts, ...(obstacleId || keepoutId ? { options } : {}), ...(keepoutId ? {
    ignored_by_fields: draft.view.bundle.scene.pv_fields.filter((field) => field.support_surface_id !== keepoutId
      && polygonDistance(rectPoly(draft.rects[field.support_surface_id]), rectPoly(draft.rects[keepoutId])) === 0
      && !demoKeepoutSelected(draft, field, keepoutId)).map((field) => ({ pv_field_id: field.pv_field_id, reason: "field_exclusion_rules_ignore_keepout" as const }))
  } : {}) };
  if (ids.length) {
    if (policy.on_module_conflict !== "remove_modules" || (strings.length > 0 && !policy.discard_dependent_strings)) {
      const message = `${keepoutId ? "Keep-out" : "Obstacle"} overlaps modules. Choose how to handle the layout.`;
      throw new ApiError(message, 422, { message, conflicts, options });
    }
    for (const field of draft.view.bundle.scene.pv_fields) if (affected.has(field.pv_field_id)) field.layout_status = "manual";
    for (const id of ids) delete draft.rects[id];
    draft.view.bundle.scene.module_instances = draft.view.bundle.scene.module_instances.filter((m) => !ids.includes(m.module_instance_id));
    for (const id of ids.filter((id) => slotOf(id))) {
      const slot = slotOf(id)!;
      const table = draft.tables.find((t) => t.table_id === slot.tableId)!;
      table.removed_slots.push([slot.row, slot.column, "manual"]);
      table.pinned = true;
    }
  }
  return commitFieldDraft(draft, strings);
}


/** Illustrative demo re-fill; the real packer remains authoritative over HTTP. */
async function finishDependentDemo(draft: State, fields: DemoView["bundle"]["scene"]["pv_fields"], action: "refill" | "delete", options: SceneConflictOptions) {
  const before = state.view.bundle;
  const b = draft.view.bundle;
  const previews: DependentFieldPreview[] = [];
  for (const field of [...fields].sort((a, b) => a.pv_field_id.localeCompare(b.pv_field_id))) {
    const id = field.pv_field_id;
    const old = before.scene.module_instances.filter((module) => module.pv_field_id === id);
    const oldIds = new Set(old.map((module) => module.module_instance_id));
    const strings = before.electrical_design.strings.filter((string) => string.module_instance_ids.some((id) => oldIds.has(id))).map((string) => string.string_id).sort();
    const manual = field.layout_status === "manual" || draft.tables.some((table) => table.pv_field_id === id && table.pinned);
    for (const module of old) delete draft.rects[module.module_instance_id];
    b.scene.module_instances = b.scene.module_instances.filter((module) => module.pv_field_id !== id);
    draft.tables = draft.tables.filter((table) => table.pv_field_id !== id);
    if (action === "delete") {
      b.scene.pv_fields = b.scene.pv_fields.filter((field) => field.pv_field_id !== id);
      delete draft.requests[id];
    } else if (draft.requests[id]) {
      draft.tables.push(...fillZone(fillInput(draft, draft.requests[id], id)).tables);
    } else {
      if (!field.setback_configuration) throw new ApiError("Stored field setback parameters are missing.", 422, { message: "Stored field setback parameters are missing.", dependent_fields: [] });
      fill(draft, id, field.support_surface_id, { orientation: field.orientation, tilt_deg: field.tilt_deg,
        module_gap_x_m: field.module_gap_x_m!, row_pitch_m: field.row_pitch_m!,
        perimeter_setback_m: field.setback_configuration.perimeter_setback_m!, obstacle_setback_m: field.setback_configuration.obstacle_setback_m! });
      const roof = rectPoly(draft.rects[field.support_surface_id]);
      b.scene.module_instances = b.scene.module_instances.filter((module) => {
        if (module.pv_field_id !== id || rectPoly(draft.rects[module.module_instance_id]).every((point) => pointInPolygon(point, roof))) return true;
        delete draft.rects[module.module_instance_id]; return false;
      });
    }
    const count = b.scene.module_instances.filter((module) => module.pv_field_id === id).length + moduleCountOf(draft.tables.filter((table) => table.pv_field_id === id));
    const power = catalog.modules.find((module) => module.revision_id === field.module_definition_revision_id)!.pmp_w;
    previews.push({ pv_field_id: id, name: field.name, action, module_count_before: old.length, module_count_after: count,
      stc_power_w_before: old.length * power, stc_power_w_after: count * power, string_ids: strings,
      requires_discard_dependent_strings: strings.length > 0, requires_discard_manual_layout: manual, conflicts: [] });
    if (action === "refill") field.layout_status = "packed";
  }
  const affected = new Set(fields.map((field) => field.pv_field_id));
  const obstacleConflicts = moduleObstacleConflicts(draft).filter((item) => affected.has(item.pv_field_id));
  const modules = [
    ...b.scene.module_instances.filter((module) => draft.rects[module.module_instance_id]).map((module) => ({ id: module.module_instance_id, field: module.pv_field_id, polygon: rectPoly(draft.rects[module.module_instance_id]) })),
    ...draft.tables.flatMap((table) => tableModules(table).map((module) => ({ id: module.id, field: table.pv_field_id, polygon: module.polygon })))
  ];
  for (const preview of previews) {
    preview.conflicts = obstacleConflicts.filter((item) => item.pv_field_id === preview.pv_field_id);
    for (const module of modules.filter((module) => module.field === preview.pv_field_id))
      for (const other of modules.filter((other) => other.field !== module.field))
        if (polygonDistance(shrink(module.polygon), shrink(other.polygon)) === 0) preview.conflicts.push({ code: "module_module_overlap", module_instance_id: module.id, other_id: other.id });
  }
  if (options.dry_run) return wait({ dry_run: true as const, dependent_fields: previews, conflicts: [] });
  let message = "";
  if (previews.some((field) => field.requires_discard_manual_layout) && !options.discard_manual_layout) message = "Dependent fields require discard_manual_layout=true.";
  else if (previews.some((field) => field.action === "refill" && !field.module_count_after)) message = "Re-filled dependent field would have zero modules.";
  else if (previews.some((field) => field.conflicts.length)) message = "Re-filled dependent fields have geometry conflicts.";
  else if (previews.some((field) => field.requires_discard_dependent_strings) && !options.discard_dependent_strings) message = "Dependent fields require discard_dependent_strings=true.";
  if (message) throw new ApiError(message, 422, { message, dependent_fields: previews });
  return commitFieldDraft(draft, previews.flatMap((field) => field.string_ids));
}


let projectDeleted = false;

function demoLossDefaults(): import("../types").ResolvedLossSettings {
  return { schema_name: "LossSettings", schema_version: "0.1", defaults_id: "recommended_defaults.v2", overrides: {},
    status: "recommended_defaults", settings_sha256: "demo-illustrative", sources: {},
    values: { soiling: { monthly_fractions: Array(12).fill(0.03) }, lid_fraction: null,
      module_mismatch_fraction: null, string_mismatch_fraction: null, dc_wiring_stc_fraction: 0.015,
      ac_wiring_nominal_fraction: 0, annual_degradation_fraction: 0.004, operating_year: 1,
      degradation_fraction: 0.002, transformer: { enabled: false, reference_power_w: null, iron_fraction: 0.001, copper_fraction: null },
      unavailability_fraction: 0 } };
}

function demoStringLengths(moduleId: string, inverterId: string, moduleCount: number): number[] {
  const mod = DEMO_MODULE_ELECTRICAL[moduleId], elec = DEMO_INVERTER_ELECTRICAL[inverterId];
  return mod && elec ? Array.from({ length: moduleCount }, (_, i) => i + 1)
    .filter(n => n * mod.voc * DEMO_COLD_FACTOR <= elec.maxDc && n * mod.vmp >= elec.window[0] && n * mod.vmp <= elec.window[1]) : [];
}

/** DEMO ONLY: the engine's suggest-layout rule on the demo's electrical stand-ins (cold factor, STC Vmp window). */
function demoSuggestLayout(st: State, inverterId: string, pvFieldIds: string[] | null): MpptLayoutSuggestion {
  const e = st.view.bundle.electrical_design;
  const none = (code: string, message: string): MpptLayoutSuggestion => ({ schema_name: "MpptLayoutSuggestion", schema_version: "demo", status: "no_solution", reasons: [{ code, message }] });
  const inv = e.inverter_instances.find((i) => i.inverter_instance_id === inverterId);
  if (!inv) return none("NOT_FOUND", `inverter not found: ${inverterId}`);
  const fields = pvFieldIds?.length ? pvFieldIds : inv.paired_pv_field_ids?.length ? inv.paired_pv_field_ids : st.view.bundle.scene.pv_fields.map((f) => f.pv_field_id);
  const taken = new Set(e.strings.filter((s) => s.target_mppt_instance_id && !inv.mppt_instance_ids.includes(s.target_mppt_instance_id)).flatMap((s) => s.module_instance_ids));
  const ctx = topologyContext(st);
  // Modules of the inverter's own and of free strings count: a suggestion restrings them (as the engine does).
  const pool = [...ctx.modules.values()].filter((m) => fields.includes(m.fieldId) && !taken.has(m.id));
  if (!pool.length) return none("NO_MODULES", "No free modules in the inverter's PV fields.");
  const moduleId = st.view.bundle.scene.pv_fields.find((f) => f.pv_field_id === pool[0].fieldId)?.module_definition_revision_id ?? "";
  const mod = DEMO_MODULE_ELECTRICAL[moduleId], elec = DEMO_INVERTER_ELECTRICAL[inv.inverter_definition_revision_id];
  if (!mod || !elec) return none("MODULE_MODEL_UNAVAILABLE", "The demo has no electrical data for this module or inverter.");
  const lengths = demoStringLengths(moduleId, inv.inverter_definition_revision_id, pool.length);
  if (!lengths.length) return none("NO_STRING_LENGTH", "No string length keeps cold Voc under the limit and Vmp inside the MPPT window.");
  // As the engine ranks: the most modules strung, then the longer string.
  const capacity = inv.mppt_instance_ids.length * elec.inputs;
  const used = (l: number) => Math.min(Math.floor(pool.length / l), capacity) * l;
  const n = lengths.reduce((best, l) => (used(l) > used(best) || (used(l) === used(best) && l > best) ? l : best));
  const strings = used(n) / n;
  const counts = inv.mppt_instance_ids.map((_, i) => Math.floor(strings / inv.mppt_instance_ids.length) + (i < strings % inv.mppt_instance_ids.length ? 1 : 0));
  return { schema_name: "MpptLayoutSuggestion", schema_version: "demo", status: "suggestion_available", inverter_instance_id: inverterId, pv_field_ids: fields,
    layout: counts.map((c) => (c ? Array(c).fill(n) : [0])),
    replace_string_ids: e.strings.filter((s) => (!s.target_mppt_instance_id || inv.mppt_instance_ids.includes(s.target_mppt_instance_id))
      && s.module_instance_ids.every((m) => pool.some((x) => x.id === m))).map((s) => s.string_id).sort(),
    string_length: n, string_count: strings, modules_used: strings * n, modules_left: pool.length - strings * n,
    inputs_per_mppt: elec.inputs, inputs_per_mppt_source: "definition",
    warnings: counts.some((c) => c * mod.imp > elec.maxInputA) ? [{ rule_id: "MPPT_OPERATING_CURRENT_EXCEEDED", message: "The demo MPPT current exceeds its limit; the inverter clips it." }] : [],
    basis: "DEMO ONLY: demo electrical stand-ins, not the engine's validation.", rejected: [], reasons: [] };
}

/** DEMO ONLY: the projects-page summary (apps/api/project_store.py project_system_summary) of the demo project. */
function demoSystemSummary(st: State): ProjectSystemSummary {
  const b = st.view.bundle;
  const count = <K extends string>(keys: K[]) => [...keys.reduce((m, k) => m.set(k, (m.get(k) ?? 0) + 1), new Map<K, number>())];
  const modules = count(b.scene.pv_fields.flatMap((f) => b.scene.module_instances.filter((m) => m.pv_field_id === f.pv_field_id).map(() => f.module_definition_revision_id)))
    .map(([rev, n]) => { const m = catalog.modules.find((x) => x.revision_id === rev); return { model: m?.model ?? rev, manufacturer: m?.manufacturer, count: n, rating_w: m?.pmp_w ?? null }; });
  const inverters = count(b.electrical_design.inverter_instances.map((i) => i.inverter_definition_revision_id))
    .map(([rev, n]) => { const i = catalog.inverters.find((x) => x.revision_id === rev); return { model: i?.model ?? rev, manufacturer: i?.manufacturer, count: n, rating_w: i?.nominal_ac_power_w ?? null }; });
  const run = [...b.simulation_runs].reverse().find((r) => r.status !== "failed" && r.summary_result)?.summary_result;
  return {
    modules, dc_kwp: modules.reduce((t, m) => t + (m.rating_w ?? 0) * m.count, 0) / 1000,
    inverters, ac_kw: inverters.reduce((t, i) => t + (i.rating_w ?? 0) * i.count, 0) / 1000,
    last_run: run ? { simulation_run_id: run.simulation_run_id, energy_kwh: run.total_energy_wh / 1000, annual: run.annual_energy_wh != null,
      specific_yield_kwh_kwp: run.specific_yield_wh_per_wp, performance_ratio: run.performance_ratio } : null
  };
}

/** DEMO ONLY: the engine's shading-free pitch formula (geometry/pvfield/pitch.py). */
function demoShadingFreePitch(depth: number, input: { tilt_deg: number; design_sun_elevation_deg: number; sun_azimuth_offset_deg: number }): ShadingFreePitch {
  const r = Math.PI / 180, plan = depth * Math.cos(input.tilt_deg * r);
  const shadow = depth * Math.sin(input.tilt_deg * r) * Math.max(Math.cos(Math.abs(input.sun_azimuth_offset_deg) * r), 0) / Math.tan(input.design_sun_elevation_deg * r);
  return { row_pitch_m: plan + shadow, plan_depth_m: plan, shadow_length_m: shadow, ground_coverage_ratio: plan / (plan + shadow), basis: "plan_depth_plus_shadow_at_design_sun.v1 (demo)" };
}

/** DEMO ONLY: illustrative systems geometry with the engine's complete-linkage normal-angle convention. */
export function demoSystemsOverview(view: ProjectView, rects: Record<string, Rect> = {}): SystemsOverview {
  const b = view.bundle;
  const surfaces = b.scene.surfaces;
  const fields = b.scene.pv_fields;
  const modules = fields.flatMap(f => b.scene.module_instances.filter(m => m.pv_field_id === f.pv_field_id && m.enabled));
  const supportIds = (f: typeof fields[number]) => f.field_kind === "explicit_layout"
    ? [...new Set(f.tables.flatMap(t => t.support_surface_id ? [t.support_surface_id] : []))] : [f.support_surface_id];
  const placement = (m: typeof modules[number]) => {
    const f = fields.find(f => f.pv_field_id === m.pv_field_id)!;
    const mount = f.field_kind === "explicit_layout" ? f.tables.find(t => t.table_id === m.table_id)! : f;
    return { field: f, mount, surface: surfaces.find(s => s.surface_id === mount.support_surface_id) };
  };
  const kwp = (ms: typeof modules) => ms.reduce((sum, m) => {
    const p = placement(m);
    const definition = view.catalog.modules.find(d => d.revision_id === (m.module_definition_revision_id ?? p.mount.module_definition_revision_id));
    if (!definition) throw new Error("Module definition is missing");
    return sum + (definition.nominal_power_w ?? definition.pmp_w) / 1000;
  }, 0);
  const entry = (building_id: string | null, name: string, ids: string[]) => {
    const ms = modules.filter(m => ids.includes(placement(m).mount.support_surface_id ?? ""));
    return { building_id, name, surface_ids: ids, pv_field_ids: fields.filter(f => supportIds(f).some(id => ids.includes(id))).map(f => f.pv_field_id), module_count: ms.length, stc_kwp: kwp(ms) };
  };
  const buildings = (b.scene.buildings ?? []).map(g => entry(g.building_id, g.name, surfaces.filter(s => s.group_id === g.building_id).map(s => s.surface_id)));
  for (const s of surfaces) if (!s.group_id && fields.some(f => supportIds(f).includes(s.surface_id))) buildings.push(entry(null, s.name, [s.surface_id]));
  const polygon = (id: string) => surfaces.find(s => s.surface_id === id)!.boundary_2d?.vertices ?? rectPoly(rects[id]);
  const eligible = surfaces.filter(s => s.usable_for_pv !== false).map(s => s.surface_id).sort();
  const parent = eligible.map((_, i) => i);
  const find = (i: number): number => parent[i] === i ? i : (parent[i] = find(parent[i]));
  for (let i = 0; i < eligible.length; i++) for (let j = i + 1; j < eligible.length; j++)
    if (polygonDistance(polygon(eligible[i]), polygon(eligible[j])) <= 1) parent[find(j)] = find(i);
  const clusters = new Map<number, string[]>();
  eligible.forEach((id, i) => clusters.set(find(i), [...(clusters.get(find(i)) ?? []), id]));
  const suggested_buildings = [...clusters.values()].sort((a, c) => a[0] < c[0] ? -1 : a[0] > c[0] ? 1 : 0).map((ids, i) => ({
    name: `Building ${i + 1}`, surface_ids: ids,
    matches_confirmed: buildings.some(g => g.building_id !== null && g.surface_ids.length === ids.length && ids.every(id => g.surface_ids.includes(id)))
  }));
  const threshold_m = b.project.distance_warning_m ?? 50;
  const distances: SystemsOverview["distances"] = [];
  buildings.forEach((a, i) => buildings.slice(i + 1).forEach((c, j) => {
    const distance_m = Math.min(...a.surface_ids.flatMap(x => c.surface_ids.map(y => polygonDistance(polygon(x), polygon(y)))));
    distances.push({ from_index: i, to_index: i + j + 1, distance_m, over_threshold: distance_m > threshold_m });
  }));
  const tolerance_deg = b.electrical_design.orientation_policy?.normal_angle_tolerance_deg ?? 1;
  const orientation: Array<{ members: typeof modules; revision: string; albedo: number; normals: Array<[number, number]> }> = [];
  for (const m of modules) {
    const p = placement(m), normal: [number, number] = [p.mount.tilt_deg, p.mount.azimuth_deg];
    const revision = m.module_definition_revision_id ?? p.mount.module_definition_revision_id;
    const albedo = (p.surface as (typeof surfaces[number] & { albedo?: number }) | undefined)?.albedo ?? .2;
    let group = orientation.find(g => g.revision === revision && g.albedo === albedo && g.normals.every(n => normalAngleDeg(...n, ...normal) <= tolerance_deg));
    if (!group) { group = { members: [], normals: [], revision, albedo }; orientation.push(group); }
    group.members.push(m); group.normals.push(normal);
  }
  const orientation_groups = orientation.map(g => {
    const ids = [...new Set(g.members.flatMap(m => placement(m).mount.support_surface_id ?? []))];
    return { label: `${g.normals[0][0].toFixed(1)}° / ${g.normals[0][1].toFixed(1)}°`,
      module_definition_revision_ids: [g.revision],
      pv_field_ids: [...new Set(g.members.map(m => m.pv_field_id))], surface_ids: ids,
      building_ids: [...new Set(ids.length ? ids.map(id => surfaces.find(s => s.surface_id === id)?.group_id ?? null) : [null])], module_count: g.members.length, stc_kwp: kwp(g.members) };
  });
  return { schema_name: "SystemsOverview", schema_version: "0.1", buildings, suggested_buildings, distances, threshold_m, tolerance_deg, orientation_groups };
}

export const mockApi = {
  sceneGeometry3d: async (_projectId: string, _signal?: AbortSignal): Promise<import("../types").ExactSceneGeometry> => {
    throw new DemoUnavailableError("Exact mesh and table geometry needs the real engine.");
  },
  componentLibrary: async (_includeHidden = false): Promise<never> => { throw new DemoUnavailableError("Importing components needs the engine"); },
  previewComponent: async (_file: File): Promise<never> => { throw new DemoUnavailableError("Importing components needs the engine"); },
  importComponent: async (_file: File): Promise<never> => { throw new DemoUnavailableError("Importing components needs the engine"); },
  previewComponentCompletion: async (_revisionId: string, _input: ComponentCompletionInput): Promise<never> => { throw new DemoUnavailableError("Completing datasheet values needs the engine"); },
  completeComponent: async (_revisionId: string, _input: ComponentCompletionInput): Promise<never> => { throw new DemoUnavailableError("Completing datasheet values needs the engine"); },
  hideComponent: async (_revisionId: string): Promise<never> => { throw new DemoUnavailableError("Importing components needs the engine"); },
  unhideComponent: async (_revisionId: string): Promise<never> => { throw new DemoUnavailableError("Importing components needs the engine"); },
  systemsOverview: (_id: string) => wait(demoSystemsOverview(state.view, state.rects)),
  updateProject: (_id: string, changes: { name?: string; description?: string; distance_warning_m?: number }) => {
    if ("distance_warning_m" in changes && (typeof changes.distance_warning_m !== "number" || !Number.isFinite(changes.distance_warning_m) || changes.distance_warning_m < 0 || changes.distance_warning_m > 10000))
      return Promise.reject(new Error("distance_warning_m must be within [0, 10000]"));
    Object.assign(state.view.bundle.project, changes);
    return wait(state.view);
  },
  updateSite: (_id: string, changes: SiteChanges, options?: { clear_weather_selection?: boolean }) => {
    const site = state.view.bundle.project.site;
    const weatherChanged = Object.entries(changes).some(([key, value]) => key !== "name" && site[key as keyof typeof site] !== value);
    if (weatherChanged && state.view.bundle.weather_selection && !options?.clear_weather_selection) return Promise.reject(new Error("Confirm clearing the weather selection."));
    Object.assign(site, changes);
    Object.assign(state.view.scene_view.site, changes);
    if (weatherChanged && options?.clear_weather_selection) state.view.bundle.weather_selection = null;
    if (Object.keys(changes).length) state.view.bundle.project.project_revision.revision_number++;
    return wait(state.view);
  },
  updateSiteDetails: (_id: string, changes: import("../types").ReportSiteChanges) => {
    const site = state.view.bundle.project.site;
    const { copy_if_missing, ...values } = changes;
    if (!Object.keys(values).length || Object.keys(values).some(key => key !== "address" && key !== "installation"))
      return Promise.reject(new Error("site details update requires only address or installation"));
    Object.assign(site, Object.fromEntries(Object.entries(values).filter(([key]) => !copy_if_missing || !(key in site))));
    persistDemoReportSite(state.view);
    return wait(state.view);
  },
  deleteProject: (id: string, confirm: string) => {
    if (id !== confirm) return Promise.reject(new Error("Confirmation must equal the project id."));
    projectDeleted = true;
    try { window.localStorage.removeItem(DEMO_REPORT_SITE_KEY); } catch { /* Storage may be disabled. */ }
    return wait({ deleted_project_id: id, removed: { bundle: true, runs: state.view.bundle.simulation_runs.length > 0, weather: !!state.view.bundle.weather_selection } });
  },
  updateLosses: (_id: string, patch: import("../types").LossPatch) => {
    const current = state.view.bundle.loss_settings ?? demoLossDefaults();
    const overrides = "reset_to_recommended_defaults" in patch ? {} : clone(current.overrides) as Record<string, unknown>;
    if ("overrides" in patch) {
      for (const [key, value] of Object.entries(patch.overrides)) {
        if ((key === "circuit_overrides" || key === "plant_ac_wiring") && value && typeof value === "object") {
          const merge = (target: Record<string, unknown>, patch: Record<string, unknown>) => {
            for (const [field, item] of Object.entries(patch)) {
              if (item === null) delete target[field];
              else if (item && typeof item === "object" && !Array.isArray(item)) {
                const child = { ...((target[field] as Record<string, unknown>) ?? {}) };
                merge(child, item as Record<string, unknown>);
                if (Object.keys(child).length) target[field] = child; else delete target[field];
              } else target[field] = item;
            }
          };
          const target = key === "plant_ac_wiring" ? {} : { ...((overrides[key] as Record<string, unknown>) ?? {}) };
          merge(target, value as Record<string, unknown>); overrides[key] = target;
        } else if (value == null) delete overrides[key];
        else if (typeof value === "object" && !Array.isArray(value)) {
          const nested = { ...(overrides[key] as Record<string, unknown> ?? {}) };
          for (const [k, v] of Object.entries(value)) { if (v == null) delete nested[k]; else nested[k] = v; }
          if (key === "soiling" && "monthly_fractions" in value) delete nested.annual_fraction;
          if (key === "soiling" && "annual_fraction" in value) delete nested.monthly_fractions;
          overrides[key] = nested;
        } else overrides[key] = value;
      }
    }
    const resolved = demoLossDefaults();
    resolved.defaults_id = "reset_to_recommended_defaults" in patch ? "recommended_defaults.v2" : patch.defaults_id ?? current.defaults_id;
    if (resolved.defaults_id === "recommended_defaults.v1") resolved.values.lid_fraction = 0;
    resolved.overrides = overrides as import("../types").LossOverrides;
    Object.assign(resolved.values, overrides);
    resolved.values.soiling = { monthly_fractions: resolved.overrides.soiling?.monthly_fractions ?? demoLossDefaults().values.soiling.monthly_fractions };
    if (resolved.overrides.soiling?.annual_fraction != null) resolved.values.soiling.monthly_fractions = Array(12).fill(resolved.overrides.soiling.annual_fraction);
    resolved.values.transformer = { ...demoLossDefaults().values.transformer, ...resolved.overrides.transformer };
    resolved.values.degradation_fraction = resolved.values.annual_degradation_fraction * (resolved.values.operating_year - 0.5);
    function markSources(value: Record<string, unknown>, path = "") {
      for (const [key, v] of Object.entries(value)) {
        const leaf = path ? `${path}.${key}` : key;
        if (v && typeof v === "object" && !Array.isArray(v)) markSources(v as Record<string, unknown>, leaf);
        else resolved.sources[leaf] = "user";
      }
    }
    markSources(overrides);
    if (resolved.overrides.soiling?.annual_fraction != null) resolved.sources["soiling.monthly_fractions"] = "user";
    resolved.status = Object.keys(overrides).length ? "edited" : "recommended_defaults";
    resolved.settings_sha256 = "demo-illustrative-" + JSON.stringify(overrides);
    state.view.bundle.loss_settings = { schema_name: "LossSettings", schema_version: "0.1", defaults_id: resolved.defaults_id, overrides: resolved.overrides };
    state.view.resolved_loss_settings = resolved;
    state.view.bundle.project.project_revision.revision_number++;
    return wait(state.view);
  },
  uploadImageryAsset: async (_id: string, file: Blob, filename: string): Promise<ImageryAsset> => {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const header = imageHeader(bytes);
    if ("problem" in header) return Promise.reject(new ApiError(i18n.t(header.problem), header.problem === "imagery.tooLarge" ? 413 : 422, { code: header.problem }));
    let hash = 0x811c9dc5;
    for (const byte of bytes) { hash ^= byte; hash = Math.imul(hash, 0x01000193) >>> 0; }
    const asset_id = `img-${hash.toString(16).padStart(8, "0")}${bytes.length.toString(16).padStart(16, "0")}`;
    const record: ImageryAsset = { asset_id, filename, mime: header.mime, width_px: header.width, height_px: header.height, bytes: bytes.length, sha256: "demo", created_at: new Date().toISOString() };
    if (!demoImagery.has(asset_id)) demoImagery.set(asset_id, { record, url: typeof URL.createObjectURL === "function" ? URL.createObjectURL(new Blob([bytes], { type: header.mime })) : "" });
    return wait(record);
  },
  updateUncertaintyAssumptions: (_id: string, ledger: UncertaintyLedger | null) => {
    if (ledger) {
      try { validateDemoLedger(ledger); } catch (e) {
        if (e instanceof DemoPxxError) return Promise.reject(new ApiError(e.message, 422, { code: e.code }));
        throw e;
      }
    }
    commit(state);
    if (ledger) state.view.bundle.uncertainty_assumptions = structuredClone(ledger);
    else delete state.view.bundle.uncertainty_assumptions;
    return wait(state.view);
  },
  reportSnapshot: async (_id: string, runId: string): Promise<VerifiedReportSnapshot> => {
    const view = clone(state.view), run = view.bundle.simulation_runs.find(r => r.simulation_run_id === runId);
    if (!run?.summary_result) throw new ApiError("Run not found", 422, "run_not_found");
    const fingerprint = demoDesignFingerprint(view.bundle);
    if (run.design_fingerprint !== fingerprint) throw new ApiError("earlier_design", 422, "earlier_design");
    view.design_fingerprint = fingerprint; view.bundle.simulation_runs = [run];
    const model = buildResultModel(view, run, {authority:"DEMO_SYNTHETIC",hourlyAcKw:null});
    const pxx = view.bundle.uncertainty_assumptions ? demoAnnualPxx(runId, run.summary_result.annual_energy_wh, view.bundle.uncertainty_assumptions) : null;
    const result = {
      schema:"rawibumi.report_snapshot.v1" as const, identity:{project_id:view.bundle.project.project_id,
        simulation_run_id:runId,name:view.bundle.project.name,package_manifest_sha256:"demo:not_a_verified_package"},
      design_view:view, summary:run.summary_result, site:view.bundle.project.site,
      monthly:{dc_kwp:model.dcKwp,monthly:run.summary_result.monthly_energy,period:{pr:run.summary_result.performance_ratio}},
      hourly_ac:{interval_seconds:3600,values:model.dcKwp === null ? null : demoSeries(model.dcKwp,model.acKw || 1).acAfter},
      annual_pxx:{...(pxx ?? {status:"no_uncertainty_ledger"}),P99:null,P99_reason:pxx?.P99.reason ?? "no_uncertainty_ledger",P99_message:pxx?.P99.message ?? "No uncertainty ledger is supplied. / Ledger ketidakpastian belum diisi."},
      method:{limits:[{code:"DEMO_ONLY",en:"Demo data are illustrative, not a validated simulation.",id:"Data demo bersifat ilustrasi, bukan simulasi tervalidasi."}],
        recorded_assumptions:run.assumptions ?? [],loss_disclosures:[],stc_notices:[]},
      checks:{},provenance:{free_csv_schema:"rawibumi.free_csv.v1"}
    };
    const digest = await crypto.subtle.digest("SHA-256",new TextEncoder().encode(canonicalSerialize(result)));
    return {...result,snapshot_sha256:Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,"0")).join("")};
  },
  annualPxx: (_id: string, runId: string) => {
    const run = state.view.bundle.simulation_runs.find((r) => r.simulation_run_id === runId);
    if (!run) return Promise.reject(new ApiError("run not found in the requested project", 422, { message: "run not found in the requested project" }));
    return wait(demoAnnualPxx(runId, run.summary_result?.annual_energy_wh, state.view.bundle.uncertainty_assumptions));
  },
  updateImagery: (_id: string, config: MapLayerConfiguration | null) => {
    for (const p of config?.providers ?? []) {
      const problem = p.provider_kind === "xyz_raster" ? templateProblem(p.tile_url_template ?? "") : null;
      if (problem) return Promise.reject(new ApiError(i18n.t(problem), 422, { code: problem }));
    }
    for (const l of config?.layers ?? [])
      if (l.layer_type === "orthophoto" && !demoImagery.has(l.imported_asset_id ?? "")) return Promise.reject(new ApiError("The overlay image is not uploaded to this project.", 422, { code: "imagery_asset_not_found" }));
    commit(state);
    if (config) state.view.bundle.imagery = structuredClone(config);
    else delete state.view.bundle.imagery;
    return wait(state.view);
  },
  imageryAssetUrl: (_id: string, assetId: string) => demoImagery.get(assetId)?.url ?? "",
  exportProject: (): Promise<{ filename: string; blob: Blob }> => notInDemo("exportProject"),
  importProject: (): Promise<ProjectView> => notInDemo("importProject"),
  projectBackups: (): Promise<ProjectBackup[]> => notInDemo("projectBackups"),
  restoreBackup: (): Promise<ProjectView> => notInDemo("restoreBackup"),
  updateShadingAccuracy: (_id: string, patch: ShadingAccuracyPatch) => {
    const before = state.view.bundle.shading_accuracy ?? {schema_version: "0.1" as const, defaults_id: "shading_accuracy.v1" as const, overrides: {}};
    const raw: ShadingAccuracySettings = JSON.parse(JSON.stringify(before));
    if ("reset_to_recommended_defaults" in patch) raw.overrides = {};
    else if ("level" in patch.overrides) {
      if (patch.overrides.level == null) delete raw.overrides.level;
      else raw.overrides.level = patch.overrides.level;
    }
    if (JSON.stringify(raw) !== JSON.stringify(before)) state.view.bundle.project.project_revision.revision_number++;
    state.view.bundle.shading_accuracy = raw;
    state.view.resolved_shading_accuracy = demoShadingAccuracy(raw);
    return wait(state.view);
  },
  updateOpticsThermal: (_id: string, patch: OpticsThermalPatch) => {
    const resolved=demoOpticsPatch(state.view.resolved_optics_thermal_settings,patch);
    state.view.bundle.optics_thermal_settings={schema_version:resolved.schema_version,defaults_id:resolved.defaults_id,overrides:resolved.overrides};
    state.view.resolved_optics_thermal_settings=resolved;
    state.view.bundle.project.project_revision.revision_number++;
    return wait(state.view);
  },
  simulationDefaults: () => wait<SimulationDefaults>({ demo: true, shading_accuracy: demoShadingAccuracy(), optics_thermal_settings: demoOpticsDefaults(), albedo: 0.20,
    thermal: { u_c_w_m2k: 20, u_v_w_m2k_per_ms: 0 },
    losses: { module_mismatch_loss_fraction: 0, string_mismatch_loss_fraction: 0, dc_array_resistance_ohm: 0 },
    simulation_timestep_seconds: 3600, module_quality: { source: "pinned_module_definition", fallback_loss_fraction: 0 },
    not_modelled: [], loss_settings: demoLossDefaults() }),
  health: () => wait({ status: "ok", phase: "demo" }),
  catalog: () => wait(catalog),
  previewWeatherFile: async (_projectId: string, _file: File): Promise<never> => { throw new DemoUnavailableError("Importing weather files needs the engine"); },
  importWeatherFile: async (_projectId: string, _file: File, _acceptDistantLocation = false): Promise<never> => { throw new DemoUnavailableError("Importing weather files needs the engine"); },
  weatherSources: () =>
    wait<WeatherSource[]>([
      { provider_id: "demo", source_id: "demo-tmy", label: "Demo TMY (synthetic)", acquisition_type: "tmy", rawibumi_resource_projection_applied: false },
      { provider_id: "demo", source_id: "demo-series", label: "Demo hourly series (synthetic)", acquisition_type: "time_series", rawibumi_resource_projection_applied: false }
    ]),
  projects: () =>
    wait<ProjectSummary[]>(projectDeleted ? [] : [
      { project_id: "demo-project", name: state.view.bundle.project.name, status: "draft", latitude_deg: state.view.bundle.project.site.latitude_deg, longitude_deg: state.view.bundle.project.site.longitude_deg, timezone: state.view.bundle.project.site.timezone }
    ]),
  projectSummary: (_id: string) => projectDeleted ? Promise.reject(new ApiError("Project not found", 404, "Project not found")) : wait(demoSystemSummary(state), 60),
  project: (_id: string) => projectDeleted ? Promise.reject(new ApiError("Project not found", 404, "Project not found")) : wait(state.view),
  createProject: (input: CreateProjectInput) => {
    projectDeleted = false;
    state = initialState(input);
    persistDemoReportSite(state.view);
    return wait(state.view);
  },
  setWorkspaceMode: (_id: string, mode: WorkspaceMode) => {
    state.view.bundle.site_workspace_bootstrap.workspace_context.mode = mode;
    return wait(state.view);
  },
  addSurface: (_id: string, input: { name: string; origin_x_m: number; origin_y_m: number; width_m: number; height_m: number; base_elevation_m: number; surface_type: string }) => {
    commit(state);
    const id = nid("srf");
    state.rects[id] = { x: input.origin_x_m, y: input.origin_y_m, w: input.width_m, h: input.height_m };
    state.view.bundle.scene.surfaces.push({ surface_id: id, name: input.name, surface_type: input.surface_type, base_elevation_m: input.base_elevation_m });
    rebuildFeatures(state);
    return wait(state.view);
  },
  sceneCommand: async <O extends SceneConflictOptions = SceneConflictOptions>(_id: string, command: SceneCommandInput, options?: O): Promise<SceneResult<O>> => {
    const draft = sceneDraft();
    const b = draft.view.bundle;
    const ids = command.target_entity_ids;
    const kind = command.command_type;
    const parameters = command.parameters;
    if (kind === "group" || kind === "ungroup") {
      const surfaces = ids.map(id => b.scene.surfaces.find(s => s.surface_id === id));
      if (!ids.length || surfaces.some(s => !s)) throw new Error("buildings may group surfaces only");
      if (kind === "group") {
        const id = parameters.group_id;
        const name = parameters.name;
        if (typeof id !== "string" || !id.trim()) throw new Error("group_id must not be empty");
        if (name !== undefined && (typeof name !== "string" || !name.trim() || name.length > 80)) throw new Error("building name must contain 1 to 80 characters");
        const existing = b.scene.buildings?.find(g => g.building_id === id);
        if (!existing && name === undefined) throw new Error("a new building requires a name");
        if (existing && typeof name === "string") existing.name = name.trim();
        if (!existing) (b.scene.buildings ??= []).push({ building_id: id, name: (name as string).trim() });
        surfaces.forEach(s => { s!.group_id = id; });
      } else surfaces.forEach(s => { s!.group_id = null; });
      if (b.scene.buildings) b.scene.buildings = b.scene.buildings.filter(g => b.scene.surfaces.some(s => s.group_id === g.building_id));
      return await finishSceneDraft(draft, undefined, options ?? {}) as SceneResult<O>;
    }
    if (kind === "set_reference_anchor") {
      if (ids.length !== 1) throw new Error("set_reference_anchor requires one target");
      const entity = b.scene.surfaces.find(s => s.surface_id === ids[0]) ?? b.scene.obstacles.find(o => o.obstacle_id === ids[0]);
      if (!entity || entity.locked || ("obstacle_type" in entity && entity.obstacle_type === "imported_mesh")) throw new Error("Reference anchor target is not editable");
      const { u, v } = parameters;
      if (!["start", "center", "end"].includes(String(u)) || !["start", "center", "end"].includes(String(v)) || Object.keys(parameters).some(k => !["u", "v"].includes(k))) throw new Error("Invalid reference anchor");
      entity.reference_anchor = { u, v } as import("../types").ReferenceAnchor;
      return await finishSceneDraft(draft, undefined, options ?? {}) as SceneResult<O>;
    }
    // A copy leaves its source and the source's fields untouched (UX2).
    const dependent = !["edit_elevation", "edit_plane", "copy"].includes(kind) ? b.scene.pv_fields.filter((field) => ids.includes(field.support_surface_id)) : [];
    for (const id of ids) {
      if (!b.scene.surfaces.some((s) => s.surface_id === id) && !b.scene.obstacles.some((o) => o.obstacle_id === id)) throw new Error(`Unknown scene entity ${id}`);
      const fields = b.scene.pv_fields.filter((f) => f.support_surface_id === id);
      if (fields.length && !["edit_elevation", "edit_plane", "copy"].includes(kind) && options?.dependent_fields !== "apply") throw new Error(`support surface is already used by PV fields ${fields.map((f) => f.pv_field_id).join(", ")}; delete the fields first`);
    }
    let obstacleId: string | undefined;
    let keepoutId: string | undefined;
    if (kind === "draw_polygon") {
      const id = nid("srf");
      setDemoGeometry(draft, id, parameters.vertices as Vec2[]);
      b.scene.surfaces.push({ surface_id: id, name: String(parameters.name), surface_type: String(parameters.surface_type), base_elevation_m: Number(parameters.base_elevation_m ?? 0) });
      if (["exclusion_area", "walkway"].includes(String(parameters.surface_type))) keepoutId = id;
    } else if (kind === "copy") {
      if (ids.length !== 1) throw new Error("target_entity_ids has invalid count for copy");
      const dx = Number(parameters.dx_m), dy = Number(parameters.dy_m);
      if (!Number.isFinite(dx) || !Number.isFinite(dy)) throw new Error("dx_m and dy_m must be finite");
      const source = ids[0];
      const surface = b.scene.surfaces.find((s) => s.surface_id === source), obstacle = b.scene.obstacles.find((o) => o.obstacle_id === source);
      if (obstacle?.obstacle_type === "imported_mesh") throw new Error(`mesh ${source}: read-only; use whole-mesh replacement or delete`);
      const id = nid(surface ? "srf" : "obs");
      const shift = (ring: Vec2[]) => ring.map(([x, y]) => [x + dx, y + dy] as Vec2);
      setDemoGeometry(draft, id, shift(rectPoly(draft.rects[source])));
      if (surface) {
        const clone = { ...structuredClone(surface), surface_id: id, name: `${surface.name} copy` };
        clone.group_id = null;
        if (clone.boundary_2d) clone.boundary_2d = { ...clone.boundary_2d, vertices: shift(clone.boundary_2d.vertices), holes: clone.boundary_2d.holes.map(shift) };
        b.scene.surfaces.push(clone);
        if (["exclusion_area", "walkway"].includes(surface.surface_type)) keepoutId = id;
        // UX3 paste with PV: the roof's fields and modules, shifted; strings are never copied (illustrative demo).
        if (parameters.with_pv === true) for (const field of b.scene.pv_fields.filter((f) => f.support_surface_id === source)) {
          const fieldId = nid("fld");
          b.scene.pv_fields.push({ ...structuredClone(field), pv_field_id: fieldId, support_surface_id: id, name: `${field.name} copy` });
          for (const module of b.scene.module_instances.filter((m) => m.pv_field_id === field.pv_field_id)) {
            const moduleId = nid("m"), r = draft.rects[module.module_instance_id];
            if (r) draft.rects[moduleId] = { ...r, x: r.x + dx, y: r.y + dy, vertices: r.vertices && shift(r.vertices) };
            b.scene.module_instances.push({ ...structuredClone(module), module_instance_id: moduleId, pv_field_id: fieldId });
          }
        }
      } else {
        b.scene.obstacles.push({ ...structuredClone(obstacle!), obstacle_id: id, name: `${obstacle!.name} copy` });
        obstacleId = id;
      }
    } else for (const id of ids) {
      const obstacle = b.scene.obstacles.find((o) => o.obstacle_id === id);
      if (obstacle && kind !== "delete") obstacleId = id;
      if (kind !== "delete" && b.scene.surfaces.some((surface) => surface.surface_id === id && ["exclusion_area", "walkway"].includes(surface.surface_type))) keepoutId = id;
      const surface = b.scene.surfaces.find(s => s.surface_id === id);
      const ring = Number(parameters.ring ?? 0);
      const outer = rectPoly(draft.rects[id]);
      const polygon = ring ? surface?.boundary_2d?.holes[ring - 1] : outer;
      if (!polygon) throw new Error("ring is outside geometry");
      const setRing = (vertices: Vec2[]) => {
        if (ring) {
          const issues = validatePolygon(vertices); if (issues.length) throw new Error(issues[0].message);
          surface!.boundary_2d!.holes[ring - 1] = vertices;
        } else setDemoGeometry(draft, id, vertices);
      };
      if (kind === "edit_plane") {
        if (!surface) throw new Error("edit_plane requires a surface");
        const slope = Number(parameters.slope_deg), azimuth = Number(parameters.azimuth_deg);
        if (!Number.isFinite(slope) || slope < 0 || slope >= 90 || !Number.isFinite(azimuth) || azimuth < 0 || azimuth >= 360) throw new Error("Invalid plane slope or azimuth");
        const before = moduleObstacleConflicts(draft);
        surface.slope_deg = slope; surface.azimuth_deg = azimuth; surface.base_elevation_m = Number(parameters.base_elevation_m);
        surface.elevation_reference = parameters.elevation_reference as typeof surface.elevation_reference;
        const conflicts = moduleObstacleConflicts(draft).filter(c => !before.some(p => p.module_instance_id === c.module_instance_id && p.other_id === c.other_id));
        if (conflicts.length) throw new ApiError("Plane change creates module–obstacle overlaps.", 422, { message: "Plane change creates module–obstacle overlaps.", conflicts });
      } else if (kind === "add_hole") {
        if (!surface) throw new Error("add_hole requires a surface");
        const vertices = parameters.vertices as Vec2[];
        const issues = validatePolygon(vertices); if (issues.length) throw new Error(issues[0].message);
        if (!vertices.every(p => pointInPolygon(p, outer))) throw new Error("A hole must lie strictly inside its surface");
        surface.boundary_2d = { vertices: outer, holes: [...(surface.boundary_2d?.holes ?? []), vertices] };
      } else if (kind === "remove_hole") {
        const index = Number(parameters.hole_index);
        if (!surface?.boundary_2d?.holes[index]) throw new Error("hole_index is outside geometry");
        surface.boundary_2d.holes.splice(index, 1);
      } else if (kind === "scale") {
        const factor = Number(parameters.factor), box = bounds([polygon]);
        if (!Number.isFinite(factor) || factor <= 0 || factor > 100) throw new Error("factor must be within (0, 100]");
        setDemoGeometry(draft, id, scalePoly(polygon, parameters.origin as Vec2 ?? [(box.minX + box.maxX) / 2, (box.minY + box.maxY) / 2], factor));
              if (surface?.boundary_2d) surface.boundary_2d.holes = surface.boundary_2d.holes.map(hole => scalePoly(hole, parameters.origin as Vec2 ?? [(box.minX + box.maxX) / 2, (box.minY + box.maxY) / 2], factor));
      } else if (kind === "rotate") {
        const box = bounds([polygon]);
        setDemoGeometry(draft, id, rotateClockwise(polygon, parameters.origin as Vec2 ?? [(box.minX + box.maxX) / 2, (box.minY + box.maxY) / 2], Number(parameters.angle_deg)));
              if (surface?.boundary_2d) surface.boundary_2d.holes = surface.boundary_2d.holes.map(hole => rotateClockwise(hole, parameters.origin as Vec2 ?? [(box.minX + box.maxX) / 2, (box.minY + box.maxY) / 2], Number(parameters.angle_deg)));
      } else if (kind === "insert_vertex") {
        const index = Number(parameters.edge_index);
        if (!Number.isInteger(index) || index < 0 || index >= polygon.length) throw new Error("edge_index is outside geometry");
        setRing( [...polygon.slice(0, index + 1), [Number(parameters.x_m), Number(parameters.y_m)], ...polygon.slice(index + 1)]);
      } else if (kind === "delete_vertex") {
        const index = Number(parameters.vertex_index);
        if (polygon.length <= 3) throw new Error("geometry must keep at least 3 vertices");
        if (!Number.isInteger(index) || index < 0 || index >= polygon.length) throw new Error("vertex_index is outside geometry");
        setRing( polygon.filter((_, i) => i !== index));
      } else if (kind === "move_edge") {
        const index = Number(parameters.edge_index), next = (index + 1) % polygon.length;
        if (!Number.isInteger(index) || index < 0 || index >= polygon.length) throw new Error("edge_index is outside geometry");
        setRing( polygon.map(([x, y], i) => i === index || i === next ? [x + Number(parameters.dx_m), y + Number(parameters.dy_m)] : [x, y]));
      } else if (kind === "edit_height") {
        const height = Number(parameters.height_m);
        if (!obstacle || !Number.isFinite(height) || height < 0 || height > 1000) throw new Error("edit_height requires an obstacle and a height within [0, 1000]");
        obstacle.height_m = height;
      } else if (kind === "move_vertex") {
        const index = Number(parameters.vertex_index);
        if (!Number.isInteger(index) || index < 0 || index >= polygon.length) throw new Error("vertex_index is outside geometry");
        setRing( polygon.map((p, i) => i === index ? [Number(parameters.target_x_m), Number(parameters.target_y_m)] : p));
      } else if (kind === "edit_exact_dimension") {
        setDemoGeometry(draft, id, parameters.preserve === "rectangle"
          ? anchoredRectangle(polygon, Number(parameters.edge_index), Number(parameters.length_m), (surface ?? obstacle)?.reference_anchor)
          : setEdgeLength(polygon, Number(parameters.edge_index), Number(parameters.length_m), (parameters.preserve ?? "start") as Preserve));
      } else if (kind === "edit_exact_angle") {
        const index = Number(parameters.edge_index), next = (index + 1) % polygon.length;
        if (!Number.isInteger(index) || !polygon[index]) throw new Error("edge_index is outside geometry");
        const length = Math.hypot(polygon[next][0] - polygon[index][0], polygon[next][1] - polygon[index][1]);
        const angle = Number(parameters.azimuth_deg) * Math.PI / 180;
        setDemoGeometry(draft, id, polygon.map((point, i) => i === next ? [polygon[index][0] + length * Math.sin(angle), polygon[index][1] + length * Math.cos(angle)] : point));
      } else if (kind === "move") {
        setDemoGeometry(draft, id, polygon.map(([x, y]) => [x + Number(parameters.dx_m), y + Number(parameters.dy_m)]));
              if (surface?.boundary_2d) surface.boundary_2d.holes = surface.boundary_2d.holes.map(hole => hole.map(([x,y]) => [x + Number(parameters.dx_m), y + Number(parameters.dy_m)] as Vec2));
      } else if (kind === "edit_elevation") {
        const entity = obstacle ?? b.scene.surfaces.find((s) => s.surface_id === id)!;
        const before = moduleObstacleConflicts(draft);
        entity.base_elevation_m = Number(parameters.base_elevation_m);
        if (!obstacle) {
          const conflicts = moduleObstacleConflicts(draft).filter((c) => !before.some((p) => p.module_instance_id === c.module_instance_id && p.other_id === c.other_id));
          if (conflicts.length) throw new ApiError("Elevation change creates module–obstacle overlaps.", 422, { message: "Elevation change creates module–obstacle overlaps.", conflicts });
        }
      } else if (kind === "delete") {
        b.scene.surfaces = b.scene.surfaces.filter((s) => s.surface_id !== id);
        b.scene.obstacles = b.scene.obstacles.filter((o) => o.obstacle_id !== id);
        delete draft.rects[id];
      } else throw new Error(`Demo scene command ${kind} is unavailable`);
    }
    if (dependent.length && options?.dependent_fields === "apply") return await finishDependentDemo(draft, dependent, kind === "delete" ? "delete" : "refill", options) as SceneResult<O>;
    return await finishSceneDraft(draft, obstacleId, options ?? {}, keepoutId) as SceneResult<O>;
  },
  moveSceneEntity: async <O extends SceneConflictOptions = SceneConflictOptions>(id: string, input: { entity_id: string; dx_m: number; dy_m: number }, options?: O): Promise<SceneResult<O>> =>
    mockApi.sceneCommand(id, { command_type: "move", target_entity_ids: [input.entity_id], parameters: { dx_m: input.dx_m, dy_m: input.dy_m } }, options),
  addPolygonObstacle: async <O extends SceneConflictOptions = SceneConflictOptions>(_id: string, input: PolygonObstacleInput, options?: O): Promise<SceneResult<O>> => {
    const draft = sceneDraft();
    const id = nid("obs");
    setDemoGeometry(draft, id, input.vertices);
    draft.view.bundle.scene.obstacles.push({ obstacle_id: id, name: input.name, obstacle_type: "extruded_polygon", base_elevation_m: input.base_elevation_m, height_m: input.height_m });
    return await finishSceneDraft(draft, id, options ?? {}) as SceneResult<O>;
  },
  addObstacle: async <O extends SceneConflictOptions = SceneConflictOptions>(id: string, input: { name: string; origin_x_m: number; origin_y_m: number; width_m: number; depth_m: number; base_elevation_m: number; height_m: number }, options?: O): Promise<SceneResult<O>> => {
    const draft = sceneDraft();
    const obstacleId = nid("obs");
    draft.rects[obstacleId] = { x: input.origin_x_m, y: input.origin_y_m, w: input.width_m, h: input.depth_m };
    draft.view.bundle.scene.obstacles.push({ obstacle_id: obstacleId, name: input.name, obstacle_type: "box", base_elevation_m: input.base_elevation_m, height_m: input.height_m });
    return await finishSceneDraft(draft, obstacleId, options ?? {}) as SceneResult<O>;
  },
  moduleCommands: async <I extends ModuleCommandInput>(_id: string, input: I): Promise<ModuleCommandResult<I>> => {
    const ids = input.module_instance_ids;
    const refuse = (message: string, detail: unknown = { message }): never => { throw new ApiError(message, 422, detail); };
    if (!Array.isArray(ids) || !ids.length || ids.length > 10000 || ids.some((id) => typeof id !== "string") || new Set(ids).size !== ids.length)
      refuse("module_instance_ids must contain 1 to 10000 unique ids");
    if (Object.keys(input).some((key) => !["command", "module_instance_ids", "dx_m", "dy_m", "discard_dependent_strings", "dry_run", "on_conflict"].includes(key))) refuse("Extra module-command keys are forbidden");
    if (!["move_modules", "delete_modules"].includes(input.command)) refuse("Unsupported module command");
    if (input.command === "delete_modules" && ("dx_m" in input || "dy_m" in input)) refuse("dx_m and dy_m are forbidden for delete_modules");
    if (input.command === "move_modules" && [input.dx_m, input.dy_m].some((v) => typeof v !== "number" || !Number.isFinite(v) || Math.abs(v) > 10000)) refuse("move_modules requires finite dx_m and dy_m within ±10000 m");
    if (input.command === "move_modules" && input.on_conflict === "fill") throw new DemoUnavailableError("Drop-to-fill needs the engine");
    if (input.command === "move_modules" && input.on_conflict !== undefined && input.on_conflict !== "reject") refuse("on_conflict must be reject or fill");
    const draft = sceneDraft(), scene = draft.view.bundle.scene, wanted = new Set(ids);
    const unknown = ids.filter((id) => !scene.module_instances.some((m) => m.module_instance_id === id));
    if (unknown.length) refuse(`module instances not found: ${unknown.sort().join(", ")}`);
    if (ids.some((id) => !draft.rects[id])) throw new DemoUnavailableError("moduleCommands on table modules; use the existing table controls");
    const fields = scene.pv_fields.filter((field) => scene.module_instances.some((m) => m.pv_field_id === field.pv_field_id && wanted.has(m.module_instance_id)));
    let strings: string[] = [];
    if (input.command === "delete_modules") {
      const impact = fields.map((field) => {
        const own = scene.module_instances.filter((m) => m.pv_field_id === field.pv_field_id);
        const removed = new Set(own.filter((m) => wanted.has(m.module_instance_id)).map((m) => m.module_instance_id));
        const power = catalog.modules.find((m) => m.revision_id === field.module_definition_revision_id)!.pmp_w;
        const affected = draft.view.bundle.electrical_design.strings.filter((s) => s.module_instance_ids.some((id) => removed.has(id))).map((s) => s.string_id).sort();
        return { pv_field_id: field.pv_field_id, name: field.name, module_count_before: own.length,
          module_count_after: own.length - removed.size, stc_power_w_before: own.length * power,
          stc_power_w_after: (own.length - removed.size) * power, string_ids: affected, field_becomes_empty: own.length === removed.size };
      });
      strings = [...new Set(impact.flatMap((f) => f.string_ids))].sort();
      const preview: ModuleDeletePreview = { dry_run: true, command: "delete_modules", module_count: ids.length, fields: impact,
        string_ids: strings, requires_discard_dependent_strings: strings.length > 0 };
      if (input.dry_run) return await wait(preview) as ModuleCommandResult<I>;
      if (strings.length && !input.discard_dependent_strings) refuse(`Delete requires discard_dependent_strings=true for string_ids: ${strings.join(", ")}.`, { message: "Delete requires discard_dependent_strings=true.", dependent_fields: impact });
      scene.module_instances = scene.module_instances.filter((m) => !wanted.has(m.module_instance_id));
      for (const id of ids) delete draft.rects[id];
    } else {
      for (const id of ids) {
        const rect = draft.rects[id]; rect.x += input.dx_m; rect.y += input.dy_m;
        if (rect.vertices) rect.vertices = translatePoly(rect.vertices, [input.dx_m, input.dy_m]);
      }
      const conflicts: ModuleMovePreview["conflicts"] = [];
      const all = [
        ...scene.module_instances.filter((m) => draft.rects[m.module_instance_id]).map((m) => ({ id: m.module_instance_id, polygon: rectPoly(draft.rects[m.module_instance_id]) })),
        ...draft.tables.flatMap((t) => tableModules(t).map((m) => ({ id: m.id, polygon: m.polygon })))
      ];
      for (const id of ids) {
        const m = scene.module_instances.find((m) => m.module_instance_id === id)!, field = fields.find((f) => f.pv_field_id === m.pv_field_id)!;
        const support = scene.surfaces.find((s) => s.surface_id === field.support_surface_id)!, ring = rectPoly(draft.rects[support.surface_id]);
        const polygon = rectPoly(draft.rects[id]), setback = field.setback_configuration?.perimeter_setback_m ?? 0;
        const record = (code: string, other_id: string) => conflicts.push({ code, other_id, module_instance_id: id, pv_field_id: field.pv_field_id });
        const boundaryDistance = (p: Vec2) => Math.min(...ring.map((a, i) => distToSegment(p, a, ring[(i + 1) % ring.length])));
        if (polygon.some((p) => (!pointInPolygon(p, ring) && boundaryDistance(p) > 1e-9) || boundaryDistance(p) < setback - 1e-9)) record("module_outside_support_or_setback", support.surface_id);
        for (const hole of support.boundary_2d?.holes ?? []) if (polygonDistance(polygon, hole) <= 1e-9 || polygonDistance(polygon, hole) < setback - 1e-9) record("module_over_hole", support.surface_id);
        for (const other of all) if (other.id !== id && polygonDistance(shrink(polygon), shrink(other.polygon)) === 0) record("module_module_overlap", other.id);
        for (const obstacle of scene.obstacles) {
          const distance = polygonDistance(polygon, rectPoly(draft.rects[obstacle.obstacle_id]));
          if (distance <= 1e-9) record("module_obstacle_overlap", obstacle.obstacle_id);
          else if (distance < (field.setback_configuration?.obstacle_setback_m ?? 0) - 1e-9) record("module_obstacle_setback", obstacle.obstacle_id);
        }
        for (const surface of scene.surfaces) if (demoKeepoutSelected(draft, field, surface.surface_id) && polygonDistance(polygon, rectPoly(draft.rects[surface.surface_id])) <= 1e-9) record("module_exclusion_overlap", surface.surface_id);
      }
      const grouped = new Map<string, { code: string; name?: string; setback?: number; members: Set<string> }>();
      for (const c of conflicts) {
        const field = fields.find((f) => f.pv_field_id === c.pv_field_id)!;
        const entity = scene.obstacles.find((o) => o.obstacle_id === c.other_id) ?? scene.surfaces.find((s) => s.surface_id === c.other_id);
        const name = entity?.name ?? c.other_id ?? "";
        const setback = c.code === "module_obstacle_setback" ? field.setback_configuration?.obstacle_setback_m ?? 0
          : c.code === "module_outside_support_or_setback" ? field.setback_configuration?.perimeter_setback_m ?? 0 : undefined;
        const key = c.code === "module_module_overlap" ? c.code : `${c.code}:${name}:${setback}`;
        const group = grouped.get(key) ?? { code: c.code, name, setback, members: new Set<string>() };
        if (c.module_instance_id && wanted.has(c.module_instance_id)) group.members.add(c.module_instance_id);
        if (c.other_id && wanted.has(c.other_id)) group.members.add(c.other_id);
        grouped.set(key, group);
      }
      const reasons = [...grouped.values()].map(({ code, name, setback, members }) => {
        const count = members.size, subject = `${count} module${count === 1 ? "" : "s"} would `;
        const action: Record<string, string> = {
          module_module_overlap: "overlap other modules", module_obstacle_overlap: `overlap obstacle ${name}`,
          module_obstacle_setback: `be closer than ${setback} m to obstacle ${name}`,
          module_outside_support_or_setback: `leave roof ${name} or its ${setback} m edge setback`,
          module_over_hole: `cover a hole in ${name}`, module_exclusion_overlap: `enter keep-out ${name}`
        };
        return { code, count, name, setback, message: action[code] ? subject + action[code] : code };
      });
      if (input.dry_run) return await wait({ dry_run: true, command: "move_modules", moved_count: ids.length, conflicts, reasons } satisfies ModuleMovePreview) as ModuleCommandResult<I>;
      if (conflicts.length) refuse("Module move refused because it creates layout conflicts.", { message: "Module move refused because it creates layout conflicts.", conflicts, reasons });
    }
    for (const field of fields) Object.assign(field, { layout_status: "manual", layout_source: "generated_then_edited", packing_input_hash: null, metadata: { row_layouts_status: "generated_lineage_only" } });
    return await commitFieldDraft(draft, strings) as ModuleCommandResult<I>;
  },
  createPvField: (_id: string, input: { name: string; support_surface_id: string; module_definition_revision_id: string; orientation: string; azimuth_deg: number; tilt_deg: number; module_gap_x_m: number; module_gap_y_m: number; row_pitch_m: number; mounting_height_m: number; perimeter_setback_m: number; obstacle_setback_m: number }) => {
    commit(state);
    const id = nid("fld");
    state.view.bundle.scene.pv_fields.push({ ...input, pv_field_id: id, row_count: 0, modules_per_row: 0,
      setback_configuration: { perimeter_setback_m: input.perimeter_setback_m, obstacle_setback_m: input.obstacle_setback_m } });
    fill(state, id, input.support_surface_id, input);
    rebuildFeatures(state);
    return wait(state.view, 300);
  },
  previewPvFieldUpdate: async (_id: string, fieldId: string, changes: PvFieldChanges) =>
    wait(refillDraft(fieldId, changes).preview),
  updatePvField: async (_id: string, fieldId: string, changes: PvFieldChanges, options: PvFieldOptions = {}) => {
    const { draft, preview } = refillDraft(fieldId, changes);
    if (preview.requires_discard_manual_layout && !options.discard_manual_layout)
      throw new ApiError("Re-fill requires discard_manual_layout=true.", 422, "Re-fill requires discard_manual_layout=true.");
    if (preview.requires_discard_dependent_strings && !options.discard_dependent_strings) {
      const message = `Re-fill requires discard_dependent_strings=true for string_ids: [${preview.string_ids.map((id) => `'${id}'`).join(", ")}].`;
      throw new ApiError(message, 422, message);
    }
    return commitFieldDraft(draft, preview.string_ids);
  },
  previewPvFieldDelete: async (_id: string, fieldId: string) => wait(fieldImpact(fieldId)),
  deletePvField: async (_id: string, fieldId: string, options: Pick<PvFieldOptions, "discard_dependent_strings"> = {}) => {
    const preview = fieldImpact(fieldId);
    if (preview.requires_discard_dependent_strings && !options.discard_dependent_strings) {
      const message = `Delete requires discard_dependent_strings=true for string_ids: [${preview.string_ids.map((id) => `'${id}'`).join(", ")}].`;
      throw new ApiError(message, 422, message);
    }
    const draft: State = { ...clone({ view: state.view, rects: state.rects, tables: state.tables, requests: state.requests }), undo: [], redo: [] };
    for (const m of draft.view.bundle.scene.module_instances.filter((m) => m.pv_field_id === fieldId)) delete draft.rects[m.module_instance_id];
    draft.view.bundle.scene.module_instances = draft.view.bundle.scene.module_instances.filter((m) => m.pv_field_id !== fieldId);
    draft.view.bundle.scene.pv_fields = draft.view.bundle.scene.pv_fields.filter((f) => f.pv_field_id !== fieldId);
    draft.tables = draft.tables.filter((t) => t.pv_field_id !== fieldId);
    delete draft.requests[fieldId];
    return commitFieldDraft(draft, preview.string_ids);
  },
  previewFill: (_id: string, request: FillZoneRequest) => {
    try {
      const fieldId = request.pv_field_id ?? "new-field";
      const before = request.pv_field_id ? state.tables.filter((t) => t.pv_field_id === fieldId) : [];
      return wait(previewOf(fillInput(state, request, fieldId), before, state.view.bundle.electrical_design.strings), 60);
    } catch (err) {
      return Promise.reject(err);
    }
  },
  applyFill: (_id: string, request: FillZoneRequest, _legacy: LegacyFieldInput | null) => {
    const b = state.view.bundle;
    const existing = request.pv_field_id ? b.scene.pv_fields.find((f) => f.pv_field_id === request.pv_field_id) : null;
    if (request.pv_field_id && !existing) return Promise.reject(new Error(`Unknown PV field ${request.pv_field_id}`));
    if (existing && existing.support_surface_id !== request.support_surface_id) return Promise.reject(new Error("A re-fill keeps the field's support surface."));
    const fieldId = existing?.pv_field_id ?? nid("fld");
    let res;
    try {
      res = fillZone(fillInput(state, request, fieldId));
    } catch (err) {
      return Promise.reject(err);
    }
    const blocking = res.findings.find((f) => f.severity === "blocking");
    if (blocking) return Promise.reject(new Error(blocking.message));
    if (!moduleCountOf(res.tables)) return Promise.reject(new Error("The fill produced no modules; adjust the setbacks, pitch or module (fail-closed)."));
    commit(state);
    if (!existing)
      b.scene.pv_fields.push({ pv_field_id: fieldId, name: request.name, support_surface_id: request.support_surface_id, module_definition_revision_id: request.module_definition_revision_id, row_count: 0, modules_per_row: 0, orientation: request.orientation, azimuth_deg: request.azimuth_deg, tilt_deg: request.tilt_deg });
    else Object.assign(existing, { name: request.name, module_definition_revision_id: request.module_definition_revision_id, orientation: request.orientation, azimuth_deg: request.azimuth_deg, tilt_deg: request.tilt_deg });
    state.tables = [...state.tables.filter((t) => t.pv_field_id !== fieldId), ...res.tables];
    state.requests[fieldId] = { ...request, pv_field_id: fieldId };
    rebuildFeatures(state);
    return wait(state.view, 200);
  },
  editTables: (_id: string, pvFieldId: string, command: TableEditCommand) => {
    const snap = structuredClone({ view: state.view, rects: state.rects, tables: state.tables, requests: state.requests });
    try {
      editTables(state, pvFieldId, command);
    } catch (err) {
      restore(state, snap);
      return Promise.reject(err);
    }
    state.undo.push(snap);
    state.redo = [];
    rebuildFeatures(state);
    return wait(state.view);
  },
  undo: (_id: string) => {
    const snap = state.undo.pop();
    if (!snap) return Promise.reject(new Error("Nothing to undo in the engine session."));
    state.redo.push(structuredClone({ view: state.view, rects: state.rects, tables: state.tables, requests: state.requests }));
    restore(state, snap);
    return wait(state.view, 60);
  },
  redo: (_id: string) => {
    const snap = state.redo.pop();
    if (!snap) return Promise.reject(new Error("Nothing to redo in the engine session."));
    state.undo.push(structuredClone({ view: state.view, rects: state.rects, tables: state.tables, requests: state.requests }));
    restore(state, snap);
    return wait(state.view, 60);
  },
  addInverter: (_id: string, input: { inverter_definition_revision_id: string; name: string }) => {
    commit(state);
    const def = catalog.inverters.find((i) => i.revision_id === input.inverter_definition_revision_id);
    const id = nid("inv");
    state.view.bundle.electrical_design.inverter_instances.push({
      inverter_instance_id: id,
      inverter_definition_revision_id: input.inverter_definition_revision_id,
      name: input.name,
      enabled: true,
      mppt_instance_ids: Array.from({ length: def?.mppt_count ?? 1 }, (_, i) => `${id}-mppt-${i + 1}`)
    });
    rebuildTopology(state);
    return wait(state.view);
  },
  removeInverter: (_id: string, inverterId: string) => {
    const e = state.view.bundle.electrical_design;
    const inv = e.inverter_instances.find((i) => i.inverter_instance_id === inverterId);
    if (!inv) return Promise.reject(new Error(`inverter not found: ${inverterId}`));
    commit(state);
    const released = e.strings.filter((s) => s.target_mppt_instance_id && inv.mppt_instance_ids.includes(s.target_mppt_instance_id));
    for (const s of released) { s.target_mppt_instance_id = null; s.enabled = false; }
    e.inverter_instances = e.inverter_instances.filter((i) => i !== inv);
    rebuildTopology(state);
    return wait({ ...state.view, command_results: [{ inverter_instance_id: inverterId, unassigned_string_ids: released.map((s) => s.string_id) }] });
  },
  changeInverter: (_id: string, inverterId: string, revisionId: string) => {
    const e = state.view.bundle.electrical_design;
    const inv = e.inverter_instances.find((i) => i.inverter_instance_id === inverterId);
    const def = catalog.inverters.find((i) => i.revision_id === revisionId);
    if (!inv || !def) return Promise.reject(new Error(`inverter or revision not found: ${inverterId}, ${revisionId}`));
    commit(state);
    const dropped = inv.mppt_instance_ids.slice(def.mppt_count);
    const released = e.strings.filter((s) => s.target_mppt_instance_id && dropped.includes(s.target_mppt_instance_id));
    for (const s of released) { s.target_mppt_instance_id = null; s.enabled = false; }
    inv.mppt_instance_ids = Array.from({ length: def.mppt_count }, (_, i) => inv.mppt_instance_ids[i] ?? `${inverterId}-mppt-${i + 1}`);
    inv.inverter_definition_revision_id = revisionId;
    rebuildTopology(state);
    const kept = e.strings.filter((s) => s.target_mppt_instance_id && inv.mppt_instance_ids.includes(s.target_mppt_instance_id)).map((s) => s.string_id);
    return wait({ ...state.view, command_results: [{ inverter_instance_id: inverterId, inverter_definition_revision_id: revisionId, kept_string_ids: kept, unassigned_string_ids: released.map((s) => s.string_id) }] });
  },
  applyLayoutReplacing: (_id: string, inverterId: string, layout: number[][], pvFieldIds: string[], replaceStringIds: string[], sources?: (string[] | null)[] | null) => {
    // One undo step for the whole restring: the snapshot before the deletion replaces the one the layout records.
    const before = structuredClone({ view: state.view, rects: state.rects, tables: state.tables, requests: state.requests });
    const e = state.view.bundle.electrical_design;
    e.strings = e.strings.filter((s) => !replaceStringIds.includes(s.string_id));
    rebuildTopology(state);
    return runTopology(state, { command_type: "apply_mppt_layout", parameters: { inverter_instance_id: inverterId, layout, pv_field_ids: pvFieldIds, ...(replaceStringIds.length ? {} : { release_modules: true }), ...(sources === undefined ? {} : { sources }) } } as TopologyCommand)
      .then((view) => { state.undo[state.undo.length - 1] = before; return view; })
      .catch((err) => { restore(state, before); throw err; });
  },
  inverterSizing: (_id: string, inverterId: string) => {
    const b = state.view.bundle, inv = b.electrical_design.inverter_instances.find(i => i.inverter_instance_id === inverterId);
    if (!inv) return Promise.reject(new Error(`inverter not found: ${inverterId}`));
    const pv_field_ids = inv.paired_pv_field_ids?.length ? inv.paired_pv_field_ids : b.scene.pv_fields.map(f => f.pv_field_id);
    const modules = b.scene.module_instances.filter(m => pv_field_ids.includes(m.pv_field_id));
    const revisionOf = (m: typeof modules[number]) => m.module_definition_revision_id ?? modulePlacement(state.view, m.module_instance_id)?.revisionId ?? "";
    const area_kwp = modules.reduce((sum, m) => { const d = state.view.catalog.modules.find(d => d.revision_id === revisionOf(m))!; return sum + (d.nominal_power_w ?? d.pmp_w) / 1000; }, 0);
    const def = state.view.catalog.inverters.find(d => d.revision_id === inv.inverter_definition_revision_id)!;
    const ac_kw = def.nominal_ac_power_w / 1000;
    const overview = demoSystemsOverview(state.view, state.rects);
    const included = new Set(overview.buildings.flatMap((g, i) => g.pv_field_ids.some(id => pv_field_ids.includes(id)) ? [i] : []));
    const elec = DEMO_INVERTER_ELECTRICAL[inv.inverter_definition_revision_id];
    const revisions = [...new Set(modules.map(revisionOf))];
    const mod = revisions.length === 1 ? DEMO_MODULE_ELECTRICAL[revisions[0]!] : undefined;
    const lengths = mod ? demoStringLengths(revisions[0]!, inv.inverter_definition_revision_id, modules.length) : [];
    return wait<InverterSizing>({ schema_name: "InverterSizing", schema_version: "0.1", pv_field_ids, module_count: modules.length, area_kwp, ac_kw,
      dc_ac_ratio: ac_kw > 0 ? area_kwp / ac_kw : null, string_length_min: lengths.length ? Math.min(...lengths) : null, string_length_max: lengths.length ? Math.max(...lengths) : null,
      reasons: lengths.length ? [] : [{ code: "DEMO_SIZING_UNAVAILABLE", message: "Demo sizing needs one supported module type and enough modules." }],
      mppt_count: inv.mppt_instance_ids.length, mppts: inv.mppt_instance_ids.map((_, i) => ({ index: i + 1, inputs: elec?.inputs ?? null, inputs_source: elec ? "definition" : null, max_strings_by_isc: null })),
      distance_warnings: overview.distances.filter(d => d.over_threshold && included.has(d.from_index) && included.has(d.to_index)).map(d => ({...d, from_name: overview.buildings[d.from_index].name, to_name: overview.buildings[d.to_index].name})) });
  },
  suggestLayout: (_id: string, inverterId: string, pvFieldIds?: string[] | null) =>
    wait<MpptLayoutSuggestion>(demoSuggestLayout(state, inverterId, pvFieldIds ?? null), 200),
  shadingFreePitch: (_id: string, input: { module_definition_revision_id: string; orientation: "portrait" | "landscape"; tilt_deg: number; design_sun_elevation_deg: number; sun_azimuth_offset_deg: number; rows_per_table?: number; module_gap_y_m?: number }) => {
    const mod = catalog.modules.find((m) => m.revision_id === input.module_definition_revision_id);
    if (!mod) return Promise.reject(new Error(`module component revision not available: ${input.module_definition_revision_id}`));
    const rows = input.rows_per_table ?? 1;
    const length = input.orientation === "landscape" ? mod.width_m : mod.height_m;
    return wait<ShadingFreePitch>(demoShadingFreePitch(rows * length + (rows - 1) * (input.module_gap_y_m ?? 0), input), 60);
  },
  electricalDryRun: (_id: string, commands: { command_type: string; parameters: Record<string, unknown> }[]) => {
    const trial: State = structuredClone(state);
    trial.undo = []; trial.redo = [];
    let chain: Promise<unknown> = Promise.resolve();
    for (const c of commands) chain = chain.then(() => runTopology(trial, c as unknown as TopologyCommand));
    return chain.then(() => wait({ dry_run: true as const, topology_view: trial.view.topology_view, topology_checks: trial.view.topology_checks! }, 60));
  },
  createStrings: (_id: string, input: { string_length: number; pv_field_id?: string | null; allow_shorter_remainder: boolean }) =>
    runTopology(state, { command_type: "create_strings", parameters: { string_length: input.string_length, pv_field_id: input.pv_field_id ?? null, ordering: "row_major", allow_shorter_remainder: input.allow_shorter_remainder } }),
  assignStrings: (_id: string, input: { inverter_instance_id: string; string_ids?: string[] | null }) =>
    runTopology(state, { command_type: "assign_strings", parameters: { inverter_instance_id: input.inverter_instance_id, string_ids: input.string_ids ?? null } }),
  topologyCommand: (_id: string, command: TopologyCommand, _view?: ProjectView) => runTopology(state, command),
  acquireWeather: (_id: string, input: { source_id: string; start_date: string; end_date: string }) => {
    state.view.bundle.weather_selection = { weather_dataset_id: "wx-demo", revision_id: nid("wx"), source_id: input.source_id, name: "Demo weather (synthetic)", start_time: input.start_date, end_time: input.end_date, timezone: "Asia/Jakarta", data_quality_status: "passed" };
    return wait({ selection: state.view.bundle.weather_selection, manifest: {}, qc_report: {} }, 400);
  },
  executionReadiness: (_id: string) => {
    const b = state.view.bundle;
    const findings = [] as ExecutionReadiness["findings"];
    if (!b.weather_selection) findings.push({ rule_id: "weather.missing", severity: "blocking", category: "weather", message: "Select a weather dataset." });
    if (state.view.topology_view.unassigned_strings.length) findings.push({ rule_id: "topology.unassigned", severity: "blocking", category: "electrical", message: "Assign every string to an MPPT." });
    if (!b.scene.module_instances.length) findings.push({ rule_id: "scene.no_modules", severity: "blocking", category: "scene", message: "Create a PV field." });
    return wait<ExecutionReadiness>({ schema_name: "Phase5ExecutionReadiness", schema_version: "demo", readiness_version: "demo", ready: findings.length === 0, execution_class: "demo", findings });
  },
  simulate: (_id: string) => {
    const run = demoRun(state.view);
    state.view.bundle.simulation_runs.push(run);
    return wait(run, 700);
  },
  runs: (_id: string) => wait<SimulationRunRecord[]>(state.view.bundle.simulation_runs),
  runResult: (_id: string, runId: string) => {
    const run = state.view.bundle.simulation_runs.find((r) => r.simulation_run_id === runId);
    return run ? wait(run) : Promise.reject(new Error(`Unknown run ${runId}`));
  },
  electricalShadingCapability: () => notInDemo("electricalShadingCapability"),
  setElectricalShadingSelection: () => notInDemo("setElectricalShadingSelection"),
  importElectricalShadingAsset: () => notInDemo("importElectricalShadingAsset"),
  electricalRegionMap: () => notInDemo("electricalRegionMap"),
  level1ModuleSnapshot: () => notInDemo("level1ModuleSnapshot"),
  save: (_id: string) =>
    wait({ project_id: "demo-project", updated_at: new Date().toISOString(), scene_hash: state.view.identity.scene_hash, electrical_hash: state.view.identity.electrical_hash, project_revision_id: "pr-demo" })
} satisfies EngineAdapter;
