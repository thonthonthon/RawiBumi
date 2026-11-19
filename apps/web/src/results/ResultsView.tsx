import { useEffect, useMemo, useState } from "react";
import { RunShadingAccuracy } from "../panels/ShadingAccuracyPanel";
import { RunOpticsThermalSettings } from "../panels/OpticsThermalPanel";
import { RunLossSettings } from "../panels/LossesPanel";
import { useTranslation } from "react-i18next";
import { DEMO, exportAPI, type RunTimeSeriesView } from "../client";
import { demoSeries } from "../demo/series";
import { useForm, useStore } from "../state/store";
import { GlyphBlocked, GlyphInfo, GlyphValid } from "../ui/icons";
import { fmt, NotWired, Section, Segmented, Select } from "../ui/kit";
import { EChart, Legend, UPlotLines } from "./ChartViews";
import { heatmapOption, monthlyOption, paletteFromTokens, waterfallOption, MONTH_KEYS, type BarSeries } from "./chartOptions";
import { DetailedElectricalShading, DetailedExecutionStatus } from "./DetailedElectricalShading";
import { buildResultModel, checkResultRules, inverterResultRows, isAnnualResult, runDesignBasis, weeklyHeatmap, type RuleResult, type InverterResultRow } from "./model";
import type { SimulationRunRecord, SummaryResult } from "../types";
import { coveredMonths, fromDemo, fromEngine, largestLosses, meanDayOfMonth, type ResultSeries } from "./series";
import { MixedOrientationResults } from "./MixedOrientation";
import { AnnualPxxCard } from "./AnnualPxx";

export function InverterResultsTable({ rows, summary }: { rows: InverterResultRow[]; summary: SummaryResult }) {
  const { t } = useTranslation();
  if (!rows.length) return null;
  const staged = !!summary.resolved_loss_settings;
  const limited = summary.loss_summary.some((l) => l.loss_type === "mppt_current_limit");
  const adjustmentWh = summary.loss_summary.filter((l) => ["plant_ac_wiring", "transformer_iron", "transformer_copper", "unavailability"].includes(l.loss_type)).reduce((sum, l) => sum + l.lost_energy_wh, 0);
  const totalLoss = (key: string) => (summary.loss_summary.find((l) => l.loss_type === key)?.lost_energy_wh ?? 0) / 1000;
  return <section className="panel-card" aria-label={t("results.inverterBreakdown")}>
    <h3>{t("results.inverterBreakdown")}</h3>
    <table className="tbl">
      <thead><tr>
        <th>{t("results.inverterName")}</th><th>DC (kWp)</th><th>{t("results.referenceProduction")} (kWh)</th>
        <th>{t("results.kpiYield")} (kWh/kWp)</th><th>{t("results.kpiClipping")} (kWh)</th>
        {staged && <th>{t("losses.acWiring")}</th>}
        {limited && <th>{t("use1.currentLimit")} (kWh)</th>}
        <th>{t("results.voltageThreshold")} (kWh)</th><th>{t("results.startupThreshold")} (kWh)</th>
      </tr></thead>
      <tbody>{rows.map((row) => <tr key={row.id} data-inverter-result={row.id}>
        <th scope="row">{row.name}</th><td>{fmt(row.dcKwp, 2)}</td>
        <td data-inverter-energy-kwh={row.energyKwh}>{fmt(row.energyKwh, 3)}</td>
        <td>{fmt(row.specificYield, 3)}</td><td>{fmt(row.clippingKwh, 3)}</td>
        {staged && <td>{fmt(row.acWiringKwh ?? 0, 3)}</td>}
        {limited && <td data-current-limit-kwh={row.currentLimitKwh ?? 0}>{fmt(row.currentLimitKwh ?? 0, 3)}</td>}
        <td>{fmt(row.voltageThresholdKwh, 3)}</td><td>{fmt(row.startupThresholdKwh, 3)}</td>
      </tr>)}</tbody>
      <tfoot>{staged && <><tr><th scope="row">{t("losses.inverterSubtotal")}</th><td></td><td>{fmt((summary.total_energy_wh + adjustmentWh) / 1000, 3)}</td></tr>
        {summary.loss_summary.filter((l) => ["plant_ac_wiring", "transformer_iron", "transformer_copper", "unavailability"].includes(l.loss_type)).map((l) => <tr key={l.loss_type}><th scope="row">{t(`losses.stages.${l.loss_type}`)}</th><td></td><td>−{fmt(l.lost_energy_wh / 1000, 3)}</td></tr>)}</>}
        <tr><th scope="row">{t("results.plantTotal")}</th>
        <td>{fmt(summary.execution_breakdown ? summary.execution_breakdown.simulated_dc_nameplate_w / 1000 : rows[0].dcKwp, 2)}</td>
        <td data-plant-energy-kwh={summary.total_energy_wh / 1000}>{fmt(summary.total_energy_wh / 1000, 3)}</td>
        <td>{fmt(summary.specific_yield_wh_per_wp, 3)}</td><td>{fmt(summary.clipping_energy_wh / 1000, 3)}</td>
        {staged && <td>{fmt(totalLoss("ac_wiring"), 3)}</td>}
        {limited && <td>{fmt(totalLoss("mppt_current_limit"), 3)}</td>}
        <td>{fmt(totalLoss("mppt_voltage_threshold"), 3)}</td><td>{fmt(totalLoss("inverter_power_threshold"), 3)}</td>
      </tr></tfoot>
    </table>
  </section>;
}

