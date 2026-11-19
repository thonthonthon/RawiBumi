import { expect, test, type Page } from "@playwright/test";
import type { Vec2 } from "../../src/geometry";

async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function open(page: Page) {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+3");
  await expect(page.locator(".toollist")).toBeVisible();
  await expect.poll(async () => (await state(page)).busy).toBeNull();
}
async function point(page: Page, p: Vec2): Promise<Vec2> {
  return page.evaluate(([x, y]) => (window as unknown as { __rawibumiPlan: { toPage(x: number, y: number): Vec2 } }).__rawibumiPlan.toPage(x, y), p);
}
async function box(page: Page, start: Vec2, end: Vec2, shift = false) {
  if (shift) await page.keyboard.down("Shift");
  await page.mouse.move(...await point(page, start)); await page.mouse.down();
  await page.mouse.move(...await point(page, end), { steps: 6 }); await page.mouse.up();
  if (shift) await page.keyboard.up("Shift");
}
async function selected(page: Page, ids: string[]) {
  await expect.poll(async () => (await state(page)).selection.slice().sort()).toEqual([...ids].sort());
}
async function click(page: Page, p: Vec2) { await page.mouse.click(...await point(page, p)); }
async function typed(page: Page, value: string) { await page.keyboard.type(value); await page.keyboard.press("Enter"); }
async function extraObstacle(page: Page) {
  await page.evaluate(async () => {
    const { mockApi } = await import("/src/demo/mockApi.ts");
    const { uiStore } = await import("/src/state/store.tsx");
    const v = await mockApi.addObstacle(uiStore.getState().state.view!.bundle.project.project_id,
      { name: "AHU-2", origin_x_m: 35, origin_y_m: 15, width_m: 2, depth_m: 1, base_elevation_m: 8, height_m: 1 });
    uiStore.getState().dispatch({ type: "setView", view: v });
  });
}
async function spy(page: Page) {
  await page.evaluate(async () => {
    const { mockApi } = await import("/src/demo/mockApi.ts");
    const w = window as unknown as { s13aCalls: string[] }; w.s13aCalls = [];
    const move = mockApi.moveSceneEntity, scene = mockApi.sceneCommand;
    mockApi.moveSceneEntity = (...args) => { w.s13aCalls.push("move"); return move(...args); };
    mockApi.sceneCommand = (...args) => { if (args[1].command_type === "rotate") w.s13aCalls.push("rotate"); return scene(...args); };
  });
}

for (const tool of ["move", "rotate"] as const) test(`${tool} completes once and later roof clicks only select`, async ({ page }) => {
  await open(page); await spy(page);
  await page.locator(".taskpanel .layer__name", { hasText: "AHU-1" }).click();
  await page.keyboard.press(tool === "move" ? "m" : "r");
  await click(page, [30, 11]); await click(page, tool === "move" ? [32, 15] : [34, 11]);
  await expect.poll(async () => (await state(page)).tool).toBe("select");
  await expect.poll(async () => (await state(page)).busy).toBeNull();
  await selected(page, ["obs-ahu-1"]);
  const after = (await state(page)).view;
  await click(page, [40, 3]); await selected(page, ["srf-roof-a"]);
  expect((await state(page)).view).toEqual(after);
  expect(await page.evaluate(() => (window as unknown as { s13aCalls: string[] }).s13aCalls)).toEqual([tool]);
});

test("typed completion, refusal and cancelled roof preview all return to Select; Escape cancels only a pick", async ({ page }) => {
  await open(page);
  await page.locator(".taskpanel .layer__name", { hasText: "AHU-1" }).click();
  await page.keyboard.press("m"); await typed(page, "30,11"); await page.keyboard.press("Escape");
  expect((await state(page)).tool).toBe("move"); await selected(page, ["obs-ahu-1"]);
  await page.evaluate(async () => { (await import("/src/demo/mockApi.ts")).mockApi.moveSceneEntity = async () => { throw new Error("S13a refused edit"); }; });
  await typed(page, "30,11"); await typed(page, "@1,0");
  await expect(page.locator(".toasts")).toContainText("S13a refused edit");
  expect((await state(page)).tool).toBe("select"); await selected(page, ["obs-ahu-1"]);
  await page.locator(".taskpanel .layer__name", { hasText: "Roof A" }).click();
  const before = (await state(page)).view;
  await page.keyboard.press("r"); await typed(page, "0,0"); await typed(page, "15");
  const dialog = page.getByRole("alertdialog", { name: "Roof carries PV fields" });
  await expect(dialog).toBeVisible(); expect((await state(page)).tool).toBe("select");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click(); await expect(dialog).toBeHidden();
  expect((await state(page)).view).toEqual(before); await selected(page, ["srf-roof-a"]);
});

