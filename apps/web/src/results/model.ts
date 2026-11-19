import i18n from "i18next";
import { modulePlacement, moduleNameplateW } from "../types";
import type { ProjectView, SimulationRunRecord } from "../types";

/**
 * The results view model (F7, ADR 0016). One projection of an engine run that the results
 * screen and the HTML report both read. It is a projection only: never a second PV solver.
 * The checks below are S10's result rules (`s10/src/domain/report.ts`, `fixture.ts`,
 * `tests/report.test.ts`, `tests/s06_report_test.py`), ported to the engine's summary result.
 */

export type Authority = "ENGINE" | "DEMO_SYNTHETIC";

export interface LossStep {
  label: string;
  stage: string;
  referenceKwh: number;
  lossKwh: number;
  remainingKwh: number;
}

export interface Coverage {
  /** Hourly intervals in the source series and how many are missing. */
  sourceHours: number;
  missingHours: number;
  /** The 52-week view shows 52 × 7 × 24 hours; the rest are left out of that view only. */
  weeklyShown: number;
  weeklyExcluded: number;
  /** Day-of-year indices (0-based) the weekly view leaves out. */
  excludedDays: number[];
}

/** Where a string's modules sit: the PV field and its orientation, from the design (not the run). */
export interface FieldOrientation {
  field: string;
  /** Engine convention: 0° north, clockwise (90° east, 180° south). */
  azimuthDeg: number;
  /** From horizontal. */
  tiltDeg: number;
  /** Module placement in the field: portrait or landscape. */
  moduleOrientation: string;
}

export interface TopologyRow {
  inverter: string;
  mppt: number;
  string: string;
  modules: number;
  /** One entry per PV field the string's modules sit in. */
  fields: FieldOrientation[];
  /** True when the string's modules face more than one azimuth/tilt. */
  mixed: boolean;
}

/** One inverter's share of the design, for the report's mapping tables (F7.1). */
export interface InverterBlock {
  name: string;
  /** Manufacturer and model from the catalogue. */
  model: string;
  acKw: number;
  /** Modules in the strings assigned to this inverter × their catalogue Pmp. */
  dcKwp: number;
  /** Module types in those strings, "manufacturer model (Pmp W)". */
  moduleModels: string[];
  rows: TopologyRow[];
}

/** Shading as the engine reports it in the run summary. Null fields: not reported. */
export interface ShadingSummary {
  /** Energy lost to shading over the run at the AC boundary, kWh; null when not quantified. */
  lossKwh: number | null;
  /** The same run with shading switched off (the engine's counterfactual), kWh. */
  unshadedKwh: number | null;
  /** What the loss covers, e.g. "geometric_near_shading_only". */
  scope: string | null;
  /** Whether electrical mismatch from partial shading is included. */
  mismatchIncluded: boolean | null;
  method: string | null;
}

export interface ResultModel {
  runId: string;
  project: string;
  timezone: string;
  periodStart: string;
  periodEnd: string;
  periodHours: number;
  authority: Authority;
  /** No P50/P90 is computed anywhere (S10 a14). */
  uncertainty: "NOT_MODELED";
  /** Whether the run simulated the current design. Only "current" may use current-design figures. */
  designBasis: DesignBasis;
  /** Null when the run saved no capacity and its design is not the current one. */
  dcKwp: number | null;
  acKw: number | null;
  /** AC energy over the simulated period, from total_energy_wh. */
  periodAcKwh: number;
  /** Only the engine's annual_energy_wh; never an estimate from period energy. */
  annualAcKwh: number | null;
  monthlyAcKwh: number[];
  specificYield: number;
  performanceRatio: number;
  peakAcKw: number;
  clippingKwh: number;
  referenceKwh: number | null;
  losses: LossStep[];
  /** 52 weeks × 24 hours of mean AC power, kW, when an hourly series exists. */
  heatmap52: number[][] | null;
  coverage: Coverage | null;
  topology: TopologyRow[];
  /** Per-inverter mapping, inverters sorted by name. */
  inverters: InverterBlock[];
  /** Strings not assigned to an MPPT. */
  unassigned: { string: string; modules: number }[];
  shading: ShadingSummary;
  assumptions: { id: string; severity: string; statement: string }[];
}

