import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function open(page: Page) {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+3");
  await expect(page.locator(".toollist")).toBeVisible();
}
async function type(page: Page, value: string) {
  await page.keyboard.type(value); await expect(page.locator(".plan__typed")).toBeVisible(); await page.keyboard.press("Enter");
}
async function state(page: Page) {
  return page.evaluate(async () => {
    const { uiStore } = await import("/src/state/store.tsx");
    const s = uiStore.getState().state;
    return { entities: s.entities, view: s.view!, selection: s.selection };
  });
}
async function point(page: Page, x: number, y: number): Promise<[number, number]> {
  return page.evaluate(([x, y]) => (window as unknown as { __rawibumiPlan: { toPage: (x: number, y: number) => [number, number] } }).__rawibumiPlan.toPage(x, y), [x, y]);
}
async function polygonRoof(page: Page) {
  await page.keyboard.press("p");
  for (const text of ["2,-14", "10,-14", "10,-6", "2,-6"]) await type(page, text);
  await page.keyboard.press("Enter");
  await expect(page.locator(".inspectorpane")).toContainText("Surface 2");
  await expect(page.locator(".inspectorpane")).toContainText("64.00 m²");
  const s = await state(page); return s.selection[0];
}
async function label(page: Page, ring: number[][], i: number) {
  const a = ring[i], b = ring[(i + 1) % ring.length];
  const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const nx = (b[1] - a[1]) / length, ny = -(b[0] - a[0]) / length;
  const off = 12 + Math.abs(nx) * 30 + Math.abs(ny) * 4;
  const p = await point(page, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
  return [p[0] + nx * off, p[1] - ny * off] as const;
}

test("rotate, outer vertex, exact dimension, insertion and holes persist; legacy drafts require discarding", async ({ page }) => {
  await open(page); const id = await polygonRoof(page);
  await page.keyboard.press("r"); await type(page, "2,-14"); await type(page, "30");
  await expect.poll(async () => (await state(page)).entities.find((e) => e.id === id)!.polygon[1][1]).toBeCloseTo(-18, 9);
  await page.keyboard.press("v");
  const from = await point(page, 2, -14), to = await point(page, 1, -14);
  await page.mouse.move(...from); await page.mouse.down(); await page.keyboard.down("Alt"); await page.mouse.move(...to, { steps: 5 }); await page.mouse.up(); await page.keyboard.up("Alt");
  await expect.poll(async () => (await state(page)).entities.find((e) => e.id === id)!.polygon[0][0]).toBeCloseTo(1, 1);
  let s = await state(page); let ring = s.entities.find((e) => e.id === id)!.polygon;
  await page.mouse.dblclick(...await label(page, ring, 0));
  const dimension = page.getByRole("textbox", { name: "Edge length in metres" });
  await expect(dimension).toBeVisible(); await dimension.fill("0"); await dimension.press("Enter");
  await expect(dimension).toHaveAttribute("aria-invalid", "true"); await expect(page.getByRole("alert")).toContainText("positive");
  await dimension.fill("10"); await dimension.press("Enter"); await expect(dimension).toBeHidden();
  await expect.poll(async () => {
    const p = (await state(page)).view.scene_view.local_features.find((f) => f.id === id)!.polygon;
    return Math.hypot(p[1][0] - p[0][0], p[1][1] - p[0][1]);
  }).toBeCloseTo(10, 9);
  s = await state(page); const entity = s.entities.find((e) => e.id === id)!;
  expect(entity.modified).toBe(false); expect(entity.pending).toEqual([]);
  expect(entity.polygon).toEqual(s.view.scene_view.local_features.find((f) => f.id === id)!.polygon);
  await expect(page.locator(".toasts")).not.toContainText("Not wired");
  ring = entity.polygon;
  const midpoint = await point(page, (ring[2][0] + ring[3][0]) / 2, (ring[2][1] + ring[3][1]) / 2);
  await page.mouse.dblclick(...midpoint);
  await expect.poll(async () => (await state(page)).entities.find((e) => e.id === id)!.polygon.length).toBe(ring.length + 1);
  const persisted = (await state(page)).entities.find((e) => e.id === id)!;
  expect(persisted.modified).toBe(false); expect(persisted.pending).toEqual([]);
  expect(persisted.polygon).toEqual((await state(page)).view.scene_view.local_features.find((f) => f.id === id)!.polygon);
  const centre = entity.polygon.reduce(([x, y], p) => [x + p[0] / entity.polygon.length, y + p[1] / entity.polygon.length], [0, 0]);
  await page.keyboard.press("h");
  for (const text of [`${centre[0] - .5},${centre[1] - .5}`, `${centre[0] + .5},${centre[1] - .5}`, `${centre[0]},${centre[1] + .5}`]) await type(page, text);
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await state(page)).entities.find((e) => e.id === id)!.holes.length).toBe(persisted.holes.length + 1);
  const withHole = (await state(page)).entities.find((e) => e.id === id)!;
  expect(withHole.modified).toBe(false); expect(withHole.pending).toEqual([]);
  expect(withHole.holes).toEqual((await state(page)).view.bundle.scene.surfaces.find((surface) => surface.surface_id === id)!.boundary_2d!.holes);
  // Preserve DEC-27 coverage for an unsaved draft left by an older browser.
  await page.evaluate(async (id) => (await import("/src/state/store.tsx")).uiStore.getState().dispatch({ type: "updateEntity", id, patch: { modified: true, plane: { mode: "flat", z_m: 99 } } }), id);
  await expect(page.locator(".inspectorpane")).toContainText("engine + local edits");
  await expect(page.locator(".inspectorpane .btn").filter({ hasText: /^Rotate about centre$/ })).toBeDisabled();
  await expect(page.locator(".toollist").getByRole("button", { name: /Rotate/ })).toBeDisabled();
  await page.locator(".inspectorpane").getByRole("button", { name: "Discard draft" }).click();
  await expect(page.locator(".inspectorpane")).not.toContainText("engine + local edits");
  expect((await state(page)).entities.find((e) => e.id === id)!.polygon).toEqual(withHole.polygon);
  expect((await state(page)).entities.find((e) => e.id === id)!.holes).toEqual(withHole.holes);
  expect((await state(page)).entities.find((e) => e.id === id)!.plane).toEqual(withHole.plane);
});

