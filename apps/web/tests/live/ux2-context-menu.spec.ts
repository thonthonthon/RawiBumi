import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("UX2 requires the disposable test API, never var/projects.");

type Vec2 = [number, number];
type Surface = { surface_id: string; name: string; boundary_2d: { vertices: Vec2[] }; slope_deg: number; azimuth_deg: number };

/** World metres to page pixels, from the plan's read-only view attribute and the same formula as toScreen. */
async function at(page: Page, p: Vec2): Promise<Vec2> {
  const canvas = page.locator("canvas.plan__canvas");
  const [cx, cy, scale] = (await canvas.getAttribute("data-plan-view"))!.split(" ").map(Number);
  const box = (await canvas.boundingBox())!;
  return [box.x + (p[0] - cx) * scale + box.width / 2, box.y + box.height / 2 - (p[1] - cy) * scale];
}
async function surfaces(request: APIRequestContext, id: string): Promise<Surface[]> {
  return (await (await request.get(`${API}/api/projects/${id}`)).json()).bundle.scene.surfaces;
}
const menu = (page: Page) => page.getByRole("menu", { name: "Plan actions" });
const item = (page: Page, id: string) => menu(page).locator(`[data-menu-item="${id}"]`);
const command = (page: Page, id: string) => page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/scene/commands`) && r.request().method() === "POST");

test("engine duplicate and undo, vertex insert and Delete, and the reference edge from the menu and by picking", async ({ page, request }) => {
  const name = `UX2 menu ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true); const id: string = (await created.json()).bundle.project.project_id;
  expect((await request.post(`${API}/api/projects/${id}/surfaces/rectangle`, { data: { name: "Live roof", width_m: 10, height_m: 6, base_elevation_m: 6 } })).ok()).toBe(true);
  const roof = (await surfaces(request, id))[0];
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+3");
  await page.locator(".taskpanel .layer__name", { hasText: "Live roof" }).click();

  // Duplicate from the keyboard menu: one engine copy command, labelled, undone by Ctrl+Z.
  await page.locator("canvas.plan__canvas").hover();
  await page.keyboard.press("Shift+F10");
  const copied = command(page, id);
  await item(page, "duplicate").click();
  const copy = await copied; expect(copy.status()).toBe(200);
  const body = JSON.parse(copy.request().postData()!);
  expect(body.command).toMatchObject({ command_type: "copy", target_entity_ids: [roof.surface_id], parameters: { dx_m: 11, dy_m: 0 } });
  const after = await copy.json();
  expect(after.history.past.at(-1).label).toBe("Duplicate Live roof.");
  const clone = (await surfaces(request, id)).find((s) => s.name === "Live roof copy")!;
  expect(clone.boundary_2d.vertices.map(([x, y]) => [x - 11, y])).toEqual(roof.boundary_2d.vertices);
  const undone = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/undo`));
  await page.keyboard.press("Control+z"); expect((await undone).status()).toBe(200);
  await expect.poll(async () => (await surfaces(request, id)).some((s) => s.name === "Live roof copy")).toBe(false);

  // Insert a vertex on edge AB from the menu, then select it by clicking and press Delete.
  await page.locator(".taskpanel .layer__name", { hasText: "Live roof" }).click();
  await page.mouse.click(...await at(page, [5, 0]), { button: "right" });
  const inserted = command(page, id);
  await item(page, "insertVertex").click(); expect((await inserted).status()).toBe(200);
  await expect.poll(async () => (await surfaces(request, id))[0].boundary_2d.vertices.length).toBe(5);
  const added = (await surfaces(request, id))[0].boundary_2d.vertices[1];
  await page.mouse.click(...await at(page, added));
  const removed = command(page, id);
  await page.keyboard.press("Delete"); expect((await removed).status()).toBe(200);
  await expect.poll(async () => (await surfaces(request, id))[0].boundary_2d.vertices).toEqual(roof.boundary_2d.vertices);

  // Reference edge BC from the menu, then CD by picking; the Inspector drop-down follows.
  const reference = page.locator(".inspector select").filter({ has: page.locator("option", { hasText: /^AB$/ }) });
  await page.mouse.click(...await at(page, [10, 3]), { button: "right" });
  const plane = command(page, id);
  await item(page, "referenceEdge").click(); expect((await plane).status()).toBe(200);
  await expect(reference).toHaveValue("1");
  const bc = (await surfaces(request, id))[0];
  expect(bc.slope_deg).toBe(5);
  await page.getByRole("button", { name: "Pick on plan", exact: true }).click();
  await expect(page.locator("[data-reference-pick]")).toBeVisible();
  const picked = command(page, id);
  await page.mouse.click(...await at(page, [5, 6])); expect((await picked).status()).toBe(200);
  await expect(reference).toHaveValue("2");
  await expect(page.locator("[data-reference-pick]")).toHaveCount(0);
  expect((await surfaces(request, id))[0].azimuth_deg).not.toBe(bc.azimuth_deg);
  expect(errors).toEqual([]);
});
