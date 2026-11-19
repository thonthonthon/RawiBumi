import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Keys } from "./CommandPalette";
import { ELECTRICAL_KEYS, ELECTRICAL_TOOLS, PLAN_KEYS, TOOLS } from "../canvas/tools";
import type { Command } from "./useCommands";

/** Plan keys, handled inside PlanCanvas, from the shared tool table. */
const CANVAS_KEYS: Array<[string, string]> = [...TOOLS.map((d) => [d.key, d.label] as [string, string]), ...PLAN_KEYS];
/** Electrical step keys (B6). */
const ELECTRICAL_SHEET: Array<[string, string]> = [...ELECTRICAL_TOOLS.filter((d) => d.tool !== "select").map((d) => [d.key, d.label] as [string, string]), ...ELECTRICAL_KEYS];

export function ShortcutSheet({ open, onClose, commands }: { open: boolean; onClose: () => void; commands: Command[] }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  const global = commands.filter((c) => c.keys);
  return (
    <dialog ref={ref} className="sheet" aria-labelledby="sheet-title" onClose={onClose} onCancel={onClose}>
      <div className="sheet__head">
        <h2 id="sheet-title">{t("shortcuts.title")}</h2>
        <button type="button" className="btn btn--sm" onClick={onClose}>
          {t("shortcuts.close")}
        </button>
      </div>
      <div className="sheet__body">
        <section>
          <h3>{t("shortcuts.global")}</h3>
          <dl className="sheet__list">
            {global.map((c) => (
              <div key={c.id} className="sheet__row">
                <dt>{c.label}</dt>
                <dd>
                  <Keys keys={c.keys!} />
                  {c.alternativeKeys?.map((keys) => <Keys key={keys} keys={keys} />)}
                </dd>
              </div>
            ))}
          </dl>
        </section>
        <section>
          <h3>{t("shortcuts.canvas")}</h3>
          <dl className="sheet__list">
            {CANVAS_KEYS.map(([k, label]) => (
              <div key={`${k}|${label}`} className="sheet__row">
                <dt>{t(label)}</dt>
                <dd>
                  <Keys keys={k} />
                </dd>
              </div>
            ))}
          </dl>
        </section>
        <section>
          <h3>{t("shortcuts.electrical")}</h3>
          <dl className="sheet__list">
            {ELECTRICAL_SHEET.map(([k, label]) => (
              <div key={`${k}|${label}`} className="sheet__row">
                <dt>{t(label)}</dt>
                <dd>
                  <Keys keys={k} />
                </dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </dialog>
  );
}
