import { useEffect, useState } from "react";
import { engine } from "../client";
import { OpticsThermalPanel } from "./OpticsThermalPanel";
import { LossesPanel } from "./LossesPanel";
import { ShadingAccuracyPanel } from "./ShadingAccuracyPanel";
import { useTranslation } from "react-i18next";
import type { SimulationDefaults } from "../types";
import { useForm, useStore } from "../state/store";
import { Field, Kv, NumberInput, Paid, PendingBlock, Section, Select } from "../ui/kit";

interface LoadPreview {
  name: string;
  rows: number;
  medianStepMin: number | null;
  min: number;
  max: number;
  mean: number;
  firstStamp: string;
  lastStamp: string;
  gaps: number;
}

function previewLoadCsv(name: string, text: string): LoadPreview | string {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  if (lines.length < 3) return "The file needs a header and at least two rows.";
  const rows = lines.slice(1).map((l) => l.split(/[,;\t]/));
  const stamps = rows.map((r) => Date.parse(r[0]));
  const vals = rows.map((r) => Number(r[1]));
  if (stamps.some((s) => Number.isNaN(s))) return "Column 1 must be a timestamp (ISO 8601 recommended).";
  if (vals.some((x) => !Number.isFinite(x))) return "Column 2 must be numeric.";
  const steps: number[] = [];
  for (let i = 1; i < stamps.length; i++) steps.push((stamps[i] - stamps[i - 1]) / 60000);
  const sorted = [...steps].sort((a, b) => a - b);
  const med = sorted.length ? sorted[Math.floor(sorted.length / 2)] : null;
  const gaps = med ? steps.filter((s) => s > med * 1.5).length : 0;
  return {
    name,
    rows: rows.length,
    medianStepMin: med,
    min: Math.min(...vals),
    max: Math.max(...vals),
    mean: vals.reduce((a, b) => a + b, 0) / vals.length,
    firstStamp: rows[0][0],
    lastStamp: rows[rows.length - 1][0],
    gaps
  };
}

