import { expect, test, type Page } from "@playwright/test";

// F4 done-when (plan C2): the golden case shows 30 and 25 against the mock; pinned
// edits survive a mock re-fill; one fill is one undo.

interface PlanHook {
  toPage: (x: number, y: number) => [number, number];
  moduleCentre: (i: number) => [number, number] | null;
  moduleId: (i: number) => string | null;
  moduleCount: () => number;
}

const hook = <T,>(page: Page, fn: string, ...args: number[]) =>
  page.evaluate(([f, a]) => {
    const h = (window as unknown as { __rawibumiPlan: Record<string, (...x: number[]) => unknown> }).__rawibumiPlan;
    return h[f as string](...(a as number[])) as T;
  }, [fn, args] as const);

async function typeIn(page: Page, text: string) {
  await page.keyboard.type(text);
  await expect(page.locator(".plan__typed")).toBeVisible();
  await page.keyboard.press("Enter");
}

const panel = (page: Page) => page.locator(".taskpanel");

/** Opens the demo project, draws the golden 12 × 8 m roof at (50, 0) and opens the PV layout step. */
async function goldenZone(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+3");
  await page.waitForTimeout(300);
  await page.keyboard.press("b");
  await typeIn(page, "50,0");
  await typeIn(page, "@12,8");
  await expect(page.locator(".toasts")).toContainText("Roof created in the engine.");
  await page.keyboard.press("z"); // nothing selected: zoom to everything, so the new roof is on screen
  await page.keyboard.press("Alt+4");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("PV layout");
  const p = panel(page);
  await p.getByLabel("Field name").fill("Golden");
  await p.getByLabel("Support surface").selectOption({ label: "Roof B · flat_roof" });
  await p.getByRole("combobox", { name: "Module", exact: true }).selectOption({ label: "Demo 2 × 1 m golden-case module (synthetic) · 400 W" });
  await p.getByLabel("Tilt").fill("0");
  await p.getByLabel("Rows per table").fill("2");
  await p.getByLabel("Module gap").fill("0.05");
  await p.getByLabel("In-table gap").fill("0.05");
  await p.getByLabel("Aisle").fill("1");
  await p.getByLabel("Edge setback").fill("0.4");
  return errors;
}

/** Index of the first module (in the plan's list) whose id belongs to a table. */
async function firstTableModule(page: Page): Promise<number> {
  const n = await hook<number>(page, "moduleCount");
  for (let i = 0; i < n; i++) if ((await hook<string>(page, "moduleId", i))?.includes("/")) return i;
  throw new Error("no table module");
}

async function clickModule(page: Page, i: number) {
  const c = await hook<[number, number]>(page, "moduleCentre", i);
  const [x, y] = await hook<[number, number]>(page, "toPage", c[0], c[1]);
  await page.mouse.click(x, y);
}

test("golden case: 30 portrait and 25 landscape against the mock, before Apply", async ({ page }) => {
  const errors = await goldenZone(page);
  const p = panel(page);
  await expect(p.getByRole("radio", { name: "Portrait · 30" })).toBeVisible();
  await expect(p.getByRole("radio", { name: "Landscape · 25" })).toBeVisible();
  await expect(p.locator(".preview-box")).toContainText("30 modules in 2 tables");
  await expect(p).toContainText("Pitch from the engine: 5.050 m");
  await p.getByRole("radio", { name: "Landscape · 25" }).click();
  await expect(p.locator(".preview-box")).toContainText("25 modules in 3 tables");
  expect(errors).toEqual([]);
});

test("one fill is one undo step, and redo puts it back", async ({ page }) => {
  await goldenZone(page);
  const p = panel(page);
  await expect(p.locator(".preview-box")).toContainText("30 modules");
  await p.getByRole("button", { name: "Apply fill" }).click();
  await expect(page.locator(".toasts")).toContainText("PV field filled by the engine.");
  const card = p.locator(".card-row", { hasText: "Golden" });
  await expect(card).toContainText("30 modules");
  await expect(card).toContainText("2 tables, 0 pinned");
  const withFill = await hook<number>(page, "moduleCount");
  await page.keyboard.press("Control+z");
  await expect(p.locator(".card-row", { hasText: "Golden" })).toHaveCount(0);
  expect(await hook<number>(page, "moduleCount")).toBe(withFill - 30);
  // The roof drawn before the fill is still there: the undo took one step only.
  await expect(p.getByLabel("Support surface")).toContainText("Roof B");
  await page.keyboard.press("Control+Shift+z");
  await expect(p.locator(".card-row", { hasText: "Golden" })).toContainText("30 modules");
});

