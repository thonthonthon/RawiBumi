import type { EChartsCoreOption } from "echarts/core";
import { reportToken as token } from "../report/tokens";

/**
 * ECharts options for the results charts (F7, ADR 0016). The results screen and the HTML
 * report build their charts from these same functions, with colours from the shared tokens,
 * so a chart in the report is the chart on screen.
 */

export interface ChartPalette {
  text: string;
  muted: string;
  grid: string;
  axis: string;
  bg: string;
  series: string[];
  loss: string;
  gain: string;
  heat: string[];
  font: string;
}

/** Colours and font from the design tokens (paper-safe hues for the stone results page and the report). */
export function paletteFromTokens(): ChartPalette {
  return {
    text: token("role-panel-text"),
    muted: token("role-panel-muted"),
    grid: token("role-chart-grid"),
    axis: token("role-chart-axis"),
    bg: "transparent",
    series: [token("role-chart-1"), token("role-chart-2"), ...[1, 3, 4, 5, 6, 7, 8].map((i) => token(`color-mppt-paper-${i}`))],
    loss: token("role-chart-loss"),
    gain: token("role-chart-1"),
    heat: [0, 1, 2, 3, 4, 5].map((i) => token(`color-heat-${i}`)),
    font: token("font-ui") || "Archivo, sans-serif"
  };
}

export const MONTH_KEYS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"] as const;

export interface BarSeries {
  name: string;
  values: number[];
  color?: string;
}

const base = (p: ChartPalette, aria: string): EChartsCoreOption => ({
  animation: false,
  backgroundColor: p.bg,
  textStyle: { fontFamily: p.font, color: p.text },
  aria: { enabled: true, label: { description: aria } },
  grid: { left: 64, right: 16, top: 24, bottom: 40, containLabel: false },
  tooltip: { trigger: "axis", confine: true }
});

const valueAxis = (p: ChartPalette, unit: string) => ({
  type: "value",
  name: unit,
  nameTextStyle: { color: p.muted, align: "right" },
  axisLabel: { color: p.muted },
  axisLine: { show: false },
  splitLine: { lineStyle: { color: p.grid } }
});

const categoryAxis = (p: ChartPalette, data: string[]) => ({
  type: "category",
  data,
  axisLabel: { color: p.muted },
  axisLine: { lineStyle: { color: p.axis } },
  axisTick: { show: false }
});

/** Monthly bars, grouped or stacked. */
export function monthlyOption(p: ChartPalette, o: { months: string[]; series: BarSeries[]; unit: string; stacked?: boolean; aria: string }): EChartsCoreOption {
  return {
    ...base(p, o.aria),
    legend: o.series.length > 1 ? { bottom: 0, textStyle: { color: p.text }, itemWidth: 12, itemHeight: 8 } : undefined,
    grid: { left: 64, right: 16, top: 24, bottom: o.series.length > 1 ? 56 : 32 },
    xAxis: categoryAxis(p, o.months),
    yAxis: valueAxis(p, o.unit),
    series: o.series.map((s, i) => ({
      type: "bar",
      name: s.name,
      data: s.values.map((v) => Number(v.toFixed(3))),
      stack: o.stacked ? "total" : undefined,
      itemStyle: { color: s.color ?? p.series[i % p.series.length] },
      barMaxWidth: 28
    }))
  };
}

export interface WaterfallInput {
  start: { label: string; value: number };
  losses: { label: string; value: number }[];
  end: { label: string; value: number };
  unit: string;
  aria: string;
}

/** Loss waterfall: the reference energy, each loss stepping down, the AC energy. */
export function waterfallOption(p: ChartPalette, w: WaterfallInput): EChartsCoreOption {
  const labels = [w.start.label, ...w.losses.map((l) => l.label), w.end.label];
  const offsets: number[] = [0];
  const heights: number[] = [w.start.value];
  let level = w.start.value;
  for (const l of w.losses) {
    level -= l.value;
    offsets.push(level);
    heights.push(l.value);
  }
  offsets.push(0);
  heights.push(w.end.value);
  return {
    ...base(p, w.aria),
    tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" } },
    grid: { left: 64, right: 16, top: 24, bottom: 96 },
    xAxis: { ...categoryAxis(p, labels), axisLabel: { color: p.muted, rotate: 40, interval: 0 } },
    yAxis: valueAxis(p, w.unit),
    series: [
      { type: "bar", stack: "w", stackStrategy: "all", data: offsets, itemStyle: { color: "transparent" }, emphasis: { disabled: true }, tooltip: { show: false } },
      {
        type: "bar",
        stack: "w",
        stackStrategy: "all",
        name: w.unit,
        data: heights.map((v, i) => ({ value: Number(v.toFixed(1)), itemStyle: { color: i === 0 || i === heights.length - 1 || v < 0 ? p.gain : p.loss } })),
        barMaxWidth: 36
      }
    ]
  };
}

/** 52 weeks × 24 hours heatmap of mean power (S10 weekly view). values[week][hour]. */
export function heatmapOption(p: ChartPalette, o: { values: number[][]; unit: string; hourLabel: string; weekLabel: string; aria: string }): EChartsCoreOption {
  const data: [number, number, number | "-"][] = [];
  let max = 0;
  o.values.forEach((row, w) =>
    row.forEach((v, h) => {
      // A cell without data stays empty ("-"), never zero.
      data.push([w, h, Number.isFinite(v) ? Number(v.toFixed(2)) : "-"]);
      if (Number.isFinite(v)) max = Math.max(max, v);
    })
  );
  return {
    ...base(p, o.aria),
    tooltip: { position: "top", confine: true },
    grid: { left: 56, right: 72, top: 16, bottom: 40 },
    xAxis: { type: "category", name: o.weekLabel, nameLocation: "middle", nameGap: 26, nameTextStyle: { color: p.muted }, data: o.values.map((_, w) => String(w + 1)), axisLabel: { color: p.muted, interval: 3 }, axisTick: { show: false }, splitArea: { show: false } },
    yAxis: { type: "category", name: o.hourLabel, nameTextStyle: { color: p.muted }, data: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0")), axisLabel: { color: p.muted, interval: 5 }, axisTick: { show: false } },
    visualMap: { min: 0, max: Math.max(max, 1e-9), calculable: false, orient: "vertical", right: 0, top: "middle", itemHeight: 140, text: [`${max.toFixed(1)} ${o.unit}`, "0"], textStyle: { color: p.muted }, inRange: { color: p.heat } },
    series: [{ type: "heatmap", data, progressive: 0, emphasis: { itemStyle: { borderColor: p.text, borderWidth: 1 } } }]
  };
}
