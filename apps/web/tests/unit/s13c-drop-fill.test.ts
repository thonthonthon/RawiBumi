import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { api } from "../../src/api";
import { engine } from "../../src/client";
import { resetStore, uiStore } from "../../src/state/store";
import { cancelModuleFill, confirmModuleFill, dragModules, moduleFill, moduleReasonText, moveModules } from "../../src/canvas/useModuleEdits";
import i18n from "../../src/i18n";
import { ApiError, type ModuleFillPreview, type ModuleMoveReason, type ProjectView } from "../../src/types";

const reason: ModuleMoveReason = { code: "module_obstacle_overlap", count: 3, name: "AHU-1", message: "3 modules would overlap obstacle AHU-1" };
const conflict = new ApiError("refused", 422, { conflicts: [{ code: reason.code }], reasons: [reason] });
let view: ProjectView;
beforeEach(async () => {
  resetStore(); cancelModuleFill(); setDemoLatency(0); void i18n.changeLanguage("en");
  view = await mockApi.project("demo-project");
  uiStore.getState().dispatch({ type: "setView", view });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); resetStore(); cancelModuleFill(); setDemoLatency(1); void i18n.changeLanguage("en"); });
const preview: ModuleFillPreview = { dry_run: true, mode: "fill", placed_count: 2, removed_count: 1,
  placed_ids: ["m001", "m002"], removed_ids: ["m003"], string_ids: ["S001"], requires_discard_dependent_strings: true,
  stc_power_w_before: 1650, stc_power_w_after: 1100, reasons: [reason] };

it.each([true, false])("preview is read-only, Cancel sends nothing, Confirm sends only required flags (%s)", async (discard) => {
  const ids = view.bundle.scene.module_instances.slice(0, 3).map((m) => m.module_instance_id);
  const ownPreview = { ...preview, placed_ids: ids.slice(0, 2), removed_ids: ids.slice(2), requires_discard_dependent_strings: discard };
  const calls = vi.spyOn(engine, "moduleCommands").mockRejectedValueOnce(conflict).mockResolvedValueOnce(ownPreview).mockResolvedValueOnce(view);
  await dragModules(ids, [2, 0]);
  expect(moduleFill.getState().pending?.preview).toEqual(ownPreview);
  expect(uiStore.getState().state.past).toHaveLength(0);
  expect(calls.mock.calls[1][1]).toEqual({ command: "move_modules", module_instance_ids: ids, dx_m: 2, dy_m: 0, on_conflict: "fill", dry_run: true });
  cancelModuleFill(); expect(calls).toHaveBeenCalledTimes(2);
  moduleFill.setState({ pending: { projectId: view.bundle.project.project_id, ids, delta: [2, 0], preview: ownPreview, reasons: [reason] } });
  await confirmModuleFill();
  expect(calls.mock.calls[2][1]).toEqual({ command: "move_modules", module_instance_ids: ids, dx_m: 2, dy_m: 0, on_conflict: "fill", ...(discard ? { discard_dependent_strings: true } : {}) });
  expect(moduleFill.getState().pending).toBeNull(); expect(uiStore.getState().state.selection).toEqual(ids.slice(0, 2));
});

it("unavailable fill has reasons and no preview/confirm operation; nudge never requests fill", async () => {
  const calls = vi.spyOn(engine, "moduleCommands").mockRejectedValueOnce(conflict).mockRejectedValueOnce(new ApiError("No modules fit", 422, { reasons: [{ code: "drop_fill_no_slots", count: 3, message: "No modules fit" }] }));
  await dragModules(["m001"], [2, 0]);
  expect(moduleFill.getState().pending?.preview).toBeUndefined(); expect(moduleFill.getState().pending?.reasons[0].code).toBe("drop_fill_no_slots");
  await confirmModuleFill(); expect(calls).toHaveBeenCalledTimes(2);
  cancelModuleFill(); calls.mockRejectedValueOnce(conflict); await moveModules(["m001"], [.1, 0]);
  expect(calls).toHaveBeenCalledTimes(3); expect(moduleFill.getState().pending).toBeNull();
  expect(uiStore.getState().state.toasts.at(-1)?.text).toContain(reason.message);
});

it("exact moves avoid fill; busy gestures send nothing; preview 409 reloads without retry", async () => {
  const calls = vi.spyOn(engine, "moduleCommands").mockResolvedValueOnce(view);
  await dragModules(["m001"], [.01, 0]); expect(calls).toHaveBeenCalledTimes(1); expect(moduleFill.getState().pending).toBeNull();
  uiStore.getState().dispatch({ type: "busy", label: "other" }); await dragModules(["m001"], [2, 0]); expect(calls).toHaveBeenCalledTimes(1);
  uiStore.getState().dispatch({ type: "busy", label: null });
  calls.mockRejectedValueOnce(conflict).mockRejectedValueOnce(new ApiError("project changed concurrently; reload and retry", 409));
  const reload = vi.spyOn(engine, "project").mockResolvedValue(view);
  await dragModules(["m001"], [2, 0]); expect(reload).toHaveBeenCalledOnce(); expect(calls).toHaveBeenCalledTimes(3);
});

it("renders authoritative English and parameterized Indonesian with unknown fallback", () => {
  expect(moduleReasonText(reason)).toBe(reason.message);
  void i18n.changeLanguage("id"); expect(moduleReasonText(reason)).toBe("3 modul akan bertumpang tindih dengan penghalang AHU-1");
  expect(moduleReasonText({ code: "module_outside_support_or_setback", count: 2, name: "Roof A", setback: .5, message: "fallback" })).toContain("2 modul akan keluar dari atap Roof A atau jarak tepinya 0.5 m");
  expect(moduleReasonText({ code: "future_rule", count: 1, message: "future_rule" })).toBe("future_rule");
});

it("A4 keeps the service English verbatim, including singular grammar, and unknown messages in both languages", () => {
  const singular = { ...reason, count: 1, message: "1 module would overlap obstacle AHU-1" };
  expect(moduleReasonText(singular)).toBe(singular.message);
  const unknown = { code: "future_rule", count: 2, message: "A new engine reason with its own wording" };
  for (const language of ["en", "id"]) {
    void i18n.changeLanguage(language);
    expect(moduleReasonText(unknown)).toBe(unknown.message);
  }
});

it("adapter posts fill bodies once; demo refuses fill honestly without changing its view", async () => {
  const body = { command: "move_modules", module_instance_ids: [view.bundle.scene.module_instances[0].module_instance_id], dx_m: 1, dy_m: 0, on_conflict: "fill", dry_run: true } as const;
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(preview), { status: 200 })); vi.stubGlobal("fetch", fetch);
  await api.moduleCommands("project", { ...body, module_instance_ids: [...body.module_instance_ids] });
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(body); expect(fetch).toHaveBeenCalledOnce();
  const before = structuredClone(await mockApi.project("demo-project"));
  await expect(mockApi.moduleCommands("demo-project", { ...body, module_instance_ids: [...body.module_instance_ids] })).rejects.toThrow("Drop-to-fill needs the engine");
  expect(await mockApi.project("demo-project")).toEqual(before);
});
