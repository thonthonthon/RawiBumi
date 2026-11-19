import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import i18n from "../../src/i18n";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { ResultsView } from "../../src/results/ResultsView";
import { renderReportDetails } from "../../src/report/render";
import type { ProjectView } from "../../src/types";

const screen = vi.hoisted(() => ({ view: null as ProjectView | null }));
vi.mock("../../src/state/store", async load => ({ ...await load<typeof import("../../src/state/store")>(),
  useStore: () => ({ state: { view: screen.view, busy: null }, dispatch: vi.fn(), toast: vi.fn(), run: vi.fn() }),
  useForm: (_key: string, initial: unknown) => [initial, vi.fn()]
}));
beforeAll(() => { setDemoLatency(0); });
afterEach(async () => { await i18n.changeLanguage("en"); });

it.each(["en", "id"] as const)("labels imported figures in Results and the shared report in %s, preserving numbers", async locale => {
  await i18n.changeLanguage(locale);
  const view = structuredClone(await mockApi.project("demo-project"));
  const run = view.bundle.simulation_runs[0];
  const source = structuredClone(await mockApi.reportSnapshot("demo-project", run.simulation_run_id));
  const label = locale === "en" ? "Imported: not computed by this installation" : "Diimpor: tidak dihitung oleh instalasi ini";
  screen.view = view;
  const localResults = renderToStaticMarkup(createElement(ResultsView));
  const localReport = renderReportDetails(source, { locale, planFigurePng: null });
  expect(localResults).not.toContain(label);
  expect(localReport.html).not.toContain(label);
  const summary = JSON.stringify(run.summary_result);
  Object.assign(run, { origin: "imported" });
  Object.assign(source.design_view.bundle.simulation_runs[0], { origin: "imported" });
  expect(renderToStaticMarkup(createElement(ResultsView))).toContain(label);
  const imported = renderReportDetails(source, { locale, planFigurePng: null });
  expect(imported.html).toContain(label);
  expect(imported.fingerprint).toBe(localReport.fingerprint);
  expect(JSON.stringify(run.summary_result)).toBe(summary);
  run.summary_result = null;
  expect(renderToStaticMarkup(createElement(ResultsView))).toContain(label);
});
