import { expect, test } from "@playwright/test";

// USE3 on the real engine: a 12° roof facing south, filled Parallel to roof, gives a field with the roof's tilt and
// azimuth, and its re-fill opens as Parallel.
const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000")) throw new Error("USE3 requires the disposable test API, never var/projects.");

test("a parallel-to-roof fill takes the roof's tilt and azimuth", async ({ page, request }) => {
  const name = `USE3 ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  const id: string = (await created.json()).bundle.project.project_id;
  const url = `${API}/api/projects/${id}`;
  const roof = await request.post(url + "/surfaces/rectangle", { data: { name: "Pitched roof", width_m: 12, height_m: 8, base_elevation_m: 6 } });
  const sid: string = (await roof.json()).bundle.scene.surfaces[0].surface_id;
  const plane = await request.post(url + "/scene/commands", { data: { command: { schema_name: "SceneEditorCommand", schema_version: "0.1", command_id: `use3-${Date.now()}`,
    command_type: "edit_plane", target_entity_ids: [sid], parameters: { slope_deg: 12, azimuth_deg: 180, base_elevation_m: 6, elevation_reference: { mode: "explicit_xy", x_m: 0, y_m: 0 } } } } });
  expect(plane.ok()).toBe(true);

  await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
  await page.goto("/"); await page.locator(".start__row", { hasText: name }).click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+4");
  const panel = page.locator(".taskpanel");
  await panel.getByRole("radio", { name: "Parallel to roof" }).click();
  await expect(panel.getByLabel(/^Tilt/)).toHaveValue("12");
  const filled = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/pv-fields`) && r.request().method() === "POST");
  await panel.getByRole("button", { name: "Apply fill", exact: true }).click();
  expect((await filled).ok()).toBe(true);
  const field = (await (await request.get(url)).json()).bundle.scene.pv_fields[0];
  expect([field.tilt_deg, field.azimuth_deg]).toEqual([12, 180]);
  await panel.getByRole("button", { name: "Re-fill", exact: true }).click();
  await expect(panel.getByRole("radio", { name: "Parallel to roof" })).toHaveAttribute("aria-checked", "true");
});
