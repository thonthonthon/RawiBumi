import { afterEach, expect, it } from "vitest";
import { responseError } from "../../src/api";
import { typingTarget } from "../../src/commands/keys";
import { mockApi } from "../../src/demo/mockApi";
import { engineCommand, redo, undo } from "../../src/state/history";
import { resetStore, uiStore } from "../../src/state/store";
import type { ProjectView } from "../../src/types";

afterEach(resetStore);

it("formats engine validation details without hiding their field or message", () => {
  expect(responseError({ detail: [{ loc: ["body", "timezone"], msg: "Unknown timezone" }] }, "Bad request")).toBe("body.timezone: Unknown timezone");
  expect(responseError({ detail: "Engine message verbatim" }, "Bad request")).toBe("Engine message verbatim");
  for (const payload of [null, "proxy", { detail: {} }, { detail: [null, 3, { msg: 4 }] }]) expect(responseError(payload, "Bad gateway")).toBe("Bad gateway");
});

it("distinguishes text entry from checkbox and file controls for shortcuts", () => {
  for (const type of ["checkbox", "radio", "button", "file", "range"]) expect(typingTarget(Object.assign(new EventTarget(), { tagName: "INPUT", type }))).toBe(false);
  for (const type of ["text", "number", "search"]) expect(typingTarget(Object.assign(new EventTarget(), { tagName: "INPUT", type }))).toBe(true);
  expect(typingTarget(Object.assign(new EventTarget(), { isContentEditable: true }))).toBe(true);
});

it("a pending command locks repeated commands and both history directions", async () => {
  let release!: (view: ProjectView) => void;
  const base = await mockApi.project("demo-project");
  const task = engineCommand("First", () => new Promise<ProjectView>((resolve) => { release = resolve; }));
  let called = false;
  expect(await engineCommand("Second", async () => { called = true; return base; })).toBeUndefined();
  await undo(); await redo();
  expect(called).toBe(false); expect(uiStore.getState().state.busy).toBe("First");
  release(base); await task;
  expect(uiStore.getState().state.past).toHaveLength(1);
  expect(uiStore.getState().state.busy).toBeNull();
});

it("rejection releases the lock without recording history and allows a retry", async () => {
  await engineCommand("Failed", async () => { throw new Error("Try again"); });
  const state = uiStore.getState().state;
  expect(state.busy).toBeNull(); expect(state.past).toEqual([]);
  expect(state.toasts.at(-1)?.text).toBe("Try again");
  await engineCommand("Retry", () => mockApi.project("demo-project"));
  expect(uiStore.getState().state.past).toHaveLength(1);
});

it("project changes clear drafts, history, targets, report choices and previews", async () => {
  const base = await mockApi.project("demo-project");
  const { dispatch } = uiStore.getState();
  dispatch({ type: "setView", view: base });
  dispatch({ type: "setForm", key: "results.run", value: "old-run" });
  dispatch({ type: "setTarget", target: "old-mppt" });
  dispatch({ type: "checkpoint" });
  const other = structuredClone(base); other.bundle.project.project_id = "other";
  dispatch({ type: "setView", view: other });
  expect(uiStore.getState().state.forms).toEqual({});
  expect(uiStore.getState().state.past).toEqual([]);
  expect(uiStore.getState().state.target).toBeNull();
  dispatch({ type: "setView", view: null });
  expect(uiStore.getState().state.electrical).toEqual({});
});

it("a new demo project preserves the entered site and workspace mode in both views", async () => {
  const view = await mockApi.createProject({ name: "Entered site", latitude_deg: -8, longitude_deg: 115, elevation_m: 725, timezone: "Asia/Makassar", workspace_mode: "map_overlay" });
  expect(view.bundle.project.site.elevation_m).toBe(725);
  expect(view.scene_view.site).toEqual(view.bundle.project.site);
  expect(view.bundle.site_workspace_bootstrap.workspace_context.mode).toBe("map_overlay");
});
