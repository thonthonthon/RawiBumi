import { EMPTY_SYSTEM, INSTALLATION_TYPES, type SystemInfo, type InstallationType } from "../report/presentation";
export { EMPTY_SYSTEM, INSTALLATION_TYPES, beyondSimulation, formatEnergy, formatPower, formatPvCapacity, type SystemInfo, type InstallationType } from "../report/presentation";
import { useEffect, useSyncExternalStore } from "react";
import { loadProjectSiteDetail, saveProjectSiteDetail } from "./address";
import { safeStorage } from "../shell/usePanes";

/**
 * System summary for the report cover (F7.2, owner's direction 22 Oct): installation type and
 * BESS (battery energy storage system) capacity. PV capacity is not entered here: it comes from
 * the design (catalogue Pmp of the placed modules).
 *
 * These are the user's statements, not simulation inputs. The engine simulates grid-connected PV
 * only; it has no battery, off-grid or export-limit model. The report says so wherever these
 * values could suggest otherwise. Stored in the project; legacy browser values are copied once when absent.
 */

const key = (projectId: string) => `rawibumi.systemInfo.${projectId}`;
const okNum = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) && x >= 0 ? x : null);

export function loadSystem(projectId: string): SystemInfo {
  try {
    const raw = safeStorage.getItem(key(projectId));
    if (!raw) return EMPTY_SYSTEM;
    const s = JSON.parse(raw) as Partial<SystemInfo>;
    return {
      installationType: INSTALLATION_TYPES.includes(s.installationType as InstallationType) ? (s.installationType as InstallationType) : null,
      bessEnergyKwh: okNum(s.bessEnergyKwh),
      bessPowerKw: okNum(s.bessPowerKw)
    };
  } catch {
    return EMPTY_SYSTEM;
  }
}

// Shared per-project state, so the Site panel and the report agree.
const entries = new Map<string, SystemInfo>();
const listeners = new Set<() => void>();
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
const entryOf = (projectId: string) => {
  let e = entries.get(projectId);
  if (!e) {
    e = loadSystem(projectId);
    entries.set(projectId, e);
  }
  return e;
};

/** Test hook. */
export function resetSystemState(): void {
  entries.clear();
  listeners.forEach((l) => l());
}

export async function loadProjectSystem(projectId: string): Promise<SystemInfo> {
  const legacy = safeStorage.getItem(key(projectId)) ? loadSystem(projectId) : undefined;
  return (await loadProjectSiteDetail(projectId, "installation", legacy)) ?? EMPTY_SYSTEM;
}

export function useSystemInfo(projectId: string): [SystemInfo, (patch: Partial<SystemInfo>) => void] {
  const s = useSyncExternalStore(subscribe, () => entryOf(projectId));
  useEffect(() => {
    let active = true;
    const initial = entryOf(projectId);
    void loadProjectSystem(projectId).then(value => { if (active && entryOf(projectId) === initial) { entries.set(projectId, value); listeners.forEach(l => l()); } })
      .catch(async error => { const { uiStore } = await import("../state/store"); uiStore.getState().toast("error", String(error)); });
    return () => { active = false; };
  }, [projectId]);
  const set = (patch: Partial<SystemInfo>) => {
    const next = { ...entryOf(projectId), ...patch };
    entries.set(projectId, next);
    void saveProjectSiteDetail(projectId, "installation", next).catch(async error => { const { uiStore } = await import("../state/store"); uiStore.getState().toast("error", String(error)); });
    listeners.forEach((l) => l());
  };
  return [s, set];
}
