/**
 * Per-inverter MPPT/input notation (UI spec §6.8.2).
 *   "16,0 ; 16,0 ; 16,0 ; 14,14"   → 4 MPPTs × 2 inputs, 76 modules
 *   "3x(16,0); 14,14"              → repeat shorthand (x, X or ×)
 * Semicolon separates MPPTs, comma separates inputs on one MPPT, 0 = empty input.
 */
export interface MpptLayout {
  mppts: number[][];
}

export interface NotationIssue {
  severity: "blocking" | "warning" | "info";
  code: string;
  message: string;
  mppt?: number;
}

export interface ParseResult {
  layout: MpptLayout | null;
  issues: NotationIssue[];
}

export function parseNotation(text: string): ParseResult {
  const issues: NotationIssue[] = [];
  const cleaned = text.replace(/\s+/g, "");
  if (!cleaned)
    return { layout: null, issues: [{ severity: "info", code: "empty", message: "Enter a layout, e.g. 16,0;16,0;16,0;14,14" }] };
  const mppts: number[][] = [];
  const parts = cleaned.split(";").filter((p) => p.length > 0);
  for (const part of parts) {
    const rep = part.match(/^(\d+)[x×X]\((.+)\)$/);
    const count = rep ? Number(rep[1]) : 1;
    const body = rep ? rep[2] : part.replace(/^\((.*)\)$/, "$1");
    const values: number[] = [];
    for (const v of body.split(",")) {
      if (!/^\d+$/.test(v)) {
        issues.push({ severity: "blocking", code: "syntax", message: `"${v}" is not a whole number of modules.` });
        return { layout: null, issues };
      }
      values.push(Number(v));
    }
    if (count < 1 || count > 64) {
      issues.push({ severity: "blocking", code: "repeat", message: `Repeat count ${count} is out of range (1–64).` });
      return { layout: null, issues };
    }
    for (let i = 0; i < count; i++) mppts.push([...values]);
  }
  return { layout: { mppts }, issues };
}

export function formatNotation(layout: MpptLayout): string {
  return layout.mppts.map((m) => m.join(",")).join(" ; ");
}

export function totalModules(layout: MpptLayout): number {
  return layout.mppts.reduce((t, m) => t + m.reduce((a, b) => a + b, 0), 0);
}

export function stringCount(layout: MpptLayout): number {
  return layout.mppts.reduce((t, m) => t + m.filter((v) => v > 0).length, 0);
}

export interface LayoutCheckInput {
  layout: MpptLayout;
  mpptCount: number | null;
  inputsPerMppt: number | null;
  modulesAvailable: number | null;
  unequalParallelPolicy: "warning" | "blocking";
}

export interface LayoutCheck {
  id: string;
  label: string;
  state: "pass" | "fail" | "warn" | "unavailable";
  detail: string;
}

export function checkLayout(input: LayoutCheckInput): { checks: LayoutCheck[]; issues: NotationIssue[] } {
  const { layout } = input;
  const checks: LayoutCheck[] = [];
  const issues: NotationIssue[] = [];

  if (input.mpptCount == null) {
    checks.push({ id: "mppt_count", label: "MPPT count", state: "unavailable", detail: "Inverter definition has no MPPT count." });
  } else if (layout.mppts.length !== input.mpptCount) {
    checks.push({ id: "mppt_count", label: "MPPT count", state: "fail", detail: `Layout has ${layout.mppts.length} groups; inverter has ${input.mpptCount}.` });
    issues.push({ severity: "blocking", code: "mppt_count", message: `Layout defines ${layout.mppts.length} MPPTs; the inverter has ${input.mpptCount}.` });
  } else {
    checks.push({ id: "mppt_count", label: "MPPT count", state: "pass", detail: `${input.mpptCount} MPPTs` });
  }

  if (input.inputsPerMppt == null) {
    checks.push({ id: "inputs", label: "Inputs per MPPT", state: "unavailable", detail: "Not in the inverter definition. Enter it with a source." });
  } else {
    const over = layout.mppts.findIndex((m) => m.length > input.inputsPerMppt!);
    if (over >= 0) {
      checks.push({ id: "inputs", label: "Inputs per MPPT", state: "fail", detail: `MPPT ${over + 1} uses ${layout.mppts[over].length}; only ${input.inputsPerMppt} exist.` });
      issues.push({ severity: "blocking", code: "inputs", mppt: over, message: `MPPT ${over + 1} uses more inputs than the inverter has.` });
    } else checks.push({ id: "inputs", label: "Inputs per MPPT", state: "pass", detail: `≤ ${input.inputsPerMppt} per MPPT` });
  }

  const total = totalModules(layout);
  if (input.modulesAvailable == null) {
    checks.push({ id: "count", label: "Module count", state: "unavailable", detail: `${total} configured. Pair a PV field to compare.` });
  } else if (total !== input.modulesAvailable) {
    checks.push({ id: "count", label: "Module count", state: "fail", detail: `${total} configured vs ${input.modulesAvailable} on paired fields` });
    issues.push({ severity: "blocking", code: "count", message: `Σ string lengths (${total}) ≠ modules on paired fields (${input.modulesAvailable}).` });
  } else {
    checks.push({ id: "count", label: "Module count", state: "pass", detail: `${total} = ${input.modulesAvailable}` });
  }

  const unequal = layout.mppts.map((m, i) => ({ i, lens: m.filter((v) => v > 0) })).filter((m) => new Set(m.lens).size > 1);
  if (unequal.length === 0) checks.push({ id: "parallel", label: "Parallel strings", state: "pass", detail: "Equal lengths on every MPPT" });
  else {
    checks.push({
      id: "parallel",
      label: "Parallel strings",
      state: input.unequalParallelPolicy === "blocking" ? "fail" : "warn",
      detail: `Unequal on MPPT ${unequal.map((u) => u.i + 1).join(", ")}`
    });
    for (const u of unequal)
      issues.push({ severity: input.unequalParallelPolicy, code: "parallel", mppt: u.i, message: `MPPT ${u.i + 1}: parallel strings of unequal length (${u.lens.join(", ")}).` });
  }

  const emptyMppts = layout.mppts.map((m, i) => (m.every((v) => v === 0) ? i + 1 : 0)).filter(Boolean);
  if (emptyMppts.length) issues.push({ severity: "info", code: "empty_mppt", message: `MPPT ${emptyMppts.join(", ")} unused.` });

  checks.push({ id: "voc", label: "Cold Voc ≤ inverter max", state: "unavailable", detail: "Engine rule (4.7); check endpoint not wired" });
  checks.push({ id: "vmp", label: "Vmp inside MPPT window", state: "unavailable", detail: "Engine rule (4.7); check endpoint not wired" });
  checks.push({ id: "current", label: "MPPT current (Imp, Isc)", state: "unavailable", detail: "Engine rule; limit may be missing from the OND" });
  return { checks, issues };
}
