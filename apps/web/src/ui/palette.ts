/**
 * Token access for code that cannot use CSS variables directly (Canvas2D,
 * MapLibre paint properties, WebGL from F2). Values are read once from
 * src/ui/tokens.css, so tokens.json stays the single source of colour.
 */
const cache = new Map<string, string>();

/** Value of `--rb-<name>`, e.g. token("role-stage-bg") or token("color-mppt-screen-3"). */
export function token(name: string): string {
  const hit = cache.get(name);
  if (hit !== undefined) return hit;
  const value = typeof document === "undefined" ? "" : getComputedStyle(document.documentElement).getPropertyValue(`--rb-${name}`).trim();
  if (value) cache.set(name, value);
  return value;
}

/** A token colour (hex) with an alpha channel, for translucent canvas fills. */
export function alpha(name: string, a: number): string {
  const hex = token(name).replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(hex)) return token(name);
  const n = parseInt(hex, 16);
  return `rgb(${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255} / ${a})`;
}

/** MPPT group colour on the graphite stage (cool hues; repeats after 8). */
export function mpptColor(index: number): string {
  return token(`color-mppt-screen-${(index % 8) + 1}`);
}

/** Canvas font string in the drawing lettering (osifont). */
export function drawingFont(px: number, weight = 400): string {
  return `${weight} ${px}px ${token("font-drawing") || "osifont, sans-serif"}`;
}

/** A token colour as an [r, g, b] triple (0–255), for pixel buffers. */
export function rgbOf(name: string): [number, number, number] {
  const hex = token(name).replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(hex)) return [0, 0, 0];
  const n = parseInt(hex, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
