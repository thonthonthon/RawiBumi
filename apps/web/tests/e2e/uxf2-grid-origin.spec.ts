import { expect, test, type Page } from "@playwright/test";

// UXF2 (U2-17, U2-18, U2-19): the grid keeps the grid-spacing setting at every zoom (snapping on or off), and the scene
// origin carries labelled X and Y arrows.
async function idle(page: Page) {
  await expect.poll(async () => page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state.busy)).toBeNull();
}

test("the fine grid stays at the grid spacing whatever the zoom, and the origin is labelled X and Y", async ({ page }) => {
  await page.addInitScript(() => {
    const log = { segments: [] as number[], labels: [] as string[] };
    (window as unknown as { __grid: typeof log }).__grid = log;
    const proto = CanvasRenderingContext2D.prototype;
    const moveTo = proto.moveTo, beginPath = proto.beginPath, stroke = proto.stroke, fillText = proto.fillText;
    let n = 0;
    proto.beginPath = function () { n = 0; return beginPath.call(this); };
    proto.moveTo = function (x: number, y: number) { n++; return moveTo.call(this, x, y); };
    proto.stroke = function (...a: []) { if (this.canvas.classList.contains("plan__layer") && this.lineWidth === 1) log.segments.push(n); return stroke.apply(this, a); };
    proto.fillText = function (text: string, x: number, y: number, w?: number) {
      if (this.canvas.classList.contains("plan__layer")) log.labels.push(text);
      return w === undefined ? fillText.call(this, text, x, y) : fillText.call(this, text, x, y, w);
    };
  });
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+3"); await idle(page);
  const measure = () => page.evaluate(async () => {
    await new Promise((r) => setTimeout(r, 300));
    const log = (window as unknown as { __grid: { segments: number[]; labels: string[] } }).__grid;
    const plan = (window as unknown as { __rawibumiPlan: { toPage(x: number, y: number): [number, number] } }).__rawibumiPlan;
    const pxPerM = Math.abs(plan.toPage(1, 0)[0] - plan.toPage(0, 0)[0]);
    const { width, height } = (document.querySelector("canvas.plan__layer") as HTMLCanvasElement).getBoundingClientRect();
    const out = { fine: Math.max(...log.segments), expected: (width + height) / (pxPerM * 0.5), pxPerM, labels: [...log.labels] };
    log.segments.length = 0; log.labels.length = 0;
    return out;
  });
  const near = await measure();
  expect(near.pxPerM * 0.5).toBeGreaterThanOrEqual(6);
  expect(Math.abs(near.fine - near.expected)).toBeLessThanOrEqual(4); // one fine line every 0.5 m (snapping is off)
  expect(near.labels).toEqual(expect.arrayContaining(["X", "Y"]));

  const box = (await page.locator(".plan__canvas").boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, 300); // zoom out
  await page.waitForTimeout(500);
  const far = await measure();
  expect(far.pxPerM).toBeLessThan(near.pxPerM * 0.8);
  if (far.pxPerM * 0.5 >= 6) expect(Math.abs(far.fine - far.expected)).toBeLessThanOrEqual(4); // still 0.5 m, not re-stepped
  else expect(far.fine).toBeLessThan(near.fine + 1); // fine lines too dense to draw: only the 5 m lines remain
  expect(far.labels).toEqual(expect.arrayContaining(["X", "Y"]));
});
