import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";
import { geocoderConfig, loadAddress, lookupAllowed, needsLookup, reverseGeocode, loadProjectAddress, saveProjectAddress, setLookupAllowed, type SiteAddress } from "./address";

/**
 * Shared site-address state for the Site panel and the report (F7.1): one entry per project,
 * so a lookup started in one place shows in the other. See address.ts for where it is kept.
 */

export type AddressStatus = "idle" | "looking" | "saving" | "failed";

interface Entry {
  address: SiteAddress | null;
  status: AddressStatus;
  error: string | null;
  /** Coordinates of the last failed automatic lookup: not retried automatically. */
  failedFor: string | null;
  loaded: boolean;
}

const entries = new Map<string, Entry>();
const listeners = new Set<() => void>();
let allowed = lookupAllowed();

const emit = () => listeners.forEach((l) => l());
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
const entryOf = (projectId: string): Entry => {
  let e = entries.get(projectId);
  if (!e) {
    e = { address: loadAddress(projectId), status: "idle", error: null, failedFor: null, loaded: false };
    entries.set(projectId, e);
  }
  return e;
};
const put = (projectId: string, patch: Partial<Entry>) => {
  entries.set(projectId, { ...entryOf(projectId), ...patch });
  emit();
};
const coordKey = (lat: number, lon: number) => `${lat.toFixed(6)},${lon.toFixed(6)}`;

/** Test hook: forget every project's state and re-read the per-browser switch. */
export function resetSiteAddressState(): void {
  entries.clear();
  allowed = lookupAllowed();
  emit();
}

export interface SiteAddressApi {
  address: SiteAddress | null;
  status: AddressStatus;
  error: string | null;
  /** False when this build has no lookup service. */
  available: boolean;
  /** The user's per-browser switch for the online lookup. */
  allowed: boolean;
  serviceLabel: string | null;
  setAllowed: (on: boolean) => void;
  /** The user types or edits the address: it becomes theirs and no lookup replaces it. */
  setText: (text: string) => void;
  /** Look the address up again now, replacing the current text. */
  lookupNow: () => void;
}

export function useSiteAddress(projectId: string, lat: number, lon: number, lang: string): SiteAddressApi {
  const entry = useSyncExternalStore(subscribe, () => entryOf(projectId));
  const isAllowed = useSyncExternalStore(subscribe, () => allowed);
  const cfg = useMemo(() => geocoderConfig(), []);

  const lookup = useCallback(
    async (force: boolean) => {
      if (!cfg) return;
      const at = coordKey(lat, lon);
      put(projectId, { status: "looking", error: null });
      try {
        const text = await reverseGeocode(cfg, lat, lon, lang);
        const now = entryOf(projectId).address;
        // A user's edit made while the lookup was running wins, unless the user asked for this lookup.
        if (!force && now?.source === "user") put(projectId, { status: "idle" });
        else {
          const a: SiteAddress = { text, source: "lookup", lat, lon, attribution: cfg.attribution || null, updatedAt: new Date().toISOString() };
          await saveProjectAddress(projectId, a);
          put(projectId, { address: a, status: "idle", failedFor: null });
        }
      } catch (e) {
        put(projectId, { status: "failed", error: (e as Error).message, failedFor: at });
      }
    },
    [cfg, projectId, lat, lon, lang]
  );

  useEffect(() => {
    let active = true;
    const initial = entryOf(projectId).address;
    put(projectId, { status: "looking" });
    void loadProjectAddress(projectId).then(address => {
      if (active) {
        const current = entryOf(projectId);
        if (current.address !== initial && current.address?.source === "user") put(projectId, { loaded: true });
        else put(projectId, { address, status: "idle", loaded: true });
      }
    }).catch(error => { if (active) put(projectId, { status: "failed", error: String(error) }); });
    return () => { active = false; };
  }, [projectId]);

  useEffect(() => {
    // Read the live entry, not this render's copy: a second effect run (React strict mode, or the
    // Site panel and the report mounting together) must see a lookup already in flight.
    const live = entryOf(projectId);
    if (!live.loaded || !cfg || !isAllowed || live.status === "looking") return;
    if (live.failedFor === coordKey(lat, lon)) return;
    if (needsLookup(live.address, lat, lon)) void lookup(false);
  }, [cfg, isAllowed, entry, projectId, lat, lon, lookup]);

  return {
    address: entry.address,
    status: entry.status,
    error: entry.error,
    available: !!cfg,
    allowed: isAllowed,
    serviceLabel: cfg?.label ?? null,
    setAllowed: (on) => {
      setLookupAllowed(on);
      allowed = on;
      emit();
    },
    setText: (text) => {
      const prev = entryOf(projectId).address;
      const a: SiteAddress = { text, source: "user", lat, lon, attribution: prev?.attribution ?? null, updatedAt: new Date().toISOString() };
      put(projectId, { address: a, status: "saving" });
      void saveProjectAddress(projectId, a).then(() => { if (entryOf(projectId).address === a) put(projectId, {status:"idle"}); })
        .catch(error => put(projectId, { status: "failed", error: String(error) }));
    },
    lookupNow: () => void lookup(true)
  };
}
