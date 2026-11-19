import { useState } from "react";
import { DEMO, engine } from "./client";
import { PlanCanvas } from "./canvas/PlanCanvas";
import { Sld } from "./electrical/Sld";
import { Inspector } from "./Inspector";
import { DeleteDialog, ImportHub, Toasts } from "./Modals";
import { ComponentsPanel } from "./panels/ComponentsPanel";
import { ElectricalPanel } from "./panels/ElectricalPanel";
import { LayoutPanel } from "./panels/LayoutPanel";
import { MeteoPanel } from "./panels/MeteoPanel";
import { ScenePanel } from "./panels/ScenePanel";
import { SimulatePanel } from "./panels/SimulatePanel";
import { SitePanel } from "./panels/SitePanel";
import { ExportView } from "./results/ExportView";
import { ResultsView } from "./results/ResultsView";
import { allFindings, stepStates } from "./state/derived";
import { Step, useStore } from "./state/store";
import { NotWired } from "./ui/kit";


const STEPS: Array<{ id: Step; label: string }> = [
  { id: "site", label: "Site" },
  { id: "scene", label: "Scene" },
  { id: "layout", label: "PV layout" },
  { id: "components", label: "Components" },
  { id: "electrical", label: "Electrical" },
  { id: "meteo", label: "Meteo & load" },
  { id: "simulate", label: "Simulate" },
  { id: "results", label: "Results" },
  { id: "export", label: "Export" }
];


const STATE_LABEL = { none: "Not started", draft: "Draft", valid: "Valid", blocked: "Blocked" } as const;


export function Workspace({ onClose }: { onClose: () => void }) {
  const { state, dispatch, run, toast } = useStore();
  const [importOpen, setImportOpen] = useState<string | null>(null);
  const [findingsOpen, setFindingsOpen] = useState(false);
  const v = state.view!;
  const states = stepStates(state);
  const findings = allFindings(state);
  const blocking = findings.filter((f) => f.severity === "blocking").length;
  const drafts = findings.filter((f) => f.severity === "draft").length;
  const warnings = findings.filter((f) => f.severity === "warning").length;
  const fullWidth = state.step === "results" || state.step === "export";


  const panel = (() => {
    switch (state.step) {
      case "site":
        return <SitePanel />;
      case "scene":
        return <ScenePanel onImport={() => setImportOpen("geometry")} />;
      case "layout":
        return <LayoutPanel />;
      case "components":
        return <ComponentsPanel onImport={() => setImportOpen("components")} />;
      case "electrical":
        return <ElectricalPanel />;
      case "meteo":
        return <MeteoPanel onImport={() => setImportOpen("meteo")} />;
      case "simulate":
        return <SimulatePanel />;
      default:
        return null;
    }
  })();


  return (
    <div className={fullWidth ? "ws ws--full" : "ws"}>
      <header className="topbar">
        <div className="topbar__brand">
          <span className="brand">RawiBumi</span>
          <span className="topbar__project">{v.bundle.project.name}</span>
          {DEMO && <span className="demo-flag" title="In-browser mock engine for UI review. Numbers are not simulation results.">Demo engine</span>}
        </div>
        <div className="topbar__site">
          {v.bundle.project.site.latitude_deg.toFixed(5)}, {v.bundle.project.site.longitude_deg.toFixed(5)} · {v.bundle.project.site.timezone} · rev {v.bundle.project.project_revision.revision_number}
        </div>
        <div className="topbar__actions">
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => dispatch({ type: "undo" })} disabled={!state.past.length} title="Undo (Ctrl+Z)">
            Undo
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => dispatch({ type: "redo" })} disabled={!state.future.length} title="Redo (Ctrl+Y)">
            Redo
          </button>
          <button
            type="button"
            className="btn btn--sm"
            disabled={!!state.busy}
            onClick={async () => {
              const r = await run("Saving", () => engine.save(v.bundle.project.project_id));
              if (r) toast("ok", `Saved revision ${r.project_revision_id}.`);
            }}
          >
            Save
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>
            Projects
          </button>
        </div>
      </header>


      <nav className="rail" aria-label="Workflow">
        {STEPS.map((s, i) => (
          <button
            key={s.id}
            type="button"
            className={state.step === s.id ? "rail__step rail__step--on" : "rail__step"}
            onClick={() => dispatch({ type: "setStep", step: s.id })}
            title={STATE_LABEL[states[s.id]]}
          >
            <span className={`rail__marker rail__marker--${states[s.id]}`}>{i + 1}</span>
            <span className="rail__label">{s.label}</span>
            <span className="rail__state">{STATE_LABEL[states[s.id]]}</span>
          </button>
        ))}
      </nav>


      {!fullWidth && <aside className="taskpanel">{panel}</aside>}


      <main className="stage">
        {fullWidth ? (
          state.step === "results" ? (
            <ResultsView />
          ) : (
            <ExportView />
          )
        ) : (
          <>
            <div className="stage__bar">
              <div className="segmented segmented--dark">
                {(["plan", "3d", "sld"] as const).map((k) => (
                  <button key={k} type="button" className={state.canvasView === k ? "segmented__opt segmented__opt--on" : "segmented__opt"} onClick={() => dispatch({ type: "setCanvasView", view: k })}>
                    {k === "plan" ? "Plan" : k === "3d" ? "3D" : "SLD"}
                  </button>
                ))}
              </div>
              <span className="stage__mode">
                {state.step === "electrical" ? "Electrical overlay: modules coloured by MPPT" : state.underlay.kind === "none" ? "Blank engineering plane" : state.underlay.kind === "tiles" ? "Tile underlay" : "Image underlay"}
              </span>
              {state.busy && <span className="stage__busy">{state.busy}…</span>}
            </div>
            <div className="stage__canvas">
              {state.canvasView === "plan" && <PlanCanvas />}
              {state.canvasView === "sld" && <Sld />}
              {state.canvasView === "3d" && (
                <div className="placeholder3d">
                  <NotWired id="view3d" />
                  <h3>3D view arrives in phase UI-C</h3>
                  <p>It will render the engine's height model (Phase 4.4) read-only first, then constraint-based editing and the sun/shadow slider.</p>
                </div>
              )}
            </div>
          </>
        )}
      </main>


      {!fullWidth && (
        <aside className="inspectorpane">
          <Inspector />
        </aside>
      )}


      <footer className={findingsOpen ? "findings findings--open" : "findings"}>
        <button type="button" className="findings__bar" onClick={() => setFindingsOpen(!findingsOpen)} aria-expanded={findingsOpen}>
          <span className="findings__title">Findings</span>
          <span className="pill pill--blocking">{blocking} blocking</span>
          <span className="pill pill--warning">{warnings} warnings</span>
          <span className="pill pill--draft">{drafts} drafts</span>
          <span className="findings__hint">{findingsOpen ? "Hide" : "Show"}</span>
        </button>
        {findingsOpen && (
          <ul className="findings__list">
            {findings.length === 0 && <li className="empty">No findings.</li>}
            {findings.map((f) => (
              <li
                key={f.id}
                className={`finding finding--${f.severity}`}
                onClick={() => {
                  if (f.step) dispatch({ type: "setStep", step: f.step });
                  if (f.entityId) dispatch({ type: "select", ids: [f.entityId] });
                }}
              >
                <span className="finding__sev">{f.severity}</span>
                <span className="finding__src">{f.source}</span>
                <span>{f.message}</span>
              </li>
            ))}
          </ul>
        )}
      </footer>


      {importOpen && <ImportHub initial={importOpen} onClose={() => setImportOpen(null)} />}
      <DeleteDialog />
      <Toasts />
    </div>
  );
}