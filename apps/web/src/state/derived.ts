import { modulePlacement, isExplicitField, isGeneratedField, moduleNameplateW } from "../types";
import type { UIState, Step } from "./store";
import { checkLayout, parseNotation } from "../electrical/notation";

export type StepState = "none" | "draft" | "valid" | "blocked";

export interface LocalFinding {
  id: string;
  severity: "blocking" | "warning" | "draft" | "info";
  source: "engine" | "ui";
  message: string;
  entityId?: string;
  step?: Step;
}

/** The part of the state that findings, step states and quantities depend on. */
export type ModelState = Pick<UIState, "view" | "entities" | "modules" | "electrical">;

/** Selector for `useUI`: the inputs of the derived values below, compared shallowly. */
export const selectModel = (s: UIState): ModelState => ({ view: s.view, entities: s.entities, modules: s.modules, electrical: s.electrical });

export function modulesPerField(state: Pick<UIState, "modules">): Record<string, number> {
  const out: Record<string, number> = {};
  for (const m of state.modules) out[m.fieldId] = (out[m.fieldId] ?? 0) + 1;
  return out;
}

export function electricalIssues(state: ModelState): LocalFinding[] {
  const v = state.view;
  if (!v) return [];
  const perField = modulesPerField(state);
  const out: LocalFinding[] = [];
  for (const inv of v.bundle.electrical_design.inverter_instances) {
    const d = state.electrical[inv.inverter_instance_id];
    if (!d) continue;
    const def = v.catalog.inverters.find((i) => i.revision_id === inv.inverter_definition_revision_id);
    const parsed = parseNotation(d.notation);
    for (const i of parsed.issues)
      if (i.severity !== "info") out.push({ id: `${inv.name}-${i.code}`, severity: "blocking", source: "ui", message: `${inv.name}: ${i.message}`, step: "electrical" });
    if (!parsed.layout) continue;
    const available = d.pairedFieldIds.length ? d.pairedFieldIds.reduce((t, f) => t + (perField[f] ?? 0), 0) : null;
    const { issues } = checkLayout({
      layout: parsed.layout,
      mpptCount: def?.mppt_count ?? null,
      inputsPerMppt: d.inputsPerMppt,
      modulesAvailable: available,
      unequalParallelPolicy: "warning"
    });
    for (const i of issues)
      if (i.severity !== "info")
        out.push({ id: `${inv.name}-${i.code}-${i.mppt ?? ""}`, severity: i.severity === "blocking" ? "blocking" : "warning", source: "ui", message: `${inv.name}: ${i.message}`, step: "electrical" });
    // S14b: the overrides the engine design holds for this inverter's MPPTs.
    for (const o of v.bundle.electrical_design.orientation_policy?.overrides ?? []) {
      const idx = inv.mppt_instance_ids.indexOf(o.mppt_instance_id);
      if (idx >= 0)
        out.push({
          id: `${inv.name}-ovr-${idx}`,
          severity: "warning",
          source: "ui",
          message: `${inv.name} MPPT ${idx + 1}: mixed-orientation override (${o.reason}). Beyond the tolerance this MPPT is simulated with mixed orientations — beyond what PVsyst and HelioScope simulate.`,
          step: "electrical"
        });
    }
  }
  return out;
}

export function allFindings(state: ModelState): LocalFinding[] {
  const v = state.view;
  const out: LocalFinding[] = [];
  if (v)
    for (const f of v.topology_consistency.findings)
      out.push({ id: `eng-${f.code}-${f.entity_id}`, severity: f.severity === "blocking" || f.severity === "error" ? "blocking" : "draft", source: "engine", message: f.message, entityId: f.entity_id || undefined, step: "electrical" });
  for (const e of state.entities) {
    if (e.source === "draft")
      out.push({ id: `draft-${e.id}`, severity: "draft", source: "ui", message: `${e.name} is a local draft (not in the engine). Needs ${e.pending.join(", ")}.`, entityId: e.id, step: "scene" });
    else if (e.modified)
      out.push({ id: `mod-${e.id}`, severity: "draft", source: "ui", message: `${e.name} has local geometry edits not committed. Needs ${e.pending.join(", ")}.`, entityId: e.id, step: "scene" });
  }
  out.push(...electricalIssues(state));
  if (v) out.push(...engineDesignBlockers(v));
  if (v && !v.bundle.weather_selection) out.push({ id: "wx", severity: "blocking", source: "ui", message: "No weather dataset selected.", step: "meteo" });
  return out;
}

/**
 * USE1 (E2): the design blockers the engine's execution readiness also raises, from what the view already carries:
 * a layout-only inverter in use, an inverter without strings, and any failed engine string check. Electrical is then
 * never shown valid while the run is blocked.
 */
