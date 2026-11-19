import type { ReactNode } from "react";
import { Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Keys } from "../commands/CommandPalette";
import type { MenuAction, MenuItem } from "../canvas/contextMenu";

const MARGIN = 4;

/** Index the keyboard moves to: arrows wrap, Home and End jump. Pure, so it is unit-tested. */
export function nextMenuIndex(key: string, current: number, count: number): number | null {
  if (!count) return null;
  if (key === "ArrowDown") return (current + 1) % count;
  if (key === "ArrowUp") return (current - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}

/** Keep the menu inside its container: shift left near the right edge, flip up near the bottom. */
export function placeMenu(at: { x: number; y: number }, menu: { w: number; h: number }, box: { w: number; h: number }) {
  const x = at.x + menu.w + MARGIN > box.w ? Math.max(MARGIN, box.w - menu.w - MARGIN) : at.x;
  const y = at.y + menu.h + MARGIN > box.h ? Math.max(MARGIN, at.y - menu.h) : at.y;
  return { x, y };
}

/**
 * A WAI-ARIA menu at a point in its container (UX2). Disabled items stay visible and focusable, with their
 * reason as text. Escape closes and asks the caller to restore focus; Tab, outside presses, wheel and blur close.
 */
export function ContextMenu({ items, at, box, label, onSelect, onClose, submenu }: {
  items: MenuItem[];
  submenu?: { label: string; content: (close: () => void) => ReactNode };
  at: { x: number; y: number };
  box: { w: number; h: number };
  label: string;
  onSelect: (id: MenuAction) => void;
  onClose: (restoreFocus: boolean) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  const [subOpen, setSubOpen] = useState(false);
  const [pos, setPos] = useState(at);
  const [active, setActive] = useState(() => Math.max(0, items.findIndex((i) => !i.disabled)));

  useLayoutEffect(() => {
    const el = ref.current;
    if (el) setPos(placeMenu(at, { w: el.offsetWidth, h: el.offsetHeight }, box));
  }, [at, box, items, subOpen]);

  useEffect(() => { buttons.current[active]?.focus(); }, [active]);

  useEffect(() => {
    const outside = (e: Event) => { if (!ref.current?.contains(e.target as Node)) onClose(false); };
    const close = () => onClose(false);
    document.addEventListener("pointerdown", outside, true);
    window.addEventListener("wheel", outside, { passive: true });
    window.addEventListener("blur", close);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("wheel", outside);
      window.removeEventListener("blur", close);
      window.removeEventListener("resize", close);
    };
  }, [onClose]);

  const choose = (item: MenuItem) => {
    if (item.disabled) return;
    onSelect(item.id);
  };

  return (
    <div
      ref={ref}
      className="ctxmenu"
      role="menu"
      aria-label={label}
      style={{ left: pos.x, top: pos.y }}
      onContextMenu={(e) => e.preventDefault()}
      onKeyDown={(e) => {
        const next = nextMenuIndex(e.key, active, items.length + (submenu ? 1 : 0));
        if (next !== null) {
          e.preventDefault();
          setActive(next);
        } else if (e.key === "ArrowRight" && active === items.length && submenu) {
          e.preventDefault();
          setSubOpen(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          onClose(true);
        } else if (e.key === "Tab") {
          e.preventDefault();
          onClose(true);
        } else if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          if (active === items.length && submenu) setSubOpen(true);
          else choose(items[active]);
        }
        // Keys typed in the menu never reach the plan's shortcuts.
        e.stopPropagation();
      }}
    >
      {items.map((item, i) => (
        <Fragment key={item.id}>
          {i > 0 && items[i - 1].group !== item.group && <div className="ctxmenu__sep" role="separator" />}
          <button
            ref={(b) => { buttons.current[i] = b; }}
            type="button"
            role="menuitem"
            tabIndex={i === active ? 0 : -1}
            className={item.danger ? "ctxmenu__item ctxmenu__item--danger" : "ctxmenu__item"}
            aria-disabled={item.disabled ? true : undefined}
            data-menu-item={item.id}
            title={item.title}
            onPointerEnter={() => setActive(i)}
            onClick={() => choose(item)}
          >
            <span className="ctxmenu__text">
              <span>{item.label}</span>
              {item.disabled && <span className="ctxmenu__reason">{item.disabled}</span>}
            </span>
            {item.keys && <Keys keys={item.keys} />}
          </button>
        </Fragment>
      ))}
      {submenu && <>
        {items.length > 0 && <div className="ctxmenu__sep" role="separator" />}
        <button ref={b => { buttons.current[items.length] = b; }} type="button" role="menuitem"
          className="ctxmenu__item" aria-haspopup="menu" aria-expanded={subOpen}
          tabIndex={active === items.length ? 0 : -1}
          onFocus={() => setActive(items.length)} onPointerEnter={() => setActive(items.length)} onClick={() => setSubOpen(!subOpen)}>
          {submenu.label} ▸
        </button>
        {subOpen && submenu.content(() => { setSubOpen(false); buttons.current[items.length]?.focus(); })}
      </>}
    </div>
  );
}
