import { worstCheck, type LiveCheck } from "../engine/topology";
import type { ProjectView } from "../types";
import { symbol, terminalAt, type SymbolId } from "./symbols";

/**
 * SLD layout from the assignment (plan B7: generated, never drawn by hand; ADR 0015).
 * A pure function of the engine's topology: strings → MPPT inputs → inverter → AC busbar
 * → grid, with the load on the busbar. Only what the design model holds is drawn; breakers,
 * isolators, fuses, SPDs, meters and transformers wait for the full SLD.
 *
 * Coordinates are SVG user units (1 unit = 1 px at 100 %), y down.
 */

export type SldNodeKind = "string" | "strings" | "mppt" | "inverter" | "bus" | "grid" | "load";

export interface SldNode {
  id: string;
  kind: SldNodeKind;
  symbol: SymbolId;
  x: number;
  y: number;
  /** Busbar only: scale along y so its terminals reach the taps. */
  stretch: number;
  /** Lettering, one entry per line, in osifont. */
  label: string[];
  labelSide: "left" | "above" | "right";
  /** The plan objects this node stands for; clicking the node selects them. */
  moduleIds: string[];
  /** Strings this node stands for (string, group, MPPT, inverter). */
  stringIds: string[];
  worst: LiveCheck["state"] | null;
  /** Drawn muted: an MPPT with no strings, or a string with no MPPT. */
  muted: boolean;
}

export interface SldEnd {
  node: string;
  /** A symbol terminal, or "tap" for a connection along the busbar. */
  terminal: string;
}

export interface SldWire {
  id: string;
  from: SldEnd;
  to: SldEnd;
  points: [number, number][];
}

export interface SldLayout {
  nodes: SldNode[];
  wires: SldWire[];
  width: number;
  height: number;
}

export const SLD = {
  row: 52,
  blockGap: 32,
  top: 56,
  /** Strings per MPPT drawn one by one; more are drawn as one group node. */
  groupAbove: 4,
  /** Unassigned strings drawn one by one; more are drawn as one group node. */
  unassignedAbove: 12,
  x: { string: 120, mppt: 270, inverter: 470, bus: 610, grid: 710 }
} as const;

const dedupe = (pts: [number, number][]) => pts.filter((p, i) => i === 0 || p[0] !== pts[i - 1][0] || p[1] !== pts[i - 1][1]);

function worstOf(states: (LiveCheck["state"] | null)[]): LiveCheck["state"] | null {
  for (const s of ["fail", "warn", "unavailable", "pass"] as const) if (states.includes(s)) return s;
  return null;
}

/** Lettering goes through i18n (i18next `t`); tests pass a stub. */
export type Translate = (key: string, opts?: Record<string, unknown>) => string;

