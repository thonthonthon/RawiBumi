import { beforeAll, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import i18n from "../../src/i18n";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { buildResultModel, inverterResultRows } from "../../src/results/model";
import { InverterResultsTable } from "../../src/results/ResultsView";
import type { InverterExecutionResult, ProjectView } from "../../src/types";

let view: ProjectView;
beforeAll(async () => { setDemoLatency(0); view = await mockApi.project("demo-project"); await i18n.changeLanguage("en"); });
function inverter(id: string, energy: number, dc: number): InverterExecutionResult {
  return { inverter_instance_id: id, name: `INV-${id}`, inverter_revision_id: id,
    simulated_dc_nameplate_w: dc, nominal_ac_power_w: 10000, total_energy_wh: energy,
    annual_energy_wh: null, specific_yield_wh_per_wp: energy / dc, performance_ratio: .8,
    monthly_energy: [], clipping_energy_wh: 1000, voltage_threshold_energy_wh: 200,
    startup_threshold_energy_wh: 100, conversion_energy_wh: 500, self_consumption_energy_wh: 20, loss_summary: [] };
}
function multi() {
  const v = structuredClone(view), run = v.bundle.simulation_runs[0], summary = run.summary_result!;
  summary.total_energy_wh = 12000; summary.specific_yield_wh_per_wp = 2.4; summary.clipping_energy_wh = 2000;
  summary.execution_breakdown = { schema_version: "0.1", simulated_dc_nameplate_w: 5000,
    plant_poa_basis: "simulated_dc_nameplate_weighted", inverters: [inverter("A", 4000, 2000), inverter("B", 8000, 3000)],
    groups: [], group_timeseries_reference: {}, inverter_timeseries_reference: {} };
  return { v, run, summary };
}
it("projects pinned per-inverter results without allocating the plant total or using the current design's capacity", () => {
  const { v, run } = multi(); const before = JSON.stringify(run);
  const rows = inverterResultRows(v, run);
  expect(rows.map((r) => [r.name, r.energyKwh, r.dcKwp])).toEqual([["INV-A", 4, 2], ["INV-B", 8, 3]]);
  const model = buildResultModel(v, run, { authority: "ENGINE", hourlyAcKw: null });
  expect(model.dcKwp).toBe(5); expect(model.acKw).toBe(20);
  expect(rows[1].specificYield).toBe(8000 / 3000);
  expect(JSON.stringify(run)).toBe(before);
});
it("renders both inverter energies and the authoritative plant yield, clipping and thresholds", () => {
  const { v, run, summary } = multi();
  const html = renderToStaticMarkup(createElement(InverterResultsTable, { rows: inverterResultRows(v, run), summary }));
  for (const text of ["Inverter results", "INV-A", "INV-B", "Plant total", "Voltage-window loss", "Startup loss"]) expect(html).toContain(text);
  expect(html).toContain('data-inverter-energy-kwh="4"'); expect(html).toContain('data-inverter-energy-kwh="8"');
  expect(html).toContain('data-plant-energy-kwh="12"');
  expect(html.split("<tfoot>")[1]).toContain("2.400");
});
it("derives a legacy singleton from the existing summary without adding fields to that summary", () => {
  const v = structuredClone(view), run = v.bundle.simulation_runs[0], summary = run.summary_result!;
  delete summary.execution_breakdown;
  v.bundle.electrical_design.inverter_instances.forEach((inv, i) => { inv.enabled = i === 0; });
  const before = JSON.stringify(summary), rows = inverterResultRows(v, run);
  expect(rows).toHaveLength(1); expect(rows[0].energyKwh).toBe(summary.total_energy_wh / 1000);
  expect(rows[0].specificYield).toBe(summary.specific_yield_wh_per_wp);
  expect(JSON.stringify(summary)).toBe(before);
});
it("never fabricates per-inverter energy for a legacy multi-inverter record", () => {
  const v = structuredClone(view), run = v.bundle.simulation_runs[0]; delete run.summary_result!.execution_breakdown;
  const inv = v.bundle.electrical_design.inverter_instances[0]; inv.enabled = true;
  v.bundle.electrical_design.inverter_instances.push({ ...inv, inverter_instance_id: "second-inverter", name: "Second" });
  expect(inverterResultRows(v, run)).toEqual([]);
});
