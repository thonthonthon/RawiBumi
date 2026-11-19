import { expect, test, type Page } from "@playwright/test";

// F2: the plan is drawn by three.js (WebGL) between two Canvas 2D layers, and
// modules are picked through a flatbush index. These checks read real pixels.

interface PlanHook {
  toPage: (x: number, y: number) => [number, number];
  view: { cx: number; cy: number; scale: number };
  moduleCentre: (i: number) => [number, number] | null;
  modulePolygon: (i: number) => [number, number][] | null;
}
interface PerfHook {
  modules: number;
  frames: () => number;
  pickBench: (n: number) => { mean: number; max: number; hits: number };
}

async function open(page: Page, query = "") {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`/${query}`);
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  return errors;
}

/** RGB of one page pixel, read from a screenshot (WebGL buffers are not readable after compositing). */
async function pixel(page: Page, x: number, y: number): Promise<[number, number, number]> {
  const png = await page.screenshot({ clip: { x: Math.round(x), y: Math.round(y), width: 1, height: 1 } });
  return page.evaluate(async (b64) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = c.height = 1;
    const ctx = c.getContext("2d")!;
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2]] as [number, number, number];
  }, png.toString("base64"));
}

const near = (a: number[], b: number[], tol = 24) => a.every((v, i) => Math.abs(v - b[i]) <= tol);

test("WebGL draws the modules and a click picks one, outlining it in the selection colour", async ({ page }) => {
  const errors = await open(page);
  await page.keyboard.press("Alt+4");
  await page.waitForTimeout(500);
  // Page points: the centre of module 10, and a point 1 px inside the middle of its first edge.
  const pts = await page.evaluate(() => {
    const plan = (window as unknown as { __rawibumiPlan: PlanHook }).__rawibumiPlan;
    const c = plan.moduleCentre(10)!;
    const poly = plan.modulePolygon(10)!;
    const cs = plan.toPage(c[0], c[1]);
    const a = plan.toPage(poly[0][0], poly[0][1]);
    const b = plan.toPage(poly[1][0], poly[1][1]);
    const m = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const len = Math.hypot(cs[0] - m[0], cs[1] - m[1]);
    return { centre: cs, edge: [m[0] + ((cs[0] - m[0]) / len) * 1.2, m[1] + ((cs[1] - m[1]) / len) * 1.2] };
  });
  const surface = [0x2e, 0x2b, 0x28];
  const fill = await pixel(page, pts.centre[0], pts.centre[1]);
  expect(near(fill, surface, 6)).toBe(false); // a module is drawn over the roof

  await page.mouse.click(pts.centre[0], pts.centre[1]);
  await expect(page.locator(".inspectorpane")).toContainText("Instance");
  await page.waitForTimeout(200);
  // DESIGN.md §6: the selection is a 2 px outline; the fill keeps its colour.
  expect(near(await pixel(page, pts.edge[0], pts.edge[1]), [0xff, 0xb2, 0x38])).toBe(true);
  expect(near(await pixel(page, pts.centre[0], pts.centre[1]), fill, 6)).toBe(true);
  expect(errors).toEqual([]);
});

test("the plan re-fits when the stage grows, until the user pans or zooms", async ({ page }) => {
  await open(page);
  await page.keyboard.press("Alt+4");
  await page.waitForTimeout(300);
  const scale = () => page.evaluate(() => (window as unknown as { __rawibumiPlan: PlanHook }).__rawibumiPlan.view.scale);
  const s0 = await scale();
  await page.keyboard.press("Alt+Backslash");
  await expect.poll(scale).toBeGreaterThan(s0 * 1.3);
});

