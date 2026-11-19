import { useEffect, useState } from "react";
import { engine } from "./client";
import { StartScreen } from "./StartScreen";
import { StoreProvider, useStore } from "./state/store";
import type { Catalog, ProjectSummary } from "./types";
import { Workspace } from "./Workspace";

function Shell() {
  const { state, dispatch, run } = useStore();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const [p, c] = await Promise.all([engine.projects(), engine.catalog()]);
      setProjects(p);
      setCatalog(c);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void refresh();
    const auto = new URLSearchParams(window.location.search).get("open");
    if (auto) void run("Opening", () => engine.project(auto)).then((v) => v && dispatch({ type: "setView", view: v }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const step = new URLSearchParams(window.location.search).get("step");
    if (step && state.view) dispatch({ type: "setStep", step: step as never });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.view?.bundle.project.project_id]);

  return (
    <>
      {error && !state.view && (
        <div className="error-banner">
          <span>Engine API unreachable: {error}. Start the API (uvicorn apps.api.server:app) or run the UI in demo mode (npm run dev:demo).</span>
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
          busy={!!state.busy}
          onCreated={(v) => dispatch({ type: "setView", view: v })}
          onOpen={(id) => void run("Opening", () => engine.project(id)).then((v) => v && dispatch({ type: "setView", view: v }))}
        />
      )}
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
