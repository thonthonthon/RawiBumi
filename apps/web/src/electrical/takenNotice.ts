import i18n from "../i18n";
import type { ProjectView } from "../types";

/** Shared by the HTTP and demo manual-string actions. */
export async function notifyTakenModules(view: ProjectView): Promise<ProjectView> {
  const results = (view as ProjectView & { command_results?: { result?: { taken_from?: Record<string, string[]>; deleted_string_ids?: string[] } }[] }).command_results ?? [];
  for (const { result } of results) {
    for (const [string, modules] of Object.entries(result?.taken_from ?? {})) {
      const removed = result?.deleted_string_ids?.includes(string) ? i18n.t("str1.removed", { string }) : "";
      const { uiStore } = await import("../state/store");
      uiStore.getState().toast("info", i18n.t("str1.moved", { count: modules.length, string, removed }));
    }
  }
  return view;
}
