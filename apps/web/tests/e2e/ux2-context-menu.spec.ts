import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import type { Vec2 } from "../../src/geometry";

// UX2 in the demo: the plan's right-click menu, Shift+F10, vertex select + Delete, the on-plan reference edge, Duplicate.
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
async function click(page: Page, p: Vec2) { await page.mouse.click(...await point(page, p)); }
async function rightClick(page: Page, p: Vec2) { await page.mouse.click(...await point(page, p), { button: "right" }); }
const menu = (page: Page) => page.getByRole("menu", { name: "Plan actions" });
const entry = (page: Page, id: string) => menu(page).locator(`[data-menu-item="${id}"]`);
async function spare(page: Page) {
  // A five-sided roof away from the array, so vertex and edge edits are free of PV-field rules.
  await page.evaluate(async () => {
    const { mockApi } = await import("/src/demo/mockApi.ts");
    const { uiStore } = await import("/src/state/store.tsx");
    const v = await mockApi.sceneCommand(uiStore.getState().state.view!.bundle.project.project_id, { command_type: "draw_polygon", target_entity_ids: [],
      parameters: { name: "Spare", surface_type: "flat_roof", vertices: [[60, 0], [70, 0], [70, 8], [65, 12], [60, 8]], base_elevation_m: 6 } });
    uiStore.getState().dispatch({ type: "setView", view: v });
  });
  await idle(page);
  await expect.poll(async () => !!(await entity(page, "Spare"))).toBe(true);
  // Fit once the plan has the new roof, so every test point is on screen.
  await page.evaluate(() => window.dispatchEvent(new Event("rawibumi:fit")));
  return (await state(page)).entities.find((e) => e.name === "Spare")!;
}
const entity = async (page: Page, name: string) => (await state(page)).entities.find((e) => e.name === name);

test("the empty-canvas menu: keyboard and pointer, focus return, and right-drag still pans", async ({ page }) => {
  await open(page);
  await page.keyboard.press("Shift+F10");
  await expect(menu(page)).toBeVisible();
  // Nothing to undo yet: Undo and Redo are disabled, so focus starts on the first enabled item.
  await expect(entry(page, "undo")).toHaveAttribute("aria-disabled", "true");
  await expect(entry(page, "selectAll")).toBeFocused();
  await expect(entry(page, "selectAll")).toBeVisible();
  await expect(entry(page, "tool:polygon")).toBeVisible();
  expect((await new AxeBuilder({ page }).include(".ctxmenu").withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze()).violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(menu(page)).toHaveCount(0);
  await rightClick(page, [45, 9]);
  await expect(menu(page)).toBeVisible();
  for (let i = 0; i < 20 && !(await entry(page, "selectAll").evaluate((e) => e === document.activeElement)); i++) await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(menu(page)).toHaveCount(0);
  await expect.poll(async () => (await state(page)).selection.length).toBe((await state(page)).entities.filter((e) => !e.hidden).length);
  await rightClick(page, [45, 9]);
  await entry(page, "clearSelection").click();
  await expect.poll(async () => (await state(page)).selection).toEqual([]);
  const before = await page.evaluate(() => (window as unknown as { __rawibumiPlan: { view: unknown } }).__rawibumiPlan.view);
  const [x, y] = await point(page, [45, 9]);
  await page.mouse.move(x, y); await page.mouse.down({ button: "right" }); await page.mouse.move(x + 80, y + 40, { steps: 6 }); await page.mouse.up({ button: "right" });
  await expect(menu(page)).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __rawibumiPlan: { view: unknown } }).__rawibumiPlan.view)).not.toEqual(before);
});

