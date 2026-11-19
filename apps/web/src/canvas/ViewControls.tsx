import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { IconSquare, IconArrowDown, IconArrowUp, IconArrowLeft, IconArrowRight, IconCube, IconFocus2 } from "@tabler/icons-react";
import { useActions, useUI } from "../state/store";
import { nextMenuIndex } from "../ui/ContextMenu";
import { VIEW_PRESETS, selectedRoof } from "./viewPresets";

const icons = { plan: IconSquare, front: IconArrowDown, back: IconArrowUp, left: IconArrowRight, right: IconArrowLeft, isometric: IconCube, face: IconFocus2 };

/** Shared list for the stage buttons and both geometry context menus. */
export function ViewControls({ menu = false, onClose }: { menu?: boolean; onClose?: () => void }) {
  const { t } = useTranslation();
  const { dispatch } = useActions();
  const { view, roof } = useUI(s => ({ view: s.canvasView, roof: selectedRoof(s.entities, s.selection) }));
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (menu) ref.current?.querySelector<HTMLButtonElement>("button")?.focus(); }, [menu]);
  return <div ref={ref} className={menu ? undefined : "segmented segmented--stage"} role={menu ? "menu" : "group"}
    aria-label={t("stage.view")} onKeyDown={menu ? e => {
      const buttons = [...e.currentTarget.querySelectorAll<HTMLButtonElement>("button")];
      const next = nextMenuIndex(e.key, buttons.indexOf(document.activeElement as HTMLButtonElement), buttons.length);
      if (next !== null) { e.preventDefault(); buttons[next]?.focus(); }
      if (e.key === "Escape" || e.key === "ArrowLeft") { e.preventDefault(); onClose?.(); }
      if (e.key === "Tab") onClose?.();
      e.stopPropagation();
    } : undefined}>
    {VIEW_PRESETS.map(p => {
      const Icon = icons[p.id];
      const disabled = p.id === "face" && !roof;
      const label = t(`stage.${p.label}`);
      const keys = "keys" in p ? p.keys : undefined;
      return <button key={p.id} type="button" className={menu ? "ctxmenu__item" : `segmented__opt${view === p.id ? " segmented__opt--on" : ""}`}
        role={menu ? "menuitemradio" : undefined} tabIndex={menu ? -1 : undefined} aria-label={label}
        aria-checked={menu ? view === p.id : undefined} aria-pressed={menu ? undefined : view === p.id}
        disabled={!menu && disabled} aria-disabled={disabled || undefined}
        title={disabled ? `${label} · ${t("stage.selectRoof")}` : `${label}${keys ? ` · ${keys}` : ""}`}
        onClick={() => { if (!disabled) { dispatch({ type: "setCanvasView", view: p.id }); onClose?.(); } }}>
        <Icon size={18} aria-hidden="true" />
        {menu && <span className="ctxmenu__text">{label}{disabled && <span className="ctxmenu__reason">{t("stage.selectRoof")}</span>}</span>}
      </button>;
    })}
  </div>;
}
