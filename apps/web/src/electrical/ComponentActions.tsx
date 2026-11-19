import { useState } from "react";
import { useTranslation } from "react-i18next";
import { engine } from "../client";
import { DatasheetCompletion } from "../Modals";
import { uiStore, useStore } from "../state/store";
import type { CatalogInverter, CatalogModule, ComponentLibraryPreview } from "../types";
import { Button } from "../ui/kit";

/** USE1: one capability vocabulary everywhere, the library's: "Ready for simulation" or "Layout only". */
export function readinessLabelKey(c: Pick<CatalogInverter | CatalogModule, "simulation_ready"> | undefined): string {
  return c?.simulation_ready === false ? "s12a.layoutOnly" : "s12a.ready";
}

/**
 * "Complete from datasheet" where the gap shows (Components, the inverter card, the Simulate blocker): opens the
 * library's S12a2 dialog for this revision, then reloads the project so its catalog names the completed revision.
 */
export function CompleteFromDatasheet({ revisionId, small = true }: { revisionId: string; small?: boolean }) {
  const { t } = useTranslation();
  const { state, dispatch, toast } = useStore();
  const [base, setBase] = useState<ComponentLibraryPreview | null>(null);
  const open = async () => {
    try {
      const entry = (await engine.componentLibrary(true)).find((e) => e.definition.revision_id === revisionId);
      const preview = entry?.completion_preview;
      if (!preview?.completion_fields?.length) {
        toast("error", t("use1.nothingToComplete"));
        return;
      }
      setBase(preview);
    } catch (err) {
      toast("error", err instanceof Error ? err.message : String(err));
    }
  };
  return (
    <>
      <span data-complete-datasheet={revisionId}>
        <Button small={small} disabled={!!state.busy} onClick={() => void open()}>
          {t("s12a2.title")}
        </Button>
      </span>
      {base && (
        <DatasheetCompletion
          key={base.revision_id}
          base={base}
          onClose={() => setBase(null)}
          onSaved={async (entry) => {
            setBase(null);
            const pid = state.view?.bundle.project.project_id;
            if (pid) {
              const view = await engine.project(pid);
              if (uiStore.getState().state.view?.bundle.project.project_id === pid) dispatch({ type: "setView", view });
            }
            toast("ok", t("s12a2.saved", { revision: entry.revision_id }));
          }}
        />
      )}
    </>
  );
}
