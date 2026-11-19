import { VIEW_PRESETS, selectedRoof } from "../canvas/viewPresets";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { tinykeys } from "tinykeys";
import { engine } from "../client";
import { LANGUAGES, setLanguage } from "../i18n";
import { railSteps } from "../modules/registry";
import { track } from "../platform/telemetry";
import { useActions, useUI } from "../state/store";
import type { Panes } from "../shell/usePanes";
import { dialogTarget, typingTarget } from "./keys";
import { redo, undo } from "../state/history";

export type CommandGroup = "navigate" | "project" | "view" | "preferences";

export interface Command {
  id: string;
  group: CommandGroup;
  label: string;
  /** tinykeys key string; shown in the palette and the shortcut sheet. */
  keys?: string;
  alternativeKeys?: string[];
  disabled?: boolean;
  run: () => void;
}

interface Options {
  onClose: () => void;
  openPalette: () => void;
  openShortcuts: () => void;
  /** Pane controls; null on full-page steps (results, export), which have no side panes. */
  panes: Panes | null;
}

/** Every workspace command, in one list: the palette, shortcuts and the sheet all read it. */
export function useCommands({ onClose, openPalette, openShortcuts, panes }: Options): Command[] {
  const { t, i18n } = useTranslation();
  const { dispatch, run, toast } = useActions();
  const state = useUI((s) => ({ roof: !!selectedRoof(s.entities, s.selection), projectId: s.view?.bundle.project.project_id, busy: s.busy, canUndo: s.past.length > 0, canRedo: s.future.length > 0 }));
  const projectId = state.projectId;

  return useMemo(() => {
    const steps: Command[] = railSteps().map((s) => ({
      id: `step.${s.id}`,
      group: "navigate",
      label: t("commands.goTo", { step: t(s.labelKey) }),
      keys: s.shortcut ? `Alt+${s.shortcut}` : undefined,
      run: () => {
        dispatch({ type: "setStep", step: s.id });
        track("step.viewed", { step: s.id });
      }
    }));
    const project: Command[] = [
      {
        id: "project.save",
        group: "project",
        label: t("commands.save"),
        keys: "$mod+s",
        disabled: !projectId || !!state.busy,
        run: () => {
          if (!projectId) return;
          void run(t("header.saving"), () => engine.save(projectId)).then((r) => r && toast("ok", t("header.saved", { rev: r.project_revision_id })));
        }
      },
      { id: "project.undo", group: "project", label: t("commands.undo"), keys: "$mod+z", disabled: !state.canUndo && !state.busy, run: () => void undo() },
      { id: "project.redo", group: "project", label: t("commands.redo"), keys: "$mod+Shift+z", alternativeKeys: ["$mod+y"], disabled: !state.canRedo || !!state.busy, run: () => void redo() },
      { id: "project.close", group: "project", label: t("commands.closeProject"), disabled: !!state.busy, run: onClose }
    ];
    const view: Command[] = [
      ...VIEW_PRESETS.map(p => ({
        id: `view.${p.id}`, group: "view" as const, label: t(`stage.${p.label}`),
        keys: "keys" in p ? p.keys : undefined, disabled: p.id === "face" && !state.roof,
        run: () => dispatch({ type: "setCanvasView", view: p.id })
      })),
      { id: "view.sld", group: "view", label: t("commands.viewSld"), run: () => dispatch({ type: "setCanvasView", view: "sld" }) },
      {
        id: "view.toggleTask",
        group: "view",
        label: t("commands.toggleTask"),
        keys: "Alt+BracketLeft",
        disabled: !panes,
        run: () => panes?.toggleTask()
      },
      {
        id: "view.toggleInspector",
        group: "view",
        label: t("commands.toggleInspector"),
        keys: "Alt+BracketRight",
        disabled: !panes,
        run: () => panes?.toggleInspector()
      },
      {
        id: "view.focusStage",
        group: "view",
        label: panes?.focused ? t("commands.restorePanes") : t("commands.focusStage"),
        keys: "Alt+Backslash",
        disabled: !panes,
        run: () => panes?.focusStage()
      },
      { id: "view.toggleRail", group: "view", label: t("commands.toggleRail"), run: () => panes?.toggleRail(), disabled: !panes },
      { id: "view.palette", group: "view", label: t("commands.palette"), keys: "$mod+k", run: openPalette },
      { id: "view.shortcuts", group: "view", label: t("commands.shortcuts"), keys: "Shift+?", run: openShortcuts }
    ];
    const prefs: Command[] = LANGUAGES.filter((l) => l !== i18n.language).map((l) => ({
      id: `pref.lang.${l}`,
      group: "preferences" as const,
      label: t("commands.language", { lang: t(`language.${l}`) }),
      run: () => setLanguage(l)
    }));
    return [...steps, ...project, ...view, ...prefs];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t, i18n.language, state.roof, projectId, state.busy, state.canUndo, state.canRedo, onClose, openPalette, openShortcuts, panes]);
}

/** Global commands also work in 3D, SLD and results; text inputs keep native undo. */
export function useShortcuts(commands: Command[]): void {
  useEffect(() => {
    const map: Record<string, (e: KeyboardEvent) => void> = {};
    for (const c of commands) {
      if (!c.keys) continue;
      for (const keys of [c.keys, ...(c.alternativeKeys ?? [])]) map[keys] = (e) => {
        if (dialogTarget(e.target) || (typingTarget(e.target) && ["project.undo", "project.redo"].includes(c.id))) return;
        e.preventDefault();
        if (c.disabled) return;
        c.run();
        track("command.run", { id: c.id, via: "keys" });
      };
    }
    return tinykeys(window, map, {
      ignore: (e) => dialogTarget(e.target) || (typingTarget(e.target) && !(e.ctrlKey || e.metaKey || e.altKey))
    });
  }, [commands]);
}
