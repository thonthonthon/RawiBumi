/**
 * The custom imagery provider (DEC-U2, bring your own key). Browser-level: it serves the landing map and every
 * project. The key lives only in this browser's storage under CREDENTIAL_REFERENCE and is never sent to the
 * engine; projects store the template (with {key}), the attribution and the reference.
 */
export const CREDENTIAL_REFERENCE = "browser-key:custom-imagery";
const PROVIDER_KEY = "rawibumi.imagery.provider";
const keyStorageName = (reference: string) => `rawibumi.imagery.key.${reference}`;

export interface ImageryProvider { name: string; tileUrlTemplate: string; attribution: string; termsAccepted: boolean }

// Storage can be missing or throw (private windows, blocked site data); the page keeps working from memory.
const memory = new Map<string, string>();
function read(name: string): string | null {
  try { const v = window.localStorage.getItem(name); if (v !== null) return v; } catch { /* fall back to memory */ }
  return memory.get(name) ?? null;
}
function write(name: string, value: string | null) {
  if (value === null) memory.delete(name); else memory.set(name, value);
  try { if (value === null) window.localStorage.removeItem(name); else window.localStorage.setItem(name, value); } catch { /* memory only */ }
  if (typeof window !== "undefined") window.dispatchEvent(new Event("rawibumi:imagery-provider"));
}

export function loadProvider(): ImageryProvider | null {
  const raw = read(PROVIDER_KEY);
  if (!raw) return null;
  try {
    const p = JSON.parse(raw) as ImageryProvider;
    return typeof p.tileUrlTemplate === "string" && typeof p.attribution === "string" ? { name: p.name || "Custom imagery", tileUrlTemplate: p.tileUrlTemplate, attribution: p.attribution, termsAccepted: !!p.termsAccepted } : null;
  } catch { return null; }
}
export const saveProvider = (p: ImageryProvider | null) => write(PROVIDER_KEY, p ? JSON.stringify(p) : null);
export const loadKey = (reference = CREDENTIAL_REFERENCE) => read(keyStorageName(reference)) ?? "";
export const saveKey = (key: string, reference = CREDENTIAL_REFERENCE) => write(keyStorageName(reference), key || null);

/** Why a template can't be used, or null. Mirrors the engine's rule: https, {z}/{x}/{y}, and {key} instead of a literal key. */
export function templateProblem(template: string): string | null {
  if (!template.startsWith("https://")) return "imagery.needsHttps";
  if (!["{z}", "{x}", "{y}"].every((t) => template.includes(t))) return "imagery.needsZxy";
  if (/[?&](key|apikey|api_key|token|access_token)=(?!\{key\})[^&]+/i.test(template)) return "imagery.literalKey";
  return null;
}

/** The provider is usable for display: a valid template, accepted terms, and a key if the template asks for one. */
export function providerReady(p: ImageryProvider | null, key = loadKey()): p is ImageryProvider {
  return !!p && p.termsAccepted && !templateProblem(p.tileUrlTemplate) && (!p.tileUrlTemplate.includes("{key}") || !!key);
}

export function tileUrl(template: string, z: number, x: number, y: number, key: string): string {
  return template.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y)).replace("{key}", encodeURIComponent(key));
}
