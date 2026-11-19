import { useState } from "react";
import type { AttributionPeriod, DetailedElectricalShading as DetailedResult } from "../types";

export const attributionChannels = [
  ["regional_mismatch", "Regional mismatch"],
  ["bypass_interaction", "Bypass interaction"],
  ["series_interaction", "Series interaction"],
  ["parallel_interaction", "Parallel/shared-MPPT interaction"],
  ["tracker_interaction", "Tracker interaction"],
  ["total_detailed_dc_delta", "Total detailed DC attribution"]
] as const;

export function signedEnergy(value: number | null): string {
  if (value === null) return "—";
  if (value === 0) return "0 Wh";
  const magnitude = Math.abs(value);
  const unit = magnitude >= 1000 ? "kWh" : "Wh";
  const amount = magnitude >= 1000 ? magnitude / 1000 : magnitude;
  const display = amount < 0.001 ? "<0.001" : amount.toLocaleString("en-US", { maximumFractionDigits: 3 });
  return `${value < 0 ? "−" : "+"}${display} ${unit} · ${value < 0 ? "recovery" : "reduction"}`;
}

export function coveragePercentage(fraction: number): string {
  if (fraction > 0 && fraction < 0.0001) return "<0.01%";
  if (fraction < 1 && fraction > 0.9999) return ">99.99%";
  return `${(fraction * 100).toLocaleString("en-US", { maximumFractionDigits: 2 })}%`;
}

export function DetailedExecutionStatus({ result }: { result: DetailedResult }) {
  const identity = result.execution_identity;
  return <div aria-label="Electrical execution identity">
    <p>Detailed electrical execution: {identity.runtime_support_result} · Requested: {identity.requested_fidelity ?? "unavailable"} · Resolved: {identity.resolved_fidelity ?? "unavailable"}</p>
    <p>Fallback policy: {identity.fallback_policy} · Fallback occurred: {identity.fallback_applied ? "yes" : "no"}</p>
    {identity.fallback_reason && <p>Backend fallback reason: {identity.fallback_reason}</p>}
    {identity.failure_reasons.length > 0 && <p>{identity.failure_reasons.join("; ")}</p>}
  </div>;
}

export function DetailedElectricalShading({ result }: { result: DetailedResult }) {
  const [periodIndex, setPeriodIndex] = useState(0);
  const summary = result.attribution_energy_summary;
  if (!summary) return null;
  const period = summary.periods[periodIndex] ?? summary.periods[0];
  const identity = result.execution_identity;
  return <section className="panel-card detailed-shading" aria-label="Detailed Electrical Shading">
    <h3>Detailed Electrical Shading</h3>
    <p>Execution: <strong>{identity.runtime_support_result}</strong> · Requested: {identity.requested_fidelity ?? "unavailable"} · Resolved: {identity.resolved_fidelity ?? "unavailable"}</p>
    <p className="note">DC attribution is explanatory. Positive = reduction; negative = recovery. Actual PCC/energy results remain authoritative; these channels are never subtracted from production again.</p>
    <label>Observed period <select value={periodIndex} onChange={event => setPeriodIndex(Number(event.target.value))}>
      {summary.periods.map((p, index) => <option key={`${p.period_kind}:${p.period_key}`} value={index}>{p.period_kind === "run_total" ? "Run total" : `${p.period_kind} · ${p.period_key}`}</option>)}
    </select></label>
    <p><strong>Attribution coverage: {period.telescope.status.replaceAll("_", " ")}</strong> · {period.observed_start} → {period.observed_end} · {period.duration_seconds} simulated seconds</p>
    <p className="note">Complete means all applicable simulated coverage, not a full calendar month or year. Partial values are observed subtotals with no extrapolation. Dark/night duration is not applicable, not failed coverage. Period assignment uses persisted local interval starts.</p>
    <AttributionPeriodTable period={period} />
    <details><summary>Model identity, references and limitations</summary>
      <p>{summary.source_identity.attribution_model_id} · version {summary.source_identity.attribution_model_version}<br />{summary.energy_summary_model_id} · version {summary.energy_summary_model_version}</p>
      {[result.selected_mppt_result, result.dc_attribution_result, result.attribution_energy_result].map((r, index) => <p key={index}>{r.artifact ?? "Artifact not produced"} · {r.status} · {r.sha256 ?? "No hash"} {r.unavailable_reason_codes.join(", ")}</p>)}
      <ul>{[...identity.limitations, ...identity.failure_reasons, ...(identity.fallback_reason ? [identity.fallback_reason] : [])].map((text, index) => <li key={index}>{text}</li>)}</ul>
    </details>
    <details><summary>Optional diagnostic artifacts · {result.diagnostic_artifacts.status}</summary><p>{result.diagnostic_artifacts.artifacts.join(", ") || "No diagnostic artifacts available."}</p><p className="note">References only. IV curves are not downloaded or rendered by this view.</p></details>
    <details><summary>Raw persisted attribution summary</summary><pre style={{ overflowX: "auto", maxHeight: 320 }}>{JSON.stringify(summary, null, 2)}</pre></details>
  </section>;
}

export function AttributionPeriodTable({ period }: { period: AttributionPeriod }) {
  return (
    <div style={{ overflowX: "auto" }}><table className="tbl">
      <thead><tr><th>Interaction</th><th>Completeness</th><th>Observed signed energy</th><th>Applicable coverage</th><th>Unavailable reason codes</th></tr></thead>
      <tbody>{attributionChannels.map(([key, label]) => {
        const c = period.channels[key];
        const known = c.completeness === "complete" || c.completeness === "partial";
        return <tr key={key}>
          <td>{label}</td><td><strong>{c.completeness.replaceAll("_", " ")}</strong>{c.completeness === "partial" && " · partial coverage"}</td>
          <td title={known ? `Raw observed signed energy: ${c.observed_signed_energy_wh} Wh` : undefined} data-raw-wh={known ? c.observed_signed_energy_wh ?? undefined : undefined}>{known ? signedEnergy(c.observed_signed_energy_wh) : "—"}</td>
          <td>{c.available_duration_seconds} / {c.applicable_duration_seconds} s{c.availability_fraction !== null && ` (${coveragePercentage(c.availability_fraction)})`}<br /><small>{c.not_applicable_duration_seconds} s not applicable · {c.unavailable_duration_seconds} s unavailable</small></td>
          <td>{c.unavailable_reason_codes.length ? c.unavailable_reason_codes.join(", ") : "—"}</td>
        </tr>;
      })}</tbody>
    </table></div>
  );
}
