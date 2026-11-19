import { beforeAll, describe, expect, it } from "vitest";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { lengthsPerMppt, layoutOfInverter, notationOfInverter } from "../../src/electrical/sync";
import { parseNotation } from "../../src/electrical/notation";
import type { TopologyCommand } from "../../src/engine/topology";
import { modulesFromView } from "../../src/state/store";
import type { ProjectView } from "../../src/types";
import { goldenRequest } from "./golden";

// F5 done-when (plan C2): plan, tree and notation stay identical through a
// 500-edit randomised test. Each edit is one engine command on the demo engine;
// after every edit the three views must agree, the consistency report must be
// free of errors, and undo/redo must restore the exact electrical design.

const PID = "demo-project";

/** A small seeded generator, so a failure reproduces. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

/** Plan (module colours), tree (topology view) and notation must say the same thing. */
function expectAgreement(v: ProjectView) {
  const modules = modulesFromView(v);
  const plan = new Map<string, Map<string, number>>(); // mpptKey or "" → string → module count
  for (const m of modules) {
    if (!m.stringId) continue;
    const key = m.mpptKey ?? "";
    const bucket = plan.get(key) ?? new Map<string, number>();
    bucket.set(m.stringId, (bucket.get(m.stringId) ?? 0) + 1);
    plan.set(key, bucket);
  }
  const fromTree = new Map<string, Map<string, number>>();
  for (const inv of v.topology_view.inverters) {
    inv.mppts.forEach((mppt, i) => {
      const bucket = new Map(mppt.strings.map((s) => [s.string_id, s.module_count] as const));
      if (bucket.size) fromTree.set(`${inv.inverter_instance_id}#${i}`, bucket);
    });
    // Notation ↔ tree: the same string lengths on every MPPT.
    const parsed = parseNotation(notationOfInverter(inv)).layout!;
    expect(lengthsPerMppt(parsed)).toEqual(lengthsPerMppt(layoutOfInverter(inv)));
    expect(lengthsPerMppt(parsed)).toEqual(inv.mppts.map((m) => m.strings.map((s) => s.module_count).sort((a, b) => a - b)));
  }
  if (v.topology_view.unassigned_strings.length) fromTree.set("", new Map(v.topology_view.unassigned_strings.map((s) => [s.string_id, s.module_count] as const)));
  // Plan ↔ tree.
  expect(Object.fromEntries([...plan].map(([k, m]) => [k, Object.fromEntries(m)]))).toEqual(Object.fromEntries([...fromTree].map(([k, m]) => [k, Object.fromEntries(m)])));
  // Engine consistency.
  expect(v.topology_consistency.findings.filter((f) => f.severity === "error")).toEqual([]);
}

let base: ProjectView;