export function LossesGridPanel() {
  const { state } = useStore();
  const v = state.view!;
  const { t } = useTranslation();
  const [defaults, setDefaults] = useState<SimulationDefaults | null>(null);
  const [defaultsFailed, setDefaultsFailed] = useState(false);
  useEffect(() => {
    let active = true;
    engine.simulationDefaults().then((values) => { if (active) setDefaults(values); }).catch(() => { if (active) setDefaultsFailed(true); });
    return () => { active = false; };
  }, []);
  const [load, setLoad] = useForm<{ preview: LoadPreview | null; error: string | null; quantity: string; convention: string; tz: string; yearMap: string }>("meteo.load", {
    preview: null,
    error: null,
    quantity: "kw",
    convention: "interval_start",
    tz: v.bundle.project.site.timezone,
    yearMap: "month_day_time"
  });
  const [zx, setZx] = useForm("meteo.zeroexport", { enabled: true, setpoint: 0, point: "pcc", allocation: "proportional", phase: "aggregate" });

  return (
    <>
      <Section primary title={t("sections.losses")}>
        {defaults ? <><AppliedDefaults values={defaults} /><LossesPanel defaults={defaults.loss_settings} /></> : <p role="status">{t(defaultsFailed ? "s7d.defaultsUnavailable" : "s7d.defaultsLoading")}</p>}
      </Section>

      <Section title={t("sections.opticsThermal")}>
        {defaults ? <OpticsThermalPanel defaults={defaults.optics_thermal_settings} /> : <p role="status">{t(defaultsFailed ? "s7d.defaultsUnavailable" : "s7d.defaultsLoading")}</p>}
      </Section>
      <ShadingAccuracyPanel />

      <Section title={t("sections.loadExport")}>
        <PendingBlock id="loadProfile" note="The file is previewed in the browser. Declarations are required, never inferred.">
          <Field label="CSV: timestamp, value">
            <input
              className="input"
              type="file"
              accept=".csv,.txt"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                file.text().then((t) => {
                  const p = previewLoadCsv(file.name, t);
                  setLoad(typeof p === "string" ? { ...load, preview: null, error: p } : { ...load, preview: p, error: null });
                });
              }}
            />
          </Field>
          {load.error && <div className="issue issue--blocking">{load.error}</div>}
          {load.preview && (
            <Kv
              rows={[
                ["File", load.preview.name],
                ["Rows", load.preview.rows.toLocaleString()],
                ["Median step", load.preview.medianStepMin ? `${load.preview.medianStepMin} min` : "—"],
                ["Gaps (> 1.5× step)", String(load.preview.gaps)],
                ["Range", `${load.preview.firstStamp} → ${load.preview.lastStamp}`],
                ["Min / mean / max", `${load.preview.min.toFixed(1)} / ${load.preview.mean.toFixed(1)} / ${load.preview.max.toFixed(1)}`]
              ]}
            />
          )}
          <div className="grid2">
            <Field label="Quantity">
              <Select value={load.quantity} onChange={(quantity) => setLoad({ ...load, quantity })} options={[{ value: "kw", label: "Power (kW)" }, { value: "kwh", label: "Energy per interval (kWh)" }]} />
            </Field>
            <Field label="Timestamp marks">
              <Select
                value={load.convention}
                onChange={(convention) => setLoad({ ...load, convention })}
                options={[
                  { value: "interval_start", label: "Interval start" },
                  { value: "interval_end", label: "Interval end" },
                  { value: "instant", label: "Instantaneous sample" }
                ]}
              />
            </Field>
            <Field label="Timezone">
              <input className="input" value={load.tz} onChange={(e) => setLoad({ ...load, tz: e.target.value })} />
            </Field>
            <Field label="Year alignment">
              <Select value={load.yearMap} onChange={(yearMap) => setLoad({ ...load, yearMap })} options={[{ value: "month_day_time", label: "Month-day-time, Feb 29 dropped" }, { value: "exact", label: "Exact timestamps" }]} />
            </Field>
          </div>
        </PendingBlock>

        <PendingBlock id="zeroExport" note="Curtailment runs at the finest resolution shared by the simulation and the load. Coarser data under-estimates curtailment; the resolution used is reported.">
          <div className="grid2">
            <Field label="Export limit" unit="kW">
              <NumberInput value={zx.setpoint} step={0.5} onChange={(setpoint) => setZx({ ...zx, setpoint })} />
            </Field>
            <Field label="Measured at">
              <Select value={zx.point} onChange={(point) => setZx({ ...zx, point })} options={[{ value: "pcc", label: "PCC (point of common coupling)" }, { value: "inverter_ac", label: "Inverter AC terminals" }]} />
            </Field>
            <Field label="Curtailment allocation">
              <Select value={zx.allocation} onChange={(allocation) => setZx({ ...zx, allocation })} options={[{ value: "proportional", label: "Proportional to available power" }]} />
            </Field>
            <Field label="Phase handling">
              <Select
                value={zx.phase}
                onChange={(phase) => setZx({ ...zx, phase })}
                options={[
                  { value: "aggregate", label: "Aggregate three-phase" },
                  { value: "per_phase", label: "Per phase (RST) — Pro", disabled: true }
                ]}
              />
            </Field>
          </div>
          <div className="sub">
            Per-phase limiting and RST balance <Paid what="Per-phase limiting" />
          </div>
        </PendingBlock>
      </Section>
    </>
  );
}

export function AppliedDefaults({ values }: { values: SimulationDefaults }) {
  const { t } = useTranslation();
  const percent = (fraction: number) => Number((fraction * 100).toPrecision(15));
  return <>
    <p>{t("s7d.applied")}{values.demo ? ` · ${t("s7d.demoValues")}` : ""}</p>
    <p>{t("s7d.moduleQualitySource", { fallback: percent(values.module_quality.fallback_loss_fraction) })}</p>

  </>;
}
