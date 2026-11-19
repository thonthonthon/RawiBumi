import fs from "node:fs";
import { expect, test, type Page } from "@playwright/test";

// F7 done-when (plan C2): S10's result rules pass (unit tests, and shown on screen here), and
// the report figure and the workstation drawing come from one renderer (pixel parity below).

async function open(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  return errors;
}

test("results: charts from the shared options, S10 checks with no failure, the 52-week heatmap and its coverage", async ({ page }) => {
  const errors = await open(page);
  await page.keyboard.press("Alt+0");
  await expect(page.getByRole("heading", { name: "Results", exact: true })).toBeVisible();
  await expect(page.locator('[data-authority="DEMO_SYNTHETIC"]')).toBeVisible();
  await expect(page.locator("[data-rule-fails]")).toHaveAttribute("data-rule-fails", "0");
  await expect(page.locator('[data-chart="Monthly energy bar chart"] canvas').first()).toBeVisible();

  await page.getByRole("radio", { name: "Loss waterfall" }).click();
  await expect(page.locator('[data-chart="Loss waterfall from reference energy to AC energy"] canvas').first()).toBeVisible();

  await page.getByRole("radio", { name: "Heatmap" }).click();
  await expect(page.locator('[data-chart="Heatmap of mean power by week and hour"] canvas').first()).toBeVisible();
  await expect(page.locator("[data-coverage]")).toContainText("Shows 8,736 of 8,760 hours");
  await expect(page.locator("[data-coverage]")).toContainText("the last 24 hours of the year are left out of this view only. 0 source hours are missing");

  await page.getByRole("radio", { name: "Daily profile" }).click();
  await expect(page.locator('[data-chart="Average daily power profile"] canvas').first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("one renderer: the report figure renderer draws the plan's WebGL layer pixel for pixel", async ({ page }) => {
  const errors = await open(page);
  await page.keyboard.press("Alt+6");
  await page.waitForTimeout(600);
  await page.keyboard.press("Escape");
  const diff = await page.evaluate(async () => {
    const h = (window as unknown as { __rawibumiPlan: { glSnapshot: () => string; figureGl: () => string } }).__rawibumiPlan;
    const load = (src: string) =>
      new Promise<ImageData>((res) => {
        const img = new Image();
        img.onload = () => {
          const c = document.createElement("canvas");
          c.width = img.width;
          c.height = img.height;
          const x = c.getContext("2d")!;
          x.drawImage(img, 0, 0);
          res(x.getImageData(0, 0, c.width, c.height));
        };
        img.src = src;
      });
    const a = await load(h.glSnapshot());
    const b = await load(h.figureGl());
    if (a.width !== b.width || a.height !== b.height) return { sizes: [a.width, a.height, b.width, b.height], mean: 1, painted: 0 };
    let sum = 0;
    let painted = 0;
    for (let i = 0; i < a.data.length; i += 4) {
      if (a.data[i + 3] > 0) painted++;
      for (let k = 0; k < 4; k++) sum += Math.abs(a.data[i + k] - b.data[i + k]);
    }
    return { sizes: [a.width, a.height], mean: sum / (a.data.length * 255), painted };
  });
  // The plan is not blank, and the figure renderer reproduces it (antialiasing tolerance only).
  expect(diff.painted).toBeGreaterThan(10_000);
  expect(diff.mean).toBeLessThan(0.002);
  expect(errors).toEqual([]);
});

test("report: eleven chapters, the plan figure, the workstation SLD, the 52-week caption; download is one HTML file", async ({ page }) => {
  const errors = await open(page);
  // The workstation SLD's inverter symbol, to compare with the report.
  await page.keyboard.press("Alt+6");
  await page.getByRole("button", { name: "SLD", exact: true }).click();
  const sldInverter = await page.locator('[data-node="inv:inv-01"] [data-symbol-body="inverter"]').innerHTML();

  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await expect(page.getByRole("radio", { name: "Branded" })).toBeDisabled();
  await page.getByRole("button", { name: "Preview report" }).click();
  const frame = page.frameLocator('iframe[title="Report preview"]');
  await expect(frame.locator("[data-chapter]")).toHaveCount(12);
  await expect(frame.locator("body")).toHaveAttribute("data-authority", "DEMO_SYNTHETIC");
  await expect(frame.locator(".stamp")).toContainText("Demo data");
  // The plan figure: a PNG drawn at twice the figure size by the plan renderer.
  const natural = await frame.locator("img[data-plan-figure]").evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight]);
  expect(natural).toEqual([1800, 1080]);
  // The SLD: the same component as the workstation, so the same symbol markup.
  expect(await frame.locator('[data-node="inv:inv-01"] [data-symbol-body="inverter"]').innerHTML()).toBe(sldInverter);
  await expect(frame.locator("#ch-heatmap figcaption")).toContainText("shows 8,736 hours of 8,760; 24 hours at the end of the year are left out of this view only. 0 source hours are missing");
  await expect(frame.locator("#ch-checks .rule-fail")).toHaveCount(0);
  await expect(frame.locator("[data-branding]")).toHaveCount(0);

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download HTML" }).click()]);
  expect(download.suggestedFilename()).toMatch(/^RawiBumi_report_.+\.html$/);
  const html = fs.readFileSync((await download.path())!, "utf8");
  expect(html.startsWith("<!doctype html>")).toBe(true);
  // Self-contained: fonts and the figure are embedded, no external stylesheet or script.
  expect(html).toContain("data:font/woff2;base64,");
  expect(html).toContain("data:image/png;base64,");
  expect(html).not.toMatch(/<link\b|<script\b/);
  expect(errors).toEqual([]);
});
