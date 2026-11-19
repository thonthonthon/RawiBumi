import { afterEach, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import i18n from "../../src/i18n";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { InverterResultsTable } from "../../src/results/ResultsView";
import type { InverterResultRow } from "../../src/results/model";

afterEach(async () => { await i18n.changeLanguage("en"); });
it.each([["en","Reference Production"],["id","Produksi Referensi"]])("labels Results production in %s, retaining numbers and the independent HTML-report label", async (locale, term) => {
  await i18n.changeLanguage(locale); setDemoLatency(0);
  const view=await mockApi.project("demo-project"), summary=view.bundle.simulation_runs[0].summary_result!;
  const row: InverterResultRow={id:"inv",name:"INV",dcKwp:1,energyKwh:12.345,specificYield:12.345,clippingKwh:0,voltageThresholdKwh:0,startupThresholdKwh:0};
  const html=renderToStaticMarkup(createElement(InverterResultsTable,{rows:[row],summary}));
  expect(html).toContain(`${term} (kWh)`);
  expect(html).toContain('data-inverter-energy-kwh="12.345"');
  for (const key of ["referenceProduction","referenceProductionPower","kpiPeriodEnergy","bPcc","mProduction","productionNote","delivered","hAc","acBefore","acAfter"]) {
    expect(i18n.t(`results.${key}`,{hours:24}),key).toContain(term);
  }
  expect(i18n.t("results.kpiEnergy")).toBe(locale==="en" ? "AC energy" : "Energi AC");
  expect(i18n.t("results.kpiPr")).toBe(locale==="en" ? "Performance ratio" : "Rasio kinerja");
});