export function engineDesignBlockers(v: NonNullable<ModelState["view"]>): LocalFinding[] {
  const out: LocalFinding[] = [];
  const topology = new Map(v.topology_view.inverters.map((i) => [i.inverter_instance_id, i]));
  for (const inv of v.bundle.electrical_design.inverter_instances) {
    const def = v.catalog.inverters.find((c) => c.revision_id === inv.inverter_definition_revision_id);
    if (def?.simulation_ready === false)
      out.push({ id: `layout-only-${inv.inverter_instance_id}`, severity: "blocking", source: "engine", step: "electrical", entityId: inv.inverter_instance_id,
        message: `${inv.name} is layout only: complete its datasheet values (or switch to the completed revision) before simulating.` });
    if (!topology.get(inv.inverter_instance_id)?.mppts.some((m) => m.strings.length))
      out.push({ id: `no-strings-${inv.inverter_instance_id}`, severity: "blocking", source: "engine", step: "electrical", entityId: inv.inverter_instance_id,
        message: `${inv.name} has no strings: assign strings to it, or remove it.` });
  }
  for (const s of v.topology_checks?.strings ?? [])
    for (const c of s.checks)
      if (c.state === "fail")
        out.push({ id: `check-${s.string_id}-${c.code}`, severity: "blocking", source: "engine", step: "electrical", entityId: s.string_id, message: `${s.string_id}: ${c.message}` });
  return out;
}

export function stepStates(state: ModelState): Record<Step, StepState> {
  const v = state.view;
  const f = allFindings(state);
  const has = (step: Step, sev: LocalFinding["severity"]) => f.some((x) => x.step === step && x.severity === sev);
  const surfaces = state.entities.filter((e) => e.kind === "surface").length;
  const runs = v?.bundle.simulation_runs ?? [];
  const lastOk = runs.length > 0 && runs[runs.length - 1].status !== "failed";
  return {
    site: v ? "valid" : "none",
    scene: surfaces === 0 ? "none" : has("scene", "draft") ? "draft" : "valid",
    layout: state.modules.length ? "valid" : "none",
    components: !(v && v.catalog.modules.length && v.catalog.inverters.length) ? "none"
      : f.some((x) => x.id.startsWith("layout-only-")) ? "blocked" : "valid",
    systems: v?.bundle.scene.buildings?.length ? "valid" : "none",
    electrical: !v || !v.bundle.electrical_design.inverter_instances.length ? "none" : has("electrical", "blocking") ? "blocked" : has("electrical", "draft") || has("electrical", "warning") ? "draft" : "valid",
    meteo: v?.bundle.weather_selection ? "valid" : "blocked",
    losses: "none",
    simulate: lastOk ? "valid" : runs.length ? "blocked" : "none",
    results: lastOk ? "valid" : "none",
    export: lastOk ? "draft" : "none"
  };
}

export interface Quantities {
  modules: number;
  /** Sum of catalogue Pmp; the engine confirms nameplate. */
  kwp: number;
  acKw: number;
  dcac: number | null;
  strings: number;
  /** Modules not yet assigned to an MPPT. */
  unassigned: number;
}

/** Counts shown in the status bar. Display arithmetic only; no engineering result. */
export function quantities(state: ModelState): Quantities {
  const v = state.view;
  if (!v) return { modules: 0, kwp: 0, acKw: 0, dcac: null, strings: 0, unassigned: 0 };
  const hasExplicit = v.bundle.scene.pv_fields.some(isExplicitField);
  const displayed = hasExplicit ? v.bundle.scene.module_instances.map(m => ({id: m.module_instance_id})) : state.modules;
  const kwp = displayed.reduce((t, m) => {
    const md = v.catalog.modules.find((x) => x.revision_id === modulePlacement(v, m.id)?.revisionId);
    return t + (md ? moduleNameplateW(md) : 0) / 1000;
  }, 0);
  const acKw = v.bundle.electrical_design.inverter_instances.reduce((t, i) => {
    const d = v.catalog.inverters.find((x) => x.revision_id === i.inverter_definition_revision_id);
    return t + (d?.nominal_ac_power_w ?? 0) / 1000;
  }, 0);
  return {
    modules: displayed.length,
    kwp,
    acKw,
    dcac: acKw ? kwp / acKw : null,
    strings: v.bundle.electrical_design.strings.length,
    unassigned: hasExplicit ? displayed.filter(m => !v.bundle.electrical_design.strings.some(s => s.module_instance_ids.includes(m.id) && s.target_mppt_instance_id && v.bundle.electrical_design.inverter_instances.some(i => i.mppt_instance_ids.includes(s.target_mppt_instance_id!)))).length : state.modules.filter((m) => !m.mpptKey).length
  };
}
