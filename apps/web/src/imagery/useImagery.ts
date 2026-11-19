import { useMemo } from "react";
import { engine } from "../client";
import i18n from "../i18n";
import { engineCommand } from "../state/history";
import { useUI } from "../state/store";
import { imageryConfig, parseImagery, type ProjectImagery } from "./config";

/** The project's persisted imagery and its save path: one engine command, one undo step, no scene revision. */
export function useImagery() {
  const raw = useUI((s) => ({ config: s.view?.bundle.imagery, projectId: s.view?.bundle.project.project_id ?? null }));
  const imagery = useMemo(() => parseImagery(raw.config), [raw.config]);
  const save = (next: ProjectImagery, label = i18n.t("imagery.saving")) => {
    const projectId = raw.projectId;
    if (!projectId) return Promise.resolve(undefined);
    return engineCommand(label, () => engine.updateImagery(projectId, imageryConfig(next)));
  };
  return { imagery, save, projectId: raw.projectId };
}
