import { expect, test } from "@playwright/test";
import { openSection } from "../e2e/sections";
import { execFileSync } from "node:child_process";
import path from "node:path";
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("RES1 requires the disposable test API, never var/projects.");
const ROOT = path.resolve(process.cwd(), "../..");

test("a run is marked as an earlier design after an edit, and undo brings it back", async ({ page, request }) => {
  const name = `RES1 basis ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true); const id: string = (await created.json()).bundle.project.project_id;
  const url = `${API}/api/projects/${id}`;
  const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "Basis roof", width_m: 1 + 18 * 1.154 - .01, height_m: 3.45, base_elevation_m: 6.1 } });
  expect(roof.ok()).toBe(true);
  const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id;
  expect((await request.post(url + "/pv-fields", { data: { name: "Basis array", support_surface_id: sid, module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: 10, row_pitch_m: 3.2, perimeter_setback_m: .5 } })).ok()).toBe(true);
  const inverter = await request.post(url + "/inverters", { data: { name: "Basis inverter", inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1" } });
  expect(inverter.ok()).toBe(true); const iid = (await inverter.json()).bundle.electrical_design.inverter_instances[0].inverter_instance_id;
  const strings = await request.post(url + "/strings", { data: { string_length: 18, allow_shorter_remainder: false } });
  expect(strings.ok()).toBe(true); const ids = (await strings.json()).bundle.electrical_design.strings.map((s: { string_id: string }) => s.string_id);
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
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();

  await page.keyboard.press("Alt+9");
  const simulated = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/simulate`) && r.request().method() === "POST");
  const run = page.getByRole("button", { name: "Validate and run", exact: true }); await expect(run).toBeEnabled(); await run.click();
  const record = await (await simulated).json();
  expect(record.design_fingerprint).toMatch(/^sha256:[0-9a-f]{64}$/);
  await page.keyboard.press("Alt+0");
  await expect(page.locator(".kpis")).toBeVisible();
  await expect(page.locator("[data-design-basis]")).toHaveCount(0);

  await page.keyboard.press("Alt+8");
  await openSection(page, "Losses");
  const panel = page.locator("[data-loss-settings]");
  await panel.getByLabel("Soiling month 1 (%)", { exact: true }).fill("8");
  const saving = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/losses`) && r.request().method() === "PATCH");
  await panel.getByRole("button", { name: "Save losses", exact: true }).click(); expect((await saving).status()).toBe(200);

  await page.keyboard.press("Alt+0");
  await expect(page.locator('[data-design-basis="earlier"]')).toContainText("These results are from an earlier design. Run again to update.");
  await expect(page.locator("[data-design-basis-hidden]")).toHaveCount(0);
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await expect(page.locator('[data-report-design-basis="earlier"]')).toBeVisible();
  await page.getByRole("button", { name: "Preview report", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("This run is from an earlier design. Run the simulation again to make a report.");
  await expect(page.locator(".report-frame")).toHaveCount(0);

  await page.keyboard.press("Alt+8");
  const undone = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/undo`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "Undo", exact: true }).first().click(); expect((await undone).status()).toBe(200);
  await expect(panel.getByLabel("Soiling month 1 (%)", { exact: true })).toHaveValue("3");
  await page.keyboard.press("Alt+0");
  await expect(page.locator(".kpis")).toBeVisible();
  await expect(page.locator("[data-design-basis]")).toHaveCount(0);
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await expect(page.locator("[data-report-design-basis]")).toHaveCount(0);
  const stored = (await (await request.get(url)).json());
  expect(stored.design_fingerprint).toBe(record.design_fingerprint);
  expect(stored.bundle.simulation_runs.at(-1).design_fingerprint).toBe(record.design_fingerprint);
  expect(errors).toEqual([]);
});
