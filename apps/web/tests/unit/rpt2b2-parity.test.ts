import { afterAll, beforeAll, expect, it } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { mockApi, setDemoLatency } from "../../src/demo/mockApi";
import { renderReport } from "../../src/report/render";
import type { VerifiedReportSnapshot } from "../../src/report/snapshot";

const directory = mkdtempSync(join(tmpdir(), "rpt2b2-node-"));
let nodeRender: typeof renderReport;
beforeAll(async () => {
  execFileSync(process.execPath, [resolve("node_modules/vite/bin/vite.js"), "build", "--mode", "report", "--outDir", directory], { env: { ...process.env, NODE_ENV: "production" }, stdio: ["ignore", "pipe", "pipe"] });
  nodeRender = createRequire(import.meta.url)(join(directory, "report-render.cjs")).renderReport;
});
afterAll(() => rmSync(directory, { recursive: true, force: true }));
const content = (html: string) => html.slice(html.indexOf("<body")).replace(/<style[^>]*>[\s\S]*?<\/style>|<svg[\s\S]*?<\/svg>/g, "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
const chartData = (html: string) => {
  const attribute = html.match(/data-report-chart-data="([^"]*)"/);
  expect(attribute).not.toBeNull();
  return JSON.parse(attribute![1].replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&"));
};
it.each(["en", "id"] as const)("Node bundle and screen renderer preserve report text and actual chart series in %s", async locale => {
  setDemoLatency(0);
  const view = await mockApi.project("demo-project");
  const source: VerifiedReportSnapshot = await mockApi.reportSnapshot("demo-project", view.bundle.simulation_runs[0].simulation_run_id);
  const options = { locale, planFigurePng: null, watermark: "free_community" as const };
  const screen = renderReport(source, options), pdf = nodeRender(source, options);
  expect(content(pdf)).toBe(content(screen));
  const series = chartData(screen);
  expect(chartData(pdf)).toEqual(series);
  source.summary.monthly_energy.forEach((row, index) => expect(Math.abs(series.monthly[0].data[index] - row.energy_wh / 1000)).toBeLessThanOrEqual(0.000500001));
  expect(series.monthly[0].name).toBe(locale === "en" ? "Reference Production" : "Produksi Referensi");
});
