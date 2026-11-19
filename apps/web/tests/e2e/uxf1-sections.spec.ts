import { expect, test } from "@playwright/test";

// UXF1 (U2-16): sections start collapsed unless they hold the active work, open on a click, remember the viewer's
// choice in this browser, and their headings read apart from their content.
test("Systems checks start collapsed, open on click, and the choice is remembered", async ({ page }) => {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+5");
  const panel = page.locator(".taskpanel");
  const toggle = (name: string) => panel.getByRole("button", { name, exact: true });
  await expect(toggle("Checks")).toHaveAttribute("aria-expanded", "false");
  await expect(panel.locator(".section__body")).toHaveCount(2);

  await toggle("Checks").click();
  await expect(toggle("Checks")).toHaveAttribute("aria-expanded", "true");
  await expect(toggle("Buildings")).toHaveAttribute("aria-expanded", "true");

  // The heading is a band apart from its content, and the open one is marked.
  const look = await panel.locator(".section").filter({ has: page.getByRole("button", { name: "Checks", exact: true }) }).evaluate((el) => {
    const head = getComputedStyle(el.querySelector(".section__head")!);
    const body = getComputedStyle(el.querySelector(".section__body")!);
    return { headBg: head.backgroundColor, bodyBg: body.backgroundColor, edge: head.borderLeftWidth, indent: parseFloat(body.paddingLeft) };
  });
  expect(look.headBg).not.toBe(look.bodyBg);
  expect(look.edge).toBe("3px");
  expect(look.indent).toBeGreaterThan(16);

  await page.reload(); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+5");
  await expect(toggle("Checks")).toHaveAttribute("aria-expanded", "true"); // remembered
  await expect(toggle("Buildings")).toHaveAttribute("aria-expanded", "true");
});

test("the section holding the active work opens by default", async ({ page }) => {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+3");
  const panel = page.locator(".taskpanel");
  await expect(panel.getByRole("button", { name: "Layers", exact: true })).toHaveAttribute("aria-expanded", "true");
  await expect(panel.locator(".section__toggle").filter({ hasText: "Snap" }).first()).toHaveAttribute("aria-expanded", "false");
});
