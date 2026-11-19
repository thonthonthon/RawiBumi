import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { engine } from "../client";
import { engineCommand } from "../state/history";
import { useStore } from "../state/store";
import type { AnnualPxxView, SimulationRunRecord, UncertaintyLedger, UncertaintyTerm } from "../types";
import { Button, Field, fmt, Section, Segmented, Select } from "../ui/kit";

/**
 * UNC1: a run's annual P50–P95 (the engine's U1 analytical method) and the project's uncertainty ledger. The
 * engine computes; this view only shows its result or its reasons. There are no numerical defaults: the six
 * categories carry U1's double-count guidance, never a value.
 */
export const CATEGORIES = [
  { key: "interannual_solar_variability", scope: "annual_weather", group: "solar_resource_weather" },
  { key: "solar_resource_reference_bias", scope: "project_persistent", group: "solar_resource_reference" },
  { key: "model_translation_uncertainty", scope: "project_persistent", group: "physical_model" },
  { key: "module_specification_uncertainty", scope: "project_persistent", group: "module_parameter" },
  { key: "loss_assumption_uncertainty", scope: "project_persistent", group: "loss_ledger" },
  { key: "annual_operating_availability_uncertainty", scope: "annual_weather", group: "annual_availability" }
] as const;

/** One editor row: the percent the engineer types is a fraction of the annual mean on save. */
export interface DraftTerm { category: string; source_key: string; double_count_group: string; scope: UncertaintyTerm["scope"]; value: string; unit: "percent" | "kwh"; provenance_type: UncertaintyTerm["provenance_type"]; source_ref: string; justification: string }

export const emptyTerm = (category: (typeof CATEGORIES)[number]): DraftTerm => ({
  category: category.key, source_key: category.key, double_count_group: category.group, scope: category.scope,
  value: "", unit: "percent", provenance_type: "user_assumption", source_ref: "", justification: ""
});

export function draftOf(ledger: UncertaintyLedger | undefined): { terms: DraftTerm[]; mode: "independent_explicit" | "matrix_explicit"; basis: string; matrix: string } {
  if (!ledger) return { terms: [], mode: "independent_explicit", basis: "", matrix: "" };
  const c = ledger.correlation;
  return {
    terms: ledger.terms.map((t) => ({
      category: CATEGORIES.some((k) => k.key === t.source_key) ? t.source_key : "custom", source_key: t.source_key, double_count_group: t.double_count_group,
      scope: t.scope, value: String(t.sigma_unit === "kwh" ? t.sigma_value : Number((t.sigma_value * 100).toPrecision(12))),
      unit: t.sigma_unit === "kwh" ? "kwh" : "percent", provenance_type: t.provenance_type, source_ref: t.source_ref, justification: t.justification
    })),
    mode: c.mode,
    basis: c.mode === "matrix_explicit" ? c.matrix_basis : c.independence_basis,
    matrix: c.mode === "matrix_explicit" ? c.matrix.map((row) => row.join(", ")).join("; ") : ""
  };
}

/** The ledger to save, or the first problem the engineer must fix (the engine validates again). */
export function ledgerOf(d: ReturnType<typeof draftOf>): { ledger: UncertaintyLedger } | { problem: string } {
  if (!d.terms.length) return { problem: "unc1.needTerm" };
  const terms: UncertaintyTerm[] = [];
  for (const t of d.terms) {
    const v = Number(t.value);
    if (t.value.trim() === "" || !Number.isFinite(v) || v < 0) return { problem: "unc1.needValue" };
    if (!t.source_ref.trim() || !t.justification.trim()) return { problem: "unc1.needSource" };
    terms.push({ source_key: t.source_key.trim(), double_count_group: t.double_count_group.trim(), scope: t.scope, provenance_type: t.provenance_type,
      source_ref: t.source_ref.trim(), justification: t.justification.trim(),
      sigma_value: t.unit === "kwh" ? v : v / 100, sigma_unit: t.unit === "kwh" ? "kwh" : "fraction_of_annual_mean" });
  }
  if (!d.basis.trim()) return { problem: "unc1.needBasis" };
  if (d.mode === "independent_explicit") return { ledger: { schema_version: "1.0", terms, correlation: { mode: "independent_explicit", independence_basis: d.basis.trim() } } };
  const matrix = d.matrix.split(";").map((row) => row.split(",").map((x) => Number(x.trim())));
  if (matrix.some((row) => row.some((x) => !Number.isFinite(x)))) return { problem: "unc1.needMatrix" };
  return { ledger: { schema_version: "1.0", terms, correlation: { mode: "matrix_explicit", matrix, matrix_basis: d.basis.trim() } } };
}