export type RuleState = "pass" | "fail" | "unavailable";

export interface RuleResult {
  /** S10 rule this ports, e.g. "S03.loss-reconciles" or "S06.a10". */
  id: string;
  state: RuleState;
  message: string;
  /** A failed blocking rule stops the report (S10: the projection is refused). */
  blocking: boolean;
}

export class ResultRuleError extends Error {
  constructor(readonly failures: RuleResult[]) {
    super(`Result rules failed: ${failures.map((f) => `${f.id} (${f.message})`).join("; ")}`);
  }
}

/** RES1: a report must describe the design the run simulated; refuse an earlier or unknown design. */
export class EarlierDesignError extends Error {
  constructor(readonly basis: Exclude<DesignBasis, "current">) {
    super(basis === "earlier" ? "This run is from an earlier design. Run the simulation again to make a report." : "This run was saved before design tracking. Run the simulation again to make a report.");
  }
}

const HOURS_PER_WEEK = 168;

/** Mean AC power per week and hour of day over the first 52 × 7 days (S10 heatmap rule). */
export function weeklyHeatmap(hourly: readonly (readonly number[])[]): { values: number[][]; coverage: Coverage } {
  const days = hourly.length;
  // A cell is the mean of that week's days that have the hour (S15: engine runs can be shorter than a year or have
  // gaps); NaN when none has it. A complete year averages all seven days, as before.
  const values = Array.from({ length: 52 }, (_, w) =>
    Array.from({ length: 24 }, (_, h) => {
      let s = 0, n = 0;
      for (let d = 0; d < 7; d++) {
        const v = hourly[w * 7 + d]?.[h];
        if (v !== undefined && Number.isFinite(v)) { s += v; n++; }
      }
      return n ? s / n : NaN;
    })
  );
  const missing = hourly.reduce((t, d) => t + (24 - d.filter((x) => Number.isFinite(x)).length), 0);
  const excludedDays = Array.from({ length: Math.max(0, days - 364) }, (_, i) => 364 + i);
  return {
    values,
    coverage: { sourceHours: days * 24, missingHours: missing, weeklyShown: 52 * HOURS_PER_WEEK, weeklyExcluded: excludedDays.length * 24, excludedDays }
  };
}

/** Installed DC capacity from the design: modules × their DC nameplate (D14: datasheet nominal, else STC Pmp). */
export function dcCapacityKwp(view: ProjectView): number {
  const pmp = new Map(view.catalog.modules.map(m => [m.revision_id, moduleNameplateW(m)]));
  let w = 0;
  // module_instances is the bundle's full list, table-level fields included.
  for (const m of view.bundle.scene.module_instances) w += pmp.get(modulePlacement(view, m.module_instance_id)?.revisionId ?? "") ?? 0;
  return w / 1000;
}

export type DesignBasis = "current" | "earlier" | "unknown";

/** RES1: "current" only when both fingerprints exist and match; a run saved before design tracking is "unknown". */
export function runDesignBasis(view: ProjectView, run: SimulationRunRecord): DesignBasis {
  if (!run.design_fingerprint || !view.design_fingerprint) return "unknown";
  return run.design_fingerprint === view.design_fingerprint ? "current" : "earlier";
}

