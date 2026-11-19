import { isExplicitField } from "../types";
import { create } from "zustand";
import { engine } from "../client";
import i18n from "../i18n";
import { engineCommand } from "../state/history";
import { uiStore } from "../state/store";
import { ApiError, type ModuleDeletePreview, type ModuleFillPreview, type ModuleMoveReason } from "../types";
import type { Vec2 } from "../geometry";

function readOnlySelection(ids: readonly string[]) {
  const store = uiStore.getState(), view = store.state.view;
  if (!view) return false;
  const fields = new Set(view.bundle.scene.pv_fields.filter(isExplicitField).map(f => f.pv_field_id));
  const readOnly = view.bundle.scene.module_instances.some(m => ids.includes(m.module_instance_id) && fields.has(m.pv_field_id));
  if (readOnly) store.toast("info", i18n.t("mesh1.noRefill"));
  return readOnly;
}
interface PendingDelete { projectId: string; ids: string[]; preview: ModuleDeletePreview }
export const moduleDeletion = create<{ pending: PendingDelete | null }>(() => ({ pending: null }));
export const cancelModuleDelete = () => moduleDeletion.setState({ pending: null });

export function moduleDragDelta(start: Vec2, end: Vec2, shift: boolean): Vec2 {
  const d: Vec2 = [end[0] - start[0], end[1] - start[1]];
  return shift ? [Math.round(d[0] * 10) / 10, Math.round(d[1] * 10) / 10] : d;
}
export function moduleNudge(key: string, shift: boolean): Vec2 | null {
  const arrows: Record<string, Vec2> = { ArrowUp: [0, 1], ArrowDown: [0, -1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] };
  const d = arrows[key], k = shift ? 1 : .1;
  return d ? [d[0] * k, d[1] * k] : null;
}
export function moduleDeleteFlags(preview: Pick<ModuleDeletePreview, "requires_discard_dependent_strings">): { discard_dependent_strings?: true } {
  return preview.requires_discard_dependent_strings ? { discard_dependent_strings: true } : {};
}

export async function previewModuleDelete(ids: readonly string[]) {
  const state = uiStore.getState().state, projectId = state.view?.bundle.project.project_id;
  if (!projectId || state.busy || !ids.length) return;
  if (readOnlySelection(ids)) return;
  await engineCommand(i18n.t("s13b.previewing"), async () => {
    const preview = await engine.moduleCommands(projectId, { command: "delete_modules", module_instance_ids: [...ids], dry_run: true });
    moduleDeletion.setState({ pending: { projectId, ids: [...ids], preview } });
    return undefined;
  });
}
export async function confirmModuleDelete() {
  const pending = moduleDeletion.getState().pending;
  if (!pending || uiStore.getState().state.busy) return;
  const view = await engineCommand(i18n.t("s13b.deleting"), () => engine.moduleCommands(pending.projectId, {
    command: "delete_modules", module_instance_ids: pending.ids, ...moduleDeleteFlags(pending.preview)
  }));
  if (view) cancelModuleDelete();
}
interface PendingFill { projectId: string; ids: string[]; delta: Vec2; preview?: ModuleFillPreview; reasons: ModuleMoveReason[] }
export const moduleFill = create<{ pending: PendingFill | null }>(() => ({ pending: null }));
export const cancelModuleFill = () => moduleFill.setState({ pending: null });
export function moduleReasonText(reason: ModuleMoveReason): string {
  if (i18n.language.split("-")[0] === "en") return reason.message;
  return i18n.t(`s13c.reasons.${reason.code}`, { ...reason, defaultValue: reason.message });
}
function errorReasons(error: unknown): ModuleMoveReason[] {
  if (error instanceof ApiError && error.detail && typeof error.detail === "object" && "reasons" in error.detail
      && Array.isArray(error.detail.reasons)) return error.detail.reasons as ModuleMoveReason[];
  return [{ code: "module_move_unavailable", count: 0, message: error instanceof Error ? error.message : String(error) }];
}
function hasConflicts(error: unknown): boolean {
  return error instanceof ApiError && error.status === 422 && !!error.detail && typeof error.detail === "object"
    && "conflicts" in error.detail && Array.isArray(error.detail.conflicts) && error.detail.conflicts.length > 0;
}
export async function confirmModuleFill() {
  const pending = moduleFill.getState().pending;
  if (!pending?.preview || uiStore.getState().state.busy) return;
  const view = await engineCommand(i18n.t("s13c.filling"), () => engine.moduleCommands(pending.projectId, {
    command: "move_modules", module_instance_ids: pending.ids, dx_m: pending.delta[0], dy_m: pending.delta[1],
    on_conflict: "fill", ...moduleDeleteFlags(pending.preview!)
  }));
  if (view) {
    const surviving = new Set(view.bundle.scene.module_instances.map((m) => m.module_instance_id));
    uiStore.getState().dispatch({ type: "select", ids: pending.preview.placed_ids.filter((id) => surviving.has(id)) });
    cancelModuleFill();
  }
}
async function move(ids: readonly string[], d: Vec2, allowFill: boolean) {
  const state = uiStore.getState().state, projectId = state.view?.bundle.project.project_id;
  if (!projectId || state.busy || !ids.length || (!d[0] && !d[1])) return;
  if (readOnlySelection(ids)) return;
  return engineCommand(i18n.t("s13b.moving"), async () => {
    try { return await engine.moduleCommands(projectId, { command: "move_modules", module_instance_ids: [...ids], dx_m: d[0], dy_m: d[1] }); }
    catch (error) {
      const reasons = errorReasons(error);
      if (allowFill && hasConflicts(error)) {
        try {
          const preview = await engine.moduleCommands(projectId, { command: "move_modules", module_instance_ids: [...ids],
            dx_m: d[0], dy_m: d[1], on_conflict: "fill", dry_run: true });
          if ("mode" in preview) moduleFill.setState({ pending: { projectId, ids: [...ids], delta: d, preview, reasons: preview.reasons } });
          else throw new Error(i18n.t("s13c.changed"));
        } catch (fillError) {
          if (fillError instanceof ApiError && fillError.status !== 422) throw fillError;
          moduleFill.setState({ pending: { projectId, ids: [...ids], delta: d, reasons: [...new Map([...errorReasons(fillError), ...reasons].map((reason) => [JSON.stringify(reason), reason])).values()] } });
        }
        return undefined;
      }
      if (error instanceof ApiError && error.status === 422)
        throw new ApiError(reasons.map(moduleReasonText).join("; "), error.status, error.detail);
      throw error;
    }
  });
}
export const moveModules = (ids: readonly string[], d: Vec2) => move(ids, d, false);
export const dragModules = (ids: readonly string[], d: Vec2) => move(ids, d, true);

/** Nudges remain exact; only a drag can offer the fill preview. */
export function useModuleEdits() { return { previewDelete: previewModuleDelete, moveModules, dragModules }; }
