import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { openSection } from "../e2e/sections";
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("UX1 requires the disposable test API, never var/projects.");

type Vec2 = [number, number];
async function at(page: Page, p: Vec2): Promise<Vec2> {
  const canvas = page.locator("canvas.plan__canvas");
  const [cx, cy, scale] = (await canvas.getAttribute("data-plan-view"))!.split(" ").map(Number);
  const box = (await canvas.boundingBox())!;
  return [box.x + (p[0] - cx) * scale + box.width / 2, box.y + box.height / 2 - (p[1] - cy) * scale];
}
async function bundle(request: APIRequestContext, id: string) { return (await (await request.get(`${API}/api/projects/${id}`)).json()).bundle; }
const imageryPut = (page: Page, id: string) => page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/imagery`) && r.request().method() === "PUT");

test("overlay upload, form edit and undo, two-point calibration and lock persist on the engine without a scene revision", async ({ page, request }) => {
  const name = `UX1 imagery ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true); const id: string = (await created.json()).bundle.project.project_id;
  expect((await request.post(`${API}/api/projects/${id}/surfaces/rectangle`, { data: { name: "Traced roof", width_m: 10, height_m: 6, base_elevation_m: 6 } })).ok()).toBe(true);
  const sceneBefore = (await bundle(request, id)).scene.revision_id;
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+1");
  const base64 = await page.evaluate(() => { const c = document.createElement("canvas"); c.width = 400; c.height = 300; const g = c.getContext("2d")!; g.fillStyle = "#3a7"; g.fillRect(0, 0, 400, 300); return c.toDataURL("image/png").split(",")[1]; });
  const png = Buffer.from(base64, "base64");
  await openSection(page, "Background image");
  const section = page.locator("[data-imagery-overlay]");
  const uploaded = page.waitForResponse((r) => r.url().includes(`/projects/${id}/imagery/assets?filename=`) && r.request().method() === "POST");
  const saved = imageryPut(page, id);
  await section.locator('input[type="file"]').setInputFiles({ name: "survey.png", mimeType: "image/png", buffer: png });
  const asset = await (await uploaded).json(); expect((await saved).status()).toBe(200);
  expect(asset).toMatchObject({ width_px: 400, height_px: 300, mime: "image/png" });
  expect(Buffer.from(await (await request.get(`${API}/api/projects/${id}/imagery/assets/${asset.asset_id}`)).body())).toEqual(png);
  await expect(section).toHaveAttribute("data-imagery-overlay", "unlocked");

  // A committed form value is one engine undo step; Ctrl+Z restores it.
  const rotation = section.getByLabel("Rotation");
  const rotated = imageryPut(page, id);
  await rotation.fill("15"); await rotation.press("Enter"); expect((await rotated).status()).toBe(200);
  await expect.poll(async () => (await bundle(request, id)).imagery.layers[0].orthophoto_georeference.control_points[1].local_y_m).not.toBeCloseTo(0.0 + 7.5, 3);
  const undone = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/undo`));
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("Control+z"); expect((await undone).status()).toBe(200);
  await expect(rotation).toHaveValue("0");

  // Two-point calibration on the plan: 8 m on the image becomes 12 m; the overlay locks.
  await page.keyboard.press("Alt+3");
  await page.locator("canvas.plan__canvas").hover();
  await page.keyboard.press("Shift+F10");
  await page.getByRole("menu", { name: "Plan actions" }).locator('[data-menu-item="overlayCalibrate"]').click();
  await page.mouse.click(...await at(page, [1, -2])); await page.mouse.click(...await at(page, [9, -2]));
  const calibrated = imageryPut(page, id);
  await page.getByLabel("True distance (m)").fill("12"); await page.getByLabel("True distance (m)").press("Enter");
  expect((await calibrated).status()).toBe(200);
  const stored = await bundle(request, id);
  const layer = stored.imagery.layers[0];
  expect(layer.locked).toBe(true);
  const [p0, p1] = layer.orthophoto_georeference.control_points;
  expect(Math.hypot(p1.local_x_m - p0.local_x_m, p1.local_y_m - p0.local_y_m) / 400).toBeCloseTo(0.075, 3);
  expect(stored.scene.revision_id).toBe(sceneBefore);
  expect(JSON.stringify(stored.imagery)).not.toMatch(/key=/);

  // Reload: the overlay and its lock come back from the project.
  await page.reload(); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+1");
  await expect(page.locator("[data-imagery-overlay]")).toHaveAttribute("data-imagery-overlay", "locked");
  await expect(page.locator("[data-imagery-overlay]").getByLabel("Resolution across")).toHaveValue("0.075");
  expect(errors).toEqual([]);
});
