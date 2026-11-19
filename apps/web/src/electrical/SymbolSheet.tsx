import { useTranslation } from "react-i18next";
import { SHEET_ORDER, symbol } from "./symbols";
import { SymbolGlyph } from "./symbols/SymbolGlyph";

/** Symbols the free SLD draws today; the rest are in the library for the full SLD. */
export const FREE_SLD_SYMBOLS = new Set(["pv-string", "mppt-input", "inverter", "busbar", "grid", "load"]);

/**
 * The symbol sheet (plan A6): every in-house IEC 60617 symbol with its terminals, drawn
 * by the same component as the SLD. The F6 done-when checks the SLD against this sheet.
 */
export function SymbolSheet() {
  const { t } = useTranslation();
  return (
    <section className="symsheet" aria-label={t("sld.symbolSheet")}>
      <p className="sld__hint">{t("sld.sheetNote")}</p>
      <ul className="symsheet__grid">
        {SHEET_ORDER.map((id) => {
          const s = symbol(id);
          const [vx, vy, vw, vh] = s.viewBox;
          const pad = 6;
          return (
            <li key={id} className="symsheet__cell" data-sheet-symbol={id}>
              <svg viewBox={`${vx - pad} ${vy - pad} ${vw + 2 * pad} ${vh + 2 * pad}`} width={(vw + 2 * pad) * 2} height={(vh + 2 * pad) * 2} role="img" aria-label={t(`symbols.${id}`)} className="symsheet__svg">
                <SymbolGlyph id={id} />
                {Object.entries(s.terminals).map(([name, [x, y]]) => (
                  <circle key={name} cx={x} cy={y} r={1.6} className="symsheet__terminal">
                    <title>{name}</title>
                  </circle>
                ))}
              </svg>
              <div className="symsheet__name">{t(`symbols.${id}`)}</div>
              <div className="symsheet__meta">
                <code>{id}.svg</code> · {t("sld.terminals", { list: Object.keys(s.terminals).join(", ") })}
              </div>
              <div className="symsheet__meta">
                {s.iec === "to confirm" ? t("sld.iecToConfirm") : t("sld.iec", { ref: s.iec })}
                {FREE_SLD_SYMBOLS.has(id) ? ` · ${t("sld.usedFree")}` : ` · ${t("sld.usedFull")}`}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
