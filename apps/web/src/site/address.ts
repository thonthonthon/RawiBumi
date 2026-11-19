import { safeStorage } from "../shell/usePanes";

/**
 * The site address (F7.1, ADR 0016 amendment). Looked up online from the site coordinates,
 * then editable; a user's edit always wins and is never overwritten by a later lookup.
 *
 * Project storage is authoritative. Legacy browser values are copied once,
 * conditionally, when no project value exists. The lookup switch remains local.
 *
 * Lookup service: OpenStreetMap Nominatim by default. Its usage policy allows at most one
 * request per second, asks for the credit "© OpenStreetMap contributors", and does not allow
 * heavy use: fine while one person designs, not for a hosted service with many users. The
 * service is swappable at build time (VITE_GEOCODER_URL / VITE_GEOCODER_ATTRIBUTION /
 * VITE_GEOCODER_LABEL) and can be switched off (VITE_GEOCODER=off) or per browser.
 */

export interface SiteAddress {
  text: string;
  /** "lookup": from the lookup service, untouched. "user": typed or edited by the user. */
  source: "lookup" | "user";
  /** The coordinates the address was looked up or confirmed for. */
  lat: number;
  lon: number;
  /** Credit line of the lookup service, when the text came from it. */
  attribution: string | null;
  updatedAt: string;
}

export interface GeocoderConfig {
  label: string;
  /** Reverse lookup URL with {lat}, {lon} and {lang}. Must answer JSON in Nominatim's format. */
  urlTemplate: string;
  attribution: string;
  minIntervalMs: number;
}

export const NOMINATIM: GeocoderConfig = {
  label: "OpenStreetMap Nominatim",
  urlTemplate: "https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lon}&zoom=18&addressdetails=1&accept-language={lang}",
  attribution: "© OpenStreetMap contributors",
  minIntervalMs: 1100
};

type Env = Partial<Record<"VITE_GEOCODER" | "VITE_GEOCODER_URL" | "VITE_GEOCODER_ATTRIBUTION" | "VITE_GEOCODER_LABEL", string>>;

/** The configured lookup service, or null when lookup is switched off for this build. */
export function geocoderConfig(env: Env = import.meta.env as Env): GeocoderConfig | null {
  if (env.VITE_GEOCODER === "off") return null;
  if (!env.VITE_GEOCODER_URL) return NOMINATIM;
  return { label: env.VITE_GEOCODER_LABEL || "Custom geocoder", urlTemplate: env.VITE_GEOCODER_URL, attribution: env.VITE_GEOCODER_ATTRIBUTION || "", minIntervalMs: NOMINATIM.minIntervalMs };
}

/** Nominatim "address" parts, most specific first. Each group gives at most one part. */
const PART_GROUPS: string[][] = [
  ["neighbourhood", "hamlet", "village", "suburb", "quarter"],
  ["city_district", "district"],
  ["city", "town", "municipality", "county"],
  ["state"],
  ["postcode"],
  ["country"]
];

/** One line from a Nominatim reverse result: street, village/district, city, province, postcode, country. */
export function formatAddress(json: unknown): string | null {
  if (!json || typeof json !== "object") return null;
  const r = json as { address?: Record<string, string>; display_name?: string; error?: string };
  if (r.error) return null;
  const a = r.address;
  if (!a) return r.display_name?.trim() || null;
  const parts: string[] = [];
  const street = [a.road, a.house_number].filter(Boolean).join(" ");
  if (street) parts.push(street);
  for (const g of PART_GROUPS) {
    const k = g.find((x) => a[x]);
    if (k) parts.push(a[k]);
  }
  const out = parts.map((p) => p.trim()).filter((p, i, xs) => p && p !== xs[i - 1]);
  return out.length ? out.join(", ") : r.display_name?.trim() || null;
}

let lastRequest = 0;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Test hook: forget the last request time. */
export function resetGeocoderClock(): void {
  lastRequest = 0;
}

