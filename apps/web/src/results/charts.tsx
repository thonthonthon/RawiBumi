import { useEffect, useRef } from "react";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}

export interface Series {
  name: string;
  color: string;
  values: number[];
}

export function MonthlyBars({ series, unit, stacked = false, height = 300 }: { series: Series[]; unit: string; stacked?: boolean; height?: number }) {
  const W = 960;
  const H = height;
  const pad = { l: 56, r: 12, t: 16, b: 30 };
  const totals = MONTHS.map((_, i) => (stacked ? series.reduce((t, s) => t + (s.values[i] ?? 0), 0) : Math.max(...series.map((s) => s.values[i] ?? 0))));
  const max = niceMax(Math.max(...totals));
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  const slot = (W - pad.l - pad.r) / 12;
  const barW = stacked ? slot * 0.62 : (slot * 0.72) / series.length;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Monthly chart in ${unit}`}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className="chart__grid" />
          <text x={pad.l - 6} y={y(t)} className="chart__tick" textAnchor="end" dominantBaseline="middle">
            {t >= 1000 ? `${(t / 1000).toLocaleString()}k` : t.toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </text>
        </g>
      ))}
      <text x={12} y={pad.t} className="chart__unit">
        {unit}
      </text>
      {MONTHS.map((m, i) => {
        const x0 = pad.l + i * slot + (slot - (stacked ? barW : barW * series.length)) / 2;
        let acc = 0;
        return (
          <g key={m}>
            {series.map((s, k) => {
              const v = s.values[i] ?? 0;
              const r = stacked ? (
                <rect key={s.name} x={x0} y={y(acc + v)} width={barW} height={Math.max(0, y(acc) - y(acc + v))} fill={s.color}>
                  <title>{`${m} · ${s.name}: ${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} ${unit}`}</title>
                </rect>
              ) : (
                <rect key={s.name} x={x0 + k * barW} y={y(v)} width={barW - 1} height={Math.max(0, y(0) - y(v))} fill={s.color}>
                  <title>{`${m} · ${s.name}: ${v.toLocaleString(undefined, { maximumFractionDigits: 1 })} ${unit}`}</title>
                </rect>
              );
              acc += v;
              return r;
            })}
            <text x={pad.l + i * slot + slot / 2} y={H - 10} className="chart__tick" textAnchor="middle">
              {m}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function Legend({ series }: { series: Series[] }) {
  return (
    <div className="legend">
      {series.map((s) => (
        <span key={s.name}>
          <i style={{ background: s.color }} />
          {s.name}
        </span>
      ))}
    </div>
  );
}

export interface WaterfallStep {
  label: string;
  value: number; // negative = loss
  kind: "start" | "loss" | "end";
}

export function Waterfall({ steps, unit }: { steps: WaterfallStep[]; unit: string }) {
  const W = 960;
  const rowH = 26;
  const H = steps.length * rowH + 30;
  const pad = { l: 170, r: 110 };
  const start = steps[0]?.value ?? 1;
  const x = (v: number) => pad.l + ((W - pad.l - pad.r) * v) / start;
  let run = start;
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Loss diagram">
      {steps.map((s, i) => {
        const yy = 10 + i * rowH;
        let x0 = 0;
        let x1 = 0;
        if (s.kind === "start" || s.kind === "end") {
          x0 = x(0);
          x1 = x(s.value);
        } else {
          x1 = x(run);
          run += s.value;
          x0 = x(run);
        }
        const pct = s.kind === "loss" ? `${((s.value / (run - s.value)) * 100).toFixed(1)} %` : "";
        return (
          <g key={s.label + i}>
            <text x={pad.l - 8} y={yy + rowH / 2} className="chart__label" textAnchor="end" dominantBaseline="middle">
              {s.label}
            </text>
            <rect x={x0} y={yy + 4} width={Math.max(1, x1 - x0)} height={rowH - 8} className={s.kind === "loss" ? "wf wf--loss" : "wf wf--total"} />
            <text x={Math.max(x1, x0) + 6} y={yy + rowH / 2} className="chart__tick" dominantBaseline="middle">
              {s.kind === "loss" ? `−${Math.abs(s.value).toLocaleString(undefined, { maximumFractionDigits: 0 })} ${unit} · ${pct}` : `${s.value.toLocaleString(undefined, { maximumFractionDigits: 0 })} ${unit}`}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Day-of-year × hour heatmap. values[day][hour]. */
export function Heatmap({ values, max, unit, timeBasis }: { values: number[][]; max: number; unit: string; timeBasis: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const days = values.length;
    const hours = values[0]?.length ?? 24;
    c.width = days;
    c.height = hours;
    const ctx = c.getContext("2d")!;
    const img = ctx.createImageData(days, hours);
    for (let d = 0; d < days; d++)
      for (let h = 0; h < hours; h++) {
        const t = Math.max(0, Math.min(1, values[d][h] / (max || 1)));
        const [r, g, b] = ramp(t);
        const k = ((hours - 1 - h) * days + d) * 4;
        img.data[k] = r;
        img.data[k + 1] = g;
        img.data[k + 2] = b;
        img.data[k + 3] = 255;
      }
    ctx.putImageData(img, 0, 0);
  }, [values, max]);
  return (
    <div className="heatmap">
      <div className="heatmap__y">
        {[24, 18, 12, 6, 0].map((h) => (
          <span key={h}>{String(h).padStart(2, "0")}:00</span>
        ))}
      </div>
      <canvas ref={ref} className="heatmap__canvas" />
      <div className="heatmap__x">
        {MONTHS.map((m) => (
          <span key={m}>{m}</span>
        ))}
      </div>
      <div className="heatmap__scale">
        <span>0</span>
        <i />
        <span>
          {max.toLocaleString(undefined, { maximumFractionDigits: 1 })} {unit}
        </span>
        <em>{timeBasis}</em>
      </div>
    </div>
  );
}

function ramp(t: number): [number, number, number] {
  // Night-slate → cell-blue → teal → irradiance amber → pale yellow
  const stops: Array<[number, [number, number, number]]> = [
    [0, [36, 44, 56]],
    [0.25, [29, 79, 143]],
    [0.5, [15, 122, 108]],
    [0.78, [217, 142, 4]],
    [1, [250, 232, 160]]
  ];
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const [t0, c0] = stops[i - 1];
      const [t1, c1] = stops[i];
      const f = (t - t0) / (t1 - t0);
      return [c0[0] + (c1[0] - c0[0]) * f, c0[1] + (c1[1] - c0[1]) * f, c0[2] + (c1[2] - c0[2]) * f] as [number, number, number];
    }
  }
  return stops[stops.length - 1][1];
}

export function DailyProfile({ lines, unit }: { lines: Series[]; unit: string }) {
  const W = 960;
  const H = 280;
  const pad = { l: 56, r: 12, t: 16, b: 30 };
  const max = niceMax(Math.max(1, ...lines.flatMap((l) => l.values)));
  const x = (h: number) => pad.l + ((W - pad.l - pad.r) * h) / 24;
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Daily profile">
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={pad.l} x2={W - pad.r} y1={y(f * max)} y2={y(f * max)} className="chart__grid" />
          <text x={pad.l - 6} y={y(f * max)} className="chart__tick" textAnchor="end" dominantBaseline="middle">
            {(f * max).toFixed(0)}
          </text>
        </g>
      ))}
      <text x={12} y={pad.t} className="chart__unit">
        {unit}
      </text>
      {[0, 6, 12, 18, 24].map((h) => (
        <text key={h} x={x(h)} y={H - 10} className="chart__tick" textAnchor="middle">
          {String(h).padStart(2, "0")}:00
        </text>
      ))}
      {lines.map((l) => (
        <polyline key={l.name} fill="none" stroke={l.color} strokeWidth={2} points={l.values.map((v, h) => `${x(h + 0.5)},${y(v)}`).join(" ")} />
      ))}
    </svg>
  );
}
