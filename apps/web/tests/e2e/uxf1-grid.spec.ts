import { expect, test, type Page } from "@playwright/test";
import { openSection } from "./sections";

// UXF1 (U2-14): grid lines stay on above an image overlay (with a halo), follow the snap spacing, and the stage toggle
// hides them and is remembered in this browser.
async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function idle(page: Page) { await expect.poll(async () => (await state(page)).busy).toBeNull(); }

test("grid lines draw over an overlay, follow the snap spacing, and the toggle hides them", async ({ page }) => {
  // Record every stroke on the plan's base canvas: [lineWidth, number of path segments].
  await page.addInitScript(() => {
    const strokes: Array<[number, number]> = [];
    (window as unknown as { __strokes: typeof strokes }).__strokes = strokes;
    const proto = CanvasRenderingContext2D.prototype;
    const moveTo = proto.moveTo, beginPath = proto.beginPath, stroke = proto.stroke;
    let segments = 0;
    proto.beginPath = function () { segments = 0; return beginPath.call(this); };
    proto.moveTo = function (x: number, y: number) { segments++; return moveTo.call(this, x, y); };
    proto.stroke = function (...args: []) {
      if (this.canvas.classList.contains("plan__layer")) strokes.push([this.lineWidth, segments]);
      return stroke.apply(this, args);
    };
  });
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+1"); await idle(page);
  await openSection(page, "Background image");
  const base64 = await page.evaluate(() => {
    const c = document.createElement("canvas"); c.width = 400; c.height = 300;
    const g = c.getContext("2d")!; g.fillStyle = "#3a7"; g.fillRect(0, 0, 400, 300);
    return c.toDataURL("image/png").split(",")[1];
  });
  await page.locator("[data-imagery-overlay] input[type=file]").setInputFiles({ name: "roof.png", mimeType: "image/png", buffer: Buffer.from(base64, "base64") });
  await idle(page);
  await expect(page.locator("[data-imagery-overlay]")).toHaveAttribute("data-imagery-overlay", "unlocked");

  const grid = page.locator("[data-grid-toggle]");
  await expect(grid).toHaveAttribute("aria-pressed", "true");
  // Each step below redraws the base canvas; read what that redraw stroked, then clear the record.
  const drawn = async () => page.evaluate(() => {
    const all = (window as unknown as { __strokes: Array<[number, number]> }).__strokes;
    const out = { halos: all.filter(([w, n]) => w === 3 && n > 2).length, strokes: all.length };
    all.length = 0;
    return out;
  });
  expect((await drawn()).halos).toBeGreaterThan(0); // grid lines with their halo, above the overlay

  await grid.click();
  await expect(grid).toHaveAttribute("aria-pressed", "false");
  await expect.poll(async () => (await page.evaluate(() => (window as unknown as { __strokes: unknown[] }).__strokes.length))).toBeGreaterThan(0);
  expect((await drawn()).halos).toBe(0);
  await page.reload(); await page.locator(".start__row").first().click(); await expect(page.locator(".rail")).toBeVisible();
  await expect(page.locator("[data-grid-toggle]")).toHaveAttribute("aria-pressed", "false"); // remembered
  await page.locator("[data-grid-toggle]").click();
  await expect(page.locator("[data-grid-toggle]")).toHaveAttribute("aria-pressed", "true");
});

test("with grid snapping on, the fine grid uses the snap spacing", async ({ page }) => {
  await page.addInitScript(() => {
    const strokes: number[] = [];
    (window as unknown as { __segments: number[] }).__segments = strokes;
    const proto = CanvasRenderingContext2D.prototype;
    const moveTo = proto.moveTo, beginPath = proto.beginPath, stroke = proto.stroke;
    let n = 0;
    proto.beginPath = function () { n = 0; return beginPath.call(this); };
    proto.moveTo = function (x: number, y: number) { n++; return moveTo.call(this, x, y); };
    proto.stroke = function (...args: []) { if (this.canvas.classList.contains("plan__layer")) strokes.push(n); return stroke.apply(this, args); };
  });
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+3"); await idle(page);
  await page.evaluate(async () => {
    const { uiStore } = await import("/src/state/store.tsx");
    (window as unknown as { __segments: number[] }).__segments.length = 0;
    uiStore.getState().dispatch({ type: "setSnap", patch: { user_grid: true, grid_spacing_m: 0.5 } });
  });
  await page.waitForTimeout(300);
  const { drawn, expected } = await page.evaluate(() => {
    const plan = (window as unknown as { __rawibumiPlan: { toPage(x: number, y: number): [number, number] } }).__rawibumiPlan;
    const pxPerM = Math.abs(plan.toPage(1, 0)[0] - plan.toPage(0, 0)[0]);
    const base = document.querySelector("canvas.plan__layer") as HTMLCanvasElement;
    const { width, height } = base.getBoundingClientRect();
    return { drawn: Math.max(...(window as unknown as { __segments: number[] }).__segments),
      expected: (width + height) / (pxPerM * 0.5) };
  });
  expect(Math.abs(drawn - expected)).toBeLessThanOrEqual(4); // one line every 0.5 m across and down the view
});
