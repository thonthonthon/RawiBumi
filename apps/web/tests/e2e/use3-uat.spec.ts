import { openSection } from "./sections";
import { expect, test, type Page } from "@playwright/test";

// USE3 in the demo: the library is browsed through filters, and a field can lie parallel to its roof.
async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function idle(page: Page) { await expect.poll(async () => (await state(page)).busy).toBeNull(); }
const panel = (page: Page) => page.locator(".taskpanel");

async function open(page: Page, step: string) {
  await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press(step); await idle(page);
}

test("the library lists only what the filters match", async ({ page }) => {
  await open(page, "Alt+2"); await openSection(page, "Library");
  await expect(panel(page)).toContainText("In this project");
  const results = panel(page).locator("[data-library-results]");
  await expect(results).toHaveAttribute("data-library-results", "2");
  await panel(page).getByRole("combobox", { name: "Status" }).selectOption("layout_only");
  await expect(results).toHaveAttribute("data-library-results", "1");
  await panel(page).getByRole("radio", { name: "Modules" }).click();
  await panel(page).getByRole("combobox", { name: "Status" }).selectOption("all");
  await panel(page).getByRole("searchbox", { name: "Search components" }).fill("golden");
  await expect(results).toHaveAttribute("data-library-results", "1");
  await expect(results).toContainText("golden-case");
});

test("parallel to roof locks the tilt to the roof plane", async ({ page }) => {
  await open(page, "Alt+4");
  await panel(page).getByRole("radio", { name: "Parallel to roof" }).click();
  const tilt = panel(page).getByLabel(/^Tilt/);
  await expect(tilt).toBeDisabled();
  await expect(tilt).toHaveValue("0");
  await expect(panel(page)).toContainText("Modules lie in the roof plane");
});