export function buildResultModel(view: ProjectView, run: SimulationRunRecord, opts: { authority: Authority; hourlyAcKw: number[][] | null; periodAware?: boolean; t?: (key: string) => string }): ResultModel {
  const s = run.summary_result;
  if (!s) throw new Error(`Run ${run.simulation_run_id} has no summary result.`);
  const designBasis = runDesignBasis(view, run);
  // Another design's capacity, topology and orientation must never be shown against this run.
  const current = designBasis === "current";
  const savedDcW = s.execution_breakdown?.simulated_dc_nameplate_w ?? s.resolved_loss_settings?.simulated_dc_nameplate_w;
  const ref = s.loss_summary.length ? s.loss_summary[0].reference_energy_wh / 1000 : null;
  let remaining = ref ?? 0;
  const losses = s.loss_summary.map((l) => {
    remaining -= l.lost_energy_wh / 1000;
    return { label: run.mixed_orientation && l.loss_type === "orientation_mismatch" ? (opts.t ?? i18n.t.bind(i18n))("losses.stages.orientation_mismatch") : l.loss_type.replace(/_/g, " "), stage: l.stage, referenceKwh: l.reference_energy_wh / 1000, lossKwh: l.lost_energy_wh / 1000, remainingKwh: remaining };
  });
  const heat = opts.hourlyAcKw ? weeklyHeatmap(opts.hourlyAcKw) : null;
  const mpptIndex = new Map<string, number>();
  for (const inv of view.topology_view.inverters) for (const m of inv.mppts) mpptIndex.set(m.mppt_instance_id, m.index);
  const invOfMppt = new Map<string, (typeof view.bundle.electrical_design.inverter_instances)[number]>();
  for (const inv of view.bundle.electrical_design.inverter_instances) for (const m of inv.mppt_instance_ids) invOfMppt.set(m, inv);
  const invDef = (id: string) => view.catalog.inverters.find((x) => x.revision_id === id);
  const acKw = s.execution_breakdown
    ? s.execution_breakdown.inverters.reduce((t, i) => t + i.nominal_ac_power_w / 1000, 0)
    : current ? view.bundle.electrical_design.inverter_instances.reduce((t, i) => t + (invDef(i.inverter_definition_revision_id)?.nominal_ac_power_w ?? 0) / 1000, 0) : null;

  const moduleDef = (moduleId: string) => view.catalog.modules.find(m => m.revision_id === modulePlacement(view, moduleId)?.revisionId);
  const orientationOf = (moduleIds: string[]): { fields: FieldOrientation[]; mixed: boolean } => {
    const records = new Map<string, FieldOrientation>();
    for (const id of moduleIds) {
      const p = modulePlacement(view, id);
      if (p) records.set(`${p.field.pv_field_id}|${p.tableId ?? ""}`, {
        field: p.tableId ? `${p.field.name} / ${p.tableId}` : p.field.name,
        azimuthDeg: p.azimuthDeg, tiltDeg: p.tiltDeg, moduleOrientation: p.orientation
      });
    }
    const fields = [...records.values()].sort((a,b) => a.field.localeCompare(b.field));
    return {fields, mixed: new Set(fields.map(f => `${f.azimuthDeg}|${f.tiltDeg}`)).size > 1};
  };
  const byString = (a: { string: string }, b: { string: string }) => a.string.localeCompare(b.string, undefined, { numeric: true });

  const assigned = current ? view.bundle.electrical_design.strings.filter((x) => x.target_mppt_instance_id && invOfMppt.has(x.target_mppt_instance_id)) : [];
  const topology: TopologyRow[] = assigned
    .map((x) => ({
      inverter: invOfMppt.get(x.target_mppt_instance_id!)!.name,
      mppt: mpptIndex.get(x.target_mppt_instance_id!) ?? 0,
      string: x.string_id,
      modules: x.module_instance_ids.length,
      ...orientationOf(x.module_instance_ids)
    }))
    .sort((a, b) => a.inverter.localeCompare(b.inverter) || a.mppt - b.mppt || byString(a, b));

  const inverters: InverterBlock[] = (current ? [...view.bundle.electrical_design.inverter_instances] : [])
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
    .map((inv) => {
      const def = invDef(inv.inverter_definition_revision_id);
      const mine = assigned.filter((x) => inv.mppt_instance_ids.includes(x.target_mppt_instance_id!));
      const modules = mine.flatMap((x) => x.module_instance_ids);
      const defs = modules.map(moduleDef);
      const models = [...new Set(defs.filter((d) => d).map((d) => `${d!.manufacturer} ${d!.model} (${moduleNameplateW(d!)} W)`))].sort();
      return {
        name: inv.name,
        model: def ? `${def.manufacturer} ${def.model}` : inv.inverter_definition_revision_id,
        acKw: (def?.nominal_ac_power_w ?? 0) / 1000,
        dcKwp: defs.reduce((t, d) => t + (d ? moduleNameplateW(d) : 0), 0) / 1000,
        moduleModels: models,
        rows: topology.filter((r) => r.inverter === inv.name)
      };
    });
  const unassigned = (current ? view.bundle.electrical_design.strings : [])
    .filter((x) => !x.target_mppt_instance_id || !invOfMppt.has(x.target_mppt_instance_id))
    .map((x) => ({ string: x.string_id, modules: x.module_instance_ids.length }))
    .sort(byString);

  const basis = (s.shading_energy_loss_basis ?? null) as Record<string, unknown> | null;
  const num = (x: unknown) => (typeof x === "number" ? x : null);
  const shading: ShadingSummary = {
    lossKwh: s.shading_energy_loss_wh === null || s.shading_energy_loss_wh === undefined ? null : s.shading_energy_loss_wh / 1000,
    unshadedKwh: num(basis?.counterfactual_pcc_energy_wh) === null ? null : num(basis!.counterfactual_pcc_energy_wh)! / 1000,
    scope: typeof basis?.scope === "string" ? basis.scope : null,
    mismatchIncluded: typeof basis?.electrical_mismatch_included === "boolean" ? basis.electrical_mismatch_included : null,
    method: typeof basis?.method_id === "string" ? basis.method_id : null
  };
  return {
    runId: run.simulation_run_id,
    project: view.bundle.project.name,
    timezone: view.bundle.project.site.timezone,
    periodStart: s.period_start_time,
    periodEnd: s.period_end_time,
    periodHours: s.period_duration_hours,
    authority: opts.authority,
    uncertainty: "NOT_MODELED",
    designBasis,
    // USE1 (R2): the run's own simulated nameplate first; unstrung placed modules are not part of the run.
    dcKwp: savedDcW !== undefined ? savedDcW / 1000 : current ? dcCapacityKwp(view) : null,
    acKw,
    periodAcKwh: s.total_energy_wh / 1000,
    annualAcKwh: s.annual_energy_wh === null ? null : s.annual_energy_wh / 1000,
    monthlyAcKwh: s.monthly_energy.map((m) => m.energy_wh / 1000),
    specificYield: s.specific_yield_wh_per_wp,
    performanceRatio: s.performance_ratio,
    peakAcKw: s.peak_ac_power_w / 1000,
    clippingKwh: s.clipping_energy_wh / 1000,
    referenceKwh: ref,
    losses,
    heatmap52: heat?.values ?? null,
    coverage: heat?.coverage ?? null,
    topology,
    inverters,
    unassigned,
    shading,
    assumptions: (run.assumptions ?? []).map((a) => ({ id: a.assumption_id ?? "", severity: a.severity ?? "info", statement: a.statement ?? "" }))
  };
}

