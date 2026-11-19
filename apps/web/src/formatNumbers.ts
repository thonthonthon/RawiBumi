/** Display only: preserve stored values and trim binary arithmetic artefacts. */
export function formatNumber(value: number, precision = 10): string {
  return Number.isFinite(value) ? String(Number(value.toPrecision(precision))) : "—";
}
export function formatPercent(value: number): string { return formatNumber(value * 100); }
