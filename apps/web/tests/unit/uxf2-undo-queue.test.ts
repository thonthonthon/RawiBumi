import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { engine } from "../../src/client";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { resetStore, uiStore } from "../../src/state/store";
import { undo, redo } from "../../src/state/history";
import type { ProjectView } from "../../src/types";
import "../../src/i18n";

// UXF2 (U2-22): an undo pressed while an edit saves is queued and runs once the save finishes; a press while an undo
// itself runs is still ignored (S17), so one press is never two steps.
let base: ProjectView;
beforeEach(async () => { resetStore(); setDemoLatency(0); base = structuredClone(await mockApi.project("demo-project")); });
afterEach(() => vi.restoreAllMocks());
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

it("an undo pressed during a save runs when the save finishes, once, with a notice", async () => {
  const { dispatch } = uiStore.getState();
  dispatch({ type: "setView", view: base });
  dispatch({ type: "busy", label: "Editing roof and PV fields" });
  const operation = vi.spyOn(engine, "undo").mockResolvedValue(base);
  await undo();
  expect(operation).not.toHaveBeenCalled();
  expect(uiStore.getState().state.toasts.at(-1)?.text).toBe("Undo will run when saving finishes.");
  dispatch({ type: "engineCommitted", view: base, label: "Editing roof and PV fields" }); // the save adds its step
  dispatch({ type: "busy", label: null });
  await flush();
  expect(operation).toHaveBeenCalledTimes(1);
  expect(uiStore.getState().state.past).toHaveLength(0);
});

it("a second press while an undo or redo runs is ignored, not queued", async () => {
  const { dispatch } = uiStore.getState();
  dispatch({ type: "setView", view: base });
  dispatch({ type: "engineCommitted", view: base, label: "Moving" });
  const undoCall = vi.spyOn(engine, "undo").mockResolvedValue(base);
  const redoCall = vi.spyOn(engine, "redo").mockResolvedValue(base);
  for (const label of ["Undoing moving", "Redoing moving"]) {
    dispatch({ type: "busy", label });
    await undo(); await redo();
    dispatch({ type: "busy", label: null });
    await flush();
  }
  expect(undoCall).not.toHaveBeenCalled();
  expect(redoCall).not.toHaveBeenCalled();
});
