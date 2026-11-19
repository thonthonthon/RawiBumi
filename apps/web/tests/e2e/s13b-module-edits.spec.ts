import { expect, test, type Page } from "@playwright/test";
import type { Vec2 } from "../../src/geometry";

async function state(page: Page) { return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state); }
async function open(page: Page) {
  await page.goto("/"); await page.locator(".start__row").first().click(); await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+4"); await expect(page.locator('.rail [aria-current="step"]')).toContainText("PV layout");
  const s = await state(page); expect(s.view!.table_layout?.tables ?? []).toEqual([]); expect(s.modules).toHaveLength(76);
  await page.evaluate(async () => {
    const { mockApi } = await import("/src/demo/mockApi.ts");
    const w = window as unknown as { s13bCalls: unknown[] }; w.s13bCalls = [];
    const original = mockApi.moduleCommands;
    mockApi.moduleCommands = (...args) => { w.s13bCalls.push(structuredClone(args[1])); return original(...args); };
  });
}
async function point(page: Page, p: Vec2): Promise<Vec2> { return page.evaluate(([x, y]) => (window as unknown as { __rawibumiPlan: { toPage(x: number, y: number): Vec2 } }).__rawibumiPlan.toPage(x, y), p); }
const centre = (polygon: Vec2[]): Vec2 => polygon.reduce<Vec2>((v, p) => [v[0] + p[0] / polygon.length, v[1] + p[1] / polygon.length], [0, 0]);
async function clickModule(page: Page, polygon: Vec2[], shift = false) {
  if (shift) await page.keyboard.down("Shift"); await page.mouse.click(...await point(page, centre(polygon))); if (shift) await page.keyboard.up("Shift");
}
async function calls(page: Page) { return page.evaluate(() => (window as unknown as { s13bCalls: Array<Record<string, unknown>> }).s13bCalls); }
async function settled(page: Page) { await expect.poll(async () => (await state(page)).busy).toBeNull(); }

test("non-table module delete previews counts, kWp and whole strings; Cancel is read-only and Confirm deletes exactly", async ({ page }) => {
  await open(page); const before = await state(page), chosen = before.modules.slice(0, 3), ids = chosen.map((m) => m.id);
  for (let i = 0; i < chosen.length; i++) await clickModule(page, chosen[i].polygon, i > 0);
  await expect.poll(async () => (await state(page)).selection).toEqual(ids); await page.keyboard.press("Delete");
  const dialog = page.getByRole("alertdialog", { name: "Delete selected modules?" });
  const stringIds = before.view!.bundle.electrical_design.strings.filter((s) => s.module_instance_ids.some((id) => ids.includes(id))).map((s) => s.string_id);
  await expect(dialog).toContainText("Modules: 76 → 73"); await expect(dialog).toContainText("STC power: 41.80 → 40.15 kWp");
  for (const id of stringIds) await expect(dialog).toContainText(id);
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click(); await expect(dialog).toBeHidden();
  expect((await state(page)).view).toEqual(before.view); expect(await calls(page)).toEqual([{ command: "delete_modules", module_instance_ids: ids, dry_run: true }]);
  await page.locator(".inspectorpane").getByRole("button", { name: "Delete 3 modules", exact: true }).click(); await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Confirm module deletion", exact: true }).click(); await expect(dialog).toBeHidden(); await settled(page);
  const after = await state(page);
  expect(after.view!.bundle.scene.module_instances).toEqual(before.view!.bundle.scene.module_instances.filter((m) => !ids.includes(m.module_instance_id)));
  expect(after.view!.bundle.electrical_design.strings).toEqual(before.view!.bundle.electrical_design.strings.filter((s) => !stringIds.includes(s.string_id)));
  expect(after.view!.bundle.scene.pv_fields[0].layout_status).toBe("manual"); expect(after.selection).toEqual([]);
  expect((await calls(page)).at(-1)).toEqual({ command: "delete_modules", module_instance_ids: ids, discard_dependent_strings: true });
});

