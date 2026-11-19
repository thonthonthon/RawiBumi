import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { openSection } from "../e2e/sections";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("S7d requires the test-only API on a checked-free loopback port, never 8000.");
const ROOT = path.resolve(process.cwd(), "../..");
const STORE = path.join(ROOT, "tmp/live-projects");
const url = (id: string) => `${API}/api/projects/${id}`;
async function view(request: APIRequestContext, id: string) { const r = await request.get(url(id)); expect(r.ok()).toBe(true); return r.json(); }
async function open(page: Page, name: string) {
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+1"); await expect(page.locator(".taskpanel").getByLabel("Site name", { exact: true })).toBeVisible();
}
async function create(request: APIRequestContext, suffix: string) {
  const name = `S7d ${suffix} ${Date.now()}`;
  const r = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, elevation_m: 25, timezone: "Asia/Jakarta", workspace_mode: "map_overlay" } }); expect(r.ok()).toBe(true);
  return { id: (await r.json()).bundle.project.project_id as string, name };
}
function pinSyntheticWeather(ids: string[]) {
  // Explicitly synthetic provider-shaped fixture, injected through the real service.
  // The store is fixed here; this helper can never use the API's production default.
  execFileSync(path.join(ROOT, ".venv/bin/python"), ["-c", `
from pathlib import Path
import sys
from apps.api.server import create_app
root = Path(sys.argv[1]).resolve()
store = root / "tmp" / "live-projects"
assert store.is_dir() and store.resolve() == store
app = create_app(store_root=store)
raw = (root / "tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json").read_bytes()
for pid in sys.argv[2:]:
    app.state.study_service.acquire_weather(pid, source_id="open_meteo_archive_era5", start_date="2025-01-01", end_date="2025-01-01", raw_response=raw)
`, ROOT, ...ids], { cwd: ROOT, timeout: 30_000 });
}
function assertDirectories(id: string, present: boolean) {
  for (const dir of ["runs", "weather"]) expect(existsSync(path.join(ROOT, "tmp", dir, id))).toBe(present);
}