test("3D preview renders the scene, labelled as a preview", async ({ page }) => {
  const errors = await open(page);
  await page.keyboard.press("Alt+6");
  await page.getByRole("button", { name: "Isometric", exact: true }).click();
  await expect(page.locator(".view3d__tag")).toHaveText("Preview");
  await page.waitForTimeout(800);
  const box = (await page.locator(".view3d__canvas").boundingBox())!;
  // Something other than the stage background is drawn near the middle.
  const bg = [0x26, 0x24, 0x22];
  let drawn = 0;
  for (const [fx, fy] of [[0.4, 0.5], [0.5, 0.5], [0.6, 0.55], [0.45, 0.6], [0.55, 0.45]]) {
    if (!near(await pixel(page, box.x + box.width * fx, box.y + box.height * fy), bg, 6)) drawn++;
  }
  expect(drawn).toBeGreaterThan(2);
  await page.getByRole("button", { name: "Reset view" }).click();
  expect(errors).toEqual([]);
});

test("100k synthetic modules: the plan draws and a pick takes under 16 ms (ADR 0002 gate)", async ({ page }) => {
  test.setTimeout(120_000);
  const errors = await open(page, "?synthetic=100000&perf");
  await page.keyboard.press("Alt+6");
  await page.waitForFunction(() => ((window as unknown as { __rawibumiPerf?: PerfHook }).__rawibumiPerf?.frames() ?? 0) > 0, null, { timeout: 60_000 });
  await expect(page.locator(".plan__synthetic")).toContainText("100000");
  await expect(page.locator(".plan__perf")).toContainText("100,000");
  const bench = await page.evaluate(() => (window as unknown as { __rawibumiPerf: PerfHook }).__rawibumiPerf.pickBench(500));
  expect(bench.hits).toBeGreaterThan(0);
  expect(bench.max).toBeLessThan(16);
  expect(errors).toEqual([]);
});

test("UI-A tools still work on the new renderer: polygon, measure, engine rectangle, move, Escape", async ({ page }) => {
  const errors = await open(page);
  await page.keyboard.press("Alt+3");
  await page.waitForTimeout(300);
  const toPage = (x: number, y: number) =>
    page.evaluate(([a, b]) => (window as unknown as { __rawibumiPlan: PlanHook }).__rawibumiPlan.toPage(a, b), [x, y] as const);
  const click = async (x: number, y: number) => {
    const [px, py] = await toPage(x, y);
    await page.mouse.click(px, py);
  };
  const layers = page.locator(".taskpanel .layer__name");
  const before = await layers.count();

  // Polygon surface: P, four clicks, Enter.
  await page.keyboard.press("p");
  await expect(page.locator(".plan__hint")).toBeVisible();
  for (const [x, y] of [[2, -14], [10, -14], [10, -6], [2, -6]]) await click(x, y);
  await page.keyboard.press("Enter");
  await expect(layers).toHaveCount(before + 1);

  // Measure: D, two clicks; the readout shows the hint until done.
  await page.keyboard.press("d");
  await click(2, -17);
  await click(10, -17);
  await page.keyboard.press("Escape");
  await expect(page.locator(".plan__hint")).toHaveCount(0);

  // Rectangle roof: B, drag; the demo engine creates the surface.
  await page.keyboard.press("b");
  const a = await toPage(16, -14);
  const b = await toPage(24, -6);
  await page.mouse.move(a[0], a[1]);
  await page.mouse.down();
  await page.mouse.move(b[0], b[1], { steps: 4 });
  await page.mouse.up();
  await expect(page.locator(".toasts")).toContainText("Roof created in the engine.");
  await expect(layers).toHaveCount(before + 2);

  // Move the draft polygon by dragging it; it stays a draft.
  await page.keyboard.press("v");
  const from = await toPage(6, -10);
  const to = await toPage(8, -10);
  await page.mouse.move(from[0], from[1]);
  await page.mouse.down();
  await page.mouse.move(to[0], to[1], { steps: 5 });
  await page.mouse.up();
  await expect(page.locator(".inspectorpane")).toContainText(/Surface/);
  expect(errors).toEqual([]);
});
