import { expect, test, type Page } from "@playwright/test";

// UXF1 (U2-1): a number field that saves to the design commits on Enter, leaving the field or a stepper; typing alone
// never saves, and Esc restores the saved value.
async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function typed(page: Page, value: string) {
  await page.keyboard.type(value); await expect(page.locator(".plan__typed")).toBeVisible(); await page.keyboard.press("Enter");
  await expect(page.locator(".plan__typed")).toBeHidden();
}

test("typing a two-digit height saves it once, on Enter; Esc, Tab, the stepper and an empty entry behave", async ({ page }) => {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+3");
  await page.keyboard.press("o"); await typed(page, "15,-14"); await typed(page, "@2,2");
  await expect.poll(async () => (await state(page)).view!.bundle.scene.obstacles.length).toBe(2);
  const id = (await state(page)).view!.bundle.scene.obstacles.at(-1)!.obstacle_id;
  const name = (await state(page)).entities.find((e) => e.id === id)!.name;
  await page.locator(".taskpanel .layer__name", { hasText: name }).click();
  // Record every height the design ever holds for this obstacle.
  await page.evaluate(async (oid) => {
    const { uiStore } = await import("/src/state/store.tsx");
    const first = uiStore.getState().state.view?.bundle.scene.obstacles.find((o: { obstacle_id: string }) => o.obstacle_id === oid)?.height_m;
    const seen: number[] = first === undefined ? [] : [first];
    (window as unknown as { __heights: number[] }).__heights = seen;
    uiStore.subscribe((s) => {
      const h = s.state.view?.bundle.scene.obstacles.find((o: { obstacle_id: string }) => o.obstacle_id === oid)?.height_m;
      if (h !== undefined && seen.at(-1) !== h) seen.push(h);
    });
  }, id);
  const heights = () => page.evaluate(() => (window as unknown as { __heights: number[] }).__heights);
  const height = page.locator(".inspectorpane").getByLabel("Height");
  const saved = async () => (await state(page)).view!.bundle.scene.obstacles.find((o) => o.obstacle_id === id)!.height_m;
  const start = await saved();

  await height.click(); await height.press("Control+a"); await height.pressSequentially("12", { delay: 80 });
  await page.waitForTimeout(400);
  expect(await saved()).toBe(start); // typing alone saves nothing
  await expect(height).toHaveValue("12");
  await height.press("Enter");
  await expect.poll(saved).toBe(12);
  expect(await heights()).toEqual([start, 12]); // never 1 on the way

  await height.press("Control+a"); await height.pressSequentially("99"); await height.press("Escape");
  await expect(height).toHaveValue("12");
  await height.press("Tab");
  expect(await saved()).toBe(12); // Esc cancelled; leaving the field afterwards saves nothing new

  await height.click(); await height.press("Control+a"); await height.pressSequentially("8"); await height.press("Tab");
  await expect.poll(saved).toBe(8); // leaving the field commits

  await height.click(); await height.press("ArrowUp");
  await expect.poll(saved).toBeCloseTo(8.1, 6); // the stepper commits at once

  await height.press("Control+a"); await height.press("Backspace"); await height.press("Enter");
  await expect(height).toHaveAttribute("aria-invalid", "true");
  await expect(height).toHaveValue("8.1");
  expect(await saved()).toBeCloseTo(8.1, 6); // an empty entry is not saved
  expect(await heights()).toEqual([start, 12, 8, expect.closeTo(8.1, 6)]);
});
