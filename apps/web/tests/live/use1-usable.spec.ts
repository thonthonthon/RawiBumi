import { expect, test as base } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import { once } from "node:events";
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import path from "node:path";

// USE1 on the real engine, the USE0 path: a layout-only inverter (a repository OND fixture) is placed, the card says
// so and completes it from datasheet values (test values only), the project switches to the completed revision, the
// engine suggests the stringing, the layout is applied, and the run completes. The library is global, so this file
// runs its own disposable API and store, as S12a does.
const SHARED = process.env.RAWIBUMI_API;
if (!SHARED || !/^http:\/\/127\.0\.0\.1:\d+$/.test(SHARED) || SHARED.endsWith(":8000")) throw new Error("USE1 requires the disposable test API, never var/projects.");
const ROOT = path.resolve(process.cwd(), "../..");

const test = base.extend<{}, { isolated: { api: string; directory: string } }>({
  isolated: [async ({}, use) => {
    mkdirSync(path.join(ROOT, "tmp"), { recursive: true });
    const directory = mkdtempSync(path.join(ROOT, "tmp", "use1-live-"));
    const script = `import runpy
from pathlib import Path
runpy.run_path("apps/web/scripts/serve-live-test-api.py",run_name="use1_test_catalog")
from apps.api.server import create_app
import uvicorn
uvicorn.run(create_app(store_root=Path(${JSON.stringify(directory)})/"projects",library_root=Path(${JSON.stringify(directory)})/"component-library"),host="127.0.0.1",port=0,timeout_keep_alive=75)
`;
    const child = spawn(path.join(ROOT, ".venv/bin/python"), ["-c", script], { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"] });
    let logs = "";
    try {
      const api = await new Promise<string>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`USE1 isolated API startup timed out: ${logs}`)), 20000);
        const data = (chunk: Buffer) => { logs += chunk.toString(); const m = logs.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/); if (m) { clearTimeout(timer); resolve(m[1]); } };
        child.stdout.on("data", data); child.stderr.on("data", data);
        child.once("error", (e) => { clearTimeout(timer); reject(e); });
        child.once("exit", (code) => { clearTimeout(timer); reject(new Error(`USE1 isolated API exited ${code}: ${logs}`)); });
      });
      await use({ api, directory });
    } finally {
      if (child.exitCode === null && child.signalCode === null) { const closed = once(child, "exit"); child.kill("SIGTERM"); await closed; }
      rmSync(directory, { recursive: true, force: true });
    }
  }, { scope: "worker", auto: true }],
  page: async ({ page, isolated }, use) => {
    await page.route("**/api/**", async (route) => {
      const source = new URL(route.request().url());
      await route.fulfill({ response: await route.fetch({ url: isolated.api + source.pathname + source.search }) });
    });
    await use(page);
    await page.unrouteAll({ behavior: "ignoreErrors" });
  }
});

test("a layout-only inverter is completed, switched, strung by suggestion and simulated, all from the UI", async ({ page, request, isolated }) => {
  test.setTimeout(240_000);
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  const API = isolated.api;
  // The layout-only inverter: the repository's Huawei OND fixture, which states no MPPT current limit.
  const imported = await request.post(`${API}/api/component-library/imports?filename=Huawei_Sun2000_100KTL_M1.OND&dry_run=false`, {
    data: readFileSync(path.join(ROOT, "tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND")), headers: { "Content-Type": "application/octet-stream" } });
  expect(imported.ok()).toBe(true);
  const revision: string = (await imported.json()).entry.revision_id;

  const name = `USE1 ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  const id: string = (await created.json()).bundle.project.project_id;
  const url = `${API}/api/projects/${id}`;
  const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "USE1 roof", width_m: 1 + 10 * 1.154 - 0.01, height_m: 3.45, base_elevation_m: 6.1 } });
  const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id;
  expect((await request.post(url + "/pv-fields", { data: { name: "USE1 array", support_surface_id: sid, module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: 10, row_pitch_m: 3.2, perimeter_setback_m: 0.5 } })).ok()).toBe(true);

  await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6");
  const panel = page.locator(".taskpanel");
  await panel.getByRole("combobox", { name: "Model", exact: true }).selectOption(revision);
  const added = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/inverters`) && r.request().method() === "POST");
  await panel.getByRole("button", { name: "Add inverter" }).click(); expect((await added).ok()).toBe(true);

  // The card says what is missing and completes it where the gap shows.
  const card = panel.locator("[data-inverter-lifecycle]").first();
  await expect(card.locator("[data-readiness]")).toHaveAttribute("data-readiness", "needs_values");
  await card.getByRole("button", { name: "Complete from datasheet" }).click();
  const dialog = page.getByRole("dialog", { name: "Complete from datasheet" });
  await dialog.getByLabel(/Maximum operating current per MPPT/).fill("26");
  await dialog.getByLabel(/Maximum short-circuit current per MPPT/).fill("33");
  await dialog.getByLabel(/^Document/).fill("USE1 live test values only, not a datasheet");
  await dialog.getByLabel(/Page/).fill("p. 1");
  await dialog.getByRole("button", { name: "Preview" }).click();
  const saved = page.waitForResponse((r) => r.url().includes(`/component-library/${revision}/complete`) && r.request().postDataJSON().dry_run === false);
  await dialog.getByRole("button", { name: "Save completed revision" }).click();
  expect((await saved).ok()).toBe(true);

  // The project still uses the original; the card offers the completed one.
  const switched = page.waitForResponse((r) => r.url().includes(`/projects/${id}/inverters/`) && r.request().method() === "PUT");
  await card.getByRole("button", { name: "Switch to completed revision" }).click();
  expect((await switched).ok()).toBe(true);
  await expect(panel.locator("[data-inverter-lifecycle] [data-readiness]").first()).toHaveAttribute("data-readiness", "ready");
  const inverter = (await (await request.get(url)).json()).bundle.electrical_design.inverter_instances[0];
  expect(inverter.inverter_definition_revision_id).not.toBe(revision);

  // The engine sizes the strings; Apply commits them.
  const suggested = page.waitForResponse((r) => r.url().endsWith("/suggest-layout"));
  await panel.getByRole("button", { name: "Suggest stringing" }).first().click();
  const suggestion = await (await suggested).json();
  expect(suggestion.status).toBe("suggestion_available");
  await expect(panel.locator('[data-suggest-result="available"]')).toContainText("Engine suggestion");
  const applied = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/electrical/commands`) && r.request().method() === "POST" && !r.request().postDataJSON().dry_run);
  await panel.getByRole("button", { name: "Apply layout" }).first().click();
  expect((await applied).ok()).toBe(true);
  const design = (await (await request.get(url)).json()).bundle.electrical_design;
  expect(design.strings.filter((s: { target_mppt_instance_id: string | null }) => s.target_mppt_instance_id).length).toBe(suggestion.string_count);
  await expect(page.locator(".rail")).toContainText("Electrical");

  // Weather: three entirely fictional clear-sky days in the isolated store, then the run.
  execFileSync(path.join(ROOT, ".venv/bin/python"), ["-c", `
