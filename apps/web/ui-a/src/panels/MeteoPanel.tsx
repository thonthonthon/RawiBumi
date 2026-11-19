import { useEffect, useState } from "react";
import { engine } from "../client";
import type { WeatherSource } from "../types";
import { useForm, useStore } from "../state/store";
import { Button, Field, Kv, NumberInput, Paid, PendingBlock, Section, Segmented, Select } from "../ui/kit";

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

export function MeteoPanel({ onImport }: { onImport: () => void }) {
  const { state, dispatch, run, toast } = useStore();
  const v = state.view!;
  const pid = v.bundle.project.project_id;
  const [sources, setSources] = useState<WeatherSource[]>([]);
  const [wx, setWx] = useForm("meteo.acquire", { source: "", start: "2025-01-01", end: "2025-12-31" });
  const [timestep, setTimestep] = useForm("meteo.timestep", "60");
  const [losses, setLosses] = useForm("meteo.losses", { albedo: 0.2, soiling: 2, lid: 1.5, quality: -0.4, mismatch: 1, dcOhmic: 1.5, acOhmic: 0.5, availability: 99.5, degradation: 0.4 });
  const [load, setLoad] = useForm<{ preview: LoadPreview | null; error: string | null; quantity: string; convention: string; tz: string; yearMap: string }>("meteo.load", {
    preview: null,
    error: null,
    quantity: "kw",
    convention: "interval_start",
    tz: v.bundle.project.site.timezone,
    yearMap: "month_day_time"
  });
  const [zx, setZx] = useForm("meteo.zeroexport", { enabled: true, setpoint: 0, point: "pcc", allocation: "proportional", phase: "aggregate" });

  useEffect(() => {
    engine
      .weatherSources()
      .then((s) => {
        setSources(s);
        if (!wx.source && s[0]) setWx({ ...wx, source: s[0].source_id });
      })
      .catch(() => setSources([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sel = v.bundle.weather_selection;
  const L = (k: keyof typeof losses, label: string, unit: string, step = 0.1) => (
    <Field label={label} unit={unit} key={k}>
      <NumberInput value={losses[k]} step={step} onChange={(x) => setLosses({ ...losses, [k]: x })} />
    </Field>
  );

  return (
    <>
      <Section title="Weather">
        {sel ? (
          <Kv
            rows={[
              ["Dataset", sel.name ?? sel.source_id ?? sel.revision_id],
              ["Period", `${sel.start_time?.slice(0, 10) ?? "—"} → ${sel.end_time?.slice(0, 10) ?? "—"}`],
              ["QC", sel.data_quality_status ?? "unknown"],
              ["Revision", sel.revision_id]
            ]}
          />
        ) : (
          <div className="issue issue--blocking">No weather dataset. Acquire one or import a file.</div>
        )}
        <Field label="Source product">
          <Select value={wx.source} onChange={(source) => setWx({ ...wx, source })} options={sources.map((s) => ({ value: s.source_id, label: s.label }))} />
        </Field>
        <div className="grid2">
          <Field label="Start">
            <input className="input" type="date" value={wx.start} onChange={(e) => setWx({ ...wx, start: e.target.value })} />
          </Field>
          <Field label="End">
            <input className="input" type="date" value={wx.end} onChange={(e) => setWx({ ...wx, end: e.target.value })} />
          </Field>
        </div>
        <div className="row">
          <Button
            small
            tone="primary"
            disabled={!wx.source}
            onClick={async () => {
              const r = await run("Acquiring weather", async () => {
                await engine.acquireWeather(pid, { source_id: wx.source, start_date: wx.start, end_date: wx.end });
                return engine.project(pid);
              });
              if (r) {
                dispatch({ type: "setView", view: r });
                toast("ok", "Weather revision pinned.");
              }
            }}
          >
            Acquire
          </Button>
          <Button small onClick={onImport}>
            Import TMY3 / EPW / MET CSV…
          </Button>
        </div>
        <Field label="Simulation timestep" unit="min">
          <Segmented value={timestep} onChange={setTimestep} options={["1", "5", "15", "60"].map((t) => ({ value: t, label: t }))} />
        </Field>
        <p className="note">Sub-hourly from hourly weather uses interval-mean-hold: no invented intra-hour variability. The temporal origin is carried into exports.</p>
      </Section>

      <Section title="Losses and settings">
        <PendingBlock id="losses" note="Values are kept in this session until the endpoint exists; the engine currently applies its own defaults.">
          <div className="grid2">
            {L("albedo", "Albedo", "–", 0.01)}
            {L("soiling", "Soiling", "%")}
            {L("lid", "LID", "%")}
            {L("quality", "Module quality (negative = gain)", "%")}
            {L("mismatch", "Mismatch", "%")}
            {L("dcOhmic", "DC ohmic at STC", "%")}
            {L("acOhmic", "AC ohmic", "%")}
            {L("availability", "Availability", "%")}
            {L("degradation", "Degradation", "%/yr")}
          </div>
        </PendingBlock>
      </Section>

      <Section title="Load profile">
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
      </Section>

      <Section title="Zero export">
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
