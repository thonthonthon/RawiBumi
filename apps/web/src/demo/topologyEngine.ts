/**
 * DEMO MODE ONLY — the demo engine's electrical topology commands (E5) and live
 * checks, standing in for the engine's ElectricalTopologyEditorSession until
 * proposal 0004 lands. Never imported by screens.
 *
 * Rules kept from the engine session (electrical/topology/editor.py):
 * - a module belongs to at most one string; strings list modules in wiring order;
 * - an assigned string is enabled, an unassigned one is not;
 * - an MPPT takes at most its verified number of DC inputs;
 * - the consistency report has the engine's codes and severities.
 * Every command either applies whole or throws, so the session can undo it.
 */
import i18n from "../i18n";
import { normalAngleDeg, type Vec2 } from "../geometry";
import type { TableRecord } from "../engine/layout";
import type { LiveCheck, StringCheck, TopologyChecks, TopologyCommand } from "../engine/topology";

export interface DemoString {
  string_id: string;
  module_instance_ids: string[];
  target_mppt_instance_id: string | null;
  enabled: boolean;
}

export interface DemoInverter {
  inverter_instance_id: string;
  inverter_definition_revision_id: string;
  name: string;
  enabled: boolean;
  mppt_instance_ids: string[];
  paired_pv_field_ids?: string[];
}

/** S14b: the orientation policy as the demo design keeps it (absent: 1° between module normals, no overrides). */
export interface DemoOrientationPolicy {
  normal_angle_tolerance_deg?: number | null;
  overrides?: Array<{ mppt_instance_id: string; reason: string }>;
}

export interface ModuleInfo {
  id: string;
  fieldId: string;
  centre: Vec2;
  enabled: boolean;
  slot: { tableId: string; row: number; column: number } | null;
}

/** Synthetic electrical data of the demo catalogue (not exposed in the catalogue summary). */
export const DEMO_MODULE_ELECTRICAL: Record<string, { voc: number; vmp: number; imp: number; isc: number }> = {
  "mod-demo-550": { voc: 49.6, vmp: 41.9, imp: 13.13, isc: 13.94 },
  "mod-demo-610": { voc: 53.4, vmp: 44.9, imp: 13.59, isc: 14.4 },
  "mod-demo-golden": { voc: 37.2, vmp: 31.0, imp: 12.9, isc: 13.7 }
};

export const DEMO_INVERTER_ELECTRICAL: Record<string, { maxDc: number; window: [number, number]; maxInputA: number; inputs: number }> = {
  "inv-demo-30k": { maxDc: 1100, window: [200, 1000], maxInputA: 32, inputs: 2 },
  "inv-demo-100k": { maxDc: 1100, window: [180, 1000], maxInputA: 40, inputs: 2 }
};

/** Demo stand-in for the engine's cold-temperature Voc rule (site minimum temperature × coefficient). */
export const DEMO_COLD_FACTOR = 1.1;

export interface TopologyContext {
  inverters: readonly DemoInverter[];
  strings: readonly DemoString[];
  modules: ReadonlyMap<string, ModuleInfo>;
  tables: readonly TableRecord[];
  /** pv_field_id → module definition, tilt and azimuth. */
  fields: ReadonlyMap<string, { module: string; tilt: number; azimuth: number }>;
  orientation_policy?: DemoOrientationPolicy;
}

const tolerance = (ctx: TopologyContext) => ctx.orientation_policy?.normal_angle_tolerance_deg ?? 1;

/**
 * S14b: the policy and pairing commands, on a copy of the demo design's inverters and policy. They change no string;
 * a refusal throws and changes nothing.
 */
