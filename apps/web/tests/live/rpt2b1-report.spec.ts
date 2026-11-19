import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("RPT2b-1 requires a disposable live API");
const ROOT = path.resolve(process.cwd(), "../..");
test("verified snapshot supplies the report method and P99 reason; a changed design is refused", async ({ page, request }) => {
  await page.addInitScript(() => localStorage.setItem("rawibumi.addressLookup", "off"));
  const name = `RPT2b-1 ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true);
  const id = (await created.json()).bundle.project.project_id, url = `${API}/api/projects/${id}`;
  try {
    const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "Synthetic report roof", width_m: 1 + 18 * 1.154 - .01, height_m: 3.45, base_elevation_m: 6.1 } });
    expect(roof.ok()).toBe(true);
    const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id;
    expect((await request.post(url + "/pv-fields", { data: { name: "Synthetic report array", support_surface_id: sid, module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: 10, row_pitch_m: 3.2, perimeter_setback_m: .5 } })).ok()).toBe(true);
    const inverter = await request.post(url + "/inverters", { data: { name: "INV", inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1" } });
    expect(inverter.ok()).toBe(true);
    const iid = (await inverter.json()).bundle.electrical_design.inverter_instances[0].inverter_instance_id;
    const strings = await request.post(url + "/strings", { data: { string_length: 18, allow_shorter_remainder: false } });
    expect(strings.ok()).toBe(true);
    const ids = (await strings.json()).bundle.electrical_design.strings.map((s: { string_id: string }) => s.string_id);
    expect(ids).toHaveLength(1);
    expect((await request.post(url + "/assignments", { data: { inverter_instance_id: iid, string_ids: ids } })).ok()).toBe(true);
    execFileSync(path.join(ROOT, ".venv/bin/python"), ["-c", `
from pathlib import Path
import sys
from apps.api.server import create_app
root=Path(sys.argv[1]).resolve();store=root/'tmp/live-projects'
assert store.is_dir() and store.resolve()==store
app=create_app(store_root=store,library_root=root/'tmp/component-library')
# Explicitly fictional full-year daylight weather; no external acquisition.
import numpy as np
import pandas as pd
import pvlib
from weather.core import build_weather_dataset,build_time_semantics
index=pd.date_range('2025-01-01',periods=8760,freq='h',tz='Asia/Jakarta')
position=pvlib.solarposition.spa_python(index+pd.Timedelta(minutes=30),latitude=-6.2,longitude=106.8,altitude=0.,pressure=100500.,temperature=30.,delta_t=None,atmos_refract=.5667,how='numpy',numthreads=1)
cosz=np.maximum(np.cos(np.radians(position['zenith'].to_numpy())),0.);dni=np.where(cosz>0,700.,0.);dhi=120.*cosz
series=pd.DataFrame({'ghi_w_m2':dhi+dni*cosz,'dni_w_m2':dni,'dhi_w_m2':dhi,'ambient_temperature_c':30.,'wind_speed_m_s':1.,'pressure_pa':100500.},index=index)
semantics=build_time_semantics(canonical_timezone='Asia/Jakarta',source_timestamp_convention='interval_start',native_interval_seconds=3600,current_interval_seconds=3600,source_timezone='Asia/Jakarta',source_utc_offset_hours=7.)
weather=build_weather_dataset(series,weather_dataset_id='rpt2b1-synthetic-weather',revision_id='rpt2b1-synthetic-weather-r1',name='Fictional RPT2b-1 annual daylight weather',site_id='rpt2b1-synthetic-site',timezone='Asia/Jakarta',native_resolution_seconds=3600,source_format='synthetic_test',source_timestamp_convention='interval_start',location={'latitude_deg':-6.2,'longitude_deg':106.8,'elevation_m':0.},native_series_origin='unknown',series_origin='unknown',time_semantics=semantics,start_time=index[0],end_time=index[-1]+pd.Timedelta(hours=1))
bundle=app.state.project_service.get_bundle(sys.argv[2]);bundle['weather_selection']=app.state.study_service.weather.save(sys.argv[2],weather);app.state.project_service.save_bundle(bundle)
`, ROOT, id], { cwd: ROOT, timeout: 30_000 });
    await page.goto("/"); await page.locator(".start__row", { hasText: name }).click();
    await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+9");
    const simulated = page.waitForResponse(r => r.url().endsWith(`/projects/${id}/simulate`) && r.request().method() === "POST");
    await page.getByRole("button", { name: "Validate and run", exact: true }).click();
    const response = await simulated; expect(response.ok()).toBe(true); const record = await response.json();
    expect(record.summary_result.annual_energy_wh).toBeGreaterThan(0);
    await expect(page.locator(".kpis")).toBeVisible();
    const snapshotUrl = `${url}/runs/${record.simulation_run_id}/report-snapshot`;
    const snapshotResponse = page.waitForResponse(r => new URL(r.url()).pathname === new URL(snapshotUrl).pathname && r.request().method() === "GET");
    await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
    const stored = await snapshotResponse;
    expect(stored.status(), await stored.text()).toBe(200);
    const snapshot = await stored.json();
    expect(snapshot.summary).toEqual(record.summary_result);
    expect(snapshot.annual_pxx.P99).toBeNull();
    expect(snapshot.annual_pxx.P99_reason).toBe("no_uncertainty_ledger");
    const preview = page.getByRole("button", { name: "Preview report", exact: true });
    await expect(preview).toBeEnabled(); await preview.click();
    const frame = page.frameLocator('iframe[title="Report preview"]');
    await expect(frame.locator('[data-report-method-limits]')).toContainText("Inverter temperature derating is not modelled");
    await expect(frame.locator('[data-report-p99-reason]')).toHaveAttribute("data-report-p99-reason", "no_uncertainty_ledger");
    await expect(frame.locator('[data-report-loss-disclosures]')).toContainText("0 %: not included");
    const changed = await request.post(url + "/surfaces/rectangle", { data: { name: "Changed design", origin_x_m: 100, width_m: 10, height_m: 10, base_elevation_m: 6.1 } });
    expect(changed.ok()).toBe(true);
    await page.reload(); await page.locator(".start__row", { hasText: name }).click();
    await expect(page.locator(".rail")).toBeVisible();
    const refusalResponse = page.waitForResponse(r => new URL(r.url()).pathname === new URL(snapshotUrl).pathname && r.request().method() === "GET");
    await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
    const refused = await refusalResponse;
    expect(refused.status()).toBe(422); expect(await refused.text()).toContain("earlier_design");
    await expect(page.locator('[data-report-design-basis="earlier"]')).toBeVisible();
    await expect(page.locator('iframe[title="Report preview"]')).toHaveCount(0);
  } finally { expect((await request.delete(url, { params: { confirm: id } })).ok()).toBe(true); }
});
