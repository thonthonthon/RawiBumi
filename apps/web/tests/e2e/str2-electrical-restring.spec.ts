import { expect, test, type Page } from "@playwright/test";

// STR2: the Electrical step's Apply re-strings an inverter by hand, like its own check and the Systems table: strings
// the new layout does not keep give back their modules (owner's beta: INV-02 from 14-module strings to 18/19 failed
// with "0 left in the pool").
async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}
async function idle(page: Page) { await expect.poll(async () => (await state(page)).busy).toBeNull(); }
const panel = (page: Page) => page.locator(".taskpanel");

test("a hand-edited layout that reuses the inverter's own modules applies", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("rawibumi.language", "en"));
  await page.goto("/");
  await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible();
  await page.keyboard.press("Alt+6"); await idle(page);
  const notation = panel(page).locator(".input--notation").first();
  const before = await notation.inputValue();
  const lengths = before.split(";").map((m) => m.split(",").map((v) => Number(v.trim())).filter((v) => v > 0));
  const total = lengths.flat().reduce((a, b) => a + b, 0);
  // Shorten the first string by one module and lengthen the last by one: the same modules, but lengths no existing
  // string has, so the inverter's old strings must give back their modules.
  const moved = lengths.map((m) => [...m]); const last = moved.findLastIndex((m) => m.length > 0);
  expect(last).toBeGreaterThan(0);
  moved[0][0] -= 1; moved[last][moved[last].length - 1] += 1;
  expect(moved.flat().reduce((a, b) => a + b, 0)).toBe(total);
  await notation.fill(moved.map((m) => m.join(",") || "0").join(" ; "));
  await expect(panel(page).getByRole("button", { name: "Apply layout" }).first()).toBeEnabled();
  await panel(page).getByRole("button", { name: "Apply layout" }).first().click(); await idle(page);
  const design = (await state(page)).view!.bundle.electrical_design;
  expect(design.strings.filter((s) => s.target_mppt_instance_id).map((s) => s.module_instance_ids.length).sort())
    .toEqual(moved.flat().sort());
  await expect(page.locator(".toasts")).not.toContainText("not enough unstrung modules");
});