/** The engine's annual-Pxx view of a run, refetched when the run or the ledger changes. */
export function useAnnualPxx(projectId: string, run: SimulationRunRecord | undefined, ledger: UncertaintyLedger | undefined) {
  const [state, setState] = useState<{ key: string; view: AnnualPxxView | null; error: string | null } | null>(null);
  const key = `${run?.simulation_run_id ?? ""}|${JSON.stringify(ledger ?? null)}`;
  useEffect(() => {
    if (!run) return;
    let live = true;
    engine.annualPxx(projectId, run.simulation_run_id)
      .then((view) => live && setState({ key, view, error: null }))
      .catch((e: unknown) => live && setState({ key, view: null, error: e instanceof Error ? e.message : String(e) }));
    return () => { live = false; };
  }, [projectId, run, key]);
  return state?.key === key ? state : null;
}

export function AnnualPxxCard({ run }: { run: SimulationRunRecord }) {
  const { t } = useTranslation();
  const { state } = useStore();
  const v = state.view!;
  const pid = v.bundle.project.project_id;
  const ledger = v.bundle.uncertainty_assumptions;
  const pxx = useAnnualPxx(pid, run, ledger);
  const [draft, setDraft] = useState(() => draftOf(ledger));
  const [problem, setProblem] = useState<string | null>(null);
  const [lastLedger, setLastLedger] = useState(ledger);
  if (lastLedger !== ledger) { setLastLedger(ledger); setDraft(draftOf(ledger)); setProblem(null); }
  const busy = !!state.busy;
  const set = (i: number, patch: Partial<DraftTerm>) => setDraft({ ...draft, terms: draft.terms.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
  const unused = CATEGORIES.filter((c) => !draft.terms.some((x) => x.category === c.key));
  const save = () => {
    const out = ledgerOf(draft);
    if ("problem" in out) { setProblem(out.problem); return; }
    setProblem(null);
    void engineCommand(t("unc1.saving"), () => engine.updateUncertaintyAssumptions(pid, out.ledger));
  };
  const view = pxx?.view;
  const r = view?.result;
  return (
    <section className="panel-card" aria-label={t("unc1.title")} data-annual-pxx={view?.status ?? (pxx?.error ? "error" : "loading")}>
      <h3>{t("unc1.title")}</h3>
      {!pxx ? <p role="status">{t("unc1.loading")}</p> : pxx.error ? <p role="alert">{t("unc1.error", { error: pxx.error })}</p> : view && r ? (
        <>
          <table className="tbl" data-pxx-table>
            <tbody>
              {(["P50", "P75", "P90", "P95"] as const).map((k) => (
                <tr key={k} data-pxx={k}><th scope="row">{k}</th><td className="num">{fmt(r.quantiles[k].energy_kwh / 1000, 2, "MWh")}</td><td className="sub">{t("unc1.exceeded", { p: Number(k.slice(1)) })}</td></tr>
              ))}
              <tr data-pxx="P99"><th scope="row">P99</th><td className="num">—</td><td className="sub">{t("unc1.p99")}</td></tr>
            </tbody>
          </table>
          <p className="sub">{t("unc1.sigma", { kwh: fmt(r.annual_sigma_kwh, 0, "kWh"), pct: r.annual_sigma_fraction === null ? "—" : (r.annual_sigma_fraction * 100).toFixed(2) })} · {t("unc1.negative", { p: r.gaussian_negative_support_probability.toExponential(2) })}</p>
          <p className="note" data-pxx-basis={view.basis.annual_mean_basis}>{t(`unc1.basis_${view.basis.annual_mean_basis}`)} {t("unc1.label")}</p>
        </>
      ) : view ? (
        <ul className="rules" data-pxx-reasons>{view.reasons.map((x) => <li key={x.code}><span className="tag tag--draft">{x.code}</span> {t(`unc1.reason_${x.code}`, { defaultValue: x.message })}</li>)}</ul>
      ) : null}

      <Section title={t("unc1.ledger")} defaultOpen={false}>
        <p className="note">{t("unc1.ledgerNote")}</p>
        {draft.terms.map((term, i) => (
          <fieldset key={i} className="colgroup" data-pxx-term={term.source_key}>
            <legend>{term.category === "custom" ? term.source_key || t("unc1.custom") : t(`unc1.cat_${term.category}`)}</legend>
            {term.category !== "custom" && <p className="sub">{t(`unc1.guide_${term.category}`)}</p>}
            <div className="grid2">
              <Field label={t("unc1.value")}>
                <input className="input input--num" inputMode="decimal" aria-label={t("unc1.valueFor", { term: term.source_key })} value={term.value} onChange={(e) => set(i, { value: e.target.value })} />
              </Field>
              <Field label={t("unc1.unit")}>
                <Select label={t("unc1.unitFor", { term: term.source_key })} value={term.unit} onChange={(unit) => set(i, { unit })} options={[{ value: "percent", label: t("unc1.percent") }, { value: "kwh", label: "kWh" }]} />
              </Field>
            </div>
            <Field label={t("unc1.source")}><input className="input" aria-label={t("unc1.sourceFor", { term: term.source_key })} value={term.source_ref} onChange={(e) => set(i, { source_ref: e.target.value })} /></Field>
            <Field label={t("unc1.justification")}><input className="input" aria-label={t("unc1.justificationFor", { term: term.source_key })} value={term.justification} onChange={(e) => set(i, { justification: e.target.value })} /></Field>
            <div className="grid2">
              <Field label={t("unc1.provenance")}>
                <Select label={t("unc1.provenance")} value={term.provenance_type} onChange={(provenance_type) => set(i, { provenance_type })}
                  options={(["user_assumption", "measured_or_derived", "versioned_software_catalog"] as const).map((p) => ({ value: p, label: t(`unc1.prov_${p}`) }))} />
              </Field>
              <Field label={t("unc1.group")} hint={t("unc1.groupHint")}><input className="input" value={term.double_count_group} onChange={(e) => set(i, { double_count_group: e.target.value })} /></Field>
            </div>
            <Button small tone="ghost" onClick={() => setDraft({ ...draft, terms: draft.terms.filter((_, j) => j !== i) })}>{t("unc1.remove")}</Button>
          </fieldset>
        ))}
        {unused.length > 0 && (
          <div className="row" data-pxx-add>
            {unused.map((c) => <Button key={c.key} small onClick={() => setDraft({ ...draft, terms: [...draft.terms, emptyTerm(c)] })}>+ {t(`unc1.cat_${c.key}`)}</Button>)}
          </div>
        )}
        <Field label={t("unc1.correlation")}>
          <Segmented label={t("unc1.correlation")} value={draft.mode} onChange={(mode) => setDraft({ ...draft, mode })}
            options={[{ value: "independent_explicit", label: t("unc1.independent") }, { value: "matrix_explicit", label: t("unc1.matrix") }]} />
        </Field>
        {draft.mode === "matrix_explicit" && (
          <Field label={t("unc1.matrixValues")} hint={t("unc1.matrixHint")}><input className="input" aria-label={t("unc1.matrixValues")} value={draft.matrix} onChange={(e) => setDraft({ ...draft, matrix: e.target.value })} /></Field>
        )}
        <Field label={t("unc1.basis")}><input className="input" aria-label={t("unc1.basis")} value={draft.basis} onChange={(e) => setDraft({ ...draft, basis: e.target.value })} /></Field>
        {problem && <p role="alert" className="issue">{t(problem)}</p>}
        <div className="row">
          <Button tone="primary" disabled={busy} onClick={save}>{t("unc1.save")}</Button>
          {ledger && <Button disabled={busy} onClick={() => void engineCommand(t("unc1.saving"), () => engine.updateUncertaintyAssumptions(pid, null))}>{t("unc1.clear")}</Button>}
        </div>
      </Section>
    </section>
  );
}