test("window selects AHU only; a box inside the roof selects exactly two module rows", async ({ page }) => {
  await open(page); await spy(page);
  await box(page, [29, 19], [34, 10]); await selected(page, ["obs-ahu-1"]);
  await page.keyboard.press("Alt+4"); await page.keyboard.press("Escape");
  const s = await state(page);
  const ys = [...new Set(s.modules.map((m) => Math.min(...m.polygon.map((p) => p[1]))))].sort((a, b) => a - b);
  const rows = s.modules.filter((m) => Math.min(...m.polygon.map((p) => p[1])) <= ys[1]);
  const points = rows.flatMap((m) => m.polygon);
  const a: Vec2 = [Math.min(...points.map((p) => p[0])) - .15, Math.min(...points.map((p) => p[1])) - .15];
  const b: Vec2 = [Math.max(...points.map((p) => p[0])) + .15, Math.max(...points.map((p) => p[1])) + .15];
  await box(page, a, b); await selected(page, rows.map((m) => m.id));
  await expect(page.locator(".inspectorpane")).toContainText(`${(rows.length * .55).toFixed(2)} kWp`);
  await expect(page.locator(".inspectorpane")).toContainText("Not wired");
  await page.locator(".inspectorpane").getByRole("button", { name: "Clear selection" }).click(); await selected(page, []);
  expect(await page.evaluate(() => (window as unknown as { s13aCalls: string[] }).s13aCalls)).toEqual([]);
});

test("crossing the roof edge includes the roof and the crossed or contained modules", async ({ page }) => {
  await open(page); await page.keyboard.press("Alt+4");
  const s = await state(page);
  const expected = s.modules.filter((m) => m.polygon.some((p) => p[1] <= 3.6) && m.polygon.some((p) => p[1] >= .7)).map((m) => m.id);
  expect(expected.length).toBeGreaterThan(0);
  await box(page, [42.5, .7], [.7, 3.6]); await selected(page, ["srf-roof-a", ...expected]);
});

test("Shift boxes add, Shift clicks toggle entities and modules, Escape and blank clicks clear", async ({ page }) => {
  await open(page); await extraObstacle(page); await page.keyboard.press("Alt+4");
  const second = (await state(page)).entities.find((e) => e.name === "AHU-2")!.id;
  await box(page, [29, 10], [34, 14]); await selected(page, ["obs-ahu-1"]);
  await box(page, [34.5, 14.5], [37.5, 16.5], true); await selected(page, ["obs-ahu-1", second]);
  // Avoid the existing rotate handle near this small obstacle's centre.
  await page.keyboard.down("Shift"); await click(page, [30.6, 12.2]); await page.keyboard.up("Shift"); await selected(page, [second]);
  const m = (await state(page)).modules[0], centre: Vec2 = [m.polygon.reduce((v, p) => v + p[0], 0) / 4, m.polygon.reduce((v, p) => v + p[1], 0) / 4];
  await page.keyboard.down("Shift"); await click(page, centre); await page.keyboard.up("Shift"); await selected(page, [second, m.id]);
  await page.keyboard.down("Shift"); await click(page, centre); await page.keyboard.up("Shift"); await selected(page, [second]);
  await page.keyboard.press("Escape"); await selected(page, []);
  await click(page, [31.6, 12.2]); await selected(page, ["obs-ahu-1"]);
  await click(page, [-1, 19]); await selected(page, []);
});

test("Space-left and middle/right pan; a plain blank left drag leaves the view unchanged", async ({ page }) => {
  await open(page);
  const current = () => page.evaluate(() => (window as unknown as { __rawibumiPlan: { view: unknown } }).__rawibumiPlan.view);
  const canvas = await page.locator(".plan__canvas").boundingBox(); expect(canvas).not.toBeNull();
  const drag = async (button: "left" | "middle" | "right") => {
    await page.mouse.move(canvas!.x + 10, canvas!.y + 10); await page.mouse.down({ button });
    await page.mouse.move(canvas!.x + 40, canvas!.y + 30, { steps: 4 }); await page.mouse.up({ button });
  };
  let before = await current(); await drag("left"); expect(await current()).toEqual(before);
  await page.keyboard.down("Space"); await drag("left"); await page.keyboard.up("Space"); expect(await current()).not.toEqual(before);
  before = await current(); await drag("middle"); expect(await current()).not.toEqual(before);
  before = await current(); await drag("right"); expect(await current()).not.toEqual(before);
});

