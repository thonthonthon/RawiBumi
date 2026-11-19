import { expect, test, type Page } from "@playwright/test";

// F5 (plan C2): the electrical tools on the demo engine. Every gesture is one
// topology command and one undo step, and the plan, tree and notation agree.

const hook = <T,>(page: Page, fn: string, ...args: number[]) =>
  page.evaluate(([f, a]) => {
    const h = (window as unknown as { __rawibumiPlan: Record<string, (...x: number[]) => unknown> }).__rawibumiPlan;
    return h[f as string](...(a as number[])) as T;
  }, [fn, args] as const);

const panel = (page: Page) => page.locator(".taskpanel");
const notation = (page: Page) => panel(page).getByLabel("MPPT layout");
const target = (page: Page) => page.locator(".quantities").locator("div", { hasText: "Target" }).locator("dd");

/** Page coordinates of the i-th module of the plan. */
async function modulePoint(page: Page, i: number): Promise<[number, number]> {
  const c = await hook<[number, number]>(page, "moduleCentre", i);
  return hook<[number, number]>(page, "toPage", c[0], c[1]);
}

async function clickModule(page: Page, i: number) {
  const [x, y] = await modulePoint(page, i);
  await page.mouse.click(x, y);
}

/** Plan indices of the modules of a string, in plan order. */
async function modulesOf(page: Page, stringId: string): Promise<number[]> {
  const n = await hook<number>(page, "moduleCount");
  const out: number[] = [];
  for (let i = 0; i < n; i++) if ((await hook<string | null>(page, "moduleString", i)) === stringId) out.push(i);
  return out;
}

async function openElectrical(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("Electrical");
  await expect(notation(page)).toHaveValue("16,0 ; 16,0 ; 16,0 ; 14,14");
  await page.waitForTimeout(300); // let the plan fit the stage above the string table
  return errors;
}

test("target keys, split, join and reverse keep the tree and the notation in step; each is one undo", async ({ page }) => {
  const errors = await openElectrical(page);
  const tree = page.getByRole("treegrid", { name: /Electrical topology/ });
  await expect(tree).toContainText("INV-01");
  await expect(tree).toContainText("MPPT 4");

  // [ ] and 1–9 set the target MPPT.
  await page.keyboard.press("]");
  await expect(target(page)).toHaveText("INV-01 · MPPT 1");
  await page.keyboard.press("3");
  await expect(target(page)).toHaveText("INV-01 · MPPT 3");
  await page.keyboard.press("[");
  await expect(target(page)).toHaveText("INV-01 · MPPT 2");

  const s1 = await modulesOf(page, "S1");
  expect(s1).toHaveLength(16);

  // Split (X) after the 5th module: S1 keeps 5, the new S6 gets 11, both on MPPT 1.
  await page.keyboard.press("x");
  await clickModule(page, s1[4]);
  await expect(notation(page)).toHaveValue("5,11 ; 16,0 ; 16,0 ; 14,14");
  await expect(tree).toContainText("S6");

  // Join (J): S1 then S6 gives S1 back with 16 modules.
  await page.keyboard.press("j");
  await clickModule(page, s1[0]);
  await clickModule(page, s1[10]);
  await expect(notation(page)).toHaveValue("16,0 ; 16,0 ; 16,0 ; 14,14");
  await expect(tree).not.toContainText("S6");

  // Reverse (R) keeps the lengths; it is one undo step of its own.
  await page.keyboard.press("r");
  await clickModule(page, s1[3]);
  await expect(page.locator(".statusbar__busy")).toHaveText("");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Control+z"); // reverse
  await expect.poll(() => page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state.past.length)).toBe(2);
  await expect(notation(page)).toHaveValue("16,0 ; 16,0 ; 16,0 ; 14,14");
  await page.keyboard.press("Control+z"); // join
  await expect(notation(page)).toHaveValue("5,11 ; 16,0 ; 16,0 ; 14,14");
  await page.keyboard.press("Control+Shift+z");
  await expect(notation(page)).toHaveValue("16,0 ; 16,0 ; 16,0 ; 14,14");
  expect(errors).toEqual([]);
});

