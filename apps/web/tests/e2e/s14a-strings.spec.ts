import { expect, test, type Page } from "@playwright/test";

// S14a in the demo: Move module (M), Swap modules (W), Delete takes a module out of its string, serpentine strings.

const hook = <T,>(page: Page, fn: string, ...args: number[]) =>
  page.evaluate(([f, a]) => {
    const h = (window as unknown as { __rawibumiPlan: Record<string, (...x: number[]) => unknown> }).__rawibumiPlan;
    return h[f as string](...(a as number[])) as T;
  }, [fn, args] as const);

async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function idle(page: Page) { await expect.poll(async () => (await state(page)).busy).toBeNull(); }
const strings = async (page: Page) => new Map((await state(page)).view!.bundle.electrical_design.strings.map((s) => [s.string_id, s.module_instance_ids]));

async function indexOf(page: Page, moduleId: string): Promise<number> {
  const n = await hook<number>(page, "moduleCount");
  for (let i = 0; i < n; i++) if ((await hook<string | null>(page, "moduleId", i)) === moduleId) return i;
  throw new Error(`module ${moduleId} is not on the plan`);
}
async function clickModule(page: Page, moduleId: string, shift = false) {
  const c = await hook<[number, number]>(page, "moduleCentre", await indexOf(page, moduleId));
  const [x, y] = await hook<[number, number]>(page, "toPage", c[0], c[1]);
  if (shift) await page.keyboard.down("Shift");
  await page.mouse.click(x, y);
  if (shift) await page.keyboard.up("Shift");
}

async function openElectrical(page: Page) {
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("Electrical");
  await idle(page);
  await page.waitForTimeout(300); // let the plan fit the stage above the string table
}

test("move a module into another string and back out, swap two modules, each one undo step", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  await openElectrical(page);
  const toolbar = page.getByRole("toolbar", { name: "Electrical tools", exact: true });
  for (const name of ["Split", "Join", "Reverse", "Move module", "Swap modules"])
    await expect(toolbar.getByRole("button", { name: new RegExp(`^${name}`) }).locator(".notwired")).toHaveCount(0);
  const before = await strings(page);
  const s1 = before.get("S1")!, s2 = before.get("S2")!;

  // Move (M): the first module of S1 takes the place of S2's third module.
  await page.keyboard.press("m");
  await clickModule(page, s1[0]);
  await expect(page.locator(".plan__hint").first()).toContainText(/Delete takes it out/);
  await clickModule(page, s2[2]); await idle(page);
  let now = await strings(page);
  expect(now.get("S1")).toEqual(s1.slice(1));
  expect(now.get("S2")).toEqual([...s2.slice(0, 2), s1[0], ...s2.slice(2)]);

  // Shift+click puts it just after the clicked module.
  await clickModule(page, s1[0]); await clickModule(page, s2[5], true); await idle(page);
  now = await strings(page);
  expect(now.get("S2")!.indexOf(s1[0])).toBe(now.get("S2")!.indexOf(s2[5]) + 1);

  // Delete takes the picked module out of its string.
  await clickModule(page, s1[0]); await page.keyboard.press("Delete"); await idle(page);
  now = await strings(page);
  expect([...now.values()].flat()).not.toContain(s1[0]);
  expect(now.get("S2")).toEqual(s2);

  // Swap (W) across strings.
  await page.keyboard.press("w");
  await clickModule(page, s1[1]); await clickModule(page, s2[0]); await idle(page);
  now = await strings(page);
  expect(now.get("S1")![0]).toBe(s2[0]);
  expect(now.get("S2")![0]).toBe(s1[1]);

  // Escape drops a pick without a command.
  await clickModule(page, s1[2]); await page.keyboard.press("Escape");
  await clickModule(page, s1[3]); await page.keyboard.press("Escape");
  expect(await strings(page)).toEqual(now);

  // Four commands, four undo steps back to the start.
  for (let i = 0; i < 4; i++) { await page.keyboard.press("Control+z"); await idle(page); }
  expect(await strings(page)).toEqual(before);
  expect(errors).toEqual([]);
});

test("serpentine strings reach the engine and show their live checks", async ({ page }) => {
  await openElectrical(page);
  const all = await strings(page);
  // Free some modules: delete every string, then string them in serpentine order.
  await page.evaluate(async (ids) => {
    const { mockApi } = await import("/src/demo/mockApi.ts");
    const { uiStore } = await import("/src/state/store.tsx");
    const pid = uiStore.getState().state.view!.bundle.project.project_id;
    const v = await mockApi.topologyCommand(pid, { command_type: "delete_strings", parameters: { string_ids: ids } }, uiStore.getState().state.view!);
    uiStore.getState().dispatch({ type: "setView", view: v });
  }, [...all.keys()]);
  await idle(page);
  await page.locator(".taskpanel").getByRole("button", { name: "Rules", exact: true }).click();
  await page.getByRole("radio", { name: "Serpentine", exact: true }).click();
  await expect(page.locator('.taskpanel .notwired[title*="serpentine"]')).toHaveCount(0);
  await page.locator(".taskpanel").getByRole("button", { name: "Create strings", exact: true }).click(); await idle(page);
  const created = (await state(page)).view!.bundle.electrical_design.strings;
  expect(created.length).toBeGreaterThan(0);
  expect(created.every((s) => s.topology_source?.includes("serpentine") ?? true)).toBe(true);
  const checks = (await state(page)).view!.topology_checks!;
  expect(checks.strings.map((s) => s.string_id)).toEqual(created.map((s) => s.string_id));
});