// A single full fixture exercises site invalidation, preservation of past runs,
// project rename/delete and shared snapshot retention without network weather.
test("pinned site edit confirms weather clearing, preserves runs, then rename and hard delete", async ({ page, request }) => {
  // Runs a full simulation: reviewer 18.7 s alone; parent parallel 48.2–57.5 s, plus a 60 s timeout.
  test.setTimeout(150_000);
  const { id, name } = await create(request, "site"); const shared = await create(request, "shared");
  expect(existsSync(path.join(STORE, `${id}.json`))).toBe(true);
  const catalog = await (await request.get(`${API}/api/catalog`)).json();
  const module = catalog.modules.find((m: { revision_id: string }) => m.revision_id === "mod-rawibumi-uat-550-r1") ?? catalog.modules[0];
  const inverter = catalog.inverters.find((m: { revision_id: string }) => m.revision_id === "inv-rawibumi-uat-150k-r1");
  const roofResponse = await request.post(url(id) + "/surfaces/rectangle", { data: { name: "S7d roof", width_m: 1 + 20 * (module.width_m + 0.02) - 0.01, height_m: 3.45, base_elevation_m: 6.1 } }); expect(roofResponse.ok()).toBe(true);
  const surface = (await roofResponse.json()).bundle.scene.surfaces[0].surface_id;
  expect((await request.post(url(id) + "/pv-fields", { data: { name: "S7d array", support_surface_id: surface, module_definition_revision_id: module.revision_id, tilt_deg: 10, row_pitch_m: 3.2, perimeter_setback_m: 0.5, obstacle_setback_m: 0.3 } })).ok()).toBe(true);
  const invResponse = await request.post(url(id) + "/inverters", { data: { inverter_definition_revision_id: inverter.revision_id, name: "INV" } }); expect(invResponse.ok()).toBe(true);
  const invId = (await invResponse.json()).bundle.electrical_design.inverter_instances[0].inverter_instance_id;
  expect((await request.post(url(id) + "/strings", { data: { string_length: 20, allow_shorter_remainder: false } })).ok()).toBe(true);
  expect((await request.post(url(id) + "/assignments", { data: { inverter_instance_id: invId } })).ok()).toBe(true);
  pinSyntheticWeather([id, shared.id]);
  const run = await request.post(url(id) + "/simulate", { data: {} }); expect(run.ok(), await run.text()).toBe(true);
  const before = await view(request, id), otherBefore = await view(request, shared.id);
  assertDirectories(id, true); const revision = before.bundle.weather_selection.revision_id;
  const digest = before.bundle.weather_selection.manifest.raw_response.sha256;
  expect(digest).toMatch(/^[0-9a-f]{64}$/); expect(digest).toBe(otherBefore.bundle.weather_selection.manifest.raw_response.sha256);
  const snapshot = path.join(ROOT, "tmp/weather-snapshots/sha256", digest.slice(0, 2), `${digest}.json`);
  await open(page, name); const p = page.locator(".taskpanel");
  const patches: Record<string, unknown>[] = [];
  page.on("request", (r) => { if (r.method() === "PATCH" && r.url().endsWith(`/projects/${id}/site`)) patches.push(r.postDataJSON()); });
  await p.getByLabel("Latitude", { exact: true }).fill("-7.25"); await p.getByRole("button", { name: "Apply", exact: true }).click();
  const dialog = page.getByRole("alertdialog", { name: "Clear pinned weather?" }); await expect(dialog).toContainText(revision);
  await expect(dialog).toContainText("Stored runs and weather files are kept"); expect(patches).toEqual([]);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click(); expect(patches).toEqual([]);
  await p.getByRole("button", { name: "Apply", exact: true }).click();
  await dialog.getByRole("button", { name: "Clear selection and apply" }).click(); await expect(dialog).toBeHidden();
  expect(patches).toEqual([{ latitude_deg: -7.25, clear_weather_selection: true }]);
  let after = await view(request, id); expect(after.bundle.project.site.latitude_deg).toBe(-7.25); expect(after.scene_view.site.latitude_deg).toBe(-7.25);
  expect(after.bundle.weather_selection).toBeNull(); expect(after.bundle.simulation_runs).toEqual(before.bundle.simulation_runs);
  expect(after.scene_view.local_features).toEqual(before.scene_view.local_features); assertDirectories(id, true);
  // Re-pin to prove a name-only edit does not invalidate weather or open a dialog.
  pinSyntheticWeather([id]); await open(page, name);
  const rePinned = (await view(request, id)).bundle.weather_selection;
  await p.getByLabel("Site name", { exact: true }).fill("Site name only"); await p.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(p.getByRole("button", { name: "Apply", exact: true })).toBeDisabled();
  await expect(page.getByRole("alertdialog")).toHaveCount(0); expect(patches.at(-1)).toEqual({ name: "Site name only" });
  after = await view(request, id); expect(after.bundle.weather_selection).toEqual(rePinned);
  await page.getByRole("button", { name: "Projects", exact: true }).click();
  const row = page.locator(".tbl--projects tbody tr", { hasText: name }); await row.getByRole("button", { name: "Rename", exact: true }).click();
  const rename = page.getByRole("dialog", { name: "Rename", exact: true }); const renamed = `${name} renamed`;
  await rename.getByLabel("Project name", { exact: true }).fill(renamed); await rename.getByRole("button", { name: "Rename", exact: true }).click(); await expect(rename).toBeHidden();
  expect((await view(request, id)).bundle.project.name).toBe(renamed);
  await row.getByRole("button", { name: "Delete", exact: true }).click(); const deletion = page.getByRole("alertdialog", { name: "Delete", exact: true });
  await expect(deletion.getByRole("button", { name: "Delete", exact: true })).toBeDisabled();
  await deletion.getByLabel("Type the exact project name").fill(renamed);
  await deletion.getByRole("button", { name: "Delete", exact: true }).click(); await expect(deletion).toBeHidden(); await expect(row).toHaveCount(0);
  expect((await request.get(url(id))).status()).toBe(404); assertDirectories(id, false); expect(existsSync(path.join(STORE, `${id}.json`))).toBe(false);
  expect(await view(request, shared.id)).toEqual(otherBefore);
  // The snapshot is also still loadable through its owning project's weather revision.
  expect(existsSync(snapshot)).toBe(true);
  expect(readFileSync(path.join(STORE, `${shared.id}.json`), "utf8")).toContain(otherBefore.bundle.weather_selection.revision_id);
});

