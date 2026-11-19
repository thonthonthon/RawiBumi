/**
 * DEMO MODE ONLY — in-browser stand-in for the RawiBumi engineering API.
 * Same method surface as ../api. All numbers are illustrative, labeled as demo
 * in the UI, and are NOT simulation results. Components are synthetic.
 */
import type {
  Catalog,
  CreateProjectInput,
  ExecutionReadiness,
  LocalFeature,
  ProjectSummary,
  ProjectView,
  SimulationRunRecord,
  WeatherSource,
  WorkspaceMode
} from "../types";


type Rect = { x: number; y: number; w: number; h: number };


const catalog: Catalog = {
  modules: [
    { revision_id: "mod-demo-550", manufacturer: "Demo", model: "550 W mono (synthetic)", pmp_w: 550, width_m: 1.134, height_m: 2.278, synthetic_reference: true, simulation_ready: true },
    { revision_id: "mod-demo-610", manufacturer: "Demo", model: "610 W mono (synthetic)", pmp_w: 610, width_m: 1.134, height_m: 2.382, synthetic_reference: true, simulation_ready: false }
  ],
  inverters: [
    { revision_id: "inv-demo-30k", manufacturer: "Demo", model: "30 kW, 4 MPPT (synthetic)", nominal_ac_power_w: 30000, mppt_count: 4, synthetic_reference: true, simulation_ready: true },
    { revision_id: "inv-demo-100k", manufacturer: "Demo", model: "100 kW, 10 MPPT (synthetic)", nominal_ac_power_w: 100000, mppt_count: 10, synthetic_reference: true, simulation_ready: false }
  ],
  module_topologies: []
};


let seq = 100;
const nid = (p: string) => `${p}-${(seq++).toString(36)}`;
const rectPoly = (r: Rect): [number, number][] => [
  [r.x, r.y],
  [r.x + r.w, r.y],
  [r.x + r.w, r.y + r.h],
  [r.x, r.y + r.h]
];
const overlaps = (a: Rect, b: Rect) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;


interface State {
  view: ProjectView;
  rects: Record<string, Rect>;
}


function monthly(totalKwh: number) {
  const shape = [0.083, 0.078, 0.086, 0.084, 0.087, 0.083, 0.088, 0.092, 0.089, 0.085, 0.074, 0.071];
  const s = shape.reduce((a, b) => a + b, 0);
  return ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12"].map(
    (month, i) => ({ month, energy_wh: (totalKwh * 1000 * shape[i]) / s })
  );
}