const close = (a: number, b: number, rel = 1e-3, abs = 1) => Math.abs(a - b) <= Math.max(abs, rel * Math.abs(b));
const finite = (xs: number[]) => xs.every((x) => Number.isFinite(x));

/** Phase 7 reports a 365-day representative year, with no frontend annualisation. */
export function isAnnualResult(m: ResultModel): m is ResultModel & { annualAcKwh: number } {
  return m.annualAcKwh !== null && Number.isFinite(m.annualAcKwh) && m.annualAcKwh >= 0 && m.periodHours === 8760 && m.monthlyAcKwh.length === 12;
}

/** S10's result rules on a result model. Unavailable means the engine does not report the input yet. */
export function checkResultRules(m: ResultModel, design: { strings: number }, periodAware = false): RuleResult[] {
  const out: RuleResult[] = [];
  const add = (id: string, state: RuleState, message: string, blocking = true) => out.push({ id, state, message, blocking });
  const monthlySum = m.monthlyAcKwh.reduce((a, b) => a + b, 0);
  const annual = isAnnualResult(m);
  const acKwh = annual ? m.annualAcKwh : m.periodAcKwh;
  const energyBasis = annual ? "annual" : "simulated-period";

  add("S03.twelve-months", m.monthlyAcKwh.length === 12 ? "pass" : "fail", `${m.monthlyAcKwh.length} monthly bins (12 required).`);
  const annualAvailable = m.annualAcKwh !== null && Number.isFinite(m.annualAcKwh) && m.annualAcKwh >= 0;
  add("S03.annual-energy-available", annualAvailable ? "pass" : "fail", annualAvailable ? "The engine reports finite, nonnegative annual energy." : "Annual energy is unavailable or invalid; an annual report requires annual_energy_wh.");
  if (annual) add("S06.a04", close(monthlySum, m.annualAcKwh) ? "pass" : "fail", `Σ monthly ${monthlySum.toFixed(1)} kWh against annual ${m.annualAcKwh.toFixed(1)} kWh.`);
  else add("S06.a04", "unavailable", "Annual reconciliation requires annual energy, exactly 8,760 period hours and 12 monthly bins.");
  const numbers = [m.periodAcKwh, m.specificYield, m.performanceRatio, m.peakAcKw, m.clippingKwh, ...m.monthlyAcKwh, ...m.losses.flatMap((l) => [l.lossKwh, l.remainingKwh]), ...[m.annualAcKwh, m.shading.lossKwh, m.shading.unshadedKwh].filter((x): x is number => x !== null)];
  add("S06.a13", finite(numbers) ? "pass" : "fail", finite(numbers) ? "Every reported number is finite." : "A reported number is not finite.");
  if (m.referenceKwh === null || !m.losses.length) add("S03.loss-reconciles", "unavailable", "The run reports no loss ledger.", false);
  else {
    const end = m.losses[m.losses.length - 1].remainingKwh;
    add("S03.loss-reconciles", close(end, acKwh) ? "pass" : "fail", `Loss waterfall ends at ${end.toFixed(1)} kWh; ${energyBasis} AC energy is ${acKwh.toFixed(1)} kWh.`);
  }
  add("S03.pcc-distinct", "unavailable", "The engine reports one AC boundary; inverter AC and PCC are not separated yet.", false);
  add("S03.full-year", m.periodHours === 8760 ? "pass" : "fail", `Run period ${m.periodHours} h (Phase 7 requires exactly 8,760 h).`);
  if (!m.coverage) add("S06.a05", "unavailable", "No hourly series: coverage and the 52-week view need the time-series route.", false);
  else {
    const c = m.coverage;
    add("S06.a05", c.missingHours === 0 && c.sourceHours === 8760 ? "pass" : "fail", `${c.sourceHours} source hours, ${c.missingHours} missing (Phase 7 requires 8,760 source hours).`);
    add("S03.weekly-reduction", c.weeklyShown + c.weeklyExcluded === c.sourceHours && c.weeklyShown === 8736 ? "pass" : "fail", `Weekly view shows ${c.weeklyShown} h and leaves out ${c.weeklyExcluded} h of ${c.sourceHours}.`);
  }
  if (m.dcKwp === null) add("S01.dc-quantity", "unavailable", "The run saved no DC capacity, and the current design is not the one it simulated.", false);
  else if (m.dcKwp > 0) {
    const implied = acKwh / m.dcKwp;
    add("S01.dc-quantity", close(implied, m.specificYield, 0.01, 0.5) ? "pass" : "fail", `Specific yield ${m.specificYield.toFixed(0)} kWh/kWp against ${implied.toFixed(0)} from ${energyBasis} energy ÷ ${m.dcKwp.toFixed(2)} kWp.`, false);
  } else add("S01.dc-quantity", "unavailable", "The design has no modules with a catalogue Pmp.", false);
  if (m.designBasis !== "current") add("S06.a06", "unavailable", "The topology table needs the run's own design; the current design is not the one it simulated.");
  else add("S06.a06", m.topology.length === new Set(m.topology.map((r) => r.string)).size && m.topology.length <= design.strings ? "pass" : "fail", `${m.topology.length} assigned strings in the topology table, each once.`);
  add("S06.a14", m.uncertainty === "NOT_MODELED" ? "pass" : "fail", "The run carries no uncertainty of its own; annual Pxx is computed separately from the assumption ledger.");
  if (periodAware && !isAnnualResult(m)) {
    const complete = m.annualAcKwh !== null && (m.periodHours === 8760 || m.periodHours === 8784);
    const inapplicable = "not applicable to a partial period";
    if (!complete) {
      for (const row of out) if (["S03.twelve-months", "S03.annual-energy-available", "S03.full-year", "S06.a05", "S03.weekly-reduction"].includes(row.id)) {
        row.state = "unavailable"; row.message = inapplicable; row.blocking = false;
      }
    } else if (isCompleteYearResult(m)) {
      for (const row of out) if (["S03.full-year", "S06.a05", "S03.weekly-reduction"].includes(row.id)) {
        if (row.id === "S03.full-year") { row.state = "pass"; row.message = `Run period ${m.periodHours} h.`; }
        else if (m.coverage) {
          const c = m.coverage;
          const pass = row.id === "S06.a05" ? c.missingHours === 0 && c.sourceHours === m.periodHours : c.weeklyShown + c.weeklyExcluded === c.sourceHours && c.weeklyShown === 8736;
          row.state = pass ? "pass" : "fail";
          row.message = `${c.sourceHours} source hours, ${c.missingHours} missing; ${c.weeklyShown} shown, ${c.weeklyExcluded} excluded.`;
        }
      }
    }
    const monthly = out.find(row => row.id === "S06.a04")!;
    monthly.state = close(monthlySum, acKwh, 1e-9, 1e-9) ? "pass" : "fail";
    monthly.message = `Σ monthly ${monthlySum.toFixed(1)} kWh against simulated-period ${acKwh.toFixed(1)} kWh.`;
  }
  return out;
}

