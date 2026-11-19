import { engine } from "../client";
import type { ProjectView, ScenePreview, DependentFieldPreview } from "../types";
import { ApiError, type SceneConflictOptions, type ObstacleConflictDetail } from "../types";
import { create } from "zustand";
import { uiStore } from "./store";
import i18n from "../i18n";

/**
 * Undo and redo across local drafts and engine commands.
 * The UI history records the order; a local step is undone here, an engine step
 * by the engine session, so the engine's data has a single undo.
 */

/** Runs an engine command that changes the project; it becomes one undo step. */
export async function engineCommand(label: string, op: () => Promise<ProjectView | undefined>): Promise<ProjectView | undefined> {
  const { run, dispatch } = uiStore.getState();
  const view = await run(label, op);
  if (view) dispatch({ type: "engineCommitted", view, label });
  return view;
}

interface SceneRefusal {
  detail: Omit<ObstacleConflictDetail, "options"> & { options?: ObstacleConflictDetail["options"] };
  label: string;
  retry: (options: SceneConflictOptions) => Promise<ProjectView>;
}
export const sceneRefusal = create<{ pending: SceneRefusal | null }>(() => ({ pending: null }));
export const cancelSceneRefusal = () => sceneRefusal.setState({ pending: null });

/** Catch scene previews inside run, preserving its normal error and 409 handling. */
export async function sceneEdit(label: string, op: (options: SceneConflictOptions) => Promise<ProjectView>, options: SceneConflictOptions = {}) {
  return engineCommand(label, async () => {
    try { return await op(options); }
    catch (error) {
      if (error instanceof ApiError && error.status === 422 && error.detail && typeof error.detail === "object"
          && "conflicts" in error.detail && Array.isArray(error.detail.conflicts)) {
        sceneRefusal.setState({ pending: { detail: error.detail as SceneRefusal["detail"], label, retry: op } });
        return undefined;
      }
      throw error;
    }
  });
}

export async function confirmSceneRefusal(choice: "remove_modules" | "refill_field") {
  const pending = sceneRefusal.getState().pending;
  const option = pending?.detail.options?.[choice];
  if (!pending || !option || (choice === "refill_field" && "available" in option && !option.available)) return;
  const flags: SceneConflictOptions = { on_module_conflict: choice };
  if (option.string_ids?.length) flags.discard_dependent_strings = true;
  if ("requires_discard_manual_layout" in option && option.requires_discard_manual_layout) flags.discard_manual_layout = true;
  cancelSceneRefusal();
  return sceneEdit(pending.label, pending.retry, flags);
}

interface DependentFieldRequest {
  fields: DependentFieldPreview[];
  message?: string;
  label: string;
  retry: (options: SceneConflictOptions) => Promise<ProjectView | ScenePreview>;
  onCommitted?: () => void;
}
export const dependentFields = create<{ pending: DependentFieldRequest | null }>(() => ({ pending: null }));
export const cancelDependentFields = () => dependentFields.setState({ pending: null });
export const dependentFieldsBlocked = (fields: DependentFieldPreview[]) => !fields.length || fields.some((field) =>
  field.conflicts.length > 0 || (field.action === "refill" && field.module_count_after === 0));

function captureDependentError(error: unknown, request: Omit<DependentFieldRequest, "fields">): boolean {
  if (error instanceof ApiError && error.status === 422 && error.detail && typeof error.detail === "object"
      && "dependent_fields" in error.detail && Array.isArray(error.detail.dependent_fields)) {
    dependentFields.setState({ pending: { ...request, fields: error.detail.dependent_fields,
      message: "message" in error.detail && typeof error.detail.message === "string" ? error.detail.message : error.message } });
    return true;
  }
  return false;
}

/** The preview is read-only; the original request is retained for explicit confirmation. */
export async function dependentSceneEdit(label: string, retry: DependentFieldRequest["retry"], onCommitted?: () => void) {
  const request = { label, retry, onCommitted };
  const preview = await uiStore.getState().run(label, async () => {
    try { return await retry({ dependent_fields: "apply", dry_run: true }); }
    catch (error) { if (captureDependentError(error, request)) return; throw error; }
  });
  if (preview && "dry_run" in preview) dependentFields.setState({ pending: { ...request, fields: preview.dependent_fields ?? [] } });
}

export async function confirmDependentFields() {
  const pending = dependentFields.getState().pending;
  if (!pending || dependentFieldsBlocked(pending.fields) || uiStore.getState().state.busy) return;
  const flags: SceneConflictOptions = { dependent_fields: "apply" };
  if (pending.fields.some((field) => field.requires_discard_dependent_strings)) flags.discard_dependent_strings = true;
  if (pending.fields.some((field) => field.requires_discard_manual_layout)) flags.discard_manual_layout = true;
  cancelDependentFields();
  const view = await engineCommand(pending.label, async () => {
    try {
      const result = await pending.retry(flags);
      if ("dry_run" in result) throw new Error("Expected the committed project view.");
      return result;
    } catch (error) { if (captureDependentError(error, pending)) return; throw error; }
  });
  if (view) pending.onCommitted?.();
  return view;
}

// UXF2 (U2-22): an undo or redo pressed while a save runs (a PV roof re-fill takes seconds) is queued and runs as soon as
// the save finishes, in order. Before, the press was silently dropped.
const queued: Array<() => Promise<void>> = [];
let draining = false;
function queueWhileBusy(action: () => Promise<void>, notice: string): boolean {
  const { state, toast } = uiStore.getState();
  if (!state.busy) return false;
  // S17: a second press while an undo or redo itself runs is ignored, so one press never becomes two steps.
  if (/^(Undoing|Redoing) /.test(state.busy)) return true;
  watchSaves();
  queued.push(action);
  toast("info", i18n.t(notice));
  return true;
}
async function drain() {
  draining = true;
  try {
    while (queued.length && !uiStore.getState().state.busy) await queued.shift()!();
  } finally {
    draining = false;
  }
}
let watching = false;
function watchSaves() {
  // Subscribed on the first queued press, not at import (tests mock the store without subscribe).
  if (watching) return;
  watching = true;
  uiStore.subscribe((now, before) => {
    if (before.state.busy && !now.state.busy && queued.length && !draining) void drain();
  });
}

export async function undo(): Promise<void> {
  const { state, dispatch, run } = uiStore.getState();
  if (queueWhileBusy(undo, "history.undoQueued")) return;
  const top = state.past[state.past.length - 1];
  if (!top) return;
  if (top.kind === "local") return dispatch({ type: "undo" });
  const id = state.view?.bundle.project.project_id;
  if (!id) return;
  const view = await run(`Undoing ${top.label.toLowerCase()}`, () => engine.undo(id, { expected_project_revision_id: state.view!.bundle.project.project_revision.project_revision_id, expected_entry_id: top.entryId ?? "demo" }));
  if (view) dispatch({ type: "engineUndone", view });
}

export async function redo(): Promise<void> {
  const { state, dispatch, run } = uiStore.getState();
  if (queueWhileBusy(redo, "history.redoQueued")) return;
  const next = state.future[0];
  if (!next) return;
  if (next.kind === "local") return dispatch({ type: "redo" });
  const id = state.view?.bundle.project.project_id;
  if (!id) return;
  const view = await run(`Redoing ${next.label.toLowerCase()}`, () => engine.redo(id, { expected_project_revision_id: state.view!.bundle.project.project_revision.project_revision_id, expected_entry_id: next.entryId ?? "demo" }));
  if (view) dispatch({ type: "engineRedone", view });
}
