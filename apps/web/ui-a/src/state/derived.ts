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

export function modulesPerField(state: UIState): Record<string, number> {
  const out: Record<string, number> = {};
  for (const m of state.modules) out[m.fieldId] = (out[m.fieldId] ?? 0) + 1;
  return out;
}

export function electricalIssues(state: UIState): LocalFinding[] {
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
    for (const [idx, o] of Object.entries(d.overrides))
      if (o.on)
        out.push({
          id: `${inv.name}-ovr-${idx}`,
          severity: "warning",
          source: "ui",
          message: `${inv.name} MPPT ${Number(idx) + 1}: mixed-orientation override${o.reason ? ` (${o.reason})` : " without a reason"}. Execution blocked until engine supports mixed-orientation IV aggregation.`,
          step: "electrical"
        });
  }
  return out;
}

export function allFindings(state: UIState): LocalFinding[] {
  const v = state.view;
  const out: LocalFinding[] = [];
  if (v)
    for (const f of v.topology_consistency.findings)
      out.push({ id: `eng-${f.code}-${f.entity_id}`, severity: f.severity === "blocking" ? "blocking" : "draft", source: "engine", message: f.message, entityId: f.entity_id || undefined, step: "electrical" });
  for (const e of state.entities) {
    if (e.source === "draft")
      out.push({ id: `draft-${e.id}`, severity: "draft", source: "ui", message: `${e.name} is a local draft (not in the engine). Needs ${e.pending.join(", ")}.`, entityId: e.id, step: "scene" });
    else if (e.modified)
      out.push({ id: `mod-${e.id}`, severity: "draft", source: "ui", message: `${e.name} has local geometry edits not committed. Needs ${e.pending.join(", ")}.`, entityId: e.id, step: "scene" });
  }
  out.push(...electricalIssues(state));
  if (v && !v.bundle.weather_selection) out.push({ id: "wx", severity: "blocking", source: "ui", message: "No weather dataset selected.", step: "meteo" });
  return out;
}

export function stepStates(state: UIState): Record<Step, StepState> {
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
    components: v && v.catalog.modules.length && v.catalog.inverters.length ? "valid" : "none",
    electrical: !v || !v.bundle.electrical_design.inverter_instances.length ? "none" : has("electrical", "blocking") ? "blocked" : has("electrical", "draft") || has("electrical", "warning") ? "draft" : "valid",
    meteo: v?.bundle.weather_selection ? "valid" : "blocked",
    simulate: lastOk ? "valid" : runs.length ? "blocked" : "none",
    results: lastOk ? "valid" : "none",
    export: lastOk ? "draft" : "none"
  };
}
