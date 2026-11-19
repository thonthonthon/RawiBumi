import { useMemo, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { useActions, useUI } from "../state/store";
import { Paid } from "../ui/kit";
import { layoutSld, selectionState, type SldNode } from "./sldLayout";
import { SldSvg } from "../report/pureSld";
export { SldSvg, type SldSvgProps } from "../report/pureSld";
import { SymbolSheet } from "./SymbolSheet";

const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2] as const;
/**
 * Single-line diagram (F6, plan B7, ADR 0015). Generated from the engine's assignment by
 * `layoutSld`; every symbol comes from the in-house library, the same component the
 * symbol sheet draws. Selection is shared with the plan both ways.
 */
export function Sld() {
  const { t } = useTranslation();
  const { dispatch } = useActions();
  const view = useUI((s) => s.view);
  const selection = useUI((s) => s.selection);
  const [zoom, setZoom] = useState<number>(1);
  const [sheet, setSheet] = useState(false);
  const layout = useMemo(() => (view ? layoutSld(view, t) : null), [view, t]);
  const selected = useMemo(() => (layout ? selectionState(layout, selection) : new Map()), [layout, selection]);
  if (!view || !layout) return null;

  const select = (n: SldNode, add: boolean) => {
    if (!n.moduleIds.length) return;
    dispatch({ type: "select", ids: add ? [...new Set([...selection, ...n.moduleIds])] : n.moduleIds });
  };
  const onKey = (n: SldNode) => (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      select(n, e.shiftKey);
    } else if (e.key === "Escape") dispatch({ type: "select", ids: [] });
  };
  const zi = ZOOMS.indexOf(zoom as (typeof ZOOMS)[number]);

  return (
    <div className="sld">
      <div className="sld__head">
        <strong>{t("sld.title")}</strong>
        <span className="sub">{t("sld.freeNote")}</span> <Paid what={t("sld.full")} />
        <span className="sld__spacer" />
        <div className="sld__tools" role="toolbar" aria-label={t("sld.toolbar")}>
          <button type="button" className="btn btn--sm btn--stage" onClick={() => setZoom(ZOOMS[Math.max(0, zi - 1)])} disabled={zi <= 0} aria-label={t("sld.zoomOut")}>
            −
          </button>
          <span className="sld__zoom" aria-live="polite">
            {Math.round(zoom * 100)} %
          </span>
          <button type="button" className="btn btn--sm btn--stage" onClick={() => setZoom(ZOOMS[Math.min(ZOOMS.length - 1, zi + 1)])} disabled={zi >= ZOOMS.length - 1} aria-label={t("sld.zoomIn")}>
            +
          </button>
          <button type="button" className="btn btn--sm btn--stage" aria-pressed={sheet} onClick={() => setSheet(!sheet)}>
            {t("sld.symbolSheet")}
          </button>
        </div>
      </div>
      {sheet ? (
        <SymbolSheet />
      ) : (
        <>
          <p className="sld__hint">{t("sld.hint")}</p>
          <SldSvg
            layout={layout}
            zoom={zoom}
            selected={selected}
            ariaLabel={t("sld.ariaLabel", { nodes: layout.nodes.length })}
            stateLabel={(w) => t(`checks.state_${w}`)}
            onSelect={select}
            onKey={onKey}
            onOpenPlan={() => dispatch({ type: "setCanvasView", view: "plan" })}
            onClear={() => dispatch({ type: "select", ids: [] })}
          />
          {!view.topology_view.inverters.length && <p className="sld__hint">{t("sld.noInverters")}</p>}
        </>
      )}
    </div>
  );
}
