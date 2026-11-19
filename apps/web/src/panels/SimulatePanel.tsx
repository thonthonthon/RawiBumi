import { useEffect, useState, useMemo } from "react";
import { engine, DEMO } from "../client";
import type { ExecutionReadiness, BrowserSimulationRequest } from "../types";
import { useStore } from "../state/store";
import { electricalIssues } from "../state/derived";
import { Button, Section, StatusDot } from "../ui/kit";
import { useTranslation } from "react-i18next";
import { missingRefillParameters } from "../engine/layout";
import { CompleteFromDatasheet } from "../electrical/ComponentActions";
import { plainFindings } from "../electrical/readinessText";
import { engineCommand } from "../state/history";

export function SimulatePanel() {
  const { t } = useTranslation();
  const { state, dispatch, run, toast } = useStore();
  const v = state.view!;
  const pid = v.bundle.project.project_id;
  const [detailed, setDetailed] = useState(false);
  const [policy, setPolicy] = useState<"fail_closed" | "explicit_lower_fidelity">("fail_closed");
  const input = useMemo<BrowserSimulationRequest | undefined>(() => detailed ? {
    electrical_shading_configuration: { requested_fidelity: "level_2_bypass_substring", fallback_policy: policy }
  } : undefined, [detailed, policy]);
  const [ready, setReady] = useState<ExecutionReadiness | null>(null);
  const uiBlocking = electricalIssues(state).filter((f) => f.severity === "blocking" || f.message.includes("override"));
  const drafts = state.entities.filter((e) => e.source === "draft" || e.modified);

  useEffect(() => {
    let current = true;
    setReady(null);
    engine.executionReadiness(pid, input)
      .then((value) => { if (current) setReady(value); })
      .catch(() => { if (current) setReady(null); });
    return () => { current = false; };
  }, [pid, input, v.bundle]);

  return (
    <>
      <Section primary title={t("s7a.warnings")}>
        <ul className="checklist">
          {ready?.findings.filter((f) => f.severity === "warning").map((f, index) => {
            const field = v.bundle.scene.pv_fields.find((x) => x.pv_field_id === f.entity_id);
            const stale = f.rule_id === "SCENE_PV_FIELD_LAYOUT_STALE";
            return <li key={`${f.rule_id}-${index}`} className="checklist__sub">
              <StatusDot state={stale ? "pass" : "warn"} />
              <span className="checklist__label">{stale ? t("s7a.refillAvailable") : f.rule_id}</span>
              <span className="checklist__detail">{f.message}</span>
              {stale && <Button small disabled={!field || missingRefillParameters(field).length > 0 || !!state.busy} onClick={() => {
                dispatch({ type: "setForm", key: "layout.refillTarget", value: f.entity_id });
                dispatch({ type: "setStep", step: "layout" });
              }}>{t("layout.refill")}</Button>}
            </li>;
          })}
        </ul>
      </Section>
      <Section primary title={t("sections.preflight")}>
        <ul className="checklist">
          <li>
            <StatusDot state={ready ? (ready.ready ? "pass" : "fail") : "unavailable"} />
            <span className="checklist__label">Engine readiness</span>
            <span className="checklist__detail">{ready ? (ready.ready ? `Ready · ${ready.execution_class ?? "supported"}` : `${ready.execution_class ?? "blocked"} · ${ready.findings.length} findings`) : "Checking…"}</span>
          </li>
          {ready && plainFindings(ready.findings.filter((f) => f.severity !== "warning"), v).map((f, index) => {
            const def = v.catalog.inverters.find((c) => c.revision_id === f.inverterRevisionId);
            return (
              <li key={`${f.rule_id}-${index}`} className="checklist__sub" data-blocker={f.rule_id}>
                <StatusDot state="fail" />
                <span className="checklist__label" title={f.key ? `${f.rule_id}: ${f.message}` : undefined}>{f.key ? t(f.key, f.values) : f.rule_id}</span>
                <span className="checklist__detail">{f.key ? <code>{f.rule_id}</code> : f.message}</span>
                {f.inverterRevisionId && (def?.superseded_by
                  ? <Button small tone="primary" disabled={!!state.busy} onClick={() => void engineCommand(t("use1.changing"), () => engine.changeInverter(pid, f.inverterInstanceId!, def.superseded_by!))}>{t("use1.switchCompleted")}</Button>
                  : <CompleteFromDatasheet revisionId={f.inverterRevisionId} />)}
              </li>
            );
          })}
          <li>
            <StatusDot state={uiBlocking.length ? "warn" : "pass"} />
            <span className="checklist__label">Electrical layout drafts</span>
            <span className="checklist__detail">{uiBlocking.length ? `${uiBlocking.length} open items (UI drafts, not sent to engine)` : "No open items"}</span>
          </li>
          <li>
            <StatusDot state={drafts.length ? "warn" : "pass"} />
            <span className="checklist__label">Uncommitted scene drafts</span>
            <span className="checklist__detail">{drafts.length ? `${drafts.length} drafts are excluded from the run` : "None"}</span>
          </li>
        </ul>
        <p className="note">The run uses only committed engine state. Local drafts never enter physics.</p>
        <Button
          tone="primary"
          disabled={!ready?.ready || !!state.busy}
          onClick={async () => {
            const r = await run("Simulating", async () => {
              const rec = await engine.simulate(pid, input);
              if (input && rec.status !== "failed") await engine.runResult(pid, rec.simulation_run_id);
              const view = await engine.project(pid);
              return { rec, view };
            });
            if (r) {
              dispatch({ type: "setView", view: r.view });
              dispatch({ type: "setForm", key: "results.run", value: r.rec.simulation_run_id });

              toast(r.rec.status === "failed" ? "error" : "ok", r.rec.status === "failed" ? "Run failed. See findings." : "Run complete.");
              if (r.rec.status !== "failed") dispatch({ type: "setStep", step: "results" });
            }
          }}
        >
          Validate and run
        </Button>
      </Section>
      <Section title={t("sections.execution")}>
        <label>Electrical shading execution
          <select aria-label="Electrical shading execution" disabled={!!state.busy} value={detailed ? "detailed" : "legacy"} onChange={(e) => { setReady(null); setDetailed(e.target.value === "detailed"); }}>
            <option value="legacy">Existing geometry execution (legacy)</option>
            <option value="detailed" disabled={DEMO}>Detailed electrical shading · level_2_bypass_substring</option>
          </select>
        </label>
        {detailed && <label>Fallback policy
          <select aria-label="Fallback policy" disabled={!!state.busy} value={policy} onChange={(e) => { setReady(null); setPolicy(e.target.value as typeof policy); }}>
            <option value="fail_closed">Fail closed · no fallback</option>
            <option value="explicit_lower_fidelity">Explicitly permit lower fidelity</option>
          </select>
        </label>}
        <p className="note">Detailed execution uses the project's pinned selections. Their fidelity and policy must match this request. Backend preflight is authoritative.</p>
      </Section>
      <Section title={t("sections.history")}>
        {v.bundle.simulation_runs.length === 0 && <div className="empty">No runs yet.</div>}
        {[...v.bundle.simulation_runs].reverse().map((r) => (
          <div className="card-row" key={r.simulation_run_id}>
            <div>
              <strong>{r.simulation_run_id}</strong>
              <div className="sub">
                weather {r.weather_dataset_revision_id} · input {r.input_hash?.slice(0, 10) ?? "—"}
              </div>
            </div>
            <span className={r.status === "failed" ? "tag tag--bad" : "tag tag--ok"}>{r.status}</span>
          </div>
        ))}
      </Section>
    </>
  );
}
