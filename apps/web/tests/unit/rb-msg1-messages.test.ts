import { expect, it } from "vitest";
import { applyTopologyCommand, type TopologyContext } from "../../src/demo/topologyEngine";

function ownerContext(): TopologyContext {
  const mppts = Array.from({ length: 13 }, (_, i) => `p${i}`);
  return {
    inverters: [{ inverter_instance_id: "inv-02", inverter_definition_revision_id: "inv-demo-100k", name: "INV-02", enabled: true, mppt_instance_ids: mppts }],
    strings: mppts.map((mppt, i) => ({ string_id: `s${i}`, target_mppt_instance_id: mppt, enabled: true,
      module_instance_ids: Array.from({ length: 14 }, (_, j) => `m${i * 14 + j}`) })),
    modules: new Map(Array.from({ length: 182 }, (_, i) => [`m${i}`, { id: `m${i}`, fieldId: "field-1", centre: [i, 0], enabled: true, slot: null }])),
    fields: new Map([["field-1", { module: "mod-demo-550", tilt: 0, azimuth: 0 }]]), tables: [],
  };
}

it.each([false, true])("mirrors the owner's shortage totals (release_modules=%s)", release => {
  for (const restricted of [false, true]) {
    const ctx = ownerContext(), before = structuredClone(ctx);
    let message = "not enough unstrung modules: this layout needs 234 modules; 182 are available for INV-02.";
    if (restricted) message += ` MPPT ${release ? 11 : 1} source fields field-1 need 18 modules; 182 are available.`;
    message += " Use fewer or shorter strings.";
    if (!release) message += " Its current strings hold 182 of them; apply from the Systems table or the Electrical step to re-use them.";
    expect(() => applyTopologyCommand(ctx, { command_type: "apply_mppt_layout", parameters: {
      inverter_instance_id: "inv-02", layout: Array.from({ length: 13 }, () => [18]), release_modules: release,
      ...(restricted ? { sources: Array.from({ length: 13 }, () => ["field-1"]) } : {}),
    } })).toThrow(message);
    expect(ctx).toEqual(before);
  }
});

it.each([false, true])("counts source fields separately within the inverter pool (restricted pool=%s)", pool => {
  const original = ownerContext();
  const ctx: TopologyContext = { ...original, strings: [],
    modules: new Map([...original.modules].map(([id, m], i) => [id, { ...m, fieldId: i < 14 ? "field-1" : "field-2", enabled: i !== 0 }])),
    fields: new Map([...original.fields, ["field-2", { module: "mod-demo-550", tilt: 0, azimuth: 0 }]]),
  };
  expect(() => applyTopologyCommand(ctx, { command_type: "apply_mppt_layout", parameters: {
    inverter_instance_id: "inv-02", layout: Array.from({ length: 13 }, (_, i) => [i === 0 ? 18 : 0]),
    sources: Array.from({ length: 13 }, (_, i) => i === 0 ? ["field-1"] : null),
    ...(pool ? { pv_field_ids: ["field-1"] } : {}),
  } })).toThrow(`not enough unstrung modules: this layout needs 18 modules; ${pool ? 13 : 181} are available for INV-02. MPPT 1 source fields field-1 need 18 modules; 13 are available. Use fewer or shorter strings.`);
});