export function applyDesignCommand(ctx: TopologyContext, cmd: TopologyCommand): { inverters: DemoInverter[]; orientation_policy: DemoOrientationPolicy } | null {
  const inverters = ctx.inverters.map((i) => ({ ...i }));
  const policy: DemoOrientationPolicy = { normal_angle_tolerance_deg: ctx.orientation_policy?.normal_angle_tolerance_deg ?? null, overrides: [...(ctx.orientation_policy?.overrides ?? [])] };
  switch (cmd.command_type) {
    case "set_orientation_tolerance": {
      const t = cmd.parameters.tolerance_deg;
      if (!Number.isFinite(t) || t < 0 || t > 1) fail("The orientation tolerance must be between 0° and 1°.");
      policy.normal_angle_tolerance_deg = t;
      break;
    }
    case "set_orientation_override": {
      const { mppt_instance_id: id, reason } = cmd.parameters;
      if (!inverters.some((i) => i.mppt_instance_ids.includes(id))) fail(`Unknown MPPT ${id}.`);
      const text = reason === null ? null : reason.trim();
      if (text !== null && (text.length < 1 || text.length > 500)) fail("An orientation override needs a reason of 1 to 500 characters.");
      policy.overrides = [...(policy.overrides ?? []).filter((o) => o.mppt_instance_id !== id), ...(text === null ? [] : [{ mppt_instance_id: id, reason: text }])]
        .sort((a, b) => a.mppt_instance_id.localeCompare(b.mppt_instance_id));
      break;
    }
    case "set_inverter_pairing": {
      const inv = inverters.find((i) => i.inverter_instance_id === cmd.parameters.inverter_instance_id) ?? fail(`Unknown inverter ${cmd.parameters.inverter_instance_id}.`);
      const ids = [...new Set(cmd.parameters.pv_field_ids)];
      const unknown = ids.filter((f) => !ctx.fields.has(f));
      if (unknown.length) fail(`Unknown PV fields: ${unknown.join(", ")}.`);
      if (ids.length) inv.paired_pv_field_ids = ids;
      else delete inv.paired_pv_field_ids;
      break;
    }
    default:
      return null;
  }
  return { inverters, orientation_policy: policy };
}

export class TopologyError extends Error {}

const fail = (message: string): never => {
  throw new TopologyError(message);
};

function nextId(strings: readonly DemoString[]): () => string {
  let n = strings.reduce((m, s) => Math.max(m, Number(/^S(\d+)$/.exec(s.string_id)?.[1] ?? 0)), 0);
  return () => `S${++n}`;
}

function mpptOwner(ctx: TopologyContext, mppt: string): DemoInverter {
  return ctx.inverters.find((i) => i.mppt_instance_ids.includes(mppt)) ?? fail(`Unknown MPPT ${mppt}.`);
}

export function mpptInputs(ctx: Pick<TopologyContext, "inverters">, mppt: string): number | null {
  const inv = ctx.inverters.find((i) => i.mppt_instance_ids.includes(mppt));
  return inv ? (DEMO_INVERTER_ELECTRICAL[inv.inverter_definition_revision_id]?.inputs ?? null) : null;
}

function checkCapacity(ctx: TopologyContext, strings: readonly DemoString[], mppt: string) {
  const cap = mpptInputs(ctx, mppt);
  const used = strings.filter((s) => s.target_mppt_instance_id === mppt).length;
  if (cap !== null && used > cap) {
    const inv = mpptOwner(ctx, mppt);
    fail(`${inv.name} MPPT ${inv.mppt_instance_ids.indexOf(mppt) + 1} has ${cap} DC inputs; this would use ${used}.`);
  }
}

function unique(ids: readonly string[], what: string): string[] {
  if (new Set(ids).size !== ids.length) fail(`${what} lists a module more than once.`);
  return [...ids];
}

/** Rows by field, then from north to south, then west to east; serpentine reverses every other row. */
export function orderModules(ctx: TopologyContext, ids: readonly string[], ordering: "row_major" | "serpentine" | "selection"): string[] {
  if (ordering === "selection") return [...ids];
  const mods = ids.map((id) => ctx.modules.get(id) ?? fail(`Unknown module ${id}.`));
  const rowKey = (m: ModuleInfo) => Math.round(m.centre[1] / 0.05);
  const sorted = [...mods].sort((a, b) => a.fieldId.localeCompare(b.fieldId) || rowKey(b) - rowKey(a) || a.centre[0] - b.centre[0] || a.id.localeCompare(b.id));
  if (ordering === "row_major") return sorted.map((m) => m.id);
  const out: string[] = [];
  let row: ModuleInfo[] = [];
  let flip = false;
  const flush = () => {
    out.push(...(flip ? [...row].reverse() : row).map((m) => m.id));
    flip = !flip;
    row = [];
  };
  for (const m of sorted) {
    if (row.length && (row[0].fieldId !== m.fieldId || rowKey(row[0]) !== rowKey(m))) {
      const nextField = row[0].fieldId !== m.fieldId;
      flush();
      if (nextField) flip = false; // like the engine: each field starts west to east
    }
    row.push(m);
  }
  if (row.length) flush();
  return out;
}