test("busy site refusal uses the engine message without reloading; already-deleted list entry refreshes", async ({ page, request }) => {
  const { id, name } = await create(request, "busy"); await open(page, name);
  let reloads = 0; page.on("request", (r) => { if (r.method() === "GET" && r.url().endsWith(`/projects/${id}`)) reloads++; });
  const message = "project has a simulation or weather acquisition in progress";
  await page.route(`**/api/projects/${id}/site`, (route) => route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: message }) }));
  await page.locator(".taskpanel").getByLabel("Site name", { exact: true }).fill("Busy site");
  await page.locator(".taskpanel").getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.locator(".toasts")).toContainText(message); await expect(page.locator(".toasts")).not.toContainText("changed elsewhere"); expect(reloads).toBe(0);
  expect((await view(request, id)).bundle.project.site.name).toBe(name);
  const listed = page.waitForResponse((r) => r.request().method() === "GET" && new URL(r.url()).pathname === "/api/projects");
  await page.getByRole("button", { name: "Projects", exact: true }).click(); await listed;
  const row = page.locator(".tbl--projects tbody tr", { hasText: name }); await expect(row).toBeVisible();
  expect((await request.delete(url(id) + `?confirm=${id}`)).ok()).toBe(true);
  await row.getByRole("button", { name: "Delete", exact: true }).click(); const deletion = page.getByRole("alertdialog", { name: "Delete", exact: true });
  await deletion.getByLabel("Type the exact project name").fill(name); await deletion.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(row).toHaveCount(0); await expect(page.locator(".toasts")).toContainText("already deleted");
});

test("loss panel matches the real defaults endpoint and offers only the hourly engine timestep", async ({ page, request }) => {
  const { name } = await create(request, "defaults"); const response = await request.get(`${API}/api/simulation-defaults`); expect(response.ok()).toBe(true);
  const defaults = await response.json(); await open(page, name); await page.keyboard.press("Alt+8");
  await openSection(page, "Losses");
  const losses = page.locator(".section", { has: page.getByRole("button", { name: "Losses", exact: true }) });
  await expect(losses).toContainText("Applied by the engine");
  await openSection(page, "Optics & thermal");
  const optics = page.locator(".section", { has: page.getByRole("button", { name: "Optics & thermal", exact: true }) });
  const rows = [
    ["Albedo month 1 (dimensionless)", String(defaults.optics_thermal_settings.values.albedo.monthly_values[0])],
    ["Thermal Uc (W/(m²·K))", String(defaults.optics_thermal_settings.values.thermal.u_c_w_m2k)],
    ["Thermal Uv (W/(m²·K)/(m/s))", String(defaults.optics_thermal_settings.values.thermal.u_v_w_m2k_per_ms)]
  ];
  for (const [label, value] of rows) await expect(optics.getByLabel(label, { exact: true })).toHaveValue(value);
  expect(defaults.module_quality).toEqual({ source: "pinned_module_definition", fallback_loss_fraction: 0 });
  await expect(losses).toContainText(`Module quality: from the pinned module definition (default ${defaults.module_quality.fallback_loss_fraction * 100} %; negative = gain)`);
  expect(defaults.not_modelled).toEqual([]);
  await expect(losses).toContainText("Recommended defaults");
  await expect(losses.getByLabel("Soiling month 1 (%)", { exact: true })).toHaveValue(String(defaults.loss_settings.values.soiling.monthly_fractions[0] * 100));
  await expect(losses.getByRole("button", { name: "Save losses", exact: true })).toBeVisible();
  await page.keyboard.press("Alt+7");
  for (const name of ["1", "5", "15"]) await expect(page.getByRole("radio", { name, exact: true })).toBeDisabled();
  await expect(page.getByRole("radio", { name: "60 min (engine)", exact: true })).toHaveAttribute("aria-checked", "true");
});
