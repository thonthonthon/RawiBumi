import fs from "node:fs";
import path from "node:path";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it } from "vitest";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { endPoint, layoutSld, selectionState, SLD, type SldLayout } from "../../src/electrical/sldLayout";
import { SHEET_ORDER, SYMBOLS, symbol } from "../../src/electrical/symbols";
import { parseSymbol, SymbolParseError } from "../../src/electrical/symbols/parse";
import { SymbolGlyph } from "../../src/electrical/symbols/SymbolGlyph";
import type { TopologyCommand } from "../../src/engine/topology";
import type { ProjectView } from "../../src/types";

// F6 (plan C2): the SLD is generated from the assignment, its symbols are the
// in-house library (the symbol sheet), and every node maps to plan objects.

const DIR = path.resolve(__dirname, "../../src/electrical/symbols");
const t = (key: string, o: Record<string, unknown> = {}) => `${key}${Object.keys(o).length ? JSON.stringify(o) : ""}`;

describe("symbol library", () => {
  const files = fs.readdirSync(DIR).filter((f) => f.endsWith(".svg"));

  it("has one file per sheet entry, named by its id, and nothing else", () => {
    expect(files.map((f) => f.replace(/\.svg$/, "")).sort()).toEqual([...SHEET_ORDER].sort());
    for (const f of files) expect(parseSymbol(fs.readFileSync(path.join(DIR, f), "utf8")).id).toBe(f.replace(/\.svg$/, ""));
    expect(Object.keys(SYMBOLS).sort()).toEqual([...SHEET_ORDER].sort());
  });

  it("every symbol has terminals on its own outline, and draws without inline style or colour", () => {
    for (const id of SHEET_ORDER) {
      const s = symbol(id);
      const [vx, vy, vw, vh] = s.viewBox;
      for (const [name, [x, y]] of Object.entries(s.terminals)) {
        expect(x >= vx && x <= vx + vw && y >= vy && y <= vy + vh, `${id}.${name} inside viewBox`).toBe(true);
        expect(x === vx || x === vx + vw || y === vy || y === vy + vh, `${id}.${name} on the viewBox edge`).toBe(true);
      }
      expect(s.elements.length).toBeGreaterThan(0);
    }
    const raw = files.map((f) => fs.readFileSync(path.join(DIR, f), "utf8")).join("\n");
    expect(raw).not.toMatch(/style=|fill="#|stroke="#|rgb\(/);
  });

  it("the parser refuses markup outside the subset", () => {
    const bad = (body: string) => () => parseSymbol(`<svg viewBox="0 0 10 10" data-symbol="x">${body}<circle data-terminal="a" cx="0" cy="0" r="0"/></svg>`);
    expect(bad(`<line style="stroke:red" x1="0" y1="0" x2="1" y2="1"/>`)).toThrow(SymbolParseError);
    expect(bad(`<image href="x.png"/>`)).toThrow(SymbolParseError);
    expect(bad(`<line class="other" x1="0" y1="0" x2="1" y2="1"/>`)).toThrow(SymbolParseError);
    expect(() => parseSymbol(`<svg viewBox="0 0 10 10" data-symbol="x"><line class="sym__line" x1="0" y1="0" x2="1" y2="1"/></svg>`)).toThrow(/no terminals/);
  });

  it("ignores <metadata>, such as a content-credentials manifest added when files are delivered", () => {
    for (const id of SHEET_ORDER) {
      const clean = fs.readFileSync(path.join(DIR, `${id}.svg`), "utf8");
      const signed = clean.replace(/(<svg\b[^>]*?)>/, '$1 xmlns:c2pa="http://c2pa.org/manifest"><metadata><c2pa:manifest>AAAWgmp1bWI+/=</c2pa:manifest></metadata>');
      expect(signed).toContain("<metadata>");
      expect(parseSymbol(signed), id).toEqual(parseSymbol(clean));
    }
    // Anything else outside the subset is still refused.
    expect(() => parseSymbol(`<svg viewBox="0 0 1 1" data-symbol="x"><foreignObject>x</foreignObject><circle data-terminal="a" cx="0" cy="0" r="0"/></svg>`)).toThrow(SymbolParseError);
  });

  it("the drawn symbol is exactly the file: same elements, attributes and text (sheet = source)", () => {
    for (const id of SHEET_ORDER) {
      const html = renderToStaticMarkup(createElement(SymbolGlyph, { id }));
      const inner = html.replace(/^<g data-symbol-body="[^"]+">/, "").replace(/<\/g>$/, "");
      const round = parseSymbol(`<svg viewBox="0 0 1 1" data-symbol="${id}">${inner}<circle data-terminal="t" cx="0" cy="0" r="0"/></svg>`);
      expect(round.elements, id).toEqual(symbol(id).elements);
    }
  });
});

/** Structural rules every generated SLD must meet. */
function expectWellFormed(layout: SldLayout, view: ProjectView) {
  const ids = new Set(layout.nodes.map((n) => n.id));
  expect(ids.size).toBe(layout.nodes.length);
  // Every wire starts and ends exactly on a terminal (or on the busbar for a tap), and is orthogonal.
  for (const w of layout.wires) {
    for (const [end, p] of [
      [w.from, w.points[0]],
      [w.to, w.points[w.points.length - 1]]
    ] as const) {
      const at = endPoint(layout, end);
      if (Array.isArray(at)) expect(p, `${w.id} ${end.node}.${end.terminal}`).toEqual(at);
      else {
        expect(p[0]).toBe(at.x);
        expect(p[1]).toBeGreaterThanOrEqual(at.yMin - 1e-9);
        expect(p[1]).toBeLessThanOrEqual(at.yMax + 1e-9);
      }
    }
    for (let i = 1; i < w.points.length; i++) expect(w.points[i][0] === w.points[i - 1][0] || w.points[i][1] === w.points[i - 1][1], `${w.id} orthogonal`).toBe(true);
  }
  // Symbols, with their selection boxes, do not overlap.
  const boxes = layout.nodes.map((n) => {
    const [vx, vy, vw, vh] = symbol(n.symbol).viewBox;
    // The 3-unit pad is the selection box the view draws: selected neighbours must not touch either.
    return { id: n.id, x0: n.x + vx - 3, y0: n.y + vy * n.stretch - 3, x1: n.x + vx + vw + 3, y1: n.y + (vy + vh) * n.stretch + 3 };
  });
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i];
      const b = boxes[j];
      const overlap = a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
      expect(overlap, `${a.id} overlaps ${b.id}`).toBe(false);
    }
  // Generated from the assignment: every string appears in exactly one string or group node,
  // under its MPPT when assigned; MPPT and inverter nodes stand for exactly their strings' modules.
  const design = view.bundle.electrical_design;
  const seen = layout.nodes.filter((n) => n.kind === "string" || n.kind === "strings").flatMap((n) => n.stringIds);
  expect(seen.sort()).toEqual(design.strings.map((s) => s.string_id).sort());
  for (const inv of view.topology_view.inverters) {
    for (const m of inv.mppts) {
      const node = layout.nodes.find((n) => n.id === `mppt:${m.mppt_instance_id}`)!;
      expect(node.stringIds).toEqual(m.strings.map((s) => s.string_id));
      const sources = layout.wires.filter((w) => w.to.node === node.id).map((w) => w.from.node);
      expect(sources.flatMap((id) => layout.nodes.find((n) => n.id === id)!.stringIds).sort()).toEqual([...node.stringIds].sort());
    }
    const invNode = layout.nodes.find((n) => n.id === `inv:${inv.inverter_instance_id}`)!;
    expect(new Set(invNode.moduleIds)).toEqual(new Set(design.strings.filter((s) => inv.mppts.some((m) => m.mppt_instance_id === s.target_mppt_instance_id)).flatMap((s) => s.module_instance_ids)));
  }
  expect(layout.width).toBeGreaterThan(0);
  expect(Math.max(...layout.nodes.map((n) => n.y))).toBeLessThan(layout.height);
}

