import { expect, test } from "@playwright/test";
import { openSection } from "../e2e/sections";
import { execFileSync } from "node:child_process";
import path from "node:path";
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("SKY1 requires the disposable test API, never var/projects.");
const ROOT = path.resolve(process.cwd(), "../..");

test("High sampling persists, runs, displays its grid, then resets to Standard", async ({ page, request }) => {
  const name = `SKY1 sampling ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true); const id: string = (await created.json()).bundle.project.project_id;
  const url = `${API}/api/projects/${id}`;
  const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "Loss roof", width_m: 1 + 18 * 1.154 - .01, height_m: 3.45, base_elevation_m: 6.1 } });
  expect(roof.ok()).toBe(true);
  const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id;
  expect((await request.post(url + "/pv-fields", { data: { name: "Loss array", support_surface_id: sid, module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: 10, row_pitch_m: 3.2, perimeter_setback_m: .5 } })).ok()).toBe(true);
  const inverter = await request.post(url + "/inverters", { data: { name: "Loss inverter", inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1" } });
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
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await page.goto("/"); await page.locator(".start__row", {hasText:name}).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+8");
  await openSection(page, "Shading accuracy");
  const panel = page.locator("[data-shading-accuracy]");
  await expect(panel).toHaveAttribute("data-shading-accuracy","standard");
  await panel.getByLabel("Shading accuracy",{exact:true}).selectOption("high");
  const save=page.waitForResponse(r=>r.url().endsWith(`/projects/${id}/shading-accuracy`)&&r.request().method()==="PATCH");
  await panel.getByRole("button",{name:"Save shading accuracy",exact:true}).click();expect((await save).status()).toBe(200);
  await expect(panel).toHaveAttribute("data-shading-accuracy","high");
  async function simulate(){
    await page.keyboard.press("Alt+9");
    const response=page.waitForResponse(r=>r.url().endsWith(`/projects/${id}/simulate`)&&r.request().method()==="POST");
    const button=page.getByRole("button",{name:"Validate and run",exact:true});await expect(button).toBeEnabled();await button.click();
    const result=await response;expect(result.ok()).toBe(true);return result.json();
  }
  const high=await simulate();expect(high.resolved_shading_accuracy.level).toBe("high");
  expect(high.resolved_shading_accuracy.sky_dome_resolution).toMatchObject({azimuth_sectors:72,elevation_bands:18,horizon_azimuth_sectors:72});
  expect(high.resolved_shading_accuracy.ground_dome_resolution).toEqual({azimuth_sectors:72,depression_bands:18});
  await openSection(page, "Settings used in this run");
  const display=page.locator("[data-run-shading-accuracy]");await expect(display).toHaveAttribute("data-run-shading-accuracy","high");
  await display.locator("summary").click();await expect(display).toContainText("High (slower, finest sampling)");await expect(display).toContainText("72 × 18");
  await page.keyboard.press("Alt+8");
  const reset=page.waitForResponse(r=>r.url().endsWith(`/projects/${id}/shading-accuracy`)&&r.request().method()==="PATCH");
  await panel.getByRole("button",{name:"Reset shading accuracy",exact:true}).click();expect((await reset).status()).toBe(200);
  await expect(panel).toHaveAttribute("data-shading-accuracy","standard");
  const standard=await simulate();expect(standard.resolved_shading_accuracy.level).toBe("standard");
  expect(standard.resolved_shading_accuracy.sky_dome_resolution).toMatchObject({azimuth_sectors:48,elevation_bands:12,horizon_azimuth_sectors:48});
  expect(standard.resolved_shading_accuracy.ground_dome_resolution).toEqual({azimuth_sectors:48,depression_bands:12});
  await expect(display).toHaveAttribute("data-run-shading-accuracy","standard");
  const saved=(await (await request.get(url)).json()).bundle.simulation_runs;
  expect(saved.find((r:{simulation_run_id:string})=>r.simulation_run_id===high.simulation_run_id).resolved_shading_accuracy).toEqual(high.resolved_shading_accuracy);
  expect(errors).toEqual([]);
});
