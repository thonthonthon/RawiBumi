import { expect, test, type Page } from "@playwright/test";

// USE3b in the demo: unstrung modules are assigned from the right-click menu, and a projects row expands to its system.
const hook = <T,>(page: Page, fn: string, ...args: number[]) =>
  page.evaluate(([f, a]) => {
    const h = (window as unknown as { __rawibumiPlan: Record<string, (...x: number[]) => unknown> }).__rawibumiPlan;
    return h[f as string](...(a as number[])) as T;
  }, [fn, args] as const);
async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function idle(page: Page) { await expect.poll(async () => (await state(page)).busy).toBeNull(); }

async function open(page: Page) {
  await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
  await page.goto("/");
}

test("a projects row expands to its PV, inverters and last run", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: /^Show the system of/ }).first().click();
  const summary = page.locator("[data-project-summary]").first();
  await expect(summary).toContainText("PV");
  await expect(summary).toContainText("kWp");
  await expect(summary).toContainText("Inverters");
});

test("right-clicking unstrung modules makes them a new string on an MPPT, in one undo step", async ({ page }) => {
  await open(page);
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6"); await idle(page);
  // Free the last string through the engine command path, then select its modules.
  const freed: string[] = await page.evaluate(async () => {
    const { uiStore } = await import("/src/state/store.tsx");
    const { engineCommand } = await import("/src/state/history.ts");
    const { engine } = await import("/src/client.ts");
    const view = uiStore.getState().state.view!;
    const last = view.bundle.electrical_design.strings.at(-1)!;
    await engineCommand("Freeing a string", () => engine.topologyCommand(view.bundle.project.project_id, { command_type: "delete_strings", parameters: { string_ids: [last.string_id] } }, view));
    uiStore.getState().dispatch({ type: "select", ids: last.module_instance_ids });
    return last.module_instance_ids;
  });
  await idle(page);
  const before = (await state(page)).view!.bundle.electrical_design.strings.length;
  const count = await hook<number>(page, "moduleCount");
  let index = -1;
  for (let i = 0; i < count && index < 0; i++) if ((await hook<string | null>(page, "moduleString", i)) === null) index = i;
  expect(index).toBeGreaterThanOrEqual(0);
  const c = await hook<[number, number]>(page, "moduleCentre", index);
  const [x, y] = await hook<[number, number]>(page, "toPage", c[0], c[1]);
  await page.mouse.click(x, y, { button: "right" });
  const item = page.getByRole("menuitem", { name: new RegExp(`^New string of ${freed.length} on .*MPPT 1`) });
  await expect(item).toBeVisible();
  await expect(page.getByRole("menuitem", { name: new RegExp(`^Add ${freed.length} to S`) }).first()).toBeVisible();
  await item.click(); await idle(page);
  const design = (await state(page)).view!.bundle.electrical_design;
  expect(design.strings.length).toBe(before + 1);
  const made = design.strings.find((s) => freed.every((m) => s.module_instance_ids.includes(m)))!;
  expect(made.target_mppt_instance_id).toBeTruthy();
  await page.locator(".stage").click({ position: { x: 5, y: 60 } });
  await page.keyboard.press("Control+z"); await idle(page);
  expect((await state(page)).view!.bundle.electrical_design.strings.length).toBe(before);
});