export function layoutSld(view: ProjectView, t: Translate): SldLayout {
  const design = view.bundle.electrical_design;
  const strings = new Map(design.strings.map((s) => [s.string_id, s]));
  const checks = new Map((view.topology_checks?.strings ?? []).map((c) => [c.string_id, c]));
  const worstOfString = (id: string) => (checks.has(id) ? worstCheck(checks.get(id)!.checks) : null);
  const modulesOf = (ids: string[]) => ids.flatMap((id) => strings.get(id)?.module_instance_ids ?? []);
  const nodes: SldNode[] = [];
  const wires: SldWire[] = [];
  const X = SLD.x;
  let y: number = SLD.top;

  const stringNode = (id: string, kind: "string", nodeId: string, at: number, muted: boolean): SldNode => {
    const s = strings.get(id);
    const n = s?.module_instance_ids.length ?? 0;
    const c = checks.get(id);
    return {
      id: nodeId,
      kind,
      symbol: "pv-string",
      x: X.string,
      y: at,
      stretch: 1,
      label: [t("sld.stringLabel", { id, count: n }), ...(c?.vmp_v != null ? [t("sld.vmp", { v: c.vmp_v.toFixed(0) })] : [])],
      labelSide: "left",
      moduleIds: s?.module_instance_ids ?? [],
      stringIds: [id],
      worst: worstOfString(id),
      muted
    };
  };
  const groupNode = (ids: string[], nodeId: string, at: number, muted: boolean): SldNode => {
    const lens = [...new Set(ids.map((id) => strings.get(id)?.module_instance_ids.length ?? 0))].sort((a, b) => a - b);
    return {
      id: nodeId,
      kind: "strings",
      symbol: "pv-string",
      x: X.string,
      y: at,
      stretch: 1,
      label: [t("sld.group", { count: ids.length, first: ids[0], last: ids[ids.length - 1] }), t("sld.groupLengths", { lengths: lens.join(", ") })],
      labelSide: "left",
      moduleIds: modulesOf(ids),
      stringIds: ids,
      worst: worstOf(ids.map(worstOfString)),
      muted
    };
  };
  const wire = (id: string, from: SldEnd, to: SldEnd, a: [number, number], b: [number, number], elbowX: number) =>
    wires.push({ id, from, to, points: dedupe([a, [elbowX, a[1]], [elbowX, b[1]], b]) });

  const inverterYs: { id: string; y: number }[] = [];
  for (const inv of view.topology_view.inverters) {
    const def = view.catalog.inverters.find((d) => d.revision_id === inv.inverter_definition_revision_id);
    const invStrings = inv.mppts.flatMap((m) => m.strings.map((s) => s.string_id));
    const mpptYs: number[] = [];
    for (const m of inv.mppts) {
      const ids = m.strings.map((s) => s.string_id);
      const rows = ids.length > SLD.groupAbove ? 1 : Math.max(1, ids.length);
      const rowYs = Array.from({ length: rows }, (_, r) => y + r * SLD.row + SLD.row / 2);
      const my = (rowYs[0] + rowYs[rowYs.length - 1]) / 2;
      mpptYs.push(my);
      const mpptId = `mppt:${m.mppt_instance_id}`;
      nodes.push({
        id: mpptId,
        kind: "mppt",
        symbol: "mppt-input",
        x: X.mppt,
        y: my,
        stretch: 1,
        label: [t("sld.mppt", { n: m.index })],
        labelSide: "above",
        moduleIds: modulesOf(ids),
        stringIds: ids,
        worst: worstOf(ids.map(worstOfString)),
        muted: ids.length === 0
      });
      const sources: SldNode[] = ids.length > SLD.groupAbove ? [groupNode(ids, `grp:${m.mppt_instance_id}`, rowYs[0], false)] : ids.map((id, r) => stringNode(id, "string", `str:${id}`, rowYs[r], false));
      for (const s of sources) {
        nodes.push(s);
        wire(`w:${s.id}`, { node: s.id, terminal: "out" }, { node: mpptId, terminal: "in" }, terminalAt("pv-string", "out", s.x, s.y), terminalAt("mppt-input", "in", X.mppt, my), X.mppt - 40);
      }
      y += rows * SLD.row;
    }
    const iy = mpptYs.length ? (mpptYs[0] + mpptYs[mpptYs.length - 1]) / 2 : y + SLD.row / 2;
    if (!mpptYs.length) y += SLD.row;
    const invId = `inv:${inv.inverter_instance_id}`;
    nodes.push({
      id: invId,
      kind: "inverter",
      symbol: "inverter",
      x: X.inverter,
      y: iy,
      stretch: 1,
      label: [inv.name, ...(def ? [t("sld.inverterModel", { model: def.model, kw: (def.nominal_ac_power_w / 1000).toFixed(0) })] : [])],
      labelSide: "above",
      moduleIds: modulesOf(invStrings),
      stringIds: invStrings,
      worst: worstOf(invStrings.map(worstOfString)),
      muted: invStrings.length === 0
    });
    inv.mppts.forEach((m, i) =>
      wire(`w:mppt:${m.mppt_instance_id}`, { node: `mppt:${m.mppt_instance_id}`, terminal: "out" }, { node: invId, terminal: "in" }, terminalAt("mppt-input", "out", X.mppt, mpptYs[i]), terminalAt("inverter", "in", X.inverter, iy), X.inverter - 50)
    );
    inverterYs.push({ id: invId, y: iy });
    y += SLD.blockGap;
  }

  // AC side: busbar, grid above the first inverter, load below the last.
  if (inverterYs.length) {
    const busTop = inverterYs[0].y - SLD.row;
    const busBottom = inverterYs[inverterYs.length - 1].y + SLD.row;
    const nominal = symbol("busbar").terminals.bottom[1] - symbol("busbar").terminals.top[1];
    const busY = (busTop + busBottom) / 2;
    nodes.push({ id: "bus", kind: "bus", symbol: "busbar", x: X.bus, y: busY, stretch: (busBottom - busTop) / nominal, label: [t("sld.bus")], labelSide: "right", moduleIds: [], stringIds: [], worst: null, muted: false });
    for (const inv of inverterYs)
      wire(`w:${inv.id}`, { node: inv.id, terminal: "out" }, { node: "bus", terminal: "tap" }, terminalAt("inverter", "out", X.inverter, inv.y), [X.bus, inv.y], X.bus);
    nodes.push({ id: "grid", kind: "grid", symbol: "grid", x: X.grid, y: busTop, stretch: 1, label: [t("sld.grid")], labelSide: "right", moduleIds: [], stringIds: [], worst: null, muted: false });
    wire("w:grid", { node: "bus", terminal: "tap" }, { node: "grid", terminal: "in" }, [X.bus, busTop], terminalAt("grid", "in", X.grid, busTop), X.bus);
    nodes.push({ id: "load", kind: "load", symbol: "load", x: X.grid, y: busBottom, stretch: 1, label: [t("sld.load")], labelSide: "right", moduleIds: [], stringIds: [], worst: null, muted: false });
    wire("w:load", { node: "bus", terminal: "tap" }, { node: "load", terminal: "in" }, [X.bus, busBottom], terminalAt("load", "in", X.grid, busBottom), X.bus);
    y = Math.max(y, busBottom + SLD.row);
  }

  // Strings with no MPPT: drawn below, muted and unconnected.
  const unassigned = view.topology_view.unassigned_strings.map((s) => s.string_id);
  if (unassigned.length) {
    y += SLD.row / 2;
    if (unassigned.length > SLD.unassignedAbove) {
      nodes.push(groupNode(unassigned, "ungrp", y + SLD.row / 2, true));
      y += SLD.row;
    } else
      for (const id of unassigned) {
        nodes.push(stringNode(id, "string", `un:${id}`, y + SLD.row / 2, true));
        y += SLD.row;
      }
  }

  return { nodes, wires, width: X.grid + 120, height: y + SLD.row / 2 };
}

