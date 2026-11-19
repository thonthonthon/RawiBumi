import { expect, test, type Page } from "@playwright/test";

// S15 in the demo: the synthetic series stays stamped in the same views; the run lists its launch warnings; the
// export form offers CSV and Parquet with the full deliverable on by default.

async function open(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
  await page.route("https://nominatim.openstreetmap.org/**", (route) => route.abort());
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  return errors;
}

test("demo Results: stamped synthetic monthly losses, meteo and PR; the launch warnings section", async ({ page }) => {
  const errors = await open(page);
  await page.keyboard.press("Alt+0");
  await expect(page.locator(".kpis")).toBeVisible();
  await expect(page.locator("[data-launch-warnings]")).toHaveAttribute("data-launch-warnings", "0");
  const kind = page.getByRole("radiogroup", { name: "Monthly quantity" });
  for (const [label, selector] of [["Losses", '[data-monthly-losses="DEMO_SYNTHETIC"]'], ["Meteo", '[data-monthly-meteo="DEMO_SYNTHETIC"]'], ["Performance", "[data-monthly-pr]"]] as const) {
    await kind.getByRole("radio", { name: label }).click();
    await expect(page.locator(selector)).toBeVisible();
    await expect(page.locator(selector).locator(".demo-stamp")).toBeVisible();
  }
  const views = page.getByRole("radiogroup", { name: "Result views" });
  await views.getByRole("radio", { name: "Daily profile" }).click();
  await expect(page.locator(".uplot")).toBeVisible();
  expect(errors).toEqual([]);
});

test("the export form: CSV and Parquet, the full deliverable on by default, and at least one format", async ({ page }) => {
  await open(page);
  await page.route("**/api/projects/*/runs/*/exports/schema", (route) => route.fulfill({ json: {
    project_id: "demo-project", run_id: "r", format: "csv", resolution: "hourly", level: "project", row_count: 2, timestamp_convention: "interval_start",
    timezone: "Asia/Jakarta", interval_seconds: 3600,
    columns: [{ id: "timestamp", label: "Interval start", unit: "ISO 8601", required: true }, { id: "pcc_power_w", label: "PCC power", unit: "W", required: false }] } }));
  let body: unknown = null;
  await page.route("**/api/projects/*/runs/*/exports", (route) => { body = route.request().postDataJSON(); return route.fulfill({ contentType: "application/zip", body: Buffer.from([80, 75, 3, 4]) }); });
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  const panel = page.locator("[data-csv-export]");
  const formats = panel.locator("[data-export-formats]");
  await expect(formats.getByRole("checkbox", { name: "CSV" })).toBeChecked();
  await expect(formats.getByRole("checkbox", { name: "Parquet" })).not.toBeChecked();
  await expect(panel.getByRole("checkbox", { name: /^Full deliverable/ })).toBeChecked();
  await formats.getByRole("checkbox", { name: "CSV" }).uncheck();
  await expect(panel.getByRole("button", { name: "Download CSV ZIP", exact: true })).toBeDisabled();
  await expect(formats).toContainText("Choose at least one file format.");
  await formats.getByRole("checkbox", { name: "Parquet" }).check();
  const download = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Download CSV ZIP", exact: true }).click();
  expect((await download).suggestedFilename()).toBe("RawiBumi_results_bundle.zip");
  expect(body).toEqual({ format: "csv", resolution: "hourly", level: "project", columns: ["pcc_power_w"], formats: ["parquet"], deliverable: true });
});