from pathlib import Path
import json, sys
import pandas as pd, pvlib
from apps.api.server import create_app
store=Path(sys.argv[1])
value=json.loads((Path('tests/fixtures/weather/open_meteo_era5_phase60d_uat.json')).read_bytes())
index=pd.date_range('2024-12-31T00:00Z', periods=24*5, freq='h')
sky=pvlib.location.Location(-6.2,106.8,altitude=25).get_clearsky(index-pd.Timedelta(minutes=30), model='ineichen')
n=len(index)
value['hourly']={'time':[int(t.timestamp()) for t in index],'temperature_2m':[25.]*n,'relative_humidity_2m':[70.]*n,'dew_point_2m':[20.]*n,
  'surface_pressure':[1000.]*n,'wind_speed_10m':[1.]*n,'shortwave_radiation':sky['ghi'].round(3).tolist(),
  'direct_normal_irradiance':sky['dni'].round(3).tolist(),'diffuse_radiation':sky['dhi'].round(3).tolist()}
value['_opensimpv_fixture_note']='Entirely fictional USE1 live days: pvlib Ineichen clear sky; not ERA5.'
app=create_app(store_root=store/'projects',library_root=store/'component-library')
app.state.study_service.acquire_weather(sys.argv[2],source_id='open_meteo_archive_era5',start_date='2025-01-01',end_date='2025-01-03',raw_response=json.dumps(value).encode())
`, isolated.directory, id], { cwd: ROOT, timeout: 60_000 });
  await page.reload(); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+9");
  const simulated = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/simulate`) && r.request().method() === "POST", { timeout: 150_000 });
  await page.getByRole("button", { name: "Validate and run", exact: true }).click();
  const run = await simulated;
  expect(run.status()).toBe(200);
  expect((await run.json()).summary_result.total_energy_wh).toBeGreaterThan(0);
  await page.keyboard.press("Alt+0");
  await expect(page.locator(".kpis")).toBeVisible();
  await expect(page.locator("[data-curtailment=none]")).toContainText("No export limit");
  expect(errors).toEqual([]);
});

test("test components are hidden unless the viewer shows them", async ({ page, request, isolated }) => {
  const name = `USE1 hidden ${Date.now()} ${Math.random()}`;
  expect((await request.post(`${isolated.api}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } })).status()).toBe(201);
  await page.addInitScript(() => { window.localStorage.setItem("rawibumi.language", "en"); window.localStorage.setItem("rawibumi.showTestComponents", "0"); });
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6");
  const model = page.locator(".taskpanel").getByRole("combobox", { name: "Model", exact: true });
  await expect(model.locator('option[value="inv-rawibumi-uat-150k-r1"]')).toHaveCount(0);
  await page.locator(".taskpanel").getByRole("checkbox", { name: "Show test components" }).check();
  await expect(model.locator('option[value="inv-rawibumi-uat-150k-r1"]')).toHaveCount(1);
});
