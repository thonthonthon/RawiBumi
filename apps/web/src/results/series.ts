import type { RunTimeSeriesView } from "../client";
import type { DemoSeries } from "../demo/series";

/**
 * S15: one hourly-series shape for the Results views, from the engine's run time-series route or (demo only) the
 * synthetic series. Matrices are site-local days × 24 hours; a missing hour is NaN. Monthly rows sit at their
 * calendar month (0–11); a month the run doesn't cover is NaN.
 */
export interface ResultSeries {
  authority: "ENGINE" | "DEMO_SYNTHETIC";
  /** YYYY-MM-DD per row of the matrices. */
  days: string[];
  ac: number[][];
  poa: number[][];
  tcell: number[][];
  /** Demo only until S19 (export limit, load profile). */
  acBeforeLimit: number[][] | null;
  load: number[][] | null;
  monthly: {
    energyKwh: number[];
    poaKwhM2: number[];
    ghiKwhM2: number[];
    performanceRatio: number[];
    /** Loss channel → kWh per calendar month, for the channels with a stored hourly column. */
    lossesKwh: Array<{ lossType: string; values: number[] }>;
  };
}

const nan = (v: number | null | undefined) => (v === null || v === undefined ? NaN : v);
const twelve = () => Array.from({ length: 12 }, () => NaN);

export function fromEngine(view: RunTimeSeriesView): ResultSeries {
  const matrix = (key: keyof RunTimeSeriesView["hourly"]) => (view.hourly[key]?.values ?? view.days.map(() => Array(24).fill(null))).map((row) => row.map(nan));
  const monthly = { energyKwh: twelve(), poaKwhM2: twelve(), ghiKwhM2: twelve(), performanceRatio: twelve(), lossesKwh: [] as Array<{ lossType: string; values: number[] }> };
  const channels = view.loss_channels.filter((c) => c.monthly).map((c) => ({ lossType: c.loss_type, values: twelve() }));
  for (const row of view.monthly) {
    const i = Number(row.month.slice(5, 7)) - 1;
    // A run longer than a year would put two rows in one calendar month: they add up.
    const add = (target: number[], v: number | null) => { target[i] = (Number.isNaN(target[i]) ? 0 : target[i]) + nan(v); };
    add(monthly.energyKwh, row.energy_kwh);
    add(monthly.poaKwhM2, row.poa_unshaded_kwh_m2);
    add(monthly.ghiKwhM2, row.ghi_kwh_m2);
    monthly.performanceRatio[i] = nan(row.performance_ratio);
    for (const c of channels) add(c.values, row.losses_kwh[c.lossType] ?? null);
  }
  monthly.lossesKwh = channels;
  return { authority: "ENGINE", days: view.days, ac: matrix("ac_kw"), poa: matrix("poa_w_m2"), tcell: matrix("cell_temperature_c"), acBeforeLimit: null, load: null, monthly };
}

const DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

/** DEMO ONLY: the synthetic series (a 365-day year) in the same shape, with illustrative monthly losses. */
export function fromDemo(d: DemoSeries, kwp: number, losses: Array<{ lossType: string; fraction: number }>): ResultSeries {
  const days: string[] = [];
  DAYS.forEach((n, m) => { for (let i = 1; i <= n; i++) days.push(`2025-${String(m + 1).padStart(2, "0")}-${String(i).padStart(2, "0")}`); });
  const sum = (mat: number[][]) => DAYS.map((_, m) => mat.reduce((t, row, i) => (days[i].slice(5, 7) === String(m + 1).padStart(2, "0") ? t + row.reduce((a, b) => a + b, 0) : t), 0));
  const energyKwh = sum(d.acAfter);
  const poaKwhM2 = sum(d.poa).map((x) => x / 1000);
  return {
    authority: "DEMO_SYNTHETIC", days, ac: d.acAfter, poa: d.poa, tcell: d.tcell, acBeforeLimit: d.acBefore, load: d.load,
    monthly: {
      energyKwh, poaKwhM2, ghiKwhM2: twelve(),
      performanceRatio: energyKwh.map((e, i) => (kwp > 0 && poaKwhM2[i] > 0 ? e / (kwp * poaKwhM2[i]) : NaN)),
      lossesKwh: losses.map((l) => ({ lossType: l.lossType, values: energyKwh.map((e) => (e * l.fraction) / (1 - l.fraction)) }))
    }
  };
}

/** Mean of each hour over the days of one calendar month (0–11), ignoring missing hours; NaN when none. */
export function meanDayOfMonth(s: ResultSeries, matrix: number[][], month: number): number[] {
  const mm = String(month + 1).padStart(2, "0");
  return Array.from({ length: 24 }, (_, h) => {
    let total = 0, n = 0;
    s.days.forEach((d, i) => {
      const v = matrix[i]?.[h];
      if (d.slice(5, 7) === mm && Number.isFinite(v)) { total += v; n++; }
    });
    return n ? total / n : NaN;
  });
}

/** Calendar months (0–11) the series covers. */
export const coveredMonths = (s: ResultSeries): number[] => [...new Set(s.days.map((d) => Number(d.slice(5, 7)) - 1))].sort((a, b) => a - b);

/** The loss channels with the largest annual magnitude, for a readable stacked chart. */
export function largestLosses(s: ResultSeries, count: number, requiredLoss?: string) {
  const total = (values: number[]) => values.reduce((t, v) => t + (Number.isFinite(v) ? Math.abs(v) : 0), 0);
  const largest = [...s.monthly.lossesKwh].filter((l) => total(l.values) > 0).sort((a, b) => total(b.values) - total(a.values)).slice(0, count);
  const required = s.monthly.lossesKwh.find(l => l.lossType === requiredLoss);
  return required && !largest.includes(required) ? [...largest.slice(0, Math.max(0, count-1)), required] : largest;
}
