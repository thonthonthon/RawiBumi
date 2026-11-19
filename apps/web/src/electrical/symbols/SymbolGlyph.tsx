import { createElement } from "react";
import { symbol, type SymbolId } from "./index";

const ATTR_NAMES: Record<string, string> = {
  class: "className",
  "text-anchor": "textAnchor",
  "dominant-baseline": "dominantBaseline",
  x1: "x1",
  y1: "y1",
  x2: "x2",
  y2: "y2"
};

/**
 * Draws one library symbol as SVG elements, centred on its origin. The SLD places it with
 * a translate; the symbol sheet draws the same component, so the two cannot differ.
 * `stretch` scales a stretchable symbol (the busbar) along y, keeping its stroke width.
 */
export function SymbolGlyph({ id, stretch = 1 }: { id: SymbolId; stretch?: number }) {
  const s = symbol(id);
  return (
    <g data-symbol-body={id}>
      {s.elements.map((e, i) => {
        const props: Record<string, string | number> = { key: i };
        for (const [k, v] of Object.entries(e.attrs)) {
          const name = ATTR_NAMES[k] ?? k;
          props[name] = s.stretch === "y" && stretch !== 1 && (k === "y1" || k === "y2" || k === "y" || k === "cy") ? Number(v) * stretch : v;
        }
        return createElement(e.tag, props, e.text);
      })}
    </g>
  );
}
