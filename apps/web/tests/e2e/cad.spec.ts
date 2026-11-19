import { expect, test, type Page } from "@playwright/test";

// F3: every mouse operation has a typed form; edit handles; engine routes for rectangles, boxes and moves.

interface PlanHook {
  toPage: (x: number, y: number) => [number, number];
  view: { scale: number };
}

async function openScene(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+3");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("Scene");
  await page.waitForTimeout(300);
  return errors;
}

const toPage = (page: Page, x: number, y: number) =>
  page.evaluate(([a, b]) => (window as unknown as { __rawibumiPlan: PlanHook }).__rawibumiPlan.toPage(a, b), [x, y] as const);

/** Types into the plan's dynamic input and presses Enter. */
async function typeIn(page: Page, text: string) {
  await page.keyboard.type(text);
  await expect(page.locator(".plan__typed")).toBeVisible();
  await page.keyboard.press("Enter");
}

/** Draws the 8 × 8 m draft roof at (2, −14) entirely by typing. */
async function typedSquare(page: Page) {
  await page.keyboard.press("p");
  for (const s of ["2,-14", "@8,0", "8<0", "@-8,0"]) await typeIn(page, s);
  await page.keyboard.press("Enter");
  await expect(page.locator(".inspectorpane")).toContainText("64.00 m²");
}

const inspector = (page: Page) => page.locator(".inspectorpane");

test("a polygon roof drawn only by typing: absolute, relative and polar entries", async ({ page }) => {
  const errors = await openScene(page);
  await typedSquare(page);
  await expect(inspector(page)).toContainText("32.00 m");
  await expect(inspector(page)).not.toContainText("polygonSurface");
  expect(errors).toEqual([]);
});

test("typed input shows the point it will place, and refuses what it cannot read", async ({ page }) => {
  await openScene(page);
  await page.keyboard.press("p");
  await page.keyboard.type("3,4");
  await expect(page.locator(".plan__typed")).toContainText("Point 3.00, 4.00 m");
  await page.keyboard.press("Escape");
  await expect(page.locator(".plan__typed")).toHaveCount(0);
  await page.keyboard.type("1,2,3");
  await page.keyboard.press("Enter");
  await expect(page.locator(".plan__typed--bad")).toContainText("one comma");
  await page.keyboard.press("Escape");
  await page.keyboard.type("250cm,1200mm+0.3");
  await expect(page.locator(".plan__typed")).toContainText("Point 2.50, 1.50 m");
});

test("move tool with a typed base and @dx,dy; arrow keys nudge 0.10 m", async ({ page }) => {
  await openScene(page);
  await typedSquare(page);
  await page.keyboard.press("m");
  await typeIn(page, "2,-14");
  await typeIn(page, "@3,0");
  const rows = inspector(page).locator("tbody tr").first();
  await expect(rows).toContainText("5.000");
  await page.keyboard.press("v");
  await page.keyboard.press("ArrowUp");
  await expect(rows).toContainText("-13.900");
  await page.keyboard.press("Shift+ArrowRight");
  await expect(rows).toContainText("6.000");
});

test("rotate tool with a typed pivot and angle, clockwise as in the engine", async ({ page }) => {
  await openScene(page);
  await typedSquare(page);
  await page.keyboard.press("r");
  await typeIn(page, "2,-14");
  await typeIn(page, "90");
  // Turning (10, −14) by 90° clockwise about (2, −14) gives (2, −22).
  const second = inspector(page).locator("tbody tr").nth(1);
  await expect(second).toContainText("2.000");
  await expect(second).toContainText("-22.000");
  await expect(inspector(page)).toContainText("64.00 m²");
});

test("double-click a dimension to type its exact length; drag an edge handle along its normal", async ({ page }) => {
  await openScene(page);
  await typedSquare(page);
  await page.keyboard.press("v");
  // Edge 0 runs (2, −14) → (10, −14); its label sits just outside, below the edge.
  const [lx, ly] = await toPage(page, 6, -14);
  await page.mouse.dblclick(lx, ly + 15);
  const dim = page.getByRole("textbox", { name: "Edge length in metres" });
  await expect(dim).toHaveValue("8.00");
  await dim.fill("10");
  await dim.press("Enter");
  // A rectangle keeps its shape (preserve "rectangle"): both end-side corners move, the far side follows.
  await expect(inspector(page).locator("tbody tr").nth(1)).toContainText("12.000");
  await expect(inspector(page)).toContainText("80.00 m²");

  // Edge 2 is the top edge (12, −6) → (2, −6) after the edit … drag its handle 2 m outward (north).
  const [hx, hy] = await toPage(page, 7, -6);
  const [tx, ty] = await toPage(page, 7, -4);
  await page.keyboard.down("Alt"); // no snapping during the drag
  await page.mouse.move(hx, hy);
  await page.mouse.down();
  await page.mouse.move(tx, ty, { steps: 5 });
  await page.mouse.up();
  await page.keyboard.up("Alt");
  // The top edge moved 2 m north: C and D go from y −6 to −4, a 10 × 10 m rectangle of 100 m².
  await expect(inspector(page).locator("tbody tr").nth(2)).toContainText("-4.000");
  await expect(inspector(page)).toContainText("100.00 m²");
});

test("rectangle roof by two clicks and box obstacle by drag, both created in the engine", async ({ page }) => {
  await openScene(page);
  const layers = page.locator(".taskpanel .layer__name");
  const before = await layers.count();
  await page.keyboard.press("b");
  const [ax, ay] = await toPage(page, 16, -14);
  const [bx, by] = await toPage(page, 24, -6);
  await page.mouse.click(ax, ay);
  await expect(page.locator(".plan__hint")).toContainText("opposite corner");
  await page.mouse.click(bx, by);
  await expect(page.locator(".toasts")).toContainText("Roof created in the engine.");
  await expect(layers).toHaveCount(before + 1);

  await page.keyboard.press("o");
  await expect(page.getByRole("spinbutton", { name: /Height/ }).or(page.getByLabel("Height"))).toBeVisible();
  const [cx, cy] = await toPage(page, 26, -14);
  const [dx, dy] = await toPage(page, 29, -11);
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(dx, dy, { steps: 4 });
  await page.mouse.up();
  await expect(page.locator(".toasts")).toContainText("Obstacle created in the engine.");
  await expect(layers).toHaveCount(before + 2);
});

test("Z zooms to the selection, Z twice zooms to everything", async ({ page }) => {
  await openScene(page);
  await typedSquare(page);
  await page.keyboard.press("v");
  const scale = () => page.evaluate(() => (window as unknown as { __rawibumiPlan: PlanHook }).__rawibumiPlan.view.scale);
  const s0 = await scale();
  await page.keyboard.press("z");
  await expect.poll(scale).toBeGreaterThan(s0 * 1.5);
  await page.waitForTimeout(500);
  await page.keyboard.press("z");
  await page.keyboard.press("z");
  await expect.poll(scale).toBeLessThan(s0 * 1.2);
});

test("the shortcut sheet lists the plan tools from the shared table", async ({ page }) => {
  await openScene(page);
  await page.keyboard.press("Shift+?");
  const sheet = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  for (const name of ["Move", "Rotate", "Rectangle roof", "Box obstacle", "Measure"]) await expect(sheet).toContainText(name);
});