test("a selected group drags with a snapped rigid delta and nudges 0.10/1.00 m while retaining ids and strings", async ({ page }) => {
  await open(page); const before = await state(page);
  const maxY = Math.max(...before.modules.map((m) => centre(m.polygon)[1]));
  const chosen = before.modules.filter((m) => centre(m.polygon)[1] === maxY).slice(0, 2), ids = chosen.map((m) => m.id);
  await clickModule(page, chosen[0].polygon); await clickModule(page, chosen[1].polygon, true);
  const a = centre(chosen[0].polygon);
  await page.mouse.move(...await point(page, a)); await page.mouse.down(); await page.keyboard.down("Shift");
  await page.mouse.move(...await point(page, [a[0], a[1] + .54]), { steps: 6 }); await page.mouse.up(); await page.keyboard.up("Shift"); await settled(page);
  await expect.poll(async () => (await calls(page)).length).toBe(1);
  const moved = (await state(page)).modules;
  for (const m of chosen) for (let i = 0; i < 4; i++) {
    const actual = moved.find((n) => n.id === m.id)!.polygon[i]; expect(actual[0]).toBeCloseTo(m.polygon[i][0], 9); expect(actual[1]).toBeCloseTo(m.polygon[i][1] + .5, 9);
  }
  await page.keyboard.press("ArrowUp"); await settled(page); await page.keyboard.press("Shift+ArrowUp"); await settled(page);
  expect((await calls(page)).map((c) => [c.command, c.dx_m, c.dy_m])).toEqual([["move_modules", 0, .5], ["move_modules", 0, .1], ["move_modules", 0, 1]]);
  const after = await state(page); expect(after.selection).toEqual(ids); expect(after.view!.bundle.electrical_design.strings).toEqual(before.view!.bundle.electrical_design.strings);
  for (const m of chosen) expect(centre(after.modules.find((n) => n.id === m.id)!.polygon)[1]).toBeCloseTo(centre(m.polygon)[1] + 1.6, 9);
});

test("a refused overlapping nudge reports the engine conflicts and preserves the design", async ({ page }) => {
  await open(page); const before = await state(page); await clickModule(page, before.modules[0].polygon);
  await page.keyboard.press("Shift+ArrowRight");
  await expect(page.locator(".toasts")).toContainText("1 module would overlap other modules"); await settled(page);
  expect((await state(page)).view).toEqual(before.view); expect(await calls(page)).toHaveLength(1);
});

test("deleting all placements warns that the field stays empty", async ({ page }) => {
  await open(page); const before = await state(page), polygon = before.modules.flatMap((m) => m.polygon);
  const a: Vec2 = [Math.min(...polygon.map((p) => p[0])) - .1, Math.min(...polygon.map((p) => p[1])) - .1];
  const b: Vec2 = [Math.max(...polygon.map((p) => p[0])) + .1, Math.max(...polygon.map((p) => p[1])) + .1];
  await page.mouse.move(...await point(page, a)); await page.mouse.down(); await page.mouse.move(...await point(page, b), { steps: 6 }); await page.mouse.up();
  await expect.poll(async () => (await state(page)).selection.length).toBe(76); await page.keyboard.press("Delete");
  const dialog = page.getByRole("alertdialog", { name: "Delete selected modules?" }); await expect(dialog).toContainText("Modules: 76 → 0");
  await expect(dialog).toContainText("This field will be empty. The field stays with a readiness warning.");
  await dialog.getByRole("button", { name: "Confirm module deletion" }).click(); await expect(dialog).toBeHidden(); await settled(page);
  expect((await state(page)).view!.bundle.scene.pv_fields).toHaveLength(1); expect((await state(page)).modules).toHaveLength(0);
});

test("active demo table modules retain their old nudge and Delete path without module commands", async ({ page }) => {
  await open(page); await page.keyboard.press("Alt+3"); await expect(page.locator(".toollist")).toBeVisible(); await page.keyboard.press("b");
  for (const text of ["50,0", "@12,8"]) { await page.keyboard.type(text); await page.keyboard.press("Enter"); }
  await expect(page.locator(".toasts")).toContainText("Roof created in the engine."); await page.keyboard.press("z"); await page.keyboard.press("Alt+4");
  const p = page.locator(".taskpanel"); await p.getByLabel("Field name").fill("S13b table");
  await p.getByLabel("Support surface").selectOption({ label: "Roof B · flat_roof" });
  await p.getByRole("combobox", { name: "Module", exact: true }).selectOption({ label: "Demo 2 × 1 m golden-case module (synthetic) · 400 W" });
  await p.getByLabel("Tilt").fill("0"); await p.getByLabel("Rows per table").fill("2"); await p.getByLabel("Edge setback").fill("0.4");
  await p.getByRole("button", { name: "Apply fill", exact: true }).click();
  await expect.poll(async () => (await state(page)).view!.table_layout!.tables.length).toBeGreaterThan(0);
  const table = (await state(page)).modules.find((m) => m.id.includes(":m"));
  const actual = table ?? (await state(page)).modules.find((m) => m.fieldId !== "fld-a")!;
  expect(actual).toBeTruthy(); await clickModule(page, actual.polygon);
  await expect(page.locator(".inspectorpane").getByRole("button", { name: /Delete \d+ module/ })).toBeDisabled();
  await page.keyboard.press("ArrowUp"); await settled(page); await page.keyboard.press("Delete"); await settled(page);
  expect(await calls(page)).toEqual([]); await expect(page.getByRole("alertdialog", { name: "Delete selected modules?" })).toBeHidden();
  expect((await state(page)).modules.some((m) => m.id === actual.id)).toBe(false);
});
