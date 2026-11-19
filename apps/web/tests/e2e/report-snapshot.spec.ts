import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

test("editing the Site address invalidates the preview and HTML download captures the new snapshot", async ({ page }) => {
  await page.route("https://nominatim.openstreetmap.org/reverse**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    headers: { "access-control-allow-origin": "*" },
    body: JSON.stringify({ display_name: "Jalan Snapshot Lama" })
  }));
  await page.goto("/");
  await page.evaluate(() => window.localStorage.clear());
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+1");
  await expect(page.locator("[data-site-address]")).toHaveValue("Jalan Snapshot Lama");

  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await page.getByRole("button", { name: "Preview report" }).click();
  const iframe = page.locator('iframe[title="Report preview"]');
  await expect(iframe).toHaveAttribute("data-report-snapshot-id", /\S+/);
  const previousId = await iframe.getAttribute("data-report-snapshot-id");
  await expect(page.frameLocator('iframe[title="Report preview"]').locator("[data-address] td")).toHaveText("Jalan Snapshot Lama");

  await page.keyboard.press("Alt+1");
  await page.locator("[data-site-address]").fill("Jalan Snapshot Baru 27, Jakarta");
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  const stale = page.locator("[data-report-stale]");
  await expect(stale).toBeVisible();
  await expect(stale).toHaveAttribute("role", "status");
  await expect(stale).toContainText("Report inputs have changed");
  await expect(iframe).toHaveCount(0);

  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download HTML" }).click();
  const download = await downloading;
  const path = await download.path();
  expect(path).not.toBeNull();
  const html = await readFile(path!, "utf8");
  expect(html).toContain("Jalan Snapshot Baru 27, Jakarta");
  expect(html).not.toContain("Jalan Snapshot Lama");
  await expect(stale).toHaveCount(0);
  await expect(iframe).toHaveAttribute("data-report-snapshot-id", /\S+/);
  expect(await iframe.getAttribute("data-report-snapshot-id")).not.toBe(previousId);
  expect(await iframe.getAttribute("srcdoc")).toBe(html);
  const cover = page.frameLocator('iframe[title="Report preview"]').locator("[data-cover]");
  await expect(cover.locator("[data-address] td")).toHaveText("Jalan Snapshot Baru 27, Jakarta");
  await expect(cover.locator("[data-report-snapshot-id]")).toHaveCount(0);
});
