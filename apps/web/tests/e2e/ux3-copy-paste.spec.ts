import { expect, test, type Page } from "@playwright/test";
import type { Vec2 } from "../../src/geometry";

// UX3 in the demo: dialog padding, vertex selection from the plan and the Inspector, copy and paste with PV.
async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function idle(page: Page) { await expect.poll(async () => (await state(page)).busy).toBeNull(); }
async function open(page: Page) {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+3");
  await expect(page.locator(".toollist")).toBeVisible(); await idle(page);
}
async function point(page: Page, p: Vec2): Promise<Vec2> {
  return page.evaluate(([x, y]) => (window as unknown as { __rawibumiPlan: { toPage(x: number, y: number): Vec2 } }).__rawibumiPlan.toPage(x, y), p);
}
const menu = (page: Page) => page.getByRole("menu", { name: "Plan actions" });
const entry = (page: Page, id: string) => menu(page).locator(`[data-menu-item="${id}"]`);
const surfaces = async (page: Page) => (await state(page)).view!.bundle.scene;
async function spare(page: Page) {
  await page.evaluate(async () => {
    const { mockApi } = await import("/src/demo/mockApi.ts");
    const { uiStore } = await import("/src/state/store.tsx");
    const v = await mockApi.sceneCommand(uiStore.getState().state.view!.bundle.project.project_id, { command_type: "draw_polygon", target_entity_ids: [],
      parameters: { name: "Spare", surface_type: "flat_roof", vertices: [[60, 0], [70, 0], [70, 8], [65, 12], [60, 8]], base_elevation_m: 6 } });
    uiStore.getState().dispatch({ type: "setView", view: v });
  });
  await idle(page);
  await page.evaluate(() => window.dispatchEvent(new Event("rawibumi:fit")));
}

test("dialogs keep their content off the border", async ({ page }) => {
  await page.goto("/");
  await page.locator(".start__map .map-basemaps").getByRole("button", { name: "Set up imagery provider", exact: true }).click();
  expect(await page.locator("[data-imagery-provider]").evaluate((e) => getComputedStyle(e).paddingLeft)).toBe("16px");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Expand map", exact: true }).click();
  expect(await page.locator("[data-expanded-map]").evaluate((e) => getComputedStyle(e).paddingLeft)).toBe("16px");
});

test("copy a roof with its PV, paste it from the menu at the click point and by keys beside it, then undo", async ({ page }) => {
  await open(page);
  const before = await surfaces(page);
  const fields = before.pv_fields.length, modules = before.module_instances.length;
  const roofModules = before.module_instances.filter((m) => m.pv_field_id === "fld-a").length;
  await page.mouse.click(...await point(page, [0.6, 9]));
  await expect.poll(async () => (await state(page)).selection).toEqual(["srf-roof-a"]);
  await page.keyboard.press("Control+c");
  await expect(page.locator(".toast").last()).toContainText("Copied Roof A");
  await page.mouse.click(...await point(page, [21, 40]), { button: "right" });
  await entry(page, "paste").click(); await idle(page);
  let scene = await surfaces(page);
  const copy = scene.surfaces.find((s) => s.name === "Roof A copy")!;
  expect(copy).toBeTruthy();
  const pasted = scene.pv_fields.find((f) => f.support_surface_id === copy.surface_id)!;
  expect(pasted.name).toContain("copy");
  expect(scene.module_instances.filter((m) => m.pv_field_id === pasted.pv_field_id)).toHaveLength(roofModules);
  const strung = new Set((await state(page)).view!.bundle.electrical_design.strings.flatMap((s) => s.module_instance_ids));
  expect(scene.module_instances.filter((m) => m.pv_field_id === pasted.pv_field_id).some((m) => strung.has(m.module_instance_id))).toBe(false);
  const copied = (await state(page)).entities.find((e) => e.id === copy.surface_id)!;
  const ys = copied.polygon.map((p) => p[1]);
  // The right-click lands on a screen pixel, so the centre matches to within a pixel (about 0.06 m here).
  expect(Math.abs((Math.min(...ys) + Math.max(...ys)) / 2 - 40)).toBeLessThan(0.1);
  await page.mouse.move(5, 5);
  await page.keyboard.press("Control+v"); await idle(page);
  scene = await surfaces(page);
  expect(scene.surfaces.filter((s) => s.name === "Roof A copy")).toHaveLength(2);
  await page.keyboard.press("Control+z"); await idle(page);
  await page.keyboard.press("Control+z"); await idle(page);
  scene = await surfaces(page);
  expect([scene.pv_fields.length, scene.module_instances.length]).toEqual([fields, modules]);
});

test("vertices: right-click selects, the Inspector lists, selects and deletes them, with the 3-vertex reason", async ({ page }) => {
  await open(page);
  await spare(page);
  await page.mouse.click(...await point(page, [64, 5]));
  await page.mouse.click(...await point(page, [65, 12]), { button: "right" });
  await expect.poll(async () => (await state(page)).vertex).toMatchObject({ ring: 0, index: 3 });
  await page.keyboard.press("Escape");
  const rows = page.locator(".inspector [data-vertex-row]");
  await expect(rows).toHaveCount(5);
  await expect(rows.nth(3)).toHaveClass(/tbl__row--selected/);
  await rows.nth(1).click();
  await expect.poll(async () => (await state(page)).vertex).toMatchObject({ ring: 0, index: 1 });
  await rows.nth(1).getByRole("button", { name: "Delete vertex B", exact: true }).click(); await idle(page);
  await expect(rows).toHaveCount(4);
  await rows.nth(0).getByRole("button", { name: "Delete vertex A", exact: true }).click(); await idle(page);
  await expect(rows).toHaveCount(3);
  const last = rows.nth(0).getByRole("button", { name: "Delete vertex A", exact: true });
  await expect(last).toHaveAttribute("aria-disabled", "true");
  await expect(last).toHaveAttribute("title", "A polygon needs at least 3 vertices");
});
