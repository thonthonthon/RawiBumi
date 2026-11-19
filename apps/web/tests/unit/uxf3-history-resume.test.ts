import { beforeEach, expect, it } from "vitest";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { resetStore, uiStore } from "../../src/state/store";
import type { ProjectView } from "../../src/types";

// UXF3 (U2-27): opening a project (also after a page reload) resumes the engine's saved undo and redo steps, so Undo
// still reaches the engine; demo history is never adopted this way.
let base: ProjectView;
beforeEach(async () => { resetStore(); setDemoLatency(0); base = structuredClone(await mockApi.project("demo-project")); });

it("an engine project's saved steps become the undo and redo lists on open", () => {
  const view = { ...base, history: { authority: "engine", limit: 10, reason: null,
    past: [{ entry_id: "e1", label: "Edit imagery" }, { entry_id: "e2", label: "Electrical commands: ['create_string', 'join_strings']" }],
    future: [{ entry_id: "e3", label: "Moving" }] } } as unknown as ProjectView;
  uiStore.getState().dispatch({ type: "setView", view });
  const { past, future } = uiStore.getState().state;
  expect(past).toEqual([{ kind: "engine", label: "Edit imagery", entryId: "e1" },
    { kind: "engine", label: "Electrical commands: ['create_string', 'join_strings']", entryId: "e2" }]);
  expect(future).toEqual([{ kind: "engine", label: "Moving", entryId: "e3" }]);
});

it("a demo project opens with empty lists, as before", () => {
  uiStore.getState().dispatch({ type: "setView", view: base });
  expect(uiStore.getState().state.past).toEqual([]);
  expect(uiStore.getState().state.future).toEqual([]);
});
