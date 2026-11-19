/** DEMO ONLY: synthetic hourly series for previewing charts that need the time-series endpoint. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

export interface DemoSeries {
  acBefore: number[][]; // kW [day][hour]
  acAfter: number[][];
  load: number[][];
  poa: number[][]; // W/m²
  tcell: number[][];
}

export function demoSeries(kwp: number, acKw: number, exportLimitKw = 0): DemoSeries {
  const r = rng(42);
  const acBefore: number[][] = [];
  const acAfter: number[][] = [];
  const load: number[][] = [];
  const poa: number[][] = [];
  const tcell: number[][] = [];
  for (let d = 0; d < 365; d++) {
    const wet = 0.5 + 0.5 * Math.cos(((d - 15) / 365) * 2 * Math.PI); // wetter around Jan
    const cloudDay = 0.55 + 0.45 * (1 - wet * 0.6) * (0.6 + 0.4 * r());
    const weekend = d % 7 === 5 || d % 7 === 6;
    const rowA: number[] = [];
    const rowB: number[] = [];
    const rowL: number[] = [];
    const rowP: number[] = [];
    const rowT: number[] = [];
    for (let h = 0; h < 24; h++) {
      const sun = Math.max(0, Math.sin(((h + 0.5 - 6) / 12.2) * Math.PI));
      const cloud = h > 12 ? cloudDay * (0.75 + 0.25 * r()) : cloudDay * (0.9 + 0.1 * r());
      const g = 1050 * sun ** 1.25 * cloud;
      const tc = 27 + g * 0.028;
      const dc = kwp * (g / 1000) * (1 - 0.0037 * (tc - 25)) * 0.9;
      const ac = Math.min(acKw, dc * 0.975);
      const base = weekend ? 0.18 : 0.35;
      const occ = weekend ? 0 : h >= 8 && h <= 17 ? 0.5 + 0.1 * r() : 0;
      const l = acKw * (base + occ + (h === 12 && !weekend ? -0.2 : 0));
      rowA.push(ac);
      rowB.push(Math.min(ac, l + exportLimitKw));
      rowL.push(l);
      rowP.push(g);
      rowT.push(tc);
    }
    acBefore.push(rowA);
    acAfter.push(rowB);
    load.push(rowL);
    poa.push(rowP);
    tcell.push(rowT);
  }
  return { acBefore, acAfter, load, poa, tcell };
}

const DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

export function monthlySum(m: number[][]): number[] {
  const out: number[] = [];
  let d = 0;
  for (const n of DAYS) {
    let s = 0;
    for (let i = 0; i < n; i++) s += m[d + i].reduce((a, b) => a + b, 0);
    out.push(s);
    d += n;
  }
  return out;
}

export function monthlyMeanDay(m: number[][], month: number): number[] {
  const start = DAYS.slice(0, month).reduce((a, b) => a + b, 0);
  const n = DAYS[month];
  return Array.from({ length: 24 }, (_, h) => {
    let s = 0;
    for (let i = 0; i < n; i++) s += m[start + i][h];
    return s / n;
  });
}
