import { openSection } from "../e2e/sections";
import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

// UNC1 on the real engine: an annual run (a fictional clear-sky year), the ledger entered in the browser, the engine's
// P50–P95 shown with the P99 reason, and the same block in the HTML report.
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("UNC1 requires the disposable test API, never var/projects.");
const ROOT = path.resolve(process.cwd(), "../..");

test("an annual run's P50–P95 from the engine under a ledger entered in the browser, and in the report", async ({ page, request }) => {
  test.setTimeout(180_000);
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  const name = `UNC1 pxx ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true); const id: string = (await created.json()).bundle.project.project_id;
  const url = `${API}/api/projects/${id}`;
  // A small system (6 modules, one string) keeps the full-year run light when it shares the machine with other live tests.
  const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "Pxx roof", width_m: 1 + 6 * 1.154 - .01, height_m: 3.45, base_elevation_m: 6.1 } });
  const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id;
  expect((await request.post(url + "/pv-fields", { data: { name: "Pxx array", support_surface_id: sid, module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: 10, row_pitch_m: 3.2, perimeter_setback_m: .5 } })).ok()).toBe(true);
  const inverter = await request.post(url + "/inverters", { data: { name: "INV", inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1" } });
  const iid = (await inverter.json()).bundle.electrical_design.inverter_instances[0].inverter_instance_id;
  const strings = await request.post(url + "/strings", { data: { string_length: 6, allow_shorter_remainder: false } });
  const ids = (await strings.json()).bundle.electrical_design.strings.map((s: { string_id: string }) => s.string_id);
  expect((await request.post(url + "/assignments", { data: { inverter_instance_id: iid, string_ids: ids } })).ok()).toBe(true);
  execFileSync(path.join(ROOT, ".venv/bin/python"), ["-c", `
from pathlib import Path
import json, sys
import pandas as pd, pvlib
from apps.api.server import create_app
root=Path(sys.argv[1]).resolve()
store=root/'tmp/live-projects'
assert store.is_dir() and store.resolve()==store
value=json.loads((root/'tests/fixtures/weather/open_meteo_era5_phase60d_uat.json').read_bytes())
index=pd.date_range('2022-12-31T00:00Z', periods=8760+48, freq='h')
sky=pvlib.location.Location(-6.2,106.8,altitude=25).get_clearsky(index-pd.Timedelta(minutes=30), model='ineichen')
value['hourly']={'time':[int(t.timestamp()) for t in index],'temperature_2m':[25.]*len(index),'relative_humidity_2m':[70.]*len(index),'dew_point_2m':[20.]*len(index),
  'surface_pressure':[1000.]*len(index),'wind_speed_10m':[1.]*len(index),'shortwave_radiation':sky['ghi'].round(3).tolist(),
  'direct_normal_irradiance':sky['dni'].round(3).tolist(),'diffuse_radiation':sky['dhi'].round(3).tolist()}
value['_opensimpv_fixture_note']='Entirely fictional UNC1 live year: pvlib Ineichen clear sky; not ERA5.'
app=create_app(store_root=store,library_root=root/'tmp/component-library')
app.state.study_service.acquire_weather(sys.argv[2],source_id='open_meteo_archive_era5',start_date='2023-01-01',end_date='2023-12-31',raw_response=json.dumps(value).encode())
`, ROOT, id], { cwd: ROOT, timeout: 60_000 });

  await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
  await page.route("https://nominatim.openstreetmap.org/**", (route) => route.abort());
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+9");
  const simulated = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/simulate`) && r.request().method() === "POST", { timeout: 120_000 });
  await page.getByRole("button", { name: "Validate and run", exact: true }).click();
  const record = await (await simulated).json();
  expect(record.summary_result.annual_energy_wh).not.toBeNull();

  await page.keyboard.press("Alt+0");
  await openSection(page, "P50–P95");
  const card = page.locator("[data-annual-pxx]");
  await expect(card).toHaveAttribute("data-annual-pxx", "unavailable");
  await card.getByRole("button", { name: "Uncertainty assumptions" }).click();
  for (const [label, value] of [["Interannual solar variability", "4"], ["Solar resource reference bias", "3"]] as const) {
    await card.locator("[data-pxx-add]").getByRole("button", { name: `+ ${label}` }).click();
  }
  for (const [key, value] of [["interannual_solar_variability", "4"], ["solar_resource_reference_bias", "3"]] as const) {
    const term = card.locator(`[data-pxx-term="${key}"]`);
    await term.getByLabel(`σ for ${key}`).fill(value);
    await term.getByLabel(`Source for ${key}`).fill("UNC1 live test");
    await term.getByLabel(`Justification for ${key}`).fill("Test value only");
  }
  await card.getByLabel("Basis for the correlation assumption").fill("Declared independent for the test");
  const saved = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/uncertainty-assumptions`) && r.request().method() === "PUT");
  await card.getByRole("button", { name: "Save assumptions" }).click();
  expect((await saved).status()).toBe(200);
  await expect(card).toHaveAttribute("data-annual-pxx", "available");

  const engine = await (await request.get(`${url}/runs/${record.simulation_run_id}/annual-pxx`)).json();
  expect(engine.status).toBe("available");
  const mu = record.summary_result.annual_energy_wh / 1000;
  expect(engine.result.quantiles.P90.energy_kwh).toBeCloseTo(mu * (1 - 1.2815515655446008 * 0.05), 6);
  const p90 = (engine.result.quantiles.P90.energy_kwh / 1000).toFixed(2);
  await expect(card.locator('[data-pxx="P90"]')).toContainText(p90);
  await expect(card.locator('[data-pxx="P99"]')).toContainText("not qualified");
  await expect(card.locator("[data-pxx-basis]")).toHaveAttribute("data-pxx-basis", "historical_year_as_mean");

  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await page.getByRole("button", { name: "Preview report", exact: true }).click();
  await expect(page.frameLocator("iframe.report-frame").locator("[data-report-pxx]")).toContainText(p90);
  expect(errors).toEqual([]);
});
