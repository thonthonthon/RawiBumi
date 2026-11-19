import { expect, test } from "@playwright/test";
import { openSection } from "../e2e/sections";

const API = process.env.RAWIBUMI_API;
if (!API || !/^http:\/\/127\.0\.0\.1:\d+$/.test(API) || API.endsWith(":8000"))
  throw new Error("USE4A requires a disposable API on a checked free port, never 8000.");

test("Systems confirms buildings, renames one, and changes a warning-only distance threshold", async ({ page, request }) => {
  const name = `USE4A ${Date.now()} ${Math.random()}`;
  const created = await request.post(`${API}/api/projects`, { data: { name, latitude_deg: -6.2, longitude_deg: 106.8, timezone: "Asia/Jakarta", workspace_mode: "blank_engineering_plane" } });
  expect(created.ok()).toBe(true);
  const id: string = (await created.json()).bundle.project.project_id;
  const url = `${API}/api/projects/${id}`;
  try {
    for (const [i, x] of [0, 10, 80].entries()) {
      const roof = await request.post(url + "/surfaces/rectangle", { data: { name: `Roof ${i + 1}`, origin_x_m: x, width_m: 10, height_m: 5, base_elevation_m: 6 } });
      expect(roof.ok()).toBe(true);
      const sid = (await roof.json()).bundle.scene.surfaces[i].surface_id;
      const filled = await request.post(url + "/pv-fields", { data: { name: `PV ${i + 1}`, support_surface_id: sid,
        module_definition_revision_id: "mod-rawibumi-uat-550-r1", tilt_deg: 10, row_pitch_m: 3.2 } });
      expect(filled.ok()).toBe(true);
    }
    await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
    await page.goto("/"); await page.locator(".start__row", { hasText: name }).click();
    await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+5");
    const panel = page.locator("[data-systems-panel]");
    for (const title of ["Buildings", "Checks"]) await openSection(page, title);
    await expect(panel).toBeVisible();
    await panel.getByRole("button", { name: "Use suggested buildings", exact: true }).click();
    await expect(panel.getByLabel(/^Building name:/)).toHaveCount(2);
    const rename = page.waitForResponse(r => r.url().endsWith(`/projects/${id}/scene/commands`) && r.request().method() === "POST" && r.request().postDataJSON().command.parameters.name === "Main");
    await panel.getByLabel(/^Building name:/).first().fill("Main");
    await panel.getByLabel(/^Building name:/).first().press("Tab");
    expect((await rename).ok()).toBe(true);
    await expect(panel.locator("[data-distance-warning]")).toHaveCount(1);
    await expect(panel.locator("tbody")).toContainText("60.0 m");
    await panel.getByLabel("Distance warning threshold").fill("100");
    await panel.getByRole("button", { name: "Save threshold", exact: true }).click();
    await expect(panel.locator("[data-distance-warning]")).toHaveCount(0);
    const result = await request.get(url + "/systems/overview"); expect(result.ok()).toBe(true);
    const overview = await result.json();
    expect(overview.buildings).toHaveLength(2); expect(overview.threshold_m).toBe(100);
    expect(overview.orientation_groups).toHaveLength(1);
    for (const building of overview.buildings) await expect(panel.locator("[data-orientation-group]")).toContainText(building.name);
    expect(overview.orientation_groups[0].building_ids).toHaveLength(2);
  } finally {
    expect((await request.delete(url, { params: { confirm: id } })).ok()).toBe(true);
  }
});
