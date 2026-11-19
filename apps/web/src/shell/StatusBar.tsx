import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { allFindings, quantities, selectModel } from "../state/derived";
import { useActions, useUI } from "../state/store";
import { GlyphBlocked, GlyphWarning } from "../ui/icons";

function useNumber() {
  const { i18n } = useTranslation();
  return (n: number, digits = 0) =>
    new Intl.NumberFormat(i18n.language === "id" ? "id-ID" : "en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
}

/** Bottom bar: quantities on the left, findings on the right, findings list above it when open. */
export function StatusBar() {
  const { t } = useTranslation();
  const num = useNumber();
  const model = useUI(selectModel);
  const busy = useUI((s) => s.busy);
  // Electrical step: the MPPT that new strings and the Assign brush go to ([ ] and 1–9).
  const target = useUI((s) => {
    if (s.step !== "electrical" || !s.target || !s.view) return null;
    for (const inv of s.view.topology_view.inverters) for (const m of inv.mppts) if (m.mppt_instance_id === s.target) return `${inv.name} · MPPT ${m.index}`;
    return null;
  });
  const { dispatch } = useActions();
  const [open, setOpen] = useState(false);
  const q = useMemo(() => quantities(model), [model]);
  const findings = useMemo(() => allFindings(model), [model]);
  const blocking = findings.filter((f) => f.severity === "blocking").length;
  const warnings = findings.filter((f) => f.severity === "warning").length;
  const drafts = findings.filter((f) => f.severity === "draft").length;

  return (
    <footer className={open ? "statusbar statusbar--open" : "statusbar"}>
      {open && (
        <ul className="findings__list" id="findings-list" aria-label={t("status.findings")}>
          {findings.length === 0 && <li className="empty">{t("status.none")}</li>}
          {findings.map((f) => (
            <li key={f.id}>
              <button
                type="button"
                className={`finding finding--${f.severity}`}
                onClick={() => {
                  if (f.step) dispatch({ type: "setStep", step: f.step });
                  if (f.entityId) dispatch({ type: "select", ids: [f.entityId] });
                }}
              >
                <span className="finding__sev">{f.severity}</span>
                <span className="finding__src">{f.source}</span>
                <span className="finding__msg">{f.message}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="statusbar__row">
        <dl className="quantities" aria-label={t("status.quantities")}>
          <div>
            <dt>{t("status.modules")}</dt>
            <dd>{num(q.modules)}</dd>
          </div>
          <div title={t("status.kwpNote")}>
            <dt>{t("status.dc")}</dt>
            <dd>
              {num(q.kwp, 2)}&nbsp;kWp
            </dd>
          </div>
          <div>
            <dt>{t("status.strings")}</dt>
            <dd>{num(q.strings)}</dd>
          </div>
          <div>
            <dt>{t("status.unassigned")}</dt>
            <dd>{num(q.unassigned)}</dd>
          </div>
          <div>
            <dt>{t("status.dcac")}</dt>
            <dd>{q.dcac == null ? "—" : num(q.dcac, 2)}</dd>
          </div>
          {target && (
            <div title={t("status.targetNote")}>
              <dt>{t("status.target")}</dt>
              <dd>{target}</dd>
            </div>
          )}
        </dl>
        <span className="statusbar__busy" aria-live="polite">
          {busy ? `${busy}…` : ""}
        </span>
        <button type="button" className="statusbar__findings" aria-expanded={open} aria-controls="findings-list" onClick={() => setOpen(!open)}>
          <span className="statusbar__label">{t("status.findings")}</span>
          <span className={blocking ? "count count--blocked" : "count"}>
            <GlyphBlocked className="glyph glyph--blocked" />
            {t("status.blocking", { count: blocking })}
          </span>
          <span className={warnings ? "count count--warning" : "count"}>
            <GlyphWarning className="glyph glyph--warning" />
            {t("status.warnings", { count: warnings })}
          </span>
          <span className="count">{t("status.drafts", { count: drafts })}</span>
          <span className="statusbar__toggle">{open ? t("status.hide") : t("status.show")}</span>
        </button>
      </div>
    </footer>
  );
}
