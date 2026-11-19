/**
 * Parser for the in-house symbol files (ADR 0004, ADR 0015). The files use a small,
 * fixed subset of SVG so they can be read the same way in the browser and in Node tests,
 * and rendered as React elements without injecting markup:
 * - root `<svg viewBox data-symbol data-name data-iec [data-stretch]>`;
 * - drawing elements `line`, `rect`, `circle`, `polyline`, `polygon`, `path`, `text`, styled only by class;
 * - terminals as `<circle data-terminal="name" cx cy r="0"/>` (not drawn);
 * - `<metadata>` and comments are ignored (ADR 0015 amendment, F7).
 */

export type SymbolTag = "line" | "rect" | "circle" | "polyline" | "polygon" | "path" | "text";

export interface SymbolElement {
  tag: SymbolTag;
  attrs: Record<string, string>;
  text?: string;
}

export interface SymbolDef {
  id: string;
  name: string;
  /** IEC 60617 reference, or "to confirm" until checked against the standard. */
  iec: string;
  viewBox: [number, number, number, number];
  /** Axis along which the layout may stretch the symbol (busbar only). */
  stretch: "y" | null;
  elements: SymbolElement[];
  terminals: Record<string, [number, number]>;
}

const TAGS = new Set<SymbolTag>(["line", "rect", "circle", "polyline", "polygon", "path", "text"]);
export const ALLOWED_ATTRS = new Set(["x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "width", "height", "d", "points", "class", "text-anchor", "dominant-baseline"]);
export const ALLOWED_CLASSES = new Set(["sym__line", "sym__fill", "sym__bus", "sym__txt", "sym__txt--small"]);

const ATTR = /([\w:-]+)="([^"]*)"/g;

function attrsOf(s: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of s.matchAll(ATTR)) out[m[1]] = m[2];
  return out;
}

export class SymbolParseError extends Error {}

export function parseSymbol(source: string): SymbolDef {
  const root = /<svg\b([^>]*)>([\s\S]*)<\/svg>/.exec(source);
  if (!root) throw new SymbolParseError("No <svg> root.");
  const ra = attrsOf(root[1]);
  const id = ra["data-symbol"];
  if (!id) throw new SymbolParseError("Root needs data-symbol.");
  const vb = (ra.viewBox ?? "").trim().split(/[\s,]+/).map(Number);
  if (vb.length !== 4 || vb.some((n) => !Number.isFinite(n))) throw new SymbolParseError(`${id}: bad viewBox.`);
  const elements: SymbolElement[] = [];
  const terminals: Record<string, [number, number]> = {};
  // Comments and <metadata> are not drawing: file signing (for example a C2PA content-credentials
  // manifest added on delivery) or an editor may put information there. Both are ignored.
  const body = root[2].replace(/<!--[\s\S]*?-->/g, "").replace(/<metadata\b[\s\S]*?<\/metadata>/g, "");
  const EL = /<(\w+)\b([^>]*?)(?:\/>|>([^<]*)<\/\1>)/g;
  for (const m of body.matchAll(EL)) {
    const tag = m[1] as SymbolTag;
    if (!TAGS.has(tag)) throw new SymbolParseError(`${id}: <${m[1]}> is not allowed in a symbol.`);
    const a = attrsOf(m[2]);
    if (a["data-terminal"]) {
      terminals[a["data-terminal"]] = [Number(a.cx), Number(a.cy)];
      continue;
    }
    for (const k of Object.keys(a)) if (!ALLOWED_ATTRS.has(k)) throw new SymbolParseError(`${id}: attribute ${k} is not allowed (style by class only).`);
    for (const c of (a.class ?? "").split(/\s+/).filter(Boolean)) if (!ALLOWED_CLASSES.has(c)) throw new SymbolParseError(`${id}: class ${c} is not allowed.`);
    elements.push(tag === "text" ? { tag, attrs: a, text: (m[3] ?? "").trim() } : { tag, attrs: a });
  }
  // Anything left over that is not whitespace is markup the parser did not understand.
  if (body.replace(EL, "").trim()) throw new SymbolParseError(`${id}: unparsed markup.`);
  if (!Object.keys(terminals).length) throw new SymbolParseError(`${id}: no terminals.`);
  return {
    id,
    name: ra["data-name"] ?? id,
    iec: ra["data-iec"] ?? "to confirm",
    viewBox: vb as [number, number, number, number],
    stretch: ra["data-stretch"] === "y" ? "y" : null,
    elements,
    terminals
  };
}
