import { afterEach, expect, it, vi } from "vitest";
import i18n from "../../src/i18n";
import { engineCommand } from "../../src/state/history";
import { resetStore, uiStore } from "../../src/state/store";
import type { ProjectView } from "../../src/types";
import fixture from "./s7b-engine-fixture.json";

afterEach(async () => { resetStore(); await i18n.changeLanguage("en"); });

it.each([
  ["en", "Another command is still running."],
  ["id", "Perintah lain masih berjalan."],
])("a busy command click is visibly refused without sending or retrying it (%s)", async (language, message) => {
  resetStore(); await i18n.changeLanguage(language);
  const view = structuredClone(fixture.views.before) as unknown as ProjectView;
  uiStore.getState().dispatch({ type: "setView", view });
  let release!: (view: ProjectView) => void;
  const assigning = engineCommand("Assigning strings", () => new Promise<ProjectView>((resolve) => { release = resolve; }));
  const deleteRequest = vi.fn(async () => view);
  try {
    // The same command wrapper used by the Delete strings button is called while
    // the first response is still pending. This attempt must never reach the API.
    expect(await engineCommand("Deleting strings", deleteRequest)).toBeUndefined();
    expect(deleteRequest).not.toHaveBeenCalled();
    const state = uiStore.getState().state;
    expect(state.toasts.at(-1)).toMatchObject({ tone: "info", text: message });
    expect(state.busy).toBe("Assigning strings"); expect(state.past).toEqual([]);
    release(view); await assigning;
    expect(deleteRequest).not.toHaveBeenCalled(); // There is no queue or automatic retry.
    expect(uiStore.getState().state.busy).toBeNull();
    expect(uiStore.getState().state.past).toHaveLength(1);
    await engineCommand("Deleting strings", deleteRequest);
    expect(deleteRequest).toHaveBeenCalledTimes(1);
    expect(uiStore.getState().state.past).toHaveLength(2);
  } finally {
    release(view); await assigning;
  }
});
