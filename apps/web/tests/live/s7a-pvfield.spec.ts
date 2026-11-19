import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// Start scripts/serve-live-test-api.py --port <checked free port>, then run
// RAWIBUMI_API=http://127.0.0.1:PORT npm run test:live -- scene-routes.spec.ts s7a-pvfield.spec.ts.
// That exact launcher uses <repo>/tmp/live-projects, never var/projects/user data.
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000"))
  throw new Error("S7a live tests require the isolated test launcher on RAWIBUMI_API (checked free port, not 8000).");

async function setup(request: APIRequestContext, suffix: string) {
  expect((await request.get(`${API}/api/health`)).ok()).toBe(true);
  const name = `S7a ${suffix} ${Date.now()}`;
  const result = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8,
    timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(result.ok()).toBe(true);
  const id: string = (await result.json()).bundle.project.project_id;
  expect((await request.post(`${API}/api/projects/${id}/surfaces/rectangle`, { data: {
    name: "S7a roof", width_m: 20, height_m: 10, base_elevation_m: 0 } })).ok()).toBe(true);
  return { id, name };
}
async function open(page: Page, name: string) {
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+4");
}
async function view(request: APIRequestContext, id: string) {
  const response = await request.get(`${API}/api/projects/${id}`); expect(response.ok()).toBe(true); return response.json();
}

test("F4: browser re-fills tilt 10 to 15, confirms string removal, then deletes the field", async ({ page, request }) => {
  const { id, name } = await setup(request, "F4"); await open(page, name);
  const p = page.locator(".taskpanel");
  await p.getByLabel("Field name").fill("Live S7a array");
  await expect(p.getByRole("button", { name: "Apply fill", exact: true })).toBeEnabled();
  await p.getByRole("button", { name: "Apply fill", exact: true }).click();
  await expect(p.locator(".card-row", { hasText: "Live S7a array" })).toContainText("tilt 10°");
  const count = (await view(request, id)).bundle.scene.module_instances.length; expect(count).toBeGreaterThan(0);
  const strings = await request.post(`${API}/api/projects/${id}/strings`, { data: { string_length: 16, allow_shorter_remainder: true } });
  expect(strings.ok()).toBe(true);
  const ids: string[] = (await strings.json()).bundle.electrical_design.strings.map((s: { string_id: string }) => s.string_id);
  expect(ids.length).toBeGreaterThan(0); await open(page, name);
  const patches: Record<string, unknown>[] = [];
  page.on("request", (r) => { if (r.method() === "PATCH" && r.url().includes("/pv-fields/")) patches.push(r.postDataJSON()); });
  await p.locator(".card-row", { hasText: "Live S7a array" }).getByRole("button", { name: "Re-fill", exact: true }).click();
  await p.getByLabel("Tilt").fill("15"); await p.getByRole("button", { name: "Apply re-fill" }).click();
  const dialog = page.getByRole("alertdialog", { name: "Preview re-fill", exact: true });
  await expect(dialog).toContainText(`Modules: ${count} →`); for (const id of ids) await expect(dialog).toContainText(id);
  expect(patches).toHaveLength(1); expect(patches[0]).toHaveProperty("dry_run", true);
  expect(patches[0]).not.toHaveProperty("discard_dependent_strings"); expect(patches[0]).not.toHaveProperty("discard_manual_layout");
  await dialog.getByRole("button", { name: "Confirm re-fill", exact: true }).click();
  await expect(dialog).toBeHidden(); await expect(p.locator(".card-row")).toContainText("tilt 15°");
  expect(patches).toHaveLength(2); expect(patches[1]).toHaveProperty("discard_dependent_strings", true);
  expect(patches[1]).not.toHaveProperty("discard_manual_layout"); expect(patches[1]).not.toHaveProperty("dry_run");
  let v = await view(request, id); expect(v.bundle.scene.pv_fields).toHaveLength(1);
  expect(v.bundle.scene.pv_fields[0].tilt_deg).toBe(15); expect(v.bundle.electrical_design.strings).toEqual([]);
  const readiness = await request.get(`${API}/api/projects/${id}/execution-readiness`);
  expect((await readiness.json()).findings.some((f: { rule_id: string }) => f.rule_id === "MODULES_NOT_SIMULATED")).toBe(true);
  await p.getByRole("button", { name: "Delete field", exact: true }).click();
  const deletion = page.getByRole("alertdialog", { name: "Preview field deletion" }); await expect(deletion).toContainText("No strings will be deleted.");
  await deletion.getByRole("button", { name: "Confirm delete field" }).click(); await expect(p.locator(".card-row")).toHaveCount(0);
  v = await view(request, id); expect(v.bundle.scene.pv_fields).toEqual([]); expect(v.bundle.scene.module_instances).toEqual([]);
});

test("real string refusals reach the toast and obstacle refusals open the dialog", async ({ page, request }) => {
  const { id, name } = await setup(request, "errors"); await open(page, name); const p = page.locator(".taskpanel");
  await expect(p.getByRole("button", { name: "Apply fill", exact: true })).toBeEnabled();
  await p.getByRole("button", { name: "Apply fill", exact: true }).click(); await expect(p.locator(".card-row")).toHaveCount(1);
  await p.getByRole("button", { name: "Re-fill", exact: true }).click(); await p.getByLabel("Tilt").fill("95");
  const refused = page.waitForResponse((r) => r.request().method() === "PATCH" && r.url().includes("/pv-fields/"));
  await p.getByRole("button", { name: "Apply re-fill" }).click(); const error = await refused; expect(error.status()).toBe(422);
  const detail = (await error.json()).detail; expect(typeof detail).toBe("string"); await expect(page.locator(".toasts")).toContainText(detail);
  const v = await view(request, id); const module = v.scene_view.local_features.find((f: { category: string }) => f.category === "module");
  const centre = [0, 1].map((axis) => module.polygon.reduce((a: number, point: number[]) => a + point[axis], 0) / module.polygon.length);
  await page.keyboard.press("Alt+3"); await page.waitForTimeout(300); await page.keyboard.press("o");
  const boxRefusal = page.waitForResponse((r) => r.url().endsWith("/obstacles/box") && r.request().method() === "POST");
  for (const text of [`${centre[0].toFixed(3)},${centre[1].toFixed(3)}`, "@0.5,0.5"]) { await page.keyboard.type(text); await expect(page.locator(".plan__typed")).toBeVisible(); await page.keyboard.press("Enter"); }
  const box = await boxRefusal; expect(box.status()).toBe(422);
  const structured = (await box.json()).detail; expect(structured.message).toBeTruthy(); expect(structured.conflicts.length).toBeGreaterThan(0);
  const obstacleDialog = page.getByRole("alertdialog", { name: "Obstacle on modules", exact: true });
  await expect(obstacleDialog).toBeVisible(); await expect(obstacleDialog).toContainText(structured.message);
  await expect(page.locator(".toasts")).not.toContainText(structured.message); await expect(page.locator(".toasts")).not.toContainText("Unprocessable Entity");
  await obstacleDialog.getByRole("button", { name: "Cancel obstacle", exact: true }).click(); await expect(obstacleDialog).toBeHidden();
  expect((await view(request, id)).bundle.scene.obstacles).toHaveLength(v.bundle.scene.obstacles.length);
});
