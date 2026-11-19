import { parseSymbol, type SymbolDef } from "./parse";

/**
 * The in-house IEC 60617 symbol library (plan A6, ADR 0004, ADR 0015). One SVG file per
 * symbol in this folder is the single source: the SLD and the symbol sheet both draw from it.
 */
const files = import.meta.glob("./*.svg", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

export const SYMBOLS: Readonly<Record<string, SymbolDef>> = Object.fromEntries(
  Object.values(files)
    .map(parseSymbol)
    .map((s) => [s.id, s] as const)
);

/** Order on the symbol sheet: DC side, conversion, AC side, then earth. */
export const SHEET_ORDER = ["pv-string", "combiner", "fuse", "dc-isolator", "spd", "mppt-input", "inverter", "ac-breaker", "busbar", "meter", "transformer", "grid", "load", "earth"] as const;

export type SymbolId = (typeof SHEET_ORDER)[number];

export function symbol(id: SymbolId): SymbolDef {
  const s = SYMBOLS[id];
  if (!s) throw new Error(`Symbol ${id} is missing from src/electrical/symbols/.`);
  return s;
}

/** World position of a terminal of a symbol placed at (x, y); `stretch` scales a stretchable symbol along y. */
export function terminalAt(id: SymbolId, name: string, x: number, y: number, stretch = 1): [number, number] {
  const t = symbol(id).terminals[name];
  if (!t) throw new Error(`Symbol ${id} has no terminal ${name}.`);
  return [x + t[0], y + t[1] * stretch];
}

export type { SymbolDef } from "./parse";
