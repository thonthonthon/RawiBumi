import { openSection } from "./sections";
import { expect, test, type Page } from "@playwright/test";

// UNC1 in the demo: no assumptions gives a reason, not a number; one sourced term gives P50–P95 and the P99 reason;
// the ledger is one undo step; the HTML report carries the Pxx block.

async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function idle(page: Page) { await expect.poll(async () => (await state(page)).busy).toBeNull(); }

async function open(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
  await page.route("https://nominatim.openstreetmap.org/**", (route) => route.abort());
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+0");
  await expect(page.locator(".kpis")).toBeVisible();
  return errors;
}

test("annual Pxx: reasons without assumptions, P50–P95 with one sourced term, undo, and the report block", async ({ page }) => {
  const errors = await open(page);
  await openSection(page, "P50–P95");
  const card = page.locator("[data-annual-pxx]");
  await expect(card).toHaveAttribute("data-annual-pxx", "unavailable");
  await card.getByRole("button", { name: "Uncertainty assumptions" }).click();
  await expect(card.locator("[data-pxx-reasons]")).toContainText("NO_ASSUMPTIONS");

  await card.locator("[data-pxx-add]").getByRole("button", { name: "+ Interannual solar variability" }).click();
  const term = card.locator('[data-pxx-term="interannual_solar_variability"]');
  await term.getByLabel("σ for interannual_solar_variability").fill("5");
  // Saving without a source is refused in the browser: nothing is invented.
  await card.getByRole("button", { name: "Save assumptions" }).click();
  await expect(card.getByRole("alert")).toContainText("needs a source and a justification");
  await term.getByLabel("Source for interannual_solar_variability").fill("Site resource study 2026");
  await term.getByLabel("Justification for interannual_solar_variability").fill("Ten-year satellite record spread");
  await card.getByLabel("Basis for the correlation assumption").fill("Single term");
  await card.getByRole("button", { name: "Save assumptions" }).click(); await idle(page);

  await expect(card).toHaveAttribute("data-annual-pxx", "available");
  const rows = card.locator("[data-pxx-table] [data-pxx]");
  await expect(rows).toHaveCount(5);
  await expect(card.locator('[data-pxx="P99"]')).toContainText("not qualified");
  await expect(card.locator("[data-pxx-basis]")).toContainText("Model-based estimate");
  const ledger = (await state(page)).view!.bundle.uncertainty_assumptions!;
  expect(ledger.terms).toEqual([{ source_key: "interannual_solar_variability", double_count_group: "solar_resource_weather", scope: "annual_weather",
    provenance_type: "user_assumption", source_ref: "Site resource study 2026", justification: "Ten-year satellite record spread", sigma_value: 0.05, sigma_unit: "fraction_of_annual_mean" }]);

  // The report carries the same Pxx block.
  await page.locator(".rail").getByRole("button", { name: /Report & export/ }).click();
  await page.getByRole("button", { name: "Preview report", exact: true }).click();
  const preview = page.frameLocator("iframe").first();
  await expect(preview.locator("[data-report-pxx]")).toContainText("P95");

  // One undo step removes the ledger again.
  await page.keyboard.press("Alt+0");
  await page.locator(".stage, .results").first().click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("Control+z"); await idle(page);
  expect((await state(page)).view!.bundle.uncertainty_assumptions).toBeUndefined();
  await expect(page.locator("[data-annual-pxx]")).toHaveAttribute("data-annual-pxx", "unavailable");
  expect(errors).toEqual([]);
});
