import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import { DEMO } from "../../client";
import type { PlanRenderer } from "../gl/planRenderer";
import type { ModuleIndex } from "./moduleIndex";

/** `?perf` shows the renderer readout on the plan. */
export function perfRequested(): boolean {
  return typeof window !== "undefined" && new URLSearchParams(window.location.search).has("perf");
}

export interface Perf {
  recordPick: (ms: number) => void;
  lastPickMs: RefObject<number>;
  renderer: RefObject<PlanRenderer | null>;
}

/**
 * Timing hooks for the renderer gate in ADR 0002 (100k modules: pan at 30 fps
 * or better, pick in 16 ms or less). Demo builds also expose them on
 * `window.__rawibumiPerf` for the performance script.
 */
export function usePerf(renderer: RefObject<PlanRenderer | null>, index: ModuleIndex): Perf {
  const lastPickMs = useRef(0);
  const perf = useMemo<Perf>(() => ({ recordPick: (ms) => void (lastPickMs.current = ms), lastPickMs, renderer }), [renderer]);
  useEffect(() => {
    if (!DEMO) return;
    (window as unknown as { __rawibumiPerf: unknown }).__rawibumiPerf = {
      modules: index.size,
      frames: () => renderer.current?.stats.frames ?? 0,
      lastFrameMs: () => renderer.current?.stats.lastFrameMs ?? 0,
      /** Time `n` picks at random points inside the layout; returns mean and worst in ms. */
      pickBench: (n = 1000) => {
        const b = index.bounds;
        if (!b) return { mean: 0, max: 0, hits: 0 };
        let max = 0;
        let hits = 0;
        const t0 = performance.now();
        for (let i = 0; i < n; i++) {
          const p: [number, number] = [b.minX + Math.random() * (b.maxX - b.minX), b.minY + Math.random() * (b.maxY - b.minY)];
          const s = performance.now();
          if (index.pick(p)) hits++;
          max = Math.max(max, performance.now() - s);
        }
        return { mean: (performance.now() - t0) / n, max, hits };
      }
    };
  }, [index, renderer]);
  return perf;
}

export function PerfOverlay({ perf, modules }: { perf: Perf; modules: number }) {
  const { t } = useTranslation();
  const [, setTick] = useState(0);
  const last = useRef({ frames: 0, at: performance.now(), fps: 0 });
  useEffect(() => {
    const id = window.setInterval(() => {
      const frames = perf.renderer.current?.stats.frames ?? 0;
      const now = performance.now();
      last.current = { frames, at: now, fps: ((frames - last.current.frames) * 1000) / (now - last.current.at) };
      setTick((n) => n + 1);
    }, 500);
    return () => window.clearInterval(id);
  }, [perf]);
  const nf = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
  return (
    <dl className="plan__perf" aria-label={t("plan.perfTitle")}>
      <div>
        <dt>{t("plan.perfModules")}</dt>
        <dd>{new Intl.NumberFormat().format(modules)}</dd>
      </div>
      <div>
        <dt>{t("plan.perfFps")}</dt>
        <dd>{nf.format(last.current.fps)}</dd>
      </div>
      <div>
        <dt>{t("plan.perfFrame")}</dt>
        <dd>{nf.format(perf.renderer.current?.stats.lastFrameMs ?? 0)} ms</dd>
      </div>
      <div>
        <dt>{t("plan.perfPick")}</dt>
        <dd>{nf.format(perf.lastPickMs.current ?? 0)} ms</dd>
      </div>
    </dl>
  );
}