function DemoStamp() {
  const { t } = useTranslation();
  return (
    <span className="demo-stamp" title={t("results.demoStampNote")}>
      {t("results.demoStamp")}
    </span>
  );
}

/** Why a series view is empty: loading, an error, a run without its package, or (S19) a quantity not modelled yet. */
function NeedsSeries({ state }: { state: SeriesState | "export_limit" | "load" }) {
  const { t } = useTranslation();
  const text = state === "export_limit" ? t("s15.needsExportLimit") : state === "load" ? t("s15.needsLoad")
    : state.kind === "loading" ? t("s15.loading") : state.kind === "omitted" ? t("data1.packageOmitted")
    : state.kind === "error" ? t("s15.error", { error: state.error }) : t("s15.unavailable");
  return (
    <div className="empty-chart" data-series-state={typeof state === "string" ? state : state.kind}>
      <p role={typeof state !== "string" && state.kind === "error" ? "alert" : "status"}>{text}</p>
    </div>
  );
}

type SeriesState = { kind: "ready"; series: ResultSeries } | { kind: "loading" } | { kind: "omitted" } | { kind: "error"; error: string } | { kind: "none" };

/** S15: the selected run's stored series from the engine route (never demo physics), as one ResultSeries. */
function useEngineSeries(projectId: string, run: SimulationRunRecord | undefined): SeriesState {
  const [state, setState] = useState<{ runId: string; value: SeriesState } | null>(null);
  const runId = run?.simulation_run_id;
  const usable = !DEMO && !!run?.summary_result && !run.package_omitted && (run.status === "completed" || run.status === "completed_with_warnings");
  useEffect(() => {
    if (!runId || !usable) return;
    const abort = new AbortController();
    setState({ runId, value: { kind: "loading" } });
    exportAPI.runSeries(projectId, runId, abort.signal)
      .then((view: RunTimeSeriesView) => setState({ runId, value: { kind: "ready", series: fromEngine(view) } }))
      .catch((e: unknown) => { if (!abort.signal.aborted) setState({ runId, value: { kind: "error", error: e instanceof Error ? e.message : String(e) } }); });
    return () => abort.abort();
  }, [projectId, runId, usable]);
  if (!run) return { kind: "none" };
  if (run.package_omitted) return { kind: "omitted" };
  if (!usable) return { kind: "none" };
  return state && state.runId === runId ? state.value : { kind: "loading" };
}

