import { bounds, type Vec2 } from "../geometry";
import type { Entity } from "../state/store";

/**
 * UX3: the plan clipboard for this page session. It refers to its source object (not a snapshot), within one
 * project (user decision 2026-11-08); a paste copies the source as it is at paste time.
 */
export interface PlanClipboard { projectId: string; entityId: string; name: string; centre: Vec2; width: number }

let clipboard: PlanClipboard | null = null;

export function copyToClipboard(projectId: string, e: Entity): PlanClipboard {
  const b = bounds([e.polygon]);
  clipboard = { projectId, entityId: e.id, name: e.name, centre: [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2], width: b.maxX - b.minX };
  return clipboard;
}
export const readClipboard = () => clipboard;
export const clearClipboard = () => { clipboard = null; };

/** Why a paste can't run now (an i18n key), or null. */
export function pasteProblem(clip: PlanClipboard | null, projectId: string | null | undefined, entities: readonly Entity[]): string | null {
  if (!clip) return "ux3.clipboardEmpty";
  if (clip.projectId !== projectId) return "ux3.otherProject";
  if (!entities.some((e) => e.id === clip.entityId)) return "ux3.sourceGone";
  return null;
}

/** Offset of the paste: the copy's centre onto `target` (pointer or right-click point), else beside the original. */
export function pasteOffset(clip: PlanClipboard, target: Vec2 | null): Vec2 {
  return target ? [target[0] - clip.centre[0], target[1] - clip.centre[1]] : [clip.width + 1, 0];
}
