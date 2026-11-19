import { beforeEach, expect, it } from "vitest";
import { demoDesignFingerprint, mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { buildResultModel, checkResultRules, dcCapacityKwp, EarlierDesignError, inverterResultRows, reportModel, runDesignBasis } from "../../src/results/model";
import type { ProjectView, SimulationRunRecord } from "../../src/types";

// RES1: a saved run is shown against the current design only when it simulated that design.
let view: ProjectView;
beforeEach(async () => { setDemoLatency(0); view = structuredClone(await mockApi.project("demo-project")); });
const opts = { authority: "ENGINE" as const, hourlyAcKw: null };
const withBasis = (v: ProjectView, fingerprint: string | undefined): { v: ProjectView; run: SimulationRunRecord } => {
  const copy = structuredClone(v), run = copy.bundle.simulation_runs[0];
  run.design_fingerprint = fingerprint;
  return { v: copy, run };
};

it("is current only when both fingerprints exist and match", () => {
  const run = view.bundle.simulation_runs[0];
  expect(view.design_fingerprint).toBeTruthy();
  expect(runDesignBasis(view, run)).toBe("current");
  expect(runDesignBasis(view, { ...run, design_fingerprint: "sha256:other" })).toBe("earlier");
  expect(runDesignBasis(view, { ...run, design_fingerprint: undefined })).toBe("unknown");
  expect(runDesignBasis(view, { ...run, design_fingerprint: null })).toBe("unknown");
  expect(runDesignBasis({ ...view, design_fingerprint: undefined }, run)).toBe("unknown");
});

it("a current run keeps today's design-derived figures", () => {
  const run = view.bundle.simulation_runs[0];
  expect(run.summary_result!.execution_breakdown).toBeUndefined();
  const m = buildResultModel(view, run, opts);
  expect(m.designBasis).toBe("current");
  expect(m.dcKwp).toBe(dcCapacityKwp(view));
  expect(m.acKw).toBeGreaterThan(0);
  expect(m.topology.length).toBeGreaterThan(0);
  expect(m.inverters.length).toBeGreaterThan(0);
});

it.each(["sha256:earlier", undefined])("an earlier or unknown run (%s) never shows current capacity, topology or orientation", (fingerprint) => {
  const { v, run } = withBasis(view, fingerprint);
  const summary = run.summary_result!;
  delete summary.resolved_loss_settings;
  const m = buildResultModel(v, run, opts);
  expect(m.designBasis).toBe(fingerprint ? "earlier" : "unknown");
  expect(m.dcKwp).toBeNull(); expect(m.acKw).toBeNull();
  expect(m.topology).toEqual([]); expect(m.inverters).toEqual([]); expect(m.unassigned).toEqual([]);
  expect(inverterResultRows(v, run)).toEqual([]);
  const rules = checkResultRules(m, { strings: v.bundle.electrical_design.strings.length });
  expect(rules.find((r) => r.id === "S01.dc-quantity")).toMatchObject({ state: "unavailable" });
  expect(rules.find((r) => r.id === "S06.a06")).toMatchObject({ state: "unavailable" });
  // Saved run figures are still shown.
  expect(m.periodAcKwh).toBe(summary.total_energy_wh / 1000);
  expect(m.specificYield).toBe(summary.specific_yield_wh_per_wp);
});

it("an earlier run uses only capacity saved with it", () => {
  const { v, run } = withBasis(view, "sha256:earlier");
  run.summary_result!.resolved_loss_settings = { ...(run.summary_result!.resolved_loss_settings ?? {}), simulated_dc_nameplate_w: 4321 } as never;
  expect(buildResultModel(v, run, opts).dcKwp).toBe(4.321);
  run.summary_result!.execution_breakdown = { schema_version: "0.1", simulated_dc_nameplate_w: 5000, plant_poa_basis: "simulated_dc_nameplate_weighted",
    inverters: [{ inverter_instance_id: "A", name: "INV-A", inverter_revision_id: "A", simulated_dc_nameplate_w: 5000, nominal_ac_power_w: 4000,
      total_energy_wh: 1, annual_energy_wh: null, specific_yield_wh_per_wp: 1, performance_ratio: 1, monthly_energy: [], clipping_energy_wh: 0,
      voltage_threshold_energy_wh: 0, startup_threshold_energy_wh: 0, conversion_energy_wh: 0, self_consumption_energy_wh: 0, loss_summary: [] }],
    groups: [], group_timeseries_reference: {}, inverter_timeseries_reference: {} };
  const m = buildResultModel(v, run, opts);
  expect([m.dcKwp, m.acKw]).toEqual([5, 4]);
  expect(inverterResultRows(v, run).map((r) => r.name)).toEqual(["INV-A"]);
  expect(m.topology).toEqual([]);
});

it.each([["sha256:earlier", "earlier"], [undefined, "unknown"]] as const)("the report refuses a %s run before building", (fingerprint, basis) => {
  const { v, run } = withBasis(view, fingerprint);
  let error: unknown;
  try { reportModel(v, run.simulation_run_id, opts); } catch (e) { error = e; }
  expect(error).toBeInstanceOf(EarlierDesignError);
  expect((error as EarlierDesignError).basis).toBe(basis);
  expect(() => reportModel(view, view.bundle.simulation_runs[0].simulation_run_id, opts)).not.toThrow(EarlierDesignError);
});

it("the demo fingerprint is canonical and ignores only project labels and envelopes", () => {
  const value = demoDesignFingerprint(view.bundle);
  const reordered = structuredClone(view.bundle);
  reordered.scene = Object.fromEntries(Object.entries(reordered.scene).reverse()) as typeof reordered.scene;
  reordered.project = { ...reordered.project, name: "Renamed", description: "Other" };
  reordered.scene.revision_id = "other-revision";
  reordered.simulation_runs = [];
  expect(demoDesignFingerprint(reordered)).toBe(value);
  const moved = structuredClone(view.bundle);
  moved.project.site.latitude_deg += 0.1;
  expect(demoDesignFingerprint(moved)).not.toBe(value);
});

it("a demo edit marks the run earlier and the demo undo brings it back", async () => {
  const run = view.bundle.simulation_runs[0];
  const edited = await mockApi.sceneCommand("demo-project", { command_type: "draw_polygon", target_entity_ids: [], parameters: { name: "Added roof", surface_type: "flat_roof", vertices: [[60, 0], [64, 0], [64, 3], [60, 3]], base_elevation_m: 3 } });
  expect(runDesignBasis(edited, run)).toBe("earlier");
  const undone = await mockApi.undo("demo-project", { expected_project_revision_id: edited.bundle.project.project_revision.project_revision_id, expected_entry_id: "demo" });
  expect(runDesignBasis(undone, run)).toBe("current");
});
