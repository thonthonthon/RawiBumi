import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { engine } from "./client";
import { StartScreen } from "./StartScreen";
import { StoreProvider, uiStore, useStore } from "./state/store";
import { ApiError } from "./types";
import type { Catalog, ProjectSummary } from "./types";
import { track } from "./platform/telemetry";
import { Workspace } from "./Workspace";
import { Toasts } from "./Modals";
import { railSteps } from "./modules/registry";

function Shell() {
  const { t } = useTranslation();
  const { state, dispatch, run, toast } = useStore();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      const [p, c] = await Promise.all([engine.projects(), engine.catalog()]);
      setProjects(p);
      setCatalog(c);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    const auto = new URLSearchParams(window.location.search).get("open");
    if (auto) void run(t("hardening.opening"), () => engine.project(auto)).then((v) => v && dispatch({ type: "setView", view: v }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const step = new URLSearchParams(window.location.search).get("step");
    const known = railSteps().find((s) => s.id === step);
    if (known && state.view) dispatch({ type: "setStep", step: known.id });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.view?.bundle.project.project_id]);

  return (
    <>
      <a className="skip-link" href="#main-content">{t("hardening.skip")}</a>
      {error && !state.view && (
        <div className="error-banner" role="alert">
          <span>{t("app.apiUnreachable", { error })}</span>
          <button type="button" className="btn btn--sm" disabled={loading} onClick={() => void refresh()}>{t("hardening.retry")}</button>
        </div>
      )}
      {state.view ? (
        <Workspace
          onClose={() => {
            dispatch({ type: "setView", view: null });
            void refresh();
          }}
        />
      ) : (
        <StartScreen
          projects={projects}
          catalog={catalog}
          loading={loading}
          unavailable={!!error}
          busy={!!state.busy}
          onRename={async (id, name) => {
            const result = await run(t("s7d.rename"), async () => {
              await engine.updateProject(id, { name }); await refresh(); return true;
            });
            return result === true;
          }}
          onDelete={async (id) => {
            const result = await run(t("s7d.delete"), async () => {
              let gone = false;
              try { await engine.deleteProject(id, id); }
              catch (error) {
                if (!(error instanceof ApiError && error.status === 404)) throw error;
                gone = true;
              }
              if (uiStore.getState().state.view?.bundle.project.project_id === id) dispatch({ type: "setView", view: null });
              await refresh();
              // After the refresh, so the notice is on screen when the row disappears (a slow list could outlast it).
              if (gone) toast("info", t("s7d.alreadyDeleted"));
              return true;
            });
            return result === true;
          }}
          onCreated={(v) => dispatch({ type: "setView", view: v })}
          onImported={(v) => { void refresh(); dispatch({ type: "setView", view: v }); }}
          onOpen={(id) =>
            void run(t("hardening.opening"), () => engine.project(id)).then((v) => {
              if (!v) return;
              dispatch({ type: "setView", view: v });
              track("project.opened");
            })
          }
        />
      )}
      <Toasts />
    </>
  );
}

export default function App() {
  return (
    <StoreProvider>
      <Shell />
    </StoreProvider>
  );
}