/** Where a wire end should be: the terminal of its node, or a point on the busbar for a tap. */
export function endPoint(layout: SldLayout, end: SldEnd): [number, number] | { x: number; yMin: number; yMax: number } {
  const n = layout.nodes.find((x) => x.id === end.node);
  if (!n) throw new Error(`Wire end on missing node ${end.node}.`);
  if (end.terminal === "tap") {
    const t = symbol(n.symbol).terminals;
    return { x: n.x, yMin: n.y + t.top[1] * n.stretch, yMax: n.y + t.bottom[1] * n.stretch };
  }
  return terminalAt(n.symbol, end.terminal, n.x, n.y, n.stretch);
}

/** SLD nodes whose plan objects are all selected (`full`) or some selected (`partial`). */
export function selectionState(layout: SldLayout, selection: readonly string[]): Map<string, "full" | "partial"> {
  const sel = new Set(selection);
  const out = new Map<string, "full" | "partial">();
  if (!sel.size) return out;
  for (const n of layout.nodes) {
    if (!n.moduleIds.length) continue;
    let hit = 0;
    for (const m of n.moduleIds) if (sel.has(m)) hit++;
    if (hit === n.moduleIds.length) out.set(n.id, "full");
    else if (hit) out.set(n.id, "partial");
  }
  return out;
}
