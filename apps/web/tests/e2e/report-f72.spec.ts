import { openSection } from "./sections";
import { expect, test } from "@playwright/test";

// F7.2 (owner's direction, 22 Oct): installation type, PV capacity and BESS capacity in the
// cover's first section. Type and BESS are entered on the Site panel; PV capacity is the design's.

test("system summary: entered on the Site panel, shown on the report cover with its limits", async ({ page }) => {
  await page.route("https://nominatim.openstreetmap.org/reverse**", (r) => r.abort());
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.evaluate(() => window.localStorage.clear());
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+1");
  await openSection(page, "Installation type");

  await expect(page.locator("[data-pv-capacity]")).toHaveText("41.8 kWp");
  await page.getByLabel("Installation type").selectOption("hybrid");
  await page.getByLabel("BESS capacity").fill("1000");
  await page.getByLabel("BESS power (optional)").fill("500");
  await expect(page.locator("[data-system-note]")).toHaveClass(/note--warn/);

  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await page.getByRole("button", { name: "Preview report" }).click();
  const cover = page.frameLocator('iframe[title="Report preview"]').locator("[data-cover]");
  await expect(cover.locator("[data-installation-type] td")).toHaveText("Hybrid (grid and battery)");
  await expect(cover.locator("[data-pv-capacity] td")).toHaveText("41.8 kWp");
  await expect(cover.locator("[data-bess] td")).toHaveText("500 kW / 1.00 MWh");
  await expect(cover.locator("[data-not-simulated]")).toContainText("batteries, off-grid operation and export limits are not simulated");

  // Kept after a reload (this browser only).
  await page.reload();
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+1");
  await openSection(page, "Installation type");
  await expect(page.getByLabel("Installation type")).toHaveValue("hybrid");
  await expect(page.getByLabel("BESS capacity")).toHaveValue("1000");
  expect(errors).toEqual([]);
});
