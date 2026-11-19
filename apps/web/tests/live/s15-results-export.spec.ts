import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { inflateRawSync } from "node:zlib";

// S15 on the real engine: the run keeps its launch readiness warning; Results draws losses, meteo, PR, the heatmap
// and daily profiles from the engine's stored series; the Export step downloads the full deliverable.
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("S15 requires the disposable test API, never var/projects.");
const ROOT = path.resolve(process.cwd(), "../..");

/** The stored (uncompressed) entries of a ZIP, by name. */
function unzip(buffer: Buffer): Map<string, Buffer> {
  const out = new Map<string, Buffer>();
  let at = 0;
  while (buffer.readUInt32LE(at) === 0x04034b50) {
    const method = buffer.readUInt16LE(at + 8), size = buffer.readUInt32LE(at + 18);
    const nameLength = buffer.readUInt16LE(at + 26), extra = buffer.readUInt16LE(at + 28);
    const name = buffer.subarray(at + 30, at + 30 + nameLength).toString();
    const data = buffer.subarray(at + 30 + nameLength + extra, at + 30 + nameLength + extra + size);
    out.set(name, method === 0 ? Buffer.from(data) : inflateRawSync(data));
    at += 30 + nameLength + extra + size;
  }
  return out;
}

test("a run's engine series drives Results, and the Export step downloads the full deliverable", async ({ page, request }) => {
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  const name = `S15 results ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true); const id: string = (await created.json()).bundle.project.project_id;
  const url = `${API}/api/projects/${id}`;
  // 19 modules in strings of 18: the 1-module remainder string stays unassigned, a non-blocking readiness warning.
  const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "Results roof", width_m: 1 + 19 * 1.154 - .01, height_m: 3.45, base_elevation_m: 6.1 } });
  const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id;
  expect((await request.post(url + "/pv-fields", { data: { name: "Results array", support_surface_id: sid, module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: 10, row_pitch_m: 3.2, perimeter_setback_m: .5 } })).ok()).toBe(true);
  const inverter = await request.post(url + "/inverters", { data: { name: "INV", inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1" } });
  const iid = (await inverter.json()).bundle.electrical_design.inverter_instances[0].inverter_instance_id;
  const strings = await request.post(url + "/strings", { data: { string_length: 18, allow_shorter_remainder: true } });
  expect(strings.ok(), await strings.text()).toBe(true);
  const ids = (await strings.json()).bundle.electrical_design.strings
    .filter((s: { module_instance_ids: string[] }) => s.module_instance_ids.length === 18).map((s: { string_id: string }) => s.string_id);
  expect((await request.post(url + "/assignments", { data: { inverter_instance_id: iid, string_ids: ids } })).ok()).toBe(true);
  execFileSync(path.join(ROOT, ".venv/bin/python"), ["-c", `
from pathlib import Path
import sys
from apps.api.server import create_app
root=Path(sys.argv[1]).resolve()
store=root/'tmp/live-projects'
assert store.is_dir() and store.resolve()==store
app=create_app(store_root=store,library_root=root/'tmp/component-library')
app.state.study_service.acquire_weather(sys.argv[2],source_id='open_meteo_archive_era5',start_date='2025-01-01',end_date='2025-01-01',raw_response=(root/'tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json').read_bytes())
`, ROOT, id], { cwd: ROOT, timeout: 30_000 });

  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+9");
  const simulated = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/simulate`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "Validate and run", exact: true }).click();
  const record = await (await simulated).json();
  expect(record.readiness_warnings.length).toBeGreaterThan(0);

  const series = page.waitForResponse((r) => r.url().endsWith(`/runs/${record.simulation_run_id}/timeseries`));
  await page.keyboard.press("Alt+0");
  expect((await series).status()).toBe(200);
  await expect(page.locator(".kpis")).toBeVisible();
  await expect(page.locator("[data-launch-warnings]")).toHaveAttribute("data-launch-warnings", String(record.readiness_warnings.length));
  // No demo stamp anywhere on the engine's views.
  await expect(page.locator(".demo-stamp")).toHaveCount(0);
  const kind = page.getByRole("radiogroup", { name: "Monthly quantity" });
  await kind.getByRole("radio", { name: "Losses" }).click();
  await expect(page.locator('[data-monthly-losses="ENGINE"] canvas, [data-monthly-losses="ENGINE"] svg').first()).toBeVisible();
  await kind.getByRole("radio", { name: "Meteo" }).click();
  await expect(page.locator('[data-monthly-meteo="ENGINE"]')).toBeVisible();
  await kind.getByRole("radio", { name: "Performance" }).click();
  await expect(page.locator("[data-monthly-pr]")).toBeVisible();
  await kind.getByRole("radio", { name: "Zero export" }).click();
  await expect(page.locator('[data-series-state="export_limit"]')).toBeVisible();

  const views = page.getByRole("radiogroup", { name: "Result views" });
  await views.getByRole("radio", { name: "Heatmap" }).click();
  await expect(page.locator("[data-coverage]")).toContainText("24");
  await expect(page.locator("[data-series-state]")).toHaveCount(0);
  await views.getByRole("radio", { name: "Daily profile" }).click();
  await expect(page.locator(".uplot, [data-month-uncovered]").first()).toBeVisible();
  await expect(page.locator(".uplot")).toBeVisible(); // January is the run's month

  // Export: CSV + Parquet, the full deliverable.
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  const panel = page.locator("[data-csv-export]");
  await expect(panel).toBeVisible();
  await panel.locator("[data-export-formats]").getByRole("checkbox", { name: "Parquet" }).check();
  const download = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Download CSV ZIP", exact: true }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("RawiBumi_results_bundle.zip");
  const entries = unzip(await readFile((await file.path())!));
  expect([...entries.keys()]).toEqual(["timeseries.csv", "timeseries.parquet", "monthly.csv", "summary-result.json",
    "design-validation-report.json", "validation-findings.json", "run-record.json", "export-manifest.json"]);
  const manifest = JSON.parse(entries.get("export-manifest.json")!.toString());
  for (const f of manifest.files) expect(createHash("sha256").update(entries.get(f.path)!).digest("hex")).toBe(f.sha256);
  expect(JSON.parse(entries.get("run-record.json")!.toString()).readiness_warnings).toEqual(record.readiness_warnings);
  expect(entries.get("monthly.csv")!.toString().split("\n")[1]).toMatch(/^2025-01,/);
  expect(errors).toEqual([]);
});
