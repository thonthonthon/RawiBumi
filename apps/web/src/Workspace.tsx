import { ViewControls } from "./canvas/ViewControls";
import i18n from "./i18n";
import { useCallback, useEffect, useState } from "react";
import { useImagery } from "./imagery/useImagery";
import { ProviderDialogHost } from "./imagery/ProviderDialog";
import { useTranslation } from "react-i18next";
import { Group, Panel, Separator, useDefaultLayout } from "react-resizable-panels";
import { PlanCanvas } from "./canvas/PlanCanvas";
import { StringTable } from "./electrical/StringTable";
import { View3D } from "./canvas/View3D";
import { DEMO } from "./client";
import { CommandPalette, Keys } from "./commands/CommandPalette";
import { keyParts } from "./commands/keys";
import { ShortcutSheet } from "./commands/ShortcutSheet";
import { useCommands, useShortcuts } from "./commands/useCommands";
import { Sld } from "./electrical/Sld";
import { Inspector } from "./Inspector";
import { DeleteDialog, ImportHub } from "./Modals";
import { stepDef } from "./modules/registry";
import { Brand } from "./shell/Brand";
import { Pane } from "./shell/Pane";
import { Rail } from "./shell/Rail";
import { StatusBar } from "./shell/StatusBar";
import { COLLAPSED_PX, INSPECTOR_PX, safeStorage, TASK_PX, usePanes } from "./shell/usePanes";
import { GRID_KEY, useActions, useUI } from "./state/store";
import { FocusOff, FocusOn } from "./ui/icons";
import { redo, undo } from "./state/history";