test("obstacle conflicts list destructive impact, trap focus, cancel safely and remove exactly the preview", async ({ page }) => {
  await open(page);
  const before = (await state(page)).view;
  const module = before.scene_view.local_features.find((f) => f.category === "module")!;
  const x = Math.min(...module.polygon.map((p) => p[0])) + 0.1, y = Math.min(...module.polygon.map((p) => p[1])) + 0.1;
  async function draw() {
    await page.keyboard.press("o"); await page.locator(".taskpanel").getByLabel("Base elevation").fill("8");
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    for (const text of [`${x},${y}`, "@0.5,0.5"]) await type(page, text);
  }
  await draw(); const dialog = page.getByRole("alertdialog", { name: "Obstacle on modules", exact: true });
  await expect(dialog).toBeVisible(); await expect(dialog.getByRole("button", { name: "Cancel obstacle" })).toBeFocused();
  await expect(dialog).toContainText("S1"); await expect(dialog).toContainText("kWp STC");
  await expect(dialog.getByRole("button", { name: "Re-fill field around obstacle" })).toBeDisabled();
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze()).violations).toEqual([]);
  for (let i = 0; i < 6; i++) { await page.keyboard.press("Tab"); expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true); }
  await page.keyboard.press("Escape"); await expect(dialog).toBeHidden();
  expect((await state(page)).view).toEqual(before);
  await draw(); await expect(dialog).toBeVisible();
  const impact = await page.evaluate(async () => (await import("/src/state/history.ts")).sceneRefusal.getState().pending!.detail.options!.remove_modules);
  await dialog.getByRole("button", { name: "Remove modules under obstacle", exact: true }).click(); await expect(dialog).toBeHidden();
  await expect.poll(async () => (await state(page)).view.bundle.scene.module_instances.length).toBe(before.bundle.scene.module_instances.length - impact.module_count);
  const after = (await state(page)).view;
  expect(after.bundle.scene.obstacles).toHaveLength(before.bundle.scene.obstacles.length + 1);
  expect(before.bundle.scene.module_instances.filter((m) => !after.bundle.scene.module_instances.some((n) => n.module_instance_id === m.module_instance_id)).map((m) => m.module_instance_id).sort()).toEqual(impact.module_instance_ids);
  for (const stringId of impact.string_ids) expect(after.bundle.electrical_design.strings.some((s) => s.string_id === stringId)).toBe(false);
});

test("hosted roof deletion explains the guard and opens the field-delete preview", async ({ page }) => {
  await open(page); await page.locator(".taskpanel .layer__name", { hasText: "Roof A" }).click(); await page.keyboard.press("Delete");
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Roof A array"); await expect(dialog.getByRole("button", { name: "Detach field" })).toHaveCount(0);
  const before = (await state(page)).view;
  await dialog.getByRole("button", { name: "Delete roof and its 1 PV fields", exact: true }).click();
  const preview = page.getByRole("alertdialog", { name: "Roof carries PV fields" });
  await expect(preview).toContainText("Roof A array");
  await expect(preview).toContainText("Modules: 76 → 0"); await expect(preview).toContainText("STC power: 41.80 → 0.00 kWp"); await expect(preview).toContainText("S1");
  await preview.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(preview).toBeHidden(); expect((await state(page)).view).toEqual(before);
  expect((await state(page)).view.bundle.scene.pv_fields).toHaveLength(1);
});

test("P and E create engine geometry using their existing base and height options", async ({ page }) => {
  await open(page); await page.keyboard.press("p");
  await page.locator(".taskpanel").getByLabel("Base elevation").fill("3");
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  for (const text of ["45,0", "49,0", "47,3"]) await type(page, text); await page.keyboard.press("Enter");
  await expect.poll(async () => (await state(page)).view.bundle.scene.surfaces.length).toBe(2);
  await page.keyboard.press("e"); await page.locator(".taskpanel").getByLabel("Base elevation").fill("4"); await page.locator(".taskpanel").getByLabel("Height").fill("2");
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  for (const text of ["45,0", "47,0", "46,1"]) await type(page, text); await page.keyboard.press("Enter");
  await expect.poll(async () => (await state(page)).view.bundle.scene.obstacles.length).toBe(2);
  const s = await state(page);
  expect(s.view.bundle.scene.surfaces.at(-1)!.base_elevation_m).toBe(3);
  expect(s.view.bundle.scene.obstacles.at(-1)!.height_m).toBe(2); expect(s.view.bundle.scene.obstacles.at(-1)!.base_elevation_m).toBe(4);
  expect(s.entities.filter((e) => e.name.startsWith("Surface") || e.name.startsWith("Obstacle")).every((e) => e.source === "engine" && !e.modified && !e.pending.length)).toBe(true);
});
