import { expect, test } from "@playwright/test";

// DATA1 needs the engine's project files; the demo hides those controls instead of imitating them.
test("the demo project list has no import, export or backups controls, and still opens a project", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".start__row").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Import project", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Export…", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Backups…", exact: true })).toHaveCount(0);
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await expect(page.locator("[data-project-file]")).toHaveCount(0);
});