/** Applies one command and returns the new strings. Throws TopologyError and changes nothing on refusal. */
export function applyTopologyCommand(ctx: TopologyContext, cmd: TopologyCommand): DemoString[] {
  let strings = ctx.strings.map((s) => ({ ...s, module_instance_ids: [...s.module_instance_ids] }));
  const newId = nextId(strings);
  const byId = (id: string) => strings.find((s) => s.string_id === id) ?? fail(`Unknown string ${id}.`);
  const owner = new Map<string, DemoString>();
  for (const s of strings) for (const m of s.module_instance_ids) owner.set(m, s);
  const freeModule = (id: string) => {
    const m = ctx.modules.get(id) ?? fail(`Unknown module ${id}.`);
    if (!m.enabled) fail(`Module ${id} is disabled.`);
    if (owner.has(id)) fail(`Module ${id} already belongs to ${owner.get(id)!.string_id}.`);
  };
  const takeUnassigned = (ids: string[]) => {
    for (const id of ids) {
      const source = owner.get(id);
      if (source?.target_mppt_instance_id) {
        const inv = mpptOwner(ctx, source.target_mppt_instance_id);
        fail(i18n.t("str1.assigned", { locations: `${source.string_id}${i18n.t("str1.onMppt")}${inv.mppt_instance_ids.indexOf(source.target_mppt_instance_id) + 1}`, strings: source.string_id }));
      }
      if (source) {
        source.module_instance_ids = source.module_instance_ids.filter((mid) => mid !== id);
        owner.delete(id);
      }
      freeModule(id);
    }
    strings = strings.filter((s) => s.module_instance_ids.length);
  };
  const assign = (s: DemoString, mppt: string | null) => {
    s.target_mppt_instance_id = mppt;
    s.enabled = mppt !== null;
  };
  switch (cmd.command_type) {
    case "create_string": {
      const ids = unique(cmd.parameters.module_instance_ids, "The string");
      if (!ids.length) fail("A string needs at least one module.");
      takeUnassigned(ids);
      const s: DemoString = { string_id: newId(), module_instance_ids: ids, target_mppt_instance_id: null, enabled: false };
      if (cmd.parameters.mppt_instance_id) {
        mpptOwner(ctx, cmd.parameters.mppt_instance_id);
        assign(s, cmd.parameters.mppt_instance_id);
      }
      strings.push(s);
      if (s.target_mppt_instance_id) checkCapacity(ctx, strings, s.target_mppt_instance_id);
      break;
    }
    case "delete_strings": {
      const ids = new Set(cmd.parameters.string_ids);
      cmd.parameters.string_ids.forEach(byId);
      strings = strings.filter((s) => !ids.has(s.string_id));
      break;
    }
    case "assign_strings_to_mppt": {
      const { string_ids, mppt_instance_id } = cmd.parameters;
      mpptOwner(ctx, mppt_instance_id);
      for (const id of string_ids) assign(byId(id), mppt_instance_id);
      checkCapacity(ctx, strings, mppt_instance_id);
      break;
    }
    case "unassign_strings":
      for (const id of cmd.parameters.string_ids) assign(byId(id), null);
      break;
    case "split_string": {
      const s = byId(cmd.parameters.string_id);
      const at = s.module_instance_ids.indexOf(cmd.parameters.after_module_instance_id);
      if (at < 0) fail(`Module ${cmd.parameters.after_module_instance_id} is not in ${s.string_id}.`);
      if (at === s.module_instance_ids.length - 1) fail("Split after the last module leaves nothing to split off.");
      const tail = s.module_instance_ids.splice(at + 1);
      const t: DemoString = { string_id: newId(), module_instance_ids: tail, target_mppt_instance_id: null, enabled: false };
      strings.push(t);
      if (s.target_mppt_instance_id) {
        assign(t, s.target_mppt_instance_id);
        checkCapacity(ctx, strings, s.target_mppt_instance_id);
      }
      break;
    }
    case "append_to_string": {
      const ids = unique(cmd.parameters.module_instance_ids, "The modules");
      const target = byId(cmd.parameters.string_id);
      if (!target.target_mppt_instance_id && ids.some((id) => target.module_instance_ids.includes(id))) fail(i18n.t("str1.alreadyIn", { string: target.string_id }));
      takeUnassigned(ids);
      target.module_instance_ids.push(...ids);
      break;
    }
    case "join_strings": {
      const { first_string_id, second_string_id } = cmd.parameters;
      if (first_string_id === second_string_id) fail("Join needs two different strings.");
      const a = byId(first_string_id);
      const b = byId(second_string_id);
      a.module_instance_ids.push(...b.module_instance_ids);
      strings = strings.filter((s) => s !== b);
      break;
    }
    case "reverse_string":
      byId(cmd.parameters.string_id).module_instance_ids.reverse();
      break;
    case "move_module": {
      const { module_instance_id: mid, to_string_id, index } = cmd.parameters;
      const from = owner.get(mid) ?? fail(`Module ${mid} is not in a string.`);
      from.module_instance_ids = from.module_instance_ids.filter((x) => x !== mid);
      if (to_string_id !== null) {
        const to = byId(to_string_id);
        const i = index === null ? to.module_instance_ids.length : Math.max(0, Math.min(index, to.module_instance_ids.length));
        to.module_instance_ids.splice(i, 0, mid);
      }
      if (!from.module_instance_ids.length) strings = strings.filter((s) => s !== from);
      break;
    }
    case "swap_modules": {
      const { first_module_instance_id: x, second_module_instance_id: y } = cmd.parameters;
      if (x === y) fail("Swap needs two different modules.");
      const sx = owner.get(x) ?? fail(`Module ${x} is not in a string.`);
      const sy = owner.get(y) ?? fail(`Module ${y} is not in a string.`);
      const ix = sx.module_instance_ids.indexOf(x);
      const iy = sy.module_instance_ids.indexOf(y);
      sx.module_instance_ids[ix] = y;
      sy.module_instance_ids[iy] = x;
      break;
    }
    case "create_strings": {
      const { string_length, module_instance_ids, pv_field_id, ordering, allow_shorter_remainder } = cmd.parameters;
      if (!Number.isInteger(string_length) || string_length < 1) fail("Modules per string must be a whole number of at least 1.");
      const pool = (module_instance_ids ?? [...ctx.modules.keys()]).filter((id) => {
        const m = ctx.modules.get(id);
        return m && m.enabled && !owner.has(id) && (!pv_field_id || m.fieldId === pv_field_id);
      });
      const ordered = orderModules(ctx, pool, ordering);
      let made = 0;
      for (let i = 0; i < ordered.length; i += string_length) {
        const chunk = ordered.slice(i, i + string_length);
        if (chunk.length < string_length && !allow_shorter_remainder) break;
        strings.push({ string_id: newId(), module_instance_ids: chunk, target_mppt_instance_id: null, enabled: false });
        made++;
      }
      if (!made) fail(`No ${string_length}-module string fits the unstrung modules.`);
      break;
    }
    case "assign_strings": {
      const inv = ctx.inverters.find((i) => i.inverter_instance_id === cmd.parameters.inverter_instance_id) ?? fail(`Unknown inverter ${cmd.parameters.inverter_instance_id}.`);
      const pick = cmd.parameters.string_ids ? cmd.parameters.string_ids.map(byId) : strings.filter((s) => !s.target_mppt_instance_id);
      if (!pick.length) fail("There are no unassigned strings.");
      let k = 0;
      for (const s of pick) {
        let placed = false;
        for (let tries = 0; tries < inv.mppt_instance_ids.length && !placed; tries++) {
          const m = inv.mppt_instance_ids[k++ % inv.mppt_instance_ids.length];
          const cap = mpptInputs(ctx, m);
          if (cap === null || strings.filter((x) => x.target_mppt_instance_id === m).length < cap) {
            assign(s, m);
            placed = true;
          }
        }
        if (!placed) fail(`${inv.name} has no free DC input left for ${s.string_id}.`);
      }
      break;
    }
    case "replicate_pattern": {
      const src = ctx.tables.find((t) => t.table_id === cmd.parameters.source_table_id) ?? fail(`Unknown table ${cmd.parameters.source_table_id}.`);
      const slotOfModule = (id: string) => ctx.modules.get(id)?.slot ?? null;
      const pattern = strings
        .filter((s) => s.module_instance_ids.length && s.module_instance_ids.every((id) => slotOfModule(id)?.tableId === src.table_id))
        .map((s) => s.module_instance_ids.map((id) => slotOfModule(id)!));
      if (!pattern.length) fail("Wire the source table first: no string lies wholly inside it.");
      const sig = (t: TableRecord) => `${t.rows}x${t.columns}|${t.orientation}|${t.removed_slots.map((r) => `${r[0]}.${r[1]}`).sort().join(",")}`;
      const candidates = cmd.parameters.targets
        ? cmd.parameters.targets.map(({ table_id: id }) => ctx.tables.find((t) => t.table_id === id) ?? fail(`Unknown table ${id}.`))
        : ctx.tables.filter((t) => t.table_id !== src.table_id && t.status === "active" && sig(t) === sig(src));
      const slotModule = new Map<string, string>();
      for (const m of ctx.modules.values()) if (m.slot) slotModule.set(`${m.slot.tableId}/${m.slot.row}.${m.slot.column}`, m.id);
      let copies = 0;
      for (const t of candidates) {
        if (sig(t) !== sig(src)) fail(`Table ${t.table_id} is not identical to the source.`);
        const mapped = pattern.map((ss) => ss.map((sl) => slotModule.get(`${t.table_id}/${sl.row}.${sl.column}`) ?? ""));
        if (mapped.some((ss) => ss.some((id) => !id || owner.has(id)))) continue; // already wired or incomplete: skipped
        for (const ids of mapped) strings.push({ string_id: newId(), module_instance_ids: ids, target_mppt_instance_id: null, enabled: false });
        copies++;
      }
      if (!copies) fail("No identical, unwired table to copy the pattern to.");
      break;
    }
    case "apply_mppt_layout": {
      const { inverter_instance_id, layout } = cmd.parameters;
      const inv = ctx.inverters.find((i) => i.inverter_instance_id === inverter_instance_id) ?? fail(`Unknown inverter ${inverter_instance_id}.`);
      const pv_field_ids = cmd.parameters.pv_field_ids?.length ? cmd.parameters.pv_field_ids : (inv.paired_pv_field_ids ?? []);
      if (layout.length !== inv.mppt_instance_ids.length) fail(`The layout has ${layout.length} MPPTs; ${inv.name} has ${inv.mppt_instance_ids.length}.`);
      const cap = mpptInputs(ctx, inv.mppt_instance_ids[0]);
      layout.forEach((row, i) => {
        if (cap !== null && row.filter((n) => n > 0).length > cap) fail(`MPPT ${i + 1} would use ${row.filter((n) => n > 0).length} inputs; it has ${cap}.`);
        if (row.some((n) => !Number.isInteger(n) || n < 0)) fail("String lengths must be whole numbers of 0 or more.");
      });
      const sources = cmd.parameters.sources;
      if (sources && sources.length !== inv.mppt_instance_ids.length) fail("sources length must equal the MPPT count");
      for (const source of sources ?? []) if (source !== null && (!source.length || source.some(f => !ctx.fields.has(f) || (pv_field_ids.length && !pv_field_ids.includes(f)))))
        fail("each source must be non-empty, known PV fields inside the inverter pool");
      const restricted = sources?.some(s => s !== null) ?? false;
      const sourceOf = (mppt: string) => sources?.[inv.mppt_instance_ids.indexOf(mppt)] ?? null;
      const inSource = (id: string, mppt: string) => sourceOf(mppt) === null
        ? !pv_field_ids.length || pv_field_ids.includes(ctx.modules.get(id)?.fieldId ?? "")
        : sourceOf(mppt)!.includes(ctx.modules.get(id)?.fieldId ?? "");
      // Keep strings that already match, by MPPT and length; free the rest of this inverter's strings.
      const mine = strings.filter((s) => s.target_mppt_instance_id && inv.mppt_instance_ids.includes(s.target_mppt_instance_id));
      const kept = new Set<DemoString>();
      const wanted: Array<{ mppt: string; n: number }> = [];
      layout.forEach((row, i) => {
        const mppt = inv.mppt_instance_ids[i];
        for (const n of row.filter((x) => x > 0)) {
          const match = mine.find((s) => !kept.has(s) && s.target_mppt_instance_id === mppt && s.module_instance_ids.length === n && (!restricted || s.module_instance_ids.every(id => inSource(id, mppt))));
          if (match) kept.add(match);
          else wanted.push({ mppt, n });
        }
      });
      for (const s of mine) if (!kept.has(s)) assign(s, null);
      // Fill the rest: unassigned strings of the right length first, then new strings from unstrung modules.
      const fieldOk = (id: string) => !pv_field_ids.length || pv_field_ids.includes(ctx.modules.get(id)?.fieldId ?? "");
      const freeStrings = strings.filter((s) => !s.target_mppt_instance_id && s.module_instance_ids.every(fieldOk));
      const fresh: Array<{ mppt: string; n: number; ids: string[] }> = [];
      for (const w of wanted) {
        const reuse = freeStrings.find((s) => !s.target_mppt_instance_id && s.module_instance_ids.length === w.n && (!restricted || s.module_instance_ids.every(id => inSource(id, w.mppt))));
        if (reuse) {
          assign(reuse, w.mppt);
          continue;
        }
        fresh.push({ ...w, ids: [] });
      }
      // UXF3 (U2-25), as in the engine: re-stringing deletes this inverter's released, unreused strings (wholly inside
      // the pool) so their modules can form the new strings.
      if (cmd.parameters.release_modules) {
        const dropped = mine.filter((x) => !kept.has(x) && !x.target_mppt_instance_id && x.module_instance_ids.every(fieldOk));
        for (const d of dropped) for (const m of d.module_instance_ids) owner.delete(m);
        strings = strings.filter((x) => !dropped.includes(x));
      }
      const unstrung = orderModules(ctx, [...ctx.modules.values()].filter((m) => m.enabled && !owner.has(m.id) && fieldOk(m.id)).map((m) => m.id), "row_major");
      const poolModules = [...unstrung];
      // Reserve constrained pools first; create IDs and append strings in the original MPPT order below.
      const allocation = restricted ? [...fresh].sort((a, b) => Number(sourceOf(a.mppt) === null) - Number(sourceOf(b.mppt) === null)) : fresh;
      for (const w of allocation) {
        const available = restricted ? unstrung.filter(id => inSource(id, w.mppt)) : unstrung;
        if (available.length < w.n) {
          const held = new Set(mine.filter(s => !kept.has(s) && !s.target_mppt_instance_id && s.module_instance_ids.every(fieldOk)).flatMap(s => s.module_instance_ids));
          const totalAvailable = new Set([...poolModules, ...held, ...strings.filter(s => kept.has(s) || (s.target_mppt_instance_id && inv.mppt_instance_ids.includes(s.target_mppt_instance_id))).flatMap(s => s.module_instance_ids)]);
          let message = `not enough unstrung modules: this layout needs ${layout.flat().reduce((a, b) => a + b, 0)} modules; ${totalAvailable.size} are available for ${inv.name || inverter_instance_id}.`;
          if (restricted) message += ` MPPT ${inv.mppt_instance_ids.indexOf(w.mppt) + 1} source fields ${(sourceOf(w.mppt) ?? pv_field_ids).join(", ") || "any"} need ${layout[inv.mppt_instance_ids.indexOf(w.mppt)].reduce((a, b) => a + b, 0)} modules; ${[...totalAvailable].filter(id => inSource(id, w.mppt)).length} are available.`;
          message += " Use fewer or shorter strings.";
          if (!cmd.parameters.release_modules && held.size) message += ` Its current strings hold ${held.size} of them; apply from the Systems table or the Electrical step to re-use them.`;
          fail(message);
        }
        const chosen = available.slice(0, w.n);
        for (const id of chosen) unstrung.splice(unstrung.indexOf(id), 1);
        w.ids = chosen;
      }
      for (const w of fresh) {
        const s: DemoString = { string_id: newId(), module_instance_ids: w.ids, target_mppt_instance_id: null, enabled: false };
        assign(s, w.mppt);
        strings.push(s);
      }
      break;
    }
    case "set_orientation_tolerance":
    case "set_orientation_override":
    case "set_inverter_pairing":
      break; // strings unchanged: applyDesignCommand changes the design
    default: {
      const never: never = cmd;
      fail(`Unknown command ${(never as { command_type: string }).command_type}.`);
    }
  }
  const report = consistencyReport({ ...ctx, strings });
  const error = report.findings.find((f) => f.severity === "error");
  if (error) fail(`Refused: ${error.message}`);
  return strings;
}