/** S15: the readiness warnings a run was launched with (or that older runs didn't record them). */
function LaunchWarnings({ run }: { run: SimulationRunRecord }) {
  const { t } = useTranslation();
  const warnings = run.readiness_warnings;
  return (
    <Section title={t("s15.launchWarnings")} defaultOpen={!!warnings?.length}
      aside={<span className="count" data-launch-warnings={warnings === undefined ? "not-recorded" : warnings.length}>{warnings === undefined ? t("s15.notRecorded") : warnings.length}</span>}>
      {warnings === undefined ? <p className="note">{t("s15.notRecordedNote")}</p>
        : warnings.length === 0 ? <p className="note">{t("s15.noWarnings")}</p>
        : <ul className="rules">{warnings.map((w, i) => <li key={`${w.rule_id}-${i}`}><span className="tag tag--draft">{w.rule_id}</span> {w.message}</li>)}</ul>}
    </Section>
  );
}

/** S10's result rules on the selected run, as glyph, rule id and message. */
function RuleList({ rules }: { rules: RuleResult[] }) {
  const { t } = useTranslation();
  return (
    <ul className="rules">
      {rules.map((r) => (
        <li key={r.id} className={`rules__item rules__item--${r.state}`}>
          {r.state === "pass" ? <GlyphValid /> : r.state === "fail" ? <GlyphBlocked /> : <GlyphInfo />}
          <span className="visually-hidden">{t(`report.state_${r.state}`)}</span>
          <code>{r.id}</code>
          <span>{r.message}</span>
        </li>
      ))}
    </ul>
  );
}

