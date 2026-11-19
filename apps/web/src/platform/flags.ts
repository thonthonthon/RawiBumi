/**
 * Feature flags for gradual release (for example a new module shown to TSE
 * users first). Defaults live here; the URL (`?flag=name` or `?flag=-name`)
 * can override them for testing. Phase 8 adds a server source.
 */
export type Flag = "module-registry-debug";

const DEFAULTS: Record<Flag, boolean> = {
  "module-registry-debug": false
};

function fromUrl(): Partial<Record<Flag, boolean>> {
  if (typeof window === "undefined") return {};
  const out: Partial<Record<Flag, boolean>> = {};
  for (const raw of new URLSearchParams(window.location.search).getAll("flag")) {
    const off = raw.startsWith("-");
    const name = (off ? raw.slice(1) : raw) as Flag;
    if (name in DEFAULTS) out[name] = !off;
  }
  return out;
}

const overrides = fromUrl();

export function flag(name: Flag): boolean {
  return overrides[name] ?? DEFAULTS[name];
}