test("multi Inspector deletes both named obstacles; mixed Delete only explains the refusal", async ({ page }) => {
  await open(page); await extraObstacle(page); await page.keyboard.press("Alt+4");
  await box(page, [29, 10], [37.5, 16.5]);
  const s = await state(page), ids = s.selection;
  expect(ids).toHaveLength(2); await expect(page.locator(".inspectorpane")).toContainText("2 obstacles");
  await page.locator(".inspectorpane").getByRole("button", { name: "Delete 2 items", exact: true }).click();
  const dialog = page.getByRole("alertdialog"); await expect(dialog).toContainText("AHU-1"); await expect(dialog).toContainText("AHU-2");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.keyboard.press("Delete"); await expect(dialog).toBeVisible(); await expect(dialog).toContainText("AHU-2");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  const m = s.modules[0]; const c: Vec2 = [m.polygon.reduce((v, p) => v + p[0], 0) / 4, m.polygon.reduce((v, p) => v + p[1], 0) / 4];
  await page.keyboard.down("Shift"); await click(page, c); await page.keyboard.up("Shift"); await selected(page, [...ids, m.id]);
  await page.keyboard.press("Delete"); await expect(dialog).toBeHidden();
  await expect(page.locator(".toasts")).toContainText("Select only scene items or only modules to delete");
  expect((await state(page)).view).toEqual(s.view);
});

test("hidden entities are excluded and locked entities remain box-selectable", async ({ page }) => {
  await open(page); await extraObstacle(page); await page.keyboard.press("Alt+4");
  const second = (await state(page)).entities.find((e) => e.name === "AHU-2")!.id;
  await page.evaluate(async (id) => {
    const { dispatch } = (await import("/src/state/store.tsx")).uiStore.getState();
    dispatch({ type: "updateEntity", id: "obs-ahu-1", patch: { hidden: true } });
    dispatch({ type: "updateEntity", id, patch: { locked: true } });
  }, second);
  await box(page, [29, 10], [37.5, 16.5]); await selected(page, [second]);
});

async function toggleLock(page: Page, name: string, locked: boolean) {
  const layer = page.locator(".taskpanel .layer", { has: page.locator(".layer__name", { hasText: name }) });
  await layer.getByTitle(locked ? "Lock" : "Unlock", { exact: true }).click();
  await expect.poll(async () => (await state(page)).entities.find((e) => e.name === name)!.locked).toBe(locked);
}
async function observeDeletes(page: Page) {
  await page.evaluate(async () => {
    const { mockApi } = await import("/src/demo/mockApi.ts");
    const w = window as unknown as { s13aDeleteTargets: string[][] }; w.s13aDeleteTargets = [];
    const scene = mockApi.sceneCommand;
    mockApi.sceneCommand = (...args) => {
      if (args[1].command_type === "delete") w.s13aDeleteTargets.push([...args[1].target_entity_ids]);
      return scene(...args);
    };
  });
}
async function deleteCalls(page: Page) {
  return page.evaluate(() => (window as unknown as { s13aDeleteTargets: string[][] }).s13aDeleteTargets);
}

test("A3: Delete on a single locked obstacle shows a notice and sends no delete", async ({ page }) => {
  await open(page); await observeDeletes(page); await toggleLock(page, "AHU-1", true);
  await page.locator(".taskpanel .layer__name", { hasText: "AHU-1" }).click();
  const before = await state(page);
  await page.locator(".inspectorpane").getByRole("button", { name: "Danger zone", exact: true }).click();
  await expect(page.locator(".inspectorpane").getByRole("button", { name: "Delete obstacle", exact: true })).toBeDisabled();
  await page.keyboard.press("Delete");
  await expect(page.getByRole("alertdialog")).toBeHidden();
  await expect(page.locator(".toasts")).toContainText("AHU-1 is locked.");
  expect(await deleteCalls(page)).toEqual([]); expect((await state(page)).view).toEqual(before.view);
  await selected(page, ["obs-ahu-1"]);
});