export interface DemoFinding {
  severity: "error" | "draft";
  code: string;
  entity_id: string;
  message: string;
}

/** The engine's consistency report rules that apply to the demo model. */
export function consistencyReport(ctx: Pick<TopologyContext, "inverters" | "strings" | "modules">) {
  const findings: DemoFinding[] = [];
  const mppts = new Set(ctx.inverters.flatMap((i) => i.mppt_instance_ids));
  const membership = new Map<string, string[]>();
  for (const s of ctx.strings) {
    if (!s.module_instance_ids.length) findings.push({ severity: "error", code: "string_empty", entity_id: s.string_id, message: `${s.string_id} has no modules.` });
    for (const m of s.module_instance_ids) {
      membership.set(m, [...(membership.get(m) ?? []), s.string_id]);
      if (!ctx.modules.has(m)) findings.push({ severity: "error", code: "string_unknown_module", entity_id: s.string_id, message: `${s.string_id} references unknown module ${m}.` });
    }
    if (s.target_mppt_instance_id === null) {
      if (s.enabled) findings.push({ severity: "error", code: "enabled_string_unassigned", entity_id: s.string_id, message: `${s.string_id} is enabled but has no MPPT.` });
      else findings.push({ severity: "draft", code: "string_unassigned", entity_id: s.string_id, message: `${s.string_id} is not yet assigned to an MPPT.` });
    } else if (!mppts.has(s.target_mppt_instance_id))
      findings.push({ severity: "error", code: "string_unknown_mppt", entity_id: s.string_id, message: `${s.string_id} targets unknown MPPT ${s.target_mppt_instance_id}.` });
  }
  for (const [m, owners] of membership)
    if (owners.length > 1) findings.push({ severity: "error", code: "module_in_multiple_strings", entity_id: m, message: `Module ${m} belongs to ${owners.join(", ")}.` });
  findings.sort((a, b) => (a.severity === b.severity ? a.code.localeCompare(b.code) || a.entity_id.localeCompare(b.entity_id) : a.severity === "error" ? -1 : 1));
  return { blocking_count: findings.filter((f) => f.severity === "error").length, draft_count: findings.filter((f) => f.severity === "draft").length, findings };
}