/** Complete recorded year, including leap years; never annualises a partial run. */
export function isCompleteYearResult(m: ResultModel): m is ResultModel & { annualAcKwh: number } {
  return m.annualAcKwh !== null && Number.isFinite(m.annualAcKwh) && m.annualAcKwh >= 0 && (m.periodHours === 8760 || m.periodHours === 8784) && m.monthlyAcKwh.length === 12;
}

/** Like S10's `projectReport`: refuses an unknown run or a model that breaks a blocking rule. */
export function reportModel(view: ProjectView, runId: string, opts: { authority: Authority; hourlyAcKw: number[][] | null; periodAware?: boolean; t?: (key: string) => string }): { model: ResultModel; rules: RuleResult[] } {
  const run = view.bundle.simulation_runs.find((r) => r.simulation_run_id === runId);
  if (!run) throw new Error(`Run ${runId} is not part of this project; no report.`);
  const basis = runDesignBasis(view, run);
  if (basis !== "current") throw new EarlierDesignError(basis);
  const model = buildResultModel(view, run, opts);
  const rules = checkResultRules(model, { strings: view.bundle.electrical_design.strings.length }, opts.periodAware);
  const failures = rules.filter((r) => r.state === "fail" && r.blocking);
  if (failures.length) throw new ResultRuleError(failures);
  return { model, rules };
}

