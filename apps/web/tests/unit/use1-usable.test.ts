import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { api } from "../../src/api";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { parseNotation } from "../../src/electrical/notation";
import { plainFindings } from "../../src/electrical/readinessText";
import { buildResultModel } from "../../src/results/model";
import { engineDesignBlockers } from "../../src/state/derived";
import type { ProjectView } from "../../src/types";
import { pickable } from "../../src/ui/testComponents";

// USE1: the notation's help, test-component filtering, plain readiness, the engine design blockers, the run's own DC
// basis, and the requests of the new routes.

let view: ProjectView;
beforeAll(async () => {
  setDemoLatency(0);
  view = await mockApi.project("demo-project");
});

describe("notation help", () => {
  it("shows the right form for a slash and for 16x2", () => {
    expect(parseNotation("16x2/16").issues[0].message).toBe('Write it as "16,16 ; 16": commas separate the strings on one MPPT, semicolons separate MPPTs.');
    expect(parseNotation("16 x 3 ; 14").issues[0].message).toContain('"16,16,16 ; 14"');
    expect(parseNotation("abc").issues[0].message).toContain("Example: 16,16 ; 16");
    expect(parseNotation("3x(16,0)").layout?.mppts).toEqual([[16, 0], [16, 0], [16, 0]]);
  });
});

describe("pickable components", () => {
  const items = [
    { revision_id: "real", synthetic_reference: false },
    { revision_id: "test", synthetic_reference: true },
    { revision_id: "old", synthetic_reference: false, superseded_by: "real" }
  ];
  it("hides test components unless shown, never offers a superseded revision, and keeps the current choice", () => {
    expect(pickable(items, false).map((c) => c.revision_id)).toEqual(["real"]);
    expect(pickable(items, true).map((c) => c.revision_id)).toEqual(["real", "test"]);
    expect(pickable(items, false, "old").map((c) => c.revision_id)).toEqual(["real", "old"]);
  });
});

describe("readiness in plain words", () => {
  it("names the inverter once for its data gaps, and keeps the rule as evidence", () => {
    const inv = view.bundle.electrical_design.inverter_instances[0];
    const found = plainFindings([
      { rule_id: "INVERTER_BASIC_DESIGN_READY_FALSE", severity: "blocking_error", category: "design_validation", entity_id: inv.inverter_instance_id, message: "basic" },
      { rule_id: "INVERTER_MPPT_DESIGN_READY_FALSE", severity: "blocking_error", category: "design_validation", entity_id: inv.inverter_instance_id, message: "mppt" },
      { rule_id: "EXECUTION_WEATHER_REVISION_REQUIRED", severity: "blocking_error", category: "weather", entity_id: null, message: "w" },
      { rule_id: "SOMETHING_ELSE", severity: "blocking_error", category: "x", entity_id: null, message: "raw" }
    ], view);
    expect(found.map((f) => [f.key, f.rule_id])).toEqual([
      ["use1.plain.inverterData", "INVERTER_BASIC_DESIGN_READY_FALSE"], ["use1.plain.noWeather", "EXECUTION_WEATHER_REVISION_REQUIRED"], ["", "SOMETHING_ELSE"]]);
    expect(found[0]).toMatchObject({ values: { name: inv.name }, inverterRevisionId: inv.inverter_definition_revision_id });
  });
});

describe("engine design blockers", () => {
  it("a layout-only inverter, an inverter without strings and a failed engine check keep Electrical from valid", () => {
    const v = structuredClone(view);
    const inv = v.bundle.electrical_design.inverter_instances[0];
    expect(engineDesignBlockers(v)).toEqual([]);
    v.catalog.inverters.find((c) => c.revision_id === inv.inverter_definition_revision_id)!.simulation_ready = false;
    v.topology_view.inverters[0].mppts.forEach((m) => { m.strings = []; });
    v.topology_checks = { basis: "x", strings: [{ string_id: "S9", vmp_v: null, window_v: null, checks: [{ code: "max_voltage", state: "fail", message: "Voc too high" }] }] };
    expect(engineDesignBlockers(v).map((f) => f.id)).toEqual([`layout-only-${inv.inverter_instance_id}`, `no-strings-${inv.inverter_instance_id}`, "check-S9-max_voltage"]);
  });
});

describe("the run's own DC basis (R2)", () => {
  it("specific yield is checked against the simulated nameplate, not the placed modules", () => {
    const v = structuredClone(view);
    const run = v.bundle.simulation_runs[0];
    run.summary_result!.resolved_loss_settings = { ...(run.summary_result!.resolved_loss_settings ?? {}), simulated_dc_nameplate_w: 12_345 } as never;
    delete (run.summary_result as { execution_breakdown?: unknown }).execution_breakdown;
    expect(buildResultModel(v, run, { authority: "DEMO_SYNTHETIC", hourlyAcKw: null }).dcKwp).toBe(12.345);
  });
});

describe("requests", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("remove, change, suggest, pitch, the dry run and the one-commit restring", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })));
    vi.stubGlobal("fetch", fetch);
    await api.removeInverter("p 1", "inv#1");
    expect([fetch.mock.calls[0][0], fetch.mock.calls[0][1].method]).toEqual(["/api/projects/p%201/inverters/inv%231", "DELETE"]);
    await api.changeInverter("p", "i", "rev-2");
    expect([fetch.mock.calls[1][1].method, JSON.parse(fetch.mock.calls[1][1].body)]).toEqual(["PUT", { inverter_definition_revision_id: "rev-2" }]);
    await api.suggestLayout("p", "i", []);
    expect([fetch.mock.calls[2][0], JSON.parse(fetch.mock.calls[2][1].body)]).toEqual(["/api/projects/p/inverters/i/suggest-layout", { pv_field_ids: null }]);
    await api.shadingFreePitch("p", { module_definition_revision_id: "m", orientation: "portrait", tilt_deg: 10, design_sun_elevation_deg: 30, sun_azimuth_offset_deg: 0 });
    expect(fetch.mock.calls[3][0]).toBe("/api/projects/p/pv-fields/shading-free-pitch");
    await api.electricalDryRun("p", [{ command_type: "delete_strings", parameters: { string_ids: ["S1", "S2"] } }, { command_type: "apply_mppt_layout", parameters: { inverter_instance_id: "i", layout: [[10]] } }]);
    const dry = JSON.parse(fetch.mock.calls[4][1].body);
    expect(dry.dry_run).toBe(true);
    expect(dry.commands.map((c: { command_type: string; parameters: unknown }) => [c.command_type, c.parameters])).toEqual([
      ["delete_string", { string_id: "S1" }], ["delete_string", { string_id: "S2" }], ["apply_mppt_layout", { inverter_instance_id: "i", layout: [[10]] }]]);
    await api.applyLayoutReplacing("p", "i", [[10], [10]], ["f"], ["S1"]);
    const batch = JSON.parse(fetch.mock.calls[5][1].body);
    expect(batch.dry_run).toBeUndefined();
    expect(batch.commands.map((c: { command_type: string }) => c.command_type)).toEqual(["delete_string", "apply_mppt_layout"]);
  });
});
