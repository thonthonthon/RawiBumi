import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("UX3 requires the disposable test API, never var/projects.");

type Vec2 = [number, number];
async function at(page: Page, p: Vec2): Promise<Vec2> {
  const canvas = page.locator("canvas.plan__canvas");
  const [cx, cy, scale] = (await canvas.getAttribute("data-plan-view"))!.split(" ").map(Number);
  const box = (await canvas.boundingBox())!;
  return [box.x + (p[0] - cx) * scale + box.width / 2, box.y + box.height / 2 - (p[1] - cy) * scale];
}
async function bundle(request: APIRequestContext, id: string) { return (await (await request.get(`${API}/api/projects/${id}`)).json()).bundle; }
const commands = (page: Page, id: string) => page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/scene/commands`) && r.request().method() === "POST");

test("paste a roof with its PV on the engine: overlap refused, a free paste copies the field unstrung, undo removes it", async ({ page, request }) => {
  const name = `UX3 paste ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true); const id: string = (await created.json()).bundle.project.project_id;
  const url = `${API}/api/projects/${id}`;
  const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "Source roof", width_m: 1 + 18 * 1.154 - .01, height_m: 3.45, base_elevation_m: 6.1 } });
  const sid = (await roof.json()).bundle.scene.surfaces[0].surface_id;
  expect((await request.post(url + "/pv-fields", { data: { name: "Source array", support_surface_id: sid, module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: 10, row_pitch_m: 3.2, perimeter_setback_m: .5 } })).ok()).toBe(true);
  const before = await bundle(request, id);
  const errors: string[] = []; page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+3");
  await page.locator(".taskpanel .layer__name", { hasText: "Source roof" }).click();
  await page.locator("canvas.plan__canvas").hover();
  await page.keyboard.press("Control+c");
  await expect(page.locator(".toast").last()).toContainText("Copied Source roof");

  // Pasting onto the original overlaps its modules: refused, nothing written.
  const refused = commands(page, id);
  await page.mouse.move(...await at(page, [11, 1.7]));
  await page.keyboard.press("Control+v");
  expect((await refused).status()).toBe(422);
  expect((await bundle(request, id)).scene).toEqual(before.scene);
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("overlaps");
  await page.keyboard.press("Escape");

  // A free spot: zoom out, then paste there from the right-click menu.
  for (let i = 0; i < 4; i++) await page.mouse.wheel(0, 400);
  await page.mouse.click(...await at(page, [11, 12]), { button: "right" });
  const pasted = commands(page, id);
  await page.getByRole("menu", { name: "Plan actions" }).locator('[data-menu-item="paste"]').click();
  const response = await pasted; expect(response.status()).toBe(200);
  expect(JSON.parse(response.request().postData()!).command.parameters.with_pv).toBe(true);
  const after = await bundle(request, id);
  const copy = after.scene.surfaces.find((s: { name: string }) => s.name === "Source roof copy");
  const field = after.scene.pv_fields.find((f: { support_surface_id: string }) => f.support_surface_id === copy.surface_id);
  expect(field.name).toBe("Source array copy");
  const modules = after.scene.module_instances.filter((m: { pv_field_id: string }) => m.pv_field_id === field.pv_field_id);
  expect(modules).toHaveLength(before.scene.module_instances.length);
  expect(after.electrical_design.strings).toEqual(before.electrical_design.strings);

  const undone = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/undo`));
  await page.keyboard.press("Control+z"); expect((await undone).status()).toBe(200);
  await expect.poll(async () => (await bundle(request, id)).scene.pv_fields.length).toBe(before.scene.pv_fields.length);
  expect(errors).toEqual([]);
});