let demo: ProjectView;
beforeAll(async () => {
  setDemoLatency(0);
  demo = await mockApi.project("demo-project");
});

describe("SLD layout from the assignment", () => {
  it("draws the demo: 5 strings → 4 MPPT inputs → INV-01 → busbar → grid and load", () => {
    const l = layoutSld(demo, t);
    const kinds = (k: string) => l.nodes.filter((n) => n.kind === k).length;
    expect([kinds("string"), kinds("mppt"), kinds("inverter"), kinds("bus"), kinds("grid"), kinds("load")]).toEqual([5, 4, 1, 1, 1, 1]);
    expect(l.wires).toHaveLength(5 + 4 + 1 + 2);
    expect(l.nodes.find((n) => n.id === "mppt:mppt-4")!.stringIds).toEqual(["S4", "S5"]);
    expectWellFormed(l, demo);
  });

  it("an empty MPPT is drawn muted and still wired to its inverter; unassigned strings are drawn unwired", async () => {
    let v = await mockApi.topologyCommand("demo-project", { command_type: "unassign_strings", parameters: { string_ids: ["S2"] } });
    const l = layoutSld(v, t);
    expect(l.nodes.find((n) => n.id === "mppt:mppt-2")).toMatchObject({ muted: true, stringIds: [] });
    expect(l.wires.some((w) => w.from.node === "mppt:mppt-2")).toBe(true);
    const un = l.nodes.find((n) => n.id === "un:S2")!;
    expect(un.muted).toBe(true);
    expect(l.wires.some((w) => w.from.node === un.id || w.to.node === un.id)).toBe(false);
    expectWellFormed(l, v);
    v = await mockApi.undo("demo-project");
    expect(layoutSld(v, t).nodes.some((n) => n.id === "un:S2")).toBe(false);
  });

  it("more than four strings on one MPPT become one group node that stands for all of them", () => {
    const v: ProjectView = structuredClone(demo);
    const m = v.topology_view.inverters[0].mppts[0];
    const extra = ["X1", "X2", "X3", "X4", "X5"].map((id, i) => ({ string_id: id, module_instance_ids: [`x-${i}-a`, `x-${i}-b`], target_mppt_instance_id: m.mppt_instance_id, enabled: true }));
    v.bundle.electrical_design.strings.push(...extra);
    m.strings.push(...extra.map((s) => ({ string_id: s.string_id, name: s.string_id, module_count: 2, enabled: true })));
    const l = layoutSld(v, t);
    const g = l.nodes.find((n) => n.id === `grp:${m.mppt_instance_id}`)!;
    expect(g.kind).toBe("strings");
    expect(g.stringIds).toEqual(["S1", "X1", "X2", "X3", "X4", "X5"]);
    expect(g.moduleIds).toHaveLength(16 + 10);
    expect(l.nodes.some((n) => n.id === "str:S1")).toBe(false);
    expect(SLD.groupAbove).toBe(4);
    expectWellFormed(l, v);
  });

  it("stays well formed through 60 random topology edits (every layout regenerated from the engine)", async () => {
    let seed = 6;
    const r = () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 2 ** 32);
    const pick = <T,>(xs: readonly T[]) => xs[Math.floor(r() * xs.length)];
    let v = await mockApi.project("demo-project");
    let applied = 0;
    for (let step = 0; applied < 60 && step < 600; step++) {
      const strs = v.bundle.electrical_design.strings;
      const mppts = v.bundle.electrical_design.inverter_instances.flatMap((i) => i.mppt_instance_ids);
      const s = pick(strs);
      const cmds: TopologyCommand[] = [
        { command_type: "unassign_strings", parameters: { string_ids: [s.string_id] } },
        { command_type: "assign_strings_to_mppt", parameters: { string_ids: [s.string_id], mppt_instance_id: pick(mppts) } },
        ...(s.module_instance_ids.length > 1 ? [{ command_type: "split_string", parameters: { string_id: s.string_id, after_module_instance_id: pick(s.module_instance_ids.slice(0, -1)) } } as TopologyCommand] : []),
        { command_type: "join_strings", parameters: { first_string_id: s.string_id, second_string_id: pick(strs).string_id } },
        { command_type: "reverse_string", parameters: { string_id: s.string_id } }
      ];
      try {
        v = await mockApi.topologyCommand("demo-project", pick(cmds));
      } catch {
        continue;
      }
      applied++;
      expectWellFormed(layoutSld(v, t), v);
    }
    expect(applied).toBe(60);
  });
});

describe("two-way selection", () => {
  it("a node stands for its modules; a plan selection marks nodes full or partial", () => {
    const l = layoutSld(demo, t);
    const s1 = l.nodes.find((n) => n.id === "str:S1")!;
    expect(s1.moduleIds).toEqual(demo.bundle.electrical_design.strings.find((s) => s.string_id === "S1")!.module_instance_ids);
    let sel = selectionState(l, s1.moduleIds);
    expect(sel.get("str:S1")).toBe("full");
    expect(sel.get("mppt:mppt-1")).toBe("full");
    expect(sel.get("inv:inv-01")).toBe("partial");
    expect(sel.has("str:S2")).toBe(false);
    sel = selectionState(l, [s1.moduleIds[0]]);
    expect(sel.get("str:S1")).toBe("partial");
    expect(selectionState(l, []).size).toBe(0);
    // Nodes with no plan object (busbar, grid, load) never select anything.
    for (const id of ["bus", "grid", "load"]) expect(l.nodes.find((n) => n.id === id)!.moduleIds).toEqual([]);
  });
});
