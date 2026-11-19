import { expect, test } from "@playwright/test";
import { openSection } from "../e2e/sections";
import { execFileSync } from "node:child_process";
import path from "node:path";
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("S18a requires the disposable test API, never var/projects.");
const ROOT = path.resolve(process.cwd(), "../..");

test("edit soiling, simulate with its immutable settings, then reset and run Recommended defaults", async ({ page, request }) => {
  const name = `S18a losses ${Date.now()} ${Math.random()}`;
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
  await openSection(page, "Losses");
  const panel = page.locator("[data-loss-settings]");
  await expect(panel).toHaveAttribute("data-loss-settings", "recommended_defaults");
  await panel.getByLabel("Soiling month 1 (%)", { exact: true }).fill("8");
  const saving = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/losses`) && r.request().method() === "PATCH");
  await panel.getByRole("button", { name: "Save losses", exact: true }).click(); expect((await saving).status()).toBe(200);
  await expect(panel).toHaveAttribute("data-loss-settings", "edited");
  async function simulate() {
    await page.keyboard.press("Alt+9");
    const response = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/simulate`) && r.request().method() === "POST");
    const button = page.getByRole("button", { name: "Validate and run", exact: true }); await expect(button).toBeEnabled(); await button.click();
    const result = await response; expect(result.ok()).toBe(true); return result.json();
  }
  const edited = await simulate(); expect(edited.resolved_loss_settings.values.soiling.monthly_fractions[0]).toBe(.08);
  expect(edited.summary_result.loss_summary.find((l: { loss_type: string }) => l.loss_type === "soiling").lost_energy_wh).toBeGreaterThan(0);
  await openSection(page, "Settings used in this run");
  await expect(page.getByText("Loss settings used for this run", { exact: false })).toBeVisible();
  await page.getByText("Loss settings used for this run", { exact: false }).click();
  await expect(page.locator("details[open]", { hasText: "Loss settings used for this run" })).toContainText(edited.resolved_loss_settings.settings_sha256);
  await expect(page.getByText("Soiling month 1 (%)", { exact: true }).locator("..")).toContainText("8 · Edited");
  await page.getByRole("radio", { name: "Loss waterfall", exact: true }).click();
  const chart = page.locator('[data-chart="Loss waterfall from reference energy to AC energy"]');
  await expect(chart.locator("canvas").first()).toBeVisible();
  await expect.poll(() => chart.evaluate(async (element) => {
    const { echarts } = await import("/src/results/echarts.ts");
    const option = echarts.getInstanceByDom(element as HTMLElement)?.getOption() as { xAxis?: Array<{ data?: string[] }> } | undefined;
    return option?.xAxis?.[0].data ?? [];
  })).toContain("Soiling (STC reference)");
  await page.keyboard.press("Alt+8"); const reset = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/losses`) && r.request().method() === "PATCH");
  await panel.getByRole("button", { name: "Reset to recommended defaults", exact: true }).click(); expect((await reset).status()).toBe(200);
  await expect(panel).toHaveAttribute("data-loss-settings", "recommended_defaults"); await expect(panel.getByLabel("Soiling month 1 (%)", { exact: true })).toHaveValue("3");
  const restored = await simulate(); expect(restored.resolved_loss_settings.status).toBe("recommended_defaults");
  expect(restored.resolved_loss_settings.values.soiling.monthly_fractions).toEqual(Array(12).fill(.03));
  expect(restored.summary_result.total_energy_wh).toBeGreaterThan(edited.summary_result.total_energy_wh);
  const saved = (await (await request.get(url)).json()).bundle.simulation_runs;
  expect(saved.find((r: { simulation_run_id: string }) => r.simulation_run_id === edited.simulation_run_id).resolved_loss_settings).toEqual(edited.resolved_loss_settings);
  expect(errors).toEqual([]);
});