test("pinned edits survive a re-fill: a deleted module stays deleted, its table stays put", async ({ page }) => {
  await goldenZone(page);
  const p = panel(page);
  await expect(p.locator(".preview-box")).toContainText("30 modules");
  await p.getByRole("button", { name: "Apply fill" }).click();
  await expect(p.locator(".card-row", { hasText: "Golden" })).toContainText("30 modules");

  // Delete one module: its table is pinned.
  const i = await firstTableModule(page);
  const gone = (await hook<string>(page, "moduleId", i))!;
  const neighbour = (await hook<string>(page, "moduleId", i + 1))!;
  await clickModule(page, i);
  await expect(p).toContainText("1 modules in 1 tables (0 pinned)");
  await page.keyboard.press("Delete");
  await expect(p.locator(".card-row", { hasText: "Golden" })).toContainText("29 modules");
  await expect(p.locator(".card-row", { hasText: "Golden" })).toContainText("1 pinned");

  // Re-fill in landscape (after Apply the form edits the same field): the preview keeps the pinned table and lists the diff.
  await expect(p).toContainText("Re-fill Golden");
  await expect(p.locator(".card-row", { hasText: "Golden" }).getByRole("button", { name: "Re-fill" })).toBeDisabled();
  await p.getByRole("radio", { name: /Landscape/ }).click();
  await expect(p.locator(".preview-box")).toContainText("1 pinned kept");
  await p.getByRole("button", { name: "Apply re-fill" }).click();
  await expect(page.locator(".toasts")).toContainText("pinned tables kept");

  const ids: string[] = [];
  const n = await hook<number>(page, "moduleCount");
  for (let k = 0; k < n; k++) ids.push((await hook<string>(page, "moduleId", k))!);
  expect(ids).not.toContain(gone);
  expect(ids).toContain(neighbour);
  await expect(p.locator(".card-row", { hasText: "Golden" })).toContainText("1 pinned");
});

test("a table drags by its module and the move is pinned; undo moves it back", async ({ page }) => {
  await goldenZone(page);
  const p = panel(page);
  await expect(p.locator(".preview-box")).toContainText("30 modules");
  await p.getByRole("button", { name: "Apply fill" }).click();
  await expect(p.locator(".card-row", { hasText: "Golden" })).toContainText("30 modules");
  const i = await firstTableModule(page);
  const before = await hook<[number, number]>(page, "moduleCentre", i);
  await clickModule(page, i);
  await p.getByLabel("Move east").fill("0");
  await p.getByLabel("Move north").fill("-0.3");
  await p.getByRole("button", { name: "Move tables" }).click();
  await expect(p.locator(".card-row", { hasText: "Golden" })).toContainText("1 pinned");
  const after = await hook<[number, number]>(page, "moduleCentre", i);
  expect(after[1]).toBeCloseTo(before[1] - 0.3, 6);
  await page.keyboard.press("Control+z");
  await expect(p.locator(".card-row", { hasText: "Golden" })).toContainText("0 pinned");
  expect((await hook<[number, number]>(page, "moduleCentre", i))[1]).toBeCloseTo(before[1], 6);

  // The same with the mouse: drag the module 1 m south with Shift (0.10 m steps).
  const [x0, y0] = await hook<[number, number]>(page, "toPage", before[0], before[1]);
  const [x1, y1] = await hook<[number, number]>(page, "toPage", before[0] + 0.02, before[1] - 1.01);
  await page.mouse.move(x0, y0);
  await page.mouse.down();
  await page.keyboard.down("Shift");
  await page.mouse.move(x1, y1, { steps: 6 });
  await page.mouse.up();
  await page.keyboard.up("Shift");
  await expect(p.locator(".card-row", { hasText: "Golden" })).toContainText("1 pinned");
  const dragged = await hook<[number, number]>(page, "moduleCentre", i);
  expect(dragged[0]).toBeCloseTo(before[0], 6);
  expect(dragged[1]).toBeCloseTo(before[1] - 1, 6);
});