test("object menu: duplicate and undo through the menu, lock with reasons, delete", async ({ page }) => {
  await open(page);
  const roof = await spare(page);
  await rightClick(page, [64, 5]);
  await expect.poll(async () => (await state(page)).selection).toEqual([roof.id]);
  await expect(entry(page, "addHole")).toBeVisible();
  await entry(page, "properties").click();
  await expect.poll(() => page.evaluate(() => !!document.activeElement?.closest(".inspectorpane"))).toBe(true);
  await rightClick(page, [64, 5]);
  await entry(page, "duplicate").click(); await idle(page);
  await expect.poll(async () => !!(await entity(page, "Spare copy"))).toBe(true);
  const copy = (await entity(page, "Spare copy"))!;
  expect(copy.polygon[0][0]).toBeCloseTo(71, 6);
  await rightClick(page, [45, 9]);
  await entry(page, "undo").click(); await idle(page);
  await expect.poll(async () => !!(await entity(page, "Spare copy"))).toBe(false);
  await rightClick(page, [64, 5]); await entry(page, "lock").click();
  await rightClick(page, [64, 5]);
  await expect(entry(page, "move")).toHaveAttribute("aria-disabled", "true");
  await expect(entry(page, "move")).toContainText("Spare is locked");
  // A disabled item does nothing and keeps the menu open.
  await entry(page, "move").click({ force: true });
  await expect(menu(page)).toBeVisible();
  expect((await state(page)).tool).toBe("select");
  await entry(page, "unlock").click();
  // Delete goes through the existing confirmation, exactly like the Delete key.
  await rightClick(page, [64, 5]); await entry(page, "delete").click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await dialog.locator(".btn--danger").click(); await idle(page);
  await expect.poll(async () => !!(await entity(page, "Spare"))).toBe(false);
});

test("vertex: delete by menu, select and Delete, and the 3-vertex limit with its reason", async ({ page }) => {
  await open(page);
  const roof = await spare(page);
  await click(page, [64, 5]);
  await rightClick(page, [65, 12]);
  await entry(page, "deleteVertex").click(); await idle(page);
  await expect.poll(async () => (await entity(page, "Spare"))!.polygon.length).toBe(4);
  await click(page, [70, 8]);
  await page.keyboard.press("Delete"); await idle(page);
  await expect.poll(async () => (await entity(page, "Spare"))!.polygon.length).toBe(3);
  expect((await entity(page, "Spare"))!.id).toBe(roof.id);
  await rightClick(page, [60, 0]);
  await expect(entry(page, "deleteVertex")).toHaveAttribute("aria-disabled", "true");
  await expect(entry(page, "deleteVertex")).toContainText("A polygon needs at least 3 vertices");
  await page.keyboard.press("Escape");
  await click(page, [70, 0]);
  await page.keyboard.press("Escape");
  expect((await state(page)).selection).toEqual([roof.id]);
});

test("edges: insert a vertex, set the reference edge from the menu and by picking, in sync with the Inspector", async ({ page }) => {
  await open(page);
  await spare(page);
  await click(page, [64, 5]);
  await rightClick(page, [65, 0]);
  await expect(entry(page, "referenceEdge")).toBeVisible();
  await entry(page, "insertVertex").click(); await idle(page);
  await expect.poll(async () => (await entity(page, "Spare"))!.polygon.length).toBe(6);
  await rightClick(page, [60, 4]);
  await entry(page, "referenceEdge").click(); await idle(page);
  await expect.poll(async () => (await entity(page, "Spare"))!.plane).toMatchObject({ mode: "edge_tilt", edgeIndex: 5 });
  const select = page.locator(".inspector select").filter({ has: page.locator('option[value="5"]') }).first();
  await expect(select).toHaveValue("5");
  await page.getByRole("button", { name: "Pick on plan", exact: true }).click();
  await expect(page.locator("[data-reference-pick]")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-reference-pick]")).toHaveCount(0);
  await page.getByRole("button", { name: "Pick on plan", exact: true }).click();
  await click(page, [70, 4]); await idle(page);
  await expect(page.locator("[data-reference-pick]")).toHaveCount(0);
  await expect.poll(async () => (await entity(page, "Spare"))!.plane).toMatchObject({ mode: "edge_tilt", edgeIndex: 2 });
  await expect(select).toHaveValue("2");
});

test("modules get their own menu, and an obstacle duplicates beside itself as one undo step", async ({ page }) => {
  await open(page);
  await rightClick(page, [10, 9]);
  await expect(entry(page, "deleteModules")).toBeVisible();
  await page.keyboard.press("Escape");
  await page.locator(".taskpanel .layer__name", { hasText: "AHU-1" }).click();
  await rightClick(page, [31.5, 12]);
  await expect(entry(page, "addHole")).toHaveCount(0);
  await entry(page, "duplicate").click(); await idle(page);
  await expect.poll(async () => (await entity(page, "AHU-1 copy"))?.polygon[0][0]).toBeCloseTo(34.2, 6);
  await page.keyboard.press("Control+z"); await idle(page);
  await expect.poll(async () => !!(await entity(page, "AHU-1 copy"))).toBe(false);
});