function demoRun(view: ProjectView): SimulationRunRecord {
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
    simulation_run_id: nid("run"),
    status: "completed",
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
  const f: LocalFeature[] = [];
  for (const s of b.scene.surfaces) f.push({ id: s.surface_id, category: "surface", subtype: s.surface_type, name: s.name, polygon: rectPoly(st.rects[s.surface_id]) });
  for (const o of b.scene.obstacles) f.push({ id: o.obstacle_id, category: "obstacle", subtype: o.obstacle_type, name: o.name, polygon: rectPoly(st.rects[o.obstacle_id]) });
  for (const m of b.scene.module_instances)
    f.push({ id: m.module_instance_id, category: "module", subtype: "module", name: m.module_instance_id, pv_field_id: m.pv_field_id, polygon: rectPoly(st.rects[m.module_instance_id]) });
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
  const un = st.view.topology_view.unassigned_strings.length;
  st.view.topology_consistency = {
    blocking_count: 0,
    draft_count: un,
    findings: un ? [{ severity: "draft", code: "string_unassigned", entity_id: "", message: `${un} strings are not assigned to an MPPT.` }] : []
  };
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
  const out: Rect[] = [];
  const x0 = s.x + input.perimeter_setback_m;
  const y0 = s.y + input.perimeter_setback_m;
  for (let y = y0; y + d <= s.y + s.h - input.perimeter_setback_m + 1e-9; y += input.row_pitch_m) {
    let inRow = 0;
    for (let x = x0; x + w <= s.x + s.w - input.perimeter_setback_m + 1e-9; x += w + input.module_gap_x_m) {
      if (maxPerRow && inRow >= maxPerRow) break;
      inRow++;
      const r = { x, y, w, h: d };
      if (!obstacles.some((o) => overlaps(o, r))) out.push(r);
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
  const view: ProjectView = {
    bundle: {
      schema_name: "ProjectBundle",
      schema_version: "demo",
      project: {
        project_id: "demo-project",
        name: input?.name ?? "Warehouse rooftop (demo)",
        status: "draft",
        site: { latitude_deg: lat, longitude_deg: lon, elevation_m: 12, timezone: input?.timezone ?? "Asia/Jakarta", north_reference: "geodetic_true_north" },
        project_revision: { project_revision_id: "pr-demo", revision_number: 1, scene_revision_id: "scene-demo", electrical_revision_id: "elec-demo" }
      },
      scene: { revision_id: "scene-demo", surfaces: [], obstacles: [], pv_fields: [], module_instances: [] },
      electrical_design: { electrical_revision_id: "elec-demo", inverter_instances: [], strings: [] },
      site_workspace_bootstrap: { workspace_context: { mode: "blank_engineering_plane", map_layer_configuration_id: null, show_true_north: true, show_metric_grid: true } },
      workspace_state: { panel_state: { site_workspace_mode: "blank_engineering_plane" } },
      weather_selection: null,
      simulation_runs: [],
      updated_at: new Date().toISOString()
    },
    scene_view: { local_features: [], geojson: { type: "FeatureCollection", features: [] }, site: { latitude_deg: lat, longitude_deg: lon, elevation_m: 12, timezone: "Asia/Jakarta", north_reference: "geodetic_true_north" } },
    topology_view: { electrical_revision_id: "elec-demo", inverters: [], unassigned_strings: [] },
    topology_consistency: { blocking_count: 0, draft_count: 0, findings: [] },
    identity: { scene_hash: "", electrical_hash: "" },
    catalog
  };
  const st: State = { view, rects: {} };
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
    tilt_deg: 10
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


let state: State = initialState();
const clone = <T>(v: T): T => structuredClone(v);
const wait = <T>(v: T, ms = 120) => new Promise<T>((r) => setTimeout(() => r(clone(v)), ms));


export const mockApi = {
  health: () => wait({ status: "ok", phase: "demo" }),
  catalog: () => wait(catalog),
  weatherSources: () =>
    wait<WeatherSource[]>([
      { provider_id: "demo", source_id: "demo-tmy", label: "Demo TMY (synthetic)", acquisition_type: "tmy", rawibumi_resource_projection_applied: false },
      { provider_id: "demo", source_id: "demo-series", label: "Demo hourly series (synthetic)", acquisition_type: "time_series", rawibumi_resource_projection_applied: false }
    ]),
  projects: () =>
    wait<ProjectSummary[]>([
      { project_id: "demo-project", name: state.view.bundle.project.name, status: "draft", latitude_deg: state.view.bundle.project.site.latitude_deg, longitude_deg: state.view.bundle.project.site.longitude_deg, timezone: "Asia/Jakarta" }
    ]),
  project: (_id: string) => wait(state.view),
  createProject: (input: CreateProjectInput) => {
    state = initialState(input);
    return wait(state.view);
  },
  setWorkspaceMode: (_id: string, mode: WorkspaceMode) => {
    state.view.bundle.site_workspace_bootstrap.workspace_context.mode = mode;
    return wait(state.view);
  },
  addSurface: (_id: string, input: { name: string; origin_x_m: number; origin_y_m: number; width_m: number; height_m: number; base_elevation_m: number; surface_type: string }) => {
    const id = nid("srf");
    state.rects[id] = { x: input.origin_x_m, y: input.origin_y_m, w: input.width_m, h: input.height_m };
    state.view.bundle.scene.surfaces.push({ surface_id: id, name: input.name, surface_type: input.surface_type, base_elevation_m: input.base_elevation_m });
    rebuildFeatures(state);
    return wait(state.view);
  },
  moveSceneEntity: (_id: string, input: { entity_id: string; dx_m: number; dy_m: number }) => {
    const r = state.rects[input.entity_id];
    if (!r) return Promise.reject(new Error(`Unknown entity ${input.entity_id}`));
    const hosts = state.view.bundle.scene.pv_fields.some((f) => f.support_surface_id === input.entity_id);
    if (hosts) return Promise.reject(new Error("Surface supports a PV field; choose layout-impact handling first (fail-closed)."));
    r.x += input.dx_m;
    r.y += input.dy_m;
    rebuildFeatures(state);
    return wait(state.view);
  },
  addObstacle: (_id: string, input: { name: string; origin_x_m: number; origin_y_m: number; width_m: number; depth_m: number; base_elevation_m: number; height_m: number }) => {
    const id = nid("obs");
    state.rects[id] = { x: input.origin_x_m, y: input.origin_y_m, w: input.width_m, h: input.depth_m };
    state.view.bundle.scene.obstacles.push({ obstacle_id: id, name: input.name, obstacle_type: "box", base_elevation_m: input.base_elevation_m, height_m: input.height_m });
    rebuildFeatures(state);
    return wait(state.view);
  },
  createPvField: (_id: string, input: { name: string; support_surface_id: string; module_definition_revision_id: string; orientation: string; azimuth_deg: number; tilt_deg: number; module_gap_x_m: number; module_gap_y_m: number; row_pitch_m: number; mounting_height_m: number; perimeter_setback_m: number; obstacle_setback_m: number }) => {
    const id = nid("fld");
    state.view.bundle.scene.pv_fields.push({ pv_field_id: id, name: input.name, support_surface_id: input.support_surface_id, module_definition_revision_id: input.module_definition_revision_id, row_count: 0, modules_per_row: 0, orientation: input.orientation, azimuth_deg: input.azimuth_deg, tilt_deg: input.tilt_deg });
    fill(state, id, input.support_surface_id, input);
    rebuildFeatures(state);
    return wait(state.view, 300);
  },
  addInverter: (_id: string, input: { inverter_definition_revision_id: string; name: string }) => {
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
  createStrings: (_id: string, input: { string_length: number; pv_field_id?: string | null; allow_shorter_remainder: boolean }) => {
    const e = state.view.bundle.electrical_design;
    const strung = new Set(e.strings.flatMap((s) => s.module_instance_ids));
    const free = state.view.bundle.scene.module_instances.filter((m) => !strung.has(m.module_instance_id) && (!input.pv_field_id || m.pv_field_id === input.pv_field_id)).map((m) => m.module_instance_id);
    for (let i = 0; i + input.string_length <= free.length || (input.allow_shorter_remainder && i < free.length); i += input.string_length)
      e.strings.push({ string_id: `S${e.strings.length + 1}`, module_instance_ids: free.slice(i, i + input.string_length), target_mppt_instance_id: null, enabled: true });
    rebuildTopology(state);
    return wait(state.view);
  },
  assignStrings: (_id: string, input: { inverter_instance_id: string }) => {
    const e = state.view.bundle.electrical_design;
    const inv = e.inverter_instances.find((i) => i.inverter_instance_id === input.inverter_instance_id);
    if (!inv) return Promise.reject(new Error("Unknown inverter"));
    let k = 0;
    for (const s of e.strings.filter((x) => !x.target_mppt_instance_id)) s.target_mppt_instance_id = inv.mppt_instance_ids[k++ % inv.mppt_instance_ids.length];
    rebuildTopology(state);
    return wait(state.view);
  },
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
  save: (_id: string) =>
    wait({ project_id: "demo-project", updated_at: new Date().toISOString(), scene_hash: state.view.identity.scene_hash, electrical_hash: state.view.identity.electrical_hash, project_revision_id: "pr-demo" })
};