test("string path creates a string on the target MPPT; the assign brush moves it", async ({ page }) => {
  const errors = await openElectrical(page);
  // Free S5's 14 modules: select it from the string table, then delete it.
  await page.locator(".stringtable tbody tr", { hasText: "S5" }).click();
  await expect(panel(page)).toContainText("14 modules selected");
  await panel(page).getByRole("button", { name: "Delete strings" }).click();
  await expect(notation(page)).toHaveValue("16,0 ; 16,0 ; 16,0 ; 14,0");

  const n = await hook<number>(page, "moduleCount");
  const free: number[] = [];
  for (let i = 0; i < n; i++) if ((await hook<string | null>(page, "moduleString", i)) === null) free.push(i);
  expect(free).toHaveLength(14);

  // String path (S) on MPPT 4: three clicks, Enter.
  await page.keyboard.press("4");
  await expect(target(page)).toHaveText("INV-01 · MPPT 4");
  await page.keyboard.press("s");
  for (const i of free.slice(0, 3)) await clickModule(page, i);
  await page.keyboard.press("Enter");
  await expect(notation(page)).toHaveValue("16,0 ; 16,0 ; 16,0 ; 14,3");
  // Three 550 W modules give Vmp ≈ 126 V, below the 200 V MPPT window: the engine's live check fails it.
  const row = page.locator(".stringtable tbody tr", { hasText: "S5" });
  await expect(row.locator(".checkglyph--fail")).toBeVisible();
  await expect(row.locator(".checkglyph--fail")).toHaveAttribute("aria-label", /outside the MPPT window/);

  // Assign brush (A) onto MPPT 1.
  await page.keyboard.press("1");
  await page.keyboard.press("a");
  await clickModule(page, free[1]);
  await expect(notation(page)).toHaveValue("16,3 ; 16,0 ; 16,0 ; 14,0");
  expect(errors).toEqual([]);
});

test("a notation edit shows its diff; Discard restores it and Apply changes the engine", async ({ page }) => {
  const errors = await openElectrical(page);
  const p = panel(page);
  await notation(page).fill("16,0 ; 16,0 ; 16,0 ; 14,0");
  await expect(p.locator(".notation-diff")).toContainText("MPPT 4: 14,14 → 14");
  await p.getByRole("button", { name: "Discard" }).click();
  await expect(notation(page)).toHaveValue("16,0 ; 16,0 ; 16,0 ; 14,14");
  await expect(p.locator(".notation-diff")).toHaveCount(0);

  await notation(page).fill("16,0 ; 16,0 ; 16,0 ; 14,0");
  await p.getByRole("button", { name: "Apply layout" }).click();
  await expect(notation(page)).toHaveValue("16,0 ; 16,0 ; 16,0 ; 14,0");
  await expect(p.locator(".notation-diff")).toHaveCount(0);
  // STR2: the string the layout no longer has is removed and its modules are free to re-string (as in Systems).
  await expect(page.getByRole("treegrid", { name: /Electrical topology/ })).toContainText("S4");
  await expect(page.getByRole("treegrid", { name: /Electrical topology/ })).not.toContainText("S5");
  // One undo step.
  await page.locator(".stage").click({ position: { x: 5, y: 60 } });
  await page.keyboard.press("Control+z");
  await expect(notation(page)).toHaveValue("16,0 ; 16,0 ; 16,0 ; 14,14");
  expect(errors).toEqual([]);
});

test("the lasso selects the modules inside the loop", async ({ page }) => {
  const errors = await openElectrical(page);
  const s1 = await modulesOf(page, "S1");
  const pts = await Promise.all(s1.slice(0, 4).map((i) => modulePoint(page, i)));
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs) - 6, Math.max(...xs) + 6, Math.min(...ys) - 6, Math.max(...ys) + 6];
  await page.keyboard.press("l");
  await page.mouse.move(x0, y0);
  await page.mouse.down();
  for (const [x, y] of [[x1, y0], [x1, y1], [x0, y1], [x0, y0 + 1]] as const) await page.mouse.move(x, y, { steps: 6 });
  await page.mouse.up();
  await expect(panel(page)).toContainText(/\d+ modules selected/);
  const text = await panel(page).locator("p.sub", { hasText: "modules selected" }).innerText();
  expect(Number(text.match(/(\d+) modules selected/)![1])).toBeGreaterThanOrEqual(4);
  expect(errors).toEqual([]);
});

test("the string table lists every string and sorts by a column", async ({ page }) => {
  const errors = await openElectrical(page);
  const rows = page.locator(".stringtable tbody tr");
  await expect(rows).toHaveCount(5);
  await page.locator(".stringtable thead").getByRole("button", { name: /Modules/ }).click();
  await expect(rows.first()).toContainText("14");
  await expect(page.locator(".stringtable thead th", { hasText: "Modules" })).toHaveAttribute("aria-sort", "ascending");
  expect(errors).toEqual([]);
});
