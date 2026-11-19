import { expect, test, type Page } from "@playwright/test";

// F1.1: the task panel, the inspector and the rail can be minimised so the stage gets the room.

async function openElectrical(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6");
  await expect(page.locator('.rail [aria-current="step"]')).toContainText("Electrical");
}

const width = (page: Page, sel: string) => page.locator(sel).evaluate((el) => Math.round(el.getBoundingClientRect().width));

test("task panel and inspector collapse and expand with keys and buttons", async ({ page }) => {
  await openElectrical(page);
  const stage0 = await width(page, ".stage");

  await page.keyboard.press("Alt+BracketLeft");
  await expect(page.getByRole("button", { name: "Expand Electrical" })).toBeVisible();
  expect(await width(page, ".taskpanel")).toBe(32);

  await page.getByRole("button", { name: "Collapse Inspector" }).click();
  await expect(page.getByRole("button", { name: "Expand Inspector" })).toBeVisible();
  expect(await width(page, ".stage")).toBeGreaterThan(stage0 + 500);

  await page.getByRole("button", { name: "Expand Electrical" }).click();
  await page.keyboard.press("Alt+BracketRight");
  await expect(page.getByRole("button", { name: "Collapse Electrical" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Collapse Inspector" })).toBeVisible();
  expect(await width(page, ".stage")).toBe(stage0);
});

test("focus collapses all three panes, survives a reload and restores default widths", async ({ page }) => {
  await openElectrical(page);
  const stage0 = await width(page, ".stage");
  const focus = page.getByRole("button", { name: "Focus", exact: true });

  await page.keyboard.press("Alt+Backslash");
  await expect(focus).toHaveAttribute("aria-pressed", "true");
  expect(await width(page, ".rail")).toBe(56);
  const focused = await width(page, ".stage");
  expect(focused).toBeGreaterThan(stage0 * 2 - 40);

  await page.reload();
  await page.locator(".start__row").first().click();
  await expect(page.getByRole("button", { name: "Focus", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(await width(page, ".stage")).toBe(focused);

  await page.getByRole("button", { name: "Focus", exact: true }).click();
  await expect(page.getByRole("button", { name: "Focus", exact: true })).toHaveAttribute("aria-pressed", "false");
  await expect.poll(() => width(page, ".taskpanel")).toBe(320);
  expect(await width(page, ".inspectorpane")).toBe(290);
  expect(await width(page, ".rail")).toBe(196);
});

test("compact rail keeps step names in the accessible name", async ({ page }) => {
  await openElectrical(page);
  await page.getByRole("button", { name: "Compact rail" }).click();
  expect(await width(page, ".rail")).toBe(56);
  await expect(page.getByRole("button", { name: /PV layout/ })).toBeVisible();
});

test("inverter sections collapse together and fold away from three inverters", async ({ page }) => {
  await openElectrical(page);
  const task = page.locator(".taskpanel");
  const add = task.getByRole("button", { name: "Add inverter" });
  await add.click();
  await expect(task.locator(".sectionbar")).toContainText("2 inverters");
  await add.click();
  await expect(task.locator(".sectionbar")).toContainText("3 inverters");

  const heads = task.locator(".section__toggle", { hasText: /^▸?▾?INV-/ });
  await expect(heads).toHaveCount(3);
  // The newest stays open, the others fold away and show a one-line summary.
  await expect(heads.nth(0)).toHaveAttribute("aria-expanded", "false");
  await expect(heads.nth(1)).toHaveAttribute("aria-expanded", "false");
  await expect(heads.nth(2)).toHaveAttribute("aria-expanded", "true");
  await expect(task.locator(".section__summary").first()).toContainText("MPPT");

  await task.getByRole("button", { name: "Expand all" }).click();
  for (let i = 0; i < 3; i++) await expect(heads.nth(i)).toHaveAttribute("aria-expanded", "true");
  await task.getByRole("button", { name: "Collapse all" }).click();
  for (let i = 0; i < 3; i++) await expect(heads.nth(i)).toHaveAttribute("aria-expanded", "false");
});
