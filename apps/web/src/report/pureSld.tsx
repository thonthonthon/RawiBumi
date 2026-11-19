import type { KeyboardEvent } from "react";
import type { SldLayout, SldNode } from "../electrical/sldLayout";
import { symbol } from "../electrical/symbols";
import { SymbolGlyph } from "../electrical/symbols/SymbolGlyph";

const LINE = 14;

/** Bounding box of a placed symbol, from its viewBox. */
function box(n: SldNode) {
  const [vx, vy, vw, vh] = symbol(n.symbol).viewBox;
  return { x: n.x + vx, y: n.y + vy * n.stretch, w: vw, h: vh * n.stretch };
}

function Glyph({ x, y, state }: { x: number; y: number; state: SldNode["worst"] }) {
  if (state === "fail")
    return (
      <g className="sld__check sld__check--fail" aria-hidden="true">
        <circle cx={x} cy={y} r={5} />
        <rect x={x - 0.8} y={y - 3} width={1.6} height={3.6} className="sld__check-mark" />
        <rect x={x - 0.8} y={y + 1.6} width={1.6} height={1.4} className="sld__check-mark" />
      </g>
    );
  if (state === "warn") return <path className="sld__check sld__check--warn" d={`M ${x} ${y - 5.5} L ${x + 5.5} ${y + 4.5} L ${x - 5.5} ${y + 4.5} Z`} aria-hidden="true" />;
  return null;
}

export interface SldSvgProps {
  layout: SldLayout;
  zoom?: number;
  selected?: ReadonlyMap<string, "full" | "partial">;
  ariaLabel: string;
  stateLabel: (state: NonNullable<SldNode["worst"]>) => string;
  /** Interaction; omitted for the static drawing in the report. */
  onSelect?: (n: SldNode, add: boolean) => void;
  onKey?: (n: SldNode) => (e: KeyboardEvent) => void;
  onOpenPlan?: () => void;
  onClear?: () => void;
}

/**
 * The SLD drawing itself. The workstation view and the HTML report both render this
 * component (the report through `renderToStaticMarkup`), so they cannot differ (ADR 0016).
 */
export function SldSvg({ layout, zoom = 1, selected = new Map(), ariaLabel, stateLabel, onSelect, onKey, onOpenPlan, onClear }: SldSvgProps) {
  const interactive = !!onSelect;
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      width={layout.width * zoom}
      height={layout.height * zoom}
      className="sld__svg"
      role={interactive ? "group" : "img"}
      aria-label={ariaLabel}
      onClick={
        onClear
          ? (e) => {
              if (e.target === e.currentTarget) onClear();
            }
          : undefined
      }
    >
      {layout.wires.map((w) => (
        <polyline key={w.id} points={w.points.map((p) => p.join(",")).join(" ")} className="sld__wire" data-wire={w.id} />
      ))}
      {layout.nodes.map((n) => {
        const b = box(n);
        const state = selected.get(n.id);
        const clickable = interactive && n.moduleIds.length > 0;
        const lx = n.labelSide === "left" ? b.x - 6 : n.labelSide === "right" ? b.x + b.w + 6 : n.x;
        const anchor = n.labelSide === "left" ? "end" : n.labelSide === "right" ? "start" : "middle";
        const ly0 = n.labelSide === "above" ? b.y - 11 - (n.label.length - 1) * LINE : n.y - ((n.label.length - 1) * LINE) / 2;
        return (
          <g
            key={n.id}
            data-node={n.id}
            data-kind={n.kind}
            data-selected={state ?? "none"}
            className={["sld__node", n.muted ? "sld__node--muted" : "", clickable ? "sld__node--link" : "", state ? `sld__node--${state}` : ""].filter(Boolean).join(" ")}
            {...(clickable
              ? {
                  role: "button",
                  tabIndex: 0,
                  "aria-pressed": state === "full",
                  "aria-label": `${n.label.join(", ")}${n.worst && n.worst !== "pass" ? `, ${stateLabel(n.worst)}` : ""}`,
                  onClick: (e: React.MouseEvent) => {
                    e.stopPropagation();
                    onSelect!(n, e.shiftKey);
                  },
                  onDoubleClick: onOpenPlan,
                  onKeyDown: onKey?.(n)
                }
              : { "aria-hidden": true })}
          >
            {/* Outline symbols have no fill: this transparent box makes the whole symbol clickable. */}
            {clickable && <rect className="sld__hit" x={b.x - 3} y={b.y - 3} width={b.w + 6} height={b.h + 6} />}
            {state && <rect className="sld__sel" x={b.x - 3} y={b.y - 3} width={b.w + 6} height={b.h + 6} />}
            <g transform={`translate(${n.x} ${n.y})`}>
              <SymbolGlyph id={n.symbol} stretch={n.stretch} />
            </g>
            {n.label.map((line, i) => (
              <text key={i} x={lx} y={ly0 + i * LINE} textAnchor={anchor} dominantBaseline="middle" className={i === 0 ? "sld__txt" : "sld__small"}>
                {line}
              </text>
            ))}
            {n.kind !== "inverter" && <Glyph x={b.x + b.w + 8} y={b.y + 4} state={n.worst} />}
          </g>
        );
      })}
    </svg>
  );
}
