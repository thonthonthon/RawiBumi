import { expect, test, type Page } from "@playwright/test";

async function open(page: Page) {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+3");
  await expect(page.locator(".toollist")).toBeVisible();
}
async function typed(page: Page, value: string) {
  await page.keyboard.type(value); await expect(page.locator(".plan__typed")).toBeVisible(); await page.keyboard.press("Enter");
  await expect(page.locator(".plan__typed")).toBeHidden();
}
async function state(page: Page) {
  return page.evaluate(async () => {
    const s = (await import("/src/state/store.tsx")).uiStore.getState().state;
    return { view: s.view!, entities: s.entities, selection: s.selection, busy: s.busy };
  });
}
async function point(page: Page, x: number, y: number): Promise<[number, number]> {
  return page.evaluate(([x, y]) => (window as unknown as { __rawibumiPlan: { toPage(x: number, y: number): [number, number] } }).__rawibumiPlan.toPage(x, y), [x, y]);
}
async function polygon(page: Page, tool: "p" | "k", points: number[][]) {
  await page.keyboard.press(tool);
  await expect(page.locator(".toollist").getByRole("button", { name: tool === "k" ? "K Keep-out zone" : "P Polygon roof", exact: true })).toHaveAttribute("aria-pressed", "true");
  for (const [x, y] of points) await typed(page, `${x},${y}`);
  await page.keyboard.press("Enter");
}

test("keep-out over modules previews strings, cancels without saving, then removes exactly the listed modules", async ({ page }) => {
  await open(page); const before = (await state(page)).view;
  const module = before.scene_view.local_features.find((f) => f.category === "module")!;
  const x = Math.min(...module.polygon.map((p) => p[0])) + .1, y = Math.min(...module.polygon.map((p) => p[1])) + .1;
  const points = [[x,y],[x+.3,y],[x+.3,y+.3]];
  await polygon(page, "k", points);
  const dialog = page.getByRole("alertdialog", { name: "Keep-out on modules", exact: true });
  await expect(dialog).toBeVisible(); await expect(dialog).toContainText("kWp STC");
  const impact = await page.evaluate(async () => (await import("/src/state/history.ts")).sceneRefusal.getState().pending!.detail.options!.remove_modules);
  expect(impact.module_count).toBeGreaterThan(0); expect(impact.string_ids.length).toBeGreaterThan(0);
  for (const id of impact.string_ids) await expect(dialog).toContainText(id);
  expect((await state(page)).view).toEqual(before);
  await dialog.getByRole("button", { name: "Cancel keep-out", exact: true }).click();
  await expect(dialog).toBeHidden(); expect((await state(page)).view).toEqual(before);
  await polygon(page, "k", points); await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Remove modules inside keep-out", exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect.poll(async () => (await state(page)).view.bundle.scene.module_instances.length).toBe(before.bundle.scene.module_instances.length-impact.module_count);
  const after = await state(page);
  expect(before.bundle.scene.module_instances.filter((m) => !after.view.bundle.scene.module_instances.some((n) => n.module_instance_id===m.module_instance_id)).map((m) => m.module_instance_id).sort()).toEqual(impact.module_instance_ids);
  for (const id of impact.string_ids) expect(after.view.bundle.electrical_design.strings.some((s) => s.string_id===id)).toBe(false);
  expect(after.entities.filter((e) => e.kind==="keepout")).toHaveLength(1);
  expect(after.entities.find((e) => e.kind==="keepout")).toMatchObject({ source: "engine", modified: false, pending: [] });
});

test("walkway, insert/delete, edge drag and obstacle height persist without local draft badges", async ({ page }) => {
  await open(page);
  await page.keyboard.press("k");
  const choice = page.getByRole("combobox", { name: "Keep-out type", exact: true });
  await choice.selectOption("walkway"); await choice.evaluate((el) => el.blur());
  for (const p of ["45,0","47,0","47,2","45,2"]) await typed(page,p);
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await state(page)).entities.filter((e) => e.subtype==="walkway").length).toBe(1);
  await polygon(page,"p",[[2,-14],[10,-14],[10,-6],[2,-6]]);
  await expect.poll(async () => (await state(page)).entities.filter((e) => e.kind==="surface").length).toBe(2);
  const id=(await state(page)).selection[0];
  const ring=async()=> (await state(page)).view.scene_view.local_features.find((f)=>f.id===id)!.polygon;
  await page.mouse.dblclick(...await point(page,6,-14));
  await expect.poll(async()=> (await ring()).length).toBe(5);
  expect((await state(page)).entities.find((e)=>e.id===id)).toMatchObject({modified:false,pending:[]});
  await page.keyboard.down("Alt"); await page.mouse.click(...await point(page,6,-14)); await page.keyboard.up("Alt");
  await expect.poll(async()=> (await ring()).length).toBe(4);
  await page.keyboard.down("Alt"); await page.mouse.move(...await point(page,6,-6)); await page.mouse.down(); await page.mouse.move(...await point(page,6,-4.75),{steps:5}); await page.mouse.up(); await page.keyboard.up("Alt");
  await expect.poll(async()=> (await ring())[2][1]).toBeCloseTo(-4.75,1);
  expect((await state(page)).entities.find((e)=>e.id===id)).toMatchObject({modified:false,pending:[]});
  await page.keyboard.press("o"); await typed(page,"15,-14"); await typed(page,"@2,2");
  await expect.poll(async()=> (await state(page)).view.bundle.scene.obstacles.length).toBe(2);
  const obstacleId=(await state(page)).view.bundle.scene.obstacles.at(-1)!.obstacle_id;
  const obstacleName=(await state(page)).entities.find((e)=>e.id===obstacleId)!.name;
  await page.locator(".taskpanel .layer__name",{hasText:obstacleName}).click();
  await page.locator(".inspectorpane").getByLabel("Height").fill("3.25"); await page.locator(".inspectorpane").getByLabel("Height").press("Enter");
  await expect.poll(async()=> (await state(page)).view.bundle.scene.obstacles.at(-1)!.height_m).toBe(3.25);
  const after = await state(page);
  expect(after.entities.find((e)=>e.id===after.selection[0])).toMatchObject({modified:false,pending:[]});
});
