import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, responseError } from "../../src/api";
import { engine } from "../../src/client";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { legacyFieldInput, legacyRefillRequest, missingRefillParameters, pvFieldChanges } from "../../src/engine/layout";
import { NotWiredError } from "../../src/pending";
import { resetStore, uiStore } from "../../src/state/store";
import i18n from "../../src/i18n";

beforeEach(() => { setDemoLatency(0); resetStore(); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("engine error contract", () => {
  it.each([
    [{ detail: "Engine says no" }, "Engine says no"],
    [{ detail: [{ loc: ["body", "tilt_deg"], msg: "invalid tilt" }] }, "body.tilt_deg: invalid tilt"],
    [{ detail: { message: "Field overlaps" } }, "Field overlaps"],
    [{ detail: { message: "Clear", conflicts: [] } }, "Clear (0 conflicts)"],
    [{ detail: { message: "Field overlaps", conflicts: [{}, {}, {}] } }, "Field overlaps (3 conflicts)"],
    [{ detail: { conflicts: [] } }, "Fallback"],
    [{ detail: [] }, "Fallback"], [null, "Fallback"]
  ])("preserves the supported detail shape", (payload, expected) => {
    expect(responseError(payload, "Fallback")).toBe(expected);
  });
  it("carries status and raw detail", async () => {
    const detail = { message: "Geometry refused", conflicts: [{ module_instance_id: "m1" }] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail }), { status: 422, statusText: "Unprocessable Entity" })));
    const error = await api.project("p").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, detail, message: "Geometry refused (1 conflicts)" });
  });
  it("keeps status text for a non-JSON response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Bad gateway", { status: 503, statusText: "Unavailable" })));
    await expect(api.project("p")).rejects.toMatchObject({ status: 503, detail: undefined, message: "Unavailable" });
  });
});

describe("shared run error path", () => {
  it("reloads exactly once on 409 and never retries the operation", async () => {
    const old = await mockApi.project("demo-project");
    const fresh = structuredClone(old); fresh.bundle.project.name = "Latest version";
    uiStore.getState().dispatch({ type: "setView", view: old });
    const reload = vi.spyOn(engine, "project").mockResolvedValue(fresh);
    const operation = vi.fn().mockRejectedValue(new ApiError("project changed concurrently; reload and retry", 409, "raw"));
    expect(await uiStore.getState().run("Editing", operation)).toBeUndefined();
    expect(operation).toHaveBeenCalledTimes(1); expect(reload).toHaveBeenCalledTimes(1);
    expect(reload).toHaveBeenCalledWith("demo-project");
    expect(uiStore.getState().state.view?.bundle.project.name).toBe("Latest version");
    expect(uiStore.getState().state.toasts.at(-1)).toMatchObject({ tone: "info", text: i18n.t("s7a.concurrentReload") });
    expect(uiStore.getState().state.busy).toBeNull();
  });
  it.each([[new ApiError("Engine refusal", 422, {}), "error", "Engine refusal"],
    [new NotWiredError("undoRedo"), "pending", "Not wired"]])("retains existing other-error behavior", async (error, tone, text) => {
    await uiStore.getState().run("Editing", () => Promise.reject(error));
    expect(uiStore.getState().state.toasts.at(-1)?.tone).toBe(tone);
    expect(uiStore.getState().state.toasts.at(-1)?.text).toContain(text);
  });
});

