import { useTranslation } from "react-i18next";
import { worstCheck, type LiveCheck, type StringCheck, type TopologyChecks } from "../engine/topology";
import { GlyphBlocked, GlyphInfo, GlyphValid, GlyphWarning } from "../ui/icons";

/**
 * Live-check display (B6). The engine computes the checks; the UI only shows
 * them: one glyph per string (its worst check) with every message in the title
 * and in the accessible name. Shape and text carry the state, not colour alone.
 */
export function CheckGlyph({ checks }: { checks: readonly LiveCheck[] | undefined }) {
  const { t } = useTranslation();
  if (!checks?.length) return null;
  const worst = worstCheck(checks);
  const label = `${t(`checks.state_${worst}`)}: ${checks.filter((c) => c.state === worst).map((c) => c.message).join("; ")}`;
  const Glyph = worst === "fail" ? GlyphBlocked : worst === "warn" ? GlyphWarning : worst === "unavailable" ? GlyphInfo : GlyphValid;
  return (
    <span className={`checkglyph checkglyph--${worst}`} title={checks.map((c) => `${t(`checks.state_${c.state}`)} · ${c.message}`).join("\n")} role="img" aria-label={label}>
      <Glyph />
    </span>
  );
}

export const checksByString = (checks: TopologyChecks | undefined): Map<string, StringCheck> => new Map((checks?.strings ?? []).map((c) => [c.string_id, c]));

/**
 * One MPPT's voltage bar: the MPPT window as a band on a 0…(window top × 1.15) scale
 * and one tick per string at its operating voltage. Voltages come from the engine's checks.
 */
export function VoltageBar({ strings, basis }: { strings: readonly StringCheck[]; basis: string }) {
  const { t } = useTranslation();
  const win = strings.find((s) => s.window_v)?.window_v ?? null;
  const vmps = strings.map((s) => s.vmp_v).filter((v): v is number => v !== null);
  if (!win || !vmps.length) return null;
  const top = Math.max(win[1], ...vmps) * 1.15;
  const pct = (v: number) => `${Math.max(0, Math.min(100, (v / top) * 100)).toFixed(2)}%`;
  const lo = Math.min(...vmps);
  const hi = Math.max(...vmps);
  const text = t("checks.voltageBar", { lo: lo.toFixed(0), hi: hi.toFixed(0), wlo: win[0].toFixed(0), whi: win[1].toFixed(0) });
  return (
    <span className="vbar" role="img" aria-label={text} title={`${text}\n${t("checks.basis", { basis })}`}>
      <span className="vbar__window" style={{ left: pct(win[0]), width: `calc(${pct(win[1])} - ${pct(win[0])})` }} />
      {strings.map((s) =>
        s.vmp_v === null ? null : (
          <span key={s.string_id} className={`vbar__tick vbar__tick--${worstCheck(s.checks)}`} style={{ left: pct(s.vmp_v) }} />
        )
      )}
    </span>
  );
}