beforeAll(async () => {
  setDemoLatency(0);
  await mockApi.createProject({ name: "F5 random", latitude_deg: -6.9, longitude_deg: 107.6, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" });
  let v = await mockApi.addSurface(PID, { name: "Roof A", origin_x_m: 0, origin_y_m: 0, width_m: 30, height_m: 16, base_elevation_m: 6, surface_type: "flat_roof" });
  const roofA = v.bundle.scene.surfaces[0].surface_id;
  v = await mockApi.applyFill(PID, goldenRequest({ name: "A", support_surface_id: roofA, module_definition_revision_id: "mod-demo-550", tilt_deg: 10, rows_per_table: 2, module_gap_m: 0.02, in_table_gap_m: 0.02, pitch: { mode: "fixed_aisle", aisle_m: 0.8 }, edge_setbacks_m: [0.5, 0.5, 0.5, 0.5], max_table_columns: 8 }), null);
  v = await mockApi.addSurface(PID, { name: "Roof B", origin_x_m: 40, origin_y_m: 0, width_m: 12, height_m: 8, base_elevation_m: 6, surface_type: "flat_roof" });
  const roofB = v.bundle.scene.surfaces[1].surface_id;
  v = await mockApi.applyFill(PID, goldenRequest({ name: "B", support_surface_id: roofB, module_definition_revision_id: "mod-demo-550", azimuth_deg: 90, tilt_deg: 15 }), null);
  await mockApi.addInverter(PID, { inverter_definition_revision_id: "inv-demo-30k", name: "INV-01" });
  base = await mockApi.addInverter(PID, { inverter_definition_revision_id: "inv-demo-100k", name: "INV-02" });
});

describe("demo topology engine: plan, tree and notation agree through 500 random edits", () => {
  it("keeps the three views identical, the report clean, and every edit reversible (500 applied edits)", async () => {
    const r = rng(20261022);
    const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(r() * xs.length)];
    let v = base;
    const counts: Record<string, { ok: number; refused: number }> = {};
    expect(v.bundle.scene.module_instances.length).toBeGreaterThan(100);

    let applied = 0;
    for (let step = 0; applied < 500 && step < 3000; step++) {
      const strings = v.bundle.electrical_design.strings;
      const mods = v.bundle.scene.module_instances.map((m) => m.module_instance_id);
      const strung = new Set(strings.flatMap((s) => s.module_instance_ids));
      const free = mods.filter((m) => !strung.has(m));
      const mppts = v.bundle.electrical_design.inverter_instances.flatMap((i) => i.mppt_instance_ids);
      const inv = pick(v.bundle.electrical_design.inverter_instances);
      const s = strings.length ? pick(strings) : null;
      const s2 = strings.length ? pick(strings) : null;
      const tables = v.table_layout?.tables.filter((t) => t.status === "active") ?? [];
      const choices: Array<() => TopologyCommand | null> = [
        () => {
          if (free.length < 2) return null;
          const start = Math.floor(r() * free.length);
          return { command_type: "create_string", parameters: { module_instance_ids: free.slice(start, start + 1 + Math.floor(r() * 18)), mppt_instance_id: r() < 0.5 ? pick(mppts) : null } };
        },
        () => (s ? { command_type: "assign_strings_to_mppt", parameters: { string_ids: [s.string_id], mppt_instance_id: pick(mppts) } } : null),
        () => (s ? { command_type: "unassign_strings", parameters: { string_ids: [s.string_id] } } : null),
        () => (s && s.module_instance_ids.length > 1 ? { command_type: "split_string", parameters: { string_id: s.string_id, after_module_instance_id: pick(s.module_instance_ids) } } : null),
        () => (s && s2 ? { command_type: "join_strings", parameters: { first_string_id: s.string_id, second_string_id: s2.string_id } } : null),
        () => (s ? { command_type: "reverse_string", parameters: { string_id: s.string_id } } : null),
        () => (s ? { command_type: "move_module", parameters: { module_instance_id: pick(s.module_instance_ids), to_string_id: s2 && r() < 0.7 ? s2.string_id : null, index: r() < 0.5 ? null : Math.floor(r() * 20) } } : null),
        () => (s && s2 ? { command_type: "swap_modules", parameters: { first_module_instance_id: pick(s.module_instance_ids), second_module_instance_id: pick(s2.module_instance_ids) } } : null),
        () => ({ command_type: "create_strings", parameters: { string_length: 2 + Math.floor(r() * 18), module_instance_ids: r() < 0.5 ? free.slice(0, 40) : null, pv_field_id: null, ordering: pick(["row_major", "serpentine"] as const), allow_shorter_remainder: r() < 0.3 } }),
        () => ({ command_type: "assign_strings", parameters: { inverter_instance_id: inv.inverter_instance_id, string_ids: null } }),
        () => (tables.length ? { command_type: "replicate_pattern", parameters: { source_table_id: pick(tables).table_id, target_table_ids: null } } : null),
        () => ({
          command_type: "apply_mppt_layout",
          parameters: { inverter_instance_id: inv.inverter_instance_id, layout: inv.mppt_instance_ids.map(() => [pick([0, 8, 12, 16]), pick([0, 0, 8, 12, 16])]), pv_field_ids: [] }
        }),
        () => (s ? { command_type: "delete_strings", parameters: { string_ids: [s.string_id] } } : null)
      ];
      const cmd = pick(choices)();
      if (!cmd) continue;
      const tally = (counts[cmd.command_type] ??= { ok: 0, refused: 0 });
      const before = JSON.stringify(v.bundle.electrical_design);
      let next: ProjectView;
      try {
        next = await mockApi.topologyCommand(PID, cmd);
      } catch {
        // A refusal changes nothing.
        tally.refused++;
        expect(JSON.stringify((await mockApi.project(PID)).bundle.electrical_design)).toBe(before);
        continue;
      }
      tally.ok++;
      applied++;
      expectAgreement(next);
      // Inverse: undo restores exactly, redo re-applies exactly.
      const undone = await mockApi.undo(PID);
      expect(JSON.stringify(undone.bundle.electrical_design)).toBe(before);
      const redone = await mockApi.redo(PID);
      expect(JSON.stringify(redone.bundle.electrical_design)).toBe(JSON.stringify(next.bundle.electrical_design));
      v = redone;
    }
    expect(applied).toBe(500);
    // Every command kind ran at least once, and refusals were exercised too.
    for (const kind of ["create_string", "assign_strings_to_mppt", "unassign_strings", "split_string", "join_strings", "reverse_string", "move_module", "swap_modules", "create_strings", "assign_strings", "replicate_pattern", "apply_mppt_layout", "delete_strings"])
      expect(counts[kind]?.ok ?? 0, kind).toBeGreaterThan(0);
    expect(Object.values(counts).reduce((t, c) => t + c.refused, 0)).toBeGreaterThan(0);
  }, 120_000);
});

describe("demo topology engine: individual rules", () => {
  it("refuses a module that is already in a string, and an MPPT beyond its inputs", async () => {
    let v = await mockApi.project(PID);
    const free = v.bundle.scene.module_instances.map((m) => m.module_instance_id).filter((m) => !v.bundle.electrical_design.strings.some((s) => s.module_instance_ids.includes(m)));
    if (free.length < 8) return;
    v = await mockApi.topologyCommand(PID, { command_type: "create_string", parameters: { module_instance_ids: free.slice(0, 2) } });
    await expect(mockApi.topologyCommand(PID, { command_type: "create_string", parameters: { module_instance_ids: [free[0]] } })).rejects.toThrow(/already belongs/);
    const mppt = v.bundle.electrical_design.inverter_instances[0].mppt_instance_ids[0];
    const others = v.bundle.electrical_design.strings.filter((s) => s.target_mppt_instance_id === mppt).length;
    const ids = [];
    for (let i = 0; i < 3 - others; i++) {
      v = await mockApi.topologyCommand(PID, { command_type: "create_string", parameters: { module_instance_ids: free.slice(2 + i * 2, 4 + i * 2) } });
      ids.push(v.bundle.electrical_design.strings[v.bundle.electrical_design.strings.length - 1].string_id);
    }
    await expect(mockApi.topologyCommand(PID, { command_type: "assign_strings_to_mppt", parameters: { string_ids: ids, mppt_instance_id: mppt } })).rejects.toThrow(/DC inputs/);
  });

  it("split then join gives the original string back; reverse twice is the identity", async () => {
    let v = await mockApi.project(PID);
    const s = v.bundle.electrical_design.strings.find((x) => x.module_instance_ids.length >= 4);
    if (!s) return;
    const original = [...s.module_instance_ids];
    v = await mockApi.topologyCommand(PID, { command_type: "split_string", parameters: { string_id: s.string_id, after_module_instance_id: original[1] } });
    const tail = v.bundle.electrical_design.strings[v.bundle.electrical_design.strings.length - 1];
    expect(tail.module_instance_ids).toEqual(original.slice(2));
    v = await mockApi.topologyCommand(PID, { command_type: "join_strings", parameters: { first_string_id: s.string_id, second_string_id: tail.string_id } });
    expect(v.bundle.electrical_design.strings.find((x) => x.string_id === s.string_id)!.module_instance_ids).toEqual(original);
    v = await mockApi.topologyCommand(PID, { command_type: "reverse_string", parameters: { string_id: s.string_id } });
    v = await mockApi.topologyCommand(PID, { command_type: "reverse_string", parameters: { string_id: s.string_id } });
    expect(v.bundle.electrical_design.strings.find((x) => x.string_id === s.string_id)!.module_instance_ids).toEqual(original);
  });

  it("live checks come with the view: one entry per string, from the engine, with its basis", async () => {
    const v = await mockApi.project(PID);
    expect(v.topology_checks?.strings.map((c) => c.string_id).sort()).toEqual(v.bundle.electrical_design.strings.map((s) => s.string_id).sort());
    expect(v.topology_checks?.basis).toMatch(/demo/);
  });
});

describe("demo topology engine: replicate pattern", () => {
  it("wires every identical, unwired table like the source table, slot by slot, unassigned", async () => {
    await mockApi.createProject({ name: "F5 replicate", latitude_deg: -6.9, longitude_deg: 107.6, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" });
    let v = await mockApi.addSurface(PID, { name: "Roof", origin_x_m: 0, origin_y_m: 0, width_m: 30, height_m: 16, base_elevation_m: 6, surface_type: "flat_roof" });
    v = await mockApi.applyFill(
      PID,
      goldenRequest({ name: "R", support_surface_id: v.bundle.scene.surfaces[0].surface_id, module_definition_revision_id: "mod-demo-550", tilt_deg: 10, rows_per_table: 2, module_gap_m: 0.02, in_table_gap_m: 0.02, pitch: { mode: "fixed_aisle", aisle_m: 0.8 }, edge_setbacks_m: [0.5, 0.5, 0.5, 0.5], max_table_columns: 8 }),
      null
    );
    const tables = v.table_layout!.tables.filter((t) => t.status === "active");
    const full = tables.filter((t) => t.rows === 2 && t.columns === 8 && !(t.removed_slots?.length));
    expect(full.length).toBeGreaterThan(2);
    const src = full[0];
    // Serpentine inside the table: row 0 left to right, row 1 right to left.
    const order = [...Array.from({ length: 8 }, (_, c) => [0, c]), ...Array.from({ length: 8 }, (_, c) => [1, 7 - c])];
    v = await mockApi.topologyCommand(PID, { command_type: "create_string", parameters: { module_instance_ids: order.map(([r, c]) => `${src.table_id}/${r}.${c}`) } });
    v = await mockApi.topologyCommand(PID, { command_type: "replicate_pattern", parameters: { source_table_id: src.table_id, target_table_ids: null } });
    expectAgreement(v);
    for (const t of full.slice(1)) {
      const want = order.map(([r, c]) => `${t.table_id}/${r}.${c}`);
      const got = v.bundle.electrical_design.strings.find((s) => s.module_instance_ids[0]?.startsWith(`${t.table_id}/`));
      expect(got?.module_instance_ids, t.table_id).toEqual(want);
      expect(got?.target_mppt_instance_id).toBeNull();
    }
    // Replicating again changes nothing: every identical table is wired now.
    const again = await mockApi.topologyCommand(PID, { command_type: "replicate_pattern", parameters: { source_table_id: src.table_id, target_table_ids: null } }).catch(() => null);
    if (again) expect(again.bundle.electrical_design.strings.length).toBe(v.bundle.electrical_design.strings.length);
  });
});