describe("S4 request shapes", () => {
  it("PATCHes only supplied changes/options and returns the dry-run preview", async () => {
    const preview = { dry_run: true, pv_field_id: "f", string_ids: ["S1"] };
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(preview), { status: 200 })));
    vi.stubGlobal("fetch", fetch);
    expect(await api.previewPvFieldUpdate("p /", "f /", { tilt_deg: 15 })).toEqual(preview);
    expect(fetch.mock.calls[0][0]).toBe("/api/projects/p%20%2F/pv-fields/f%20%2F");
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: "PATCH" });
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ tilt_deg: 15, dry_run: true });
    await api.updatePvField("p", "f", { tilt_deg: 15 }, { discard_dependent_strings: true });
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ tilt_deg: 15, discard_dependent_strings: true });
    await api.updatePvField("p", "f", { name: "Renamed" });
    expect(JSON.parse(fetch.mock.calls[2][1].body)).toEqual({ name: "Renamed" });
  });
  it("DELETE uses query flags and no body", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200 })));
    vi.stubGlobal("fetch", fetch);
    await api.previewPvFieldDelete("p", "f"); await api.deletePvField("p", "f", { discard_dependent_strings: true }); await api.deletePvField("p", "f");
    expect(fetch.mock.calls.map((c) => c[0])).toEqual(["/api/projects/p/pv-fields/f?dry_run=true", "/api/projects/p/pv-fields/f?discard_dependent_strings=true", "/api/projects/p/pv-fields/f"]);
    expect(fetch.mock.calls.every((c) => c[1].method === "DELETE" && c[1].body === undefined)).toBe(true);
  });
});

describe("lossless legacy-field mapping", () => {
  it("stores the approved demo seed metadata with its original modules/strings/counts", async () => {
    const view = await mockApi.project("demo-project"); const f = view.bundle.scene.pv_fields[0];
    expect(f).toMatchObject({ module_gap_x_m: 0.02, module_gap_y_m: 0.02, row_pitch_m: 3.1, mounting_height_m: 0.2,
      setback_configuration: { perimeter_setback_m: 1.2, obstacle_setback_m: 0.6 }, row_count: 4, modules_per_row: 19 });
    expect(view.bundle.scene.module_instances).toHaveLength(76);
    expect(view.bundle.electrical_design.strings.map((s) => s.module_instance_ids.length)).toEqual([16, 16, 16, 14, 14]);
  });
  it("maps untouched fields to no changes, and tilt to the fresh-fill pitch", async () => {
    const view = await mockApi.project("demo-project"); const field = view.bundle.scene.pv_fields[0], mod = view.catalog.modules[0];
    const request = legacyRefillRequest(field, mod, 4)!;
    expect(pvFieldChanges(request, field, mod)).toEqual({ changes: {}, reasons: [] });
    const changed = { ...request, tilt_deg: 15 };
    const mapped = pvFieldChanges(changed, field, mod);
    const fresh = legacyFieldInput({ ...changed, pv_field_id: null }, mod).input!;
    expect(mapped.changes).toEqual({ tilt_deg: 15, row_pitch_m: fresh.row_pitch_m });
    expect(pvFieldChanges({ ...request, azimuth_deg: 360 }, field, mod).reasons).toContain("azimuth_deg must be within [0, 360)");
    for (const changes of [{ walkway: { every_modules: 3, width_m: 1 } }, { max_table_columns: 4 },
      { edge_setbacks_m: [1, 2, 1, 1] }, { pitch: { mode: "shading_free" as const, sun_elevation_deg: 30, sun_azimuth_offset_deg: 0 } }]) {
      expect(pvFieldChanges({ ...request, ...changes }, field, mod).reasons.length).toBeGreaterThan(0);
    }
  });
  it("names missing real-bundle parameters and never substitutes defaults (A3)", async () => {
    const view = await mockApi.project("demo-project"); const field = structuredClone(view.bundle.scene.pv_fields[0]);
    delete field.module_gap_y_m; delete field.row_pitch_m; delete field.setback_configuration?.obstacle_setback_m;
    expect(missingRefillParameters(field)).toEqual(["module_gap_y_m", "row_pitch_m", "setback_configuration.obstacle_setback_m"]);
    expect(legacyRefillRequest(field, view.catalog.modules[0], 4)).toBeNull();
  });
});