/** Results (F7, ADR 0016): one result model, charts from the shared options, S10 rules on screen. */
export function ResultsView() {
  const { t } = useTranslation();
  const { state } = useStore();
  const v = state.view!;
  const runs = v.bundle.simulation_runs;
  const [runId, setRunId] = useForm("results.run", runs[runs.length - 1]?.simulation_run_id ?? "");
  const [tab, setTab] = useForm("results.tab", "monthly");
  const [monthlyKind, setMonthlyKind] = useForm("results.monthlyKind", "production");
  const [heatVar, setHeatVar] = useForm("results.heatVar", "ac");
  const [month, setMonth] = useForm("results.month", "6");
  const run = runs.find((r) => r.simulation_run_id === runId) ?? runs[runs.length - 1];
  const s = run?.summary_result;
  const palette = useMemo(() => paletteFromTokens(), []);
  const months = useMemo(() => MONTH_KEYS.map((k) => t(`results.month_${k}`)), [t]);

  const base = useMemo(() => (run?.summary_result ? buildResultModel(v, run, { authority: DEMO ? "DEMO_SYNTHETIC" : "ENGINE", hourlyAcKw: null }) : null), [v, run, t]);
  const engineState = useEngineSeries(v.bundle.project.project_id, run);
  // The demo keeps its stamped synthetic year; the engine's series comes from the run's stored package (S15).
  const seriesState: SeriesState = useMemo(() => {
    if (!DEMO) return engineState;
    if (!base || base.dcKwp === null || !isAnnualResult(base) || !s) return { kind: "none" };
    const synthetic = demoSeries(base.dcKwp, base.acKw || 1);
    return { kind: "ready", series: fromDemo(synthetic, base.dcKwp, s.loss_summary.filter(l => l.loss_type !== "orientation_mismatch").slice(0, 8).map((l) => ({ lossType: l.loss_type, fraction: l.loss_fraction }))) };
  }, [engineState, base, s]);
  const series = seriesState.kind === "ready" ? seriesState.series : null;
  const model = useMemo(() => (run?.summary_result && base ? (series ? buildResultModel(v, run, { authority: series.authority, hourlyAcKw: series.ac }) : base) : null), [v, run, base, series]);
  const rules = useMemo(() => (model ? checkResultRules(model, { strings: v.bundle.electrical_design.strings.length }) : []), [model, v]);

  if (!run || !s || !model)
    return (
      <div className="results results--empty">
        <h2>{run ? t("results.unavailable") : t("results.none")}</h2>
        {run && "origin" in run && run.origin === "imported" && <p data-imported-run>{t("r1.importedRun")}</p>}
        {run?.detailed_electrical_shading && <DetailedExecutionStatus result={run.detailed_electrical_shading} />}
        {run?.detailed_electrical_shading?.attribution_energy_summary && <DetailedElectricalShading key={run.simulation_run_id} result={run.detailed_electrical_shading} />}
        <p>{t("results.noneHint")}</p>
      </div>
    );

  const annual = isAnnualResult(model);
  const energyLabel = annual ? t("results.referenceProduction") : t("results.kpiPeriodEnergy", { hours: model.periodHours });
  const kpiLabel = (key: string) => annual ? t(key) : t("results.periodKpi", { label: t(key), hours: model.periodHours });
  const production: BarSeries = { name: energyLabel, values: model.monthlyAcKwh, color: palette.series[0] };
  // A run shorter than a year opens the daily view on a month it covers.
  const covered = series ? coveredMonths(series) : [];
  const shownMonth = series && covered.length && !covered.includes(Number(month)) ? String(covered[0]) : month;
  const monthOf = (m: number[][]) => Array.from({ length: 12 }, (_, k) => m.reduce((t, row, i) => (series && Number(series.days[i].slice(5, 7)) - 1 === k ? t + row.reduce((a, b) => a + (Number.isFinite(b) ? b : 0), 0) : t), 0));
  const curtailed = series?.acBeforeLimit ? monthOf(series.acBeforeLimit).map((b, i) => b - monthOf(series.ac)[i]) : null;
  const counts = { pass: 0, fail: 0, unavailable: 0 };
  for (const r of rules) counts[r.state]++;

  const monthlyChart = (o: { series: BarSeries[]; unit: string; stacked?: boolean }) => (
    <EChart option={monthlyOption(palette, { months, aria: t("results.monthlyAria"), ...o })} label={t("results.monthlyAria")} height={300} />
  );

  return (
    <div className="results">
      <header className="results__head">
        <div>
          <h2>{t("results.title")}</h2>
          {run.detailed_electrical_shading && <DetailedExecutionStatus result={run.detailed_electrical_shading} />}
          <div className="sub">
            {run.simulation_run_id} · {s.period_start_time.slice(0, 10)} → {s.period_end_time.slice(0, 10)} · {t("results.weather", { name: run.weather_source?.source_product_name ?? run.weather_dataset_revision_id })}
          </div>
          <div className="results__authority">
            <span className={model.authority === "ENGINE" ? "tag tag--ok" : "tag tag--draft"} data-authority={model.authority}>
              {t(model.authority === "ENGINE" ? "report.authorityEngine" : "report.authoritySynthetic")}
            </span>
            <span className="sub">{t("results.uncertainty")}</span>
          </div>
        </div>
        <Select label={t("results.run")} value={run.simulation_run_id} onChange={setRunId} options={runs.map((r) => ({ value: r.simulation_run_id, label: `${r.simulation_run_id} · ${r.status}${runDesignBasis(v, r) === "earlier" ? ` · ${t("res1.earlierTag")}` : ""}` }))} />
      </header>
      {"origin" in run && run.origin === "imported" && <p data-imported-run>{t("r1.importedRun")}</p>}
      <MixedOrientationResults run={run} bundle={v.bundle} />
      {run.package_omitted && <div className="issue" role="status" data-package-omitted>{t("data1.packageOmitted")}</div>}
      {run.module_self_shading !== true && (
        <div className="issue issue--draft" role="status" data-row-shading="not-recorded">{t("res4d.legacyShading")}</div>
      )}
      {model.designBasis !== "current" && (
        <div className={model.designBasis === "earlier" ? "issue issue--draft" : "issue"} role="status" data-design-basis={model.designBasis}>
          {t(model.designBasis === "earlier" ? "res1.earlier" : "res1.unknown")} {t("res1.savedOnly")}
        </div>
      )}

      <div className="kpis">
        <div>
          <span>{energyLabel}</span>
          <strong>{annual ? fmt(model.annualAcKwh / 1000, 1) : fmt(model.periodAcKwh, 3)}</strong>
          <em>{annual ? "MWh" : "kWh"}</em>
        </div>
        <div>
          <span>{kpiLabel("results.kpiYield")}</span>
          <strong>{fmt(model.specificYield, 0)}</strong>
          <em>kWh/kWp</em>
        </div>
        <div>
          <span>{kpiLabel("results.kpiPr")}</span>
          <strong>{fmt(model.performanceRatio * 100, 1)}</strong>
          <em>%</em>
          <small>{t("results.prBasis")}</small>
        </div>
        <div>
          <span>{kpiLabel("results.kpiPeak")}</span>
          <strong>{fmt(model.peakAcKw, 1)}</strong>
          <em>kW</em>
        </div>
        <div>
          <span>{kpiLabel("results.kpiClipping")}</span>
          <strong>{fmt(annual ? model.clippingKwh / 1000 : model.clippingKwh, 2)}</strong>
          <em>{annual ? "MWh" : "kWh"}</em>
        </div>
        <div>
          <span>{t("results.kpiCurtailment")}</span>
          {curtailed ? (
            <>
              <strong>{fmt(curtailed.reduce((a, b) => a + b, 0) / 1000, 1)}</strong>
              <em>MWh</em>
              <DemoStamp />
            </>
          ) : (
            <>
              <strong>—</strong>
              <small data-curtailment="none">{t("use1.noExportLimit")}</small>
            </>
          )}
        </div>
      </div>

      <div className="results__tabs">
        <Segmented
          label={t("results.views")}
          value={tab}
          onChange={setTab}
          options={[
            { value: "monthly", label: t("results.tabMonthly") },
            { value: "losses", label: t("results.tabLosses") },
            { value: "heatmap", label: t("results.tabHeatmap") },
            { value: "daily", label: t("results.tabDaily") },
            { value: "ledger", label: t("results.tabAssumptions") }
          ]}
        />
      </div>

      {tab === "monthly" && (
        <div className="panel-card">
          <div className="panel-card__head">
            <Segmented
              label={t("results.monthlyKind")}
              value={monthlyKind}
              onChange={setMonthlyKind}
              options={[
                { value: "production", label: t("results.mProduction") },
                { value: "zeroexport", label: t("results.mZeroExport") },
                { value: "performance", label: t("results.mPerformance") },
                { value: "losses", label: t("results.mLosses") },
                { value: "meteo", label: t("results.mMeteo") }
              ]}
            />
          </div>
          {monthlyKind === "production" && (
            <>
              {monthlyChart({ series: [production], unit: "kWh" })}
              <p className="note">{t("results.productionNote")}</p>
            </>
          )}
          {monthlyKind === "zeroexport" &&
            (series && curtailed ? (
              <>
                <DemoStamp />
                {monthlyChart({
                  stacked: true,
                  unit: "kWh",
                  series: [
                    { name: t("results.delivered"), values: monthOf(series.ac), color: palette.series[0] },
                    { name: t("results.curtailed"), values: curtailed, color: palette.loss }
                  ]
                })}
                <p className="note">{t("results.zeroExportNote")}</p>
              </>
            ) : (
              <NeedsSeries state="export_limit" />
            ))}
          {monthlyKind === "performance" && (
            <>
              {model.dcKwp === null ? <p className="note" data-design-basis-hidden>{t("res1.noCapacity")}</p> : <>
                {monthlyChart({ series: [{ name: t("results.kpiYield"), values: model.monthlyAcKwh.map((e) => e / Math.max(model.dcKwp!, 1e-9)), color: palette.series[1] }], unit: "kWh/kWp" })}
                <p className="note">{t("results.performanceNote", { kwp: model.dcKwp.toFixed(2) })}</p>
                {series ? <div data-monthly-pr>
                  {series.authority === "DEMO_SYNTHETIC" && <DemoStamp />}
                  {monthlyChart({ series: [{ name: t("results.kpiPr"), values: series.monthly.performanceRatio.map((x) => x * 100), color: palette.series[2] }], unit: "%" })}
                  <p className="note">{t("s15.prNote")}</p>
                </div> : <NeedsSeries state={seriesState} />}
              </>}
            </>
          )}
          {monthlyKind === "losses" &&
            (series ? (
              <div data-monthly-losses={series.authority}>
                {series.authority === "DEMO_SYNTHETIC" && <DemoStamp />}
                {monthlyChart({
                  stacked: true,
                  unit: "kWh",
                  series: largestLosses(series, 8, run.mixed_orientation ? "orientation_mismatch" : undefined).map((l, i) => ({
                    name: t(`losses.stages.${l.lossType}`, { defaultValue: l.lossType.replace(/_/g, " ") }),
                    values: l.values,
                    color: palette.series[(i + 2) % palette.series.length]
                  }))
                })}
                <p className="note">{t(series.authority === "ENGINE" ? "s15.monthlyLossesEngine" : "results.monthlyLossesNote")}</p>
              </div>
            ) : (
              <NeedsSeries state={seriesState} />
            ))}
          {monthlyKind === "meteo" &&
            (series ? (
              <div data-monthly-meteo={series.authority}>
                {series.authority === "DEMO_SYNTHETIC" && <DemoStamp />}
                {monthlyChart({ series: [
                  { name: t("results.poa"), values: series.monthly.poaKwhM2, color: palette.series[3] },
                  ...(series.monthly.ghiKwhM2.some(Number.isFinite) ? [{ name: t("s15.ghi"), values: series.monthly.ghiKwhM2, color: palette.series[4] }] : [])
                ], unit: "kWh/m²" })}
              </div>
            ) : (
              <NeedsSeries state={seriesState} />
            ))}
        </div>
      )}

      {tab === "losses" && (
        <div className="panel-card">
          <p className="note">{t("results.lossesNote")}</p>
          {model.losses.length ? (
            <EChart
              option={waterfallOption(palette, {
                start: { label: t("results.reference"), value: model.referenceKwh ?? 0 },
                losses: model.losses.map((l) => ({ label: t(`losses.stages.${l.label.replaceAll(" ", "_")}`, { defaultValue: l.label }), value: l.lossKwh })),
                end: { label: energyLabel, value: annual ? model.annualAcKwh : model.periodAcKwh },
                unit: "kWh",
                aria: t("results.waterfallAria")
              })}
              label={t("results.waterfallAria")}
              height={360}
            />
          ) : (
            <div className="empty">{t("results.noLedger")}</div>
          )}
          {run.mixed_orientation && <table className="tbl" aria-label={t("use5b.lossTable")}>
            <thead><tr><th>{t("use5b.loss")}</th><th>{t("use5b.energy")}</th></tr></thead>
            <tbody>{s.loss_summary.map(l => <tr key={l.loss_type} data-loss-type={l.loss_type}>
              <th scope="row">{t(`losses.stages.${l.loss_type}`, { defaultValue: l.loss_type.replaceAll("_", " ") })}</th>
              <td data-loss-wh={l.lost_energy_wh}>{fmt(l.lost_energy_wh/1000, 3)}</td>
            </tr>)}</tbody>
          </table>}
          <p className="note">{t("results.stages", { list: [...new Set(s.loss_summary.map((l) => l.stage))].join(", ") })}</p>
        </div>
      )}

      {tab === "heatmap" && (
        <div className="panel-card">
          <div className="panel-card__head">
            <Segmented
              label={t("results.heatVar")}
              value={heatVar}
              onChange={setHeatVar}
              options={[
                { value: "ac", label: t("results.hAc") },
                { value: "poa", label: t("results.poa") },
                { value: "curt", label: t("results.curtailed") },
                { value: "tcell", label: t("results.hTcell") }
              ]}
            />
            {series?.authority === "DEMO_SYNTHETIC" && <DemoStamp />}
          </div>
          {series && heatVar === "curt" && !series.acBeforeLimit ? <NeedsSeries state="export_limit" /> : series ? (
            (() => {
              const before = series.acBeforeLimit;
              const m =
                heatVar === "ac"
                  ? series.ac
                  : heatVar === "poa"
                    ? series.poa
                    : heatVar === "curt" && before
                      ? before.map((d, i) => d.map((x, h) => x - series.ac[i][h]))
                      : series.tcell;
              const unit = heatVar === "poa" ? "W/m²" : heatVar === "tcell" ? "°C" : "kW";
              const w = weeklyHeatmap(m);
              return (
                <>
                  <EChart option={heatmapOption(palette, { values: w.values, unit, hourLabel: t("results.hour"), weekLabel: t("results.week"), aria: t("results.heatmapAria") })} label={t("results.heatmapAria")} height={320} />
                  <p className="note" data-coverage>
                    {t("results.heatmapCoverage", { shown: w.coverage.weeklyShown.toLocaleString("en-US"), excluded: w.coverage.weeklyExcluded, source: w.coverage.sourceHours.toLocaleString("en-US"), missing: w.coverage.missingHours })}
                  </p>
                </>
              );
            })()
          ) : (
            <NeedsSeries state={seriesState} />
          )}
        </div>
      )}

      {tab === "daily" && (
        <div className="panel-card">
          <div className="panel-card__head">
            <Select label={t("results.month")} value={shownMonth} onChange={setMonth} options={months.map((m, i) => ({ value: String(i), label: t("results.averageDay", { month: m }) }))} />
            {series?.authority === "DEMO_SYNTHETIC" && <DemoStamp />}
          </div>
          {series && !coveredMonths(series).includes(Number(shownMonth)) ? <p className="note" data-month-uncovered>{t("s15.monthNotCovered")}</p> : series ? (
            (() => {
              const before = series.acBeforeLimit, load = series.load;
              const lines = [
                ...(before ? [{ name: t("results.acBefore"), color: palette.series[2], values: meanDayOfMonth(series, before, Number(shownMonth)) }] : []),
                { name: before ? t("results.acAfter") : t("results.referenceProductionPower"), color: palette.series[0], values: meanDayOfMonth(series, series.ac, Number(shownMonth)) },
                ...(load ? [{ name: t("results.load"), color: palette.series[4], values: meanDayOfMonth(series, load, Number(shownMonth)) }] : [])
              ];
              return (
                <>
                  <UPlotLines x={Array.from({ length: 24 }, (_, h) => h)} lines={lines} unit="kW" label={t("results.dailyAria")} font={palette.font} axis={palette.muted} grid={palette.grid} />
                  <Legend items={lines} />
                </>
              );
            })()
          ) : (
            <NeedsSeries state={seriesState} />
          )}
        </div>
      )}

      {tab === "ledger" && (
        <div className="panel-card">
          {model.assumptions.length === 0 && <div className="empty">{t("results.noAssumptions")}</div>}
          <table className="tbl">
            <tbody>
              {model.assumptions.map((a, i) => (
                <tr key={a.id || i}>
                  <td>{a.id}</td>
                  <td>
                    <span className={a.severity === "warning" ? "tag tag--draft" : "tag"}>{a.severity}</span>
                  </td>
                  <td>{a.statement}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Section
        title={t("results.checksTitle")}
        defaultOpen={counts.fail > 0}
        aside={<span className={counts.fail ? "count count--blocked" : "count"} data-rule-fails={counts.fail}>{t("results.checksSummary", counts)}</span>}
      >
        <p className="note">{t("results.checksNote")}</p>
        <RuleList rules={rules} />
      </Section>
      <LaunchWarnings run={run} />
      <Section title={t("results.pxxSection")}><AnnualPxxCard run={run} /></Section>

      <Section title={t("results.invertersSection")}><InverterResultsTable rows={inverterResultRows(v, run)} summary={s} /></Section>
      <Section title={t("results.settingsSection")}><RunLossSettings run={run} /><RunOpticsThermalSettings run={run} /><RunShadingAccuracy run={run} /></Section>

      {run.detailed_electrical_shading?.attribution_energy_summary && (
        <Section title={t("results.detailedSection")}>
          <div className="panel-card" aria-label={t("results.boundaries")}>
            <table className="tbl">
              <tbody>
                <tr>
                  <th>{t("results.bGeometric")}</th>
                  <td>{t("results.bGeometricNote")}</td>
                </tr>
                <tr>
                  <th>{t("results.bDetailed")}</th>
                  <td>{t("results.bDetailedNote")}</td>
                </tr>
                <tr>
                  <th>{t("results.bDownstream")}</th>
                  <td>{t("results.bDownstreamNote")}</td>
                </tr>
                <tr>
                  <th>{t("results.bPcc")}</th>
                  <td>{t("results.bPccNote")}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <DetailedElectricalShading key={run.simulation_run_id} result={run.detailed_electrical_shading} />
        </Section>
      )}
    </div>
  );
}