export function Workspace({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const { dispatch } = useActions();
  const state = useUI((s) => ({
    view: s.view,
    step: s.step,
    canvasView: s.canvasView,
    topToolNote: s.topToolNote,
    showGrid: s.showGrid,
    busy: s.busy,
    canUndo: s.past.length > 0,
    canRedo: s.future.length > 0
  }));
  const [importOpen, setImportOpen] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const v = state.view!;
  const step = stepDef(state.step);
  const full = step?.layout === "full";

  const openPalette = useCallback(() => setPaletteOpen(true), []);
  const openShortcuts = useCallback(() => setSheetOpen(true), []);
  const panes = usePanes();
  const commands = useCommands({ onClose, openPalette, openShortcuts, panes: full ? null : panes });
  useShortcuts(commands);
  const ctx = { openImport: (c: string) => setImportOpen(c) };
  const { imagery: stageImagery } = useImagery();

  // UX2 "Properties": show the Inspector and move focus into it.
  useEffect(() => {
    const show = () => {
      if (full) return;
      if (panes.inspectorCollapsed) panes.toggleInspector();
      requestAnimationFrame(() => document.querySelector<HTMLElement>(".inspectorpane .inspector input, .inspectorpane .inspector button, .inspectorpane .inspector select")?.focus());
    };
    window.addEventListener("rawibumi:show-inspector", show);
    return () => window.removeEventListener("rawibumi:show-inspector", show);
  }, [full, panes]);
  const layout = useDefaultLayout({ id: "rawibumi.workspace", storage: safeStorage, panelIds: ["task", "stage", "inspector"] });

  const canvas = (
    <div className="stage__canvas">
      {state.canvasView === "plan" && <PlanCanvas />}
      {state.canvasView === "sld" && <Sld />}
      {state.canvasView !== "plan" && state.canvasView !== "sld" && <View3D key={state.canvasView} preset={state.canvasView} onCameraFrame={frame => dispatch({ type: "setCameraFrame", frame })} />}
    </div>
  );
  const stage = (
    <main className="stage" id="main-content" tabIndex={-1} aria-label={t("stage.views")}>
      <div className="stage__bar">
        <ViewControls />
        <button type="button" className="btn btn--sm btn--stage" aria-pressed={state.canvasView === "sld"}
          onClick={() => dispatch({ type: "setCanvasView", view: "sld" })}>{t("stage.sld")}</button>
        <span className="stage__mode">
          {state.step === "electrical"
            ? t("stage.modeElectrical")
            : stageImagery.overlay
              ? t("stage.modeImage")
              : stageImagery.satellite
                ? t("stage.modeTiles")
                : t("stage.modeBlank")}
        </span>
        <span className="stage__spacer" />
        {state.canvasView === "plan" && (
          <button
            type="button"
            className="btn btn--sm btn--stage"
            aria-pressed={state.showGrid}
            data-grid-toggle
            onClick={() => {
              const show = !state.showGrid;
              dispatch({ type: "setShowGrid", show });
              try { window.localStorage.setItem(GRID_KEY, show ? "1" : "0"); } catch { /* not remembered; still toggles */ }
            }}
          >
            {t("stage.grid")}
          </button>
        )}
        <button
          type="button"
          className="btn btn--sm btn--stage"
          aria-pressed={panes.focused}
          onClick={panes.focusStage}
          title={`${t("panes.focus")} · ${keyParts("Alt+Backslash").join("+")}`}
        >
          {panes.focused ? <FocusOff /> : <FocusOn />}
          {t("panes.focus")}
        </button>
      </div>
      {state.topToolNote && state.canvasView !== "plan" && <p role="status">{t("stage.topToolNote")}</p>}
      {state.step === "electrical" && state.view ? (
        // Electrical step (B6): the string table under the canvas, resizable.
        <Group orientation="vertical" className="stage__split">
          <Panel id="canvas" minSize="160px">
            {canvas}
          </Panel>
          <Separator className="splitter splitter--h" />
          <Panel id="strings" defaultSize="28%" minSize="72px" collapsible>
            <StringTable />
          </Panel>
        </Group>
      ) : (
        canvas
      )}
    </main>
  );

  return (
    <div className="ws">
      <header className="topbar">
        <Brand />
        <span className="topbar__divider" aria-hidden="true" />
        <span className="topbar__project">{v.bundle.project.name}</span>
        <span className="topbar__meta">
          {t("header.revision", { n: v.bundle.project.project_revision.revision_number })} · {v.bundle.project.site.timezone}
        </span>
        {DEMO && (
          <span className="demo-flag" title={t("app.demoEngineTitle")}>
            {t("app.demoEngine")}
          </span>
        )}
        <span className="topbar__spacer" />
        <a className="btn btn--sm btn--quiet" href={i18n.language === "id" ? "/manual/id.html" : "/manual/index.html"} target="_blank" rel="noopener">{t("header.manual")}</a>
        <button type="button" className="btn btn--sm btn--quiet" onClick={() => void undo()} disabled={!state.canUndo && !state.busy}>
          {t("header.undo")}
        </button>
        <button type="button" className="btn btn--sm btn--quiet" onClick={() => void redo()} disabled={!state.canRedo || !!state.busy}>
          {t("header.redo")}
        </button>
        <button type="button" className="btn btn--sm btn--quiet" onClick={openPalette}>
          {t("header.commands")} <Keys keys="$mod+k" />
        </button>
        <button type="button" className="btn btn--sm btn--quiet" onClick={onClose} disabled={!!state.busy}>
          {t("header.projects")}
        </button>
        <button
          type="button"
          className="btn btn--sm btn--primary"
          disabled={!!state.busy}
          onClick={() => commands.find((c) => c.id === "project.save")?.run()}
        >
          {t("header.save")}
        </button>
      </header>

      <div className="ws__body">
        <Rail compact={panes.railCompact} onToggleCompact={panes.toggleRail} />
        {full ? (
          <main className="fullview" id="main-content" tabIndex={-1}>{step?.render(ctx)}</main>
        ) : (
          <Group orientation="horizontal" className="ws__panels" defaultLayout={layout.defaultLayout} onLayoutChanged={layout.onLayoutChanged}>
            <Panel
              id="task"
              panelRef={panes.taskRef}
              defaultSize={`${TASK_PX}px`}
              minSize="260px"
              maxSize="480px"
              collapsible
              collapsedSize={`${COLLAPSED_PX}px`}
              onResize={panes.onTaskResize}
              className="taskpanel"
            >
              <Pane title={step ? t(step.labelKey) : ""} side="left" collapsed={panes.taskCollapsed} onToggle={panes.toggleTask} keys="Alt+BracketLeft">
                {step?.render(ctx)}
              </Pane>
            </Panel>
            <Separator className="splitter" />
            <Panel id="stage" minSize="360px">
              {stage}
            </Panel>
            <Separator className="splitter" />
            <Panel
              id="inspector"
              panelRef={panes.inspectorRef}
              defaultSize={`${INSPECTOR_PX}px`}
              minSize="240px"
              maxSize="440px"
              collapsible
              collapsedSize={`${COLLAPSED_PX}px`}
              onResize={panes.onInspectorResize}
              className="inspectorpane"
            >
              <Pane title={t("panes.inspector")} side="right" collapsed={panes.inspectorCollapsed} onToggle={panes.toggleInspector} keys="Alt+BracketRight">
                <Inspector />
              </Pane>
            </Panel>
          </Group>
        )}
      </div>

      <StatusBar />
      <ProviderDialogHost />

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} commands={commands} />
      <ShortcutSheet open={sheetOpen} onClose={() => setSheetOpen(false)} commands={commands} />
      {importOpen && <ImportHub initial={importOpen} onClose={() => setImportOpen(null)} />}
      <DeleteDialog />
    </div>
  );
}
