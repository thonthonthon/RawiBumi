import type { Tool } from "../state/store";

/**
 * The plan tools, in one table (DESIGN.md §5, UI spec "Tools and shortcuts").
 * The scene panel's tool list, the plan's keys and the shortcut sheet all read it.
 */
export interface ToolDef {
  tool: Tool;
  /** Single key, lower case, as typed. */
  key: string;
  /** i18n keys under `tools.` */
  label: string;
  note: string;
  /** Pending endpoint id when the tool's result is a local draft; null when it reaches the engine. */
  pending: string | null;
  /** What typed input means while the tool is active. */
  typed: "point" | "angle" | null;
}

export const TOOLS: readonly ToolDef[] = [
  { tool: "select", key: "v", label: "tools.select", note: "tools.selectNote", pending: null, typed: null },
  { tool: "move", key: "m", label: "tools.move", note: "tools.moveNote", pending: null, typed: "point" },
  { tool: "rotate", key: "r", label: "tools.rotate", note: "tools.rotateNote", pending: null, typed: "angle" },
  { tool: "rect_engine", key: "b", label: "tools.building", note: "tools.buildingNote", pending: null, typed: "point" },
  { tool: "polygon", key: "p", label: "tools.polygon", note: "tools.polygonNote", pending: null, typed: "point" },
  { tool: "hole", key: "h", label: "tools.hole", note: "tools.holeNote", pending: null, typed: "point" },
  { tool: "box_obstacle", key: "o", label: "tools.boxObstacle", note: "tools.boxObstacleNote", pending: null, typed: "point" },
  { tool: "obstacle", key: "e", label: "tools.extrusion", note: "tools.extrusionNote", pending: null, typed: "point" },
  { tool: "keepout", key: "k", label: "tools.keepout", note: "tools.keepoutNote", pending: null, typed: "point" },
  { tool: "measure", key: "d", label: "tools.measure", note: "tools.measureNote", pending: null, typed: "point" }
];

/**
 * Electrical step tools (B6). Geometry is read-only in this step; every tool is an
 * engine topology command (proposal 0004), so `pending` names that route.
 */
export const ELECTRICAL_TOOLS: readonly ToolDef[] = [
  { tool: "select", key: "v", label: "tools.select", note: "tools.selectNote", pending: null, typed: null },
  { tool: "string_path", key: "s", label: "tools.stringPath", note: "tools.stringPathNote", pending: null, typed: null },
  { tool: "assign", key: "a", label: "tools.assign", note: "tools.assignNote", pending: null, typed: null },
  { tool: "lasso", key: "l", label: "tools.lasso", note: "tools.lassoNote", pending: null, typed: null },
  { tool: "split", key: "x", label: "tools.split", note: "tools.splitNote", pending: null, typed: null },
  { tool: "join", key: "j", label: "tools.join", note: "tools.joinNote", pending: null, typed: null },
  { tool: "reverse", key: "r", label: "tools.reverse", note: "tools.reverseNote", pending: null, typed: null },
  { tool: "move_module", key: "m", label: "tools.moveModule", note: "tools.moveModuleNote", pending: null, typed: null },
  { tool: "swap_modules", key: "w", label: "tools.swapModules", note: "tools.swapModulesNote", pending: null, typed: null }
];

export const ELECTRICAL_TOOL_SET: ReadonlySet<Tool> = new Set(ELECTRICAL_TOOLS.filter((t) => t.tool !== "select").map((t) => t.tool));

/** The tools of a step: the electrical step has its own; every other step uses the scene tools. */
export const toolsForStep = (step: string): readonly ToolDef[] => (step === "electrical" ? ELECTRICAL_TOOLS : TOOLS);
export const toolByKey = (step: string, key: string): Tool | undefined => toolsForStep(step).find((t) => t.key === key)?.tool;

export const TOOL_BY_KEY: ReadonlyMap<string, Tool> = new Map(TOOLS.map((t) => [t.key, t.tool]));
export const toolDef = (tool: Tool): ToolDef => TOOLS.find((t) => t.tool === tool) ?? ELECTRICAL_TOOLS.find((t) => t.tool === tool) ?? TOOLS[0];

/** Polygon tools: click vertices, close on the first vertex, Enter or double-click. */
export const DRAW_TOOLS: ReadonlySet<Tool> = new Set<Tool>(["polygon", "obstacle", "keepout", "hole"]);
/** Two-corner rectangle tools, created directly in the engine. */
export const RECT_TOOLS: ReadonlySet<Tool> = new Set<Tool>(["rect_engine", "box_obstacle"]);

/** Plan keys besides the tool keys, for the shortcut sheet. */
export const PLAN_KEYS: ReadonlyArray<[keys: string, label: string]> = [
  ["z", "shortcuts.zoom"],
  ["Enter", "shortcuts.finish"],
  ["Escape", "shortcuts.cancel"],
  ["Delete", "shortcuts.deleteSel"],
  ["ArrowUp", "shortcuts.nudge"],
  ["Shift+ArrowUp", "shortcuts.nudgeLarge"],
  ["Alt", "shortcuts.noSnap"],
  ["Shift", "shortcuts.angle15"],
  ["Delete", "shortcuts.deleteModules"],
  ["Shift+Delete", "shortcuts.deleteTables"],
  ["ArrowRight", "shortcuts.moveTables"],
  ["Shift+F10", "shortcuts.contextMenu"],
  ["ContextMenu", "shortcuts.contextMenu"],
  ["Delete", "shortcuts.deleteVertex"],
  ["$mod+c", "shortcuts.copy"],
  ["$mod+v", "shortcuts.paste"],
];

/** Electrical step keys besides its tool keys (B6), for the shortcut sheet. */
export const ELECTRICAL_KEYS: ReadonlyArray<[keys: string, label: string]> = [
  ["[", "shortcuts.targetPrev"],
  ["]", "shortcuts.targetNext"],
  ["1", "shortcuts.targetN"],
  ["Enter", "shortcuts.pathCreate"],
  ["Backspace", "shortcuts.pathBack"],
  ["Delete", "shortcuts.moduleUnstring"],
  ["Escape", "shortcuts.gestureCancel"]
];

/** Arrow-key nudge steps, metres (UI spec: 0.10 m, Shift 1.00 m). */
export const NUDGE_M = 0.1;
export const NUDGE_LARGE_M = 1;