describe("new demo adapter operations", () => {
  it("previews without writes, requires string discard and deletes whole strings on re-fill", async () => {
    const before = await mockApi.project("demo-project");
    const preview = await mockApi.previewPvFieldUpdate("demo-project", "fld-a", { tilt_deg: 15 });
    expect(preview.requires_discard_dependent_strings).toBe(true);
    expect(await mockApi.project("demo-project")).toEqual(before);
    await expect(mockApi.updatePvField("demo-project", "fld-a", { tilt_deg: 15 })).rejects.toThrow("discard_dependent_strings=true");
    expect(await mockApi.project("demo-project")).toEqual(before);
    const after = await mockApi.updatePvField("demo-project", "fld-a", { tilt_deg: 15 }, { discard_dependent_strings: true });
    expect(after.bundle.scene.pv_fields).toHaveLength(1); expect(after.bundle.scene.pv_fields[0].tilt_deg).toBe(15);
    expect(after.bundle.scene.module_instances).toHaveLength(preview.module_count_after);
    expect(after.bundle.electrical_design.strings).toEqual([]);
    await mockApi.undo("demo-project");
  });
  it("deletion previews counts/power/strings and requires its flag", async () => {
    const before = await mockApi.project("demo-project");
    const preview = await mockApi.previewPvFieldDelete("demo-project", "fld-a");
    expect(preview).toMatchObject({ module_count: 76, stc_power_w: 76 * 550, requires_discard_dependent_strings: true });
    expect(await mockApi.project("demo-project")).toEqual(before);
    await expect(mockApi.deletePvField("demo-project", "fld-a")).rejects.toThrow("discard_dependent_strings=true");
    const result = await mockApi.deletePvField("demo-project", "fld-a", { discard_dependent_strings: true });
    expect(result.bundle.scene.pv_fields).toEqual([]); expect(result.bundle.scene.module_instances).toEqual([]);
    expect(result.bundle.electrical_design.strings).toEqual([]);
    await mockApi.undo("demo-project");
  });
  it("retains every supplied legacy create parameter", async () => {
    const view = await mockApi.addSurface("demo-project", { name: "Extra", origin_x_m: 100, origin_y_m: 0, width_m: 12, height_m: 8, base_elevation_m: 0, surface_type: "flat_roof" });
    const input = { name: "Legacy", support_surface_id: view.bundle.scene.surfaces.at(-1)!.surface_id, module_definition_revision_id: "mod-demo-550",
      orientation: "portrait", azimuth_deg: 0, tilt_deg: 10, module_gap_x_m: 0.03, module_gap_y_m: 0.04, row_pitch_m: 3.2, mounting_height_m: 0.4, perimeter_setback_m: 0.5, obstacle_setback_m: 0.7 };
    const created = await mockApi.createPvField("demo-project", input);
    expect(created.bundle.scene.pv_fields.at(-1)).toMatchObject(input);
    await mockApi.undo("demo-project"); await mockApi.undo("demo-project");
  });
});

it("demo manual layouts require their own explicit discard flag", async () => {
  const roof = await mockApi.addSurface("demo-project", { name: "Manual fixture", origin_x_m: 200, origin_y_m: 0,
    width_m: 12, height_m: 8, base_elevation_m: 0, surface_type: "flat_roof" });
  // An explicitly authored demo fixture, not a parameter sent by the UI.
  const input = { name: "Manual", support_surface_id: roof.bundle.scene.surfaces.at(-1)!.surface_id, module_definition_revision_id: "mod-demo-550",
    orientation: "portrait", azimuth_deg: 0, tilt_deg: 10, module_gap_x_m: 0.02, module_gap_y_m: 0.02, row_pitch_m: 3.2,
    mounting_height_m: 0.2, perimeter_setback_m: 0.3, obstacle_setback_m: 0.3, layout_status: "manual" };
  const view = await mockApi.createPvField("demo-project", input);
  const field = view.bundle.scene.pv_fields.at(-1)!.pv_field_id;
  expect((await mockApi.previewPvFieldUpdate("demo-project", field, { tilt_deg: 15 })).requires_discard_manual_layout).toBe(true);
  await expect(mockApi.updatePvField("demo-project", field, { tilt_deg: 15 })).rejects.toThrow("discard_manual_layout=true");
  expect(await mockApi.project("demo-project")).toEqual(view);
  const updated = await mockApi.updatePvField("demo-project", field, { tilt_deg: 15 }, { discard_manual_layout: true });
  expect(updated.bundle.scene.pv_fields.at(-1)?.tilt_deg).toBe(15);
});
