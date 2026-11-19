import { useEffect, useState } from "react";
import { engine } from "../client";
import type { ExecutionReadiness } from "../types";
import { useStore } from "../state/store";
import { electricalIssues } from "../state/derived";
import { Button, Section, StatusDot } from "../ui/kit";

export function SimulatePanel() {
  const { state, dispatch, run, toast } = useStore();
  const v = state.view!;
  const pid = v.bundle.project.project_id;
  const [ready, setReady] = useState<ExecutionReadiness | null>(null);
  const uiBlocking = electricalIssues(state).filter((f) => f.severity === "blocking" || f.message.includes("override"));
  const drafts = state.entities.filter((e) => e.source === "draft" || e.modified);

  useEffect(() => {
    engine
      .executionReadiness(pid)
      .then(setReady)
      .catch(() => setReady(null));
  }, [pid, v.bundle.project.project_revision.revision_number, v.bundle.weather_selection?.revision_id]);

  return (
    <>
      <Section title="Preflight">
        <ul className="checklist">
          <li>
            <StatusDot state={ready ? (ready.ready ? "pass" : "fail") : "unavailable"} />
            <span className="checklist__label">Engine readiness</span>
            <span className="checklist__detail">{ready ? (ready.ready ? `Ready · ${ready.execution_class ?? "supported"}` : `${ready.findings.length} blocking`) : "Checking…"}</span>
          </li>
          {ready?.findings.map((f) => (
            <li key={f.rule_id} className="checklist__sub">
              <StatusDot state="fail" />
              <span className="checklist__label">{f.rule_id}</span>
              <span className="checklist__detail">{f.message}</span>
            </li>
          ))}
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
          disabled={!ready?.ready}
          onClick={async () => {
            const r = await run("Simulating", async () => {
              const rec = await engine.simulate(pid);
              const view = await engine.project(pid);
              return { rec, view };
            });
            if (r) {
              dispatch({ type: "setView", view: r.view });
              toast(r.rec.status === "failed" ? "error" : "ok", r.rec.status === "failed" ? "Run failed. See findings." : "Run complete.");
              if (r.rec.status !== "failed") dispatch({ type: "setStep", step: "results" });
            }
          }}
        >
          Validate and run
        </Button>
      </Section>
      <Section title="Run history">
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
