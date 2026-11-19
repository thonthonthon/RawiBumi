import { expect, test, type Page } from "@playwright/test";
import type { Vec2 } from "../../src/geometry";
async function state(page: Page) { return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state); }
async function open(page: Page) {
  await page.goto("/"); await page.locator(".start__row").first().click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+4");
  await page.evaluate(async () => {
    const { mockApi } = await import("/src/demo/mockApi.ts");
    const w = window as unknown as { s13cCalls: unknown[] }; w.s13cCalls = [];
    const original = mockApi.moduleCommands;
    mockApi.moduleCommands = (...args) => { w.s13cCalls.push(structuredClone(args[1])); return original(...args); };
  });
}
async function point(page: Page, p: Vec2): Promise<Vec2> { return page.evaluate(([x, y]) => (window as unknown as { __rawibumiPlan: { toPage(x: number, y: number): Vec2 } }).__rawibumiPlan.toPage(x, y), p); }
async function calls(page: Page) { return page.evaluate(() => (window as unknown as { s13cCalls: Array<Record<string, unknown>> }).s13cCalls); }
const centre = (polygon: Vec2[]): Vec2 => polygon.reduce<Vec2>((v, p) => [v[0] + p[0] / polygon.length, v[1] + p[1] / polygon.length], [0, 0]);

test("refused demo drag gives plain reasons and an honest unavailable fill, with no Confirm or fake change", async ({ page }) => {
  await open(page); const before = await state(page); const a=centre(before.modules[0].polygon);
  await page.mouse.click(...await point(page,a)); await page.mouse.move(...await point(page,a)); await page.mouse.down(); await page.keyboard.down("Shift");
  await page.mouse.move(...await point(page,[a[0]+1,a[1]]),{steps:6});await page.mouse.up(); await page.keyboard.up("Shift");
  const dialog=page.getByRole("alertdialog",{name:"These modules don't fit exactly there. Fit into this space?"});
  await expect(dialog).toContainText("1 module would overlap other modules");
  await expect(dialog).toContainText("Drop-to-fill needs the engine");
  await expect(dialog.getByRole("button",{name:"Confirm fill",exact:true})).toHaveCount(0);
  expect(await calls(page)).toEqual([
    {command:"move_modules",module_instance_ids:[before.modules[0].id],dx_m:expect.closeTo(1,9),dy_m:expect.closeTo(0,9)},
    {command:"move_modules",module_instance_ids:[before.modules[0].id],dx_m:expect.closeTo(1,9),dy_m:expect.closeTo(0,9),on_conflict:"fill",dry_run:true}
  ]);
  await dialog.getByRole("button",{name:"Cancel",exact:true}).click();await expect(dialog).toBeHidden();
  expect((await state(page)).view).toEqual(before.view);expect(await calls(page)).toHaveLength(2);
});

test("a refused nudge has a plain toast and never offers fill",async({page})=>{
  await open(page);const before=await state(page);await page.mouse.click(...await point(page,centre(before.modules[0].polygon)));
  await page.keyboard.press("Shift+ArrowRight");await expect(page.locator(".toasts")).toContainText("1 module would overlap other modules");
  await expect(page.getByRole("alertdialog")).toHaveCount(0);expect(await calls(page)).toHaveLength(1);
  expect((await state(page)).view).toEqual(before.view);
});
