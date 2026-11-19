import { expect, test } from "@playwright/test";
import { openSection } from "../e2e/sections";
import { execFileSync } from "node:child_process";
import path from "node:path";
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("S18b requires the disposable test API, never var/projects.");
const ROOT = path.resolve(process.cwd(), "../..");

test("edit transposition and Uc, record immutable optics settings, then reset and run Recommended defaults", async ({ page, request }) => {
  const name = `S18b losses ${Date.now()} ${Math.random()}`;
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
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+8");
  await openSection(page, "Optics & thermal");
  const panel = page.locator("[data-optics-settings]");
  await expect(panel).toHaveAttribute("data-optics-settings", "recommended_defaults");
  await panel.getByLabel("Transposition model", {exact:true}).selectOption("isotropic");
  await panel.getByLabel("Thermal Uc (W/(m²·K))", {exact:true}).fill("27");
  const saving=page.waitForResponse(r=>r.url().endsWith(`/projects/${id}/optics-thermal`)&&r.request().method()==="PATCH");
  await panel.getByRole("button",{name:"Save optics and thermal",exact:true}).click();expect((await saving).status()).toBe(200);
  await expect(panel).toHaveAttribute("data-optics-settings","edited");
  async function simulate(){
    await page.keyboard.press("Alt+9");
    const response=page.waitForResponse(r=>r.url().endsWith(`/projects/${id}/simulate`)&&r.request().method()==="POST");
    const button=page.getByRole("button",{name:"Validate and run",exact:true});await expect(button).toBeEnabled();await button.click();
    const result=await response;expect(result.ok()).toBe(true);return result.json();
  }
  const edited=await simulate();
  expect(edited.resolved_optics_thermal_settings.values.transposition).toBe("isotropic");
  expect(edited.resolved_optics_thermal_settings.values.thermal.u_c_w_m2k).toBe(27);
  await openSection(page, "Settings used in this run");
  const detail=page.locator("[data-run-optics-settings]");await expect(detail).toBeVisible();await detail.locator("summary").click();
  await expect(detail).toContainText(edited.resolved_optics_thermal_settings.settings_sha256);await expect(detail).toContainText("Isotropic");
  await expect(detail).toContainText("27");
  await page.keyboard.press("Alt+8");
  const reset=page.waitForResponse(r=>r.url().endsWith(`/projects/${id}/optics-thermal`)&&r.request().method()==="PATCH");
  await panel.getByRole("button",{name:"Reset optics and thermal",exact:true}).click();expect((await reset).status()).toBe(200);
  await expect(panel).toHaveAttribute("data-optics-settings","recommended_defaults");
  const restored=await simulate();expect(restored.resolved_optics_thermal_settings.values.transposition).toBe("perez_hourly");
  expect(restored.resolved_optics_thermal_settings.values.thermal.u_c_w_m2k).toBe(20);
  expect(restored.resolved_optics_thermal_settings.values.thermal.irradiance_basis).toBe("effective");
  const saved=(await (await request.get(url)).json()).bundle.simulation_runs;
  expect(saved.find((r:{simulation_run_id:string})=>r.simulation_run_id===edited.simulation_run_id).resolved_optics_thermal_settings).toEqual(edited.resolved_optics_thermal_settings);
  expect(errors).toEqual([]);
});
