import { expect, test } from "@playwright/test";
import { openSection } from "../e2e/sections";
import { execFileSync } from "node:child_process";
import path from "node:path";
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("S18c requires the disposable test API.");
const ROOT = path.resolve(process.cwd(), "../..");

test("save inverter DC and quality plus plant cable, inspect recorded results, reset and run defaults", async ({ page, request }) => {
  const name = `S18c circuits ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true); const id = (await created.json()).bundle.project.project_id;
  const url = `${API}/api/projects/${id}`;
  const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "Circuit roof", width_m: 1 + 18 * 1.154 - .01, height_m: 3.45, base_elevation_m: 6.1 } });
  expect(roof.ok()).toBe(true); const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id;
  expect((await request.post(url + "/pv-fields", { data: { name: "Circuit array", support_surface_id: sid, module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: 10, row_pitch_m: 3.2, perimeter_setback_m: .5 } })).ok()).toBe(true);
  const inv = await request.post(url + "/inverters", { data: { name: "Circuit inverter", inverter_definition_revision_id: "inv-rawibumi-uat-150k-r1" } });
  expect(inv.ok()).toBe(true); const iid = (await inv.json()).bundle.electrical_design.inverter_instances[0].inverter_instance_id;
  const strings = await request.post(url + "/strings", { data: { string_length: 18, allow_shorter_remainder: false } });
  expect(strings.ok()).toBe(true); const ids = (await strings.json()).bundle.electrical_design.strings.map((s: { string_id: string }) => s.string_id);
  expect((await request.post(url + "/assignments", { data: { inverter_instance_id: iid, string_ids: ids } })).ok()).toBe(true);
  execFileSync(path.join(ROOT, ".venv/bin/python"), ["-c", `
from pathlib import Path
import sys
from apps.api.server import create_app
root=Path(sys.argv[1]).resolve();store=root/'tmp/live-projects'
assert store.is_dir() and store.resolve()==store
app=create_app(store_root=store,library_root=root/'tmp/component-library')
app.state.study_service.acquire_weather(sys.argv[2],source_id='open_meteo_archive_era5',start_date='2025-01-01',end_date='2025-01-01',raw_response=(root/'tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json').read_bytes())
`, ROOT, id], { cwd: ROOT, timeout: 30_000 });
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+8");
  await openSection(page, "Losses");
  const panel = page.locator("[data-circuit-loss-editor]");
  await panel.getByLabel("Circuit inverter · DC wiring (%)").fill("1.08");
  await panel.getByLabel("Circuit inverter · Module quality (%)").fill("-0.75");
  await panel.getByRole("combobox", { name: "AC combiner to PCC · Input mode", exact: true }).selectOption("cable");
  await panel.getByLabel("AC combiner to PCC · One-way length (m)", { exact: true }).fill("40");
  await panel.getByLabel("AC combiner to PCC · Cross-section per phase (mm²)", { exact: true }).selectOption("120");
  await expect(panel.getByText(/Assumption: 50 °C conductor temperature/)).toBeVisible();
  await panel.getByLabel("AC combiner to PCC · Conductor temperature (°C)", { exact: true }).fill("60");
  const saving = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/losses`) && r.request().method() === "PATCH");
  await panel.getByRole("button", { name: "Save circuit losses", exact: true }).click(); expect((await saving).status()).toBe(200);
  await expect(panel.getByRole("button", { name: "Save circuit losses", exact: true })).toBeDisabled();
  async function simulate() {
    const previous = new Set((await (await request.get(url)).json()).bundle.simulation_runs.map((r: { simulation_run_id: string }) => r.simulation_run_id));
    await page.keyboard.press("Alt+9");
    const response = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/simulate`) && r.request().method() === "POST");
    const run = page.getByRole("button", { name: "Validate and run", exact: true }); await expect(run).toBeEnabled(); await run.click();
    expect((await response).ok()).toBe(true);
    await expect(page.getByRole("heading", { name: "Results", exact: true })).toBeVisible();
    const saved = (await (await request.get(url)).json()).bundle.simulation_runs;
    const created = saved.find((r: { simulation_run_id: string }) => !previous.has(r.simulation_run_id));
    expect(created).toBeDefined(); return created;
  }
  const edited = await simulate(); expect(edited.circuit_loss_resolution.active).toBe(true);
  expect(edited.circuit_loss_resolution.plant_ac_wiring.conductor_temperature_c).toBe(60);
  expect(edited.summary_result.loss_summary.find((l: { loss_type: string }) => l.loss_type === "plant_ac_wiring").lost_energy_wh).toBeGreaterThan(0);
  await openSection(page, "Settings used in this run");
  await page.getByText("Loss settings used for this run", { exact: false }).click();
  const recorded = page.locator("[data-run-circuit-losses]"); await expect(recorded).toContainText("Circuit inverter");
  await expect(recorded).toContainText("1.08"); await expect(recorded).toContainText("-0.75"); await expect(recorded).toContainText("60 °C");
  await page.keyboard.press("Alt+8");
  const reset = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/losses`) && r.request().method() === "PATCH");
  await page.getByRole("button", { name: "Reset to recommended defaults", exact: true }).click(); expect((await reset).status()).toBe(200);
  await expect(panel.getByLabel("Circuit inverter · DC wiring (%)")).toHaveValue("");
  await expect(panel.getByRole("combobox", { name: "AC combiner to PCC · Input mode", exact: true })).toHaveValue("inherit");
  const restored = await simulate(); expect(restored.simulation_run_id).not.toBe(edited.simulation_run_id); expect(restored.circuit_loss_resolution).toBeUndefined();
  expect(restored.resolved_loss_settings.status).toBe("recommended_defaults");
  const saved = (await (await request.get(url)).json()).bundle.simulation_runs;
  expect(saved.find((r: { simulation_run_id: string }) => r.simulation_run_id === edited.simulation_run_id).circuit_loss_resolution).toEqual(edited.circuit_loss_resolution);
  expect(errors).toEqual([]);
});
