import { openSection } from "../e2e/sections";
import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("S16 requires the disposable live-test API, never port 8000.");
const ROOT = path.resolve(process.cwd(), "../..");
const cmd = (kind: string, parameters: Record<string, unknown>, id: string) => ({ schema_name: "ElectricalTopologyCommand", schema_version: "0.1", command_id: id, command_type: kind, parameters });

test("two roof orientations and two inverters simulate and show each inverter plus the PCC total", async ({ page, request }) => {
  // RB-4D: every run includes module self-shading, so this simulation is slower under parallel live load.
  test.setTimeout(240_000);
  const name = `S16 multi ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, elevation_m: 25, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true);
  const id: string = (await created.json()).bundle.project.project_id;
  const url = `${API}/api/projects/${id}`;
  const catalog = await (await request.get(`${API}/api/catalog`)).json();
  const module = catalog.modules.find((m: { revision_id: string }) => m.revision_id === "mod-rawibumi-uat-550-r1");
  expect(module).toBeTruthy();
  const commands = [];
  for (let i = 0; i < 2; i++) {
    const surface = await request.post(url + "/surfaces/rectangle", { data: { name: `Roof ${i+1}`, origin_x_m: i*100, width_m: 1+18*1.154-.01, height_m: 3.45, base_elevation_m: 6.1 } });
    expect(surface.ok()).toBe(true);
    const surfaces = (await surface.json()).bundle.scene.surfaces;
    const sid = surfaces[surfaces.length-1].surface_id;
    const filled = await request.post(url + "/pv-fields", { data: { name: `Array ${i+1}`, support_surface_id: sid, module_definition_revision_id: module.revision_id, tilt_deg: i === 0 ? 10 : 15, row_pitch_m: 3.2, perimeter_setback_m: .5 } });
    expect(filled.ok()).toBe(true);
    const view = await filled.json();
    const field = view.bundle.scene.pv_fields.find((f: { support_surface_id: string }) => f.support_surface_id === sid);
    const modules = view.bundle.scene.module_instances.filter((m: { pv_field_id: string }) => m.pv_field_id === field.pv_field_id).map((m: { module_instance_id: string }) => m.module_instance_id);
    expect(modules).toHaveLength(18);
    const added = await request.post(url + "/inverters", { data: { name: `S16 INV-${i+1}`, inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1" } });
    expect(added.ok()).toBe(true);
    const design = (await added.json()).bundle.electrical_design;
    const inverter = design.inverter_instances[design.inverter_instances.length-1];
    const mppt = design.mppt_instances.find((m: { inverter_instance_id: string; index: number }) => m.inverter_instance_id === inverter.inverter_instance_id && m.index === 1);
    const stringId = `S${i+1}`;
    commands.push(cmd("create_string", { string_id: stringId, module_instance_ids: modules }, `s16-create-${i}`));
    commands.push(cmd("assign_strings_to_mppt", { string_ids: [stringId], mppt_instance_id: mppt.mppt_instance_id }, `s16-assign-${i}`));
  }
  expect((await request.post(url + "/electrical/commands", { data: { commands } })).ok()).toBe(true);
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
  const ready = await (await request.get(url + "/execution-readiness")).json();
  expect(ready.ready).toBe(true); expect(ready.execution_plan.group_count).toBe(2);
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+9");
  const runResponse = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/simulate`) && r.request().method() === "POST");
  const runButton = page.getByRole("button", { name: "Validate and run", exact: true });
  await expect(runButton).toBeEnabled();
  await runButton.click();
  const response = await runResponse; expect(response.ok()).toBe(true);
  const run = await response.json(); expect(["completed", "completed_with_warnings"]).toContain(run.status);
  const summary = run.summary_result;
  expect(summary.execution_breakdown.inverters).toHaveLength(2);
  await openSection(page, "Inverters and MPPTs");
  await expect.poll(async () => page.locator('[data-plant-energy-kwh]').count()).toBe(1);
  const table = page.getByRole("region", { name: "Inverter results" });
  await expect(table).toContainText("S16 INV-1"); await expect(table).toContainText("S16 INV-2");
  await expect(table).toContainText("Plant total");
  for (const inverter of summary.execution_breakdown.inverters) {
    const row = table.locator('[data-inverter-result]', { hasText: inverter.name });
    await expect(row.locator('[data-inverter-energy-kwh]')).toHaveAttribute("data-inverter-energy-kwh", String(inverter.total_energy_wh / 1000));
  }
  await expect(table.locator('[data-plant-energy-kwh]')).toHaveAttribute("data-plant-energy-kwh", String(summary.total_energy_wh / 1000));
  expect(summary.execution_breakdown.inverters.reduce((sum: number, i: { total_energy_wh: number }) => sum+i.total_energy_wh, 0)).toBeCloseTo(summary.total_energy_wh, 7);
  expect(errors).toEqual([]);
});
