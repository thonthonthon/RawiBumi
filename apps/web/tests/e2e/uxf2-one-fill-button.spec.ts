import { expect, test, type Page } from "@playwright/test";

// UXF2 (U2-21): one fill button. On a roof that already has a layout, Apply fill asks to confirm the replacement; Cancel
// changes nothing; Confirm re-fills the existing field (no second field, no separate re-fill step).
async function state(page: Page) {
  return page.evaluate(async () => (await import("/src/state/store.tsx")).uiStore.getState().state);
}

test("Apply fill on an occupied roof confirms the replacement, then re-fills the existing field", async ({ page }) => {
  await page.goto("/"); await page.locator(".start__row").first().click();
  await expect(page.locator(".rail")).toBeVisible(); await page.keyboard.press("Alt+4");
  const p = page.locator(".taskpanel");
  await expect(p.locator("[data-occupied-roof]")).toContainText("Roof A already has 'Roof A array'. Apply fill replaces its layout");
  await expect(p.getByRole("button", { name: /^Re-fill Roof A array$/ })).toHaveCount(0); // no separate re-fill step
  const before = (await state(page)).view!.bundle.scene.pv_fields.map((f) => [f.pv_field_id, f.tilt_deg]);

  await p.getByLabel("Tilt").fill("15");
  const apply = p.getByRole("button", { name: "Apply fill", exact: true });
  await expect(apply).toBeEnabled();
  await apply.click();
  const dialog = page.getByRole("alertdialog", { name: "Preview re-fill", exact: true });
  await expect(dialog.locator("[data-replaces-layout]")).toContainText("This replaces the existing layout on this roof");
  await expect(dialog).toContainText("Modules: 76 →");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).toBeHidden();
  expect((await state(page)).view!.bundle.scene.pv_fields.map((f) => [f.pv_field_id, f.tilt_deg])).toEqual(before);

  await apply.click();
  await dialog.getByRole("button", { name: "Confirm re-fill", exact: true }).click();
  await expect(dialog).toBeHidden();
  const fields = (await state(page)).view!.bundle.scene.pv_fields;
  expect(fields.map((f) => f.pv_field_id)).toEqual(before.map(([id]) => id)); // the same field, replaced in place
  expect(fields.find((f) => f.pv_field_id === before[0][0])!.tilt_deg).toBe(15);
});
