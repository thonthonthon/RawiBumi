import type { ReactNode } from "react";
import type { Feature } from "../platform/entitlements";
import type { Step } from "../state/store";

/** What a step's panel can ask of the shell. */
export interface StepContext {
  openImport: (category: "geometry" | "components" | "meteo") => void;
}

export interface StepDef {
  /** Core steps use the Step union; a module that adds steps widens it in its ADR. */
  id: Step;
  shortcut?: "0" | "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9";
  /** i18n key of the rail label, e.g. "steps.layout". */
  labelKey: string;
  /** "workspace": task panel + stage + inspector. "full": the step owns the whole area. */
  layout: "workspace" | "full";
  /** Task panel (workspace layout) or the full view (full layout). */
  render: (ctx: StepContext) => ReactNode;
  /** Hidden unless `can(feature)` is true. */
  feature?: Feature;
}

/**
 * A module contributes rail steps (and, from F7, result tabs and report
 * chapters). New engines (Hybrid, Load, Grid, Uncertainty, BOQ, FinMod) plug in
 * here instead of editing the shell. See docs/adr/0008-shell-and-module-registry.md.
 */
export interface ModuleDef {
  id: string;
  /** Lower comes first in the rail. Core uses 0–99. */
  order: number;
  steps: StepDef[];
}
