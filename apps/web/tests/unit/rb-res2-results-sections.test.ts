import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import i18n from "../../src/i18n";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { ResultsView } from "../../src/results/ResultsView";
import type { ProjectView } from "../../src/types";

const screen = vi.hoisted(() => ({ view: null as ProjectView | null }));
vi.mock("../../src/state/store", async load => ({ ...await load<typeof import("../../src/state/store")>(),
  useStore: () => ({ state: { view: screen.view, busy: null }, dispatch: vi.fn(), toast: vi.fn(), run: vi.fn() }),
  useForm: (_key: string, initial: unknown) => [initial, vi.fn()]
}));
beforeEach(async () => {
  setDemoLatency(0);
  screen.view = structuredClone(await mockApi.project("demo-project"));
  screen.view.bundle.simulation_runs = [screen.view.bundle.simulation_runs[0]];
  screen.view.bundle.simulation_runs[0].readiness_warnings = [];
});
afterEach(async () => { vi.unstubAllGlobals(); await i18n.changeLanguage("en"); });
const render = () => renderToStaticMarkup(createElement(ResultsView));
const sections = (html: string) => [...html.matchAll(/class="section__toggle"[^>]*aria-expanded="(true|false)"[^>]*><span[^>]*>[^<]*<\/span>([^<]*)<\/button>/g)].map(m => ({ title: m[2], open: m[1] === "true" }));

it.each(["en", "id"])("puts KPIs, default Monthly chart, then closed detail sections in order (%s)", async locale => {
  await i18n.changeLanguage(locale);
  const before = JSON.stringify(screen.view);
  const html = render();
  const titles = ["results.checksTitle", "s15.launchWarnings", "results.pxxSection", "results.invertersSection", "results.settingsSection"].map(key => i18n.t(key));
  expect(sections(html)).toEqual(titles.map(title => ({ title, open: false })));
  expect(html.indexOf('class="kpis"')).toBeLessThan(html.indexOf('class="results__tabs"'));
  expect(html.indexOf('class="results__tabs"')).toBeLessThan(html.indexOf(`data-chart="${i18n.t("results.monthlyAria")}"`));
  expect(html.indexOf(`data-chart="${i18n.t("results.monthlyAria")}"`)).toBeLessThan(html.indexOf('class="section section--closed"'));
  expect(html).not.toContain("data-annual-pxx");
  expect(html).not.toContain("data-inverter-result");
  expect(html).not.toContain(i18n.t("results.detailedSection"));
  expect(JSON.stringify(screen.view)).toBe(before);
});

it("opens Checks on rule failure and Launch warnings only when recorded warnings exist", () => {
  const run = screen.view!.bundle.simulation_runs[0];
  run.summary_result!.annual_energy_wh = -1;
  run.readiness_warnings = [{ rule_id: "recorded-warning", severity: "warning", entity_id: null, message: "Recorded launch warning" }];
  const html = render();
  expect(sections(html).slice(0, 2)).toEqual([
    { title: i18n.t("results.checksTitle"), open: true }, { title: i18n.t("s15.launchWarnings"), open: true }
  ]);
  expect(html).toContain("S03.annual-energy-available");
  expect(html).toContain("Recorded launch warning");
  run.readiness_warnings = undefined;
  expect(sections(render())[1].open).toBe(false);
});

it("adds the closed detailed section last only with attribution, keeping execution status above KPIs", () => {
  const run = screen.view!.bundle.simulation_runs[0];
  const artifact = { status: "unavailable", artifact: null, sha256: null, model_id: null, unavailable_reason_codes: [] };
  run.detailed_electrical_shading = {
    execution_identity: { requested_fidelity: null, resolved_fidelity: null, runtime_support_result: "pcc_complete", limitations: [], failure_reasons: [], fallback_reason: null, fallback_applied: false, fallback_policy: "fail_closed" },
    selected_mppt_result: artifact, dc_attribution_result: artifact, attribution_energy_result: artifact,
    attribution_energy_summary: { energy_summary_model_id: "recorded", energy_summary_model_version: "1", source_identity: { attribution_model_id: "recorded", attribution_model_version: "1" }, periods: [] },
    diagnostic_artifacts: { status: "unavailable", artifacts: [] }
  };
  const html = render();
  expect(sections(html)).toHaveLength(6);
  expect(sections(html).at(-1)).toEqual({ title: i18n.t("results.detailedSection"), open: false });
  expect(html.indexOf('aria-label="Electrical execution identity"')).toBeLessThan(html.indexOf('class="kpis"'));
  expect(html).not.toContain('class="panel-card detailed-shading"');
  run.detailed_electrical_shading.attribution_energy_summary = null;
  expect(sections(render())).toHaveLength(5);
});

it("keeps a previously opened section open through the existing Section storage", () => {
  vi.stubGlobal("window", { localStorage: { getItem: (key: string) => key === `rawibumi.section.${i18n.t("results.pxxSection")}` ? "1" : null } });
  expect(sections(render()).find(s => s.title === i18n.t("results.pxxSection"))?.open).toBe(true);
  expect(render()).toContain("data-annual-pxx");
});
