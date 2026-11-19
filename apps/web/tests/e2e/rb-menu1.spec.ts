import { expect, test } from "@playwright/test";
import { openSection } from "./sections";
import { en } from "../../src/i18n/en";
import { id } from "../../src/i18n/id";

test("moved sections belong to Losses & grid; Weather and Simulate keep their own sections", async ({ page }) => {
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  const headings = page.locator(".taskpanel .section__toggle");
  await page.keyboard.press("Alt+7");
  await expect(headings).toHaveText([/Weather$/]); // toggles start with ▾/▸
  await expect(page.locator(".taskpanel")).toContainText(en.stepIntros.weatherCaveat);
  await page.keyboard.press("Alt+8");
  await expect(headings).toHaveText([/Losses$/, /Optics & thermal$/, /Shading accuracy$/, /Load & zero export$/]);
  await openSection(page, "Losses");
  await openSection(page, "Optics & thermal");
  await expect(page.locator("[data-optics-settings]")).toBeVisible();
  await expect(page.locator("[data-loss-settings]")).toBeVisible();
  await openSection(page, "Load & zero export");
  await expect(page.getByLabel("CSV: timestamp, value")).toBeVisible();
  await openSection(page, "Load & zero export");
  await expect(page.getByLabel("Export limit", { exact: false })).toBeVisible();
  await openSection(page, "Shading accuracy");
  await expect(page.locator("[data-shading-accuracy]")).toBeVisible();
  await page.keyboard.press("Alt+9");
  await expect(headings).toContainText(["Before you run", "Preflight", "Execution options", "Run history"]);
  await expect(headings.filter({ hasText: "Shading accuracy" })).toHaveCount(0);
});

for (const [step, label] of [["meteo", "Weather"], ["unknown-step", "Scene"], ["losses", "Losses & grid"]]) {
  test(`?step=${step} preserves step-id routing`, async ({ page }) => {
    await page.goto(`/?step=${step}`);
    await page.locator(".start__row").first().click();
    await expect(page.locator('.rail [aria-current="step"]')).toContainText(label);
  });
}

for (const [language, messages] of [["en", en], ["id", id]] as const) {
  test(`every step starts with its ${language} intro and matches its numbered shortcut`, async ({ page }) => {
    await page.addInitScript(lang => localStorage.setItem("rawibumi.language", lang), language);
    await page.goto("/");
    await page.locator(".start__row").first().click();
    const keys = ["site", "components", "scene", "layout", "systems", "electrical", "meteo", "losses", "simulate", "results", "export"] as const;
    await expect(page.locator(".rail__step .rail__label")).toHaveText(keys.map(key => messages.steps[key]));
    for (const [index, key] of keys.entries()) {
      const railStep = page.locator(".rail__step").nth(index);
      await expect(railStep.locator(".rail__num")).toHaveText(String(index + 1).padStart(2, "0"));
      if (index < 10) {
        const shortcut = (index + 1) % 10;
        await expect(railStep).toHaveAttribute("title", new RegExp(`Alt\\+${shortcut}$`));
        await page.keyboard.press(`Alt+${shortcut}`);
      } else {
        await expect(railStep).not.toHaveAttribute("title", /Alt\+/);
        await page.keyboard.press("Control+k");
        await page.getByPlaceholder(messages.commands.placeholder).fill(messages.steps.export);
        await page.keyboard.press("Enter");
      }
      await expect(railStep).toHaveAttribute("aria-current", "step");
      const panel = index < 9 ? page.locator(".taskpanel .pane__body") : page.locator(".fullview");
      await expect(panel.locator(":scope > p").first()).toHaveText(messages.stepIntros[key]);
    }
  });
}
