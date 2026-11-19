import { useMemo } from "react";
import { DEMO } from "../client";
import { demoSeries, monthlyMeanDay, monthlySum } from "../demo/series";
import { useForm, useStore } from "../state/store";
import { fmt, NotWired, Segmented, Select } from "../ui/kit";
import { DailyProfile, Heatmap, Legend, MonthlyBars, Series, Waterfall, WaterfallStep } from "./charts";

const C = { prod: "#1d4f8f", curt: "#d98e04", load: "#56657a", pr: "#0f7a6c", ghi: "#c08a00", poa: "#d98e04", temp: "#a33a5b" };
const LOSS_COLORS = ["#1d4f8f", "#2f6fbf", "#0f7a6c", "#4f8a2f", "#7a4fa3", "#a8641a", "#a33a5b", "#56657a", "#c08a00", "#1b8aa8"];

function DemoStamp() {
  return <span className="demo-stamp" title="Synthetic data generated in the browser to preview this chart. Not a simulation result.">Demo data</span>;
}

function NeedsSeries() {
  return (
    <div className="empty-chart">
      <NotWired id="timeSeries" />
      <p>This view needs the run time-series endpoint. It renders here as soon as the engine exposes it.</p>
    </div>
  );
}

export function ResultsView() {
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

  const kwp = state.modules.length * 0.55;
  const acKw = v.bundle.electrical_design.inverter_instances.reduce((t, i) => t + (v.catalog.inverters.find((x) => x.revision_id === i.inverter_definition_revision_id)?.nominal_ac_power_w ?? 0) / 1000, 0);
  const series = useMemo(() => (DEMO ? demoSeries(kwp, acKw || 1) : null), [kwp, acKw]);

  if (!run || !s)
    return (
      <div className="results results--empty">
        <h2>No results yet</h2>
        <p>Run a simulation from the Simulate step. Results appear here with monthly charts, the loss diagram, a heatmap and daily profiles.</p>
      </div>
    );

  const production: Series = { name: "AC energy", color: C.prod, values: s.monthly_energy.map((m) => m.energy_wh / 1000) };
  const curtailed = series ? monthlySum(series.acBefore).map((b, i) => b - monthlySum(series.acAfter)[i]) : null;

  const steps: WaterfallStep[] = s.loss_summary.length
    ? [
        { label: "Reference energy", value: s.loss_summary[0].reference_energy_wh / 1000, kind: "start" },
        ...s.loss_summary.map((l) => ({ label: l.loss_type.replace(/_/g, " "), value: -l.lost_energy_wh / 1000, kind: "loss" as const })),
        { label: "AC energy", value: s.total_energy_wh / 1000, kind: "end" }
      ]
    : [];

  return (
    <div className="results">
      <header className="results__head">
        <div>
          <h2>Results</h2>
          <div className="sub">
            {run.simulation_run_id} · {s.period_start_time.slice(0, 10)} → {s.period_end_time.slice(0, 10)} · weather {run.weather_source?.source_product_name ?? run.weather_dataset_revision_id}
          </div>
        </div>
        <Select value={run.simulation_run_id} onChange={setRunId} options={runs.map((r) => ({ value: r.simulation_run_id, label: `${r.simulation_run_id} · ${r.status}` }))} />
      </header>

      <div className="kpis">
        <div>
          <span>AC energy</span>
          <strong>{fmt(s.total_energy_wh / 1e6, 1)}</strong>
          <em>MWh</em>
        </div>
        <div>
          <span>Specific yield</span>
          <strong>{fmt(s.specific_yield_wh_per_wp, 0)}</strong>
          <em>kWh/kWp</em>
        </div>
        <div>
          <span>Performance ratio</span>
          <strong>{fmt(s.performance_ratio * 100, 1)}</strong>
          <em>%</em>
          <small>Basis not reported by the API</small>
        </div>
        <div>
          <span>Peak AC</span>
          <strong>{fmt(s.peak_ac_power_w / 1000, 1)}</strong>
          <em>kW</em>
        </div>
        <div>
          <span>Clipping</span>
          <strong>{fmt(s.clipping_energy_wh / 1e6, 2)}</strong>
          <em>MWh</em>
        </div>
        <div>
          <span>Zero-export curtailment</span>
          {curtailed ? (
            <>
              <strong>{fmt(curtailed.reduce((a, b) => a + b, 0) / 1000, 1)}</strong>
              <em>MWh</em>
              <DemoStamp />
            </>
          ) : (
            <NotWired id="zeroExport" compact />
          )}
        </div>
      </div>

      <div className="results__tabs">
        <Segmented
          value={tab}
          onChange={setTab}
          options={[
            { value: "monthly", label: "Monthly" },
            { value: "losses", label: "Loss diagram" },
            { value: "heatmap", label: "Heatmap" },
            { value: "daily", label: "Daily profile" },
            { value: "ledger", label: "Assumptions" }
          ]}
        />
      </div>

      {tab === "monthly" && (
        <div className="panel-card">
          <div className="panel-card__head">
            <Segmented
              value={monthlyKind}
              onChange={setMonthlyKind}
              options={[
                { value: "production", label: "Production" },
                { value: "zeroexport", label: "Zero export" },
                { value: "performance", label: "Performance" },
                { value: "losses", label: "Losses" },
                { value: "meteo", label: "Meteo" }
              ]}
            />
          </div>
          {monthlyKind === "production" && (
            <>
              <MonthlyBars series={[production]} unit="kWh" />
              <Legend series={[production]} />
              <p className="note">From the run's monthly energy (wired). Whether this is before or after zero export is not stated by the API yet.</p>
            </>
          )}
          {monthlyKind === "zeroexport" &&
            (series ? (
              <>
                <DemoStamp />
                <MonthlyBars
                  stacked
                  unit="kWh"
                  series={[
                    { name: "Delivered after zero export", color: C.prod, values: monthlySum(series.acAfter) },
                    { name: "Curtailed", color: C.curt, values: curtailed! }
                  ]}
                />
                <Legend series={[{ name: "Delivered after zero export", color: C.prod, values: [] }, { name: "Curtailed", color: C.curt, values: [] }]} />
                <p className="note">Both series come from the same synthetic hourly profile, so they are consistent with each other but not with the KPIs above.</p>
              </>
            ) : (
              <NeedsSeries />
            ))}
          {monthlyKind === "performance" &&
            (series ? (
              <>
                <DemoStamp />
                <MonthlyBars
                  series={[
                    {
                      name: "Specific yield",
                      color: C.pr,
                      values: production.values.map((e) => e / Math.max(kwp, 1e-9))
                    }
                  ]}
                  unit="kWh/kWp"
                />
                <p className="note">Monthly specific yield from wired monthly energy; monthly PR needs the time-series endpoint.</p>
              </>
            ) : (
              <NeedsSeries />
            ))}
          {monthlyKind === "losses" &&
            (series ? (
              <>
                <DemoStamp />
                <MonthlyBars
                  stacked
                  unit="kWh"
                  series={s.loss_summary.slice(0, 8).map((l, i) => ({
                    name: l.loss_type.replace(/_/g, " "),
                    color: LOSS_COLORS[i % LOSS_COLORS.length],
                    values: production.values.map((e) => (e * l.loss_fraction) / (1 - l.loss_fraction))
                  }))}
                />
                <Legend series={s.loss_summary.slice(0, 8).map((l, i) => ({ name: l.loss_type.replace(/_/g, " "), color: LOSS_COLORS[i % LOSS_COLORS.length], values: [] }))} />
              </>
            ) : (
              <NeedsSeries />
            ))}
          {monthlyKind === "meteo" &&
            (series ? (
              <>
                <DemoStamp />
                <MonthlyBars series={[{ name: "POA", color: C.poa, values: monthlySum(series.poa).map((x) => x / 1000) }]} unit="kWh/m²" />
                <Legend series={[{ name: "POA irradiation (demo)", color: C.poa, values: [] }]} />
              </>
            ) : (
              <NeedsSeries />
            ))}
        </div>
      )}

      {tab === "losses" && (
        <div className="panel-card">
          {steps.length ? <Waterfall steps={steps} unit="kWh" /> : <div className="empty">This run reported no loss ledger.</div>}
          <p className="note">From the run's loss ledger (wired). Stages: {[...new Set(s.loss_summary.map((l) => l.stage))].join(", ")}.</p>
        </div>
      )}

      {tab === "heatmap" && (
        <div className="panel-card">
          <div className="panel-card__head">
            <Segmented
              value={heatVar}
              onChange={setHeatVar}
              options={[
                { value: "ac", label: "AC after zero export" },
                { value: "poa", label: "POA" },
                { value: "curt", label: "Curtailment" },
                { value: "tcell", label: "Cell temperature" }
              ]}
            />
            {series && <DemoStamp />}
          </div>
          {series ? (
            (() => {
              const m =
                heatVar === "ac"
                  ? series.acAfter
                  : heatVar === "poa"
                    ? series.poa
                    : heatVar === "curt"
                      ? series.acBefore.map((d, i) => d.map((x, h) => x - series.acAfter[i][h]))
                      : series.tcell;
              const unit = heatVar === "poa" ? "W/m²" : heatVar === "tcell" ? "°C" : "kW";
              const max = Math.max(...m.flat());
              return <Heatmap values={m} max={max} unit={unit} timeBasis="Local standard time, interval start" />;
            })()
          ) : (
            <NeedsSeries />
          )}
        </div>
      )}

      {tab === "daily" && (
        <div className="panel-card">
          <div className="panel-card__head">
            <Select value={month} onChange={setMonth} options={["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].map((m, i) => ({ value: String(i), label: `Average day · ${m}` }))} />
            {series && <DemoStamp />}
          </div>
          {series ? (
            <>
              <DailyProfile
                unit="kW"
                lines={[
                  { name: "AC before zero export", color: "#9fb3c8", values: monthlyMeanDay(series.acBefore, Number(month)) },
                  { name: "AC after zero export", color: C.prod, values: monthlyMeanDay(series.acAfter, Number(month)) },
                  { name: "Load", color: C.load, values: monthlyMeanDay(series.load, Number(month)) }
                ]}
              />
              <Legend
                series={[
                  { name: "AC before zero export", color: "#9fb3c8", values: [] },
                  { name: "AC after zero export", color: C.prod, values: [] },
                  { name: "Load", color: C.load, values: [] }
                ]}
              />
            </>
          ) : (
            <NeedsSeries />
          )}
        </div>
      )}

      {tab === "ledger" && (
        <div className="panel-card">
          {(run.assumptions ?? []).length === 0 && <div className="empty">No assumptions recorded for this run.</div>}
          <table className="tbl">
            <tbody>
              {(run.assumptions ?? []).map((a, i) => (
                <tr key={a.assumption_id ?? i}>
                  <td>{a.assumption_id}</td>
                  <td>
                    <span className={a.severity === "warning" ? "tag tag--draft" : "tag"}>{a.severity ?? "info"}</span>
                  </td>
                  <td>{a.statement}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