/** Live checks per string (B6). Demo basis: STC values and a fixed cold factor; the engine uses the site's design temperatures. */
export function liveChecks(ctx: TopologyContext): TopologyChecks {
  const out: StringCheck[] = [];
  const onMppt = new Map<string, DemoString[]>();
  for (const s of ctx.strings) if (s.target_mppt_instance_id) onMppt.set(s.target_mppt_instance_id, [...(onMppt.get(s.target_mppt_instance_id) ?? []), s]);
  const moduleOf = (s: DemoString) => {
    const f = ctx.fields.get(ctx.modules.get(s.module_instance_ids[0] ?? "")?.fieldId ?? "");
    return f ? { e: DEMO_MODULE_ELECTRICAL[f.module], f } : null;
  };
  for (const s of ctx.strings) {
    const n = s.module_instance_ids.length;
    const mod = moduleOf(s);
    const inv = s.target_mppt_instance_id ? ctx.inverters.find((i) => i.mppt_instance_ids.includes(s.target_mppt_instance_id!)) : undefined;
    const ie = inv ? DEMO_INVERTER_ELECTRICAL[inv.inverter_definition_revision_id] : undefined;
    const checks: LiveCheck[] = [];
    const vmp = mod?.e ? n * mod.e.vmp : null;
    if (!ie || vmp === null) checks.push({ code: "voltage_window", state: "unavailable", message: inv ? "No electrical data for this module or inverter." : "Not assigned to an MPPT." });
    else {
      const ok = vmp >= ie.window[0] && vmp <= ie.window[1];
      checks.push({ code: "voltage_window", state: ok ? "pass" : "fail", message: `Vmp ${vmp.toFixed(0)} V ${ok ? "inside" : "outside"} the MPPT window ${ie.window[0]}–${ie.window[1]} V.` });
      const voc = n * mod!.e.voc * DEMO_COLD_FACTOR;
      checks.push({ code: "max_voltage", state: voc <= ie.maxDc ? "pass" : "fail", message: `Cold Voc ${voc.toFixed(0)} V (demo: STC × ${DEMO_COLD_FACTOR}) against ${ie.maxDc} V maximum.` });
      const peers = onMppt.get(s.target_mppt_instance_id!) ?? [];
      const amps = peers.reduce((t, x) => t + (moduleOf(x)?.e?.imp ?? 0), 0);
      checks.push({ code: "current", state: amps <= ie.maxInputA ? "pass" : "fail", message: `MPPT current ${amps.toFixed(1)} A of ${ie.maxInputA} A.` });
      const lengths = new Set(peers.map((x) => x.module_instance_ids.length));
      checks.push({ code: "unequal_lengths", state: lengths.size > 1 ? "warn" : "pass", message: lengths.size > 1 ? `Parallel strings of unequal length on this MPPT: ${[...lengths].sort((a, b) => a - b).join(", ")}.` : "Equal lengths on this MPPT." });
      let spread = 0;
      const fs = peers.map((x) => moduleOf(x)?.f).filter(Boolean) as Array<{ tilt: number; azimuth: number }>;
      for (const a of fs) for (const b of fs) spread = Math.max(spread, normalAngleDeg(a.tilt, a.azimuth, b.tilt, b.azimuth));
      const tol = tolerance(ctx);
      const accepted = ctx.orientation_policy?.overrides?.find((o) => o.mppt_instance_id === s.target_mppt_instance_id);
      checks.push(spread <= tol ? { code: "orientation", state: "pass", message: "One orientation on this MPPT." }
        : accepted ? { code: "orientation", state: "pass", message: `Mixed orientation accepted by override: ${accepted.reason}` }
        : { code: "orientation", state: "warn", message: `Strings on this MPPT face ${spread.toFixed(1)}° apart (more than ${tol}°).` });
      checks.push({ code: "inputs", state: peers.length > ie.inputs ? "fail" : "pass", message: `${peers.length} of ${ie.inputs} DC inputs used.` });
      const paired = inv?.paired_pv_field_ids ?? [];
      const outside = [...new Set(s.module_instance_ids.map((id) => ctx.modules.get(id)?.fieldId ?? "").filter((f) => paired.length && !paired.includes(f)))];
      checks.push(!paired.length ? { code: "pairing", state: "pass", message: "The inverter has no paired fields." }
        : outside.length ? { code: "pairing", state: "warn", message: `Modules outside the inverter's paired fields: ${outside.join(", ")}.` }
        : { code: "pairing", state: "pass", message: "All modules are in the inverter's paired fields." });
    }
    out.push({ string_id: s.string_id, vmp_v: vmp, window_v: ie ? ie.window : null, checks });
  }
  return { basis: `demo: STC values; cold Voc = STC × ${DEMO_COLD_FACTOR}; orientation tolerance ${tolerance(ctx)}° between module normals`, strings: out };
}
