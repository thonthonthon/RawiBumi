import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, newCommandId } from "../../src/api";
import { engine } from "../../src/client";
import { ApiError } from "../../src/types";
import { resetStore, uiStore } from "../../src/state/store";
import fixture from "./s7b-engine-fixture.json";
import type { ProjectView } from "../../src/types";

beforeEach(resetStore);
afterEach(() => { resetStore(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("uses the exact S6 edit/delete and defaults request contracts", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200 })));
  vi.stubGlobal("fetch", fetch);
  await api.updateProject("p /", { name: "Renamed", description: "Description" });
  await api.updateSite("p /", { latitude_deg: -7 }, { clear_weather_selection: true });
  await api.updateSite("p /", { name: "Site only" });
  await api.deleteProject("p /", "p /"); await api.simulationDefaults();
  expect(fetch.mock.calls.map(([url, init]) => [url, init.method ?? "GET", init.body && JSON.parse(init.body)])).toEqual([
    ["/api/projects/p%20%2F", "PATCH", { name: "Renamed", description: "Description" }],
    ["/api/projects/p%20%2F/site", "PATCH", { latitude_deg: -7, clear_weather_selection: true }],
    ["/api/projects/p%20%2F/site", "PATCH", { name: "Site only" }],
    ["/api/projects/p%20%2F?confirm=p%20%2F", "DELETE", undefined], ["/api/simulation-defaults", "GET", undefined]
  ]);
});
it("creates distinct RFC 4122 v4 command ids without randomUUID, including both command routes", async () => {
  const getRandomValues = crypto.getRandomValues.bind(crypto);
  vi.stubGlobal("crypto", { getRandomValues });
  const ids = new Set(Array.from({ length: 100 }, () => newCommandId()));
  expect(ids.size).toBe(100);
  for (const id of ids) expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200 })));
  vi.stubGlobal("fetch", fetch);
  await api.sceneCommand("p", { command_type: "move", target_entity_ids: ["roof"], parameters: { dx_m: 1, dy_m: 0 } });
  await api.topologyCommand("p", { command_type: "delete_strings", parameters: { string_ids: ["S001"] } });
  for (const [, init] of fetch.mock.calls) {
    const body = JSON.parse(init.body); expect((body.command ?? body.commands[0]).command_id).toMatch(/^[0-9a-f-]{36}$/);
  }
});
it.each([true, false])("distinguishes a busy 409 (busy=%s) from a concurrent update without retry", async (busy) => {
  const view = structuredClone(fixture.views.before) as unknown as ProjectView;
  uiStore.getState().dispatch({ type: "setView", view });
  const reload = vi.spyOn(engine, "project").mockResolvedValue(view);
  const message = busy ? "project has a simulation or weather acquisition in progress; retry after it finishes" : "project changed concurrently; reload and retry";
  const operation = vi.fn().mockRejectedValue(new ApiError(message, 409, message));
  await uiStore.getState().run("Editing site", operation);
  expect(operation).toHaveBeenCalledTimes(1); expect(reload).toHaveBeenCalledTimes(busy ? 0 : 1);
  const toast = uiStore.getState().state.toasts.at(-1)!;
  if (busy) expect(toast).toMatchObject({ tone: "error", text: message });
  else expect(toast.text).toContain("changed elsewhere");
});

it("demo metadata/site/delete methods preserve revisions, geometry and weather confirmation semantics", async () => {
  const { mockApi, setDemoLatency } = await import("../../src/demo/mockApi"); setDemoLatency(0);
  const created = await mockApi.createProject({ name: "S7d demo", latitude_deg: -6.2, longitude_deg: 106.8, elevation_m: 25, timezone: "Asia/Jakarta", workspace_mode: "map_overlay" });
  const id = created.bundle.project.project_id;
  await mockApi.acquireWeather(id, { source_id: "demo-tmy", start_date: "2025-01-01", end_date: "2025-01-01" });
  const initial = await mockApi.project(id);
  const renamed = await mockApi.updateProject(id, { name: "Renamed demo", description: "Description" });
  expect(renamed.bundle.project.project_revision).toEqual(initial.bundle.project.project_revision);
  expect(renamed.bundle.project).toHaveProperty("description", "Description");
  const named = await mockApi.updateSite(id, { name: "Named site" });
  expect(named.bundle.weather_selection).toEqual(initial.bundle.weather_selection);
  await expect(mockApi.updateSite(id, { timezone: "Asia/Makassar" })).rejects.toThrow(/Confirm clearing/);
  const updated = await mockApi.updateSite(id, { timezone: "Asia/Makassar", latitude_deg: -7.25 }, { clear_weather_selection: true });
  expect(updated.bundle.weather_selection).toBeNull();
  expect(updated.scene_view.site).toEqual(updated.bundle.project.site);
  expect(updated.scene_view.local_features).toEqual(initial.scene_view.local_features);
  expect((await mockApi.projects())[0]).toMatchObject({ name: "Renamed demo", timezone: "Asia/Makassar", latitude_deg: -7.25 });
  await expect(mockApi.deleteProject(id, "wrong")).rejects.toThrow(/Confirmation/);
  expect(await mockApi.projects()).toHaveLength(1);
  expect(await mockApi.deleteProject(id, id)).toMatchObject({ deleted_project_id: id, removed: { bundle: true } });
  expect(await mockApi.projects()).toEqual([]);
  await expect(mockApi.project(id)).rejects.toMatchObject({ status: 404 });
  await mockApi.createProject({ name: "Next demo", latitude_deg: 0, longitude_deg: 0, timezone: "UTC" });
  expect(await mockApi.projects()).toHaveLength(1);
});
