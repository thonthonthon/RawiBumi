import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { EChartsCoreOption } from "echarts/core";
import { echarts } from "./echarts";

/** An ECharts chart on screen (canvas). The option comes from chartOptions.ts, as in the report. */
export function EChart({ option, height = 320, label }: { option: EChartsCoreOption; height?: number; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<ReturnType<typeof echarts.init> | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const c = echarts.init(ref.current, null, { renderer: "canvas" });
    chart.current = c;
    // A resize can arrive after unmount (tab switch); a disposed chart must not be touched.
    const ro = new ResizeObserver(() => {
      if (!c.isDisposed()) c.resize();
    });
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      if (!c.isDisposed()) {
        // Invalidate zrender's multi-frame paint before disposing its canvas.
        c.clear();
        c.dispose();
      }
      chart.current = null;
    };
  }, []);
  useEffect(() => {
    const c = chart.current;
    if (c && !c.isDisposed()) c.setOption(option, { notMerge: true });
  }, [option]);
  return <div ref={ref} className="echart" style={{ height }} role="img" aria-label={label} data-chart={label} />;
}

export interface Line {
  name: string;
  color: string;
  values: number[];
}

/** Time-series lines with uPlot (fast for long hourly series). x is hours 0–23 for a daily profile. */
export function UPlotLines({ x, lines, unit, height = 280, label, font, axis, grid }: { x: number[]; lines: Line[]; unit: string; height?: number; label: string; font: string; axis: string; grid: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const opts: uPlot.Options = {
      width: el.clientWidth || 600,
      height,
      scales: { x: { time: false } },
      legend: { show: false },
      cursor: { drag: { x: false, y: false } },
      axes: [
        { stroke: axis, grid: { stroke: grid, width: 1 }, font: `12px ${font}`, values: (_u, ticks) => ticks.map((t) => `${String(t).padStart(2, "0")}:00`) },
        { stroke: axis, grid: { stroke: grid, width: 1 }, font: `12px ${font}`, label: unit, labelFont: `12px ${font}`, size: 60 }
      ],
      series: [{}, ...lines.map((l) => ({ label: l.name, stroke: l.color, width: 2, points: { show: false } }))]
    };
    const u = new uPlot(opts, [x, ...lines.map((l) => l.values)], el);
    const ro = new ResizeObserver(() => u.setSize({ width: el.clientWidth || 600, height }));
    ro.observe(el);
    return () => {
      ro.disconnect();
      u.destroy();
    };
  }, [x, lines, unit, height, font, axis, grid]);
  return <div ref={ref} className="uplot-host" role="img" aria-label={label} data-chart={label} />;
}

/** Colour key for a set of series. */
export function Legend({ items }: { items: { name: string; color: string }[] }) {
  return (
    <ul className="chart-legend">
      {items.map((i) => (
        <li key={i.name}>
          <i style={{ background: i.color }} aria-hidden="true" />
          {i.name}
        </li>
      ))}
    </ul>
  );
}
