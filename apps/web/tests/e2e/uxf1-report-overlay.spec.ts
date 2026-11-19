import { expect, test, type Page } from "@playwright/test";
import { openSection } from "./sections";

// UXF1 (U2-15): the report's plan figure draws the user's calibrated overlay under the design, with a caption; without
// an overlay it is the same image as before; a photo too large for the PDF falls back to a smaller figure.
async function idle(page: Page) {
  await expect.poll(async () => page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state.busy)).toBeNull();
}

test("the report figure shows the overlay, is unchanged without one, and always fits the PDF limit", async ({ page }) => {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+1"); await idle(page);
  await openSection(page, "Background image");
  const base64 = await page.evaluate(() => {
    const c = document.createElement("canvas"); c.width = 400; c.height = 300;
    const g = c.getContext("2d")!; g.fillStyle = "#ff00ff"; g.fillRect(0, 0, 400, 300);
    return c.toDataURL("image/png").split(",")[1];
  });
  await page.locator("[data-imagery-overlay] input[type=file]").setInputFiles({ name: "site.png", mimeType: "image/png", buffer: Buffer.from(base64, "base64") });
  await idle(page);

  const result = await page.evaluate(async () => {
    const { uiStore } = await import("/src/state/store.tsx");
    const { captureReportPlan } = await import("/src/report/build.ts");
    const { renderPlanFigure } = await import("/src/canvas/figure.ts");
    const { overlayStringsOf } = await import("/src/canvas/plan/electricalOverlay.ts");
    const { figureOverlayLoaded } = await import("/src/imagery/overlayImage.ts");
    const { t } = (await import("/src/i18n/index.ts")).default;
    const s = uiStore.getState().state;
    const base = { view: s.view!, entities: s.entities, modules: s.modules, t: t as (k: string) => string };
    const decode = async (png: string) => {
      const img = new Image(); img.src = png; await img.decode();
      const c = document.createElement("canvas"); c.width = img.width; c.height = img.height;
      const g = c.getContext("2d")!; g.drawImage(img, 0, 0);
      const d = g.getImageData(0, 0, c.width, c.height).data;
      let magenta = 0;
      for (let k = 0; k < d.length; k += 4) if (d[k] > 150 && d[k + 2] > 150 && d[k + 1] < 110) magenta++;
      return { width: img.width, magenta };
    };
    const plain = captureReportPlan({ ...base, overlay: null })!;
    const before = renderPlanFigure({ entities: s.entities, modules: s.modules, strings: overlayStringsOf(s.view!, s.modules), electrical: true,
      size: { w: 900, h: 540 }, labels: { north: t("plan.north"), draft: t("report.draft") } });
    const overlay = await figureOverlayLoaded(s.view!);
    const withOverlay = captureReportPlan({ ...base, overlay })!;
    // An uncompressible background filling an empty figure, one image pixel per print pixel: too large at dpr 2.
    const empty = { ...base, entities: [], modules: [] };
    const W = 2000, H = 1200, mpp = captureReportPlan({ ...empty, overlay: null })!.metresPerPx / 2;
    const noise = document.createElement("canvas"); noise.width = W; noise.height = H;
    const ng = noise.getContext("2d")!; const px = ng.createImageData(W, H);
    for (let k = 0; k < px.data.length; k++) px.data[k] = (k % 4 === 3) ? 255 : Math.floor(Math.random() * 256);
    ng.putImageData(px, 0, 0);
    const huge = captureReportPlan({ ...empty, overlay: { ...overlay!, image: noise as unknown as HTMLImageElement, width: W, height: H,
      transform: { offset: [-(W / 2) * mpp, (H / 2) * mpp] as [number, number], rotationDeg: 0, sx: mpp, sy: mpp }, opacity: 1 } })!;
    const bytes = (png: string) => Math.floor((png.length - png.indexOf(",") - 1) * 3 / 4);
    return { same: plain.png === before.png, plain: await decode(plain.png), overlay: overlay !== null,
      withOverlay: await decode(withOverlay.png), huge: { ...(await decode(huge.png)), bytes: bytes(huge.png) } };
  });
  expect(result.same).toBe(true); // no overlay: the figure is the one the report drew before
  expect(result.plain.magenta).toBe(0);
  expect(result.overlay).toBe(true);
  expect(result.withOverlay.magenta).toBeGreaterThan(1000); // the overlay is under the design
  expect(result.withOverlay.width).toBe(1800); // print resolution when it fits
  expect(result.huge.width).toBe(900); // shrunk to fit
  expect(result.huge.bytes).toBeLessThanOrEqual(4 * 1024 * 1024);
});
