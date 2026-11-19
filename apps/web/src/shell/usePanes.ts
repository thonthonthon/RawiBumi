import { useCallback, useMemo, useRef, useState } from "react";
import { usePanelRef, type PanelSize } from "react-resizable-panels";
import { track } from "../platform/telemetry";

/** Width of a collapsed task panel or inspector: a strip with one expand button. */
export const COLLAPSED_PX = 32;
/** Default widths, used when a pane expands with no remembered size (after a reload). */
export const TASK_PX = 320;
export const INSPECTOR_PX = 290;
const RAIL_KEY = "rawibumi.rail";

/** Pane state is a per-viewer convenience; storage may be unavailable. */
export const safeStorage = {
  getItem: (k: string) => {
    try {
      return window.localStorage.getItem(k);
    } catch {
      return null;
    }
  },
  setItem: (k: string, v: string) => {
    try {
      window.localStorage.setItem(k, v);
    } catch {
      // ignore
    }
  }
};

export interface Panes {
  taskRef: ReturnType<typeof usePanelRef>;
  inspectorRef: ReturnType<typeof usePanelRef>;
  taskCollapsed: boolean;
  inspectorCollapsed: boolean;
  railCompact: boolean;
  /** True when the task panel, the inspector and the rail are all minimised. */
  focused: boolean;
  onTaskResize: (size: PanelSize) => void;
  onInspectorResize: (size: PanelSize) => void;
  toggleTask: () => void;
  toggleInspector: () => void;
  toggleRail: () => void;
  focusStage: () => void;
}

/**
 * Collapse state of the three panes around the stage (F1.1). Panel sizes,
 * including collapsed ones, persist through useDefaultLayout; the rail's
 * compact state persists here.
 */
export function usePanes(): Panes {
  const taskRef = usePanelRef();
  const inspectorRef = usePanelRef();
  const [taskCollapsed, setTaskCollapsed] = useState(false);
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [railCompact, setRailCompactState] = useState(() => safeStorage.getItem(RAIL_KEY) === "compact");

  const setRailCompact = useCallback((compact: boolean) => {
    setRailCompactState(compact);
    safeStorage.setItem(RAIL_KEY, compact ? "compact" : "full");
  }, []);

  // Last open width of each pane in this session. After a reload of a collapsed
  // layout there is none, and the pane opens at its default width, not its minimum.
  const lastPx = useRef<{ task?: number; inspector?: number }>({});
  const open = useCallback(
    (pane: "task" | "inspector") => {
      const p = (pane === "task" ? taskRef : inspectorRef).current;
      p?.resize(`${lastPx.current[pane] ?? (pane === "task" ? TASK_PX : INSPECTOR_PX)}px`);
    },
    [taskRef, inspectorRef]
  );

  const flip = useCallback(
    (pane: "task" | "inspector") => {
      const p = (pane === "task" ? taskRef : inspectorRef).current;
      if (!p) return;
      const collapsing = !p.isCollapsed();
      if (collapsing) p.collapse();
      else open(pane);
      track("pane.toggled", { pane, collapsed: collapsing });
    },
    [taskRef, inspectorRef, open]
  );

  const toggleTask = useCallback(() => flip("task"), [flip]);
  const toggleInspector = useCallback(() => flip("inspector"), [flip]);
  const toggleRail = useCallback(() => {
    setRailCompact(!railCompact);
    track("pane.toggled", { pane: "rail", collapsed: !railCompact });
  }, [railCompact, setRailCompact]);

  const focused = taskCollapsed && inspectorCollapsed && railCompact;
  const focusStage = useCallback(() => {
    const t = taskRef.current;
    const i = inspectorRef.current;
    if (focused) {
      // Widen the rail first: panel sizes are kept as fractions of the group,
      // so opening the panes before the group shrinks would leave them narrower.
      setRailCompact(false);
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          if (t?.isCollapsed()) open("task");
          if (i?.isCollapsed()) open("inspector");
        })
      );
    } else {
      if (t && !t.isCollapsed()) t.collapse();
      if (i && !i.isCollapsed()) i.collapse();
      setRailCompact(true);
    }
    track("pane.focus", { on: !focused });
  }, [focused, taskRef, inspectorRef, setRailCompact, open]);

  const onTaskResize = useCallback((s: PanelSize) => {
    const collapsed = s.inPixels <= COLLAPSED_PX + 1;
    if (!collapsed) lastPx.current.task = s.inPixels;
    setTaskCollapsed(collapsed);
  }, []);
  const onInspectorResize = useCallback((s: PanelSize) => {
    const collapsed = s.inPixels <= COLLAPSED_PX + 1;
    if (!collapsed) lastPx.current.inspector = s.inPixels;
    setInspectorCollapsed(collapsed);
  }, []);

  return useMemo(
    () => ({
      taskRef,
      inspectorRef,
      taskCollapsed,
      inspectorCollapsed,
      railCompact,
      focused,
      onTaskResize,
      onInspectorResize,
      toggleTask,
      toggleInspector,
      toggleRail,
      focusStage
    }),
    [taskRef, inspectorRef, taskCollapsed, inspectorCollapsed, railCompact, focused, onTaskResize, onInspectorResize, toggleTask, toggleInspector, toggleRail, focusStage]
  );
}
