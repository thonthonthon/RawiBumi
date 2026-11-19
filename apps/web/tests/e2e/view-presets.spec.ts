import { expect, test, type Page } from "@playwright/test";

const state = (page: Page) => page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
async function open(page: Page) {
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+3");
  await expect(page.locator(".toollist")).toBeVisible();
}
const button = (page: Page, name: string) => page.getByRole("button", { name, exact: true });

test("Top → Front → Isometric → Top keeps the selected roof and zoomed region", async ({ page }) => {
  await open(page);
  await expect(button(page, "Perpendicular to face")).toBeDisabled();
  await page.locator(".taskpanel .layer__name").filter({ hasText: "Roof A" }).first().click();
  const selection = (await state(page)).selection;
  expect(selection.length).toBeGreaterThan(0);
  await expect(button(page, "Perpendicular to face")).toBeEnabled();
  const viewport = (await state(page)).planViewport!;
  for (const name of ["Front", "Isometric", "Top"]) {
    await button(page, name).click();
    await expect(button(page, name)).toHaveAttribute("aria-pressed", "true");
    expect((await state(page)).selection).toEqual(selection);
    expect((await state(page)).step).toBe("scene");
  }
  await expect(page.locator(".plan__canvas")).toBeVisible();
  await expect.poll(async () => (await state(page)).planViewport?.view).toEqual(viewport.view);
  await button(page, "Perpendicular to face").click();
  await expect(page.locator(".view3d__canvas")).toBeVisible();
});

test("Top-only tools show the note and return to Select outside Top", async ({ page }) => {
  await open(page);
  await page.keyboard.press("p");
  expect((await state(page)).tool).toBe("polygon");
  await button(page, "Front").click();
  await expect(page.getByRole("status").filter({ hasText: "This tool works in Top view" })).toBeVisible();
  expect((await state(page)).tool).toBe("select");
  await page.locator('.toollist button').filter({ hasText: "Measure" }).click();
  expect((await state(page)).tool).toBe("select");
  await button(page, "Top").click();
  await page.keyboard.press("p");
  expect((await state(page)).tool).toBe("polygon");
});

test("both geometry context menus offer View, with keyboard navigation and disabled face", async ({ page }) => {
  await open(page);
  for (const canvas of [".plan__canvas", ".view3d__canvas"]) {
    await page.locator(canvas).click({ button: "right", position: { x: 30, y: 220 } }); // below the 3D toolbar
    const view = page.getByRole("menuitem", { name: "View ▸", exact: true });
    await view.focus(); await page.keyboard.press("ArrowRight");
    const menu = page.getByRole("menu", { name: "View", exact: true });
    await expect(menu.getByRole("menuitemradio")).toHaveCount(7);
    await expect(menu.getByRole("menuitemradio", { name: "Perpendicular to face", exact: true })).toHaveAttribute("aria-disabled", "true");
    await expect(menu.getByRole("menuitemradio", { name: "Top", exact: true })).toBeFocused();
    await page.keyboard.press("ArrowDown"); await page.keyboard.press("Enter");
    await expect(button(page, "Front")).toHaveAttribute("aria-pressed", "true");
  }
});

test("free shortcuts switch geometry views and project reload remembers the chosen view", async ({ page }) => {
  await open(page);
  for (const [key, name] of [["Shift+F", "Front"], ["Shift+I", "Isometric"], ["Shift+T", "Top"]]) {
    await page.keyboard.press(key);
    await expect(button(page, name)).toHaveAttribute("aria-pressed", "true");
  }
  await button(page, "Right").click();
  await page.reload();
  await page.locator(".start__row").first().click();
  await expect(button(page, "Right")).toHaveAttribute("aria-pressed", "true");
  await button(page, "SLD").click();
  await expect(page.locator(".sld")).toBeVisible();
});