/** A short, stable fingerprint of a model (S10 a02): same input, same text. FNV-1a over canonical JSON. */
export function modelFingerprint(m: ResultModel): string {
  const json = JSON.stringify(m, Object.keys(m).sort());
  const full = JSON.stringify(m);
  let h = 0x811c9dc5;
  for (const ch of json + full) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

export interface InverterResultRow {
  acWiringKwh?: number;
  id: string;
  name: string;
  dcKwp: number;
  energyKwh: number;
  specificYield: number;
  clippingKwh: number;
  voltageThresholdKwh: number;
  startupThresholdKwh: number;
  /** USE1: energy lost to the MPPT operating-current limit, when the run records it. */
  currentLimitKwh?: number;
}

/** Use recorded results; a legacy singleton needs no new backend fields. */
export function inverterResultRows(view: ProjectView, run: SimulationRunRecord): InverterResultRow[] {
  const summary = run.summary_result;
  if (!summary) return [];
  if (summary.execution_breakdown) return summary.execution_breakdown.inverters.map((i) => ({
    id: i.inverter_instance_id, name: i.name, dcKwp: i.simulated_dc_nameplate_w / 1000,
    energyKwh: i.total_energy_wh / 1000, specificYield: i.specific_yield_wh_per_wp,
    clippingKwh: i.clipping_energy_wh / 1000, voltageThresholdKwh: i.voltage_threshold_energy_wh / 1000,
    startupThresholdKwh: i.startup_threshold_energy_wh / 1000,
    acWiringKwh: (i.loss_summary.find((l) => l.loss_type === "ac_wiring")?.lost_energy_wh ?? 0) / 1000,
    currentLimitKwh: (i.loss_summary.find((l) => l.loss_type === "mppt_current_limit")?.lost_energy_wh ?? 0) / 1000
  }));
  // Without a breakdown the row names and DC come from the design, so only the run's own design may supply them.
  if (runDesignBasis(view, run) !== "current") return [];
  const enabled = view.bundle.electrical_design.inverter_instances.filter((i) => i.enabled);
  if (enabled.length !== 1) return [];
  const inverter = enabled[0];
  const targets = new Set(inverter.mppt_instance_ids);
  const modules = new Set(view.bundle.electrical_design.strings.filter((s) => s.enabled && s.target_mppt_instance_id && targets.has(s.target_mppt_instance_id)).flatMap((s) => s.module_instance_ids));
  const pmp = new Map(view.catalog.modules.map((m) => [m.revision_id, moduleNameplateW(m)]));
  const dc = view.bundle.scene.module_instances.filter((m) => m.enabled && modules.has(m.module_instance_id)).reduce((total, m) => total + (pmp.get(modulePlacement(view, m.module_instance_id)?.revisionId ?? "") ?? 0), 0);
  const loss = (key: string) => summary.loss_summary.find((l) => l.loss_type === key)?.lost_energy_wh ?? 0;
  const recordedDcW = summary.resolved_loss_settings?.simulated_dc_nameplate_w ?? dc;
  const inverterWh = summary.total_energy_wh + loss("plant_ac_wiring") + loss("transformer_iron") + loss("transformer_copper") + loss("unavailability");
  return [{ id: inverter.inverter_instance_id, name: inverter.name, dcKwp: recordedDcW / 1000,
    energyKwh: inverterWh / 1000, specificYield: summary.resolved_loss_settings && recordedDcW > 0 ? inverterWh / recordedDcW : summary.specific_yield_wh_per_wp,
    clippingKwh: summary.clipping_energy_wh / 1000, voltageThresholdKwh: loss("mppt_voltage_threshold") / 1000,
    startupThresholdKwh: loss("inverter_power_threshold") / 1000, acWiringKwh: loss("ac_wiring") / 1000,
    currentLimitKwh: loss("mppt_current_limit") / 1000 }];
}