/** Reverse lookup, at most one request per `minIntervalMs` from this page. Throws on failure. */
export async function reverseGeocode(cfg: GeocoderConfig, lat: number, lon: number, lang: string, fetchImpl: typeof fetch = fetch, signal?: AbortSignal): Promise<string> {
  const wait = lastRequest + cfg.minIntervalMs - Date.now();
  if (wait > 0) await sleep(wait);
  lastRequest = Date.now();
  const url = cfg.urlTemplate
    .replace("{lat}", encodeURIComponent(lat.toFixed(6)))
    .replace("{lon}", encodeURIComponent(lon.toFixed(6)))
    .replace("{lang}", encodeURIComponent(lang));
  const res = await fetchImpl(url, { signal, headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`Address lookup failed: HTTP ${res.status}`);
  const text = formatAddress(await res.json());
  if (!text) throw new Error("Address lookup found no address for these coordinates.");
  return text;
}

const SAME = 1e-6;
export const sameCoords = (a: { lat: number; lon: number }, lat: number, lon: number) => Math.abs(a.lat - lat) < SAME && Math.abs(a.lon - lon) < SAME;

/** Whether an automatic lookup should run: no address yet, or a looked-up one for other coordinates. Never over a user's edit. */
export function needsLookup(a: SiteAddress | null, lat: number, lon: number): boolean {
  if (!a) return true;
  return a.source === "lookup" && !sameCoords(a, lat, lon);
}

const key = (projectId: string) => `rawibumi.siteAddress.${projectId}`;
const LOOKUP_KEY = "rawibumi.addressLookup";

export function loadAddress(projectId: string): SiteAddress | null {
  try {
    const raw = safeStorage.getItem(key(projectId));
    if (!raw) return null;
    const a = JSON.parse(raw) as SiteAddress;
    return typeof a?.text === "string" && (a.source === "lookup" || a.source === "user") ? a : null;
  } catch {
    return null;
  }
}

export function saveAddress(projectId: string, a: SiteAddress): void {
  safeStorage.setItem(key(projectId), JSON.stringify(a));
}

/** Per-browser switch: the user may turn the online lookup off (it sends the coordinates to the service). */
export function lookupAllowed(): boolean {
  return safeStorage.getItem(LOOKUP_KEY) !== "off";
}

export function setLookupAllowed(on: boolean): void {
  safeStorage.setItem(LOOKUP_KEY, on ? "on" : "off");
}

// Shared migration/write boundary: a server-side conditional copy prevents two tabs
// from overwriting project data with an old browser value.
const siteLoads = new Map<string, Promise<unknown>>();
const siteWrites = new Map<string, Promise<unknown>>();
type Site = import("../types").ProjectView["bundle"]["project"]["site"];
async function writeProjectSite(projectId: string, changes: import("../types").ReportSiteChanges) {
  const operation = (siteWrites.get(projectId) ?? Promise.resolve()).catch(() => {}).then(async () => {
    const { engine } = await import("../client");
    const view = await engine.updateSiteDetails(projectId, changes);
    const { uiStore } = await import("../state/store");
    const current = uiStore.getState().state.view;
    if (current?.bundle.project.project_id === projectId) {
      // A late metadata response must not replace newer design or history state.
      const site = { ...current.bundle.project.site };
      for (const field of ["address", "installation"] as const)
        if (field in view.bundle.project.site) Object.assign(site, { [field]: view.bundle.project.site[field] });
      uiStore.getState().dispatch({type:"setView",view:{...current,bundle:{...current.bundle,
        project:{...current.bundle.project,site}}}});
    }
    return view;
  });
  siteWrites.set(projectId, operation);
  try { return await operation; } finally { if (siteWrites.get(projectId) === operation) siteWrites.delete(projectId); }
}
export async function loadProjectSiteDetail<K extends "address" | "installation">(projectId: string, field: K, legacy: Site[K]): Promise<Site[K]> {
  const key = `${projectId}/${field}`;
  const pending = siteLoads.get(key); if (pending) return pending as Promise<Site[K]>;
  const operation = (async () => {
    await siteWrites.get(projectId);
    const { engine } = await import("../client");
    const { uiStore } = await import("../state/store");
    const current = uiStore.getState().state.view;
    let view = current?.bundle.project.project_id === projectId ? current : await engine.project(projectId);
    if (!(field in view.bundle.project.site) && legacy != null) {
      view = await writeProjectSite(projectId, { [field]: legacy, copy_if_missing: true });
    }
    return view.bundle.project.site[field];
  })();
  siteLoads.set(key, operation);
  try { return await operation; } finally { siteLoads.delete(key); }
}
export async function saveProjectSiteDetail<K extends "address" | "installation">(projectId: string, field: K, value: Site[K]): Promise<void> {
  await writeProjectSite(projectId, { [field]: value });
}
export async function loadProjectAddress(projectId: string): Promise<SiteAddress | null> {
  return (await loadProjectSiteDetail(projectId, "address", loadAddress(projectId))) ?? null;
}
export function saveProjectAddress(projectId: string, value: SiteAddress): Promise<void> {
  return saveProjectSiteDetail(projectId, "address", value);
}