test("A3: box plus Delete skips the locked obstacle and confirms only the unlocked target", async ({ page }) => {
  await open(page); await extraObstacle(page); await observeDeletes(page); await toggleLock(page, "AHU-1", true);
  await page.keyboard.press("Alt+4"); await box(page, [29, 10], [37.5, 16.5]);
  const before = await state(page), second = before.entities.find((e) => e.name === "AHU-2")!.id;
  await selected(page, ["obs-ahu-1", second]); await page.keyboard.press("Delete");
  const dialog = page.getByRole("alertdialog");
  await expect(dialog.getByRole("heading")).toHaveText("Delete AHU-2?");
  await expect(dialog.locator("p").first()).not.toContainText("AHU-1");
  await expect(dialog).toContainText("1 locked item is not deleted: AHU-1");
  expect(await deleteCalls(page)).toEqual([]);
  await dialog.getByRole("button", { name: "Delete", exact: true }).click(); await expect(dialog).toBeHidden();
  await expect.poll(() => deleteCalls(page)).toEqual([[second]]);
  await expect.poll(async () => (await state(page)).view!.bundle.scene.obstacles.map((e) => e.obstacle_id)).toEqual(["obs-ahu-1"]);
  const after = await state(page);
  expect(after.entities.find((e) => e.id === "obs-ahu-1")).toEqual(before.entities.find((e) => e.id === "obs-ahu-1"));
  expect(after.view!.bundle.scene.module_instances).toEqual(before.view!.bundle.scene.module_instances);
  await selected(page, ["obs-ahu-1"]);
});

test("A3: multi-selection Delete counts only unlocked items and disables an all-locked selection", async ({ page }) => {
  await open(page); await extraObstacle(page); await observeDeletes(page);
  await toggleLock(page, "AHU-1", true); await toggleLock(page, "AHU-2", true);
  await page.keyboard.press("Alt+4"); await box(page, [29, 10], [37.5, 16.5]);
  const before = await state(page); expect(before.selection).toHaveLength(2);
  const button = page.locator(".inspectorpane").getByRole("button", { name: /^Delete \d+ items?$/ });
  await expect(button).toHaveText("Delete 0 items"); await expect(button).toBeDisabled(); await expect(button).toHaveAttribute("title", /locked/i);
  await page.keyboard.press("Delete"); await expect(page.getByRole("alertdialog")).toBeHidden();
  await expect(page.locator(".toasts")).toContainText("2 selected items are locked.");
  expect(await deleteCalls(page)).toEqual([]); await selected(page, before.selection);
  await page.keyboard.press("Alt+3"); await toggleLock(page, "AHU-2", false); await page.keyboard.press("Alt+4");
  await expect(button).toHaveText("Delete 1 item"); await expect(button).toBeEnabled();
  await button.click(); const dialog = page.getByRole("alertdialog");
  await expect(dialog.getByRole("heading")).toHaveText("Delete AHU-2?");
  await expect(dialog).toContainText("1 locked item is not deleted: AHU-1");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click(); await expect(dialog).toBeHidden();
  expect(await deleteCalls(page)).toEqual([]); expect((await state(page)).view).toEqual(before.view);
  await selected(page, before.selection);
});

test("A3: a single unlocked obstacle still confirms and deletes normally", async ({ page }) => {
  await open(page); await observeDeletes(page);
  await page.locator(".taskpanel .layer__name", { hasText: "AHU-1" }).click();
  const before = await state(page); await page.keyboard.press("Delete");
  const dialog = page.getByRole("alertdialog");
  await expect(dialog.getByRole("heading")).toHaveText("Delete AHU-1?");
  await expect(dialog).toContainText("Deletes AHU-1 from the engine. Undo is available while this edit remains in session history.");
  await expect(dialog).not.toContainText("locked item");
  await dialog.getByRole("button", { name: "Delete", exact: true }).click(); await expect(dialog).toBeHidden();
  await expect.poll(() => deleteCalls(page)).toEqual([["obs-ahu-1"]]);
  await expect.poll(async () => (await state(page)).view!.bundle.scene.obstacles).toEqual([]);
  expect((await state(page)).view!.bundle.scene.module_instances).toEqual(before.view!.bundle.scene.module_instances);
  await selected(page, []);
});
