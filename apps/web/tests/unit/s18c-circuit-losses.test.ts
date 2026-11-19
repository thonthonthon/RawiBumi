import { expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import i18n from "../../src/i18n";
import { acSegmentDraft, acSegmentValue, acSegmentErrors, circuitDraft, circuitFormPatch, circuitFormErrors, CircuitLossEditor, RunCircuitLosses } from "../../src/panels/LossesPanel";
import type { ProjectView, CircuitLossResolution } from "../../src/types";
import fixture from "./s7b-engine-fixture.json";
const view = () => {
  const v = structuredClone(fixture.views.before) as unknown as ProjectView;
  v.bundle.electrical_design.inverter_instances = [{ inverter_instance_id: "inv-circuit", inverter_definition_revision_id: "invented-inverter-r1", name: "Circuit inverter", enabled: true, mppt_instance_ids: ["mppt-circuit"] }];
  v.topology_view.inverters = [{ inverter_instance_id: "inv-circuit", inverter_definition_revision_id: "invented-inverter-r1", name: "Circuit inverter", enabled: true, mppts: [{ mppt_instance_id: "mppt-circuit", index: 1, strings: [] }] }];
  return v;
};

it("cable controls require explicit one-way, phase and editable assumed temperature inputs", () => {
  const draft = { ...acSegmentDraft(), mode: "cable" as const, length: "40", area: "120" };
  expect(draft.temperature).toBe("50");
  expect(acSegmentErrors(draft)).toEqual([]);
  expect(acSegmentValue(draft)).toMatchObject({ length_one_way_m: 40, cross_section_per_phase_mm2: 120, conductor_temperature_c: 50, phase_system: "balanced_three_phase", power_factor: 1 });
  expect(acSegmentErrors({ ...draft, temperature: "" })).toContain("temperature");
  expect(acSegmentValue({ ...draft, temperature: "70" })).toMatchObject({ conductor_temperature_c: 70 });
  expect(acSegmentErrors({ ...draft, area: "0" })).toContain("area");
});
it("percent mode uses an explicit named reference and validates custom power", () => {
  const draft = { ...acSegmentDraft(), mode: "percent" as const, fraction: "1.5", reference: "custom" as const, power: "80000" };
  expect(acSegmentValue(draft)).toEqual({ mode: "percent", loss_fraction: .015, reference: "custom", reference_power_w: 80000 });
  expect(acSegmentErrors({ ...draft, power: "" })).toContain("power");
  expect(acSegmentValue({ ...draft, reference: "rated_ac" })).toEqual({ mode: "percent", loss_fraction: .015, reference: "rated_ac" });
});
it("per-inverter and MPPT controls use IDs, signed fractions and explicit rebind metadata", () => {
  const v = view(), d = circuitDraft(v), iid = Object.keys(d.inverters)[0], mid = Object.keys(d.mppts)[0];
  expect(iid).toBeTruthy(); expect(mid).toBeTruthy();
  d.inverters[iid].dc = "1.08"; d.inverters[iid].quality = "-0.75"; d.mppts[mid].dc = "0";
  const patch = circuitFormPatch(v, d);
  expect(patch).toMatchObject({ overrides: { circuit_overrides: { binding: { electrical_revision_id: v.bundle.electrical_design.electrical_revision_id, topology_sha256: null }, inverters: { [iid]: { dc_wiring_stc_fraction: .0108, module_quality_fraction: -.0075 } }, mppts: { [mid]: { dc_wiring_stc_fraction: 0 } } } } });
  expect(circuitFormErrors(d)).toEqual([]);
  d.inverters[iid].quality = "-100"; expect(circuitFormErrors(d)).toContain(`${iid}.quality`);
  expect(circuitFormPatch(v, circuitDraft(v))).toEqual({ overrides: { circuit_overrides: null, plant_ac_wiring: null } });
});
it("the editable table and plant block are translated and visibly disabled while busy", async () => {
  for (const language of ["en", "id"]) {
    await i18n.changeLanguage(language);
    const html = renderToStaticMarkup(createElement(CircuitLossEditor, { view: view(), busy: true, save: async () => undefined }));
    expect(html).toContain(i18n.t("circuit.plantSegment")); expect(html).toContain(i18n.t("circuit.mpptOverrides"));
    expect(html).toContain("disabled"); expect(html).not.toMatch(/pvsyst|nist|schneider/i);
  }
});
it("selected-run circuit evidence renders its values without consulting today's project", async () => {
  await i18n.changeLanguage("en");
  const r = { schema_name: "CircuitLossResolution", schema_version: "0.1", active: true, requested_overrides: {}, binding: null, circuits: { m: { inverter_instance_id: "i", mppt_instance_id: "m", mppt_index: 1, dc_wiring_stc_fraction: .0108, dc_wiring_source: "inverter_override", module_quality_by_module: { mod: -.0075 }, module_quality_sources: { mod: "inverter_override" }, reference_voltage_v: 600, reference_current_a: 20, resistance_ohm: .324 } }, inverters: { i: { name: "Recorded inverter", nominal_ac_power_w: 100000, ac_wiring: { mode: "percent", loss_fraction: .02, reference: "custom", reference_power_w: 80000, quadratic_coefficient_per_w: .02 / 80000, active: true, source: "inverter_override" } } }, plant_ac_wiring: null } as CircuitLossResolution;
  const html = renderToStaticMarkup(createElement(RunCircuitLosses, { resolution: r }));
  expect(html).toContain("Recorded inverter"); expect(html).toContain("1.08"); expect(html).toContain("-0.75"); expect(html).toContain("80000");
});
