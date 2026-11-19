import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { keyParts } from "../commands/keys";
import { railSteps } from "../modules/registry";
import { track } from "../platform/telemetry";
import { selectModel, stepStates, type StepState } from "../state/derived";
import { useActions, useUI } from "../state/store";
import { GlyphBlocked, GlyphValid, GlyphWarning, PaneLeftCollapse, PaneLeftExpand } from "../ui/icons";

function StateGlyph({ state }: { state: StepState }) {
  if (state === "valid") return <GlyphValid className="glyph glyph--valid" />;
  if (state === "draft") return <GlyphWarning className="glyph glyph--warning" />;
  if (state === "blocked") return <GlyphBlocked className="glyph glyph--blocked" />;
  return <span className="glyph glyph--none" aria-hidden="true" />;
}

export function Rail({ compact, onToggleCompact }: { compact: boolean; onToggleCompact: () => void }) {
  const { t } = useTranslation();
  const model = useUI(selectModel);
  const step = useUI((s) => s.step);
  const { dispatch } = useActions();
  const states = useMemo(() => stepStates(model), [model]);
  return (
    <nav className={compact ? "rail rail--compact" : "rail"} aria-label={t("header.workflow")}>
      <ol className="rail__list">
        {railSteps().map((s, i) => {
          const on = step === s.id;
          const st = states[s.id];
          return (
            <li key={s.id}>
              <button
                type="button"
                className={on ? "rail__step rail__step--on" : "rail__step"}
                aria-current={on ? "step" : undefined}
                title={`${t(s.labelKey)} · ${t(`stepState.${st}`)}${s.shortcut ? ` · ${keyParts(`Alt+${s.shortcut}`).join("+")}` : ""}`}
                onClick={() => {
                  dispatch({ type: "setStep", step: s.id });
                  track("step.viewed", { step: s.id });
                }}
              >
                <span className="rail__num">{String(i + 1).padStart(2, "0")}</span>
                <span className="rail__label">{t(s.labelKey)}</span>
                {on && <span className="rail__marker" aria-hidden="true" />}
                <StateGlyph state={st} />
                <span className="visually-hidden">, {t(`stepState.${st}`)}</span>
              </button>
            </li>
          );
        })}
      </ol>
      <button
        type="button"
        className="rail__compact"
        onClick={onToggleCompact}
        aria-pressed={compact}
        aria-label={t("panes.railCompact")}
        title={t("panes.railCompact")}
      >
        {compact ? <PaneLeftExpand /> : <PaneLeftCollapse />}
        <span className="rail__label" aria-hidden="true">
          {t("panes.railCompact")}
        </span>
      </button>
    </nav>
  );
}
