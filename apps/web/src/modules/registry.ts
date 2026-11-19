import { can } from "../platform/entitlements";
import type { Step } from "../state/store";
import { coreModule } from "./core";
import type { ModuleDef, StepDef } from "./types";

/**
 * Installed modules. A private or paid module is added here by its package's
 * entry point in the build that includes it (open-core mechanism: ADR index,
 * "paid-module mechanism under AGPL-3.0", still open).
 */
const MODULES: ModuleDef[] = [coreModule];

export function installedModules(): readonly ModuleDef[] {
  return [...MODULES].sort((a, b) => a.order - b.order);
}

/** Rail steps in order, filtered by entitlement. */
export function railSteps(): StepDef[] {
  return installedModules()
    .flatMap((m) => m.steps)
    .filter((s) => !s.feature || can(s.feature));
}

export function stepDef(id: Step): StepDef | undefined {
  return railSteps().find((s) => s.id === id);
}
